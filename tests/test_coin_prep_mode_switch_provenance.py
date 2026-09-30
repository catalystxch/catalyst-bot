"""A mode switch must not erase provenance of still-owned prep outputs."""

import hashlib
from decimal import Decimal
from types import SimpleNamespace

import coin_prep_worker
import database
import wallet_sage


def test_ordinary_wallet_disappearance_still_clears_purpose(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "gone.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    coin_id = hashlib.sha256(b"disappeared-wallet-coin").hexdigest()
    assert database.upsert_coin(coin_id, "xch", 11_000_000_000, purpose="replacement")
    try:
        assert database.mark_coins_gone([database.norm_coin_id(coin_id)]) == 1
        coin = database.get_coin_state(coin_id)
        assert coin["status"] == "gone"
        assert coin["purpose"] is None
        assert database.upsert_coin(coin_id, "xch", 11_000_000_000)
        reappeared = database.get_coin_state(coin_id)
        assert reappeared["status"] == "free"
        assert reappeared["purpose"] is None
    finally:
        database.close_connection()


def test_direct_batch_does_not_park_still_owned_replacement_before_dispatch(
    tmp_path, monkeypatch
):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "direct.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    coin_id = hashlib.sha256(b"still-owned-direct-batch-coin").hexdigest()
    assert database.upsert_coin(
        coin_id,
        "xch",
        11_000_000_000,
        designation="tier_spare",
        assigned_tier="inner",
        purpose="replacement",
    )

    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._db_ready = True
    worker.is_sage = True
    worker.xch_wallet_id = 1
    worker.cat_wallet_id = 2
    worker.tier_enabled = False
    worker.xch_target_coins = 1
    worker.cat_target_coins = 0
    worker.xch_coin_size = Decimal("0.011")
    worker.cat_coin_size = Decimal("1")
    worker.cat_decimals = 3
    worker.cat_reserve = Decimal("0")
    worker.status = SimpleNamespace(progress=0.0)
    worker.log = lambda _message: None
    worker.update_status = lambda *_args, **_kwargs: None
    worker._recover_coin_prep_operations_read_only = lambda _observe: True
    worker.get_coin_count = lambda wallet_id: 1 if wallet_id == 1 else 0
    worker.get_balance = lambda wallet_id: (
        Decimal("1") if wallet_id == 1 else Decimal("0")
    )
    worker._log_coin_snapshot = lambda *_args: None
    worker._set_status_coin_counts = lambda **_kwargs: None
    worker._format_cat_amount = str
    worker.cancel_all_offers = lambda: True
    worker._complete_existing_tier_preparation = lambda: True
    observed_at_dispatch = []
    worker._run_direct_batch_prep = lambda: (
        observed_at_dispatch.append(database.get_coin_state(coin_id)) or True
    )
    monkeypatch.setattr(
        wallet_sage,
        "get_wallet_balance",
        lambda _wallet_id: (_ for _ in ()).throw(RuntimeError("isolated test")),
    )
    monkeypatch.setattr(coin_prep_worker.time, "sleep", lambda _seconds: None)

    try:
        assert worker.run_full_preparation() is True
        assert observed_at_dispatch[0]["status"] == "free"
        assert observed_at_dispatch[0]["purpose"] == "replacement"
    finally:
        database.close_connection()


def test_sell_only_final_sweep_preserves_owned_buy_coin_purpose(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "coins.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    monkeypatch.setattr("user_paths.data_dir", lambda: str(tmp_path))

    reserve_id = hashlib.sha256(b"mode-switch-reserve").hexdigest()
    buy_coin_id = hashlib.sha256(b"mode-switch-buy-replacement").hexdigest()
    absent_coin_id = hashlib.sha256(b"mode-switch-no-longer-owned").hexdigest()
    reserve = {"coin_id": reserve_id, "amount": 138_000_000_000_000}
    buy_coin = {"coin_id": buy_coin_id, "amount": 11_000_000_000}
    assert database.upsert_coin(
        reserve_id,
        "xch",
        reserve["amount"],
        designation="reserve",
        assigned_tier="none",
        purpose="top_up",
    )
    assert database.upsert_coin(
        buy_coin_id,
        "xch",
        buy_coin["amount"],
        designation="tier_spare",
        assigned_tier="inner",
        purpose="replacement",
    )
    assert database.upsert_coin(
        absent_coin_id,
        "xch",
        11_000_000_000,
        designation="tier_spare",
        assigned_tier="inner",
        purpose="replacement",
    )

    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker._db_ready = True
    worker.is_sage = True
    worker.xch_wallet_id = 1
    worker.cat_wallet_id = 2
    worker.tier_enabled = True
    worker.xch_target_coins = 0  # sell-only mode retains no buy tier in this plan
    worker.cat_target_coins = 0
    worker.log = lambda _message: None
    worker._get_coins_via_rpc = lambda wallet_id, _name, selectable_only=False: (
        [reserve, buy_coin] if wallet_id == 1 else []
    )
    worker._partition_coins_for_designation = lambda _coins, _wallet_type: (
        {},
        [reserve, buy_coin],
    )

    try:
        worker._designate_final_sweep()
        still_owned = database.get_coin_state(buy_coin_id)
        assert still_owned["status"] == "free"
        assert still_owned["purpose"] == "replacement"
        assert still_owned["designation"] == "unknown"
        assert still_owned["assigned_tier"] == "none"
        assert database.get_coin_state(absent_coin_id)["status"] == "gone"
        assert database.set_coin_designation(buy_coin_id, "tier_spare", "inner")
        assert database.get_tier_spare_counts("xch")["inner"] == 1
    finally:
        database.close_connection()
