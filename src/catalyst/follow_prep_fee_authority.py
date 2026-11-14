"""Verify the exact pre-run Follow binding required for prep fee limits.

This module is intentionally not wired to legacy Coin Prep dispatch. Callers
must supply the coordinator's durable approval link, the current policy and
configuration, the current wallet identity, and the exact validated fee
approval context.
"""

import re

from follow_run_policy import FollowRunPolicy


_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_ACTIVE_PREP_STATES = frozenset(
    {
        "prep_pending",
        "preparing",
        "awaiting_confirmation",
        "ready",
        "start_pending",
        "running",
    }
)


def _digest(value):
    return type(value) is str and _DIGEST_RE.fullmatch(value) is not None


def verified_prep_fee_cap(
    *,
    policy,
    coordinator_state,
    current_configuration_sha256,
    approved_snapshot,
    requested_approval_id,
    run_session_id,
) -> int:
    """Return the approved per-transaction cap only for an exact run binding.

    The coordinator session binds pre-run Coin Prep before a real run ID exists.
    Its durable record must point to both the exact Coin Prep fee approval and
    that approval's Coin Prep session. Cumulative approval amounts are ignored.
    """
    valid = (
        isinstance(policy, FollowRunPolicy)
        and type(coordinator_state) is dict
        and type(approved_snapshot) is dict
        and type(approved_snapshot.get("identity")) is dict
        and type(approved_snapshot.get("scope")) is dict
        and type(approved_snapshot.get("approval")) is dict
        and _digest(current_configuration_sha256)
        and _digest(run_session_id)
        and _digest(requested_approval_id)
    )
    if not valid:
        raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_REQUIRED")

    coordinator = coordinator_state
    approval_id = approved_snapshot["approval"].get("approval_id")
    prep_session_id = approved_snapshot["scope"].get("session_id")
    wallet_identity = approved_snapshot["identity"]
    fingerprint = wallet_identity.get("wallet_fingerprint")
    network = wallet_identity.get("network")
    asset_id = wallet_identity.get("asset_id")
    run_id = coordinator.get("run_id")
    if (
        coordinator.get("state") not in _ACTIVE_PREP_STATES
        or coordinator.get("session_id") != run_session_id
        or coordinator.get("policy_digest") != policy.digest
        or coordinator.get("configuration_sha256") != current_configuration_sha256
        or (run_id is not None and not _digest(run_id))
        or coordinator.get("fee_approval_id") != requested_approval_id
        or coordinator.get("fee_approval_session_id") != prep_session_id
        or approval_id != requested_approval_id
        or not _digest(prep_session_id)
        or type(fingerprint) is not int
        or str(fingerprint) != policy.wallet_fingerprint
        or network != policy.network
        or asset_id != policy.asset_id
    ):
        raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_REQUIRED")

    return policy.maximum_fee_mojos_per_tx
