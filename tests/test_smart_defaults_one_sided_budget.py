"""Smart Settings must size the active side from its own spendable asset."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import api_server
from blueprints import smart_defaults


_MARKET = {
    "dexie_ticker": {
        "price": 0.0001,
        "volume_30d": 10,
        "high_30d": 0.00012,
        "low_30d": 0.00009,
    },
    "dexie_trades": {
        "total_count": 100,
        "volume_trend": "stable",
        "trades": [{"price": 0.0001, "xch_amount": 1}],
    },
    "tibet_pool": {},
    "tibet_quote": {},
    "spacescan": {},
    "internal_db": {},
}
_ANALYSIS = {
    "volatility": {
        "regime": "normal",
        "range_30d_pct": 10,
        "range_90d_pct": 20,
        "max_single_move_pct": 3,
        "confidence": "high",
        "std_dev_pct": 1,
        "quiet_phase": False,
    },
    "liquidity": {
        "fills_per_day": 5,
        "daily_volume_xch": 10,
        "pool_depth_xch": 200,
        "level": "deep",
        "volume_trend": "stable",
    },
    "token_health": {
        "risk_level": "healthy",
        "activity_level": "active",
        "holder_count": 1000,
    },
    "bot_performance": {"has_history": False},
    "data_quality": {"score": 100, "quality": "excellent"},
}
_BOOK = {
    "has_data": True,
    "api_ok": True,
    "num_buy_offers": 10,
    "num_sell_offers": 10,
    "competitor_spread_bps": 500,
    "best_bid": 0.000096,
    "best_ask": 0.000104,
}
_CONFIDENCE = SimpleNamespace(
    state="GREEN",
    data_valid=True,
    provider_redundancy=2,
    follow_capacity_fraction=Decimal("1"),
    market_stage="FOLLOW",
    trusted_midpoint=Decimal("0.0001"),
    trusted_bid=Decimal("0.000096"),
    trusted_ask=Decimal("0.000104"),
    independent_bid_depth_mojos=10**15,
    independent_ask_depth_mojos=10**15,
    manipulation_score=0,
    reason_codes=(),
    evidence_digests=("a" * 64, "b" * 64),
    source_health={"dexie": "valid", "splash": "valid"},
)


def _recommend(
    mode,
    *,
    xch_mojos,
    cat_mojos,
    fee_mojos=None,
    target_offers=None,
    fills_per_day=None,
    shutdown_fee_mojos=None,
):
    analysis = (
        _ANALYSIS
        if fills_per_day is None
        else {
            **_ANALYSIS,
            "liquidity": {**_ANALYSIS["liquidity"], "fills_per_day": fills_per_day},
        }
    )

    def balance(wallet_id):
        amount = xch_mojos if wallet_id == 1 else cat_mojos
        return {
            "success": True,
            "wallet_balance": {
                "unconfirmed_wallet_balance": amount,
                "confirmed_wallet_balance": amount,
                "spendable_balance": amount,
                "pending_coin_removal_count": 0,
            },
        }

    with (
        patch("wallet.get_wallet_balance", side_effect=balance),
        patch("market_data_collector.collect_all_market_data", return_value=_MARKET),
        patch("market_data_collector.analyze_market_data", return_value=analysis),
        patch.object(
            smart_defaults, "_fetch_dexie_orderbook_standalone", return_value=_BOOK
        ),
        patch.object(
            smart_defaults,
            "_smart_market_own_offer_identities",
            return_value=frozenset(),
        ),
        patch.object(
            smart_defaults, "_derive_smart_market_confidence", return_value=_CONFIDENCE
        ),
        patch.object(
            smart_defaults,
            "_smart_dbx_defaults",
            return_value={
                "dbx_max_spread_bps": 500,
                "pair_incentivized": False,
                "dbx_buy_incentive": None,
                "dbx_sell_incentive": None,
            },
        ),
        patch(
            "tx_fees.get_suggested_transaction_fee",
            side_effect=lambda *, target_seconds, cost: (
                {"available": True, "fee_mojos": shutdown_fee_mojos}
                if cost == 11_000_000_000 and shutdown_fee_mojos is not None
                else {"available": True, "fee_mojos": fee_mojos}
                if fee_mojos is not None
                else {"available": False}
            ),
        ),
    ):
        with api_server.app.test_request_context("/api/smart-defaults"):
            response = smart_defaults._calculate_smart_defaults(
                xch_reserve=0,
                cat_reserve=0,
                risk_profile="balanced",
                liquidity_mode=mode,
                asset_id="e" * 64,
                cat_wallet_id=2,
                cat_decimals=3,
                cat_ticker_id="TST_XCH",
                cat_name="TestCAT",
                target_offers_per_side=target_offers,
            )
    assert response.status_code == 200
    return response.get_json()


def _active_ladder_xch(plan, side):
    headroom = Decimal("1") + Decimal(str(plan["coin_prep_headroom_pct"])) / 100
    return sum(
        (
            Decimal(str(plan.get(f"{side}_{tier}_size_xch") or 0))
            * (
                (plan.get(f"{side}_{tier}_tier_count") or 0)
                + (plan.get(f"{side}_{tier}_tier_spare_count") or 0)
            )
            * headroom
        )
        for tier in ("inner", "mid", "outer", "extreme")
    )


def test_buy_only_tiny_cat_balance_does_not_zero_xch_ladder():
    plan = _recommend("buy_only", xch_mojos=10_000_000_000_000, cat_mojos=1_000)
    assert plan["max_active_buy"] > 0
    assert Decimal(str(plan["buy_inner_size_xch"] or 0)) >= Decimal("0.005")
    assert plan["max_active_sell"] == 0
    fee_pool = Decimal(str(plan["fee_coin_size_xch"])) * plan["fee_prep_count"]
    assert _active_ladder_xch(plan, "buy") + fee_pool + Decimal(
        str(plan["topup_pool_xch"])
    ) <= Decimal("10")


def test_requested_24_per_side_resizes_the_ladder_from_available_balances():
    plan = _recommend(
        "two_sided",
        xch_mojos=127_908_416_089_710,
        cat_mojos=1_235_383_474,
        target_offers=24,
    )

    assert plan["max_active_buy"] == 24
    assert plan["max_active_sell"] == 24
    assert (
        sum(
            plan[f"buy_{tier}_tier_count"]
            for tier in ("inner", "mid", "outer", "extreme")
        )
        == 24
    )
    assert (
        sum(
            plan[f"sell_{tier}_tier_count"]
            for tier in ("inner", "mid", "outer", "extreme")
        )
        == 24
    )
    fee_pool = Decimal(str(plan["fee_coin_size_xch"])) * plan["fee_prep_count"]
    assert _active_ladder_xch(plan, "buy") + fee_pool + Decimal(
        str(plan["topup_pool_xch"])
    ) <= Decimal("127.908416089710")


def test_requested_100_per_side_is_not_limited_by_market_default_count():
    plan = _recommend(
        "two_sided",
        xch_mojos=10_000_000_000_000_000,
        cat_mojos=100_000_000_000,
        target_offers=100,
    )

    assert plan["max_active_buy"] == 100
    assert plan["max_active_sell"] == 100


def test_thin_market_target_does_not_lose_a_slot_to_capacity_rounding():
    plan = _recommend(
        "two_sided",
        xch_mojos=127_908_416_089_710,
        cat_mojos=1_235_383_474,
        target_offers=24,
        fills_per_day=0.87,
    )

    assert plan["max_active_buy"] == 24
    assert plan["max_active_sell"] == 24
    assert plan["_capital_plan"]["n_final"] == 24
    fee_pool = Decimal(str(plan["fee_coin_size_xch"])) * plan["fee_prep_count"]
    assert _active_ladder_xch(plan, "buy") + fee_pool + Decimal(
        str(plan["topup_pool_xch"])
    ) <= Decimal("127.908416089710")
    assert _active_ladder_xch(plan, "sell") / Decimal(
        str(plan["smart_mid_price"])
    ) + Decimal(str(plan["topup_pool_cat"])) <= Decimal("1235383.474")


def test_smart_fee_coin_covers_full_book_shutdown_quote():
    plan = _recommend(
        "two_sided",
        xch_mojos=127_908_416_089_710,
        cat_mojos=1_235_383_474,
        target_offers=24,
        fills_per_day=0.87,
        fee_mojos=13_079_100,
        shutdown_fee_mojos=2_326_137_840,
    )

    assert plan["max_active_buy"] == 24
    assert plan["max_active_sell"] == 24
    assert Decimal(str(plan["fee_coin_size_xch"])) >= Decimal("0.004652275680")
    assert Decimal(str(plan["fee_coin_size_xch"])) * plan["fee_prep_count"] <= 1


def test_sell_only_tiny_fee_funded_xch_balance_does_not_shrink_cat_ladder():
    plan = _recommend("sell_only", xch_mojos=200_000_000_000, cat_mojos=1_000_000_000)
    assert plan["max_active_sell"] >= 20
    assert Decimal(str(plan["sell_inner_size_xch"] or 0)) >= Decimal("0.1")
    assert plan["max_active_buy"] == 0
    assert plan["fee_prep_count"] > 0
    fee_pool = Decimal(str(plan["fee_coin_size_xch"])) * plan["fee_prep_count"]
    assert Decimal("0") < fee_pool < Decimal("0.2")
    assert _active_ladder_xch(plan, "sell") / Decimal(
        str(plan["smart_mid_price"])
    ) + Decimal(str(plan["topup_pool_cat"])) <= Decimal("1000000")


def test_fee_inventory_can_use_more_than_three_percent_after_buy_principal_reserve():
    plan = _recommend(
        "two_sided",
        xch_mojos=10_000_000_000_000,
        cat_mojos=1_000_000_000_000_000,
        fee_mojos=1_000_000_000,
    )

    fee_pool = Decimal(str(plan["fee_coin_size_xch"])) * plan["fee_prep_count"]
    assert fee_pool > Decimal("0.3")  # old 3% cap on a 10 XCH wallet
    assert _active_ladder_xch(plan, "buy") + fee_pool + Decimal(
        str(plan["topup_pool_xch"])
    ) <= Decimal("10"), plan["_capital_plan"]


def test_final_fee_reconciliation_shrinks_weekly_inventory_to_safe_remainder():
    plan = {
        "coin_prep_headroom_pct": 0,
        "buy_inner_size_xch": 0.005,
        "buy_inner_tier_count": 10,
        "buy_inner_tier_spare_count": 0,
        "fee_coin_size_xch": 0.001,
        "fee_prep_count": 100,
        "topup_pool_xch": 0.02,
        "_capital_plan": {},
    }

    smart_defaults._reconcile_smart_fee_inventory(plan, Decimal("0.1"))

    assert plan["fee_prep_count"] == 30
    assert Decimal("0.005") * plan["buy_inner_tier_count"] + Decimal(
        str(plan["topup_pool_xch"])
    ) + Decimal(str(plan["fee_coin_size_xch"])) * plan["fee_prep_count"] <= Decimal(
        "0.1"
    )
