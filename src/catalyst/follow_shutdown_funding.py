"""Read-only one-block shutdown fee envelope for a proposed Follow run.

This is a funding screen, not a quote for offers that do not yet exist. Sage
must price the exact live book before cancellation; a book that cannot fit in
one block also needs a separate, proven multi-cohort shutdown path.
"""

from __future__ import annotations

from coin_prep_fee_pricing import is_current_fee_quote
from fee_estimation import quote_fee


ONE_BLOCK_COST_LIMIT = 11_000_000_000


def preview_one_block_shutdown_funding(
    *,
    maximum_fee_mojos: int,
    spent_fee_mojos: int,
    held_fee_mojos: int,
    largest_fee_coin_mojos: int,
    protected_shutdown_fee_mojos: int,
    target_seconds: int,
) -> dict:
    """Require both ceiling headroom and one independently spendable fee coin.

    The full-book executable cost is unknown until offers exist. ``ready``
    certifies only this conservative one-block funding screen; callers must
    separately prove the actual book, fee coin and cohort structure.
    """
    amounts = (
        maximum_fee_mojos,
        spent_fee_mojos,
        held_fee_mojos,
        largest_fee_coin_mojos,
        protected_shutdown_fee_mojos,
    )
    if (
        any(type(value) is not int or value < 0 for value in amounts)
        or maximum_fee_mojos == 0
        or type(target_seconds) is not int
        or target_seconds < 1
    ):
        raise ValueError("FOLLOW_SHUTDOWN_FUNDING_INPUT_INVALID")
    remaining = maximum_fee_mojos - spent_fee_mojos - held_fee_mojos
    result = {
        "ready": False,
        "reason": "FOLLOW_SHUTDOWN_FEE_ESTIMATE_UNAVAILABLE",
        "cost_mojos": ONE_BLOCK_COST_LIMIT,
        "quoted_fee_mojos": None,
        "remaining_fee_mojos": remaining,
        "largest_fee_coin_mojos": largest_fee_coin_mojos,
        "protected_shutdown_fee_mojos": protected_shutdown_fee_mojos,
        "full_book_proven": False,
        "dispatch_authorized": False,
    }
    try:
        quote = quote_fee(ONE_BLOCK_COST_LIMIT, target_seconds=target_seconds)
    except Exception:
        return result
    if not is_current_fee_quote(quote, ONE_BLOCK_COST_LIMIT, target_seconds):
        return result
    fee = quote["fee_mojos"]
    result["quoted_fee_mojos"] = fee
    result["observed_at"] = quote["observed_at"]
    result["expires_at"] = quote["expires_at"]
    if fee <= 0:
        result["reason"] = "FOLLOW_SHUTDOWN_FEE_FUNDING_REQUIRED"
    elif fee > remaining:
        result["reason"] = "FOLLOW_SHUTDOWN_FEE_CAP_INSUFFICIENT"
    elif fee > protected_shutdown_fee_mojos:
        result["reason"] = "FOLLOW_SHUTDOWN_RESERVE_INSUFFICIENT"
    elif fee > largest_fee_coin_mojos:
        result["reason"] = "FOLLOW_SHUTDOWN_FEE_COIN_TOO_SMALL"
    else:
        result["ready"] = True
        result["reason"] = "one_block_funding_screen_passed"
    return result
