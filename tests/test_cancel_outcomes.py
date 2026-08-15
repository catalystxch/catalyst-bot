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
            "cancel-tx-123",
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
            {"success": True, "transaction_id": "cancel-tx-456"},
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


def test_safe_raw_evidence_is_bounded_redacted_and_deterministically_digested():
    """Persisting a large signed response must not persist its secrets verbatim."""
    response = {
        "api_token": "do-not-persist",
        "coin_spends": ["x" * 5_000],
        "nested": {"private_key": "also-do-not-persist"},
    }

    first = safe_raw_response(response, limit=256)
    second = safe_raw_response(
        {
            "nested": {"private_key": "also-do-not-persist"},
            "coin_spends": ["x" * 5_000],
            "api_token": "do-not-persist",
        },
        limit=256,
    )
    evidence = json.loads(first)

    assert first == second
    assert len(first.encode("utf-8")) <= 256
    assert "do-not-persist" not in first
    assert "x" * 100 not in first
    assert evidence["sha256"] == "2775aeb86df2c6084f48bf02428c3598cbeb297669d40d1dfa51a36cae8cbecf"
    assert evidence["truncated"] is True


def test_cancellation_result_keeps_digest_with_bounded_raw_evidence():
    """A constructor result preserves safe diagnostics without changing outcome."""
    result = cancellation_result(
        CANCEL_FAILED,
        method="submit_transaction",
        raw_response={"error": "rejected", "signature": "secret"},
        error="rejected",
    )

    assert result["outcome"] == CANCEL_FAILED
    assert result["success"] is False
    assert result["submitted"] is False
    assert result["reconciliation_required"] is False
    assert result["evidence_digest"]
    assert "secret" not in result["raw_response"]
