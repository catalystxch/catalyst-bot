"""Pure policy tests for the durable offer registry."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from itertools import product

import pytest

from offer_registry import (
    AuthorizationCode,
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


def test_task3_database_row_adapts_without_persistence_dependencies():
    """Catches drift from Task 3 column/state and canonical coin JSON contracts."""

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
        "offer_text_sha256": None,
        "sage_trade_id": None,
        "lifecycle_state": "creation_unknown",
    }

    adapted = offer_record_from_row(row)

    assert adapted.state is RegistryState.UNKNOWN
    assert adapted.offered_amount_atomic == "9223372036854775808"
    assert adapted.selected_coin_ids == (COIN,)
    with pytest.raises(ValueError, match="selected_coin_ids_json"):
        offer_record_from_row({**row, "selected_coin_ids_json": "not-json"})


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
    assert (
        authorize_mutation(
            RegistrySnapshot((retired_parent, child)),
            request(
                MutationKind.CREATE,
                ref=OfferReference(intent_id=child.intent_id),
            ),
        ).code
        is AuthorizationCode.INVALID_LINEAGE
    )


@pytest.mark.parametrize(
    "blocker",
    [RegistryState.UNKNOWN, RegistryState.CONFLICTED, RegistryState.QUARANTINED],
)
def test_unresolved_registry_state_blocks_every_wallet_mutation(blocker):
    """Catches local mutation continuing while any registry row is unresolved."""

    snapshot = RegistrySnapshot(
        (record(), record(intent_id="blocker", state=blocker, trade_id="1" * 64))
    )
    for kind in MutationKind:
        decision = authorize_mutation(snapshot, request(kind))
        assert decision.allowed is False
        assert decision.code is AuthorizationCode.REGISTRY_BLOCKED


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


def test_authorizers_are_total_for_malformed_public_inputs():
    """Catches bad runtime shapes raising past the wallet-mutation boundary."""

    assert (
        authorize_mutation(object(), object()).code is AuthorizationCode.INVALID_INPUT
    )
    assert (
        authorize_transition(object(), object(), "terminal", WALLET, NETWORK).code
        is AuthorizationCode.INVALID_INPUT
    )
