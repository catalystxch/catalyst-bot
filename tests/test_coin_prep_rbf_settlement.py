"""RBF winner proof must come from confirmed chain records, not a preview."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import database


SOURCE = "1" * 64
ORIGINAL_TX = "2" * 64
SUCCESSOR_TX = "3" * 64
ATTEMPT = "4" * 64
SHARED = [f"{index + 10:064x}" for index in range(4)]
OLD_CHANGE = "a" * 64
NEW_CHANGE = "b" * 64
FEE_COIN_AMOUNT = 20_000_000_000
CHANGE = 1_435_390_971_590
FEE = 15_654_431


def _utc(offset=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _outputs(change_id, change_amount):
    return [
        {"coin_id": coin_id, "amount_mojos": FEE_COIN_AMOUNT,
         "purpose": "fee_reserve"}
        for coin_id in SHARED
    ] + [{"coin_id": change_id, "amount_mojos": change_amount,
          "purpose": "top_up"}]


def _facts(winner):
    original = _outputs(OLD_CHANGE, CHANGE)
    successor = _outputs(NEW_CHANGE, CHANGE - FEE)
    attempt = {
        "attempt_id": ATTEMPT,
        "original_transaction_id": ORIGINAL_TX,
        "original_outputs_json": json.dumps(original),
        "successor_outputs_json": json.dumps(successor),
    }
    operation = {
        "source_coin_ids_json": json.dumps([SOURCE]),
        "wallet_identity_json": json.dumps({"network_id": "mainnet"}),
    }
    winning = original if winner == "ORIGINAL" else successor
    chain = {
        "complete": True,
        "network": "mainnet",
        "observed_at": _utc(0),
        "source_coin_id": SOURCE,
        "source_spent_height": 100,
        "coins": [
            {"coin_id": item["coin_id"], "amount_mojos": item["amount_mojos"],
             "confirmed_height": (
                 100 if item["coin_id"] in {output["coin_id"] for output in winning}
                 else None
             )}
            for item in [*original, successor[-1]]
        ],
    }
    evidence = {
        "rbf_attempt_id": ATTEMPT,
        "reason_code": (
            "AUTHORITATIVE_RBF_ORIGINAL_CONFIRMED"
            if winner == "ORIGINAL"
            else "AUTHORITATIVE_RBF_REPLACEMENT_CONFIRMED"
        ),
        "winner_transaction_id": (
            ORIGINAL_TX if winner == "ORIGINAL" else SUCCESSOR_TX
        ),
        "rbf_chain_view": chain,
        "expected_outputs": winning,
    }
    return operation, attempt, evidence


@pytest.mark.parametrize("winner", ["ORIGINAL", "SUCCESSOR"])
def test_only_height_proven_winner_settles(winner):
    operation, attempt, evidence = _facts(winner)
    expected_tx = ORIGINAL_TX if winner == "ORIGINAL" else SUCCESSOR_TX
    assert database._verify_coin_prep_rbf_winner(
        operation, attempt, evidence
    ) == (winner, expected_tx)


def test_ambiguous_two_changes_confirmed_is_rejected():
    operation, attempt, evidence = _facts("SUCCESSOR")
    evidence["rbf_chain_view"]["coins"][-2]["confirmed_height"] = 100
    with pytest.raises(ValueError, match="winner is not proven"):
        database._verify_coin_prep_rbf_winner(operation, attempt, evidence)


def test_no_source_spend_height_is_rejected():
    operation, attempt, evidence = _facts("SUCCESSOR")
    evidence["rbf_chain_view"]["source_spent_height"] = 0
    with pytest.raises(ValueError):
        database._verify_coin_prep_rbf_winner(operation, attempt, evidence)


def test_unsigned_only_has_no_chain_proof():
    operation, attempt, evidence = _facts("SUCCESSOR")
    evidence["rbf_chain_view"] = None
    with pytest.raises(ValueError, match="not complete"):
        database._verify_coin_prep_rbf_winner(operation, attempt, evidence)


@pytest.mark.parametrize("winner", ["ORIGINAL", "SUCCESSOR"])
def test_resolution_commits_operation_attempt_coins_and_latch_together(
    tmp_path, monkeypatch, winner
):
    path = tmp_path / "rbf.db"
    monkeypatch.setattr(database, "DB_PATH", str(path))
    conn = database._sqlite_connect(path)
    conn.row_factory = __import__("sqlite3").Row
    conn.executescript(database.SCHEMA_SQL + database.STABILITY_SCHEMA_SQL)
    for column in (
        "designation TEXT", "assigned_tier TEXT",
    ):
        conn.execute(f"ALTER TABLE coins ADD COLUMN {column}")
    database._validate_stability_schema(conn)
    operation_id = "coin-prep:" + "5" * 64
    claim = "6" * 64
    identity = {
        "backend": "sage", "name": "wallet", "fingerprint": 736588221,
        "network_id": "mainnet", "kind": "bls", "has_secrets": True,
        "bound_at_utc": _utc(-10), "maximum_age_seconds": 300,
    }
    identity_json = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    target = {"wallet_type": "xch", "outputs": [
        {"output_index": index, "amount_mojos": FEE_COIN_AMOUNT,
         "purpose": "fee_reserve"} for index in range(4)
    ] + [{"output_index": 4, "amount_mojos": CHANGE, "purpose": "top_up"}]}
    op_fields = (
        operation_id, "split", "fee_reserve", json.dumps([SOURCE]),
        json.dumps(target), identity_json, "{}", claim, 1,
        "SUBMITTED_UNKNOWN", json.dumps({
            "reason_code": "SUBMITTED_UNKNOWN", "effect_claim_token": claim,
            "effect_claim_generation": 1, "dispatch_outcome": "SUBMITTED",
        }), _utc(-5),
    )
    conn.execute(
        "INSERT INTO coin_prep_operations (operation_id,operation_kind,purpose,"
        "source_coin_ids_json,target_contract_json,wallet_identity_json,"
        "prepared_evidence_json,effect_claim_token,effect_claim_generation,"
        "outcome,outcome_evidence_json,prepared_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        op_fields,
    )
    conn.execute(
        "UPDATE runtime_safety_latch SET generation=1,state='tripped',"
        "reason_code='COIN_PREP_RECOVERY_REQUIRED',"
        "blocking_operation_ids_json=?,wallet_fingerprint_hash=?,network='mainnet' "
        "WHERE singleton_id=1",
        (json.dumps(sorted([operation_id, f"wallet-effect:{claim}"])),
         __import__("mutation_gate").wallet_fingerprint_hash(identity["fingerprint"])),
    )
    original = _outputs(OLD_CHANGE, CHANGE)
    successor = _outputs(NEW_CHANGE, CHANGE - FEE)
    conn.execute(
        "INSERT INTO coin_prep_rbf_attempts (attempt_id,operation_id,"
        "original_transaction_id,unsigned_sha256,review_sha256,fee_mojos,"
        "original_outputs_json,successor_outputs_json,wallet_identity_sha256,"
        "latch_generation,reviewed_at,review_expires_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ATTEMPT, operation_id, ORIGINAL_TX, "7" * 64, "8" * 64, FEE,
         json.dumps(original), json.dumps(successor), "9" * 64, 1,
         _utc(-3), _utc(60)),
    )
    conn.execute(
        "INSERT INTO coin_prep_rbf_dispatches "
        "(attempt_id,operation_id,lease_version,owner_run_id,started_at) "
        "VALUES (?,?,?,?,?)", (ATTEMPT, operation_id, 1, "run", _utc(-2)),
    )
    conn.commit()
    conn.close()

    _, _, proof = _facts(winner)
    expected = original if winner == "ORIGINAL" else successor
    authoritative = {
        "fresh": True, "complete": True, "wallet_identity": identity,
        "observed_at": _utc(0), "expires_at": _utc(300),
        "coins": expected,
    }
    # Use one timestamp for the exact expiry relationship.
    authoritative["expires_at"] = (
        datetime.fromisoformat(authoritative["observed_at"].replace("Z", "+00:00"))
        + timedelta(seconds=300)
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    ambiguous = json.loads(json.dumps(proof["rbf_chain_view"]))
    ambiguous["coins"][-2]["confirmed_height"] = 100
    ambiguous["coins"][-1]["confirmed_height"] = 100
    with pytest.raises(ValueError, match="winner is not proven"):
        database.resolve_coin_prep_rbf_attempt(
            ATTEMPT, winner=winner,
            winner_transaction_id=proof["winner_transaction_id"],
            chain_view=ambiguous, authoritative_view=authoritative,
        )
    with pytest.raises(ValueError, match="joint no-effect proof"):
        database.record_coin_prep_operation_outcome(
            operation_id, outcome="FAILED", evidence_json={
                "reason_code": "NO_EFFECT_GUESSED",
                "effect_claim_token": claim,
                "effect_claim_generation": 1,
                "dispatch_outcome": "RELEASED_NO_EFFECT",
                "effect_attempted": False,
            },
        )
    still = database._stability_read_only_connection()
    try:
        assert still.execute(
            "SELECT outcome FROM coin_prep_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()["outcome"] == "SUBMITTED_UNKNOWN"
        assert still.execute(
            "SELECT state FROM runtime_safety_latch WHERE singleton_id=1"
        ).fetchone()["state"] == "tripped"
        assert still.execute(
            "SELECT 1 FROM coin_prep_rbf_resolutions WHERE attempt_id=?",
            (ATTEMPT,),
        ).fetchone() is None
    finally:
        still.close()
    result = database.resolve_coin_prep_rbf_attempt(
        ATTEMPT, winner=winner,
        winner_transaction_id=proof["winner_transaction_id"],
        chain_view=proof["rbf_chain_view"],
        authoritative_view=authoritative,
    )
    assert result["operation"]["outcome"] == "CONFIRMED"
    check = database._stability_read_only_connection()
    try:
        resolution = check.execute(
            "SELECT winner FROM coin_prep_rbf_resolutions WHERE attempt_id=?",
            (ATTEMPT,),
        ).fetchone()
        latch = check.execute(
            "SELECT state,blocking_operation_ids_json FROM runtime_safety_latch "
            "WHERE singleton_id=1"
        ).fetchone()
        assert resolution["winner"] == winner
        assert latch["state"] == "resolved"
        assert json.loads(latch["blocking_operation_ids_json"]) == []
        coins = check.execute(
            "SELECT coin_id FROM coins WHERE coin_id IN (?,?,?,?,?)",
            tuple("0x" + item["coin_id"] for item in expected),
        ).fetchall()
        assert len(coins) == 5
    finally:
        check.close()


def test_successor_adoption_requires_dead_expired_exact_owner(tmp_path, monkeypatch):
    path = tmp_path / "adopt.db"
    monkeypatch.setattr(database, "DB_PATH", str(path))
    conn = database._sqlite_connect(path)
    conn.row_factory = __import__("sqlite3").Row
    conn.executescript(database.SCHEMA_SQL + database.STABILITY_SCHEMA_SQL)
    op_id = "coin-prep:" + "5" * 64
    claim = "6" * 64
    identity = {
        "backend": "sage", "name": "wallet", "fingerprint": 736588221,
        "network_id": "mainnet", "kind": "bls", "has_secrets": True,
        "bound_at_utc": _utc(-10), "maximum_age_seconds": 300,
    }
    wallet_hash = __import__("mutation_gate").wallet_fingerprint_hash(
        identity["fingerprint"]
    )
    conn.execute(
        "INSERT INTO coin_prep_operations (operation_id,operation_kind,purpose,"
        "source_coin_ids_json,target_contract_json,wallet_identity_json,"
        "prepared_evidence_json,effect_claim_token,effect_claim_generation,"
        "outcome,prepared_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (op_id, "split", "fee_reserve", json.dumps([SOURCE]),
         json.dumps({"wallet_type": "xch", "outputs": [
             {"output_index": index, "amount_mojos": FEE_COIN_AMOUNT,
              "purpose": "fee_reserve"} for index in range(4)
         ] + [{"output_index": 4, "amount_mojos": CHANGE,
               "purpose": "top_up"}]}),
         json.dumps(identity), "{}", claim, 1, "SUBMITTED_UNKNOWN", _utc(-100)),
    )
    conn.execute(
        "UPDATE runtime_safety_latch SET generation=1,state='tripped',"
        "reason_code='COIN_PREP_RECOVERY_REQUIRED',"
        "blocking_operation_ids_json=?,wallet_fingerprint_hash=?,network='mainnet' "
        "WHERE singleton_id=1",
        (json.dumps(sorted([op_id, f"wallet-effect:{claim}"])), wallet_hash),
    )
    prior_acquired = _utc(-100)
    prior_expires = _utc(-1)
    conn.execute(
        "UPDATE runtime_mutation_lease SET lease_version=1,active=1,"
        "owner_run_id='prior',owner_pid=123,owner_host='host',"
        "wallet_fingerprint_hash=?,network='mainnet',acquired_at=?,"
        "heartbeat_at=?,expires_at=?,released_at=NULL WHERE singleton_id=1",
        (wallet_hash, prior_acquired, prior_acquired, prior_expires),
    )
    conn.commit()
    conn.close()
    kwargs = {
        "operation_id": op_id,
        "expected_latch_generation": 1,
        "expected_lease_version": 1,
        "expected_prior_owner_run_id": "prior",
        "expected_prior_owner_pid": 123,
        "expected_prior_owner_host": "host",
        "expected_prior_acquired_at": prior_acquired,
        "expected_prior_expires_at": prior_expires,
        "expected_prior_released_at": None,
        "successor_owner_run_id": "successor",
        "successor_owner_pid": 456,
        "successor_owner_host": "host",
        "lease_expires_at": _utc(90),
        "prior_owner_liveness_proven_dead": False,
        "observed_at": _utc(0),
    }
    with pytest.raises(ValueError, match="not proven dead"):
        database.adopt_coin_prep_rbf_successor(**kwargs)
    kwargs["prior_owner_liveness_proven_dead"] = True
    result = database.adopt_coin_prep_rbf_successor(**kwargs)
    assert result["adopted"] is True
    assert result["lease"]["owner_run_id"] == "successor"
    assert result["lease"]["lease_version"] == 2
    v2_conn = database._stability_connection()
    try:
        old_target = v2_conn.execute(
            "SELECT target_contract_json FROM coin_prep_operations WHERE operation_id=?",
            (op_id,),
        ).fetchone()["target_contract_json"]
        v2_target = json.loads(old_target)
        v2_target["contract_version"] = 2
        v2_conn.execute(
            "UPDATE coin_prep_operations SET target_contract_json=? "
            "WHERE operation_id=?", (json.dumps(v2_target), op_id),
        )
        v2_conn.commit()
        with pytest.raises(ValueError, match="exact XCH fee split"):
            database.prepare_coin_prep_rbf_attempt(
                operation_id=op_id, original_transaction_id=ORIGINAL_TX,
                unsigned_sha256="7" * 64, review_sha256="8" * 64,
                fee_mojos=FEE,
                original_outputs=_outputs(OLD_CHANGE, CHANGE),
                successor_outputs=_outputs(NEW_CHANGE, CHANGE - FEE),
                latch_generation=1, reviewed_at=_utc(-1),
                review_expires_at=_utc(60),
            )
        v2_conn.execute(
            "UPDATE coin_prep_operations SET target_contract_json=? "
            "WHERE operation_id=?", (old_target, op_id),
        )
        v2_conn.commit()
    finally:
        v2_conn.close()
    first = database.prepare_coin_prep_rbf_attempt(
        operation_id=op_id, original_transaction_id=ORIGINAL_TX,
        unsigned_sha256="7" * 64, review_sha256="8" * 64, fee_mojos=FEE,
        original_outputs=_outputs(OLD_CHANGE, CHANGE),
        successor_outputs=_outputs(NEW_CHANGE, CHANGE - FEE),
        latch_generation=1, reviewed_at=_utc(-1), review_expires_at=_utc(60),
    )["attempt"]
    second = database.prepare_coin_prep_rbf_attempt(
        operation_id=op_id, original_transaction_id=ORIGINAL_TX,
        unsigned_sha256="9" * 64, review_sha256="a" * 64, fee_mojos=FEE,
        original_outputs=_outputs(OLD_CHANGE, CHANGE),
        successor_outputs=_outputs(NEW_CHANGE, CHANGE - FEE),
        latch_generation=1, reviewed_at=_utc(-1), review_expires_at=_utc(60),
    )["attempt"]
    assert first["attempt_id"] != second["attempt_id"]
    expired = database.prepare_coin_prep_rbf_attempt(
        operation_id=op_id, original_transaction_id=ORIGINAL_TX,
        unsigned_sha256="c" * 64, review_sha256="d" * 64, fee_mojos=FEE,
        original_outputs=_outputs(OLD_CHANGE, CHANGE),
        successor_outputs=_outputs(NEW_CHANGE, CHANGE - FEE),
        latch_generation=1, reviewed_at=_utc(-100), review_expires_at=_utc(-50),
    )["attempt"]
    with pytest.raises(ValueError, match="time is not current"):
        database.record_coin_prep_rbf_dispatch_start(
            expired["attempt_id"], owner_run_id="successor", lease_version=2,
            started_at=_utc(-60),
        )
    with pytest.raises(ValueError, match="review has changed"):
        database.record_coin_prep_rbf_dispatch_start(
            expired["attempt_id"], owner_run_id="successor", lease_version=2,
        )
    pre = database.authorize_coin_prep_rbf_rescue_target(
        attempt_id=first["attempt_id"], operation_id=op_id,
        expected_latch_generation=1, unsigned_sha256="7" * 64,
        owner_run_id="successor", lease_version=2,
    )
    assert pre["dispatch_started"] is False
    database.record_coin_prep_rbf_sign_start(
        second["attempt_id"], owner_run_id="successor", lease_version=2
    )
    with pytest.raises(ValueError, match="not proven stopped"):
        database.record_coin_prep_rbf_sign_no_submit(
            second["attempt_id"],
            receipt={
                "attempt_id": second["attempt_id"],
                "reason_code": "CRASH_BEFORE_SUBMIT_MARKER",
                "submit_rpc_attempted": False,
                "evidence_sha256": "d" * 64,
            },
            prior_owner_liveness_proven_dead=True,
        )
    inactive = database._stability_connection()
    try:
        inactive.execute(
            "UPDATE runtime_mutation_lease SET active=0, released_at=? "
            "WHERE singleton_id=1", (_utc(0),),
        )
        inactive.commit()
    finally:
        inactive.close()
    database.record_coin_prep_rbf_sign_no_submit(
        second["attempt_id"], receipt={
            "attempt_id": second["attempt_id"],
            "reason_code": "CRASH_BEFORE_SUBMIT_MARKER",
            "submit_rpc_attempted": False,
            "evidence_sha256": "e" * 64,
        },
        prior_owner_liveness_proven_dead=True,
    )
    reactivated = database._stability_connection()
    try:
        reactivated.execute(
            "UPDATE runtime_mutation_lease SET active=1,released_at=NULL "
            "WHERE singleton_id=1"
        )
        reactivated.commit()
    finally:
        reactivated.close()
    with pytest.raises(ValueError, match="no active exact successor"):
        database.record_coin_prep_rbf_submit_start(
            second["attempt_id"], owner_run_id="successor", lease_version=2
        )
    database.record_coin_prep_rbf_sign_start(
        first["attempt_id"], owner_run_id="successor", lease_version=2
    )
    database.record_coin_prep_rbf_dispatch_start(
        first["attempt_id"], owner_run_id="successor", lease_version=2
    )
    with pytest.raises(ValueError, match="submit-start marker already exists"):
        database.record_coin_prep_rbf_sign_no_submit(
            first["attempt_id"], receipt={
                "attempt_id": first["attempt_id"],
                "reason_code": "PRE_SUBMIT_EXCEPTION",
                "submit_rpc_attempted": False,
                "evidence_sha256": "f" * 64,
            },
        )
    post = database.authorize_coin_prep_rbf_rescue_target(
        attempt_id=first["attempt_id"], operation_id=op_id,
        expected_latch_generation=1, unsigned_sha256="7" * 64,
        owner_run_id="successor", lease_version=2, allow_dispatched=True,
    )
    assert post["dispatch_started"] is True
    with pytest.raises(ValueError, match="already dispatched"):
        database.authorize_coin_prep_rbf_rescue_target(
            attempt_id=first["attempt_id"], operation_id=op_id,
            expected_latch_generation=1, unsigned_sha256="7" * 64,
            owner_run_id="successor", lease_version=2,
        )
    with pytest.raises(ValueError, match="one-shot"):
        database.record_coin_prep_rbf_dispatch_start(
            second["attempt_id"], owner_run_id="successor", lease_version=2
        )
