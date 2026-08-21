"""Durable public-offer publication policy and repository tests."""

import hashlib
import os
import socket
import sys
from decimal import Decimal

import pytest


_SOCKET_ATTEMPTS = []


def _block_socket(*args, **kwargs):
    _SOCKET_ATTEMPTS.append((args, kwargs))
    raise AssertionError("publication outbox tests prohibit network access")


# Install the network tripwire before importing any CATalyst module.
socket.socket.connect = _block_socket
socket.socket.connect_ex = _block_socket
socket.create_connection = _block_socket

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "catalyst")),
)

from publication_outbox import (  # noqa: E402
    PublicationState,
    canonical_publication_identity,
    deterministic_retry_delay,
    redact_publication_evidence,
    transition_publication,
)
import database  # noqa: E402
import bot_loop  # noqa: E402
import dexie_manager  # noqa: E402
import splash_manager  # noqa: E402


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _prepare_and_confirm(db, *, intent_id="intent-1", generation=7):
    offer_fingerprint = _sha(f"offer:{intent_id}")
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
        slot_key=f"slot:{intent_id}",
        generation=generation,
        offered_amount_atomic="1000000000000",
        requested_amount_atomic="2000000",
        selected_coin_ids_json=[_sha(f"coin:{intent_id}")],
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"phase": "prepared"},
        prepared_at=AT,
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
    )
    return intent, trade_id, offer_fingerprint


def _claim(db, publisher="dexie", *, owner="worker-a", token="claim-a", at=LATER):
    return db.claim_publication_outbox(
        publisher=publisher,
        owner_run_id=owner,
        claim_token=token,
        claimed_at=at,
        claim_expires_at=LEASE_END if at == LATER else "2026-08-15T12:01:00.000000Z",
    )


@pytest.fixture(autouse=True)
def _zero_socket_attempts():
    before = len(_SOCKET_ATTEMPTS)
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
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected insert failure")),
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

    assert isolated_database.get_offer_intent("intent-rollback")["lifecycle_state"] == "prepared"
    assert isolated_database.list_publication_outbox(intent_id="intent-rollback") == []


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
            **{**kwargs, "publisher": "splash", "payload_json": {"offer_ref": _sha("other")}}
        )
    conflicted = isolated_database.get_publication_outbox("pub-duplicate")
    assert conflicted["state"] == "unresolved"
    assert conflicted["last_error_sha256"] == _sha(conflicted["last_error_json"])


def test_claim_is_compare_and_set_with_exact_owner_token_generation_and_version(
    isolated_database,
):
    _prepare_and_confirm(isolated_database)
    first = _claim(isolated_database)
    racing = _claim(isolated_database, owner="worker-b", token="claim-b")

    assert first["state"] == "claimed"
    assert first["claim_owner_run_id"] == "worker-a"
    assert first["claim_token"] == "claim-a"
    assert first["claim_generation"] == 1
    assert first["row_version"] == 1
    assert racing is None


def test_success_requires_current_claim_version_and_digest_binds_acknowledgement(
    isolated_database,
):
    _prepare_and_confirm(isolated_database)
    claim = _claim(isolated_database)
    completed = isolated_database.complete_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id="worker-a",
        claim_token="claim-a",
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        acknowledgement_json={"provider_response_id": "dexie-1", "offer": "offer1secret"},
        completed_at=WITHIN_LEASE,
    )

    assert completed["state"] == "succeeded"
    assert "offer1secret" not in completed["acknowledgement_json"]
    assert completed["acknowledgement_sha256"] == _sha(completed["acknowledgement_json"])
    assert isolated_database.complete_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id="worker-a",
        claim_token="claim-a",
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        acknowledgement_json={"provider_response_id": "late"},
        completed_at=WITHIN_LEASE,
    ) is None


def test_retry_preserves_identity_payload_and_uses_injected_backoff_time(
    isolated_database,
):
    _prepare_and_confirm(isolated_database)
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
    _prepare_and_confirm(isolated_database)
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
    assert isolated_database.complete_publication_outbox(
        publication_id=abandoned["publication_id"],
        owner_run_id="worker-a",
        claim_token="claim-a",
        claim_generation=abandoned["claim_generation"],
        expected_row_version=abandoned["row_version"],
        acknowledgement_json={"provider_response_id": "stale-success"},
        completed_at=AFTER_LEASE,
    ) is None


def test_terminal_suppression_invalidates_late_claim_without_wallet_side_effect(
    isolated_database,
):
    intent, _trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
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
    assert isolated_database.complete_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id="worker-a",
        claim_token="claim-a",
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        acknowledgement_json={"provider_response_id": "late"},
        completed_at=AFTER_LEASE,
    ) is None
    assert isolated_database.get_offer_intent(intent["intent_id"])["lifecycle_state"] == "created"


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
    ("module", "manager_name", "publisher", "response"),
    [
        (dexie_manager, "DexieManager", "dexie", {"success": True, "dexie_id": "dexie-1"}),
        (splash_manager, "SplashManager", "splash", {"success": True, "provider_response_id": "splash-1"}),
    ],
)
def test_manager_adapters_drain_durable_claims_and_visibility_cannot_terminalize_wallet(
    isolated_database, monkeypatch, module, manager_name, publisher, response
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    offer_text = "offer1durable-publication"
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

    def fake_post(payload, observed_trade_id=None, force=False, idempotency_key=None):
        observed.append((payload, observed_trade_id, force, idempotency_key))
        return dict(response)

    monkeypatch.setattr(manager, "_post_single", fake_post)
    result = manager.flush_queue()

    assert result["posted"] == 1
    assert observed[0][0] == offer_text
    assert observed[0][1] == trade_id
    assert observed[0][3].startswith(f"mainnet:{_sha(f'offer:{intent['intent_id']}')}")
    assert isolated_database.get_offer_intent(intent["intent_id"])["lifecycle_state"] == "created"
    assert isolated_database.get_offer(trade_id)["status"] == "open"


def test_durable_manager_keeps_ambiguous_remote_success_retryable(
    isolated_database, monkeypatch
):
    _intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    _persist_offer_projection(isolated_database, trade_id, "offer1ambiguous")
    manager = splash_manager.SplashManager()
    monkeypatch.setattr(splash_manager.cfg, "SPLASH_ENABLED", True, raising=False)
    manager.enable_durable_outbox(
        owner_run_id="worker-splash",
        now_provider=lambda: LATER,
        lease_expires_provider=lambda _now: LEASE_END,
    )
    monkeypatch.setattr(manager, "_post_single", lambda *args, **kwargs: {"success": True})

    result = manager.flush_queue()
    row = isolated_database.list_publication_outbox(
        intent_id=_intent["intent_id"], publisher="splash"
    )[0]
    assert result["posted"] == 0
    assert result["failed"] == 1
    assert row["state"] == "retryable"


def test_worker_rechecks_injected_time_after_remote_success_before_completion(
    isolated_database, monkeypatch
):
    intent, trade_id, _fingerprint = _prepare_and_confirm(isolated_database)
    _persist_offer_projection(isolated_database, trade_id, "offer1late-success")
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
