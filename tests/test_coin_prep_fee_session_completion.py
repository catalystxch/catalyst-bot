"""Standalone fee sessions rotate only after authoritative plan completion."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest

import coin_prep_fee_approval as service
import coin_prep_fee_runtime as runtime
import database
from fee_approval_test_utils import _coin
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


def _install_completed_targets(state, approval_id):
    context = runtime.read_approved_prep_fee_snapshot(approval_id)
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
    return targets


def test_incomplete_current_wallet_cannot_complete_or_rotate_session(approved):
    approval = approved["approval"]
    with pytest.raises(ValueError, match="FEE_SESSION_INCOMPLETE"):
        service.complete_coin_prep_fee_session(approval["approval_id"])

    original_scope = service.resolve_server_fee_scope(
        identity=runtime.read_fee_economic_snapshot({})["identity"]
    )
    assert original_scope["session_id"]
    assert database.get_coin_prep_fee_session(original_scope["session_id"])["generation"] == 1
    assert database.get_connection().execute(
        "SELECT COUNT(*) FROM coin_prep_fee_session_completions"
    ).fetchone()[0] == 0


def test_exact_current_targets_complete_once_and_next_preview_rotates_generation(approved):
    approval = approved["approval"]
    old_context = database.get_coin_prep_fee_approval_context(approval["approval_id"])
    old_session_id = json.loads(old_context["scope_json"])["session_id"]
    targets = _install_completed_targets(approved, approval["approval_id"])

    completed = service.complete_coin_prep_fee_session(approval["approval_id"])
    replay = service.complete_coin_prep_fee_session(approval["approval_id"])
    assert completed["session_id"] == old_session_id
    assert completed["approval_id"] == approval["approval_id"]
    assert completed["target_count"] == len(targets)
    assert completed["operation_count"] == 0
    assert completed["idempotent"] is False
    assert replay == {**completed, "idempotent": True}

    identity = runtime.read_fee_economic_snapshot({})["identity"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        scopes = list(pool.map(
            lambda _: service.resolve_server_fee_scope(identity=identity), range(8)
        ))
    assert len({scope["session_id"] for scope in scopes}) == 1
    new_session_id = scopes[0]["session_id"]
    assert new_session_id != old_session_id
    assert database.get_coin_prep_fee_session(new_session_id)["generation"] == 2
    assert database.get_coin_prep_fee_session(old_session_id)["current_session_id"] == new_session_id
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        runtime.read_approved_prep_fee_snapshot(approval["approval_id"])


def test_unresolved_fee_hold_blocks_completion_even_when_targets_exist(approved):
    approval = approved["approval"]
    _install_completed_targets(approved, approval["approval_id"])
    database.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256=approval["scope_sha256"],
        plan_sha256=approval["plan_sha256"],
        operation_id="1" * 64,
        fee_mojos=10,
        cancellation=False,
    )
    with pytest.raises(ValueError, match="FEE_SESSION_EFFECT_UNRESOLVED"):
        service.complete_coin_prep_fee_session(approval["approval_id"])
    assert database.get_connection().execute(
        "SELECT COUNT(*) FROM coin_prep_fee_session_completions"
    ).fetchone()[0] == 0


def test_generation_two_cannot_be_injected_without_completion_evidence(approved):
    approval = approved["approval"]
    context = database.get_coin_prep_fee_approval_context(approval["approval_id"])
    session_id = json.loads(context["scope_json"])["session_id"]
    session = database.get_coin_prep_fee_session(session_id)
    conn = database.get_connection()
    with pytest.raises(Exception, match="completion evidence"):
        conn.execute(
            "INSERT INTO coin_prep_fee_sessions VALUES (?, ?, ?, ?, ?)",
            ("e" * 64, session["identity_sha256"], session["identity_json"], 2, 1001),
        )
    conn.rollback()
    assert database.get_coin_prep_fee_session(session_id)["current_session_id"] == session_id


def test_fee_approval_status_survives_restart_without_granting_dispatch(approved):
    approval = approved["approval"]

    initial = database.get_coin_prep_fee_approval_status(approval["approval_id"])

    assert initial["state"] == "approved"
    assert initial["approval_id"] == approval["approval_id"]
    assert initial["held_fee_mojos"] == 0
    assert initial["spent_fee_mojos"] == 0
    assert initial["remaining_fee_mojos"] == approval["total_fee_mojos"]
    assert initial["unresolved_operation_count"] == 0
    assert initial["session_completed"] is False
    assert initial["dispatch_authorized"] is False

    database.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256=approval["scope_sha256"],
        plan_sha256=approval["plan_sha256"],
        operation_id="2" * 64,
        fee_mojos=10,
        cancellation=False,
    )

    recovered = database.get_coin_prep_fee_approval_status(approval["approval_id"])

    assert recovered["state"] == "held_before_submission"
    assert recovered["held_fee_mojos"] == 10
    assert recovered["remaining_fee_mojos"] == approval["total_fee_mojos"] - 10
    assert recovered["unresolved_operation_count"] == 1
    assert recovered["pending_operation"] == {
        "fee_mojos": 10,
        "cancellation": False,
        "effect_state": "held_before_submission",
    }
    assert recovered["dispatch_authorized"] is False


def test_campaign_scope_proves_exact_targets_without_standalone_rotation(
    approved, monkeypatch,
):
    approval = approved["approval"]
    targets = _install_completed_targets(approved, approval["approval_id"])
    campaign_id = "c" * 64
    context = deepcopy(runtime.read_approved_prep_fee_snapshot(approval["approval_id"]))
    context["scope"] = {
        **context["scope"],
        "session_id": None,
        "campaign_id": campaign_id,
    }
    context["campaign"] = {"campaign_id": campaign_id, "revision": 7}
    monkeypatch.setattr(runtime, "read_approved_prep_fee_snapshot", lambda _approval: context)
    monkeypatch.setattr(
        database,
        "get_coin_prep_fee_approval_status",
        lambda _approval: {
            "state": "approved",
            "stale": False,
            "unresolved_operation_count": 0,
            "reservation_count": 2,
        },
    )

    completed = service.complete_coin_prep_fee_scope(approval["approval_id"])

    assert completed == {
        "approval_id": approval["approval_id"],
        "campaign_id": campaign_id,
        "target_count": len(targets),
        "operation_count": 2,
        "campaign_managed": True,
        "idempotent": True,
        "dispatch_authorized": False,
    }
    assert database.get_connection().execute(
        "SELECT COUNT(*) FROM coin_prep_fee_session_completions"
    ).fetchone()[0] == 0
