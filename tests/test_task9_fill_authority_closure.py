"""Task 9 closure tests for economic-fill and permanent coin authority."""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
from decimal import Decimal
from pathlib import Path

import pytest

import database
import market_data_collector
import risk_manager


AT = "2026-08-20T12:00:00.000000Z"
FILLED_AT = "2026-08-20T12:00:01.000000Z"
AFTER = "2026-08-20T12:00:02.000000Z"
WALLET = "f" * 64
ASSET = "a" * 64
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "catalyst"


@pytest.fixture(autouse=True)
def _socket_guard(monkeypatch):
    attempts: list[str] = []

    def blocked(*_args, **_kwargs):
        attempts.append("socket")
        raise AssertionError("Task 9 closure tests forbid network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "fill-authority.db"))
    database._db_initialized_path = ""
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: AT)
    database.init_database()
    yield tmp_path / "fill-authority.db"
    database.close_connection()


def _canonical_digest(value: dict) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _seed_authoritative_fill(
    *,
    suffix: str = "one",
    coin_id: str | None = None,
    tier: str = "inner",
    fee_mojos_xch: int = 7,
) -> tuple[dict, dict]:
    identity = hashlib.sha256(suffix.encode()).hexdigest()
    trade_id = f"trade-{suffix}"
    intent_id = f"intent-{suffix}"
    selected_coin_id = coin_id or hashlib.sha256(f"coin:{suffix}".encode()).hexdigest()
    receive_coin_id = hashlib.sha256(f"receive:{suffix}".encode()).hexdigest()
    transaction_id = hashlib.sha256(f"transaction:{suffix}".encode()).hexdigest()
    wallet_identity = {
        "wallet_fingerprint_hash": WALLET,
        "network": "mainnet",
    }

    assert database.upsert_coin(
        selected_coin_id,
        "xch",
        100_000_000_000,
        designation="tier_spare",
        tier=tier,
    )
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="fill-authority-test",
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        asset_id=ASSET,
        side="buy",
        tier=tier,
        purpose="fill_authority_test",
        slot_key=f"slot:{identity}",
        generation=0,
        offered_amount_atomic="100000000000",
        requested_amount_atomic="100000",
        selected_coin_ids_json=[selected_coin_id],
        wallet_identity_json=wallet_identity,
        evidence_json={"fixture": "fill authority intent"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=hashlib.sha256(f"offer:{suffix}".encode()).hexdigest(),
        wallet_identity_json=wallet_identity,
        evidence_json={"fixture": "fill authority creation"},
        finalized_at=AT,
        finalize_selected_coin_reservations=True,
    )
    assert database.add_offer(
        trade_id,
        "buy",
        Decimal("0.001"),
        Decimal("0.1"),
        Decimal("100"),
        ASSET,
        tier=tier,
        coin_id=database.norm_coin_id(selected_coin_id),
        fee_mojos_xch=fee_mojos_xch,
    )
    evidence = {
        "fixture": "fill authority terminal",
        "trade_id": trade_id,
        "classification": {
            "classification": "FILLED_PROVEN",
            "transaction_id": transaction_id,
            "spend_identity": None,
            "block_height": 42,
            "receive_coin_id": receive_coin_id,
            "receive_amount_mojos": 100_000,
            "filled_at": FILLED_AT,
        },
    }
    kwargs = {
        "intent_id": intent_id,
        "operation_id": f"reconcile:{intent_id}",
        "classification": "FILLED_PROVEN",
        "reason_code": "TEST_AUTHORITATIVE_PROOF",
        "wallet_identity_json": wallet_identity,
        "evidence_json": evidence,
        "evidence_sha256": _canonical_digest(evidence),
        "transaction_id": transaction_id,
        "block_height": 42,
        "receive_coin_id": receive_coin_id,
        "receive_amount_mojos": 100_000,
        "filled_at": FILLED_AT,
        "reconciled_at": AFTER,
    }
    result = database.commit_offer_reconciliation(**kwargs)
    return result, {**kwargs, "coin_id": database.norm_coin_id(selected_coin_id)}


def _insert_prefixed_active_intent(
    conn, *, source_intent_id: str, suffix: str
) -> tuple[str, str]:
    source = conn.execute(
        "SELECT * FROM offer_intents WHERE intent_id=?", (source_intent_id,)
    ).fetchone()
    values = dict(source)
    intent_id = f"prefixed-active-{suffix}"
    trade_id = f"prefixed-active-trade-{suffix}"
    values.update(
        {
            "intent_id": intent_id,
            "slot_key": f"prefixed-active-slot-{suffix}",
            "parent_intent_id": None,
            "child_intent_id": None,
            "offer_text_sha256": hashlib.sha256(
                f"prefixed-active-offer-{suffix}".encode()
            ).hexdigest(),
            "sage_trade_id": trade_id,
            "publication_identity": None,
            "lifecycle_state": "created",
            "row_version": 0,
            "submitted_at": AT,
            "confirmed_at": AT,
            "first_visible_at": AT,
            "terminal_at": None,
            "updated_at": AFTER,
        }
    )
    columns = tuple(values)
    conn.execute(
        f"INSERT INTO offer_intents ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _column in columns)})",
        tuple(values[column] for column in columns),
    )
    return intent_id, trade_id


def _clear_fill_authority_closure_watermark(conn) -> None:
    conn.execute("DROP TRIGGER stability_migration_watermarks_no_delete")
    conn.execute(
        "DELETE FROM stability_migration_watermarks WHERE migration_key=?",
        (database._FILL_AUTHORITY_CLOSURE_MIGRATION_KEY,),
    )
    conn.execute(
        """CREATE TRIGGER stability_migration_watermarks_no_delete
        BEFORE DELETE ON stability_migration_watermarks
        BEGIN
            SELECT RAISE(ABORT, 'stability_migration_watermarks is append-only');
        END"""
    )
    conn.commit()


@pytest.mark.parametrize(
    "requested_status",
    [None, "verified", "verified_exact", "verified_authoritative"],
)
def test_public_record_fill_never_creates_economic_authority(
    isolated_database, monkeypatch, requested_status
):
    suffix = requested_status or "default"
    trade_id = f"proofless-{suffix}"
    coin_id = hashlib.sha256(trade_id.encode()).hexdigest()
    kwargs = {}
    if requested_status is not None:
        kwargs["verification_status"] = requested_status
    fill_id = database.record_fill(
        trade_id=trade_id,
        side="buy",
        price_xch=Decimal("0.001"),
        size_xch=Decimal("0.1"),
        size_cat=Decimal("100"),
        cat_asset_id=ASSET,
        **kwargs,
    )
    assert database.add_offer(
        trade_id,
        "buy",
        Decimal("0.001"),
        Decimal("0.1"),
        Decimal("100"),
        ASSET,
        coin_id=coin_id,
    )

    stored = (
        database.get_connection()
        .execute("SELECT verification_status FROM fills WHERE fill_id=?", (fill_id,))
        .fetchone()
    )
    assert stored["verification_status"] == "legacy_unproven_filled"
    assert database.get_fills(cat_asset_id=ASSET) == []
    assert [
        row["fill_id"] for row in database.get_fills(ASSET, include_legacy=True)
    ] == [fill_id]
    assert database.count_recent_fills(24) == 0
    assert database.get_net_position(ASSET) == Decimal("0")
    stats = database.get_stats(ASSET)
    assert stats["raw_total_fills"] == 0
    assert stats["total_fills"] == 0
    usage = database.get_offer_coin_usage_summary(coin_id, ASSET)
    assert usage["verified_fill_count"] == 0
    assert usage["verified_trade_ids"] == []

    monkeypatch.setattr(risk_manager.cfg, "CAT_ASSET_ID", ASSET)
    monkeypatch.setattr(risk_manager.cfg, "RUN_HISTORY_CUTOFF", None, raising=False)
    manager = risk_manager.RiskManager()
    manager.update_inventory()
    assert manager._net_position_cat == Decimal("0")
    market = market_data_collector._fetch_internal_db_history(ASSET)
    assert market["fill_count"] == 0
    assert market["own_fill_samples"] == 0


def test_backfill_demotes_every_unproven_verified_variant(isolated_database):
    conn = database.get_connection()
    variants = ("verified", "verified_exact", "verified_authoritative", "verified_old")
    for index, status in enumerate(variants):
        trade_id = f"historical-{index}"
        assert database.add_offer(
            trade_id,
            "sell",
            Decimal("0.002"),
            Decimal("0.2"),
            Decimal("100"),
            ASSET,
        )
        conn.execute(
            "UPDATE offers SET status='filled', lifecycle_state='filled', filled_at=? "
            "WHERE trade_id=?",
            (FILLED_AT, trade_id),
        )
        conn.execute(
            "INSERT INTO fills (trade_id, side, price_xch, size_xch, size_cat, "
            "filled_at, cat_asset_id, tier, verification_status, fee_mojos_xch) "
            "VALUES (?, 'sell', '0.002', '0.2', '100', ?, ?, 'inner', ?, 0)",
            (trade_id, FILLED_AT, ASSET, status),
        )
    conn.commit()

    repaired = database.backfill_verified_fills_from_offers(limit=20)

    assert {row["trade_id"] for row in repaired} == {
        f"historical-{index}" for index in range(len(variants))
    }
    statuses = conn.execute(
        "SELECT verification_status FROM fills ORDER BY trade_id"
    ).fetchall()
    assert {row["verification_status"] for row in statuses} == {
        "legacy_unproven_filled"
    }
    assert database.get_fills(ASSET) == []


def test_textual_verified_fill_does_not_seed_authoritative_hook_work(
    isolated_database,
):
    conn = database.get_connection()
    cursor = conn.execute(
        "INSERT INTO fills (trade_id, side, price_xch, size_xch, size_cat, "
        "filled_at, cat_asset_id, tier, verification_status, fee_mojos_xch) "
        "VALUES ('forged-hook-fill', 'buy', '0.001', '0.1', '100', ?, ?, "
        "'inner', 'verified_authoritative', 0)",
        (FILLED_AT, ASSET),
    )
    fill_id = int(cursor.lastrowid)
    conn.commit()

    database._backfill_authoritative_fill_hook_outbox(conn)

    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_hook_outbox WHERE fill_id=?", (fill_id,)
        ).fetchone()[0]
        == 0
    )


def test_authoritative_fill_has_one_immutable_authority_receipt(isolated_database):
    result, _kwargs = _seed_authoritative_fill()
    receipt = (
        database.get_connection()
        .execute(
            "SELECT * FROM authoritative_fill_receipts WHERE fill_id=?",
            (result["fill_id"],),
        )
        .fetchone()
    )
    assert receipt is not None
    assert len(receipt["authority_token"]) == 64
    assert database.get_fills(ASSET)[0]["fill_id"] == result["fill_id"]


def test_migration_restores_receipt_only_from_complete_historical_proof(
    isolated_database,
):
    result, _kwargs = _seed_authoritative_fill(
        suffix="historical-proof-control", fee_mojos_xch=0
    )
    conn = database.get_connection()
    conn.execute("DROP TRIGGER authoritative_fill_receipts_no_delete")
    conn.execute(
        "DELETE FROM authoritative_fill_receipts WHERE fill_id=?",
        (result["fill_id"],),
    )
    conn.execute(
        """CREATE TRIGGER authoritative_fill_receipts_no_delete
        BEFORE DELETE ON authoritative_fill_receipts
        BEGIN
            SELECT RAISE(ABORT, 'authoritative_fill_receipts is append-only');
        END"""
    )
    conn.commit()
    _clear_fill_authority_closure_watermark(conn)

    database._migrate_fill_authority_closure(conn)

    assert (
        conn.execute(
            "SELECT COUNT(*) FROM authoritative_fill_receipts WHERE fill_id=?",
            (result["fill_id"],),
        ).fetchone()[0]
        == 1
    )
    assert database.get_fill_by_id(result["fill_id"])["verification_status"] == (
        "verified_authoritative"
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_authority_migration_audit "
            "WHERE authority_type='fill' AND subject_id=?",
            (str(result["fill_id"]),),
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    ("column", "changed"),
    [
        ("price_xch", "0.002"),
        ("size_xch", "0.2"),
        ("size_cat", "101"),
        ("fee_mojos_xch", 8),
    ],
)
def test_migration_never_mints_authority_from_correlated_mutable_economics(
    isolated_database, column, changed
):
    result, _kwargs = _seed_authoritative_fill(
        suffix=f"historical-{column}", fee_mojos_xch=0
    )
    conn = database.get_connection()
    conn.execute("DROP TRIGGER authoritative_fill_receipts_no_delete")
    conn.execute(
        "DELETE FROM authoritative_fill_receipts WHERE fill_id=?",
        (result["fill_id"],),
    )
    conn.execute(
        """CREATE TRIGGER authoritative_fill_receipts_no_delete
        BEFORE DELETE ON authoritative_fill_receipts
        BEGIN
            SELECT RAISE(ABORT, 'authoritative_fill_receipts is append-only');
        END"""
    )
    conn.execute(
        f"UPDATE fills SET {column}=? WHERE fill_id=?", (changed, result["fill_id"])
    )
    conn.execute(
        f"UPDATE offers SET {column}=? WHERE trade_id=?",
        (changed, f"trade-historical-{column}"),
    )
    conn.commit()
    _clear_fill_authority_closure_watermark(conn)

    database._migrate_fill_authority_closure(conn)

    assert (
        conn.execute(
            "SELECT COUNT(*) FROM authoritative_fill_receipts WHERE fill_id=?",
            (result["fill_id"],),
        ).fetchone()[0]
        == 0
    )
    assert database.get_fill_by_id(result["fill_id"])["verification_status"] == (
        "legacy_unproven_filled"
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_authority_migration_audit "
            "WHERE authority_type='fill' AND subject_id=? "
            "AND reason_code='UNPROVEN_ECONOMIC_FILL_DEMOTED'",
            (str(result["fill_id"]),),
        ).fetchone()[0]
        == 1
    )


def test_market_history_consumes_exact_authoritative_projection(isolated_database):
    for suffix in ("market-history-a", "market-history-b", "market-history-c"):
        _seed_authoritative_fill(suffix=suffix)

    history = market_data_collector._fetch_internal_db_history(ASSET)

    assert history["fill_count"] == 3
    assert history["own_fill_samples"] == 3


def test_authoritative_fill_rejects_enrichment_changes(isolated_database):
    result, _kwargs = _seed_authoritative_fill()
    fill_id = result["fill_id"]
    assert not database.update_fill_enrichment(fill_id, spent_block_height=43)
    assert not database.update_fill_enrichment(fill_id, receive_amount_mojos=100_001)
    assert not database.update_fill_enrichment(fill_id, receive_coin_id="9" * 64)
    assert not database.update_fill_enrichment(fill_id, header_hash="8" * 64)


def test_proofless_fill_cannot_enter_round_trip_pnl(isolated_database):
    result, _kwargs = _seed_authoritative_fill(suffix="round-trip")
    proofless_id = database.record_fill(
        trade_id="proofless-round-trip",
        side="sell",
        price_xch=Decimal("0.002"),
        size_xch=Decimal("0.2"),
        size_cat=Decimal("100"),
        cat_asset_id=ASSET,
        filled_at=AFTER,
    )

    assert (
        database.match_round_trip(result["fill_id"], proofless_id, Decimal("0.1")) == -1
    )
    assert database.get_fill_by_id(result["fill_id"])["round_trip_id"] is None
    assert database.get_fill_by_id(proofless_id)["round_trip_id"] is None
    stats = database.get_stats(ASSET)
    assert stats["round_trips"] == 0
    assert stats["realised_pnl_xch"] == "0"


def test_historical_proofless_round_trip_pair_is_never_economic(isolated_database):
    result, _kwargs = _seed_authoritative_fill(suffix="historical-round-trip")
    proofless_id = database.record_fill(
        trade_id="historical-proofless-round-trip",
        side="sell",
        price_xch=Decimal("0.002"),
        size_xch=Decimal("0.2"),
        size_cat=Decimal("100"),
        cat_asset_id=ASSET,
        filled_at=AFTER,
    )
    conn = database.get_connection()
    conn.execute(
        "UPDATE fills SET round_trip_id=?, pnl_xch='0.1' WHERE fill_id IN (?, ?)",
        (result["fill_id"], result["fill_id"], proofless_id),
    )
    conn.commit()

    stats = database.get_stats(ASSET)
    assert stats["round_trips"] == 0
    assert stats["realised_pnl_xch"] == "0"
    assert stats["win_rate"] == 0
    assert stats["avg_round_trip_secs"] == 0


def test_nonauthoritative_enrichment_accepts_only_nullable_exact_types(
    isolated_database,
):
    fill_id = database.record_fill(
        trade_id="legacy-enrichment",
        side="buy",
        price_xch=Decimal("0.001"),
        size_xch=Decimal("0.1"),
        size_cat=Decimal("100"),
        cat_asset_id=ASSET,
    )
    assert not database.update_fill_enrichment(fill_id, spent_block_height=True)
    assert not database.update_fill_enrichment(fill_id, receive_amount_mojos=True)
    assert not database.update_fill_enrichment(fill_id, receive_coin_id=123)
    assert not database.update_fill_enrichment(fill_id, header_hash=123)
    assert database.update_fill_enrichment(fill_id, spent_block_height=42)
    assert not database.update_fill_enrichment(fill_id, spent_block_height=43)
    assert database.update_fill_enrichment(fill_id, receive_coin_id="7" * 64)
    stored = database.get_fill_by_id(fill_id)
    assert stored["spent_block_height"] == 42
    assert stored["receive_coin_id"] == "0x" + "7" * 64


@pytest.mark.parametrize(
    ("column", "changed"),
    [
        ("tier", "outer"),
        ("fee_mojos_xch", 8),
        ("spent_block_height", 43),
        ("spent_block_index", 43),
        ("receive_coin_id", "0x" + "9" * 64),
        ("receive_amount_mojos", 100_001),
    ],
)
def test_changed_authoritative_fill_replay_is_rejected(
    isolated_database, column, changed
):
    result, kwargs = _seed_authoritative_fill(suffix=column)
    conn = database.get_connection()
    conn.execute(
        f"UPDATE fills SET {column}=? WHERE fill_id=?", (changed, result["fill_id"])
    )
    conn.commit()

    with pytest.raises(ValueError, match="authoritative fill"):
        database.commit_offer_reconciliation(
            **{key: value for key, value in kwargs.items() if key != "coin_id"}
        )
    assert database.get_fills(ASSET) == []


def test_permanent_spend_dominates_corrupt_free_projection_and_all_readers(
    isolated_database,
):
    _result, kwargs = _seed_authoritative_fill()
    coin_id = kwargs["coin_id"]
    conn = database.get_connection()
    conn.execute(
        "UPDATE coins SET status='free', trade_id=NULL, designation='tier_spare', "
        "assigned_tier='inner' WHERE coin_id=?",
        (coin_id,),
    )
    conn.commit()

    assert database.get_free_coins("xch") == []
    assert database.get_smallest_free_tier_spare("xch") is None
    assert database.get_coin_summary()["xch_total"] == 0
    assert coin_id not in database.get_all_coins_state()
    assert database.get_designation_summary("xch")["tier_spare"]["count"] == 0
    assert database.get_tier_spare_counts("xch")["inner"] == 0
    assert database.get_live_tier_group_counts()["xch"]["inner"] == 0
    assert database.get_coins_by_designation("xch", "tier_spare", "inner") == []

    conn.execute(
        "UPDATE coins SET status='locked', trade_id='corrupt-live-offer' "
        "WHERE coin_id=?",
        (coin_id,),
    )
    conn.commit()
    assert database.coin_sanity_check(open_offer_count=0)["locked_count"] == 0


def test_recent_deposit_candidates_exclude_permanent_spend(isolated_database):
    _result, kwargs = _seed_authoritative_fill(suffix="deposit-candidate")
    coin_id = kwargs["coin_id"]
    conn = database.get_connection()
    conn.execute(
        "UPDATE coins SET status='gone', trade_id=NULL, designation='reserve' "
        "WHERE coin_id=?",
        (coin_id,),
    )
    conn.commit()

    assert (
        database.get_recent_available_deposit_coins(
            "xch", minimum_amount_mojos=1, maximum_amount_mojos=200_000_000_000
        )
        == []
    )


def test_authoritative_availability_predicate_has_complete_reader_inventory():
    readers = (
        database.get_free_coins,
        database.get_recent_available_deposit_coins,
        database.get_smallest_free_tier_spare,
        database.get_coin_summary,
        database.get_all_coins_state,
        database.get_coins_by_designation,
        database.get_oversized_locked_offers,
        database.get_designation_summary,
        database.get_tier_spare_counts,
        database.get_live_tier_group_counts,
        database.coin_sanity_check,
        database.mark_coins_gone,
        database.mark_unreserved_free_coins_gone_for_preparation,
    )
    for reader in readers:
        assert "_authoritative_coin_available_predicate" in inspect.getsource(reader)

    for relative in ("coin_manager.py", "bot_health.py", "coin_prep_worker.py"):
        source = (SOURCE_ROOT / relative).read_text(encoding="utf-8")
        assert "AND status='free'" not in source
        assert "WHERE wallet_type=? AND status='free'" not in source

    coin_manager_source = (SOURCE_ROOT / "coin_manager.py").read_text(encoding="utf-8")
    assert "SELECT COUNT(*) FROM coins WHERE status='locked'" not in coin_manager_source
    assert "WHERE wallet_type=? AND status IN ('free', 'locked')" not in (
        coin_manager_source
    )
    bot_loop_source = (SOURCE_ROOT / "bot_loop.py").read_text(encoding="utf-8")
    assert '"FROM coins "' not in bot_loop_source


def test_authority_projections_are_indexed_and_migration_is_hard_bounded(
    isolated_database,
):
    conn = database.get_connection()
    plan = conn.execute(
        "EXPLAIN QUERY PLAN SELECT coin_id FROM coins WHERE status='free' AND "
        + database._authoritative_coin_available_predicate()
    ).fetchall()
    detail = " ".join(str(row["detail"]) for row in plan)
    assert "idx_offer_reconciliation_coin_outcomes_permanent" in detail
    assert database._MAX_FILL_AUTHORITY_CLOSURE_ROWS == 4096
    source = inspect.getsource(database._migrate_fill_authority_closure)
    assert source.count("_MAX_FILL_AUTHORITY_CLOSURE_ROWS + 1") >= 2
    assert "selected_count > _MAX_FILL_AUTHORITY_CLOSURE_ROWS" in source


def test_cross_intent_release_cannot_supersede_permanent_spend(isolated_database):
    _result, kwargs = _seed_authoritative_fill()
    coin_id = kwargs["coin_id"]
    conn = database._stability_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError, match="permanent"):
            database._insert_authoritative_coin_outcomes(
                conn,
                intent_id="different-intent",
                trade_id="different-trade",
                selected_coin_ids=[coin_id],
                event={
                    "outcome": "EXPIRED_PROVEN",
                    "event_id": "reconcile:different-intent:attempt:1:finalized",
                    "evidence_sha256": "e" * 64,
                },
                recorded_at=AFTER,
            )
        conn.rollback()
    finally:
        conn.close()

    outcome = database._authoritative_coin_outcome(database.get_connection(), coin_id)
    assert outcome is not None
    assert outcome["disposition"] == "spent"


def test_cross_intent_expiry_commit_rejects_and_rolls_back(isolated_database):
    _result, kwargs = _seed_authoritative_fill(suffix="release-rollback")
    coin_id = kwargs["coin_id"]
    conn = database.get_connection()
    intent_id, trade_id = _insert_prefixed_active_intent(
        conn, source_intent_id=kwargs["intent_id"], suffix="release-rollback"
    )
    conn.execute(
        "UPDATE coins SET status='locked', trade_id=? WHERE coin_id=?",
        (trade_id, coin_id),
    )
    conn.commit()
    before_outcomes = conn.execute(
        "SELECT COUNT(*) FROM offer_reconciliation_coin_outcomes WHERE coin_id=?",
        (coin_id,),
    ).fetchone()[0]
    evidence = {"fixture": "contradictory release", "trade_id": trade_id}

    with pytest.raises(RuntimeError, match="permanent"):
        database.commit_offer_reconciliation(
            intent_id=intent_id,
            operation_id=f"reconcile:{intent_id}",
            classification="EXPIRED_PROVEN",
            reason_code="TEST_CONTRADICTORY_RELEASE",
            wallet_identity_json={
                "wallet_fingerprint_hash": WALLET,
                "network": "mainnet",
            },
            evidence_json=evidence,
            evidence_sha256=_canonical_digest(evidence),
            reconciled_at=AFTER,
        )

    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_operation_journal WHERE intent_id=? "
            "AND operation_type='RECONCILE'",
            (intent_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_reconciliation_coin_outcomes WHERE coin_id=?",
            (coin_id,),
        ).fetchone()[0]
        == before_outcomes
    )
    projection = database.get_coin_state(coin_id)
    assert projection["status"] == "locked"
    assert projection["trade_id"] == trade_id


def test_migration_audits_prefixed_active_owner_of_permanently_spent_coin(
    isolated_database,
):
    _result, kwargs = _seed_authoritative_fill(suffix="active-owner")
    coin_id = kwargs["coin_id"]
    conn = database.get_connection()
    active_intent_id, _trade_id = _insert_prefixed_active_intent(
        conn, source_intent_id=kwargs["intent_id"], suffix="active-owner"
    )
    _clear_fill_authority_closure_watermark(conn)

    database._migrate_fill_authority_closure(conn)

    audit = conn.execute(
        "SELECT details_json FROM offer_authority_migration_audit "
        "WHERE authority_type='coin' AND subject_id=?",
        (coin_id,),
    ).fetchone()
    assert active_intent_id in json.loads(audit["details_json"])["active_intent_ids"]
    assert database.get_coin_state(coin_id)["status"] == "spent"
    latch = database.get_runtime_safety_latch()
    assert f"authority:coin:{coin_id}" in json.loads(
        latch["blocking_operation_ids_json"]
    )


def test_migration_audits_latches_and_repairs_prefixed_release_conflict(
    isolated_database,
):
    _result, kwargs = _seed_authoritative_fill()
    coin_id = kwargs["coin_id"]
    conn = database.get_connection()
    before_count = conn.execute(
        "SELECT COUNT(*) FROM offer_reconciliation_coin_outcomes WHERE coin_id=?",
        (coin_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO offer_reconciliation_coin_outcomes "
        "(coin_id, intent_id, trade_id, outcome, disposition, terminal_event_id, "
        " evidence_sha256, recorded_at) "
        "VALUES (?, 'prefixed-release-intent', 'prefixed-release-trade', "
        "'EXPIRED_PROVEN', 'released', 'prefixed-release-event', ?, ?)",
        (coin_id, "e" * 64, AFTER),
    )
    conn.execute(
        "UPDATE coins SET status='free', trade_id=NULL, designation='tier_spare', "
        "assigned_tier='inner' WHERE coin_id=?",
        (coin_id,),
    )
    _clear_fill_authority_closure_watermark(conn)

    database._migrate_fill_authority_closure(conn)

    outcome = database._authoritative_coin_outcome(conn, coin_id)
    assert outcome["disposition"] == "spent"
    assert outcome["intent_id"] == kwargs["intent_id"]
    assert (
        conn.execute("SELECT status FROM coins WHERE coin_id=?", (coin_id,)).fetchone()[
            "status"
        ]
        == "spent"
    )
    audit = conn.execute(
        "SELECT reason_code FROM offer_authority_migration_audit "
        "WHERE authority_type='coin' AND subject_id=?",
        (coin_id,),
    ).fetchone()
    assert audit["reason_code"] == "PERMANENT_SPEND_AUTHORITY_CONFLICT"
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert f"authority:coin:{coin_id}" in json.loads(
        latch["blocking_operation_ids_json"]
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_reconciliation_coin_outcomes WHERE coin_id=?",
            (coin_id,),
        ).fetchone()[0]
        == before_count + 1
    )
