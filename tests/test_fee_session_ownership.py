"""Standalone fee scopes are server-owned, stable and cannot reset commitments."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3

import pytest

import coin_prep_fee_approval as service
import database


IDENTITY = {"network": "mainnet", "wallet_type": "sage", "wallet_fingerprint": 736588221,
            "wallet_id": 2, "xch_wallet_id": 1, "asset_id": "b8" * 32, "ticker": "MZ_XCH"}
PLAN = {"target_seconds": 300, "coin_multiplier": "1", "headroom_pct": "0",
        "liquidity_mode": "two_sided", "reserve_floors_mojos": {"xch": 0, "cat": 0},
        "campaign_revision": None, "cancellation_policy": "protected_no_prep",
        "outputs": []}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "sessions.db"))
    database.init_database()
    yield database
    database.close_connection()


def _scope(identity=None, campaign_id=None):
    resolve = getattr(service, "resolve_server_fee_scope", None)
    assert callable(resolve), "durable server-owned preparation scope is missing"
    return resolve(identity=IDENTITY if identity is None else identity, campaign_id=campaign_id)


def _restart(ledger):
    ledger.close_connection()
    ledger._db_initialized_path = None
    ledger.init_database()


def test_refresh_restart_and_resets_reuse_the_same_server_session(ledger):
    first = _scope()
    assert len(first["session_id"]) == 64
    assert first["campaign_id"] is None
    assert first["session_id"] != "d" * 64
    _restart(ledger)
    assert ledger.guarded_reset_authoritative_state(clear_terminal_offers=True)["success"]
    ledger.reset_lifecycle_observability_stats()
    second = _scope(dict(reversed(list(IDENTITY.items()))))
    assert second == first
    conn = ledger.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM coin_prep_fee_sessions").fetchone()[0] == 1
    for table in ("fee_approvals", "approved_fee_reservations", "coin_prep_operations", "wallet_effect_claims"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_concurrent_preview_collectors_share_one_session(ledger):
    with ThreadPoolExecutor(max_workers=4) as pool:
        scopes = list(pool.map(lambda _: _scope(), range(8)))
    assert len({scope["session_id"] for scope in scopes}) == 1
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM coin_prep_fee_sessions").fetchone()[0] == 1


@pytest.mark.parametrize("field,value", [("wallet_fingerprint", 3702373391), ("wallet_id", 3),
                                        ("xch_wallet_id", 4), ("asset_id", "a" * 64),
                                        ("ticker", "DBX_XCH"), ("network", "testnet11"),
                                        ("wallet_type", "chia")])
def test_changed_wallet_identity_cannot_adopt_another_wallet_session(ledger, field, value):
    first = _scope()
    second = _scope({**IDENTITY, field: value})
    assert second["session_id"] != first["session_id"]
    assert _scope() == first


def test_campaign_scope_never_allocates_a_standalone_session(ledger):
    scope = _scope(campaign_id="c" * 64)
    assert scope["campaign_id"] == "c" * 64
    assert scope["session_id"] is None
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM coin_prep_fee_sessions").fetchone()[0] == 0


@pytest.mark.parametrize("overrides", [{"wallet_fingerprint": True}, {"wallet_id": 0},
                                     {"asset_id": "B8" * 32}, {"network": "unknown"},
                                     {"session_id": "d" * 64}, {"plan_sha256": "a" * 64}])
def test_client_authority_or_invalid_identity_cannot_mint_a_session(ledger, overrides):
    with pytest.raises(ValueError):
        _scope({**IDENTITY, **overrides})
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM coin_prep_fee_sessions").fetchone()[0] == 0


def test_refreshed_scope_counts_old_fees_even_when_plan_changes(ledger):
    first = service.canonical_fee_contract(_scope(), PLAN)
    approval = ledger.create_fee_approval(scope_sha256=first["scope_sha256"], plan_sha256=first["plan_sha256"],
                                          total_fee_mojos=80, cancellation_reserve_mojos=20)
    ledger.reserve_approved_fee(approval_id=approval["approval_id"], scope_sha256=first["scope_sha256"],
                                plan_sha256=first["plan_sha256"], operation_id="1" * 64,
                                fee_mojos=30, cancellation=False)
    changed = service.canonical_fee_contract(_scope(), {**PLAN, "headroom_pct": "10"})
    assert changed["scope_sha256"] == first["scope_sha256"]
    assert changed["plan_sha256"] != first["plan_sha256"]
    updated = ledger.create_fee_approval(scope_sha256=changed["scope_sha256"], plan_sha256=changed["plan_sha256"],
                                         total_fee_mojos=90, cancellation_reserve_mojos=20)
    assert updated["version"] == 2
    assert updated["held_fee_mojos"] == 30
    assert updated["remaining_preparation_fee_mojos"] == 40


def test_session_records_cannot_be_replaced_deleted_or_rebound(ledger):
    scope = _scope()
    conn = ledger.get_connection()
    for statement in ("DELETE FROM coin_prep_fee_sessions",
                      "UPDATE coin_prep_fee_sessions SET generation=2",
                      "INSERT OR REPLACE INTO coin_prep_fee_sessions SELECT * FROM coin_prep_fee_sessions"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
        conn.rollback()
    assert _scope() == scope


def test_second_session_generation_cannot_discard_an_unfinished_scope(ledger):
    _scope()
    conn = ledger.get_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO coin_prep_fee_sessions "
                     "SELECT ?, identity_sha256, identity_json, 2, created_at FROM coin_prep_fee_sessions",
                     ("e" * 64,))
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM coin_prep_fee_sessions").fetchone()[0] == 1


def test_session_lookup_returns_canonical_identity_but_no_spending_permission(ledger):
    scope = _scope()
    session = ledger.get_coin_prep_fee_session(scope["session_id"])
    encoded = json.dumps(IDENTITY, sort_keys=True, separators=(",", ":"))
    assert session["identity_json"] == encoded
    assert session["identity_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert session["generation"] == 1
    assert session["current_session_id"] == scope["session_id"]
    assert session.get("dispatch_authorized", False) is False


def test_lost_session_guard_blocks_readback(ledger):
    scope = _scope()
    conn = ledger.get_connection()
    conn.execute("DROP TRIGGER coin_prep_fee_sessions_no_delete")
    conn.commit()
    with pytest.raises(RuntimeError, match="trigger"):
        ledger.get_coin_prep_fee_session(scope["session_id"])


def test_unknown_session_cannot_be_adopted_from_a_preview(ledger):
    _scope()
    with pytest.raises(ValueError, match="FEE_SESSION_REQUIRED"):
        ledger.get_coin_prep_fee_session("d" * 64)


def _remove_fee_watermark(conn):
    # Only the isolated fixture is rewound to the actual old schema shape.
    guard = conn.execute("SELECT sql FROM sqlite_master WHERE "
                         "name='stability_migration_watermarks_no_delete'").fetchone()[0]
    conn.execute("DROP TRIGGER stability_migration_watermarks_no_delete")
    conn.execute("DELETE FROM stability_migration_watermarks WHERE migration_key='coin-prep-fee-approval-schema'")
    conn.execute(guard)


def _remove_fee_tables(ledger):
    conn = ledger.get_connection()
    _remove_fee_watermark(conn)
    for table in ("coin_prep_fee_consents", "coin_prep_fee_previews", "approved_fee_outcomes",
                  "approved_fee_reservations", "fee_approvals", "coin_prep_fee_sessions"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    ledger.close_connection()


def test_upgrade_from_pre_fee_schema_keeps_existing_stability_watermarks(ledger):
    # A real prior installation already completed stability migrations but had
    # no fee schema. It must upgrade, not be mistaken for erased legacy evidence.
    prior = [tuple(row) for row in ledger.get_connection().execute(
        "SELECT * FROM stability_migration_watermarks WHERE migration_key<>'coin-prep-fee-approval-schema'")]
    _remove_fee_tables(ledger)
    try:
        _restart(ledger)
    except RuntimeError as exc:
        pytest.fail(f"legitimate pre-fee installation cannot upgrade: {exc}")
    recovered = [tuple(row) for row in ledger.get_connection().execute(
        "SELECT * FROM stability_migration_watermarks WHERE migration_key<>'coin-prep-fee-approval-schema'")]
    assert recovered == prior
    assert _scope()["session_id"]


def test_migration_adds_session_ownership_without_releasing_existing_fees(ledger):
    approval = ledger.create_fee_approval(scope_sha256="a" * 64, plan_sha256="b" * 64,
                                         total_fee_mojos=80, cancellation_reserve_mojos=20)
    ledger.reserve_approved_fee(approval_id=approval["approval_id"], scope_sha256="a" * 64,
                                plan_sha256="b" * 64, operation_id="1" * 64, fee_mojos=30,
                                cancellation=False)
    conn = ledger.get_connection()
    _remove_fee_watermark(conn)
    conn.execute("DROP TABLE IF EXISTS coin_prep_fee_sessions")
    conn.commit()
    _restart(ledger)
    assert ledger.get_fee_approval(approval["approval_id"])["held_fee_mojos"] == 30
    assert _scope()["session_id"]


def test_missing_session_table_after_completed_migration_is_not_recreated_silently(ledger):
    _scope()
    conn = ledger.get_connection()
    conn.execute("DROP TABLE coin_prep_fee_sessions")
    conn.commit()
    with pytest.raises(RuntimeError, match="fee.*watermark.*schema"):
        _restart(ledger)
