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


def test_ceiling_review_freezes_active_run_without_creating_authority(approved):
    run_id, identity = _run(approved)
    review = database.create_follow_fee_ceiling_review(
        run_id=run_id,
        identity=identity,
        configuration_sha256="a" * 64,
        proposed_maximum_fee_mojos=120,
        observed_fee_principal_mojos=120,
        now_epoch=1002,
    )
    assert len(review["review_id"]) == 64
    assert len(review["review_sha256"]) == 64
    assert review["dispatch_authorized"] is False
    stored = database.get_follow_fee_ceiling_review(review["review_id"])
    assert stored["review_sha256"] == review["review_sha256"]
    assert stored["run_id"] == run_id
    assert stored["prior_revision"] == 0
    assert stored["prior_maximum_fee_mojos"] == 80
    assert stored["proposed_maximum_fee_mojos"] == 120
    assert stored["expires_at_epoch"] == 1302
    assert stored["consumed"] is False
    assert (
        database.get_effective_follow_fee_policy(
            run_id=run_id, identity=identity, now_epoch=1002
        )["maximum_fee_mojos"]
        == 80
    )


@pytest.mark.parametrize(
    ("proposed", "principal", "configuration"),
    [
        (80, 80, "a" * 64),
        (39, 80, "a" * 64),
        (120, 119, "a" * 64),
        (120, 120, "b" * 64),
    ],
)
def test_ceiling_review_rejects_unchanged_unfunded_or_wrong_config(
    approved, proposed, principal, configuration
):
    run_id, identity = _run(approved)
    with pytest.raises(ValueError, match="FOLLOW_FEE_REVISION_"):
        database.create_follow_fee_ceiling_review(
            run_id=run_id,
            identity=identity,
            configuration_sha256=configuration,
            proposed_maximum_fee_mojos=proposed,
            observed_fee_principal_mojos=principal,
            now_epoch=1002,
        )
    conn = database.get_connection()
    assert (
        conn.execute("SELECT count(*) FROM follow_fee_ceiling_reviews").fetchone()[0]
        == 0
    )
    conn.close()


def test_ceiling_review_rejects_stopped_run(approved):
    run_id, identity = _run(approved)
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1003)
    with pytest.raises(ValueError, match="FOLLOW_FEE_REVISION_CHANGED"):
        database.create_follow_fee_ceiling_review(
            run_id=run_id,
            identity=identity,
            configuration_sha256="a" * 64,
            proposed_maximum_fee_mojos=120,
            observed_fee_principal_mojos=120,
            now_epoch=1004,
        )


def test_ceiling_review_getter_rejects_wrong_digest(approved):
    run_id, identity = _run(approved)
    review = database.create_follow_fee_ceiling_review(
        run_id=run_id,
        identity=identity,
        configuration_sha256="a" * 64,
        proposed_maximum_fee_mojos=120,
        observed_fee_principal_mojos=120,
        now_epoch=1002,
    )
    conn = database.get_connection()
    conn.execute("DROP TRIGGER follow_fee_ceiling_reviews_no_update")
    conn.execute(
        "UPDATE follow_fee_ceiling_reviews SET review_sha256=? WHERE review_id=?",
        ("0" * 64, review["review_id"]),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="FOLLOW_FEE_REVISION_REVIEW_MISMATCH"):
        database.get_follow_fee_ceiling_review(review["review_id"])


def test_effective_policy_reads_confirmed_revision_without_resetting_scope(approved):
    run_id, identity = _run(approved)
    review = database.create_follow_fee_ceiling_review(
        run_id=run_id,
        identity=identity,
        configuration_sha256="a" * 64,
        proposed_maximum_fee_mojos=120,
        observed_fee_principal_mojos=120,
        now_epoch=1002,
    )
    revised = database.create_fee_approval(
        scope_sha256=approved["approval"]["scope_sha256"],
        plan_sha256=approved["approval"]["plan_sha256"],
        total_fee_mojos=120,
        cancellation_reserve_mojos=40,
    )
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO follow_fee_ceiling_revisions VALUES (?,?,?,?,?,?,?)",
        (run_id, 1, review["review_id"], revised["approval_id"], 120, 40, 1003),
    )
    conn.commit()
    policy = database.get_effective_follow_fee_policy(
        run_id=run_id, identity=identity, now_epoch=1004
    )
    assert policy["ready"] is True
    assert policy["revision"] == 1
    assert policy["approval_id"] == revised["approval_id"]
    assert policy["maximum_fee_mojos"] == 120
    assert policy["remaining_fee_mojos"] == 120
    assert policy["scope_sha256"] == approved["approval"]["scope_sha256"]
    assert policy["dispatch_authorized"] is False

    second = database.create_follow_fee_ceiling_review(
        run_id=run_id,
        identity=identity,
        configuration_sha256="a" * 64,
        proposed_maximum_fee_mojos=100,
        observed_fee_principal_mojos=100,
        now_epoch=1005,
    )
    assert (
        database.get_follow_fee_ceiling_review(second["review_id"])["prior_revision"]
        == 1
    )
    assert (
        database.get_follow_fee_ceiling_review(second["review_id"])[
            "prior_maximum_fee_mojos"
        ]
        == 120
    )
    third_approval = database.create_fee_approval(
        scope_sha256=approved["approval"]["scope_sha256"],
        plan_sha256=approved["approval"]["plan_sha256"],
        total_fee_mojos=100,
        cancellation_reserve_mojos=40,
    )
    conn.execute(
        "INSERT INTO follow_fee_ceiling_revisions VALUES (?,?,?,?,?,?,?)",
        (run_id, 2, second["review_id"], third_approval["approval_id"], 100, 40, 1006),
    )
    conn.commit()
    conn.close()
    policy = database.get_effective_follow_fee_policy(
        run_id=run_id, identity=identity, now_epoch=1007
    )
    assert policy["ready"] is True
    assert policy["revision"] == 2
    assert policy["maximum_fee_mojos"] == 100
    assert policy["approval_id"] == third_approval["approval_id"]


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
    with pytest.raises(sqlite3.IntegrityError, match="binding mismatch"):
        conn.execute(
            "INSERT INTO follow_fee_ceiling_revisions VALUES (?,?,?,?,?,?,?)",
            (run_id, 1, "1" * 64, revision_approval["approval_id"], 121, 40, 1003),
        )
    conn.rollback()
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
