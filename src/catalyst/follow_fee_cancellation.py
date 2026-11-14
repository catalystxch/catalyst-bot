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
from follow_shutdown_funding import ONE_BLOCK_COST_LIMIT
import wallet


def _verified_active_transaction_fee_cap(
    *, run_id: str, identity: dict, now_epoch: int | None = None
) -> int | None:
    """Return the cap only when the active coordinator proves this exact run.

    Stopped-run recovery deliberately has no coordinator binding and therefore
    keeps its separate durable fee authority. This helper never infers a cap
    from that cumulative recovery authority.
    """
    try:
        from follow_run_coordinator import FollowRunCoordinator

        coordinator = FollowRunCoordinator().read_state()
        policy = database.get_active_follow_run_policy()
    except Exception as exc:
        raise ValueError("FOLLOW_RUN_FEE_CAP_AUTHORITY_UNAVAILABLE") from exc
    if coordinator is None:
        return None
    if type(coordinator) is not dict:
        raise ValueError("FOLLOW_RUN_FEE_CAP_AUTHORITY_MISMATCH")
    if coordinator.get("state") != "running":
        # Manual cleanup can follow a stopped or failed replacement run.  It
        # has no active creation scope.  A persisted policy for this wallet
        # may still lower the fee used by the older run's cleanup authority.
        if policy is None:
            return None
        if (
            identity.get("network") == policy.network
            and identity.get("asset_id") == policy.asset_id
            and str(identity.get("wallet_fingerprint")) == policy.wallet_fingerprint
        ):
            return policy.maximum_fee_mojos_per_tx
        return None
    try:
        from confidence_override import current_configuration_digest, current_scope

        config_digest = current_configuration_digest()
        scope = current_scope()
    except Exception as exc:
        raise ValueError("FOLLOW_RUN_FEE_CAP_AUTHORITY_UNAVAILABLE") from exc
    if (
        coordinator.get("run_id") != run_id
        or policy is None
        or coordinator.get("policy_digest") != policy.digest
        or coordinator.get("configuration_sha256") != config_digest
        or type(scope) is not dict
        or scope.get("follow_run_id") != run_id
        or scope.get("configuration_sha256") != config_digest
        or scope.get("identity") != identity
        or identity.get("network") != policy.network
        or identity.get("asset_id") != policy.asset_id
        or str(identity.get("wallet_fingerprint")) != policy.wallet_fingerprint
    ):
        raise ValueError("FOLLOW_RUN_FEE_CAP_AUTHORITY_MISMATCH")
    cap = policy.maximum_fee_mojos_per_tx
    from follow_run_fee_cap_grant import get_follow_run_fee_cap_grant

    grant = get_follow_run_fee_cap_grant(run_id=run_id, now_epoch=now_epoch)
    if grant is not None:
        cap = grant["maximum_fee_mojos_per_tx"]
    return cap


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
    """Converge a Sage unsigned cancellation against current run fee authority."""
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

    try:
        transaction_fee_cap = _verified_active_transaction_fee_cap(
            run_id=run_id, identity=identity, now_epoch=now_epoch
        )
    except ValueError as exc:
        return _refused(str(exc), authority)

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
        if cost > ONE_BLOCK_COST_LIMIT:
            return _refused(
                "FEE_CANCELLATION_BATCH_OVER_BLOCK_LIMIT",
                authority,
                required_cost=cost,
            )
        try:
            quote = quote_fee(cost, target_seconds=target_seconds)
        except Exception:
            return _refused("FEE_ESTIMATE_UNAVAILABLE", authority)
        if not is_current_fee_quote(quote, cost, target_seconds):
            return _refused("FEE_ESTIMATE_UNAVAILABLE", authority)
        quoted_fee = quote["fee_mojos"]
        selected_fee = (
            min(quoted_fee, transaction_fee_cap)
            if transaction_fee_cap is not None
            else quoted_fee
        )
        if selected_fee == fee:
            if fee == 0:
                return _refused("FEE_CANCELLATION_FUNDING_REQUIRED", authority)
            after = database.get_effective_follow_fee_policy(
                run_id=run_id, identity=identity, now_epoch=now_epoch
            )
            if after.get("ready") is not True or after != authority:
                return _refused("FOLLOW_FEE_APPROVAL_STALE", after)
            if (
                after.get("unbounded") is not True
                and fee > after["remaining_fee_mojos"]
            ):
                return _refused("FEE_BUDGET_EXCEEDED", after, required_fee_mojos=fee)
            return {
                "available": True,
                "reason": "cost_fee_consistent",
                "authority": after,
                "trade_ids": trades,
                "source_coin_ids": sources,
                "fee_coin_id": fee_coins[0],
                "fee_mojos": fee,
                "fee_cap_mojos": transaction_fee_cap,
                "fee_cap_warning": (
                    {
                        "code": "FOLLOW_FEE_RECOMMENDATION_ABOVE_POLICY_CAP",
                        "run_id": run_id,
                        "reason": "FEE_CAP_BELOW_RECOMMENDATION",
                        "recommended_fee_mojos": quoted_fee,
                        "approved_maximum_fee_mojos": transaction_fee_cap,
                    }
                    if transaction_fee_cap is not None
                    and quoted_fee > transaction_fee_cap
                    else None
                ),
                "cost": cost,
                "quote": quote,
                "validated_unsigned": built,
                "dispatch_authorized": False,
            }
        fee = selected_fee
    return _refused("FEE_PRICING_NOT_CONVERGED", authority)
