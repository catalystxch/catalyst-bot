"""Systemic one-authority tests for Task 9 offer terminality and reset safety."""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import api_server
import bot_loop
import boost_manager
import database
import offer_manager
import offer_reconciliation
import shape_fix_orchestrator
import sniper
from cancel_outcomes import CANCEL_CONFIRMED, cancellation_result


AT = "2026-08-20T12:00:00.000000Z"
AFTER = "2026-08-20T12:00:02.000000Z"
WALLET = "f" * 64
ASSET = "a" * 64
TRADE = "b" * 64
COIN = "1" * 64
OTHER_COIN = "2" * 64
OFFER_HASH = "d" * 64
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "catalyst"


@pytest.fixture(autouse=True)
def _socket_guard(monkeypatch):
    attempts: list[str] = []

    def blocked(*_args, **_kwargs):
        attempts.append("socket")
        raise AssertionError("Task 9 tests forbid network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "authority.db"))
    database._db_initialized_path = ""
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: AT)
    database.init_database()
    yield tmp_path / "authority.db"
    database.close_connection()


def _seed_created_intent(
    *,
    intent_id: str = "intent-authority",
    run_id: str = "run-old",
    slot_key: str = "ladder:buy:0",
    generation: int = 0,
    trade_id: str = TRADE,
    coin_id: str = COIN,
    expires_at: str | None = None,
    tier: str = "inner",
) -> dict:
    assert database.upsert_coin(
        coin_id,
        "xch",
        1000,
        designation="tier_spare",
        tier=tier,
        purpose="lifecycle",
    )
    prepared = database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id=run_id,
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        asset_id=ASSET,
        side="buy",
        tier=tier,
        purpose="normal_lifecycle",
        slot_key=slot_key,
        generation=generation,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[coin_id],
        wallet_identity_json={"wallet_fingerprint_hash": WALLET, "network": "mainnet"},
        evidence_json={"source": "authority-policy-test"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    created = database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=OFFER_HASH,
        wallet_identity_json={"wallet_fingerprint_hash": WALLET, "network": "mainnet"},
        evidence_json={"effect_attempted": True},
        finalized_at=AFTER,
        finalize_selected_coin_reservations=True,
    )
    assert database.add_offer(
        trade_id,
        "buy",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET,
        tier=tier,
        expires_at=expires_at,
        coin_id=database.norm_coin_id(coin_id),
    )
    assert prepared["intent_id"] == created["intent_id"]
    return created


def _seed_registry_only_intent(*, lifecycle_state: str) -> tuple[str, str, str]:
    """Persist one Task 4 reservation without creating a legacy offer row."""

    intent_id = f"intent-registry-only-{lifecycle_state}"
    coin_id = hashlib.sha256(f"coin:{lifecycle_state}".encode()).hexdigest()
    assert database.upsert_coin(coin_id, "xch", 1000, tier="inner", purpose="lifecycle")
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="run-registry-only",
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        asset_id=ASSET,
        side="buy",
        tier="inner",
        purpose="authority_crash_recovery",
        slot_key=f"slot:{intent_id}",
        generation=0,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[coin_id],
        wallet_identity_json={"wallet_fingerprint_hash": WALLET, "network": "mainnet"},
        evidence_json={"source": "registry-only-authority-test"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    mutation_identity = f"intent:{intent_id}"
    if lifecycle_state != "prepared":
        outcome = {
            "submitted_unconfirmed": "SUBMITTED_UNCONFIRMED",
            "creation_unknown": "UNKNOWN",
            "created": "CONFIRMED",
        }[lifecycle_state]
        is_created = lifecycle_state == "created"
        database.finalize_offer_intent(
            intent_id=intent_id,
            operation_id=f"create:{intent_id}",
            event_id=f"create:{intent_id}:finalized",
            lifecycle_state=lifecycle_state,
            outcome=outcome,
            sage_trade_id=TRADE if is_created else None,
            offer_text_sha256=OFFER_HASH if is_created else None,
            wallet_identity_json={
                "wallet_fingerprint_hash": WALLET,
                "network": "mainnet",
            },
            evidence_json={"source": "registry-only-finalization-test"},
            reason_code=None if is_created else f"{outcome}_TEST",
            finalized_at=AFTER,
            finalize_selected_coin_reservations=True,
        )
        if is_created:
            mutation_identity = TRADE
    return intent_id, coin_id, mutation_identity


def _assert_created_offer_is_protected() -> None:
    offer = database.get_offer(TRADE)
    coin = database.get_coin_state(COIN)
    intent = database.get_offer_intent("intent-authority")
    assert offer["status"] == "open"
    assert offer["lifecycle_state"] == "open"
    assert coin["status"] == "locked"
    assert coin["trade_id"] == TRADE
    assert intent["lifecycle_state"] == "created"


def test_default_open_view_retains_elapsed_and_all_pending_safety_rows(
    isolated_database,
):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _seed_created_intent(expires_at=past)
    assert database.add_offer(
        "pending-cancel",
        "sell",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET,
    )
    assert database.add_offer(
        "pending-fill",
        "sell",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET,
    )
    assert database.update_offer_lifecycle_state("pending-cancel", "cancel_requested")
    assert database.update_offer_lifecycle_state("pending-fill", "mempool_observed")

    ids = {row["trade_id"] for row in database.get_open_offers(cat_asset_id=ASSET)}

    assert ids == {TRADE, "pending-cancel", "pending-fill"}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda: database.update_offer_status(TRADE, "filled"),
        lambda: database.update_offer_status(TRADE, "cancelled"),
        lambda: database.update_offer_status(TRADE, "expired"),
        lambda: database.batch_cancel_stale_offers([TRADE]),
        lambda: database.expire_elapsed_open_offers(
            cat_asset_id=ASSET, now=datetime.now(timezone.utc)
        ),
        lambda: database.expire_open_offers_by_time(
            cat_asset_id=ASSET, now_ts=datetime.now(timezone.utc).timestamp()
        ),
        lambda: database.free_coin(COIN),
        lambda: database.mark_coin_spent(COIN),
    ],
)
def test_legacy_terminal_and_release_apis_cannot_mutate_created_intent(
    isolated_database,
    mutation,
):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    _seed_created_intent(expires_at=past)

    result = mutation()

    assert result is False or result == 0 or result == [] or result == ()
    _assert_created_offer_is_protected()


def test_legacy_record_fill_cannot_terminalize_registered_open_offer(
    isolated_database,
):
    _seed_created_intent()

    fill_id = database.record_fill(
        TRADE,
        "buy",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET,
    )

    assert fill_id == -1
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    _assert_created_offer_is_protected()


@pytest.mark.parametrize(
    "lifecycle_state",
    ["prepared", "submitted_unconfirmed", "creation_unknown", "created"],
)
def test_registry_only_identity_fences_every_legacy_terminal_path(
    isolated_database,
    lifecycle_state,
):
    intent_id, coin_id, mutation_identity = _seed_registry_only_intent(
        lifecycle_state=lifecycle_state
    )
    before_intent = database.get_offer_intent(intent_id)
    before_coin = database.get_coin_state(coin_id)

    assert database.update_offer_status(mutation_identity, "filled") is False
    assert (
        database.update_offer_lifecycle_state(mutation_identity, "user_cancelled")
        is False
    )
    assert database.batch_cancel_stale_offers([mutation_identity]) == 0
    assert (
        database.record_fill(
            mutation_identity,
            "buy",
            Decimal("0.001"),
            Decimal("1"),
            Decimal("1000"),
            ASSET,
        )
        == -1
    )

    assert database.get_offer(mutation_identity) is None
    assert database.get_offer_intent(intent_id) == before_intent
    assert database.get_coin_state(coin_id) == before_coin
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []


def test_legacy_terminal_fsm_signal_reports_no_transition_without_proof(
    isolated_database,
):
    _seed_created_intent()

    transition = database.transition_offer(TRADE, "fill_detected")

    assert transition is None
    _assert_created_offer_is_protected()


def test_blocked_record_fill_does_not_commit_a_caller_owned_transaction(
    isolated_database,
):
    _seed_created_intent()
    conn = database.get_connection()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO bot_settings (key, value, updated_at) VALUES ('tx-probe', '1', ?)",
        (AT,),
    )

    fill_id = database.record_fill(
        TRADE,
        "buy",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET,
    )

    assert fill_id == -1
    assert conn.in_transaction is True
    conn.rollback()
    assert (
        conn.execute("SELECT 1 FROM bot_settings WHERE key='tx-probe'").fetchone()
        is None
    )


def test_unregistered_open_offer_rejects_legacy_fill_in_caller_transaction(
    isolated_database,
):
    assert database.add_offer(
        "legacy-unregistered",
        "buy",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET,
    )
    conn = database.get_connection()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO bot_settings (key, value, updated_at) VALUES ('tx-probe', '1', ?)",
        (AT,),
    )

    fill_id = database.record_fill(
        "legacy-unregistered",
        "buy",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET,
    )

    assert fill_id == -1
    assert conn.in_transaction is True
    assert conn.execute("SELECT 1 FROM fills").fetchone() is None
    conn.rollback()
    assert (
        conn.execute("SELECT 1 FROM bot_settings WHERE key='tx-probe'").fetchone()
        is None
    )
    assert (
        conn.execute("SELECT 1 FROM fills WHERE fill_id=?", (fill_id,)).fetchone()
        is None
    )
    assert database.get_offer("legacy-unregistered")["status"] == "open"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda: database.update_offer_status("legacy-unregistered", "filled"),
        lambda: database.update_offer_status("legacy-unregistered", "cancelled"),
        lambda: database.update_offer_status("legacy-unregistered", "expired"),
        lambda: database.update_offer_lifecycle_state(
            "legacy-unregistered", "user_cancelled"
        ),
        lambda: database.batch_cancel_stale_offers(["legacy-unregistered"]),
        lambda: database.expire_elapsed_open_offers(
            cat_asset_id=ASSET, now=datetime.now(timezone.utc)
        ),
        lambda: database.expire_open_offers_by_time(
            cat_asset_id=ASSET, now_ts=datetime.now(timezone.utc).timestamp()
        ),
    ],
)
def test_unregistered_open_offer_rejects_every_legacy_terminal_api(
    isolated_database,
    mutation,
):
    assert database.add_offer(
        "legacy-unregistered",
        "buy",
        Decimal("0.001"),
        Decimal("1"),
        Decimal("1000"),
        ASSET,
        expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )

    result = mutation()

    assert result is False or result == 0 or result == []
    offer = database.get_offer("legacy-unregistered")
    assert offer["status"] == "open"
    assert offer["lifecycle_state"] == "open"


def test_cross_run_generation_selection_blocks_an_old_active_slot(
    isolated_database,
):
    _seed_created_intent(run_id="run-old", slot_key="ladder:buy:7", generation=4)
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="run-new",
        owner_pid=12345,
        owner_host="test-host",
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        lease_expires_at="2099-08-20T12:05:00Z",
        now=AT,
    )
    assert acquired["acquired"] is True

    selected = database.select_offer_creation_generation(slot_key="ladder:buy:7")

    assert selected == {
        "run_id": "run-new",
        "generation": 4,
        "active_intent_id": "intent-authority",
        "active_lifecycle_state": "created",
    }


@pytest.mark.parametrize("blocking_state", ["unknown", "conflicted"])
def test_cross_run_generation_selection_retains_reconciliation_blocker(
    isolated_database,
    blocking_state,
):
    _seed_created_intent(run_id="run-old", slot_key="ladder:buy:7", generation=4)
    conn = database.get_connection()
    conn.execute(
        "UPDATE offer_intents SET lifecycle_state=? WHERE intent_id='intent-authority'",
        (blocking_state,),
    )
    conn.commit()
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="run-new",
        owner_pid=12345,
        owner_host="test-host",
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        lease_expires_at="2099-08-20T12:05:00Z",
        now=AT,
    )
    assert acquired["acquired"] is True

    selected = database.select_offer_creation_generation(slot_key="ladder:buy:7")

    assert selected == {
        "run_id": "run-new",
        "generation": 4,
        "active_intent_id": "intent-authority",
        "active_lifecycle_state": blocking_state,
    }


@pytest.mark.parametrize("blocking_state", ["unknown", "conflicted"])
def test_direct_prepare_cannot_bypass_reconciliation_blocked_slot(
    isolated_database,
    blocking_state,
):
    _seed_created_intent(run_id="run-old", slot_key="ladder:buy:7", generation=4)
    assert database.upsert_coin(
        OTHER_COIN,
        "xch",
        1000,
        designation="tier_spare",
        tier="inner",
        purpose="lifecycle",
    )
    conn = database.get_connection()
    conn.execute(
        "UPDATE offer_intents SET lifecycle_state=? WHERE intent_id='intent-authority'",
        (blocking_state,),
    )
    conn.commit()

    with pytest.raises(
        sqlite3.IntegrityError, match="UNIQUE constraint failed: offer_intents.slot_key"
    ):
        database.prepare_offer_intent(
            intent_id="intent-second",
            operation_id="create:intent-second",
            event_id="create:intent-second:prepared",
            run_id="run-new",
            wallet_fingerprint_hash=WALLET,
            network="mainnet",
            asset_id=ASSET,
            side="buy",
            tier="inner",
            purpose="normal_lifecycle",
            slot_key="ladder:buy:7",
            generation=4,
            offered_amount_atomic="1000",
            requested_amount_atomic="2000",
            selected_coin_ids_json=[OTHER_COIN],
            wallet_identity_json={"wallet_fingerprint_hash": WALLET},
            evidence_json={"source": "blocked-slot-bypass"},
            prepared_at=AFTER,
            reserve_selected_coins=True,
            require_new_intent=True,
        )
    assert database.get_offer_intent("intent-second") is None


def test_active_slot_unique_index_covers_every_reconciliation_blocker(
    isolated_database,
):
    row = (
        database.get_connection()
        .execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='uniq_offer_intents_active_slot_generation'"
        )
        .fetchone()
    )
    normalized = "".join(str(row["sql"]).lower().split())
    assert "'unknown'" in normalized
    assert "'conflicted'" in normalized


def test_cross_run_generation_advances_after_authoritative_terminal_state(
    isolated_database,
):
    _seed_created_intent(run_id="run-old", slot_key="ladder:buy:7", generation=4)
    conn = database.get_connection()
    conn.execute(
        "UPDATE offer_intents SET lifecycle_state='terminal' "
        "WHERE intent_id='intent-authority'"
    )
    conn.commit()
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="run-new",
        owner_pid=12345,
        owner_host="test-host",
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        lease_expires_at="2099-08-20T12:05:00Z",
        now=AT,
    )
    assert acquired["acquired"] is True

    selected = database.select_offer_creation_generation(slot_key="ladder:buy:7")

    assert selected == {
        "run_id": "run-new",
        "generation": 5,
        "active_intent_id": None,
        "active_lifecycle_state": None,
    }


def _clone_nonterminal_intents(conn, count: int) -> None:
    start = int(
        conn.execute(
            "SELECT COUNT(*) FROM offer_intents WHERE intent_id LIKE 'bulk-intent-%'"
        ).fetchone()[0]
    )
    conn.executemany(
        """
        INSERT INTO offer_intents (
            intent_id, run_id, wallet_fingerprint_hash, network, asset_id,
            side, tier, purpose, slot_key, generation, parent_intent_id,
            child_intent_id, offered_amount_atomic, requested_amount_atomic,
            selected_coin_ids_json, selected_coin_ids_sha256,
            offer_text_sha256, sage_trade_id, publication_identity,
            lifecycle_state, row_version, prepared_at, submitted_at,
            confirmed_at, first_visible_at, terminal_at, updated_at
        )
        SELECT ?, run_id, wallet_fingerprint_hash, network, asset_id,
               side, tier, purpose, NULL, generation, NULL, NULL,
               offered_amount_atomic, requested_amount_atomic,
               selected_coin_ids_json, selected_coin_ids_sha256,
               NULL, NULL, NULL, 'created', 0, prepared_at, NULL,
               NULL, NULL, NULL, updated_at
          FROM offer_intents WHERE intent_id='intent-authority'
        """,
        ((f"bulk-intent-{index}",) for index in range(start, start + count)),
    )
    conn.commit()


def test_nonterminal_reservation_scan_has_exact_row_cap(isolated_database):
    _seed_created_intent()
    conn = database.get_connection()
    _clone_nonterminal_intents(conn, 4095)

    assert database.get_free_coins("xch") == []

    _clone_nonterminal_intents(conn, 1)
    with pytest.raises(RuntimeError, match="nonterminal intent reservation limit"):
        database.get_free_coins("xch")


def test_nonterminal_reservation_rejects_oversize_json_before_parsing(
    isolated_database,
    monkeypatch,
):
    _seed_created_intent()
    conn = database.get_connection()
    conn.execute(
        "UPDATE offer_intents SET selected_coin_ids_json=? "
        "WHERE intent_id='intent-authority'",
        ("[" + " " * (database._MAX_STABILITY_JSON_INPUT_CHARS + 1) + "]",),
    )
    conn.commit()
    loads = MagicMock(side_effect=AssertionError("oversize JSON was parsed"))
    monkeypatch.setattr(database.json, "loads", loads)

    with pytest.raises(RuntimeError, match="selected coin JSON exceeds hard limit"):
        database.get_free_coins("xch")

    loads.assert_not_called()


def test_reservation_mutators_do_not_delegate_unbounded_sql_json_traversal():
    for function in (
        database.mark_coins_gone,
        database.free_unreserved_locked_coin_for_reconciliation,
        database.reconcile_wallet_locked_coin_links,
        database.reconcile_coins_with_wallet,
        database.cleanup_orphaned_locked_coins,
    ):
        assert "_nonterminal_registry_coin_absent_sql" not in inspect.getsource(
            function
        )


def test_generation_selector_uses_bounded_indexed_queries():
    source = inspect.getsource(database.select_offer_creation_generation)
    assert "        rows = conn.execute" not in source
    assert source.count("LIMIT 1") >= 2


def test_corrupt_free_coin_row_cannot_bypass_nonterminal_intent_reservation(
    isolated_database,
):
    _seed_created_intent()
    conn = database.get_connection()
    conn.execute(
        "UPDATE coins SET status='free', trade_id=NULL WHERE coin_id=?",
        (database.norm_coin_id(COIN),),
    )
    conn.commit()

    assert COIN not in {
        str(row["coin_id"]).removeprefix("0x") for row in database.get_free_coins("xch")
    }
    assert database.lock_coin(COIN, "different-trade") is False
    with pytest.raises(ValueError, match="nonterminal|reserved|free"):
        database.prepare_offer_intent(
            intent_id="intent-second",
            operation_id="create:intent-second",
            event_id="create:intent-second:prepared",
            run_id="run-new",
            wallet_fingerprint_hash=WALLET,
            network="mainnet",
            asset_id=ASSET,
            side="buy",
            tier="inner",
            purpose="normal_lifecycle",
            slot_key="ladder:buy:99",
            generation=0,
            offered_amount_atomic="1000",
            requested_amount_atomic="2000",
            selected_coin_ids_json=[COIN],
            wallet_identity_json={"wallet_fingerprint_hash": WALLET},
            evidence_json={"source": "second-intent"},
            prepared_at=AFTER,
            reserve_selected_coins=True,
            require_new_intent=True,
        )
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_offer_intent("intent-authority")["lifecycle_state"] == "created"
    coin = database.get_coin_state(COIN)
    assert coin["status"] == "free"
    assert coin["trade_id"] is None


def test_coin_prep_cleanup_preserves_corrupt_free_registry_reservation(
    isolated_database,
):
    _seed_created_intent()
    assert database.upsert_coin(OTHER_COIN, "xch", 2000)
    conn = database.get_connection()
    conn.execute(
        "UPDATE coins SET status='free', trade_id=NULL WHERE coin_id=?",
        (database.norm_coin_id(COIN),),
    )
    conn.commit()

    changed = database.mark_unreserved_free_coins_gone_for_preparation()

    assert changed == 1
    assert database.get_coin_state(COIN)["status"] == "free"
    assert database.get_coin_state(OTHER_COIN)["status"] == "gone"


def test_replenishment_does_not_open_a_slot_from_wallet_omission(monkeypatch):
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(offer_manager.cfg, "TIER_ENABLED", True)
    tier = manager._classify_tier(0, 1, side="buy")
    monkeypatch.setattr(
        offer_manager,
        "get_open_offers",
        lambda **_kwargs: [{"trade_id": TRADE, "tier": tier}],
    )

    slots = manager.get_replenishment_slots(
        "buy", 1, cat_asset_id=ASSET, live_offer_ids=set()
    )

    assert slots == []


def test_requote_does_not_cold_rebuild_over_wallet_omitted_db_offer(
    isolated_database, monkeypatch
):
    acquired = database.acquire_runtime_mutation_lease(
        owner_run_id="run-requote-authority",
        owner_pid=12345,
        owner_host="test-host",
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        lease_expires_at="2099-08-20T12:05:00Z",
        now=AT,
    )
    assert acquired["acquired"] is True
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(offer_manager.cfg, "CAT_ASSET_ID", ASSET)
    monkeypatch.setattr(
        offer_manager,
        "get_open_offers",
        lambda **_kwargs: [
            {
                "trade_id": TRADE,
                "tier": "inner",
                "price_xch": "0.001",
                "created_at": AT,
            }
        ],
    )
    create_ladder = MagicMock(return_value=[{"trade_id": "replacement"}])
    monkeypatch.setattr(manager, "create_ladder", create_ladder)

    result = manager.requote_side(
        "buy",
        Decimal("0.002"),
        live_offer_ids=set(),
        force_cancel_storm=True,
    )

    assert result["offers"] == []
    assert result["replaced_count"] == 0
    create_ladder.assert_not_called()


def test_shape_fix_requires_proof_for_every_cancelled_member(monkeypatch):
    fake_database = SimpleNamespace(
        get_open_offers=lambda **_kwargs: [],
        get_authoritative_terminal_record=lambda trade_id: (
            {"terminal_state": "cancelled"} if trade_id == TRADE else None
        ),
    )
    monkeypatch.setitem(sys.modules, "database", fake_database)
    clock = {"value": 0.0}

    def advancing_clock():
        clock["value"] += 0.6
        return clock["value"]

    monkeypatch.setattr(shape_fix_orchestrator.time, "time", advancing_clock)
    monkeypatch.setattr(shape_fix_orchestrator.time, "sleep", lambda _seconds: None)
    orchestrator = shape_fix_orchestrator.ShapeFixOrchestrator(
        SimpleNamespace(), SimpleNamespace(emit=lambda *_args, **_kwargs: None)
    )
    orchestrator.CONFIRMATION_TIMEOUT_S = 1.0
    orchestrator.CONFIRMATION_POLL_INTERVAL_S = 0.0
    flow = shape_fix_orchestrator.FlowState(
        flow_id="shape-authority",
        side="buy",
        trade_ids=[TRADE, "c" * 64],
        total_requested=2,
    )

    orchestrator._stage_waiting_for_confirmation(flow)

    assert flow.halt_reason is shape_fix_orchestrator.HaltReason.TIMEOUT_CONFIRMATION
    assert shape_fix_orchestrator.Stage.WAITING_FOR_CONFIRMATION not in (
        flow.stages_completed
    )


def _bare_boost_manager() -> boost_manager.BoostManager:
    manager = object.__new__(boost_manager.BoostManager)
    manager._lock = threading.RLock()
    manager._active_boost_ids = [TRADE]
    manager._offer_manager = SimpleNamespace(_bot_cancelled_ids=set())
    manager._boost_id_expiry = {}
    manager._buy_probe_tid = TRADE
    manager._sell_probe_tid = ""
    manager._buy_probe_tid_history = {TRADE}
    manager._sell_probe_tid_history = set()
    manager._arb_count = 0
    manager._on_inverted_arb = MagicMock()
    return manager


def test_boost_and_sniper_prune_retain_wallet_absent_unproven_offers(monkeypatch):
    monkeypatch.setattr(
        database, "get_authoritative_terminal_record", lambda _tid: None
    )
    manager = _bare_boost_manager()
    snipe = sniper.Sniper()
    snipe._active_snipe_ids = [TRADE]
    snipe._active_snipe_sides = {TRADE: "buy"}

    manager.prune_active_boosts(set())
    snipe.prune_active_snipes(set())

    assert manager._active_boost_ids == [TRADE]
    manager._on_inverted_arb.assert_not_called()
    assert snipe._active_snipe_ids == [TRADE]
    assert snipe._active_snipe_sides == {TRADE: "buy"}


def test_boost_deactivate_retains_unproven_cancel_submission(isolated_database):
    class SubmittedCancelManager:
        def __init__(self):
            self._bot_cancelled_ids = set()

        def _canonical_cancel_intent(self, trade_id):
            return SimpleNamespace(
                operation_id=f"cancel:{trade_id}",
                intent_id=f"cancel-target:{trade_id}",
            )

        def cancel_offers(self, trade_ids, **_kwargs):
            return {trade_id: {"success": True} for trade_id in trade_ids}

        def get_cancel_result_authority(self, _trade_id):
            return None

    manager = boost_manager.BoostManager(offer_manager=SubmittedCancelManager())
    manager._boost_active = True
    manager._active_boost_ids = [TRADE]
    manager._boost_mid_price = Decimal("1")
    manager._gap_spread_bps = 137

    result = manager.deactivate()

    assert result["success"] is False
    assert result["pending"] == 1
    assert result["cancelled"] == 0
    assert manager._active_boost_ids == [TRADE]


def test_boost_task2_confirmation_cannot_replace_task9_terminal_proof(
    isolated_database,
):
    _seed_created_intent(tier="boost")
    result = {
        **cancellation_result(
            CANCEL_CONFIRMED,
            method="authority-policy-test",
            raw_response={"outcome": CANCEL_CONFIRMED},
        ),
        "_catalyst_effect_attempted": False,
        "_catalyst_idempotent_replay": True,
        "_catalyst_operation_id": f"cancel:{TRADE}",
        "_catalyst_intent_id": f"cancel-target:{TRADE}",
        "_catalyst_attempt": 1,
    }

    class Task2ConfirmedManager:
        _bot_cancelled_ids = set()

        @staticmethod
        def _canonical_cancel_intent(trade_id):
            return SimpleNamespace(
                operation_id=f"cancel:{trade_id}",
                intent_id=f"cancel-target:{trade_id}",
            )

        @staticmethod
        def cancel_offers(trade_ids, **_kwargs):
            return {trade_id: dict(result) for trade_id in trade_ids}

        @staticmethod
        def get_cancel_result_authority(trade_id):
            return {
                "trade_id": trade_id,
                "operation_id": f"cancel:{trade_id}",
                "intent_id": f"cancel-target:{trade_id}",
                "attempt": 1,
                "outcome": CANCEL_CONFIRMED,
            }

    manager = boost_manager.BoostManager(offer_manager=Task2ConfirmedManager())
    manager._boost_active = True
    manager._active_boost_ids = [TRADE]

    outcome = manager.deactivate()

    assert outcome["success"] is False
    assert outcome["cancelled"] == 0
    assert outcome["pending"] == 1
    assert manager._active_boost_ids == [TRADE]


def test_bot_loop_retirement_retains_unproven_sniper_cancel(isolated_database):
    _seed_created_intent(tier="sniper")
    loop = object.__new__(bot_loop.BotLoop)
    loop.sniper = SimpleNamespace(
        _snipe_lock=threading.RLock(),
        _active_snipe_ids=[TRADE],
        _active_snipe_sides={TRADE: "buy"},
    )

    retired = loop._retire_authoritative_sniper_ids([TRADE])

    assert retired == set()
    assert loop.sniper._active_snipe_ids == [TRADE]
    assert loop.sniper._active_snipe_sides == {TRADE: "buy"}


def _insert_legacy_boost_fill_without_intent() -> dict:
    conn = database.get_connection()
    cursor = conn.execute(
        """
        INSERT INTO fills (
            trade_id, side, price_xch, size_xch, size_cat, filled_at,
            cat_asset_id, tier, verification_status
        ) VALUES (?, 'buy', '0.001', '1', '1000', ?, ?, 'boost', 'verified_authoritative')
        """,
        (TRADE, AT, ASSET),
    )
    fill_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO offer_fill_hook_outbox "
        "(fill_id, hook_name, state, attempt) "
        "VALUES (?, 'boost_notification', 'pending', 0)",
        (fill_id,),
    )
    conn.execute(
        "INSERT INTO offer_fill_boost_commands "
        "(fill_id, trade_id, side, state, registered_at, applied_at) "
        "VALUES (?, ?, 'buy', 'registered', ?, NULL)",
        (fill_id, TRADE, AT),
    )
    conn.commit()
    return {
        "fill_id": fill_id,
        "trade_id": TRADE,
        "side": "buy",
        "price_xch": "0.001",
        "size_xch": "1",
        "size_cat": "1000",
        "tier": "boost",
        "filled_at": AT,
        "spent_block_index": 42,
    }


def test_legacy_boost_without_intent_trips_global_latch(isolated_database, monkeypatch):
    fill = _insert_legacy_boost_fill_without_intent()
    manager = _bare_boost_manager()
    manager.capture_authoritative_boost_fill_materialization = MagicMock()
    manager.notify_authoritative_boost_fill = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=manager)),
    )
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    callback = offer_reconciliation._post_fill_hook_callbacks(fill)[
        "boost_notification"
    ]

    with pytest.raises(RuntimeError, match="missing immutable materialization"):
        callback(
            fill,
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )

    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert latch["reason_code"] == "BOOST_COMMAND_MISSING_MATERIALIZATION"
    assert json.loads(latch["blocking_operation_ids_json"]) == [
        f"boost-fill:{fill['fill_id']}"
    ]
    manager.capture_authoritative_boost_fill_materialization.assert_not_called()
    manager.notify_authoritative_boost_fill.assert_not_called()


def test_repeated_stability_init_skips_all_append_only_backfill_scans(
    isolated_database,
    monkeypatch,
):
    names = (
        "_backfill_authoritative_sweep_active_queues",
        "_backfill_authoritative_sweep_safety_state",
        "_backfill_authoritative_boost_log_sinks",
        "_audit_legacy_boost_command_materializations",
        "_audit_legacy_offer_fill_hook_receipts",
        "_backfill_authoritative_fill_hook_outbox",
    )
    calls = {name: 0 for name in names}
    for name in names:
        original = getattr(database, name)

        def counted(*args, __name=name, __original=original, **kwargs):
            calls[__name] += 1
            return __original(*args, **kwargs)

        monkeypatch.setattr(database, name, counted)

    database._migrate_stability_schema()
    database._migrate_stability_schema()

    assert calls == {name: 0 for name in names}


def test_stability_watermark_with_missing_migrated_schema_fails_closed(
    isolated_database,
):
    conn = database.get_connection()
    conn.execute("DROP TABLE offer_fill_sweep_safety_state")
    conn.commit()
    database.close_connection()

    with pytest.raises(RuntimeError, match="watermark contradicts schema"):
        database._migrate_stability_schema()


@pytest.mark.parametrize(
    "table_name",
    [
        "offer_fill_hook_outbox",
        "offer_fill_hook_migration_audit",
        "offer_fill_boost_command_materializations",
    ],
)
def test_stability_watermark_rejects_every_missing_backfill_target(
    isolated_database,
    table_name,
):
    conn = database.get_connection()
    conn.execute(f"DROP TABLE {table_name}")
    conn.commit()
    database.close_connection()

    with pytest.raises(RuntimeError, match="watermark contradicts schema"):
        database._migrate_stability_schema()


def _insert_fill_with_downstream_fk() -> int:
    conn = database.get_connection()
    cursor = conn.execute(
        """
        INSERT INTO fills (
            trade_id, side, price_xch, size_xch, size_cat, filled_at,
            cat_asset_id, tier, verification_status
        ) VALUES ('legacy-fill', 'buy', '0.001', '1', '1000', ?, ?, 'inner',
                  'verified_authoritative')
        """,
        (AT, ASSET),
    )
    fill_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO offer_fill_hook_outbox "
        "(fill_id, hook_name, state, attempt) "
        "VALUES (?, 'offer_filled_event', 'pending', 0)",
        (fill_id,),
    )
    conn.commit()
    return fill_id


def test_destructive_reset_helper_returns_conflict_without_fk_error_or_data_loss(
    isolated_database,
    monkeypatch,
):
    fill_id = _insert_fill_with_downstream_fk()
    monkeypatch.setattr(api_server, "bot", None)

    result = api_server._reset_fresh_run_session(
        clear_coins=True,
        clear_price_history=True,
        clear_inventory=True,
        cancel_open_offers=True,
        preserve_history=False,
        reason="test-reset",
    )

    assert result["success"] is False
    assert result["error"] == "authoritative_state_conflict"
    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM fills WHERE fill_id=?", (fill_id,)
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_hook_outbox WHERE fill_id=?", (fill_id,)
        ).fetchone()[0]
        == 1
    )


def test_pnl_reset_route_returns_stable_conflict_for_authoritative_fill(
    isolated_database,
    monkeypatch,
):
    fill_id = _insert_fill_with_downstream_fk()
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server.mutation_gate, "enter_mutation", lambda _operation: "permit"
    )
    monkeypatch.setattr(api_server.mutation_gate, "exit_mutation", lambda _permit: True)
    api_server.app.testing = True
    client = api_server.app.test_client()

    response = client.post(
        "/api/pnl/reset",
        json={"confirm": "RESET"},
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "authoritative_state_conflict"
    assert (
        database.get_connection()
        .execute("SELECT COUNT(*) FROM fills WHERE fill_id=?", (fill_id,))
        .fetchone()[0]
        == 1
    )


def test_full_session_reset_refuses_nonterminal_state_before_runtime_clear(
    isolated_database,
    monkeypatch,
):
    _seed_created_intent()
    runtime_reset = MagicMock(return_value=["unsafe-runtime-clear"])
    monkeypatch.setattr(api_server, "_reset_fresh_run_runtime_memory", runtime_reset)
    monkeypatch.setattr(api_server, "bot", None)

    result = api_server._reset_fresh_run_session(
        clear_coins=False,
        clear_price_history=True,
        clear_inventory=True,
        cancel_open_offers=False,
        preserve_history=False,
        reason="nonterminal-reset",
    )

    assert result["success"] is False
    assert result["error"] == "authoritative_state_conflict"
    runtime_reset.assert_not_called()
    _assert_created_offer_is_protected()


def test_empty_database_reset_remains_compatible(isolated_database, monkeypatch):
    monkeypatch.setattr(api_server, "bot", None)

    result = api_server._reset_fresh_run_session(
        clear_coins=True,
        clear_price_history=True,
        clear_inventory=True,
        cancel_open_offers=True,
        preserve_history=False,
        reason="empty-reset",
    )

    assert result["success"] is True
    assert result["fills_cleared"] == 0
    assert result["coins_cleared"] == 0
    assert result["open_offers_cancelled"] == 0


def test_offer_history_reset_refuses_nonterminal_kernel_state(
    isolated_database,
    monkeypatch,
):
    _seed_created_intent()
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server.mutation_gate, "enter_mutation", lambda _operation: "permit"
    )
    monkeypatch.setattr(api_server.mutation_gate, "exit_mutation", lambda _permit: True)
    api_server.app.testing = True
    client = api_server.app.test_client()

    response = client.post(
        "/api/reset/offer-history",
        json={"confirm": "RESET"},
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "authoritative_state_conflict"
    _assert_created_offer_is_protected()


def test_session_fresh_start_does_not_mask_authoritative_reset_conflict(
    isolated_database,
    monkeypatch,
):
    _insert_fill_with_downstream_fk()
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server.mutation_gate, "enter_mutation", lambda _operation: "permit"
    )
    monkeypatch.setattr(api_server.mutation_gate, "exit_mutation", lambda _permit: True)
    fresh_start_set = MagicMock()
    monkeypatch.setattr(api_server, "_fresh_start_set", fresh_start_set)
    api_server.app.testing = True
    client = api_server.app.test_client()

    response = client.post(
        "/api/session/fresh-start",
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "authoritative_state_conflict"
    fresh_start_set.assert_not_called()


def test_source_inventory_has_no_unfenced_terminal_or_reset_bypasses():
    api_source = (SOURCE_ROOT / "api_server.py").read_text(encoding="utf-8")
    offers_source = (SOURCE_ROOT / "blueprints" / "offers.py").read_text(
        encoding="utf-8"
    )
    prep_source = (SOURCE_ROOT / "blueprints" / "coin_prep.py").read_text(
        encoding="utf-8"
    )
    prep_worker_source = (SOURCE_ROOT / "coin_prep_worker.py").read_text(
        encoding="utf-8"
    )
    bot_source = (SOURCE_ROOT / "bot_loop.py").read_text(encoding="utf-8")
    session_source = (SOURCE_ROOT / "blueprints" / "session.py").read_text(
        encoding="utf-8"
    )
    for source in (api_source, offers_source, prep_source, session_source):
        assert "DELETE FROM fills" not in source
        assert "DELETE FROM coins" not in source
        assert "UPDATE offers SET status='cancelled'" not in source
        assert "DELETE FROM offers" not in source

    assert "not in live_offer_ids" not in inspect.getsource(
        offer_manager.OfferManager.get_replenishment_slots
    )
    assert 'if o.get("trade_id") in live_offer_ids' not in inspect.getsource(
        offer_manager.OfferManager.requote_side
    )
    assert "get_authoritative_terminal_record" in inspect.getsource(
        shape_fix_orchestrator.ShapeFixOrchestrator._stage_waiting_for_confirmation
    )
    assert "get_authoritative_terminal_record" in inspect.getsource(
        boost_manager.BoostManager.prune_active_boosts
    )
    assert "get_authoritative_terminal_record" in inspect.getsource(
        sniper.Sniper.prune_active_snipes
    )
    assert "_active_boost_ids.clear()" not in inspect.getsource(
        boost_manager.BoostManager.deactivate
    )
    assert "bot.boost_manager._active_boost_ids.clear()" not in offers_source
    assert "self.sniper._active_snipe_ids.remove(_tid)" not in bot_source
    assert "self.sniper._active_snipe_ids = failed_ids" not in bot_source
    assert "_retire_authoritative_sniper_ids" in bot_source
    assert "UPDATE coins SET status='gone' WHERE status='free'" not in (
        prep_worker_source
    )
    assert (
        prep_worker_source.count("mark_unreserved_free_coins_gone_for_preparation") >= 2
    )


def test_manual_cancel_all_does_not_hide_locally_elapsed_wallet_offers():
    assert "is_offer_time_expired" not in inspect.getsource(api_server.api_cancel_all)


def test_boost_deactivate_api_projects_the_proof_preserving_manager_state():
    source = inspect.getsource(api_server.api_boost_deactivate)
    assert 'events.emit("boost", {"active": False})' not in source
    assert "boost_manager.get_state()" in source
