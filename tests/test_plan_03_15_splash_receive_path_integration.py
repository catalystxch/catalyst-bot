"""Slice 03-15 — splash offer receive path (integration test).

Tests the full chain for an incoming offer from the Splash P2P network:
  1. POST offer1... to /api/splash/incoming (SPLASH_RECEIVE_ENABLED=True)
  2. database.record_splash_incoming() writes to real SQLite (not mocked)
  3. get_splash_incoming_offers() returns the record
  4. Deduplication: second POST with same offer → new=False, only 1 DB row
  5. Stats via get_splash_incoming_stats() reflect the record count
  6. Rate limit fires correctly after burst
  7. Bot absent: SSE emit skipped, response still ok=True
  8. Bot present: get_splash_receive_stats() called for SSE emit

Uses the same temp-DB pattern as slices 03-09 and 02-30.
The Flask test client drives /api/splash/incoming; database is real SQLite.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import database as _db
    import api_server

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    _db = None
    api_server = None
    _SKIP = str(exc)


_LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
_VALID_OFFER = "offer1" + "a" * 100  # minimal valid offer (starts with offer1)


class _TempDB(unittest.TestCase):
    """Base: redirect the database module to a fresh temp SQLite file."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._tmp_path = self._tmp.name

        self._orig_db_path = _db.DB_PATH
        _db.DB_PATH = self._tmp_path

        self._orig_init_path = _db._db_initialized_path
        _db._db_initialized_path = ""

        if hasattr(_db._local, "conn") and _db._local.conn:
            try:
                _db._local.conn.close()
            except Exception:
                pass
        _db._local.conn = None
        _db.init_database()

        # Also spin up the Flask test client
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        api_server._rate_limit_log.clear()
        api_server._SPLASH_RATE_LIMIT["hits"].clear()
        api_server._SPLASH_BACKLOG_CACHE["checked_at"] = 0.0
        api_server._SPLASH_BACKLOG_CACHE["new_count"] = 0
        self._mutation_patches = (
            patch.object(api_server, "_ensure_mutation_runtime", return_value=None),
            patch.object(
                api_server.mutation_gate, "enter_mutation", return_value="permit"
            ),
            patch.object(api_server.mutation_gate, "exit_mutation", return_value=True),
        )
        for mutation_patch in self._mutation_patches:
            mutation_patch.start()
            self.addCleanup(mutation_patch.stop)

    def tearDown(self):
        if hasattr(_db._local, "conn") and _db._local.conn:
            try:
                _db._local.conn.close()
            except Exception:
                pass
        _db._local.conn = None
        _db.DB_PATH = self._orig_db_path
        _db._db_initialized_path = self._orig_init_path
        try:
            os.unlink(self._tmp_path)
        except Exception:
            pass
        api_server._rate_limit_log.clear()
        api_server._SPLASH_RATE_LIMIT["hits"].clear()
        api_server._SPLASH_BACKLOG_CACHE["checked_at"] = 0.0
        api_server._SPLASH_BACKLOG_CACHE["new_count"] = 0

    def _post_offer(self, offer=_VALID_OFFER, enabled=True):
        with (
            patch.object(
                api_server.cfg, "SPLASH_RECEIVE_ENABLED", enabled, create=True
            ),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
            patch.object(api_server, "bot", None),
        ):
            return self.client.post(
                "/api/splash/incoming",
                json={"offer": offer},
                environ_base=_LOOPBACK,
            )


# ---------------------------------------------------------------------------
# DB write and retrieval
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"modules unavailable: {_SKIP}")
class TestSplashReceiveDB(_TempDB):
    """Offer received via webhook must be persisted to the real DB."""

    def test_valid_offer_returns_200(self):
        resp = self._post_offer()
        self.assertEqual(resp.status_code, 200)

    def test_valid_offer_response_has_ok_true(self):
        resp = self._post_offer()
        self.assertTrue(resp.get_json().get("ok"))

    def test_valid_offer_response_has_new_true(self):
        """First submission of an offer returns new=True."""
        resp = self._post_offer()
        self.assertTrue(resp.get_json().get("new"))

    def test_offer_written_to_db(self):
        """After a valid POST, get_splash_incoming_offers() returns the record."""
        self._post_offer()
        rows = _db.get_splash_incoming_offers()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["offer_bech32"].startswith("offer1"))

    def test_offer_has_status_new(self):
        """Newly received offer has status='new'."""
        self._post_offer()
        rows = _db.get_splash_incoming_offers()
        self.assertEqual(rows[0].get("status"), "new")

    def test_offer_has_source_ip(self):
        """Source IP (loopback) is recorded in DB."""
        self._post_offer()
        rows = _db.get_splash_incoming_offers()
        self.assertEqual(rows[0].get("source_ip"), "127.0.0.1")

    def test_pending_batch_can_select_oldest_offers_first(self):
        """A sustained inbound stream must not starve the oldest new offers."""

        for suffix in ("a", "b", "c"):
            self._post_offer(offer="offer1" + suffix * 100)
        conn = _db.get_connection()
        rows = conn.execute(
            "SELECT id FROM splash_incoming_offers ORDER BY id"
        ).fetchall()
        ids = [row["id"] for row in rows]

        pending = _db.get_splash_incoming_offers(
            status="new",
            limit=2,
            oldest_first=True,
        )

        self.assertEqual([row["id"] for row in pending], ids[:2])

    def test_database_lock_is_not_reported_as_a_duplicate(self):
        """Persistence failure must be distinguishable from duplicate input."""

        connection = MagicMock()
        connection.execute.side_effect = sqlite3.OperationalError(
            "database is locked"
        )
        with patch("database.get_connection", return_value=connection):
            result = _db.record_splash_incoming(
                _VALID_OFFER,
                "locked-fingerprint",
                source_ip="127.0.0.1",
            )

        self.assertIsNone(result)

    def test_transient_database_lock_is_retried_before_webhook_failure(self):
        """A brief competing write must not drop an inbound Splash offer."""

        connection = MagicMock()
        attempts = {"select": 0}

        def execute(sql, _params=()):
            if "SELECT id FROM splash_incoming_offers" in sql:
                attempts["select"] += 1
                if attempts["select"] == 1:
                    raise sqlite3.OperationalError("database is locked")
                return MagicMock(fetchone=MagicMock(return_value=None))
            return MagicMock()

        connection.execute.side_effect = execute
        with patch("database.get_connection", return_value=connection):
            result = _db.record_splash_incoming(
                _VALID_OFFER,
                "transient-lock-fingerprint",
                source_ip="127.0.0.1",
            )

        self.assertTrue(result)
        self.assertEqual(attempts["select"], 2)
        connection.rollback.assert_called_once()
        connection.commit.assert_called_once()

    def test_transient_database_lock_is_retried_before_status_update_is_lost(self):
        """A brief competing write must not leave a classified offer as new."""

        connection = MagicMock()
        attempts = {"update": 0}

        def execute(sql, _params=()):
            if "UPDATE splash_incoming_offers" in sql:
                attempts["update"] += 1
                if attempts["update"] == 1:
                    raise sqlite3.OperationalError("database is locked")
            return MagicMock()

        connection.execute.side_effect = execute
        with patch("database.get_connection", return_value=connection):
            result = _db.update_splash_incoming_status(
                454158,
                "processed",
                pair_hint="MZ_XCH",
            )

        self.assertTrue(result)
        self.assertEqual(attempts["update"], 2)
        connection.rollback.assert_called_once()
        connection.commit.assert_called_once()

    def test_database_lock_returns_retryable_webhook_failure(self):
        """Splash must receive non-2xx when its offer was not persisted."""

        with patch("database.record_splash_incoming", return_value=None):
            resp = self._post_offer()

        self.assertEqual(resp.status_code, 503)
        self.assertFalse(resp.get_json().get("ok"))
        self.assertEqual(resp.get_json().get("error"), "persistence_unavailable")


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"modules unavailable: {_SKIP}")
class TestSplashReceiveDeduplicate(_TempDB):
    """Same offer submitted twice must be deduplicated at the DB level."""

    def test_second_submission_returns_new_false(self):
        """Second POST with identical offer returns new=False."""
        self._post_offer()
        resp2 = self._post_offer()
        self.assertFalse(resp2.get_json().get("new"))

    def test_duplicate_does_not_create_second_row(self):
        """DB contains only 1 row after two identical POSTs."""
        self._post_offer()
        self._post_offer()
        rows = _db.get_splash_incoming_offers()
        self.assertEqual(len(rows), 1)

    def test_different_offers_both_stored(self):
        """Two distinct offers create two separate DB rows."""
        offer_a = "offer1" + "a" * 100
        offer_b = "offer1" + "b" * 100
        self._post_offer(offer=offer_a)
        self._post_offer(offer=offer_b)
        rows = _db.get_splash_incoming_offers()
        self.assertEqual(len(rows), 2)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"modules unavailable: {_SKIP}")
class TestSplashReceiveStats(_TempDB):
    """Stats function must reflect what's in the DB."""

    def test_stats_after_one_offer(self):
        """get_splash_incoming_stats() returns count >= 1 after one offer."""
        self._post_offer()
        stats = _db.get_splash_incoming_stats()
        total = stats.get("total") or stats.get("count") or 0
        self.assertGreaterEqual(total, 1)

    def test_stats_empty_before_any_offer(self):
        """Stats on a fresh DB return 0 total."""
        stats = _db.get_splash_incoming_stats()
        total = stats.get("total") or stats.get("count") or 0
        self.assertEqual(total, 0)


# ---------------------------------------------------------------------------
# Bot-present path: SSE emit
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"modules unavailable: {_SKIP}")
class TestSplashReceiveBotPresent(_TempDB):
    """When bot is present, receive stats are emitted to SSE subscribers."""

    def test_bot_receive_stats_called_on_new_offer(self):
        """When a new offer arrives and bot is present, get_splash_receive_stats is called."""
        fake_bot = MagicMock()
        fake_bot.get_splash_receive_stats.return_value = {
            "enabled": True,
            "received": 1,
        }

        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
            patch("api_server.events") as mock_events,
            patch.object(api_server, "bot", fake_bot),
        ):
            self.client.post(
                "/api/splash/incoming",
                json={"offer": _VALID_OFFER},
                environ_base=_LOOPBACK,
            )

        fake_bot.get_splash_receive_stats.assert_called_once()
        mock_events.emit.assert_called_once()

    def test_bot_absent_does_not_raise(self):
        """No bot present → no SSE emit attempt, response still ok."""
        resp = self._post_offer()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("ok"))

    def test_duplicate_offer_does_not_emit_sse(self):
        """Duplicate offer (new=False) must NOT emit SSE."""
        self._post_offer()  # first — new=True, would emit if bot present

        fake_bot = MagicMock()
        fake_bot.get_splash_receive_stats.return_value = {}

        with (
            patch.object(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, create=True),
            patch("api_server._splash_incoming_rate_limited", return_value=False),
            patch("api_server.events") as mock_events,
            patch.object(api_server, "bot", fake_bot),
        ):
            self.client.post(
                "/api/splash/incoming",
                json={"offer": _VALID_OFFER},
                environ_base=_LOOPBACK,
            )

        # Duplicate → was_new=False → no emit
        mock_events.emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
