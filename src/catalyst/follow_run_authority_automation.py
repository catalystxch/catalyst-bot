"""Create run authority after Coin Prep from the already confirmed Follow policy.

This is a continuation of the native policy confirmation, not a second review
screen. It creates no wallet effect; the existing Follow review/confirmation
service still owns the durable fee scope, overlap, and authority checks.
"""

from __future__ import annotations

from decimal import Decimal
import re
import time


_DIGEST = re.compile(r"[0-9a-f]{64}")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _validate_policy_and_prep(session_id: str) -> tuple[dict, object, dict, dict]:
    import confidence_override
    import database
    from coin_prep_fee_runtime import _configuration, read_approved_prep_fee_snapshot
    from follow_prep_fee_authority import verified_prep_fee_cap
    from follow_run_coordinator import FollowRunCoordinator

    if type(session_id) is not str or _DIGEST.fullmatch(session_id) is None:
        raise ValueError("FOLLOW_RUN_SESSION_REQUIRED")
    coordinator = FollowRunCoordinator()
    state = coordinator.get_state()
    policy = database.get_active_follow_run_policy()
    _require(
        type(state) is dict and state.get("session_id") == session_id,
        "FOLLOW_RUN_SESSION_REQUIRED",
    )
    _require(
        state.get("state") == "ready" and state.get("unknown_effect") is False,
        "FOLLOW_RUN_PREP_NOT_READY",
    )
    _require(
        state.get("run_id") is None
        or (
            type(state.get("run_id")) is str
            and _DIGEST.fullmatch(state["run_id"]) is not None
        ),
        "FOLLOW_RUN_AUTHORITY_ALREADY_BOUND",
    )
    _require(
        policy is not None and policy.digest == state.get("policy_digest"),
        "FOLLOW_RUN_POLICY_NOT_APPROVED",
    )

    configuration = _configuration()
    configuration_sha256 = confidence_override.current_configuration_digest()
    _require(
        configuration_sha256 == state.get("configuration_sha256")
        and confidence_override._configuration_digest(configuration)
        == configuration_sha256,
        "FOLLOW_RUN_AUTHORITY_CHANGED",
    )
    _require(
        configuration.get("MAX_ACTIVE_BUY_OFFERS") == policy.buy_target
        and configuration.get("MAX_ACTIVE_SELL_OFFERS") == policy.sell_target,
        "FOLLOW_RUN_AUTHORITY_CHANGED",
    )
    try:
        decimals = configuration["CAT_DECIMALS"]
        xch_reserve = Decimal(str(configuration["XCH_RESERVE"])) * 10**12
        cat_reserve = Decimal(str(configuration["CAT_RESERVE"])) * 10**decimals
        fee_principal = (
            configuration["FEE_PREP_COUNT"]
            * Decimal(str(configuration["FEE_COIN_SIZE_XCH"]))
            * 10**12
        )
        if any(
            value != value.to_integral_value()
            for value in (xch_reserve, cat_reserve, fee_principal)
        ):
            raise ValueError
        reserve_match = (
            int(xch_reserve) == policy.xch_reserve_mojos
            and int(cat_reserve) == policy.cat_reserve_atoms
            and int(fee_principal) == policy.fee_coin_principal_mojos
        )
    except Exception as exc:
        raise ValueError("FOLLOW_RUN_AUTHORITY_CHANGED") from exc
    _require(reserve_match, "FOLLOW_RUN_AUTHORITY_CHANGED")
    approval_id = state.get("fee_approval_id")
    prep_session_id = state.get("fee_approval_session_id")
    _require(
        type(approval_id) is str
        and _DIGEST.fullmatch(approval_id) is not None
        and type(prep_session_id) is str
        and _DIGEST.fullmatch(prep_session_id) is not None,
        "FOLLOW_RUN_PREP_FEE_BINDING_INVALID",
    )
    approved = read_approved_prep_fee_snapshot(approval_id)
    _require(
        type(approved) is dict
        and approved.get("approval", {}).get("approval_id") == approval_id
        and approved.get("scope", {}).get("session_id") == prep_session_id,
        "FOLLOW_RUN_PREP_FEE_BINDING_INVALID",
    )
    cap = verified_prep_fee_cap(
        policy=policy,
        coordinator_state=state,
        current_configuration_sha256=configuration_sha256,
        approved_snapshot=approved,
        requested_approval_id=approval_id,
        run_session_id=session_id,
    )
    _require(
        cap == policy.maximum_fee_mojos_per_tx, "FOLLOW_RUN_PREP_FEE_BINDING_INVALID"
    )

    status = database.get_coin_prep_fee_approval_status(approval_id)
    completion = database.get_coin_prep_fee_session_completion(prep_session_id)
    _require(
        type(status) is dict
        and status.get("approval_id") == approval_id
        and status.get("stale") is False
        and status.get("session_completed") is True
        and status.get("unresolved_operation_count") == 0
        and type(completion) is dict
        and completion.get("approval_id") == approval_id,
        "FOLLOW_RUN_PREP_NOT_CONFIRMED",
    )
    identity = approved.get("identity")
    scope = approved.get("scope")
    _require(
        type(identity) is dict
        and type(scope) is dict
        and scope.get("session_id") == prep_session_id
        and scope.get("campaign_id") is None
        and identity.get("network") == policy.network
        and str(identity.get("wallet_fingerprint")) == policy.wallet_fingerprint
        and identity.get("asset_id") == policy.asset_id,
        "FOLLOW_RUN_AUTHORITY_CHANGED",
    )
    return state, policy, approved, configuration


def _validate_proposal(policy, proposal: dict) -> None:
    """Ensure freshly observed principal and slots fit the signed policy."""
    funded_buy = proposal.get("funded_buy_limit", policy.buy_target)
    funded_sell = proposal.get("funded_sell_limit", policy.sell_target)
    partial = funded_buy != policy.buy_target or funded_sell != policy.sell_target
    _require(
        type(proposal) is dict
        and proposal.get("dispatch_authorized") is False
        and proposal.get("identity", {}).get("network") == policy.network
        and str(proposal.get("identity", {}).get("wallet_fingerprint"))
        == policy.wallet_fingerprint
        and proposal.get("identity", {}).get("asset_id") == policy.asset_id,
        "FOLLOW_RUN_AUTHORITY_CHANGED",
    )
    _require(
        proposal.get("buy_limit") == policy.buy_target
        and proposal.get("sell_limit") == policy.sell_target
        and proposal.get("replacement_count_gate_passed") is True
        and type(funded_buy) is int
        and type(funded_sell) is int
        and 1 <= funded_buy <= policy.buy_target
        and 1 <= funded_sell <= policy.sell_target
        and proposal.get("buy_slots_arithmetic_fit") == funded_buy
        and proposal.get("sell_slots_arithmetic_fit") == funded_sell
        and (
            not partial
            or (
                type(proposal.get("slot_assignment_sha256")) is str
                and _DIGEST.fullmatch(proposal["slot_assignment_sha256"]) is not None
            )
        ),
        "FOLLOW_SLOT_INVENTORY_SHORT",
    )
    for assignment in proposal.get("funded_output_assignments", []):
        try:
            price = Decimal(assignment["price_xch"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("FOLLOW_FUNDED_TARGET_PROOF_INVALID") from None
        _require(
            policy.price_min <= price <= policy.price_max,
            "FOLLOW_FUNDED_TARGET_PRICE_OUTSIDE_POLICY",
        )
    _require(
        type(proposal.get("maximum_trade_xch_mojos")) is int
        and type(proposal.get("maximum_trade_cat_atoms")) is int
        and proposal["maximum_trade_xch_mojos"] > 0
        and proposal["maximum_trade_cat_atoms"] > 0,
        "FOLLOW_TRADING_PRINCIPAL_INSUFFICIENT",
    )
    _require(
        proposal["maximum_trade_xch_mojos"] <= policy.maximum_trade_xch_mojos
        and proposal["maximum_trade_cat_atoms"] <= policy.maximum_trade_cat_atoms,
        "FOLLOW_TRADING_PRINCIPAL_EXCEEDS_APPROVAL",
    )
    _require(
        type(policy.price_anchor) is Decimal
        and type(policy.price_min) is Decimal
        and type(policy.price_max) is Decimal
        and policy.price_min <= policy.price_anchor <= policy.price_max,
        "FOLLOW_RUN_POLICY_INVALID",
    )
    funding = proposal.get("shutdown_funding")
    _require(
        type(funding) is dict and funding.get("ready") is True,
        funding.get("reason", "FOLLOW_SHUTDOWN_FUNDING_REQUIRED")
        if type(funding) is dict
        else "FOLLOW_SHUTDOWN_FUNDING_REQUIRED",
    )
    quoted = funding.get("quoted_fee_mojos")
    _require(type(quoted) is int and quoted > 0, "FOLLOW_SHUTDOWN_FUNDING_REQUIRED")


def _validate_observed_proposal(policy, proposal, approved, configuration_sha256):
    _validate_proposal(policy, proposal)
    identity_keys = (
        "network",
        "wallet_type",
        "wallet_fingerprint",
        "wallet_id",
        "xch_wallet_id",
        "asset_id",
        "ticker",
    )
    expected_identity = {key: approved["identity"].get(key) for key in identity_keys}
    _require(
        proposal.get("identity") == expected_identity
        and proposal.get("configuration_sha256") == configuration_sha256,
        "FOLLOW_RUN_AUTHORITY_CHANGED",
    )


def _fee_cap_warning(policy, proposal, *, run_id=None):
    recommended_fee = proposal["shutdown_funding"]["quoted_fee_mojos"]
    if recommended_fee <= policy.maximum_fee_mojos_per_tx:
        return None
    return {
        "code": "FOLLOW_FEE_RECOMMENDATION_ABOVE_POLICY_CAP",
        "run_id": run_id,
        "recommended_fee_mojos": recommended_fee,
        "maximum_fee_mojos_per_tx": policy.maximum_fee_mojos_per_tx,
        "message": "The current network recommendation is above the approved per-transaction cap; cancellations must use an exact quote at or below the cap.",
    }


def authorize_approved_follow_run(session_id: str) -> dict:
    """Bind a real authority run ID using prior native policy consent.

    The active policy is the durable record of the native confirmation. Exact
    prep approval, wallet/configuration, principal, slots and the per-tx fee
    limit are freshly reproved before the existing authority service is used.
    """
    import database
    from confidence_override import current_configuration_digest
    from follow_principal import (
        confirm_follow_run_review,
        prepare_follow_run_review,
        preview_approved_follow_principal,
    )
    from follow_run_coordinator import FollowRunCoordinator
    from follow_run_terms import CONTINUOUS_RUN_EXPIRY

    state, policy, approved, _configuration = _validate_policy_and_prep(session_id)
    configuration_sha256 = state["configuration_sha256"]
    approval_id = state["fee_approval_id"]
    now = int(time.time())

    # Check existing idempotent state without minting a second authority.
    current_state = FollowRunCoordinator().get_state()
    if current_state is not None and current_state.get("run_id") is not None:
        authority = database.get_follow_creation_authority(
            identity=approved["identity"],
            configuration_sha256=configuration_sha256,
            now_epoch=now,
        )
        _require(
            authority.get("ready") is True
            and authority.get("run_id") == current_state["run_id"]
            and authority.get("approval_id") == approval_id
            and authority.get("identity") == approved["identity"]
            and authority.get("configuration_sha256") == configuration_sha256
            and authority.get("buy_limit") == policy.buy_target
            and authority.get("sell_limit") == policy.sell_target,
            "FOLLOW_RUN_AUTHORITY_PROOF_INVALID",
        )
        existing_proposal = preview_approved_follow_principal(
            approval_id, buy_limit=policy.buy_target, sell_limit=policy.sell_target
        )
        _validate_observed_proposal(
            policy, existing_proposal, approved, configuration_sha256
        )
        _require(
            current_state.get("funded_buy_limit")
            == existing_proposal["funded_buy_limit"]
            and current_state.get("funded_sell_limit")
            == existing_proposal["funded_sell_limit"]
            and current_state.get("funded_proof_sha256")
            == existing_proposal["slot_assignment_sha256"],
            "FOLLOW_RUN_AUTHORITY_PROOF_INVALID",
        )
        return {
            "success": True,
            "state": current_state["state"],
            "run_id": current_state["run_id"],
            "fee_warning": _fee_cap_warning(
                policy, existing_proposal, run_id=current_state["run_id"]
            ),
            "dispatch_authorized": False,
        }

    proposal = preview_approved_follow_principal(
        approval_id, buy_limit=policy.buy_target, sell_limit=policy.sell_target
    )
    _validate_observed_proposal(policy, proposal, approved, configuration_sha256)
    _require(
        current_configuration_digest() == configuration_sha256
        and database.get_active_follow_run_policy().digest == policy.digest,
        "FOLLOW_RUN_AUTHORITY_CHANGED",
    )

    # Existing review confirmation retains the durable fee-scope, stale
    # approval, overlap, stopped-bot, shutdown funding and SQLite guards. The
    # review is created only after prior native policy confirmation.
    fee_status = database.get_coin_prep_fee_approval_status(approval_id)
    _require(
        type(fee_status) is dict
        and type(fee_status.get("total_fee_mojos")) is int
        and fee_status["total_fee_mojos"] > 0,
        "FOLLOW_FEE_APPROVAL_STALE",
    )
    # The run review's maximum is the approved cumulative scope budget. The
    # independent per-transaction ceiling remains policy.maximum_fee_mojos_per_tx.
    review = prepare_follow_run_review(
        approval_id,
        buy_limit=policy.buy_target,
        sell_limit=policy.sell_target,
        duration_seconds=None,
        requested_fee_cap_mojos=fee_status["total_fee_mojos"],
        continuous=True,
    )
    _validate_observed_proposal(policy, review, approved, configuration_sha256)
    result = confirm_follow_run_review(review["review_id"], review["review_sha256"])
    run_id = result.get("run_id") if type(result) is dict else None
    _require(
        type(run_id) is str
        and _DIGEST.fullmatch(run_id) is not None
        and result.get("dispatch_authorized") is False,
        "FOLLOW_RUN_AUTHORITY_REQUIRED",
    )

    # Quote and policy may change while the review service rechecks the
    # proposal. The independent shutdown funding proof still must pass; a
    # recommendation above the per-tx policy cap is reported for the capped
    # cancellation path, which performs its own exact quote and unsigned build.
    try:
        after_state, after_policy, after_approved, _ = _validate_policy_and_prep(
            session_id
        )
        after_proposal = preview_approved_follow_principal(
            approval_id, buy_limit=policy.buy_target, sell_limit=policy.sell_target
        )
        _validate_observed_proposal(
            policy, after_proposal, after_approved, configuration_sha256
        )
        _require(
            after_policy.digest == policy.digest
            and after_state["configuration_sha256"] == configuration_sha256
            and after_approved["identity"] == approved["identity"],
            "FOLLOW_RUN_AUTHORITY_CHANGED",
        )
    except Exception:
        database.stop_follow_run_authority(
            run_id=run_id, stopped_at_epoch=int(time.time())
        )
        raise

    try:
        bound = FollowRunCoordinator().bind_authority(
            session_id=session_id,
            run_id=run_id,
            policy_digest=policy.digest,
            configuration_sha256=configuration_sha256,
            funded_buy_limit=after_proposal["funded_buy_limit"],
            funded_sell_limit=after_proposal["funded_sell_limit"],
            funded_proof_sha256=after_proposal["slot_assignment_sha256"],
        )
        _require(
            bound.get("run_id") == run_id and bound.get("state") == "ready",
            "FOLLOW_RUN_AUTHORITY_PROOF_INVALID",
        )
    except Exception:
        try:
            database.stop_follow_run_authority(
                run_id=run_id, stopped_at_epoch=int(time.time())
            )
        except Exception:
            pass
        raise
    # The state machine itself owns the continuous lifetime sentinel. This
    # assertion catches accidental divergence from the authority convention.
    _require(CONTINUOUS_RUN_EXPIRY > int(time.time()), "FOLLOW_RUN_AUTHORITY_INVALID")
    return {
        "success": True,
        "state": bound["state"],
        "run_id": run_id,
        "fee_warning": _fee_cap_warning(policy, after_proposal, run_id=run_id),
        "dispatch_authorized": False,
    }
