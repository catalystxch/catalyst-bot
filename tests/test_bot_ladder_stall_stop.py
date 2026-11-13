import time
from types import SimpleNamespace


def test_stalled_ladder_stops_coordinator_without_cancelling_offers(monkeypatch):
    import bot_loop
    from bot_loop import BotLoop
    from follow_run_coordinator import FollowRunCoordinator

    run_id = "a" * 64
    stopped = []
    thread = SimpleNamespace(
        name="create-sell",
        is_alive=lambda: True,
        _catalyst_start_at=time.time() - 300,
    )
    bot = SimpleNamespace(
        _ladder_threads=[thread],
        _reviewed_follow_run_id=run_id,
        _runtime_recovery_cycle_boundary=lambda: True,
        stop=lambda wait: stopped.append(("bot", wait)),
    )
    monkeypatch.setattr(
        bot_loop.mutation_gate,
        "read_only_status",
        lambda: SimpleNamespace(reason_code=None),
    )
    monkeypatch.setattr(bot_loop, "log_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        FollowRunCoordinator,
        "read_state",
        lambda _self: {
            "state": "running",
            "run_id": run_id,
            "session_id": "b" * 64,
            "policy_digest": "c" * 64,
            "configuration_sha256": "d" * 64,
        },
    )
    monkeypatch.setattr(
        FollowRunCoordinator,
        "stop_run",
        lambda _self, **kwargs: stopped.append(("coordinator", kwargs)),
    )

    assert BotLoop._run_one_cycle(bot) is False
    assert stopped == [
        ("bot", False),
        (
            "coordinator",
            {
                "session_id": "b" * 64,
                "policy_digest": "c" * 64,
                "configuration_sha256": "d" * 64,
            },
        ),
    ]
