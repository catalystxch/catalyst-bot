from __future__ import annotations

import socket
import threading
import hashlib
import json
import os
import pickle
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import offer_manager
from cancel_outcomes import (
    CANCEL_CONFIRMED,
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    CANCEL_UNKNOWN,
    cancellation_result,
    validate_cancel_result,
)
import database
import mutation_gate
import wallet
from offer_manager import OfferManager
from boost_manager import BoostManager


TRADE_ID = "a" * 64
INTENT_ID = "intent-cancel-a"
OPERATION_ID = f"cancel:{TRADE_ID}"
AT = "2026-08-16T12:00:00Z"
COIN_ID = "c" * 64
ASSET_ID = "d" * 64


def _binding():
    return mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="TEST WALLET",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc="2026-08-16T11:59:50Z",
        maximum_age_seconds=30,
    )


def _identity(second: int):
    return {
        "success": True,
        "backend": "sage",
        "name": "TEST WALLET",
        "fingerprint": 123456789,
        "network_id": "mainnet",
        "kind": "bls",
        "has_secrets": True,
        "observed_at_utc": f"2026-08-16T12:00:{second:02d}Z",
    }


def _stub_cancel_continuation_authority(monkeypatch, *, effect, identity_count=3):
    identities = [_identity(index + 1) for index in range(identity_count)]
    adapter = SimpleNamespace(
        get_wallet_identity=lambda: identities.pop(0),
        cancel_offer=effect,
    )
    permit = object()
    exits = []
    checks = []
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(mutation_gate, "enter_wallet_mutation", lambda _op: permit)
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda supplied, _op: (
            (_binding(), adapter)
            if supplied is permit
            else (_ for _ in ()).throw(AssertionError("wrong permit"))
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda _binding_value, snapshot, _op: {
            "allowed": True,
            "reason": "identity_verified",
            "observed_at_utc": snapshot["observed_at_utc"].replace("Z", ".000000Z"),
        },
    )
    monkeypatch.setattr(
        mutation_gate,
        "wallet_mutation_permit_journal_authority",
        lambda supplied, _op: (
            {
                "mode": "runtime",
                "owner_run_id": "run-task8",
                "owner_pid": os.getpid(),
                "owner_host": socket.gethostname(),
                "lease_version": 7,
                "lease_epoch": "2026-08-16T11:59:55.000000Z",
                "authority_generation_digest": "4" * 64,
                "binding_digest": mutation_gate.wallet_identity_binding_digest(
                    _binding()
                ),
            }
            if supplied is permit
            else (_ for _ in ()).throw(AssertionError("wrong permit"))
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_operation_continuation",
        lambda supplied, operation, blocker, intent: (
            checks.append((supplied, operation, blocker, intent))
            or (_binding(), adapter)
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_operation_continuation",
        lambda supplied, snapshot, operation, blocker, intent: (
            checks.append((supplied, operation, blocker, intent))
            or (
                _binding(),
                adapter,
                {
                    "allowed": True,
                    "reason": "identity_verified",
                    "observed_at_utc": snapshot["observed_at_utc"].replace(
                        "Z", ".000000Z"
                    ),
                },
            )
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "exit_wallet_mutation",
        lambda supplied: exits.append(supplied) or True,
    )
    return permit, identities, exits, checks


def _install_real_cancel_authority(monkeypatch, *, effect):
    """Install the real owner gate with only identity/RPC effects stubbed."""

    now = [datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)]
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="TEST WALLET",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=(now[0] - timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=30,
    )

    def identity():
        now[0] += timedelta(milliseconds=100)
        return {
            "success": True,
            "backend": binding.backend,
            "name": binding.name,
            "fingerprint": binding.fingerprint,
            "network_id": binding.network_id,
            "kind": binding.kind,
            "has_secrets": binding.has_secrets,
            "observed_at_utc": now[0]
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        }

    adapter = SimpleNamespace(
        get_wallet_identity=identity,
        cancel_offer=effect,
    )
    runtime = mutation_gate.MutationGate(
        run_id="run-task8-real-gate",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network=binding.network_id,
        lease_seconds=30,
        clock=lambda: now[0],
        pid_liveness=lambda _pid, _host: False,
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    acquire = runtime.acquire()
    assert acquire["acquired"] is True, acquire
    monkeypatch.setattr(mutation_gate, "_runtime", runtime)
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", adapter)
    return runtime


@pytest.fixture(autouse=True)
def _fail_closed_network_guard(monkeypatch):
    attempts: list[str] = []

    def blocked(*_args, **_kwargs):
        attempts.append("socket")
        raise AssertionError("network access is forbidden in Task 8 tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    mutation_gate.shutdown_runtime()
    mutation_gate.clear_worker_authority_environment()
    path = tmp_path / "task8.db"
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(path))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    monkeypatch.setattr(
        database,
        "_stability_wall_clock",
        lambda: "2026-08-16T12:00:00.000000Z",
    )
    database.init_database()
    yield path
    mutation_gate.shutdown_runtime()
    mutation_gate.clear_worker_authority_environment()
    database.close_connection()


def _seed_locked_offer(trade_id: str = TRADE_ID) -> None:
    assert database.upsert_coin(
        COIN_ID,
        "xch",
        1_000,
        designation="tier_active",
        assigned_tier="inner",
    )
    assert database.add_offer(
        trade_id,
        "buy",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET_ID,
        tier="inner",
        coin_id=COIN_ID,
    )
    assert database.lock_coin(database.norm_coin_id(COIN_ID), trade_id)


def _seed_task7_created_offer(
    *,
    trade_id: str,
    coin_id: str,
    intent_seed: str,
    expires_at: str | None = None,
) -> str:
    """Persist one Task 7 creation journal and its confirmed trade binding."""

    intent_id = hashlib.sha256(intent_seed.encode("utf-8")).hexdigest()
    operation_id = f"create:{intent_id}"
    assert database.upsert_coin(
        coin_id,
        "xch",
        1_000,
        designation="tier_spare",
        assigned_tier="inner",
        purpose="lifecycle",
    )
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:prepared",
        run_id=f"run-task7-{intent_seed}",
        wallet_fingerprint_hash="f" * 64,
        network="mainnet",
        asset_id=ASSET_ID,
        side="buy",
        tier="inner",
        purpose="normal_lifecycle",
        slot_key=f"slot:{intent_seed}",
        generation=0,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[coin_id],
        wallet_identity_json={"binding_digest": "b" * 64},
        evidence_json={"canonical_intent_sha256": intent_id},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:finalized:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=hashlib.sha256(
            f"offer:{intent_seed}".encode("utf-8")
        ).hexdigest(),
        wallet_identity_json={"binding_digest": "b" * 64},
        evidence_json={"effect_attempted": True},
        finalized_at="2026-08-16T12:00:01Z",
        finalize_selected_coin_reservations=True,
    )
    assert database.add_offer(
        trade_id,
        "buy",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET_ID,
        tier="inner",
        expires_at=expires_at,
        coin_id=coin_id,
    )
    return intent_id


def _offer_and_coin(trade_id: str = TRADE_ID) -> tuple[dict, dict]:
    offer = database.get_offer(trade_id)
    coin = dict(
        database.get_connection()
        .execute(
            "SELECT * FROM coins WHERE coin_id=?", (database.norm_coin_id(COIN_ID),)
        )
        .fetchone()
    )
    return offer, coin


def _prepare_cancel(
    *,
    trade_id: str = TRADE_ID,
    operation_id: str = OPERATION_ID,
    attempt: int = 1,
    prepared_at: str = AT,
    claim_effect: bool = False,
):
    return database.prepare_offer_cancel(
        operation_id=operation_id,
        event_id=f"{operation_id}:attempt:{attempt}:prepared",
        trade_id=trade_id,
        intent_id=INTENT_ID,
        attempt=attempt,
        wallet_identity_json={"snapshot_sha256": "b" * 64},
        evidence_json={"trade_id": trade_id, "cohort_id": "single"},
        prepared_at=prepared_at,
        claim_effect=claim_effect,
    )


def _finalize_cancel(
    outcome: str,
    *,
    attempt: int = 1,
    finalized_at: str = "2026-08-16T12:00:01Z",
):
    result = cancellation_result(
        outcome,
        method="single_rpc",
        raw_response={"success": False, "error_code": "REJECTED"},
        error="REJECTED" if outcome == CANCEL_FAILED else "",
    )
    return database.finalize_offer_cancel(
        operation_id=OPERATION_ID,
        event_id=f"{OPERATION_ID}:attempt:{attempt}:finalized",
        trade_id=TRADE_ID,
        intent_id=INTENT_ID,
        attempt=attempt,
        cancel_result=result,
        wallet_identity_json={"snapshot_sha256": "b" * 64},
        evidence_json={"trade_id": TRADE_ID, "cancel_result": result},
        finalized_at=finalized_at,
    )


def test_cancel_request_is_durable_before_any_wallet_effect(isolated_database):
    prepared = _prepare_cancel()

    events = database.get_offer_operation_events(OPERATION_ID)
    assert [
        (row["operation_type"], row["phase"], row["outcome"]) for row in events
    ] == [("CANCEL", "PREPARED", "PREPARED")]
    assert events[0]["blocks_mutation"] == 1
    assert events[0]["request_timestamp"] == "2026-08-16T12:00:00.000000Z"
    assert prepared == events[0]


@pytest.mark.parametrize(
    ("operation_id", "event_id", "trade_id"),
    [
        (
            f"cancel:{'g' * 64}",
            f"cancel:{'g' * 64}:attempt:1:prepared",
            "g" * 64,
        ),
        (
            f"cancel:{TRADE_ID.upper()}",
            f"cancel:{TRADE_ID.upper()}:attempt:1:prepared",
            TRADE_ID.upper(),
        ),
        (
            f"cancel:{'b' * 64}",
            f"cancel:{'b' * 64}:attempt:1:prepared",
            TRADE_ID,
        ),
        (OPERATION_ID, f"{OPERATION_ID}:prepared", TRADE_ID),
    ],
)
def test_cancel_prepare_rejects_noncanonical_or_cross_bound_identifiers(
    isolated_database,
    operation_id,
    event_id,
    trade_id,
):
    with pytest.raises(ValueError, match="canonical cancellation identifiers"):
        database.prepare_offer_cancel(
            operation_id=operation_id,
            event_id=event_id,
            trade_id=trade_id,
            intent_id=INTENT_ID,
            attempt=1,
            wallet_identity_json={"snapshot_sha256": "b" * 64},
            evidence_json={"trade_id": trade_id, "cohort_id": "single"},
            prepared_at=AT,
        )


def test_cancel_finalize_rejects_noncanonical_event_identifier(isolated_database):
    _prepare_cancel()
    result = cancellation_result(
        CANCEL_FAILED,
        method="single_rpc",
        raw_response={"success": False, "error": "rejected"},
    )

    with pytest.raises(ValueError, match="canonical cancellation identifiers"):
        database.finalize_offer_cancel(
            operation_id=OPERATION_ID,
            event_id=f"{OPERATION_ID}:finalized",
            trade_id=TRADE_ID,
            intent_id=INTENT_ID,
            attempt=1,
            cancel_result=result,
            wallet_identity_json={"snapshot_sha256": "b" * 64},
            evidence_json={"trade_id": TRADE_ID, "cancel_result": result},
            finalized_at="2026-08-16T12:00:01Z",
        )


def test_cancel_prepare_atomically_marks_legacy_offer_pending_and_retains_coin(
    isolated_database,
):
    _seed_locked_offer()

    _prepare_cancel()

    offer, coin = _offer_and_coin()
    assert offer["status"] == "open"
    assert offer["lifecycle_state"] == "cancel_requested"
    assert offer["cancel_last_attempt_at"] == "2026-08-16T12:00:00.000000Z"
    assert coin["status"] == "locked"
    assert coin["trade_id"] == TRADE_ID


def test_failed_cancel_restores_prior_active_lifecycle_and_authorizes_next_attempt(
    isolated_database,
):
    _seed_locked_offer()
    assert database.update_offer_lifecycle_state(TRADE_ID, "created")

    first_claim = _prepare_cancel(claim_effect=True)
    _finalize_cancel(CANCEL_FAILED)

    offer, coin = _offer_and_coin()
    assert offer["status"] == "open"
    assert offer["lifecycle_state"] == "created"
    assert coin["status"] == "locked"
    assert coin["trade_id"] == TRADE_ID
    assert first_claim["effect_claimed"] is True
    assert database.get_offer_cancel_effect_claim(
        operation_id=OPERATION_ID,
        attempt=1,
    ) == {
        "operation_id": OPERATION_ID,
        "attempt": 1,
        "prepared_event_id": f"{OPERATION_ID}:attempt:1:prepared",
        "claimed_at": "2026-08-16T12:00:00.000000Z",
    }

    second_claim = _prepare_cancel(
        attempt=2,
        prepared_at="2026-08-16T12:00:02Z",
        claim_effect=True,
    )

    assert second_claim["effect_claimed"] is True
    assert database.get_offer_cancel_effect_claim(
        operation_id=OPERATION_ID,
        attempt=2,
    ) == {
        "operation_id": OPERATION_ID,
        "attempt": 2,
        "prepared_event_id": f"{OPERATION_ID}:attempt:2:prepared",
        "claimed_at": "2026-08-16T12:00:02.000000Z",
    }
    assert second_claim["event"]["event_id"] == (f"{OPERATION_ID}:attempt:2:prepared")
    assert [
        (event["attempt"], event["phase"], event["outcome"])
        for event in database.get_offer_operation_events(OPERATION_ID)
    ] == [
        (1, "PREPARED", "PREPARED"),
        (1, "FINALIZED", CANCEL_FAILED),
        (2, "PREPARED", "PREPARED"),
    ]
    assert database.get_offer(TRADE_ID)["lifecycle_state"] == "cancel_requested"
    with pytest.raises(ValueError, match="prior.*failed|attempt"):
        _prepare_cancel(
            attempt=3,
            prepared_at="2026-08-16T12:00:03Z",
            claim_effect=True,
        )


def test_unknown_cancel_cannot_authorize_later_attempt(isolated_database):
    _seed_locked_offer()
    _prepare_cancel()
    _finalize_cancel(CANCEL_UNKNOWN)

    with pytest.raises(ValueError, match="prior.*failed|attempt"):
        _prepare_cancel(
            attempt=2,
            prepared_at="2026-08-16T12:00:02Z",
            claim_effect=True,
        )


def test_failed_cancel_next_attempt_has_one_atomic_effect_claim(
    isolated_database,
):
    _seed_locked_offer()
    _prepare_cancel()
    _finalize_cancel(CANCEL_FAILED)
    barrier = threading.Barrier(2)
    claims: list[bool] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            claim = _prepare_cancel(
                attempt=2,
                prepared_at="2026-08-16T12:00:02Z",
                claim_effect=True,
            )
            claims.append(claim["effect_claimed"])
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert sorted(claims) == [False, True]
    assert [
        event["attempt"] for event in database.get_offer_operation_events(OPERATION_ID)
    ] == [
        1,
        1,
        2,
    ]


@pytest.mark.parametrize(
    ("outcome", "transaction_id", "spend_identity", "blocks_mutation"),
    [
        (CANCEL_UNKNOWN, "", "", 1),
        (CANCEL_SUBMITTED_UNCONFIRMED, "1" * 64, "", 1),
        (CANCEL_SUBMITTED_UNCONFIRMED, "", f"sha256:{'2' * 64}", 1),
        (CANCEL_FAILED, "", "", 0),
    ],
)
def test_nonterminal_cancel_outcomes_are_atomic_and_never_release_or_terminalize(
    isolated_database,
    outcome,
    transaction_id,
    spend_identity,
    blocks_mutation,
):
    _seed_locked_offer()
    _prepare_cancel()
    result = cancellation_result(
        outcome,
        method="single_rpc",
        raw_response={"success": outcome == CANCEL_FAILED},
        error="REJECTED" if outcome == CANCEL_FAILED else "",
        transaction_id=transaction_id,
        spend_identity=spend_identity,
    )

    finalized = database.finalize_offer_cancel(
        operation_id=OPERATION_ID,
        event_id=f"{OPERATION_ID}:attempt:1:finalized",
        trade_id=TRADE_ID,
        intent_id=INTENT_ID,
        attempt=1,
        cancel_result=result,
        wallet_identity_json={"snapshot_sha256": "b" * 64},
        evidence_json={"trade_id": TRADE_ID, "cancel_result": result},
        finalized_at="2026-08-16T12:00:01Z",
    )

    assert finalized["outcome"] == outcome
    assert finalized["blocks_mutation"] == blocks_mutation
    offer, coin = _offer_and_coin()
    assert offer["status"] == "open"
    assert offer["lifecycle_state"] == (
        "open" if outcome == CANCEL_FAILED else "cancel_requested"
    )
    assert coin["status"] == "locked"
    assert coin["trade_id"] == TRADE_ID
    events = database.get_offer_operation_events(OPERATION_ID)
    assert [(event["phase"], event["outcome"]) for event in events] == [
        ("PREPARED", "PREPARED"),
        ("FINALIZED", outcome),
    ]
    blockers = database.get_unresolved_offer_operation_blockers()
    assert [event["operation_id"] for event in blockers] == (
        [OPERATION_ID] if blocks_mutation else []
    )


def test_cancel_confirmed_requires_future_authoritative_terminal_proof_boundary(
    isolated_database,
):
    _seed_locked_offer()
    _prepare_cancel()
    claimed = cancellation_result(
        CANCEL_CONFIRMED,
        method="adapter_claim",
        raw_response={"success": True},
    )

    with pytest.raises(ValueError, match="authoritative terminal proof"):
        database.finalize_offer_cancel(
            operation_id=OPERATION_ID,
            event_id=f"{OPERATION_ID}:attempt:1:finalized",
            trade_id=TRADE_ID,
            intent_id=INTENT_ID,
            attempt=1,
            cancel_result=claimed,
            wallet_identity_json={"snapshot_sha256": "b" * 64},
            evidence_json={"trade_id": TRADE_ID, "cancel_result": claimed},
            finalized_at="2026-08-16T12:00:01Z",
        )

    offer, coin = _offer_and_coin()
    assert offer["status"] == "open"
    assert coin["status"] == "locked"
    assert [
        (row["phase"], row["outcome"])
        for row in database.get_offer_operation_events(OPERATION_ID)
    ] == [("PREPARED", "PREPARED")]


def test_cancel_prepare_concurrent_duplicate_has_one_durable_member(
    isolated_database,
):
    barrier = threading.Barrier(2)
    rows: list[dict] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            rows.append(_prepare_cancel())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert len(rows) == 2
    assert rows[0] == rows[1]
    assert len(database.get_offer_operation_events(OPERATION_ID)) == 1


def test_canonical_cancel_result_validator_rejects_hostile_or_contradictory_schema():
    from cancel_outcomes import validate_cancel_result

    canonical = cancellation_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        method="single_rpc",
        raw_response={"success": True, "transaction_id": "1" * 64},
        transaction_id="1" * 64,
    )
    assert validate_cancel_result(canonical) == canonical
    contradictory = dict(canonical, success=True)
    with pytest.raises(ValueError, match="canonical cancellation result"):
        validate_cancel_result(contradictory)
    with pytest.raises(ValueError, match="canonical cancellation result"):
        validate_cancel_result({**canonical, "extra": True})

    class HostileDict(dict):
        def items(self):
            raise AssertionError("hostile mapping must not be traversed")

    with pytest.raises(ValueError, match="canonical cancellation result"):
        validate_cancel_result(HostileDict(canonical))


def test_cancel_repository_rejects_hostile_or_oversized_evidence_before_write(
    isolated_database,
):
    class HostileDict(dict):
        def items(self):
            raise AssertionError("hostile mapping must not be traversed")

    with pytest.raises(ValueError, match="evidence_json"):
        database.prepare_offer_cancel(
            operation_id=OPERATION_ID,
            event_id=f"{OPERATION_ID}:attempt:1:prepared",
            trade_id=TRADE_ID,
            intent_id=INTENT_ID,
            attempt=1,
            wallet_identity_json={"snapshot_sha256": "b" * 64},
            evidence_json=HostileDict(trade_id=TRADE_ID),
            prepared_at=AT,
        )
    with pytest.raises(ValueError, match="65536 UTF-8 bytes"):
        database.prepare_offer_cancel(
            operation_id=OPERATION_ID,
            event_id=f"{OPERATION_ID}:attempt:1:prepared",
            trade_id=TRADE_ID,
            intent_id=INTENT_ID,
            attempt=1,
            wallet_identity_json={"snapshot_sha256": "b" * 64},
            evidence_json={"trade_id": TRADE_ID, "padding": "x" * 65536},
            prepared_at=AT,
        )
    assert database.get_offer_operation_events(OPERATION_ID) == []


def test_cancel_continuation_is_single_use_bound_and_journals_exact_authority(
    isolated_database,
    monkeypatch,
):
    effects = []

    def effect(trade_id, secure, timeout, fee_mojos, *, _identity_recheck=None):
        _identity_recheck("cancel_offer")
        effects.append((trade_id, secure, timeout, fee_mojos))
        return cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method="single_rpc",
            raw_response={"success": True, "transaction_id": "1" * 64},
            transaction_id="1" * 64,
        )

    permit, identities, exits, checks = _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
    )
    continuation = wallet.begin_offer_cancel_continuation(
        operation_id=OPERATION_ID,
        intent_id=INTENT_ID,
        trade_id=TRADE_ID,
        ttl_seconds=30,
    )
    journal = wallet.offer_cancel_continuation_journal(continuation)
    encoded = json.dumps(journal["snapshot"], sort_keys=True, separators=(",", ":"))
    assert journal["snapshot_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert journal["snapshot"]["operation_id"] == OPERATION_ID
    assert journal["snapshot"]["intent_id"] == INTENT_ID
    assert journal["snapshot"]["trade_id"] == TRADE_ID
    assert journal["snapshot"]["authority"]["owner_run_id"] == "run-task8"
    assert journal["snapshot"]["binding"] == (
        mutation_gate.wallet_identity_binding_payload(_binding())
    )
    intent = SimpleNamespace(
        operation_id=OPERATION_ID,
        intent_id=INTENT_ID,
        authority_run_id=None,
    )
    verified, run_id, wallet_hash, network = (
        OfferManager._verified_continuation_journal(
            journal,
            intent,
            trade_id=TRADE_ID,
            allowed_backends=frozenset({"sage", "chia"}),
        )
    )
    assert verified == journal
    assert run_id == "run-task8"
    assert wallet_hash == mutation_gate.wallet_fingerprint_hash(123456789)
    assert network == "mainnet"
    tampered = json.loads(json.dumps(journal))
    tampered["snapshot"]["authority"]["binding_digest"] = "0" * 64
    tampered["snapshot_sha256"] = hashlib.sha256(
        json.dumps(tampered["snapshot"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="authority proof binding mismatch"):
        OfferManager._verified_continuation_journal(
            tampered,
            intent,
            trade_id=TRADE_ID,
            allowed_backends=frozenset({"sage", "chia"}),
        )
    with pytest.raises(TypeError):
        pickle.dumps(continuation)

    first = wallet.cancel_offer(
        TRADE_ID,
        secure=True,
        timeout=20,
        fee_mojos=10,
        _cancel_continuation=continuation,
        _cancel_operation_id=OPERATION_ID,
        _cancel_intent_id=INTENT_ID,
    )
    replay = wallet.cancel_offer(
        TRADE_ID,
        _cancel_continuation=continuation,
        _cancel_operation_id=OPERATION_ID,
        _cancel_intent_id=INTENT_ID,
    )

    assert first["outcome"] == CANCEL_SUBMITTED_UNCONFIRMED
    assert first["_catalyst_effect_attempted"] is True
    assert replay["outcome"] == CANCEL_UNKNOWN
    assert replay["_catalyst_effect_attempted"] is False
    assert effects == [(TRADE_ID, True, 20, 10)]
    assert exits == [permit]
    assert identities == []
    assert [entry[2:] for entry in checks] == [
        (OPERATION_ID, INTENT_ID),
        (OPERATION_ID, INTENT_ID),
    ]


def test_wallet_cancel_facade_refuses_unjournaled_single_and_batch(monkeypatch):
    effects = []
    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        identity_count=0,
    )

    single = wallet.cancel_offer(TRADE_ID)
    batch = wallet.cancel_offers_batch([TRADE_ID, "b" * 64])

    assert single["outcome"] == CANCEL_UNKNOWN
    assert single["_catalyst_effect_attempted"] is False
    assert [batch[trade_id]["outcome"] for trade_id in batch] == [
        CANCEL_UNKNOWN,
        CANCEL_UNKNOWN,
    ]
    assert effects == []


def test_cancel_continuation_wrong_trade_is_consumed_without_effect(monkeypatch):
    effects = []
    permit, identities, exits, checks = _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        identity_count=1,
    )
    continuation = wallet.begin_offer_cancel_continuation(
        operation_id=OPERATION_ID,
        intent_id=INTENT_ID,
        trade_id=TRADE_ID,
    )

    wrong = wallet.cancel_offer(
        "b" * 64,
        _cancel_continuation=continuation,
        _cancel_operation_id=OPERATION_ID,
        _cancel_intent_id=INTENT_ID,
    )
    replay = wallet.cancel_offer(
        TRADE_ID,
        _cancel_continuation=continuation,
        _cancel_operation_id=OPERATION_ID,
        _cancel_intent_id=INTENT_ID,
    )

    assert wrong["outcome"] == CANCEL_UNKNOWN
    assert wrong["_catalyst_effect_attempted"] is False
    assert replay["outcome"] == CANCEL_UNKNOWN
    assert effects == []
    assert checks == []
    assert exits == [permit]
    assert identities == []


@pytest.mark.parametrize("misuse", ["thread", "expired"])
def test_cancel_continuation_thread_and_ttl_misuse_close_without_effect(
    monkeypatch,
    misuse,
):
    if misuse == "expired":
        monotonic_values = iter([10.0, 41.0])
        monkeypatch.setattr(wallet.time, "monotonic", lambda: next(monotonic_values))
    effects = []
    permit, identities, exits, checks = _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        identity_count=1,
    )
    continuation = wallet.begin_offer_cancel_continuation(
        operation_id=OPERATION_ID,
        intent_id=INTENT_ID,
        trade_id=TRADE_ID,
        ttl_seconds=30,
    )
    results = []

    def invoke():
        results.append(
            wallet.cancel_offer(
                TRADE_ID,
                _cancel_continuation=continuation,
                _cancel_operation_id=OPERATION_ID,
                _cancel_intent_id=INTENT_ID,
            )
        )

    if misuse == "thread":
        thread = threading.Thread(target=invoke)
        thread.start()
        thread.join(timeout=5)
        assert thread.is_alive() is False
    else:
        invoke()

    assert results[0]["outcome"] == CANCEL_UNKNOWN
    assert results[0]["_catalyst_effect_attempted"] is False
    assert effects == []
    assert checks == []
    assert exits == [permit]
    assert identities == []


def test_mutation_gate_continuation_allows_only_exact_cancel_prepared_blocker(
    isolated_database,
    monkeypatch,
):
    adapter = object()
    binding = _binding()
    clock = lambda: datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
    gate = mutation_gate.MutationGate(
        run_id="run-task8",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network="mainnet",
        lease_seconds=30,
        clock=clock,
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    acquire = gate.acquire()
    assert acquire["acquired"] is True, acquire
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    permit = mutation_gate.enter_wallet_mutation("wallet:cancel_offer")
    _prepare_cancel()

    authorized_binding, authorized_adapter = (
        mutation_gate.require_wallet_operation_continuation(
            permit,
            "wallet:cancel_offer",
            OPERATION_ID,
            INTENT_ID,
        )
    )

    assert authorized_binding is binding
    assert authorized_adapter is adapter
    real_authorization_snapshot = database.get_mutation_authorization_snapshot

    def corrupt_authorization_snapshot(*args, **kwargs):
        snapshot = real_authorization_snapshot(*args, **kwargs)
        snapshot["unresolved"] = [dict(row) for row in snapshot["unresolved"]]
        snapshot["unresolved"][0]["evidence_sha256"] = "0" * 64
        return snapshot

    monkeypatch.setattr(
        database,
        "get_mutation_authorization_snapshot",
        corrupt_authorization_snapshot,
    )
    with pytest.raises(mutation_gate.MutationBlocked) as corrupt:
        mutation_gate.require_wallet_operation_continuation(
            permit,
            "wallet:cancel_offer",
            OPERATION_ID,
            INTENT_ID,
        )
    assert corrupt.value.reason_code == "UNRESOLVED_OPERATIONS"
    with pytest.raises(mutation_gate.MutationBlocked) as wrong:
        mutation_gate.require_wallet_operation_continuation(
            permit,
            "wallet:cancel_offer",
            "cancel:wrong",
            INTENT_ID,
        )
    assert wrong.value.reason_code == "UNRESOLVED_OPERATIONS"
    assert mutation_gate.exit_wallet_mutation(permit) is True


def test_worker_cancel_continuation_accepts_only_exact_cancel_prepared_blocker(
    isolated_database,
    monkeypatch,
):
    adapter = object()
    binding = _binding()
    parent = mutation_gate.MutationGate(
        run_id="parent-task8",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network="mainnet",
        lease_seconds=300,
        clock=lambda: datetime.now(timezone.utc),
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id=OPERATION_ID,
        purpose="offer-cancel",
        worker_id="worker-task8",
        ttl_seconds=120,
        require_wallet_identity=True,
    )
    monkeypatch.setattr(mutation_gate, "_runtime", None)
    mutation_gate.install_worker_authority_environment(
        handoff.to_environment(),
        wallet_adapter_authority=adapter,
    )
    try:
        permit = mutation_gate.enter_wallet_mutation("wallet:cancel_offer")
        proof = mutation_gate.wallet_mutation_permit_journal_authority(
            permit,
            "wallet:cancel_offer",
        )
        _prepare_cancel()

        authorized_binding, authorized_adapter = (
            mutation_gate.require_wallet_operation_continuation(
                permit,
                "wallet:cancel_offer",
                OPERATION_ID,
                INTENT_ID,
            )
        )

        assert authorized_binding == binding
        assert authorized_adapter is adapter
        assert proof == {
            "mode": "worker",
            "delegation_id": handoff.delegation_id,
            "parent_run_id": handoff.parent_run_id,
            "delegation_operation_id": OPERATION_ID,
            "purpose": handoff.purpose,
            "worker_id": handoff.worker_id,
            "parent_lease_epoch": handoff.parent_lease_epoch,
            "authority_generation_digest": proof["authority_generation_digest"],
            "binding_digest": mutation_gate.wallet_identity_binding_digest(binding),
        }
        assert len(proof["authority_generation_digest"]) == 64
        real_authorization_snapshot = database.get_mutation_authorization_snapshot

        def corrupt_authorization_snapshot(*args, **kwargs):
            snapshot = real_authorization_snapshot(*args, **kwargs)
            snapshot["unresolved"] = [dict(row) for row in snapshot["unresolved"]]
            snapshot["unresolved"][0]["evidence_sha256"] = "0" * 64
            return snapshot

        monkeypatch.setattr(
            database,
            "get_mutation_authorization_snapshot",
            corrupt_authorization_snapshot,
        )
        with pytest.raises(mutation_gate.MutationBlocked) as corrupt:
            mutation_gate.require_wallet_operation_continuation(
                permit,
                "wallet:cancel_offer",
                OPERATION_ID,
                INTENT_ID,
            )
        assert corrupt.value.reason_code == "WORKER_PARENT_LEASE_INVALID"
        with pytest.raises(mutation_gate.MutationBlocked) as wrong:
            mutation_gate.require_wallet_operation_continuation(
                permit,
                "wallet:cancel_offer",
                "cancel:wrong",
                INTENT_ID,
            )
        assert wrong.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"
        assert mutation_gate.exit_wallet_mutation(permit) is True
    finally:
        mutation_gate.clear_worker_authority_environment()


@pytest.mark.parametrize(
    ("outcome", "transaction_id", "spend_identity", "blocks"),
    [
        (CANCEL_SUBMITTED_UNCONFIRMED, "1" * 64, None, True),
        (CANCEL_SUBMITTED_UNCONFIRMED, None, "sha256:" + "2" * 64, True),
        (CANCEL_FAILED, None, None, False),
        (CANCEL_UNKNOWN, None, None, True),
    ],
)
def test_offer_manager_single_cancel_is_durable_typed_and_idempotent(
    isolated_database,
    monkeypatch,
    outcome,
    transaction_id,
    spend_identity,
    blocks,
):
    _seed_locked_offer()
    effects = []

    def effect(trade_id, secure, timeout, fee_mojos, *, _identity_recheck=None):
        _identity_recheck("cancel_offer")
        effects.append((trade_id, secure, timeout, fee_mojos))
        return cancellation_result(
            outcome,
            method="single_rpc",
            raw_response={
                "outcome": outcome,
                "transaction_id": transaction_id,
                "spend_identity": spend_identity,
            },
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    manager = OfferManager()

    first = manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]
    replay = manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]

    assert first["outcome"] == outcome
    assert first["transaction_id"] == (transaction_id or "")
    assert first["spend_identity"] == (spend_identity or "")
    assert replay["outcome"] == outcome
    assert replay["_catalyst_idempotent_replay"] is True
    assert effects == [(TRADE_ID, True, 60, None)]
    operation_id = f"cancel:{TRADE_ID}"
    events = database.get_offer_operation_events(operation_id)
    assert [(event["phase"], event["outcome"]) for event in events] == [
        ("PREPARED", "PREPARED"),
        ("FINALIZED", outcome),
    ]
    assert events[1]["blocks_mutation"] == int(blocks)
    offer = database.get_offer(TRADE_ID)
    assert offer["status"] == "open"
    assert offer["lifecycle_state"] == (
        "open" if outcome == CANCEL_FAILED else "cancel_requested"
    )
    assert (
        database.get_all_coins_state()[database.norm_coin_id(COIN_ID)]["status"]
        == "locked"
    )
    assert TRADE_ID not in manager._bot_cancelled_ids
    latch = database.get_runtime_safety_latch()
    assert (latch["state"] == "tripped") is blocks
    if blocks:
        assert json.loads(latch["blocking_operation_ids_json"]) == [operation_id]


def test_offer_manager_wallet_effect_runs_outside_every_database_transaction(
    isolated_database,
    monkeypatch,
):
    transaction_states = []

    def effect(*_args, _identity_recheck=None, **_kwargs):
        transaction_states.append(database.get_connection().in_transaction)
        _identity_recheck("cancel_offer")
        transaction_states.append(database.get_connection().in_transaction)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=3,
    )
    result = OfferManager().cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]

    assert result["outcome"] == CANCEL_FAILED
    assert transaction_states == [False, False]


def test_offer_manager_invalid_typed_result_extras_fail_closed_unknown(
    isolated_database,
    monkeypatch,
):
    invalid = cancellation_result(
        CANCEL_FAILED,
        method="single_rpc",
        raw_response={"success": False, "error": "rejected"},
    )
    invalid["extra"] = True
    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, _identity_recheck=None, **_kwargs: (
            _identity_recheck("cancel_offer") or invalid
        ),
        identity_count=3,
    )

    result = OfferManager().cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]

    assert result["outcome"] == CANCEL_UNKNOWN
    assert result["_catalyst_effect_attempted"] is True
    assert database.get_offer_operation_events(OPERATION_ID)[1]["blocks_mutation"] == 1


def test_offer_manager_unknown_cancel_journals_even_without_legacy_offer(
    isolated_database,
    monkeypatch,
):
    effects = []

    def effect(*_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(True)
        return cancellation_result(
            CANCEL_UNKNOWN,
            method="single_rpc",
            raw_response={"status": 404},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    result = OfferManager().cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]

    assert result["outcome"] == CANCEL_UNKNOWN
    assert effects == [True]
    assert database.get_offer(TRADE_ID) is None
    assert len(database.get_offer_operation_events(f"cancel:{TRADE_ID}")) == 2


@pytest.mark.parametrize(
    ("crash_phase", "expected_events", "expected_effects"),
    [
        ("before_prepare", 0, 0),
        ("after_prepare", 1, 0),
        ("before_wallet", 1, 0),
        ("after_response", 1, 1),
        ("before_final_commit", 1, 1),
        ("after_final_commit", 2, 1),
    ],
)
def test_offer_manager_cancel_crash_boundaries_never_resubmit(
    isolated_database,
    monkeypatch,
    crash_phase,
    expected_events,
    expected_effects,
):
    _seed_locked_offer()
    effects = []

    def effect(*_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(True)
        return cancellation_result(
            CANCEL_UNKNOWN,
            method="single_rpc",
            raw_response={"response_lost": True},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    manager = OfferManager()

    def crash(phase, _intent):
        if phase == crash_phase:
            raise RuntimeError(f"crash:{phase}")

    manager._offer_cancel_crash_hook = crash
    with pytest.raises(RuntimeError, match=f"crash:{crash_phase}"):
        manager.cancel_offers([TRADE_ID], force_storm=True)

    operation_id = f"cancel:{TRADE_ID}"
    assert len(database.get_offer_operation_events(operation_id)) == expected_events
    assert len(effects) == expected_effects
    manager._offer_cancel_crash_hook = None
    replay = manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]
    assert replay["outcome"] == CANCEL_UNKNOWN
    assert len(effects) == expected_effects + int(expected_events == 0)
    assert len(database.get_offer_operation_events(operation_id)) == (
        1 if expected_events == 1 else 2
    )


def test_offer_manager_mixed_batch_preserves_results_before_ambiguity_and_aborts_tail(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    outcomes = {
        trade_ids[0]: cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        ),
        trade_ids[1]: cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method="single_rpc",
            raw_response={"success": True, "transaction_id": "1" * 64},
            transaction_id="1" * 64,
        ),
        trade_ids[2]: cancellation_result(
            CANCEL_UNKNOWN,
            method="single_rpc",
            raw_response={"response_lost": True},
        ),
    }
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return outcomes[trade_id]

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=12,
    )
    results = OfferManager().cancel_offers(trade_ids, force_storm=True)

    assert [results[trade_id]["outcome"] for trade_id in trade_ids] == [
        CANCEL_FAILED,
        CANCEL_SUBMITTED_UNCONFIRMED,
        CANCEL_FAILED,
    ]
    assert effects == trade_ids[:2]
    assert results[trade_ids[2]]["method"] == "batch_abort_ambiguous"
    assert results[trade_ids[2]]["_catalyst_effect_attempted"] is False
    prepared_evidence = []
    for trade_id in trade_ids:
        events = database.get_offer_operation_events(f"cancel:{trade_id}")
        assert len(events) == 2
        prepared_evidence.append(json.loads(events[0]["evidence_json"]))
    assert len({entry["cohort_id"] for entry in prepared_evidence}) == 1
    assert len({entry["member_id"] for entry in prepared_evidence}) == 3
    latch = database.get_runtime_safety_latch()
    assert json.loads(latch["blocking_operation_ids_json"]) == [
        f"cancel:{trade_ids[1]}",
    ]


def test_offer_manager_prepares_entire_cohort_before_first_wallet_effect(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        if not effects:
            assert [
                [
                    event["phase"]
                    for event in database.get_offer_operation_events(f"cancel:{member}")
                ]
                for member in trade_ids
            ] == [["PREPARED"], ["PREPARED"], ["PREPARED"]]
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=12,
    )

    results = OfferManager().cancel_offers(trade_ids, force_storm=True)

    assert effects == trade_ids
    assert [results[trade_id]["outcome"] for trade_id in trade_ids] == [
        CANCEL_FAILED,
        CANCEL_FAILED,
        CANCEL_FAILED,
    ]


def test_offer_manager_prepares_all_71_members_before_first_wallet_effect(
    isolated_database,
    monkeypatch,
):
    """Cancel All must preserve one authority envelope for a 71-offer book."""

    trade_ids = [f"{index:064x}" for index in range(1, 72)]
    canonical_trade_ids = sorted(trade_ids)
    acquired = []
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        assert acquired == canonical_trade_ids
        assert all(
            [
                event["phase"]
                for event in database.get_offer_operation_events(f"cancel:{member}")
            ]
            == ["PREPARED"]
            for member in canonical_trade_ids
        )
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method="single_rpc",
            raw_response={"success": True, "transaction_id": "1" * 64},
            transaction_id="1" * 64,
        )

    _install_real_cancel_authority(monkeypatch, effect=effect)
    manager = OfferManager()
    acquire = manager._acquire_cancel_authority

    def tracked_acquire(intent):
        acquired.append(intent.trade_id)
        return acquire(intent)

    monkeypatch.setattr(manager, "_acquire_cancel_authority", tracked_acquire)
    results = manager.cancel_offers(trade_ids, force_storm=True)

    assert effects == canonical_trade_ids[:1]
    assert results[canonical_trade_ids[0]]["outcome"] == CANCEL_SUBMITTED_UNCONFIRMED
    assert all(
        results[trade_id]["method"] == "batch_abort_ambiguous"
        for trade_id in canonical_trade_ids[1:]
    )
    prepared = [
        json.loads(
            database.get_offer_operation_events(f"cancel:{trade_id}")[0][
                "evidence_json"
            ]
        )
        for trade_id in canonical_trade_ids
    ]
    cohort_sizes = {}
    for evidence in prepared:
        cohort_sizes.setdefault(evidence["cohort_id"], evidence["cohort_size"])
    assert list(cohort_sizes.values()) == [71]
    assert all(
        [
            event["phase"]
            for event in database.get_offer_operation_events(f"cancel:{tid}")
        ]
        == ["PREPARED", "FINALIZED"]
        for tid in canonical_trade_ids
    )


def test_offer_manager_restart_closes_atomically_prepared_cohort_without_effect(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=12,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:after_cohort_prepare"))
        if phase == "after_cohort_prepare"
        else None
    )

    with pytest.raises(RuntimeError, match="crash:after_cohort_prepare"):
        manager.cancel_offers(trade_ids, force_storm=True)

    assert effects == []
    manager._offer_cancel_crash_hook = None
    replay = OfferManager().cancel_offers(trade_ids, force_storm=True)

    assert effects == []
    for trade_id in trade_ids:
        assert replay[trade_id]["outcome"] == CANCEL_FAILED
        assert replay[trade_id]["method"] == "cohort_recovery_unattempted"
        assert replay[trade_id]["_catalyst_effect_attempted"] is False
        assert len(database.get_offer_operation_events(f"cancel:{trade_id}")) == 2


def test_cohort_prepare_crash_before_atomic_commit_persists_no_partial_member(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=12,
    )
    manager = OfferManager()
    prepare_members = []

    def crash_before_second_member(phase, intent):
        if phase != "before_cohort_prepare":
            return
        prepare_members.append(intent.trade_id)
        if len(prepare_members) == 2:
            raise RuntimeError("crash:before_atomic_cohort_commit")

    manager._offer_cancel_crash_hook = crash_before_second_member

    with pytest.raises(RuntimeError, match="crash:before_atomic_cohort_commit"):
        manager.cancel_offers(trade_ids, force_storm=True)

    assert effects == []
    assert [
        len(database.get_offer_operation_events(f"cancel:{trade_id}"))
        for trade_id in trade_ids
    ] == [0, 0, 0]
    assert database.get_unresolved_offer_operation_blockers() == []


def test_persisted_cohort_recovery_discovers_member_omitted_by_restart_subset(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=16,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:after_atomic_cohort_commit"))
        if phase == "after_cohort_prepare"
        else None
    )
    with pytest.raises(RuntimeError, match="crash:after_atomic_cohort_commit"):
        manager.cancel_offers(trade_ids, force_storm=True)

    assert effects == []
    assert [
        len(database.get_offer_operation_events(f"cancel:{trade_id}"))
        for trade_id in trade_ids
    ] == [1, 1, 1]

    replay = OfferManager().cancel_offers(trade_ids[1:], force_storm=True)

    assert effects == []
    assert set(replay) == set(trade_ids[1:])
    assert all(result["outcome"] == CANCEL_FAILED for result in replay.values())
    assert [
        len(database.get_offer_operation_events(f"cancel:{trade_id}"))
        for trade_id in trade_ids
    ] == [2, 2, 2]
    assert database.get_unresolved_offer_operation_blockers() == []


def test_persisted_cohort_recovery_precedes_fresh_member_from_restart_superset(
    isolated_database,
    monkeypatch,
):
    cohort_trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    fresh_trade_id = "d" * 64
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=20,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:after_atomic_cohort_commit"))
        if phase == "after_cohort_prepare"
        else None
    )
    with pytest.raises(RuntimeError, match="crash:after_atomic_cohort_commit"):
        manager.cancel_offers(cohort_trade_ids, force_storm=True)

    replay = OfferManager().cancel_offers(
        [cohort_trade_ids[1], fresh_trade_id],
        force_storm=True,
    )

    assert effects == [fresh_trade_id]
    assert replay[cohort_trade_ids[1]]["outcome"] == CANCEL_FAILED
    assert replay[fresh_trade_id]["outcome"] == CANCEL_FAILED
    assert [
        len(database.get_offer_operation_events(f"cancel:{trade_id}"))
        for trade_id in cohort_trade_ids
    ] == [2, 2, 2]
    assert len(database.get_offer_operation_events(f"cancel:{fresh_trade_id}")) == 2
    assert database.get_unresolved_offer_operation_blockers() == []


def test_task7_intent_cohort_recovery_discovers_omitted_restart_subset(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["1" * 64, "2" * 64, "3" * 64]
    intent_ids = [
        _seed_task7_created_offer(
            trade_id=trade_id,
            coin_id=coin_id,
            intent_seed=f"task7-subset-{index}",
        )
        for index, (trade_id, coin_id) in enumerate(
            zip(trade_ids, ["7" * 64, "8" * 64, "9" * 64]), start=1
        )
    ]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=16,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:task7-cohort-prepared"))
        if phase == "after_cohort_prepare"
        else None
    )
    with pytest.raises(RuntimeError, match="crash:task7-cohort-prepared"):
        manager.cancel_offers(trade_ids, force_storm=True)

    replay = OfferManager().cancel_offers(trade_ids[1:], force_storm=True)

    assert effects == []
    assert all(result["outcome"] == CANCEL_FAILED for result in replay.values())
    for trade_id, intent_id in zip(trade_ids, intent_ids):
        events = database.get_offer_operation_events(f"cancel:{trade_id}")
        assert [event["phase"] for event in events] == ["PREPARED", "FINALIZED"]
        assert {event["intent_id"] for event in events} == {intent_id}
    assert database.get_unresolved_offer_operation_blockers() == []


def test_task7_intent_cohort_recovery_precedes_restart_superset_effect(
    isolated_database,
    monkeypatch,
):
    cohort_trade_ids = ["4" * 64, "5" * 64]
    fresh_trade_id = "6" * 64
    for index, (trade_id, coin_id) in enumerate(
        zip(
            [*cohort_trade_ids, fresh_trade_id],
            ["a" * 64, "b" * 64, "c" * 64],
        ),
        start=1,
    ):
        _seed_task7_created_offer(
            trade_id=trade_id,
            coin_id=coin_id,
            intent_seed=f"task7-superset-{index}",
        )
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=16,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:task7-cohort-prepared"))
        if phase == "after_cohort_prepare"
        else None
    )
    with pytest.raises(RuntimeError, match="crash:task7-cohort-prepared"):
        manager.cancel_offers(cohort_trade_ids, force_storm=True)

    replay = OfferManager().cancel_offers(
        [cohort_trade_ids[1], fresh_trade_id], force_storm=True
    )

    assert effects == [fresh_trade_id]
    assert replay[cohort_trade_ids[1]]["outcome"] == CANCEL_FAILED
    assert replay[fresh_trade_id]["outcome"] == CANCEL_FAILED
    assert database.get_unresolved_offer_operation_blockers() == []


def test_offer_manager_post_claim_crash_keeps_only_claimed_member_unknown(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=12,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, intent: (
        (_ for _ in ()).throw(RuntimeError("crash:post_claim"))
        if phase == "before_wallet" and intent.trade_id == trade_ids[0]
        else None
    )

    with pytest.raises(RuntimeError, match="crash:post_claim"):
        manager.cancel_offers(trade_ids, force_storm=True)

    assert effects == []
    assert (
        database.get_offer_cancel_effect_claim(
            operation_id=f"cancel:{trade_ids[0]}", attempt=1
        )
        is not None
    )
    for trade_id in trade_ids[1:]:
        assert (
            database.get_offer_cancel_effect_claim(
                operation_id=f"cancel:{trade_id}", attempt=1
            )
            is None
        )

    replay = OfferManager().cancel_offers(trade_ids, force_storm=True)

    assert effects == []
    assert replay[trade_ids[0]]["outcome"] == CANCEL_UNKNOWN
    for trade_id in trade_ids[1:]:
        assert replay[trade_id]["outcome"] == CANCEL_FAILED
        assert replay[trade_id]["method"] == "cohort_recovery_unattempted"
    blockers = database.get_unresolved_offer_operation_blockers()
    assert [blocker["operation_id"] for blocker in blockers] == [
        f"cancel:{trade_ids[0]}"
    ]


def test_cohort_member_gate_requires_effect_claim_when_it_is_sole_blocker(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64]
    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: pytest.fail("wallet effect is forbidden"),
        identity_count=8,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:after_cohort_prepare"))
        if phase == "after_cohort_prepare"
        else None
    )

    with pytest.raises(RuntimeError, match="crash:after_cohort_prepare"):
        manager.cancel_offers(trade_ids, force_storm=True)

    blocker = database.get_unresolved_offer_operation_blockers()[-1]
    operation_id = blocker["operation_id"]
    assert (
        mutation_gate._is_exact_prepared_operation_blocker(
            [blocker],
            operation="wallet:cancel_offer",
            operation_id=operation_id,
            intent_id=blocker["intent_id"],
        )
        is False
    )
    assert (
        database.claim_offer_cancel_effect(
            operation_id=operation_id,
            trade_id=trade_ids[-1],
            attempt=1,
            claimed_at="2026-08-16T12:00:01Z",
        )
        is True
    )
    assert (
        mutation_gate._is_exact_prepared_operation_blocker(
            [blocker],
            operation="wallet:cancel_offer",
            operation_id=operation_id,
            intent_id=blocker["intent_id"],
        )
        is True
    )


def test_no_effect_finalize_atomically_rejects_existing_effect_claim(
    isolated_database,
):
    wallet_identity = {"snapshot_sha256": "b" * 64}
    database.prepare_offer_cancel(
        operation_id=OPERATION_ID,
        event_id=f"{OPERATION_ID}:attempt:1:prepared",
        trade_id=TRADE_ID,
        intent_id=INTENT_ID,
        attempt=1,
        wallet_identity_json=wallet_identity,
        evidence_json={
            "trade_id": TRADE_ID,
            "effect_claim_protocol": "durable_cohort_claim_v1",
        },
        prepared_at=AT,
    )
    assert (
        database.claim_offer_cancel_effect(
            operation_id=OPERATION_ID,
            trade_id=TRADE_ID,
            attempt=1,
            claimed_at="2026-08-16T12:00:01Z",
        )
        is True
    )
    result = cancellation_result(
        CANCEL_FAILED,
        method="cohort_recovery_unattempted",
        error="CANCEL_REJECTED",
    )
    finalize = {
        "operation_id": OPERATION_ID,
        "event_id": f"{OPERATION_ID}:attempt:1:finalized",
        "trade_id": TRADE_ID,
        "intent_id": INTENT_ID,
        "attempt": 1,
        "cancel_result": result,
        "wallet_identity_json": wallet_identity,
        "evidence_json": {
            "trade_id": TRADE_ID,
            "effect_attempted": False,
            "cancel_result": result,
        },
        "finalized_at": "2026-08-16T12:00:02Z",
    }

    with pytest.raises(TypeError, match="exact bool"):
        database.finalize_offer_cancel(**finalize, require_unclaimed=1)
    with pytest.raises(ValueError, match="effect claim"):
        database.finalize_offer_cancel(**finalize, require_unclaimed=True)

    # An adapter-local proved rejection after dispatch retains the ordinary
    # finalize path even though authority was durably claimed.
    finalized = database.finalize_offer_cancel(**finalize)
    assert finalized["outcome"] == CANCEL_FAILED


def test_prepare_cancel_cohort_transaction_rolls_back_and_exactly_replays(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    core_members = [
        {
            "trade_id": trade_id,
            "operation_id": f"cancel:{trade_id}",
            "intent_id": f"cancel-target:{trade_id}",
            "attempt": 1,
            "prepared_event_id": f"cancel:{trade_id}:attempt:1:prepared",
        }
        for trade_id in trade_ids
    ]
    manifest = database.canonical_offer_cancel_cohort_manifest(core_members)
    requests = []
    for member in manifest["members"]:
        requests.append(
            {
                "operation_id": member["operation_id"],
                "event_id": member["prepared_event_id"],
                "trade_id": member["trade_id"],
                "intent_id": member["intent_id"],
                "attempt": member["attempt"],
                "wallet_identity_json": {"snapshot_sha256": member["trade_id"]},
                "evidence_json": {
                    "trade_id": member["trade_id"],
                    "cohort_id": manifest["cohort_id"],
                    "cohort_size": manifest["member_count"],
                    "member_id": member["member_id"],
                    "effect_claim_protocol": "durable_cohort_claim_v1",
                },
            }
        )

    real_insert = database._insert_offer_operation_event
    insert_count = 0

    def crash_on_second_insert(conn, values):
        nonlocal insert_count
        insert_count += 1
        if insert_count == 2:
            raise RuntimeError("crash:inside_atomic_cohort_prepare")
        return real_insert(conn, values)

    monkeypatch.setattr(
        database,
        "_insert_offer_operation_event",
        crash_on_second_insert,
    )
    with pytest.raises(RuntimeError, match="crash:inside_atomic_cohort_prepare"):
        database.prepare_offer_cancel_cohort(
            manifest_json=manifest,
            member_requests_json=requests,
            prepared_at=AT,
        )

    assert database.get_offer_cancel_cohort_manifest(manifest["cohort_id"]) is None
    assert [
        database.get_offer_operation_events(member["operation_id"])
        for member in manifest["members"]
    ] == [[], [], []]

    monkeypatch.setattr(database, "_insert_offer_operation_event", real_insert)
    first = database.prepare_offer_cancel_cohort(
        manifest_json=manifest,
        member_requests_json=requests,
        prepared_at=AT,
    )
    replay = database.prepare_offer_cancel_cohort(
        manifest_json=manifest,
        member_requests_json=json.loads(json.dumps(requests)),
        prepared_at="2026-08-16T12:00:09Z",
    )

    assert first["inserted"] is True
    assert replay["inserted"] is False
    assert replay["manifest"] == manifest
    assert [event["event_id"] for event in replay["events"]] == [
        member["prepared_event_id"] for member in manifest["members"]
    ]


def test_cancel_cohort_manifest_rejects_caps_digest_and_member_tamper(
    isolated_database,
):
    def member(index):
        trade_id = f"{index:064x}"
        return {
            "trade_id": trade_id,
            "operation_id": f"cancel:{trade_id}",
            "intent_id": f"cancel-target:{trade_id}",
            "attempt": 1,
            "prepared_event_id": f"cancel:{trade_id}:attempt:1:prepared",
        }

    with pytest.raises(ValueError, match="2 to 128"):
        database.canonical_offer_cancel_cohort_manifest([member(1)])
    with pytest.raises(ValueError, match="2 to 128"):
        database.canonical_offer_cancel_cohort_manifest(
            [member(index) for index in range(1, 130)]
        )

    manifest = database.canonical_offer_cancel_cohort_manifest([member(1), member(2)])
    tampered_digest = json.loads(json.dumps(manifest))
    tampered_digest["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="not canonical"):
        database.validate_offer_cancel_cohort_manifest(tampered_digest)
    tampered_member = json.loads(json.dumps(manifest))
    tampered_member["members"][0]["member_id"] = "cancel-member:" + "0" * 64
    with pytest.raises(ValueError, match="not canonical"):
        database.validate_offer_cancel_cohort_manifest(tampered_member)


def test_cancel_cohort_uses_actual_task7_created_intents_before_any_effect(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["1" * 64, "2" * 64]
    intent_ids = [
        _seed_task7_created_offer(
            trade_id=trade_id,
            coin_id=coin_id,
            intent_seed=f"real-task7-offer-{index}",
        )
        for index, (trade_id, coin_id) in enumerate(
            zip(trade_ids, ["e" * 64, "f" * 64]), start=1
        )
    ]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=8,
    )

    results = OfferManager().cancel_offers(trade_ids, force_storm=True)

    assert effects == trade_ids
    assert [results[trade_id]["outcome"] for trade_id in trade_ids] == [
        CANCEL_FAILED,
        CANCEL_FAILED,
    ]
    expected_manifest = database.canonical_offer_cancel_cohort_manifest(
        [
            {
                "trade_id": trade_id,
                "operation_id": f"cancel:{trade_id}",
                "intent_id": intent_id,
                "attempt": 1,
                "prepared_event_id": f"cancel:{trade_id}:attempt:1:prepared",
            }
            for trade_id, intent_id in zip(trade_ids, intent_ids)
        ]
    )
    manifest = database.get_offer_cancel_cohort_manifest(expected_manifest["cohort_id"])
    assert manifest == expected_manifest
    assert [member["intent_id"] for member in manifest["members"]] == intent_ids
    for trade_id, intent_id in zip(trade_ids, intent_ids):
        events = database.get_offer_operation_events(f"cancel:{trade_id}")
        prepared_evidence = json.loads(events[0]["evidence_json"])
        assert events[0]["intent_id"] == intent_id
        assert prepared_evidence["intent_id"] == intent_id


def test_cancel_cohort_accepts_mixed_fallback_and_task7_intents_and_rejects_swap(
    isolated_database,
):
    task7_trade_id = "3" * 64
    fallback_trade_id = "4" * 64
    task7_intent_id = _seed_task7_created_offer(
        trade_id=task7_trade_id,
        coin_id="7" * 64,
        intent_seed="mixed-real-task7-offer",
    )
    fallback_intent_id = f"cancel-target:{fallback_trade_id}"
    manifest = database.canonical_offer_cancel_cohort_manifest(
        [
            {
                "trade_id": task7_trade_id,
                "operation_id": f"cancel:{task7_trade_id}",
                "intent_id": task7_intent_id,
                "attempt": 1,
                "prepared_event_id": (f"cancel:{task7_trade_id}:attempt:1:prepared"),
            },
            {
                "trade_id": fallback_trade_id,
                "operation_id": f"cancel:{fallback_trade_id}",
                "intent_id": fallback_intent_id,
                "attempt": 1,
                "prepared_event_id": (f"cancel:{fallback_trade_id}:attempt:1:prepared"),
            },
        ]
    )
    assert {member["intent_id"] for member in manifest["members"]} == {
        task7_intent_id,
        fallback_intent_id,
    }

    requests = []
    for member in manifest["members"]:
        requests.append(
            {
                "operation_id": member["operation_id"],
                "event_id": member["prepared_event_id"],
                "trade_id": member["trade_id"],
                "intent_id": member["intent_id"],
                "attempt": member["attempt"],
                "wallet_identity_json": {"snapshot_sha256": "a" * 64},
                "evidence_json": {
                    "trade_id": member["trade_id"],
                    "intent_id": member["intent_id"],
                    "operation_id": member["operation_id"],
                    "attempt": member["attempt"],
                    "cohort_id": manifest["cohort_id"],
                    "cohort_size": manifest["member_count"],
                    "member_id": member["member_id"],
                    "reason": "test",
                    "continuation_journal_sha256": "a" * 64,
                    "wallet_effect": {"secure": True},
                    "effect_claim_protocol": "durable_cohort_claim_v1",
                },
            }
        )
    swapped = json.loads(json.dumps(requests))
    swapped[0]["intent_id"], swapped[1]["intent_id"] = (
        swapped[1]["intent_id"],
        swapped[0]["intent_id"],
    )
    with pytest.raises(ValueError, match="manifest-bound"):
        database.prepare_offer_cancel_cohort(
            manifest_json=manifest,
            member_requests_json=swapped,
            prepared_at=AT,
        )
    assert database.get_offer_cancel_cohort_manifest(manifest["cohort_id"]) is None


@pytest.mark.parametrize(
    "intent_id",
    [
        "task7-alias",
        "A" * 64,
        "a" * 63,
        "cancel-target:" + "A" * 64,
    ],
)
def test_cancel_cohort_rejects_noncanonical_creation_and_fallback_intents(intent_id):
    trade_ids = ["5" * 64, "6" * 64]
    with pytest.raises(ValueError, match="intent identity"):
        database.canonical_offer_cancel_cohort_manifest(
            [
                {
                    "trade_id": trade_id,
                    "operation_id": f"cancel:{trade_id}",
                    "intent_id": (
                        intent_id if index == 0 else f"cancel-target:{trade_id}"
                    ),
                    "attempt": 1,
                    "prepared_event_id": f"cancel:{trade_id}:attempt:1:prepared",
                }
                for index, trade_id in enumerate(trade_ids)
            ]
        )


def test_no_effect_finalize_wins_before_claim_in_one_atomic_order(
    isolated_database,
):
    wallet_identity = {"snapshot_sha256": "b" * 64}
    database.prepare_offer_cancel(
        operation_id=OPERATION_ID,
        event_id=f"{OPERATION_ID}:attempt:1:prepared",
        trade_id=TRADE_ID,
        intent_id=INTENT_ID,
        attempt=1,
        wallet_identity_json=wallet_identity,
        evidence_json={
            "trade_id": TRADE_ID,
            "effect_claim_protocol": "durable_cohort_claim_v1",
        },
        prepared_at=AT,
    )
    result = cancellation_result(
        CANCEL_FAILED,
        method="cohort_recovery_unattempted",
        error="CANCEL_REJECTED",
    )
    finalized = database.finalize_offer_cancel(
        operation_id=OPERATION_ID,
        event_id=f"{OPERATION_ID}:attempt:1:finalized",
        trade_id=TRADE_ID,
        intent_id=INTENT_ID,
        attempt=1,
        cancel_result=result,
        wallet_identity_json=wallet_identity,
        evidence_json={
            "trade_id": TRADE_ID,
            "effect_attempted": False,
            "cancel_result": result,
        },
        finalized_at="2026-08-16T12:00:01Z",
        require_unclaimed=True,
    )

    assert finalized["outcome"] == CANCEL_FAILED
    with pytest.raises(ValueError, match="finalized cancellation"):
        database.claim_offer_cancel_effect(
            operation_id=OPERATION_ID,
            trade_id=TRADE_ID,
            attempt=1,
            claimed_at="2026-08-16T12:00:02Z",
        )


def test_claim_and_no_effect_finalize_race_has_one_atomic_winner(
    isolated_database,
):
    wallet_identity = {"snapshot_sha256": "b" * 64}
    database.prepare_offer_cancel(
        operation_id=OPERATION_ID,
        event_id=f"{OPERATION_ID}:attempt:1:prepared",
        trade_id=TRADE_ID,
        intent_id=INTENT_ID,
        attempt=1,
        wallet_identity_json=wallet_identity,
        evidence_json={
            "trade_id": TRADE_ID,
            "effect_claim_protocol": "durable_cohort_claim_v1",
        },
        prepared_at=AT,
    )
    result = cancellation_result(
        CANCEL_FAILED,
        method="cohort_recovery_unattempted",
        error="CANCEL_REJECTED",
    )
    barrier = threading.Barrier(2)
    outcomes = {}
    outcome_lock = threading.Lock()

    def claim():
        barrier.wait()
        try:
            value = database.claim_offer_cancel_effect(
                operation_id=OPERATION_ID,
                trade_id=TRADE_ID,
                attempt=1,
                claimed_at="2026-08-16T12:00:01Z",
            )
        except Exception as exc:
            value = exc
        with outcome_lock:
            outcomes["claim"] = value

    def finalize_unclaimed():
        barrier.wait()
        try:
            value = database.finalize_offer_cancel(
                operation_id=OPERATION_ID,
                event_id=f"{OPERATION_ID}:attempt:1:finalized",
                trade_id=TRADE_ID,
                intent_id=INTENT_ID,
                attempt=1,
                cancel_result=result,
                wallet_identity_json=wallet_identity,
                evidence_json={
                    "trade_id": TRADE_ID,
                    "effect_attempted": False,
                    "cancel_result": result,
                },
                finalized_at="2026-08-16T12:00:01Z",
                require_unclaimed=True,
            )
        except Exception as exc:
            value = exc
        with outcome_lock:
            outcomes["finalize"] = value

    threads = [
        threading.Thread(target=claim),
        threading.Thread(target=finalize_unclaimed),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    claim_won = outcomes["claim"] is True
    finalize_won = type(outcomes["finalize"]) is dict
    assert claim_won is not finalize_won
    events = database.get_offer_operation_events(OPERATION_ID)
    durable_claim = database.get_offer_cancel_effect_claim(
        operation_id=OPERATION_ID,
        attempt=1,
    )
    if claim_won:
        assert isinstance(outcomes["finalize"], ValueError)
        assert "effect claim" in str(outcomes["finalize"])
        assert [event["phase"] for event in events] == ["PREPARED"]
        assert durable_claim is not None
    else:
        assert isinstance(outcomes["claim"], ValueError)
        assert "finalized cancellation" in str(outcomes["claim"])
        assert [event["phase"] for event in events] == ["PREPARED", "FINALIZED"]
        assert durable_claim is None


def test_claim_between_recovery_read_and_finalize_remains_unknown_and_blocking(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64]
    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: pytest.fail("wallet effect is forbidden"),
        identity_count=8,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:after_cohort_prepare"))
        if phase == "after_cohort_prepare"
        else None
    )
    with pytest.raises(RuntimeError, match="crash:after_cohort_prepare"):
        manager.cancel_offers(trade_ids, force_storm=True)

    event = database.get_offer_operation_events(f"cancel:{trade_ids[0]}")[0]
    prepared = json.loads(event["evidence_json"])
    intent = manager._canonical_cancel_intent(trade_ids[0])
    context = manager._recoverable_unclaimed_cohort_cancel(
        intent,
        attempt=1,
        cohort_id=prepared["cohort_id"],
        cohort_size=prepared["cohort_size"],
        member_id=prepared["member_id"],
    )
    assert context is not None
    assert (
        database.claim_offer_cancel_effect(
            operation_id=intent.operation_id,
            trade_id=intent.trade_id,
            attempt=1,
            claimed_at="2026-08-16T12:00:01Z",
        )
        is True
    )

    raced = manager._finalize_unattempted_cohort_cancel(
        intent,
        attempt=1,
        cohort_id=prepared["cohort_id"],
        cohort_size=prepared["cohort_size"],
        member_id=prepared["member_id"],
        context=context,
        reason_code="COHORT_RECOVERY_UNATTEMPTED",
    )

    assert raced["outcome"] == CANCEL_UNKNOWN
    assert [
        row["phase"] for row in database.get_offer_operation_events(intent.operation_id)
    ] == ["PREPARED"]
    assert [
        row["operation_id"]
        for row in database.get_unresolved_offer_operation_blockers()
    ] == [
        intent.operation_id,
        f"cancel:{trade_ids[1]}",
    ]


def test_concurrent_identical_cancel_cohorts_never_duplicate_member_effect(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    effects = []
    effect_lock = threading.Lock()

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        with effect_lock:
            effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=24,
    )
    monkeypatch.setattr(
        wallet._wallet_adapter, "get_wallet_identity", lambda: _identity(1)
    )
    managers = [OfferManager(), OfferManager()]
    prototypes = {}
    for trade_id in trade_ids:
        intent = managers[0]._canonical_cancel_intent(trade_id)
        continuation, journal, wallet_hash, network = managers[
            0
        ]._acquire_cancel_authority(intent)
        wallet.close_offer_cancel_continuation(continuation)
        prototypes[trade_id] = (journal, wallet_hash, network)
    acquisition_barrier = threading.Barrier(2)
    continuations = []

    def exact_authority(intent):
        if intent.trade_id == trade_ids[0]:
            acquisition_barrier.wait(timeout=5)
        continuation = object()
        continuations.append(continuation)
        journal, wallet_hash, network = prototypes[intent.trade_id]
        return (
            continuation,
            json.loads(json.dumps(journal)),
            wallet_hash,
            network,
        )

    for manager in managers:
        monkeypatch.setattr(manager, "_acquire_cancel_authority", exact_authority)
    monkeypatch.setattr(
        wallet,
        "close_offer_cancel_continuation",
        lambda continuation: continuation in continuations,
    )
    results = []
    errors = []

    def invoke(manager):
        try:
            results.append(manager.cancel_offers(trade_ids, force_storm=True))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=invoke, args=(manager,)) for manager in managers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(results) == 2
    assert all(effects.count(trade_id) <= 1 for trade_id in trade_ids)
    for trade_id in trade_ids:
        events = database.get_offer_operation_events(f"cancel:{trade_id}")
        assert [event["phase"] for event in events] == ["PREPARED", "FINALIZED"]


@pytest.mark.parametrize("ambiguous_index", [0, 1, 2])
def test_offer_manager_real_gate_stops_after_ambiguous_batch_member(
    isolated_database,
    monkeypatch,
    ambiguous_index,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        if trade_id == trade_ids[ambiguous_index]:
            return cancellation_result(
                CANCEL_UNKNOWN,
                method="single_rpc",
                raw_response={"response_lost": True},
            )
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        )

    _install_real_cancel_authority(monkeypatch, effect=effect)
    results = OfferManager().cancel_offers(trade_ids, force_storm=True)

    assert effects == trade_ids[: ambiguous_index + 1]
    assert results[trade_ids[ambiguous_index]]["outcome"] == CANCEL_UNKNOWN
    for index, trade_id in enumerate(trade_ids):
        events = database.get_offer_operation_events(f"cancel:{trade_id}")
        assert len(events) == 2
        if index < ambiguous_index:
            assert results[trade_id]["outcome"] == CANCEL_FAILED
        elif index > ambiguous_index:
            assert results[trade_id]["outcome"] == CANCEL_FAILED
            assert results[trade_id]["method"] == "batch_abort_ambiguous"
            assert results[trade_id]["_catalyst_effect_attempted"] is False
    latch = database.get_runtime_safety_latch()
    assert json.loads(latch["blocking_operation_ids_json"]) == [
        f"cancel:{trade_ids[ambiguous_index]}"
    ]


def test_offer_manager_member_finalization_loss_aborts_unattempted_cohort_tail(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=12,
    )
    real_finalize = database.finalize_offer_cancel

    def finalize_with_one_failure(*args, **kwargs):
        if kwargs.get("trade_id") == trade_ids[1]:
            raise RuntimeError("simulated final commit loss")
        return real_finalize(*args, **kwargs)

    monkeypatch.setattr(database, "finalize_offer_cancel", finalize_with_one_failure)
    results = OfferManager().cancel_offers(trade_ids, force_storm=True)

    assert effects == trade_ids[:2]
    assert results[trade_ids[0]]["outcome"] == CANCEL_FAILED
    assert results[trade_ids[1]]["outcome"] == CANCEL_UNKNOWN
    assert results[trade_ids[2]]["outcome"] == CANCEL_FAILED
    assert results[trade_ids[2]]["method"] == "batch_abort_ambiguous"
    assert results[trade_ids[2]]["_catalyst_effect_attempted"] is False
    assert len(database.get_offer_operation_events(f"cancel:{trade_ids[0]}")) == 2
    assert len(database.get_offer_operation_events(f"cancel:{trade_ids[1]}")) == 1
    assert len(database.get_offer_operation_events(f"cancel:{trade_ids[2]}")) == 2
    latch = database.get_runtime_safety_latch()
    assert json.loads(latch["blocking_operation_ids_json"]) == [
        f"cancel:{trade_ids[1]}"
    ]


def test_offer_manager_duplicate_coalesces_and_alias_is_rejected_before_effect(
    isolated_database,
    monkeypatch,
):
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    manager = OfferManager()
    results = manager.cancel_offers([TRADE_ID, TRADE_ID], force_storm=True)

    assert list(results) == [TRADE_ID]
    assert effects == [TRADE_ID]
    with pytest.raises(ValueError, match="canonical lowercase hex"):
        manager.cancel_offers(["0x" + TRADE_ID], force_storm=True)
    assert effects == [TRADE_ID]


def test_cancel_storm_refusal_returns_canonical_typed_outcome_for_every_member(
    isolated_database,
    monkeypatch,
):
    trade_ids = [f"{index:064x}" for index in range(1, 6)]
    monkeypatch.setattr(
        database,
        "get_open_offers",
        lambda **_kwargs: [{"trade_id": trade_id} for trade_id in trade_ids],
    )
    effects = []
    monkeypatch.setattr(
        wallet,
        "cancel_offer",
        lambda *_args, **_kwargs: effects.append(True),
    )

    results = OfferManager().cancel_offers(trade_ids, reason="requote")

    assert list(results) == trade_ids
    for trade_id in trade_ids:
        result = results[trade_id]
        assert validate_cancel_result(result) == result
        assert result["outcome"] == CANCEL_FAILED
        assert result["method"] == "cancel_storm_guard"
        assert result["error"] == "CANCEL_REJECTED"
        evidence = json.loads(result["raw_response"])
        assert evidence == {
            "code": "CR",
            "d": result["evidence_digest"],
            "k": "mapping",
            "keys": 2,
            "n": 63,
            "t": True,
            "v": 4,
        }
    assert effects == []


def test_failed_replay_is_outside_fresh_cancel_cohort(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _install_real_cancel_authority(monkeypatch, effect=effect)
    manager = OfferManager()
    first = manager.cancel_offers([trade_ids[0]], force_storm=True)
    replay_and_fresh = manager.cancel_offers(trade_ids, force_storm=True)

    assert first[trade_ids[0]]["outcome"] == CANCEL_FAILED
    assert replay_and_fresh[trade_ids[0]]["outcome"] == CANCEL_FAILED
    assert replay_and_fresh[trade_ids[1]]["outcome"] == CANCEL_FAILED
    assert effects == trade_ids
    assert len(database.get_offer_operation_events(f"cancel:{trade_ids[0]}")) == 2
    assert len(database.get_offer_operation_events(f"cancel:{trade_ids[1]}")) == 2


def test_multiple_failed_replays_are_outside_new_fresh_cohort(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
    replay_ids = [trade_ids[0], trade_ids[2]]
    fresh_ids = [trade_ids[1], trade_ids[3]]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _install_real_cancel_authority(monkeypatch, effect=effect)
    manager = OfferManager()
    manager.cancel_offers(replay_ids, force_storm=True)
    results = manager.cancel_offers(trade_ids, force_storm=True)

    assert effects == replay_ids + fresh_ids
    assert all(results[trade_id]["outcome"] == CANCEL_FAILED for trade_id in trade_ids)
    prepared = [
        json.loads(
            database.get_offer_operation_events(f"cancel:{trade_id}")[0][
                "evidence_json"
            ]
        )
        for trade_id in fresh_ids
    ]
    assert {entry["cohort_size"] for entry in prepared} == {2}
    assert len({entry["cohort_id"] for entry in prepared}) == 1


def test_concurrent_mixed_replay_and_fresh_cohort_never_duplicates_fresh_effect(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]
    replay_id = trade_ids[0]
    fresh_ids = trade_ids[1:]
    effects = []
    effect_lock = threading.Lock()

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        with effect_lock:
            effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=24,
    )
    first_manager = OfferManager()
    first_manager.cancel_offers([replay_id], force_storm=True)
    effects.clear()
    monkeypatch.setattr(
        wallet._wallet_adapter,
        "get_wallet_identity",
        lambda: _identity(1),
    )
    managers = [OfferManager(), OfferManager()]
    acquisition_barrier = threading.Barrier(2)

    for manager in managers:
        original_authority = manager._acquire_cancel_authority

        def exact_authority(intent, _original=original_authority):
            if intent.trade_id == fresh_ids[0]:
                acquisition_barrier.wait(timeout=5)
            return _original(intent)

        monkeypatch.setattr(manager, "_acquire_cancel_authority", exact_authority)
    results = []
    errors = []

    def invoke(manager):
        try:
            results.append(manager.cancel_offers(trade_ids, force_storm=True))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=invoke, args=(manager,)) for manager in managers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(results) == 2
    assert all(replay_id in result for result in results), results
    assert all(result[replay_id]["outcome"] == CANCEL_FAILED for result in results)
    assert effects.count(replay_id) == 0
    assert all(effects.count(trade_id) <= 1 for trade_id in fresh_ids)
    blockers = database.get_unresolved_offer_operation_blockers()
    diagnostic = {
        "blockers": [
            (row["operation_id"], row["phase"], row["outcome"], row["reason_code"])
            for row in blockers
        ],
        "results": [
            {
                trade_id: (
                    result["outcome"],
                    result["method"],
                    result.get("_catalyst_effect_attempted"),
                )
                for trade_id, result in batch.items()
            }
            for batch in results
        ],
        "effects": effects,
        "events": {
            trade_id: [
                (row["phase"], row["outcome"], row["reason_code"])
                for row in database.get_offer_operation_events(f"cancel:{trade_id}")
            ]
            for trade_id in fresh_ids
        },
    }
    assert blockers == [], json.dumps(diagnostic, sort_keys=True)
    prepared = [
        json.loads(
            database.get_offer_operation_events(f"cancel:{trade_id}")[0][
                "evidence_json"
            ]
        )
        for trade_id in fresh_ids
    ]
    assert {entry["cohort_size"] for entry in prepared} == {2}
    assert len({entry["cohort_id"] for entry in prepared}) == 1


@pytest.mark.parametrize(
    "ambiguous_outcome",
    [CANCEL_SUBMITTED_UNCONFIRMED, CANCEL_UNKNOWN],
)
def test_ambiguous_replay_blocks_every_fresh_batch_effect(
    isolated_database,
    monkeypatch,
    ambiguous_outcome,
):
    trade_ids = ["a" * 64, "b" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(ambiguous_outcome, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    manager = OfferManager()
    first = manager.cancel_offers([trade_ids[0]], force_storm=True)
    blocked = manager.cancel_offers(trade_ids, force_storm=True)

    assert blocked[trade_ids[0]]["outcome"] == first[trade_ids[0]]["outcome"]
    assert blocked[trade_ids[0]]["_catalyst_attempt"] == 1
    assert blocked[trade_ids[0]]["_catalyst_idempotent_replay"] is True
    assert blocked[trade_ids[0]]["_catalyst_effect_attempted"] is False
    assert blocked[trade_ids[1]]["outcome"] == CANCEL_UNKNOWN
    assert blocked[trade_ids[1]]["_catalyst_effect_attempted"] is False
    assert effects == [trade_ids[0]]
    assert database.get_offer_operation_events(f"cancel:{trade_ids[1]}") == []


def test_explicit_failed_retry_attempt_remains_in_fresh_cohort(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64]
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(CANCEL_FAILED, method="single_rpc")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=12,
    )
    manager = OfferManager()
    manager.cancel_offers([trade_ids[0]], force_storm=True)
    results = manager.cancel_offers(
        trade_ids,
        force_storm=True,
        _retry_failed_attempts={trade_ids[0]: 1},
    )

    assert effects == [trade_ids[0], trade_ids[0], trade_ids[1]]
    assert all(results[trade_id]["outcome"] == CANCEL_FAILED for trade_id in trade_ids)
    prepared = [
        json.loads(
            database.get_offer_operation_events(f"cancel:{trade_id}")[
                2 if trade_id == trade_ids[0] else 0
            ]["evidence_json"]
        )
        for trade_id in trade_ids
    ]
    assert {entry["cohort_size"] for entry in prepared} == {2}
    assert len({entry["cohort_id"] for entry in prepared}) == 1


def test_offer_manager_concurrent_duplicate_cancel_has_one_wallet_effect(
    isolated_database,
    monkeypatch,
):
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=8,
    )
    monkeypatch.setattr(
        wallet._wallet_adapter,
        "get_wallet_identity",
        lambda: _identity(1),
    )
    manager = OfferManager()
    intent = manager._canonical_cancel_intent(TRADE_ID)
    captured_continuation, captured_journal, wallet_hash, network = (
        manager._acquire_cancel_authority(intent)
    )
    assert wallet.close_offer_cancel_continuation(captured_continuation) is True

    continuations = []

    def exact_authority(_intent):
        continuation = object()
        continuations.append(continuation)
        return (
            continuation,
            json.loads(json.dumps(captured_journal)),
            wallet_hash,
            network,
        )

    def wallet_effect(trade_id, **_kwargs):
        result = effect(trade_id, _identity_recheck=lambda _step: None)
        return {**result, "_catalyst_effect_attempted": True}

    monkeypatch.setattr(manager, "_acquire_cancel_authority", exact_authority)
    monkeypatch.setattr(wallet, "cancel_offer", wallet_effect)
    monkeypatch.setattr(
        wallet,
        "close_offer_cancel_continuation",
        lambda continuation: continuation in continuations,
    )
    real_prepare = database.prepare_offer_cancel
    prepare_barrier = threading.Barrier(2)
    prepare_count = 0
    prepare_count_lock = threading.Lock()

    def synchronized_prepare(*args, **kwargs):
        nonlocal prepare_count
        prepare_barrier.wait(timeout=5)
        assert kwargs["wallet_identity_json"] == captured_journal
        kwargs["prepared_at"] = AT
        result = real_prepare(*args, **kwargs)
        with prepare_count_lock:
            prepare_count += 1
        return result

    monkeypatch.setattr(database, "prepare_offer_cancel", synchronized_prepare)
    results = []
    errors = []

    def invoke():
        try:
            results.append(
                manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(thread.is_alive() is False for thread in threads)
    assert errors == []
    assert len(results) == 2
    assert prepare_count == 2
    assert effects == [TRADE_ID]
    assert {result["outcome"] for result in results} == {
        CANCEL_FAILED,
        CANCEL_UNKNOWN,
    }
    assert len(database.get_offer_operation_events(OPERATION_ID)) == 2
    latch = database.get_runtime_safety_latch()
    assert json.loads(latch["blocking_operation_ids_json"]) == [OPERATION_ID]


def test_offer_manager_tampered_prepared_event_replays_unknown_without_effect(
    isolated_database,
    monkeypatch,
):
    effects = []
    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        identity_count=4,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:after_prepare"))
        if phase == "after_prepare"
        else None
    )
    with pytest.raises(RuntimeError, match="crash:after_prepare"):
        manager.cancel_offers([TRADE_ID], force_storm=True)
    real_events = database.get_offer_operation_events

    def corrupted_events(operation_id):
        rows = [dict(row) for row in real_events(operation_id)]
        rows[0]["evidence_sha256"] = "0" * 64
        return rows

    monkeypatch.setattr(database, "get_offer_operation_events", corrupted_events)
    manager._offer_cancel_crash_hook = None

    result = manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]

    assert result["outcome"] == CANCEL_UNKNOWN
    assert result["_catalyst_effect_attempted"] is False
    assert effects == []


def test_offer_manager_recomputed_final_evidence_cross_binding_tamper_is_unknown(
    isolated_database,
    monkeypatch,
):
    effects = []

    def effect(*_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(True)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    manager = OfferManager()
    first = manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]
    assert first["outcome"] == CANCEL_FAILED
    real_events = database.get_offer_operation_events

    def corrupted_events(operation_id):
        rows = [dict(row) for row in real_events(operation_id)]
        evidence = json.loads(rows[1]["evidence_json"])
        evidence["member_id"] = "cancel-member:" + "0" * 64
        rows[1]["evidence_json"] = json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
        )
        rows[1]["evidence_sha256"] = hashlib.sha256(
            rows[1]["evidence_json"].encode()
        ).hexdigest()
        return rows

    monkeypatch.setattr(database, "get_offer_operation_events", corrupted_events)
    replay = manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]

    assert replay["outcome"] == CANCEL_UNKNOWN
    assert replay["_catalyst_effect_attempted"] is False
    assert effects == [True]


def test_offer_manager_recomputed_nonhex_cohort_tamper_is_unknown(
    isolated_database,
    monkeypatch,
):
    effects = []

    def effect(*_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(True)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    manager = OfferManager()
    first = manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]
    assert first["outcome"] == CANCEL_FAILED
    real_events = database.get_offer_operation_events

    def corrupted_events(operation_id):
        rows = [dict(row) for row in real_events(operation_id)]
        prepared = json.loads(rows[0]["evidence_json"])
        prepared["cohort_id"] = "cancel-cohort:" + "g" * 64
        prepared["member_id"] = (
            "cancel-member:"
            + hashlib.sha256(
                OfferManager._canonical_creation_json(
                    {
                        "cohort_id": prepared["cohort_id"],
                        "operation_id": operation_id,
                        "trade_id": TRADE_ID,
                    }
                ).encode("utf-8")
            ).hexdigest()
        )
        rows[0]["evidence_json"] = json.dumps(
            prepared,
            sort_keys=True,
            separators=(",", ":"),
        )
        rows[0]["evidence_sha256"] = hashlib.sha256(
            rows[0]["evidence_json"].encode()
        ).hexdigest()
        finalized = json.loads(rows[1]["evidence_json"])
        finalized["cohort_id"] = prepared["cohort_id"]
        finalized["member_id"] = prepared["member_id"]
        rows[1]["evidence_json"] = json.dumps(
            finalized,
            sort_keys=True,
            separators=(",", ":"),
        )
        rows[1]["evidence_sha256"] = hashlib.sha256(
            rows[1]["evidence_json"].encode()
        ).hexdigest()
        return rows

    monkeypatch.setattr(database, "get_offer_operation_events", corrupted_events)
    replay = manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]

    assert replay["outcome"] == CANCEL_UNKNOWN
    assert replay["_catalyst_effect_attempted"] is False
    assert effects == [True]


def test_offer_manager_recomputed_nonhex_batch_abort_blocker_is_unknown(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64]

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        assert trade_id == trade_ids[0]
        return cancellation_result(
            CANCEL_UNKNOWN,
            method="single_rpc",
            raw_response={"response_lost": True},
        )

    _install_real_cancel_authority(monkeypatch, effect=effect)
    manager = OfferManager()
    first = manager.cancel_offers(trade_ids, force_storm=True)
    assert first[trade_ids[1]]["method"] == "batch_abort_ambiguous"
    operation_id = f"cancel:{trade_ids[1]}"
    real_events = database.get_offer_operation_events

    def corrupted_events(requested_operation_id):
        rows = [dict(row) for row in real_events(requested_operation_id)]
        if requested_operation_id == operation_id:
            finalized = json.loads(rows[1]["evidence_json"])
            finalized["aborted_by_operation_id"] = "cancel:" + "g" * 64
            rows[1]["evidence_json"] = json.dumps(
                finalized,
                sort_keys=True,
                separators=(",", ":"),
            )
            rows[1]["evidence_sha256"] = hashlib.sha256(
                rows[1]["evidence_json"].encode()
            ).hexdigest()
        return rows

    monkeypatch.setattr(database, "get_offer_operation_events", corrupted_events)
    replay = manager._existing_cancel_result(
        manager._canonical_cancel_intent(trade_ids[1])
    )

    assert replay["outcome"] == CANCEL_UNKNOWN
    assert replay["_catalyst_effect_attempted"] is False


def test_cancel_all_routes_every_member_through_durable_typed_path(
    isolated_database,
    monkeypatch,
):
    trade_ids = ["a" * 64, "b" * 64]
    for trade_id in trade_ids:
        assert database.add_offer(
            trade_id,
            "buy",
            Decimal("0.001"),
            Decimal("1"),
            Decimal("1000"),
            ASSET_ID,
            tier="inner",
        )
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=8,
    )
    results = OfferManager().cancel_all(cat_asset_id=ASSET_ID)

    assert effects == trade_ids
    assert [results[trade_id]["outcome"] for trade_id in trade_ids] == [
        CANCEL_FAILED,
        CANCEL_FAILED,
    ]
    for trade_id in trade_ids:
        assert len(database.get_offer_operation_events(f"cancel:{trade_id}")) == 2
        offer = database.get_offer(trade_id)
        assert offer["status"] == "open"
        assert offer["lifecycle_state"] == "open"


def test_retry_failed_cancel_advances_durable_attempt_after_restart(
    isolated_database,
    monkeypatch,
):
    _seed_locked_offer()
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    first_manager = OfferManager()
    first = first_manager.cancel_offers([TRADE_ID], force_storm=True)[TRADE_ID]
    assert first["outcome"] == CANCEL_FAILED
    assert first["_catalyst_attempt"] == 1
    durable_candidates = database.get_retryable_failed_offer_cancels()
    assert len(durable_candidates) == 1
    assert durable_candidates[0]["trade_id"] == TRADE_ID
    assert (
        first_manager._existing_cancel_result(
            first_manager._canonical_cancel_intent(TRADE_ID)
        )["outcome"]
        == CANCEL_FAILED
    )

    restarted_manager = OfferManager()
    restarted_manager._cancel_retry_backoff_seconds = 0
    assert restarted_manager.retry_failed_cancels() == 0

    assert effects == [TRADE_ID, TRADE_ID]
    events = database.get_offer_operation_events(OPERATION_ID)
    assert [(event["attempt"], event["phase"]) for event in events] == [
        (1, "PREPARED"),
        (1, "FINALIZED"),
        (2, "PREPARED"),
        (2, "FINALIZED"),
    ]
    offer = database.get_offer(TRADE_ID)
    assert offer["status"] == "open"
    assert offer["lifecycle_state"] == "open"
    assert restarted_manager._pending_cancel_retries[TRADE_ID]["attempts"] == 2
    assert (
        database.get_all_coins_state()[database.norm_coin_id(COIN_ID)]["status"]
        == "locked"
    )
    authority = restarted_manager.get_cancel_result_authority(TRADE_ID)
    assert authority == {
        "trade_id": TRADE_ID,
        "operation_id": OPERATION_ID,
        "intent_id": f"cancel-target:{TRADE_ID}",
        "attempt": 2,
        "outcome": CANCEL_FAILED,
    }
    durable_envelope = restarted_manager._existing_cancel_result(
        restarted_manager._canonical_cancel_intent(TRADE_ID)
    )
    assert durable_envelope["_catalyst_attempt"] == 2
    monkeypatch.setattr(
        restarted_manager,
        "cancel_offers",
        lambda trade_ids, **_kwargs: {
            trade_id: durable_envelope for trade_id in trade_ids
        },
    )
    boost = BoostManager(offer_manager=restarted_manager)

    assert boost._request_replacement_cancels(
        [TRADE_ID], reason="durable-retry-authority-test"
    ) == {TRADE_ID: CANCEL_FAILED}
    assert TRADE_ID not in restarted_manager._bot_cancelled_ids


def _persist_cancel_authority_projection_state(monkeypatch, state, latch_calls):
    """Persist one actual Task 8 journal shape without retaining setup latch calls."""

    _seed_locked_offer()
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        if state == "submitted":
            return cancellation_result(
                CANCEL_SUBMITTED_UNCONFIRMED,
                method="single_rpc",
                raw_response={"success": True, "transaction_id": "d" * 64},
                transaction_id="d" * 64,
            )
        if state == "unknown":
            return cancellation_result(
                CANCEL_UNKNOWN,
                method="single_rpc",
                raw_response={"success": True},
            )
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error": "rejected"},
            error="REJECTED",
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=8,
    )
    monkeypatch.setattr(
        OfferManager,
        "_trip_cancel_latch",
        staticmethod(lambda *args, **kwargs: latch_calls.append((args, kwargs))),
    )
    manager = OfferManager()
    if state in {"prepared", "confirmed"}:
        manager._offer_cancel_crash_hook = lambda phase, _intent: (
            (_ for _ in ()).throw(RuntimeError("crash:authority-projection"))
            if phase == "after_prepare"
            else None
        )
        with pytest.raises(RuntimeError, match="crash:authority-projection"):
            manager.cancel_offers([TRADE_ID], force_storm=True)
    else:
        manager.cancel_offers([TRADE_ID], force_storm=True)
    latch_calls.clear()

    if state == "confirmed":
        prepared = database.get_offer_operation_events(OPERATION_ID)[0]
        prepared_evidence = json.loads(prepared["evidence_json"])
        confirmed = cancellation_result(
            CANCEL_CONFIRMED,
            method="task9_authoritative",
            raw_response={"success": True},
        )
        database.append_offer_operation_event(
            event_id=f"{OPERATION_ID}:attempt:1:finalized",
            operation_id=OPERATION_ID,
            intent_id=prepared["intent_id"],
            operation_type="CANCEL",
            attempt=1,
            phase="FINALIZED",
            outcome=CANCEL_CONFIRMED,
            request_timestamp="2026-08-16T12:00:01Z",
            wallet_identity_json=json.loads(prepared["wallet_identity_json"]),
            evidence_json={
                "trade_id": TRADE_ID,
                "attempt": 1,
                "cohort_id": prepared_evidence["cohort_id"],
                "member_id": prepared_evidence["member_id"],
                "effect_attempted": False,
                "cancel_result": confirmed,
            },
            reason_code=CANCEL_CONFIRMED,
            blocks_mutation=False,
            created_at="2026-08-16T12:00:01Z",
        )
    elif state in {"malformed", "malformed_early"}:
        conn = database.get_connection()
        conn.execute("DROP TRIGGER offer_operation_journal_no_update")
        evidence_json = "{}"
        if state == "malformed_early":
            conn.execute(
                """
                UPDATE offer_operation_journal
                SET wallet_identity_json='{}'
                WHERE operation_id=? AND phase='PREPARED'
                """,
                (OPERATION_ID,),
            )
        else:
            conn.execute(
                """
                UPDATE offer_operation_journal
                SET evidence_json=?, evidence_sha256=?
                WHERE operation_id=? AND phase='FINALIZED'
                """,
                (
                    evidence_json,
                    hashlib.sha256(evidence_json.encode("utf-8")).hexdigest(),
                    OPERATION_ID,
                ),
            )
        conn.execute(
            """
            CREATE TRIGGER offer_operation_journal_no_update
            BEFORE UPDATE ON offer_operation_journal
            BEGIN
                SELECT RAISE(ABORT, 'offer_operation_journal is append-only');
            END
            """
        )
        conn.commit()
    return effects


@pytest.mark.parametrize(
    ("state", "expected_outcome"),
    [
        ("failed", CANCEL_FAILED),
        ("confirmed", CANCEL_CONFIRMED),
        ("prepared", None),
        ("submitted", None),
        ("unknown", None),
        ("malformed", None),
        ("malformed_early", None),
    ],
)
def test_cancel_result_authority_projection_is_read_only_for_all_journal_states(
    isolated_database,
    monkeypatch,
    state,
    expected_outcome,
):
    latch_calls = []
    effects = _persist_cancel_authority_projection_state(
        monkeypatch,
        state,
        latch_calls,
    )
    before = {
        "latch": database.get_runtime_safety_latch(),
        "events": database.get_offer_operation_events(OPERATION_ID),
        "claim": database.get_offer_cancel_effect_claim(
            operation_id=OPERATION_ID,
            attempt=1,
        ),
        "offer": database.get_offer(TRADE_ID),
        "effects": list(effects),
    }

    authority = OfferManager().get_cancel_result_authority(TRADE_ID)

    after = {
        "latch": database.get_runtime_safety_latch(),
        "events": database.get_offer_operation_events(OPERATION_ID),
        "claim": database.get_offer_cancel_effect_claim(
            operation_id=OPERATION_ID,
            attempt=1,
        ),
        "offer": database.get_offer(TRADE_ID),
        "effects": list(effects),
    }
    assert latch_calls == []
    assert after == before
    if expected_outcome is None:
        assert authority is None
    else:
        assert authority == {
            "trade_id": TRADE_ID,
            "operation_id": OPERATION_ID,
            "intent_id": f"cancel-target:{TRADE_ID}",
            "attempt": 1,
            "outcome": expected_outcome,
        }


def test_cancel_result_authority_prepared_read_does_not_trip_durable_latch(
    isolated_database,
    monkeypatch,
):
    _seed_locked_offer()
    effects = []

    def effect(*args, **kwargs):
        effects.append((args, kwargs))
        raise AssertionError("prepared authority read must not reach the wallet effect")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=4,
    )
    manager = OfferManager()
    manager._offer_cancel_crash_hook = lambda phase, _intent: (
        (_ for _ in ()).throw(RuntimeError("crash:prepared-authority-read"))
        if phase == "after_prepare"
        else None
    )
    with pytest.raises(RuntimeError, match="crash:prepared-authority-read"):
        manager.cancel_offers([TRADE_ID], force_storm=True)
    real_trip = database.trip_runtime_safety_latch
    trip_calls = []

    def counted_trip(**kwargs):
        trip_calls.append(kwargs)
        return real_trip(**kwargs)

    monkeypatch.setattr(database, "trip_runtime_safety_latch", counted_trip)
    before_latch = database.get_runtime_safety_latch()
    before_events = database.get_offer_operation_events(OPERATION_ID)

    authority = OfferManager().get_cancel_result_authority(TRADE_ID)

    assert trip_calls == []
    assert database.get_runtime_safety_latch() == before_latch
    assert database.get_offer_operation_events(OPERATION_ID) == before_events
    assert authority is None
    assert effects == []


def test_retry_failed_cancel_uses_durable_backoff(
    isolated_database,
    monkeypatch,
):
    _seed_locked_offer()
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    first_manager = OfferManager()
    first_manager.cancel_offers([TRADE_ID], force_storm=True)
    failed_at = datetime.fromisoformat(
        database.get_retryable_failed_offer_cancels()[0]["created_at"].replace(
            "Z", "+00:00"
        )
    ).timestamp()
    clock = [failed_at + 29]
    monkeypatch.setattr(offer_manager.time, "time", lambda: clock[0])

    restarted_manager = OfferManager()
    restarted_manager._cancel_retry_backoff_seconds = 30
    assert restarted_manager.retry_failed_cancels() == 0
    assert effects == [TRADE_ID]
    assert restarted_manager._pending_cancel_retries[TRADE_ID]["attempts"] == 1

    clock[0] = failed_at + 31
    assert restarted_manager.retry_failed_cancels() == 0
    assert effects == [TRADE_ID, TRADE_ID]
    assert restarted_manager._pending_cancel_retries[TRADE_ID]["attempts"] == 2


def test_retry_failed_cancel_reconciles_elapsed_offer_before_wallet_effect(
    isolated_database,
    monkeypatch,
):
    intent_id = _seed_task7_created_offer(
        trade_id=TRADE_ID,
        coin_id=COIN_ID,
        intent_seed="retry-expired-before-effect",
        expires_at="2026-08-16T11:59:00Z",
    )
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=3,
    )
    manager = OfferManager()
    manager._cancel_retry_backoff_seconds = 0
    manager.cancel_offers([TRADE_ID], force_storm=True)

    import offer_reconciliation

    reconcile_calls = []

    def reconcile(candidate_intent_id):
        reconcile_calls.append(candidate_intent_id)
        assert database.update_offer_status(TRADE_ID, "expired") is True
        return {
            "classification": offer_reconciliation.EXPIRED_PROVEN,
            "applied": True,
        }

    monkeypatch.setattr(offer_reconciliation, "reconcile_offer", reconcile)
    monkeypatch.setattr(
        offer_manager.time,
        "time",
        lambda: datetime(2026, 8, 16, 12, 1, tzinfo=timezone.utc).timestamp(),
    )

    assert manager.retry_failed_cancels() == 0

    assert effects == [TRADE_ID]
    assert reconcile_calls == [intent_id]
    assert manager.get_active_cancel_settlement_operation() is None


def test_retry_failed_cancel_accepts_existing_terminal_authority_without_replay(
    isolated_database,
    monkeypatch,
):
    intent_id = _seed_task7_created_offer(
        trade_id=TRADE_ID,
        coin_id=COIN_ID,
        intent_seed="retry-existing-terminal-authority",
        expires_at="2026-08-16T11:59:00Z",
    )
    manager = OfferManager()
    intent = manager._canonical_cancel_intent(TRADE_ID)
    offer = database.get_offer(TRADE_ID)
    replay_calls = []

    monkeypatch.setattr(
        database,
        "get_offer_intent",
        lambda candidate_intent_id: {
            **database.get_offer_intent_by_trade_id(TRADE_ID),
            "intent_id": candidate_intent_id,
            "lifecycle_state": "terminal",
        },
    )
    monkeypatch.setattr(
        database,
        "get_authoritative_terminal_record",
        lambda trade_id: {
            "intent_id": intent_id,
            "operation_id": f"reconcile:{intent_id}",
            "sage_trade_id": trade_id,
            "outcome": "EXPIRED_PROVEN",
            "terminal_state": "expired",
        },
    )

    import offer_reconciliation

    monkeypatch.setattr(
        offer_reconciliation,
        "reconcile_offer",
        lambda *args, **kwargs: replay_calls.append((args, kwargs)),
    )

    assert (
        manager._reconcile_elapsed_cancel_retry(
            intent,
            offer,
            now_timestamp=datetime(2026, 8, 16, 12, 1, tzinfo=timezone.utc).timestamp(),
        )
        is True
    )
    assert replay_calls == []
    assert database.get_runtime_safety_latch()["state"] == "resolved"


def test_retry_failed_cancel_settles_submitted_result_before_next_mutation(
    isolated_database,
    monkeypatch,
):
    intent_id = _seed_task7_created_offer(
        trade_id=TRADE_ID,
        coin_id=COIN_ID,
        intent_seed="retry-submitted-settlement",
    )
    effects = []
    active_operations = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        active_operations.append(manager.get_active_cancel_settlement_operation())
        if len(effects) == 1:
            return cancellation_result(
                CANCEL_FAILED,
                method="single_rpc",
                raw_response={"success": False},
            )
        return cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method="single_rpc",
            raw_response={"success": True, "transaction_id": "e" * 64},
            transaction_id="e" * 64,
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    manager = OfferManager()
    manager._cancel_retry_backoff_seconds = 0
    manager.cancel_offers([TRADE_ID], force_storm=True)

    import offer_reconciliation

    reconcile_calls = []
    release_calls = []
    monkeypatch.setattr(
        offer_reconciliation,
        "load_authoritative_evidence",
        lambda _intent: {"wallet": "complete"},
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "_derive_single_cancel_context",
        lambda *_args, **_kwargs: {"members": [{"trade_id": TRADE_ID}]},
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "classify_terminal_evidence",
        lambda *_args, **_kwargs: {
            "classification": offer_reconciliation.CANCELLED_PROVEN,
            "reason_code": "EXACT_CANCEL_RETURN_PROOF",
        },
    )

    def reconcile(intent_id, **kwargs):
        reconcile_calls.append((intent_id, kwargs))
        return {
            "classification": offer_reconciliation.CANCELLED_PROVEN,
            "applied": True,
        }

    monkeypatch.setattr(offer_reconciliation, "reconcile_offer", reconcile)
    monkeypatch.setattr(
        mutation_gate,
        "current_runtime",
        lambda: SimpleNamespace(
            release_resolved=lambda generation, operation_ids: (
                release_calls.append((generation, operation_ids))
                or {"released": True, "reason": "released"}
            )
        ),
    )

    assert manager.retry_failed_cancels() == 0

    assert effects == [TRADE_ID, TRADE_ID]
    assert active_operations == [None, OPERATION_ID]
    assert manager.get_active_cancel_settlement_operation() is None
    assert len(reconcile_calls) == 1
    assert reconcile_calls[0][0] == intent_id
    assert release_calls == [(1, [OPERATION_ID])]


def test_retry_failed_cancel_pauses_when_submitted_result_is_not_proven(
    isolated_database,
    monkeypatch,
):
    _seed_task7_created_offer(
        trade_id=TRADE_ID,
        coin_id=COIN_ID,
        intent_seed="retry-submitted-not-proven",
    )
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        if len(effects) == 1:
            return cancellation_result(
                CANCEL_FAILED,
                method="single_rpc",
                raw_response={"success": False},
            )
        return cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method="single_rpc",
            raw_response={"success": True, "transaction_id": "e" * 64},
            transaction_id="e" * 64,
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=6,
    )
    manager = OfferManager()
    manager._cancel_retry_backoff_seconds = 0
    manager.cancel_offers([TRADE_ID], force_storm=True)

    import offer_reconciliation

    reconcile_calls = []
    release_calls = []
    monkeypatch.setattr(offer_manager.cfg, "CANCEL_MAX_WAIT_SECS", 0)
    monkeypatch.setattr(
        offer_reconciliation,
        "load_authoritative_evidence",
        lambda _intent: {"wallet": "pending"},
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "_derive_single_cancel_context",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "classify_terminal_evidence",
        lambda *_args, **_kwargs: {
            "classification": offer_reconciliation.UNKNOWN,
            "reason_code": "CANCEL_PROOF_INCOMPLETE",
        },
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "reconcile_offer",
        lambda *args, **kwargs: reconcile_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        mutation_gate,
        "current_runtime",
        lambda: SimpleNamespace(
            release_resolved=lambda generation, operation_ids: (
                release_calls.append((generation, operation_ids))
                or {"released": True, "reason": "released"}
            )
        ),
    )

    assert manager.retry_failed_cancels() == -1

    assert effects == [TRADE_ID, TRADE_ID]
    assert reconcile_calls == []
    assert release_calls == []
    blockers = database.get_unresolved_offer_operation_blockers()
    assert [row["operation_id"] for row in blockers] == [OPERATION_ID]


def test_retry_failed_cancel_race_has_one_new_wallet_effect(
    isolated_database,
    monkeypatch,
):
    _seed_locked_offer()
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=9,
    )
    OfferManager().cancel_offers([TRADE_ID], force_storm=True)
    effects.clear()
    real_candidates = database.get_retryable_failed_offer_cancels
    barrier = threading.Barrier(2)

    def synchronized_candidates():
        candidates = real_candidates()
        barrier.wait(timeout=5)
        return candidates

    monkeypatch.setattr(
        database,
        "get_retryable_failed_offer_cancels",
        synchronized_candidates,
    )
    managers = [OfferManager(), OfferManager()]
    for manager in managers:
        manager._cancel_retry_backoff_seconds = 0
    errors = []

    def run(manager):
        try:
            manager.retry_failed_cancels()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(manager,)) for manager in managers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert effects == [TRADE_ID]
    assert [
        (event["attempt"], event["phase"])
        for event in database.get_offer_operation_events(OPERATION_ID)
    ] == [
        (1, "PREPARED"),
        (1, "FINALIZED"),
        (2, "PREPARED"),
        (2, "FINALIZED"),
    ]


def test_retry_exhaustion_keeps_durable_failure_without_terminalizing(
    isolated_database,
    monkeypatch,
):
    _seed_locked_offer()
    effects = []

    def effect(trade_id, *_args, _identity_recheck=None, **_kwargs):
        _identity_recheck("cancel_offer")
        effects.append(trade_id)
        return cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False},
        )

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=effect,
        identity_count=15,
    )
    manager = OfferManager()
    manager._cancel_retry_backoff_seconds = 0
    manager.cancel_offers([TRADE_ID], force_storm=True)
    for _attempt in range(1, manager._max_cancel_retries):
        assert manager.retry_failed_cancels() == 0

    assert manager.retry_failed_cancels() == 0
    assert effects == [TRADE_ID] * manager._max_cancel_retries
    assert database.get_offer(TRADE_ID)["status"] == "open"
    assert database.get_offer(TRADE_ID)["lifecycle_state"] == "open"
    assert manager._pending_cancel_retries[TRADE_ID]["attempts"] == (
        manager._max_cancel_retries
    )
    assert (
        database.get_all_coins_state()[database.norm_coin_id(COIN_ID)]["status"]
        == "locked"
    )


def test_production_cancellation_callers_route_or_deny_before_adapter():
    source_root = Path(__file__).resolve().parents[1] / "src" / "catalyst"

    offers_source = (source_root / "blueprints" / "offers.py").read_text(
        encoding="utf-8"
    )
    stopped_cancel = offers_source.split(
        "else:\n        # Bot stopped or not started", 1
    )[1].split('@bp.route("/api/offers/cleanup_orphans"', 1)[0]
    assert "durable_manager.cancel_offers(" in stopped_cancel
    assert "cancel_offers_batch(" not in stopped_cancel
    assert "UPDATE offers SET status='cancelled'" not in stopped_cancel

    bot_loop_source = (source_root / "bot_loop.py").read_text(encoding="utf-8")
    orphan_cleanup = bot_loop_source.split("    def cleanup_orphaned_offers", 1)[
        1
    ].split("\n    def ", 1)[0]
    assert "self.offer_manager.cancel_offers(" in orphan_cleanup
    assert "cancel_offers_batch(" not in orphan_cleanup

    for adapter_name in ("wallet_sage.py", "wallet_chia.py"):
        adapter_source = (source_root / adapter_name).read_text(encoding="utf-8")
        cleanup = adapter_source.split("def cleanup_expired_offers", 1)[1].split(
            "\ndef ", 1
        )[0]
        assert "cancel_offer(" not in cleanup

    worker_source = (source_root / "coin_prep_worker.py").read_text(encoding="utf-8")
    worker_cancel = worker_source.split("    def cancel_all_offers", 1)[1].split(
        "\n    def ", 1
    )[0]
    assert "pending_methods" not in worker_cancel
    assert "rpc_cancel_offer" not in worker_cancel

    # Task 16 owns removal/migration of the manual Sage debug route.  Until
    # then its direct facade call is stable fail-closed and cannot reach an
    # adapter without the opaque cancellation continuation.
    market_source = (source_root / "blueprints" / "market.py").read_text(
        encoding="utf-8"
    )
    debug_route = market_source.split("def api_debug_sage_single_offer_test():", 1)[
        1
    ].split("\n@bp.route", 1)[0]
    assert "cancel_offer(trade_id" in debug_route
    wallet_source = (source_root / "wallet.py").read_text(encoding="utf-8")
    facade_cancel = wallet_source.split("def cancel_offer(", 1)[1].split(
        "\ndef cancel_offers_batch(", 1
    )[0]
    assert '"OFFER_CANCEL_JOURNAL_REQUIRED"' in facade_cancel
    assert '_run_wallet_mutation("cancel_offer"' not in facade_cancel
