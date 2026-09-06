"""Slice 04-14 — dashboard endpoint contract tests.

Tests GET /api/dashboard:
  - No auth required (read-only aggregator)
  - Returns 200 with all required top-level keys
  - bot=None returns safe empty shapes for bot-dependent fields
"""

import os
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import api_server
    from blueprints import dashboard as dashboard_bp

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    dashboard_bp = None
    _SKIP = str(exc)


def _empty_spacescan():
    return {
        "enabled": False,
        "has_data": False,
        "holder_count": 0,
        "activity_level": "unknown",
        "risk_level": "unknown",
        "price_gap_bps": 0,
    }


def _priced_spacescan():
    data = _empty_spacescan()
    data.update(
        {
            "enabled": True,
            "has_data": True,
            "price_xch": "0.005",
            "price_usd": "0.0125",
        }
    )
    return data


def _make_mock_db_conn():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None
    mock_cur.fetchall.return_value = []
    mock_cur.__iter__ = MagicMock(return_value=iter([]))
    mock_conn.execute.return_value = mock_cur
    return mock_conn


class _FlaskBase(unittest.TestCase):
    _LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

    def setUp(self):
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        api_server._rate_limit_log.clear()
        self._fiat_price_patcher = patch(
            "market_data_collector.get_cached_xch_usd_price",
            return_value=None,
        )
        self._fiat_price_patcher.start()
        self.addCleanup(self._fiat_price_patcher.stop)

    def tearDown(self):
        api_server._rate_limit_log.clear()

    def _get_dashboard(self):
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 0,
            "cat_free_count": 0,
            "xch_total": 0,
            "cat_total": 0,
        }
        with (
            patch("database.get_stats", return_value=fake_stats),
            patch("database.get_coin_summary", return_value=fake_summary),
            patch("database.get_open_offers", return_value=[]),
            patch("database.get_connection", return_value=_make_mock_db_conn()),
            patch.object(
                api_server,
                "_get_spacescan_market_context",
                return_value=_empty_spacescan(),
            ),
            patch.object(api_server, "bot", None),
        ):
            return self.client.get("/api/dashboard", environ_base=self._LOOPBACK)


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestDashboard(_FlaskBase):
    def test_returns_200(self):
        resp = self._get_dashboard()
        self.assertEqual(resp.status_code, 200)

    def test_response_has_top_level_keys(self):
        resp = self._get_dashboard()
        body = resp.get_json()
        for key in (
            "settings",
            "market_health",
            "wallet",
            "coins",
            "performance",
            "current_cat",
            "links",
        ):
            self.assertIn(key, body)

    def test_response_has_fiat_price_summary(self):
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 0,
            "cat_free_count": 0,
            "xch_total": 0,
            "cat_total": 0,
        }
        price_result = {
            "has_data": True,
            "xch_usd": 2.5,
            "source": "spacescan",
            "fetched_at": 1777824000.0,
        }
        with (
            patch("database.get_stats", return_value=fake_stats),
            patch("database.get_coin_summary", return_value=fake_summary),
            patch("database.get_open_offers", return_value=[]),
            patch("database.get_connection", return_value=_make_mock_db_conn()),
            patch(
                "market_data_collector.get_cached_xch_usd_price",
                return_value=price_result,
            ),
            patch.object(
                api_server,
                "_get_spacescan_market_context",
                return_value=_priced_spacescan(),
            ),
            patch.object(api_server, "bot", None),
        ):
            resp = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        fiat = resp.get_json()["fiat_prices"]
        self.assertEqual(fiat["xch_usd_price"], "2.5")
        self.assertEqual(fiat["xch_usd_source"], "spacescan")
        self.assertEqual(fiat["cat_usd_price"], "0.0125")
        self.assertEqual(fiat["cat_price_xch"], "0.005")
        self.assertEqual(fiat["cat_usd_source"], "spacescan")

    def test_fiat_summary_prefers_executable_market_over_spacescan_price(self):
        with patch(
            "market_data_collector.get_cached_xch_usd_price",
            return_value={"has_data": True, "xch_usd": "2", "source": "coingecko"},
        ):
            fiat = dashboard_bp._build_fiat_price_summary(
                {
                    "price_xch": "0.000000001",
                    "price_usd": "0.000000002",
                    "price_gap_bps": "9999.875",
                },
                executable_mid_price="0.00008",
            )

        self.assertEqual(fiat["cat_price_xch"], "0.00008")
        self.assertEqual(fiat["cat_usd_price"], "0.00016")
        self.assertEqual(fiat["cat_usd_source"], "market × coingecko")

    def test_stopped_dashboard_uses_current_orderbook_for_cat_fiat(self):
        risk_manager = MagicMock()
        risk_manager.get_inventory_state.return_value = {}
        risk_manager.get_circuit_breaker_blocked_side.return_value = ""
        risk_manager.get_market_health.return_value = {
            "status": "green",
            "message": "Market conditions healthy — bot stopped",
            "conditions": [],
            "metrics": {},
        }
        market_intel = MagicMock()
        market_intel.get_market_summary.return_value = {
            "best_bid": "0.00007",
            "best_ask": "0.00009",
            "orderbook_refreshes": 1,
        }
        price_engine = MagicMock()
        price_engine.get_last_price.return_value = Decimal("0")
        stopped_bot = types.SimpleNamespace(
            risk_manager=risk_manager,
            market_intel=market_intel,
            price_engine=price_engine,
            _loop_count=1,
            _bot_state={},
            _last_live_offer_edges={},
            _probe_state={},
            _start_time=0,
            coin_manager=None,
            sniper=None,
            boost_manager=None,
            get_state=lambda: {"running": False},
            is_running=lambda: False,
        )
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 0,
            "cat_free_count": 0,
            "xch_total": 0,
            "cat_total": 0,
        }
        with (
            patch("database.get_stats", return_value=fake_stats),
            patch("database.get_coin_summary", return_value=fake_summary),
            patch("database.get_live_tier_group_counts", return_value={}),
            patch("database.get_open_offers", return_value=[]),
            patch("database.get_connection", return_value=_make_mock_db_conn()),
            patch(
                "market_data_collector.get_cached_xch_usd_price",
                return_value={"xch_usd": "2", "source": "coingecko"},
            ),
            patch.object(
                dashboard_bp, "_dashboard_wallet_reads_allowed", return_value=False
            ),
            patch.object(
                api_server,
                "_get_spacescan_market_context",
                return_value={
                    **_priced_spacescan(),
                    "price_xch": "0.000000001",
                    "price_usd": "0.000000002",
                },
            ),
            patch.object(api_server, "bot", stopped_bot),
        ):
            response = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)

        self.assertEqual(response.status_code, 200)
        fiat = response.get_json()["fiat_prices"]
        self.assertEqual(fiat["cat_price_xch"], "0.00008")
        self.assertEqual(fiat["cat_usd_price"], "0.00016")
        self.assertEqual(fiat["cat_usd_source"], "market × coingecko")

    def test_settings_has_trading_section(self):
        resp = self._get_dashboard()
        body = resp.get_json()
        self.assertIn("trading", body["settings"])
        self.assertIn("spreads", body["settings"])

    def test_market_health_has_status(self):
        resp = self._get_dashboard()
        body = resp.get_json()
        self.assertIn("status", body["market_health"])

    def test_market_health_does_not_claim_stopped_bot_is_operating(self):
        risk_manager = MagicMock()
        risk_manager.get_inventory_state.return_value = {}
        risk_manager.get_circuit_breaker_blocked_side.return_value = ""
        risk_manager.get_market_health.return_value = {
            "status": "green",
            "message": "Market healthy — bot operating normally",
            "conditions": [],
            "metrics": {},
        }
        stopped_bot = types.SimpleNamespace(
            risk_manager=risk_manager,
            _loop_count=127,
            _bot_state={},
            _last_live_offer_edges={},
            _probe_state={},
            _start_time=0,
            market_intel=None,
            price_engine=None,
            coin_manager=None,
            sniper=None,
            boost_manager=None,
            get_state=lambda: {"running": False},
            is_running=lambda: False,
        )
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 0,
            "cat_free_count": 0,
            "xch_total": 0,
            "cat_total": 0,
        }

        with (
            patch("database.get_stats", return_value=fake_stats),
            patch("database.get_coin_summary", return_value=fake_summary),
            patch("database.get_live_tier_group_counts", return_value={}),
            patch("database.get_open_offers", return_value=[]),
            patch("database.get_connection", return_value=_make_mock_db_conn()),
            patch.object(
                dashboard_bp,
                "_dashboard_wallet_reads_allowed",
                return_value=False,
            ),
            patch.object(
                api_server,
                "_get_spacescan_market_context",
                return_value=_empty_spacescan(),
            ),
            patch.object(api_server, "bot", stopped_bot),
        ):
            resp = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.get_json()["market_health"]["message"],
            "Market conditions healthy — bot stopped",
        )

    def test_market_health_reports_tibetswap_outage_as_degraded(self):
        risk_manager = MagicMock()
        risk_manager.get_inventory_state.return_value = {}
        risk_manager.get_circuit_breaker_blocked_side.return_value = ""
        risk_manager.get_market_health.return_value = {
            "status": "green",
            "message": "Market healthy — bot operating normally",
            "conditions": [],
            "metrics": {},
        }
        running_bot = types.SimpleNamespace(
            risk_manager=risk_manager,
            _loop_count=127,
            _bot_state={},
            _last_live_offer_edges={},
            _probe_state={},
            _start_time=0,
            _startup_self_test_results={
                "tibet": {
                    "name": "TibetSwap API",
                    "ok": False,
                    "status_code": 502,
                    "error": "HTTP 502 (server error)",
                    "missing_if_down": "AMM reference price and drift protection",
                    "critical": False,
                }
            },
            market_intel=None,
            price_engine=None,
            coin_manager=None,
            sniper=None,
            boost_manager=None,
            get_state=lambda: {"running": True},
            is_running=lambda: True,
        )
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 0,
            "cat_free_count": 0,
            "xch_total": 0,
            "cat_total": 0,
        }

        with (
            patch("database.get_stats", return_value=fake_stats),
            patch("database.get_coin_summary", return_value=fake_summary),
            patch("database.get_live_tier_group_counts", return_value={}),
            patch("database.get_open_offers", return_value=[]),
            patch("database.get_connection", return_value=_make_mock_db_conn()),
            patch.object(
                dashboard_bp,
                "_dashboard_wallet_reads_allowed",
                return_value=False,
            ),
            patch.object(
                api_server,
                "_get_spacescan_market_context",
                return_value=_empty_spacescan(),
            ),
            patch.object(api_server, "bot", running_bot),
        ):
            resp = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        market_health = resp.get_json()["market_health"]
        self.assertEqual(market_health["status"], "amber")
        self.assertIn("TibetSwap", market_health["message"])
        self.assertIn("Dexie-only", market_health["message"])
        self.assertTrue(
            any(
                condition.get("level") == "amber"
                and "AMM drift protection" in condition.get("text", "")
                for condition in market_health["conditions"]
            )
        )

    def test_wallet_has_balance_keys(self):
        resp = self._get_dashboard()
        body = resp.get_json()
        wallet = body["wallet"]
        for key in ("xch_spendable", "xch_total", "cat_spendable", "cat_total"):
            self.assertIn(key, wallet)

    def test_coins_has_count_keys(self):
        resp = self._get_dashboard()
        body = resp.get_json()
        coins = body["coins"]
        for key in ("xch_free", "xch_locked", "xch_total"):
            self.assertIn(key, coins)

    def test_links_has_dexie_orderbook(self):
        resp = self._get_dashboard()
        body = resp.get_json()
        self.assertIn("dexie_orderbook", body["links"])

    def test_current_cat_is_dict(self):
        resp = self._get_dashboard()
        body = resp.get_json()
        self.assertIsInstance(body["current_cat"], dict)

    def test_dashboard_does_not_read_wallet_before_startup_authorised(self):
        with (
            patch("wallet.get_wallet_balance") as get_wallet_balance,
            patch("wallet.rpc") as wallet_rpc,
            patch("wallet.is_initialized", return_value=False),
            patch("chia_node.is_startup_authorised", return_value=False),
        ):
            resp = self._get_dashboard()

        self.assertEqual(resp.status_code, 200)
        get_wallet_balance.assert_not_called()
        wallet_rpc.assert_not_called()

    def test_dashboard_reads_and_caches_wallet_after_sage_initialized(self):
        asset_id = "aa" * 32
        original_active_cat = dict(api_server._active_cat)
        api_server.clear_balance_snapshot()
        api_server._active_cat.clear()
        api_server._active_cat.update(
            {
                "asset_id": asset_id,
                "wallet_id": 2,
                "name": "TestCAT",
                "decimals": 3,
                "ticker_id": "TEST_XCH",
            }
        )
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 12,
            "cat_free_count": 9,
            "xch_total": 12,
            "cat_total": 9,
        }
        xch_balance = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 12_500_000_000_000,
                "spendable_balance": 12_000_000_000_000,
            },
        }
        cat_balance = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 987_654_321,
                "spendable_balance": 900_000_000,
            },
        }

        cached = None
        try:
            with (
                patch("database.get_stats", return_value=fake_stats),
                patch("database.get_coin_summary", return_value=fake_summary),
                patch("database.get_open_offers", return_value=[]),
                patch("database.get_connection", return_value=_make_mock_db_conn()),
                patch.object(
                    api_server,
                    "_get_spacescan_market_context",
                    return_value=_empty_spacescan(),
                ),
                patch.object(api_server, "bot", None),
                patch("wallet.is_initialized", return_value=True),
                patch("chia_node.is_startup_authorised", return_value=False),
                patch(
                    "wallet.get_wallet_balance",
                    side_effect=[xch_balance, cat_balance],
                ) as get_wallet_balance,
            ):
                resp = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)
                cached = api_server.get_cached_balance_snapshot(
                    asset_id=asset_id,
                    cat_wallet_id=2,
                )
        finally:
            api_server.clear_balance_snapshot()
            api_server._active_cat.clear()
            api_server._active_cat.update(original_active_cat)

        self.assertEqual(resp.status_code, 200)
        get_wallet_balance.assert_any_call(1)
        get_wallet_balance.assert_any_call(2)
        wallet = resp.get_json()["wallet"]
        self.assertEqual(float(wallet["xch_total"]), 12.5)
        self.assertEqual(float(wallet["xch_spendable"]), 12.0)
        self.assertEqual(float(wallet["cat_total"]), 987654.321)
        self.assertEqual(float(wallet["cat_spendable"]), 900000.0)

        self.assertIsNotNone(cached)
        self.assertEqual(cached["xch"]["total"], 12.5)
        self.assertEqual(cached["cat"]["total"], 987654.321)

    def test_dashboard_does_not_cache_partial_live_wallet_read(self):
        asset_id = "aa" * 32
        original_active_cat = dict(api_server._active_cat)
        api_server.clear_balance_snapshot()
        api_server._active_cat.clear()
        api_server._active_cat.update(
            {
                "asset_id": asset_id,
                "wallet_id": 2,
                "name": "TestCAT",
                "decimals": 3,
                "ticker_id": "TEST_XCH",
            }
        )
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 12,
            "cat_free_count": 9,
            "xch_total": 12,
            "cat_total": 9,
        }
        xch_balance = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 12_500_000_000_000,
                "spendable_balance": 12_000_000_000_000,
            },
        }
        cat_failure = {"success": False, "error": "CAT read failed"}

        cached = None
        try:
            with (
                patch("database.get_stats", return_value=fake_stats),
                patch("database.get_coin_summary", return_value=fake_summary),
                patch("database.get_open_offers", return_value=[]),
                patch("database.get_connection", return_value=_make_mock_db_conn()),
                patch.object(
                    api_server,
                    "_get_spacescan_market_context",
                    return_value=_empty_spacescan(),
                ),
                patch.object(api_server, "bot", None),
                patch("wallet.is_initialized", return_value=True),
                patch("chia_node.is_startup_authorised", return_value=False),
                patch(
                    "wallet.get_wallet_balance",
                    side_effect=[xch_balance, cat_failure],
                ),
            ):
                resp = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)
                cached = api_server.get_cached_balance_snapshot(
                    asset_id=asset_id,
                    cat_wallet_id=2,
                )
        finally:
            api_server.clear_balance_snapshot()
            api_server._active_cat.clear()
            api_server._active_cat.update(original_active_cat)

        self.assertEqual(resp.status_code, 200)
        wallet = resp.get_json()["wallet"]
        self.assertEqual(float(wallet["xch_total"]), 12.5)
        self.assertEqual(float(wallet["cat_total"]), 0.0)
        self.assertIsNone(cached)

    def test_dashboard_reuses_verified_cat_balance_on_transient_zero(self):
        asset_id = "aa" * 32
        original_active_cat = dict(api_server._active_cat)
        api_server.clear_balance_snapshot()
        api_server._active_cat.clear()
        api_server._active_cat.update(
            {
                "asset_id": asset_id,
                "wallet_id": 2,
                "name": "TestCAT",
                "decimals": 3,
                "ticker_id": "TEST_XCH",
            }
        )
        api_server.cache_balance_snapshot(
            asset_id=asset_id,
            cat_wallet_id=2,
            balances={
                "xch": {"total": 5.0, "spendable": 4.0},
                "cat": {"total": 6_500_000.0, "spendable": 6_400_000.0},
            },
            source="test",
        )

        zero_balance = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 0,
                "spendable_balance": 0,
            },
        }
        active_bot = types.SimpleNamespace(
            get_state=lambda: {"running": True},
            is_running=lambda: True,
            risk_manager=None,
            market_intel=None,
            coin_manager=None,
            sniper=None,
            boost_manager=None,
            price_engine=None,
            _bot_state={},
            _last_live_offer_edges={},
            _loop_count=1,
            _start_time=0,
            _probe_state={},
        )
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 0,
            "cat_free_count": 0,
            "xch_total": 0,
            "cat_total": 0,
        }

        try:
            with (
                patch("database.get_stats", return_value=fake_stats),
                patch("database.get_coin_summary", return_value=fake_summary),
                patch("database.get_open_offers", return_value=[]),
                patch("database.get_connection", return_value=_make_mock_db_conn()),
                patch.object(
                    api_server,
                    "_get_spacescan_market_context",
                    return_value=_empty_spacescan(),
                ),
                patch.object(
                    api_server, "_get_live_local_offer_edges", return_value={}
                ),
                patch("wallet.get_wallet_balance", return_value=zero_balance),
                patch("wallet.rpc", return_value={"coins": []}),
                patch.object(api_server, "bot", active_bot),
            ):
                resp = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)
        finally:
            api_server.clear_balance_snapshot()
            api_server._active_cat.clear()
            api_server._active_cat.update(original_active_cat)

        self.assertEqual(resp.status_code, 200)
        wallet = resp.get_json()["wallet"]
        self.assertEqual(float(wallet["cat_total"]), 6_500_000.0)
        self.assertEqual(float(wallet["cat_spendable"]), 6_400_000.0)

    def test_stopped_dashboard_prefers_fresh_wallet_offer_snapshot(self):
        """Expired durable rows must not resurrect offers after a fresh empty sync."""
        stale_buys = [{"trade_id": f"buy-{index}"} for index in range(24)]
        stale_sells = [{"trade_id": f"sell-{index}"} for index in range(13)]

        def stale_db_offers(*, side=None, **_kwargs):
            if side == "buy":
                return list(stale_buys)
            if side == "sell":
                return list(stale_sells)
            return list(stale_buys + stale_sells)

        stopped_bot = types.SimpleNamespace(
            get_state=lambda: {"running": False},
            is_running=lambda: False,
            offer_manager=types.SimpleNamespace(
                get_wallet_sync_snapshot=lambda: {
                    "buy": [],
                    "sell": [],
                    "closed": [],
                    "meta": {"fresh": True, "using_cache": False},
                }
            ),
            risk_manager=None,
            market_intel=None,
            coin_manager=None,
            sniper=None,
            boost_manager=None,
            price_engine=None,
            _bot_state={},
            _last_live_offer_edges={},
            _loop_count=0,
            _start_time=0,
            _probe_state={},
        )
        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 12,
            "buy_fills": 0,
            "sell_fills": 12,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "24.9828",
        }
        fake_summary = {
            "xch_free_count": 92,
            "cat_free_count": 43,
            "xch_total": 116,
            "cat_total": 56,
        }

        with (
            patch("database.get_stats", return_value=fake_stats),
            patch("database.get_coin_summary", return_value=fake_summary),
            patch("database.get_live_tier_group_counts", return_value={}),
            patch("database.get_open_offers", side_effect=stale_db_offers),
            patch("database.get_connection", return_value=_make_mock_db_conn()),
            patch.object(
                dashboard_bp,
                "_dashboard_wallet_reads_allowed",
                return_value=False,
            ),
            patch.object(
                api_server,
                "_get_spacescan_market_context",
                return_value=_empty_spacescan(),
            ),
            patch.object(api_server, "bot", stopped_bot),
        ):
            resp = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        performance = resp.get_json()["performance"]
        self.assertEqual(performance["open_buys"], 0)
        self.assertEqual(performance["open_sells"], 0)
        self.assertEqual(performance["open_offers"], 0)

    def test_market_health_uses_live_offer_edges_for_inner_spread(self):
        risk_manager = MagicMock()
        risk_manager.get_inventory_state.return_value = {}
        risk_manager.get_circuit_breaker_blocked_side.return_value = ""
        risk_manager.get_market_health.return_value = {
            "status": "green",
            "message": "ok",
            "conditions": [],
            "metrics": {
                "your_spread_bps": "1770.5",
                "buy_spread_bps": "798.4",
                "sell_spread_bps": "972.1",
            },
        }
        bot = MagicMock()
        bot.risk_manager = risk_manager
        bot._loop_count = 5
        bot._start_time = 0
        bot._bot_state = {"mid_price": "0.0001318526026886049206032406980"}
        bot._probe_state = {}
        bot.market_intel = None
        bot.coin_manager = None
        bot.sniper = None
        bot.boost_manager = None
        bot.price_engine.get_last_price.return_value = (
            "0.0001318526026886049206032406980"
        )

        fake_stats = {
            "realised_pnl_xch": "0",
            "total_fills": 0,
            "buy_fills": 0,
            "sell_fills": 0,
            "round_trips": 0,
            "win_rate": 0,
            "fill_rate_per_hour": 0,
            "avg_spread_capture": "0",
            "pending_verification_count": 0,
            "volume_xch": "0",
        }
        fake_summary = {
            "xch_free_count": 0,
            "cat_free_count": 0,
            "xch_total": 0,
            "cat_total": 0,
        }
        live_edges = {
            "our_best_bid": api_server.Decimal("0.0001297758078408030669426051158"),
            "our_best_ask": api_server.Decimal("0.0001349368190860945260879005506"),
            "our_open_buys": 23,
            "our_open_sells": 23,
            "source": "wallet_sync",
        }

        with (
            patch("database.get_stats", return_value=fake_stats),
            patch("database.get_coin_summary", return_value=fake_summary),
            patch("database.get_open_offers", return_value=[]),
            patch("database.get_connection", return_value=_make_mock_db_conn()),
            patch.object(
                api_server,
                "_get_spacescan_market_context",
                return_value=_empty_spacescan(),
            ),
            patch.object(
                api_server, "_get_live_local_offer_edges", return_value=live_edges
            ),
            patch.object(
                api_server,
                "_active_cat",
                {"asset_id": "aa" * 32, "wallet_id": 2, "decimals": 3},
            ),
            patch.object(api_server, "bot", bot),
        ):
            resp = self.client.get("/api/dashboard", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        metrics = resp.get_json()["market_health"]["metrics"]
        self.assertEqual(metrics["our_best_bid"], str(live_edges["our_best_bid"]))
        self.assertEqual(metrics["our_best_ask"], str(live_edges["our_best_ask"]))
        expected_bps = (
            (live_edges["our_best_ask"] - live_edges["our_best_bid"])
            / api_server.Decimal(bot._bot_state["mid_price"])
            * api_server.Decimal("10000")
        )
        self.assertAlmostEqual(
            float(metrics["your_spread_bps"]), float(expected_bps), places=6
        )

    def test_live_offer_edges_does_not_sync_wallet_when_state_stopped(self):
        sync_from_wallet = MagicMock(return_value=([], [], None))
        stopped_bot = types.SimpleNamespace(
            get_state=lambda: {"running": False},
            is_running=lambda: True,
            offer_manager=types.SimpleNamespace(sync_from_wallet=sync_from_wallet),
        )

        with (
            patch.object(api_server, "bot", stopped_bot),
            patch.object(
                api_server,
                "get_connection",
                return_value=_make_mock_db_conn(),
            ),
        ):
            result = api_server._get_live_local_offer_edges("aa" * 32)

        sync_from_wallet.assert_not_called()
        self.assertEqual(result["source"], "db_open_offers")
        self.assertEqual(result["our_open_buys"], 0)
        self.assertEqual(result["our_open_sells"], 0)

    def test_live_offer_edges_prefers_fresh_stopped_wallet_snapshot_over_stale_db(self):
        """A stopped app must not present stale DB rows as live offers."""
        stale_conn = MagicMock()
        stale_conn.execute.return_value.fetchall.return_value = [
            {
                "side": "buy",
                "min_price": 0.000064,
                "max_price": 0.000065,
                "cnt": 24,
            },
            {
                "side": "sell",
                "min_price": 0.000067,
                "max_price": 0.000068,
                "cnt": 13,
            },
        ]
        stopped_bot = types.SimpleNamespace(
            get_state=lambda: {"running": False},
            is_running=lambda: False,
            offer_manager=types.SimpleNamespace(
                get_wallet_sync_snapshot=lambda: {
                    "buy": [],
                    "sell": [],
                    "closed": [],
                    "meta": {
                        "fresh": True,
                        "using_cache": False,
                        "last_success_at": 123.0,
                    },
                }
            ),
        )

        with (
            patch.object(api_server, "bot", stopped_bot),
            patch.object(api_server, "get_connection", return_value=stale_conn),
        ):
            result = api_server._get_live_local_offer_edges("aa" * 32)

        self.assertEqual(result["source"], "wallet_snapshot")
        self.assertEqual(result["our_best_bid"], api_server.Decimal("0"))
        self.assertEqual(result["our_best_ask"], api_server.Decimal("0"))
        self.assertEqual(result["our_open_buys"], 0)
        self.assertEqual(result["our_open_sells"], 0)

    def test_cat_topup_pool_empty_recommendation_does_not_suggest_coin_prep(self):
        cfg = types.SimpleNamespace(
            TIER_ENABLED=True,
            ENABLE_SELL=True,
            SNIPER_ENABLED=True,
            SNIPER_PREP_COUNT=25,
            SNIPER_SIZE_XCH="0.001",
            SELL_INNER_TIER_SPARE_COUNT=8,
            SELL_MID_TIER_SPARE_COUNT=4,
            SELL_OUTER_TIER_SPARE_COUNT=5,
            SELL_EXTREME_TIER_SPARE_COUNT=2,
        )
        coins = {
            "tier_counts": {
                "enabled": True,
                "cat": {
                    "inner": 8,
                    "mid": 4,
                    "outer": 5,
                    "extreme": 2,
                    "sniper": 24,
                    "reserve": 0,
                    "dust": 0,
                },
                "xch": {},
            }
        }

        recs = dashboard_bp._build_coin_recommendations(cfg, coins, is_running=True)

        self.assertTrue(recs)
        rec = recs[0]
        self.assertEqual(rec["id"], "cat_topup_pool_empty")
        self.assertEqual(rec["action"], "reviewTopupPool")
        self.assertIn("CAT top-up pool", rec["title"])
        self.assertIn("allocate an incoming CAT coin", rec["message"])
        self.assertNotIn("Coin Prep", rec["message"])

    def test_cat_topup_pool_empty_recommendation_waits_during_live_topup(self):
        cfg = types.SimpleNamespace(
            TIER_ENABLED=True,
            ENABLE_SELL=True,
            SNIPER_ENABLED=True,
            SNIPER_PREP_COUNT=25,
            SNIPER_SIZE_XCH="0.001",
            SELL_INNER_TIER_SPARE_COUNT=8,
            SELL_MID_TIER_SPARE_COUNT=4,
            SELL_OUTER_TIER_SPARE_COUNT=5,
            SELL_EXTREME_TIER_SPARE_COUNT=2,
        )
        coins = {
            "topup_running": True,
            "tier_counts": {
                "enabled": True,
                "cat": {
                    "inner": 1,
                    "mid": 4,
                    "outer": 5,
                    "extreme": 2,
                    "sniper": 24,
                    "reserve": 0,
                    "dust": 0,
                },
                "xch": {},
            },
        }

        recs = dashboard_bp._build_coin_recommendations(cfg, coins, is_running=True)

        self.assertEqual(recs, [])

    def test_shape_fix_coin_prep_halt_copy_is_explicitly_nuclear(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_gui.html"),
            encoding="utf-8",
        ) as handle:
            html = handle.read()

        self.assertIn(
            "Stop the bot, review Smart Settings, then run Coin Prep",
            html,
        )
        self.assertNotIn(
            "Could not produce tier-correct coins (run coin prep)",
            html,
        )
        self.assertIn("'reviewTopupPool'", html)
        self.assertIn("CAT top-up pool empty", html)

    def test_dashboard_has_fiat_price_display_hooks(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_gui.html"),
            encoding="utf-8",
        ) as handle:
            html = handle.read()

        self.assertIn('id="ccFiatPrices"', html)
        self.assertIn('id="ccXchUsdPrice"', html)
        self.assertIn('id="ccCatUsdPrice"', html)
        self.assertIn('id="snapshotXchUsd"', html)
        self.assertIn('id="snapshotCatUsd"', html)
        self.assertIn("updateFiatPriceSummary", html)

    def test_status_sync_requests_dashboard_fiat_prices_after_pair_loads(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_gui.html"),
            encoding="utf-8",
        ) as handle:
            html = handle.read()

        self.assertIn("function ensureFiatPricesFromDashboard", html)
        status_sync = html.split("function syncCommandCentreFromStatus(data)")[1]
        status_sync = status_sync.split("let _sseConnection")[0]
        self.assertIn("ensureFiatPricesFromDashboard", status_sync)

    def test_frontend_preserves_verified_balances_when_status_zero_is_placeholder(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_gui.html"),
            encoding="utf-8",
        ) as handle:
            html = handle.read()

        self.assertIn("function mergeVerifiedWalletBalances", html)
        self.assertIn("function _walletBalanceFieldIsPresent", html)
        self.assertIn("function hasVerifiedWalletBalance", html)
        self.assertIn("function resetSmartBalanceSnapshot", html)
        self.assertIn("options.preserveVerifiedOnZero", html)
        self.assertIn("transientStatusZero", html)
        self.assertNotIn("_walletBalanceSideIsZero(merged[sideName])", html)

        fetch_status = html.split("async function fetchStatus()")[1]
        fetch_status = fetch_status.split("function updateUI(data)")[0]
        self.assertIn("{ preserveVerifiedOnZero: true }", fetch_status)

        reset_pair = html.split("function resetPairSelectionState")[1]
        reset_pair = reset_pair.split("function shouldRequireExplicitPairSelection")[0]
        self.assertIn("resetVerifiedWalletBalances();", reset_pair)
        self.assertIn("resetSmartBalanceSnapshot();", reset_pair)

        reserve_helper = html.split("function getWalletBalance(type)")[1]
        reserve_helper = reserve_helper.split("function setReservePercent")[0]
        self.assertIn("hasVerifiedWalletBalance('xch')", reserve_helper)
        self.assertIn("hasVerifiedWalletBalance('cat')", reserve_helper)

        refresh = html.split("async function refreshBalances")[1]
        refresh = refresh.split("async function refreshCATs")[0]
        self.assertIn("mergeVerifiedWalletBalances(data.balances", refresh)

        update_ui = html.split("function updateUI(data)")[1]
        update_ui = update_ui.split("// Coin tracking (free vs locked)")[0]
        self.assertIn("mergeVerifiedWalletBalances", update_ui)

        dashboard = html.split("async function fetchDashboard")[1]
        dashboard = dashboard.split("// Normalize field names")[0]
        self.assertIn("mergeVerifiedWalletBalances", dashboard)

        status_sync = html.split("function syncCommandCentreFromStatus(data)")[1]
        status_sync = status_sync.split("let _sseConnection")[0]
        self.assertIn("mergeVerifiedWalletBalances", status_sync)
        self.assertNotIn(
            "cat_total: Number(data.balances?.cat?.total || 0)", status_sync
        )

    def test_fiat_price_summary_clears_snapshot_fields_when_prices_missing(self):
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_gui.html"),
            encoding="utf-8",
        ) as handle:
            html = handle.read()

        self.assertIn("function resetFiatPriceSummary", html)
        summary = html.split("function updateFiatPriceSummary")[1]
        summary = summary.split("function updateCommandCentre")[0]
        self.assertIn("resetFiatPriceSummary(currentCat);", summary)

        reset = html.split("function resetFiatPriceSummary")[1]
        reset = reset.split("function updateFiatPriceSummary")[0]
        for field_id in (
            "ccXchUsdPrice",
            "ccCatUsdPrice",
            "ccFiatPriceSource",
            "snapshotXchUsd",
            "snapshotCatUsd",
            "snapshotCatUsdLabel",
        ):
            self.assertIn(field_id, reset)


if __name__ == "__main__":
    unittest.main()
