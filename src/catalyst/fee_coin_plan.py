"""Pure planning helpers for a week of dedicated transaction fee coins.

This module estimates fee-coin principal only. Its result is not fee consent,
dispatch authority, or a limit on actual network fees.
"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING


_MOJOS_PER_XCH = 1_000_000_000_000
_MIN_FEE_COIN_MOJOS = _MOJOS_PER_XCH // 1_000
_FEE_COIN_SIZE_STEP_MOJOS = 1_000_000
_MAX_FEE_OPERATIONS_PER_COIN = 10
_FEE_COIN_FEE_MULTIPLIER = 20
_DAYS_PER_WEEK = 7


def _nonnegative_rate(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("recent fee operations per day must be nonnegative")
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("recent fee operations per day must be nonnegative") from exc
    if not rate.is_finite() or rate < 0:
        raise ValueError("recent fee operations per day must be nonnegative")
    return rate


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def plan_weekly_fee_coins(
    estimated_fee_mojos: int,
    active_offer_target_count: int,
    recent_fee_operations_per_day=None,
    allocatable_xch_mojos: int = 0,
) -> dict:
    """Plan fee-coin principal for seven days without exceeding allocation.

    The model assumes at least two network-fee operations per active offer
    slot per day, plus two operations per slot for startup and shutdown. Recent
    observed activity can raise the daily rate. One fee coin is modeled to
    serve at most ten fee operations.
    """
    if (
        type(estimated_fee_mojos) is not int
        or estimated_fee_mojos <= 0
        or type(active_offer_target_count) is not int
        or active_offer_target_count <= 0
        or type(allocatable_xch_mojos) is not int
        or allocatable_xch_mojos < 0
    ):
        raise ValueError("fee estimate, offer count, or allocation is invalid")

    slots = active_offer_target_count
    baseline_operations_per_day = 2 * slots
    if recent_fee_operations_per_day is None:
        daily_operations = baseline_operations_per_day
    else:
        observed_daily = int(
            _nonnegative_rate(recent_fee_operations_per_day).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        daily_operations = max(baseline_operations_per_day, observed_daily)

    modeled_operation_count = daily_operations * _DAYS_PER_WEEK + 2 * slots
    target_fee_coin_count = _ceil_div(
        modeled_operation_count, _MAX_FEE_OPERATIONS_PER_COIN
    )

    raw_size = max(
        _MIN_FEE_COIN_MOJOS,
        estimated_fee_mojos * _FEE_COIN_FEE_MULTIPLIER,
    )
    fee_coin_size_mojos = (
        _ceil_div(raw_size, _FEE_COIN_SIZE_STEP_MOJOS) * _FEE_COIN_SIZE_STEP_MOJOS
    )
    target_principal = target_fee_coin_count * fee_coin_size_mojos
    fee_coin_count = min(
        target_fee_coin_count,
        allocatable_xch_mojos // fee_coin_size_mojos,
    )
    principal = fee_coin_count * fee_coin_size_mojos

    return {
        "fee_coin_size_mojos": fee_coin_size_mojos,
        "fee_coin_count": fee_coin_count,
        "target_fee_coin_count": target_fee_coin_count,
        "fee_coin_principal_mojos": principal,
        "target_fee_coin_principal_mojos": target_principal,
        "modeled_operation_count": modeled_operation_count,
        "underfunded": fee_coin_count < target_fee_coin_count,
    }
