"""Shared exact-input Sage batch descriptions and read-only cost inspection."""

from coin_prep_batch_plan import BatchPlan
from coin_prep_targets import MAX_ATOMIC_AMOUNT
from replacement_capacity import canonical_coin_prep_contract
import wallet


def batch_target_contract(plan: BatchPlan, address: str, cat_asset_id: str | None) -> dict:
    """Describe the same economic effects used by preview and the journal."""
    if type(plan) is not BatchPlan or plan.transaction_required is not True:
        raise ValueError("an exact transaction batch is required")
    if type(plan.fee_mojos) is not int or not 0 <= plan.fee_mojos <= MAX_ATOMIC_AMOUNT:
        raise ValueError("batch fee must be an exact bounded integer")
    outputs = []
    for index, output in enumerate(plan.outputs):
        if type(output.amount_mojos) is not int or not 1 <= output.amount_mojos <= MAX_ATOMIC_AMOUNT:
            raise ValueError("batch output must be an exact bounded integer")
        outputs.append({
            "output_index": index, "asset": output.asset, "address": address,
            "amount_mojos": output.amount_mojos,
            "purpose": {"change": "top_up", "fee_change": "fee_reserve"}.get(
                output.purpose, output.purpose
            ),
            "ordinal": output.ordinal,
        })
    target = {
        "contract_version": 2, "wallet_type": plan.asset,
        "cat_asset_id": cat_asset_id if plan.asset == "cat" else None,
        "fee_mojos": plan.fee_mojos, "outputs": outputs,
    }
    if plan.fee_source_id:
        target["external_fee"] = {"fee_mojos": plan.fee_mojos, "coin_ids": [plan.fee_source_id]}
    # The journal's pure canonical validator also guards unsigned preview input.
    # Validation here creates no journal, claim, reservation or wallet effect.
    canonical_coin_prep_contract(
        operation_kind="split", purpose="replacement",
        source_coin_ids=list(plan.source_coin_ids), target_contract=target,
    )
    return target


def batch_actions(target: dict) -> list[dict]:
    actions = []
    for output in target["outputs"]:
        action_id = {"type": "xch"} if output["asset"] == "xch" else {
            "type": "existing", "asset_id": target["cat_asset_id"],
        }
        actions.append({
            "type": "send", "id": action_id, "address": output["address"],
            "amount": str(output["amount_mojos"]), "memos": [],
        })
    if target["fee_mojos"]:
        actions.append({"type": "fee", "amount": str(target["fee_mojos"])})
    return actions


def batch_validation_contract(plan: BatchPlan, target: dict) -> dict:
    return {
        "source_asset": plan.asset, "source_coin_ids": list(plan.source_coin_ids),
        "fee_coin_ids": [plan.fee_source_id] if plan.fee_source_id else [],
        "cat_asset_id": target["cat_asset_id"], "fee_mojos": plan.fee_mojos,
        "outputs": [{key: value for key, value in output.items() if key != "output_index"}
                    for output in target["outputs"]],
    }


def inspect_batch_unsigned(plan: BatchPlan, address: str, cat_asset_id: str | None) -> dict:
    """Construct/validate current inputs and calculate actual unsigned CLVM cost.

    This is an internal trusted-runtime result, not a client payload or permission
    to submit. It never writes claims/effect evidence or reserves/signs/spends.
    Uninspectable effects/costs cannot fall back to an allegedly exact heuristic.
    """
    target = batch_target_contract(plan, address, cat_asset_id)
    selected = [*plan.source_coin_ids]
    if plan.fee_source_id:
        selected.append(plan.fee_source_id)
    unsigned = wallet.build_transaction_rpc(selected, batch_actions(target))
    validated = wallet.inspect_unsigned_transaction_effect(
        unsigned, batch_validation_contract(plan, target)
    )
    if type(validated) is not dict or validated.get("_catalyst_validated_unsigned") is not True:
        return {
            "available": False, "cost": None,
            "reason": validated.get("reason", "UNSIGNED_EFFECT_NOT_INSPECTABLE")
            if type(validated) is dict else "UNSIGNED_EFFECT_NOT_INSPECTABLE",
        }
    cost = validated.get("_catalyst_exact_unsigned_cost")
    if type(cost) is not int or cost <= 0:
        return {"available": False, "cost": None, "reason": "FEE_UNSIGNED_COST_UNAVAILABLE"}
    return {
        "available": True, "reason": "validated_unsigned_cost", "cost": cost,
        "cost_kind": "exact_unsigned", "target_contract": target,
        "validated_unsigned": validated,
    }
