"""An incomplete SQLite salvage must not replace durable trading authority."""

import sqlite3

import database
import pytest


def test_missing_database_with_bound_wallet_and_prior_ui_state_fails_closed(
    monkeypatch, tmp_path
):
    (tmp_path / ".env").write_text(
        "WALLET_TYPE=sage\nSAGE_FINGERPRINT='736588221'\n", encoding="utf-8"
    )
    (tmp_path / ".window_state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bot.db"))

    result = database.attempt_db_recovery()

    assert result["action"] == "failed"
    assert result["error"] == "missing_database_existing_profile"
    assert not (tmp_path / "bot.db").exists()


def test_preconfigured_first_run_without_database_is_allowed(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "WALLET_TYPE=sage\nSAGE_FINGERPRINT='123456789'\n", encoding="utf-8"
    )
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bot.db"))

    assert database.attempt_db_recovery() == {
        "action": "ok",
        "result": "no_db_file",
    }


@pytest.mark.parametrize(
    "artifact",
    ["bot.db-wal", "backups/bot_backup_20261006_000000.db", "coin_prep_last.json"],
)
def test_missing_database_with_authority_artifact_fails_closed(
    monkeypatch, tmp_path, artifact
):
    prior = tmp_path / artifact
    prior.parent.mkdir(parents=True, exist_ok=True)
    prior.write_bytes(b"prior profile evidence")
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bot.db"))

    result = database.attempt_db_recovery()

    assert result["action"] == "failed"
    assert result["error"] == "missing_database_existing_profile"


def test_missing_database_in_unbound_first_run_profile_is_allowed(
    monkeypatch, tmp_path
):
    (tmp_path / ".migration_complete").write_text("migration checked")
    (tmp_path / ".env").write_text(
        "WALLET_TYPE=sage\nSAGE_FINGERPRINT=\nCAT_ASSET_ID=\n", encoding="utf-8"
    )
    (tmp_path / "backups").mkdir()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bot.db"))

    assert database.attempt_db_recovery() == {
        "action": "ok",
        "result": "no_db_file",
    }


def test_initialized_unbound_profile_fails_closed_if_database_disappears(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "bot.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.close_connection()
    try:
        database.init_database()
        assert db_path.exists()
        assert (tmp_path / "bot.db.initialized").exists()
        database.close_connection()
        db_path.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = tmp_path / f"bot.db{suffix}"
            if sidecar.exists():
                sidecar.unlink()

        result = database.attempt_db_recovery()

        assert result["action"] == "failed"
        assert result["error"] == "missing_database_existing_profile"
    finally:
        database.close_connection()


def test_partial_salvage_keeps_live_database(monkeypatch, tmp_path):
    db_path = tmp_path / "bot.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE fee_ledger (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO fee_ledger VALUES ('existing-grant')")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(
        database,
        "check_db_integrity",
        lambda: {"ok": False, "result": "simulated damaged page"},
    )

    class RejectSalvagedRow(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("INSERT INTO"):
                raise sqlite3.OperationalError("simulated destination write failure")
            return super().execute(sql, *args, **kwargs)

    original_connect = database._sqlite_connect

    def reject_recovered_insert(path, *args, **kwargs):
        if str(path).endswith("bot.db.recovered"):
            kwargs["factory"] = RejectSalvagedRow
        return original_connect(path, *args, **kwargs)

    monkeypatch.setattr(database, "_sqlite_connect", reject_recovered_insert)

    result = database.attempt_db_recovery()

    assert result["action"] == "failed"
    assert result.get("skipped_statements") == 1
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT id FROM fee_ledger").fetchall() == [
            ("existing-grant",)
        ]
    finally:
        conn.close()


def test_clean_dump_cannot_prove_corrupt_authority_is_complete(monkeypatch, tmp_path):
    db_path = tmp_path / "bot.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE fee_ledger (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO fee_ledger VALUES ('existing-grant')")
        conn.commit()
    finally:
        conn.close()
    original = db_path.read_bytes()
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(
        database,
        "check_db_integrity",
        lambda: {"ok": False, "result": "simulated damaged page"},
    )

    result = database.attempt_db_recovery()

    assert result["action"] == "failed"
    assert result["error"] == "manual_reconciliation_required"
    assert db_path.read_bytes() == original
    assert (tmp_path / "bot.db.recovered").exists()
