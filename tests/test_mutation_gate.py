"""Durable mutation gate, run lease, and child delegation contracts."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import pickle
import signal
import sqlite3
import socket
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

import database
import mutation_gate


NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
WALLET_HASH = hashlib.sha256(b"wallet-a").hexdigest()
OTHER_WALLET_HASH = hashlib.sha256(b"wallet-b").hexdigest()


class Clock:
    def __init__(self, value: datetime = NOW):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def isolated_gate_database(tmp_path: Path, monkeypatch):
    original_path = database.DB_PATH
    original_initialized_path = database._db_initialized_path
    database.close_connection()
    path = tmp_path / "mutation-gate.db"
    database.DB_PATH = str(path)
    database._db_initialized_path = ""
    clock = Clock()
    monkeypatch.setattr(
        database,
        "_stability_wall_clock",
        lambda: clock().isoformat(timespec="microseconds").replace("+00:00", "Z"),
        raising=False,
    )
    database.init_database()
    try:
        yield path, clock
    finally:
        mutation_gate.shutdown_runtime()
        database.close_connection()
        database.DB_PATH = original_path
        database._db_initialized_path = original_initialized_path


def _gate(
    clock: Clock,
    *,
    run_id: str = "run-a",
    pid: int = 111,
    host: str = "test-host",
    pid_liveness=None,
) -> mutation_gate.MutationGate:
    return mutation_gate.MutationGate(
        run_id=run_id,
        owner_pid=pid,
        owner_host=host,
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        lease_seconds=30,
        clock=clock,
        pid_liveness=pid_liveness or (lambda _pid, _host: False),
    )


def _append_event(operation_id: str, *, blocks: bool, suffix: str) -> None:
    database.append_offer_operation_event(
        event_id=f"event:{operation_id}:{suffix}",
        operation_id=operation_id,
        operation_type="RECONCILE" if not blocks else "CREATE",
        attempt=1,
        phase="RECONCILED" if not blocks else "RESULT",
        outcome="CONFIRMED" if not blocks else "UNKNOWN",
        request_timestamp=NOW,
        evidence_json={"source": "test"},
        reason_code=None if not blocks else "CREATE_UNKNOWN",
        blocks_mutation=blocks,
        created_at=NOW,
    )


def _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch):
    original_platform = sys.platform
    monkeypatch.setattr(sys, "platform", "linux")
    sys.modules.pop("desktop_app", None)
    module = importlib.import_module("desktop_app")
    monkeypatch.setattr(sys, "platform", original_platform)
    return module


def test_trip_is_durable_across_runtime_and_module_reload(isolated_gate_database):
    _path, clock = isolated_gate_database
    first = _gate(clock)
    assert first.acquire()["acquired"] is True

    _append_event("create:1", blocks=True, suffix="unknown")
    tripped = first.trip("CREATE_UNKNOWN", ["create:1"])
    assert tripped.reason_code == "CREATE_UNKNOWN"
    assert tripped.allowed is False

    reloaded = importlib.reload(mutation_gate)
    restarted = reloaded.MutationGate(
        run_id="run-restarted",
        owner_pid=222,
        owner_host="test-host",
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        lease_seconds=30,
        clock=clock,
        pid_liveness=lambda _pid, _host: False,
    )
    status = restarted.status()
    assert status.allowed is False
    assert status.reason_code == "CREATE_UNKNOWN"
    assert status.latch_generation == 1
    assert status.blocking_operation_ids == ("create:1",)


def test_trip_notifies_once_and_late_handler_observes_latch(isolated_gate_database):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    _append_event("create:1", blocks=True, suffix="unknown")
    calls: list[str] = []
    gate.register_stop_handler(calls.append)

    threads = [
        threading.Thread(
            target=gate.trip,
            args=("CREATE_UNKNOWN", ["create:1"]),
        )
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls == ["CREATE_UNKNOWN"]
    late_calls: list[str] = []
    gate.register_stop_handler(late_calls.append)
    assert late_calls == ["CREATE_UNKNOWN"]
    gate.register_stop_handler(late_calls.append)
    assert late_calls == ["CREATE_UNKNOWN"]


def test_reason_codes_are_allowlisted_and_never_expose_exception_text(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    _append_event("create:1", blocks=True, suffix="unknown")
    secret = "rpc failed token=super-secret"

    status = gate.trip(secret, ["create:1"])

    assert status.reason_code == "MUTATION_GATE_SAFETY_STOP"
    assert secret not in repr(status)
    assert secret not in json.dumps(status.to_dict())
    assert secret not in str(database.get_runtime_safety_latch())


def test_fresh_durable_read_blocks_even_when_process_cache_was_healthy(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    gate.require_allowed("offer.create")
    _append_event("create:1", blocks=True, suffix="unknown")
    database.trip_runtime_safety_latch(
        reason_code="CREATE_UNKNOWN",
        blocking_operation_ids=["create:1"],
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        tripped_at=clock(),
    )

    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.require_allowed("offer.create")

    assert exc_info.value.reason_code == "CREATE_UNKNOWN"
    assert "offer.create" in str(exc_info.value)


def test_durable_read_failure_is_stable_fail_closed(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(
        database,
        "get_mutation_authorization_snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("password=do-not-leak")),
    )

    status = gate.status()

    assert status.allowed is False
    assert status.reason_code == "DURABLE_STATE_UNAVAILABLE"
    assert "do-not-leak" not in repr(status)
    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.require_allowed("coin.split")
    assert exc_info.value.reason_code == "DURABLE_STATE_UNAVAILABLE"


def test_release_requires_generation_and_every_journal_blocker_resolved(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    _append_event("create:1", blocks=True, suffix="unknown")
    gate.trip("CREATE_UNKNOWN", ["create:1"])

    stale = gate.release_resolved(0, ["create:1"])
    assert stale["released"] is False
    assert stale["reason"] == "generation_mismatch"
    unresolved = gate.release_resolved(1, ["create:1"])
    assert unresolved["released"] is False
    assert unresolved["reason"] == "blockers_still_unresolved"

    _append_event("create:1", blocks=False, suffix="reconciled")
    released = gate.release_resolved(1, ["create:1"])
    assert released["released"] is True
    assert gate.status().allowed is True


def test_release_rejects_a_different_wallet_or_network_binding(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    owner = _gate(clock)
    assert owner.acquire()["acquired"] is True
    _append_event("create:bound", blocks=True, suffix="unknown")
    owner.trip("CREATE_UNKNOWN", ["create:bound"])
    _append_event("create:bound", blocks=False, suffix="reconciled")
    wrong_binding = mutation_gate.MutationGate(
        run_id="run-wrong-binding",
        owner_pid=222,
        owner_host="test-host",
        wallet_fingerprint_hash=OTHER_WALLET_HASH,
        network="testnet11",
        lease_seconds=30,
        clock=clock,
        pid_liveness=lambda _pid, _host: False,
    )

    denied = wrong_binding.release_resolved(1, ["create:bound"])

    assert denied["released"] is False
    assert denied["reason"] == "latch_binding_mismatch"
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_two_independent_processes_cannot_both_acquire(
    isolated_gate_database,
):
    path, _clock = isolated_gate_database
    source_root = Path(__file__).resolve().parents[1] / "src" / "catalyst"
    code = r"""
import json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, sys.argv[1])
import database
database.close_connection()
database.DB_PATH = sys.argv[2]
database._db_initialized_path = ""
database.init_database()
import mutation_gate
gate = mutation_gate.MutationGate(
    run_id=sys.argv[3], owner_pid=os.getpid(), owner_host="race-host",
    wallet_fingerprint_hash=sys.argv[4], network="mainnet", lease_seconds=60,
)
print(json.dumps(gate.acquire()))
"""
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                code,
                str(source_root),
                str(path),
                f"run-{index}",
                WALLET_HASH,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(2)
    ]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout.strip().splitlines()[-1]))

    assert sum(bool(result["acquired"]) for result in results) == 1
    loser = next(result for result in results if not result["acquired"])
    assert loser["reason"] == "owned_by_other_run"


def test_expired_lease_is_not_stolen_while_prior_pid_is_alive(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    first = _gate(clock, run_id="run-a", pid=111)
    assert first.acquire()["acquired"] is True
    clock.advance(31)
    contender = _gate(
        clock,
        run_id="run-b",
        pid=222,
        pid_liveness=lambda pid, host: (
            True if (pid, host) == (111, "test-host") else None
        ),
    )

    result = contender.acquire()

    assert result["acquired"] is False
    assert result["reason"] == "prior_owner_alive"


@pytest.mark.parametrize("liveness", [None, True])
def test_remote_or_unknown_pid_state_never_proves_owner_dead(
    isolated_gate_database, liveness
):
    _path, clock = isolated_gate_database
    first = _gate(clock, run_id="run-a", pid=111, host="other-host")
    assert first.acquire()["acquired"] is True
    clock.advance(31)
    contender = _gate(
        clock,
        run_id="run-b",
        pid=222,
        host="test-host",
        pid_liveness=lambda _pid, _host: liveness,
    )

    result = contender.acquire()

    assert result["acquired"] is False
    assert result["reason"] == "prior_owner_liveness_unproven"


def test_dead_owner_takeover_requires_no_unresolved_journal_or_latch_work(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    first = _gate(clock, run_id="run-a", pid=111)
    assert first.acquire()["acquired"] is True
    clock.advance(31)
    _append_event("create:1", blocks=True, suffix="unknown")
    contender = _gate(clock, run_id="run-b", pid=222)

    blocked = contender.acquire()
    assert blocked["acquired"] is False
    assert blocked["reason"] == "unresolved_operations"

    _append_event("create:1", blocks=False, suffix="reconciled")
    database.trip_runtime_safety_latch(
        reason_code="CREATE_UNKNOWN",
        blocking_operation_ids=["create:1"],
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        tripped_at=clock(),
    )
    blocked_latch = contender.acquire()
    assert blocked_latch["acquired"] is False
    assert blocked_latch["reason"] == "safety_latch_tripped"

    assert database.resolve_runtime_safety_latch(
        expected_generation=1,
        resolved_operation_ids=["create:1"],
        resolved_at=clock(),
    )["resolved"]
    acquired = contender.acquire()
    assert acquired["acquired"] is True
    assert acquired["reason"] == "expired_lease_taken_over"


def test_heartbeat_is_exact_cas_monotonic_and_failure_flips_read_only(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    first_version = gate.status().lease_version
    clock.advance(10)
    heartbeat = gate.heartbeat()
    assert heartbeat["heartbeat"] is True
    assert gate.status().lease_version == first_version + 1

    real_heartbeat = database.heartbeat_runtime_mutation_lease
    monkeypatch.setattr(
        database,
        "heartbeat_runtime_mutation_lease",
        lambda **_kwargs: {
            "heartbeat": False,
            "reason": "compare_and_set_failed",
            "lease": database.get_runtime_mutation_lease(),
        },
    )
    failed = gate.heartbeat()
    monkeypatch.setattr(database, "heartbeat_runtime_mutation_lease", real_heartbeat)

    assert failed["heartbeat"] is False
    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.require_allowed("offer.cancel")
    assert exc_info.value.reason_code == "HEARTBEAT_FAILED"


def test_expired_heartbeat_cannot_resurrect_lease(isolated_gate_database):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    before = database.get_runtime_mutation_lease()
    clock.advance(31)

    result = gate.heartbeat()
    after = database.get_runtime_mutation_lease()

    assert result["heartbeat"] is False
    assert result["reason"] == "lease_expired"
    assert after["lease_version"] == before["lease_version"]
    assert after["expires_at"] == before["expires_at"]
    with pytest.raises(mutation_gate.MutationBlocked):
        gate.require_allowed("offer.create")


def test_concurrent_require_observes_process_fence_after_release(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    original_get = database.get_mutation_authorization_snapshot
    lease_read = threading.Event()
    continue_read = threading.Event()
    outcomes: list[str] = []

    def delayed_get(**kwargs):
        row = original_get(**kwargs)
        lease_read.set()
        assert continue_read.wait(timeout=5)
        return row

    monkeypatch.setattr(database, "get_mutation_authorization_snapshot", delayed_get)

    def require():
        try:
            gate.require_allowed("coin.split")
            outcomes.append("allowed")
        except mutation_gate.MutationBlocked as exc:
            outcomes.append(exc.reason_code)

    thread = threading.Thread(target=require)
    thread.start()
    assert lease_read.wait(timeout=5)
    assert gate.release_lease()["released"] is True
    continue_read.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert outcomes == ["LEASE_LOST"]


def test_database_write_lock_during_heartbeat_fails_closed(
    isolated_gate_database, monkeypatch
):
    path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")

    def short_timeout_connection():
        conn = sqlite3.connect(path, timeout=0.05, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=50")
        return conn

    monkeypatch.setattr(database, "_stability_connection", short_timeout_connection)
    try:
        result = gate.heartbeat()
    finally:
        blocker.rollback()
        blocker.close()

    assert result == {"heartbeat": False, "reason": "durable_state_unavailable"}
    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.require_allowed("coin.split")
    assert exc_info.value.reason_code == "HEARTBEAT_FAILED"


def test_release_uses_exact_owner_and_version_and_cannot_be_reused(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True

    released = gate.release_lease()
    again = gate.release_lease()

    assert released["released"] is True
    assert again["released"] is False
    assert again["reason"] == "not_owned"
    with pytest.raises(mutation_gate.MutationBlocked):
        gate.require_allowed("offer.create")


def test_delegation_is_hash_only_secret_safe_and_exactly_scoped(
    isolated_gate_database,
):
    path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True

    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:1",
        purpose="coin_prep",
        worker_id="worker-1",
        ttl_seconds=20,
    )
    child_env = handoff.to_environment()
    token = child_env[mutation_gate.DELEGATION_TOKEN_ENV]

    assert token not in repr(handoff)
    assert token not in json.dumps(handoff.public_dict())
    assert token.encode("utf-8") not in path.read_bytes()
    assert (
        gate.validate_worker_delegation(
            delegation_id=handoff.delegation_id,
            raw_token=token,
            parent_run_id=gate.run_id,
            operation_id="coin-prep:1",
            purpose="coin_prep",
            worker_id="worker-1",
        )["allowed"]
        is True
    )

    wrong_values = {
        "raw_token": "wrong-token",
        "parent_run_id": "wrong-parent",
        "operation_id": "wrong-operation",
        "purpose": "wrong-purpose",
        "worker_id": "wrong-worker",
        "wallet_fingerprint_hash": OTHER_WALLET_HASH,
        "network": "testnet11",
    }
    base = {
        "delegation_id": handoff.delegation_id,
        "raw_token": token,
        "parent_run_id": gate.run_id,
        "operation_id": "coin-prep:1",
        "purpose": "coin_prep",
        "worker_id": "worker-1",
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": "mainnet",
    }
    for key, value in wrong_values.items():
        candidate = dict(base)
        candidate[key] = value
        denied = gate.validate_worker_delegation(**candidate)
        assert denied == {"allowed": False, "reason": "worker_delegation_invalid"}


def test_delegation_expires_revokes_and_parent_lease_loss_invalidates_child(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True

    first = gate.issue_worker_delegation(
        operation_id="coin-prep:expire",
        purpose="coin_prep",
        worker_id="worker-expire",
        ttl_seconds=5,
    )
    first_env = first.to_environment()
    clock.advance(6)
    assert (
        gate.validate_worker_environment(first_env)["reason"]
        == "worker_delegation_invalid"
    )

    second = gate.issue_worker_delegation(
        operation_id="coin-prep:revoke",
        purpose="coin_prep",
        worker_id="worker-revoke",
        ttl_seconds=10,
    )
    second_env = second.to_environment()
    assert gate.revoke_worker_delegation(second)["revoked"] is True
    assert (
        gate.validate_worker_environment(second_env)["reason"]
        == "worker_delegation_invalid"
    )

    third = gate.issue_worker_delegation(
        operation_id="coin-prep:lease-loss",
        purpose="coin_prep",
        worker_id="worker-loss",
        ttl_seconds=10,
    )
    third_env = third.to_environment()
    assert gate.release_lease()["released"] is True
    assert (
        gate.validate_worker_environment(third_env)["reason"] == "parent_lease_invalid"
    )


def test_parent_heartbeat_keeps_delegation_valid_but_new_lease_epoch_does_not(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    parent = _gate(clock, run_id="run-parent", pid=111)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:1",
        purpose="coin_prep",
        worker_id="worker-1",
        ttl_seconds=60,
    )
    env = handoff.to_environment()
    clock.advance(10)
    assert parent.heartbeat()["heartbeat"] is True
    assert parent.validate_worker_environment(env)["allowed"] is True

    clock.advance(31)
    replacement = _gate(clock, run_id="run-next", pid=222)
    assert replacement.acquire()["acquired"] is True
    assert parent.validate_worker_environment(env)["reason"] == "parent_lease_invalid"


def test_os_pid_liveness_is_fail_closed_for_remote_host_and_current_process():
    local_host = socket.gethostname()
    assert mutation_gate.pid_liveness(os.getpid(), local_host) is True
    assert mutation_gate.pid_liveness(os.getpid(), "definitely-remote-host") is None


def test_module_runtime_helpers_require_initialization(isolated_gate_database):
    mutation_gate.shutdown_runtime()

    status = mutation_gate.status()

    assert status.allowed is False
    assert status.reason_code == "MUTATION_RUNTIME_NOT_INITIALIZED"
    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        mutation_gate.require_allowed("offer.create")
    assert exc_info.value.reason_code == "MUTATION_RUNTIME_NOT_INITIALIZED"


def test_delegation_has_no_generic_serialization_path_for_raw_token(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:serialize",
        purpose="coin_prep",
        worker_id="worker-serialize",
        ttl_seconds=10,
    )

    with pytest.raises(TypeError):
        asdict(handoff)
    with pytest.raises(TypeError):
        vars(handoff)
    with pytest.raises(TypeError):
        pickle.dumps(handoff)


def test_hostile_worker_environment_mapping_fails_closed(isolated_gate_database):
    class HostileMapping(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("secret=hostile")

    result = mutation_gate.validate_worker_environment(HostileMapping())

    assert result == {"allowed": False, "reason": "worker_delegation_invalid"}


def test_explicit_empty_worker_environment_never_falls_back_to_process_environment(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    parent = _gate(clock)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:environment",
        purpose="coin_prep",
        worker_id="worker-environment",
        ttl_seconds=30,
    )
    for key, value in handoff.to_environment().items():
        monkeypatch.setenv(key, value)

    with pytest.raises(mutation_gate.MutationBlocked):
        mutation_gate.require_worker_allowed_from_environment("coin.split", {})


def test_gate_status_serialization_is_bounded():
    status = mutation_gate.GateStatus(
        allowed=False,
        reason_code="UNRESOLVED_OPERATIONS",
        source="operation_journal",
        blocking_operation_ids=tuple(f"operation:{index}" for index in range(100)),
    )

    payload = status.to_dict()

    assert payload["blocking_operation_count"] == 100
    assert len(payload["blocking_operation_ids"]) == 32


def test_release_and_reacquire_same_run_invalidates_prior_delegation_epoch(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    parent = _gate(clock, run_id="run-parent", pid=111)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:epoch",
        purpose="coin_prep",
        worker_id="worker-epoch",
        ttl_seconds=60,
    )
    env = handoff.to_environment()
    assert parent.release_lease()["released"] is True
    clock.advance(1)
    assert parent.acquire()["acquired"] is True

    assert parent.validate_worker_environment(env)["reason"] == "parent_lease_invalid"


def test_api_write_route_classification_is_exhaustive_and_explicit(monkeypatch):
    monkeypatch.setenv("CMM_DATA_DIR", str(Path.cwd() / ".pytest-api-gate"))
    import api_server

    classified = (
        api_server._MUTATING_API_ENDPOINTS
        | api_server._READ_ONLY_WRITE_API_ENDPOINTS
        | api_server._CONTROL_WRITE_API_ENDPOINTS
    )
    write_endpoints = {
        rule.endpoint
        for rule in api_server.app.url_map.iter_rules()
        if {"POST", "PUT", "PATCH", "DELETE"}.intersection(rule.methods)
    }

    assert classified == write_endpoints
    assert not (
        api_server._MUTATING_API_ENDPOINTS & api_server._READ_ONLY_WRITE_API_ENDPOINTS
    )
    assert "offers.api_cancel_offer" in api_server._MUTATING_API_ENDPOINTS
    assert "coin_prep.api_coin_prep_trigger" in api_server._MUTATING_API_ENDPOINTS
    assert "sage.api_wallet_begin_startup" in api_server._MUTATING_API_ENDPOINTS
    assert "sage.api_wallet_retry_sage_connect" in api_server._MUTATING_API_ENDPOINTS
    assert "bot.api_bot_stop" in api_server._CONTROL_WRITE_API_ENDPOINTS


def test_api_blocks_mutation_but_keeps_diagnostics_and_read_only_posts(
    monkeypatch,
):
    import api_server

    api_server.app.testing = True
    client = api_server.app.test_client()
    auth = {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}
    denied = mutation_gate.GateStatus(
        allowed=False,
        reason_code="LEASE_OWNED_BY_OTHER",
        source="lease",
        lease_active=True,
        lease_version=7,
        lease_expires_at="2026-08-15T12:05:00.000000Z",
        owner_run_id="other-run",
        owner_pid=999,
    )
    calls = {"cancel": 0}

    class FakeOfferManager:
        def cancel_offers(self, *_args, **_kwargs):
            calls["cancel"] += 1
            return {}

    fake_bot = SimpleNamespace(
        offer_manager=FakeOfferManager(),
        is_running=lambda: False,
        coin_manager=SimpleNamespace(is_busy=lambda: False),
    )
    monkeypatch.setattr(api_server, "bot", fake_bot)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(api_server.mutation_gate, "status", lambda: denied)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "require_allowed",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )

    blocked = client.post(
        "/api/offers/cancel",
        json={"trade_id": "0x" + "a" * 64},
        headers=auth,
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    diagnostic = client.get(
        "/api/safety/status", environ_base={"REMOTE_ADDR": "127.0.0.1"}
    )
    read_only_post = client.post(
        "/api/settings/validate",
        json={"SPREAD_BPS": 100},
        headers=auth,
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert blocked.status_code == 423
    assert blocked.get_json() == {
        "success": False,
        "error": "mutation_gate_blocked",
        "reason": "LEASE_OWNED_BY_OTHER",
        "operation": "api:offers.api_cancel_offer",
    }
    assert calls["cancel"] == 0
    assert diagnostic.status_code == 200
    assert diagnostic.get_json()["safety"]["lease"]["owner_run_id"] == "other-run"
    assert read_only_post.status_code == 200


def test_non_owner_api_cannot_launch_or_restart_wallet_services(monkeypatch):
    import api_server
    import chia_node
    import sage_node

    calls = []
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "require_allowed",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    monkeypatch.setattr(
        chia_node, "set_auto_launch", lambda value: calls.append(("auto", value))
    )
    monkeypatch.setattr(chia_node, "start_preload", lambda: calls.append("chia"))
    monkeypatch.setattr(sage_node, "reset_preload", lambda: calls.append("reset"))
    monkeypatch.setattr(sage_node, "start_preload", lambda: calls.append("sage"))
    client = api_server.app.test_client()
    headers = {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}

    responses = [
        client.post(
            "/api/wallet/begin-startup",
            json={"auto_launch": True},
            headers=headers,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ),
        client.post(
            "/api/wallet/retry-sage-connect",
            headers=headers,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        ),
    ]

    assert [response.status_code for response in responses] == [423, 423]
    assert calls == []


def test_api_runtime_initialization_uses_config_binding_without_wallet_rpc(
    monkeypatch,
):
    import api_server

    captured = {}
    fake_gate = SimpleNamespace(
        last_acquire_result={"acquired": False, "reason": "owned_by_other_run"},
        register_stop_handler=lambda handler: captured.setdefault("handler", handler),
        status=lambda: mutation_gate.GateStatus(
            allowed=False,
            reason_code="LEASE_OWNED_BY_OTHER",
            source="lease",
        ),
    )

    def fake_initialize(**kwargs):
        captured.update(kwargs)
        return fake_gate

    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "736588221")
    monkeypatch.setattr(api_server.cfg, "WALLET_FINGERPRINT", "")
    monkeypatch.setattr(api_server.mutation_gate, "initialize", fake_initialize)
    monkeypatch.setattr(
        sys.modules["wallet"],
        "get_wallet_identity",
        lambda: (_ for _ in ()).throw(AssertionError("wallet RPC must not run")),
        raising=False,
    )

    result = api_server.initialize_mutation_runtime(start_heartbeat=False)

    expected_hash = hashlib.sha256(b"fingerprint:736588221").hexdigest()
    assert captured["wallet_fingerprint_hash"] == expected_hash
    assert captured["network"] == "mainnet"
    assert captured["start_heartbeat"] is False
    assert result["allowed"] is False
    assert result["reason_code"] == "LEASE_OWNED_BY_OTHER"


def test_app_bridge_mutation_methods_are_explicitly_guarded_and_return_dicts(
    monkeypatch,
):
    import api_server
    import app_bridge

    expected = {
        "activate_boost": "app_bridge:activate_boost",
        "begin_startup": "app_bridge:begin_startup",
        "cancel_all_offers": "app_bridge:cancel_all_offers",
        "cancel_offer": "app_bridge:cancel_offer",
        "cleanup_orphans": "app_bridge:cleanup_orphans",
        "deactivate_boost": "app_bridge:deactivate_boost",
        "start_bot": "app_bridge:start_bot",
        "trigger_coin_prep": "app_bridge:trigger_coin_prep",
        "trigger_topup": "app_bridge:trigger_topup",
    }
    assert {
        name: getattr(getattr(app_bridge.AppBridge, name), "_mutation_operation", None)
        for name in expected
    } == expected

    calls = []
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "require_allowed",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    monkeypatch.setattr(
        api_server,
        "api_cancel_offer",
        lambda: calls.append("handler-called"),
    )

    result = app_bridge.AppBridge().cancel_offer({"trade_id": "0x" + "a" * 64})

    assert result == {
        "success": False,
        "error": "mutation_gate_blocked",
        "reason": "LEASE_OWNED_BY_OTHER",
        "operation": "app_bridge:cancel_offer",
    }
    assert calls == []


def test_parent_launcher_uses_environment_only_and_revokes_on_request(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    parent = _gate(clock)
    assert parent.acquire()["acquired"] is True
    mutation_gate.shutdown_runtime()
    mutation_gate._runtime = parent
    import coin_manager

    env = {"SAFE": "value"}
    handoff = coin_manager._issue_coin_prep_worker_delegation(
        env,
        operation_id="coin-prep:run-1",
        worker_id="coin-prep-worker:run-1",
        ttl_seconds=30,
    )
    cmd = [sys.executable, "coin_prep_worker.py", "--run-id", "run-1"]

    assert env[mutation_gate.DELEGATION_TOKEN_ENV]
    assert env[mutation_gate.DELEGATION_TOKEN_ENV] not in " ".join(cmd)
    assert coin_manager._revoke_coin_prep_worker_delegation(handoff)["revoked"] is True
    assert parent.validate_worker_environment(env)["allowed"] is False


def test_worker_rejects_missing_wrong_and_dead_parent_before_wallet_callback(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    parent = _gate(clock)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:run-1",
        purpose="coin_prep",
        worker_id="coin-prep-worker:run-1",
        ttl_seconds=30,
    )
    import coin_prep_worker

    args = SimpleNamespace(run_id="run-1", sage_rpc_smoke=False)
    wallet_calls: list[str] = []
    for env in (
        {},
        {**handoff.to_environment(), mutation_gate.DELEGATION_TOKEN_ENV: "wrong"},
    ):
        with pytest.raises(mutation_gate.MutationBlocked):
            coin_prep_worker._validate_coin_prep_worker_delegation(args, env)
        assert wallet_calls == []

    valid = coin_prep_worker._validate_coin_prep_worker_delegation(
        args, handoff.to_environment()
    )
    assert valid["allowed"] is True

    assert parent.release_lease()["released"] is True
    with pytest.raises(mutation_gate.MutationBlocked):
        coin_prep_worker._guarded_wallet_mutation(
            "coin.split",
            lambda: wallet_calls.append("called"),
            environment=handoff.to_environment(),
        )
    assert wallet_calls == []


def test_worker_consumes_handoff_without_leaking_token_to_grandchildren(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    parent = _gate(clock)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:consume",
        purpose="coin_prep",
        worker_id="coin-prep-worker:consume",
        ttl_seconds=30,
    )
    import coin_prep_worker

    monkeypatch.setattr(coin_prep_worker, "_worker_delegation_environment", None)
    for key, value in handoff.to_environment().items():
        monkeypatch.setenv(key, value)
    args = SimpleNamespace(run_id="consume", sage_rpc_smoke=False)

    assert coin_prep_worker._validate_coin_prep_worker_delegation(args)["allowed"]
    assert all(
        key not in os.environ
        for key in (
            mutation_gate.DELEGATION_ID_ENV,
            mutation_gate.DELEGATION_TOKEN_ENV,
            mutation_gate.DELEGATION_PARENT_RUN_ENV,
            mutation_gate.DELEGATION_OPERATION_ENV,
            mutation_gate.DELEGATION_PURPOSE_ENV,
            mutation_gate.DELEGATION_WORKER_ENV,
            mutation_gate.DELEGATION_WALLET_ENV,
            mutation_gate.DELEGATION_NETWORK_ENV,
        )
    )
    calls = []
    coin_prep_worker._guarded_wallet_mutation(
        "coin.split", lambda: calls.append("called")
    )
    assert calls == ["called"]


def test_worker_has_no_direct_known_wallet_mutator_calls():
    source_path = (
        Path(__file__).resolve().parents[1] / "src" / "catalyst" / "coin_prep_worker.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    mutator_names = {
        "cancel_offers_batch",
        "combine_coins",
        "rpc_cancel_offer",
        "sage_login",
        "sage_split",
        "sage_topup_split",
        "send_cat_multi",
        "send_transaction",
        "send_transaction_multi",
        "split_coins_rpc",
    }

    direct_calls = [
        (node.lineno, node.func.id)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in mutator_names
    ]

    assert direct_calls == []


def test_worker_sage_rpc_smoke_is_explicitly_nonmutating_and_exempt(monkeypatch):
    import coin_prep_worker

    args = SimpleNamespace(run_id=None, sage_rpc_smoke=True)
    monkeypatch.setattr(
        coin_prep_worker.mutation_gate,
        "require_worker_allowed_from_environment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("smoke must not need mutation authority")
        ),
    )

    assert coin_prep_worker._validate_coin_prep_worker_delegation(args, {}) == {
        "allowed": True,
        "reason": "read_only_smoke",
    }
    with pytest.raises(mutation_gate.MutationBlocked):
        coin_prep_worker._validate_coin_prep_worker_delegation(
            SimpleNamespace(run_id=None, sage_rpc_smoke=1), {}
        )

    class HostileArgs:
        @property
        def sage_rpc_smoke(self):
            raise RuntimeError("secret=hostile-args")

    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        coin_prep_worker._validate_coin_prep_worker_delegation(HostileArgs(), {})
    assert exc_info.value.reason_code == "WORKER_DELEGATION_INVALID"


def test_terminal_process_fence_cannot_be_cleared_by_resolving_an_idle_latch(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(
        database,
        "heartbeat_runtime_mutation_lease",
        lambda **_kwargs: {"heartbeat": False, "reason": "compare_and_set_failed"},
    )

    assert gate.heartbeat()["heartbeat"] is False
    assert gate.status().reason_code == "HEARTBEAT_FAILED"


def test_terminal_fence_overrides_an_existing_latch_mirror(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    _append_event("create:terminal-precedence", blocks=True, suffix="unknown")
    gate.trip("CREATE_UNKNOWN", ["create:terminal-precedence"])
    monkeypatch.setattr(
        database,
        "heartbeat_runtime_mutation_lease",
        lambda **_kwargs: {"heartbeat": False, "reason": "compare_and_set_failed"},
    )

    assert gate.heartbeat()["heartbeat"] is False
    _append_event("create:terminal-precedence", blocks=False, suffix="reconciled")
    released = gate.release_resolved(1, ["create:terminal-precedence"])

    assert released["released"] is False
    assert released["reason"] == "terminal_process_fence"
    assert database.get_runtime_safety_latch()["state"] == "tripped"
    assert (
        database.resolve_runtime_safety_latch(
            expected_generation=1,
            resolved_operation_ids=["create:terminal-precedence"],
            resolved_at=clock(),
        )["resolved"]
        is True
    )
    assert gate.status().reason_code == "HEARTBEAT_FAILED"

    released = gate.release_resolved(0, [])

    assert released["released"] is False
    assert released["reason"] == "terminal_process_fence"
    assert gate.status().reason_code == "HEARTBEAT_FAILED"


def test_database_authorization_snapshot_is_complete(isolated_gate_database):
    snapshot = database.get_mutation_authorization_snapshot()

    assert set(snapshot) == {"latch", "unresolved", "lease", "delegation"}
    assert snapshot["latch"]["singleton_id"] == 1
    assert snapshot["lease"]["singleton_id"] == 1
    assert snapshot["unresolved"] == []
    assert snapshot["delegation"] is None


def test_authorization_snapshot_stays_coherent_during_concurrent_commit(
    isolated_gate_database, monkeypatch
):
    path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    original_connection = database._stability_connection
    interleaved = threading.Event()

    class InterleavingConnection:
        def __init__(self):
            self.inner = original_connection()

        def execute(self, sql, parameters=()):
            cursor = self.inner.execute(sql, parameters)
            if not interleaved.is_set() and "SELECT * FROM runtime_safety_latch" in sql:
                interleaved.set()
                writer = sqlite3.connect(str(path), timeout=5)
                try:
                    writer.execute("PRAGMA busy_timeout=5000")
                    writer.execute(
                        "UPDATE runtime_safety_latch "
                        "SET generation=generation+1 WHERE singleton_id=1"
                    )
                    writer.execute(
                        "UPDATE runtime_mutation_lease "
                        "SET active=0, lease_version=lease_version+1 WHERE singleton_id=1"
                    )
                    writer.commit()
                finally:
                    writer.close()
            return cursor

        def commit(self):
            return self.inner.commit()

        def rollback(self):
            return self.inner.rollback()

        def close(self):
            return self.inner.close()

    monkeypatch.setattr(database, "_stability_connection", InterleavingConnection)

    snapshot = database.get_mutation_authorization_snapshot()

    assert interleaved.is_set()
    assert snapshot["latch"]["generation"] == 0
    assert snapshot["lease"]["active"] == 1
    reader = sqlite3.connect(str(path))
    try:
        assert (
            reader.execute(
                "SELECT generation FROM runtime_safety_latch WHERE singleton_id=1"
            ).fetchone()[0]
            == 1
        )
        assert (
            reader.execute(
                "SELECT active FROM runtime_mutation_lease WHERE singleton_id=1"
            ).fetchone()[0]
            == 0
        )
    finally:
        reader.close()


def test_authorization_snapshot_rolls_back_and_closes_on_read_failure(monkeypatch):
    calls = []

    class BrokenConnection:
        def execute(self, sql, _parameters=()):
            calls.append(sql)
            if sql == "BEGIN":
                return self
            raise sqlite3.DatabaseError("read failed")

        def rollback(self):
            calls.append("rollback")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(database, "_stability_connection", lambda: BrokenConnection())

    with pytest.raises(sqlite3.DatabaseError, match="read failed"):
        database.get_mutation_authorization_snapshot()
    assert calls[-2:] == ["rollback", "close"]


def test_expired_takeover_rechecks_gate_inside_lease_transaction(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    prior = _gate(clock, run_id="prior", pid=111)
    assert prior.acquire()["acquired"] is True
    clock.advance(31)
    takeover = _gate(clock, run_id="takeover", pid=222)
    original_acquire = database.acquire_runtime_mutation_lease
    errors = []
    calls = []

    def trip_before_cas(**kwargs):
        calls.append(kwargs)
        try:
            _append_event("create:takeover-race", blocks=True, suffix="unknown")
            database.trip_runtime_safety_latch(
                reason_code="CREATE_UNKNOWN",
                reason="Creation outcome requires reconciliation",
                blocking_operation_ids=["create:takeover-race"],
                wallet_fingerprint_hash=WALLET_HASH,
                network="mainnet",
                tripped_at=clock(),
            )
            return original_acquire(**kwargs)
        except Exception as exc:
            errors.append(repr(exc))
            raise

    monkeypatch.setattr(database, "acquire_runtime_mutation_lease", trip_before_cas)

    result = takeover.acquire()

    assert calls
    assert errors == []
    assert result["acquired"] is False
    assert result["reason"] == "mutation_gate_blocked"


def test_owner_and_worker_authorization_use_only_one_database_snapshot(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    parent = _gate(clock)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:snapshot",
        purpose="coin_prep",
        worker_id="coin-prep-worker:snapshot",
        ttl_seconds=30,
    )
    environment = handoff.to_environment()
    delegation = database.get_valid_worker_delegation(
        delegation_id=handoff.delegation_id,
        delegation_token_hash=hashlib.sha256(
            environment[mutation_gate.DELEGATION_TOKEN_ENV].encode("utf-8")
        ).hexdigest(),
        parent_run_id=parent.run_id,
        operation_id=handoff.operation_id,
        purpose=handoff.purpose,
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        now=clock(),
    )
    snapshot = {
        "latch": database.get_runtime_safety_latch(),
        "unresolved": [],
        "lease": database.get_runtime_mutation_lease(),
        "delegation": delegation,
    }
    calls = []

    def atomic_snapshot(**kwargs):
        calls.append(kwargs)
        return snapshot

    monkeypatch.setattr(
        database,
        "get_mutation_authorization_snapshot",
        atomic_snapshot,
        raising=False,
    )

    def legacy_read(*_args, **_kwargs):
        raise AssertionError("authorization must not use split legacy reads")

    for name in (
        "get_runtime_safety_latch",
        "get_unresolved_offer_operation_blockers",
        "get_runtime_mutation_lease",
        "get_valid_worker_delegation",
    ):
        monkeypatch.setattr(database, name, legacy_read)

    assert parent.status().allowed is True
    assert parent.validate_worker_environment(environment)["allowed"] is True
    assert len(calls) == 2
    assert calls[0] == {}
    assert calls[1]["delegation_id"] == handoff.delegation_id


def test_repeated_initialize_is_idempotent_and_mismatch_requires_shutdown(
    isolated_gate_database,
):
    _path, _clock = isolated_gate_database
    first = mutation_gate.initialize(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        owner_pid=321,
        owner_host="test-host",
        start_heartbeat=False,
    )

    again = mutation_gate.initialize(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        owner_pid=321,
        owner_host="test-host",
        start_heartbeat=False,
    )

    assert again is first
    with pytest.raises(RuntimeError, match="shutdown_runtime"):
        mutation_gate.initialize(
            wallet_fingerprint_hash=OTHER_WALLET_HASH,
            network="testnet11",
            owner_pid=654,
            owner_host="test-host",
            start_heartbeat=False,
        )
    lease = database.get_runtime_mutation_lease()
    assert lease["owner_run_id"] == first.run_id
    assert lease["active"] == 1


def test_identical_read_only_runtime_can_explicitly_promote_through_full_acquire(
    isolated_gate_database,
):
    _path, _clock = isolated_gate_database
    read_only = mutation_gate.initialize(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        owner_pid=322,
        owner_host="test-host",
        start_heartbeat=False,
        acquire_lease=False,
    )
    assert read_only.last_acquire_result == {
        "acquired": False,
        "reason": "not_attempted",
    }
    assert database.get_runtime_mutation_lease()["active"] == 0

    promoted = mutation_gate.initialize(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        owner_pid=322,
        owner_host="test-host",
        start_heartbeat=False,
        acquire_lease=True,
    )

    assert promoted is read_only
    assert promoted.last_acquire_result["acquired"] is True
    lease = database.get_runtime_mutation_lease()
    assert lease["active"] == 1
    assert lease["owner_run_id"] == promoted.run_id


def test_non_acquiring_runtime_uses_sqlite_read_only_authorization_snapshot(
    isolated_gate_database, monkeypatch
):
    _path, _clock = isolated_gate_database
    gate = mutation_gate.initialize(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        owner_pid=323,
        owner_host="test-host",
        start_heartbeat=False,
        acquire_lease=False,
    )
    original = database.get_mutation_authorization_snapshot
    calls = []

    def capture(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(database, "get_mutation_authorization_snapshot", capture)

    assert gate.status().allowed is False
    assert calls == [{"read_only": True}]


def test_read_only_status_fails_closed_without_creating_a_missing_database(
    tmp_path, monkeypatch
):
    missing = tmp_path / "missing" / "catalyst.db"
    monkeypatch.setattr(database, "DB_PATH", str(missing))
    gate = mutation_gate.MutationGate(
        run_id="diagnostics-missing-db",
        owner_pid=324,
        owner_host="test-host",
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        read_only=True,
    )

    status = gate.status()

    assert status.allowed is False
    assert status.reason_code == "DURABLE_STATE_UNAVAILABLE"
    assert not missing.exists()


def test_non_owner_blocks_destructive_routes_and_unknown_writes_by_default(
    monkeypatch,
):
    import api_server

    destructive = {
        "config_bp.api_config_update",
        "offers.api_purge_fills",
        "offers.api_reset_full",
        "offers.api_reset_offer_history",
        "session.api_session_fresh_start",
        "cat.api_deposit_advisory_allocate",
        "market.api_dexie_repost",
    }
    assert destructive <= api_server._MUTATING_API_ENDPOINTS
    assert destructive.isdisjoint(api_server._CONTROL_WRITE_API_ENDPOINTS)
    assert api_server._write_endpoint_requires_mutation("future.new_write") is True
    assert api_server._write_endpoint_requires_mutation("bot.api_bot_stop") is False

    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "require_allowed",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    response = api_server.app.test_client().post(
        "/api/reset/full",
        json={"confirm": True},
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 423
    assert response.get_json()["reason"] == "LEASE_OWNED_BY_OTHER"


def test_all_direct_bridge_shared_mutations_have_gate_metadata():
    import app_bridge

    expected = {
        "apply_config",
        "begin_startup",
        "clear_logs",
        "dismiss_alert",
        "download_splash_setup",
        "fresh_start",
        "live_config",
        "purge_fills",
        "reload_config",
        "repost_dexie",
        "reset_coin_prep",
        "reset_full",
        "reset_offer_history",
        "reset_pnl",
        "select_cat",
        "set_sage_fingerprint",
        "set_splash_receive",
        "setup_certs",
        "setup_spacescan",
        "start_splash_node",
        "start_update_install",
        "start_with_fingerprint",
        "update_config",
    }

    assert all(
        getattr(getattr(app_bridge.AppBridge, name), "_mutation_operation", None)
        for name in expected
    )


def test_coin_prep_cancel_revokes_and_clears_manager_delegation(monkeypatch):
    import api_server
    import coin_manager
    from blueprints import coin_prep

    class Process:
        pid = 4567

        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

    delegation = object()
    manager = SimpleNamespace(
        _prep_process=Process(),
        _prep_delegation=delegation,
        _prep_running=True,
        _lock=threading.Lock(),
    )
    monkeypatch.setattr(
        api_server, "bot", SimpleNamespace(coin_manager=manager), raising=False
    )
    monkeypatch.setattr(api_server, "_coin_prep_proc", None)
    monkeypatch.setattr(coin_prep, "log_event", lambda *_args, **_kwargs: None)
    revoked = []
    monkeypatch.setattr(
        coin_manager,
        "_revoke_coin_prep_worker_delegation",
        lambda item: revoked.append(item) or {"revoked": True},
    )

    with api_server.app.test_request_context("/api/coin-prep/cancel", method="POST"):
        response = coin_prep.api_coin_prep_cancel()

    assert response.get_json()["success"] is True
    assert revoked == [delegation]
    assert manager._prep_delegation is None


def test_coin_prep_reset_rejects_a_live_worker(monkeypatch):
    import api_server
    from blueprints import coin_prep

    process = SimpleNamespace(poll=lambda: None)
    manager = SimpleNamespace(_prep_process=process, _prep_running=True)
    monkeypatch.setattr(
        api_server, "bot", SimpleNamespace(coin_manager=manager), raising=False
    )
    monkeypatch.setattr(api_server, "_coin_prep_proc", None)
    monkeypatch.setitem(api_server._coin_prep_state, "running", True)

    with api_server.app.test_request_context("/api/coin-prep/reset", method="POST"):
        response, status_code = coin_prep.api_coin_prep_reset()

    assert status_code == 409
    assert response.get_json()["error"] == "coin_prep_still_running"
    assert manager._prep_running is True


def test_desktop_cleanup_releases_lease_even_when_bot_stop_fails(monkeypatch):
    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    class Bot:
        _running = True

        def stop(self):
            raise RuntimeError("stop failed")

    released = []
    monkeypatch.setattr(api_server, "bot", Bot())
    monkeypatch.setattr(
        api_server,
        "release_mutation_runtime",
        lambda: released.append(True) or {"released": True},
    )
    monkeypatch.setattr(database, "log_event", lambda *_args, **_kwargs: None)

    desktop_app._cleanup()

    assert released == [True]


def test_second_desktop_process_enters_alternate_port_diagnostics(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    started = []
    monkeypatch.setattr(desktop_app, "_acquire_instance_lock", lambda: False)
    monkeypatch.setattr(desktop_app, "_open_existing_instance_in_browser", lambda: None)
    monkeypatch.setattr(
        desktop_app,
        "_find_available_diagnostics_port",
        lambda preferred: preferred + 7,
        raising=False,
    )
    monkeypatch.setattr(
        desktop_app,
        "run_read_only_diagnostics_mode",
        lambda port: started.append(port),
        raising=False,
    )

    assert desktop_app.main(["--show-console"]) == 0
    assert started == [desktop_app.FLASK_PORT + 7]


def test_diagnostics_server_never_constructs_bot_or_acquires_lease(monkeypatch):
    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    calls = []
    monkeypatch.setattr(
        database,
        "init_database",
        lambda: (_ for _ in ()).throw(
            AssertionError("diagnostics cannot initialize or migrate the database")
        ),
    )
    monkeypatch.setattr(
        api_server,
        "init_database",
        lambda: (_ for _ in ()).throw(
            AssertionError("diagnostics cannot initialize or migrate the database")
        ),
    )
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda **kwargs: calls.append(("initialize", kwargs)) or {},
    )
    monkeypatch.setattr(
        api_server,
        "create_bot",
        lambda: (_ for _ in ()).throw(AssertionError("diagnostics cannot create bot")),
    )
    monkeypatch.setattr(
        api_server.app,
        "run",
        lambda **kwargs: calls.append(("run", kwargs)),
    )

    desktop_app.run_read_only_diagnostics_mode(5017)

    assert ("initialize", {"start_heartbeat": False, "acquire_lease": False}) in calls
    assert (
        "run",
        {
            "host": "127.0.0.1",
            "port": 5017,
            "debug": False,
            "threaded": True,
            "use_reloader": False,
        },
    ) in calls


def test_standalone_diagnostics_server_is_database_read_only(monkeypatch):
    import api_server

    calls = []
    monkeypatch.setattr(
        api_server,
        "init_database",
        lambda: (_ for _ in ()).throw(
            AssertionError("diagnostics cannot initialize or migrate the database")
        ),
    )
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda **kwargs: calls.append(("initialize", kwargs)) or {},
    )
    monkeypatch.setattr(
        api_server.app,
        "run",
        lambda **kwargs: calls.append(("run", kwargs)),
    )

    api_server._serve_read_only_diagnostics(5018)

    assert calls == [
        ("initialize", {"start_heartbeat": False, "acquire_lease": False}),
        (
            "run",
            {
                "host": "127.0.0.1",
                "port": 5018,
                "debug": False,
                "threaded": True,
                "use_reloader": False,
            },
        ),
    ]


def test_diagnostics_mode_exposes_only_bounded_safety_status(monkeypatch):
    import api_server

    denied = mutation_gate.GateStatus(
        allowed=False,
        reason_code="LEASE_OWNED_BY_OTHER",
        source="lease",
        owner_run_id="owner-run",
        owner_pid=456,
    )
    monkeypatch.setattr(api_server, "_read_only_diagnostics_active", True)
    monkeypatch.setattr(api_server.mutation_gate, "status", lambda: denied)
    client = api_server.app.test_client()

    safety = client.get("/api/safety/status", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    ordinary = client.get("/api/status", environ_base={"REMOTE_ADDR": "127.0.0.1"})

    assert safety.status_code == 200
    assert safety.get_json()["safety"]["lease"]["owner_run_id"] == "owner-run"
    assert ordinary.status_code == 423
    assert ordinary.get_json() == {
        "success": False,
        "error": "diagnostics_read_only",
        "reason": "DIAGNOSTICS_READ_ONLY",
    }


def test_standalone_diagnostics_shutdown_has_no_shared_side_effects(monkeypatch):
    import api_server
    import chia_node

    calls = []
    monkeypatch.setattr(
        api_server,
        "backup_database",
        lambda: calls.append("backup"),
    )
    monkeypatch.setattr(
        chia_node,
        "stop_chia",
        lambda *_args, **_kwargs: calls.append("stop-chia") or {"success": True},
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "shutdown_runtime",
        lambda: calls.append("local-runtime") or {"released": False},
    )
    monkeypatch.setattr(
        api_server,
        "bot",
        SimpleNamespace(
            is_running=lambda: True,
            stop=lambda: calls.append("stop-bot"),
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        api_server._read_only_diagnostics_shutdown(signal.SIGTERM, None)

    assert exc_info.value.code == 0
    assert calls == ["local-runtime"]


def test_standalone_port_selection_honors_env_and_falls_back_to_diagnostics(
    monkeypatch,
):
    import api_server

    monkeypatch.setenv("CATALYST_FLASK_PORT", "5123")
    monkeypatch.setattr(
        api_server,
        "_loopback_port_is_available",
        lambda port: port == 5124,
        raising=False,
    )

    assert api_server._configured_flask_port() == 5123
    assert api_server._select_standalone_server_mode(5123) == (5124, True)
