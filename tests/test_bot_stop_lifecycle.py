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

    class CooldownSplash(_NoOp):
        _running = True
        stopped = False

        def stop(self):
            self.stopped = True

    loop.splash_node = CooldownSplash()
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
    assert loop.splash_node.stopped is True


def _loop_with_unstoppable_splash(monkeypatch):
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._stop_finalize_lock = threading.Lock()
    loop._stop_finalize_thread = None
    loop._thread = None
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

    class UnstoppableSplash:
        def is_running(self):
            return True

        def stop(self):
            return False

    loop.splash_node = UnstoppableSplash()
    states = []
    events = []
    loop._set_state = lambda **updates: states.append(updates)
    loop._clear_alert = lambda _alert_id: None
    monkeypatch.setattr(bot_loop, "_mempool_watcher_mod", None)
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda _level, event, _message, **_kwargs: events.append(event),
    )
    return loop, states, events


def test_synchronous_stop_stays_incomplete_when_splash_child_survives(monkeypatch):
    loop, states, events = _loop_with_unstoppable_splash(monkeypatch)

    assert loop.stop(wait=True) is False
    assert states[-1]["status"] == "stopping"
    assert "bot_stopped" not in events


def test_async_stop_stays_incomplete_when_splash_child_survives(monkeypatch):
    loop, states, events = _loop_with_unstoppable_splash(monkeypatch)
    loop._running = False

    loop._finalize_stop()

    assert states[-1]["status"] == "stopping"
    assert "bot_stopped" not in events


def test_stop_retries_transient_splash_failure(monkeypatch):
    loop, states, _events = _loop_with_unstoppable_splash(monkeypatch)
    loop._state_lock = threading.Lock()
    loop._bot_state = {"status": "running"}
    loop._set_state = lambda **updates: (
        loop._bot_state.update(updates),
        states.append(updates),
    )
    attempts = []

    def stop_splash():
        attempts.append(True)
        return len(attempts) > 1

    loop.splash_node.stop = stop_splash
    assert loop.stop(wait=True) is False
    assert loop._bot_state["status"] == "stopping"
    assert loop.stop(wait=True) is True
    assert attempts == [True, True]
    assert loop._bot_state["status"] == "stopped"


def test_sync_stop_stays_incomplete_when_splash_manager_survives(monkeypatch):
    loop, states, events = _loop_with_unstoppable_splash(monkeypatch)

    class AliveManager:
        def is_alive(self):
            return True

    loop.splash_node._running = False
    loop.splash_node._thread = AliveManager()
    loop.splash_node.is_running = lambda: False

    assert loop.stop(wait=True) is False
    assert states[-1]["status"] == "stopping"
    assert "bot_stopped" not in events


def test_stopping_bot_exposes_retry_only_after_failed_finalizer_exits():
    """A finished failed stop must be retryable without reopening Start."""
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = False
    loop._state_lock = threading.Lock()
    loop._bot_state = {"running": False, "status": "stopping"}

    class Finalizer:
        alive = True

        def is_alive(self):
            return self.alive

    finalizer = Finalizer()
    loop._stop_finalize_thread = finalizer

    assert hasattr(loop, "stop_retry_available")
    assert loop.stop_retry_available() is False
    finalizer.alive = False
    assert loop.stop_retry_available() is True
    loop._bot_state["status"] = "stopped"
    assert loop.stop_retry_available() is False
