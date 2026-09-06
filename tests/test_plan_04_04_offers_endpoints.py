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
from datetime import datetime, timedelta, timezone
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


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_history_age_label_treats_legacy_naive_utc_timestamp_as_utc():
    timestamp = (datetime.now(timezone.utc) - timedelta(days=90)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    label = api_server._history_age_label(timestamp)

    assert label.endswith("d ago")
    assert float(label.removesuffix("d ago")) >= 89.9


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
    assert view["severity"] == "error"
    assert "awaiting authoritative proof" in view["message"]
    assert "confirmed" not in json.dumps(view).lower()


def test_cancel_all_progress_consumer_counts_only_authoritative_terminals():
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
        "phase": "reconciling",
        "total": 3,
        "cancelled": 2,
        "pending": 1,
        "failed": 0,
        "message": "Waiting for authoritative cancellation proof: 2/3 offers terminal.",
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

    assert view["cancelled"] == 2
    assert view["processed"] == 2
    assert view["remaining"] == 1
    assert view["isDone"] is False
    assert view["severity"] == "info"
    assert "2/3 offers terminal" in view["message"]


def test_cancel_all_progress_modal_describes_native_bulk_sage_confirmation():
    """The GUI must set honest expectations for native Sage bulk cancellation."""

    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    modal_source = gui_source.split('id="cancelProgressModal"', 1)[1].split(
        "<!-- Boost Confirmation Modal -->", 1
    )[0]
    modal_text = " ".join(modal_source.lower().split())

    assert "one at a time" not in modal_text
    assert "waits for authoritative on-chain confirmation" in modal_text
    assert "single bulk transaction" in modal_text
    assert "well under a minute" not in modal_text


def test_cancel_all_deadline_bounds_bulk_proof_recording_without_multi_hour_wait():
    """One transaction still needs bounded per-member durable proof commits."""
    from blueprints import offers

    assert offers._cancel_all_deadline_seconds(1, 90) == 180.0
    assert offers._cancel_all_deadline_seconds(71, 90) == 880.0
    assert offers._cancel_all_deadline_seconds(500, 90) == 3_600.0
    assert offers._cancel_all_deadline_seconds(1, 240) == 480.0


def test_cancel_all_gui_timeout_honours_backend_authoritative_deadline():
    """The UI must not call a healthy long-running cancel failed after five minutes."""

    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the bounded GUI consumer test")
    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    helper_source = (
        "function cancelAllClientTimeoutMs"
        + gui_source.split("function cancelAllClientTimeoutMs", 1)[1].split(
            "async function confirmCancelAll", 1
        )[0]
    )
    script = helper_source + "\nconsole.log(cancelAllClientTimeoutMs(8280));"
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert int(completed.stdout.strip()) >= 8_310_000
    confirm_source = gui_source.split("async function confirmCancelAll()", 1)[1]
    confirm_source = confirm_source.split(
        "// Local helper: read cached cancel-all state", 1
    )[0]
    assert "cancelAllClientTimeoutMs(result.timeout_seconds)" in confirm_source
    assert "}, 300000);" not in confirm_source


def test_shutdown_offer_disposition_does_not_claim_zero_offers_were_left_open():
    """A clean empty wallet must be described as empty at shutdown."""

    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the shutdown UI test")
    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    helper_source = (
        "function shutdownOfferDisposition"
        + gui_source.split("function shutdownOfferDisposition", 1)[1].split(
            "async function confirmShutdown", 1
        )[0]
    )
    script = (
        helper_source
        + "\nconsole.log(JSON.stringify([shutdownOfferDisposition({offers:{buy:[],sell:[]}}), shutdownOfferDisposition({offers:{buy:[{}],sell:[{},{}]}}), shutdownOfferDisposition({offers:{buy:[{}],sell:[{},{}]}}, {total:3,cancelled:3,confirmed:3,pending:0,failed:0})]));"
    )
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    empty, active, terminal_after_stale_view = json.loads(completed.stdout)

    assert empty["count"] == 0
    assert empty["copy"] == "No open offers were left behind."
    assert active["count"] == 3
    assert active["copy"] == "3 open offers left active."
    assert terminal_after_stale_view["count"] == 0
    assert terminal_after_stale_view["copy"] == "No open offers were left behind."


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
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {
                        "intent_id": "intent-a",
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
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
                "timeout_seconds": 180.0,
                "message": "Cancelling 1 offers in background...",
            },
        )
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [trade_id], reason="manual_cancel_all", force_storm=True
        )
        stopped.coin_manager.refresh_fee_pool_from_wallet.assert_called_once_with()
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
                "cancelled": 1,
                "pending": 0,
                "failed": 0,
            },
        )

    def test_stopped_cancel_all_waits_for_authoritative_terminal_reconciliation(self):
        """Shutdown must not finish after one submitted cancel aborts its peers."""
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = ["a" * 64, "b" * 64]
        stopped.offer_manager.cancel_offers.return_value = {
            trade_ids[0]: {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
            },
            trade_ids[1]: {
                "outcome": "CANCEL_FAILED",
                "success": False,
            },
        }
        reconciled = {"done": False}

        def finish_retries():
            reconciled["done"] = True
            return 0

        stopped.offer_manager.retry_failed_cancels.side_effect = finish_retries

        def terminal_record(trade_id):
            if not reconciled["done"]:
                return None
            return {
                "intent_id": f"intent:{trade_id}",
                "sage_trade_id": trade_id,
                "outcome": "CANCELLED_PROVEN",
            }

        def terminal_records(candidates):
            return {
                candidate: record
                for candidate in candidates
                if (record := terminal_record(candidate)) is not None
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
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        stopped.offer_manager.retry_failed_cancels.assert_called_once_with()
        status = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(
            {
                key: status[key]
                for key in (
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
                "running": False,
                "complete": True,
                "phase": "complete",
                "total": 2,
                "cancelled": 2,
                "pending": 0,
                "failed": 0,
            },
        )

    def test_stopped_cancel_all_refreshes_wallet_snapshot_after_completion(self):
        """A proven Cancel All must replace the stopped UI's stale offer cache."""

        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64

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
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        stopped.offer_manager.expect_empty_wallet_offer_book.assert_called_once_with(
            "manual_cancel_all_confirmed"
        )
        stopped.offer_manager.sync_from_wallet.assert_called_once_with()

    def test_cancel_all_completed_at_deadline_is_not_reported_as_zero_pending_error(
        self,
    ):
        """Final terminal proof wins even when it arrives on the deadline boundary."""
        from blueprints import offers

        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        reconciled = {"done": False}

        def finish_retries():
            reconciled["done"] = True
            return 0

        stopped.offer_manager.retry_failed_cancels.side_effect = finish_retries

        def terminal_record(candidate):
            if not reconciled["done"]:
                return None
            return {
                "intent_id": f"intent:{candidate}",
                "sage_trade_id": candidate,
                "outcome": "CANCELLED_PROVEN",
            }

        def terminal_records(candidates):
            return {
                candidate: record
                for candidate in candidates
                if (record := terminal_record(candidate)) is not None
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
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(offers, "_cancel_all_deadline_seconds", return_value=0.0),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        status = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["phase"], "complete")
        self.assertTrue(status["complete"])
        self.assertFalse(status["running"])
        self.assertIsNone(status["error"])
        self.assertEqual(status["cancelled"], 1)
        self.assertEqual(status["pending"], 0)
        self.assertEqual(status["failed"], 0)

    def test_cancel_all_status_reads_terminal_proof_in_one_batch(self):
        """Large native Sage batches must not issue one DB query per member."""
        from blueprints import offers

        trade_ids = ["a" * 64, "b" * 64, "c" * 64]
        calls = []

        def batch_records(candidates):
            calls.append(list(candidates))
            return {
                trade_ids[0]: {
                    "sage_trade_id": trade_ids[0],
                    "outcome": "CANCELLED_PROVEN",
                },
                trade_ids[1]: {
                    "sage_trade_id": trade_ids[1],
                    "outcome": "ACTIVE_PROVEN",
                },
                trade_ids[2]: {
                    "sage_trade_id": "d" * 64,
                    "outcome": "EXPIRED_PROVEN",
                },
            }

        with (
            patch.object(
                offers.database,
                "get_authoritative_terminal_records",
                side_effect=batch_records,
                create=True,
            ),
            patch.object(
                offers.database,
                "get_authoritative_terminal_record",
                side_effect=AssertionError("serial terminal lookup is forbidden"),
            ),
        ):
            terminal = offers._authoritatively_terminal_offer_ids(trade_ids)

        self.assertEqual(terminal, {trade_ids[0]})
        self.assertEqual(calls, [trade_ids])

    def test_cancel_all_status_advances_while_serial_retry_is_in_flight(self):
        """Polling must see exact durable proof before a slow retry batch returns."""
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = ["a" * 64, "b" * 64, "c" * 64]
        records = {}
        snapshots = []

        def poll():
            snapshots.append(
                self.client.get(
                    "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
                ).get_json()
            )

        def terminal_records(candidates):
            return {
                candidate: records[candidate]
                for candidate in candidates
                if candidate in records
            }

        def finish_retries():
            # One exact proof, one mismatched proof and one mere submission.
            records.update(
                {
                    trade_ids[0]: {
                        "sage_trade_id": trade_ids[0],
                        "outcome": "CANCELLED_PROVEN",
                    },
                    trade_ids[1]: {
                        "sage_trade_id": "d" * 64,
                        "outcome": "CANCELLED_PROVEN",
                    },
                    trade_ids[2]: {
                        "sage_trade_id": trade_ids[2],
                        "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                    },
                }
            )
            poll()
            records[trade_ids[1]] = {
                "sage_trade_id": trade_ids[1],
                "outcome": "EXPIRED_PROVEN",
            }
            poll()
            records[trade_ids[2]] = {
                "sage_trade_id": trade_ids[2],
                "outcome": "CANCELLED_PROVEN",
            }
            poll()
            return 0

        def run_now(*, operation, target, name):
            target()
            return object()

        stopped.offer_manager.retry_failed_cancels.side_effect = finish_retries
        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[
                    {"trade_id": trade_id, "status": "ACTIVE"} for trade_id in trade_ids
                ],
            ),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(s["cancelled"], s.get("confirmed"), s["pending"]) for s in snapshots],
            [(1, 1, 2), (2, 2, 1), (3, 3, 0)],
        )
        for snapshot in snapshots:
            self.assertTrue(snapshot["running"])
            self.assertFalse(snapshot["complete"])
            self.assertEqual(snapshot["total"], 3)
            self.assertEqual(snapshot["phase"], "reconciling")
            self.assertIn(
                f"{snapshot['confirmed']}/3 offers terminal", snapshot["message"]
            )
            self.assertNotIn("_target_trade_ids", snapshot)
        # Only the worker may declare completion, after the retry call returns.
        final = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertTrue(final["complete"])
        self.assertFalse(final["running"])
        stopped.offer_manager.retry_failed_cancels.assert_called_once_with()

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
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {
                        "intent_id": "intent-a",
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
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
        assert "const cancelled = Number(state.cancelled || 0);" in status_consumer
        assert "const pending = Number(state.pending || 0);" in status_consumer
        assert "authoritatively terminal" in status_consumer
        shutdown_source = gui_source.split("async function confirmShutdown()", 1)[1]
        shutdown_source = shutdown_source.split("// Wallet Picker Modal", 1)[0]
        assert "cancelResult.async === true" in shutdown_source
        assert "cancelResult.total" in shutdown_source
        assert "cancelResult.timeout_seconds" in shutdown_source
        assert "await waitForShutdownCancelAllCompletion" in shutdown_source
        cancel_response_window = shutdown_source.split(
            "const cancelResult = await cancelResp.json();", 1
        )[1].split("const isAsyncCancel = cancelResult.async === true;", 1)[0]
        assert "stopShutdownCancelAllPoll();" not in cancel_response_window
        assert "cancelled + pending + failed !== count" in shutdown_source
        assert "cancelled !== count" in shutdown_source
        assert "throw e;" in shutdown_source
        assert "/offers/open_count" not in shutdown_source
        assert "authoritatively terminal" in shutdown_source

    def test_stopped_cancel_all_submits_500_offers_in_one_authority_envelope(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = [f"{index:064x}" for index in range(1, 501)]
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
            }
            for trade_id in trade_ids
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
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=lambda candidates: {
                    trade_id: {
                        "intent_id": f"intent:{trade_id}",
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                    for trade_id in candidates
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            trade_ids,
            reason="manual_cancel_all",
            force_storm=True,
        )
        status = self.client.get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["total"], 500)
        self.assertEqual(status["batch_size"], 500)
        self.assertEqual(status["total_batches"], 1)
        self.assertEqual(status["cancelled"], 500)
        self.assertEqual(status["pending"], 0)
        self.assertEqual(status["failed"], 0)

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
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {
                        "intent_id": "intent-a",
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            retry = self._post("/api/offers/cancel_all")

        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.get_json()["async"])
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [trade_id], reason="manual_cancel_all", force_storm=True
        )
        retry_direct_batch.assert_not_called()


def test_offer_diagnostic_does_not_invent_dexie_staleness_from_local_agreement():
    from blueprints.offers import _offer_diagnostic_assessment

    result = _offer_diagnostic_assessment(
        wallet_error=None,
        duplicate_coin_ids=[],
        reserve_backed=[],
        stale_in_db=[],
        wallet_only=[],
        wallet_cancel_pending=[],
        wallet_cancelled_still_visible=[],
    )

    assert result["local_book_consistent"] is True
    assert result["dexie_rows_evaluated"] is False
    assert result["likely_stale_dexie_rows"] is None
    assert "cannot determine" in result["diagnosis"]


if __name__ == "__main__":
    unittest.main()
