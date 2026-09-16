"""Pure exact reusable cohorts and fee capacity for a verified prep inventory."""

from dataclasses import replace
import re

from coin_prep_batch_plan import CoinSnapshot, SelectableCoin, TargetOutput
from coin_prep_targets import MAX_ATOMIC_AMOUNT, MAX_PLAN_OUTPUTS


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_ATOMIC_AMOUNT


def prepare_fee_inventory(snapshot, targets, reserve_floors):
    """Retain all target principal and the greater of physical/declared reserves.

    Reconciliation-protected inputs do not fund reserves or fees. Classifying
    exact denominations writes no designation and assigns each target once,
    using the same amount/purpose/tier/ordinal order as the execution worker.
    """
    if (type(snapshot) is not CoinSnapshot or type(snapshot.coins) is not tuple
            or type(targets) is not tuple or len(targets) > MAX_PLAN_OUTPUTS
            or type(reserve_floors) is not dict or set(reserve_floors) != {"xch", "cat"}
            or not all(_integer(v) for v in reserve_floors.values())):
        raise ValueError("FEE_INVENTORY_INVALID")
    ids = set()
    for coin in snapshot.coins:
        if (type(coin) is not SelectableCoin or coin.asset not in ("xch", "cat")
                or type(coin.coin_id) is not str or re.fullmatch(r"[0-9a-f]{64}", coin.coin_id) is None
                or coin.coin_id in ids or not _integer(coin.amount_mojos, 1)
                or type(coin.selectable) is not bool or type(coin.protected) is not bool):
            raise ValueError("FEE_INVENTORY_INVALID")
        ids.add(coin.coin_id)
    cohorts, identities = {}, set()
    principal = {"xch": 0, "cat": 0}
    for target in targets:
        if (type(target) is not TargetOutput or target.asset not in principal
                or target.purpose not in ("replacement", "fee_reserve")
                or not _integer(target.amount_mojos, 1) or not _integer(target.ordinal)
                or not _integer(target.tier_rank) or (target.asset, target.ordinal) in identities):
            raise ValueError("FEE_TARGETS_INVALID")
        identities.add((target.asset, target.ordinal))
        principal[target.asset] += target.amount_mojos
        cohorts.setdefault((target.asset, target.amount_mojos), []).append(target)
    for cohort in cohorts.values():
        cohort.sort(key=lambda target: (target.purpose, target.tier_rank, target.ordinal))
    total, physical_reserve = {"xch": 0, "cat": 0}, {"xch": 0, "cat": 0}
    classified, reused = [], 0
    for coin in sorted(snapshot.coins, key=lambda coin: (coin.asset, coin.coin_id)):
        if coin.selectable and (not coin.protected or coin.purpose == "reserve"):
            total[coin.asset] += coin.amount_mojos
        if coin.selectable and coin.protected and coin.purpose == "reserve":
            physical_reserve[coin.asset] += coin.amount_mojos
        cohort = cohorts.get((coin.asset, coin.amount_mojos), [])
        if coin.selectable and not coin.protected and cohort:
            coin = replace(coin, purpose=cohort.pop(0).purpose)
            reused += 1
        elif not coin.protected:
            # Only exact requested target roles can grant reuse in this plan.
            coin = replace(coin, purpose="")
        classified.append(coin)
    if not all(_integer(value) for values in (principal, total, physical_reserve) for value in values.values()):
        raise ValueError("FEE_INVENTORY_INVALID")
    retained = {asset: max(reserve_floors[asset], physical_reserve[asset]) for asset in total}
    return {"snapshot": CoinSnapshot(tuple(classified)), "retained_principal_mojos": principal,
            "fee_funding_mojos": max(0, total["xch"] - retained["xch"] - principal["xch"]),
            "principal_funded": all(total[asset] >= retained[asset] + principal[asset] for asset in total),
            "reused_target_count": reused}
