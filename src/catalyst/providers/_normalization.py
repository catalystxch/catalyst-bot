"""Shared fail-closed normalization helpers for provider adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .models import (
    Capability,
    ObservationQuality,
    ProviderObservation,
    canonical_evidence_json,
    evidence_digest,
)


def utc_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if type(current) is not datetime or current.tzinfo is None:
        raise TypeError("observation time must be timezone-aware")
    return current.astimezone(timezone.utc)


def source_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if type(value) is not str:
        raise TypeError("provider source_time must be ISO-8601 text")
    text = value.strip()
    parsed = datetime.fromisoformat(
        text[:-1] + "+00:00" if text.endswith("Z") else text
    )
    if parsed.tzinfo is None:
        raise ValueError("provider source_time must include a timezone")
    return parsed.astimezone(timezone.utc)


def exact_price(value: Any) -> Decimal:
    if type(value) not in {str, Decimal}:
        raise TypeError("provider price must be exact text or Decimal")
    try:
        price = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("provider price is invalid") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError("provider price must be finite and positive")
    return price


def exact_nonnegative_height(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("provider height must be a nonnegative integer")
    return value


def observation(
    *,
    provider_id: str,
    capability: Capability,
    payload: Mapping[str, Any],
    observed_at: datetime,
    identity_keys: tuple[str, ...],
    freshness_seconds: int,
    quality: ObservationQuality,
    reason_codes: tuple[str, ...] = (),
    source_time: datetime | None = None,
    source_height: int | None = None,
) -> ProviderObservation:
    raw = canonical_evidence_json(payload)
    freshness_origin = source_time if source_time is not None else observed_at
    return ProviderObservation(
        provider_id=provider_id,
        capability=capability,
        observed_at=observed_at,
        source_time=source_time,
        source_height=source_height,
        fresh_until=freshness_origin + timedelta(seconds=freshness_seconds),
        identity_keys=identity_keys,
        payload_sha256=evidence_digest(raw),
        quality=quality,
        reason_codes=reason_codes,
        raw_evidence_json=raw,
    )


def failed_observation(
    *,
    provider_id: str,
    capability: Capability,
    identity_keys: tuple[str, ...],
    now: datetime,
    error: Exception,
    freshness_seconds: int,
) -> ProviderObservation:
    reason = (
        "provider_timeout"
        if isinstance(error, TimeoutError)
        else "malformed_provider_response"
    )
    return observation(
        provider_id=provider_id,
        capability=capability,
        payload={"available": False, "error_type": type(error).__name__},
        observed_at=now,
        identity_keys=identity_keys,
        freshness_seconds=freshness_seconds,
        quality=ObservationQuality.INVALID,
        reason_codes=(reason,),
    )
