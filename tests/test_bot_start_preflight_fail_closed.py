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


def test_direct_bot_start_blocks_when_wallet_offer_read_turns_stale(monkeypatch):
    """The second start boundary protects the API-to-worker race."""
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
        _clear_alert=lambda _name: None,
        _fresh_wallet_offer_book_for_start=lambda: False,
        _watcher_stop_event=SimpleNamespace(
            clear=lambda: (_ for _ in ()).throw(
                AssertionError("stale wallet offers reached worker startup")
            )
        ),
    )
    monkeypatch.setattr(bot_loop.mutation_gate, "require_allowed", lambda *_: None)
    monkeypatch.setattr(bot_loop.cfg, "reload", lambda: None)
    monkeypatch.setattr(bot_loop, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        doctor,
        "run_preflight",
        lambda **_: SimpleNamespace(summary="Ready", duration_ms=1, can_start=True),
    )
    monkeypatch.setattr(wallet, "get_wallet_type", lambda: "chia")

    assert bot_loop.BotLoop.start(loop) is False
    assert states[-1]["status"] == "blocked"
    assert states[-1]["running"] is False


def test_direct_bot_start_requires_fresh_wallet_offer_metadata():
    manager = SimpleNamespace(
        sync_from_wallet=lambda: ([{"trade_id": "cached"}], [], []),
        get_wallet_sync_meta=lambda: {"fresh": False, "using_cache": True},
    )
    manager.sync_from_wallet_with_meta = lambda: (
        manager.sync_from_wallet(),
        manager.get_wallet_sync_meta(),
    )
    loop = SimpleNamespace(offer_manager=manager)
    assert bot_loop.BotLoop._fresh_wallet_offer_book_for_start(loop) is False
    manager.get_wallet_sync_meta = lambda: {"fresh": True, "using_cache": False}
    assert bot_loop.BotLoop._fresh_wallet_offer_book_for_start(loop) is True


def test_stale_wallet_cycle_does_not_run_fill_detection():
    calls = []
    loop = SimpleNamespace(
        _wallet_sync_stale_cycle=True,
        offer_manager=SimpleNamespace(_offer_details_cache={}),
        fill_tracker=SimpleNamespace(
            detect_fills=lambda *args: (
                calls.append(args)
                or {"buy_fills": [{"trade_id": "false-fill"}], "sell_fills": []}
            )
        ),
    )

    result = bot_loop.BotLoop._detect_fills_for_wallet_cycle(
        loop, {"cached-buy"}, set()
    )
    assert result == {"buy_fills": [], "sell_fills": []}
    assert calls == []

    loop._wallet_sync_stale_cycle = False
    result = bot_loop.BotLoop._detect_fills_for_wallet_cycle(loop, {"fresh-buy"}, set())
    assert result["buy_fills"][0]["trade_id"] == "false-fill"
    assert calls == [({"fresh-buy"}, set(), {})]
