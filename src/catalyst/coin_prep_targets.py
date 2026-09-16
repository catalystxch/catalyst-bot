"""Pure atomic output construction shared by Coin Prep preview and execution."""

from decimal import Decimal, DecimalException, ROUND_CEILING, ROUND_DOWN, localcontext

from coin_prep_batch_plan import TargetOutput


MAX_ATOMIC_AMOUNT = 2**63 - 1
MAX_PLAN_OUTPUTS = 10_000


def build_prep_targets(
    *, tier_order, xch_counts: dict, cat_counts: dict,
    xch_sizes: dict, cat_sizes: dict, cat_decimals: int,
) -> tuple[TargetOutput, ...]:
    """Convert already prepared display sizes to exact deterministic outputs.

    Headroom/ladder generation happens before this boundary. Counts must be
    exact integers, XCH retains the worker's downward atomic conversion, and
    CAT rounds upward so a displayed amount never underfunds an offer. Fee
    denominations are XCH-only. This function performs no wallet/DB activity.
    """
    if type(tier_order) not in (tuple, list) or any(
        type(tier) is not str or not tier for tier in tier_order
    ) or len(set(tier_order)) != len(tier_order):
        raise ValueError("Coin Prep tier order is invalid or duplicated")
    if type(cat_decimals) is not int or not 0 <= cat_decimals <= 18:
        raise ValueError("Coin Prep CAT scale is invalid")
    total = 0
    for counts, sizes in ((xch_counts, xch_sizes), (cat_counts, cat_sizes)):
        if type(counts) is not dict or type(sizes) is not dict or set(counts) - set(tier_order):
            raise ValueError("Coin Prep tier counts/sizes are not represented")
        for count in counts.values():
            if type(count) is not int or count < 0:
                raise ValueError("Coin Prep count must be an exact nonnegative integer")
            total += count
    if total > MAX_PLAN_OUTPUTS:
        raise ValueError("Coin Prep output plan is too large")
    if cat_counts.get("fees", 0):
        raise ValueError("Coin Prep fee funding must use XCH")
    targets = []
    for asset, counts, sizes, decimals in (
        ("xch", xch_counts, xch_sizes, 12), ("cat", cat_counts, cat_sizes, cat_decimals),
    ):
        ordinal = 0
        for rank, tier in enumerate(tier_order):
            count = counts.get(tier, 0)
            if count == 0:
                continue
            value = sizes.get(tier)
            if type(value) not in (str, int, Decimal):
                raise ValueError("Coin Prep prepared amount cannot be implicitly coerced")
            try:
                with localcontext() as context:
                    context.prec = 80
                    amount = Decimal(value)
                    if not amount.is_finite() or amount <= 0:
                        raise ValueError("Coin Prep prepared amount is invalid")
                    atoms = amount * Decimal(10**decimals)
                    rounded = atoms.to_integral_value(
                        rounding=ROUND_DOWN if asset == "xch" else ROUND_CEILING
                    )
                    if not 1 <= rounded <= MAX_ATOMIC_AMOUNT:
                        raise ValueError("Coin Prep atomic amount is outside supported bounds")
                    mojos = int(rounded)
            except DecimalException as exc:
                raise ValueError("Coin Prep prepared amount is invalid") from exc
            for _ in range(count):
                targets.append(TargetOutput(
                    asset, "fee_reserve" if tier == "fees" else "replacement",
                    rank, mojos, ordinal,
                ))
                ordinal += 1
    return tuple(targets)
