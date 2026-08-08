"""Slice 04-11 — trading-pair endpoint contract tests.

Tests GET /api/cats, POST /api/cat/select, POST /api/cat/refresh:
  - Auth required for write endpoints
  - Input validation (asset_id format, name/ticker length, decimals range)
  - bot-running gate on cat/select (409)
  - Response shapes
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import api_server

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    _SKIP = str(exc)

# Valid 64-hex asset_id for test use
_VALID_ASSET_ID = "a" * 64
_VALID_BODY = {
    "asset_id": _VALID_ASSET_ID,
    "wallet_id": 2,
    "name": "TestCAT",
    "decimals": 3,
}


class _FlaskBase(unittest.TestCase):
    _LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

    def setUp(self):
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        self.token = api_server._LOCAL_API_TOKEN
        self.auth = {"X-Bot-Local-Token": self.token}
        api_server._rate_limit_log.clear()

    def tearDown(self):
        api_server._rate_limit_log.clear()

    def _post(self, path, body=None, auth=True):
        headers = dict(self.auth) if auth else {}
        return self.client.post(
            path,
            json=body or {},
            headers=headers,
            environ_base=self._LOOPBACK,
        )


# ---------------------------------------------------------------------------
# 1. GET /api/cats
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCatsGet(_FlaskBase):
    def test_returns_200(self):
        with (
            patch("wallet.get_wallets", return_value={"success": True, "wallets": []}),
            patch("wallet.get_wallet_type", return_value="sage"),
        ):
            resp = self.client.get("/api/cats", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_response_has_cats_list(self):
        with (
            patch("wallet.get_wallets", return_value={"success": True, "wallets": []}),
            patch("wallet.get_wallet_type", return_value="sage"),
        ):
            resp = self.client.get("/api/cats", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("cats", body)
        self.assertIsInstance(body["cats"], list)

    def test_no_wallet_cats_returns_list(self):
        # With no wallet CATs, list may still contain the active CAT
        # (pre-populated from _active_cat / .env). Just verify it's a list.
        with (
            patch("wallet.get_wallets", return_value={"success": True, "wallets": []}),
            patch("wallet.get_wallet_type", return_value="sage"),
        ):
            resp = self.client.get("/api/cats", environ_base=self._LOOPBACK)
        self.assertIsInstance(resp.get_json()["cats"], list)


# ---------------------------------------------------------------------------
# 2. POST /api/cat/select
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCatSelect(_FlaskBase):
    def _mocked_post(self, body):
        with (
            patch.object(api_server.cfg, "update"),
            patch("threading.Thread") as mt,
            patch("wallet.notify_cat_asset_id_changed"),
            patch.object(api_server, "bot", None),
        ):
            mt.return_value.start = MagicMock()
            return self._post("/api/cat/select", body)

    def test_requires_token(self):
        resp = self._post("/api/cat/select", _VALID_BODY, auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_invalid_body_returns_error(self):
        # Flask returns 415 Unsupported Media Type for non-JSON content type
        # (newer Flask), or 400 if get_json() returns None and the route checks it
        resp = self.client.post(
            "/api/cat/select",
            data="not json",
            content_type="text/plain",
            headers=self.auth,
            environ_base=self._LOOPBACK,
        )
        self.assertIn(resp.status_code, (400, 415))

    def test_asset_id_too_short_returns_400(self):
        body = {**_VALID_BODY, "asset_id": "abc123"}
        resp = self._mocked_post(body)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json().get("success"))

    def test_asset_id_non_hex_returns_400(self):
        body = {**_VALID_BODY, "asset_id": "z" * 64}
        resp = self._mocked_post(body)
        self.assertEqual(resp.status_code, 400)

    def test_name_too_long_returns_400(self):
        body = {**_VALID_BODY, "name": "x" * 129}
        resp = self._mocked_post(body)
        self.assertEqual(resp.status_code, 400)

    def test_ticker_too_long_returns_400(self):
        body = {**_VALID_BODY, "ticker_id": "T" * 65}
        resp = self._mocked_post(body)
        self.assertEqual(resp.status_code, 400)

    def test_invalid_decimals_returns_400(self):
        body = {**_VALID_BODY, "decimals": 99}
        resp = self._mocked_post(body)
        self.assertEqual(resp.status_code, 400)

    def test_negative_decimals_returns_400(self):
        body = {**_VALID_BODY, "decimals": -1}
        resp = self._mocked_post(body)
        self.assertEqual(resp.status_code, 400)

    def test_bot_running_returns_409(self):
        running_bot = MagicMock()
        running_bot.is_running.return_value = True
        with patch.object(api_server, "bot", running_bot):
            resp = self._post("/api/cat/select", _VALID_BODY)
        self.assertEqual(resp.status_code, 409)

    def test_valid_body_returns_200(self):
        resp = self._mocked_post(_VALID_BODY)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("success"))

    def test_response_echoes_asset_id(self):
        resp = self._mocked_post(_VALID_BODY)
        body = resp.get_json()
        self.assertEqual(body.get("asset_id"), _VALID_ASSET_ID)

    def test_sage_select_normalizes_synthetic_wallet_id_to_active_id(self):
        original_active_cat = dict(api_server._active_cat)
        original_cat_wallet_id = api_server.cfg.CAT_WALLET_ID
        try:
            api_server.cfg.CAT_WALLET_ID = 1000
            body = {**_VALID_BODY, "wallet_id": 1000}
            with (
                patch.object(api_server.cfg, "update"),
                patch("threading.Thread") as mt,
                patch.object(api_server, "get_wallet_type", return_value="sage"),
                patch("wallet.notify_cat_asset_id_changed"),
                patch.object(api_server, "bot", None),
            ):
                mt.return_value.start = MagicMock()
                resp = self._post("/api/cat/select", body)

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json().get("wallet_id"), 2)
            self.assertEqual(api_server._active_cat.get("wallet_id"), 2)
            self.assertEqual(api_server.cfg.CAT_WALLET_ID, 2)
        finally:
            api_server.clear_balance_snapshot()
            api_server.cfg.CAT_WALLET_ID = original_cat_wallet_id
            api_server._active_cat.clear()
            api_server._active_cat.update(original_active_cat)


# ---------------------------------------------------------------------------
# 3. POST /api/cat/refresh
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCatRefresh(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/cat/refresh", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_returns_200(self):
        with patch.object(api_server.cfg, "reload"):
            resp = self._post("/api/cat/refresh")
        self.assertEqual(resp.status_code, 200)

    def test_success_key_true(self):
        with patch.object(api_server.cfg, "reload"):
            resp = self._post("/api/cat/refresh")
        self.assertTrue(resp.get_json().get("success"))

    def test_cfg_reload_is_called(self):
        with patch.object(api_server.cfg, "reload") as mock_reload:
            self._post("/api/cat/refresh")
        mock_reload.assert_called_once()


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestBalanceRefresh(_FlaskBase):
    def test_sage_balance_refresh_uses_active_asset_wallet_id_after_remap(self):
        original_active_cat = dict(api_server._active_cat)
        original_cat_wallet_id = api_server.cfg.CAT_WALLET_ID
        api_server.cfg.CAT_WALLET_ID = 1000
        api_server._active_cat.clear()
        api_server._active_cat.update(
            {
                "asset_id": _VALID_ASSET_ID,
                "wallet_id": 1000,
                "name": "TestCAT",
                "decimals": 3,
            }
        )

        calls = []

        def fake_balance(wallet_id):
            calls.append(wallet_id)
            if wallet_id == 1:
                mojos = 5_000_000_000_000
            elif wallet_id == 2:
                mojos = 1_000_000 * 1_000
            else:
                mojos = 0
            return {
                "success": True,
                "wallet_balance": {
                    "confirmed_wallet_balance": mojos,
                    "spendable_balance": mojos,
                },
            }

        try:
            with (
                patch("wallet.WALLET_ID_XCH", 1),
                patch.object(api_server, "get_wallet_type", return_value="sage"),
                patch("wallet.get_wallet_balance", side_effect=fake_balance),
                patch("wallet.notify_cat_asset_id_changed") as notify_cat,
            ):
                resp = self._post("/api/balances/refresh")

            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertTrue(body.get("success"))
            self.assertEqual(calls, [1, 2])
            self.assertEqual(body["balances"]["cat"]["total"], 1_000_000)
            self.assertEqual(api_server._active_cat.get("wallet_id"), 2)
            self.assertEqual(api_server.cfg.CAT_WALLET_ID, 2)
            notify_cat.assert_called_once_with(_VALID_ASSET_ID)
        finally:
            api_server.cfg.CAT_WALLET_ID = original_cat_wallet_id
            api_server._active_cat.clear()
            api_server._active_cat.update(original_active_cat)

    def test_status_keeps_refreshed_sage_cat_balance_before_bot_start(self):
        import blueprints.bot as bot_blueprint

        original_active_cat = dict(api_server._active_cat)
        original_cat_wallet_id = api_server.cfg.CAT_WALLET_ID
        original_price_cache = getattr(bot_blueprint, "_prebot_price_cache", None)
        api_server.cfg.CAT_WALLET_ID = 1000
        api_server._active_cat.clear()
        api_server._active_cat.update(
            {
                "asset_id": _VALID_ASSET_ID,
                "wallet_id": 1000,
                "name": "TestCAT",
                "decimals": 3,
                "ticker_id": "TEST_XCH",
            }
        )
        bot_blueprint._prebot_price_cache = {
            "fetched_at": time.time(),
            "pricing": {"bid": 0, "mid": 0, "ask": 0},
            "asset_id": _VALID_ASSET_ID,
        }

        calls = []

        def fake_balance(wallet_id):
            calls.append(wallet_id)
            if wallet_id == 1:
                mojos = 5_000_000_000_000
            elif wallet_id == 2:
                mojos = 1_000_000 * 1_000
            else:
                mojos = 0
            return {
                "success": True,
                "wallet_balance": {
                    "confirmed_wallet_balance": mojos,
                    "spendable_balance": mojos,
                },
            }

        try:
            with (
                patch("wallet.WALLET_ID_XCH", 1),
                patch.object(api_server, "bot", None),
                patch.object(api_server, "get_wallet_type", return_value="sage"),
                patch("wallet.get_wallet_balance", side_effect=fake_balance),
                patch("wallet.notify_cat_asset_id_changed"),
            ):
                refresh_resp = self._post("/api/balances/refresh")
                status_resp = self.client.get(
                    "/api/status", environ_base=self._LOOPBACK
                )

            self.assertEqual(refresh_resp.status_code, 200)
            self.assertEqual(status_resp.status_code, 200)
            self.assertEqual(calls, [1, 2])
            body = status_resp.get_json()
            self.assertEqual(body["balances"]["cat"]["total"], 1_000_000)
            self.assertEqual(body["balances"]["cat"]["spendable"], 1_000_000)
            self.assertEqual(body["current_cat"]["asset_id"], _VALID_ASSET_ID)
            self.assertEqual(body["current_cat"]["wallet_id"], 2)
        finally:
            api_server.cfg.CAT_WALLET_ID = original_cat_wallet_id
            api_server._active_cat.clear()
            api_server._active_cat.update(original_active_cat)
            if original_price_cache is None:
                try:
                    delattr(bot_blueprint, "_prebot_price_cache")
                except AttributeError:
                    pass
            else:
                bot_blueprint._prebot_price_cache = original_price_cache

    def test_balance_refresh_ignores_transient_cat_zero_after_verified_balance(self):
        original_active_cat = dict(api_server._active_cat)
        original_cat_wallet_id = api_server.cfg.CAT_WALLET_ID
        api_server.cfg.CAT_WALLET_ID = 1000
        api_server._active_cat.clear()
        api_server._active_cat.update(
            {
                "asset_id": _VALID_ASSET_ID,
                "wallet_id": 1000,
                "name": "TestCAT",
                "decimals": 3,
                "ticker_id": "TEST_XCH",
            }
        )

        xch_ok = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 5_000_000_000_000,
                "spendable_balance": 4_000_000_000_000,
            },
        }
        cat_ok = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 6_500_000_000,
                "spendable_balance": 6_400_000_000,
            },
        }
        cat_zero = {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 0,
                "spendable_balance": 0,
            },
        }

        try:
            with (
                patch("wallet.WALLET_ID_XCH", 1),
                patch.object(api_server, "get_wallet_type", return_value="sage"),
                patch(
                    "wallet.get_wallet_balance",
                    side_effect=[xch_ok, cat_ok, xch_ok, cat_zero],
                ),
                patch("wallet.notify_cat_asset_id_changed"),
            ):
                first = self._post("/api/balances/refresh")
                second = self._post("/api/balances/refresh")

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            body = second.get_json()
            self.assertEqual(body["balances"]["cat"]["total"], 6_500_000)
            self.assertEqual(body["balances"]["cat"]["spendable"], 6_400_000)
        finally:
            api_server.cfg.CAT_WALLET_ID = original_cat_wallet_id
            api_server._active_cat.clear()
            api_server._active_cat.update(original_active_cat)
            api_server.clear_balance_snapshot()


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSageWalletIdNormalization(unittest.TestCase):
    def test_active_cat_wallet_id_uses_fixed_sage_id(self):
        with patch.object(api_server, "get_wallet_type", return_value="sage"):
            self.assertEqual(api_server.active_cat_wallet_id(1000, _VALID_ASSET_ID), 2)

    def test_active_cat_wallet_id_preserves_chia_id(self):
        with patch.object(api_server, "get_wallet_type", return_value="chia"):
            self.assertEqual(
                api_server.active_cat_wallet_id(1000, _VALID_ASSET_ID),
                1000,
            )

    def test_status_and_dashboard_balance_paths_use_active_cat_wallet_helper(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = (
            root / "src" / "catalyst" / "blueprints" / "dashboard.py"
        ).read_text(encoding="utf-8")
        status = (root / "src" / "catalyst" / "blueprints" / "bot.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("api_server.active_cat_wallet_id", dashboard)
        self.assertIn("api_server.active_cat_wallet_id", status)

    def test_cat_blueprint_routes_notify_through_wallet_facade(self):
        root = Path(__file__).resolve().parents[1]
        cat_blueprint = (root / "src" / "catalyst" / "blueprints" / "cat.py").read_text(
            encoding="utf-8"
        )
        wallet = (root / "src" / "catalyst" / "wallet.py").read_text(encoding="utf-8")

        self.assertIn("from wallet import notify_cat_asset_id_changed", cat_blueprint)
        self.assertNotIn(
            "from wallet_sage import notify_cat_asset_id_changed",
            cat_blueprint,
        )
        self.assertIn("notify_cat_asset_id_changed", wallet)


if __name__ == "__main__":
    unittest.main()
