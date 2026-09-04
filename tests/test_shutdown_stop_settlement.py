"""Shutdown must drain producers and reconcile a late cancellation before cancel-all."""

from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime, timezone
import threading

import pytest
from flask import Flask

import api_server  # Initialize the blueprint registration before importing its module.
from blueprints import bot as bot_routes


@pytest.mark.parametrize(
    "alive,settled", [(True, False), (False, False), (False, True)]
)
def test_shutdown_stop_waits_for_drain_and_exact_settlement(
    monkeypatch, alive, settled
):
    manager = SimpleNamespace(
        reconcile_pending_cancellation_once=Mock(return_value=settled)
    )
    bot = SimpleNamespace(stop=Mock(), offer_manager=manager)
    server = SimpleNamespace(
        bot=bot,
        events=SimpleNamespace(emit=Mock()),
        _shutdown_thread_refs=lambda _bot: [SimpleNamespace(is_alive=lambda: alive)],
    )
    monkeypatch.setattr(bot_routes, "_api_server", lambda: server)
    with Flask(__name__).test_request_context(
        "/api/bot/stop", method="POST", json={"settle_cancellations": True}
    ):
        response = bot_routes.api_bot_stop().get_json()
    assert response["success"] is True
    assert response["stopped"] is (not alive and settled)
    assert manager.reconcile_pending_cancellation_once.call_count == int(not alive)


def test_shutdown_stop_does_not_claim_success_on_inventory_error(monkeypatch):
    bot = SimpleNamespace(stop=Mock(), offer_manager=Mock())
    server = SimpleNamespace(
        bot=bot,
        events=SimpleNamespace(emit=Mock()),
        _shutdown_thread_refs=Mock(side_effect=RuntimeError("inventory unavailable")),
    )
    monkeypatch.setattr(bot_routes, "_api_server", lambda: server)
    with Flask(__name__).test_request_context(
        "/api/bot/stop", method="POST", json={"settle_cancellations": True}
    ):
        response = bot_routes.api_bot_stop().get_json()
    assert response["success"] is False and response["stopped"] is False


def test_native_stop_forwards_shutdown_reconciliation_mode(monkeypatch):
    from app_bridge import AppBridge

    calls = []

    def stop_handler():
        from flask import request, jsonify

        calls.append(request.get_json())
        return jsonify(success=True, stopped=True)

    monkeypatch.setattr(api_server, "api_bot_stop", stop_handler)
    bridge = object.__new__(AppBridge)
    result = bridge.stop_bot({"settle_cancellations": True})
    assert calls == [{"settle_cancellations": True}]
    assert result["stopped"] is True


@pytest.mark.parametrize(
    "changed",
    [
        None,
        "active",
        "owner_run_id",
        "owner_pid",
        "owner_host",
        "wallet_fingerprint_hash",
        "network",
        "lease_version",
        "acquired_at",
        "expires_at",
        "expired",
        "local_fence",
        "quiescing",
    ],
)
def test_reconciliation_lease_requires_current_incarnation(monkeypatch, changed):
    from mutation_gate import MutationGate

    gate = object.__new__(MutationGate)
    values = dict(
        run_id="run",
        owner_pid=123,
        owner_host="host",
        wallet_fingerprint_hash="wallet",
        network="mainnet",
    )
    for key, value in values.items():
        object.__setattr__(gate, key, value)
    gate._lock = threading.RLock()
    gate._lease_version = 4
    gate._lease_acquired_at = "2026-09-04T12:00:00Z"
    gate._local_reason_code = "UNRESOLVED_OPERATIONS"
    gate._quiescing = False
    gate._wallet_lifecycle_transitioning = False
    gate._now = lambda: datetime(2026, 9, 4, 12, 1, tzinfo=timezone.utc)
    lease = dict(
        active=1,
        owner_run_id="run",
        owner_pid=123,
        owner_host="host",
        wallet_fingerprint_hash="wallet",
        network="mainnet",
        lease_version=4,
        acquired_at=gate._lease_acquired_at,
        expires_at="2026-09-04T12:02:00Z",
    )
    if changed == "local_fence":
        gate._local_reason_code = "LEASE_LOST"
    elif changed == "quiescing":
        gate._quiescing = True
    elif changed == "expired":
        lease["expires_at"] = "2026-09-04T12:01:00Z"
    elif changed is not None:
        lease[changed] = 0 if changed == "active" else "wrong"
    gate._authorization_snapshot = lambda: {"lease": lease}
    assert gate.has_live_reconciliation_lease() is (changed is None)


def test_stop_during_retry_settlement_prevents_next_effect(monkeypatch):
    import database
    from offer_manager import OfferManager

    manager = object.__new__(OfferManager)
    manager._cancel_settlement_lock = threading.Lock()
    manager._cancel_settlement_operation_id = None
    manager._stop_requested = False
    manager._pending_cancel_retries = {}
    manager._bot_cancelled_ids = set()
    manager._max_cancel_retries = 4
    manager._cancel_retry_backoff_seconds = 0
    candidates = [
        dict(
            trade_id=letter * 64,
            operation_id="cancel:" + letter * 64,
            attempt=1,
            created_at="2026-01-01T00:00:00Z",
        )
        for letter in ("a", "b")
    ]
    monkeypatch.setattr(database, "get_unresolved_offer_operation_blockers", lambda: [])
    monkeypatch.setattr(
        database, "get_retryable_failed_offer_cancels", lambda: candidates
    )
    monkeypatch.setattr(database, "get_offer", lambda _tid: None)
    monkeypatch.setattr(
        manager,
        "_canonical_cancel_intent",
        lambda tid: SimpleNamespace(
            trade_id=tid, operation_id="cancel:" + tid, intent_id="intent:" + tid
        ),
    )
    monkeypatch.setattr(
        manager,
        "_existing_cancel_result",
        lambda _intent: {"outcome": "CANCEL_FAILED", "_catalyst_attempt": 1},
    )
    monkeypatch.setattr(
        manager, "_reconcile_elapsed_cancel_retry", lambda *_a, **_k: None
    )
    effects = []
    monkeypatch.setattr(
        manager,
        "cancel_offers",
        lambda ids, **_k: (
            effects.append(ids[0])
            or {ids[0]: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}}
        ),
    )

    def settle(_intent):
        manager._stop_requested = True
        return True

    monkeypatch.setattr(manager, "_settle_submitted_cancel", settle)
    assert manager.retry_failed_cancels() == 0
    assert effects == ["a" * 64]
    assert manager.get_active_cancel_settlement_operation() is None


def test_shutdown_stops_idle_runtime_monitor_before_drain(monkeypatch):
    import runtime_monitor

    # Endpoint tests may leave mocked worker references in API module state.
    # This fixture owns only the real monitor below; retain the real inventory
    # function while isolating unrelated global workers.
    for name in ("_coin_prep_thread", "_cancel_all_thread", "_boost_activation_thread"):
        monkeypatch.setattr(api_server, name, None)
    monkeypatch.setattr(api_server, "_background_mutation_threads", {})
    bot = SimpleNamespace(
        _running=False,
        stop=Mock(),
        offer_manager=SimpleNamespace(reconcile_pending_cancellation_once=lambda: True),
    )
    monitor = runtime_monitor.RuntimeMonitor(bot)
    monitor._enabled = True
    monkeypatch.setattr(monitor, "_sync_alert", lambda *_args: None)
    monkeypatch.setattr(runtime_monitor, "log_event", lambda *_args, **_kwargs: None)
    bot.runtime_monitor = monitor
    server = SimpleNamespace(
        bot=bot,
        events=SimpleNamespace(emit=Mock()),
        _shutdown_thread_refs=api_server._shutdown_thread_refs,
    )
    monkeypatch.setattr(bot_routes, "_api_server", lambda: server)
    monitor.start()
    thread = monitor._thread
    try:
        with Flask(__name__).test_request_context(
            "/api/bot/stop", method="POST", json={"settle_cancellations": True}
        ):
            response = bot_routes.api_bot_stop().get_json()
        assert response["stopped"] is True, (
            response,
            [(repr(t), t.is_alive()) for t in api_server._shutdown_thread_refs(bot)],
        )
        assert not thread.is_alive()
    finally:
        monitor.stop()


def test_runtime_monitor_stop_retains_unfinished_thread_handle():
    from runtime_monitor import RuntimeMonitor

    monitor = object.__new__(RuntimeMonitor)
    thread = SimpleNamespace(is_alive=lambda: True, join=Mock())
    monitor._thread = thread
    monitor._wake_event = threading.Event()
    monitor.stop()
    assert monitor._thread is thread
