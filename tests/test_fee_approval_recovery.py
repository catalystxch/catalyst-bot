"""Fee holds require authoritative effect evidence, never caller settlement flags."""

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import database
import mutation_gate
import replacement_capacity


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    # Do not import another test module: conftest captures imports per collector.
    def clear_authorities():
        with database._wallet_effect_process_authorities_lock:
            states = list(database._wallet_effect_process_authorities.values())
            database._wallet_effect_process_authorities.clear()
        for state in states:
            mutation_gate.exit_wallet_mutation(state.permit)

    original_initialized = database._db_initialized_path
    clear_authorities()
    mutation_gate.shutdown_runtime()
    mutation_gate.clear_worker_authority_environment()
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "recovery.db"))
    database._db_initialized_path = ""
    monkeypatch.setattr(
        database, "_stability_wall_clock", lambda: "2026-08-21T12:00:00.000000Z"
    )
    yield
    clear_authorities()
    mutation_gate.shutdown_runtime()
    mutation_gate.clear_worker_authority_environment()
    database.close_connection()
    database._db_initialized_path = original_initialized


def _activate_wallet_authority(monkeypatch):
    now = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Fee Recovery Wallet",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=(now - timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=15,
    )
    monkeypatch.setattr(mutation_gate, "_utc_now", lambda: now)
    runtime = mutation_gate.initialize(
        run_id="fee-recovery",
        owner_pid=111,
        owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network="mainnet",
        lease_seconds=30,
        start_heartbeat=False,
        wallet_identity_binding=binding,
        wallet_adapter_authority=object(),
    )
    assert runtime.last_acquire_result["acquired"] is True
    return binding


def _prepared(monkeypatch):
    database.init_database()
    binding = _activate_wallet_authority(monkeypatch)
    identity = mutation_gate.wallet_identity_binding_payload(binding)
    source, fee_source = "1" * 64, "2" * 64
    target = {
        "contract_version": 2,
        "wallet_type": "cat",
        "cat_asset_id": "a" * 64,
        "fee_mojos": 10,
        "external_fee": {"fee_mojos": 10, "coin_ids": [fee_source]},
        "outputs": [
            {
                "output_index": 0,
                "asset": "cat",
                "address": "xch1batchowner",
                "amount_mojos": 90,
                "purpose": "replacement",
                "ordinal": 0,
            },
            {
                "output_index": 1,
                "asset": "xch",
                "address": "xch1batchowner",
                "amount_mojos": 20,
                "purpose": "fee_reserve",
                "ordinal": -1,
            },
        ],
    }
    contract = replacement_capacity.canonical_coin_prep_contract(
        operation_kind="split",
        purpose="replacement",
        source_coin_ids=[source],
        target_contract=target,
    )
    target = contract["target_contract"]
    operation_id = contract["operation_id"]
    database.upsert_coin(source, "cat", 90, purpose="replacement")
    database.upsert_coin(fee_source, "xch", 30, purpose="fee_reserve")
    claim = database.claim_wallet_effect(
        operation_id=operation_id,
        source_coin_ids=[source],
        fee_coin_ids=[fee_source],
    )
    database.prepare_coin_prep_operation(
        operation_kind="split",
        purpose="replacement",
        source_coin_ids=[source],
        target_contract=target,
        wallet_identity_json=identity,
        evidence_json={},
        effect_claim_token=claim["claim_token"],
        effect_claim_generation=claim["generation"],
    )
    constructed = [
        {**item, "coin_id": str(index + 3) * 64}
        for index, item in enumerate(target["outputs"])
    ]
    for item in constructed:
        del item["output_index"]
    database.bind_coin_prep_constructed_outputs(
        operation_id,
        plan_hash=target["plan_hash"],
        constructed_outputs=constructed,
    )
    approval = database.create_fee_approval(
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        total_fee_mojos=100,
        cancellation_reserve_mojos=20,
    )
    database.reserve_approved_fee(
        approval_id=approval["approval_id"],
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        operation_id=operation_id,
        fee_mojos=10,
        cancellation=False,
    )
    return operation_id, claim, identity, constructed, approval


def _submit(operation_id, claim):
    dispatch = database.begin_wallet_effect_dispatch(
        claim["claim_token"],
        claim["generation"],
        operation_id=operation_id,
        source_coin_ids=["1" * 64],
        fee_coin_ids=["2" * 64],
    )
    database.complete_wallet_effect_dispatch(dispatch, result={"success": True})
    return database.record_coin_prep_operation_outcome(
        operation_id,
        outcome="SUBMITTED_UNKNOWN",
        evidence_json={
            "reason_code": "WALLET_EFFECT_UNKNOWN_UNRECONCILED",
            "effect_claim_token": claim["claim_token"],
            "effect_claim_generation": claim["generation"],
            "dispatch_outcome": "UNKNOWN",
        },
    )["operation"]


def _evidence_id(operation):
    return hashlib.sha256(operation["outcome_evidence_json"].encode()).hexdigest()


def test_missing_authoritative_evidence_never_refunds_fee(
    isolated_database, monkeypatch
):
    operation_id, _, _, _, approval = _prepared(monkeypatch)
    assert callable(getattr(database, "record_fee_reservation_outcome", None)), (
        "authoritative fee settlement is missing"
    )
    with pytest.raises(ValueError, match="FEE_EFFECT_UNRESOLVED"):
        database.record_fee_reservation_outcome(operation_id, "f" * 64)
    state = database.get_fee_approval(approval["approval_id"])
    assert state["held_fee_mojos"] == 10
    assert state["spent_fee_mojos"] == 0


def test_caller_no_effect_flags_do_not_release_unresolved_claim(
    isolated_database, monkeypatch
):
    operation_id, claim, _, _, approval = _prepared(monkeypatch)
    operation = database.record_coin_prep_operation_outcome(
        operation_id,
        outcome="FAILED",
        evidence_json={
            "reason_code": "CALLER_TIMEOUT",
            "effect_claim_token": claim["claim_token"],
            "effect_claim_generation": claim["generation"],
            "dispatch_outcome": "RELEASED_NO_EFFECT",
            "effect_attempted": False,
        },
    )["operation"]
    with pytest.raises(ValueError, match="FEE_EFFECT_UNRESOLVED"):
        database.record_fee_reservation_outcome(operation_id, _evidence_id(operation))
    conn = database.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO approved_fee_outcomes VALUES (?, ?, ?, ?)",
            (
                operation_id,
                "RELEASED_NO_EFFECT",
                _evidence_id(operation),
                operation["outcome_evidence_json"],
            ),
        )
    conn.rollback()
    assert database.get_fee_approval(approval["approval_id"])["held_fee_mojos"] == 10


def test_timeout_and_restart_leave_submitted_fee_held(isolated_database, monkeypatch):
    operation_id, claim, _, _, approval = _prepared(monkeypatch)
    operation = _submit(operation_id, claim)
    assert callable(getattr(database, "record_fee_reservation_outcome", None)), (
        "authoritative fee settlement is missing"
    )
    with pytest.raises(ValueError, match="FEE_EFFECT_UNRESOLVED"):
        database.record_fee_reservation_outcome(operation_id, _evidence_id(operation))
    database.close_connection()
    database.init_database()
    state = database.get_fee_approval(approval["approval_id"])
    assert state["committed_fee_mojos"] == 10
    assert state["held_fee_mojos"] == 10


@pytest.mark.parametrize(
    "outcome,held,spent,remaining", [("CONFIRMED", 0, 10, 90), ("FAILED", 0, 0, 100)]
)
def test_exact_journal_evidence_settles_once(
    isolated_database, monkeypatch, outcome, held, spent, remaining
):
    operation_id, claim, identity, outputs, approval = _prepared(monkeypatch)
    _submit(operation_id, claim)
    common = {
        "effect_claim_token": claim["claim_token"],
        "effect_claim_generation": claim["generation"],
    }
    view = {
        "fresh": True,
        "complete": True,
        "wallet_identity": identity,
        "observed_at": "2026-08-21T12:00:01.000000Z",
        "expires_at": "2026-08-21T12:00:16.000000Z",
    }
    if outcome == "CONFIRMED":
        expected = [
            {
                "coin_id": item["coin_id"],
                "amount_mojos": item["amount_mojos"],
                "purpose": item["purpose"],
            }
            for item in outputs
        ]
        evidence = {
            **common,
            "reason_code": "AUTHORITATIVE_POST_VIEW_CONFIRMED",
            "source_coin_ids": ["1" * 64],
            "expected_outputs": expected,
            "authoritative_view": {**view, "coins": expected},
            "expected_wallet_identity": identity,
        }
    else:
        evidence = {
            **common,
            "reason_code": "AUTHORITATIVE_NO_EFFECT_CONFIRMED",
            "dispatch_outcome": "RELEASED_NO_EFFECT",
            "effect_attempted": False,
            "source_coin_ids": ["1" * 64],
            "fee_coin_ids": ["2" * 64],
            "authoritative_view": {
                **view,
                "selectable_coin_ids": ["1" * 64, "2" * 64],
                "pending_transaction_ids": [],
            },
            "expected_wallet_identity": identity,
        }
    operation = database.record_coin_prep_operation_outcome(
        operation_id, outcome=outcome, evidence_json=evidence
    )["operation"]
    assert callable(getattr(database, "record_fee_reservation_outcome", None)), (
        "authoritative fee settlement is missing"
    )
    with pytest.raises(ValueError, match="FEE_EVIDENCE_MISMATCH"):
        database.record_fee_reservation_outcome(operation_id, "f" * 64)
    database.record_fee_reservation_outcome(operation_id, _evidence_id(operation))
    database.record_fee_reservation_outcome(operation_id, _evidence_id(operation))
    conn = database.get_connection()
    for statement in [
        "UPDATE approved_fee_outcomes SET evidence_json='{}'",
        "DELETE FROM approved_fee_outcomes",
        "INSERT OR REPLACE INTO approved_fee_outcomes "
        "SELECT operation_id, state, evidence_id, '{}' FROM approved_fee_outcomes",
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
        conn.rollback()
    reset = database.guarded_reset_authoritative_state(clear_terminal_offers=True)
    assert reset["success"] is True
    database.reset_lifecycle_observability_stats()
    database.close_connection()
    database.init_database()
    state = database.get_fee_approval(approval["approval_id"])
    assert state["held_fee_mojos"] == held
    assert state["spent_fee_mojos"] == spent
    assert state["remaining_fee_mojos"] == remaining
    second = database.create_fee_approval(
        scope_sha256="a" * 64,
        plan_sha256="b" * 64,
        total_fee_mojos=200,
        cancellation_reserve_mojos=20,
    )
    assert second["spent_fee_mojos"] == spent
    assert second["remaining_fee_mojos"] == remaining + 100
    assert second["committed_fee_mojos"] == spent
    if outcome == "FAILED":
        database.reserve_approved_fee(
            approval_id=second["approval_id"],
            scope_sha256="a" * 64,
            plan_sha256="b" * 64,
            operation_id="9" * 64,
            fee_mojos=180,
            cancellation=False,
        )
        assert database.get_fee_approval(second["approval_id"])["held_fee_mojos"] == 180
