"""Durable stability-kernel schema and repository contract tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import database


STABILITY_TABLES = {
    "offer_intents",
    "offer_operation_journal",
    "runtime_safety_latch",
    "runtime_mutation_lease",
    "runtime_worker_delegations",
    "publication_outbox",
}

AT = "2026-08-15 12:00:00"
LATER = "2026-08-15 12:01:00"
EXPIRES = "2026-08-15 12:05:00"
AFTER_EXPIRY = "2026-08-15 12:06:00"


@pytest.fixture
def isolated_database(tmp_path: Path):
    """Redirect the real database module to one disposable SQLite file."""

    original_path = database.DB_PATH
    original_initialized_path = database._db_initialized_path
    database.close_connection()
    path = tmp_path / "stability.db"
    database.DB_PATH = str(path)
    database._db_initialized_path = ""
    try:
        yield path
    finally:
        database.close_connection()
        database.DB_PATH = original_path
        database._db_initialized_path = original_initialized_path


def _table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }


def _integrity(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])


def _drop_stability_schema(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        for table in STABILITY_TABLES:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.commit()


def _replay_migrations() -> None:
    database.close_connection()
    database._db_initialized_path = ""
    database.init_database()
    database.close_connection()


def _seed_representative_legacy_database(path: Path) -> None:
    """Create a populated pre-lifecycle database that current migrations accept."""

    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE offers (
                trade_id TEXT PRIMARY KEY,
                side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                price_xch TEXT NOT NULL,
                size_xch TEXT NOT NULL,
                size_cat TEXT NOT NULL,
                tier TEXT DEFAULT 'mid'
                    CHECK(tier IN ('inner', 'mid', 'outer', 'extreme', 'sniper')),
                status TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open', 'filled', 'cancelled', 'expired')),
                dexie_id TEXT,
                dexie_posted INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                filled_at TEXT,
                cancelled_at TEXT,
                expires_at TEXT,
                cat_asset_id TEXT NOT NULL
            );
            INSERT INTO offers (
                trade_id, side, price_xch, size_xch, size_cat, tier,
                status, created_at, cat_asset_id
            ) VALUES (
                'legacy-trade', 'buy', '0.0001', '1', '10000', 'mid',
                'open', '2025-01-01 00:00:00', 'legacy-asset'
            );

            CREATE TABLE fills (
                fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT NOT NULL,
                side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
                price_xch TEXT NOT NULL,
                size_xch TEXT NOT NULL,
                size_cat TEXT NOT NULL,
                filled_at TEXT NOT NULL,
                round_trip_id INTEGER,
                pnl_xch TEXT,
                cat_asset_id TEXT NOT NULL
            );

            CREATE TABLE config_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                key TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT
            );

            CREATE TABLE coins (
                coin_id TEXT PRIMARY KEY,
                wallet_type TEXT NOT NULL CHECK(wallet_type IN ('xch', 'cat')),
                amount_mojos INTEGER NOT NULL,
                tier TEXT,
                status TEXT NOT NULL DEFAULT 'free'
                    CHECK(status IN ('free', 'locked', 'spent', 'gone')),
                trade_id TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            """
        )


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _prepare_intent(
    intent_id: str = "intent-1",
    *,
    operation_id: str | None = None,
    event_id: str | None = None,
    offered_amount_atomic: str = "18446744073709551616000000000000000001",
    requested_amount_atomic: str = "340282366920938463463374607431768211457",
    selected_coin_ids_json=None,
):
    return database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id or f"create:{intent_id}",
        event_id=event_id or f"event:prepare:{intent_id}",
        run_id="run-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        asset_id=_sha("asset-a"),
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key="asset-a:buy:inner",
        generation=7,
        parent_intent_id=None,
        offered_amount_atomic=offered_amount_atomic,
        requested_amount_atomic=requested_amount_atomic,
        selected_coin_ids_json=(
            [_sha("coin-b"), _sha("coin-a")]
            if selected_coin_ids_json is None
            else selected_coin_ids_json
        ),
        wallet_identity_json={
            "fingerprint_sha256": _sha("wallet-a"),
            "network": "mainnet",
        },
        evidence_json={"source": "unit-test", "phase": "prepared"},
        prepared_at=AT,
    )


def _finalize_intent(
    intent_id: str = "intent-1",
    *,
    operation_id: str | None = None,
    event_id: str | None = None,
    trade_id: str | None = None,
    offer_hash: str | None = None,
    lifecycle_state: str = "created",
    outcome: str = "CONFIRMED",
    blocks_mutation: bool = False,
    evidence_json=None,
):
    return database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id or f"create:{intent_id}",
        event_id=event_id or f"event:finalize:{intent_id}",
        attempt=1,
        lifecycle_state=lifecycle_state,
        outcome=outcome,
        sage_trade_id=trade_id if trade_id is not None else _sha(f"trade:{intent_id}"),
        offer_text_sha256=(
            offer_hash if offer_hash is not None else _sha(f"offer:{intent_id}")
        ),
        wallet_identity_json={
            "fingerprint_sha256": _sha("wallet-a"),
            "network": "mainnet",
        },
        evidence_json=(
            evidence_json
            if evidence_json is not None
            else {"source": "unit-test", "phase": "finalized"}
        ),
        blocks_mutation=blocks_mutation,
        finalized_at=LATER,
    )


def test_migrates_empty_database_idempotently_with_integrity_ok(isolated_database):
    database.init_database()
    database.close_connection()

    assert STABILITY_TABLES <= _table_names(isolated_database)
    assert _integrity(isolated_database) == "ok"

    _replay_migrations()

    assert STABILITY_TABLES <= _table_names(isolated_database)
    assert _integrity(isolated_database) == "ok"


def test_migrates_current_database_without_changing_existing_rows(isolated_database):
    database.init_database()
    conn = database.get_connection()
    conn.execute(
        """INSERT INTO offers (
               trade_id, side, price_xch, size_xch, size_cat, tier,
               status, created_at, cat_asset_id, lifecycle_state
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "current-trade",
            "sell",
            "0.2",
            "2",
            "10",
            "outer",
            "open",
            AT,
            "asset-current",
            "open",
        ),
    )
    conn.commit()
    database.close_connection()
    _drop_stability_schema(isolated_database)

    _replay_migrations()

    with sqlite3.connect(isolated_database) as conn:
        existing = conn.execute(
            "SELECT side, size_xch FROM offers WHERE trade_id='current-trade'"
        ).fetchone()
    assert existing == ("sell", "2")
    assert STABILITY_TABLES <= _table_names(isolated_database)
    assert _integrity(isolated_database) == "ok"


def test_migrates_representative_legacy_database(isolated_database):
    _seed_representative_legacy_database(isolated_database)

    _replay_migrations()
    _replay_migrations()

    with sqlite3.connect(isolated_database) as conn:
        existing = conn.execute(
            "SELECT side, size_cat FROM offers WHERE trade_id='legacy-trade'"
        ).fetchone()
    assert existing == ("buy", "10000")
    assert STABILITY_TABLES <= _table_names(isolated_database)
    assert _integrity(isolated_database) == "ok"


def test_concurrent_initializers_observe_complete_stability_schema(isolated_database):
    def initialize_and_observe(_index: int) -> set[str]:
        database.init_database()
        with sqlite3.connect(isolated_database) as conn:
            return {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

    with ThreadPoolExecutor(max_workers=6) as executor:
        observed = list(executor.map(initialize_and_observe, range(18)))

    assert all(STABILITY_TABLES <= tables for tables in observed)
    assert _integrity(isolated_database) == "ok"


def test_schema_has_exact_identity_uniqueness_and_singletons(isolated_database):
    database.init_database()
    _prepare_intent("intent-a")
    _finalize_intent("intent-a", trade_id=_sha("shared-trade"), offer_hash=_sha("offer-a"))
    _prepare_intent("intent-b")

    with pytest.raises(sqlite3.IntegrityError):
        _finalize_intent(
            "intent-b",
            trade_id=_sha("shared-trade"),
            offer_hash=_sha("offer-b"),
        )

    assert database.get_offer_intent("intent-b")["lifecycle_state"] == "prepared"
    assert len(database.get_offer_operation_events("create:intent-b")) == 1

    _prepare_intent("intent-c")
    with pytest.raises(sqlite3.IntegrityError):
        _finalize_intent(
            "intent-c",
            trade_id=_sha("trade-c"),
            offer_hash=_sha("offer-a"),
        )

    conn = database.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO runtime_safety_latch (singleton_id, generation, state, "
            "blocking_operation_ids_json, updated_at) VALUES (2, 0, 'resolved', '[]', ?)",
            (AT,),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO runtime_mutation_lease (singleton_id, lease_version, active, updated_at) "
            "VALUES (2, 0, 0, ?)",
            (AT,),
        )
    conn.rollback()


def test_journal_constraints_are_idempotent_and_append_only(isolated_database):
    database.init_database()
    first = database.append_offer_operation_event(
        event_id="event-1",
        operation_id="cancel:intent-1",
        intent_id=None,
        operation_type="CANCEL",
        attempt=2,
        phase="SUBMITTED",
        outcome="SUBMITTED_UNCONFIRMED",
        request_timestamp=AT,
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"tx": _sha("tx-1")},
        transaction_id=_sha("tx-1"),
        reason_code="MEMPOOL_PENDING",
        blocks_mutation=True,
        created_at=AT,
    )
    repeated = database.append_offer_operation_event(
        event_id="event-1",
        operation_id="cancel:intent-1",
        intent_id=None,
        operation_type="CANCEL",
        attempt=2,
        phase="SUBMITTED",
        outcome="SUBMITTED_UNCONFIRMED",
        request_timestamp=AT,
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"tx": _sha("tx-1")},
        transaction_id=_sha("tx-1"),
        reason_code="MEMPOOL_PENDING",
        blocks_mutation=True,
        created_at=AT,
    )
    assert repeated == first

    with pytest.raises(ValueError, match="event_id"):
        database.append_offer_operation_event(
            event_id="event-1",
            operation_id="different-operation",
            operation_type="RECONCILE",
            attempt=1,
            phase="READ",
            outcome="CONFIRMED",
            request_timestamp=AT,
            evidence_json={},
            created_at=AT,
        )

    with pytest.raises(sqlite3.IntegrityError):
        database.append_offer_operation_event(
            event_id="event-2",
            operation_id="cancel:intent-1",
            operation_type="CANCEL",
            attempt=2,
            phase="SUBMITTED",
            outcome="UNKNOWN",
            request_timestamp=AT,
            evidence_json={},
            created_at=AT,
        )

    conn = database.get_connection()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "UPDATE offer_operation_journal SET outcome='CONFIRMED' WHERE event_id='event-1'"
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM offer_operation_journal WHERE event_id='event-1'")
    conn.rollback()


def test_prepare_and_finalize_preserve_exact_amounts_hashes_and_canonical_json(
    isolated_database,
):
    database.init_database()
    prepared = _prepare_intent()

    assert prepared["offered_amount_atomic"] == "18446744073709551616000000000000000001"
    assert prepared["requested_amount_atomic"] == "340282366920938463463374607431768211457"
    assert prepared["selected_coin_ids_json"] == json.dumps(
        sorted({_sha("coin-b"), _sha("coin-a")}),
        separators=(",", ":"),
        sort_keys=True,
    )
    assert prepared["selected_coin_ids_sha256"] == hashlib.sha256(
        prepared["selected_coin_ids_json"].encode("utf-8")
    ).hexdigest()
    assert prepared["lifecycle_state"] == "prepared"
    assert prepared["row_version"] == 0

    finalized = _finalize_intent()

    assert finalized["sage_trade_id"] == _sha("trade:intent-1")
    assert finalized["offer_text_sha256"] == _sha("offer:intent-1")
    assert finalized["lifecycle_state"] == "created"
    assert finalized["confirmed_at"] == LATER
    assert finalized["row_version"] == 1
    events = database.get_offer_operation_events("create:intent-1")
    assert [event["phase"] for event in events] == ["PREPARED", "FINALIZED"]
    assert events[-1]["evidence_sha256"] == hashlib.sha256(
        events[-1]["evidence_json"].encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_coin_ids_json", "not-json"),
        ("wallet_identity_json", "not-json"),
        ("evidence_json", "not-json"),
    ],
)
def test_prepare_validates_json_before_writing(isolated_database, field, value):
    database.init_database()
    kwargs = {
        "intent_id": "invalid-json-intent",
        "operation_id": "create:invalid-json-intent",
        "event_id": "event:invalid-json-intent",
        "run_id": "run-a",
        "wallet_fingerprint_hash": _sha("wallet-a"),
        "network": "mainnet",
        "asset_id": _sha("asset-a"),
        "side": "sell",
        "tier": "mid",
        "purpose": "ladder",
        "offered_amount_atomic": "1",
        "requested_amount_atomic": "2",
        "selected_coin_ids_json": [_sha("coin-json-validation")],
        "wallet_identity_json": {},
        "evidence_json": {},
        "prepared_at": AT,
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match="JSON"):
        database.prepare_offer_intent(**kwargs)

    assert database.get_offer_intent("invalid-json-intent") is None
    assert database.get_offer_operation_events("create:invalid-json-intent") == []


def test_finalize_invalid_json_rolls_back_intent_and_journal(isolated_database):
    database.init_database()
    _prepare_intent()

    with pytest.raises(ValueError, match="JSON"):
        _finalize_intent(evidence_json="not-json")

    assert database.get_offer_intent("intent-1")["lifecycle_state"] == "prepared"
    assert len(database.get_offer_operation_events("create:intent-1")) == 1


def test_prepare_requires_at_least_one_selected_coin_identity(isolated_database):
    database.init_database()

    with pytest.raises(ValueError, match="selected coin"):
        _prepare_intent("intent-no-coins", selected_coin_ids_json=[])

    assert database.get_offer_intent("intent-no-coins") is None


def test_confirmed_finalize_requires_identity_and_cannot_be_rebound(isolated_database):
    database.init_database()
    _prepare_intent()

    with pytest.raises(ValueError, match="trade ID and offer hash"):
        database.finalize_offer_intent(
            intent_id="intent-1",
            operation_id="create:intent-1",
            event_id="event:missing-identity",
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=None,
            offer_text_sha256=None,
            evidence_json={},
            finalized_at=LATER,
        )
    assert database.get_offer_intent("intent-1")["lifecycle_state"] == "prepared"

    _finalize_intent()
    with pytest.raises(ValueError, match="already finalized"):
        database.finalize_offer_intent(
            intent_id="intent-1",
            operation_id="create:intent-1",
            event_id="event:rebind",
            attempt=2,
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=_sha("replacement-trade"),
            offer_text_sha256=_sha("replacement-offer"),
            evidence_json={},
            finalized_at=EXPIRES,
        )
    assert database.get_offer_intent("intent-1")["sage_trade_id"] == _sha(
        "trade:intent-1"
    )


def test_oversized_evidence_is_rejected_before_journal_write(isolated_database):
    database.init_database()

    with pytest.raises(ValueError, match="evidence_json exceeds"):
        database.append_offer_operation_event(
            event_id="event:oversized",
            operation_id="reconcile:oversized",
            operation_type="RECONCILE",
            attempt=1,
            phase="READ",
            outcome="UNKNOWN",
            request_timestamp=AT,
            evidence_json={"raw": "x" * 65536},
            blocks_mutation=True,
            created_at=AT,
        )

    assert database.get_offer_operation_events("reconcile:oversized") == []


def test_latest_append_only_event_derives_unresolved_blockers(isolated_database):
    database.init_database()
    _prepare_intent()
    blockers = database.get_unresolved_offer_operation_blockers()
    assert [row["operation_id"] for row in blockers] == ["create:intent-1"]

    _finalize_intent()
    assert database.get_unresolved_offer_operation_blockers() == []

    database.append_offer_operation_event(
        event_id="event:cancel:unknown",
        operation_id="cancel:intent-1",
        intent_id="intent-1",
        operation_type="CANCEL",
        attempt=1,
        phase="RESULT",
        outcome="UNKNOWN",
        request_timestamp=LATER,
        evidence_json={"status": "timeout"},
        reason_code="RPC_TIMEOUT",
        blocks_mutation=True,
        created_at=LATER,
    )
    assert [row["operation_id"] for row in database.get_unresolved_offer_operation_blockers()] == [
        "cancel:intent-1"
    ]

    database.append_offer_operation_event(
        event_id="event:cancel:reconciled",
        operation_id="cancel:intent-1",
        intent_id="intent-1",
        operation_type="RECONCILE",
        attempt=1,
        phase="RECONCILED",
        outcome="CONFIRMED",
        request_timestamp=EXPIRES,
        evidence_json={"status": "CANCELLED"},
        blocks_mutation=False,
        created_at=EXPIRES,
    )
    assert database.get_unresolved_offer_operation_blockers() == []


def test_latch_transitions_are_generation_cas_and_preserve_blockers(isolated_database):
    database.init_database()
    initial = database.get_runtime_safety_latch()
    assert initial["state"] == "resolved"
    assert initial["generation"] == 0

    for index in (1, 2):
        database.append_offer_operation_event(
            event_id=f"event:block:{index}",
            operation_id=f"create:intent-{index}",
            operation_type="CREATE",
            attempt=1,
            phase="RESULT",
            outcome="UNKNOWN",
            request_timestamp=AT,
            evidence_json={"status": "timeout"},
            blocks_mutation=True,
            created_at=AT,
        )

    tripped = database.trip_runtime_safety_latch(
        reason_code="CREATE_UNKNOWN",
        reason="create result needs reconciliation",
        blocking_operation_ids=["create:intent-2", "create:intent-1"],
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        tripped_at=AT,
    )
    assert tripped["state"] == "tripped"
    assert tripped["generation"] == 1
    assert json.loads(tripped["blocking_operation_ids_json"]) == [
        "create:intent-1",
        "create:intent-2",
    ]

    with pytest.raises(ValueError, match="wallet binding"):
        database.trip_runtime_safety_latch(
            reason_code="OTHER_UNKNOWN",
            blocking_operation_ids=["create:intent-3"],
            wallet_fingerprint_hash=_sha("wallet-b"),
            network="mainnet",
            tripped_at=LATER,
        )

    stale = database.resolve_runtime_safety_latch(
        expected_generation=0,
        resolved_operation_ids=["create:intent-1", "create:intent-2"],
        resolved_at=LATER,
    )
    assert stale["resolved"] is False
    assert stale["reason"] == "generation_mismatch"

    incomplete = database.resolve_runtime_safety_latch(
        expected_generation=1,
        resolved_operation_ids=["create:intent-1"],
        resolved_at=LATER,
    )
    assert incomplete["resolved"] is False
    assert incomplete["reason"] == "blockers_not_resolved"

    still_unresolved = database.resolve_runtime_safety_latch(
        expected_generation=1,
        resolved_operation_ids=["create:intent-1", "create:intent-2"],
        resolved_at=LATER,
    )
    assert still_unresolved["resolved"] is False
    assert still_unresolved["reason"] == "blockers_still_unresolved"

    for index in (1, 2):
        database.append_offer_operation_event(
            event_id=f"event:resolved:{index}",
            operation_id=f"create:intent-{index}",
            operation_type="RECONCILE",
            attempt=1,
            phase="RECONCILED",
            outcome="CONFIRMED",
            request_timestamp=LATER,
            evidence_json={"status": "authoritative"},
            blocks_mutation=False,
            created_at=LATER,
        )

    resolved = database.resolve_runtime_safety_latch(
        expected_generation=1,
        resolved_operation_ids=["create:intent-2", "create:intent-1"],
        resolved_at=LATER,
    )
    assert resolved["resolved"] is True
    assert resolved["latch"]["state"] == "resolved"
    assert resolved["latch"]["generation"] == 1


def test_mutation_lease_acquire_heartbeat_release_are_compare_and_set(
    isolated_database,
):
    database.init_database()
    first = database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=EXPIRES,
        now=AT,
    )
    assert first["acquired"] is True
    assert first["lease"]["lease_version"] == 1

    competing = database.acquire_runtime_mutation_lease(
        owner_run_id="run-b",
        owner_pid=200,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=EXPIRES,
        now=LATER,
    )
    assert competing["acquired"] is False
    assert competing["reason"] == "owned_by_other_run"
    assert competing["lease"]["owner_run_id"] == "run-a"

    heartbeat = database.heartbeat_runtime_mutation_lease(
        owner_run_id="run-a",
        expected_lease_version=1,
        lease_expires_at="2026-08-15 12:10:00",
        heartbeat_at=LATER,
    )
    assert heartbeat["heartbeat"] is True
    assert heartbeat["lease"]["lease_version"] == 2

    stale_heartbeat = database.heartbeat_runtime_mutation_lease(
        owner_run_id="run-a",
        expected_lease_version=1,
        lease_expires_at="2026-08-15 12:11:00",
        heartbeat_at=EXPIRES,
    )
    assert stale_heartbeat["heartbeat"] is False
    assert stale_heartbeat["reason"] == "compare_and_set_failed"

    wrong_release = database.release_runtime_mutation_lease(
        owner_run_id="run-b", expected_lease_version=2, released_at=EXPIRES
    )
    assert wrong_release["released"] is False

    released = database.release_runtime_mutation_lease(
        owner_run_id="run-a", expected_lease_version=2, released_at=EXPIRES
    )
    assert released["released"] is True
    assert released["lease"]["active"] == 0
    assert released["lease"]["lease_version"] == 3


def test_expired_lease_takeover_requires_explicit_cas_version(isolated_database):
    database.init_database()
    first = database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=EXPIRES,
        now=AT,
    )
    assert first["acquired"] is True

    no_proof = database.acquire_runtime_mutation_lease(
        owner_run_id="run-b",
        owner_pid=200,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15 12:20:00",
        now=AFTER_EXPIRY,
        allow_expired_takeover=True,
    )
    assert no_proof["acquired"] is False
    assert no_proof["reason"] == "takeover_requires_compare_and_set"

    takeover = database.acquire_runtime_mutation_lease(
        owner_run_id="run-b",
        owner_pid=200,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15 12:20:00",
        now=AFTER_EXPIRY,
        allow_expired_takeover=True,
        expected_lease_version=1,
    )
    assert takeover["acquired"] is True
    assert takeover["reason"] == "expired_lease_taken_over"
    assert takeover["lease"]["owner_run_id"] == "run-b"
    assert takeover["lease"]["lease_version"] == 2


def test_worker_delegation_is_exactly_scoped_and_expires(isolated_database):
    database.init_database()
    issued = database.issue_worker_delegation(
        delegation_id="delegation-1",
        delegation_token_hash=_sha("token-1"),
        parent_run_id="run-a",
        operation_id="coin-prep:1",
        worker_id="worker-1",
        purpose="replacement-capacity",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        issued_at=AT,
        expires_at=EXPIRES,
        metadata_json={"asset_id": _sha("asset-a")},
    )
    assert issued["state"] == "active"

    valid = database.get_valid_worker_delegation(
        delegation_id="delegation-1",
        delegation_token_hash=_sha("token-1"),
        parent_run_id="run-a",
        operation_id="coin-prep:1",
        purpose="replacement-capacity",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        now=LATER,
    )
    assert valid is not None

    wrong_scope = database.get_valid_worker_delegation(
        delegation_id="delegation-1",
        delegation_token_hash=_sha("token-1"),
        parent_run_id="run-a",
        operation_id="coin-prep:1",
        purpose="fee-pool",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        now=LATER,
    )
    assert wrong_scope is None

    assert database.expire_worker_delegations(now=AFTER_EXPIRY) == 1
    assert (
        database.get_valid_worker_delegation(
            delegation_id="delegation-1",
            delegation_token_hash=_sha("token-1"),
            parent_run_id="run-a",
            operation_id="coin-prep:1",
            purpose="replacement-capacity",
            wallet_fingerprint_hash=_sha("wallet-a"),
            network="mainnet",
            now=AFTER_EXPIRY,
        )
        is None
    )


def test_worker_delegation_can_be_revoked_before_expiry(isolated_database):
    database.init_database()
    database.issue_worker_delegation(
        delegation_id="delegation-revoke",
        delegation_token_hash=_sha("token-revoke"),
        parent_run_id="run-a",
        operation_id="coin-prep:revoke",
        worker_id="worker-1",
        purpose="replacement-capacity",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        issued_at=AT,
        expires_at=EXPIRES,
    )

    revoked = database.revoke_worker_delegation(
        delegation_id="delegation-revoke",
        parent_run_id="run-a",
        operation_id="coin-prep:revoke",
        revoked_at=LATER,
    )

    assert revoked["revoked"] is True
    assert revoked["delegation"]["state"] == "revoked"
    assert (
        database.get_valid_worker_delegation(
            delegation_id="delegation-revoke",
            delegation_token_hash=_sha("token-revoke"),
            parent_run_id="run-a",
            operation_id="coin-prep:revoke",
            purpose="replacement-capacity",
            wallet_fingerprint_hash=_sha("wallet-a"),
            network="mainnet",
            now=LATER,
        )
        is None
    )


def test_publication_outbox_enforces_exact_idempotency_and_valid_json(
    isolated_database,
):
    database.init_database()
    queued = database.enqueue_publication_outbox(
        publication_id="publication-1",
        idempotency_key="mainnet:offer-a:epoch-1",
        intent_id="intent-not-yet-required",
        network="mainnet",
        offer_fingerprint=_sha("offer-a"),
        publication_epoch="epoch-1",
        publisher="dexie",
        payload_json={"offer_reference": _sha("offer-a")},
        queued_at=AT,
    )
    assert queued["queued"] is True
    assert queued["record"]["state"] == "queued"

    repeated = database.enqueue_publication_outbox(
        publication_id="publication-1",
        idempotency_key="mainnet:offer-a:epoch-1",
        intent_id="intent-not-yet-required",
        network="mainnet",
        offer_fingerprint=_sha("offer-a"),
        publication_epoch="epoch-1",
        publisher="dexie",
        payload_json={"offer_reference": _sha("offer-a")},
        queued_at=AT,
    )
    assert repeated["queued"] is False
    assert repeated["idempotent"] is True
    assert repeated["record"] == queued["record"]

    restarted_retry = database.enqueue_publication_outbox(
        publication_id="publication-new-local-id",
        idempotency_key="mainnet:offer-a:epoch-1",
        intent_id="intent-not-yet-required",
        network="mainnet",
        offer_fingerprint=_sha("offer-a"),
        publication_epoch="epoch-1",
        publisher="dexie",
        payload_json={"offer_reference": _sha("offer-a")},
        queued_at=LATER,
    )
    assert restarted_retry["queued"] is False
    assert restarted_retry["idempotent"] is True
    assert restarted_retry["record"]["publication_id"] == "publication-1"

    with pytest.raises(ValueError, match="idempotency"):
        database.enqueue_publication_outbox(
            publication_id="publication-2",
            idempotency_key="mainnet:offer-a:epoch-1",
            network="mainnet",
            offer_fingerprint=_sha("different-offer"),
            publication_epoch="epoch-2",
            publisher="splash",
            payload_json={},
            queued_at=AT,
        )

    with pytest.raises(ValueError, match="JSON"):
        database.enqueue_publication_outbox(
            publication_id="publication-invalid",
            idempotency_key="mainnet:invalid:epoch-1",
            network="mainnet",
            offer_fingerprint=_sha("offer-invalid"),
            publication_epoch="epoch-1",
            publisher="dexie",
            payload_json="not-json",
            queued_at=AT,
        )
    assert database.get_publication_outbox("publication-invalid") is None
