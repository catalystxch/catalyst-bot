"""Pure offer-registry state and mutation authorization policy.

The registry database is deliberately outside this module.  Callers load rows
through :mod:`database`, convert them to immutable records, evaluate policy,
then use a narrow database function to persist an authorized result.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class RegistryState(StrEnum):
    PREPARED = "prepared"
    SUBMITTED_UNCONFIRMED = "submitted_unconfirmed"
    CREATED = "created"
    VISIBLE = "visible"
    CANCEL_REQUESTED = "cancel_requested"
    TERMINAL = "terminal"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"
    QUARANTINED = "quarantined"


class MutationKind(StrEnum):
    CREATE = "create"
    CANCEL = "cancel"
    REPLACE = "replace"
    PUBLISH = "publish"


class TerminalOutcome(StrEnum):
    CREATION_FAILED = "creation_failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FILLED = "filled"
    EXPIRED = "expired"


class EvidenceSource(StrEnum):
    AUTHORITATIVE_WALLET = "authoritative_wallet"
    EXACT_TRANSACTION = "exact_transaction"
    EXACT_COIN_SPEND = "exact_coin_spend"
    FULL_WALLET_HISTORY = "full_wallet_history"
    THIRD_PARTY_OBSERVATION = "third_party_observation"


class AuthorizationCode(StrEnum):
    ALLOWED = "allowed"
    IDEMPOTENT = "idempotent"
    INVALID_INPUT = "invalid_input"
    INVALID_TRANSITION = "invalid_transition"
    NOT_REGISTERED = "not_registered"
    AMBIGUOUS_MATCH = "ambiguous_match"
    REFERENCE_MISMATCH = "reference_mismatch"
    PROTECTED_OFFER = "protected_offer"
    NOT_OWNED = "not_owned"
    WALLET_MISMATCH = "wallet_mismatch"
    NETWORK_MISMATCH = "network_mismatch"
    REGISTRY_BLOCKED = "registry_blocked"
    INVALID_MUTATION_STATE = "invalid_mutation_state"
    DUPLICATE_ACTIVE_SLOT = "duplicate_active_slot"
    MISSING_SELECTED_COINS = "missing_selected_coins"
    SELECTED_COINS_MISMATCH = "selected_coins_mismatch"
    INVALID_LINEAGE = "invalid_lineage"
    REPLACEMENT_CHILD_NOT_VISIBLE = "replacement_child_not_visible"
    TERMINAL_PROOF_REQUIRED = "terminal_proof_required"
    TERMINAL_PROOF_INSUFFICIENT = "terminal_proof_insufficient"
    RECONCILIATION_EVIDENCE_REQUIRED = "reconciliation_evidence_required"
    QUARANTINE_PROOF_REQUIRED = "quarantine_proof_required"
    EVIDENCE_MISMATCH = "evidence_mismatch"


_HEX_DIGITS = frozenset("0123456789abcdef")
_BLOCKING_STATES = frozenset(
    {RegistryState.UNKNOWN, RegistryState.CONFLICTED, RegistryState.QUARANTINED}
)
_ACTIVE_SLOT_STATES = frozenset(
    state for state in RegistryState if state != RegistryState.TERMINAL
)


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _optional_text(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    return _required_text(value, label)


def _hex_identity(value: Any, label: str) -> str:
    text = _required_text(value, label).lower()
    if len(text) != 64 or any(character not in _HEX_DIGITS for character in text):
        raise ValueError(f"{label} must be a 32-byte hex identity")
    return text


def _optional_hex_identity(value: Any, label: str) -> Optional[str]:
    return None if value is None else _hex_identity(value, label)


def _atomic_amount(value: Any, label: str) -> str:
    if type(value) is int:
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise ValueError(f"{label} must be a positive atomic integer")
    if not text or not text.isascii() or not text.isdigit() or int(text) <= 0:
        raise ValueError(f"{label} must be a positive atomic integer")
    return text


def _coin_ids(values: Any) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("selected_coin_ids must be a collection of coin identities")
    try:
        normalized = tuple(
            sorted({_hex_identity(value, "selected coin id") for value in values})
        )
    except TypeError as exc:
        raise ValueError(
            "selected_coin_ids must be a collection of coin identities"
        ) from exc
    return normalized


@dataclass(frozen=True, slots=True)
class OfferRecord:
    """One immutable registry row returned by the database boundary."""

    intent_id: str
    run_id: str
    wallet_fingerprint_hash: str
    network: str
    asset_id: str
    side: str
    tier: str
    purpose: str
    slot_key: Optional[str]
    generation: int
    parent_intent_id: Optional[str]
    child_intent_id: Optional[str]
    offered_amount_atomic: str | int
    requested_amount_atomic: str | int
    selected_coin_ids: tuple[str, ...]
    offer_text_sha256: Optional[str]
    sage_trade_id: Optional[str]
    state: RegistryState
    owned: bool = True
    protected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "intent_id", _required_text(self.intent_id, "intent_id")
        )
        object.__setattr__(self, "run_id", _required_text(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "wallet_fingerprint_hash",
            _hex_identity(self.wallet_fingerprint_hash, "wallet_fingerprint_hash"),
        )
        object.__setattr__(self, "network", _required_text(self.network, "network"))
        object.__setattr__(self, "asset_id", _required_text(self.asset_id, "asset_id"))
        safe_side = _required_text(self.side, "side").lower()
        if safe_side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        object.__setattr__(self, "side", safe_side)
        object.__setattr__(self, "tier", _required_text(self.tier, "tier"))
        object.__setattr__(self, "purpose", _required_text(self.purpose, "purpose"))
        object.__setattr__(self, "slot_key", _optional_text(self.slot_key, "slot_key"))
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        object.__setattr__(
            self,
            "parent_intent_id",
            _optional_text(self.parent_intent_id, "parent_intent_id"),
        )
        object.__setattr__(
            self,
            "child_intent_id",
            _optional_text(self.child_intent_id, "child_intent_id"),
        )
        if (
            self.parent_intent_id == self.intent_id
            or self.child_intent_id == self.intent_id
        ):
            raise ValueError("an offer cannot be its own parent or child")
        object.__setattr__(
            self,
            "offered_amount_atomic",
            _atomic_amount(self.offered_amount_atomic, "offered_amount_atomic"),
        )
        object.__setattr__(
            self,
            "requested_amount_atomic",
            _atomic_amount(self.requested_amount_atomic, "requested_amount_atomic"),
        )
        object.__setattr__(self, "selected_coin_ids", _coin_ids(self.selected_coin_ids))
        object.__setattr__(
            self,
            "offer_text_sha256",
            _optional_hex_identity(self.offer_text_sha256, "offer_text_sha256"),
        )
        object.__setattr__(
            self,
            "sage_trade_id",
            _optional_hex_identity(self.sage_trade_id, "sage_trade_id"),
        )
        if not isinstance(self.state, RegistryState):
            raise ValueError("state must be a RegistryState")
        if type(self.owned) is not bool or type(self.protected) is not bool:
            raise ValueError("owned and protected must be booleans")


@dataclass(frozen=True, slots=True)
class OfferReference:
    intent_id: Optional[str] = None
    sage_trade_id: Optional[str] = None
    offer_text_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "intent_id", _optional_text(self.intent_id, "reference intent_id")
        )
        object.__setattr__(
            self,
            "sage_trade_id",
            _optional_hex_identity(self.sage_trade_id, "reference sage_trade_id"),
        )
        object.__setattr__(
            self,
            "offer_text_sha256",
            _optional_hex_identity(
                self.offer_text_sha256, "reference offer_text_sha256"
            ),
        )


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    records: tuple[OfferRecord, ...]
    protected_sage_trade_ids: frozenset[str] = frozenset()
    protected_offer_hashes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.records, (str, bytes)):
            raise ValueError("records must be a collection of OfferRecord values")
        try:
            records = tuple(self.records)
        except TypeError as exc:
            raise ValueError(
                "records must be a collection of OfferRecord values"
            ) from exc
        if any(not isinstance(record, OfferRecord) for record in records):
            raise ValueError("records must contain only OfferRecord values")
        object.__setattr__(self, "records", records)
        object.__setattr__(
            self,
            "protected_sage_trade_ids",
            frozenset(
                _hex_identity(value, "protected Sage trade id")
                for value in self.protected_sage_trade_ids
            ),
        )
        object.__setattr__(
            self,
            "protected_offer_hashes",
            frozenset(
                _hex_identity(value, "protected offer hash")
                for value in self.protected_offer_hashes
            ),
        )


@dataclass(frozen=True, slots=True)
class MutationRequest:
    kind: MutationKind
    reference: OfferReference
    wallet_fingerprint_hash: str
    network: str
    selected_coin_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MutationKind):
            raise ValueError("kind must be a MutationKind")
        if not isinstance(self.reference, OfferReference):
            raise ValueError("reference must be an OfferReference")
        object.__setattr__(
            self,
            "wallet_fingerprint_hash",
            _hex_identity(self.wallet_fingerprint_hash, "wallet_fingerprint_hash"),
        )
        object.__setattr__(self, "network", _required_text(self.network, "network"))
        object.__setattr__(self, "selected_coin_ids", _coin_ids(self.selected_coin_ids))


@dataclass(frozen=True, slots=True)
class OfferEvidence:
    """Exact evidence for reconciliation or a terminal classification."""

    observed_state: RegistryState
    terminal_outcome: Optional[TerminalOutcome]
    source: EvidenceSource
    intent_id: str
    wallet_fingerprint_hash: str
    network: str
    offered_amount_atomic: str | int
    requested_amount_atomic: str | int
    selected_coin_ids: tuple[str, ...]
    sage_trade_id: Optional[str]
    offer_text_sha256: Optional[str]
    observed_at: str
    transaction_id: Optional[str] = None
    spend_identity: Optional[str] = None
    block_height: Optional[int] = None
    full_history: bool = False
    input_coins_owned_unlocked: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.observed_state, RegistryState):
            raise ValueError("observed_state must be a RegistryState")
        if self.terminal_outcome is not None and not isinstance(
            self.terminal_outcome, TerminalOutcome
        ):
            raise ValueError("terminal_outcome must be a TerminalOutcome")
        if not isinstance(self.source, EvidenceSource):
            raise ValueError("source must be an EvidenceSource")
        object.__setattr__(
            self, "intent_id", _required_text(self.intent_id, "intent_id")
        )
        object.__setattr__(
            self,
            "wallet_fingerprint_hash",
            _hex_identity(self.wallet_fingerprint_hash, "wallet_fingerprint_hash"),
        )
        object.__setattr__(self, "network", _required_text(self.network, "network"))
        object.__setattr__(
            self,
            "offered_amount_atomic",
            _atomic_amount(self.offered_amount_atomic, "offered_amount_atomic"),
        )
        object.__setattr__(
            self,
            "requested_amount_atomic",
            _atomic_amount(self.requested_amount_atomic, "requested_amount_atomic"),
        )
        object.__setattr__(self, "selected_coin_ids", _coin_ids(self.selected_coin_ids))
        object.__setattr__(
            self,
            "sage_trade_id",
            _optional_hex_identity(self.sage_trade_id, "sage_trade_id"),
        )
        object.__setattr__(
            self,
            "offer_text_sha256",
            _optional_hex_identity(self.offer_text_sha256, "offer_text_sha256"),
        )
        object.__setattr__(
            self, "observed_at", _required_text(self.observed_at, "observed_at")
        )
        object.__setattr__(
            self,
            "transaction_id",
            _optional_text(self.transaction_id, "transaction_id"),
        )
        object.__setattr__(
            self,
            "spend_identity",
            _optional_text(self.spend_identity, "spend_identity"),
        )
        if self.block_height is not None and (
            type(self.block_height) is not int or self.block_height < 0
        ):
            raise ValueError("block_height must be a non-negative integer")
        if (
            type(self.full_history) is not bool
            or type(self.input_coins_owned_unlocked) is not bool
        ):
            raise ValueError("evidence flags must be booleans")


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    code: AuthorizationCode
    reason: str
    record: Optional[OfferRecord] = None
    idempotent: bool = False


_PERSISTED_STATE_ALIASES = {
    "creation_unknown": RegistryState.UNKNOWN,
    "creation_failed": RegistryState.TERMINAL,
}


def offer_record_from_row(
    row: Any, *, owned: bool = True, protected: bool = False
) -> OfferRecord:
    """Adapt one Task 3 ``offer_intents`` row to an immutable policy record."""

    if not isinstance(row, Mapping):
        raise ValueError("offer intent row must be a mapping")
    coin_json = row.get("selected_coin_ids_json")
    if not isinstance(coin_json, str):
        raise ValueError("selected_coin_ids_json must be canonical JSON text")
    try:
        coin_ids = json.loads(coin_json)
    except (TypeError, ValueError) as exc:
        raise ValueError("selected_coin_ids_json must contain valid JSON") from exc
    if not isinstance(coin_ids, list):
        raise ValueError("selected_coin_ids_json must contain a JSON array")
    raw_state = row.get("lifecycle_state")
    if not isinstance(raw_state, str):
        raise ValueError("lifecycle_state is required")
    normalized_state = raw_state.strip().lower()
    try:
        state = _PERSISTED_STATE_ALIASES.get(normalized_state)
        if state is None:
            state = RegistryState(normalized_state)
    except ValueError as exc:
        raise ValueError("lifecycle_state is not recognized") from exc
    return OfferRecord(
        intent_id=row.get("intent_id"),
        run_id=row.get("run_id"),
        wallet_fingerprint_hash=row.get("wallet_fingerprint_hash"),
        network=row.get("network"),
        asset_id=row.get("asset_id"),
        side=row.get("side"),
        tier=row.get("tier"),
        purpose=row.get("purpose"),
        slot_key=row.get("slot_key"),
        generation=row.get("generation"),
        parent_intent_id=row.get("parent_intent_id"),
        child_intent_id=row.get("child_intent_id"),
        offered_amount_atomic=row.get("offered_amount_atomic"),
        requested_amount_atomic=row.get("requested_amount_atomic"),
        selected_coin_ids=tuple(coin_ids),
        offer_text_sha256=row.get("offer_text_sha256"),
        sage_trade_id=row.get("sage_trade_id"),
        state=state,
        owned=owned,
        protected=protected,
    )


_ALLOWED_TRANSITIONS = frozenset(
    {
        (RegistryState.PREPARED, RegistryState.SUBMITTED_UNCONFIRMED),
        (RegistryState.PREPARED, RegistryState.CREATED),
        (RegistryState.PREPARED, RegistryState.TERMINAL),
        (RegistryState.PREPARED, RegistryState.UNKNOWN),
        (RegistryState.PREPARED, RegistryState.CONFLICTED),
        (RegistryState.PREPARED, RegistryState.QUARANTINED),
        (RegistryState.SUBMITTED_UNCONFIRMED, RegistryState.CREATED),
        (RegistryState.SUBMITTED_UNCONFIRMED, RegistryState.TERMINAL),
        (RegistryState.SUBMITTED_UNCONFIRMED, RegistryState.UNKNOWN),
        (RegistryState.SUBMITTED_UNCONFIRMED, RegistryState.CONFLICTED),
        (RegistryState.SUBMITTED_UNCONFIRMED, RegistryState.QUARANTINED),
        (RegistryState.CREATED, RegistryState.VISIBLE),
        (RegistryState.CREATED, RegistryState.CANCEL_REQUESTED),
        (RegistryState.CREATED, RegistryState.TERMINAL),
        (RegistryState.CREATED, RegistryState.UNKNOWN),
        (RegistryState.CREATED, RegistryState.CONFLICTED),
        (RegistryState.CREATED, RegistryState.QUARANTINED),
        (RegistryState.VISIBLE, RegistryState.CANCEL_REQUESTED),
        (RegistryState.VISIBLE, RegistryState.TERMINAL),
        (RegistryState.VISIBLE, RegistryState.UNKNOWN),
        (RegistryState.VISIBLE, RegistryState.CONFLICTED),
        (RegistryState.VISIBLE, RegistryState.QUARANTINED),
        (RegistryState.CANCEL_REQUESTED, RegistryState.CREATED),
        (RegistryState.CANCEL_REQUESTED, RegistryState.VISIBLE),
        (RegistryState.CANCEL_REQUESTED, RegistryState.TERMINAL),
        (RegistryState.CANCEL_REQUESTED, RegistryState.UNKNOWN),
        (RegistryState.CANCEL_REQUESTED, RegistryState.CONFLICTED),
        (RegistryState.CANCEL_REQUESTED, RegistryState.QUARANTINED),
        (RegistryState.UNKNOWN, RegistryState.CREATED),
        (RegistryState.UNKNOWN, RegistryState.VISIBLE),
        (RegistryState.UNKNOWN, RegistryState.TERMINAL),
        (RegistryState.UNKNOWN, RegistryState.CONFLICTED),
        (RegistryState.UNKNOWN, RegistryState.QUARANTINED),
        (RegistryState.CONFLICTED, RegistryState.CREATED),
        (RegistryState.CONFLICTED, RegistryState.VISIBLE),
        (RegistryState.CONFLICTED, RegistryState.TERMINAL),
        (RegistryState.CONFLICTED, RegistryState.UNKNOWN),
        (RegistryState.CONFLICTED, RegistryState.QUARANTINED),
        (RegistryState.QUARANTINED, RegistryState.TERMINAL),
    }
)


def _decision(
    allowed: bool,
    code: AuthorizationCode,
    reason: str,
    record: Optional[OfferRecord] = None,
    *,
    idempotent: bool = False,
) -> AuthorizationDecision:
    return AuthorizationDecision(allowed, code, reason, record, idempotent)


def transition_decision(source: Any, destination: Any) -> AuthorizationDecision:
    """Return the complete deterministic state-table decision."""

    if not isinstance(source, RegistryState) or not isinstance(
        destination, RegistryState
    ):
        return _decision(
            False, AuthorizationCode.INVALID_INPUT, "registry states are required"
        )
    if source == destination:
        return _decision(
            True,
            AuthorizationCode.IDEMPOTENT,
            "same state is an idempotent replay",
            idempotent=True,
        )
    if (source, destination) in _ALLOWED_TRANSITIONS:
        return _decision(True, AuthorizationCode.ALLOWED, "transition is permitted")
    return _decision(
        False, AuthorizationCode.INVALID_TRANSITION, "transition is not permitted"
    )


def _protected_reference(snapshot: RegistrySnapshot, reference: OfferReference) -> bool:
    return bool(
        (
            reference.sage_trade_id
            and reference.sage_trade_id in snapshot.protected_sage_trade_ids
        )
        or (
            reference.offer_text_sha256
            and reference.offer_text_sha256 in snapshot.protected_offer_hashes
        )
    )


def _resolve(
    snapshot: RegistrySnapshot, reference: OfferReference
) -> tuple[Optional[OfferRecord], Optional[AuthorizationDecision]]:
    if not any(
        (reference.intent_id, reference.sage_trade_id, reference.offer_text_sha256)
    ):
        return None, _decision(
            False, AuthorizationCode.INVALID_INPUT, "offer reference is empty"
        )
    if _protected_reference(snapshot, reference):
        return None, _decision(
            False, AuthorizationCode.PROTECTED_OFFER, "offer is protected"
        )

    matches = []
    for record in snapshot.records:
        if (
            (reference.intent_id and reference.intent_id == record.intent_id)
            or (
                reference.sage_trade_id
                and reference.sage_trade_id == record.sage_trade_id
            )
            or (
                reference.offer_text_sha256
                and reference.offer_text_sha256 == record.offer_text_sha256
            )
        ):
            matches.append(record)
    if not matches:
        return None, _decision(
            False, AuthorizationCode.NOT_REGISTERED, "offer is not registered"
        )
    if len(matches) != 1:
        return None, _decision(
            False, AuthorizationCode.AMBIGUOUS_MATCH, "offer reference is ambiguous"
        )
    record = matches[0]
    if (
        (reference.intent_id and reference.intent_id != record.intent_id)
        or (reference.sage_trade_id and reference.sage_trade_id != record.sage_trade_id)
        or (
            reference.offer_text_sha256
            and reference.offer_text_sha256 != record.offer_text_sha256
        )
    ):
        return None, _decision(
            False, AuthorizationCode.REFERENCE_MISMATCH, "offer identifiers disagree"
        )
    if record.protected:
        return None, _decision(
            False, AuthorizationCode.PROTECTED_OFFER, "offer is protected", record
        )
    if not record.owned:
        return None, _decision(
            False, AuthorizationCode.NOT_OWNED, "offer is not CATalyst-owned", record
        )
    return record, None


def _binding_decision(
    record: OfferRecord, wallet_fingerprint_hash: Any, network: Any
) -> Optional[AuthorizationDecision]:
    if not isinstance(wallet_fingerprint_hash, str) or not isinstance(network, str):
        return _decision(
            False,
            AuthorizationCode.INVALID_INPUT,
            "wallet and network are required",
            record,
        )
    if wallet_fingerprint_hash != record.wallet_fingerprint_hash:
        return _decision(
            False, AuthorizationCode.WALLET_MISMATCH, "wallet binding differs", record
        )
    if network != record.network:
        return _decision(
            False, AuthorizationCode.NETWORK_MISMATCH, "network binding differs", record
        )
    return None


def _records_by_intent(snapshot: RegistrySnapshot, intent_id: str) -> list[OfferRecord]:
    return [record for record in snapshot.records if record.intent_id == intent_id]


def _lineage_decision(
    snapshot: RegistrySnapshot, record: OfferRecord
) -> Optional[AuthorizationDecision]:
    parent = None
    child = None
    if record.parent_intent_id:
        parents = _records_by_intent(snapshot, record.parent_intent_id)
        if len(parents) != 1:
            return _decision(
                False,
                AuthorizationCode.INVALID_LINEAGE,
                "replacement parent is not unique",
                record,
            )
        parent = parents[0]
        if parent.child_intent_id != record.intent_id:
            return _decision(
                False,
                AuthorizationCode.INVALID_LINEAGE,
                "parent does not name exact child",
                record,
            )
        if record.generation != parent.generation + 1:
            return _decision(
                False,
                AuthorizationCode.INVALID_LINEAGE,
                "replacement generation is not consecutive",
                record,
            )
        if parent.state not in {RegistryState.CREATED, RegistryState.VISIBLE}:
            return _decision(
                False,
                AuthorizationCode.INVALID_LINEAGE,
                "replacement parent is not active",
                record,
            )
    claimed_children = [
        candidate
        for candidate in snapshot.records
        if candidate.parent_intent_id == record.intent_id
    ]
    if record.child_intent_id is None and claimed_children:
        return _decision(
            False,
            AuthorizationCode.INVALID_LINEAGE,
            "parent does not name claimed child",
            record,
        )
    if record.child_intent_id is not None and (
        len(claimed_children) != 1
        or claimed_children[0].intent_id != record.child_intent_id
    ):
        return _decision(
            False,
            AuthorizationCode.INVALID_LINEAGE,
            "parent has an ambiguous child claim",
            record,
        )
    if record.child_intent_id:
        children = _records_by_intent(snapshot, record.child_intent_id)
        if len(children) != 1:
            return _decision(
                False,
                AuthorizationCode.INVALID_LINEAGE,
                "replacement child is not unique",
                record,
            )
        child = children[0]
        if child.parent_intent_id != record.intent_id:
            return _decision(
                False,
                AuthorizationCode.INVALID_LINEAGE,
                "child does not name exact parent",
                record,
            )
        if child.generation != record.generation + 1:
            return _decision(
                False,
                AuthorizationCode.INVALID_LINEAGE,
                "replacement generation is not consecutive",
                record,
            )
    for related in (parent, child):
        if related is None:
            continue
        if (
            related.run_id != record.run_id
            or related.wallet_fingerprint_hash != record.wallet_fingerprint_hash
            or related.network != record.network
            or related.asset_id != record.asset_id
            or related.side != record.side
            or related.tier != record.tier
            or related.slot_key != record.slot_key
        ):
            return _decision(
                False,
                AuthorizationCode.INVALID_LINEAGE,
                "replacement identity or slot differs",
                record,
            )
    return None


def _has_duplicate_active_slot(snapshot: RegistrySnapshot, record: OfferRecord) -> bool:
    return bool(
        record.slot_key is not None
        and any(
            other.intent_id != record.intent_id
            and other.run_id == record.run_id
            and other.slot_key == record.slot_key
            and other.generation == record.generation
            and other.state in _ACTIVE_SLOT_STATES
            for other in snapshot.records
        )
    )


def authorize_mutation(snapshot: Any, request: Any) -> AuthorizationDecision:
    """Authorize one mutation from a single immutable registry snapshot."""

    if not isinstance(snapshot, RegistrySnapshot) or not isinstance(
        request, MutationRequest
    ):
        return _decision(
            False,
            AuthorizationCode.INVALID_INPUT,
            "snapshot and mutation request are required",
        )
    record, denied = _resolve(snapshot, request.reference)
    if denied is not None:
        return denied
    assert record is not None
    binding = _binding_decision(
        record, request.wallet_fingerprint_hash, request.network
    )
    if binding is not None:
        return binding
    blockers = [item for item in snapshot.records if item.state in _BLOCKING_STATES]
    if blockers:
        return _decision(
            False,
            AuthorizationCode.REGISTRY_BLOCKED,
            "an unresolved registry row blocks mutation",
            record,
        )
    if not record.selected_coin_ids:
        return _decision(
            False,
            AuthorizationCode.MISSING_SELECTED_COINS,
            "selected coin identity is missing",
            record,
        )
    lineage = _lineage_decision(snapshot, record)
    if lineage is not None:
        return lineage

    allowed_states = {
        MutationKind.CREATE: {RegistryState.PREPARED},
        MutationKind.CANCEL: {RegistryState.CREATED, RegistryState.VISIBLE},
        MutationKind.REPLACE: {RegistryState.CREATED, RegistryState.VISIBLE},
        MutationKind.PUBLISH: {RegistryState.CREATED, RegistryState.VISIBLE},
    }
    if record.state not in allowed_states[request.kind]:
        return _decision(
            False,
            AuthorizationCode.INVALID_MUTATION_STATE,
            "registry state blocks this mutation",
            record,
        )

    if request.kind == MutationKind.CREATE:
        if not request.selected_coin_ids:
            return _decision(
                False,
                AuthorizationCode.MISSING_SELECTED_COINS,
                "create request has no selected coins",
                record,
            )
        if request.selected_coin_ids != record.selected_coin_ids:
            return _decision(
                False,
                AuthorizationCode.SELECTED_COINS_MISMATCH,
                "selected coin identity differs",
                record,
            )
        if _has_duplicate_active_slot(snapshot, record):
            return _decision(
                False,
                AuthorizationCode.DUPLICATE_ACTIVE_SLOT,
                "active slot generation already exists",
                record,
            )

    if (
        request.kind in {MutationKind.CANCEL, MutationKind.REPLACE}
        and record.child_intent_id
    ):
        child = _records_by_intent(snapshot, record.child_intent_id)[0]
        if child.state != RegistryState.VISIBLE:
            return _decision(
                False,
                AuthorizationCode.REPLACEMENT_CHILD_NOT_VISIBLE,
                "replacement child is not visible",
                record,
            )
    return _decision(True, AuthorizationCode.ALLOWED, "mutation is authorized", record)


def _evidence_matches(
    record: OfferRecord, evidence: OfferEvidence, destination: RegistryState
) -> bool:
    return bool(
        evidence.observed_state == destination
        and evidence.intent_id == record.intent_id
        and evidence.wallet_fingerprint_hash == record.wallet_fingerprint_hash
        and evidence.network == record.network
        and evidence.offered_amount_atomic == record.offered_amount_atomic
        and evidence.requested_amount_atomic == record.requested_amount_atomic
        and evidence.selected_coin_ids == record.selected_coin_ids
        and (
            record.sage_trade_id is None
            or evidence.sage_trade_id == record.sage_trade_id
        )
        and (
            record.offer_text_sha256 is None
            or evidence.offer_text_sha256 == record.offer_text_sha256
        )
    )


def _terminal_evidence_decision(
    record: OfferRecord, evidence: OfferEvidence
) -> Optional[AuthorizationDecision]:
    if evidence.terminal_outcome is None:
        return _decision(
            False,
            AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT,
            "terminal outcome is absent",
            record,
        )
    if evidence.source == EvidenceSource.THIRD_PARTY_OBSERVATION:
        return _decision(
            False,
            AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT,
            "third-party observation is not terminal proof",
            record,
        )
    if record.state == RegistryState.PREPARED and evidence.terminal_outcome not in {
        TerminalOutcome.CREATION_FAILED,
        TerminalOutcome.REJECTED,
    }:
        return _decision(
            False,
            AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT,
            "prepared intent has no live-offer terminal outcome",
            record,
        )
    if evidence.terminal_outcome in {
        TerminalOutcome.CREATION_FAILED,
        TerminalOutcome.REJECTED,
    }:
        if record.state not in {
            RegistryState.PREPARED,
            RegistryState.SUBMITTED_UNCONFIRMED,
        } or evidence.source not in {
            EvidenceSource.AUTHORITATIVE_WALLET,
            EvidenceSource.FULL_WALLET_HISTORY,
        }:
            return _decision(
                False,
                AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT,
                "creation failure lacks authoritative wallet proof",
                record,
            )
    elif evidence.terminal_outcome == TerminalOutcome.EXPIRED:
        if evidence.source not in {
            EvidenceSource.AUTHORITATIVE_WALLET,
            EvidenceSource.FULL_WALLET_HISTORY,
        }:
            return _decision(
                False,
                AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT,
                "expiry lacks authoritative wallet proof",
                record,
            )
    elif evidence.source in {
        EvidenceSource.EXACT_TRANSACTION,
        EvidenceSource.EXACT_COIN_SPEND,
    }:
        if (
            not (evidence.transaction_id or evidence.spend_identity)
            or evidence.block_height is None
            or evidence.block_height <= 0
        ):
            return _decision(
                False,
                AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT,
                "on-chain terminal proof is incomplete",
                record,
            )
    elif evidence.source not in {
        EvidenceSource.AUTHORITATIVE_WALLET,
        EvidenceSource.FULL_WALLET_HISTORY,
    }:
        return _decision(
            False,
            AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT,
            "terminal evidence source is not authoritative",
            record,
        )
    return None


def authorize_transition(
    snapshot: Any,
    reference: Any,
    destination: Any,
    wallet_fingerprint_hash: Any,
    network: Any,
    *,
    evidence: Any = None,
) -> AuthorizationDecision:
    """Authorize a registry transition, including proof-bearing reconciliation."""

    if (
        not isinstance(snapshot, RegistrySnapshot)
        or not isinstance(reference, OfferReference)
        or not isinstance(destination, RegistryState)
        or (evidence is not None and not isinstance(evidence, OfferEvidence))
    ):
        return _decision(
            False,
            AuthorizationCode.INVALID_INPUT,
            "typed registry transition inputs are required",
        )
    record, denied = _resolve(snapshot, reference)
    if denied is not None:
        return denied
    assert record is not None
    binding = _binding_decision(record, wallet_fingerprint_hash, network)
    if binding is not None:
        return binding
    if not record.selected_coin_ids:
        return _decision(
            False,
            AuthorizationCode.MISSING_SELECTED_COINS,
            "selected coin identity is missing",
            record,
        )
    lineage = _lineage_decision(snapshot, record)
    if lineage is not None:
        return lineage
    if _has_duplicate_active_slot(snapshot, record):
        return _decision(
            False,
            AuthorizationCode.DUPLICATE_ACTIVE_SLOT,
            "active slot generation already exists",
            record,
        )
    table = transition_decision(record.state, destination)
    if not table.allowed:
        return _decision(False, table.code, table.reason, record)
    if table.idempotent:
        return _decision(
            True, AuthorizationCode.IDEMPOTENT, table.reason, record, idempotent=True
        )

    needs_reconciliation = record.state in _BLOCKING_STATES
    if destination == RegistryState.TERMINAL and evidence is None:
        return _decision(
            False,
            AuthorizationCode.TERMINAL_PROOF_REQUIRED,
            "terminal transition requires proof",
            record,
        )
    if needs_reconciliation and evidence is None:
        return _decision(
            False,
            AuthorizationCode.RECONCILIATION_EVIDENCE_REQUIRED,
            "unresolved state requires reconciliation evidence",
            record,
        )
    if evidence is not None and not _evidence_matches(record, evidence, destination):
        return _decision(
            False,
            AuthorizationCode.EVIDENCE_MISMATCH,
            "evidence does not exactly match the offer",
            record,
        )
    if record.state == RegistryState.QUARANTINED:
        if not (
            evidence
            and evidence.source == EvidenceSource.FULL_WALLET_HISTORY
            and evidence.full_history
            and evidence.input_coins_owned_unlocked
        ):
            return _decision(
                False,
                AuthorizationCode.QUARANTINE_PROOF_REQUIRED,
                "quarantine requires full history and owned unlocked coins",
                record,
            )
    if destination == RegistryState.TERMINAL:
        assert isinstance(evidence, OfferEvidence)
        terminal_denial = _terminal_evidence_decision(record, evidence)
        if terminal_denial is not None:
            return terminal_denial
    elif (
        needs_reconciliation
        and evidence is not None
        and evidence.source == EvidenceSource.THIRD_PARTY_OBSERVATION
    ):
        return _decision(
            False,
            AuthorizationCode.RECONCILIATION_EVIDENCE_REQUIRED,
            "third-party evidence cannot resolve registry state",
            record,
        )
    return _decision(
        True, AuthorizationCode.ALLOWED, "transition is authorized", record
    )


__all__ = [
    "AuthorizationCode",
    "AuthorizationDecision",
    "EvidenceSource",
    "MutationKind",
    "MutationRequest",
    "OfferEvidence",
    "OfferRecord",
    "OfferReference",
    "RegistrySnapshot",
    "RegistryState",
    "TerminalOutcome",
    "authorize_mutation",
    "authorize_transition",
    "offer_record_from_row",
    "transition_decision",
]
