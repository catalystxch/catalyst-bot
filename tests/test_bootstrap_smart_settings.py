from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapDecision,
    CampaignSide,
    CampaignStage,
)
import api_server  # noqa: F401 - initializes blueprint imports in app order
from offer_book_policy import derive_bootstrap_plan
from blueprints.smart_defaults import derive_bootstrap_smart_settings


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ASSET_ID = "cd" * 32


def _campaign(**overrides):
    values = {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 736588221,
        "wallet_id": 2,
        "asset_id": ASSET_ID,
        "anchor_price": Decimal("0.01"),
        "xch_budget": Decimal("1.2"),
        "cat_budget": Decimal("120"),
        "fee_budget_xch": Decimal("0.03"),
        "subsidy_budget_xch": Decimal("0"),
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=7),
    }
    values.update(overrides)
    return BootstrapCampaign(**values)


def _decision(campaign, **overrides):
    values = {
        "authorized": True,
        "stage": CampaignStage.BOOTSTRAP,
        "deployment_fraction": Decimal("0.10"),
        "anchor_price": campaign.anchor_price,
        "minimum_price": campaign.minimum_price,
        "maximum_price": campaign.maximum_price,
        "allowed_sides": campaign.allowed_sides,
        "cooldown_sides": frozenset(),
        "stop_reason": None,
        "reason_codes": ("bootstrap_capacity_0.10",),
        "cancellation_required": False,
        "manual_restart_required": False,
        "cancellation_fee_reserve_xch": campaign.fee_budget_xch * Decimal("0.20"),
    }
    values.update(overrides)
    return BootstrapDecision(**values)


def _balances(**overrides):
    values = {
        "xch_available": Decimal("1.2"),
        "cat_available": Decimal("120"),
        "fee_spent_xch": Decimal("0"),
        "subsidy_spent_xch": Decimal("0"),
        "network_fee_xch": Decimal("0.00001"),
        "expected_cancel_requotes": 1,
        "minimum_profit_xch": Decimal("0"),
        "fee_coin_size_xch": Decimal("0.001"),
    }
    values.update(overrides)
    return values


def test_initial_plan_has_three_monotonic_levels_inside_exact_budget_and_corridor():
    campaign = _campaign()
    plan = derive_bootstrap_plan(campaign, _decision(campaign), _balances())

    assert plan["authorized"] is True
    buys = plan["sides"]["buy"]["levels"]
    sells = plan["sides"]["sell"]["levels"]
    assert len(buys) == len(sells) == 3
    assert [level["price"] for level in buys] == sorted(
        (level["price"] for level in buys), reverse=True
    )
    assert [level["price"] for level in sells] == sorted(
        level["price"] for level in sells
    )
    assert all(
        campaign.minimum_price <= level["price"] <= campaign.maximum_price
        for level in (*buys, *sells)
    )
    assert sum(level["xch_amount"] for level in buys) == Decimal("0.12")
    assert sum(level["cat_amount"] for level in sells) == Decimal("12")
    assert sum(level["xch_amount"] for level in buys) <= (
        campaign.xch_budget * Decimal("0.10")
    )
    assert sum(level["cat_amount"] for level in sells) <= (
        campaign.cat_budget * Decimal("0.10")
    )


def test_buy_only_plan_has_no_cat_offer_or_cat_coin_prep_outputs():
    campaign = _campaign(cat_budget=Decimal("0"))
    plan = derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        _balances(cat_available=Decimal("999999")),
    )

    assert plan["mode"] == "BUY_ONLY"
    assert plan["sides"]["sell"]["levels"] == []
    assert plan["coin_prep"]["cat_offer_coins"] == []
    assert len(plan["coin_prep"]["xch_offer_coins"]) == 3


def test_zero_available_inventory_pauses_only_the_depleted_side():
    campaign = _campaign()
    plan = derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        _balances(xch_available=Decimal("0")),
    )

    assert plan["sides"]["buy"]["paused"] is True
    assert plan["sides"]["buy"]["levels"] == []
    assert plan["sides"]["sell"]["paused"] is False
    assert len(plan["sides"]["sell"]["levels"]) == 3
    assert "buy_inventory_depleted" in plan["reason_codes"]


def test_creation_fee_plan_never_consumes_cancellation_reserve():
    campaign = _campaign(fee_budget_xch=Decimal("0.01"))
    plan = derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        _balances(
            fee_spent_xch=Decimal("0.0079"),
            network_fee_xch=Decimal("0.00001"),
            expected_cancel_requotes=0,
        ),
    )

    assert plan["cancellation_fee_reserve_xch"] == Decimal("0.002")
    assert plan["creation_fee_available_xch"] == Decimal("0.0001")
    assert plan["creation_fee_required_xch"] <= Decimal("0.0001")
    assert plan["fee_budget_after_plan_xch"] >= Decimal("0.002")


def test_smart_settings_uses_bootstrap_authority_instead_of_follow_capacity():
    campaign = _campaign()

    plan = derive_bootstrap_smart_settings(
        campaign=campaign,
        decision=_decision(campaign),
        balances=_balances(),
    )

    assert plan["authorized"] is True
    assert plan["market_mode"] == "bootstrap"
    assert plan["follow_capacity_fraction"] == Decimal("0")
    assert len(plan["sides"]["buy"]["levels"]) == 3
    assert len(plan["sides"]["sell"]["levels"]) == 3
