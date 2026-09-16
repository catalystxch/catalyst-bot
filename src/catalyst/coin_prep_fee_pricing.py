"""Read-only exact next-batch fee/cost convergence shared by preview and dispatch.

No fee hold, effect claim, signing or submission occurs here. An available result
is cost/effect inspection evidence, never permission to dispatch. Live callers
must revalidate identity/inventory and enforce durable consent and journal fencing.
"""

import time

from coin_prep_batch_plan import BatchConstraints, BatchRefusal, plan_batch
from coin_prep_targets import MAX_ATOMIC_AMOUNT
from coin_prep_unsigned import inspect_batch_unsigned
from fee_estimation import QUOTE_MAX_AGE_SECONDS, quote_fee


def _now():
    return int(time.time())


def _integer(value, minimum=0, maximum=MAX_ATOMIC_AMOUNT):
    return type(value) is int and minimum <= value <= maximum


def is_current_fee_quote(quote, cost, target_seconds):
    """Recheck original provenance/age without renewing a cached quote."""
    if type(quote) is not dict or quote.get("available") is not True:
        return False
    observed = quote.get("observed_at")
    expires = quote.get("expires_at")
    return (
        _integer(quote.get("cost"), 1) and quote["cost"] == cost
        and _integer(quote.get("target_seconds"), 1) and quote["target_seconds"] == target_seconds
        and _integer(quote.get("fee_mojos"))
        and quote.get("source") in ("coinset", "full_node_rpc")
        and _integer(observed) and _integer(expires)
        and expires == observed + QUOTE_MAX_AGE_SECONDS
        and observed <= _now() < expires
    )


def _unavailable(reason):
    return {"available": False, "reason": reason, "dispatch_authorized": False}


def price_next_prep_batch(*, snapshot, targets, reserve_floors, receive_address,
                          cat_asset_id, target_seconds=300):
    """Rebuild until the exact effect's fee matches its fresh cost-specific quote.

    Four bounded rounds permit fee-induced changes to inputs/change/cost; an
    oscillating or unavailable estimate stops without exposing a usable bundle.
    Economic targets and reserve floors remain unchanged throughout repricing.
    """
    if (not _integer(target_seconds, 1, 86_400) or type(reserve_floors) is not dict
            or set(reserve_floors) != {"xch", "cat"}
            or not all(_integer(value) for value in reserve_floors.values())):
        raise ValueError("FEE_PRICING_CONSTRAINTS_INVALID")
    fee = 0
    for _round in range(4):
        plan = plan_batch(snapshot, targets, BatchConstraints(reserve_floors, fee))
        if type(plan) is BatchRefusal:
            return _unavailable(plan.code)
        if plan.transaction_required is False:
            return {"available": True, "reason": "targets_already_prepared", "plan": plan,
                    "transaction_required": False, "dispatch_authorized": False}
        try:
            inspection = inspect_batch_unsigned(plan, receive_address, cat_asset_id)
        except Exception:
            return _unavailable("FEE_UNSIGNED_COST_UNAVAILABLE")
        if (type(inspection) is not dict or inspection.get("available") is not True
                or not _integer(inspection.get("cost"), 1)):
            reason = inspection.get("reason") if type(inspection) is dict else None
            if _round == 0 and fee == 0 and reason == "DUPLICATE_OUTPUT_ID":
                # Change equal to a target produces the same destination coin ID.
                # A one-mojo unsigned-only seed lets us request actual guidance;
                # it is never an approved/dispatched fee floor. A final zero
                # quote that remains unbuildable still refuses below.
                fee = 1
                continue
            return _unavailable(reason if type(reason) is str else "FEE_UNSIGNED_COST_UNAVAILABLE")
        try:
            quote = quote_fee(inspection["cost"], target_seconds=target_seconds)
        except Exception:
            return _unavailable("FEE_ESTIMATE_UNAVAILABLE")
        if not is_current_fee_quote(quote, inspection["cost"], target_seconds):
            return _unavailable("FEE_ESTIMATE_UNAVAILABLE")
        if quote["fee_mojos"] == fee:
            return {"available": True, "reason": "cost_fee_consistent", "plan": plan,
                    "inspection": inspection, "quote": quote,
                    "transaction_required": True, "dispatch_authorized": False}
        fee = quote["fee_mojos"]
    return _unavailable("FEE_PRICING_NOT_CONVERGED")
