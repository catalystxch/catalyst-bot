"""A proven cancellation latch must open a fenced native review, not trading."""

import importlib
import json
import os
import socket
import sys
from types import SimpleNamespace

import pytest


def _desktop(monkeypatch):
    original_platform = sys.platform
    monkeypatch.setattr(sys, "platform", "linux")
    sys.modules.pop("desktop_app", None)
    module = importlib.import_module("desktop_app")
    monkeypatch.setattr(sys, "platform", original_platform)
    return module


def test_cancel_latch_startup_skips_legacy_auto_release(monkeypatch):
    import api_server
    import database

    desktop = _desktop(monkeypatch)
    blocked = {
        "allowed": False,
        "failed_check": "unresolved_operations",
        "reason_code": "UNRESOLVED_OPERATIONS",
    }
    recovered = []
    monkeypatch.setattr(database, "init_database", lambda: None)
    monkeypatch.setattr(desktop, "_retire_expired_dead_startup_lease", lambda: None)
    monkeypatch.setattr(api_server, "initialize_mutation_runtime", lambda: blocked)
    monkeypatch.setattr(
        api_server,
        "has_exact_cancel_latch_review_startup_candidate",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        api_server,
        "recover_legacy_startup_reservations",
        lambda: recovered.append(True) or {"recovered": 2, "remaining": 0},
    )

    assert desktop._initialize_startup_ownership() == blocked
    assert recovered == []


def test_cancel_latch_startup_routes_to_restricted_owner(monkeypatch):
    import api_server
    import database
    import read_only_diagnostics

    desktop = _desktop(monkeypatch)
    blocked = {"allowed": False, "reason_code": "UNRESOLVED_OPERATIONS"}
    events = []

    class Arbiter:
        acquired = True

        def release(self):
            events.append("arbiter_release")

    monkeypatch.setattr(read_only_diagnostics, "acquire_startup_arbiter", Arbiter)
    monkeypatch.setattr(
        read_only_diagnostics, "preflight_requires_diagnostics", lambda: False
    )
    monkeypatch.setattr(desktop, "_acquire_instance_lock", lambda: True)
    monkeypatch.setattr(database, "attempt_db_recovery", lambda: {"action": "ok"})
    monkeypatch.setattr(desktop, "_initialize_startup_ownership", lambda: blocked)
    monkeypatch.setattr(
        api_server,
        "activate_cancel_latch_review_restricted_startup",
        lambda authorization: events.append(("cancel_review", authorization)) or True,
        raising=False,
    )

    assert desktop._authorize_desktop_startup() is True
    assert events == [("cancel_review", blocked), "arbiter_release"]


def test_cancel_latch_restricted_view_has_no_trading_bridge_or_routes(monkeypatch):
    import api_server

    desktop = _desktop(monkeypatch)
    monkeypatch.setattr(
        api_server, "_cancel_latch_review_recovery_active", True, raising=False
    )
    assert desktop._create_desktop_bridge() is None
    for method, path in (
        ("GET", "/api/offers"),
        ("POST", "/api/bot/start"),
        ("POST", "/api/offers/cancel_all"),
        ("POST", "/api/safety/release-resolved"),
    ):
        with api_server.app.test_request_context(
            path, method=method, environ_base={"REMOTE_ADDR": "127.0.0.1"}
        ):
            response = api_server.enforce_local_runtime_guard()
            assert response is not None
            assert response[1] == 423
    with api_server.app.test_request_context(
        "/", headers={api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}
    ):
        response = api_server.serve_gui()
    assert response.status_code == 200
    assert b"Confirm database-only latch release" in response.data
    assert b"Start Bot" not in response.data


def test_cancel_latch_candidate_requires_only_exact_cancel_blockers(monkeypatch):
    import api_server
    import mutation_gate

    fingerprint = 3702373391
    wallet_hash = mutation_gate.wallet_fingerprint_hash(fingerprint)
    latch = {
        "state": "tripped",
        "reason_code": "UNRESOLVED_OPERATIONS",
        "generation": 154,
        "wallet_fingerprint_hash": wallet_hash,
        "network": "mainnet",
        "blocking_operation_ids_json": json.dumps(
            ["cancel:" + "a" * 64, "cancel:" + "b" * 64]
        ),
    }
    monkeypatch.setattr(api_server.database, "get_runtime_safety_latch", lambda: latch)
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: (wallet_hash, "mainnet")
    )
    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage", raising=False)
    assert api_server.has_exact_cancel_latch_review_startup_candidate() is True

    latch["blocking_operation_ids_json"] = json.dumps(
        ["cancel:" + "a" * 64, "create:" + "b" * 64]
    )
    assert api_server.has_exact_cancel_latch_review_startup_candidate() is False


@pytest.mark.parametrize("post_match", [True, False])
def test_cancel_latch_restricted_owner_rechecks_proof_after_lease(
    monkeypatch, post_match
):
    import api_server
    import cancel_latch_review
    import mutation_gate

    fingerprint = 3702373391
    wallet_hash = mutation_gate.wallet_fingerprint_hash(fingerprint)
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Harvestr test wallet",
        fingerprint=fingerprint,
        network_id="mainnet",
        kind="private",
        has_secrets=True,
        bound_at_utc="2026-10-22T12:00:00Z",
        maximum_age_seconds=60,
    )
    events = []
    state = {"owned": False, "digest": "a" * 64}
    runtime = SimpleNamespace(
        run_id="review-run",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        _lease_acquired_at="2026-10-22T12:00:00Z",
        last_acquire_result={"acquired": False},
        register_stop_handler=lambda _handler: events.append("register"),
        start_heartbeat=lambda: events.append("heartbeat") or True,
    )
    runtime.status = lambda: SimpleNamespace(
        to_dict=lambda: {
            "allowed": False,
            "reason_code": "UNRESOLVED_OPERATIONS",
            "source": "durable_latch",
            "lease": {
                "active": state["owned"],
                "owned_by_this_run": state["owned"],
                "owner_run_id": runtime.run_id,
                "version": 8,
            },
        }
    )
    monkeypatch.setattr(api_server, "_cancel_latch_review_recovery_active", False)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_mutation_runtime", None)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(
        api_server, "has_exact_cancel_latch_review_startup_candidate", lambda: True
    )
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: (wallet_hash, "mainnet")
    )
    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", lambda _network: binding
    )
    monkeypatch.setattr(api_server, "get_wallet_adapter_authority", object)

    def initialize(**kwargs):
        events.append("acquire" if kwargs["acquire_lease"] else "inspect")
        if kwargs["acquire_lease"]:
            state["owned"] = True
            runtime.last_acquire_result = {"acquired": True}
            if not post_match:
                state["digest"] = "b" * 64
        return runtime

    monkeypatch.setattr(mutation_gate, "initialize", initialize)
    monkeypatch.setattr(
        mutation_gate,
        "shutdown_runtime",
        lambda **kwargs: events.append(("shutdown", kwargs["release_owned_lease"])),
    )
    monkeypatch.setattr(
        api_server.database,
        "get_runtime_mutation_lease",
        lambda: {
            "active": 1,
            "owner_run_id": runtime.run_id,
            "owner_pid": runtime.owner_pid,
            "owner_host": runtime.owner_host,
            "acquired_at": runtime._lease_acquired_at,
            "lease_version": 8,
        },
    )

    def review(*, bot):
        events.append("review")
        return {
            "ready": True,
            "generation": 154,
            "operation_ids": ["cancel:" + "a" * 64, "cancel:" + "b" * 64],
            "review_digest": state["digest"],
        }

    monkeypatch.setattr(cancel_latch_review, "review", review)
    blocked = {"allowed": False, "reason_code": "UNRESOLVED_OPERATIONS"}
    assert (
        api_server.activate_cancel_latch_review_restricted_startup(blocked)
        is post_match
    )
    assert events[:4] == ["inspect", "review", "acquire", "review"]
    assert ("heartbeat" in events) is post_match
    assert api_server._cancel_latch_review_recovery_active is post_match
    if not post_match:
        assert ("shutdown", True) in events


def test_cancel_latch_restricted_owner_rejects_ineligible_latch(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "_cancel_latch_review_recovery_active", False)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(
        api_server, "has_exact_cancel_latch_review_startup_candidate", lambda: False
    )
    assert (
        api_server.activate_cancel_latch_review_restricted_startup(
            {"allowed": False, "reason_code": "UNRESOLVED_OPERATIONS"}
        )
        is False
    )
