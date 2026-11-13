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
    buy_target_limit: int | None = None,
    sell_target_limit: int | None = None,
) -> dict:
    """Require one fitting approved replacement denomination per initial slot.

    This does not prove live market confidence, price bounds, DB tier labels,
    offer profitability, or wallet dispatch. The caller must separately prove
    that each approved output still maps to one selectable wallet coin.
    """

    partial_targets = buy_target_limit is not None or sell_target_limit is not None
    if (buy_target_limit is None) != (sell_target_limit is None):
        raise ValueError("FOLLOW_SLOT_INPUT_INVALID")
    buy_target = buy_limit if buy_target_limit is None else buy_target_limit
    sell_target = sell_limit if sell_target_limit is None else sell_target_limit
    if (
        type(buy_limit) is not int
        or type(sell_limit) is not int
        or buy_limit < (0 if partial_targets else 1)
        or sell_limit < (0 if partial_targets else 1)
        or buy_limit > 2**63 - 1
        or sell_limit > 2**63 - 1
        or type(buy_target) is not int
        or type(sell_target) is not int
        or buy_target < 1
        or sell_target < 1
        or buy_limit > buy_target
        or sell_limit > sell_target
        or type(buy_reversed) is not bool
        or type(cat_decimals) is not int
        or not 0 <= cat_decimals <= 18
        or type(maximum_trade_xch_mojos) is not int
        or type(maximum_trade_cat_atoms) is not int
        or maximum_trade_xch_mojos <= 0
        or maximum_trade_cat_atoms <= 0
        or type(outputs) is not list
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

    if sum(
        len(options)
        for (asset, _rank), options in coins.items()
        if asset == "xch"
    ) < buy_limit or sum(
        len(options)
        for (asset, _rank), options in coins.items()
        if asset == "cat"
    ) < sell_limit:
        raise ValueError("FOLLOW_SLOT_DENOMINATION_SHORT")

    required = {"xch": 0, "cat": 0}
    assigned_sources = {"xch": 0, "cat": 0}
    assignments = []
    for side, limit, counts, sizes, asset in (
        ("buy", buy_limit, buy_tier_counts, buy_tier_sizes_xch, "xch"),
        ("sell", sell_limit, sell_tier_counts, sell_tier_sizes_xch, "cat"),
    ):
        target = buy_target if side == "buy" else sell_target
        if sum(counts.values()) != target:
            raise ValueError("FOLLOW_SLOT_TIER_COUNTS_INVALID")
        for slot in range(limit):
            tier = classify_slot_tier(slot, target, tier_counts=counts)
            size = sizes.get(tier)
            if size is None or size <= 0:
                raise ValueError("FOLLOW_SLOT_TIER_COUNTS_INVALID")
            price = ladder_price_for_slot(
                slot, side, mid, spread, target, min_edge_bps=min_edge_bps
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
            assigned_sources[asset] += coin_amount
            assignments.append(
                (side, slot, tier, format(price, "f"), atoms, ordinal, coin_amount)
            )
    if (
        required["xch"] > maximum_trade_xch_mojos
        or required["cat"] > maximum_trade_cat_atoms
    ):
        raise ValueError("FOLLOW_SLOT_PRINCIPAL_SHORT")
    if (
        assigned_sources["xch"] > maximum_trade_xch_mojos
        or assigned_sources["cat"] > maximum_trade_cat_atoms
    ):
        raise ValueError("FOLLOW_SLOT_SOURCE_PRINCIPAL_SHORT")
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
        "assigned_xch_coin_mojos": assigned_sources["xch"],
        "assigned_cat_coin_atoms": assigned_sources["cat"],
        "slot_assignment_sha256": digest,
        "dispatch_authorized": False,
    }


def find_fundable_follow_slot_limits(
    *,
    buy_target: int,
    sell_target: int,
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
    """Find the largest independently fundable prefix on each side.

    The signed targets and tier distribution stay fixed. A partial initial
    book uses the same prefix of those target slots, so its prices and source
    denominations remain consistent with the approved full ladder. This is
    an initial funding proof only; later top-ups must recompute it.
    """
    if (
        type(buy_target) is not int
        or type(sell_target) is not int
        or buy_target < 1
        or sell_target < 1
        or buy_target > 2**63 - 1
        or sell_target > 2**63 - 1
    ):
        raise ValueError("FOLLOW_SLOT_INPUT_INVALID")

    def max_prefix(side: str) -> int:
        low, high = 0, buy_target if side == "buy" else sell_target
        best = 0
        while low <= high:
            candidate = (low + high) // 2
            buy_limit = candidate if side == "buy" else 0
            sell_limit = candidate if side == "sell" else 0
            try:
                prove_initial_follow_slot_fit(
                    buy_limit=buy_limit,
                    sell_limit=sell_limit,
                    buy_target_limit=buy_target,
                    sell_target_limit=sell_target,
                    mid_price=mid_price,
                    half_spread=half_spread,
                    min_edge_bps=min_edge_bps,
                    buy_tier_counts=buy_tier_counts,
                    sell_tier_counts=sell_tier_counts,
                    buy_tier_sizes_xch=buy_tier_sizes_xch,
                    sell_tier_sizes_xch=sell_tier_sizes_xch,
                    buy_reversed=buy_reversed,
                    cat_decimals=cat_decimals,
                    max_coin_size_ratio=max_coin_size_ratio,
                    maximum_trade_xch_mojos=maximum_trade_xch_mojos,
                    maximum_trade_cat_atoms=maximum_trade_cat_atoms,
                    outputs=outputs,
                )
                best = candidate
                low = candidate + 1
            except ValueError:
                high = candidate - 1
        return best

    buy_limit = max_prefix("buy")
    sell_limit = max_prefix("sell")
    fit = prove_initial_follow_slot_fit(
        buy_limit=buy_limit,
        sell_limit=sell_limit,
        buy_target_limit=buy_target,
        sell_target_limit=sell_target,
        mid_price=mid_price,
        half_spread=half_spread,
        min_edge_bps=min_edge_bps,
        buy_tier_counts=buy_tier_counts,
        sell_tier_counts=sell_tier_counts,
        buy_tier_sizes_xch=buy_tier_sizes_xch,
        sell_tier_sizes_xch=sell_tier_sizes_xch,
        buy_reversed=buy_reversed,
        cat_decimals=cat_decimals,
        max_coin_size_ratio=max_coin_size_ratio,
        maximum_trade_xch_mojos=maximum_trade_xch_mojos,
        maximum_trade_cat_atoms=maximum_trade_cat_atoms,
        outputs=outputs,
    )
    return {
        **fit,
        "buy_target": buy_target,
        "sell_target": sell_target,
        "funded_buy_limit": buy_limit,
        "funded_sell_limit": sell_limit,
        "partial_target": buy_limit < buy_target or sell_limit < sell_target,
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
    allow_partial: bool = False,
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
    fit_terms = {
        "mid_price": mid,
        "half_spread": spread_bps / Decimal("20000"),
        "min_edge_bps": min_edge_bps,
        "buy_tier_counts": counts["buy"],
        "sell_tier_counts": counts["sell"],
        "buy_tier_sizes_xch": get_tier_sizes_for_side("buy"),
        "sell_tier_sizes_xch": get_tier_sizes_for_side("sell"),
        "buy_reversed": configuration["BUY_LADDER_REVERSED"],
        "cat_decimals": configuration["CAT_DECIMALS"],
        "max_coin_size_ratio": ratio,
        "maximum_trade_xch_mojos": maximum_trade_xch_mojos,
        "maximum_trade_cat_atoms": maximum_trade_cat_atoms,
        "outputs": outputs,
    }
    if allow_partial:
        result = find_fundable_follow_slot_limits(
            buy_target=buy_limit, sell_target=sell_limit, **fit_terms
        )
    else:
        result = prove_initial_follow_slot_fit(
            buy_limit=buy_limit, sell_limit=sell_limit, **fit_terms
        )
    if api_server._get_readonly_mid_price_str() != first_quote:
        raise ValueError("FOLLOW_SLOT_PRICE_CHANGED")
    return {**result, "readonly_mid_price_xch": format(mid, "f")}
