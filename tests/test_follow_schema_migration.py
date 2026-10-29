import database
import pytest

KEY = "follow-run-authority-schema"
TABLES = ("follow_run_stops", "follow_run_authorities", "follow_run_reviews")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "migration.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def test_existing_watermark_allows_first_follow_install(isolated_db):
    conn = database.get_connection()
    conn.execute("DROP TRIGGER stability_migration_watermarks_no_delete")
    conn.execute(
        "DELETE FROM stability_migration_watermarks WHERE migration_key=?", (KEY,)
    )
    for table in TABLES:
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
        == 1
    )
    assert all(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        for table in TABLES
    )
    database.close_connection()
    database._migrate_stability_schema()


def test_existing_follow_profile_installs_append_only_reapproval_table(isolated_db):
    conn = database.get_connection()
    conn.execute("DROP TABLE follow_run_reapprovals")
    conn.commit()
    database.close_connection()
    database._migrate_stability_schema()
    conn = database.get_connection()
    assert (
        conn.execute("SELECT count(*) FROM follow_run_reapprovals").fetchone()[0] == 0
    )


@pytest.mark.parametrize("table", TABLES)
def test_follow_watermark_rejects_missing_installed_table(isolated_db, table):
    conn = database.get_connection()
    conn.execute(f"DROP TABLE {table}")
    conn.commit()
    database.close_connection()
    with pytest.raises(
        RuntimeError, match="Follow authority schema watermark contradicts schema"
    ):
        database._migrate_stability_schema()
