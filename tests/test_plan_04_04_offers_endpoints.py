"""Slice 04-04 — offers endpoint contract tests.

Tests /api/offers, /api/offers/cancel_all/status, /api/offers/open_count,
/api/offers/cancel_all (POST), /api/offers/cancel (POST):
  - Auth required for write endpoints
  - bot=None → 500 for bot-dependent reads
  - Response shapes and required keys
  - Input validation (missing trade_id, bad JSON)
"""

import os
import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_test_support import permit_api_mutations

ROOT = Path(__file__).resolve().parents[1]

try:
    import api_server

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    _SKIP = str(exc)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


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


def _make_bot(offers=([], [], [])):
    bot = MagicMock()
    bot.is_running.return_value = True
    bot.offer_manager.sync_from_wallet.return_value = offers
    bot.offer_manager.cancel_all.return_value = {"cancelled": [], "failed": []}
    bot.offer_manager.cancel_offers.return_value = {"success": True}
    bot.coin_manager.is_busy.return_value = False
    return bot


def test_generic_cancel_all_progress_consumer_never_claims_terminal_confirmation():
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the bounded GUI consumer test")
    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    helper_source = (
        "function cancelAllProgressView"
        + gui_source.split("function cancelAllProgressView", 1)[1].split(
            "function renderCancelAllProgress", 1
        )[0]
    )
    status = {
        "phase": "complete",
        "total": 3,
        "pending": 2,
        "failed": 1,
        "cancelled": 99,
        "message": "Cancellation requests journaled",
    }
    script = (
        helper_source
        + "\nconsole.log(JSON.stringify(cancelAllProgressView(JSON.parse(process.argv[1]), 0)));"
    )
    completed = subprocess.run(
        [node, "-e", script, json.dumps(status)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    view = json.loads(completed.stdout)

    assert view["total"] == 3
    assert view["pending"] == 2
    assert view["failed"] == 1
    assert view["processed"] == 3
    assert view["isDone"] is True
    assert view["severity"] == "warning"
    assert "pending authoritative reconciliation" in view["message"]
    assert "confirmed" not in json.dumps(view).lower()


# ---------------------------------------------------------------------------
# 1. GET /api/offers
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestOffersGet(_FlaskBase):
    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self.client.get("/api/offers", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 500)

    def test_bot_set_returns_200(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self.client.get("/api/offers", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_response_has_buys_sells_counts(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self.client.get("/api/offers", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("buys", body)
        self.assertIn("sells", body)
        self.assertIn("buy_count", body)
        self.assertIn("sell_count", body)

    def test_empty_offers_returns_zero_counts(self):
        with patch.object(api_server, "bot", _make_bot(offers=([], [], []))):
            resp = self.client.get("/api/offers", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertEqual(body["buy_count"], 0)
        self.assertEqual(body["sell_count"], 0)


# ---------------------------------------------------------------------------
# 2. GET /api/offers/cancel_all/status
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCancelAllStatus(_FlaskBase):
    def test_returns_200_always(self):
        resp = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        )
        self.assertEqual(resp.status_code, 200)

    def test_response_has_success_key(self):
        resp = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        )
        body = resp.get_json()
        self.assertTrue(body.get("success"))


# ---------------------------------------------------------------------------
# 3. GET /api/offers/open_count
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestOpenOfferCount(_FlaskBase):
    """Stub database.get_open_offers to a clean empty list so the route's
    real DB fetch doesn't intermittently fail under parallel xdist
    workers competing for the same sqlite write-lock."""

    def setUp(self):
        super().setUp()
        import database

        self._orig_get_open_offers = database.get_open_offers
        database.get_open_offers = lambda *a, **kw: []

    def tearDown(self):
        import database

        database.get_open_offers = self._orig_get_open_offers
        super().tearDown()

    def test_returns_200(self):
        resp = self.client.get("/api/offers/open_count", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_response_has_open_count(self):
        resp = self.client.get("/api/offers/open_count", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("open_count", body)
        self.assertIsInstance(body["open_count"], int)

    def test_success_key_true_on_success(self):
        resp = self.client.get("/api/offers/open_count", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertTrue(body.get("success"))


# ---------------------------------------------------------------------------
# 4. POST /api/offers/cancel
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCancelOffer(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/offers/cancel", {"trade_id": "abc123"}, auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._post("/api/offers/cancel", {"trade_id": "abc123"})
        self.assertEqual(resp.status_code, 500)

    def test_invalid_body_returns_400(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self.client.post(
                "/api/offers/cancel",
                data="not json",
                content_type="text/plain",
                headers=self.auth,
                environ_base=self._LOOPBACK,
            )
        self.assertEqual(resp.status_code, 400)

    def test_missing_trade_id_returns_400(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._post("/api/offers/cancel", {})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_empty_trade_id_returns_400(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._post("/api/offers/cancel", {"trade_id": ""})
        self.assertEqual(resp.status_code, 400)

    def test_legacy_truthy_cancel_is_denied_without_typed_outcome(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {"success": True}
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body.get("success"))

    def test_cancel_response_has_trade_id(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {"success": True}
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})
        body = resp.get_json()
        self.assertEqual(body.get("trade_id"), "trade-abc-001")

    def test_submitted_cancel_is_reported_pending_not_cancelled(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
            }
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(
            resp.get_json(),
            {
                "success": True,
                "status": "pending_reconciliation",
                "confirmed": False,
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "trade_id": "trade-abc-001",
            },
        )

    def test_missing_requested_trade_result_fails_closed(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "different-trade": {"success": True}
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "trade_id": "trade-abc-001",
                "error": "Offer cancellation failed",
                "reason": "WALLET_MUTATION_FAILED",
            },
        )

    def test_malformed_requested_trade_result_fails_closed(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {"trade-abc-001": ["hostile"]}
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "trade_id": "trade-abc-001",
                "error": "Offer cancellation failed",
                "reason": "WALLET_MUTATION_FAILED",
            },
        )

    def test_cancel_result_error_returns_400(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {"error": "storm_protection"}
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})
        self.assertEqual(resp.status_code, 400)

    def test_identity_denial_is_not_reported_as_cancelled(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {
                "success": False,
                "error": "Wallet mutation blocked by identity safety check",
                "reason": "WALLET_IDENTITY_MISMATCH",
            }
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "trade_id": "trade-abc-001",
                "error": "Wallet mutation blocked by identity safety check",
                "reason": "WALLET_IDENTITY_MISMATCH",
            },
        )

    def test_cancel_denial_does_not_echo_hostile_wallet_reason_or_error(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {
                "success": False,
                "error": "secret backend traceback",
                "reason": "WALLET_HOSTILE_REASON",
            }
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "trade_id": "trade-abc-001",
                "error": "Offer cancellation failed",
                "reason": "WALLET_MUTATION_FAILED",
            },
        )


# ---------------------------------------------------------------------------
# 5. POST /api/offers/cancel_all
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCancelAllPost(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/offers/cancel_all", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_bot_none_uses_direct_wallet_path(self):
        # bot=None → direct wallet RPC path; no open offers → 200 success
        with (
            patch.object(api_server, "bot", None),
            patch("wallet.get_all_offers", return_value=[]),
            patch("wallet.cancel_offers_batch", return_value={}),
            patch("wallet.is_offer_time_expired", return_value=False),
        ):
            resp = self._post("/api/offers/cancel_all")
        self.assertEqual(resp.status_code, 200)

    def test_bot_running_returns_409(self):
        # Running bot must be stopped before cancel_all is allowed
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._post("/api/offers/cancel_all")
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.get_json().get("success"))

    def test_bot_stopped_cancel_all_returns_success(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        with (
            patch.object(api_server, "bot", stopped),
            patch("wallet.get_all_offers", return_value=[]),
            patch("wallet.cancel_offers_batch", return_value={}),
            patch("wallet.is_offer_time_expired", return_value=False),
        ):
            resp = self._post("/api/offers/cancel_all")
        self.assertIn(resp.status_code, (200, 202))

    def test_stopped_bot_routes_active_offer_through_durable_manager(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
                "submitted": True,
                "confirmed": False,
                "failed": False,
                "unknown": False,
                "method": "single_rpc",
                "transaction_id": "b" * 64,
                "spend_bundle_id": None,
                "error": None,
                "http_status": None,
                "raw_response": {"transaction_id": "b" * 64},
                "evidence_sha256": "c" * 64,
            }
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch("wallet.cancel_offers_batch") as direct_batch,
            patch("wallet.is_offer_time_expired", return_value=False),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.get_json(),
            {
                "success": True,
                "async": True,
                "total": 1,
                "message": "Cancelling 1 offers in background...",
            },
        )
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [trade_id], reason="manual_cancel_all", force_storm=True
        )
        direct_batch.assert_not_called()

        status = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(
            {
                key: status[key]
                for key in (
                    "success",
                    "running",
                    "complete",
                    "phase",
                    "total",
                    "cancelled",
                    "pending",
                    "failed",
                )
            },
            {
                "success": True,
                "running": False,
                "complete": True,
                "phase": "complete",
                "total": 1,
                "cancelled": 0,
                "pending": 1,
                "failed": 0,
            },
        )

    def test_stopped_cancel_all_retries_exact_durable_failed_attempt(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_UNKNOWN",
                "success": False,
                "submitted": False,
                "reconciliation_required": True,
            }
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch(
                "database.get_retryable_failed_offer_cancels",
                return_value=[
                    {
                        "trade_id": trade_id,
                        "operation_id": f"cancel:{trade_id}",
                        "attempt": 1,
                    }
                ],
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [trade_id],
            reason="manual_cancel_all",
            force_storm=True,
            _retry_failed_attempts={trade_id: 1},
        )

        gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
        status_consumer = gui_source.split(
            "async function pollShutdownCancelAllStatusOnce()", 1
        )[1].split("function startShutdownCancelAllPoll()", 1)[0]
        assert "const pending = Number(state.pending || 0);" in status_consumer
        assert "pending authoritative reconciliation" in status_consumer
        assert "const cancelled =" not in status_consumer
        shutdown_source = gui_source.split("async function confirmShutdown()", 1)[1]
        shutdown_source = shutdown_source.split("// Wallet Picker Modal", 1)[0]
        assert "cancelResult.async === true" in shutdown_source
        assert "cancelResult.total" in shutdown_source
        assert "await waitForShutdownCancelAllCompletion" in shutdown_source
        assert "pending + failed !== count" in shutdown_source
        assert "throw e;" in shutdown_source
        assert "/offers/open_count" not in shutdown_source
        assert "pending authoritative reconciliation" in shutdown_source
        assert "confirmed cancelled" not in shutdown_source

    def test_stopped_cancel_all_partitions_71_offers_into_bounded_cohorts(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = [f"{index:064x}" for index in range(1, 72)]

        def journal_batch(batch, **_kwargs):
            return {
                trade_id: {
                    "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                    "success": True,
                }
                for trade_id in batch
            }

        stopped.offer_manager.cancel_offers.side_effect = journal_batch

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[
                    {"trade_id": trade_id, "status": "ACTIVE"} for trade_id in trade_ids
                ],
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        calls = stopped.offer_manager.cancel_offers.call_args_list
        self.assertEqual([len(call.args[0]) for call in calls], [64, 7])
        self.assertEqual(
            [trade_id for call in calls for trade_id in call.args[0]], trade_ids
        )

        status = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["total"], 71)
        self.assertEqual(status["pending"], 71)
        self.assertEqual(status["failed"], 0)

    def test_stopped_cancel_all_treats_65th_offer_as_an_independent_request(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = [f"{index:064x}" for index in range(1, 66)]

        stopped.offer_manager.cancel_offers.side_effect = lambda batch, **_kwargs: {
            trade_id: {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
            }
            for trade_id in batch
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[
                    {"trade_id": trade_id, "status": "ACTIVE"} for trade_id in trade_ids
                ],
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        calls = stopped.offer_manager.cancel_offers.call_args_list
        self.assertEqual([len(call.args[0]) for call in calls], [64, 1])
        self.assertEqual(calls[1].args[0], [trade_ids[-1]])

    def test_stopped_cancel_all_preserves_first_batch_progress_if_second_fails(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = [f"{index:064x}" for index in range(1, 72)]

        def journal_then_fail(batch, **_kwargs):
            if len(batch) == 7:
                raise RuntimeError("second cancellation cohort failed")
            return {
                trade_id: {
                    "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                    "success": True,
                }
                for trade_id in batch
            }

        stopped.offer_manager.cancel_offers.side_effect = journal_then_fail

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[
                    {"trade_id": trade_id, "status": "ACTIVE"} for trade_id in trade_ids
                ],
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        status = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertFalse(status["running"])
        self.assertFalse(status["complete"])
        self.assertEqual(status["phase"], "error")
        self.assertEqual(status["current_batch"], 2)
        self.assertEqual(status["pending"], 64)
        self.assertEqual(status["failed"], 0)
        self.assertIn("second cancellation cohort failed", status["error"])

    def test_uninitialised_bot_denial_clears_state_and_allows_coordinator_retry(self):
        trade_id = "a" * 64
        stopped = _make_bot()
        stopped.is_running.return_value = False
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_FAILED",
                "success": False,
                "submitted": False,
                "confirmed": False,
                "failed": True,
                "unknown": False,
                "method": "single_rpc",
                "transaction_id": None,
                "spend_bundle_id": None,
                "error": "not found",
                "http_status": 404,
                "raw_response": {"error": "not found"},
                "evidence_sha256": "c" * 64,
            }
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", None),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch("wallet.cancel_offers_batch") as direct_batch,
            patch("wallet.is_offer_time_expired", return_value=False),
            patch.object(api_server, "start_mutation_thread") as start_thread,
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(
            resp.get_json().get("reason"),
            "DURABLE_CANCEL_COORDINATOR_UNAVAILABLE",
        )
        direct_batch.assert_not_called()
        start_thread.assert_not_called()

        status = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertFalse(status["running"])
        self.assertFalse(status["complete"])
        self.assertEqual(status["phase"], "error")
        self.assertEqual(
            status["error"], "Offer cancellation coordinator is unavailable"
        )

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch("wallet.cancel_offers_batch") as retry_direct_batch,
            patch("wallet.is_offer_time_expired", return_value=False),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            retry = self._post("/api/offers/cancel_all")

        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.get_json()["async"])
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [trade_id], reason="manual_cancel_all", force_storm=True
        )
        retry_direct_batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
