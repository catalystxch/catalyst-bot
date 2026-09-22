"""Exact protected pricing for cancellation caused by the Coin Prep workflow.

This module is read-only.  An available result remains incapable of signing or
submitting until the offer journal and database reservation boundary accept the
same approval, quote, selected roots and sealed unsigned bundle.
"""

import re

import database
from coin_prep_fee_pricing import is_current_fee_quote
from coin_prep_fee_runtime import read_approved_prep_fee_snapshot
from fee_estimation import quote_fee
import wallet


_HEX_64 = re.compile(r"[0-9a-f]{64}")
_CONTEXT_KEYS = (
    "identity",
    "configuration",
    "receive_address",
    "recipe",
    "campaign",
    "scope",
)


def _unavailable(context, reason, **details):
    return {
        "available": False,
        "reason": reason,
        "approval": context["approval"],
        "dispatch_authorized": False,
        **details,
    }


def _canonical_ids(values, *, minimum=1):
    if type(values) is not list or len(values) < minimum:
        raise ValueError("FEE_CANCELLATION_PLAN_INVALID")
    normalized = []
    for value in values:
        if type(value) is not str:
            raise ValueError("FEE_CANCELLATION_PLAN_INVALID")
        item = value.strip().lower().removeprefix("0x")
        if not _HEX_64.fullmatch(item):
            raise ValueError("FEE_CANCELLATION_PLAN_INVALID")
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise ValueError("FEE_CANCELLATION_PLAN_INVALID")
    return normalized


def price_approved_cancellation(
    *,
    approval_id: str,
    trade_ids: list,
    source_coin_ids: list,
    fee_coin_id: str,
) -> dict:
    """Converge a cancellation fee against the actual Sage unsigned bundle."""

    trades = _canonical_ids(trade_ids)
    sources = _canonical_ids(source_coin_ids)
    fee_ids = _canonical_ids([fee_coin_id])
    if len(trades) != len(sources) or fee_ids[0] in set(sources):
        raise ValueError("FEE_CANCELLATION_PLAN_INVALID")

    accounting = database.get_coin_prep_fee_approval_status(approval_id)
    if accounting["unresolved_operation_count"]:
        context = {"approval": accounting}
        return _unavailable(context, "FEE_EFFECT_RECOVERY_REQUIRED")
    context = read_approved_prep_fee_snapshot(approval_id)
    target_seconds = context["recipe"]["economic_plan"]["target_seconds"]
    fee = 0
    for _round in range(4):
        built = wallet.build_cancel_offers_batch_unsigned(
            trades,
            fee_mojos=fee,
            source_coin_ids=sources,
            fee_coin_id=fee_ids[0],
        )
        cost = (
            built.get("_catalyst_exact_unsigned_cost")
            if type(built) is dict
            and built.get("_catalyst_validated_cancel_unsigned") is True
            else None
        )
        if type(cost) is not int or isinstance(cost, bool) or cost <= 0:
            return _unavailable(context, "FEE_UNSIGNED_COST_UNAVAILABLE")
        try:
            quote = quote_fee(cost, target_seconds=target_seconds)
        except Exception:
            return _unavailable(context, "FEE_ESTIMATE_UNAVAILABLE")
        if not is_current_fee_quote(quote, cost, target_seconds):
            return _unavailable(context, "FEE_ESTIMATE_UNAVAILABLE")
        if quote["fee_mojos"] == fee:
            after = read_approved_prep_fee_snapshot(approval_id)
            if any(after[key] != context[key] for key in _CONTEXT_KEYS):
                raise ValueError("FEE_APPROVAL_STALE")
            if fee > after["approval"]["remaining_fee_mojos"]:
                return _unavailable(
                    after,
                    "FEE_BUDGET_EXCEEDED",
                    required_fee_mojos=fee,
                )
            return {
                **after,
                "available": True,
                "reason": "cost_fee_consistent",
                "trade_ids": trades,
                "source_coin_ids": sources,
                "fee_coin_id": fee_ids[0],
                "fee_mojos": fee,
                "cost": cost,
                "quote": quote,
                "validated_unsigned": built,
                "dispatch_authorized": False,
            }
        fee = quote["fee_mojos"]
    return _unavailable(context, "FEE_PRICING_NOT_CONVERGED")


def reserve_approved_cancellation(
    *,
    approval_id: str,
    manifest: dict,
    priced_cancellation: dict,
) -> dict:
    """Bind the sealed cancellation and exact quote to its PREPARED cohort."""

    if (
        type(priced_cancellation) is not dict
        or priced_cancellation.get("available") is not True
        or priced_cancellation.get("approval", {}).get("approval_id") != approval_id
    ):
        raise ValueError("FEE_CANCELLATION_PLAN_INVALID")
    context = read_approved_prep_fee_snapshot(approval_id)
    if any(
        priced_cancellation.get(key) != context[key] for key in _CONTEXT_KEYS
    ):
        raise ValueError("FEE_APPROVAL_STALE")
    unsigned = priced_cancellation.get("validated_unsigned")
    cost = priced_cancellation.get("cost")
    quote = priced_cancellation.get("quote")
    if (
        type(unsigned) is not dict
        or unsigned.get("_catalyst_validated_cancel_unsigned") is not True
        or unsigned.get("_catalyst_exact_unsigned_cost") != cost
        or not is_current_fee_quote(
            quote,
            cost,
            context["recipe"]["economic_plan"]["target_seconds"],
        )
        or quote["fee_mojos"] != priced_cancellation.get("fee_mojos")
    ):
        raise ValueError("FEE_ESTIMATE_UNAVAILABLE")
    contract = {
        "protocol": "sage_native_cancel_offers_zero_plus_fee_v1",
        "trade_ids": list(priced_cancellation["trade_ids"]),
        "source_coin_ids": list(priced_cancellation["source_coin_ids"]),
        "fee_coin_id": priced_cancellation["fee_coin_id"],
        "fee_mojos": priced_cancellation["fee_mojos"],
    }
    hold = database.reserve_coin_prep_cancellation_fee(
        approval_id=approval_id,
        scope_sha256=context["approval"]["scope_sha256"],
        plan_sha256=context["approval"]["plan_sha256"],
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=quote,
    )
    return {
        **hold,
        "batch_contract": contract,
        "validated_unsigned": unsigned,
        "dispatch_authorized": False,
    }


def recheck_reserved_approved_cancellation(
    *,
    approval_id: str,
    manifest: dict,
    priced_cancellation: dict,
) -> dict:
    """Revalidate the sealed hold immediately before the effect claim.

    This remains read-only and returns no signing authority.  The subsequent
    durable cohort claim is still the one wallet-effect fence.
    """

    if (
        type(priced_cancellation) is not dict
        or priced_cancellation.get("available") is not True
        or priced_cancellation.get("approval", {}).get("approval_id") != approval_id
    ):
        raise ValueError("FEE_CANCELLATION_PLAN_INVALID")
    context = read_approved_prep_fee_snapshot(approval_id)
    if any(priced_cancellation.get(key) != context[key] for key in _CONTEXT_KEYS):
        raise ValueError("FEE_APPROVAL_STALE")
    quote = priced_cancellation.get("quote")
    cost = priced_cancellation.get("cost")
    unsigned = priced_cancellation.get("validated_unsigned")
    if (
        type(unsigned) is not dict
        or unsigned.get("_catalyst_validated_cancel_unsigned") is not True
        or unsigned.get("_catalyst_exact_unsigned_cost") != cost
        or not is_current_fee_quote(
            quote,
            cost,
            context["recipe"]["economic_plan"]["target_seconds"],
        )
        or quote["fee_mojos"] != priced_cancellation.get("fee_mojos")
    ):
        raise ValueError("FEE_ESTIMATE_UNAVAILABLE")
    hold = database.get_coin_prep_cancellation_fee_hold(manifest)
    if (
        hold["approval_id"] != approval_id
        or hold["scope_sha256"] != context["approval"]["scope_sha256"]
        or hold["plan_sha256"] != context["approval"]["plan_sha256"]
        or hold["fee_mojos"] != priced_cancellation["fee_mojos"]
    ):
        raise ValueError("FEE_APPROVAL_STALE")
    return {**hold, "dispatch_authorized": False}
