"""Pure deterministic planner for bounded final-output Sage Coin Prep batches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SelectableCoin:
    asset: str
    coin_id: str
    amount_mojos: int
    purpose: str = ""
    selectable: bool = True
    protected: bool = False


@dataclass(frozen=True)
class CoinSnapshot:
    coins: tuple[SelectableCoin, ...]


@dataclass(frozen=True)
class TargetOutput:
    asset: str
    purpose: str
    tier_rank: int
    amount_mojos: int
    ordinal: int


@dataclass(frozen=True)
class BatchConstraints:
    reserve_floors: Mapping[str, int]
    fee_mojos: int
    max_asset_inputs: int = 50
    max_outputs: int = 128


@dataclass(frozen=True)
class PlannedOutput:
    asset: str
    purpose: str
    amount_mojos: int
    ordinal: int


@dataclass(frozen=True)
class BatchPlan:
    asset: str
    source_coin_ids: tuple[str, ...]
    fee_source_id: str | None
    outputs: tuple[PlannedOutput, ...]
    reused_coin_ids: tuple[str, ...]
    reused_target_ids: tuple[tuple[str, int], ...]
    fee_mojos: int
    transaction_required: bool = True

    @classmethod
    def no_transaction(cls, reused: list[tuple[TargetOutput, SelectableCoin]]):
        return cls(
            asset="",
            source_coin_ids=(),
            fee_source_id=None,
            outputs=(),
            reused_coin_ids=tuple(sorted(coin.coin_id for _, coin in reused)),
            reused_target_ids=tuple(
                sorted((target.asset, target.ordinal) for target, _ in reused)
            ),
            fee_mojos=0,
            transaction_required=False,
        )


@dataclass(frozen=True)
class BatchRefusal:
    code: str
    message: str
    prerequisite_allowed: bool = False


def _normal_asset(value: str) -> str:
    return str(value or "").strip().lower()


def _target_key(target: TargetOutput):
    return (
        target.asset,
        target.purpose,
        target.tier_rank,
        target.amount_mojos,
        target.ordinal,
    )


def _refuse(code: str, message: str, *, prerequisite=False) -> BatchRefusal:
    return BatchRefusal(code, message, prerequisite)


def plan_batch(
    snapshot: CoinSnapshot,
    targets: tuple[TargetOutput, ...],
    constraints: BatchConstraints,
) -> BatchPlan | BatchRefusal:
    """Plan the next CAT-first batch from a complete selectable snapshot.

    The caller submits at most one plan, authoritatively refreshes the snapshot,
    and invokes this function again. This keeps unconfirmed change out of later
    plans and makes crash recovery an operation-level concern rather than a
    planner side effect.
    """
    if type(snapshot) is not CoinSnapshot or type(snapshot.coins) is not tuple:
        return _refuse("INVALID_SNAPSHOT", "Coin snapshot is malformed")
    if (
        type(constraints.fee_mojos) is not int
        or constraints.fee_mojos < 0
        or type(constraints.max_asset_inputs) is not int
        or constraints.max_asset_inputs < 1
        or type(constraints.max_outputs) is not int
        or constraints.max_outputs < 1
    ):
        return _refuse("INVALID_CONSTRAINTS", "Batch constraints are malformed")

    coins: list[SelectableCoin] = []
    coin_ids: set[str] = set()
    for item in snapshot.coins:
        if (
            type(item) is not SelectableCoin
            or not item.coin_id
            or item.coin_id in coin_ids
            or _normal_asset(item.asset) not in {"xch", "cat"}
            or type(item.amount_mojos) is not int
            or item.amount_mojos <= 0
        ):
            return _refuse(
                "INVALID_SNAPSHOT", "Coin snapshot has an invalid or duplicate coin"
            )
        coin_ids.add(item.coin_id)
        coins.append(
            SelectableCoin(
                _normal_asset(item.asset),
                item.coin_id,
                item.amount_mojos,
                item.purpose,
                item.selectable,
                item.protected,
            )
        )

    ordered_targets: list[TargetOutput] = []
    target_ids: set[tuple[str, int]] = set()
    for item in targets:
        asset = _normal_asset(getattr(item, "asset", ""))
        identity = (asset, getattr(item, "ordinal", -1))
        if (
            type(item) is not TargetOutput
            or asset not in {"xch", "cat"}
            or not item.purpose
            or type(item.amount_mojos) is not int
            or item.amount_mojos <= 0
            or type(item.ordinal) is not int
            or item.ordinal < 0
            or identity in target_ids
        ):
            return _refuse(
                "INVALID_TARGETS", "Target outputs are malformed or repeated"
            )
        target_ids.add(identity)
        ordered_targets.append(
            TargetOutput(
                asset, item.purpose, item.tier_rank, item.amount_mojos, item.ordinal
            )
        )
    ordered_targets.sort(key=_target_key)

    available_for_reuse: dict[tuple[str, str, int], list[SelectableCoin]] = {}
    for item in coins:
        if item.selectable and not item.protected and item.purpose:
            available_for_reuse.setdefault(
                (item.asset, item.purpose, item.amount_mojos), []
            ).append(item)
    for cohort in available_for_reuse.values():
        cohort.sort(key=lambda item: item.coin_id)

    reused: list[tuple[TargetOutput, SelectableCoin]] = []
    missing: list[TargetOutput] = []
    reused_ids: set[str] = set()
    for item in ordered_targets:
        cohort = available_for_reuse.get(
            (item.asset, item.purpose, item.amount_mojos), []
        )
        selected = next(
            (coin for coin in cohort if coin.coin_id not in reused_ids), None
        )
        if selected is None:
            missing.append(item)
        else:
            reused.append((item, selected))
            reused_ids.add(selected.coin_id)
    if not missing:
        return BatchPlan.no_transaction(reused)

    # CAT first keeps its separately confirmed XCH fee change available when
    # the following XCH batch is replanned.
    batch_asset = "cat" if any(item.asset == "cat" for item in missing) else "xch"
    batch_targets = [item for item in missing if item.asset == batch_asset]
    required = sum(item.amount_mojos for item in batch_targets)
    if batch_asset == "xch":
        required += constraints.fee_mojos

    total_by_asset = {
        asset: sum(
            c.amount_mojos
            for c in coins
            if c.asset == asset and c.selectable and not c.protected
        )
        for asset in ("xch", "cat")
    }
    fee_loss = constraints.fee_mojos
    xch_floor = int(constraints.reserve_floors.get("xch", 0) or 0)
    cat_floor = int(constraints.reserve_floors.get("cat", 0) or 0)
    if min(xch_floor, cat_floor) < 0:
        return _refuse("INVALID_CONSTRAINTS", "Reserve floors cannot be negative")
    if total_by_asset["xch"] - fee_loss < xch_floor:
        return _refuse(
            "RESERVE_FLOOR", "Planned fee would breach the XCH reserve floor"
        )
    if total_by_asset["cat"] < cat_floor:
        return _refuse("RESERVE_FLOOR", "CAT snapshot is below its reserve floor")

    candidates = sorted(
        (
            item
            for item in coins
            if item.asset == batch_asset
            and item.selectable
            and not item.protected
            and item.coin_id not in reused_ids
        ),
        key=lambda item: (-item.amount_mojos, item.coin_id),
    )
    selected: list[SelectableCoin] = []
    selected_total = 0
    for item in candidates:
        if selected_total >= required:
            break
        selected.append(item)
        selected_total += item.amount_mojos
    if selected_total < required:
        return _refuse(
            "INSUFFICIENT_SOURCES",
            f"No selectable {batch_asset.upper()} source cohort can fund the batch",
        )
    if len(selected) > constraints.max_asset_inputs:
        return _refuse(
            "INPUT_CAP_REQUIRES_PREREQUISITE",
            "The next target needs a bounded consolidation prerequisite",
            prerequisite=True,
        )

    fee_source = None
    fee_change = 0
    if batch_asset == "cat" and constraints.fee_mojos:
        fee_candidates = sorted(
            (
                item
                for item in coins
                if item.asset == "xch"
                and item.selectable
                and not item.protected
                and item.coin_id not in reused_ids
                and item.amount_mojos >= constraints.fee_mojos
            ),
            key=lambda item: (item.amount_mojos, item.coin_id),
        )
        if not fee_candidates:
            return _refuse(
                "FEE_SOURCE_REQUIRED",
                "CAT prep has no separate selectable XCH fee input",
                prerequisite=True,
            )
        fee_source = fee_candidates[0]
        fee_change = fee_source.amount_mojos - constraints.fee_mojos

    outputs = [
        PlannedOutput(item.asset, item.purpose, item.amount_mojos, item.ordinal)
        for item in batch_targets
    ]
    asset_change = selected_total - required
    if asset_change:
        outputs.append(PlannedOutput(batch_asset, "change", asset_change, -1))
    if fee_change:
        outputs.append(PlannedOutput("xch", "fee_change", fee_change, -1))
    outputs.sort(
        key=lambda item: (item.asset, item.purpose, item.amount_mojos, item.ordinal)
    )
    if len(outputs) > constraints.max_outputs:
        return _refuse(
            "OUTPUT_CAP_EXCEEDED", "Final outputs exceed the configured batch cap"
        )

    return BatchPlan(
        asset=batch_asset,
        source_coin_ids=tuple(sorted(item.coin_id for item in selected)),
        fee_source_id=fee_source.coin_id if fee_source else None,
        outputs=tuple(outputs),
        reused_coin_ids=tuple(sorted(reused_ids)),
        reused_target_ids=tuple(
            sorted((item.asset, item.ordinal) for item, _ in reused)
        ),
        fee_mojos=constraints.fee_mojos,
    )
