"""Read-only evidence collection and proof-bound offer reconciliation.

Wallet reads finish before this module asks :mod:`database` to commit anything.
The classifier is pure and deliberately treats malformed, stale, incomplete, or
contradictory observations as unsafe rather than guessing from offer absence.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from offer_registry import (
    EvidenceSource,
    OfferEvidence,
    OfferReference,
    RegistrySnapshot,
    RegistryState,
    TerminalOutcome,
    authorize_transition,
    offer_record_from_row,
)


FILLED_PROVEN = "FILLED_PROVEN"
CANCELLED_PROVEN = "CANCELLED_PROVEN"
EXPIRED_PROVEN = "EXPIRED_PROVEN"
ACTIVE_PROVEN = "ACTIVE_PROVEN"
UNKNOWN = "UNKNOWN"
CONFLICT = "CONFLICT"

_HEX = frozenset("0123456789abcdef")
_ACTIVE_STATUSES = frozenset(
    {
        0,
        1,
        2,
        "pending",
        "active",
        "pending_accept",
        "pending_confirm",
        "pending_cancel",
    }
)
_FILLED_STATUSES = frozenset(
    {4, "confirmed", "completed", "success", "taken", "filled"}
)
_CANCELLED_STATUSES = frozenset({3, "cancelled", "canceled"})
_EXPIRED_STATUSES = frozenset({5, "expired"})
_TERMINAL_STATUSES = _FILLED_STATUSES | _CANCELLED_STATUSES | _EXPIRED_STATUSES
_MAX_EVIDENCE_AGE_SECONDS = 300
_MAX_SOURCE_SKEW_SECONDS = 60
_MAX_HISTORY_RECORDS = 1000
_MAX_HISTORY_PAGE_SIZE = 1000
_MAX_HISTORY_PAGES = 20
_MAX_WALLET_IDS = 64
_MAX_SELECTED_COINS = 256
_MAX_TRANSACTION_FLOWS = 512
_MAX_CANCEL_MEMBERS = 64
_MAX_AUXILIARY_COINS = 256
_MAX_COIN_RECORDS = 4096
_MAX_PROVIDER_RECORD_FIELDS = 64
_MAX_SOURCE_TIMESTAMPS = 4096
_MAX_PROVIDER_SCALAR_CHARS = 4096
_MAX_PROVIDER_CONTAINER_ITEMS = 4096
_MAX_PROVIDER_DEPTH = 16
_MAX_PROVIDER_NODES = 300_000
_MAX_PROVIDER_TOTAL_TEXT_BYTES = 8 * 1024 * 1024
_MAX_ATOMIC_DIGITS = 128
_MAX_ATOMIC_BITS = 512
_SENSITIVE_KEYS = frozenset(
    {
        "key",
        "mnemonic",
        "offer",
        "offer_bech32",
        "private_key",
        "puzzle_reveal",
        "secret",
        "seed",
        "signature",
    }
)
_MAX_CANONICAL_DEPTH = 64
_MAX_CANONICAL_CONTAINER_ITEMS = 4096
_MAX_CANONICAL_NODES = 100_000
_MAX_CANONICAL_TEXT_BYTES = 8 * 1024 * 1024


class _EvidenceEncodingError(ValueError):
    """Raised when hostile evidence cannot be encoded exactly within bounds."""


class _SourceLimitError(ValueError):
    """Raised before traversing a wallet collection beyond an absolute cap."""


def _unknown(reason: str, **details: Any) -> dict[str, Any]:
    return {"classification": UNKNOWN, "reason_code": reason, **details}


def _conflict(reason: str = "TERMINAL_EVIDENCE_CONFLICT") -> dict[str, Any]:
    return {"classification": CONFLICT, "reason_code": reason}


def _validate_provider_value_bounds(
    value: Any,
    *,
    depth: int = 0,
    state: dict[str, int] | None = None,
) -> None:
    """Preflight exact provider shapes before normalization or copying."""

    if state is None:
        state = {"nodes": 0, "text_bytes_upper": 0}
    state["nodes"] += 1
    if state["nodes"] > _MAX_PROVIDER_NODES or depth > _MAX_PROVIDER_DEPTH:
        raise _SourceLimitError("provider structure exceeds source limit")
    if type(value) is str:
        if len(value) > _MAX_PROVIDER_SCALAR_CHARS:
            raise _SourceLimitError("provider text exceeds source limit")
        state["text_bytes_upper"] += len(value) * 4
        if state["text_bytes_upper"] > _MAX_PROVIDER_TOTAL_TEXT_BYTES:
            raise _SourceLimitError("provider text exceeds source limit")
        return
    if type(value) is bytes:
        if len(value) > _MAX_PROVIDER_SCALAR_CHARS:
            raise _SourceLimitError("provider bytes exceed source limit")
        state["text_bytes_upper"] += len(value)
        if state["text_bytes_upper"] > _MAX_PROVIDER_TOTAL_TEXT_BYTES:
            raise _SourceLimitError("provider bytes exceed source limit")
        return
    if type(value) is int:
        if value.bit_length() > 4096:
            raise _SourceLimitError("provider integer exceeds source limit")
        return
    if type(value) is bool or value is None:
        return
    if type(value) is dict:
        if len(value) > _MAX_PROVIDER_CONTAINER_ITEMS:
            raise _SourceLimitError("provider object exceeds source limit")
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("provider object key must be exact text")
            if len(key) > _MAX_PROVIDER_SCALAR_CHARS:
                raise _SourceLimitError("provider object key exceeds source limit")
            state["text_bytes_upper"] += len(key) * 4
            if state["text_bytes_upper"] > _MAX_PROVIDER_TOTAL_TEXT_BYTES:
                raise _SourceLimitError("provider text exceeds source limit")
            _validate_provider_value_bounds(item, depth=depth + 1, state=state)
        return
    if type(value) is list:
        if len(value) > _MAX_PROVIDER_CONTAINER_ITEMS:
            raise _SourceLimitError("provider list exceeds source limit")
        for item in value:
            _validate_provider_value_bounds(item, depth=depth + 1, state=state)
        return
    raise ValueError("provider value must use exact bounded JSON scalar types")


def _provider_value_within_bounds(value: Any) -> bool:
    try:
        _validate_provider_value_bounds(value)
    except (TypeError, ValueError):
        return False
    return True


def _require_provider_bounds(value: Any) -> None:
    _validate_provider_value_bounds(value)


def _norm_id(value: Any) -> str:
    if type(value) is not str or len(value) > _MAX_PROVIDER_SCALAR_CHARS:
        return ""
    text = value.strip().lower()
    return text[2:] if text.startswith("0x") else text


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """Select a provider alias without invoking truthiness on hostile values."""

    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _hex_id(value: Any) -> str:
    text = _norm_id(value)
    if len(text) != 64 or any(character not in _HEX for character in text):
        return ""
    return text


def _positive_int(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def _atomic_text(value: Any) -> str:
    if type(value) is int:
        if value <= 0 or value.bit_length() > _MAX_ATOMIC_BITS:
            return ""
        text = str(value)
    elif type(value) is str:
        if len(value) > _MAX_ATOMIC_DIGITS:
            return ""
        text = value
    else:
        return ""
    if (
        not text
        or text[0] not in "123456789"
        or not text.isascii()
        or not text.isdigit()
    ):
        return ""
    return text


def _parse_utc(value: Any) -> datetime | None:
    if type(value) is not str or len(value) > 128 or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _canonical_utc(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        parsed = parsed.astimezone(timezone.utc)
    else:
        parsed = _parse_utc(value)
        if parsed is None:
            raise ValueError("timestamp must be timezone-aware UTC text")
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _is_canonical_utc_text(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        return value == _canonical_utc(value)
    except ValueError:
        return False


def _clock_utc(clock: Callable[[], Any] | None = None) -> str:
    value = clock() if clock is not None else datetime.now(timezone.utc)
    return _canonical_utc(value)


def _source_timestamp(value: Any) -> Any:
    if type(value) is not dict:
        return None
    for key in ("observed_at_utc", "source_observed_at", "observed_at"):
        if key in value:
            return value[key]
    return None


def _status(value: Any) -> int | str | None:
    if type(value) is int:
        return value
    if type(value) is str and len(value) <= 64 and value.strip():
        return value.strip().lower()
    return None


def _redact_json(
    value: Any,
    *,
    depth: int = 0,
    state: dict[str, Any] | None = None,
    redact_sensitive: bool = True,
) -> Any:
    if state is None:
        state = {
            "nodes": 0,
            "text_bytes": 0,
            "text_bytes_upper": 0,
            "scalar_bytes_upper": 0,
            "active_containers": set(),
        }
    state["nodes"] += 1
    if state["nodes"] > _MAX_CANONICAL_NODES:
        raise _EvidenceEncodingError("evidence node cap exceeded")
    if depth > _MAX_CANONICAL_DEPTH:
        raise _EvidenceEncodingError("evidence depth cap exceeded")
    if type(value) is dict:
        if len(value) > _MAX_CANONICAL_CONTAINER_ITEMS:
            raise _EvidenceEncodingError("evidence object cap exceeded")
        if any(type(key) is not str for key in value):
            raise _EvidenceEncodingError("evidence object key is not text")
        for key in value:
            if (
                len(key) > _MAX_CANONICAL_TEXT_BYTES // 4
                or state["text_bytes_upper"] + len(key) * 4 > _MAX_CANONICAL_TEXT_BYTES
            ):
                raise _EvidenceEncodingError("evidence text cap exceeded")
            state["text_bytes_upper"] += len(key) * 4
            try:
                encoded_key = key.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise _EvidenceEncodingError(
                    "evidence object key is not valid UTF-8"
                ) from exc
            state["text_bytes"] += len(encoded_key)
            if state["text_bytes"] > _MAX_CANONICAL_TEXT_BYTES:
                raise _EvidenceEncodingError("evidence text cap exceeded")
        container_id = id(value)
        if container_id in state["active_containers"]:
            raise _EvidenceEncodingError("cyclic evidence container")
        state["active_containers"].add(container_id)
        result: dict[str, Any] = {}
        try:
            for key in sorted(value):
                if redact_sensitive and key.strip().lower() in _SENSITIVE_KEYS:
                    continue
                result[key] = _redact_json(
                    value[key],
                    depth=depth + 1,
                    state=state,
                    redact_sensitive=redact_sensitive,
                )
            return result
        finally:
            state["active_containers"].remove(container_id)
    if type(value) is list:
        if len(value) > _MAX_CANONICAL_CONTAINER_ITEMS:
            raise _EvidenceEncodingError("evidence list cap exceeded")
        container_id = id(value)
        if container_id in state["active_containers"]:
            raise _EvidenceEncodingError("cyclic evidence container")
        state["active_containers"].add(container_id)
        try:
            return [
                _redact_json(
                    item,
                    depth=depth + 1,
                    state=state,
                    redact_sensitive=redact_sensitive,
                )
                for item in value
            ]
        finally:
            state["active_containers"].remove(container_id)
    if type(value) is str:
        if (
            len(value) > _MAX_CANONICAL_TEXT_BYTES // 4
            or state["text_bytes_upper"] + len(value) * 4 > _MAX_CANONICAL_TEXT_BYTES
        ):
            raise _EvidenceEncodingError("evidence text cap exceeded")
        state["text_bytes_upper"] += len(value) * 4
        try:
            encoded_text = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _EvidenceEncodingError("evidence text is not valid UTF-8") from exc
        state["text_bytes"] += len(encoded_text)
        if state["text_bytes"] > _MAX_CANONICAL_TEXT_BYTES:
            raise _EvidenceEncodingError("evidence text cap exceeded")
        if redact_sensitive and len(value) > 4096:
            tail_digest = hashlib.sha256(encoded_text).hexdigest()
            return value[:256] + f"<redacted-long-text-sha256:{tail_digest}>"
        return value
    if type(value) is int:
        if value.bit_length() > 4096:
            raise _EvidenceEncodingError("evidence integer cap exceeded")
        state["scalar_bytes_upper"] += max(1, value.bit_length()) + 2
        if (
            state["text_bytes_upper"]
            + state["scalar_bytes_upper"]
            + state["nodes"] * 16
            > _MAX_CANONICAL_TEXT_BYTES
        ):
            raise _EvidenceEncodingError("evidence canonical payload cap exceeded")
        return value
    if type(value) is bool or value is None:
        state["scalar_bytes_upper"] += 5
        return value
    raise _EvidenceEncodingError("evidence contains unsupported scalar")


def canonical_evidence_and_digest(
    evidence: Any, *, max_bytes: int = 65536
) -> tuple[str, str]:
    """Return bounded, redacted canonical JSON and its exact SHA-256 digest."""

    if type(max_bytes) is not int or max_bytes < 128:
        raise ValueError("max_bytes must be an integer of at least 128")
    preflight_state = {
        "nodes": 0,
        "text_bytes": 0,
        "text_bytes_upper": 0,
        "scalar_bytes_upper": 0,
        "active_containers": set(),
    }
    redacted = _redact_json(evidence, state=preflight_state)
    if (
        preflight_state["text_bytes_upper"]
        + preflight_state["scalar_bytes_upper"]
        + preflight_state["nodes"] * 16
        > _MAX_CANONICAL_TEXT_BYTES
    ):
        raise _EvidenceEncodingError("evidence canonical payload cap exceeded")
    full_encoded = json.dumps(
        redacted,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(full_encoded) > _MAX_CANONICAL_TEXT_BYTES:
        raise _EvidenceEncodingError("evidence canonical payload cap exceeded")
    full_bytes = full_encoded.encode("utf-8")
    if len(full_bytes) > _MAX_CANONICAL_TEXT_BYTES:
        raise _EvidenceEncodingError("evidence canonical payload cap exceeded")
    full_digest = hashlib.sha256(full_bytes).hexdigest()
    if len(full_bytes) <= max_bytes:
        return full_encoded, full_digest

    def exact_subset(value: Any, *, list_limit: int) -> Any:
        if type(value) is dict:
            return {
                key: exact_subset(item, list_limit=list_limit)
                for key, item in value.items()
            }
        if type(value) is list:
            return [
                exact_subset(item, list_limit=list_limit) for item in value[:list_limit]
            ]
        return value

    encoded = ""
    for list_limit in (8, 4, 2, 1, 0):
        subset = exact_subset(redacted, list_limit=list_limit)
        subset_encoded = json.dumps(
            subset,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        envelope = {
            "bounded": True,
            "exact_subset": subset,
            "exact_subset_sha256": hashlib.sha256(
                subset_encoded.encode("utf-8")
            ).hexdigest(),
            "full_evidence_sha256": full_digest,
            "redacted": True,
        }
        encoded = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) <= max_bytes:
            return encoded, full_digest
    subset = {}
    subset_encoded = "{}"
    encoded = json.dumps(
        {
            "bounded": True,
            "exact_subset": subset,
            "exact_subset_sha256": hashlib.sha256(
                subset_encoded.encode("utf-8")
            ).hexdigest(),
            "full_evidence_sha256": full_digest,
            "redacted": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("max_bytes is too small for bounded evidence")
    return encoded, full_digest


def _exact_intent(intent: Any) -> dict[str, Any] | None:
    if type(intent) is not dict:
        return None
    required_text = (
        "intent_id",
        "wallet_fingerprint_hash",
        "network",
        "asset_id",
        "side",
        "offered_amount_atomic",
        "requested_amount_atomic",
        "selected_coin_ids_json",
        "offer_text_sha256",
        "sage_trade_id",
    )
    if any(type(intent.get(key)) is not str for key in required_text):
        return None
    if not _hex_id(intent["wallet_fingerprint_hash"]) or not _hex_id(
        intent["asset_id"]
    ):
        return None
    if intent["side"] not in {"buy", "sell"}:
        return None
    if not _atomic_text(intent["offered_amount_atomic"]) or not _atomic_text(
        intent["requested_amount_atomic"]
    ):
        return None
    if not _hex_id(intent["sage_trade_id"]) or not _hex_id(intent["offer_text_sha256"]):
        return None
    try:
        raw_coins = json.loads(intent["selected_coin_ids_json"])
    except (TypeError, ValueError):
        return None
    if (
        type(raw_coins) is not list
        or not raw_coins
        or len(raw_coins) > _MAX_SELECTED_COINS
    ):
        return None
    coin_ids = tuple(_hex_id(value) for value in raw_coins)
    if any(not value for value in coin_ids) or coin_ids != tuple(sorted(set(coin_ids))):
        return None
    offer_created_at = _parse_utc(_first_present(intent, "confirmed_at", "prepared_at"))
    if offer_created_at is None:
        return None
    return {
        **intent,
        "asset_id": _hex_id(intent["asset_id"]),
        "sage_trade_id": _hex_id(intent["sage_trade_id"]),
        "selected_coin_ids": coin_ids,
        "offered_amount": int(intent["offered_amount_atomic"]),
        "requested_amount": int(intent["requested_amount_atomic"]),
        "offer_created_at": offer_created_at,
    }


def _source_error(evidence: dict[str, Any], now: datetime) -> str | None:
    if not _is_canonical_utc_text(evidence.get("observed_at")):
        return "EVIDENCE_TIMESTAMP_INVALID"
    top_observed = _parse_utc(evidence.get("observed_at"))
    if top_observed is None:
        return "EVIDENCE_TIMESTAMP_INVALID"
    if not _is_canonical_utc_text(evidence.get("collection_started_at")):
        return "EVIDENCE_TIMESTAMP_INVALID"
    collection_started = _parse_utc(evidence["collection_started_at"])
    if collection_started is None:
        return "EVIDENCE_TIMESTAMP_INVALID"
    age = (now - top_observed).total_seconds()
    if age > _MAX_EVIDENCE_AGE_SECONDS or age < -30:
        return "EVIDENCE_STALE"
    effective_times: list[datetime] = [collection_started, top_observed, now]
    identity = evidence.get("wallet_identity")
    if (
        type(identity) is not dict
        or identity.get("complete") is not True
        or type(identity.get("provenance")) is not str
        or not identity["provenance"]
    ):
        return "WALLET_IDENTITY_INCOMPLETE"
    if (
        not _is_canonical_utc_text(identity.get("observed_at"))
        or not _is_canonical_utc_text(identity.get("source_observed_at"))
        or type(identity.get("source_observed_at_all")) is not list
        or not identity["source_observed_at_all"]
        or type(identity.get("read_observed_at")) is not list
        or not identity["read_observed_at"]
    ):
        return "EVIDENCE_TIMESTAMP_INVALID"
    identity_source_times = identity["source_observed_at_all"]
    identity_read_times = identity["read_observed_at"]
    if (
        len(identity_source_times) > _MAX_SOURCE_TIMESTAMPS
        or len(identity_read_times) > _MAX_SOURCE_TIMESTAMPS
    ):
        return "EVIDENCE_SOURCE_LIMIT_EXCEEDED"
    identity_singular_source = identity["source_observed_at"]
    identity_times = (
        (identity["observed_at"], identity_singular_source),
        identity_source_times,
        identity_read_times,
    )
    for timestamps in identity_times:
        for timestamp in timestamps:
            if not _is_canonical_utc_text(timestamp):
                return "EVIDENCE_TIMESTAMP_INVALID"
            parsed = _parse_utc(timestamp)
            if parsed is None:
                return "EVIDENCE_TIMESTAMP_INVALID"
            timestamp_age = (top_observed - parsed).total_seconds()
            if timestamp_age < -30 or timestamp_age > _MAX_EVIDENCE_AGE_SECONDS:
                return "EVIDENCE_STALE"
            effective_times.append(parsed)
    if identity_singular_source not in identity_source_times:
        return "EVIDENCE_TIMESTAMP_INVALID"
    for name, reason in (
        ("offer_history", "OFFER_HISTORY_INCOMPLETE"),
        ("transaction_history", "TRANSACTION_HISTORY_INCOMPLETE"),
        ("coin_records", "COIN_RECORDS_INCOMPLETE"),
    ):
        source = evidence.get(name)
        if type(source) is not dict or source.get("complete") is not True:
            return reason
        if type(source.get("provenance")) is not str or not source["provenance"]:
            return reason
        all_source_times = source.get("source_observed_at_all")
        if all_source_times is not None:
            if type(all_source_times) is not list:
                return "EVIDENCE_TIMESTAMP_INVALID"
            if len(all_source_times) > _MAX_SOURCE_TIMESTAMPS:
                return "EVIDENCE_SOURCE_LIMIT_EXCEEDED"
        read_times = source.get("read_observed_at")
        if type(read_times) is not list or not read_times:
            return "EVIDENCE_TIMESTAMP_INVALID"
        if len(read_times) > _MAX_SOURCE_TIMESTAMPS:
            return "EVIDENCE_SOURCE_LIMIT_EXCEEDED"
        if not _is_canonical_utc_text(source.get("observed_at")):
            return "EVIDENCE_TIMESTAMP_INVALID"
        observed = _parse_utc(source.get("observed_at"))
        if observed is None:
            return "EVIDENCE_TIMESTAMP_INVALID"
        effective_times.append(observed)
        source_age = (top_observed - observed).total_seconds()
        if source_age < -30 or source_age > _MAX_EVIDENCE_AGE_SECONDS:
            return "EVIDENCE_STALE"
        effective = observed
        source_observed_at = source.get("source_observed_at")
        if source_observed_at is not None:
            if not _is_canonical_utc_text(source_observed_at):
                return "EVIDENCE_TIMESTAMP_INVALID"
            source_observed = _parse_utc(source_observed_at)
            if source_observed is None:
                return "EVIDENCE_TIMESTAMP_INVALID"
            source_observed_age = (top_observed - source_observed).total_seconds()
            if (
                source_observed_age < -30
                or source_observed_age > _MAX_EVIDENCE_AGE_SECONDS
            ):
                return "EVIDENCE_STALE"
            effective = source_observed
            effective_times.append(source_observed)
        if all_source_times is not None:
            if (
                source_observed_at is not None
                and source_observed_at not in all_source_times
            ):
                return "EVIDENCE_TIMESTAMP_INVALID"
            if not all_source_times:
                effective_times.append(effective)
            for source_time in all_source_times:
                if not _is_canonical_utc_text(source_time):
                    return "EVIDENCE_TIMESTAMP_INVALID"
                parsed_source_time = _parse_utc(source_time)
                if parsed_source_time is None:
                    return "EVIDENCE_TIMESTAMP_INVALID"
                page_age = (top_observed - parsed_source_time).total_seconds()
                if page_age < -30 or page_age > _MAX_EVIDENCE_AGE_SECONDS:
                    return "EVIDENCE_STALE"
                effective_times.append(parsed_source_time)
        else:
            effective_times.append(effective)
        for read_time in read_times:
            if not _is_canonical_utc_text(read_time):
                return "EVIDENCE_TIMESTAMP_INVALID"
            parsed_read = _parse_utc(read_time)
            if parsed_read is None:
                return "EVIDENCE_TIMESTAMP_INVALID"
            read_age = (top_observed - parsed_read).total_seconds()
            if read_age < -30 or read_age > _MAX_EVIDENCE_AGE_SECONDS:
                return "EVIDENCE_STALE"
            effective_times.append(parsed_read)
        pagination = source.get("pagination")
        if type(pagination) is not dict:
            return reason
        if _positive_int(pagination.get("pages_read")) is None:
            return reason
        if _positive_int(pagination.get("page_size")) is None:
            return reason
        if pagination.get("locally_normalized") is not True:
            return reason
        if (
            pagination.get("remote_bounds_honored") is not True
            and pagination.get("authoritative_end") is not True
        ):
            return reason
    if (
        effective_times
        and (max(effective_times) - min(effective_times)).total_seconds()
        > _MAX_SOURCE_SKEW_SECONDS
    ):
        return "EVIDENCE_SOURCE_SKEW"
    return None


def _offer_summary_matches(intent: dict[str, Any], offer: Any) -> bool:
    if type(offer) is not dict:
        return False
    if (
        _hex_id(_first_present(offer, "trade_id", "offer_id"))
        != intent["sage_trade_id"]
    ):
        return False
    summary = offer.get("summary")
    if type(summary) is not dict:
        return False
    offered = summary.get("offered")
    requested = summary.get("requested")
    if (
        type(offered) is not dict
        or type(requested) is not dict
        or len(offered) != 1
        or len(requested) != 1
    ):
        return False
    offered_asset = "xch" if intent["side"] == "buy" else intent["asset_id"]
    requested_asset = intent["asset_id"] if intent["side"] == "buy" else "xch"
    if tuple(offered) != (offered_asset,) or tuple(requested) != (requested_asset,):
        return False
    if _positive_int(offered[offered_asset]) != intent["offered_amount"]:
        return False
    if _positive_int(requested[requested_asset]) != intent["requested_amount"]:
        return False
    selected = offer.get("selected_coin_ids")
    if selected is None:
        return True
    if type(selected) is not list or len(selected) > _MAX_SELECTED_COINS:
        return False
    normalized = tuple(sorted(_hex_id(value) for value in selected))
    return bool(
        all(normalized)
        and len(normalized) == len(set(normalized))
        and normalized == intent["selected_coin_ids"]
    )


def _asset(value: Any) -> str:
    if value == "xch":
        return "xch"
    return _hex_id(value)


def _flow(entry: Any) -> tuple[str, str, int, str, str, str] | None:
    if type(entry) is not dict:
        return None
    coin_id = _hex_id(_first_present(entry, "coin_id", "id"))
    asset_value = entry.get("asset_id")
    if "asset_id" not in entry and type(entry.get("asset")) is dict:
        asset_value = entry["asset"].get("asset_id")
    asset_id = _asset(asset_value)
    amount = _positive_int(entry.get("amount"))
    address_kind = entry.get("address_kind")
    raw_parent = _first_present(entry, "parent_coin_id", "parent_id", "source_coin_id")
    parent_coin_id = _hex_id(raw_parent) if raw_parent is not None else ""
    raw_condition = entry.get("spend_condition_id")
    spend_condition_id = (
        raw_condition if type(raw_condition) is str and raw_condition.strip() else ""
    )
    if (
        not coin_id
        or not asset_id
        or amount is None
        or address_kind not in {None, "own", "offer"}
        or (raw_parent is not None and not parent_coin_id)
        or (raw_condition is not None and not spend_condition_id)
    ):
        return None
    return (
        coin_id,
        asset_id,
        amount,
        address_kind,
        parent_coin_id,
        spend_condition_id,
    )


def _coin_map(source: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    records = source.get("records")
    if type(records) is not dict or len(records) > _MAX_COIN_RECORDS:
        return None
    normalized: dict[str, dict[str, Any]] = {}
    for raw_id, record in records.items():
        if type(record) is not dict:
            return None
        explicit_id = record.get("coin_id")
        if explicit_id is None:
            candidate_id = raw_id
        elif type(explicit_id) is str:
            candidate_id = explicit_id
        else:
            return None
        coin_id = _hex_id(candidate_id)
        if not coin_id or coin_id in normalized:
            return None
        normalized[coin_id] = record
    return normalized


def _transaction_rows(source: dict[str, Any]) -> list[dict[str, Any]] | None:
    rows = source.get("records")
    if (
        type(rows) is not list
        or len(rows) > _MAX_HISTORY_RECORDS
        or any(type(row) is not dict for row in rows)
    ):
        return None
    return rows


def _exact_transaction(
    transactions: list[dict[str, Any]], transaction_id: str
) -> dict[str, Any] | None:
    target_id = _hex_id(transaction_id)
    if not target_id:
        return None
    matches = [
        row for row in transactions if _hex_id(row.get("transaction_id")) == target_id
    ]
    if len(matches) != 1:
        return None
    tx = matches[0]
    if (
        tx.get("confirmed") is not True
        or _positive_int(tx.get("confirmed_height")) is None
    ):
        return None
    spend_identity = tx.get("spend_identity")
    if spend_identity is not None and (
        type(spend_identity) is not str or not spend_identity
    ):
        return None
    if not _is_canonical_utc_text(tx.get("timestamp")):
        return None
    spent = tx.get("spent")
    created = tx.get("created")
    if (
        type(spent) is not list
        or type(created) is not list
        or len(spent) > _MAX_TRANSACTION_FLOWS
        or len(created) > _MAX_TRANSACTION_FLOWS
    ):
        return None
    if any(_flow(entry) is None for entry in spent) or any(
        _flow(entry) is None for entry in created
    ):
        return None
    return tx


def _coin_matches_flow(
    record: dict[str, Any],
    flow: tuple[str, str, int, str, str, str],
    tx: dict[str, Any],
    *,
    spent: bool,
) -> bool:
    coin_id, asset_id, amount, _kind, _parent, _condition = flow
    height_key = "spent_height" if spent else "created_height"
    raw_record_coin_id = _first_present(record, "coin_id")
    record_coin_id = coin_id if raw_record_coin_id is None else raw_record_coin_id
    return bool(
        _hex_id(record_coin_id) == coin_id
        and _asset(record.get("asset_id")) == asset_id
        and _positive_int(record.get("amount")) == amount
        and _positive_int(record.get(height_key)) == tx["confirmed_height"]
        and _hex_id(record.get("transaction_id")) == _hex_id(tx["transaction_id"])
        and record.get("owned") is True
        and (spent or record.get("spent_height") in (None, 0))
    )


def _fill_proof(
    intent: dict[str, Any],
    offer: dict[str, Any],
    tx: dict[str, Any],
    coins: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    del offer
    offered_asset = "xch" if intent["side"] == "buy" else intent["asset_id"]
    requested_asset = intent["asset_id"] if intent["side"] == "buy" else "xch"
    spent = [_flow(entry) for entry in tx["spent"]]
    created = [_flow(entry) for entry in tx["created"]]
    selected_flows = [
        flow for flow in spent if flow and flow[0] in intent["selected_coin_ids"]
    ]
    if {flow[0] for flow in selected_flows} != set(intent["selected_coin_ids"]):
        return None
    if any(flow[1] != offered_asset for flow in selected_flows):
        return None
    if sum(flow[2] for flow in selected_flows) != intent["offered_amount"]:
        return None
    for flow in selected_flows:
        record = coins.get(flow[0])
        if record is None or not _coin_matches_flow(record, flow, tx, spent=True):
            return None
        offer_id = _norm_id(record.get("offer_id"))
        if offer_id and offer_id not in {
            intent["sage_trade_id"],
            _norm_id(intent["offer_text_sha256"]),
        }:
            return None
    receipts = [
        flow
        for flow in created
        if flow and flow[1] == requested_asset and flow[2] == intent["requested_amount"]
    ]
    if len(receipts) != 1:
        return None
    receipt = receipts[0]
    receipt_record = coins.get(receipt[0])
    if receipt_record is None or not _coin_matches_flow(
        receipt_record, receipt, tx, spent=False
    ):
        return None
    return {
        "transaction_id": tx["transaction_id"],
        "spend_identity": tx.get("spend_identity"),
        "block_height": tx["confirmed_height"],
        "filled_at": tx["timestamp"],
        "receive_coin_id": receipt[0],
        "receive_amount_mojos": receipt[2],
    }


def _basic_cancel_members(
    context: Any,
) -> tuple[list[dict[str, Any]], tuple[str, ...]] | None:
    if type(context) is not dict or type(context.get("members")) is not list:
        return None
    members = context["members"]
    auxiliary = context.get("auxiliary_coin_ids", [])
    if (
        not members
        or len(members) > _MAX_CANCEL_MEMBERS
        or type(auxiliary) is not list
        or len(auxiliary) > _MAX_AUXILIARY_COINS
    ):
        return None
    normalized_aux = tuple(sorted(_hex_id(value) for value in auxiliary))
    if any(not value for value in normalized_aux) or len(normalized_aux) != len(
        set(normalized_aux)
    ):
        return None
    for member in members:
        if (
            type(member) is not dict
            or type(member.get("selected_coin_ids")) is not list
            or not member["selected_coin_ids"]
            or len(member["selected_coin_ids"]) > _MAX_SELECTED_COINS
        ):
            return None
        if not _hex_id(member.get("trade_id")) or not _is_canonical_utc_text(
            member.get("request_timestamp")
        ):
            return None
        if not _is_canonical_utc_text(member.get("transaction_timestamp")):
            return None
        if (
            not _hex_id(member.get("asset_id"))
            or member.get("side") not in {"buy", "sell"}
            or not _atomic_text(member.get("offered_amount_atomic"))
            or not _atomic_text(member.get("requested_amount_atomic"))
            or not _hex_id(member.get("offer_text_sha256"))
        ):
            return None
        selected = tuple(
            sorted(_hex_id(value) for value in member["selected_coin_ids"])
        )
        if any(not value for value in selected) or len(selected) != len(set(selected)):
            return None
        transaction_id = member.get("transaction_id")
        spend_identity = member.get("spend_identity")
        if transaction_id is not None and not _hex_id(transaction_id):
            return None
        if spend_identity is not None and (
            type(spend_identity) is not str or not spend_identity
        ):
            return None
        if transaction_id is None and spend_identity is None:
            return None
    return members, normalized_aux


def _validated_cancel_context(context: Any) -> dict[str, Any] | None:
    parsed = _basic_cancel_members(context)
    if parsed is None or type(context) is not dict:
        return None
    cohort_id = context.get("cohort_id")
    manifest_sha256 = _hex_id(context.get("manifest_sha256"))
    if type(cohort_id) is not str or not cohort_id.strip() or not manifest_sha256:
        return None
    members, auxiliary = parsed
    exact_members: list[dict[str, Any]] = []
    seen_member_ids: set[str] = set()
    seen_prepared_events: set[str] = set()
    seen_trade_ids: set[str] = set()
    for member in members:
        intent_id = member.get("intent_id")
        trade_id = _hex_id(member.get("trade_id"))
        member_id = member.get("member_id")
        prepared_event_id = member.get("prepared_event_id")
        if (
            type(intent_id) is not str
            or not intent_id.strip()
            or type(member_id) is not str
            or not member_id.strip()
            or type(prepared_event_id) is not str
        ):
            return None
        prefix = f"cancel:{trade_id}:attempt:"
        if not prepared_event_id.startswith(prefix) or not prepared_event_id.endswith(
            ":prepared"
        ):
            return None
        attempt_text = prepared_event_id[len(prefix) : -len(":prepared")]
        if not attempt_text.isdigit() or int(attempt_text) < 1:
            return None
        if (
            member_id in seen_member_ids
            or prepared_event_id in seen_prepared_events
            or trade_id in seen_trade_ids
        ):
            return None
        seen_member_ids.add(member_id)
        seen_prepared_events.add(prepared_event_id)
        seen_trade_ids.add(trade_id)
        exact_members.append(
            {
                "intent_id": intent_id,
                "trade_id": trade_id,
                "member_id": member_id,
                "prepared_event_id": prepared_event_id,
                "selected_coin_ids": sorted(
                    _hex_id(value) for value in member["selected_coin_ids"]
                ),
                "request_timestamp": member["request_timestamp"],
                "transaction_timestamp": member["transaction_timestamp"],
                "asset_id": _hex_id(member["asset_id"]),
                "side": member["side"],
                "offered_amount_atomic": _atomic_text(member["offered_amount_atomic"]),
                "requested_amount_atomic": _atomic_text(
                    member["requested_amount_atomic"]
                ),
                "offer_text_sha256": _hex_id(member["offer_text_sha256"]),
                "transaction_id": (
                    _hex_id(member["transaction_id"])
                    if member.get("transaction_id") is not None
                    else None
                ),
                "spend_identity": member.get("spend_identity"),
            }
        )
    return {
        "cohort_id": cohort_id,
        "manifest_sha256": manifest_sha256,
        "members": exact_members,
        "auxiliary_coin_ids": list(auxiliary),
    }


def _cancel_proof(
    intent: dict[str, Any],
    offers: list[dict[str, Any]],
    tx: dict[str, Any],
    coins: dict[str, dict[str, Any]],
    context: Any,
) -> dict[str, Any] | None:
    exact_context = _validated_cancel_context(context)
    if exact_context is None:
        return None
    members = exact_context["members"]
    auxiliary = tuple(exact_context["auxiliary_coin_ids"])
    target_members = [
        member
        for member in members
        if _hex_id(member["trade_id"]) == intent["sage_trade_id"]
    ]
    if (
        len(target_members) != 1
        or tuple(
            sorted(_hex_id(value) for value in target_members[0]["selected_coin_ids"])
        )
        != intent["selected_coin_ids"]
    ):
        return None
    for member in members:
        if member.get("transaction_id") is not None and _hex_id(
            member["transaction_id"]
        ) != _hex_id(tx["transaction_id"]):
            return None
        if member.get("spend_identity") is not None and member[
            "spend_identity"
        ] != tx.get("spend_identity"):
            return None
        if member["transaction_timestamp"] != tx["timestamp"]:
            return None
    tx_time = _parse_utc(tx["timestamp"])
    if tx_time is None or any(
        tx_time.timestamp() < _parse_utc(member["request_timestamp"]).timestamp() - 5
        for member in members
    ):
        return None
    expected_offer_inputs: set[str] = set()
    expected_trade_by_coin: dict[str, str] = {}
    for member in members:
        trade_id = _hex_id(member["trade_id"])
        selected = {_hex_id(value) for value in member["selected_coin_ids"]}
        expected_offer_inputs.update(selected)
        expected_trade_by_coin.update({coin_id: trade_id for coin_id in selected})
        matching = [
            row
            for row in offers
            if _hex_id(_first_present(row, "trade_id", "offer_id")) == trade_id
        ]
        if len(matching) != 1:
            return None
        if (
            trade_id != intent["sage_trade_id"]
            and _status(matching[0].get("status")) not in _CANCELLED_STATUSES
        ):
            return {"_conflict_reason": "CANCEL_COHORT_MEMBER_CONTRADICTION"}
        member_intent = {
            "sage_trade_id": trade_id,
            "side": member["side"],
            "asset_id": member["asset_id"],
            "offered_amount": int(member["offered_amount_atomic"]),
            "requested_amount": int(member["requested_amount_atomic"]),
            "selected_coin_ids": tuple(sorted(selected)),
        }
        if not _offer_summary_matches(member_intent, matching[0]):
            return {"_conflict_reason": "CANCEL_COHORT_MEMBER_CONTRADICTION"}
        observed_selected = matching[0].get("selected_coin_ids")
        if (
            type(observed_selected) is not list
            or len(observed_selected) > _MAX_SELECTED_COINS
            or {_hex_id(value) for value in observed_selected} != selected
        ):
            return {"_conflict_reason": "CANCEL_COHORT_MEMBER_CONTRADICTION"}
        if _hex_id(matching[0].get("transaction_id")) != _hex_id(tx["transaction_id"]):
            return None
    if expected_offer_inputs & set(auxiliary):
        return None
    spent = [_flow(entry) for entry in tx["spent"]]
    created = [_flow(entry) for entry in tx["created"]]
    if any(flow is None for flow in spent) or any(flow is None for flow in created):
        return None
    spent_by_id = {flow[0]: flow for flow in spent if flow}
    if len(spent_by_id) != len(spent) or set(spent_by_id) != (
        expected_offer_inputs | set(auxiliary)
    ):
        return None
    for member in members:
        selected = {_hex_id(value) for value in member["selected_coin_ids"]}
        offered_asset = "xch" if member["side"] == "buy" else member["asset_id"]
        member_flows = [spent_by_id[coin_id] for coin_id in selected]
        if any(flow[1] != offered_asset for flow in member_flows) or sum(
            flow[2] for flow in member_flows
        ) != int(member["offered_amount_atomic"]):
            return {"_conflict_reason": "CANCEL_COHORT_MEMBER_CONTRADICTION"}
    for coin_id, flow in spent_by_id.items():
        record = coins.get(coin_id)
        if record is None or not _coin_matches_flow(record, flow, tx, spent=True):
            return None
        offer_id = _norm_id(record.get("offer_id"))
        if (
            coin_id in expected_offer_inputs
            and offer_id != expected_trade_by_coin[coin_id]
        ):
            return {"_conflict_reason": "CANCEL_COHORT_MEMBER_CONTRADICTION"}
        if coin_id in auxiliary and (flow[1] != "xch" or offer_id):
            return None
    available = {flow[0]: flow for flow in created if flow}
    if len(available) != len(created):
        return None
    rebindings: list[dict[str, Any]] = []
    unmatched_xch_inputs: list[tuple[str, tuple[str, str, int, str, str, str]]] = []
    for input_id in sorted(expected_offer_inputs):
        input_flow = spent_by_id[input_id]
        candidates = sorted(
            coin_id
            for coin_id, flow in available.items()
            if flow[1:3] == input_flow[1:3]
        )
        if candidates:
            return_id = candidates[0]
            if len(candidates) > 1:
                lineage_matches = [
                    coin_id
                    for coin_id in candidates
                    if available[coin_id][4] == input_id
                    or (input_flow[5] and available[coin_id][5] == input_flow[5])
                ]
                if len(lineage_matches) != 1:
                    return {"_conflict_reason": "CANCEL_RETURN_LINEAGE_AMBIGUOUS"}
                return_id = lineage_matches[0]
            available.pop(return_id)
            rebindings.append(
                {
                    "input_coin_id": input_id,
                    "return_coin_id": return_id,
                    "asset_id": input_flow[1],
                    "amount": input_flow[2],
                }
            )
        elif input_flow[1] == "xch":
            unmatched_xch_inputs.append((input_id, input_flow))
        else:
            return None
    fee = 0
    if unmatched_xch_inputs:
        if len(unmatched_xch_inputs) != 1 or auxiliary:
            return None
        input_id, input_flow = unmatched_xch_inputs[0]
        xch_returns = sorted(
            (coin_id, flow) for coin_id, flow in available.items() if flow[1] == "xch"
        )
        if len(xch_returns) != 1 or xch_returns[0][1][2] >= input_flow[2]:
            return None
        return_id, return_flow = xch_returns[0]
        available.pop(return_id)
        fee = input_flow[2] - return_flow[2]
        rebindings.append(
            {
                "input_coin_id": input_id,
                "return_coin_id": return_id,
                "asset_id": "xch",
                "amount": return_flow[2],
            }
        )
    remaining_spent = [spent_by_id[coin_id] for coin_id in auxiliary]
    if Counter(
        (flow[1], flow[2]) for flow in remaining_spent if flow[1] != "xch"
    ) != Counter((flow[1], flow[2]) for flow in available.values() if flow[1] != "xch"):
        return None
    xch_in = sum(flow[2] for flow in remaining_spent if flow[1] == "xch")
    xch_out = sum(flow[2] for flow in available.values() if flow[1] == "xch")
    if any(flow[1] != "xch" for flow in remaining_spent) or any(
        flow[1] != "xch" for flow in available.values()
    ):
        return None
    if xch_out > xch_in:
        return None
    fee += xch_in - xch_out
    for flow in created:
        record = coins.get(flow[0])
        if record is None or not _coin_matches_flow(record, flow, tx, spent=False):
            return None
    target_ids = set(intent["selected_coin_ids"])
    return {
        "transaction_id": tx["transaction_id"],
        "spend_identity": tx.get("spend_identity"),
        "block_height": tx["confirmed_height"],
        "fee_mojos": fee,
        "grouped_cancel": len(members) > 1,
        "coin_rebindings": [
            row
            for row in sorted(rebindings, key=lambda row: row["input_coin_id"])
            if row["input_coin_id"] in target_ids
        ],
    }


def _selected_inputs_are_exactly_owned_and_linked(
    intent: dict[str, Any], coins: dict[str, dict[str, Any]]
) -> bool:
    offered_asset = "xch" if intent["side"] == "buy" else intent["asset_id"]
    selected_total = 0
    for coin_id in intent["selected_coin_ids"]:
        record = coins.get(coin_id)
        offer_link = _norm_id(record.get("offer_id")) if record else ""
        amount = _positive_int(record.get("amount")) if record else None
        if (
            record is None
            or record.get("owned") is not True
            or record.get("spent_height") not in (None, 0)
            or _asset(record.get("asset_id")) != offered_asset
            or amount is None
            or offer_link
            not in {
                intent["sage_trade_id"],
                _norm_id(intent["offer_text_sha256"]),
            }
        ):
            return False
        selected_total += amount
    return selected_total == intent["offered_amount"]


def _classify_terminal_evidence(
    intent: Any,
    evidence: Any,
    *,
    cancel_context: Any = None,
    now: Any = None,
) -> dict[str, Any]:
    """Classify immutable evidence without database, wallet, or clock side effects."""

    exact_intent = _exact_intent(intent)
    if exact_intent is None or type(evidence) is not dict:
        return _unknown("EVIDENCE_SCHEMA_INVALID")
    if (
        evidence.get("schema_version") != 1
        or type(evidence.get("schema_version")) is not int
    ):
        return _unknown("EVIDENCE_SCHEMA_INVALID")
    observed_now = datetime.now(timezone.utc) if now is None else _parse_utc(now)
    if observed_now is None:
        return _unknown("NOW_TIMESTAMP_INVALID")
    source_error = _source_error(evidence, observed_now)
    if source_error:
        return _unknown(source_error)
    if (
        _hex_id(evidence.get("wallet_fingerprint_hash"))
        != exact_intent["wallet_fingerprint_hash"]
        or evidence.get("network") != exact_intent["network"]
    ):
        return _unknown("WALLET_NETWORK_BINDING_MISMATCH")
    offer_rows = evidence["offer_history"].get("records")
    raw_transactions = evidence["transaction_history"].get("records")
    raw_coins = evidence["coin_records"].get("records")
    if (
        type(offer_rows) is list
        and len(offer_rows) > _MAX_HISTORY_RECORDS
        or type(raw_transactions) is list
        and len(raw_transactions) > _MAX_HISTORY_RECORDS
        or type(raw_coins) is dict
        and len(raw_coins) > _MAX_COIN_RECORDS
    ):
        return _unknown("EVIDENCE_SOURCE_LIMIT_EXCEEDED")
    transactions = _transaction_rows(evidence["transaction_history"])
    coins = _coin_map(evidence["coin_records"])
    if type(offer_rows) is not list or transactions is None or coins is None:
        return _unknown("EVIDENCE_SCHEMA_INVALID")
    if any(type(row) is not dict for row in offer_rows):
        return _unknown("EVIDENCE_SCHEMA_INVALID")
    try:
        offer_rows = _dedupe_records(offer_rows, "trade_id")
        transactions = _dedupe_records(transactions, "transaction_id")
    except (TypeError, ValueError):
        return _unknown("EVIDENCE_SCHEMA_INVALID")
    matches = [
        row
        for row in offer_rows
        if type(row) is dict
        and _hex_id(_first_present(row, "trade_id", "offer_id"))
        == exact_intent["sage_trade_id"]
    ]
    if not matches:
        return _unknown("OFFER_ABSENCE_NOT_PROOF")
    if len(matches) != 1:
        return _conflict("DUPLICATE_OFFER_IDENTITY")
    offer = matches[0]
    if not _offer_summary_matches(exact_intent, offer):
        return _unknown("OFFER_IDENTITY_OR_AMOUNT_MISMATCH")
    status = _status(offer.get("status"))
    transaction_id = offer.get("transaction_id")
    target_transaction_id = _hex_id(transaction_id)
    if target_transaction_id:
        tx_matches = [
            row
            for row in transactions
            if _hex_id(row.get("transaction_id")) == target_transaction_id
        ]
        if len(tx_matches) > 1:
            return _conflict("DUPLICATE_TRANSACTION_IDENTITY")
    tx = (
        _exact_transaction(transactions, transaction_id)
        if type(transaction_id) is str and transaction_id
        else None
    )
    if tx is not None:
        tx_time = _parse_utc(tx.get("timestamp"))
        if tx_time is not None and tx_time < exact_intent["offer_created_at"]:
            return _unknown("FILL_PREDATES_OFFER")
        if tx_time is not None and tx_time > observed_now:
            return _unknown("TRANSACTION_TIME_OUTSIDE_EVIDENCE_WINDOW")
    fill = _fill_proof(exact_intent, offer, tx, coins) if tx is not None else None
    cancel = (
        _cancel_proof(exact_intent, offer_rows, tx, coins, cancel_context)
        if tx is not None and cancel_context is not None
        else None
    )
    if cancel is not None and cancel.get("_conflict_reason"):
        return _conflict(cancel["_conflict_reason"])
    if status in _FILLED_STATUSES and cancel is not None:
        return _conflict()
    if status in (_ACTIVE_STATUSES | _EXPIRED_STATUSES) and (
        fill is not None or cancel is not None
    ):
        return _conflict()
    # A grouped cancellation can return another cohort member's asset in the
    # exact amount this member requested.  The complete request-bound return
    # flow disambiguates that apparent receipt; without it, fail as conflict.
    if status in _CANCELLED_STATUSES and cancel is not None:
        return {
            "classification": CANCELLED_PROVEN,
            "reason_code": "EXACT_CANCEL_RETURN_PROOF",
            **cancel,
        }
    if status in _CANCELLED_STATUSES and fill is not None:
        return _conflict()
    if fill is not None and cancel is not None:
        return _conflict()
    if status in _FILLED_STATUSES:
        if fill is None:
            return _unknown("FILL_PROOF_INCOMPLETE")
        return {
            "classification": FILLED_PROVEN,
            "reason_code": "EXACT_FILL_PROOF",
            **fill,
        }
    if status in _CANCELLED_STATUSES:
        return _unknown("CANCEL_PROOF_INCOMPLETE")
    if status in _EXPIRED_STATUSES:
        if not _selected_inputs_are_exactly_owned_and_linked(exact_intent, coins):
            return _unknown("EXPIRY_SAFE_RELEASE_UNPROVEN")
        return {
            "classification": EXPIRED_PROVEN,
            "reason_code": "AUTHORITATIVE_EXPIRY_PROOF",
            "input_coins_owned_unlocked": True,
        }
    if status in _ACTIVE_STATUSES:
        if not _selected_inputs_are_exactly_owned_and_linked(exact_intent, coins):
            return _unknown("ACTIVE_INPUT_STATE_UNPROVEN")
        return {
            "classification": ACTIVE_PROVEN,
            "reason_code": "AUTHORITATIVE_ACTIVE_PROOF",
        }
    return _unknown("OFFER_STATUS_UNKNOWN")


def classify_terminal_evidence(
    intent: Any,
    evidence: Any,
    *,
    cancel_context: Any = None,
    now: Any = None,
) -> dict[str, Any]:
    """Total public classifier boundary for untrusted wallet evidence."""

    try:
        return _classify_terminal_evidence(
            intent,
            evidence,
            cancel_context=cancel_context,
            now=now,
        )
    except BaseException:
        return _unknown("EVIDENCE_SCHEMA_INVALID")


def _offer_list(
    result: Any, *, record_cap: int = _MAX_HISTORY_RECORDS
) -> list[dict[str, Any]] | None:
    if type(result) is list:
        rows = result
    elif type(result) is dict:
        if len(result) > _MAX_PROVIDER_RECORD_FIELDS:
            raise _SourceLimitError("offer response fields exceed source limit")
        rows = None
        for key in ("trades", "offers", "trade_records"):
            candidate = result.get(key)
            if type(candidate) is list:
                rows = candidate
                break
        if rows is None:
            return None
    else:
        return None
    if len(rows) > min(record_cap, _MAX_HISTORY_RECORDS):
        raise _SourceLimitError("offer rows exceed source limit")
    if any(type(row) is not dict for row in rows):
        return None
    if any(len(row) > _MAX_PROVIDER_RECORD_FIELDS for row in rows):
        raise _SourceLimitError("offer record fields exceed source limit")
    _require_provider_bounds(result)
    return rows


def _dedupe_records(records: Any, identity_key: str) -> list[dict[str, Any]]:
    if type(records) is not list or len(records) > _MAX_HISTORY_RECORDS:
        raise _SourceLimitError("history records exceed source limit")
    by_id: dict[str, list[dict[str, Any]]] = {}
    canonical_by_id: dict[str, set[str]] = {}
    anonymous: list[dict[str, Any]] = []
    for row in records:
        raw_identity = row.get(identity_key)
        if raw_identity is None and identity_key == "trade_id":
            raw_identity = row.get("offer_id")
        identity = _norm_id(raw_identity)
        if identity:
            bounded_row = _redact_json(row, redact_sensitive=False)
            canonical = json.dumps(
                bounded_row,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            seen = canonical_by_id.setdefault(identity, set())
            if canonical not in seen:
                by_id.setdefault(identity, []).append(row)
                seen.add(canonical)
        else:
            anonymous.append(row)
    return [row for key in sorted(by_id) for row in by_id[key]] + anonymous


def _authoritative_page_end(result: Any, row_count: int) -> bool:
    if type(result) is not dict:
        return False
    total = result.get("total")
    if type(total) is int and total >= 0 and total == row_count:
        return True
    return bool(result.get("end_of_history") is True or result.get("has_more") is False)


def load_sage_offer_history(
    *,
    get_all_offers: Callable[..., Any],
    include_completed: bool,
    clock: Callable[[], Any] | None = None,
    page_size: int = 50,
    max_pages: int = 20,
    max_records: int = 1000,
) -> dict[str, Any]:
    """Read bounded Sage offer pages and normalize ignored filters locally."""

    if type(include_completed) is not bool or any(
        type(value) is not int or value <= 0
        for value in (page_size, max_pages, max_records)
    ):
        raise ValueError("offer history bounds and include_completed must be exact")
    if (
        page_size > _MAX_HISTORY_PAGE_SIZE
        or max_pages > _MAX_HISTORY_PAGES
        or max_records > _MAX_HISTORY_RECORDS
    ):
        raise ValueError("offer history bounds exceed hard limits")
    pages: list[list[dict[str, Any]]] = []
    collected_count = 0
    read_times: list[str] = []
    source_times: list[str] = []
    read_error = None
    complete = False
    remote_bounds_honored = True
    stable_oversized = False
    authoritative_end = False
    for page_index in range(max_pages):
        start = page_index * page_size
        try:
            result = get_all_offers(
                include_completed=include_completed,
                start=start,
                end=start + page_size,
            )
        except BaseException:
            read_times.append(_clock_utc(clock))
            read_error = "reader_exception"
            break
        read_times.append(_clock_utc(clock))
        try:
            rows = _offer_list(result, record_cap=max_records - collected_count)
        except _SourceLimitError:
            read_error = "source_limit_exceeded"
            break
        except (TypeError, ValueError):
            read_error = "normalization_exception"
            break
        if rows is None:
            read_error = "reader_malformed"
            break
        provided_timestamp = _source_timestamp(result)
        if type(provided_timestamp) is str:
            source_times.append(provided_timestamp)
        pages.append(rows)
        collected_count += len(rows)
        page_authoritative_end = _authoritative_page_end(result, len(rows))
        try:
            repeated_first_page = page_index > 0 and rows == pages[0]
        except BaseException:
            pages.pop()
            collected_count -= len(rows)
            read_error = "normalization_exception"
            break
        if repeated_first_page and len(rows) >= page_size:
            remote_bounds_honored = False
            stable_oversized = len(rows) > page_size
            authoritative_end = page_authoritative_end
            complete = authoritative_end and len(rows) <= max_records
            pages = [pages[0]]
            break
        if len(rows) > page_size:
            remote_bounds_honored = False
            if page_authoritative_end and len(rows) <= max_records:
                authoritative_end = True
                complete = True
                break
            continue
        if len(rows) < page_size:
            complete = True
            break
        if collected_count >= max_records:
            break
    try:
        collected_records: list[dict[str, Any]] = []
        for page in pages:
            collected_records.extend(page)
        records = _dedupe_records(collected_records, "trade_id")
    except BaseException:
        records = []
        complete = False
        read_error = "normalization_exception"
    if not include_completed:
        records = [
            row
            for row in records
            if _status(row.get("status")) not in _TERMINAL_STATUSES
        ]
    return {
        "observed_at": read_times[-1] if read_times else _clock_utc(clock),
        "source_observed_at": source_times[-1] if source_times else None,
        "source_observed_at_all": source_times,
        "read_observed_at": read_times or [_clock_utc(clock)],
        "provenance": "wallet.get_all_offers",
        "complete": complete,
        "read_error": read_error,
        "records": records,
        "include_completed_normalized": True,
        "pagination": {
            "pages_read": len(pages) if pages else 1,
            "page_size": page_size,
            "remote_bounds_honored": remote_bounds_honored,
            "locally_normalized": True,
            "stable_oversized_snapshot": stable_oversized,
            "authoritative_end": authoritative_end,
        },
    }


def _normalized_transaction_flow(entry: Any) -> dict[str, Any] | None:
    if type(entry) is not dict:
        return None
    if len(entry) > _MAX_PROVIDER_RECORD_FIELDS:
        raise _SourceLimitError("transaction flow fields exceed source limit")
    _require_provider_bounds(entry)
    coin_id = _hex_id(_first_present(entry, "coin_id", "name", "id"))
    asset_present = "asset_id" in entry
    asset_value = entry.get("asset_id")
    if not asset_present and type(entry.get("asset")) is dict:
        asset_present = "asset_id" in entry["asset"]
        asset_value = entry["asset"].get("asset_id")
    asset_id = "xch" if asset_present and asset_value is None else _asset(asset_value)
    raw_amount = entry.get("amount")
    amount_text = _atomic_text(raw_amount)
    address_kind = entry.get("address_kind")
    if (
        not coin_id
        or not asset_present
        or not asset_id
        or not amount_text
        or address_kind not in {None, "own", "offer"}
    ):
        return None
    normalized = {
        "coin_id": coin_id,
        "asset_id": asset_id,
        "amount": int(amount_text),
        "address_kind": address_kind,
    }
    raw_parent = _first_present(entry, "parent_coin_id", "parent_id", "source_coin_id")
    if raw_parent is not None:
        parent_coin_id = _hex_id(raw_parent)
        if not parent_coin_id:
            return None
        normalized["parent_coin_id"] = parent_coin_id
    raw_condition = entry.get("spend_condition_id")
    if raw_condition is not None:
        if type(raw_condition) is not str or not raw_condition.strip():
            return None
        normalized["spend_condition_id"] = raw_condition
    return normalized


def _normalized_transaction_row(row: dict[str, Any]) -> dict[str, Any]:
    if type(row) is not dict:
        raise ValueError("transaction row must be an exact object")
    if len(row) > _MAX_PROVIDER_RECORD_FIELDS:
        raise _SourceLimitError("transaction record fields exceed source limit")
    raw_spent = row.get("spent")
    if raw_spent is None:
        raw_spent = row.get("removals")
    raw_created = row.get("created")
    if raw_created is None:
        raw_created = row.get("additions")
    if type(raw_spent) is list and len(raw_spent) > _MAX_TRANSACTION_FLOWS:
        raise _SourceLimitError("transaction spent flow source limit exceeded")
    if type(raw_created) is list and len(raw_created) > _MAX_TRANSACTION_FLOWS:
        raise _SourceLimitError("transaction created flow source limit exceeded")
    for flows in (raw_spent, raw_created):
        if type(flows) is list and any(
            type(entry) is dict and len(entry) > _MAX_PROVIDER_RECORD_FIELDS
            for entry in flows
        ):
            raise _SourceLimitError("transaction flow fields exceed source limit")
    _require_provider_bounds(row)
    transaction_id = _hex_id(_first_present(row, "transaction_id", "name", "tx_id"))
    spend_identity = _first_present(row, "spend_identity", "spend_bundle_id")
    if type(spend_identity) is not str or not spend_identity:
        spend_identity = None
    raw_height = row.get("confirmed_height")
    if raw_height is None:
        raw_height = row.get("confirmed_at_height")
    height_text = _atomic_text(raw_height)
    confirmed_height = int(height_text) if height_text else None
    raw_timestamp = row.get("timestamp")
    if raw_timestamp is None:
        raw_timestamp = row.get("created_at_time")
    if _is_canonical_utc_text(raw_timestamp):
        timestamp = raw_timestamp
    elif type(raw_timestamp) is int and raw_timestamp > 0:
        try:
            timestamp = _canonical_utc(
                datetime.fromtimestamp(raw_timestamp, timezone.utc)
            )
        except (OverflowError, OSError, ValueError):
            timestamp = None
    else:
        timestamp = None
    spent = (
        [_normalized_transaction_flow(entry) for entry in raw_spent]
        if type(raw_spent) is list
        else None
    )
    created = (
        [_normalized_transaction_flow(entry) for entry in raw_created]
        if type(raw_created) is list
        else None
    )
    return {
        "transaction_id": transaction_id,
        "spend_identity": spend_identity,
        "confirmed": row.get("confirmed") is True,
        "confirmed_height": confirmed_height,
        "timestamp": timestamp,
        "spent": spent,
        "created": created,
    }


def _load_transactions(
    reader: Callable[..., Any],
    *,
    wallet_ids: tuple[int, ...],
    clock: Callable[[], Any] | None,
    page_size: int,
    max_pages: int,
    max_records: int,
) -> dict[str, Any]:
    if (
        type(wallet_ids) is not tuple
        or not wallet_ids
        or len(wallet_ids) > _MAX_WALLET_IDS
        or any(type(wallet_id) is not int or wallet_id <= 0 for wallet_id in wallet_ids)
        or len(set(wallet_ids)) != len(wallet_ids)
        or any(
            type(value) is not int or value <= 0
            for value in (page_size, max_pages, max_records)
        )
    ):
        raise ValueError("transaction history bounds must be exact")
    if (
        page_size > _MAX_HISTORY_PAGE_SIZE
        or max_pages > _MAX_HISTORY_PAGES
        or max_records > _MAX_HISTORY_RECORDS
    ):
        raise ValueError("transaction history bounds exceed hard limits")
    records: list[dict[str, Any]] = []
    complete = True
    pages_read = 0
    read_times: list[str] = []
    source_times: list[str] = []
    read_error = None
    remote_bounds_honored = True
    stable_oversized = False
    authoritative_end = False
    for wallet_id in wallet_ids:
        wallet_complete = False
        previous_rows: list[dict[str, Any]] | None = None
        for page_index in range(max_pages):
            start = page_index * page_size
            try:
                result = reader(
                    wallet_id=wallet_id,
                    start=start,
                    end=start + page_size,
                    sort_key="CONFIRMED_AT_HEIGHT",
                    reverse=True,
                )
            except BaseException:
                pages_read += 1
                read_times.append(_clock_utc(clock))
                read_error = "reader_exception"
                complete = False
                break
            pages_read += 1
            read_times.append(_clock_utc(clock))
            if (
                type(result) is not dict
                or result.get("success") is not True
                or type(result.get("transactions")) is not list
            ):
                read_error = "reader_malformed"
                complete = False
                break
            rows = result["transactions"]
            if len(rows) > _MAX_HISTORY_RECORDS or len(rows) > max_records - len(
                records
            ):
                read_error = "source_limit_exceeded"
                complete = False
                break
            if any(type(row) is not dict for row in rows):
                read_error = "reader_malformed"
                complete = False
                break
            if len(result) > _MAX_PROVIDER_RECORD_FIELDS or any(
                len(row) > _MAX_PROVIDER_RECORD_FIELDS for row in rows
            ):
                read_error = "source_limit_exceeded"
                complete = False
                break
            try:
                _require_provider_bounds(result)
            except _SourceLimitError:
                read_error = "source_limit_exceeded"
                complete = False
                break
            except BaseException:
                read_error = "normalization_exception"
                complete = False
                break
            provided_timestamp = _source_timestamp(result)
            if type(provided_timestamp) is str:
                source_times.append(provided_timestamp)
            try:
                repeated_page = previous_rows is not None and rows == previous_rows
            except BaseException:
                read_error = "normalization_exception"
                complete = False
                break
            if repeated_page and len(rows) >= page_size:
                remote_bounds_honored = False
                complete = False
                break
            previous_rows = rows
            try:
                normalized_page = [_normalized_transaction_row(row) for row in rows]
            except _SourceLimitError:
                read_error = "source_limit_exceeded"
                complete = False
                break
            except BaseException:
                read_error = "normalization_exception"
                complete = False
                break
            records.extend(normalized_page)
            total = result.get("total")
            if len(rows) > page_size:
                remote_bounds_honored = False
                if (
                    type(total) is int
                    and total == len(rows)
                    and len(rows) <= max_records
                ):
                    stable_oversized = True
                    authoritative_end = True
                    wallet_complete = True
                else:
                    complete = False
                break
            if type(total) is int and total >= 0 and start + len(rows) >= total:
                wallet_complete = True
                break
            if len(rows) < page_size:
                wallet_complete = True
                break
            if len(records) >= max_records:
                break
        complete = complete and wallet_complete
        if len(records) >= max_records:
            complete = False
            break
    try:
        records = _dedupe_records(records, "transaction_id")
    except BaseException:
        records = []
        complete = False
        read_error = "normalization_exception"
    return {
        "observed_at": read_times[-1] if read_times else _clock_utc(clock),
        "source_observed_at": source_times[-1] if source_times else None,
        "source_observed_at_all": source_times,
        "read_observed_at": read_times or [_clock_utc(clock)],
        "provenance": "wallet.get_transactions_list",
        "complete": complete,
        "read_error": read_error,
        "records": records,
        "pagination": {
            "pages_read": max(1, pages_read),
            "page_size": page_size,
            "remote_bounds_honored": remote_bounds_honored,
            "locally_normalized": True,
            "stable_oversized_snapshot": stable_oversized,
            "authoritative_end": authoritative_end,
        },
    }


def load_authoritative_evidence(
    intent: Any,
    *,
    wallet_facade: Any = None,
    clock: Callable[[], Any] | None = None,
    wallet_ids: tuple[int, ...] = (1,),
    page_size: int = 50,
    max_pages: int = 20,
    max_records: int = 1000,
) -> dict[str, Any]:
    """Collect all read-only wallet evidence before any database transaction."""

    exact_intent = _exact_intent(intent)
    if exact_intent is None:
        raise ValueError("intent is not an exact registered offer")
    if (
        type(wallet_ids) is not tuple
        or not wallet_ids
        or len(wallet_ids) > _MAX_WALLET_IDS
        or any(type(wallet_id) is not int or wallet_id <= 0 for wallet_id in wallet_ids)
        or len(set(wallet_ids)) != len(wallet_ids)
        or any(
            type(value) is not int or value <= 0
            for value in (page_size, max_pages, max_records)
        )
    ):
        raise ValueError("authoritative loader bounds must be exact")
    if (
        page_size > _MAX_HISTORY_PAGE_SIZE
        or max_pages > _MAX_HISTORY_PAGES
        or max_records > _MAX_HISTORY_RECORDS
    ):
        raise ValueError("authoritative loader bounds exceed hard limits")
    if wallet_facade is None:
        import wallet as wallet_facade
    collection_started_at = _clock_utc(clock)
    try:
        identity_reader = getattr(wallet_facade, "get_wallet_identity")
        identity = identity_reader()
        if type(identity) is dict:
            if len(identity) > _MAX_PROVIDER_RECORD_FIELDS:
                raise _SourceLimitError("wallet identity fields exceed source limit")
            _require_provider_bounds(identity)
        identity_error = None
    except _SourceLimitError:
        identity = None
        identity_error = "source_limit_exceeded"
    except BaseException:
        identity = None
        identity_error = "reader_exception"
    identity_read_at = _clock_utc(clock)
    identity_observed = (
        _parse_utc(identity.get("observed_at_utc"))
        if type(identity) is dict
        and _is_canonical_utc_text(identity.get("observed_at_utc"))
        else None
    )
    evidence_observed = _parse_utc(identity_read_at)
    identity_age = (
        (evidence_observed - identity_observed).total_seconds()
        if evidence_observed is not None and identity_observed is not None
        else None
    )
    identity_valid = bool(
        type(identity) is dict
        and identity.get("success") is True
        and identity_age is not None
        and -30 <= identity_age <= _MAX_EVIDENCE_AGE_SECONDS
        and type(identity.get("network_id")) is str
        and identity["network_id"]
    )
    wallet_hash = identity.get("wallet_fingerprint_hash") if identity_valid else None
    if (
        not _hex_id(wallet_hash)
        and identity_valid
        and type(identity.get("fingerprint")) is int
        and identity["fingerprint"] > 0
    ):
        wallet_hash = hashlib.sha256(
            f"fingerprint:{identity['fingerprint']}".encode("utf-8")
        ).hexdigest()
    network = identity.get("network_id") if identity_valid else None

    try:
        offer_reader = getattr(wallet_facade, "get_all_offers")
    except BaseException:
        offer_reader = None

    def unavailable_offer_reader(**_kwargs):
        raise RuntimeError("offer reader unavailable")

    offers = load_sage_offer_history(
        get_all_offers=(
            offer_reader if callable(offer_reader) else unavailable_offer_reader
        ),
        include_completed=True,
        clock=clock,
        page_size=page_size,
        max_pages=max_pages,
        max_records=max_records,
    )
    try:
        transaction_reader = getattr(wallet_facade, "get_transactions_list")
    except BaseException:
        transaction_reader = None

    def unavailable_transaction_reader(**_kwargs):
        raise RuntimeError("transaction reader unavailable")

    transactions = _load_transactions(
        (
            transaction_reader
            if callable(transaction_reader)
            else unavailable_transaction_reader
        ),
        wallet_ids=wallet_ids,
        clock=clock,
        page_size=page_size,
        max_pages=max_pages,
        max_records=max_records,
    )
    required_ids = set(exact_intent["selected_coin_ids"])
    coin_cap_exceeded = False
    for tx in transactions["records"]:
        for flow_name in ("spent", "created"):
            flows = tx.get(flow_name)
            if type(flows) is not list or len(flows) > _MAX_TRANSACTION_FLOWS:
                coin_cap_exceeded = True
                continue
            for entry in flows:
                flow = _flow(entry)
                if flow:
                    if (
                        flow[0] not in required_ids
                        and len(required_ids) >= _MAX_COIN_RECORDS
                    ):
                        coin_cap_exceeded = True
                        continue
                    required_ids.add(flow[0])
    try:
        coin_reader = getattr(wallet_facade, "get_coins_by_ids")
        raw_coin_result = coin_reader(sorted(required_ids))
        coin_error = None
    except BaseException:
        raw_coin_result = None
        coin_error = "reader_exception"
    coin_read_at = _clock_utc(clock)
    coin_source_observed_at = None
    if (
        type(raw_coin_result) is dict
        and raw_coin_result.get("success") is True
        and type(raw_coin_result.get("records")) is dict
    ):
        raw_coins = raw_coin_result["records"]
    else:
        raw_coins = raw_coin_result
    normalized_coins: dict[str, dict[str, Any]] = {}
    if type(raw_coins) is not dict and coin_error is None:
        coin_error = "reader_malformed"
    elif type(raw_coins) is dict and len(raw_coins) > _MAX_COIN_RECORDS:
        coin_error = "source_limit_exceeded"
    elif type(raw_coins) is dict:
        try:
            if any(
                type(raw_record) is dict
                and len(raw_record) > _MAX_PROVIDER_RECORD_FIELDS
                for raw_record in raw_coins.values()
            ):
                raise _SourceLimitError("coin record fields exceed source limit")
            _require_provider_bounds(raw_coin_result)
            coin_source_observed_at = _source_timestamp(raw_coin_result)
            for raw_id, raw_record in raw_coins.items():
                if type(raw_record) is not dict:
                    continue
                explicit_id = raw_record.get("coin_id")
                if explicit_id is None:
                    candidate_id = raw_id
                elif type(explicit_id) is str:
                    candidate_id = explicit_id
                else:
                    raise ValueError("coin record identity is not exact text")
                coin_id = _hex_id(candidate_id)
                if not coin_id:
                    continue
                record = dict(raw_record)
                record["coin_id"] = coin_id
                normalized_coins[coin_id] = record
        except _SourceLimitError:
            normalized_coins = {}
            coin_error = "source_limit_exceeded"
        except BaseException:
            normalized_coins = {}
            coin_error = "normalization_exception"
    if coin_cap_exceeded and coin_error is None:
        coin_error = "source_limit_exceeded"
    coin_complete = bool(
        not coin_cap_exceeded
        and type(raw_coins) is dict
        and set(normalized_coins) == required_ids
        and coin_error is None
    )
    collected_at = _clock_utc(clock)
    return {
        "schema_version": 1,
        "collection_started_at": collection_started_at,
        "observed_at": collected_at,
        "wallet_fingerprint_hash": _norm_id(wallet_hash),
        "network": network,
        "wallet_identity": {
            "observed_at": identity_read_at,
            "source_observed_at": (
                identity.get("observed_at_utc") if type(identity) is dict else None
            ),
            "source_observed_at_all": (
                [identity["observed_at_utc"]]
                if type(identity) is dict
                and type(identity.get("observed_at_utc")) is str
                else []
            ),
            "read_observed_at": [identity_read_at],
            "provenance": "wallet.get_wallet_identity",
            "complete": identity_valid,
            "read_error": identity_error,
        },
        "offer_history": offers,
        "transaction_history": transactions,
        "coin_records": {
            "observed_at": coin_read_at,
            "source_observed_at": (
                coin_source_observed_at
                if type(coin_source_observed_at) is str
                else None
            ),
            "read_observed_at": [coin_read_at],
            "provenance": "wallet.get_coins_by_ids",
            "complete": coin_complete,
            "read_error": coin_error,
            "records": normalized_coins,
            "pagination": {
                "pages_read": 1,
                "page_size": max(1, len(required_ids)),
                "remote_bounds_honored": True,
                "locally_normalized": True,
            },
        },
        "local_expired": False,
    }


def _registry_evidence(
    intent: dict[str, Any], result: dict[str, Any], observed_at: str
) -> tuple[RegistryState, OfferEvidence]:
    classification = result["classification"]
    terminal = {
        FILLED_PROVEN: (TerminalOutcome.FILLED, EvidenceSource.EXACT_TRANSACTION),
        CANCELLED_PROVEN: (
            TerminalOutcome.CANCELLED,
            EvidenceSource.EXACT_TRANSACTION,
        ),
        EXPIRED_PROVEN: (
            TerminalOutcome.EXPIRED,
            EvidenceSource.AUTHORITATIVE_WALLET,
        ),
    }
    if classification in terminal:
        outcome, source = terminal[classification]
        destination = RegistryState.TERMINAL
    elif classification == CONFLICT:
        outcome = None
        source = EvidenceSource.AUTHORITATIVE_WALLET
        destination = RegistryState.CONFLICTED
    elif classification == UNKNOWN:
        outcome = None
        source = EvidenceSource.AUTHORITATIVE_WALLET
        destination = RegistryState.UNKNOWN
    else:
        outcome = None
        source = EvidenceSource.AUTHORITATIVE_WALLET
        current = RegistryState(intent["lifecycle_state"])
        destination = (
            current
            if current
            in {
                RegistryState.CREATED,
                RegistryState.VISIBLE,
                RegistryState.CANCEL_REQUESTED,
            }
            else RegistryState.CREATED
        )
    exact = _exact_intent(intent)
    assert exact is not None
    registry_evidence = OfferEvidence(
        observed_state=destination,
        terminal_outcome=outcome,
        source=source,
        intent_id=exact["intent_id"],
        wallet_fingerprint_hash=exact["wallet_fingerprint_hash"],
        network=exact["network"],
        offered_amount_atomic=exact["offered_amount_atomic"],
        requested_amount_atomic=exact["requested_amount_atomic"],
        selected_coin_ids=exact["selected_coin_ids"],
        sage_trade_id=exact["sage_trade_id"],
        offer_text_sha256=exact["offer_text_sha256"],
        observed_at=observed_at,
        transaction_id=result.get("transaction_id"),
        spend_identity=result.get("spend_identity"),
        block_height=result.get("block_height"),
        input_coins_owned_unlocked=result.get("input_coins_owned_unlocked") is True,
    )
    return destination, registry_evidence


def _trip_denial_latch(
    intent: dict[str, Any],
    operation_id: str,
    code: str,
    reason: str,
    now: Any,
) -> None:
    import database

    database.trip_runtime_safety_latch(
        reason_code=code,
        reason=reason,
        blocking_operation_ids=[operation_id],
        wallet_fingerprint_hash=intent["wallet_fingerprint_hash"],
        network=intent["network"],
        tripped_at=now,
    )


def _incomplete_loader_evidence(
    intent: dict[str, Any], observed_at: str
) -> dict[str, Any]:
    def failed_source(provenance: str) -> dict[str, Any]:
        return {
            "observed_at": observed_at,
            "source_observed_at": None,
            "read_observed_at": [observed_at],
            "provenance": provenance,
            "complete": False,
            "read_error": "collection_exception",
            "records": {},
            "pagination": {
                "pages_read": 1,
                "page_size": 1,
                "remote_bounds_honored": False,
                "locally_normalized": True,
            },
        }

    offers = failed_source("wallet.get_all_offers")
    offers["records"] = []
    transactions = failed_source("wallet.get_transactions_list")
    transactions["records"] = []
    return {
        "schema_version": 1,
        "collection_started_at": observed_at,
        "observed_at": observed_at,
        "wallet_fingerprint_hash": intent["wallet_fingerprint_hash"],
        "network": intent["network"],
        "wallet_identity": {
            "observed_at": observed_at,
            "source_observed_at": None,
            "source_observed_at_all": [],
            "read_observed_at": [observed_at],
            "provenance": "wallet.get_wallet_identity",
            "complete": False,
            "read_error": "collection_exception",
        },
        "offer_history": offers,
        "transaction_history": transactions,
        "coin_records": failed_source("wallet.get_coins_by_ids"),
        "local_expired": False,
    }


class _PostFillEffectUncertain(RuntimeError):
    """A durable or process effect may exist but its acknowledgement is unsure."""


def _post_fill_hook_callbacks(fill: dict[str, Any]) -> dict[str, Callable[..., Any]]:
    """Build additive, replay-safe callbacks for one committed durable fill."""

    import database

    trade_id = fill["trade_id"]
    stored_offer = database.get_offer(trade_id)
    offer = stored_offer if type(stored_offer) is dict else {}
    stored_coin_id = offer.get("coin_id")
    coin_id = (
        stored_coin_id
        if type(stored_coin_id) is str and stored_coin_id.strip()
        else "unknown"
    )
    fill_detail = {
        "fill_id": fill["fill_id"],
        "trade_id": trade_id,
        "side": fill["side"],
        "price": fill["price_xch"],
        "size_xch": fill["size_xch"],
        "size_cat": fill["size_cat"],
        "tier": fill["tier"],
        "coin_id": coin_id,
        "timestamp": fill["filled_at"],
        "spent_block_index": fill.get("spent_block_index"),
    }
    classification_box: dict[str, Any] = {}

    def offer_filled_event(
        _row: dict[str, Any], *, claim_token: str, claim_generation: int
    ) -> dict[str, Any]:
        return database.log_authoritative_offer_filled_once(
            int(fill["fill_id"]),
            f"{str(fill['side']).upper()} offer {trade_id[:16]}... "
            "filled from authoritative on-chain proof",
            {
                "fill_id": fill["fill_id"],
                "trade_id": trade_id,
                "side": fill["side"],
                "tier": fill["tier"],
                "filled_at": fill["filled_at"],
                "spent_block_index": fill.get("spent_block_index"),
            },
            created_at=fill["filled_at"],
            claim_token=claim_token,
            claim_generation=claim_generation,
        )

    def boost_notification(
        _row: dict[str, Any], *, claim_token: str, claim_generation: int
    ) -> dict[str, Any]:
        tier = fill.get("tier")
        applicable = type(tier) is str and tier.lower() == "boost"
        if not applicable:
            return database.record_offer_fill_hook_sink_ack(
                int(fill["fill_id"]),
                "boost_notification",
                {"trade_id": trade_id, "applicable": False},
                claim_token=claim_token,
                claim_generation=claim_generation,
            )
        api_server = sys.modules.get("api_server")
        bot_ref = getattr(api_server, "bot", None) if api_server is not None else None
        manager = getattr(bot_ref, "boost_manager", None) if bot_ref else None
        if (
            manager is None
            or not hasattr(manager, "notify_authoritative_boost_fill")
            or not hasattr(manager, "capture_authoritative_boost_fill_materialization")
        ):
            raise RuntimeError("BoostManager is unavailable")
        stored_command = database.get_authoritative_boost_fill_command(
            int(fill["fill_id"])
        )
        materialization = (
            stored_command.get("materialization")
            if type(stored_command) is dict
            else None
        )
        if type(materialization) is not dict:
            materialization = manager.capture_authoritative_boost_fill_materialization(
                int(fill["fill_id"]), trade_id, str(fill["side"])
            )
        if type(materialization) is not dict:
            raise RuntimeError("BoostManager has no exact authoritative probe state")
        command = database.register_authoritative_boost_fill_command(
            int(fill["fill_id"]),
            trade_id,
            str(fill["side"]),
            materialization=materialization,
            claim_token=claim_token,
            claim_generation=claim_generation,
        )
        effect_state = manager.notify_authoritative_boost_fill(
            int(fill["fill_id"]),
            trade_id,
            str(fill["side"]),
            command["materialization"],
        )
        if type(effect_state) is not dict:
            raise RuntimeError("BoostManager returned no exact authoritative effect")
        try:
            return database.complete_authoritative_boost_fill_command(
                int(fill["fill_id"]),
                trade_id,
                str(fill["side"]),
                effect_state,
                claim_token=claim_token,
                claim_generation=claim_generation,
            )
        except Exception as exc:
            raise _PostFillEffectUncertain(
                "Boost effect succeeded before durable acknowledgement"
            ) from exc

    def classification():
        existing = classification_box.get("value")
        if existing is not None:
            return existing
        from fill_classifier import classify_fill

        result = classify_fill(trade_id, fill_detail, None)
        result.side = fill["side"]
        classification_box["value"] = result
        return result

    def fill_classification(
        _row: dict[str, Any], *, claim_token: str, claim_generation: int
    ) -> dict[str, Any]:
        result = classification()
        acknowledgement = database.store_authoritative_fill_classification_ack(
            int(fill["fill_id"]),
            {
                "classification": result.classification,
                "spent_block_index": result.spent_block_index,
                "taker_puzzle_hash": result.taker_puzzle_hash,
                "sweep_group_id": result.sweep_group_id,
            },
            claim_token=claim_token,
            claim_generation=claim_generation,
        )
        return acknowledgement

    def sweep_registration(
        _row: dict[str, Any], *, claim_token: str, claim_generation: int
    ) -> dict[str, Any]:
        result = classification()
        database.register_authoritative_sweep_fill(
            int(fill["fill_id"]),
            {
                "trade_id": trade_id,
                "classification": result.classification,
                "spent_block_index": result.spent_block_index,
                "taker_puzzle_hash": result.taker_puzzle_hash,
                "sweep_group_id": result.sweep_group_id,
                "side": fill["side"],
            },
            claim_token=claim_token,
            claim_generation=claim_generation,
        )
        try:
            from sweep_coordinator import get_coordinator

            coordinator = get_coordinator()
            if hasattr(coordinator, "process_authoritative_fill"):
                coordinator.process_authoritative_fill(int(fill["fill_id"]), result)
            else:
                coordinator.process_fill(int(fill["fill_id"]), result)
            if (
                result.spent_block_index is not None
                and hasattr(coordinator, "has_registered_fill")
                and not (coordinator.has_registered_fill(int(fill["fill_id"])))
            ):
                raise RuntimeError("SweepCoordinator rejected durable registration")
            return database.acknowledge_authoritative_sweep_registration(
                int(fill["fill_id"]),
                claim_token=claim_token,
                claim_generation=claim_generation,
            )
        except Exception as exc:
            raise _PostFillEffectUncertain(
                "sweep registration is durable but process delivery is uncertain"
            ) from exc

    return {
        "offer_filled_event": offer_filled_event,
        "boost_notification": boost_notification,
        "fill_classification": fill_classification,
        "sweep_registration": sweep_registration,
    }


def _run_post_fill_hooks(fill: dict[str, Any], *, completed_at: str) -> dict[str, str]:
    """Run post-commit hooks without allowing failures to undo proof."""

    import database

    _ = completed_at
    results: dict[str, str] = {}
    try:
        callbacks = _post_fill_hook_callbacks(fill)
    except Exception:
        try:
            results = database.record_offer_fill_hook_construction_failure(
                int(fill["fill_id"])
            )
        except BaseException:
            results = {
                name: "in_progress" for name in database._AUTHORITATIVE_FILL_HOOKS
            }
        try:
            database.log_event(
                "warning",
                "authoritative_fill_hook_construction_failed",
                f"Post-fill callbacks could not be built for fill {fill['fill_id']}",
                data={"fill_id": fill["fill_id"]},
            )
        except Exception:
            pass
        return results
    for hook_name, callback in callbacks.items():
        try:
            claim = database.claim_offer_fill_hook(int(fill["fill_id"]), hook_name)
        except Exception:
            results[hook_name] = "failed"
            try:
                database.log_event(
                    "warning",
                    "authoritative_fill_hook_claim_failed",
                    f"Post-fill hook {hook_name} could not be claimed for fill "
                    f"{fill['fill_id']}",
                    data={"fill_id": fill["fill_id"], "hook_name": hook_name},
                )
            except Exception:
                pass
            continue
        if claim["status"] != "claimed":
            results[hook_name] = claim["status"]
            continue
        claim_token = claim["claim_token"]
        claim_generation = claim["claim_generation"]
        heartbeat_stop = threading.Event()

        def maintain_claim() -> None:
            interval = max(0.01, database._AUTHORITATIVE_FILL_HOOK_LEASE_SECONDS / 3)
            while not heartbeat_stop.wait(interval):
                try:
                    held = database.heartbeat_offer_fill_hook(
                        int(fill["fill_id"]),
                        hook_name,
                        claim_token,
                        claim_generation,
                    )
                except Exception:
                    return
                if not held:
                    return

        heartbeat_thread = threading.Thread(
            target=maintain_claim,
            name=f"offer-fill-hook-{fill['fill_id']}-{hook_name}",
            daemon=True,
        )
        heartbeat_thread.start()
        effect_boundary = False
        try:
            acknowledgement = callback(
                fill,
                claim_token=claim_token,
                claim_generation=claim_generation,
            )
            if not database.validate_offer_fill_hook_sink_ack(
                int(fill["fill_id"]),
                hook_name,
                acknowledgement,
                claim_token=claim_token,
                claim_generation=claim_generation,
            ):
                raise RuntimeError(
                    "post-fill sink did not return its durable fill acknowledgement"
                )
            effect_boundary = True
        except Exception as exc:
            effect_boundary = isinstance(exc, _PostFillEffectUncertain)
            try:
                effect_boundary = (
                    database.has_offer_fill_hook_delivery_ack(
                        int(fill["fill_id"]),
                        hook_name,
                        claim_token,
                        claim_generation,
                    )
                    or effect_boundary
                )
            except Exception:
                pass
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)
        if effect_boundary:
            try:
                completed = database.complete_offer_fill_hook(
                    int(fill["fill_id"]),
                    hook_name,
                    claim_token,
                    claim_generation=claim_generation,
                )
            except Exception:
                results[hook_name] = "in_progress"
                try:
                    database.log_event(
                        "warning",
                        "authoritative_fill_hook_receipt_uncertain",
                        f"Post-fill hook {hook_name} receipt is uncertain for fill "
                        f"{fill['fill_id']}",
                        data={"fill_id": fill["fill_id"], "hook_name": hook_name},
                    )
                except Exception:
                    pass
            else:
                results[hook_name] = "completed" if completed else "already_completed"
            continue
        try:
            reset = database.fail_offer_fill_hook(
                int(fill["fill_id"]),
                hook_name,
                claim_token,
                claim_generation=claim_generation,
                error_code="CALLBACK_FAILED",
            )
        except Exception:
            reset = False
        results[hook_name] = "failed" if reset else "in_progress"
        try:
            database.log_event(
                "warning",
                "authoritative_fill_hook_failed",
                f"Post-fill hook {hook_name} failed for fill {fill['fill_id']}",
                data={"fill_id": fill["fill_id"], "hook_name": hook_name},
            )
        except Exception:
            pass
    return results


def drain_offer_fill_hook_outbox(*, limit: int = 32) -> dict[int, dict[str, str]]:
    """Drain pending or abandoned durable post-fill work without wallet reads."""

    import database

    drained: dict[int, dict[str, str]] = {}
    for fill_id in database.get_offer_fill_hook_outbox_work(limit=limit):
        fill = database.get_fill_by_id(fill_id)
        if fill is None:
            continue
        drained[fill_id] = _run_post_fill_hooks(
            fill, completed_at=str(fill["filled_at"])
        )
    return drained


def reconcile_offer(
    intent_id: str,
    *,
    evidence: Any = None,
    cancel_context: Any = None,
    wallet_facade: Any = None,
    now: Any = None,
) -> dict[str, Any]:
    """Authorize and persist one exact reconciliation result."""

    import database

    intent = database.get_offer_intent(intent_id)
    if intent is None:
        raise ValueError("intent_id does not exist")
    if evidence is None:
        try:
            collected = load_authoritative_evidence(intent, wallet_facade=wallet_facade)
        except BaseException:
            observed_at = _clock_utc()
            collected = _incomplete_loader_evidence(intent, observed_at)
        else:
            observed_at = _clock_utc()
    else:
        observed_at = _canonical_utc(datetime.now(timezone.utc) if now is None else now)
        collected = evidence
    result = classify_terminal_evidence(
        intent,
        collected,
        cancel_context=cancel_context,
        now=observed_at,
    )
    destination, registry_evidence = _registry_evidence(intent, result, observed_at)
    records = tuple(
        offer_record_from_row(row) for row in database.get_offer_intents_for_registry()
    )
    decision = authorize_transition(
        RegistrySnapshot(records),
        OfferReference(
            intent_id=intent["intent_id"],
            sage_trade_id=intent["sage_trade_id"],
            offer_text_sha256=intent["offer_text_sha256"],
        ),
        destination,
        intent["wallet_fingerprint_hash"],
        intent["network"],
        evidence=registry_evidence,
    )
    operation_id = f"reconcile:{intent['intent_id']}"
    if not decision.allowed:
        _trip_denial_latch(
            intent,
            operation_id,
            decision.code.value,
            decision.reason,
            observed_at,
        )
        return {
            **result,
            "applied": False,
            "authorization_code": decision.code.value,
        }
    durable_proof = {"classification": result, "evidence": collected}
    exact_cancel_context = _validated_cancel_context(cancel_context)
    if result["classification"] == CANCELLED_PROVEN:
        if exact_cancel_context is None:
            raise RuntimeError("proven cancellation lost its validated Task 8 context")
        durable_proof["cancel_context"] = exact_cancel_context
    try:
        durable_json, evidence_sha256 = canonical_evidence_and_digest(durable_proof)
    except Exception:
        encoding_result = _unknown("EVIDENCE_ENCODING_FAILED")
        fallback_destination, fallback_evidence = _registry_evidence(
            intent, encoding_result, observed_at
        )
        fallback_decision = authorize_transition(
            RegistrySnapshot(records),
            OfferReference(
                intent_id=intent["intent_id"],
                sage_trade_id=intent["sage_trade_id"],
                offer_text_sha256=intent["offer_text_sha256"],
            ),
            fallback_destination,
            intent["wallet_fingerprint_hash"],
            intent["network"],
            evidence=fallback_evidence,
        )
        if not fallback_decision.allowed:
            _trip_denial_latch(
                intent,
                operation_id,
                fallback_decision.code.value,
                fallback_decision.reason,
                observed_at,
            )
            return {
                **encoding_result,
                "applied": False,
                "authorization_code": fallback_decision.code.value,
            }
        minimal_proof = {
            "classification": encoding_result,
            "evidence": {"encoding_failed": True, "redacted": True},
        }
        durable_json = json.dumps(
            minimal_proof,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence_sha256 = hashlib.sha256(durable_json.encode("utf-8")).hexdigest()
        committed = database.commit_offer_reconciliation(
            intent_id=intent["intent_id"],
            operation_id=operation_id,
            classification=UNKNOWN,
            reason_code=encoding_result["reason_code"],
            wallet_identity_json={
                "wallet_fingerprint_hash": intent["wallet_fingerprint_hash"],
                "network": intent["network"],
            },
            evidence_json=durable_json,
            evidence_sha256=evidence_sha256,
            transaction_id=None,
            spend_identity=None,
            block_height=None,
            receive_coin_id=None,
            receive_amount_mojos=None,
            filled_at=None,
            fee_mojos=0,
            coin_rebindings=[],
            cancel_context_json=None,
            reconciled_at=observed_at,
        )
        return {
            **encoding_result,
            "applied": False,
            "authorization_code": fallback_decision.code.value,
            "evidence_sha256": evidence_sha256,
            "event": committed["event"],
            "idempotent": committed["idempotent"],
        }
    try:
        committed = database.commit_offer_reconciliation(
            intent_id=intent["intent_id"],
            operation_id=operation_id,
            classification=result["classification"],
            reason_code=result["reason_code"],
            wallet_identity_json={
                "wallet_fingerprint_hash": intent["wallet_fingerprint_hash"],
                "network": intent["network"],
            },
            evidence_json=durable_json,
            evidence_sha256=evidence_sha256,
            transaction_id=result.get("transaction_id"),
            spend_identity=result.get("spend_identity"),
            block_height=result.get("block_height"),
            receive_coin_id=result.get("receive_coin_id"),
            receive_amount_mojos=result.get("receive_amount_mojos"),
            filled_at=result.get("filled_at"),
            fee_mojos=result.get("fee_mojos", 0),
            coin_rebindings=result.get("coin_rebindings", []),
            cancel_context_json=(
                exact_cancel_context
                if result["classification"] == CANCELLED_PROVEN
                else None
            ),
            reconciled_at=observed_at,
        )
    except ValueError as exc:
        if result["classification"] == CANCELLED_PROVEN and "Task 8" in str(exc):
            _trip_denial_latch(
                intent,
                operation_id,
                "TASK8_BINDING_CONFLICT",
                "authoritative cancellation proof conflicts with durable Task 8 state",
                observed_at,
            )
        raise
    response = {
        **result,
        "applied": result["classification"]
        in {FILLED_PROVEN, CANCELLED_PROVEN, EXPIRED_PROVEN},
        "authorization_code": decision.code.value,
        "evidence_sha256": evidence_sha256,
        "event": committed["event"],
        "idempotent": committed["idempotent"],
    }
    if result["classification"] == FILLED_PROVEN:
        fill_id = committed.get("fill_id")
        fill = database.get_fill_by_trade_id(intent["sage_trade_id"])
        if fill_id is None or fill is None or int(fill["fill_id"]) != int(fill_id):
            raise RuntimeError(
                "authoritative fill commit lost its durable fill identity"
            )
        response["fill_id"] = int(fill_id)
        response["post_fill_hooks"] = _run_post_fill_hooks(
            fill, completed_at=observed_at
        )
    return response


__all__ = [
    "ACTIVE_PROVEN",
    "CANCELLED_PROVEN",
    "CONFLICT",
    "EXPIRED_PROVEN",
    "FILLED_PROVEN",
    "UNKNOWN",
    "canonical_evidence_and_digest",
    "classify_terminal_evidence",
    "drain_offer_fill_hook_outbox",
    "load_authoritative_evidence",
    "load_sage_offer_history",
    "reconcile_offer",
]
