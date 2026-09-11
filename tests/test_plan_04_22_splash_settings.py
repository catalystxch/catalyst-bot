"""Slice 04-22 — splash endpoints + settings/config export tests.

Tests:
  Splash:
    GET  /api/splash/stats           — bot required, returns stats dict
    GET  /api/splash/receive         — bot required, returns receive stats
    POST /api/splash/receive         — toggle enabled flag
    GET  /api/splash/node            — bot required, returns node status
    POST /api/splash/node/start      — bot required, starts node
    POST /api/splash/incoming        — webhook: disabled→403, no offer→400,
                                       bad format→400, oversized→413, ok→200
  Settings:
    GET  /api/settings/defaults      — returns cfg dict with success=True
    POST /api/settings/validate      — empty body→400, valid→{valid,errors,warnings}
  Config export:
    GET  /api/config/export-env      — returns text/plain .env content
"""

import os
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_test_support import permit_api_mutations

try:
    import api_server

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    _SKIP = str(exc)


_LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}


def _make_bot():
    bot = MagicMock()
    bot.splash_manager.get_stats.return_value = {"total_sent": 0}
    bot.splash_manager.check_health.return_value = {"ok": True}
    bot.get_splash_receive_stats.return_value = {"enabled": False, "received": 0}
    bot.splash_node.get_status.return_value = {"running": False}
    bot.splash_node.start.return_value = True
    bot.splash_node.is_running.return_value = False
    return bot


class _FlaskBase(unittest.TestCase):
    _LOOPBACK = _LOOPBACK

    def setUp(self):
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        self.token = api_server._LOCAL_API_TOKEN
        self.auth = {"X-Bot-Local-Token": self.token}
        api_server._rate_limit_log.clear()
        permit_api_mutations(self, api_server)
        api_server._SPLASH_RATE_LIMIT["hits"].clear()
        api_server._SPLASH_RATE_LIMIT["rejected_total"] = 0
        api_server._SPLASH_RECENT_DELIVERIES["fingerprints"].clear()
        api_server._SPLASH_RECENT_DELIVERIES["duplicate_total"] = 0
        api_server._SPLASH_INFLIGHT_DELIVERIES["events"].clear()
        api_server._SPLASH_BACKLOG_CACHE["checked_at"] = 0.0
        api_server._SPLASH_BACKLOG_CACHE["new_count"] = 0

    def tearDown(self):
        api_server._rate_limit_log.clear()
        api_server._SPLASH_RATE_LIMIT["hits"].clear()
        api_server._SPLASH_RATE_LIMIT["rejected_total"] = 0
        api_server._SPLASH_RECENT_DELIVERIES["fingerprints"].clear()
        api_server._SPLASH_RECENT_DELIVERIES["duplicate_total"] = 0
        api_server._SPLASH_INFLIGHT_DELIVERIES["events"].clear()
        api_server._SPLASH_BACKLOG_CACHE["checked_at"] = 0.0
        api_server._SPLASH_BACKLOG_CACHE["new_count"] = 0

    def _get(self, path):
        return self.client.get(path, environ_base=_LOOPBACK)

    def _post(self, path, body=None, auth=True):
        headers = dict(self.auth) if auth else {}
        return self.client.post(
            path,
            json=body or {},
            headers=headers,
            environ_base=_LOOPBACK,
        )


# ---------------------------------------------------------------------------
# GET /api/splash/stats
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSplashStats(_FlaskBase):
    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._get("/api/splash/stats")
        self.assertEqual(resp.status_code, 500)

    def test_returns_200_with_bot(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._get("/api/splash/stats")
        self.assertEqual(resp.status_code, 200)

    def test_response_is_dict(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._get("/api/splash/stats")
        self.assertIsInstance(resp.get_json(), dict)

    def test_response_has_health_key(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._get("/api/splash/stats")
        self.assertIn("health", resp.get_json())

    def test_response_exposes_webhook_backpressure_counters(self):
        api_server._SPLASH_RATE_LIMIT["rejected_total"] = 7
        api_server._SPLASH_RECENT_DELIVERIES["duplicate_total"] = 11
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._get("/api/splash/stats")

        counters = resp.get_json()["receive"]["webhook_backpressure"]
        self.assertEqual(counters["rate_limited_total"], 7)
        self.assertEqual(counters["duplicate_bypassed_total"], 11)


# ---------------------------------------------------------------------------
# GET/POST /api/splash/receive
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSplashReceive(_FlaskBase):
    def test_get_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._get("/api/splash/receive")
        self.assertEqual(resp.status_code, 500)

    def test_get_returns_200_with_bot(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._get("/api/splash/receive")
        self.assertEqual(resp.status_code, 200)

    def test_post_requires_token(self):
        resp = self._post("/api/splash/receive", {"enabled": True}, auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_post_toggle_returns_success(self):
        bot = _make_bot()
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server.cfg, "update"),
            patch("api_server.log_event"),
        ):
            resp = self._post("/api/splash/receive", {"enabled": False})
        body = resp.get_json()
        self.assertTrue(body.get("success"))

    def test_post_response_has_enabled_key(self):
        bot = _make_bot()
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server.cfg, "update"),
            patch("api_server.log_event"),
        ):
            resp = self._post("/api/splash/receive", {"enabled": True})
        self.assertIn("enabled", resp.get_json())


# ---------------------------------------------------------------------------
# GET /api/splash/node
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSplashNode(_FlaskBase):
    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._get("/api/splash/node")
        self.assertEqual(resp.status_code, 500)

    def test_returns_200_with_bot(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._get("/api/splash/node")
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# POST /api/splash/node/start
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSplashNodeStart(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/splash/node/start", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._post("/api/splash/node/start")
        self.assertEqual(resp.status_code, 500)

    def test_returns_200_with_bot(self):
        bot = _make_bot()
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server.cfg, "update"),
            patch("api_server.log_event"),
        ):
            resp = self._post("/api/splash/node/start")
        self.assertEqual(resp.status_code, 200)

    def test_response_has_success_key(self):
        bot = _make_bot()
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server.cfg, "update"),
            patch("api_server.log_event"),
        ):
            resp = self._post("/api/splash/node/start")
        self.assertIn("success", resp.get_json())


# ---------------------------------------------------------------------------
# POST /api/splash/incoming  (webhook)
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSplashIncoming(_FlaskBase):
    """Token-exempt write route, but gated by SPLASH_RECEIVE_ENABLED."""

    def _post_incoming(self, body):
        # /api/splash/incoming is token-exempt — no auth header needed
        return self.client.post(
            "/api/splash/incoming",
            json=body,
            environ_base=_LOOPBACK,
        )

    def test_disabled_returns_403(self):
        with patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", False, create=True):
            resp = self._post_incoming({"offer": "offer1abc"})
        self.assertEqual(resp.status_code, 403)

    def test_missing_offer_returns_400(self):
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
        ):
            resp = self._post_incoming({})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_offer_format_returns_400(self):
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
        ):
            resp = self._post_incoming({"offer": "notanoffer"})
        self.assertEqual(resp.status_code, 400)

    def test_oversized_offer_returns_413(self):
        huge = "offer1" + "x" * 32800
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
        ):
            resp = self._post_incoming({"offer": huge})
        self.assertEqual(resp.status_code, 413)

    def test_valid_offer_returns_200(self):
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
            patch("database.record_splash_incoming", return_value=True),
            patch("api_server.log_event"),
            patch.object(api_server, "bot", None),
        ):
            resp = self._post_incoming({"offer": "offer1valid"})
        self.assertEqual(resp.status_code, 200)

    def test_valid_offer_response_has_ok_key(self):
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
            patch("database.record_splash_incoming", return_value=True),
            patch("api_server.log_event"),
            patch.object(api_server, "bot", None),
        ):
            resp = self._post_incoming({"offer": "offer1valid"})
        self.assertIn("ok", resp.get_json())

    def test_valid_offer_notes_successful_webhook_delivery_on_splash_node(self):
        bot = _make_bot()
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
            patch("database.record_splash_incoming", return_value=False),
            patch.object(api_server, "bot", bot),
        ):
            resp = self._post_incoming({"offer": "offer1duplicate"})

        self.assertEqual(resp.status_code, 200)
        bot.splash_node.note_webhook_delivery.assert_called_once_with()

    def test_rate_limited_returns_429(self):
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=True),
        ):
            resp = self._post_incoming({"offer": "offer1valid"})
        self.assertEqual(resp.status_code, 429)

    def test_concurrent_duplicate_delivery_persists_once(self):
        """Concurrent gossip for one offer must share one persistence attempt."""

        request_barrier = threading.Barrier(2)
        first_persist_started = threading.Event()
        second_persist_started = threading.Event()
        release_persist = threading.Event()
        call_lock = threading.Lock()
        call_count = 0

        def persist_once(*_args, **_kwargs):
            nonlocal call_count
            with call_lock:
                call_count += 1
                current_call = call_count
            if current_call == 1:
                first_persist_started.set()
            else:
                second_persist_started.set()
            release_persist.wait(timeout=2)
            return current_call == 1

        def post_offer():
            request_barrier.wait(timeout=2)
            with api_server.app.test_client() as client:
                return client.post(
                    "/api/splash/incoming",
                    json={"offer": "offer1concurrentduplicate"},
                    environ_base=_LOOPBACK,
                )

        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
            patch(
                "api_server._record_splash_incoming_locked",
                side_effect=persist_once,
            ),
            patch.object(api_server, "bot", None),
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(post_offer) for _ in range(2)]
                self.assertTrue(first_persist_started.wait(timeout=2))
                time.sleep(0.1)
                release_persist.set()
                responses = [future.result(timeout=2) for future in futures]

        self.assertFalse(second_persist_started.is_set())
        self.assertEqual(call_count, 1)
        self.assertTrue(all(response.status_code == 200 for response in responses))

    def test_recent_duplicate_bypasses_rate_limit_and_second_db_write(self):
        """A repeated network offer must not consume scarce webhook capacity."""
        bot = _make_bot()
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch(
                "api_server._splash_incoming_rate_limited",
                side_effect=[False, True],
            ) as rate_limited,
            patch("database.record_splash_incoming", return_value=False) as record_mock,
            patch.object(api_server, "bot", bot),
        ):
            first = self._post_incoming({"offer": "offer1duplicate"})
            second = self._post_incoming({"offer": "offer1duplicate"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.get_json()["new"])
        self.assertTrue(second.get_json()["duplicate"])
        self.assertEqual(rate_limited.call_count, 1)
        self.assertEqual(record_mock.call_count, 1)
        self.assertEqual(
            api_server._splash_incoming_backpressure_stats()[
                "duplicate_bypassed_total"
            ],
            1,
        )

    def test_unseen_offer_remains_rate_limited_after_acknowledged_offer(self):
        """De-duplication must not weaken backpressure for genuinely new data."""
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch(
                "api_server._splash_incoming_rate_limited",
                side_effect=[False, True],
            ),
            patch("database.record_splash_incoming", return_value=True) as record_mock,
            patch.object(api_server, "bot", None),
        ):
            first = self._post_incoming({"offer": "offer1first"})
            second = self._post_incoming({"offer": "offer1second"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json()["error"], "rate_limited")
        self.assertEqual(record_mock.call_count, 1)

    def test_duplicate_gossip_burst_is_acknowledged_without_db_amplification(self):
        """A realistic repeated-gossip burst writes once and preserves protection."""
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch.object(api_server.cfg, "SPLASH_RECEIVE_MAX_PER_SEC", 1, create=True),
            patch("database.record_splash_incoming", return_value=True) as record_mock,
            patch.object(api_server, "bot", None),
        ):
            responses = [
                self._post_incoming({"offer": "offer1networkgossip"})
                for _ in range(100)
            ]
            unseen = self._post_incoming({"offer": "offer1unseen"})

        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertTrue(
            all(
                response.get_json().get("duplicate") is True
                for response in responses[1:]
            )
        )
        self.assertEqual(record_mock.call_count, 1)
        self.assertEqual(unseen.status_code, 429)
        stats = api_server._splash_incoming_backpressure_stats()
        self.assertEqual(stats["duplicate_bypassed_total"], 99)
        self.assertEqual(stats["rate_limited_total"], 1)

    def test_recent_delivery_cache_expires_and_is_bounded(self):
        with (
            patch.object(api_server, "_SPLASH_RECENT_DELIVERY_TTL_S", 10.0),
            patch.object(api_server, "_SPLASH_RECENT_DELIVERY_MAX", 2),
            patch("api_server.time.time", side_effect=[100.0, 101.0, 102.0, 113.0]),
        ):
            api_server._splash_incoming_note_delivery("first")
            api_server._splash_incoming_note_delivery("second")
            api_server._splash_incoming_note_delivery("third")
            self.assertFalse(api_server._splash_incoming_recent_duplicate("second"))

        stats = api_server._splash_incoming_backpressure_stats()
        self.assertLessEqual(stats["recent_fingerprints"], 2)
        self.assertEqual(stats["duplicate_bypassed_total"], 0)

    def test_backlog_full_returns_429_without_db_write(self):
        """A full incoming backlog must reject before attempting another DB write."""
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch.object(
                api_server.cfg, "SPLASH_RECEIVE_MAX_BACKLOG", 250, create=True
            ),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
            patch("database.get_splash_incoming_stats", return_value={"new": 250}),
            patch("database.record_splash_incoming", return_value=True) as record_mock,
        ):
            resp = self._post_incoming({"offer": "offer1valid"})

        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.get_json().get("error"), "backlog_full")
        record_mock.assert_not_called()

    def test_invalid_body_returns_400(self):
        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
        ):
            resp = self.client.post(
                "/api/splash/incoming",
                data="not json",
                content_type="text/plain",
                environ_base=_LOOPBACK,
            )
        self.assertIn(resp.status_code, (400, 415))


# ---------------------------------------------------------------------------
# GET /api/settings/defaults
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSettingsDefaults(_FlaskBase):
    def test_returns_200(self):
        resp = self._get("/api/settings/defaults")
        self.assertEqual(resp.status_code, 200)

    def test_success_key_true(self):
        resp = self._get("/api/settings/defaults")
        self.assertTrue(resp.get_json().get("success"))

    def test_response_is_dict(self):
        resp = self._get("/api/settings/defaults")
        self.assertIsInstance(resp.get_json(), dict)

    def test_no_auth_required(self):
        # GET endpoint — no token needed
        resp = self._get("/api/settings/defaults")
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# POST /api/settings/validate
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSettingsValidate(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/settings/validate", {}, auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_empty_body_returns_400(self):
        resp = self.client.post(
            "/api/settings/validate",
            data="not json",
            content_type="text/plain",
            headers=self.auth,
            environ_base=_LOOPBACK,
        )
        self.assertIn(resp.status_code, (400, 415))

    def test_valid_body_returns_200(self):
        resp = self._post("/api/settings/validate", {"SPREAD_BPS": 100})
        self.assertEqual(resp.status_code, 200)

    def test_response_has_valid_errors_warnings(self):
        resp = self._post("/api/settings/validate", {"SPREAD_BPS": 100})
        body = resp.get_json()
        for key in ("valid", "errors", "warnings"):
            self.assertIn(key, body)

    def test_low_spread_produces_warning(self):
        resp = self._post("/api/settings/validate", {"SPREAD_BPS": 5})
        body = resp.get_json()
        self.assertIsInstance(body.get("warnings"), list)
        self.assertTrue(len(body["warnings"]) > 0)

    def test_invalid_spread_produces_error(self):
        resp = self._post("/api/settings/validate", {"SPREAD_BPS": "abc"})
        body = resp.get_json()
        self.assertFalse(body.get("valid"))
        self.assertTrue(len(body.get("errors", [])) > 0)

    def test_zero_num_offers_produces_error(self):
        resp = self._post("/api/settings/validate", {"NUM_OFFERS": 0})
        body = resp.get_json()
        self.assertFalse(body.get("valid"))


# ---------------------------------------------------------------------------
# GET /api/config/export-env
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestConfigExportEnv(_FlaskBase):
    def test_returns_200(self):
        resp = self._get("/api/config/export-env")
        self.assertEqual(resp.status_code, 200)

    def test_content_type_is_text(self):
        resp = self._get("/api/config/export-env")
        self.assertIn("text/plain", resp.content_type)

    def test_content_disposition_is_attachment(self):
        resp = self._get("/api/config/export-env")
        cd = resp.headers.get("Content-Disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn(".env", cd)

    def test_response_body_contains_env_comment(self):
        resp = self._get("/api/config/export-env")
        text = resp.data.decode("utf-8", errors="replace")
        self.assertIn("CATalyst", text)

    def test_response_body_contains_gui_offer_limits(self):
        resp = self._get("/api/config/export-env")
        text = resp.data.decode("utf-8", errors="replace")
        self.assertIn("MAX_ACTIVE_BUY=", text)
        self.assertIn("MAX_ACTIVE_SELL=", text)

    def test_response_body_contains_tibet_shock_trigger(self):
        resp = self._get("/api/config/export-env")
        text = resp.data.decode("utf-8", errors="replace")
        self.assertIn("TIBET_SHOCK_CANCEL_TRIGGER_PCT=", text)
        self.assertIn("ARB_ALERT_THRESHOLD_BPS=", text)

    def test_no_auth_required(self):
        # Export is a read-only GET
        resp = self._get("/api/config/export-env")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
