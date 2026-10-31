"""A reserve-floor breach revokes Follow creation before cancellation."""

from types import SimpleNamespace

import bot_loop
import pytest


RUN_ID = "a" * 64
TRADE_ID = "b" * 64
NEW_TRADE_ID = "c" * 64


@pytest.fixture(autouse=True)
def reviewed_follow_identity(monkeypatch):
    monkeypatch.setattr(
        bot_loop.database,
        "get_follow_run_identity",
        lambda _run_id: {"network": "mainnet"},
    )


def _fake_loop(*, follow=True, stop_recorded=True, cancel_phase_allowed=True):
    calls = []

    class Loop:
        _reviewed_follow_run_id = RUN_ID if follow else None

        def _enter_runtime_effect_phase(self, phase):
            calls.append(("phase", phase))
            return cancel_phase_allowed

        def stop(self, *, wait):
            calls.append(("stop", wait))
            return True

        def _record_reviewed_follow_stop(self):
            calls.append(("record_stop",))
            return stop_recorded

    loop = Loop()
    loop.offer_manager = SimpleNamespace(
        wait_for_offer_creation_quiescence=lambda: calls.append(("quiesce",)),
        preview_follow_cancel_book=lambda cohorts, **_kwargs: {
            "cohorts": cohorts,
            "dispatch_authorized": False,
        },
        cancel_offers=lambda ids, **kwargs: calls.append(
            ("cancel", tuple(ids), kwargs["reason"])
        ),
    )
    return loop, calls


def test_follow_reserve_floor_stops_then_cancels_exact_current_run(monkeypatch):
    loop, calls = _fake_loop()
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "sage_trade_id": TRADE_ID,
                "lifecycle_state": "visible",
                "terminal_at": None,
            }
        ],
    )
    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, {TRADE_ID}) is False
    assert calls == [
        ("phase", "cancel"),
        ("stop", False),
        ("record_stop",),
        ("quiesce",),
        ("cancel", (TRADE_ID,), "reserve_floor_breached"),
    ]


def test_follow_reserve_floor_refuses_wallet_effect_without_durable_stop(monkeypatch):
    loop, calls = _fake_loop(stop_recorded=False)
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: (_ for _ in ()).throw(AssertionError("registry read")),
    )
    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, {TRADE_ID}) is False
    assert calls == [("phase", "cancel"), ("stop", False), ("record_stop",)]


def test_follow_reserve_floor_includes_offer_created_before_quiescence(monkeypatch):
    loop, calls = _fake_loop()
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "sage_trade_id": trade_id,
                "lifecycle_state": "visible",
                "terminal_at": None,
            }
            for trade_id in (TRADE_ID, NEW_TRADE_ID)
        ],
    )
    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, {TRADE_ID}) is False
    assert calls[-1] == (
        "cancel",
        (TRADE_ID, NEW_TRADE_ID),
        "reserve_floor_breached",
    )


def test_follow_reserve_floor_splits_oversized_48_book_and_proves_each_cohort(
    monkeypatch,
):
    loop, calls = _fake_loop()
    monkeypatch.setattr(
        bot_loop.database, "get_unresolved_offer_operation_blockers", lambda: []
    )
    trade_ids = [f"{index:064x}" for index in range(1, 49)]
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "sage_trade_id": trade_id,
                "lifecycle_state": "visible",
                "terminal_at": None,
            }
            for trade_id in trade_ids
        ],
    )
    proven = set()
    in_flight = set()
    effects = []

    def cancel(ids, **_kwargs):
        if len(ids) > 12:
            raise ValueError("FEE_CANCELLATION_BATCH_OVER_BLOCK_LIMIT")
        assert not in_flight, "next wallet effect preceded terminal proof"
        in_flight.update(ids)
        effects.append(tuple(ids))
        return {
            trade_id: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"} for trade_id in ids
        }

    def reconcile():
        proven.update(in_flight)
        in_flight.clear()
        return 0

    monkeypatch.setattr(loop.offer_manager, "cancel_offers", cancel)
    loop.offer_manager.reconcile_submitted_cancels_only = reconcile
    monkeypatch.setattr(
        bot_loop.database,
        "get_authoritative_terminal_records",
        lambda ids: {
            trade_id: {
                "sage_trade_id": trade_id,
                "outcome": "CANCELLED_PROVEN",
            }
            for trade_id in ids
            if trade_id in proven
        },
    )

    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, set(trade_ids)) is False
    assert len(effects) == 4
    assert all(len(cohort) == 12 for cohort in effects)
    assert set().union(*(set(cohort) for cohort in effects)) == set(trade_ids)
    assert proven == set(trade_ids)


def test_follow_reserve_floor_never_submits_second_cohort_without_first_proof(
    monkeypatch,
):
    loop, _calls = _fake_loop()
    monkeypatch.setattr(
        bot_loop.database, "get_unresolved_offer_operation_blockers", lambda: []
    )
    trade_ids = [f"{index:064x}" for index in range(1, 49)]
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "sage_trade_id": trade_id,
                "lifecycle_state": "visible",
                "terminal_at": None,
            }
            for trade_id in trade_ids
        ],
    )
    effects = []

    def cancel(ids, **_kwargs):
        if len(ids) > 12:
            raise ValueError("FEE_UNSIGNED_COST_UNAVAILABLE")
        effects.append(tuple(ids))
        return {
            trade_id: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"} for trade_id in ids
        }

    monkeypatch.setattr(loop.offer_manager, "cancel_offers", cancel)
    loop.offer_manager.reconcile_submitted_cancels_only = lambda: -1
    monkeypatch.setattr(
        bot_loop.database, "get_authoritative_terminal_records", lambda _ids: {}
    )
    ticks = iter([0.0, 301.0])
    monkeypatch.setattr(
        bot_loop,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _seconds: None),
    )

    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, set(trade_ids)) is False
    assert len(effects) == 1
    assert len(effects[0]) == 12


def test_follow_reserve_floor_does_not_split_with_unresolved_cancel(monkeypatch):
    loop, _calls = _fake_loop()
    trade_ids = [f"{index:064x}" for index in range(1, 49)]
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "sage_trade_id": trade_id,
                "lifecycle_state": "visible",
                "terminal_at": None,
            }
            for trade_id in trade_ids
        ],
    )
    attempts = []

    def cancel(ids, **_kwargs):
        attempts.append(tuple(ids))
        raise ValueError("FEE_UNSIGNED_COST_UNAVAILABLE")

    monkeypatch.setattr(loop.offer_manager, "cancel_offers", cancel)
    monkeypatch.setattr(
        bot_loop.database,
        "get_unresolved_offer_operation_blockers",
        lambda: [{"operation_id": "cancel:ambiguous"}],
    )

    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, set(trade_ids)) is False
    assert attempts == [tuple(sorted(trade_ids))]


@pytest.mark.parametrize("offer_count", [2, 12])
def test_follow_reserve_floor_splits_small_oversized_book(monkeypatch, offer_count):
    loop, _calls = _fake_loop()
    trade_ids = [f"{index:064x}" for index in range(1, offer_count + 1)]
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "sage_trade_id": trade_id,
                "lifecycle_state": "visible",
                "terminal_at": None,
            }
            for trade_id in trade_ids
        ],
    )
    monkeypatch.setattr(
        bot_loop.database, "get_unresolved_offer_operation_blockers", lambda: []
    )
    proven = set()
    effects = []

    def cancel(ids, **_kwargs):
        if len(ids) > 1:
            raise ValueError("FEE_CANCELLATION_BATCH_OVER_BLOCK_LIMIT")
        effects.append(tuple(ids))
        proven.update(ids)
        return {ids[0]: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}}

    monkeypatch.setattr(loop.offer_manager, "cancel_offers", cancel)
    loop.offer_manager.reconcile_submitted_cancels_only = lambda: 0
    monkeypatch.setattr(
        bot_loop.database,
        "get_authoritative_terminal_records",
        lambda ids: {
            trade_id: {
                "sage_trade_id": trade_id,
                "outcome": "CANCELLED_PROVEN",
            }
            for trade_id in ids
            if trade_id in proven
        },
    )

    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, set(trade_ids)) is False
    assert len(effects) == offer_count
    assert all(len(cohort) == 1 for cohort in effects)


def test_follow_reserve_floor_reports_known_pre_effect_failure_without_waiting(
    monkeypatch,
):
    loop, _calls = _fake_loop()
    trade_ids = [f"{index:064x}" for index in range(1, 49)]
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "sage_trade_id": trade_id,
                "lifecycle_state": "visible",
                "terminal_at": None,
            }
            for trade_id in trade_ids
        ],
    )
    monkeypatch.setattr(
        bot_loop.database, "get_unresolved_offer_operation_blockers", lambda: []
    )
    effects = []

    def cancel(ids, **_kwargs):
        if len(ids) > 12:
            raise ValueError("FEE_CANCELLATION_BATCH_OVER_BLOCK_LIMIT")
        effects.append(tuple(ids))
        return {
            trade_id: {
                "outcome": "CANCEL_FAILED",
                "submitted": False,
                "reconciliation_required": False,
            }
            for trade_id in ids
        }

    monkeypatch.setattr(loop.offer_manager, "cancel_offers", cancel)
    loop.offer_manager.reconcile_submitted_cancels_only = lambda: (_ for _ in ()).throw(
        AssertionError("known pre-effect failure must not wait for proof")
    )

    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, set(trade_ids)) is False
    assert len(effects) == 1


def test_follow_reserve_floor_requires_aggregate_fee_preview_before_effect(
    monkeypatch,
):
    loop, calls = _fake_loop()
    trade_ids = [f"{index:064x}" for index in range(1, 49)]
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "sage_trade_id": trade_id,
                "lifecycle_state": "visible",
                "terminal_at": None,
            }
            for trade_id in trade_ids
        ],
    )
    loop.offer_manager.preview_follow_cancel_book = lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(ValueError("FEE_BUDGET_EXCEEDED"))
    loop.offer_manager.cancel_offers = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("no wallet effect without aggregate fee proof")
    )

    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, set(trade_ids)) is False
    assert ("stop", False) in calls


def test_follow_reserve_floor_still_stops_when_cancel_phase_is_denied(monkeypatch):
    loop, calls = _fake_loop(cancel_phase_allowed=False)
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: (_ for _ in ()).throw(AssertionError("registry read")),
    )
    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, {TRADE_ID}) is False
    assert calls == [("phase", "cancel"), ("stop", False), ("record_stop",)]


def test_follow_reserve_floor_refuses_incomplete_book(monkeypatch):
    loop, calls = _fake_loop()
    monkeypatch.setattr(bot_loop.database, "get_offer_intents_for_registry", lambda: [])
    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, {TRADE_ID}) is False
    assert not any(call[0] == "cancel" for call in calls)


def test_legacy_reserve_floor_keeps_existing_cancel_behavior(monkeypatch):
    loop, calls = _fake_loop(follow=False)
    monkeypatch.setattr(
        bot_loop.database,
        "get_offer_intents_for_registry",
        lambda: (_ for _ in ()).throw(AssertionError("registry read")),
    )
    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, {TRADE_ID}) is True
    assert calls == [
        ("phase", "cancel"),
        ("cancel", (TRADE_ID,), "reserve_floor_breached"),
    ]


def test_legacy_reserve_floor_cancel_exception_prevents_offer_creation(monkeypatch):
    loop, calls = _fake_loop(follow=False)
    monkeypatch.setattr(
        loop.offer_manager,
        "cancel_offers",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cancel failed")),
    )
    assert bot_loop.BotLoop._cancel_reserve_floor_offers(loop, {TRADE_ID}) is False
    assert calls == [("phase", "cancel")]
