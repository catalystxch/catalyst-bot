"""Pure policy for durable Dexie/Splash offer publication.

This module deliberately has no database, network, environment, or clock imports.
Callers provide already-observed timestamps to repository functions in
``database.py`` and perform remote effects only after a durable claim commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
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
    safe_epoch = _exact_matching_text(
        publication_epoch, _EPOCH_RE, "publication_epoch"
    )
    return PublicationIdentity(
        network=safe_network,
        offer_fingerprint=safe_fingerprint,
        publication_epoch=safe_epoch,
        idempotency_key=f"{safe_network}:{safe_fingerprint}:{safe_epoch}",
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

    if type(source) is not PublicationState or type(destination) is not PublicationState:
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
