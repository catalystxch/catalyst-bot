from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import api_server
import bot_loop
import cat_resolver
import market_data_collector
import doctor
from blueprints import bot as bot_routes
from blueprints import boost as boost_routes
from blueprints import market
from boost_manager import BoostManager
from blueprints.smart_defaults import _fetch_price_standalone
from price_engine import PriceEngine


ASSET_ID = "b8" * 32


def test_price_engine_is_dexie_only_and_never_calls_retired_provider(monkeypatch):
    engine = PriceEngine()
    engine._fetch_dexie_price = Mock(return_value=Decimal("0.1"))
    engine._fetch_tibet_price = Mock(
        side_effect=AssertionError("retired provider called")
    )
    engine._apply_safety_guards = lambda value: value
    engine._update_reference_price = lambda value: None
    monkeypatch.setattr("price_engine.record_price", lambda **kwargs: True)

    result = engine.get_price(cat_asset_id=ASSET_ID, ticker_id="MZ_XCH")

    engine._fetch_tibet_price.assert_not_called()
    assert result["mid_price"] == Decimal("0.1")
    assert result["strategy_used"] == "dexie_offer_book"
    assert result["tibet_price"] is None
    assert result["tibet_available"] is False
    assert result["tibet_status"] == "retired"
    assert result["arb_opportunity"] is None


def test_smart_settings_and_market_collection_have_no_live_tibet_fetch_call():
    standalone_source = inspect.getsource(_fetch_price_standalone)
    collection_source = inspect.getsource(market_data_collector.collect_all_market_data)

    assert "api.v2.tibetswap.io" not in standalone_source
    assert '_record_api_call("tibetswap"' not in standalone_source
    assert "_fetch_tibet_pool(" not in collection_source
    assert "_fetch_tibet_quote(" not in collection_source
    assert '"status": "retired"' in collection_source


def test_cat_metadata_resolver_never_contacts_tibet(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"tickers": []}

    def fake_get(url, **kwargs):
        calls.append(url)
        assert "tibet" not in url.lower()
        return Response()

    monkeypatch.setattr(cat_resolver.requests, "get", fake_get)

    result = cat_resolver.resolve_cat_metadata(ASSET_ID)

    assert result["pair_lookup_status"] == "retired"
    assert result["retired_provider"] == "TibetSwap"
    assert calls and all("dexie" in url.lower() for url in calls)


def test_bot_price_watcher_is_retired_and_cannot_poll_reserves():
    source = inspect.getsource(bot_loop.BotLoop._price_watcher_thread)

    assert "_fetch_tibet_reserves" not in source
    assert "requests.Session" not in source
    assert "retired" in source.lower()


def test_startup_health_check_marks_tibetswap_retired_without_network_probe():
    source = inspect.getsource(bot_loop.BotLoop._run_startup_self_test)

    assert "api.v2.tibetswap.io" not in source
    assert 'results["tibet"]' in source
    assert '"status": "retired"' in source


def test_market_summary_and_startup_price_never_read_tibetswap():
    startup_source = inspect.getsource(market._get_startup_price_cached)
    summary_source = inspect.getsource(market.api_market_summary)

    assert "_get_tibet_pairs_cached" not in startup_source
    assert "TIBET_API_BASE" not in startup_source
    assert "_get_tibet_pairs_cached" not in summary_source
    assert "TIBET_API_BASE" not in summary_source
    assert '"tibet_status": "retired"' in summary_source


def test_retired_tibet_debug_endpoint_cannot_contact_network():
    source = inspect.getsource(market.api_debug_tibet_test)

    assert "requests" not in source
    assert "api.v2.tibetswap.io" not in source
    assert '"status": "retired"' in source


def test_status_and_doctor_health_paths_never_contact_tibetswap():
    status_source = inspect.getsource(bot_routes.api_status)
    doctor_source = inspect.getsource(doctor._check_tibet_reachable)

    assert "_get_tibet_pairs_cached" not in status_source
    assert "TIBET_API_BASE" not in status_source
    assert "requests" not in doctor_source
    assert 'status="skip"' in doctor_source
    assert "retired" in doctor_source.lower()


def test_live_health_paths_do_not_describe_retirement_as_an_outage():
    dashboard_source = inspect.getsource(
        __import__("blueprints.dashboard", fromlist=["api_dashboard"]).api_dashboard
    )
    augment_source = inspect.getsource(
        bot_loop.BotLoop._augment_health_with_provider_context
    )

    for source in (dashboard_source, augment_source):
        assert "TibetSwap API unavailable" not in source
        assert "Market degraded — TibetSwap" not in source
        assert "Dexie-only pricing" not in source
        assert '"pricing_mode"] = "offer_book_confidence"' in source


def test_live_ui_does_not_offer_retired_tibet_outage_fallback():
    html = (Path(__file__).resolve().parents[1] / "bot_gui.html").read_text(
        encoding="utf-8"
    )

    assert "During a TibetSwap outage" not in html


def test_operational_alerts_do_not_treat_tibet_as_live_connectivity():
    step_sla_source = inspect.getsource(bot_loop.BotLoop._check_step_sla)

    assert "Sage/Coinset/Tibet connectivity" not in step_sla_source


def test_market_module_does_not_keep_retired_outage_fallback_wording():
    market_source = inspect.getsource(market)

    assert "Dexie-only pricing" not in market_source
    assert "AMM drift protection is unavailable" not in market_source


def test_legacy_boost_activation_is_retired_without_starting_a_mutation(monkeypatch):
    fake_manager = Mock()
    fake_bot = Mock(boost_manager=fake_manager)
    start_mutation = Mock(side_effect=AssertionError("mutation worker started"))
    monkeypatch.setattr(api_server, "bot", fake_bot)
    monkeypatch.setattr(api_server, "start_mutation_thread", start_mutation)

    with api_server.app.test_request_context(
        "/api/boost/activate", method="POST", json={}
    ):
        response, status = boost_routes.api_boost_activate()

    assert status == 410
    assert response.get_json() == {
        "success": False,
        "status": "retired",
        "reason": "TIBETSWAP_SHUTDOWN",
        "replacement": "book_opportunity",
    }
    start_mutation.assert_not_called()
    fake_manager.activate.assert_not_called()


def test_legacy_boost_manager_cannot_create_new_offers():
    offer_manager = Mock()
    manager = BoostManager(offer_manager=offer_manager)

    result = manager.activate(Decimal("1"))

    assert result == {
        "success": False,
        "status": "retired",
        "reason": "TIBETSWAP_SHUTDOWN",
        "replacement": "book_opportunity",
    }
    offer_manager.create_ladder.assert_not_called()
    offer_manager.create_offer_with_retry.assert_not_called()


def test_production_cycle_fences_recovered_legacy_boost_mutations():
    source = inspect.getsource(bot_loop.BotLoop._run_one_cycle)

    assert "LEGACY_TIBET_BOOST_RUNTIME_ENABLED" in source


def test_legacy_slippage_endpoint_is_explicitly_retired(monkeypatch):
    fake_engine = Mock()
    fake_engine.get_tibet_quote.side_effect = AssertionError("retired provider called")
    monkeypatch.setattr(api_server, "bot", Mock(price_engine=fake_engine))

    with api_server.app.test_request_context("/api/market/slippage?amount=1&side=buy"):
        response = market.api_market_slippage()

    payload = response.get_json()
    fake_engine.get_tibet_quote.assert_not_called()
    assert payload == {
        "available": False,
        "provider": "tibetswap",
        "status": "retired",
        "reason": "TIBETSWAP_SHUTDOWN",
    }


def test_legacy_amm_endpoint_is_explicitly_retired(monkeypatch):
    fake_monitor = Mock()
    fake_monitor.get_amm_state.side_effect = AssertionError("retired monitor called")
    monkeypatch.setattr(api_server, "bot", Mock(amm_monitor=fake_monitor))

    with api_server.app.test_request_context("/api/amm/price"):
        response = market.api_amm_price()

    fake_monitor.get_amm_state.assert_not_called()
    assert response.get_json() == {
        "available": False,
        "provider": "tibetswap",
        "status": "retired",
        "reason": "TIBETSWAP_SHUTDOWN",
    }


def test_retired_pool_and_quote_methods_do_not_use_network(monkeypatch):
    engine = PriceEngine()
    engine._session.get = Mock(side_effect=AssertionError("network call attempted"))

    assert engine._fetch_tibet_price(ASSET_ID) is None
    assert engine._find_tibet_pair(ASSET_ID) is None
    assert engine._get_tibet_pairs() == []
    assert (
        engine.inject_tibet_reserves(
            asset_id=ASSET_ID,
            xch_reserve=1,
            token_reserve=1,
        )
        is False
    )
    assert engine.get_tibet_pool_info(ASSET_ID)["status"] == "retired"
    assert engine.get_tibet_quote(Decimal("1"), "buy")["status"] == "retired"
    engine._session.get.assert_not_called()


def test_legacy_tibet_mempool_and_sniper_paths_are_runtime_fenced():
    mempool_source = inspect.getsource(bot_loop.BotLoop._try_start_mempool_watcher)
    coin_prep_source = inspect.getsource(
        __import__("coin_manager").CoinManager._sniper_pool_enabled
    )
    cycle_source = inspect.getsource(bot_loop.BotLoop._run_one_cycle)

    assert "_find_tibet_pair" not in mempool_source
    assert "start_watcher" not in mempool_source
    assert '"tibetswap_mempool_watcher_retired"' in mempool_source
    assert "return False" in coin_prep_source
    assert "_sniper_on = False" in cycle_source
    assert "self.amm_monitor.is_available()" not in cycle_source


def test_cycle_does_not_print_prices_or_requote_decisions_to_clear_text_console():
    """Structured logs must replace terminal output that CodeQL treats as sensitive."""
    source = inspect.getsource(bot_loop.BotLoop._run_one_cycle)

    assert "print(baseline_msg" not in source
    assert "Tibet: {tibet_p}" not in source
    assert "print(msg, flush=True)" not in source
    assert "print(done_msg, flush=True)" not in source
    assert "Gap closer refreshed at {mid_price" not in source
    assert "[REQUOTE] {side} side ({reason})" not in source


def test_current_operator_docs_do_not_advertise_retired_tibetswap_features():
    root = Path(__file__).resolve().parents[1]
    current_docs = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "README.md",
            "docs/PRIVACY.md",
            "docs/tutorial-master-settings-inventory.md",
            "tests/manual_test_checklist.md",
        )
    )

    for retired_claim in (
        "Sniper probes.",
        "TibetSwap AMM",
        "Fetch and blend TibetSwap and Dexie pricing",
        "keeps TibetSwap reserves fresh",
        "TibetSwap pool coin",
        "Price oracle using TibetSwap and Dexie",
        "CATalyst queries TibetSwap for pool, reserve, price",
        "lists all MZ_XCH and other CAT pools from TibetSwap",
    ):
        assert retired_claim not in current_docs
