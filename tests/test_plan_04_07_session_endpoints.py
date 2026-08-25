"""Slice 04-07 — session endpoint contract tests.

Tests POST /api/session/fresh-start, POST /api/session/resume-chosen,
GET /api/check-resume:
  - Auth required for write endpoints
  - Response shape and required keys
  - check-resume branches: bot running, fresh-start set, wallet offers
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_test_support import permit_api_mutations

try:
    import api_server

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    _SKIP = str(exc)


_FAKE_SESSION_SUMMARY = {
    "success": True,
    "fills_cleared": 0,
    "round_trips_cleared": 0,
    "price_history_cleared": False,
    "inventory_cleared": False,
    "coins_cleared": 0,
    "open_offers_cancelled": 0,
    "reset_at": "2026-01-01T00:00:00",
    "preserve_history": False,
}


class _FlaskBase(unittest.TestCase):
    _LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

    def setUp(self):
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        self.token = api_server._LOCAL_API_TOKEN
        self.auth = {"X-Bot-Local-Token": self.token}
        api_server._rate_limit_log.clear()
        permit_api_mutations(self, api_server)

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
# 1. POST /api/session/fresh-start
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSessionFreshStart(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/session/fresh-start", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_returns_200(self):
        with (
            patch.object(
                api_server,
                "_reset_fresh_run_session",
                return_value=_FAKE_SESSION_SUMMARY,
            ),
            patch.object(api_server, "_fresh_start_set"),
        ):
            resp = self._post("/api/session/fresh-start")
        self.assertEqual(resp.status_code, 200)

    def test_success_key_true(self):
        with (
            patch.object(
                api_server,
                "_reset_fresh_run_session",
                return_value=_FAKE_SESSION_SUMMARY,
            ),
            patch.object(api_server, "_fresh_start_set"),
        ):
            resp = self._post("/api/session/fresh-start")
        self.assertTrue(resp.get_json().get("success"))

    def test_response_has_message(self):
        with (
            patch.object(
                api_server,
                "_reset_fresh_run_session",
                return_value=_FAKE_SESSION_SUMMARY,
            ),
            patch.object(api_server, "_fresh_start_set"),
        ):
            resp = self._post("/api/session/fresh-start")
        self.assertIn("message", resp.get_json())

    def test_fresh_start_set_is_called(self):
        with (
            patch.object(
                api_server,
                "_reset_fresh_run_session",
                return_value=_FAKE_SESSION_SUMMARY,
            ),
            patch.object(api_server, "_fresh_start_set") as mock_set,
        ):
            self._post("/api/session/fresh-start")
        mock_set.assert_called_once()


# ---------------------------------------------------------------------------
# 2. POST /api/session/resume-chosen
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSessionResumeChosen(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/session/resume-chosen", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_returns_200(self):
        with patch.object(api_server, "_fresh_start_clear"):
            resp = self._post("/api/session/resume-chosen")
        self.assertEqual(resp.status_code, 200)

    def test_success_key_true(self):
        with patch.object(api_server, "_fresh_start_clear"):
            resp = self._post("/api/session/resume-chosen")
        self.assertTrue(resp.get_json().get("success"))

    def test_fresh_start_clear_is_called(self):
        with patch.object(api_server, "_fresh_start_clear") as mock_clear:
            self._post("/api/session/resume-chosen")
        mock_clear.assert_called_once()


# ---------------------------------------------------------------------------
# 3. GET /api/check-resume
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCheckResume(_FlaskBase):
    def test_returns_200(self):
        with (
            patch("chia_node.is_startup_authorised", return_value=True),
            patch("wallet.get_all_offers", return_value=[]),
            patch.object(api_server, "bot", None),
            patch.object(api_server, "_fresh_start_is_set", return_value=False),
        ):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_response_has_can_resume_key(self):
        with (
            patch("chia_node.is_startup_authorised", return_value=True),
            patch("wallet.get_all_offers", return_value=[]),
            patch.object(api_server, "bot", None),
            patch.object(api_server, "_fresh_start_is_set", return_value=False),
        ):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)
        self.assertIn("can_resume", resp.get_json())

    def test_bot_running_returns_cannot_resume(self):
        bot = MagicMock()
        bot._loop_count = 5
        bot.is_running.return_value = True
        with patch.object(api_server, "bot", bot):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertFalse(body["can_resume"])
        self.assertEqual(body.get("reason"), "bot_already_running")

    def test_stopped_bot_with_completed_loops_can_resume_live_offers(self):
        """Stopping after live cycles must expose the existing Sage ladder."""
        fake_buy = {"trade_id": "live-buy", "status": "active", "side": "buy"}
        fake_sell = {
            "trade_id": "live-sell",
            "status": "active",
            "side": "sell",
        }
        offer_manager = MagicMock()
        offer_manager.sync_from_wallet.return_value = ([fake_buy], [fake_sell], [])
        bot = MagicMock()
        bot._loop_count = 46
        bot.is_running.return_value = False
        bot.offer_manager = offer_manager

        with (
            patch("chia_node.is_startup_authorised", return_value=True),
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "_fresh_start_is_set", return_value=False),
            patch("api_server.get_connection", return_value=MagicMock()),
            patch("database.get_connection", return_value=MagicMock()),
            patch("database.get_open_offers", return_value=[]),
        ):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)

        body = resp.get_json()
        self.assertTrue(body["can_resume"])
        self.assertEqual(body["buy_count"], 1)
        self.assertEqual(body["sell_count"], 1)
        offer_manager.sync_from_wallet.assert_called_once_with()

    def test_fresh_start_set_returns_cannot_resume(self):
        with (
            patch.object(api_server, "bot", None),
            patch.object(api_server, "_fresh_start_is_set", return_value=True),
        ):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertFalse(body["can_resume"])
        self.assertEqual(body.get("reason"), "fresh_start_chosen")

    def test_no_wallet_offers_returns_cannot_resume(self):
        with (
            patch("chia_node.is_startup_authorised", return_value=True),
            patch("wallet.get_all_offers", return_value=[]),
            patch.object(api_server, "bot", None),
            patch.object(api_server, "_fresh_start_is_set", return_value=False),
        ):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertFalse(body["can_resume"])

    def test_open_offers_returns_can_resume(self):
        fake_offer = {"trade_id": "abc", "status": "PENDING_ACCEPT"}
        with (
            patch("chia_node.is_startup_authorised", return_value=True),
            patch("wallet.get_all_offers", return_value=[fake_offer]),
            patch(
                "wallet.classify_offers_from_list", return_value=([fake_offer], [], [])
            ),
            patch("api_server.get_connection", return_value=MagicMock()),
            patch("database.get_connection", return_value=MagicMock()),
            patch("database.get_open_offers", return_value=[]),
            patch.object(api_server, "bot", None),
            patch.object(api_server, "_fresh_start_is_set", return_value=False),
        ):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertTrue(body["can_resume"])
        self.assertIn("buy_count", body)
        self.assertIn("sell_count", body)

    def test_open_offers_refreshes_offer_manager_snapshot_for_status_ui(self):
        """Resume detection and the stopped status UI must share one live book."""
        fake_buy = {"trade_id": "live-buy", "status": "active", "side": "buy"}
        fake_sell = {
            "trade_id": "live-sell",
            "status": "active",
            "side": "sell",
        }
        offer_manager = MagicMock()
        offer_manager.sync_from_wallet.return_value = ([fake_buy], [fake_sell], [])
        bot = MagicMock()
        bot._loop_count = 0
        bot.is_running.return_value = False
        bot.offer_manager = offer_manager

        with (
            patch("chia_node.is_startup_authorised", return_value=True),
            patch("wallet.get_all_offers") as get_all_offers,
            patch("api_server.get_connection", return_value=MagicMock()),
            patch("database.get_connection", return_value=MagicMock()),
            patch("database.get_open_offers", return_value=[]),
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "_fresh_start_is_set", return_value=False),
        ):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["buy_count"], 1)
        self.assertEqual(body["sell_count"], 1)
        offer_manager.sync_from_wallet.assert_called_once_with()
        get_all_offers.assert_not_called()

    def test_wallet_not_started_does_not_query_offers(self):
        with (
            patch.object(api_server, "bot", None),
            patch.object(api_server, "_fresh_start_is_set", return_value=False),
            patch("chia_node.is_startup_authorised", return_value=False),
            patch("wallet.get_all_offers") as get_all_offers,
        ):
            resp = self.client.get("/api/check-resume", environ_base=self._LOOPBACK)

        body = resp.get_json()
        self.assertFalse(body["can_resume"])
        self.assertEqual(body.get("reason"), "wallet_not_started")
        get_all_offers.assert_not_called()


if __name__ == "__main__":
    unittest.main()
