"""Strict, cost-specific network fee quotes; unavailable is never a zero fee."""

import time
from decimal import Decimal, InvalidOperation, ROUND_CEILING

MAX_ATOMIC_AMOUNT = 2**63 - 1
QUOTE_MAX_AGE_SECONDS = 60
_FAILURE_REASONS = frozenset({
    "invalid_fee_quote_request", "stale_or_future_fee_quote", "invalid_fee_response",
    "invalid_network_evidence", "fee_provider_unsynced", "fee_provider_unavailable",
    "fee_provider_disabled", "fee_provider_not_configured", "fee_provider_rate_limited",
    "fee_provider_http_error",
})


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_ATOMIC_AMOUNT


def fee_failure_diagnostics(value):
    """Bounded non-authoritative reasons, never raw exceptions/URLs/provider text."""
    if type(value) is not dict:
        return []
    rows = value.get("provider_failures")
    if type(rows) is not list:
        rows = [value] if value.get("available") is not True else []
    result = []
    for row in rows[:8]:
        if type(row) is not dict or row.get("source") not in ("coinset", "full_node_rpc"):
            continue
        reason = row.get("reason")
        reason = reason if type(reason) is str and reason in _FAILURE_REASONS else "fee_provider_unavailable"
        observed = row.get("observed_at")
        diagnostic = {"source": row["source"], "reason": reason,
                      "observed_at": observed if _integer(observed) else None}
        if diagnostic not in result:
            result.append(diagnostic)
    return result


def fee_quote_network_evidence(quote):
    """Return validated internal diagnostics; legacy absent evidence is unknown."""
    unknown = {"full_node_synced": None, "mempool_size": None,
               "mempool_fees": None, "last_block_cost": None}
    evidence = quote.get("network_evidence", unknown)
    if type(evidence) is not dict or set(evidence) != set(unknown):
        raise ValueError("invalid_network_evidence")
    if evidence["full_node_synced"] is not None and evidence["full_node_synced"] is not True:
        raise ValueError("invalid_network_evidence")
    if any(value is not None and not _integer(value) for key, value in evidence.items()
           if key != "full_node_synced"):
        raise ValueError("invalid_network_evidence")
    return dict(evidence)


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
        "network_evidence": {
            "full_node_synced": None, "mempool_size": None,
            "mempool_fees": None, "last_block_cost": None,
        },
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
    # Absence is unknown; an explicitly unhealthy or malformed observation
    # cannot support a usable quote, including an apparently free transaction.
    evidence = result["network_evidence"]
    if "full_node_synced" in response:
        if type(response["full_node_synced"]) is not bool:
            result["reason"] = "invalid_network_evidence"
            return result
        evidence["full_node_synced"] = response["full_node_synced"]
        if response["full_node_synced"] is False:
            result["reason"] = "fee_provider_unsynced"
            return result
    for field in ("mempool_size", "mempool_fees", "last_block_cost"):
        if field in response:
            if not _integer(response[field]):
                result["reason"] = "invalid_network_evidence"
                return result
            evidence[field] = response[field]
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
    quote = normalize_fee_response(
        snapshot.get("raw") if snapshot.get("available") is True else None,
        cost=cost,
        target_seconds=target_seconds,
        source=snapshot.get("source"),
        observed_at=snapshot.get("observed_at"),
        now=now,
    )
    if quote["available"] is not True:
        quote["provider_failures"] = fee_failure_diagnostics(
            snapshot if snapshot.get("available") is not True else quote)
    return quote
