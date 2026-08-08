"""Slice 04-01 — status endpoints contract tests.

Tests /api/bot/state, /api/bot/price, and /api/status response contracts:
  - correct status codes for bot=None vs bot-set
  - required keys present in successful responses
  - error shape on failure paths
  - wallet calls skipped when bot provides sufficient state
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import api_server

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    _SKIP = str(exc)


# ---------------------------------------------------------------------------
# Fake bots
# ---------------------------------------------------------------------------


def _fake_bot_stopped():
    """Minimal fake bot in a stopped state with non-zero coin counts."""
    return types.SimpleNamespace(
        is_running=lambda: False,
        _start_time=None,
        get_state=lambda: {
            "running": False,
            "loop_count": 0,
            "loop_duration": 0,
            "loop_seconds": 30,
            "dry_run": True,
            # Non-zero coins so api_bot_state() doesn't fall back to wallet RPC
            "coins": {
                "xch_coins": 5,
                "cat_coins": 3,
                "xch_total_coins": 7,
                "cat_total_coins": 4,
                "xch_locked_coins": 2,
                "cat_locked_coins": 1,
                "xch_balance": {"spendable": 5.0, "total": 7.0},
                "cat_balance": {"spendable": 3.0, "total": 4.0},
                "inventory": {},
            },
            "risk": {"circuit_breaker_tripped": False},
            "stats": {"total_fills": 0, "errors": 0},
            "fills": {"recent": [], "counts": {}},
            "sniper": {"total_snipes": 0},
            "market_intel": {},
            "diagnostics": {},
            "splash": {},
            "splash_node": {"running": False},
            "chia_health": {"status": "not_started"},
            "wallet_type": "sage",
        },
        get_price_info=lambda: {
            "mid_price": "0",
            "last_quoted_buy": "0",
            "last_quoted_sell": "0",
        },
    )


def _fake_bot_running():
    """Minimal fake bot in a running state."""
    return types.SimpleNamespace(
        is_running=lambda: True,
        _start_time=1700000000.0,
        get_state=lambda: {
            "running": True,
            "loop_count": 42,
            "loop_duration": 1.5,
            "loop_seconds": 30,
            "dry_run": False,
            "coins": {
                "xch_coins": 10,
                "cat_coins": 8,
                "xch_total_coins": 15,
                "cat_total_coins": 12,
                "xch_locked_coins": 5,
                "cat_locked_coins": 4,
                "xch_balance": {"spendable": 10.0, "total": 15.0},
                "cat_balance": {"spendable": 8.0, "total": 12.0},
                "inventory": {},
            },
            "risk": {"circuit_breaker_tripped": False},
            "stats": {"total_fills": 5, "errors": 0},
            "fills": {"recent": [], "counts": {"total": 5}},
            "sniper": {"total_snipes": 1},
            "market_intel": {},
            "diagnostics": {},
            "splash": {},
            "splash_node": {"running": False},
            "chia_health": {"status": "healthy"},
            "wallet_type": "sage",
        },
        get_price_info=lambda: {
            "mid_price": "0.00123456",
            "last_quoted_buy": "0.00122000",
            "last_quoted_sell": "0.00124900",
        },
    )


# ---------------------------------------------------------------------------
# Base — Flask test client
# ---------------------------------------------------------------------------


class _FlaskBase(unittest.TestCase):
    _LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

    def setUp(self):
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        api_server._rate_limit_log.clear()

    def tearDown(self):
        api_server._rate_limit_log.clear()


# ---------------------------------------------------------------------------
# 1. /api/bot/state
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestBotStateContract(_FlaskBase):
    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 500)

    def test_bot_none_error_body_has_error_key(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("error", body)

    def test_stopped_bot_returns_200(self):
        with patch.object(api_server, "bot", _fake_bot_stopped()):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_stopped_bot_running_field_false(self):
        with patch.object(api_server, "bot", _fake_bot_stopped()):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertFalse(body.get("running"))

    def test_running_bot_returns_200(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_running_bot_running_field_true(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertTrue(body.get("running"))

    def test_response_is_dict(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        self.assertIsInstance(resp.get_json(), dict)

    def test_loop_count_present(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("loop_count", body)
        self.assertEqual(body["loop_count"], 42)

    def test_coins_key_present(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("coins", body)


# ---------------------------------------------------------------------------
# 2. /api/bot/price
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestBotPriceContract(_FlaskBase):
    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/bot/price", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 500)

    def test_bot_none_error_key(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/bot/price", environ_base=self._LOOPBACK)
        self.assertIn("error", resp.get_json())

    def test_bot_set_returns_200(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/price", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_mid_price_key_present(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/price", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("mid_price", body)

    def test_last_quoted_buy_key_present(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/price", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("last_quoted_buy", body)

    def test_last_quoted_sell_key_present(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/price", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("last_quoted_sell", body)

    def test_price_values_are_strings(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/price", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIsInstance(body["mid_price"], str)
        self.assertIsInstance(body["last_quoted_buy"], str)
        self.assertIsInstance(body["last_quoted_sell"], str)

    def test_price_values_match_fake_bot(self):
        with patch.object(api_server, "bot", _fake_bot_running()):
            resp = self.client.get("/api/bot/price", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertEqual(body["mid_price"], "0.00123456")


# ---------------------------------------------------------------------------
# 3. /api/status — smoke contract (bot=None, no asset_id, startup not authorised)
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestStatusEndpointSmoke(_FlaskBase):
    def setUp(self):
        super().setUp()
        # Patch get_wallet_type to avoid live wallet call
        self._wt_patcher = patch.object(
            api_server, "get_wallet_type", return_value="sage"
        )
        self._wt_patcher.start()
        # Clear active_cat so no TibetSwap/Dexie calls are made
        self._orig_cat = dict(api_server._active_cat)
        api_server._active_cat.clear()

    def tearDown(self):
        self._wt_patcher.stop()
        api_server._active_cat.update(self._orig_cat)
        super().tearDown()

    def test_returns_200_with_no_bot(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_response_is_dict(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        self.assertIsInstance(resp.get_json(), dict)

    def test_running_key_present(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("running", body)

    def test_stats_key_present(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("stats", body)

    def test_balances_key_present(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("balances", body)

    def test_offers_key_present(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("offers", body)

    def test_current_cat_key_present(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("current_cat", body)

    def test_running_false_when_no_bot(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertFalse(body.get("running"))

    def test_no_bot_status_does_not_read_wallet(self):
        with (
            patch.object(api_server, "bot", None),
            patch("wallet.get_all_offers") as get_all_offers,
            patch("wallet.get_spendable_coin_count") as get_spendable_coin_count,
        ):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        get_all_offers.assert_not_called()
        get_spendable_coin_count.assert_not_called()

    def test_idle_health_snapshot_counts_unreachable_live_check_as_failure(self):
        raw_health = {
            "status": "unreachable",
            "healthy": False,
            "wallet": {
                "reachable": False,
                "synced": False,
                "syncing": False,
                "sync_state": "rpc_failed",
            },
            "node": {"reachable": False, "synced": False},
        }

        with (
            patch("chia_node.is_startup_authorised", return_value=True),
            patch("wallet.get_chia_health", return_value=raw_health),
        ):
            health = api_server._get_health_snapshot()

        self.assertEqual(health["status"], "unreachable")
        self.assertGreaterEqual(health["consecutive_failures"], 1)

    def test_status_state_stopped_does_not_read_wallet_even_if_method_true(self):
        stopped_state_bot = _fake_bot_stopped()
        stopped_state_bot.is_running = lambda: True

        with (
            patch.object(api_server, "bot", stopped_state_bot),
            patch("wallet.get_all_offers") as get_all_offers,
            patch("wallet.get_spendable_coin_count") as get_spendable_coin_count,
            patch("wallet.get_wallet_balance") as get_wallet_balance,
        ):
            resp = self.client.get("/api/status", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json().get("running"))
        get_all_offers.assert_not_called()
        get_spendable_coin_count.assert_not_called()
        get_wallet_balance.assert_not_called()

    def test_stopped_bot_state_does_not_read_wallet_for_zero_db_snapshot(self):
        zero_bot = _fake_bot_stopped()
        zero_state = zero_bot.get_state()
        zero_state["coins"] = {
            "xch_coins": 0,
            "cat_coins": 0,
            "xch_total_coins": 0,
            "cat_total_coins": 0,
            "xch_locked_coins": 0,
            "cat_locked_coins": 0,
            "xch_balance": {"spendable": 0, "total": 0},
            "cat_balance": {"spendable": 0, "total": 0},
            "inventory": {},
        }
        zero_bot.get_state = lambda: zero_state

        with (
            patch.object(api_server, "bot", zero_bot),
            patch("database.get_coin_summary", return_value={}),
            patch("wallet.get_spendable_coin_count") as get_spendable_coin_count,
        ):
            resp = self.client.get("/api/bot/state", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        get_spendable_coin_count.assert_not_called()

    def test_stopped_status_reuses_tibet_pairs_for_immediate_polls(self):
        from blueprints import market as market_routes

        with market_routes._TIBET_PAIRS_CACHE_LOCK:
            market_routes._TIBET_PAIRS_CACHE.update(
                {"base": "", "fetched_at": 0.0, "pairs": []}
            )

        asset_id = "abc123cat"
        original_cat = dict(api_server._active_cat)
        api_server._active_cat.update(
            {
                "asset_id": asset_id,
                "ticker_id": "ABC_XCH",
                "decimals": 3,
                "name": "ABC",
            }
        )

        class FakeResponse:
            status_code = 200

            def json(self):
                return [
                    {
                        "asset_id": asset_id,
                        "xch_reserve": 1_000_000_000_000,
                        "token_reserve": 1_000,
                    }
                ]

        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append(str(url))
            return FakeResponse()

        try:
            with (
                patch.object(api_server, "bot", _fake_bot_stopped()),
                patch("database.get_coin_summary", return_value={}),
                patch("requests.get", side_effect=fake_get),
            ):
                self.client.get("/api/status", environ_base=self._LOOPBACK)
                self.client.get("/api/status", environ_base=self._LOOPBACK)
        finally:
            api_server._active_cat.clear()
            api_server._active_cat.update(original_cat)

        tibet_calls = [url for url in calls if "tibetswap" in url]
        self.assertEqual(len(tibet_calls), 1)

    def test_stopped_status_keeps_active_cat_when_prebot_price_cache_is_used(self):
        from blueprints import bot as bot_routes

        asset_id = "b" * 64
        original_cat = dict(api_server._active_cat)
        original_cache = getattr(bot_routes, "_prebot_price_cache", None)
        api_server._active_cat.update(
            {
                "asset_id": asset_id,
                "wallet_id": 7,
                "ticker_id": "BBC_XCH",
                "decimals": 3,
                "name": "BBC",
            }
        )
        bot_routes._prebot_price_cache = {
            "fetched_at": 9_999_999_999.0,
            "pricing": {"bid": 1, "mid": 2, "ask": 3},
            "asset_id": asset_id,
        }

        try:
            with patch.object(api_server, "bot", None):
                resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        finally:
            if original_cache is None:
                try:
                    delattr(bot_routes, "_prebot_price_cache")
                except AttributeError:
                    pass
            else:
                bot_routes._prebot_price_cache = original_cache
            api_server._active_cat.clear()
            api_server._active_cat.update(original_cat)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["current_cat"]["asset_id"], asset_id)

    def test_stopped_status_reuses_verified_balance_after_refresh(self):
        from blueprints import bot as bot_routes

        asset_id = "c" * 64
        original_cat = dict(api_server._active_cat)
        original_cache = getattr(bot_routes, "_prebot_price_cache", None)
        if hasattr(api_server, "clear_balance_snapshot"):
            api_server.clear_balance_snapshot()
        api_server._active_cat.update(
            {
                "asset_id": asset_id,
                "wallet_id": 9,
                "ticker_id": "CBC_XCH",
                "decimals": 3,
                "name": "CBC",
            }
        )
        bot_routes._prebot_price_cache = {
            "fetched_at": 9_999_999_999.0,
            "pricing": {"bid": 1, "mid": 2, "ask": 3},
            "asset_id": asset_id,
        }
        xch_balance = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 3_000_000_000_000,
                "spendable_balance": 2_500_000_000_000,
            },
        }
        cat_balance = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 4_200_000_000,
                "spendable_balance": 4_100_000_000,
            },
        }

        try:
            with patch(
                "wallet.get_wallet_balance", side_effect=[xch_balance, cat_balance]
            ):
                refresh = self.client.post(
                    "/api/balances/refresh",
                    headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
                    environ_base=self._LOOPBACK,
                )
            with patch.object(api_server, "bot", None):
                resp = self.client.get("/api/status", environ_base=self._LOOPBACK)
        finally:
            if hasattr(api_server, "clear_balance_snapshot"):
                api_server.clear_balance_snapshot()
            if original_cache is None:
                try:
                    delattr(bot_routes, "_prebot_price_cache")
                except AttributeError:
                    pass
            else:
                bot_routes._prebot_price_cache = original_cache
            api_server._active_cat.clear()
            api_server._active_cat.update(original_cat)

        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(resp.status_code, 200)
        balances = resp.get_json()["balances"]
        self.assertEqual(balances["xch"]["total"], 3.0)
        self.assertEqual(balances["cat"]["total"], 4_200_000.0)


# ---------------------------------------------------------------------------
# 4. Write-guard — POST without token returns 401 (before Flask method-check)
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestStatusEndpointWriteGuards(_FlaskBase):
    """The before_request guard intercepts POST requests without a valid token
    and returns 401 — before Flask can return 405 for a GET-only route."""

    def test_bot_state_post_no_token_returns_401(self):
        resp = self.client.post("/api/bot/state", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 401)

    def test_bot_price_post_no_token_returns_401(self):
        resp = self.client.post("/api/bot/price", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 401)

    def test_status_post_no_token_returns_401(self):
        resp = self.client.post("/api/status", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 401)

    def test_bot_state_post_with_token_returns_405(self):
        """Valid token passes auth but Flask still rejects POST on GET-only route."""
        headers = {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}
        resp = self.client.post(
            "/api/bot/state", headers=headers, environ_base=self._LOOPBACK
        )
        self.assertEqual(resp.status_code, 405)


if __name__ == "__main__":
    unittest.main()
