"""Durable stability-kernel schema and repository contract tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import database


STABILITY_TABLES = {
    "offer_intents",
    "offer_operation_journal",
    "offer_reconciliation_coin_outcomes",
    "offer_cancel_cohort_manifests",
    "offer_cancel_effect_claims",
    "runtime_safety_latch",
    "runtime_mutation_lease",
    "runtime_worker_delegations",
    "publication_outbox",
    "stability_migration_watermarks",
}

AT = "2026-08-15T12:00:00.000000Z"
LATER = "2026-08-15T12:01:00.000000Z"
EXPIRES = "2026-08-15T12:05:00.000000Z"
AFTER_EXPIRY = "2026-08-15T12:06:00.000000Z"
_DEFAULT = object()


@pytest.fixture
def isolated_database(tmp_path: Path, monkeypatch):
    """Redirect the real database module to one disposable SQLite file."""

    original_path = database.DB_PATH
    original_initialized_path = database._db_initialized_path
    database.close_connection()
    path = tmp_path / "stability.db"
    database.DB_PATH = str(path)
    database._db_initialized_path = ""
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: AT, raising=False)
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
    generation=7,
    slot_key="asset-a:buy:inner",
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
        slot_key=slot_key,
        generation=generation,
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
    trade_id=_DEFAULT,
    offer_hash=_DEFAULT,
    lifecycle_state: str = "created",
    outcome: str = "CONFIRMED",
    blocks_mutation: bool = False,
    evidence_json=None,
    publication_identity: str | None = None,
    child_intent_id: str | None = None,
    attempt=1,
    reason_code: str | None = None,
):
    return database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id or f"create:{intent_id}",
        event_id=event_id or f"event:finalize:{intent_id}",
        attempt=attempt,
        lifecycle_state=lifecycle_state,
        outcome=outcome,
        sage_trade_id=(
            _sha(f"trade:{intent_id}") if trade_id is _DEFAULT else trade_id
        ),
        offer_text_sha256=(
            _sha(f"offer:{intent_id}") if offer_hash is _DEFAULT else offer_hash
        ),
        publication_identity=publication_identity,
        child_intent_id=child_intent_id,
        wallet_identity_json={
            "fingerprint_sha256": _sha("wallet-a"),
            "network": "mainnet",
        },
        evidence_json=(
            evidence_json
            if evidence_json is not None
            else {"source": "unit-test", "phase": "finalized"}
        ),
        reason_code=reason_code,
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


def test_authoritative_coin_outcomes_are_append_only_and_coin_indexed(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        tables = _table_names(isolated_database)
        indexes = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='index' AND sql IS NOT NULL"
            )
        }
        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name='offer_reconciliation_coin_outcomes'"
            )
        }

    assert "offer_reconciliation_coin_outcomes" in tables
    assert "idx_offer_reconciliation_coin_outcomes_latest" in indexes
    assert (
        "(coin_id, outcome_sequence)"
        in indexes["idx_offer_reconciliation_coin_outcomes_latest"]
    )
    assert triggers == {
        "offer_reconciliation_coin_outcomes_no_update",
        "offer_reconciliation_coin_outcomes_no_delete",
    }


def test_prior_task9_schema_backfills_exact_terminal_coin_outcome_once(
    isolated_database,
):
    database.init_database()
    intent_id = "migration-terminal-coin-outcome"
    trade_id = _sha("migration-terminal-trade")
    coin_id = _sha("migration-terminal-coin")
    wallet_hash = _sha("migration-terminal-wallet")
    asset_id = _sha("migration-terminal-asset")
    wallet_identity = {
        "wallet_fingerprint_hash": wallet_hash,
        "network": "mainnet",
    }
    assert database.upsert_coin(
        coin_id,
        "xch",
        1000,
        tier="inner",
        designation="tier_active",
        assigned_tier="inner",
    )
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="migration-terminal-run",
        wallet_fingerprint_hash=wallet_hash,
        network="mainnet",
        asset_id=asset_id,
        side="buy",
        tier="inner",
        purpose="migration_test",
        slot_key="migration-terminal-slot",
        generation=0,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[coin_id],
        wallet_identity_json=wallet_identity,
        evidence_json={"migration": "prepared"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=_sha("migration-terminal-offer"),
        wallet_identity_json=wallet_identity,
        evidence_json={"migration": "created"},
        finalized_at=LATER,
        finalize_selected_coin_reservations=True,
    )
    assert database.add_offer(
        trade_id=trade_id,
        side="buy",
        price_xch=database.Decimal("0.0000005"),
        size_xch=database.Decimal("0.000000001"),
        size_cat=database.Decimal("2"),
        cat_asset_id=asset_id,
        tier="inner",
        coin_id=database.norm_coin_id(coin_id),
    )
    transaction_id = _sha("migration-terminal-transaction")
    receive_coin_id = _sha("migration-terminal-receive")
    filled_at = "2026-08-15T12:01:30.000000Z"
    stored_offer = database.get_offer(trade_id)
    evidence = {
        "migration": "exact terminal coin outcome",
        "classification": {
            "classification": "FILLED_PROVEN",
            "transaction_id": transaction_id,
            "spend_identity": None,
            "block_height": 42,
            "receive_coin_id": receive_coin_id,
            "receive_amount_mojos": 2000,
            "filled_at": filled_at,
        },
        "fill_authority": {
            "schema_version": 1,
            "intent_id": intent_id,
            "trade_id": trade_id,
            "side": stored_offer["side"],
            "price_xch": stored_offer["price_xch"],
            "size_xch": stored_offer["size_xch"],
            "size_cat": stored_offer["size_cat"],
            "cat_asset_id": stored_offer["cat_asset_id"],
            "tier": stored_offer["tier"],
            "fee_mojos_xch": stored_offer["fee_mojos_xch"],
            "spent_block_height": 42,
            "receive_coin_id": database.norm_coin_id(receive_coin_id),
            "receive_amount_mojos": 2000,
            "filled_at": filled_at,
            "transaction_id": transaction_id,
            "spend_identity": None,
        },
    }
    evidence_text = json.dumps(
        evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    result = database.commit_offer_reconciliation(
        intent_id=intent_id,
        operation_id=f"reconcile:{intent_id}",
        classification="FILLED_PROVEN",
        reason_code="MIGRATION_TEST_PROOF",
        wallet_identity_json=wallet_identity,
        evidence_json=evidence,
        evidence_sha256=hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
        transaction_id=transaction_id,
        block_height=42,
        receive_coin_id=receive_coin_id,
        receive_amount_mojos=2000,
        filled_at=filled_at,
        reconciled_at="2026-08-15T12:02:00.000000Z",
    )
    terminal_event_id = result["event"]["event_id"]
    database.close_connection()

    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP TABLE offer_reconciliation_coin_outcomes")
        conn.commit()

    _replay_migrations()

    with sqlite3.connect(isolated_database) as conn:
        row = conn.execute(
            "SELECT coin_id, intent_id, trade_id, outcome, disposition, "
            "terminal_event_id, evidence_sha256, recorded_at "
            "FROM offer_reconciliation_coin_outcomes"
        ).fetchone()
        assert row == (
            database.norm_coin_id(coin_id),
            intent_id,
            trade_id,
            "FILLED_PROVEN",
            "spent",
            terminal_event_id,
            hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
            "2026-08-15T12:02:00.000000Z",
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE offer_reconciliation_coin_outcomes SET disposition='spent'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM offer_reconciliation_coin_outcomes")

    _replay_migrations()

    with sqlite3.connect(isolated_database) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM offer_reconciliation_coin_outcomes"
            ).fetchone()[0]
            == 1
        )


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


def test_stability_migration_fails_closed_on_missing_required_column_and_rolls_back(
    isolated_database,
):
    with sqlite3.connect(isolated_database) as conn:
        conn.execute(
            """
            CREATE TABLE offer_intents (
                intent_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                slot_key TEXT,
                generation INTEGER NOT NULL DEFAULT 0,
                parent_intent_id TEXT,
                sage_trade_id TEXT,
                offer_text_sha256 TEXT,
                lifecycle_state TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    with pytest.raises(RuntimeError, match="offer_intents.*missing required columns"):
        database.init_database()

    assert "offer_intents" in _table_names(isolated_database)
    assert "offer_operation_journal" not in _table_names(isolated_database)
    assert _integrity(isolated_database) == "ok"


def test_stability_migration_rejects_wrong_unique_partial_index(isolated_database):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP INDEX uniq_offer_intents_active_slot_generation")
        conn.execute(
            """
            CREATE INDEX uniq_offer_intents_active_slot_generation
            ON offer_intents(slot_key, run_id, generation)
            """
        )
    database._db_initialized_path = ""

    with pytest.raises(RuntimeError, match="active_slot_generation.*unique partial"):
        database.init_database()


def test_stability_migration_upgrades_previous_global_active_slot_index(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP INDEX uniq_offer_intents_active_slot_generation")
        conn.execute(database._PREVIOUS_OFFER_INTENT_ACTIVE_SLOT_INDEX_SQL)
    database._db_initialized_path = ""

    database.init_database()

    with sqlite3.connect(isolated_database) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='uniq_offer_intents_active_slot_generation'"
        ).fetchone()
    normalized = "".join(str(row[0]).lower().split())
    assert "'unknown'" in normalized
    assert "'conflicted'" in normalized


def test_stability_migration_rejects_wrong_append_only_trigger(isolated_database):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP TRIGGER offer_operation_journal_no_update")
        conn.execute(
            """
            CREATE TRIGGER offer_operation_journal_no_update
            BEFORE UPDATE ON offer_operation_journal BEGIN SELECT 1; END
            """
        )
    database._db_initialized_path = ""

    with pytest.raises(RuntimeError, match="append-only trigger"):
        database.init_database()


def test_stability_migration_upgrades_exact_legacy_boost_identity_trigger(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP TRIGGER offer_fill_boost_commands_guarded_update")
        conn.executescript(database._LEGACY_OFFER_FILL_BOOST_COMMAND_GUARD_SQL)
    database._db_initialized_path = ""

    database.init_database()

    with sqlite3.connect(isolated_database) as conn:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='offer_fill_boost_commands_guarded_update'"
        ).fetchone()[0]
        effect_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='offer_fill_boost_effects'"
        ).fetchone()
    assert "OLD.fill_id <> NEW.fill_id" in trigger_sql
    assert effect_table == (1,)


def test_stability_migration_rejects_malformed_boost_identity_trigger(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    malformed = database._LEGACY_OFFER_FILL_BOOST_COMMAND_GUARD_SQL.replace(
        "OLD.side <> NEW.side", "OLD.side = NEW.side"
    )
    assert malformed != database._LEGACY_OFFER_FILL_BOOST_COMMAND_GUARD_SQL
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP TRIGGER offer_fill_boost_commands_guarded_update")
        conn.executescript(malformed)
    database._db_initialized_path = ""

    with pytest.raises(RuntimeError, match="offer_fill_boost_commands_guarded_update"):
        database.init_database()


def test_stability_migration_rejects_malformed_boost_effect_table(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP TRIGGER offer_fill_boost_effects_no_update")
        conn.execute("DROP TRIGGER offer_fill_boost_effects_no_delete")
        conn.execute("DROP TABLE offer_fill_boost_effects")
        conn.execute(
            """
            CREATE TABLE offer_fill_boost_effects (
                fill_id INTEGER PRIMARY KEY,
                trade_id TEXT NOT NULL,
                side TEXT NOT NULL,
                effect_json TEXT NOT NULL
            )
            """
        )
    database._db_initialized_path = ""

    with pytest.raises(
        RuntimeError,
        match="offer_fill_boost_effects.*missing required columns.*applied_at",
    ):
        database.init_database()


def test_boost_command_materialization_schema_is_immutable_and_audited(
    isolated_database,
):
    database.init_database()
    conn = database.get_connection()
    table = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='offer_fill_boost_command_materializations'"
    ).fetchone()
    triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='offer_fill_boost_command_materializations'"
        ).fetchall()
    }

    assert table is not None
    columns = {
        row[1]: (row[2], row[3])
        for row in conn.execute(
            "PRAGMA table_info(offer_fill_boost_command_materializations)"
        ).fetchall()
    }
    assert columns["materialization_json"] == ("TEXT", 1)
    assert columns["materialization_sha256"] == ("TEXT", 1)
    assert triggers == {
        "offer_fill_boost_command_materializations_no_update",
        "offer_fill_boost_command_materializations_no_delete",
    }


def test_stability_migration_rejects_malformed_boost_materialization_table(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP TRIGGER offer_fill_boost_command_materializations_no_update")
        conn.execute("DROP TRIGGER offer_fill_boost_command_materializations_no_delete")
        conn.execute("DROP TABLE offer_fill_boost_command_materializations")
        conn.execute(
            """
            CREATE TABLE offer_fill_boost_command_materializations (
                fill_id INTEGER PRIMARY KEY,
                trade_id TEXT NOT NULL,
                side TEXT NOT NULL,
                materialization_json TEXT NOT NULL
            )
            """
        )
    database._db_initialized_path = ""

    with pytest.raises(
        RuntimeError,
        match="offer_fill_boost_command_materializations.*missing required columns",
    ):
        database.init_database()


def test_boost_log_and_sweep_safety_materializations_are_schema_guarded(
    isolated_database,
):
    database.init_database()
    conn = database.get_connection()
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
            (
                "offer_fill_boost_log_sinks",
                "offer_fill_sweep_safety_state",
                "offer_fill_sweep_migration_audit",
            ),
        ).fetchall()
    }
    triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name IN "
            "(?, ?, ?, ?, ?, ?)",
            (
                "offer_fill_boost_log_sinks_no_update",
                "offer_fill_boost_log_sinks_no_delete",
                "offer_fill_sweep_safety_state_guarded_update",
                "offer_fill_sweep_safety_state_no_delete",
                "offer_fill_sweep_migration_audit_no_update",
                "offer_fill_sweep_migration_audit_no_delete",
            ),
        ).fetchall()
    }

    assert tables == {
        "offer_fill_boost_log_sinks",
        "offer_fill_sweep_safety_state",
        "offer_fill_sweep_migration_audit",
    }
    assert triggers == {
        "offer_fill_boost_log_sinks_no_update",
        "offer_fill_boost_log_sinks_no_delete",
        "offer_fill_sweep_safety_state_guarded_update",
        "offer_fill_sweep_safety_state_no_delete",
        "offer_fill_sweep_migration_audit_no_update",
        "offer_fill_sweep_migration_audit_no_delete",
    }


def test_repeated_migration_does_not_rescan_append_only_effect_history(
    isolated_database,
    monkeypatch,
):
    database.init_database()
    database.close_connection()
    statements = []
    real_connect = database.sqlite3.connect

    def traced_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(database.sqlite3, "connect", traced_connect)

    database._migrate_stability_schema()

    normalized = [" ".join(statement.lower().split()) for statement in statements]
    assert not any(
        "from offer_fill_sweep_events as event left join" in statement
        for statement in normalized
    )
    assert not any(
        "from offer_fill_boost_effects as effect join" in statement
        and "left join offer_fill_boost_log_sinks" in statement
        for statement in normalized
    )


def test_sweep_active_queues_have_indexed_bounded_query_plans(isolated_database):
    database.init_database()
    conn = database.get_connection()

    registration_plan = " ".join(
        str(row[3])
        for row in conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT registration.fill_id, registration.trade_id, "
            "       registration.classification_json "
            "FROM offer_fill_sweep_registration_queue AS queue "
            "JOIN offer_fill_sweep_registrations AS registration "
            "  ON registration.fill_id=queue.fill_id "
            "WHERE queue.state='active' "
            "ORDER BY queue.fill_id LIMIT 4097"
        ).fetchall()
    )
    pending_plan = " ".join(
        str(row[3])
        for row in conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT event.event_id, event.event_json "
            "FROM offer_fill_sweep_delivery_queue AS queue "
            "JOIN offer_fill_sweep_events AS event ON event.event_id=queue.event_id "
            "WHERE queue.state='pending' "
            "ORDER BY queue.queued_at, queue.event_id LIMIT 200"
        ).fetchall()
    )
    expired_plan = " ".join(
        str(row[3])
        for row in conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT event_id FROM offer_fill_sweep_delivery_queue "
            "WHERE state='running' AND claimed_at<=? "
            "ORDER BY claimed_at, event_id LIMIT 1",
            (AT,),
        ).fetchall()
    )
    completed_plan = " ".join(
        str(row[3])
        for row in conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT queue.event_id "
            "FROM offer_fill_sweep_delivery_queue AS queue "
            "JOIN offer_fill_sweep_delivery_acks AS ack "
            "  ON ack.event_id=queue.event_id "
            "WHERE queue.state='completed' "
            "ORDER BY queue.completed_at, queue.event_id LIMIT 256"
        ).fetchall()
    )
    finalized_plan = " ".join(
        str(row[3])
        for row in conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT queue.fill_id "
            "FROM offer_fill_sweep_registration_queue AS queue "
            "JOIN offer_fill_sweep_finalizations AS finalization "
            "  ON finalization.fill_id=queue.fill_id "
            "WHERE queue.state='finalized' "
            "ORDER BY queue.finalized_at, queue.fill_id LIMIT 256"
        ).fetchall()
    )
    safety_plan = " ".join(
        str(row[3])
        for row in conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT safety.side, safety.event_id, safety.expires_at, "
            "       safety.effect_at, effect.effect_json, effect.effect_sha256, "
            "       event.spent_block_index, event.sweep_group_id, event.event_json "
            "FROM offer_fill_sweep_safety_state AS safety "
            "JOIN offer_fill_sweep_downstream_effects AS effect "
            "  ON effect.event_id=safety.event_id "
            "JOIN offer_fill_sweep_events AS event ON event.event_id=effect.event_id "
            "ORDER BY safety.side LIMIT 3"
        ).fetchall()
    )

    assert "idx_offer_fill_sweep_registration_queue_active" in registration_plan
    assert "idx_offer_fill_sweep_delivery_pending" in pending_plan
    assert "idx_offer_fill_sweep_delivery_claim" in expired_plan
    assert "idx_offer_fill_sweep_delivery_completed" in completed_plan
    assert "idx_offer_fill_sweep_registration_queue_finalized" in finalized_plan
    assert "sqlite_autoindex_offer_fill_sweep_safety_state_1" in safety_plan
    assert "USE TEMP B-TREE" not in registration_plan
    assert "USE TEMP B-TREE" not in pending_plan
    assert "USE TEMP B-TREE" not in expired_plan
    assert "USE TEMP B-TREE" not in completed_plan
    assert "USE TEMP B-TREE" not in finalized_plan
    assert "USE TEMP B-TREE" not in safety_plan


def test_sweep_auxiliary_queue_deletes_are_guarded_by_completed_state(
    isolated_database,
):
    database.init_database()
    conn = database.get_connection()
    triggers = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
            "AND name IN (?, ?)",
            (
                "offer_fill_sweep_registration_queue_guarded_delete",
                "offer_fill_sweep_delivery_queue_guarded_delete",
            ),
        ).fetchall()
    }

    assert set(triggers) == {
        "offer_fill_sweep_registration_queue_guarded_delete",
        "offer_fill_sweep_delivery_queue_guarded_delete",
    }
    assert (
        "OLD.state <> 'finalized'"
        in triggers["offer_fill_sweep_registration_queue_guarded_delete"]
    )
    assert (
        "OLD.state <> 'completed'"
        in triggers["offer_fill_sweep_delivery_queue_guarded_delete"]
    )


def test_unique_table_key_validator_rejects_partial_and_created_indexes():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE sample (event_id TEXT NOT NULL);
            CREATE UNIQUE INDEX sample_partial ON sample(event_id)
                WHERE event_id IS NOT NULL;
            """
        )
        with pytest.raises(RuntimeError, match="missing UNIQUE key"):
            database._require_unique_key(conn, "sample", ("event_id",))

        conn.execute("DROP INDEX sample_partial")
        conn.execute("CREATE UNIQUE INDEX sample_created ON sample(event_id)")
        with pytest.raises(RuntimeError, match="missing UNIQUE key"):
            database._require_unique_key(conn, "sample", ("event_id",))

        conn.executescript(
            """
            DROP TABLE sample;
            CREATE TABLE sample (event_id TEXT NOT NULL UNIQUE);
            """
        )
        database._require_unique_key(conn, "sample", ("event_id",))
    finally:
        conn.close()


class _CanonicalizationAbort(BaseException):
    pass


class _HostileCanonicalMapping(dict):
    def items(self):
        raise _CanonicalizationAbort("mapping traversal escaped preflight")


class _HostileCanonicalKey(str):
    def __lt__(self, _other):
        raise _CanonicalizationAbort("key sort escaped preflight")


@pytest.mark.parametrize(
    "payload",
    [
        _HostileCanonicalMapping({"safe": 1}),
        {_HostileCanonicalKey("hostile"): 1, "safe": 2},
    ],
)
def test_database_canonical_json_rejects_container_subclasses_before_dump(payload):
    with pytest.raises(ValueError, match="exact JSON containers"):
        database._canonical_json_text(payload, "payload", expected_type=dict)


def test_database_json_text_cap_precedes_parser_allocation(monkeypatch):
    oversized_json_text = " " * (2 * 1024 * 1024 + 1)
    calls = []

    def forbidden_loads(_value):
        calls.append(True)
        raise AssertionError("oversized JSON text reached parser")

    monkeypatch.setattr(database.json, "loads", forbidden_loads)

    with pytest.raises(ValueError, match="input exceeds"):
        database._canonical_json_text(oversized_json_text, "payload")

    assert calls == []


def test_stability_migration_rejects_check_text_hidden_in_comment(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        original = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='runtime_safety_latch'"
        ).fetchone()[0]
        malformed = original.replace(
            "CHECK(singleton_id = 1)",
            "/* CHECK(singleton_id = 1) */",
        )
        assert malformed != original
        version = conn.execute("PRAGMA schema_version").fetchone()[0]
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute(
            "UPDATE sqlite_master SET sql=? WHERE type='table' "
            "AND name='runtime_safety_latch'",
            (malformed,),
        )
        conn.execute("PRAGMA writable_schema=OFF")
        conn.execute(f"PRAGMA schema_version={version + 1}")
    database._db_initialized_path = ""

    with pytest.raises(RuntimeError, match="canonical table definition"):
        database.init_database()


def test_stability_migration_rejects_unexpected_trigger_on_stability_table(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute(
            """
            CREATE TRIGGER offer_intents_unexpected
            BEFORE UPDATE ON offer_intents BEGIN SELECT 1; END
            """
        )
    database._db_initialized_path = ""

    with pytest.raises(RuntimeError, match="unexpected stability trigger"):
        database.init_database()


@pytest.mark.parametrize(
    ("table_name", "trigger_target"),
    [
        ("offer_intents", "OFFER_INTENTS"),
        ("offer_operation_journal", '"OfFeR_OpErAtIoN_JoUrNaL"'),
        ("runtime_safety_latch", "RUNTIME_SAFETY_LATCH"),
        ("runtime_mutation_lease", '"RuNtImE_MuTaTiOn_LeAsE"'),
        ("runtime_worker_delegations", "RUNTIME_WORKER_DELEGATIONS"),
        ("publication_outbox", '"PuBlIcAtIoN_OuTbOx"'),
    ],
)
def test_stability_migration_rejects_case_variant_trigger_on_every_safety_table(
    isolated_database, table_name, trigger_target
):
    database.init_database()
    database.close_connection()
    trigger_name = f"unexpected_case_{table_name}"
    with sqlite3.connect(isolated_database) as conn:
        conn.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            AFTER UPDATE ON {trigger_target} BEGIN SELECT 1; END
            """
        )
        stored_owner = conn.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type='trigger' AND name=?",
            (trigger_name,),
        ).fetchone()[0]
    assert stored_owner != table_name
    assert stored_owner.casefold() == table_name.casefold()
    database._db_initialized_path = ""

    with pytest.raises(RuntimeError, match="unexpected stability trigger"):
        database.init_database()


def test_case_variant_trigger_is_rejected_before_timestamp_normalization_side_effect(
    isolated_database,
):
    database.init_database()
    _prepare_intent("intent-trigger-side-effect")
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.executescript(
            """
            CREATE TABLE migration_trigger_effects (value TEXT NOT NULL);
            UPDATE offer_intents SET updated_at='2026-08-15 12:01:00'
            WHERE intent_id='intent-trigger-side-effect';
            CREATE TRIGGER unexpected_normalization_trigger
            AFTER UPDATE ON "OFFER_INTENTS"
            BEGIN
                INSERT INTO migration_trigger_effects(value) VALUES ('fired');
            END;
            """
        )
    database._db_initialized_path = ""

    with pytest.raises(RuntimeError, match="unexpected stability trigger"):
        database.init_database()

    with sqlite3.connect(isolated_database) as conn:
        effects = conn.execute("SELECT value FROM migration_trigger_effects").fetchall()
        stored = conn.execute(
            "SELECT updated_at FROM offer_intents "
            "WHERE intent_id='intent-trigger-side-effect'"
        ).fetchone()[0]
    assert effects == []
    assert stored == "2026-08-15 12:01:00"


def test_unicode_trigger_name_and_quoted_case_variant_owner_cannot_bypass_validation(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    trigger_name = "\N{GREEK CAPITAL LETTER DELTA}_unexpected"
    with sqlite3.connect(isolated_database) as conn:
        conn.execute(
            f"""
            CREATE TRIGGER "{trigger_name}"
            AFTER UPDATE ON [OfFeR_InTeNtS] BEGIN SELECT 1; END
            """
        )
        stored = conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='trigger' AND name=?",
            (trigger_name,),
        ).fetchone()
    assert stored == (trigger_name, "OfFeR_InTeNtS")
    database._db_initialized_path = ""

    with pytest.raises(RuntimeError, match="unexpected stability trigger"):
        database.init_database()


def test_non_stability_trigger_with_case_variant_owner_is_ignored(isolated_database):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute(
            """
            CREATE TRIGGER legitimate_offer_trigger
            AFTER UPDATE ON "OFFERS" BEGIN SELECT 1; END
            """
        )
    database._db_initialized_path = ""

    database.init_database()

    with sqlite3.connect(isolated_database) as conn:
        trigger = conn.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type='trigger' "
            "AND name='legitimate_offer_trigger'"
        ).fetchone()
    assert trigger == ("OFFERS",)


def test_unicode_confusable_trigger_owners_remain_distinct_from_stability_tables(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    confusable_owners = (
        ("offer_intent\N{LATIN SMALL LETTER LONG S}", "long_s_owner_trigger"),
        (
            "runtime_wor\N{KELVIN SIGN}er_delegations",
            "kelvin_owner_trigger",
        ),
        (
            "publ\N{LATIN CAPITAL LETTER I WITH DOT ABOVE}cation_outbox",
            "dotted_i_owner_trigger",
        ),
        (
            "offer_\N{CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I}ntents",
            "cyrillic_i_owner_trigger",
        ),
    )
    with sqlite3.connect(isolated_database) as conn:
        for owner, trigger_name in confusable_owners:
            conn.execute(f'CREATE TABLE "{owner}" (value INTEGER NOT NULL)')
            conn.execute(
                f'CREATE TRIGGER "{trigger_name}" '
                f'AFTER UPDATE ON "{owner}" BEGIN SELECT 1; END'
            )
    database._db_initialized_path = ""

    database.init_database()

    with sqlite3.connect(isolated_database) as conn:
        stored_owners = dict(
            conn.execute(
                "SELECT name, tbl_name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        )
    for owner, trigger_name in confusable_owners:
        assert stored_owners[trigger_name] == owner


def test_stability_migration_rejects_missing_singleton_check_and_extra_rows(
    isolated_database,
):
    with sqlite3.connect(isolated_database) as conn:
        conn.executescript(
            """
            CREATE TABLE runtime_safety_latch (
                singleton_id INTEGER PRIMARY KEY,
                generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
                state TEXT NOT NULL DEFAULT 'resolved'
                    CHECK(state IN ('resolved', 'tripped')),
                reason_code TEXT,
                reason TEXT,
                blocking_operation_ids_json TEXT NOT NULL DEFAULT '[]',
                wallet_fingerprint_hash TEXT,
                network TEXT,
                tripped_at TEXT,
                resolved_at TEXT,
                updated_at TEXT NOT NULL
            );
            INSERT INTO runtime_safety_latch (
                singleton_id, generation, state,
                blocking_operation_ids_json, updated_at
            ) VALUES
                (1, 0, 'resolved', '[]', '2026-08-15T12:00:00.000000Z'),
                (2, 0, 'resolved', '[]', '2026-08-15T12:00:00.000000Z');
            """
        )

    with pytest.raises(RuntimeError, match="runtime_safety_latch.*singleton"):
        database.init_database()


def test_stability_migration_rejects_wrong_required_column_property(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        original = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='publication_outbox'"
        ).fetchone()[0]
        malformed = original.replace(
            "network                     TEXT NOT NULL",
            "network                     TEXT",
        )
        assert malformed != original
        version = conn.execute("PRAGMA schema_version").fetchone()[0]
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute(
            "UPDATE sqlite_master SET sql=? WHERE type='table' "
            "AND name='publication_outbox'",
            (malformed,),
        )
        conn.execute("PRAGMA writable_schema=OFF")
        conn.execute(f"PRAGMA schema_version={version + 1}")
    database._db_initialized_path = ""

    with pytest.raises(
        RuntimeError, match="publication_outbox.network.*NOT NULL property"
    ):
        database.init_database()


def test_stability_migration_rejects_extra_singleton_rows_even_with_check_shape(
    isolated_database,
):
    with sqlite3.connect(isolated_database) as conn:
        conn.executescript(
            """
            CREATE TABLE runtime_safety_latch (
                singleton_id INTEGER PRIMARY KEY,
                generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
                state TEXT NOT NULL DEFAULT 'resolved'
                    CHECK(state IN ('resolved', 'tripped')),
                reason_code TEXT,
                reason TEXT,
                blocking_operation_ids_json TEXT NOT NULL DEFAULT '[]',
                wallet_fingerprint_hash TEXT,
                network TEXT,
                tripped_at TEXT,
                resolved_at TEXT,
                updated_at TEXT NOT NULL
            );
            INSERT INTO runtime_safety_latch (
                singleton_id, generation, state,
                blocking_operation_ids_json, updated_at
            ) VALUES
                (1, 0, 'resolved', '[]', '2026-08-15T12:00:00.000000Z'),
                (2, 0, 'resolved', '[]', '2026-08-15T12:00:00.000000Z');
            """
        )
        original = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='runtime_safety_latch'"
        ).fetchone()[0]
        shaped = original.replace(
            "singleton_id INTEGER PRIMARY KEY,",
            "singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),",
        )
        assert shaped != original
        version = conn.execute("PRAGMA schema_version").fetchone()[0]
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute(
            "UPDATE sqlite_master SET sql=? WHERE type='table' "
            "AND name='runtime_safety_latch'",
            (shaped,),
        )
        conn.execute("PRAGMA writable_schema=OFF")
        conn.execute(f"PRAGMA schema_version={version + 1}")

    with pytest.raises(RuntimeError, match="runtime_safety_latch.*cardinality"):
        database.init_database()


def test_stability_migration_waits_for_database_writer_and_completes_atomically(
    isolated_database,
):
    blocker = sqlite3.connect(isolated_database, timeout=1, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(database.init_database)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.1)
            blocker.commit()
            future.result(timeout=10)
    finally:
        if blocker.in_transaction:
            blocker.rollback()
        blocker.close()

    assert STABILITY_TABLES <= _table_names(isolated_database)
    assert _integrity(isolated_database) == "ok"


def test_complete_initialization_is_serialized_across_processes(isolated_database):
    child_code = """
import sys
sys.path.insert(0, 'src/catalyst')
import database
database.close_connection()
database.DB_PATH = sys.argv[1]
database._db_initialized_path = ''
print('ready', flush=True)
database.init_database()
print('done', flush=True)
"""
    process = None
    with database._database_migration_guard(timeout=2):
        lock_path = Path(f"{isolated_database}.migration.lock")
        assert lock_path.exists()
        process = subprocess.Popen(
            [sys.executable, "-c", child_code, str(isolated_database)],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.5)

    try:
        stdout, stderr = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        pytest.fail(f"child initializer did not finish: {stdout=} {stderr=}")
    assert process.returncode == 0, stderr
    assert stdout.strip() == "done"
    assert STABILITY_TABLES <= _table_names(isolated_database)
    assert _integrity(isolated_database) == "ok"


def test_database_migration_guard_times_out_and_releases_after_exception(
    isolated_database,
):
    with pytest.raises(RuntimeError, match="boom"):
        with database._database_migration_guard(timeout=1):
            with pytest.raises(TimeoutError, match="migration lock"):
                with database._database_migration_guard(timeout=0.1):
                    pass
            raise RuntimeError("boom")

    with database._database_migration_guard(timeout=1):
        assert Path(f"{isolated_database}.migration.lock").exists()


def test_migration_normalizes_existing_mutable_stability_timestamps(
    isolated_database,
):
    database.init_database()
    _prepare_intent("intent-legacy-time")
    database.enqueue_publication_outbox(
        publication_id="publication-legacy-time",
        idempotency_key="publish:legacy-time",
        intent_id="intent-legacy-time",
        network="mainnet",
        offer_fingerprint=_sha("offer-legacy-time"),
        publication_epoch="epoch-legacy-time",
        publisher="dexie",
        payload_json={"offer": "legacy-time"},
        queued_at=AT,
    )
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute(
            "UPDATE offer_intents SET prepared_at=?, updated_at=? WHERE intent_id=?",
            (
                "2026-08-15 13:00:00+01:00",
                "2026-08-15 12:01:00.5",
                "intent-legacy-time",
            ),
        )
        conn.execute(
            "UPDATE runtime_safety_latch SET updated_at=? WHERE singleton_id=1",
            ("2026-08-15 12:01:00",),
        )
        conn.execute(
            """
            UPDATE runtime_mutation_lease
            SET lease_version=3, active=1, owner_run_id='run-legacy',
                owner_pid=101, owner_host='host-legacy',
                wallet_fingerprint_hash=?, network='mainnet',
                acquired_at=?, heartbeat_at=?, expires_at=?, updated_at=?
            WHERE singleton_id=1
            """,
            (
                _sha("wallet-legacy"),
                "2026-08-15 13:00:00+01:00",
                "2026-08-15 12:01:00.25",
                "2026-08-15 12:05:00",
                "2026-08-15 12:01:00.25",
            ),
        )
        conn.execute(
            """
            INSERT INTO runtime_worker_delegations (
                delegation_id, delegation_token_hash, parent_run_id,
                operation_id, worker_id, purpose, wallet_fingerprint_hash,
                network, state, metadata_json, issued_at, expires_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', '{}', ?, ?, ?)
            """,
            (
                "delegation-legacy-time",
                _sha("token-legacy-time"),
                "run-legacy",
                "coin-prep:legacy-time",
                "worker-legacy",
                "replacement-capacity",
                _sha("wallet-legacy"),
                "mainnet",
                "2026-08-15 07:00:00-05:00",
                "2026-08-15 12:05:00",
                "2026-08-15 12:00:00",
            ),
        )
        conn.execute(
            """
            UPDATE publication_outbox
            SET queued_at=?, next_attempt_at=?, updated_at=?
            WHERE publication_id='publication-legacy-time'
            """,
            (
                "2026-08-15 12:00:00",
                "2026-08-15 13:02:00+01:00",
                "2026-08-15 12:01:00.125",
            ),
        )
    database._db_initialized_path = ""

    database.init_database()

    intent = database.get_offer_intent("intent-legacy-time")
    assert intent["prepared_at"] == AT
    assert intent["updated_at"] == "2026-08-15T12:01:00.500000Z"
    assert database.get_runtime_safety_latch()["updated_at"] == LATER
    lease = database.get_runtime_mutation_lease()
    assert lease["acquired_at"] == AT
    assert lease["heartbeat_at"] == "2026-08-15T12:01:00.250000Z"
    assert lease["expires_at"] == EXPIRES
    delegation = database.get_valid_worker_delegation(
        delegation_id="delegation-legacy-time",
        delegation_token_hash=_sha("token-legacy-time"),
        parent_run_id="run-legacy",
        operation_id="coin-prep:legacy-time",
        purpose="replacement-capacity",
        wallet_fingerprint_hash=_sha("wallet-legacy"),
        network="mainnet",
        now=LATER,
    )
    assert delegation["issued_at"] == AT
    assert delegation["expires_at"] == EXPIRES
    publication = database.get_publication_outbox("publication-legacy-time")
    assert publication["queued_at"] == AT
    assert publication["next_attempt_at"] == "2026-08-15T12:02:00.000000Z"
    assert publication["updated_at"] == "2026-08-15T12:01:00.125000Z"


def test_invalid_stored_safety_timestamp_fails_closed_and_rolls_back_migration(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP INDEX idx_offer_intents_parent")
        conn.execute(
            "UPDATE runtime_mutation_lease SET updated_at='not-a-timestamp' "
            "WHERE singleton_id=1"
        )
    database._db_initialized_path = ""

    with pytest.raises(
        RuntimeError, match="runtime_mutation_lease.updated_at.*invalid"
    ):
        database.init_database()

    with sqlite3.connect(isolated_database) as conn:
        index = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' "
            "AND name='idx_offer_intents_parent'"
        ).fetchone()
        stored = conn.execute(
            "SELECT updated_at FROM runtime_mutation_lease WHERE singleton_id=1"
        ).fetchone()[0]
    assert index is None
    assert stored == "not-a-timestamp"
    assert database._db_initialized_path == ""
    assert _integrity(isolated_database) == "ok"


def test_schema_has_exact_identity_uniqueness_and_singletons(isolated_database):
    database.init_database()
    _prepare_intent("intent-a", slot_key="identity-slot-a")
    _finalize_intent(
        "intent-a", trade_id=_sha("shared-trade"), offer_hash=_sha("offer-a")
    )
    _prepare_intent(
        "intent-b",
        generation=8,
        slot_key="identity-slot-b",
        selected_coin_ids_json=[_sha("identity-coin-b")],
    )

    with pytest.raises(sqlite3.IntegrityError):
        _finalize_intent(
            "intent-b",
            trade_id=_sha("shared-trade"),
            offer_hash=_sha("offer-b"),
        )

    assert database.get_offer_intent("intent-b")["lifecycle_state"] == "prepared"
    assert len(database.get_offer_operation_events("create:intent-b")) == 1

    _prepare_intent(
        "intent-c",
        generation=9,
        slot_key="identity-slot-c",
        selected_coin_ids_json=[_sha("identity-coin-c")],
    )
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


def test_cancel_effect_claim_schema_is_unique_validated_and_append_only(
    isolated_database,
):
    database.init_database()
    operation_id = f"cancel:{'a' * 64}"
    prepared_event_id = f"{operation_id}:attempt:1:prepared"
    conn = database.get_connection()
    conn.execute(
        """
        INSERT INTO offer_cancel_effect_claims (
            operation_id, attempt, prepared_event_id, claimed_at
        ) VALUES (?, ?, ?, ?)
        """,
        (operation_id, 1, prepared_event_id, AT),
    )
    conn.commit()

    assert database.get_offer_cancel_effect_claim(
        operation_id=operation_id, attempt=1
    ) == {
        "operation_id": operation_id,
        "attempt": 1,
        "prepared_event_id": prepared_event_id,
        "claimed_at": AT,
    }
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO offer_cancel_effect_claims (
                operation_id, attempt, prepared_event_id, claimed_at
            ) VALUES (?, ?, ?, ?)
            """,
            (operation_id, 1, f"{operation_id}:duplicate", LATER),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "UPDATE offer_cancel_effect_claims SET claimed_at=? WHERE operation_id=?",
            (LATER, operation_id),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "DELETE FROM offer_cancel_effect_claims WHERE operation_id=?",
            (operation_id,),
        )
    conn.rollback()


def test_cancel_cohort_manifest_schema_is_unique_and_append_only(
    isolated_database,
):
    database.init_database()
    conn = database.get_connection()
    manifest = {
        "schema_version": 1,
        "cohort_id": "cancel-cohort:" + "a" * 64,
        "member_count": 2,
        "members": [],
    }
    manifest_json = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest_sha256 = hashlib.sha256(manifest_json.encode()).hexdigest()
    conn.execute(
        """
        INSERT INTO offer_cancel_cohort_manifests (
            cohort_id, manifest_sha256, member_count, manifest_json, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            manifest["cohort_id"],
            manifest_sha256,
            manifest["member_count"],
            manifest_json,
            AT,
        ),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO offer_cancel_cohort_manifests (
                cohort_id, manifest_sha256, member_count, manifest_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (manifest["cohort_id"], _sha("other"), 2, "{}", LATER),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "UPDATE offer_cancel_cohort_manifests SET created_at=? WHERE cohort_id=?",
            (LATER, manifest["cohort_id"]),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "DELETE FROM offer_cancel_cohort_manifests WHERE cohort_id=?",
            (manifest["cohort_id"],),
        )
    conn.rollback()


def test_cancel_cohort_manifest_migration_rejects_malformed_existing_table(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP TABLE offer_cancel_cohort_manifests")
        conn.execute(
            """
            CREATE TABLE offer_cancel_cohort_manifests (
                manifest_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                cohort_id TEXT NOT NULL UNIQUE,
                manifest_sha256 TEXT NOT NULL UNIQUE,
                member_count INTEGER NOT NULL,
                manifest_json TEXT NOT NULL
            )
            """
        )
    database._db_initialized_path = ""

    with pytest.raises(
        RuntimeError,
        match="offer_cancel_cohort_manifests.*missing required columns.*created_at",
    ):
        database.init_database()


def test_cancel_effect_claim_migration_rejects_malformed_existing_table(
    isolated_database,
):
    database.init_database()
    database.close_connection()
    with sqlite3.connect(isolated_database) as conn:
        conn.execute("DROP TABLE offer_cancel_effect_claims")
        conn.execute(
            """
            CREATE TABLE offer_cancel_effect_claims (
                claim_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                prepared_event_id TEXT NOT NULL,
                UNIQUE(operation_id, attempt),
                UNIQUE(prepared_event_id)
            )
            """
        )
    database._db_initialized_path = ""

    with pytest.raises(
        RuntimeError,
        match="offer_cancel_effect_claims.*missing required columns.*claimed_at",
    ):
        database.init_database()


def test_prepare_and_finalize_preserve_exact_amounts_hashes_and_canonical_json(
    isolated_database,
):
    database.init_database()
    prepared = _prepare_intent()

    assert prepared["offered_amount_atomic"] == "18446744073709551616000000000000000001"
    assert (
        prepared["requested_amount_atomic"] == "340282366920938463463374607431768211457"
    )
    assert prepared["selected_coin_ids_json"] == json.dumps(
        sorted({_sha("coin-b"), _sha("coin-a")}),
        separators=(",", ":"),
        sort_keys=True,
    )
    assert (
        prepared["selected_coin_ids_sha256"]
        == hashlib.sha256(
            prepared["selected_coin_ids_json"].encode("utf-8")
        ).hexdigest()
    )
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
    assert (
        events[-1]["evidence_sha256"]
        == hashlib.sha256(events[-1]["evidence_json"].encode("utf-8")).hexdigest()
    )


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


@pytest.mark.parametrize(
    ("lifecycle_state", "outcome"),
    [
        ("created", "UNKNOWN"),
        ("created", "FAILED"),
        ("creation_unknown", "CONFIRMED"),
        ("creation_unknown", "SUBMITTED_UNCONFIRMED"),
        ("submitted_unconfirmed", "UNKNOWN"),
        ("creation_failed", "CONFIRMED"),
        ("rejected", "FAILED"),
    ],
)
def test_finalize_rejects_state_outcome_permutations_and_rolls_back(
    isolated_database, lifecycle_state, outcome
):
    database.init_database()
    intent_id = f"intent-invalid-{lifecycle_state}-{outcome}"
    _prepare_intent(intent_id)

    with pytest.raises(ValueError, match="state/outcome"):
        _finalize_intent(
            intent_id,
            lifecycle_state=lifecycle_state,
            outcome=outcome,
            trade_id=None,
            offer_hash=None,
            reason_code="TEST_INVALID_PERMUTATION",
        )

    intent = database.get_offer_intent(intent_id)
    assert intent["lifecycle_state"] == "prepared"
    assert intent["row_version"] == 0
    assert len(database.get_offer_operation_events(f"create:{intent_id}")) == 1


@pytest.mark.parametrize(
    ("lifecycle_state", "outcome", "expected_blocking"),
    [
        ("created", "CONFIRMED", 0),
        ("submitted_unconfirmed", "SUBMITTED_UNCONFIRMED", 1),
        ("creation_unknown", "UNKNOWN", 1),
        ("creation_failed", "FAILED", 0),
    ],
)
def test_finalize_derives_blocking_from_allowed_creation_outcome(
    isolated_database, lifecycle_state, outcome, expected_blocking
):
    database.init_database()
    intent_id = f"intent-{lifecycle_state}"
    _prepare_intent(intent_id)
    is_confirmed = outcome == "CONFIRMED"

    finalized = _finalize_intent(
        intent_id,
        lifecycle_state=lifecycle_state,
        outcome=outcome,
        trade_id=_sha(f"trade:{intent_id}") if is_confirmed else None,
        offer_hash=_sha(f"offer:{intent_id}") if is_confirmed else None,
        blocks_mutation=not bool(expected_blocking),
        reason_code=None if is_confirmed else f"CREATE_{outcome}",
    )

    event = database.get_offer_operation_events(f"create:{intent_id}")[-1]
    assert finalized["lifecycle_state"] == lifecycle_state
    assert event["outcome"] == outcome
    assert event["blocks_mutation"] == expected_blocking
    assert (finalized["sage_trade_id"] is not None) is is_confirmed
    assert (finalized["offer_text_sha256"] is not None) is is_confirmed


def test_unknown_creation_remains_latest_blocker_until_confirmed_reconciliation(
    isolated_database,
):
    database.init_database()
    _prepare_intent()

    _finalize_intent(
        lifecycle_state="creation_unknown",
        outcome="UNKNOWN",
        trade_id=None,
        offer_hash=None,
        blocks_mutation=False,
        reason_code="RPC_TIMEOUT",
    )

    blockers = database.get_unresolved_offer_operation_blockers()
    assert [(row["operation_id"], row["outcome"]) for row in blockers] == [
        ("create:intent-1", "UNKNOWN")
    ]

    _finalize_intent(
        event_id="event:reconciled:intent-1",
        attempt=2,
        lifecycle_state="created",
        outcome="CONFIRMED",
        trade_id=_sha("trade:intent-1"),
        offer_hash=_sha("offer:intent-1"),
    )
    assert database.get_unresolved_offer_operation_blockers() == []


@pytest.mark.parametrize("source_state", ["submitted_unconfirmed", "creation_unknown"])
@pytest.mark.parametrize(
    ("destination_state", "destination_outcome"),
    [
        ("submitted_unconfirmed", "SUBMITTED_UNCONFIRMED"),
        ("creation_unknown", "UNKNOWN"),
        ("creation_failed", "FAILED"),
    ],
)
def test_ambiguous_creation_may_not_transition_to_nonconfirmed_destination(
    isolated_database, source_state, destination_state, destination_outcome
):
    database.init_database()
    intent_id = f"intent:{source_state}:{destination_state}"
    _prepare_intent(intent_id)
    source_outcome = (
        "SUBMITTED_UNCONFIRMED"
        if source_state == "submitted_unconfirmed"
        else "UNKNOWN"
    )
    _finalize_intent(
        intent_id,
        lifecycle_state=source_state,
        outcome=source_outcome,
        trade_id=None,
        offer_hash=None,
        reason_code="wallet-timeout",
    )

    with pytest.raises(ValueError, match="source/destination"):
        _finalize_intent(
            intent_id,
            event_id=f"event:transition:{intent_id}",
            attempt=2,
            lifecycle_state=destination_state,
            outcome=destination_outcome,
            trade_id=None,
            offer_hash=None,
            reason_code="still-ambiguous",
        )

    current = database.get_offer_intent(intent_id)
    assert current["lifecycle_state"] == source_state
    assert current["row_version"] == 1
    latest = database.get_unresolved_offer_operation_blockers()
    assert [row["operation_id"] for row in latest] == [f"create:{intent_id}"]
    assert latest[0]["blocks_mutation"] == 1
    with pytest.raises(sqlite3.IntegrityError):
        _prepare_intent(f"replacement:{intent_id}")


@pytest.mark.parametrize("source_state", ["submitted_unconfirmed", "creation_unknown"])
def test_ambiguous_creation_may_only_reconcile_to_confirmed_created(
    isolated_database, source_state
):
    database.init_database()
    intent_id = f"intent:reconcile:{source_state}"
    _prepare_intent(intent_id)
    _finalize_intent(
        intent_id,
        lifecycle_state=source_state,
        outcome=(
            "SUBMITTED_UNCONFIRMED"
            if source_state == "submitted_unconfirmed"
            else "UNKNOWN"
        ),
        trade_id=None,
        offer_hash=None,
        reason_code="wallet-timeout",
    )

    reconciled = _finalize_intent(
        intent_id,
        event_id=f"event:reconciled:{intent_id}",
        attempt=2,
    )

    assert reconciled["lifecycle_state"] == "created"
    assert reconciled["row_version"] == 2
    assert database.get_unresolved_offer_operation_blockers() == []


@pytest.mark.parametrize(
    ("terminal_state", "terminal_outcome", "trade_id", "offer_hash", "reason_code"),
    [
        ("created", "CONFIRMED", _DEFAULT, _DEFAULT, None),
        ("creation_failed", "FAILED", None, None, "wallet-rejected"),
    ],
)
def test_terminal_creation_states_reject_later_transition_events(
    isolated_database,
    terminal_state,
    terminal_outcome,
    trade_id,
    offer_hash,
    reason_code,
):
    database.init_database()
    intent_id = f"intent:terminal:{terminal_state}"
    _prepare_intent(intent_id)
    terminal = _finalize_intent(
        intent_id,
        lifecycle_state=terminal_state,
        outcome=terminal_outcome,
        trade_id=trade_id,
        offer_hash=offer_hash,
        reason_code=reason_code,
    )

    with pytest.raises(ValueError, match="already finalized"):
        _finalize_intent(
            intent_id,
            event_id=f"event:after-terminal:{intent_id}",
            attempt=2,
            lifecycle_state="creation_failed",
            outcome="FAILED",
            trade_id=None,
            offer_hash=None,
            reason_code="late-failure",
        )

    assert database.get_offer_intent(intent_id) == terminal
    assert len(database.get_offer_operation_events(f"create:{intent_id}")) == 2


def test_historical_exact_replay_after_reconciliation_returns_current_intent(
    isolated_database,
):
    database.init_database()
    _prepare_intent("intent-historical-replay")
    _finalize_intent(
        "intent-historical-replay",
        lifecycle_state="creation_unknown",
        outcome="UNKNOWN",
        trade_id=None,
        offer_hash=None,
        reason_code="wallet-timeout",
        evidence_json={"request": "historical"},
    )
    reconciled = _finalize_intent(
        "intent-historical-replay",
        event_id="event:reconcile:intent-historical-replay",
        attempt=2,
    )

    replayed = _finalize_intent(
        "intent-historical-replay",
        lifecycle_state="creation_unknown",
        outcome="UNKNOWN",
        trade_id=None,
        offer_hash=None,
        reason_code="wallet-timeout",
        evidence_json={"request": "historical"},
    )

    assert replayed == reconciled
    assert (
        len(database.get_offer_operation_events("create:intent-historical-replay")) == 3
    )

    with pytest.raises(ValueError, match="different journal data"):
        _finalize_intent(
            "intent-historical-replay",
            lifecycle_state="creation_unknown",
            outcome="UNKNOWN",
            trade_id=None,
            offer_hash=None,
            reason_code="different-reason",
            evidence_json={"request": "historical"},
        )


def test_finalize_exact_replay_includes_publication_and_child_identity(
    isolated_database,
):
    database.init_database()
    _prepare_intent()
    first = _finalize_intent(
        publication_identity="publication:1",
        child_intent_id="intent-child-1",
    )

    replay = _finalize_intent(
        publication_identity="publication:1",
        child_intent_id="intent-child-1",
    )
    assert replay == first

    with pytest.raises(ValueError, match="different intent state"):
        _finalize_intent(
            publication_identity="publication:other",
            child_intent_id="intent-child-other",
        )

    persisted = database.get_offer_intent("intent-1")
    assert persisted["publication_identity"] == "publication:1"
    assert persisted["child_intent_id"] == "intent-child-1"
    assert len(database.get_offer_operation_events("create:intent-1")) == 2


@pytest.mark.parametrize("generation", [True, 7.0, "7"])
def test_prepare_rejects_coercible_noninteger_generation(isolated_database, generation):
    database.init_database()

    with pytest.raises(ValueError, match="generation must be an integer"):
        _prepare_intent("intent-bad-generation", generation=generation)
    assert database.get_offer_intent("intent-bad-generation") is None


@pytest.mark.parametrize(
    ("state", "outcome", "trade_id", "offer_hash", "reason_code"),
    [
        ("prepared", None, None, None, None),
        (
            "submitted_unconfirmed",
            "SUBMITTED_UNCONFIRMED",
            None,
            None,
            "wallet-timeout",
        ),
        ("creation_unknown", "UNKNOWN", None, None, "wallet-timeout"),
        ("created", "CONFIRMED", _DEFAULT, _DEFAULT, None),
    ],
)
def test_active_lifecycle_states_hold_one_database_enforced_slot_generation(
    isolated_database, state, outcome, trade_id, offer_hash, reason_code
):
    database.init_database()
    _prepare_intent("intent-active-a")
    if outcome is not None:
        _finalize_intent(
            "intent-active-a",
            lifecycle_state=state,
            outcome=outcome,
            trade_id=trade_id,
            offer_hash=offer_hash,
            reason_code=reason_code,
        )

    with pytest.raises(sqlite3.IntegrityError):
        _prepare_intent("intent-active-b")
    assert database.get_offer_intent("intent-active-b") is None


def test_terminal_failure_releases_slot_until_replacement_becomes_active(
    isolated_database,
):
    database.init_database()
    _prepare_intent("intent-failed-a")
    _finalize_intent(
        "intent-failed-a",
        lifecycle_state="creation_failed",
        outcome="FAILED",
        trade_id=None,
        offer_hash=None,
        reason_code="wallet-rejected",
    )

    replacement = _prepare_intent("intent-failed-b")
    with pytest.raises(sqlite3.IntegrityError):
        _prepare_intent("intent-next-generation", generation=8)

    assert replacement["lifecycle_state"] == "prepared"
    assert database.get_offer_intent("intent-next-generation") is None


def test_racing_prepares_cannot_claim_same_active_slot_generation(
    isolated_database,
):
    database.init_database()

    def prepare(intent_id):
        try:
            return ("ok", _prepare_intent(intent_id)["intent_id"])
        except sqlite3.IntegrityError:
            return ("conflict", intent_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(prepare, ["intent-race-a", "intent-race-b"]))

    assert sorted(result[0] for result in results) == ["conflict", "ok"]
    assert (
        sum(
            database.get_offer_intent(intent_id) is not None
            for intent_id in ("intent-race-a", "intent-race-b")
        )
        == 1
    )


@pytest.mark.parametrize("attempt", [True, 1.0, "1"])
def test_journal_rejects_coercible_noninteger_attempt(isolated_database, attempt):
    database.init_database()

    with pytest.raises(ValueError, match="attempt must be an integer"):
        database.append_offer_operation_event(
            event_id="event:bad-attempt",
            operation_id="operation:bad-attempt",
            operation_type="RECONCILE",
            attempt=attempt,
            phase="READ",
            outcome="UNKNOWN",
            request_timestamp=AT,
            evidence_json={},
        )
    assert database.get_offer_operation_events("operation:bad-attempt") == []


@pytest.mark.parametrize("row_version", [True, 0.0, "0"])
def test_finalize_rejects_coercible_noninteger_row_version(
    isolated_database, row_version
):
    database.init_database()
    _prepare_intent()

    with pytest.raises(ValueError, match="expected_row_version must be an integer"):
        database.finalize_offer_intent(
            intent_id="intent-1",
            operation_id="create:intent-1",
            event_id="event:bad-version",
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=_sha("trade:intent-1"),
            offer_text_sha256=_sha("offer:intent-1"),
            expected_row_version=row_version,
            evidence_json={},
            finalized_at=LATER,
        )
    assert database.get_offer_intent("intent-1")["row_version"] == 0


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
    assert [
        row["operation_id"]
        for row in database.get_unresolved_offer_operation_blockers()
    ] == ["cancel:intent-1"]

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
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        heartbeat_at=LATER,
    )
    assert heartbeat["heartbeat"] is True
    assert heartbeat["lease"]["lease_version"] == 2

    stale_heartbeat = database.heartbeat_runtime_mutation_lease(
        owner_run_id="run-a",
        expected_lease_version=1,
        lease_expires_at="2026-08-15T12:11:00.000000Z",
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
        lease_expires_at="2026-08-15T12:20:00.000000Z",
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
        lease_expires_at="2026-08-15T12:20:00.000000Z",
        now=AFTER_EXPIRY,
        allow_expired_takeover=True,
        expected_lease_version=1,
    )
    assert takeover["acquired"] is True
    assert takeover["reason"] == "expired_lease_taken_over"
    assert takeover["lease"]["owner_run_id"] == "run-b"
    assert takeover["lease"]["lease_version"] == 2


@pytest.mark.parametrize(
    ("now", "expiry", "expected_now", "expected_expiry"),
    [
        (
            "2026-08-15T13:00:00+01:00",
            "2026-08-15T13:05:00+01:00",
            AT,
            EXPIRES,
        ),
        (
            "2026-08-15T07:00:00-05:00",
            "2026-08-15T07:05:00-05:00",
            AT,
            EXPIRES,
        ),
        (
            "2026-08-15T12:00:00.123456Z",
            "2026-08-15T12:05:00.654321Z",
            "2026-08-15T12:00:00.123456Z",
            "2026-08-15T12:05:00.654321Z",
        ),
    ],
)
def test_lease_timestamps_normalize_offsets_to_sortable_utc(
    isolated_database, now, expiry, expected_now, expected_expiry
):
    database.init_database()

    result = database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=expiry,
        now=now,
    )

    assert result["acquired"] is True
    assert result["lease"]["acquired_at"] == expected_now
    assert result["lease"]["heartbeat_at"] == expected_now
    assert result["lease"]["expires_at"] == expected_expiry


@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "not-a-time",
        "2026-08-15 12:00:00",
        "2026-08-15 12:00:00+00:00",
        "2026-08-15T12:00:00",
        "2026-08-15T12:00Z",
        "2026-08-15T12:00:00z",
        "2026-08-15T12:00:00,123Z",
        "2026-08-15",
        "2026-08-15T25:00:00Z",
        "2026-08-15T12:00:00+99:00",
    ],
)
def test_lease_rejects_invalid_or_naive_timestamp_before_write(
    isolated_database, bad_timestamp
):
    database.init_database()

    with pytest.raises(ValueError, match="timestamp"):
        database.acquire_runtime_mutation_lease(
            owner_run_id="run-a",
            owner_pid=100,
            owner_host="host-a",
            wallet_fingerprint_hash=_sha("wallet-a"),
            network="mainnet",
            lease_expires_at=EXPIRES,
            now=bad_timestamp,
        )
    assert database.get_runtime_mutation_lease()["active"] == 0


def test_same_owner_lease_renewal_requires_exact_fencing_and_binding(
    isolated_database,
):
    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=EXPIRES,
        now=AT,
    )

    no_version = database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now=LATER,
    )
    assert no_version["acquired"] is False
    assert no_version["reason"] == "renewal_requires_compare_and_set"

    mismatches = [
        {"owner_pid": 101},
        {"owner_host": "host-b"},
        {"wallet_fingerprint_hash": _sha("wallet-b")},
        {"network": "testnet11"},
    ]
    for mismatch in mismatches:
        values = {
            "owner_run_id": "run-a",
            "owner_pid": 100,
            "owner_host": "host-a",
            "wallet_fingerprint_hash": _sha("wallet-a"),
            "network": "mainnet",
            "lease_expires_at": "2026-08-15T12:10:00.000000Z",
            "now": LATER,
            "expected_lease_version": 1,
        }
        values.update(mismatch)
        result = database.acquire_runtime_mutation_lease(**values)
        assert result["acquired"] is False
        assert result["reason"] == "owner_binding_mismatch"
        assert result["lease"]["lease_version"] == 1

    renewed = database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now=LATER,
        expected_lease_version=1,
    )
    assert renewed["acquired"] is True
    assert renewed["reason"] == "renewed"
    assert renewed["lease"]["lease_version"] == 2

    stale_restart = database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:11:00.000000Z",
        now="2026-08-15T12:02:00.000000Z",
        expected_lease_version=1,
    )
    assert stale_restart["acquired"] is False
    assert stale_restart["reason"] == "compare_and_set_failed"


def test_same_owner_cannot_renew_expired_lease(isolated_database):
    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=EXPIRES,
        now=AT,
    )

    result = database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:20:00.000000Z",
        now=AFTER_EXPIRY,
        expected_lease_version=1,
    )

    assert result["acquired"] is False
    assert result["reason"] == "lease_expired"
    assert result["lease"]["lease_version"] == 1


def test_heartbeat_cannot_resurrect_or_shorten_lease(isolated_database):
    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=EXPIRES,
        now=AT,
    )

    shortened = database.heartbeat_runtime_mutation_lease(
        owner_run_id="run-a",
        expected_lease_version=1,
        lease_expires_at="2026-08-15T12:04:00.000000Z",
        heartbeat_at=LATER,
    )
    assert shortened["heartbeat"] is False
    assert shortened["reason"] == "new_expiry_not_monotonic"

    expired = database.heartbeat_runtime_mutation_lease(
        owner_run_id="run-a",
        expected_lease_version=1,
        lease_expires_at="2026-08-15T12:20:00.000000Z",
        heartbeat_at=AFTER_EXPIRY,
    )
    assert expired["heartbeat"] is False
    assert expired["reason"] == "lease_expired"
    assert expired["lease"]["lease_version"] == 1


@pytest.mark.parametrize("operation", ["renew", "heartbeat"])
def test_lease_waiter_uses_post_lock_wall_clock_and_cannot_cross_expiry(
    isolated_database, monkeypatch, operation
):
    monkeypatch.setattr(
        database,
        "_stability_wall_clock",
        lambda: database._stability_timestamp(datetime.now(timezone.utc), "wall clock"),
        raising=False,
    )
    database.init_database()
    started = datetime.now(timezone.utc)
    expires = started + timedelta(seconds=0.35)
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=expires,
        now=started,
    )

    blocker = sqlite3.connect(isolated_database, timeout=2, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")

    def wait_for_lock():
        if operation == "renew":
            return database.acquire_runtime_mutation_lease(
                owner_run_id="run-a",
                owner_pid=100,
                owner_host="host-a",
                wallet_fingerprint_hash=_sha("wallet-a"),
                network="mainnet",
                lease_expires_at=started + timedelta(seconds=10),
                now=started + timedelta(seconds=0.1),
                expected_lease_version=1,
            )
        return database.heartbeat_runtime_mutation_lease(
            owner_run_id="run-a",
            expected_lease_version=1,
            lease_expires_at=started + timedelta(seconds=10),
            heartbeat_at=started + timedelta(seconds=0.1),
        )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(wait_for_lock)
            time.sleep(0.55)
            assert future.done() is False
            blocker.commit()
            result = future.result(timeout=5)
    finally:
        if blocker.in_transaction:
            blocker.rollback()
        blocker.close()

    success_key = "acquired" if operation == "renew" else "heartbeat"
    assert result[success_key] is False
    assert result["reason"] == "lease_expired"
    assert result["lease"]["lease_version"] == 1


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_lease_cas_rejects_coercible_noninteger_versions(isolated_database, version):
    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=EXPIRES,
        now=AT,
    )

    with pytest.raises(ValueError, match="expected_lease_version must be an integer"):
        database.heartbeat_runtime_mutation_lease(
            owner_run_id="run-a",
            expected_lease_version=version,
            lease_expires_at="2026-08-15T12:10:00.000000Z",
            heartbeat_at=LATER,
        )
    with pytest.raises(ValueError, match="expected_lease_version must be an integer"):
        database.release_runtime_mutation_lease(
            owner_run_id="run-a",
            expected_lease_version=version,
            released_at=LATER,
        )
    assert database.get_runtime_mutation_lease()["lease_version"] == 1


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_lease_reacquire_rejects_coercible_noninteger_version(
    isolated_database, version
):
    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=100,
        owner_host="host-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at=EXPIRES,
        now=AT,
    )

    with pytest.raises(ValueError, match="expected_lease_version must be an integer"):
        database.acquire_runtime_mutation_lease(
            owner_run_id="run-a",
            owner_pid=100,
            owner_host="host-a",
            wallet_fingerprint_hash=_sha("wallet-a"),
            network="mainnet",
            lease_expires_at="2026-08-15T12:10:00.000000Z",
            now=LATER,
            expected_lease_version=version,
        )


@pytest.mark.parametrize("generation", [True, 1.0, "1"])
def test_latch_resolve_rejects_coercible_noninteger_generation(
    isolated_database, generation
):
    database.init_database()

    with pytest.raises(ValueError, match="expected_generation must be an integer"):
        database.resolve_runtime_safety_latch(
            expected_generation=generation,
            resolved_operation_ids=[],
            resolved_at=LATER,
        )


def test_delegation_uses_utc_normalization_for_expiry_comparison(isolated_database):
    database.init_database()
    issued = database.issue_worker_delegation(
        delegation_id="delegation-offset",
        delegation_token_hash=_sha("token-offset"),
        parent_run_id="run-a",
        operation_id="coin-prep:offset",
        worker_id="worker-1",
        purpose="replacement-capacity",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        issued_at="2026-08-15T13:00:00+01:00",
        expires_at="2026-08-15T07:05:00-05:00",
    )
    assert issued["issued_at"] == AT
    assert issued["expires_at"] == EXPIRES

    assert (
        database.get_valid_worker_delegation(
            delegation_id="delegation-offset",
            delegation_token_hash=_sha("token-offset"),
            parent_run_id="run-a",
            operation_id="coin-prep:offset",
            purpose="replacement-capacity",
            wallet_fingerprint_hash=_sha("wallet-a"),
            network="mainnet",
            now="2026-08-15T13:04:00+01:00",
        )
        is not None
    )
    assert database.expire_worker_delegations(now="2026-08-15T08:06:00-04:00") == 1


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
