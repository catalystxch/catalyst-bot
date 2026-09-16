from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import database
import pytest
from market_evidence import migrate_post_tibet_state
import inspect


ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
POST_TIBET_SCHEMA_KEY = "post-tibetswap-offer-book-schema"
POST_TIBET_REQUIRED_TABLES = (
    "fill_confidence_assessments",
    "offer_book_competition_claims",
    "offer_publication_discoveries",
)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "migration.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def _add_offer(trade_id: str):
    assert database.add_offer(
        trade_id=trade_id,
        side="buy",
        price_xch=Decimal("0.1"),
        size_xch=Decimal("1"),
        size_cat=Decimal("10"),
        cat_asset_id=ASSET_ID,
    )


def _remove_post_tibet_schema_watermark(conn):
    conn.execute("DROP TRIGGER stability_migration_watermarks_no_delete")
    conn.execute(
        "DELETE FROM stability_migration_watermarks WHERE migration_key=?",
        (POST_TIBET_SCHEMA_KEY,),
    )
    conn.execute(
        """CREATE TRIGGER stability_migration_watermarks_no_delete
        BEFORE DELETE ON stability_migration_watermarks BEGIN
            SELECT RAISE(ABORT, 'stability_migration_watermarks is append-only');
        END"""
    )


def test_v13_watermark_allows_first_post_tibet_schema_install(isolated_db):
    conn = database.get_connection()
    _remove_post_tibet_schema_watermark(conn)
    for table_name in POST_TIBET_REQUIRED_TABLES:
        conn.execute(f"DROP TABLE {table_name}")
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    conn = database.get_connection()
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    watermark = conn.execute(
        "SELECT schema_version, policy_sha256 "
        "FROM stability_migration_watermarks WHERE migration_key=?",
        (POST_TIBET_SCHEMA_KEY,),
    ).fetchone()
    assert set(POST_TIBET_REQUIRED_TABLES) <= tables
    assert watermark is not None
    assert watermark["schema_version"] == 1
    assert len(watermark["policy_sha256"]) == 64


def test_post_tibet_watermark_rejects_missing_installed_schema(isolated_db):
    conn = database.get_connection()
    conn.execute("DROP TABLE offer_book_competition_claims")
    conn.commit()
    database.close_connection()

    with pytest.raises(
        RuntimeError,
        match="post-TibetSwap schema watermark contradicts schema",
    ):
        database._migrate_stability_schema()


def test_migration_retains_proven_owned_offer_and_legacy_tibet_history(isolated_db):
    _add_offer("owned-offer")
    database.record_price(ASSET_ID, Decimal("0.1"), Decimal("0.11"), Decimal("0.105"))

    report = migrate_post_tibet_state(
        asset_id=ASSET_ID,
        authoritative_open_trade_ids={"owned-offer"},
        ownership_proven=True,
        now=NOW,
    )

    assert report["can_start"] is True
    assert report["retained_offer_ids"] == ["owned-offer"]
    assert report["unsafe_offer_ids"] == []
    assert report["legacy_tibet_history_rows"] == 1
    assert report["tibet_live_features"] == "retired"


def test_migration_fails_closed_when_ownership_is_not_proven(isolated_db):
    _add_offer("unproven-offer")

    report = migrate_post_tibet_state(
        asset_id=ASSET_ID,
        authoritative_open_trade_ids=set(),
        ownership_proven=False,
        now=NOW,
    )

    assert report["can_start"] is False
    assert report["reason_code"] == "POST_TIBET_OWNERSHIP_UNPROVEN"
    assert report["unsafe_offer_ids"] == ["unproven-offer"]


def test_migration_is_idempotent_and_does_not_delete_legacy_history(isolated_db):
    database.record_price(ASSET_ID, Decimal("0.1"), Decimal("0.11"), Decimal("0.105"))

    first = migrate_post_tibet_state(
        asset_id=ASSET_ID,
        authoritative_open_trade_ids=set(),
        ownership_proven=True,
        now=NOW,
    )
    second = migrate_post_tibet_state(
        asset_id=ASSET_ID,
        authoritative_open_trade_ids={"later-value-is-ignored"},
        ownership_proven=False,
        now=NOW,
    )

    assert second == first
    assert database.count_legacy_tibet_price_rows(ASSET_ID) == 1
    assert database.get_post_tibet_migration_report(ASSET_ID) == first


def test_bot_start_enforces_migration_from_fresh_sage_offer_snapshot(
    isolated_db, monkeypatch
):
    import api_server  # noqa: F401 - complete blueprint registration first
    import blueprints.bot as bot_blueprint
    import wallet

    _add_offer("owned-offer")
    monkeypatch.setattr(
        wallet,
        "get_all_offers",
        lambda **_kwargs: [{"trade_id": "owned-offer"}],
    )

    report = bot_blueprint._enforce_post_tibet_start_migration(ASSET_ID)

    assert report["can_start"] is True
    assert report["retained_offer_ids"] == ["owned-offer"]
    assert "_enforce_post_tibet_start_migration" in inspect.getsource(
        bot_blueprint.api_bot_start
    )


def test_bot_start_migration_fails_closed_when_sage_offer_read_is_unavailable(
    isolated_db, monkeypatch
):
    import api_server  # noqa: F401 - complete blueprint registration first
    import blueprints.bot as bot_blueprint
    import wallet

    _add_offer("unknown-offer")
    monkeypatch.setattr(wallet, "get_all_offers", lambda **_kwargs: None)

    report = bot_blueprint._enforce_post_tibet_start_migration(ASSET_ID)

    assert report["can_start"] is False
    assert report["reason_code"] == "POST_TIBET_SAGE_OFFERS_UNAVAILABLE"
    assert database.get_post_tibet_migration_report(ASSET_ID) is None


def test_bot_start_retries_failed_migration_after_sage_reconciliation(
    isolated_db, monkeypatch
):
    import api_server  # noqa: F401 - complete blueprint registration first
    import blueprints.bot as bot_blueprint
    import wallet

    _add_offer("reconciled-offer")
    snapshots = iter(
        [
            [],
            [{"trade_id": "reconciled-offer"}],
        ]
    )
    calls = []

    def get_all_offers(**kwargs):
        calls.append(kwargs)
        return next(snapshots)

    monkeypatch.setattr(wallet, "get_all_offers", get_all_offers)

    blocked = bot_blueprint._enforce_post_tibet_start_migration(ASSET_ID)
    recovered = bot_blueprint._enforce_post_tibet_start_migration(ASSET_ID)

    assert blocked["can_start"] is False
    assert blocked["reason_code"] == "POST_TIBET_UNSAFE_OPEN_OFFERS"
    assert recovered["can_start"] is True
    assert recovered["retained_offer_ids"] == ["reconciled-offer"]
    assert len(calls) == 2
    assert database.get_post_tibet_migration_report(ASSET_ID) == recovered
