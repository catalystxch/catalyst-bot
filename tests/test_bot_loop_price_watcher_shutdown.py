def test_retired_tibetswap_price_watcher_exits_without_live_io(monkeypatch):
    import bot_loop

    watcher = object.__new__(bot_loop.BotLoop)
    calls = []
    watcher._fetch_tibet_reserves = lambda *_args: calls.append("tibet")
    events = []
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda level, event, message, **kwargs: events.append((level, event, message)),
    )

    watcher._price_watcher_thread()

    assert calls == []
    assert events == [
        (
            "info",
            "tibetswap_price_watcher_retired",
            "TibetSwap reserve watcher is retired in the offer-book market model",
        )
    ]


def test_retired_tibetswap_price_watcher_is_not_restarted_as_crashed(monkeypatch):
    import bot_loop

    class DeadThread:
        @staticmethod
        def is_alive():
            return False

    watcher = object.__new__(bot_loop.BotLoop)
    watcher._running = True
    watcher._health_thread = None
    watcher._watcher_thread = DeadThread()
    watcher._coin_watcher_thread = None
    watcher._splash_receive_thread = None
    watcher._start_health_monitor = lambda: None
    watcher._start_coin_watcher = lambda: None
    restarted = []
    watcher._start_price_watcher = lambda: restarted.append("price-watcher")
    watcher._emit_alert = lambda *_args, **_kwargs: None
    watcher._clear_alert = lambda *_args, **_kwargs: None
    events = []
    monkeypatch.setattr(bot_loop.cfg, "SPLASH_ENABLED", False)
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda level, event, message, **kwargs: events.append((level, event, message)),
    )

    watcher._check_background_thread_liveness()

    assert restarted == []
    assert not any(event == "background_thread_died" for _, event, _ in events)
