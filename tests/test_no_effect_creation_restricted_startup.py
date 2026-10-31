"""An unresolved creation opens only the exact local proof review."""

import importlib
import json
import os
import socket
import sys
from types import SimpleNamespace


def _desktop(monkeypatch):
    original_platform = sys.platform
    monkeypatch.setattr(sys, "platform", "linux")
    sys.modules.pop("desktop_app", None)
    module = importlib.import_module("desktop_app")
    monkeypatch.setattr(sys, "platform", original_platform)
    return module


def test_candidate_requires_one_exact_creation(monkeypatch):
    import api_server
    import database

    operation = "create:" + "a" * 64
    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: ("wallet", "mainnet")
    )
    monkeypatch.setattr(
        database,
        "get_runtime_safety_latch",
        lambda: {
            "state": "tripped",
            "reason_code": "UNRESOLVED_OPERATIONS",
            "wallet_fingerprint_hash": "wallet",
            "network": "mainnet",
            "blocking_operation_ids_json": json.dumps([operation]),
        },
    )
    blockers = [{"operation_id": operation}]
    monkeypatch.setattr(
        database, "get_unresolved_offer_operation_blockers", lambda: blockers
    )
    monkeypatch.setattr(
        database,
        "validate_offer_operation_event",
        lambda _id: {
            "operation_type": "CREATE",
            "outcome": "UNKNOWN",
            "blocks_mutation": 1,
        },
    )
    monkeypatch.setattr(
        database,
        "get_offer_intent",
        lambda _id: {
            "lifecycle_state": "creation_unknown",
            "sage_trade_id": None,
            "wallet_fingerprint_hash": "wallet",
            "network": "mainnet",
        },
    )
    assert api_server.has_exact_no_effect_creation_startup_candidate() is True
    blockers.append({"operation_id": "create:" + "b" * 64})
    assert api_server.has_exact_no_effect_creation_startup_candidate() is False


def test_restricted_window_fences_http_and_bridge(monkeypatch):
    import api_server

    desktop = _desktop(monkeypatch)
    monkeypatch.setattr(api_server, "_no_effect_creation_recovery_active", True)
    bridge = desktop._create_desktop_bridge()
    assert callable(bridge.preview_no_effect_creation)
    assert callable(bridge.commit_no_effect_creation)
    assert not hasattr(bridge, "start_bot")
    assert not hasattr(bridge, "cancel_all")
    for method, path in (
        ("POST", "/api/bot/start"),
        ("POST", "/api/offers/cancel_all"),
    ):
        with api_server.app.test_request_context(
            path, method=method, environ_base={"REMOTE_ADDR": "127.0.0.1"}
        ):
            response = api_server.enforce_local_runtime_guard()
        assert response[1] == 423
    with api_server.app.test_request_context(
        "/", headers={api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}
    ):
        response = api_server.serve_gui()
    assert response.status_code == 200
    assert b"Confirm database-only recovery" in response.data


def test_restricted_startup_does_not_request_trading_authorization(monkeypatch):
    import api_server

    desktop = _desktop(monkeypatch)
    monkeypatch.setattr(api_server, "_no_effect_creation_recovery_active", True)

    def forbidden():
        raise AssertionError("restricted recovery must not initialize normal trading")

    monkeypatch.setattr(api_server, "initialize_mutation_runtime", forbidden)
    monkeypatch.setattr(api_server, "_start_owned_runtime_services", forbidden)
    desktop._start_owned_runtime_services()


def test_desktop_routes_exact_creation_to_restricted_owner(monkeypatch):
    import api_server
    import database
    import read_only_diagnostics

    desktop = _desktop(monkeypatch)
    blocked = {"allowed": False, "reason_code": "UNRESOLVED_OPERATIONS"}
    calls = []

    class Arbiter:
        acquired = True

        def release(self):
            calls.append("release")

    monkeypatch.setattr(read_only_diagnostics, "acquire_startup_arbiter", Arbiter)
    monkeypatch.setattr(
        read_only_diagnostics, "preflight_requires_diagnostics", lambda: False
    )
    monkeypatch.setattr(desktop, "_acquire_instance_lock", lambda: True)
    monkeypatch.setattr(database, "attempt_db_recovery", lambda: {"action": "ok"})
    monkeypatch.setattr(desktop, "_initialize_startup_ownership", lambda: blocked)
    monkeypatch.setattr(
        api_server, "activate_refresh_abort_restricted_startup", lambda _a: False
    )
    monkeypatch.setattr(
        api_server, "activate_cancel_latch_review_restricted_startup", lambda _a: False
    )
    monkeypatch.setattr(
        api_server,
        "activate_no_effect_creation_restricted_startup",
        lambda a: calls.append(("creation", a)) or True,
    )
    assert desktop._authorize_desktop_startup() is True
    assert calls == [("creation", blocked), "release"]


def test_restricted_owner_requires_complete_proof_and_keeps_latch(monkeypatch):
    import api_server
    import creation_no_effect_recovery
    import mutation_gate

    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Test wallet",
        fingerprint=736588221,
        network_id="mainnet",
        kind="private",
        has_secrets=True,
        bound_at_utc="2026-10-31T22:00:00Z",
        maximum_age_seconds=60,
    )
    events = []
    runtime = SimpleNamespace(
        run_id="exact-review",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        last_acquire_result={"acquired": True},
        register_stop_handler=lambda _handler: events.append("stop_handler"),
        start_heartbeat=lambda: events.append("heartbeat") or True,
    )
    runtime.status = lambda: SimpleNamespace(
        to_dict=lambda: {
            "allowed": False,
            "reason_code": "UNRESOLVED_OPERATIONS",
            "source": "durable_latch",
            "lease": {"owned_by_this_run": True},
        }
    )
    monkeypatch.setattr(api_server, "_no_effect_creation_recovery_active", False)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(
        api_server, "has_exact_no_effect_creation_startup_candidate", lambda: True
    )
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: ("wallet", "mainnet")
    )
    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", lambda _network: binding
    )
    monkeypatch.setattr(api_server, "get_wallet_adapter_authority", object)
    monkeypatch.setattr(mutation_gate, "initialize", lambda **_kw: runtime)
    monkeypatch.setattr(
        mutation_gate,
        "shutdown_runtime",
        lambda **kwargs: events.append(("shutdown", kwargs["release_owned_lease"])),
    )
    monkeypatch.setattr(
        creation_no_effect_recovery,
        "collect_no_effect_creation_proof",
        lambda: events.append("proof") or {"proof_digest": "a" * 64},
    )
    blocked = {"allowed": False, "reason_code": "UNRESOLVED_OPERATIONS"}
    assert api_server.activate_no_effect_creation_restricted_startup(blocked) is True
    assert events == ["proof", "stop_handler", "heartbeat"]
    assert api_server._no_effect_creation_recovery_active is True


def test_restricted_owner_refuses_failed_proof(monkeypatch):
    import api_server
    import creation_no_effect_recovery
    import mutation_gate

    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Test wallet",
        fingerprint=736588221,
        network_id="mainnet",
        kind="private",
        has_secrets=True,
        bound_at_utc="2026-10-31T22:00:00Z",
        maximum_age_seconds=60,
    )
    events = []
    runtime = SimpleNamespace(last_acquire_result={"acquired": True})
    runtime.status = lambda: SimpleNamespace(
        to_dict=lambda: {
            "reason_code": "UNRESOLVED_OPERATIONS",
            "source": "durable_latch",
            "lease": {"owned_by_this_run": True},
        }
    )
    monkeypatch.setattr(api_server, "_no_effect_creation_recovery_active", False)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(
        api_server, "has_exact_no_effect_creation_startup_candidate", lambda: True
    )
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: ("wallet", "mainnet")
    )
    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", lambda _network: binding
    )
    monkeypatch.setattr(api_server, "get_wallet_adapter_authority", object)
    monkeypatch.setattr(mutation_gate, "initialize", lambda **_kw: runtime)
    monkeypatch.setattr(
        mutation_gate,
        "shutdown_runtime",
        lambda **kwargs: events.append(("shutdown", kwargs["release_owned_lease"])),
    )

    def reject_proof():
        assert api_server._no_effect_creation_recovery_active is True
        raise ValueError("Sage proof unavailable")

    monkeypatch.setattr(
        creation_no_effect_recovery, "collect_no_effect_creation_proof", reject_proof
    )
    assert (
        api_server.activate_no_effect_creation_restricted_startup(
            {"allowed": False, "reason_code": "UNRESOLVED_OPERATIONS"}
        )
        is False
    )
    assert api_server._no_effect_creation_recovery_active is False
    assert events == [("shutdown", True)]
