"""Pure frozen Coin Prep economics shared by fee previews and execution.

No wallet, database or provider reads occur here. Runtime callers supply trusted
configuration/campaign snapshots. Generated worker overrides contain exact
prepared amounts with zero additional headroom; dispatch must adopt the frozen
target contract, not independently re-price or re-size an approved recipe.
"""

from dataclasses import asdict
from decimal import Decimal, DecimalException, ROUND_CEILING, ROUND_HALF_EVEN
import re

from amount_utils import round_cat_display_amount_up_to_mojo
from coin_prep_targets import MAX_ATOMIC_AMOUNT, MAX_PLAN_OUTPUTS, build_prep_targets
from ladder_sizing import TIER_ORDER, summarize_sell_ladder_cat


PREP_TIERS = (*TIER_ORDER, "fees")
_REVERSED = dict(zip(TIER_ORDER, reversed(TIER_ORDER)))


def _integer(value, minimum=0, maximum=MAX_ATOMIC_AMOUNT):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Coin Prep requires an exact bounded integer")
    return value


def _decimal(value, minimum=Decimal("0"), maximum=None):
    if type(value) not in (str, int, Decimal) or len(str(value)) > 128:
        raise ValueError("Coin Prep requires an exact decimal")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < minimum or (maximum is not None and amount > maximum):
            raise ValueError("Coin Prep decimal is outside supported bounds")
        return amount
    except DecimalException as exc:
        raise ValueError("Coin Prep decimal is invalid") from exc


def _text(amount):
    text = format(amount, "f")
    return (text.rstrip("0").rstrip(".") if "." in text else text) if amount else "0"


def normalize_fee_prep_options(options):
    """Accept choices only; wallet/economic authority never comes from clients."""
    allowed = {"coin_multiplier", "target_seconds", "bootstrap_campaign_id", "bootstrap_campaign_revision"}
    try:
        if type(options) is not dict or set(options) - allowed:
            raise ValueError("unknown request fields")
        result = {"coin_multiplier": _text(_decimal(options.get("coin_multiplier", "1"),
                                                    Decimal("0.5"), Decimal("3"))),
                  "target_seconds": _integer(options.get("target_seconds", 300), 1, 86_400)}
        if "bootstrap_campaign_id" in options or "bootstrap_campaign_revision" in options:
            campaign_id = options.get("bootstrap_campaign_id")
            if type(campaign_id) is not str or re.fullmatch(r"[0-9a-f]{64}", campaign_id) is None:
                raise ValueError("invalid campaign identity")
            result.update(bootstrap_campaign_id=campaign_id,
                          bootstrap_campaign_revision=_integer(options.get("bootstrap_campaign_revision")))
        return result
    except ValueError:
        raise ValueError("FEE_PREP_OPTIONS_INVALID") from None


def validate_fee_pool_configuration(configuration):
    """Do not let legacy fee-pool coercion change frozen preview economics."""
    try:
        _integer(configuration["FEE_PREP_COUNT"], 0, MAX_PLAN_OUTPUTS)
        _decimal(configuration["FEE_COIN_SIZE_XCH"],
                 maximum=Decimal(MAX_ATOMIC_AMOUNT) / Decimal(10**12))
    except (KeyError, TypeError, ValueError):
        raise ValueError("FEE_PREP_CONFIGURATION_INVALID") from None


def prepared_xch_size(live_size, headroom_multiplier):
    """Use the worker's twelve-place half-even headroom conversion."""
    size = _decimal(live_size)
    multiplier = _decimal(headroom_multiplier, Decimal("1"))
    return (size * multiplier).quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)


def prepared_cat_sizes(*, live_sizes, price, headroom_multiplier, cat_decimals,
                       sell_counts, max_offers, spread_bps, min_edge_bps):
    """Derive CAT denominations from the same generated live sell ladder."""
    price = _decimal(price)
    if price <= 0:
        raise ValueError("FEE_PREP_PRICE_UNAVAILABLE")
    multiplier = _decimal(headroom_multiplier, Decimal("1"))
    _integer(cat_decimals, 0, 18)
    _integer(max_offers, 0, MAX_PLAN_OUTPUTS)
    if type(live_sizes) is not dict or type(sell_counts) is not dict:
        raise ValueError("Coin Prep sell ladder inputs are invalid")
    sizes = {tier: _decimal(size) for tier, size in live_sizes.items()}
    counts = {tier: _integer(count, 0, MAX_PLAN_OUTPUTS) for tier, count in sell_counts.items()}
    summary = summarize_sell_ladder_cat(
        mid_price=price, spread_fraction=_decimal(spread_bps) / Decimal("10000"),
        max_offers=max_offers, tier_counts=counts, tier_sizes_xch=sizes,
        min_edge_bps=_decimal(min_edge_bps),
    )
    result = {}
    for tier, size in sizes.items():
        if tier == "fees":
            result[tier] = Decimal("0")
            continue
        amount = summary.max_cat_per_tier.get(tier, Decimal("0"))
        if amount <= 0:
            amount = size / price
        result[tier] = round_cat_display_amount_up_to_mojo(amount * multiplier, cat_decimals)
    return result


def _configuration(configuration):
    if type(configuration) is not dict:
        raise ValueError("Coin Prep configuration snapshot is missing")
    decimals = _integer(configuration["CAT_DECIMALS"], 0, 18)
    mode = configuration["LIQUIDITY_MODE"]
    if mode not in ("two_sided", "buy_only", "sell_only"):
        raise ValueError("Coin Prep liquidity mode is invalid")
    floors = {}
    for asset, key, scale in (("xch", "XCH_RESERVE", 12), ("cat", "CAT_RESERVE", decimals)):
        floors[asset] = _integer(int((_decimal(configuration[key]) * Decimal(10**scale))
                                    .to_integral_value(rounding=ROUND_CEILING)))
    return decimals, mode, floors


def _spec(values):
    return ",".join(f"{tier}={_text(values[tier])}" for tier in PREP_TIERS if tier in values)


def _result(*, configuration, xch_counts, cat_counts, xch_sizes, cat_sizes,
            multiplier, headroom, target_seconds, campaign_revision=None, multiplier_applied=False):
    decimals, mode, floors = _configuration(configuration)
    targets = build_prep_targets(tier_order=PREP_TIERS, xch_counts=xch_counts, cat_counts=cat_counts,
                                 xch_sizes=xch_sizes, cat_sizes=cat_sizes, cat_decimals=decimals)
    return {
        "targets": targets,
        "economic_plan": {
            "target_seconds": _integer(target_seconds, 1, 86_400),
            "coin_multiplier": _text(multiplier), "headroom_pct": _text(headroom),
            "liquidity_mode": mode, "reserve_floors_mojos": floors,
            "campaign_revision": campaign_revision, "cancellation_policy": "protected_no_prep",
            "outputs": [asdict(target) for target in targets],
        },
        "worker_args": {
            "xch_target": sum(xch_counts.values()), "cat_target": sum(cat_counts.values()),
            "buy_tier_sizes": _spec(xch_sizes), "cat_tier_sizes": _spec(cat_sizes),
            "tier_counts_xch": _spec(xch_counts), "tier_counts_cat": _spec(cat_counts),
            "prep_headroom_pct": "0",
        },
        "multiplier_applied": multiplier_applied,
    }


def build_standard_prep_economics(*, configuration, fee_pool, live_price,
                                  coin_multiplier="1", target_seconds=300):
    """Freeze standard tier/uniform settings into exact economic outputs."""
    decimals, mode, _ = _configuration(configuration)
    multiplier = _decimal(coin_multiplier, Decimal("0.5"), Decimal("3"))
    headroom = _decimal(configuration["COIN_PREP_HEADROOM_PCT"], maximum=Decimal("100"))
    headroom_multiplier = Decimal("1") + headroom / Decimal("100")
    for key in ("TIER_ENABLED", "BUY_LADDER_REVERSED"):
        if type(configuration[key]) is not bool:
            raise ValueError("Coin Prep tier flags must be exact booleans")
    tiered = configuration["TIER_ENABLED"]
    xch_counts, cat_counts, buy_sizes, sell_sizes = {}, {}, {}, {}
    if tiered:
        reversed_buy = configuration["BUY_LADDER_REVERSED"]
        for tier in TIER_ORDER:
            for side, counts, sizes in (("BUY", xch_counts, buy_sizes), ("SELL", cat_counts, sell_sizes)):
                position = _REVERSED[tier] if side == "BUY" and reversed_buy else tier
                count = sum(_integer(configuration.get(f"{side}_{position.upper()}_TIER{suffix}_COUNT", 0),
                                     0, MAX_PLAN_OUTPUTS) for suffix in ("", "_SPARE"))
                modern = _decimal(configuration.get(f"{side}_{position.upper()}_SIZE_XCH", 0))
                legacy = _REVERSED[position] if side == "BUY" and reversed_buy else position
                size = modern if modern > 0 else _decimal(configuration.get(f"{legacy.upper()}_SIZE_XCH", 0))
                sizes[tier] = size
                if count:
                    counts[tier] = count
    else:
        count = int(sum(_integer(configuration[key], 0, MAX_PLAN_OUTPUTS) for key in
                        ("MAX_ACTIVE_BUY_OFFERS", "MAX_ACTIVE_SELL_OFFERS")) * multiplier)
        xch_counts = {"inner": count} if count else {}
        cat_counts = dict(xch_counts)
        buy_sizes = {"inner": _decimal(configuration["DEFAULT_TRADE_XCH"])}
        sell_sizes = dict(buy_sizes)
    if mode == "buy_only":
        cat_counts = {}
    elif mode == "sell_only":
        xch_counts = {}
    xch_sizes = {tier: prepared_xch_size(size, headroom_multiplier) for tier, size in buy_sizes.items()}
    cat_sizes = {}
    if cat_counts:
        try:
            price = _decimal(live_price)
            if price <= 0:
                raise ValueError("missing price")
        except ValueError:
            raise ValueError("FEE_PREP_PRICE_UNAVAILABLE") from None
        if tiered:
            cat_sizes = prepared_cat_sizes(
                live_sizes={tier: sell_sizes[tier] for tier in cat_counts}, price=price,
                headroom_multiplier=headroom_multiplier, cat_decimals=decimals,
                sell_counts=cat_counts, max_offers=sum(cat_counts.values()),
                spread_bps=configuration["SPREAD_BPS"], min_edge_bps=configuration["MIN_EDGE_BPS"],
            )
        else:
            cat_sizes = {"inner": round_cat_display_amount_up_to_mojo(
                (sell_sizes["inner"] / price) * headroom_multiplier, decimals)}
    if type(fee_pool) is not dict or type(fee_pool.get("enabled")) is not bool:
        raise ValueError("Coin Prep fee pool settings are invalid")
    fee_count = _integer(fee_pool["count"], 0, MAX_PLAN_OUTPUTS)
    fee_size = _decimal(fee_pool["coin_size_xch"])
    if fee_pool["enabled"]:
        if not fee_count or fee_size <= 0:
            raise ValueError("Coin Prep enabled fee pool is unfunded")
        xch_counts["fees"], xch_sizes["fees"] = fee_count, fee_size
    return _result(configuration=configuration, xch_counts=xch_counts, cat_counts=cat_counts,
                   xch_sizes=xch_sizes, cat_sizes=cat_sizes, multiplier=multiplier,
                   headroom=headroom, target_seconds=target_seconds, multiplier_applied=not tiered)


def _parse_spec(spec, *, counts=False):
    if type(spec) is not str or len(spec) > 2048:
        raise ValueError("Coin Prep exact specification is invalid")
    result = {}
    for pair in spec.split(",") if spec else ():
        parts = pair.split("=")
        if len(parts) != 2 or parts[0] not in PREP_TIERS or parts[0] in result:
            raise ValueError("Coin Prep exact tier is invalid or duplicated")
        value = parts[1]
        if counts:
            if re.fullmatch(r"0|[1-9][0-9]{0,4}", value) is None:
                raise ValueError("Coin Prep exact count is invalid")
            result[parts[0]] = _integer(int(value), 0, MAX_PLAN_OUTPUTS)
        else:
            result[parts[0]] = _decimal(value)
    return result


def build_exact_prep_economics(*, configuration, worker_args, campaign_revision, target_seconds=300):
    """Freeze authorized Bootstrap denominations without market inference."""
    _integer(campaign_revision, 0)
    keys = {"xch_target", "cat_target", "buy_tier_sizes", "cat_tier_sizes",
            "tier_counts_xch", "tier_counts_cat", "prep_headroom_pct"}
    if type(worker_args) is not dict or set(worker_args) != keys or _decimal(worker_args["prep_headroom_pct"]) != 0:
        raise ValueError("Coin Prep exact overrides are incomplete or resize outputs")
    xch_counts = _parse_spec(worker_args["tier_counts_xch"], counts=True)
    cat_counts = _parse_spec(worker_args["tier_counts_cat"], counts=True)
    for asset, counts in (("xch", xch_counts), ("cat", cat_counts)):
        if _integer(worker_args[f"{asset}_target"], 0, MAX_PLAN_OUTPUTS) != sum(counts.values()):
            raise ValueError("Coin Prep exact targets and counts differ")
    return _result(configuration=configuration, xch_counts=xch_counts, cat_counts=cat_counts,
                   xch_sizes=_parse_spec(worker_args["buy_tier_sizes"]),
                   cat_sizes=_parse_spec(worker_args["cat_tier_sizes"]),
                   multiplier=Decimal("1"), headroom=Decimal("0"), target_seconds=target_seconds,
                   campaign_revision=campaign_revision)
