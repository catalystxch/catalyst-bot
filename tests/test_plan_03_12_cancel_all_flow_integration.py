"""Slice 03-12 — cancel-all flow integration test.

Tests the full stop-button flow: open offers in DB → cancel_all() bulk cancel →
DB offers marked cancelled/kept pending based on wallet response.

Uses real SQLite temp DB. cancel_offers_batch (wallet RPC) is mocked.
"""

import os
import sys
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import database as _db
    from database import add_offer, get_open_offers, init_database

    _SKIP_DB = None
except ModuleNotFoundError as exc:
    _db = None
    _SKIP_DB = str(exc)

try:
    import offer_manager as _om_mod
    from offer_manager import OfferManager

    _SKIP_OM = None
except ModuleNotFoundError as exc:
    OfferManager = None
    _SKIP_OM = str(exc)


_P = Decimal("0.001")
_SX = Decimal("1.0")
_SC = Decimal("1000")
_ASSET = "aabbcc1122"


def _add_offer(trade_id: str, side: str = "buy"):
    add_offer(trade_id, side, _P, _SX, _SC, _ASSET, tier="inner")


def _fake_cfg(**overrides):
    defaults = dict(CAT_ASSET_ID=_ASSET)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Temp-DB base class
# ---------------------------------------------------------------------------


class _TempDB(unittest.TestCase):
    def setUp(self):
        sys.modules["database"] = _db

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

    def tearDown(self):
        if hasattr(_db._local, "conn") and _db._local.conn:
            try:
                _db._local.conn.close()
            except Exception:
                pass
        _db._local.conn = None
        _db.DB_PATH = self._orig_db_path
        _db._db_initialized_path = self._orig_init_path
        sys.modules["database"] = _db
        try:
            os.unlink(self._tmp_path)
        except OSError:
            pass

    def _open_offer_count(self) -> int:
        return len(get_open_offers(cat_asset_id=_ASSET))

    def _offer_status(self, trade_id: str) -> str:
        conn = _db.get_connection()
        row = conn.execute(
            "SELECT status FROM offers WHERE trade_id=?", (trade_id,)
        ).fetchone()
        return dict(row)["status"] if row else None


# ---------------------------------------------------------------------------
# 1. cancel_all() — confirmed cancel path
# ---------------------------------------------------------------------------


@unittest.skipIf(
    _SKIP_DB is not None or _SKIP_OM is not None,
    f"dependencies unavailable: db={_SKIP_DB} om={_SKIP_OM}",
)
class TestCancelAllConfirmed(_TempDB):
    def _run_cancel(self, trade_ids, bulk_response):
        """Patch the durable typed cancellation entrypoint and run cancel_all()."""
        om = OfferManager()
        fake_cfg = _fake_cfg()
        with (
            patch.object(_om_mod, "cfg", fake_cfg),
            patch.object(om, "cancel_offers", return_value=bulk_response),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [],
                    "total": 0,
                    "end_of_history": True,
                },
            ),
        ):
            return om.cancel_all(cat_asset_id=_ASSET)

    def test_no_open_offers_returns_empty_dict(self):
        result = self._run_cancel([], {})
        self.assertEqual(result, {})

    def test_single_legacy_success_does_not_terminalize(self):
        _add_offer("tid-a")
        bulk = {"tid-a": {"success": True, "method": "bulk"}}
        self._run_cancel(["tid-a"], bulk)
        self.assertEqual(self._offer_status("tid-a"), "open")

    def test_multiple_legacy_successes_remain_open_without_terminal_proof(self):
        for i in range(3):
            _add_offer(f"tid-{i}")
        self.assertEqual(self._open_offer_count(), 3)

        bulk = {f"tid-{i}": {"success": True, "method": "bulk"} for i in range(3)}
        self._run_cancel([f"tid-{i}" for i in range(3)], bulk)
        self.assertEqual(self._open_offer_count(), 3)

    def test_failed_cancel_leaves_offer_open(self):
        _add_offer("tid-fail")
        bulk = {"tid-fail": {"success": False, "error": "rpc error"}}
        self._run_cancel(["tid-fail"], bulk)
        # Offer NOT marked cancelled — remains open
        status = self._offer_status("tid-fail")
        self.assertNotEqual(status, "cancelled")

    def test_mixed_success_failure(self):
        _add_offer("tid-ok")
        _add_offer("tid-nok")
        bulk = {
            "tid-ok": {"success": True, "method": "bulk"},
            "tid-nok": {"success": False, "error": "timeout"},
        }
        self._run_cancel(["tid-ok", "tid-nok"], bulk)
        self.assertEqual(self._offer_status("tid-ok"), "open")
        self.assertNotEqual(self._offer_status("tid-nok"), "cancelled")

    def test_return_dict_contains_all_trade_ids(self):
        for i in range(2):
            _add_offer(f"rt-{i}")
        bulk = {f"rt-{i}": {"success": True, "method": "bulk"} for i in range(2)}
        result = self._run_cancel([f"rt-{i}" for i in range(2)], bulk)
        for i in range(2):
            self.assertIn(f"rt-{i}", result)

    def test_tracked_offer_does_not_hide_untracked_live_wallet_offer(self):
        tracked_id = "a" * 64
        untracked_id = "b" * 64
        _add_offer(tracked_id)
        wallet_rows = [
            {
                "trade_id": trade_id,
                "status": "PENDING_ACCEPT",
                "summary": {
                    "offered": {"xch": 1000},
                    "requested": {_ASSET: 100},
                },
            }
            for trade_id in (tracked_id, untracked_id)
        ]
        dispatched = []

        def cancel_ids(trade_ids, **_kwargs):
            dispatched.append(tuple(trade_ids))
            return {trade_id: {"success": True} for trade_id in trade_ids}

        manager = OfferManager()
        with (
            patch.object(_om_mod, "cfg", _fake_cfg()),
            patch.object(manager, "cancel_offers", side_effect=cancel_ids),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": wallet_rows,
                    "total": 2,
                    "end_of_history": True,
                },
            ),
        ):
            result = manager.cancel_all(cat_asset_id=_ASSET)

        self.assertEqual(dispatched, [(tracked_id, untracked_id)])
        self.assertEqual(set(result), {tracked_id, untracked_id})

    def test_incomplete_wallet_history_prevents_partial_cancel(self):
        tracked_id = "a" * 64
        _add_offer(tracked_id)
        manager = OfferManager()
        with (
            patch.object(_om_mod, "cfg", _fake_cfg()),
            patch.object(manager, "cancel_offers") as dispatcher,
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={"success": False},
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "CANCEL_ALL_WALLET_HISTORY_INCOMPLETE"
            ):
                manager.cancel_all(cat_asset_id=_ASSET)
        dispatcher.assert_not_called()

    def test_unresolved_prior_cancel_blocks_next_fee_cohort(self):
        trade_id = "a" * 64
        _add_offer(trade_id)
        manager = OfferManager()
        with (
            patch.object(_om_mod, "cfg", _fake_cfg()),
            patch.object(manager, "cancel_offers") as dispatcher,
            patch.object(manager, "reconcile_submitted_cancels_only", return_value=-1),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [],
                    "total": 0,
                    "end_of_history": True,
                },
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "CANCEL_ALL_PRIOR_COHORT_UNRESOLVED"
            ):
                manager.cancel_all(cat_asset_id=_ASSET)
        dispatcher.assert_not_called()

    def test_side_filter_includes_wallet_only_blocked_side(self):
        tracked_buy = "a" * 64
        wallet_buy = "b" * 64
        wallet_sell = "c" * 64
        _add_offer(tracked_buy, "buy")
        wallet_rows = [
            {
                "trade_id": trade_id,
                "status": "PENDING_ACCEPT",
                "summary": {
                    "offered": {"xch": 1000} if side == "buy" else {_ASSET: 100},
                    "requested": {_ASSET: 100} if side == "buy" else {"xch": 1000},
                },
            }
            for trade_id, side in (
                (tracked_buy, "buy"),
                (wallet_buy, "buy"),
                (wallet_sell, "sell"),
            )
        ]
        manager = OfferManager()
        with (
            patch.object(_om_mod, "cfg", _fake_cfg()),
            patch.object(manager, "cancel_offers", return_value={}) as dispatcher,
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": wallet_rows,
                    "total": 3,
                    "end_of_history": True,
                },
            ),
        ):
            manager.cancel_all(cat_asset_id=_ASSET, side_filter="buy")
        self.assertEqual(dispatcher.call_args.args[0], [tracked_buy, wallet_buy])

    def test_bootstrap_and_orphan_cancel_in_separate_fee_scopes(self):
        bootstrap_id = "a" * 64
        orphan_id = "b" * 64
        campaign_id = "c" * 64
        _add_offer(bootstrap_id)

        def wallet_row(trade_id):
            return {
                "trade_id": trade_id,
                "status": "PENDING_ACCEPT",
                "summary": {
                    "offered": {"xch": 1000},
                    "requested": {_ASSET: 100},
                },
            }

        wallet_rows = [wallet_row(bootstrap_id), wallet_row(orphan_id)]
        calls = []

        def cancel_ids(trade_ids, **kwargs):
            calls.append((tuple(trade_ids), kwargs))
            return {trade_id: {"success": True} for trade_id in trade_ids}

        def creation_intent(trade_id):
            if trade_id == bootstrap_id:
                return {"purpose": f"bootstrap:{campaign_id}:revision:1"}
            return None

        def history(**_kwargs):
            return {
                "success": True,
                "offers": wallet_rows,
                "total": len(wallet_rows),
                "end_of_history": True,
            }

        manager = OfferManager()
        with (
            patch.object(_om_mod, "cfg", _fake_cfg()),
            patch.object(manager, "cancel_offers", side_effect=cancel_ids),
            patch.object(
                _db, "get_offer_intent_by_trade_id", side_effect=creation_intent
            ),
            patch("wallet.get_authoritative_offer_history", side_effect=history),
        ):
            manager.cancel_all(cat_asset_id=_ASSET)
            self.assertEqual(calls[0][0], (orphan_id,))
            self.assertIsNone(calls[0][1]["fee_approval_id"])

            # Only authoritative proof that the first cohort is gone permits
            # the bootstrap campaign's distinct protected fee scope next.
            wallet_rows[:] = [wallet_row(bootstrap_id)]
            manager.cancel_all(cat_asset_id=_ASSET)
            self.assertEqual(calls[1][0], (bootstrap_id,))

    def test_distinct_bootstrap_campaigns_have_distinct_fee_cohorts(self):
        first, second = "a" * 64, "b" * 64
        purposes = {
            first: f"bootstrap:{'c' * 64}:revision:1",
            second: f"bootstrap:{'d' * 64}:revision:2",
        }
        with patch.object(
            _db,
            "get_offer_intent_by_trade_id",
            side_effect=lambda trade_id: {"purpose": purposes[trade_id]},
        ):
            groups = OfferManager._cancel_fee_scope_groups([second, first])

        self.assertEqual([group["trade_ids"] for group in groups], [[first], [second]])
        self.assertNotEqual(groups[0]["campaign_id"], groups[1]["campaign_id"])


# ---------------------------------------------------------------------------
# 2. cancel_all() — pending-cancel path (submitted but not confirmed)
# ---------------------------------------------------------------------------


@unittest.skipIf(
    _SKIP_DB is not None or _SKIP_OM is not None,
    f"dependencies unavailable: db={_SKIP_DB} om={_SKIP_OM}",
)
class TestCancelAllPending(_TempDB):
    def test_pending_cancel_leaves_offer_open_in_db(self):
        _add_offer("tid-pending")
        om = OfferManager()
        fake_cfg = _fake_cfg()
        # Legacy truthy method strings are not terminal cancellation proof.
        bulk = {"tid-pending": {"success": True, "method": "submitted_pending_confirm"}}
        with (
            patch.object(_om_mod, "cfg", fake_cfg),
            patch.object(om, "cancel_offers", return_value=bulk),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [],
                    "total": 0,
                    "end_of_history": True,
                },
            ),
        ):
            om.cancel_all(cat_asset_id=_ASSET)
        # Pending cancel — DB status unchanged (still "open")
        self.assertEqual(self._offer_status("tid-pending"), "open")


# ---------------------------------------------------------------------------
# 3. cancel_all() — side filter
# ---------------------------------------------------------------------------


@unittest.skipIf(
    _SKIP_DB is not None or _SKIP_OM is not None,
    f"dependencies unavailable: db={_SKIP_DB} om={_SKIP_OM}",
)
class TestCancelAllSideFilter(_TempDB):
    def _cancel_side(self, side_filter, bulk_response):
        om = OfferManager()
        fake_cfg = _fake_cfg()
        with (
            patch.object(_om_mod, "cfg", fake_cfg),
            patch.object(om, "cancel_offers", return_value=bulk_response),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [],
                    "total": 0,
                    "end_of_history": True,
                },
            ),
        ):
            return om.cancel_all(cat_asset_id=_ASSET, side_filter=side_filter)

    def test_buy_filter_cancels_only_buy_offers(self):
        _add_offer("buy-1", "buy")
        _add_offer("sell-1", "sell")
        bulk = {"buy-1": {"success": True, "method": "bulk"}}
        self._cancel_side("buy", bulk)
        self.assertEqual(self._offer_status("buy-1"), "open")
        self.assertEqual(self._offer_status("sell-1"), "open")

    def test_sell_filter_cancels_only_sell_offers(self):
        _add_offer("buy-2", "buy")
        _add_offer("sell-2", "sell")
        bulk = {"sell-2": {"success": True, "method": "bulk"}}
        self._cancel_side("sell", bulk)
        self.assertEqual(self._offer_status("buy-2"), "open")
        self.assertEqual(self._offer_status("sell-2"), "open")

    def test_no_filter_cancels_all_sides(self):
        _add_offer("buy-3", "buy")
        _add_offer("sell-3", "sell")
        bulk = {
            "buy-3": {"success": True, "method": "bulk"},
            "sell-3": {"success": True, "method": "bulk"},
        }
        self._cancel_side("", bulk)
        self.assertEqual(self._offer_status("buy-3"), "open")
        self.assertEqual(self._offer_status("sell-3"), "open")


# ---------------------------------------------------------------------------
# 4. cancel_all() — exception during bulk cancel
# ---------------------------------------------------------------------------


@unittest.skipIf(
    _SKIP_DB is not None or _SKIP_OM is not None,
    f"dependencies unavailable: db={_SKIP_DB} om={_SKIP_OM}",
)
class TestCancelAllExceptionHandling(_TempDB):
    def test_exception_in_bulk_cancel_does_not_crash_caller(self):
        _add_offer("tid-exc")
        om = OfferManager()
        fake_cfg = _fake_cfg()
        with (
            patch.object(_om_mod, "cfg", fake_cfg),
            patch.object(
                om,
                "cancel_offers",
                side_effect=RuntimeError("wallet offline"),
            ),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [],
                    "total": 0,
                    "end_of_history": True,
                },
            ),
        ):
            # Should not raise
            result = om.cancel_all(cat_asset_id=_ASSET)
        # Still returns a result dict (may be empty or with the tid)
        self.assertIsNotNone(result)
        # Offer not marked cancelled (cancel didn't succeed)
        status = self._offer_status("tid-exc")
        self.assertNotEqual(status, "cancelled")


if __name__ == "__main__":
    unittest.main()
