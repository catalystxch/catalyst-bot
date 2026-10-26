"""Read-only exact cancellation pricing for one reviewed Follow run.

An available price is evidence only. The durable cohort journal, atomic fee
hold, final adapter callback and terminal outcome must still authorize any
wallet effect. This module never signs, submits or reserves a fee.
"""

from __future__ import annotations

import database
from coin_prep_fee_cancellation import _canonical_ids
from coin_prep_fee_pricing import is_current_fee_quote
from fee_estimation import quote_fee
import wallet


def _refused(reason: str, authority: dict, **details) -> dict:
    return {
        "available": False,
        "reason": reason,
        "authority": authority,
        "dispatch_authorized": False,
        **details,
    }


def price_follow_cancellation(
    *,
    run_id: str,
    identity: dict,
    trade_ids: list,
    source_coin_ids: list,
    fee_coin_id: str,
    now_epoch: int,
) -> dict:
    """Converge a Sage unsigned cancellation against the effective run cap."""
    trades = _canonical_ids(trade_ids)
    sources = _canonical_ids(source_coin_ids)
    fee_coins = _canonical_ids([fee_coin_id])
    if len(trades) != len(sources) or fee_coins[0] in set(sources):
        raise ValueError("FEE_CANCELLATION_PLAN_INVALID")
    authority = database.get_effective_follow_fee_policy(
        run_id=run_id, identity=identity, now_epoch=now_epoch
    )
    if authority.get("ready") is not True:
        return _refused(
            str(authority.get("reason_code") or "FOLLOW_AUTHORITY_REQUIRED"),
            authority,
        )
    target_seconds = authority.get("target_seconds")
    if type(target_seconds) is not int or target_seconds < 1:
        return _refused("FOLLOW_FEE_APPROVAL_MISMATCH", authority)

    fee = 0
    for _round in range(4):
        built = wallet.build_cancel_offers_batch_unsigned(
            trades,
            fee_mojos=fee,
            source_coin_ids=sources,
            fee_coin_id=fee_coins[0],
        )
        cost = (
            built.get("_catalyst_exact_unsigned_cost")
            if type(built) is dict
            and built.get("_catalyst_validated_cancel_unsigned") is True
            else None
        )
        if type(cost) is not int or cost <= 0:
            return _refused("FEE_UNSIGNED_COST_UNAVAILABLE", authority)
        try:
            quote = quote_fee(cost, target_seconds=target_seconds)
        except Exception:
            return _refused("FEE_ESTIMATE_UNAVAILABLE", authority)
        if not is_current_fee_quote(quote, cost, target_seconds):
            return _refused("FEE_ESTIMATE_UNAVAILABLE", authority)
        quoted_fee = quote["fee_mojos"]
        if quoted_fee == fee:
            if fee == 0:
                return _refused("FEE_CANCELLATION_FUNDING_REQUIRED", authority)
            after = database.get_effective_follow_fee_policy(
                run_id=run_id, identity=identity, now_epoch=now_epoch
            )
            if after.get("ready") is not True or after != authority:
                return _refused("FOLLOW_FEE_APPROVAL_STALE", after)
            if fee > after["remaining_fee_mojos"]:
                return _refused("FEE_BUDGET_EXCEEDED", after, required_fee_mojos=fee)
            return {
                "available": True,
                "reason": "cost_fee_consistent",
                "authority": after,
                "trade_ids": trades,
                "source_coin_ids": sources,
                "fee_coin_id": fee_coins[0],
                "fee_mojos": fee,
                "cost": cost,
                "quote": quote,
                "validated_unsigned": built,
                "dispatch_authorized": False,
            }
        fee = quoted_fee
    return _refused("FEE_PRICING_NOT_CONVERGED", authority)
