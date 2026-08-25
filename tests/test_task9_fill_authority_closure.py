"""Task 9 closure tests for economic-fill and permanent coin authority."""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
import sqlite3
import threading
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import database
import market_data_collector
import offer_reconciliation
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


@pytest.fixture
def active_wallet_effect_runtime(isolated_database):
    import mutation_gate

    mutation_gate.shutdown_runtime(release_owned_lease=True)
    clock = {"now": datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)}
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Task 9 Wallet",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc="2026-08-20T11:59:59.000000Z",
        maximum_age_seconds=15,
    )

    class WalletAdapterDouble:
        pass

    adapter = WalletAdapterDouble()
    runtime = mutation_gate.MutationGate(
        run_id="task9-wallet-effect-owner",
        owner_pid=4242,
        owner_host="task9-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network="mainnet",
        lease_seconds=30,
        clock=lambda: clock["now"],
        pid_liveness=lambda _pid, _host: False,
        wallet_identity_binding=binding,
        wallet_adapter_authority=adapter,
    )
    assert runtime.acquire()["acquired"] is True
    mutation_gate._runtime = runtime
    try:
        yield runtime, clock, mutation_gate.wallet_fingerprint_hash(binding.fingerprint)
    finally:
        mutation_gate.shutdown_runtime(release_owned_lease=True)


def _canonical_digest(value: dict) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _task12_split_prep_contract(source_coin_id: str) -> dict:
    return {
        "operation_kind": "split",
        "purpose": "operator_recovery",
        "target_contract": {
            "wallet_type": "xch",
            "outputs": [
                {
                    "output_index": 0,
                    "amount_mojos": 199_999,
                    "purpose": "operator_recovery",
                }
            ],
        },
        "pre_view_coin_ids": [source_coin_id],
    }


def _bind_task12_worker_identity(worker, runtime) -> None:
    import mutation_gate

    identity = mutation_gate.wallet_identity_binding_payload(
        runtime.wallet_identity_binding
    )
    worker._current_coin_prep_wallet_identity = lambda: identity


def _wallet_effect_result_marker(claim_token: str, *, attempted: bool) -> dict:
    row = (
        database.get_connection()
        .execute(
            "SELECT authority_json FROM wallet_effect_claim_authorities "
            "WHERE claim_token=?",
            (claim_token,),
        )
        .fetchone()
    )
    assert row is not None
    authority = json.loads(str(row["authority_json"]))
    authority.pop("lease_version", None)
    return {
        "success": False,
        "_catalyst_effect_attempted": attempted,
        "_catalyst_wallet_authority_sha256": _canonical_digest(authority),
    }


def _wallet_effect_real_facade_result(
    runtime, monkeypatch, *, attempted: bool, success: bool = False
) -> dict:
    import mutation_gate
    import wallet

    adapter = runtime._wallet_adapter_authority
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    if attempted:
        monkeypatch.setattr(wallet, "_identity_from_adapter", lambda _adapter: {})
        monkeypatch.setattr(
            mutation_gate,
            "require_fresh_wallet_identity",
            lambda _binding, _snapshot, _operation: None,
        )
        monkeypatch.setattr(
            adapter,
            "test_effect_adapter",
            lambda: {"success": success},
            raising=False,
        )
    else:

        def blocked_identity(_adapter):
            raise mutation_gate.MutationBlocked(
                "WALLET_IDENTITY_CHANGED", "wallet:test_effect_adapter"
            )

        monkeypatch.setattr(wallet, "_identity_from_adapter", blocked_identity)
    return wallet._run_wallet_mutation("test_effect_adapter")


def _seed_authoritative_fill(
    *,
    suffix: str = "one",
    coin_id: str | None = None,
    tier: str = "inner",
    fee_mojos_xch: int = 7,
    side: str = "buy",
    price_xch: Decimal | None = None,
    size_xch: Decimal = Decimal("0.1"),
    size_cat: Decimal = Decimal("100"),
    filled_at: str = FILLED_AT,
    cat_asset_id: str = ASSET,
    reconciled_at: str = AFTER,
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
    cat_decimals = 3
    if price_xch is None:
        price_xch = size_xch / size_cat
    xch_amount_atomic = int(size_xch * Decimal(1_000_000_000_000))
    cat_amount_atomic = int(size_cat * (Decimal(10) ** cat_decimals))
    offered_amount_atomic = xch_amount_atomic if side == "buy" else cat_amount_atomic
    requested_amount_atomic = cat_amount_atomic if side == "buy" else xch_amount_atomic

    assert database.upsert_coin(
        selected_coin_id,
        "xch" if side == "buy" else "cat",
        offered_amount_atomic,
        designation="tier_spare",
        tier=tier,
        purpose="lifecycle",
    )
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="fill-authority-test",
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        asset_id=cat_asset_id,
        side=side,
        tier=tier,
        purpose="fill_authority_test",
        slot_key=f"slot:{identity}",
        generation=0,
        offered_amount_atomic=str(offered_amount_atomic),
        requested_amount_atomic=str(requested_amount_atomic),
        selected_coin_ids_json=[selected_coin_id],
        cat_decimals=cat_decimals,
        fee_mojos_xch=fee_mojos_xch,
        fee_provenance="EXPLICIT_TEST_CREATE_FEE_V1",
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
        side,
        price_xch,
        size_xch,
        size_cat,
        cat_asset_id,
        tier=tier,
        coin_id=database.norm_coin_id(selected_coin_id),
        fee_mojos_xch=fee_mojos_xch,
    )
    economics = database.get_offer_intent_economic_authority(intent_id)
    assert economics is not None
    assert economics["price_xch"] == str(price_xch)
    assert economics["size_xch"] == str(size_xch)
    assert economics["size_cat"] == str(size_cat)
    transaction_flow_sha256 = database.canonical_fill_transaction_flow_token(
        transaction_id,
        None,
        42,
        economics["selected_coin_ids_sha256"],
        side,
        cat_asset_id,
        str(offered_amount_atomic),
        str(requested_amount_atomic),
        database.norm_coin_id(receive_coin_id),
        requested_amount_atomic,
    )
    evidence = {
        "fixture": "fill authority terminal",
        "trade_id": trade_id,
        "fill_authority": {
            "schema_version": 1,
            "intent_id": intent_id,
            "prepared_event_id": economics["prepared_event_id"],
            "economic_authority_token": economics["authority_token"],
            "trade_id": trade_id,
            "side": side,
            "price_xch": str(price_xch),
            "size_xch": str(size_xch),
            "size_cat": str(size_cat),
            "cat_asset_id": cat_asset_id,
            "tier": tier,
            "offered_amount_atomic": str(offered_amount_atomic),
            "requested_amount_atomic": str(requested_amount_atomic),
            "cat_decimals": cat_decimals,
            "fee_mojos_xch": fee_mojos_xch,
            "fee_provenance": "EXPLICIT_TEST_CREATE_FEE_V1",
            "selected_coin_ids_sha256": economics["selected_coin_ids_sha256"],
            "transaction_flow_sha256": transaction_flow_sha256,
            "spent_block_height": 42,
            "receive_coin_id": database.norm_coin_id(receive_coin_id),
            "receive_amount_mojos": requested_amount_atomic,
            "filled_at": filled_at,
            "transaction_id": transaction_id,
            "spend_identity": None,
        },
        "classification": {
            "classification": "FILLED_PROVEN",
            "reason_code": "TEST_AUTHORITATIVE_PROOF",
            "transaction_id": transaction_id,
            "spend_identity": None,
            "block_height": 42,
            "receive_coin_id": receive_coin_id,
            "receive_amount_mojos": requested_amount_atomic,
            "filled_at": filled_at,
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
        "receive_amount_mojos": requested_amount_atomic,
        "filled_at": filled_at,
        "reconciled_at": reconciled_at,
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


def _delete_authoritative_receipt_for_test(conn, fill_id: int) -> dict:
    receipt = dict(
        conn.execute(
            "SELECT * FROM authoritative_fill_receipts WHERE fill_id=?", (fill_id,)
        ).fetchone()
    )
    conn.execute("DROP TRIGGER authoritative_fill_receipts_no_delete")
    conn.execute("DELETE FROM authoritative_fill_receipts WHERE fill_id=?", (fill_id,))
    conn.execute(
        """CREATE TRIGGER authoritative_fill_receipts_no_delete
        BEFORE DELETE ON authoritative_fill_receipts
        BEGIN
            SELECT RAISE(ABORT, 'authoritative_fill_receipts is append-only');
        END"""
    )
    conn.commit()
    return receipt


def test_direct_receipt_insert_requires_exact_terminal_fill_proof(
    isolated_database,
):
    proven, _proof = _seed_authoritative_fill(suffix="receipt-guard-source")
    conn = database.get_connection()
    unrelated = conn.execute(
        "SELECT event_id, intent_id, evidence_sha256, created_at "
        "FROM offer_operation_journal "
        "WHERE intent_id=? AND operation_type='CREATE' AND phase='PREPARED'",
        ("intent-receipt-guard-source",),
    ).fetchone()
    assert unrelated is not None

    cursor = conn.execute(
        "INSERT INTO fills (trade_id, side, price_xch, size_xch, size_cat, "
        "filled_at, cat_asset_id, tier, verification_status, fee_mojos_xch, "
        "spent_block_index, spent_block_height, receive_coin_id, "
        "receive_amount_mojos) VALUES (?, 'buy', '0.001', '0.1', '100', ?, ?, "
        "'inner', 'verified_authoritative', 0, 77, 77, ?, 100000)",
        (
            "trade-forged-receipt",
            FILLED_AT,
            ASSET,
            hashlib.sha256(b"forged-receive").hexdigest(),
        ),
    )
    forged_fill_id = int(cursor.lastrowid)
    values = (
        forged_fill_id,
        str(unrelated["evidence_sha256"]),
        str(unrelated["event_id"]),
        str(unrelated["intent_id"]),
        "trade-forged-receipt",
        "buy",
        "0.001",
        "0.1",
        "100",
        ASSET,
        "inner",
        FILLED_AT,
        0,
        77,
        hashlib.sha256(b"forged-receive").hexdigest(),
        100_000,
        "forged-transaction",
        None,
        str(unrelated["evidence_sha256"]),
        str(unrelated["created_at"]),
    )
    with pytest.raises(sqlite3.IntegrityError, match="terminal fill proof"):
        conn.execute(
            "INSERT INTO authoritative_fill_receipts ("
            + ", ".join(database._AUTHORITATIVE_FILL_RECEIPT_COLUMNS)
            + ") VALUES ("
            + ", ".join("?" for _column in database._AUTHORITATIVE_FILL_RECEIPT_COLUMNS)
            + ")",
            values,
        )

    conn.rollback()
    assert database.get_fills(ASSET) == [
        row for row in database.get_fills(ASSET) if row["fill_id"] == proven["fill_id"]
    ]


@pytest.mark.parametrize("contradiction", ["event", "token", "intent", "outcome"])
def test_direct_receipt_insert_rejects_changed_proof_identity(
    isolated_database, contradiction
):
    result, proof = _seed_authoritative_fill(suffix=f"direct-{contradiction}")
    other, _other_proof = _seed_authoritative_fill(
        suffix=f"direct-{contradiction}-other"
    )
    conn = database.get_connection()
    receipt = _delete_authoritative_receipt_for_test(conn, result["fill_id"])
    other_receipt = conn.execute(
        "SELECT * FROM authoritative_fill_receipts WHERE fill_id=?",
        (other["fill_id"],),
    ).fetchone()

    if contradiction == "event":
        receipt["terminal_event_id"] = conn.execute(
            "SELECT event_id FROM offer_operation_journal "
            "WHERE intent_id=? AND operation_type='CREATE' AND phase='PREPARED'",
            (proof["intent_id"],),
        ).fetchone()[0]
    elif contradiction == "token":
        receipt["authority_token"] = "0" * 64
    elif contradiction == "intent":
        receipt["intent_id"] = str(other_receipt["intent_id"])
    else:
        conn.execute("DROP TRIGGER offer_reconciliation_coin_outcomes_no_delete")
        conn.execute(
            "DELETE FROM offer_reconciliation_coin_outcomes WHERE terminal_event_id=?",
            (receipt["terminal_event_id"],),
        )
        conn.execute(
            """CREATE TRIGGER offer_reconciliation_coin_outcomes_no_delete
            BEFORE DELETE ON offer_reconciliation_coin_outcomes
            BEGIN
                SELECT RAISE(ABORT, 'offer_reconciliation_coin_outcomes is append-only');
            END"""
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="terminal fill proof"):
        conn.execute(
            "INSERT INTO authoritative_fill_receipts ("
            + ", ".join(database._AUTHORITATIVE_FILL_RECEIPT_COLUMNS)
            + ") VALUES ("
            + ", ".join("?" for _column in database._AUTHORITATIVE_FILL_RECEIPT_COLUMNS)
            + ")",
            tuple(
                receipt[name] for name in database._AUTHORITATIVE_FILL_RECEIPT_COLUMNS
            ),
        )
    conn.rollback()
    assert database.get_authoritative_fill_by_id(result["fill_id"]) is None


@pytest.mark.parametrize(
    ("column", "changed"),
    [
        ("price_xch", "0.009"),
        ("size_xch", "0.9"),
        ("size_cat", "900"),
        ("fee_mojos_xch", 999),
    ],
)
def test_receipt_insert_rejects_economics_not_bound_to_terminal_evidence(
    isolated_database, column, changed
):
    result, _proof = _seed_authoritative_fill(suffix=f"forged-{column}")
    conn = database.get_connection()
    receipt = _delete_authoritative_receipt_for_test(conn, result["fill_id"])
    conn.execute(
        f"UPDATE fills SET {column}=? WHERE fill_id=?", (changed, result["fill_id"])
    )
    conn.execute(
        f"UPDATE offers SET {column}=? WHERE trade_id=?",
        (changed, f"trade-forged-{column}"),
    )
    receipt[column] = changed

    with pytest.raises(sqlite3.IntegrityError, match="terminal fill proof"):
        conn.execute(
            "INSERT INTO authoritative_fill_receipts ("
            + ", ".join(database._AUTHORITATIVE_FILL_RECEIPT_COLUMNS)
            + ") VALUES ("
            + ", ".join("?" for _column in database._AUTHORITATIVE_FILL_RECEIPT_COLUMNS)
            + ")",
            tuple(
                receipt[name] for name in database._AUTHORITATIVE_FILL_RECEIPT_COLUMNS
            ),
        )
    conn.rollback()
    assert database.get_fills(ASSET) == []


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
    assert "idx_wallet_effect_claim_coins_coin" in detail
    assert "idx_coin_prep_operations_recovery" in detail
    assert detail.count("VIRTUAL TABLE") == 1
    assert "SCAN prep_source VIRTUAL TABLE INDEX 1:" in detail
    assert database._MAX_FILL_AUTHORITY_CLOSURE_ROWS == 4096
    source = inspect.getsource(database._migrate_fill_authority_closure)
    assert source.count("_MAX_FILL_AUTHORITY_CLOSURE_ROWS + 1") >= 2
    assert "selected_count > _MAX_FILL_AUTHORITY_CLOSURE_ROWS" in source


def test_wallet_effect_claim_root_materializes_exact_indexed_coin_cohort(
    active_wallet_effect_runtime,
    monkeypatch,
):
    runtime, _clock, _wallet_hash = active_wallet_effect_runtime
    source_id = hashlib.sha256(b"claim-trigger-source").hexdigest()
    fee_id = hashlib.sha256(b"claim-trigger-fee").hexdigest()
    assert database.upsert_coin(source_id, "xch", 1000, tier="none")
    assert database.upsert_coin(fee_id, "xch", 1000, tier="none")
    claim = database.claim_wallet_effect(
        operation_id="claim-trigger-materialization",
        source_coin_ids=[source_id],
        fee_coin_ids=[fee_id],
    )
    assert claim is not None

    rows = (
        database.get_connection()
        .execute(
            "SELECT coin_id, role FROM wallet_effect_claim_coins "
            "WHERE claim_token=? ORDER BY coin_id",
            (claim["claim_token"],),
        )
        .fetchall()
    )
    assert [(row["coin_id"], row["role"]) for row in rows] == [
        (coin_id, "source" if coin_id in set(claim["source_coin_ids"]) else "fee")
        for coin_id in claim["cohort_coin_ids"]
    ]
    dispatch = database.begin_wallet_effect_dispatch(
        claim["claim_token"],
        claim["generation"],
        operation_id=claim["operation_id"],
        source_coin_ids=[source_id],
        fee_coin_ids=[fee_id],
    )
    assert dispatch is not None
    with database.wallet_effect_adapter_dispatch_authority(dispatch):
        no_effect_result = _wallet_effect_real_facade_result(
            runtime, monkeypatch, attempted=False
        )
    assert (
        database.complete_wallet_effect_dispatch(
            dispatch,
            result=no_effect_result,
        )
        == "RELEASED_NO_EFFECT"
    )


def test_persisted_wallet_authority_marker_cannot_release_effect_claim(
    active_wallet_effect_runtime,
):
    source_coin_id = hashlib.sha256(b"persisted-marker-forgery").hexdigest()
    assert database.upsert_coin(source_coin_id, "xch", 1000, tier="none")
    claim = database.claim_wallet_effect(
        operation_id="coin_manager.split_sage",
        source_coin_ids=[source_coin_id],
    )
    assert claim is not None
    dispatch = database.begin_wallet_effect_dispatch(
        claim["claim_token"],
        claim["generation"],
        operation_id=claim["operation_id"],
        source_coin_ids=[source_coin_id],
    )
    assert dispatch is not None

    # Every field below is reconstructed from durable rows.  No caller-authored
    # serialization may prove that the wallet facade returned before an effect.
    forged = _wallet_effect_result_marker(claim["claim_token"], attempted=False)
    assert (
        database.complete_wallet_effect_dispatch(dispatch, result=forged) == "UNKNOWN"
    )
    assert (
        database.get_connection()
        .execute(
            "SELECT outcome FROM wallet_effect_claim_resolutions WHERE claim_token=?",
            (claim["claim_token"],),
        )
        .fetchone()[0]
        == "UNKNOWN"
    )


def test_wallet_facade_attestation_issuer_is_not_retrievable_after_bootstrap(
    active_wallet_effect_runtime,
):
    import wallet  # noqa: F401 - importing consumes the one-shot bootstrap

    source_coin_id = hashlib.sha256(b"facade-issuer-bootstrap").hexdigest()
    assert database.upsert_coin(source_coin_id, "xch", 1000, tier="none")
    claim = database.claim_wallet_effect(
        operation_id="coin_manager.split_sage",
        source_coin_ids=[source_coin_id],
    )
    assert claim is not None
    dispatch = database.begin_wallet_effect_dispatch(
        claim["claim_token"],
        claim["generation"],
        operation_id=claim["operation_id"],
        source_coin_ids=[source_coin_id],
    )
    assert dispatch is not None
    durable_authority = json.loads(
        database.get_connection()
        .execute(
            "SELECT authority_json FROM wallet_effect_claim_authorities "
            "WHERE claim_token=?",
            (claim["claim_token"],),
        )
        .fetchone()[0]
    )

    recovered_issuer = database._take_wallet_effect_adapter_facade_authority()
    assert recovered_issuer is None
    with database.wallet_effect_adapter_dispatch_authority(dispatch):
        forged_attestation = database._issue_wallet_effect_adapter_outcome_attestation(
            recovered_issuer,
            wallet_operation="wallet:forged_callback",
            wallet_authority=durable_authority,
            effect_attempted=False,
        )
    assert forged_attestation is None
    assert (
        database.complete_wallet_effect_dispatch(
            dispatch,
            result={
                "success": False,
                "_catalyst_effect_attempted": False,
                "_catalyst_wallet_effect_attestation": forged_attestation,
            },
        )
        == "UNKNOWN"
    )


def test_opaque_wallet_outcome_attestation_is_bound_to_exact_dispatch(
    active_wallet_effect_runtime,
    monkeypatch,
):
    runtime, _clock, _wallet_hash = active_wallet_effect_runtime
    dispatches = []
    for index in range(2):
        coin_id = hashlib.sha256(f"opaque-replay-{index}".encode()).hexdigest()
        assert database.upsert_coin(coin_id, "xch", 1000, tier="none")
        claim = database.claim_wallet_effect(
            operation_id="coin_manager.split_sage",
            source_coin_ids=[coin_id],
        )
        assert claim is not None
        dispatch = database.begin_wallet_effect_dispatch(
            claim["claim_token"],
            claim["generation"],
            operation_id=claim["operation_id"],
            source_coin_ids=[coin_id],
        )
        assert dispatch is not None
        dispatches.append(dispatch)

    with database.wallet_effect_adapter_dispatch_authority(dispatches[0]):
        original = _wallet_effect_real_facade_result(
            runtime, monkeypatch, attempted=False
        )
    wrong_dispatch_copy = dict(original)

    assert (
        database.complete_wallet_effect_dispatch(
            dispatches[1], result=wrong_dispatch_copy
        )
        == "UNKNOWN"
    )


def test_opaque_wallet_outcome_attestation_is_consumed_exactly_once(
    active_wallet_effect_runtime,
    monkeypatch,
):
    runtime, _clock, _wallet_hash = active_wallet_effect_runtime
    dispatches = []
    for index in range(2):
        coin_id = hashlib.sha256(f"opaque-single-use-{index}".encode()).hexdigest()
        assert database.upsert_coin(coin_id, "xch", 1000, tier="none")
        claim = database.claim_wallet_effect(
            operation_id="coin_manager.split_sage",
            source_coin_ids=[coin_id],
        )
        assert claim is not None
        dispatch = database.begin_wallet_effect_dispatch(
            claim["claim_token"],
            claim["generation"],
            operation_id=claim["operation_id"],
            source_coin_ids=[coin_id],
        )
        assert dispatch is not None
        dispatches.append(dispatch)

    with database.wallet_effect_adapter_dispatch_authority(dispatches[0]):
        original = _wallet_effect_real_facade_result(
            runtime, monkeypatch, attempted=False
        )
    with pytest.raises(AttributeError):
        original["_catalyst_wallet_effect_attestation"].effect_attempted = True
    valid_copy = dict(original)
    consumed_replay = dict(original)

    assert (
        database.complete_wallet_effect_dispatch(dispatches[0], result=valid_copy)
        == "RELEASED_NO_EFFECT"
    )
    assert (
        database.complete_wallet_effect_dispatch(dispatches[1], result=consumed_replay)
        == "UNKNOWN"
    )
    with pytest.raises(ValueError, match="not current"):
        database.complete_wallet_effect_dispatch(dispatches[0], result=original)


def test_real_wallet_facade_pre_effect_block_emits_releasable_attestation(
    active_wallet_effect_runtime,
    monkeypatch,
):
    import coin_manager
    import mutation_gate
    import wallet

    runtime, _clock, _wallet_hash = active_wallet_effect_runtime
    source_coin_id = hashlib.sha256(b"wallet-facade-pre-effect-block").hexdigest()
    assert database.upsert_coin(source_coin_id, "xch", 1000, tier="none")
    monkeypatch.setattr(wallet, "_wallet_adapter", runtime._wallet_adapter_authority)

    def blocked_identity(_adapter):
        raise mutation_gate.MutationBlocked(
            "WALLET_IDENTITY_CHANGED", "wallet:split_coins_rpc"
        )

    monkeypatch.setattr(wallet, "_identity_from_adapter", blocked_identity)
    result = coin_manager._run_claimed_wallet_effect(
        "coin_manager.split_sage",
        lambda: wallet._run_wallet_mutation("split_coins_rpc"),
        source_coin_ids=[source_coin_id],
    )

    assert result["success"] is False
    assert result["_catalyst_effect_attempted"] is False
    assert "_catalyst_wallet_effect_attestation" not in result
    assert (
        database.get_connection()
        .execute("SELECT outcome FROM wallet_effect_claim_resolutions")
        .fetchone()[0]
        == "RELEASED_NO_EFFECT"
    )


def test_real_wallet_facade_post_effect_exception_remains_fenced_unknown(
    active_wallet_effect_runtime,
    monkeypatch,
):
    import coin_manager
    import mutation_gate
    import wallet

    runtime, _clock, _wallet_hash = active_wallet_effect_runtime
    adapter = runtime._wallet_adapter_authority
    source_coin_id = hashlib.sha256(b"wallet-facade-post-effect-error").hexdigest()
    assert database.upsert_coin(source_coin_id, "xch", 1000, tier="none")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_identity_from_adapter", lambda _adapter: {})
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda _binding, _snapshot, _operation: None,
    )

    def backend_error():
        raise RuntimeError("adapter outcome lost after effect boundary")

    monkeypatch.setattr(adapter, "test_effect_adapter", backend_error, raising=False)
    result = coin_manager._run_claimed_wallet_effect(
        "coin_manager.split_sage",
        lambda: wallet._run_wallet_mutation("test_effect_adapter"),
        source_coin_ids=[source_coin_id],
    )

    assert result["success"] is False
    assert result["_catalyst_effect_attempted"] is True
    assert "_catalyst_wallet_effect_attestation" not in result
    assert (
        database.get_connection()
        .execute("SELECT outcome FROM wallet_effect_claim_resolutions")
        .fetchone()[0]
        == "UNKNOWN"
    )


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
    conn.execute("DROP TRIGGER offer_reconciliation_coin_outcomes_proof_guard_v2")
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
    audit_codes = {
        row["reason_code"]
        for row in conn.execute(
            "SELECT reason_code FROM offer_authority_migration_audit "
            "WHERE authority_type='coin' AND subject_id=?",
            (coin_id,),
        ).fetchall()
    }
    assert "MALFORMED_COIN_OUTCOME_QUARANTINED" in audit_codes
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


def test_wallet_effect_authority_rejects_spent_coin_without_mutable_projection(
    isolated_database,
):
    _result, proof = _seed_authoritative_fill(suffix="effect-authority")
    spent_coin_id = proof["coin_id"]
    safe_coin_id = database.norm_coin_id(hashlib.sha256(b"safe-effect").hexdigest())
    assert database.upsert_coin(
        safe_coin_id,
        "xch",
        200_000_000_000,
        designation="reserve",
        tier="none",
    )
    conn = database.get_connection()
    conn.execute("DELETE FROM coins WHERE coin_id=?", (spent_coin_id,))
    conn.commit()

    assert database.authorize_wallet_effect_coin_ids([spent_coin_id]) is None
    assert database.authorize_wallet_effect_coin_ids([safe_coin_id]) == [safe_coin_id]
    assert (
        database.authorize_wallet_effect_coin_ids([safe_coin_id, spent_coin_id]) is None
    )


def test_coin_manager_combine_rechecks_authority_before_wallet_effect(
    isolated_database, monkeypatch
):
    import coin_manager
    import wallet

    _result, proof = _seed_authoritative_fill(suffix="manager-effect-race")
    safe_coin_id = database.norm_coin_id(
        hashlib.sha256(b"manager-safe-effect").hexdigest()
    )
    assert database.upsert_coin(
        safe_coin_id, "xch", 200_000_000_000, designation="reserve", tier="none"
    )
    effect_calls: list[list[str]] = []

    def fake_combine(*, coin_ids, fee_mojos):
        del fee_mojos
        effect_calls.append(list(coin_ids))
        return {"success": True, "transaction_id": "manager-effect"}

    manager = object.__new__(coin_manager.CoinManager)
    manager._tx_fee_mojos = lambda: 0
    manager._filter_out_protected_coin_ids = lambda coin_ids: list(coin_ids)
    manager._extract_sage_transaction_ids = lambda _result: ["manager-effect"]
    monkeypatch.setattr(coin_manager, "get_wallet_type", lambda: "sage")
    monkeypatch.setattr(wallet, "combine_coins", fake_combine)

    assert not manager._consolidate_coins(
        "XCH",
        1,
        300_000_000_000,
        False,
        source_coin_ids=[safe_coin_id, proof["coin_id"]],
    )
    assert effect_calls == []


def test_coin_manager_split_rechecks_authority_before_wallet_effect(
    isolated_database, monkeypatch
):
    import coin_manager

    _result, proof = _seed_authoritative_fill(suffix="manager-split-race")
    effect_calls: list[str] = []
    manager = object.__new__(coin_manager.CoinManager)
    monkeypatch.setattr(coin_manager, "_get_free_coins_rpc", lambda _wallet_id: {})
    monkeypatch.setattr(coin_manager, "get_wallet_type", lambda: "sage")
    monkeypatch.setattr(
        coin_manager,
        "split_coins_rpc",
        lambda **_kwargs: effect_calls.append("split") or {"success": True},
    )

    assert not manager._split_via_cli(
        1, proof["coin_id"], 2, Decimal("0.05"), name="authority-race"
    )
    assert effect_calls == []


def test_coin_manager_topup_rechecks_authority_before_wallet_effect(
    isolated_database, monkeypatch
):
    import coin_manager
    import wallet

    _result, proof = _seed_authoritative_fill(suffix="manager-topup-race")
    effect_calls: list[str] = []
    manager = object.__new__(coin_manager.CoinManager)
    manager._topup_should_stop = lambda: False
    manager._get_owned_coin_amount_map = lambda *_args, **_kwargs: {}
    manager._coinset_topup_split_state = lambda **_kwargs: None
    manager._tx_fee_mojos = lambda: 0
    monkeypatch.setattr(
        coin_manager,
        "get_next_address",
        lambda **_kwargs: {"success": True, "address": "xch1authority"},
    )
    monkeypatch.setattr(
        wallet,
        "sage_topup_split",
        lambda **_kwargs: effect_calls.append("topup") or {"success": True},
    )

    assert not manager._sage_one_step_split(
        "XCH",
        1,
        proof["coin_id"],
        num_to_create=2,
        trading_size_mojos=1_000,
        is_cat=False,
    )
    assert effect_calls == []


def test_coin_manager_absorb_rechecks_entire_cohort_before_wallet_effect(
    isolated_database, monkeypatch
):
    import coin_manager
    import wallet

    _result, proof = _seed_authoritative_fill(suffix="manager-absorb-race")
    reserve_id = database.norm_coin_id(hashlib.sha256(b"absorb-reserve").hexdigest())
    assert database.upsert_coin(
        reserve_id, "xch", 200_000, designation="reserve", tier="none"
    )
    effect_calls: list[list[str]] = []
    manager = object.__new__(coin_manager.CoinManager)
    manager._get_coin_prep_headroom_multiplier = lambda: Decimal("1")
    manager._tx_fee_mojos = lambda: 0
    manager._filter_out_protected_coin_ids = lambda coin_ids: list(coin_ids)
    manager._recent_absorb_submissions = {}
    monkeypatch.setattr(coin_manager, "get_wallet_type", lambda: "sage")
    monkeypatch.setattr(
        coin_manager,
        "_get_free_coins_rpc",
        lambda _wallet_id: {
            "confirmed_records": [
                {"coin_id": reserve_id, "amount": 200_000},
                {"coin_id": proof["coin_id"], "amount": 100_000},
            ]
        },
    )
    monkeypatch.setattr(
        wallet,
        "combine_coins",
        lambda *, coin_ids, fee_mojos: (
            effect_calls.append(list(coin_ids)) or {"success": True}
        ),
    )

    assert not manager._absorb_misfits_to_reserve(
        "XCH",
        1,
        {
            "reserve": [{"coin_id": reserve_id, "amount": 200_000}],
            "small": [{"coin_id": proof["coin_id"], "amount": 100_000}],
        },
        {"inner": 50_000},
        is_cat=False,
    )
    assert effect_calls == []


def test_coin_prep_worker_combine_rechecks_authority_before_wallet_effect(
    isolated_database, monkeypatch
):
    import coin_prep_worker
    import wallet

    _result, proof = _seed_authoritative_fill(suffix="worker-effect-race")
    safe_coin_id = database.norm_coin_id(
        hashlib.sha256(b"worker-safe-effect").hexdigest()
    )
    assert database.upsert_coin(
        safe_coin_id, "xch", 200_000_000_000, designation="reserve", tier="none"
    )
    effect_calls: list[list[str]] = []

    def fake_combine(*, coin_ids, fee_mojos):
        del fee_mojos
        effect_calls.append(list(coin_ids))
        return {"success": True, "transaction_id": "worker-effect"}

    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._is_subprocess = False
    worker.log = lambda _message: None
    worker._sage_consolidation_max_inputs_per_tx = lambda: 100
    worker._priority_combine_fee_mojos = lambda _count: 0
    worker._sage_submit_succeeded = lambda result: bool(result)
    worker._consolidate_wallet_sage_fallback = lambda _wallet_id, _name: False
    monkeypatch.setattr(
        wallet,
        "get_spendable_coins_rpc",
        lambda _wallet_id: {
            "success": True,
            "confirmed_records": [
                {"coin_id": safe_coin_id, "spent_block_index": 0},
                {"coin_id": proof["coin_id"], "spent_block_index": 0},
            ],
        },
    )
    monkeypatch.setattr(wallet, "combine_coins", fake_combine)

    assert not worker._consolidate_wallet_sage_combine(1, "XCH")
    assert effect_calls == []


def test_coin_prep_worker_split_rechecks_authority_before_wallet_effect(
    isolated_database,
):
    import coin_prep_worker

    _result, proof = _seed_authoritative_fill(suffix="worker-split-race")
    effect_calls: list[str] = []
    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._is_subprocess = False
    worker.log = lambda _message: None

    result = worker._call_wallet_mutation(
        "coin_prep.split_single_sage",
        lambda **_kwargs: effect_calls.append("split") or {"success": True},
        target_coin_id=proof["coin_id"],
    )

    assert result is None
    assert effect_calls == []


def test_coin_prep_worker_send_to_self_consolidate_rechecks_exact_cohort(
    isolated_database,
):
    import coin_prep_worker

    _result, proof = _seed_authoritative_fill(suffix="worker-consolidate-race")
    safe_coin_id = database.norm_coin_id(
        hashlib.sha256(b"worker-consolidate-safe").hexdigest()
    )
    assert database.upsert_coin(
        safe_coin_id, "xch", 200_000_000_000, designation="reserve", tier="none"
    )
    effect_calls: list[list[str]] = []

    def fake_send(*, source_coin_ids):
        effect_calls.append(list(source_coin_ids))
        return {"success": True}

    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._is_subprocess = False
    worker.log = lambda _message: None

    result = worker._call_wallet_mutation(
        "coin_prep.consolidate_balance",
        fake_send,
        source_coin_ids=[safe_coin_id, proof["coin_id"]],
    )

    assert result is None
    assert effect_calls == []


def test_classification_ack_cannot_rebind_authoritative_receipt_height(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(suffix="classification-height")
    fill_id = result["fill_id"]
    claim = database.claim_offer_fill_hook(fill_id, "fill_classification")
    assert claim["status"] == "claimed"

    with pytest.raises(ValueError, match="receipt height"):
        database.store_authoritative_fill_classification_ack(
            fill_id,
            {
                "classification": "dexie_combined",
                "spent_block_index": 999,
                "taker_puzzle_hash": None,
                "sweep_group_id": "sweep_999",
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )

    stored = database.get_fill_by_id(fill_id)
    assert stored["spent_block_index"] == 42
    assert stored["spent_block_height"] == 42


def test_post_fill_claim_and_callback_block_when_fill_authority_is_tampered(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(suffix="post-fill-tamper")
    fill_id = result["fill_id"]
    claimed = database.claim_offer_fill_hook(fill_id, "fill_classification")
    assert claimed["status"] == "claimed"
    conn = database.get_connection()
    conn.execute("UPDATE fills SET tier='outer' WHERE fill_id=?", (fill_id,))
    conn.commit()

    with pytest.raises(ValueError, match="authority"):
        database.store_authoritative_fill_classification_ack(
            fill_id,
            {
                "classification": "dexie_combined",
                "spent_block_index": 42,
                "taker_puzzle_hash": None,
                "sweep_group_id": "sweep_42",
            },
            claim_token=claimed["claim_token"],
            claim_generation=claimed["claim_generation"],
        )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_hook_delivery_acks WHERE fill_id=?",
            (fill_id,),
        ).fetchone()[0]
        == 0
    )

    blocked = database.claim_offer_fill_hook(fill_id, "sweep_registration")
    assert blocked["status"] == "blocked"
    outbox = conn.execute(
        "SELECT state, last_error_code FROM offer_fill_hook_outbox "
        "WHERE fill_id=? AND hook_name='sweep_registration'",
        (fill_id,),
    ).fetchone()
    assert outbox["state"] == "pending"
    assert outbox["last_error_code"] == "AUTHORITATIVE_FILL_PROOF_LOST"


def test_outbox_selection_durably_blocks_tampered_fill_authority(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(suffix="outbox-select-tamper")
    fill_id = result["fill_id"]
    conn = database.get_connection()
    conn.execute("UPDATE fills SET tier='outer' WHERE fill_id=?", (fill_id,))
    conn.commit()

    assert fill_id not in database.get_offer_fill_hook_outbox_work()
    blocked = conn.execute(
        "SELECT COUNT(*) FROM offer_fill_hook_outbox "
        "WHERE fill_id=? AND state='pending' "
        "AND last_error_code='AUTHORITATIVE_FILL_PROOF_LOST'",
        (fill_id,),
    ).fetchone()[0]
    assert blocked == len(database._AUTHORITATIVE_FILL_HOOKS)
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert latch["reason_code"] == "AUTHORITATIVE_FILL_PROOF_LOST"


def test_post_fill_ack_cannot_complete_after_authority_changes(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(suffix="post-fill-ack-race")
    fill_id = result["fill_id"]
    claim = database.claim_offer_fill_hook(fill_id, "boost_notification")
    acknowledgement = database.record_offer_fill_hook_sink_ack(
        fill_id,
        "boost_notification",
        {"trade_id": "trade-post-fill-ack-race", "applicable": False},
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    conn = database.get_connection()
    conn.execute("UPDATE fills SET tier='outer' WHERE fill_id=?", (fill_id,))
    conn.commit()

    assert not database.validate_offer_fill_hook_sink_ack(
        fill_id,
        "boost_notification",
        acknowledgement,
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    with pytest.raises(ValueError, match="authority"):
        database.complete_offer_fill_hook(
            fill_id,
            "boost_notification",
            claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    outbox = conn.execute(
        "SELECT state, last_error_code FROM offer_fill_hook_outbox "
        "WHERE fill_id=? AND hook_name='boost_notification'",
        (fill_id,),
    ).fetchone()
    assert tuple(outbox) == ("pending", "AUTHORITATIVE_FILL_PROOF_LOST")
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_boost_registration_persists_exact_fill_authority_binding(
    isolated_database,
):
    result, proof = _seed_authoritative_fill(
        suffix="boost-authority-binding", tier="boost"
    )
    fill_id = result["fill_id"]
    claim = database.claim_offer_fill_hook(fill_id, "boost_notification")
    command = database.register_authoritative_boost_fill_command(
        fill_id,
        "trade-boost-authority-binding",
        "buy",
        materialization={
            "schema_version": 1,
            "fill_id": fill_id,
            "trade_id": "trade-boost-authority-binding",
            "side": "buy",
            "probe_trade_id": "trade-boost-authority-binding",
            "probe_matched": True,
            "settled_before": False,
            "offset_bps": 25,
            "floor_bps": 25,
            "last_safe_offset_bps": 20,
        },
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    receipt = (
        database.get_connection()
        .execute(
            "SELECT authority_token FROM authoritative_fill_receipts WHERE fill_id=?",
            (fill_id,),
        )
        .fetchone()
    )

    assert command["materialization"]["schema_version"] == 2
    assert command["materialization"]["authority_token"] == receipt["authority_token"]
    assert command["materialization"]["tier"] == "boost"
    assert command["materialization"]["spent_block_height"] == 42
    assert proof["block_height"] == 42


def test_sweep_registration_rejects_classification_height_rebinding(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(suffix="sweep-height-binding")
    fill_id = result["fill_id"]
    claim = database.claim_offer_fill_hook(fill_id, "sweep_registration")

    with pytest.raises(ValueError, match="receipt height"):
        database.register_authoritative_sweep_fill(
            fill_id,
            {
                "trade_id": "trade-sweep-height-binding",
                "classification": "dexie_combined",
                "spent_block_index": 999,
                "taker_puzzle_hash": None,
                "sweep_group_id": "sweep_999",
                "side": "buy",
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )


def test_round_trip_pnl_requires_canonical_authoritative_receipts_and_fees(
    isolated_database,
):
    buy, _buy_proof = _seed_authoritative_fill(
        suffix="round-trip-buy",
        side="buy",
        price_xch=Decimal("0.001"),
        size_xch=Decimal("0.1"),
        size_cat=Decimal("100"),
        fee_mojos_xch=7,
        filled_at="2026-08-20T12:00:01.000000Z",
    )
    sell, _sell_proof = _seed_authoritative_fill(
        suffix="round-trip-sell",
        side="sell",
        price_xch=Decimal("0.0012"),
        size_xch=Decimal("0.12"),
        size_cat=Decimal("100"),
        fee_mojos_xch=11,
        filled_at="2026-08-20T12:00:03.000000Z",
        reconciled_at="2026-08-20T12:00:05.000000Z",
    )
    expected = Decimal("0.019999999982")
    conn = database.get_connection()
    receipts = {
        row["fill_id"]: row
        for row in conn.execute(
            "SELECT fill_id, authority_token FROM authoritative_fill_receipts "
            "WHERE fill_id IN (?, ?)",
            (buy["fill_id"], sell["fill_id"]),
        ).fetchall()
    }

    with pytest.raises(sqlite3.IntegrityError, match="round-trip"):
        conn.execute(
            "INSERT INTO authoritative_round_trip_receipts "
            "(round_trip_id, buy_fill_id, sell_fill_id, buy_authority_token, "
            " sell_authority_token, authority_token, realised_pnl_xch, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                buy["fill_id"],
                buy["fill_id"],
                sell["fill_id"],
                receipts[buy["fill_id"]]["authority_token"],
                receipts[sell["fill_id"]]["authority_token"],
                "0" * 64,
                "999",
                AFTER,
            ),
        )
    conn.rollback()

    assert (
        database.match_round_trip(buy["fill_id"], sell["fill_id"], Decimal("999")) == -1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM authoritative_round_trip_receipts"
        ).fetchone()[0]
        == 0
    )

    round_trip_id = database.match_round_trip(buy["fill_id"], sell["fill_id"], expected)
    assert round_trip_id == buy["fill_id"]
    receipt = conn.execute(
        "SELECT * FROM authoritative_round_trip_receipts WHERE round_trip_id=?",
        (round_trip_id,),
    ).fetchone()
    assert Decimal(receipt["realised_pnl_xch"]) == expected
    assert receipt["buy_authority_token"] == receipts[buy["fill_id"]]["authority_token"]
    assert (
        receipt["sell_authority_token"] == receipts[sell["fill_id"]]["authority_token"]
    )

    conn.execute(
        "UPDATE fills SET pnl_xch='877' WHERE fill_id IN (?, ?)",
        (buy["fill_id"], sell["fill_id"]),
    )
    conn.commit()
    stats = database.get_stats(ASSET)
    assert Decimal(stats["realised_pnl_xch"]) == expected
    assert stats["round_trips"] == 1
    assert stats["win_rate"] == 100.0


def test_round_trip_authority_rejects_changed_replay_and_wrong_order(
    isolated_database,
):
    buy, _buy_proof = _seed_authoritative_fill(
        suffix="round-trip-replay-buy",
        side="buy",
        filled_at="2026-08-20T12:00:03.000000Z",
        reconciled_at="2026-08-20T12:00:05.000000Z",
    )
    sell, _sell_proof = _seed_authoritative_fill(
        suffix="round-trip-replay-sell",
        side="sell",
        size_xch=Decimal("0.11"),
        filled_at="2026-08-20T12:00:02.000000Z",
    )

    assert (
        database.match_round_trip(
            buy["fill_id"], sell["fill_id"], Decimal("0.009999999986")
        )
        == -1
    )
    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM authoritative_round_trip_receipts"
        ).fetchone()[0]
        == 0
    )

    conn.execute(
        "UPDATE fills SET filled_at='2026-08-20T12:00:04.000000Z' WHERE fill_id=?",
        (sell["fill_id"],),
    )
    conn.commit()
    # Mutable timestamp repair cannot re-authorize a receipt whose immutable
    # timestamp remains earlier than the buy leg.
    assert (
        database.match_round_trip(
            buy["fill_id"], sell["fill_id"], Decimal("0.009999999986")
        )
        == -1
    )


def test_round_trip_authority_is_atomic_under_exact_replay_race(
    isolated_database,
):
    buy, _buy_proof = _seed_authoritative_fill(
        suffix="round-trip-race-buy",
        side="buy",
        filled_at="2026-08-20T12:00:01.000000Z",
    )
    sell, _sell_proof = _seed_authoritative_fill(
        suffix="round-trip-race-sell",
        side="sell",
        size_xch=Decimal("0.11"),
        filled_at="2026-08-20T12:00:03.000000Z",
        reconciled_at="2026-08-20T12:00:05.000000Z",
    )
    expected = Decimal("0.009999999986")
    barrier = threading.Barrier(2)
    results: list[int] = []

    def match() -> None:
        barrier.wait(timeout=5)
        results.append(
            database.match_round_trip(buy["fill_id"], sell["fill_id"], expected)
        )
        database.close_connection()

    workers = [threading.Thread(target=match) for _index in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert all(not worker.is_alive() for worker in workers)
    assert sorted(results) == [buy["fill_id"], buy["fill_id"]]
    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM authoritative_round_trip_receipts"
        ).fetchone()[0]
        == 1
    )


def test_market_position_uses_authoritative_receipts_not_legacy_inventory(
    isolated_database,
):
    _seed_authoritative_fill(
        suffix="market-position-authority", size_cat=Decimal("100")
    )
    assert database.record_inventory_snapshot(ASSET, Decimal("877"))

    history = market_data_collector._fetch_internal_db_history(ASSET)
    analysis = market_data_collector._analyze_bot_performance({"internal_db": history})

    assert Decimal(str(history["latest_net_position"])) == Decimal("100")
    assert history["latest_legacy_net_position"] == 877.0
    assert history["inventory_position_authority"] == "authoritative_fill_receipts"
    assert analysis["inventory_drift"] == "long_cat"


def test_new_migration_audits_receipts_forged_under_prior_watermark(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(suffix="prior-watermark-forgery")
    fill_id = result["fill_id"]
    conn = database.get_connection()
    receipt = dict(
        conn.execute(
            "SELECT * FROM authoritative_fill_receipts WHERE fill_id=?", (fill_id,)
        ).fetchone()
    )
    conn.execute("DROP TRIGGER authoritative_fill_receipts_no_delete")
    conn.execute("DROP TRIGGER authoritative_fill_receipts_proof_guard")
    conn.execute("DELETE FROM authoritative_fill_receipts WHERE fill_id=?", (fill_id,))
    receipt["authority_token"] = "b" * 64
    columns = tuple(receipt)
    conn.execute(
        f"INSERT INTO authoritative_fill_receipts ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _column in columns)})",
        tuple(receipt[column] for column in columns),
    )
    conn.commit()
    _clear_fill_authority_closure_watermark(conn)
    conn.execute(
        "INSERT INTO stability_migration_watermarks "
        "(migration_key, schema_version, policy_sha256, completed_at) "
        "VALUES ('task9-fill-authority-closure', 1, ?, ?)",
        (
            hashlib.sha256(
                b"task9-fill-authority-closure:v1:receipt-permanent-spend-dominance"
            ).hexdigest(),
            AT,
        ),
    )
    conn.commit()
    database.close_connection()
    database._db_initialized_path = ""

    database.init_database()

    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT verification_status FROM fills WHERE fill_id=?", (fill_id,)
        ).fetchone()[0]
        == "legacy_unproven_filled"
    )
    assert database.get_fills(cat_asset_id=ASSET) == []
    audit = conn.execute(
        "SELECT reason_code FROM offer_authority_migration_audit "
        "WHERE authority_type='fill' AND subject_id=?",
        (str(fill_id),),
    ).fetchone()
    assert audit["reason_code"] == "UNPROVEN_ECONOMIC_FILL_DEMOTED"


def test_post_fill_callback_reload_blocks_demotion_after_claim(
    isolated_database, monkeypatch
):
    result, _proof = _seed_authoritative_fill(suffix="callback-reload-race")
    fill_id = result["fill_id"]
    original_claim = database.claim_offer_fill_hook
    tampered = False

    def claim_then_demote(claim_fill_id, hook_name):
        nonlocal tampered
        claim = original_claim(claim_fill_id, hook_name)
        if claim["status"] == "claimed" and not tampered:
            tampered = True
            conn = database.get_connection()
            conn.execute("UPDATE fills SET tier='mid' WHERE fill_id=?", (fill_id,))
            conn.commit()
        return claim

    calls: list[str] = []

    def callbacks(_fill):
        return {
            name: (
                lambda _row, *, claim_token, claim_generation, name=name: (
                    calls.append(name) or {}
                )
            )
            for name in database._AUTHORITATIVE_FILL_HOOKS
        }

    monkeypatch.setattr(database, "claim_offer_fill_hook", claim_then_demote)
    monkeypatch.setattr(offer_reconciliation, "_post_fill_hook_callbacks", callbacks)

    statuses = offer_reconciliation._run_post_fill_hooks(
        database.get_fill_by_id(fill_id), completed_at=FILLED_AT
    )

    assert calls == []
    assert "blocked" in statuses.values()
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_worker_denies_auto_selected_source_and_fee_inputs(
    isolated_database,
):
    import coin_prep_worker

    source_coin_id = hashlib.sha256(b"explicit-worker-source").hexdigest()
    assert database.upsert_coin(
        source_coin_id,
        "xch",
        200_000,
        designation="reserve",
        tier="none",
        purpose="lifecycle",
    )
    calls: list[str] = []
    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._is_subprocess = False
    worker.log = lambda _message: None

    pool = worker._call_wallet_mutation(
        "coin_prep.create_pool",
        lambda *_args, **_kwargs: calls.append("auto-source") or {"success": True},
        1,
        100_000,
        "xch1authority",
        fee_mojos=0,
    )
    split = worker._call_wallet_mutation(
        "coin_prep.split_single_sage",
        lambda **_kwargs: calls.append("auto-fee") or {"success": True},
        target_coin_id=source_coin_id,
        fee_mojos=1,
    )
    ignored_source = worker._call_wallet_mutation(
        "coin_prep.consolidate_balance",
        lambda **_kwargs: calls.append("ignored-source") or {"success": True},
        wallet_id=1,
        amount_mojos=100_000,
        address="xch1authority",
        fee_mojos=0,
        source_coin_ids=[source_coin_id],
    )

    assert pool is None
    assert split is None
    assert ignored_source is None
    assert calls == []


def test_worker_binds_xch_combine_fee_to_the_exact_source_cohort(
    isolated_database,
    monkeypatch,
):
    import coin_prep_worker
    import replacement_capacity

    source_coin_ids = [
        hashlib.sha256(b"worker-combine-source-one").hexdigest(),
        hashlib.sha256(b"worker-combine-source-two").hexdigest(),
    ]
    target_contract = {
        "wallet_type": "xch",
        "outputs": [
            {
                "output_index": 0,
                "amount_mojos": 399_999,
                "purpose": "top_up",
            }
        ],
    }
    prep_contract = {
        "operation_kind": "combine",
        "purpose": "top_up",
        "target_contract": target_contract,
        "pre_view_coin_ids": source_coin_ids,
    }
    canonical_prep = replacement_capacity.canonical_coin_prep_contract(
        operation_kind="combine",
        purpose="top_up",
        source_coin_ids=source_coin_ids,
        target_contract=target_contract,
    )
    wallet_identity = {"backend": "sage", "fingerprint": 161616161}
    for coin_id in source_coin_ids:
        assert database.upsert_coin(
            coin_id, "xch", 200_000, designation="reserve", tier="none"
        )

    claims: list[dict] = []

    def claim(**kwargs):
        claims.append(kwargs)
        return {"claim_token": "b" * 64, "generation": 1}

    monkeypatch.setattr(coin_prep_worker, "claim_wallet_effect", claim)
    monkeypatch.setattr(
        coin_prep_worker, "wallet_effect_claim_is_current", lambda *_a, **_k: True
    )
    dispatch = object()
    monkeypatch.setattr(
        coin_prep_worker, "begin_wallet_effect_dispatch", lambda *_a, **_k: dispatch
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "wallet_effect_adapter_dispatch_authority",
        lambda capability: nullcontext(capability),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "complete_wallet_effect_dispatch",
        lambda capability, **_kwargs: "SUBMITTED" if capability is dispatch else None,
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "prepare_coin_prep_operation",
        lambda **_kwargs: {
            "operation": {
                "operation_id": canonical_prep["operation_id"],
                "source_coin_ids_json": json.dumps(source_coin_ids),
                "wallet_identity_json": json.dumps(wallet_identity),
                "effect_claim_token": "b" * 64,
                "effect_claim_generation": 1,
            }
        },
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "record_coin_prep_operation_outcome",
        lambda operation_id, **kwargs: {
            "operation": {"operation_id": operation_id, **kwargs}
        },
    )
    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._is_subprocess = False
    worker.log = lambda _message: None
    worker._current_coin_prep_wallet_identity = lambda: wallet_identity
    worker._observe_coin_prep_post_effect = lambda _operation: {
        "expected_outputs": [],
        "authoritative_view": {},
    }
    worker._verify_authoritative_post_operation_view = lambda **_kwargs: True
    calls: list[tuple[list[str], int]] = []

    subset = worker._call_wallet_mutation(
        "coin_prep.combine",
        lambda **_kwargs: calls.append(([], 0)) or {"success": True},
        coin_ids=source_coin_ids,
        fee_mojos=1,
        _authority_fee_coin_ids=source_coin_ids[:1],
        _prep_contract=prep_contract,
    )
    exact = worker._call_wallet_mutation(
        "coin_prep.combine",
        lambda *, coin_ids, fee_mojos: (
            calls.append((coin_ids, fee_mojos)) or {"success": True}
        ),
        coin_ids=source_coin_ids,
        fee_mojos=1,
        _authority_fee_coin_ids=source_coin_ids,
        _prep_contract=prep_contract,
    )

    assert subset is None
    assert exact == {"success": True}
    assert calls == [(source_coin_ids, 1)]
    assert claims == [
        {
            "operation_id": canonical_prep["operation_id"],
            "source_coin_ids": source_coin_ids,
            "fee_coin_ids": source_coin_ids,
        }
    ]


def test_worker_binds_xch_split_fee_to_its_exact_source_coin(
    isolated_database,
    monkeypatch,
):
    import coin_prep_worker
    import replacement_capacity

    source_coin_id = hashlib.sha256(b"worker-xch-split-source").hexdigest()
    target_contract = {
        "wallet_type": "xch",
        "outputs": [
            {
                "output_index": 0,
                "amount_mojos": 499_999,
                "purpose": "fee_reserve",
            },
            {
                "output_index": 1,
                "amount_mojos": 499_999,
                "purpose": "fee_reserve",
            },
        ],
    }
    prep_contract = {
        "operation_kind": "split",
        "purpose": "fee_reserve",
        "target_contract": target_contract,
        "pre_view_coin_ids": [source_coin_id],
    }
    canonical_prep = replacement_capacity.canonical_coin_prep_contract(
        operation_kind="split",
        purpose="fee_reserve",
        source_coin_ids=[source_coin_id],
        target_contract=target_contract,
    )
    wallet_identity = {"backend": "sage", "fingerprint": 171717171}
    assert database.upsert_coin(
        source_coin_id,
        "xch",
        1_000_000,
        designation="fee",
        tier="fees",
        purpose="fee_reserve",
    )

    claims: list[dict] = []

    def claim(**kwargs):
        claims.append(kwargs)
        return {"claim_token": "c" * 64, "generation": 1}

    monkeypatch.setattr(coin_prep_worker, "claim_wallet_effect", claim)
    monkeypatch.setattr(
        coin_prep_worker, "wallet_effect_claim_is_current", lambda *_a, **_k: True
    )
    dispatch = object()
    monkeypatch.setattr(
        coin_prep_worker, "begin_wallet_effect_dispatch", lambda *_a, **_k: dispatch
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "wallet_effect_adapter_dispatch_authority",
        lambda capability: nullcontext(capability),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "complete_wallet_effect_dispatch",
        lambda capability, **_kwargs: "SUBMITTED" if capability is dispatch else None,
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "prepare_coin_prep_operation",
        lambda **_kwargs: {
            "operation": {
                "operation_id": canonical_prep["operation_id"],
                "source_coin_ids_json": json.dumps([source_coin_id]),
                "wallet_identity_json": json.dumps(wallet_identity),
                "effect_claim_token": "c" * 64,
                "effect_claim_generation": 1,
            }
        },
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "record_coin_prep_operation_outcome",
        lambda operation_id, **kwargs: {
            "operation": {"operation_id": operation_id, **kwargs}
        },
    )
    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._is_subprocess = False
    worker.log = lambda _message: None
    worker._current_coin_prep_wallet_identity = lambda: wallet_identity
    worker._observe_coin_prep_post_effect = lambda _operation: {
        "expected_outputs": [],
        "authoritative_view": {},
    }
    worker._verify_authoritative_post_operation_view = lambda **_kwargs: True
    calls: list[dict] = []

    denied = worker._call_wallet_mutation(
        "coin_prep.split_xch_pool",
        lambda **kwargs: calls.append(kwargs) or {"success": True},
        target_coin_id=source_coin_id,
        fee_mojos=2,
        _prep_contract=prep_contract,
    )
    exact = worker._call_wallet_mutation(
        "coin_prep.split_xch_pool",
        lambda **kwargs: calls.append(kwargs) or {"success": True},
        target_coin_id=source_coin_id,
        fee_mojos=2,
        _authority_fee_coin_ids=[source_coin_id],
        _prep_contract=prep_contract,
    )

    assert denied is None
    assert exact == {"success": True}
    assert calls == [{"target_coin_id": source_coin_id, "fee_mojos": 2}]
    assert claims == [
        {
            "operation_id": canonical_prep["operation_id"],
            "source_coin_ids": [source_coin_id],
            "fee_coin_ids": [source_coin_id],
        }
    ]


def test_coin_manager_denies_unknown_or_malformed_wallet_effect_contract(
    isolated_database,
):
    import coin_manager

    source_coin_id = hashlib.sha256(b"manager-contract-source").hexdigest()
    assert database.upsert_coin(
        source_coin_id, "xch", 200_000, designation="reserve", tier="none"
    )
    calls: list[str] = []

    unknown = coin_manager._run_claimed_wallet_effect(
        "attacker_keyword_split",
        lambda: calls.append("unknown") or {"success": True},
        source_coin_ids=[source_coin_id],
    )
    malformed = coin_manager._run_claimed_wallet_effect(
        "coin_manager.consolidate_sage",
        lambda: calls.append("malformed") or {"success": True},
        source_coin_ids=[source_coin_id],
    )
    ignored_source = coin_manager._run_claimed_wallet_effect(
        "coin_manager.pool_send_sage",
        lambda: calls.append("ignored-source") or {"success": True},
        source_coin_ids=[source_coin_id],
        fee_mojos=0,
    )

    assert unknown is coin_manager._WALLET_EFFECT_DENIED
    assert malformed is coin_manager._WALLET_EFFECT_DENIED
    assert ignored_source is coin_manager._WALLET_EFFECT_DENIED
    assert calls == []


def test_wallet_effect_recheck_denial_retains_uncertain_claim(monkeypatch):
    import coin_manager

    source_coin_id = hashlib.sha256(b"claim-recheck-release").hexdigest()
    callback_calls: list[str] = []
    retained: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        coin_manager,
        "claim_wallet_effect",
        lambda **_kwargs: {"claim_token": "c" * 64, "generation": 3},
    )
    monkeypatch.setattr(
        coin_manager,
        "wallet_effect_claim_is_current",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        coin_manager,
        "retain_wallet_effect_claim_for_reconciliation",
        lambda *args, **kwargs: retained.append((args, kwargs)) or True,
    )

    result = coin_manager._run_claimed_wallet_effect(
        "coin_manager.split_sage",
        lambda: callback_calls.append("effect") or {"success": True},
        source_coin_ids=[source_coin_id],
    )

    assert result is coin_manager._WALLET_EFFECT_DENIED
    assert callback_calls == []
    assert retained == [
        (
            ("c" * 64, 3),
            {
                "reason_code": "AUTHORITY_RECHECK_FAILED_BEFORE_EFFECT",
            },
        )
    ]


def test_wallet_effect_claim_blocks_interleaved_task4_prepare(
    active_wallet_effect_runtime,
    monkeypatch,
):
    import coin_prep_worker

    source_coin_id = hashlib.sha256(b"claim-task4-barrier").hexdigest()
    assert database.upsert_coin(
        source_coin_id, "xch", 200_000, designation="reserve", tier="none"
    )
    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._is_subprocess = False
    worker.log = lambda _message: None
    task4_denied: list[bool] = []
    runtime, _clock, wallet_hash = active_wallet_effect_runtime
    _bind_task12_worker_identity(worker, runtime)
    worker._observe_coin_prep_post_effect = lambda _operation: {
        "expected_outputs": [],
        "authoritative_view": {},
    }
    worker._verify_authoritative_post_operation_view = lambda **_kwargs: True

    def effect(**_kwargs):
        try:
            database.prepare_offer_intent(
                intent_id="claim-barrier-intent",
                operation_id="create:claim-barrier-intent",
                event_id="create:claim-barrier-intent:prepared",
                run_id="claim-barrier-run",
                wallet_fingerprint_hash=wallet_hash,
                network="mainnet",
                asset_id=ASSET,
                side="buy",
                tier="inner",
                purpose="claim_barrier_test",
                slot_key="claim-barrier-slot",
                generation=0,
                offered_amount_atomic="1000",
                requested_amount_atomic="2000",
                selected_coin_ids_json=[source_coin_id],
                wallet_identity_json={
                    "wallet_fingerprint_hash": wallet_hash,
                    "network": "mainnet",
                },
                evidence_json={"fixture": "claim barrier"},
                prepared_at=AT,
                reserve_selected_coins=True,
            )
        except ValueError as exc:
            task4_denied.append("wallet effect claim" in str(exc).lower())
        return {
            **_wallet_effect_real_facade_result(
                runtime, monkeypatch, attempted=True, success=True
            ),
            "success": True,
            "transaction_id": "claim-barrier-effect",
        }

    result = worker._call_wallet_mutation(
        "coin_prep.split_single_sage",
        effect,
        target_coin_id=source_coin_id,
        fee_mojos=0,
        _prep_contract=_task12_split_prep_contract(source_coin_id),
    )

    assert result["success"] is True
    assert task4_denied == [True]


def test_wallet_effect_claim_blocks_free_and_wallet_reconciliation(
    active_wallet_effect_runtime,
):
    free_coin_id = hashlib.sha256(b"claim-free-barrier").hexdigest()
    gone_coin_id = hashlib.sha256(b"claim-reconcile-barrier").hexdigest()
    assert database.upsert_coin(free_coin_id, "xch", 200_000, tier="none")
    assert database.upsert_coin(gone_coin_id, "xch", 300_000, tier="none")
    database.get_connection().execute(
        "UPDATE coins SET status='gone' WHERE coin_id=?",
        (database.norm_coin_id(gone_coin_id),),
    )
    database.get_connection().commit()
    free_claim = database.claim_wallet_effect(
        operation_id="claim-free-barrier",
        source_coin_ids=[free_coin_id],
    )
    gone_claim = database.claim_wallet_effect(
        operation_id="claim-reconcile-barrier",
        source_coin_ids=[gone_coin_id],
    )
    assert free_claim is not None
    assert gone_claim is not None

    assert database.free_coin(free_coin_id) is False
    stats = database.reconcile_coins_with_wallet(
        {database.norm_coin_id(gone_coin_id): 300_000},
        {database.norm_coin_id(gone_coin_id): 300_000},
        "xch",
    )

    assert stats["protected"] == 2
    assert stats["reappeared"] == 0
    assert database.get_coin_state(gone_coin_id)["status"] == "gone"
    assert database.retain_wallet_effect_claim_for_reconciliation(
        free_claim["claim_token"],
        free_claim["generation"],
        reason_code="TEST_COMPLETE",
    )
    assert database.retain_wallet_effect_claim_for_reconciliation(
        gone_claim["claim_token"],
        gone_claim["generation"],
        reason_code="TEST_COMPLETE",
    )


def test_unresolved_wallet_effect_claim_survives_restart_and_fences_task4(
    active_wallet_effect_runtime,
):
    import coin_prep_worker

    source_coin_id = hashlib.sha256(b"claim-crash-restart").hexdigest()
    assert database.upsert_coin(
        source_coin_id, "xch", 200_000, designation="reserve", tier="none"
    )
    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._is_subprocess = False
    worker.log = lambda _message: None
    runtime, _clock, wallet_hash = active_wallet_effect_runtime
    _bind_task12_worker_identity(worker, runtime)

    with pytest.raises(SystemExit):
        worker._call_wallet_mutation(
            "coin_prep.split_single_sage",
            lambda **_kwargs: (_ for _ in ()).throw(SystemExit("crash boundary")),
            target_coin_id=source_coin_id,
            fee_mojos=0,
            _prep_contract=_task12_split_prep_contract(source_coin_id),
        )

    import mutation_gate

    # Simulate process death: only process-local permits disappear. The
    # unresolved durable claim and dispatch must survive the restart.
    with database._wallet_effect_process_authorities_lock:
        crashed_states = list(database._wallet_effect_process_authorities.values())
        database._wallet_effect_process_authorities.clear()
    for state in crashed_states:
        mutation_gate.exit_wallet_mutation(state.permit)
    mutation_gate.shutdown_runtime(release_owned_lease=True)
    database.close_connection()
    database._db_initialized_path = ""
    database.init_database()
    with pytest.raises(ValueError, match="wallet effect claim"):
        database.prepare_offer_intent(
            intent_id="claim-crash-intent",
            operation_id="create:claim-crash-intent",
            event_id="create:claim-crash-intent:prepared",
            run_id="claim-crash-run",
            wallet_fingerprint_hash=wallet_hash,
            network="mainnet",
            asset_id=ASSET,
            side="buy",
            tier="inner",
            purpose="claim_crash_test",
            slot_key="claim-crash-slot",
            generation=0,
            offered_amount_atomic="1000",
            requested_amount_atomic="2000",
            selected_coin_ids_json=[source_coin_id],
            wallet_identity_json={
                "wallet_fingerprint_hash": wallet_hash,
                "network": "mainnet",
            },
            evidence_json={"fixture": "claim crash"},
            prepared_at=AT,
            reserve_selected_coins=True,
        )


def test_wallet_effect_claim_guard_recomputes_exact_source_fee_union(
    isolated_database,
):
    source_coin_id = database.norm_coin_id(
        hashlib.sha256(b"claim-shape-source").hexdigest()
    )
    fee_coin_id = database.norm_coin_id(hashlib.sha256(b"claim-shape-fee").hexdigest())
    source_json = json.dumps([source_coin_id], separators=(",", ":"))
    fee_json = json.dumps([fee_coin_id], separators=(",", ":"))
    # A canonical-looking root that omits the fee input from its cohort must
    # not become durable authority, even on an application DB connection.
    forged_cohort_json = source_json
    digest = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()

    with pytest.raises(sqlite3.IntegrityError, match="claim cohort"):
        database.get_connection().execute(
            "INSERT INTO wallet_effect_claims ("
            "claim_token, operation_id, operation_contract, generation, "
            "source_coin_ids_json, source_coin_ids_sha256, fee_coin_ids_json, "
            "fee_coin_ids_sha256, cohort_coin_ids_json, cohort_coin_ids_sha256, "
            "wallet_fingerprint_hash, network, claimed_at) "
            "VALUES (?, ?, 'EXPLICIT_COIN_COHORT_V1', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "1" * 64,
                "claim-shape-forgery",
                source_json,
                digest(source_json),
                fee_json,
                digest(fee_json),
                forged_cohort_json,
                digest(forged_cohort_json),
                WALLET,
                "mainnet",
                AT,
            ),
        )
    database.get_connection().rollback()


def test_wallet_effect_resolution_guard_requires_exact_outcome_evidence_and_replays(
    active_wallet_effect_runtime,
    monkeypatch,
):
    runtime, _clock, _wallet_hash = active_wallet_effect_runtime
    source_coin_id = hashlib.sha256(b"claim-resolution-source").hexdigest()
    assert database.upsert_coin(source_coin_id, "xch", 1000, tier="none")
    claim = database.claim_wallet_effect(
        operation_id="claim-resolution",
        source_coin_ids=[source_coin_id],
    )
    assert claim is not None
    dispatch = database.begin_wallet_effect_dispatch(
        claim["claim_token"],
        claim["generation"],
        operation_id=claim["operation_id"],
        source_coin_ids=[source_coin_id],
    )
    assert dispatch is not None
    forged = json.dumps(
        {
            "effect_attempted": True,
            "reason_code": "FORGED_NO_EFFECT",
            "result_type": "dict",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(sqlite3.IntegrityError, match="claim resolution"):
        database.get_connection().execute(
            "INSERT INTO wallet_effect_claim_resolutions "
            "(claim_token, generation, outcome, evidence_json, evidence_sha256, "
            " resolved_at) VALUES (?, ?, 'RELEASED_NO_EFFECT', ?, ?, ?)",
            (
                claim["claim_token"],
                claim["generation"],
                forged,
                hashlib.sha256(forged.encode("utf-8")).hexdigest(),
                AT,
            ),
        )

    database.get_connection().rollback()

    with database.wallet_effect_adapter_dispatch_authority(dispatch):
        no_effect_result = _wallet_effect_real_facade_result(
            runtime, monkeypatch, attempted=False
        )
    assert (
        database.complete_wallet_effect_dispatch(
            dispatch,
            result=no_effect_result,
            resolved_at=AT,
        )
        == "RELEASED_NO_EFFECT"
    )
    with pytest.raises(ValueError, match="not current"):
        database.complete_wallet_effect_dispatch(
            dispatch,
            result={},
            resolved_at=AFTER,
        )


def test_submitted_legacy_runtime_topup_can_be_adopted_only_with_exact_fee_proof(
    active_wallet_effect_runtime,
    monkeypatch,
):
    """Recover the pre-journal live top-up without directly clearing safety."""

    import mutation_gate

    runtime, _clock, _wallet_hash = active_wallet_effect_runtime
    source = hashlib.sha256(b"legacy-runtime-topup-source").hexdigest()
    fee_source = hashlib.sha256(b"legacy-runtime-topup-fee").hexdigest()
    target = hashlib.sha256(b"legacy-runtime-topup-target").hexdigest()
    change = hashlib.sha256(b"legacy-runtime-topup-change").hexdigest()
    fee_change = hashlib.sha256(b"legacy-runtime-topup-fee-change").hexdigest()
    assert database.upsert_coin(source, "cat", 500, purpose="top_up")
    assert database.upsert_coin(fee_source, "xch", 1000, purpose="fee_reserve")
    claim = database.claim_wallet_effect(
        operation_id="coin_manager.topup_split_sage",
        source_coin_ids=[source],
        fee_coin_ids=[fee_source],
    )
    dispatch = database.begin_wallet_effect_dispatch(
        claim["claim_token"],
        claim["generation"],
        operation_id=claim["operation_id"],
        source_coin_ids=[source],
        fee_coin_ids=[fee_source],
    )
    with database.wallet_effect_adapter_dispatch_authority(dispatch):
        result = _wallet_effect_real_facade_result(
            runtime, monkeypatch, attempted=True, success=True
        )
    assert (
        database.complete_wallet_effect_dispatch(dispatch, result=result) == "SUBMITTED"
    )

    identity = mutation_gate.wallet_identity_binding_payload(
        runtime._wallet_identity_binding
    )
    expected_outputs = [
        {"coin_id": target, "amount_mojos": 100, "purpose": "replacement"},
        {"coin_id": change, "amount_mojos": 400, "purpose": "top_up"},
    ]
    fee_outputs = [
        {"coin_id": fee_change, "amount_mojos": 987, "purpose": "fee_reserve"}
    ]
    target_contract = {
        "wallet_type": "cat",
        "outputs": [
            {
                "output_index": index,
                "amount_mojos": output["amount_mojos"],
                "purpose": output["purpose"],
            }
            for index, output in enumerate(expected_outputs)
        ],
    }

    def view(coins):
        return {
            "fresh": True,
            "complete": True,
            "wallet_identity": identity,
            "observed_at": "2026-08-20T12:00:00.000000Z",
            "expires_at": "2026-08-20T12:00:15.000000Z",
            "coins": coins,
        }

    common = {
        "operation_kind": "split",
        "purpose": "replacement",
        "source_coin_ids": [source],
        "target_contract": target_contract,
        "wallet_identity_json": identity,
        "effect_claim_token": claim["claim_token"],
        "effect_claim_generation": claim["generation"],
    }
    with pytest.raises(ValueError, match="fee reconciliation"):
        database.adopt_legacy_submitted_topup_coin_prep_operation(
            **common,
            evidence_json={"pre_view_coin_ids": [source]},
        )

    adopted = database.adopt_legacy_submitted_topup_coin_prep_operation(
        **common,
        evidence_json={
            "pre_view_coin_ids": [source],
            "fee_reconciliation": {
                "source_coin_ids": [fee_source],
                "expected_outputs": fee_outputs,
                "authoritative_view": view(fee_outputs),
            },
        },
    )
    assert adopted["operation"]["outcome"] == "SUBMITTED_UNKNOWN"

    confirmed = database.record_coin_prep_operation_outcome(
        adopted["operation"]["operation_id"],
        outcome="CONFIRMED",
        evidence_json={
            "reason_code": "AUTHORITATIVE_POST_VIEW_CONFIRMED",
            "effect_claim_token": claim["claim_token"],
            "effect_claim_generation": claim["generation"],
            "source_coin_ids": [source],
            "expected_outputs": expected_outputs,
            "authoritative_view": view(expected_outputs),
            "expected_wallet_identity": identity,
        },
    )
    assert confirmed["operation"]["outcome"] == "CONFIRMED"
    assert database.get_runtime_safety_latch()["state"] == "resolved"


def test_submitted_legacy_runtime_absorb_can_be_adopted_with_exact_output_proof(
    active_wallet_effect_runtime,
    monkeypatch,
):
    """Recover the pre-journal reserve combine without replaying its spend."""

    import mutation_gate

    runtime, _clock, _wallet_hash = active_wallet_effect_runtime
    reserve = hashlib.sha256(b"legacy-runtime-absorb-reserve").hexdigest()
    misfit = hashlib.sha256(b"legacy-runtime-absorb-misfit").hexdigest()
    combined = hashlib.sha256(b"legacy-runtime-absorb-output").hexdigest()
    assert database.upsert_coin(reserve, "xch", 1000, purpose="top_up")
    assert database.upsert_coin(misfit, "xch", 200, purpose="replacement")
    claim = database.claim_wallet_effect(
        operation_id="coin_manager.absorb_sage",
        source_coin_ids=[reserve, misfit],
        fee_coin_ids=[reserve, misfit],
    )
    dispatch = database.begin_wallet_effect_dispatch(
        claim["claim_token"],
        claim["generation"],
        operation_id=claim["operation_id"],
        source_coin_ids=[reserve, misfit],
        fee_coin_ids=[reserve, misfit],
    )
    with database.wallet_effect_adapter_dispatch_authority(dispatch):
        result = _wallet_effect_real_facade_result(
            runtime, monkeypatch, attempted=True, success=True
        )
    assert (
        database.complete_wallet_effect_dispatch(dispatch, result=result) == "SUBMITTED"
    )

    identity = mutation_gate.wallet_identity_binding_payload(
        runtime._wallet_identity_binding
    )
    expected_outputs = [
        {"coin_id": combined, "amount_mojos": 1187, "purpose": "top_up"}
    ]
    authoritative_view = {
        "fresh": True,
        "complete": True,
        "wallet_identity": identity,
        "observed_at": "2026-08-20T12:00:00.000000Z",
        "expires_at": "2026-08-20T12:00:15.000000Z",
        "coins": expected_outputs,
    }
    adopted = database.adopt_legacy_submitted_topup_coin_prep_operation(
        operation_kind="combine",
        purpose="top_up",
        source_coin_ids=[reserve, misfit],
        target_contract={
            "wallet_type": "xch",
            "outputs": [
                {
                    "output_index": 0,
                    "amount_mojos": 1187,
                    "purpose": "top_up",
                }
            ],
        },
        wallet_identity_json=identity,
        evidence_json={
            "pre_view_coin_ids": [reserve, misfit],
            "fee_reconciliation": {
                "source_coin_ids": [reserve, misfit],
                "expected_outputs": expected_outputs,
                "authoritative_view": authoritative_view,
            },
        },
        effect_claim_token=claim["claim_token"],
        effect_claim_generation=claim["generation"],
    )
    assert adopted["operation"]["outcome"] == "SUBMITTED_UNKNOWN"

    confirmed = database.record_coin_prep_operation_outcome(
        adopted["operation"]["operation_id"],
        outcome="CONFIRMED",
        evidence_json={
            "reason_code": "AUTHORITATIVE_POST_VIEW_CONFIRMED",
            "effect_claim_token": claim["claim_token"],
            "effect_claim_generation": claim["generation"],
            "source_coin_ids": [reserve, misfit],
            "expected_outputs": expected_outputs,
            "authoritative_view": authoritative_view,
            "expected_wallet_identity": identity,
        },
    )
    assert confirmed["operation"]["outcome"] == "CONFIRMED"
    assert database.get_runtime_safety_latch()["state"] == "resolved"


def test_post_fill_claim_attestation_guard_recomputes_exact_canonical_binding(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(suffix="claim-attestation-shape")
    fill_id = result["fill_id"]
    receipt = database.get_authoritative_fill_by_id(fill_id)
    claim_token = "c" * 64
    conn = database.get_connection()
    conn.execute(
        "UPDATE offer_fill_hook_outbox SET state='running', attempt=1, "
        "claim_token=?, claimed_at=? WHERE fill_id=? "
        "AND hook_name='offer_filled_event'",
        (claim_token, AT, fill_id),
    )
    forged = json.dumps(
        {
            "schema_version": 1,
            "fill_id": fill_id,
            "hook_name": "offer_filled_event",
            "claim_generation": 1,
            "claim_token": "d" * 64,
            "authority_token": receipt["authority_token"],
            "revocation_epoch": 0,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    with pytest.raises(sqlite3.IntegrityError, match="claim attestation"):
        conn.execute(
            "INSERT INTO offer_fill_hook_claim_attestations "
            "(fill_id, hook_name, claim_generation, claim_token, authority_token, "
            "revocation_epoch, attestation_json, attestation_sha256, claimed_at) "
            "VALUES (?, 'offer_filled_event', 1, ?, ?, 0, ?, ?, ?)",
            (
                fill_id,
                claim_token,
                receipt["authority_token"],
                forged,
                hashlib.sha256(forged.encode("utf-8")).hexdigest(),
                AT,
            ),
        )
    conn.rollback()


def test_raw_sqlite_without_authority_helpers_cannot_insert_forged_journal(
    isolated_database,
):
    selected_coin_id = hashlib.sha256(b"raw-journal-source").hexdigest()
    assert database.upsert_coin(
        selected_coin_id, "xch", 1000, tier="inner", purpose="lifecycle"
    )
    database.prepare_offer_intent(
        intent_id="raw-journal-intent",
        operation_id="create:raw-journal-intent",
        event_id="create:raw-journal-intent:prepared",
        run_id="raw-journal-run",
        wallet_fingerprint_hash=WALLET,
        network="mainnet",
        asset_id=ASSET,
        side="buy",
        tier="inner",
        purpose="raw_journal_guard_test",
        slot_key="raw-journal-slot",
        generation=0,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[selected_coin_id],
        wallet_identity_json={},
        evidence_json={},
        prepared_at=AT,
    )
    raw = sqlite3.connect(str(isolated_database))
    try:
        with pytest.raises(sqlite3.DatabaseError):
            raw.execute(
                "INSERT INTO offer_operation_journal "
                "(event_id, operation_id, intent_id, operation_type, attempt, "
                " phase, outcome, request_timestamp, wallet_identity_json, "
                " evidence_json, evidence_sha256, blocks_mutation, created_at) "
                "VALUES (?, ?, ?, 'RECONCILE', 1, 'FINALIZED', 'FILLED_PROVEN', "
                " ?, '{}', '{}', ?, 0, ?)",
                (
                    "reconcile:raw-journal-intent:attempt:1:finalized",
                    "reconcile:raw-journal-intent",
                    "raw-journal-intent",
                    AFTER,
                    "0" * 64,
                    AFTER,
                ),
            )
    finally:
        raw.rollback()
        raw.close()


def test_read_only_diagnostics_connections_register_authority_helpers():
    import read_only_diagnostics

    conn = read_only_diagnostics._sqlite_connect(":memory:")
    try:
        registered = {
            str(row[0]): int(row[5])
            for row in conn.execute("PRAGMA function_list").fetchall()
        }
    finally:
        conn.close()

    deterministic = 0x800
    assert registered["catalyst_sha256"] & deterministic
    assert registered["catalyst_is_canonical_json"] & deterministic
    strict = read_only_diagnostics._sqlite_connect(":memory:")
    try:
        assert (
            strict.execute(
                "SELECT catalyst_is_canonical_json(?)", ('{"value":NaN}',)
            ).fetchone()[0]
            == 0
        )
        assert (
            strict.execute(
                "SELECT catalyst_is_canonical_json(?)", ('{"value":1}',)
            ).fetchone()[0]
            == 1
        )
    finally:
        strict.close()
    assert inspect.getsource(read_only_diagnostics).count("sqlite3.connect(") == 1


def test_selected_coin_digest_is_recomputed_by_insert_guard(isolated_database):
    result, proof = _seed_authoritative_fill(suffix="selected-digest-guard")
    del result
    conn = database.get_connection()
    source = dict(
        conn.execute(
            "SELECT * FROM offer_intents WHERE intent_id=?", (proof["intent_id"],)
        ).fetchone()
    )
    source.update(
        {
            "intent_id": "wrong-selected-digest-intent",
            "run_id": "wrong-selected-digest-run",
            "slot_key": "wrong-selected-digest-slot",
            "sage_trade_id": "wrong-selected-digest-trade",
            "offer_text_sha256": hashlib.sha256(b"wrong-selected-offer").hexdigest(),
            "selected_coin_ids_sha256": "0" * 64,
        }
    )
    columns = tuple(source)

    with pytest.raises(sqlite3.IntegrityError, match="selected coin"):
        conn.execute(
            f"INSERT INTO offer_intents ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _column in columns)})",
            tuple(source[column] for column in columns),
        )
    conn.rollback()


def test_revocation_after_claim_blocks_callback_and_completed_replay(
    isolated_database, monkeypatch
):
    result, _proof = _seed_authoritative_fill(suffix="revocation-callback-race")
    fill_id = result["fill_id"]
    original_claim = database.claim_offer_fill_hook
    revoked = False

    def claim_then_revoke(claim_fill_id, hook_name):
        nonlocal revoked
        claim = original_claim(claim_fill_id, hook_name)
        if claim["status"] == "claimed" and not revoked:
            revoked = True
            database.revoke_offer_fill_authority(
                claim_fill_id,
                reason_code="TEST_REVOCATION_INTERLEAVE",
                evidence={"fixture": "revocation after claim"},
                revoked_at=AFTER,
            )
        return claim

    calls: list[str] = []

    def callbacks(_fill):
        return {
            name: (
                lambda _row, *, claim_token, claim_generation, name=name: (
                    calls.append(name) or {}
                )
            )
            for name in database._AUTHORITATIVE_FILL_HOOKS
        }

    monkeypatch.setattr(database, "claim_offer_fill_hook", claim_then_revoke)
    monkeypatch.setattr(offer_reconciliation, "_post_fill_hook_callbacks", callbacks)

    statuses = offer_reconciliation._run_post_fill_hooks(
        database.get_authoritative_fill_by_id(fill_id), completed_at=FILLED_AT
    )

    assert calls == []
    assert "blocked" in statuses.values()
    assert database.get_offer_fill_hook_receipts(fill_id) == []
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert latch["reason_code"] == "AUTHORITATIVE_FILL_PROOF_LOST"


def test_process_effect_fence_serializes_revocation_through_callback_boundary(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(
        suffix="revocation-process-effect-race", tier="boost"
    )
    fill_id = result["fill_id"]
    claim = database.claim_offer_fill_hook(fill_id, "boost_notification")
    assert hasattr(database, "offer_fill_process_effect_authority")
    entered = threading.Event()
    release_effect = threading.Event()
    revocation_done = threading.Event()
    order: list[str] = []
    errors: list[BaseException] = []

    def run_effect() -> None:
        try:
            with database.offer_fill_process_effect_authority(
                fill_id,
                "boost_notification",
                claim["claim_token"],
                claim["claim_generation"],
            ):
                order.append("effect-start")
                entered.set()
                assert release_effect.wait(timeout=5)
                order.append("effect-end")
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def revoke() -> None:
        try:
            database.revoke_offer_fill_authority(
                fill_id,
                reason_code="TEST_FINAL_EFFECT_REVOCATION_INTERLEAVE",
                evidence={"fixture": "revocation waits for process effect"},
                revoked_at=AFTER,
            )
            order.append("revoked")
            revocation_done.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    effect_thread = threading.Thread(target=run_effect)
    effect_thread.start()
    assert entered.wait(timeout=5)
    revoke_thread = threading.Thread(target=revoke)
    revoke_thread.start()
    assert not revocation_done.wait(timeout=0.1)
    release_effect.set()
    effect_thread.join(timeout=5)
    revoke_thread.join(timeout=5)

    assert not effect_thread.is_alive()
    assert not revoke_thread.is_alive()
    assert errors == []
    assert order == ["effect-start", "effect-end", "revoked"]
    assert database.get_authoritative_fill_by_id(fill_id) is None


def test_missing_receipt_uses_journal_binding_to_trip_named_latch(isolated_database):
    result, _proof = _seed_authoritative_fill(suffix="missing-receipt-binding")
    fill_id = result["fill_id"]
    conn = database.get_connection()
    _delete_authoritative_receipt_for_test(conn, fill_id)

    blocked = database.claim_offer_fill_hook(fill_id, "boost_notification")

    assert blocked["status"] == "blocked"
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert latch["reason_code"] == "AUTHORITATIVE_FILL_PROOF_LOST"


def test_post_fill_classification_uses_immutable_selected_coin_not_offer_projection(
    isolated_database, monkeypatch
):
    result, proof = _seed_authoritative_fill(suffix="immutable-callback-coin")
    fill_id = result["fill_id"]
    attacker_coin_id = database.norm_coin_id(
        hashlib.sha256(b"attacker-callback-coin").hexdigest()
    )
    conn = database.get_connection()
    conn.execute(
        "UPDATE offers SET coin_id=? WHERE trade_id=?",
        (attacker_coin_id, proof["intent_id"].replace("intent-", "trade-")),
    )
    conn.commit()
    seen: list[str] = []

    class Result:
        classification = "dexie_combined"
        spent_block_index = 42
        taker_puzzle_hash = None
        sweep_group_id = "sweep_42"
        side = "buy"

    import fill_classifier

    def classify(_trade_id, detail, _wallet):
        seen.append(detail["coin_id"])
        return Result()

    monkeypatch.setattr(fill_classifier, "classify_fill", classify)
    callbacks = offer_reconciliation._post_fill_hook_callbacks(
        database.get_authoritative_fill_by_id(fill_id)
    )
    claim = database.claim_offer_fill_hook(fill_id, "fill_classification")
    callbacks["fill_classification"](
        database.get_authoritative_fill_by_id(fill_id),
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )

    assert seen == [proof["coin_id"]]


def test_revoked_boost_effect_is_not_restored_from_durable_materialization(
    isolated_database,
):
    result, _proof = _seed_authoritative_fill(
        suffix="revoked-boost-restore", tier="boost"
    )
    fill = database.get_authoritative_fill_by_id(result["fill_id"])
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    materialization = {
        "schema_version": 1,
        "fill_id": fill["fill_id"],
        "trade_id": fill["trade_id"],
        "side": fill["side"],
        "probe_trade_id": fill["trade_id"],
        "probe_matched": True,
        "settled_before": False,
        "offset_bps": 10,
        "floor_bps": 10,
        "last_safe_offset_bps": 9,
    }
    database.register_authoritative_boost_fill_command(
        fill["fill_id"],
        fill["trade_id"],
        fill["side"],
        materialization=materialization,
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    effect = database.materialize_authoritative_boost_fill_effect(
        fill["fill_id"],
        fill["trade_id"],
        fill["side"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    database.complete_authoritative_boost_fill_command(
        fill["fill_id"],
        fill["trade_id"],
        fill["side"],
        effect,
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    database.revoke_offer_fill_authority(
        fill["fill_id"],
        reason_code="TEST_REVOKED_BOOST_RESTORE",
        evidence={"fixture": "revoked boost restore"},
        revoked_at=AFTER,
    )

    with pytest.raises(RuntimeError, match="Boost effect"):
        database.get_materialized_authoritative_boost_commands()

    assert database.get_runtime_safety_latch()["reason_code"] == (
        "AUTHORITATIVE_FILL_PROOF_LOST"
    )


def test_boost_restore_process_effect_fence_serializes_revocation_through_apply(
    isolated_database,
):
    import boost_manager

    result, _proof = _seed_authoritative_fill(
        suffix="boost-restore-process-fence", tier="boost"
    )
    fill = database.get_authoritative_fill_by_id(result["fill_id"])
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    materialization = {
        "schema_version": 1,
        "fill_id": fill["fill_id"],
        "trade_id": fill["trade_id"],
        "side": fill["side"],
        "probe_trade_id": fill["trade_id"],
        "probe_matched": True,
        "settled_before": False,
        "offset_bps": 10,
        "floor_bps": 10,
        "last_safe_offset_bps": 9,
    }
    database.register_authoritative_boost_fill_command(
        fill["fill_id"],
        fill["trade_id"],
        fill["side"],
        materialization=materialization,
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    effect = database.materialize_authoritative_boost_fill_effect(
        fill["fill_id"],
        fill["trade_id"],
        fill["side"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    database.complete_authoritative_boost_fill_command(
        fill["fill_id"],
        fill["trade_id"],
        fill["side"],
        effect,
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )

    entered = threading.Event()
    release_effect = threading.Event()
    revocation_done = threading.Event()
    order: list[str] = []
    errors: list[BaseException] = []

    def restore() -> None:
        try:
            with database.authoritative_boost_restore_effect_authority() as commands:
                assert [command["fill_id"] for command in commands] == [fill["fill_id"]]
                order.append("restore-start")
                entered.set()
                assert release_effect.wait(timeout=5)
                order.append("restore-end")
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def revoke() -> None:
        try:
            database.revoke_offer_fill_authority(
                fill["fill_id"],
                reason_code="TEST_BOOST_RESTORE_PROCESS_FENCE",
                evidence={"fixture": "Boost restore process fence"},
                revoked_at=AFTER,
            )
            order.append("revoked")
            revocation_done.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    restore_thread = threading.Thread(target=restore)
    restore_thread.start()
    assert entered.wait(timeout=5)
    revoke_thread = threading.Thread(target=revoke)
    revoke_thread.start()
    assert not revocation_done.wait(timeout=0.1)
    release_effect.set()
    restore_thread.join(timeout=5)
    revoke_thread.join(timeout=5)

    assert errors == []
    assert order == ["restore-start", "restore-end", "revoked"]
    assert database.get_authoritative_fill_by_id(fill["fill_id"]) is None
    assert "authoritative_boost_restore_effect_authority" in inspect.getsource(
        boost_manager.BoostManager.__init__
    )


def test_revoked_fill_blocks_sweep_event_materialization_and_delivery(
    isolated_database,
):
    first, _first_proof = _seed_authoritative_fill(suffix="revoked-sweep-first")
    second, _second_proof = _seed_authoritative_fill(suffix="revoked-sweep-second")
    fill_ids = [first["fill_id"], second["fill_id"]]
    for fill_id in fill_ids:
        fill = database.get_authoritative_fill_by_id(fill_id)
        claim = database.claim_offer_fill_hook(fill_id, "sweep_registration")
        database.register_authoritative_sweep_fill(
            fill_id,
            {
                "trade_id": fill["trade_id"],
                "classification": "unknown",
                "spent_block_index": fill["spent_block_height"],
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
                "side": fill["side"],
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    event = database.finalize_authoritative_sweep_registrations(
        fill_ids, 42, "sweep-revocation-test"
    )
    delivery = database.claim_authoritative_sweep_event()
    assert delivery["event_id"] == event["event_id"]
    database.revoke_offer_fill_authority(
        fill_ids[0],
        reason_code="TEST_REVOKED_SWEEP_DELIVERY",
        evidence={"fixture": "revoked sweep delivery"},
        revoked_at=AFTER,
    )

    with pytest.raises((RuntimeError, ValueError), match="sweep.*authority"):
        database.materialize_authoritative_sweep_downstream_effect(
            event["event_id"],
            delivery["claim_token"],
            delivery["claim_generation"],
            known_protection_seconds=90,
            unknown_protection_seconds=30,
        )

    assert (
        database.get_connection()
        .execute(
            "SELECT 1 FROM offer_fill_sweep_downstream_effects WHERE event_id=?",
            (event["event_id"],),
        )
        .fetchone()
        is None
    )


def test_sweep_process_effect_fence_serializes_revocation_through_apply(
    isolated_database,
):
    first, _first_proof = _seed_authoritative_fill(suffix="sweep-fence-first")
    second, _second_proof = _seed_authoritative_fill(suffix="sweep-fence-second")
    fill_ids = [first["fill_id"], second["fill_id"]]
    for fill_id in fill_ids:
        fill = database.get_authoritative_fill_by_id(fill_id)
        claim = database.claim_offer_fill_hook(fill_id, "sweep_registration")
        database.register_authoritative_sweep_fill(
            fill_id,
            {
                "trade_id": fill["trade_id"],
                "classification": "unknown",
                "spent_block_index": fill["spent_block_height"],
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
                "side": fill["side"],
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    event = database.finalize_authoritative_sweep_registrations(
        fill_ids, 42, "sweep-process-fence"
    )
    delivery = database.claim_authoritative_sweep_event()
    entered = threading.Event()
    release_effect = threading.Event()
    revocation_done = threading.Event()
    order: list[str] = []
    errors: list[BaseException] = []

    def run_effect() -> None:
        try:
            with database.authoritative_sweep_process_effect_authority(
                event["event_id"],
                delivery["claim_token"],
                delivery["claim_generation"],
            ):
                order.append("effect-start")
                entered.set()
                assert release_effect.wait(timeout=5)
                order.append("effect-end")
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def revoke() -> None:
        try:
            database.revoke_offer_fill_authority(
                fill_ids[0],
                reason_code="TEST_SWEEP_PROCESS_FENCE",
                evidence={"fixture": "sweep process fence"},
                revoked_at=AFTER,
            )
            order.append("revoked")
            revocation_done.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    effect_thread = threading.Thread(target=run_effect)
    effect_thread.start()
    assert entered.wait(timeout=5)
    revoke_thread = threading.Thread(target=revoke)
    revoke_thread.start()
    assert not revocation_done.wait(timeout=0.1)
    release_effect.set()
    effect_thread.join(timeout=5)
    revoke_thread.join(timeout=5)

    assert errors == []
    assert order == ["effect-start", "effect-end", "revoked"]


def test_wallet_effect_claim_requires_exact_active_runtime_authority(
    isolated_database,
):
    source_coin_id = hashlib.sha256(b"runtime-authority-required").hexdigest()
    assert database.upsert_coin(source_coin_id, "xch", 1000, tier="none")

    claim = database.claim_wallet_effect(
        operation_id="coin_manager.split_sage",
        source_coin_ids=[source_coin_id],
    )

    assert claim is None
    assert (
        database.get_connection()
        .execute("SELECT COUNT(*) FROM wallet_effect_claims")
        .fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("boundary", ["coin_manager", "coin_prep_worker"])
@pytest.mark.parametrize("authority_change", ["heartbeat", "owner_takeover"])
def test_wallet_dispatch_fences_task4_until_exact_runtime_outcome(
    active_wallet_effect_runtime, monkeypatch, boundary, authority_change
):
    import coin_manager
    import coin_prep_worker

    runtime, clock, wallet_hash = active_wallet_effect_runtime
    source_coin_id = hashlib.sha256(
        f"dispatch-fence:{boundary}:{authority_change}".encode()
    ).hexdigest()
    assert database.upsert_coin(
        source_coin_id, "xch", 200_000, tier="none", purpose="lifecycle"
    )
    task4_denials: list[str] = []

    def prepare_after_dispatch(suffix: str) -> bool:
        try:
            database.prepare_offer_intent(
                intent_id=f"dispatch-fence-{suffix}",
                operation_id=f"create:dispatch-fence-{suffix}",
                event_id=f"create:dispatch-fence-{suffix}:prepared",
                run_id="dispatch-fence-task4",
                wallet_fingerprint_hash=wallet_hash,
                network="mainnet",
                asset_id=ASSET,
                side="buy",
                tier="inner",
                purpose="dispatch_fence_test",
                slot_key=f"dispatch-fence-slot-{suffix}",
                generation=0,
                offered_amount_atomic="200000",
                requested_amount_atomic="400000",
                selected_coin_ids_json=[source_coin_id],
                wallet_identity_json={
                    "wallet_fingerprint_hash": wallet_hash,
                    "network": "mainnet",
                },
                evidence_json={"fixture": "dispatch fence"},
                prepared_at=AT,
                reserve_selected_coins=True,
            )
        except ValueError as exc:
            task4_denials.append(str(exc))
            return False
        return True

    def adapter_result(*_args, **_kwargs):
        dispatch_count = (
            database.get_connection()
            .execute("SELECT COUNT(*) FROM wallet_effect_dispatches")
            .fetchone()[0]
        )
        assert dispatch_count == 1
        assert prepare_after_dispatch(f"during-{boundary}-{authority_change}") is False
        if authority_change == "heartbeat":
            clock["now"] += timedelta(seconds=1)
            assert runtime.heartbeat()["heartbeat"] is True
        else:
            database.get_connection().execute(
                "UPDATE runtime_mutation_lease "
                "SET owner_run_id='replacement-owner', owner_pid=5252, "
                "    acquired_at=?, lease_version=lease_version+1 "
                "WHERE singleton_id=1",
                (AFTER,),
            )
            database.get_connection().commit()
        return _wallet_effect_real_facade_result(runtime, monkeypatch, attempted=False)

    if boundary == "coin_manager":
        result = coin_manager._run_claimed_wallet_effect(
            "coin_manager.split_sage",
            adapter_result,
            source_coin_ids=[source_coin_id],
        )
    else:
        worker = object.__new__(coin_prep_worker.CoinPrepWorker)
        worker._is_subprocess = False
        worker.log = lambda _message: None
        _bind_task12_worker_identity(worker, runtime)
        result = worker._call_wallet_mutation(
            "coin_prep.split_single_sage",
            adapter_result,
            target_coin_id=source_coin_id,
            fee_mojos=0,
            _prep_contract=_task12_split_prep_contract(source_coin_id),
        )

    if boundary == "coin_manager":
        assert result["_catalyst_effect_attempted"] is False
    elif authority_change == "heartbeat":
        assert result is None
    else:
        assert isinstance(result, coin_prep_worker.CoinPrepSubmittedUnknown)
        assert result.dispatch_outcome == "UNKNOWN"
    outcome = (
        database.get_connection()
        .execute("SELECT outcome FROM wallet_effect_claim_resolutions")
        .fetchone()[0]
    )
    assert any("wallet effect claim" in denial.lower() for denial in task4_denials)
    if authority_change == "heartbeat":
        assert outcome == "RELEASED_NO_EFFECT"
        assert prepare_after_dispatch(f"after-{boundary}") is True
    else:
        assert outcome == "UNKNOWN"
        assert prepare_after_dispatch(f"after-{boundary}") is False


def test_malformed_prior_coin_outcome_does_not_remain_an_availability_authority(
    isolated_database,
):
    _result, proof = _seed_authoritative_fill(suffix="malformed-prior-coin-outcome")
    conn = database.get_connection()
    conn.execute("DROP TRIGGER offer_operation_journal_no_update")
    conn.execute(
        "UPDATE offer_operation_journal SET attempt=2 WHERE event_id=?",
        (f"reconcile:{proof['intent_id']}:attempt:1:finalized",),
    )
    conn.execute(
        """CREATE TRIGGER offer_operation_journal_no_update
        BEFORE UPDATE ON offer_operation_journal
        BEGIN
            SELECT RAISE(ABORT, 'offer_operation_journal is append-only');
        END"""
    )
    conn.commit()
    _clear_fill_authority_closure_watermark(conn)

    database._migrate_fill_authority_closure(conn)

    available = conn.execute(
        "SELECT coin_id FROM coins WHERE coin_id=? AND "
        + database._authoritative_coin_available_predicate(),
        (proof["coin_id"],),
    ).fetchall()
    assert [row["coin_id"] for row in available] == [proof["coin_id"]]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_authority_migration_audit "
            "WHERE authority_type='coin' AND subject_id=? "
            "AND reason_code='MALFORMED_COIN_OUTCOME_QUARANTINED'",
            (proof["coin_id"],),
        ).fetchone()[0]
        == 1
    )


def test_prior_coin_outcome_outside_selected_cohort_is_quarantined_on_upgrade(
    isolated_database,
):
    _result, proof = _seed_authoritative_fill(suffix="prior-outcome-wrong-member")
    wrong_coin_id = database.norm_coin_id(
        hashlib.sha256(b"prior-outcome-wrong-member").hexdigest()
    )
    assert wrong_coin_id != proof["coin_id"]
    assert database.upsert_coin(wrong_coin_id, "xch", 1000, tier="none")
    conn = database.get_connection()
    conn.execute("DROP TRIGGER offer_reconciliation_coin_outcomes_proof_guard_v2")
    cursor = conn.execute(
        "INSERT INTO offer_reconciliation_coin_outcomes "
        "(coin_id, intent_id, trade_id, outcome, disposition, terminal_event_id, "
        " evidence_sha256, recorded_at) "
        "SELECT ?, intent_id, trade_id, outcome, disposition, terminal_event_id, "
        "       evidence_sha256, recorded_at "
        "FROM offer_reconciliation_coin_outcomes WHERE coin_id=?",
        (wrong_coin_id, proof["coin_id"]),
    )
    forged_sequence = int(cursor.lastrowid)
    conn.commit()
    _clear_fill_authority_closure_watermark(conn)

    database._migrate_fill_authority_closure(conn)

    quarantine = conn.execute(
        "SELECT reason_code FROM offer_reconciliation_coin_outcome_quarantine "
        "WHERE outcome_sequence=?",
        (forged_sequence,),
    ).fetchone()
    assert quarantine is not None
    assert quarantine["reason_code"] == "MALFORMED_COIN_OUTCOME"
    available = conn.execute(
        "SELECT coin_id FROM coins WHERE coin_id=? AND "
        + database._authoritative_coin_available_predicate(),
        (wrong_coin_id,),
    ).fetchall()
    assert [row["coin_id"] for row in available] == [wrong_coin_id]


def test_boost_and_sweep_process_effect_boundaries_include_durable_acknowledgement():
    source = inspect.getsource(offer_reconciliation._post_fill_hook_callbacks)
    boost_boundary = source[
        source.index(
            "with database.offer_fill_process_effect_authority("
        ) : source.index("    def classification")
    ]
    sweep_start = source.index(
        "with database.offer_fill_process_effect_authority(",
        source.index("    def sweep_registration"),
    )
    sweep_boundary = source[sweep_start : source.index("    return {", sweep_start)]

    assert (
        "complete_authoritative_boost_fill_command"
        in boost_boundary.split("        try:", 1)[0]
    )
    assert (
        "acknowledge_authoritative_sweep_registration"
        in sweep_boundary.split("        except Exception", 1)[0]
    )


def test_sweep_startup_restore_serializes_receipt_revocation_through_process_apply(
    isolated_database, monkeypatch
):
    import sweep_coordinator

    coordinator = sweep_coordinator.SweepCoordinator(window_secs=15)
    result, _proof = _seed_authoritative_fill(suffix="sweep-restore-process-fence")
    fill = database.get_authoritative_fill_by_id(result["fill_id"])
    claim = database.claim_offer_fill_hook(fill["fill_id"], "sweep_registration")
    database.register_authoritative_sweep_fill(
        fill["fill_id"],
        {
            "trade_id": fill["trade_id"],
            "classification": "unknown",
            "spent_block_index": fill["spent_block_height"],
            "taker_puzzle_hash": None,
            "sweep_group_id": None,
            "side": fill["side"],
        },
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    entered = threading.Event()
    release_apply = threading.Event()
    revoked = threading.Event()
    order: list[str] = []
    errors: list[BaseException] = []
    original_process = coordinator.process_authoritative_fill

    def gated_process(fill_id, classification):
        order.append("restore-start")
        entered.set()
        assert release_apply.wait(timeout=5)
        result = original_process(fill_id, classification)
        order.append("restore-end")
        return result

    monkeypatch.setattr(coordinator, "process_authoritative_fill", gated_process)

    def restore() -> None:
        try:
            coordinator._restore_authoritative_registrations()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def revoke() -> None:
        try:
            database.revoke_offer_fill_authority(
                fill["fill_id"],
                reason_code="TEST_SWEEP_RESTORE_PROCESS_FENCE",
                evidence={"fixture": "Sweep restore process fence"},
                revoked_at=AFTER,
            )
            order.append("revoked")
            revoked.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    restore_thread = threading.Thread(target=restore)
    restore_thread.start()
    assert entered.wait(timeout=5)
    revoke_thread = threading.Thread(target=revoke)
    revoke_thread.start()
    revocation_interleaved = revoked.wait(timeout=0.1)
    release_apply.set()
    restore_thread.join(timeout=5)
    revoke_thread.join(timeout=5)

    assert not restore_thread.is_alive()
    assert not revoke_thread.is_alive()
    assert errors == []
    assert revocation_interleaved is False
    assert order == ["restore-start", "restore-end", "revoked"]
    assert "authoritative_sweep_restore_effect_authority" in inspect.getsource(
        sweep_coordinator.SweepCoordinator._restore_authoritative_registrations
    )


def test_economic_fill_dedupe_uses_immutable_selected_coin_authority(
    isolated_database,
):
    first, first_proof = _seed_authoritative_fill(suffix="immutable-dedupe-first")
    second, second_proof = _seed_authoritative_fill(suffix="immutable-dedupe-second")
    assert first_proof["coin_id"] != second_proof["coin_id"]
    first_fill = database.get_authoritative_fill_by_id(first["fill_id"])
    second_fill = database.get_authoritative_fill_by_id(second["fill_id"])
    conn = database.get_connection()
    attacker_coin_id = hashlib.sha256(b"mutable-shared-offer-coin").hexdigest()
    conn.execute(
        "UPDATE offers SET coin_id=? WHERE trade_id IN (?, ?)",
        (attacker_coin_id, first_fill["trade_id"], second_fill["trade_id"]),
    )
    conn.commit()

    fill_ids = database._get_economic_verified_fill_ids(conn, ASSET)

    assert sorted(fill_ids) == sorted([first["fill_id"], second["fill_id"]])
    stats = database.get_stats(ASSET)
    assert stats["total_fills"] == 2
    assert stats["duplicate_fill_rows"] == 0


def test_unrelated_revocation_does_not_invalidate_current_fill_claim(
    isolated_database,
):
    subject, _subject_proof = _seed_authoritative_fill(
        suffix="unrelated-revocation-subject"
    )
    unrelated, _unrelated_proof = _seed_authoritative_fill(
        suffix="unrelated-revocation-other"
    )
    subject_fill = database.get_authoritative_fill_by_id(subject["fill_id"])
    claim = database.claim_offer_fill_hook(subject["fill_id"], "boost_notification")
    acknowledgement = database.record_offer_fill_hook_sink_ack(
        subject["fill_id"],
        "boost_notification",
        {"trade_id": subject_fill["trade_id"], "applicable": False},
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    database.revoke_offer_fill_authority(
        unrelated["fill_id"],
        reason_code="TEST_UNRELATED_REVOCATION",
        evidence={"fixture": "unrelated fill only"},
        revoked_at=AFTER,
    )

    assert database.validate_offer_fill_hook_sink_ack(
        subject["fill_id"],
        "boost_notification",
        acknowledgement,
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    assert database.complete_offer_fill_hook(
        subject["fill_id"],
        "boost_notification",
        claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )


def test_terminal_classifier_has_no_implicit_wall_clock_default():
    source = inspect.getsource(offer_reconciliation._classify_terminal_evidence)
    assert "datetime.now(" not in source
    assert "NOW_TIMESTAMP_REQUIRED" in source


def test_fill_tracker_retry_docs_describe_source_truth_not_spacescan_only():
    import fill_tracker

    initializer = inspect.getsource(fill_tracker.FillTracker.__init__)
    retry = inspect.getsource(fill_tracker.FillTracker._retry_pending_reverify)
    assert "source-truth verification" in initializer
    assert "source-truth verification" in retry
    assert "Re-run Spacescan verification" not in retry
    assert '"rejected" → retain the row and coin lock' in retry
    assert "budget is exhausted,\n            retain the row and coin lock" in retry
