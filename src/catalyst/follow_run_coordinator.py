"""Durable orchestration state for one approved Follow run.

This module records progress only. It performs no wallet operation and grants
no authority by itself; callers continue to use the existing guarded services.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time


_VERSION = 1
_RUN_ID_RE = re.compile(r"[0-9a-f]{64}")
_STATES = {
    "prep_pending",
    "preparing",
    "awaiting_confirmation",
    "ready",
    "start_pending",
    "running",
    "recoverable_error",
    "stopped",
}
_LOCK = threading.RLock()


class FollowRunCoordinator:
    """Persist and idempotently advance a single approved run session."""

    SETTING_KEY = "follow_run_coordinator_v1"

    def _read(self) -> dict | None:
        import database

        try:
            raw = database.get_setting(self.SETTING_KEY)
        except Exception as exc:
            raise ValueError("FOLLOW_RUN_COORDINATOR_READ_FAILED") from exc
        if raw is None or raw == "":
            return None
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "version",
                    "session_id",
                    "run_id",
                    "policy_digest",
                    "configuration_sha256",
                    "state",
                    "updated_at_epoch",
                    "recoverable_reason",
                    "unknown_effect",
                }
                or type(value["version"]) is not int
                or value["version"] != _VERSION
                or not self._digest(value["session_id"])
                or (
                    value["run_id"] is not None
                    and not self._digest(value["run_id"])
                )
                or not self._digest(value["policy_digest"])
                or not self._digest(value["configuration_sha256"])
                or type(value["state"]) is not str
                or value["state"] not in _STATES
                or type(value["updated_at_epoch"]) is not int
                or value["updated_at_epoch"] < 0
                or (
                    value["recoverable_reason"] is not None
                    and (
                        type(value["recoverable_reason"]) is not str
                        or re.fullmatch(
                            r"[A-Z][A-Z0-9_]{0,63}", value["recoverable_reason"]
                        )
                        is None
                    )
                )
                or type(value["unknown_effect"]) is not bool
                or (
                    value["state"] in {"recoverable_error", "stopped"}
                    and value["recoverable_reason"] is None
                )
                or (
                    value["state"] not in {"recoverable_error", "stopped"}
                    and value["recoverable_reason"] is not None
                )
                or (
                    value["unknown_effect"]
                    and not (
                        value["state"] in {"recoverable_error", "stopped"}
                        and value["recoverable_reason"] == "UNKNOWN_EFFECT"
                    )
                )
            ):
                raise ValueError("invalid coordinator record")
            return value
        except Exception as exc:
            raise ValueError("FOLLOW_RUN_COORDINATOR_STATE_INVALID") from exc

    def _write(self, state: dict) -> dict:
        import database

        serialized = json.dumps(
            state, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if database.set_setting(self.SETTING_KEY, serialized) is not True:
            raise ValueError("FOLLOW_RUN_COORDINATOR_PERSIST_FAILED")
        return dict(state)

    @staticmethod
    def _digest(value: object) -> bool:
        return type(value) is str and _RUN_ID_RE.fullmatch(value) is not None

    @staticmethod
    def _now(now_epoch: int | None) -> int:
        now = int(time.time()) if now_epoch is None else now_epoch
        if type(now) is not int or now < 0:
            raise ValueError("FOLLOW_RUN_COORDINATOR_TIME_INVALID")
        return now

    def begin_run(
        self,
        *,
        policy_digest: str,
        configuration_sha256: str,
        now_epoch: int | None = None,
    ) -> dict:
        """Create/reuse a session before the authority service creates run_id."""
        if not self._digest(policy_digest) or not self._digest(configuration_sha256):
            raise ValueError("FOLLOW_RUN_AUTHORITY_INVALID")
        now = self._now(now_epoch)
        import database

        with _LOCK:
            current = self._read()
            if current is not None and current["state"] != "stopped":
                if (
                    current["policy_digest"] != policy_digest
                    or current["configuration_sha256"] != configuration_sha256
                ):
                    raise ValueError("FOLLOW_RUN_AUTHORITY_CHANGED")
            active_policy = database.get_active_follow_run_policy()
            if active_policy is None or active_policy.digest != policy_digest:
                raise ValueError("FOLLOW_RUN_POLICY_NOT_APPROVED")
            if current is not None and current["state"] != "stopped":
                return current
            return self._write(
                {
                    "version": _VERSION,
                    "session_id": secrets.token_hex(32),
                    "run_id": None,
                    "policy_digest": policy_digest,
                    "configuration_sha256": configuration_sha256,
                    "state": "prep_pending",
                    "updated_at_epoch": now,
                    "recoverable_reason": None,
                    "unknown_effect": False,
                }
            )

    def get_state(self) -> dict | None:
        """Read current orchestration state, failing closed if malformed."""
        with _LOCK:
            current = self._read()
            return dict(current) if current is not None else None

    def read_state(self) -> dict | None:
        """Stable name for integration callers reading the active run record."""
        return self.get_state()

    def _bound(self, session_id: str, policy_digest: str, configuration_sha256: str):
        current = self._read()
        if current is None or current["session_id"] != session_id:
            raise ValueError("FOLLOW_RUN_SESSION_REQUIRED")
        if (
            current["policy_digest"] != policy_digest
            or current["configuration_sha256"] != configuration_sha256
        ):
            raise ValueError("FOLLOW_RUN_AUTHORITY_CHANGED")
        import database

        active_policy = database.get_active_follow_run_policy()
        if active_policy is None or active_policy.digest != policy_digest:
            raise ValueError("FOLLOW_RUN_POLICY_NOT_APPROVED")
        return current

    @staticmethod
    def _verify_authority(
        *, run_id: str, policy_digest: str, configuration_sha256: str, now_epoch: int
    ) -> None:
        import database

        try:
            policy = database.get_active_follow_run_policy()
            identity = database.get_follow_run_identity(run_id)
            authority = database.get_follow_creation_authority(
                identity=identity,
                configuration_sha256=configuration_sha256,
                now_epoch=now_epoch,
            )
        except Exception as exc:
            raise ValueError("FOLLOW_RUN_AUTHORITY_PROOF_INVALID") from exc
        if (
            policy is None
            or policy.digest != policy_digest
            or type(identity) is not dict
            or identity.get("network") != policy.network
            or str(identity.get("wallet_fingerprint")) != policy.wallet_fingerprint
            or identity.get("asset_id") != policy.asset_id
            or authority.get("ready") is not True
            or authority.get("run_id") != run_id
            or authority.get("identity") != identity
            or authority.get("configuration_sha256") != configuration_sha256
            or authority.get("buy_limit") != policy.buy_target
            or authority.get("sell_limit") != policy.sell_target
        ):
            raise ValueError("FOLLOW_RUN_AUTHORITY_PROOF_INVALID")

    def _transition(
        self,
        *,
        session_id: str,
        policy_digest: str,
        configuration_sha256: str,
        target: str,
        allowed_from: set[str],
        now_epoch: int | None,
        recoverable_reason: str | None = None,
        unknown_effect: bool | None = None,
        resolve_unknown_effect: bool = False,
    ) -> dict:
        now = self._now(now_epoch)
        with _LOCK:
            current = self._bound(session_id, policy_digest, configuration_sha256)
            if current["state"] == target:
                desired_unknown = (
                    current["unknown_effect"]
                    if unknown_effect is None
                    else unknown_effect
                )
                if (
                    current["recoverable_reason"] == recoverable_reason
                    and current["unknown_effect"] == desired_unknown
                ):
                    return current
            if current["unknown_effect"] and not resolve_unknown_effect:
                raise ValueError("UNKNOWN_EFFECT_RECONCILIATION_REQUIRED")
            if current["state"] not in allowed_from:
                raise ValueError("FOLLOW_RUN_TRANSITION_INVALID")
            updated = {
                **current,
                "state": target,
                "updated_at_epoch": now,
                "recoverable_reason": recoverable_reason,
                "unknown_effect": (
                    current["unknown_effect"]
                    if unknown_effect is None
                    else unknown_effect
                ),
            }
            return self._write(updated)

    def bind_authority(
        self,
        *,
        session_id: str,
        run_id: str,
        policy_digest: str,
        configuration_sha256: str,
        now_epoch: int | None = None,
    ) -> dict:
        """Attach the real run_id returned by the durable authority service."""
        if not self._digest(run_id):
            raise ValueError("FOLLOW_RUN_AUTHORITY_INVALID")
        now = self._now(now_epoch)
        with _LOCK:
            current = self._bound(session_id, policy_digest, configuration_sha256)
            if current["run_id"] is not None:
                if current["run_id"] == run_id:
                    return current
                raise ValueError("FOLLOW_RUN_AUTHORITY_CHANGED")
            if current["state"] not in {"ready", "start_pending"}:
                raise ValueError("FOLLOW_RUN_TRANSITION_INVALID")
            self._verify_authority(
                run_id=run_id,
                policy_digest=policy_digest,
                configuration_sha256=configuration_sha256,
                now_epoch=now,
            )
            return self._write({**current, "run_id": run_id, "updated_at_epoch": now})

    def stop_run(
        self,
        *,
        session_id: str,
        policy_digest: str,
        configuration_sha256: str,
        now_epoch: int | None = None,
    ) -> dict:
        """Durably disable run resumption without cancelling live offers."""
        now = self._now(now_epoch)
        import database

        with _LOCK:
            current = self._read()
            if current is None or current["session_id"] != session_id:
                raise ValueError("FOLLOW_RUN_SESSION_REQUIRED")
            if (
                current["policy_digest"] != policy_digest
                or current["configuration_sha256"] != configuration_sha256
            ):
                raise ValueError("FOLLOW_RUN_AUTHORITY_CHANGED")
            if current["state"] == "stopped":
                return current
            try:
                if current["run_id"] is not None:
                    database.stop_follow_run_authority(
                        run_id=current["run_id"], stopped_at_epoch=now
                    )
                from follow_restart_intent import clear_follow_restart_intent

                clear_follow_restart_intent(reason="manual_stop", now_epoch=now)
                cleared = database.clear_active_follow_run_policy()
            except Exception as exc:
                raise ValueError("FOLLOW_RUN_STOP_PERSIST_FAILED") from exc
            if cleared is not True:
                raise ValueError("FOLLOW_RUN_STOP_PERSIST_FAILED")
            reason = "UNKNOWN_EFFECT" if current["unknown_effect"] else "MANUAL_STOP"
            return self._write(
                {
                    **current,
                    "state": "stopped",
                    "updated_at_epoch": now,
                    "recoverable_reason": reason,
                }
            )

    def mark_preparing(self, *, session_id, policy_digest, configuration_sha256, now_epoch=None):
        return self._transition(
            session_id=session_id,
            policy_digest=policy_digest,
            configuration_sha256=configuration_sha256,
            target="preparing",
            allowed_from={"prep_pending", "preparing", "recoverable_error"},
            now_epoch=now_epoch,
        )

    def reconcile_prep(
        self,
        *,
        session_id: str,
        policy_digest: str,
        configuration_sha256: str,
        effect_status: str,
        prep_complete: bool,
        fee_status: str,
        now_epoch: int | None = None,
    ) -> dict:
        """Advance only from caller-reconciled journal/chain observations."""
        if effect_status not in {"none", "confirmed", "proven_absent", "unknown"}:
            raise ValueError("FOLLOW_RUN_PREP_OBSERVATION_INVALID")
        if type(prep_complete) is not bool or fee_status not in {
            "within_cap",
            "above_cap",
        }:
            raise ValueError("FOLLOW_RUN_PREP_OBSERVATION_INVALID")
        if effect_status == "unknown":
            return self._transition(
                session_id=session_id,
                policy_digest=policy_digest,
                configuration_sha256=configuration_sha256,
                target="recoverable_error",
                allowed_from=_STATES,
                now_epoch=now_epoch,
                recoverable_reason="UNKNOWN_EFFECT",
                unknown_effect=True,
            )
        resolved_unknown = False
        with _LOCK:
            current = self._bound(session_id, policy_digest, configuration_sha256)
            if current["unknown_effect"]:
                # An empty observation is not proof that an ambiguous effect
                # did not land. Recovery needs an authoritative terminal fact.
                if effect_status not in {"confirmed", "proven_absent"}:
                    return current
                resolved_unknown = True
        if fee_status == "above_cap":
            return self._transition(
                session_id=session_id,
                policy_digest=policy_digest,
                configuration_sha256=configuration_sha256,
                target="awaiting_confirmation",
                allowed_from={"prep_pending", "preparing", "awaiting_confirmation", "recoverable_error"},
                now_epoch=now_epoch,
                recoverable_reason=None,
                unknown_effect=False,
                resolve_unknown_effect=resolved_unknown,
            )
        return self._transition(
            session_id=session_id,
            policy_digest=policy_digest,
            configuration_sha256=configuration_sha256,
            target="ready" if prep_complete else "preparing",
            allowed_from={
                "prep_pending",
                "preparing",
                "awaiting_confirmation",
                "recoverable_error",
                "ready",
            },
            now_epoch=now_epoch,
            recoverable_reason=None,
            unknown_effect=False,
            resolve_unknown_effect=resolved_unknown,
        )

    def mark_start_pending(self, *, session_id, policy_digest, configuration_sha256, now_epoch=None):
        now = self._now(now_epoch)
        current = self.get_state()
        if current is None or current["session_id"] != session_id or current["run_id"] is None:
            raise ValueError("FOLLOW_RUN_AUTHORITY_REQUIRED")
        self._verify_authority(
            run_id=current["run_id"],
            policy_digest=policy_digest,
            configuration_sha256=configuration_sha256,
            now_epoch=now,
        )
        return self._transition(
            session_id=session_id,
            policy_digest=policy_digest,
            configuration_sha256=configuration_sha256,
            target="start_pending",
            allowed_from={"ready", "start_pending"},
            now_epoch=now,
        )

    def mark_running(self, *, session_id, policy_digest, configuration_sha256, now_epoch=None):
        now = self._now(now_epoch)
        current = self.get_state()
        if current is None or current["session_id"] != session_id or current["run_id"] is None:
            raise ValueError("FOLLOW_RUN_AUTHORITY_REQUIRED")
        self._verify_authority(
            run_id=current["run_id"],
            policy_digest=policy_digest,
            configuration_sha256=configuration_sha256,
            now_epoch=now,
        )
        return self._transition(
            session_id=session_id,
            policy_digest=policy_digest,
            configuration_sha256=configuration_sha256,
            target="running",
            allowed_from={"start_pending", "running"},
            now_epoch=now,
        )

    def record_recoverable_error(
        self,
        *,
        session_id: str,
        policy_digest: str,
        configuration_sha256: str,
        reason: str,
        unknown_effect: bool = False,
        now_epoch: int | None = None,
    ) -> dict:
        if (
            type(reason) is not str
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", reason)
            or type(unknown_effect) is not bool
        ):
            raise ValueError("FOLLOW_RUN_ERROR_INVALID")
        return self._transition(
            session_id=session_id,
            policy_digest=policy_digest,
            configuration_sha256=configuration_sha256,
            target="recoverable_error",
            allowed_from=_STATES,
            now_epoch=now_epoch,
            recoverable_reason=reason,
            unknown_effect=unknown_effect,
        )
