"""Contract tests for fail-closed cancellation result normalization."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from cancel_outcomes import (
    CANCEL_CONFIRMED,
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    CANCEL_UNKNOWN,
    COMPACT_EVIDENCE_CODE_ALIASES,
    cancellation_result,
    decode_evidence_code,
    normalize_cancel_response,
    safe_raw_response,
)


class _UnhashableStr(str):
    __hash__ = None


class _HostileHashStr(str):
    def __hash__(self):
        raise AssertionError("decoder invoked attacker-controlled __hash__")


class _HostileEqualHashStr(str):
    def __hash__(self):
        return str.__hash__(self)

    def __eq__(self, other):
        raise AssertionError("decoder invoked attacker-controlled __eq__")


class _HostileStringifiable:
    def __str__(self):
        raise AssertionError("decoder invoked attacker-controlled __str__")


class _HostileMapping(Mapping):
    def __getitem__(self, key):
        raise AssertionError("decoder read an attacker-controlled mapping")

    def __iter__(self):
        raise AssertionError("decoder iterated an attacker-controlled mapping")

    def __len__(self):
        raise AssertionError("decoder measured an attacker-controlled mapping")


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
    ("response", "error", "want_outcome"),
    [
        (
            {"success": False, "error_code": "MEMPOOL_CONFLICT"},
            "MEMPOOL_CONFLICT",
            CANCEL_FAILED,
        ),
        (
            {"status": "REJECTED", "code": "MEMPOOL_CONFLICT"},
            "MEMPOOL_CONFLICT",
            CANCEL_FAILED,
        ),
        (
            {"status": "NOT_ALREADY_INCLUDING", "error_code": "MEMPOOL_CONFLICT"},
            None,
            CANCEL_UNKNOWN,
        ),
        (
            {"code": "MEMPOOL_CONFLICT"},
            "NOT_MEMPOOL_CONFLICT",
            CANCEL_UNKNOWN,
        ),
        (
            {"code": "MEMPOOL_CONFLICT"},
            "rejected: mempool_conflict was not observed",
            CANCEL_UNKNOWN,
        ),
    ],
)
def test_full_evidence_scan_blocks_positive_submission_on_rejection_or_negation(
    response, error, want_outcome
):
    """Any rejection or negation anywhere wins before positive codes are read."""
    result = normalize_cancel_response(
        response,
        error=error,
        method="submit_transaction",
        transaction_id="a" * 64,
    )

    assert result["outcome"] == want_outcome
    assert result["submitted"] is False


@pytest.mark.parametrize(
    "positive_code",
    [
        "MEMPOOL_CONFLICT",
        "ALREADY_INCLUDING",
        "ALREADY_INCLUDING_TRANSACTION",
    ],
)
def test_every_not_positive_code_blocks_submitted_classification(positive_code):
    """All positive codes have a systematic NOT_ fail-closed counterpart."""
    result = normalize_cancel_response(
        {"code": positive_code, "status": f"NOT_{positive_code}"},
        method="submit_transaction",
        transaction_id="a" * 64,
    )

    assert result["outcome"] == CANCEL_UNKNOWN
    assert result["submitted"] is False


@pytest.mark.parametrize(
    ("message", "want_outcome"),
    [
        ("cancel rejected", CANCEL_FAILED),
        ("transaction rejected", CANCEL_FAILED),
        ("cancellation was not rejected", CANCEL_UNKNOWN),
        ("rejection not observed", CANCEL_UNKNOWN),
        ('history: "cancel rejected" yesterday', CANCEL_UNKNOWN),
        ("remote detail contains cancel rejected", CANCEL_UNKNOWN),
    ],
)
def test_rejection_prose_requires_an_exact_unnegated_phrase(message, want_outcome):
    """Historical or negated text cannot manufacture a terminal failure."""
    result = normalize_cancel_response(
        {"error": message}, method="submit_transaction", transaction_id="a" * 64
    )

    assert result["outcome"] == want_outcome


@pytest.mark.parametrize(
    ("transaction_id", "valid"),
    [
        ("a" * 64, True),
        ("0x" + "b" * 64, True),
        ("123e4567-e89b-12d3-a456-426614174000", False),
        ("ffffffff-ffff-ffff-ffff-ffffffffffff", False),
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
    assert evidence["tx"] == "c" * 64
    assert evidence["success"] is True
    assert evidence["t"] is True


@pytest.mark.parametrize("limit", [192, 256])
def test_evidence_priority_preserves_digest_transaction_id_and_positive_code(limit):
    """Useful reconciliation identity must survive before generic metadata."""
    rendered = safe_raw_response(
        {
            "Authorization": "Bearer secret",
            "coin_spends": ["x" * 5_000],
            "error_code": "MEMPOOL_CONFLICT",
            "key_count_noise": [1, 2, 3],
            "success": True,
            "transaction_id": "d" * 64,
        },
        limit=limit,
    )
    evidence = json.loads(rendered)

    assert len(rendered.encode("utf-8")) <= limit
    assert evidence["d"]
    assert evidence["tx"] == "d" * 64
    assert decode_evidence_code(evidence["code"]) == "MEMPOOL_CONFLICT"


@pytest.mark.parametrize("limit", [192, 256])
def test_compact_evidence_keeps_longest_decision_code_with_transaction_id(limit):
    """The longest canonical reason still fits alongside digest and tx identity."""
    response = {
        "Authorization": "Bearer secret",
        "code": "ALREADY_INCLUDING_TRANSACTION",
        "coin_spends": ["x" * 5_000],
        "transaction_id": "e" * 64,
    }
    rendered = safe_raw_response(
        response,
        limit=limit,
        decision_code="ALREADY_INCLUDING_TRANSACTION",
    )
    evidence = json.loads(rendered)

    assert len(rendered.encode("utf-8")) <= limit
    assert decode_evidence_code(evidence["code"]) == "ALREADY_INCLUDING_TRANSACTION"
    assert evidence["tx"] == "e" * 64
    assert evidence["d"]


@pytest.mark.parametrize(
    ("response", "want_outcome", "want_reason"),
    [
        (
            {"code": "MEMPOOL_CONFLICT", "status": "REJECTED"},
            CANCEL_FAILED,
            "REJECTED",
        ),
        (
            {
                "code": "MEMPOOL_CONFLICT",
                "status": "NOT_ALREADY_INCLUDING_TRANSACTION",
            },
            CANCEL_UNKNOWN,
            "NOT_ALREADY_INCLUDING_TRANSACTION",
        ),
    ],
)
def test_evidence_code_is_derived_from_final_decision_not_raw_positive_signal(
    response, want_outcome, want_reason
):
    """A losing raw positive code must not survive as cancellation evidence."""
    result = normalize_cancel_response(
        {**response, "transaction_id": "f" * 64}, method="submit_transaction"
    )
    evidence = json.loads(result["raw_response"])

    assert result["outcome"] == want_outcome
    assert decode_evidence_code(evidence["code"]) == want_reason


@pytest.mark.parametrize(
    "positive_code",
    [
        "MEMPOOL_CONFLICT",
        "ALREADY_INCLUDING",
        "ALREADY_INCLUDING_TRANSACTION",
    ],
)
@pytest.mark.parametrize(
    "signal_location",
    ["error_code", "code", "status", "error", "adapter_error"],
)
def test_positive_signal_without_valid_identity_uses_unknown_reason_everywhere(
    positive_code, signal_location
):
    """A losing positive signal must not remain authoritative after downgrade."""
    response = {}
    adapter_error = None
    if signal_location == "adapter_error":
        adapter_error = positive_code
    else:
        response[signal_location] = positive_code

    result = normalize_cancel_response(
        response,
        error=adapter_error,
        method="submit_transaction",
    )
    evidence = json.loads(result["raw_response"])

    assert result["outcome"] == CANCEL_UNKNOWN
    assert result["error"] == CANCEL_UNKNOWN
    assert decode_evidence_code(evidence["code"]) == CANCEL_UNKNOWN
    for limit in (192, 256):
        bounded = safe_raw_response(
            response,
            limit=limit,
            decision_code=result["error"],
        )
        bounded_evidence = json.loads(bounded)
        assert len(bounded.encode("utf-8")) <= limit
        assert decode_evidence_code(bounded_evidence["code"]) == CANCEL_UNKNOWN
        inferred = safe_raw_response(response, limit=limit)
        inferred_evidence = json.loads(inferred)
        assert decode_evidence_code(inferred_evidence["code"]) == CANCEL_UNKNOWN


@pytest.mark.parametrize(
    "invalid_alias",
    [
        [],
        {},
        0,
        1.5,
        True,
        False,
        None,
        "",
        "UNKNOWN",
        "MC ",
        "mc",
    ],
)
def test_evidence_decoder_is_total_and_fail_closed_for_invalid_aliases(
    invalid_alias,
):
    """Malformed JSON-valid aliases must return empty instead of raising."""
    assert decode_evidence_code(invalid_alias) == ""


@pytest.mark.parametrize(
    "alias",
    [
        _UnhashableStr("MC"),
        _HostileHashStr("MC"),
        _HostileEqualHashStr("MC"),
    ],
    ids=["unhashable", "hostile-hash", "hostile-equality"],
)
def test_evidence_decoder_rejects_str_subclasses_without_invoking_them(alias):
    """Only exact built-in strings may reach the compact-code mapping."""
    assert decode_evidence_code(alias) == ""


@pytest.mark.parametrize(
    "alias",
    [
        _HostileStringifiable(),
        _HostileMapping(),
        [],
        {},
        None,
        0,
        1,
        1.5,
        True,
        False,
    ],
    ids=[
        "hostile-str",
        "hostile-mapping",
        "list",
        "dict",
        "none",
        "zero",
        "integer",
        "float",
        "true",
        "false",
    ],
)
def test_evidence_decoder_rejects_non_strings_without_coercion(alias):
    """Rejected types must not be coerced, hashed, compared, or traversed."""
    assert decode_evidence_code(alias) == ""


@pytest.mark.parametrize(
    ("alias", "want"),
    [
        ("MC", "MEMPOOL_CONFLICT"),
        ("CU", CANCEL_UNKNOWN),
        ("", ""),
        ("UNKNOWN", ""),
        ("MC ", ""),
        ("mc", ""),
    ],
)
def test_evidence_decoder_accepts_only_exact_plain_alias_strings(alias, want):
    """Plain documented aliases decode while malformed strings fail closed."""
    assert decode_evidence_code(alias) == want


def test_compact_evidence_schema_is_immutable_unique_and_round_trips():
    """Runtime mutation or duplicate aliases must not desynchronise v4 codecs."""
    original_alias = COMPACT_EVIDENCE_CODE_ALIASES["MEMPOOL_CONFLICT"]
    try:
        with pytest.raises(TypeError):
            COMPACT_EVIDENCE_CODE_ALIASES["MEMPOOL_CONFLICT"] = "RJ"
    finally:
        if COMPACT_EVIDENCE_CODE_ALIASES["MEMPOOL_CONFLICT"] != original_alias:
            COMPACT_EVIDENCE_CODE_ALIASES["MEMPOOL_CONFLICT"] = original_alias

    aliases = tuple(COMPACT_EVIDENCE_CODE_ALIASES.values())
    assert len(aliases) == len(set(aliases))
    for code, alias in COMPACT_EVIDENCE_CODE_ALIASES.items():
        evidence = json.loads(
            safe_raw_response({}, limit=192, decision_code=code)
        )
        assert evidence["v"] == 4
        assert evidence["code"] == alias
        assert decode_evidence_code(alias) == code


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
