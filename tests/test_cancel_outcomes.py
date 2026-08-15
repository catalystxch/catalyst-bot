"""Contract tests for fail-closed cancellation result normalization."""

from __future__ import annotations

import json

import pytest

from cancel_outcomes import (
    CANCEL_CONFIRMED,
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    CANCEL_UNKNOWN,
    cancellation_result,
    normalize_cancel_response,
    safe_raw_response,
)


@pytest.mark.parametrize(
    (
        "name,response,error,http_status,confirmed,transaction_id,spend_identity,"
        "want_outcome,want_submitted,want_reconciliation"
    ),
    [
        (
            "authoritative confirmation",
            {"success": True},
            None,
            None,
            True,
            "",
            "",
            CANCEL_CONFIRMED,
            False,
            False,
        ),
        (
            "timeout after request",
            None,
            TimeoutError("response lost"),
            None,
            False,
            "",
            "",
            CANCEL_UNKNOWN,
            False,
            True,
        ),
        (
            "disconnect after request",
            None,
            ConnectionError("connection reset"),
            None,
            False,
            "",
            "",
            CANCEL_UNKNOWN,
            False,
            True,
        ),
        (
            "malformed json response",
            "{not-json",
            None,
            None,
            False,
            "",
            "",
            CANCEL_UNKNOWN,
            False,
            True,
        ),
        (
            "404 is not cancellation proof",
            {"error": "offer missing"},
            None,
            404,
            False,
            "",
            "",
            CANCEL_UNKNOWN,
            False,
            True,
        ),
        (
            "missing offer row is not cancellation proof",
            {"success": True, "offer": None},
            None,
            None,
            False,
            "",
            "",
            CANCEL_UNKNOWN,
            False,
            True,
        ),
        (
            "mempool conflict with transaction identity",
            {"error": "MEMPOOL_CONFLICT"},
            None,
            None,
            False,
            "a" * 64,
            "",
            CANCEL_SUBMITTED_UNCONFIRMED,
            True,
            True,
        ),
        (
            "already including with exact spend identity",
            {"status": "already_including"},
            None,
            None,
            False,
            "",
            "sha256:" + "a" * 64,
            CANCEL_SUBMITTED_UNCONFIRMED,
            True,
            True,
        ),
        (
            "explicit rejection",
            {"success": False, "error": "rejected before submission"},
            None,
            None,
            False,
            "",
            "",
            CANCEL_FAILED,
            False,
            False,
        ),
        (
            "accepted transaction id is submitted but unconfirmed",
            {"success": True, "transaction_id": "b" * 64},
            None,
            None,
            False,
            "",
            "",
            CANCEL_SUBMITTED_UNCONFIRMED,
            True,
            True,
        ),
        (
            "already including without an exact identity stays unknown",
            {"status": "already_including"},
            None,
            None,
            False,
            "",
            "",
            CANCEL_UNKNOWN,
            False,
            True,
        ),
    ],
    ids=lambda case: case if isinstance(case, str) else "case",
)
def test_normalizes_cancel_evidence_fail_closed(
    name,
    response,
    error,
    http_status,
    confirmed,
    transaction_id,
    spend_identity,
    want_outcome,
    want_submitted,
    want_reconciliation,
):
    """Changing any ambiguous branch to success would break this contract."""
    result = normalize_cancel_response(
        response,
        error=error,
        http_status=http_status,
        confirmed=confirmed,
        transaction_id=transaction_id,
        spend_identity=spend_identity,
        method="sage_cancel",
    )

    assert result["outcome"] == want_outcome, name
    assert result["success"] is (want_outcome == CANCEL_CONFIRMED), name
    assert result["submitted"] is want_submitted, name
    assert result["reconciliation_required"] is want_reconciliation, name


@pytest.mark.parametrize(
    ("transaction_id", "spend_identity"),
    [
        ("", ""),
        ("", "opaque-bundle-label"),
    ],
)
def test_submitted_requires_transaction_id_or_exact_spend_identity(
    transaction_id, spend_identity
):
    """A generic acknowledgement must not be promoted to a reconcilable submit."""
    result = cancellation_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        method="submit_transaction",
        raw_response={"success": True},
        transaction_id=transaction_id,
        spend_identity=spend_identity,
    )

    assert result["outcome"] == CANCEL_UNKNOWN
    assert result["success"] is False
    assert result["submitted"] is False
    assert result["reconciliation_required"] is True


@pytest.mark.parametrize(
    ("response", "want_outcome"),
    [
        ({"error_code": "MEMPOOL_CONFLICT"}, CANCEL_SUBMITTED_UNCONFIRMED),
        (
            {"status": "ALREADY_INCLUDING_TRANSACTION"},
            CANCEL_SUBMITTED_UNCONFIRMED,
        ),
        (
            {"error": "rejected: mempool_conflict was not observed"},
            CANCEL_UNKNOWN,
        ),
        ({"status": "not already_including"}, CANCEL_UNKNOWN),
        ({"code": "MEMPOOL_CONFLICT_RETRY"}, CANCEL_UNKNOWN),
        ({"success": False, "error_code": "MEMPOOL_CONFLICT"}, CANCEL_FAILED),
        ({"status": "REJECTED", "code": "MEMPOOL_CONFLICT"}, CANCEL_FAILED),
    ],
)
def test_only_exact_positive_mempool_codes_can_mark_submission(
    response, want_outcome
):
    """Negated or rejected prose must never become a submitted cancellation."""
    result = normalize_cancel_response(
        response,
        method="submit_transaction",
        transaction_id="a" * 64,
    )

    assert result["outcome"] == want_outcome
    assert result["success"] is False
    assert result["submitted"] is (want_outcome == CANCEL_SUBMITTED_UNCONFIRMED)


@pytest.mark.parametrize(
    ("transaction_id", "valid"),
    [
        ("a" * 64, True),
        ("0x" + "b" * 64, True),
        ("123e4567-e89b-12d3-a456-426614174000", True),
        ("cancel-tx-456", False),
        (" " + "a" * 64, False),
        ("a" * 65, False),
        (True, False),
        (7, False),
        (["a" * 64], False),
        ({"transaction_id": "a" * 64}, False),
    ],
)
def test_submitted_accepts_only_bounded_transaction_id_grammars(
    transaction_id, valid
):
    """Coercing arbitrary values to strings would fabricate reconciliation IDs."""
    result = cancellation_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        method="submit_transaction",
        transaction_id=transaction_id,
    )

    assert result["outcome"] == (
        CANCEL_SUBMITTED_UNCONFIRMED if valid else CANCEL_UNKNOWN
    )
    assert result["submitted"] is valid
    assert result["transaction_id"] == (transaction_id.lower() if valid else "")


def test_safe_evidence_is_allowlisted_and_deterministically_digested():
    """Persisting a response must project diagnostics, never raw credentials."""
    response = {
        "Authorization": "Bearer do-not-persist",
        "Cookie": "session=also-do-not-persist",
        "api_key": "do-not-persist",
        "credential": "do-not-persist",
        "passphrase": "do-not-persist",
        "coin_spends": ["x" * 5_000],
        "nested": {"private_key": "also-do-not-persist", "token": "nested"},
        "error": "Authorization: Bearer free-text-secret",
        "success": True,
        "transaction_id": "c" * 64,
    }

    first = safe_raw_response(response, limit=256)
    second = safe_raw_response(
        {
            "transaction_id": "c" * 64,
            "success": True,
            "error": "Authorization: Bearer free-text-secret",
            "nested": {"private_key": "also-do-not-persist", "token": "nested"},
            "coin_spends": ["x" * 5_000],
            "passphrase": "do-not-persist",
            "credential": "do-not-persist",
            "api_key": "do-not-persist",
            "Cookie": "session=also-do-not-persist",
            "Authorization": "Bearer do-not-persist",
        },
        limit=256,
    )
    evidence = json.loads(first)

    assert first == second
    assert len(first.encode("utf-8")) <= 256
    assert "do-not-persist" not in first
    assert "free-text-secret" not in first
    assert "also-do-not-persist" not in first
    assert "x" * 100 not in first
    assert evidence["transaction_id"] == "c" * 64
    assert evidence["success"] is True
    assert evidence["truncated"] is True


def test_cancellation_result_keeps_digest_with_bounded_raw_evidence():
    """A constructor result preserves safe diagnostics without changing outcome."""
    result = cancellation_result(
        CANCEL_FAILED,
        method="submit_transaction",
        raw_response={"error": "rejected", "signature": "secret"},
        error="Authorization: Bearer secret",
    )

    assert result["outcome"] == CANCEL_FAILED
    assert result["success"] is False
    assert result["submitted"] is False
    assert result["reconciliation_required"] is False
    assert result["evidence_digest"]
    assert "secret" not in result["raw_response"]
    assert "secret" not in result["error"]


def test_cancellation_result_does_not_surface_unbounded_method_text():
    """Caller-provided labels cannot become a side channel for header values."""
    result = cancellation_result(
        CANCEL_FAILED,
        method="Authorization: Bearer " + "method-secret" * 100,
        error="failed",
    )

    assert result["method"] == "CANCEL_METHOD_UNCLASSIFIED"
    assert "method-secret" not in result["method"]


@pytest.mark.parametrize("limit", [2, 32])
def test_safe_evidence_respects_even_tiny_byte_limits(limit):
    """A durable evidence field must never overflow its declared byte limit."""
    rendered = safe_raw_response({"Authorization": "secret"}, limit=limit)

    assert len(rendered.encode("utf-8")) <= limit
