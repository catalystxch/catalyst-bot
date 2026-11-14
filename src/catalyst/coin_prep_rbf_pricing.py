"""Read-only, cost-specific pricing for one pending Coin Prep replacement."""

from __future__ import annotations

from config import cfg
from coin_prep_fee_pricing import is_current_fee_quote
from fee_estimation import quote_fee
from tx_fees import get_suggested_transaction_fee
from wallet import preview_coin_prep_rbf_unsigned


_MIN_RBF_BUMP_MOJOS = 10_000_000
_MAX_ROUNDS = 4


def quote_required_replacement_fee(cost: int) -> dict:
    """Return a fresh floor for this exact executable cost and mempool view."""
    target_seconds = int(getattr(cfg, "TRANSACTION_FEE_TARGET_SECS", 300) or 300)
    if type(cost) is not int or cost <= 0 or not 1 <= target_seconds <= 86_400:
        return {"available": False, "reason": "RBF_FEE_TARGET_INVALID"}
    try:
        quote = quote_fee(cost, target_seconds=target_seconds, force_refresh=True)
    except Exception:
        return {"available": False, "reason": "RBF_FEE_ESTIMATE_UNAVAILABLE"}
    if not is_current_fee_quote(quote, cost, target_seconds):
        return {"available": False, "reason": "RBF_FEE_ESTIMATE_UNAVAILABLE"}
    estimated = quote.get("fee_mojos")
    if type(estimated) is not int or estimated < 0:
        return {"available": False, "reason": "RBF_FEE_ESTIMATE_INVALID"}
    # The normalized quote omits the provider's maximum. Read the cached
    # original only if it is the exact same observation.
    provider = get_suggested_transaction_fee(cost=cost, target_seconds=target_seconds)
    same_observation = (
        provider.get("available") is True
        and provider.get("observed_at") == quote.get("observed_at")
        and provider.get("cost") == cost
        and provider.get("target_seconds") == target_seconds
    )
    raw = (provider.get("raw") or {}) if same_observation else {}
    mempool_cost = raw.get("mempool_size")
    mempool_max = raw.get("mempool_max_size")
    if (
        type(mempool_cost) is not int
        or type(mempool_max) is not int
        or mempool_cost < 0
        or mempool_max <= 0
    ):
        return {"available": False, "reason": "RBF_MEMPOOL_CAPACITY_UNKNOWN"}
    full_for_candidate = mempool_cost + cost > mempool_max
    minimum = max(
        _MIN_RBF_BUMP_MOJOS,
        (estimated * 11 + 9) // 10,
        5 * cost + 1 if full_for_candidate else 0,
    )
    return {
        "available": True,
        "minimum_fee_mojos": minimum,
        "quote": quote,
        "full_for_candidate": full_for_candidate,
    }


def price_pending_coin_prep_replacement(
    operation_id: str, original_transaction_id: str
) -> dict:
    """Build only unsigned candidates until fee and executable cost agree.

    A successful result is a review candidate. It is never submission authority.
    The fee quote is guidance from a remote full node and must be rechecked at
    the eventual sign/submit boundary.
    """
    fee = _MIN_RBF_BUMP_MOJOS
    for _ in range(_MAX_ROUNDS):
        candidate = preview_coin_prep_rbf_unsigned(
            operation_id, original_transaction_id, fee
        )
        if candidate.get("success") is not True:
            return {
                "available": False,
                "reason": candidate.get("reason") or "RBF_UNSIGNED_PREVIEW_UNAVAILABLE",
            }
        unsigned = candidate.get("unsigned") or {}
        cost = unsigned.get("_catalyst_exact_unsigned_cost")
        if type(cost) is not int or cost <= 0:
            return {"available": False, "reason": "RBF_UNSIGNED_COST_UNAVAILABLE"}
        guidance = quote_required_replacement_fee(cost)
        if guidance.get("available") is not True:
            return guidance
        minimum = guidance["minimum_fee_mojos"]
        if fee >= minimum:
            return {
                "available": True,
                "reason": "unsigned_candidate_priced",
                "operation_id": operation_id,
                "original_transaction_id": original_transaction_id,
                "fee_mojos": fee,
                "cost": cost,
                "quote": guidance["quote"],
                "preview": candidate,
                "dispatch_authorized": False,
            }
        fee = minimum
    return {"available": False, "reason": "RBF_FEE_PRICING_NOT_CONVERGED"}
