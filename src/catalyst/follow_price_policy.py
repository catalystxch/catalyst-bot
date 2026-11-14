"""Pure fallback decision for an identity-bound approved Follow price anchor."""

from decimal import Decimal

from follow_run_policy import FollowRunPolicy


def _blocked(reason: str) -> dict:
    return {
        "use_anchor": False,
        "price": None,
        "source": None,
        "warning_active": False,
        "warning_code": None,
        "reason": reason,
    }


def approved_anchor_fallback(
    *,
    policy: FollowRunPolicy,
    live_price_available: bool,
    run_active: bool,
    wallet_identity_matches: bool,
    red_guard_allows: bool,
) -> dict:
    """Use the approved in-range anchor only when no live source is available.

    The caller must supply the currently approved durable policy, the result
    of active-run and wallet-identity checks, and the existing RED governance
    decision. This helper grants no authority and imposes no anchor timeout.
    Its warning remains active on every fallback decision until live pricing
    becomes available.
    """
    if type(live_price_available) is not bool:
        return _blocked("LIVE_PRICE_STATUS_INVALID")
    if live_price_available:
        return {
            "use_anchor": False,
            "price": None,
            "source": None,
            "warning_active": False,
            "warning_code": None,
            "reason": None,
        }
    if not isinstance(policy, FollowRunPolicy):
        return _blocked("FOLLOW_RUN_POLICY_REQUIRED")
    if run_active is not True:
        return _blocked("FOLLOW_RUN_NOT_ACTIVE")
    if wallet_identity_matches is not True:
        return _blocked("FOLLOW_RUN_WALLET_IDENTITY_MISMATCH")
    if red_guard_allows is not True:
        return _blocked("RED_GUARD_BLOCKED")

    anchor = policy.price_anchor
    minimum = policy.price_min
    maximum = policy.price_max
    if (
        not isinstance(anchor, Decimal)
        or not isinstance(minimum, Decimal)
        or not isinstance(maximum, Decimal)
        or not anchor.is_finite()
        or not minimum.is_finite()
        or not maximum.is_finite()
        or minimum <= 0
        or not minimum <= anchor <= maximum
    ):
        return _blocked("FOLLOW_RUN_PRICE_POLICY_INVALID")

    return {
        "use_anchor": True,
        "price": anchor,
        "source": "approved_follow_anchor",
        "warning_active": True,
        "warning_code": "APPROVED_PRICE_ANCHOR_IN_USE",
        "reason": None,
    }
