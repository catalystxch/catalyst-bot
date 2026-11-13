"""Advance an already approved Follow setup through guarded Coin Prep."""

from __future__ import annotations

import re


def _route_json(route, path: str, *, body: dict | None = None, permit=None) -> dict:
    import api_server
    from flask import g
    import json

    with api_server.app.test_request_context(
        path,
        method="POST" if body is not None else "GET",
        content_type="application/json" if body is not None else None,
        data=json.dumps(body) if body is not None else None,
    ):
        if permit is not None:
            g._mutation_permit = permit
        try:
            response = route()
        finally:
            if permit is not None:
                g.pop("_mutation_permit", None)
    if type(response) is tuple:
        response = response[0]
    return response.get_json() if hasattr(response, "get_json") else {}


def advance_approved_follow_run(session_id: str, *, permit=None) -> dict:
    """One idempotent progress step. No client supplied fee or wallet authority."""
    import confidence_override
    import database
    from follow_run_coordinator import FollowRunCoordinator

    if type(session_id) is not str or re.fullmatch(r"[0-9a-f]{64}", session_id) is None:
        raise ValueError("FOLLOW_RUN_SESSION_REQUIRED")
    coordinator = FollowRunCoordinator()
    state = coordinator.get_state()
    policy = database.get_active_follow_run_policy()
    if (
        type(state) is not dict
        or state["session_id"] != session_id
        or policy is None
        or state["policy_digest"] != policy.digest
        or state["configuration_sha256"]
        != confidence_override.current_configuration_digest()
    ):
        raise ValueError("FOLLOW_RUN_AUTHORITY_CHANGED")
    key = {
        "session_id": session_id,
        "policy_digest": state["policy_digest"],
        "configuration_sha256": state["configuration_sha256"],
    }
    if state["state"] == "prep_pending":
        approval_id = state["fee_approval_id"]
        if approval_id is None:
            from coin_prep_fee_approval import (
                approve_coin_prep_fees,
                preview_coin_prep_fees,
            )

            preview = preview_coin_prep_fees(
                {"coin_multiplier": "1", "target_seconds": 300}
            )
            if preview.get("available") is not True:
                return {
                    "success": False,
                    "state": "prep_pending",
                    "reason": preview.get("reason", "FEE_PREVIEW_UNAVAILABLE"),
                    "action_needed": True,
                }
            approved = approve_coin_prep_fees(preview_id=preview["preview_id"])
            approval_id = approved["approval_id"]
            coordinator.bind_prep_approval(**key, approval_id=approval_id)
        coordinator.mark_preparing(**key)
        import api_server

        result = _route_json(
            api_server.api_coin_prep_trigger,
            "/api/coin-prep/trigger",
            body={"coin_multiplier": 1, "fee_approval_id": approval_id},
            permit=permit,
        )
        if result.get("success") is not True:
            # The route may have reached the worker before its response failed.
            # Require independent status reconciliation before another launch.
            coordinator.record_recoverable_error(
                **key, reason="PREP_START_UNVERIFIED", unknown_effect=True
            )
            return {
                "success": False,
                "state": "recoverable_error",
                "reason": result.get("reason", "PREP_START_UNVERIFIED"),
                "action_needed": True,
            }
        return {
            "success": True,
            "state": "preparing",
            "message": "Preparing the approved ladder coins",
            "action_needed": False,
        }
    if state["state"] == "preparing":
        import api_server

        status = _route_json(api_server.api_coin_prep_status, "/api/coin-prep/status")
        if status.get("success") is not True:
            return {
                "success": False,
                "state": "preparing",
                "reason": "PREP_STATUS_UNAVAILABLE",
                "action_needed": True,
            }
        if status.get("running") is True:
            return {
                "success": True,
                "state": "preparing",
                "message": str(status.get("message") or "Preparing ladder coins")[:256],
                "action_needed": False,
            }
        if (
            status.get("complete") is True
            and status.get("fee_approval_id") == state["fee_approval_id"]
            and not status.get("error")
        ):
            coordinator.reconcile_prep(
                **key,
                effect_status="confirmed",
                prep_complete=True,
                fee_status="within_cap",
            )
            return {
                "success": True,
                "state": "ready",
                "message": "Coin preparation completed; checking run authority",
                "action_needed": False,
            }
        return {
            "success": False,
            "state": "preparing",
            "reason": "PREP_RESULT_UNVERIFIED",
            "action_needed": True,
        }
    if state["state"] in {"running", "start_pending"}:
        return {
            "success": True,
            "state": state["state"],
            "message": "Approved ladder is starting" if state["state"] == "start_pending" else "Approved ladder is running",
            "action_needed": False,
        }
    if state["state"] == "ready":
        return {
            "success": False,
            "state": "ready",
            "reason": "FOLLOW_RUN_AUTHORITY_NOT_BOUND",
            "action_needed": True,
        }
    return {
        "success": False,
        "state": state["state"],
        "reason": state.get("recoverable_reason") or "FOLLOW_RUN_RECOVERY_REQUIRED",
        "action_needed": True,
    }
