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

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


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
    provider_hint = dexie_status in {"spent", "taken", "filled", "completed"} or (
        splash_status in {"spent", "taken", "filled", "completed"}
    )

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

    coinset_tx = evidence.get("coinset_transaction_id")
    spacescan_tx = evidence.get("spacescan_transaction_id")
    coinset_height = evidence.get("coinset_height")
    spacescan_height = evidence.get("spacescan_height")
    coinset_complete = _exact_chain_reference(coinset_tx, coinset_height)
    spacescan_complete = _exact_chain_reference(spacescan_tx, spacescan_height)
    if coinset_complete and spacescan_complete:
        if coinset_tx == spacescan_tx and coinset_height == spacescan_height:
            reasons = ["exact_chain_evidence_agreement"]
            if sage_status in {"", "pending", "delayed", "unknown"}:
                reasons.append("sage_delayed_chain_confirmation")
            return FillAuthorityDecision(
                FillConfidence.CONFIRMED,
                "FILL",
                "CORROBORATED_CHAIN",
                tuple(reasons),
            )
        return FillAuthorityDecision(
            FillConfidence.PROBABLE,
            "LIKELY_FILL",
            "CONFLICTED_CHAIN",
            ("chain_evidence_conflict",),
            "AMBER",
        )

    if provider_hint:
        return FillAuthorityDecision(
            FillConfidence.PROBABLE,
            "LIKELY_FILL",
            "MARKETPLACE_HINT",
            ("third_party_fill_hint",),
        )
    return FillAuthorityDecision(
        FillConfidence.OBSERVED,
        "POSSIBLE_FILL",
        "LOCAL_OBSERVATION",
        ("offer_disappearance_observed",),
    )


def _exact_chain_reference(transaction_id, height) -> bool:
    return bool(
        type(transaction_id) is str
        and len(transaction_id) == 64
        and all(character in "0123456789abcdef" for character in transaction_id)
        and type(height) is int
        and height > 0
    )


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
