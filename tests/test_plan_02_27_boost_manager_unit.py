"""Slice 02-27 — boost_manager.py unit tests.

Covers: _bps_to_pct (pure), BoostManager._find_stale_offers
(tested with a minimal fake offer_manager providing a price cache).
No offer creation, network calls, or database access.
"""

import socket
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch


_SOCKET_ATTEMPTS = []


def _blocked_socket(*args, **kwargs):
    _SOCKET_ATTEMPTS.append((args, kwargs))
    raise AssertionError("network access is forbidden in boost manager tests")


_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
socket.socket.connect = _blocked_socket
socket.socket.connect_ex = _blocked_socket
socket.create_connection = _blocked_socket

try:
    import boost_manager as _bm_mod
    from boost_manager import _bps_to_pct, BoostManager
    from cancel_outcomes import (
        CANCEL_CONFIRMED,
        CANCEL_FAILED,
        CANCEL_SUBMITTED_UNCONFIRMED,
        CANCEL_UNKNOWN,
        cancellation_result,
    )

    _SKIP = None
except ModuleNotFoundError as exc:
    _SKIP = str(exc)
finally:
    socket.socket.connect = _ORIGINAL_SOCKET_CONNECT
    socket.socket.connect_ex = _ORIGINAL_SOCKET_CONNECT_EX
    socket.create_connection = _ORIGINAL_CREATE_CONNECTION

_SKIP_MSG = f"boost_manager unavailable: {_SKIP}"


class _FakeOfferManager:
    """Minimal fake with a price cache so _find_stale_offers can find prices."""

    def __init__(self, prices=None):
        self._offer_details_cache = {
            tid: {"price": price} for tid, price in (prices or {}).items()
        }
        self._cycle_used_coin_ids = set()


def _cancel_result(outcome):
    transaction_id = "a" * 64 if outcome == CANCEL_SUBMITTED_UNCONFIRMED else ""
    return cancellation_result(
        outcome,
        method="boost_manager_test",
        raw_response={"outcome": outcome},
        transaction_id=transaction_id,
        error="REJECTED" if outcome == CANCEL_FAILED else None,
    )


def _offer_manager_cancel_envelope(
    outcome,
    *,
    trade_id,
    intent_id=None,
    effect_attempted=True,
    idempotent_replay=False,
    attempt=1,
):
    return {
        **_cancel_result(outcome),
        "_catalyst_effect_attempted": effect_attempted,
        "_catalyst_idempotent_replay": idempotent_replay,
        "_catalyst_operation_id": f"cancel:{trade_id}",
        "_catalyst_intent_id": intent_id or f"cancel-target:{trade_id}",
        "_catalyst_attempt": attempt,
    }


class _ReplacementOfferManager:
    def __init__(
        self,
        cancel_result=None,
        *,
        intent_ids=None,
        cancel_authorities=None,
    ):
        self._bot_cancelled_ids = set()
        self._cycle_used_coin_ids = set()
        self._offer_details_cache = {}
        self.cancel_calls = []
        self.create_calls = []
        self.cancel_result = cancel_result or _cancel_result(CANCEL_FAILED)
        self.intent_ids = dict(intent_ids or {})
        self.cancel_authorities = dict(cancel_authorities or {})

    def _canonical_cancel_intent(self, trade_id):
        return SimpleNamespace(
            trade_id=trade_id,
            operation_id=f"cancel:{trade_id}",
            intent_id=self.intent_ids.get(trade_id, f"cancel-target:{trade_id}"),
        )

    def cancel_offers(self, trade_ids, **kwargs):
        trade_ids = list(trade_ids)
        self.cancel_calls.append((trade_ids, kwargs))
        return {trade_id: self.cancel_result for trade_id in trade_ids}

    def get_cancel_result_authority(self, trade_id):
        if trade_id in self.cancel_authorities:
            return self.cancel_authorities[trade_id]
        result = self.cancel_result
        if type(result) is dict and set(result) & {
            "_catalyst_effect_attempted",
            "_catalyst_idempotent_replay",
            "_catalyst_operation_id",
            "_catalyst_intent_id",
            "_catalyst_attempt",
        } == {
            "_catalyst_effect_attempted",
            "_catalyst_idempotent_replay",
            "_catalyst_operation_id",
            "_catalyst_intent_id",
            "_catalyst_attempt",
        }:
            return {
                "trade_id": trade_id,
                "operation_id": result["_catalyst_operation_id"],
                "intent_id": result["_catalyst_intent_id"],
                "attempt": result["_catalyst_attempt"],
                "outcome": result["outcome"],
            }
        return None

    def create_ladder(self, *args, **kwargs):
        self.create_calls.append((args, kwargs))
        side = args[1]
        return [{"trade_id": f"{side}-new", "offer_bech32": f"offer-{side}"}]


# ---------------------------------------------------------------------------
# _bps_to_pct
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, _SKIP_MSG)
class TestBoostBpsToPct(unittest.TestCase):
    def test_30_bps(self):
        self.assertEqual(_bps_to_pct(30), "0.30%")

    def test_100_bps(self):
        self.assertEqual(_bps_to_pct(100), "1.0%")

    def test_invalid_input(self):
        result = _bps_to_pct("not_a_number")
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# BoostManager._find_stale_offers
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, _SKIP_MSG)
class TestFindStaleOffers(unittest.TestCase):
    """_find_stale_offers uses offer_manager._offer_details_cache for prices."""

    def _make_manager(self, prices=None):
        return BoostManager(offer_manager=_FakeOfferManager(prices))

    def test_empty_offers_returns_empty(self):
        mgr = self._make_manager()
        result = mgr._find_stale_offers([], Decimal("0.001"), "buy", Decimal("0.05"))
        self.assertEqual(result, [])

    def test_zero_mid_price_returns_empty(self):
        prices = {"tid1": Decimal("0.001")}
        mgr = self._make_manager(prices)
        offers = [{"trade_id": "tid1"}]
        result = mgr._find_stale_offers(offers, Decimal("0"), "buy", Decimal("0.05"))
        self.assertEqual(result, [])

    def test_no_offer_manager_returns_empty(self):
        mgr = BoostManager(offer_manager=None)
        offers = [{"trade_id": "tid1"}]
        result = mgr._find_stale_offers(
            offers, Decimal("0.001"), "buy", Decimal("0.05")
        )
        self.assertEqual(result, [])

    def test_stale_offer_identified(self):
        # mid=0.001, spread=0.05 → target_bps=500
        # offer at 0.002 → distance = 0.001/0.001 * 10000 = 10000 bps > 500 → stale
        prices = {"tid1": Decimal("0.002")}
        mgr = self._make_manager(prices)
        offers = [{"trade_id": "tid1"}]
        result = mgr._find_stale_offers(
            offers, Decimal("0.001"), "buy", Decimal("0.05")
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["trade_id"], "tid1")

    def test_fresh_offer_not_stale(self):
        # offer at 0.00103 → distance = 0.00003/0.001 * 10000 = 300 bps < 500 → not stale
        prices = {"tid1": Decimal("0.00103")}
        mgr = self._make_manager(prices)
        offers = [{"trade_id": "tid1"}]
        result = mgr._find_stale_offers(
            offers, Decimal("0.001"), "buy", Decimal("0.05")
        )
        self.assertEqual(result, [])

    def test_sorted_most_stale_first(self):
        # tid1: 0.0015 → 5000 bps from 0.001, tid2: 0.002 → 10000 bps → tid2 first
        prices = {"tid1": Decimal("0.0015"), "tid2": Decimal("0.002")}
        mgr = self._make_manager(prices)
        offers = [{"trade_id": "tid1"}, {"trade_id": "tid2"}]
        result = mgr._find_stale_offers(
            offers, Decimal("0.001"), "buy", Decimal("0.05")
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["trade_id"], "tid2")  # most stale first

    def test_offers_missing_trade_id_skipped(self):
        mgr = self._make_manager({"": Decimal("0.002")})
        offers = [{"no_trade_id": True}]
        result = mgr._find_stale_offers(
            offers, Decimal("0.001"), "buy", Decimal("0.05")
        )
        self.assertEqual(result, [])

    def test_distance_bps_appended_to_result(self):
        prices = {"tid1": Decimal("0.002")}
        mgr = self._make_manager(prices)
        offers = [{"trade_id": "tid1"}]
        result = mgr._find_stale_offers(
            offers, Decimal("0.001"), "buy", Decimal("0.05")
        )
        self.assertIn("_distance_bps", result[0])
        self.assertGreater(result[0]["_distance_bps"], 0)


@unittest.skipIf(_SKIP is not None, _SKIP_MSG)
class TestFlexibleProbeSize(unittest.TestCase):
    def test_activate_creates_only_one_inverted_probe_side(self):
        class OfferManager:
            def __init__(self):
                self.created_sides = []
                self._cycle_used_coin_ids = set()
                self._offer_details_cache = {}

            def create_offer_with_retry(self, offer_dict, **_kwargs):
                side = "buy" if offer_dict.get("1", 0) < 0 else "sell"
                self.created_sides.append(side)
                return {
                    "success": True,
                    "trade_id": f"tid-{side}-{len(self.created_sides)}",
                    "offer": f"offer-{side}-{len(self.created_sides)}",
                    "locked_coin_id": f"coin-{side}-{len(self.created_sides)}",
                }

        class DexiePoster:
            def __init__(self):
                self.posted = []

            def _post_single(self, bech32, trade_id, force=False):
                self.posted.append((bech32, trade_id, force))

        fake_cfg = SimpleNamespace(
            CAT_DECIMALS=3,
            CAT_ASSET_ID="asset",
            CAT_WALLET_ID=2,
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=True,
            DRY_RUN=False,
            ENABLE_BUY=True,
            ENABLE_SELL=True,
            GAP_PROBE_INITIAL_PAST_FEE_BPS=10,
            SNIPER_EXPIRY_SECS=600,
            SNIPER_SIZE_XCH="0.001",
            TIBETSWAP_FEE_BPS=70,
            WALLET_ID_XCH=1,
        )
        offer_manager = OfferManager()
        dexie = DexiePoster()
        mgr = BoostManager(offer_manager=offer_manager, dexie_manager=dexie)

        with (
            patch.object(_bm_mod, "cfg", fake_cfg),
            patch.object(_bm_mod, "add_offer", return_value=True),
            patch.object(_bm_mod, "lock_coin"),
            patch.object(_bm_mod, "log_event"),
        ):
            result = mgr.activate(Decimal("0.0001"))

        self.assertTrue(result["success"])
        self.assertEqual(result["created"], 1)
        self.assertEqual(offer_manager.created_sides, ["buy"])
        self.assertEqual(len(dexie.posted), 1)
        self.assertEqual(mgr._buy_probe_tid, "tid-buy-1")
        self.assertEqual(mgr._sell_probe_tid, "")

    def test_step_creates_missing_alternating_inverted_probe_side(self):
        class OfferManager:
            def __init__(self):
                self.created_sides = []
                self._cycle_used_coin_ids = set()
                self._offer_details_cache = {}

            def create_offer_with_retry(self, offer_dict, **_kwargs):
                side = "buy" if offer_dict.get("1", 0) < 0 else "sell"
                self.created_sides.append(side)
                return {
                    "success": True,
                    "trade_id": f"tid-{side}-{len(self.created_sides)}",
                    "offer": f"offer-{side}-{len(self.created_sides)}",
                    "locked_coin_id": f"coin-{side}-{len(self.created_sides)}",
                }

        fake_cfg = SimpleNamespace(
            CAT_DECIMALS=3,
            CAT_ASSET_ID="asset",
            CAT_WALLET_ID=2,
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=False,
            DRY_RUN=False,
            ENABLE_BUY=True,
            ENABLE_SELL=True,
            GAP_CLOSE_STEP_COOLDOWN_SECS=60,
            GAP_PROBE_MAX_PAST_FEE_BPS=500,
            GAP_PROBE_STEP_BPS=30,
            SNIPER_EXPIRY_SECS=600,
            SNIPER_SIZE_XCH="0.001",
            TIBETSWAP_FEE_BPS=70,
            WALLET_ID_XCH=1,
        )
        offer_manager = OfferManager()
        mgr = BoostManager(offer_manager=offer_manager)
        mgr._boost_active = True
        mgr._boost_mid_price = Decimal("0.0001")
        mgr._buy_offset_bps = 80
        mgr._sell_offset_bps = 80
        mgr._next_step_is_buy = False
        mgr._stable_since = 1
        mgr._last_step_time = 1

        with (
            patch.object(_bm_mod, "cfg", fake_cfg),
            patch.object(_bm_mod, "add_offer", return_value=True),
            patch.object(_bm_mod, "lock_coin"),
            patch.object(_bm_mod, "log_event"),
            patch.object(_bm_mod.time, "time", return_value=1000),
        ):
            acted = mgr.step_tighter(Decimal("0"))

        self.assertTrue(acted)
        self.assertEqual(offer_manager.created_sides, ["sell"])
        self.assertEqual(mgr._sell_probe_tid, "tid-sell-1")
        self.assertIn("tid-sell-1", mgr._active_boost_ids)

    def test_gap_closer_created_log_preserves_sub_one_cat_amounts(self):
        class OfferManager:
            def __init__(self):
                self._cycle_used_coin_ids = set()
                self._offer_details_cache = {}

            def create_offer_with_retry(self, *_args, **_kwargs):
                return {
                    "success": True,
                    "trade_id": "tid-low-decimal",
                    "offer": "offer-low-decimal",
                    "locked_coin_id": "coin-low-decimal",
                }

        fake_cfg = SimpleNamespace(
            CAT_DECIMALS=3,
            CAT_ASSET_ID="asset",
            CAT_WALLET_ID=2,
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=False,
            DRY_RUN=False,
            SNIPER_EXPIRY_SECS=600,
            WALLET_ID_XCH=1,
        )
        mgr = BoostManager(offer_manager=OfferManager())

        with (
            patch.object(_bm_mod, "cfg", fake_cfg),
            patch.object(_bm_mod, "add_offer", return_value=True),
            patch.object(_bm_mod, "lock_coin"),
            patch.object(_bm_mod, "log_event") as log_event_mock,
        ):
            mgr._create_single_offer("buy", Decimal("250"), Decimal("0.5"))

        messages = [call.args[2] for call in log_event_mock.call_args_list]
        self.assertTrue(any("0.002 CAT" in msg for msg in messages))
        self.assertFalse(any("0.00 CAT" in msg for msg in messages))

    def test_sell_probe_retries_with_smaller_sniper_coin(self):
        class FlexibleOfferManager:
            def __init__(self):
                self.calls = []
                self._cycle_used_coin_ids = set()
                self._offer_details_cache = {}

            def create_offer_with_retry(self, offer_dict, **kwargs):
                self.calls.append((offer_dict, kwargs))
                if kwargs.get("selected_coin_id") == "cat-sniper-79000":
                    return {
                        "success": True,
                        "trade_id": "tid-flex",
                        "offer": "offer-flex",
                        "locked_coin_id": "cat-sniper-79000",
                    }
                return {
                    "success": False,
                    "error": "no_preferred_tier_coin",
                    "preferred_tier": "sniper",
                }

        fake_cfg = SimpleNamespace(
            CAT_DECIMALS=3,
            CAT_ASSET_ID="asset",
            CAT_WALLET_ID=2,
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=False,
            DRY_RUN=False,
            SNIPER_EXPIRY_SECS=600,
            WALLET_ID_XCH=1,
        )
        offer_manager = FlexibleOfferManager()
        mgr = BoostManager(offer_manager=offer_manager)

        with (
            patch.object(_bm_mod, "cfg", fake_cfg),
            patch.object(_bm_mod, "add_offer", return_value=True),
            patch.object(_bm_mod, "lock_coin"),
            patch.object(
                mgr,
                "_find_flexible_sniper_coin",
                return_value={"coin_id": "cat-sniper-79000", "amount_mojos": 79000},
                create=True,
            ),
        ):
            result = mgr._create_single_offer(
                "sell", Decimal("0.0001175"), Decimal("0.01")
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["trade_id"], "tid-flex")
        self.assertEqual(result["size_cat"], Decimal("79"))
        self.assertEqual(result["size_xch"], Decimal("0.0092825"))
        self.assertEqual(len(offer_manager.calls), 2)

        retry_offer, retry_kwargs = offer_manager.calls[1]
        self.assertEqual(retry_offer[str(fake_cfg.CAT_WALLET_ID)], -79000)
        self.assertEqual(retry_kwargs["selected_coin_id"], "cat-sniper-79000")


@unittest.skipIf(_SKIP is not None, _SKIP_MSG)
class TestReplacementCancellationBoundary(unittest.TestCase):
    def _step_manager(self, side, cancel_result=None):
        offer_manager = _ReplacementOfferManager(cancel_result)
        manager = BoostManager(offer_manager=offer_manager)
        manager._boost_active = True
        manager._boost_mid_price = Decimal("0.0001")
        manager._buy_offset_bps = 80
        manager._sell_offset_bps = 80
        manager._buy_probe_tid = "buy-old"
        manager._sell_probe_tid = "sell-old"
        manager._active_boost_ids = ["buy-old", "sell-old"]
        manager._next_step_is_buy = side == "buy"
        manager._stable_since = 1
        manager._last_step_time = 1
        return manager, offer_manager

    def _step_cfg(self):
        return SimpleNamespace(
            ENABLE_BUY=True,
            ENABLE_SELL=True,
            GAP_CLOSE_STEP_COOLDOWN_SECS=60,
            GAP_PROBE_MAX_PAST_FEE_BPS=500,
            GAP_PROBE_STEP_BPS=30,
            TIBETSWAP_FEE_BPS=70,
        )

    def test_offer_manager_metadata_envelope_preserves_all_typed_outcomes(self):
        trade_id = "1" * 64
        intent_id = "a" * 64
        expected = {
            CANCEL_CONFIRMED: CANCEL_UNKNOWN,
            CANCEL_FAILED: CANCEL_FAILED,
            CANCEL_SUBMITTED_UNCONFIRMED: CANCEL_SUBMITTED_UNCONFIRMED,
            CANCEL_UNKNOWN: CANCEL_UNKNOWN,
        }
        for outcome, expected_outcome in expected.items():
            with self.subTest(outcome=outcome):
                envelope = _offer_manager_cancel_envelope(
                    outcome,
                    trade_id=trade_id,
                    intent_id=intent_id,
                    effect_attempted=outcome != CANCEL_UNKNOWN,
                    idempotent_replay=outcome == CANCEL_UNKNOWN,
                    attempt=2,
                )
                offer_manager = _ReplacementOfferManager(
                    envelope,
                    intent_ids={trade_id: intent_id},
                )
                manager = BoostManager(offer_manager=offer_manager)

                outcomes = manager._request_replacement_cancels(
                    [trade_id], reason="metadata-envelope-test"
                )

                self.assertEqual(outcomes, {trade_id: expected_outcome})
                if outcome == CANCEL_FAILED:
                    self.assertNotIn(trade_id, offer_manager._bot_cancelled_ids)
                else:
                    self.assertIn(trade_id, offer_manager._bot_cancelled_ids)

    def test_bare_results_never_treat_confirmation_as_authoritative(self):
        trade_id = "4" * 64
        cases = (
            (CANCEL_CONFIRMED, CANCEL_UNKNOWN, True),
            (CANCEL_FAILED, CANCEL_FAILED, False),
            (
                CANCEL_SUBMITTED_UNCONFIRMED,
                CANCEL_SUBMITTED_UNCONFIRMED,
                True,
            ),
            (CANCEL_UNKNOWN, CANCEL_UNKNOWN, True),
        )
        for supplied, expected, marker_retained in cases:
            with self.subTest(outcome=supplied):
                offer_manager = _ReplacementOfferManager(_cancel_result(supplied))
                manager = BoostManager(offer_manager=offer_manager)

                outcomes = manager._request_replacement_cancels(
                    [trade_id], reason="bare-result-authority-test"
                )

                self.assertEqual(outcomes, {trade_id: expected})
                self.assertEqual(
                    trade_id in offer_manager._bot_cancelled_ids,
                    marker_retained,
                )

    def test_enriched_results_with_wrong_positive_attempt_fail_closed(self):
        trade_id = "5" * 64
        intent_id = "e" * 64
        for outcome in (
            CANCEL_CONFIRMED,
            CANCEL_FAILED,
            CANCEL_SUBMITTED_UNCONFIRMED,
            CANCEL_UNKNOWN,
        ):
            with self.subTest(outcome=outcome):
                envelope = _offer_manager_cancel_envelope(
                    outcome,
                    trade_id=trade_id,
                    intent_id=intent_id,
                    effect_attempted=outcome != CANCEL_UNKNOWN,
                    idempotent_replay=outcome == CANCEL_UNKNOWN,
                    attempt=3,
                )
                offer_manager = _ReplacementOfferManager(
                    envelope,
                    intent_ids={trade_id: intent_id},
                    cancel_authorities={
                        trade_id: {
                            "trade_id": trade_id,
                            "operation_id": f"cancel:{trade_id}",
                            "intent_id": intent_id,
                            "attempt": 2,
                            "outcome": outcome,
                        }
                    },
                )
                authority = offer_manager.get_cancel_result_authority(trade_id)
                with self.assertRaisesRegex(ValueError, "metadata"):
                    _bm_mod._validated_replacement_cancel_envelope(
                        envelope,
                        expected_identity=(f"cancel:{trade_id}", intent_id),
                        expected_authority=authority,
                    )
                manager = BoostManager(offer_manager=offer_manager)

                outcomes = manager._request_replacement_cancels(
                    [trade_id], reason="wrong-attempt-authority-test"
                )

                self.assertEqual(outcomes, {trade_id: CANCEL_UNKNOWN})
                self.assertIn(trade_id, offer_manager._bot_cancelled_ids)

    def test_metadata_enriched_confirmed_result_can_replace_exact_old_offer(self):
        trade_id = "2" * 64
        intent_id = "b" * 64
        envelope = _offer_manager_cancel_envelope(
            CANCEL_CONFIRMED,
            trade_id=trade_id,
            intent_id=intent_id,
            effect_attempted=False,
            idempotent_replay=True,
            attempt=3,
        )
        offer_manager = _ReplacementOfferManager(
            envelope,
            intent_ids={trade_id: intent_id},
        )
        manager = BoostManager(offer_manager=offer_manager)
        manager._boost_active = True
        manager._boost_mid_price = Decimal("0.0001")
        manager._buy_offset_bps = 80
        manager._sell_offset_bps = 80
        manager._buy_probe_tid = trade_id
        manager._sell_probe_tid = None
        manager._active_boost_ids = [trade_id]
        manager._next_step_is_buy = True
        manager._stable_since = 1
        manager._last_step_time = 1
        new_offer = {"trade_id": "buy-new", "offer_bech32": "offer-buy-new"}
        config = self._step_cfg()
        config.DEXIE_AUTO_POST = False
        with (
            patch.object(_bm_mod, "cfg", config),
            patch.object(_bm_mod.time, "time", return_value=1000),
            patch.object(_bm_mod.time, "sleep"),
            patch.object(manager, "_create_single_offer", return_value=new_offer),
            patch.object(
                _bm_mod, "_has_authoritative_terminal_proof", return_value=True
            ),
            patch.object(_bm_mod, "log_event"),
        ):
            acted = manager.step_tighter(Decimal("0"))

        self.assertTrue(acted)
        self.assertEqual(manager._buy_probe_tid, "buy-new")
        self.assertNotIn(trade_id, manager._active_boost_ids)

    def test_partial_extra_cross_bound_and_hostile_metadata_fail_closed(self):
        trade_id = "3" * 64
        intent_id = "c" * 64
        canonical = _offer_manager_cancel_envelope(
            CANCEL_FAILED,
            trade_id=trade_id,
            intent_id=intent_id,
        )

        class HostileDict(dict):
            pass

        malformed = []
        partial = dict(canonical)
        del partial["_catalyst_attempt"]
        malformed.append(partial)
        malformed.append({**canonical, "unexpected": True})
        malformed.append({**canonical, "_catalyst_effect_attempted": 1})
        malformed.append({**canonical, "_catalyst_idempotent_replay": 0})
        malformed.append({**canonical, "_catalyst_operation_id": "cancel:" + "4" * 64})
        malformed.append({**canonical, "_catalyst_intent_id": "d" * 64})
        malformed.append({**canonical, "_catalyst_attempt": True})
        malformed.append({**canonical, "_catalyst_attempt": 0})
        malformed.append({**canonical, "_catalyst_idempotent_replay": True})
        malformed.append(HostileDict(canonical))
        for case_index, result in enumerate(malformed):
            # xdist must serialize subtest metadata back to the controller;
            # never include the deliberately hostile mapping itself.
            with self.subTest(
                case_index=case_index,
                result_type=type(result).__name__,
            ):
                offer_manager = _ReplacementOfferManager(
                    result,
                    intent_ids={trade_id: intent_id},
                )
                manager = BoostManager(offer_manager=offer_manager)

                outcomes = manager._request_replacement_cancels(
                    [trade_id], reason="hostile-envelope-test"
                )

                self.assertEqual(outcomes, {trade_id: CANCEL_UNKNOWN})
                self.assertIn(trade_id, offer_manager._bot_cancelled_ids)

    def test_buy_step_failed_cancel_retains_old_probe_and_creates_nothing(self):
        manager, offer_manager = self._step_manager("buy")
        with (
            patch.object(_bm_mod, "cfg", self._step_cfg()),
            patch.object(_bm_mod.time, "time", return_value=1000),
            patch.object(_bm_mod.time, "sleep"),
            patch.object(manager, "_create_single_offer") as create,
            patch.object(_bm_mod, "log_event"),
        ):
            acted = manager.step_tighter(Decimal("0"))

        self.assertFalse(acted)
        self.assertEqual(manager._buy_offset_bps, 80)
        self.assertEqual(manager._buy_probe_tid, "buy-old")
        self.assertIn("buy-old", manager._active_boost_ids)
        create.assert_not_called()
        self.assertEqual(len(offer_manager.cancel_calls), 1)

    def test_sell_step_failed_cancel_retains_old_probe_and_creates_nothing(self):
        manager, offer_manager = self._step_manager("sell")
        with (
            patch.object(_bm_mod, "cfg", self._step_cfg()),
            patch.object(_bm_mod.time, "time", return_value=1000),
            patch.object(_bm_mod.time, "sleep"),
            patch.object(manager, "_create_single_offer") as create,
            patch.object(_bm_mod, "log_event"),
        ):
            acted = manager.step_tighter(Decimal("0"))

        self.assertFalse(acted)
        self.assertEqual(manager._sell_offset_bps, 80)
        self.assertEqual(manager._sell_probe_tid, "sell-old")
        self.assertIn("sell-old", manager._active_boost_ids)
        create.assert_not_called()
        self.assertEqual(len(offer_manager.cancel_calls), 1)

    def test_buy_step_submitted_unknown_and_malformed_results_all_block(self):
        blocked_results = (
            _cancel_result(CANCEL_SUBMITTED_UNCONFIRMED),
            _cancel_result(CANCEL_UNKNOWN),
            {"success": True},
        )
        for cancel_result in blocked_results:
            with self.subTest(cancel_result=cancel_result):
                manager, _offer_manager = self._step_manager("buy", cancel_result)
                with (
                    patch.object(_bm_mod, "cfg", self._step_cfg()),
                    patch.object(_bm_mod.time, "time", return_value=1000),
                    patch.object(_bm_mod.time, "sleep"),
                    patch.object(manager, "_create_single_offer") as create,
                    patch.object(_bm_mod, "log_event"),
                ):
                    acted = manager.step_tighter(Decimal("0"))

                self.assertFalse(acted)
                self.assertEqual(manager._buy_probe_tid, "buy-old")
                self.assertIn("buy-old", manager._active_boost_ids)
                create.assert_not_called()

    def test_buy_step_bare_confirmed_result_retains_slot_and_creates_nothing(self):
        manager, _offer_manager = self._step_manager(
            "buy", _cancel_result(CANCEL_CONFIRMED)
        )
        new_offer = {"trade_id": "buy-new", "offer_bech32": "offer-buy-new"}
        config = self._step_cfg()
        config.DEXIE_AUTO_POST = False
        with (
            patch.object(_bm_mod, "cfg", config),
            patch.object(_bm_mod.time, "time", return_value=1000),
            patch.object(_bm_mod.time, "sleep"),
            patch.object(
                manager, "_create_single_offer", return_value=new_offer
            ) as create,
            patch.object(_bm_mod, "log_event"),
        ):
            acted = manager.step_tighter(Decimal("0"))

        self.assertFalse(acted)
        self.assertEqual(manager._buy_probe_tid, "buy-old")
        self.assertIn("buy-old", manager._active_boost_ids)
        self.assertNotIn("buy-new", manager._active_boost_ids)
        create.assert_not_called()

    def test_legacy_subprobe_failed_cancel_retains_pair_and_spread(self):
        offer_manager = _ReplacementOfferManager()
        manager = BoostManager(offer_manager=offer_manager)
        manager._boost_active = True
        manager._boost_mid_price = Decimal("0.0001")
        manager._gap_spread_bps = 100
        manager._active_boost_ids = ["buy-old", "sell-old"]
        manager._stable_since = 1
        manager._last_step_time = 1
        config = SimpleNamespace(
            GAP_CLOSE_BELOW_FLOOR_MULT=0.25,
            GAP_CLOSE_SAFETY_BUFFER_BPS=20,
            GAP_CLOSE_STEP_COOLDOWN_SECS=60,
        )
        with (
            patch.object(_bm_mod, "cfg", config),
            patch.object(_bm_mod.time, "time", return_value=1000),
            patch.object(manager, "_create_gap_closer_pair") as create,
            patch.object(_bm_mod, "log_event"),
        ):
            acted = manager._legacy_step_tighter(Decimal("100"))

        self.assertFalse(acted)
        self.assertEqual(manager._gap_spread_bps, 100)
        self.assertEqual(manager._active_boost_ids, ["buy-old", "sell-old"])
        create.assert_not_called()

    def test_legacy_step_failed_cancel_retains_pair_and_spread(self):
        offer_manager = _ReplacementOfferManager()
        manager = BoostManager(offer_manager=offer_manager)
        manager._boost_active = True
        manager._boost_mid_price = Decimal("0.0001")
        manager._gap_spread_bps = 200
        manager._active_boost_ids = ["buy-old", "sell-old"]
        manager._stable_since = 1
        manager._last_step_time = 1
        config = SimpleNamespace(
            GAP_CLOSE_SAFETY_BUFFER_BPS=20,
            GAP_CLOSE_STEP_COOLDOWN_SECS=60,
            GAP_CLOSE_STEP_PCT=10,
        )
        with (
            patch.object(_bm_mod, "cfg", config),
            patch.object(_bm_mod.time, "time", return_value=1000),
            patch.object(manager, "_create_gap_closer_pair") as create,
            patch.object(_bm_mod, "log_event"),
        ):
            acted = manager._legacy_step_tighter(Decimal("0"))

        self.assertFalse(acted)
        self.assertEqual(manager._gap_spread_bps, 200)
        self.assertEqual(manager._active_boost_ids, ["buy-old", "sell-old"])
        create.assert_not_called()

    def test_refresh_failed_cancel_retains_old_pair_and_creates_nothing(self):
        offer_manager = _ReplacementOfferManager()
        manager = BoostManager(offer_manager=offer_manager)
        manager._boost_active = True
        manager._boost_mid_price = Decimal("0.0001")
        manager._gap_spread_bps = 100
        manager._buy_probe_tid = "buy-old"
        manager._sell_probe_tid = "sell-old"
        manager._active_boost_ids = ["buy-old", "sell-old"]
        config = SimpleNamespace()
        with (
            patch.object(_bm_mod, "cfg", config),
            patch.object(_bm_mod.time, "sleep"),
            patch.object(manager, "_create_inverted_probe_pair") as create,
            patch.object(_bm_mod, "log_event"),
        ):
            acted = manager.refresh_if_needed(Decimal("0.0002"))

        self.assertFalse(acted)
        self.assertEqual(manager._active_boost_ids, ["buy-old", "sell-old"])
        self.assertEqual(manager._buy_probe_tid, "buy-old")
        self.assertEqual(manager._sell_probe_tid, "sell-old")
        create.assert_not_called()

    def test_handoff_failed_cancel_creates_and_posts_nothing(self):
        offer_manager = _ReplacementOfferManager()
        offer_manager._offer_details_cache["buy-old"] = {"price": "0.00008"}
        dexie = SimpleNamespace(queue_post=unittest.mock.Mock())
        manager = BoostManager(
            offer_manager=offer_manager,
            dexie_manager=dexie,
            risk_manager=object(),
        )
        manager._boost_mid_price = Decimal("0.0001")
        manager._gap_spread_bps = 100
        config = SimpleNamespace(
            CAT_ASSET_ID="asset",
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=True,
            ENABLE_BUY=True,
            ENABLE_SELL=False,
        )
        with (
            patch.object(_bm_mod, "cfg", config),
            patch.object(
                _bm_mod,
                "db_get_open_offers",
                return_value=[{"trade_id": "buy-old", "tier": "inner"}],
            ),
            patch.object(_bm_mod, "log_event"),
        ):
            manager._handoff_to_inner_tier()

        self.assertEqual(len(offer_manager.cancel_calls), 1)
        self.assertEqual(offer_manager.create_calls, [])
        dexie.queue_post.assert_not_called()

    def test_inverted_cascade_failed_cancel_creates_and_posts_nothing(self):
        offer_manager = _ReplacementOfferManager()
        dexie = SimpleNamespace(queue_post=unittest.mock.Mock())
        splash = SimpleNamespace(queue_post=unittest.mock.Mock())
        manager = BoostManager(
            offer_manager=offer_manager,
            dexie_manager=dexie,
            risk_manager=object(),
            splash_manager=splash,
        )
        manager._boost_mid_price = Decimal("0.0001")
        config = SimpleNamespace(
            CAT_ASSET_ID="asset",
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=True,
            ENABLE_BUY=True,
            ENABLE_SELL=False,
            GAP_PROBE_CASCADE_COUNT_PER_SIDE=1,
            GAP_PROBE_CASCADE_HALF_SPREAD_BPS=50,
            SPLASH_ENABLED=True,
        )
        with (
            patch.object(_bm_mod, "cfg", config),
            patch(
                "database.get_open_offers",
                return_value=[
                    {"trade_id": "buy-old", "tier": "inner", "price": "0.00008"}
                ],
            ),
            patch.object(_bm_mod, "log_event"),
        ):
            manager._cascade_after_inverted_floor()

        self.assertEqual(len(offer_manager.cancel_calls), 1)
        self.assertEqual(offer_manager.create_calls, [])
        dexie.queue_post.assert_not_called()
        splash.queue_post.assert_not_called()

    def test_main_book_cascade_failed_cancel_creates_and_posts_nothing(self):
        offer_manager = _ReplacementOfferManager()
        risk_manager = SimpleNamespace(
            get_adjusted_spread=lambda _side: Decimal("0.01")
        )
        dexie = SimpleNamespace(queue_post=unittest.mock.Mock())
        manager = BoostManager(
            offer_manager=offer_manager,
            dexie_manager=dexie,
            risk_manager=risk_manager,
        )
        manager._boost_active = True
        manager._gap_spread_bps = 100
        stale = {"trade_id": "buy-old", "price": "0.00008"}
        config = SimpleNamespace(
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=True,
            ENABLE_BUY=True,
            ENABLE_SELL=False,
            GAP_CLOSE_CASCADE_BATCH_SIZE=1,
        )
        with (
            patch.object(_bm_mod, "cfg", config),
            patch.object(manager, "_find_stale_offers", return_value=[stale]),
            patch.object(_bm_mod, "log_event"),
        ):
            result = manager.cascade_main_book(Decimal("0.0001"), [stale], [])

        self.assertFalse(result["success"])
        self.assertEqual(len(offer_manager.cancel_calls), 1)
        self.assertEqual(offer_manager.create_calls, [])
        dexie.queue_post.assert_not_called()

    def test_main_book_cascade_replaces_only_exact_confirmed_member(self):
        confirmed_trade_id = "6" * 64
        failed_trade_id = "7" * 64

        class MixedOfferManager(_ReplacementOfferManager):
            def __init__(self):
                super().__init__()
                self.results = {
                    confirmed_trade_id: _offer_manager_cancel_envelope(
                        CANCEL_CONFIRMED,
                        trade_id=confirmed_trade_id,
                        effect_attempted=False,
                        idempotent_replay=True,
                        attempt=2,
                    ),
                    failed_trade_id: _offer_manager_cancel_envelope(
                        CANCEL_FAILED,
                        trade_id=failed_trade_id,
                        attempt=1,
                    ),
                }

            def cancel_offers(self, trade_ids, **kwargs):
                trade_ids = list(trade_ids)
                self.cancel_calls.append((trade_ids, kwargs))
                return {trade_id: self.results[trade_id] for trade_id in trade_ids}

            def get_cancel_result_authority(self, trade_id):
                result = self.results[trade_id]
                return {
                    "trade_id": trade_id,
                    "operation_id": result["_catalyst_operation_id"],
                    "intent_id": result["_catalyst_intent_id"],
                    "attempt": result["_catalyst_attempt"],
                    "outcome": result["outcome"],
                }

        offer_manager = MixedOfferManager()
        risk_manager = SimpleNamespace(
            get_adjusted_spread=lambda _side: Decimal("0.01")
        )
        manager = BoostManager(
            offer_manager=offer_manager,
            risk_manager=risk_manager,
        )
        manager._boost_active = True
        manager._gap_spread_bps = 100
        stale = [
            {"trade_id": confirmed_trade_id, "price": "0.00008"},
            {"trade_id": failed_trade_id, "price": "0.00007"},
        ]
        config = SimpleNamespace(
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=False,
            ENABLE_BUY=True,
            ENABLE_SELL=False,
            GAP_CLOSE_CASCADE_BATCH_SIZE=2,
        )
        with (
            patch.object(_bm_mod, "cfg", config),
            patch.object(manager, "_find_stale_offers", return_value=stale),
            patch.object(
                _bm_mod,
                "_has_authoritative_terminal_proof",
                side_effect=lambda trade_id: trade_id == confirmed_trade_id,
            ),
            patch.object(_bm_mod, "log_event"),
        ):
            result = manager.cascade_main_book(Decimal("0.0001"), stale, [])

        self.assertTrue(result["success"])
        self.assertEqual(result["total_created"], 1)
        self.assertEqual(result["total_cancelled"], 1)
        self.assertEqual(offer_manager.create_calls[0][1]["num_offers"], 1)
        self.assertIn(confirmed_trade_id, offer_manager._bot_cancelled_ids)
        self.assertNotIn(failed_trade_id, offer_manager._bot_cancelled_ids)


@unittest.skipIf(_SKIP is not None, _SKIP_MSG)
class TestInvertedCascadeBroadcast(unittest.TestCase):
    def test_inverted_cascade_queues_new_offers_to_dexie_and_splash(self):
        buy_old_1 = "8" * 64
        buy_old_2 = "9" * 64
        sell_old_1 = "a" * 64
        sell_old_2 = "b" * 64

        class QueuePoster:
            def __init__(self):
                self.queued = []

            def queue_post(self, bech32, trade_id):
                self.queued.append((bech32, trade_id))

        class CascadeOfferManager:
            def __init__(self):
                self._bot_cancelled_ids = set()
                self.cancelled = []
                self.cancel_results = {}

            @staticmethod
            def _canonical_cancel_intent(trade_id):
                return SimpleNamespace(
                    trade_id=trade_id,
                    operation_id=f"cancel:{trade_id}",
                    intent_id=f"cancel-target:{trade_id}",
                )

            def create_ladder(self, _mid_price, side, **_kwargs):
                return [
                    {
                        "offer_bech32": f"offer1-{side}-1",
                        "trade_id": f"{side}-new-1",
                    },
                    {
                        "offer_bech32": f"offer1-{side}-2",
                        "trade_id": f"{side}-new-2",
                    },
                ]

            def cancel_offers(self, trade_ids, **_kwargs):
                self.cancelled.extend(trade_ids)
                self.cancel_results = {
                    trade_id: _offer_manager_cancel_envelope(
                        CANCEL_CONFIRMED,
                        trade_id=trade_id,
                        effect_attempted=False,
                        idempotent_replay=True,
                    )
                    for trade_id in trade_ids
                }
                return self.cancel_results

            def get_cancel_result_authority(self, trade_id):
                result = self.cancel_results[trade_id]
                return {
                    "trade_id": trade_id,
                    "operation_id": result["_catalyst_operation_id"],
                    "intent_id": result["_catalyst_intent_id"],
                    "attempt": result["_catalyst_attempt"],
                    "outcome": result["outcome"],
                }

        fake_cfg = SimpleNamespace(
            CAT_ASSET_ID="asset",
            COIN_IDS_ENABLED=True,
            DEXIE_AUTO_POST=True,
            ENABLE_BUY=True,
            ENABLE_SELL=True,
            GAP_PROBE_CASCADE_COUNT_PER_SIDE=2,
            GAP_PROBE_CASCADE_HALF_SPREAD_BPS=50,
            SPLASH_ENABLED=True,
        )
        old_offers = {
            "buy": [
                {"trade_id": buy_old_1, "tier": "inner", "price": "0.00009"},
                {"trade_id": buy_old_2, "tier": "inner", "price": "0.00008"},
            ],
            "sell": [
                {"trade_id": sell_old_1, "tier": "inner", "price": "0.00012"},
                {"trade_id": sell_old_2, "tier": "inner", "price": "0.00013"},
            ],
        }

        def get_open_offers(side=None, **_kwargs):
            return old_offers.get(side, [])

        offer_manager = CascadeOfferManager()
        dexie = QueuePoster()
        splash = QueuePoster()
        mgr = BoostManager(
            offer_manager=offer_manager,
            dexie_manager=dexie,
            risk_manager=object(),
            splash_manager=splash,
        )
        mgr._boost_mid_price = Decimal("0.00010")

        with (
            patch.object(_bm_mod, "cfg", fake_cfg),
            patch("database.get_open_offers", side_effect=get_open_offers),
            patch.object(
                _bm_mod, "_has_authoritative_terminal_proof", return_value=True
            ),
            patch.object(_bm_mod, "log_event"),
        ):
            mgr._cascade_after_inverted_floor()

        expected = [
            ("offer1-buy-1", "buy-new-1"),
            ("offer1-buy-2", "buy-new-2"),
            ("offer1-sell-1", "sell-new-1"),
            ("offer1-sell-2", "sell-new-2"),
        ]
        self.assertEqual(dexie.queued, expected)
        self.assertEqual(splash.queued, expected)


if __name__ == "__main__":
    unittest.main()
