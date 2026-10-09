"""Repost status must reflect each publisher's actual response."""

from types import SimpleNamespace

import pytest

import bot_loop
import database


@pytest.mark.parametrize(
    ("splash_result", "expected_success"),
    [
        ({"posted": 0, "failed": 1, "skipped": 0, "requeued": 1}, False),
        ({"posted": 0, "failed": 0, "skipped": 0, "requeued": 0}, False),
        (None, False),
        ({"posted": 1, "failed": 0, "skipped": 0, "requeued": 0}, True),
    ],
)
def test_repost_reports_local_splash_result_without_claiming_peer_delivery(
    monkeypatch, splash_result, expected_success
):
    events = []
    loop = object.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._enter_runtime_effect_phase = lambda _phase: True
    loop.offer_manager = SimpleNamespace(
        sync_from_wallet_with_meta=lambda: (
            ([{"trade_id": "offer-trade", "side": "buy"}], [], []),
            {"fresh": True, "using_cache": False},
        )
    )
    loop.dexie_manager = SimpleNamespace(
        queue_post=lambda *_args, **_kwargs: None,
        flush_queue=lambda **_kwargs: {
            "posted": 1,
            "failed": 0,
            "skipped": 0,
            "requeued": 0,
        },
    )
    loop.splash_manager = SimpleNamespace(
        queue_post=lambda *_args, **_kwargs: None,
        flush_queue=lambda **_kwargs: splash_result,
    )
    monkeypatch.setattr(bot_loop.cfg, "DEXIE_AUTO_POST", True)
    monkeypatch.setattr(bot_loop.cfg, "SPLASH_ENABLED", True)
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", "a" * 64)
    monkeypatch.setattr(
        database,
        "get_offers_for_repost",
        lambda **_kwargs: [
            {
                "trade_id": "offer-trade",
                "side": "buy",
                "offer_bech32": "offer1example",
                "dexie_id": None,
            }
        ],
    )
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda level, event, message, data=None: events.append(
            (level, event, message, data)
        ),
    )

    result = loop._repost_active_offers_to_dexie(reason="startup_resume")

    if expected_success:
        assert result is not False
        assert any(
            event == "splash_repost_done"
            and "local Splash node" in message
            and "peer delivery unverified" in message
            for _level, event, message, _data in events
        )
    else:
        assert result is False
        assert any(event == "splash_repost_failed" for _, event, _, _ in events)
        assert not any(event == "splash_repost_done" for _, event, _, _ in events)

    assert not any("Confirmed" in message for _, _, message, _ in events)


def test_failed_dexie_repost_does_not_claim_offers_were_posted(monkeypatch):
    events = []
    loop = object.__new__(bot_loop.BotLoop)
    loop._running = True
    loop._enter_runtime_effect_phase = lambda _phase: True
    loop.offer_manager = SimpleNamespace(
        sync_from_wallet_with_meta=lambda: (
            ([{"trade_id": "offer-trade", "side": "buy"}], [], []),
            {"fresh": True, "using_cache": False},
        )
    )
    loop.dexie_manager = SimpleNamespace(
        queue_post=lambda *_args, **_kwargs: None,
        flush_queue=lambda **_kwargs: {
            "posted": 0,
            "failed": 1,
            "skipped": 0,
            "requeued": 1,
        },
    )
    monkeypatch.setattr(bot_loop.cfg, "DEXIE_AUTO_POST", True)
    monkeypatch.setattr(bot_loop.cfg, "SPLASH_ENABLED", False)
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", "a" * 64)
    monkeypatch.setattr(
        database,
        "get_offers_for_repost",
        lambda **_kwargs: [
            {
                "trade_id": "offer-trade",
                "side": "buy",
                "offer_bech32": "offer1example",
                "dexie_id": None,
            }
        ],
    )
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda level, event, message, data=None: events.append(
            (level, event, message, data)
        ),
    )

    assert loop._repost_active_offers_to_dexie(reason="startup_resume") is False
    assert any(event == "dexie_repost_incomplete" for _, event, _, _ in events)
    assert not any(event == "dexie_repost_done" for _, event, _, _ in events)
