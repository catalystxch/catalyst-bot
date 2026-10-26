"""Exact read-only principal bound for a reviewed two-sided Follow run."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING

from coin_prep_batch_plan import CoinSnapshot


def _floor_atoms(value: Decimal, decimals: int) -> int:
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise ValueError("FOLLOW_PRINCIPAL_RESERVE_INVALID")
    return int((value * (10**decimals)).to_integral_value(rounding=ROUND_CEILING))


def calculate_follow_principal(
    snapshot: CoinSnapshot,
    *,
    xch_reserve: Decimal,
    cat_reserve: Decimal,
    cat_decimals: int,
    fee_cap_mojos: int,
    fee_pool_principal_mojos: int,
    fee_reserve_coin_ids: set[str],
) -> dict:
    """Bound both trading balances without spending protected fee principal.

    The caller supplies a complete, identity-verified selectable Sage snapshot.
    This function is pure: it cannot grant run authority, change settings or
    submit a wallet effect. Any missing or contradictory coin data fails closed.
    """

    if (
        type(snapshot) is not CoinSnapshot
        or type(cat_decimals) is not int
        or not 0 <= cat_decimals <= 18
        or type(fee_cap_mojos) is not int
        or fee_cap_mojos <= 0
        or type(fee_pool_principal_mojos) is not int
        or fee_pool_principal_mojos < 0
        or type(fee_reserve_coin_ids) is not set
    ):
        raise ValueError("FOLLOW_PRINCIPAL_INPUT_INVALID")
    xch_floor = _floor_atoms(xch_reserve, 12)
    cat_floor = _floor_atoms(cat_reserve, cat_decimals)
    fee_floor = max(fee_cap_mojos, fee_pool_principal_mojos)
    if any(
        type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in fee_reserve_coin_ids
    ):
        raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")

    totals = {"xch": 0, "cat": 0}
    protected = {"xch": 0, "cat": 0}
    user_reserve = {"xch": 0, "cat": 0}
    unprotected_count = {"xch": 0, "cat": 0}
    fee_coins = 0
    seen = set()
    canonical = []
    for coin in snapshot.coins:
        coin_id = getattr(coin, "coin_id", None)
        asset = getattr(coin, "asset", None)
        amount = getattr(coin, "amount_mojos", None)
        purpose = getattr(coin, "purpose", None)
        selectable = getattr(coin, "selectable", None)
        is_protected = getattr(coin, "protected", None)
        if (
            type(coin_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", coin_id) is None
            or coin_id in seen
            or asset not in totals
            or type(amount) is not int
            or amount <= 0
            or type(purpose) is not str
            or type(selectable) is not bool
            or selectable is not True
            or type(is_protected) is not bool
            or (purpose == "fee_reserve") != (coin_id in fee_reserve_coin_ids)
            or (coin_id in fee_reserve_coin_ids and asset != "xch")
        ):
            raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")
        seen.add(coin_id)
        totals[asset] += amount
        if is_protected or coin_id in fee_reserve_coin_ids:
            protected[asset] += amount
        else:
            unprotected_count[asset] += 1
        if purpose == "reserve":
            if not is_protected:
                raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")
            user_reserve[asset] += amount
        if coin_id in fee_reserve_coin_ids:
            fee_coins += amount
        canonical.append((asset, coin_id, amount, purpose, is_protected))
    if not fee_reserve_coin_ids.issubset(seen):
        raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")

    extra_xch_reserve = max(0, xch_floor - user_reserve["xch"])
    extra_cat_reserve = max(0, cat_floor - user_reserve["cat"])
    extra_fee = max(0, fee_floor - fee_coins)
    trade_xch = totals["xch"] - protected["xch"] - extra_xch_reserve - extra_fee
    trade_cat = totals["cat"] - protected["cat"] - extra_cat_reserve
    if trade_xch <= 0:
        raise ValueError("FOLLOW_FEE_PRINCIPAL_UNAVAILABLE")
    if trade_cat <= 0:
        raise ValueError("FOLLOW_TRADING_PRINCIPAL_UNAVAILABLE")
    digest = hashlib.sha256(
        json.dumps(sorted(canonical), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "maximum_trade_xch_mojos": trade_xch,
        "maximum_trade_cat_atoms": trade_cat,
        "protected_fee_principal_mojos": fee_floor,
        "protected_xch_reserve_mojos": xch_floor,
        "protected_cat_reserve_atoms": cat_floor,
        "selectable_xch_mojos": totals["xch"],
        "selectable_cat_atoms": totals["cat"],
        "unprotected_xch_coin_count": unprotected_count["xch"],
        "unprotected_cat_coin_count": unprotected_count["cat"],
        "inventory_sha256": digest,
        "dispatch_authorized": False,
    }


def read_follow_principal_snapshot(*, fee_cap_mojos: int) -> dict:
    """Read the verified Sage inventory and durable fee-coin designation.

    The result is a principal proposal for native review, never wallet-effect
    authority. A later review must re-read it before consuming consent.
    """

    from coin_prep_fee_runtime import read_fee_wallet_snapshot
    from tx_fees import get_fee_pool_plan
    import database

    observed = read_fee_wallet_snapshot()
    config = observed["configuration"]
    snapshot = observed["snapshot"]
    plan = get_fee_pool_plan()
    if type(plan) is not dict or type(plan.get("enabled")) is not bool:
        raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
    fee_pool_principal = 0
    if plan["enabled"]:
        count = plan.get("count")
        size = plan.get("coin_size_mojos")
        if type(count) is not int or count < 1 or type(size) is not int or size < 1:
            raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
        fee_pool_principal = count * size
    fee_rows = database.get_free_coins("xch")
    if type(fee_rows) is not list:
        raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
    fee_ids = {
        row["coin_id"]
        for row in fee_rows
        if type(row) is dict and row.get("purpose") == "fee_reserve"
    }
    if any(type(coin_id) is not str for coin_id in fee_ids):
        raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
    if any(
        coin.coin_id in fee_ids and coin.purpose not in {"", "fee_reserve"}
        for coin in snapshot.coins
    ):
        raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")
    enriched = CoinSnapshot(
        tuple(
            replace(coin, purpose="fee_reserve") if coin.coin_id in fee_ids else coin
            for coin in snapshot.coins
        )
    )
    selected_fee_ids = fee_ids.intersection(coin.coin_id for coin in enriched.coins)
    result = calculate_follow_principal(
        enriched,
        xch_reserve=config["XCH_RESERVE"],
        cat_reserve=config["CAT_RESERVE"],
        cat_decimals=config["CAT_DECIMALS"],
        fee_cap_mojos=fee_cap_mojos,
        fee_pool_principal_mojos=fee_pool_principal,
        fee_reserve_coin_ids=selected_fee_ids,
    )
    identity = observed["identity"]
    proposal_sha256 = hashlib.sha256(
        json.dumps(
            {"identity": identity, "principal": result},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {**result, "identity": identity, "principal_review_sha256": proposal_sha256}
