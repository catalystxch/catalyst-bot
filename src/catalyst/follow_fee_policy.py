"""Pure per-transaction fee selection for an approved run policy.

This helper selects an amount and reports when the approved maximum is below
fresh network guidance. It does not approve or dispatch a wallet effect.
"""

MAX_ATOMIC_AMOUNT = 2**63 - 1


def _positive_mojos(value):
    return type(value) is int and 0 < value <= MAX_ATOMIC_AMOUNT


def select_transaction_fee(
    *, recommended_fee_mojos: int, maximum_fee_per_transaction_mojos: int
) -> dict:
    """Select a positive fee within the cap and flag insufficient cap headroom.

    ``recommended_fee_mojos`` must come from a fresh quote supplied by the
    caller. When it exceeds the cap, the selected amount is the cap (a
    lower-fee attempt may proceed under caller policy) and ``raise_cap_needed``
    tells the caller that the approved maximum does not cover the recommendation.
    The result is advisory and carries no wallet-dispatch authority.
    """
    if not _positive_mojos(recommended_fee_mojos) or not _positive_mojos(
        maximum_fee_per_transaction_mojos
    ):
        raise ValueError("invalid_fee_policy_amount")

    exceeds_cap = recommended_fee_mojos > maximum_fee_per_transaction_mojos
    return {
        "fee_mojos": min(recommended_fee_mojos, maximum_fee_per_transaction_mojos),
        "raise_cap_needed": exceeds_cap,
        "reason": "FEE_CAP_BELOW_RECOMMENDATION" if exceeds_cap else None,
    }
