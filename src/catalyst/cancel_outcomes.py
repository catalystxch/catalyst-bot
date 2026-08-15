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
_UUID_TRANSACTION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
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
_SAFE_DIAGNOSTIC_CODES = _POSITIVE_SUBMISSION_CODES | _REJECTION_CODES


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
    if _HEX_TRANSACTION_ID.fullmatch(value) or _UUID_TRANSACTION_ID.fullmatch(value):
        return value.lower()
    return ""


def _validated_spend_identity(value: Any) -> str:
    if not isinstance(value, str) or not _EXACT_SPEND_IDENTITY.fullmatch(value):
        return ""
    return value.lower()


def _safe_error_code(value: Any) -> str:
    code = _normalized_code(value)
    return code if code in _SAFE_DIAGNOSTIC_CODES else "CANCEL_ERROR_UNCLASSIFIED"


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


def _evidence_projection(value: Any) -> dict[str, Any]:
    """Keep only safe, bounded response facts; never retain raw payload text."""
    raw = _canonical_json(value)
    projection: dict[str, Any] = {
        "byte_length": len(raw.encode("utf-8")),
        "schema": "catalyst.cancel.response.v2",
        "kind": "mapping" if isinstance(value, Mapping) else type(value).__name__,
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "truncated": True,
    }
    if not isinstance(value, Mapping):
        return projection

    projection["key_count"] = len(value)
    if isinstance(value.get("success"), bool):
        projection["success"] = value["success"]
    safe_codes = sorted(_response_codes(value) & _SAFE_DIAGNOSTIC_CODES)
    if safe_codes:
        projection["codes"] = safe_codes
    transaction_id = _validated_transaction_id(
        value.get("transaction_id") or value.get("tx_id")
    )
    if transaction_id:
        projection["transaction_id"] = transaction_id
    spend_identity = _validated_spend_identity(value.get("spend_identity"))
    if spend_identity:
        projection["spend_identity"] = spend_identity
    if isinstance(value.get("coin_spends"), (list, tuple)):
        projection["coin_spends_count"] = len(value["coin_spends"])
    return projection


def safe_raw_response(value: Any, limit: int = 4096) -> str:
    """Return a bounded allowlisted evidence projection, never raw response text."""
    limit = max(2, int(limit))
    projection = _evidence_projection(value)
    for removable in ("coin_spends_count", "key_count", "codes", "kind"):
        rendered = _canonical_json(projection)
        if len(rendered.encode("utf-8")) <= limit:
            return rendered
        projection.pop(removable, None)

    rendered = _canonical_json(projection)
    if len(rendered.encode("utf-8")) <= limit:
        return rendered
    fallback = _canonical_json(
        {
            "schema": "catalyst.cancel.response.v2",
            "sha256": evidence_digest(value),
            "truncated": True,
        }
    )
    return fallback if len(fallback.encode("utf-8")) <= limit else "{}"


def _has_submission_identity(transaction_id: str, spend_identity: str) -> bool:
    return bool(transaction_id) or bool(spend_identity)


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
    raw_evidence = safe_raw_response(raw_response)
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

    error_code = _normalized_code(error)
    identity_present = _has_submission_identity(transaction_id, spend_identity)
    if http_status == 404:
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error="CANCEL_ERROR_UNCLASSIFIED",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if error is not None:
        if error_code in _REJECTION_CODES:
            outcome = CANCEL_FAILED
        elif error_code in _POSITIVE_SUBMISSION_CODES and identity_present:
            outcome = CANCEL_SUBMITTED_UNCONFIRMED
        else:
            outcome = CANCEL_UNKNOWN
        return cancellation_result(
            outcome,
            method=method,
            raw_response=response,
            error=error_code or "CANCEL_ERROR_UNCLASSIFIED",
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

    response_codes = _response_codes(response)
    if response.get("success") is False or response_codes & _REJECTION_CODES:
        return cancellation_result(
            CANCEL_FAILED,
            method=method,
            raw_response=response,
            error=next(
                iter(sorted(response_codes & _REJECTION_CODES)),
                "CANCEL_ERROR_UNCLASSIFIED",
            ),
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if response_codes & _POSITIVE_SUBMISSION_CODES:
        outcome = CANCEL_SUBMITTED_UNCONFIRMED if identity_present else CANCEL_UNKNOWN
        return cancellation_result(
            outcome,
            method=method,
            raw_response=response,
            error=next(iter(sorted(response_codes & _POSITIVE_SUBMISSION_CODES))),
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
    "cancellation_result",
    "evidence_digest",
    "normalize_cancel_response",
    "normalize_cancel_result",
    "safe_raw_response",
]
