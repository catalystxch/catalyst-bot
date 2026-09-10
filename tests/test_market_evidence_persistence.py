from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import database
import pytest
from market_evidence import (
    MarketConfidenceSnapshot,
    persist_confidence_snapshot,
    persist_provider_observation,
)
from providers.models import (
    Capability,
    ObservationQuality,
    ProviderObservation,
    canonical_evidence_json,
    evidence_digest,
)


ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "market.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def _provider_observation(observed_at=NOW):
    raw = canonical_evidence_json({"asset_id": ASSET_ID, "bids": [], "asks": []})
    return ProviderObservation(
        provider_id="dexie",
        capability=Capability.ORDER_BOOK,
        observed_at=observed_at,
        source_time=None,
        source_height=None,
        fresh_until=observed_at + timedelta(seconds=20),
        identity_keys=(ASSET_ID,),
        payload_sha256=evidence_digest(raw),
        quality=ObservationQuality.DEGRADED,
        reason_codes=("empty_book",),
        raw_evidence_json=raw,
    )


def test_provider_observation_round_trip_is_idempotent(isolated_db):
    observation = _provider_observation()

    first_id = persist_provider_observation(observation)
    second_id = persist_provider_observation(observation)

    assert first_id == second_id
    rows = database.get_market_provider_observations(asset_id=ASSET_ID, limit=10)
    assert len(rows) == 1
    assert rows[0]["provider_id"] == "dexie"
    assert rows[0]["payload_sha256"] == observation.payload_sha256
    assert rows[0]["reason_codes"] == ["empty_book"]


def test_confidence_snapshot_survives_connection_restart(isolated_db):
    snapshot = MarketConfidenceSnapshot(
        asset_id=ASSET_ID,
        state="RED",
        derived_at=NOW,
        trusted_midpoint=Decimal("0.125"),
        trusted_bid=Decimal("0.12"),
        trusted_ask=Decimal("0.13"),
        degraded_since=NOW - timedelta(minutes=4),
        withdrawal_stage="MIDDLE",
        recovery_refreshes=0,
        reason_codes=("one_sided_book",),
        source_health={"dexie": "degraded", "splash": "valid"},
        evidence_digests=("ab" * 32,),
    )

    snapshot_id = persist_confidence_snapshot(snapshot)
    database.close_connection()
    restored = database.get_latest_market_confidence_snapshot(ASSET_ID)

    assert restored["snapshot_id"] == snapshot_id
    assert restored["state"] == "RED"
    assert restored["trusted_midpoint"] == "0.125"
    assert restored["degraded_since"] == "2026-09-10T11:56:00.000000Z"
    assert restored["source_health"] == {"dexie": "degraded", "splash": "valid"}


def test_evidence_compaction_keeps_daily_non_sensitive_summary(isolated_db):
    old = NOW - timedelta(days=31)
    persist_provider_observation(_provider_observation(old))

    result = database.compact_market_provider_evidence(
        before=NOW - timedelta(days=30), summarized_at=NOW
    )

    assert result == {"deleted": 1, "summaries_written": 1}
    assert database.get_market_provider_observations(asset_id=ASSET_ID, limit=10) == []
    summaries = database.get_market_evidence_summaries(asset_id=ASSET_ID, limit=10)
    assert summaries[0]["observation_count"] == 1
    assert summaries[0]["provider_id"] == "dexie"
    assert "raw_evidence" not in summaries[0]


def test_bot_housekeeping_compacts_provider_evidence_after_thirty_days(monkeypatch):
    from bot_loop import BotLoop

    calls = []
    monkeypatch.setattr(
        database,
        "compact_market_provider_evidence",
        lambda **kwargs: calls.append(kwargs) or {
            "deleted": 0,
            "summaries_written": 0,
        },
    )

    result = BotLoop._compact_market_evidence(now=NOW)

    assert result == {"deleted": 0, "summaries_written": 0}
    assert calls == [{"before": NOW - timedelta(days=30), "summarized_at": NOW}]


def test_guarded_price_reset_clears_derived_market_evidence_but_preserves_migration(
    isolated_db,
):
    persist_provider_observation(_provider_observation())
    persist_confidence_snapshot(
        MarketConfidenceSnapshot(
            asset_id=ASSET_ID,
            state="AMBER",
            derived_at=NOW,
            trusted_midpoint=Decimal("0.125"),
            trusted_bid=Decimal("0.12"),
            trusted_ask=Decimal("0.13"),
            degraded_since=None,
            withdrawal_stage="NONE",
            recovery_refreshes=0,
            reason_codes=("single_provider_dependency",),
            source_health={"dexie": "valid", "splash": "unavailable"},
            evidence_digests=("ab" * 32,),
        )
    )
    database.store_post_tibet_migration_report(
        ASSET_ID,
        {"migration_version": 1, "can_start": True},
        NOW,
    )

    result = database.guarded_reset_authoritative_state(clear_price_history=True)

    assert result["success"] is True
    assert result["market_evidence_cleared"] == {
        "provider_observations": 1,
        "confidence_snapshots": 1,
        "summaries": 0,
    }
    assert database.get_market_provider_observations(ASSET_ID, limit=10) == []
    assert database.get_latest_market_confidence_snapshot(ASSET_ID) is None
    assert database.get_post_tibet_migration_report(ASSET_ID)["can_start"] is True
