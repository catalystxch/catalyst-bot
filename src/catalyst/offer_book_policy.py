"""Offer-book-only Smart Settings derivation for CATalyst v1.4."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


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
    text = format(value, "f").rstrip("0").rstrip(".")
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
