"""Production runtime coordination for bounded Market Bootstrap campaigns."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapDecision,
    BootstrapEvidence,
    CampaignSide,
    evaluate_bootstrap_campaign,
)
import mutation_gate
from offer_book_policy import derive_bootstrap_plan


_IDENTITY_FIELDS = (
    "network",
    "wallet_type",
    "wallet_fingerprint",
    "wallet_id",
    "asset_id",
)
_NONTERMINAL_INTENT_STATES = frozenset(
    {
        "prepared",
        "submitted_unconfirmed",
        "creation_unknown",
        "created",
        "visible",
        "unknown",
        "conflicted",
    }
)
_LEVELS = frozenset({"near", "middle", "far"})
_SIDES = frozenset({"buy", "sell"})


def _utc(value: Any, label: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError(f"Bootstrap {label} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"Bootstrap {label} is invalid") from exc
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise ValueError(f"Bootstrap {label} is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"Bootstrap {label} is invalid")
    return parsed


def campaign_from_record(record: dict[str, Any]) -> BootstrapCampaign:
    """Reconstruct immutable financial authority from one durable row."""

    if type(record) is not dict or record.get("status") != "active":
        raise ValueError("active Bootstrap campaign record is required")
    return BootstrapCampaign(
        network=record.get("network"),
        wallet_type=record.get("wallet_type"),
        wallet_fingerprint=record.get("wallet_fingerprint"),
        wallet_id=record.get("wallet_id"),
        asset_id=record.get("asset_id"),
        anchor_price=_decimal(record.get("anchor_price"), "anchor price"),
        minimum_price=_decimal(record.get("minimum_price"), "minimum price"),
        maximum_price=_decimal(record.get("maximum_price"), "maximum price"),
        xch_budget=_decimal(record.get("xch_budget"), "XCH budget"),
        cat_budget=_decimal(record.get("cat_budget"), "CAT budget"),
        fee_budget_xch=_decimal(record.get("fee_budget_xch"), "fee budget"),
        subsidy_budget_xch=_decimal(record.get("subsidy_budget_xch"), "subsidy budget"),
        created_at=_utc(record.get("created_at"), "created time"),
        expires_at=_utc(record.get("expires_at"), "expiry"),
    )


def evidence_from_record(record: dict[str, Any]) -> BootstrapEvidence:
    """Recover the last durable evidence without inventing observations."""

    sides = record.get("independent_depth_sides") or []
    adverse = record.get("adverse_fill_times") or []
    try:
        return BootstrapEvidence(
            confirmed_fills=int(record.get("confirmed_fills", 0)),
            settlement_clusters=int(record.get("settlement_clusters", 0)),
            independent_depth_sides=frozenset(CampaignSide(side) for side in sides),
            stable_since=(
                None
                if record.get("stable_since") is None
                else _utc(record["stable_since"], "stable time")
            ),
            suspected_linked_activity=bool(
                record.get("suspected_linked_activity", False)
            ),
            adverse_fill_times=tuple(
                (CampaignSide(item["side"]), _utc(item["occurred_at"], "fill time"))
                for item in adverse
            ),
            fee_spent_xch=_decimal(record.get("fee_spent_xch", "0"), "fee spent"),
            realized_loss_xch=_decimal(
                record.get("realized_loss_xch", "0"), "realized loss"
            ),
            marked_inventory_loss_xch=_decimal(
                record.get("marked_inventory_loss_xch", "0"), "inventory loss"
            ),
            current_anchor_price=_decimal(
                record.get("current_anchor_price"), "current anchor"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Bootstrap evidence record is invalid") from exc


def plan_bootstrap_runtime_transition(
    *,
    campaign_record: dict,
    decision: BootstrapDecision,
    unresolved_cancellation_count: int,
) -> dict[str, Any]:
    """Plan the next live Bootstrap action without a wallet effect."""

    if type(campaign_record) is not dict or type(decision) is not BootstrapDecision:
        raise TypeError("exact Bootstrap campaign and decision are required")
    if (
        type(unresolved_cancellation_count) is not int
        or unresolved_cancellation_count < 0
    ):
        raise ValueError("unresolved cancellation count is invalid")
    if campaign_record.get("status") != "active":
        return {
            "allow_create": False,
            "allow_requote": False,
            "cancel_required": unresolved_cancellation_count > 0,
            "cancel_reason": "bootstrap_campaign_not_active",
            "manual_restart_required": True,
        }
    if unresolved_cancellation_count:
        return {
            "allow_create": False,
            "allow_requote": False,
            "cancel_required": True,
            "cancel_reason": "bootstrap_cancellation_recovery",
            "manual_restart_required": bool(decision.manual_restart_required),
        }
    if decision.cancellation_required or not decision.authorized:
        stop_reason = decision.stop_reason.value if decision.stop_reason else "unsafe"
        return {
            "allow_create": False,
            "allow_requote": False,
            "cancel_required": True,
            "cancel_reason": f"bootstrap_{stop_reason}",
            "manual_restart_required": bool(decision.manual_restart_required),
        }
    return {
        "allow_create": True,
        "allow_requote": True,
        "cancel_required": False,
        "cancel_reason": None,
        "manual_restart_required": False,
    }


def derive_bootstrap_runtime(
    *,
    campaign_record: dict[str, Any],
    identity: dict[str, Any],
    balances: dict[str, Any],
    now: datetime,
    unresolved_cancellation_count: int = 0,
) -> dict[str, Any]:
    """Derive one exact, identity-bound live campaign decision and plan."""

    if type(identity) is not dict:
        raise ValueError("Bootstrap identity is invalid")
    expected = {field: campaign_record.get(field) for field in _IDENTITY_FIELDS}
    observed = {field: identity.get(field) for field in _IDENTITY_FIELDS}
    if observed != expected:
        raise ValueError("Bootstrap identity does not match campaign authority")
    if type(now) is not datetime or now.tzinfo is None:
        raise ValueError("Bootstrap runtime time is invalid")
    now = now.astimezone(timezone.utc)
    campaign = campaign_from_record(campaign_record)
    evidence = evidence_from_record(campaign_record)
    decision = evaluate_bootstrap_campaign(campaign, evidence, now=now)
    transition = plan_bootstrap_runtime_transition(
        campaign_record=campaign_record,
        decision=decision,
        unresolved_cancellation_count=unresolved_cancellation_count,
    )
    authority = mutation_gate.authorize_market_mutation(
        operation="create",
        follow_authorized=False,
        identity=observed,
        asset_id=campaign.asset_id,
        bootstrap_campaign=campaign_record,
        bootstrap_decision=decision,
        expected_campaign_id=campaign_record.get("campaign_id"),
        expected_revision=campaign_record.get("revision"),
        now=now,
    )
    plan = derive_bootstrap_plan(campaign, decision, balances)
    if authority.get("allowed") is not True or transition["allow_create"] is not True:
        plan = {**plan, "authorized": False}
    return {
        "campaign": campaign,
        "evidence": evidence,
        "decision": decision,
        "transition": transition,
        "authority": authority,
        "plan": plan,
    }


def active_bootstrap_levels(
    intents: list[dict[str, Any]],
    *,
    campaign_id: str,
    revision: int,
) -> frozenset[tuple[str, str]]:
    """Return exact nonterminal campaign slots already owned by Sage."""

    if type(intents) is not list:
        raise TypeError("Bootstrap intents must be a list")
    prefix = f"bootstrap:{campaign_id}:{revision}:"
    purpose = f"bootstrap:{campaign_id}:revision:{revision}"
    active: set[tuple[str, str]] = set()
    for intent in intents:
        if type(intent) is not dict:
            continue
        if intent.get("purpose") != purpose:
            continue
        if str(intent.get("lifecycle_state") or "").lower() not in (
            _NONTERMINAL_INTENT_STATES
        ):
            continue
        slot_key = str(intent.get("slot_key") or "")
        if not slot_key.startswith(prefix):
            continue
        remainder = slot_key[len(prefix) :].split(":")
        if len(remainder) != 2:
            continue
        side, level = remainder
        if side in _SIDES and level in _LEVELS:
            active.add((side, level))
    return frozenset(active)
