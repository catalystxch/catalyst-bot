"""Offer-lifecycle manager for ladder creation, requoting, expiry, and cancellation

The `OfferManager` class bridges pricing and risk output from `PriceEngine` and
`RiskManager` to wallet-RPC offer operations exposed via the `wallet` module.
It owns ladder construction, price-move-triggered requoting, expiry handling,
and batch cancellation, and it maintains `_bot_cancelled_ids` so `FillTracker`
can distinguish genuine fills from bot-initiated cancels.

Key responsibilities:
    - Build buy/sell ladders sized against available coin inventory
    - Requote offers when the mid-price drifts past configured thresholds
    - Cancel offers individually or in batches and track which IDs we cancelled
    - Coordinate with `Sniper` and `BoostManager` to avoid coin double-spend

Thread-safe via `_lock`. All mutating operations should be called while holding
the lock, and any coin reservation crosses through shared state guarded here.
"""

import hashlib
import json
import os
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, List, Tuple, Callable, Any

from config import cfg
from ladder_sizing import classify_slot_tier, ladder_price_for_slot
from database import (
    add_offer,
    update_offer_status,
    transition_offer,
    get_open_offers,
    log_event,
    lock_coin,
    update_offer_bech32,
)
from wallet import (
    create_offer,
    get_all_offers,
    classify_offers_from_list,
    get_offer_bech32,
    cleanup_expired_offers,
    get_exact_spendable_coins_rpc,
    get_wallet_type,
    get_owned_coins_detailed,
)
import database
import mutation_gate
import offer_registry
from refresh_safety import RefreshPlan, plan_refresh
from sage_offer_wire import canonical_sage_offer_text
import wallet
from cancel_outcomes import (
    CANCEL_CONFIRMED,
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    CANCEL_UNKNOWN,
    cancellation_result,
    normalize_cancel_response,
    validate_cancel_result,
)


@dataclass(frozen=True, slots=True)
class _CanonicalOfferCreationIntent:
    intent_id: str
    operation_id: str
    offer_items: tuple[tuple[str, int], ...]
    offered_amount_atomic: str
    requested_amount_atomic: str
    selected_coin_id: str
    asset_id: str
    side: str
    tier: str
    purpose: str
    slot_key: str
    generation: int
    authority_run_id: Optional[str]
    parent_intent_id: Optional[str]
    offer_size_uniqueness_json: str
    expiry_seconds: int
    expiry_offset: int
    stagger_seconds: int
    offer_max_time: int
    min_coin_hint: Optional[int]
    max_coin_hint: Optional[int]
    canonical_intent_sha256: str

    def offer_dict(self) -> dict[str, int]:
        return dict(self.offer_items)

    def offer_size_uniqueness(self) -> dict[str, Any]:
        return json.loads(self.offer_size_uniqueness_json)


@dataclass(frozen=True, slots=True)
class _CanonicalOfferCancelIntent:
    trade_id: str
    intent_id: str
    operation_id: str
    authority_run_id: Optional[str] = None


@dataclass(frozen=True, slots=True)
class _OfferCancelResultProjection:
    result: Optional[dict]
    latch_binding: Optional[tuple[str, str]]
    authoritative: bool


class _OfferCreationClaimLost(Exception):
    """Another exact slot or selected-coin claim committed first."""


def _wallet_mutation_count(result) -> int:
    return result if type(result) is int and result >= 0 else 0


# ---------------------------------------------------------------------------
# Amount conversion helpers (from V1 — critical to get right)
# ---------------------------------------------------------------------------


def xch_to_mojos(amount_xch: Decimal) -> int:
    """Convert XCH to mojos. 1 XCH = 1,000,000,000,000 mojos."""
    return int((amount_xch * Decimal("1000000000000")).to_integral_value(ROUND_DOWN))


def mojos_to_xch(mojos: int) -> Decimal:
    """Convert mojos to XCH."""
    return Decimal(mojos) / Decimal("1000000000000")


def cat_to_mojos(amount: Decimal, decimals: int) -> int:
    """Convert CAT amount to mojos. Uses 10^decimals, NOT 1e12."""
    scale = Decimal(10) ** Decimal(decimals)
    return int((amount * scale).to_integral_value(ROUND_DOWN))


def mojos_to_cat(mojos: int, decimals: int) -> Decimal:
    """Convert mojos to CAT amount."""
    scale = Decimal(10) ** Decimal(decimals)
    return Decimal(mojos) / scale


# ---------------------------------------------------------------------------
# Offer Manager
# ---------------------------------------------------------------------------
class OfferManager:
    """Manages the full lifecycle of market-making offers.

    Responsibilities:
    - Create offer ladders (buy and sell sides)
    - Track which offers we created vs filled vs cancelled
    - Handle requoting when price moves beyond threshold
    - Manage offer expiry (staggered expiry to avoid cascades)
    - Queue offers for Dexie posting
    """

    @staticmethod
    def plan_staged_refresh(
        targets: List[Dict[str, Any]],
        *,
        overlap_capacity: int,
        batch_size: int,
        operator_mass_cancel: bool = False,
    ) -> RefreshPlan:
        """Return the pure Task 11 plan before any requote wallet effect.

        Capacity is deliberately supplied by the caller's authoritative
        snapshot.  This manager boundary must not guess or repurpose Task 12
        capacity accounting.
        """

        return plan_refresh(
            targets,
            overlap_capacity=overlap_capacity,
            batch_size=batch_size,
            operator_mass_cancel=operator_mass_cancel,
        )

    @staticmethod
    def _trip_refresh_lineage_latch(
        *,
        operation_id: str,
        parent: Optional[Dict[str, Any]] = None,
        cohort_trade_ids: Optional[List[str]] = None,
        side: Optional[str] = None,
        malformed_snapshot_entries: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Latch any malformed refresh boundary before another mutation."""

        wallet_hash = parent.get("wallet_fingerprint_hash") if parent else None
        network = parent.get("network") if parent else None
        if not isinstance(wallet_hash, str) or not isinstance(network, str):
            lease = database.get_runtime_mutation_lease()
            wallet_hash = lease.get("wallet_fingerprint_hash")
            network = lease.get("network")
        if (
            not isinstance(wallet_hash, str)
            or not wallet_hash
            or not isinstance(network, str)
            or not network
        ):
            raise RuntimeError("refresh lineage cannot bind the runtime safety latch")
        cohort = cohort_trade_ids or ([parent.get("sage_trade_id")] if parent else [])
        malformed = malformed_snapshot_entries or []
        if not cohort and not malformed:
            raise RuntimeError("refresh lineage blocker lacks exact snapshot authority")
        incident_id = database.refresh_lineage_blocker_operation_id(
            reason_code=operation_id,
            cohort_trade_ids=cohort,
            malformed_snapshot_entries=malformed,
        )
        database.record_refresh_lineage_blocker(
            operation_id=incident_id,
            wallet_fingerprint_hash=wallet_hash,
            network=network,
            side=side or (parent.get("side") if parent else ""),
            asset_id=parent.get("asset_id") if parent else cfg.CAT_ASSET_ID,
            cohort_trade_ids=cohort,
            malformed_snapshot_entries=malformed,
            reason_code=operation_id,
        )

    def _resume_pending_refresh_lineage_completions(self, side: str) -> Optional[str]:
        """Commit one proof-complete lineage even when its parent left open offers.

        The query and completion check are durable/read-only until the final
        database commit; neither branch performs a wallet or network effect.
        """

        parent_ids = database.get_pending_refresh_lineage_parent_ids(
            asset_id=cfg.CAT_ASSET_ID, side=side, limit=64
        )
        for parent_id in parent_ids:
            completion = database.refresh_lineage_completion(
                parent_id, require_visible=True
            )
            if completion.get("complete"):
                committed = database.commit_refresh_lineage_completion(parent_id)
                if committed.get("committed"):
                    return "awaiting_terminal_projection"
                if committed.get("reason") in {
                    "invalid_lineage",
                    "parent_missing",
                    "parent_identity_missing",
                }:
                    parent = database.get_offer_intent(parent_id)
                    self._trip_refresh_lineage_latch(
                        operation_id=f"refresh-lineage:{parent_id}:resume",
                        parent=parent,
                    )
                    return "lineage_resume_inconsistent"
                return "awaiting_task8_task9"
            if completion.get("reason") in {
                "invalid_lineage",
                "parent_missing",
                "parent_identity_missing",
            }:
                parent = database.get_offer_intent(parent_id)
                self._trip_refresh_lineage_latch(
                    operation_id=f"refresh-lineage:{parent_id}:resume",
                    parent=parent,
                )
                return "lineage_resume_inconsistent"
        return None

    def _collect_staged_refresh_parents(
        self, open_offers: List[Dict[str, Any]], side: str
    ) -> tuple[Dict[str, tuple[Dict[str, Any], Dict[str, Any], int]], Optional[str]]:
        """Validate a complete cohort before resuming one durable lineage edge.

        The first phase contains no wallet effect: it classifies every selected
        row before a Task 8 cancellation may be invoked.  This makes a later
        malformed row fail closed even when an earlier parent is cancel-ready.
        """

        candidates: Dict[str, tuple[Dict[str, Any], Dict[str, Any], int]] = {}
        resume_actions: List[tuple[str, Dict[str, Any], str]] = []
        issues: List[tuple[str, Optional[Dict[str, Any]]]] = []
        canonical_trade_ids: Dict[int, str] = {}
        malformed_snapshot_entries = []
        for index, offer in enumerate(open_offers):
            candidate = offer.get("trade_id") if type(offer) is dict else None
            canonical = self._canonical_sage_trade_id(candidate)
            if canonical is None:
                malformed_snapshot_entries.append(
                    self._malformed_refresh_identity_entry(index, candidate)
                )
            else:
                canonical_trade_ids[index] = canonical
        cohort_trade_ids = list(canonical_trade_ids.values())
        slot_prefix = f"ladder:{cfg.CAT_ASSET_ID}:{side}:"
        for index, offer in enumerate(open_offers):
            trade_id = canonical_trade_ids.get(index)
            intent = (
                database.get_offer_intent_by_trade_id(trade_id)
                if trade_id is not None
                else None
            )
            if type(intent) is not dict:
                issues.append(("registry_parent_missing", None))
                continue
            if intent.get("asset_id") != cfg.CAT_ASSET_ID or intent.get("side") != side:
                issues.append(("registry_parent_conflict", intent))
                continue
            if intent.get("child_intent_id"):
                completion = database.refresh_lineage_completion(
                    intent["intent_id"], require_visible=True
                )
                if completion.get("complete"):
                    resume_actions.append(
                        ("commit", intent, "awaiting_terminal_projection")
                    )
                    continue
                reason = completion.get("reason")
                if reason in {
                    "invalid_lineage",
                    "parent_missing",
                    "parent_identity_missing",
                }:
                    issues.append(("lineage_resume_inconsistent", intent))
                    continue
                eligibility = database.refresh_parent_cancel_eligibility(
                    intent["intent_id"], require_visible=True
                )
                if eligibility.get("eligible"):
                    events = database.get_offer_operation_events(f"cancel:{trade_id}")
                    if events:
                        latest = events[-1]
                        if int(latest.get("blocks_mutation") or 0) == 1 or (
                            latest.get("phase") == "RECONCILED"
                            and latest.get("outcome") == CANCEL_CONFIRMED
                        ):
                            resume_actions.append(
                                ("wait", intent, "awaiting_task8_task9")
                            )
                        else:
                            resume_actions.append(
                                ("cancel", intent, "awaiting_task8_task9")
                            )
                    else:
                        resume_actions.append(
                            ("cancel", intent, "awaiting_task8_task9")
                        )
                    continue
                if eligibility.get("reason") in {"invalid_lineage", "parent_missing"}:
                    issues.append(("lineage_resume_inconsistent", intent))
                    continue
                resume_actions.append(
                    ("wait", intent, "awaiting_visibility_or_terminal_proof")
                )
                continue
            if intent.get("parent_intent_id"):
                if (
                    database.get_refresh_lineage_commit_for_child(intent["intent_id"])
                    is None
                ):
                    resume_actions.append(
                        ("wait", intent, "awaiting_parent_completion")
                    )
                    continue
            if intent.get("lifecycle_state") not in {"created", "visible"}:
                issues.append(("registry_parent_conflict", intent))
                continue
            slot_key = intent.get("slot_key")
            if not isinstance(slot_key, str) or not slot_key.startswith(slot_prefix):
                issues.append(("registry_parent_conflict", intent))
                continue
            try:
                slot = int(slot_key[len(slot_prefix) :])
            except ValueError:
                issues.append(("registry_parent_conflict", intent))
                continue
            if intent["intent_id"] in candidates:
                issues.append(("registry_parent_coverage_incomplete", intent))
                continue
            candidates[intent["intent_id"]] = (offer, intent, slot)
        slots = [slot for _offer, _intent, slot in candidates.values()]
        if len(cohort_trade_ids) != len(open_offers) or len(cohort_trade_ids) != len(
            set(cohort_trade_ids)
        ):
            issues.append(("registry_parent_coverage_incomplete", None))
        if len(slots) != len(set(slots)):
            issues.append(("registry_parent_coverage_incomplete", None))
        if issues:
            pause, parent = issues[0]
            operation_id = f"refresh-lineage:{side}:coverage"
            if parent is not None:
                operation_id = (
                    f"refresh-lineage:{parent['intent_id']}:resume"
                    if pause == "lineage_resume_inconsistent"
                    else f"refresh-lineage:{parent['intent_id']}:coverage"
                )
            self._trip_refresh_lineage_latch(
                operation_id=operation_id,
                parent=parent,
                cohort_trade_ids=cohort_trade_ids,
                side=side,
                malformed_snapshot_entries=malformed_snapshot_entries,
            )
            return {}, pause
        # Phase two begins only after the whole selected/open cohort passed
        # exact identity, state, and slot validation.  Task 8 remains the
        # only cancellation authority and owns its wallet effect.
        for action, parent, pause in sorted(
            resume_actions, key=lambda item: item[1]["intent_id"]
        ):
            if action == "wait":
                return {}, pause
            if action == "commit":
                completion = database.commit_refresh_lineage_completion(
                    parent["intent_id"]
                )
                if completion.get("committed"):
                    return {}, pause
                if completion.get("reason") in {
                    "invalid_lineage",
                    "parent_missing",
                    "parent_identity_missing",
                }:
                    self._trip_refresh_lineage_latch(
                        operation_id=f"refresh-lineage:{side}:coverage",
                        parent=parent,
                        cohort_trade_ids=cohort_trade_ids,
                        side=side,
                    )
                    return {}, "lineage_resume_inconsistent"
                return {}, "awaiting_task8_task9"
            # Re-read Task 8 eligibility immediately before its cancellation
            # boundary: the validation snapshot never grants mutation rights.
            eligibility = database.refresh_parent_cancel_eligibility(
                parent["intent_id"], require_visible=True
            )
            if not eligibility.get("eligible"):
                return {}, "awaiting_visibility_or_terminal_proof"
            trade_id = parent.get("sage_trade_id")
            events = database.get_offer_operation_events(f"cancel:{trade_id}")
            if events:
                latest = events[-1]
                if int(latest.get("blocks_mutation") or 0) == 1 or (
                    latest.get("phase") == "RECONCILED"
                    and latest.get("outcome") == CANCEL_CONFIRMED
                ):
                    return {}, "awaiting_task8_task9"
            self.cancel_offers(
                [trade_id], reason="refresh_lineage", skip_confirmation=False
            )
            return {}, "awaiting_task8_task9"
        return candidates, None

    def __init__(self):
        # Track which offers the bot cancelled (vs externally filled).
        # Used by fill_tracker to distinguish own-cancel from counterparty fill.
        self._bot_cancelled_ids: set = set()

        # Cache of offer details for fill recording
        self._offer_details_cache: Dict[str, Dict] = {}

        # Last requote time per side (cooldown enforcement)
        self._last_requote_time: Dict[str, float] = {"buy": 0, "sell": 0}

        # Lock for thread safety during offer operations
        self._lock = threading.Lock()

        # Sage creation authority requires strictly newer identity evidence for
        # every continuation. Parallel ladder workers can observe identities in
        # one order and enter the authority gate in another, causing valid
        # creates to fail closed as stale. Keep the complete journal + wallet
        # effect on one ordered lane per manager while leaving ladder planning
        # and result processing parallel.
        self._sage_creation_authority_lock = threading.Lock()

        # ----- V1 Parity: Retry failed cancels -----
        # Dict of trade_id -> {"attempts": int, "first_failed": float}
        self._pending_cancel_retries: Dict[str, Dict] = {}
        self._max_cancel_retries: int = 5
        self._cancel_retry_backoff_seconds: int = 30
        # A retry that submits a Sage cancellation must remain the sole
        # mutation owner while Task 9 proves the resulting spend.  The API
        # safety callback reads this exact operation ID so it can defer its
        # stop notification without ever reopening the mutation gate.
        self._cancel_settlement_lock = threading.Lock()
        self._cancel_settlement_operation_id: Optional[str] = None

        # ----- V1 Parity: Recently created offers (anti-overcount) -----
        # Dict of trade_id -> creation_time — offers created this cycle
        # that may not be visible in wallet sync yet
        self._recently_created: Dict[str, float] = {}
        self._recently_created_ttl: int = (
            600  # 10 minutes — must outlast Sage sync delays
        )

        # ----- Stop signal -----
        # Set by bot_loop.stop() to interrupt long-running ladder creation.
        # Without this, create_ladder's for-loop runs to completion even
        # after stop() is called, because the 10s join timeout expires
        # before the loop finishes. GUI shows "stopped" but the thread
        # keeps creating offers for minutes.
        self._stop_requested: bool = False

        # ----- AMM Monitor reference -----
        # Injected by bot_loop after both modules are instantiated.
        # Used to call check_amm_buffer() before posting each offer slot
        # so we never post inside TibetSwap's arb zone.
        self.amm_monitor = None

        # ----- Dexie Manager reference -----
        # Injected by bot_loop after instantiation.
        # Used to purge cancelled offer IDs from the Dexie post queue so
        # they don't generate spurious "Invalid Offer" 400 errors on flush.
        self.dexie_manager = None
        self.splash_manager = None

        # ----- Fee coin pool reference -----
        # Injected by bot_loop: self.offer_manager._fee_pool = self.coin_manager.fee_pool
        # Each create/cancel reserves a dedicated fee coin from this pool
        # so concurrent operations don't fight over the same fee coin.
        self._fee_pool = None

        # ----- Shared in-flight coin tracking -----
        # Coins currently selected for offer creation (not yet confirmed).
        # Checked by both main loop and sniper under _lock to prevent
        # double-selecting the same coin in concurrent create paths.
        self._inflight_coin_ids: set = set()

        # ----- Per-cycle used coin exclusion -----
        # Coins successfully used by any offer creation within the current
        # bot cycle.  Unlike _inflight_coin_ids (released after each RPC
        # call) this set persists for the entire cycle so that a second
        # create_ladder call (e.g. the sell side after the buy side) will
        # not re-select a coin that is still pending on-chain confirmation.
        # Cleared at the start of every cycle via clear_cycle_coins().
        self._cycle_used_coin_ids: set = set()

        # Test-only crash boundary hook. Production leaves this unset; the
        # immutable intent argument lets tests simulate process loss without
        # weakening or branching the durable state machine.
        self._offer_creation_crash_hook = None
        self._offer_cancel_crash_hook = None

        # ----- Fix F: Slot suspension for coin exhaustion self-heal -----
        # When a specific slot fails to get a unique coin 3 consecutive times,
        # suspend it to prevent infinite retry loops. Slots are unsuspended
        # when coins become available again.
        # Key: f"{side}_{slot}" → consecutive failure count
        self._slot_fail_counts: Dict[str, int] = {}
        # Set of f"{side}_{slot}" keys that are currently suspended
        self._suspended_slots: set = set()
        self._slot_suspend_threshold: int = 3  # consecutive failures before suspension
        # Per-slot warn cooldown: only emit slot_suspended log once every 10 min
        # per slot to prevent repeated log entries when the suspend/unsuspend
        # cycle triggers rapidly during sustained coin exhaustion.
        self._slot_warned_at: Dict[str, float] = {}
        self._slot_warn_cooldown: float = 600.0  # seconds

        # Position-hard-guard log cooldown — when net position exceeds the hard
        # limit, every ladder attempt emits the same block error. During a
        # sustained imbalance the logs flooded with 4 identical ERROR lines per
        # minute. Cooldown to once per 60s per side so the block reason stays
        # visible without drowning other signals.
        self._position_guard_logged_at: Dict[str, float] = {}
        self._position_guard_log_cooldown: float = 60.0  # seconds
        self._position_guard_paused: Dict[str, Dict[str, Any]] = {}
        self._position_guard_pause_secs: float = self._position_guard_log_cooldown

        # ----- Wallet sync fail-closed cache -----
        # When Sage get_offers times out, we must not treat that as an empty
        # book. Keep the last successful classified view so callers can fail
        # closed and avoid rebuilding on top of still-live offers.
        self._wallet_sync_cache: Dict[str, List[Dict]] = {
            "buy": [],
            "sell": [],
            "closed": [],
        }
        self._wallet_sync_meta: Dict[str, Any] = {
            "fresh": True,
            "using_cache": False,
            "consecutive_failures": 0,
            "last_error": "",
            "last_success_at": 0.0,
            "last_failure_at": 0.0,
            "cache_size": 0,
            "last_suspicious_empty_log_key": "",
            "suspicious_empty_suppressed": 0,
        }
        self._expected_empty_wallet_book: Dict[str, Any] = {
            "until": 0.0,
            "reason": "",
        }

    # -------------------------------------------------------------------
    # Per-cycle coin exclusion
    # -------------------------------------------------------------------

    def clear_cycle_coins(self):
        """Reset the per-cycle used-coin set.

        Called by bot_loop at the start of every trading cycle so that
        coins confirmed on-chain since the last cycle become available
        again, while coins used earlier *within* the same cycle stay
        excluded until the cycle boundary.
        """
        self._cycle_used_coin_ids.clear()

    def get_position_guard_pause(self, side: Optional[str] = None) -> Dict[str, Any]:
        """Return current position-guard pauses, pruning expired entries."""
        now = time.time()
        expired = []
        for key, item in list(self._position_guard_paused.items()):
            try:
                expires_at = float((item or {}).get("expires_at", 0.0) or 0.0)
            except Exception:
                expires_at = 0.0
            if expires_at and expires_at <= now:
                expired.append(key)
        for key in expired:
            self._position_guard_paused.pop(key, None)

        if side is not None:
            return dict(self._position_guard_paused.get(str(side).lower()) or {})
        return {key: dict(val) for key, val in self._position_guard_paused.items()}

    def check_position_guard(
        self,
        side: str,
        mid_price: Decimal,
        num: int,
        slot_start: int,
        total_slots: Optional[int],
        slot_sequence: Optional[List[int]],
        risk_manager,
        default_size: Optional[Decimal],
        cat_asset_id: Optional[str] = None,
        log_block: bool = False,
        record_pause: bool = False,
    ) -> Dict[str, Any]:
        """Check whether creating a ladder batch would worsen inventory risk.

        Returns a structured result so callers can distinguish a deliberate
        position pause from a wallet/create failure.
        """
        side = str(side or "").lower()
        result: Dict[str, Any] = {
            "blocked": False,
            "side": side,
        }
        if risk_manager is None:
            return result

        try:
            max_pos_xch = Decimal(str(getattr(cfg, "MAX_POSITION_XCH", "5") or "5"))
            if max_pos_xch <= 0:
                if record_pause:
                    self._position_guard_paused.pop(side, None)
                return result
            hard_pos_xch = max_pos_xch * Decimal("1.1")
            net_pos_cat = Decimal(str(risk_manager._net_position_cat))
            net_pos_xch = (
                abs(net_pos_cat) * mid_price if mid_price > 0 else Decimal("0")
            )
            total_slots = total_slots if total_slots is not None else num
            projected_increase_xch = self._estimate_ladder_worst_case_xch(
                side=side,
                num=num,
                slot_start=slot_start,
                total_slots=total_slots,
                slot_sequence=slot_sequence,
                risk_manager=risk_manager,
                default_size=default_size,
            )

            # Legacy/self-heal path: if the configured max position is lower
            # than a fresh designed ladder while position is effectively flat,
            # raise the session hard limit so an old config does not brick the
            # bot. Smart Settings persists a consistent value for new configs.
            if (
                projected_increase_xch > hard_pos_xch
                and net_pos_xch < max_pos_xch * Decimal("0.05")
            ):
                healed = projected_increase_xch * Decimal("1.05")
                if healed > hard_pos_xch:
                    if not getattr(self, "_max_pos_warned", False):
                        log_event(
                            "warning",
                            "max_position_auto_raised",
                            f"MAX_POSITION_XCH={max_pos_xch} XCH is inconsistent "
                            f"with the configured ladder "
                            f"(side={side}, num={num}, designed worst-case "
                            f"{projected_increase_xch:.4f} XCH > hard limit "
                            f"{hard_pos_xch:.4f} XCH). Session hard limit "
                            f"auto-raised to {healed:.4f} XCH so the bot "
                            f"can operate. Re-run Smart Settings to persist "
                            f"a consistent MAX_POSITION_XCH.",
                        )
                        self._max_pos_warned = True
                    hard_pos_xch = healed

            same_side_open_xch = Decimal("0")
            try:
                existing = get_open_offers(
                    side=side, cat_asset_id=cat_asset_id or cfg.CAT_ASSET_ID
                )
                for offer in existing or []:
                    size_raw = offer.get("size_xch") or offer.get("size_xch_mojos")
                    if size_raw is None:
                        continue
                    try:
                        if isinstance(size_raw, int) and size_raw > 1_000_000_000:
                            same_side_open_xch += Decimal(size_raw) / Decimal(
                                "1000000000000"
                            )
                        else:
                            same_side_open_xch += Decimal(str(size_raw))
                    except Exception:
                        continue
            except Exception:
                same_side_open_xch = Decimal("0")

            net_new_exposure_xch = projected_increase_xch - same_side_open_xch
            if net_new_exposure_xch < 0:
                net_new_exposure_xch = Decimal("0")

            add_long_dir = (side == "buy" and net_pos_cat >= 0) or (
                side == "sell" and net_pos_cat <= 0
            )
            projected_position_xch = net_pos_xch + net_new_exposure_xch
            blocked = bool(add_long_dir and projected_position_xch > hard_pos_xch)
            if not blocked:
                if record_pause:
                    self._position_guard_paused.pop(side, None)
                return result

            opposite_side = "buy" if side == "sell" else "sell"
            result.update(
                {
                    "blocked": True,
                    "side": side,
                    "opposite_side": opposite_side,
                    "num": int(num),
                    "default_size_xch": str(default_size or Decimal("0")),
                    "net_position_cat": str(net_pos_cat),
                    "current_position_xch": str(net_pos_xch),
                    "full_ladder_value_xch": str(projected_increase_xch),
                    "same_side_open_xch": str(same_side_open_xch),
                    "net_new_exposure_xch": str(net_new_exposure_xch),
                    "projected_position_xch": str(projected_position_xch),
                    "hard_limit_xch": str(hard_pos_xch),
                    "max_position_xch": str(max_pos_xch),
                    "expires_at": time.time() + self._position_guard_pause_secs,
                }
            )
            if record_pause:
                self._position_guard_paused[side] = dict(result)

            if log_block:
                now = time.time()
                last = self._position_guard_logged_at.get(side, 0.0)
                if (now - last) >= self._position_guard_log_cooldown:
                    self._position_guard_logged_at[side] = now
                    log_event(
                        "warning",
                        "position_hard_guard_blocked",
                        f"Position guard paused {side} ladder: current position "
                        f"{net_pos_xch:.4f} XCH (net {net_pos_cat:+.0f} CAT). "
                        f"Creating this batch would add {net_new_exposure_xch:.4f} XCH "
                        f"of same-side exposure and project {projected_position_xch:.4f} XCH "
                        f"above the hard limit {hard_pos_xch:.4f} XCH "
                        f"(110% of MAX_POSITION_XCH={max_pos_xch}). "
                        f"{opposite_side.capitalize()} offers remain live to rebalance; "
                        "wait for them to fill or adjust Max Position in Settings "
                        "if you accept the risk.",
                        data=result,
                    )
            return result
        except Exception as exc:
            log_event(
                "debug",
                "position_hard_guard_failed",
                f"Position rebalance guard check failed (proceeding): {exc}",
            )
            return result

    # -------------------------------------------------------------------
    # Fix F: Slot suspension management
    # -------------------------------------------------------------------

    def record_slot_coin_failure(self, side: str, slot: int):
        """Record a coin preselection failure for a slot.

        After _slot_suspend_threshold consecutive failures, the slot is
        suspended to prevent infinite retry loops in recovery mode.
        Suspended slots auto-clear after 20 cycles (self-heal) so the
        ladder doesn't permanently degrade if the topup worker restocks.
        """
        key = f"{side}_{slot}"
        count = self._slot_fail_counts.get(key, 0) + 1
        self._slot_fail_counts[key] = count
        if count >= self._slot_suspend_threshold and key not in self._suspended_slots:
            self._suspended_slots.add(key)
            self._slot_suspended_at = getattr(self, "_slot_suspended_at", {})
            self._slot_suspended_at[key] = time.time()
            # Rate-limit the warning to once per cooldown window per slot.
            # During sustained coin exhaustion the suspend→auto-clear→suspend
            # cycle fires every ~20 cycles; without this guard the same slot
            # generates a new WARNING every ~15 minutes indefinitely.
            _now = time.time()
            _last_warn = self._slot_warned_at.get(key, 0.0)
            if (_now - _last_warn) >= self._slot_warn_cooldown:
                self._slot_warned_at[key] = _now
                log_event(
                    "info",
                    "slot_suspended",
                    f"Slot {side} #{slot} is waiting for a matching tier coin "
                    f"after {count} selection misses — will retry when coins are available",
                )
        # F63: auto-clear after 20 cycles (~10 minutes at typical loop speed).
        # This prevents permanent ladder degradation if unsuspend_slots
        # never fires or coins are replenished via topup without triggering
        # the explicit unsuspend check.
        if count > self._slot_suspend_threshold + 20:
            self._slot_fail_counts[key] = 0
            self._suspended_slots.discard(key)
            log_event(
                "info",
                "slot_suspension_expired",
                f"Slot {side} #{slot} suspension expired after {count} "
                f"cycles — re-enabling for next attempt",
            )

    def clear_slot_failure(self, side: str, slot: int):
        """Clear the failure counter for a slot after successful creation."""
        key = f"{side}_{slot}"
        self._slot_fail_counts.pop(key, None)
        self._suspended_slots.discard(key)

    def is_slot_suspended(self, side: str, slot: int) -> bool:
        """Check if a slot is currently suspended due to coin exhaustion."""
        return f"{side}_{slot}" in self._suspended_slots

    def get_suspended_slot_count(self, side: str) -> int:
        """Count how many slots are suspended for a given side."""
        prefix = f"{side}_"
        return sum(1 for k in self._suspended_slots if k.startswith(prefix))

    def unsuspend_slots_if_coins_available(self, side: str):
        """Unsuspend slots for a side if spare tier coins have become available.

        Called by bot_loop at the start of each cycle to check whether
        previously exhausted coin pools have been replenished.

        Uses the DB coin tracking (which knows tier designations) rather than
        the raw wallet RPC to avoid counting fee/sniper/reserve coins that
        cannot be used for offer creation — those would cause an endless
        suspend → unsuspend → fail cycle.
        """
        prefix = f"{side}_"
        suspended_for_side = [k for k in self._suspended_slots if k.startswith(prefix)]
        if not suspended_for_side:
            return

        wallet_type = "cat" if side == "sell" else "xch"
        try:
            # Count only tier-designated trading coins (excludes fee, sniper,
            # reserve, dust and unknown coins which cannot fill offer slots).
            from database import get_free_coins

            db_free = get_free_coins(wallet_type)
            _TRADING_DESIGS = {"tier_spare", "tier_active"}
            _SKIP_TIERS = {"none", "sniper", "reserve", "fee"}
            usable_by_tier: Dict[str, int] = {}
            usable_total = 0
            for coin in db_free:
                designation = str(coin.get("designation", "") or "")
                tier = str(coin.get("assigned_tier", "none") or "none").lower()
                if designation not in _TRADING_DESIGS or tier in _SKIP_TIERS:
                    continue
                usable_total += 1
                usable_by_tier[tier] = usable_by_tier.get(tier, 0) + 1
            if usable_total <= 0:
                return

            slots_to_unsuspend: List[str] = []
            if not cfg.TIER_ENABLED:
                slots_to_unsuspend = suspended_for_side[:usable_total]
            else:
                total_slots = int(
                    getattr(
                        cfg,
                        "MAX_ACTIVE_BUY_OFFERS"
                        if side == "buy"
                        else "MAX_ACTIVE_SELL_OFFERS",
                        0,
                    )
                    or 0
                )
                if total_slots <= 0:
                    prefix_cfg = "BUY_" if side == "buy" else "SELL_"
                    total_slots = sum(
                        int(
                            getattr(cfg, f"{prefix_cfg}{tier.upper()}_TIER_COUNT", 0)
                            or 0
                        )
                        for tier in ("inner", "mid", "outer", "extreme")
                    )
                try:
                    from coin_manager import coin_size_tier_for_slot_position
                except Exception:

                    def coin_size_tier_for_slot_position(tier, side=None):
                        del side
                        return tier

                def _slot_index(key: str) -> int:
                    try:
                        return int(str(key).rsplit("_", 1)[1])
                    except Exception:
                        return 1_000_000

                for key in sorted(suspended_for_side, key=_slot_index):
                    slot = _slot_index(key)
                    if slot >= 1_000_000:
                        continue
                    position_tier = self._classify_tier(slot, total_slots, side=side)
                    coin_tier = str(
                        coin_size_tier_for_slot_position(position_tier, side=side)
                    ).lower()
                    if usable_by_tier.get(coin_tier, 0) <= 0:
                        continue
                    usable_by_tier[coin_tier] -= 1
                    slots_to_unsuspend.append(key)

            if not slots_to_unsuspend:
                return
            suspended_for_side = slots_to_unsuspend
            spare_count = len(slots_to_unsuspend)
            if usable_total > 0:
                for key in suspended_for_side:
                    self._suspended_slots.discard(key)
                    self._slot_fail_counts.pop(key, None)
                log_event(
                    "info",
                    "slots_unsuspended",
                    f"Unsuspended {len(suspended_for_side)} {side} slots — "
                    f"{spare_count} matching spare tier coin(s) now available",
                )
        except Exception as e:
            log_event(
                "debug",
                "slot_unsuspend_check_failed",
                f"Could not check coins for slot unsuspension: {e}",
            )

    # -------------------------------------------------------------------
    # Coin ID Extraction (for before/after snapshot)
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_coin_id_set(rpc_result) -> set:
        """Extract a set of unique coin IDs from a get_spendable_coins RPC response.

        The RPC returns {"success": true, "confirmed_records": [...]}.
        Each record has a nested "coin" dict with parent_coin_info, puzzle_hash, amount.

        IMPORTANT: The wallet does NOT return a "name" field on this Chia version.
        Multiple coins can share the same parent_coin_info (from splits).
        The unique coin ID must be computed as SHA256(parent + puzzle_hash + amount).
        Uses _coin_id_from_record from coin_manager.py which handles this correctly.
        """
        from coin_manager import _coin_id_from_record

        ids = set()
        if not rpc_result or not isinstance(rpc_result, dict):
            return ids
        records = rpc_result.get("confirmed_records") or rpc_result.get("records") or []
        for r in records:
            cid = _coin_id_from_record(r)
            if cid:
                ids.add(cid)
        return ids

    # -------------------------------------------------------------------
    # Coin Selection (V3 — deterministic coin locking via Sage PR#761)
    # -------------------------------------------------------------------

    @staticmethod
    def _coin_designation_priority(
        designation: str, assigned_tier: str, preferred_tier: str = None
    ) -> int:
        """Sort priority for designated free coins."""
        desig = (designation or "unknown").lower()
        tier = (assigned_tier or "none").lower()
        pref = (preferred_tier or "").lower()

        if pref:
            if desig == "tier_spare" and tier == pref:
                return 0
            if desig == "tier_active" and tier == pref:
                return 1
            if desig == "tier_spare":
                return 2
            if desig == "tier_active":
                return 3
            if desig == "dust":
                return 4
            return 5

        if desig == "tier_spare":
            return 0
        if desig == "tier_active":
            return 1
        if desig == "dust":
            return 2
        return 3

    def _select_coin_for_offer(
        self,
        wallet_id: int,
        amount_mojos: int,
        used_coins: set = None,
        preferred_tier: str = None,
        strict_preferred_tier: bool = False,
        spendable_records: List[Dict] = None,
        exclude_coin_ids: set = None,
        max_amount_mojos: int = None,
        tier_sizes_mojos: Optional[Dict[str, int]] = None,
    ) -> Optional[str]:
        """Pre-select the best coin for an offer before creating it.

        Instead of letting the wallet auto-select (and then polling to
        find out which coin it picked), we choose the coin ourselves
        and pass it via coin_ids to make_offer. This gives us:
        - Deterministic coin locking (we know exactly which coin)
        - No polling delay (~45x faster batch creation)
        - No coin reuse risk (we track used coins in-batch)

        Strategy: closest-fit — pick the smallest coin that's large enough.
        This minimises waste (avoids using a 10 XCH coin for a 0.1 XCH offer).

        Args:
            wallet_id: Which wallet to query (1=XCH, CAT wallet ID for CATs)
            amount_mojos: How much this offer needs to spend (in mojos)
            used_coins: Set of coin_ids already used in this batch (reuse guard)
            max_amount_mojos: Upper bound on coin size (exclusive). When set,
                coins larger than this are rejected even as fallback. This
                prevents a 5 XCH coin being selected for a 0.634 XCH offer in
                exact_tier_spend_mode — locking 87% of the coin as change.
                When no coin fits within [amount_mojos, max_amount_mojos],
                returns None so the slot suspends and triggers a topup.
            tier_sizes_mojos: Optional mapping of tier name → mojos used to
                strict-validate candidate coins via
                :func:`coin_classifier.classify_coin`. When provided AND
                ``preferred_tier`` is set, coins classified as a MISFIT for
                that tier (under the SSOT 0.98/1.5 bounds) are rejected —
                even if they satisfy the raw amount_mojos / max_amount_mojos
                window. This prevents the 2026-04-17 regression where the
                offer selector happily accepted a 23.4k CAT coin for an
                "inner" slot even though strict bounds classified it as a
                misfit, producing a ragged ladder shape on Dexie.
                Leave None to preserve legacy behaviour.

        Returns:
            coin_id string if a suitable coin is found, None otherwise.
            When None is returned, the caller should fall back to polling.
        """
        from coin_manager import _coin_id_from_record

        if used_coins is None:
            used_coins = set()

        # SSOT misfit rejection — precompute once so it's cheap to apply per
        # candidate. Only active when the caller supplied both
        # preferred_tier and tier_sizes_mojos. See the F70 docstring above
        # for why this exists.
        #
        # Design note: we only reject TRUE misfits here (coins that fit no
        # configured tier under the 0.98/1.5 bounds). Reserve and dust coins
        # are NOT rejected by this check — other pre-existing filters
        # (designation == "reserve", size floor vs amount_mojos) handle
        # those categories. Narrowing the check to misfits only keeps F70
        # targeted at the ladder-shape regression without breaking legacy
        # callers that use oversize coins for tier-agnostic fallback paths.
        _reject_misfit = bool(preferred_tier and tier_sizes_mojos)
        if _reject_misfit:
            from coin_classifier import classify_coin, CoinDesignation

            _pref_lower = (preferred_tier or "").lower()

            def _coin_fits_preferred_tier(coin_amount_mojos: int) -> bool:
                """Returns True when the coin is usable for ``preferred_tier``.

                Rules, in order:
                  1. Misfits and dust are always rejected (F70 invariant).
                  2. Reserve-sized coins pass here; other selector filters
                     (``max_amount_mojos``, designation == "reserve") decide
                     whether they're actually usable for this slot.
                  3. Tier-fit coins must match ``preferred_tier`` EXACTLY —
                     this is the 2026-04-18 slot-21/23 taper fix. Before
                     this line, a mid-sized coin could back an outer-
                     position slot (reverse-buy: outer position ↔ mid size)
                     simply because it wasn't a misfit. Now we require the
                     classifier's best_tier to equal the caller's preferred
                     tier so wrong-sized coins fail the selector cleanly
                     (→ slot skip → topup backfill) instead of landing on
                     the ladder as a taper violation.
                """
                cls = classify_coin(coin_amount_mojos, tier_sizes_mojos)
                if cls.is_misfit:
                    return False
                # Dust and reserve coins pass F70 here — other selector
                # filters (coin_amount < amount_mojos, max_amount_mojos,
                # designation == "reserve") decide whether they're usable.
                # We don't want to duplicate those rejections here.
                if cls.designation != CoinDesignation.TIER_SPARE:
                    return True
                # For tier-spare coins we require an EXACT match with
                # preferred_tier. This is the 2026-04-18 taper fix: a mid-
                # sized coin was backing an outer-position slot under
                # reverse-buy (outer position ↔ mid size) because it wasn't
                # a misfit. Requiring best_tier == preferred_tier forces
                # the selector to return None when no correctly-sized coin
                # is available, which triggers clean slot-skip → topup
                # backfill instead of building a ragged ladder.
                best = (cls.best_tier or "").lower() if cls.best_tier else ""
                return bool(best) and best == _pref_lower
        else:
            _coin_fits_preferred_tier = None  # type: ignore

        try:
            if spendable_records is None:
                rpc_result = get_exact_spendable_coins_rpc(wallet_id)
                if not rpc_result or not rpc_result.get("success"):
                    return None
                records = (
                    rpc_result.get("confirmed_records")
                    or rpc_result.get("records")
                    or []
                )
            else:
                records = spendable_records
            wallet_type = "xch" if wallet_id == cfg.WALLET_ID_XCH else "cat"

            spendable_amounts = {}
            fallback_candidates = []
            for r in records:
                coin_id = _coin_id_from_record(r)
                if not coin_id:
                    continue

                coin_id = coin_id.lower()
                coin_data = r.get("coin", {})
                coin_amount = int(coin_data.get("amount", 0))
                spendable_amounts[coin_id] = coin_amount

                if coin_id in used_coins or coin_amount < amount_mojos:
                    continue
                if coin_id in self._cycle_used_coin_ids:
                    continue
                if exclude_coin_ids and coin_id in exclude_coin_ids:
                    continue
                # Reject coins that are too large when a size cap is set.
                # A 5 XCH coin for a 0.634 XCH offer locks 87% as change and
                # creates a cascading wrong-size cycle. Fail cleanly instead.
                if max_amount_mojos is not None and coin_amount > max_amount_mojos:
                    continue
                # F70 SSOT misfit guard: reject coins that the unified
                # classifier says don't fit the preferred tier. Without this,
                # a 23.4k-CAT change coin from a past fill could be used to
                # back an "inner" slot even though it's 12% below inner's
                # strict floor — producing ragged ladder shape like the
                # 2026-04-17 incident.
                if _coin_fits_preferred_tier is not None:
                    if not _coin_fits_preferred_tier(coin_amount):
                        continue

                fallback_candidates.append(
                    (coin_amount - amount_mojos, coin_id, coin_amount)
                )

            pref = (preferred_tier or "").lower()
            strict_pref = bool(pref and strict_preferred_tier)
            db_free_coins = []
            reserve_ids = set()
            try:
                from database import get_free_coins, get_reserve_coins

                db_free_coins = get_free_coins(wallet_type)
                reserve_ids = {
                    str(c.get("coin_id", "")).strip().lower()
                    for c in get_reserve_coins(wallet_type)
                    if c.get("coin_id")
                }
            except Exception as e:
                log_event(
                    "debug",
                    "coin_select_db_unavailable",
                    f"DB coin inventory unavailable for {wallet_type}: {e}",
                )

            if db_free_coins:
                designated_candidates = []
                oversize_designated_candidates = []
                try:
                    oversize_fallback_ratio = Decimal(
                        str(
                            getattr(cfg, "COIN_OVERSIZE_FALLBACK_RATIO", "2.0") or "2.0"
                        )
                    )
                except Exception:
                    oversize_fallback_ratio = Decimal("2.0")
                for coin in db_free_coins:
                    coin_id = str(coin.get("coin_id", "")).strip().lower()
                    if not coin_id or coin_id in used_coins:
                        continue

                    designation = (coin.get("designation") or "unknown").lower()
                    assigned_tier = (coin.get("assigned_tier") or "none").lower()
                    if designation == "reserve" or coin_id in reserve_ids:
                        continue
                    if assigned_tier == "sniper" and pref != "sniper":
                        continue
                    if strict_pref:
                        if designation not in ("tier_spare", "tier_active"):
                            continue
                        if assigned_tier != pref:
                            continue

                    coin_amount = spendable_amounts.get(coin_id)
                    if coin_amount is None or coin_amount < amount_mojos:
                        continue
                    if max_amount_mojos is not None and coin_amount > max_amount_mojos:
                        same_tier_designated = (
                            strict_pref
                            and designation in ("tier_spare", "tier_active")
                            and assigned_tier == pref
                        )
                        if (
                            same_tier_designated
                            and oversize_fallback_ratio > 0
                            and Decimal(coin_amount)
                            <= (Decimal(amount_mojos) * oversize_fallback_ratio)
                        ):
                            priority = self._coin_designation_priority(
                                designation, assigned_tier, preferred_tier
                            )
                            oversize_designated_candidates.append(
                                (
                                    priority,
                                    coin_amount - amount_mojos,
                                    coin_id,
                                    coin_amount,
                                    designation,
                                    assigned_tier,
                                )
                            )
                        continue
                    # F70 SSOT misfit guard with DB-trust override (2026-04-26):
                    # The live-price classifier shifts tier-size cutoffs every
                    # cycle, so a coin prepped at price P for tier T can drop
                    # below T's live floor after a small price move. When the
                    # DB already has assigned_tier == preferred_tier we trust
                    # the prep designation and only veto outright misfits
                    # (coins that fit no tier under live sizes). Without this,
                    # a 4% price drop drained inner-prepped coins into mid-
                    # sell offers and tripped a needless topup on first ladder.
                    if _coin_fits_preferred_tier is not None:
                        db_match = designation == "tier_spare" and assigned_tier == pref
                        if not db_match:
                            if not _coin_fits_preferred_tier(coin_amount):
                                continue

                    priority = self._coin_designation_priority(
                        designation, assigned_tier, preferred_tier
                    )
                    designated_candidates.append(
                        (
                            priority,
                            coin_amount - amount_mojos,
                            coin_id,
                            coin_amount,
                            designation,
                            assigned_tier,
                        )
                    )

                if designated_candidates:
                    designated_candidates.sort(key=lambda x: (x[0], x[1]))
                    (
                        _,
                        best_surplus,
                        best_coin_id,
                        best_amount,
                        best_desig,
                        best_tier,
                    ) = designated_candidates[0]
                    log_event(
                        "debug",
                        "coin_selected",
                        f"Selected designated coin {best_coin_id[:16]}... "
                        f"({best_amount} mojos, surplus={best_surplus}, "
                        f"{best_desig}/{best_tier})",
                    )
                    return best_coin_id

                if oversize_designated_candidates:
                    oversize_designated_candidates.sort(key=lambda x: (x[0], x[1]))
                    (
                        _,
                        best_surplus,
                        best_coin_id,
                        best_amount,
                        best_desig,
                        best_tier,
                    ) = oversize_designated_candidates[0]
                    log_event(
                        "info",
                        "coin_select_oversize_tier_fallback",
                        f"Selected moderately oversized same-tier coin "
                        f"{best_coin_id[:16]}... ({best_amount} mojos, "
                        f"need={amount_mojos}, surplus={best_surplus}, "
                        f"{best_desig}/{best_tier})",
                    )
                    return best_coin_id

                log_event(
                    "debug",
                    "coin_select_none",
                    f"No eligible designated {wallet_type.upper()} coins for "
                    f"{amount_mojos} mojos (preferred_tier={preferred_tier or 'any'}, "
                    f"{len(db_free_coins)} DB free, {len(used_coins)} used) "
                    f"— falling through to any available coin",
                )
                # Don't return None here — fall through to fallback candidates
                # so that coins from other tiers can be used rather than failing
                # the entire offer creation.

            if strict_pref:
                log_event(
                    "debug",
                    "coin_select_none",
                    f"No strict {pref} coin available for {amount_mojos} mojos "
                    f"(wallet {wallet_id}, {len(records)} spendable, "
                    f"{len(used_coins)} used in batch)",
                )
                return None

            candidates = [
                item for item in fallback_candidates if item[1] not in reserve_ids
            ]

            if candidates:
                candidates.sort(key=lambda x: x[0])
                best_surplus, best_coin_id, best_amount = candidates[0]

                log_event(
                    "debug",
                    "coin_selected",
                    f"Selected fallback coin {best_coin_id[:16]}... "
                    f"({best_amount} mojos, surplus={best_surplus}) "
                    f"from {len(candidates)} candidates",
                )
                return best_coin_id

        except Exception as e:
            log_event(
                "warning",
                "coin_select_error",
                f"Coin selection failed: {e} — will fall back to polling",
            )
            return None

    @staticmethod
    def _slot_size_variation(slot: int, expected_unique_count: int = 100) -> Decimal:
        """Return a deterministic per-slot size delta for uniqueness.

        The step is adaptive:
        - for small ladders, use larger visible nudges (around 1e-5 XCH)
        - for very large ladders, shrink toward 1e-8 XCH so thousands of
          offers still fit under the 0.001 XCH ceiling
        """
        if slot < 0:
            slot = 0
        if expected_unique_count <= 0:
            expected_unique_count = 1
        min_step = Decimal("0.00000001")
        max_step = Decimal("0.00001000")
        dynamic_step = Decimal("0.001") / Decimal(expected_unique_count)
        step = max(min_step, min(max_step, dynamic_step))
        variation = step * Decimal(slot + 1)
        max_variation = Decimal("0.001")
        if variation > max_variation:
            variation = max_variation
        return variation.quantize(Decimal("0.00000001"))

    @staticmethod
    def _size_key(size_xch: Decimal) -> Decimal:
        """Normalize offer sizes to the on-chain/display precision we care about."""
        return Decimal(str(size_xch)).quantize(Decimal("0.00000001"))

    @staticmethod
    def _requested_amount_from_open_offer(
        open_offer: Dict, side: str, decimals: int
    ) -> Optional[int]:
        """Extract the requested-side amount from an open offer in raw mojos."""
        raw_amount = (
            open_offer.get("size_cat") if side == "buy" else open_offer.get("size_xch")
        )
        if raw_amount in (None, ""):
            return None
        amount_decimal = Decimal(str(raw_amount))
        if side == "buy":
            return cat_to_mojos(amount_decimal, decimals)
        return xch_to_mojos(amount_decimal)

    def _allocate_unique_requested_mojos(
        self, base_requested_mojos: int, slot: int, used_requested_amounts: set
    ) -> int:
        """Return a requested amount that doesn't collide with live/batch offers."""
        candidate = int(base_requested_mojos)
        if candidate not in used_requested_amounts:
            used_requested_amounts.add(candidate)
            return candidate

        probe_slot = slot
        for _ in range(1000):
            candidate = int(base_requested_mojos) + max(1, probe_slot + 1)
            if candidate not in used_requested_amounts:
                used_requested_amounts.add(candidate)
                return candidate
            probe_slot += 1
        # Exhausted uniqueness attempts — return last probe
        log_event(
            "warning",
            "uniqueness_exhausted",
            "Could not find unique requested_mojos after 1000 attempts",
        )
        used_requested_amounts.add(candidate)
        return candidate

    def _allocate_unique_size_xch(
        self,
        base_size: Decimal,
        slot: int,
        tier_mode: bool,
        used_size_keys: set,
        expected_unique_count: int,
    ) -> Decimal:
        """Pick a size variation that does not collide with existing live offers."""
        probe_slot = slot
        for _ in range(1000):
            variation = self._slot_size_variation(
                probe_slot,
                expected_unique_count=expected_unique_count,
            )
            if tier_mode:
                candidate = max(Decimal("0.000001"), base_size - variation)
            else:
                candidate = base_size + variation

            key = self._size_key(candidate)
            if key not in used_size_keys:
                used_size_keys.add(key)
                return key
            probe_slot += 1
        # Exhausted uniqueness attempts — return last probe
        log_event(
            "warning",
            "uniqueness_exhausted",
            "Could not find unique size_xch after 1000 attempts",
        )
        used_size_keys.add(key)
        return key

    @staticmethod
    def _get_ladder_parallelism(coin_ids_enabled: bool) -> int:
        """Choose a safe worker count for live offer creation.

        Only allows parallelism when coin_ids are both enabled AND the
        wallet backend actually sends them in the RPC payload. Currently
        only Sage supports coin_ids; Chia wallet silently ignores them,
        so parallel creates would race on coin selection.
        """
        if not coin_ids_enabled:
            return 1
        # Chia wallet doesn't pass coin_ids to the RPC — force serial
        try:
            from wallet import get_wallet_type

            if get_wallet_type() != "sage":
                return 1
        except Exception:
            return 1
        try:
            configured = int(getattr(cfg, "LADDER_CREATE_PARALLELISM", 5) or 5)
        except Exception:
            configured = 5
        return max(1, configured)

    def get_replenishment_slots(
        self,
        side: str,
        total_slots: int,
        cat_asset_id: str = None,
        live_offer_ids: set = None,
    ) -> List[int]:
        """Plan which canonical ladder slots should be replenished next.

        Uses the live open offer counts per tier to determine which tiers are
        short relative to the full ladder shape. This avoids treating a refill
        of 1-2 offers as a brand new mini-ladder, which would otherwise skew
        replenishment toward inner/outer tiers.

        Args:
            live_offer_ids: Diagnostic wallet snapshot retained for API
                compatibility. Wallet omission never opens a durable slot.
        """
        asset_id = cat_asset_id or cfg.CAT_ASSET_ID

        if total_slots <= 0:
            return []

        tier_slots: Dict[str, List[int]] = {}
        for slot in range(total_slots):
            tier = self._classify_tier(slot, total_slots, side=side)
            tier_slots.setdefault(tier, []).append(slot)

        occupied_slots: set[int] = set()
        slot_reader = getattr(database, "get_active_offer_slot_keys", None)
        if slot_reader is not None:
            try:
                slot_prefix = f"ladder:{asset_id}:{side}:"
                for slot_key in slot_reader(
                    asset_id=asset_id,
                    side=side,
                ):
                    if not isinstance(slot_key, str) or not slot_key.startswith(
                        slot_prefix
                    ):
                        raise ValueError("active ladder slot key is not canonical")
                    suffix = slot_key[len(slot_prefix) :]
                    slot = int(suffix)
                    if str(slot) != suffix or slot < 0 or slot >= total_slots:
                        raise ValueError("active ladder slot key is out of range")
                    occupied_slots.add(slot)
            except Exception as exc:
                log_event(
                    "error",
                    "replenishment_slot_authority_unavailable",
                    "Durable ladder slot authority is unavailable; replenishment paused",
                    {"side": side, "asset_id": asset_id, "error": str(exc)},
                )
                return []

        if not cfg.TIER_ENABLED:
            return [
                slot
                for slot in tier_slots.get("mid", [])
                if slot not in occupied_slots and not self.is_slot_suspended(side, slot)
            ]

        live_counts = {tier: 0 for tier in tier_slots}
        for offer in get_open_offers(side=side, cat_asset_id=asset_id):
            tier = (offer.get("tier") or "mid").lower()
            if tier not in live_counts:
                continue
            live_counts[tier] += 1

        planned_slots: List[int] = []
        for tier in ("inner", "mid", "outer", "extreme"):
            tier_candidates = tier_slots.get(tier, [])
            if not tier_candidates:
                continue
            eligible_slots = [
                slot
                for slot in tier_candidates
                if not self.is_slot_suspended(side, slot)
            ]
            if not eligible_slots:
                continue
            live_count = live_counts.get(tier, 0)
            needed = len(eligible_slots) - live_count
            if needed <= 0:
                continue
            slots = [slot for slot in eligible_slots if slot not in occupied_slots]
            # Fill from the INNERMOST slots (front of the list, closest to mid)
            # so that replenishments after fills land back at the tightest
            # price position rather than the outermost end of the tier.
            #
            # Previous behaviour was slots[live_count:] (tail = outermost),
            # which caused a filled inner-tier offer to be replaced near the
            # outer boundary of that tier — not like-for-like.
            planned_slots.extend(slots[:needed])
        return planned_slots

    @staticmethod
    def _normalize_offer_ref(value: str) -> str:
        """Normalize offer hashes/trade ids for exact Sage offer_id comparison."""
        if not value:
            return ""
        normalized = str(value).strip().lower()
        if normalized.startswith("0x"):
            normalized = normalized[2:]
        return normalized

    @staticmethod
    def _normalize_coin_ref(value: str) -> str:
        """Normalize coin ids to lowercase 0x-prefixed form."""
        if not value:
            return ""
        normalized = str(value).strip().lower()
        if not normalized.startswith("0x"):
            normalized = "0x" + normalized
        return normalized

    def _sort_open_offers_for_requote(
        self, offers: List[Dict], side: str, mid_price: Decimal = None
    ) -> List[Dict]:
        """Sort live ladder offers so the most at-risk are cancelled first.

        Fix D: During a requote triggered by AMM drift, the offers closest to
        the new mid price are most at risk of being taken at stale prices.
        Sort by distance from the new mid price (ascending) so these inner
        offers are cancelled first.

        When mid_price is not provided, falls back to tier-based inner-out
        ordering (legacy behaviour).
        """
        if mid_price is not None and mid_price > 0:
            # Sort by distance from new mid price — closest first (most at risk)
            def _key_distance(offer: Dict):
                try:
                    price = Decimal(str(offer.get("price_xch") or "0"))
                except Exception:
                    price = Decimal("0")
                distance = abs(price - mid_price)
                # Tiebreaker: created_at so order is deterministic
                created_at = str(offer.get("created_at") or "")
                return (distance, created_at)

            return sorted(list(offers or []), key=_key_distance)

        # Fallback: tier-based inner-out ordering
        tier_rank = {
            "inner": 0,
            "mid": 1,
            "outer": 2,
            "extreme": 3,
        }

        def _key(offer: Dict):
            tier = str(offer.get("tier") or "mid").lower()
            rank = tier_rank.get(tier, 99)
            try:
                price = Decimal(str(offer.get("price_xch") or "0"))
            except Exception:
                price = Decimal("0")
            price_sort = -price if side == "buy" else price
            created_at = str(offer.get("created_at") or "")
            return (rank, price_sort, created_at)

        return sorted(list(offers or []), key=_key)

    def _select_requote_cancel_targets(
        self, offers: List[Dict], count: int, mid_price: Decimal = None
    ) -> List[Dict]:
        """Choose cancel targets for a partial requote.

        Closest-to-mid offers remain the priority. When a larger partial pass
        cannot process the whole side, reserve a small slice for old/far offers
        that would otherwise survive every capped pass.
        """
        ordered = list(offers or [])
        if count <= 0:
            return []
        if len(ordered) <= count:
            return ordered[:count]
        if count <= 3:
            return ordered[:count]

        deferred = ordered[count:]
        if not deferred:
            return ordered[:count]

        stale_slots = min(2, max(1, count // 4), len(deferred), count - 1)
        risk_slots = count - stale_slots
        risk_targets = ordered[:risk_slots]

        def _stale_key(offer: Dict):
            created_at = str(offer.get("created_at") or "9999")
            try:
                price = Decimal(str(offer.get("price_xch") or "0"))
            except Exception:
                price = Decimal("0")
            distance = (
                abs(price - mid_price) if mid_price and mid_price > 0 else Decimal("0")
            )
            return (created_at, -distance, str(offer.get("trade_id") or ""))

        stale_targets = sorted(deferred, key=_stale_key)[:stale_slots]
        return risk_targets + stale_targets

    def _get_sage_locked_coin_ids_for_trade(
        self, wallet_id: int, trade_id: str
    ) -> Optional[List[str]]:
        """Ask Sage which owned coins are locked by a specific offer_id/trade_id."""
        if get_wallet_type() != "sage" or wallet_id is None or not trade_id:
            return None
        try:
            detailed_map = get_owned_coins_detailed(wallet_id)
        except Exception as e:
            log_event(
                "warning",
                "coin_ids_verify_failed",
                f"Could not inspect Sage locked coins for {trade_id[:12]}...: {e}",
            )
            return None
        if detailed_map is None:
            return None

        wanted_offer_id = self._normalize_offer_ref(trade_id)
        locked_coin_ids = []
        for coin_id, info in detailed_map.items():
            offer_id = self._normalize_offer_ref((info or {}).get("offer_id"))
            if offer_id == wanted_offer_id:
                locked_coin_ids.append(self._normalize_coin_ref(coin_id))
        return sorted(set(locked_coin_ids))

    def _verify_sage_offer_locked_inputs(
        self, wallet_id: int, trade_id: str, selected_coin_id: str, max_polls: int = 6
    ) -> Dict:
        """Inspect which maker inputs Sage actually locked for a new offer."""
        normalized_selected = self._normalize_coin_ref(selected_coin_id)
        for poll in range(max_polls):
            locked_coin_ids = self._get_sage_locked_coin_ids_for_trade(
                wallet_id, trade_id
            )
            if locked_coin_ids:
                return {
                    "verified": True,
                    "locked_coin_ids": locked_coin_ids,
                    "selected_present": normalized_selected in locked_coin_ids,
                }
            if poll < max_polls - 1:
                time.sleep(1)
        return {
            "verified": False,
            "locked_coin_ids": [],
            "selected_present": False,
        }

    # -------------------------------------------------------------------
    # Offer Creation
    # -------------------------------------------------------------------

    @staticmethod
    def _canonical_creation_json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _canonical_sage_trade_id(value: Any) -> Optional[str]:
        if type(value) is not str or len(value) != 64:
            return None
        if any(character not in "0123456789abcdef" for character in value):
            return None
        return value

    @staticmethod
    def _malformed_refresh_identity_entry(index: int, value: Any) -> Dict[str, Any]:
        """Return bounded, redacted incident material for an invalid trade ID."""

        digest = hashlib.sha256()
        if isinstance(value, str):
            for offset in range(0, len(value), 4096):
                digest.update(
                    str.encode(value[offset : offset + 4096], "utf-8", "surrogatepass")
                )
        else:
            type_name = f"{type(value).__module__}.{type(value).__qualname__}"
            try:
                representation = repr(value)
            except Exception:
                representation = "<unrepresentable>"
            digest.update(
                f"{type_name}:{representation[:4096]}".encode(
                    "utf-8", "backslashreplace"
                )
            )
        return {"entry_index": index, "entry_sha256": digest.hexdigest()}

    @staticmethod
    def _canonical_sage_offer_text(value: Any) -> Optional[str]:
        return canonical_sage_offer_text(value)

    @staticmethod
    def _canonical_sage_creation_identity(result: Any) -> Optional[tuple[str, str]]:
        if type(result) is not dict or result.get("success") is not True:
            return None
        for error_key in ("error", "error_message"):
            error = result.get(error_key)
            if error is not None and not (type(error) is str and error == ""):
                return None
        status = result.get("status")
        if status is not None and type(status) is not str:
            return None
        if type(status) is str and status.strip().lower() in {
            "error",
            "failed",
            "failure",
            "rejected",
        }:
            return None
        trade_record_value = result.get("trade_record")
        if trade_record_value is None:
            trade_record = {}
        elif type(trade_record_value) is dict:
            trade_record = trade_record_value
        else:
            return None

        def supplied_trade_id(value: Any) -> tuple[bool, Optional[str]]:
            if value is None or (type(value) is str and value == ""):
                return False, None
            return True, OfferManager._canonical_sage_trade_id(value)

        direct_present, direct = supplied_trade_id(result.get("trade_id"))
        nested_present, nested = supplied_trade_id(trade_record.get("trade_id"))
        if (direct_present and direct is None) or (nested_present and nested is None):
            return None
        if direct is not None and nested is not None and direct != nested:
            return None
        trade_id = direct if direct is not None else nested
        offer_text = OfferManager._canonical_sage_offer_text(result.get("offer"))
        if trade_id is None or offer_text is None:
            return None
        return trade_id, offer_text

    @staticmethod
    def _canonical_selected_coin_id(value: Any) -> str:
        if type(value) is not str:
            raise ValueError("selected coin ID must be canonical text")
        normalized = value.strip().lower()
        if normalized.startswith("0x"):
            normalized = normalized[2:]
        if (
            len(normalized) != 64
            or not normalized.isascii()
            or any(character not in "0123456789abcdef" for character in normalized)
        ):
            raise ValueError("selected coin ID must be exactly 32-byte hex")
        return normalized

    def _build_canonical_creation_intent(
        self,
        *,
        offer_dict: dict,
        selected_coin_id: str,
        preferred_tier: Optional[str],
        creation_context: Optional[dict],
        expiry_seconds: int,
        expiry_offset: int,
        stagger_seconds: int,
        offer_max_time: int,
        min_coin_hint: Optional[int],
        max_coin_hint: Optional[int],
    ) -> _CanonicalOfferCreationIntent:
        if type(offer_dict) is not dict or not offer_dict:
            raise ValueError("offer_dict must be a non-empty exact object")
        items = []
        negative = []
        positive = []
        for raw_wallet_id, raw_amount in offer_dict.items():
            if type(raw_wallet_id) is int and raw_wallet_id > 0:
                wallet_id = str(raw_wallet_id)
            elif (
                type(raw_wallet_id) is str
                and raw_wallet_id.isascii()
                and raw_wallet_id.isdigit()
                and raw_wallet_id == str(int(raw_wallet_id))
                and int(raw_wallet_id) > 0
            ):
                wallet_id = raw_wallet_id
            else:
                raise ValueError("wallet IDs must be canonical positive integers")
            if type(raw_amount) is not int or raw_amount == 0:
                raise ValueError("offer amounts must be exact non-zero integers")
            item = (wallet_id, raw_amount)
            items.append(item)
            (negative if raw_amount < 0 else positive).append(item)
        if len(negative) != 1 or len(positive) != 1:
            raise ValueError("offer intent requires exactly one spend and one request")
        if len({wallet_id for wallet_id, _amount in items}) != len(items):
            raise ValueError("wallet IDs must be unique after canonicalization")
        items.sort(key=lambda item: int(item[0]))
        coin_id = self._canonical_selected_coin_id(selected_coin_id)
        for label, value in (
            ("expiry_seconds", expiry_seconds),
            ("expiry_offset", expiry_offset),
            ("stagger_seconds", stagger_seconds),
            ("offer_max_time", offer_max_time),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be an exact non-negative integer")
        for label, value in (
            ("min_coin_hint", min_coin_hint),
            ("max_coin_hint", max_coin_hint),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{label} must be an exact non-negative integer")
        context = {} if creation_context is None else creation_context
        if type(context) is not dict:
            raise ValueError("creation_context must be an exact object")
        generation = context.get("generation", 0)
        if type(generation) is not int or generation < 0:
            raise ValueError("creation generation must be a non-negative integer")
        authority_run_id = context.get("_authority_run_id")
        if authority_run_id is not None and (
            type(authority_run_id) is not str
            or not authority_run_id
            or authority_run_id != authority_run_id.strip()
        ):
            raise ValueError("creation authority run ID must be canonical text")
        inferred_side = (
            "buy"
            if int(negative[0][0]) == int(getattr(cfg, "WALLET_ID_XCH", 1))
            else "sell"
        )
        side = context.get("side", inferred_side)
        if type(side) is not str or side not in {"buy", "sell"}:
            raise ValueError("creation side must be buy or sell")
        tier = context.get("tier", preferred_tier or "unclassified")
        purpose = context.get("purpose", "normal_lifecycle")
        asset_id = context.get("asset_id", getattr(cfg, "CAT_ASSET_ID", None))
        parent_intent_id = context.get("parent_intent_id")
        for label, value in (
            ("tier", tier),
            ("purpose", purpose),
            ("asset_id", asset_id),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"creation {label} must be canonical text")
        if parent_intent_id is not None and (
            type(parent_intent_id) is not str
            or not parent_intent_id
            or parent_intent_id != parent_intent_id.strip()
        ):
            raise ValueError("parent_intent_id must be canonical text")
        uniqueness = context.get(
            "offer_size_uniqueness",
            {
                "requested_amount_atomic": str(positive[0][1]),
                "offer_items_sha256": hashlib.sha256(
                    self._canonical_creation_json(items).encode("utf-8")
                ).hexdigest(),
            },
        )
        if type(uniqueness) is not dict:
            raise ValueError("offer_size_uniqueness must be an exact object")
        uniqueness_json = self._canonical_creation_json(uniqueness)
        if len(uniqueness_json.encode("utf-8")) > 4096:
            raise ValueError("offer_size_uniqueness exceeds 4096 UTF-8 bytes")
        provisional_slot = context.get("slot_key")
        if provisional_slot is None:
            provisional_slot = (
                "offer:"
                + hashlib.sha256(
                    self._canonical_creation_json(
                        {
                            "offer_items": items,
                            "selected_coin_id": coin_id,
                            "side": side,
                            "tier": tier,
                            "purpose": purpose,
                        }
                    ).encode("utf-8")
                ).hexdigest()
            )
        if (
            type(provisional_slot) is not str
            or not provisional_slot
            or provisional_slot != provisional_slot.strip()
        ):
            raise ValueError("creation slot_key must be canonical text")
        identity_payload = {
            "schema_version": 1,
            "offer_items": items,
            "selected_coin_id": coin_id,
            "asset_id": asset_id,
            "side": side,
            "tier": tier,
            "purpose": purpose,
            "slot_key": provisional_slot,
            "generation": generation,
            "authority_run_id": authority_run_id,
            "parent_intent_id": parent_intent_id,
            "offer_size_uniqueness": json.loads(uniqueness_json),
            "wallet_effect": {
                "validate_only": False,
                "expiry_seconds": expiry_seconds,
                "expiry_offset": expiry_offset,
                "stagger_seconds": stagger_seconds,
                "min_coin_hint": min_coin_hint,
                "max_coin_hint": max_coin_hint,
            },
        }
        digest = hashlib.sha256(
            self._canonical_creation_json(identity_payload).encode("utf-8")
        ).hexdigest()
        return _CanonicalOfferCreationIntent(
            intent_id=digest,
            operation_id=f"create:{digest}",
            offer_items=tuple(items),
            offered_amount_atomic=str(abs(negative[0][1])),
            requested_amount_atomic=str(positive[0][1]),
            selected_coin_id=coin_id,
            asset_id=asset_id,
            side=side,
            tier=tier,
            purpose=purpose,
            slot_key=provisional_slot,
            generation=generation,
            authority_run_id=authority_run_id,
            parent_intent_id=parent_intent_id,
            offer_size_uniqueness_json=uniqueness_json,
            expiry_seconds=expiry_seconds,
            expiry_offset=expiry_offset,
            stagger_seconds=stagger_seconds,
            offer_max_time=offer_max_time,
            min_coin_hint=min_coin_hint,
            max_coin_hint=max_coin_hint,
            canonical_intent_sha256=digest,
        )

    @staticmethod
    def _resolve_creation_context_generation(creation_context: Any) -> Any:
        if (
            type(creation_context) is not dict
            or "select_next_generation" not in creation_context
        ):
            return creation_context
        if creation_context["select_next_generation"] is not True:
            raise ValueError("select_next_generation must be exact true")
        if "generation" in creation_context or "_authority_run_id" in creation_context:
            raise ValueError("durable generation selection cannot be overridden")
        slot_key = creation_context.get("slot_key")
        if type(slot_key) is not str or not slot_key or slot_key != slot_key.strip():
            raise ValueError(
                "durable generation selection requires a canonical slot_key"
            )
        selection = database.select_offer_creation_generation(slot_key=slot_key)
        if type(selection) is not dict:
            raise ValueError("durable generation selection is malformed")
        generation = selection.get("generation")
        run_id = selection.get("run_id")
        if type(generation) is not int or generation < 0:
            raise ValueError("durable generation selection is malformed")
        if type(run_id) is not str or not run_id or run_id != run_id.strip():
            raise ValueError("durable generation authority is malformed")
        resolved = dict(creation_context)
        del resolved["select_next_generation"]
        parent_intent_id = resolved.get("parent_intent_id")
        if parent_intent_id is not None:
            parent = database.get_offer_intent(parent_intent_id)
            if type(parent) is not dict:
                raise ValueError("refresh parent intent is missing")
            if (
                parent.get("slot_key") != slot_key
                or type(parent.get("generation")) is not int
                or generation != parent.get("generation")
                or selection.get("active_intent_id") != parent_intent_id
                or selection.get("active_lifecycle_state")
                != parent.get("lifecycle_state")
                or parent.get("child_intent_id") is not None
                or parent.get("lifecycle_state") not in {"created", "visible"}
            ):
                raise ValueError("refresh parent generation authority is invalid")
            generation = int(parent["generation"]) + 1
        resolved["generation"] = generation
        resolved["_authority_run_id"] = run_id
        return resolved

    def _offer_creation_crash_boundary(
        self,
        phase: str,
        intent: _CanonicalOfferCreationIntent,
    ) -> None:
        hook = self._offer_creation_crash_hook
        if hook is not None:
            hook(phase, intent)

    @staticmethod
    def _existing_creation_result(
        intent: _CanonicalOfferCreationIntent,
        existing: dict,
    ) -> dict:
        state = str(existing.get("lifecycle_state") or "")
        if state == "created":
            trade_id = str(existing.get("sage_trade_id") or "")
            offer_max_time = OfferManager._persisted_creation_offer_max_time(
                intent, existing
            )
            if offer_max_time is None:
                OfferManager._trip_creation_latch(
                    intent,
                    reason_code="UNRESOLVED_OPERATIONS",
                    wallet_fingerprint_hash=str(existing["wallet_fingerprint_hash"]),
                    network=str(existing["network"]),
                )
                return OfferManager._creation_reconciliation_result(intent)
            return {
                "success": True,
                "trade_id": trade_id,
                "trade_record": {"trade_id": trade_id},
                "locked_coin_id": intent.selected_coin_id,
                "offer_max_time": offer_max_time,
                "_catalyst_effect_attempted": False,
                "_catalyst_idempotent_replay": True,
                "_catalyst_intent_id": intent.intent_id,
            }
        if state in {"prepared", "submitted_unconfirmed", "creation_unknown"}:
            OfferManager._trip_creation_latch(
                intent,
                reason_code="UNRESOLVED_OPERATIONS",
                wallet_fingerprint_hash=str(existing["wallet_fingerprint_hash"]),
                network=str(existing["network"]),
            )
            return OfferManager._creation_reconciliation_result(intent)
        return {
            "success": False,
            "error": "Offer creation intent is already terminal",
            "reason": "OFFER_CREATION_ALREADY_FINALIZED",
            "_catalyst_effect_attempted": False,
            "_catalyst_intent_id": intent.intent_id,
        }

    @staticmethod
    def _persisted_creation_offer_max_time(
        intent: _CanonicalOfferCreationIntent,
        existing: dict,
    ) -> Optional[int]:
        try:
            events = database.get_offer_operation_events(intent.operation_id)
        except Exception:
            return None
        for event in events:
            if type(event) is not dict or event.get("phase") != "PREPARED":
                continue
            try:
                canonical_event = database.validate_offer_operation_event(event)
                evidence = json.loads(canonical_event["evidence_json"])
                journal = json.loads(canonical_event["wallet_identity_json"])
                journal, run_id, wallet_hash, network = (
                    OfferManager._verified_continuation_journal(journal, intent)
                )
            except (KeyError, TypeError, ValueError):
                return None
            if (
                canonical_event["event_id"] != f"{intent.operation_id}:prepared"
                or canonical_event["operation_id"] != intent.operation_id
                or canonical_event["intent_id"] != intent.intent_id
                or canonical_event["operation_type"] != "CREATE"
                or canonical_event["attempt"] != 1
                or canonical_event["phase"] != "PREPARED"
                or canonical_event["outcome"] != "PREPARED"
                or canonical_event["transaction_id"] is not None
                or canonical_event["spend_identity"] is not None
                or canonical_event["reason_code"] != "INTENT_PREPARED"
                or canonical_event["blocks_mutation"] != 1
                or canonical_event["request_timestamp"] != canonical_event["created_at"]
                or type(evidence) is not dict
                or set(evidence)
                != {
                    "canonical_intent_sha256",
                    "continuation_journal_sha256",
                    "offer_items",
                    "wallet_effect",
                    "offer_size_uniqueness",
                    "selected_coin_ids",
                }
                or evidence["canonical_intent_sha256"] != intent.canonical_intent_sha256
                or evidence["offer_items"]
                != [list(item) for item in intent.offer_items]
                or evidence["offer_size_uniqueness"] != intent.offer_size_uniqueness()
                or evidence["selected_coin_ids"] != [intent.selected_coin_id]
                or evidence["continuation_journal_sha256"] != journal["snapshot_sha256"]
                or run_id != existing.get("run_id")
                or wallet_hash != existing.get("wallet_fingerprint_hash")
                or network != existing.get("network")
            ):
                return None
            continuation_digest = evidence["continuation_journal_sha256"]
            if (
                type(continuation_digest) is not str
                or len(continuation_digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in continuation_digest
                )
            ):
                return None
            wallet_effect = evidence["wallet_effect"]
            if type(wallet_effect) is not dict or set(wallet_effect) != {
                "validate_only",
                "expiry_seconds",
                "expiry_offset",
                "stagger_seconds",
                "offer_max_time",
                "min_coin_hint",
                "max_coin_hint",
            }:
                return None
            expected_effect = {
                "validate_only": False,
                "expiry_seconds": intent.expiry_seconds,
                "expiry_offset": intent.expiry_offset,
                "stagger_seconds": intent.stagger_seconds,
                "min_coin_hint": intent.min_coin_hint,
                "max_coin_hint": intent.max_coin_hint,
            }
            if any(
                wallet_effect[key] != value for key, value in expected_effect.items()
            ):
                return None
            offer_max_time = wallet_effect["offer_max_time"]
            if type(offer_max_time) is not int or offer_max_time < 0:
                return None
            return offer_max_time
        return None

    @staticmethod
    def _creation_reconciliation_result(
        intent: _CanonicalOfferCreationIntent,
    ) -> dict:
        return {
            "success": False,
            "error": "Offer creation requires reconciliation",
            "reason": "OFFER_CREATION_RECONCILIATION_REQUIRED",
            "_catalyst_effect_attempted": False,
            "_catalyst_intent_id": intent.intent_id,
        }

    @staticmethod
    def _trip_creation_latch(
        intent: _CanonicalOfferCreationIntent,
        *,
        reason_code: str,
        wallet_fingerprint_hash: str,
        network: str,
    ) -> bool:
        try:
            database.trip_runtime_safety_latch(
                reason_code=reason_code,
                reason="Offer creation outcome requires reconciliation",
                blocking_operation_ids=[intent.operation_id],
                wallet_fingerprint_hash=wallet_fingerprint_hash,
                network=network,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _verified_continuation_journal(
        journal: Any,
        intent: _CanonicalOfferCreationIntent | _CanonicalOfferCancelIntent,
        *,
        trade_id: Optional[str] = None,
        allowed_backends: frozenset[str] = frozenset({"sage"}),
    ) -> tuple[dict, str, str, str]:
        if type(journal) is not dict or set(journal) != {
            "snapshot",
            "snapshot_sha256",
        }:
            raise ValueError("offer creation authority journal is malformed")
        snapshot = journal["snapshot"]
        expected_snapshot_keys = {
            "schema_version",
            "operation_id",
            "intent_id",
            "binding",
            "binding_digest",
            "observation",
            "observation_digest",
            "authority",
        }
        if trade_id is not None:
            expected_snapshot_keys.add("trade_id")
        if type(snapshot) is not dict or set(snapshot) != expected_snapshot_keys:
            raise ValueError("offer creation authority journal is malformed")
        if (
            type(snapshot["schema_version"]) is not int
            or snapshot["schema_version"] != 1
        ):
            raise ValueError("offer creation authority schema is unsupported")
        encoded = OfferManager._canonical_creation_json(snapshot)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if (
            type(journal["snapshot_sha256"]) is not str
            or journal["snapshot_sha256"] != digest
        ):
            raise ValueError("offer creation authority journal digest mismatch")
        if (
            snapshot.get("operation_id") != intent.operation_id
            or snapshot.get("intent_id") != intent.intent_id
            or (trade_id is not None and snapshot.get("trade_id") != trade_id)
        ):
            raise ValueError("offer creation authority journal scope mismatch")
        binding_payload = snapshot.get("binding")
        if type(binding_payload) is not dict:
            raise ValueError("offer creation authority binding is missing")
        try:
            binding = mutation_gate.WalletIdentityBinding(**binding_payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("offer creation authority binding is malformed") from exc
        if binding_payload != mutation_gate.wallet_identity_binding_payload(binding):
            raise ValueError("offer creation authority binding is not canonical")
        binding_digest = mutation_gate.wallet_identity_binding_digest(binding)
        if snapshot.get("binding_digest") != binding_digest:
            raise ValueError("offer creation authority binding digest mismatch")
        if binding.backend not in allowed_backends:
            raise ValueError("offer authority backend is unsupported")
        observation = snapshot.get("observation")
        if type(observation) is not dict or set(observation) != {
            "backend",
            "name",
            "fingerprint",
            "network_id",
            "kind",
            "has_secrets",
            "observed_at_utc",
        }:
            raise ValueError("offer creation observation is missing")
        observed_at = observation["observed_at_utc"]
        if (
            type(observation["backend"]) is not str
            or type(observation["name"]) is not str
            or type(observation["fingerprint"]) is not int
            or type(observation["network_id"]) is not str
            or type(observation["kind"]) is not str
            or observation["has_secrets"] is not True
            or type(observed_at) is not str
        ):
            raise ValueError("offer creation observation is malformed")
        expected_observation_identity = {
            "backend": binding.backend,
            "name": binding.name,
            "fingerprint": binding.fingerprint,
            "network_id": binding.network_id,
            "kind": binding.kind,
            "has_secrets": binding.has_secrets,
        }
        if {
            key: observation[key] for key in expected_observation_identity
        } != expected_observation_identity:
            raise ValueError("offer creation observation does not match binding")
        try:
            parsed_observed_at = datetime.fromisoformat(
                observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else ""
            )
        except ValueError as exc:
            raise ValueError(
                "offer creation observation timestamp is malformed"
            ) from exc
        canonical_observed_at = (
            parsed_observed_at.astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        if observed_at != canonical_observed_at:
            raise ValueError("offer creation observation timestamp is not canonical")
        identity_decision = mutation_gate.validate_wallet_identity(
            binding,
            {"success": True, **observation},
            now=parsed_observed_at,
        )
        if identity_decision != {
            "allowed": True,
            "reason": "identity_verified",
            "observed_at_utc": observed_at,
        }:
            raise ValueError("offer creation observation is not exact identity proof")
        observation_digest = hashlib.sha256(
            OfferManager._canonical_creation_json(observation).encode("utf-8")
        ).hexdigest()
        if (
            type(snapshot.get("observation_digest")) is not str
            or snapshot["observation_digest"] != observation_digest
        ):
            raise ValueError("offer creation observation digest mismatch")
        authority = snapshot.get("authority")
        if type(authority) is not dict:
            raise ValueError("offer creation authority proof is missing")
        runtime_authority_keys = {
            "mode",
            "owner_run_id",
            "owner_pid",
            "owner_host",
            "lease_version",
            "lease_epoch",
            "authority_generation_digest",
            "binding_digest",
        }
        worker_authority_keys = {
            "mode",
            "delegation_id",
            "parent_run_id",
            "delegation_operation_id",
            "purpose",
            "worker_id",
            "parent_lease_epoch",
            "authority_generation_digest",
            "binding_digest",
        }
        mode = authority.get("mode")
        expected_authority_keys = (
            runtime_authority_keys
            if mode == "runtime"
            else worker_authority_keys
            if mode == "worker"
            else set()
        )
        if set(authority) != expected_authority_keys:
            raise ValueError("offer creation authority proof is incomplete")
        if authority["binding_digest"] != binding_digest:
            raise ValueError("offer creation authority proof binding mismatch")
        generation_digest = authority.get("authority_generation_digest")
        if (
            type(generation_digest) is not str
            or len(generation_digest) != 64
            or any(
                character not in "0123456789abcdef" for character in generation_digest
            )
        ):
            raise ValueError("offer creation authority generation is malformed")
        if mode == "runtime":
            run_id = authority["owner_run_id"]
            epoch = authority["lease_epoch"]
            if (
                type(authority["owner_pid"]) is not int
                or authority["owner_pid"] <= 0
                or type(authority["lease_version"]) is not int
                or authority["lease_version"] <= 0
                or type(authority["owner_host"]) is not str
                or not authority["owner_host"]
            ):
                raise ValueError("offer creation runtime authority is malformed")
        elif mode == "worker":
            run_id = authority["parent_run_id"]
            epoch = authority["parent_lease_epoch"]
            if authority["delegation_operation_id"] != intent.operation_id:
                raise ValueError("worker delegation is bound to another operation")
            for key in ("delegation_id", "purpose", "worker_id"):
                if type(authority[key]) is not str or not authority[key]:
                    raise ValueError("offer creation worker authority is malformed")
        else:
            raise ValueError("offer creation authority mode is malformed")
        if type(run_id) is not str or not run_id or type(epoch) is not str or not epoch:
            raise ValueError("offer creation authority ownership is malformed")
        if intent.authority_run_id is not None and run_id != intent.authority_run_id:
            raise ValueError("offer creation generation authority run mismatch")
        return (
            journal,
            run_id,
            mutation_gate.wallet_fingerprint_hash(binding.fingerprint),
            binding.network_id,
        )

    @staticmethod
    def _bounded_lock_verification(value: Any) -> dict[str, Any]:
        source = value if type(value) is dict else {}
        locked = source.get("locked_coin_ids")
        if type(locked) is not list:
            locked = []
        canonical_locked = set()
        for coin_id in locked[:32]:
            if type(coin_id) is not str:
                continue
            normalized = coin_id.strip().lower()
            if normalized.startswith("0x"):
                normalized = normalized[2:]
            if len(normalized) != 64 or any(
                character not in "0123456789abcdef" for character in normalized
            ):
                continue
            canonical_locked.add("0x" + normalized)
        return {
            "verified": source.get("verified") is True,
            "locked_coin_ids": sorted(canonical_locked),
            "selected_present": source.get("selected_present") is True,
        }

    @staticmethod
    def _authorize_prepared_creation(
        intent: _CanonicalOfferCreationIntent,
        wallet_hash: str,
        network: str,
    ) -> dict[str, Any]:
        records = tuple(
            offer_registry.offer_record_from_row(row)
            for row in database.get_offer_intents_for_registry()
        )
        decision = offer_registry.authorize_mutation(
            offer_registry.RegistrySnapshot(records=records),
            offer_registry.MutationRequest(
                kind=offer_registry.MutationKind.CREATE,
                reference=offer_registry.OfferReference(intent_id=intent.intent_id),
                wallet_fingerprint_hash=wallet_hash,
                network=network,
                selected_coin_ids=(intent.selected_coin_id,),
            ),
        )
        return {
            "allowed": decision.allowed is True,
            "code": decision.code.value,
        }

    def _create_offer_from_journal(
        self,
        *,
        intent: _CanonicalOfferCreationIntent,
        spend_wallet_id: int,
    ) -> dict:
        with self._sage_creation_authority_lock:
            return self._create_offer_from_journal_serialized(
                intent=intent,
                spend_wallet_id=spend_wallet_id,
            )

    def _create_offer_from_journal_serialized(
        self,
        *,
        intent: _CanonicalOfferCreationIntent,
        spend_wallet_id: int,
    ) -> dict:
        existing = database.get_offer_intent(intent.intent_id)
        if existing is not None:
            return self._existing_creation_result(intent, existing)
        continuation = None
        journal = None
        prepared = False
        wallet_call_started = False
        wallet_hash = ""
        network = ""
        try:
            continuation = wallet.begin_offer_creation_continuation(
                operation_id=intent.operation_id,
                intent_id=intent.intent_id,
                ttl_seconds=60,
            )
            journal = wallet.offer_creation_continuation_journal(continuation)
            journal, run_id, wallet_hash, network = self._verified_continuation_journal(
                journal,
                intent,
            )
            prepared_at = datetime.now(timezone.utc).isoformat()
            prepared_evidence = {
                "canonical_intent_sha256": intent.canonical_intent_sha256,
                "continuation_journal_sha256": journal["snapshot_sha256"],
                "offer_items": list(intent.offer_items),
                "wallet_effect": {
                    "validate_only": False,
                    "expiry_seconds": intent.expiry_seconds,
                    "expiry_offset": intent.expiry_offset,
                    "stagger_seconds": intent.stagger_seconds,
                    "offer_max_time": intent.offer_max_time,
                    "min_coin_hint": intent.min_coin_hint,
                    "max_coin_hint": intent.max_coin_hint,
                },
                "offer_size_uniqueness": intent.offer_size_uniqueness(),
                "selected_coin_ids": [intent.selected_coin_id],
            }
            self._offer_creation_crash_boundary("before_intent_commit", intent)
            try:
                database.prepare_offer_intent(
                    intent_id=intent.intent_id,
                    operation_id=intent.operation_id,
                    event_id=f"{intent.operation_id}:prepared",
                    run_id=run_id,
                    wallet_fingerprint_hash=wallet_hash,
                    network=network,
                    asset_id=intent.asset_id,
                    side=intent.side,
                    tier=intent.tier,
                    purpose=intent.purpose,
                    slot_key=intent.slot_key,
                    generation=intent.generation,
                    parent_intent_id=intent.parent_intent_id,
                    offered_amount_atomic=intent.offered_amount_atomic,
                    requested_amount_atomic=intent.requested_amount_atomic,
                    selected_coin_ids_json=[intent.selected_coin_id],
                    cat_decimals=int(getattr(cfg, "CAT_DECIMALS", 3)),
                    fee_mojos_xch=0,
                    fee_provenance="EXPLICIT_CREATE_OFFER_FEE_V1",
                    wallet_identity_json=journal,
                    evidence_json=prepared_evidence,
                    prepared_at=prepared_at,
                    reserve_selected_coins=True,
                    require_new_intent=True,
                )
            except Exception as exc:
                message = str(exc)
                if (
                    "offer intent already exists" in message
                    or "selected coin is not free" in message
                    or "UNIQUE constraint failed: offer_intents.run_id" in message
                    or "UNIQUE constraint failed: offer_intents.slot_key" in message
                ):
                    raise _OfferCreationClaimLost from exc
                raise
            prepared = True
            self._offer_creation_crash_boundary("after_intent_commit", intent)
            registry_authorization = self._authorize_prepared_creation(
                intent,
                wallet_hash,
                network,
            )
            if registry_authorization["allowed"] is not True:
                denied_at = datetime.now(timezone.utc).isoformat()
                database.finalize_offer_intent(
                    intent_id=intent.intent_id,
                    operation_id=intent.operation_id,
                    event_id=f"{intent.operation_id}:finalized:registry-denied",
                    lifecycle_state="creation_failed",
                    outcome="FAILED",
                    wallet_identity_json=journal,
                    evidence_json={
                        "canonical_intent_sha256": intent.canonical_intent_sha256,
                        "continuation_journal_sha256": journal["snapshot_sha256"],
                        "effect_attempted": False,
                        "registry_authorization": registry_authorization,
                    },
                    reason_code=f"REGISTRY_{registry_authorization['code']}",
                    finalized_at=denied_at,
                    finalize_selected_coin_reservations=True,
                )
                return {
                    "success": False,
                    "error": "Offer creation denied by registry policy",
                    "reason": "OFFER_CREATION_REGISTRY_DENIED",
                    "_catalyst_effect_attempted": False,
                    "_catalyst_intent_id": intent.intent_id,
                }
            self._offer_creation_crash_boundary("before_wallet_call", intent)
            wallet_call_started = True
            result = wallet.create_offer(
                intent.offer_dict(),
                validate_only=False,
                max_time=intent.offer_max_time,
                min_coin_amount=intent.min_coin_hint,
                max_coin_amount=intent.max_coin_hint,
                coin_ids=[intent.selected_coin_id],
                _creation_continuation=continuation,
                _creation_operation_id=intent.operation_id,
                _creation_intent_id=intent.intent_id,
            )
            continuation = None
            self._offer_creation_crash_boundary("after_wallet_response", intent)
            effect_attempted = (
                type(result) is dict
                and result.get("_catalyst_effect_attempted") is True
            )
            success = type(result) is dict and result.get("success") is True
            sage_identity = self._canonical_sage_creation_identity(result)
            trade_id, offer_text = sage_identity or ("", "")
            result_reason = result.get("reason") if type(result) is dict else None
            safe_result_reason = (
                result_reason[:128]
                if type(result_reason) is str and result_reason
                else "MALFORMED_RESULT"
            )
            if success and sage_identity is None:
                safe_result_reason = "MALFORMED_RESULT"
            finalized_at = datetime.now(timezone.utc).isoformat()
            base_evidence = {
                "canonical_intent_sha256": intent.canonical_intent_sha256,
                "continuation_journal_sha256": journal["snapshot_sha256"],
                "effect_attempted": effect_attempted,
                "offer_size_uniqueness": intent.offer_size_uniqueness(),
                "registry_authorization": registry_authorization,
                "wallet_result": {
                    "success": success,
                    "trade_id_present": bool(trade_id),
                    "offer_text_present": bool(offer_text),
                    "reason": safe_result_reason,
                },
            }
            if success and effect_attempted and trade_id and offer_text:
                verification = self._bounded_lock_verification(
                    self._verify_sage_offer_locked_inputs(
                        spend_wallet_id,
                        trade_id,
                        intent.selected_coin_id,
                    )
                )
                offer_hash = hashlib.sha256(offer_text.encode("utf-8")).hexdigest()
                evidence = dict(base_evidence)
                evidence.update(
                    {
                        "locked_input_verification": verification,
                        "offer_text_sha256": offer_hash,
                        "sage_trade_id": trade_id,
                    }
                )
                self._offer_creation_crash_boundary("before_trade_id_commit", intent)
                database.finalize_offer_intent(
                    intent_id=intent.intent_id,
                    operation_id=intent.operation_id,
                    event_id=f"{intent.operation_id}:finalized:confirmed",
                    lifecycle_state="created",
                    outcome="CONFIRMED",
                    sage_trade_id=trade_id,
                    offer_text_sha256=offer_hash,
                    wallet_identity_json=journal,
                    evidence_json=evidence,
                    finalized_at=finalized_at,
                    finalize_selected_coin_reservations=True,
                )
                self._offer_creation_crash_boundary("after_trade_id_commit", intent)
                enriched = dict(result)
                enriched["locked_coin_id"] = intent.selected_coin_id
                enriched["offer_max_time"] = intent.offer_max_time
                enriched["_catalyst_intent_id"] = intent.intent_id
                enriched["_catalyst_locked_input_verification"] = verification
                return enriched
            if (
                type(result) is dict
                and result.get("_catalyst_effect_attempted") is False
            ):
                evidence = dict(base_evidence)
                database.finalize_offer_intent(
                    intent_id=intent.intent_id,
                    operation_id=intent.operation_id,
                    event_id=f"{intent.operation_id}:finalized:failed",
                    lifecycle_state="creation_failed",
                    outcome="FAILED",
                    wallet_identity_json=journal,
                    evidence_json=evidence,
                    reason_code=(
                        safe_result_reason
                        if safe_result_reason != "MALFORMED_RESULT"
                        else "CREATE_REJECTED"
                    ),
                    finalized_at=finalized_at,
                    finalize_selected_coin_reservations=True,
                )
                failed = dict(result)
                failed["_catalyst_intent_id"] = intent.intent_id
                return failed
            database.finalize_offer_intent(
                intent_id=intent.intent_id,
                operation_id=intent.operation_id,
                event_id=f"{intent.operation_id}:finalized:unknown",
                lifecycle_state="creation_unknown",
                outcome="UNKNOWN",
                wallet_identity_json=journal,
                evidence_json=base_evidence,
                reason_code="CREATE_RESPONSE_AMBIGUOUS",
                finalized_at=finalized_at,
                finalize_selected_coin_reservations=True,
            )
            return self._existing_creation_result(
                intent,
                database.get_offer_intent(intent.intent_id),
            )
        except _OfferCreationClaimLost:
            raise
        except Exception:
            current = None
            try:
                current = database.get_offer_intent(intent.intent_id)
            except Exception:
                pass
            if not prepared:
                if current is None:
                    raise
                self._trip_creation_latch(
                    intent,
                    reason_code="UNRESOLVED_OPERATIONS",
                    wallet_fingerprint_hash=wallet_hash,
                    network=network,
                )
                return self._creation_reconciliation_result(intent)
            if current is not None and current.get("lifecycle_state") == "created":
                return self._existing_creation_result(intent, current)
            exception_evidence = {
                "canonical_intent_sha256": intent.canonical_intent_sha256,
                "continuation_journal_sha256": (
                    journal.get("snapshot_sha256")
                    if type(journal) is dict
                    and type(journal.get("snapshot_sha256")) is str
                    else ""
                ),
                "effect_attempted": wallet_call_started,
                "failure_stage": (
                    "post_wallet_call" if wallet_call_started else "pre_wallet_call"
                ),
            }
            finalized = False
            try:
                if current is not None and current.get("lifecycle_state") == "prepared":
                    database.finalize_offer_intent(
                        intent_id=intent.intent_id,
                        operation_id=intent.operation_id,
                        event_id=(
                            f"{intent.operation_id}:finalized:exception-unknown"
                            if wallet_call_started
                            else f"{intent.operation_id}:finalized:pre-effect-exception"
                        ),
                        lifecycle_state=(
                            "creation_unknown"
                            if wallet_call_started
                            else "creation_failed"
                        ),
                        outcome="UNKNOWN" if wallet_call_started else "FAILED",
                        wallet_identity_json=journal,
                        evidence_json=exception_evidence,
                        reason_code=(
                            "CREATE_POST_EFFECT_EXCEPTION"
                            if wallet_call_started
                            else "CREATE_PRE_EFFECT_EXCEPTION"
                        ),
                        finalized_at=datetime.now(timezone.utc).isoformat(),
                        finalize_selected_coin_reservations=True,
                    )
                    finalized = True
                elif current is not None and current.get("lifecycle_state") in {
                    "creation_unknown",
                    "submitted_unconfirmed",
                }:
                    wallet_call_started = True
                    finalized = True
            except Exception:
                finalized = False
            if not wallet_call_started and finalized:
                return {
                    "success": False,
                    "error": "Offer creation failed before wallet effect",
                    "reason": "OFFER_CREATION_PRE_EFFECT_FAILED",
                    "_catalyst_effect_attempted": False,
                    "_catalyst_intent_id": intent.intent_id,
                }
            self._trip_creation_latch(
                intent,
                reason_code="UNRESOLVED_OPERATIONS",
                wallet_fingerprint_hash=wallet_hash,
                network=network,
            )
            return self._creation_reconciliation_result(intent)
        finally:
            if continuation is not None:
                try:
                    wallet.close_offer_creation_continuation(continuation)
                except Exception:
                    # Cleanup is best-effort and must never replace the stable
                    # durable result (or the original pre-prepare exception).
                    pass

    def create_offer_with_retry(
        self,
        offer_dict: dict,
        max_retries: int = 2,
        expiry_offset: int = 0,
        expiry_secs: int = None,
        used_coins: set = None,
        coin_ids_enabled: bool = False,
        selected_coin_id: str = None,
        preferred_tier: str = None,
        strict_preferred_tier: bool = False,
        creation_context: dict = None,
    ) -> Optional[Dict]:
        """Create a Chia offer with automatic retry on transient errors.

        Thread-safe: acquires self._lock to prevent concurrent coin selection
        from different threads (main loop, sniper, boost) choosing the same coin.

        Handles the "Wallet needs to be fully synced" error that occurs
        briefly during heavy operations: retry with backoff until the wallet
        reports fully synced or the retry budget is exhausted.

        Two coin detection modes:
        1. coin_ids mode (V3): Pre-select a coin and pass it to make_offer.
           The wallet locks exactly that coin — no polling needed. ~45x faster.
        2. Polling mode (V2 fallback): Snapshot coins before/after, poll to
           detect which coin disappeared. Used when coin_ids is disabled or
           when coin selection fails.

        Args:
            offer_dict: {str(wallet_id): amount_mojos} — negative=spend, positive=receive
            max_retries: How many times to retry on transient errors
            expiry_offset: Extra seconds added to expiry for staggering
            expiry_secs: Override expiry duration (e.g., short expiry for sniper offers)
            used_coins: Set of coin_ids already used in this batch (reuse guard)
            preferred_tier: Optional target tier ('inner', 'mid', 'outer',
                'extreme', 'sniper'). Matching designated spares are preferred.
            strict_preferred_tier: When True, only coins in preferred_tier are
                eligible. If none are available, offer creation fails cleanly.
            coin_ids_enabled: If True, pre-select coins via _select_coin_for_offer()
            selected_coin_id: Optional coin ID chosen by the caller. When
                provided, this is used directly and we do not re-select.

        Returns the wallet RPC response, or None on failure.
        The response will include a 'locked_coin_id' key if coin detection succeeded.
        """
        # --- Reservation lease ---
        # Acquire a soft capacity hold before hitting the wallet.  This prevents
        # concurrent threads (sniper, boost, main loop) from over-allocating the
        # same balance.  We fail-open on any reservation system error so that a
        # broken DB never blocks offer creation.
        _reservation_id: Optional[str] = None
        try:
            from reservation_manager import ReservationManager as _RM

            _xch_spend = 0
            _cat_spend = 0
            _xch_wid = getattr(cfg, "WALLET_ID_XCH", 1)
            _cat_wid = getattr(cfg, "CAT_WALLET_ID", 2)
            for _wid, _amt in offer_dict.items():
                if int(_amt) < 0:
                    if int(_wid) == _xch_wid:
                        _xch_spend += abs(int(_amt))
                    elif int(_wid) == _cat_wid:
                        _cat_spend += abs(int(_amt))
            if _xch_spend > 0 or _cat_spend > 0:
                _rm = _RM()
                _res = _rm.try_acquire(
                    purpose=f"create_offer_{preferred_tier or 'default'}",
                    xch_mojos=_xch_spend,
                    cat_mojos=_cat_spend,
                    lease_secs=90,
                )
                if _res.success:
                    _reservation_id = _res.reservation_id
        except Exception:
            pass  # fail-open — reservation is a guard, not a blocker

        try:
            return self._create_offer_with_retry_inner(
                offer_dict=offer_dict,
                max_retries=max_retries,
                expiry_offset=expiry_offset,
                expiry_secs=expiry_secs,
                used_coins=used_coins,
                coin_ids_enabled=coin_ids_enabled,
                selected_coin_id=selected_coin_id,
                preferred_tier=preferred_tier,
                strict_preferred_tier=strict_preferred_tier,
                creation_context=creation_context,
            )
        finally:
            if _reservation_id:
                try:
                    from reservation_manager import ReservationManager as _RM2

                    _RM2().release(_reservation_id, status="completed")
                except Exception:
                    pass

    def _create_offer_with_retry_inner(
        self,
        offer_dict: dict,
        max_retries: int = 2,
        expiry_offset: int = 0,
        expiry_secs: int = None,
        used_coins: set = None,
        coin_ids_enabled: bool = False,
        selected_coin_id: str = None,
        preferred_tier: str = None,
        strict_preferred_tier: bool = False,
        creation_context: dict = None,
    ) -> Optional[Dict]:
        """Internal implementation — called by create_offer_with_retry after
        the reservation lease is acquired.  See create_offer_with_retry for
        full documentation."""
        # On-chain expiry — offers auto-expire and vanish from Dexie.
        # The fill tracker's mass disappearance guard (3-strike rule)
        # handles the phantom fill risk from expired offers.
        # expiry_secs parameter allows override (e.g., shorter for sniper).
        _expiry = expiry_secs if expiry_secs is not None else cfg.OFFER_EXPIRY_SECS
        stagger = 0
        if _expiry and _expiry > 0:
            # Stagger expiry across offers to avoid mass-expiry cascades
            stagger = expiry_offset * cfg.OFFER_STAGGER_SECS if expiry_offset else 0
            offer_max_time = int(time.time()) + _expiry + stagger
        else:
            offer_max_time = 0

        # Coin selection hints — tell the wallet what size coin to use.
        # Range: 80%-200% of spend amount. Tight enough to pick the right
        # tier, loose enough to not fail when coins aren't perfectly sized.
        # The min_coin_amount of 80% prevents using undersized coins.
        # The max_coin_amount of 200% prevents wasting large reserve coins.
        # If this still fails (e.g. all coins are much larger), the wallet
        # will return an error and we can retry without hints.
        spend_amount = 0
        spend_wallet_id = None
        for wid, amt in offer_dict.items():
            if int(amt) < 0:
                if abs(int(amt)) > spend_amount:
                    spend_amount = abs(int(amt))
                    spend_wallet_id = int(wid)
        # Hint: use coins between 80% and 200% of the spend amount
        min_coin_hint = (spend_amount * 8) // 10 if spend_amount > 0 else None
        max_coin_hint = spend_amount * 2 if spend_amount > 0 else None

        try:
            authoritative_backend = wallet.get_wallet_backend_authority()
        except Exception:
            authoritative_backend = None
        if authoritative_backend not in {"sage", "chia"}:
            return {
                "success": False,
                "error": "Wallet backend authority unavailable",
                "reason": "OFFER_CREATION_AUTHORITY_DENIED",
                "_catalyst_effect_attempted": False,
            }

        # --- V3 Coin Selection Mode ---
        # When coin_ids_enabled=True, we pre-select a specific coin and pass it
        # to the wallet via coin_ids. The wallet locks exactly that coin, so we
        # don't need before/after snapshot polling. ~45x faster for batch creation.
        # If selection fails, we fall back to the V2 polling mode below.
        #
        # Lock protects coin selection so concurrent threads (main loop, sniper,
        # boost) cannot pick the same coin. Released before wallet RPC calls.
        caller_selected_coin_id = selected_coin_id
        use_coin_ids_mode = False

        with self._lock:
            if (
                caller_selected_coin_id
                and spend_wallet_id is not None
                and spend_amount > 0
            ):
                # Check inflight set to prevent sniper/main loop overlap
                if caller_selected_coin_id in self._inflight_coin_ids:
                    log_event(
                        "warning",
                        "coin_ids_locked",
                        f"Coin {caller_selected_coin_id[:16]}... already in-flight, skipping",
                    )
                    return {"success": False, "error": "coin_inflight"}
                selected_coin_id = caller_selected_coin_id
                use_coin_ids_mode = True
                self._inflight_coin_ids.add(selected_coin_id)
                log_event(
                    "debug",
                    "coin_ids_mode",
                    f"Using caller-selected coin: {selected_coin_id[:16]}... "
                    f"for {spend_amount} mojos",
                )
            elif (
                (coin_ids_enabled or authoritative_backend == "sage")
                and spend_wallet_id is not None
                and spend_amount > 0
            ):
                selected_coin_id = self._select_coin_for_offer(
                    spend_wallet_id,
                    spend_amount,
                    used_coins,
                    preferred_tier=preferred_tier,
                    strict_preferred_tier=strict_preferred_tier,
                    exclude_coin_ids=self._inflight_coin_ids,
                )
                if selected_coin_id:
                    use_coin_ids_mode = True
                    self._inflight_coin_ids.add(selected_coin_id)
                    log_event(
                        "debug",
                        "coin_ids_mode",
                        f"Using coin_ids mode: {selected_coin_id[:16]}... "
                        f"for {spend_amount} mojos",
                    )
                elif strict_preferred_tier and preferred_tier:
                    log_event(
                        "info",
                        "coin_ids_no_preferred_tier",
                        f"No {preferred_tier} coin available for {spend_amount} mojos",
                    )
                    return {
                        "success": False,
                        "error": "no_preferred_tier_coin",
                        "preferred_tier": preferred_tier,
                    }
                else:
                    log_event(
                        "debug",
                        "coin_ids_fallback",
                        "Coin selection returned None — falling back to polling mode",
                    )

        if (
            not use_coin_ids_mode
            and spend_wallet_id is not None
            and authoritative_backend == "sage"
        ):
            return {
                "success": False,
                "error": "no_exact_selected_coin",
                "reason": "OFFER_CREATION_EXACT_COIN_REQUIRED",
                "_catalyst_effect_attempted": False,
            }

        # Track which coin was claimed for inflight cleanup
        _inflight_claimed = selected_coin_id if use_coin_ids_mode else None

        if use_coin_ids_mode and selected_coin_id and authoritative_backend == "sage":
            try:
                try:
                    resolved_creation_context = (
                        self._resolve_creation_context_generation(creation_context)
                    )
                except (ValueError, mutation_gate.MutationBlocked):
                    raise
                except Exception:
                    return {
                        "success": False,
                        "error": "Durable offer generation unavailable",
                        "reason": "OFFER_CREATION_AUTHORITY_DENIED",
                        "_catalyst_effect_attempted": False,
                    }
                intent = self._build_canonical_creation_intent(
                    offer_dict=offer_dict,
                    selected_coin_id=selected_coin_id,
                    preferred_tier=preferred_tier,
                    creation_context=resolved_creation_context,
                    expiry_seconds=_expiry,
                    expiry_offset=expiry_offset,
                    stagger_seconds=stagger,
                    offer_max_time=offer_max_time,
                    min_coin_hint=min_coin_hint,
                    max_coin_hint=max_coin_hint,
                )
                return self._create_offer_from_journal(
                    intent=intent,
                    spend_wallet_id=spend_wallet_id,
                )
            except _OfferCreationClaimLost:
                return {
                    "success": False,
                    "error": "Offer creation claim lost",
                    "reason": "OFFER_CREATION_RACE_LOST",
                    "_catalyst_effect_attempted": False,
                    "_catalyst_intent_id": intent.intent_id,
                }
            except mutation_gate.MutationBlocked:
                return {
                    "success": False,
                    "error": "Offer creation authority denied",
                    "reason": "OFFER_CREATION_AUTHORITY_DENIED",
                    "_catalyst_effect_attempted": False,
                }
            except ValueError as exc:
                return {
                    "success": False,
                    "error": str(exc),
                    "reason": "OFFER_CREATION_INTENT_INVALID",
                    "_catalyst_effect_attempted": False,
                }
            finally:
                if _inflight_claimed:
                    with self._lock:
                        self._inflight_coin_ids.discard(_inflight_claimed)

        # --- Before snapshot (V2 polling mode only) ---
        # Only needed when NOT using coin_ids mode.
        # get_spendable_coins_rpc returns {"success": true, "confirmed_records": [...]}
        # Each record has nested "coin" dict: {"parent_coin_info": "...", "amount": N}
        # We use "name" (computed coin ID) if available, else "parent_coin_info"
        before_coin_ids = set()
        if not use_coin_ids_mode and spend_wallet_id is not None:
            try:
                rpc_result = get_exact_spendable_coins_rpc(spend_wallet_id)
                before_coin_ids = self._extract_coin_id_set(rpc_result)
            except Exception as e:
                log_event(
                    "warning",
                    "coin_snapshot_before_fail",
                    f"Could not snapshot coins before offer: {e}",
                )

        # Offers are created with fee=0 so no fee coin is needed.
        # Fee coins are reserved only for coin management transactions
        # (splits, combines) where a non-zero tx fee is actually charged.
        try:
            for attempt in range(max_retries + 1):
                # Pass coin_ids to wallet if we pre-selected a coin
                if use_coin_ids_mode and selected_coin_id:
                    res = create_offer(
                        offer_dict,
                        validate_only=False,
                        max_time=offer_max_time,
                        min_coin_amount=min_coin_hint,
                        max_coin_amount=max_coin_hint,
                        coin_ids=[selected_coin_id],
                    )
                else:
                    res = create_offer(
                        offer_dict,
                        validate_only=False,
                        max_time=offer_max_time,
                        min_coin_amount=min_coin_hint,
                        max_coin_amount=max_coin_hint,
                    )

                if res and res.get("success"):
                    # Include expiry info so caller can record it in DB
                    res["offer_max_time"] = offer_max_time

                    # --- Coin detection: two paths ---
                    if use_coin_ids_mode and selected_coin_id:
                        # PATH 1: coin_ids mode — we know which coin we asked Sage to use.
                        # The ladder path will still verify the wallet's exact offer_id
                        # lock attribution before posting the offer live.
                        res["locked_coin_id"] = selected_coin_id
                        log_event(
                            "debug",
                            "coin_ids_locked",
                            f"coin_ids mode: selected coin {selected_coin_id[:16]}... "
                            f"recorded for post-create verification",
                        )
                    elif before_coin_ids and spend_wallet_id is not None:
                        # PATH 2: V2 polling mode — snapshot before/after to detect lock.
                        # Poll until the wallet confirms the coin is actually locked.
                        # The Chia wallet can be slow to propagate coin locks, especially
                        # for CAT wallets. Without this, the next offer may reuse the
                        # same coin (creating overlapping offers on Dexie).
                        locked_coin = None
                        max_lock_polls = 5  # Up to 5 seconds waiting for lock
                        for poll in range(max_lock_polls):
                            time.sleep(1)
                            try:
                                rpc_result = get_exact_spendable_coins_rpc(
                                    spend_wallet_id
                                )
                                after_coin_ids = self._extract_coin_id_set(rpc_result)
                                missing = before_coin_ids - after_coin_ids
                                if len(missing) >= 1:
                                    # Pick the coin that disappeared
                                    if len(missing) == 1:
                                        locked_coin = missing.pop()
                                    else:
                                        # Multiple coins vanished between snapshots — expected
                                        # during parallel offer creation (other threads locked
                                        # their own coins in the same interval). Downstream
                                        # offer-id lock attribution still verifies the exact
                                        # coin owned by this offer, so picking one arbitrarily
                                        # is safe. Keep at debug to avoid ladder-burst noise.
                                        log_event(
                                            "debug",
                                            "coin_snapshot_multi",
                                            f"Parallel offer creation: {len(missing)} coins "
                                            f"locked between snapshots; picking first",
                                        )
                                        locked_coin = sorted(missing)[0]
                                    break  # Coin is confirmed locked
                            except Exception as e:
                                log_event(
                                    "warning",
                                    "coin_snapshot_poll_fail",
                                    f"Poll {poll + 1}/{max_lock_polls} failed: {e}",
                                )

                        if locked_coin:
                            res["locked_coin_id"] = locked_coin

                            # --- Reuse detection ---
                            # If this coin was already used by a previous offer in this
                            # batch, the wallet didn't properly lock it. Cancel this
                            # duplicate offer and retry after a longer delay.
                            if used_coins and locked_coin in used_coins:
                                trade_record = res.get("trade_record") or {}
                                dup_trade_id = (
                                    res.get("trade_id")
                                    or trade_record.get("trade_id")
                                    or ""
                                )
                                log_event(
                                    "warning",
                                    "coin_reuse_detected",
                                    f"Coin {locked_coin[:16]}... reused! "
                                    f"Cancelling duplicate offer {dup_trade_id[:12]}... "
                                    f"(attempt {attempt + 1}/{max_retries + 1})",
                                )
                                # Route duplicate cleanup through the same
                                # durable cancellation journal as every other
                                # offer cancellation.
                                if dup_trade_id:
                                    try:
                                        self.cancel_offers(
                                            [dup_trade_id],
                                            reason="coin_reuse_detected",
                                            force_storm=True,
                                        )
                                        time.sleep(2)
                                    except Exception as e:
                                        log_event(
                                            "warning",
                                            "coin_reuse_cancel_failed",
                                            f"Could not cancel duplicate offer {dup_trade_id[:16]}...: {e}",
                                        )
                                # Only retry once for reuse — if wallet keeps picking
                                # the same coin, further retries won't help.
                                if attempt < 1:
                                    time.sleep(3)
                                    # Re-snapshot and retry
                                    try:
                                        rpc_result = get_exact_spendable_coins_rpc(
                                            spend_wallet_id
                                        )
                                        before_coin_ids = self._extract_coin_id_set(
                                            rpc_result
                                        )
                                    except Exception as e:
                                        log_event(
                                            "warning",
                                            "coin_resnapshot_failed",
                                            f"Coin re-snapshot after reuse failed: {e}",
                                        )
                                    continue  # Retry this offer once
                                else:
                                    log_event(
                                        "warning",
                                        "coin_reuse_giving_up",
                                        f"Wallet keeps reusing coin {locked_coin[:16]}... "
                                        f"— skipping this offer slot",
                                    )
                                    res["success"] = False
                                    res["error"] = "coin_reuse"
                                    return res
                        else:
                            log_event(
                                "warning",
                                "coin_lock_timeout",
                                f"No coin disappeared after {max_lock_polls}s — "
                                f"wallet may have reused a locked coin",
                            )
                    return res

                # Check for specific error types
                error_msg = str(res.get("error", "")) if res else ""

                # If coin_ids mode failed, fall back to polling mode for retry.
                # The pre-selected coin may have been spent by another transaction.
                if use_coin_ids_mode and attempt < max_retries:
                    if caller_selected_coin_id:
                        log_event(
                            "warning",
                            "coin_ids_failed",
                            f"Caller-selected coin {caller_selected_coin_id[:16]}... "
                            f"failed ({error_msg}) — not falling back to polling "
                            f"mode to avoid overlapping offers",
                        )
                        return res
                    log_event(
                        "warning",
                        "coin_ids_failed",
                        f"coin_ids mode failed ({error_msg}), "
                        f"falling back to polling mode for retry",
                    )
                    use_coin_ids_mode = False
                    selected_coin_id = None
                    # Take a before-snapshot for polling mode
                    if spend_wallet_id is not None:
                        try:
                            rpc_result = get_exact_spendable_coins_rpc(spend_wallet_id)
                            before_coin_ids = self._extract_coin_id_set(rpc_result)
                        except Exception as e:
                            log_event(
                                "warning",
                                "coin_ids_fallback_snapshot_failed",
                                f"Before-snapshot for polling-mode fallback failed: {e}",
                            )
                    time.sleep(2)
                    continue  # Retry in polling mode

                # MEMPOOL_CONFLICT — coin was spent by another transaction.
                # Don't retry with same coins, re-snapshot and try once more.
                if "MEMPOOL_CONFLICT" in error_msg:
                    log_event(
                        "warning",
                        "offer_mempool_conflict",
                        "MEMPOOL_CONFLICT: another tx spent one of the coins we tried to use. "
                        "Re-snapshotting coins...",
                    )
                    if spend_wallet_id is not None and attempt < max_retries:
                        time.sleep(3)
                        try:
                            rpc_result = get_exact_spendable_coins_rpc(spend_wallet_id)
                            before_coin_ids = self._extract_coin_id_set(rpc_result)
                        except Exception as e:
                            log_event(
                                "warning",
                                "mempool_conflict_resnapshot_failed",
                                f"Coin re-snapshot after MEMPOOL_CONFLICT failed: {e}",
                            )
                        continue  # Retry with fresh coin snapshot
                    return res  # Out of retries

                # Insufficient balance — no coins of the right size. Don't retry,
                # the wallet simply doesn't have enough to create this offer.
                if "insufficient balance" in error_msg.lower():
                    log_event(
                        "warning",
                        "offer_insufficient_balance",
                        f"Insufficient coins for offer: {error_msg}",
                    )
                    return res

                if "fully synced" in error_msg and attempt < max_retries:
                    wait_secs = 3 * (attempt + 1)
                    log_event(
                        "warning",
                        "offer_retry",
                        f"Wallet sync error, retrying in {wait_secs}s (attempt {attempt + 1}/{max_retries})",
                    )
                    time.sleep(wait_secs)
                    continue

                # "spendable balance" error with coin hints → hints filtered out all coins.
                # Retry once WITHOUT hints so the wallet can pick any coin it wants.
                if (
                    (
                        "spendable balance" in error_msg
                        or "minimum coin amount" in error_msg.lower()
                    )
                    and (min_coin_hint or max_coin_hint)
                    and attempt < max_retries
                ):
                    log_event(
                        "warning",
                        "offer_hint_retry",
                        f"Coin hints may be too tight (min={min_coin_hint}, max={max_coin_hint}), "
                        f"retrying without hints...",
                    )
                    min_coin_hint = None
                    max_coin_hint = None
                    # Re-snapshot before retry since coins may have changed
                    if spend_wallet_id is not None:
                        try:
                            rpc_result = get_exact_spendable_coins_rpc(spend_wallet_id)
                            before_coin_ids = self._extract_coin_id_set(rpc_result)
                        except Exception as e:
                            log_event(
                                "warning",
                                "hint_retry_snapshot_failed",
                                f"Coin re-snapshot after hint retry failed: {e}",
                            )
                    time.sleep(2)
                    continue

                # Non-retryable error or out of retries.
                # NOTE: log at debug — the calling ladder loop fires
                # `offer_create_failed` with side+index context (and includes
                # this same error string), so re-logging at error level here
                # doubles every failure in the operator log. Keep this as a
                # debug breadcrumb so the raw Sage error is still captured in
                # the structured events table for forensics, but don't count
                # it twice in the visible error stream.
                error_detail = error_msg or "Unknown error"
                log_event(
                    "debug", "offer_failed", f"Offer creation failed: {error_detail}"
                )
                return res

            return None
        finally:
            # Always release the inflight lock regardless of outcome.
            # Prevents coin IDs from being permanently locked in _inflight_coin_ids
            # after the RPC call completes (success, failure, or exception).
            if _inflight_claimed:
                with self._lock:
                    self._inflight_coin_ids.discard(_inflight_claimed)

    def create_ladder(
        self,
        mid_price: Decimal,
        side: str,
        num_offers: int = None,
        trade_size_xch: Decimal = None,
        spread_fraction: Decimal = None,
        cat_asset_id: str = None,
        cat_decimals: int = None,
        cat_wallet_id: int = None,
        risk_manager=None,
        slot_start: int = 0,
        total_slots: int = None,
        coin_ids_enabled: bool = False,
        slot_sequence: List[int] = None,
        price_cap: Decimal = None,
        price_floor: Decimal = None,
        interpolate_refill_prices: bool = True,
        refresh_parent_ids: Dict[int, str] = None,
    ) -> List[Dict]:
        """Create a ladder of offers on one side (buy or sell).

        Places offers at evenly spaced prices from mid_price outward.
        Each offer gets a staggered expiry to avoid mass-expiry cascades.
        If TIER_ENABLED, uses different sizes per tier (inner/mid/outer/extreme).

        Args:
            mid_price: Current mid price in XCH per CAT
            side: 'buy' or 'sell'
            num_offers: Number of offers to create in THIS call
            trade_size_xch: Size per offer in XCH (defaults to config, overridden by tiers)
            spread_fraction: Half-spread as fraction (defaults to config)
            risk_manager: Optional RiskManager for tier sizing
            slot_start: Starting slot index for this batch (used by requote batches)
            total_slots: Total slots in the FULL ladder (for price/tier calculation).
                         When None, defaults to num (the entire ladder in one call).
            coin_ids_enabled: If True, pre-select coins for each offer (V3 fast mode)
            slot_sequence: Optional canonical slot indexes to create. When
                provided, these override slot_start/num sequencing and are used
                for refill/top-up batches so they replenish the intended tiers.
            interpolate_refill_prices: When True, refill batches interpolate
                into the surviving tier's price band. Recovery anchor-drift
                refills set this False so missing slots price from the current
                grid instead of stale surviving offers.
            refresh_parent_ids: Exact durable parent intent keyed by ladder
                slot.  When supplied, creation is a Task 11 child and is
                bound only after its confirmed Sage identity is durable.

        Returns list of created offer details (trade_id, price, size, etc.)
        """
        # Use config defaults
        if slot_sequence is not None:
            slot_sequence = list(slot_sequence)
            num = len(slot_sequence)
        elif side == "buy":
            num = num_offers or cfg.MAX_ACTIVE_BUY_OFFERS
        else:
            num = num_offers or cfg.MAX_ACTIVE_SELL_OFFERS

        # Compute default_size early — it's needed by both the position guard
        # below AND the main offer-creation loop, so define it once here.
        default_size = trade_size_xch or cfg.DEFAULT_TRADE_XCH

        guard = self.check_position_guard(
            side=side,
            mid_price=mid_price,
            num=num,
            slot_start=slot_start,
            total_slots=total_slots if total_slots is not None else num,
            slot_sequence=slot_sequence,
            risk_manager=risk_manager,
            default_size=default_size,
            cat_asset_id=cat_asset_id,
            log_block=True,
            record_pause=True,
        )
        if guard.get("blocked"):
            return []

        # F25 (2026-04-08): position rebalance hard guard.
        # Risk_manager already enforces MAX_POSITION_XCH as a soft limit
        # via spread skew. This is a HARD backstop: if creating these
        # offers would push the bot's position past 110% of the
        # configured max position (a 10% buffer above the soft limit),
        # refuse the entire batch.
        #
        # The directional logic:
        #   - net_position > 0  → bot is LONG CAT
        #   - Each BUY offer (if filled) → MORE long  → +size_xch worth of CAT
        #   - Each SELL offer (if filled) → LESS long → -size_xch worth of CAT
        #
        # If we're already long and trying to create buys → check ceiling
        # If we're already short and trying to create sells → check floor
        # The opposite direction is always safe (it reduces position).
        if risk_manager is not None:
            try:
                max_pos_xch = Decimal(str(getattr(cfg, "MAX_POSITION_XCH", "5") or "5"))
                hard_pos_xch = max_pos_xch * Decimal("1.1")
                # net_position is in CAT — convert to XCH equivalent
                net_pos_cat = Decimal(str(risk_manager._net_position_cat))
                if mid_price > 0:
                    net_pos_xch = abs(net_pos_cat) * mid_price
                else:
                    net_pos_xch = Decimal("0")
                # Project the position INCREASE if all these offers fill.
                # Use the REAL tier-summed ladder value when tiered sizing is
                # on (the old `default_size × num` proxy over- or under-counts
                # depending on which tier DEFAULT_TRADE_XCH lands on, and that
                # drift was making the guard fire on legitimate ladders).
                projected_increase_xch = self._estimate_ladder_worst_case_xch(
                    side=side,
                    num=num,
                    slot_start=slot_start,
                    total_slots=total_slots if total_slots is not None else num,
                    slot_sequence=slot_sequence,
                    risk_manager=risk_manager,
                    default_size=default_size,
                )

                # Self-heal: if MAX_POSITION_XCH was set too low relative to
                # the designed ladder (e.g. smart-defaults ran before the
                # consistency clamp existed, or operator set it manually),
                # the guard would block every ladder creation forever. Detect
                # that case at net_pos≈0 and raise the session hard limit to
                # the designed ladder + 5%. Log once per side. Smart Settings
                # now emits a consistent MAX_POSITION_XCH so this only kicks
                # in for legacy configs.
                if (
                    projected_increase_xch > hard_pos_xch
                    and max_pos_xch > 0
                    and net_pos_xch < max_pos_xch * Decimal("0.05")
                ):
                    _healed = projected_increase_xch * Decimal("1.05")
                    if _healed > hard_pos_xch:
                        if not getattr(self, "_max_pos_warned", False):
                            log_event(
                                "warning",
                                "max_position_auto_raised",
                                f"MAX_POSITION_XCH={max_pos_xch} XCH is inconsistent "
                                f"with the configured ladder "
                                f"(side={side}, num={num}, designed worst-case "
                                f"{projected_increase_xch:.4f} XCH > hard limit "
                                f"{hard_pos_xch:.4f} XCH). Session hard limit "
                                f"auto-raised to {_healed:.4f} XCH so the bot "
                                f"can operate. Re-run Smart Settings to persist "
                                f"a consistent MAX_POSITION_XCH.",
                            )
                            self._max_pos_warned = True
                        hard_pos_xch = _healed

                # F69 (2026-04-17): net out already-open same-side exposure.
                # A REQUOTE (or top-up of an existing ladder) cancels N existing
                # offers and recreates them at a new price. The new exposure is
                # not ADDED on top of the old — it REPLACES it. Without this
                # subtraction, a legitimate requote during a market move hits
                # the hard guard because "current_position + full_new_ladder >
                # limit", even though the real delta is zero. See emergency
                # requote at 2026-04-17 01:34:10 which blocked 22/24 sell
                # replacements during a 2.6% price shock.
                #
                # We subtract the XCH value of currently-open same-side offers
                # from the projected increase. This is the "delta exposure"
                # the new creation actually adds above the existing ladder.
                same_side_open_xch = Decimal("0")
                try:
                    from database import get_open_offers as _gopen

                    _existing = _gopen(
                        side=side, cat_asset_id=cat_asset_id or cfg.CAT_ASSET_ID
                    )
                    for _off in _existing or []:
                        _sz = _off.get("size_xch") or _off.get("size_xch_mojos")
                        if _sz is None:
                            continue
                        try:
                            # size_xch may be stored as XCH float or mojos int —
                            # prefer the column name we just read. size_xch is
                            # the canonical XCH-unit column in this schema.
                            if isinstance(_sz, (int,)) and _sz > 1_000_000_000:
                                # mojos
                                same_side_open_xch += Decimal(_sz) / Decimal(
                                    "1000000000000"
                                )
                            else:
                                same_side_open_xch += Decimal(str(_sz))
                        except Exception:
                            continue
                except Exception:
                    # Fail open — if we can't read the existing exposure, fall
                    # back to the pre-F69 behaviour. Worse: block a legit
                    # requote. Better than: allow unbounded growth.
                    same_side_open_xch = Decimal("0")

                net_new_exposure_xch = projected_increase_xch - same_side_open_xch
                if net_new_exposure_xch < 0:
                    net_new_exposure_xch = Decimal("0")

                # Only block if we're adding to the position in the wrong direction
                add_long_dir = (side == "buy" and net_pos_cat >= 0) or (
                    side == "sell" and net_pos_cat <= 0
                )
                if (
                    add_long_dir
                    and net_pos_xch + net_new_exposure_xch > hard_pos_xch
                    and max_pos_xch > 0
                ):
                    _now = time.time()
                    _last = self._position_guard_logged_at.get(side, 0.0)
                    _should_log = (_now - _last) >= self._position_guard_log_cooldown
                    if _should_log:
                        self._position_guard_logged_at[side] = _now
                        log_event(
                            "warning",
                            "position_hard_guard_blocked",
                            f"BLOCKED ladder creation: side={side}, num={num}, "
                            f"size={default_size}, current_position={net_pos_xch:.4f} XCH "
                            f"(net {net_pos_cat:+.0f} CAT), full-ladder value "
                            f"{projected_increase_xch:.4f} XCH, already-open same-side "
                            f"{same_side_open_xch:.4f} XCH, net new exposure "
                            f"{net_new_exposure_xch:.4f} XCH → projected "
                            f"{(net_pos_xch + net_new_exposure_xch):.4f} XCH > "
                            f"hard limit {hard_pos_xch:.4f} XCH (110% of "
                            f"MAX_POSITION_XCH={max_pos_xch}). Allow position to "
                            f"unwind via the opposite side first. "
                            f"(suppressing duplicates for {int(self._position_guard_log_cooldown)}s)",
                        )
                    return []
            except Exception as _pg_err:
                # Fail-open: never block trading on a guard bug
                log_event(
                    "debug",
                    "position_hard_guard_failed",
                    f"Position rebalance guard check failed (proceeding): {_pg_err}",
                )

        # total_slots = the full ladder size (for price spacing and tier classification)
        # When called normally: total_slots == num (full ladder in one call)
        # When called from requote: total_slots = 40 but num = 5 (one batch)
        if total_slots is None:
            total_slots = num

        half_spread = spread_fraction or cfg.get_spread_fraction() / Decimal("2")
        asset_id = cat_asset_id or cfg.CAT_ASSET_ID
        decimals = cat_decimals or cfg.CAT_DECIMALS
        wallet_cat = cat_wallet_id or cfg.CAT_WALLET_ID

        created = []
        used_coin_ids = set()  # Track coins locked by this batch to detect reuse
        used_size_keys_by_tier = {}
        existing_size_counts_by_tier = {}
        used_requested_amounts = set()
        exact_tier_spend_mode = bool(cfg.TIER_ENABLED and coin_ids_enabled)
        prep_headroom_pct = Decimal(str(getattr(cfg, "COIN_PREP_HEADROOM_PCT", "0")))
        align_live_offer_to_selected_coin = (
            exact_tier_spend_mode and prep_headroom_pct <= Decimal("0")
        )

        # Snapshot of surviving same-side offers' PRICES grouped by DB tier.
        # Consumed by `_interpolate_refill_price` so that refill slots land
        # INSIDE the existing tier's price band rather than at a fresh
        # grid position anchored on a mid that has drifted. Initial-ladder
        # calls (slot_sequence is None) don't use this — they fall back to
        # the classical `_get_ladder_price` formula. The loop below also
        # populates the size-dedup set that existed previously.
        existing_prices_by_tier: Dict[str, List[Decimal]] = {}
        try:
            for open_offer in get_open_offers(side=side, cat_asset_id=asset_id):
                tier_name = (open_offer.get("tier") or "mid").lower()
                raw_size = open_offer.get("size_xch")
                if raw_size is not None:
                    try:
                        size_key = self._size_key(Decimal(str(raw_size)))
                        used_size_keys_by_tier.setdefault(tier_name, set()).add(
                            size_key
                        )
                    except Exception:
                        pass
                # Price capture — skip non-ladder tiers (sniper/fees/reserve
                # aren't part of the main book and shouldn't anchor refills).
                if tier_name in ("sniper", "fees", "reserve"):
                    continue
                raw_price = open_offer.get("price_xch") or open_offer.get("price")
                if raw_price is None:
                    continue
                try:
                    p = Decimal(str(raw_price))
                    if p > 0:
                        existing_prices_by_tier.setdefault(tier_name, []).append(p)
                except Exception:
                    continue
            existing_size_counts_by_tier = {
                tier_name: len(size_keys)
                for tier_name, size_keys in used_size_keys_by_tier.items()
            }
        except Exception as e:
            log_event(
                "debug",
                "offer_size_snapshot_fail",
                f"Could not snapshot existing {side} offer sizes: {e}",
            )

        if exact_tier_spend_mode:
            try:
                for open_offer in get_open_offers(side=side, cat_asset_id=asset_id):
                    requested_mojos = self._requested_amount_from_open_offer(
                        open_offer,
                        side,
                        decimals,
                    )
                    if requested_mojos:
                        used_requested_amounts.add(int(requested_mojos))
            except Exception as e:
                log_event(
                    "debug",
                    "offer_requested_snapshot_fail",
                    f"Could not snapshot existing {side} requested amounts: {e}",
                )

        planned_counts_by_tier = {}
        for i in range(num):
            slot = slot_sequence[i] if slot_sequence is not None else (slot_start + i)
            tier = self._classify_tier(slot, total_slots, side=side)
            planned_counts_by_tier[tier] = planned_counts_by_tier.get(tier, 0) + 1

        # ── Phase 1: Pre-compute all offer specs ──────────────────────────
        # Calculate prices, sizes, tiers, and offer dicts for all slots upfront.
        # This is pure math — no RPC calls, instant.
        offer_specs = []
        for i in range(num):
            if self._stop_requested:
                log_event(
                    "info",
                    "ladder_interrupted",
                    f"Ladder creation interrupted by stop signal after "
                    f"{len(offer_specs)}/{num} {side} offers planned",
                )
                break

            slot = slot_sequence[i] if slot_sequence is not None else (slot_start + i)

            # Fix F: skip suspended slots (coin exhaustion self-heal)
            if self.is_slot_suspended(side, slot):
                continue

            # Pricing path:
            #   * Initial-ladder call (slot_sequence is None): classical
            #     grid formula anchored on mid_price.
            #   * Refill call (slot_sequence is not None): interpolate
            #     into the surviving tier band so the new offer lands at
            #     a price consistent with the existing ladder, even if
            #     mid has drifted. Falls back to the grid formula when
            #     the target tier is empty or the surrounding data is
            #     insufficient.
            if (
                interpolate_refill_prices
                and slot_sequence is not None
                and existing_prices_by_tier
            ):
                price = self._interpolate_refill_price(
                    slot,
                    side,
                    total_slots,
                    existing_prices_by_tier,
                    mid_price,
                    half_spread,
                )
                if price is None:
                    price = self._get_ladder_price(
                        slot, side, mid_price, half_spread, total_slots
                    )
                    log_event(
                        "info",
                        "refill_interpolation_fallback",
                        f"{side} refill slot {slot} could not interpolate "
                        f"from surviving tier prices; using current grid price",
                    )
            else:
                price = self._get_ladder_price(
                    slot, side, mid_price, half_spread, total_slots
                )
            price = self._apply_price_bounds(
                price,
                side,
                price_cap=price_cap,
                price_floor=price_floor,
            )
            if price is None or price <= 0:
                continue

            # AMM buffer guard — skip slots that would land inside TibetSwap's
            # arb zone. An offer priced within AMM_BUFFER_BPS of the live AMM
            # price will be swept immediately by the TibetSwap arb bot.
            if self.amm_monitor is not None:
                try:
                    buffer_ok = self.amm_monitor.check_amm_buffer(price, side)
                    if buffer_ok is False:
                        continue  # Inside AMM arb band — skip slot
                except Exception:
                    log_event(
                        "warning",
                        "amm_buffer_error",
                        f"AMM buffer check failed for {side} — skipping slot",
                    )
                    continue  # Fail closed on errors too

            tier = self._classify_tier(slot, total_slots, side=side)
            if cfg.TIER_ENABLED and risk_manager:
                size_xch = risk_manager.get_tier_size(tier, side=side)
            else:
                size_xch = default_size

            # In tiered coin_ids mode we keep the spend side aligned to the
            # prepped tier coin sizes. Even tiny nudges can cause Sage to lock
            # a second helper coin to avoid awkward dust/change.
            if not exact_tier_spend_mode:
                tier_used_sizes = used_size_keys_by_tier.setdefault(tier, set())
                expected_unique_count = existing_size_counts_by_tier.get(
                    tier, 0
                ) + planned_counts_by_tier.get(tier, 0)
                size_xch = self._allocate_unique_size_xch(
                    size_xch,
                    slot,
                    cfg.TIER_ENABLED and risk_manager,
                    tier_used_sizes,
                    max(1, expected_unique_count),
                )

            cat_amount = size_xch / price

            # Sanity: reject astronomically large CAT amounts that would
            # result from near-zero prices slipping through bounds checks.
            max_cat_sanity = size_xch / Decimal("0.0000001")  # 1e-7 XCH floor
            if cat_amount > max_cat_sanity:
                log_event(
                    "warning",
                    "cat_amount_sanity",
                    f"Skipping {side} slot {slot}: cat_amount {cat_amount:.2f} "
                    f"exceeds sanity limit (price {price:.12f} too small)",
                )
                continue

            cat_mojos = cat_to_mojos(cat_amount, decimals)
            cat_amount = mojos_to_cat(cat_mojos, decimals)
            xch_mojos = xch_to_mojos(size_xch)

            if side == "buy":
                offer_dict = {
                    str(cfg.WALLET_ID_XCH): -int(xch_mojos),
                    str(wallet_cat): int(cat_mojos),
                }
            else:
                offer_dict = {
                    str(wallet_cat): -int(cat_mojos),
                    str(cfg.WALLET_ID_XCH): int(xch_mojos),
                }

            offer_specs.append(
                {
                    "i": i,
                    "slot": slot,
                    "price": price,
                    "tier": tier,
                    "size_xch": size_xch,
                    "cat_amount": cat_amount,
                    "offer_dict": offer_dict,
                    "stagger": i,
                }
            )

        if cfg.DRY_RUN:
            for spec in offer_specs:
                log_event(
                    "info",
                    "dry_run",
                    f"[DRY RUN] Would create {side} offer at {spec['price']}",
                )
            return created

        # ── Phase 2: Pre-select coins for all offers ──────────────────────
        # Sequential coin selection — each coin must be unique. Fast (~1ms each).
        # Buy offers spend XCH (wallet 1), sell offers spend CAT (cat wallet).
        if coin_ids_enabled:
            spend_wallet_id = cfg.WALLET_ID_XCH if side == "buy" else wallet_cat
            spendable_records = None
            spendable_amounts = {}
            try:
                rpc_result = get_exact_spendable_coins_rpc(spend_wallet_id)
                if rpc_result and rpc_result.get("success"):
                    spendable_records = (
                        rpc_result.get("confirmed_records")
                        or rpc_result.get("records")
                        or []
                    )
                    for record in spendable_records:
                        coin_id = self._extract_coin_id_set(
                            {"confirmed_records": [record]}
                        )
                        if not coin_id:
                            continue
                        coin_data = record.get("coin", {})
                        try:
                            spendable_amounts[next(iter(coin_id))] = int(
                                coin_data.get("amount", 0)
                            )
                        except Exception:
                            continue
                else:
                    log_event(
                        "warning",
                        "coin_select_snapshot_fail",
                        f"Could not snapshot spendable coins for wallet {spend_wallet_id} "
                        f"before {side} ladder selection",
                    )
            except Exception as e:
                log_event(
                    "warning",
                    "coin_select_snapshot_fail",
                    f"Spendable snapshot failed for wallet {spend_wallet_id}: {e}",
                )

            for spec in offer_specs:
                # Find the spending side (negative amount)
                spec_spend_wallet_id = None
                spend_amount = 0
                for wid, amt in spec["offer_dict"].items():
                    if int(amt) < 0:
                        spec_spend_wallet_id = int(wid)
                        spend_amount = abs(int(amt))
                        break

                # Translate the slot's POSITION tier into the COIN SIZE tier
                # the prepared coin pool actually labels its coins with. Under
                # BUY_LADDER_REVERSED an "extreme position" buy slot needs an
                # inner-sized coin (and so on). Single source of truth: the
                # live BUY_*_TIER_COUNT + BUY_LADDER_REVERSED settings drive
                # both prep and selection.
                from coin_manager import coin_size_tier_for_slot_position as _coin_tier

                coin_size_pref = _coin_tier(spec["tier"], side=side)

                # In exact_tier_spend_mode, cap the coin size so we never use
                # a wildly oversized coin (e.g. 5 XCH for a 0.634 XCH offer).
                # When no coin fits within the cap, return None → clean slot
                # failure → slot suspension → topup splits the reserve.
                _max_coin = None
                if exact_tier_spend_mode:
                    _ratio = float(getattr(cfg, "COIN_MAX_SIZE_RATIO", "1.5"))
                    if _ratio > 0:
                        _max_coin = int(spend_amount * _ratio)

                # F70 — pass tier sizes so the selector can do strict SSOT
                # misfit rejection via classify_coin(). Without this, the
                # selector would accept coins that are below inner's 0.98
                # floor even though reconcile (post-fix) would classify
                # them as UNKNOWN.
                _tier_sizes_mojos_for_select = None
                try:
                    from coin_manager import get_tier_sizes_mojos_from_cfg as _gt_mojos

                    _tier_sizes_mojos_for_select = _gt_mojos(is_cat=(side == "sell"))
                except Exception:
                    _tier_sizes_mojos_for_select = None

                coin_id = self._select_coin_for_offer(
                    spec_spend_wallet_id or spend_wallet_id,
                    spend_amount,
                    used_coin_ids,
                    preferred_tier=coin_size_pref,
                    strict_preferred_tier=exact_tier_spend_mode,
                    spendable_records=spendable_records,
                    max_amount_mojos=_max_coin,
                    tier_sizes_mojos=_tier_sizes_mojos_for_select,
                )
                spec["coin_id"] = coin_id
                if coin_id:
                    spec["selected_coin_amount"] = spendable_amounts.get(coin_id)
                    used_coin_ids.add(coin_id)
                    if align_live_offer_to_selected_coin:
                        selected_amount = spec.get("selected_coin_amount")
                        if selected_amount:
                            if side == "buy":
                                exact_size_xch = mojos_to_xch(int(selected_amount))
                                exact_cat_amount = exact_size_xch / spec["price"]
                                exact_cat_mojos = cat_to_mojos(
                                    exact_cat_amount, decimals
                                )
                                spec["size_xch"] = exact_size_xch
                                spec["cat_amount"] = mojos_to_cat(
                                    exact_cat_mojos, decimals
                                )
                                spec["offer_dict"] = {
                                    str(cfg.WALLET_ID_XCH): -int(selected_amount),
                                    str(wallet_cat): int(exact_cat_mojos),
                                }
                            else:
                                exact_cat_amount = mojos_to_cat(
                                    int(selected_amount), decimals
                                )
                                exact_xch_mojos = xch_to_mojos(
                                    exact_cat_amount * spec["price"]
                                )
                                spec["size_xch"] = mojos_to_xch(exact_xch_mojos)
                                spec["cat_amount"] = exact_cat_amount
                                spec["offer_dict"] = {
                                    str(wallet_cat): -int(selected_amount),
                                    str(cfg.WALLET_ID_XCH): int(exact_xch_mojos),
                                }

        # ── Phase 3: Create all offers in parallel ────────────────────────
        # Fire up to 5 concurrent make_offer RPC calls. Each has its own
        # pre-selected coin_id so there's no contention.
        if coin_ids_enabled and exact_tier_spend_mode:
            for spec in offer_specs:
                if not spec.get("coin_id"):
                    continue
                if side == "buy":
                    spend_xch_mojos = abs(
                        int(spec["offer_dict"][str(cfg.WALLET_ID_XCH)])
                    )
                    requested_cat_mojos = int(spec["offer_dict"][str(wallet_cat)])
                    unique_requested_cat_mojos = self._allocate_unique_requested_mojos(
                        requested_cat_mojos,
                        spec["slot"],
                        used_requested_amounts,
                    )
                    spec["size_xch"] = mojos_to_xch(spend_xch_mojos)
                    spec["cat_amount"] = mojos_to_cat(
                        unique_requested_cat_mojos, decimals
                    )
                    if spec["cat_amount"] > 0:
                        spec["price"] = spec["size_xch"] / spec["cat_amount"]
                    spec["offer_dict"] = {
                        str(cfg.WALLET_ID_XCH): -int(spend_xch_mojos),
                        str(wallet_cat): int(unique_requested_cat_mojos),
                    }
                else:
                    spend_cat_mojos = abs(int(spec["offer_dict"][str(wallet_cat)]))
                    requested_xch_mojos = int(
                        spec["offer_dict"][str(cfg.WALLET_ID_XCH)]
                    )
                    unique_requested_xch_mojos = self._allocate_unique_requested_mojos(
                        requested_xch_mojos,
                        spec["slot"],
                        used_requested_amounts,
                    )
                    spec["size_xch"] = mojos_to_xch(unique_requested_xch_mojos)
                    spec["cat_amount"] = mojos_to_cat(spend_cat_mojos, decimals)
                    if spec["cat_amount"] > 0:
                        spec["price"] = spec["size_xch"] / spec["cat_amount"]
                    spec["offer_dict"] = {
                        str(wallet_cat): -int(spend_cat_mojos),
                        str(cfg.WALLET_ID_XCH): int(unique_requested_xch_mojos),
                    }

        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading as _threading

        # During requote batches (small num_offers from rolling wave), use
        # serial creation.  Parallel creation with Sage can cause
        # BAD_AGGREGATE_SIGNATURE when multiple concurrent make_offer RPCs
        # contend for the same fee coin.  Full ladder creates (startup/cold)
        # still benefit from parallelism since they run before any cancels.
        _is_requote_batch = refresh_parent_ids is not None or (
            num is not None and num < total_slots
        )
        if _is_requote_batch:
            max_parallel = 1
        else:
            max_parallel = self._get_ladder_parallelism(coin_ids_enabled)
        _results_lock = _threading.Lock()
        _used_coins_lock = _threading.Lock()
        _results_map = {}  # {i: res}

        def _create_one(spec):
            """Create a single offer (runs in thread pool)."""
            if coin_ids_enabled and not spec.get("coin_id"):
                # Pre-selection returned no coin. In exact tier mode, never
                # let Sage auto-select a fallback coin: it can pick a reserve
                # or wrong-sized tier coin and pin the topup pool behind a
                # tiny offer. Skip the slot so topup/coin-prep can repair it.
                if exact_tier_spend_mode or max_parallel != 1:
                    msg = (
                        f"No unique pre-selected coin available for {side} "
                        f"slot {spec['slot']} — skipping to avoid overlap"
                    )
                    log_event("debug", "coin_select_skip", msg)
                    # Fix F: track consecutive failures for this slot
                    self.record_slot_coin_failure(side, spec["slot"])
                    return spec["i"], {
                        "success": False,
                        "error": "no_unique_coin_preselected",
                    }
                # Serial non-tier mode: proceed without pre-selection.
                log_event(
                    "debug",
                    "coin_select_skip_serial_fallback",
                    f"No pre-selected coin for {side} slot {spec['slot']} "
                    f"— serial mode, letting Sage pick from wallet",
                )

            parent_intent_id = (
                refresh_parent_ids.get(int(spec["slot"]))
                if refresh_parent_ids is not None
                else None
            )
            res = self.create_offer_with_retry(
                spec["offer_dict"],
                expiry_offset=spec["stagger"],
                used_coins=used_coin_ids,
                coin_ids_enabled=coin_ids_enabled,
                selected_coin_id=spec.get("coin_id"),
                preferred_tier=spec["tier"],
                creation_context={
                    "slot_key": f"ladder:{asset_id}:{side}:{spec['slot']}",
                    "select_next_generation": True,
                    "asset_id": asset_id,
                    "side": side,
                    "tier": spec["tier"],
                    "purpose": "normal_lifecycle",
                    "parent_intent_id": parent_intent_id,
                    "offer_size_uniqueness": {
                        "slot": spec["slot"],
                        "requested_amount_atomic": str(
                            next(
                                int(amount)
                                for amount in spec["offer_dict"].values()
                                if int(amount) > 0
                            )
                        ),
                    },
                },
            )
            if parent_intent_id is not None and res and res.get("success"):
                child_intent_id = res.get("_catalyst_intent_id")
                if type(child_intent_id) is not str or not child_intent_id:
                    self._trip_refresh_lineage_latch(
                        operation_id=f"refresh-lineage:{parent_intent_id}:child-identity",
                        parent=database.get_offer_intent(parent_intent_id),
                    )
                    return spec["i"], {
                        "success": False,
                        "error": "refresh_child_identity_missing",
                    }
                try:
                    database.bind_refresh_lineage(parent_intent_id, child_intent_id)
                except Exception:
                    self._trip_refresh_lineage_latch(
                        operation_id=f"refresh-lineage:{parent_intent_id}:bind",
                        parent=database.get_offer_intent(parent_intent_id),
                    )
                    return spec["i"], {
                        "success": False,
                        "error": "refresh_lineage_bind_failed",
                    }
            if res and res.get("success"):
                locked_coin_id = res.get("locked_coin_id")
                if locked_coin_id:
                    with _used_coins_lock:
                        used_coin_ids.add(locked_coin_id)
                        self._cycle_used_coin_ids.add(locked_coin_id)
                # Fix F: clear failure counter on successful creation
                self.clear_slot_failure(side, spec["slot"])
            try:
                delay_ms = int(getattr(cfg, "LADDER_CREATE_DELAY_MS", 0) or 0)
            except Exception:
                delay_ms = 0
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
            return spec["i"], res

        log_event(
            "info",
            "ladder_parallel",
            f"Creating {len(offer_specs)} {side} offers with {max_parallel} parallel workers",
        )
        _ladder_start = time.time()

        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            futures = [executor.submit(_create_one, spec) for spec in offer_specs]
            for f in as_completed(futures):
                try:
                    idx, res = f.result()
                    with _results_lock:
                        _results_map[idx] = res
                except Exception as e:
                    log_event("warning", "parallel_offer_error", f"Thread error: {e}")

        _ladder_elapsed = time.time() - _ladder_start
        log_event(
            "info",
            "ladder_parallel_done",
            f"{len(offer_specs)} {side} offers fired in {_ladder_elapsed:.1f}s",
        )

        # ── Phase 4: Process results (sequential — DB writes) ─────────────
        for spec in offer_specs:
            i = spec["i"]
            res = _results_map.get(i)
            price = spec["price"]
            tier = spec["tier"]
            size_xch = spec["size_xch"]
            cat_amount = spec["cat_amount"]
            slot = spec["slot"]

            if not res or not res.get("success"):
                error_msg = str(res.get("error", "")) if res else ""
                fail_msg = f"Offer #{i + 1}/{num} {side} FAILED: {error_msg[:100]}"
                # Coin exhaustion is an expected operational state (not a code
                # defect) — already tracked by record_slot_coin_failure /
                # slot_suspended, so downgrade to debug to avoid log spam.
                _fail_level = (
                    "debug" if error_msg == "no_unique_coin_preselected" else "error"
                )
                if _fail_level != "debug":
                    print(f"  ❌ {fail_msg}", flush=True)
                log_event(_fail_level, "offer_create_failed", fail_msg)
                continue

            trade_record = res.get("trade_record") or {}
            trade_id = res.get("trade_id") or trade_record.get("trade_id") or ""

            if not trade_id:
                continue

            parent_intent_id = (
                refresh_parent_ids.get(int(slot))
                if refresh_parent_ids is not None
                else None
            )
            child_intent_id = res.get("_catalyst_intent_id")
            if parent_intent_id is not None:
                if type(child_intent_id) is not str or not child_intent_id:
                    self._trip_refresh_lineage_latch(
                        operation_id=f"refresh-lineage:{parent_intent_id}:child-identity",
                        parent=database.get_offer_intent(parent_intent_id),
                    )
                    log_event(
                        "error",
                        "refresh_child_identity_missing",
                        "Confirmed refresh child did not return its durable intent ID",
                    )
                    continue
                try:
                    database.bind_refresh_lineage(parent_intent_id, child_intent_id)
                except Exception as exc:
                    # The child is durable and remains a recovery boundary;
                    # do not cancel the parent when the reverse edge is not.
                    self._trip_refresh_lineage_latch(
                        operation_id=f"refresh-lineage:{parent_intent_id}:bind",
                        parent=database.get_offer_intent(parent_intent_id),
                    )
                    log_event(
                        "error",
                        "refresh_lineage_bind_failed",
                        f"Held parent cancellation after child creation: {exc}",
                    )
                    continue

            locked_coin_id = res.get("locked_coin_id")
            verified_locked_coin_ids = []
            if coin_ids_enabled and locked_coin_id and get_wallet_type() == "sage":
                spend_wallet_id = None
                for wid, amt in spec["offer_dict"].items():
                    if int(amt) < 0:
                        spend_wallet_id = int(wid)
                        break

                verification = self._verify_sage_offer_locked_inputs(
                    spend_wallet_id,
                    trade_id,
                    locked_coin_id,
                )
                if verification.get("verified"):
                    verified_locked_coin_ids = verification.get("locked_coin_ids") or []
                    selected_present = verification.get("selected_present", False)
                    if len(verified_locked_coin_ids) > 1 or not selected_present:
                        log_event(
                            "info",
                            "coin_ids_overlap_observed",
                            f"Sage locked {len(verified_locked_coin_ids)} inputs for "
                            f"{trade_id[:12]}... "
                            f"({', '.join(cid[:14] + '...' for cid in verified_locked_coin_ids)}) "
                            f"while selected={locked_coin_id[:14]}...",
                        )

            locked_preview = locked_coin_id[:16] if locked_coin_id else "none"
            ok_msg = (
                f"Offer #{i + 1}/{num} {side} @ {price:.8f} | "
                f"size={float(size_xch):.4f} XCH | "
                f"trade_id={trade_id[:16]}... | coin={locked_preview}"
            )
            print(f"  ✅ {ok_msg}", flush=True)
            log_event("success", "offer_created", ok_msg)

            # DB: record offer
            _omt = res.get("offer_max_time", 0)
            if _omt and int(_omt) > 0:
                from datetime import datetime, timezone

                expires_at = datetime.fromtimestamp(
                    int(_omt), tz=timezone.utc
                ).isoformat()
            else:
                expires_at = None

            # Select the coin_id to store in the DB.
            # When Sage bundles both the trade coin and the fee coin as maker
            # inputs, `verified_locked_coin_ids` contains both (sorted by hash).
            # Always prefer the pre-selected trade coin (`locked_coin_id`) when
            # it appears in the verified list — this prevents the fee coin from
            # being recorded as the offer's trade coin (bug: fee-coin backed offers).
            if verified_locked_coin_ids:
                normalized_locked_coin_id = self._normalize_coin_ref(locked_coin_id)
                normalized_verified_coin_ids = {
                    self._normalize_coin_ref(coin_id)
                    for coin_id in verified_locked_coin_ids
                }
                if (
                    normalized_locked_coin_id
                    and normalized_locked_coin_id in normalized_verified_coin_ids
                ):
                    db_coin_id = locked_coin_id  # pre-selected trade coin confirmed ✓
                else:
                    # Pre-selected coin not verified (Sage used different coin).
                    # Use whatever Sage locked — and log a warning so we can track.
                    db_coin_id = verified_locked_coin_ids[0]
                    if locked_coin_id:
                        log_event(
                            "warning",
                            "trade_coin_not_verified",
                            f"Pre-selected coin {locked_coin_id[:16]}... was NOT found in "
                            f"Sage's locked inputs for {trade_id[:12]}... "
                            f"(Sage locked: {', '.join(c[:14] + '...' for c in verified_locked_coin_ids[:3])}). "
                            f"Offer may use an unexpected coin.",
                        )
            else:
                db_coin_id = locked_coin_id
            db_ok = add_offer(
                trade_id=trade_id,
                side=side,
                price_xch=price,
                size_xch=size_xch,
                size_cat=cat_amount,
                cat_asset_id=asset_id,
                tier=tier,
                expires_at=expires_at,
                coin_id=db_coin_id,
            )
            if not db_ok:
                # DB insert failed — cancel on-chain offer to prevent wallet/DB
                # divergence (offer exists in wallet but isn't tracked).
                log_event(
                    "error",
                    "ladder_db_cancel",
                    f"DB insert failed for {trade_id[:16]}..., cancelling on-chain offer",
                )
                try:
                    self.cancel_offers([trade_id], reason="db_insert_failed")
                except Exception:
                    pass
                continue

            lock_targets = verified_locked_coin_ids or (
                [locked_coin_id] if locked_coin_id else []
            )
            for coin_id in lock_targets:
                used_coin_ids.add(coin_id)
                self._cycle_used_coin_ids.add(coin_id)
                try:
                    lock_coin(coin_id, trade_id)
                except Exception as e:
                    log_event(
                        "warning",
                        "coin_lock_failed",
                        f"DB coin lock failed for coin {coin_id[:16] if coin_id else 'unknown'}... "
                        f"(offer {trade_id[:16] if trade_id else '?'}...): {e}",
                    )

            # Cache for fill tracking
            offer_detail = {
                "trade_id": trade_id,
                "side": side,
                "price": price,
                "size_xch": size_xch,
                "size_cat": cat_amount,
                "tier": tier,
                "slot": slot,
                "coin_id": locked_coin_id,
            }
            if verified_locked_coin_ids:
                offer_detail["locked_coin_ids"] = verified_locked_coin_ids

            # Get bech32 for Dexie posting
            offer_bech32 = res.get("offer") or ""
            if not offer_bech32:
                offer_bech32 = get_offer_bech32(trade_id) or ""
            if offer_bech32:
                offer_detail["offer_bech32"] = offer_bech32
                update_offer_bech32(trade_id, offer_bech32)

            self._offer_details_cache[trade_id] = offer_detail
            self._recently_created[trade_id] = time.time()
            created.append(offer_detail)

        return created

    def _estimate_ladder_worst_case_xch(
        self,
        side: str,
        num: int,
        slot_start: int,
        total_slots: int,
        slot_sequence: Optional[List[int]],
        risk_manager,
        default_size: Optional[Decimal],
    ) -> Decimal:
        """Sum of per-slot tier sizes for the slots this call will create.

        Used by the F25 position hard guard to decide whether the full
        ladder, if all filled, would exceed MAX_POSITION_XCH × 1.1. The
        prior implementation used `default_size × num` which silently
        under- or over-counted depending on which tier DEFAULT_TRADE_XCH
        happened to map to — with reverse-buy on, that drifted enough
        to block legitimate initial ladders. Summing the actual tier
        sizes each slot will use eliminates the drift.

        Falls back to `default_size × num` when tiered sizing is off or
        the tier-size lookup fails, so the guard never becomes blind.
        """
        fallback = (default_size or Decimal("0")) * Decimal(num)
        if not cfg.TIER_ENABLED or risk_manager is None:
            return fallback
        total = Decimal("0")
        for i in range(num):
            if slot_sequence is not None:
                slot = slot_sequence[i]
            else:
                slot = slot_start + i
            tier = self._classify_tier(slot, total_slots, side=side)
            try:
                sz = risk_manager.get_tier_size(tier, side=side)
            except Exception:
                sz = default_size or Decimal("0")
            if sz is None:
                sz = default_size or Decimal("0")
            try:
                total += Decimal(str(sz))
            except Exception:
                total += default_size or Decimal("0")
        return total if total > 0 else fallback

    def _get_ladder_price(
        self,
        slot: int,
        side: str,
        mid_price: Decimal,
        half_spread: Decimal,
        max_offers: int,
    ) -> Optional[Decimal]:
        """Calculate the price for a specific ladder slot.

        Arithmetic ladder: steady increase from tight (near mid) to wide.
        Slot 0 (inner) starts at MIN_EDGE_BPS from mid.
        Slot N-1 (extreme) reaches the full adjusted half_spread.

        This creates a smooth orderbook: tight offers near mid price
        (where most fills happen) and wider offers at the extremes.
        """
        return ladder_price_for_slot(
            slot,
            side,
            mid_price,
            half_spread,
            max_offers,
            min_edge_bps=getattr(cfg, "MIN_EDGE_BPS", Decimal("0")),
        )

    def _interpolate_refill_price(
        self,
        slot: int,
        side: str,
        total_slots: int,
        existing_prices_by_tier: Dict[str, List[Decimal]],
        mid_price: Decimal,
        half_spread: Decimal,
    ) -> Optional[Decimal]:
        """Price a refill slot by interpolating into the existing ladder.

        When a filled slot gets refilled, the mid price has usually drifted
        since the ladder was built. Pricing the replacement from the live
        mid produces an offer that interleaves with surviving offers at
        their original prices, scrambling the tier ordering on Dexie and
        tripping the ladder-taper watchdog.

        This helper anchors refills to the tier they belong to:

        * **≥2 surviving same-tier offers** → interpolate between the
          tier's closest-to-mid and furthest-from-mid prices, by the
          slot's rank-within-tier. New offers slot into the gap in the
          tier's existing price band.
        * **Exactly 1 surviving same-tier offer** → use it as one anchor
          and the adjacent tier's boundary as the other. If no neighbour
          is usable, fall back to the live-mid grid price.
        * **0 survivors in the target tier** → fall back to
          ``_get_ladder_price`` anchored on ``mid_price``. The refill
          repopulates the empty tier from scratch at the current market.

        Sanity guard: if the interpolated price falls outside
        ``mid × (1 ± MAX_SPREAD_BPS/10000)`` returns None so the caller
        skips the slot. The graduated-requote path will rebuild the
        whole ladder when drift is that large — patching would produce
        economically bad offers.
        """
        target_tier = self._classify_tier(slot, total_slots, side=side)

        # Build this side's tier-count map so we can compute rank-within-tier.
        tier_order = ("inner", "mid", "outer", "extreme")
        prefix = "BUY_" if (side or "").lower() == "buy" else "SELL_"
        tier_sizes = {
            t: int(getattr(cfg, f"{prefix}{t.upper()}_TIER_COUNT", 0) or 0)
            for t in tier_order
        }
        if sum(tier_sizes.values()) == 0:
            # Legacy shared counts (pre-F62).
            tier_sizes = {
                t: int(getattr(cfg, f"{t.upper()}_TIER_COUNT", 0) or 0)
                for t in tier_order
            }

        tier_size = tier_sizes.get(target_tier, 0)
        if tier_size <= 0:
            # No tier structure configured → no sensible interpolation.
            return self._get_ladder_price(
                slot, side, mid_price, half_spread, total_slots
            )

        # Rank-within-tier is slot minus the total slots in prior tiers.
        rank_within_tier = slot
        for t in tier_order:
            if t == target_tier:
                break
            rank_within_tier -= tier_sizes.get(t, 0)
        if rank_within_tier < 0 or rank_within_tier >= tier_size:
            # Inconsistency — safer to fall back than extrapolate.
            return self._get_ladder_price(
                slot, side, mid_price, half_spread, total_slots
            )

        # Sort prices by distance-from-mid. Buy side: closest-to-mid is
        # HIGHEST price (just below mid). Sell side: closest-to-mid is
        # LOWEST price (just above mid).
        def _dist_key(p: Decimal) -> Decimal:
            return -p if (side or "").lower() == "buy" else p

        same_tier_prices = existing_prices_by_tier.get(target_tier) or []
        sorted_tier = sorted(same_tier_prices, key=_dist_key)

        # Locate adjacent tiers so a lone survivor can still interpolate.
        prev_tier = None
        next_tier = None
        for i, t in enumerate(tier_order):
            if t == target_tier:
                if i > 0:
                    prev_tier = tier_order[i - 1]
                if i < len(tier_order) - 1:
                    next_tier = tier_order[i + 1]
                break

        inner_anchor: Optional[Decimal] = None
        outer_anchor: Optional[Decimal] = None

        if len(sorted_tier) >= 2:
            inner_anchor = sorted_tier[0]
            outer_anchor = sorted_tier[-1]
        elif len(sorted_tier) == 1:
            sole = sorted_tier[0]
            prev_prices = (
                sorted(existing_prices_by_tier.get(prev_tier, []), key=_dist_key)
                if prev_tier
                else []
            )
            next_prices = (
                sorted(existing_prices_by_tier.get(next_tier, []), key=_dist_key)
                if next_tier
                else []
            )
            # Use the adjacent-tier boundary on whichever side the survivor
            # doesn't cover. If we have neighbour boundaries on both sides,
            # prefer those as anchors — the sole survivor is already in the
            # band and the interpolation across the full tier width is
            # more accurate.
            if prev_prices:
                inner_anchor = prev_prices[-1]
            else:
                inner_anchor = sole
            if next_prices:
                outer_anchor = next_prices[0]
            else:
                outer_anchor = sole
            if inner_anchor == outer_anchor:
                # Both fell back to the sole survivor → can't interpolate.
                return self._get_ladder_price(
                    slot, side, mid_price, half_spread, total_slots
                )
        else:
            # Empty tier → fresh grid price anchored on current mid.
            return self._get_ladder_price(
                slot, side, mid_price, half_spread, total_slots
            )

        if inner_anchor is None or outer_anchor is None:
            return self._get_ladder_price(
                slot, side, mid_price, half_spread, total_slots
            )

        # Linear interpolation by rank-within-tier. Formula is side-agnostic
        # because `sorted_tier` is always [closest, …, furthest] regardless
        # of which direction "closest" means numerically.
        denom = Decimal(max(1, tier_size - 1))
        fraction = Decimal(rank_within_tier) / denom
        inner_d = Decimal(str(inner_anchor))
        outer_d = Decimal(str(outer_anchor))
        price = inner_d + (outer_d - inner_d) * fraction

        if price <= 0:
            return None

        # Economic sanity guard — reject prices outside MAX_SPREAD_BPS of
        # mid. A stale tier + big mid move can produce interpolated prices
        # well off the current market. Returning None skips this slot;
        # the graduated-requote path will catch up when drift is real.
        try:
            max_bps = Decimal(str(getattr(cfg, "MAX_SPREAD_BPS", 2500) or 2500))
            if max_bps > 0:
                offset = max_bps / Decimal("10000")
                lower = mid_price * (Decimal("1") - offset)
                upper = mid_price * (Decimal("1") + offset)
                if price < lower or price > upper:
                    return None
        except Exception:
            # Sanity check is best-effort — never block an otherwise valid
            # refill just because the MAX_SPREAD_BPS config is odd.
            pass

        return price

    def _apply_price_bounds(
        self,
        price: Optional[Decimal],
        side: str,
        price_cap: Decimal = None,
        price_floor: Decimal = None,
    ) -> Optional[Decimal]:
        """Clamp ladder prices so the main book never crosses a surviving probe."""
        if price is None:
            return None

        if side == "buy" and price_cap is not None:
            cap = Decimal(str(price_cap))
            if cap > 0:
                price = min(price, cap)
        if side == "sell" and price_floor is not None:
            floor = Decimal(str(price_floor))
            if floor > 0:
                price = max(price, floor)
        return price

    def _classify_tier(self, slot: int, total: int, side: str = None) -> str:
        """Classify an offer's tier based on its position in the ladder.

        `side` selects per-side BUY_*_TIER_COUNT vs SELL_*_TIER_COUNT keys
        so the buy and sell ladders can have independent tier shapes.
        Falls back to per-tier MAX of both sides if `side` is None — this
        keeps existing call sites that don't yet pass side from breaking.
        """
        if not cfg.TIER_ENABLED:
            return "mid"
        if total <= 0:
            return "mid"

        side_norm = (side or "").lower()
        if side_norm == "buy":
            prefix = "BUY_"
        elif side_norm == "sell":
            prefix = "SELL_"
        else:
            prefix = None

        if prefix is None:
            configured = {
                tier: max(
                    int(getattr(cfg, f"BUY_{tier.upper()}_TIER_COUNT", 0) or 0),
                    int(getattr(cfg, f"SELL_{tier.upper()}_TIER_COUNT", 0) or 0),
                )
                for tier in ("inner", "mid", "outer", "extreme")
            }
        else:
            configured = {
                tier: int(getattr(cfg, f"{prefix}{tier.upper()}_TIER_COUNT", 0) or 0)
                for tier in ("inner", "mid", "outer", "extreme")
            }
        return classify_slot_tier(slot, total, tier_counts=configured)

    # -------------------------------------------------------------------
    # Requoting (cancel + recreate when price moves)
    # -------------------------------------------------------------------

    def should_requote(
        self, side: str, current_price: Decimal, last_quoted_price: Decimal
    ) -> bool:
        """Check if offers on this side need requoting.

        Requoting happens when the mid price has moved more than
        REQUOTE_BPS from where we last placed offers.

        Returns True/False for backward compatibility.
        Use should_requote_graduated() for the severity level.
        """
        if not cfg.AUTO_REQUOTE:
            return False

        # Cooldown check
        elapsed = time.time() - self._last_requote_time.get(side, 0)
        if elapsed < cfg.REQUOTE_COOLDOWN_SECS:
            return False

        # Price movement check
        if last_quoted_price <= 0:
            return False

        move_fraction = abs(current_price - last_quoted_price) / last_quoted_price
        requote_fraction = cfg.get_requote_fraction()

        return move_fraction > requote_fraction

    def should_requote_graduated(
        self, side: str, current_price: Decimal, last_quoted_price: Decimal
    ):
        """Like should_requote but returns a RequoteSeverity level.

        Determines HOW MUCH of the book needs adjusting based on
        the magnitude of price drift:
          NONE      — no action (drift < inner threshold)
          INNER     — adjust inner tier only
          INNER_MID — adjust inner + mid tiers
          FULL      — adjust all tiers (still budget-capped)
          EMERGENCY — offers may be arbable, cancel immediately
        """
        from reaction_strategy import RequoteSeverity, classify_drift

        if not cfg.AUTO_REQUOTE:
            return RequoteSeverity.NONE

        # Cooldown check
        elapsed = time.time() - self._last_requote_time.get(side, 0)
        if elapsed < cfg.REQUOTE_COOLDOWN_SECS:
            return RequoteSeverity.NONE

        if last_quoted_price <= 0:
            return RequoteSeverity.NONE

        move_fraction = abs(current_price - last_quoted_price) / last_quoted_price
        return classify_drift(
            move_fraction,
            inner_threshold=getattr(cfg, "REQUOTE_DRIFT_INNER", Decimal("0.003")),
            mid_threshold=getattr(cfg, "REQUOTE_DRIFT_MID", Decimal("0.008")),
            full_threshold=getattr(cfg, "REQUOTE_DRIFT_FULL", Decimal("0.02")),
            emergency_threshold=getattr(
                cfg, "REQUOTE_DRIFT_EMERGENCY", Decimal("0.05")
            ),
        )

    def requote_side(
        self,
        side: str,
        current_price: Decimal,
        dexie_manager=None,
        risk_manager=None,
        spread_fraction: Decimal = None,
        price_cap: Decimal = None,
        price_floor: Decimal = None,
        live_offer_ids: set = None,
        max_offers: int = 0,
        allowed_tiers: set = None,
        force_cancel_storm: bool = False,
    ) -> List[Dict]:
        """Single-pass requote: cancel old offers, then create replacements.

        One pass through:
            1. Count spare coins available for this side
            2. Cancel matching old offers and wait for confirmed removal
            3. Create replacements only for confirmed cancelled slots
            4. Post replacements to Dexie immediately
            5. Return; pending cancels stay open and block replacement
               creation until Sage stops reporting them fillable.

        Args:
            max_offers: If > 0, create/cancel at most this many offers.
                        0 means no limit.
            allowed_tiers: If provided, only target offers in these tiers
                           for replacement (graduated response).

        Returns dict with offers, fully_replaced, replaced_count, target_count.
        """
        del force_cancel_storm
        # NOTE: _last_requote_time is set only when we actually do work (create or cancel).
        # Early returns (no spares, create failed) intentionally leave it unchanged so the
        # next cycle's cooldown check doesn't see a false "just requoted" timestamp and
        # suppress a genuine retry when conditions improve.

        # ── Gather open offers to replace ──
        all_open = get_open_offers(side=side, cat_asset_id=cfg.CAT_ASSET_ID)
        open_offers = [o for o in all_open if o.get("tier") not in ("boost", "sniper")]
        # Wallet omission is diagnostic only.  Durable nonterminal rows remain
        # capacity-owning until Task 9 commits exact terminal proof.
        # Sort most-at-risk first so cancels prioritise the stale-est offers.
        open_offers = self._sort_open_offers_for_requote(
            open_offers, side, mid_price=current_price
        )

        # ── Graduated response: tier filter + budget cap ──
        # Track pre-filter count so the cold-start detection below can tell
        # "this side is truly empty" (do a full rebuild) apart from "the tier
        # filter drained the scope but other tiers are still live" (do
        # nothing — the ladder-fill path will refill the cancelled tier on
        # the next cycle with proper tier-matched coins).
        pre_filter_offer_count = len(open_offers)
        if allowed_tiers:
            _before = len(open_offers)
            open_offers = [
                o
                for o in open_offers
                if str(o.get("tier") or "mid").lower() in allowed_tiers
            ]
            if len(open_offers) < _before:
                log_event(
                    "info",
                    "requote_tier_filter",
                    f"Tier filter ({', '.join(sorted(allowed_tiers))}): "
                    f"{_before} → {len(open_offers)} offers to process",
                )
        # `original_target_count` captures how many offers the requote
        # SHOULD replace before the per-cycle budget cap trims the list.
        # It is returned alongside the truncated target_count so callers
        # can tell the difference between a true full-replace and "we
        # capped at the budget and the rest of the old quotes are still
        # live." Previously only the truncated count was exposed, so a
        # capped FULL requote could report fully_replaced=True while 20+
        # stale offers sat exposed at the old mid until the next cycle.
        original_target_count = len(open_offers)
        if max_offers > 0 and len(open_offers) > max_offers:
            _full = len(open_offers)
            open_offers = open_offers[:max_offers]
            log_event(
                "info",
                "requote_budget_cap",
                f"Budget cap: processing {max_offers} of {_full} offers "
                f"this cycle (rest deferred)",
            )

        target_count = len(open_offers)

        log_event(
            "info",
            "requote_start",
            f"Requote {side}: {target_count} offers to replace, "
            f"new price {current_price:.8f}",
        )

        # ── Tier filter emptied the requote scope, but side is not cold ──
        # Happens after a defensive-cancel clears one tier in the wallet just
        # before this requote runs. Pre-fix behavior: fell through to the
        # cold-start branch below and rebuilt the FULL ladder, colliding with
        # the untouched outer/mid/extreme offers and producing duplicate-offer
        # storms that the trim pass had to clean up (post-mortem 2026-04-22
        # 05:10 cascade). Correct behavior: let the standard ladder-fill path
        # restore the cancelled tier on the next cycle with tier-matched
        # coins.
        if not open_offers and allowed_tiers and pre_filter_offer_count > 0:
            log_event(
                "info",
                "requote_tier_empty_skip",
                f"Tier filter drained requote scope for {side} "
                f"({pre_filter_offer_count} non-matching offers still "
                f"live) — deferring to ladder-fill on next cycle",
            )
            return {
                "offers": [],
                "fully_replaced": False,
                "replaced_count": 0,
                "target_count": 0,
                "original_target_count": 0,
                "tier_filter_drained": True,
            }

        # ── Wallet-truth cold-start guard ──
        # Before the "no offers anywhere" branch triggers a full ladder
        # rebuild, double-check against the wallet snapshot. During the
        # post-mortem cascade, the DB briefly showed zero open offers for a
        # side (cancelled records) while Sage still held live "zombie"
        # offers — a cold-start rebuild at that moment would stack a full
        # ladder on top of the zombies and overshoot the cap. If the
        # wallet says offers are still live, defer; the regular
        # reconcile + ladder-fill paths will catch up on the next cycle.
        if not open_offers and live_offer_ids is not None and len(live_offer_ids) > 0:
            log_event(
                "info",
                "requote_skip_wallet_has_offers",
                f"DB shows {side} empty but wallet still holds "
                f"{len(live_offer_ids)} live offer(s) — deferring "
                f"cold-start rebuild to avoid zombie pile-up",
            )
            return {
                "offers": [],
                "fully_replaced": False,
                "replaced_count": 0,
                "target_count": 0,
                "original_target_count": 0,
                "tier_filter_drained": False,
            }

        # ── Cold start: no existing offers → full ladder ──
        if not open_offers:
            log_event(
                "info",
                "requote_cold_start",
                f"No existing offers for {side} — creating full ladder",
            )
            fresh = self.create_ladder(
                current_price,
                side,
                risk_manager=risk_manager,
                spread_fraction=spread_fraction,
                coin_ids_enabled=cfg.COIN_IDS_ENABLED,
                price_cap=price_cap,
                price_floor=price_floor,
            )
            if dexie_manager and fresh:
                for offer in fresh:
                    bech32 = offer.get("offer_bech32", "")
                    trade_id = offer.get("trade_id", "")
                    if bech32 and trade_id:
                        dexie_manager.queue_post(bech32, trade_id)
                log_event(
                    "info",
                    "requote_cold_start_queued",
                    f"Queued {len(fresh)} fresh {side} offers to Dexie",
                )
            # Cold start did real work — stamp the cooldown timer
            with self._lock:
                self._last_requote_time[side] = time.time()
            return {
                "offers": fresh,
                "fully_replaced": True,
                "replaced_count": len(fresh),
                "target_count": 0,
                "original_target_count": 0,
                "tier_filter_drained": False,
            }

        pending_lineage_pause = self._resume_pending_refresh_lineage_completions(side)
        if pending_lineage_pause is not None:
            log_event(
                "info",
                "requote_pending_lineage_paused",
                f"Requote {side}: {pending_lineage_pause}; holding new children",
            )
            return {
                "offers": [],
                "fully_replaced": False,
                "replaced_count": 0,
                "target_count": target_count,
                "original_target_count": original_target_count,
                "pending_cancel_count": 0,
                "failed_cancel_count": 0,
                "tier_filter_drained": False,
                "refresh_paused": True,
            }

        # Pending children normally consume the overlap coin that makes the
        # new-child planner pause.  Resume their already-durable lineage
        # before consulting capacity, otherwise Task 8/9 closure could be
        # stranded forever at zero spares.
        refresh_by_parent, refresh_pause = self._collect_staged_refresh_parents(
            open_offers, side
        )
        if refresh_pause is not None:
            log_event(
                "info",
                "requote_staged_refresh_paused",
                f"Requote {side}: {refresh_pause}; holding new children",
            )
            return {
                "offers": [],
                "fully_replaced": False,
                "replaced_count": 0,
                "target_count": target_count,
                "original_target_count": original_target_count,
                "pending_cancel_count": 0,
                "failed_cancel_count": 0,
                "tier_filter_drained": False,
                "refresh_paused": True,
            }

        # ── Count spare coins ──
        # Use DB coin tracking (which knows tier designations) rather than the
        # raw wallet RPC so that fee/sniper/reserve coins are not counted as
        # usable — they fail preselection and produce wasted RPC round-trips.
        wallet_type_str = "cat" if side == "sell" else "xch"
        spare_count = 0
        try:
            from database import get_free_coins

            _db_free = get_free_coins(wallet_type_str)
            _TRADING_DESIGS = {"tier_spare", "tier_active"}
            _SKIP_TIERS = {"none", "sniper", "reserve", "fee"}
            spare_count = sum(
                1
                for c in _db_free
                if c.get("designation", "") in _TRADING_DESIGS
                and c.get("assigned_tier", "none") not in _SKIP_TIERS
            )
        except Exception as exc:
            # The durable free-pool query is the reservation authority.  A
            # wallet count cannot safely replace it because it omits Task 4
            # selections and could create over a protected offer.
            log_event(
                "warning",
                "requote_spare_query_blocked",
                f"Requote {side}: durable spare query failed closed: {exc}",
            )
            spare_count = 0

        log_event(
            "info",
            "requote_spare_coins",
            f"Spare {side} coins: {spare_count} (tier-designated)",
        )

        if spare_count == 0:
            log_event(
                "info",
                "requote_no_spares",
                f"Requote {side}: 0 spare coins — cannot create "
                f"replacements, trim pass will clean excess if needed",
            )
            return {
                "offers": [],
                "fully_replaced": False,
                "replaced_count": 0,
                "target_count": target_count,
                "original_target_count": original_target_count,
                "pending_cancel_count": 0,
                "failed_cancel_count": 0,
                "tier_filter_drained": False,
            }

        # Task 11 refresh is create-child-first.  The exact cohort was
        # validated above; Task 12 still owns purpose-separated capacity.
        refresh_plan = self.plan_staged_refresh(
            [
                {
                    "intent_id": intent_id,
                    "severity": max(0, target_count - index),
                    "slot_key": parent["slot_key"],
                    "generation": parent["generation"],
                }
                for index, (intent_id, (_offer, parent, _slot)) in enumerate(
                    refresh_by_parent.items()
                )
            ],
            overlap_capacity=spare_count,
            batch_size=target_count,
        )
        if refresh_plan.mode != "stage":
            log_event(
                "info",
                "requote_staged_refresh_paused",
                f"Requote {side}: {refresh_plan.reason}",
            )
            return {
                "offers": [],
                "fully_replaced": False,
                "replaced_count": 0,
                "target_count": target_count,
                "original_target_count": original_target_count,
                "pending_cancel_count": 0,
                "failed_cancel_count": 0,
                "tier_filter_drained": False,
                "refresh_paused": True,
            }
        staged = [
            refresh_by_parent[parent_id] for parent_id in refresh_plan.stage_parent_ids
        ]
        refresh_parent_ids = {
            slot: parent["intent_id"] for _offer, parent, slot in staged
        }
        new_offers = self.create_ladder(
            current_price,
            side,
            num_offers=len(staged),
            slot_sequence=sorted(refresh_parent_ids),
            total_slots=(
                cfg.MAX_ACTIVE_BUY_OFFERS
                if side == "buy"
                else cfg.MAX_ACTIVE_SELL_OFFERS
            ),
            risk_manager=risk_manager,
            spread_fraction=spread_fraction,
            coin_ids_enabled=cfg.COIN_IDS_ENABLED,
            price_cap=price_cap,
            price_floor=price_floor,
            refresh_parent_ids=refresh_parent_ids,
        )
        if dexie_manager:
            for offer in new_offers:
                bech32 = offer.get("offer_bech32", "")
                trade_id = offer.get("trade_id", "")
                if bech32 and trade_id:
                    dexie_manager.queue_post(bech32, trade_id)
        # Queueing publication is not visibility.  The parent remains intact
        # until the registry visibility boundary is durably recorded and Task
        # 8 independently authorizes cancellation.
        with self._lock:
            self._last_requote_time[side] = time.time()
        return {
            "offers": new_offers,
            "fully_replaced": False,
            "replaced_count": len(new_offers),
            "target_count": target_count,
            "original_target_count": original_target_count,
            "pending_cancel_count": 0,
            "failed_cancel_count": 0,
            "lineage_pending_count": len(new_offers),
            "tier_filter_drained": False,
        }

    # -------------------------------------------------------------------
    # Cancellation
    # -------------------------------------------------------------------

    @staticmethod
    def _is_canonical_cancel_digest_id(value: Any, prefix: str) -> bool:
        if (
            type(value) is not str
            or type(prefix) is not str
            or not value.startswith(prefix)
            or len(value) != len(prefix) + 64
        ):
            return False
        suffix = value[len(prefix) :]
        if suffix.lower() != suffix:
            return False
        try:
            bytes.fromhex(suffix)
        except ValueError:
            return False
        return True

    @staticmethod
    def _canonical_cancel_intent(trade_id: Any) -> _CanonicalOfferCancelIntent:
        if (
            type(trade_id) is not str
            or len(trade_id) != 64
            or trade_id.lower() != trade_id
        ):
            raise ValueError("cancellation trade_id must be canonical lowercase hex")
        try:
            bytes.fromhex(trade_id)
        except ValueError as exc:
            raise ValueError(
                "cancellation trade_id must be canonical lowercase hex"
            ) from exc
        creation_intent = database.get_offer_intent_by_trade_id(trade_id)
        intent_id = (
            creation_intent["intent_id"]
            if type(creation_intent) is dict
            and type(creation_intent.get("intent_id")) is str
            and creation_intent["intent_id"]
            else f"cancel-target:{trade_id}"
        )
        return _CanonicalOfferCancelIntent(
            trade_id=trade_id,
            intent_id=intent_id,
            operation_id=f"cancel:{trade_id}",
        )

    def _offer_cancel_crash_boundary(
        self,
        phase: str,
        intent: _CanonicalOfferCancelIntent,
    ) -> None:
        hook = self._offer_cancel_crash_hook
        if hook is not None:
            hook(phase, intent)

    @staticmethod
    def _cancel_reconciliation_result(
        intent: _CanonicalOfferCancelIntent,
        *,
        idempotent_replay: bool,
        effect_attempted: bool = False,
        attempt: int = 1,
    ) -> dict:
        result = cancellation_result(
            CANCEL_UNKNOWN,
            method="journal_replay",
            raw_response={"operation_id": intent.operation_id},
        )
        result["_catalyst_effect_attempted"] = effect_attempted
        result["_catalyst_idempotent_replay"] = idempotent_replay
        result["_catalyst_operation_id"] = intent.operation_id
        result["_catalyst_intent_id"] = intent.intent_id
        result["_catalyst_attempt"] = attempt
        return result

    @staticmethod
    def _trip_cancel_latch(
        intent: _CanonicalOfferCancelIntent,
        *,
        wallet_fingerprint_hash: str,
        network: str,
    ) -> None:
        database.trip_runtime_safety_latch(
            reason_code="UNRESOLVED_OPERATIONS",
            reason="Cancellation outcome requires authoritative reconciliation",
            blocking_operation_ids=[intent.operation_id],
            wallet_fingerprint_hash=wallet_fingerprint_hash,
            network=network,
        )

    @staticmethod
    def _trip_cancel_replay_latch(
        intent: _CanonicalOfferCancelIntent,
        *,
        attempt: int,
        wallet_fingerprint_hash: str,
        network: str,
    ) -> None:
        """Let the durable effect owner finish before fencing a replay."""

        deadline = time.monotonic() + 65.0
        while time.monotonic() < deadline:
            try:
                events = database.get_offer_operation_events(intent.operation_id)
                if any(
                    event.get("attempt") == attempt
                    and event.get("phase") in {"FINALIZED", "RECONCILED"}
                    for event in events
                ):
                    break
            except Exception:
                break
            time.sleep(0.01)
        OfferManager._trip_cancel_latch(
            intent,
            wallet_fingerprint_hash=wallet_fingerprint_hash,
            network=network,
        )

    @staticmethod
    def _acquire_cancel_authority(
        intent: _CanonicalOfferCancelIntent,
    ) -> tuple[Any, dict, str, str]:
        continuation = wallet.begin_offer_cancel_continuation(
            operation_id=intent.operation_id,
            intent_id=intent.intent_id,
            trade_id=intent.trade_id,
            ttl_seconds=60,
        )
        try:
            journal = wallet.offer_cancel_continuation_journal(continuation)
            journal, _run_id, wallet_hash, network = (
                OfferManager._verified_continuation_journal(
                    journal,
                    intent,
                    trade_id=intent.trade_id,
                    allowed_backends=frozenset({"sage", "chia"}),
                )
            )
            return continuation, journal, wallet_hash, network
        except BaseException:
            wallet.close_offer_cancel_continuation(continuation)
            raise

    @staticmethod
    def _cancel_prepared_evidence(
        intent: _CanonicalOfferCancelIntent,
        *,
        attempt: int,
        reason: str,
        cohort_id: str,
        cohort_size: int,
        member_id: str,
        journal: dict,
    ) -> dict:
        safe_reason = reason if type(reason) is str else "manual"
        safe_reason = safe_reason.strip()[:128] or "manual"
        evidence = {
            "trade_id": intent.trade_id,
            "intent_id": intent.intent_id,
            "operation_id": intent.operation_id,
            "attempt": attempt,
            "cohort_id": cohort_id,
            "member_id": member_id,
            "reason": safe_reason,
            "continuation_journal_sha256": journal["snapshot_sha256"],
            "wallet_effect": {
                "secure": True,
                "timeout": 60,
                "fee_mojos": None,
            },
        }
        if cohort_size > 1:
            evidence["cohort_size"] = cohort_size
            evidence["effect_claim_protocol"] = "durable_cohort_claim_v1"
        return evidence

    @staticmethod
    def _prepare_cancel_member(
        intent: _CanonicalOfferCancelIntent,
        *,
        attempt: int,
        reason: str,
        cohort_id: str,
        cohort_size: int = 1,
        member_id: str,
        journal: dict,
        claim_effect: bool = True,
    ) -> bool:
        claim = database.prepare_offer_cancel(
            operation_id=intent.operation_id,
            event_id=f"{intent.operation_id}:attempt:{attempt}:prepared",
            trade_id=intent.trade_id,
            intent_id=intent.intent_id,
            attempt=attempt,
            wallet_identity_json=journal,
            evidence_json=OfferManager._cancel_prepared_evidence(
                intent,
                attempt=attempt,
                reason=reason,
                cohort_id=cohort_id,
                cohort_size=cohort_size,
                member_id=member_id,
                journal=journal,
            ),
            claim_effect=claim_effect,
        )
        if not claim_effect:
            if type(claim) is not dict:
                raise ValueError("cancellation prepared event is invalid")
            database.validate_offer_operation_event(claim)
            return True
        if (
            type(claim) is not dict
            or set(claim) != {"event", "effect_claimed"}
            or type(claim["event"]) is not dict
            or type(claim["effect_claimed"]) is not bool
        ):
            raise ValueError("cancellation effect claim result is invalid")
        return claim["effect_claimed"]

    @staticmethod
    def _recoverable_unclaimed_cohort_cancel(
        intent: _CanonicalOfferCancelIntent,
        *,
        attempt: int,
        cohort_id: str,
        cohort_size: int,
        member_id: str,
    ) -> Optional[dict]:
        """Validate proof that a cohort member never crossed the effect boundary."""

        rows = database.get_offer_operation_events(intent.operation_id)
        if not rows:
            return None
        events = [database.validate_offer_operation_event(row) for row in rows]
        if len(events) != attempt * 2 - 1:
            return None
        for prior_attempt in range(1, attempt):
            prepared_prior, finalized_prior = events[
                (prior_attempt - 1) * 2 : prior_attempt * 2
            ]
            if (
                prepared_prior["attempt"] != prior_attempt
                or prepared_prior["phase"] != "PREPARED"
                or prepared_prior["outcome"] != "PREPARED"
                or finalized_prior["attempt"] != prior_attempt
                or finalized_prior["phase"] != "FINALIZED"
                or finalized_prior["outcome"] != CANCEL_FAILED
                or finalized_prior["blocks_mutation"] != 0
            ):
                return None
        prepared = events[-1]
        if (
            prepared["event_id"] != f"{intent.operation_id}:attempt:{attempt}:prepared"
            or prepared["operation_id"] != intent.operation_id
            or prepared["intent_id"] != intent.intent_id
            or prepared["operation_type"] != "CANCEL"
            or prepared["attempt"] != attempt
            or prepared["phase"] != "PREPARED"
            or prepared["outcome"] != "PREPARED"
            or prepared["transaction_id"] is not None
            or prepared["spend_identity"] is not None
            or prepared["reason_code"] != "CANCEL_PREPARED"
            or prepared["blocks_mutation"] != 1
            or prepared["request_timestamp"] != prepared["created_at"]
        ):
            return None
        journal = json.loads(prepared["wallet_identity_json"])
        journal, _run_id, wallet_hash, network = (
            OfferManager._verified_continuation_journal(
                journal,
                intent,
                trade_id=intent.trade_id,
                allowed_backends=frozenset({"sage", "chia"}),
            )
        )
        evidence = json.loads(prepared["evidence_json"])
        required_keys = {
            "trade_id",
            "intent_id",
            "operation_id",
            "attempt",
            "cohort_id",
            "cohort_size",
            "member_id",
            "reason",
            "continuation_journal_sha256",
            "wallet_effect",
            "effect_claim_protocol",
        }
        if type(evidence) is not dict or frozenset(evidence) not in {
            frozenset(required_keys),
            frozenset(required_keys | {"prior_lifecycle_state"}),
        }:
            return None
        if (
            evidence["trade_id"] != intent.trade_id
            or evidence["intent_id"] != intent.intent_id
            or evidence["operation_id"] != intent.operation_id
            or evidence["attempt"] != attempt
            or evidence["cohort_id"] != cohort_id
            or evidence["cohort_size"] != cohort_size
            or evidence["member_id"] != member_id
            or evidence["effect_claim_protocol"] != "durable_cohort_claim_v1"
            or type(evidence["reason"]) is not str
            or not 1 <= len(evidence["reason"]) <= 128
            or evidence["continuation_journal_sha256"] != journal["snapshot_sha256"]
            or evidence["wallet_effect"]
            != {"secure": True, "timeout": 60, "fee_mojos": None}
            or (
                "prior_lifecycle_state" in evidence
                and (
                    type(evidence["prior_lifecycle_state"]) is not str
                    or not evidence["prior_lifecycle_state"]
                    or evidence["prior_lifecycle_state"]
                    in {"cancel_requested", "cancel_sent", "mempool_observed"}
                )
            )
        ):
            return None
        if (
            database.get_offer_cancel_effect_claim(
                operation_id=intent.operation_id,
                attempt=attempt,
            )
            is not None
        ):
            return None
        return {
            "journal": journal,
            "wallet_hash": wallet_hash,
            "network": network,
        }

    @staticmethod
    def _finalize_unattempted_cohort_cancel(
        intent: _CanonicalOfferCancelIntent,
        *,
        attempt: int,
        cohort_id: str,
        cohort_size: int,
        member_id: str,
        context: dict,
        reason_code: str,
        blocking_operation_id: str = "",
    ) -> dict:
        raw_response = {"reason_code": reason_code}
        if blocking_operation_id:
            raw_response["blocking_operation_id"] = blocking_operation_id
        result = cancellation_result(
            CANCEL_FAILED,
            method=(
                "batch_abort_ambiguous"
                if reason_code == "BATCH_ABORTED_BY_AMBIGUOUS_PEER"
                else "cohort_recovery_unattempted"
            ),
            raw_response=raw_response,
            error="CANCEL_REJECTED",
        )
        evidence = {
            "trade_id": intent.trade_id,
            "attempt": attempt,
            "cohort_id": cohort_id,
            "member_id": member_id,
            "effect_attempted": False,
            "cancel_result": result,
        }
        if blocking_operation_id:
            evidence["aborted_by_operation_id"] = blocking_operation_id
        try:
            database.finalize_offer_cancel(
                operation_id=intent.operation_id,
                event_id=f"{intent.operation_id}:attempt:{attempt}:finalized",
                trade_id=intent.trade_id,
                intent_id=intent.intent_id,
                attempt=attempt,
                cancel_result=result,
                wallet_identity_json=context["journal"],
                evidence_json=evidence,
                require_unclaimed=True,
            )
        except Exception:
            existing = OfferManager._existing_cancel_result(intent)
            if existing is not None:
                return existing
            return OfferManager._cancel_reconciliation_result(
                intent,
                idempotent_replay=False,
                effect_attempted=False,
                attempt=attempt,
            )
        result["_catalyst_effect_attempted"] = False
        result["_catalyst_idempotent_replay"] = False
        result["_catalyst_operation_id"] = intent.operation_id
        result["_catalyst_intent_id"] = intent.intent_id
        result["_catalyst_attempt"] = attempt
        return result

    def _recover_persisted_cancel_cohorts(self) -> Dict[str, dict]:
        """Close every discoverable manifest member that provably had no effect."""

        recovered = {}
        for manifest in database.get_unresolved_offer_cancel_cohort_manifests():
            cohort_id = manifest["cohort_id"]
            cohort_size = manifest["member_count"]
            for member in manifest["members"]:
                intent = self._canonical_cancel_intent(member["trade_id"])
                if (
                    intent.operation_id != member["operation_id"]
                    or intent.intent_id != member["intent_id"]
                ):
                    raise ValueError("durable cancellation manifest identity changed")
                context = self._recoverable_unclaimed_cohort_cancel(
                    intent,
                    attempt=member["attempt"],
                    cohort_id=cohort_id,
                    cohort_size=cohort_size,
                    member_id=member["member_id"],
                )
                if context is None:
                    result = self._existing_cancel_result(intent)
                    if result is None:
                        result = self._cancel_reconciliation_result(
                            intent,
                            idempotent_replay=True,
                            effect_attempted=False,
                            attempt=member["attempt"],
                        )
                else:
                    result = self._finalize_unattempted_cohort_cancel(
                        intent,
                        attempt=member["attempt"],
                        cohort_id=cohort_id,
                        cohort_size=cohort_size,
                        member_id=member["member_id"],
                        context=context,
                        reason_code="COHORT_RECOVERY_UNATTEMPTED",
                    )
                recovered[intent.trade_id] = result
        return recovered

    def _abort_cancel_after_ambiguous_peer(
        self,
        *,
        intent: _CanonicalOfferCancelIntent,
        attempt: int,
        reason: str,
        cohort_id: str,
        member_id: str,
        ambiguous_operation_id: str,
        continuation: Any,
        journal: dict,
        wallet_hash: str,
        network: str,
    ) -> dict:
        """Durably close a pre-authorized batch tail without a wallet effect."""

        try:
            effect_claimed = self._prepare_cancel_member(
                intent,
                attempt=attempt,
                reason=reason,
                cohort_id=cohort_id,
                member_id=member_id,
                journal=journal,
            )
            if not effect_claimed:
                self._trip_cancel_replay_latch(
                    intent,
                    attempt=attempt,
                    wallet_fingerprint_hash=wallet_hash,
                    network=network,
                )
                return self._cancel_reconciliation_result(
                    intent,
                    idempotent_replay=True,
                    effect_attempted=False,
                    attempt=attempt,
                )
            result = cancellation_result(
                CANCEL_FAILED,
                method="batch_abort_ambiguous",
                raw_response={
                    "reason_code": "BATCH_ABORTED_BY_AMBIGUOUS_PEER",
                    "blocking_operation_id": ambiguous_operation_id,
                },
                error="CANCEL_REJECTED",
            )
            database.finalize_offer_cancel(
                operation_id=intent.operation_id,
                event_id=f"{intent.operation_id}:attempt:{attempt}:finalized",
                trade_id=intent.trade_id,
                intent_id=intent.intent_id,
                attempt=attempt,
                cancel_result=result,
                wallet_identity_json=journal,
                evidence_json={
                    "trade_id": intent.trade_id,
                    "attempt": attempt,
                    "cohort_id": cohort_id,
                    "member_id": member_id,
                    "effect_attempted": False,
                    "cancel_result": result,
                    "aborted_by_operation_id": ambiguous_operation_id,
                },
            )
            result["_catalyst_effect_attempted"] = False
            result["_catalyst_idempotent_replay"] = False
            result["_catalyst_operation_id"] = intent.operation_id
            result["_catalyst_intent_id"] = intent.intent_id
            result["_catalyst_attempt"] = attempt
            return result
        except Exception:
            self._trip_cancel_latch(
                intent,
                wallet_fingerprint_hash=wallet_hash,
                network=network,
            )
            return self._cancel_reconciliation_result(
                intent,
                idempotent_replay=False,
                effect_attempted=False,
                attempt=attempt,
            )
        finally:
            wallet.close_offer_cancel_continuation(continuation)

    @staticmethod
    def _read_existing_cancel_result(
        intent: _CanonicalOfferCancelIntent,
    ) -> _OfferCancelResultProjection:
        """Read and validate a durable cancel result without mutating state."""

        rows = database.get_offer_operation_events(intent.operation_id)
        if not rows:
            return _OfferCancelResultProjection(None, None, False)
        wallet_hash = ""
        network = ""
        latest_attempt = 1
        try:
            events = [database.validate_offer_operation_event(row) for row in rows]
            if not events:
                raise ValueError("cancellation journal has an invalid event count")
            latest_attempt = events[-1]["attempt"]
            if latest_attempt < 1 or len(events) not in {
                latest_attempt * 2 - 1,
                latest_attempt * 2,
            }:
                raise ValueError("cancellation journal has an invalid event count")
            for prior_attempt in range(1, latest_attempt):
                prior_prepared, prior_finalized = events[
                    (prior_attempt - 1) * 2 : prior_attempt * 2
                ]
                if (
                    prior_prepared["attempt"] != prior_attempt
                    or prior_prepared["phase"] != "PREPARED"
                    or prior_prepared["outcome"] != "PREPARED"
                    or prior_finalized["attempt"] != prior_attempt
                    or prior_finalized["phase"] != "FINALIZED"
                    or prior_finalized["outcome"] != CANCEL_FAILED
                    or prior_finalized["blocks_mutation"] != 0
                ):
                    raise ValueError(
                        "cancellation attempts are not contiguous failures"
                    )
            events = events[(latest_attempt - 1) * 2 :]
            prepared = events[0]
            journal = json.loads(prepared["wallet_identity_json"])
            journal, _run_id, wallet_hash, network = (
                OfferManager._verified_continuation_journal(
                    journal,
                    intent,
                    trade_id=intent.trade_id,
                    allowed_backends=frozenset({"sage", "chia"}),
                )
            )
            prepared_evidence = json.loads(prepared["evidence_json"])
            if type(prepared_evidence) is not dict:
                raise ValueError("cancellation prepared evidence is not exact")
            cohort_id = prepared_evidence.get("cohort_id")
            member_id = prepared_evidence.get("member_id")
            expected_member_id = (
                "cancel-member:"
                + hashlib.sha256(
                    OfferManager._canonical_creation_json(
                        {
                            "cohort_id": cohort_id,
                            "operation_id": intent.operation_id,
                            "attempt": latest_attempt,
                            "trade_id": intent.trade_id,
                        }
                    ).encode("utf-8")
                ).hexdigest()
            )
            if (
                prepared["event_id"]
                != f"{intent.operation_id}:attempt:{latest_attempt}:prepared"
                or prepared["operation_id"] != intent.operation_id
                or prepared["intent_id"] != intent.intent_id
                or prepared["operation_type"] != "CANCEL"
                or prepared["attempt"] != latest_attempt
                or prepared["phase"] != "PREPARED"
                or prepared["outcome"] != "PREPARED"
                or prepared["transaction_id"] is not None
                or prepared["spend_identity"] is not None
                or prepared["reason_code"] != "CANCEL_PREPARED"
                or prepared["blocks_mutation"] != 1
                or prepared["request_timestamp"] != prepared["created_at"]
                or type(prepared_evidence) is not dict
                or prepared_evidence.get("trade_id") != intent.trade_id
                or prepared_evidence.get("intent_id") != intent.intent_id
                or prepared_evidence.get("operation_id") != intent.operation_id
                or prepared_evidence.get("attempt") != latest_attempt
                or prepared_evidence.get("continuation_journal_sha256")
                != journal["snapshot_sha256"]
                or frozenset(prepared_evidence)
                not in {
                    frozenset(
                        {
                            "trade_id",
                            "intent_id",
                            "operation_id",
                            "attempt",
                            "cohort_id",
                            "member_id",
                            "reason",
                            "continuation_journal_sha256",
                            "wallet_effect",
                        }
                    ),
                    frozenset(
                        {
                            "trade_id",
                            "intent_id",
                            "operation_id",
                            "attempt",
                            "cohort_id",
                            "member_id",
                            "reason",
                            "continuation_journal_sha256",
                            "wallet_effect",
                            "prior_lifecycle_state",
                        }
                    ),
                    frozenset(
                        {
                            "trade_id",
                            "intent_id",
                            "operation_id",
                            "attempt",
                            "cohort_id",
                            "member_id",
                            "reason",
                            "continuation_journal_sha256",
                            "wallet_effect",
                            "effect_claim_protocol",
                        }
                    ),
                    frozenset(
                        {
                            "trade_id",
                            "intent_id",
                            "operation_id",
                            "attempt",
                            "cohort_id",
                            "member_id",
                            "reason",
                            "continuation_journal_sha256",
                            "wallet_effect",
                            "effect_claim_protocol",
                            "prior_lifecycle_state",
                        }
                    ),
                    frozenset(
                        {
                            "trade_id",
                            "intent_id",
                            "operation_id",
                            "attempt",
                            "cohort_id",
                            "cohort_size",
                            "member_id",
                            "reason",
                            "continuation_journal_sha256",
                            "wallet_effect",
                            "effect_claim_protocol",
                        }
                    ),
                    frozenset(
                        {
                            "trade_id",
                            "intent_id",
                            "operation_id",
                            "attempt",
                            "cohort_id",
                            "cohort_size",
                            "member_id",
                            "reason",
                            "continuation_journal_sha256",
                            "wallet_effect",
                            "effect_claim_protocol",
                            "prior_lifecycle_state",
                        }
                    ),
                }
                or (
                    "prior_lifecycle_state" in prepared_evidence
                    and (
                        type(prepared_evidence["prior_lifecycle_state"]) is not str
                        or not prepared_evidence["prior_lifecycle_state"]
                        or prepared_evidence["prior_lifecycle_state"]
                        in {"cancel_requested", "cancel_sent", "mempool_observed"}
                    )
                )
                or not OfferManager._is_canonical_cancel_digest_id(
                    cohort_id,
                    "cancel-cohort:",
                )
                or type(member_id) is not str
                or member_id != expected_member_id
                or type(prepared_evidence.get("reason")) is not str
                or not 1 <= len(prepared_evidence["reason"]) <= 128
                or prepared_evidence.get("wallet_effect")
                != {"secure": True, "timeout": 60, "fee_mojos": None}
                or (
                    "effect_claim_protocol" in prepared_evidence
                    and (
                        prepared_evidence["effect_claim_protocol"]
                        != "durable_cohort_claim_v1"
                        or (
                            prepared_evidence.get("cohort_size") is not None
                            and (
                                type(prepared_evidence["cohort_size"]) is not int
                                or isinstance(prepared_evidence["cohort_size"], bool)
                                or prepared_evidence["cohort_size"] < 2
                            )
                        )
                    )
                )
            ):
                raise ValueError("cancellation prepared event is not exact")
            if len(events) == 1:
                return _OfferCancelResultProjection(
                    result=OfferManager._cancel_reconciliation_result(
                        intent,
                        idempotent_replay=True,
                        attempt=latest_attempt,
                    ),
                    latch_binding=(wallet_hash, network),
                    authoritative=False,
                )
            finalized = events[1]
            final_evidence = json.loads(finalized["evidence_json"])
            if type(final_evidence) is not dict:
                raise ValueError("cancellation final evidence is not exact")
            result = validate_cancel_result(final_evidence["cancel_result"])
            final_evidence_keys = {
                "trade_id",
                "attempt",
                "cohort_id",
                "member_id",
                "effect_attempted",
                "cancel_result",
            }
            is_batch_abort = result["method"] == "batch_abort_ambiguous"
            if is_batch_abort:
                final_evidence_keys.add("aborted_by_operation_id")
            expected_blocks = int(
                result["outcome"] in {CANCEL_SUBMITTED_UNCONFIRMED, CANCEL_UNKNOWN}
            )
            if (
                finalized["event_id"]
                != f"{intent.operation_id}:attempt:{latest_attempt}:finalized"
                or finalized["operation_id"] != intent.operation_id
                or finalized["intent_id"] != intent.intent_id
                or finalized["operation_type"] != "CANCEL"
                or finalized["attempt"] != latest_attempt
                or finalized["phase"] != "FINALIZED"
                or finalized["outcome"] != result["outcome"]
                or finalized["transaction_id"] != (result["transaction_id"] or None)
                or finalized["spend_identity"] != (result["spend_identity"] or None)
                or finalized["blocks_mutation"] != expected_blocks
                or finalized["reason_code"] != result["outcome"]
                or finalized["request_timestamp"] != finalized["created_at"]
                or finalized["wallet_identity_json"] != prepared["wallet_identity_json"]
                or type(final_evidence) is not dict
                or set(final_evidence) != final_evidence_keys
                or final_evidence.get("trade_id") != intent.trade_id
                or final_evidence.get("attempt") != latest_attempt
                or final_evidence.get("cohort_id") != cohort_id
                or final_evidence.get("member_id") != member_id
                or type(final_evidence.get("effect_attempted")) is not bool
                or final_evidence.get("cancel_result") != result
                or (
                    is_batch_abort
                    and (
                        result["outcome"] != CANCEL_FAILED
                        or final_evidence["effect_attempted"] is not False
                        or not OfferManager._is_canonical_cancel_digest_id(
                            final_evidence.get("aborted_by_operation_id"),
                            "cancel:",
                        )
                    )
                )
            ):
                raise ValueError("cancellation final event is not exact")
            result["_catalyst_effect_attempted"] = False
            result["_catalyst_idempotent_replay"] = True
            result["_catalyst_operation_id"] = intent.operation_id
            result["_catalyst_intent_id"] = intent.intent_id
            result["_catalyst_attempt"] = latest_attempt
            return _OfferCancelResultProjection(
                result=result,
                latch_binding=(wallet_hash, network) if expected_blocks else None,
                authoritative=not bool(expected_blocks),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return _OfferCancelResultProjection(
                result=OfferManager._cancel_reconciliation_result(
                    intent,
                    idempotent_replay=True,
                    attempt=latest_attempt,
                ),
                latch_binding=(
                    (wallet_hash, network) if wallet_hash and network else None
                ),
                authoritative=False,
            )

    @staticmethod
    def _existing_cancel_result(
        intent: _CanonicalOfferCancelIntent,
    ) -> Optional[dict]:
        projection = OfferManager._read_existing_cancel_result(intent)
        if projection.latch_binding is not None and type(projection.result) is dict:
            attempt = projection.result.get("_catalyst_attempt")
            try:
                events = database.get_offer_operation_events(intent.operation_id)
                latest = events[-1] if events else None
            except Exception:
                latest = None
            if (
                type(attempt) is int
                and type(latest) is dict
                and latest.get("attempt") == attempt
                and latest.get("phase") == "PREPARED"
            ):
                # Another exact caller owns (or already claimed) this effect.
                # Returning the durable PREPARED projection is fail-closed and
                # must not advance the recovery generation underneath the
                # owner before it can append FINALIZED. Startup recovery still
                # fences a genuinely stranded PREPARED row.
                return projection.result
        if projection.latch_binding is not None:
            wallet_hash, network = projection.latch_binding
            OfferManager._trip_cancel_latch(
                intent,
                wallet_fingerprint_hash=wallet_hash,
                network=network,
            )
        return projection.result

    def get_cancel_result_authority(self, trade_id: Any) -> Optional[dict]:
        """Project the latest exact durable cancellation result for one trade."""

        intent = self._canonical_cancel_intent(trade_id)
        projection = self._read_existing_cancel_result(intent)
        result = projection.result
        if type(result) is not dict or not projection.authoritative:
            return None
        metadata_keys = frozenset(
            {
                "_catalyst_effect_attempted",
                "_catalyst_idempotent_replay",
                "_catalyst_operation_id",
                "_catalyst_intent_id",
                "_catalyst_attempt",
            }
        )
        if not metadata_keys.issubset(result):
            return None
        typed_result = {
            key: value for key, value in result.items() if key not in metadata_keys
        }
        try:
            typed_result = validate_cancel_result(typed_result)
        except (TypeError, ValueError):
            return None
        attempt = result["_catalyst_attempt"]
        effect_attempted = result["_catalyst_effect_attempted"]
        idempotent_replay = result["_catalyst_idempotent_replay"]
        if (
            type(effect_attempted) is not bool
            or type(idempotent_replay) is not bool
            or (effect_attempted and idempotent_replay)
            or result["_catalyst_operation_id"] != intent.operation_id
            or result["_catalyst_intent_id"] != intent.intent_id
            or type(attempt) is not int
            or attempt < 1
        ):
            return None
        return {
            "trade_id": intent.trade_id,
            "operation_id": intent.operation_id,
            "intent_id": intent.intent_id,
            "attempt": attempt,
            "outcome": typed_result["outcome"],
        }

    def _cancel_one_from_journal(
        self,
        *,
        intent: _CanonicalOfferCancelIntent,
        reason: str,
        cohort_id: str,
        member_id: str,
        continuation: Any = None,
        journal: Optional[dict] = None,
        wallet_hash: str = "",
        network: str = "",
        attempt: int = 1,
        prepared_for_cohort: bool = False,
    ) -> dict:
        existing = None if prepared_for_cohort else self._existing_cancel_result(intent)
        may_advance_failed_attempt = (
            existing is not None
            and attempt > 1
            and existing.get("outcome") == CANCEL_FAILED
            and existing.get("_catalyst_attempt") == attempt - 1
        )
        if (
            existing is not None
            and not may_advance_failed_attempt
            and not prepared_for_cohort
        ):
            if continuation is not None:
                wallet.close_offer_cancel_continuation(continuation)
            return existing
        try:
            if continuation is None:
                continuation, journal, wallet_hash, network = (
                    self._acquire_cancel_authority(intent)
                )
            if type(journal) is not dict:
                raise ValueError("cancellation authority journal is missing")
            if prepared_for_cohort:
                self._offer_cancel_crash_boundary("after_prepare", intent)
                try:
                    effect_claimed = database.claim_offer_cancel_effect(
                        operation_id=intent.operation_id,
                        trade_id=intent.trade_id,
                        attempt=attempt,
                    )
                except (TypeError, ValueError):
                    existing = self._existing_cancel_result(intent)
                    if existing is not None:
                        return existing
                    raise
            else:
                self._offer_cancel_crash_boundary("before_prepare", intent)
                try:
                    effect_claimed = self._prepare_cancel_member(
                        intent,
                        attempt=attempt,
                        reason=reason,
                        cohort_id=cohort_id,
                        member_id=member_id,
                        journal=journal,
                    )
                except (TypeError, ValueError):
                    existing = self._existing_cancel_result(intent)
                    if existing is not None:
                        return existing
                    raise
                self._offer_cancel_crash_boundary("after_prepare", intent)
            if not effect_claimed:
                self._trip_cancel_replay_latch(
                    intent,
                    attempt=attempt,
                    wallet_fingerprint_hash=wallet_hash,
                    network=network,
                )
                return self._cancel_reconciliation_result(
                    intent,
                    idempotent_replay=True,
                    effect_attempted=False,
                    attempt=attempt,
                )
            self._offer_cancel_crash_boundary("before_wallet", intent)
            continuation_refreshed = not prepared_for_cohort or (
                continuation is not None
                and wallet.refresh_offer_cancel_continuation(
                    continuation,
                    operation_id=intent.operation_id,
                    intent_id=intent.intent_id,
                    trade_id=intent.trade_id,
                    ttl_seconds=60,
                )
            )
            if continuation_refreshed:
                raw_result = wallet.cancel_offer(
                    intent.trade_id,
                    secure=True,
                    timeout=60,
                    fee_mojos=None,
                    _cancel_continuation=continuation,
                    _cancel_operation_id=intent.operation_id,
                    _cancel_intent_id=intent.intent_id,
                )
                continuation = None
            else:
                raw_result = cancellation_result(
                    CANCEL_UNKNOWN,
                    method="continuation_refresh",
                    raw_response={
                        "reason_code": "CONTINUATION_REFRESH_BLOCKED",
                    },
                )
                raw_result["_catalyst_effect_attempted"] = False
            effect_attempted = (
                type(raw_result) is dict
                and raw_result.get("_catalyst_effect_attempted") is True
            )
            typed_candidate = (
                {
                    key: value
                    for key, value in raw_result.items()
                    if key != "_catalyst_effect_attempted"
                }
                if type(raw_result) is dict
                else raw_result
            )
            try:
                result = validate_cancel_result(typed_candidate)
            except (TypeError, ValueError):
                result = cancellation_result(
                    CANCEL_UNKNOWN,
                    method="wallet_facade",
                    raw_response={
                        "invalid_result_schema": type(typed_candidate).__name__
                    },
                )
            if result["outcome"] == CANCEL_CONFIRMED:
                result = cancellation_result(
                    CANCEL_UNKNOWN,
                    method="wallet_facade",
                    raw_response={"claimed_outcome": CANCEL_CONFIRMED},
                )
            self._offer_cancel_crash_boundary("after_response", intent)
            final_evidence = {
                "trade_id": intent.trade_id,
                "attempt": attempt,
                "cohort_id": cohort_id,
                "member_id": member_id,
                "effect_attempted": effect_attempted,
                "cancel_result": result,
            }
            self._offer_cancel_crash_boundary("before_final_commit", intent)
            try:
                database.finalize_offer_cancel(
                    operation_id=intent.operation_id,
                    event_id=f"{intent.operation_id}:attempt:{attempt}:finalized",
                    trade_id=intent.trade_id,
                    intent_id=intent.intent_id,
                    attempt=attempt,
                    cancel_result=result,
                    wallet_identity_json=journal,
                    evidence_json=final_evidence,
                )
            except Exception:
                self._trip_cancel_latch(
                    intent,
                    wallet_fingerprint_hash=wallet_hash,
                    network=network,
                )
                return self._cancel_reconciliation_result(
                    intent,
                    idempotent_replay=False,
                    effect_attempted=effect_attempted,
                    attempt=attempt,
                )
            if result["outcome"] in {
                CANCEL_SUBMITTED_UNCONFIRMED,
                CANCEL_UNKNOWN,
            }:
                self._trip_cancel_latch(
                    intent,
                    wallet_fingerprint_hash=wallet_hash,
                    network=network,
                )
            self._offer_cancel_crash_boundary("after_final_commit", intent)
            result["_catalyst_effect_attempted"] = effect_attempted
            result["_catalyst_idempotent_replay"] = False
            result["_catalyst_operation_id"] = intent.operation_id
            result["_catalyst_intent_id"] = intent.intent_id
            result["_catalyst_attempt"] = attempt
            return result
        finally:
            if continuation is not None:
                wallet.close_offer_cancel_continuation(continuation)

    def cancel_offers(
        self,
        trade_ids: List[str],
        reason: str = "manual",
        force_storm: bool = False,
        skip_confirmation: bool = False,
        _retry_failed_attempts: Optional[Dict[str, int]] = None,
    ) -> Dict:
        """Cancel a list of offers.

        Marks them as bot-cancelled so fill detection doesn't count them as fills.
        Sequential cancellation with delays (parallel breaks the wallet).

        F20 (2026-04-08): cancel-storm protection. If a single call asks
        to cancel more than CANCEL_STORM_THRESHOLD_PCT of the live book
        in one shot AND the caller didn't pass force_storm=True, the
        call is REFUSED with a critical alert. Reasons that legitimately
        cancel large fractions (Cancel All button, reserve floor breach,
        circuit breaker, shutdown) all explicitly pass force_storm=True.
        Routine requote/expiry/sniper paths do NOT — so a bug there
        that tries to nuke the book gets caught here instead of executing.
        """
        del skip_confirmation
        if not trade_ids:
            return {}

        # F20: cancel-storm protection
        if not force_storm:
            try:
                # Count how many offers we currently have live (DB view)
                from database import get_open_offers as _gso

                live_count = len(_gso(cat_asset_id=cfg.CAT_ASSET_ID))
            except Exception:
                live_count = 0
            if live_count > 0:
                pct = (len(trade_ids) / live_count) * 100
                threshold_pct = float(
                    getattr(cfg, "CANCEL_STORM_THRESHOLD_PCT", 80) or 80
                )
                if pct >= threshold_pct and len(trade_ids) >= 5:
                    log_event(
                        "error",
                        "cancel_storm_blocked",
                        f"BLOCKED cancel storm: caller {reason} tried to cancel "
                        f"{len(trade_ids)}/{live_count} offers ({pct:.0f}%) in one "
                        f"shot. Threshold is {threshold_pct:.0f}%. Refusing — pass "
                        f"force_storm=True if this is intentional (e.g. Cancel All, "
                        f"reserve floor breach, shutdown).",
                    )
                    return {
                        tid: cancellation_result(
                            CANCEL_FAILED,
                            method="cancel_storm_guard",
                            raw_response={
                                "reason_code": "CANCEL_STORM_BLOCKED",
                                "effect_attempted": False,
                            },
                            error="CANCEL_REJECTED",
                        )
                        for tid in trade_ids
                    }

        canonical_intents = [self._canonical_cancel_intent(tid) for tid in trade_ids]
        self._recover_persisted_cancel_cohorts()
        unique_intents = []
        seen_trade_ids = set()
        for intent in canonical_intents:
            if intent.trade_id not in seen_trade_ids:
                seen_trade_ids.add(intent.trade_id)
                unique_intents.append(intent)
        canonical_trade_ids = sorted(seen_trade_ids)
        retry_failed_attempts = (
            {} if _retry_failed_attempts is None else _retry_failed_attempts
        )
        if type(retry_failed_attempts) is not dict or any(
            type(trade_id) is not str
            or trade_id not in seen_trade_ids
            or type(prior_attempt) is not int
            or isinstance(prior_attempt, bool)
            or prior_attempt < 1
            for trade_id, prior_attempt in retry_failed_attempts.items()
        ):
            raise ValueError("failed cancel retry authority is invalid")
        cohort_id = (
            "cancel-cohort:"
            + hashlib.sha256(
                self._canonical_creation_json(canonical_trade_ids).encode("utf-8")
            ).hexdigest()
        )
        members = []
        for intent in unique_intents:
            attempt = retry_failed_attempts.get(intent.trade_id, 0) + 1
            member_id = (
                "cancel-member:"
                + hashlib.sha256(
                    self._canonical_creation_json(
                        {
                            "cohort_id": cohort_id,
                            "operation_id": intent.operation_id,
                            "attempt": attempt,
                            "trade_id": intent.trade_id,
                        }
                    ).encode("utf-8")
                ).hexdigest()
            )
            members.append((intent, attempt, member_id))

        is_cohort = len(members) > 1
        recoverable_contexts = {}
        existing_results = {}
        for intent, attempt, member_id in members:
            context = None
            if is_cohort:
                try:
                    context = self._recoverable_unclaimed_cohort_cancel(
                        intent,
                        attempt=attempt,
                        cohort_id=cohort_id,
                        cohort_size=len(members),
                        member_id=member_id,
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    context = None
            if context is not None:
                recoverable_contexts[intent.trade_id] = context
                existing_results[intent.trade_id] = None
            else:
                existing_results[intent.trade_id] = self._existing_cancel_result(intent)
        recovering_interrupted_cohort = bool(recoverable_contexts)
        retry_eligible = {
            intent.trade_id: (
                intent.trade_id in retry_failed_attempts
                and existing_results[intent.trade_id] is not None
                and existing_results[intent.trade_id].get("outcome") == CANCEL_FAILED
                and existing_results[intent.trade_id].get("_catalyst_attempt")
                == attempt - 1
            )
            for intent, attempt, _member_id in members
        }
        if not recovering_interrupted_cohort and any(
            result is not None
            and result["outcome"] in {CANCEL_SUBMITTED_UNCONFIRMED, CANCEL_UNKNOWN}
            for result in existing_results.values()
        ):
            return {
                intent.trade_id: existing_results[intent.trade_id]
                or self._cancel_reconciliation_result(
                    intent,
                    idempotent_replay=False,
                    effect_attempted=False,
                )
                for intent, _attempt, _member_id in members
            }

        ordered_members = list(members)
        if not recovering_interrupted_cohort:
            participating = [
                (intent, attempt)
                for intent, attempt, _member_id in members
                if existing_results[intent.trade_id] is None
                or retry_eligible[intent.trade_id]
            ]
            manifest = None
            if len(participating) > 1:
                manifest = database.canonical_offer_cancel_cohort_manifest(
                    [
                        {
                            "trade_id": intent.trade_id,
                            "operation_id": intent.operation_id,
                            "intent_id": intent.intent_id,
                            "attempt": attempt,
                            "prepared_event_id": (
                                f"{intent.operation_id}:attempt:{attempt}:prepared"
                            ),
                        }
                        for intent, attempt in participating
                    ]
                )
                cohort_id = manifest["cohort_id"]
                intents_by_trade_id = {
                    intent.trade_id: intent for intent, _attempt in participating
                }
                members = [
                    (
                        intents_by_trade_id[member["trade_id"]],
                        member["attempt"],
                        member["member_id"],
                    )
                    for member in manifest["members"]
                ]
            else:
                participating_trade_ids = sorted(
                    intent.trade_id for intent, _attempt in participating
                )
                cohort_id = (
                    "cancel-cohort:"
                    + hashlib.sha256(
                        self._canonical_creation_json(participating_trade_ids).encode(
                            "utf-8"
                        )
                    ).hexdigest()
                )
                members = []
                for intent, attempt in participating:
                    member_id = (
                        "cancel-member:"
                        + hashlib.sha256(
                            self._canonical_creation_json(
                                {
                                    "cohort_id": cohort_id,
                                    "operation_id": intent.operation_id,
                                    "attempt": attempt,
                                    "trade_id": intent.trade_id,
                                }
                            ).encode("utf-8")
                        ).hexdigest()
                    )
                    members.append((intent, attempt, member_id))
            is_cohort = len(members) > 1
        else:
            manifest = None

        authorities = {}
        try:
            # Acquire in reverse dispatch order so the first wallet effect uses
            # the freshest continuation even for the 500-member API envelope.
            for intent, _attempt, _member_id in reversed(members):
                if (
                    existing_results[intent.trade_id] is None
                    and intent.trade_id not in recoverable_contexts
                ) or retry_eligible[intent.trade_id]:
                    authorities[intent.trade_id] = self._acquire_cancel_authority(
                        intent
                    )

            if is_cohort:
                if manifest is not None:
                    requests = []
                    for intent, attempt, member_id in members:
                        self._offer_cancel_crash_boundary(
                            "before_cohort_prepare", intent
                        )
                        authority = authorities.get(intent.trade_id)
                        if authority is None:
                            raise ValueError(
                                "cancellation cohort authority is incomplete"
                            )
                        _continuation, journal, _wallet_hash, _network = authority
                        requests.append(
                            {
                                "operation_id": intent.operation_id,
                                "event_id": (
                                    f"{intent.operation_id}:attempt:{attempt}:prepared"
                                ),
                                "trade_id": intent.trade_id,
                                "intent_id": intent.intent_id,
                                "attempt": attempt,
                                "wallet_identity_json": journal,
                                "evidence_json": self._cancel_prepared_evidence(
                                    intent,
                                    attempt=attempt,
                                    reason=reason,
                                    cohort_id=cohort_id,
                                    cohort_size=len(members),
                                    member_id=member_id,
                                    journal=journal,
                                ),
                            }
                        )
                    cohort_prepare = database.prepare_offer_cancel_cohort(
                        manifest_json=manifest,
                        member_requests_json=requests,
                    )
                    if cohort_prepare["inserted"] is False:
                        replay_results = {}
                        for (
                            replay_intent,
                            replay_attempt,
                            _member_id,
                        ) in ordered_members:
                            replay_result = existing_results[replay_intent.trade_id]
                            if replay_result is None:
                                replay_result = self._read_existing_cancel_result(
                                    replay_intent
                                ).result
                            if replay_result is None:
                                replay_result = self._cancel_reconciliation_result(
                                    replay_intent,
                                    idempotent_replay=True,
                                    effect_attempted=False,
                                    attempt=replay_attempt,
                                )
                            replay_results[replay_intent.trade_id] = replay_result
                        return replay_results
                else:
                    for intent, attempt, member_id in members:
                        authority = authorities.get(intent.trade_id)
                        if authority is None:
                            continue
                        _continuation, journal, _wallet_hash, _network = authority
                        self._offer_cancel_crash_boundary(
                            "before_cohort_prepare", intent
                        )
                        try:
                            self._prepare_cancel_member(
                                intent,
                                attempt=attempt,
                                reason=reason,
                                cohort_id=cohort_id,
                                cohort_size=len(members),
                                member_id=member_id,
                                journal=journal,
                                claim_effect=False,
                            )
                        except (TypeError, ValueError):
                            context = self._recoverable_unclaimed_cohort_cancel(
                                intent,
                                attempt=attempt,
                                cohort_id=cohort_id,
                                cohort_size=len(members),
                                member_id=member_id,
                            )
                            if context is None:
                                raise
                            recoverable_contexts[intent.trade_id] = context
                            recovering_interrupted_cohort = True
                self._offer_cancel_crash_boundary(
                    "after_cohort_prepare",
                    members[0][0],
                )

            if recovering_interrupted_cohort:
                processed_results = {}
                for intent, attempt, member_id in members:
                    existing = existing_results[intent.trade_id]
                    if existing is not None:
                        result = existing
                    else:
                        context = recoverable_contexts.get(intent.trade_id)
                        if context is None:
                            context = self._recoverable_unclaimed_cohort_cancel(
                                intent,
                                attempt=attempt,
                                cohort_id=cohort_id,
                                cohort_size=len(members),
                                member_id=member_id,
                            )
                        if context is None:
                            result = self._cancel_reconciliation_result(
                                intent,
                                idempotent_replay=True,
                                effect_attempted=False,
                                attempt=attempt,
                            )
                        else:
                            result = self._finalize_unattempted_cohort_cancel(
                                intent,
                                attempt=attempt,
                                cohort_id=cohort_id,
                                cohort_size=len(members),
                                member_id=member_id,
                                context=context,
                                reason_code="COHORT_RECOVERY_UNATTEMPTED",
                            )
                    processed_results[intent.trade_id] = result
                results = {}
                for intent, attempt, _member_id in ordered_members:
                    result = processed_results.get(intent.trade_id)
                    if result is None:
                        result = existing_results[intent.trade_id]
                    if result is None:
                        result = self._cancel_reconciliation_result(
                            intent,
                            idempotent_replay=True,
                            effect_attempted=False,
                            attempt=attempt,
                        )
                    results[intent.trade_id] = result
                    if result.get("outcome") == CANCEL_FAILED:
                        prior_retry = self._pending_cancel_retries.get(
                            intent.trade_id, {}
                        )
                        self._pending_cancel_retries[intent.trade_id] = {
                            "attempts": result.get("_catalyst_attempt", attempt),
                            "first_failed": prior_retry.get(
                                "first_failed", time.time()
                            ),
                        }
                    else:
                        self._pending_cancel_retries.pop(intent.trade_id, None)
                return results

            processed_results = {}
            ambiguous_operation_id = ""
            for intent, attempt, member_id in members:
                existing = existing_results[intent.trade_id]
                if existing is not None and not retry_eligible[intent.trade_id]:
                    result = existing
                else:
                    continuation, journal, wallet_hash, network = authorities.pop(
                        intent.trade_id
                    )
                    if ambiguous_operation_id:
                        if is_cohort:
                            try:
                                context = self._recoverable_unclaimed_cohort_cancel(
                                    intent,
                                    attempt=attempt,
                                    cohort_id=cohort_id,
                                    cohort_size=len(members),
                                    member_id=member_id,
                                )
                                if context is None:
                                    result = self._existing_cancel_result(intent)
                                    if result is None:
                                        result = self._cancel_reconciliation_result(
                                            intent,
                                            idempotent_replay=True,
                                            effect_attempted=False,
                                            attempt=attempt,
                                        )
                                else:
                                    result = self._finalize_unattempted_cohort_cancel(
                                        intent,
                                        attempt=attempt,
                                        cohort_id=cohort_id,
                                        cohort_size=len(members),
                                        member_id=member_id,
                                        context=context,
                                        reason_code="BATCH_ABORTED_BY_AMBIGUOUS_PEER",
                                        blocking_operation_id=ambiguous_operation_id,
                                    )
                            finally:
                                wallet.close_offer_cancel_continuation(continuation)
                        else:
                            result = self._abort_cancel_after_ambiguous_peer(
                                intent=intent,
                                attempt=attempt,
                                reason=reason,
                                cohort_id=cohort_id,
                                member_id=member_id,
                                ambiguous_operation_id=ambiguous_operation_id,
                                continuation=continuation,
                                journal=journal,
                                wallet_hash=wallet_hash,
                                network=network,
                            )
                    else:
                        result = self._cancel_one_from_journal(
                            intent=intent,
                            attempt=attempt,
                            reason=reason,
                            cohort_id=cohort_id,
                            member_id=member_id,
                            continuation=continuation,
                            journal=journal,
                            wallet_hash=wallet_hash,
                            network=network,
                            prepared_for_cohort=is_cohort,
                        )
                processed_results[intent.trade_id] = result
                if not ambiguous_operation_id and result["outcome"] in {
                    CANCEL_SUBMITTED_UNCONFIRMED,
                    CANCEL_UNKNOWN,
                }:
                    ambiguous_operation_id = intent.operation_id
            results = {}
            for intent, attempt, _member_id in ordered_members:
                result = processed_results.get(intent.trade_id)
                if result is None:
                    result = existing_results[intent.trade_id]
                if result is None:
                    result = self._cancel_reconciliation_result(
                        intent,
                        idempotent_replay=True,
                        effect_attempted=False,
                        attempt=attempt,
                    )
                results[intent.trade_id] = result
                if result.get("outcome") == CANCEL_FAILED:
                    prior_retry = self._pending_cancel_retries.get(intent.trade_id, {})
                    self._pending_cancel_retries[intent.trade_id] = {
                        "attempts": result.get("_catalyst_attempt", attempt),
                        "first_failed": prior_retry.get("first_failed", time.time()),
                    }
                else:
                    self._pending_cancel_retries.pop(intent.trade_id, None)
            return results
        finally:
            for continuation, _journal, _wallet_hash, _network in authorities.values():
                wallet.close_offer_cancel_continuation(continuation)

    def cancel_all(
        self,
        cat_asset_id: str = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        side_filter: str = "",
    ) -> Dict:
        """Cancel all open offers (or only one side's offers) in controlled batches.

        Sage wallet struggles with bulk cancels — each cancel is an on-chain
        transaction and too many at once can cause long pending states. This
        method cancels in measured batches with a short pause between batches
        so we can push harder than one-by-one shutdown without blind fire-and-forget.

        First checks the database. If the DB has no open offers (e.g. pre-existing
        offers that were never inserted), falls back to fetching directly from the
        wallet RPC.

        Args:
            side_filter: If "buy", cancel only buy offers. If "sell", cancel only
                         sell offers. Empty string (default) cancels all sides.
                         Used by the position circuit breaker to cancel only the
                         accumulating side while keeping the correcting side live.
        """

        def emit_progress(**payload):
            if not progress_callback:
                return
            try:
                progress_callback(payload)
            except Exception as e:
                log_event(
                    "debug",
                    "cancel_progress_callback_failed",
                    f"Cancel progress callback raised: {e}",
                )

        asset_id = cat_asset_id or cfg.CAT_ASSET_ID
        open_offers = get_open_offers(cat_asset_id=asset_id)

        # Apply side filter if specified (e.g. position circuit breaker only
        # wants to cancel buys when over-long, leaving sells live)
        _side = str(side_filter or "").strip().lower()
        if _side in ("buy", "sell"):
            open_offers = [o for o in open_offers if o.get("side", "") == _side]
            log_event(
                "info",
                "cancel_all",
                f"Side filter '{_side}' applied — cancelling {len(open_offers)} "
                f"{_side} offers only",
            )

        trade_ids = [o["trade_id"] for o in open_offers]

        # Fallback: if DB has nothing, check the wallet directly
        if not trade_ids:
            log_event(
                "info", "cancel_all", "DB has 0 open offers — fetching from wallet RPC"
            )
            try:
                all_wallet = get_all_offers(include_completed=False, start=0, end=500)
                if all_wallet:
                    open_buys, open_sells, _ = classify_offers_from_list(
                        all_wallet, asset_id
                    )
                    if _side == "buy":
                        side_offers = open_buys
                    elif _side == "sell":
                        side_offers = open_sells
                    else:
                        side_offers = open_buys + open_sells
                    for o in side_offers:
                        tid = o.get("trade_id", "")
                        if tid and tid not in trade_ids:
                            trade_ids.append(tid)
                    if trade_ids:
                        log_event(
                            "info",
                            "cancel_all",
                            f"Found {len(trade_ids)} open offers from wallet RPC",
                        )
            except Exception as e:
                log_event("error", "cancel_all", f"Wallet RPC fallback failed: {e}")

        if not trade_ids:
            self.expect_empty_wallet_offer_book("cancel_all_no_active_offers")
            emit_progress(
                running=False,
                complete=True,
                phase="complete",
                total=0,
                batch_size=0,
                total_batches=0,
                current_batch=0,
                cancelled=0,
                failed=0,
                message="No active offers found to cancel.",
            )
            return {}

        try:
            results = self.cancel_offers(
                trade_ids,
                reason="cancel_all",
                force_storm=True,
            )
        except Exception as exc:
            # No wallet effect is issued outside ``cancel_offers``.  If the
            # durable dispatcher itself is unavailable, keep every offer
            # non-terminal and return the same typed fail-closed shape callers
            # receive for an ambiguous journal outcome.
            log_event(
                "error",
                "cancel_all_journal_unavailable",
                f"Durable cancellation dispatcher failed: {type(exc).__name__}",
            )
            results = {}
            for trade_id in trade_ids:
                result = cancellation_result(
                    CANCEL_UNKNOWN,
                    method="journal_dispatch",
                    raw_response={
                        "reason_code": "DURABLE_CANCEL_UNAVAILABLE",
                        "error_type": type(exc).__name__,
                    },
                )
                result["_catalyst_effect_attempted"] = False
                result["_catalyst_idempotent_replay"] = False
                result["_catalyst_operation_id"] = f"cancel:{trade_id}"
                result["_catalyst_intent_id"] = f"cancel-target:{trade_id}"
                results[trade_id] = result
        submitted = sum(
            result.get("outcome") == CANCEL_SUBMITTED_UNCONFIRMED
            for result in results.values()
            if type(result) is dict
        )
        unknown = sum(
            result.get("outcome") == CANCEL_UNKNOWN
            for result in results.values()
            if type(result) is dict
        )
        failed = sum(
            result.get("outcome") == CANCEL_FAILED
            for result in results.values()
            if type(result) is dict
        )
        emit_progress(
            running=False,
            complete=True,
            phase="complete",
            total=len(trade_ids),
            batch_size=len(trade_ids),
            total_batches=1,
            current_batch=1,
            cancelled=0,
            confirmed=0,
            pending=submitted + unknown,
            failed=failed,
            message=(
                "Cancellation requests journaled; authoritative terminal "
                "reconciliation remains pending."
            ),
        )
        return results

    # -------------------------------------------------------------------
    # -------------------------------------------------------------------
    # Cache maintenance
    # -------------------------------------------------------------------

    def prune_caches(self, active_trade_ids: set = None):
        """Prune unbounded in-memory caches to prevent memory growth.

        Called periodically from housekeeping.
        """
        # Prune _bot_cancelled_ids — only remove IDs that are confirmed gone
        # AND are NOT pending a cancel retry. Removing an ID whose cancel is
        # still in-flight would cause fill_tracker to misinterpret the eventual
        # disappearance as a real fill (phantom fill bug).
        if active_trade_ids is not None and len(self._bot_cancelled_ids) > 500:
            pending_retry_ids = set(self._pending_cancel_retries.keys())
            safe_to_prune = (
                self._bot_cancelled_ids - active_trade_ids - pending_retry_ids
            )
            # Keep IDs that are still in active offers (cancel not confirmed yet)
            # or still queued for retry
            self._bot_cancelled_ids -= safe_to_prune

        # Prune _offer_details_cache — remove entries not in active offers
        if active_trade_ids is not None and len(self._offer_details_cache) > 200:
            stale = [k for k in self._offer_details_cache if k not in active_trade_ids]
            for k in stale:
                del self._offer_details_cache[k]

        # Prune _recently_created — remove expired entries
        now = time.time()
        expired = [
            k
            for k, t in self._recently_created.items()
            if now - t > self._recently_created_ttl
        ]
        for k in expired:
            del self._recently_created[k]

        # NOTE: _inflight_coin_ids is deliberately NOT cleared here.
        # Each _create_offer_with_retry_inner call adds a coin under
        # self._lock and has its own try/finally that discards it on
        # every exit path (success, failure, exception). A periodic
        # `clear()` here would race with slow in-flight creates that
        # have released the lock for the RPC call — clearing during
        # that RPC window would let another thread re-pick the same
        # coin and cause a MEMPOOL_CONFLICT or double-spend.

    # -------------------------------------------------------------------
    # Expiry management
    # -------------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """Observe locally expired offers without inferring terminality.

        Adapter and database compatibility helpers are both fail-closed. They
        may report diagnostics, but Task 9 owns cancellation/expiry proof and
        the associated reservation mutation.
        """
        count = cleanup_expired_offers()
        return _wallet_mutation_count(count) + len(self.cleanup_expired_db_offers())

    def cleanup_expired_db_offers(self) -> List[str]:
        """Run the guarded legacy expiry probe for observability.

        All durable offer rows remain open until authoritative Task 9 proof;
        local time and pending-cancel observations cannot retire them.
        """
        try:
            from database import expire_open_offers_by_time

            return expire_open_offers_by_time(cat_asset_id=cfg.CAT_ASSET_ID)
        except Exception as e:
            log_event(
                "warning",
                "local_expired_offer_cleanup_failed",
                f"Could not retire locally expired offers: {e}",
            )
            return []

    # -------------------------------------------------------------------
    # Offer state queries
    # -------------------------------------------------------------------

    def is_bot_cancelled(self, trade_id: str) -> bool:
        """Return True if this trade_id was cancelled by the bot.

        Non-destructive: does NOT remove the ID on read. The ID is removed
        when prune_caches() runs (safely, excluding pending retry IDs).
        This prevents phantom fills when a cancel takes multiple cycles
        to confirm on-chain.
        """
        return trade_id in self._bot_cancelled_ids

    def get_cached_details(self, trade_id: str) -> Optional[Dict]:
        """Get cached offer details for a trade_id."""
        return self._offer_details_cache.get(trade_id)

    def get_open_offer_count(self, side: str = None) -> int:
        """Count open offers, optionally by side."""
        offers = get_open_offers(side=side, cat_asset_id=cfg.CAT_ASSET_ID)
        return len(offers)

    # -------------------------------------------------------------------
    # Pre-emptive offer refresh (V1 parity: detect_expiring_offers)
    # -------------------------------------------------------------------

    def detect_expiring_offers(
        self, open_offers: list, refresh_before_secs: int = None
    ) -> List[str]:
        """Find offers approaching expiry so we can replace them BEFORE they die.

        V1 had this as detect_expiring_offers() — it's critical for continuous
        market presence. Without it, offers expire and there's a window with
        nothing on the book until the next cycle creates replacements.

        Args:
            open_offers: List of offer records from wallet sync
            refresh_before_secs: How far ahead to look (default: 5 min before expiry)

        Returns list of trade_ids that are about to expire.
        """
        if refresh_before_secs is None:
            refresh_before_secs = getattr(cfg, "OFFER_REFRESH_BEFORE", 1800)

        now = int(time.time())
        # Sniper and boost probes intentionally use short expiries. Wallet
        # records do not carry CATalyst's DB-only ``tier`` label, while this
        # input commonly contains both wallet and DB copies of the same offer.
        # Discover protected IDs across the complete merged view first so an
        # unlabeled wallet copy cannot be selected before its labeled DB copy.
        protected_ids = {
            offer.get("trade_id")
            for offer in open_offers
            if (offer.get("tier") or "").lower() in {"sniper", "boost"}
            and offer.get("trade_id")
        }
        expiring = []

        for offer in open_offers:
            trade_id = offer.get("trade_id", "")
            if trade_id in protected_ids:
                continue
            # Check valid_times.max_time from the wallet RPC record
            valid_times = offer.get("valid_times") or {}
            max_time = (
                valid_times.get("max_time", 0)
                or offer.get("max_time", 0)
                or offer.get("expires_at_second", 0)
            )

            if not max_time and offer.get("expires_at"):
                try:
                    from datetime import datetime, timezone

                    exp_time = datetime.fromisoformat(
                        str(offer.get("expires_at")).replace("Z", "+00:00")
                    )
                    if exp_time.tzinfo is None:
                        exp_time = exp_time.replace(tzinfo=timezone.utc)
                    max_time = int(exp_time.timestamp())
                except Exception:
                    max_time = 0

            try:
                max_time_int = int(max_time or 0)
            except Exception:
                max_time_int = 0

            if max_time_int > 0:
                time_left = max_time_int - now
                if 0 < time_left < refresh_before_secs:
                    if trade_id:
                        expiring.append(trade_id)

        expiring = list(dict.fromkeys(expiring))

        if expiring:
            log_event(
                "info",
                "expiring_soon",
                f"Found {len(expiring)} offers expiring within {refresh_before_secs}s",
            )

        return expiring

    # -------------------------------------------------------------------
    # Trim excess offers (Fix 3: belt-and-braces overshoot guard)
    # -------------------------------------------------------------------

    def trim_excess_offers(
        self, mid_price: Decimal, wallet_buys: list = None, wallet_sells: list = None
    ) -> int:
        """Cancel any offers above the configured per-side cap.

        Belt-and-braces guard against the requote overshoot the bot got
        into on 2026-04-07: when cancels were slow to confirm, repeated
        create-first requote rounds left the live book at 29 sells against
        a 24 cap. The over-allocation guard only blocked NEW creation; it
        never trimmed the excess. This method does the trim.

        When ``wallet_buys`` / ``wallet_sells`` are provided (from the
        wallet sync step), they are used as the ground-truth open-offer
        count instead of the DB.  This closes the gap where the DB has
        already marked a cancel-pending offer as "cancelled" but the
        wallet still holds it open — the DB would show 12 (under cap)
        while the wallet shows 20 (8 excess).

        Strategy: pick the offers furthest from `mid_price` on each side
        (least useful market-making) and cancel them until count == cap.

        Returns: total number of offers asked to cancel (across both sides).
        """

        # SINGLE SOURCE OF TRUTH: cap comes from the sum of tier counts in
        # the live ladder settings, not a separate MAX_ACTIVE_* key. This
        # ensures trim never fights the ladder the user asked for.
        def _ladder_cap(side: str) -> int:
            try:
                if side == "buy":
                    total = (
                        int(getattr(cfg, "BUY_INNER_TIER_COUNT", 0) or 0)
                        + int(getattr(cfg, "BUY_MID_TIER_COUNT", 0) or 0)
                        + int(getattr(cfg, "BUY_OUTER_TIER_COUNT", 0) or 0)
                        + int(getattr(cfg, "BUY_EXTREME_TIER_COUNT", 0) or 0)
                    )
                else:
                    total = (
                        int(getattr(cfg, "SELL_INNER_TIER_COUNT", 0) or 0)
                        + int(getattr(cfg, "SELL_MID_TIER_COUNT", 0) or 0)
                        + int(getattr(cfg, "SELL_OUTER_TIER_COUNT", 0) or 0)
                        + int(getattr(cfg, "SELL_EXTREME_TIER_COUNT", 0) or 0)
                    )
                if total > 0:
                    return total
            except Exception:
                pass
            # Fallback to legacy caps if tier counts are not available
            if side == "buy":
                return int(getattr(cfg, "MAX_ACTIVE_BUY_OFFERS", 25) or 25)
            return int(getattr(cfg, "MAX_ACTIVE_SELL_OFFERS", 25) or 25)

        max_buy = _ladder_cap("buy")
        max_sell = _ladder_cap("sell")

        try:
            mid_d = Decimal(str(mid_price or 0))
        except Exception:
            mid_d = Decimal("0")

        total_trimmed = 0

        _wallet_map = {"buy": wallet_buys, "sell": wallet_sells}

        for side, cap in (("buy", max_buy), ("sell", max_sell)):
            # Prefer wallet ground truth over DB — the wallet shows what
            # is ACTUALLY open on-chain, while the DB might have already
            # marked cancel-pending offers as "cancelled".
            _w_offers = _wallet_map.get(side)
            if _w_offers is not None:
                open_offers_all = list(_w_offers)
            else:
                try:
                    open_offers_all = (
                        get_open_offers(side=side, cat_asset_id=cfg.CAT_ASSET_ID) or []
                    )
                except Exception as e:
                    log_event(
                        "warning",
                        "trim_excess_query_failed",
                        f"trim_excess_offers: could not query open {side} offers: {e}",
                    )
                    continue

            # Exclude sniper-tier and boost-tier offers from the ladder cap
            # check — both are separate pools (sniper for arb snipes, boost
            # for Close the Gap probes) and must not cause ladder offers to
            # be cancelled. Without this, activating Close the Gap pushes
            # the count to ladder+1 each side and the trimmer cancels two
            # ladder offers per cycle, churning the book.
            #
            # Subtle: when wallet_buys/wallet_sells are passed in (the common
            # path), the offer dicts come from the WALLET and don't carry the
            # `tier` field — that's a DB-only label. We have to look up the
            # boost/sniper trade_ids from the DB and exclude them by id.
            try:
                _db_open = (
                    get_open_offers(side=side, cat_asset_id=cfg.CAT_ASSET_ID) or []
                )
                _excluded_ids = {
                    o.get("trade_id")
                    for o in _db_open
                    if (o.get("tier") or "").lower() in ("sniper", "boost")
                    and o.get("trade_id")
                }
            except Exception:
                _excluded_ids = set()
            open_offers = [
                o
                for o in open_offers_all
                if (o.get("tier") or "").lower() not in ("sniper", "boost")
                and o.get("trade_id") not in _excluded_ids
            ]

            # Exclude offers already pending cancel (fire-and-forget from
            # requote).  Without this, trim re-cancels the same offers,
            # wasting RPCs and filling the retry queue with noise.
            _pending = self._bot_cancelled_ids
            open_offers = [o for o in open_offers if o.get("trade_id") not in _pending]

            excess = len(open_offers) - cap
            if excess <= 0:
                continue

            # Fee coin dedication (via FeeCoinPool) eliminates the
            # MEMPOOL_CONFLICT risk that previously required a per-cycle cap.
            # Each cancel batch now reserves its own fee coin, so we can
            # trim all excess in one shot instead of spreading across cycles.

            def _distance_from_mid(o):
                try:
                    p = Decimal(str(o.get("price_xch") or o.get("price") or 0))
                    if p <= 0 or mid_d <= 0:
                        return Decimal("0")
                    return abs(p - mid_d)
                except Exception:
                    return Decimal("0")

            # Sort furthest-from-mid first; those carry the least
            # market-making value, so they're the safest to drop.
            sorted_offers = sorted(open_offers, key=_distance_from_mid, reverse=True)
            to_cancel = sorted_offers[:excess]
            cancel_ids = [o.get("trade_id") for o in to_cancel if o.get("trade_id")]

            if not cancel_ids:
                continue

            log_event(
                "info",
                "trim_excess_offers",
                f"Trim pass: {side} open={len(open_offers)} > cap={cap}, "
                f"cancelling {len(cancel_ids)} furthest-from-mid offer(s)",
            )

            try:
                self.cancel_offers(
                    cancel_ids, reason="trim_excess", skip_confirmation=True
                )
                total_trimmed += len(cancel_ids)
            except Exception as e:
                log_event(
                    "error",
                    "trim_excess_cancel_failed",
                    f"trim_excess_offers: cancel call failed for {side}: {e}",
                )

        return total_trimmed

    # -------------------------------------------------------------------
    # Retry failed cancels (V1 parity: retry_failed_cancels)
    # -------------------------------------------------------------------

    def get_active_cancel_settlement_operation(self) -> Optional[str]:
        """Return the exact retry operation currently awaiting Task 9 proof."""

        with self._cancel_settlement_lock:
            return self._cancel_settlement_operation_id

    def _begin_cancel_settlement(self, operation_id: str) -> bool:
        if type(operation_id) is not str or not operation_id:
            return False
        with self._cancel_settlement_lock:
            if self._cancel_settlement_operation_id is not None:
                return False
            self._cancel_settlement_operation_id = operation_id
            return True

    def _end_cancel_settlement(self, operation_id: str) -> None:
        with self._cancel_settlement_lock:
            if self._cancel_settlement_operation_id == operation_id:
                self._cancel_settlement_operation_id = None

    @staticmethod
    def _settle_submitted_cancel(
        intent: _CanonicalOfferCancelIntent,
    ) -> bool:
        """Release one cancel latch only after exact authoritative proof.

        A successful Sage submission is not a terminal outcome.  Retry callers
        must therefore wait for Task 9 reconciliation before attempting the
        next wallet mutation; otherwise the next retry collides with the latch
        raised for this operation and stops the bot.
        """

        import offer_reconciliation

        try:
            latch = database.get_runtime_safety_latch()
            blockers = database.get_unresolved_offer_operation_blockers()
            blocker_ids = [row.get("operation_id") for row in blockers]
            generation = latch.get("generation")
            if (
                latch.get("state") != "tripped"
                or type(generation) is not int
                or isinstance(generation, bool)
                or generation < 1
                or blocker_ids != [intent.operation_id]
            ):
                return False
        except Exception:
            return False

        max_wait = max(0.0, float(cfg.CANCEL_MAX_WAIT_SECS))
        poll_interval = max(0.05, float(cfg.CANCEL_POLL_INTERVAL_SECS))
        deadline = time.monotonic() + max_wait
        while True:
            try:
                intent_row = database.get_offer_intent(intent.intent_id)
                if (
                    type(intent_row) is not dict
                    or intent_row.get("sage_trade_id") != intent.trade_id
                ):
                    return False
                evidence = offer_reconciliation.load_authoritative_evidence(intent_row)
                observed_at = offer_reconciliation._clock_utc()
                cancel_context = offer_reconciliation._derive_single_cancel_context(
                    intent_row,
                    evidence,
                    database_module=database,
                    observed_at=observed_at,
                )
                classification = offer_reconciliation.classify_terminal_evidence(
                    intent_row,
                    evidence,
                    cancel_context=cancel_context,
                    now=observed_at,
                )
                if (
                    cancel_context is not None
                    and classification.get("classification")
                    == offer_reconciliation.CANCELLED_PROVEN
                ):
                    reconciled = offer_reconciliation.reconcile_offer(
                        intent.intent_id,
                        evidence=evidence,
                        cancel_context=cancel_context,
                        now=observed_at,
                    )
                    if (
                        reconciled.get("classification")
                        == offer_reconciliation.CANCELLED_PROVEN
                        and reconciled.get("applied") is True
                    ):
                        runtime = mutation_gate.current_runtime()
                        if runtime is None:
                            return False
                        released = runtime.release_resolved(
                            generation,
                            [intent.operation_id],
                        )
                        if released.get("released") is True:
                            return True
                        # The transactional reconciliation may have resolved
                        # the durable latch itself.  In that case, accept the
                        # transition only when this exact generation is clear
                        # and the live runtime independently reports allowed.
                        post_latch = database.get_runtime_safety_latch()
                        post_blockers = (
                            database.get_unresolved_offer_operation_blockers()
                        )
                        status_reader = getattr(runtime, "status", None)
                        runtime_status = (
                            status_reader() if callable(status_reader) else None
                        )
                        runtime_allowed = (
                            runtime_status.get("allowed") is True
                            if type(runtime_status) is dict
                            else getattr(runtime_status, "allowed", False) is True
                        )
                        return bool(
                            post_latch.get("state") == "resolved"
                            and post_latch.get("generation") == generation
                            and not post_blockers
                            and runtime_allowed
                        )
            except Exception:
                # Read-only evidence can be briefly incomplete while Sage is
                # confirming the spend.  Never infer success from that gap.
                pass

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(poll_interval, remaining))

    @staticmethod
    def _reconcile_elapsed_cancel_retry(
        intent: _CanonicalOfferCancelIntent,
        offer: Any,
        *,
        now_timestamp: float,
    ) -> Optional[bool]:
        """Reconcile an already-terminal offer before retrying its cancel.

        A failed batch peer can naturally expire while another member awaits
        confirmation.  Retrying the stale peer through Sage creates a second,
        redundant wallet spend and immediately closes the safety gate.  Once
        the durable expiry has elapsed (or the DB is already terminal), use
        Task 9 evidence instead.  ``None`` means the offer is still eligible
        for an ordinary retry; ``False`` means proof is not ready and the
        wallet effect must be skipped this pass.
        """

        if type(offer) is not dict:
            return None
        status = str(offer.get("status") or "").strip().lower()
        should_reconcile = status in {"cancelled", "expired"}
        expires_at = offer.get("expires_at")
        if not should_reconcile and expires_at:
            try:
                expiry = datetime.fromisoformat(
                    str(expires_at).strip().replace("Z", "+00:00")
                )
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                should_reconcile = expiry <= datetime.fromtimestamp(
                    now_timestamp, tz=timezone.utc
                )
            except (OverflowError, OSError, TypeError, ValueError):
                should_reconcile = False
        if not should_reconcile:
            return None

        try:
            import offer_reconciliation

            intent_row = database.get_offer_intent(intent.intent_id)
            if (
                type(intent_row) is not dict
                or intent_row.get("sage_trade_id") != intent.trade_id
            ):
                return False
            terminal = {
                offer_reconciliation.FILLED_PROVEN,
                offer_reconciliation.CANCELLED_PROVEN,
                offer_reconciliation.EXPIRED_PROVEN,
            }
            if intent_row.get("lifecycle_state") == "terminal":
                authoritative = database.get_authoritative_terminal_record(
                    intent.trade_id
                )
                if (
                    type(authoritative) is dict
                    and authoritative.get("intent_id") == intent.intent_id
                    and authoritative.get("sage_trade_id") == intent.trade_id
                    and authoritative.get("operation_id")
                    == f"reconcile:{intent.intent_id}"
                    and authoritative.get("outcome") in terminal
                ):
                    return True
                return False
            result = offer_reconciliation.reconcile_offer(intent.intent_id)
            if (
                result.get("applied") is True
                and result.get("classification") in terminal
            ):
                return True
            log_event(
                "info",
                "cancel_retry_terminal_reconciliation_pending",
                f"Offer {intent.trade_id[:16]}... is past its terminal bound; "
                "awaiting authoritative reconciliation instead of submitting "
                "another cancel",
                data={
                    "trade_id": intent.trade_id,
                    "classification": result.get("classification"),
                    "reason_code": result.get("reason_code"),
                },
            )
        except Exception as exc:
            log_event(
                "warning",
                "cancel_retry_terminal_reconciliation_failed",
                f"Could not reconcile elapsed offer {intent.trade_id[:16]}...: "
                f"{type(exc).__name__}",
                data={"trade_id": intent.trade_id},
            )
        return False

    def retry_failed_cancels(self) -> int:
        """Retry exact durable failures; memory is only a health-reporting cache."""
        # A batch deliberately aborts later members after one cancellation
        # crosses the submitted-but-unconfirmed boundary. Reconcile that exact
        # blocker before reading or retrying failed peers; otherwise the retry
        # attempts a second wallet mutation behind a closed safety gate.
        try:
            blockers = database.get_unresolved_offer_operation_blockers()
        except Exception as exc:
            log_event(
                "error",
                "cancel_settlement_journal_unavailable",
                f"Could not read unresolved cancellations: {type(exc).__name__}",
            )
            return -1
        if blockers:
            if len(blockers) != 1:
                return -1
            operation_id = blockers[0].get("operation_id")
            if not self._is_canonical_cancel_digest_id(operation_id, "cancel:"):
                return -1
            intent = self._canonical_cancel_intent(operation_id.removeprefix("cancel:"))
            if not self._begin_cancel_settlement(intent.operation_id):
                return -1
            try:
                if not self._settle_submitted_cancel(intent):
                    return -1
            finally:
                self._end_cancel_settlement(intent.operation_id)

        try:
            candidates = database.get_retryable_failed_offer_cancels()
        except Exception as exc:
            log_event(
                "error",
                "cancel_retry_journal_unavailable",
                f"Could not read durable failed cancellations: {type(exc).__name__}",
            )
            return 0

        durable_ids = set()
        now = time.time()
        for candidate in candidates:
            try:
                trade_id = candidate["trade_id"]
                attempt = candidate["attempt"]
                intent = self._canonical_cancel_intent(trade_id)
                if (
                    candidate["operation_id"] != intent.operation_id
                    or type(attempt) is not int
                    or isinstance(attempt, bool)
                    or attempt < 1
                ):
                    raise ValueError("durable cancellation retry candidate is invalid")
                existing_result = self._existing_cancel_result(intent)
                if (
                    existing_result is None
                    or existing_result.get("outcome") != CANCEL_FAILED
                    or existing_result.get("_catalyst_attempt") != attempt
                ):
                    raise ValueError("durable cancellation retry candidate is stale")
                failed_at = datetime.fromisoformat(
                    candidate["created_at"].replace("Z", "+00:00")
                )
                if failed_at.tzinfo is None:
                    failed_at = failed_at.replace(tzinfo=timezone.utc)
                failed_timestamp = failed_at.astimezone(timezone.utc).timestamp()
            except (KeyError, TypeError, ValueError):
                continue

            durable_ids.add(trade_id)
            self._bot_cancelled_ids.discard(trade_id)
            prior_retry = self._pending_cancel_retries.get(trade_id, {})
            self._pending_cancel_retries[trade_id] = {
                "attempts": attempt,
                "first_failed": prior_retry.get("first_failed", failed_timestamp),
            }
            try:
                offer = database.get_offer(trade_id)
            except Exception:
                offer = None
            if offer and (offer.get("status") == "filled" or offer.get("filled_at")):
                self._pending_cancel_retries.pop(trade_id, None)
                continue
            terminal_reconciled = self._reconcile_elapsed_cancel_retry(
                intent,
                offer,
                now_timestamp=now,
            )
            if terminal_reconciled is not None:
                if terminal_reconciled:
                    self._pending_cancel_retries.pop(trade_id, None)
                    self._bot_cancelled_ids.discard(trade_id)
                # Even incomplete terminal proof is a reason to wait, never
                # to submit a redundant wallet mutation for an elapsed offer.
                continue
            if attempt >= self._max_cancel_retries:
                continue
            retry_after = self._cancel_retry_backoff_seconds * (2 ** (attempt - 1))
            if now < failed_timestamp + retry_after:
                continue
            if not self._begin_cancel_settlement(intent.operation_id):
                return -1
            try:
                results = self.cancel_offers(
                    [trade_id],
                    reason="retry_failed_cancel",
                    force_storm=True,
                    _retry_failed_attempts={trade_id: attempt},
                )
                result = results.get(trade_id)
                if type(result) is not dict:
                    return -1
                outcome = result.get("outcome")
                if outcome == CANCEL_SUBMITTED_UNCONFIRMED:
                    if not self._settle_submitted_cancel(intent):
                        log_event(
                            "warning",
                            "cancel_retry_confirmation_pending",
                            "A submitted cancel still requires exact authoritative "
                            "confirmation; no further wallet mutation will run this cycle",
                            data={"operation_id": intent.operation_id},
                        )
                        return -1
                elif outcome == CANCEL_UNKNOWN:
                    return -1
            finally:
                self._end_cancel_settlement(intent.operation_id)

        for trade_id in set(self._pending_cancel_retries) - durable_ids:
            self._pending_cancel_retries.pop(trade_id, None)
            self._bot_cancelled_ids.discard(trade_id)
        return 0

    # -------------------------------------------------------------------
    # Recently-created tracking (V1 parity: prevents over-creation)
    # -------------------------------------------------------------------

    def clean_visible_recently_created(self, visible_ids: set):
        """Remove recently-created offers that now appear in wallet sync.

        Without this, offers get double-counted: once in the wallet sync
        count and once in the recently-created count. This would make the
        bot think it has more offers than it really does and skip creating.
        """
        to_remove = [tid for tid in self._recently_created if tid in visible_ids]
        for tid in to_remove:
            self._recently_created.pop(tid, None)

    def forget_recently_created(self, trade_id: str):
        """Drop a recently-created marker after the offer reaches a terminal state."""
        if trade_id:
            self._recently_created.pop(trade_id, None)

    def get_recently_created_ids_by_side(self) -> Dict[str, set]:
        """Return live recently-created IDs grouped by cached offer side."""
        now = time.time()
        grouped = {"buy": set(), "sell": set()}
        expired_keys = []

        for tid, info_time in self._recently_created.items():
            if now - info_time > self._recently_created_ttl:
                expired_keys.append(tid)
                continue
            detail = self._offer_details_cache.get(tid, {})
            side = detail.get("side")
            if side in grouped:
                grouped[side].add(tid)

        for key in expired_keys:
            self._recently_created.pop(key, None)

        return grouped

    def get_recently_created_count(self, side: str) -> int:
        """Count offers created recently that might not be visible in wallet yet.

        V1 tracked this to prevent creating too many offers when the wallet
        RPC hasn't caught up yet. Only counts offers NOT yet visible in
        wallet sync (clean_visible_recently_created removes the visible ones).
        """
        now = time.time()
        count = 0
        expired_keys = []

        for tid, info_time in self._recently_created.items():
            if now - info_time > self._recently_created_ttl:
                expired_keys.append(tid)
            else:
                detail = self._offer_details_cache.get(tid, {})
                if detail.get("side") == side:
                    count += 1

        # Prune expired entries
        for k in expired_keys:
            self._recently_created.pop(k, None)

        return count

    # -------------------------------------------------------------------
    # Wallet sync
    # -------------------------------------------------------------------

    def get_wallet_sync_meta(self) -> Dict[str, Any]:
        """Return lightweight metadata about the last wallet offer sync."""
        return dict(self._wallet_sync_meta)

    def get_wallet_sync_snapshot(self) -> Dict[str, Any]:
        """Return a defensive copy of the last wallet-authoritative offer book."""
        return {
            "buy": [dict(o) for o in self._wallet_sync_cache.get("buy", [])],
            "sell": [dict(o) for o in self._wallet_sync_cache.get("sell", [])],
            "closed": [dict(o) for o in self._wallet_sync_cache.get("closed", [])],
            "meta": dict(self._wallet_sync_meta),
        }

    def expect_empty_wallet_offer_book(
        self, reason: str, ttl_seconds: int = 180
    ) -> None:
        """Allow the next empty wallet offer sync after an intentional cancel-all."""
        self._expected_empty_wallet_book = {
            "until": time.time() + max(1, int(ttl_seconds or 1)),
            "reason": str(reason or "expected_empty_offer_book"),
        }

    def _cached_wallet_offer_ids(self) -> set:
        ids = set()
        for side in ("buy", "sell"):
            for offer in self._wallet_sync_cache.get(side, []) or []:
                tid = offer.get("trade_id") or offer.get("offer_id")
                if tid:
                    ids.add(str(tid))
        return ids

    def _worker_cancelled_empty_reason(self, cached_ids: set) -> str:
        """Return a reason when coin prep intentionally cancelled cached offers."""
        if not cached_ids:
            return ""

        try:
            from user_paths import worker_cancelled_ids_file

            cancelled_path = worker_cancelled_ids_file()
        except Exception:
            cancelled_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "worker_cancelled_ids.json",
            )

        if not cancelled_path or not os.path.exists(cancelled_path):
            return ""

        try:
            with open(cancelled_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                cancelled_ids = payload.get("cancelled_ids") or []
            else:
                cancelled_ids = payload or []
            cancelled_set = {
                str(tid).strip() for tid in cancelled_ids if str(tid).strip()
            }
        except Exception as e:
            log_event(
                "debug",
                "worker_cancelled_ids_read_failed",
                f"Could not inspect coin-prep cancelled IDs: {e}",
            )
            return ""

        if cached_ids.issubset(cancelled_set):
            return "coin_prep_cancel_all"
        return ""

    def _db_empty_offer_book_reason(self) -> str:
        """Return a reason when the DB has no active offers to protect in cache."""
        try:
            active_offers = get_open_offers(cat_asset_id=cfg.CAT_ASSET_ID)
        except Exception as e:
            log_event(
                "debug",
                "db_active_offer_check_failed",
                f"Could not inspect active DB offers before accepting empty wallet: {e}",
            )
            return ""
        if not active_offers:
            return "db_no_active_offers"

        # Sage can retain an offer's open-looking status after its max-time
        # has elapsed, while omitting that max-time from get_offers.  The
        # durable row still has the exact expiry written when CATalyst created
        # the offer.  If every protected row is locally expired, accepting the
        # wallet's empty book is safe and avoids pinning a stale resume cache.
        now_dt = datetime.now(timezone.utc)
        for offer in active_offers:
            expires_at = offer.get("expires_at")
            if not expires_at:
                return ""
            try:
                expiry_dt = datetime.fromisoformat(
                    str(expires_at).replace("Z", "+00:00")
                )
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                return ""
            if expiry_dt > now_dt:
                return ""
        return "db_all_offers_expired"

    def _expected_empty_wallet_reason(self, now_ts: float, cached_ids: set) -> str:
        expected_until = float(
            self._expected_empty_wallet_book.get("until", 0.0) or 0.0
        )
        if expected_until >= now_ts:
            return str(
                self._expected_empty_wallet_book.get("reason", "")
                or "expected_empty_offer_book"
            )
        return self._worker_cancelled_empty_reason(cached_ids) or (
            self._db_empty_offer_book_reason() if cached_ids else ""
        )

    def sync_from_wallet(self) -> Tuple[List, List, List]:
        """Sync offer state from the Chia wallet RPC.

        Fetches all offers from the wallet and classifies them.
        Returns (open_buys, open_sells, closed).

        CRITICAL: Uses include_completed=False to only get open offers.
        With include_completed=True, old cancelled/completed offers flood
        the result window (end=500) and push genuinely open offers out
        of the results — the exact V1 truncation bug but at 200 instead
        of 50. By excluding completed, we only get what matters.
        """
        # Only fetch non-completed offers — avoids truncation by old cancelled offers
        all_offers = get_all_offers(include_completed=False, start=0, end=500)
        if all_offers is None:
            err = str(
                getattr(get_all_offers, "_last_error", "")
                or "wallet get_offers unavailable"
            )
            self._wallet_sync_meta["fresh"] = False
            self._wallet_sync_meta["using_cache"] = bool(
                self._wallet_sync_cache["buy"]
                or self._wallet_sync_cache["sell"]
                or self._wallet_sync_cache["closed"]
            )
            self._wallet_sync_meta["consecutive_failures"] = (
                int(self._wallet_sync_meta.get("consecutive_failures", 0) or 0) + 1
            )
            self._wallet_sync_meta["last_error"] = err
            self._wallet_sync_meta["last_failure_at"] = time.time()
            self._wallet_sync_meta["cache_size"] = len(
                self._wallet_sync_cache["buy"]
            ) + len(self._wallet_sync_cache["sell"])

            if self._wallet_sync_meta["consecutive_failures"] == 1:
                if self._wallet_sync_meta["using_cache"]:
                    log_event(
                        "warning",
                        "wallet_sync_cache",
                        f"Wallet offer sync failed — using last known offer book. {err}",
                    )
                else:
                    log_event(
                        "warning",
                        "wallet_sync_unavailable",
                        f"Wallet offer sync failed and no cached book is available. {err}",
                    )

            return (
                [dict(o) for o in self._wallet_sync_cache["buy"]],
                [dict(o) for o in self._wallet_sync_cache["sell"]],
                [dict(o) for o in self._wallet_sync_cache["closed"]],
            )

        open_buy, open_sell, closed = classify_offers_from_list(
            all_offers, cfg.CAT_ASSET_ID
        )

        # Suspicious-empty guard: Sage's get_offers occasionally returns a
        # valid-but-empty response during a sync hiccup — same RPC blip
        # that produces "get_coins(selectable) returned 0 coins (total=0)"
        # warnings. Without this guard the empty response would (a) flush
        # the cache, (b) make every cycle's mass_disappearance_guard
        # strike, and (c) eventually trip the 3-strike acceptance and
        # pause trading on a wallet that's actually fine.
        #
        # Treat "we had >=5 offers a moment ago and now Sage returns 0"
        # as a transient hiccup: keep the cached view, mark fresh=False,
        # and let the fill-tracker's existing not-fresh check absorb the
        # cycle. Real bulk cancellations recover on the very next poll
        # (mass guard accepts after 3 strikes anyway), so the false-
        # positive cost is negligible compared to a paused bot.
        prev_total = len(self._wallet_sync_cache["buy"]) + len(
            self._wallet_sync_cache["sell"]
        )
        curr_total = len(open_buy) + len(open_sell)
        _now = time.time()
        expected_empty_reason = ""
        if curr_total == 0 and prev_total >= 5:
            expected_empty_reason = self._expected_empty_wallet_reason(
                _now,
                self._cached_wallet_offer_ids(),
            )
            if expected_empty_reason:
                self._expected_empty_wallet_book = {"until": 0.0, "reason": ""}
                log_event(
                    "info",
                    "wallet_sync_expected_empty",
                    f"Wallet returned 0 offers after {expected_empty_reason}; "
                    f"accepting empty book instead of cached {prev_total}-offer view",
                )
            else:
                suspicious_error = f"suspicious_empty_offers (prev={prev_total})"
                suspicious_log_key = f"suspicious_empty_offers:{prev_total}"
                self._wallet_sync_meta.update(
                    {
                        "fresh": False,
                        "using_cache": True,
                        "consecutive_failures": int(
                            self._wallet_sync_meta.get("consecutive_failures", 0) or 0
                        )
                        + 1,
                        "last_error": suspicious_error,
                        "last_failure_at": _now,
                        "cache_size": prev_total,
                    }
                )
                if (
                    self._wallet_sync_meta.get("last_suspicious_empty_log_key")
                    != suspicious_log_key
                ):
                    self._wallet_sync_meta["last_suspicious_empty_log_key"] = (
                        suspicious_log_key
                    )
                    self._wallet_sync_meta["suspicious_empty_suppressed"] = 0
                    log_event(
                        "warning",
                        "wallet_sync_suspicious_empty",
                        f"Wallet returned 0 offers but had {prev_total} a moment ago - "
                        f"treating as Sage sync hiccup, using cached view this cycle",
                    )
                else:
                    self._wallet_sync_meta["suspicious_empty_suppressed"] = (
                        int(
                            self._wallet_sync_meta.get("suspicious_empty_suppressed", 0)
                            or 0
                        )
                        + 1
                    )
                return (
                    [dict(o) for o in self._wallet_sync_cache["buy"]],
                    [dict(o) for o in self._wallet_sync_cache["sell"]],
                    [dict(o) for o in self._wallet_sync_cache["closed"]],
                )

        previous_failures = int(
            self._wallet_sync_meta.get("consecutive_failures", 0) or 0
        )
        self._wallet_sync_cache["buy"] = [dict(o) for o in open_buy]
        self._wallet_sync_cache["sell"] = [dict(o) for o in open_sell]
        self._wallet_sync_cache["closed"] = [dict(o) for o in closed]
        self._wallet_sync_meta.update(
            {
                "fresh": True,
                "using_cache": False,
                "consecutive_failures": 0,
                "last_error": "",
                "last_success_at": time.time(),
                "cache_size": len(open_buy) + len(open_sell),
                "last_suspicious_empty_log_key": "",
                "suspicious_empty_suppressed": 0,
            }
        )
        if expected_empty_reason:
            self._wallet_sync_meta["expected_empty_reason"] = expected_empty_reason
        else:
            self._wallet_sync_meta.pop("expected_empty_reason", None)

        if previous_failures > 0:
            log_event(
                "info",
                "wallet_sync_recovered",
                f"Wallet offer sync recovered after {previous_failures} failed poll(s)",
            )

        return open_buy, open_sell, closed
