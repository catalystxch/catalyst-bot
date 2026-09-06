import threading


def test_price_watcher_interrupts_long_poll_delay_on_stop(monkeypatch):
    import bot_loop
    from config import cfg

    fetch_started = threading.Event()
    watcher = object.__new__(bot_loop.BotLoop)
    watcher._running = True
    watcher._startup_complete = threading.Event()
    watcher._startup_complete.set()
    watcher._watcher_stop_event = threading.Event()
    watcher._watcher_interval = 60
    watcher._watcher_min_change_pct = 0.03
    watcher._watcher_lock = threading.Lock()
    watcher._watcher_data = {
        "last_xch_reserve": 0,
        "last_token_reserve": 0,
        "triggered": False,
        "change_pct": 0.0,
        "direction": "",
        "last_change_ts": 0,
        "polls": 0,
        "triggers": 0,
    }
    watcher._bot_state = {"running": True}

    def no_tibet_pool(_session):
        fetch_started.set()
        return None, None

    watcher._fetch_tibet_reserves = no_tibet_pool
    monkeypatch.setattr(cfg, "CAT_ASSET_ID", "a" * 64, raising=False)
    monkeypatch.setattr(bot_loop, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot_loop, "log_thread_start", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot_loop, "slog", lambda *args, **kwargs: None)

    thread = threading.Thread(target=watcher._price_watcher_thread, daemon=True)
    thread.start()
    assert fetch_started.wait(timeout=1)

    watcher._running = False
    watcher._watcher_stop_event.set()
    thread.join(timeout=0.5)

    assert not thread.is_alive()
