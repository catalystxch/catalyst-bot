"""Typed, fail-closed normalization for cancellation evidence.

This module deliberately has no wallet or database dependencies.  An adapter
can report what it observed, but only a caller with authoritative proof may
mark a cancellation as confirmed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


CANCEL_CONFIRMED = "CANCEL_CONFIRMED"
CANCEL_SUBMITTED_UNCONFIRMED = "CANCEL_SUBMITTED_UNCONFIRMED"
CANCEL_FAILED = "CANCEL_FAILED"
CANCEL_UNKNOWN = "CANCEL_UNKNOWN"

_OUTCOMES = frozenset(
    {
        CANCEL_CONFIRMED,
        CANCEL_SUBMITTED_UNCONFIRMED,
        CANCEL_FAILED,
        CANCEL_UNKNOWN,
    }
)
_EXACT_SPEND_IDENTITY = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)
_HEX_TRANSACTION_ID = re.compile(r"^(?:0x)?[0-9a-f]{64}$", re.IGNORECASE)
_STABLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_METHOD_TAG = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_POSITIVE_SUBMISSION_CODES = frozenset(
    {
        "MEMPOOL_CONFLICT",
        "ALREADY_INCLUDING",
        "ALREADY_INCLUDING_TRANSACTION",
    }
)
_REJECTION_CODES = frozenset({"REJECTED", "FAILED", "CANCEL_REJECTED"})
_NEGATED_SUBMISSION_CODES = frozenset(
    f"NOT_{code}" for code in _POSITIVE_SUBMISSION_CODES
)
_SAFE_DIAGNOSTIC_CODES = (
    _POSITIVE_SUBMISSION_CODES | _REJECTION_CODES | _NEGATED_SUBMISSION_CODES
)
_EXACT_REJECTION_PHRASES = frozenset(
    {"rejected", "cancel rejected", "transaction rejected"}
)
_NEGATED_SUBMISSION_TEXT = re.compile(
    r"\b(?:not|no)[ _-]*(?:mempool_conflict|already_including)\b",
    re.IGNORECASE,
)
COMPACT_EVIDENCE_CODE_ALIASES = {
    CANCEL_CONFIRMED: "CC",
    CANCEL_SUBMITTED_UNCONFIRMED: "CS",
    CANCEL_FAILED: "CF",
    CANCEL_UNKNOWN: "CU",
    "MEMPOOL_CONFLICT": "MC",
    "ALREADY_INCLUDING": "AI",
    "ALREADY_INCLUDING_TRANSACTION": "AIT",
    "REJECTED": "RJ",
    "FAILED": "FL",
    "CANCEL_REJECTED": "CR",
    "NOT_MEMPOOL_CONFLICT": "NMC",
    "NOT_ALREADY_INCLUDING": "NAI",
    "NOT_ALREADY_INCLUDING_TRANSACTION": "NAIT",
}
_COMPACT_EVIDENCE_CODE_DECODER = {
    alias: code for code, alias in COMPACT_EVIDENCE_CODE_ALIASES.items()
}


def _json_default(value: Any) -> dict[str, str]:
    """Avoid repr() because it can accidentally contain credential material."""
    return {"non_json_type": type(value).__name__}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def evidence_digest(value: Any) -> str:
    """Return a deterministic digest without retaining the original response."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_code(value: Any) -> str:
    """Accept only an exact stable code, never an arbitrary message substring."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip().upper()
    if candidate != value.upper() or not _STABLE_CODE.fullmatch(candidate):
        return ""
    return candidate


def _validated_transaction_id(value: Any) -> str:
    """Return a canonical Sage/Chia transaction identifier, or an empty string."""
    if not isinstance(value, str):
        return ""
    if _HEX_TRANSACTION_ID.fullmatch(value):
        return value.lower()
    return ""


def _validated_spend_identity(value: Any) -> str:
    if not isinstance(value, str) or not _EXACT_SPEND_IDENTITY.fullmatch(value):
        return ""
    return value.lower()


def _safe_error_code(value: Any) -> str:
    code = _normalized_code(value)
    return code if code in _SAFE_DIAGNOSTIC_CODES else "CANCEL_ERROR_UNCLASSIFIED"


def decode_evidence_code(alias: Any) -> str:
    """Decode the documented v4 compact evidence reason, or return empty."""
    return _COMPACT_EVIDENCE_CODE_DECODER.get(alias, "")


def _safe_method(value: Any) -> str:
    if isinstance(value, str) and _METHOD_TAG.fullmatch(value):
        return value
    return "CANCEL_METHOD_UNCLASSIFIED"


def _response_codes(response: Mapping[str, Any]) -> set[str]:
    return {
        code
        for field in ("error_code", "code", "status", "error")
        if (code := _normalized_code(response.get(field)))
    }


def _evidence_reason_from_raw(value: Any) -> str:
    if not isinstance(value, Mapping):
        return CANCEL_UNKNOWN
    codes = _response_codes(value)
    if value.get("success") is False or codes & _REJECTION_CODES:
        return sorted(codes & _REJECTION_CODES)[0] if codes & _REJECTION_CODES else CANCEL_FAILED
    if codes & _NEGATED_SUBMISSION_CODES:
        return sorted(codes & _NEGATED_SUBMISSION_CODES)[0]
    if codes & _POSITIVE_SUBMISSION_CODES:
        return sorted(codes & _POSITIVE_SUBMISSION_CODES)[0]
    return CANCEL_UNKNOWN


def _evidence_reason(value: Any, decision_code: Any) -> str:
    code = _normalized_code(decision_code)
    if code in COMPACT_EVIDENCE_CODE_ALIASES:
        return code
    return _evidence_reason_from_raw(value)


def _evidence_projection(
    value: Any, decision_code: Any = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return compact-core and optional safe facts without retaining raw text."""
    raw = _canonical_json(value)
    core: dict[str, Any] = {
        "d": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "t": True,
        "v": 4,
    }
    optional: dict[str, Any] = {
        "k": "mapping" if isinstance(value, Mapping) else type(value).__name__,
        "n": len(raw.encode("utf-8")),
    }
    reason = _evidence_reason(value, decision_code)
    core["code"] = COMPACT_EVIDENCE_CODE_ALIASES[reason]
    if isinstance(value, Mapping):
        optional["keys"] = len(value)
        if isinstance(value.get("success"), bool):
            optional["success"] = value["success"]
        transaction_id = _validated_transaction_id(
            value.get("transaction_id") or value.get("tx_id")
        )
        if transaction_id:
            core["tx"] = transaction_id
        spend_identity = _validated_spend_identity(value.get("spend_identity"))
        if spend_identity:
            core["spend"] = spend_identity
        if isinstance(value.get("coin_spends"), (list, tuple)):
            optional["spends"] = len(value["coin_spends"])
    return core, optional


def safe_raw_response(value: Any, limit: int = 4096, decision_code: Any = "") -> str:
    """Return a bounded allowlisted evidence projection, never raw response text."""
    limit = max(2, int(limit))
    projection, optional = _evidence_projection(value, decision_code)
    rendered = _canonical_json(projection)
    if len(rendered.encode("utf-8")) <= limit:
        for key in ("success", "n", "spends", "keys", "k"):
            if key not in optional:
                continue
            candidate = {**projection, key: optional[key]}
            candidate_rendered = _canonical_json(candidate)
            if len(candidate_rendered.encode("utf-8")) <= limit:
                projection = candidate
        return _canonical_json(projection)
    fallback = _canonical_json({"d": evidence_digest(value), "v": 4})
    return fallback if len(fallback.encode("utf-8")) <= limit else "{}"


def _has_submission_identity(transaction_id: str, spend_identity: str) -> bool:
    return bool(transaction_id) or bool(spend_identity)


def _evidence_values(
    response: Any, error: BaseException | str | None
) -> tuple[Any, ...]:
    values: list[Any] = [error]
    if isinstance(response, Mapping):
        values.extend(
            response.get(field) for field in ("error_code", "code", "status", "error")
        )
    return tuple(values)


def _has_explicit_rejection(response: Any, values: tuple[Any, ...]) -> bool:
    if isinstance(response, Mapping) and response.get("success") is False:
        return True
    return any(
        _normalized_code(value) in _REJECTION_CODES
        or (
            isinstance(value, str)
            and " ".join(value.casefold().split()) in _EXACT_REJECTION_PHRASES
        )
        for value in values
    )


def _has_negated_submission_marker(values: tuple[Any, ...]) -> bool:
    return any(
        _normalized_code(value) in _NEGATED_SUBMISSION_CODES
        or (isinstance(value, str) and bool(_NEGATED_SUBMISSION_TEXT.search(value)))
        for value in values
    )


def _has_ambiguous_evidence_text(values: tuple[Any, ...]) -> bool:
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        if _normalized_code(value):
            continue
        normalized_phrase = " ".join(value.casefold().split())
        if normalized_phrase in _EXACT_REJECTION_PHRASES:
            continue
        if _NEGATED_SUBMISSION_TEXT.search(value):
            continue
        return True
    return False


def cancellation_result(
    outcome: str,
    *,
    method: str,
    raw_response: Any = None,
    error: str = "",
    transaction_id: str = "",
    spend_identity: str = "",
) -> dict[str, Any]:
    """Build one canonical cancellation outcome without promoting an ACK.

    ``CANCEL_SUBMITTED_UNCONFIRMED`` is reserved for an acknowledgement that
    has an identifier suitable for later reconciliation.
    """
    normalized = str(outcome or "").strip().upper()
    error_text = _safe_error_code(error) if error else ""
    transaction_id = _validated_transaction_id(transaction_id)
    spend_identity = _validated_spend_identity(spend_identity)
    if normalized not in _OUTCOMES:
        normalized = CANCEL_UNKNOWN
        error_text = error_text or "CANCEL_ERROR_UNCLASSIFIED"
    if normalized == CANCEL_SUBMITTED_UNCONFIRMED and not _has_submission_identity(
        transaction_id, spend_identity
    ):
        normalized = CANCEL_UNKNOWN
        error_text = error_text or "CANCEL_ERROR_UNCLASSIFIED"

    submitted = normalized == CANCEL_SUBMITTED_UNCONFIRMED
    evidence_reason = (
        error_text
        if error_text in COMPACT_EVIDENCE_CODE_ALIASES
        else normalized
    )
    raw_evidence = safe_raw_response(raw_response, decision_code=evidence_reason)
    result: dict[str, Any] = {
        "outcome": normalized,
        "success": normalized == CANCEL_CONFIRMED,
        "submitted": submitted,
        "reconciliation_required": submitted or normalized == CANCEL_UNKNOWN,
        "method": _safe_method(method),
        "transaction_id": transaction_id,
        "spend_identity": spend_identity,
        "raw_response": raw_evidence,
        "evidence_digest": evidence_digest(raw_response),
    }
    if error_text:
        result["error"] = error_text
    return result


def normalize_cancel_response(
    response: Any,
    *,
    method: str,
    error: BaseException | str | None = None,
    http_status: int | None = None,
    confirmed: bool = False,
    transaction_id: str = "",
    spend_identity: str = "",
) -> dict[str, Any]:
    """Classify adapter evidence while failing closed on every ambiguity.

    ``confirmed`` must come from the authoritative reconciliation path; fields
    in an RPC payload such as ``success`` or ``confirmed`` are never proof.
    """
    if isinstance(response, Mapping):
        transaction_id = transaction_id or response.get("transaction_id") or response.get(
            "tx_id"
        )
        spend_identity = spend_identity or response.get("spend_identity")
    transaction_id = _validated_transaction_id(transaction_id)
    spend_identity = _validated_spend_identity(spend_identity)
    if confirmed:
        return cancellation_result(
            CANCEL_CONFIRMED,
            method=method,
            raw_response=response,
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )

    identity_present = _has_submission_identity(transaction_id, spend_identity)
    values = _evidence_values(response, error)
    all_codes = {_normalized_code(value) for value in values} - {""}
    if _has_explicit_rejection(response, values):
        rejection_codes = sorted(all_codes & _REJECTION_CODES)
        return cancellation_result(
            CANCEL_FAILED,
            method=method,
            raw_response=response,
            error=rejection_codes[0] if rejection_codes else "REJECTED",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if _has_negated_submission_marker(values):
        negated_codes = sorted(all_codes & _NEGATED_SUBMISSION_CODES)
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error=negated_codes[0] if negated_codes else "CANCEL_ERROR_UNCLASSIFIED",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if _has_ambiguous_evidence_text(values):
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error="CANCEL_ERROR_UNCLASSIFIED",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if http_status == 404:
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error="CANCEL_ERROR_UNCLASSIFIED",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if not isinstance(response, Mapping):
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error="CANCEL_ERROR_UNCLASSIFIED",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if response.get("offer") is None and "offer" in response:
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error="CANCEL_ERROR_UNCLASSIFIED",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )

    positive_codes = sorted(all_codes & _POSITIVE_SUBMISSION_CODES)
    if positive_codes:
        outcome = CANCEL_SUBMITTED_UNCONFIRMED if identity_present else CANCEL_UNKNOWN
        return cancellation_result(
            outcome,
            method=method,
            raw_response=response,
            error=positive_codes[0],
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if response.get("success") is True and identity_present:
        return cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method=method,
            raw_response=response,
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    return cancellation_result(
        CANCEL_UNKNOWN,
        method=method,
        raw_response=response,
        error="CANCEL_ERROR_UNCLASSIFIED",
        transaction_id=transaction_id,
        spend_identity=spend_identity,
    )


normalize_cancel_result = normalize_cancel_response


__all__ = [
    "CANCEL_CONFIRMED",
    "CANCEL_FAILED",
    "CANCEL_SUBMITTED_UNCONFIRMED",
    "CANCEL_UNKNOWN",
    "COMPACT_EVIDENCE_CODE_ALIASES",
    "cancellation_result",
    "decode_evidence_code",
    "evidence_digest",
    "normalize_cancel_response",
    "normalize_cancel_result",
    "safe_raw_response",
]
