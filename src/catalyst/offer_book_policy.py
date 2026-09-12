"""Offer-book-only Smart Settings derivation for CATalyst v1.4."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapDecision,
    CampaignSide,
)


_PRESETS: dict[str, dict[str, Decimal | int]] = {
    "conservative": {
        "depth_multiple": Decimal("3"),
        "movement_persistence_refreshes": 3,
        "churn_amber": 35,
        "churn_red": 70,
        "base_spread_bps": Decimal("450"),
        "volatility_multiplier": Decimal("1.25"),
    },
    "balanced": {
        "depth_multiple": Decimal("2"),
        "movement_persistence_refreshes": 2,
        "churn_amber": 50,
        "churn_red": 80,
        "base_spread_bps": Decimal("350"),
        "volatility_multiplier": Decimal("1"),
    },
    "aggressive": {
        "depth_multiple": Decimal("1.5"),
        "movement_persistence_refreshes": 2,
        "churn_amber": 65,
        "churn_red": 90,
        "base_spread_bps": Decimal("250"),
        "volatility_multiplier": Decimal("0.75"),
    },
}


def _positive_decimal(value: Any, label: str, *, allow_zero: bool = False) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{label} must be a Decimal")
    if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{label} is invalid")
    return value


def _text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def derive_offer_book_policy(
    *,
    risk_profile: str,
    configured_offer_size_xch: Decimal,
    independent_depth_xch: Decimal,
    volatility_bps: Decimal,
    churn_score: int,
    network_fee_xch: Decimal,
    expected_cancel_requotes: int,
    minimum_profit_xch: Decimal,
) -> dict[str, Any]:
    """Return visible, deterministic thresholds without any AMM dependency."""

    preset_name = str(risk_profile).strip().lower()
    if preset_name not in _PRESETS:
        raise ValueError("risk_profile must be conservative, balanced, or aggressive")
    offer_size = _positive_decimal(
        configured_offer_size_xch, "configured_offer_size_xch"
    )
    depth = _positive_decimal(
        independent_depth_xch, "independent_depth_xch", allow_zero=True
    )
    volatility = _positive_decimal(volatility_bps, "volatility_bps", allow_zero=True)
    fee = _positive_decimal(network_fee_xch, "network_fee_xch", allow_zero=True)
    minimum_profit = _positive_decimal(
        minimum_profit_xch, "minimum_profit_xch", allow_zero=True
    )
    if type(churn_score) is not int or not 0 <= churn_score <= 100:
        raise ValueError("churn_score must be an integer from 0 to 100")
    if type(expected_cancel_requotes) is not int or expected_cancel_requotes < 0:
        raise ValueError("expected_cancel_requotes must be nonnegative")

    preset = _PRESETS[preset_name]
    depth_multiple = Decimal(preset["depth_multiple"])
    minimum_depth = offer_size * depth_multiple
    profit_floor = fee * Decimal(1 + expected_cancel_requotes) + minimum_profit
    spread_floor = profit_floor / offer_size * Decimal(10_000)
    churn_widening = Decimal(churn_score) * Decimal("2")
    recommended_spread = max(
        spread_floor,
        Decimal(preset["base_spread_bps"])
        + volatility * Decimal(preset["volatility_multiplier"])
        + churn_widening,
    )
    opportunity_size = min(offer_size * Decimal("0.5"), depth * Decimal("0.02"))
    opportunity_enabled = bool(
        depth >= minimum_depth and churn_score < int(preset["churn_amber"])
    )
    return {
        "market_model": "offer_book",
        "risk_profile": preset_name,
        "independent_depth_xch": _text(depth),
        "independent_depth_sufficient": depth >= minimum_depth,
        "minimum_independent_depth_xch": _text(minimum_depth),
        "profit_floor_xch": _text(profit_floor),
        "spread_floor_bps": _text(spread_floor),
        "recommended_spread_bps": _text(recommended_spread),
        "derived_thresholds": {
            "editable": False,
            "depth_multiple": _text(depth_multiple),
            "movement_persistence_refreshes": int(
                preset["movement_persistence_refreshes"]
            ),
            "churn_amber": int(preset["churn_amber"]),
            "churn_red": int(preset["churn_red"]),
        },
        "opportunity_orders": {
            "enabled": opportunity_enabled,
            "purpose": "book_opportunity",
            "max_size_xch": _text(opportunity_size),
            "requires_confirmed_depth": True,
        },
    }


def _bootstrap_decimal(
    values: dict[str, Any], key: str, *, allow_zero: bool = True
) -> Decimal:
    value = values.get(key, Decimal("0"))
    if type(value) is not Decimal:
        raise TypeError(f"{key} must be a Decimal")
    if not value.is_finite() or value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{key} is invalid")
    return value


def _split_exact(total: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    unit = total / Decimal("3")
    return unit, unit, total - unit - unit


def derive_bootstrap_plan(
    campaign: BootstrapCampaign,
    decision: BootstrapDecision,
    balances: dict[str, Any],
) -> dict[str, Any]:
    """Derive a bounded, purpose-separated three-level Bootstrap plan."""

    if type(campaign) is not BootstrapCampaign:
        raise TypeError("campaign must be a BootstrapCampaign")
    if type(decision) is not BootstrapDecision:
        raise TypeError("decision must be a BootstrapDecision")
    if type(balances) is not dict:
        raise TypeError("balances must be a dict")
    if (
        decision.minimum_price != campaign.minimum_price
        or decision.maximum_price != campaign.maximum_price
        or decision.allowed_sides != campaign.allowed_sides
    ):
        raise ValueError("Bootstrap decision does not match campaign authority")
    if type(decision.deployment_fraction) is not Decimal or not Decimal(
        "0"
    ) <= decision.deployment_fraction <= Decimal("1"):
        raise ValueError("Bootstrap deployment fraction is invalid")

    xch_available = _bootstrap_decimal(balances, "xch_available")
    cat_available = _bootstrap_decimal(balances, "cat_available")
    fee_spent = _bootstrap_decimal(balances, "fee_spent_xch")
    subsidy_spent = _bootstrap_decimal(balances, "subsidy_spent_xch")
    network_fee = _bootstrap_decimal(balances, "network_fee_xch")
    minimum_profit = _bootstrap_decimal(balances, "minimum_profit_xch")
    fee_coin_size = _bootstrap_decimal(balances, "fee_coin_size_xch")
    expected_cancel_requotes = balances.get("expected_cancel_requotes", 0)
    if type(expected_cancel_requotes) is not int or expected_cancel_requotes < 0:
        raise ValueError("expected_cancel_requotes must be nonnegative")

    mode = (
        "TWO_SIDED"
        if len(campaign.allowed_sides) == 2
        else ("BUY_ONLY" if CampaignSide.BUY in campaign.allowed_sides else "SELL_ONLY")
    )
    cancellation_reserve = campaign.fee_budget_xch * Decimal("0.20")
    if decision.cancellation_fee_reserve_xch != cancellation_reserve:
        raise ValueError("Bootstrap cancellation fee reserve is invalid")
    creation_limit = campaign.fee_budget_xch - cancellation_reserve
    creation_fee_available = max(Decimal("0"), creation_limit - fee_spent)
    subsidy_available = max(Decimal("0"), campaign.subsidy_budget_xch - subsidy_spent)

    plan: dict[str, Any] = {
        "authorized": False,
        "mode": mode,
        "stage": decision.stage.value,
        "deployment_fraction": decision.deployment_fraction,
        "anchor_price": decision.anchor_price,
        "minimum_price": decision.minimum_price,
        "maximum_price": decision.maximum_price,
        "sides": {
            "buy": {"paused": True, "levels": []},
            "sell": {"paused": True, "levels": []},
        },
        "reason_codes": tuple(decision.reason_codes),
        "subsidy_used_xch": Decimal("0"),
        "cancellation_fee_reserve_xch": cancellation_reserve,
        "creation_fee_available_xch": creation_fee_available,
        "creation_fee_required_xch": Decimal("0"),
        "fee_budget_after_plan_xch": campaign.fee_budget_xch - fee_spent,
        "coin_prep": {
            "campaign_asset_id": campaign.asset_id,
            "xch_offer_coins": [],
            "cat_offer_coins": [],
            "fee_coins": [],
            "excluded_xch": {},
            "excluded_purposes": (
                "campaign_protected",
                "cancellation_reserve",
                "unrelated_wallet",
                "unresolved_effect",
                "existing_offer",
            ),
        },
    }
    if not decision.authorized:
        return plan

    active_sides = campaign.allowed_sides - decision.cooldown_sides
    xch_deployment = min(
        campaign.xch_budget * decision.deployment_fraction,
        xch_available,
    )
    cat_deployment = min(
        campaign.cat_budget * decision.deployment_fraction,
        cat_available,
    )
    reasons = list(decision.reason_codes)
    if CampaignSide.BUY in active_sides and xch_deployment == 0:
        active_sides = active_sides - {CampaignSide.BUY}
        reasons.append("buy_inventory_depleted")
    if CampaignSide.SELL in active_sides and cat_deployment == 0:
        active_sides = active_sides - {CampaignSide.SELL}
        reasons.append("sell_inventory_depleted")
    for side in decision.cooldown_sides:
        reasons.append(f"{side.value}_adverse_fill_cooldown")

    xch_stage_target = campaign.xch_budget * decision.deployment_fraction
    cat_stage_target = campaign.cat_budget * decision.deployment_fraction
    xch_ratio = (
        min(Decimal("1"), xch_available / xch_stage_target)
        if xch_stage_target > 0
        else Decimal("0")
    )
    cat_ratio = (
        min(Decimal("1"), cat_available / cat_stage_target)
        if cat_stage_target > 0
        else Decimal("0")
    )
    inventory_skew = Decimal("0")
    if len(active_sides) == 2:
        inventory_skew = (cat_ratio - xch_ratio) * Decimal("0.02")
        inventory_skew = min(Decimal("0.02"), max(Decimal("-0.02"), inventory_skew))

    trusted_bid = balances.get("trusted_bid")
    trusted_ask = balances.get("trusted_ask")
    for value, label in ((trusted_bid, "trusted_bid"), (trusted_ask, "trusted_ask")):
        if value is not None and (
            type(value) is not Decimal or not value.is_finite() or value <= 0
        ):
            raise ValueError(f"{label} is invalid")

    price_shapes = {
        CampaignSide.BUY: (Decimal("0.98"), Decimal("0.95"), Decimal("0.90")),
        CampaignSide.SELL: (Decimal("1.02"), Decimal("1.05"), Decimal("1.10")),
    }
    amounts = {
        CampaignSide.BUY: _split_exact(xch_deployment),
        CampaignSide.SELL: _split_exact(cat_deployment),
    }
    level_names = ("near", "middle", "far")
    all_levels: list[dict[str, Any]] = []
    for side in (CampaignSide.BUY, CampaignSide.SELL):
        if side not in active_sides:
            continue
        levels: list[dict[str, Any]] = []
        for level_name, shape, amount in zip(
            level_names, price_shapes[side], amounts[side], strict=True
        ):
            raw_price = decision.anchor_price * (shape - inventory_skew)
            price = min(
                decision.maximum_price,
                max(decision.minimum_price, raw_price),
            )
            if side is CampaignSide.BUY:
                price = min(price, decision.anchor_price)
                if trusted_bid is not None:
                    if trusted_bid < decision.minimum_price:
                        levels = []
                        reasons.append("buy_trusted_range_outside_corridor")
                        break
                    price = min(price, trusted_bid)
                xch_amount = amount
                cat_amount = xch_amount / price
                expected_gross = cat_amount * (decision.anchor_price - price)
            else:
                price = max(price, decision.anchor_price)
                if trusted_ask is not None:
                    if trusted_ask > decision.maximum_price:
                        levels = []
                        reasons.append("sell_trusted_range_outside_corridor")
                        break
                    price = max(price, trusted_ask)
                cat_amount = amount
                xch_amount = cat_amount * price
                expected_gross = cat_amount * (price - decision.anchor_price)
            level = {
                "level": level_name,
                "side": side.value,
                "price": price,
                "xch_amount": xch_amount,
                "cat_amount": cat_amount,
                "expected_gross_xch": expected_gross,
                "subsidy_xch": Decimal("0"),
            }
            levels.append(level)
            all_levels.append(level)
        plan["sides"][side.value] = {
            "paused": not bool(levels),
            "levels": levels,
        }

    fee_per_offer = network_fee * Decimal(1 + expected_cancel_requotes)
    creation_fee_required = fee_per_offer * Decimal(len(all_levels))
    if creation_fee_required > creation_fee_available:
        plan["reason_codes"] = ("bootstrap_creation_fee_budget_exhausted",)
        return plan

    profit_floor = fee_per_offer + minimum_profit
    subsidy_required = sum(
        max(Decimal("0"), profit_floor - level["expected_gross_xch"])
        for level in all_levels
    )
    if subsidy_required > subsidy_available:
        plan["reason_codes"] = ("bootstrap_profit_floor_unfunded",)
        return plan
    for level in all_levels:
        level["subsidy_xch"] = max(
            Decimal("0"), profit_floor - level["expected_gross_xch"]
        )

    fee_budget_after_plan = campaign.fee_budget_xch - fee_spent - creation_fee_required
    if fee_budget_after_plan < cancellation_reserve:
        plan["reason_codes"] = ("bootstrap_cancellation_fee_reserve_protected",)
        return plan

    xch_levels = plan["sides"]["buy"]["levels"]
    cat_levels = plan["sides"]["sell"]["levels"]
    plan["coin_prep"] = {
        "campaign_asset_id": campaign.asset_id,
        "xch_offer_coins": [
            {
                "purpose": "bootstrap_buy",
                "level": level["level"],
                "amount_xch": level["xch_amount"],
            }
            for level in xch_levels
        ],
        "cat_offer_coins": [
            {
                "purpose": "bootstrap_sell",
                "level": level["level"],
                "amount_cat": level["cat_amount"],
            }
            for level in cat_levels
        ],
        "fee_coins": [
            {
                "purpose": "bootstrap_fee",
                "level": level["level"],
                "side": level["side"],
                "amount_xch": fee_coin_size,
            }
            for level in all_levels
            if network_fee > 0
        ],
        "excluded_xch": {
            "campaign_undeployed_xch": campaign.xch_budget - xch_deployment,
            "cancellation_fee_reserve_xch": cancellation_reserve,
            "subsidy_remaining_xch": subsidy_available - subsidy_required,
        },
        "excluded_purposes": (
            "campaign_protected",
            "cancellation_reserve",
            "unrelated_wallet",
            "unresolved_effect",
            "existing_offer",
        ),
    }
    plan.update(
        authorized=bool(all_levels),
        reason_codes=tuple(dict.fromkeys(reasons)),
        subsidy_used_xch=subsidy_required,
        creation_fee_required_xch=creation_fee_required,
        fee_budget_after_plan_xch=fee_budget_after_plan,
        inventory_skew_fraction=inventory_skew,
    )
    return plan
