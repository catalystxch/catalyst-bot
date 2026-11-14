"""Prepare one durable, human-readable fee-prep replacement review.

The caller derives the operation and original transaction IDs from server-side
recovery state. This service builds unsigned evidence and records a review only;
it never signs or submits a wallet effect.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from coin_prep_rbf_pricing import price_pending_coin_prep_replacement
from database import (
    get_coin_prep_rbf_preview_authority,
    prepare_coin_prep_rbf_attempt,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hex_id(value: Any) -> str:
    if type(value) is not str:
        raise ValueError("invalid RBF identity")
    canonical = value.lower().removeprefix("0x")
    if re.fullmatch(r"[0-9a-f]{64}", canonical) is None:
        raise ValueError("invalid RBF identity")
    return canonical


def _outputs(value: Any) -> list[dict]:
    if type(value) is not list or len(value) != 5:
        raise ValueError("RBF review requires five outputs")
    result = []
    for item in value:
        if type(item) is not dict:
            raise ValueError("RBF review output is malformed")
        coin_id = _hex_id(item.get("coin_id"))
        amount = item.get("amount_mojos")
        purpose = item.get("purpose")
        if (
            type(amount) is not int
            or amount <= 0
            or purpose not in {"fee_reserve", "top_up"}
        ):
            raise ValueError("RBF review output is malformed")
        result.append({"coin_id": coin_id, "amount_mojos": amount, "purpose": purpose})
    if len({item["coin_id"] for item in result}) != 5:
        raise ValueError("RBF review output IDs are duplicated")
    if sorted(item["purpose"] for item in result) != [
        "fee_reserve",
        "fee_reserve",
        "fee_reserve",
        "fee_reserve",
        "top_up",
    ]:
        raise ValueError("RBF review output purposes are malformed")
    return sorted(result, key=lambda item: item["coin_id"])


def _timestamp(epoch_seconds: int) -> str:
    return (
        datetime.fromtimestamp(epoch_seconds, timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def prepare_coin_prep_rbf_review(
    operation_id: str, original_transaction_id: str
) -> dict:
    """Price and seal one server-selected pending fee-prep replacement."""

    def refuse(reason: str) -> dict:
        return {"available": False, "reason": reason, "dispatch_authorized": False}

    try:
        if (
            type(operation_id) is not str
            or re.fullmatch(r"coin-prep:[0-9a-f]{64}", operation_id) is None
        ):
            return refuse("RBF_REVIEW_OPERATION_INVALID")
        original_tx = _hex_id(original_transaction_id)
        priced = price_pending_coin_prep_replacement(operation_id, original_tx)
        if type(priced) is not dict or priced.get("available") is not True:
            reason = priced.get("reason") if type(priced) is dict else None
            return refuse(
                reason
                if type(reason) is str and reason
                else "RBF_REVIEW_PRICING_UNAVAILABLE"
            )
        preview = priced["preview"]
        if (
            type(preview) is not dict
            or preview.get("success") is not True
            or preview.get("operation_id") != operation_id
            or _hex_id(preview.get("original_transaction_id")) != original_tx
        ):
            return refuse("RBF_REVIEW_PREVIEW_MISMATCH")
        unsigned = preview["unsigned"]
        digest = _hex_id(unsigned.get("_catalyst_unsigned_digest"))
        if unsigned.get("_catalyst_executable_effect_bound") is not True:
            return refuse("RBF_REVIEW_UNSIGNED_UNVERIFIED")
        fee = priced["fee_mojos"]
        cost = priced["cost"]
        if (
            type(fee) is not int
            or fee < 10_000_000
            or type(cost) is not int
            or cost <= 0
            or preview.get("fee_mojos") != fee
            or unsigned.get("_catalyst_exact_unsigned_cost") != cost
        ):
            return refuse("RBF_REVIEW_COST_OR_FEE_MISMATCH")
        original = _outputs(preview["original_outputs"])
        successor = _outputs(preview["successor_outputs"])
        old_reserves = sorted(
            item["amount_mojos"]
            for item in original
            if item["purpose"] == "fee_reserve"
        )
        new_reserves = sorted(
            item["amount_mojos"]
            for item in successor
            if item["purpose"] == "fee_reserve"
        )
        old_change = next(
            item["amount_mojos"] for item in original if item["purpose"] == "top_up"
        )
        new_change = next(
            item["amount_mojos"] for item in successor if item["purpose"] == "top_up"
        )
        if old_reserves != new_reserves or old_change - new_change != fee:
            return refuse("RBF_REVIEW_NOT_FEE_ONLY")
        quote = priced["quote"]
        if type(quote) is not dict or quote.get("available") is not True:
            return refuse("RBF_REVIEW_QUOTE_UNAVAILABLE")
        observed = quote.get("observed_at")
        expires = quote.get("expires_at")
        if (
            type(observed) is not int
            or type(expires) is not int
            or type(quote.get("fee_mojos")) is not int
            or quote.get("source") not in {"coinset", "full_node_rpc"}
            or type(quote.get("target_seconds")) is not int
            or not 1 <= quote["target_seconds"] <= 86_400
            or quote.get("cost") != cost
            or expires <= observed
        ):
            return refuse("RBF_REVIEW_QUOTE_INVALID")
        now = int(datetime.now(timezone.utc).timestamp())
        if not observed <= now < expires:
            return refuse("RBF_REVIEW_QUOTE_EXPIRED")
        authority = get_coin_prep_rbf_preview_authority(operation_id)
        latch = authority["latch"]
        generation = latch["generation"]
        if type(generation) is not int or generation < 1:
            return refuse("RBF_REVIEW_LATCH_INVALID")
        review = {
            "schema_version": 1,
            "operation_id": operation_id,
            "original_transaction_id": original_tx,
            "unsigned_sha256": digest,
            "latch_generation": generation,
            "fee_mojos": fee,
            "fee_xch": format(Decimal(fee) / Decimal(10**12), "f"),
            "cost": cost,
            "original_outputs": original,
            "successor_outputs": successor,
            "quote": {
                "source": quote.get("source"),
                "target_seconds": quote.get("target_seconds"),
                "fee_mojos": quote["fee_mojos"],
                "observed_at": observed,
                "expires_at": expires,
            },
            "review_expires_at": _timestamp(expires),
        }
        review_sha256 = hashlib.sha256(_canonical_json(review).encode()).hexdigest()
        prepared = prepare_coin_prep_rbf_attempt(
            operation_id=operation_id,
            original_transaction_id=original_tx,
            unsigned_sha256=digest,
            review_sha256=review_sha256,
            fee_mojos=fee,
            original_outputs=original,
            successor_outputs=successor,
            latch_generation=generation,
            reviewed_at=_timestamp(now),
            review_expires_at=review["review_expires_at"],
        )
        attempt = prepared["attempt"]
        if (
            attempt["review_sha256"] != review_sha256
            or attempt["unsigned_sha256"] != digest
            or attempt["operation_id"] != operation_id
        ):
            return refuse("RBF_REVIEW_RECORD_MISMATCH")
        if int(datetime.now(timezone.utc).timestamp()) >= expires:
            return refuse("RBF_REVIEW_QUOTE_EXPIRED")
        return {
            "available": True,
            "reason": "review_prepared",
            "attempt_id": attempt["attempt_id"],
            "review_sha256": review_sha256,
            "review": review,
            "dispatch_authorized": False,
        }
    except Exception:
        return refuse("RBF_REVIEW_UNAVAILABLE")
