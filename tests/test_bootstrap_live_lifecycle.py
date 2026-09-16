from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapEvidence,
    evaluate_bootstrap_campaign,
)
from bot_loop import plan_bootstrap_runtime_transition
from fill_tracker import derive_bootstrap_settlement_evidence
from offer_book_policy import derive_bootstrap_plan
from offer_manager import (
    bootstrap_offer_specs,
    require_active_bootstrap_intent_authority,
)
from offer_reconciliation import plan_bootstrap_restart_recovery


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ASSET_ID = "12" * 32
CAMPAIGN_ID = "34" * 32


def _campaign():
    return BootstrapCampaign(
        network="mainnet",
        wallet_type="sage",
        wallet_fingerprint=736588221,
        wallet_id=2,
        asset_id=ASSET_ID,
        anchor_price=Decimal("0.01"),
        xch_budget=Decimal("1"),
        cat_budget=Decimal("100"),
        fee_budget_xch=Decimal("0.02"),
        subsidy_budget_xch=Decimal("0"),
        created_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=6),
    )


def _record(campaign, **overrides):
    record = {
        **campaign.to_record(),
        "campaign_id": CAMPAIGN_ID,
        "revision": 5,
        "status": "active",
        "stage": "bootstrap",
        "stop_reason": None,
    }
    record.update(overrides)
    return record


def _decision(campaign, evidence=None):
    return evaluate_bootstrap_campaign(
        campaign,
        evidence or BootstrapEvidence(),
        now=NOW,
    )


def _plan(campaign):
    return derive_bootstrap_plan(
        campaign,
        _decision(campaign),
        {
            "xch_available": Decimal("1"),
            "cat_available": Decimal("100"),
            "fee_spent_xch": Decimal("0"),
            "subsidy_spent_xch": Decimal("0"),
            "network_fee_xch": Decimal("0"),
            "expected_cancel_requotes": 0,
            "minimum_profit_xch": Decimal("0"),
            "fee_coin_size_xch": Decimal("0.001"),
        },
    )


def test_every_bootstrap_offer_spec_carries_campaign_and_budget_revision():
    campaign = _campaign()
    specs = bootstrap_offer_specs(
        _plan(campaign),
        campaign_authority=_record(campaign),
    )

    assert len(specs) == 6
    assert all(spec["campaign_id"] == CAMPAIGN_ID for spec in specs)
    assert all(spec["campaign_revision"] == 5 for spec in specs)
    assert all(
        spec["purpose"] == f"bootstrap:{CAMPAIGN_ID}:revision:5" for spec in specs
    )


def test_offer_journal_boundary_rechecks_active_campaign_revision(monkeypatch):
    campaign = _campaign()
    authority = _record(campaign)
    purpose = f"bootstrap:{CAMPAIGN_ID}:revision:5"
    monkeypatch.setattr(
        "offer_manager.database.get_bootstrap_campaign",
        lambda campaign_id: authority if campaign_id == CAMPAIGN_ID else None,
    )

    verified = require_active_bootstrap_intent_authority(
        purpose=purpose,
        asset_id=ASSET_ID,
        now=NOW,
    )
    assert verified["campaign_id"] == CAMPAIGN_ID
    assert verified["campaign_revision"] == 5

    authority["revision"] = 6
    try:
        require_active_bootstrap_intent_authority(
            purpose=purpose,
            asset_id=ASSET_ID,
            now=NOW,
        )
    except ValueError as exc:
        assert str(exc) == "Bootstrap campaign revision is no longer active"
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("superseded Bootstrap revision was accepted")


def test_loss_stop_schedules_authoritative_cancellation_and_manual_restart():
    campaign = _campaign()
    campaign_value = campaign.xch_budget + campaign.cat_budget * campaign.anchor_price
    decision = _decision(
        campaign,
        BootstrapEvidence(realized_loss_xch=campaign_value * Decimal("0.05")),
    )

    transition = plan_bootstrap_runtime_transition(
        campaign_record=_record(campaign),
        decision=decision,
        unresolved_cancellation_count=0,
    )

    assert transition["allow_create"] is False
    assert transition["allow_requote"] is False
    assert transition["cancel_required"] is True
    assert transition["cancel_reason"] == "bootstrap_loss_limit"
    assert transition["manual_restart_required"] is True


def test_restart_resumes_unresolved_cancellation_without_replacement_creation():
    campaign = _campaign()
    authority = _record(campaign)

    recovery = plan_bootstrap_restart_recovery(
        campaign_record=authority,
        unresolved_trade_ids=("aa" * 32, "bb" * 32),
    )
    transition = plan_bootstrap_runtime_transition(
        campaign_record=authority,
        decision=_decision(campaign),
        unresolved_cancellation_count=2,
    )

    assert recovery["action"] == "resume_cancellation"
    assert recovery["allow_replacement"] is False
    assert recovery["trade_ids"] == ("aa" * 32, "bb" * 32)
    assert transition["allow_create"] is False
    assert transition["allow_requote"] is False
    assert transition["cancel_required"] is True


def test_only_sage_confirmed_independent_nonlinked_settlements_advance_evidence():
    rows = [
        {
            "campaign_id": CAMPAIGN_ID,
            "trade_id": "01" * 32,
            "settlement_identity": "11" * 32,
            "participant_cluster": "external-a",
            "side": "buy",
            "filled_at": "2026-09-12T11:50:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000000,
            "receive_coin_id": "21" * 32,
            "independent_depth": True,
            "adverse": False,
        },
        {
            "campaign_id": CAMPAIGN_ID,
            "trade_id": "02" * 32,
            "settlement_identity": "12" * 32,
            "participant_cluster": "own",
            "side": "sell",
            "filled_at": "2026-09-12T11:51:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000001,
            "receive_coin_id": "22" * 32,
            "independent_depth": True,
            "adverse": False,
        },
        {
            "campaign_id": CAMPAIGN_ID,
            "trade_id": "03" * 32,
            "settlement_identity": "13" * 32,
            "participant_cluster": "external-b",
            "side": "sell",
            "filled_at": "2026-09-12T11:52:00.000000Z",
            "verification_status": "pending",
            "spent_block_height": None,
            "receive_coin_id": None,
            "independent_depth": True,
            "adverse": False,
        },
        {
            "campaign_id": CAMPAIGN_ID,
            "trade_id": "04" * 32,
            "settlement_identity": "14" * 32,
            "participant_cluster": "linked-b",
            "side": "sell",
            "filled_at": "2026-09-12T11:53:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000002,
            "receive_coin_id": "24" * 32,
            "independent_depth": True,
            "adverse": True,
        },
    ]

    evidence = derive_bootstrap_settlement_evidence(
        rows,
        campaign_id=CAMPAIGN_ID,
        own_trade_ids=frozenset({"02" * 32}),
        linked_cluster_ids=frozenset({"linked-b"}),
    )

    assert evidence.confirmed_fills == 1
    assert evidence.settlement_clusters == 1
    assert evidence.independent_depth_sides == frozenset()
    assert evidence.adverse_fill_times == ()
