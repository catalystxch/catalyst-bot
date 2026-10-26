"""Pure arithmetic and prepared-denomination check for a Follow initial book."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_DOWN

from ladder_sizing import TIER_ORDER, classify_slot_tier, ladder_price_for_slot


def _positive_decimal(value: Decimal) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise ValueError("FOLLOW_SLOT_INPUT_INVALID")
    return value


def prove_initial_follow_slot_fit(
    *,
    buy_limit: int,
    sell_limit: int,
    mid_price: Decimal,
    half_spread: Decimal,
    min_edge_bps: Decimal,
    buy_tier_counts: dict,
    sell_tier_counts: dict,
    buy_tier_sizes_xch: dict,
    sell_tier_sizes_xch: dict,
    buy_reversed: bool,
    cat_decimals: int,
    max_coin_size_ratio: Decimal,
    maximum_trade_xch_mojos: int,
    maximum_trade_cat_atoms: int,
    outputs: list[dict],
) -> dict:
    """Require one fitting approved replacement denomination per initial slot.

    This does not prove live market confidence, price bounds, DB tier labels,
    offer profitability, or wallet dispatch. The caller must separately prove
    that each approved output still maps to one selectable wallet coin.
    """

    if (
        type(buy_limit) is not int
        or type(sell_limit) is not int
        or not 1 <= buy_limit <= 50
        or not 1 <= sell_limit <= 50
        or type(buy_reversed) is not bool
        or type(cat_decimals) is not int
        or not 0 <= cat_decimals <= 18
        or type(maximum_trade_xch_mojos) is not int
        or type(maximum_trade_cat_atoms) is not int
        or maximum_trade_xch_mojos <= 0
        or maximum_trade_cat_atoms <= 0
        or type(outputs) is not list
        or len(outputs) > 128
    ):
        raise ValueError("FOLLOW_SLOT_INPUT_INVALID")
    mid = _positive_decimal(mid_price)
    spread = _positive_decimal(half_spread)
    ratio = _positive_decimal(max_coin_size_ratio)
    if (
        type(min_edge_bps) is not Decimal
        or not min_edge_bps.is_finite()
        or min_edge_bps < 0
        or type(buy_tier_counts) is not dict
        or type(sell_tier_counts) is not dict
        or type(buy_tier_sizes_xch) is not dict
        or type(sell_tier_sizes_xch) is not dict
        or any(
            type(value) is not int or value < 0
            for value in (*buy_tier_counts.values(), *sell_tier_counts.values())
        )
        or any(
            type(value) is not Decimal or not value.is_finite() or value < 0
            for value in (*buy_tier_sizes_xch.values(), *sell_tier_sizes_xch.values())
        )
        or set(buy_tier_counts) - set(TIER_ORDER)
        or set(sell_tier_counts) - set(TIER_ORDER)
        or set(buy_tier_sizes_xch) - set(TIER_ORDER)
        or set(sell_tier_sizes_xch) - set(TIER_ORDER)
    ):
        raise ValueError("FOLLOW_SLOT_INPUT_INVALID")

    coins: dict[tuple[str, int], list[tuple[int, int]]] = {}
    seen = set()
    for output in outputs:
        if type(output) is not dict or set(output) != {
            "asset",
            "purpose",
            "tier_rank",
            "amount_mojos",
            "ordinal",
        }:
            raise ValueError("FOLLOW_SLOT_PLAN_INVALID")
        asset = output["asset"]
        purpose = output["purpose"]
        rank = output["tier_rank"]
        amount = output["amount_mojos"]
        ordinal = output["ordinal"]
        if (
            type(asset) is not str
            or asset not in {"xch", "cat"}
            or type(purpose) is not str
            or purpose not in {"replacement", "fee_reserve"}
            or type(rank) is not int
            or not 0 <= rank <= len(TIER_ORDER)
            or type(amount) is not int
            or amount <= 0
            or type(ordinal) is not int
            or ordinal < 0
            or (asset, ordinal) in seen
            or (
                purpose == "fee_reserve" and (asset != "xch" or rank != len(TIER_ORDER))
            )
        ):
            raise ValueError("FOLLOW_SLOT_PLAN_INVALID")
        seen.add((asset, ordinal))
        if purpose == "replacement":
            if rank == len(TIER_ORDER):
                raise ValueError("FOLLOW_SLOT_PLAN_INVALID")
            coins.setdefault((asset, rank), []).append((amount, ordinal))
    for options in coins.values():
        options.sort()

    required = {"xch": 0, "cat": 0}
    assignments = []
    for side, limit, counts, sizes, asset in (
        ("buy", buy_limit, buy_tier_counts, buy_tier_sizes_xch, "xch"),
        ("sell", sell_limit, sell_tier_counts, sell_tier_sizes_xch, "cat"),
    ):
        if sum(counts.values()) != limit:
            raise ValueError("FOLLOW_SLOT_TIER_COUNTS_INVALID")
        for slot in range(limit):
            tier = classify_slot_tier(slot, limit, tier_counts=counts)
            size = sizes.get(tier)
            if size is None or size <= 0:
                raise ValueError("FOLLOW_SLOT_TIER_COUNTS_INVALID")
            price = ladder_price_for_slot(
                slot, side, mid, spread, limit, min_edge_bps=min_edge_bps
            )
            if price is None or price <= 0:
                raise ValueError("FOLLOW_SLOT_PRICE_INVALID")
            amount = size if side == "buy" else size / price
            scale = 12 if side == "buy" else cat_decimals
            atoms = int(
                (amount * Decimal(10**scale)).to_integral_value(rounding=ROUND_DOWN)
            )
            if atoms <= 0:
                raise ValueError("FOLLOW_SLOT_AMOUNT_INVALID")
            coin_tier = (
                TIER_ORDER[::-1][TIER_ORDER.index(tier)]
                if side == "buy" and buy_reversed
                else tier
            )
            options = coins.get((asset, TIER_ORDER.index(coin_tier)), [])
            cap = int(Decimal(atoms) * ratio)
            selected = next(
                (
                    index
                    for index, (coin_amount, _) in enumerate(options)
                    if atoms <= coin_amount <= cap
                ),
                None,
            )
            if selected is None:
                raise ValueError("FOLLOW_SLOT_DENOMINATION_SHORT")
            coin_amount, ordinal = options.pop(selected)
            required[asset] += atoms
            assignments.append(
                (side, slot, tier, format(price, "f"), atoms, ordinal, coin_amount)
            )
    if (
        required["xch"] > maximum_trade_xch_mojos
        or required["cat"] > maximum_trade_cat_atoms
    ):
        raise ValueError("FOLLOW_SLOT_PRINCIPAL_SHORT")
    digest_terms = {
        "buy_limit": buy_limit,
        "sell_limit": sell_limit,
        "mid_price": format(mid, "f"),
        "half_spread": format(spread, "f"),
        "min_edge_bps": format(min_edge_bps, "f"),
        "max_coin_size_ratio": format(ratio, "f"),
        "cat_decimals": cat_decimals,
        "buy_reversed": buy_reversed,
        "assignments": assignments,
    }
    digest = hashlib.sha256(
        json.dumps(digest_terms, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "buy_slots_arithmetic_fit": buy_limit,
        "sell_slots_arithmetic_fit": sell_limit,
        "required_xch_mojos": required["xch"],
        "required_cat_atoms": required["cat"],
        "slot_assignment_sha256": digest,
        "dispatch_authorized": False,
    }


def preview_current_follow_slot_fit(
    *,
    configuration: dict,
    outputs: list[dict],
    buy_limit: int,
    sell_limit: int,
    maximum_trade_xch_mojos: int,
    maximum_trade_cat_atoms: int,
) -> dict:
    """Apply current production tier sizes to a read-only executable quote.

    The approved prep snapshot supplied by the caller already revalidated
    wallet identity, settings and denominations. This arithmetic check still
    grants neither a Follow review nor trading authority.
    """

    import api_server
    from config import cfg, get_tier_sizes_for_side

    if (
        type(configuration) is not dict
        or configuration.get("LIQUIDITY_MODE") != "two_sided"
        or configuration.get("TIER_ENABLED") is not True
        or configuration.get("BUY_LADDER_REVERSED")
        is not getattr(cfg, "BUY_LADDER_REVERSED", None)
        or configuration.get("MAX_ACTIVE_BUY_OFFERS") != buy_limit
        or configuration.get("MAX_ACTIVE_SELL_OFFERS") != sell_limit
        or getattr(cfg, "ENABLE_BUY", None) is not True
        or getattr(cfg, "ENABLE_SELL", None) is not True
        or getattr(cfg, "DRY_RUN", None) is not False
        or getattr(cfg, "COIN_IDS_ENABLED", None) is not True
        or getattr(cfg, "TIER_ENABLED", None) is not True
    ):
        raise ValueError("FOLLOW_SLOT_CONFIGURATION_MISMATCH")
    try:
        spread_bps = Decimal(configuration["SPREAD_BPS"])
        min_edge_bps = Decimal(configuration["MIN_EDGE_BPS"])
        ratio = Decimal(str(cfg.COIN_MAX_SIZE_RATIO))
        first_quote = api_server._get_readonly_mid_price_str()
        mid = Decimal(first_quote)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ValueError("FOLLOW_SLOT_PRICE_UNAVAILABLE") from None
    counts = {
        side: {
            tier: configuration.get(f"{side.upper()}_{tier.upper()}_TIER_COUNT", 0)
            for tier in TIER_ORDER
        }
        for side in ("buy", "sell")
    }
    result = prove_initial_follow_slot_fit(
        buy_limit=buy_limit,
        sell_limit=sell_limit,
        mid_price=mid,
        half_spread=spread_bps / Decimal("20000"),
        min_edge_bps=min_edge_bps,
        buy_tier_counts=counts["buy"],
        sell_tier_counts=counts["sell"],
        buy_tier_sizes_xch=get_tier_sizes_for_side("buy"),
        sell_tier_sizes_xch=get_tier_sizes_for_side("sell"),
        buy_reversed=configuration["BUY_LADDER_REVERSED"],
        cat_decimals=configuration["CAT_DECIMALS"],
        max_coin_size_ratio=ratio,
        maximum_trade_xch_mojos=maximum_trade_xch_mojos,
        maximum_trade_cat_atoms=maximum_trade_cat_atoms,
        outputs=outputs,
    )
    if api_server._get_readonly_mid_price_str() != first_quote:
        raise ValueError("FOLLOW_SLOT_PRICE_CHANGED")
    return {**result, "readonly_mid_price_xch": format(mid, "f")}
