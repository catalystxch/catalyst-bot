"""Regression coverage for the runtime ladder watchdog's live target."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import bot_loop
import config
import database
import ladder_watchdog


def test_watchdog_audits_the_effective_adaptive_target(monkeypatch):
    """A healthy capacity-capped book must not be compared with its ceiling."""

    rows = [
        {
            "trade_id": f"trade-{side}-{index}",
            "price_xch": str(100 - index if side == "buy" else 100 + index),
            "size_xch": "1",
            "tier": "inner",
        }
        for side in ("buy", "sell")
        for index in range(11)
    ]

    def get_open_offers(*, side, cat_asset_id):
        assert cat_asset_id == "adaptive-watchdog-cat"
        return [row for row in rows if f"-{side}-" in row["trade_id"]]

    captured = {}

    def run_periodic_audit(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(database, "get_open_offers", get_open_offers)
    monkeypatch.setattr(database, "get_locked_coins", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        bot_loop, "_get_wallet_confirmed_locked_coin_ids", lambda: set()
    )
    monkeypatch.setattr(ladder_watchdog, "run_periodic_audit", run_periodic_audit)
    monkeypatch.setattr(config, "get_buy_tier_size_xch", lambda _tier: "1")
    monkeypatch.setattr(config, "get_sell_tier_size_xch", lambda _tier: "1")

    cfg = bot_loop.cfg
    monkeypatch.setattr(cfg, "CAT_ASSET_ID", "adaptive-watchdog-cat")
    for side in ("BUY", "SELL"):
        monkeypatch.setattr(cfg, f"{side}_INNER_TIER_COUNT", 14)
        monkeypatch.setattr(cfg, f"{side}_MID_TIER_COUNT", 13)
        monkeypatch.setattr(cfg, f"{side}_OUTER_TIER_COUNT", 11)
        monkeypatch.setattr(cfg, f"{side}_EXTREME_TIER_COUNT", 7)

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop.coin_manager = SimpleNamespace(
        _lock=threading.Lock(),
        _xch_total_coins=100,
        _cat_total_coins=100,
        _xch_coins=89,
        _cat_coins=89,
        _xch_locked_coins=11,
        _cat_locked_coins=11,
        _get_live_offer_targets=lambda: {"buy": 11, "sell": 11},
    )
    loop.fill_tracker = SimpleNamespace(_last_fill_time={})
    loop._watchdog_post_fill_cooldown_secs = 60
    loop._watchdog_violation_streaks = {}
    loop._watchdog_persistence_threshold = 5
    loop._event_bus = None
    loop._loop_count = 10

    loop._run_ladder_watchdog()

    assert captured["buy_tier_counts"] == {
        "inner": 11,
        "mid": 0,
        "outer": 0,
        "extreme": 0,
    }
    assert captured["sell_tier_counts"] == {
        "inner": 11,
        "mid": 0,
        "outer": 0,
        "extreme": 0,
    }
