"""An unfinished ladder wallet call must finish before the next cycle begins."""

import bot_loop


class _UnfinishedLadder:
    name = "create-sell"
    _catalyst_start_at = 0

    def is_alive(self):
        return True


def test_next_cycle_waits_for_unfinished_ladder_before_wallet_sync():
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._recovery_state = {}
    loop._ladder_threads = [_UnfinishedLadder()]
    loop._runtime_recovery_cycle_boundary = lambda: True
    loop._set_cycle_step = lambda step: (_ for _ in ()).throw(
        AssertionError(f"cycle entered {step} before ladder thread completed")
    )

    assert loop._run_one_cycle() is False


def test_stalled_ladder_stops_bot_before_wallet_sync(monkeypatch):
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._recovery_state = {}
    thread = _UnfinishedLadder()
    thread._catalyst_start_at = 100
    loop._ladder_threads = [thread]
    loop._runtime_recovery_cycle_boundary = lambda: True
    calls = []
    loop.stop = lambda wait=False: calls.append(wait) or True
    loop._set_cycle_step = lambda step: (_ for _ in ()).throw(
        AssertionError(f"cycle entered {step} with a stalled ladder")
    )
    monkeypatch.setattr(bot_loop.time, "time", lambda: 340)

    assert loop._run_one_cycle() is False
    assert calls == [False]
