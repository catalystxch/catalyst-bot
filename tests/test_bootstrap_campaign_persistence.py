from datetime import datetime, timedelta, timezone
from decimal import Decimal

import database
import pytest
from bootstrap_campaign import BootstrapCampaign


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ASSET_ID = "cd" * 32


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bootstrap.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def make_campaign(**overrides):
    values = {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 736588221,
        "wallet_id": 2,
        "asset_id": ASSET_ID,
        "anchor_price": Decimal("0.0100"),
        "minimum_price": Decimal("0.0050"),
        "maximum_price": Decimal("0.0200"),
        "xch_budget": Decimal("1.2500"),
        "cat_budget": Decimal("125.000"),
        "fee_budget_xch": Decimal("0.0500"),
        "subsidy_budget_xch": Decimal("0.000"),
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=7),
    }
    values.update(overrides)
    return BootstrapCampaign(**values)


def test_bootstrap_campaign_round_trip_preserves_canonical_decimal_strings(
    isolated_db,
):
    campaign_id = database.create_bootstrap_campaign(make_campaign().to_record())

    restored = database.get_bootstrap_campaign(campaign_id)

    assert len(campaign_id) == 64
    assert restored["campaign_id"] == campaign_id
    assert restored["anchor_price"] == "0.01"
    assert restored["minimum_price"] == "0.005"
    assert restored["maximum_price"] == "0.02"
    assert restored["xch_budget"] == "1.25"
    assert restored["cat_budget"] == "125"
    assert restored["fee_budget_xch"] == "0.05"
    assert restored["subsidy_budget_xch"] == "0"
    assert restored["status"] == "active"
    assert restored["revision"] == 0


def test_second_schema_initialization_is_idempotent(isolated_db):
    database._db_initialized_path = ""
    database.init_database()
    database._db_initialized_path = ""
    database.init_database()

    campaign_id = database.create_bootstrap_campaign(make_campaign().to_record())

    assert database.get_bootstrap_campaign(campaign_id) is not None


def test_v13_stability_watermark_allows_first_bootstrap_schema_install(isolated_db):
    """A pre-Bootstrap profile must not treat new v1.4 tables as corruption."""

    conn = database.get_connection()
    for table_name in (
        "bootstrap_participation",
        "bootstrap_campaign_events",
        "bootstrap_campaigns",
    ):
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
    assert {
        "bootstrap_campaigns",
        "bootstrap_campaign_events",
        "bootstrap_participation",
    } <= tables


def test_only_one_active_campaign_exists_per_wallet_network_and_asset(isolated_db):
    first_id = database.create_bootstrap_campaign(make_campaign().to_record())

    with pytest.raises(ValueError, match="active Bootstrap campaign"):
        database.create_bootstrap_campaign(
            make_campaign(
                anchor_price=Decimal("0.011"),
                created_at=NOW + timedelta(minutes=1),
                expires_at=NOW + timedelta(days=7),
            ).to_record()
        )

    assert database.stop_bootstrap_campaign(
        first_id,
        "manual",
        NOW + timedelta(minutes=2),
    )
    second_id = database.create_bootstrap_campaign(
        make_campaign(
            anchor_price=Decimal("0.011"),
            created_at=NOW + timedelta(minutes=3),
            expires_at=NOW + timedelta(days=7),
        ).to_record()
    )
    assert second_id != first_id


def test_identical_create_retry_returns_the_original_campaign(isolated_db):
    record = make_campaign().to_record()

    first_id = database.create_bootstrap_campaign(record)
    second_id = database.create_bootstrap_campaign(record)

    assert second_id == first_id


def test_restart_preserves_stage_cooldown_fee_and_loss_state(isolated_db):
    campaign_id = database.create_bootstrap_campaign(make_campaign().to_record())
    new_revision = database.update_bootstrap_campaign_state(
        campaign_id,
        expected_revision=0,
        record={
            "stage": "discovery_50",
            "deployment_fraction": "0.5",
            "current_anchor_price": "0.0105",
            "stable_since": NOW - timedelta(minutes=30),
            "confirmed_fills": 6,
            "settlement_clusters": 3,
            "independent_depth_sides": ["buy", "sell"],
            "suspected_linked_activity": False,
            "adverse_fill_times": [
                {"side": "sell", "occurred_at": NOW - timedelta(minutes=2)}
            ],
            "fee_spent_xch": "0.004",
            "realized_loss_xch": "0.002",
            "marked_inventory_loss_xch": "0.003",
            "updated_at": NOW,
        },
    )
    database.close_connection()

    restored = database.get_bootstrap_campaign(campaign_id)

    assert new_revision == 1
    assert restored["stage"] == "discovery_50"
    assert restored["deployment_fraction"] == "0.5"
    assert restored["current_anchor_price"] == "0.0105"
    assert restored["confirmed_fills"] == 6
    assert restored["settlement_clusters"] == 3
    assert restored["independent_depth_sides"] == ["buy", "sell"]
    assert restored["adverse_fill_times"] == [
        {"occurred_at": "2026-09-12T11:58:00.000000Z", "side": "sell"}
    ]
    assert restored["fee_spent_xch"] == "0.004"
    assert restored["realized_loss_xch"] == "0.002"
    assert restored["marked_inventory_loss_xch"] == "0.003"


def test_state_update_compare_and_set_rejects_stale_revision(isolated_db):
    campaign_id = database.create_bootstrap_campaign(make_campaign().to_record())
    state = {
        "stage": "bootstrap",
        "deployment_fraction": "0.1",
        "current_anchor_price": "0.01",
        "stable_since": None,
        "confirmed_fills": 0,
        "settlement_clusters": 0,
        "independent_depth_sides": [],
        "suspected_linked_activity": False,
        "adverse_fill_times": [],
        "fee_spent_xch": "0",
        "realized_loss_xch": "0",
        "marked_inventory_loss_xch": "0",
        "updated_at": NOW,
    }
    assert (
        database.update_bootstrap_campaign_state(
            campaign_id,
            expected_revision=0,
            record=state,
        )
        == 1
    )

    with pytest.raises(RuntimeError, match="compare-and-set"):
        database.update_bootstrap_campaign_state(
            campaign_id,
            expected_revision=0,
            record=state,
        )


def test_campaign_event_append_is_idempotent_and_ordered(isolated_db):
    campaign_id = database.create_bootstrap_campaign(make_campaign().to_record())
    event = {
        "campaign_id": campaign_id,
        "event_type": "stage_changed",
        "occurred_at": NOW,
        "data": {"from": "bootstrap", "to": "discovery_25"},
    }

    first_id = database.append_bootstrap_campaign_event(event)
    second_id = database.append_bootstrap_campaign_event(event)

    assert second_id == first_id
    assert database.list_bootstrap_campaign_events(campaign_id) == [
        {
            "event_id": first_id,
            "campaign_id": campaign_id,
            "event_type": "stage_changed",
            "occurred_at": "2026-09-12T12:00:00.000000Z",
            "data": {"from": "bootstrap", "to": "discovery_25"},
        }
    ]


def test_participation_record_is_idempotent_and_survives_restart(isolated_db):
    campaign_id = database.create_bootstrap_campaign(make_campaign().to_record())
    record = {
        "campaign_id": campaign_id,
        "report_id": "ef" * 32,
        "recorded_at": NOW,
        "data": {"eligible_offer_ids": ["offer-1"], "uptime_seconds": 60},
    }

    first_id = database.record_bootstrap_participation(record)
    second_id = database.record_bootstrap_participation(record)
    database.close_connection()

    assert second_id == first_id
    assert database.list_bootstrap_participation(campaign_id) == [
        {
            "participation_id": first_id,
            "campaign_id": campaign_id,
            "report_id": "ef" * 32,
            "recorded_at": "2026-09-12T12:00:00.000000Z",
            "data": {"eligible_offer_ids": ["offer-1"], "uptime_seconds": 60},
        }
    ]
