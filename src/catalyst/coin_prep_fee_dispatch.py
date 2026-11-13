"""Trusted frozen-plan exact pricing immediately before prep effect claiming.

This service never signs, submits or treats a preview as a spending permit.
Actual dispatch additionally needs the exact journal-bound atomic fee hold and
the existing wallet-effect fence. No manual fee/price/plan override is accepted.
"""

from coin_prep_fee_funding import prepare_fee_inventory
from coin_prep_fee_pricing import is_current_fee_quote, price_next_prep_batch
import coin_prep_fee_pricing
from coin_prep_fee_runtime import read_approved_prep_fee_snapshot
from fee_estimation import fee_failure_diagnostics
from super_log import slog
import database
import json
from dataclasses import replace


def _paused(context, reason, **details):
    return {
        "available": False,
        "reason": reason,
        "approval": context["approval"],
        "dispatch_authorized": False,
        **details,
    }


def _follow_prep_fee_cap(approval_id, approved_snapshot=None):
    """Return a cap only when the durable Follow session binds this approval."""
    from follow_run_coordinator import FollowRunCoordinator

    state = FollowRunCoordinator().get_state()
    if type(state) is not dict or state.get("fee_approval_id") != approval_id:
        return None
    policy = database.get_active_follow_run_policy()
    if policy is None:
        raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_REQUIRED")
    if approved_snapshot is None:
        approved_snapshot = read_approved_prep_fee_snapshot(approval_id)
    from confidence_override import current_configuration_digest
    from follow_prep_fee_authority import verified_prep_fee_cap

    return verified_prep_fee_cap(
        policy=policy,
        coordinator_state=state,
        current_configuration_sha256=current_configuration_digest(),
        approved_snapshot=approved_snapshot,
        requested_approval_id=approval_id,
        run_session_id=state.get("session_id"),
    )


def _verify_current_inventory(context, saved_snapshot, plan, operation_id, claim):
    fee_ids = [plan.fee_source_id] if plan.fee_source_id else []
    if not database.wallet_effect_claim_is_current(
        claim["claim_token"],
        claim["generation"],
        operation_id=operation_id,
        source_coin_ids=list(plan.source_coin_ids),
        fee_coin_ids=fee_ids,
    ):
        raise ValueError("FEE_EFFECT_NOT_DISPATCHABLE")
    own_ids = {
        coin_id.removeprefix("0x")
        for key in ("source_coin_ids_json", "fee_coin_ids_json")
        for coin_id in json.loads(claim[key])
    }
    original = {coin.coin_id: coin for coin in saved_snapshot.coins}
    reserve_floors = context["recipe"]["economic_plan"]["reserve_floors_mojos"]
    reserves = {
        row["coin_id"].removeprefix("0x")
        for asset in ("xch", "cat")
        for row in database.get_reserve_coins(asset)
    }
    prior_invalid = [
        coin_id
        for coin_id in own_ids
        if coin_id not in original
        or not original[coin_id].selectable
        or (
            original[coin_id].protected
            and not (
                original[coin_id].purpose == "reserve"
                and reserve_floors[original[coin_id].asset] == 0
            )
        )
    ]
    if own_ids & reserves or prior_invalid:
        invalid_kinds = {
            "missing": sum(coin_id not in original for coin_id in prior_invalid),
            "protected": sum(
                coin_id in original and original[coin_id].protected
                for coin_id in prior_invalid
            ),
            "nonselectable": sum(
                coin_id in original and not original[coin_id].selectable
                for coin_id in prior_invalid
            ),
            "fee_source": sum(coin_id in fee_ids for coin_id in prior_invalid),
        }
        slog(
            "coin_prep",
            "Direct batch preclaim inventory changed",
            {
                "reserve_overlap_count": len(own_ids & reserves),
                "invalid_source_count": len(prior_invalid),
                "invalid_kinds": invalid_kinds,
            },
            level="warning",
        )
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    fresh = {}
    for coin in context["snapshot"].coins:
        if coin.coin_id in own_ids:
            before = original[coin.coin_id]
            # Ignore only own claim's protection designation, never amount,
            # asset, selectability, reserve changes or unrelated protections.
            if coin.protected and coin.purpose == "protected":
                coin = replace(coin, protected=before.protected, purpose=before.purpose)
        fresh[coin.coin_id] = coin
    if fresh != original:
        old_ids, new_ids = set(original), set(fresh)
        changed = [
            coin_id
            for coin_id in old_ids & new_ids
            if original[coin_id] != fresh[coin_id]
        ]
        changed_fields = sorted(
            {
                field
                for coin_id in changed
                for field in vars(original[coin_id])
                if getattr(original[coin_id], field) != getattr(fresh[coin_id], field)
            }
        )
        slog(
            "coin_prep",
            "Direct batch inventory changed before dispatch",
            {
                "missing_count": len(old_ids - new_ids),
                "added_count": len(new_ids - old_ids),
                "changed_count": len(changed),
                "changed_fields": changed_fields,
                "own_missing_count": len(own_ids - new_ids),
                "own_changed_count": len(own_ids & set(changed)),
            },
            level="warning",
        )
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")


def price_approved_prep_batch(approval_id: str) -> dict:
    """Price actual unsigned effects inside the latest remaining prep allowance.

    Refresh frozen consent, inventory and configuration before and after slow
    unsigned builds/network estimates. Expected inventory progression cannot
    resize targets; any change during this individual pricing pass invalidates
    that pass. Unknown holds and protected cancellation cover remain counted.
    """
    # A previous worker may have stopped after the authoritative prep outcome
    # was journalled but before its exact fee hold was settled. Only terminal
    # journal evidence can close that gap; unknown effects remain held.
    database.settle_terminal_coin_prep_fee_reservations()
    accounting = database.get_coin_prep_fee_approval_status(approval_id)
    if accounting["unresolved_operation_count"]:
        return {
            "available": False,
            "reason": "FEE_EFFECT_RECOVERY_REQUIRED",
            "approval": accounting,
            "recovery_state": accounting["state"],
            "dispatch_authorized": False,
        }
    context = read_approved_prep_fee_snapshot(approval_id)
    follow_fee_cap = _follow_prep_fee_cap(approval_id, context)
    recipe = context["recipe"]
    plan = recipe["economic_plan"]
    funding = prepare_fee_inventory(
        context["snapshot"], recipe["targets"], plan["reserve_floors_mojos"]
    )
    if funding["principal_funded"] is not True:
        return _paused(context, "FEE_PREP_PRINCIPAL_UNFUNDED")
    pricing = price_next_prep_batch(
        snapshot=funding["snapshot"],
        targets=recipe["targets"],
        reserve_floors=plan["reserve_floors_mojos"],
        receive_address=context["receive_address"],
        cat_asset_id=context["identity"]["asset_id"],
        target_seconds=plan["target_seconds"],
        maximum_fee_mojos=follow_fee_cap,
    )
    after = read_approved_prep_fee_snapshot(approval_id)
    if any(
        after[key] != context[key]
        for key in (
            "identity",
            "configuration",
            "receive_address",
            "snapshot",
            "recipe",
            "campaign",
            "scope",
        )
    ):
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    # Re-read durable accounting: concurrent holds cannot inherit an earlier
    # larger allowance, even though they do not change the economic plan.
    context = after
    if pricing["available"] is not True:
        return _paused(
            context,
            pricing["reason"],
            diagnostic_stage="unsigned_pricing",
            provider_failures=fee_failure_diagnostics(pricing),
        )
    if pricing.get("fee_cap_warning"):
        slog(
            "coin_prep",
            "Follow prep recommended fee exceeds approved per-transaction maximum; trying the approved maximum",
            pricing["fee_cap_warning"],
            level="warning",
        )
    if pricing["transaction_required"] is True:
        fee = pricing["plan"].fee_mojos
        # Slow inventory reads can leave a valid quote too close to expiry for
        # the worker's pre-claim guard. Reprice the already inspected cost only;
        # never renew a cached timestamp or resize an approved executable fee.
        if is_current_fee_quote(
            pricing["quote"], pricing["inspection"]["cost"], plan["target_seconds"]
        ) and not is_current_fee_quote(
            pricing["quote"],
            pricing["inspection"]["cost"],
            plan["target_seconds"],
            now=coin_prep_fee_pricing._now() + 10,
        ):
            from fee_estimation import quote_fee

            try:
                fresh = quote_fee(
                    pricing["inspection"]["cost"],
                    target_seconds=plan["target_seconds"],
                    force_refresh=True,
                )
            except Exception:
                fresh = None
            if not is_current_fee_quote(
                fresh,
                pricing["inspection"]["cost"],
                plan["target_seconds"],
                now=coin_prep_fee_pricing._now() + 10,
            ) or (
                fresh["fee_mojos"] != fee
                and not (
                    follow_fee_cap is not None
                    and fee == follow_fee_cap
                    and fresh["fee_mojos"] > follow_fee_cap
                )
            ):
                return _paused(
                    context,
                    "FEE_ESTIMATE_UNAVAILABLE",
                    diagnostic_stage="post_inventory_fresh_quote",
                )
            pricing = {**pricing, "quote": fresh}
        if not is_current_fee_quote(
            pricing["quote"], pricing["inspection"]["cost"], plan["target_seconds"]
        ):
            quote = pricing["quote"]
            return _paused(
                context,
                "FEE_ESTIMATE_UNAVAILABLE",
                diagnostic_stage="post_inventory_quote_recheck",
                quote_timing={
                    "observed_at": quote.get("observed_at"),
                    "expires_at": quote.get("expires_at"),
                    "checked_at": coin_prep_fee_pricing._now(),
                },
            )
        if (
            context["approval"].get("unbounded") is not True
            and fee > context["approval"]["remaining_preparation_fee_mojos"]
        ):
            return _paused(context, "FEE_BUDGET_EXCEEDED", required_fee_mojos=fee)
        if fee > funding["fee_funding_mojos"]:
            return _paused(
                context, "FEE_PREP_FUNDING_INSUFFICIENT", required_fee_mojos=fee
            )
    return {
        **context,
        "available": True,
        "reason": pricing["reason"],
        "funding": funding,
        "pricing": pricing,
        "follow_fee_cap_mojos": follow_fee_cap,
        "fee_cap_warning": pricing.get("fee_cap_warning"),
        "dispatch_authorized": False,
    }


def reserve_approved_prep_dispatch(
    *,
    approval_id: str,
    operation_id: str,
    priced_batch: dict,
    attempt_id: str | None = None,
) -> dict:
    """Bind executable cost/effects to PREPARED journal and hold the exact fee.

    Accept only an internal server pricing result, never client economics. Own
    claims can now protect the selected roots, so do not replan from a post-claim
    selectable snapshot. Instead verify the saved pre-claim plan, fresh frozen
    economics, executable bundle, exact journal and current undispatched claim.
    A successful hold is NOT authorization to sign or to replay an operation.
    """
    from coin_prep_batch_plan import BatchConstraints, BatchPlan, plan_batch
    from coin_prep_unsigned import batch_target_contract, batch_validation_contract
    from replacement_capacity import canonical_coin_prep_contract
    import wallet

    if type(priced_batch) is not dict or priced_batch.get("available") is not True:
        raise ValueError("FEE_DISPATCH_PLAN_MISMATCH")
    context = read_approved_prep_fee_snapshot(approval_id)
    follow_fee_cap = _follow_prep_fee_cap(approval_id, context)
    if priced_batch.get("approval", {}).get("approval_id") != approval_id or any(
        priced_batch.get(key) != context[key]
        for key in (
            "identity",
            "configuration",
            "receive_address",
            "recipe",
            "campaign",
            "scope",
        )
    ):
        raise ValueError("FEE_DISPATCH_PLAN_MISMATCH")
    pricing = priced_batch.get("pricing")
    if type(pricing) is not dict or pricing.get("transaction_required") is not True:
        raise ValueError("FEE_DISPATCH_PLAN_MISMATCH")
    plan = pricing.get("plan")
    if type(plan) is not BatchPlan or plan.transaction_required is not True:
        raise ValueError("FEE_DISPATCH_PLAN_MISMATCH")
    economics = context["recipe"]["economic_plan"]
    funding = prepare_fee_inventory(
        priced_batch["snapshot"],
        context["recipe"]["targets"],
        economics["reserve_floors_mojos"],
    )
    expected = plan_batch(
        funding["snapshot"],
        context["recipe"]["targets"],
        BatchConstraints(
            economics["reserve_floors_mojos"],
            plan.fee_mojos,
            allow_bounded_prerequisite=True,
        ),
    )
    if (
        funding["principal_funded"] is not True
        or plan != expected
        or plan.fee_mojos > funding["fee_funding_mojos"]
    ):
        raise ValueError("FEE_DISPATCH_PLAN_MISMATCH")
    target = batch_target_contract(
        plan, context["receive_address"], context["identity"]["asset_id"]
    )
    canonical = canonical_coin_prep_contract(
        operation_kind="split",
        purpose="replacement",
        source_coin_ids=list(plan.source_coin_ids),
        target_contract=target,
        attempt_id=attempt_id,
    )
    if canonical["operation_id"] != operation_id:
        raise ValueError("FEE_DISPATCH_PLAN_MISMATCH")
    claim = database.get_coin_prep_fee_dispatch_claim(operation_id)
    _verify_current_inventory(
        context, priced_batch["snapshot"], plan, operation_id, claim
    )
    # Re-run actual executable validation/cost, not just a caller-held marker.
    inspection = pricing.get("inspection")
    if type(inspection) is not dict or inspection.get("target_contract") != target:
        raise ValueError("FEE_DISPATCH_PLAN_MISMATCH")
    validated = wallet.inspect_unsigned_transaction_effect(
        inspection.get("validated_unsigned"), batch_validation_contract(plan, target)
    )
    if (
        type(validated) is not dict
        or validated.get("_catalyst_validated_unsigned") is not True
        or validated.get("_catalyst_executable_effect_bound") is not True
    ):
        raise ValueError("FEE_UNSIGNED_COST_UNAVAILABLE")
    quote = pricing.get("quote")
    cost = validated.get("_catalyst_exact_unsigned_cost")
    capped_recommendation = (
        follow_fee_cap is not None
        and plan.fee_mojos == follow_fee_cap
        and type(quote) is dict
        and type(quote.get("fee_mojos")) is int
        and quote.get("fee_mojos", 0) > follow_fee_cap
    )
    if (
        not is_current_fee_quote(quote, cost, economics["target_seconds"])
        or (quote["fee_mojos"] != plan.fee_mojos and not capped_recommendation)
        or priced_batch.get("follow_fee_cap_mojos") != follow_fee_cap
    ):
        slog(
            "coin_prep",
            "Direct batch fee quote rejected before wallet dispatch",
            {
                "operation_id": operation_id,
                "quote_observed_at": quote.get("observed_at")
                if type(quote) is dict
                else None,
                "quote_expires_at": quote.get("expires_at")
                if type(quote) is dict
                else None,
                "quoted_cost": quote.get("cost") if type(quote) is dict else None,
                "validated_cost": cost,
                "quoted_fee_mojos": quote.get("fee_mojos")
                if type(quote) is dict
                else None,
                "planned_fee_mojos": plan.fee_mojos,
            },
            level="warning",
        )
        raise ValueError("FEE_ESTIMATE_UNAVAILABLE")
    # Bind actual derived additions; a different earlier binding cannot survive.
    database.bind_coin_prep_constructed_outputs(
        operation_id,
        plan_hash=canonical["target_contract"]["plan_hash"],
        constructed_outputs=validated["constructed_outputs"],
    )
    final = read_approved_prep_fee_snapshot(approval_id)
    if any(
        final[key] != context[key]
        for key in (
            "identity",
            "configuration",
            "receive_address",
            "recipe",
            "campaign",
            "scope",
        )
    ):
        raise ValueError("FEE_APPROVAL_STALE")
    _verify_current_inventory(
        final, priced_batch["snapshot"], plan, operation_id, claim
    )
    hold = database.reserve_coin_prep_fee_for_dispatch(
        approval_id=approval_id,
        scope_sha256=final["approval"]["scope_sha256"],
        plan_sha256=final["approval"]["plan_sha256"],
        operation_id=operation_id,
        final_quote=quote,
        executed_fee_mojos=plan.fee_mojos,
    )
    return {**hold, "validated_unsigned": validated, "dispatch_authorized": False}


def recheck_approved_prep_dispatch(
    *, approval_id: str, operation_id: str, priced_batch: dict, dispatch_capability=None
) -> None:
    """Final read-only check after the hold, before the existing effect fence.

    The hold remains counted if identity/settings/inventory/guidance changed;
    failure here is not authoritative proof that an effect can be refunded.
    """
    context = read_approved_prep_fee_snapshot(approval_id)
    if any(
        priced_batch[key] != context[key]
        for key in (
            "identity",
            "configuration",
            "receive_address",
            "recipe",
            "campaign",
            "scope",
        )
    ):
        raise ValueError("FEE_APPROVAL_STALE")
    pricing = priced_batch["pricing"]
    if not is_current_fee_quote(
        pricing["quote"],
        pricing["inspection"]["cost"],
        context["recipe"]["economic_plan"]["target_seconds"],
    ):
        raise ValueError("FEE_ESTIMATE_UNAVAILABLE")
    claim = database.get_coin_prep_fee_dispatch_claim(
        operation_id, dispatch_capability=dispatch_capability
    )
    _verify_current_inventory(
        context, priced_batch["snapshot"], pricing["plan"], operation_id, claim
    )
