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

_DELEGATION_ENV_NAMES = (
    DELEGATION_ID_ENV,
    DELEGATION_TOKEN_ENV,
    DELEGATION_PARENT_RUN_ENV,
    DELEGATION_OPERATION_ENV,
    DELEGATION_PURPOSE_ENV,
    DELEGATION_WORKER_ENV,
    DELEGATION_WALLET_ENV,
    DELEGATION_NETWORK_ENV,
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
    ):
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
        self.wallet_identity_binding = wallet_identity_binding
        self._last_wallet_identity_observed_at_utc: Optional[str] = None
        self._lock = threading.RLock()
        self._mutation_condition = threading.Condition(self._lock)
        self._active_mutations: dict[str, str] = {}
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

    def _status_from_rows(
        self,
        latch: Mapping[str, Any],
        lease: Mapping[str, Any],
        unresolved: list[Mapping[str, Any]],
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
            self._set_local_block("LEASE_LOST")
            return result("LEASE_LOST", "lease")
        if not lease_active:
            return result("LEASE_UNAVAILABLE", "lease")
        if not owned:
            return result("LEASE_OWNED_BY_OTHER", "lease")
        if expected_version is None:
            self._set_local_block("LEASE_LOST")
            return result("LEASE_LOST", "lease")
        if lease_expiry is None or _as_utc(lease_expiry) <= self._now():
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

    def require_allowed(self, operation: str) -> GateStatus:
        current = self.status()
        if not current.allowed:
            raise MutationBlocked(current.reason_code, operation)
        return current

    def require_fresh_wallet_identity(
        self, snapshot: Any, operation: str
    ) -> dict[str, Any]:
        """Require a new exact identity observation under current lease authority."""

        safe_operation = _safe_operation(operation)
        with self._lock:
            self.require_allowed(safe_operation)
            decision = validate_wallet_identity(
                self.wallet_identity_binding,
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
            if self._quiescing:
                raise MutationBlocked("MUTATION_SHUTTING_DOWN", safe_operation)
            self.require_allowed(safe_operation)
            permit = str(uuid.uuid4())
            self._active_mutations[permit] = safe_operation
            return permit

    def exit_mutation(self, permit: str) -> bool:
        """Finish one exact guarded mutation permit."""

        if type(permit) is not str or not permit:
            return False
        with self._mutation_condition:
            removed = self._active_mutations.pop(permit, None) is not None
            if removed:
                self._mutation_condition.notify_all()
            return removed

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
                result = {"released": False, "reason": "durable_state_unavailable"}
            if result.get("released"):
                self._lease_version = None
            else:
                self._set_local_block("LEASE_LOST")
            return result

    @_stop_callback_boundary
    def issue_worker_delegation(
        self,
        *,
        operation_id: str,
        purpose: str,
        worker_id: str,
        ttl_seconds: int,
    ) -> WorkerDelegation:
        operation = _exact_text(operation_id, "operation_id")
        safe_purpose = _exact_text(purpose, "purpose", max_length=64)
        safe_worker = _exact_text(worker_id, "worker_id")
        ttl = _exact_positive_int(ttl_seconds, "ttl_seconds")
        if ttl > 3600:
            raise ValueError("ttl_seconds exceeds the maximum delegation lifetime")
        with self._lock:
            self.require_allowed(f"delegate:{safe_purpose}")
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
        if not isinstance(metadata, dict):
            return _invalid_worker()
        latch = authorization["latch"]
        if str(latch.get("state") or "") != "resolved":
            return _invalid_worker("parent_gate_blocked")
        if authorization["unresolved"]:
            return _invalid_worker("parent_gate_blocked")
        lease = authorization["lease"]
        expected = (
            True,
            values["parent_run_id"],
            values["wallet_fingerprint_hash"],
            values["network"],
            metadata.get("parent_pid"),
            metadata.get("parent_host"),
            metadata.get("parent_acquired_at"),
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
        }
    except Exception:
        return _invalid_worker()


def validate_worker_environment(
    environment: Mapping[str, str], *, now: Optional[datetime] = None
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
            now=_as_utc(now or _utc_now()),
        )
    except Exception:
        return _invalid_worker()


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


@dataclass(frozen=True)
class WalletMutationPermit:
    mode: str
    permit: Optional[str] = None


def install_worker_authority_environment(environment: Mapping[str, str]) -> None:
    """Retain a validated child delegation for fresh per-effect checks."""

    result = validate_worker_environment(environment)
    if result.get("allowed") is not True:
        raise MutationBlocked("WORKER_DELEGATION_INVALID", "worker.install")
    try:
        copied = {
            name: _exact_text(environment.get(name), name, max_length=512)
            for name in _DELEGATION_ENV_NAMES
        }
    except Exception as exc:
        raise MutationBlocked("WORKER_DELEGATION_INVALID", "worker.install") from exc
    with _worker_authority_lock:
        global _worker_authority_environment, _worker_authority_bound_at_utc
        global _worker_identity_last_observed_at_utc
        _worker_authority_environment = copied
        _worker_authority_bound_at_utc = _timestamp(_utc_now())
        _worker_identity_last_observed_at_utc = None


def clear_worker_authority_environment() -> None:
    with _worker_authority_lock:
        global _worker_authority_environment, _worker_authority_bound_at_utc
        global _worker_identity_last_observed_at_utc
        _worker_authority_environment = None
        _worker_authority_bound_at_utc = None
        _worker_identity_last_observed_at_utc = None


def worker_identity_lease_binding() -> Optional[dict[str, str]]:
    """Return only the non-token identity binding after fresh delegation proof."""

    with _worker_authority_lock:
        environment = (
            dict(_worker_authority_environment)
            if _worker_authority_environment is not None
            else None
        )
    if environment is None:
        return None
    require_worker_allowed_from_environment("wallet:identity", environment)
    with _worker_authority_lock:
        if (
            _worker_authority_environment != environment
            or _worker_authority_bound_at_utc is None
        ):
            return None
        return {
            "wallet_fingerprint_hash": environment[DELEGATION_WALLET_ENV],
            "network": environment[DELEGATION_NETWORK_ENV],
            "bound_at_utc": _worker_authority_bound_at_utc,
        }


def enter_wallet_mutation(operation: str) -> WalletMutationPermit:
    """Enter either an owned-runtime or delegated-worker mutation boundary."""

    runtime = current_runtime()
    if runtime is not None:
        return WalletMutationPermit("runtime", runtime.enter_mutation(operation))
    with _worker_authority_lock:
        environment = (
            dict(_worker_authority_environment)
            if _worker_authority_environment is not None
            else None
        )
    if environment is None:
        raise MutationBlocked("MUTATION_RUNTIME_NOT_INITIALIZED", operation)
    require_worker_allowed_from_environment(operation, environment)
    return WalletMutationPermit("worker")


def exit_wallet_mutation(permit: Any) -> bool:
    if type(permit) is not WalletMutationPermit:
        return False
    if permit.mode == "worker":
        return True
    if permit.mode != "runtime" or permit.permit is None:
        return False
    return exit_mutation(permit.permit)


def require_fresh_wallet_identity(
    binding: WalletIdentityBinding, snapshot: Any, operation: str
) -> dict[str, Any]:
    """Apply identity proof to the active owner or delegated worker."""

    runtime = current_runtime()
    if runtime is not None:
        if runtime.wallet_identity_binding != binding:
            raise MutationBlocked("WALLET_IDENTITY_BINDING_INVALID", operation)
        return runtime.require_fresh_wallet_identity(snapshot, operation)

    lease_binding = worker_identity_lease_binding()
    if lease_binding is None:
        raise MutationBlocked("MUTATION_RUNTIME_NOT_INITIALIZED", operation)
    try:
        binding_matches = (
            wallet_fingerprint_hash(binding.fingerprint)
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
) -> MutationGate:
    global _runtime
    with _runtime_lock:
        safe_pid = owner_pid or os.getpid()
        safe_host = owner_host or socket.gethostname()
        previous = _runtime
        if previous is not None:
            same_binding = (
                previous.owner_pid == safe_pid
                and previous.owner_host == safe_host
                and previous.wallet_fingerprint_hash == wallet_fingerprint_hash
                and previous.network == network
                and previous.lease_seconds == lease_seconds
                and previous.wallet_identity_binding == wallet_identity_binding
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
    "DELEGATION_NETWORK_ENV",
    "DELEGATION_OPERATION_ENV",
    "DELEGATION_PARENT_RUN_ENV",
    "DELEGATION_PURPOSE_ENV",
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
    "require_fresh_wallet_identity",
    "require_worker_allowed_from_environment",
    "shutdown_runtime",
    "status",
    "trip",
    "validate_wallet_identity",
    "validate_worker_environment",
    "wallet_fingerprint_hash",
    "worker_identity_lease_binding",
]
