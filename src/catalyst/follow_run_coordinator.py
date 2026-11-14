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


_VERSION = 3
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
            current_keys = {
                "version",
                "session_id",
                "run_id",
                "policy_digest",
                "configuration_sha256",
                "state",
                "updated_at_epoch",
                "recoverable_reason",
                "unknown_effect",
                "fee_approval_id",
                "fee_approval_session_id",
                "funded_buy_limit",
                "funded_sell_limit",
                "funded_proof_sha256",
                "funded_refresh_proof_sha256",
            }
            v2_keys = current_keys - {"funded_refresh_proof_sha256"}
            v1_keys = v2_keys - {
                "funded_buy_limit",
                "funded_sell_limit",
                "funded_proof_sha256",
            }
            legacy_keys = v1_keys - {
                "fee_approval_id",
                "fee_approval_session_id",
            }
            migrated = (
                type(value) is dict
                and type(value.get("version")) is int
                and value["version"] in {1, 2}
                and frozenset(value)
                in {frozenset(v2_keys), frozenset(v1_keys), frozenset(legacy_keys)}
            )
            if migrated:
                value = {
                    **value,
                    "version": _VERSION,
                    "fee_approval_id": None,
                    "fee_approval_session_id": None,
                    "funded_buy_limit": None,
                    "funded_sell_limit": None,
                    "funded_proof_sha256": None,
                    "funded_refresh_proof_sha256": None,
                }
            if (
                type(value) is not dict
                or set(value) != current_keys
                or type(value["version"]) is not int
                or value["version"] != _VERSION
                or not self._digest(value["session_id"])
                or (value["run_id"] is not None and not self._digest(value["run_id"]))
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
                    value["fee_approval_id"] is not None
                    and not self._digest(value["fee_approval_id"])
                )
                or (
                    value["fee_approval_session_id"] is not None
                    and not self._digest(value["fee_approval_session_id"])
                )
                or (
                    (value["fee_approval_id"] is None)
                    != (value["fee_approval_session_id"] is None)
                )
                or (
                    value["funded_buy_limit"] is not None
                    and (
                        type(value["funded_buy_limit"]) is not int
                        or value["funded_buy_limit"] < 1
                    )
                )
                or (
                    value["funded_sell_limit"] is not None
                    and (
                        type(value["funded_sell_limit"]) is not int
                        or value["funded_sell_limit"] < 1
                    )
                )
                or (
                    (value["funded_buy_limit"] is None)
                    != (value["funded_sell_limit"] is None)
                )
                or (
                    value["funded_proof_sha256"] is not None
                    and not self._digest(value["funded_proof_sha256"])
                )
                or (
                    value["funded_proof_sha256"] is not None
                    and value["funded_buy_limit"] is None
                )
                or (
                    value["funded_refresh_proof_sha256"] is not None
                    and (
                        not self._digest(value["funded_refresh_proof_sha256"])
                        or value["funded_buy_limit"] is None
                    )
                )
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
            if migrated:
                # Older single-approval runs had no partial ceiling field.
                # Preserve their full signed target only when the persisted
                # database authority independently proves that exact target.
                if (
                    value["run_id"] is not None
                    and value["state"] in {"ready", "start_pending", "running"}
                    and value["unknown_effect"] is False
                ):
                    try:
                        import database

                        policy = database.get_active_follow_run_policy()
                        identity = database.get_follow_run_identity(value["run_id"])
                        authority = database.get_follow_creation_authority(
                            identity=identity,
                            configuration_sha256=value["configuration_sha256"],
                            now_epoch=int(time.time()),
                        )
                        if (
                            policy is not None
                            and policy.digest == value["policy_digest"]
                            and type(authority) is dict
                            and authority.get("ready") is True
                            and authority.get("run_id") == value["run_id"]
                            and authority.get("configuration_sha256")
                            == value["configuration_sha256"]
                            and authority.get("buy_limit") == policy.buy_target
                            and authority.get("sell_limit") == policy.sell_target
                            and identity.get("network") == policy.network
                            and str(identity.get("wallet_fingerprint"))
                            == policy.wallet_fingerprint
                            and identity.get("asset_id") == policy.asset_id
                        ):
                            value["funded_buy_limit"] = policy.buy_target
                            value["funded_sell_limit"] = policy.sell_target
                    except Exception:
                        pass
                return self._write(value)
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
                    "fee_approval_id": None,
                    "fee_approval_session_id": None,
                    "funded_buy_limit": None,
                    "funded_sell_limit": None,
                    "funded_proof_sha256": None,
                    "funded_refresh_proof_sha256": None,
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
        funded_buy_limit: int | None = None,
        funded_sell_limit: int | None = None,
        funded_proof_sha256: str | None = None,
        now_epoch: int | None = None,
    ) -> dict:
        """Attach the real run_id returned by the durable authority service."""
        if not self._digest(run_id):
            raise ValueError("FOLLOW_RUN_AUTHORITY_INVALID")
        now = self._now(now_epoch)
        if (funded_buy_limit is None) != (funded_sell_limit is None):
            raise ValueError("FOLLOW_FUNDED_TARGET_BINDING_INVALID")
        if funded_proof_sha256 is not None and not self._digest(funded_proof_sha256):
            raise ValueError("FOLLOW_FUNDED_TARGET_BINDING_INVALID")
        if funded_buy_limit is not None and (
            type(funded_buy_limit) is not int
            or type(funded_sell_limit) is not int
            or funded_buy_limit < 1
            or funded_sell_limit < 1
        ):
            raise ValueError("FOLLOW_FUNDED_TARGET_BINDING_INVALID")
        with _LOCK:
            current = self._bound(session_id, policy_digest, configuration_sha256)
            if current["run_id"] is not None:
                if current["run_id"] == run_id and (
                    funded_buy_limit is None
                    or (
                        current.get("funded_buy_limit") == funded_buy_limit
                        and current.get("funded_sell_limit") == funded_sell_limit
                        and current.get("funded_proof_sha256") == funded_proof_sha256
                    )
                ):
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
            import database

            policy = database.get_active_follow_run_policy()
            if funded_buy_limit is None:
                funded_buy_limit = getattr(policy, "buy_target", None)
                funded_sell_limit = getattr(policy, "sell_target", None)
            if (
                type(funded_buy_limit) is not int
                or type(funded_sell_limit) is not int
                or not 1 <= funded_buy_limit <= getattr(policy, "buy_target", 0)
                or not 1 <= funded_sell_limit <= getattr(policy, "sell_target", 0)
                or (
                    (
                        funded_buy_limit < policy.buy_target
                        or funded_sell_limit < policy.sell_target
                    )
                    and not self._digest(funded_proof_sha256)
                )
            ):
                raise ValueError("FOLLOW_FUNDED_TARGET_BINDING_INVALID")
            return self._write(
                {
                    **current,
                    "run_id": run_id,
                    "funded_buy_limit": funded_buy_limit,
                    "funded_sell_limit": funded_sell_limit,
                    "funded_proof_sha256": funded_proof_sha256,
                    "funded_refresh_proof_sha256": None,
                    "updated_at_epoch": now,
                }
            )

    def refresh_funded_limits(
        self,
        *,
        session_id: str,
        run_id: str,
        policy_digest: str,
        configuration_sha256: str,
        funded_buy_limit: int,
        funded_sell_limit: int,
        proof_sha256: str,
        now_epoch: int | None = None,
    ) -> dict:
        """Raise a running book ceiling from a fresh read-only fit proof."""
        if (
            not self._digest(run_id)
            or not self._digest(proof_sha256)
            or type(funded_buy_limit) is not int
            or type(funded_sell_limit) is not int
            or funded_buy_limit < 1
            or funded_sell_limit < 1
        ):
            raise ValueError("FOLLOW_FUNDED_TARGET_BINDING_INVALID")
        now = self._now(now_epoch)
        import database
        import confidence_override

        with _LOCK:
            current = self._bound(session_id, policy_digest, configuration_sha256)
            if (
                current.get("run_id") != run_id
                or current.get("unknown_effect") is not False
                or current.get("state") not in {"running", "start_pending"}
                or current.get("funded_buy_limit") is None
            ):
                raise ValueError("FOLLOW_FUNDED_TARGET_AUTHORITY_CHANGED")
            policy = database.get_active_follow_run_policy()
            if (
                policy is None
                or policy.digest != policy_digest
                or confidence_override.current_configuration_digest()
                != configuration_sha256
                or funded_buy_limit > policy.buy_target
                or funded_sell_limit > policy.sell_target
                or funded_buy_limit < current["funded_buy_limit"]
                or funded_sell_limit < current["funded_sell_limit"]
            ):
                raise ValueError("FOLLOW_FUNDED_TARGET_AUTHORITY_CHANGED")
            if (
                funded_buy_limit == current["funded_buy_limit"]
                and funded_sell_limit == current["funded_sell_limit"]
                and current.get("funded_refresh_proof_sha256") == proof_sha256
            ):
                return current
            return self._write(
                {
                    **current,
                    "funded_buy_limit": funded_buy_limit,
                    "funded_sell_limit": funded_sell_limit,
                    "funded_refresh_proof_sha256": proof_sha256,
                    "updated_at_epoch": now,
                }
            )

    def bind_prep_approval(
        self,
        *,
        session_id: str,
        policy_digest: str,
        configuration_sha256: str,
        approval_id: str,
        now_epoch: int | None = None,
    ) -> dict:
        """Bind a freshly verified standalone prep fee approval to this run."""
        if not self._digest(approval_id):
            raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_INVALID")
        now = self._now(now_epoch)
        import confidence_override
        import database
        import coin_prep_fee_runtime

        with _LOCK:
            current = self._bound(session_id, policy_digest, configuration_sha256)
            if current["state"] not in {"prep_pending", "preparing"}:
                raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_INVALID")
            if current["unknown_effect"] or current["run_id"] is not None:
                raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_INVALID")
            if (
                current["fee_approval_id"] is not None
                and current["fee_approval_id"] != approval_id
            ):
                raise ValueError("FOLLOW_RUN_PREP_FEE_APPROVAL_CHANGED")

            try:
                active_policy = database.get_active_follow_run_policy()
                configuration = coin_prep_fee_runtime._configuration()
                current_config_sha256 = (
                    confidence_override.current_configuration_digest()
                )
                if (
                    active_policy is None
                    or active_policy.digest != policy_digest
                    or current_config_sha256 != configuration_sha256
                    or confidence_override._configuration_digest(configuration)
                    != configuration_sha256
                    or configuration.get("MAX_ACTIVE_BUY_OFFERS")
                    != active_policy.buy_target
                    or configuration.get("MAX_ACTIVE_SELL_OFFERS")
                    != active_policy.sell_target
                ):
                    raise ValueError("FOLLOW_RUN_AUTHORITY_CHANGED")
                base_identity = coin_prep_fee_runtime._verified_identity(configuration)
                expected_identity = {
                    **base_identity,
                    "asset_id": str(configuration.get("CAT_ASSET_ID") or "")
                    .strip()
                    .lower()
                    .removeprefix("0x"),
                    "wallet_id": configuration.get("CAT_WALLET_ID"),
                    "xch_wallet_id": configuration.get("WALLET_ID_XCH"),
                    "ticker": configuration.get("CAT_TICKER_ID"),
                }
                approved = coin_prep_fee_runtime.read_approved_prep_fee_snapshot(
                    approval_id
                )
            except ValueError as exc:
                reason = str(exc)
                if reason == "FOLLOW_RUN_AUTHORITY_CHANGED":
                    raise
                raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_INVALID") from exc
            except Exception as exc:
                raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_INVALID") from exc

            scope = approved.get("scope") if type(approved) is dict else None
            identity = approved.get("identity") if type(approved) is dict else None
            approval = approved.get("approval") if type(approved) is dict else None
            prep_session_id = scope.get("session_id") if type(scope) is dict else None
            scope_identity = (
                {key: scope.get(key) for key in expected_identity}
                if type(scope) is dict
                else None
            )
            if (
                type(expected_identity) is not dict
                or type(expected_identity.get("wallet_fingerprint")) is not int
                or not self._digest(expected_identity.get("asset_id"))
                or identity != expected_identity
                or scope_identity != expected_identity
                or scope.get("campaign_id") is not None
                or not self._digest(prep_session_id)
                or type(approval) is not dict
                or approval.get("approval_id") != approval_id
                or type(approval.get("unbounded")) is not bool
                or approved.get("recovery_only") is True
                or approved.get("recovery_action") is not None
                or expected_identity.get("network") != active_policy.network
                or str(expected_identity.get("wallet_fingerprint"))
                != active_policy.wallet_fingerprint
                or expected_identity.get("asset_id") != active_policy.asset_id
            ):
                raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_INVALID")

            if current["fee_approval_id"] == approval_id:
                if current["fee_approval_session_id"] != prep_session_id:
                    raise ValueError("FOLLOW_RUN_PREP_FEE_APPROVAL_CHANGED")
                return current
            candidate = {
                **current,
                "fee_approval_id": approval_id,
                "fee_approval_session_id": prep_session_id,
                "updated_at_epoch": now,
            }
            try:
                from follow_prep_fee_authority import verified_prep_fee_cap

                cap = verified_prep_fee_cap(
                    policy=active_policy,
                    coordinator_state=candidate,
                    current_configuration_sha256=configuration_sha256,
                    approved_snapshot=approved,
                    requested_approval_id=approval_id,
                    run_session_id=session_id,
                )
            except Exception as exc:
                raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_INVALID") from exc
            if cap != active_policy.maximum_fee_mojos_per_tx:
                raise ValueError("FOLLOW_RUN_PREP_FEE_BINDING_INVALID")
            return self._write(candidate)

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

    def mark_preparing(
        self, *, session_id, policy_digest, configuration_sha256, now_epoch=None
    ):
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
                allowed_from={
                    "prep_pending",
                    "preparing",
                    "awaiting_confirmation",
                    "recoverable_error",
                },
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

    def mark_start_pending(
        self, *, session_id, policy_digest, configuration_sha256, now_epoch=None
    ):
        now = self._now(now_epoch)
        current = self.get_state()
        if (
            current is None
            or current["session_id"] != session_id
            or current["run_id"] is None
        ):
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

    def mark_running(
        self, *, session_id, policy_digest, configuration_sha256, now_epoch=None
    ):
        now = self._now(now_epoch)
        current = self.get_state()
        if (
            current is None
            or current["session_id"] != session_id
            or current["run_id"] is None
        ):
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
