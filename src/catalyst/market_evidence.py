"""Durable provider evidence, confidence snapshots, and v1.4 migration state."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

import database
from providers.models import ProviderObservation


_ASSET_ID = re.compile(r"[0-9a-f]{64}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_CONFIDENCE_STATES = frozenset({"GREEN", "AMBER", "RED"})
_WITHDRAWAL_STAGES = frozenset({"NONE", "INNER", "MIDDLE", "ALL", "PAUSED"})
_SOURCE_HEALTH = frozenset({"valid", "degraded", "invalid", "unavailable"})


def _asset_id(value: str) -> str:
    if type(value) is not str:
        raise TypeError("asset_id must be text")
    normalized = value.strip().lower()
    if _ASSET_ID.fullmatch(normalized) is None:
        raise ValueError("asset_id must be a 64-character lowercase hex value")
    return normalized


def _aware_utc(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise TypeError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _decimal_text(value: Decimal | None, label: str) -> str | None:
    if value is None:
        return None
    if type(value) is not Decimal:
        raise TypeError(f"{label} must be a Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{label} must be finite and positive")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class MarketConfidenceSnapshot:
    """One immutable explanation of CATalyst's market confidence decision."""

    asset_id: str
    state: str
    derived_at: datetime
    trusted_midpoint: Decimal | None
    trusted_bid: Decimal | None
    trusted_ask: Decimal | None
    degraded_since: datetime | None
    withdrawal_stage: str
    recovery_refreshes: int
    reason_codes: tuple[str, ...]
    source_health: Mapping[str, str]
    evidence_digests: tuple[str, ...]
    material: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _asset_id(self.asset_id))
        if self.state not in _CONFIDENCE_STATES:
            raise ValueError("state must be GREEN, AMBER, or RED")
        derived_at = _aware_utc(self.derived_at, "derived_at")
        degraded_since = (
            _aware_utc(self.degraded_since, "degraded_since")
            if self.degraded_since is not None
            else None
        )
        if degraded_since is not None and degraded_since > derived_at:
            raise ValueError("degraded_since cannot follow derived_at")
        object.__setattr__(self, "derived_at", derived_at)
        object.__setattr__(self, "degraded_since", degraded_since)
        midpoint = _decimal_text(self.trusted_midpoint, "trusted_midpoint")
        bid = _decimal_text(self.trusted_bid, "trusted_bid")
        ask = _decimal_text(self.trusted_ask, "trusted_ask")
        if (bid is None) != (ask is None):
            raise ValueError("trusted bid and ask must be supplied together")
        if bid is not None and Decimal(bid) > Decimal(ask):
            raise ValueError("trusted bid cannot exceed trusted ask")
        if (
            midpoint is not None
            and bid is not None
            and not (Decimal(bid) <= Decimal(midpoint) <= Decimal(ask))
        ):
            raise ValueError("trusted midpoint must lie inside the trusted spread")
        if self.withdrawal_stage not in _WITHDRAWAL_STAGES:
            raise ValueError("withdrawal_stage is invalid")
        if type(self.recovery_refreshes) is not int or self.recovery_refreshes < 0:
            raise ValueError("recovery_refreshes must be a nonnegative integer")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code for code in self.reason_codes
        ):
            raise ValueError("reason_codes are invalid")
        if not isinstance(self.source_health, Mapping) or any(
            type(provider) is not str or not provider or health not in _SOURCE_HEALTH
            for provider, health in self.source_health.items()
        ):
            raise ValueError("source_health is invalid")
        object.__setattr__(
            self, "source_health", dict(sorted(self.source_health.items()))
        )
        if type(self.evidence_digests) is not tuple or any(
            type(digest) is not str or _DIGEST.fullmatch(digest) is None
            for digest in self.evidence_digests
        ):
            raise ValueError("evidence_digests are invalid")
        if type(self.material) is not bool:
            raise TypeError("material must be a boolean")

    def to_record(self) -> dict[str, Any]:
        record = {
            "asset_id": self.asset_id,
            "state": self.state,
            "derived_at": _iso_utc(self.derived_at),
            "trusted_midpoint": _decimal_text(
                self.trusted_midpoint, "trusted_midpoint"
            ),
            "trusted_bid": _decimal_text(self.trusted_bid, "trusted_bid"),
            "trusted_ask": _decimal_text(self.trusted_ask, "trusted_ask"),
            "degraded_since": _iso_utc(self.degraded_since),
            "withdrawal_stage": self.withdrawal_stage,
            "recovery_refreshes": self.recovery_refreshes,
            "reason_codes": list(self.reason_codes),
            "source_health": dict(self.source_health),
            "evidence_digests": list(self.evidence_digests),
            "material": self.material,
        }
        record["snapshot_id"] = hashlib.sha256(
            _canonical_json(record).encode("utf-8")
        ).hexdigest()
        return record


def persist_provider_observation(observation: ProviderObservation) -> str:
    if type(observation) is not ProviderObservation:
        raise TypeError("observation must be a ProviderObservation")
    raw_evidence = json.loads(observation.raw_evidence_json)
    candidate = raw_evidence.get("asset_id")
    if candidate is None:
        candidate = next(
            (key for key in observation.identity_keys if _ASSET_ID.fullmatch(key)),
            None,
        )
    asset = _asset_id(candidate)
    stable_identity = {
        "provider_id": observation.provider_id,
        "capability": observation.capability.value,
        "observed_at": _iso_utc(observation.observed_at),
        "identity_keys": list(observation.identity_keys),
        "payload_sha256": observation.payload_sha256,
    }
    observation_id = hashlib.sha256(
        _canonical_json(stable_identity).encode("utf-8")
    ).hexdigest()
    return database.record_market_provider_observation(
        {
            "observation_id": observation_id,
            "asset_id": asset,
            "provider_id": observation.provider_id,
            "capability": observation.capability.value,
            "observed_at": _iso_utc(observation.observed_at),
            "source_time": _iso_utc(observation.source_time),
            "source_height": observation.source_height,
            "fresh_until": _iso_utc(observation.fresh_until),
            "identity_keys": list(observation.identity_keys),
            "payload_sha256": observation.payload_sha256,
            "quality": observation.quality.value,
            "reason_codes": list(observation.reason_codes),
            "raw_evidence_json": observation.raw_evidence_json,
            "created_at": _iso_utc(observation.observed_at),
        }
    )


def persist_confidence_snapshot(
    snapshot: MarketConfidenceSnapshot, *, engine_state: Mapping[str, Any] | None = None
) -> str:
    if type(snapshot) is not MarketConfidenceSnapshot:
        raise TypeError("snapshot must be a MarketConfidenceSnapshot")
    normalized_state = dict(engine_state) if engine_state is not None else None
    return database.record_market_confidence_snapshot(
        snapshot.to_record(), normalized_state
    )


def load_confidence_engine_state(asset_id: str) -> dict[str, Any] | None:
    return database.get_market_confidence_engine_state(_asset_id(asset_id))


def migrate_post_tibet_state(
    *,
    asset_id: str,
    authoritative_open_trade_ids: set[str],
    ownership_proven: bool,
    now: datetime,
) -> dict[str, Any]:
    """Record a one-time, fail-closed migration without mutating wallet state."""

    asset = _asset_id(asset_id)
    completed_at = _aware_utc(now, "now")
    if type(authoritative_open_trade_ids) is not set or any(
        type(trade_id) is not str or not trade_id
        for trade_id in authoritative_open_trade_ids
    ):
        raise ValueError("authoritative_open_trade_ids must be a set of IDs")
    if type(ownership_proven) is not bool:
        raise TypeError("ownership_proven must be a boolean")
    existing = database.get_post_tibet_migration_report(asset)
    if existing is not None and existing.get("can_start") is True:
        return existing

    local_open_ids = sorted(
        str(offer["trade_id"]) for offer in database.get_open_offers(cat_asset_id=asset)
    )
    authoritative = set(authoritative_open_trade_ids)
    retained = sorted(set(local_open_ids) & authoritative) if ownership_proven else []
    unsafe = (
        sorted(set(local_open_ids) - authoritative)
        if ownership_proven
        else local_open_ids
    )
    can_start = not unsafe
    report = {
        "asset_id": asset,
        "migration_version": 1,
        "completed_at": _iso_utc(completed_at),
        "can_start": can_start,
        "reason_code": (
            "POST_TIBET_MIGRATION_READY"
            if can_start
            else (
                "POST_TIBET_OWNERSHIP_UNPROVEN"
                if not ownership_proven
                else "POST_TIBET_UNSAFE_OPEN_OFFERS"
            )
        ),
        "retained_offer_ids": retained,
        "unsafe_offer_ids": unsafe,
        "legacy_tibet_history_rows": database.count_legacy_tibet_price_rows(asset),
        "tibet_live_features": "retired",
    }
    return database.store_post_tibet_migration_report(asset, report, completed_at)
