"""Restart-safe progressive withdrawal when trusted market evidence is lost."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

import database


_ASSET_ID = re.compile(r"[0-9a-f]{64}")
_STATES = frozenset({"GREEN", "AMBER", "RED"})
_ALL_TIERS = (
    "inner",
    "middle",
    "outer",
    "extreme",
    "opportunity",
    "sniper",
    "boost",
)


def _asset_id(value: str) -> str:
    if type(value) is not str:
        raise TypeError("asset_id must be text")
    normalized = value.strip().lower()
    if _ASSET_ID.fullmatch(normalized) is None:
        raise ValueError("asset_id must be a 64-character hex value")
    return normalized


def _utc(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise TypeError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(
        value[:-1] + "+00:00" if value.endswith("Z") else value
    )


@dataclass(frozen=True, slots=True)
class DegradedMarketDecision:
    confidence_state: str
    can_create: bool
    can_requote: bool
    cancel_tiers: tuple[str, ...]
    paused: bool
    recovering: bool
    stage: str
    degraded_since: datetime | None
    recovery_refreshes: int
    notify: bool
    reason_code: str


class DegradedMarketController:
    """Apply the approved 0/3/10-minute withdrawal and 3/60 recovery policy."""

    def __init__(self, *, asset_id: str) -> None:
        self.asset_id = _asset_id(asset_id)
        restored = database.get_degraded_market_state(self.asset_id)
        self._degraded_since = (
            _parse(restored.get("degraded_since")) if restored else None
        )
        self._recovery_started_at = (
            _parse(restored.get("recovery_started_at")) if restored else None
        )
        self._recovery_refreshes = (
            int(restored.get("recovery_refreshes", 0)) if restored else 0
        )
        self._last_confidence_state = (
            str(restored["last_confidence_state"]) if restored else None
        )
        self._stage = (
            str(restored.get("withdrawal_stage", "NONE")) if restored else "NONE"
        )

    def update(self, *, confidence_state: str, now: datetime) -> DegradedMarketDecision:
        state = str(confidence_state).strip().upper()
        if state not in _STATES:
            raise ValueError("confidence_state must be GREEN, AMBER, or RED")
        current_time = _utc(now, "now")
        transitioned = (
            self._last_confidence_state is not None
            and self._last_confidence_state != state
        )
        notify = transitioned
        reason = "MARKET_CONFIDENCE_HEALTHY"

        if state == "RED":
            if self._degraded_since is None:
                self._degraded_since = current_time
                notify = True
            self._recovery_started_at = None
            self._recovery_refreshes = 0
            self._stage = self._stage_for(current_time)
            reason = f"MARKET_DEGRADED_{self._stage}"
        elif self._degraded_since is not None:
            if state == "GREEN":
                if self._recovery_started_at is None:
                    self._recovery_started_at = current_time
                    self._recovery_refreshes = 1
                else:
                    self._recovery_refreshes += 1
                recovery_elapsed = (
                    current_time - self._recovery_started_at
                ).total_seconds()
                if self._recovery_refreshes >= 3 and recovery_elapsed >= 60:
                    self._degraded_since = None
                    self._recovery_started_at = None
                    self._recovery_refreshes = 0
                    self._stage = "NONE"
                    notify = True
                    reason = "MARKET_RECOVERY_COMPLETE"
                else:
                    self._stage = self._stage_for(current_time)
                    reason = "MARKET_RECOVERY_PENDING"
            else:
                self._recovery_started_at = None
                self._recovery_refreshes = 0
                self._stage = self._stage_for(current_time)
                reason = "MARKET_RECOVERY_INTERRUPTED"
        else:
            self._stage = "NONE"
            self._recovery_started_at = None
            self._recovery_refreshes = 0
            if state == "AMBER":
                reason = "MARKET_CONFIDENCE_RESTRICTED"

        recovering = self._degraded_since is not None and state == "GREEN"
        degraded = self._degraded_since is not None
        if degraded:
            cancel_tiers = self._cancel_tiers(self._stage)
            can_create = False
            can_requote = False
            paused = self._stage == "ALL"
        elif state == "AMBER":
            cancel_tiers = ()
            can_create = False
            # Requotes create the replacement before cancelling the parent so
            # they temporarily increase live exposure.  AMBER is a strict
            # no-new-exposure state, therefore it cannot safely authorize the
            # current requote implementation either.
            can_requote = False
            paused = False
        else:
            cancel_tiers = ()
            can_create = True
            can_requote = True
            paused = False

        self._last_confidence_state = state
        database.save_degraded_market_state(
            {
                "asset_id": self.asset_id,
                "degraded_since": _iso(self._degraded_since),
                "recovery_started_at": _iso(self._recovery_started_at),
                "recovery_refreshes": self._recovery_refreshes,
                "last_confidence_state": state,
                "withdrawal_stage": self._stage,
                "updated_at": _iso(current_time),
            }
        )
        return DegradedMarketDecision(
            confidence_state=state,
            can_create=can_create,
            can_requote=can_requote,
            cancel_tiers=cancel_tiers,
            paused=paused,
            recovering=recovering,
            stage=self._stage,
            degraded_since=self._degraded_since,
            recovery_refreshes=self._recovery_refreshes,
            notify=notify,
            reason_code=reason,
        )

    def _stage_for(self, now: datetime) -> str:
        if self._degraded_since is None:
            return "NONE"
        elapsed = max(0, (now - self._degraded_since).total_seconds())
        if elapsed >= 600:
            return "ALL"
        if elapsed >= 180:
            return "MIDDLE"
        return "INNER"

    @staticmethod
    def _cancel_tiers(stage: str) -> tuple[str, ...]:
        if stage == "ALL":
            return _ALL_TIERS
        if stage == "MIDDLE":
            return _ALL_TIERS[:2]
        if stage == "INNER":
            return _ALL_TIERS[:1]
        return ()
