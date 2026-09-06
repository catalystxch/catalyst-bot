"""Read-only setup pricing remains usable during the external TibetSwap outage."""

from unittest.mock import Mock

import pytest

import api_server  # noqa: F401 - initialise the Flask owner before its blueprints
from blueprints import market


@pytest.fixture
def prices(monkeypatch):
    monkeypatch.setattr(
        market, "_STARTUP_PRICE_CACHE", {"key": None, "expires_at": 0, "price": {}}
    )
    monkeypatch.setattr(market, "_record_api_call", Mock())
    monkeypatch.setattr(market, "_get_tibet_pairs_cached", Mock(return_value=[]))
    response = Mock(status_code=200)
    response.json.return_value = [
        {"ticker_id": "MZ_XCH", "bid": "0.00007", "ask": "0.00009"}
    ]
    fetch = Mock(return_value=response)
    monkeypatch.setattr("requests.get", fetch)
    return response, fetch


def test_tibetswap_outage_dexie_cache_expires_and_refetches(prices, monkeypatch):
    clock = Mock(return_value=100)
    monkeypatch.setattr(market.time, "monotonic", clock)
    response, fetch = prices
    assert market._get_startup_price_cached("aa", "MZ")["mid"] == "0.00008"
    response.json.return_value[0]["ask"] = "0.00011"
    clock.return_value = 159
    assert market._get_startup_price_cached("aa", "MZ")["mid"] == "0.00008"
    clock.return_value = 160
    assert market._get_startup_price_cached("aa", "MZ")["mid"] == "0.00009"
    assert fetch.call_count == 2


def test_tibetswap_outage_accepts_real_dexie_ticker_response_shape(prices):
    response, _ = prices
    response.json.return_value = {
        "success": True,
        "tickers": [
            {
                "ticker_id": "MZ_XCH",
                "base_id": "aa",
                "bid": "0.00007",
                "ask": "0.00009",
            }
        ],
    }

    assert market._get_startup_price_cached("aa", "MZ_XCH") == {
        "mid": "0.00008",
        "source": "dexie_bid_ask",
        "tibet_available": False,
    }


@pytest.mark.parametrize(
    "row",
    [
        {"ticker_id": "OTHER_XCH", "bid": "1", "ask": "2"},
        {"bid": "1", "ask": "2"},
        {"ticker_id": "MZ_XCH", "bid": "2", "ask": "1"},
        {"ticker_id": "MZ_XCH", "bid": "NaN", "ask": "Infinity"},
        {"ticker_id": "MZ_XCH", "bid": "-1", "ask": "2"},
        {"ticker_id": "MZ_XCH", "last_price": "100"},
        {"ticker_id": "MZ_XCH", "bid": "0", "ask": "2"},
        {"ticker_id": "MZ_XCH", "bid": "bad", "ask": "2"},
        None,
    ],
)
def test_tibetswap_outage_never_substitutes_unsafe_or_historical_dexie_price(
    prices, row
):
    response, _ = prices
    response.json.return_value = [row]
    assert market._get_startup_price_cached("aa", "MZ_XCH") == {}


def test_tibetswap_outage_and_dexie_failure_are_negative_cached(prices, monkeypatch):
    import requests

    clock = Mock(return_value=100)
    monkeypatch.setattr(market.time, "monotonic", clock)
    _, fetch = prices
    fetch.side_effect = requests.Timeout("provider unavailable")
    assert market._get_startup_price_cached("aa", "MZ_XCH") == {}
    clock.return_value = 114
    assert market._get_startup_price_cached("aa", "MZ_XCH") == {}
    assert fetch.call_count == 1
    clock.return_value = 115
    assert market._get_startup_price_cached("aa", "MZ_XCH") == {}
    assert fetch.call_count == 2
    assert market._get_tibet_pairs_cached.call_count == 2


@pytest.mark.parametrize("key_change", ["asset", "ticker", "decimals"])
def test_tibetswap_outage_quote_cache_is_scoped_to_pair(prices, key_change):
    response, fetch = prices
    assert market._get_startup_price_cached("aa", "MZ_XCH")["mid"] == "0.00008"
    response.json.return_value = []
    args = {"asset_id": "aa", "ticker_id": "MZ_XCH", "decimals": 3}
    args[
        {"asset": "asset_id", "ticker": "ticker_id", "decimals": "decimals"}[key_change]
    ] = {
        "asset": "bb",
        "ticker": "OTHER_XCH",
        "decimals": 0,
    }[key_change]
    assert market._get_startup_price_cached(**args) == {}
    assert fetch.call_count == 2


def test_available_tibetswap_pool_uses_decimal_reserves_including_zero_decimals(prices):
    _, fetch = prices
    market._get_tibet_pairs_cached.return_value = [
        {"asset_id": "0xAA", "xch_reserve": "3000000000000", "token_reserve": "2"}
    ]
    assert market._get_startup_price_cached("aa", "MZ_XCH", 0) == {
        "mid": "1.5",
        "source": "tibetswap",
        "tibet_available": True,
    }
    fetch.assert_not_called()


def test_no_selected_asset_does_not_fetch(prices):
    assert market._get_startup_price_cached("", "MZ_XCH") == {}
    prices[1].assert_not_called()
    market._get_tibet_pairs_cached.assert_not_called()
