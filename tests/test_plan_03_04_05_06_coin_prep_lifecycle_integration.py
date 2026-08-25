"""Slices 03-04, 03-05, 03-06 — coin prep lifecycle (integration tests).

Three slices in one file — all test the coin prep trigger/status/reset cycle
with real SQLite DB and mocked subprocess/threading:

  03-04: coin-prep full cycle — consolidate → split → verify
    - Trigger sets state: running=True, phase=idle, run_id populated
    - Status endpoint reads state file when provided (phase progress)
    - Complete: running=False, complete=True after mock completion
    - Fills in DB are NOT cleared on default (preserve_history=True) trigger

  03-05: coin-prep retry (soft reset, preserve fills)
    - Soft reset via /api/coin-prep/reset clears running/error state
    - Fills survive soft reset
    - Re-trigger after reset sets running=True again
    - Error state is cleared on re-trigger

  03-06: guarded coin-prep full reset (fresh-start path)
    - full_reset=True succeeds only when no authoritative fill state exists
    - fills make the reset return a stable conflict without mutation
    - full_reset=False (default) preserves history

Threading is mocked to prevent the do_prep() thread from actually launching.
Uses the TempDB pattern for real SQLite isolation.
"""

import os
import sys
import tempfile
import unittest
from decimal import Decimal
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
_FAKE_ASSET = "a" * 64
_TRADE_ID_A = "prep-test-001"
_TRADE_ID_B = "prep-test-002"


class _TempDB(unittest.TestCase):
    """Base: redirect database module to a fresh temp SQLite file."""

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

        api_server.app.testing = True
        self.client = api_server.app.test_client()
        self.token = api_server._LOCAL_API_TOKEN
        api_server._rate_limit_log.clear()
        api_server._fresh_start_clear()
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

        self._orig_session_start_time = api_server._session_start_time
        self._orig_run_history_cutoff = api_server._run_history_cutoff

        # Snapshot coin prep state so tearDown can restore it
        self._orig_coin_prep_state = dict(api_server._coin_prep_state)
        self._orig_coin_prep_proc = api_server._coin_prep_proc
        api_server._coin_prep_state.update(
            {
                "running": False,
                "complete": False,
                "error": None,
                "phase": "idle",
                "run_id": None,
                "started_at": None,
            }
        )
        api_server._coin_prep_proc = None

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
        api_server._fresh_start_clear()
        api_server._session_start_time = self._orig_session_start_time
        api_server._run_history_cutoff = self._orig_run_history_cutoff
        api_server._coin_prep_state.clear()
        api_server._coin_prep_state.update(self._orig_coin_prep_state)
        api_server._coin_prep_proc = self._orig_coin_prep_proc

    def _seed_fill(self, trade_id=_TRADE_ID_A):
        _db.record_fill(
            trade_id=trade_id,
            side="buy",
            price_xch=Decimal("0.002"),
            size_xch=Decimal("0.001"),
            size_cat=Decimal("0.5"),
            cat_asset_id=_FAKE_ASSET,
        )

    def _seed_terminal_offer_proof(self):
        """Mirror a completed TEST 7 offer with append-only proof history."""
        coin_id = "b" * 64
        trade_id = "c" * 64
        intent_id = "intent-terminal-reprep"
        prepared_at = "2026-08-22T06:48:40Z"
        finalized_at = "2026-08-22T06:48:41Z"

        self.assertTrue(
            _db.upsert_coin(
                coin_id,
                "xch",
                1000,
                designation="tier_spare",
                tier="inner",
                purpose="lifecycle",
            )
        )
        _db.prepare_offer_intent(
            intent_id=intent_id,
            operation_id=f"create:{intent_id}",
            event_id=f"create:{intent_id}:prepared",
            run_id="run-terminal-reprep",
            wallet_fingerprint_hash="d" * 64,
            network="mainnet",
            asset_id=_FAKE_ASSET,
            side="buy",
            tier="inner",
            purpose="normal_lifecycle",
            slot_key="ladder:buy:0",
            generation=0,
            offered_amount_atomic="1000",
            requested_amount_atomic="2000",
            selected_coin_ids_json=[coin_id],
            wallet_identity_json={"wallet_fingerprint_hash": "d" * 64},
            evidence_json={"source": "terminal-reprep-regression"},
            prepared_at=prepared_at,
            reserve_selected_coins=True,
        )
        _db.finalize_offer_intent(
            intent_id=intent_id,
            operation_id=f"create:{intent_id}",
            event_id=f"create:{intent_id}:finalized",
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=trade_id,
            offer_text_sha256="e" * 64,
            wallet_identity_json={"wallet_fingerprint_hash": "d" * 64},
            evidence_json={"effect_attempted": True},
            finalized_at=finalized_at,
            finalize_selected_coin_reservations=True,
        )
        self.assertTrue(
            _db.add_offer(
                trade_id,
                "buy",
                Decimal("0.001"),
                Decimal("1"),
                Decimal("1000"),
                _FAKE_ASSET,
                tier="inner",
                coin_id=coin_id,
            )
        )
        conn = _db.get_connection()
        conn.execute(
            "UPDATE offer_intents SET lifecycle_state='terminal', "
            "terminal_at=?, updated_at=? WHERE intent_id=?",
            (finalized_at, finalized_at, intent_id),
        )
        conn.execute(
            "UPDATE offers SET status='cancelled', lifecycle_state='cancelled' "
            "WHERE trade_id=?",
            (trade_id,),
        )
        conn.execute(
            "UPDATE coins SET status='spent', trade_id=? WHERE coin_id=?",
            (trade_id, _db.norm_coin_id(coin_id)),
        )
        conn.commit()
        return intent_id, trade_id, coin_id

    def _fill_count(self):
        conn = _db.get_connection()
        return conn.execute("SELECT COUNT(*) AS cnt FROM fills").fetchone()["cnt"]

    def _make_bot(self):
        bot = MagicMock()
        bot.is_running.return_value = False
        bot.stop = MagicMock()
        bot.coin_manager._prep_process = None
        bot.coin_manager._prep_running = False
        bot.coin_manager.check_coin_prep_status.return_value = {"running": False}
        bot.coin_manager.get_coin_health.return_value = (5, 5)
        return bot

    def _trigger(self, bot_mock=None, full_reset=False):
        """POST /api/coin-prep/trigger with threading mocked out."""
        mock_thread = MagicMock()
        with (
            patch.object(api_server, "bot", bot_mock or self._make_bot()),
            patch("blueprints.coin_prep.threading.Thread") as mock_thread_cls,
            patch("blueprints.coin_prep.log_event"),
            patch("os.path.exists", return_value=True),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            mock_thread_cls.return_value = mock_thread
            return self.client.post(
                "/api/coin-prep/trigger",
                json={"full_reset": full_reset},
                headers={"X-Bot-Local-Token": self.token},
                environ_base=_LOOPBACK,
            )

    def _reset(self, bot_mock=None):
        with patch.object(api_server, "bot", bot_mock), patch("api_server.log_event"):
            return self.client.post(
                "/api/coin-prep/reset",
                headers={"X-Bot-Local-Token": self.token},
                environ_base=_LOOPBACK,
            )

    def _status(self, bot_mock=None):
        with (
            patch.object(api_server, "bot", bot_mock),
            patch("os.path.exists", return_value=False),
        ):
            return self.client.get(
                "/api/coin-prep/status",
                environ_base=_LOOPBACK,
            )


# ---------------------------------------------------------------------------
# 03-04: coin-prep full cycle — trigger → running → state transitions
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"modules unavailable: {_SKIP}")
class TestCoinPrepFullCycle(_TempDB):
    """Trigger starts the cycle; state transitions must be correct."""

    def test_trigger_returns_success(self):
        resp = self._trigger()
        self.assertTrue(resp.get_json().get("success"))

    def test_trigger_sets_running_true(self):
        """After trigger, _coin_prep_state['running'] is True."""
        self._trigger()
        self.assertTrue(api_server._coin_prep_state.get("running"))

    def test_trigger_sets_run_id(self):
        """Each trigger creates a unique run_id."""
        self._trigger()
        run_id = api_server._coin_prep_state.get("run_id")
        self.assertIsNotNone(run_id)
        self.assertGreater(len(run_id), 0)

    def test_trigger_sets_started_at(self):
        """Trigger records the start timestamp."""
        self._trigger()
        self.assertIsNotNone(api_server._coin_prep_state.get("started_at"))

    def test_trigger_clears_previous_error(self):
        """Re-trigger after error must clear the previous error message."""
        api_server._coin_prep_state["error"] = "previous failure"
        self._trigger()
        self.assertIsNone(api_server._coin_prep_state.get("error"))

    def test_trigger_stops_running_bot(self):
        """Trigger must call bot.stop() to prevent concurrent trading."""
        bot = self._make_bot()
        bot.is_running.return_value = True
        self._trigger(bot_mock=bot)
        bot.stop.assert_called()

    def test_status_endpoint_returns_running_state(self):
        """Status endpoint reflects the running=True state after trigger."""
        self._trigger()
        resp = self._status()
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body.get("running"))

    def test_second_run_id_differs_from_first(self):
        """A fresh trigger after reset produces a different run_id."""
        self._trigger()
        first_id = api_server._coin_prep_state.get("run_id")
        self._reset()
        self._trigger()
        second_id = api_server._coin_prep_state.get("run_id")
        self.assertNotEqual(first_id, second_id)

    def test_default_trigger_preserves_fills(self):
        """Default trigger (full_reset=False) must NOT delete fills from DB."""
        self._seed_fill()
        self.assertEqual(self._fill_count(), 1)
        self._trigger(full_reset=False)
        self.assertEqual(self._fill_count(), 1)

    def test_keep_history_reprep_starts_with_terminal_offer_proof(self):
        """Completed offer evidence must not block the routine re-prep path."""
        intent_id, trade_id, coin_id = self._seed_terminal_offer_proof()

        resp = self._trigger(full_reset=False)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))
        conn = _db.get_connection()
        self.assertEqual(
            conn.execute(
                "SELECT lifecycle_state FROM offer_intents WHERE intent_id=?",
                (intent_id,),
            ).fetchone()[0],
            "terminal",
        )
        self.assertGreater(
            conn.execute(
                "SELECT COUNT(*) FROM offer_operation_journal WHERE intent_id=?",
                (intent_id,),
            ).fetchone()[0],
            0,
        )
        coin = conn.execute(
            "SELECT status, trade_id FROM coins WHERE coin_id=?",
            (_db.norm_coin_id(coin_id),),
        ).fetchone()
        self.assertEqual((coin[0], coin[1]), ("spent", trade_id))

    def test_keep_history_reprep_reconciles_expired_open_offer_before_guard(self):
        """Routine re-prep must reconcile terminal Sage evidence first."""

        intent_id, trade_id, coin_id = self._seed_terminal_offer_proof()
        conn = _db.get_connection()
        conn.execute(
            "UPDATE offer_intents SET lifecycle_state='created', terminal_at=NULL "
            "WHERE intent_id=?",
            (intent_id,),
        )
        conn.execute(
            "UPDATE offers SET status='open', lifecycle_state='open' WHERE trade_id=?",
            (trade_id,),
        )
        conn.execute(
            "UPDATE coins SET status='locked', trade_id=? WHERE coin_id=?",
            (trade_id, _db.norm_coin_id(coin_id)),
        )
        conn.commit()

        def reconcile_expired(candidate_intent_id, **_kwargs):
            self.assertEqual(candidate_intent_id, intent_id)
            db_conn = _db.get_connection()
            db_conn.execute(
                "UPDATE offer_intents SET lifecycle_state='terminal', terminal_at=? "
                "WHERE intent_id=?",
                ("2026-08-24T09:55:00Z", intent_id),
            )
            db_conn.execute(
                "UPDATE offers SET status='expired', lifecycle_state='expired' "
                "WHERE trade_id=?",
                (trade_id,),
            )
            db_conn.execute(
                "UPDATE coins SET status='free', trade_id=NULL WHERE coin_id=?",
                (_db.norm_coin_id(coin_id),),
            )
            db_conn.commit()
            return {"classification": "EXPIRED_PROVEN", "applied": True}

        with (
            patch(
                "offer_reconciliation.load_authoritative_evidence",
                return_value={"schema_version": 1},
            ),
            patch(
                "offer_reconciliation._clock_utc",
                return_value="2026-08-24T09:55:00Z",
            ),
            patch(
                "offer_reconciliation._derive_single_cancel_context",
                return_value=None,
            ),
            patch(
                "offer_reconciliation.classify_terminal_evidence",
                return_value={"classification": "EXPIRED_PROVEN"},
            ),
            patch(
                "offer_reconciliation.reconcile_offer",
                side_effect=reconcile_expired,
            ) as reconcile,
        ):
            resp = self._trigger(full_reset=False)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get("success"))
        self.assertEqual(reconcile.call_count, 1)
        self.assertEqual(reconcile.call_args.args, (intent_id,))
        self.assertEqual(
            reconcile.call_args.kwargs,
            {
                "evidence": {"schema_version": 1},
                "cancel_context": None,
                "now": "2026-08-24T09:55:00Z",
            },
        )


# ---------------------------------------------------------------------------
# 03-05: coin-prep retry — soft reset preserves DB, re-trigger restores state
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"modules unavailable: {_SKIP}")
class TestCoinPrepRetry(_TempDB):
    """Soft reset must clear running state without touching fills."""

    def test_reset_returns_success(self):
        resp = self._reset()
        self.assertTrue(resp.get_json().get("success"))

    def test_reset_clears_running_flag(self):
        """After reset, _coin_prep_state['running'] is False."""
        api_server._coin_prep_state["running"] = True
        self._reset()
        self.assertFalse(api_server._coin_prep_state.get("running"))

    def test_reset_clears_complete_flag(self):
        """After reset, complete is False."""
        api_server._coin_prep_state["complete"] = True
        self._reset()
        self.assertFalse(api_server._coin_prep_state.get("complete"))

    def test_reset_clears_error_state(self):
        """Error from previous run is cleared on soft reset."""
        api_server._coin_prep_state["error"] = "Worker exited with code 1"
        self._reset()
        self.assertIsNone(api_server._coin_prep_state.get("error"))

    def test_reset_preserves_fills(self):
        """Soft reset never touches the fills table."""
        self._seed_fill()
        self._trigger()
        self._reset()
        self.assertEqual(self._fill_count(), 1)

    def test_retrigger_after_reset_sets_running(self):
        """Re-trigger after soft reset starts a new run (running=True)."""
        api_server._coin_prep_state["running"] = False
        api_server._coin_prep_state["error"] = "prev error"
        self._trigger()
        self.assertTrue(api_server._coin_prep_state.get("running"))

    def test_retrigger_after_reset_clears_error(self):
        """Re-trigger after error clears the error field."""
        api_server._coin_prep_state["error"] = "some crash"
        self._trigger()
        self.assertIsNone(api_server._coin_prep_state.get("error"))

    def test_reset_ungates_coin_manager(self):
        """Reset must set coin_manager._prep_running=False to ungate the bot loop."""
        bot = self._make_bot()
        bot.coin_manager._prep_running = True
        self._reset(bot_mock=bot)
        self.assertFalse(bot.coin_manager._prep_running)

    def test_fills_survive_trigger_reset_retrigger_cycle(self):
        """Fills must survive the full retry cycle."""
        self._seed_fill()
        self._trigger(full_reset=False)
        self._reset()
        self._trigger(full_reset=False)
        self.assertEqual(self._fill_count(), 1)


# ---------------------------------------------------------------------------
# 03-06: coin-prep full reset path — authoritative fills deny mutation
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"modules unavailable: {_SKIP}")
class TestCoinPrepFullReset(_TempDB):
    """A full reset must not erase durable fill/proof history."""

    def test_full_reset_trigger_returns_success(self):
        resp = self._trigger(full_reset=True)
        self.assertTrue(resp.get_json().get("success"))

    def test_full_reset_with_fill_returns_conflict_without_mutation(self):
        self._seed_fill()
        self.assertEqual(self._fill_count(), 1)
        resp = self._trigger(full_reset=True)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json().get("error"), "authoritative_state_conflict")
        self.assertEqual(self._fill_count(), 1)

    def test_full_reset_with_multiple_fills_preserves_every_row(self):
        self._seed_fill(trade_id=_TRADE_ID_A)
        self._seed_fill(trade_id=_TRADE_ID_B)
        self.assertEqual(self._fill_count(), 2)
        resp = self._trigger(full_reset=True)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(
            resp.get_json().get("conflicts"), ["authoritative_session_state"]
        )
        self.assertEqual(self._fill_count(), 2)

    def test_default_trigger_does_not_clear_fills(self):
        """full_reset=False (default) must NOT clear fills."""
        self._seed_fill()
        self._trigger(full_reset=False)
        self.assertEqual(self._fill_count(), 1)

    def test_full_reset_still_sets_running_true(self):
        """Even the full-reset path must set the running flag."""
        self._trigger(full_reset=True)
        self.assertTrue(api_server._coin_prep_state.get("running"))

    def test_full_reset_clears_complete_flag(self):
        """Full reset trigger re-starts the cycle (complete=False)."""
        api_server._coin_prep_state["complete"] = True
        self._trigger(full_reset=True)
        self.assertFalse(api_server._coin_prep_state.get("complete"))

    def test_full_reset_sets_run_id(self):
        """Full reset trigger still creates a unique run_id."""
        self._trigger(full_reset=True)
        self.assertIsNotNone(api_server._coin_prep_state.get("run_id"))


if __name__ == "__main__":
    unittest.main()
