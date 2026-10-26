"""Fee ceiling revision tables have their own original-profile migration gate."""

import database
import pytest


KEY = "follow-fee-ceiling-revision-schema"
TABLES = ("follow_fee_ceiling_reviews", "follow_fee_ceiling_revisions")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "migration.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def test_existing_profile_can_install_revision_schema_once(isolated_db):
    conn = database.get_connection()
    conn.execute("DROP TRIGGER stability_migration_watermarks_no_delete")
    conn.execute(
        "DELETE FROM stability_migration_watermarks WHERE migration_key=?", (KEY,)
    )
    for table in reversed(TABLES):
        conn.execute(f"DROP TABLE {table}")
    conn.commit()
    database.close_connection()
    database._migrate_stability_schema()
    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT schema_version FROM stability_migration_watermarks WHERE migration_key=?",
            (KEY,),
        ).fetchone()[0]
        == 2
    )
    assert all(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        for table in TABLES
    )
    database.close_connection()
    database._migrate_stability_schema()


@pytest.mark.parametrize("table", TABLES)
def test_revision_watermark_rejects_missing_installed_table(isolated_db, table):
    conn = database.get_connection()
    conn.execute(f"DROP TABLE {table}")
    conn.commit()
    database.close_connection()
    with pytest.raises(RuntimeError, match="fee ceiling revision schema watermark"):
        database._migrate_stability_schema()
