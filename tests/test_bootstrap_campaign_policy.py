from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapEvidence,
    CampaignMode,
    CampaignSide,
    CampaignStage,
    derive_anchor_from_valuation,
    evaluate_bootstrap_campaign,
)


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ASSET_ID = "ab" * 32


def make_campaign(**overrides):
    values = {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 736588221,
        "wallet_id": 2,
        "asset_id": ASSET_ID,
        "anchor_price": Decimal("0.01"),
        "xch_budget": Decimal("1"),
        "cat_budget": Decimal("100"),
        "fee_budget_xch": Decimal("0.05"),
        "subsidy_budget_xch": Decimal("0"),
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=7),
    }
    values.update(overrides)
    return BootstrapCampaign(**values)


def test_campaign_defaults_isolate_budgets_and_bound_the_price_corridor():
    campaign = make_campaign()

    assert campaign.mode is CampaignMode.BOOTSTRAP
    assert campaign.minimum_price == Decimal("0.005")
    assert campaign.maximum_price == Decimal("0.02")
    assert campaign.initial_deployment_fraction == Decimal("0.10")
    assert campaign.subsidy_budget_xch == Decimal("0")
    assert campaign.allowed_sides == frozenset({CampaignSide.BUY, CampaignSide.SELL})


def test_initial_decision_authorizes_only_ten_percent_of_funded_sides():
    decision = evaluate_bootstrap_campaign(
        make_campaign(cat_budget=Decimal("0")),
        BootstrapEvidence(),
        now=NOW,
    )

    assert decision.authorized is True
    assert decision.stage is CampaignStage.BOOTSTRAP
    assert decision.deployment_fraction == Decimal("0.10")
    assert decision.allowed_sides == frozenset({CampaignSide.BUY})
    assert decision.minimum_price == Decimal("0.005")
    assert decision.maximum_price == Decimal("0.02")


def test_anchor_from_supply_and_xch_valuation_is_exact():
    assert derive_anchor_from_valuation(
        circulating_supply=Decimal("1000000"),
        implied_valuation_xch=Decimal("250"),
    ) == Decimal("0.00025")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"asset_id": "ab" * 31}, "asset ID"),
        ({"asset_id": "z" * 64}, "asset ID"),
        ({"network": "mainnet11"}, "network"),
        ({"wallet_type": "chia"}, "wallet type"),
        ({"wallet_fingerprint": 0}, "fingerprint"),
        ({"wallet_id": 0}, "wallet ID"),
        ({"anchor_price": Decimal("0")}, "anchor"),
        ({"minimum_price": Decimal("0")}, "minimum price"),
        ({"minimum_price": Decimal("0.02")}, "corridor"),
        ({"maximum_price": Decimal("0.005")}, "corridor"),
        ({"xch_budget": Decimal("-1")}, "XCH budget"),
        ({"cat_budget": Decimal("-1")}, "CAT budget"),
        ({"fee_budget_xch": Decimal("-1")}, "fee budget"),
        ({"subsidy_budget_xch": Decimal("-1")}, "subsidy budget"),
        (
            {"xch_budget": Decimal("0"), "cat_budget": Decimal("0")},
            "funded side",
        ),
        ({"created_at": datetime(2026, 9, 12)}, "UTC"),
        ({"expires_at": NOW + timedelta(days=7, seconds=1)}, "seven days"),
    ],
)
def test_invalid_campaign_authority_is_rejected(overrides, message):
    with pytest.raises((TypeError, ValueError), match=message):
        make_campaign(**overrides)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("anchor_price", 0.01),
        ("minimum_price", 0.005),
        ("maximum_price", 0.02),
        ("xch_budget", 1.0),
        ("cat_budget", 100.0),
        ("fee_budget_xch", 0.05),
        ("subsidy_budget_xch", 0.0),
    ],
)
def test_float_monetary_authority_is_rejected(field, value):
    with pytest.raises(TypeError, match="Decimal"):
        make_campaign(**{field: value})


@pytest.mark.parametrize(
    ("supply", "valuation", "message"),
    [
        (Decimal("0"), Decimal("1"), "circulating supply"),
        (Decimal("1"), Decimal("0"), "valuation"),
        (1.0, Decimal("1"), "Decimal"),
        (Decimal("1"), 1.0, "Decimal"),
    ],
)
def test_invalid_valuation_anchor_inputs_are_rejected(supply, valuation, message):
    with pytest.raises((TypeError, ValueError), match=message):
        derive_anchor_from_valuation(
            circulating_supply=supply,
            implied_valuation_xch=valuation,
        )
