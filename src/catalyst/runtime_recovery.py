"""Pure fail-closed policy for runtime clock and quarantine recovery evidence.

This module intentionally performs no database, wallet, environment, network,
or clock reads.  Callers inject observations and persist decisions elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any


_MAX_TIMING_SECONDS = Decimal("86400")


@dataclass(frozen=True)
class ClockSample:
    monotonic_seconds: Any
    wall_utc: Any


@dataclass(frozen=True)
class DiscontinuityDecision:
    discontinuity: bool
    reason_code: str
    monotonic_delta_seconds: str | None
    wall_delta_seconds: str | None


def _exact_finite_decimal(value: Any) -> Decimal | None:
    if type(value) is Decimal:
        candidate = value
    elif type(value) is int:
        candidate = Decimal(value)
    elif type(value) is float:
        try:
            candidate = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    else:
        return None
    return candidate if candidate.is_finite() else None


def _threshold(value: Any, *, allow_zero: bool) -> Decimal | None:
    candidate = _exact_finite_decimal(value)
    lower_ok = candidate is not None and (
        candidate >= 0 if allow_zero else candidate > 0
    )
    return candidate if lower_ok and candidate <= _MAX_TIMING_SECONDS else None


def _canonical_utc(value: Any) -> datetime | None:
    if type(value) is not datetime:
        return None
    if value.tzinfo is not timezone.utc or value.utcoffset() != timedelta(0):
        return None
    return value


def _seconds_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _timedelta_seconds(value: timedelta) -> Decimal:
    return (
        Decimal(value.days) * Decimal(86400)
        + Decimal(value.seconds)
        + (Decimal(value.microseconds) / Decimal(1_000_000))
    )


def detect_discontinuity(
    previous: Any,
    current: Any,
    *,
    maximum_monotonic_gap_seconds: Any,
    maximum_wall_skew_seconds: Any,
) -> DiscontinuityDecision:
    """Return a total decision over two injected clock samples."""

    gap_limit = _threshold(maximum_monotonic_gap_seconds, allow_zero=False)
    skew_limit = _threshold(maximum_wall_skew_seconds, allow_zero=True)
    if gap_limit is None or skew_limit is None or type(current) is not ClockSample:
        return DiscontinuityDecision(True, "CLOCK_SAMPLE_MALFORMED", None, None)
    current_mono = _exact_finite_decimal(current.monotonic_seconds)
    current_wall = _canonical_utc(current.wall_utc)
    if current_mono is None or current_wall is None:
        return DiscontinuityDecision(True, "CLOCK_SAMPLE_MALFORMED", None, None)
    if previous is None:
        return DiscontinuityDecision(False, "BASELINE_ESTABLISHED", None, None)
    if type(previous) is not ClockSample:
        return DiscontinuityDecision(True, "CLOCK_SAMPLE_MALFORMED", None, None)
    previous_mono = _exact_finite_decimal(previous.monotonic_seconds)
    previous_wall = _canonical_utc(previous.wall_utc)
    if previous_mono is None or previous_wall is None:
        return DiscontinuityDecision(True, "CLOCK_SAMPLE_MALFORMED", None, None)

    monotonic_delta = current_mono - previous_mono
    wall_delta = _timedelta_seconds(current_wall - previous_wall)
    mono_text = _seconds_text(monotonic_delta)
    wall_text = _seconds_text(wall_delta)
    if monotonic_delta < 0:
        return DiscontinuityDecision(True, "MONOTONIC_ROLLBACK", mono_text, wall_text)
    if wall_delta < 0:
        return DiscontinuityDecision(True, "WALL_CLOCK_ROLLBACK", mono_text, wall_text)
    if monotonic_delta > gap_limit:
        return DiscontinuityDecision(True, "MONOTONIC_GAP", mono_text, wall_text)
    if abs(wall_delta - monotonic_delta) > skew_limit:
        return DiscontinuityDecision(True, "WALL_CLOCK_JUMP", mono_text, wall_text)
    return DiscontinuityDecision(False, "CLOCK_CONTINUOUS", mono_text, wall_text)


def _proof_denied(reason: str) -> dict[str, Any]:
    return {"allowed": False, "reason_code": reason}


def _canonical_utc_text(value: Any) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError):
        return None
    canonical = (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return parsed if parsed.tzinfo is not None and canonical == value else None


def validate_quarantine_resolution_proof(
    requirements: Any,
    proof: Any,
    *,
    now: Any,
    maximum_age_seconds: Any,
) -> dict[str, Any]:
    """Validate an internally collected full-history proof, without I/O."""

    try:
        if type(requirements) is not dict or type(proof) is not dict:
            return _proof_denied("QUARANTINE_PROOF_MALFORMED")
        binding_fields = (
            "quarantine_id",
            "recovery_id",
            "latch_generation",
            "wallet_fingerprint_hash",
            "network",
            "authority_digest",
        )
        if any(proof.get(field) != requirements.get(field) for field in binding_fields):
            return _proof_denied("QUARANTINE_PROOF_BINDING_MISMATCH")
        if proof.get("version") != 1 or type(proof.get("latch_generation")) is not int:
            return _proof_denied("QUARANTINE_PROOF_MALFORMED")
        if type(proof.get("history_complete")) is not bool:
            return _proof_denied("QUARANTINE_PROOF_MALFORMED")
        if (
            type(proof.get("authoritative_read_performed")) is not bool
            or proof["authoritative_read_performed"] is not True
            or proof.get("history_provenance") != "wallet.get_all_offers"
            or proof.get("identity_provenance") != "wallet.get_wallet_identity"
        ):
            return _proof_denied("QUARANTINE_FULL_HISTORY_INCOMPLETE")
        if proof["history_complete"] is not True:
            return _proof_denied("QUARANTINE_FULL_HISTORY_INCOMPLETE")
        maximum_age = _threshold(maximum_age_seconds, allow_zero=False)
        current = _canonical_utc(now)
        observed = _canonical_utc_text(proof.get("observed_at"))
        if maximum_age is None or current is None or observed is None:
            return _proof_denied("QUARANTINE_PROOF_MALFORMED")
        age = _timedelta_seconds(current - observed)
        if age < 0 or age > maximum_age:
            return _proof_denied("QUARANTINE_PROOF_STALE")
        offers = requirements.get("offers")
        absent = proof.get("absent_offer_ids")
        coins = proof.get("coins")
        if (
            type(offers) is not list
            or type(absent) is not list
            or type(coins) is not list
        ):
            return _proof_denied("QUARANTINE_PROOF_MALFORMED")
        expected_offer_ids: set[str] = set()
        expected_coin_ids: set[str] = set()
        for offer in offers:
            if type(offer) is not dict or type(offer.get("trade_id")) is not str:
                return _proof_denied("QUARANTINE_PROOF_MALFORMED")
            selected = offer.get("selected_coin_ids")
            if type(selected) is not list or any(
                type(item) is not str for item in selected
            ):
                return _proof_denied("QUARANTINE_PROOF_MALFORMED")
            expected_offer_ids.add(offer["trade_id"])
            expected_coin_ids.update(selected)
        if set(absent) != expected_offer_ids or len(absent) != len(expected_offer_ids):
            return _proof_denied("QUARANTINED_OFFER_ABSENCE_INCOMPLETE")
        by_coin: dict[str, dict[str, Any]] = {}
        for coin in coins:
            if type(coin) is not dict or type(coin.get("coin_id")) is not str:
                return _proof_denied("QUARANTINE_PROOF_MALFORMED")
            if coin["coin_id"] in by_coin:
                return _proof_denied("QUARANTINE_PROOF_MALFORMED")
            if (
                type(coin.get("owned")) is not bool
                or type(coin.get("unlocked")) is not bool
            ):
                return _proof_denied("QUARANTINE_PROOF_MALFORMED")
            by_coin[coin["coin_id"]] = coin
        if set(by_coin) != expected_coin_ids:
            return _proof_denied("QUARANTINED_INPUT_PROOF_INCOMPLETE")
        for coin_id in sorted(expected_coin_ids):
            if by_coin[coin_id]["owned"] is not True:
                return _proof_denied("QUARANTINED_INPUT_NOT_OWNED")
            if by_coin[coin_id]["unlocked"] is not True:
                return _proof_denied("QUARANTINED_INPUT_LOCKED")
        canonical = json.dumps(
            proof, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        return {
            "allowed": True,
            "reason_code": "QUARANTINE_PROOF_COMPLETE",
            "proof_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "proof_json": canonical,
        }
    except BaseException:
        return _proof_denied("QUARANTINE_PROOF_MALFORMED")


__all__ = [
    "ClockSample",
    "DiscontinuityDecision",
    "detect_discontinuity",
    "validate_quarantine_resolution_proof",
]
