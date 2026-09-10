from __future__ import annotations

import pytest
from fill_classifier import FillConfidence, assess_fill_confidence


TX_ID = "ab" * 32


@pytest.mark.parametrize(
    ("evidence", "confidence", "outcome"),
    [
        ({"offer_missing": True}, FillConfidence.OBSERVED, "POSSIBLE_FILL"),
        (
            {"offer_missing": True, "dexie_status": "spent"},
            FillConfidence.PROBABLE,
            "LIKELY_FILL",
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
            "coinset_transaction_id": TX_ID,
            "coinset_height": 456,
            "spacescan_transaction_id": TX_ID,
            "spacescan_height": 456,
        }
    )

    assert decision.confidence is FillConfidence.CONFIRMED
    assert decision.outcome == "FILL"
    assert decision.authority_source == "CORROBORATED_CHAIN"
    assert "sage_delayed_chain_confirmation" in decision.reason_codes


def test_chain_disagreement_blocks_accounting_and_requests_amber_market_state():
    decision = assess_fill_confidence(
        {
            "offer_missing": True,
            "dexie_status": "spent",
            "coinset_transaction_id": TX_ID,
            "coinset_height": 456,
            "spacescan_transaction_id": TX_ID,
            "spacescan_height": 457,
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
