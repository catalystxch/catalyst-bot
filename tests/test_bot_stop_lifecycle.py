import threading

import bot_loop


class _NoOp:
    def stop(self, *args, **kwargs):
        return None

    def stop_topup(self, *args, **kwargs):
        return None

    def set(self):
        return None

    def is_running(self):
        return False


def test_async_stop_finalizer_does_not_publish_stopped_while_cycle_is_alive(
    monkeypatch,
):
    joins = []
    states = []

    class SlowCycleThread:
        alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            joins.append(timeout)
            if timeout is None:
                self.alive = False

    cycle_thread = SlowCycleThread()
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._stop_finalize_lock = threading.Lock()
    loop._thread = cycle_thread
    loop.coin_manager = _NoOp()
    loop._watcher_stop_event = _NoOp()
    loop._watcher_event = _NoOp()
    loop.amm_monitor = _NoOp()
    loop._splash_receive_thread = None
    loop._health_thread = None
    loop._watcher_thread = None
    loop._coin_watcher_thread = None
    loop._startup_repost_thread = None
    loop.splash_node = _NoOp()
    loop._clear_alert = lambda _alert_id: None

    def record_state(**updates):
        if updates.get("status") == "stopped":
            assert not cycle_thread.is_alive()
        states.append(updates)

    loop._set_state = record_state
    monkeypatch.setattr(bot_loop, "_mempool_watcher_mod", None)
    monkeypatch.setattr(bot_loop, "log_event", lambda *args, **kwargs: None)

    loop._finalize_stop()

    assert joins == [30, None]
    assert states[-1] == {"running": False, "status": "stopped"}


def test_synchronous_stop_does_not_publish_stopped_while_cycle_is_alive(monkeypatch):
    joins = []
    states = []
    finalizers = []

    class SlowCycleThread:
        def is_alive(self):
            return True

        def join(self, timeout=None):
            joins.append(timeout)

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._stop_finalize_lock = threading.Lock()
    loop._stop_finalize_thread = None
    loop._thread = SlowCycleThread()
    loop.coin_manager = _NoOp()
    loop.offer_manager = type("OfferManager", (), {"_stop_requested": False})()
    loop._watcher_stop_event = _NoOp()
    loop._watcher_event = _NoOp()
    loop.amm_monitor = _NoOp()
    loop._splash_receive_thread = None
    loop._health_thread = None
    loop._watcher_thread = None
    loop._coin_watcher_thread = None
    loop._startup_repost_thread = None
    loop.splash_node = _NoOp()
    loop._clear_alert = lambda _alert_id: None
    loop._set_state = lambda **updates: states.append(updates)

    class DeferredFinalizer:
        def __init__(self, *, target, daemon, name):
            finalizers.append((target, daemon, name))

        def start(self):
            return None

        def is_alive(self):
            return False

    monkeypatch.setattr(bot_loop, "_mempool_watcher_mod", None)
    monkeypatch.setattr(bot_loop, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot_loop.threading, "Thread", DeferredFinalizer)

    stopped = loop.stop(wait=True)

    assert stopped is False
    assert joins == [30]
    assert {"running": False, "status": "stopped"} not in states
    assert states[-1] == {"running": False, "status": "stopping"}
    assert len(finalizers) == 1
