"""Helpers for a resource-backed initial Follow book below signed targets."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import re


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _parse_count_spec(value: object) -> dict[str, int]:
    if type(value) is not str or len(value) > 2048:
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
    result = {}
    for item in value.split(",") if value else ():
        parts = item.split("=")
        if (
            len(parts) != 2
            or not parts[0]
            or parts[0] in result
            or re.fullmatch(r"0|[1-9][0-9]{0,4}", parts[1]) is None
        ):
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
        result[parts[0]] = int(parts[1])
    return result


def _count_spec(values: dict[str, int], tier_order: tuple[str, ...]) -> str:
    return ",".join(
        f"{tier}={values[tier]}" for tier in tier_order if values.get(tier, 0) > 0
    )


def derive_refreshed_funded_limits(
    *,
    target_buy: int,
    target_sell: int,
    current_buy: int,
    current_sell: int,
    active_buy: int,
    active_sell: int,
    free_buy: int,
    free_sell: int,
) -> tuple[int, int]:
    """Combine existing open slots and a fresh free-coin prefix proof."""
    values = (
        target_buy,
        target_sell,
        current_buy,
        current_sell,
        active_buy,
        active_sell,
        free_buy,
        free_sell,
    )
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
    if (
        target_buy < 1
        or target_sell < 1
        or current_buy < 1
        or current_sell < 1
        or current_buy > target_buy
        or current_sell > target_sell
        or active_buy > target_buy
        or active_sell > target_sell
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
    return (
        min(target_buy, max(current_buy, active_buy + free_buy)),
        min(target_sell, max(current_sell, active_sell + free_sell)),
    )


def validate_follow_prep_authority(
    *,
    session_id: str,
    coordinator_state: dict,
    policy,
    configuration: dict,
    configuration_sha256: str,
    identity: dict,
) -> bool:
    """Require one current, native-confirmed policy session before partial prep."""
    from follow_run_policy import FollowRunPolicy

    if (
        type(session_id) is not str
        or _DIGEST.fullmatch(session_id) is None
        or type(coordinator_state) is not dict
        or type(policy) is not FollowRunPolicy
        or type(configuration) is not dict
        or type(identity) is not dict
        or type(configuration_sha256) is not str
        or _DIGEST.fullmatch(configuration_sha256) is None
    ):
        raise ValueError("FOLLOW_RUN_PREP_AUTHORITY_INVALID")
    if (
        coordinator_state.get("session_id") != session_id
        or coordinator_state.get("run_id") is not None
        or coordinator_state.get("policy_digest") != policy.digest
        or coordinator_state.get("configuration_sha256") != configuration_sha256
        or coordinator_state.get("state") not in {"prep_pending", "preparing"}
        or coordinator_state.get("unknown_effect") is not False
        or coordinator_state.get("run_id") is not None
        or configuration.get("MAX_ACTIVE_BUY_OFFERS") != policy.buy_target
        or configuration.get("MAX_ACTIVE_SELL_OFFERS") != policy.sell_target
        or identity.get("network") != policy.network
        or str(identity.get("wallet_fingerprint")) != policy.wallet_fingerprint
        or identity.get("asset_id") != policy.asset_id
    ):
        raise ValueError("FOLLOW_RUN_AUTHORITY_CHANGED")
    return True


def plan_partial_follow_prep_recipe(
    recipe: dict,
    *,
    configuration: dict,
    policy,
    available_trade_xch_mojos: int,
    available_trade_cat_atoms: int,
) -> dict:
    """Derive and freeze the largest funded prefixes under the signed caps."""
    from follow_run_policy import FollowRunPolicy
    from follow_slot_fit import preview_current_follow_slot_fit

    if (
        type(recipe) is not dict
        or type(configuration) is not dict
        or type(policy) is not FollowRunPolicy
        or type(available_trade_xch_mojos) is not int
        or type(available_trade_cat_atoms) is not int
        or available_trade_xch_mojos <= 0
        or available_trade_cat_atoms <= 0
        or configuration.get("MAX_ACTIVE_BUY_OFFERS") != policy.buy_target
        or configuration.get("MAX_ACTIVE_SELL_OFFERS") != policy.sell_target
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
    budget_xch = min(available_trade_xch_mojos, policy.maximum_trade_xch_mojos)
    budget_cat = min(available_trade_cat_atoms, policy.maximum_trade_cat_atoms)
    fit = preview_current_follow_slot_fit(
        configuration=configuration,
        outputs=[asdict(target) for target in recipe.get("targets", ())],
        buy_limit=policy.buy_target,
        sell_limit=policy.sell_target,
        maximum_trade_xch_mojos=budget_xch,
        maximum_trade_cat_atoms=budget_cat,
        allow_partial=True,
        mid_price_override=policy.price_anchor,
    )
    funded_buy = fit.get("funded_buy_limit")
    funded_sell = fit.get("funded_sell_limit")
    if (
        type(funded_buy) is not int
        or type(funded_sell) is not int
        or not 1 <= funded_buy <= policy.buy_target
        or not 1 <= funded_sell <= policy.sell_target
    ):
        raise ValueError("FOLLOW_FUNDED_TARGETS_UNAVAILABLE")
    from decimal import Decimal

    for assignment in fit.get("funded_output_assignments", []):
        try:
            price = Decimal(assignment["price_xch"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID") from None
        if not policy.price_min <= price <= policy.price_max:
            raise ValueError("FOLLOW_FUNDED_TARGET_PRICE_OUTSIDE_POLICY")
    return trim_follow_prep_recipe(
        recipe,
        fit,
        configuration=configuration,
        buy_target=policy.buy_target,
        sell_target=policy.sell_target,
    )


def refresh_running_follow_funded_limits(session_id: str, *, offer_manager) -> dict:
    """Raise a running book ceiling from one fresh wallet-backed slot proof.

    Already-open durable slots count toward the book. Additional free coins
    count only when their authoritative tier assignment and current wallet
    membership support a target-prefix fit under the approved principal caps.
    This function never lowers a ceiling or creates an offer.
    """
    import hashlib
    import json
    import database
    import confidence_override
    from coin_prep_fee_runtime import _configuration, read_approved_prep_fee_snapshot
    from coin_prep_economics import PREP_TIERS

    from follow_principal import _principal_from_observed_snapshot
    from follow_run_coordinator import FollowRunCoordinator
    from follow_run_policy import FollowRunPolicy
    from follow_slot_fit import preview_current_follow_slot_fit

    coordinator = FollowRunCoordinator()
    state = coordinator.get_state()
    policy = database.get_active_follow_run_policy()
    if (
        type(session_id) is not str
        or _DIGEST.fullmatch(session_id) is None
        or type(state) is not dict
        or type(policy) is not FollowRunPolicy
        or state.get("session_id") != session_id
        or state.get("run_id") is None
        or state.get("policy_digest") != policy.digest
        or state.get("state") != "running"
        or state.get("unknown_effect") is not False
        or state.get("fee_approval_id") is None
        or offer_manager is None
        or state.get("configuration_sha256")
        != confidence_override.current_configuration_digest()
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_AUTHORITY_CHANGED")
    configuration = _configuration()
    if (
        configuration.get("MAX_ACTIVE_BUY_OFFERS") != policy.buy_target
        or configuration.get("MAX_ACTIVE_SELL_OFFERS") != policy.sell_target
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_AUTHORITY_CHANGED")
    approval_id = state["fee_approval_id"]
    status = database.get_coin_prep_fee_approval_status(approval_id)
    approved = read_approved_prep_fee_snapshot(approval_id)
    if (
        type(status) is not dict
        or status.get("approval_id") != approval_id
        or status.get("stale") is not False
        or status.get("session_completed") is not True
        or status.get("unresolved_operation_count") != 0
        or approved.get("request_options", {}).get("follow_run_session_id")
        != session_id
        or approved.get("scope", {}).get("session_id")
        != state.get("fee_approval_session_id")
        or approved.get("identity", {}).get("network") != policy.network
        or str(approved.get("identity", {}).get("wallet_fingerprint"))
        != policy.wallet_fingerprint
        or approved.get("identity", {}).get("asset_id") != policy.asset_id
        or (
            status.get("unbounded") is not True
            and (
                type(status.get("total_fee_mojos")) is not int
                or status["total_fee_mojos"] <= 0
            )
        )
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_PREP_CHANGED")
    principal = _principal_from_observed_snapshot(
        approved,
        fee_cap_mojos=(
            None if status.get("unbounded") is True else status["total_fee_mojos"]
        ),
    )
    trade_xch = min(
        principal["maximum_trade_xch_mojos"], policy.maximum_trade_xch_mojos
    )
    trade_cat = min(
        principal["maximum_trade_cat_atoms"], policy.maximum_trade_cat_atoms
    )

    def _eligible_free_rows(snapshot):
        wallet_by_id = {coin.coin_id: coin for coin in snapshot.coins}
        free_rows = []
        for asset in ("xch", "cat"):
            for row in database.get_free_coins(asset):
                coin_id = str(row.get("coin_id", "")).lower().removeprefix("0x")
                wallet_coin = wallet_by_id.get(coin_id)
                tier = str(row.get("assigned_tier") or "").lower()
                if (
                    wallet_coin is None
                    or wallet_coin.protected
                    or wallet_coin.purpose not in {"", "replacement"}
                    or type(row.get("amount_mojos")) is not int
                    or wallet_coin.amount_mojos != row.get("amount_mojos")
                    or row.get("designation") not in {"tier_spare", "tier_active"}
                    or row.get("purpose")
                    not in {"replacement", "fill_response", "top_up"}
                    or tier not in PREP_TIERS[:-1]
                ):
                    continue
                free_rows.append((asset, coin_id, tier, row["amount_mojos"]))
        return sorted(free_rows)

    free_rows = _eligible_free_rows(approved["snapshot"])
    outputs = []
    ordinals = {"xch": 0, "cat": 0}
    for asset, _coin_id, tier, amount in free_rows:
        ordinal = ordinals[asset]
        ordinals[asset] += 1
        outputs.append(
            {
                "asset": asset,
                "purpose": "replacement",
                "tier_rank": PREP_TIERS.index(tier),
                "amount_mojos": amount,
                "ordinal": ordinal,
            }
        )
    buy_slot_candidates = offer_manager.get_replenishment_slots(
        "buy",
        policy.buy_target,
        cat_asset_id=configuration.get("CAT_ASSET_ID"),
    )
    sell_slot_candidates = offer_manager.get_replenishment_slots(
        "sell",
        policy.sell_target,
        cat_asset_id=configuration.get("CAT_ASSET_ID"),
    )
    if type(buy_slot_candidates) is not list or type(sell_slot_candidates) is not list:
        raise ValueError("FOLLOW_FUNDED_TARGET_INVENTORY_UNAVAILABLE")
    fit = preview_current_follow_slot_fit(
        configuration=configuration,
        outputs=outputs,
        buy_limit=policy.buy_target,
        sell_limit=policy.sell_target,
        maximum_trade_xch_mojos=trade_xch,
        maximum_trade_cat_atoms=trade_cat,
        allow_partial=True,
        mid_price_override=policy.price_anchor,
        buy_slot_candidates=buy_slot_candidates,
        sell_slot_candidates=sell_slot_candidates,
    )
    for assignment in fit.get("funded_output_assignments", []):
        from decimal import Decimal

        price = Decimal(assignment["price_xch"])
        if not policy.price_min <= price <= policy.price_max:
            raise ValueError("FOLLOW_FUNDED_TARGET_PRICE_OUTSIDE_POLICY")

    from confidence_override import current_scope

    scope = current_scope()
    if type(scope) is not dict or scope.get("follow_run_id") != state["run_id"]:
        raise ValueError("FOLLOW_FUNDED_TARGET_AUTHORITY_CHANGED")
    asset_id = policy.asset_id
    active_counts = {}
    for side in ("buy", "sell"):
        keys = database.get_active_offer_slot_keys(asset_id=asset_id, side=side)
        prefix = f"ladder:{configuration.get('CAT_ASSET_ID')}:{side}:"
        if (
            type(keys) is not list
            or any(
                type(key) is not str
                or not key.startswith(prefix)
                or re.fullmatch(r"0|[1-9][0-9]{0,5}", key[len(prefix) :]) is None
                or int(key[len(prefix) :])
                >= (policy.buy_target if side == "buy" else policy.sell_target)
                for key in keys
            )
            or len(keys) != len(set(keys))
        ):
            raise ValueError("FOLLOW_FUNDED_TARGET_INVENTORY_UNAVAILABLE")
        active_counts[side] = len(keys)
    if (
        offer_manager.get_replenishment_slots(
            "buy", policy.buy_target, cat_asset_id=configuration.get("CAT_ASSET_ID")
        )
        != buy_slot_candidates
        or offer_manager.get_replenishment_slots(
            "sell", policy.sell_target, cat_asset_id=configuration.get("CAT_ASSET_ID")
        )
        != sell_slot_candidates
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_CHANGED")
    proposed_buy, proposed_sell = derive_refreshed_funded_limits(
        target_buy=policy.buy_target,
        target_sell=policy.sell_target,
        current_buy=state["funded_buy_limit"],
        current_sell=state["funded_sell_limit"],
        active_buy=active_counts["buy"],
        active_sell=active_counts["sell"],
        free_buy=fit["funded_buy_limit"],
        free_sell=fit["funded_sell_limit"],
    )
    after = read_approved_prep_fee_snapshot(approval_id)
    after_status = database.get_coin_prep_fee_approval_status(approval_id)
    if (
        type(after) is not dict
        or type(after_status) is not dict
        or any(
            after.get(key) != approved.get(key)
            for key in ("identity", "configuration", "scope", "recipe", "snapshot")
        )
        or after_status != status
        or _eligible_free_rows(after["snapshot"]) != free_rows
        or confidence_override.current_configuration_digest()
        != state["configuration_sha256"]
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_CHANGED")
    if (
        proposed_buy == state["funded_buy_limit"]
        and proposed_sell == state["funded_sell_limit"]
    ):
        return state
    proof_terms = {
        "session_id": session_id,
        "run_id": state["run_id"],
        "policy_digest": policy.digest,
        "configuration_sha256": state["configuration_sha256"],
        "principal_review_sha256": principal["principal_review_sha256"],
        "slot_assignment_sha256": fit["slot_assignment_sha256"],
        "active_counts": active_counts,
        "funded_buy_limit": proposed_buy,
        "funded_sell_limit": proposed_sell,
    }
    proof_sha256 = hashlib.sha256(
        json.dumps(proof_terms, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return coordinator.refresh_funded_limits(
        session_id=session_id,
        run_id=state["run_id"],
        policy_digest=policy.digest,
        configuration_sha256=state["configuration_sha256"],
        funded_buy_limit=proposed_buy,
        funded_sell_limit=proposed_sell,
        proof_sha256=proof_sha256,
    )


def trim_follow_prep_recipe(
    recipe: dict,
    fit: dict,
    *,
    configuration: dict,
    buy_target: int,
    sell_target: int,
) -> dict:
    """Freeze only the exact outputs assigned to fundable target prefixes.

    Fee-reserve outputs are preserved in full. Desired target counts stay in
    the active policy; this recipe contains only the initial replacement coins.
    """
    from coin_prep_economics import PREP_TIERS, build_exact_prep_economics

    targets = recipe.get("targets") if type(recipe) is dict else None
    worker_args = recipe.get("worker_args") if type(recipe) is dict else None
    funded_buy = fit.get("funded_buy_limit") if type(fit) is dict else None
    funded_sell = fit.get("funded_sell_limit") if type(fit) is dict else None
    assignments = fit.get("funded_output_assignments") if type(fit) is dict else None
    proof = fit.get("slot_assignment_sha256") if type(fit) is dict else None
    if (
        type(targets) is not tuple
        or type(worker_args) is not dict
        or type(configuration) is not dict
        or type(buy_target) is not int
        or type(sell_target) is not int
        or buy_target < 1
        or sell_target < 1
        or fit.get("buy_target") != buy_target
        or fit.get("sell_target") != sell_target
        or type(funded_buy) is not int
        or type(funded_sell) is not int
        or not 1 <= funded_buy <= buy_target
        or not 1 <= funded_sell <= sell_target
        or type(assignments) is not list
        or _DIGEST.fullmatch(proof) is None
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
    if len(assignments) != funded_buy + funded_sell:
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")

    by_asset_ordinal = {}
    for target in targets:
        asset = getattr(target, "asset", None)
        purpose = getattr(target, "purpose", None)
        ordinal = getattr(target, "ordinal", None)
        if (
            asset not in {"xch", "cat"}
            or purpose not in {"replacement", "fee_reserve"}
            or type(ordinal) is not int
            or ordinal < 0
            or (asset, ordinal) in by_asset_ordinal
        ):
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
        by_asset_ordinal[(asset, ordinal)] = target

    selected = set()
    side_slots = {"buy": set(), "sell": set()}
    for item in assignments:
        if type(item) is not dict or set(item) != {
            "side",
            "slot",
            "tier",
            "price_xch",
            "output_ordinal",
        }:
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
        try:
            price = Decimal(item["price_xch"])
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID") from None
        if type(item["price_xch"]) is not str or not price.is_finite() or price <= 0:
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
        side = item["side"]
        slot = item["slot"]
        ordinal = item["output_ordinal"]
        asset = "xch" if side == "buy" else "cat" if side == "sell" else None
        target = by_asset_ordinal.get((asset, ordinal)) if asset else None
        if (
            type(slot) is not int
            or slot < 0
            or side not in side_slots
            or type(item["tier"]) is not str
            or target is None
            or target.purpose != "replacement"
            or (asset, ordinal) in selected
            or slot in side_slots[side]
        ):
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
        selected.add((asset, ordinal))
        side_slots[side].add(slot)
    if side_slots["buy"] != set(range(funded_buy)) or side_slots["sell"] != set(
        range(funded_sell)
    ):
        raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")

    selected_targets = [
        target
        for target in targets
        if target.purpose == "fee_reserve" or (target.asset, target.ordinal) in selected
    ]
    counts = {
        "xch": {tier: 0 for tier in PREP_TIERS},
        "cat": {tier: 0 for tier in PREP_TIERS},
    }
    for target in selected_targets:
        if type(target.tier_rank) is not int or not 0 <= target.tier_rank < len(
            PREP_TIERS
        ):
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID")
        counts[target.asset][PREP_TIERS[target.tier_rank]] += 1

    args = dict(worker_args)
    args["xch_target"] = sum(counts["xch"].values())
    args["cat_target"] = sum(counts["cat"].values())
    args["tier_counts_xch"] = _count_spec(counts["xch"], PREP_TIERS)
    args["tier_counts_cat"] = _count_spec(counts["cat"], PREP_TIERS)
    exact = build_exact_prep_economics(
        configuration=configuration,
        worker_args=args,
        campaign_revision=recipe.get("economic_plan", {}).get("campaign_revision") or 0,
        target_seconds=recipe["economic_plan"]["target_seconds"],
    )
    canonical_outputs = sorted(
        (asdict(target) for target in exact["targets"]),
        key=lambda row: (row["asset"], row["ordinal"]),
    )
    return {
        **recipe,
        "targets": exact["targets"],
        "worker_args": args,
        "economic_plan": {
            **recipe["economic_plan"],
            "outputs": canonical_outputs,
        },
        "funded_buy_limit": funded_buy,
        "funded_sell_limit": funded_sell,
        "funded_target_proof_sha256": proof,
    }
