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


def test_active_bootstrap_campaign_uses_its_bound_anchor_when_market_has_no_trusted_price(
    monkeypatch,
):
    import bot_health
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._recovery_state = {}
    loop._runtime_recovery_cycle_boundary = lambda: True
    loop._set_cycle_step = lambda _step: None
    loop._process_authoritative_sweep_events = lambda: None
    cycle_stop_steps = []
    loop._cycle_stop_requested = lambda step: cycle_stop_steps.append(step) or (
        step == "price_fetch"
    )
    loop.offer_manager = SimpleNamespace(clear_cycle_coins=lambda: None)
    loop._refresh_offer_book_market = lambda: SimpleNamespace(
        confidence=SimpleNamespace(
            trusted_midpoint=None,
            reason_codes=("insufficient_ask_depth", "single_provider_dependency"),
        )
    )
    loop._bootstrap_campaign_context = lambda: {
        "active": True,
        "blocked": False,
        "campaign": {
            "current_anchor_price": "0.0001",
            "minimum_price": "0.00005",
            "maximum_price": "0.0002",
        },
    }

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

    assert "price_fetch" in cycle_stop_steps
    assert loop._market_no_trusted_price_warned is False
    assert not [
        event for event in events if event[1] == "market_confidence_no_trusted_price"
    ]
    assert [event for event in events if event[1] == "bootstrap_anchor_price_active"]


def test_startup_requote_baseline_uses_active_bootstrap_anchor_when_book_is_red(
    monkeypatch,
):
    """A resumed Bootstrap book must not start with a false zero-price warning."""

    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._last_quoted_price = {"buy": Decimal("0"), "sell": Decimal("0")}
    loop._last_quoted_plain_mid = {"buy": Decimal("0"), "sell": Decimal("0")}
    loop._current_mid_price = Decimal("0")
    loop._probe_lock = __import__("threading").Lock()
    loop._probe_state = {"confirmed_price": None}
    loop._refresh_offer_book_market = lambda: SimpleNamespace(
        confidence=SimpleNamespace(trusted_midpoint=None)
    )
    loop._bootstrap_campaign_context = lambda: {
        "active": True,
        "blocked": False,
        "campaign": {
            "current_anchor_price": "0.0001",
            "minimum_price": "0.00005",
            "maximum_price": "0.0002",
        },
    }

    events = []
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda level, event_type, message, **kwargs: events.append(
            (level, event_type, message, kwargs)
        ),
    )

    loop._set_startup_requote_baseline()

    assert loop._last_quoted_price == {
        "buy": Decimal("0.0001"),
        "sell": Decimal("0.0001"),
    }
    assert loop._last_quoted_plain_mid == {
        "buy": Decimal("0.0001"),
        "sell": Decimal("0.0001"),
    }
    assert loop._current_mid_price == Decimal("0.0001")
    assert loop._probe_state["confirmed_price"] == Decimal("0.0001")
    assert not [event for event in events if event[1] == "startup_baseline_zero"]
    assert [event for event in events if event[1] == "startup_bootstrap_baseline_price"]
