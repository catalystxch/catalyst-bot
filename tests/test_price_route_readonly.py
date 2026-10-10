"""Public price reads must not advance trading state or write price history."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import api_server
from blueprints import market
import requests


def test_stopped_price_route_uses_readonly_setup_quote(monkeypatch):
    engine = SimpleNamespace(get_price=Mock(return_value={"mid_price": Decimal("9")}))
    bot = SimpleNamespace(is_running=Mock(return_value=False), price_engine=engine)
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(
        api_server,
        "_active_cat",
        {"asset_id": "a" * 64, "ticker_id": "MZ_XCH", "decimals": 3},
    )
    setup_quote = Mock(return_value={"mid": "0.00008", "source": "dexie_bid_ask"})
    monkeypatch.setattr(market, "_get_startup_price_cached", setup_quote)

    with api_server.app.test_client() as client:
        response = client.get("/api/price")

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["mid"] == "0.00008"
    engine.get_price.assert_not_called()
    setup_quote.assert_called_once_with("a" * 64, "MZ_XCH", 3)


def test_running_price_route_uses_selected_pair_without_repricing(monkeypatch):
    engine = SimpleNamespace(
        get_price=Mock(return_value={"mid_price": Decimal("9")}),
        get_last_price=Mock(return_value=Decimal("0.00008")),
        _last_price_result={
            "mid_price": Decimal("0.00008"),
            "dexie_price": Decimal("0.00008"),
            "strategy_used": "dexie_offer_book",
        },
    )
    bot = SimpleNamespace(is_running=Mock(return_value=True), price_engine=engine)
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(
        api_server,
        "_active_cat",
        {"asset_id": "a" * 64, "ticker_id": "MZ_XCH", "decimals": 3},
    )
    setup_quote = Mock(return_value={"mid": "0.00008", "source": "dexie_bid_ask"})
    monkeypatch.setattr(market, "_get_startup_price_cached", setup_quote)

    with api_server.app.test_client() as client:
        response = client.get("/api/price")

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["mid"] == "0.00008"
    engine.get_price.assert_not_called()
    setup_quote.assert_called_once_with("a" * 64, "MZ_XCH", 3)


def test_pre_bot_price_route_ignores_another_assets_ticker_row(monkeypatch):
    """Setup pricing must bind a public quote to the selected CAT asset."""
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(
        api_server,
        "_active_cat",
        {"asset_id": "a" * 64, "ticker_id": "MZ_XCH", "decimals": 3},
    )
    monkeypatch.setattr(
        market, "_STARTUP_PRICE_CACHE", {"key": None, "expires_at": 0.0, "price": {}}
    )
    monkeypatch.setattr(
        requests,
        "get",
        Mock(
            return_value=SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "tickers": [
                        {
                            "ticker_id": "OTHER_XCH",
                            "base_id": "b" * 64,
                            "bid": "8",
                            "ask": "10",
                        },
                        {
                            "ticker_id": "MZ_XCH",
                            "base_id": "a" * 64,
                            "bid": "0.00007",
                            "ask": "0.00009",
                        },
                    ]
                },
            )
        ),
    )

    with api_server.app.test_client() as client:
        response = client.get("/api/price")

    assert response.status_code == 200
    assert Decimal(str(response.json["mid"])) == Decimal("0.00008")
