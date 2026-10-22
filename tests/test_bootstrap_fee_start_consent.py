"""Bootstrap Start Bot needs advance campaign-bound cancellation consent."""

from importlib import import_module

import api_server  # noqa: F401 - establishes blueprint import order


def test_start_fee_readiness_rejects_missing_campaign_approval(monkeypatch):
    bot = import_module("blueprints.bot")
    database = import_module("database")
    campaign = {"campaign_id": "a" * 64, "revision": 0, "fee_budget_xch": "0.05"}
    monkeypatch.setattr(
        database, "get_latest_coin_prep_fee_approval_for_campaign", lambda _id: None
    )

    result = bot._bootstrap_cancellation_fee_start_readiness(campaign)

    assert result == {
        "ready": False,
        "reason": "bootstrap_cancellation_fee_approval_required",
    }


def test_start_fee_readiness_rejects_recovery_only_or_stale_approval(monkeypatch):
    bot = import_module("blueprints.bot")
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    campaign = {"campaign_id": "a" * 64, "revision": 0, "fee_budget_xch": "0.05"}
    monkeypatch.setattr(
        database,
        "get_latest_coin_prep_fee_approval_for_campaign",
        lambda _id: "b" * 64,
    )

    def rejected(_id, **_kwargs):
        raise ValueError("FEE_APPROVAL_RECOVERY_ONLY")

    monkeypatch.setattr(runtime, "read_approved_prep_fee_snapshot", rejected)

    assert bot._bootstrap_cancellation_fee_start_readiness(campaign) == {
        "ready": False,
        "reason": "bootstrap_cancellation_fee_approval_stale",
    }


def test_start_fee_readiness_requires_remaining_cancellation_cover(monkeypatch):
    bot = import_module("blueprints.bot")
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    campaign = {"campaign_id": "a" * 64, "revision": 0, "fee_budget_xch": "0.05"}
    monkeypatch.setattr(
        database,
        "get_latest_coin_prep_fee_approval_for_campaign",
        lambda _id: "b" * 64,
    )
    monkeypatch.setattr(
        runtime,
        "read_approved_prep_fee_snapshot",
        lambda _id, **_kwargs: {
            "campaign": campaign,
            "recovery_only": False,
            "approval": {
                "total_fee_mojos": 50_000_000_000,
                "cancellation_reserve_mojos": 1000,
                "remaining_fee_mojos": 0,
            },
        },
    )

    assert bot._bootstrap_cancellation_fee_start_readiness(campaign) == {
        "ready": False,
        "reason": "bootstrap_cancellation_fee_budget_insufficient",
    }


def test_start_fee_readiness_accepts_current_campaign_consent(monkeypatch):
    bot = import_module("blueprints.bot")
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    campaign = {"campaign_id": "a" * 64, "revision": 0, "fee_budget_xch": "0.05"}
    monkeypatch.setattr(
        database,
        "get_latest_coin_prep_fee_approval_for_campaign",
        lambda _id: "b" * 64,
    )
    monkeypatch.setattr(
        runtime,
        "read_approved_prep_fee_snapshot",
        lambda _id, **_kwargs: {
            "campaign": campaign,
            "recovery_only": False,
            "approval": {
                "total_fee_mojos": 50_000_000_000,
                "cancellation_reserve_mojos": 1000,
                "remaining_fee_mojos": 1000,
            },
        },
    )

    assert bot._bootstrap_cancellation_fee_start_readiness(campaign) == {
        "ready": True,
        "approval_id": "b" * 64,
    }


def test_start_fee_readiness_rejects_superseded_campaign_revision(monkeypatch):
    bot = import_module("blueprints.bot")
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    campaign = {"campaign_id": "a" * 64, "revision": 1, "fee_budget_xch": "0.05"}
    monkeypatch.setattr(
        database,
        "get_latest_coin_prep_fee_approval_for_campaign",
        lambda _id: "b" * 64,
    )
    monkeypatch.setattr(
        runtime,
        "read_approved_prep_fee_snapshot",
        lambda _id, **_kwargs: {
            "campaign": {**campaign, "revision": 0},
            "recovery_only": False,
            "approval": {
                "total_fee_mojos": 50_000_000_000,
                "cancellation_reserve_mojos": 1000,
                "remaining_fee_mojos": 1000,
            },
        },
    )

    assert bot._bootstrap_cancellation_fee_start_readiness(campaign) == {
        "ready": False,
        "reason": "bootstrap_cancellation_fee_approval_stale",
    }
