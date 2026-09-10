from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import inspect
from types import SimpleNamespace

import database
import pytest
from market_runtime import OfferBookMarketRuntime


ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "market-runtime.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def _book():
    return {
        "bids": [
            {"offer_id": "buy-1", "price": "0.00009", "amount_mojos": 3_000_000_000_000}
        ],
        "asks": [
            {"offer_id": "sell-1", "price": "0.00011", "amount_mojos": 3_000_000_000_000}
        ],
    }


def _splash():
    return [
        {"offer_id": "splash-buy", "side": "buy", "price": "0.00009", "amount_mojos": 3_000_000_000_000},
        {"offer_id": "splash-sell", "side": "sell", "price": "0.00011", "amount_mojos": 3_000_000_000_000},
    ]


def test_runtime_persists_one_coherent_green_decision(isolated_db):
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda asset_id: _book(),
        fetch_splash_offers=lambda asset_id: _splash(),
        fetch_splash_health=lambda: {"running": True, "api_reachable": True, "peers": 2},
    )

    result = runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )

    assert result.confidence.state == "GREEN"
    assert result.confidence.trusted_midpoint is not None
    assert result.degraded.can_create is True
    assert result.degraded.can_requote is True
    stored = database.get_latest_market_confidence_snapshot(ASSET_ID)
    assert stored["state"] == "GREEN"
    assert stored["snapshot_id"] == result.snapshot_id
    providers = database.get_market_provider_observations(ASSET_ID, limit=10)
    assert {row["provider_id"] for row in providers} == {"dexie", "splash"}


def test_runtime_fails_closed_when_only_our_offers_remain(isolated_db):
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda asset_id: _book(),
        fetch_splash_offers=lambda asset_id: [],
        fetch_splash_health=lambda: {"running": True, "api_reachable": True, "peers": 1},
    )

    result = runtime.refresh(
        own_offer_identities=frozenset({"buy-1", "sell-1"}),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )

    assert result.confidence.state == "RED"
    assert result.degraded.can_create is False
    assert result.degraded.can_requote is False
    assert result.degraded.cancel_tiers == ("inner",)
    assert "one_sided_book" in result.confidence.reason_codes


def test_bot_runtime_phase_gate_blocks_exposure_but_never_safety_cancel(monkeypatch):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._market_runtime_required = True
    loop._market_degraded_decision = SimpleNamespace(
        can_create=False,
        can_requote=False,
    )
    monkeypatch.setattr(loop, "_runtime_recovery_cycle_boundary", lambda: True)
    loop._runtime_recovery_monotonic = lambda: 1
    loop._runtime_recovery_wall_clock = lambda: NOW
    loop._runtime_recovery_gap_seconds = 10
    loop._runtime_recovery_skew_seconds = 2

    assert loop._enter_runtime_effect_phase("create") is False
    assert loop._enter_runtime_effect_phase("publication") is False
    assert loop._enter_runtime_effect_phase("requote") is False
    assert loop._enter_runtime_effect_phase("cancel") is True
    assert loop._enter_runtime_effect_phase("trim") is True


def test_bot_runtime_phase_gate_fails_closed_before_first_confidence_refresh(monkeypatch):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._market_runtime_required = True
    loop._market_degraded_decision = None
    monkeypatch.setattr(loop, "_runtime_recovery_cycle_boundary", lambda: True)
    loop._runtime_recovery_monotonic = lambda: 1
    loop._runtime_recovery_wall_clock = lambda: NOW
    loop._runtime_recovery_gap_seconds = 10
    loop._runtime_recovery_skew_seconds = 2

    assert loop._enter_runtime_effect_phase("create") is False
    assert loop._enter_runtime_effect_phase("cancel") is True


def test_bot_records_exact_splash_offer_for_confidence():
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._splash_confidence_offers = {}
    loop._splash_confidence_lock = __import__("threading").Lock()
    classified = {
        "relevant": True,
        "side": "sell",
        "summary": {
            "offered": {ASSET_ID: 12_500_000},
            "requested": {"xch": 1_000_000_000_000},
        },
    }

    assert loop._remember_splash_confidence_offer(
        fingerprint="splash-offer-1",
        classified=classified,
        observed_at=NOW,
    ) is True

    row = loop._get_fresh_splash_confidence_offers(ASSET_ID, now=NOW)[0]
    assert row == {
        "offer_id": "splash-offer-1",
        "side": "sell",
        "price": "0.00008",
        "amount_mojos": 1_000_000_000_000,
    }


def test_market_withdrawal_cancels_only_requested_tiers(monkeypatch):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    cancelled = []
    loop.offer_manager = SimpleNamespace(
        cancel_offers=lambda ids, **kwargs: cancelled.extend(ids) or {}
    )
    monkeypatch.setattr(loop, "_enter_runtime_effect_phase", lambda phase: phase == "cancel")
    monkeypatch.setattr(
        bot_loop,
        "get_open_offers",
        lambda cat_asset_id=None: [
            {"trade_id": "inner", "tier": "inner"},
            {"trade_id": "mid", "tier": "mid"},
            {"trade_id": "outer", "tier": "outer"},
        ],
        raising=False,
    )

    loop._apply_market_withdrawal(
        SimpleNamespace(cancel_tiers=("inner", "middle"), reason_code="MARKET_DEGRADED_MIDDLE")
    )

    assert cancelled == ["inner", "mid"]


def test_trading_cycle_prices_mutations_from_offer_book_confidence_only():
    import bot_loop

    source = inspect.getsource(bot_loop.BotLoop._run_one_cycle)

    assert "_refresh_offer_book_market" in source
    assert "self.price_engine.get_price(" not in source
    assert "both oracles (Dexie + TibetSwap)" not in source


def test_all_mutation_adjacent_price_reads_use_offer_book_confidence_only():
    import bot_loop

    methods = (
        bot_loop.BotLoop._refresh_price_if_mempool_move_pending,
        bot_loop.BotLoop._startup_sync,
        bot_loop.BotLoop._create_offers_if_needed,
        bot_loop.BotLoop.graceful_config_change,
    )

    for method in methods:
        source = inspect.getsource(method)
        assert "self.price_engine.get_price(" not in source, method.__name__
