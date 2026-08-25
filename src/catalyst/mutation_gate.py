"""Fail-closed durable mutation ownership and child-worker delegation.

The SQLite rows owned by :mod:`database` are authoritative.  Process-local
state exists only to stop work immediately after a heartbeat or persistence
failure; every mutation check re-reads the durable latch, journal blockers,
and lease.
"""

from __future__ import annotations

import atexit
import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time
import uuid
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Mapping, Optional

import database

try:
    from super_log import slog
except Exception:  # pragma: no cover - only minimal diagnostic environments

    def slog(*_args, **_kwargs):
        return None


DELEGATION_ID_ENV = "_CATALYST_DELEGATION_ID"
DELEGATION_TOKEN_ENV = "_CATALYST_DELEGATION_TOKEN"
DELEGATION_PARENT_RUN_ENV = "_CATALYST_DELEGATION_PARENT_RUN_ID"
DELEGATION_OPERATION_ENV = "_CATALYST_DELEGATION_OPERATION_ID"
DELEGATION_PURPOSE_ENV = "_CATALYST_DELEGATION_PURPOSE"
DELEGATION_WORKER_ENV = "_CATALYST_DELEGATION_WORKER_ID"
DELEGATION_WALLET_ENV = "_CATALYST_DELEGATION_WALLET_HASH"
DELEGATION_NETWORK_ENV = "_CATALYST_DELEGATION_NETWORK"
DELEGATION_IDENTITY_ENV = "_CATALYST_DELEGATION_IDENTITY"
DELEGATION_IDENTITY_DIGEST_ENV = "_CATALYST_DELEGATION_IDENTITY_DIGEST"
DELEGATION_PARENT_EPOCH_ENV = "_CATALYST_DELEGATION_PARENT_EPOCH"

_DELEGATION_ENV_NAMES = (
    DELEGATION_ID_ENV,
    DELEGATION_TOKEN_ENV,
    DELEGATION_PARENT_RUN_ENV,
    DELEGATION_OPERATION_ENV,
    DELEGATION_PURPOSE_ENV,
    DELEGATION_WORKER_ENV,
    DELEGATION_WALLET_ENV,
    DELEGATION_NETWORK_ENV,
    DELEGATION_IDENTITY_ENV,
    DELEGATION_IDENTITY_DIGEST_ENV,
    DELEGATION_PARENT_EPOCH_ENV,
)

_ALLOWED_REASON_CODES = frozenset(
    {
        "CANCEL_UNKNOWN",
        "CREATE_UNKNOWN",
        "DURABLE_STATE_UNAVAILABLE",
        "HEARTBEAT_FAILED",
        "LATCH_BINDING_MISMATCH",
        "LEASE_EXPIRED",
        "LEASE_LOST",
        "LEASE_OWNED_BY_OTHER",
        "LEASE_UNAVAILABLE",
        "MUTATION_GATE_SAFETY_STOP",
        "MUTATION_RUNTIME_NOT_INITIALIZED",
        "MUTATION_SHUTTING_DOWN",
        "OPERATION_UNKNOWN",
        "RECONCILIATION_REQUIRED",
        "RUNTIME_DISCONTINUITY",
        "UNRESOLVED_OPERATIONS",
        "WORKER_DELEGATION_INVALID",
        "WORKER_PARENT_LEASE_INVALID",
        "WALLET_BACKEND_UNSUPPORTED",
        "WALLET_IDENTITY_BINDING_INVALID",
        "WALLET_IDENTITY_MALFORMED",
        "WALLET_IDENTITY_MISMATCH",
        "WALLET_IDENTITY_NON_SIGNING",
        "WALLET_IDENTITY_STALE",
        "WALLET_IDENTITY_UNAVAILABLE",
        "WALLET_MUTATION_FAILED",
    }
)

_REASON_DESCRIPTIONS = {
    "CANCEL_UNKNOWN": "Cancellation outcome requires reconciliation",
    "CREATE_UNKNOWN": "Creation outcome requires reconciliation",
    "DURABLE_STATE_UNAVAILABLE": "Durable mutation state is unavailable",
    "HEARTBEAT_FAILED": "Mutation lease heartbeat failed",
    "LATCH_BINDING_MISMATCH": "Safety latch binding does not match this run",
    "LEASE_EXPIRED": "Mutation lease expired",
    "LEASE_LOST": "Mutation lease ownership changed",
    "LEASE_OWNED_BY_OTHER": "Another CATalyst run owns mutation",
    "LEASE_UNAVAILABLE": "No active mutation lease is owned by this run",
    "MUTATION_GATE_SAFETY_STOP": "Mutation stopped by the safety gate",
    "MUTATION_RUNTIME_NOT_INITIALIZED": "Mutation runtime is not initialized",
    "MUTATION_SHUTTING_DOWN": "Mutation runtime is shutting down",
    "OPERATION_UNKNOWN": "Operation outcome requires reconciliation",
    "RECONCILIATION_REQUIRED": "Authoritative reconciliation is required",
    "RUNTIME_DISCONTINUITY": "Runtime clock discontinuity requires recovery",
    "UNRESOLVED_OPERATIONS": "Unresolved operation journal entries block mutation",
    "WORKER_DELEGATION_INVALID": "Worker mutation delegation is invalid",
    "WORKER_PARENT_LEASE_INVALID": "Worker parent lease is no longer valid",
    "WALLET_BACKEND_UNSUPPORTED": "Wallet backend cannot prove mutation identity",
    "WALLET_IDENTITY_BINDING_INVALID": "Expected wallet identity binding is invalid",
    "WALLET_IDENTITY_MALFORMED": "Wallet returned malformed identity evidence",
    "WALLET_IDENTITY_MISMATCH": "Active wallet identity does not match the expected binding",
    "WALLET_IDENTITY_NON_SIGNING": "Active wallet cannot sign mutations",
    "WALLET_IDENTITY_STALE": "Wallet identity evidence is stale or replayed",
    "WALLET_IDENTITY_UNAVAILABLE": "Fresh wallet identity is unavailable",
    "WALLET_MUTATION_FAILED": "Wallet mutation failed after authorization",
}

_TERMINAL_PROCESS_FENCES = frozenset(
    {
        "DURABLE_STATE_UNAVAILABLE",
        "HEARTBEAT_FAILED",
        "LEASE_EXPIRED",
        "LEASE_LOST",
    }
)


class MutationBlocked(RuntimeError):
    """Raised immediately before a mutation that is not durably authorized."""

    def __init__(self, reason_code: str, operation: str = "mutation"):
        self.reason_code = _safe_reason_code(reason_code)
        self.operation = _safe_operation(operation)
        super().__init__(f"{self.reason_code}:{self.operation}")


@dataclass(frozen=True)
class GateStatus:
    allowed: bool
    reason_code: str
    source: str
    latch_generation: int = 0
    blocking_operation_ids: tuple[str, ...] = ()
    lease_active: bool = False
    lease_version: int = 0
    lease_expires_at: Optional[str] = None
    owner_run_id: Optional[str] = None
    owner_pid: Optional[int] = None
    owner_is_this_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        visible_blockers = self.blocking_operation_ids[:32]
        return {
            "allowed": bool(self.allowed),
            "reason_code": self.reason_code,
            "source": self.source,
            "latch_generation": int(self.latch_generation),
            "blocking_operation_ids": list(visible_blockers),
            "blocking_operation_count": len(self.blocking_operation_ids),
            "lease": {
                "active": bool(self.lease_active),
                "version": int(self.lease_version),
                "expires_at": self.lease_expires_at,
                "owner_run_id": self.owner_run_id,
                "owner_pid": self.owner_pid,
                "owned_by_this_run": bool(self.owner_is_this_run),
            },
        }


def _strict_utc_timestamp(value: Any, name: str) -> tuple[datetime, str]:
    """Parse the canonical Task-1 identity timestamp without local ambiguity."""

    if type(value) is not str or not value.endswith("Z"):
        raise ValueError(f"{name} must be a canonical UTC timestamp")
    parsed = _as_utc(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    return parsed, _timestamp(parsed)


def wallet_fingerprint_hash(fingerprint: Any) -> str:
    """Return the exact stable lease binding for a wallet fingerprint."""

    if type(fingerprint) is not int or fingerprint < 1:
        raise ValueError("fingerprint must be a positive exact integer")
    return hashlib.sha256(f"fingerprint:{fingerprint}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WalletIdentityBinding:
    """Exact expected wallet identity and freshness contract for mutations."""

    backend: str
    fingerprint: int
    network_id: str
    kind: str
    has_secrets: bool
    bound_at_utc: str
    name: str = ""
    maximum_age_seconds: int = 10

    def __post_init__(self) -> None:
        backend = _exact_text(self.backend, "backend", max_length=16).lower()
        network = _exact_text(self.network_id, "network_id", max_length=64).lower()
        kind = _exact_text(self.kind, "kind", max_length=64).lower()
        if type(self.fingerprint) is not int or self.fingerprint < 1:
            raise ValueError("fingerprint must be a positive exact integer")
        if self.has_secrets is not True:
            raise ValueError("mutation binding must require signing capability")
        name = _exact_text(self.name, "name", max_length=128)
        object.__setattr__(self, "name", name)
        if type(self.maximum_age_seconds) is not int or not (
            1 <= self.maximum_age_seconds <= 300
        ):
            raise ValueError("maximum_age_seconds is invalid")
        _, bound_timestamp = _strict_utc_timestamp(self.bound_at_utc, "bound_at_utc")
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "network_id", network)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "bound_at_utc", bound_timestamp)


def wallet_identity_binding_payload(binding: Any) -> dict[str, Any]:
    """Return the complete canonical non-secret mutation identity authority."""

    if type(binding) is not WalletIdentityBinding:
        raise ValueError("wallet identity binding must have the exact type")
    return {
        "backend": binding.backend,
        "name": binding.name,
        "fingerprint": binding.fingerprint,
        "network_id": binding.network_id,
        "kind": binding.kind,
        "has_secrets": binding.has_secrets,
        "bound_at_utc": binding.bound_at_utc,
        "maximum_age_seconds": binding.maximum_age_seconds,
    }


def wallet_identity_binding_digest(binding: Any) -> str:
    """Authenticate every field in a complete wallet identity authority."""

    encoded = json.dumps(
        wallet_identity_binding_payload(binding),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class _OwnerIdentityAuthority:
    """Process-private immutable copy of an owner's acquired identity authority."""

    binding: Optional[WalletIdentityBinding]
    binding_digest: Optional[str]
    wallet_fingerprint_hash: str
    network: str
    backend: Optional[str]
    wallet_adapter_authority: Any
    generation_digest: str


_owner_identity_authorities_lock = threading.RLock()
_owner_identity_authorities: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _new_authority_generation_digest() -> str:
    """Return a non-revivable journal identity for one process-local generation."""

    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def _registered_owner_identity_authority(
    owner: Any,
) -> Optional[_OwnerIdentityAuthority]:
    with _owner_identity_authorities_lock:
        return _owner_identity_authorities.get(owner)


def _rotate_owner_identity_authority(owner: Any) -> bool:
    """Install a fresh opaque authority generation after lease acquisition."""

    with _owner_identity_authorities_lock:
        authority = _owner_identity_authorities.get(owner)
        if type(authority) is not _OwnerIdentityAuthority:
            return False
        _owner_identity_authorities[owner] = _OwnerIdentityAuthority(
            binding=authority.binding,
            binding_digest=authority.binding_digest,
            wallet_fingerprint_hash=authority.wallet_fingerprint_hash,
            network=authority.network,
            backend=authority.backend,
            wallet_adapter_authority=authority.wallet_adapter_authority,
            generation_digest=_new_authority_generation_digest(),
        )
        return True


def _binding_wallet_hash(binding: WalletIdentityBinding) -> str:
    return wallet_fingerprint_hash(binding.fingerprint)


def _wallet_identity_payload_text(
    binding: Optional[WalletIdentityBinding],
) -> str:
    payload = wallet_identity_binding_payload(binding) if binding is not None else {}
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _wallet_identity_from_payload_text(
    payload_text: Any,
) -> Optional[WalletIdentityBinding]:
    text = _exact_text(payload_text, "wallet_identity_payload", max_length=2048)
    payload = json.loads(text)
    if type(payload) is not dict:
        raise ValueError("wallet identity payload must be an exact object")
    if payload == {}:
        if text != "{}":
            raise ValueError("empty wallet identity payload is not canonical")
        return None
    expected_keys = {
        "backend",
        "name",
        "fingerprint",
        "network_id",
        "kind",
        "has_secrets",
        "bound_at_utc",
        "maximum_age_seconds",
    }
    if set(payload) != expected_keys:
        raise ValueError("wallet identity payload fields are invalid")
    binding = WalletIdentityBinding(**payload)
    if text != _wallet_identity_payload_text(binding):
        raise ValueError("wallet identity payload is not canonical")
    return binding


def validate_wallet_identity(
    binding: Any,
    snapshot: Any,
    *,
    now: Optional[datetime] = None,
    last_observed_at_utc: Optional[str] = None,
) -> dict[str, Any]:
    """Pure, total fail-closed check over one uncached identity observation."""

    if type(binding) is not WalletIdentityBinding:
        return {"allowed": False, "reason": "WALLET_IDENTITY_BINDING_INVALID"}
    if binding.backend not in {"sage", "chia"}:
        return {"allowed": False, "reason": "WALLET_BACKEND_UNSUPPORTED"}
    if type(snapshot) is not dict:
        return {"allowed": False, "reason": "WALLET_IDENTITY_MALFORMED"}
    try:
        success = snapshot.get("success")
        if success is False:
            return {"allowed": False, "reason": "WALLET_IDENTITY_UNAVAILABLE"}
        if success is not True:
            return {"allowed": False, "reason": "WALLET_IDENTITY_MALFORMED"}

        backend = snapshot.get("backend")
        fingerprint = snapshot.get("fingerprint")
        network = snapshot.get("network_id")
        kind = snapshot.get("kind")
        signing = snapshot.get("has_secrets")
        name = snapshot.get("name")
        observed_raw = snapshot.get("observed_at_utc")
        if (
            binding.backend == "chia"
            and backend == "chia"
            and (network is None or kind is None or signing is None)
        ):
            return {"allowed": False, "reason": "WALLET_BACKEND_UNSUPPORTED"}
        if (
            type(backend) is not str
            or type(fingerprint) is not int
            or fingerprint < 1
            or type(network) is not str
            or type(kind) is not str
            or type(signing) is not bool
            or (name is not None and type(name) is not str)
        ):
            return {"allowed": False, "reason": "WALLET_IDENTITY_MALFORMED"}
        observed, observed_text = _strict_utc_timestamp(observed_raw, "observed_at_utc")
        current = _as_utc(now or _utc_now())
        bound_at = _as_utc(binding.bound_at_utc)
        previous = (
            _strict_utc_timestamp(last_observed_at_utc, "last_observed_at_utc")[0]
            if last_observed_at_utc is not None
            else bound_at
        )
    except Exception:
        return {"allowed": False, "reason": "WALLET_IDENTITY_MALFORMED"}

    if signing is not True:
        return {"allowed": False, "reason": "WALLET_IDENTITY_NON_SIGNING"}
    if (
        backend != binding.backend
        or fingerprint != binding.fingerprint
        or network.lower() != binding.network_id
        or kind.lower() != binding.kind
        or name != binding.name
    ):
        return {"allowed": False, "reason": "WALLET_IDENTITY_MISMATCH"}
    age = (current - observed).total_seconds()
    if age < 0 or age > binding.maximum_age_seconds or observed <= previous:
        return {"allowed": False, "reason": "WALLET_IDENTITY_STALE"}
    return {
        "allowed": True,
        "reason": "identity_verified",
        "observed_at_utc": observed_text,
    }


class WorkerDelegation:
    """Opaque child handoff whose raw token has no generic serializer."""

    __slots__ = (
        "delegation_id",
        "parent_run_id",
        "operation_id",
        "purpose",
        "worker_id",
        "wallet_fingerprint_hash",
        "network",
        "wallet_identity_payload",
        "wallet_identity_digest",
        "parent_lease_epoch",
        "expires_at",
        "_raw_token",
    )

    def __init__(
        self,
        *,
        delegation_id: str,
        parent_run_id: str,
        operation_id: str,
        purpose: str,
        worker_id: str,
        wallet_fingerprint_hash: str,
        network: str,
        wallet_identity_payload: str,
        wallet_identity_digest: str,
        parent_lease_epoch: str,
        expires_at: str,
        _raw_token: str,
    ):
        object.__setattr__(self, "delegation_id", delegation_id)
        object.__setattr__(self, "parent_run_id", parent_run_id)
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "worker_id", worker_id)
        object.__setattr__(self, "wallet_fingerprint_hash", wallet_fingerprint_hash)
        object.__setattr__(self, "network", network)
        object.__setattr__(self, "wallet_identity_payload", wallet_identity_payload)
        object.__setattr__(self, "wallet_identity_digest", wallet_identity_digest)
        object.__setattr__(self, "parent_lease_epoch", parent_lease_epoch)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "_raw_token", _raw_token)

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("WorkerDelegation is immutable")

    def __repr__(self) -> str:
        return f"WorkerDelegation({self.public_dict()!r})"

    def __reduce_ex__(self, _protocol: int):
        raise TypeError(
            "WorkerDelegation can only be handed off through to_environment()"
        )

    def __getstate__(self):
        raise TypeError(
            "WorkerDelegation can only be handed off through to_environment()"
        )

    def public_dict(self) -> dict[str, str]:
        return {
            "delegation_id": self.delegation_id,
            "parent_run_id": self.parent_run_id,
            "operation_id": self.operation_id,
            "purpose": self.purpose,
            "worker_id": self.worker_id,
            "wallet_fingerprint_hash": self.wallet_fingerprint_hash,
            "network": self.network,
            "wallet_identity_digest": self.wallet_identity_digest,
            "parent_lease_epoch": self.parent_lease_epoch,
            "expires_at": self.expires_at,
        }

    def to_environment(self) -> dict[str, str]:
        """Return the sole supported raw-token handoff channel."""

        return {
            DELEGATION_ID_ENV: self.delegation_id,
            DELEGATION_TOKEN_ENV: self._raw_token,
            DELEGATION_PARENT_RUN_ENV: self.parent_run_id,
            DELEGATION_OPERATION_ENV: self.operation_id,
            DELEGATION_PURPOSE_ENV: self.purpose,
            DELEGATION_WORKER_ENV: self.worker_id,
            DELEGATION_WALLET_ENV: self.wallet_fingerprint_hash,
            DELEGATION_NETWORK_ENV: self.network,
            DELEGATION_IDENTITY_ENV: self.wallet_identity_payload,
            DELEGATION_IDENTITY_DIGEST_ENV: self.wallet_identity_digest,
            DELEGATION_PARENT_EPOCH_ENV: self.parent_lease_epoch,
        }


def _exact_text(value: Any, name: str, *, max_length: int = 256) -> str:
    if type(value) is not str:
        raise ValueError(f"{name} must be an exact string")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise ValueError(f"{name} is invalid")
    return normalized


def _exact_positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _safe_reason_code(reason: Any) -> str:
    if type(reason) is not str:
        return "MUTATION_GATE_SAFETY_STOP"
    normalized = reason.strip().upper()
    if normalized not in _ALLOWED_REASON_CODES:
        return "MUTATION_GATE_SAFETY_STOP"
    return normalized


def _safe_operation(operation: Any) -> str:
    if type(operation) is not str:
        return "mutation"
    value = operation.strip()
    if not value or len(value) > 128:
        return "mutation"
    return "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in value)


def _is_exact_prepared_operation_blocker(
    unresolved: Any,
    *,
    operation: str,
    operation_id: str,
    intent_id: str,
) -> bool:
    if type(unresolved) is not list or not unresolved:
        return False
    try:
        blockers = [
            database.validate_offer_operation_event(blocker) for blocker in unresolved
        ]
    except (TypeError, ValueError):
        return False
    base_operation = next(
        (
            candidate
            for candidate in ("wallet:create_offer", "wallet:cancel_offer")
            if operation == candidate or operation.startswith(f"{candidate}:")
        ),
        None,
    )
    expected_by_operation = {
        "wallet:create_offer": ("CREATE", "INTENT_PREPARED"),
        "wallet:cancel_offer": ("CANCEL", "CANCEL_PREPARED"),
    }
    expected = expected_by_operation.get(base_operation)
    if expected is None:
        return False
    operation_type, reason_code = expected
    own_blockers = [
        blocker
        for blocker in blockers
        if blocker["operation_id"] == operation_id and blocker["intent_id"] == intent_id
    ]
    if len(own_blockers) != 1:
        return False
    blocker = own_blockers[0]
    expected_attempt = blocker["attempt"] if operation_type == "CANCEL" else 1
    exact_own_blocker = {
        "event_id": blocker["event_id"],
        "operation_id": blocker["operation_id"],
        "intent_id": blocker["intent_id"],
        "operation_type": blocker["operation_type"],
        "attempt": blocker["attempt"],
        "phase": blocker["phase"],
        "outcome": blocker["outcome"],
        "transaction_id": blocker["transaction_id"],
        "spend_identity": blocker["spend_identity"],
        "reason_code": blocker["reason_code"],
        "blocks_mutation": blocker["blocks_mutation"],
        "timestamps_match": blocker["request_timestamp"] == blocker["created_at"],
    } == {
        "event_id": (
            f"{operation_id}:attempt:{expected_attempt}:prepared"
            if operation_type == "CANCEL"
            else blocker["event_id"]
        ),
        "operation_id": operation_id,
        "intent_id": intent_id,
        "operation_type": operation_type,
        "attempt": expected_attempt,
        "phase": "PREPARED",
        "outcome": "PREPARED",
        "transaction_id": None,
        "spend_identity": None,
        "reason_code": reason_code,
        "blocks_mutation": 1,
        "timestamps_match": True,
    }
    if not exact_own_blocker:
        return False
    if len(blockers) == 1:
        if operation_type != "CANCEL":
            return True
        try:
            single_evidence = json.loads(blocker["evidence_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return True
        if (
            type(single_evidence) is not dict
            or "effect_claim_protocol" not in single_evidence
        ):
            return True
        if "cohort_size" not in single_evidence:
            required_single_evidence_keys = {
                "trade_id",
                "intent_id",
                "operation_id",
                "attempt",
                "cohort_id",
                "member_id",
                "reason",
                "continuation_journal_sha256",
                "wallet_effect",
                "effect_claim_protocol",
            }
            if frozenset(single_evidence) not in {
                frozenset(required_single_evidence_keys),
                frozenset(required_single_evidence_keys | {"prior_lifecycle_state"}),
            }:
                return False
            try:
                trade_id = single_evidence["trade_id"]
                attempt = single_evidence["attempt"]
                cohort_id = single_evidence["cohort_id"]
                reason = single_evidence["reason"]
                continuation_digest = single_evidence[
                    "continuation_journal_sha256"
                ]
                wallet_identity = json.loads(blocker["wallet_identity_json"])
                if (
                    type(trade_id) is not str
                    or len(trade_id) != 64
                    or trade_id.lower() != trade_id
                    or type(attempt) is not int
                    or isinstance(attempt, bool)
                    or attempt < 1
                    or single_evidence["intent_id"] != intent_id
                    or single_evidence["operation_id"] != operation_id
                    or operation_id != f"cancel:{trade_id}"
                    or blocker["attempt"] != attempt
                    or type(reason) is not str
                    or not 1 <= len(reason) <= 128
                    or type(continuation_digest) is not str
                    or len(continuation_digest) != 64
                    or continuation_digest.lower() != continuation_digest
                    or type(wallet_identity) is not dict
                    or wallet_identity.get("snapshot_sha256")
                    != continuation_digest
                    or single_evidence["effect_claim_protocol"]
                    != "durable_cohort_claim_v1"
                    or single_evidence["wallet_effect"]
                    != {"secure": True, "timeout": 60, "fee_mojos": None}
                    or (
                        "prior_lifecycle_state" in single_evidence
                        and (
                            type(single_evidence["prior_lifecycle_state"]) is not str
                            or not single_evidence["prior_lifecycle_state"]
                            or single_evidence["prior_lifecycle_state"]
                            in {"cancel_requested", "cancel_sent", "mempool_observed"}
                        )
                    )
                ):
                    return False
                bytes.fromhex(trade_id)
                bytes.fromhex(continuation_digest)
                expected_cohort_id = (
                    "cancel-cohort:"
                    + hashlib.sha256(
                        json.dumps(
                            [trade_id], sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")
                    ).hexdigest()
                )
                expected_member_id = (
                    "cancel-member:"
                    + hashlib.sha256(
                        json.dumps(
                            {
                                "attempt": attempt,
                                "cohort_id": expected_cohort_id,
                                "operation_id": operation_id,
                                "trade_id": trade_id,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                )
                if (
                    cohort_id != expected_cohort_id
                    or single_evidence["member_id"] != expected_member_id
                ):
                    return False
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                return False
            return (
                database.get_offer_cancel_effect_claim(
                    operation_id=operation_id,
                    attempt=attempt,
                )
                is not None
            )
    if operation_type != "CANCEL":
        return False

    required_evidence_keys = {
        "trade_id",
        "intent_id",
        "operation_id",
        "attempt",
        "cohort_id",
        "cohort_size",
        "member_id",
        "reason",
        "continuation_journal_sha256",
        "wallet_effect",
        "effect_claim_protocol",
    }

    def cohort_member(event: dict) -> Optional[dict]:
        try:
            evidence = json.loads(event["evidence_json"])
            if type(evidence) is not dict or frozenset(evidence) not in {
                frozenset(required_evidence_keys),
                frozenset(required_evidence_keys | {"prior_lifecycle_state"}),
            }:
                return None
            trade_id = evidence["trade_id"]
            attempt = evidence["attempt"]
            cohort_id = evidence["cohort_id"]
            cohort_size = evidence["cohort_size"]
            if (
                type(trade_id) is not str
                or len(trade_id) != 64
                or trade_id.lower() != trade_id
                or type(attempt) is not int
                or isinstance(attempt, bool)
                or attempt < 1
                or type(cohort_size) is not int
                or isinstance(cohort_size, bool)
                or cohort_size < 2
                or evidence["operation_id"] != event["operation_id"]
                or evidence["intent_id"] != event["intent_id"]
                or event["operation_id"] != f"cancel:{trade_id}"
                or event["event_id"]
                != f"{event['operation_id']}:attempt:{attempt}:prepared"
                or event["attempt"] != attempt
                or event["operation_type"] != "CANCEL"
                or event["phase"] != "PREPARED"
                or event["outcome"] != "PREPARED"
                or event["reason_code"] != "CANCEL_PREPARED"
                or event["blocks_mutation"] != 1
                or event["transaction_id"] is not None
                or event["spend_identity"] is not None
                or event["request_timestamp"] != event["created_at"]
                or evidence["effect_claim_protocol"] != "durable_cohort_claim_v1"
                or evidence["wallet_effect"]
                != {"secure": True, "timeout": 60, "fee_mojos": None}
            ):
                return None
            bytes.fromhex(trade_id)
            expected_member_id = (
                "cancel-member:"
                + hashlib.sha256(
                    json.dumps(
                        {
                            "attempt": attempt,
                            "cohort_id": cohort_id,
                            "operation_id": event["operation_id"],
                            "trade_id": trade_id,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            )
            if evidence["member_id"] != expected_member_id:
                return None
            return {
                "trade_id": trade_id,
                "attempt": attempt,
                "cohort_id": cohort_id,
                "cohort_size": cohort_size,
                "operation_id": event["operation_id"],
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    contexts = [cohort_member(blocker) for blocker in blockers]
    if any(context is None for context in contexts):
        return False
    own_context = cohort_member(blocker)
    if own_context is None:
        return False
    cohort_id = own_context["cohort_id"]
    cohort_size = own_context["cohort_size"]
    if any(
        context["cohort_id"] != cohort_id or context["cohort_size"] != cohort_size
        for context in contexts
    ):
        return False
    try:
        full_events = database.get_offer_cancel_cohort_prepared_events(cohort_id)
        full_contexts = [cohort_member(event) for event in full_events]
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if (
        len(full_contexts) != cohort_size
        or any(context is None for context in full_contexts)
        or len({context["operation_id"] for context in full_contexts}) != cohort_size
    ):
        return False
    try:
        manifest = database.get_offer_cancel_cohort_manifest(cohort_id)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if manifest is not None:
        if (
            manifest["member_count"] != cohort_size
            or len(manifest["members"]) != cohort_size
        ):
            return False
        expected_members = {
            (
                member["operation_id"],
                member["attempt"],
                member["trade_id"],
            )
            for member in manifest["members"]
        }
        actual_members = {
            (
                context["operation_id"],
                context["attempt"],
                context["trade_id"],
            )
            for context in full_contexts
        }
        if actual_members != expected_members:
            return False
        try:
            for event in full_events:
                database.validate_offer_cancel_cohort_prepared_event(event, manifest)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
    else:
        # Compatibility for PREPARED cohorts written before durable manifests
        # existed.  They can complete only under the original exact digest
        # contract; every new cohort is manifest-bound above.
        trade_ids = sorted(context["trade_id"] for context in full_contexts)
        expected_cohort_id = (
            "cancel-cohort:"
            + hashlib.sha256(
                json.dumps(trade_ids, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        if cohort_id != expected_cohort_id:
            return False
    return (
        database.get_offer_cancel_effect_claim(
            operation_id=operation_id,
            attempt=own_context["attempt"],
        )
        is not None
    )


def _same_handler(first: Optional[Callable], second: Optional[Callable]) -> bool:
    if first is second:
        return True
    try:
        return bool(first == second)
    except Exception:
        return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")
        return value.astimezone(timezone.utc)
    if type(value) is not str:
        raise ValueError("timestamp must be an exact string or datetime")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone information")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _decode_blockers(row: Mapping[str, Any]) -> tuple[str, ...]:
    try:
        raw = json.loads(str(row.get("blocking_operation_ids_json") or "[]"))
    except Exception as exc:
        raise ValueError("invalid durable blocker list") from exc
    if not isinstance(raw, list):
        raise ValueError("invalid durable blocker list")
    values = []
    for item in raw:
        values.append(_exact_text(item, "blocking operation id"))
    if len(values) != len(set(values)):
        raise ValueError("duplicate durable blocker")
    return tuple(sorted(values))


def _lease_public_result(result: Mapping[str, Any]) -> dict[str, Any]:
    lease = result.get("lease")
    if not isinstance(lease, Mapping):
        lease = None
    return {key: value for key, value in result.items() if key != "lease"} | (
        {"lease": dict(lease)} if lease is not None else {}
    )


def pid_liveness(pid: int, owner_host: str) -> Optional[bool]:
    """Return True/False only when local OS evidence is decisive.

    ``None`` means fail-closed uncertainty.  A reused PID is deliberately
    reported alive because it cannot prove that the prior owner is gone.
    """

    try:
        safe_pid = _exact_positive_int(pid, "pid")
        safe_host = _exact_text(owner_host, "owner_host")
    except ValueError:
        return None
    local_names = {socket.gethostname().casefold(), socket.getfqdn().casefold()}
    if safe_host.casefold() not in local_names:
        return None
    if safe_pid == os.getpid():
        return True

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process = ctypes.windll.kernel32.OpenProcess(
                0x1000 | 0x00100000, False, safe_pid
            )
            if not process:
                error = ctypes.windll.kernel32.GetLastError()
                return False if error == 87 else None
            try:
                exit_code = wintypes.DWORD()
                if not ctypes.windll.kernel32.GetExitCodeProcess(
                    process, ctypes.byref(exit_code)
                ):
                    return None
                return exit_code.value == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(process)
        except Exception:
            return None

    try:
        os.kill(safe_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _stop_callback_boundary(method):
    """Dispatch a pending stop callback after the outer gate lock is released."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        depth = int(getattr(self._stop_dispatch_local, "depth", 0))
        self._stop_dispatch_local.depth = depth + 1
        try:
            return method(self, *args, **kwargs)
        finally:
            self._stop_dispatch_local.depth = depth
            if depth == 0:
                self._flush_stop_handler()

    return wrapped


class MutationGate:
    """One process' view of the durable safety latch and mutation lease."""

    _IMMUTABLE_IDENTITY_ATTRIBUTES = frozenset(
        {
            "wallet_identity_binding",
            "wallet_identity_binding_digest",
            "_wallet_identity_binding",
            "_wallet_identity_binding_digest",
            "_identity_wallet_fingerprint_hash",
            "_identity_network",
            "_identity_backend",
            "_wallet_adapter_authority",
            "_identity_authority_installed",
        }
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if (
            name in self._IMMUTABLE_IDENTITY_ATTRIBUTES
            and self.__dict__.get("_identity_authority_installed") is True
        ):
            raise AttributeError("wallet identity authority is immutable")
        object.__setattr__(self, name, value)

    @property
    def wallet_identity_binding(self) -> Optional[WalletIdentityBinding]:
        authority = _registered_owner_identity_authority(self)
        return authority.binding if authority is not None else None

    @property
    def wallet_identity_binding_digest(self) -> Optional[str]:
        authority = _registered_owner_identity_authority(self)
        return authority.binding_digest if authority is not None else None

    def __init__(
        self,
        *,
        run_id: str,
        owner_pid: int,
        owner_host: str,
        wallet_fingerprint_hash: str,
        network: str,
        lease_seconds: int = 30,
        clock: Callable[[], datetime] = _utc_now,
        pid_liveness: Callable[[int, str], Optional[bool]] = pid_liveness,
        read_only: bool = False,
        wallet_identity_binding: Optional[WalletIdentityBinding] = None,
        wallet_adapter_authority: Any = None,
    ):
        object.__setattr__(self, "_identity_authority_installed", False)
        self.run_id = _exact_text(run_id, "run_id")
        self.owner_pid = _exact_positive_int(owner_pid, "owner_pid")
        self.owner_host = _exact_text(owner_host, "owner_host")
        self.wallet_fingerprint_hash = _exact_text(
            wallet_fingerprint_hash, "wallet_fingerprint_hash"
        )
        self.network = _exact_text(network, "network", max_length=64)
        self.lease_seconds = _exact_positive_int(lease_seconds, "lease_seconds")
        if type(read_only) is not bool:
            raise TypeError("read_only must be an exact bool")
        self._read_only = read_only
        self._clock = clock
        self._pid_liveness = pid_liveness
        if wallet_identity_binding is not None and (
            type(wallet_identity_binding) is not WalletIdentityBinding
            or hashlib.sha256(
                f"fingerprint:{wallet_identity_binding.fingerprint}".encode("utf-8")
            ).hexdigest()
            != self.wallet_fingerprint_hash
            or wallet_identity_binding.network_id != self.network.lower()
        ):
            raise ValueError("wallet identity binding does not match lease binding")
        identity_digest = (
            wallet_identity_binding_digest(wallet_identity_binding)
            if wallet_identity_binding is not None
            else None
        )
        object.__setattr__(self, "_wallet_identity_binding", wallet_identity_binding)
        object.__setattr__(self, "_wallet_identity_binding_digest", identity_digest)
        object.__setattr__(
            self,
            "_identity_wallet_fingerprint_hash",
            self.wallet_fingerprint_hash,
        )
        object.__setattr__(self, "_identity_network", self.network)
        object.__setattr__(
            self,
            "_identity_backend",
            wallet_identity_binding.backend
            if wallet_identity_binding is not None
            else None,
        )
        object.__setattr__(self, "_wallet_adapter_authority", wallet_adapter_authority)
        authority = _OwnerIdentityAuthority(
            binding=wallet_identity_binding,
            binding_digest=identity_digest,
            wallet_fingerprint_hash=self.wallet_fingerprint_hash,
            network=self.network,
            backend=(
                wallet_identity_binding.backend
                if wallet_identity_binding is not None
                else None
            ),
            wallet_adapter_authority=wallet_adapter_authority,
            generation_digest=_new_authority_generation_digest(),
        )
        with _owner_identity_authorities_lock:
            _owner_identity_authorities[self] = authority
        object.__setattr__(self, "_identity_authority_installed", True)
        self._last_wallet_identity_observed_at_utc: Optional[str] = None
        self._lock = threading.RLock()
        self._mutation_condition = threading.Condition(self._lock)
        self._active_mutations: dict[str, str] = {}
        self._active_wallet_mutations: set[str] = set()
        self._wallet_lifecycle_transitioning = False
        self._quiescing = False
        self._lease_version: Optional[int] = None
        self._lease_acquired_at: Optional[str] = None
        self._local_reason_code = ""
        self._local_latch_generation: Optional[int] = None
        self._stop_handler: Optional[Callable[[str], None]] = None
        self._notified_stop_handler: Optional[Callable[[str], None]] = None
        self._pending_stop_notification: Optional[tuple[Callable[[str], None], str]] = (
            None
        )
        self._stop_dispatch_local = threading.local()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self.last_acquire_result: dict[str, Any] = {
            "acquired": False,
            "reason": "not_attempted",
        }

    def require_wallet_identity_authority(
        self, operation: str
    ) -> WalletIdentityBinding:
        """Revalidate the frozen complete authority at a wallet boundary."""

        try:
            authority = _registered_owner_identity_authority(self)
            binding = self._wallet_identity_binding
            valid = (
                type(authority) is _OwnerIdentityAuthority
                and type(binding) is WalletIdentityBinding
                and binding is authority.binding
                and wallet_identity_binding_digest(binding) == authority.binding_digest
                and self._wallet_identity_binding_digest == authority.binding_digest
                and self.wallet_identity_binding is authority.binding
                and self.wallet_identity_binding_digest == authority.binding_digest
                and self.wallet_fingerprint_hash == authority.wallet_fingerprint_hash
                and self.network == authority.network
                and self.wallet_fingerprint_hash
                == self._identity_wallet_fingerprint_hash
                and self.network == self._identity_network
                and binding.backend == authority.backend
                and self._identity_backend == authority.backend
                and wallet_fingerprint_hash(binding.fingerprint)
                == authority.wallet_fingerprint_hash
                and binding.network_id == authority.network.lower()
            )
        except Exception:
            valid = False
        if not valid:
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
        return binding

    def require_wallet_adapter_authority(self, candidate: Any, operation: str) -> Any:
        """Return the acquired adapter only when its external pin is intact."""

        self.require_wallet_identity_authority(operation)
        authority = _registered_owner_identity_authority(self)
        if (
            type(authority) is not _OwnerIdentityAuthority
            or authority.wallet_adapter_authority is None
            or candidate is not authority.wallet_adapter_authority
            or self._wallet_adapter_authority is not authority.wallet_adapter_authority
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
        return authority.wallet_adapter_authority

    def _authorization_snapshot(self) -> dict[str, Any]:
        if self._read_only:
            return database.get_mutation_authorization_snapshot(read_only=True)
        return database.get_mutation_authorization_snapshot()

    def _now(self) -> datetime:
        value = self._clock()
        return _as_utc(value)

    def _set_local_block(
        self, reason_code: str, *, latch_generation: Optional[int] = None
    ) -> None:
        safe_reason = _safe_reason_code(reason_code)
        with self._lock:
            if safe_reason in _TERMINAL_PROCESS_FENCES:
                self._local_reason_code = safe_reason
                self._local_latch_generation = None
            elif not self._local_reason_code:
                self._local_reason_code = safe_reason
            if (
                latch_generation is not None
                and safe_reason not in _TERMINAL_PROCESS_FENCES
            ):
                self._local_latch_generation = int(latch_generation)
            if self._stop_handler is not None and not _same_handler(
                self._stop_handler, self._notified_stop_handler
            ):
                self._notified_stop_handler = self._stop_handler
                self._pending_stop_notification = (self._stop_handler, safe_reason)

    def _flush_stop_handler(self) -> None:
        with self._lock:
            notification = self._pending_stop_notification
            self._pending_stop_notification = None
        if notification is not None:
            callback, safe_reason = notification
            try:
                callback(safe_reason)
            except Exception:
                slog(
                    "SAFETY",
                    "Mutation stop handler failed",
                    {"reason_code": safe_reason},
                    level="error",
                )

    @_stop_callback_boundary
    def register_stop_handler(self, handler: Optional[Callable[[str], None]]) -> None:
        if handler is not None and not callable(handler):
            raise TypeError("stop handler must be callable or None")
        with self._lock:
            self._stop_handler = handler
            local_reason = self._local_reason_code
        if handler is not None and local_reason:
            self._set_local_block(local_reason)
            return
        if handler is not None:
            # status() invokes a newly registered handler when it discovers a
            # durable latch. Lease ownership diagnostics do not create a local
            # asynchronous stop event.
            self.status()

    @_stop_callback_boundary
    def acquire(self) -> dict[str, Any]:
        with self._lock:
            if self._active_wallet_mutations or self._wallet_lifecycle_transitioning:
                result = {
                    "acquired": False,
                    "reason": "active_wallet_mutations",
                }
                return result
            try:
                authorization = self._authorization_snapshot()
                current = authorization["lease"]
                now = self._now()
                expiry = now + timedelta(seconds=self.lease_seconds)
                expected_version = int(current["lease_version"])
                allow_takeover = False

                if bool(current.get("active")):
                    current_owner = str(current.get("owner_run_id") or "")
                    expired = _as_utc(current.get("expires_at")) <= now
                    if current_owner == self.run_id:
                        if expired:
                            result = {
                                "acquired": False,
                                "reason": "lease_expired",
                                "lease": current,
                            }
                            self._set_local_block("LEASE_EXPIRED")
                            self.last_acquire_result = result
                            return _lease_public_result(result)
                        if self._lease_version != expected_version:
                            result = {
                                "acquired": False,
                                "reason": "same_run_fencing_unproven",
                                "lease": current,
                            }
                            self._set_local_block("LEASE_LOST")
                            self.last_acquire_result = result
                            return _lease_public_result(result)
                    else:
                        if not expired:
                            result = {
                                "acquired": False,
                                "reason": "owned_by_other_run",
                                "lease": current,
                            }
                            self.last_acquire_result = result
                            return _lease_public_result(result)
                        prior_host = str(current.get("owner_host") or "")
                        alive = self._pid_liveness(
                            int(current.get("owner_pid") or 0), prior_host
                        )
                        if alive is True:
                            result = {
                                "acquired": False,
                                "reason": "prior_owner_alive",
                                "lease": current,
                            }
                            self.last_acquire_result = result
                            return _lease_public_result(result)
                        if alive is not False:
                            result = {
                                "acquired": False,
                                "reason": "prior_owner_liveness_unproven",
                                "lease": current,
                            }
                            self.last_acquire_result = result
                            return _lease_public_result(result)
                        latch = authorization["latch"]
                        if str(latch.get("state") or "") != "resolved":
                            result = {
                                "acquired": False,
                                "reason": "safety_latch_tripped",
                                "lease": current,
                            }
                            self.last_acquire_result = result
                            return _lease_public_result(result)
                        if authorization["unresolved"]:
                            result = {
                                "acquired": False,
                                "reason": "unresolved_operations",
                                "lease": current,
                            }
                            self.last_acquire_result = result
                            return _lease_public_result(result)
                        allow_takeover = True

                result = database.acquire_runtime_mutation_lease(
                    owner_run_id=self.run_id,
                    owner_pid=self.owner_pid,
                    owner_host=self.owner_host,
                    wallet_fingerprint_hash=self.wallet_fingerprint_hash,
                    network=self.network,
                    lease_expires_at=expiry,
                    now=now,
                    allow_expired_takeover=allow_takeover,
                    expected_lease_version=expected_version,
                )
                result = _lease_public_result(result)
                if result.get("acquired"):
                    lease = result["lease"]
                    self._lease_version = int(lease["lease_version"])
                    self._lease_acquired_at = str(lease.get("acquired_at") or "")
                    if not _rotate_owner_identity_authority(self):
                        self._set_local_block("WALLET_IDENTITY_BINDING_INVALID")
                self.last_acquire_result = result
                return result
            except Exception:
                self._set_local_block("DURABLE_STATE_UNAVAILABLE")
                result = {
                    "acquired": False,
                    "reason": "durable_state_unavailable",
                }
                self.last_acquire_result = result
                return result

    @_stop_callback_boundary
    def acquire_recovery_successor(self, recovery_epoch: Any) -> dict[str, Any]:
        """Acquire only as an append-only successor to one frozen recovery."""

        with self._lock:
            if self._active_wallet_mutations or self._wallet_lifecycle_transitioning:
                return {"acquired": False, "reason": "active_wallet_mutations"}
            try:
                if (
                    type(recovery_epoch) is not dict
                    or recovery_epoch.get("wallet_fingerprint_hash")
                    != self.wallet_fingerprint_hash
                    or recovery_epoch.get("network") != self.network
                    or type(recovery_epoch.get("recovery_id")) is not str
                ):
                    return {
                        "acquired": False,
                        "reason": "recovery_binding_mismatch",
                    }
                authorization = self._authorization_snapshot()
                current = authorization.get("lease")
                latch = authorization.get("latch")
                if type(current) is not dict or type(latch) is not dict:
                    raise ValueError("runtime recovery authority is unavailable")
                if (
                    latch.get("state") != "tripped"
                    or int(latch.get("generation") or -1)
                    != int(recovery_epoch.get("latch_generation") or -2)
                    or _decode_blockers(latch)
                    != (str(recovery_epoch.get("blocker_id") or ""),)
                ):
                    return {
                        "acquired": False,
                        "reason": "recovery_latch_mismatch",
                        "lease": current,
                    }
                now = self._now()
                prior_dead = False
                if bool(current.get("active")) and current.get(
                    "owner_run_id"
                ) != self.run_id:
                    if _as_utc(current.get("expires_at")) > now:
                        return {
                            "acquired": False,
                            "reason": "prior_recovery_owner_active",
                            "lease": current,
                        }
                    prior_dead = self._pid_liveness(
                        int(current.get("owner_pid") or 0),
                        str(current.get("owner_host") or ""),
                    ) is False
                    if not prior_dead:
                        return {
                            "acquired": False,
                            "reason": "prior_owner_liveness_unproven",
                            "lease": current,
                        }
                adopted = database.adopt_runtime_recovery_epoch(
                    recovery_id=recovery_epoch["recovery_id"],
                    successor_owner_run_id=self.run_id,
                    successor_owner_pid=self.owner_pid,
                    successor_owner_host=self.owner_host,
                    wallet_fingerprint_hash=self.wallet_fingerprint_hash,
                    network=self.network,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    expected_lease_version=int(current["lease_version"]),
                    prior_owner_liveness_proven_dead=prior_dead,
                    now=now,
                )
                result = {
                    "acquired": adopted.get("adopted") is True,
                    "reason": adopted.get("reason") or "recovery_adoption_failed",
                    "lease": adopted.get("lease"),
                    "recovery_takeover": adopted.get("record"),
                }
                if result["acquired"]:
                    lease = result["lease"]
                    self._lease_version = int(lease["lease_version"])
                    self._lease_acquired_at = str(lease.get("acquired_at") or "")
                    self._read_only = False
                    if not _rotate_owner_identity_authority(self):
                        self._set_local_block("WALLET_IDENTITY_BINDING_INVALID")
                self.last_acquire_result = _lease_public_result(result)
                return self.last_acquire_result
            except Exception:
                result = {
                    "acquired": False,
                    "reason": "durable_state_unavailable",
                }
                self.last_acquire_result = result
                return result

    def _status_from_rows(
        self,
        latch: Mapping[str, Any],
        lease: Mapping[str, Any],
        unresolved: list[Mapping[str, Any]],
        *,
        mirror_process_fence: bool = True,
    ) -> GateStatus:
        generation = int(latch.get("generation") or 0)
        blockers = _decode_blockers(latch)
        lease_active = bool(lease.get("active"))
        lease_version = int(lease.get("lease_version") or 0)
        lease_expiry = str(lease.get("expires_at")) if lease.get("expires_at") else None
        owner_run_id = (
            str(lease.get("owner_run_id")) if lease.get("owner_run_id") else None
        )
        owner_pid = int(lease["owner_pid"]) if lease.get("owner_pid") else None
        owned = bool(
            lease_active
            and owner_run_id == self.run_id
            and owner_pid == self.owner_pid
            and str(lease.get("owner_host") or "") == self.owner_host
            and str(lease.get("wallet_fingerprint_hash") or "")
            == self.wallet_fingerprint_hash
            and str(lease.get("network") or "") == self.network
        )

        def result(reason_code: str, source: str) -> GateStatus:
            return GateStatus(
                allowed=False,
                reason_code=reason_code,
                source=source,
                latch_generation=generation,
                blocking_operation_ids=blockers,
                lease_active=lease_active,
                lease_version=lease_version,
                lease_expires_at=lease_expiry,
                owner_run_id=owner_run_id,
                owner_pid=owner_pid,
                owner_is_this_run=owned,
            )

        if str(latch.get("state") or "") == "tripped":
            binding_matches = (
                str(latch.get("wallet_fingerprint_hash") or "")
                == self.wallet_fingerprint_hash
                and str(latch.get("network") or "") == self.network
            )
            reason = (
                _safe_reason_code(latch.get("reason_code"))
                if binding_matches
                else "LATCH_BINDING_MISMATCH"
            )
            if mirror_process_fence:
                self._set_local_block(reason, latch_generation=generation)
            return result(reason, "durable_latch")
        if str(latch.get("state") or "") != "resolved":
            return result("DURABLE_STATE_UNAVAILABLE", "durable_latch")
        if unresolved:
            return result("UNRESOLVED_OPERATIONS", "operation_journal")
        with self._lock:
            local_reason = self._local_reason_code
            expected_version = self._lease_version
        if local_reason:
            return result(local_reason, "process")
        if expected_version is not None and (
            not lease_active or not owned or lease_version != expected_version
        ):
            if mirror_process_fence:
                self._set_local_block("LEASE_LOST")
            return result("LEASE_LOST", "lease")
        if not lease_active:
            return result("LEASE_UNAVAILABLE", "lease")
        if not owned:
            return result("LEASE_OWNED_BY_OTHER", "lease")
        if expected_version is None:
            if mirror_process_fence:
                self._set_local_block("LEASE_LOST")
            return result("LEASE_LOST", "lease")
        if lease_expiry is None or _as_utc(lease_expiry) <= self._now():
            if mirror_process_fence:
                self._set_local_block("LEASE_EXPIRED")
            return result("LEASE_EXPIRED", "lease")
        return GateStatus(
            allowed=True,
            reason_code="",
            source="lease",
            latch_generation=generation,
            blocking_operation_ids=blockers,
            lease_active=True,
            lease_version=lease_version,
            lease_expires_at=lease_expiry,
            owner_run_id=owner_run_id,
            owner_pid=owner_pid,
            owner_is_this_run=True,
        )

    @_stop_callback_boundary
    def status(self) -> GateStatus:
        with self._lock:
            try:
                authorization = self._authorization_snapshot()
                return self._status_from_rows(
                    authorization["latch"],
                    authorization["lease"],
                    authorization["unresolved"],
                )
            except Exception:
                self._set_local_block("DURABLE_STATE_UNAVAILABLE")
                return GateStatus(
                    allowed=False,
                    reason_code="DURABLE_STATE_UNAVAILABLE",
                    source="durable_read",
                )

    def read_only_status(self) -> GateStatus:
        """Return fresh diagnostics without installing a process-local fence.

        Mutation boundaries continue to use :meth:`status`, which mirrors any
        durable stop into process memory and invokes the stop handler.  A GET
        diagnostics request must not create that state transition merely by
        sampling a short-lived worker reconciliation latch.
        """

        with self._lock:
            try:
                authorization = self._authorization_snapshot()
                return self._status_from_rows(
                    authorization["latch"],
                    authorization["lease"],
                    authorization["unresolved"],
                    mirror_process_fence=False,
                )
            except Exception:
                return GateStatus(
                    allowed=False,
                    reason_code="DURABLE_STATE_UNAVAILABLE",
                    source="durable_read",
                )

    def require_allowed(self, operation: str) -> GateStatus:
        current = self.status()
        if not current.allowed:
            raise MutationBlocked(current.reason_code, operation)
        return current

    def require_operation_continuation(
        self,
        permit: str,
        operation: str,
        blocking_operation_id: str,
        blocking_intent_id: str,
    ) -> tuple[WalletIdentityBinding, Any]:
        """Allow one already-entered wallet effect past only its own PREPARED blocker."""

        safe_operation = _safe_operation(operation)
        blocker = _exact_text(blocking_operation_id, "blocking_operation_id")
        intent = _exact_text(blocking_intent_id, "blocking_intent_id")
        with self._lock:
            self.require_active_wallet_mutation_permit(permit, safe_operation)
            if self._quiescing or self._wallet_lifecycle_transitioning:
                raise MutationBlocked("MUTATION_SHUTTING_DOWN", safe_operation)
            if self._local_reason_code:
                raise MutationBlocked(self._local_reason_code, safe_operation)
            try:
                authorization = self._authorization_snapshot()
                latch = authorization["latch"]
                unresolved = authorization["unresolved"]
                lease = authorization["lease"]
                if str(latch.get("state") or "") != "resolved":
                    raise MutationBlocked(
                        _safe_reason_code(latch.get("reason_code")), safe_operation
                    )
                if not _is_exact_prepared_operation_blocker(
                    unresolved,
                    operation=safe_operation,
                    operation_id=blocker,
                    intent_id=intent,
                ):
                    raise MutationBlocked("UNRESOLVED_OPERATIONS", safe_operation)
                expected_lease = (
                    True,
                    self.run_id,
                    self.owner_pid,
                    self.owner_host,
                    self.wallet_fingerprint_hash,
                    self.network,
                    self._lease_version,
                    self._lease_acquired_at,
                )
                actual_lease = (
                    bool(lease.get("active")),
                    str(lease.get("owner_run_id") or ""),
                    lease.get("owner_pid"),
                    str(lease.get("owner_host") or ""),
                    str(lease.get("wallet_fingerprint_hash") or ""),
                    str(lease.get("network") or ""),
                    int(lease.get("lease_version") or 0),
                    str(lease.get("acquired_at") or ""),
                )
                if actual_lease != expected_lease:
                    self._set_local_block("LEASE_LOST")
                    raise MutationBlocked("LEASE_LOST", safe_operation)
                if _as_utc(lease.get("expires_at")) <= self._now():
                    self._set_local_block("LEASE_EXPIRED")
                    raise MutationBlocked("LEASE_EXPIRED", safe_operation)
            except MutationBlocked:
                raise
            except Exception as exc:
                self._set_local_block("DURABLE_STATE_UNAVAILABLE")
                raise MutationBlocked(
                    "DURABLE_STATE_UNAVAILABLE", safe_operation
                ) from exc
            binding = self.require_wallet_identity_authority(safe_operation)
            adapter = self.require_wallet_adapter_authority(
                self._wallet_adapter_authority, safe_operation
            )
            return binding, adapter

    def require_fresh_operation_continuation(
        self,
        permit: str,
        snapshot: Any,
        operation: str,
        blocking_operation_id: str,
        blocking_intent_id: str,
    ) -> tuple[WalletIdentityBinding, Any, dict[str, Any]]:
        """Validate fresh identity while allowing only the effect's own blocker."""

        safe_operation = _safe_operation(operation)
        with self._lock:
            binding, adapter = self.require_operation_continuation(
                permit,
                safe_operation,
                blocking_operation_id,
                blocking_intent_id,
            )
            decision = validate_wallet_identity(
                binding,
                snapshot,
                now=self._now(),
                last_observed_at_utc=self._last_wallet_identity_observed_at_utc,
            )
            if decision.get("allowed") is not True:
                raise MutationBlocked(decision.get("reason"), safe_operation)
            self._last_wallet_identity_observed_at_utc = str(
                decision["observed_at_utc"]
            )
            return binding, adapter, decision

    def require_fresh_wallet_identity(
        self, snapshot: Any, operation: str
    ) -> dict[str, Any]:
        """Require a new exact identity observation under current lease authority."""

        safe_operation = _safe_operation(operation)
        with self._lock:
            binding = self.require_wallet_identity_authority(safe_operation)
            self.require_allowed(safe_operation)
            decision = validate_wallet_identity(
                binding,
                snapshot,
                now=self._now(),
                last_observed_at_utc=self._last_wallet_identity_observed_at_utc,
            )
            if decision.get("allowed") is not True:
                raise MutationBlocked(decision.get("reason"), safe_operation)
            self._last_wallet_identity_observed_at_utc = str(
                decision["observed_at_utc"]
            )
            return decision

    @_stop_callback_boundary
    def enter_mutation(self, operation: str) -> str:
        """Register one guarded in-process mutation until its exact exit."""

        safe_operation = _safe_operation(operation)
        with self._lock:
            if self._quiescing or self._wallet_lifecycle_transitioning:
                raise MutationBlocked("MUTATION_SHUTTING_DOWN", safe_operation)
            self.require_allowed(safe_operation)
            permit = str(uuid.uuid4())
            self._active_mutations[permit] = safe_operation
            return permit

    def register_wallet_mutation_permit(self, permit: str, operation: str) -> None:
        """Bind an active generic token to wallet lifecycle coordination."""

        safe_operation = _safe_operation(operation)
        with self._lock:
            if (
                type(permit) is not str
                or permit not in self._active_mutations
                or self._quiescing
                or self._wallet_lifecycle_transitioning
            ):
                raise MutationBlocked("MUTATION_SHUTTING_DOWN", safe_operation)
            self._active_wallet_mutations.add(permit)

    def exit_mutation(self, permit: str) -> bool:
        """Finish one exact guarded mutation permit."""

        if type(permit) is not str or not permit:
            return False
        with self._mutation_condition:
            self._active_wallet_mutations.discard(permit)
            removed = self._active_mutations.pop(permit, None) is not None
            if removed:
                self._mutation_condition.notify_all()
            return removed

    def require_active_mutation_permit(self, permit: str, operation: str) -> None:
        """Require that an exact permit still belongs to this runtime."""

        safe_operation = _safe_operation(operation)
        if type(permit) is not str or not permit:
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
        with self._lock:
            if permit not in self._active_mutations:
                raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)

    def require_active_wallet_mutation_permit(
        self, permit: str, operation: str
    ) -> None:
        """Require an exact active token registered for wallet lifecycle fencing."""

        safe_operation = _safe_operation(operation)
        if type(permit) is not str or not permit:
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
        with self._lock:
            if (
                permit not in self._active_mutations
                or permit not in self._active_wallet_mutations
            ):
                raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)

    def begin_quiesce(self) -> None:
        """Deny new in-process mutations before shutdown drains existing work."""

        with self._mutation_condition:
            self._quiescing = True
            self._mutation_condition.notify_all()

    def wait_for_quiescence(self, timeout_seconds: float) -> bool:
        """Wait boundedly until every guarded in-process mutation has exited."""

        timeout = max(0.0, float(timeout_seconds))
        deadline = time.monotonic() + timeout
        with self._mutation_condition:
            while self._active_mutations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._mutation_condition.wait(timeout=remaining)
            return True

    def active_mutation_count(self) -> int:
        with self._lock:
            return len(self._active_mutations)

    def active_wallet_mutation_count(self) -> int:
        with self._lock:
            return len(self._active_wallet_mutations)

    @_stop_callback_boundary
    def trip(
        self, reason_code: str, blocking_operation_ids: list[str] | tuple[str, ...]
    ) -> GateStatus:
        safe_reason = _safe_reason_code(reason_code)
        try:
            database.trip_runtime_safety_latch(
                reason_code=safe_reason,
                reason=_REASON_DESCRIPTIONS[safe_reason],
                blocking_operation_ids=blocking_operation_ids,
                wallet_fingerprint_hash=self.wallet_fingerprint_hash,
                network=self.network,
                tripped_at=self._now(),
            )
            self._set_local_block(safe_reason)
        except Exception:
            self._set_local_block("DURABLE_STATE_UNAVAILABLE")
        return self.status()

    @_stop_callback_boundary
    def release_resolved(
        self, expected_generation: int, resolved_operation_ids: list[str]
    ) -> dict[str, Any]:
        try:
            with self._lock:
                local_reason = self._local_reason_code
                if local_reason in _TERMINAL_PROCESS_FENCES:
                    return {
                        "released": False,
                        "reason": "terminal_process_fence",
                        "status": self.status().to_dict(),
                    }
                authorization = self._authorization_snapshot()
                latch = authorization["latch"]
                if str(latch.get("state") or "") != "tripped":
                    externally_resolved = (
                        str(latch.get("state") or "") == "resolved"
                        and int(latch.get("generation") or 0) == expected_generation
                        and self._local_latch_generation == expected_generation
                        and bool(local_reason)
                        and not authorization["unresolved"]
                        and type(resolved_operation_ids) in (list, tuple)
                        and 1 <= len(resolved_operation_ids) <= 64
                        and len(set(resolved_operation_ids))
                        == len(resolved_operation_ids)
                        and all(
                            type(operation_id) is str and bool(operation_id.strip())
                            for operation_id in resolved_operation_ids
                        )
                        and str(latch.get("wallet_fingerprint_hash") or "")
                        == self.wallet_fingerprint_hash
                        and str(latch.get("network") or "") == self.network
                    )
                    if externally_resolved:
                        self._local_reason_code = ""
                        self._local_latch_generation = None
                        self._notified_stop_handler = None
                        current = self.status()
                        return {
                            "released": current.allowed,
                            "reason": (
                                "released"
                                if current.allowed
                                else current.reason_code.lower()
                            ),
                            "status": current.to_dict(),
                        }
                    return {
                        "released": False,
                        "reason": "not_tripped",
                        "status": self._status_from_rows(
                            latch,
                            authorization["lease"],
                            authorization["unresolved"],
                        ).to_dict(),
                    }
                if int(latch.get("generation") or 0) != expected_generation:
                    return {
                        "released": False,
                        "reason": "generation_mismatch",
                        "status": self._status_from_rows(
                            latch,
                            authorization["lease"],
                            authorization["unresolved"],
                        ).to_dict(),
                    }
                if (
                    str(latch.get("wallet_fingerprint_hash") or "")
                    != self.wallet_fingerprint_hash
                    or str(latch.get("network") or "") != self.network
                ):
                    return {
                        "released": False,
                        "reason": "latch_binding_mismatch",
                        "status": self.status().to_dict(),
                    }
                result = database.resolve_runtime_safety_latch(
                    expected_generation=expected_generation,
                    resolved_operation_ids=resolved_operation_ids,
                    resolved_at=self._now(),
                )
                if not result.get("resolved"):
                    return {
                        "released": False,
                        "reason": result.get("reason") or "not_resolved",
                        "status": self.status().to_dict(),
                    }
                if self._local_latch_generation == expected_generation:
                    self._local_reason_code = ""
                    self._local_latch_generation = None
                    self._notified_stop_handler = None
                current = self.status()
                return {
                    "released": current.allowed,
                    "reason": "released"
                    if current.allowed
                    else current.reason_code.lower(),
                    "status": current.to_dict(),
                }
        except Exception:
            self._set_local_block("DURABLE_STATE_UNAVAILABLE")
            return {
                "released": False,
                "reason": "durable_state_unavailable",
                "status": self.status().to_dict(),
            }

    @_stop_callback_boundary
    def heartbeat(self) -> dict[str, Any]:
        with self._lock:
            version = self._lease_version
            if version is None:
                self._set_local_block("HEARTBEAT_FAILED")
                return {"heartbeat": False, "reason": "not_owned"}
            now = self._now()
            try:
                result = database.heartbeat_runtime_mutation_lease(
                    owner_run_id=self.run_id,
                    expected_lease_version=version,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                )
                result = _lease_public_result(result)
            except Exception:
                result = {"heartbeat": False, "reason": "durable_state_unavailable"}
            if result.get("heartbeat"):
                self._lease_version = int(result["lease"]["lease_version"])
                return result
            self._set_local_block("HEARTBEAT_FAILED")
            return result

    def start_heartbeat(self, interval_seconds: Optional[float] = None) -> bool:
        with self._lock:
            if self._heartbeat_thread and self._heartbeat_thread.is_alive():
                return False
            interval = (
                float(interval_seconds)
                if interval_seconds is not None
                else max(1.0, self.lease_seconds / 3)
            )
            if interval <= 0 or interval >= self.lease_seconds:
                raise ValueError("heartbeat interval must be within the lease duration")
            self._heartbeat_stop.clear()

            def run() -> None:
                while not self._heartbeat_stop.wait(interval):
                    if not self.heartbeat().get("heartbeat"):
                        return

            self._heartbeat_thread = threading.Thread(
                target=run,
                daemon=True,
                name="mutation-lease-heartbeat",
            )
            self._heartbeat_thread.start()
            return True

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)

    @_stop_callback_boundary
    def release_lease(self) -> dict[str, Any]:
        with self._lock:
            if self._active_wallet_mutations or self._wallet_lifecycle_transitioning:
                return {
                    "released": False,
                    "reason": "active_wallet_mutations",
                }
            self._wallet_lifecycle_transitioning = True
        try:
            self.stop_heartbeat()
            with self._lock:
                version = self._lease_version
                if version is None:
                    return {"released": False, "reason": "not_owned"}
                try:
                    result = database.release_runtime_mutation_lease(
                        owner_run_id=self.run_id,
                        expected_lease_version=version,
                        released_at=self._now(),
                    )
                    result = _lease_public_result(result)
                except Exception:
                    result = {
                        "released": False,
                        "reason": "durable_state_unavailable",
                    }
                if result.get("released"):
                    self._lease_version = None
                else:
                    self._set_local_block("LEASE_LOST")
                return result
        finally:
            with self._lock:
                self._wallet_lifecycle_transitioning = False

    @_stop_callback_boundary
    def issue_worker_delegation(
        self,
        *,
        operation_id: str,
        purpose: str,
        worker_id: str,
        ttl_seconds: int,
        require_wallet_identity: bool = False,
    ) -> WorkerDelegation:
        operation = _exact_text(operation_id, "operation_id")
        safe_purpose = _exact_text(purpose, "purpose", max_length=64)
        safe_worker = _exact_text(worker_id, "worker_id")
        ttl = _exact_positive_int(ttl_seconds, "ttl_seconds")
        if type(require_wallet_identity) is not bool:
            raise TypeError("require_wallet_identity must be an exact bool")
        wallet_identity_required = require_wallet_identity
        if ttl > 3600:
            raise ValueError("ttl_seconds exceeds the maximum delegation lifetime")
        with self._lock:
            self.require_allowed(f"delegate:{safe_purpose}")
            binding = self.wallet_identity_binding
            if wallet_identity_required and binding is None:
                raise MutationBlocked(
                    "WALLET_IDENTITY_BINDING_INVALID",
                    f"delegate:{safe_purpose}:identity",
                )
            if binding is not None:
                binding = self.require_wallet_identity_authority(
                    f"delegate:{safe_purpose}:identity"
                )
            identity_payload = _wallet_identity_payload_text(binding)
            identity_digest = (
                wallet_identity_binding_digest(binding)
                if binding is not None
                else hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()
            )
            parent_epoch = _exact_text(
                self._lease_acquired_at,
                "parent_lease_epoch",
                max_length=64,
            )
            now = self._now()
            expires = now + timedelta(seconds=ttl)
            database.expire_worker_delegations(now=now)
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            delegation_id = str(uuid.uuid4())
            metadata = {
                "parent_acquired_at": self._lease_acquired_at,
                "parent_host": self.owner_host,
                "parent_pid": self.owner_pid,
                "wallet_identity_payload": identity_payload,
                "wallet_identity_digest": identity_digest,
                "parent_lease_epoch": parent_epoch,
                "wallet_identity_required": wallet_identity_required,
            }
            inserted = False
            try:
                database.issue_worker_delegation(
                    delegation_id=delegation_id,
                    delegation_token_hash=token_hash,
                    parent_run_id=self.run_id,
                    operation_id=operation,
                    worker_id=safe_worker,
                    purpose=safe_purpose,
                    wallet_fingerprint_hash=self.wallet_fingerprint_hash,
                    network=self.network,
                    issued_at=now,
                    expires_at=expires,
                    metadata_json=metadata,
                )
                inserted = True
                # Re-read after issuance: a lost lease cannot produce a usable child.
                self.require_allowed(f"delegate:{safe_purpose}:issued")
            except Exception:
                if inserted:
                    try:
                        revoked = database.revoke_worker_delegation(
                            delegation_id=delegation_id,
                            parent_run_id=self.run_id,
                            operation_id=operation,
                            revoked_at=self._now(),
                        )
                        if not revoked.get("revoked"):
                            self._set_local_block("DURABLE_STATE_UNAVAILABLE")
                    except Exception:
                        self._set_local_block("DURABLE_STATE_UNAVAILABLE")
                raise
            return WorkerDelegation(
                delegation_id=delegation_id,
                parent_run_id=self.run_id,
                operation_id=operation,
                purpose=safe_purpose,
                worker_id=safe_worker,
                wallet_fingerprint_hash=self.wallet_fingerprint_hash,
                network=self.network,
                wallet_identity_payload=identity_payload,
                wallet_identity_digest=identity_digest,
                parent_lease_epoch=parent_epoch,
                expires_at=_timestamp(expires),
                _raw_token=raw_token,
            )

    def validate_worker_delegation(
        self,
        *,
        delegation_id: str,
        raw_token: str,
        parent_run_id: str,
        operation_id: str,
        purpose: str,
        worker_id: str,
        wallet_fingerprint_hash: Optional[str] = None,
        network: Optional[str] = None,
    ) -> dict[str, Any]:
        return _validate_worker_delegation(
            delegation_id=delegation_id,
            raw_token=raw_token,
            parent_run_id=parent_run_id,
            operation_id=operation_id,
            purpose=purpose,
            worker_id=worker_id,
            wallet_fingerprint_hash=wallet_fingerprint_hash
            if wallet_fingerprint_hash is not None
            else self.wallet_fingerprint_hash,
            network=network if network is not None else self.network,
            now=self._now(),
        )

    def validate_worker_environment(
        self, environment: Mapping[str, str]
    ) -> dict[str, Any]:
        return validate_worker_environment(environment, now=self._now())

    def revoke_worker_delegation(self, delegation: WorkerDelegation) -> dict[str, Any]:
        if type(delegation) is not WorkerDelegation:
            raise TypeError("delegation must be WorkerDelegation")
        return database.revoke_worker_delegation(
            delegation_id=delegation.delegation_id,
            parent_run_id=self.run_id,
            operation_id=delegation.operation_id,
            revoked_at=self._now(),
        )


def _invalid_worker(reason: str = "worker_delegation_invalid") -> dict[str, Any]:
    return {"allowed": False, "reason": reason}


def _validate_worker_delegation(
    *,
    delegation_id: Any,
    raw_token: Any,
    parent_run_id: Any,
    operation_id: Any,
    purpose: Any,
    worker_id: Any,
    wallet_fingerprint_hash: Any,
    network: Any,
    now: datetime,
    wallet_identity_payload: Any = None,
    wallet_identity_digest: Any = None,
    parent_lease_epoch: Any = None,
    allowed_blocking_operation_id: Optional[str] = None,
    allowed_blocking_intent_id: Optional[str] = None,
    allowed_blocking_wallet_operation: str = "wallet:create_offer",
) -> dict[str, Any]:
    try:
        values = {
            "delegation_id": _exact_text(delegation_id, "delegation_id"),
            "raw_token": _exact_text(raw_token, "raw_token", max_length=512),
            "parent_run_id": _exact_text(parent_run_id, "parent_run_id"),
            "operation_id": _exact_text(operation_id, "operation_id"),
            "purpose": _exact_text(purpose, "purpose", max_length=64),
            "worker_id": _exact_text(worker_id, "worker_id"),
            "wallet_fingerprint_hash": _exact_text(
                wallet_fingerprint_hash, "wallet_fingerprint_hash"
            ),
            "network": _exact_text(network, "network", max_length=64),
        }
        token_hash = hashlib.sha256(values["raw_token"].encode("utf-8")).hexdigest()
        authorization = database.get_mutation_authorization_snapshot(
            delegation_id=values["delegation_id"],
            delegation_token_hash=token_hash,
            parent_run_id=values["parent_run_id"],
            operation_id=values["operation_id"],
            purpose=values["purpose"],
            wallet_fingerprint_hash=values["wallet_fingerprint_hash"],
            network=values["network"],
            now=now,
        )
        row = authorization["delegation"]
        if row is None:
            return _invalid_worker()
        if not hmac.compare_digest(
            str(row.get("worker_id") or ""), values["worker_id"]
        ):
            return _invalid_worker()
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
        if type(metadata) is not dict:
            return _invalid_worker()
        metadata_payload = _exact_text(
            metadata.get("wallet_identity_payload"),
            "wallet_identity_payload",
            max_length=2048,
        )
        metadata_digest = _exact_text(
            metadata.get("wallet_identity_digest"),
            "wallet_identity_digest",
            max_length=64,
        )
        metadata_epoch = _exact_text(
            metadata.get("parent_lease_epoch"),
            "parent_lease_epoch",
            max_length=64,
        )
        _strict_utc_timestamp(metadata_epoch, "parent_lease_epoch")
        binding = _wallet_identity_from_payload_text(metadata_payload)
        identity_required = metadata.get("wallet_identity_required", False)
        if type(identity_required) is not bool or (
            identity_required and binding is None
        ):
            return _invalid_worker()
        recomputed_digest = (
            wallet_identity_binding_digest(binding)
            if binding is not None
            else hashlib.sha256(metadata_payload.encode("utf-8")).hexdigest()
        )
        if not hmac.compare_digest(metadata_digest, recomputed_digest):
            return _invalid_worker()
        supplied_identity = (
            wallet_identity_payload,
            wallet_identity_digest,
            parent_lease_epoch,
        )
        if any(value is not None for value in supplied_identity):
            if not all(type(value) is str for value in supplied_identity):
                return _invalid_worker()
            if supplied_identity != (
                metadata_payload,
                metadata_digest,
                metadata_epoch,
            ):
                return _invalid_worker()
        if binding is not None and (
            _binding_wallet_hash(binding) != values["wallet_fingerprint_hash"]
            or binding.network_id != values["network"].lower()
        ):
            return _invalid_worker()
        latch = authorization["latch"]
        if str(latch.get("state") or "") != "resolved":
            return _invalid_worker("parent_gate_blocked")
        unresolved = authorization["unresolved"]
        if unresolved:
            if (
                type(allowed_blocking_operation_id) is not str
                or type(allowed_blocking_intent_id) is not str
                or not _is_exact_prepared_operation_blocker(
                    unresolved,
                    operation=allowed_blocking_wallet_operation,
                    operation_id=allowed_blocking_operation_id,
                    intent_id=allowed_blocking_intent_id,
                )
            ):
                return _invalid_worker("parent_gate_blocked")
        lease = authorization["lease"]
        expected = (
            True,
            values["parent_run_id"],
            values["wallet_fingerprint_hash"],
            values["network"],
            metadata.get("parent_pid"),
            metadata.get("parent_host"),
            metadata_epoch,
        )
        actual = (
            bool(lease.get("active")),
            str(lease.get("owner_run_id") or ""),
            str(lease.get("wallet_fingerprint_hash") or ""),
            str(lease.get("network") or ""),
            lease.get("owner_pid"),
            lease.get("owner_host"),
            lease.get("acquired_at"),
        )
        if actual != expected:
            return _invalid_worker("parent_lease_invalid")
        if _as_utc(lease.get("expires_at")) <= now:
            return _invalid_worker("parent_lease_invalid")
        return {
            "allowed": True,
            "reason": "delegated",
            "delegation_id": values["delegation_id"],
            "operation_id": values["operation_id"],
            "purpose": values["purpose"],
            "worker_id": values["worker_id"],
            "wallet_identity_binding": binding,
            "wallet_identity_digest": metadata_digest,
            "parent_lease_epoch": metadata_epoch,
        }
    except Exception:
        return _invalid_worker()


def _validate_worker_environment(
    environment: Mapping[str, str],
    *,
    now: Optional[datetime] = None,
    allowed_blocking_operation_id: Optional[str] = None,
    allowed_blocking_intent_id: Optional[str] = None,
    allowed_blocking_wallet_operation: str = "wallet:create_offer",
) -> dict[str, Any]:
    if not isinstance(environment, Mapping):
        return _invalid_worker()
    try:
        values = {name: environment.get(name) for name in _DELEGATION_ENV_NAMES}
        return _validate_worker_delegation(
            delegation_id=values[DELEGATION_ID_ENV],
            raw_token=values[DELEGATION_TOKEN_ENV],
            parent_run_id=values[DELEGATION_PARENT_RUN_ENV],
            operation_id=values[DELEGATION_OPERATION_ENV],
            purpose=values[DELEGATION_PURPOSE_ENV],
            worker_id=values[DELEGATION_WORKER_ENV],
            wallet_fingerprint_hash=values[DELEGATION_WALLET_ENV],
            network=values[DELEGATION_NETWORK_ENV],
            wallet_identity_payload=values[DELEGATION_IDENTITY_ENV],
            wallet_identity_digest=values[DELEGATION_IDENTITY_DIGEST_ENV],
            parent_lease_epoch=values[DELEGATION_PARENT_EPOCH_ENV],
            now=_as_utc(now or _utc_now()),
            allowed_blocking_operation_id=allowed_blocking_operation_id,
            allowed_blocking_intent_id=allowed_blocking_intent_id,
            allowed_blocking_wallet_operation=allowed_blocking_wallet_operation,
        )
    except Exception:
        return _invalid_worker()


def validate_worker_environment(
    environment: Mapping[str, str], *, now: Optional[datetime] = None
) -> dict[str, Any]:
    return _validate_worker_environment(environment, now=now)


def require_worker_allowed_from_environment(
    operation: str, environment: Optional[Mapping[str, str]] = None
) -> dict[str, Any]:
    result = validate_worker_environment(
        os.environ if environment is None else environment
    )
    if not result.get("allowed"):
        reason = (
            "WORKER_PARENT_LEASE_INVALID"
            if result.get("reason") in {"parent_lease_invalid", "parent_gate_blocked"}
            else "WORKER_DELEGATION_INVALID"
        )
        raise MutationBlocked(reason, operation)
    return result


_runtime_lock = threading.RLock()
_runtime: Optional[MutationGate] = None
_worker_authority_lock = threading.RLock()
_worker_authority_environment: Optional[dict[str, str]] = None
_worker_authority_bound_at_utc: Optional[str] = None
_worker_identity_last_observed_at_utc: Optional[str] = None
_worker_wallet_identity_binding: Optional[WalletIdentityBinding] = None
_worker_wallet_identity_digest: Optional[str] = None
_worker_parent_lease_epoch: Optional[str] = None
_worker_wallet_adapter_authorities: dict[int, tuple[WalletIdentityBinding, Any]] = {}
_worker_authority_generation: Any = None
_worker_authority_generation_digest: Optional[str] = None
_worker_active_wallet_mutations: dict[str, Any] = {}


@dataclass(frozen=True)
class WalletMutationPermit:
    mode: str
    permit: Optional[str] = None
    runtime_authority: Any = None
    authority_generation: Any = None
    wallet_identity_binding: Optional[WalletIdentityBinding] = None
    wallet_adapter_authority: Any = None


def install_worker_authority_environment(
    environment: Mapping[str, str], *, wallet_adapter_authority: Any = None
) -> None:
    """Retain a validated child delegation for fresh per-effect checks."""

    with _worker_authority_lock:
        if _worker_active_wallet_mutations:
            raise MutationBlocked("MUTATION_SHUTTING_DOWN", "worker.install")
    result = validate_worker_environment(environment)
    if result.get("allowed") is not True:
        raise MutationBlocked("WORKER_DELEGATION_INVALID", "worker.install")
    binding = result.get("wallet_identity_binding")
    identity_digest = result.get("wallet_identity_digest")
    parent_epoch = result.get("parent_lease_epoch")
    try:
        if (
            type(binding) is not WalletIdentityBinding
            or type(identity_digest) is not str
            or not hmac.compare_digest(
                identity_digest, wallet_identity_binding_digest(binding)
            )
            or type(parent_epoch) is not str
            or wallet_adapter_authority is None
        ):
            raise ValueError("delegation has no complete wallet identity")
        _strict_utc_timestamp(parent_epoch, "parent_lease_epoch")
    except Exception as exc:
        raise MutationBlocked("WORKER_DELEGATION_INVALID", "worker.install") from exc
    try:
        copied = {
            name: _exact_text(
                environment.get(name),
                name,
                max_length=2048 if name == DELEGATION_IDENTITY_ENV else 512,
            )
            for name in _DELEGATION_ENV_NAMES
        }
    except Exception as exc:
        raise MutationBlocked("WORKER_DELEGATION_INVALID", "worker.install") from exc
    with _worker_authority_lock:
        global _worker_authority_environment, _worker_authority_bound_at_utc
        global _worker_identity_last_observed_at_utc
        global _worker_wallet_identity_binding, _worker_wallet_identity_digest
        global _worker_parent_lease_epoch
        global _worker_authority_generation, _worker_authority_generation_digest
        if _worker_active_wallet_mutations:
            raise MutationBlocked("MUTATION_SHUTTING_DOWN", "worker.install")
        if _worker_authority_environment is not None:
            installed_binding = _worker_wallet_identity_binding
            registered = (
                _worker_wallet_adapter_authorities.get(id(installed_binding))
                if installed_binding is not None
                else None
            )
            if (
                type(_worker_authority_environment) is dict
                and _worker_authority_environment == copied
                and installed_binding == binding
                and _worker_wallet_identity_digest == identity_digest
                and _worker_parent_lease_epoch == parent_epoch
                and type(registered) is tuple
                and len(registered) == 2
                and registered[0] is installed_binding
                and registered[1] is wallet_adapter_authority
            ):
                return
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", "worker.install")
        _worker_authority_environment = copied
        _worker_authority_bound_at_utc = binding.bound_at_utc
        _worker_wallet_identity_binding = binding
        _worker_wallet_identity_digest = identity_digest
        _worker_parent_lease_epoch = parent_epoch
        _worker_identity_last_observed_at_utc = None
        _worker_authority_generation = object()
        _worker_authority_generation_digest = _new_authority_generation_digest()
        _worker_wallet_adapter_authorities[id(binding)] = (
            binding,
            wallet_adapter_authority,
        )


def clear_worker_authority_environment() -> bool:
    with _worker_authority_lock:
        global _worker_authority_environment, _worker_authority_bound_at_utc
        global _worker_identity_last_observed_at_utc
        global _worker_wallet_identity_binding, _worker_wallet_identity_digest
        global _worker_parent_lease_epoch
        global _worker_authority_generation, _worker_authority_generation_digest
        if _worker_active_wallet_mutations:
            return False
        binding = _worker_wallet_identity_binding
        _worker_authority_environment = None
        _worker_authority_bound_at_utc = None
        _worker_wallet_identity_binding = None
        _worker_wallet_identity_digest = None
        _worker_parent_lease_epoch = None
        _worker_identity_last_observed_at_utc = None
        _worker_authority_generation = None
        _worker_authority_generation_digest = None
        if binding is not None:
            _worker_wallet_adapter_authorities.pop(id(binding), None)
        return True


def worker_identity_lease_binding() -> Optional[dict[str, Any]]:
    """Return the frozen complete identity after fresh delegation proof."""

    with _worker_authority_lock:
        environment = (
            dict(_worker_authority_environment)
            if _worker_authority_environment is not None
            else None
        )
        binding = _worker_wallet_identity_binding
        identity_digest = _worker_wallet_identity_digest
        parent_epoch = _worker_parent_lease_epoch
    if environment is None:
        return None
    require_worker_allowed_from_environment("wallet:identity", environment)
    with _worker_authority_lock:
        if (
            _worker_authority_environment != environment
            or _worker_authority_bound_at_utc is None
            or _worker_wallet_identity_binding is not binding
            or _worker_wallet_identity_digest != identity_digest
            or _worker_parent_lease_epoch != parent_epoch
        ):
            return None
        try:
            if (
                type(binding) is not WalletIdentityBinding
                or type(identity_digest) is not str
                or not hmac.compare_digest(
                    identity_digest, wallet_identity_binding_digest(binding)
                )
                or parent_epoch != environment[DELEGATION_PARENT_EPOCH_ENV]
                or _binding_wallet_hash(binding) != environment[DELEGATION_WALLET_ENV]
                or binding.network_id != environment[DELEGATION_NETWORK_ENV].lower()
            ):
                return None
        except Exception:
            return None
        return {
            "wallet_fingerprint_hash": environment[DELEGATION_WALLET_ENV],
            "network": environment[DELEGATION_NETWORK_ENV],
            "bound_at_utc": binding.bound_at_utc,
            "binding": binding,
            "binding_digest": identity_digest,
            "parent_lease_epoch": parent_epoch,
        }


def worker_wallet_adapter_authority(candidate: Any, operation: str) -> Any:
    """Return the installed worker adapter only while delegation proof is fresh."""

    lease_binding = worker_identity_lease_binding()
    if lease_binding is None:
        raise MutationBlocked("MUTATION_RUNTIME_NOT_INITIALIZED", operation)
    binding = lease_binding["binding"]
    with _worker_authority_lock:
        registered = _worker_wallet_adapter_authorities.get(id(binding))
        if (
            type(registered) is not tuple
            or len(registered) != 2
            or registered[0] is not binding
            or registered[1] is not candidate
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
        return registered[1]


def enter_wallet_mutation(operation: str) -> WalletMutationPermit:
    """Enter either an owned-runtime or delegated-worker mutation boundary."""

    with _runtime_lock:
        runtime = _runtime
        if runtime is not None:
            binding = runtime.require_wallet_identity_authority(operation)
            authority = _registered_owner_identity_authority(runtime)
            if (
                type(authority) is not _OwnerIdentityAuthority
                or authority.binding is not binding
                or authority.wallet_adapter_authority is None
            ):
                raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
            token = runtime.enter_mutation(operation)
            try:
                runtime.register_wallet_mutation_permit(token, operation)
            except Exception:
                runtime.exit_mutation(token)
                raise
            result = WalletMutationPermit(
                "runtime",
                token,
                runtime,
                authority,
                binding,
                authority.wallet_adapter_authority,
            )
        else:
            result = None
    if result is not None:
        try:
            require_wallet_mutation_permit_authority(result, operation)
        except Exception:
            runtime.exit_mutation(token)
            raise
        return result
    with _worker_authority_lock:
        environment = (
            dict(_worker_authority_environment)
            if _worker_authority_environment is not None
            else None
        )
        generation = _worker_authority_generation
        binding = _worker_wallet_identity_binding
        registered = (
            _worker_wallet_adapter_authorities.get(id(binding))
            if binding is not None
            else None
        )
    if environment is None:
        raise MutationBlocked("MUTATION_RUNTIME_NOT_INITIALIZED", operation)
    require_worker_allowed_from_environment(operation, environment)
    with _worker_authority_lock:
        if (
            generation is None
            or generation is not _worker_authority_generation
            or binding is not _worker_wallet_identity_binding
            or type(registered) is not tuple
            or len(registered) != 2
            or registered[0] is not binding
            or registered[1] is None
            or _worker_authority_environment != environment
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
        token = str(uuid.uuid4())
        _worker_active_wallet_mutations[token] = generation
    return WalletMutationPermit(
        "worker",
        permit=token,
        authority_generation=generation,
        wallet_identity_binding=binding,
        wallet_adapter_authority=registered[1],
    )


def require_wallet_mutation_permit_authority(
    permit: Any, operation: str
) -> tuple[WalletIdentityBinding, Any]:
    """Revalidate one exact owner/worker authority generation."""

    if (
        type(permit) is not WalletMutationPermit
        or type(permit.permit) is not str
        or not permit.permit
        or type(permit.wallet_identity_binding) is not WalletIdentityBinding
        or permit.wallet_adapter_authority is None
    ):
        raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
    if permit.mode == "runtime":
        runtime = permit.runtime_authority
        authority = permit.authority_generation
        if (
            type(runtime) is not MutationGate
            or type(authority) is not _OwnerIdentityAuthority
            or current_runtime() is not runtime
            or _registered_owner_identity_authority(runtime) is not authority
            or authority.binding is not permit.wallet_identity_binding
            or authority.wallet_adapter_authority is not permit.wallet_adapter_authority
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
        runtime.require_active_wallet_mutation_permit(permit.permit, operation)
        runtime.require_wallet_identity_authority(operation)
        runtime.require_wallet_adapter_authority(
            permit.wallet_adapter_authority, operation
        )
        runtime.require_allowed(operation)
        return permit.wallet_identity_binding, permit.wallet_adapter_authority
    if permit.mode != "worker" or permit.runtime_authority is not None:
        raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
    with _worker_authority_lock:
        generation = _worker_authority_generation
        binding = _worker_wallet_identity_binding
        registered = (
            _worker_wallet_adapter_authorities.get(id(binding))
            if binding is not None
            else None
        )
        environment = (
            dict(_worker_authority_environment)
            if _worker_authority_environment is not None
            else None
        )
        if (
            generation is None
            or generation is not permit.authority_generation
            or binding is not permit.wallet_identity_binding
            or type(registered) is not tuple
            or len(registered) != 2
            or registered[0] is not binding
            or registered[1] is not permit.wallet_adapter_authority
            or _worker_active_wallet_mutations.get(permit.permit)
            is not permit.authority_generation
            or environment is None
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
    require_worker_allowed_from_environment(operation, environment)
    with _worker_authority_lock:
        if (
            generation is not _worker_authority_generation
            or binding is not _worker_wallet_identity_binding
            or _worker_active_wallet_mutations.get(permit.permit)
            is not permit.authority_generation
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
    return permit.wallet_identity_binding, permit.wallet_adapter_authority


def wallet_mutation_permit_journal_authority(
    permit: Any, operation: str
) -> dict[str, Any]:
    """Return the exact non-secret authority generation held by one permit."""

    binding, _adapter = require_wallet_mutation_permit_authority(permit, operation)
    binding_digest = wallet_identity_binding_digest(binding)
    if permit.mode == "runtime":
        runtime = permit.runtime_authority
        authority = permit.authority_generation
        with runtime._lock:
            if (
                _registered_owner_identity_authority(runtime) is not authority
                or type(runtime._lease_version) is not int
                or runtime._lease_version <= 0
                or type(runtime._lease_acquired_at) is not str
                or not runtime._lease_acquired_at
                or type(authority.generation_digest) is not str
                or len(authority.generation_digest) != 64
            ):
                raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
            return {
                "mode": "runtime",
                "owner_run_id": runtime.run_id,
                "owner_pid": runtime.owner_pid,
                "owner_host": runtime.owner_host,
                "lease_version": runtime._lease_version,
                "lease_epoch": runtime._lease_acquired_at,
                "authority_generation_digest": authority.generation_digest,
                "binding_digest": binding_digest,
            }
    with _worker_authority_lock:
        environment = (
            dict(_worker_authority_environment)
            if _worker_authority_environment is not None
            else None
        )
        generation_digest = _worker_authority_generation_digest
        if (
            environment is None
            or _worker_authority_generation is not permit.authority_generation
            or type(generation_digest) is not str
            or len(generation_digest) != 64
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
        return {
            "mode": "worker",
            "delegation_id": environment[DELEGATION_ID_ENV],
            "parent_run_id": environment[DELEGATION_PARENT_RUN_ENV],
            "delegation_operation_id": environment[DELEGATION_OPERATION_ENV],
            "purpose": environment[DELEGATION_PURPOSE_ENV],
            "worker_id": environment[DELEGATION_WORKER_ENV],
            "parent_lease_epoch": environment[DELEGATION_PARENT_EPOCH_ENV],
            "authority_generation_digest": generation_digest,
            "binding_digest": binding_digest,
        }


def require_wallet_operation_continuation(
    permit: Any,
    operation: str,
    blocking_operation_id: str,
    blocking_intent_id: str,
) -> tuple[WalletIdentityBinding, Any]:
    """Revalidate one held permit while allowing only its own durable blocker."""

    safe_operation = _safe_operation(operation)
    blocker = _exact_text(blocking_operation_id, "blocking_operation_id")
    intent = _exact_text(blocking_intent_id, "blocking_intent_id")
    if (
        type(permit) is not WalletMutationPermit
        or type(permit.permit) is not str
        or not permit.permit
        or type(permit.wallet_identity_binding) is not WalletIdentityBinding
        or permit.wallet_adapter_authority is None
    ):
        raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
    if permit.mode == "runtime":
        runtime = permit.runtime_authority
        authority = permit.authority_generation
        if (
            type(runtime) is not MutationGate
            or type(authority) is not _OwnerIdentityAuthority
            or current_runtime() is not runtime
            or _registered_owner_identity_authority(runtime) is not authority
            or authority.binding is not permit.wallet_identity_binding
            or authority.wallet_adapter_authority is not permit.wallet_adapter_authority
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
        return runtime.require_operation_continuation(
            permit.permit,
            safe_operation,
            blocker,
            intent,
        )
    if permit.mode != "worker" or permit.runtime_authority is not None:
        raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
    with _worker_authority_lock:
        generation = _worker_authority_generation
        binding = _worker_wallet_identity_binding
        registered = (
            _worker_wallet_adapter_authorities.get(id(binding))
            if binding is not None
            else None
        )
        environment = (
            dict(_worker_authority_environment)
            if _worker_authority_environment is not None
            else None
        )
        valid = (
            generation is not None
            and generation is permit.authority_generation
            and binding is permit.wallet_identity_binding
            and type(registered) is tuple
            and len(registered) == 2
            and registered[0] is binding
            and registered[1] is permit.wallet_adapter_authority
            and _worker_active_wallet_mutations.get(permit.permit)
            is permit.authority_generation
            and environment is not None
            and environment[DELEGATION_OPERATION_ENV] == blocker
        )
    if not valid:
        raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
    result = _validate_worker_environment(
        environment,
        allowed_blocking_operation_id=blocker,
        allowed_blocking_intent_id=intent,
        allowed_blocking_wallet_operation=safe_operation,
    )
    if result.get("allowed") is not True:
        reason = (
            "WORKER_PARENT_LEASE_INVALID"
            if result.get("reason") in {"parent_lease_invalid", "parent_gate_blocked"}
            else "WORKER_DELEGATION_INVALID"
        )
        raise MutationBlocked(reason, safe_operation)
    with _worker_authority_lock:
        if (
            generation is not _worker_authority_generation
            or binding is not _worker_wallet_identity_binding
            or _worker_active_wallet_mutations.get(permit.permit)
            is not permit.authority_generation
            or _worker_authority_environment != environment
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
    return permit.wallet_identity_binding, permit.wallet_adapter_authority


def require_fresh_wallet_operation_continuation(
    permit: Any,
    snapshot: Any,
    operation: str,
    blocking_operation_id: str,
    blocking_intent_id: str,
) -> tuple[WalletIdentityBinding, Any, dict[str, Any]]:
    """Validate a fresh identity under one exact scoped continuation."""

    global _worker_identity_last_observed_at_utc
    safe_operation = _safe_operation(operation)
    blocker = _exact_text(blocking_operation_id, "blocking_operation_id")
    intent = _exact_text(blocking_intent_id, "blocking_intent_id")
    if type(permit) is not WalletMutationPermit:
        raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
    if permit.mode == "runtime":
        runtime = permit.runtime_authority
        authority = permit.authority_generation
        if (
            type(runtime) is not MutationGate
            or type(authority) is not _OwnerIdentityAuthority
            or current_runtime() is not runtime
            or _registered_owner_identity_authority(runtime) is not authority
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
        return runtime.require_fresh_operation_continuation(
            permit.permit,
            snapshot,
            safe_operation,
            blocker,
            intent,
        )
    binding, adapter = require_wallet_operation_continuation(
        permit,
        safe_operation,
        blocker,
        intent,
    )
    with _worker_authority_lock:
        last_observed = _worker_identity_last_observed_at_utc
        generation = _worker_authority_generation
        environment = (
            dict(_worker_authority_environment)
            if _worker_authority_environment is not None
            else None
        )
    decision = validate_wallet_identity(
        binding,
        snapshot,
        last_observed_at_utc=last_observed,
    )
    if decision.get("allowed") is not True:
        raise MutationBlocked(decision.get("reason"), safe_operation)
    require_wallet_operation_continuation(
        permit,
        f"{safe_operation}:dispatch",
        blocker,
        intent,
    )
    with _worker_authority_lock:
        if (
            generation is not _worker_authority_generation
            or environment != _worker_authority_environment
            or _worker_active_wallet_mutations.get(permit.permit)
            is not permit.authority_generation
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", safe_operation)
        _worker_identity_last_observed_at_utc = str(decision["observed_at_utc"])
    return binding, adapter, decision


def exit_wallet_mutation(permit: Any) -> bool:
    if type(permit) is not WalletMutationPermit:
        return False
    if permit.mode == "worker":
        with _worker_authority_lock:
            if (
                type(permit.permit) is not str
                or _worker_active_wallet_mutations.get(permit.permit)
                is not permit.authority_generation
            ):
                return False
            _worker_active_wallet_mutations.pop(permit.permit, None)
            return True
    if (
        permit.mode != "runtime"
        or permit.permit is None
        or type(permit.runtime_authority) is not MutationGate
    ):
        return False
    return permit.runtime_authority.exit_mutation(permit.permit)


def require_fresh_wallet_identity(
    binding: WalletIdentityBinding, snapshot: Any, operation: str
) -> dict[str, Any]:
    """Apply identity proof to the active owner or delegated worker."""

    runtime = current_runtime()
    if runtime is not None:
        authority = runtime.require_wallet_identity_authority(operation)
        if (
            type(binding) is not WalletIdentityBinding
            or wallet_identity_binding_digest(binding)
            != runtime.wallet_identity_binding_digest
            or authority != binding
        ):
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
        return runtime.require_fresh_wallet_identity(snapshot, operation)

    lease_binding = worker_identity_lease_binding()
    if lease_binding is None:
        raise MutationBlocked("MUTATION_RUNTIME_NOT_INITIALIZED", operation)
    try:
        binding_matches = (
            type(binding) is WalletIdentityBinding
            and wallet_identity_binding_digest(binding)
            == lease_binding["binding_digest"]
            and binding == lease_binding["binding"]
            and wallet_fingerprint_hash(binding.fingerprint)
            == lease_binding["wallet_fingerprint_hash"]
            and binding.network_id == lease_binding["network"].lower()
            and binding.bound_at_utc == lease_binding["bound_at_utc"]
        )
    except Exception:
        binding_matches = False
    if not binding_matches:
        raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
    with _worker_authority_lock:
        global _worker_identity_last_observed_at_utc
        decision = validate_wallet_identity(
            binding,
            snapshot,
            last_observed_at_utc=_worker_identity_last_observed_at_utc,
        )
        if decision.get("allowed") is not True:
            raise MutationBlocked(decision.get("reason"), operation)
        _worker_identity_last_observed_at_utc = str(decision["observed_at_utc"])
        return decision


def initialize(
    *,
    wallet_fingerprint_hash: str,
    network: str,
    run_id: Optional[str] = None,
    owner_pid: Optional[int] = None,
    owner_host: Optional[str] = None,
    lease_seconds: int = 30,
    start_heartbeat: bool = True,
    acquire_lease: bool = True,
    wallet_identity_binding: Optional[WalletIdentityBinding] = None,
    wallet_adapter_authority: Any = None,
) -> MutationGate:
    global _runtime
    with _runtime_lock:
        safe_pid = owner_pid or os.getpid()
        safe_host = owner_host or socket.gethostname()
        previous = _runtime
        if previous is not None:
            if previous.wallet_identity_binding is not None:
                previous.require_wallet_identity_authority("runtime:initialize")
            same_binding = (
                previous.owner_pid == safe_pid
                and previous.owner_host == safe_host
                and previous.wallet_fingerprint_hash == wallet_fingerprint_hash
                and previous.network == network
                and previous.lease_seconds == lease_seconds
                and previous.wallet_identity_binding == wallet_identity_binding
                and previous._wallet_adapter_authority is wallet_adapter_authority
                and (run_id is None or previous.run_id == run_id)
            )
            if not same_binding:
                raise RuntimeError(
                    "mutation runtime already initialized; call shutdown_runtime first"
                )
            if acquire_lease and not previous.last_acquire_result.get("acquired"):
                with previous._lock:
                    terminal_fence = (
                        previous._local_reason_code in _TERMINAL_PROCESS_FENCES
                    )
                if not terminal_fence:
                    acquired = previous.acquire()
                    if acquired.get("acquired"):
                        previous._read_only = False
            if (
                acquire_lease
                and start_heartbeat
                and previous.last_acquire_result.get("acquired")
            ):
                previous.start_heartbeat()
            return previous
        gate = MutationGate(
            run_id=run_id or str(uuid.uuid4()),
            owner_pid=safe_pid,
            owner_host=safe_host,
            wallet_fingerprint_hash=wallet_fingerprint_hash,
            network=network,
            lease_seconds=lease_seconds,
            read_only=not acquire_lease,
            wallet_identity_binding=wallet_identity_binding,
            wallet_adapter_authority=wallet_adapter_authority,
        )
        if acquire_lease:
            gate.acquire()
        if gate.last_acquire_result.get("acquired") and start_heartbeat:
            gate.start_heartbeat()
        _runtime = gate
    return gate


def current_runtime() -> Optional[MutationGate]:
    with _runtime_lock:
        return _runtime


def _uninitialized_status() -> GateStatus:
    return GateStatus(
        allowed=False,
        reason_code="MUTATION_RUNTIME_NOT_INITIALIZED",
        source="process",
    )


def status() -> GateStatus:
    runtime = current_runtime()
    return runtime.status() if runtime is not None else _uninitialized_status()


def read_only_status() -> GateStatus:
    """Read the live gate for diagnostics without changing process state."""

    runtime = current_runtime()
    return (
        runtime.read_only_status() if runtime is not None else _uninitialized_status()
    )


def require_allowed(operation: str) -> GateStatus:
    runtime = current_runtime()
    if runtime is None:
        raise MutationBlocked("MUTATION_RUNTIME_NOT_INITIALIZED", operation)
    return runtime.require_allowed(operation)


def enter_mutation(operation: str) -> str:
    runtime = current_runtime()
    if runtime is None:
        # Route/bridge tests and embedders have historically overridden the
        # module boundary. Preserve that boundary while still failing closed
        # when no override is installed.
        require_allowed(operation)
        raise MutationBlocked("MUTATION_RUNTIME_NOT_INITIALIZED", operation)
    return runtime.enter_mutation(operation)


def exit_mutation(permit: str) -> bool:
    runtime = current_runtime()
    return runtime.exit_mutation(permit) if runtime is not None else False


def trip(reason_code: str, blocking_operation_ids: list[str]) -> GateStatus:
    runtime = current_runtime()
    if runtime is None:
        raise MutationBlocked("MUTATION_RUNTIME_NOT_INITIALIZED", "trip")
    return runtime.trip(reason_code, blocking_operation_ids)


def release_resolved(
    expected_generation: int, resolved_operation_ids: list[str]
) -> dict[str, Any]:
    runtime = current_runtime()
    if runtime is None:
        return {
            "released": False,
            "reason": "mutation_runtime_not_initialized",
            "status": _uninitialized_status().to_dict(),
        }
    return runtime.release_resolved(expected_generation, resolved_operation_ids)


def shutdown_runtime(*, release_owned_lease: bool = False) -> dict[str, Any]:
    """Detach the process runtime, releasing only after explicit proof.

    The default is deliberately safe for ``atexit`` and diagnostic teardown:
    stop heartbeats but leave an active lease to expire.  The API's centralized
    quiescence path is the sole caller authorized to request a durable release.
    """

    global _runtime
    with _runtime_lock:
        runtime = _runtime
        if runtime is not None and runtime.active_wallet_mutation_count() > 0:
            return {
                "released": False,
                "reason": "active_wallet_mutations",
            }
        _runtime = None
    if runtime is None:
        return {"released": False, "reason": "not_initialized"}
    if release_owned_lease:
        return runtime.release_lease()
    runtime.stop_heartbeat()
    return {"released": False, "reason": "lease_retained"}


atexit.register(shutdown_runtime)


__all__ = [
    "DELEGATION_ID_ENV",
    "DELEGATION_IDENTITY_ENV",
    "DELEGATION_IDENTITY_DIGEST_ENV",
    "DELEGATION_NETWORK_ENV",
    "DELEGATION_OPERATION_ENV",
    "DELEGATION_PARENT_RUN_ENV",
    "DELEGATION_PURPOSE_ENV",
    "DELEGATION_PARENT_EPOCH_ENV",
    "DELEGATION_TOKEN_ENV",
    "DELEGATION_WALLET_ENV",
    "DELEGATION_WORKER_ENV",
    "GateStatus",
    "MutationBlocked",
    "MutationGate",
    "WalletIdentityBinding",
    "WalletMutationPermit",
    "clear_worker_authority_environment",
    "enter_mutation",
    "enter_wallet_mutation",
    "exit_mutation",
    "exit_wallet_mutation",
    "install_worker_authority_environment",
    "WorkerDelegation",
    "current_runtime",
    "initialize",
    "pid_liveness",
    "release_resolved",
    "require_allowed",
    "require_fresh_wallet_operation_continuation",
    "require_fresh_wallet_identity",
    "require_wallet_mutation_permit_authority",
    "require_wallet_operation_continuation",
    "require_worker_allowed_from_environment",
    "shutdown_runtime",
    "status",
    "read_only_status",
    "trip",
    "validate_wallet_identity",
    "validate_worker_environment",
    "wallet_fingerprint_hash",
    "wallet_identity_binding_digest",
    "wallet_identity_binding_payload",
    "wallet_mutation_permit_journal_authority",
    "worker_identity_lease_binding",
    "worker_wallet_adapter_authority",
]
