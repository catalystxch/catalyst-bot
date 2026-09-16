"""Strict, cost-specific network fee quotes; unavailable is never a zero fee."""

import time
from decimal import Decimal, InvalidOperation, ROUND_CEILING

MAX_ATOMIC_AMOUNT = 2**63 - 1
QUOTE_MAX_AGE_SECONDS = 60


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_ATOMIC_AMOUNT


def normalize_fee_response(response, *, cost, target_seconds, source, observed_at, now):
    """Validate a provider response without manufacturing missing fee guidance.

    Observation time belongs to the network response, not a cache retrieval.
    Optional request echoes must match exactly if the provider supplies them.
    """
    result = {
        "available": False,
        "reason": "invalid_fee_quote_request",
        "source": source,
        "cost": cost,
        "target_seconds": target_seconds,
        "fee_mojos": None,
        "fee_xch": None,
        "observed_at": observed_at,
        "expires_at": None,
    }
    if not (
        _integer(cost, 1)
        and _integer(target_seconds)
        and _integer(observed_at)
        and _integer(now)
        and source in ("coinset", "full_node_rpc")
    ):
        return result
    result["expires_at"] = observed_at + QUOTE_MAX_AGE_SECONDS
    if not 0 <= now - observed_at < QUOTE_MAX_AGE_SECONDS:
        result["reason"] = "stale_or_future_fee_quote"
        return result
    result["reason"] = "invalid_fee_response"
    if not isinstance(response, dict) or response.get("success") is not True:
        return result
    if "cost" in response and (
        not _integer(response["cost"], 1) or response["cost"] != cost
    ):
        return result
    if "target_times" in response:
        targets = response["target_times"]
        if not (
            isinstance(targets, list)
            and len(targets) == 1
            and _integer(targets[0])
            and targets[0] == target_seconds
        ):
            return result
    estimates = response.get("estimates")
    if not isinstance(estimates, list) or len(estimates) != 1:
        return result
    value = estimates[0]
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return result
    try:
        estimate = Decimal(str(value))
        if not estimate.is_finite() or not 0 <= estimate <= MAX_ATOMIC_AMOUNT:
            return result
        fee = int(estimate.to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, OverflowError):
        return result
    result.update(
        available=True,
        reason="network_fee_estimate",
        fee_mojos=fee,
        fee_xch=format(Decimal(fee) / Decimal(10**12), "f"),
    )
    return result


def quote_fee(cost: int, target_seconds: int = 300) -> dict:
    """Get configured network guidance, retaining its original observation time.

    This read-only quote does not authorize a wallet effect or a manual fallback.
    Revalidate the raw provider response rather than trusting a derived cache fee.
    """
    now = int(time.time())
    invalid = normalize_fee_response(
        None,
        cost=cost,
        target_seconds=target_seconds,
        source="full_node_rpc",
        observed_at=now,
        now=now,
    )
    if not _integer(cost, 1) or not _integer(target_seconds):
        return invalid
    from tx_fees import get_suggested_transaction_fee

    snapshot = get_suggested_transaction_fee(cost=cost, target_seconds=target_seconds)
    now = int(time.time())
    return normalize_fee_response(
        snapshot.get("raw") if snapshot.get("available") is True else None,
        cost=cost,
        target_seconds=target_seconds,
        source=snapshot.get("source"),
        observed_at=snapshot.get("observed_at"),
        now=now,
    )
