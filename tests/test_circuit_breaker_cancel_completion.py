"""A submitted cancellation is not proof that a circuit breaker cleared offers."""

from types import SimpleNamespace
from unittest.mock import Mock

from bot_loop import BotLoop


def _bot_with_cancel_result(result):
    bot = SimpleNamespace(
        _circuit_breaker_offer_safed=False,
        risk_manager=SimpleNamespace(
            _circuit_breaker_reason="price outside corridor",
            get_circuit_breaker_blocked_side=lambda: None,
            is_full_halt=lambda: True,
        ),
        offer_manager=SimpleNamespace(cancel_all=Mock(return_value=result)),
        coin_manager=SimpleNamespace(snapshot_coins=Mock()),
        _enter_runtime_effect_phase=lambda _phase: True,
        _emit_coin_update=lambda _reason: None,
    )
    return bot


def test_submitted_cancel_does_not_mark_circuit_breaker_safed():
    bot = _bot_with_cancel_result(
        {"a" * 64: {"success": True, "outcome": "submitted_unconfirmed"}}
    )

    BotLoop._safeguard_offers_for_circuit_breaker(bot)

    assert bot._circuit_breaker_offer_safed is False


def test_proven_empty_inventory_marks_circuit_breaker_safed():
    bot = _bot_with_cancel_result({})

    BotLoop._safeguard_offers_for_circuit_breaker(bot)

    assert bot._circuit_breaker_offer_safed is True
