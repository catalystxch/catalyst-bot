from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapDecision,
    CampaignStage,
)
import api_server  # noqa: F401 - initializes blueprint imports in app order
from blueprints.coin_prep import (
    bootstrap_coin_prep_requirements,
    bootstrap_coin_prep_worker_args,
)
from coin_prep_economics import build_exact_prep_economics
from offer_book_policy import derive_bootstrap_plan
from offer_manager import bootstrap_offer_specs


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ASSET_ID = "ef" * 32


def _campaign(
    *,
    subsidy=Decimal("0"),
    anchor=Decimal("0.01"),
    xch_budget=Decimal("1"),
    cat_budget=Decimal("0"),
):
    return BootstrapCampaign(
        network="mainnet",
        wallet_type="sage",
        wallet_fingerprint=736588221,
        wallet_id=2,
        asset_id=ASSET_ID,
        anchor_price=anchor,
        xch_budget=xch_budget,
        cat_budget=cat_budget,
        fee_budget_xch=Decimal("0.02"),
        subsidy_budget_xch=subsidy,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )


def _decision(campaign):
    return BootstrapDecision(
        authorized=True,
        stage=CampaignStage.BOOTSTRAP,
        deployment_fraction=Decimal("0.10"),
        anchor_price=campaign.anchor_price,
        minimum_price=campaign.minimum_price,
        maximum_price=campaign.maximum_price,
        allowed_sides=campaign.allowed_sides,
        cooldown_sides=frozenset(),
        stop_reason=None,
        reason_codes=("bootstrap_capacity_0.10",),
        cancellation_required=False,
        manual_restart_required=False,
        cancellation_fee_reserve_xch=Decimal("0.004"),
    )


def _balances(**overrides):
    values = {
        "xch_available": Decimal("1"),
        "cat_available": Decimal("0"),
        "fee_spent_xch": Decimal("0"),
        "subsidy_spent_xch": Decimal("0"),
        "network_fee_xch": Decimal("0"),
        "expected_cancel_requotes": 0,
        "minimum_profit_xch": Decimal("0.001"),
        "fee_coin_size_xch": Decimal("0.001"),
    }
    values.update(overrides)
    return values


def test_bootstrap_sell_levels_split_market_budget_into_atomic_mz_amounts():
    campaign = _campaign(xch_budget=Decimal("61"), cat_budget=Decimal("725000"))
    plan = derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        _balances(
            xch_available=Decimal("138"),
            cat_available=Decimal("1089357"),
            minimum_profit_xch=Decimal("0"),
        ),
        cat_decimals=3,
    )

    assert plan["authorized"] is True
    assert [level["cat_amount"] for level in plan["sides"]["sell"]["levels"]] == [
        Decimal("24166.667"),
        Decimal("24166.667"),
        Decimal("24166.666"),
    ]
    assert sum(
        level["cat_amount"] for level in plan["sides"]["sell"]["levels"]
    ) == Decimal("72500")
    worker_args = bootstrap_coin_prep_worker_args(
        plan, replacement_waves={"buy": 10, "sell": 10}
    )
    exact = build_exact_prep_economics(
        configuration={
            "CAT_DECIMALS": 3,
            "LIQUIDITY_MODE": "two_sided",
            "XCH_RESERVE": Decimal("0"),
            "CAT_RESERVE": Decimal("0"),
        },
        worker_args=worker_args,
        campaign_revision=0,
    )
    assert (
        sum(output.amount_mojos for output in exact["targets"] if output.asset == "cat")
        == 725_000_000
    )


def test_below_floor_quote_requires_the_exact_separate_subsidy_shortfall():
    unsubsidized = _campaign()
    blocked = derive_bootstrap_plan(
        unsubsidized,
        _decision(unsubsidized),
        _balances(),
    )
    assert blocked["authorized"] is False
    assert blocked["reason_codes"] == ("bootstrap_profit_floor_unfunded",)

    subsidized = _campaign(subsidy=Decimal("0.0004"))
    funded = derive_bootstrap_plan(
        subsidized,
        _decision(subsidized),
        _balances(),
    )
    assert funded["authorized"] is True
    assert funded["subsidy_used_xch"] > Decimal("0")
    assert funded["subsidy_used_xch"] <= subsidized.subsidy_budget_xch
    assert any(level["subsidy_xch"] > 0 for level in funded["sides"]["buy"]["levels"])

    too_small = _campaign(
        subsidy=funded["subsidy_used_xch"] - Decimal("0.000000000001")
    )
    rejected = derive_bootstrap_plan(
        too_small,
        _decision(too_small),
        _balances(),
    )
    assert rejected["authorized"] is False


def test_coin_prep_projection_contains_only_staged_purpose_separated_outputs():
    campaign = _campaign(subsidy=Decimal("0.0004"))
    plan = derive_bootstrap_plan(campaign, _decision(campaign), _balances())

    prep = bootstrap_coin_prep_requirements(plan)

    assert prep["campaign_asset_id"] == ASSET_ID
    assert prep["xch_offer_coins"] == [
        {
            "purpose": "bootstrap_buy",
            "level": level["level"],
            "amount_xch": level["xch_amount"],
        }
        for level in plan["sides"]["buy"]["levels"]
    ]
    assert prep["cat_offer_coins"] == []
    assert all(coin["purpose"] == "bootstrap_fee" for coin in prep["fee_coins"])
    assert prep["excluded_xch"] == {
        "campaign_undeployed_xch": Decimal("0.9"),
        "cancellation_fee_reserve_xch": Decimal("0.004"),
        "subsidy_remaining_xch": campaign.subsidy_budget_xch - plan["subsidy_used_xch"],
    }


def test_manual_zero_fee_still_prepares_configured_protected_fee_pool():
    campaign = _campaign(xch_budget=Decimal("61"), cat_budget=Decimal("725000"))
    plan = derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        _balances(
            xch_available=Decimal("138"),
            cat_available=Decimal("1089357"),
            minimum_profit_xch=Decimal("0"),
            network_fee_xch=Decimal("0"),
            fee_pool_enabled=True,
        ),
        cat_decimals=3,
    )

    assert plan["authorized"] is True
    assert plan["creation_fee_required_xch"] == Decimal("0")
    assert len(plan["coin_prep"]["fee_coins"]) == 6
    assert all(
        coin["amount_xch"] == Decimal("0.001")
        for coin in plan["coin_prep"]["fee_coins"]
    )
    worker_args = bootstrap_coin_prep_worker_args(plan)
    assert "fees=0.001" in worker_args["buy_tier_sizes"]
    assert "fees=6" in worker_args["tier_counts_xch"]

    without_pool = derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        _balances(
            xch_available=Decimal("138"),
            cat_available=Decimal("1089357"),
            minimum_profit_xch=Decimal("0"),
            network_fee_xch=Decimal("0"),
            fee_pool_enabled=False,
        ),
        cat_decimals=3,
    )
    assert without_pool["coin_prep"]["fee_coins"] == []


def test_offer_specs_preserve_exact_bootstrap_level_purpose_and_amounts():
    campaign = _campaign(subsidy=Decimal("0.0004"))
    plan = derive_bootstrap_plan(campaign, _decision(campaign), _balances())

    specs = bootstrap_offer_specs(plan)

    assert len(specs) == 3
    assert [spec["level"] for spec in specs] == ["near", "middle", "far"]
    assert all(spec["purpose"] == "bootstrap_market" for spec in specs)
    assert all(spec["side"] == "buy" for spec in specs)
    assert [spec["price"] for spec in specs] == [
        level["price"] for level in plan["sides"]["buy"]["levels"]
    ]
    assert [spec["xch_amount"] for spec in specs] == [
        level["xch_amount"] for level in plan["sides"]["buy"]["levels"]
    ]
    assert sum(spec["subsidy_xch"] for spec in specs) == plan["subsidy_used_xch"]


def test_trusted_bounds_shift_each_bootstrap_ladder_without_collapsing_tiers():
    campaign = _campaign(
        anchor=Decimal("0.000075"),
        xch_budget=Decimal("1"),
        cat_budget=Decimal("150000"),
    )
    plan = derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        _balances(
            cat_available=Decimal("150000"),
            minimum_profit_xch=Decimal("0"),
            trusted_bid=Decimal("0.00004"),
            trusted_ask=Decimal("0.00011"),
        ),
    )

    buy_prices = [level["price"] for level in plan["sides"]["buy"]["levels"]]
    sell_prices = [level["price"] for level in plan["sides"]["sell"]["levels"]]

    assert plan["authorized"] is True
    assert buy_prices[0] == Decimal("0.00004")
    assert sell_prices[0] == Decimal("0.00011")
    assert buy_prices[0] > buy_prices[1] > buy_prices[2]
    assert sell_prices[0] < sell_prices[1] < sell_prices[2]
    assert all(campaign.minimum_price <= price for price in buy_prices)
    assert all(price <= campaign.maximum_price for price in sell_prices)


def test_trusted_boundary_with_no_room_for_three_levels_pauses_that_side():
    campaign = _campaign(
        anchor=Decimal("0.000075"),
        xch_budget=Decimal("0"),
        cat_budget=Decimal("150000"),
    )
    plan = derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        _balances(
            cat_available=Decimal("150000"),
            minimum_profit_xch=Decimal("0"),
            trusted_ask=campaign.maximum_price,
        ),
    )

    assert plan["sides"]["sell"] == {"paused": True, "levels": []}
    assert "sell_trusted_range_insufficient_corridor" in plan["reason_codes"]
