"""One-time, identity-bound Sage WalletConnect message-signing requests.

This module never exposes offer, coin-spend, send, or cancellation methods.
The browser transports the single allowed WalletConnect message method while
Python owns request authority, expiry, identity checks, and BLS verification.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
import threading
from typing import Any, Callable

from bootstrap_manifest import (
    SIGNATURE_ALGORITHM,
    ManifestError,
    canonical_manifest_bytes,
    verify_campaign_manifest,
)


WALLETCONNECT_METHOD = "chia_signMessageByAddress"


class SigningError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class WalletIdentity:
    wallet_type: str
    fingerprint: int
    network: str
    signing_address: str

    @property
    def account(self) -> str:
        return f"chia:{self.network}:{self.fingerprint}"

    @property
    def chain(self) -> str:
        return f"chia:{self.network}"


@dataclass(frozen=True)
class SigningRequest:
    request_id: str
    purpose: str
    method: str
    required_methods: tuple[str, ...]
    account: str
    chain: str
    signing_address: str
    message: str
    message_digest: str
    created_at: datetime
    expires_at: datetime

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "purpose": self.purpose,
            "method": self.method,
            "required_methods": list(self.required_methods),
            "account": self.account,
            "chain": self.chain,
            "signing_address": self.signing_address,
            "message": self.message,
            "message_digest": self.message_digest,
            "created_at": _timestamp(self.created_at),
            "expires_at": _timestamp(self.expires_at),
        }


@dataclass
class _PendingRequest:
    request: SigningRequest
    manifest: dict[str, Any]
    identity: WalletIdentity


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _validate_identity(identity: Any) -> WalletIdentity:
    if not isinstance(identity, WalletIdentity):
        raise SigningError("invalid_wallet_identity")
    if identity.wallet_type.lower() != "sage":
        raise SigningError("sage_wallet_required")
    if type(identity.fingerprint) is not int or identity.fingerprint <= 0:
        raise SigningError("invalid_wallet_fingerprint")
    if identity.network not in {"mainnet", "testnet"}:
        raise SigningError("invalid_wallet_network")
    prefix = "xch1" if identity.network == "mainnet" else "txch1"
    if (
        type(identity.signing_address) is not str
        or not identity.signing_address.startswith(prefix)
        or re.fullmatch(r"(?:xch|txch)1[0-9a-z]{20,90}", identity.signing_address)
        is None
    ):
        raise SigningError("invalid_signing_address")
    return identity


class WalletConnectSigningService:
    """Own non-financial WalletConnect request state for one app process."""

    def __init__(
        self,
        *,
        project_id: str,
        identity_reader: Callable[[], WalletIdentity],
        clock: Callable[[], datetime] | None = None,
        request_ttl: timedelta = timedelta(minutes=2),
    ):
        self._project_id = project_id.strip() if type(project_id) is str else ""
        self._identity_reader = identity_reader
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._request_ttl = request_ttl
        self._lock = threading.RLock()
        self._pending: dict[str, _PendingRequest] = {}

    @property
    def pending_request_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _recheck(self, expected: WalletIdentity) -> WalletIdentity:
        try:
            actual = _validate_identity(self._identity_reader())
        except SigningError:
            raise
        except Exception as exc:
            raise SigningError("wallet_identity_unavailable") from exc
        if actual != expected:
            raise SigningError("wallet_identity_changed")
        return actual

    def begin_manifest_signature(
        self, manifest: dict[str, Any], identity: WalletIdentity
    ) -> SigningRequest:
        if not self._project_id:
            raise SigningError("walletconnect_project_id_missing")
        expected = _validate_identity(identity)
        self._recheck(expected)
        try:
            message = canonical_manifest_bytes(manifest)
        except ManifestError as exc:
            raise SigningError(exc.code) from exc
        now = self._clock().astimezone(timezone.utc)
        request = SigningRequest(
            request_id=secrets.token_hex(16),
            purpose="bootstrap_manifest",
            method=WALLETCONNECT_METHOD,
            required_methods=(WALLETCONNECT_METHOD,),
            account=expected.account,
            chain=expected.chain,
            signing_address=expected.signing_address,
            message=f"0x{message.hex()}",
            message_digest=hashlib.sha256(message).hexdigest(),
            created_at=now,
            expires_at=now + self._request_ttl,
        )
        with self._lock:
            self._pending[request.request_id] = _PendingRequest(
                request=request,
                manifest=deepcopy(manifest),
                identity=expected,
            )
        return request

    def complete_manifest_signature(
        self,
        request_id: str,
        response: dict[str, Any],
        identity: WalletIdentity,
    ) -> dict[str, Any]:
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            raise SigningError("signing_request_not_pending")
        now = self._clock().astimezone(timezone.utc)
        if now > pending.request.expires_at:
            raise SigningError("signing_request_expired")
        expected = _validate_identity(identity)
        if expected != pending.identity:
            raise SigningError("wallet_identity_changed")
        self._recheck(expected)
        if type(response) is not dict:
            raise SigningError("invalid_walletconnect_response")
        checks = (
            ("requestId", pending.request.request_id, "signing_request_id_mismatch"),
            ("account", pending.request.account, "walletconnect_account_mismatch"),
            ("address", pending.request.signing_address, "signing_address_mismatch"),
            (
                "messageDigest",
                pending.request.message_digest,
                "message_digest_mismatch",
            ),
        )
        for field, required, code in checks:
            if response.get(field) != required:
                raise SigningError(code)
        signed = {
            "manifest": deepcopy(pending.manifest),
            "signature": {
                "algorithm": SIGNATURE_ALGORITHM,
                "signing_address": pending.request.signing_address,
                "public_key": response.get("publicKey"),
                "signature": response.get("signature"),
                "message_digest": pending.request.message_digest,
            },
        }
        verification = verify_campaign_manifest(signed)
        if verification.status != "VERIFIED":
            raise SigningError(verification.reason_code or "signature_invalid")
        return signed

    def fail_request(self, request_id: str, reason: str) -> None:
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            raise SigningError("signing_request_not_pending")
        codes = {
            "user_rejected": "walletconnect_user_rejected",
            "timeout": "walletconnect_timeout",
            "disconnected": "walletconnect_disconnected",
        }
        raise SigningError(codes.get(reason, "walletconnect_request_failed"))
