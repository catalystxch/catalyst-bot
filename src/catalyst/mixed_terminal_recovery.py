"""Proof-only recovery of an exact elapsed campaign's terminal offer cohort.

The cohort validator is deliberately pure. It grants no lease, trading permit,
wallet effect, or terminal database write. Sage evidence collection and the
fenced commit are separate steps and must recheck this result.
"""

from __future__ import annotations

import json
import re
from typing import Any


_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_OPEN_STATES = frozenset({"created", "visible", "unknown"})
_TERMINAL_OUTCOMES = frozenset({"FILLED_PROVEN", "EXPIRED_PROVEN"})


def _hex_identity(value: Any) -> bool:
    return type(value) is str and _HEX_64.fullmatch(value) is not None


def _intent_identity(value: Any) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 128
        and value.strip() == value
        and not any(ord(char) < 32 for char in value)
    )


def validate_mixed_terminal_cohort(
    campaign: Any,
    intents: Any,
    open_offers: Any,
    unresolved_blockers: Any,
    terminal_records: Any,
    latch: Any,
) -> list[dict[str, Any]]:
    """Return sorted exact roots or refuse the entire mixed recovery cohort."""

    if (
        type(campaign) is not dict
        or not _hex_identity(campaign.get("campaign_id"))
        or not _hex_identity(campaign.get("asset_id"))
        or type(campaign.get("revision")) is not int
        or campaign["revision"] < 0
        or campaign.get("network") not in {"mainnet", "testnet"}
        or campaign.get("status") != "active"
        or type(intents) is not list
        or type(open_offers) is not list
        or type(unresolved_blockers) is not list
        or type(terminal_records) is not dict
        or type(latch) is not dict
    ):
        raise ValueError("mixed terminal campaign authority is invalid")
    purpose = f"bootstrap:{campaign['campaign_id']}:revision:{campaign['revision']}"
    prefix = f"bootstrap:{campaign['campaign_id']}:revision:"
    asset = campaign["asset_id"]
    network = campaign["network"]
    roots = [
        row for row in intents if type(row) is dict and row.get("purpose") == purpose
    ]
    if not 1 <= len(roots) <= 256 or any(type(row) is not dict for row in intents):
        raise ValueError("mixed terminal roots are incomplete")
    wallet_hashes = {row.get("wallet_fingerprint_hash") for row in roots}
    if len(wallet_hashes) != 1 or not _hex_identity(next(iter(wallet_hashes))):
        raise ValueError("mixed terminal wallet binding differs")
    wallet_hash = next(iter(wallet_hashes))
    if any(
        row.get("purpose") != purpose
        and row.get("lifecycle_state") != "terminal"
        and (
            str(row.get("purpose") or "").startswith(prefix)
            or (
                row.get("wallet_fingerprint_hash") == wallet_hash
                and row.get("network") == network
                and row.get("asset_id") == asset
            )
        )
        for row in intents
    ):
        raise ValueError("unrelated unresolved offer root exists")
    intent_ids = [row.get("intent_id") for row in roots]
    trade_ids = [row.get("sage_trade_id") for row in roots]
    if (
        any(not _intent_identity(value) for value in intent_ids)
        or any(not _hex_identity(value) for value in trade_ids)
        or len(set(intent_ids)) != len(roots)
        or len(set(trade_ids)) != len(roots)
        or any(
            row.get("wallet_fingerprint_hash") != wallet_hash
            or row.get("network") != network
            or row.get("asset_id") != asset
            or row.get("side") not in {"buy", "sell"}
            or type(row.get("tier")) is not str
            or not row["tier"]
            or row.get("lifecycle_state") not in _OPEN_STATES | {"terminal"}
            or row.get("parent_intent_id") is not None
            or row.get("child_intent_id") is not None
            for row in roots
        )
    ):
        raise ValueError("mixed terminal root identity differs")
    open_roots = [row for row in roots if row["lifecycle_state"] in _OPEN_STATES]
    expected_blockers = {f"reconcile:{row['intent_id']}" for row in open_roots}
    if len(expected_blockers) != len(open_roots):
        raise ValueError("mixed terminal blockers are duplicated")
    if any(type(row) is not dict for row in unresolved_blockers):
        raise ValueError("mixed terminal journal is invalid")
    journal = {row.get("operation_id"): row for row in unresolved_blockers}
    if len(journal) != len(unresolved_blockers):
        raise ValueError("mixed terminal journal identities are duplicated")
    try:
        latch_ids = json.loads(latch["blocking_operation_ids_json"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("mixed terminal latch blockers are invalid") from exc
    if type(latch_ids) is not list or len(latch_ids) != len(set(latch_ids)):
        raise ValueError("mixed terminal latch blockers are duplicated")
    restricted = latch.get("state") == "tripped"
    if restricted:
        if (
            latch.get("reason_code") != "REGISTRY_BLOCKED"
            or type(latch.get("generation")) is not int
            or latch["generation"] < 1
            or latch.get("wallet_fingerprint_hash") != wallet_hash
            or latch.get("network") != network
            or not expected_blockers
            or set(latch_ids) != expected_blockers
            or set(journal) != expected_blockers
        ):
            raise ValueError("mixed terminal restricted blocker set differs")
    elif latch.get("state") == "resolved":
        if (
            latch_ids
            or journal
            or any(row["lifecycle_state"] == "unknown" for row in roots)
        ):
            raise ValueError("mixed terminal normal authority is not clear")
    else:
        raise ValueError("mixed terminal latch state is unsupported")
    for row in open_roots:
        blocker = journal.get(f"reconcile:{row['intent_id']}")
        if restricted and (
            blocker is None
            or blocker.get("intent_id") != row["intent_id"]
            or blocker.get("operation_type") != "RECONCILE"
            or blocker.get("outcome") != "UNKNOWN"
            or blocker.get("blocks_mutation") != 1
        ):
            raise ValueError("mixed terminal journal does not match the root")
    projected = {
        offer.get("trade_id"): offer for offer in open_offers if type(offer) is dict
    }
    if (
        len(projected) != len(open_offers)
        or set(projected) != {row["sage_trade_id"] for row in open_roots}
        or any(
            type(offer) is not dict
            or offer.get("status") != "open"
            or offer.get("cat_asset_id") != asset
            or offer.get("side") != row["side"]
            or offer.get("tier") != row["tier"]
            for row in open_roots
            for offer in [projected.get(row["sage_trade_id"])]
        )
    ):
        raise ValueError("mixed terminal open projection differs")
    expected_terminal = {
        row["sage_trade_id"] for row in roots if row["lifecycle_state"] == "terminal"
    }
    if set(terminal_records) != expected_terminal:
        raise ValueError("mixed terminal durable proofs are incomplete")
    for row in roots:
        if row["lifecycle_state"] != "terminal":
            continue
        proof = terminal_records[row["sage_trade_id"]]
        if (
            type(proof) is not dict
            or proof.get("intent_id") != row["intent_id"]
            or proof.get("operation_id") != f"reconcile:{row['intent_id']}"
            or proof.get("outcome") not in _TERMINAL_OUTCOMES
            or not _hex_identity(proof.get("evidence_sha256"))
        ):
            raise ValueError("mixed terminal durable proof differs")
    return [dict(row) for row in sorted(roots, key=lambda row: row["intent_id"])]
