"""Durable public-offer publication policy and repository tests."""

import hashlib
import json
import os
import socket
import sys
from decimal import Decimal

import pytest


_SOCKET_ATTEMPTS = []


@pytest.fixture(autouse=True)
def _complete_requests_test_interface(monkeypatch):
    """Normalize legacy import stubs without enabling real network access."""

    def unexpected_post(*_args, **_kwargs):
        raise AssertionError("publication transport must be explicitly mocked")

    for module in (dexie_manager, splash_manager):
        monkeypatch.setattr(module.requests, "post", unexpected_post, raising=False)
        monkeypatch.setattr(module.requests, "Timeout", TimeoutError, raising=False)
        monkeypatch.setattr(
            module.requests,
            "ConnectionError",
            ConnectionError,
            raising=False,
        )


def _block_socket(*args, **kwargs):
    _SOCKET_ATTEMPTS.append((args, kwargs))
    raise AssertionError("publication outbox tests prohibit network access")


# Install the network tripwire before importing any CATalyst module.
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
socket.socket.connect = _block_socket
socket.socket.connect_ex = _block_socket
socket.create_connection = _block_socket

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "catalyst")),
)

try:
    from publication_outbox import (  # noqa: E402
        PublicationState,
        canonical_publication_identity,
        deterministic_retry_delay,
        redact_publication_evidence,
        transition_publication,
    )
    import publication_outbox as publication_policy  # noqa: E402
    import database  # noqa: E402
    import bot_loop  # noqa: E402
    import dexie_manager  # noqa: E402
    import splash_manager  # noqa: E402
finally:
    socket.socket.connect = _ORIGINAL_SOCKET_CONNECT
    socket.socket.connect_ex = _ORIGINAL_SOCKET_CONNECT_EX
    socket.create_connection = _ORIGINAL_CREATE_CONNECTION


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _offer_text(intent_id: str) -> str:
    return f"offer1durable-{intent_id}"


AT = "2026-08-15T12:00:00.000000Z"
LATER = "2026-08-15T12:00:05.000000Z"
LEASE_END = "2026-08-15T12:00:30.000000Z"
WITHIN_LEASE = "2026-08-15T12:00:20.000000Z"
AFTER_LEASE = "2026-08-15T12:00:31.000000Z"


@pytest.fixture
def isolated_database(tmp_path):
    original_path = database.DB_PATH
    database.DB_PATH = str(tmp_path / "publication.db")
    existing = getattr(database._local, "conn", None)
    if existing is not None:
        existing.close()
    database._local.conn = None
    database.init_database()
    try:
        yield database
    finally:
        existing = getattr(database._local, "conn", None)
        if existing is not None:
            existing.close()
        database._local.conn = None
        database.DB_PATH = original_path


def _prepare_and_confirm(
    db, *, intent_id="intent-1", generation=7, reserve_selected_coins=False
):
    offer_fingerprint = _sha(_offer_text(intent_id))
    trade_id = _sha(f"trade:{intent_id}")
    db.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id=f"run:{intent_id}",
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        asset_id=_sha("asset"),
        side="buy",
        tier="inner",
        purpose="ladder",
        coin_purpose="lifecycle" if reserve_selected_coins else None,
        slot_key=f"slot:{intent_id}",
        generation=generation,
        offered_amount_atomic="1000000000000",
        requested_amount_atomic="2000000",
        selected_coin_ids_json=[_sha(f"coin:{intent_id}")],
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"phase": "prepared"},
        prepared_at=AT,
        reserve_selected_coins=reserve_selected_coins,
    )
    intent = db.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=offer_fingerprint,
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"phase": "confirmed"},
        finalized_at=LATER,
        finalize_selected_coin_reservations=reserve_selected_coins,
    )
    return intent, trade_id, offer_fingerprint


def _prepare_claimable(db, *, intent_id="intent-1", generation=7):
    intent, trade_id, fingerprint = _prepare_and_confirm(
        db, intent_id=intent_id, generation=generation
    )
    _persist_offer_projection(db, trade_id, _offer_text(intent_id))
    return intent, trade_id, fingerprint


def _claim(db, publisher="dexie", *, owner="worker-a", token="claim-a", at=LATER):
    return db.claim_publication_outbox(
        publisher=publisher,
        owner_run_id=owner,
        claim_token=token,
        claimed_at=at,
        claim_expires_at=LEASE_END if at == LATER else "2026-08-15T12:01:00.000000Z",
    )


@pytest.fixture(autouse=True)
def _zero_socket_attempts(monkeypatch):
    before = len(_SOCKET_ATTEMPTS)
    monkeypatch.setattr(socket.socket, "connect", _block_socket)
    monkeypatch.setattr(socket.socket, "connect_ex", _block_socket)
    monkeypatch.setattr(socket, "create_connection", _block_socket)
    yield
    assert len(_SOCKET_ATTEMPTS) == before


def test_identity_is_exact_network_fingerprint_epoch_tuple():
    identity = canonical_publication_identity("mainnet", _sha("offer"), "7:dexie")

    assert identity.network == "mainnet"
    assert identity.offer_fingerprint == _sha("offer")
    assert identity.publication_epoch == "7:dexie"
    assert identity.idempotency_key == f"mainnet:{_sha('offer')}:7:dexie"

    for malformed in (
        ("MAINNET", _sha("offer"), "7:dexie"),
        (" mainnet", _sha("offer"), "7:dexie"),
        ("mainnet", "not-a-fingerprint", "7:dexie"),
        ("mainnet", _sha("offer").upper(), "7:dexie"),
        ("mainnet", _sha("offer"), True),
        ("mainnet", _sha("offer"), "x" * 257),
    ):
        with pytest.raises((TypeError, ValueError)):
            canonical_publication_identity(*malformed)


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        (PublicationState.QUEUED, PublicationState.CLAIMED),
        (PublicationState.CLAIMED, PublicationState.SUCCEEDED),
        (PublicationState.CLAIMED, PublicationState.RETRYABLE),
        (PublicationState.QUEUED, PublicationState.SUPPRESSED),
        (PublicationState.CLAIMED, PublicationState.SUPPRESSED),
        (PublicationState.RETRYABLE, PublicationState.SUPPRESSED),
    ],
)
def test_state_machine_allows_only_proof_bound_edges(source, destination):
    assert transition_publication(source, destination) is destination


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        (PublicationState.QUEUED, PublicationState.SUCCEEDED),
        (PublicationState.RETRYABLE, PublicationState.SUCCEEDED),
        (PublicationState.SUPPRESSED, PublicationState.CLAIMED),
        (PublicationState.SUCCEEDED, PublicationState.RETRYABLE),
        (PublicationState.UNRESOLVED, PublicationState.CLAIMED),
    ],
)
def test_state_machine_fails_closed_on_invalid_edges(source, destination):
    with pytest.raises(ValueError, match="transition"):
        transition_publication(source, destination)


def test_retry_backoff_is_deterministic_bounded_and_integer_only():
    assert [deterministic_retry_delay(i) for i in range(1, 6)] == [5, 10, 20, 40, 80]
    assert deterministic_retry_delay(99) == 3600
    for malformed in (True, 1.5, "2", 0, -1):
        with pytest.raises((TypeError, ValueError)):
            deterministic_retry_delay(malformed)


def test_evidence_is_redacted_size_bounded_and_offer_free():
    raw_offer = "offer1" + ("secret" * 100)
    redacted = redact_publication_evidence(
        {
            "provider_response_id": "response-1",
            "offer": raw_offer,
            "authorization_token": "token-value",
            "error": "remote said " + ("x" * 5000),
        }
    )

    rendered = repr(redacted)
    assert raw_offer not in rendered
    assert "token-value" not in rendered
    assert len(rendered) < 5000
    assert redacted["provider_response_id"] == "response-1"


@pytest.mark.parametrize(
    ("result", "expected_state"),
    [
        (
            {
                "outcome": "acknowledged",
                "provider": "dexie",
                "provider_response_id": "dexie-1",
                "echoed_idempotency_key": "expected-key",
                "request_sha256": _sha("request"),
                "response_sha256": _sha("response"),
                "status_code": 201,
            },
            PublicationState.SUCCEEDED,
        ),
        (
            {
                "outcome": "acknowledged",
                "provider": "dexie",
                "provider_response_id": "dexie-1",
                "echoed_idempotency_key": "wrong-key",
                "request_sha256": _sha("request"),
                "response_sha256": _sha("response"),
                "status_code": 201,
            },
            PublicationState.UNRESOLVED,
        ),
        (
            {
                "outcome": "no_effect",
                "provider": "dexie",
                "reason_code": "RATE_LIMITED",
                "request_sha256": _sha("request"),
                "response_sha256": _sha("response"),
                "status_code": 429,
                "acceptance": False,
            },
            PublicationState.RETRYABLE,
        ),
        (
            {
                "outcome": "ambiguous",
                "provider": "dexie",
                "reason_code": "TIMEOUT_AFTER_DISPATCH",
                "request_sha256": _sha("request"),
            },
            PublicationState.UNRESOLVED,
        ),
    ],
)
def test_provider_result_policy_retries_only_explicit_no_effect(result, expected_state):
    decision = publication_policy.classify_provider_result(
        publisher="dexie",
        result=result,
        expected_idempotency_key="expected-key",
        expected_request_sha256=_sha("request"),
    )
    assert decision.state is expected_state


def test_confirmation_transactionally_enqueues_both_destinations_by_reference(
    isolated_database,
):
    intent, trade_id, offer_fingerprint = _prepare_and_confirm(isolated_database)

    rows = isolated_database.list_publication_outbox(intent_id=intent["intent_id"])
    assert [(row["publisher"], row["publication_epoch"]) for row in rows] == [
        ("dexie", "7:dexie"),
        ("splash", "7:splash"),
    ]
    assert all(row["offer_fingerprint"] == offer_fingerprint for row in rows)
    assert all(row["payload_json"] == f'{{"offer_ref":"{trade_id}"}}' for row in rows)
    assert all("offer1" not in row["payload_json"] for row in rows)
    assert intent["publication_identity"] == f"mainnet:{offer_fingerprint}:7"


def test_finalize_rolls_back_confirmation_if_publication_insert_fails(
    isolated_database, monkeypatch
):
    isolated_database.prepare_offer_intent(
        intent_id="intent-rollback",
        operation_id="create:intent-rollback",
        event_id="create:intent-rollback:prepared",
        run_id="run:intent-rollback",
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        asset_id=_sha("asset"),
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key="slot:intent-rollback",
        generation=1,
        offered_amount_atomic="10",
        requested_amount_atomic="20",
        selected_coin_ids_json=[_sha("coin:rollback")],
        wallet_identity_json={"network": "mainnet"},
        evidence_json={},
        prepared_at=AT,
    )
    monkeypatch.setattr(
        isolated_database,
        "_insert_confirmed_publication_rows",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("injected insert failure")
        ),
    )

    with pytest.raises(RuntimeError, match="injected insert failure"):
        isolated_database.finalize_offer_intent(
            intent_id="intent-rollback",
            operation_id="create:intent-rollback",
            event_id="create:intent-rollback:confirmed",
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=_sha("trade:rollback"),
            offer_text_sha256=_sha("offer:rollback"),
            wallet_identity_json={"network": "mainnet"},
            evidence_json={},
            finalized_at=LATER,
        )

    assert (
        isolated_database.get_offer_intent("intent-rollback")["lifecycle_state"]
        == "prepared"
    )
    assert isolated_database.list_publication_outbox(intent_id="intent-rollback") == []


def test_confirmation_conflict_rolls_back_intent_but_persists_unresolved_evidence(
    isolated_database,
):
    intent_id = "intent-confirmation-conflict"
    trade_id = _sha(f"trade:{intent_id}")
    offer_fingerprint = _sha(_offer_text(intent_id))
    isolated_database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id=f"run:{intent_id}",
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        asset_id=_sha("asset"),
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key=f"slot:{intent_id}",
        generation=7,
        offered_amount_atomic="10",
        requested_amount_atomic="20",
        selected_coin_ids_json=[_sha(f"coin:{intent_id}")],
        wallet_identity_json={"network": "mainnet"},
        evidence_json={},
        prepared_at=AT,
    )
    conflict_identity = canonical_publication_identity(
        "mainnet", offer_fingerprint, "7:dexie"
    )
    isolated_database.enqueue_publication_outbox(
        publication_id="preexisting-conflict",
        idempotency_key=conflict_identity.idempotency_key,
        intent_id=intent_id,
        network="mainnet",
        offer_fingerprint=offer_fingerprint,
        publication_epoch="7:dexie",
        publisher="splash",
        payload_json={"offer_ref": trade_id},
        queued_at=AT,
    )

    with pytest.raises(ValueError, match="publication.*conflict"):
        isolated_database.finalize_offer_intent(
            intent_id=intent_id,
            operation_id=f"create:{intent_id}",
            event_id=f"create:{intent_id}:confirmed",
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=trade_id,
            offer_text_sha256=offer_fingerprint,
            wallet_identity_json={"network": "mainnet"},
            evidence_json={},
            finalized_at=LATER,
        )

    assert (
        isolated_database.get_offer_intent(intent_id)["lifecycle_state"] == "prepared"
    )
    conflict = isolated_database.get_publication_outbox("preexisting-conflict")
    assert conflict["state"] == "unresolved"
    assert conflict["last_error_sha256"] == _sha(conflict["last_error_json"])


def test_finalize_requires_exact_canonical_publication_identity(isolated_database):
    intent_id = "intent-canonical-publication"
    isolated_database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id=f"run:{intent_id}",
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        asset_id=_sha("asset"),
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key=f"slot:{intent_id}",
        generation=3,
        offered_amount_atomic="10",
        requested_amount_atomic="20",
        selected_coin_ids_json=[_sha(f"coin:{intent_id}")],
        wallet_identity_json={"network": "mainnet"},
        evidence_json={},
        prepared_at=AT,
    )
    trade_id = _sha(f"trade:{intent_id}")
    offer_fingerprint = _sha(_offer_text(intent_id))
    canonical = f"mainnet:{offer_fingerprint}:3"

    with pytest.raises(ValueError, match="publication_identity"):
        isolated_database.finalize_offer_intent(
            intent_id=intent_id,
            operation_id=f"create:{intent_id}",
            event_id=f"create:{intent_id}:hostile",
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=trade_id,
            offer_text_sha256=offer_fingerprint,
            publication_identity="publication:alias",
            wallet_identity_json={"network": "mainnet"},
            evidence_json={},
            finalized_at=LATER,
        )
    assert (
        isolated_database.get_offer_intent(intent_id)["lifecycle_state"] == "prepared"
    )

    confirmed = isolated_database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=offer_fingerprint,
        publication_identity=canonical,
        wallet_identity_json={"network": "mainnet"},
        evidence_json={},
        finalized_at=LATER,
    )
    assert confirmed["publication_identity"] == canonical


def test_exact_duplicate_is_idempotent_and_conflicting_duplicate_unresolves(
    isolated_database,
):
    identity = canonical_publication_identity("mainnet", _sha("duplicate"), "1:dexie")
    kwargs = dict(
        publication_id="pub-duplicate",
        idempotency_key=identity.idempotency_key,
        network=identity.network,
        offer_fingerprint=identity.offer_fingerprint,
        publication_epoch=identity.publication_epoch,
        publisher="dexie",
        payload_json={"offer_ref": _sha("trade")},
        queued_at=AT,
    )
    first = isolated_database.enqueue_publication_outbox(**kwargs)
    duplicate = isolated_database.enqueue_publication_outbox(**kwargs)
    assert first["queued"] is True
    assert duplicate["idempotent"] is True
    assert duplicate["record"]["publication_id"] == "pub-duplicate"

    with pytest.raises(ValueError, match="conflict"):
        isolated_database.enqueue_publication_outbox(
            **{
                **kwargs,
                "publisher": "splash",
                "payload_json": {"offer_ref": _sha("other")},
            }
        )
    conflicted = isolated_database.get_publication_outbox("pub-duplicate")
    assert conflicted["state"] == "unresolved"
    assert conflicted["last_error_sha256"] == _sha(conflicted["last_error_json"])


def test_claim_is_compare_and_set_with_exact_owner_token_generation_and_version(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    first = _claim(isolated_database)
    racing = _claim(isolated_database, owner="worker-b", token="claim-b")

    assert first["state"] == "claimed"
    assert first["claim_owner_run_id"] == "worker-a"
    assert first["claim_token"] == "claim-a"
    assert first["claim_generation"] == 1
    assert first["row_version"] == 1
    assert racing is None


def test_repost_queue_is_idempotent_while_exact_publication_is_in_flight(
    isolated_database,
):
    intent, trade_id, fingerprint = _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("request-contract"),
        dispatched_at=WITHIN_LEASE,
    )
    assert dispatched["state"] == "claimed"

    queued = isolated_database.enqueue_publication_for_trade(
        trade_id=trade_id,
        offer_fingerprint=fingerprint,
        publisher="dexie",
        force=True,
        network=intent["network"],
        queued_at=WITHIN_LEASE,
    )

    assert queued["queued"] is False
    assert queued["idempotent"] is True
    assert queued["record"]["publication_id"] == claim["publication_id"]
    assert (
        len(
            isolated_database.list_publication_outbox(
                intent_id=intent["intent_id"], publisher="dexie"
            )
        )
        == 1
    )


@pytest.mark.parametrize("projection", ["missing", "mutated"])
def test_claim_fails_closed_before_remote_when_offer_bytes_are_not_immutable(
    isolated_database, monkeypatch, projection
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    if projection == "mutated":
        _persist_offer_projection(isolated_database, trade_id, "offer1mutated-bytes")
    manager = dexie_manager.DexieManager()
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)
    manager.enable_durable_outbox(
        owner_run_id="worker-dexie",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    remote_calls = []
    monkeypatch.setattr(
        manager,
        "_post_single",
        lambda *args, **kwargs: (
            remote_calls.append((args, kwargs))
            or {"success": True, "dexie_id": "should-not-run"}
        ),
    )

    result = manager.flush_queue()
    row = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )[0]
    assert remote_calls == []
    assert result["requeued"] == 0
    assert row["state"] == "unresolved"
    assert row["last_error_sha256"] == _sha(row["last_error_json"])


def test_success_requires_current_claim_version_and_digest_binds_acknowledgement(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    completed = isolated_database.complete_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id="worker-a",
        claim_token="claim-a",
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        acknowledgement_json={
            "provider_response_id": "dexie-1",
            "offer": "offer1secret",
        },
        completed_at=WITHIN_LEASE,
    )

    assert completed["state"] == "succeeded"
    assert "offer1secret" not in completed["acknowledgement_json"]
    assert completed["acknowledgement_sha256"] == _sha(
        completed["acknowledgement_json"]
    )
    assert (
        isolated_database.complete_publication_outbox(
            publication_id=claim["publication_id"],
            owner_run_id="worker-a",
            claim_token="claim-a",
            claim_generation=claim["claim_generation"],
            expected_row_version=claim["row_version"],
            acknowledgement_json={"provider_response_id": "late"},
            completed_at=WITHIN_LEASE,
        )
        is None
    )


def test_retry_preserves_identity_payload_and_uses_injected_backoff_time(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    retried = isolated_database.retry_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id="worker-a",
        claim_token="claim-a",
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        error_json={"kind": "timeout", "offer": "offer1secret"},
        retry_at="2026-08-15T12:00:10.000000Z",
        updated_at=LATER,
    )

    assert retried["state"] == "retryable"
    assert retried["idempotency_key"] == claim["idempotency_key"]
    assert retried["payload_json"] == claim["payload_json"]
    assert retried["next_attempt_at"] == "2026-08-15T12:00:10.000000Z"
    assert "offer1secret" not in retried["last_error_json"]


def test_crash_after_remote_success_reclaims_stale_claim_with_same_identity(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    abandoned = _claim(isolated_database)
    reclaimed = _claim(
        isolated_database,
        owner="worker-b",
        token="claim-b",
        at=AFTER_LEASE,
    )

    assert reclaimed["idempotency_key"] == abandoned["idempotency_key"]
    assert reclaimed["payload_json"] == abandoned["payload_json"]
    assert reclaimed["claim_generation"] == abandoned["claim_generation"] + 1
    assert (
        isolated_database.complete_publication_outbox(
            publication_id=abandoned["publication_id"],
            owner_run_id="worker-a",
            claim_token="claim-a",
            claim_generation=abandoned["claim_generation"],
            expected_row_version=abandoned["row_version"],
            acknowledgement_json={"provider_response_id": "stale-success"},
            completed_at=AFTER_LEASE,
        )
        is None
    )


def test_terminal_suppression_invalidates_late_claim_without_wallet_side_effect(
    isolated_database,
):
    intent, _trade_id, _fingerprint = _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    conn = isolated_database._stability_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        isolated_database._suppress_publication_outbox_rows(
            conn,
            intent_id=intent["intent_id"],
            proof_json={"terminal_event_id": "proof-1", "outcome": "CANCELLED_PROVEN"},
            suppressed_at=AFTER_LEASE,
        )
        conn.commit()
    finally:
        conn.close()

    suppressed = isolated_database.get_publication_outbox(claim["publication_id"])
    assert suppressed["state"] == "suppressed"
    assert (
        isolated_database.complete_publication_outbox(
            publication_id=claim["publication_id"],
            owner_run_id="worker-a",
            claim_token="claim-a",
            claim_generation=claim["claim_generation"],
            expected_row_version=claim["row_version"],
            acknowledgement_json={"provider_response_id": "late"},
            completed_at=AFTER_LEASE,
        )
        is None
    )
    assert (
        isolated_database.get_offer_intent(intent["intent_id"])["lifecycle_state"]
        == "created"
    )


def test_terminal_reconciliation_suppresses_unresolved_publication_blocker(
    isolated_database,
):
    selected_coin_id = _sha("coin:intent-1")
    assert isolated_database.upsert_coin(
        selected_coin_id,
        "xch",
        1000000000000,
        tier="inner",
        designation="tier_active",
        assigned_tier="inner",
        purpose="lifecycle",
    )
    intent, trade_id, _fingerprint = _prepare_and_confirm(
        isolated_database, reserve_selected_coins=True
    )
    _persist_offer_projection(
        isolated_database, trade_id, _offer_text(intent["intent_id"])
    )
    claim = _claim(isolated_database)
    unresolved = isolated_database.unresolve_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        error_json={"code": "PUBLICATION_OFFER_REFERENCE_MISSING"},
        unresolved_at=WITHIN_LEASE,
    )
    assert unresolved["state"] == "unresolved"

    evidence = {"proof": "authoritative terminal state"}
    evidence_text = json.dumps(
        evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    isolated_database.commit_offer_reconciliation(
        intent_id=intent["intent_id"],
        operation_id=f"reconcile:{intent['intent_id']}",
        classification="EXPIRED_PROVEN",
        reason_code="AUTHORITATIVE_EXPIRY",
        wallet_identity_json={
            "wallet_fingerprint_hash": _sha("wallet"),
            "network": "mainnet",
        },
        evidence_json=evidence,
        evidence_sha256=_sha(evidence_text),
        reconciled_at=AFTER_LEASE,
    )

    suppressed = isolated_database.get_publication_outbox(claim["publication_id"])
    assert suppressed["state"] == "suppressed"
    snapshot = isolated_database.get_stability_startup_recovery_snapshot()
    assert snapshot["publication_issues"] == []
    assert snapshot["blocker_counts"]["publication_claims"] == 0

    # A legacy build could terminalize the intent without suppressing an
    # already-unresolved row.  Exact reconciliation replay must repair it.
    conn = isolated_database.get_connection()
    conn.execute(
        "UPDATE publication_outbox SET state='unresolved', suppression_json=NULL, "
        "suppression_sha256=NULL, updated_at=? WHERE publication_id=?",
        (AFTER_LEASE, claim["publication_id"]),
    )
    conn.commit()
    replay = isolated_database.commit_offer_reconciliation(
        intent_id=intent["intent_id"],
        operation_id=f"reconcile:{intent['intent_id']}",
        classification="EXPIRED_PROVEN",
        reason_code="AUTHORITATIVE_EXPIRY",
        wallet_identity_json={
            "wallet_fingerprint_hash": _sha("wallet"),
            "network": "mainnet",
        },
        evidence_json=evidence,
        evidence_sha256=_sha(evidence_text),
        reconciled_at=AFTER_LEASE,
    )
    assert replay["idempotent"] is True
    assert (
        isolated_database.get_publication_outbox(claim["publication_id"])["state"]
        == "suppressed"
    )


def _persist_offer_projection(db, trade_id, offer_text):
    assert db.add_offer(
        trade_id=trade_id,
        side="buy",
        price_xch=Decimal("0.5"),
        size_xch=Decimal("1"),
        size_cat=Decimal("2"),
        cat_asset_id=_sha("asset"),
        tier="inner",
    )
    assert db.update_offer_bech32(trade_id, offer_text)


@pytest.mark.parametrize(
    ("module", "manager_name", "publisher", "provider_id"),
    [
        (dexie_manager, "DexieManager", "dexie", "dexie-1"),
        (splash_manager, "SplashManager", "splash", "splash-1"),
    ],
)
def test_manager_adapters_drain_durable_claims_and_visibility_cannot_terminalize_wallet(
    isolated_database, monkeypatch, module, manager_name, publisher, provider_id
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    _persist_offer_projection(isolated_database, trade_id, offer_text)
    manager = getattr(module, manager_name)()
    monkeypatch.setattr(module.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(module.cfg, "SPLASH_ENABLED", True, raising=False)
    manager.enable_durable_outbox(
        owner_run_id=f"worker-{publisher}",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    observed = []

    def fake_post(
        payload,
        observed_trade_id=None,
        force=False,
        idempotency_key=None,
        request_contract=None,
    ):
        observed.append((payload, observed_trade_id, force, idempotency_key))
        return {
            "outcome": "acknowledged",
            "provider": publisher,
            "provider_response_id": provider_id,
            "echoed_idempotency_key": idempotency_key,
            "request_sha256": publication_policy.publication_request_sha256(
                request_contract
            ),
            "response_sha256": _sha("bounded-provider-ack"),
            "status_code": 201,
        }

    monkeypatch.setattr(manager, "_post_single", fake_post)
    result = manager.flush_queue()

    assert result["posted"] == 1
    assert observed[0][0] == offer_text
    assert observed[0][1] == trade_id
    assert observed[0][3].startswith(
        f"mainnet:{_sha(_offer_text(intent['intent_id']))}"
    )
    assert (
        isolated_database.get_offer_intent(intent["intent_id"])["lifecycle_state"]
        == "created"
    )
    assert isolated_database.get_offer(trade_id)["status"] == "open"


def test_durable_dexie_flush_stops_before_cycle_sla_budget(
    isolated_database, monkeypatch
):
    for index in range(4):
        _prepare_claimable(
            isolated_database,
            intent_id=f"budget-{index}",
            generation=index + 1,
        )

    manager = dexie_manager.DexieManager()
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 30, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_TIMEOUT", 15, raising=False)
    monkeypatch.setattr(manager, "_durable_flush_budget_seconds", 45.0, raising=False)

    elapsed = {"seconds": 0.0}
    monkeypatch.setattr(
        dexie_manager.time,
        "monotonic",
        lambda: elapsed["seconds"],
    )
    manager.enable_durable_outbox(
        owner_run_id="worker-dexie-budget",
        network="mainnet",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    observed = []

    def slow_acknowledged_post(
        _offer,
        trade_id=None,
        _force=False,
        idempotency_key=None,
        request_contract=None,
    ):
        observed.append(trade_id)
        elapsed["seconds"] += 16.0
        return {
            "outcome": "acknowledged",
            "provider": "dexie",
            "provider_response_id": f"dexie-{len(observed)}",
            "echoed_idempotency_key": idempotency_key,
            "request_sha256": publication_policy.publication_request_sha256(
                request_contract
            ),
            "response_sha256": _sha(f"response-{len(observed)}"),
            "status_code": 201,
        }

    monkeypatch.setattr(manager, "_post_single", slow_acknowledged_post)

    result = manager.flush_queue()

    assert len(observed) == 2
    assert result["posted"] == 2
    assert result["budget_exhausted"] is True
    rows = isolated_database.list_publication_outbox(publisher="dexie")
    assert sum(row["state"] == "queued" for row in rows) == 2


def test_durable_splash_flush_stops_before_cycle_sla_budget(
    isolated_database, monkeypatch
):
    for index in range(4):
        _prepare_claimable(
            isolated_database,
            intent_id=f"splash-budget-{index}",
            generation=index + 1,
        )

    manager = splash_manager.SplashManager()
    monkeypatch.setattr(splash_manager.cfg, "SPLASH_ENABLED", True, raising=False)
    monkeypatch.setattr(splash_manager.cfg, "MAX_POSTS_PER_LOOP", 30, raising=False)
    monkeypatch.setattr(splash_manager.cfg, "SPLASH_POST_TIMEOUT", 15, raising=False)
    monkeypatch.setattr(manager, "_durable_flush_budget_seconds", 45.0, raising=False)

    elapsed = {"seconds": 0.0}
    monkeypatch.setattr(
        splash_manager.time,
        "monotonic",
        lambda: elapsed["seconds"],
    )
    manager.enable_durable_outbox(
        owner_run_id="worker-splash-budget",
        network="mainnet",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    observed = []

    def slow_acknowledged_post(
        _offer,
        trade_id=None,
        _force=False,
        idempotency_key=None,
        request_contract=None,
    ):
        observed.append(trade_id)
        elapsed["seconds"] += 16.0
        return {
            "outcome": "acknowledged",
            "provider": "splash",
            "provider_response_id": f"splash-{len(observed)}",
            "echoed_idempotency_key": idempotency_key,
            "request_sha256": publication_policy.publication_request_sha256(
                request_contract
            ),
            "response_sha256": _sha(f"splash-response-{len(observed)}"),
            "status_code": 201,
        }

    monkeypatch.setattr(manager, "_post_single", slow_acknowledged_post)

    result = manager.flush_queue()

    assert len(observed) == 2
    assert result["posted"] == 2
    assert result["budget_exhausted"] is True
    rows = isolated_database.list_publication_outbox(publisher="splash")
    assert sum(row["state"] == "queued" for row in rows) == 2


def test_durable_manager_latches_ambiguous_remote_success_unresolved(
    isolated_database, monkeypatch
):
    _intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    _persist_offer_projection(
        isolated_database, trade_id, _offer_text(_intent["intent_id"])
    )
    manager = splash_manager.SplashManager()
    monkeypatch.setattr(splash_manager.cfg, "SPLASH_ENABLED", True, raising=False)
    manager.enable_durable_outbox(
        owner_run_id="worker-splash",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    monkeypatch.setattr(
        manager, "_post_single", lambda *args, **kwargs: {"success": True}
    )

    result = manager.flush_queue()
    row = isolated_database.list_publication_outbox(
        intent_id=_intent["intent_id"], publisher="splash"
    )[0]
    assert result["posted"] == 0
    assert result["failed"] == 1
    assert row["state"] == "unresolved"


def test_worker_rechecks_injected_time_after_remote_success_before_completion(
    isolated_database, monkeypatch
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    _persist_offer_projection(
        isolated_database, trade_id, _offer_text(intent["intent_id"])
    )
    observed_times = iter((LATER, AFTER_LEASE))
    manager = dexie_manager.DexieManager()
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)
    manager.enable_durable_outbox(
        owner_run_id="worker-dexie",
        now_provider=lambda: next(observed_times),
        lease_expires_provider=lambda _now: LEASE_END,
    )
    monkeypatch.setattr(
        manager,
        "_post_single",
        lambda *args, **kwargs: {"success": True, "dexie_id": "dexie-late"},
    )

    result = manager.flush_queue()
    row = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )[0]
    assert result["posted"] == 0
    assert row["state"] == "claimed"


class _TransportResponse:
    def __init__(self, status_code, payload, *, headers=None):
        import json

        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload) if payload is not None else ""
        self.content = self.text.encode("utf-8")

    def json(self):
        if self._payload is None:
            raise ValueError("malformed response")
        return self._payload


def test_expired_dispatched_claim_recovers_from_exact_dexie_readback_only(
    isolated_database,
):
    intent, trade_id, fingerprint = _prepare_claimable(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("request-contract"),
        dispatched_at=WITHIN_LEASE,
    )

    assert (
        isolated_database.recover_publication_outbox_from_provider_readback(
            publication_id=dispatched["publication_id"],
            expected_row_version=dispatched["row_version"],
            provider="dexie",
            provider_response_id="dexie-readback-1",
            observed_trade_id=trade_id,
            observed_offer_bech32="offer1wrong",
            provider_status=0,
            observed_at=AFTER_LEASE,
        )
        is None
    )
    assert (
        isolated_database.get_publication_outbox(claim["publication_id"])["state"]
        == "claimed"
    )

    recovered = isolated_database.recover_publication_outbox_from_provider_readback(
        publication_id=dispatched["publication_id"],
        expected_row_version=dispatched["row_version"],
        provider="dexie",
        provider_response_id="dexie-readback-1",
        observed_trade_id=f"0x{trade_id}",
        observed_offer_bech32=offer_text,
        provider_status=0,
        observed_at=AFTER_LEASE,
    )

    assert recovered["state"] == "succeeded"
    assert recovered["offer_fingerprint"] == fingerprint
    acknowledgement = json.loads(recovered["acknowledgement_json"])
    assert acknowledgement == {
        "code": "EXACT_PROVIDER_READBACK",
        "payload_sha256": fingerprint,
        "provider": "dexie",
        "provider_response_id": "dexie-readback-1",
        "provider_status": 0,
        "request_sha256": _sha("request-contract"),
        "trade_id": trade_id,
    }
    assert recovered["acknowledgement_sha256"] == _sha(
        recovered["acknowledgement_json"]
    )
    projected = isolated_database.get_offer(trade_id)
    assert projected["dexie_id"] == "dexie-readback-1"
    assert projected["dexie_posted"] == 1
    snapshot = isolated_database.get_stability_startup_recovery_snapshot()
    assert snapshot["blocker_counts"]["publication_claims"] == 0


def test_startup_recovers_expired_dexie_claim_from_exact_active_offer(
    isolated_database, monkeypatch
):
    intent, trade_id, _fingerprint = _prepare_claimable(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    claim = _claim(isolated_database)
    isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("request-contract"),
        dispatched_at=WITHIN_LEASE,
    )
    calls = []

    def exact_orderbook(url, **kwargs):
        calls.append((url, kwargs["params"]))
        return _TransportResponse(
            200,
            {
                "count": 1,
                "page": 1,
                "page_size": 100,
                "offers": [
                    {
                        "id": "dexie-readback-1",
                        "status": 0,
                        "trade_id": f"0x{trade_id}",
                        "offer": offer_text,
                    }
                ],
            },
        )

    monkeypatch.setattr(dexie_manager.requests, "get", exact_orderbook)
    result = dexie_manager.recover_expired_dexie_publications_at_startup(
        now_provider=lambda: AFTER_LEASE
    )

    assert result == {"checked": 1, "recovered": 1, "remaining": 0}
    assert calls == [
        (
            "https://api.dexie.space/v1/offers",
            {
                "offered": "xch",
                "requested": _sha("asset"),
                "status": 0,
                "page_size": 100,
                "page": 1,
            },
        )
    ]
    assert isolated_database.get_offer(trade_id)["dexie_id"] == "dexie-readback-1"


def test_startup_recovers_unresolved_dexie_dispatch_from_exact_active_offer(
    isolated_database, monkeypatch
):
    intent, trade_id, _fingerprint = _prepare_claimable(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("request-contract"),
        dispatched_at=WITHIN_LEASE,
    )
    unresolved = isolated_database.unresolve_publication_outbox(
        publication_id=dispatched["publication_id"],
        owner_run_id=dispatched["claim_owner_run_id"],
        claim_token=dispatched["claim_token"],
        claim_generation=dispatched["claim_generation"],
        expected_row_version=dispatched["row_version"],
        error_json={
            "code": "AMBIGUOUS_TRANSPORT_FAILURE",
            "provider": "dexie",
            "request_sha256": dispatched["request_sha256"],
        },
        unresolved_at=WITHIN_LEASE,
    )

    def exact_orderbook(_url, **_kwargs):
        return _TransportResponse(
            200,
            {
                "count": 1,
                "page": 1,
                "page_size": 100,
                "offers": [
                    {
                        "id": "dexie-readback-unresolved",
                        "status": 0,
                        "trade_id": f"0x{trade_id}",
                        "offer": offer_text,
                    }
                ],
            },
        )

    monkeypatch.setattr(dexie_manager.requests, "get", exact_orderbook)
    result = dexie_manager.recover_expired_dexie_publications_at_startup(
        now_provider=lambda: AFTER_LEASE
    )

    assert result == {"checked": 1, "recovered": 1, "remaining": 0}
    recovered = isolated_database.get_publication_outbox(unresolved["publication_id"])
    assert recovered["state"] == "succeeded"
    assert recovered["claim_owner_run_id"] is None
    assert recovered["claim_token"] is None
    assert recovered["claim_expires_at"] is None
    assert isolated_database.get_offer(trade_id)["dexie_id"] == (
        "dexie-readback-unresolved"
    )


def test_startup_readback_checks_unexpired_claim_after_owner_is_absent(
    isolated_database, monkeypatch
):
    intent, trade_id, _fingerprint = _prepare_claimable(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    claim = _claim(isolated_database)
    isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("request-contract"),
        dispatched_at=WITHIN_LEASE,
    )

    def exact_orderbook(_url, **_kwargs):
        return _TransportResponse(
            200,
            {
                "count": 1,
                "page": 1,
                "page_size": 100,
                "offers": [
                    {
                        "id": "dexie-readback-unexpired",
                        "status": 0,
                        "trade_id": f"0x{trade_id}",
                        "offer": offer_text,
                    }
                ],
            },
        )

    monkeypatch.setattr(dexie_manager.requests, "get", exact_orderbook)
    result = dexie_manager.recover_expired_dexie_publications_at_startup(
        now_provider=lambda: WITHIN_LEASE
    )

    assert result == {"checked": 1, "recovered": 1, "remaining": 0}
    recovered = isolated_database.get_publication_outbox(claim["publication_id"])
    assert recovered["state"] == "succeeded"
    assert isolated_database.get_offer(trade_id)["dexie_id"] == (
        "dexie-readback-unexpired"
    )


@pytest.mark.parametrize("publisher", ["dexie", "splash"])
def test_upgrade_restart_recovers_undispatched_publication_claim_without_active_owner(
    isolated_database, publisher
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database, publisher=publisher)

    result = isolated_database.recover_undispatched_publication_claims_at_startup(
        recovered_at=WITHIN_LEASE
    )

    recovered = isolated_database.get_publication_outbox(claim["publication_id"])
    assert result == {"examined": 1, "recovered": 1, "remaining": 0}
    assert recovered["state"] == "retryable"
    assert recovered["claim_owner_run_id"] is None
    assert recovered["claim_token"] is None
    assert recovered["claim_expires_at"] is None
    assert recovered["next_attempt_at"] == WITHIN_LEASE
    assert recovered["row_version"] == claim["row_version"] + 1
    assert json.loads(recovered["last_error_json"]) == {
        "code": "UPGRADE_RESTART_RECOVERED_UNDISPATCHED_PUBLICATION_CLAIM"
    }
    snapshot = isolated_database.get_stability_startup_recovery_snapshot()
    assert snapshot["publication_issues"] == []
    assert snapshot["blocker_counts"]["publication_claims"] == 0


def test_upgrade_restart_does_not_recover_publication_claim_from_active_owner(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    lease = isolated_database.acquire_runtime_mutation_lease(
        owner_run_id="live-owner",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        lease_expires_at="2099-01-01T00:05:00.000000Z",
        now=AT,
    )
    assert lease["acquired"] is True

    result = isolated_database.recover_undispatched_publication_claims_at_startup(
        recovered_at=WITHIN_LEASE
    )

    retained = isolated_database.get_publication_outbox(claim["publication_id"])
    assert result == {"examined": 0, "recovered": 0, "remaining": 1}
    assert retained["state"] == "claimed"
    assert retained["claim_owner_run_id"] == "worker-a"
    assert retained["claim_token"] == "claim-a"
    assert retained["claim_expires_at"] == LEASE_END
    assert retained["row_version"] == claim["row_version"]


def test_upgrade_restart_keeps_dispatched_publication_claim_fail_closed(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("upgrade-restart-request"),
        dispatched_at=WITHIN_LEASE,
    )

    result = isolated_database.recover_undispatched_publication_claims_at_startup(
        recovered_at=AFTER_LEASE
    )

    retained = isolated_database.get_publication_outbox(claim["publication_id"])
    assert result == {"examined": 1, "recovered": 0, "remaining": 1}
    assert retained == dispatched
    assert retained["state"] == "claimed"


@pytest.mark.parametrize("orphaned_state", ["claimed", "unresolved"])
def test_upgrade_restart_suppresses_orphaned_dispatched_publication_without_redispatch(
    isolated_database, orphaned_state
):
    intent, trade_id, fingerprint = _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("upgrade-restart-request"),
        dispatched_at=WITHIN_LEASE,
    )
    if orphaned_state == "unresolved":
        isolated_database.unresolve_publication_outbox(
            publication_id=dispatched["publication_id"],
            owner_run_id=dispatched["claim_owner_run_id"],
            claim_token=dispatched["claim_token"],
            claim_generation=dispatched["claim_generation"],
            expected_row_version=dispatched["row_version"],
            error_json={
                "code": "AMBIGUOUS_TRANSPORT_FAILURE",
                "provider": "dexie",
                "request_sha256": dispatched["request_sha256"],
            },
            unresolved_at=WITHIN_LEASE,
        )
    else:
        assert dispatched["state"] == "claimed"

    assert isolated_database.get_stability_startup_recovery_snapshot()[
        "publication_issues"
    ] == [claim["publication_id"]]

    result = isolated_database.suppress_orphaned_dispatched_publications_at_startup(
        recovered_at=AFTER_LEASE
    )

    assert result == {"examined": 1, "suppressed": 1, "remaining": 0}
    recovered = isolated_database.get_publication_outbox(claim["publication_id"])
    assert recovered["state"] == "suppressed"
    assert recovered["claim_owner_run_id"] is None
    assert recovered["claim_token"] is None
    assert recovered["claim_expires_at"] is None
    assert recovered["next_attempt_at"] is None
    assert recovered["terminal_at"] == AFTER_LEASE
    assert json.loads(recovered["suppression_json"]) == {
        "code": "UPGRADE_RESTART_ORPHANED_DISPATCH_SUPPRESSED",
        "prior_state": orphaned_state,
        "publisher": "dexie",
        "request_sha256": dispatched["request_sha256"],
    }
    assert (
        isolated_database.get_stability_startup_recovery_snapshot()[
            "publication_issues"
        ]
        == []
    )
    assert (
        isolated_database.claim_publication_outbox(
            publisher="dexie",
            owner_run_id="worker-b",
            claim_token="claim-b",
            claimed_at=AFTER_LEASE,
            claim_expires_at="2026-08-15T12:01:00.000000Z",
        )
        is None
    )
    with pytest.raises(ValueError, match="suppressed publication history"):
        isolated_database.enqueue_publication_for_trade(
            trade_id=trade_id,
            offer_fingerprint=fingerprint,
            publisher="dexie",
            force=True,
            network="mainnet",
            queued_at=AFTER_LEASE,
        )


def test_expired_dispatched_claim_records_provider_and_can_be_suppressed(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("expired-dispatch-request"),
        dispatched_at=WITHIN_LEASE,
    )

    assert (
        isolated_database.claim_publication_outbox(
            publisher="dexie",
            owner_run_id="replacement-worker",
            claim_token="replacement-claim",
            claimed_at=AFTER_LEASE,
            claim_expires_at="2026-08-15T12:01:00.000000Z",
        )
        is None
    )
    unresolved = isolated_database.get_publication_outbox(claim["publication_id"])
    assert unresolved["state"] == "unresolved"
    assert json.loads(unresolved["last_error_json"]) == {
        "code": "POSSIBLE_PRIOR_DISPATCH_WITHOUT_OBSERVATION",
        "provider": "dexie",
        "request_sha256": dispatched["request_sha256"],
    }

    result = isolated_database.suppress_orphaned_dispatched_publications_at_startup(
        recovered_at="2026-08-15T12:00:32.000000Z"
    )

    assert result == {"examined": 1, "suppressed": 1, "remaining": 0}


@pytest.mark.parametrize("recovery", ["readback", "suppression"])
def test_exact_legacy_expired_dispatch_evidence_remains_recoverable(
    isolated_database, recovery
):
    intent, trade_id, _fingerprint = _prepare_claimable(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("legacy-expired-dispatch-request"),
        dispatched_at=WITHIN_LEASE,
    )
    assert (
        isolated_database.claim_publication_outbox(
            publisher="dexie",
            owner_run_id="replacement-worker",
            claim_token="replacement-claim",
            claimed_at=AFTER_LEASE,
            claim_expires_at="2026-08-15T12:01:00.000000Z",
        )
        is None
    )
    legacy_error = json.dumps(
        {
            "code": "POSSIBLE_PRIOR_DISPATCH_WITHOUT_OBSERVATION",
            "request_sha256": dispatched["request_sha256"],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    conn = isolated_database.get_connection()
    conn.execute(
        "UPDATE publication_outbox SET last_error_json=?, last_error_sha256=? "
        "WHERE publication_id=?",
        (
            legacy_error,
            hashlib.sha256(legacy_error.encode("utf-8")).hexdigest(),
            claim["publication_id"],
        ),
    )
    conn.commit()
    unresolved = isolated_database.get_publication_outbox(claim["publication_id"])

    if recovery == "readback":
        recovered = isolated_database.recover_publication_outbox_from_provider_readback(
            publication_id=unresolved["publication_id"],
            expected_row_version=unresolved["row_version"],
            provider="dexie",
            provider_response_id="dexie-legacy-recovery",
            observed_trade_id=trade_id,
            observed_offer_bech32=offer_text,
            provider_status=0,
            observed_at="2026-08-15T12:00:32.000000Z",
        )
        assert recovered["state"] == "succeeded"
    else:
        result = isolated_database.suppress_orphaned_dispatched_publications_at_startup(
            recovered_at="2026-08-15T12:00:32.000000Z"
        )
        assert result == {"examined": 1, "suppressed": 1, "remaining": 0}


def test_upgrade_restart_keeps_ambiguous_publication_when_owner_is_active(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("upgrade-restart-request"),
        dispatched_at=WITHIN_LEASE,
    )
    lease = isolated_database.acquire_runtime_mutation_lease(
        owner_run_id="live-owner",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        lease_expires_at="2099-01-01T00:05:00.000000Z",
        now=AT,
    )
    assert lease["acquired"] is True

    result = isolated_database.suppress_orphaned_dispatched_publications_at_startup(
        recovered_at=AFTER_LEASE
    )

    assert result == {"examined": 0, "suppressed": 0, "remaining": 1}
    assert (
        isolated_database.get_publication_outbox(claim["publication_id"]) == dispatched
    )


def test_upgrade_restart_suppresses_orphaned_dispatch_after_dead_lease_proof(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("upgrade-restart-request"),
        dispatched_at=WITHIN_LEASE,
    )
    lease_result = isolated_database.acquire_runtime_mutation_lease(
        owner_run_id="upgrade-killed-owner",
        owner_pid=2147483647,
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        lease_expires_at="2099-01-01T00:05:00.000000Z",
        now=AT,
    )
    assert lease_result["acquired"] is True
    conn = isolated_database.get_connection()
    conn.execute(
        "UPDATE runtime_mutation_lease SET expires_at=?, heartbeat_at=?, updated_at=? "
        "WHERE singleton_id=1",
        (LEASE_END, LEASE_END, LEASE_END),
    )
    conn.commit()
    lease = isolated_database.get_runtime_mutation_lease()

    retired = isolated_database.retire_expired_dead_runtime_lease_at_startup(
        retired_at=AFTER_LEASE,
        expected_lease_version=lease["lease_version"],
        prior_owner_liveness_proven_dead=True,
    )
    result = isolated_database.suppress_orphaned_dispatched_publications_at_startup(
        recovered_at=AFTER_LEASE
    )

    assert retired["retired"] is True
    assert result == {"examined": 1, "suppressed": 1, "remaining": 0}
    recovered = isolated_database.get_publication_outbox(claim["publication_id"])
    assert recovered["state"] == "suppressed"
    retained_lease = isolated_database.get_runtime_mutation_lease()
    assert retained_lease["active"] == 0
    assert retained_lease["owner_run_id"] == "upgrade-killed-owner"
    assert retained_lease["lease_version"] == lease["lease_version"] + 1


def test_upgrade_restart_does_not_retire_stale_lease_without_dead_owner_proof(
    isolated_database,
):
    lease_result = isolated_database.acquire_runtime_mutation_lease(
        owner_run_id="possibly-live-owner",
        owner_pid=os.getpid(),
        owner_host=socket.gethostname(),
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        lease_expires_at="2099-01-01T00:05:00.000000Z",
        now=AT,
    )
    assert lease_result["acquired"] is True
    conn = isolated_database.get_connection()
    conn.execute(
        "UPDATE runtime_mutation_lease SET expires_at=?, heartbeat_at=?, updated_at=? "
        "WHERE singleton_id=1",
        (LEASE_END, LEASE_END, LEASE_END),
    )
    conn.commit()
    lease = isolated_database.get_runtime_mutation_lease()

    retained = isolated_database.retire_expired_dead_runtime_lease_at_startup(
        retired_at=AFTER_LEASE,
        expected_lease_version=lease["lease_version"],
        prior_owner_liveness_proven_dead=False,
    )

    assert retained["retired"] is False
    assert retained["reason"] == "prior_owner_liveness_unproven"
    assert isolated_database.get_runtime_mutation_lease()["active"] == 1


def test_upgrade_restart_keeps_unresolved_row_without_dispatch_evidence_fail_closed(
    isolated_database,
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    unresolved = isolated_database.unresolve_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        error_json={"code": "PUBLICATION_OFFER_REFERENCE_MISSING"},
        unresolved_at=WITHIN_LEASE,
    )

    result = isolated_database.suppress_orphaned_dispatched_publications_at_startup(
        recovered_at=AFTER_LEASE
    )

    assert result == {"examined": 1, "suppressed": 0, "remaining": 1}
    assert (
        isolated_database.get_publication_outbox(claim["publication_id"]) == unresolved
    )


@pytest.mark.parametrize(
    ("column", "malformed_value"),
    [
        ("request_sha256", "A" * 64),
        ("payload_sha256", "0" * 64),
        ("recovery_generation", 99),
        ("updated_at", "2026-08-15T13:00:20.000000+01:00"),
        ("claim_expires_at", "2026-08-15T13:00:30.000000+01:00"),
    ],
)
def test_upgrade_restart_keeps_malformed_dispatched_publication_fail_closed(
    isolated_database, column, malformed_value
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("upgrade-restart-request"),
        dispatched_at=WITHIN_LEASE,
    )
    conn = isolated_database.get_connection()
    conn.execute(
        f"UPDATE publication_outbox SET {column}=? WHERE publication_id=?",
        (malformed_value, claim["publication_id"]),
    )
    conn.commit()
    malformed = isolated_database.get_publication_outbox(claim["publication_id"])

    result = isolated_database.suppress_orphaned_dispatched_publications_at_startup(
        recovered_at=AFTER_LEASE
    )

    assert result == {"examined": 1, "suppressed": 0, "remaining": 1}
    assert (
        isolated_database.get_publication_outbox(claim["publication_id"]) == malformed
    )


@pytest.mark.parametrize(
    "malformed_error",
    [
        {
            "code": "AMBIGUOUS_TRANSPORT_FAILURE",
            "provider": "splash",
            "request_sha256": _sha("upgrade-restart-request"),
        },
        {
            "code": "AMBIGUOUS_TRANSPORT_FAILURE",
            "provider": "dexie",
            "request_sha256": _sha("different-request"),
        },
    ],
)
def test_upgrade_restart_keeps_unlinked_unresolved_error_evidence_fail_closed(
    isolated_database, malformed_error
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=_sha("upgrade-restart-request"),
        dispatched_at=WITHIN_LEASE,
    )
    unresolved = isolated_database.unresolve_publication_outbox(
        publication_id=dispatched["publication_id"],
        owner_run_id=dispatched["claim_owner_run_id"],
        claim_token=dispatched["claim_token"],
        claim_generation=dispatched["claim_generation"],
        expected_row_version=dispatched["row_version"],
        error_json={
            "code": "AMBIGUOUS_TRANSPORT_FAILURE",
            "provider": "dexie",
            "request_sha256": dispatched["request_sha256"],
        },
        unresolved_at=WITHIN_LEASE,
    )
    error_text = json.dumps(
        malformed_error, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    conn = isolated_database.get_connection()
    conn.execute(
        "UPDATE publication_outbox SET last_error_json=?, last_error_sha256=? "
        "WHERE publication_id=?",
        (
            error_text,
            hashlib.sha256(error_text.encode("utf-8")).hexdigest(),
            claim["publication_id"],
        ),
    )
    conn.commit()
    malformed = isolated_database.get_publication_outbox(claim["publication_id"])

    result = isolated_database.suppress_orphaned_dispatched_publications_at_startup(
        recovered_at=AFTER_LEASE
    )

    assert result == {"examined": 1, "suppressed": 0, "remaining": 1}
    assert malformed["state"] == unresolved["state"] == "unresolved"
    assert (
        isolated_database.get_publication_outbox(claim["publication_id"]) == malformed
    )


def test_startup_repost_skips_suppressed_offer_and_continues_batch(
    monkeypatch,
):
    suppressed_error = getattr(database, "PublicationSuppressedError", ValueError)

    class RepostDexie:
        def __init__(self):
            self.calls = []
            self.flushes = 0

        def queue_post(self, _offer, trade_id, force=False):
            self.calls.append((trade_id, force))
            if trade_id == "suppressed-trade":
                raise suppressed_error("suppressed publication history blocks new work")

        def flush_queue(self, flush_all=False):
            self.flushes += int(flush_all)

    loop = object.__new__(bot_loop.BotLoop)
    loop._running = True
    loop.dexie_manager = RepostDexie()
    loop.splash_manager = object()
    events = []
    monkeypatch.setattr(bot_loop.cfg, "DEXIE_AUTO_POST", True)
    monkeypatch.setattr(bot_loop.cfg, "SPLASH_ENABLED", False)
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", _sha("asset"))
    monkeypatch.setattr(
        database,
        "get_offers_for_repost",
        lambda **_kwargs: [
            {
                "trade_id": "suppressed-trade",
                "offer_bech32": "offer1suppressed",
                "dexie_id": None,
                "side": "buy",
            },
            {
                "trade_id": "ordinary-trade",
                "offer_bech32": "offer1ordinary",
                "dexie_id": None,
                "side": "sell",
            },
        ],
    )
    monkeypatch.setattr(
        bot_loop,
        "log_event",
        lambda level, event, message, data=None: events.append(
            (level, event, message, data)
        ),
    )

    loop._repost_active_offers_to_dexie(reason="startup_resume")

    assert loop.dexie_manager.calls == [
        ("suppressed-trade", True),
        ("ordinary-trade", True),
    ]
    assert loop.dexie_manager.flushes == 1
    assert any(event == "dexie_repost_quarantined" for _, event, _, _ in events)
    assert not any(event == "dexie_repost_failed" for _, event, _, _ in events)


@pytest.mark.parametrize(
    ("column", "malformed_value"),
    [
        ("claim_owner_run_id", " worker-a"),
        ("claim_token", "claim-a "),
        ("updated_at", "not-a-timestamp"),
        ("claim_expires_at", "2026-08-15T12:10:00.000000Z"),
        ("claim_generation", 0),
        ("recovery_generation", 1),
    ],
)
def test_upgrade_restart_keeps_malformed_undispatched_claim_fail_closed(
    isolated_database, column, malformed_value
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    conn = isolated_database.get_connection()
    conn.execute(
        f"UPDATE publication_outbox SET {column}=? WHERE publication_id=?",
        (malformed_value, claim["publication_id"]),
    )
    conn.commit()
    corrupted = isolated_database.get_publication_outbox(claim["publication_id"])

    result = isolated_database.recover_undispatched_publication_claims_at_startup(
        recovered_at=WITHIN_LEASE
    )

    assert result == {"examined": 1, "recovered": 0, "remaining": 1}
    assert (
        isolated_database.get_publication_outbox(claim["publication_id"]) == corrupted
    )


@pytest.mark.parametrize(
    ("claim_generation", "attempt_count", "row_version"),
    [
        (2, 1, 2),
        (1, 2, 2),
        (2, 2, 1),
    ],
)
def test_upgrade_restart_keeps_impossible_claim_generation_fail_closed(
    isolated_database, claim_generation, attempt_count, row_version
):
    _prepare_claimable(isolated_database)
    claim = _claim(isolated_database)
    conn = isolated_database.get_connection()
    conn.execute(
        "UPDATE publication_outbox SET claim_generation=?, attempt_count=?, "
        "row_version=? WHERE publication_id=?",
        (claim_generation, attempt_count, row_version, claim["publication_id"]),
    )
    conn.commit()
    corrupted = isolated_database.get_publication_outbox(claim["publication_id"])

    result = isolated_database.recover_undispatched_publication_claims_at_startup(
        recovered_at=WITHIN_LEASE
    )

    assert result == {"examined": 1, "recovered": 0, "remaining": 1}
    assert (
        isolated_database.get_publication_outbox(claim["publication_id"]) == corrupted
    )


@pytest.mark.parametrize(
    ("module", "manager_name", "publisher", "provider_id"),
    [
        (dexie_manager, "DexieManager", "dexie", "dexie-response-1"),
        (splash_manager, "SplashManager", "splash", "splash-response-1"),
    ],
)
def test_actual_transport_binds_request_header_bytes_and_provider_acknowledgement(
    isolated_database, monkeypatch, module, manager_name, publisher, provider_id
):
    intent, trade_id, fingerprint = _prepare_and_confirm(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    _persist_offer_projection(isolated_database, trade_id, offer_text)
    manager = getattr(module, manager_name)()
    monkeypatch.setattr(module.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(module.cfg, "SPLASH_ENABLED", True, raising=False)
    monkeypatch.setattr(module.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)
    manager.enable_durable_outbox(
        owner_run_id=f"worker-{publisher}",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        key = kwargs["headers"]["idempotency-key"]
        return _TransportResponse(
            201,
            {"id": provider_id, "idempotency_key": key},
        )

    monkeypatch.setattr(module.requests, "post", fake_post)
    result = manager.flush_queue()

    row = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher=publisher
    )[0]
    assert result["posted"] == 1
    assert len(calls) == 1
    assert calls[0][1]["json"]["offer"] == offer_text
    assert _sha(calls[0][1]["json"]["offer"]) == fingerprint
    assert calls[0][1]["headers"]["idempotency-key"] == row["idempotency_key"]
    assert row["state"] == "succeeded"
    acknowledgement = __import__("json").loads(row["acknowledgement_json"])
    assert acknowledgement["provider_response_id"] == provider_id
    assert acknowledgement["request_sha256"] == row["request_sha256"]
    assert acknowledgement["response_sha256"] == _sha(
        calls[0][0]
        and _TransportResponse(
            201, {"id": provider_id, "idempotency_key": row["idempotency_key"]}
        ).content.decode()
    )


def test_splash_http_2xx_without_remote_id_is_a_durable_acknowledgement(
    isolated_database, monkeypatch
):
    intent, trade_id, fingerprint = _prepare_and_confirm(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    _persist_offer_projection(isolated_database, trade_id, offer_text)
    manager = splash_manager.SplashManager()
    monkeypatch.setattr(splash_manager.cfg, "SPLASH_ENABLED", True, raising=False)
    monkeypatch.setattr(splash_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)
    manager.enable_durable_outbox(
        owner_run_id="worker-splash",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    response = _TransportResponse(200, {"success": True})
    calls = []

    def accepted_without_remote_id(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(splash_manager.requests, "post", accepted_without_remote_id)
    result = manager.flush_queue()

    row = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="splash"
    )[0]
    assert result["posted"] == 1
    assert len(calls) == 1
    assert calls[0][1]["json"]["offer"] == offer_text
    assert _sha(calls[0][1]["json"]["offer"]) == fingerprint
    assert row["state"] == "succeeded"
    acknowledgement = json.loads(row["acknowledgement_json"])
    assert acknowledgement["code"] == "SPLASH_HTTP_ACCEPTED"
    assert acknowledgement["provider_response_id"] == (
        f"splash-http-200:{_sha(response.content.decode())}"
    )


def test_legacy_splash_missing_id_blocker_recovers_without_redispatch(
    isolated_database,
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    _persist_offer_projection(
        isolated_database, trade_id, _offer_text(intent["intent_id"])
    )
    claim = _claim(isolated_database, publisher="splash")
    request_sha256 = _sha("legacy-splash-request")
    dispatched = isolated_database.mark_publication_dispatch_started(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        request_sha256=request_sha256,
        dispatched_at=WITHIN_LEASE,
    )
    unresolved = isolated_database.unresolve_publication_outbox(
        publication_id=dispatched["publication_id"],
        owner_run_id=dispatched["claim_owner_run_id"],
        claim_token=dispatched["claim_token"],
        claim_generation=dispatched["claim_generation"],
        expected_row_version=dispatched["row_version"],
        error_json={
            "code": "MALFORMED_PROVIDER_ACKNOWLEDGEMENT",
            "provider": "splash",
            "request_sha256": request_sha256,
        },
        unresolved_at=WITHIN_LEASE,
    )
    assert unresolved["state"] == "unresolved"
    assert isolated_database.get_stability_startup_recovery_snapshot()[
        "publication_issues"
    ] == [claim["publication_id"]]

    recovered = isolated_database.recover_legacy_splash_http_acknowledgements(
        recovered_at=AFTER_LEASE
    )

    assert recovered == 1
    row = isolated_database.get_publication_outbox(claim["publication_id"])
    assert row["state"] == "succeeded"
    acknowledgement = json.loads(row["acknowledgement_json"])
    assert acknowledgement == {
        "code": "LEGACY_SPLASH_HTTP_2XX_ACKNOWLEDGEMENT_RECOVERED",
        "provider": "splash",
        "request_sha256": request_sha256,
    }
    assert (
        isolated_database.get_stability_startup_recovery_snapshot()[
            "publication_issues"
        ]
        == []
    )


@pytest.mark.parametrize("failure", ["mismatched_echo", "timeout"])
def test_dispatched_ambiguous_response_is_unresolved_and_never_retried(
    isolated_database, monkeypatch, failure
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    _persist_offer_projection(
        isolated_database, trade_id, _offer_text(intent["intent_id"])
    )
    manager = dexie_manager.DexieManager()
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_RETRIES", 3, raising=False)
    manager.enable_durable_outbox(
        owner_run_id="worker-dexie",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if failure == "timeout":
            raise dexie_manager.requests.Timeout("timed out after dispatch")
        return _TransportResponse(
            200,
            {"id": "dexie-ambiguous", "idempotency_key": "wrong-key"},
        )

    monkeypatch.setattr(dexie_manager.requests, "post", fake_post)
    result = manager.flush_queue()
    row = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )[0]
    assert len(calls) == 1
    assert result["requeued"] == 0
    assert row["state"] == "unresolved"


def test_stale_dispatched_claim_without_observation_contract_never_replays(
    isolated_database, monkeypatch
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    _persist_offer_projection(
        isolated_database, trade_id, _offer_text(intent["intent_id"])
    )
    first = dexie_manager.DexieManager()
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)
    first.enable_durable_outbox(
        owner_run_id="worker-first",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    calls = []

    def accepted_post(url, **kwargs):
        calls.append((url, kwargs))
        key = kwargs["headers"]["idempotency-key"]
        return _TransportResponse(201, {"id": "dexie-1", "idempotency_key": key})

    monkeypatch.setattr(dexie_manager.requests, "post", accepted_post)
    monkeypatch.setattr(
        dexie_manager,
        "complete_publication_outbox",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("crash after remote success")
        ),
    )
    with pytest.raises(RuntimeError, match="crash after remote success"):
        first.flush_queue()
    assert len(calls) == 1

    second = dexie_manager.DexieManager()
    second.enable_durable_outbox(
        owner_run_id="worker-second",
        now_provider=lambda: AFTER_LEASE,
        lease_expires_provider=lambda _now: "2026-08-15T12:01:00.000000Z",
    )
    result = second.flush_queue()
    row = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )[0]
    assert len(calls) == 1
    assert result["posted"] == 0
    assert row["state"] == "unresolved"

    before = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )
    for force in (False, True):
        with pytest.raises(ValueError, match="unresolved"):
            second.queue_post(_offer_text(intent["intent_id"]), trade_id, force=force)
    after = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )
    assert [item["publication_id"] for item in after] == [
        item["publication_id"] for item in before
    ]
    assert second.flush_queue()["posted"] == 0
    assert len(calls) == 1


def test_legacy_plaintext_queue_without_authoritative_intent_fails_closed(
    isolated_database, monkeypatch
):
    trade_id = _sha("legacy-trade")
    offer_text = "offer1legacy-durable"
    _persist_offer_projection(isolated_database, trade_id, offer_text)
    manager = dexie_manager.DexieManager()
    manager.queue_post(offer_text, trade_id, force=True)
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)
    calls = []

    def accepted_post(url, **kwargs):
        calls.append((url, kwargs))
        key = kwargs["headers"]["idempotency-key"]
        return _TransportResponse(201, {"id": "dexie-legacy", "idempotency_key": key})

    monkeypatch.setattr(dexie_manager.requests, "post", accepted_post)
    with pytest.raises(ValueError, match="authoritative intent"):
        manager.enable_durable_outbox(
            owner_run_id="legacy-worker",
            network="mainnet",
            now_provider=lambda: LATER,
            lease_expires_provider=lambda _now: LEASE_END,
        )

    assert manager._queue == []
    assert isolated_database.list_publication_outbox(publisher="dexie") == []
    assert calls == []


def test_intentional_reposts_allocate_monotonic_durable_publisher_epochs(
    isolated_database, monkeypatch
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    _persist_offer_projection(isolated_database, trade_id, offer_text)
    manager = dexie_manager.DexieManager()
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)

    def accepted_post(url, **kwargs):
        key = kwargs["headers"]["idempotency-key"]
        return _TransportResponse(201, {"id": "dexie-repost", "idempotency_key": key})

    monkeypatch.setattr(dexie_manager.requests, "post", accepted_post)
    manager.enable_durable_outbox(
        owner_run_id="repost-worker",
        network="mainnet",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    assert manager.flush_queue()["posted"] == 1

    manager.queue_post(offer_text, trade_id, force=False)
    assert (
        len(
            isolated_database.list_publication_outbox(
                intent_id=intent["intent_id"], publisher="dexie"
            )
        )
        == 1
    )

    manager.queue_post(offer_text, trade_id, force=True)
    assert manager._queue == []
    rows = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )
    assert [row["publication_epoch"] for row in rows] == [
        "7:dexie",
        "repost-0000000001:dexie",
    ]
    assert manager.flush_queue()["posted"] == 1

    manager.queue_post(offer_text, trade_id, force=True)
    rows = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )
    assert [row["publication_epoch"] for row in rows] == [
        "7:dexie",
        "repost-0000000001:dexie",
        "repost-0000000002:dexie",
    ]


def test_visible_repost_keeps_intent_link_and_task9_suppresses_late_worker(
    isolated_database, monkeypatch
):
    selected_coin_id = _sha("coin:intent-1")
    assert isolated_database.upsert_coin(
        selected_coin_id,
        "xch",
        1000000000000,
        tier="inner",
        designation="tier_active",
        assigned_tier="inner",
        purpose="lifecycle",
    )
    intent, trade_id, fingerprint = _prepare_and_confirm(
        isolated_database, reserve_selected_coins=True
    )
    offer_text = _offer_text(intent["intent_id"])
    _persist_offer_projection(isolated_database, trade_id, offer_text)
    manager = dexie_manager.DexieManager()
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)

    def accepted_post(url, **kwargs):
        key = kwargs["headers"]["idempotency-key"]
        return _TransportResponse(201, {"id": "dexie-visible", "idempotency_key": key})

    monkeypatch.setattr(dexie_manager.requests, "post", accepted_post)
    manager.enable_durable_outbox(
        owner_run_id="visible-worker",
        network="mainnet",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    assert manager.flush_queue()["posted"] == 1
    isolated_database.record_offer_intent_visibility(
        intent["intent_id"],
        publication_identity=intent["publication_identity"],
        visible_at="2026-08-15T12:00:06.000000Z",
    )
    manager.queue_post(offer_text, trade_id, force=True)
    rows = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )
    assert len(rows) == 2
    assert rows[-1]["intent_id"] == intent["intent_id"]
    assert rows[-1]["offer_fingerprint"] == fingerprint
    claim = isolated_database.claim_publication_outbox(
        publisher="dexie",
        owner_run_id="late-visible-worker",
        claim_token="late-visible-claim",
        claimed_at="2026-08-15T12:00:07.000000Z",
        claim_expires_at="2026-08-15T12:00:30.000000Z",
    )
    assert claim["publication_id"] == rows[-1]["publication_id"]

    evidence = {"proof": "authoritative expiry"}
    evidence_text = json.dumps(
        evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    isolated_database.commit_offer_reconciliation(
        intent_id=intent["intent_id"],
        operation_id=f"reconcile:{intent['intent_id']}",
        classification="EXPIRED_PROVEN",
        reason_code="AUTHORITATIVE_EXPIRY",
        wallet_identity_json={
            "wallet_fingerprint_hash": _sha("wallet"),
            "network": "mainnet",
        },
        evidence_json=evidence,
        evidence_sha256=_sha(evidence_text),
        reconciled_at="2026-08-15T12:00:08.000000Z",
    )
    suppressed = isolated_database.get_publication_outbox(claim["publication_id"])
    assert suppressed["state"] == "suppressed"
    assert (
        isolated_database.complete_publication_outbox(
            publication_id=claim["publication_id"],
            owner_run_id=claim["claim_owner_run_id"],
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
            expected_row_version=claim["row_version"],
            acknowledgement_json={"provider_response_id": "too-late"},
            completed_at="2026-08-15T12:00:09.000000Z",
        )
        is None
    )


def test_canonical_request_digest_binds_claim_rewards_and_rejects_payload_drift():
    builder = getattr(
        publication_policy, "canonical_publication_request_contract", None
    )
    assert builder is not None, "canonical request-contract builder is required"
    common = {
        "publisher": "dexie",
        "offer_bech32": "offer1request-contract",
        "idempotency_key": "mainnet:fingerprint:epoch",
        "destination_url": "https://api.dexie.space/v1/offers",
        "bot_tag": "catalyst-test",
    }
    enabled = builder(**common, claim_rewards=True)
    disabled = builder(**common, claim_rewards=False)
    enabled_digest = publication_policy.publication_request_sha256(enabled)
    disabled_digest = publication_policy.publication_request_sha256(disabled)
    assert enabled_digest != disabled_digest

    changed = json.loads(json.dumps(enabled))
    changed["body"]["claim_rewards"] = False
    changed_digest = publication_policy.publication_request_sha256(changed)
    assert changed_digest == disabled_digest
    assert changed_digest != enabled_digest

    bool_version = json.loads(json.dumps(enabled))
    bool_version["schema_version"] = True
    with pytest.raises(ValueError, match="version"):
        publication_policy.publication_request_sha256(bool_version)


def test_dexie_dispatch_uses_one_claim_rewards_contract_despite_config_drift(
    isolated_database, monkeypatch
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    offer_text = _offer_text(intent["intent_id"])
    _persist_offer_projection(isolated_database, trade_id, offer_text)
    manager = dexie_manager.DexieManager()
    monkeypatch.setattr(dexie_manager.cfg, "DEXIE_POST_ENABLED", True, raising=False)
    monkeypatch.setattr(dexie_manager.cfg, "MAX_POSTS_PER_LOOP", 1, raising=False)
    monkeypatch.setattr(
        dexie_manager.cfg, "DEXIE_AUTO_CLAIM_REWARDS", True, raising=False
    )
    manager.enable_durable_outbox(
        owner_run_id="contract-worker",
        network="mainnet",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    original_mark = dexie_manager.mark_publication_dispatch_started

    def mark_then_change_config(**kwargs):
        marked = original_mark(**kwargs)
        monkeypatch.setattr(
            dexie_manager.cfg, "DEXIE_AUTO_CLAIM_REWARDS", False, raising=False
        )
        return marked

    monkeypatch.setattr(
        dexie_manager, "mark_publication_dispatch_started", mark_then_change_config
    )
    calls = []

    def accepted_post(url, **kwargs):
        calls.append((url, kwargs))
        key = kwargs["headers"]["idempotency-key"]
        return _TransportResponse(201, {"id": "dexie-contract", "idempotency_key": key})

    monkeypatch.setattr(dexie_manager.requests, "post", accepted_post)
    assert manager.flush_queue()["posted"] == 1
    assert calls[0][1]["json"].get("claim_rewards") is True
    row = isolated_database.list_publication_outbox(
        intent_id=intent["intent_id"], publisher="dexie"
    )[0]
    contract = publication_policy.canonical_publication_request_contract(
        publisher="dexie",
        offer_bech32=offer_text,
        idempotency_key=row["idempotency_key"],
        destination_url=calls[0][0],
        bot_tag=dexie_manager.cfg.BOT_TAG,
        claim_rewards=True,
    )
    assert row["request_sha256"] == publication_policy.publication_request_sha256(
        contract
    )


def test_startup_enables_durable_workers_before_gate_and_drains_after_gate():
    events = []

    class Gate:
        def set(self):
            events.append("startup_gate")

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = False
    loop._startup_complete = Gate()
    loop._startup_sync = lambda: events.append("startup_recovery")
    loop._enable_durable_publication_outbox = lambda: events.append("enable_outbox")
    loop._flush_public_offer_queues = lambda: events.append("drain_outbox")
    loop._set_state = lambda **kwargs: None

    loop._run_loop()

    assert events == [
        "startup_recovery",
        "enable_outbox",
        "startup_gate",
        "drain_outbox",
    ]


def test_startup_publishes_reconciled_offer_counts_before_runtime_gate():
    events = []

    class Gate:
        def set(self):
            events.append("startup_gate")

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._running = False
    loop._startup_complete = Gate()
    loop._startup_sync = lambda: {
        "open_buys": 36,
        "open_sells": 36,
    }
    loop._enable_durable_publication_outbox = lambda: events.append("enable_outbox")
    loop._flush_public_offer_queues = lambda: events.append("drain_outbox")

    def record_state(**updates):
        if "open_buys" in updates or "open_sells" in updates:
            events.append(
                ("offer_counts", updates["open_buys"], updates["open_sells"])
            )

    loop._set_state = record_state

    loop._run_loop()

    assert events == [
        ("offer_counts", 36, 36),
        "enable_outbox",
        "startup_gate",
        "drain_outbox",
    ]
