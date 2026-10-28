"""A completed Coin Prep scope needs a fresh, single-use initial Follow cap review."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module

import pytest

import database
from fee_approval_test_utils import _coin
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


def _completed_review(state):
    global database
    database = import_module("database")
    from coin_prep_fee_approval import complete_coin_prep_fee_session
    from prestart_follow_fee_ceiling import preview_prestart_follow_fee_ceiling

    prior = state["approval"]
    context = import_module("coin_prep_fee_runtime").read_approved_prep_fee_snapshot(
        prior["approval_id"]
    )
    targets = context["recipe"]["targets"]
    state["xch"] = [
        _coin(20000 + index, str(target.amount_mojos))
        for index, target in enumerate(targets)
        if target.asset == "xch"
    ]
    state["cat"] = [
        _coin(30000 + index, str(target.amount_mojos))
        for index, target in enumerate(targets)
        if target.asset == "cat"
    ]
    state["xch"].append(_coin(40000, str(10_000_000_000)))
    complete_coin_prep_fee_session(prior["approval_id"])
    return preview_prestart_follow_fee_ceiling(prior["approval_id"], 5_000_000_000)


def test_completed_prep_can_review_exact_prestart_ceiling_without_wallet_effect(
    approved,
):
    from prestart_follow_fee_ceiling import (
        confirm_prestart_follow_fee_ceiling,
    )

    prior = approved["approval"]
    review = _completed_review(approved)
    assert review["prior_maximum_fee_mojos"] == 80
    assert review["proposed_maximum_fee_mojos"] == 5_000_000_000
    assert review["spent_fee_mojos"] == 0
    assert review["held_fee_mojos"] == 0
    assert review["dispatch_authorized"] is False
    assert database.get_fee_approval(prior["approval_id"])["total_fee_mojos"] == 80
    confirmed = confirm_prestart_follow_fee_ceiling(
        review["preview_id"], review["review_sha256"]
    )
    assert confirmed["total_fee_mojos"] == 5_000_000_000
    assert confirmed["spent_fee_mojos"] == 0
    assert confirmed["held_fee_mojos"] == 0
    assert confirmed["dispatch_authorized"] is False
    assert (
        database.get_latest_prestart_follow_fee_approval(prior["approval_id"])
        == confirmed["approval_id"]
    )
    from follow_principal import preview_approved_follow_principal

    follow = preview_approved_follow_principal(confirmed["approval_id"])
    assert follow["approval_id"] == confirmed["approval_id"]
    assert follow["maximum_fee_mojos"] == 5_000_000_000
    assert follow["current_prep_targets_proven"] is True
    with pytest.raises(ValueError, match="FEE_PRESTART_REVIEW_USED"):
        confirm_prestart_follow_fee_ceiling(
            review["preview_id"], review["review_sha256"]
        )


def test_prestart_review_requires_completed_session(approved):
    from prestart_follow_fee_ceiling import preview_prestart_follow_fee_ceiling

    with pytest.raises(ValueError, match="FEE_SESSION_INCOMPLETE"):
        preview_prestart_follow_fee_ceiling(
            approved["approval"]["approval_id"], 5_000_000_000
        )


def test_completed_session_accepts_only_one_initial_ceiling_revision(approved):
    from prestart_follow_fee_ceiling import (
        confirm_prestart_follow_fee_ceiling,
        preview_prestart_follow_fee_ceiling,
    )

    review = _completed_review(approved)
    confirmed = confirm_prestart_follow_fee_ceiling(
        review["preview_id"], review["review_sha256"]
    )
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        preview_prestart_follow_fee_ceiling(confirmed["approval_id"], 6_000_000_000)


def test_prestart_review_rejects_changed_accounting(approved):
    from prestart_follow_fee_ceiling import confirm_prestart_follow_fee_ceiling

    review = _completed_review(approved)
    prior = approved["approval"]
    database.reserve_approved_fee(
        approval_id=prior["approval_id"],
        scope_sha256=prior["scope_sha256"],
        plan_sha256=prior["plan_sha256"],
        operation_id="a" * 64,
        fee_mojos=10,
        cancellation=False,
    )
    with pytest.raises(ValueError, match="FEE_PRESTART_ACCOUNTING_CHANGED"):
        confirm_prestart_follow_fee_ceiling(
            review["preview_id"], review["review_sha256"]
        )
    assert database.get_fee_approval(prior["approval_id"])["total_fee_mojos"] == 80


def test_ordinary_prep_confirmation_cannot_consume_prestart_review(approved):
    from coin_prep_fee_approval import approve_coin_prep_fees

    review = _completed_review(approved)
    with pytest.raises(ValueError, match="FEE_PRESTART_NATIVE_CONFIRMATION_REQUIRED"):
        approve_coin_prep_fees(
            preview_id=review["preview_id"],
            maximum_fee_mojos=5_000_000_000,
            cancellation_reserve_mojos=40,
        )


def test_prestart_review_rejects_session_rotation(approved):
    from coin_prep_fee_approval import resolve_server_fee_scope
    from coin_prep_fee_runtime import read_fee_economic_snapshot
    from prestart_follow_fee_ceiling import confirm_prestart_follow_fee_ceiling

    review = _completed_review(approved)
    resolve_server_fee_scope(identity=read_fee_economic_snapshot({})["identity"])
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        confirm_prestart_follow_fee_ceiling(
            review["preview_id"], review["review_sha256"]
        )


def test_prestart_review_rejects_wallet_target_change(approved):
    from prestart_follow_fee_ceiling import confirm_prestart_follow_fee_ceiling

    review = _completed_review(approved)
    approved["cat"].pop()
    with pytest.raises(ValueError, match="FEE_SESSION_INCOMPLETE"):
        confirm_prestart_follow_fee_ceiling(
            review["preview_id"], review["review_sha256"]
        )
    assert (
        database.get_latest_prestart_follow_fee_approval(
            approved["approval"]["approval_id"]
        )
        is None
    )


def test_concurrent_final_click_consumes_prestart_review_once(approved):
    from prestart_follow_fee_ceiling import confirm_prestart_follow_fee_ceiling

    review = _completed_review(approved)

    def attempt(_):
        try:
            return confirm_prestart_follow_fee_ceiling(
                review["preview_id"], review["review_sha256"]
            )["approval_id"]
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert len([value for value in outcomes if len(value) == 64]) == 1
    assert any(
        value in {"FEE_PRESTART_REVIEW_USED", "FEE_APPROVAL_STALE"}
        for value in outcomes
    )


def test_existing_follow_run_blocks_prestart_confirmation(approved):
    from prestart_follow_fee_ceiling import confirm_prestart_follow_fee_ceiling
    from test_follow_fee_cancellation import _run

    review = _completed_review(approved)
    _run(approved)
    with pytest.raises(ValueError, match="FEE_PRESTART_RUN_EXISTS"):
        confirm_prestart_follow_fee_ceiling(
            review["preview_id"], review["review_sha256"]
        )
    assert (
        database.get_latest_prestart_follow_fee_approval(
            approved["approval"]["approval_id"]
        )
        is None
    )


def test_changed_wallet_identity_blocks_prestart_confirmation(approved):
    from prestart_follow_fee_ceiling import confirm_prestart_follow_fee_ceiling

    review = _completed_review(approved)
    approved["identity"]["fingerprint"] = 12345
    with pytest.raises(ValueError, match="FEE_WALLET_IDENTITY_UNAVAILABLE"):
        confirm_prestart_follow_fee_ceiling(
            review["preview_id"], review["review_sha256"]
        )


def test_expired_prestart_review_cannot_append_approval(approved):
    from prestart_follow_fee_ceiling import confirm_prestart_follow_fee_ceiling

    review = _completed_review(approved)
    approved["now"] = review["expires_at"]
    with pytest.raises(ValueError, match="FEE_PREVIEW_STALE"):
        confirm_prestart_follow_fee_ceiling(
            review["preview_id"], review["review_sha256"]
        )


def test_lost_fee_funding_blocks_prestart_confirmation(approved):
    from prestart_follow_fee_ceiling import confirm_prestart_follow_fee_ceiling

    review = _completed_review(approved)
    approved["xch"].pop()
    with pytest.raises(ValueError, match="FEE_PRESTART_FUNDING_INSUFFICIENT"):
        confirm_prestart_follow_fee_ceiling(
            review["preview_id"], review["review_sha256"]
        )
