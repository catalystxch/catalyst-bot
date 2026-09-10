"""Classify detected fills as retail, arb sweep, Dexie-combined, or unknown

Takes a detected fill plus any available Dexie metadata and labels it as one of
RETAIL, ARB_SWEEP_BUY, ARB_SWEEP_SELL, DEXIE_COMBINED, or UNKNOWN. The decision
uses taker-puzzle-hash matching against `cfg.KNOWN_ARB_PUZZLE_HASHES`, Dexie
response metadata, and clustering by `spent_block_index` to spot multi-offer
atomic sweeps. The module is pure functions plus a single DB write through
`update_fill_classification`.

Key responsibilities:
    - Resolve taker puzzle hash and match against the known arb-wallet set
    - Detect DEXIE_COMBINED bundles via shared block index across close fills
    - Return a `FillClassification` with category, confidence, and evidence
    - Persist the label without ever blocking the fill-recording path

Fail-open by design: any exception inside classification is swallowed and the
fill is left labelled `unknown`, so fill recording is never prevented by a
classifier bug or missing upstream data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Set

from providers.models import canonical_evidence_json, evidence_digest


# ---------------------------------------------------------------------------
# Classification constants
# ---------------------------------------------------------------------------


class FillType:
    RETAIL = "retail"
    ARB_SWEEP_BUY = "arb_sweep_buy"
    ARB_SWEEP_SELL = "arb_sweep_sell"
    DEXIE_COMBINED = "dexie_combined"
    UNKNOWN = "unknown"


class FillConfidence(str, Enum):
    """Evidence maturity for economic accounting and replacement authority."""

    OBSERVED = "Observed"
    PROBABLE = "Probable"
    CONFIRMED = "Confirmed"


@dataclass(frozen=True, slots=True)
class FillAuthorityDecision:
    confidence: FillConfidence
    outcome: str
    authority_source: str
    reason_codes: tuple[str, ...]
    market_confidence_impact: str | None = None

    @property
    def can_account(self) -> bool:
        return self.confidence is FillConfidence.CONFIRMED and self.outcome == "FILL"

    @property
    def can_replace(self) -> bool:
        return self.can_account


def assess_fill_confidence(evidence: Dict) -> FillAuthorityDecision:
    """Classify untrusted fill hints without authorizing premature accounting.

    Sage remains authoritative.  When Sage is delayed, exact Coinset and
    Spacescan transaction/height agreement is sufficient corroborated chain
    proof.  Marketplace statuses alone can reach only ``Probable``.
    """

    if type(evidence) is not dict:
        raise TypeError("fill evidence must be a dict")
    sage_status = str(evidence.get("sage_status") or "").strip().lower()
    dexie_status = str(evidence.get("dexie_status") or "").strip().lower()
    splash_status = str(evidence.get("splash_status") or "").strip().lower()
    spacescan_status = str(evidence.get("spacescan_status") or "").strip().lower()
    provider_statuses = (dexie_status, splash_status, spacescan_status)
    provider_hint_count = sum(
        status in {"spent", "taken", "filled", "completed"}
        for status in provider_statuses
    )
    provider_hint = provider_hint_count > 0
    chain_state = _external_chain_evidence_state(evidence)

    if evidence.get("reorg") is True:
        return FillAuthorityDecision(
            FillConfidence.OBSERVED,
            "CONFLICT",
            "CHAIN",
            ("chain_reorg_observed",),
            "AMBER",
        )
    if evidence.get("self_spend") is True:
        return FillAuthorityDecision(
            FillConfidence.OBSERVED,
            "NOT_FILL",
            "SAGE",
            ("self_spend_rejected",),
        )
    if evidence.get("external_cancel") is True:
        return FillAuthorityDecision(
            FillConfidence.OBSERVED,
            "NOT_FILL",
            "CHAIN",
            ("external_cancellation_proven",),
        )
    if sage_status in {"cancelled", "canceled", "expired"}:
        if chain_state == "confirmed":
            return FillAuthorityDecision(
                FillConfidence.OBSERVED,
                "CONFLICT",
                "SAGE_AND_CORROBORATED_CHAIN",
                ("sage_chain_evidence_conflict",),
                "AMBER",
            )
        reasons = ["sage_terminal_non_fill"]
        if provider_hint:
            reasons.append("sage_cancel_overrides_provider_hint")
        return FillAuthorityDecision(
            FillConfidence.OBSERVED,
            "NOT_FILL",
            "SAGE",
            tuple(reasons),
            "AMBER" if provider_hint else None,
        )

    sage_height = evidence.get("sage_confirmed_height")
    if sage_status in {"confirmed", "completed", "filled"} and (
        type(sage_height) is int and sage_height > 0
    ):
        return FillAuthorityDecision(
            FillConfidence.CONFIRMED,
            "FILL",
            "SAGE",
            ("sage_confirmed_fill",),
        )

    if chain_state == "confirmed":
        reasons = ["exact_chain_evidence_agreement"]
        if sage_status in {"", "pending", "delayed", "unknown"}:
            reasons.append("sage_delayed_chain_confirmation")
        return FillAuthorityDecision(
            FillConfidence.CONFIRMED,
            "FILL",
            "CORROBORATED_CHAIN",
            tuple(reasons),
        )
    if chain_state == "conflict":
        return FillAuthorityDecision(
            FillConfidence.PROBABLE,
            "LIKELY_FILL",
            "CONFLICTED_CHAIN",
            ("chain_evidence_conflict",),
            "AMBER",
        )

    if provider_hint_count >= 2:
        return FillAuthorityDecision(
            FillConfidence.PROBABLE,
            "LIKELY_FILL",
            "CORROBORATED_MARKETPLACE_HINTS",
            ("multiple_third_party_fill_hints",),
        )
    if provider_hint:
        return FillAuthorityDecision(
            FillConfidence.OBSERVED,
            "POSSIBLE_FILL",
            "MARKETPLACE_HINT",
            ("third_party_fill_hint",),
        )
    return FillAuthorityDecision(
        FillConfidence.OBSERVED,
        "POSSIBLE_FILL",
        "LOCAL_OBSERVATION",
        ("offer_disappearance_observed",),
    )


def _exact_hex_id(value) -> str | None:
    if type(value) is not str:
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        return None
    return normalized


def _exact_chain_inputs(value) -> tuple[tuple[str, str, int], ...] | None:
    if type(value) is not list or not value or len(value) > 64:
        return None
    normalized = []
    for row in value:
        if type(row) is not dict or set(row) != {
            "coin_id",
            "asset_id",
            "amount_mojos",
        }:
            return None
        coin_id = _exact_hex_id(row.get("coin_id"))
        asset_id = str(row.get("asset_id") or "").strip().lower()
        amount = row.get("amount_mojos")
        if (
            coin_id is None
            or (asset_id != "xch" and _exact_hex_id(asset_id) is None)
            or type(amount) is not int
            or isinstance(amount, bool)
            or amount <= 0
        ):
            return None
        normalized.append((coin_id, asset_id, amount))
    if len({coin_id for coin_id, _asset_id, _amount in normalized}) != len(
        normalized
    ):
        return None
    return tuple(sorted(normalized))


def _exact_external_chain_evidence(value) -> tuple | None:
    if type(value) is not dict or set(value) != {
        "transaction_id",
        "spend_identity",
        "block_height",
        "inputs",
    }:
        return None
    transaction_id = _exact_hex_id(value.get("transaction_id"))
    spend_identity = _exact_hex_id(value.get("spend_identity"))
    height = value.get("block_height")
    inputs = _exact_chain_inputs(value.get("inputs"))
    if (
        transaction_id is None
        or spend_identity is None
        or type(height) is not int
        or isinstance(height, bool)
        or height <= 0
        or inputs is None
    ):
        return None
    return transaction_id, spend_identity, height, inputs


def _external_chain_evidence_state(evidence: Dict) -> str:
    """Return confirmed/conflict/incomplete for optional dual chain proof."""

    coinset_raw = evidence.get("coinset_evidence")
    spacescan_raw = evidence.get("spacescan_evidence")
    expected_raw = evidence.get("expected_inputs")
    if coinset_raw is None and spacescan_raw is None:
        return "incomplete"
    coinset = _exact_external_chain_evidence(coinset_raw)
    spacescan = _exact_external_chain_evidence(spacescan_raw)
    expected = _exact_chain_inputs(expected_raw)
    if coinset is None or spacescan is None or expected is None:
        return "incomplete"
    if coinset != spacescan or coinset[3] != expected:
        return "conflict"
    return "confirmed"


def build_fill_confidence_record(
    *,
    trade_id: str,
    asset_id: str,
    decision: FillAuthorityDecision,
    evidence: Dict,
    observed_at: datetime,
) -> Dict:
    """Build one immutable, redacted assessment for durable UI/audit state."""

    safe_trade_id = _exact_hex_id(trade_id)
    safe_asset_id = _exact_hex_id(asset_id)
    if safe_trade_id is None or safe_asset_id is None:
        raise ValueError("trade_id and asset_id must be exact lowercase hex identities")
    if type(decision) is not FillAuthorityDecision:
        raise TypeError("decision must be a FillAuthorityDecision")
    if type(observed_at) is not datetime or observed_at.tzinfo is None:
        raise TypeError("observed_at must be timezone-aware")
    if type(evidence) is not dict:
        raise TypeError("evidence must be a dict")
    evidence_json = canonical_evidence_json(evidence)
    observed_text = observed_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    record = {
        "trade_id": safe_trade_id,
        "asset_id": safe_asset_id,
        "confidence": decision.confidence.name,
        "outcome": decision.outcome,
        "authority_source": decision.authority_source,
        "reason_codes": list(decision.reason_codes),
        "market_confidence_impact": decision.market_confidence_impact,
        "can_account": decision.can_account,
        "can_replace": decision.can_replace,
        "evidence_json": evidence_json,
        "evidence_sha256": evidence_digest(evidence_json),
        "observed_at": observed_text,
    }
    identity_json = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    record["assessment_id"] = hashlib.sha256(identity_json.encode("utf-8")).hexdigest()
    return record


@dataclass
class FillClassification:
    """Result of classifying a single fill."""

    trade_id: str
    classification: str = FillType.UNKNOWN
    confidence: str = "low"  # "high" | "medium" | "low"
    taker_puzzle_hash: Optional[str] = None
    spent_block_index: Optional[int] = None
    sweep_group_id: Optional[str] = None  # set by SweepCoordinator
    reasons: List[str] = field(default_factory=list)
    # Stamped by fill_tracker after classification so sweep protection
    # can determine which side was swept without a DB lookup.
    side: Optional[str] = None  # "buy" | "sell"

    def is_arb(self) -> bool:
        return self.classification in (
            FillType.ARB_SWEEP_BUY,
            FillType.ARB_SWEEP_SELL,
            FillType.DEXIE_COMBINED,
        )


# ---------------------------------------------------------------------------
# Core classification logic
# ---------------------------------------------------------------------------


def classify_fill(
    trade_id: str,
    fill_detail: Dict,
    dexie_detail: Optional[Dict] = None,
) -> FillClassification:
    """Classify a single fill based on available data.

    Args:
        trade_id:     The offer's trade_id.
        fill_detail:  Dict from _record_fill() — side, coin_id, tier, etc.
        dexie_detail: Optional Dexie offer detail response (may be None if
                      Dexie was unreachable at fill time).

    Returns:
        FillClassification with the best available classification.
    """
    result = FillClassification(trade_id=trade_id)
    # Task 9's authoritative reconciliation already proved this on-chain
    # height.  Preserve it independently of optional third-party metadata so
    # a missing Dexie detail cannot erase sweep grouping evidence.
    if type(fill_detail) is dict:
        authoritative_block = fill_detail.get("spent_block_index")
        if type(authoritative_block) is int and authoritative_block > 0:
            result.spent_block_index = authoritative_block

    # Pull known arb puzzle hashes from config (fail-open)
    known_arb_hashes: Set[str] = set()
    try:
        from config import cfg

        raw_hashes = getattr(cfg, "KNOWN_ARB_PUZZLE_HASHES", [])
        known_arb_hashes = {
            h.strip().lower().removeprefix("0x")
            for h in (raw_hashes if isinstance(raw_hashes, (list, tuple)) else [])
            if h.strip()
        }
    except Exception:
        pass

    side = str(fill_detail.get("side") or "").lower()

    # --- Extract spent_block_index from Dexie detail ---
    if type(dexie_detail) is dict:
        raw_block = dexie_detail.get("spent_block_index")
        if raw_block is not None and result.spent_block_index is None:
            try:
                result.spent_block_index = int(raw_block)
            except (TypeError, ValueError):
                pass
        else:
            # spent_block_index is absent from the Dexie response.
            # This means the SweepCoordinator cannot group this fill with others
            # that share the same on-chain block. Log at debug level so we can
            # track how often Dexie omits this field.
            result.reasons.append("dexie_detail present but spent_block_index missing")
            try:
                import logging as _logging

                _logging.getLogger("fill_classifier").debug(
                    "trade_id=%s: dexie_detail present but spent_block_index absent — "
                    "sweep grouping disabled for this fill. "
                    "Dexie response keys: %s",
                    trade_id,
                    sorted(dexie_detail.keys()),
                )
            except Exception:
                pass

        # --- Extract taker puzzle hash from Dexie output_coins ---
        # When an offer is filled, the output_coins dict shows where each asset
        # was sent. For a buy offer (we spend XCH), XCH outputs go to the taker.
        # For a sell offer (we spend CAT), CAT outputs go to the taker.
        try:
            result.taker_puzzle_hash = _extract_taker_puzzle_hash(dexie_detail, side)
        except Exception:
            pass

    # --- Arb detection via known puzzle hash ---
    if result.taker_puzzle_hash and known_arb_hashes:
        norm = result.taker_puzzle_hash.lower().removeprefix("0x")
        if norm in known_arb_hashes:
            result.classification = (
                FillType.ARB_SWEEP_BUY if side == "sell" else FillType.ARB_SWEEP_SELL
            )
            result.confidence = "high"
            result.reasons.append(
                f"taker_puzzle_hash matches known arb wallet ({norm[:12]}...)"
            )
            return result

    # --- Dexie combined-offer marker ---
    # Dexie sometimes sets a "combined" or "matched_offers" field on fills
    # that are part of an atomic multi-offer sweep.
    if dexie_detail:
        combined = dexie_detail.get("combined") or dexie_detail.get("is_combined")
        matched = dexie_detail.get("matched_offers") or dexie_detail.get(
            "related_offers"
        )
        if combined or (isinstance(matched, list) and len(matched) > 1):
            result.classification = FillType.DEXIE_COMBINED
            result.confidence = "high"
            result.reasons.append("dexie_combined flag or multiple matched_offers")
            return result

    # --- Retail: Dexie data present, no arb or combined signals ---
    # If we have Dexie detail (the offer was visible on Dexie) but none of the
    # arb signals fired, this is a normal retail fill with medium confidence.
    # UNKNOWN is reserved for fills where Dexie detail was unavailable entirely.
    if dexie_detail:
        result.classification = FillType.RETAIL
        result.confidence = "medium"
        result.reasons.append("dexie detail present, no arb/combined signals detected")
        return result

    # --- UNKNOWN: no Dexie data, can't classify ---
    # SweepCoordinator will upgrade UNKNOWN→DEXIE_COMBINED if multiple fills
    # share the same spent_block_index in the next bot cycle.
    result.classification = FillType.UNKNOWN
    result.confidence = "low"
    result.reasons.append(
        "no dexie detail available — insufficient data for classification"
    )
    return result


def _extract_taker_puzzle_hash(detail: Dict, side: str) -> Optional[str]:
    """Extract the taker's puzzle hash from Dexie offer output_coins.

    For a buy offer (bot spent XCH), the taker received XCH.
    For a sell offer (bot spent CAT), the taker received CAT.
    We look at the output coins for the asset the taker received,
    and return the puzzle_hash of the first external output.

    Dexie output_coins structure:
        { "xch": [{"id": "...", "puzzle_hash": "...", "amount": N}, ...],
          "<asset_id>": [...] }
    """
    if not isinstance(detail, dict):
        return None

    output_coins: Dict = detail.get("output_coins") or {}
    if not isinstance(output_coins, dict):
        return None

    try:
        from config import cfg

        xch_wid = str(getattr(cfg, "WALLET_ID_XCH", 1))
        cat_asset_id = str(getattr(cfg, "CAT_ASSET_ID", "")).lower()
    except Exception:
        xch_wid = "1"
        cat_asset_id = ""

    # The taker receives the asset we're selling:
    #   buy offer  → we spent XCH, taker receives our CAT or we receive CAT;
    #                actually taker receives XCH change — skip this path.
    # More reliably: taker puzzle hash is on the output for the asset we SENT.
    #   sell offer → we sent CAT → look for CAT in output_coins
    #   buy offer  → we sent XCH → look for XCH in output_coins
    target_key: Optional[str] = None
    for key in output_coins.keys():
        key_lower = str(key).lower()
        if side == "sell" and (key_lower == cat_asset_id or "cat" in key_lower):
            target_key = key
            break
        if side == "buy" and key_lower in ("xch", "1", xch_wid):
            target_key = key
            break

    if target_key is None:
        # Fallback: take the first non-empty key
        for key, coins in output_coins.items():
            if coins:
                target_key = key
                break

    if target_key is None:
        return None

    coins = output_coins.get(target_key) or []
    if not isinstance(coins, list) or not coins:
        return None

    # Return the puzzle_hash of the first coin (the taker's receiving address)
    first = coins[0]
    if isinstance(first, dict):
        ph = first.get("puzzle_hash") or first.get("puzzleHash")
        if ph:
            return str(ph).lower().removeprefix("0x")

    return None


# ---------------------------------------------------------------------------
# Batch update helper
# ---------------------------------------------------------------------------


def update_fill_classification(
    fill_id: int,
    classification: FillClassification,
) -> bool:
    """Persist a FillClassification back to the fills table.

    Returns True on success.  Fail-open — never raises.
    """
    try:
        from database import get_connection

        conn = get_connection()
        conn.execute(
            """UPDATE fills
               SET fill_classification = ?,
                   taker_puzzle_hash   = ?,
                   spent_block_index   = ?,
                   sweep_group_id      = ?
               WHERE fill_id = ?""",
            (
                classification.classification,
                classification.taker_puzzle_hash,
                classification.spent_block_index,
                classification.sweep_group_id,
                fill_id,
            ),
        )
        conn.commit()
        return True
    except Exception:
        return False


def classify_and_store_fill(
    fill_id: int,
    trade_id: str,
    fill_detail: Dict,
    dexie_detail: Optional[Dict] = None,
) -> FillClassification:
    """Classify a fill and immediately persist the result.

    This is the main entry point called from fill_tracker after
    a fill is recorded.  All errors are swallowed.
    """
    try:
        result = classify_fill(trade_id, fill_detail, dexie_detail)
        update_fill_classification(fill_id, result)
        return result
    except Exception:
        return FillClassification(trade_id=trade_id)
