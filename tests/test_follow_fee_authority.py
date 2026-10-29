"""A Follow run cannot silently reset its financial authority on restart."""

import json
from unittest.mock import patch

import database
import pytest
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401
from follow_run_terms import CONTINUOUS_RUN_EXPIRY


def test_explicit_continuous_review_survives_finite_window(approved):
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
        principal_review_sha256="d" * 64,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=CONTINUOUS_RUN_EXPIRY,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    with pytest.raises(ValueError, match="FOLLOW_REVIEW_INVALID"):
        database.create_follow_run_review(**terms)
    review = database.create_follow_run_review(**terms, continuous=True)
    with patch.object(database.time, "time", return_value=1002):
        run = database.create_follow_run_authority(
            consent_id=review["review_id"],
            review_sha256=review["review_sha256"],
            **terms,
        )
    assert run["run_id"]
    assert (
        database.get_follow_run_review(review["review_id"])["expires_at_epoch"]
        == CONTINUOUS_RUN_EXPIRY
    )


def reviewed_run(**terms):
    terms.setdefault("principal_review_sha256", "d" * 64)
    review = database.create_follow_run_review(**terms)
    with patch.object(
        database.time, "time", return_value=terms["started_at_epoch"] + 1
    ):
        return database.create_follow_run_authority(
            consent_id=review["review_id"],
            review_sha256=review["review_sha256"],
            **terms,
        )


def test_reapproved_continuous_run_supersedes_old_hash_without_resetting_fee_scope(
    approved,
):
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
    terms = dict(
        approval_id=approval_id,
        identity=identity,
        configuration_sha256="a" * 64,
        principal_review_sha256="d" * 64,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=CONTINUOUS_RUN_EXPIRY,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    first = database.create_follow_run_review(**terms, continuous=True)
    with patch.object(database.time, "time", return_value=1002):
        old = database.create_follow_run_authority(
            consent_id=first["review_id"], review_sha256=first["review_sha256"], **terms
        )
    renewed_terms = terms | {
        "principal_review_sha256": "e" * 64,
        "started_at_epoch": 1005,
    }
    renewed = database.create_follow_run_review(**renewed_terms, continuous=True)
    with patch.object(database.time, "time", return_value=1006):
        new = database.create_follow_run_authority(
            consent_id=renewed["review_id"],
            review_sha256=renewed["review_sha256"],
            reapprove_run_id=old["run_id"],
            **renewed_terms,
        )
    assert new["run_id"] == old["run_id"]
    assert database.get_follow_run_review(renewed["review_id"])["consumed"] is True
    active = database.get_follow_creation_authority(
        identity=identity, configuration_sha256="a" * 64, now_epoch=1007
    )
    assert active["run_id"] == new["run_id"]
    assert active["consent_id"] == renewed["review_id"]
    assert active["principal_review_sha256"] == "e" * 64


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
        principal_review_sha256="d" * 64,
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
    assert stored["principal_review_sha256"] == terms["principal_review_sha256"]
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
        with pytest.raises(ValueError, match="FOLLOW_REVIEW_CHANGED"):
            database.create_follow_run_authority(
                consent_id=review["review_id"],
                review_sha256=review["review_sha256"],
                **(terms | {"principal_review_sha256": "e" * 64}),
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
            principal_review_sha256="d" * 64,
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
            principal_review_sha256="d" * 64,
            buy_limit=24,
            sell_limit=24,
            started_at_epoch=1001,
            expires_at_epoch=1001 + 48 * 3600,
            maximum_fee_mojos=80,
            protected_shutdown_fee_mojos=0,
        )


def test_follow_review_rejects_approval_scope_and_ceiling_mismatch(approved):
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
    terms = dict(
        approval_id=approval_id,
        identity=identity,
        configuration_sha256="a" * 64,
        principal_review_sha256="d" * 64,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=1001 + 48 * 3600,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    with pytest.raises(ValueError, match="FOLLOW_FEE_APPROVAL_MISMATCH"):
        database.create_follow_run_review(**(terms | {"maximum_fee_mojos": 81}))
    with pytest.raises(ValueError, match="FOLLOW_FEE_APPROVAL_MISMATCH"):
        database.create_follow_run_review(
            **(
                terms
                | {
                    "identity": {
                        **identity,
                        "wallet_fingerprint": identity["wallet_fingerprint"] + 1,
                    }
                }
            )
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
    assert current["approval_id"] == approval_id
    assert current["principal_review_sha256"] == "d" * 64
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


def test_unexpired_follow_run_marker_survives_stop_and_settings_drift(approved):
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
    marker = database.get_unexpired_follow_run_marker(
        asset_id=identity["asset_id"], now_epoch=1002
    )
    assert marker["run_id"] == run["run_id"]
    assert marker["stopped"] is False
    database.stop_follow_run_authority(run_id=run["run_id"], stopped_at_epoch=1010)
    marker = database.get_unexpired_follow_run_marker(
        asset_id=identity["asset_id"], now_epoch=1011
    )
    assert marker["run_id"] == run["run_id"]
    assert marker["stopped"] is True
    assert (
        database.get_unexpired_follow_run_marker(asset_id="b" * 64, now_epoch=1011)
        is None
    )
    assert (
        database.get_unexpired_follow_run_marker(
            asset_id=identity["asset_id"], now_epoch=1001 + 48 * 3600
        )
        is None
    )


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
