"""Proof-bound recovery for pre-intent Sage offer reservations.

Older CATalyst releases stored an open offer and its locked coin before the
append-only intent registry existed. New startup safety correctly refuses an
unowned lock. This migration adopts only an offer that Sage independently
proves expired, then routes its terminal write through Task 9's existing
reconciliation boundary. No wallet mutation is performed here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any


_HEX = frozenset("0123456789abcdef")
_XCH_SCALE = Decimal("1000000000000")


def _hex_id(value: Any) -> str:
    if type(value) is not str:
        return ""
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return text if len(text) == 64 and all(character in _HEX for character in text) else ""


def _canonical_utc(value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("legacy offer timestamp is unavailable")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise ValueError("legacy offer timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _atomic_amount(value: Any, scale: Decimal, label: str) -> str:
    try:
        amount = Decimal(str(value)) * scale
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    integral = amount.to_integral_value()
    if amount != integral or integral <= 0:
        raise ValueError(f"{label} is not an exact positive atomic amount")
    return str(int(integral))


def _legacy_intent(candidate: Any, wallet_hash: str, network: str, decimals: int) -> dict:
    if type(candidate) is not dict:
        raise ValueError("legacy reservation candidate is malformed")
    trade_id = _hex_id(candidate.get("trade_id"))
    coin_id = _hex_id(candidate.get("coin_id"))
    asset_id = _hex_id(candidate.get("cat_asset_id"))
    side = candidate.get("side")
    tier = candidate.get("tier")
    offer_text = candidate.get("offer_bech32")
    if (
        not trade_id
        or not coin_id
        or not asset_id
        or side not in {"buy", "sell"}
        or type(tier) is not str
        or not tier.strip()
        or type(offer_text) is not str
        or not offer_text
        or type(decimals) is not int
        or not 0 <= decimals <= 18
    ):
        raise ValueError("legacy reservation candidate identity is invalid")
    xch = _atomic_amount(candidate.get("size_xch"), _XCH_SCALE, "legacy XCH amount")
    cat = _atomic_amount(
        candidate.get("size_cat"), Decimal(10) ** decimals, "legacy CAT amount"
    )
    prepared_at = _canonical_utc(candidate.get("created_at"))
    return {
        "intent_id": f"legacy-startup:{trade_id}",
        "wallet_fingerprint_hash": wallet_hash,
        "network": network,
        "asset_id": asset_id,
        "side": side,
        "tier": tier.strip(),
        "offered_amount_atomic": xch if side == "buy" else cat,
        "requested_amount_atomic": cat if side == "buy" else xch,
        "selected_coin_ids_json": json.dumps([coin_id], separators=(",", ":")),
        "selected_coin_ids": [coin_id],
        "offer_text_sha256": hashlib.sha256(offer_text.encode("utf-8")).hexdigest(),
        "sage_trade_id": trade_id,
        "prepared_at": prepared_at,
        "confirmed_at": prepared_at,
        "fee_mojos_xch": candidate.get("fee_mojos_xch", 0),
        "coin_purpose": candidate.get("coin_purpose"),
    }


def recover_legacy_sage_reservations(
    *,
    wallet_fingerprint_hash: str,
    network: str,
    wallet_facade: Any = None,
    database_module: Any = None,
    reconciliation_module: Any = None,
    config: Any = None,
) -> dict[str, int]:
    """Adopt and expire exact legacy locks using fresh Sage evidence only."""

    wallet_hash = _hex_id(wallet_fingerprint_hash)
    if not wallet_hash or type(network) is not str or not network.strip():
        raise ValueError("legacy recovery wallet binding is invalid")
    safe_network = network.strip().lower()
    if database_module is None:
        import database as database_module
    if reconciliation_module is None:
        import offer_reconciliation as reconciliation_module
    if wallet_facade is None:
        import wallet as wallet_facade
    if config is None:
        from config import cfg as config
    decimals = getattr(config, "CAT_DECIMALS", None)
    if type(decimals) is not int or not 0 <= decimals <= 18:
        raise ValueError("legacy recovery CAT decimals are invalid")

    candidates = database_module.get_legacy_startup_reservation_candidates(limit=128)
    if type(candidates) is not list or len(candidates) > 128:
        raise RuntimeError("legacy reservation inventory is malformed")
    result = {"examined": len(candidates), "recovered": 0, "remaining": 0}
    wallet_identity = {
        "wallet_fingerprint_hash": wallet_hash,
        "network": safe_network,
    }

    for candidate in candidates:
        try:
            synthetic = _legacy_intent(candidate, wallet_hash, safe_network, decimals)
            intent_id = synthetic["intent_id"]
            existing = database_module.get_offer_intent(intent_id)
            evidence_target = (
                existing
                if type(existing) is dict
                and existing.get("lifecycle_state") in {"created", "unknown", "conflicted"}
                else synthetic
            )
            evidence = reconciliation_module.load_authoritative_evidence(
                evidence_target, wallet_facade=wallet_facade
            )
            observed_at = evidence.get("observed_at") if type(evidence) is dict else None
            classification = reconciliation_module.classify_terminal_evidence(
                evidence_target, evidence, now=observed_at
            )
            if (
                type(classification) is not dict
                or classification.get("classification")
                != reconciliation_module.EXPIRED_PROVEN
            ):
                result["remaining"] += 1
                continue

            if existing is None:
                database_module.prepare_offer_intent(
                    intent_id=intent_id,
                    operation_id=f"create:{intent_id}",
                    event_id=f"create:{intent_id}:prepared",
                    run_id=f"legacy-startup:{wallet_hash[:16]}",
                    wallet_fingerprint_hash=wallet_hash,
                    network=safe_network,
                    asset_id=synthetic["asset_id"],
                    side=synthetic["side"],
                    tier=synthetic["tier"],
                    purpose="legacy_startup_migration",
                    coin_purpose=synthetic["coin_purpose"],
                    offered_amount_atomic=synthetic["offered_amount_atomic"],
                    requested_amount_atomic=synthetic["requested_amount_atomic"],
                    selected_coin_ids_json=synthetic["selected_coin_ids"],
                    cat_decimals=decimals,
                    fee_mojos_xch=synthetic["fee_mojos_xch"],
                    fee_provenance="LEGACY_OFFER_PROJECTION_V1",
                    wallet_identity_json=wallet_identity,
                    evidence_json={
                        "migration": "legacy_startup_expiry",
                        "trade_id": synthetic["sage_trade_id"],
                    },
                    prepared_at=synthetic["prepared_at"],
                    reserve_selected_coins=False,
                    require_new_intent=False,
                )
                existing = database_module.get_offer_intent(intent_id)

            if type(existing) is dict and existing.get("lifecycle_state") == "prepared":
                database_module.finalize_offer_intent(
                    intent_id=intent_id,
                    operation_id=f"create:{intent_id}",
                    event_id=f"create:{intent_id}:finalized",
                    lifecycle_state="created",
                    outcome="CONFIRMED",
                    sage_trade_id=synthetic["sage_trade_id"],
                    offer_text_sha256=synthetic["offer_text_sha256"],
                    wallet_identity_json=wallet_identity,
                    evidence_json={
                        "migration": "legacy_startup_expiry",
                        "trade_id": synthetic["sage_trade_id"],
                    },
                    reason_code="LEGACY_OFFER_ADOPTED",
                    finalized_at=synthetic["confirmed_at"],
                    finalize_selected_coin_reservations=False,
                )

            reconciled = reconciliation_module.reconcile_offer(
                intent_id, evidence=evidence, now=observed_at
            )
            if (
                type(reconciled) is dict
                and reconciled.get("classification")
                == reconciliation_module.EXPIRED_PROVEN
                and reconciled.get("applied") is True
            ):
                result["recovered"] += 1
            else:
                result["remaining"] += 1
        except Exception:
            result["remaining"] += 1
    return result
