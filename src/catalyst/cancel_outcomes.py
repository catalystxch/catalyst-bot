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
_SENSITIVE_KEY_PARTS = (
    "secret",
    "private",
    "password",
    "token",
    "mnemonic",
    "signature",
    "seed",
)
_EXACT_SPEND_IDENTITY = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)
_MEMPOOL_MARKERS = ("mempool_conflict", "already_including", "already in mempool")


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


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part in key_text.lower() for part in _SENSITIVE_KEY_PARTS):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return _json_default(value)


def safe_raw_response(value: Any, limit: int = 4096) -> str:
    """Return deterministic, bounded diagnostics with sensitive fields redacted.

    Oversized responses retain only their digest and byte length.  This avoids
    persisting partial JSON or an arbitrarily large signed-spend response.
    """
    limit = max(2, int(limit))
    raw = _canonical_json(value)
    safe = _canonical_json(_redact(value))
    if len(safe.encode("utf-8")) <= limit:
        return safe

    compact = {
        "byte_length": len(raw.encode("utf-8")),
        "evidence_schema": "catalyst.cancel.response-digest.v1",
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "truncated": True,
    }
    rendered = _canonical_json(compact)
    return rendered if len(rendered.encode("utf-8")) <= limit else "{}"


def _is_exact_spend_identity(value: str) -> bool:
    return bool(_EXACT_SPEND_IDENTITY.fullmatch(value.strip()))


def _has_submission_identity(transaction_id: str, spend_identity: str) -> bool:
    return bool(transaction_id.strip()) or _is_exact_spend_identity(spend_identity)


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
    error_text = str(error or "")[:1000]
    transaction_id = str(transaction_id or "").strip()
    spend_identity = str(spend_identity or "").strip()
    if normalized not in _OUTCOMES:
        normalized = CANCEL_UNKNOWN
        error_text = error_text or "invalid_cancel_outcome"
    if normalized == CANCEL_SUBMITTED_UNCONFIRMED and not _has_submission_identity(
        transaction_id, spend_identity
    ):
        normalized = CANCEL_UNKNOWN
        error_text = error_text or "submitted cancellation lacks exact identity"

    submitted = normalized == CANCEL_SUBMITTED_UNCONFIRMED
    raw_evidence = safe_raw_response(raw_response)
    result: dict[str, Any] = {
        "outcome": normalized,
        "success": normalized == CANCEL_CONFIRMED,
        "submitted": submitted,
        "reconciliation_required": submitted or normalized == CANCEL_UNKNOWN,
        "method": str(method or ""),
        "transaction_id": transaction_id,
        "spend_identity": spend_identity,
        "raw_response": raw_evidence,
        "evidence_digest": evidence_digest(raw_response),
    }
    if error_text:
        result["error"] = error_text
    return result


def _contains_mempool_marker(value: Any) -> bool:
    return any(marker in str(value or "").lower() for marker in _MEMPOOL_MARKERS)


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
        transaction_id = str(
            transaction_id or response.get("transaction_id") or response.get("tx_id") or ""
        )
        spend_identity = str(
            spend_identity or response.get("spend_identity") or ""
        )
    if confirmed:
        return cancellation_result(
            CANCEL_CONFIRMED,
            method=method,
            raw_response=response,
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )

    error_text = str(error or "")
    identity_present = _has_submission_identity(
        str(transaction_id or ""), str(spend_identity or "")
    )
    if http_status == 404:
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error="cancel response was HTTP 404",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if error is not None:
        outcome = (
            CANCEL_SUBMITTED_UNCONFIRMED
            if _contains_mempool_marker(error_text) and identity_present
            else CANCEL_UNKNOWN
        )
        return cancellation_result(
            outcome,
            method=method,
            raw_response=response,
            error=error_text or "cancel transport error",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if not isinstance(response, Mapping):
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error="malformed cancel response",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if response.get("offer") is None and "offer" in response:
        return cancellation_result(
            CANCEL_UNKNOWN,
            method=method,
            raw_response=response,
            error="cancel response lacks offer",
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )

    response_error = response.get("error")
    response_status = response.get("status")
    if _contains_mempool_marker(response_error) or _contains_mempool_marker(
        response_status
    ):
        outcome = CANCEL_SUBMITTED_UNCONFIRMED if identity_present else CANCEL_UNKNOWN
        return cancellation_result(
            outcome,
            method=method,
            raw_response=response,
            error=str(response_error or response_status or "mempool acknowledgement"),
            transaction_id=transaction_id,
            spend_identity=spend_identity,
        )
    if response.get("success") is False or str(response_status).lower() in {
        "rejected",
        "failed",
    }:
        return cancellation_result(
            CANCEL_FAILED,
            method=method,
            raw_response=response,
            error=str(response_error or response_status or "cancel rejected"),
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
        error="cancel acknowledgement lacks authoritative proof or exact identity",
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
