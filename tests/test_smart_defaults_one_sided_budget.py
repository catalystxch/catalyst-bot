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


def _recommend(mode, *, xch_mojos, cat_mojos):
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
        patch("market_data_collector.analyze_market_data", return_value=_ANALYSIS),
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
            "tx_fees.get_suggested_transaction_fee", return_value={"available": False}
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
