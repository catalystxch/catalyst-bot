from decimal import Decimal

import pytest

import database
from follow_run_policy import FollowRunPolicy
from follow_run_review_service import (
    confirm_follow_run_policy_review,
    prepare_follow_run_policy_review,
)


IDENTITY = {
    "network": "mainnet",
    "wallet_type": "sage",
    "wallet_fingerprint": "fingerprint-123",
    "wallet_id": 2,
    "xch_wallet_id": 1,
    "asset_id": "a" * 64,
}
CONFIGURATION_SHA256 = "c" * 64


def make_policy(**changes):
    terms = {
        "wallet_fingerprint": IDENTITY["wallet_fingerprint"],
        "network": IDENTITY["network"],
        "asset_id": IDENTITY["asset_id"],
        "buy_target": 100,
        "sell_target": 100,
        "price_anchor": Decimal("0.0123"),
        "price_min": Decimal("0.011"),
        "price_max": Decimal("0.013"),
        "maximum_fee_mojos_per_tx": 2_000_000,
        "fee_coin_principal_mojos": 8_000_000_000,
        "xch_reserve_mojos": 1_000_000_000,
        "cat_reserve_atoms": 25_000,
        "maximum_trade_xch_mojos": 100_000_000_000,
        "maximum_trade_cat_atoms": 1_000_000_000,
    }
    terms.update(changes)
    return FollowRunPolicy(**terms)


def test_prepare_is_disclosure_only_and_shows_terms_and_red_reasons(monkeypatch):
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda _policy: pytest.fail("preparing must not persist authority"),
    )

    review = prepare_follow_run_policy_review(
        make_policy(),
        wallet_identity=IDENTITY,
        configuration_sha256=CONFIGURATION_SHA256,
        red_reasons=["THIN_BOOK", "STALE_PRICE"],
        now_epoch=100,
    )

    assert review["success"] is True
    assert review["policy_digest"] == make_policy().digest
    assert review["disclosure"]["configuration_sha256"] == CONFIGURATION_SHA256
    assert review["disclosure"]["policy"]["buy_target"] == 100
    assert review["disclosure"]["red_reasons"] == ["THIN_BOOK", "STALE_PRICE"]
    assert review["review_expires_at_epoch"] == 400


def test_explicit_confirm_persists_exact_reviewed_policy(monkeypatch):
    saved = []
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda policy: saved.append(policy) or True,
    )
    policy = make_policy()
    review = prepare_follow_run_policy_review(
        policy,
        wallet_identity=IDENTITY,
        configuration_sha256=CONFIGURATION_SHA256,
        red_reasons=["THIN_BOOK"],
        now_epoch=100,
    )

    result = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        current_policy=policy,
        current_wallet_identity=IDENTITY,
        current_configuration_sha256=CONFIGURATION_SHA256,
        current_red_reasons=["THIN_BOOK"],
        now_epoch=101,
    )

    assert result["success"] is True
    assert result["policy_digest"] == policy.digest
    assert saved == [policy]


def test_reject_does_not_persist(monkeypatch):
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda _policy: pytest.fail("declined review must not persist"),
    )
    review = prepare_follow_run_policy_review(
        make_policy(),
        wallet_identity=IDENTITY,
        configuration_sha256=CONFIGURATION_SHA256,
        red_reasons=[],
        now_epoch=100,
    )

    result = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=False,
        current_policy=make_policy(),
        current_wallet_identity=IDENTITY,
        current_configuration_sha256=CONFIGURATION_SHA256,
        current_red_reasons=[],
        now_epoch=101,
    )
    assert result["success"] is False
    assert result["reason"] == "FOLLOW_RUN_REVIEW_NOT_ACCEPTED"


@pytest.mark.parametrize(
    "change",
    [
        {"policy": {"buy_target": 24}},
        {"identity": {"wallet_fingerprint": "other"}},
    ],
)
def test_changed_policy_or_identity_does_not_persist(monkeypatch, change):
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda _policy: pytest.fail("changed review must not persist"),
    )
    policy = make_policy()
    review = prepare_follow_run_policy_review(
        policy,
        wallet_identity=IDENTITY,
        configuration_sha256=CONFIGURATION_SHA256,
        red_reasons=["THIN_BOOK"],
        now_epoch=100,
    )
    current_policy = make_policy(**change.get("policy", {}))
    current_identity = {**IDENTITY, **change.get("identity", {})}

    result = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        current_policy=current_policy,
        current_wallet_identity=current_identity,
        current_configuration_sha256=CONFIGURATION_SHA256,
        current_red_reasons=["THIN_BOOK"],
        now_epoch=101,
    )
    assert result["success"] is False
    assert result["reason"] == "FOLLOW_RUN_REVIEW_CHANGED"


def test_expired_review_does_not_persist(monkeypatch):
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda _policy: pytest.fail("expired review must not persist"),
    )
    policy = make_policy()
    review = prepare_follow_run_policy_review(
        policy,
        wallet_identity=IDENTITY,
        configuration_sha256=CONFIGURATION_SHA256,
        red_reasons=[],
        now_epoch=100,
        ttl_seconds=5,
    )

    result = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        current_policy=policy,
        current_wallet_identity=IDENTITY,
        current_configuration_sha256=CONFIGURATION_SHA256,
        current_red_reasons=[],
        now_epoch=105,
    )
    assert result["success"] is False
    assert result["reason"] == "FOLLOW_RUN_REVIEW_EXPIRED"


def test_review_digest_mismatch_and_replay_are_rejected(monkeypatch):
    saved = []
    monkeypatch.setattr(
        database, "record_active_follow_run_policy", lambda p: saved.append(p) or True
    )
    policy = make_policy()
    review = prepare_follow_run_policy_review(
        policy,
        wallet_identity=IDENTITY,
        configuration_sha256=CONFIGURATION_SHA256,
        red_reasons=[],
        now_epoch=100,
    )

    bad_digest = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256="0" * 64,
        accepted=True,
        current_policy=policy,
        current_wallet_identity=IDENTITY,
        current_configuration_sha256=CONFIGURATION_SHA256,
        current_red_reasons=[],
        now_epoch=101,
    )
    assert bad_digest["success"] is False

    approved = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        current_policy=policy,
        current_wallet_identity=IDENTITY,
        current_configuration_sha256=CONFIGURATION_SHA256,
        current_red_reasons=[],
        now_epoch=101,
    )
    replay = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        current_policy=policy,
        current_wallet_identity=IDENTITY,
        current_configuration_sha256=CONFIGURATION_SHA256,
        current_red_reasons=[],
        now_epoch=102,
    )
    assert approved["success"] is True
    assert replay["reason"] == "FOLLOW_RUN_REVIEW_REQUIRED"
    assert saved == [policy]


def test_persistence_failure_does_not_report_approval(monkeypatch):
    monkeypatch.setattr(
        database, "record_active_follow_run_policy", lambda _policy: False
    )
    policy = make_policy()
    review = prepare_follow_run_policy_review(
        policy,
        wallet_identity=IDENTITY,
        configuration_sha256=CONFIGURATION_SHA256,
        red_reasons=[],
        now_epoch=100,
    )

    result = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        current_policy=policy,
        current_wallet_identity=IDENTITY,
        current_configuration_sha256=CONFIGURATION_SHA256,
        current_red_reasons=[],
        now_epoch=101,
    )
    assert result == {
        "success": False,
        "reason": "FOLLOW_RUN_POLICY_PERSIST_FAILED",
    }


@pytest.mark.parametrize(
    ("configuration", "reasons"),
    [
        ("d" * 64, ["THIN_BOOK"]),
        (CONFIGURATION_SHA256, ["STALE_PRICE"]),
    ],
)
def test_changed_configuration_or_red_evidence_invalidates_review(
    monkeypatch, configuration, reasons
):
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda _policy: pytest.fail("changed review must not persist"),
    )
    policy = make_policy()
    review = prepare_follow_run_policy_review(
        policy,
        wallet_identity=IDENTITY,
        configuration_sha256=CONFIGURATION_SHA256,
        red_reasons=["THIN_BOOK"],
        now_epoch=100,
    )

    result = confirm_follow_run_policy_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        current_policy=policy,
        current_wallet_identity=IDENTITY,
        current_configuration_sha256=configuration,
        current_red_reasons=reasons,
        now_epoch=101,
    )
    assert result == {"success": False, "reason": "FOLLOW_RUN_REVIEW_CHANGED"}
