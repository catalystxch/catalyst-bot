"""Pure policy for durable Dexie/Splash offer publication.

This module deliberately has no database, network, environment, or clock imports.
Callers provide already-observed timestamps to repository functions in
``database.py`` and perform remote effects only after a durable claim commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any


_NETWORK_RE = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}\Z")
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}\Z")
_EPOCH_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,255}\Z")


class PublicationState(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    SUPPRESSED = "suppressed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class PublicationIdentity:
    network: str
    offer_fingerprint: str
    publication_epoch: str
    idempotency_key: str


@dataclass(frozen=True)
class PublicationDecision:
    state: PublicationState
    evidence: dict[str, Any]


def _exact_matching_text(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be exact text")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{label} is not canonical")
    return value


def canonical_publication_identity(
    network: Any, offer_fingerprint: Any, publication_epoch: Any
) -> PublicationIdentity:
    """Validate and return the exact durable publication identity tuple."""

    safe_network = _exact_matching_text(network, _NETWORK_RE, "network")
    safe_fingerprint = _exact_matching_text(
        offer_fingerprint, _FINGERPRINT_RE, "offer_fingerprint"
    )
    safe_epoch = _exact_matching_text(publication_epoch, _EPOCH_RE, "publication_epoch")
    return PublicationIdentity(
        network=safe_network,
        offer_fingerprint=safe_fingerprint,
        publication_epoch=safe_epoch,
        idempotency_key=f"{safe_network}:{safe_fingerprint}:{safe_epoch}",
    )


def _bounded_request_text(value: Any, label: str, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ValueError(f"{label} must be bounded exact text")
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} is not canonical")
    return value


def canonical_publication_request_contract(
    *,
    publisher: Any,
    offer_bech32: Any,
    idempotency_key: Any,
    destination_url: Any,
    claim_rewards: Any = None,
    bot_tag: Any = None,
) -> dict[str, Any]:
    """Build the complete bounded contract used for digest and transport."""

    safe_publisher = _exact_matching_text(
        publisher, re.compile(r"(?:dexie|splash)\Z"), "publisher"
    )
    if type(offer_bech32) is not str or not offer_bech32.startswith("offer1"):
        raise ValueError("offer_bech32 must be exact canonical offer text")
    encoded_offer = offer_bech32.encode("utf-8")
    if len(encoded_offer) > 2 * 1024 * 1024:
        raise ValueError("offer_bech32 exceeds its byte limit")
    safe_key = _bounded_request_text(idempotency_key, "idempotency_key", 512)
    destination = _bounded_request_text(destination_url, "destination_url", 2048)
    if not destination.startswith(("https://", "http://")):
        raise ValueError("destination_url must use HTTP or HTTPS")
    if safe_publisher == "dexie":
        if type(claim_rewards) is not bool:
            raise TypeError("claim_rewards must be an exact bool for Dexie")
        safe_bot_tag = _bounded_request_text(bot_tag, "bot_tag", 128)
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "idempotency-key": safe_key,
            "x-bot-tag": safe_bot_tag,
        }
        body = {"claim_rewards": claim_rewards, "offer": offer_bech32}
    else:
        if claim_rewards is not None or bot_tag is not None:
            raise ValueError("Splash request contract rejects Dexie-only fields")
        headers = {
            "content-type": "application/json",
            "idempotency-key": safe_key,
        }
        body = {"offer": offer_bech32}
    return {
        "body": body,
        "destination_url": destination,
        "headers": headers,
        "method": "POST",
        "publisher": safe_publisher,
        "schema_version": 1,
    }


def publication_request_sha256(contract: Any) -> str:
    """Validate and digest one complete canonical outbound request contract."""

    if type(contract) is not dict or set(contract) != {
        "body",
        "destination_url",
        "headers",
        "method",
        "publisher",
        "schema_version",
    }:
        raise ValueError("canonical request contract fields are invalid")
    if (
        type(contract.get("method")) is not str
        or contract.get("method") != "POST"
        or type(contract.get("schema_version")) is not int
        or contract.get("schema_version") != 1
    ):
        raise ValueError("canonical request contract version is invalid")
    body = contract.get("body")
    headers = contract.get("headers")
    if type(body) is not dict or type(headers) is not dict:
        raise ValueError("canonical request contract mappings are invalid")
    publisher = contract.get("publisher")
    if publisher == "dexie":
        if set(body) != {"claim_rewards", "offer"} or set(headers) != {
            "accept",
            "content-type",
            "idempotency-key",
            "x-bot-tag",
        }:
            raise ValueError("canonical request contract shape is invalid")
        rebuilt = canonical_publication_request_contract(
            publisher=publisher,
            offer_bech32=body.get("offer"),
            idempotency_key=headers.get("idempotency-key"),
            destination_url=contract.get("destination_url"),
            claim_rewards=body.get("claim_rewards"),
            bot_tag=headers.get("x-bot-tag"),
        )
    elif publisher == "splash":
        if set(body) != {"offer"} or set(headers) != {
            "content-type",
            "idempotency-key",
        }:
            raise ValueError("canonical request contract shape is invalid")
        rebuilt = canonical_publication_request_contract(
            publisher=publisher,
            offer_bech32=body.get("offer"),
            idempotency_key=headers.get("idempotency-key"),
            destination_url=contract.get("destination_url"),
        )
    else:
        raise ValueError("canonical request contract publisher is invalid")
    if rebuilt != contract:
        raise ValueError("canonical request contract is not normalized")
    material = json.dumps(
        contract,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def provider_response_sha256(response_body: Any) -> str:
    """Digest one bounded exact response body without retaining its content."""

    if type(response_body) is not bytes:
        raise TypeError("provider response body must be exact bytes")
    if len(response_body) > 65536:
        raise ValueError("provider response body exceeds its byte limit")
    return hashlib.sha256(response_body).hexdigest()


def classify_provider_result(
    *,
    publisher: Any,
    result: Any,
    expected_idempotency_key: Any,
    expected_request_sha256: Any,
) -> PublicationDecision:
    """Classify a synchronous provider result without performing side effects."""

    safe_publisher = _exact_matching_text(
        publisher, re.compile(r"(?:dexie|splash)\Z"), "publisher"
    )
    if type(expected_idempotency_key) is not str or not expected_idempotency_key:
        raise ValueError("expected_idempotency_key must be exact text")
    expected_request = _exact_matching_text(
        expected_request_sha256,
        _FINGERPRINT_RE,
        "expected_request_sha256",
    )

    def unresolved(code: str) -> PublicationDecision:
        return PublicationDecision(
            PublicationState.UNRESOLVED,
            {
                "code": code,
                "provider": safe_publisher,
                "request_sha256": expected_request,
            },
        )

    if type(result) is not dict:
        return unresolved("MALFORMED_PROVIDER_RESULT")
    if result.get("provider") != safe_publisher:
        return unresolved("PROVIDER_BINDING_MISMATCH")
    if result.get("request_sha256") != expected_request:
        return unresolved("REQUEST_BINDING_MISMATCH")
    outcome = result.get("outcome")
    if outcome == "acknowledged":
        status = result.get("status_code")
        provider_id = result.get("provider_response_id")
        response_digest = result.get("response_sha256")
        echo = result.get("echoed_idempotency_key")
        splash_http_ack = (
            safe_publisher == "splash"
            and type(status) is int
            and 200 <= status < 300
            and provider_id is None
            and type(response_digest) is str
            and _FINGERPRINT_RE.fullmatch(response_digest) is not None
        )
        if splash_http_ack:
            # The local Splash daemon acknowledges acceptance with HTTP 2xx
            # but, unlike Dexie, does not return a durable remote offer ID.
            # Bind that protocol acknowledgement to the exact response bytes
            # so it can cross CATalyst's local durability boundary without a
            # duplicate redispatch on restart.
            provider_id = f"splash-http-{status}:{response_digest}"
        if (
            type(status) is not int
            or not 200 <= status < 300
            or type(provider_id) is not str
            or not provider_id
            or len(provider_id) > 256
            or any(ord(character) < 33 for character in provider_id)
            or type(response_digest) is not str
            or _FINGERPRINT_RE.fullmatch(response_digest) is None
        ):
            return unresolved("MALFORMED_PROVIDER_ACKNOWLEDGEMENT")
        if echo is not None and echo != expected_idempotency_key:
            return unresolved("IDEMPOTENCY_ECHO_MISMATCH")
        return PublicationDecision(
            PublicationState.SUCCEEDED,
            {
                "code": (
                    "SPLASH_HTTP_ACCEPTED"
                    if splash_http_ack
                    else "SYNCHRONOUS_PROVIDER_ACKNOWLEDGEMENT"
                ),
                "provider": safe_publisher,
                "provider_response_id": provider_id,
                "request_sha256": expected_request,
                "response_sha256": response_digest,
                "status_code": status,
            },
        )
    if outcome == "no_effect":
        status = result.get("status_code")
        response_digest = result.get("response_sha256")
        reason = result.get("reason_code")
        if (
            result.get("acceptance") is not False
            or type(status) is not int
            or not 400 <= status < 500
            or type(response_digest) is not str
            or _FINGERPRINT_RE.fullmatch(response_digest) is None
            or type(reason) is not str
            or not reason
        ):
            return unresolved("NO_EFFECT_PROOF_INVALID")
        evidence = {
            "code": reason[:128],
            "provider": safe_publisher,
            "request_sha256": expected_request,
            "response_sha256": response_digest,
            "status_code": status,
        }
        if status == 429 or (status == 400 and reason == "INVALID_OFFER"):
            return PublicationDecision(PublicationState.RETRYABLE, evidence)
        return PublicationDecision(PublicationState.UNRESOLVED, evidence)
    return unresolved(
        result.get("reason_code")
        if type(result.get("reason_code")) is str and result.get("reason_code")
        else "AMBIGUOUS_PROVIDER_RESULT"
    )


_TRANSITIONS = {
    PublicationState.QUEUED: frozenset(
        {
            PublicationState.CLAIMED,
            PublicationState.SUPPRESSED,
            PublicationState.UNRESOLVED,
        }
    ),
    PublicationState.CLAIMED: frozenset(
        {
            PublicationState.SUCCEEDED,
            PublicationState.RETRYABLE,
            PublicationState.SUPPRESSED,
            PublicationState.UNRESOLVED,
        }
    ),
    PublicationState.RETRYABLE: frozenset(
        {
            PublicationState.CLAIMED,
            PublicationState.SUPPRESSED,
            PublicationState.UNRESOLVED,
        }
    ),
    PublicationState.SUCCEEDED: frozenset(),
    PublicationState.SUPPRESSED: frozenset(),
    PublicationState.UNRESOLVED: frozenset(),
}


def transition_publication(source: Any, destination: Any) -> PublicationState:
    """Authorize one publication transition or fail closed."""

    if (
        type(source) is not PublicationState
        or type(destination) is not PublicationState
    ):
        raise TypeError("publication transitions require exact PublicationState values")
    if destination not in _TRANSITIONS[source]:
        raise ValueError(
            f"publication transition {source.value}->{destination.value} is forbidden"
        )
    return destination


def deterministic_retry_delay(attempt: Any) -> int:
    """Return bounded exponential retry seconds for an exact attempt number."""

    if type(attempt) is not int:
        raise TypeError("attempt must be an exact integer")
    if attempt < 1:
        raise ValueError("attempt must be positive")
    return min(3600, 5 * (2 ** min(attempt - 1, 10)))


def retry_timestamp(observed_at: Any, attempt: Any) -> str:
    """Add deterministic backoff to an injected canonical UTC timestamp."""

    if type(observed_at) is not str or not observed_at.endswith("Z"):
        raise ValueError("observed_at must be canonical UTC text")
    try:
        parsed = datetime.fromisoformat(observed_at[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("observed_at must be canonical UTC text") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("observed_at must be UTC")
    delayed = parsed.astimezone(timezone.utc) + timedelta(
        seconds=deterministic_retry_delay(attempt)
    )
    return delayed.isoformat(timespec="microseconds").replace("+00:00", "Z")


_SENSITIVE_EVIDENCE_KEYS = (
    "offer",
    "authorization",
    "credential",
    "secret",
    "token",
    "private",
)
_MAX_EVIDENCE_TEXT = 1024
_MAX_EVIDENCE_ITEMS = 64
_MAX_EVIDENCE_DEPTH = 6


def redact_publication_evidence(value: Any, *, _depth: int = 0) -> Any:
    """Return a bounded JSON-safe evidence tree without offer or secret text."""

    if _depth > _MAX_EVIDENCE_DEPTH:
        return "[depth-limit]"
    if type(value) is dict:
        redacted = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_EVIDENCE_ITEMS:
                redacted["truncated"] = True
                break
            if type(key) is not str:
                continue
            safe_key = key[:128]
            lowered = safe_key.lower()
            if any(marker in lowered for marker in _SENSITIVE_EVIDENCE_KEYS):
                redacted[safe_key] = "[redacted]"
            else:
                redacted[safe_key] = redact_publication_evidence(
                    item, _depth=_depth + 1
                )
        return redacted
    if type(value) in {list, tuple}:
        return [
            redact_publication_evidence(item, _depth=_depth + 1)
            for item in value[:_MAX_EVIDENCE_ITEMS]
        ]
    if type(value) is str:
        text = value[:_MAX_EVIDENCE_TEXT]
        offer_index = text.lower().find("offer1")
        if offer_index >= 0:
            return text[:offer_index] + "[redacted-offer]"
        return text
    if type(value) in {int, bool} or value is None:
        return value
    return f"[{type(value).__name__}]"
