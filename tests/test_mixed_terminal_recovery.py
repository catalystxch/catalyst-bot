"""The mixed terminal preview must fence the complete durable cohort."""

from __future__ import annotations

import json

import pytest


CAMPAIGN_ID = "a" * 64
ASSET_ID = "b" * 64
WALLET_HASH = "f" * 64


def _cohort():
    campaign = {
        "campaign_id": CAMPAIGN_ID,
        "revision": 0,
        "asset_id": ASSET_ID,
        "network": "mainnet",
        "status": "active",
    }
    intents = []
    offers = []
    blockers = []
    for index in range(6):
        intent_id = f"{index + 1:064x}"
        trade_id = f"{index + 11:064x}"
        state = "unknown" if index == 0 else "visible"
        intent = {
            "intent_id": intent_id,
            "sage_trade_id": trade_id,
            "purpose": f"bootstrap:{CAMPAIGN_ID}:revision:0",
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
            "asset_id": ASSET_ID,
            "side": "buy" if index < 3 else "sell",
            "tier": "inner",
            "lifecycle_state": state,
            "parent_intent_id": None,
            "child_intent_id": None,
        }
        intents.append(intent)
        offers.append(
            {
                "intent_id": intent_id,
                "trade_id": trade_id,
                "cat_asset_id": ASSET_ID,
                "side": intent["side"],
                "tier": "inner",
                "status": "open",
            }
        )
        blockers.append(
            {
                "operation_id": f"reconcile:{intent_id}",
                "intent_id": intent_id,
                "operation_type": "RECONCILE",
                "phase": "PREPARED",
                "outcome": "UNKNOWN",
                "blocks_mutation": 1,
            }
        )
    latch = {
        "state": "tripped",
        "reason_code": "REGISTRY_BLOCKED",
        "generation": 150,
        "blocking_operation_ids_json": json.dumps(
            [f"reconcile:{row['intent_id']}" for row in intents]
        ),
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": "mainnet",
    }
    return campaign, intents, offers, blockers, latch


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "unsupported_unknown",
        "unrelated_root",
        "duplicate_trade",
        "missing_projection",
        "extra_blocker",
        "wrong_asset",
        "lineage",
    ],
)
def test_mixed_cohort_requires_exact_six_roots(change):
    from mixed_terminal_recovery import validate_mixed_terminal_cohort

    campaign, intents, offers, blockers, latch = _cohort()
    if change == "unsupported_unknown":
        blockers[0]["outcome"] = "CREATED"
    elif change == "unrelated_root":
        intents.append({**intents[0], "intent_id": "e" * 64, "purpose": "unrelated"})
    elif change == "duplicate_trade":
        intents[1]["sage_trade_id"] = intents[0]["sage_trade_id"]
    elif change == "missing_projection":
        offers.pop()
    elif change == "extra_blocker":
        blockers.append({**blockers[0], "operation_id": "other"})
    elif change == "wrong_asset":
        offers[0]["cat_asset_id"] = "d" * 64
    elif change == "lineage":
        intents[0]["parent_intent_id"] = "d" * 64
    if change == "valid":
        result = validate_mixed_terminal_cohort(
            campaign, intents, offers, blockers, {}, latch
        )
        assert [row["intent_id"] for row in result] == sorted(
            row["intent_id"] for row in intents
        )
        assert result[0]["lifecycle_state"] == "unknown"
    else:
        with pytest.raises(ValueError):
            validate_mixed_terminal_cohort(
                campaign, intents, offers, blockers, {}, latch
            )


def test_mixed_cohort_retry_includes_proven_terminal_without_reapplying():
    from mixed_terminal_recovery import validate_mixed_terminal_cohort

    campaign, intents, offers, blockers, latch = _cohort()
    completed = intents[0]
    completed["lifecycle_state"] = "terminal"
    completed["intent_id"] = "historical-filled-intent"
    offers.pop(0)
    blockers.pop(0)
    latch["blocking_operation_ids_json"] = json.dumps(
        [row["operation_id"] for row in blockers]
    )
    proof = {
        completed["sage_trade_id"]: {
            "intent_id": completed["intent_id"],
            "operation_id": f"reconcile:{completed['intent_id']}",
            "outcome": "FILLED_PROVEN",
            "evidence_sha256": "9" * 64,
        }
    }
    result = validate_mixed_terminal_cohort(
        campaign, intents, offers, blockers, proof, latch
    )
    assert len(result) == 6
    assert sum(row["lifecycle_state"] == "terminal" for row in result) == 1


def test_mixed_cohort_allowed_latch_accepts_only_supported_open_roots():
    from mixed_terminal_recovery import validate_mixed_terminal_cohort

    campaign, intents, offers, _blockers, latch = _cohort()
    intents[0]["lifecycle_state"] = "visible"
    latch.update(
        state="resolved",
        reason_code=None,
        blocking_operation_ids_json="[]",
    )
    assert (
        len(validate_mixed_terminal_cohort(campaign, intents, offers, [], {}, latch))
        == 6
    )
    intents[0]["lifecycle_state"] = "unknown"
    with pytest.raises(ValueError):
        validate_mixed_terminal_cohort(campaign, intents, offers, [], {}, latch)
