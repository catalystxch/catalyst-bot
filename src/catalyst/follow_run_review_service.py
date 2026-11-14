"""Short-lived, disclosure-only approval for a Follow run policy."""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
import hashlib
import json
import re
import secrets
import threading
import time

from follow_run_policy import FollowRunPolicy


_DEFAULT_REVIEW_TTL_SECONDS = 300
_MAX_REVIEW_TTL_SECONDS = 900
_reviews: dict[str, dict] = {}
_reviews_lock = threading.RLock()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_identity(identity: object, policy: FollowRunPolicy) -> dict:
    if type(identity) is not dict or any(type(key) is not str for key in identity):
        raise ValueError("FOLLOW_RUN_REVIEW_IDENTITY_INVALID")
    try:
        copied = json.loads(_canonical_json(identity))
    except (TypeError, ValueError):
        raise ValueError("FOLLOW_RUN_REVIEW_IDENTITY_INVALID") from None
    if (
        copied.get("network") != policy.network
        or copied.get("wallet_fingerprint") != policy.wallet_fingerprint
        or copied.get("asset_id") != policy.asset_id
    ):
        raise ValueError("FOLLOW_RUN_REVIEW_IDENTITY_MISMATCH")
    return copied


def _policy_terms(policy: FollowRunPolicy) -> dict:
    terms = {}
    for field in fields(policy):
        value = getattr(policy, field.name)
        if isinstance(value, Decimal):
            value = "0" if value == 0 else format(value.normalize(), "f")
        terms[field.name] = value
    return terms


def _review_digest(disclosure: dict) -> str:
    return hashlib.sha256(_canonical_json(disclosure).encode("utf-8")).hexdigest()


def _validated_reasons(reasons: object) -> list[str]:
    if type(reasons) not in (list, tuple) or any(
        type(reason) is not str or not reason.strip() for reason in reasons
    ):
        raise ValueError("FOLLOW_RUN_REVIEW_REASONS_INVALID")
    return list(reasons)


def prepare_follow_run_policy_review(
    policy: FollowRunPolicy,
    *,
    wallet_identity: dict,
    configuration_sha256: str,
    red_reasons: list[str] | tuple[str, ...],
    now_epoch: int | None = None,
    ttl_seconds: int = _DEFAULT_REVIEW_TTL_SECONDS,
) -> dict:
    """Freeze the exact disclosure; this does not persist or authorize it."""
    if not isinstance(policy, FollowRunPolicy):
        raise ValueError("FOLLOW_RUN_REVIEW_POLICY_INVALID")
    now = int(time.time()) if now_epoch is None else now_epoch
    if type(now) is not int or now < 0:
        raise ValueError("FOLLOW_RUN_REVIEW_TIME_INVALID")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= _MAX_REVIEW_TTL_SECONDS:
        raise ValueError("FOLLOW_RUN_REVIEW_TTL_INVALID")
    if (
        type(configuration_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", configuration_sha256) is None
    ):
        raise ValueError("FOLLOW_RUN_REVIEW_CONFIGURATION_INVALID")
    reasons = _validated_reasons(red_reasons)

    identity = _canonical_identity(wallet_identity, policy)
    review_id = secrets.token_hex(32)
    expires_at = now + ttl_seconds
    disclosure = {
        "identity": identity,
        "policy": _policy_terms(policy),
        "policy_digest": policy.digest,
        "configuration_sha256": configuration_sha256,
        "red_reasons": reasons,
        "review_id": review_id,
        "review_expires_at_epoch": expires_at,
    }
    digest = _review_digest(disclosure)
    with _reviews_lock:
        for key in [
            key for key, value in _reviews.items() if value["expires_at"] <= now
        ]:
            del _reviews[key]
        _reviews[review_id] = {
            "policy": policy,
            "policy_digest": policy.digest,
            "identity": identity,
            "configuration_sha256": configuration_sha256,
            "red_reasons": reasons,
            "disclosure": disclosure,
            "review_sha256": digest,
            "expires_at": expires_at,
        }
    return {
        "success": True,
        "review_id": review_id,
        "review_sha256": digest,
        "policy_digest": policy.digest,
        "review_expires_at_epoch": expires_at,
        "disclosure": json.loads(_canonical_json(disclosure)),
    }


def confirm_follow_run_policy_review(
    *,
    review_id: str,
    review_sha256: str,
    accepted: bool,
    current_policy: FollowRunPolicy,
    current_wallet_identity: dict,
    current_configuration_sha256: str,
    current_red_reasons: list[str] | tuple[str, ...],
    now_epoch: int | None = None,
) -> dict:
    """Persist the reviewed policy only after exact, explicit confirmation."""
    if accepted is not True:
        if type(review_id) is str:
            with _reviews_lock:
                _reviews.pop(review_id, None)
        return {"success": False, "reason": "FOLLOW_RUN_REVIEW_NOT_ACCEPTED"}
    now = int(time.time()) if now_epoch is None else now_epoch
    if type(now) is not int or now < 0:
        return {"success": False, "reason": "FOLLOW_RUN_REVIEW_INVALID"}
    if (
        type(review_id) is not str
        or len(review_id) != 64
        or type(review_sha256) is not str
        or len(review_sha256) != 64
        or not isinstance(current_policy, FollowRunPolicy)
    ):
        return {"success": False, "reason": "FOLLOW_RUN_REVIEW_INVALID"}

    with _reviews_lock:
        review = _reviews.get(review_id)
        if review is None:
            return {"success": False, "reason": "FOLLOW_RUN_REVIEW_REQUIRED"}
        if now >= review["expires_at"]:
            del _reviews[review_id]
            return {"success": False, "reason": "FOLLOW_RUN_REVIEW_EXPIRED"}
        if (
            review_sha256 != review["review_sha256"]
            or _review_digest(review["disclosure"]) != review["review_sha256"]
        ):
            return {"success": False, "reason": "FOLLOW_RUN_REVIEW_CHANGED"}
        try:
            identity = _canonical_identity(current_wallet_identity, current_policy)
            reasons = _validated_reasons(current_red_reasons)
        except (TypeError, ValueError):
            return {"success": False, "reason": "FOLLOW_RUN_REVIEW_CHANGED"}
        if (
            current_policy.digest != review["policy_digest"]
            or identity != review["identity"]
            or current_configuration_sha256 != review["configuration_sha256"]
            or reasons != review["red_reasons"]
        ):
            del _reviews[review_id]
            return {"success": False, "reason": "FOLLOW_RUN_REVIEW_CHANGED"}

        try:
            import database

            persisted = database.record_active_follow_run_policy(current_policy)
            if persisted is not True:
                raise ValueError("FOLLOW_RUN_POLICY_PERSIST_FAILED")
        except Exception:
            return {
                "success": False,
                "reason": "FOLLOW_RUN_POLICY_PERSIST_FAILED",
            }
        del _reviews[review_id]
        return {
            "success": True,
            "policy_digest": current_policy.digest,
            "dispatch_authorized": False,
        }
