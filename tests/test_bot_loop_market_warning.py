from decimal import Decimal
from types import SimpleNamespace


def test_unchanged_missing_trusted_price_logs_one_warning_per_outage(monkeypatch):
    import bot_health
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._recovery_state = {}
    loop._runtime_recovery_cycle_boundary = lambda: True
    loop._set_cycle_step = lambda _step: None
    loop._process_authoritative_sweep_events = lambda: None
    loop.offer_manager = SimpleNamespace(clear_cycle_coins=lambda: None)
    loop._refresh_offer_book_market = lambda: SimpleNamespace(
        confidence=SimpleNamespace(
            trusted_midpoint=None,
            reason_codes=("insufficient_ask_depth", "single_provider_dependency"),
        )
    )

    events = []
    monkeypatch.setattr(bot_health, "run_runtime_checks", lambda **_kwargs: None)
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda level, event_type, message, **kwargs: events.append(
            (level, event_type, message, kwargs)
        ),
    )

    loop._run_one_cycle()
    loop._run_one_cycle()

    warnings = [
        event for event in events if event[1] == "market_confidence_no_trusted_price"
    ]
    assert len(warnings) == 1


def test_recovered_trusted_price_rearms_warning_for_later_outage(monkeypatch):
    import bot_health
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._recovery_state = {}
    loop._runtime_recovery_cycle_boundary = lambda: True
    loop._set_cycle_step = lambda _step: None
    loop._process_authoritative_sweep_events = lambda: None
    loop._cycle_stop_requested = lambda _step: True
    loop._set_state = lambda **_state: None
    loop.offer_manager = SimpleNamespace(clear_cycle_coins=lambda: None)
    market_results = iter(
        (
            SimpleNamespace(confidence=SimpleNamespace(trusted_midpoint=None)),
            SimpleNamespace(
                confidence=SimpleNamespace(trusted_midpoint=Decimal("0.001"))
            ),
            SimpleNamespace(confidence=SimpleNamespace(trusted_midpoint=None)),
        )
    )
    loop._refresh_offer_book_market = lambda: next(market_results)

    events = []
    monkeypatch.setattr(bot_health, "run_runtime_checks", lambda **_kwargs: None)
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda level, event_type, message, **kwargs: events.append(
            (level, event_type, message, kwargs)
        ),
    )

    loop._run_one_cycle()
    loop._run_one_cycle()
    loop._run_one_cycle()

    warnings = [
        event for event in events if event[1] == "market_confidence_no_trusted_price"
    ]
    assert len(warnings) == 2
