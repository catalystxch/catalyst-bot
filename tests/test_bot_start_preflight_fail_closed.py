"""Unexpected startup diagnostics must never admit a trading loop."""

from types import SimpleNamespace

import bot_loop
import pytest


@pytest.mark.parametrize("failure_stage", ["preflight", "signing_fallback"])
def test_bot_start_blocks_when_signing_readiness_cannot_be_proven(
    monkeypatch, failure_stage
):
    import doctor
    import wallet

    states = []
    loop = SimpleNamespace(
        _running=False,
        _stop_finalize_thread=None,
        _set_state=lambda **state: states.append(state),
        _reset_runtime_state=lambda: None,
        _establish_runtime_recovery_baseline=lambda: True,
        _restore_authoritative_sweep_downstream_effects=lambda: None,
        runtime_monitor=SimpleNamespace(reset_session=lambda: None),
        _recovery_state={},
        _clear_alert=lambda name: None,
        _watcher_stop_event=SimpleNamespace(
            clear=lambda: (_ for _ in ()).throw(
                AssertionError("trading startup reached")
            )
        ),
    )
    monkeypatch.setattr(bot_loop.mutation_gate, "require_allowed", lambda *_: None)
    monkeypatch.setattr(bot_loop.cfg, "reload", lambda: None)
    monkeypatch.setattr(bot_loop, "log_event", lambda *args, **kwargs: None)
    if failure_stage == "preflight":
        monkeypatch.setattr(doctor, "run_preflight", lambda **_: 1 / 0)
    else:
        monkeypatch.setattr(
            doctor,
            "run_preflight",
            lambda **_: SimpleNamespace(summary="Ready", duration_ms=1, can_start=True),
        )
    monkeypatch.setattr(wallet, "get_wallet_type", lambda: "sage")
    if failure_stage == "preflight":
        monkeypatch.setattr(wallet, "get_current_key", lambda: {"has_secrets": True})
    else:
        monkeypatch.setattr(wallet, "get_current_key", lambda: 1 / 0)

    assert bot_loop.BotLoop.start(loop) is False
    assert loop._running is False
    assert states[-1]["status"] == "blocked"
