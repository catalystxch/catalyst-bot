"""A thin token's volatility must not trigger a network call on every spread."""

from __future__ import annotations

from decimal import Decimal

import dexie_manager
import requests
import risk_manager


class _CountingDexie:
    def __init__(self):
        self.calls = 0

    def compute_v3_trade_metrics(self, ticker_id, hours):
        self.calls += 1
        return {"trades_in_window": 1, "price_stdev_pct": 0}


def test_zero_volatility_is_cached_instead_of_refetched(monkeypatch):
    manager = risk_manager.RiskManager.__new__(risk_manager.RiskManager)
    manager._cached_volatility = Decimal("0")
    manager._volatility_updated = 0
    manager._price_engine = None
    manager._dexie_manager = _CountingDexie()
    monkeypatch.setattr(risk_manager.cfg, "CAT_TICKER_ID", "MZ_XCH", raising=False)

    assert manager._get_volatility() == Decimal("0")
    for _ in range(5):
        manager._get_volatility()

    assert manager._dexie_manager.calls == 1


def test_failed_trade_fetch_backs_off_instead_of_retrying_every_call(monkeypatch):
    dm = dexie_manager.DexieManager()
    calls = []

    def failing_get(*_args, **_kwargs):
        calls.append(True)
        raise requests.ConnectionError("dns down")

    monkeypatch.setattr(dexie_manager.requests, "get", failing_get)

    assert dm.fetch_v3_historical_trades("MZ_XCH") is None
    assert dm.fetch_v3_historical_trades("MZ_XCH") is None
    assert dm.fetch_v3_historical_trades("MZ_XCH", force=True) is None

    assert len(calls) == 1


def test_backoff_serves_stale_trades_and_clears_after_success(monkeypatch):
    dm = dexie_manager.DexieManager()
    dm._v3_trades_cache["MZ_XCH"] = {"trades": [{"price": 1}], "fetched_at": 0}

    def failing_get(*_args, **_kwargs):
        raise requests.ConnectionError("dns down")

    monkeypatch.setattr(dexie_manager.requests, "get", failing_get)
    assert dm.fetch_v3_historical_trades("MZ_XCH") is None
    assert dm.fetch_v3_historical_trades("MZ_XCH") == [{"price": 1}]

    class _Ok:
        status_code = 200

        @staticmethod
        def json():
            return [{"price": 2}]

    monkeypatch.setattr(dexie_manager.requests, "get", lambda *_a, **_k: _Ok())
    dm._v3_trades_failed_until["MZ_XCH"] = 0
    assert dm.fetch_v3_historical_trades("MZ_XCH", force=True) == [{"price": 2}]
    assert "MZ_XCH" not in dm._v3_trades_failed_until
