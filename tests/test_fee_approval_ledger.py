"""Fee approvals must survive restarts and serialize competing spenders."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

import database


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "fees.db"))
    database.init_database()
    yield database
    database.close_connection()


def _approval(ledger, total=10_000_000_000, cancellation=2_000_000_000):
    assert callable(getattr(ledger, "create_fee_approval", None)), (
        "durable fee approval is missing"
    )
    return ledger.create_fee_approval(
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        total_fee_mojos=total,
        cancellation_reserve_mojos=cancellation,
    )


def test_observed_relay_fee_cannot_consume_cancellation_reserve(ledger):
    approval = _approval(ledger)
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        ledger.reserve_approved_fee(
            approval_id=approval["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id="1" * 64,
            fee_mojos=8_016_000_000,
            cancellation=False,
        )
    assert ledger.get_fee_approval(approval["approval_id"])["committed_fee_mojos"] == 0


def test_cap_increase_counts_prior_pending_fees(ledger):
    first = _approval(ledger, total=100_000_000_000, cancellation=20_000_000_000)
    ledger.reserve_approved_fee(
        approval_id=first["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=8_016_000_000,
        cancellation=False,
    )
    second = _approval(ledger, total=200_000_000_000, cancellation=40_000_000_000)
    assert (
        ledger.get_fee_approval(second["approval_id"])["committed_fee_mojos"]
        == 8_016_000_000
    )
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        ledger.reserve_approved_fee(
            approval_id=first["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id="2" * 64,
            fee_mojos=2_508_000_000,
            cancellation=False,
        )


def test_duplicate_operation_is_not_charged_twice(ledger):
    approval = _approval(ledger)
    args = dict(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=1_000_000_000,
        cancellation=False,
    )
    ledger.reserve_approved_fee(**args)
    ledger.reserve_approved_fee(**args)
    assert (
        ledger.get_fee_approval(approval["approval_id"])["committed_fee_mojos"]
        == 1_000_000_000
    )
    with pytest.raises(ValueError, match="FEE_OPERATION_CONFLICT"):
        ledger.reserve_approved_fee(**{**args, "fee_mojos": 2_000_000_000})


def test_prior_reservation_can_be_recovered_after_cap_increase(ledger):
    first = _approval(ledger)
    args = dict(
        approval_id=first["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=1_000_000_000,
        cancellation=False,
    )
    original = ledger.reserve_approved_fee(**args)
    second = _approval(ledger, total=100_000_000_000, cancellation=20_000_000_000)
    recovered = ledger.reserve_approved_fee(**args)
    assert recovered["operation_id"] == original["operation_id"]
    assert recovered["fee_mojos"] == original["fee_mojos"]
    assert (
        ledger.get_fee_approval(second["approval_id"])["committed_fee_mojos"]
        == 1_000_000_000
    )


def test_wrong_identity_cannot_use_approval(ledger):
    approval = _approval(ledger)
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        ledger.reserve_approved_fee(
            approval_id=approval["approval_id"],
            scope_sha256="c" * 64,
            plan_sha256="b" * 64,
            operation_id="1" * 64,
            fee_mojos=1,
            cancellation=False,
        )


def test_cancellation_can_use_protected_allowance_but_not_exceed_total(ledger):
    approval = _approval(ledger)
    for operation, fee, cancellation in [
        ("1", 8_000_000_000, False),
        ("2", 2_000_000_000, True),
    ]:
        ledger.reserve_approved_fee(
            approval_id=approval["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id=operation * 64,
            fee_mojos=fee,
            cancellation=cancellation,
        )
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        ledger.reserve_approved_fee(
            approval_id=approval["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id="3" * 64,
            fee_mojos=1,
            cancellation=True,
        )


def test_concurrent_reservations_cannot_each_spend_same_remainder(ledger):
    approval = _approval(ledger)

    def reserve(operation):
        try:
            ledger.reserve_approved_fee(
                approval_id=approval["approval_id"],
                scope_sha256="a" * 64,
                plan_sha256="b" * 64,
                operation_id=str(operation) * 64,
                fee_mojos=5_000_000_000,
                cancellation=False,
            )
            return True
        except ValueError as exc:
            assert str(exc) == "FEE_BUDGET_EXCEEDED"
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [1, 2]))
    assert sorted(results) == [False, True]
    assert (
        ledger.get_fee_approval(approval["approval_id"])["committed_fee_mojos"]
        == 5_000_000_000
    )


def test_reservation_survives_connection_restart(ledger):
    approval = _approval(ledger)
    ledger.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=7_000_000_000,
        cancellation=False,
    )
    ledger.close_connection()
    ledger.init_database()
    assert (
        ledger.get_fee_approval(approval["approval_id"])["committed_fee_mojos"]
        == 7_000_000_000
    )
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        ledger.reserve_approved_fee(
            approval_id=approval["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id="2" * 64,
            fee_mojos=2_000_000_000,
            cancellation=False,
        )


@pytest.mark.parametrize("fee", [True, 1.0, "1", -1, 2**63])
def test_invalid_fee_cannot_create_commitment(ledger, fee):
    approval = _approval(ledger)
    with pytest.raises(ValueError):
        ledger.reserve_approved_fee(
            approval_id=approval["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id="1" * 64,
            fee_mojos=fee,
            cancellation=False,
        )
    assert ledger.get_fee_approval(approval["approval_id"])["committed_fee_mojos"] == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE fee_approvals SET total_fee_mojos=20000000000",
        "DELETE FROM fee_approvals",
        "UPDATE approved_fee_reservations SET fee_mojos=0",
        "DELETE FROM approved_fee_reservations",
    ],
)
def test_approved_economics_and_commitments_cannot_be_rewritten(ledger, statement):
    approval = _approval(ledger)
    ledger.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=123,
        cancellation=False,
    )
    conn = ledger.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(statement)
    conn.rollback()
    assert (
        ledger.get_fee_approval(approval["approval_id"])["committed_fee_mojos"] == 123
    )


def test_fractional_fee_cannot_enter_durable_schema(ledger):
    approval = _approval(ledger)
    with pytest.raises(sqlite3.IntegrityError):
        ledger.get_connection().execute(
            "INSERT INTO approved_fee_reservations VALUES (?, ?, ?, ?, ?, ?)",
            ("1" * 64, approval["approval_id"], "a" * 64, "b" * 64, 1.5, 0),
        )
    ledger.get_connection().rollback()


def test_schema_validation_rejects_fee_index_with_wrong_scope(ledger):
    conn = ledger.get_connection()
    conn.execute("DROP INDEX IF EXISTS idx_approved_fee_reservations_scope")
    conn.execute(
        "CREATE INDEX idx_approved_fee_reservations_scope ON approved_fee_reservations(plan_sha256)"
    )
    with pytest.raises(RuntimeError, match="idx_approved_fee_reservations_scope"):
        ledger._validate_stability_schema(conn)
    conn.rollback()


def test_new_ceiling_cannot_forget_committed_fees(ledger):
    approval = _approval(ledger)
    ledger.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=7_000_000_000,
        cancellation=False,
    )
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        _approval(ledger, total=6_000_000_000, cancellation=2_000_000_000)


LEGACY_SCHEMA = """
CREATE TABLE fee_approvals (
    approval_id TEXT PRIMARY KEY, scope_sha256 TEXT NOT NULL,
    plan_sha256 TEXT NOT NULL, version INTEGER NOT NULL,
    total_fee_mojos INTEGER NOT NULL CHECK(total_fee_mojos >= 0),
    cancellation_reserve_mojos INTEGER NOT NULL CHECK(cancellation_reserve_mojos >= 0),
    UNIQUE(scope_sha256, version)
);
CREATE TABLE approved_fee_reservations (
    operation_id TEXT PRIMARY KEY,
    approval_id TEXT NOT NULL REFERENCES fee_approvals(approval_id),
    scope_sha256 TEXT NOT NULL, plan_sha256 TEXT NOT NULL,
    fee_mojos INTEGER NOT NULL CHECK(fee_mojos >= 0),
    cancellation INTEGER NOT NULL CHECK(cancellation IN (0, 1))
);
"""


def _install_legacy(ledger, approval_id, fee=123, schema=LEGACY_SCHEMA):
    conn = ledger.get_connection()
    conn.executescript(
        "DROP TABLE coin_prep_fee_consents; DROP TABLE coin_prep_fee_previews; "
        "DROP TABLE approved_fee_outcomes; DROP TABLE approved_fee_reservations; DROP TABLE fee_approvals;"
        + schema
    )
    conn.execute(
        "INSERT INTO fee_approvals VALUES (?, ?, ?, 1, 10000000000, 2000000000)",
        (approval_id, "a" * 64, "b" * 64),
    )
    conn.execute(
        "INSERT INTO approved_fee_reservations VALUES (?, ?, ?, ?, ?, 0)",
        ("1" * 64, approval_id, "a" * 64, "b" * 64, fee),
    )
    conn.commit()


def test_exact_pr218_schema_upgrades_without_losing_pending_fee(ledger):
    approval = _approval(ledger)
    _install_legacy(ledger, approval["approval_id"])
    ledger._migrate_stability_schema()
    assert (
        ledger.get_fee_approval(approval["approval_id"])["committed_fee_mojos"] == 123
    )
    with pytest.raises(sqlite3.IntegrityError):
        ledger.get_connection().execute("DELETE FROM approved_fee_reservations")
    ledger.get_connection().rollback()


def test_legacy_fractional_commitment_blocks_upgrade_without_refund(ledger):
    approval = _approval(ledger)
    _install_legacy(ledger, approval["approval_id"], fee=1.5)
    with pytest.raises((RuntimeError, sqlite3.IntegrityError)):
        ledger._migrate_stability_schema()
    assert (
        ledger.get_connection()
        .execute("SELECT fee_mojos FROM approved_fee_reservations")
        .fetchone()[0]
        == 1.5
    )


def test_legacy_shape_drift_is_not_silently_repaired(ledger):
    approval = _approval(ledger)
    _install_legacy(
        ledger,
        approval["approval_id"],
        schema=LEGACY_SCHEMA.replace("CHECK(fee_mojos >= 0)", "CHECK(fee_mojos >= -1)"),
    )
    with pytest.raises(RuntimeError, match="fee"):
        ledger._migrate_stability_schema()
    assert (
        ledger.get_connection()
        .execute("SELECT fee_mojos FROM approved_fee_reservations")
        .fetchone()[0]
        == 123
    )


def test_reservation_replay_is_not_a_new_dispatch_permission(ledger):
    approval = _approval(ledger)
    args = dict(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=123,
        cancellation=False,
    )
    original = ledger.reserve_approved_fee(**args)
    replay = ledger.reserve_approved_fee(**args)
    assert original["idempotent"] is False
    assert replay["idempotent"] is True


def test_new_approval_cannot_reduce_protected_cancellation_allowance(ledger):
    _approval(ledger)
    with pytest.raises(ValueError, match="FEE_CANCEL_PROTECTION_DECREASED"):
        _approval(ledger, total=20_000_000_000, cancellation=1_000_000_000)


def test_history_and_observability_reset_preserve_approval_and_hold(ledger):
    approval = _approval(ledger)
    ledger.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=123,
        cancellation=False,
    )
    result = ledger.guarded_reset_authoritative_state(clear_terminal_offers=True)
    assert result["success"] is True
    ledger.reset_lifecycle_observability_stats()
    ledger.close_connection()
    ledger.init_database()
    state = ledger.get_fee_approval(approval["approval_id"])
    assert state["total_fee_mojos"] == 10_000_000_000
    assert state["cancellation_reserve_mojos"] == 2_000_000_000
    assert state["held_fee_mojos"] == 123
    assert state["spent_fee_mojos"] == 0


def test_exact_held_total_near_sqlite_limit_does_not_overflow(ledger):
    approval = _approval(ledger, total=2**63 - 1, cancellation=0)
    for operation, fee in [("1", 2**62), ("2", 2**62 - 1)]:
        ledger.reserve_approved_fee(
            approval_id=approval["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id=operation * 64,
            fee_mojos=fee,
            cancellation=False,
        )
    state = ledger.get_fee_approval(approval["approval_id"])
    assert state["held_fee_mojos"] == 2**63 - 1
    assert state["remaining_fee_mojos"] == 0
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        ledger.reserve_approved_fee(
            approval_id=approval["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id="3" * 64,
            fee_mojos=1,
            cancellation=False,
        )


@pytest.mark.parametrize("table", ["fee_approvals", "approved_fee_reservations"])
def test_replace_cannot_rewrite_immutable_fee_rows(ledger, table):
    approval = _approval(ledger)
    ledger.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=123,
        cancellation=False,
    )
    conn = ledger.get_connection()
    if table == "fee_approvals":
        statement = (
            "INSERT OR REPLACE INTO fee_approvals "
            "SELECT approval_id, scope_sha256, plan_sha256, version, "
            "20000000000, cancellation_reserve_mojos FROM fee_approvals"
        )
    else:
        statement = (
            "INSERT OR REPLACE INTO approved_fee_reservations "
            "SELECT operation_id, approval_id, scope_sha256, plan_sha256, "
            "0, cancellation FROM approved_fee_reservations"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(statement)
    conn.rollback()
    state = ledger.get_fee_approval(approval["approval_id"])
    assert state["total_fee_mojos"] == 10_000_000_000
    assert state["held_fee_mojos"] == 123


def test_preparation_readback_accounts_for_consumed_cancellation_fees(ledger):
    approval = _approval(ledger, total=100, cancellation=20)
    ledger.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=50,
        cancellation=True,
    )
    state = ledger.get_fee_approval(approval["approval_id"])
    assert state["remaining_preparation_fee_mojos"] == 50


def test_unbound_outcome_insert_cannot_refund_a_hold(ledger):
    approval = _approval(ledger)
    ledger.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id="1" * 64,
        fee_mojos=123,
        cancellation=False,
    )
    conn = ledger.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO approved_fee_outcomes VALUES (?, ?, ?, ?)",
            ("1" * 64, "RELEASED_NO_EFFECT", "f" * 64, "{}"),
        )
    conn.rollback()
    assert ledger.get_fee_approval(approval["approval_id"])["held_fee_mojos"] == 123
