"""Pure policy helpers for post-TibetSwap coin preparation."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping


def exclude_retired_sniper_pools(
    xch_tier_counts: Mapping[str, int],
    cat_tier_counts: Mapping[str, int],
    tier_sizes: Mapping[str, Decimal],
) -> tuple[dict[str, int], dict[str, int], dict[str, Decimal]]:
    """Return prep plans with every retired sniper cohort removed.

    Releases before v1.4 could leave ``SNIPER_ENABLED`` and its pool sizes in
    an upgraded user's configuration.  Sniping depended on TibetSwap and is
    retired, so those legacy values must not shape the wallet or add needless
    Coin Prep transactions.
    """

    return (
        {key: value for key, value in xch_tier_counts.items() if key != "sniper"},
        {key: value for key, value in cat_tier_counts.items() if key != "sniper"},
        {key: value for key, value in tier_sizes.items() if key != "sniper"},
    )
