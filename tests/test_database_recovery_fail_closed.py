"""An incomplete SQLite salvage must not replace durable trading authority."""

import sqlite3

import database


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
