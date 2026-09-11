from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fill_classifier import (
    FillConfidence,
    assess_fill_confidence,
    build_fill_confidence_record,
)


TX_ID = "ab" * 32
SPEND_ID = "cd" * 32
INPUT_ID = "12" * 32
ASSET_ID = "34" * 32
NOW = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def _exact_external_fill_evidence():
    exact_flow = {
        "transaction_id": TX_ID,
        "spend_identity": SPEND_ID,
        "block_height": 456,
        "inputs": [{"coin_id": INPUT_ID, "asset_id": ASSET_ID, "amount_mojos": 123000}],
    }
    return {
        "expected_inputs": [
            {"coin_id": INPUT_ID, "asset_id": ASSET_ID, "amount_mojos": 123000}
        ],
        "coinset_evidence": dict(exact_flow),
        "spacescan_evidence": dict(exact_flow),
    }


@pytest.mark.parametrize(
    ("evidence", "confidence", "outcome"),
    [
        ({"offer_missing": True}, FillConfidence.OBSERVED, "POSSIBLE_FILL"),
        (
            {"offer_missing": True, "dexie_status": "spent"},
            FillConfidence.OBSERVED,
            "POSSIBLE_FILL",
        ),
        (
            {
                "offer_missing": True,
                "sage_status": "confirmed",
                "sage_confirmed_height": 123,
            },
            FillConfidence.CONFIRMED,
            "FILL",
        ),
        (
            {
                "offer_missing": True,
                "sage_status": "cancelled",
                "dexie_status": "spent",
            },
            FillConfidence.OBSERVED,
            "NOT_FILL",
        ),
        (
            {"offer_missing": True, "self_spend": True},
            FillConfidence.OBSERVED,
            "NOT_FILL",
        ),
        (
            {"offer_missing": True, "external_cancel": True},
            FillConfidence.OBSERVED,
            "NOT_FILL",
        ),
        (
            {"offer_missing": True, "reorg": True},
            FillConfidence.OBSERVED,
            "CONFLICT",
        ),
    ],
)
def test_fill_confidence_classification(evidence, confidence, outcome):
    decision = assess_fill_confidence(evidence)

    assert decision.confidence is confidence
    assert decision.outcome == outcome
    assert decision.can_account is (confidence is FillConfidence.CONFIRMED)
    assert decision.can_replace is (confidence is FillConfidence.CONFIRMED)


def test_coinset_and_spacescan_exact_block_agreement_confirms_during_sage_delay():
    decision = assess_fill_confidence(
        {
            "offer_missing": True,
            "sage_status": "pending",
            **_exact_external_fill_evidence(),
        }
    )

    assert decision.confidence is FillConfidence.CONFIRMED
    assert decision.outcome == "FILL"
    assert decision.authority_source == "CORROBORATED_CHAIN"
    assert "sage_delayed_chain_confirmation" in decision.reason_codes


def test_chain_disagreement_blocks_accounting_and_requests_amber_market_state():
    external = _exact_external_fill_evidence()
    external["spacescan_evidence"] = {
        **external["spacescan_evidence"],
        "block_height": 457,
    }
    decision = assess_fill_confidence(
        {
            "offer_missing": True,
            "dexie_status": "spent",
            **external,
        }
    )

    assert decision.confidence is FillConfidence.PROBABLE
    assert decision.can_account is False
    assert decision.can_replace is False
    assert decision.market_confidence_impact == "AMBER"
    assert "chain_evidence_conflict" in decision.reason_codes


def test_sage_authority_overrides_third_party_fill_hint():
    decision = assess_fill_confidence(
        {
            "offer_missing": True,
            "sage_status": "cancelled",
            "dexie_status": "spent",
            "splash_status": "taken",
            "coinset_transaction_id": TX_ID,
            "coinset_height": 456,
        }
    )

    assert decision.outcome == "NOT_FILL"
    assert decision.authority_source == "SAGE"
    assert decision.can_account is False
    assert "sage_cancel_overrides_provider_hint" in decision.reason_codes


def test_two_independent_provider_hints_are_probable_but_not_accountable():
    decision = assess_fill_confidence(
        {
            "offer_missing": True,
            "dexie_status": "filled",
            "splash_status": "taken",
        }
    )

    assert decision.confidence is FillConfidence.PROBABLE
    assert decision.outcome == "LIKELY_FILL"
    assert decision.can_account is False
    assert decision.can_replace is False


def test_external_confirmation_requires_exact_input_asset_and_amount_agreement():
    external = _exact_external_fill_evidence()
    external["spacescan_evidence"] = {
        **external["spacescan_evidence"],
        "inputs": [{"coin_id": INPUT_ID, "asset_id": ASSET_ID, "amount_mojos": 122999}],
    }

    decision = assess_fill_confidence(
        {"offer_missing": True, "sage_status": "delayed", **external}
    )

    assert decision.confidence is FillConfidence.PROBABLE
    assert decision.outcome == "LIKELY_FILL"
    assert decision.market_confidence_impact == "AMBER"
    assert "chain_evidence_conflict" in decision.reason_codes


def test_sage_nonfill_conflicting_with_exact_external_fill_is_amber_and_not_accounted():
    decision = assess_fill_confidence(
        {
            "offer_missing": True,
            "sage_status": "cancelled",
            **_exact_external_fill_evidence(),
        }
    )

    assert decision.confidence is FillConfidence.OBSERVED
    assert decision.outcome == "CONFLICT"
    assert decision.market_confidence_impact == "AMBER"
    assert decision.can_account is False
    assert "sage_chain_evidence_conflict" in decision.reason_codes


def test_fill_confidence_record_round_trips_immutable_evidence(tmp_path, monkeypatch):
    import database

    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "fill-confidence.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    try:
        evidence = {
            "offer_missing": True,
            "dexie_status": "filled",
            "splash_status": "taken",
        }
        decision = assess_fill_confidence(evidence)
        record = build_fill_confidence_record(
            trade_id=TX_ID,
            asset_id=ASSET_ID,
            decision=decision,
            evidence=evidence,
            observed_at=NOW,
        )

        first = database.record_fill_confidence_assessment(record)
        second = database.record_fill_confidence_assessment(record)
        rows = database.get_fill_confidence_assessments(ASSET_ID, limit=10)

        assert first == second == record["assessment_id"]
        assert len(rows) == 1
        assert rows[0]["trade_id"] == TX_ID
        assert rows[0]["confidence"] == "PROBABLE"
        assert rows[0]["can_account"] is False
        assert rows[0]["can_replace"] is False
        assert rows[0]["reason_codes"] == ["multiple_third_party_fill_hints"]
        assert rows[0]["evidence"] == evidence
    finally:
        database.close_connection()


def test_only_confirmed_fill_assessment_can_authorize_economic_effects():
    observed = build_fill_confidence_record(
        trade_id=TX_ID,
        asset_id=ASSET_ID,
        decision=assess_fill_confidence({"offer_missing": True}),
        evidence={"offer_missing": True},
        observed_at=NOW,
    )
    confirmed_evidence = {
        "offer_missing": True,
        "sage_status": "confirmed",
        "sage_confirmed_height": 123,
    }
    confirmed = build_fill_confidence_record(
        trade_id=TX_ID,
        asset_id=ASSET_ID,
        decision=assess_fill_confidence(confirmed_evidence),
        evidence=confirmed_evidence,
        observed_at=NOW,
    )

    assert observed["can_account"] is False
    assert observed["can_replace"] is False
    assert confirmed["can_account"] is True
    assert confirmed["can_replace"] is True


def _persist_fill_assessment(database, *, evidence, observed_at=NOW):
    decision = assess_fill_confidence(evidence)
    record = build_fill_confidence_record(
        trade_id=TX_ID,
        asset_id=ASSET_ID,
        decision=decision,
        evidence=evidence,
        observed_at=observed_at,
    )
    database.record_fill_confidence_assessment(record)
    return record


def test_data_reset_preserves_unresolved_fill_evidence(tmp_path, monkeypatch):
    import database

    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "unresolved-reset.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    try:
        _persist_fill_assessment(database, evidence={"offer_missing": True})

        result = database.guarded_reset_authoritative_state(clear_fills=True)

        assert result["success"] is False
        assert "unresolved_fill_evidence" in result["conflicts"]
        assert result["fill_confidence_assessments_cleared"] == 0
        assert len(database.get_fill_confidence_assessments(ASSET_ID, limit=10)) == 1
    finally:
        database.close_connection()


def test_data_reset_includes_resolved_fill_evidence(tmp_path, monkeypatch):
    import database

    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "resolved-reset.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    try:
        _persist_fill_assessment(
            database,
            evidence={"offer_missing": True, "external_cancel": True},
        )

        result = database.guarded_reset_authoritative_state(clear_fills=True)

        assert result["success"] is True
        assert result["fill_confidence_assessments_cleared"] == 1
        assert database.get_fill_confidence_assessments(ASSET_ID, limit=10) == []
    finally:
        database.close_connection()
