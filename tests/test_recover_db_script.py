"""Manual recovery must preserve the live authority on failed replacement."""

import sqlite3

from scripts import recover_db


def test_manual_salvage_never_replaces_live_authority(monkeypatch, tmp_path):
    db_path = tmp_path / "bot.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE fee_ledger (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO fee_ledger VALUES ('existing-grant')")
        conn.commit()
    finally:
        conn.close()
    original = db_path.read_bytes()

    monkeypatch.setattr(recover_db, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(recover_db, "_is_locked", lambda _path: False)
    monkeypatch.setattr(
        recover_db,
        "_integrity",
        lambda path: (
            (True, "ok") if path.name.endswith(".recovered") else (False, "damaged")
        ),
    )
    assert recover_db.main() != 0
    assert db_path.read_bytes() == original
    assert (tmp_path / "bot.db.recovered").exists()


def test_incomplete_manual_salvage_discards_candidate(monkeypatch, tmp_path):
    db_path = tmp_path / "bot.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE fee_ledger (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO fee_ledger VALUES ('existing-grant')")
        conn.commit()
    finally:
        conn.close()
    original = db_path.read_bytes()
    monkeypatch.setattr(recover_db, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(recover_db, "_is_locked", lambda _path: False)
    monkeypatch.setattr(recover_db, "_integrity", lambda _path: (False, "damaged"))

    class RejectSalvagedRow(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("INSERT INTO"):
                raise sqlite3.OperationalError("simulated destination write failure")
            return super().execute(sql, *args, **kwargs)

    original_connect = recover_db.sqlite3.connect

    def reject_recovered_insert(path, *args, **kwargs):
        if str(path).endswith("bot.db.recovered"):
            kwargs["factory"] = RejectSalvagedRow
        return original_connect(path, *args, **kwargs)

    monkeypatch.setattr(recover_db.sqlite3, "connect", reject_recovered_insert)

    assert recover_db.main() != 0
    assert db_path.read_bytes() == original
    assert not (tmp_path / "bot.db.recovered").exists()
