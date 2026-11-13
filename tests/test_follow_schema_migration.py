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


def test_existing_follow_tables_migrate_to_unbounded_positive_slot_counts(isolated_db):
    conn = database.get_connection()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN EXCLUSIVE")
    dependent_triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' "
        "AND tbl_name!='follow_run_authorities' "
        "AND sql LIKE '%follow_run_authorities%'"
    ).fetchall()
    for (trigger_name,) in dependent_triggers:
        conn.execute(f'DROP TRIGGER "{trigger_name}"')
    conn.commit()
    for table in ("follow_run_reviews", "follow_run_authorities"):
        definition = str(
            conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
        )
        assert "buy_limit>0" in definition
        assert "sell_limit>0" in definition
        legacy_definition = definition.replace(
            "buy_limit>0", "buy_limit BETWEEN 1 AND 50"
        ).replace("sell_limit>0", "sell_limit BETWEEN 1 AND 50")
        temporary = f"{table}_legacy_limit"
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute(
            legacy_definition.replace(
                f"CREATE TABLE {table} (", f"CREATE TABLE {temporary} (", 1
            )
        )
        conn.execute(f"INSERT INTO {temporary} SELECT * FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {temporary} RENAME TO {table}")
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
    database.close_connection()
    database._migrate_stability_schema()
    conn = database.get_connection()
    for table in ("follow_run_reviews", "follow_run_authorities"):
        definition = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0]
        assert "BETWEEN 1 AND 50" not in definition
        assert "buy_limit>0" in definition
        assert "sell_limit>0" in definition
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
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


def test_legacy_unique_approval_schema_upgrades_once(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    current_sql = database.STABILITY_SCHEMA_SQL
    prefix, authority_sql = current_sql.split(
        "CREATE TABLE IF NOT EXISTS follow_run_authorities (", 1
    )
    legacy_sql = (
        prefix
        + "CREATE TABLE IF NOT EXISTS follow_run_authorities ("
        + authority_sql.replace(
            "approval_id TEXT NOT NULL REFERENCES coin_prep_fee_consents(approval_id)",
            "approval_id TEXT UNIQUE NOT NULL REFERENCES coin_prep_fee_consents(approval_id)",
            1,
        )
    )
    assert legacy_sql != current_sql
    monkeypatch.setattr(database, "STABILITY_SCHEMA_SQL", legacy_sql)
    database.init_database()
    database.close_connection()
    monkeypatch.setattr(database, "STABILITY_SCHEMA_SQL", current_sql)

    database._migrate_stability_schema()
    database._migrate_stability_schema()
    conn = database.get_connection()
    definition = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='follow_run_authorities'"
    ).fetchone()[0]
    assert "approval_id TEXT NOT NULL REFERENCES" in definition
    assert "approval_id TEXT UNIQUE NOT NULL REFERENCES" not in definition
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_follow_run_authorities_approval'"
        ).fetchone()
        is not None
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
