"""Immutable provider observations with exact, auditable values."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_ASSET_ID = re.compile(r"[0-9a-f]{64}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REDACTED_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
    }
)
_MAX_EVIDENCE_BYTES = 64 * 1024


class Capability(str, Enum):
    ORDER_BOOK = "order_book"
    SETTLED_TRADES = "settled_trades"
    TOKEN_METADATA = "token_metadata"
    PUBLISH_OFFER = "publish_offer"
    DISCOVER_OFFER = "discover_offer"
    WALLET_AUTHORITY = "wallet_authority"
    CHAIN_EVIDENCE = "chain_evidence"
    EXACT_FILL_AUTHORITY = "exact_fill_authority"
    PEER_HEALTH = "peer_health"
    PARTIAL_CREATE = "partial_create"
    PARTIAL_CANCEL = "partial_cancel"
    PARTIAL_STATE = "partial_state"
    PARTIAL_LINEAGE = "partial_lineage"
    PARTIAL_FILL = "partial_fill"
    PARTIAL_DISCOVERY = "partial_discovery"


class ObservationQuality(str, Enum):
    VALID = "valid"
    DEGRADED = "degraded"
    INVALID = "invalid"


def _provider_id(value: str) -> str:
    if type(value) is not str:
        raise TypeError("provider_id must be a string")
    normalized = value.strip().lower()
    if _PROVIDER_ID.fullmatch(normalized) is None:
        raise ValueError("provider_id is invalid")
    return normalized


def _aware_utc(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise TypeError(f"{label} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _asset_id(value: str, *, allow_xch: bool = False) -> str:
    if type(value) is not str:
        raise TypeError("asset identity must be a string")
    normalized = value.strip().lower()
    if allow_xch and normalized == "xch":
        return normalized
    if _ASSET_ID.fullmatch(normalized) is None:
        raise ValueError("asset identity must be a 64-character hex asset ID")
    return normalized


def _redact_evidence(value: Any) -> Any:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is Decimal:
        return str(value)
    if type(value) in {list, tuple}:
        return [_redact_evidence(item) for item in value]
    if isinstance(value, Mapping):
        normalized = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("evidence object keys must be strings")
            normalized[key] = (
                "[redacted]"
                if key.strip().lower() in _REDACTED_KEYS
                else _redact_evidence(item)
            )
        return normalized
    raise TypeError(f"unsupported evidence value: {type(value).__name__}")


def canonical_evidence_json(value: Mapping[str, Any]) -> str:
    """Return deterministic, redacted JSON bounded for durable diagnostics."""

    if not isinstance(value, Mapping):
        raise TypeError("evidence must be a mapping")
    encoded = json.dumps(
        _redact_evidence(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if len(encoded.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
        raise ValueError(f"evidence exceeds the {_MAX_EVIDENCE_BYTES}-byte limit")
    return encoded


def evidence_digest(raw_evidence_json: str) -> str:
    if type(raw_evidence_json) is not str:
        raise TypeError("raw evidence must be JSON text")
    return hashlib.sha256(raw_evidence_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider_id: str
    capabilities: frozenset[Capability]

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        if type(self.capabilities) is not frozenset or not self.capabilities:
            raise ValueError("provider capabilities must be a non-empty frozenset")
        if any(type(item) is not Capability for item in self.capabilities):
            raise TypeError("provider capabilities contain an invalid value")

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    provider_id: str
    capability: Capability
    observed_at: datetime
    source_time: datetime | None
    source_height: int | None
    fresh_until: datetime
    identity_keys: tuple[str, ...]
    payload_sha256: str
    quality: ObservationQuality
    reason_codes: tuple[str, ...]
    raw_evidence_json: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        if type(self.capability) is not Capability:
            raise TypeError("capability is invalid")
        observed_at = _aware_utc(self.observed_at, "observed_at")
        fresh_until = _aware_utc(self.fresh_until, "fresh_until")
        source_time = (
            _aware_utc(self.source_time, "source_time")
            if self.source_time is not None
            else None
        )
        if source_time is not None and source_time > observed_at:
            raise ValueError("source_time cannot be later than observed_at")
        freshness_origin = source_time if source_time is not None else observed_at
        if fresh_until < freshness_origin:
            raise ValueError("fresh_until cannot be earlier than its freshness origin")
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "source_time", source_time)
        object.__setattr__(self, "fresh_until", fresh_until)
        if self.source_height is not None and (
            type(self.source_height) is not int or self.source_height < 0
        ):
            raise ValueError("source_height must be a nonnegative integer")
        if (
            type(self.identity_keys) is not tuple
            or not self.identity_keys
            or any(
                type(key) is not str or not key.strip() for key in self.identity_keys
            )
        ):
            raise ValueError("identity_keys must contain non-empty strings")
        if len(set(self.identity_keys)) != len(self.identity_keys):
            raise ValueError("identity_keys must be unique")
        if (
            type(self.payload_sha256) is not str
            or _DIGEST.fullmatch(self.payload_sha256) is None
        ):
            raise ValueError("payload_sha256 is invalid")
        if type(self.quality) is not ObservationQuality:
            raise TypeError("quality is invalid")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or not code for code in self.reason_codes
        ):
            raise ValueError("reason_codes are invalid")
        if type(self.raw_evidence_json) is not str:
            raise TypeError("raw_evidence_json must be text")
        if len(self.raw_evidence_json.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
            raise ValueError(
                f"raw evidence exceeds the {_MAX_EVIDENCE_BYTES}-byte limit"
            )
        try:
            raw_evidence = json.loads(self.raw_evidence_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("raw_evidence_json is invalid JSON") from exc
        if type(raw_evidence) is not dict:
            raise ValueError("raw_evidence_json must contain an object")
        if evidence_digest(self.raw_evidence_json) != self.payload_sha256:
            raise ValueError("raw evidence digest does not match payload_sha256")

    def constructor_values(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "capability": self.capability.value,
            "observed_at": _iso_utc(self.observed_at),
            "source_time": _iso_utc(self.source_time),
            "source_height": self.source_height,
            "fresh_until": _iso_utc(self.fresh_until),
            "identity_keys": list(self.identity_keys),
            "payload_sha256": self.payload_sha256,
            "quality": self.quality.value,
            "reason_codes": list(self.reason_codes),
            "raw_evidence": json.loads(self.raw_evidence_json),
        }


@dataclass(frozen=True, slots=True)
class MarketQuote:
    base_asset_id: str
    quote_asset_id: str
    bid: Decimal
    ask: Decimal
    observed_at: datetime
    provider_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_asset_id", _asset_id(self.base_asset_id))
        object.__setattr__(
            self, "quote_asset_id", _asset_id(self.quote_asset_id, allow_xch=True)
        )
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(
            self, "observed_at", _aware_utc(self.observed_at, "observed_at")
        )
        if type(self.bid) is not Decimal or type(self.ask) is not Decimal:
            raise TypeError("market prices must be Decimal values")
        if not self.bid.is_finite() or not self.ask.is_finite():
            raise ValueError("market prices must be finite")
        if self.bid <= 0 or self.ask <= 0 or self.bid > self.ask:
            raise ValueError("market prices must be positive and ordered")

    @property
    def midpoint(self) -> Decimal:
        return (self.bid + self.ask) / Decimal(2)


@dataclass(frozen=True, slots=True)
class BookObservation:
    asset_id: str
    quote_asset_id: str
    bids: tuple[tuple[Decimal, int, str], ...]
    asks: tuple[tuple[Decimal, int, str], ...]
    observed_at: datetime
    provider_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _asset_id(self.asset_id))
        object.__setattr__(
            self, "quote_asset_id", _asset_id(self.quote_asset_id, allow_xch=True)
        )
        object.__setattr__(self, "provider_id", _provider_id(self.provider_id))
        object.__setattr__(
            self, "observed_at", _aware_utc(self.observed_at, "observed_at")
        )
        identities: set[str] = set()
        for side, levels in (("bid", self.bids), ("ask", self.asks)):
            if type(levels) is not tuple:
                raise TypeError(f"{side} levels must be a tuple")
            prior_price = None
            for level in levels:
                if type(level) is not tuple or len(level) != 3:
                    raise TypeError(
                        "book levels must be (price, amount, identity) tuples"
                    )
                price, amount, identity = level
                if type(price) is not Decimal or not price.is_finite() or price <= 0:
                    raise ValueError("book level price is invalid")
                if type(amount) is not int or amount <= 0:
                    raise ValueError("book level amount must be a positive integer")
                if type(identity) is not str or not identity.strip():
                    raise ValueError("book level identity is invalid")
                if identity in identities:
                    raise ValueError("book level identities must be unique")
                identities.add(identity)
                if prior_price is not None and (
                    (side == "bid" and price > prior_price)
                    or (side == "ask" and price < prior_price)
                ):
                    raise ValueError(f"{side} levels are not sorted")
                prior_price = price
        if self.bids and self.asks and self.bids[0][0] > self.asks[0][0]:
            raise ValueError("book is crossed")

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0][0] if self.asks else None
