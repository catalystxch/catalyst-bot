"""Cancel-on-exit must settle each exact operation before another effect."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import database
import offer_manager
import offer_reconciliation
from offer_manager import OfferManager


@pytest.fixture
def manager(monkeypatch):
    manager = object.__new__(OfferManager)
    manager._cancel_settlement_lock = threading.Lock()
    manager._cancel_settlement_operation_id = None
    monkeypatch.setattr(
        manager,
        "_canonical_cancel_intent",
        lambda tid: SimpleNamespace(
            trade_id=tid, intent_id="intent:" + tid, operation_id="cancel:" + tid
        ),
    )
    monkeypatch.setattr(database, "get_authoritative_terminal_record", lambda tid: None)
    monkeypatch.setattr(database, "get_offer", lambda tid: None)
    return manager


def test_waits_for_each_confirmation_before_next_effect(manager, monkeypatch):
    calls = []

    def cancel(ids, **kwargs):
        calls.append(("submit", ids[0], kwargs.get("_retry_failed_attempts")))
        return {ids[0]: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}}

    def settle(intent, **kwargs):
        calls.append(("settle", intent.trade_id))
        return True

    monkeypatch.setattr(manager, "cancel_offers", cancel)
    monkeypatch.setattr(manager, "_settle_submitted_cancel", settle)
    progress = []
    result = manager.cancel_offers_and_settle(
        ["a", "b"],
        retry_failed_attempts={"b": 1},
        progress_callback=lambda **p: progress.append(p),
    )
    assert calls == [
        ("submit", "a", None),
        ("settle", "a"),
        ("submit", "b", {"b": 1}),
        ("settle", "b"),
    ]
    assert result["complete"] is True
    assert result["cancelled"] == 2 and result["pending"] == 0
    assert progress[-1]["cancelled"] == 2
    assert manager.get_active_cancel_settlement_operation() is None


@pytest.mark.parametrize(
    "outcome,settles",
    [
        ("CANCEL_SUBMITTED_UNCONFIRMED", False),
        ("CANCEL_UNKNOWN", False),
        ("CANCEL_FAILED", False),
        ("CANCEL_CONFIRMED", True),
    ],
)
def test_unproven_or_failed_result_never_reaches_next_offer(
    manager, monkeypatch, outcome, settles
):
    cancel = Mock(return_value={"a": {"outcome": outcome}})
    monkeypatch.setattr(manager, "cancel_offers", cancel)
    monkeypatch.setattr(manager, "_settle_submitted_cancel", Mock(return_value=settles))
    result = manager.cancel_offers_and_settle(["a", "b"])
    assert result["complete"] is False
    assert result["cancelled"] == 0
    assert result["remaining"] == 2
    assert cancel.call_count == 1
    assert manager.get_active_cancel_settlement_operation() is None


def test_exception_releases_settlement_lock_and_stops(manager, monkeypatch):
    monkeypatch.setattr(
        manager, "cancel_offers", Mock(side_effect=RuntimeError("private detail"))
    )
    result = manager.cancel_offers_and_settle(["a", "b"])
    assert result["complete"] is False
    assert "private detail" not in str(result)
    assert manager.get_active_cancel_settlement_operation() is None


@pytest.mark.parametrize("proof_after", [150, None])
def test_confirmed_batch_waits_for_late_proof_without_resubmitting(
    manager, monkeypatch, proof_after
):
    """Exercise the real settlement loop across the old 90-second cutoff."""
    clock = [0.0]
    current = [None]
    submitted = []
    applied = []
    monkeypatch.setattr(
        offer_manager,
        "time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            time=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        ),
    )
    monkeypatch.setattr(offer_manager.cfg, "CANCEL_MAX_WAIT_SECS", 90)
    monkeypatch.setattr(offer_manager.cfg, "CANCEL_POLL_INTERVAL_SECS", 5)
    monkeypatch.setattr(
        manager, "_reconcile_elapsed_cancel_retry", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        database,
        "get_runtime_safety_latch",
        lambda: {"state": "tripped", "generation": 1},
    )
    monkeypatch.setattr(
        database,
        "get_unresolved_offer_operation_blockers",
        lambda: [{"operation_id": "cancel:" + current[0]}],
    )
    monkeypatch.setattr(
        database, "get_offer_intent", lambda iid: {"sage_trade_id": iid.split(":")[1]}
    )

    def cancel(ids, **kwargs):
        current[0] = ids[0]
        submitted.append((ids[0], clock[0]))
        return {ids[0]: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}}

    monkeypatch.setattr(manager, "cancel_offers", cancel)
    monkeypatch.setattr(
        offer_reconciliation, "load_authoritative_evidence", lambda intent: {}
    )
    monkeypatch.setattr(
        offer_reconciliation, "_derive_single_cancel_context", lambda *a, **kw: {}
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "classify_terminal_evidence",
        lambda *a, **kw: {
            "classification": "CANCELLED_PROVEN"
            if proof_after is not None and clock[0] - submitted[-1][1] >= proof_after
            else "UNKNOWN"
        },
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "reconcile_offer",
        lambda iid, **kw: (
            applied.append(iid)
            or {"classification": "CANCELLED_PROVEN", "applied": True}
        ),
    )
    monkeypatch.setattr(
        offer_manager.mutation_gate,
        "current_runtime",
        lambda: SimpleNamespace(release_resolved=lambda *a: {"released": True}),
    )

    result = manager.cancel_offers_and_settle(["a", "b"])
    if proof_after is not None:
        assert result["complete"] is True
        assert submitted == [("a", 0), ("b", 150)]
        assert applied == ["intent:a", "intent:b"]
        assert result["resolved"] == 2
    else:
        assert result["complete"] is False and result["pending"] == 1
        assert submitted == [("a", 0)] and applied == []
        assert clock[0] == 600


def test_desktop_bridge_preserves_confirmation_mode(monkeypatch):
    import inspect
    import api_server
    from app_bridge import AppBridge
    from flask import request

    seen = []
    monkeypatch.setattr(
        api_server,
        "api_cancel_all",
        lambda: seen.append(request.get_json()) or {"success": True},
    )
    inspect.unwrap(AppBridge.cancel_all_offers)(
        object(), {"wait_for_confirmation": True}
    )
    assert seen == [{"wait_for_confirmation": True}]


@pytest.mark.parametrize("proven", [False, True])
def test_elapsed_member_is_reconciled_without_cancel_effect(
    manager, monkeypatch, proven
):
    cancel = Mock()
    monkeypatch.setattr(manager, "cancel_offers", cancel)
    monkeypatch.setattr(
        manager, "_reconcile_elapsed_cancel_retry", lambda *a, **kw: proven
    )
    proof = {
        "intent_id": "intent:a",
        "sage_trade_id": "a",
        "operation_id": "reconcile:intent:a",
        "outcome": "EXPIRED_PROVEN",
    }
    monkeypatch.setattr(
        database,
        "get_authoritative_terminal_record",
        Mock(side_effect=[None, proof] if proven else [None]),
    )
    result = manager.cancel_offers_and_settle(["a"])
    cancel.assert_not_called()
    assert result["complete"] is proven
    assert result["cancelled"] == 0
    if proven:
        assert result["resolved"] == 1 and result["closed"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"success": False, "offers": []},
        {"success": False, "error": "", "offers": []},
        {"error": "unavailable", "offers": []},
    ],
)
def test_sage_failed_empty_response_has_no_end_authority(monkeypatch, payload):
    import wallet_sage

    monkeypatch.setattr(wallet_sage, "rpc", lambda *a, **kw: payload)
    result = wallet_sage.get_authoritative_offer_history(
        include_completed=False, end=500
    )
    assert result["success"] is False
    assert result["end_of_history"] is False
