"""Pure, fail-closed planning for staged offer refreshes.

This module deliberately has no database, wallet, or network dependency.  It
only turns authoritative capacity supplied by the caller into a deterministic
stage/pause decision; Task 12 owns how that capacity is calculated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class RefreshPlan:
    """A pure refresh decision; execution still needs mutation authority."""

    mode: str
    reason: str | None
    stage_parent_ids: tuple[str, ...]
    cancel_parent_ids: tuple[str, ...]
    create_child_first: bool
    requires_mutation_authority: bool


def _exact_nonnegative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _target_identity(target: Mapping[str, Any]) -> tuple[int, str, int, str]:
    if not isinstance(target, Mapping):
        raise TypeError("refresh target must be a mapping")
    intent_id = target.get("intent_id")
    slot_key = target.get("slot_key")
    severity = target.get("severity", 0)
    generation = target.get("generation", 0)
    if type(intent_id) is not str or not intent_id:
        raise ValueError("refresh target intent_id is required")
    if type(slot_key) is not str or not slot_key:
        raise ValueError("refresh target slot_key is required")
    _exact_nonnegative_int(severity, "refresh target severity")
    _exact_nonnegative_int(generation, "refresh target generation")
    # Higher severity is riskier; the remaining keys make recovery stable.
    return (-severity, slot_key, generation, intent_id)


def plan_refresh(
    targets: Iterable[Mapping[str, Any]],
    *,
    overlap_capacity: int,
    batch_size: int,
    operator_mass_cancel: bool = False,
) -> RefreshPlan:
    """Plan a bounded create-child-first batch from authoritative capacity.

    ``operator_mass_cancel`` is intentionally an exact bool escape hatch. It
    only expresses a cancel-first *plan*: it never constitutes wallet or
    registry mutation authority.
    """

    if type(operator_mass_cancel) is not bool:
        raise TypeError("operator_mass_cancel must be an exact bool")
    capacity = _exact_nonnegative_int(overlap_capacity, "overlap_capacity")
    limit = _exact_nonnegative_int(batch_size, "batch_size")
    ordered = sorted(tuple(targets), key=_target_identity)
    intent_ids = tuple(target["intent_id"] for target in ordered)
    if len(intent_ids) != len(set(intent_ids)):
        raise ValueError("refresh target intent_ids must be unique")
    if not intent_ids:
        return RefreshPlan("noop", "no_refresh_targets", (), (), True, True)
    if operator_mass_cancel:
        return RefreshPlan(
            "operator_cancel_first",
            "explicit_operator_request",
            (),
            intent_ids,
            False,
            True,
        )
    staged = min(len(intent_ids), capacity, limit)
    if staged == 0:
        return RefreshPlan("pause", "overlap_capacity_exhausted", (), (), True, True)
    return RefreshPlan("stage", None, intent_ids[:staged], (), True, True)


__all__ = ["RefreshPlan", "plan_refresh"]
