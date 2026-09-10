from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import database
import pytest
from market_evidence import migrate_post_tibet_state


ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


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
