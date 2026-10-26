"""A Follow run retains one cumulative ledger across ceiling revisions."""

import hashlib
import json
import sqlite3

import database
import pytest
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401
from test_follow_fee_cancellation import _run


def test_initial_effective_fee_policy_uses_original_run_scope(approved):
    run_id, identity = _run(approved)
    policy = database.get_effective_follow_fee_policy(
        run_id=run_id, identity=identity, now_epoch=1002
    )
    assert policy["ready"] is True
    assert policy["run_id"] == run_id
    assert policy["approval_id"] == approved["approval"]["approval_id"]
    assert policy["maximum_fee_mojos"] == 80
    assert policy["protected_shutdown_fee_mojos"] == 40
    assert policy["spent_fee_mojos"] == 0
    assert policy["held_fee_mojos"] == 0
    assert policy["revision"] == 0
    assert policy["dispatch_authorized"] is False


def test_fee_ceiling_review_is_append_only(approved):
    run_id, identity = _run(approved)
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO follow_fee_ceiling_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "1" * 64,
            "2" * 64,
            run_id,
            hashlib.sha256(encoded.encode()).hexdigest(),
            approved["approval"]["scope_sha256"],
            approved["approval"]["plan_sha256"],
            "a" * 64,
            0,
            80,
            120,
            40,
            120,
            1002,
            1302,
        ),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE follow_fee_ceiling_reviews SET proposed_maximum_fee_mojos=121 "
            "WHERE review_id=?",
            ("1" * 64,),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM follow_fee_ceiling_reviews WHERE review_id=?", ("1" * 64,)
        )
    conn.rollback()
    revision_approval = database.create_fee_approval(
        scope_sha256=approved["approval"]["scope_sha256"],
        plan_sha256=approved["approval"]["plan_sha256"],
        total_fee_mojos=120,
        cancellation_reserve_mojos=40,
    )
    conn.execute(
        "INSERT INTO follow_fee_ceiling_revisions VALUES (?,?,?,?,?,?,?)",
        (run_id, 1, "1" * 64, revision_approval["approval_id"], 120, 40, 1003),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE follow_fee_ceiling_revisions SET maximum_fee_mojos=121 "
            "WHERE run_id=? AND revision=1",
            (run_id,),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM follow_fee_ceiling_revisions WHERE run_id=? AND revision=1",
            (run_id,),
        )
