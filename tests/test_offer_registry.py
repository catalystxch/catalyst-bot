"""Pure policy tests for the durable offer registry."""

from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, fields, replace
from itertools import product

import pytest

from offer_registry import (
    AuthorizationCode,
    AuthorizationDecision,
    EvidenceSource,
    MutationKind,
    MutationRequest,
    OfferEvidence,
    OfferRecord,
    OfferReference,
    RegistrySnapshot,
    RegistryState,
    TerminalOutcome,
    authorize_mutation,
    authorize_transition,
    offer_record_from_row,
    transition_decision,
)


WALLET = "a" * 64
OTHER_WALLET = "b" * 64
NETWORK = "mainnet"
TRADE = "c" * 64
OFFER_HASH = "d" * 64
COIN = "e" * 64
OTHER_COIN = "f" * 64


class HostileStr(str):
    """A string-shaped object whose inherited operations are attacker-controlled."""

    def __str__(self):
        raise AssertionError("hostile __str__ invoked")

    def strip(self, *args, **kwargs):
        raise AssertionError("hostile strip invoked")

    def lower(self):
        raise AssertionError("hostile lower invoked")

    def __eq__(self, other):
        raise AssertionError("hostile equality invoked")

    def __hash__(self):
        raise AssertionError("hostile hash invoked")


class HostileOfferRecord(OfferRecord):
    """A stored UNKNOWN record that lies about its state after construction."""

    def __getattribute__(self, name):
        if name == "state":
            underlying = object.__getattribute__(self, name)
            if underlying is RegistryState.UNKNOWN:
                return RegistryState.VISIBLE
        return object.__getattribute__(self, name)


class OfferRecordSubclass(OfferRecord):
    pass


class RegistrySnapshotSubclass(RegistrySnapshot):
    pass


class MutationRequestSubclass(MutationRequest):
    pass


class OfferReferenceSubclass(OfferReference):
    pass


class OfferEvidenceSubclass(OfferEvidence):
    pass


class DomainTypeSpoof:
    """A mutable object that makes isinstance() claim a policy domain type."""

    def __init__(self, claimed_type):
        self.claimed_type = claimed_type

    @property
    def __class__(self):
        return self.claimed_type


def subclass_copy(subclass, value, base_type):
    return subclass(
        **{
            field.name: object.__getattribute__(value, field.name)
            for field in fields(base_type)
        }
    )


def record(
    *,
    intent_id: str = "intent-1",
    state: RegistryState = RegistryState.CREATED,
    wallet: str = WALLET,
    network: str = NETWORK,
    slot_key: str | None = "buy:inner",
    generation: int = 1,
    parent_intent_id: str | None = None,
    child_intent_id: str | None = None,
    selected_coin_ids: tuple[str, ...] = (COIN,),
    trade_id: str | None = TRADE,
    offer_hash: str | None = OFFER_HASH,
    owned: bool = True,
    protected: bool = False,
) -> OfferRecord:
    return OfferRecord(
        intent_id=intent_id,
        run_id="run-1",
        wallet_fingerprint_hash=wallet,
        network=network,
        asset_id="asset-1",
        side="buy",
        tier="inner",
        purpose="normal",
        slot_key=slot_key,
        generation=generation,
        parent_intent_id=parent_intent_id,
        child_intent_id=child_intent_id,
        offered_amount_atomic="1000",
        requested_amount_atomic=2000,
        selected_coin_ids=selected_coin_ids,
        offer_text_sha256=offer_hash,
        sage_trade_id=trade_id,
        state=state,
        owned=owned,
        protected=protected,
    )


def reference(intent_id: str = "intent-1") -> OfferReference:
    return OfferReference(intent_id=intent_id)


def request(
    kind: MutationKind,
    *,
    ref: OfferReference | None = None,
    wallet: str = WALLET,
    network: str = NETWORK,
    selected_coin_ids: tuple[str, ...] = (COIN,),
) -> MutationRequest:
    return MutationRequest(
        kind=kind,
        reference=ref or reference(),
        wallet_fingerprint_hash=wallet,
        network=network,
        selected_coin_ids=selected_coin_ids,
    )


def evidence(
    *,
    observed_state: RegistryState = RegistryState.TERMINAL,
    outcome: TerminalOutcome | None = TerminalOutcome.FILLED,
    source: EvidenceSource = EvidenceSource.EXACT_COIN_SPEND,
    wallet: str = WALLET,
    network: str = NETWORK,
    intent_id: str = "intent-1",
    selected_coin_ids: tuple[str, ...] = (COIN,),
    transaction_id: str | None = "tx-1",
    spend_identity: str | None = "spend-1",
    block_height: int | None = 123,
    full_history: bool = False,
    input_coins_owned_unlocked: bool = False,
) -> OfferEvidence:
    return OfferEvidence(
        observed_state=observed_state,
        terminal_outcome=outcome,
        source=source,
        intent_id=intent_id,
        wallet_fingerprint_hash=wallet,
        network=network,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids=selected_coin_ids,
        sage_trade_id=TRADE,
        offer_text_sha256=OFFER_HASH,
        observed_at="2026-08-15T12:00:00+00:00",
        transaction_id=transaction_id,
        spend_identity=spend_identity,
        block_height=block_height,
        full_history=full_history,
        input_coins_owned_unlocked=input_coins_owned_unlocked,
    )


ALLOWED_EDGES = {
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


@pytest.mark.parametrize(
    ("source", "destination"), product(RegistryState, RegistryState)
)
def test_complete_state_table_denies_every_unlisted_edge(source, destination):
    """Catches accidental permissive edges anywhere in the 9x9 state table."""

    decision = transition_decision(source, destination)
    expected = source == destination or (source, destination) in ALLOWED_EDGES

    assert decision.allowed is expected
    assert decision.idempotent is (source == destination)


def test_state_transition_function_is_total_for_malformed_types():
    """Catches enum coercion or exceptions that would bypass fail-closed policy."""

    for source, destination in (("created", RegistryState.VISIBLE), (None, object())):
        decision = transition_decision(source, destination)
        assert decision.allowed is False
        assert decision.code is AuthorizationCode.INVALID_INPUT


def test_domain_values_are_deeply_immutable_and_atomic_amounts_never_float():
    """Catches mutable coin collections and float/coercible amount acceptance."""

    item = record()
    assert item.offered_amount_atomic == "1000"
    assert item.requested_amount_atomic == "2000"
    with pytest.raises(FrozenInstanceError):
        item.state = RegistryState.VISIBLE
    with pytest.raises(ValueError, match="atomic integer"):
        replace(record(), offered_amount_atomic=1.5)
    with pytest.raises(ValueError, match="atomic integer"):
        replace(record(), offered_amount_atomic=True)

    mutable_coins = [COIN]
    normalized = replace(item, selected_coin_ids=mutable_coins)
    snapshot = RegistrySnapshot(
        [normalized],
        protected_sage_trade_ids=[TRADE],
        protected_offer_hashes=[OFFER_HASH],
    )
    mutation = request(MutationKind.CREATE, selected_coin_ids=mutable_coins)
    proof = replace(evidence(), selected_coin_ids=mutable_coins)
    mutable_coins.clear()

    assert type(normalized.selected_coin_ids) is tuple
    assert type(snapshot.records) is tuple
    assert type(snapshot.protected_sage_trade_ids) is frozenset
    assert type(snapshot.protected_offer_hashes) is frozenset
    assert type(mutation.selected_coin_ids) is tuple
    assert type(proof.selected_coin_ids) is tuple
    assert normalized.selected_coin_ids == (COIN,)


def test_public_text_rejects_hostile_subclasses_without_invoking_overrides():
    """Catches subclass hooks spoofing validation, equality, hashing, or storage."""

    with pytest.raises(ValueError):
        replace(record(), intent_id=HostileStr("intent-hostile"))
    with pytest.raises(ValueError):
        replace(record(), wallet_fingerprint_hash=HostileStr(WALLET))
    with pytest.raises(ValueError):
        replace(record(), offered_amount_atomic=HostileStr("1000"))
    with pytest.raises(ValueError):
        OfferReference(intent_id=HostileStr("intent-hostile"))
    with pytest.raises(ValueError):
        RegistrySnapshot((), protected_sage_trade_ids=(HostileStr(TRADE),))
    with pytest.raises(ValueError):
        replace(evidence(), network=HostileStr(NETWORK))
    with pytest.raises(ValueError):
        AuthorizationDecision(
            True,
            AuthorizationCode.ALLOWED,
            HostileStr("authorized"),
        )

    item = record()
    for value in (
        item.intent_id,
        item.run_id,
        item.wallet_fingerprint_hash,
        item.network,
        item.asset_id,
        item.side,
        item.tier,
        item.purpose,
        item.slot_key,
        item.offered_amount_atomic,
        item.requested_amount_atomic,
        *item.selected_coin_ids,
        item.offer_text_sha256,
        item.sage_trade_id,
    ):
        assert type(value) is str


def test_hostile_runtime_wallet_and_network_are_denied_without_comparison():
    """Catches equality-overriding binding inputs authorizing the wrong context."""

    snapshot = RegistrySnapshot((record(),))
    hostile_wallet = authorize_transition(
        snapshot,
        reference(),
        RegistryState.VISIBLE,
        HostileStr(OTHER_WALLET),
        NETWORK,
    )
    hostile_network = authorize_transition(
        snapshot,
        reference(),
        RegistryState.VISIBLE,
        WALLET,
        HostileStr("testnet11"),
    )
    assert hostile_wallet.code is AuthorizationCode.INVALID_INPUT
    assert hostile_network.code is AuthorizationCode.INVALID_INPUT


def test_snapshot_rejects_offer_record_subclass_before_policy_access():
    """Catches an underlying UNKNOWN row lying that it is mutation-safe."""

    hostile = subclass_copy(
        HostileOfferRecord,
        record(state=RegistryState.UNKNOWN),
        OfferRecord,
    )
    assert object.__getattribute__(hostile, "state") is RegistryState.UNKNOWN
    assert hostile.state is RegistryState.VISIBLE

    with pytest.raises(ValueError, match="OfferRecord"):
        RegistrySnapshot((hostile,))


def test_authorize_mutation_rejects_registry_snapshot_subclass():
    """Catches a snapshot subtype changing its records after validation."""

    hostile = subclass_copy(
        RegistrySnapshotSubclass,
        RegistrySnapshot((record(state=RegistryState.VISIBLE),)),
        RegistrySnapshot,
    )
    decision = authorize_mutation(hostile, request(MutationKind.CANCEL))
    assert decision.code is AuthorizationCode.INVALID_INPUT


def test_authorize_mutation_rejects_mutation_request_subclass():
    """Catches a request subtype changing its mutation kind after validation."""

    hostile = subclass_copy(
        MutationRequestSubclass,
        request(MutationKind.CANCEL),
        MutationRequest,
    )
    decision = authorize_mutation(
        RegistrySnapshot((record(state=RegistryState.VISIBLE),)), hostile
    )
    assert decision.code is AuthorizationCode.INVALID_INPUT


def test_authorize_transition_rejects_offer_reference_subclass():
    """Catches a reference subtype redirecting lookup after validation."""

    hostile = subclass_copy(
        OfferReferenceSubclass,
        reference(),
        OfferReference,
    )
    decision = authorize_transition(
        RegistrySnapshot((record(),)),
        hostile,
        RegistryState.VISIBLE,
        WALLET,
        NETWORK,
    )
    assert decision.code is AuthorizationCode.INVALID_INPUT


def test_authorize_transition_rejects_offer_evidence_subclass():
    """Catches an evidence subtype changing terminal proof after validation."""

    hostile = subclass_copy(OfferEvidenceSubclass, evidence(), OfferEvidence)
    decision = authorize_transition(
        RegistrySnapshot((record(state=RegistryState.VISIBLE),)),
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=hostile,
    )
    assert decision.code is AuthorizationCode.INVALID_INPUT


def test_domain_enum_and_decision_fields_reject_isinstance_spoofs():
    """Catches mutable objects impersonating enum and record domain types."""

    with pytest.raises(ValueError):
        replace(record(), state=DomainTypeSpoof(RegistryState))
    with pytest.raises(ValueError):
        replace(request(MutationKind.CANCEL), kind=DomainTypeSpoof(MutationKind))
    with pytest.raises(ValueError):
        replace(evidence(), source=DomainTypeSpoof(EvidenceSource))
    with pytest.raises(ValueError):
        replace(evidence(), terminal_outcome=DomainTypeSpoof(TerminalOutcome))
    with pytest.raises(ValueError):
        AuthorizationDecision(
            True,
            DomainTypeSpoof(AuthorizationCode),
            "spoofed decision",
        )
    hostile_record = subclass_copy(OfferRecordSubclass, record(), OfferRecord)
    with pytest.raises(ValueError):
        AuthorizationDecision(
            True,
            AuthorizationCode.ALLOWED,
            "spoofed record",
            hostile_record,
        )

    transition = transition_decision(
        DomainTypeSpoof(RegistryState), RegistryState.VISIBLE
    )
    assert transition.code is AuthorizationCode.INVALID_INPUT
    assert type(transition) is AuthorizationDecision


def task3_row(**changes):
    coin_json = f'["{COIN}"]'
    row = {
        "intent_id": "intent-db",
        "run_id": "run-1",
        "wallet_fingerprint_hash": WALLET,
        "network": NETWORK,
        "asset_id": "asset-1",
        "side": "sell",
        "tier": "outer",
        "purpose": "normal",
        "slot_key": "sell:outer",
        "generation": 0,
        "parent_intent_id": None,
        "child_intent_id": None,
        "offered_amount_atomic": "9223372036854775808",
        "requested_amount_atomic": "2000",
        "selected_coin_ids_json": f'["{COIN}"]',
        "selected_coin_ids_sha256": hashlib.sha256(coin_json.encode()).hexdigest(),
        "offer_text_sha256": None,
        "sage_trade_id": None,
        "lifecycle_state": "creation_unknown",
    }
    row.update(changes)
    return row


def test_task3_database_row_adapts_without_persistence_dependencies():
    """Catches drift from Task 3 column/state and canonical coin JSON contracts."""

    row = task3_row()

    adapted = offer_record_from_row(row)

    assert adapted.state is RegistryState.UNKNOWN
    assert adapted.offered_amount_atomic == "9223372036854775808"
    assert adapted.selected_coin_ids == (COIN,)
    with pytest.raises(ValueError, match="selected_coin_ids_json"):
        offer_record_from_row({**row, "selected_coin_ids_json": "not-json"})


@pytest.mark.parametrize(
    ("coin_json", "digest"),
    [
        (f'[ "{COIN}" ]', None),
        (f'["{COIN}","{COIN}"]', None),
        (f'["{OTHER_COIN}","{COIN}"]', None),
        (f'["{COIN}"]', "0" * 64),
        (
            f'["{COIN}"]',
            hashlib.sha256(f'["{COIN}"]'.encode()).hexdigest().upper(),
        ),
        (f'["{COIN}"]', None),
    ],
)
def test_task3_adapter_rejects_noncanonical_or_unverified_coin_identity(
    coin_json, digest
):
    """Catches adapter-side repair or acceptance of unverified coin JSON."""

    if digest is None and coin_json != f'["{COIN}"]':
        digest = hashlib.sha256(coin_json.encode()).hexdigest()
    row = task3_row(selected_coin_ids_json=coin_json)
    if digest is None:
        row.pop("selected_coin_ids_sha256")
    else:
        row["selected_coin_ids_sha256"] = digest

    with pytest.raises(ValueError, match="selected_coin_ids"):
        offer_record_from_row(row)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_coin_ids_json", HostileStr(f'["{COIN}"]')),
        ("selected_coin_ids_sha256", HostileStr("0" * 64)),
        ("lifecycle_state", HostileStr("creation_unknown")),
        ("network", HostileStr(NETWORK)),
    ],
)
def test_task3_adapter_rejects_hostile_text_row_values(field, value):
    """Catches persistence rows invoking subclass operations during adaptation."""

    with pytest.raises(ValueError):
        offer_record_from_row(task3_row(**{field: value}))


@pytest.mark.parametrize(
    ("snapshot", "mutation", "code"),
    [
        (
            RegistrySnapshot((record(),)),
            request(MutationKind.CANCEL, wallet=OTHER_WALLET),
            AuthorizationCode.WALLET_MISMATCH,
        ),
        (
            RegistrySnapshot((record(),)),
            request(MutationKind.CANCEL, network="testnet11"),
            AuthorizationCode.NETWORK_MISMATCH,
        ),
        (
            RegistrySnapshot((record(protected=True),)),
            request(MutationKind.CANCEL),
            AuthorizationCode.PROTECTED_OFFER,
        ),
        (
            RegistrySnapshot((record(owned=False),)),
            request(MutationKind.CANCEL),
            AuthorizationCode.NOT_OWNED,
        ),
    ],
)
def test_mutation_authorization_fails_closed_on_binding_and_ownership(
    snapshot, mutation, code
):
    """Catches mutation approval against the wrong wallet, network, or owner."""

    decision = authorize_mutation(snapshot, mutation)
    assert decision.allowed is False
    assert decision.code is code


def test_protected_identifiers_are_denied_even_without_a_registry_row():
    """Catches treating an absent protected offer as ordinary not-found data."""

    snapshot = RegistrySnapshot((), protected_sage_trade_ids=frozenset({TRADE}))
    decision = authorize_mutation(
        snapshot,
        request(MutationKind.CANCEL, ref=OfferReference(sage_trade_id=TRADE)),
    )
    assert decision.code is AuthorizationCode.PROTECTED_OFFER


@pytest.mark.parametrize(
    "protected_kwargs",
    [
        {"protected_sage_trade_ids": frozenset({TRADE})},
        {"protected_offer_hashes": frozenset({OFFER_HASH})},
    ],
)
def test_intent_only_reference_cannot_bypass_resolved_record_protection(
    protected_kwargs,
):
    """Catches alternate identifiers bypassing a protected secondary identity."""

    snapshot = RegistrySnapshot((record(),), **protected_kwargs)
    mutation = authorize_mutation(snapshot, request(MutationKind.CANCEL))
    transition = authorize_transition(
        snapshot,
        reference(),
        RegistryState.VISIBLE,
        WALLET,
        NETWORK,
    )
    assert mutation.code is AuthorizationCode.PROTECTED_OFFER
    assert transition.code is AuthorizationCode.PROTECTED_OFFER


def test_cross_identifier_matches_to_different_rows_are_ambiguous():
    """Catches first-match wins when supplied identifiers name two offers."""

    other = record(intent_id="intent-2", trade_id="1" * 64, offer_hash="2" * 64)
    snapshot = RegistrySnapshot((record(), other))
    mutation = request(
        MutationKind.CANCEL,
        ref=OfferReference(intent_id="intent-1", sage_trade_id=other.sage_trade_id),
    )
    assert (
        authorize_mutation(snapshot, mutation).code is AuthorizationCode.AMBIGUOUS_MATCH
    )


def test_duplicate_intent_rows_are_ambiguous_even_when_primary_identity_matches():
    """Catches corrupt duplicate primary identities being collapsed to one row."""

    duplicate = record(trade_id="1" * 64, offer_hash="2" * 64)
    decision = authorize_mutation(
        RegistrySnapshot((record(), duplicate)), request(MutationKind.CANCEL)
    )
    assert decision.code is AuthorizationCode.AMBIGUOUS_MATCH


def test_unique_secondary_reference_cannot_hide_duplicate_primary_rows():
    """Catches lookup by a unique trade/hash masking duplicate intent storage."""

    sibling = record(trade_id="1" * 64, offer_hash="2" * 64)
    snapshot = RegistrySnapshot((record(), sibling))
    mutation = authorize_mutation(
        snapshot,
        request(
            MutationKind.CANCEL,
            ref=OfferReference(sage_trade_id=TRADE),
        ),
    )
    transition = authorize_transition(
        snapshot,
        OfferReference(offer_text_sha256=OFFER_HASH),
        RegistryState.VISIBLE,
        WALLET,
        NETWORK,
    )
    assert mutation.code is AuthorizationCode.AMBIGUOUS_MATCH
    assert transition.code is AuthorizationCode.AMBIGUOUS_MATCH


@pytest.mark.parametrize("duplicate_field", ["sage_trade_id", "offer_text_sha256"])
def test_unrelated_duplicate_durable_identity_blocks_unique_target(duplicate_field):
    """Catches global registry corruption being ignored outside the lookup row."""

    common = "1" * 64
    first_kwargs = {
        "intent_id": "intent-corrupt-1",
        "trade_id": "2" * 64,
        "offer_hash": "3" * 64,
    }
    second_kwargs = {
        "intent_id": "intent-corrupt-2",
        "trade_id": "4" * 64,
        "offer_hash": "5" * 64,
    }
    if duplicate_field == "sage_trade_id":
        first_kwargs["trade_id"] = common
        second_kwargs["trade_id"] = common
    else:
        first_kwargs["offer_hash"] = common
        second_kwargs["offer_hash"] = common
    snapshot = RegistrySnapshot(
        (record(), record(**first_kwargs), record(**second_kwargs))
    )

    decision = authorize_mutation(snapshot, request(MutationKind.CANCEL))

    assert decision.code is AuthorizationCode.AMBIGUOUS_MATCH


def test_create_denies_duplicate_active_slot_and_missing_or_mismatched_coins():
    """Catches duplicate effects and creates without exact selected inputs."""

    candidate = record(state=RegistryState.PREPARED, trade_id=None, offer_hash=None)
    duplicate = record(intent_id="intent-2", state=RegistryState.VISIBLE)
    assert (
        authorize_mutation(
            RegistrySnapshot((candidate, duplicate)), request(MutationKind.CREATE)
        ).code
        is AuthorizationCode.DUPLICATE_ACTIVE_SLOT
    )

    missing = record(
        state=RegistryState.PREPARED,
        trade_id=None,
        offer_hash=None,
        selected_coin_ids=(),
    )
    assert (
        authorize_mutation(
            RegistrySnapshot((missing,)), request(MutationKind.CREATE)
        ).code
        is AuthorizationCode.MISSING_SELECTED_COINS
    )
    assert (
        authorize_mutation(
            RegistrySnapshot((candidate,)),
            request(MutationKind.CREATE, selected_coin_ids=(OTHER_COIN,)),
        ).code
        is AuthorizationCode.SELECTED_COINS_MISMATCH
    )


def test_exact_bidirectional_parent_child_lineage_is_required():
    """Catches one-sided links, skipped generations, and mismatched slots."""

    parent = record(child_intent_id="intent-child", state=RegistryState.VISIBLE)
    child = record(
        intent_id="intent-child",
        state=RegistryState.PREPARED,
        trade_id=None,
        offer_hash=None,
        parent_intent_id=parent.intent_id,
        generation=3,
    )
    decision = authorize_mutation(
        RegistrySnapshot((parent, child)),
        request(
            MutationKind.CREATE,
            ref=OfferReference(intent_id=child.intent_id),
        ),
    )
    assert decision.code is AuthorizationCode.INVALID_LINEAGE

    valid_child = record(
        intent_id="intent-child",
        state=RegistryState.VISIBLE,
        parent_intent_id=parent.intent_id,
        generation=2,
        trade_id="1" * 64,
        offer_hash="2" * 64,
    )
    allowed = authorize_mutation(
        RegistrySnapshot((parent, valid_child)), request(MutationKind.CANCEL)
    )
    assert allowed.allowed is True


def test_create_allows_one_exact_prepared_child_before_post_create_binding():
    """The child claims its parent before the reverse edge can be committed."""

    parent = record(state=RegistryState.VISIBLE, child_intent_id=None)
    child = record(
        intent_id="intent-child",
        state=RegistryState.PREPARED,
        trade_id=None,
        offer_hash=None,
        parent_intent_id=parent.intent_id,
        generation=2,
    )
    allowed = authorize_mutation(
        RegistrySnapshot((parent, child)),
        request(
            MutationKind.CREATE,
            ref=OfferReference(intent_id=child.intent_id),
        ),
    )

    assert allowed.allowed is True

    sibling = record(
        intent_id="intent-sibling",
        state=RegistryState.PREPARED,
        trade_id=None,
        offer_hash=None,
        parent_intent_id=parent.intent_id,
        generation=2,
        selected_coin_ids=(OTHER_COIN,),
    )
    denied = authorize_mutation(
        RegistrySnapshot((parent, child, sibling)),
        request(
            MutationKind.CREATE,
            ref=OfferReference(intent_id=child.intent_id),
        ),
    )

    assert denied.code is AuthorizationCode.INVALID_LINEAGE

    failed_prior_child = record(
        intent_id="intent-failed-child",
        state=RegistryState.TERMINAL,
        trade_id=None,
        offer_hash=None,
        parent_intent_id=parent.intent_id,
        generation=2,
        selected_coin_ids=(OTHER_COIN,),
    )
    recovered = authorize_mutation(
        RegistrySnapshot((parent, failed_prior_child, child)),
        request(
            MutationKind.CREATE,
            ref=OfferReference(intent_id=child.intent_id),
        ),
    )

    assert recovered.allowed is True


def test_lineage_rejects_unlisted_siblings_and_terminal_parents():
    """Catches a second child claim or replacement of a retired parent."""

    parent = record(child_intent_id="intent-child", state=RegistryState.VISIBLE)
    child = record(
        intent_id="intent-child",
        state=RegistryState.VISIBLE,
        parent_intent_id=parent.intent_id,
        generation=2,
        trade_id="1" * 64,
        offer_hash="2" * 64,
    )
    sibling = record(
        intent_id="intent-sibling",
        state=RegistryState.PREPARED,
        parent_intent_id=parent.intent_id,
        generation=2,
        trade_id=None,
        offer_hash=None,
    )
    assert (
        authorize_mutation(
            RegistrySnapshot((parent, child, sibling)), request(MutationKind.CANCEL)
        ).code
        is AuthorizationCode.INVALID_LINEAGE
    )

    retired_parent = record(
        child_intent_id="intent-child", state=RegistryState.TERMINAL
    )
    uncreated_child = record(
        intent_id="intent-child",
        state=RegistryState.PREPARED,
        parent_intent_id=retired_parent.intent_id,
        generation=2,
        trade_id=None,
        offer_hash=None,
    )
    assert (
        authorize_mutation(
            RegistrySnapshot((retired_parent, uncreated_child)),
            request(
                MutationKind.CREATE,
                ref=OfferReference(intent_id=uncreated_child.intent_id),
            ),
        ).code
        is AuthorizationCode.INVALID_LINEAGE
    )


def test_terminal_parent_allows_recovery_of_already_created_child():
    """A proven-retired parent must not strand its already-live successor."""

    parent = record(child_intent_id="intent-child", state=RegistryState.TERMINAL)
    child = record(
        intent_id="intent-child",
        state=RegistryState.VISIBLE,
        parent_intent_id=parent.intent_id,
        generation=2,
        trade_id="1" * 64,
        offer_hash="2" * 64,
    )
    snapshot = RegistrySnapshot((parent, child))
    child_ref = OfferReference(intent_id=child.intent_id)

    cancel = authorize_mutation(
        snapshot,
        request(MutationKind.CANCEL, ref=child_ref),
    )
    replace = authorize_mutation(
        snapshot,
        request(MutationKind.REPLACE, ref=child_ref),
    )
    checkpoint = authorize_transition(
        snapshot,
        child_ref,
        RegistryState.CANCEL_REQUESTED,
        WALLET,
        NETWORK,
    )

    assert cancel.allowed is True
    assert replace.allowed is True
    assert checkpoint.allowed is True


def test_cancel_requested_parent_remains_live_for_staged_child_reconciliation():
    """Catches cancelling parents being rejected as replacement lineage anchors."""

    parent = record(
        child_intent_id="intent-child", state=RegistryState.CANCEL_REQUESTED
    )
    child = record(
        intent_id="intent-child",
        state=RegistryState.PREPARED,
        trade_id=None,
        offer_hash=None,
        parent_intent_id=parent.intent_id,
        generation=2,
    )
    snapshot = RegistrySnapshot((parent, child))

    create = authorize_mutation(
        snapshot,
        request(
            MutationKind.CREATE,
            ref=OfferReference(intent_id=child.intent_id),
        ),
    )
    reconciled = authorize_transition(
        snapshot,
        OfferReference(intent_id=child.intent_id),
        RegistryState.CREATED,
        WALLET,
        NETWORK,
    )
    assert create.allowed is True
    assert reconciled.allowed is True


@pytest.mark.parametrize(
    "blocker",
    [RegistryState.UNKNOWN, RegistryState.CONFLICTED, RegistryState.QUARANTINED],
)
def test_unresolved_registry_state_blocks_every_wallet_mutation(blocker):
    """Catches local mutation continuing while any registry row is unresolved."""

    snapshot = RegistrySnapshot(
        (
            record(),
            record(
                intent_id="blocker",
                state=blocker,
                trade_id="1" * 64,
                offer_hash="2" * 64,
            ),
        )
    )
    for kind in MutationKind:
        decision = authorize_mutation(snapshot, request(kind))
        assert decision.allowed is False
        assert decision.code is AuthorizationCode.REGISTRY_BLOCKED
        assert decision.record is snapshot.records[0]


def test_other_unresolved_row_blocks_transition_and_target_requires_reconciliation():
    """Catches transition checkpoints bypassing the registry-wide safety freeze."""

    blocker = record(
        intent_id="blocker",
        state=RegistryState.UNKNOWN,
        trade_id="1" * 64,
        offer_hash="2" * 64,
        slot_key="buy:outer",
    )
    snapshot = RegistrySnapshot((record(), blocker))
    denied = authorize_transition(
        snapshot,
        reference(),
        RegistryState.VISIBLE,
        WALLET,
        NETWORK,
    )
    assert denied.code is AuthorizationCode.REGISTRY_BLOCKED

    target = RegistrySnapshot((record(state=RegistryState.UNKNOWN),))
    idempotent_without_reconciliation = authorize_transition(
        target,
        reference(),
        RegistryState.UNKNOWN,
        WALLET,
        NETWORK,
    )
    assert (
        idempotent_without_reconciliation.code
        is AuthorizationCode.RECONCILIATION_EVIDENCE_REQUIRED
    )
    wrong = evidence(
        observed_state=RegistryState.UNKNOWN,
        outcome=None,
        source=EvidenceSource.AUTHORITATIVE_WALLET,
        network="testnet11",
        transaction_id=None,
        spend_identity=None,
        block_height=None,
    )
    assert (
        authorize_transition(
            target,
            reference(),
            RegistryState.UNKNOWN,
            WALLET,
            NETWORK,
            evidence=wrong,
        ).code
        is AuthorizationCode.EVIDENCE_MISMATCH
    )
    third_party = replace(
        wrong, network=NETWORK, source=EvidenceSource.THIRD_PARTY_OBSERVATION
    )
    assert (
        authorize_transition(
            target,
            reference(),
            RegistryState.UNKNOWN,
            WALLET,
            NETWORK,
            evidence=third_party,
        ).code
        is AuthorizationCode.RECONCILIATION_EVIDENCE_REQUIRED
    )


def test_authoritative_target_reconciliation_does_not_exclude_other_blocker():
    """Catches excluding every blocker when only the target has exact evidence."""

    target = record(state=RegistryState.UNKNOWN)
    blocker = record(
        intent_id="blocker",
        state=RegistryState.CONFLICTED,
        trade_id="1" * 64,
        offer_hash="2" * 64,
        slot_key="buy:outer",
    )
    proof = evidence(observed_state=RegistryState.VISIBLE, outcome=None)
    denied = authorize_transition(
        RegistrySnapshot((target, blocker)),
        reference(),
        RegistryState.VISIBLE,
        WALLET,
        NETWORK,
        evidence=proof,
    )
    assert denied.code is AuthorizationCode.REGISTRY_BLOCKED


def test_cancel_and_replacement_checkpoints_share_verified_child_gate():
    """Catches transition persistence where both wallet mutations are denied."""

    parent = record(child_intent_id="intent-child", state=RegistryState.VISIBLE)
    child = record(
        intent_id="intent-child",
        state=RegistryState.CREATED,
        parent_intent_id=parent.intent_id,
        generation=2,
        trade_id="1" * 64,
        offer_hash="2" * 64,
    )
    snapshot = RegistrySnapshot((parent, child))

    for kind in (MutationKind.CANCEL, MutationKind.REPLACE):
        mutation = authorize_mutation(snapshot, request(kind))
        assert mutation.code is AuthorizationCode.REPLACEMENT_CHILD_NOT_VISIBLE

    checkpoint = authorize_transition(
        snapshot,
        reference(),
        RegistryState.CANCEL_REQUESTED,
        WALLET,
        NETWORK,
    )
    assert checkpoint.code is AuthorizationCode.REPLACEMENT_CHILD_NOT_VISIBLE


@pytest.mark.parametrize(
    "outcome", [TerminalOutcome.CANCELLED, TerminalOutcome.EXPIRED]
)
def test_parent_retirement_requires_visible_child_but_proven_fill_does_not(outcome):
    """Catches lineage retirement before child proof without blocking real fills."""

    parent = record(child_intent_id="intent-child", state=RegistryState.VISIBLE)
    child = record(
        intent_id="intent-child",
        state=RegistryState.CREATED,
        parent_intent_id=parent.intent_id,
        generation=2,
        trade_id="1" * 64,
        offer_hash="2" * 64,
    )
    snapshot = RegistrySnapshot((parent, child))
    source = (
        EvidenceSource.AUTHORITATIVE_WALLET
        if outcome is TerminalOutcome.EXPIRED
        else EvidenceSource.EXACT_COIN_SPEND
    )
    retirement = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=evidence(outcome=outcome, source=source),
    )
    fill = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=evidence(outcome=TerminalOutcome.FILLED),
    )
    assert retirement.code is AuthorizationCode.REPLACEMENT_CHILD_NOT_VISIBLE
    assert fill.allowed is True


def test_terminal_transition_requires_exact_authoritative_proof():
    """Catches absence/status guesses becoming terminal registry truth."""

    snapshot = RegistrySnapshot((record(state=RegistryState.VISIBLE),))
    no_proof = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
    )
    assert no_proof.code is AuthorizationCode.TERMINAL_PROOF_REQUIRED

    wrong_amount = replace(evidence(), offered_amount_atomic="1001")
    denied = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=wrong_amount,
    )
    assert denied.code is AuthorizationCode.EVIDENCE_MISMATCH

    allowed = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=evidence(),
    )
    assert allowed.allowed is True


def test_transition_authorization_rechecks_coin_slot_and_lineage_invariants():
    """Catches reconciliation bypassing invariants enforced for wallet calls."""

    missing = record(state=RegistryState.CREATED, selected_coin_ids=())
    assert (
        authorize_transition(
            RegistrySnapshot((missing,)),
            reference(),
            RegistryState.VISIBLE,
            WALLET,
            NETWORK,
        ).code
        is AuthorizationCode.MISSING_SELECTED_COINS
    )

    candidate = record(state=RegistryState.PREPARED, trade_id=None, offer_hash=None)
    duplicate = record(intent_id="intent-2", state=RegistryState.VISIBLE)
    assert (
        authorize_transition(
            RegistrySnapshot((candidate, duplicate)),
            reference(),
            RegistryState.CREATED,
            WALLET,
            NETWORK,
        ).code
        is AuthorizationCode.DUPLICATE_ACTIVE_SLOT
    )

    parent = record(child_intent_id="intent-child", state=RegistryState.VISIBLE)
    invalid_child = record(
        intent_id="intent-child",
        state=RegistryState.PREPARED,
        trade_id=None,
        offer_hash=None,
        parent_intent_id=parent.intent_id,
        generation=3,
    )
    assert (
        authorize_transition(
            RegistrySnapshot((parent, invalid_child)),
            OfferReference(intent_id=invalid_child.intent_id),
            RegistryState.CREATED,
            WALLET,
            NETWORK,
        ).code
        is AuthorizationCode.INVALID_LINEAGE
    )


def test_terminal_proof_source_has_outcome_specific_requirements():
    """Catches third-party absence or incomplete on-chain observations as proof."""

    snapshot = RegistrySnapshot((record(state=RegistryState.CANCEL_REQUESTED),))
    incomplete = evidence(
        outcome=TerminalOutcome.CANCELLED,
        transaction_id=None,
        spend_identity=None,
        block_height=None,
    )
    assert (
        authorize_transition(
            snapshot,
            reference(),
            RegistryState.TERMINAL,
            WALLET,
            NETWORK,
            evidence=incomplete,
        ).code
        is AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT
    )

    wallet_expiry = evidence(
        outcome=TerminalOutcome.EXPIRED,
        source=EvidenceSource.AUTHORITATIVE_WALLET,
        transaction_id=None,
        spend_identity=None,
        block_height=None,
    )
    assert authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=wallet_expiry,
    ).allowed


@pytest.mark.parametrize(
    ("outcome", "source", "full_history", "owned_unlocked"),
    [
        (
            TerminalOutcome.FILLED,
            EvidenceSource.AUTHORITATIVE_WALLET,
            False,
            False,
        ),
        (
            TerminalOutcome.CANCELLED,
            EvidenceSource.AUTHORITATIVE_WALLET,
            False,
            False,
        ),
        (
            TerminalOutcome.FILLED,
            EvidenceSource.FULL_WALLET_HISTORY,
            True,
            False,
        ),
        (
            TerminalOutcome.CANCELLED,
            EvidenceSource.FULL_WALLET_HISTORY,
            True,
            True,
        ),
    ],
)
def test_filled_and_cancelled_require_chain_proof_regardless_of_source_label(
    outcome, source, full_history, owned_unlocked
):
    """Catches wallet/history labels bypassing outcome-driven chain proof."""

    proof = evidence(
        outcome=outcome,
        source=source,
        transaction_id=None,
        spend_identity=None,
        block_height=None,
        full_history=full_history,
        input_coins_owned_unlocked=owned_unlocked,
    )
    decision = authorize_transition(
        RegistrySnapshot((record(state=RegistryState.VISIBLE),)),
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=proof,
    )
    assert decision.code is AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT


@pytest.mark.parametrize(
    ("outcome", "source", "full_history", "owned_unlocked", "identity_field"),
    [
        (
            TerminalOutcome.FILLED,
            EvidenceSource.AUTHORITATIVE_WALLET,
            False,
            False,
            "transaction_id",
        ),
        (
            TerminalOutcome.CANCELLED,
            EvidenceSource.AUTHORITATIVE_WALLET,
            False,
            False,
            "spend_identity",
        ),
        (
            TerminalOutcome.FILLED,
            EvidenceSource.FULL_WALLET_HISTORY,
            True,
            False,
            "spend_identity",
        ),
        (
            TerminalOutcome.CANCELLED,
            EvidenceSource.FULL_WALLET_HISTORY,
            True,
            True,
            "transaction_id",
        ),
    ],
)
def test_exact_chain_proof_authorizes_live_outcome_across_wallet_sources(
    outcome, source, full_history, owned_unlocked, identity_field
):
    """Catches outcome proof accidentally being tied to only exact-source labels."""

    identity = {
        "transaction_id": None,
        "spend_identity": None,
        identity_field: "exact-chain-identity",
    }
    proof = evidence(
        outcome=outcome,
        source=source,
        block_height=456,
        full_history=full_history,
        input_coins_owned_unlocked=owned_unlocked,
        **identity,
    )
    assert authorize_transition(
        RegistrySnapshot((record(state=RegistryState.VISIBLE),)),
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=proof,
    ).allowed


@pytest.mark.parametrize(
    ("state", "outcome"),
    [
        (RegistryState.PREPARED, TerminalOutcome.CREATION_FAILED),
        (RegistryState.PREPARED, TerminalOutcome.REJECTED),
        (RegistryState.VISIBLE, TerminalOutcome.EXPIRED),
    ],
)
def test_non_chain_terminal_outcomes_retain_authoritative_wallet_semantics(
    state, outcome
):
    """Catches chain-proof hardening spilling into non-chain terminal outcomes."""

    item = record(
        state=state,
        trade_id=None if state is RegistryState.PREPARED else TRADE,
        offer_hash=None if state is RegistryState.PREPARED else OFFER_HASH,
    )
    proof = evidence(
        outcome=outcome,
        source=EvidenceSource.AUTHORITATIVE_WALLET,
        transaction_id=None,
        spend_identity=None,
        block_height=None,
    )
    if state is RegistryState.PREPARED:
        proof = replace(proof, sage_trade_id=None, offer_text_sha256=None)
    assert authorize_transition(
        RegistrySnapshot((item,)),
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=proof,
    ).allowed


@pytest.mark.parametrize("outcome", [TerminalOutcome.FILLED, TerminalOutcome.CANCELLED])
def test_terminal_idempotent_replay_validates_supplied_outcome_proof(outcome):
    """Catches same-state replay accepting an asserted but unproven outcome."""

    snapshot = RegistrySnapshot((record(state=RegistryState.TERMINAL),))
    insufficient = evidence(
        outcome=outcome,
        source=EvidenceSource.AUTHORITATIVE_WALLET,
        transaction_id=None,
        spend_identity=None,
        block_height=None,
    )
    denied = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=insufficient,
    )
    assert denied.code is AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT

    proven = replace(insufficient, spend_identity="spend-proven", block_height=456)
    replay = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=proven,
    )
    assert replay.allowed and replay.idempotent


def test_quarantined_cancel_requires_chain_proof_and_accepts_exact_spend():
    """Catches safe-release flags replacing cancellation transaction proof."""

    snapshot = RegistrySnapshot((record(state=RegistryState.QUARANTINED),))
    incomplete = evidence(
        outcome=TerminalOutcome.CANCELLED,
        source=EvidenceSource.FULL_WALLET_HISTORY,
        transaction_id=None,
        spend_identity=None,
        block_height=None,
        full_history=True,
        input_coins_owned_unlocked=True,
    )
    denied = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=incomplete,
    )
    assert denied.code is AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT

    proven = replace(incomplete, transaction_id="cancel-tx", block_height=456)
    assert authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=proven,
    ).allowed


@pytest.mark.parametrize(
    "changes",
    [
        {
            "source": EvidenceSource.FULL_WALLET_HISTORY,
            "full_history": False,
        },
        {
            "source": EvidenceSource.AUTHORITATIVE_WALLET,
            "full_history": True,
        },
        {
            "source": EvidenceSource.EXACT_COIN_SPEND,
            "input_coins_owned_unlocked": True,
        },
    ],
)
def test_evidence_rejects_impossible_source_flag_combinations(changes):
    """Catches proof flags being asserted by evidence sources that cannot know them."""

    with pytest.raises(ValueError):
        replace(evidence(), **changes)


def test_evidence_rejects_terminal_outcome_state_contradictions():
    """Catches one evidence object asserting terminal and nonterminal truth."""

    with pytest.raises(ValueError):
        replace(evidence(), observed_state=RegistryState.VISIBLE)
    with pytest.raises(ValueError):
        replace(evidence(), terminal_outcome=None)


@pytest.mark.parametrize(
    "outcome",
    [
        TerminalOutcome.CANCELLED,
        TerminalOutcome.EXPIRED,
        TerminalOutcome.CREATION_FAILED,
        TerminalOutcome.REJECTED,
    ],
)
def test_quarantine_safe_release_requires_full_history_and_unlocked_inputs(outcome):
    """Catches a quarantine release without an authoritative safe-to-release proof."""

    snapshot = RegistrySnapshot((record(state=RegistryState.QUARANTINED),))
    safe_release = evidence(
        outcome=outcome,
        source=EvidenceSource.FULL_WALLET_HISTORY,
        full_history=True,
        input_coins_owned_unlocked=True,
    )
    assert authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=safe_release,
    ).allowed

    unsafe_release = replace(safe_release, input_coins_owned_unlocked=False)
    assert (
        authorize_transition(
            snapshot,
            reference(),
            RegistryState.TERMINAL,
            WALLET,
            NETWORK,
            evidence=unsafe_release,
        ).code
        is AuthorizationCode.QUARANTINE_PROOF_REQUIRED
    )


def test_quarantined_fill_requires_spent_inputs_and_authoritative_chain_proof():
    """Catches filled inputs being declared both spent and owned/unlocked."""

    snapshot = RegistrySnapshot((record(state=RegistryState.QUARANTINED),))
    spent = evidence(
        outcome=TerminalOutcome.FILLED,
        source=EvidenceSource.FULL_WALLET_HISTORY,
        full_history=True,
        input_coins_owned_unlocked=False,
    )
    assert authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=spent,
    ).allowed

    impossible = replace(spent, input_coins_owned_unlocked=True)
    assert (
        authorize_transition(
            snapshot,
            reference(),
            RegistryState.TERMINAL,
            WALLET,
            NETWORK,
            evidence=impossible,
        ).code
        is AuthorizationCode.QUARANTINE_PROOF_REQUIRED
    )

    incomplete = replace(
        spent,
        transaction_id=None,
        spend_identity=None,
        block_height=None,
    )
    assert (
        authorize_transition(
            snapshot,
            reference(),
            RegistryState.TERMINAL,
            WALLET,
            NETWORK,
            evidence=incomplete,
        ).code
        is AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT
    )


def test_third_party_observation_never_proves_a_terminal_outcome():
    """Catches third-party status observations being promoted to durable truth."""

    snapshot = RegistrySnapshot((record(state=RegistryState.VISIBLE),))
    third_party = evidence(source=EvidenceSource.THIRD_PARTY_OBSERVATION)
    assert (
        authorize_transition(
            snapshot,
            reference(),
            RegistryState.TERMINAL,
            WALLET,
            NETWORK,
            evidence=third_party,
        ).code
        is AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT
    )

    impossible_fill = evidence(
        source=EvidenceSource.AUTHORITATIVE_WALLET,
        input_coins_owned_unlocked=True,
    )
    assert (
        authorize_transition(
            snapshot,
            reference(),
            RegistryState.TERMINAL,
            WALLET,
            NETWORK,
            evidence=impossible_fill,
        ).code
        is AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT
    )


def test_prepared_offer_cannot_be_classified_filled_or_cancelled():
    """Catches impossible live-offer outcomes before any submission."""

    snapshot = RegistrySnapshot(
        (record(state=RegistryState.PREPARED, trade_id=None, offer_hash=None),)
    )
    impossible = evidence(outcome=TerminalOutcome.FILLED)
    impossible = replace(
        impossible,
        sage_trade_id=None,
        offer_text_sha256=None,
    )
    decision = authorize_transition(
        snapshot,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=impossible,
    )
    assert decision.code is AuthorizationCode.TERMINAL_PROOF_INSUFFICIENT


def test_unknown_conflict_and_quarantine_can_only_resolve_with_exact_evidence():
    """Catches clearing fail-closed states from stale or partial observations."""

    for state in (RegistryState.UNKNOWN, RegistryState.CONFLICTED):
        snapshot = RegistrySnapshot((record(state=state),))
        denied = authorize_transition(
            snapshot, reference(), RegistryState.VISIBLE, WALLET, NETWORK
        )
        assert denied.code is AuthorizationCode.RECONCILIATION_EVIDENCE_REQUIRED
        proof = evidence(observed_state=RegistryState.VISIBLE, outcome=None)
        assert authorize_transition(
            snapshot,
            reference(),
            RegistryState.VISIBLE,
            WALLET,
            NETWORK,
            evidence=proof,
        ).allowed

    quarantined = RegistrySnapshot((record(state=RegistryState.QUARANTINED),))
    weak = evidence(
        outcome=TerminalOutcome.CANCELLED,
        source=EvidenceSource.AUTHORITATIVE_WALLET,
    )
    denied = authorize_transition(
        quarantined,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=weak,
    )
    assert denied.code is AuthorizationCode.QUARANTINE_PROOF_REQUIRED
    full = evidence(
        outcome=TerminalOutcome.CANCELLED,
        source=EvidenceSource.FULL_WALLET_HISTORY,
        full_history=True,
        input_coins_owned_unlocked=True,
    )
    assert authorize_transition(
        quarantined,
        reference(),
        RegistryState.TERMINAL,
        WALLET,
        NETWORK,
        evidence=full,
    ).allowed


def test_same_state_replay_is_idempotent_but_still_identity_bound():
    """Catches both duplicate side effects and cross-wallet idempotency bypasses."""

    snapshot = RegistrySnapshot((record(state=RegistryState.TERMINAL),))
    replay = authorize_transition(
        snapshot, reference(), RegistryState.TERMINAL, WALLET, NETWORK
    )
    assert replay.allowed and replay.idempotent
    denied = authorize_transition(
        snapshot, reference(), RegistryState.TERMINAL, OTHER_WALLET, NETWORK
    )
    assert denied.code is AuthorizationCode.WALLET_MISMATCH
    wrong_evidence = replace(evidence(), requested_amount_atomic="2001")
    assert (
        authorize_transition(
            snapshot,
            reference(),
            RegistryState.TERMINAL,
            WALLET,
            NETWORK,
            evidence=wrong_evidence,
        ).code
        is AuthorizationCode.EVIDENCE_MISMATCH
    )


def test_authorizers_are_total_for_malformed_public_inputs():
    """Catches bad runtime shapes raising past the wallet-mutation boundary."""

    assert (
        authorize_mutation(object(), object()).code is AuthorizationCode.INVALID_INPUT
    )
    assert (
        authorize_transition(object(), object(), "terminal", WALLET, NETWORK).code
        is AuthorizationCode.INVALID_INPUT
    )
