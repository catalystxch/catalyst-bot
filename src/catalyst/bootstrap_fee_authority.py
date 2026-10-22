"""Current ordinary fee consent required for Bootstrap offer creation."""

from decimal import Decimal
from typing import Any

from super_log import slog


def cancellation_fee_readiness(campaign: dict[str, Any]) -> dict[str, Any]:
    """Verify current campaign consent and its remaining cancellation reserve."""
    try:
        from database import get_latest_coin_prep_fee_approval_for_campaign

        approval_id = get_latest_coin_prep_fee_approval_for_campaign(
            campaign["campaign_id"]
        )
    except Exception:
        return {"ready": False, "reason": "bootstrap_cancellation_fee_approval_stale"}
    if approval_id is None:
        return {
            "ready": False,
            "reason": "bootstrap_cancellation_fee_approval_required",
        }
    try:
        from coin_prep_fee_runtime import read_approved_prep_fee_snapshot

        context = read_approved_prep_fee_snapshot(
            approval_id, allow_policy_only_revision=True
        )
        approval = context["approval"]
        bound_campaign = context["campaign"]
        campaign_cap = Decimal(str(campaign["fee_budget_xch"])) * Decimal(10**12)
        if (
            type(bound_campaign) is not dict
            or bound_campaign.get("campaign_id") != campaign["campaign_id"]
            or type(campaign.get("revision")) is not int
            or bound_campaign.get("revision") != campaign["revision"]
            or context.get("recovery_only") is not False
            or not campaign_cap.is_finite()
            or campaign_cap <= 0
        ):
            raise ValueError("FEE_APPROVAL_STALE")
        total = approval["total_fee_mojos"]
        reserve = approval["cancellation_reserve_mojos"]
        remaining = approval["remaining_fee_mojos"]
        if (
            any(type(amount) is not int for amount in (total, reserve, remaining))
            or total <= 0
            or total > campaign_cap
            or reserve <= 0
            or remaining < reserve
        ):
            return {
                "ready": False,
                "reason": "bootstrap_cancellation_fee_budget_insufficient",
            }
    except Exception as exc:
        slog(
            "SAFETY",
            "Bootstrap cancellation fee verification failed closed",
            {"error": str(exc)[:256]},
            level="warning",
        )
        return {"ready": False, "reason": "bootstrap_cancellation_fee_approval_stale"}
    return {"ready": True, "approval_id": approval_id}
