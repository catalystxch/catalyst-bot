from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapDecision,
    CampaignStage,
)
import api_server  # noqa: F401 - initializes blueprint imports in app order
from blueprints.coin_prep import bootstrap_coin_prep_requirements
from offer_book_policy import derive_bootstrap_plan
from offer_manager import bootstrap_offer_specs


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ASSET_ID = "ef" * 32


def _campaign(*, subsidy=Decimal("0")):
    return BootstrapCampaign(
        network="mainnet",
        wallet_type="sage",
        wallet_fingerprint=736588221,
        wallet_id=2,
        asset_id=ASSET_ID,
        anchor_price=Decimal("0.01"),
        xch_budget=Decimal("1"),
        cat_budget=Decimal("0"),
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
