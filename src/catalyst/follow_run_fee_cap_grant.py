"""Native-confirmed per-transaction cap grant for one active Follow run.

The grant is intentionally stored apart from :class:`FollowRunPolicy`: that
policy's digest is part of the run's authority proof and must remain stable.
This service records operator consent only; fee consumers must separately
verify the grant before using its higher cap.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time


_PENDING_KEY = "follow_run_fee_cap_review_v1"
_GRANT_KEY = "follow_run_fee_cap_grant_v1"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_FEE = 2**63 - 1
_REVIEW_TTL_SECONDS = 120
_QUOTE_MAX_AGE_SECONDS = 30
_LOCK = threading.RLock()


def _canonical_digest(value: dict) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _active_context(*, now_epoch: int) -> tuple[dict, object, dict, str]:
    import database
    from confidence_override import current_configuration_digest
    from follow_run_coordinator import FollowRunCoordinator

    state = FollowRunCoordinator().get_state()
    policy = database.get_active_follow_run_policy()
    if (
        type(state) is not dict
        or state.get("state") != "running"
        or type(state.get("run_id")) is not str
        or _DIGEST.fullmatch(state["run_id"]) is None
        or policy is None
        or state.get("policy_digest") != policy.digest
    ):
        raise ValueError("FOLLOW_FEE_CAP_GRANT_AUTHORITY_REQUIRED")
    config_digest = current_configuration_digest()
    if state.get("configuration_sha256") != config_digest:
        raise ValueError("FOLLOW_FEE_CAP_GRANT_AUTHORITY_CHANGED")
    identity = database.get_follow_run_identity(state["run_id"])
    if (
        type(identity) is not dict
        or identity.get("network") != policy.network
        or identity.get("asset_id") != policy.asset_id
        or str(identity.get("wallet_fingerprint")) != policy.wallet_fingerprint
    ):
        raise ValueError("FOLLOW_FEE_CAP_GRANT_AUTHORITY_CHANGED")
    authority = database.get_follow_creation_authority(
        identity=identity, configuration_sha256=config_digest, now_epoch=now_epoch
    )
    if (
        type(authority) is not dict
        or authority.get("ready") is not True
        or authority.get("run_id") != state["run_id"]
        or authority.get("identity") != identity
        or authority.get("configuration_sha256") != config_digest
        or authority.get("buy_limit") != policy.buy_target
        or authority.get("sell_limit") != policy.sell_target
    ):
        raise ValueError("FOLLOW_FEE_CAP_GRANT_AUTHORITY_CHANGED")
    return state, policy, identity, config_digest


def _fresh_recommendation(*, now_epoch: int) -> dict:
    """Read fresh fee evidence from the trusted server-side estimator."""
    try:
        import tx_fees

        quote = tx_fees.get_suggested_transaction_fee(force_refresh=True)
    except Exception as exc:
        raise ValueError("FOLLOW_FEE_CAP_GRANT_RECOMMENDATION_UNAVAILABLE") from exc
    if (
        type(quote) is not dict
        or quote.get("available") is not True
        or type(quote.get("fee_mojos")) is not int
        or not 0 < quote["fee_mojos"] <= _MAX_FEE
        or type(quote.get("observed_at")) is not int
        or not 0 <= now_epoch - quote["observed_at"] <= _QUOTE_MAX_AGE_SECONDS
        or type(quote.get("source")) is not str
        or not quote["source"]
        or type(quote.get("target_seconds")) is not int
        or quote["target_seconds"] < 1
    ):
        raise ValueError("FOLLOW_FEE_CAP_GRANT_RECOMMENDATION_UNAVAILABLE")
    return {
        "fee_mojos": quote["fee_mojos"],
        "source": quote["source"],
        "observed_at": quote["observed_at"],
        "target_seconds": quote["target_seconds"],
        "cost": quote.get("cost"),
    }


def prepare_follow_run_fee_cap_grant(*, now_epoch: int | None = None) -> dict:
    """Freeze a fresh recommendation above the approved cap for native review."""
    now = int(time.time()) if now_epoch is None else now_epoch
    if type(now) is not int or now < 0:
        raise ValueError("FOLLOW_FEE_CAP_GRANT_INVALID")
    state, policy, identity, config_digest = _active_context(now_epoch=now)
    recommendation = _fresh_recommendation(now_epoch=now)
    recommended_fee_mojos = recommendation["fee_mojos"]
    prior = policy.maximum_fee_mojos_per_tx
    if recommended_fee_mojos <= prior:
        raise ValueError("FOLLOW_FEE_CAP_GRANT_NOT_REQUIRED")
    terms = {
        "review_id": secrets.token_hex(32),
        "run_id": state["run_id"],
        "session_id": state["session_id"],
        "policy_digest": policy.digest,
        "configuration_sha256": config_digest,
        "wallet_identity": identity,
        "prior_maximum_fee_mojos_per_tx": prior,
        "recommended_fee_mojos": recommended_fee_mojos,
        "network_recommendation": recommendation,
        "proposed_maximum_fee_mojos_per_tx": recommended_fee_mojos,
        "reviewed_at_epoch": now,
        "expires_at_epoch": now + _REVIEW_TTL_SECONDS,
    }
    review = {
        **terms,
        "review_sha256": _canonical_digest(terms),
        "dispatch_authorized": False,
    }
    import database

    with _LOCK:
        if (
            database.set_setting(
                _PENDING_KEY, json.dumps(review, sort_keys=True, separators=(",", ":"))
            )
            is not True
        ):
            raise ValueError("FOLLOW_FEE_CAP_GRANT_PERSIST_FAILED")
    return {"success": True, "review": review, "dispatch_authorized": False}


def confirm_follow_run_fee_cap_grant(
    *, review_id: str, review_sha256: str, accepted: bool, now_epoch: int | None = None
) -> dict:
    """Persist the exact explicitly accepted review without touching policy/run proof."""
    now = int(time.time()) if now_epoch is None else now_epoch
    if (
        type(now) is not int
        or now < 0
        or accepted is not True
        or type(review_id) is not str
        or _DIGEST.fullmatch(review_id) is None
        or type(review_sha256) is not str
        or _DIGEST.fullmatch(review_sha256) is None
    ):
        raise ValueError("FOLLOW_FEE_CAP_GRANT_CONFIRMATION_REQUIRED")
    state, policy, identity, config_digest = _active_context(now_epoch=now)
    import database

    with _LOCK:
        raw = database.get_setting(_PENDING_KEY)
        try:
            review = json.loads(raw) if type(raw) is str else None
        except Exception as exc:
            raise ValueError("FOLLOW_FEE_CAP_GRANT_REVIEW_REQUIRED") from exc
        if type(review) is not dict or set(review) != {
            "review_id",
            "run_id",
            "session_id",
            "policy_digest",
            "configuration_sha256",
            "wallet_identity",
            "prior_maximum_fee_mojos_per_tx",
            "recommended_fee_mojos",
            "network_recommendation",
            "proposed_maximum_fee_mojos_per_tx",
            "reviewed_at_epoch",
            "expires_at_epoch",
            "review_sha256",
            "dispatch_authorized",
        }:
            raise ValueError("FOLLOW_FEE_CAP_GRANT_REVIEW_REQUIRED")
        terms = {
            key: value
            for key, value in review.items()
            if key not in {"review_sha256", "dispatch_authorized"}
        }
        if review.get("review_sha256") != _canonical_digest(
            terms
        ) or review_sha256 != review.get("review_sha256"):
            raise ValueError("FOLLOW_FEE_CAP_GRANT_REVIEW_CHANGED")
        if review.get("review_id") != review_id:
            raise ValueError("FOLLOW_FEE_CAP_GRANT_REVIEW_REQUIRED")
        if not review["reviewed_at_epoch"] <= now < review["expires_at_epoch"]:
            raise ValueError("FOLLOW_FEE_CAP_GRANT_REVIEW_EXPIRED")
        if (
            review["run_id"] != state["run_id"]
            or review["session_id"] != state["session_id"]
            or review["policy_digest"] != policy.digest
            or review["configuration_sha256"] != config_digest
            or review["wallet_identity"] != identity
            or review["prior_maximum_fee_mojos_per_tx"]
            != policy.maximum_fee_mojos_per_tx
            or review["proposed_maximum_fee_mojos_per_tx"]
            != review["recommended_fee_mojos"]
            or type(review["recommended_fee_mojos"]) is not int
            or review["recommended_fee_mojos"] <= policy.maximum_fee_mojos_per_tx
        ):
            raise ValueError("FOLLOW_FEE_CAP_GRANT_REVIEW_CHANGED")
        current_recommendation = _fresh_recommendation(now_epoch=now)
        reviewed_recommendation = review["network_recommendation"]
        if any(
            current_recommendation.get(key) != reviewed_recommendation.get(key)
            for key in ("fee_mojos", "source", "target_seconds", "cost")
        ):
            raise ValueError("FOLLOW_FEE_CAP_GRANT_REVIEW_CHANGED")
        grant_terms = {
            "version": 1,
            "run_id": state["run_id"],
            "session_id": state["session_id"],
            "policy_digest": policy.digest,
            "configuration_sha256": config_digest,
            "wallet_identity": identity,
            "prior_maximum_fee_mojos_per_tx": policy.maximum_fee_mojos_per_tx,
            "maximum_fee_mojos_per_tx": review["proposed_maximum_fee_mojos_per_tx"],
            "review_id": review_id,
            "review_sha256": review_sha256,
            "confirmed_at_epoch": now,
        }
        grant = {
            **grant_terms,
            "grant_sha256": _canonical_digest(grant_terms),
            "dispatch_authorized": False,
        }
        if database.set_setting(_PENDING_KEY, "") is not True:
            raise ValueError("FOLLOW_FEE_CAP_GRANT_PERSIST_FAILED")
        if (
            database.set_setting(
                _GRANT_KEY, json.dumps(grant, sort_keys=True, separators=(",", ":"))
            )
            is not True
        ):
            raise ValueError("FOLLOW_FEE_CAP_GRANT_PERSIST_FAILED")
    return {
        "success": True,
        "grant": grant,
        "policy_digest": policy.digest,
        "dispatch_authorized": False,
    }


def get_follow_run_fee_cap_grant(
    *, run_id: str, now_epoch: int | None = None
) -> dict | None:
    """Return a verified grant only while its exact run/policy/config binding is active."""
    now = int(time.time()) if now_epoch is None else now_epoch
    state, policy, identity, config_digest = _active_context(now_epoch=now)
    if state["run_id"] != run_id:
        return None
    import database

    raw = database.get_setting(_GRANT_KEY)
    try:
        grant = json.loads(raw) if type(raw) is str else None
    except Exception:
        return None
    if type(grant) is not dict or grant.get("dispatch_authorized") is not False:
        return None
    terms = {
        key: value
        for key, value in grant.items()
        if key not in {"grant_sha256", "dispatch_authorized"}
    }
    if (
        grant.get("grant_sha256") != _canonical_digest(terms)
        or grant.get("run_id") != run_id
        or grant.get("session_id") != state["session_id"]
        or grant.get("policy_digest") != policy.digest
        or grant.get("configuration_sha256") != config_digest
        or grant.get("wallet_identity") != identity
        or grant.get("prior_maximum_fee_mojos_per_tx")
        != policy.maximum_fee_mojos_per_tx
        or type(grant.get("maximum_fee_mojos_per_tx")) is not int
        or grant["maximum_fee_mojos_per_tx"] <= policy.maximum_fee_mojos_per_tx
    ):
        return None
    return grant
