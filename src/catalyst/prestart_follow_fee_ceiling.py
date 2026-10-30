"""Fresh, read-only economics for changing a completed session's initial Follow cap.

The resulting preview is not spending consent or run authority. Confirmation is
deliberately separate and only exposed through the native desktop bridge.
"""

import hashlib
import json

import database
import coin_prep_fee_approval as fee_approval
from coin_prep_fee_approval import (
    _digest,
    _exact_int,
    _prove_approved_coin_prep_targets,
    _canonical_json,
)


def _review_from_preview(preview: dict) -> dict:
    quote = json.loads(preview["quote_json"])
    marker = quote.get("prestart_review")
    if type(marker) is not dict:
        raise ValueError("FEE_PRESTART_REVIEW_REQUIRED")
    return {
        "preview_id": preview["preview_id"],
        "prior_approval_id": marker["prior_approval_id"],
        "prior_maximum_fee_mojos": marker["prior_maximum_fee_mojos"],
        "proposed_maximum_fee_mojos": marker["proposed_maximum_fee_mojos"],
        "spent_fee_mojos": marker["spent_fee_mojos"],
        "held_fee_mojos": marker["held_fee_mojos"],
        "protected_cancellation_fee_mojos": marker["protected_cancellation_fee_mojos"],
        "fee_funding_mojos": quote["fee_funding_mojos"],
        "estimated_cancellation_fee_mojos": marker["protected_cancellation_fee_mojos"],
        "observed_at": preview["observed_at"],
        "expires_at": preview["expires_at"],
        "wallet": json.loads(preview["scope_json"]),
        "dispatch_authorized": False,
    }


def _review_digest(review: dict) -> str:
    encoded = json.dumps(review, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def preview_prestart_follow_fee_ceiling(
    approval_id: str, proposed_maximum_fee_mojos: int
) -> dict:
    """Quote the original completed plan without minting a new prep session."""
    _digest(approval_id)
    maximum = _exact_int(proposed_maximum_fee_mojos)
    from coin_prep_fee_runtime import read_approved_prep_fee_snapshot
    from coin_prep_fee_funding import prepare_fee_inventory

    approved = read_approved_prep_fee_snapshot(approval_id)
    scope = approved["scope"]
    if scope["campaign_id"] is not None or scope["session_id"] is None:
        raise ValueError("FEE_PRESTART_STANDALONE_REQUIRED")
    session = database.get_coin_prep_fee_session(scope["session_id"])
    if session["current_session_id"] != scope["session_id"]:
        raise ValueError("FEE_APPROVAL_STALE")
    try:
        completion = database.get_coin_prep_fee_session_completion(scope["session_id"])
    except ValueError as exc:
        raise ValueError("FEE_SESSION_INCOMPLETE") from exc
    if completion["approval_id"] != approval_id:
        raise ValueError("FEE_APPROVAL_STALE")
    prior = approved["approval"]
    if maximum <= prior["total_fee_mojos"]:
        raise ValueError("FEE_PRESTART_CEILING_MUST_INCREASE")
    first_targets = _prove_approved_coin_prep_targets(approved)
    after = read_approved_prep_fee_snapshot(approval_id)
    if (
        any(
            after[key] != approved[key]
            for key in (
                "identity",
                "configuration",
                "receive_address",
                "snapshot",
                "recipe",
                "scope",
                "approval",
            )
        )
        or _prove_approved_coin_prep_targets(after) != first_targets
    ):
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    if (
        sorted(first_targets.reused_coin_ids)
        != json.loads(completion["evidence_json"])["target_coin_ids"]
    ):
        raise ValueError("FEE_PRESTART_TARGETS_CHANGED")
    funding = prepare_fee_inventory(
        after["snapshot"],
        after["recipe"]["targets"],
        after["recipe"]["economic_plan"]["reserve_floors_mojos"],
    )
    budget = database.get_fee_scope_budget(prior["scope_sha256"])
    protected = budget["protected_cancellation_fee_mojos"]
    if maximum < max(
        budget["committed_fee_mojos"] + protected, prior["total_fee_mojos"]
    ) or (maximum - budget["committed_fee_mojos"] > funding["fee_funding_mojos"]):
        raise ValueError("FEE_PRESTART_FUNDING_INSUFFICIENT")
    consent = database.get_coin_prep_fee_approval_context(approval_id)
    observed_at = fee_approval._now()
    expires_at = observed_at + 60
    marker = {
        "prior_approval_id": approval_id,
        "prior_maximum_fee_mojos": prior["total_fee_mojos"],
        "proposed_maximum_fee_mojos": maximum,
        "spent_fee_mojos": budget["spent_fee_mojos"],
        "held_fee_mojos": budget["held_fee_mojos"],
        "protected_cancellation_fee_mojos": budget["protected_cancellation_fee_mojos"],
        "completion_evidence_sha256": completion["evidence_sha256"],
    }
    stored = database.store_coin_prep_fee_preview(
        scope_sha256=consent["scope_sha256"],
        plan_sha256=consent["plan_sha256"],
        scope_json=consent["scope_json"],
        plan_json=consent["plan_json"],
        request_options_json=consent["request_options_json"],
        quote_json=_canonical_json(
            {
                "available": True,
                "estimated_preparation_fee_mojos": 0,
                "estimated_cancellation_fee_mojos": protected,
                "fee_funding_mojos": funding["fee_funding_mojos"],
                "approval_authority": json.loads(consent["quote_json"])[
                    "approval_authority"
                ],
                "execution_context": json.loads(consent["quote_json"])[
                    "execution_context"
                ],
                "prestart_review": marker,
            }
        ),
        observed_at=observed_at,
        expires_at=expires_at,
    )
    review = _review_from_preview(stored)
    return {**review, "review_sha256": _review_digest(review)}


def confirm_prestart_follow_fee_ceiling(preview_id: str, review_sha256: str) -> dict:
    """Confirm native review without creating a worker, transaction or run."""
    _digest(preview_id)
    _digest(review_sha256)
    preview = database.get_coin_prep_fee_preview(preview_id)
    review = _review_from_preview(preview)
    if _review_digest(review) != review_sha256:
        raise ValueError("FEE_PRESTART_REVIEW_CHANGED")
    if database.coin_prep_fee_preview_consumed(preview_id):
        raise ValueError("FEE_PRESTART_REVIEW_USED")
    from coin_prep_fee_funding import prepare_fee_inventory
    from coin_prep_fee_runtime import read_approved_prep_fee_snapshot

    prior_id = review["prior_approval_id"]
    context = read_approved_prep_fee_snapshot(prior_id)
    completion = database.get_coin_prep_fee_session_completion(
        context["scope"]["session_id"]
    )
    if (
        completion["evidence_sha256"]
        != json.loads(preview["quote_json"])["prestart_review"][
            "completion_evidence_sha256"
        ]
    ):
        raise ValueError("FEE_APPROVAL_STALE")
    targets = _prove_approved_coin_prep_targets(context)
    if (
        sorted(targets.reused_coin_ids)
        != json.loads(completion["evidence_json"])["target_coin_ids"]
    ):
        raise ValueError("FEE_PRESTART_TARGETS_CHANGED")
    funding = prepare_fee_inventory(
        context["snapshot"],
        context["recipe"]["targets"],
        context["recipe"]["economic_plan"]["reserve_floors_mojos"],
    )
    result = database.confirm_prestart_follow_fee_ceiling_review(
        preview_id=preview_id,
        current_fee_funding_mojos=funding["fee_funding_mojos"],
    )
    # The ledger append is immutable. If the wallet changes during the commit,
    # the new consent cannot be used for Follow because its frozen execution
    # binding and exact inventory are rechecked by the next native review.
    after = read_approved_prep_fee_snapshot(result["approval_id"])
    if (
        any(
            after[key] != context[key]
            for key in (
                "identity",
                "configuration",
                "receive_address",
                "snapshot",
                "recipe",
                "scope",
            )
        )
        or _prove_approved_coin_prep_targets(after) != targets
    ):
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    return result
