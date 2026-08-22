from __future__ import annotations

import builtins
import socket
import os
import hashlib
import json
import pickle
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import database
import mutation_gate
import offer_manager
import wallet


COIN_A = "a" * 64
COIN_B = "b" * 64
COIN_C = "d" * 64
AT = "2026-08-16T12:00:00Z"
VALID_SAGE_OFFER = "offer1qqr83wcuu2rykccqsgpsedq9qpyxgqxptsfxvk"
CREATION_CONTEXT = {
    "slot_key": "ladder:buy:7",
    "generation": 3,
    "asset_id": "c" * 64,
    "side": "buy",
    "tier": "inner",
    "purpose": "normal_lifecycle",
    "offer_size_uniqueness": {
        "slot": 7,
        "requested_amount_atomic": "2000",
    },
}


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


def _stub_continuation_authority(monkeypatch, *, effect, identity_count=3):
    identities = [_identity(index + 1) for index in range(identity_count)]
    adapter = SimpleNamespace(
        get_wallet_identity=lambda: identities.pop(0),
        create_offer=effect,
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
                "owner_run_id": "run-task7",
                "lease_version": 7,
                "lease_epoch": "2026-08-16T11:59:55.000000Z",
                "authority_generation_digest": "4" * 64,
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


def _stub_offer_manager_wallet(monkeypatch, *, effect):
    begun = []
    closed = []

    def begin(*, operation_id, intent_id, ttl_seconds):
        capability = object()
        begun.append(
            {
                "capability": capability,
                "operation_id": operation_id,
                "intent_id": intent_id,
                "ttl_seconds": ttl_seconds,
            }
        )
        return capability

    def journal(capability):
        entry = next(item for item in begun if item["capability"] is capability)
        binding = mutation_gate.wallet_identity_binding_payload(_binding())
        observed = _identity(1)
        observed.pop("success")
        observed["observed_at_utc"] = observed["observed_at_utc"].replace(
            "Z", ".000000Z"
        )
        observation_encoded = json.dumps(
            observed,
            sort_keys=True,
            separators=(",", ":"),
        )
        snapshot = {
            "schema_version": 1,
            "operation_id": entry["operation_id"],
            "intent_id": entry["intent_id"],
            "binding": binding,
            "binding_digest": mutation_gate.wallet_identity_binding_digest(_binding()),
            "observation": observed,
            "observation_digest": hashlib.sha256(
                observation_encoded.encode()
            ).hexdigest(),
            "authority": {
                "mode": "runtime",
                "owner_run_id": "run-task7",
                "owner_pid": os.getpid(),
                "owner_host": socket.gethostname(),
                "lease_version": 7,
                "lease_epoch": "2026-08-16T11:59:55.000000Z",
                "authority_generation_digest": "4" * 64,
                "binding_digest": mutation_gate.wallet_identity_binding_digest(
                    _binding()
                ),
            },
        }
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        return {
            "snapshot": snapshot,
            "snapshot_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        }

    monkeypatch.setattr(wallet, "begin_offer_creation_continuation", begin)
    monkeypatch.setattr(wallet, "offer_creation_continuation_journal", journal)
    monkeypatch.setattr(
        wallet,
        "close_offer_creation_continuation",
        lambda capability: closed.append(capability) or True,
    )
    monkeypatch.setattr(wallet, "create_offer", effect)
    return begun, closed


@pytest.fixture(autouse=True)
def _fail_closed_network_guard(monkeypatch):
    attempts: list[str] = []

    def blocked(*_args, **_kwargs):
        attempts.append("socket")
        raise AssertionError("network access is forbidden in Task 7 tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    path = tmp_path / "task7.db"
    original_upsert_coin = database.upsert_coin

    def upsert_lifecycle_coin(*args, **kwargs):
        kwargs.setdefault("purpose", "lifecycle")
        return original_upsert_coin(*args, **kwargs)

    monkeypatch.setattr(database, "upsert_coin", upsert_lifecycle_coin)
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
    database.close_connection()


def _prepare(*, intent_id: str, operation_id: str, coin_id: str):
    return database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"prepare:{intent_id}",
        run_id="run-task7",
        wallet_fingerprint_hash="f" * 64,
        network="mainnet",
        asset_id="c" * 64,
        side="buy",
        tier="inner",
        purpose="normal_lifecycle",
        slot_key=f"slot:{intent_id}",
        generation=0,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[coin_id],
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"canonical_intent_sha256": "e" * 64},
        prepared_at=AT,
        reserve_selected_coins=True,
    )


def test_prepare_atomically_reserves_exact_selected_coin_and_replay_is_idempotent(
    isolated_database,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")

    first = _prepare(
        intent_id="intent-a", operation_id="create:intent-a", coin_id=COIN_A
    )
    replay = _prepare(
        intent_id="intent-a", operation_id="create:intent-a", coin_id=COIN_A
    )

    assert replay == first
    assert database.get_offer_intent_coin_reservations("intent-a") == [
        {
            "coin_id": COIN_A,
            "reservation_identity": "intent:intent-a",
            "status": "reserved",
            "trade_id": None,
            "purpose": "lifecycle",
        }
    ]


def test_prepare_same_selected_coin_race_has_one_winner(isolated_database):
    assert database.upsert_coin(COIN_B, "xch", 1000, designation="tier_spare")

    _prepare(intent_id="intent-a", operation_id="create:intent-a", coin_id=COIN_B)
    with pytest.raises(ValueError, match="selected coin is not free"):
        _prepare(intent_id="intent-b", operation_id="create:intent-b", coin_id=COIN_B)

    assert database.get_offer_intent("intent-b") is None
    assert database.get_offer_operation_events("create:intent-b") == []


def test_prepare_can_claim_new_intent_without_replay_ambiguity(isolated_database):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    values = {
        "intent_id": "intent-a",
        "operation_id": "create:intent-a",
        "event_id": "prepare:intent-a",
        "run_id": "run-task7",
        "wallet_fingerprint_hash": "f" * 64,
        "network": "mainnet",
        "asset_id": "c" * 64,
        "side": "buy",
        "tier": "inner",
        "purpose": "normal_lifecycle",
        "slot_key": "slot:intent-a",
        "generation": 0,
        "offered_amount_atomic": "1000",
        "requested_amount_atomic": "2000",
        "selected_coin_ids_json": [COIN_A],
        "wallet_identity_json": {"binding_digest": "d" * 64},
        "evidence_json": {"canonical_intent_sha256": "e" * 64},
        "prepared_at": AT,
        "reserve_selected_coins": True,
        "require_new_intent": True,
    }

    database.prepare_offer_intent(**values)
    with pytest.raises(ValueError, match="offer intent already exists"):
        database.prepare_offer_intent(**values)


def test_prepare_replay_never_reacquires_terminal_intent_reservation(
    isolated_database,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    _prepare(intent_id="intent-a", operation_id="create:intent-a", coin_id=COIN_A)
    database.finalize_offer_intent(
        intent_id="intent-a",
        operation_id="create:intent-a",
        event_id="final:failed",
        lifecycle_state="creation_failed",
        outcome="FAILED",
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"effect_attempted": False},
        reason_code="CREATE_REJECTED",
        finalized_at="2026-08-16T12:00:01Z",
        finalize_selected_coin_reservations=True,
    )
    assert (
        database.get_offer_intent_coin_reservations("intent-a")[0]["status"]
        == "released"
    )

    replay = _prepare(
        intent_id="intent-a",
        operation_id="create:intent-a",
        coin_id=COIN_A,
    )

    assert replay["lifecycle_state"] == "creation_failed"
    assert (
        database.get_offer_intent_coin_reservations("intent-a")[0]["status"]
        == "released"
    )
    assert len(database.get_offer_operation_events("create:intent-a")) == 2


def test_generation_selection_advances_only_after_terminal_intent(
    isolated_database,
):
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="run-task7",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(123456789),
        network="mainnet",
        lease_expires_at="2099-08-16T12:05:00Z",
        now=AT,
    )
    assert acquired["acquired"] is True
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    assert database.upsert_coin(COIN_B, "xch", 1000, designation="tier_spare")

    empty = database.select_offer_creation_generation(slot_key="ladder:buy:7")
    assert empty == {
        "run_id": "run-task7",
        "generation": 0,
        "active_intent_id": None,
        "active_lifecycle_state": None,
    }

    failed = _prepare(
        intent_id="intent-failed",
        operation_id="create:intent-failed",
        coin_id=COIN_A,
    )
    # Exercise the same durable slot the selector owns.
    assert failed["slot_key"] == "slot:intent-failed"
    database.finalize_offer_intent(
        intent_id="intent-failed",
        operation_id="create:intent-failed",
        event_id="final:failed-generation",
        lifecycle_state="creation_failed",
        outcome="FAILED",
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"effect_attempted": False},
        reason_code="CREATE_REJECTED",
        finalized_at="2026-08-16T12:00:01Z",
        finalize_selected_coin_reservations=True,
    )
    next_generation = database.select_offer_creation_generation(
        slot_key="slot:intent-failed"
    )
    assert next_generation == {
        "run_id": "run-task7",
        "generation": 1,
        "active_intent_id": None,
        "active_lifecycle_state": None,
    }

    created = database.prepare_offer_intent(
        intent_id="intent-created",
        operation_id="create:intent-created",
        event_id="prepare:intent-created",
        run_id="run-task7",
        wallet_fingerprint_hash="f" * 64,
        network="mainnet",
        asset_id="c" * 64,
        side="buy",
        tier="inner",
        purpose="normal_lifecycle",
        slot_key="slot:intent-failed",
        generation=1,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[COIN_B],
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"canonical_intent_sha256": "e" * 64},
        prepared_at="2026-08-16T12:00:02Z",
        reserve_selected_coins=True,
    )
    database.finalize_offer_intent(
        intent_id=created["intent_id"],
        operation_id="create:intent-created",
        event_id="final:created-generation",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id="1" * 64,
        offer_text_sha256="2" * 64,
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"effect_attempted": True},
        finalized_at="2026-08-16T12:00:03Z",
        finalize_selected_coin_reservations=True,
    )
    active = database.select_offer_creation_generation(slot_key="slot:intent-failed")
    assert active == {
        "run_id": "run-task7",
        "generation": 1,
        "active_intent_id": "intent-created",
        "active_lifecycle_state": "created",
    }


@pytest.mark.parametrize(
    ("lifecycle_state", "outcome", "trade_id", "offer_hash", "expected_status"),
    [
        ("created", "CONFIRMED", "1" * 64, "2" * 64, "bound"),
        ("creation_unknown", "UNKNOWN", None, None, "reserved"),
        ("submitted_unconfirmed", "SUBMITTED_UNCONFIRMED", None, None, "reserved"),
        ("creation_failed", "FAILED", None, None, "released"),
    ],
)
def test_finalize_updates_selected_coin_reservation_only_for_proven_outcome(
    isolated_database,
    lifecycle_state,
    outcome,
    trade_id,
    offer_hash,
    expected_status,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    _prepare(intent_id="intent-a", operation_id="create:intent-a", coin_id=COIN_A)

    database.finalize_offer_intent(
        intent_id="intent-a",
        operation_id="create:intent-a",
        event_id=f"final:{outcome}",
        lifecycle_state=lifecycle_state,
        outcome=outcome,
        sage_trade_id=trade_id,
        offer_text_sha256=offer_hash,
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"effect_attempted": outcome != "FAILED"},
        reason_code=None if outcome == "CONFIRMED" else f"CREATE_{outcome}",
        finalized_at="2026-08-16T12:00:01Z",
        finalize_selected_coin_reservations=True,
    )

    reservation = database.get_offer_intent_coin_reservations("intent-a")[0]
    assert reservation["status"] == expected_status
    assert reservation["trade_id"] == (trade_id if expected_status == "bound" else None)


def test_offer_creation_continuation_journals_authority_and_is_single_use(
    monkeypatch,
):
    identities = [_identity(1), _identity(2), _identity(3)]
    effects = []

    def create_effect(*args, **kwargs):
        kwargs["_identity_recheck"]("make_offer")
        effects.append((args, kwargs))
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": "offer1test",
        }

    adapter = SimpleNamespace(
        get_wallet_identity=lambda: identities.pop(0),
        create_offer=create_effect,
    )
    permit = object()
    exits = []
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
        lambda supplied, _op: {
            "mode": "runtime",
            "owner_run_id": "run-task7",
            "lease_version": 7,
            "lease_epoch": "2026-08-16T11:59:55.000000Z",
            "authority_generation_digest": "4" * 64,
        },
        raising=False,
    )
    continuation_checks = []
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_operation_continuation",
        lambda supplied, operation, blocker, intent: (
            continuation_checks.append((supplied, operation, blocker, intent))
            or (_binding(), adapter)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_operation_continuation",
        lambda supplied, snapshot, operation, blocker, intent: (
            continuation_checks.append((supplied, operation, blocker, intent))
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
        raising=False,
    )
    monkeypatch.setattr(
        mutation_gate,
        "exit_wallet_mutation",
        lambda supplied: exits.append(supplied) or True,
    )

    continuation = wallet.begin_offer_creation_continuation(
        operation_id="create:intent-a",
        intent_id="intent-a",
        ttl_seconds=30,
    )
    journal = wallet.offer_creation_continuation_journal(continuation)

    assert journal["snapshot"][
        "binding"
    ] == mutation_gate.wallet_identity_binding_payload(_binding())
    assert journal["snapshot"]["binding_digest"] == (
        mutation_gate.wallet_identity_binding_digest(_binding())
    )
    assert journal["snapshot"]["observation"]["observed_at_utc"] == (
        "2026-08-16T12:00:01.000000Z"
    )
    assert journal["snapshot"]["authority"]["authority_generation_digest"] == ("4" * 64)
    assert len(journal["snapshot_sha256"]) == 64
    assert "permit" not in repr(journal).lower()

    result = wallet.create_offer(
        {"1": -1000, "2": 2000},
        validate_only=False,
        coin_ids=[COIN_A],
        _creation_continuation=continuation,
        _creation_operation_id="create:intent-a",
        _creation_intent_id="intent-a",
    )
    replay = wallet.create_offer(
        {"1": -1000, "2": 2000},
        validate_only=False,
        coin_ids=[COIN_A],
        _creation_continuation=continuation,
        _creation_operation_id="create:intent-a",
        _creation_intent_id="intent-a",
    )

    assert result["success"] is True, result
    assert result["_catalyst_effect_attempted"] is True
    assert replay == {
        "success": False,
        "error": "Wallet mutation blocked by identity safety check",
        "reason": "OFFER_CREATION_CONTINUATION_INVALID",
        "_catalyst_effect_attempted": False,
    }
    assert len(effects) == 1
    assert continuation_checks == [
        (permit, "wallet:create_offer", "create:intent-a", "intent-a"),
        (
            permit,
            "wallet:create_offer:make_offer:identity",
            "create:intent-a",
            "intent-a",
        ),
    ]
    assert exits == [permit]
    assert identities == []


def test_offer_creation_continuation_rejects_forgery_without_effect(monkeypatch):
    effects = []
    _stub_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        identity_count=0,
    )

    result = wallet.create_offer(
        {"1": -1000, "2": 2000},
        _creation_continuation=object(),
        _creation_operation_id="create:intent-a",
        _creation_intent_id="intent-a",
    )

    assert result == {
        "success": False,
        "error": "Wallet mutation blocked by identity safety check",
        "reason": "OFFER_CREATION_CONTINUATION_INVALID",
        "_catalyst_effect_attempted": False,
    }
    assert effects == []


def test_offer_creation_continuation_wrong_intent_is_consumed_and_closed(
    monkeypatch,
):
    effects = []
    permit, identities, exits, checks = _stub_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        identity_count=1,
    )
    continuation = wallet.begin_offer_creation_continuation(
        operation_id="create:intent-a",
        intent_id="intent-a",
    )

    wrong = wallet.create_offer(
        {"1": -1000, "2": 2000},
        _creation_continuation=continuation,
        _creation_operation_id="create:intent-a",
        _creation_intent_id="intent-b",
    )
    replay = wallet.create_offer(
        {"1": -1000, "2": 2000},
        _creation_continuation=continuation,
        _creation_operation_id="create:intent-a",
        _creation_intent_id="intent-a",
    )

    assert wrong["reason"] == "OFFER_CREATION_CONTINUATION_INVALID"
    assert wrong["_catalyst_effect_attempted"] is False
    assert replay["reason"] == "OFFER_CREATION_CONTINUATION_INVALID"
    assert effects == []
    assert checks == []
    assert exits == [permit]
    assert identities == []


def test_offer_creation_continuation_is_thread_bound_and_closes_on_misuse(
    monkeypatch,
):
    effects = []
    permit, identities, exits, checks = _stub_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        identity_count=1,
    )
    continuation = wallet.begin_offer_creation_continuation(
        operation_id="create:intent-a",
        intent_id="intent-a",
    )
    results = []

    thread = threading.Thread(
        target=lambda: results.append(
            wallet.create_offer(
                {"1": -1000, "2": 2000},
                _creation_continuation=continuation,
                _creation_operation_id="create:intent-a",
                _creation_intent_id="intent-a",
            )
        )
    )
    thread.start()
    thread.join(timeout=5)

    assert thread.is_alive() is False
    assert results[0]["reason"] == "OFFER_CREATION_CONTINUATION_INVALID"
    assert results[0]["_catalyst_effect_attempted"] is False
    assert effects == []
    assert checks == []
    assert exits == [permit]
    assert identities == []


def test_offer_creation_continuation_expires_before_effect(monkeypatch):
    monotonic_values = iter([10.0, 41.0])
    monkeypatch.setattr(wallet.time, "monotonic", lambda: next(monotonic_values))
    effects = []
    permit, identities, exits, checks = _stub_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        identity_count=1,
    )
    continuation = wallet.begin_offer_creation_continuation(
        operation_id="create:intent-a",
        intent_id="intent-a",
        ttl_seconds=30,
    )

    result = wallet.create_offer(
        {"1": -1000, "2": 2000},
        _creation_continuation=continuation,
        _creation_operation_id="create:intent-a",
        _creation_intent_id="intent-a",
    )

    assert result["reason"] == "OFFER_CREATION_CONTINUATION_INVALID"
    assert result["_catalyst_effect_attempted"] is False
    assert effects == []
    assert checks == []
    assert exits == [permit]
    assert identities == []


def test_offer_creation_continuation_backend_exception_closes_after_attempt(
    monkeypatch,
):
    def explode(*_args, **_kwargs):
        _kwargs["_identity_recheck"]("make_offer")
        raise RuntimeError("response lost")

    permit, identities, exits, checks = _stub_continuation_authority(
        monkeypatch,
        effect=explode,
        identity_count=3,
    )
    continuation = wallet.begin_offer_creation_continuation(
        operation_id="create:intent-a",
        intent_id="intent-a",
    )

    result = wallet.create_offer(
        {"1": -1000, "2": 2000},
        _creation_continuation=continuation,
        _creation_operation_id="create:intent-a",
        _creation_intent_id="intent-a",
    )

    assert result == {
        "success": False,
        "error": "Wallet mutation blocked by identity safety check",
        "reason": "WALLET_MUTATION_FAILED",
        "_catalyst_effect_attempted": True,
    }
    assert checks == [
        (permit, "wallet:create_offer", "create:intent-a", "intent-a"),
        (
            permit,
            "wallet:create_offer:make_offer:identity",
            "create:intent-a",
            "intent-a",
        ),
    ]
    assert exits == [permit]
    assert identities == []


def test_offer_creation_continuation_local_rejection_is_proven_no_effect(
    monkeypatch,
):
    adapter_calls = []

    def reject_locally(*_args, **_kwargs):
        adapter_calls.append(True)
        return {"success": False, "reason": "LOCAL_VALIDATION_REJECTED"}

    permit, identities, exits, checks = _stub_continuation_authority(
        monkeypatch,
        effect=reject_locally,
        identity_count=2,
    )
    continuation = wallet.begin_offer_creation_continuation(
        operation_id="create:intent-a",
        intent_id="intent-a",
    )

    result = wallet.create_offer(
        {"1": -1000, "2": 2000},
        _creation_continuation=continuation,
        _creation_operation_id="create:intent-a",
        _creation_intent_id="intent-a",
    )

    assert result == {
        "success": False,
        "reason": "LOCAL_VALIDATION_REJECTED",
        "_catalyst_effect_attempted": False,
    }
    assert adapter_calls == [True]
    assert checks == [(permit, "wallet:create_offer", "create:intent-a", "intent-a")]
    assert exits == [permit]
    assert identities == []


def test_offer_creation_continuation_is_unserializable_and_explicit_close_is_once(
    monkeypatch,
):
    permit, identities, exits, checks = _stub_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: pytest.fail("effect must not run"),
        identity_count=1,
    )
    continuation = wallet.begin_offer_creation_continuation(
        operation_id="create:intent-a",
        intent_id="intent-a",
    )

    with pytest.raises(TypeError):
        pickle.dumps(continuation)
    assert "permit" not in repr(continuation).lower()
    assert wallet.close_offer_creation_continuation(continuation) is True
    assert wallet.close_offer_creation_continuation(continuation) is False
    assert exits == [permit]
    assert checks == []
    assert identities == []


def test_offer_manager_prepares_before_effect_and_finalizes_exact_evidence(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(offer_dict, **kwargs):
        effects.append((dict(offer_dict), dict(kwargs)))
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    begun, closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_A],
            "selected_present": True,
        },
    )

    first = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        max_retries=2,
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )
    replay = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        max_retries=2,
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert first["success"] is True
    assert replay["success"] is True
    assert replay["_catalyst_idempotent_replay"] is True
    assert first["_catalyst_intent_id"] == replay["_catalyst_intent_id"]
    assert replay["offer_max_time"] == first["offer_max_time"]
    assert len(effects) == 1
    assert len(begun) == 1
    assert closed == []
    effect_kwargs = effects[0][1]
    assert effect_kwargs["_creation_continuation"] is begun[0]["capability"]
    assert effect_kwargs["_creation_operation_id"] == begun[0]["operation_id"]
    assert effect_kwargs["_creation_intent_id"] == begun[0]["intent_id"]
    assert effect_kwargs["min_coin_amount"] == 800
    assert effect_kwargs["max_coin_amount"] == 2000

    intent = database.get_offer_intent(first["_catalyst_intent_id"])
    assert intent["lifecycle_state"] == "created"
    assert intent["run_id"] == "run-task7"
    assert intent["slot_key"] == CREATION_CONTEXT["slot_key"]
    assert intent["generation"] == CREATION_CONTEXT["generation"]
    assert intent["sage_trade_id"] == "3" * 64
    assert (
        intent["offer_text_sha256"]
        == hashlib.sha256(VALID_SAGE_OFFER.encode()).hexdigest()
    )
    assert database.get_offer_intent_coin_reservations(intent["intent_id"]) == [
        {
            "coin_id": COIN_A,
            "reservation_identity": f"intent:{intent['intent_id']}",
            "status": "bound",
            "trade_id": "3" * 64,
            "purpose": "lifecycle",
        }
    ]
    events = database.get_offer_operation_events(begun[0]["operation_id"])
    assert [(row["phase"], row["outcome"]) for row in events] == [
        ("PREPARED", "PREPARED"),
        ("FINALIZED", "CONFIRMED"),
    ]
    prepared_evidence = json.loads(events[0]["evidence_json"])
    final_evidence = json.loads(events[-1]["evidence_json"])
    persisted_authority = json.loads(events[0]["wallet_identity_json"])
    assert persisted_authority == json.loads(events[-1]["wallet_identity_json"])
    assert (
        persisted_authority["snapshot"]["authority"]["authority_generation_digest"]
        == "4" * 64
    )
    assert persisted_authority["snapshot"]["authority"]["lease_epoch"] == (
        "2026-08-16T11:59:55.000000Z"
    )
    assert persisted_authority["snapshot"]["binding"] == (
        mutation_gate.wallet_identity_binding_payload(_binding())
    )
    assert len(persisted_authority["snapshot_sha256"]) == 64
    assert len(final_evidence["canonical_intent_sha256"]) == 64
    assert prepared_evidence["wallet_effect"] == {
        "expiry_offset": 0,
        "expiry_seconds": offer_manager.cfg.OFFER_EXPIRY_SECS,
        "max_coin_hint": 2000,
        "min_coin_hint": 800,
        "offer_max_time": effect_kwargs["max_time"],
        "stagger_seconds": 0,
        "validate_only": False,
    }
    assert (
        final_evidence["offer_size_uniqueness"]
        == CREATION_CONTEXT["offer_size_uniqueness"]
    )
    assert final_evidence["locked_input_verification"] == {
        "locked_coin_ids": ["0x" + COIN_A],
        "selected_present": True,
        "verified": True,
    }
    assert final_evidence["registry_authorization"] == {
        "allowed": True,
        "code": "allowed",
    }


def test_offer_manager_ladder_generation_advances_after_failure_but_not_created(
    isolated_database,
    monkeypatch,
):
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="run-task7",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(123456789),
        network="mainnet",
        lease_expires_at="2099-08-16T12:05:00Z",
        now=AT,
    )
    assert acquired["acquired"] is True
    for coin_id in (COIN_A, COIN_B, COIN_C):
        assert database.upsert_coin(coin_id, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(_offer_dict, **_kwargs):
        effects.append(True)
        if len(effects) == 1:
            return {
                "success": False,
                "reason": "CREATE_REJECTED",
                "_catalyst_effect_attempted": False,
            }
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_B],
            "selected_present": True,
        },
    )
    auto_context = {
        key: value for key, value in CREATION_CONTEXT.items() if key != "generation"
    }
    auto_context["select_next_generation"] = True

    failed = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=auto_context,
    )
    created = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_B,
        preferred_tier="inner",
        creation_context=auto_context,
    )
    blocked = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_C,
        preferred_tier="inner",
        creation_context=auto_context,
    )

    rows = sorted(
        database.get_offer_intents_for_registry(), key=lambda row: row["generation"]
    )
    assert failed["success"] is False
    assert created["success"] is True
    assert blocked["success"] is False
    assert blocked["reason"] == "OFFER_CREATION_RACE_LOST"
    assert len(effects) == 2
    assert [row["generation"] for row in rows] == [0, 1]
    assert [row["lifecycle_state"] for row in rows] == [
        "creation_failed",
        "created",
    ]
    assert (
        database.get_offer_intent_coin_reservations(rows[0]["intent_id"])[0]["status"]
        == "released"
    )
    assert (
        database.get_offer_intent_coin_reservations(rows[1]["intent_id"])[0]["status"]
        == "bound"
    )


def test_offer_manager_generation_selection_requires_matching_journal_run(
    isolated_database,
    monkeypatch,
):
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="run-task7",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(123456789),
        network="mainnet",
        lease_expires_at="2099-08-16T12:05:00Z",
        now=AT,
    )
    assert acquired["acquired"] is True
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    complete_journal = wallet.offer_creation_continuation_journal

    def wrong_run_journal(capability):
        journal = complete_journal(capability)
        journal["snapshot"]["authority"]["owner_run_id"] = "run-other"
        snapshot_encoded = json.dumps(
            journal["snapshot"], sort_keys=True, separators=(",", ":")
        )
        journal["snapshot_sha256"] = hashlib.sha256(
            snapshot_encoded.encode()
        ).hexdigest()
        return journal

    monkeypatch.setattr(
        wallet,
        "offer_creation_continuation_journal",
        wrong_run_journal,
    )
    context = {
        key: value for key, value in CREATION_CONTEXT.items() if key != "generation"
    }
    context["select_next_generation"] = True

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=context,
    )

    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_INTENT_INVALID"
    assert effects == []
    assert database.get_offer_intents_for_registry() == []
    assert closed == [begun[0]["capability"]]


def test_offer_manager_generation_selector_exception_is_stable_before_authority(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    monkeypatch.setattr(
        database,
        "select_offer_creation_generation",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("generation database unavailable")
        ),
    )
    monkeypatch.setattr(
        wallet,
        "begin_offer_creation_continuation",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("generation failure must be pre-authority")
        ),
    )
    monkeypatch.setattr(
        wallet,
        "create_offer",
        lambda *_args, **_kwargs: effects.append(True),
    )
    context = {
        key: value for key, value in CREATION_CONTEXT.items() if key != "generation"
    }
    context["select_next_generation"] = True

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=context,
    )

    assert result == {
        "success": False,
        "error": "Durable offer generation unavailable",
        "reason": "OFFER_CREATION_AUTHORITY_DENIED",
        "_catalyst_effect_attempted": False,
    }
    assert effects == []
    assert database.get_offer_intents_for_registry() == []
    assert database.get_runtime_safety_latch()["state"] == "resolved"


def test_offer_manager_rejects_unbounded_offer_size_evidence_before_authority(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, _closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    context = dict(CREATION_CONTEXT)
    context["offer_size_uniqueness"] = {"hostile": "x" * 5000}

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=context,
    )

    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_INTENT_INVALID"
    assert effects == []
    assert begun == []


@pytest.mark.parametrize(
    "changed_effect_args",
    [
        {"expiry_secs": 601},
        {"expiry_offset": 1},
    ],
)
def test_offer_manager_effect_arguments_are_part_of_canonical_intent_identity(
    isolated_database,
    monkeypatch,
    changed_effect_args,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(*_args, **_kwargs):
        effects.append(True)
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    begun, closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_A],
            "selected_present": True,
        },
    )
    base_args = {"expiry_secs": 600, "expiry_offset": 0}

    first = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
        **base_args,
    )
    second = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
        **(base_args | changed_effect_args),
    )

    assert first["success"] is True
    assert second["reason"] == "OFFER_CREATION_RACE_LOST"
    assert len(effects) == 1
    assert len(begun) == 2
    assert begun[0]["intent_id"] != begun[1]["intent_id"]
    assert closed == [begun[1]["capability"]]


def test_offer_manager_wall_clock_drift_does_not_change_idempotency_identity(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    clock = {"value": 1_000}
    monkeypatch.setattr(offer_manager.time, "time", lambda: clock["value"])

    def effect(*_args, **_kwargs):
        effects.append(True)
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    begun, _closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_A],
            "selected_present": True,
        },
    )
    call = lambda: manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        expiry_secs=600,
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    first = call()
    clock["value"] = 1_005
    replay = call()

    assert first["success"] is True
    assert replay["success"] is True
    assert replay["_catalyst_idempotent_replay"] is True
    assert replay["offer_max_time"] == first["offer_max_time"]
    assert len(begun) == 1
    assert effects == [True]


@pytest.mark.parametrize(
    "tamper",
    [
        "evidence_digest",
        "reason_code",
        "extra_field",
        "missing_prepared",
        "unparseable_evidence",
        "journal_cross_binding",
    ],
)
def test_offer_manager_created_replay_rejects_tampered_prepared_evidence(
    isolated_database,
    monkeypatch,
    tamper,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(*_args, **_kwargs):
        effects.append(True)
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_A],
            "selected_present": True,
        },
    )
    call = lambda: manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        expiry_secs=600,
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )
    first = call()
    real_get_events = database.get_offer_operation_events

    def tampered_events(operation_id):
        rows = [dict(row) for row in real_get_events(operation_id)]
        if tamper == "missing_prepared":
            return [row for row in rows if row["phase"] != "PREPARED"]
        prepared = next(row for row in rows if row["phase"] == "PREPARED")
        if tamper == "evidence_digest":
            evidence = json.loads(prepared["evidence_json"])
            evidence["wallet_effect"]["offer_max_time"] = 777
            prepared["evidence_json"] = json.dumps(
                evidence, sort_keys=True, separators=(",", ":")
            )
            # Preserve the original digest to prove replay checks it.
        elif tamper == "reason_code":
            prepared["reason_code"] = "ALTERED_PREPARED_REASON"
        elif tamper == "extra_field":
            prepared["unexpected_field"] = "not an exact journal row"
        elif tamper == "journal_cross_binding":
            journal = json.loads(prepared["wallet_identity_json"])
            journal["snapshot"]["authority"]["authority_generation_digest"] = "5" * 64
            snapshot_encoded = json.dumps(
                journal["snapshot"], sort_keys=True, separators=(",", ":")
            )
            journal["snapshot_sha256"] = hashlib.sha256(
                snapshot_encoded.encode()
            ).hexdigest()
            prepared["wallet_identity_json"] = json.dumps(
                journal, sort_keys=True, separators=(",", ":")
            )
        else:
            prepared["evidence_json"] = "{"
        return rows

    monkeypatch.setattr(
        database,
        "get_offer_operation_events",
        tampered_events,
    )

    replay = call()

    assert first["success"] is True
    assert replay["success"] is False
    assert replay["reason"] == "OFFER_CREATION_RECONCILIATION_REQUIRED"
    assert effects == [True]
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_offer_manager_authority_denial_is_stable_and_pre_effect(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    monkeypatch.setattr(
        wallet,
        "begin_offer_creation_continuation",
        lambda **_kwargs: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_LOST", "wallet:create_offer")
        ),
    )
    monkeypatch.setattr(
        wallet,
        "create_offer",
        lambda *_args, **_kwargs: effects.append(True),
    )

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result == {
        "success": False,
        "error": "Offer creation authority denied",
        "reason": "OFFER_CREATION_AUTHORITY_DENIED",
        "_catalyst_effect_attempted": False,
    }
    assert effects == []
    assert database.get_offer_intents_for_registry() == []


def test_offer_manager_non_sage_backend_authority_stays_on_legacy_dispatch(
    isolated_database,
    monkeypatch,
):
    legacy_calls = []
    # Mutable/config-facing wallet type is deliberately wrong: dispatch must
    # use the adapter selection authority frozen by wallet.py at import.
    monkeypatch.setattr(offer_manager, "get_wallet_type", lambda: "sage")
    monkeypatch.setattr(
        wallet,
        "get_wallet_backend_authority",
        lambda: "chia",
        raising=False,
    )
    monkeypatch.setattr(
        wallet,
        "begin_offer_creation_continuation",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-Sage creation must not enter Task7 continuation")
        ),
    )

    def legacy_create(offer_dict, **kwargs):
        legacy_calls.append((dict(offer_dict), dict(kwargs)))
        return {
            "success": True,
            "trade_id": "legacy-chia-trade",
            "trade_record": {"trade_id": "legacy-chia-trade"},
            "offer": "offer1legacychia",
        }

    monkeypatch.setattr(offer_manager, "create_offer", legacy_create)

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is True
    assert result["locked_coin_id"] == COIN_A
    assert legacy_calls[0][1]["coin_ids"] == [COIN_A]
    assert database.get_offer_intents_for_registry() == []


def test_offer_manager_sage_backend_authority_ignores_mutable_type_drift(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(*_args, **_kwargs):
        effects.append(True)
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    begun, _closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    monkeypatch.setattr(offer_manager, "get_wallet_type", lambda: "chia")
    monkeypatch.setattr(wallet, "get_wallet_backend_authority", lambda: "sage")
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_A],
            "selected_present": True,
        },
    )

    result = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is True
    assert effects == [True]
    assert len(begun) == 1
    assert (
        database.get_offer_intent(result["_catalyst_intent_id"])["lifecycle_state"]
        == "created"
    )


def test_offer_manager_rejects_duplicate_wallet_ids_after_canonicalization(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, _closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )

    result = offer_manager.OfferManager().create_offer_with_retry(
        {1: -1000, "1": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_INTENT_INVALID"
    assert effects == []
    assert begun == []


@pytest.mark.parametrize(
    "offer_dict",
    [
        {"01": -1000, "2": 2000},
        {"0": -1000, "2": 2000},
        {1: -1000, "01": 2000},
    ],
)
def test_offer_manager_rejects_noncanonical_wallet_id_aliases_before_authority(
    isolated_database,
    monkeypatch,
    offer_dict,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, _closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )

    result = offer_manager.OfferManager().create_offer_with_retry(
        offer_dict,
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_INTENT_INVALID"
    assert effects == []
    assert begun == []


def test_offer_manager_rejects_incomplete_authority_proof_before_prepare(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    complete_journal = wallet.offer_creation_continuation_journal

    def incomplete_journal(capability):
        journal = complete_journal(capability)
        del journal["snapshot"]["authority"]["owner_pid"]
        encoded = json.dumps(
            journal["snapshot"],
            sort_keys=True,
            separators=(",", ":"),
        )
        journal["snapshot_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
        return journal

    monkeypatch.setattr(
        wallet,
        "offer_creation_continuation_journal",
        incomplete_journal,
    )

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_INTENT_INVALID"
    assert effects == []
    assert database.get_offer_intent(begun[0]["intent_id"]) is None
    assert closed == [begun[0]["capability"]]


def test_offer_manager_rejects_malformed_identity_observation_before_prepare(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    complete_journal = wallet.offer_creation_continuation_journal

    def malformed_journal(capability):
        journal = complete_journal(capability)
        journal["snapshot"]["observation"] = {"malformed": True}
        observation_encoded = json.dumps(
            journal["snapshot"]["observation"],
            sort_keys=True,
            separators=(",", ":"),
        )
        journal["snapshot"]["observation_digest"] = hashlib.sha256(
            observation_encoded.encode()
        ).hexdigest()
        snapshot_encoded = json.dumps(
            journal["snapshot"],
            sort_keys=True,
            separators=(",", ":"),
        )
        journal["snapshot_sha256"] = hashlib.sha256(
            snapshot_encoded.encode()
        ).hexdigest()
        return journal

    monkeypatch.setattr(
        wallet,
        "offer_creation_continuation_journal",
        malformed_journal,
    )

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_INTENT_INVALID"
    assert effects == []
    assert database.get_offer_intent(begun[0]["intent_id"]) is None
    assert closed == [begun[0]["capability"]]


def test_offer_manager_rejects_noncanonical_binding_snapshot_before_prepare(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    complete_journal = wallet.offer_creation_continuation_journal

    def noncanonical_journal(capability):
        journal = complete_journal(capability)
        journal["snapshot"]["binding"]["backend"] = "SAGE"
        snapshot_encoded = json.dumps(
            journal["snapshot"],
            sort_keys=True,
            separators=(",", ":"),
        )
        journal["snapshot_sha256"] = hashlib.sha256(
            snapshot_encoded.encode()
        ).hexdigest()
        return journal

    monkeypatch.setattr(
        wallet,
        "offer_creation_continuation_journal",
        noncanonical_journal,
    )

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_INTENT_INVALID"
    assert effects == []
    assert database.get_offer_intent(begun[0]["intent_id"]) is None
    assert closed == [begun[0]["capability"]]


class _HostileWalletResultValue:
    def __bool__(self):
        raise AssertionError("wallet result values must not be coerced to bool")

    def __str__(self):
        raise AssertionError("wallet result values must not be coerced to str")


class _HostileStatus(str):
    pass


def test_canonical_sage_offer_validation_does_not_require_full_chia(monkeypatch):
    real_import = builtins.__import__

    def unavailable_chia(name, *args, **kwargs):
        if name == "chia" or name.startswith("chia."):
            raise ImportError("full chia-blockchain is unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable_chia)

    assert (
        offer_manager.OfferManager._canonical_sage_offer_text(VALID_SAGE_OFFER)
        == VALID_SAGE_OFFER
    )


def test_canonical_sage_offer_validation_fails_closed_without_chia_rs(monkeypatch):
    real_import = builtins.__import__

    def unavailable_chia_rs(name, *args, **kwargs):
        if name == "chia_rs" or name.startswith("chia_rs."):
            raise ImportError("chia_rs is unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable_chia_rs)

    assert (
        offer_manager.OfferManager._canonical_sage_offer_text(VALID_SAGE_OFFER) is None
    )


@pytest.mark.parametrize(
    "offer_text",
    [
        # A canonical/checksummed, version-6 zlib stream whose payload is not a
        # SpendBundle.  A checksum/zlib-only validator would accept this.
        "offer1qqr83wcuu2rykjevft9zc2229j4dfnwt9lg5m4pd9eyv6j73f54v6j7ffyzsp83kpt9s66nysm",
        # A valid empty SpendBundle plus trailing bytes, recompressed and
        # Bech32 encoded with a valid checksum.
        "offer1qqr83wcuu2rykccqsgpsedq9z5qyn8gp8yxcrgqg",
    ],
)
def test_canonical_sage_offer_rejects_valid_wire_non_spend_bundles(offer_text):
    assert offer_manager.OfferManager._canonical_sage_offer_text(offer_text) is None


@pytest.mark.parametrize(
    "wallet_result",
    [
        {
            "success": True,
            "trade_id": "not-a-sage-id",
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "trade_id": "3" * 64,
            "trade_record": {"trade_id": "4" * 64},
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "trade_id": "3" * 64,
            "offer": "not-a-sage-offer",
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "error": "contradictory wallet error",
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "trade_id": "3" * 64,
            "offer": "offer1",
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "trade_id": "3" * 64,
            "offer": "offer1b",
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "trade_id": "3" * 64,
            "offer": "offer1qqqqqq",
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "trade_id": "3" * 64,
            "offer": "offer1qygzyaw",
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER.upper(),
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "error_message": "contradictory wallet error",
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "status": "failed",
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER + " ",
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "status": _HostileStatus("failed"),
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        },
        {
            "success": True,
            "status": object(),
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        },
    ],
)
def test_offer_manager_malformed_or_contradictory_sage_identity_is_unknown(
    isolated_database,
    monkeypatch,
    wallet_result,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(*_args, **_kwargs):
        effects.append(True)
        return dict(wallet_result)

    begun, _closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_A],
            "selected_present": True,
        },
    )

    result = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_RECONCILIATION_REQUIRED"
    assert effects == [True]
    assert intent["lifecycle_state"] == "creation_unknown"
    assert intent["sage_trade_id"] is None
    assert intent["offer_text_sha256"] is None
    assert (
        database.get_offer_intent_coin_reservations(intent["intent_id"])[0]["status"]
        == "reserved"
    )
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_offer_manager_hostile_success_fields_finalize_unknown_without_raising(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(*_args, **_kwargs):
        effects.append(True)
        return {
            "success": True,
            "trade_id": _HostileWalletResultValue(),
            "trade_record": _HostileWalletResultValue(),
            "offer": _HostileWalletResultValue(),
            "reason": _HostileWalletResultValue(),
            "_catalyst_effect_attempted": True,
        }

    begun, _closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_RECONCILIATION_REQUIRED"
    assert intent["lifecycle_state"] == "creation_unknown"
    assert (
        database.get_offer_intent_coin_reservations(intent["intent_id"])[0]["status"]
        == "reserved"
    )
    assert effects == [True]


def test_offer_manager_registry_denial_is_proven_no_effect_terminal_failure(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    monkeypatch.setattr(
        offer_manager.offer_registry,
        "authorize_mutation",
        lambda *_args, **_kwargs: offer_manager.offer_registry.AuthorizationDecision(
            allowed=False,
            code=offer_manager.offer_registry.AuthorizationCode.REGISTRY_BLOCKED,
            reason="blocked by test registry row",
        ),
    )
    manager = offer_manager.OfferManager()

    result = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert result["reason"] == "OFFER_CREATION_REGISTRY_DENIED"
    assert result["_catalyst_effect_attempted"] is False
    assert effects == []
    assert closed == [begun[0]["capability"]]
    assert intent["lifecycle_state"] == "creation_failed"
    assert (
        database.get_offer_intent_coin_reservations(intent["intent_id"])[0]["status"]
        == "released"
    )
    assert database.get_runtime_safety_latch()["state"] == "resolved"


def test_offer_manager_registry_exception_is_stable_proven_no_effect_failure(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_authorize_prepared_creation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("hostile registry failure")
        ),
    )

    result = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert result == {
        "success": False,
        "error": "Offer creation failed before wallet effect",
        "reason": "OFFER_CREATION_PRE_EFFECT_FAILED",
        "_catalyst_effect_attempted": False,
        "_catalyst_intent_id": intent["intent_id"],
    }
    assert effects == []
    assert closed == [begun[0]["capability"]]
    assert intent["lifecycle_state"] == "creation_failed"
    assert (
        database.get_offer_intent_coin_reservations(intent["intent_id"])[0]["status"]
        == "released"
    )
    assert database.get_runtime_safety_latch()["state"] == "resolved"


def test_offer_manager_post_commit_prepare_exception_is_stable_and_latched(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    real_prepare = database.prepare_offer_intent

    def committed_then_raised(**kwargs):
        real_prepare(**kwargs)
        raise RuntimeError("trailing committed-state read failed")

    monkeypatch.setattr(database, "prepare_offer_intent", committed_then_raised)

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_RECONCILIATION_REQUIRED"
    assert result["_catalyst_effect_attempted"] is False
    assert effects == []
    assert closed == [begun[0]["capability"]]
    assert intent["lifecycle_state"] == "prepared"
    assert (
        database.get_offer_intent_coin_reservations(intent["intent_id"])[0]["status"]
        == "reserved"
    )
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_offer_manager_pre_commit_prepare_rejection_never_false_latches(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    monkeypatch.setattr(
        database,
        "prepare_offer_intent",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("pre-commit rejection")),
    )

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_INTENT_INVALID"
    assert effects == []
    assert database.get_offer_intent(begun[0]["intent_id"]) is None
    assert database.get_runtime_safety_latch()["state"] == "resolved"
    assert closed == [begun[0]["capability"]]


def test_offer_manager_continuation_close_failure_never_masks_stable_failure(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []
    begun, _closed = _stub_offer_manager_wallet(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
    )
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_authorize_prepared_creation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("hostile registry failure")
        ),
    )
    monkeypatch.setattr(
        wallet,
        "close_offer_creation_continuation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("hostile close failure")
        ),
    )

    result = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert result["reason"] == "OFFER_CREATION_PRE_EFFECT_FAILED"
    assert result["_catalyst_effect_attempted"] is False
    assert effects == []
    assert intent["lifecycle_state"] == "creation_failed"


@pytest.mark.parametrize("failure_stage", ["verification", "finalization"])
def test_offer_manager_post_effect_exception_is_stable_unknown_and_latched(
    isolated_database,
    monkeypatch,
    failure_stage,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(*_args, **_kwargs):
        effects.append(True)
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    begun, _closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    if failure_stage == "verification":
        monkeypatch.setattr(
            manager,
            "_verify_sage_offer_locked_inputs",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("hostile verification failure")
            ),
        )
    else:
        monkeypatch.setattr(
            manager,
            "_verify_sage_offer_locked_inputs",
            lambda *_args, **_kwargs: {
                "verified": True,
                "locked_coin_ids": ["0x" + COIN_A],
                "selected_present": True,
            },
        )
        real_finalize = database.finalize_offer_intent
        failed_once = {"value": False}

        def fail_confirmed_once(**kwargs):
            if kwargs["lifecycle_state"] == "created" and not failed_once["value"]:
                failed_once["value"] = True
                raise RuntimeError("hostile confirmed finalization failure")
            return real_finalize(**kwargs)

        monkeypatch.setattr(database, "finalize_offer_intent", fail_confirmed_once)

    result = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_RECONCILIATION_REQUIRED"
    assert effects == [True]
    assert intent["lifecycle_state"] == "creation_unknown"
    assert (
        database.get_offer_intent_coin_reservations(intent["intent_id"])[0]["status"]
        == "reserved"
    )
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_offer_manager_latch_failure_does_not_mask_reconciliation_result(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(*_args, **_kwargs):
        effects.append(True)
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    begun, _closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("hostile verification failure")
        ),
    )
    monkeypatch.setattr(
        database,
        "trip_runtime_safety_latch",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("hostile latch failure")),
    )

    result = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert result["success"] is False
    assert result["reason"] == "OFFER_CREATION_RECONCILIATION_REQUIRED"
    assert effects == [True]
    assert intent["lifecycle_state"] == "creation_unknown"


@pytest.mark.parametrize(
    ("wallet_result", "expected_state", "expected_reservation"),
    [
        (
            {
                "success": False,
                "reason": "WALLET_REJECTED",
                "_catalyst_effect_attempted": False,
            },
            "creation_failed",
            "released",
        ),
        (
            {
                "success": False,
                "reason": "WALLET_MUTATION_FAILED",
                "_catalyst_effect_attempted": True,
            },
            "creation_unknown",
            "reserved",
        ),
        (
            {
                "success": True,
                "offer": "",
                "trade_id": "",
                "_catalyst_effect_attempted": True,
            },
            "creation_unknown",
            "reserved",
        ),
    ],
)
def test_offer_manager_finalizes_failed_or_unknown_from_exact_effect_evidence(
    isolated_database,
    monkeypatch,
    wallet_result,
    expected_state,
    expected_reservation,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(*_args, **_kwargs):
        effects.append(True)
        return dict(wallet_result)

    begun, _closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    call = lambda: manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        max_retries=4,
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    first = call()
    replay = call()

    intent = database.get_offer_intent(begun[0]["intent_id"])
    assert intent["lifecycle_state"] == expected_state
    assert (
        database.get_offer_intent_coin_reservations(intent["intent_id"])[0]["status"]
        == expected_reservation
    )
    assert len(effects) == 1
    assert first["success"] is False
    assert replay["success"] is False
    if expected_state == "creation_unknown":
        assert replay["reason"] == "OFFER_CREATION_RECONCILIATION_REQUIRED"
        assert database.get_runtime_safety_latch()["state"] == "tripped"
    else:
        assert replay["reason"] == "OFFER_CREATION_ALREADY_FINALIZED"
        assert database.get_runtime_safety_latch()["state"] == "resolved"


class _InjectedOfferCreationCrash(BaseException):
    pass


@pytest.mark.parametrize(
    ("phase", "expected_effects", "expected_state"),
    [
        ("before_intent_commit", 1, None),
        ("after_intent_commit", 0, "prepared"),
        ("before_wallet_call", 0, "prepared"),
        ("after_wallet_response", 1, "prepared"),
        ("before_trade_id_commit", 1, "prepared"),
        ("after_trade_id_commit", 1, "created"),
    ],
)
def test_offer_manager_crash_boundaries_never_resubmit_ambiguous_intent(
    isolated_database,
    monkeypatch,
    phase,
    expected_effects,
    expected_state,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    effects = []

    def effect(_offer_dict, **_kwargs):
        effects.append(True)
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    begun, closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_A],
            "selected_present": True,
        },
    )

    def crash_hook(observed_phase, _intent):
        if observed_phase == phase:
            raise _InjectedOfferCreationCrash(phase)

    manager._offer_creation_crash_hook = crash_hook
    call = lambda: manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        max_retries=2,
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )
    with pytest.raises(_InjectedOfferCreationCrash):
        call()
    intent_after_crash = database.get_offer_intent(begun[0]["intent_id"])
    manager._offer_creation_crash_hook = None
    retry = call()

    assert len(effects) == expected_effects
    if expected_state is None:
        assert intent_after_crash is None
        assert retry["success"] is True
        assert len(effects) == 1
    else:
        assert intent_after_crash["lifecycle_state"] == expected_state
        intent = database.get_offer_intent(begun[0]["intent_id"])
        if expected_state == "created":
            assert retry["success"] is True
            assert retry["_catalyst_idempotent_replay"] is True
        else:
            assert retry == {
                "success": False,
                "error": "Offer creation requires reconciliation",
                "reason": "OFFER_CREATION_RECONCILIATION_REQUIRED",
                "_catalyst_effect_attempted": False,
                "_catalyst_intent_id": intent["intent_id"],
            }
            reservations = database.get_offer_intent_coin_reservations(
                intent["intent_id"]
            )
            assert reservations[0]["status"] == "reserved"
            latch = database.get_runtime_safety_latch()
            assert latch["state"] == "tripped"
            assert begun[0]["operation_id"] in json.loads(
                latch["blocking_operation_ids_json"]
            )
    assert len(closed) == (
        1
        if phase
        in {"before_intent_commit", "after_intent_commit", "before_wallet_call"}
        else 0
    )


@pytest.mark.parametrize("race_kind", ["same_slot", "same_coin"])
def test_offer_manager_concurrent_creation_has_exactly_one_effect_winner(
    isolated_database,
    monkeypatch,
    race_kind,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    assert database.upsert_coin(COIN_B, "xch", 1000, designation="tier_spare")
    effects = []
    effects_lock = threading.Lock()

    def effect(_offer_dict, **_kwargs):
        with effects_lock:
            effects.append(True)
        return {
            "success": True,
            "trade_id": ("3" if len(effects) == 1 else "4") * 64,
            "offer": VALID_SAGE_OFFER,
            "_catalyst_effect_attempted": True,
        }

    begun, closed = _stub_offer_manager_wallet(monkeypatch, effect=effect)
    original_begin = wallet.begin_offer_creation_continuation
    authority_barrier = threading.Barrier(2)

    def synchronized_begin(**kwargs):
        capability = original_begin(**kwargs)
        authority_barrier.wait(timeout=5)
        return capability

    monkeypatch.setattr(wallet, "begin_offer_creation_continuation", synchronized_begin)
    managers = [offer_manager.OfferManager(), offer_manager.OfferManager()]
    for manager in managers:
        monkeypatch.setattr(
            manager,
            "_verify_sage_offer_locked_inputs",
            lambda *_args, **_kwargs: {
                "verified": True,
                "locked_coin_ids": ["0x" + COIN_A],
                "selected_present": True,
            },
        )
    contexts = [dict(CREATION_CONTEXT), dict(CREATION_CONTEXT)]
    coins = [COIN_A, COIN_B]
    if race_kind == "same_coin":
        coins[1] = COIN_A
        contexts[1]["slot_key"] = "ladder:buy:8"
    results = []
    result_lock = threading.Lock()

    def run(index):
        result = managers[index].create_offer_with_retry(
            {"1": -1000, "2": 2000 + index},
            coin_ids_enabled=True,
            selected_coin_id=coins[index],
            preferred_tier="inner",
            creation_context=contexts[index],
        )
        with result_lock:
            results.append(result)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(thread.is_alive() is False for thread in threads)
    assert len(effects) == 1
    assert sum(result.get("success") is True for result in results) == 1
    loser = next(result for result in results if result.get("success") is not True)
    assert loser == {
        "success": False,
        "error": "Offer creation claim lost",
        "reason": "OFFER_CREATION_RACE_LOST",
        "_catalyst_effect_attempted": False,
        "_catalyst_intent_id": loser["_catalyst_intent_id"],
    }
    assert len(begun) == 2
    assert len(closed) == 1
    assert (
        sum(
            database.get_offer_intent(entry["intent_id"]) is not None for entry in begun
        )
        == 1
    )


def test_mutation_gate_continuation_allows_only_its_prepared_blocker(
    isolated_database,
    monkeypatch,
):
    adapter = object()
    binding = _binding()
    clock = lambda: datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
    gate = mutation_gate.MutationGate(
        run_id="run-task7",
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
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    permit = mutation_gate.enter_wallet_mutation("wallet:create_offer")
    proof = mutation_gate.wallet_mutation_permit_journal_authority(
        permit, "wallet:create_offer"
    )
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    _prepare(intent_id="intent-a", operation_id="create:intent-a", coin_id=COIN_A)

    authorized_binding, authorized_adapter = (
        mutation_gate.require_wallet_operation_continuation(
            permit,
            "wallet:create_offer",
            "create:intent-a",
            "intent-a",
        )
    )
    fresh_binding, fresh_adapter, identity_decision = (
        mutation_gate.require_fresh_wallet_operation_continuation(
            permit,
            _identity(0),
            "wallet:create_offer:identity",
            "create:intent-a",
            "intent-a",
        )
    )

    assert proof["mode"] == "runtime"
    assert proof["owner_run_id"] == "run-task7"
    assert proof["lease_version"] == 1
    assert proof["lease_epoch"] == "2026-08-16T12:00:00.000000Z"
    assert len(proof["authority_generation_digest"]) == 64
    assert proof["binding_digest"] == mutation_gate.wallet_identity_binding_digest(
        binding
    )
    assert authorized_binding is binding
    assert authorized_adapter is adapter
    assert fresh_binding is binding
    assert fresh_adapter is adapter
    assert identity_decision["allowed"] is True
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
            "wallet:create_offer",
            "create:intent-a",
            "intent-a",
        )
    assert corrupt.value.reason_code == "UNRESOLVED_OPERATIONS"
    with pytest.raises(mutation_gate.MutationBlocked) as wrong:
        mutation_gate.require_wallet_operation_continuation(
            permit,
            "wallet:create_offer",
            "create:other-intent",
            "intent-a",
        )
    assert wrong.value.reason_code == "UNRESOLVED_OPERATIONS"
    database.finalize_offer_intent(
        intent_id="intent-a",
        operation_id="create:intent-a",
        event_id="final:unknown",
        lifecycle_state="creation_unknown",
        outcome="UNKNOWN",
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"effect_attempted": True},
        reason_code="CREATE_RESPONSE_AMBIGUOUS",
        finalized_at="2026-08-16T12:00:01Z",
        finalize_selected_coin_reservations=True,
    )
    with pytest.raises(mutation_gate.MutationBlocked) as unknown:
        mutation_gate.require_wallet_operation_continuation(
            permit,
            "wallet:create_offer",
            "create:intent-a",
            "intent-a",
        )
    assert unknown.value.reason_code == "UNRESOLVED_OPERATIONS"
    with pytest.raises(mutation_gate.MutationBlocked):
        gate.require_allowed("wallet:cancel_offer")

    assert mutation_gate.exit_wallet_mutation(permit) is True


def test_worker_continuation_journals_exact_delegation_generation_and_epoch(
    isolated_database,
    monkeypatch,
):
    adapter = object()
    binding = _binding()
    parent = mutation_gate.MutationGate(
        run_id="parent-task7",
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
        operation_id="create:intent-worker",
        purpose="offer-create",
        worker_id="worker-task7",
        ttl_seconds=120,
        require_wallet_identity=True,
    )
    monkeypatch.setattr(mutation_gate, "_runtime", None)
    mutation_gate.install_worker_authority_environment(
        handoff.to_environment(),
        wallet_adapter_authority=adapter,
    )
    try:
        permit = mutation_gate.enter_wallet_mutation("wallet:create_offer")
        proof = mutation_gate.wallet_mutation_permit_journal_authority(
            permit,
            "wallet:create_offer",
        )
        assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
        _prepare(
            intent_id="intent-worker",
            operation_id="create:intent-worker",
            coin_id=COIN_A,
        )

        authorized_binding, authorized_adapter = (
            mutation_gate.require_wallet_operation_continuation(
                permit,
                "wallet:create_offer",
                "create:intent-worker",
                "intent-worker",
            )
        )

        assert proof == {
            "mode": "worker",
            "delegation_id": handoff.delegation_id,
            "parent_run_id": handoff.parent_run_id,
            "delegation_operation_id": handoff.operation_id,
            "purpose": handoff.purpose,
            "worker_id": handoff.worker_id,
            "parent_lease_epoch": handoff.parent_lease_epoch,
            "authority_generation_digest": proof["authority_generation_digest"],
            "binding_digest": mutation_gate.wallet_identity_binding_digest(binding),
        }
        assert len(proof["authority_generation_digest"]) == 64
        assert authorized_binding == binding
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
                "wallet:create_offer",
                "create:intent-worker",
                "intent-worker",
            )
        assert corrupt.value.reason_code == "WORKER_PARENT_LEASE_INVALID"
        database.finalize_offer_intent(
            intent_id="intent-worker",
            operation_id="create:intent-worker",
            event_id="final:worker-unknown",
            lifecycle_state="creation_unknown",
            outcome="UNKNOWN",
            wallet_identity_json={"binding_digest": "d" * 64},
            evidence_json={"effect_attempted": True},
            reason_code="CREATE_RESPONSE_AMBIGUOUS",
            finalized_at="2026-08-16T12:00:01Z",
            finalize_selected_coin_reservations=True,
        )
        with pytest.raises(mutation_gate.MutationBlocked) as unknown:
            mutation_gate.require_wallet_operation_continuation(
                permit,
                "wallet:create_offer",
                "create:intent-worker",
                "intent-worker",
            )
        assert unknown.value.reason_code == "WORKER_PARENT_LEASE_INVALID"
        with pytest.raises(mutation_gate.MutationBlocked) as ordinary:
            mutation_gate.require_wallet_mutation_permit_authority(
                permit,
                "wallet:create_offer",
            )
        assert ordinary.value.reason_code == "WORKER_PARENT_LEASE_INVALID"
        assert mutation_gate.exit_wallet_mutation(permit) is True
    finally:
        mutation_gate.clear_worker_authority_environment()


def test_offer_manager_real_gate_and_wallet_continuation_cross_prepared_blocker(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    identities = [_identity(0), _identity(1), _identity(2)]
    effects = []

    def create_effect(*_args, **kwargs):
        kwargs["_identity_recheck"]("make_offer")
        effects.append(True)
        return {
            "success": True,
            "trade_id": "3" * 64,
            "offer": VALID_SAGE_OFFER,
        }

    adapter = SimpleNamespace(
        get_wallet_identity=lambda: identities.pop(0),
        create_offer=create_effect,
    )
    binding = _binding()
    gate = mutation_gate.MutationGate(
        run_id="run-task7",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network="mainnet",
        lease_seconds=30,
        clock=lambda: datetime(2026, 8, 16, 12, 0, 10, tzinfo=timezone.utc),
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(
        manager,
        "_verify_sage_offer_locked_inputs",
        lambda *_args, **_kwargs: {
            "verified": True,
            "locked_coin_ids": ["0x" + COIN_A],
            "selected_present": True,
        },
    )

    result = manager.create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    assert result["success"] is True, result
    assert result["_catalyst_effect_attempted"] is True
    assert effects == [True]
    assert identities == []
    assert gate.active_wallet_mutation_count() == 0
    assert (
        database.get_offer_intent(result["_catalyst_intent_id"])["lifecycle_state"]
        == "created"
    )


def test_offer_manager_adapter_local_rejection_finalizes_failed_and_releases(
    isolated_database,
    monkeypatch,
):
    assert database.upsert_coin(COIN_A, "xch", 1000, designation="tier_spare")
    identities = [_identity(0), _identity(1)]
    adapter_calls = []

    def reject_before_effect(*_args, **_kwargs):
        adapter_calls.append(True)
        return {"success": False, "reason": "LOCAL_VALIDATION_REJECTED"}

    adapter = SimpleNamespace(
        get_wallet_identity=lambda: identities.pop(0),
        create_offer=reject_before_effect,
    )
    binding = _binding()
    gate = mutation_gate.MutationGate(
        run_id="run-task7",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network="mainnet",
        lease_seconds=30,
        clock=lambda: datetime(2026, 8, 16, 12, 0, 10, tzinfo=timezone.utc),
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")

    result = offer_manager.OfferManager().create_offer_with_retry(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=True,
        selected_coin_id=COIN_A,
        preferred_tier="inner",
        creation_context=CREATION_CONTEXT,
    )

    intent = database.get_offer_intent(result["_catalyst_intent_id"])
    assert result["success"] is False
    assert result["reason"] == "LOCAL_VALIDATION_REJECTED"
    assert result["_catalyst_effect_attempted"] is False
    assert adapter_calls == [True]
    assert identities == []
    assert intent["lifecycle_state"] == "creation_failed"
    assert (
        database.get_offer_intent_coin_reservations(intent["intent_id"])[0]["status"]
        == "released"
    )
    assert database.get_runtime_safety_latch()["state"] == "resolved"
