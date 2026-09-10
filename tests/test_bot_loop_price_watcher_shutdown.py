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
