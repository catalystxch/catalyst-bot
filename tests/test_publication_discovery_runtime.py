from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import database
import pytest
from types import SimpleNamespace


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
AT = NOW.isoformat(timespec="microseconds").replace("+00:00", "Z")
CONFIRMED = (
    (NOW + timedelta(seconds=5))
    .isoformat(timespec="microseconds")
    .replace("+00:00", "Z")
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "discovery.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield database
    database.close_connection()


def _created_intent(db, *, intent_id: str = "intent-1"):
    offer_text = f"offer1exact-{intent_id}"
    offer_identity = _sha(offer_text)
    trade_id = _sha(f"trade:{intent_id}")
    db.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="run:test",
        wallet_fingerprint_hash=_sha("wallet"),
        network="mainnet",
        asset_id=_sha("asset"),
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key=f"slot:{intent_id}",
        generation=1,
        offered_amount_atomic="1000000000000",
        requested_amount_atomic="2000000",
        selected_coin_ids_json=[_sha(f"coin:{intent_id}")],
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"phase": "prepared"},
        prepared_at=AT,
    )
    intent = db.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=offer_identity,
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"phase": "confirmed"},
        finalized_at=CONFIRMED,
    )
    return intent, trade_id, offer_identity


def test_discovery_rows_are_durable_and_exact_evidence_is_idempotent(
    isolated_database,
):
    db = isolated_database
    intent, _trade_id, identity = _created_intent(db)

    first = db.ensure_offer_publication_discoveries(intent["intent_id"])
    replay = db.ensure_offer_publication_discoveries(intent["intent_id"])

    assert {row["provider"] for row in first} == {"dexie", "splash"}
    assert replay == first
    assert all(row["state"] == "pending" for row in first)
    assert all(row["offer_identity"] == identity for row in first)

    exact = db.record_offer_publication_discovery(
        intent["intent_id"],
        provider="dexie",
        observed_offer_identity=identity,
        observed_at=NOW + timedelta(seconds=20),
    )
    duplicate = db.record_offer_publication_discovery(
        intent["intent_id"],
        provider="dexie",
        observed_offer_identity=identity,
        observed_at=NOW + timedelta(seconds=25),
    )

    assert exact["state"] == "exact"
    assert duplicate["state"] == "exact"
    assert duplicate["first_observed_at"] == exact["first_observed_at"]


def test_discovery_deadline_is_durable_and_does_not_release_offer_slot(
    isolated_database,
):
    db = isolated_database
    intent, _trade_id, _identity = _created_intent(db)
    db.ensure_offer_publication_discoveries(intent["intent_id"])

    before = db.expire_offer_publication_discoveries(
        intent["intent_id"], now=NOW + timedelta(seconds=94)
    )
    expired = db.expire_offer_publication_discoveries(
        intent["intent_id"], now=NOW + timedelta(seconds=95)
    )

    assert all(row["state"] == "pending" for row in before)
    assert all(row["state"] == "deadline_expired" for row in expired)
    assert db.get_offer_intent(intent["intent_id"])["lifecycle_state"] == "created"


def test_bot_marks_offer_visible_only_from_exact_public_rediscovery(
    isolated_database, monkeypatch
):
    import bot_loop

    intent, _trade_id, identity = _created_intent(isolated_database)
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop.offer_manager = SimpleNamespace(cancel_offers=lambda *_args, **_kwargs: {})
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", intent["asset_id"], raising=False)
    monkeypatch.setattr(loop, "_enter_runtime_effect_phase", lambda phase: True)

    result = loop._reconcile_offer_publication_discovery(
        dexie_book={
            "bids": [
                {
                    "offer_id": identity,
                    "offer_identity": identity,
                    "trade_id": intent["sage_trade_id"],
                }
            ],
            "asks": [],
        },
        splash_offers=[],
        now=NOW + timedelta(seconds=20),
    )

    stored = isolated_database.get_offer_intent(intent["intent_id"])
    assert result == {"visible": 1, "pending": 0, "cancel_requested": 0}
    assert stored["lifecycle_state"] == "visible"
    assert stored["publication_identity"] == f"dexie:{identity}"


def test_bot_cancels_via_authoritative_manager_after_discovery_deadline(
    isolated_database, monkeypatch
):
    import bot_loop

    intent, trade_id, _identity = _created_intent(isolated_database)
    cancelled = []
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop.offer_manager = SimpleNamespace(
        cancel_offers=lambda ids, **kwargs: cancelled.extend(ids) or {}
    )
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", intent["asset_id"], raising=False)
    monkeypatch.setattr(
        loop, "_enter_runtime_effect_phase", lambda phase: phase == "cancel"
    )

    result = loop._reconcile_offer_publication_discovery(
        dexie_book={"bids": [], "asks": []},
        splash_offers=[],
        now=NOW + timedelta(seconds=95),
    )

    assert result == {"visible": 0, "pending": 0, "cancel_requested": 1}
    assert cancelled == [trade_id]
    assert (
        isolated_database.get_offer_intent(intent["intent_id"])["lifecycle_state"]
        == "created"
    )
