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
import time
import urllib.error
import urllib.request
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
    mutation_gate.clear_worker_authority_environment()
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
        mutation_gate.clear_worker_authority_environment()
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


def _identity_gate(clock: Clock):
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Delegated Wallet",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=(NOW - timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=15,
    )
    gate = mutation_gate.MutationGate(
        run_id="identity-parent",
        owner_pid=111,
        owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network=binding.network_id,
        lease_seconds=30,
        clock=clock,
        pid_liveness=lambda _pid, _host: False,
        wallet_identity_binding=binding,
    )
    return gate, binding


def _wallet_owner(clock: Clock, adapter, *, run_id: str, pid: int = 111):
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Permit Wallet",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=(clock() - timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=15,
    )
    runtime = mutation_gate.MutationGate(
        run_id=run_id,
        owner_pid=pid,
        owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network=binding.network_id,
        lease_seconds=30,
        clock=clock,
        pid_liveness=lambda _pid, _host: False,
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    return runtime, binding


def _wallet_snapshot(clock: Clock, binding):
    clock.advance(1)
    return {
        "success": True,
        "backend": "sage",
        "name": binding.name,
        "fingerprint": binding.fingerprint,
        "network_id": binding.network_id,
        "kind": binding.kind,
        "has_secrets": True,
        "observed_at_utc": clock()
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }


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


def _active_delegation_row(handoff, environment, now):
    return database.get_valid_worker_delegation(
        delegation_id=handoff.delegation_id,
        delegation_token_hash=hashlib.sha256(
            environment[mutation_gate.DELEGATION_TOKEN_ENV].encode("utf-8")
        ).hexdigest(),
        parent_run_id=handoff.parent_run_id,
        operation_id=handoff.operation_id,
        purpose=handoff.purpose,
        wallet_fingerprint_hash=handoff.wallet_fingerprint_hash,
        network=handoff.network,
        now=now,
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
    secret = "rpc failed token=test-placeholder-secret"

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


def test_release_supports_native_bulk_cancel_cohort_above_legacy_64_cap(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    operation_ids = [f"cancel:{index:064x}" for index in range(71)]
    for operation_id in operation_ids:
        _append_event(operation_id, blocks=True, suffix="unknown")
    gate.trip("CANCEL_SUBMITTED_UNCONFIRMED", operation_ids)
    for operation_id in operation_ids:
        _append_event(operation_id, blocks=False, suffix="reconciled")

    released = gate.release_resolved(1, operation_ids)

    assert released["released"] is True
    assert released["reason"] == "released"
    assert gate.status().allowed is True


def test_release_clears_matching_local_fence_after_external_durable_resolution(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    operation_id = "create:external-reconciliation"
    _append_event(operation_id, blocks=True, suffix="unknown")
    gate.trip("CREATE_UNKNOWN", [operation_id])
    _append_event(operation_id, blocks=False, suffix="reconciled")
    durable = database.resolve_runtime_safety_latch(
        expected_generation=1,
        resolved_operation_ids=[operation_id],
        resolved_at=clock(),
    )
    assert durable["resolved"] is True
    assert gate.status().allowed is False

    released = gate.release_resolved(1, [operation_id])

    assert released["released"] is True
    assert released["reason"] == "released"
    assert gate.status().allowed is True


def test_read_only_status_does_not_install_a_transient_durable_latch_fence(
    isolated_gate_database,
):
    """Diagnostics must observe a worker latch without mutating owner state."""

    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    operation_id = "create:diagnostic-read"
    _append_event(operation_id, blocks=True, suffix="submitted")
    database.trip_runtime_safety_latch(
        reason_code="CREATE_UNKNOWN",
        blocking_operation_ids=[operation_id],
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        tripped_at=clock(),
    )

    observed = gate.read_only_status()

    assert observed.allowed is False
    assert observed.source == "durable_latch"
    _append_event(operation_id, blocks=False, suffix="confirmed")
    assert (
        database.resolve_runtime_safety_latch(
            expected_generation=1,
            resolved_operation_ids=[operation_id],
            resolved_at=clock(),
        )["resolved"]
        is True
    )

    assert gate.read_only_status().allowed is True
    assert gate.status().allowed is True


def test_release_resolved_serializes_heartbeat_through_post_resolve_status(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    _append_event("create:release-race", blocks=True, suffix="unknown")
    gate.trip("CREATE_UNKNOWN", ["create:release-race"])
    _append_event("create:release-race", blocks=False, suffix="reconciled")
    clock.advance(1)

    progress = threading.Event()
    snapshot_captured = threading.Event()
    continue_release = threading.Event()
    heartbeat_done = threading.Event()
    observed = {}

    class ObservableRLock:
        def __init__(self):
            self._inner = threading.RLock()
            self._state_lock = threading.Lock()
            self._owner = None
            self._depth = 0

        def acquire(self, *args, **kwargs):
            thread_id = threading.get_ident()
            with self._state_lock:
                contended = self._owner is not None and self._owner != thread_id
            if contended:
                observed.setdefault("path", "contended")
                progress.set()
            acquired = self._inner.acquire(*args, **kwargs)
            if acquired:
                with self._state_lock:
                    if self._owner == thread_id:
                        self._depth += 1
                    else:
                        self._owner = thread_id
                        self._depth = 1
            return acquired

        def release(self):
            thread_id = threading.get_ident()
            with self._state_lock:
                assert self._owner == thread_id
                self._depth -= 1
                if self._depth == 0:
                    self._owner = None
            self._inner.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.release()

    gate._lock = ObservableRLock()
    original_snapshot = gate._authorization_snapshot
    original_heartbeat = database.heartbeat_runtime_mutation_lease

    def pause_after_snapshot():
        snapshot = original_snapshot()
        if not snapshot_captured.is_set():
            snapshot_captured.set()
            assert continue_release.wait(5)
        return snapshot

    def observe_heartbeat(**kwargs):
        observed.setdefault("path", "heartbeat_entered")
        progress.set()
        try:
            return original_heartbeat(**kwargs)
        finally:
            heartbeat_done.set()

    monkeypatch.setattr(gate, "_authorization_snapshot", pause_after_snapshot)
    monkeypatch.setattr(database, "heartbeat_runtime_mutation_lease", observe_heartbeat)
    release_result = {}
    heartbeat_result = {}
    release_thread = threading.Thread(
        target=lambda: release_result.update(
            gate.release_resolved(1, ["create:release-race"])
        )
    )
    heartbeat_thread = threading.Thread(
        target=lambda: heartbeat_result.update(gate.heartbeat())
    )

    release_thread.start()
    assert snapshot_captured.wait(5)
    heartbeat_thread.start()
    try:
        assert progress.wait(5)
        if observed.get("path") == "heartbeat_entered":
            assert heartbeat_done.wait(5)
    finally:
        continue_release.set()
    release_thread.join(5)
    heartbeat_thread.join(5)

    assert observed["path"] == "contended"
    assert release_result["released"] is True
    assert heartbeat_result.get("heartbeat") is True, heartbeat_result
    assert gate.status().allowed is True
    already_resolved = gate.release_resolved(1, ["create:release-race"])
    assert already_resolved["released"] is False
    assert already_resolved["reason"] == "not_tripped"
    assert already_resolved["status"]["allowed"] is True


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


@pytest.mark.parametrize(
    ("prior_host", "contender_host"),
    [
        ("catalyst-host", "catalyst-host.example.test"),
        ("catalyst-host.example.test", "catalyst-host"),
    ],
)
def test_short_and_fqdn_local_aliases_delegate_takeover_to_pid_liveness(
    isolated_gate_database,
    prior_host: str,
    contender_host: str,
):
    _path, clock = isolated_gate_database
    first = _gate(clock, run_id="run-a", pid=111, host=prior_host)
    assert first.acquire()["acquired"] is True
    clock.advance(31)
    probes = []
    contender = _gate(
        clock,
        run_id="run-b",
        pid=222,
        host=contender_host,
        pid_liveness=lambda pid, host: probes.append((pid, host)) or False,
    )

    result = contender.acquire()

    assert result["acquired"] is True
    assert probes == [(111, prior_host)]


@pytest.mark.parametrize("owner_host", ["catalyst-host", "catalyst-host.example.test"])
def test_default_pid_liveness_recognizes_local_short_and_fqdn_aliases(
    monkeypatch,
    owner_host: str,
):
    monkeypatch.setattr(socket, "gethostname", lambda: "catalyst-host")
    monkeypatch.setattr(socket, "getfqdn", lambda: "catalyst-host.example.test")

    def missing(_pid, _signal):
        raise ProcessLookupError

    if os.name != "nt":
        monkeypatch.setattr(os, "kill", missing)
        assert mutation_gate.pid_liveness(919191, owner_host) is False
    else:
        assert owner_host.casefold() in {
            socket.gethostname().casefold(),
            socket.getfqdn().casefold(),
        }


@pytest.mark.parametrize(
    "factory_name",
    ["_stability_connection", "_stability_read_only_connection"],
)
def test_stability_connection_factory_closes_handle_when_setup_pragma_fails(
    monkeypatch,
    factory_name: str,
):
    class BrokenConnection:
        row_factory = None

        def __init__(self):
            self.closed = False

        def create_function(self, *_args, **_kwargs):
            return None

        def execute(self, _statement):
            raise sqlite3.OperationalError("pragma setup failed")

        def close(self):
            self.closed = True

    connection = BrokenConnection()
    monkeypatch.setattr(
        database.sqlite3, "connect", lambda *_args, **_kwargs: connection
    )

    with pytest.raises(sqlite3.OperationalError):
        getattr(database, factory_name)()

    assert connection.closed is True


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
    assert result["reason"] == (
        "prior_owner_alive" if liveness is True else "prior_owner_liveness_unproven"
    )


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
    releases = []
    release_thread = threading.Thread(
        target=lambda: releases.append(gate.release_lease())
    )
    release_thread.start()
    release_thread.join(timeout=0.05)
    assert release_thread.is_alive()
    continue_read.set()
    thread.join(timeout=5)
    release_thread.join(timeout=5)

    assert not thread.is_alive()
    assert not release_thread.is_alive()
    assert outcomes == ["allowed"]
    assert releases[0]["released"] is True


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


def test_transient_durable_heartbeat_failure_retries_before_process_fence(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    clock.advance(10)
    real_heartbeat = database.heartbeat_runtime_mutation_lease
    calls = 0

    def transient_failure(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_heartbeat(**kwargs)

    monkeypatch.setattr(
        database,
        "heartbeat_runtime_mutation_lease",
        transient_failure,
    )

    result = gate.heartbeat()

    assert result["heartbeat"] is True
    assert calls == 2
    assert gate.status().allowed is True


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


def test_worker_delegation_authenticates_complete_parent_identity(
    isolated_gate_database,
):
    """The child handoff contains the exact parent binding and lease epoch."""

    _path, clock = isolated_gate_database
    gate, binding = _identity_gate(clock)
    assert gate.acquire()["acquired"] is True

    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:identity",
        purpose="coin_prep",
        worker_id="worker-identity",
        ttl_seconds=20,
    )
    environment = handoff.to_environment()

    payload = json.loads(environment[mutation_gate.DELEGATION_IDENTITY_ENV])
    assert payload == mutation_gate.wallet_identity_binding_payload(binding)
    assert environment[mutation_gate.DELEGATION_IDENTITY_DIGEST_ENV] == (
        mutation_gate.wallet_identity_binding_digest(binding)
    )
    assert environment[mutation_gate.DELEGATION_PARENT_EPOCH_ENV]
    assert gate.validate_worker_environment(environment)["allowed"] is True


@pytest.mark.parametrize("field", ["payload", "digest", "epoch"])
def test_worker_delegation_rejects_identity_or_epoch_environment_tamper(
    isolated_gate_database, field
):
    """Full binding and parent epoch are authenticated, not trusted env config."""

    _path, clock = isolated_gate_database
    gate, _binding_value = _identity_gate(clock)
    assert gate.acquire()["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id=f"coin-prep:tamper:{field}",
        purpose="coin_prep",
        worker_id=f"worker-{field}",
        ttl_seconds=20,
    )
    environment = handoff.to_environment()
    if field == "payload":
        payload = json.loads(environment[mutation_gate.DELEGATION_IDENTITY_ENV])
        payload["name"] = "Hostile Wallet"
        environment[mutation_gate.DELEGATION_IDENTITY_ENV] = json.dumps(payload)
    elif field == "digest":
        environment[mutation_gate.DELEGATION_IDENTITY_DIGEST_ENV] = "0" * 64
    else:
        environment[mutation_gate.DELEGATION_PARENT_EPOCH_ENV] = (
            "2026-08-15T11:59:59.000000Z"
        )

    assert gate.validate_worker_environment(environment) == {
        "allowed": False,
        "reason": "worker_delegation_invalid",
    }


def test_installed_worker_binding_is_complete_and_cfg_independent(
    isolated_gate_database, monkeypatch
):
    """The full parent authority freezes at install, before the first effect."""

    import wallet

    _path, clock = isolated_gate_database
    gate, binding = _identity_gate(clock)
    assert gate.acquire()["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:freeze",
        purpose="coin_prep",
        worker_id="worker-freeze",
        ttl_seconds=20,
    )
    environment = handoff.to_environment()
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    mutation_gate.install_worker_authority_environment(
        environment,
        wallet_adapter_authority=wallet.get_wallet_adapter_authority(),
    )

    monkeypatch.setattr(wallet.cfg, "SAGE_FINGERPRINT", "999999999")
    monkeypatch.setattr(
        wallet.cfg, "WALLET_EXPECTED_NAME", "Hostile Wallet", raising=False
    )
    monkeypatch.setattr(
        wallet.cfg, "WALLET_EXPECTED_KEY_KIND", "hostile-kind", raising=False
    )
    monkeypatch.setattr(
        wallet.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 300, raising=False
    )

    authority = mutation_gate.worker_identity_lease_binding()
    assert authority["binding"] == binding
    assert authority["binding_digest"] == (
        mutation_gate.wallet_identity_binding_digest(binding)
    )
    assert wallet._expected_identity_binding() == binding


def test_installed_worker_binding_rechecks_revocation_before_effect(
    isolated_gate_database, monkeypatch
):
    """A frozen child binding never outlives its durable delegation."""

    import wallet

    _path, clock = isolated_gate_database
    gate, _binding_value = _identity_gate(clock)
    assert gate.acquire()["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:revoked-identity",
        purpose="coin_prep",
        worker_id="worker-revoked-identity",
        ttl_seconds=20,
    )
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    mutation_gate.install_worker_authority_environment(
        handoff.to_environment(),
        wallet_adapter_authority=wallet.get_wallet_adapter_authority(),
    )
    assert gate.revoke_worker_delegation(handoff)["revoked"] is True

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        mutation_gate.worker_identity_lease_binding()

    assert error.value.reason_code == "WORKER_DELEGATION_INVALID"


def test_installed_worker_adapter_rejects_self_consistent_facade_global_swap(
    isolated_gate_database, monkeypatch
):
    """A delegated worker cannot redirect effects by replacing facade globals."""

    import wallet

    _path, clock = isolated_gate_database
    gate, _binding_value = _identity_gate(clock)
    assert gate.acquire()["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:adapter-pin",
        purpose="coin_prep",
        worker_id="worker-adapter-pin",
        ttl_seconds=20,
    )
    original = wallet.get_wallet_adapter_authority()
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    mutation_gate.install_worker_authority_environment(
        handoff.to_environment(),
        wallet_adapter_authority=original,
    )
    evil = SimpleNamespace()
    monkeypatch.setattr(wallet, "_wallet_adapter", evil)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", evil)

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        wallet._expected_identity_authority()

    assert error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


def test_installed_worker_adapter_cannot_be_rebound_without_clear(
    isolated_gate_database, monkeypatch
):
    """A live worker authority is immutable until explicit lifecycle cleanup."""

    import wallet

    _path, clock = isolated_gate_database
    gate, _binding_value = _identity_gate(clock)
    assert gate.acquire()["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:adapter-rebind",
        purpose="coin_prep",
        worker_id="worker-adapter-rebind",
        ttl_seconds=20,
    )
    environment = handoff.to_environment()
    original = wallet.get_wallet_adapter_authority()
    evil = SimpleNamespace()
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    mutation_gate.install_worker_authority_environment(
        environment,
        wallet_adapter_authority=original,
    )
    mutation_gate.install_worker_authority_environment(
        environment,
        wallet_adapter_authority=original,
    )

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        mutation_gate.install_worker_authority_environment(
            environment,
            wallet_adapter_authority=evil,
        )

    assert error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"
    assert mutation_gate.worker_wallet_adapter_authority(original, "test") is original


def test_owner_wallet_effect_cannot_cross_runtime_generation_aba(
    isolated_gate_database, monkeypatch
):
    """A stale R1 permit cannot authorize or strand an effect under equal R2."""

    import wallet

    _path, clock = isolated_gate_database
    effects = []
    lifecycle_results = []
    lifecycle_errors = []
    swapped = False

    def identity_snapshot():
        nonlocal swapped
        if not swapped:
            swapped = True

            def replace_runtime():
                try:
                    lifecycle_results.append(
                        mutation_gate.shutdown_runtime(release_owned_lease=True)
                    )
                except BaseException as exc:
                    lifecycle_errors.append(exc)

            lifecycle = threading.Thread(target=replace_runtime)
            lifecycle.start()
            lifecycle.join(timeout=2)
            assert not lifecycle.is_alive()
            assert lifecycle_errors == []
        clock.advance(1)
        return {
            "success": True,
            "backend": "sage",
            "name": binding.name,
            "fingerprint": binding.fingerprint,
            "network_id": binding.network_id,
            "kind": binding.kind,
            "has_secrets": True,
            "observed_at_utc": clock()
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        }

    adapter = SimpleNamespace(
        get_wallet_identity=identity_snapshot,
        create_offer=lambda *args, **kwargs: (
            effects.append("effect") or {"success": True}
        ),
    )
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Delegated Wallet",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=(clock() - timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=15,
    )
    original = mutation_gate.MutationGate(
        run_id="identity-original",
        owner_pid=111,
        owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network=binding.network_id,
        lease_seconds=30,
        clock=clock,
        pid_liveness=lambda _pid, _host: False,
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    assert original.acquire()["acquired"] is True
    mutation_gate._runtime = original
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", adapter)

    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect"]
    assert lifecycle_results == [
        {"released": False, "reason": "active_wallet_mutations"}
    ]
    assert original.active_mutation_count() == 0
    assert mutation_gate.current_runtime() is original

    assert mutation_gate.shutdown_runtime(release_owned_lease=True)["released"] is True
    replacement = mutation_gate.MutationGate(
        run_id="identity-replacement",
        owner_pid=222,
        owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network=binding.network_id,
        lease_seconds=30,
        clock=clock,
        pid_liveness=lambda _pid, _host: False,
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    assert replacement.acquire()["acquired"] is True
    mutation_gate._runtime = replacement
    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect", "effect"]
    assert replacement.active_mutation_count() == 0

    adapter.create_offer = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("private backend failure")
    )
    failed = wallet.create_offer({1: -1})
    assert failed["success"] is False
    assert failed["reason"] == "WALLET_MUTATION_FAILED"
    assert failed["_catalyst_effect_attempted"] is True
    assert "private backend failure" not in str(failed)
    assert replacement.active_mutation_count() == 0
    assert replacement.active_wallet_mutation_count() == 0
    assert mutation_gate.shutdown_runtime(release_owned_lease=True)["released"] is True


def test_owner_wallet_effect_cannot_cross_same_runtime_reacquire_generation(
    isolated_gate_database, monkeypatch
):
    """A fresh lease acquisition on the same runtime invalidates old permits."""

    import wallet

    _path, clock = isolated_gate_database
    effects = []
    lifecycle_results = []
    cycled = False

    def identity_snapshot():
        nonlocal cycled
        if not cycled:
            cycled = True
            lifecycle_results.append(runtime.release_lease())
            lifecycle_results.append(runtime.acquire())
        clock.advance(1)
        return {
            "success": True,
            "backend": "sage",
            "name": binding.name,
            "fingerprint": binding.fingerprint,
            "network_id": binding.network_id,
            "kind": binding.kind,
            "has_secrets": True,
            "observed_at_utc": clock()
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        }

    adapter = SimpleNamespace(
        get_wallet_identity=identity_snapshot,
        create_offer=lambda *args, **kwargs: (
            effects.append("effect") or {"success": True}
        ),
    )
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Reacquired Wallet",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=(clock() - timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=15,
    )
    runtime = mutation_gate.MutationGate(
        run_id="same-runtime-reacquire",
        owner_pid=111,
        owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network=binding.network_id,
        lease_seconds=30,
        clock=clock,
        pid_liveness=lambda _pid, _host: False,
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    assert runtime.acquire()["acquired"] is True
    mutation_gate._runtime = runtime
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", adapter)

    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect"]
    assert lifecycle_results == [
        {"released": False, "reason": "active_wallet_mutations"},
        {"acquired": False, "reason": "active_wallet_mutations"},
    ]
    assert runtime.active_mutation_count() == 0

    assert runtime.release_lease()["released"] is True
    assert runtime.acquire()["acquired"] is True
    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect", "effect"]
    assert runtime.active_mutation_count() == 0


def test_owner_shutdown_cannot_replace_runtime_after_final_wallet_check(
    isolated_gate_database, monkeypatch
):
    """Shutdown refuses after the final check until the exact permit exits."""

    import wallet

    _path, clock = isolated_gate_database
    effects = []
    lifecycle = {}
    adapter = SimpleNamespace(
        get_wallet_identity=lambda: _wallet_snapshot(clock, binding),
        create_offer=lambda *args, **kwargs: (
            effects.append("effect") or {"success": True}
        ),
    )
    runtime, binding = _wallet_owner(clock, adapter, run_id="final-check-owner")
    assert runtime.acquire()["acquired"] is True
    mutation_gate._runtime = runtime
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", adapter)
    original_check = mutation_gate.require_wallet_mutation_permit_authority

    def replace_after_final_check(permit, operation):
        result = original_check(permit, operation)
        if operation == "wallet:create_offer:effect" and "shutdown" not in lifecycle:
            lifecycle["shutdown"] = mutation_gate.shutdown_runtime(
                release_owned_lease=True
            )
            if lifecycle["shutdown"].get("released") is True:
                replacement, _ = _wallet_owner(
                    clock,
                    adapter,
                    run_id="final-check-replacement",
                    pid=222,
                )
                lifecycle["replacement_acquire"] = replacement.acquire()
                mutation_gate._runtime = replacement
                lifecycle["replacement"] = replacement
        return result

    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        replace_after_final_check,
    )

    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect"]
    assert lifecycle["shutdown"] == {
        "released": False,
        "reason": "active_wallet_mutations",
    }
    assert "replacement" not in lifecycle
    assert mutation_gate.current_runtime() is runtime
    assert runtime.active_mutation_count() == 0

    assert mutation_gate.shutdown_runtime(release_owned_lease=True)["released"] is True
    replacement, _ = _wallet_owner(
        clock,
        adapter,
        run_id="final-check-replacement",
        pid=222,
    )
    assert replacement.acquire()["acquired"] is True
    mutation_gate._runtime = replacement
    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect", "effect"]
    assert replacement.active_mutation_count() == 0


def test_owner_release_and_reacquire_refuse_after_final_wallet_check(
    isolated_gate_database, monkeypatch
):
    """The same runtime cannot rotate its lease while a wallet permit is active."""

    import wallet

    _path, clock = isolated_gate_database
    effects = []
    lifecycle = {}
    adapter = SimpleNamespace(
        get_wallet_identity=lambda: _wallet_snapshot(clock, binding),
        create_offer=lambda *args, **kwargs: (
            effects.append("effect") or {"success": True}
        ),
    )
    runtime, binding = _wallet_owner(clock, adapter, run_id="final-check-reacquire")
    assert runtime.acquire()["acquired"] is True
    mutation_gate._runtime = runtime
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", adapter)
    original_check = mutation_gate.require_wallet_mutation_permit_authority

    def reacquire_after_final_check(permit, operation):
        result = original_check(permit, operation)
        if operation == "wallet:create_offer:effect" and "release" not in lifecycle:
            lifecycle["release"] = runtime.release_lease()
            lifecycle["acquire"] = runtime.acquire()
        return result

    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        reacquire_after_final_check,
    )

    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect"]
    assert lifecycle["release"] == {
        "released": False,
        "reason": "active_wallet_mutations",
    }
    assert lifecycle["acquire"] == {
        "acquired": False,
        "reason": "active_wallet_mutations",
    }
    assert runtime.last_acquire_result["acquired"] is True
    assert runtime.status().allowed is True
    assert runtime.active_mutation_count() == 0

    assert runtime.release_lease()["released"] is True
    assert runtime.acquire()["acquired"] is True
    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect", "effect"]
    assert runtime.active_mutation_count() == 0


def test_worker_wallet_effect_cannot_cross_install_generation_aba(
    isolated_gate_database, monkeypatch
):
    """Clear/reinstall cannot make an old worker permit current again."""

    import wallet

    _path, clock = isolated_gate_database
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    parent, binding = _identity_gate(clock)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:worker-generation-aba",
        purpose="coin_prep",
        worker_id="worker-generation-aba",
        ttl_seconds=20,
    )
    environment = handoff.to_environment()
    effects = []
    lifecycle_errors = []
    lifecycle_results = []
    swapped = False

    def identity_snapshot():
        nonlocal swapped
        if not swapped:
            swapped = True

            def replace_worker_authority():
                try:
                    lifecycle_results.append(
                        mutation_gate.clear_worker_authority_environment()
                    )
                    try:
                        mutation_gate.install_worker_authority_environment(
                            environment,
                            wallet_adapter_authority=adapter,
                        )
                    except mutation_gate.MutationBlocked as exc:
                        lifecycle_results.append(exc.reason_code)
                    else:
                        lifecycle_results.append("allowed")
                except BaseException as exc:
                    lifecycle_errors.append(exc)

            lifecycle = threading.Thread(target=replace_worker_authority)
            lifecycle.start()
            lifecycle.join(timeout=2)
            assert not lifecycle.is_alive()
            assert lifecycle_errors == []
        clock.advance(1)
        return {
            "success": True,
            "backend": "sage",
            "name": binding.name,
            "fingerprint": binding.fingerprint,
            "network_id": binding.network_id,
            "kind": binding.kind,
            "has_secrets": True,
            "observed_at_utc": clock()
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        }

    adapter = SimpleNamespace(
        get_wallet_identity=identity_snapshot,
        create_offer=lambda *args, **kwargs: (
            effects.append("effect") or {"success": True}
        ),
    )
    mutation_gate.install_worker_authority_environment(
        environment,
        wallet_adapter_authority=adapter,
    )
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", adapter)

    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect"]
    assert lifecycle_results == [False, "MUTATION_SHUTTING_DOWN"]

    assert mutation_gate.clear_worker_authority_environment() is True
    mutation_gate.install_worker_authority_environment(
        environment,
        wallet_adapter_authority=adapter,
    )
    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect", "effect"]

    adapter.create_offer = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("private worker failure")
    )
    failed = wallet.create_offer({1: -1})
    assert failed["success"] is False
    assert failed["reason"] == "WALLET_MUTATION_FAILED"
    assert failed["_catalyst_effect_attempted"] is True
    assert "private worker failure" not in str(failed)
    assert mutation_gate.clear_worker_authority_environment() is True


def test_worker_clear_and_reinstall_refuse_after_final_wallet_check(
    isolated_gate_database, monkeypatch
):
    """Worker lifecycle cannot replace an install until its exact permit exits."""

    import wallet

    _path, clock = isolated_gate_database
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    parent, binding = _identity_gate(clock)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:worker-final-check",
        purpose="coin_prep",
        worker_id="worker-final-check",
        ttl_seconds=20,
    )
    environment = handoff.to_environment()
    effects = []
    lifecycle = {}
    adapter = SimpleNamespace(
        get_wallet_identity=lambda: _wallet_snapshot(clock, binding),
        create_offer=lambda *args, **kwargs: (
            effects.append("effect") or {"success": True}
        ),
    )
    mutation_gate.install_worker_authority_environment(
        environment,
        wallet_adapter_authority=adapter,
    )
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", adapter)
    original_check = mutation_gate.require_wallet_mutation_permit_authority

    def reinstall_after_final_check(permit, operation):
        result = original_check(permit, operation)
        if operation == "wallet:create_offer:effect" and "clear" not in lifecycle:
            lifecycle["clear"] = mutation_gate.clear_worker_authority_environment()
            try:
                mutation_gate.install_worker_authority_environment(
                    environment,
                    wallet_adapter_authority=adapter,
                )
            except mutation_gate.MutationBlocked as exc:
                lifecycle["install"] = exc.reason_code
            else:
                lifecycle["install"] = "allowed"
        return result

    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        reinstall_after_final_check,
    )

    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect"]
    assert lifecycle == {"clear": False, "install": "MUTATION_SHUTTING_DOWN"}

    assert mutation_gate.clear_worker_authority_environment() is True
    mutation_gate.install_worker_authority_environment(
        environment,
        wallet_adapter_authority=adapter,
    )
    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "_catalyst_effect_attempted": True,
    }
    assert effects == ["effect", "effect"]


def test_wallet_lifecycle_waits_for_every_generation_scoped_permit(
    isolated_gate_database, monkeypatch
):
    """Owner and worker lifecycle remain refused until all permits drain."""

    _path, clock = isolated_gate_database
    monkeypatch.setattr(mutation_gate, "_utc_now", clock)
    adapter = SimpleNamespace(get_wallet_identity=lambda: {})
    runtime, _binding = _wallet_owner(clock, adapter, run_id="permit-drain-owner")
    assert runtime.acquire()["acquired"] is True
    mutation_gate._runtime = runtime
    first = mutation_gate.enter_wallet_mutation("wallet:first")
    second = mutation_gate.enter_wallet_mutation("wallet:second")

    assert mutation_gate.shutdown_runtime(release_owned_lease=True) == {
        "released": False,
        "reason": "active_wallet_mutations",
    }
    assert mutation_gate.exit_wallet_mutation(first) is True
    assert mutation_gate.shutdown_runtime(release_owned_lease=True) == {
        "released": False,
        "reason": "active_wallet_mutations",
    }
    assert mutation_gate.exit_wallet_mutation(second) is True
    assert mutation_gate.shutdown_runtime(release_owned_lease=True)["released"] is True

    parent, _binding = _identity_gate(clock)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:worker-permit-drain",
        purpose="coin_prep",
        worker_id="worker-permit-drain",
        ttl_seconds=20,
    )
    environment = handoff.to_environment()
    mutation_gate.install_worker_authority_environment(
        environment,
        wallet_adapter_authority=adapter,
    )
    first = mutation_gate.enter_wallet_mutation("wallet:first")
    second = mutation_gate.enter_wallet_mutation("wallet:second")

    assert mutation_gate.clear_worker_authority_environment() is False
    assert mutation_gate.exit_wallet_mutation(first) is True
    assert mutation_gate.clear_worker_authority_environment() is False
    assert mutation_gate.exit_wallet_mutation(second) is True
    assert mutation_gate.clear_worker_authority_environment() is True


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
        gate.validate_worker_environment(third_env)["reason"]
        == "worker_delegation_invalid"
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
    assert (
        parent.validate_worker_environment(env)["reason"] == "worker_delegation_invalid"
    )


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

    assert (
        parent.validate_worker_environment(env)["reason"] == "worker_delegation_invalid"
    )


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
    assert "coin_prep.api_log_event" in api_server._READ_ONLY_WRITE_API_ENDPOINTS
    assert "bot.api_bot_stop" in api_server._CONTROL_WRITE_API_ENDPOINTS


def test_coin_prep_telemetry_does_not_enter_wallet_mutation_gate(monkeypatch):
    import api_server

    api_server.app.testing = True
    client = api_server.app.test_client()
    auth = {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}
    received = []

    monkeypatch.setattr(
        api_server.mutation_gate,
        "enter_mutation",
        lambda _operation: (_ for _ in ()).throw(
            AssertionError("telemetry must not sample the wallet mutation gate")
        ),
    )
    monkeypatch.setattr(
        api_server.database,
        "log_event",
        lambda severity, event_type, message: received.append(
            (severity, event_type, message)
        ),
    )

    response = client.post(
        "/api/log",
        json={
            "severity": "info",
            "event_type": "coin_prep",
            "message": "worker telemetry remains available during reconciliation",
        },
        headers=auth,
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert received == [
        (
            "info",
            "coin_prep",
            "worker telemetry remains available during reconciliation",
        )
    ]


def test_splash_inbox_during_coin_prep_does_not_latch_parent_process(
    isolated_gate_database, monkeypatch
):
    """Market-data ingestion must not permanently fence an in-flight prep owner."""
    import api_server

    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    operation_id = "create:pending-prep-effect"
    _append_event(operation_id, blocks=True, suffix="submitted")
    database.trip_runtime_safety_latch(
        reason_code="CREATE_UNKNOWN",
        blocking_operation_ids=[operation_id],
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        tripped_at=clock(),
    )
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(api_server.mutation_gate, "enter_mutation", gate.enter_mutation)
    monkeypatch.setattr(api_server, "cfg", SimpleNamespace(SPLASH_RECEIVE_ENABLED=True))
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_splash_incoming_rate_limited", lambda: False)
    monkeypatch.setattr(api_server, "_splash_incoming_backlog_full", lambda: False)

    response = api_server.app.test_client().post(
        "/api/splash/incoming",
        json={"offer": "offer1testincomingmarketdata"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "new": True}
    assert gate.read_only_status().allowed is False
    assert database.get_splash_incoming_offers(limit=10)
    _append_event(operation_id, blocks=False, suffix="confirmed")
    assert database.resolve_runtime_safety_latch(
        expected_generation=1,
        resolved_operation_ids=[operation_id],
        resolved_at=clock(),
    )["resolved"] is True
    assert gate.status().allowed is True


@pytest.mark.parametrize(
    "reason_code", ["COIN_PREP_EFFECT_UNKNOWN", "COIN_PREP_RECOVERY_REQUIRED"]
)
def test_coin_prep_latch_diagnostics_preserve_the_actionable_reason(
    isolated_gate_database, reason_code
):
    _path, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    database.trip_runtime_safety_latch(
        reason_code=reason_code,
        blocking_operation_ids=["coin-prep:pending"],
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        tripped_at=clock(),
    )
    status = gate.read_only_status().to_dict()
    assert status["allowed"] is False
    assert status["reason_code"] == reason_code
    assert status["blocking_operation_count"] == 1
    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.require_allowed("offer.create")
    assert exc_info.value.reason_code == reason_code


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
    monkeypatch.setattr(
        api_server,
        "_stability_startup_status",
        {
            "allowed": True,
            "reason_code": "",
            "source": "startup_recovery",
            "failed_check": None,
            "checks": [],
            "blocker_counts": {
                "operations": 0,
                "prepared_creations": 0,
                "submitted_cancels": 0,
                "contradictory_history": 0,
                "reservations": 0,
                "publication_claims": 0,
            },
        },
    )
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: ("a" * 64, "mainnet"),
    )
    monkeypatch.setattr(api_server.database, "DB_PATH", __file__)
    monkeypatch.setattr(
        api_server.database,
        "get_stability_diagnostic_counts",
        lambda: {"registry": 0, "lineage": 0, "reserve": 0, "publication": 0},
    )
    monkeypatch.setattr(api_server.mutation_gate, "read_only_status", lambda: denied)
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
    safety = diagnostic.get_json()["safety"]
    assert safety["identity"]["lease_owner"] == "other_run"
    assert "owner_run_id" not in safety["lease"]
    assert "other-run" not in json.dumps(safety, sort_keys=True)
    assert read_only_post.status_code == 200


def test_api_import_does_not_start_cat_resolver_before_lease(tmp_path: Path):
    data_dir = tmp_path / "resolver-import"
    env = os.environ.copy()
    env["CMM_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src" / "catalyst")
    code = r"""
import threading
real_thread = threading.Thread
class GuardedThread(real_thread):
    def __init__(self, *args, **kwargs):
        if kwargs.get("name") == "cat-resolver":
            raise AssertionError("CAT resolver started during import")
        super().__init__(*args, **kwargs)
threading.Thread = GuardedThread
import api_server
"""

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def _clean_startup_recovery_snapshot():
    return {
        "latch": {"state": "resolved", "reason_code": None},
        "lease": {
            "active": 0,
            "owner_pid": None,
            "owner_host": None,
            "heartbeat_at": None,
            "expires_at": None,
        },
        "blockers": [],
        "reservation_issues": [],
        "publication_issues": [],
        "blocker_counts": {
            "operations": 0,
            "prepared_creations": 0,
            "submitted_cancels": 0,
            "contradictory_history": 0,
            "reservations": 0,
            "publication_claims": 0,
        },
        "source_timestamps": {
            "operations": None,
            "reservations": None,
            "publication_claims": None,
        },
        "authority_digest": "clean-startup-authority",
    }


def _configured_startup_identity_proof(monkeypatch, api_server, *, fingerprint):
    bound_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Startup Test Wallet",
        fingerprint=fingerprint,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=bound_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        maximum_age_seconds=15,
    )
    monkeypatch.setattr(
        api_server,
        "_configured_wallet_identity_binding",
        lambda _network: binding,
    )
    return binding


def test_generic_runtime_initialization_never_starts_cat_resolver(monkeypatch):
    import api_server

    starts = []

    class Runtime:
        def register_stop_handler(self, _handler):
            return None

        def status(self):
            return mutation_gate.GateStatus(
                allowed=True,
                reason_code="",
                source="lease",
                lease_active=True,
                owner_is_this_run=True,
            )

    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: (
            mutation_gate.wallet_fingerprint_hash(123456789),
            "mainnet",
        ),
    )
    _configured_startup_identity_proof(
        monkeypatch,
        api_server,
        fingerprint=123456789,
    )
    monkeypatch.setattr(
        api_server.database,
        "check_db_integrity",
        lambda: {"ok": True, "result": "ok", "errors": []},
    )
    monkeypatch.setattr(
        api_server.database,
        "get_stability_startup_recovery_snapshot",
        _clean_startup_recovery_snapshot,
    )
    monkeypatch.setattr(
        api_server.mutation_gate, "initialize", lambda **_kwargs: Runtime()
    )
    monkeypatch.setattr(
        api_server,
        "_start_background_cat_resolver",
        lambda: starts.append("resolver"),
        raising=False,
    )

    read_only = api_server.initialize_mutation_runtime(
        start_heartbeat=False, acquire_lease=False
    )
    owner = api_server.initialize_mutation_runtime(
        start_heartbeat=False, acquire_lease=True
    )

    assert read_only["allowed"] is True
    assert owner["allowed"] is True
    assert [
        check["source"]
        for check in owner["checks"]
        if check["name"] in {"wallet_identity_freshness", "authority_revalidation"}
    ] == ["configured_binding", "configured_binding"]
    assert starts == []

    api_server._start_owned_runtime_services(owner)

    assert starts == ["resolver"]


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
        register_stop_handler=lambda handler: captured.setdefault("handler", handler),
        status=lambda: mutation_gate.GateStatus(
            allowed=True,
            reason_code="",
            source="lease",
            lease_active=True,
            owner_is_this_run=True,
        ),
    )

    def fake_initialize(**kwargs):
        captured.setdefault("calls", []).append(dict(kwargs))
        captured.update(kwargs)
        return fake_gate

    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "736588221")
    monkeypatch.setattr(api_server.cfg, "WALLET_FINGERPRINT", "")
    monkeypatch.setattr(api_server.mutation_gate, "initialize", fake_initialize)
    _configured_startup_identity_proof(
        monkeypatch,
        api_server,
        fingerprint=736588221,
    )
    monkeypatch.setattr(
        api_server.database,
        "check_db_integrity",
        lambda: {"ok": True, "result": "ok", "errors": []},
    )
    monkeypatch.setattr(
        api_server.database,
        "get_stability_startup_recovery_snapshot",
        _clean_startup_recovery_snapshot,
    )

    result = api_server.initialize_mutation_runtime(start_heartbeat=False)

    expected_hash = hashlib.sha256(b"fingerprint:736588221").hexdigest()
    assert captured["wallet_fingerprint_hash"] == expected_hash
    assert captured["network"] == "mainnet"
    assert captured["start_heartbeat"] is False
    assert [call["acquire_lease"] for call in captured["calls"]] == [False, True]
    assert [
        check["source"]
        for check in result["checks"]
        if check["name"] in {"wallet_identity_freshness", "authority_revalidation"}
    ] == ["configured_binding", "configured_binding"]
    assert result["allowed"] is True
    assert result["reason_code"] == ""


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


def test_every_existing_public_appbridge_callable_has_auditable_access_classification():
    import app_bridge

    public = {
        name
        for name, value in vars(app_bridge.AppBridge).items()
        if not name.startswith("_") and callable(value)
    }
    classified = (
        app_bridge._APP_BRIDGE_MUTATION_METHODS
        | app_bridge._APP_BRIDGE_READ_ONLY_METHODS
        | app_bridge._APP_BRIDGE_CONTROL_METHODS
    )

    assert public == classified
    assert not (
        app_bridge._APP_BRIDGE_MUTATION_METHODS
        & app_bridge._APP_BRIDGE_READ_ONLY_METHODS
    )
    assert all(
        app_bridge._APP_BRIDGE_ACCESS_BY_FUNCTION[vars(app_bridge.AppBridge)[name]]
        in {"mutation", "read_only", "control"}
        for name in public
    )


def test_desktop_coin_prep_passes_guarded_permit_to_real_route(
    isolated_gate_database, monkeypatch,
):
    """Desktop prep must reach wallet preflight, not lose its permit in Flask g."""
    import api_server
    import app_bridge
    from blueprints import coin_prep

    _, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(api_server, "wallet_setup_bootstrap_allows", lambda _op: False)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_coin_prep_proc", None)
    monkeypatch.setattr(api_server, "_coin_prep_thread", None)
    monkeypatch.setattr(api_server, "_coin_prep_state", {"running": False})
    # Stop at the external wallet boundary: no wallet calls, resets or worker.
    monkeypatch.setattr(
        coin_prep, "_wallet_open_offer_snapshot_before_prep",
        lambda: {"complete": False, "open_offer_count": 0, "open_trade_ids": []},
    )

    result = app_bridge.AppBridge().trigger_coin_prep()

    assert result["error"] == "coin_prep_wallet_offer_check_unavailable"
    assert result["reason"] == "WALLET_OFFER_BOOK_UNAVAILABLE"
    assert api_server._coin_prep_state["running"] is False
    # Early return must release both admission and exclusive fencing.
    next_permit = gate.enter_mutation("test:after-desktop-preflight")
    assert gate.acquire_exclusive_mutation(
        next_permit, "test:after-desktop-preflight", timeout_seconds=0,
    ) is True
    assert gate.exit_mutation(next_permit) is True


@pytest.mark.parametrize("payload, expected", [
    (None, {}),
    ({"coin_multiplier": 1.5, "reset_pnl": False,
      "reset_offer_history": True, "reset_counters": True},
     {"coin_multiplier": 1.5, "reset_pnl": False,
      "reset_offer_history": True, "reset_counters": True}),
    ({"full_reset": True, "reset_offer_history": False},
     {"full_reset": True, "reset_offer_history": False}),
])
def test_desktop_coin_prep_forwards_selected_options(
    isolated_gate_database, monkeypatch, payload, expected,
):
    """Native prep must deliver the same JSON contract as browser HTTP prep."""
    from flask import jsonify, request
    import api_server
    import app_bridge

    _, clock = isolated_gate_database
    gate = _gate(clock)
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(api_server, "wallet_setup_bootstrap_allows", lambda _op: False)
    # Observe the bridge's outbound JSON at the handler boundary, without
    # actually deleting histories or launching a financial operation.
    monkeypatch.setattr(
        api_server, "api_coin_prep_trigger",
        lambda: jsonify({"success": True, "received": request.get_json()}),
    )

    result = app_bridge.AppBridge().trigger_coin_prep(payload)

    assert result == {"success": True, "received": expected}


def test_future_unclassified_appbridge_callable_defaults_to_mutation_guard(
    monkeypatch,
):
    import app_bridge

    writes = []

    def future_write(_self, hostile_payload=None):
        writes.append(hostile_payload)
        return {"success": True}

    monkeypatch.setattr(
        app_bridge.AppBridge, "future_write", future_write, raising=False
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    bridge = app_bridge.AppBridge()
    bridge._api = SimpleNamespace(
        _ensure_mutation_runtime=lambda: None,
        mutation_gate=mutation_gate,
    )

    result = bridge.future_write({"write": True})

    assert result == {
        "success": False,
        "error": "mutation_gate_blocked",
        "reason": "LEASE_OWNED_BY_OTHER",
        "operation": "app_bridge:future_write",
    }
    assert writes == []


def test_future_mutation_marker_without_guard_cannot_bypass_default_deny(
    monkeypatch,
):
    import app_bridge

    writes = []

    def future_write(_self):
        writes.append("wrote")
        return {"success": True}

    future_write._bridge_access = "mutation"
    monkeypatch.setattr(
        app_bridge.AppBridge, "future_marked_write", future_write, raising=False
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    bridge = app_bridge.AppBridge()
    bridge._api = SimpleNamespace(
        _ensure_mutation_runtime=lambda: None,
        mutation_gate=mutation_gate,
    )

    result = bridge.future_marked_write()

    assert result["success"] is False
    assert result["reason"] == "LEASE_OWNED_BY_OTHER"
    assert writes == []


def test_appbridge_callable_markers_and_dynamic_descriptors_cannot_spoof_trust(
    monkeypatch,
):
    from functools import wraps

    import app_bridge

    writes = []

    def marked_read_only(_self):
        writes.append("class-monkeypatch")
        return {"success": True}

    marked_read_only._bridge_access = "read_only"

    class HostileCallable:
        def __init__(self, label):
            self.label = label

        def __getattr__(self, name):
            if name == "_bridge_access":
                return "read_only"
            raise AttributeError(name)

        def __call__(self):
            writes.append(self.label)
            return {"success": True}

    class HostileDescriptor:
        def __get__(self, _instance, _owner):
            return HostileCallable("descriptor")

    @wraps(app_bridge.AppBridge.get_status)
    def spoofing_wrapper(_self):
        writes.append("wrapper")
        return {"success": True}

    spoofing_wrapper._bridge_access = "read_only"

    monkeypatch.setattr(
        mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    fake_api = SimpleNamespace(
        _ensure_mutation_runtime=lambda: None,
        mutation_gate=mutation_gate,
    )
    results = []

    class_cases = (
        ("future_marked_read", marked_read_only),
        (
            "get_status",
            lambda _self: writes.append("class-override") or {"success": True},
        ),
        ("future_descriptor", HostileDescriptor()),
        ("get_status", spoofing_wrapper),
    )
    for name, value in class_cases:
        with monkeypatch.context() as patcher:
            patcher.setattr(app_bridge.AppBridge, name, value, raising=False)
            bridge = app_bridge.AppBridge()
            bridge._api = fake_api
            results.append(getattr(bridge, name)())

    dynamic = app_bridge.AppBridge()
    dynamic._api = fake_api
    dynamic.future_dynamic = HostileCallable("instance-dynamic")
    results.append(dynamic.future_dynamic())

    assert all(result["reason"] == "LEASE_OWNED_BY_OTHER" for result in results)
    assert writes == []


def test_untrusted_appbridge_descriptor_cannot_execute_before_mutation_permit(
    monkeypatch,
):
    import app_bridge

    writes = []

    class EvilDescriptor:
        def __get__(self, _instance, _owner):
            writes.append("descriptor-get")
            return lambda: writes.append("descriptor-call") or {"success": True}

    monkeypatch.setattr(
        mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    monkeypatch.setattr(
        app_bridge.AppBridge,
        "future_descriptor",
        EvilDescriptor(),
        raising=False,
    )
    bridge = app_bridge.AppBridge()
    app_bridge._APP_BRIDGE_API_SLOT.__set__(
        bridge,
        SimpleNamespace(
            _ensure_mutation_runtime=lambda: None,
            mutation_gate=mutation_gate,
        ),
    )

    call = bridge.future_descriptor

    assert writes == []
    result = call()
    assert result["reason"] == "LEASE_OWNED_BY_OTHER"
    assert writes == []


def test_appbridge_private_api_descriptor_cannot_execute_before_mutation_permit(
    monkeypatch,
):
    import app_bridge

    writes = []

    class PrivateApiDescriptor:
        def __get__(self, instance, _owner):
            writes.append("private-api-get")
            return object.__getattribute__(instance, "__dict__")["_api"]

        def __set__(self, instance, value):
            object.__getattribute__(instance, "__dict__")["_api"] = value

    def future_write(_self):
        writes.append("future-write")
        return {"success": True}

    monkeypatch.setattr(
        mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    monkeypatch.setattr(app_bridge.AppBridge, "_api", PrivateApiDescriptor())
    monkeypatch.setattr(
        app_bridge.AppBridge, "future_write", future_write, raising=False
    )
    bridge = app_bridge.AppBridge()
    app_bridge._APP_BRIDGE_API_SLOT.__set__(
        bridge,
        SimpleNamespace(
            _ensure_mutation_runtime=lambda: None,
            mutation_gate=mutation_gate,
        ),
    )

    call = bridge.future_write

    assert writes == []
    result = call()
    assert result["reason"] == "LEASE_OWNED_BY_OTHER"
    assert writes == []


def test_missing_appbridge_attribute_getattr_runs_only_inside_mutation_permit(
    monkeypatch,
):
    import app_bridge

    writes = []

    def hostile_getattr(_self, name):
        writes.append(f"getattr:{name}")
        return lambda: writes.append("call") or {"success": True}

    monkeypatch.setattr(
        mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )
    monkeypatch.setattr(
        app_bridge.AppBridge, "__getattr__", hostile_getattr, raising=False
    )
    bridge = app_bridge.AppBridge()
    bridge._api = SimpleNamespace(
        _ensure_mutation_runtime=lambda: None,
        mutation_gate=mutation_gate,
    )

    call = bridge.future_missing

    assert writes == []
    result = call()
    assert result["reason"] == "LEASE_OWNED_BY_OTHER"
    assert writes == []


def test_appbridge_subclass_cannot_replace_enforcement_hook():
    import app_bridge

    with pytest.raises(TypeError, match="__getattribute__"):

        class BypassBridge(app_bridge.AppBridge):
            def __getattribute__(self, name):
                return lambda: {"success": True, "name": name}


def test_appbridge_hostile_metaclass_cannot_install_late_enforcement_bypass():
    import app_bridge

    writes = []

    class LateBypassMeta(type):
        def __new__(metaclass, name, bases, namespace):
            subclass = super().__new__(metaclass, name, bases, namespace)

            def bypass(_self, attribute):
                if attribute == "future_write":
                    return lambda: writes.append("write") or {"success": True}
                return object.__getattribute__(_self, attribute)

            type.__setattr__(subclass, "__getattribute__", bypass)
            return subclass

    with pytest.raises(TypeError, match="final"):

        class BypassBridge(app_bridge.AppBridge, metaclass=LateBypassMeta):
            pass

    assert writes == []


def test_exact_registered_read_only_appbridge_method_preserves_read_only_ux(
    monkeypatch,
):
    import app_bridge

    monkeypatch.setattr(
        mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            AssertionError(f"read-only method was mutation guarded: {operation}")
        ),
    )

    result = app_bridge.AppBridge().get_app_info()

    assert result["name"] == "CATalyst"
    assert result["mode"] == "desktop"


def test_parent_launcher_uses_environment_only_and_revokes_on_request(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    parent, _binding_value = _identity_gate(clock)
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


def test_coin_prep_log_delivery_uses_selected_owner_port_not_preferred_listener(
    monkeypatch,
):
    import coin_prep_worker

    selected_port = 6128
    preferred_url = "http://127.0.0.1:5000/api/log"
    selected_url = f"http://127.0.0.1:{selected_port}/api/log"
    deliveries = []

    class Session:
        def post(self, url, **kwargs):
            deliveries.append((url, kwargs))

    fake_requests = SimpleNamespace(
        post=lambda url, **kwargs: deliveries.append((url, kwargs)),
        Session=Session,
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setenv("CATALYST_FLASK_PORT", str(selected_port))
    monkeypatch.setattr(coin_prep_worker, "_LOCAL_API_TOKEN", "selected-token")

    mirror = coin_prep_worker.ApiMirrorStream(
        SimpleNamespace(write=lambda _data: None, flush=lambda: None),
        event_type="coin_prep_stdout",
        severity="info",
    )
    mirror._emit_line("mirror log")

    queued_worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    queued_worker._api_log_queue = coin_prep_worker.Queue()
    queued_worker._api_log_queue.put({"message": "queued log"})
    queued_worker._api_log_queue.put(None)
    queued_worker._api_log_loop()

    assert [url for url, _kwargs in deliveries] == [selected_url, selected_url]
    assert all(url != preferred_url for url, _kwargs in deliveries)
    assert all(
        kwargs["headers"] == {"X-Bot-Local-Token": "selected-token"}
        for _url, kwargs in deliveries
    )


def test_tray_fallback_uses_selected_owner_port_and_token_before_callbacks_are_wired(
    monkeypatch,
):
    import tray_manager

    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    monkeypatch.setenv("CATALYST_FLASK_PORT", "6133")
    monkeypatch.setenv("BOT_LOCAL_WRITE_TOKEN", "tray-selected-token")
    monkeypatch.setattr(
        tray_manager.urllib.request,
        "urlopen",
        lambda request, timeout: (
            requests.append((request.full_url, timeout, dict(request.header_items())))
            or Response()
        ),
    )

    tray = object.__new__(tray_manager.TrayManager)
    tray._call_flask_api("/api/bot/start")

    assert requests == [
        (
            "http://127.0.0.1:6133/api/bot/start",
            5,
            {
                "Content-type": "application/json",
                "X-bot-local-token": "tray-selected-token",
            },
        )
    ]


def test_tray_fallback_missing_or_hostile_token_fails_closed_without_logging(
    monkeypatch, capsys
):
    import tray_manager

    requests = []
    monkeypatch.delenv("BOT_LOCAL_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(
        tray_manager.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: requests.append("sent"),
    )
    tray = object.__new__(tray_manager.TrayManager)

    tray._call_flask_api("/api/bot/start")

    class HostileEnvironment:
        def get(self, _name, _default=None):
            raise RuntimeError("hostile-secret-value")

    monkeypatch.setattr(
        tray_manager,
        "os",
        SimpleNamespace(environ=HostileEnvironment()),
    )
    tray._call_flask_api("/api/bot/stop")

    captured = capsys.readouterr()
    assert requests == []
    assert "hostile-secret-value" not in captured.out
    assert "hostile-secret-value" not in captured.err


@pytest.mark.parametrize("port_value", [None, "0", "not-a-port"])
def test_tray_fallback_missing_or_invalid_selected_port_fails_closed(
    monkeypatch,
    port_value,
):
    import tray_manager

    requests = []
    monkeypatch.setenv("BOT_LOCAL_WRITE_TOKEN", "tray-selected-token")
    if port_value is None:
        monkeypatch.delenv("CATALYST_FLASK_PORT", raising=False)
    else:
        monkeypatch.setenv("CATALYST_FLASK_PORT", port_value)
    monkeypatch.setattr(
        tray_manager.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: requests.append("sent"),
    )

    object.__new__(tray_manager.TrayManager)._call_flask_api("/api/bot/start")

    assert requests == []


@pytest.mark.parametrize("control_error", [KeyboardInterrupt, SystemExit])
def test_tray_fallback_hostile_port_environment_fails_closed_without_logging(
    monkeypatch,
    capsys,
    control_error,
):
    import tray_manager

    requests = []
    escaped = []

    class HostilePortEnvironment:
        def get(self, name, _default=None):
            if name == "BOT_LOCAL_WRITE_TOKEN":
                return "tray-selected-token"
            raise control_error("hostile-port-secret")

    monkeypatch.setattr(
        tray_manager,
        "os",
        SimpleNamespace(environ=HostilePortEnvironment()),
    )
    monkeypatch.setattr(
        tray_manager.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: requests.append("sent"),
    )
    try:
        object.__new__(tray_manager.TrayManager)._call_flask_api("/api/bot/stop")
    except BaseException as exc:
        escaped.append(type(exc))

    captured = capsys.readouterr()
    assert escaped == []
    assert requests == []
    assert "hostile-port-secret" not in captured.out
    assert "hostile-port-secret" not in captured.err


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
    parent, _binding_value = _identity_gate(clock)
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
    assert all(key not in os.environ for key in mutation_gate._DELEGATION_ENV_NAMES)
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


def test_observed_lease_expiry_is_an_irreversible_runtime_fence(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="expiry-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)

    clock.advance(31)
    assert gate.status().reason_code == "LEASE_EXPIRED"
    clock.advance(-31)

    assert gate.status().reason_code == "LEASE_EXPIRED"
    assert gate.release_resolved(0, [])["reason"] == "terminal_process_fence"
    promoted = mutation_gate.initialize(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        run_id=gate.run_id,
        owner_pid=gate.owner_pid,
        owner_host=gate.owner_host,
        lease_seconds=gate.lease_seconds,
        start_heartbeat=False,
        acquire_lease=True,
    )
    assert promoted is gate
    assert promoted.status().reason_code == "LEASE_EXPIRED"


def test_observed_lease_version_loss_is_an_irreversible_runtime_fence(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="lost-owner")
    acquired = gate.acquire()
    assert acquired["acquired"] is True
    heartbeat_at = clock() + timedelta(seconds=1)
    external = database.heartbeat_runtime_mutation_lease(
        owner_run_id=gate.run_id,
        expected_lease_version=acquired["lease"]["lease_version"],
        heartbeat_at=heartbeat_at,
        lease_expires_at=heartbeat_at + timedelta(seconds=30),
    )
    assert external["heartbeat"] is True

    assert gate.status().reason_code == "LEASE_LOST"
    gate._lease_version = external["lease"]["lease_version"]

    assert gate.status().reason_code == "LEASE_LOST"
    assert gate.release_resolved(0, [])["reason"] == "terminal_process_fence"


@pytest.mark.parametrize("change", ["deactivated", "owner_replaced"])
def test_observed_lease_owner_loss_is_an_irreversible_runtime_fence(
    isolated_gate_database, change
):
    path, clock = isolated_gate_database
    gate = _gate(clock, run_id="owner-loss-runtime")
    acquired = gate.acquire()
    assert acquired["acquired"] is True
    original = database.get_runtime_mutation_lease()
    with sqlite3.connect(path) as conn:
        if change == "deactivated":
            conn.execute(
                "UPDATE runtime_mutation_lease SET active=0, lease_version=lease_version+1 "
                "WHERE singleton_id=1"
            )
        else:
            conn.execute(
                "UPDATE runtime_mutation_lease SET owner_run_id='replacement-owner', "
                "owner_pid=222, lease_version=lease_version+1 WHERE singleton_id=1"
            )
        conn.commit()

    assert gate.status().reason_code == "LEASE_LOST"

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            UPDATE runtime_mutation_lease
            SET lease_version=?,active=?,owner_run_id=?,owner_pid=?
            WHERE singleton_id=1
            """,
            (
                original["lease_version"],
                original["active"],
                original["owner_run_id"],
                original["owner_pid"],
            ),
        )
        conn.commit()

    assert gate.status().reason_code == "LEASE_LOST"


def test_stop_callback_runs_without_holding_the_gate_lock(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="callback-lock-owner")
    acquired = gate.acquire()
    assert acquired["acquired"] is True
    callback_read_completed = []

    def stop_handler(_reason):
        reader = threading.Thread(target=gate.active_mutation_count)
        reader.start()
        reader.join(timeout=0.5)
        callback_read_completed.append(not reader.is_alive())

    gate.register_stop_handler(stop_handler)
    heartbeat_at = clock() + timedelta(seconds=1)
    external = database.heartbeat_runtime_mutation_lease(
        owner_run_id=gate.run_id,
        expected_lease_version=acquired["lease"]["lease_version"],
        heartbeat_at=heartbeat_at,
        lease_expires_at=heartbeat_at + timedelta(seconds=30),
    )
    assert external["heartbeat"] is True

    assert gate.status().reason_code == "LEASE_LOST"
    assert callback_read_completed == [True]


def test_status_snapshot_and_heartbeat_version_update_are_serialized(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="status-heartbeat-owner")
    assert gate.acquire()["acquired"] is True
    original_snapshot = database.get_mutation_authorization_snapshot
    snapshot_captured = threading.Event()
    release_snapshot = threading.Event()
    heartbeat_done = threading.Event()
    status_result = {}
    heartbeat_result = {}

    def delayed_snapshot(**kwargs):
        snapshot = original_snapshot(**kwargs)
        if threading.current_thread().name == "status-race":
            snapshot_captured.set()
            assert release_snapshot.wait(timeout=3)
        return snapshot

    monkeypatch.setattr(
        database, "get_mutation_authorization_snapshot", delayed_snapshot
    )

    status_thread = threading.Thread(
        target=lambda: status_result.setdefault("status", gate.status()),
        name="status-race",
    )

    def run_heartbeat():
        heartbeat_result.update(gate.heartbeat())
        heartbeat_done.set()

    status_thread.start()
    assert snapshot_captured.wait(timeout=3)
    clock.advance(1)
    heartbeat_thread = threading.Thread(target=run_heartbeat, name="heartbeat-race")
    heartbeat_thread.start()
    heartbeat_done.wait(timeout=1)
    release_snapshot.set()
    status_thread.join(timeout=3)
    heartbeat_thread.join(timeout=3)

    assert not status_thread.is_alive()
    assert not heartbeat_thread.is_alive()
    assert status_result["status"].allowed is True
    assert heartbeat_result["heartbeat"] is True
    assert gate.status().allowed is True


def test_failed_post_insert_delegation_check_revokes_the_exact_child_scope(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="delegation-cleanup-owner")
    acquired = gate.acquire()
    assert acquired["acquired"] is True
    inserted = {}
    original_issue = database.issue_worker_delegation

    def insert_then_lose_lease(**kwargs):
        row = original_issue(**kwargs)
        inserted.update(row)
        heartbeat_at = clock() + timedelta(seconds=1)
        external = database.heartbeat_runtime_mutation_lease(
            owner_run_id=gate.run_id,
            expected_lease_version=acquired["lease"]["lease_version"],
            heartbeat_at=heartbeat_at,
            lease_expires_at=heartbeat_at + timedelta(seconds=30),
        )
        assert external["heartbeat"] is True
        return row

    monkeypatch.setattr(database, "issue_worker_delegation", insert_then_lose_lease)

    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.issue_worker_delegation(
            operation_id="coin-prep:post-insert-loss",
            purpose="coin_prep",
            worker_id="worker-post-insert-loss",
            ttl_seconds=30,
        )

    assert exc_info.value.reason_code == "LEASE_LOST"
    assert inserted
    assert (
        database.get_valid_worker_delegation(
            delegation_id=inserted["delegation_id"],
            delegation_token_hash=inserted["delegation_token_hash"],
            parent_run_id=inserted["parent_run_id"],
            operation_id=inserted["operation_id"],
            purpose=inserted["purpose"],
            wallet_fingerprint_hash=inserted["wallet_fingerprint_hash"],
            network=inserted["network"],
            now=clock(),
        )
        is None
    )


def test_frozen_clock_release_and_reacquire_cannot_revive_old_delegation(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="frozen-epoch-owner")
    assert gate.acquire()["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:frozen-epoch",
        purpose="coin_prep",
        worker_id="worker-frozen-epoch",
        ttl_seconds=30,
    )
    environment = handoff.to_environment()
    assert gate.validate_worker_environment(environment)["allowed"] is True

    assert gate.release_lease()["released"] is True
    assert gate.acquire()["acquired"] is True

    assert gate.validate_worker_environment(environment)["allowed"] is False
    assert _active_delegation_row(handoff, environment, clock()) is None


def test_lease_release_revokes_children_atomically_and_cas_failure_does_not(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="atomic-release-owner")
    acquired = gate.acquire()
    assert acquired["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:atomic-release",
        purpose="coin_prep",
        worker_id="worker-atomic-release",
        ttl_seconds=30,
    )
    environment = handoff.to_environment()
    version = acquired["lease"]["lease_version"]

    stale = database.release_runtime_mutation_lease(
        owner_run_id=gate.run_id,
        expected_lease_version=version + 1,
        released_at=clock(),
    )
    assert stale["released"] is False
    assert _active_delegation_row(handoff, environment, clock()) is not None

    released = database.release_runtime_mutation_lease(
        owner_run_id=gate.run_id,
        expected_lease_version=version,
        released_at=clock(),
    )
    assert released["released"] is True
    assert _active_delegation_row(handoff, environment, clock()) is None


def test_lease_release_rolls_back_when_child_revocation_fails(
    isolated_gate_database,
):
    path, clock = isolated_gate_database
    gate = _gate(clock, run_id="release-rollback-owner")
    acquired = gate.acquire()
    assert acquired["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:release-rollback",
        purpose="coin_prep",
        worker_id="worker-release-rollback",
        ttl_seconds=30,
    )
    environment = handoff.to_environment()
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TRIGGER fail_parent_delegation_revoke
            BEFORE UPDATE OF state ON runtime_worker_delegations
            WHEN NEW.state='revoked'
            BEGIN
                SELECT RAISE(ABORT, 'forced delegation revoke failure');
            END
            """
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(sqlite3.IntegrityError, match="forced delegation revoke"):
        database.release_runtime_mutation_lease(
            owner_run_id=gate.run_id,
            expected_lease_version=acquired["lease"]["lease_version"],
            released_at=clock(),
        )

    lease = database.get_runtime_mutation_lease()
    assert lease["active"] == 1
    assert lease["lease_version"] == acquired["lease"]["lease_version"]
    assert _active_delegation_row(handoff, environment, clock()) is not None


def test_expired_dead_owner_takeover_revokes_crashed_parent_delegations(
    isolated_gate_database,
):
    _path, clock = isolated_gate_database
    parent = _gate(clock, run_id="crashed-parent", pid=111)
    assert parent.acquire()["acquired"] is True
    handoff = parent.issue_worker_delegation(
        operation_id="coin-prep:crashed-parent",
        purpose="coin_prep",
        worker_id="worker-crashed-parent",
        ttl_seconds=120,
    )
    environment = handoff.to_environment()
    clock.advance(31)
    takeover = _gate(clock, run_id="takeover-owner", pid=222)

    assert takeover.acquire()["acquired"] is True
    assert parent.validate_worker_environment(environment)["allowed"] is False
    assert _active_delegation_row(handoff, environment, clock()) is None


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


def test_desktop_cleanup_uses_central_quiescence_and_never_releases_directly(
    monkeypatch,
):
    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    calls = []
    monkeypatch.setattr(
        api_server,
        "release_mutation_runtime",
        lambda: (_ for _ in ()).throw(
            AssertionError("desktop cleanup cannot release ownership directly")
        ),
    )
    monkeypatch.setattr(
        api_server,
        "quiesce_and_release_mutation_runtime",
        lambda: calls.append("central") or {"released": False},
        raising=False,
    )
    monkeypatch.setattr(database, "log_event", lambda *_args, **_kwargs: None)

    desktop_app._cleanup()

    assert calls == ["central"]


def test_gui_shutdown_stops_bot_before_cancelling_wallet_offers(monkeypatch):
    import api_server
    from blueprints import bot as bot_blueprint

    order = []
    captured = {}

    class DeferredThread:
        def __init__(self, target, **_kwargs):
            captured["target"] = target

        def start(self):
            return None

    class OfferManager:
        def cancel_all(self):
            order.append("cancel")
            return {}

        def sync_from_wallet(self):
            return [], [], {}

    fake_bot = SimpleNamespace(
        offer_manager=OfferManager(),
        coin_manager=SimpleNamespace(_prep_running=False),
        runtime_monitor=SimpleNamespace(stop=lambda: None),
        splash_node=SimpleNamespace(is_running=lambda: False),
        stop=lambda wait=True: order.append("stop"),
    )
    monkeypatch.setattr(api_server, "bot", fake_bot)
    monkeypatch.setattr(bot_blueprint.threading, "Thread", DeferredThread)
    monkeypatch.setattr(bot_blueprint.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(bot_blueprint, "backup_database", lambda: None)
    monkeypatch.setattr(api_server, "_coin_prep_proc", None)
    monkeypatch.setattr(
        api_server.mutation_gate, "enter_mutation", lambda _operation: "permit"
    )
    monkeypatch.setattr(api_server.mutation_gate, "exit_mutation", lambda _permit: True)
    monkeypatch.setattr(
        api_server,
        "quiesce_and_release_mutation_runtime",
        lambda **_kwargs: order.append("central") or {"released": True},
    )
    monkeypatch.setattr(bot_blueprint.os, "_exit", lambda _code: None)
    monkeypatch.setattr(database, "get_open_offers", lambda: [])
    monkeypatch.setattr(database, "update_offer_status", lambda *_args: None)
    monkeypatch.setattr(
        database,
        "get_connection",
        lambda: SimpleNamespace(execute=lambda *_args: None, commit=lambda: None),
    )

    with api_server.app.test_request_context(
        "/api/shutdown", method="POST", json={"cancel_offers": True}
    ):
        response = bot_blueprint.api_shutdown()
    assert response.get_json()["success"] is True
    captured["target"]()

    assert order.index("stop") < order.index("cancel") < order.index("central")


def test_gui_shutdown_wallet_absence_never_terminalizes_submitted_cancel(monkeypatch):
    import api_server
    from blueprints import bot as bot_blueprint

    captured = {}
    status_updates = []

    class DeferredThread:
        def __init__(self, target, **_kwargs):
            captured["target"] = target

        def start(self):
            return None

    class OfferManager:
        def cancel_all(self):
            return {"shutdown-trade": {"success": True}}

        def sync_from_wallet(self):
            return [], [], {}

    fake_bot = SimpleNamespace(
        offer_manager=OfferManager(),
        coin_manager=SimpleNamespace(_prep_running=False),
        runtime_monitor=SimpleNamespace(stop=lambda: None),
        splash_node=SimpleNamespace(is_running=lambda: False),
        stop=lambda wait=True: None,
    )
    monkeypatch.setattr(api_server, "bot", fake_bot)
    monkeypatch.setattr(bot_blueprint.threading, "Thread", DeferredThread)
    monkeypatch.setattr(bot_blueprint.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(bot_blueprint, "backup_database", lambda: None)
    monkeypatch.setattr(api_server, "_coin_prep_proc", None)
    monkeypatch.setattr(
        api_server.mutation_gate, "enter_mutation", lambda _operation: "permit"
    )
    monkeypatch.setattr(api_server.mutation_gate, "exit_mutation", lambda _permit: True)
    monkeypatch.setattr(
        api_server,
        "quiesce_and_release_mutation_runtime",
        lambda **_kwargs: {"released": True},
    )
    monkeypatch.setattr(bot_blueprint.os, "_exit", lambda _code: None)
    monkeypatch.setattr(
        database,
        "update_offer_status",
        lambda trade_id, status: status_updates.append((trade_id, status)),
    )
    monkeypatch.setattr(
        database,
        "get_connection",
        lambda: SimpleNamespace(execute=lambda *_args: None, commit=lambda: None),
    )

    with api_server.app.test_request_context(
        "/api/shutdown", method="POST", json={"cancel_offers": True}
    ):
        response = bot_blueprint.api_shutdown()
    assert response.get_json()["success"] is True

    captured["target"]()

    assert status_updates == []


def test_gui_shutdown_cancel_failure_still_releases_permit_and_quiesces(monkeypatch):
    import api_server
    from blueprints import bot as bot_blueprint

    captured = {}
    order = []

    class DeferredThread:
        def __init__(self, target, **_kwargs):
            captured["target"] = target

        def start(self):
            return None

    class OfferManager:
        def cancel_all(self):
            raise RuntimeError("cancel unavailable")

    fake_bot = SimpleNamespace(
        offer_manager=OfferManager(),
        coin_manager=SimpleNamespace(_prep_running=False),
        runtime_monitor=SimpleNamespace(stop=lambda: None),
        splash_node=SimpleNamespace(is_running=lambda: False),
        stop=lambda wait=True: None,
    )
    monkeypatch.setattr(api_server, "bot", fake_bot)
    monkeypatch.setattr(bot_blueprint.threading, "Thread", DeferredThread)
    monkeypatch.setattr(bot_blueprint.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(bot_blueprint, "backup_database", lambda: None)
    monkeypatch.setattr(api_server, "_coin_prep_proc", None)
    monkeypatch.setattr(
        api_server.mutation_gate, "enter_mutation", lambda _operation: "permit"
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "exit_mutation",
        lambda permit: order.append(("exit", permit)) or True,
    )
    monkeypatch.setattr(
        api_server,
        "quiesce_and_release_mutation_runtime",
        lambda **_kwargs: order.append(("quiesce", None)) or {"released": True},
    )
    monkeypatch.setattr(bot_blueprint.os, "_exit", lambda _code: None)
    monkeypatch.setattr(
        database,
        "get_connection",
        lambda: SimpleNamespace(execute=lambda *_args: None, commit=lambda: None),
    )

    with api_server.app.test_request_context(
        "/api/shutdown", method="POST", json={"cancel_offers": True}
    ):
        response = bot_blueprint.api_shutdown()
    assert response.get_json()["success"] is True

    captured["target"]()

    assert order == [("exit", "permit"), ("quiesce", None)]


def test_inflight_mutation_quiescence_blocks_new_work_and_lease_release(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="inflight-shutdown-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )
    permit = gate.enter_mutation("test:inflight")

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=None,
        wait_seconds=0,
    )

    assert result["released"] is False
    assert result["reason"] == "mutations_in_flight"
    assert database.get_runtime_mutation_lease()["active"] == 1
    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.enter_mutation("test:new-after-quiesce")
    assert exc_info.value.reason_code == "MUTATION_SHUTTING_DOWN"
    assert gate.exit_mutation(permit) is True


def test_exclusive_mutation_fences_new_work_until_owner_exits(
    isolated_gate_database,
):
    """Coin-shape work can drain peers without globally quiescing shutdown."""

    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="exclusive-coin-prep-owner")
    assert gate.acquire()["acquired"] is True
    owner = gate.enter_mutation("api:coin-prep")
    peer = gate.enter_mutation("api:offer-create")
    acquired = threading.Event()
    errors = []

    def acquire_exclusive():
        try:
            gate.acquire_exclusive_mutation(
                owner,
                "api:coin-prep",
                timeout_seconds=1,
            )
            acquired.set()
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=acquire_exclusive)
    worker.start()
    deadline = time.monotonic() + 1
    while gate._exclusive_mutation_permit != owner and time.monotonic() < deadline:
        time.sleep(0.005)
    assert gate._exclusive_mutation_permit == owner
    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.enter_mutation("api:offer-cancel")
    assert exc_info.value.reason_code == "MUTATION_SHUTTING_DOWN"
    assert gate.exit_mutation(peer) is True
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert errors == []
    assert acquired.is_set()
    assert gate.exit_mutation(owner) is True
    after = gate.enter_mutation("api:after-coin-prep")
    assert gate.exit_mutation(after) is True


def test_exclusive_mutation_timeout_reopens_gate(isolated_gate_database):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="exclusive-timeout-owner")
    assert gate.acquire()["acquired"] is True
    owner = gate.enter_mutation("api:coin-prep")
    peer = gate.enter_mutation("api:offer-create")

    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        gate.acquire_exclusive_mutation(
            owner,
            "api:coin-prep",
            timeout_seconds=0,
        )

    assert exc_info.value.reason_code == "MUTATION_EXCLUSION_TIMEOUT"
    after = gate.enter_mutation("api:after-timeout")
    assert gate.exit_mutation(after) is True
    assert gate.exit_mutation(peer) is True
    assert gate.exit_mutation(owner) is True


def test_shutdown_stop_exception_or_live_thread_keeps_lease_until_expiry(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="failed-stop-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )

    class LiveThread:
        name = "stuck-bot-thread"

        def is_alive(self):
            return True

    class Bot:
        _running = True
        _thread = LiveThread()
        coin_manager = None
        runtime_monitor = None

        def stop(self, wait=True):
            raise RuntimeError("stop failed")

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=Bot(),
        wait_seconds=0,
    )

    assert result["released"] is False
    assert result["reason"] == "mutation_producers_not_stopped"
    assert "stuck-bot-thread" in result["live_threads"]
    assert database.get_runtime_mutation_lease()["active"] == 1
    heartbeat = getattr(gate, "_heartbeat_thread", None)
    assert heartbeat is None or not heartbeat.is_alive()


def test_shutdown_unknown_thread_liveness_fails_closed_and_stops_heartbeat(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="unknown-thread-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )

    class UnknownThread:
        name = "unknown-bot-thread"

        def is_alive(self):
            raise RuntimeError("liveness unavailable")

    bot = SimpleNamespace(
        _thread=UnknownThread(),
        coin_manager=None,
        runtime_monitor=None,
        amm_monitor=None,
        stop=lambda wait=True: True,
    )

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=bot,
        wait_seconds=0,
    )

    assert result["released"] is False
    assert result["reason"] == "mutation_producers_not_stopped"
    assert result["unverified_threads"] == ["unknown-bot-thread"]
    assert database.get_runtime_mutation_lease()["active"] == 1
    heartbeat = getattr(gate, "_heartbeat_thread", None)
    assert heartbeat is None or not heartbeat.is_alive()


def test_shutdown_tracks_every_background_wallet_mutation_producer(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="background-producer-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )

    class LiveThread:
        def __init__(self, name):
            self.name = name

        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

    cancel_all = LiveThread("cancel-all-bg")
    boost = LiveThread("boost-activate-bg")
    ladder = LiveThread("create-buy")
    graceful = LiveThread("graceful-cancel")
    monkeypatch.setattr(api_server, "_cancel_all_thread", cancel_all, raising=False)
    monkeypatch.setattr(api_server, "_boost_activation_thread", boost, raising=False)
    bot = SimpleNamespace(
        coin_manager=None,
        runtime_monitor=None,
        amm_monitor=None,
        _ladder_threads=[ladder],
        _graceful_cancel_thread=graceful,
        stop=lambda wait=True: True,
    )

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=bot,
        wait_seconds=0,
    )

    assert result["released"] is False
    assert result["reason"] == "mutation_producers_not_stopped"
    assert set(result["live_threads"]) == {
        "boost-activate-bg",
        "cancel-all-bg",
        "create-buy",
        "graceful-cancel",
    }
    assert database.get_runtime_mutation_lease()["active"] == 1


def test_shutdown_tracks_sniper_and_shape_fix_workers(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="nested-producer-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )

    class LiveThread:
        def __init__(self, name):
            self.name = name

        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

    sniper = LiveThread("probe-sell")
    shape_fix = LiveThread("shape_fix_buy")
    aborts = []
    orchestrator = SimpleNamespace(
        _threads={"buy": shape_fix},
        abort_flow=lambda side: aborts.append(side) or side == "buy",
    )
    bot = SimpleNamespace(
        coin_manager=None,
        runtime_monitor=None,
        amm_monitor=None,
        shape_fix_orchestrator=orchestrator,
        _sniper_threads=[sniper],
        stop=lambda wait=True: True,
    )

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=bot,
        wait_seconds=0,
    )

    assert result["released"] is False
    assert set(result["live_threads"]) == {"probe-sell", "shape_fix_buy"}
    assert aborts == ["buy", "sell"]
    assert database.get_runtime_mutation_lease()["active"] == 1


def test_topup_stop_timeout_preserves_busy_state_and_thread_identity(monkeypatch):
    import coin_manager

    class LiveThread:
        name = "coin-topup"

        @staticmethod
        def is_alive():
            return True

        @staticmethod
        def join(timeout=None):
            return None

    manager = coin_manager.CoinManager.__new__(coin_manager.CoinManager)
    manager._lock = threading.RLock()
    manager._topup_running = True
    manager._topup_stop_requested = False
    manager._topup_thread = LiveThread()
    monkeypatch.setattr(coin_manager, "log_event", lambda *_args, **_kwargs: None)

    stopped = manager.stop_topup(wait_secs=0)

    assert stopped is False
    assert manager._topup_running is True
    assert manager._topup_stop_requested is True
    assert manager._topup_thread is not None
    assert manager._topup_thread.is_alive() is True


def test_topup_worker_finalizer_alone_clears_thread_and_busy_state(monkeypatch):
    import coin_manager

    manager = coin_manager.CoinManager.__new__(coin_manager.CoinManager)
    manager._lock = threading.RLock()
    manager._topup_running = True
    manager._topup_stop_requested = True
    manager._topup_thread = threading.current_thread()
    manager.update_coin_counts = lambda: None
    manager.log_inventory = lambda: None
    monkeypatch.setattr(coin_manager, "log_event", lambda *_args, **_kwargs: None)

    manager._topup_worker(0, 0)

    assert manager._topup_running is False
    assert manager._topup_stop_requested is False
    assert manager._topup_thread is None


def test_shutdown_snapshots_shape_fix_threads_under_owner_lock():
    import api_server

    class TrackingLock:
        held = False

        def __enter__(self):
            self.held = True

        def __exit__(self, exc_type, exc, traceback):
            self.held = False

    lock = TrackingLock()

    class GuardedThreads(dict):
        def values(self):
            assert lock.held, "worker inventory must hold the owner's lock"
            return super().values()

    worker = SimpleNamespace(is_alive=lambda: True)
    orchestrator = SimpleNamespace(
        _lock=lock,
        _threads=GuardedThreads(buy=worker),
    )
    bot = SimpleNamespace(
        coin_manager=None,
        runtime_monitor=None,
        amm_monitor=None,
        shape_fix_orchestrator=orchestrator,
    )

    assert worker in api_server._shutdown_thread_refs(bot)


def test_process_exit_hook_cannot_release_after_quiescence_proof_failed(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="failed-exit-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )

    class LiveThread:
        name = "still-mutating"

        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

    bot = SimpleNamespace(
        _thread=LiveThread(),
        coin_manager=None,
        runtime_monitor=None,
        amm_monitor=None,
        stop=lambda wait=True: True,
    )
    failed = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=bot,
        wait_seconds=0,
    )
    assert failed["released"] is False

    exit_result = mutation_gate.shutdown_runtime()

    assert exit_result["released"] is False
    assert exit_result["reason"] == "lease_retained"
    assert database.get_runtime_mutation_lease()["active"] == 1


def test_async_route_worker_cannot_start_after_shutdown_quiesces(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="route-shutdown-race-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )
    parent_permit = gate.enter_mutation("api:test:parent")
    shutdown_result = {}
    shutdown_done = threading.Event()

    def shutdown():
        shutdown_result.update(
            api_server.quiesce_and_release_mutation_runtime(
                bot_instance=None,
                wait_seconds=1,
            )
        )
        shutdown_done.set()

    shutdown_thread = threading.Thread(target=shutdown)
    shutdown_thread.start()
    deadline = time.monotonic() + 1
    while not gate._quiescing and time.monotonic() < deadline:
        time.sleep(0.005)
    assert gate._quiescing is True
    wallet_calls = []

    with pytest.raises(mutation_gate.MutationBlocked) as exc_info:
        api_server.start_mutation_thread(
            operation="api:test:async",
            target=lambda: wallet_calls.append("wallet"),
            name="test-async-wallet",
        )
    assert exc_info.value.reason_code == "MUTATION_SHUTTING_DOWN"
    assert wallet_calls == []

    assert gate.exit_mutation(parent_permit) is True
    shutdown_thread.join(timeout=2)
    assert shutdown_done.is_set()
    assert shutdown_result["released"] is True


def test_shutdown_recaptures_thread_refs_after_request_permits_drain(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="late-publication-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )
    parent_permit = gate.enter_mutation("api:coin-prep:request")
    result = {}

    def shutdown():
        result.update(
            api_server.quiesce_and_release_mutation_runtime(
                bot_instance=None,
                wait_seconds=1,
            )
        )

    shutdown_thread = threading.Thread(target=shutdown)
    shutdown_thread.start()
    deadline = time.monotonic() + 1
    while not gate._quiescing and time.monotonic() < deadline:
        time.sleep(0.005)
    assert gate._quiescing is True

    class LateWorker:
        name = "late-coin-prep"

        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

    monkeypatch.setattr(api_server, "_coin_prep_thread", LateWorker())
    assert gate.exit_mutation(parent_permit) is True
    shutdown_thread.join(timeout=2)

    assert not shutdown_thread.is_alive()
    assert result["released"] is False
    assert result["reason"] == "mutation_producers_not_stopped"
    assert result["live_threads"] == ["late-coin-prep"]
    assert database.get_runtime_mutation_lease()["active"] == 1


def test_shutdown_retains_lease_for_topup_published_during_bot_stop(
    isolated_gate_database, monkeypatch
):
    import api_server
    import coin_manager

    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="late-topup-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )
    monkeypatch.setattr(coin_manager, "log_event", lambda *_args, **_kwargs: None)

    class LiveTopup:
        name = "late-coin-topup"

        @staticmethod
        def is_alive():
            return True

        @staticmethod
        def join(timeout=None):
            return None

    manager = coin_manager.CoinManager.__new__(coin_manager.CoinManager)
    manager._lock = threading.RLock()
    manager._prep_process = None
    manager._prep_delegation = None
    manager._prep_running = False
    manager._topup_running = False
    manager._topup_stop_requested = False
    manager._topup_thread = None
    late_topup = LiveTopup()

    class Bot:
        coin_manager = manager
        runtime_monitor = None
        amm_monitor = None
        shape_fix_orchestrator = None

        @staticmethod
        def stop(wait=True):
            manager._topup_running = True
            manager._topup_thread = late_topup
            assert manager.stop_topup(wait_secs=0) is False
            return False

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=Bot(), wait_seconds=0
    )

    assert result["released"] is False
    assert result["reason"] == "mutation_producers_not_stopped"
    assert result["live_threads"] == ["late-coin-topup"]
    assert manager._topup_running is True
    assert manager._topup_stop_requested is True
    assert manager._topup_thread is late_topup
    assert database.get_runtime_mutation_lease()["active"] == 1


def test_shutdown_recaptures_child_handles_after_request_permits_drain(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="late-child-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )
    parent_permit = gate.enter_mutation("api:coin-prep:late-child-request")
    result = {}

    def shutdown():
        result.update(
            api_server.quiesce_and_release_mutation_runtime(
                bot_instance=None,
                wait_seconds=1,
            )
        )

    shutdown_thread = threading.Thread(target=shutdown)
    shutdown_thread.start()
    deadline = time.monotonic() + 1
    while not gate._quiescing and time.monotonic() < deadline:
        time.sleep(0.005)
    assert gate._quiescing is True

    class LateChild:
        pid = 9200

        def poll(self):
            return None

        def terminate(self):
            raise RuntimeError("still starting")

        def kill(self):
            raise RuntimeError("still starting")

    late_child = LateChild()
    monkeypatch.setattr(api_server, "_coin_prep_proc", late_child)
    assert gate.exit_mutation(parent_permit) is True
    shutdown_thread.join(timeout=2)

    assert not shutdown_thread.is_alive()
    assert result["released"] is False
    assert result["reason"] == "mutation_producers_not_stopped"
    assert result["live_child_pids"] == [9200]
    assert api_server._coin_prep_proc is late_child
    assert database.get_runtime_mutation_lease()["active"] == 1


def test_shutdown_unverified_child_without_pid_retains_lease(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="unknown-child-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )

    class UnknownChild:
        pid = None

        def poll(self):
            return None

        def terminate(self):
            raise RuntimeError("terminate unavailable")

        def kill(self):
            raise RuntimeError("kill unavailable")

    child = UnknownChild()
    manager = SimpleNamespace(
        _prep_process=child,
        _prep_delegation=None,
        _prep_running=False,
        _topup_running=False,
    )
    bot = SimpleNamespace(
        coin_manager=manager,
        runtime_monitor=None,
        amm_monitor=None,
        stop=lambda wait=True: True,
    )

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=bot,
        wait_seconds=0,
    )

    assert result["released"] is False
    assert result["reason"] == "mutation_producers_not_stopped"
    assert result["live_child_pids"] == []
    assert manager._prep_process is child
    assert database.get_runtime_mutation_lease()["active"] == 1


def test_shutdown_child_kill_failure_retains_handles_and_lease(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="failed-child-stop-owner")
    assert gate.acquire()["acquired"] is True
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )

    class UnkillableProcess:
        pid = 9001

        def poll(self):
            return None

        def terminate(self):
            raise RuntimeError("terminate failed")

        def kill(self):
            raise RuntimeError("kill failed")

    process = UnkillableProcess()
    delegation = object()
    manager = SimpleNamespace(
        _prep_process=process,
        _prep_delegation=delegation,
        _prep_running=True,
        _topup_thread=None,
    )
    bot = SimpleNamespace(
        _running=False,
        coin_manager=manager,
        runtime_monitor=None,
        stop=lambda wait=True: False,
    )
    monkeypatch.setattr(api_server, "_coin_prep_proc", None)

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=bot,
        wait_seconds=0,
    )

    assert result["released"] is False
    assert result["reason"] == "mutation_producers_not_stopped"
    assert result["live_child_pids"] == [9001]
    assert manager._prep_process is process
    assert manager._prep_delegation is delegation
    assert database.get_runtime_mutation_lease()["active"] == 1


def test_safe_shutdown_stops_both_children_revokes_scope_then_releases(
    isolated_gate_database, monkeypatch
):
    _path, clock = isolated_gate_database
    gate = _gate(clock, run_id="safe-shutdown-owner")
    assert gate.acquire()["acquired"] is True
    handoff = gate.issue_worker_delegation(
        operation_id="coin-prep:safe-shutdown",
        purpose="coin_prep",
        worker_id="worker-safe-shutdown",
        ttl_seconds=30,
    )
    environment = handoff.to_environment()
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    import api_server

    monkeypatch.setattr(api_server, "_mutation_runtime", gate)
    monkeypatch.setattr(
        api_server, "_mutation_runtime_db_path", os.path.abspath(database.DB_PATH)
    )

    class Process:
        def __init__(self, pid):
            self.pid = pid
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.alive = False

    class BotThread:
        name = "bot-main"

        def __init__(self):
            self.alive = True

        def is_alive(self):
            return self.alive

    manager_process = Process(9101)
    blueprint_process = Process(9102)
    bot_thread = BotThread()
    manager = SimpleNamespace(
        _prep_process=manager_process,
        _prep_delegation=handoff,
        _prep_running=True,
        _topup_thread=None,
    )

    class Bot:
        _running = True
        _thread = bot_thread
        coin_manager = manager
        runtime_monitor = None

        def stop(self, wait=True):
            self._running = False
            bot_thread.alive = False
            return True

    monkeypatch.setattr(api_server, "_coin_prep_proc", blueprint_process)

    result = api_server.quiesce_and_release_mutation_runtime(
        bot_instance=Bot(),
        wait_seconds=0,
    )

    assert result["released"] is True
    assert database.get_runtime_mutation_lease()["active"] == 0
    assert manager_process.poll() == 0
    assert blueprint_process.poll() == 0
    assert manager._prep_process is None
    assert manager._prep_delegation is None
    assert api_server._coin_prep_proc is None
    assert _active_delegation_row(handoff, environment, clock()) is None


def test_second_desktop_process_enters_alternate_port_diagnostics(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    started = []
    reservation = SimpleNamespace(port=desktop_app.FLASK_PORT + 7)
    monkeypatch.setattr(desktop_app.sys, "platform", "win32")
    monkeypatch.setattr(desktop_app, "_acquire_instance_lock", lambda: False)
    monkeypatch.setattr(
        desktop_app, "_open_existing_instance_in_browser", lambda _port: None
    )
    monkeypatch.setattr(desktop_app, "_focus_existing_catalyst_window", lambda: False)
    monkeypatch.setattr(
        desktop_app,
        "_reserve_diagnostics_server_port",
        lambda: reservation,
        raising=False,
    )
    monkeypatch.setattr(
        desktop_app,
        "run_read_only_diagnostics_desktop_mode",
        lambda supplied: started.append(supplied),
        raising=False,
    )

    assert desktop_app.main(["--show-console"]) == 0
    assert started == [reservation]


def test_mutation_stop_handler_defers_only_exact_cancel_settlement(monkeypatch):
    import api_server

    stop_calls = []
    deferred_reasons = []

    class Bot:
        @staticmethod
        def is_running():
            return True

        @staticmethod
        def can_defer_mutation_safety_stop(reason_code):
            deferred_reasons.append(reason_code)
            return True

        @staticmethod
        def stop(wait=True):
            stop_calls.append(wait)

    monkeypatch.setattr(api_server, "bot", Bot())
    monkeypatch.setattr(api_server, "slog", lambda *_args, **_kwargs: None)

    api_server._mutation_stop_handler("UNRESOLVED_OPERATIONS")
    assert deferred_reasons == ["UNRESOLVED_OPERATIONS"]
    assert stop_calls == []

    api_server._mutation_stop_handler("WALLET_IDENTITY_MISMATCH")
    assert deferred_reasons == ["UNRESOLVED_OPERATIONS"]
    assert stop_calls == [False]


def test_second_desktop_opens_exact_diagnostics_port_not_unrelated_preferred(
    monkeypatch,
):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    reservation = SimpleNamespace(port=6130)
    opened = []
    served = []

    monkeypatch.setattr(desktop_app, "FLASK_PORT", 5000)
    monkeypatch.setattr(desktop_app, "_authorize_desktop_startup", lambda: False)
    monkeypatch.setattr(desktop_app, "_release_instance_lock", lambda: False)
    monkeypatch.setattr(
        desktop_app, "_focus_existing_catalyst_window", lambda: False, raising=False
    )
    monkeypatch.setattr(
        desktop_app, "_reserve_diagnostics_server_port", lambda: reservation
    )
    monkeypatch.setattr(
        desktop_app,
        "run_read_only_diagnostics_mode",
        lambda supplied, *, ready_callback: (
            served.append(supplied),
            ready_callback(),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "webbrowser",
        SimpleNamespace(open=lambda url: opened.append(url)),
    )

    assert desktop_app.main(["--flask", "--show-console"]) == 0
    assert served == [reservation]
    assert opened == ["http://127.0.0.1:6130/"]


def test_second_desktop_opens_diagnostics_only_after_socket_handoff(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    reservation = SimpleNamespace(port=6131)
    events = []

    def serve_after_handoff(supplied, *, ready_callback=None):
        assert supplied is reservation
        events.append("handoff")
        assert ready_callback is not None
        ready_callback()
        events.append("serve")

    monkeypatch.setattr(desktop_app, "_authorize_desktop_startup", lambda: False)
    monkeypatch.setattr(desktop_app, "_release_instance_lock", lambda: False)
    monkeypatch.setattr(
        desktop_app, "_focus_existing_catalyst_window", lambda: False, raising=False
    )
    monkeypatch.setattr(
        desktop_app, "_reserve_diagnostics_server_port", lambda: reservation
    )
    monkeypatch.setattr(
        desktop_app, "run_read_only_diagnostics_mode", serve_after_handoff
    )
    monkeypatch.setitem(
        sys.modules,
        "webbrowser",
        SimpleNamespace(open=lambda url: events.append(("open", url))),
    )

    assert desktop_app.main(["--flask", "--show-console"]) == 0
    assert events == [
        "handoff",
        ("open", "http://127.0.0.1:6131/"),
        "serve",
    ]


def test_second_desktop_restores_existing_window_without_opening_diagnostics(
    monkeypatch,
):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []

    monkeypatch.setattr(desktop_app, "_authorize_desktop_startup", lambda: False)
    monkeypatch.setattr(
        desktop_app,
        "_release_instance_lock",
        lambda: events.append("release") or True,
    )
    monkeypatch.setattr(
        desktop_app,
        "_focus_existing_catalyst_window",
        lambda: events.append("focus") or True,
        raising=False,
    )
    monkeypatch.setattr(
        desktop_app,
        "_reserve_diagnostics_server_port",
        lambda: (_ for _ in ()).throw(
            AssertionError("focused duplicate must not start diagnostics")
        ),
    )

    assert desktop_app.main(["--show-console"]) == 0
    assert events == ["release", "focus"]


def test_windows_existing_catalyst_window_is_restored_and_foregrounded(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    class User32:
        def __init__(self):
            self.shown = []
            self.raised = []
            self.foregrounded = []

        @staticmethod
        def EnumWindows(callback, _context):
            callback(101, 0)
            callback(202, 0)
            return True

        @staticmethod
        def GetWindowThreadProcessId(handle, owner_pid):
            owner_pid._obj.value = 4567 if handle == 101 else 9876
            return 1

        @staticmethod
        def GetWindowTextLengthW(handle):
            return len("CATalyst" if handle == 101 else "CATalyst Setup")

        @staticmethod
        def GetWindowTextW(handle, buffer, _length):
            buffer.value = "CATalyst" if handle == 101 else "CATalyst Setup"
            return len(buffer.value)

        def ShowWindow(self, handle, command):
            self.shown.append((handle, command))
            return True

        def BringWindowToTop(self, handle):
            self.raised.append(handle)
            return True

        def SetForegroundWindow(self, handle):
            self.foregrounded.append(handle)
            return True

        @staticmethod
        def GetForegroundWindow():
            return 101

    user32 = User32()
    monkeypatch.setattr(desktop_app.os, "getpid", lambda: 9999)

    assert desktop_app._focus_catalyst_window_with_user32(
        user32, lambda callback: callback, owner_pid=4567
    )
    assert user32.shown == [(101, 9)]
    assert user32.raised == [101]
    assert user32.foregrounded == [101]


def test_windows_existing_window_handoff_fails_when_foreground_is_denied(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    class User32:
        @staticmethod
        def EnumWindows(callback, _context):
            callback(101, 0)
            return True

        @staticmethod
        def GetWindowThreadProcessId(_handle, owner_pid):
            owner_pid._obj.value = 4567
            return 1

        @staticmethod
        def GetWindowTextLengthW(_handle):
            return len("CATalyst")

        @staticmethod
        def GetWindowTextW(_handle, buffer, _length):
            buffer.value = "CATalyst"
            return len(buffer.value)

        @staticmethod
        def ShowWindow(_handle, _command):
            return True

        @staticmethod
        def BringWindowToTop(_handle):
            return False

        @staticmethod
        def SetForegroundWindow(_handle):
            return False

        @staticmethod
        def GetForegroundWindow():
            return 303

    monkeypatch.setattr(desktop_app.os, "getpid", lambda: 9999)

    assert not desktop_app._focus_catalyst_window_with_user32(
        User32(), lambda callback: callback, owner_pid=4567
    )


def test_windows_window_handoff_rejects_same_title_from_wrong_process(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    class User32:
        shown = []

        @staticmethod
        def EnumWindows(callback, _context):
            callback(101, 0)
            return True

        @staticmethod
        def GetWindowThreadProcessId(_handle, owner_pid):
            owner_pid._obj.value = 9876
            return 1

        @staticmethod
        def GetWindowTextLengthW(_handle):
            return len("CATalyst")

        @staticmethod
        def GetWindowTextW(_handle, buffer, _length):
            buffer.value = "CATalyst"
            return len(buffer.value)

        def ShowWindow(self, handle, command):
            self.shown.append((handle, command))
            return True

    user32 = User32()

    assert not desktop_app._focus_catalyst_window_with_user32(
        user32, lambda callback: callback, owner_pid=4567
    )
    assert user32.shown == []


def test_windows_owner_handoff_retries_while_native_window_is_starting(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    attempts = []
    outcomes = iter((False, False, True))
    clock = iter((0.0, 0.1, 0.2))

    monkeypatch.setattr(desktop_app.sys, "platform", "win32")
    monkeypatch.setattr(desktop_app.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        desktop_app.time, "sleep", lambda seconds: attempts.append(seconds)
    )

    focused = desktop_app._focus_existing_catalyst_window(
        owner_pid=4567,
        timeout_seconds=2,
        focus_attempt=lambda pid: attempts.append(pid) or next(outcomes),
    )
    assert focused
    assert attempts == [4567, 0.1, 4567, 0.1, 4567]


def test_windows_handoff_owner_pid_comes_from_current_profile_lock(
    tmp_path, monkeypatch
):
    import read_only_diagnostics

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    lock_path = tmp_path / ".instance.lock"
    lock_path.write_bytes(b"\x00pid=4567 started=123\n")

    monkeypatch.setattr(desktop_app.sys, "platform", "win32")
    monkeypatch.setattr(desktop_app, "_instance_lock_path", lambda: str(lock_path))
    monkeypatch.setattr(
        read_only_diagnostics,
        "read_safety_status",
        lambda: {"lease": {"active": False, "owner_pid": None}},
    )
    monkeypatch.setattr(desktop_app.os, "getpid", lambda: 9999)

    assert desktop_app._current_profile_owner_pid() == 4567


def test_desktop_safety_fallback_opens_branded_native_window(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    reservation = SimpleNamespace(port=6133)
    events = []

    def serve(supplied, *, ready_callback=None, lifetime_seconds=300):
        events.append(("serve", supplied, lifetime_seconds))
        ready_callback()

    fake_webview = SimpleNamespace(
        create_window=lambda **kwargs: events.append(("window", kwargs)),
        start=lambda **kwargs: events.append(("start", kwargs)),
    )
    monkeypatch.setattr(desktop_app, "run_read_only_diagnostics_mode", serve)
    monkeypatch.setattr(desktop_app, "_detect_gui_backend", lambda: "edgechromium")
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    desktop_app.run_read_only_diagnostics_desktop_mode(reservation)

    window = next(item[1] for item in events if item[0] == "window")
    assert window["title"] == "CATalyst Startup Safety"
    assert window["url"] == "http://127.0.0.1:6133/"
    assert ("serve", reservation, None) in events
    assert ("start", {"gui": "edgechromium", "http_server": False}) in events


def test_failed_desktop_start_routes_to_native_diagnostics(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    reservation = SimpleNamespace(port=6134)
    events = []

    monkeypatch.setattr(desktop_app.sys, "platform", "win32")
    monkeypatch.setattr(desktop_app, "_authorize_desktop_startup", lambda: False)
    monkeypatch.setattr(desktop_app, "_release_instance_lock", lambda: False)
    monkeypatch.setattr(desktop_app, "_focus_existing_catalyst_window", lambda: False)
    monkeypatch.setattr(
        desktop_app, "_reserve_diagnostics_server_port", lambda: reservation
    )
    monkeypatch.setattr(
        desktop_app,
        "run_read_only_diagnostics_desktop_mode",
        lambda supplied: events.append(supplied),
        raising=False,
    )
    monkeypatch.setattr(
        desktop_app,
        "run_read_only_diagnostics_mode",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("desktop fallback must not open a browser")
        ),
    )

    assert desktop_app.main(["--show-console"]) == 0
    assert events == [reservation]


def test_non_windows_desktop_safety_fallback_uses_branded_browser(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    reservation = SimpleNamespace(port=6135)
    events = []

    monkeypatch.setattr(desktop_app.sys, "platform", "linux")
    monkeypatch.setattr(desktop_app, "_authorize_desktop_startup", lambda: False)
    monkeypatch.setattr(desktop_app, "_release_instance_lock", lambda: True)
    monkeypatch.setattr(desktop_app, "_focus_existing_catalyst_window", lambda: False)
    monkeypatch.setattr(
        desktop_app, "_reserve_diagnostics_server_port", lambda: reservation
    )
    monkeypatch.setattr(
        desktop_app,
        "run_read_only_diagnostics_mode",
        lambda supplied, *, ready_callback: (
            events.append(("serve", supplied)),
            ready_callback(),
        ),
    )
    monkeypatch.setattr(
        desktop_app,
        "_open_existing_instance_in_browser",
        lambda port: events.append(("browser", port)),
    )
    monkeypatch.setattr(
        desktop_app,
        "run_read_only_diagnostics_desktop_mode",
        lambda _reservation: (_ for _ in ()).throw(
            AssertionError("headless non-Windows fallback must not require pywebview")
        ),
    )

    assert desktop_app.main(["--show-console"]) == 0
    assert events == [("serve", reservation), ("browser", 6135)]


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("1", 1),
        ("65535", 65535),
        ("0", 5000),
        ("65536", 5000),
        ("not-a-port", 5000),
    ],
)
def test_desktop_port_normalization_matches_standalone(
    monkeypatch, configured, expected
):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    assert desktop_app._normalize_flask_port(configured) == expected


def test_desktop_diagnostics_reservation_excludes_owner_preferred_port(monkeypatch):
    import read_only_diagnostics

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    calls = []
    reservation = SimpleNamespace(port=65534)
    monkeypatch.setattr(desktop_app, "FLASK_PORT", 65535)
    monkeypatch.setattr(
        read_only_diagnostics,
        "reserve_loopback_port",
        lambda preferred, **kwargs: calls.append((preferred, kwargs)) or reservation,
    )

    assert desktop_app._reserve_diagnostics_server_port() is reservation
    assert calls == [(65535, {"include_preferred": False})]


def test_loopback_port_reservation_scans_down_from_65535_and_closes_losers(
    monkeypatch,
):
    import read_only_diagnostics

    attempts = []
    sockets = []

    class FakeSocket:
        def __init__(self):
            self.bound_port = None
            self.closed = False
            sockets.append(self)

        def setsockopt(self, *_args):
            return None

        def set_inheritable(self, _value):
            return None

        def bind(self, address):
            self.bound_port = int(address[1])
            attempts.append(self.bound_port)
            if self.bound_port != 65534:
                raise OSError("occupied")

        def listen(self, _backlog):
            return None

        def getsockname(self):
            return ("127.0.0.1", self.bound_port)

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        read_only_diagnostics.socket,
        "socket",
        lambda *_args, **_kwargs: FakeSocket(),
    )

    reservation = read_only_diagnostics.reserve_loopback_port(
        65535, include_preferred=True, search_limit=1
    )
    try:
        assert reservation.port == 65534
        assert attempts == [65535, 65534]
        assert sockets[0].closed is True
        assert sockets[1].closed is False
    finally:
        reservation.release()

    assert sockets[1].closed is True


def test_real_loopback_reservation_prevents_concurrent_port_steal():
    import read_only_diagnostics

    unrelated = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        unrelated.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    unrelated.bind(("127.0.0.1", 0))
    unrelated.listen(1)
    preferred = int(unrelated.getsockname()[1])
    reservation = None
    thief = None
    successor = None
    try:
        reservation = read_only_diagnostics.reserve_loopback_port(preferred)
        assert reservation.port != preferred

        thief = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            thief.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        with pytest.raises(OSError):
            thief.bind(("127.0.0.1", reservation.port))

        claimed_port = reservation.port
        assert reservation.release() is True
        successor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            successor.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        successor.bind(("127.0.0.1", claimed_port))
    finally:
        if reservation is not None:
            reservation.release()
        for handle in (thief, successor, unrelated):
            if handle is not None:
                handle.close()


@pytest.mark.parametrize("control_error", [KeyboardInterrupt, SystemExit])
def test_loopback_reservation_release_closes_before_reraising_control_flow(
    control_error,
):
    import read_only_diagnostics

    real_socket_type = socket.socket

    class InterruptingCloseSocket(real_socket_type):
        close_calls = 0

        def close(self):
            self.close_calls += 1
            raise control_error("close interrupted")

    handle = InterruptingCloseSocket(socket.AF_INET, socket.SOCK_STREAM)
    handle.bind(("127.0.0.1", 0))
    reservation = read_only_diagnostics.LoopbackPortReservation(handle)
    try:
        with pytest.raises(control_error, match="close interrupted"):
            reservation.release()

        assert handle.close_calls == 1
        assert handle.fileno() == -1
        assert reservation.release() is False
    finally:
        real_socket_type.close(handle)


def test_loopback_reservation_release_recovers_from_hostile_close_idempotently():
    import read_only_diagnostics

    real_socket_type = socket.socket

    class HostileCloseSocket(real_socket_type):
        close_calls = 0

        def close(self):
            self.close_calls += 1
            raise RuntimeError("hostile close")

    handle = HostileCloseSocket(socket.AF_INET, socket.SOCK_STREAM)
    handle.bind(("127.0.0.1", 0))
    reservation = read_only_diagnostics.LoopbackPortReservation(handle)
    try:
        assert reservation.release() is True
        assert handle.close_calls == 1
        assert handle.fileno() == -1
        assert reservation.release() is False
    finally:
        real_socket_type.close(handle)


def test_loopback_reservation_release_proves_noop_override_closed():
    import read_only_diagnostics

    real_socket_type = socket.socket

    class NoOpCloseSocket(real_socket_type):
        close_calls = 0

        def close(self):
            self.close_calls += 1

    handle = NoOpCloseSocket(socket.AF_INET, socket.SOCK_STREAM)
    handle.bind(("127.0.0.1", 0))
    port = int(handle.getsockname()[1])
    reservation = read_only_diagnostics.LoopbackPortReservation(handle)
    try:
        assert reservation.release() is True
        assert handle.close_calls == 1
        assert handle.fileno() == -1
        assert reservation.release() is False
        replacement = real_socket_type(socket.AF_INET, socket.SOCK_STREAM)
        try:
            replacement.bind(("127.0.0.1", port))
        finally:
            replacement.close()
    finally:
        real_socket_type.close(handle)


def test_loopback_reservation_failed_close_retains_ownership_for_retry():
    import read_only_diagnostics

    class RetryCloseHandle:
        def __init__(self):
            self.close_calls = 0

        def getsockname(self):
            return ("127.0.0.1", 6133)

        def fileno(self):
            return 42

        def close(self):
            self.close_calls += 1
            if self.close_calls <= 2:
                raise RuntimeError("retry close")

    handle = RetryCloseHandle()
    reservation = read_only_diagnostics.LoopbackPortReservation(handle)

    assert reservation.release() is False
    assert reservation.fileno() == 42
    assert handle.close_calls == 2
    assert reservation.release() is True
    assert handle.close_calls == 3
    assert reservation.release() is False


def test_loopback_reservation_concurrent_release_closes_exactly_once():
    import read_only_diagnostics

    entered = threading.Event()
    proceed = threading.Event()

    class SlowCloseHandle:
        def __init__(self):
            self.close_calls = 0

        def getsockname(self):
            return ("127.0.0.1", 6133)

        def close(self):
            self.close_calls += 1
            entered.set()
            assert proceed.wait(timeout=2)

    handle = SlowCloseHandle()
    reservation = read_only_diagnostics.LoopbackPortReservation(handle)
    results = []
    workers = [
        threading.Thread(target=lambda: results.append(reservation.release()))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    assert entered.wait(timeout=2)
    proceed.set()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()

    assert sorted(results) == [False, True]
    assert handle.close_calls == 1


@pytest.mark.parametrize("control_error", [KeyboardInterrupt, SystemExit])
def test_loopback_reservation_setup_closes_socket_before_reraising_control_flow(
    monkeypatch,
    control_error,
):
    import read_only_diagnostics

    real_socket_type = socket.socket

    class InterruptingSetupSocket(real_socket_type):
        close_calls = 0

        def set_inheritable(self, _value):
            raise control_error("setup interrupted")

        def close(self):
            self.close_calls += 1
            raise RuntimeError("hostile setup close")

    handle = InterruptingSetupSocket(socket.AF_INET, socket.SOCK_STREAM)
    monkeypatch.setattr(
        read_only_diagnostics.socket,
        "socket",
        lambda *_args, **_kwargs: handle,
    )
    try:
        with pytest.raises(control_error, match="setup interrupted"):
            read_only_diagnostics.reserve_loopback_port(5000, search_limit=0)

        assert handle.close_calls == 1
        assert handle.fileno() == -1
    finally:
        real_socket_type.close(handle)


def test_loopback_reservation_setup_proves_noop_override_closed(monkeypatch):
    import read_only_diagnostics

    real_socket_type = socket.socket
    blocker = real_socket_type(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    port = int(blocker.getsockname()[1])

    class NoOpCloseSocket(real_socket_type):
        close_calls = 0

        def close(self):
            self.close_calls += 1

    handle = NoOpCloseSocket(socket.AF_INET, socket.SOCK_STREAM)
    monkeypatch.setattr(
        read_only_diagnostics.socket,
        "socket",
        lambda *_args, **_kwargs: handle,
    )
    try:
        with pytest.raises(RuntimeError, match="no loopback server port"):
            read_only_diagnostics.reserve_loopback_port(port, search_limit=0)

        assert handle.close_calls == 1
        assert handle.fileno() == -1
    finally:
        real_socket_type.close(handle)
        blocker.close()


def test_reserved_port_does_not_report_server_ready_before_handoff():
    import read_only_diagnostics

    reservation = read_only_diagnostics.reserve_loopback_port(5000)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(0.2)
    try:
        with pytest.raises(OSError):
            client.connect(("127.0.0.1", reservation.port))
    finally:
        client.close()
        reservation.release()


def test_desktop_constructor_failure_cannot_publish_false_server_readiness(
    monkeypatch,
):
    import api_server
    import werkzeug.serving

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    constructor_done = threading.Event()
    thread_errors = []
    events = []

    class Reservation:
        port = 6129
        listening = False

        def listen(self):
            self.listening = True
            events.append("listen")

        def fileno(self):
            return 99

        def release(self):
            events.append("release")
            return True

    reservation = Reservation()

    def fail_constructor(*_args, **_kwargs):
        constructor_done.set()
        raise RuntimeError("werkzeug constructor failed")

    real_thread = threading.Thread

    class CapturingThread:
        def __init__(self, *, target, args=(), **_kwargs):
            self._target = target
            self._args = args
            self._thread = None

        def start(self):
            def invoke():
                try:
                    api_server._build_flask_server_on_reservation(self._args[0])
                except BaseException as exc:
                    thread_errors.append(exc)

            self._thread = real_thread(target=invoke, daemon=True)
            self._thread.start()

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace())
    monkeypatch.setattr(desktop_app, "_reserve_owner_server_port", lambda: reservation)
    monkeypatch.setattr(desktop_app, "_start_owned_runtime_services", lambda: None)
    monkeypatch.setattr(
        desktop_app, "threading", SimpleNamespace(Thread=CapturingThread)
    )
    monkeypatch.setattr(
        desktop_app,
        "wait_for_flask",
        lambda timeout: constructor_done.wait(timeout) and reservation.listening,
    )
    monkeypatch.setattr(
        desktop_app,
        "_start_system_tray",
        lambda: (_ for _ in ()).throw(AssertionError("false readiness advanced")),
    )
    monkeypatch.setattr(desktop_app, "_cleanup", lambda: events.append("cleanup"))
    monkeypatch.setattr(werkzeug.serving, "make_server", fail_constructor)

    with pytest.raises(SystemExit) as exc_info:
        desktop_app.run_desktop_mode()

    assert exc_info.value.code == 1
    assert reservation.listening is False
    assert len(thread_errors) == 1
    assert isinstance(thread_errors[0], RuntimeError)
    assert "cleanup" in events


def test_diagnostics_http_handoff_keeps_exact_reserved_socket_exclusive():
    from http.server import BaseHTTPRequestHandler

    import read_only_diagnostics

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return None

    reservation = read_only_diagnostics.reserve_loopback_port(5000)
    selected = reservation.port
    server = reservation.into_http_server(Handler)
    thief = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    successor = None
    try:
        if os.name == "nt":
            thief.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        with pytest.raises(OSError):
            thief.bind(("127.0.0.1", selected))
    finally:
        thief.close()
        server.server_close()

    try:
        successor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            successor.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        successor.bind(("127.0.0.1", selected))
    finally:
        if successor is not None:
            successor.close()


def test_diagnostics_http_constructor_failure_releases_reserved_socket(
    monkeypatch,
):
    import read_only_diagnostics

    reservation = read_only_diagnostics.reserve_loopback_port(5000)
    selected = reservation.port
    monkeypatch.setattr(
        read_only_diagnostics,
        "ThreadingHTTPServer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("constructor")),
    )

    with pytest.raises(RuntimeError, match="constructor"):
        reservation.into_http_server(object)

    assert reservation.release() is False
    successor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            successor.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        successor.bind(("127.0.0.1", selected))
    finally:
        successor.close()


def test_diagnostics_http_interrupted_handoff_releases_reserved_socket(
    monkeypatch,
):
    import read_only_diagnostics

    reservation = read_only_diagnostics.reserve_loopback_port(5000)
    selected = reservation.port
    monkeypatch.setattr(
        reservation,
        "listen",
        lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        reservation.into_http_server(object)

    assert reservation.release() is False
    successor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            successor.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        successor.bind(("127.0.0.1", selected))
    finally:
        successor.close()


def test_minimal_diagnostics_serve_consumes_supplied_reservation(monkeypatch):
    import read_only_diagnostics

    events = []

    class Server:
        def serve_forever(self, poll_interval):
            events.append(("serve", poll_interval))

        def server_close(self):
            events.append("close")

    class Reservation:
        port = 6123

        def into_http_server(self, handler):
            events.append(("handoff", handler))
            return Server()

    read_only_diagnostics.serve(reservation=Reservation())

    assert events[0][0] == "handoff"
    assert events[1:] == [("serve", 0.2), "close"]


def test_minimal_diagnostics_root_is_branded_html_not_raw_safety_json(tmp_path):
    import read_only_diagnostics

    reservation = read_only_diagnostics.reserve_loopback_port(5000)
    selected = reservation.port
    server = reservation.into_http_server(
        read_only_diagnostics._handler(tmp_path / "missing.db")
    )
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{selected}/", timeout=2
        ) as response:
            content_type = response.headers.get("content-type", "").lower()
            body = response.read().decode("utf-8")

        assert "text/html" in content_type
        assert "CATalyst could not start normally" in body
        assert "/api/safety/status" in body
        assert not body.lstrip().startswith("{")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_diagnostics_preserves_specific_startup_denial_over_generic_lease():
    import read_only_diagnostics

    durable = {
        "allowed": False,
        "reason_code": "LEASE_UNAVAILABLE",
        "source": "lease",
        "lease": {"active": False, "owner_pid": None},
    }
    startup_denial = {
        "allowed": False,
        "reason_code": "WALLET_IDENTITY_BINDING_INVALID",
        "source": "wallet_identity_freshness",
        "recovery": {
            "failed_check": "wallet_identity_freshness",
            "blocker_counts": {"reservations": 2},
            "wallet_id": "must-not-leak",
        },
    }

    merged = read_only_diagnostics.merge_startup_denial(durable, startup_denial)

    assert merged == {
        "allowed": False,
        "reason_code": "WALLET_IDENTITY_BINDING_INVALID",
        "source": "wallet_identity_freshness",
        "lease": {"active": False, "owner_pid": None},
        "recovery": {
            "failed_check": "wallet_identity_freshness",
            "blocker_counts": {"reservations": 2},
        },
    }


def test_diagnostics_never_overrides_a_stronger_durable_reason():
    import read_only_diagnostics

    durable = {
        "allowed": False,
        "reason_code": "LEASE_OWNED_BY_OTHER",
        "source": "lease",
        "lease": {"active": True, "owner_pid": 1234},
    }
    startup_denial = {
        "allowed": False,
        "reason_code": "WALLET_IDENTITY_BINDING_INVALID",
        "source": "wallet_identity_freshness",
    }

    assert (
        read_only_diagnostics.merge_startup_denial(durable, startup_denial) == durable
    )


@pytest.mark.parametrize(
    "method",
    ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT", "BREW"],
)
def test_minimal_diagnostics_rejects_every_non_get_method_as_read_only(
    tmp_path, method
):
    import read_only_diagnostics

    reservation = read_only_diagnostics.reserve_loopback_port(5000)
    selected = reservation.port
    server = reservation.into_http_server(
        read_only_diagnostics._handler(tmp_path / "missing.db")
    )
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        daemon=True,
    )
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{selected}/", data=b"", method=method
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request, timeout=2)
        assert exc_info.value.code == 423
        body = exc_info.value.read()
        if method == "HEAD":
            assert body == b""
        else:
            assert json.loads(body.decode("utf-8")) == {
                "success": False,
                "error": "diagnostics_read_only",
                "reason": "DIAGNOSTICS_READ_ONLY",
            }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_minimal_diagnostics_serve_schedules_bounded_shutdown(monkeypatch):
    import read_only_diagnostics

    events = []

    class Timer:
        def __init__(self, seconds, callback):
            events.append(("timer", seconds, callback.__name__))
            self.daemon = False

        def start(self):
            events.append(("timer-start", self.daemon))

        def cancel(self):
            events.append("timer-cancel")

    class Server:
        def shutdown(self):
            events.append("shutdown")

        def serve_forever(self, poll_interval):
            events.append(("serve", poll_interval))

        def server_close(self):
            events.append("close")

    class Reservation:
        port = 6123

        def into_http_server(self, _handler):
            events.append("handoff")
            return Server()

    monkeypatch.setattr(read_only_diagnostics.threading, "Timer", Timer)

    read_only_diagnostics.serve(reservation=Reservation(), lifetime_seconds=300)

    assert events == [
        "handoff",
        ("timer", 300.0, "shutdown"),
        ("timer-start", True),
        ("serve", 0.2),
        "timer-cancel",
        "close",
    ]


def test_minimal_diagnostics_never_signals_ready_when_handoff_fails():
    import read_only_diagnostics

    events = []

    class Reservation:
        port = 6132

        def into_http_server(self, _handler):
            events.append("handoff")
            raise RuntimeError("handoff failed")

        def release(self):
            events.append("release")
            return True

    with pytest.raises(RuntimeError, match="handoff failed"):
        read_only_diagnostics.serve(
            reservation=Reservation(),
            ready_callback=lambda: events.append("ready"),
        )

    assert events == ["handoff", "release"]


def test_werkzeug_server_handoff_retains_exact_loopback_reservation():
    import api_server
    import read_only_diagnostics

    reservation = read_only_diagnostics.reserve_loopback_port(5000)
    selected = reservation.port
    server = api_server._build_flask_server_on_reservation(reservation)
    thief = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    successor = None
    try:
        assert reservation.release() is False
        if os.name == "nt":
            thief.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        with pytest.raises(OSError):
            thief.bind(("127.0.0.1", selected))
    finally:
        thief.close()
        server.server_close()

    try:
        successor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            successor.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        successor.bind(("127.0.0.1", selected))
    finally:
        if successor is not None:
            successor.close()


def test_desktop_owner_reserves_alternate_port_and_propagates_exact_binding(
    monkeypatch,
):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    unrelated = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    unrelated.bind(("127.0.0.1", 0))
    unrelated.listen(1)
    preferred = int(unrelated.getsockname()[1])
    monkeypatch.setattr(desktop_app, "FLASK_PORT", preferred)
    reservation = None
    try:
        reservation = desktop_app._reserve_owner_server_port()

        assert reservation.port != preferred
        assert desktop_app.FLASK_PORT == reservation.port
        assert os.environ["CATALYST_FLASK_PORT"] == str(reservation.port)
        assert unrelated.getsockname()[1] == preferred
    finally:
        if reservation is not None:
            reservation.release()
        unrelated.close()


def test_authorized_desktop_flask_mode_hands_reservation_to_exact_server(
    monkeypatch,
):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    reservation = SimpleNamespace(port=6124, release=lambda: events.append("release"))

    monkeypatch.setattr(
        desktop_app,
        "_reserve_owner_server_port",
        lambda: events.append("reserve") or reservation,
        raising=False,
    )
    monkeypatch.setattr(
        desktop_app,
        "_start_owned_runtime_services",
        lambda: events.append("services"),
        raising=False,
    )
    monkeypatch.setattr(
        desktop_app,
        "start_flask_server",
        lambda supplied: events.append(("serve", supplied)),
    )
    monkeypatch.setattr(desktop_app, "_cleanup", lambda: events.append("cleanup"))
    monkeypatch.setattr(desktop_app.signal, "signal", lambda *_args: None)

    desktop_app.run_flask_mode()

    assert events == [
        "reserve",
        "services",
        ("serve", reservation),
        "release",
        "cleanup",
    ]


def test_authorized_desktop_mode_uses_alternate_reserved_port_for_server_and_window(
    monkeypatch,
):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    selected_port = 6125

    class StopDesktop(Exception):
        pass

    class ClosingEvent:
        def __iadd__(self, _handler):
            return self

    window = SimpleNamespace(events=SimpleNamespace(closing=ClosingEvent()))

    def create_window(**kwargs):
        events.append(("window", kwargs["url"]))
        return window

    fake_webview = SimpleNamespace(
        create_window=create_window,
        start=lambda **_kwargs: (_ for _ in ()).throw(StopDesktop()),
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setitem(sys.modules, "notification_manager", None)

    reservation = SimpleNamespace(port=selected_port)

    def reserve():
        desktop_app.FLASK_PORT = selected_port
        os.environ["CATALYST_FLASK_PORT"] = str(selected_port)
        events.append("reserve")
        return reservation

    class ImmediateThread:
        def __init__(self, *, target, args=(), **_kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(desktop_app, "check_port_free", lambda _port: False)
    monkeypatch.setattr(
        desktop_app, "_reserve_owner_server_port", reserve, raising=False
    )
    monkeypatch.setattr(
        desktop_app,
        "_start_owned_runtime_services",
        lambda: events.append("services"),
        raising=False,
    )
    monkeypatch.setattr(
        desktop_app,
        "start_flask_server",
        lambda supplied: events.append(("serve", supplied)),
    )
    monkeypatch.setattr(desktop_app.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(desktop_app, "wait_for_flask", lambda timeout: True)
    monkeypatch.setattr(desktop_app, "_start_system_tray", lambda: (None, None))
    monkeypatch.setattr(desktop_app, "_load_window_state", lambda: {})
    monkeypatch.setattr(
        desktop_app, "_should_restore_saved_window_position", lambda: False
    )

    with pytest.raises(StopDesktop):
        desktop_app.run_desktop_mode()

    assert events[:3] == ["reserve", "services", ("serve", reservation)]
    assert ("window", f"http://127.0.0.1:{selected_port}/") in events


def test_desktop_thread_construction_failure_releases_port_and_lease(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []

    class Reservation:
        port = 6126

        def release(self):
            events.append("release")
            return True

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace())
    monkeypatch.setattr(
        desktop_app,
        "_reserve_owner_server_port",
        lambda: events.append("reserve") or Reservation(),
    )
    monkeypatch.setattr(
        desktop_app,
        "_start_owned_runtime_services",
        lambda: events.append("services"),
    )
    monkeypatch.setattr(
        desktop_app.threading,
        "Thread",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("thread constructor")),
    )
    monkeypatch.setattr(desktop_app, "_cleanup", lambda: events.append("cleanup"))

    with pytest.raises(RuntimeError, match="thread constructor"):
        desktop_app.run_desktop_mode()

    assert events == ["reserve", "services", "release", "cleanup"]


def test_flask_signal_setup_failure_releases_port_and_lease(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []

    class Reservation:
        port = 6127

        def release(self):
            events.append("release")
            return True

    monkeypatch.setattr(
        desktop_app,
        "_reserve_owner_server_port",
        lambda: events.append("reserve") or Reservation(),
    )
    monkeypatch.setattr(
        desktop_app,
        "_start_owned_runtime_services",
        lambda: events.append("services"),
    )
    monkeypatch.setattr(
        desktop_app.signal,
        "signal",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("signal setup")),
    )
    monkeypatch.setattr(desktop_app, "_cleanup", lambda: events.append("cleanup"))

    with pytest.raises(RuntimeError, match="signal setup"):
        desktop_app.run_flask_mode()

    assert events == ["reserve", "services", "release", "cleanup"]


def test_authorized_desktop_startup_exception_runs_central_lease_cleanup(
    tmp_path: Path, monkeypatch
):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    monkeypatch.setenv("CMM_DATA_DIR", str(tmp_path / "startup-failure"))
    monkeypatch.setattr(desktop_app, "_authorize_desktop_startup", lambda: True)
    monkeypatch.setattr(desktop_app, "_enable_pythonw_startup_log", lambda: None)
    monkeypatch.setattr(desktop_app, "_attach_to_kill_on_close_job", lambda: None)
    monkeypatch.setattr(
        desktop_app,
        "run_desktop_mode",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("server startup failed")),
    )
    monkeypatch.setattr(desktop_app, "_cleanup", lambda: events.append("cleanup"))
    monkeypatch.setattr(desktop_app, "_CONSOLE_HIDDEN", True)
    monkeypatch.setattr(desktop_app, "_show_fatal_error_dialog", lambda _msg: None)
    monkeypatch.setattr(database, "attempt_db_recovery", lambda: {})

    assert desktop_app.main(["--show-console"]) == 1
    assert events == ["cleanup"]


def test_desktop_lease_acquisition_defers_owner_services_until_port_reserved(
    monkeypatch,
):
    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        desktop_app,
        "_retire_expired_dead_startup_lease",
        lambda: (
            events.append("retire_stale_lease")
            or {"retired": False, "reason": "lease_not_active"}
        ),
    )
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda: events.append("lease") or {"allowed": True},
    )
    monkeypatch.setattr(
        api_server,
        "_start_owned_runtime_services",
        lambda _authorization: events.append("services"),
    )

    assert desktop_app._initialize_startup_ownership() == {"allowed": True}
    assert events == ["database", "retire_stale_lease", "lease"]


@pytest.mark.parametrize(
    "reason_code",
    [
        "COIN_PREP_EFFECT_UNKNOWN",
        "WALLET_EFFECT_SUBMITTED_UNRECONCILED",
        "WALLET_EFFECT_UNKNOWN_UNRECONCILED",
    ],
)
def test_desktop_retries_startup_after_exact_coin_prep_recovery(
    monkeypatch, reason_code
):
    """Catches a recoverable submitted split trapping reload in diagnostics."""

    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    authorizations = iter(
        [
            {
                "allowed": False,
                "reason_code": reason_code,
                "failed_check": "unresolved_operations",
            },
            {"allowed": True, "reason_code": "", "failed_check": None},
        ]
    )
    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda: events.append("authorize") or next(authorizations),
    )
    monkeypatch.setitem(
        sys.modules,
        "coin_prep_worker",
        SimpleNamespace(
            recover_coin_prep_operations_at_startup=lambda: (
                events.append("coin_prep_recovery") or True
            )
        ),
    )

    result = desktop_app._initialize_startup_ownership()

    assert result["allowed"] is True
    assert events == [
        "database",
        "authorize",
        "coin_prep_recovery",
        "authorize",
    ]


def test_desktop_retires_expired_lease_only_after_dead_owner_proof(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    lease = {
        "active": 1,
        "lease_version": 17,
        "owner_pid": 2147483647,
        "owner_host": socket.gethostname(),
    }
    calls = []
    monkeypatch.setattr(database, "get_runtime_mutation_lease", lambda: dict(lease))
    monkeypatch.setattr(
        mutation_gate,
        "pid_liveness",
        lambda pid, host: calls.append(("liveness", pid, host)) or False,
    )
    monkeypatch.setattr(
        database,
        "retire_expired_dead_runtime_lease_at_startup",
        lambda **kwargs: (
            calls.append(("retire", kwargs))
            or {"retired": True, "reason": "expired_dead_owner"}
        ),
    )

    result = desktop_app._retire_expired_dead_startup_lease()

    assert result["retired"] is True
    assert calls == [
        ("liveness", 2147483647, socket.gethostname()),
        (
            "retire",
            {
                "expected_lease_version": 17,
                "prior_owner_liveness_proven_dead": True,
            },
        ),
    ]


def test_desktop_waits_for_brief_dead_owner_lease_then_retires_it(monkeypatch):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    lease = {
        "active": 1,
        "lease_version": 19,
        "owner_run_id": "killed-updater-owner",
        "owner_pid": 2147483647,
        "owner_host": socket.gethostname(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(milliseconds=50))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    calls = []
    retire_results = iter(
        [
            {"retired": False, "reason": "lease_not_expired", "lease": dict(lease)},
            {"retired": True, "reason": "expired_dead_owner", "lease": dict(lease)},
        ]
    )
    monkeypatch.setattr(database, "get_runtime_mutation_lease", lambda: dict(lease))
    monkeypatch.setattr(
        mutation_gate,
        "pid_liveness",
        lambda pid, host: calls.append(("liveness", pid, host)) or False,
    )
    monkeypatch.setattr(
        database,
        "retire_expired_dead_runtime_lease_at_startup",
        lambda **kwargs: calls.append(("retire", kwargs)) or next(retire_results),
    )
    monkeypatch.setattr(
        desktop_app.time,
        "sleep",
        lambda seconds: calls.append(("sleep", seconds)),
    )

    result = desktop_app._retire_expired_dead_startup_lease()

    assert result["retired"] is True
    assert [event[0] for event in calls] == [
        "liveness",
        "retire",
        "sleep",
        "liveness",
        "retire",
    ]
    assert 0 < calls[2][1] <= desktop_app._STARTUP_DEAD_LEASE_MAX_WAIT_SECONDS
    assert (
        calls[1][1]
        == calls[4][1]
        == {
            "expected_lease_version": 19,
            "prior_owner_liveness_proven_dead": True,
        }
    )


def test_desktop_retries_startup_after_exact_dexie_publication_recovery(
    monkeypatch,
):
    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    authorizations = iter(
        [
            {
                "allowed": False,
                "reason_code": "PUBLICATION_CLAIM_RECOVERY_REQUIRED",
                "failed_check": "publication_claims",
            },
            {"allowed": True, "reason_code": "", "failed_check": None},
        ]
    )
    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda: events.append("authorize") or next(authorizations),
    )
    monkeypatch.setitem(
        sys.modules,
        "dexie_manager",
        SimpleNamespace(
            recover_expired_dexie_publications_at_startup=lambda: (
                events.append("dexie_publication_recovery")
                or {"checked": 1, "recovered": 1, "remaining": 0}
            )
        ),
    )

    result = desktop_app._initialize_startup_ownership()

    assert result["allowed"] is True
    assert events == [
        "database",
        "authorize",
        "dexie_publication_recovery",
        "authorize",
    ]


def test_desktop_retries_startup_after_orphaned_publication_is_suppressed(
    monkeypatch,
):
    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    authorizations = iter(
        [
            {
                "allowed": False,
                "reason_code": "PUBLICATION_CLAIM_RECOVERY_REQUIRED",
                "failed_check": "publication_claims",
            },
            {"allowed": True, "reason_code": "", "failed_check": None},
        ]
    )
    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        database,
        "recover_undispatched_publication_claims_at_startup",
        lambda: (
            events.append("undispatched_publication_recovery")
            or {"examined": 1, "recovered": 0, "remaining": 1}
        ),
    )
    monkeypatch.setattr(
        database,
        "suppress_orphaned_dispatched_publications_at_startup",
        lambda: (
            events.append("orphaned_publication_suppression")
            or {"examined": 1, "suppressed": 1, "remaining": 0}
        ),
    )
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda: events.append("authorize") or next(authorizations),
    )
    monkeypatch.setitem(
        sys.modules,
        "dexie_manager",
        SimpleNamespace(
            recover_expired_dexie_publications_at_startup=lambda: (
                events.append("dexie_publication_recovery")
                or {"checked": 1, "recovered": 0, "remaining": 1}
            )
        ),
    )

    result = desktop_app._initialize_startup_ownership()

    assert result["allowed"] is True
    assert events == [
        "database",
        "authorize",
        "undispatched_publication_recovery",
        "dexie_publication_recovery",
        "orphaned_publication_suppression",
        "authorize",
    ]


def test_desktop_upgrade_restart_recovers_undispatched_publication_before_readback(
    monkeypatch,
):
    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    authorizations = iter(
        [
            {
                "allowed": False,
                "reason_code": "PUBLICATION_CLAIM_RECOVERY_REQUIRED",
                "failed_check": "publication_claims",
            },
            {"allowed": True, "reason_code": "", "failed_check": None},
        ]
    )
    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        database,
        "recover_undispatched_publication_claims_at_startup",
        lambda: (
            events.append("undispatched_publication_recovery")
            or {"examined": 1, "recovered": 1, "remaining": 0}
        ),
    )
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda: events.append("authorize") or next(authorizations),
    )
    monkeypatch.setitem(
        sys.modules,
        "dexie_manager",
        SimpleNamespace(
            recover_expired_dexie_publications_at_startup=lambda: (
                events.append("dexie_publication_recovery")
                or {"checked": 0, "recovered": 0, "remaining": 1}
            )
        ),
    )
    monkeypatch.setattr(
        api_server,
        "recover_legacy_startup_reservations",
        lambda: (
            events.append("legacy_recovery")
            or {"examined": 0, "recovered": 0, "remaining": 0}
        ),
    )

    result = desktop_app._initialize_startup_ownership()

    assert result["allowed"] is True
    assert events == [
        "database",
        "authorize",
        "undispatched_publication_recovery",
        "authorize",
    ]


def test_desktop_resumes_interrupted_legacy_reservation_recovery(monkeypatch):
    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    authorizations = iter(
        [
            {
                "allowed": False,
                "reason_code": "UNRESOLVED_OPERATIONS",
                "failed_check": "unresolved_operations",
            },
            {"allowed": True, "reason_code": "", "failed_check": None},
        ]
    )
    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda: events.append("authorize") or next(authorizations),
    )
    monkeypatch.setattr(
        api_server,
        "recover_legacy_startup_reservations",
        lambda: (
            events.append("legacy_recovery")
            or {"examined": 1, "recovered": 1, "remaining": 0}
        ),
    )

    result = desktop_app._initialize_startup_ownership()

    assert result["allowed"] is True
    assert events == [
        "database",
        "authorize",
        "legacy_recovery",
        "authorize",
    ]


def test_desktop_retries_transient_legacy_recovery_while_sage_restarts(monkeypatch):
    """Sage becoming ready moments later must not strand safe legacy locks."""

    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    authorizations = iter(
        [
            {
                "allowed": False,
                "reason_code": "RESERVATION_RECONCILIATION_REQUIRED",
                "failed_check": "reservations",
            },
            {"allowed": True, "reason_code": "", "failed_check": None},
        ]
    )
    recoveries = iter(
        [
            {"examined": 2, "recovered": 0, "remaining": 2},
            {"examined": 2, "recovered": 2, "remaining": 0},
        ]
    )
    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda: events.append("authorize") or next(authorizations),
    )
    monkeypatch.setattr(
        api_server,
        "recover_legacy_startup_reservations",
        lambda: events.append("legacy_recovery") or next(recoveries),
    )
    monkeypatch.setattr(
        desktop_app.time,
        "sleep",
        lambda seconds: events.append(("sleep", seconds)),
    )

    result = desktop_app._initialize_startup_ownership()

    assert result["allowed"] is True
    assert events == [
        "database",
        "authorize",
        "legacy_recovery",
        ("sleep", 1.0),
        "legacy_recovery",
        "authorize",
    ]


def test_desktop_legacy_recovery_retry_is_bounded_and_fail_closed(monkeypatch):
    """Missing Sage evidence must still stop after the bounded retry window."""

    import api_server

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []
    blocked = {
        "allowed": False,
        "reason_code": "RESERVATION_RECONCILIATION_REQUIRED",
        "failed_check": "reservations",
    }
    monkeypatch.setattr(database, "init_database", lambda: events.append("database"))
    monkeypatch.setattr(
        api_server,
        "initialize_mutation_runtime",
        lambda: events.append("authorize") or blocked,
    )
    monkeypatch.setattr(
        api_server,
        "recover_legacy_startup_reservations",
        lambda: (
            events.append("legacy_recovery")
            or {"examined": 2, "recovered": 0, "remaining": 2}
        ),
    )
    monkeypatch.setattr(
        desktop_app.time,
        "sleep",
        lambda seconds: events.append(("sleep", seconds)),
    )

    result = desktop_app._initialize_startup_ownership()

    assert result == blocked
    assert events == [
        "database",
        "authorize",
        "legacy_recovery",
        ("sleep", 1.0),
        "legacy_recovery",
        ("sleep", 1.0),
        "legacy_recovery",
    ]


def test_desktop_holds_startup_arbiter_until_gate_lease_is_allowed(monkeypatch):
    import read_only_diagnostics

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    events = []

    class Arbiter:
        acquired = True
        reason = ""
        released = False

        def release(self):
            self.released = True
            events.append("arbiter_release")
            return True

    arbiter = Arbiter()
    monkeypatch.setattr(
        read_only_diagnostics,
        "acquire_startup_arbiter",
        lambda: events.append("arbiter_acquire") or arbiter,
    )
    monkeypatch.setattr(
        read_only_diagnostics,
        "preflight_requires_diagnostics",
        lambda: events.append("durable_preflight") or False,
    )
    monkeypatch.setattr(
        desktop_app,
        "_acquire_instance_lock",
        lambda: events.append("instance_lock") or True,
    )
    monkeypatch.setattr(
        desktop_app,
        "_initialize_startup_ownership",
        lambda: events.append("lease_acquire") or {"allowed": not arbiter.released},
        raising=False,
    )
    monkeypatch.setattr(desktop_app, "_enable_pythonw_startup_log", lambda: None)
    monkeypatch.setattr(desktop_app, "_attach_to_kill_on_close_job", lambda: None)
    monkeypatch.setattr(desktop_app, "_hide_windows_console", lambda: None)
    monkeypatch.setattr(
        desktop_app,
        "run_flask_mode",
        lambda: events.append(("run", arbiter.released)),
    )
    monkeypatch.setattr(database, "attempt_db_recovery", lambda: {})

    assert desktop_app.main(["--flask", "--show-console"]) == 0
    assert events == [
        "arbiter_acquire",
        "durable_preflight",
        "instance_lock",
        "lease_acquire",
        "arbiter_release",
        ("run", True),
    ]


def test_desktop_foreign_lease_preflight_never_touches_writable_instance_lock(
    monkeypatch,
):
    import read_only_diagnostics

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    calls = []
    monkeypatch.setattr(desktop_app.sys, "platform", "win32")
    monkeypatch.setattr(
        read_only_diagnostics, "preflight_requires_diagnostics", lambda: True
    )
    monkeypatch.setattr(
        desktop_app,
        "_acquire_instance_lock",
        lambda: (_ for _ in ()).throw(
            AssertionError("foreign owner path must not open the lock file")
        ),
    )
    monkeypatch.setattr(
        desktop_app, "_open_existing_instance_in_browser", lambda _port: None
    )
    monkeypatch.setattr(desktop_app, "_focus_existing_catalyst_window", lambda: False)
    reservation = SimpleNamespace(port=desktop_app.FLASK_PORT + 9)
    monkeypatch.setattr(
        desktop_app,
        "_reserve_diagnostics_server_port",
        lambda: reservation,
    )
    monkeypatch.setattr(
        desktop_app,
        "run_read_only_diagnostics_desktop_mode",
        lambda supplied: calls.append(supplied),
    )

    assert desktop_app.main(["--show-console"]) == 0
    assert calls == [reservation]


def test_desktop_instance_lock_path_is_stdlib_only_before_ownership(
    tmp_path: Path, monkeypatch
):
    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)
    data_dir = tmp_path / "lock-race"
    monkeypatch.setenv("CMM_DATA_DIR", str(data_dir))
    imported = []
    real_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] == "user_paths":
            imported.append(name)
            raise AssertionError("lock preflight cannot import user_paths")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)

    path = desktop_app._instance_lock_path()

    assert imported == []
    assert Path(path) == data_dir / ".instance.lock"
    assert not data_dir.exists()


def test_pythonw_import_before_ownership_creates_no_shared_files(tmp_path: Path):
    data_dir = tmp_path / "pythonw-preflight"
    env = os.environ.copy()
    env["CMM_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path(__file__).parents[1] / "src" / "catalyst"),
            str(Path(__file__).parents[1]),
        ]
    )
    command = (
        "import sys;"
        "sys.executable='pythonw.exe';"
        "sys.stdout=None;sys.stderr=None;"
        "import desktop_app"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=Path(__file__).parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    assert not data_dir.exists()


def test_startup_arbiter_serializes_canonical_data_directory(tmp_path: Path):
    import read_only_diagnostics

    data_dir = tmp_path / "arbiter-data"
    alias = data_dir.parent / "." / data_dir.name
    first = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=data_dir, wait_seconds=0
    )
    try:
        assert first.acquired is True
        second = read_only_diagnostics.acquire_startup_arbiter(
            data_dir=alias, wait_seconds=0
        )
        assert second.acquired is False
        assert second.reason == "startup_arbiter_busy"
        assert second.lock_path == first.lock_path
    finally:
        first.release()

    successor = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=alias, wait_seconds=0
    )
    try:
        assert successor.acquired is True
        assert successor.lock_path == first.lock_path
    finally:
        successor.release()


def test_startup_arbiter_symlink_case_and_unrelated_directory_identity(tmp_path: Path):
    import read_only_diagnostics

    target = tmp_path / "MixedCaseData"
    target.mkdir()
    case_alias = Path(str(target).swapcase()) if os.name == "nt" else target
    assert read_only_diagnostics._startup_lock_path(
        case_alias
    ) == read_only_diagnostics._startup_lock_path(target)

    symlink = tmp_path / "data-alias"
    try:
        symlink.symlink_to(target, target_is_directory=True)
    except OSError:
        symlink = target
    assert read_only_diagnostics._startup_lock_path(
        symlink
    ) == read_only_diagnostics._startup_lock_path(target)

    unrelated = tmp_path / "unrelated-data"
    first = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=target, wait_seconds=0
    )
    second = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=unrelated, wait_seconds=0
    )
    try:
        assert first.acquired is True
        assert second.acquired is True
        assert first.lock_path != second.lock_path
    finally:
        first.release()
        second.release()


@pytest.mark.parametrize(
    ("platform", "environment", "expected_parts"),
    [
        ("win32", {"APPDATA": "platform-appdata"}, ("platform-appdata", "Catalyst")),
        (
            "darwin",
            {},
            ("home", "Library", "Application Support", "Catalyst"),
        ),
        ("linux", {"XDG_DATA_HOME": "platform-xdg"}, ("platform-xdg", "Catalyst")),
    ],
)
def test_startup_arbiter_default_data_path_is_stdlib_and_platform_stable(
    tmp_path: Path, monkeypatch, platform, environment, expected_parts
):
    import read_only_diagnostics

    monkeypatch.delenv("CMM_DATA_DIR", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    for name, relative in environment.items():
        monkeypatch.setenv(name, str(tmp_path / relative))
    monkeypatch.setattr(read_only_diagnostics.sys, "platform", platform)
    monkeypatch.setattr(
        read_only_diagnostics.Path,
        "home",
        classmethod(lambda _cls: tmp_path / "home"),
    )

    resolved = read_only_diagnostics._data_directory()

    expected = tmp_path.joinpath(*expected_parts)
    assert resolved == expected
    assert read_only_diagnostics._startup_lock_path().parent.name == (
        "catalyst-startup-arbiters"
    )


def test_startup_arbiter_busy_and_setup_failures_close_the_open_handle(
    tmp_path: Path, monkeypatch
):
    import read_only_diagnostics

    class Handle:
        closed = False

        def seek(self, *_args):
            raise RuntimeError("lock setup failed")

        def close(self):
            self.closed = True

    handle = Handle()
    monkeypatch.setattr(
        read_only_diagnostics, "_open_startup_lock", lambda _path: handle
    )

    denied = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=tmp_path / "handle-close", wait_seconds=0
    )

    assert denied.acquired is False
    assert denied.reason == "startup_arbiter_unavailable"
    assert handle.closed is True


def test_startup_arbiter_ignores_stale_file_without_live_os_lock(tmp_path: Path):
    import read_only_diagnostics

    data_dir = tmp_path / "stale-file"
    lock_path = read_only_diagnostics._startup_lock_path(data_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_bytes(b"stale-owner-metadata")

    arbiter = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=data_dir, wait_seconds=0
    )
    try:
        assert arbiter.acquired is True
    finally:
        arbiter.release()


def test_startup_arbiter_open_error_fails_closed(tmp_path: Path, monkeypatch):
    import read_only_diagnostics

    monkeypatch.setattr(
        read_only_diagnostics,
        "_open_startup_lock",
        lambda _path: (_ for _ in ()).throw(OSError("lock denied")),
    )

    denied = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=tmp_path / "denied", wait_seconds=0
    )

    assert denied.acquired is False
    assert denied.reason == "startup_arbiter_unavailable"


def test_startup_arbiter_os_lock_is_released_after_process_crash(tmp_path: Path):
    source_root = Path(__file__).resolve().parents[1] / "src" / "catalyst"
    data_dir = tmp_path / "crash-release"
    code = r"""
import os, sys, time
sys.path.insert(0, sys.argv[1])
import read_only_diagnostics
arbiter = read_only_diagnostics.acquire_startup_arbiter(
    data_dir=sys.argv[2], wait_seconds=0
)
sys.stdout.write("ACQUIRED\n" if arbiter.acquired else "DENIED\n")
sys.stdout.flush()
time.sleep(30)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(source_root), str(data_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ACQUIRED"
    finally:
        process.kill()
        process.wait(timeout=10)

    import read_only_diagnostics

    successor = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=data_dir, wait_seconds=2
    )
    try:
        assert successor.acquired is True
    finally:
        successor.release()


def test_diagnostics_preflight_fails_closed_if_checkpoint_races_snapshot_copy(
    isolated_gate_database, monkeypatch
):
    path, clock = isolated_gate_database
    import read_only_diagnostics

    database.close_connection()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="checkpoint-race-owner",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        lease_expires_at=clock() + timedelta(minutes=5),
        now=clock(),
        expected_lease_version=0,
    )
    assert acquired["acquired"] is True
    real_copy = read_only_diagnostics.shutil.copyfile
    checkpointed = []

    def copy_then_checkpoint(source, destination, *args, **kwargs):
        result = real_copy(source, destination, *args, **kwargs)
        if Path(source) == path and not checkpointed:
            checkpointed.append(True)
            database.close_connection()
            with sqlite3.connect(path) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return result

    monkeypatch.setattr(read_only_diagnostics.shutil, "copyfile", copy_then_checkpoint)

    assert read_only_diagnostics.preflight_requires_diagnostics(path) is True
    assert checkpointed == [True]


def test_diagnostics_preflight_allows_brief_dead_owner_lease_to_reach_recovery(
    isolated_gate_database, monkeypatch
):
    path, clock = isolated_gate_database
    import read_only_diagnostics

    expires_at = (
        (datetime.now(timezone.utc) + timedelta(seconds=5))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="upgrade-hard-killed-owner",
        owner_pid=2147483647,
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        lease_expires_at=expires_at,
        now=clock(),
        expected_lease_version=0,
    )
    assert acquired["acquired"] is True
    database.close_connection()
    monkeypatch.setattr(
        read_only_diagnostics,
        "_pid_liveness",
        lambda pid, host: False,
    )

    assert read_only_diagnostics.preflight_requires_diagnostics(path) is False


def test_diagnostics_preflight_keeps_long_dead_owner_lease_fail_closed(
    isolated_gate_database, monkeypatch
):
    path, clock = isolated_gate_database
    import read_only_diagnostics

    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="unexpected-long-lease-owner",
        owner_pid=2147483647,
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
        now=clock(),
        expected_lease_version=0,
    )
    assert acquired["acquired"] is True
    database.close_connection()
    monkeypatch.setattr(
        read_only_diagnostics,
        "_pid_liveness",
        lambda pid, host: False,
    )

    assert read_only_diagnostics.preflight_requires_diagnostics(path) is True


def test_diagnostics_preflight_allows_valid_legacy_database_migration(tmp_path: Path):
    import read_only_diagnostics

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings(key,value) VALUES ('NETWORK','mainnet')")
        conn.commit()

    assert read_only_diagnostics.preflight_requires_diagnostics(path) is False


@pytest.mark.parametrize(
    "table_name",
    [
        "offer_intents",
        "offer_operation_journal",
        "publication_outbox",
        "runtime_mutation_lease",
        "runtime_safety_latch",
        "runtime_worker_delegations",
    ],
)
def test_diagnostics_preflight_rejects_every_partial_stability_schema(
    tmp_path: Path, table_name: str
):
    import read_only_diagnostics

    path = tmp_path / f"partial-{table_name}.db"
    with sqlite3.connect(path) as conn:
        conn.execute(f'CREATE TABLE "{table_name}" (id INTEGER)')
        conn.commit()

    assert read_only_diagnostics.preflight_requires_diagnostics(path) is True


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _free_loopback_port_pair() -> tuple[int, int]:
    for _attempt in range(100):
        first = _free_loopback_port()
        if first >= 65535:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as second_listener:
            try:
                second_listener.bind(("127.0.0.1", first + 1))
            except Exception:
                continue
        return first, first + 1
    raise AssertionError("could not reserve a free adjacent loopback port pair")


def _bounded_loopback_candidates(
    preferred: int, *, include_preferred: bool
) -> tuple[int, ...]:
    import read_only_diagnostics

    return tuple(
        read_only_diagnostics._candidate_loopback_ports(
            preferred,
            include_preferred=include_preferred,
            search_limit=50,
        )
    )


def _wait_for_diagnostics_status(process, port: int) -> dict:
    deadline = time.monotonic() + 10
    url = f"http://127.0.0.1:{port}/api/safety/status"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"diagnostics process exited early: {process.communicate()[1]}"
            )
        try:
            with urllib.request.urlopen(url, timeout=0.25) as response:
                return json.loads(response.read().decode("utf-8"))
        except OSError:
            time.sleep(0.05)
    return_code = process.poll()
    stderr = process.communicate(timeout=1)[1] if return_code is not None else ""
    raise AssertionError(
        f"diagnostics server did not become ready: code={return_code}, stderr={stderr}"
    )


def _wait_for_any_diagnostics_status(process, ports) -> tuple[int, dict]:
    deadline = time.monotonic() + 30
    candidate_ports = tuple(ports)[:8]
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"diagnostics process exited early: {process.communicate()[1]}"
            )
        for port in candidate_ports:
            if process.poll() is not None:
                raise AssertionError(
                    f"diagnostics process exited early: {process.communicate()[1]}"
                )
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/safety/status", timeout=1
                ) as response:
                    return port, json.loads(response.read().decode("utf-8"))
            except Exception:
                continue
        time.sleep(0.02)
    process.terminate()
    stdout, stderr = process.communicate(timeout=10)
    raise AssertionError(
        "diagnostics server did not become ready on an allowed port: "
        f"stdout={stdout!r}, stderr={stderr!r}"
    )


def _standalone_test_environment(tmp_path: Path, data_dir: Path, port: int) -> dict:
    """Build an isolated process environment without starting real CAT resolution."""

    data_dir.mkdir()
    # These tests exercise first database/lease ownership, not legacy install-dir
    # migration.  A developer worktree may legitimately contain ignored runtime
    # state from packaged-app testing; prevent that state from being copied into
    # the isolated child profile and changing its startup authorization.
    (data_dir / ".migration_complete").write_text(
        "Standalone mutation-gate test profile; legacy migration disabled.\n",
        encoding="utf-8",
    )
    (data_dir / ".env").write_text(
        "WALLET_TYPE=sage\n"
        "SAGE_FINGERPRINT=161616161\n"
        "WALLET_EXPECTED_NAME=Task 16 Synthetic Wallet\n"
        "WALLET_EXPECTED_KEY_KIND=bls\n"
        "WALLET_IDENTITY_MAX_AGE_SECONDS=10\n",
        encoding="utf-8",
    )
    support = tmp_path / "standalone-test-support"
    support.mkdir(exist_ok=True)
    (support / "sitecustomize.py").write_text(
        "import sys, types\n"
        "module = types.ModuleType('cat_resolver')\n"
        "module.resolve_and_apply = lambda _cfg: {}\n"
        "sys.modules['cat_resolver'] = module\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CMM_DATA_DIR"] = str(data_dir)
    env["CATALYST_FLASK_PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    # Task 14 made an immutable configured wallet identity mandatory before a
    # fresh runtime may acquire its lease.  Give these standalone processes a
    # deterministic, non-secret test identity instead of inheriting operator
    # configuration (or failing closed as unconfigured).
    env["CATALYST_NETWORK_ID"] = "mainnet"
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(support),
            str(Path(__file__).parents[1] / "src" / "catalyst"),
            str(Path(__file__).parents[1]),
        ]
    )
    return env


def _start_standalone_process(env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "src" / "catalyst" / "api_server.py"),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_safety_servers(processes, ports, count: int) -> dict[int, dict]:
    deadline = time.monotonic() + 60
    found = {}
    process_ids = {process.pid for process in processes}
    # The supplied preferred port was confirmed free immediately before the
    # children started.  Poll its nearest bounded alternatives repeatedly;
    # walking the entire production search window once can consume the whole
    # readiness deadline on Windows when an unopened port drops SYN packets.
    candidate_ports = tuple(ports)[: max(8, count * 4)]
    while time.monotonic() < deadline:
        exited = [process for process in processes if process.poll() is not None]
        if exited:
            details = [process.communicate()[1] for process in exited]
            raise AssertionError(f"standalone process exited early: {details}")
        for port in candidate_ports:
            if port in found:
                continue
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/safety/status", timeout=1
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    safety = payload.get("safety", {})
                    lease = safety.get("lease", {})
                    owner_pid = lease.get("owner_pid")
                    # Owner diagnostics intentionally redact the process ID;
                    # the per-process ``owned_by_this_run`` proof is the
                    # public correlation signal for an allowed child.
                    belongs_to_child = owner_pid in process_ids or (
                        safety.get("allowed") is True
                        and lease.get("owned_by_this_run") is True
                    )
                    if belongs_to_child:
                        found[port] = payload
            except Exception:
                continue
        if len(found) >= count:
            return found
        time.sleep(0.02)
    for process in processes:
        if process.poll() is None:
            process.terminate()
    details = [process.communicate(timeout=10) for process in processes]
    raise AssertionError(
        f"expected {count} safety servers, found {found}; processes={details}"
    )


def _terminate_test_processes(processes) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.mark.parametrize("corrupt", [False, True])
def test_spawned_desktop_diagnostics_is_import_and_filesystem_side_effect_free(
    tmp_path: Path,
    corrupt: bool,
):
    data_dir = tmp_path / ("corrupt" if corrupt else "missing")
    data_dir.mkdir()
    database_path = data_dir / "bot.db"
    if corrupt:
        database_path.write_bytes(b"not-a-sqlite-database")
    expected_files = {
        item.name: item.read_bytes() for item in data_dir.iterdir() if item.is_file()
    }
    port = _free_loopback_port()
    env = os.environ.copy()
    env["CMM_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path(__file__).parents[1] / "src" / "catalyst"),
            str(Path(__file__).parents[1]),
        ]
    )
    command = (
        "import builtins,desktop_app,read_only_diagnostics;"
        "real=builtins.__import__;"
        "blocked={'api_server','config','user_paths','super_log'};"
        "builtins.__import__=lambda name,*a,**k: "
        "(_ for _ in ()).throw(AssertionError(name)) "
        "if name.split('.')[0] in blocked else real(name,*a,**k);"
        f"r=read_only_diagnostics.reserve_loopback_port({port},search_limit=0);"
        "desktop_app.run_read_only_diagnostics_mode(r)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", command],
        cwd=Path(__file__).parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        payload = _wait_for_diagnostics_status(process, port)
        assert payload["safety"]["allowed"] is False
        assert payload["safety"]["reason_code"] == "DURABLE_STATE_UNAVAILABLE"
    finally:
        process.terminate()
        process.wait(timeout=10)

    actual_files = {
        item.name: item.read_bytes() for item in data_dir.iterdir() if item.is_file()
    }
    assert actual_files == expected_files


def test_free_port_standalone_process_defers_to_existing_durable_owner(
    tmp_path: Path,
    monkeypatch,
):
    data_dir = tmp_path / "standalone-foreign-owner"
    data_dir.mkdir()
    child_database = data_dir / "bot.db"
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(child_database))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    now = datetime.now(timezone.utc)
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="already-running-owner",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        lease_expires_at=now + timedelta(minutes=10),
        now=now,
        expected_lease_version=0,
    )
    assert acquired["acquired"] is True
    database.close_connection()
    before_names = {item.name for item in data_dir.iterdir()}
    before_database = child_database.read_bytes()

    port = _free_loopback_port()
    env = os.environ.copy()
    env["CMM_DATA_DIR"] = str(data_dir)
    env["CATALYST_FLASK_PORT"] = str(port)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path(__file__).parents[1] / "src" / "catalyst"),
            str(Path(__file__).parents[1]),
        ]
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "src" / "catalyst" / "api_server.py"),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        selected_port, payload = _wait_for_any_diagnostics_status(
            process,
            _bounded_loopback_candidates(port, include_preferred=False),
        )
        assert selected_port != port
        assert payload["safety"]["allowed"] is False
        assert payload["safety"]["reason_code"] == "LEASE_OWNED_BY_OTHER"
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(
                f"http://127.0.0.1:{selected_port}/api/status", timeout=1
            )
        assert error.value.code == 423
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert {item.name for item in data_dir.iterdir()} == before_names
    assert child_database.read_bytes() == before_database


def test_simultaneous_first_run_standalone_processes_create_exactly_one_owner(
    tmp_path: Path,
):
    data_dir = tmp_path / "simultaneous-first-run"
    assert not data_dir.exists()
    port = _free_loopback_port()
    env = _standalone_test_environment(tmp_path, data_dir, port)
    processes = [_start_standalone_process(env), _start_standalone_process(env)]
    try:
        servers = _wait_for_safety_servers(
            processes,
            _bounded_loopback_candidates(port, include_preferred=True),
            count=2,
        )
        allowed = [
            (server_port, payload)
            for server_port, payload in servers.items()
            if payload["safety"]["allowed"]
        ]
        denied = [
            (server_port, payload)
            for server_port, payload in servers.items()
            if not payload["safety"]["allowed"]
        ]
        assert len(allowed) == 1
        assert len(denied) == 1
        assert denied[0][1]["safety"]["reason_code"] == "LEASE_OWNED_BY_OTHER"

        with sqlite3.connect(data_dir / "bot.db") as conn:
            rows = conn.execute(
                "SELECT active, owner_pid FROM runtime_mutation_lease"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1
        assert allowed[0][1]["safety"]["lease"]["owned_by_this_run"] is True
        assert "owner_pid" not in allowed[0][1]["safety"]["lease"]
        assert rows[0][1] in {process.pid for process in processes}
    finally:
        _terminate_test_processes(processes)

    import read_only_diagnostics

    successor = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=data_dir, wait_seconds=1
    )
    try:
        assert successor.acquired is True
    finally:
        successor.release()


def test_unrelated_port_occupancy_still_allows_one_full_owner_on_alternate_port(
    tmp_path: Path,
):
    data_dir = tmp_path / "occupied-port-first-run"
    port = _free_loopback_port()
    env = _standalone_test_environment(tmp_path, data_dir, port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unrelated_listener:
        unrelated_listener.bind(("127.0.0.1", port))
        unrelated_listener.listen(1)
        process = _start_standalone_process(env)
        try:
            servers = _wait_for_safety_servers(
                [process],
                _bounded_loopback_candidates(port, include_preferred=True),
                count=1,
            )
            selected_port, payload = next(iter(servers.items()))
            assert selected_port != port
            assert payload["safety"]["allowed"] is True
            assert payload["safety"]["lease"]["owned_by_this_run"] is True
            assert "owner_pid" not in payload["safety"]["lease"]
            with sqlite3.connect(data_dir / "bot.db") as conn:
                durable_owner_pid = conn.execute(
                    "SELECT owner_pid FROM runtime_mutation_lease WHERE active=1"
                ).fetchone()[0]
            assert durable_owner_pid == process.pid
        finally:
            _terminate_test_processes([process])


def test_spawned_desktop_waits_for_arbiter_before_foreign_owner_preflight(
    tmp_path: Path, monkeypatch
):
    import read_only_diagnostics

    data_dir = tmp_path / "desktop-startup-barrier"
    data_dir.mkdir()
    child_database = data_dir / "bot.db"
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(child_database))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    database.close_connection()
    arbiter = read_only_diagnostics.acquire_startup_arbiter(
        data_dir=data_dir, wait_seconds=0
    )
    assert arbiter.acquired is True
    attempt_marker = tmp_path / "child-attempted-arbiter"
    port, _diagnostics_port = _free_loopback_port_pair()
    env = os.environ.copy()
    env["CMM_DATA_DIR"] = str(data_dir)
    env["CATALYST_FLASK_PORT"] = str(port)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path(__file__).parents[1] / "src" / "catalyst"),
            str(Path(__file__).parents[1]),
        ]
    )
    command = r"""
import builtins, pathlib, sys
import read_only_diagnostics
real_acquire = read_only_diagnostics.acquire_startup_arbiter
marker = pathlib.Path(sys.argv[1])
def observed_acquire(**kwargs):
    marker.write_text(str(read_only_diagnostics._startup_lock_path()), encoding="utf-8")
    return real_acquire(**kwargs)
read_only_diagnostics.acquire_startup_arbiter = observed_acquire
import desktop_app
desktop_app._open_existing_instance_in_browser = lambda _port: None
real_import = builtins.__import__
blocked = {"api_server", "config", "user_paths", "super_log", "database"}
def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in blocked:
        raise AssertionError(f"writable import before diagnostics: {name}")
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
raise SystemExit(desktop_app.main(["--show-console"]))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", command, str(attempt_marker)],
        cwd=Path(__file__).parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not attempt_marker.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(process.communicate()[1])
            time.sleep(0.02)
        assert attempt_marker.exists()
        assert Path(attempt_marker.read_text(encoding="utf-8")) == arbiter.lock_path
        assert process.poll() is None

        now = datetime.now(timezone.utc)
        acquired = database.acquire_runtime_mutation_lease(
            owner_run_id="barrier-parent-owner",
            owner_pid=os.getpid(),
            owner_host=socket.gethostname(),
            wallet_fingerprint_hash=WALLET_HASH,
            network="mainnet",
            lease_expires_at=now + timedelta(minutes=5),
            now=now,
            expected_lease_version=0,
        )
        assert acquired["acquired"] is True
        database.close_connection()
        before = {
            item.name: item.read_bytes()
            for item in data_dir.iterdir()
            if item.is_file()
        }
        arbiter.release()

        selected_port, payload = _wait_for_any_diagnostics_status(
            process,
            _bounded_loopback_candidates(port, include_preferred=False),
        )
        assert selected_port != port
        assert payload["safety"]["reason_code"] == "LEASE_OWNED_BY_OTHER"
        after = {
            item.name: item.read_bytes()
            for item in data_dir.iterdir()
            if item.is_file()
        }
        assert after == before
    finally:
        arbiter.release()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        database.close_connection()


def test_diagnostics_server_never_constructs_bot_or_acquires_lease(monkeypatch):
    import read_only_diagnostics

    desktop_app = _import_desktop_app_without_rewrapping_pytest_streams(monkeypatch)

    calls = []
    reservation = SimpleNamespace(port=5017)
    monkeypatch.setattr(
        read_only_diagnostics,
        "serve",
        lambda **kwargs: calls.append(("minimal-serve", kwargs)),
    )

    desktop_app.run_read_only_diagnostics_mode(reservation)

    assert calls == [
        (
            "minimal-serve",
            {
                "reservation": reservation,
                "ready_callback": None,
                "lifetime_seconds": 300,
            },
        )
    ]


def test_standalone_diagnostics_server_is_database_read_only(monkeypatch):
    import api_server

    calls = []
    reservation = SimpleNamespace(port=5018, release=lambda: calls.append("release"))
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
        "_serve_flask_app_on_reservation",
        lambda supplied: calls.append(("serve", supplied)),
    )

    api_server._serve_read_only_diagnostics(reservation)

    assert calls == [
        ("initialize", {"start_heartbeat": False, "acquire_lease": False}),
        ("serve", reservation),
        "release",
    ]


def test_diagnostics_mode_exposes_only_bounded_safety_status(monkeypatch):
    import api_server

    denied = mutation_gate.GateStatus(
        allowed=False,
        reason_code="LEASE_OWNED_BY_OTHER",
        source="lease",
        lease_active=True,
        lease_version=9,
        lease_expires_at="2026-08-22T23:59:00.000000Z",
        owner_run_id="owner-run",
        owner_pid=456,
    )
    monkeypatch.setattr(api_server, "_read_only_diagnostics_active", True)
    monkeypatch.setattr(api_server.mutation_gate, "read_only_status", lambda: denied)
    monkeypatch.setattr(
        api_server,
        "_stability_startup_status",
        {
            "allowed": False,
            "reason_code": "LEASE_OWNED_BY_OTHER",
            "source": "startup_recovery",
            "failed_check": "lease",
            "checks": [
                {
                    "name": "lease",
                    "ok": False,
                    "reason_code": "LEASE_OWNED_BY_OTHER",
                    "source_age_seconds": 0,
                    "source": "durable_snapshot",
                    "blocker_counts": {},
                }
            ],
            "blocker_counts": {
                "operations": 0,
                "prepared_creations": 0,
                "submitted_cancels": 0,
                "contradictory_history": 0,
                "reservations": 0,
                "publication_claims": 0,
            },
        },
    )
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: ("f" * 64, "mainnet")
    )
    monkeypatch.setattr(api_server.database, "DB_PATH", __file__)
    monkeypatch.setattr(
        api_server.database,
        "get_stability_diagnostic_counts",
        lambda: {"registry": 0, "lineage": 0, "reserve": 0, "publication": 0},
    )
    client = api_server.app.test_client()

    safety = client.get("/api/safety/status", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    ordinary = client.get("/api/status", environ_base={"REMOTE_ADDR": "127.0.0.1"})

    assert safety.status_code == 200
    public_safety = safety.get_json()["safety"]
    assert public_safety["identity"]["lease_owner"] == "other_run"
    assert "owner_run_id" not in public_safety["lease"]
    assert "owner-run" not in json.dumps(public_safety, sort_keys=True)
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


def test_standalone_port_reservation_uses_atomic_bidirectional_selector(monkeypatch):
    import api_server
    import read_only_diagnostics

    monkeypatch.setenv("CATALYST_FLASK_PORT", "5123")
    calls = []
    reservation = SimpleNamespace(port=65534)
    monkeypatch.setattr(
        read_only_diagnostics,
        "reserve_loopback_port",
        lambda preferred, **kwargs: calls.append((preferred, kwargs)) or reservation,
    )

    assert api_server._configured_flask_port() == 5123
    assert api_server._reserve_standalone_server_port(65535) is reservation
    assert calls == [(65535, {"include_preferred": True})]
