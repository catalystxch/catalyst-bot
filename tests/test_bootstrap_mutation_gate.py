from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapEvidence,
    evaluate_bootstrap_campaign,
)
from mutation_gate import authorize_market_mutation


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ASSET_ID = "ab" * 32
CAMPAIGN_ID = "cd" * 32


def _campaign(*, expires_at=None):
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
        expires_at=expires_at or NOW + timedelta(days=6),
    )


def _record(campaign, **overrides):
    record = {
        **campaign.to_record(),
        "campaign_id": CAMPAIGN_ID,
        "revision": 3,
        "status": "active",
        "stage": "bootstrap",
        "stop_reason": None,
    }
    record.update(overrides)
    return record


def _identity(**overrides):
    identity = {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 736588221,
        "wallet_id": 2,
        "asset_id": ASSET_ID,
    }
    identity.update(overrides)
    return identity


def _authorize(campaign, **overrides):
    values = {
        "operation": "create",
        "follow_authorized": False,
        "identity": _identity(),
        "asset_id": ASSET_ID,
        "bootstrap_campaign": _record(campaign),
        "bootstrap_decision": evaluate_bootstrap_campaign(
            campaign, BootstrapEvidence(), now=NOW
        ),
        "expected_campaign_id": CAMPAIGN_ID,
        "expected_revision": 3,
        "now": NOW,
    }
    values.update(overrides)
    return authorize_market_mutation(**values)


def test_red_follow_has_no_bypass_without_an_exact_active_campaign():
    result = authorize_market_mutation(
        operation="create",
        follow_authorized=False,
        identity=_identity(),
        asset_id=ASSET_ID,
        bootstrap_campaign=None,
        bootstrap_decision=None,
        expected_campaign_id=None,
        expected_revision=None,
        now=NOW,
    )

    assert result == {
        "allowed": False,
        "mode": None,
        "reason_code": "MARKET_AUTHORITY_REQUIRED",
    }


def test_exact_active_campaign_can_authorize_without_follow_confidence():
    campaign = _campaign()
    result = _authorize(campaign)

    assert result == {
        "allowed": True,
        "mode": "bootstrap",
        "reason_code": "BOOTSTRAP_AUTHORIZED",
        "campaign_id": CAMPAIGN_ID,
        "campaign_revision": 3,
    }


def test_changed_identity_stopped_expired_and_superseded_authority_fail_closed():
    campaign = _campaign()

    assert _authorize(campaign, identity=_identity(wallet_id=3))["reason_code"] == (
        "BOOTSTRAP_IDENTITY_MISMATCH"
    )
    assert _authorize(
        campaign,
        bootstrap_campaign=_record(campaign, status="stopped"),
    )["reason_code"] == "BOOTSTRAP_NOT_ACTIVE"
    assert _authorize(campaign, expected_revision=2)["reason_code"] == (
        "BOOTSTRAP_REVISION_SUPERSEDED"
    )

    expired = _campaign(expires_at=NOW - timedelta(microseconds=1))
    assert _authorize(
        expired,
        bootstrap_campaign=_record(expired),
        bootstrap_decision=evaluate_bootstrap_campaign(
            expired, BootstrapEvidence(), now=NOW
        ),
    )["reason_code"] == "BOOTSTRAP_EXPIRED"


def test_valid_follow_authority_does_not_require_a_bootstrap_campaign():
    result = authorize_market_mutation(
        operation="requote",
        follow_authorized=True,
        identity=_identity(),
        asset_id=ASSET_ID,
        bootstrap_campaign=None,
        bootstrap_decision=None,
        expected_campaign_id=None,
        expected_revision=None,
        now=NOW,
    )

    assert result == {
        "allowed": True,
        "mode": "follow",
        "reason_code": "FOLLOW_AUTHORIZED",
    }
