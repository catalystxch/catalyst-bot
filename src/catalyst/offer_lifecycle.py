"""Pure state-machine definitions for offer tracking

Defines the `OfferState` and `OfferSignal` enums plus `apply_signal(state, signal)
-> OfferTransition`, which is the single authority for legal offer state changes.
This module is stateless and has no external dependencies — callers feed in a
state and a signal and receive back the new state and a recommended action.

Key responsibilities:
    - Enumerate extended lifecycle states and the signals that drive them
    - Compute deterministic `(state, signal) -> transition` results
    - Preserve backward compatibility with the legacy 4-value `status` column
      through `coarse_status()`

Legacy transitions remain available for existing callers.  New stability-kernel
callers must route terminal-looking signals through
``signal_requires_registry_proof()`` and the stricter :mod:`offer_registry`
authorization policy before persisting a terminal registry state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class OfferState(StrEnum):
    """Extended offer lifecycle states."""

    OPEN = "open"  # live on wallet, tradeable
    REFRESH_DUE = "refresh_due"  # expiry approaching, needs requote
    CANCEL_REQUESTED = "cancel_requested"  # cancel RPC sent, awaiting confirmation
    CANCELLED = "cancelled"  # terminal: cancel confirmed
    MEMPOOL_OBSERVED = "mempool_observed"  # potential take seen in mempool
    FILLED = "filled"  # terminal: fill detected & verified
    EXPIRED = "expired"  # terminal: time-expired
    NOT_SUBMITTED = "not_submitted"  # terminal: local row never became wallet-visible
    PHANTOM_REJECTED = "phantom_rejected"  # terminal: self-spend/false fill rejected


class OfferSignal(StrEnum):
    """Signals that drive state transitions."""

    EXPIRY_NEAR = "expiry_near"  # refresh window entered
    CANCEL_SENT = "cancel_sent"  # cancel RPC dispatched
    CANCEL_CONFIRMED = "cancel_confirmed"  # wallet confirmed cancel
    CANCEL_FAILED = "cancel_failed"  # cancel RPC failed, revert to previous
    FILL_DETECTED = "fill_detected"  # offer disappeared (not our cancel)
    FILL_VERIFIED = "fill_verified"  # on-chain verification passed
    FILL_REJECTED = "fill_rejected"  # phantom/self-spend detected
    TIME_EXPIRED = "time_expired"  # max_time passed
    REFRESH_POSTED = "refresh_posted"  # replacement offer created
    MEMPOOL_SEEN = "mempool_seen"  # potential take in mempool


@dataclass(frozen=True, slots=True)
class OfferTransition:
    """Result of applying a signal to a state."""

    old_state: OfferState
    new_state: OfferState
    signal: OfferSignal
    action: str  # what the caller should do
    reason: str  # human-readable explanation


@dataclass(frozen=True, slots=True)
class PublicationDiscoveryDecision:
    """Mutation instruction derived from exact public discovery evidence."""

    action: str
    reason_code: str
    exact_providers: tuple[str, ...] = ()
    mismatched_providers: tuple[str, ...] = ()
    retry_after_seconds: int = 0


class OfferDiscoveryTracker:
    """Require exact rediscovery within 90 seconds before an offer stays live."""

    publication_targets = ("dexie", "splash")
    discovery_deadline_seconds = 90

    def __init__(self, *, offer_identity: str, created_at: datetime) -> None:
        self.offer_identity = self._identity(offer_identity)
        self.created_at = self._time(created_at, "created_at")
        self._submissions: dict[str, bool] = {}
        self._exact_providers: set[str] = set()
        self._mismatched_providers: set[str] = set()

    def record_submission(self, *, provider: str, succeeded: bool) -> None:
        provider_id = self._provider(provider)
        if type(succeeded) is not bool:
            raise TypeError("succeeded must be a boolean")
        self._submissions[provider_id] = succeeded

    def record_discovery(self, *, provider: str, observed_offer_identity: str) -> None:
        provider_id = self._provider(provider)
        observed = self._identity(observed_offer_identity)
        if observed == self.offer_identity:
            self._exact_providers.add(provider_id)
            self._mismatched_providers.discard(provider_id)
        elif provider_id not in self._exact_providers:
            self._mismatched_providers.add(provider_id)

    def evaluate(self, *, now: datetime) -> PublicationDiscoveryDecision:
        current = self._time(now, "now")
        exact = tuple(sorted(self._exact_providers))
        mismatched = tuple(sorted(self._mismatched_providers))
        if exact:
            return PublicationDiscoveryDecision(
                action="KEEP_LIVE",
                reason_code="PUBLICATION_EXACTLY_DISCOVERED",
                exact_providers=exact,
                mismatched_providers=mismatched,
            )
        elapsed = (current - self.created_at).total_seconds()
        if elapsed >= self.discovery_deadline_seconds:
            return PublicationDiscoveryDecision(
                action="CANCEL_VIA_SAGE",
                reason_code="PUBLICATION_DISCOVERY_DEADLINE_EXCEEDED",
                mismatched_providers=mismatched,
            )
        return PublicationDiscoveryDecision(
            action="WAIT_FOR_DISCOVERY",
            reason_code="PUBLICATION_DISCOVERY_PENDING",
            mismatched_providers=mismatched,
            retry_after_seconds=max(0, self.discovery_deadline_seconds - int(elapsed)),
        )

    def replacement_decision(
        self,
        *,
        authoritative_terminal: bool,
        terminal_at: datetime | None,
        attempt: int,
        now: datetime,
    ) -> PublicationDiscoveryDecision:
        if type(authoritative_terminal) is not bool:
            raise TypeError("authoritative_terminal must be a boolean")
        if type(attempt) is not int or attempt < 0:
            raise ValueError("attempt must be a nonnegative integer")
        current = self._time(now, "now")
        if not authoritative_terminal or terminal_at is None:
            return PublicationDiscoveryDecision(
                action="BLOCK_REPLACEMENT",
                reason_code="AUTHORITATIVE_TERMINAL_PROOF_REQUIRED",
            )
        terminal = self._time(terminal_at, "terminal_at")
        delay = min(300, 5 * (2**attempt))
        remaining = delay - int((current - terminal).total_seconds())
        if remaining > 0:
            return PublicationDiscoveryDecision(
                action="WAIT_REPLACEMENT_BACKOFF",
                reason_code="REPLACEMENT_BACKOFF_ACTIVE",
                retry_after_seconds=remaining,
            )
        return PublicationDiscoveryDecision(
            action="ALLOW_REPLACEMENT",
            reason_code="TERMINAL_PROOF_AND_BACKOFF_SATISFIED",
        )

    def authorize_duplicate_create(self, offer_identity: str) -> bool:
        """Reject a retry for the same still-tracked economic offer."""

        return self._identity(offer_identity) != self.offer_identity

    def to_state(self) -> dict[str, Any]:
        return {
            "offer_identity": self.offer_identity,
            "created_at": self.created_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "submissions": dict(sorted(self._submissions.items())),
            "exact_providers": sorted(self._exact_providers),
            "mismatched_providers": sorted(self._mismatched_providers),
        }

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "OfferDiscoveryTracker":
        if not isinstance(state, Mapping):
            raise TypeError("discovery state must be a mapping")
        timestamp = str(state["created_at"])
        created_at = datetime.fromisoformat(
            timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
        )
        tracker = cls(
            offer_identity=str(state["offer_identity"]), created_at=created_at
        )
        submissions = state.get("submissions", {})
        if not isinstance(submissions, Mapping):
            raise ValueError("submissions must be a mapping")
        for provider, succeeded in submissions.items():
            tracker.record_submission(provider=str(provider), succeeded=succeeded)
        for provider in state.get("exact_providers", []):
            tracker._exact_providers.add(tracker._provider(provider))
        for provider in state.get("mismatched_providers", []):
            tracker._mismatched_providers.add(tracker._provider(provider))
        return tracker

    @staticmethod
    def _provider(value: str) -> str:
        provider = str(value).strip().lower()
        if provider not in OfferDiscoveryTracker.publication_targets:
            raise ValueError("provider must be dexie or splash")
        return provider

    @staticmethod
    def _identity(value: str) -> str:
        identity = str(value).strip().lower()
        if len(identity) != 64 or any(
            character not in "0123456789abcdef" for character in identity
        ):
            raise ValueError("offer identity must be a 32-byte hex value")
        return identity

    @staticmethod
    def _time(value: datetime, label: str) -> datetime:
        if type(value) is not datetime or value.tzinfo is None:
            raise TypeError(f"{label} must be a timezone-aware datetime")
        return value.astimezone(timezone.utc)


# Terminal states — no further transitions allowed
_TERMINAL_STATES = frozenset(
    {
        OfferState.CANCELLED,
        OfferState.FILLED,
        OfferState.EXPIRED,
        OfferState.NOT_SUBMITTED,
        OfferState.PHANTOM_REJECTED,
    }
)


def apply_signal(state: OfferState, signal: OfferSignal) -> OfferTransition:
    """Pure function: apply a signal to an offer state, return transition.

    If the signal is invalid for the current state, returns a noop transition.
    """
    # Terminal states reject all signals
    if state in _TERMINAL_STATES:
        return OfferTransition(
            old_state=state,
            new_state=state,
            signal=signal,
            action="noop",
            reason="offer_in_terminal_state",
        )

    # ---- OPEN state transitions ----
    if state == OfferState.OPEN:
        if signal == OfferSignal.EXPIRY_NEAR:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.REFRESH_DUE,
                signal=signal,
                action="schedule_requote",
                reason="refresh_window_entered",
            )
        if signal == OfferSignal.CANCEL_SENT:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.CANCEL_REQUESTED,
                signal=signal,
                action="await_cancel_confirm",
                reason="cancel_dispatched",
            )
        if signal == OfferSignal.FILL_DETECTED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.FILLED,
                signal=signal,
                action="record_fill",
                reason="offer_disappeared_not_our_cancel",
            )
        if signal == OfferSignal.TIME_EXPIRED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.EXPIRED,
                signal=signal,
                action="cleanup_expired",
                reason="offer_time_expired",
            )
        if signal == OfferSignal.MEMPOOL_SEEN:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.MEMPOOL_OBSERVED,
                signal=signal,
                action="mark_mempool_observed",
                reason="potential_take_seen",
            )

    # ---- REFRESH_DUE transitions ----
    if state == OfferState.REFRESH_DUE:
        if signal == OfferSignal.REFRESH_POSTED:
            # This offer is being replaced — mark it cancelled
            return OfferTransition(
                old_state=state,
                new_state=OfferState.CANCELLED,
                signal=signal,
                action="track_replacement",
                reason="offer_replaced_by_refresh",
            )
        if signal == OfferSignal.CANCEL_SENT:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.CANCEL_REQUESTED,
                signal=signal,
                action="await_cancel_confirm",
                reason="cancel_during_refresh",
            )
        if signal == OfferSignal.FILL_DETECTED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.FILLED,
                signal=signal,
                action="record_fill",
                reason="filled_while_awaiting_refresh",
            )
        if signal == OfferSignal.TIME_EXPIRED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.EXPIRED,
                signal=signal,
                action="cleanup_expired",
                reason="expired_before_refresh",
            )
        if signal == OfferSignal.MEMPOOL_SEEN:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.MEMPOOL_OBSERVED,
                signal=signal,
                action="mark_mempool_observed",
                reason="potential_take_while_refresh_due",
            )

    # ---- CANCEL_REQUESTED transitions ----
    if state == OfferState.CANCEL_REQUESTED:
        if signal == OfferSignal.CANCEL_CONFIRMED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.CANCELLED,
                signal=signal,
                action="finalize_cancel",
                reason="cancel_confirmed_by_wallet",
            )
        if signal == OfferSignal.CANCEL_FAILED:
            # Revert to open — cancel didn't take
            return OfferTransition(
                old_state=state,
                new_state=OfferState.OPEN,
                signal=signal,
                action="retry_or_revert",
                reason="cancel_rpc_failed",
            )
        if signal == OfferSignal.FILL_DETECTED:
            # Race: filled while cancel was in flight
            return OfferTransition(
                old_state=state,
                new_state=OfferState.FILLED,
                signal=signal,
                action="record_fill",
                reason="filled_during_cancel",
            )
        if signal == OfferSignal.TIME_EXPIRED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.EXPIRED,
                signal=signal,
                action="cleanup_expired",
                reason="expired_during_cancel",
            )
        if signal == OfferSignal.MEMPOOL_SEEN:
            # Mempool take observed while cancel is in flight — note but
            # stay in cancel_requested; the fill or cancel will resolve it
            return OfferTransition(
                old_state=state,
                new_state=state,
                signal=signal,
                action="note_mempool_during_cancel",
                reason="mempool_seen_but_cancel_pending",
            )

    # ---- MEMPOOL_OBSERVED transitions ----
    if state == OfferState.MEMPOOL_OBSERVED:
        if signal == OfferSignal.FILL_DETECTED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.FILLED,
                signal=signal,
                action="record_fill",
                reason="mempool_take_confirmed",
            )
        if signal == OfferSignal.FILL_VERIFIED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.FILLED,
                signal=signal,
                action="record_verified_fill",
                reason="on_chain_verification_passed",
            )
        if signal == OfferSignal.TIME_EXPIRED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.EXPIRED,
                signal=signal,
                action="cleanup_expired",
                reason="expired_after_mempool",
            )
        if signal == OfferSignal.CANCEL_SENT:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.CANCEL_REQUESTED,
                signal=signal,
                action="await_cancel_confirm",
                reason="cancel_despite_mempool",
            )

    # ---- FILLED → verification sub-signals ----
    # Note: FILLED is terminal for most signals, but we allow
    # FILL_REJECTED to transition to PHANTOM_REJECTED.
    # This is handled specially since FILLED is in _TERMINAL_STATES.
    # Callers should use apply_fill_verification() for this path.

    # Default: no valid transition
    return OfferTransition(
        old_state=state,
        new_state=state,
        signal=signal,
        action="noop",
        reason="signal_ignored_for_state",
    )


def apply_fill_verification(state: OfferState, signal: OfferSignal) -> OfferTransition:
    """Handle post-fill verification signals.

    Separated from apply_signal() because FILLED is normally terminal.
    Only FILL_VERIFIED (stays filled) and FILL_REJECTED (phantom) are valid.
    """
    if state == OfferState.FILLED:
        if signal == OfferSignal.FILL_VERIFIED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.FILLED,
                signal=signal,
                action="confirm_fill",
                reason="verification_passed",
            )
        if signal == OfferSignal.FILL_REJECTED:
            return OfferTransition(
                old_state=state,
                new_state=OfferState.PHANTOM_REJECTED,
                signal=signal,
                action="revert_fill_record",
                reason="self_spend_or_phantom_detected",
            )

    return OfferTransition(
        old_state=state,
        new_state=state,
        signal=signal,
        action="noop",
        reason="not_a_fill_verification_context",
    )


def coarse_status(lifecycle_state: str) -> str:
    """Map an extended lifecycle state to the legacy 4-value status.

    Used for backward-compatible DB queries and GUI display.
    """
    _map = {
        "open": "open",
        "refresh_due": "open",
        "cancel_requested": "open",  # still live until confirmed
        "cancelled": "cancelled",
        "mempool_observed": "open",  # still live until confirmed
        "filled": "filled",
        "expired": "expired",
        "not_submitted": "expired",  # no live offer exists; unlock local coin
        "phantom_rejected": "cancelled",  # treat as cancelled for legacy
        # Stability-kernel states preserve the legacy four-value projection.
        "prepared": "open",
        "submitted_unconfirmed": "open",
        "creation_unknown": "open",
        "creation_failed": "expired",
        "created": "open",
        "visible": "open",
        "unknown": "open",
        "conflicted": "open",
        "quarantined": "open",
        "terminal": "expired",
    }
    return _map.get(lifecycle_state, "open")


def is_terminal(state: str) -> bool:
    """Check if a lifecycle state is terminal (no further transitions)."""
    return state in {
        "cancelled",
        "filled",
        "expired",
        "not_submitted",
        "phantom_rejected",
        "creation_failed",
        "terminal",
    }


def registry_state(lifecycle_state: str) -> str:
    """Project legacy/coarse lifecycle values into strict registry states.

    This adapter intentionally does not infer a terminal outcome.  The registry
    stores that classification only after its separate proof policy succeeds.
    """

    mapping = {
        "open": "visible",
        "refresh_due": "visible",
        "cancel_requested": "cancel_requested",
        "mempool_observed": "visible",
        "filled": "terminal",
        "cancelled": "terminal",
        "expired": "terminal",
        "not_submitted": "terminal",
        "phantom_rejected": "terminal",
        "prepared": "prepared",
        "submitted_unconfirmed": "submitted_unconfirmed",
        "creation_unknown": "unknown",
        "creation_failed": "terminal",
        "created": "created",
        "visible": "visible",
        "unknown": "unknown",
        "conflicted": "conflicted",
        "quarantined": "quarantined",
        "terminal": "terminal",
    }
    return mapping.get(str(lifecycle_state).strip().lower(), "unknown")


def signal_requires_registry_proof(signal: OfferSignal) -> bool:
    """Return whether a legacy signal is insufficient terminal proof alone."""

    return signal in {
        OfferSignal.FILL_DETECTED,
        OfferSignal.TIME_EXPIRED,
        OfferSignal.REFRESH_POSTED,
    }
