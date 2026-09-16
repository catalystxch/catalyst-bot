from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapEvidence,
    CampaignMode,
    CampaignSide,
    CampaignStage,
    CampaignStopReason,
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


@pytest.mark.parametrize(
    ("fills", "clusters", "stable_minutes", "fraction", "stage"),
    [
        (0, 0, 0, "0.10", CampaignStage.BOOTSTRAP),
        (2, 2, 0, "0.25", CampaignStage.DISCOVERY_25),
        (6, 3, 30, "0.50", CampaignStage.DISCOVERY_50),
        (12, 5, 120, "1.00", CampaignStage.ESTABLISHED),
    ],
)
def test_capacity_requires_approved_fill_cluster_and_depth_thresholds(
    fills,
    clusters,
    stable_minutes,
    fraction,
    stage,
):
    evidence = BootstrapEvidence(
        confirmed_fills=fills,
        settlement_clusters=clusters,
        independent_depth_sides=frozenset({CampaignSide.BUY, CampaignSide.SELL}),
        stable_since=NOW - timedelta(minutes=stable_minutes),
    )

    decision = evaluate_bootstrap_campaign(make_campaign(), evidence, now=NOW)

    assert decision.deployment_fraction == Decimal(fraction)
    assert decision.stage is stage


@pytest.mark.parametrize(
    "evidence_kwargs",
    [
        {
            "confirmed_fills": 2,
            "settlement_clusters": 1,
            "independent_depth_sides": frozenset({CampaignSide.BUY, CampaignSide.SELL}),
            "stable_since": NOW,
        },
        {
            "confirmed_fills": 2,
            "settlement_clusters": 2,
            "independent_depth_sides": frozenset({CampaignSide.BUY}),
            "stable_since": NOW,
        },
        {
            "confirmed_fills": 6,
            "settlement_clusters": 3,
            "independent_depth_sides": frozenset({CampaignSide.BUY, CampaignSide.SELL}),
            "stable_since": NOW - timedelta(minutes=29, seconds=59),
        },
    ],
)
def test_capacity_does_not_advance_when_one_required_threshold_is_missing(
    evidence_kwargs,
):
    decision = evaluate_bootstrap_campaign(
        make_campaign(), BootstrapEvidence(**evidence_kwargs), now=NOW
    )

    assert decision.deployment_fraction < Decimal("0.50")


def test_suspected_linked_activity_cannot_unlock_capacity():
    decision = evaluate_bootstrap_campaign(
        make_campaign(),
        BootstrapEvidence(
            confirmed_fills=12,
            settlement_clusters=5,
            independent_depth_sides=frozenset({CampaignSide.BUY, CampaignSide.SELL}),
            stable_since=NOW - timedelta(hours=3),
            suspected_linked_activity=True,
        ),
        now=NOW,
    )

    assert decision.deployment_fraction == Decimal("0.10")
    assert "linked_activity_excluded" in decision.reason_codes


def test_adverse_fill_cools_only_affected_side_for_five_minutes():
    campaign = make_campaign()
    before_boundary = evaluate_bootstrap_campaign(
        campaign,
        BootstrapEvidence(
            adverse_fill_times=((CampaignSide.SELL, NOW - timedelta(minutes=4)),)
        ),
        now=NOW,
    )
    at_boundary = evaluate_bootstrap_campaign(
        campaign,
        BootstrapEvidence(
            adverse_fill_times=((CampaignSide.SELL, NOW - timedelta(minutes=5)),)
        ),
        now=NOW,
    )

    assert before_boundary.cooldown_sides == frozenset({CampaignSide.SELL})
    assert at_boundary.cooldown_sides == frozenset()


@pytest.mark.parametrize(
    ("proposed", "hour_ago", "day_ago", "expected"),
    [
        ("0.02", "0.01", "0.01", "0.0105"),
        ("0.001", "0.01", "0.01", "0.0095"),
        ("0.0125", "0.012", "0.01", "0.012"),
    ],
)
def test_anchor_movement_is_capped_hourly_daily_and_by_corridor(
    proposed,
    hour_ago,
    day_ago,
    expected,
):
    decision = evaluate_bootstrap_campaign(
        make_campaign(),
        BootstrapEvidence(
            current_anchor_price=Decimal(hour_ago),
            proposed_anchor_price=Decimal(proposed),
            anchor_price_one_hour_ago=Decimal(hour_ago),
            anchor_price_one_day_ago=Decimal(day_ago),
        ),
        now=NOW,
    )

    assert decision.anchor_price == Decimal(expected)
    assert "anchor_movement_capped" in decision.reason_codes


def test_seven_day_expiry_authorizes_only_cancellation():
    decision = evaluate_bootstrap_campaign(
        make_campaign(),
        BootstrapEvidence(),
        now=NOW + timedelta(days=7),
    )

    assert decision.authorized is False
    assert decision.deployment_fraction == Decimal("0")
    assert decision.stop_reason is CampaignStopReason.EXPIRED
    assert decision.cancellation_required is True
    assert decision.manual_restart_required is True


def test_five_percent_campaign_loss_requires_manual_restart():
    decision = evaluate_bootstrap_campaign(
        make_campaign(),
        BootstrapEvidence(
            realized_loss_xch=Decimal("0.05"),
            marked_inventory_loss_xch=Decimal("0.05"),
        ),
        now=NOW,
    )

    assert decision.authorized is False
    assert decision.stop_reason is CampaignStopReason.LOSS_LIMIT
    assert decision.cancellation_required is True
    assert decision.manual_restart_required is True


def test_fee_eighty_percent_stops_creation_and_preserves_cancellation_reserve():
    decision = evaluate_bootstrap_campaign(
        make_campaign(fee_budget_xch=Decimal("0.05")),
        BootstrapEvidence(fee_spent_xch=Decimal("0.04")),
        now=NOW,
    )

    assert decision.authorized is False
    assert decision.stop_reason is CampaignStopReason.FEE_RESERVE
    assert decision.cancellation_required is True
    assert decision.manual_restart_required is False
    assert decision.cancellation_fee_reserve_xch == Decimal("0.01")


@pytest.mark.parametrize(
    ("evidence_kwargs", "message"),
    [
        ({"confirmed_fills": -1}, "confirmed fills"),
        ({"settlement_clusters": -1}, "settlement clusters"),
        ({"fee_spent_xch": -1.0}, "Decimal"),
        ({"realized_loss_xch": Decimal("-1")}, "realized loss"),
        (
            {"stable_since": datetime(2026, 9, 12, 11, 0)},
            "UTC",
        ),
        (
            {"adverse_fill_times": ((CampaignSide.BUY, datetime(2026, 9, 12)),)},
            "UTC",
        ),
        ({"independent_depth_sides": frozenset({"buy"})}, "campaign side"),
        ({"current_anchor_price": Decimal("0")}, "current anchor"),
    ],
)
def test_invalid_evidence_cannot_change_campaign_authority(evidence_kwargs, message):
    with pytest.raises((TypeError, ValueError), match=message):
        BootstrapEvidence(**evidence_kwargs)
