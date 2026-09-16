"""Fee approvals must survive restarts and serialize competing spenders."""

from concurrent.futures import ThreadPoolExecutor

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
    assert recovered == original
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
