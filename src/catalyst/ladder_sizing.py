"""Pure ladder sizing helpers shared by prep, validation, and offer creation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Optional, Tuple


TIER_ORDER = ("inner", "mid", "outer", "extreme")


@dataclass(frozen=True)
class SellLadderCatSummary:
    live_cat_total: Decimal
    tier_live_cat: Dict[str, Decimal]
    max_cat_per_tier: Dict[str, Decimal]
    first_price_per_tier: Dict[str, Decimal]
    tier_counts: Dict[str, int]


def _decimal(value, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def normalize_tier_counts(
    max_offers: int,
    tier_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    dist = {tier: 0 for tier in TIER_ORDER}
    max_offers = max(0, int(max_offers or 0))
    if max_offers <= 0:
        return dist

    configured = {
        tier: max(0, int((tier_counts or {}).get(tier, 0) or 0)) for tier in TIER_ORDER
    }
    if any(configured.values()):
        remaining = max_offers
        for tier in TIER_ORDER:
            take = min(configured[tier], remaining)
            dist[tier] = take
            remaining -= take
        if remaining > 0:
            dist["extreme"] += remaining
        return dist

    for slot in range(max_offers):
        ratio = Decimal(slot) / Decimal(max_offers)
        if ratio < Decimal("0.1"):
            dist["inner"] += 1
        elif ratio < Decimal("0.4"):
            dist["mid"] += 1
        elif ratio < Decimal("0.7"):
            dist["outer"] += 1
        else:
            dist["extreme"] += 1
    return dist


def classify_slot_tier(
    slot: int,
    total_slots: int,
    tier_counts: Optional[Dict[str, int]] = None,
) -> str:
    if total_slots <= 0:
        return "mid"

    dist = normalize_tier_counts(total_slots, tier_counts=tier_counts)
    running = 0
    for tier in TIER_ORDER:
        running += dist[tier]
        if slot < running:
            return tier
    return "extreme"


def thin_market_edges(
    *, trusted_bid, trusted_ask, step_bps
) -> Optional[Tuple[Decimal, Decimal]]:
    """Return the (buy, sell) inner-slot prices just inside the outside book.

    The inner buy sits ``step_bps`` above the best outside bid and the inner
    sell ``step_bps`` below the best outside ask.  Returns None when the edges
    are unknown or too close together to step inside without crossing.
    """
    if trusted_bid is None or trusted_ask is None:
        return None
    bid = _decimal(trusted_bid)
    ask = _decimal(trusted_ask)
    step = _decimal(step_bps) / Decimal("10000")
    if bid <= 0 or ask <= bid or step < 0:
        return None
    buy_edge = bid * (Decimal("1") + step)
    sell_edge = ask * (Decimal("1") - step)
    if buy_edge >= sell_edge:
        return None
    return buy_edge, sell_edge


def thin_market_side_mid(
    side: str,
    *,
    trusted_bid,
    trusted_ask,
    step_bps,
    min_edge_bps=Decimal("0"),
) -> Optional[Decimal]:
    """Back-solve a side-specific ladder mid from the outside book edge.

    Used as the per-side reference for drift and requote decisions: it moves
    in proportion to that side's own outside edge and nothing else.
    """
    if side not in ("buy", "sell"):
        return None
    edges = thin_market_edges(
        trusted_bid=trusted_bid, trusted_ask=trusted_ask, step_bps=step_bps
    )
    inner_edge = _decimal(min_edge_bps) / Decimal("10000")
    if edges is None or not Decimal("0") <= inner_edge < 1:
        return None
    buy_edge, sell_edge = edges
    if side == "buy":
        return buy_edge / (Decimal("1") - inner_edge)
    return sell_edge / (Decimal("1") + inner_edge)


def thin_market_slot_price(
    slot: int, side: str, edge_price, depth_bps, max_offers: int
) -> Optional[Decimal]:
    """Price one slot of a ladder that starts at its outside-book edge.

    Slot 0 sits at ``edge_price``; the last slot sits ``depth_bps`` further
    from the market (lower for buys, higher for sells), evenly stepped.
    """
    max_offers = int(max_offers or 0)
    edge = _decimal(edge_price)
    depth = _decimal(depth_bps) / Decimal("10000")
    if max_offers <= 0 or edge <= 0 or depth < 0 or side not in ("buy", "sell"):
        return None
    index = min(max(0, int(slot or 0)), max_offers - 1)
    distance = (
        Decimal("0") if max_offers == 1 else depth * Decimal(index) / (max_offers - 1)
    )
    if side == "buy":
        price = edge * (Decimal("1") - distance)
    else:
        price = edge * (Decimal("1") + distance)
    return price if price > 0 else None


def ladder_price_for_slot(
    slot: int,
    side: str,
    mid_price,
    spread_fraction,
    max_offers: int,
    min_edge_bps=Decimal("0"),
) -> Optional[Decimal]:
    max_offers = int(max_offers or 0)
    if max_offers <= 0:
        return None

    mid = _decimal(mid_price)
    spread = _decimal(spread_fraction)
    min_edge = _decimal(min_edge_bps) / Decimal("10000")
    if mid <= 0:
        return None

    if min_edge >= spread:
        distance = spread
    elif max_offers == 1:
        distance = min_edge
    else:
        step = (spread - min_edge) / Decimal(max_offers - 1)
        distance = min_edge + step * Decimal(max(0, int(slot or 0)))

    if (side or "").lower() == "buy":
        price = mid * (Decimal("1") - distance)
    else:
        price = mid * (Decimal("1") + distance)

    if price <= 0:
        return None
    return price


def summarize_sell_ladder_cat(
    *,
    mid_price,
    spread_fraction,
    max_offers: int,
    tier_counts: Optional[Dict[str, int]],
    tier_sizes_xch: Dict[str, Decimal],
    min_edge_bps=Decimal("0"),
) -> SellLadderCatSummary:
    dist = normalize_tier_counts(max_offers, tier_counts=tier_counts)
    tier_live_cat = {tier: Decimal("0") for tier in TIER_ORDER}
    max_cat_per_tier = {tier: Decimal("0") for tier in TIER_ORDER}
    first_price_per_tier: Dict[str, Decimal] = {}
    live_total = Decimal("0")

    for slot in range(max(0, int(max_offers or 0))):
        tier = classify_slot_tier(slot, max_offers, tier_counts=tier_counts)
        size_xch = _decimal((tier_sizes_xch or {}).get(tier, 0))
        if size_xch <= 0:
            continue
        price = ladder_price_for_slot(
            slot,
            "sell",
            mid_price,
            spread_fraction,
            max_offers,
            min_edge_bps=min_edge_bps,
        )
        if price is None or price <= 0:
            continue

        first_price_per_tier.setdefault(tier, price)
        cat_amount = size_xch / price
        tier_live_cat[tier] += cat_amount
        if cat_amount > max_cat_per_tier[tier]:
            max_cat_per_tier[tier] = cat_amount
        live_total += cat_amount

    return SellLadderCatSummary(
        live_cat_total=live_total,
        tier_live_cat=tier_live_cat,
        max_cat_per_tier=max_cat_per_tier,
        first_price_per_tier=first_price_per_tier,
        tier_counts=dist,
    )


def prepared_sell_ladder_cat_total(
    *,
    mid_price,
    spread_bps,
    min_edge_bps,
    max_sell: int,
    tier_counts: Optional[Dict[str, int]],
    tier_spares: Optional[Dict[str, int]],
    tier_sizes_xch: Dict[str, Decimal],
    headroom_mult,
) -> int:
    try:
        max_offers = int(max_sell or 0)
    except (TypeError, ValueError):
        max_offers = 0
    counts = {
        tier: max(0, int((tier_counts or {}).get(tier, 0) or 0)) for tier in TIER_ORDER
    }
    if max_offers <= 0:
        max_offers = sum(counts.values())
    if max_offers <= 0:
        return 0

    summary = summarize_sell_ladder_cat(
        mid_price=mid_price,
        spread_fraction=_decimal(spread_bps) / Decimal("10000"),
        max_offers=max_offers,
        tier_counts=counts,
        tier_sizes_xch=tier_sizes_xch,
        min_edge_bps=min_edge_bps,
    )
    headroom = _decimal(headroom_mult, "1")
    spares = {
        tier: max(0, int((tier_spares or {}).get(tier, 0) or 0)) for tier in TIER_ORDER
    }

    total = 0
    for tier in TIER_ORDER:
        per_coin = summary.max_cat_per_tier[tier]
        if per_coin <= 0:
            continue
        prepared = int((per_coin * headroom).to_integral_value(rounding=ROUND_HALF_UP))
        total += (summary.tier_counts[tier] + spares[tier]) * prepared
    return total
