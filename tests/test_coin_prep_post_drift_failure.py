import sys
import types
import hashlib
from decimal import Decimal
from unittest.mock import MagicMock

import coin_prep_worker


def test_authoritative_post_operation_identity_drift_is_durable_failure(monkeypatch):
    """Catches count-only prep success under a stale or different wallet binding."""

    assert hasattr(
        coin_prep_worker.CoinPrepWorker,
        "_verify_authoritative_post_operation_view",
    )
    outcomes = []
    monkeypatch.setattr(
        coin_prep_worker,
        "record_coin_prep_operation_outcome",
        lambda operation_id, **kwargs: (
            outcomes.append((operation_id, kwargs))
            or {"operation": {"operation_id": operation_id, **kwargs}}
        ),
        raising=False,
    )
    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.log = MagicMock()
    worker.update_status = MagicMock()
    source = hashlib.sha256(b"source").hexdigest()
    output = hashlib.sha256(b"output").hexdigest()
    expected_identity = {
        "backend": "sage",
        "name": "Task 12 Wallet",
        "fingerprint": 123,
        "network_id": "mainnet",
        "kind": "bls",
        "has_secrets": True,
        "bound_at_utc": "2026-08-21T12:00:00.000000Z",
        "maximum_age_seconds": 300,
    }

    verified = worker._verify_authoritative_post_operation_view(
        operation_id="coin-prep:" + hashlib.sha256(b"operation").hexdigest(),
        source_coin_ids=[source],
        expected_outputs=[
            {"coin_id": output, "amount_mojos": 100, "purpose": "replacement"}
        ],
        authoritative_view={
            "fresh": True,
            "complete": True,
            "wallet_identity": {**expected_identity, "fingerprint": 999},
            "observed_at": "2026-08-21T12:00:01.000000Z",
            "expires_at": "2026-08-21T12:05:00.000000Z",
            "coins": [
                {"coin_id": output, "amount_mojos": 100, "purpose": "replacement"}
            ],
        },
        expected_wallet_identity=expected_identity,
        effect_claim_token="e" * 64,
        effect_claim_generation=1,
        dispatch_outcome="SUBMITTED",
    )

    assert verified is False
    assert outcomes[0][1]["outcome"] == "SUBMITTED_UNKNOWN"
    assert outcomes[0][1]["evidence_json"]["reason_code"] == "wallet_identity_mismatch"
    assert worker.update_status.call_args.kwargs["error"].startswith(
        "POST_PREP_AUTHORITY_UNRESOLVED"
    )


def test_post_prep_tier_drift_is_a_hard_failure(monkeypatch):
    fake_coin_manager = types.ModuleType("coin_manager")
    fake_coin_manager.check_tier_size_drift_standalone = lambda: [
        {
            "side": "cat",
            "tier": "outer",
            "ratio": "0.917",
            "coin_count": 3,
        }
    ]

    events = []
    fake_database = types.ModuleType("database")
    fake_database.log_event = lambda severity, event_type, message: events.append(
        (severity, event_type, message)
    )

    monkeypatch.setitem(sys.modules, "coin_manager", fake_coin_manager)
    monkeypatch.setitem(sys.modules, "database", fake_database)

    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.log = MagicMock()
    worker.update_status = MagicMock()

    assert worker._verify_post_prep_tier_drift() is False
    worker.update_status.assert_called_once()
    args, kwargs = worker.update_status.call_args
    phase = kwargs.get("phase") if kwargs else None
    if phase is None and args:
        phase = args[0]
    assert phase == coin_prep_worker.PrepPhase.ERROR
    assert "POST_PREP_TIER_DRIFT" in str(kwargs.get("error", ""))
    assert events
    assert events[0][1] == "tier_size_post_prep_drift"


def test_run_full_preparation_stops_before_complete_banner_on_post_drift(
    monkeypatch,
):
    fake_coin_manager = types.ModuleType("coin_manager")
    fake_coin_manager.reclassify_tier_spare_coins = lambda: {}
    fake_coin_manager.check_tier_size_drift_standalone = lambda: [
        {
            "side": "cat",
            "tier": "outer",
            "ratio": "0.917",
            "coin_count": 3,
        }
    ]

    fake_database = types.ModuleType("database")
    fake_database.log_event = lambda *args, **kwargs: None

    fake_wallet_sage = types.ModuleType("wallet_sage")
    fake_wallet_sage.get_wallet_balance = lambda wallet_id: {
        "success": True,
        "wallet_balance": {
            "confirmed_wallet_balance": 10**15,
            "unconfirmed_wallet_balance": 10**15,
            "spendable_balance": 10**15,
        },
    }

    monkeypatch.setitem(sys.modules, "coin_manager", fake_coin_manager)
    monkeypatch.setitem(sys.modules, "database", fake_database)
    monkeypatch.setitem(sys.modules, "wallet_sage", fake_wallet_sage)
    monkeypatch.setattr(coin_prep_worker.time, "sleep", lambda *_args, **_kwargs: None)

    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.xch_wallet_id = 1
    worker.cat_wallet_id = 2
    worker.tier_enabled = False
    worker.is_sage = False
    worker._db_ready = False
    worker.xch_target_coins = 1
    worker.cat_target_coins = 1
    worker.xch_expected_total_coins = 2
    worker.cat_expected_total_coins = 2
    worker.xch_coin_size = Decimal("1")
    worker.cat_coin_size = Decimal("1")
    worker.xch_reserve = Decimal("0")
    worker.cat_reserve = Decimal("0")
    worker.cat_decimals = 3
    worker.log = MagicMock()
    worker.update_status = MagicMock()
    worker.get_coin_count = MagicMock(return_value=1)
    worker.get_balance = MagicMock(return_value=Decimal("10"))
    worker._log_coin_snapshot = MagicMock()
    worker._set_status_coin_counts = MagicMock()
    worker.cancel_all_offers = MagicMock(return_value=True)
    worker._tx_fee_mojos = MagicMock(return_value=0)
    worker.consolidate_wallet = MagicMock()
    worker._designate_reserve_after_consolidation = MagicMock()
    worker.create_pools_parallel = MagicMock(return_value=True)
    worker.split_coins_parallel = MagicMock(return_value=True)
    worker.verify_coins = MagicMock(return_value=(2, 2))
    worker._merge_xch_fee_change_into_reserve = MagicMock(return_value=False)
    worker._designate_final_sweep = MagicMock()
    worker._format_cat_amount = str
    worker._recover_coin_prep_operations_read_only = MagicMock(return_value=True)
    worker._observe_recoverable_coin_prep_operation = MagicMock()

    assert worker.run_full_preparation() is False
    worker.update_status.assert_any_call(
        coin_prep_worker.PrepPhase.ERROR,
        0.99,
        "Post-prep tier drift detected - manual re-prep required",
        error="POST_PREP_TIER_DRIFT: cat/outer=0.917x (n=3)",
    )
    logged = "\n".join(str(call) for call in worker.log.mock_calls)
    assert "COIN PREPARATION COMPLETE" not in logged
