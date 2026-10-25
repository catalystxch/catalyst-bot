"""A Follow run cannot silently reset its financial authority on restart."""

import json
from unittest.mock import patch

import database
import pytest
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


def reviewed_run(**terms):
    review = database.create_follow_run_review(**terms)
    with patch.object(
        database.time, "time", return_value=terms["started_at_epoch"] + 1
    ):
        return database.create_follow_run_authority(
            consent_id=review["review_id"],
            review_sha256=review["review_sha256"],
            **terms,
        )


def test_follow_review_is_exact_single_use_and_expires(approved):
    approval_id = approved["approval"]["approval_id"]
    scope = json.loads(
        database.get_coin_prep_fee_approval_context(approval_id)["scope_json"]
    )
    terms = dict(
        approval_id=approval_id,
        identity={
            key: scope[key]
            for key in (
                "network",
                "wallet_type",
                "wallet_fingerprint",
                "wallet_id",
                "xch_wallet_id",
                "asset_id",
                "ticker",
            )
        },
        configuration_sha256="a" * 64,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=1001 + 48 * 3600,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    review = database.create_follow_run_review(**terms)
    stored = database.get_follow_run_review(review["review_id"])
    assert stored["review_sha256"] == review["review_sha256"]
    assert stored["identity"] == terms["identity"]
    assert stored["buy_limit"] == stored["sell_limit"] == 24
    assert stored["maximum_fee_mojos"] == 80
    assert stored["protected_shutdown_fee_mojos"] == 40
    assert stored["consumed"] is False
    assert stored["dispatch_authorized"] is False
    with patch.object(database.time, "time", return_value=1002):
        with pytest.raises(ValueError, match="FOLLOW_REVIEW_CHANGED"):
            database.create_follow_run_authority(
                consent_id=review["review_id"],
                review_sha256="f" * 64,
                **terms,
            )
        with pytest.raises(ValueError, match="FOLLOW_REVIEW_CHANGED"):
            database.create_follow_run_authority(
                consent_id=review["review_id"],
                review_sha256=review["review_sha256"],
                **(terms | {"buy_limit": 25}),
            )
        run = database.create_follow_run_authority(
            consent_id=review["review_id"],
            review_sha256=review["review_sha256"],
            **terms,
        )
        assert run["consent_id"] == review["review_id"]
        assert database.get_follow_run_review(review["review_id"])["consumed"] is True
        with pytest.raises(ValueError, match="FOLLOW_REVIEW_USED"):
            database.create_follow_run_authority(
                consent_id=review["review_id"],
                review_sha256=review["review_sha256"],
                **terms,
            )

    with pytest.raises(ValueError, match="FOLLOW_REVIEW_REQUIRED"):
        database.get_follow_run_review("0" * 64)
    expired = database.create_follow_run_review(
        **(terms | {"started_at_epoch": 2000, "expires_at_epoch": 2000 + 48 * 3600})
    )
    with patch.object(database.time, "time", return_value=2301):
        with pytest.raises(ValueError, match="FOLLOW_REVIEW_EXPIRED"):
            database.create_follow_run_authority(
                consent_id=expired["review_id"],
                review_sha256=expired["review_sha256"],
                **(
                    terms
                    | {"started_at_epoch": 2000, "expires_at_epoch": 2000 + 48 * 3600}
                ),
            )


def test_arbitrary_follow_consent_cannot_create_financial_run(approved):
    approval_id = approved["approval"]["approval_id"]
    scope = json.loads(
        database.get_coin_prep_fee_approval_context(approval_id)["scope_json"]
    )
    identity = {
        key: scope[key]
        for key in (
            "network",
            "wallet_type",
            "wallet_fingerprint",
            "wallet_id",
            "xch_wallet_id",
            "asset_id",
            "ticker",
        )
    }
    with pytest.raises(ValueError, match="FOLLOW_REVIEW_REQUIRED"):
        database.create_follow_run_authority(
            consent_id="c" * 64,
            review_sha256="f" * 64,
            approval_id=approval_id,
            identity=identity,
            configuration_sha256="a" * 64,
            buy_limit=24,
            sell_limit=24,
            started_at_epoch=1001,
            expires_at_epoch=1001 + 48 * 3600,
            maximum_fee_mojos=80,
            protected_shutdown_fee_mojos=40,
        )


def test_follow_review_requires_positive_protected_shutdown_reserve(approved):
    approval_id = approved["approval"]["approval_id"]
    scope = json.loads(
        database.get_coin_prep_fee_approval_context(approval_id)["scope_json"]
    )
    identity = {
        key: scope[key]
        for key in (
            "network",
            "wallet_type",
            "wallet_fingerprint",
            "wallet_id",
            "xch_wallet_id",
            "asset_id",
            "ticker",
        )
    }
    with pytest.raises(ValueError, match="FOLLOW_FEE_CAP_INVALID"):
        database.create_follow_run_review(
            approval_id=approval_id,
            identity=identity,
            configuration_sha256="a" * 64,
            buy_limit=24,
            sell_limit=24,
            started_at_epoch=1001,
            expires_at_epoch=1001 + 48 * 3600,
            maximum_fee_mojos=80,
            protected_shutdown_fee_mojos=0,
        )


def test_follow_creation_authority_is_bound_to_original_review(approved):
    approval_id = approved["approval"]["approval_id"]
    context = database.get_coin_prep_fee_approval_context(approval_id)
    scope = json.loads(context["scope_json"])
    identity = {
        key: scope[key]
        for key in (
            "network",
            "wallet_type",
            "wallet_fingerprint",
            "wallet_id",
            "xch_wallet_id",
            "asset_id",
            "ticker",
        )
    }
    config_digest = "a" * 64
    run = reviewed_run(
        approval_id=approval_id,
        identity=identity,
        configuration_sha256=config_digest,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=1001 + 48 * 3600,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )

    current = database.get_follow_creation_authority(
        identity=identity,
        configuration_sha256=config_digest,
        now_epoch=1002,
    )
    assert current["ready"] is True
    assert current["run_id"] == run["run_id"]
    assert current["maximum_fee_mojos"] == 80
    assert current["protected_shutdown_fee_mojos"] == 40
    assert current["buy_limit"] == current["sell_limit"] == 24

    changed = database.get_follow_creation_authority(
        identity=identity,
        configuration_sha256="b" * 64,
        now_epoch=1002,
    )
    assert changed["ready"] is False
    assert changed["reason_code"] == "FOLLOW_CONFIGURATION_CHANGED"

    expired = database.get_follow_creation_authority(
        identity=identity,
        configuration_sha256=config_digest,
        now_epoch=1001 + 48 * 3600,
    )
    assert expired["ready"] is False
    assert expired["reason_code"] == "FOLLOW_RUN_EXPIRED"


def test_unresolved_fee_effect_temporarily_blocks_creation_without_reset(approved):
    approval_id = approved["approval"]["approval_id"]
    scope = json.loads(
        database.get_coin_prep_fee_approval_context(approval_id)["scope_json"]
    )
    identity = {
        key: scope[key]
        for key in (
            "network",
            "wallet_type",
            "wallet_fingerprint",
            "wallet_id",
            "xch_wallet_id",
            "asset_id",
            "ticker",
        )
    }
    run = reviewed_run(
        approval_id=approval_id,
        identity=identity,
        configuration_sha256="a" * 64,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=1001 + 48 * 3600,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    database.reserve_approved_fee(
        approval_id=approval_id,
        scope_sha256=approved["approval"]["scope_sha256"],
        plan_sha256=approved["approval"]["plan_sha256"],
        operation_id="1" * 64,
        fee_mojos=1,
        cancellation=True,
    )
    blocked = database.get_follow_creation_authority(
        identity=identity, configuration_sha256="a" * 64, now_epoch=1002
    )
    assert blocked["ready"] is False
    assert blocked["reason_code"] == "FOLLOW_UNRESOLVED_EFFECT"
    assert blocked["run_id"] == run["run_id"]
    cleanup = database.get_follow_cleanup_authority(
        run_id=run["run_id"], identity=identity, now_epoch=1002
    )
    assert cleanup["ready"] is False
    assert cleanup["reason_code"] == "FOLLOW_UNRESOLVED_EFFECT"
    assert cleanup["held_fee_mojos"] == 1
    assert cleanup["remaining_fee_mojos"] == 79


def test_unapproved_fee_ledger_cannot_create_follow_authority(approved):
    approval_id = approved["approval"]["approval_id"]
    scope = json.loads(
        database.get_coin_prep_fee_approval_context(approval_id)["scope_json"]
    )
    identity = {
        key: scope[key]
        for key in (
            "network",
            "wallet_type",
            "wallet_fingerprint",
            "wallet_id",
            "xch_wallet_id",
            "asset_id",
            "ticker",
        )
    }
    generic = database.create_fee_approval(
        scope_sha256="e" * 64,
        plan_sha256="f" * 64,
        total_fee_mojos=80,
        cancellation_reserve_mojos=40,
    )
    import pytest

    with pytest.raises(ValueError, match="FOLLOW_FEE_APPROVAL_REQUIRED"):
        reviewed_run(
            approval_id=generic["approval_id"],
            identity=identity,
            configuration_sha256="a" * 64,
            buy_limit=24,
            sell_limit=24,
            started_at_epoch=1001,
            expires_at_epoch=1001 + 48 * 3600,
            maximum_fee_mojos=80,
            protected_shutdown_fee_mojos=40,
        )


def test_stopping_run_revokes_creation_but_keeps_cleanup_scope(approved):
    approval_id = approved["approval"]["approval_id"]
    scope = json.loads(
        database.get_coin_prep_fee_approval_context(approval_id)["scope_json"]
    )
    identity = {
        key: scope[key]
        for key in (
            "network",
            "wallet_type",
            "wallet_fingerprint",
            "wallet_id",
            "xch_wallet_id",
            "asset_id",
            "ticker",
        )
    }
    run = reviewed_run(
        approval_id=approval_id,
        identity=identity,
        configuration_sha256="a" * 64,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=1001 + 48 * 3600,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    database.stop_follow_run_authority(run_id=run["run_id"], stopped_at_epoch=1010)
    result = database.get_follow_creation_authority(
        identity=identity, configuration_sha256="a" * 64, now_epoch=1011
    )
    assert result["ready"] is False
    assert result["reason_code"] == "FOLLOW_RUN_STOPPED"
    assert result["run_id"] == run["run_id"]
    assert result["consent_id"] == run["consent_id"]


def test_stopped_and_expired_run_retains_only_bound_cleanup_scope(approved):
    approval_id = approved["approval"]["approval_id"]
    scope = json.loads(
        database.get_coin_prep_fee_approval_context(approval_id)["scope_json"]
    )
    identity = {
        key: scope[key]
        for key in (
            "network",
            "wallet_type",
            "wallet_fingerprint",
            "wallet_id",
            "xch_wallet_id",
            "asset_id",
            "ticker",
        )
    }
    run = reviewed_run(
        approval_id=approval_id,
        identity=identity,
        configuration_sha256="a" * 64,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=1001 + 48 * 3600,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    database.stop_follow_run_authority(run_id=run["run_id"], stopped_at_epoch=1010)
    cleanup = database.get_follow_cleanup_authority(
        run_id=run["run_id"], identity=identity, now_epoch=1001 + 48 * 3600 + 1
    )
    assert cleanup["ready"] is True
    assert cleanup["approval_id"] == approval_id
    assert cleanup["maximum_fee_mojos"] == 80
    assert cleanup["protected_shutdown_fee_mojos"] == 40
    assert cleanup["dispatch_authorized"] is False
    wrong = {**identity, "wallet_fingerprint": identity["wallet_fingerprint"] + 1}
    refused = database.get_follow_cleanup_authority(
        run_id=run["run_id"], identity=wrong, now_epoch=1001 + 48 * 3600 + 1
    )
    assert refused["ready"] is False
    assert refused["reason_code"] == "FOLLOW_IDENTITY_MISMATCH"
