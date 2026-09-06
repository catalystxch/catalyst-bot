import json
import threading
from contextlib import nullcontext
from decimal import Decimal

import pytest

import coin_prep_worker
import wallet
from coin_prep_batch_plan import (
    BatchConstraints,
    BatchPlan,
    CoinSnapshot,
    PlannedOutput,
    SelectableCoin,
)


def _worker():
    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.is_sage = True
    worker.tier_enabled = True
    worker._db_ready = True
    worker._is_subprocess = False
    worker.xch_wallet_id = 1
    worker.cat_wallet_id = 2
    worker.cat_decimals = 3
    worker.cat_reserve = Decimal("0")
    worker.tier_order = ["tier"]
    worker.xch_tier_counts = {"tier": 126}
    worker.cat_tier_counts = {"tier": 76}
    worker.tier_xch_sizes = {"tier": Decimal("0.00000000001")}
    worker.tier_cat_sizes = {"tier": Decimal("0.01")}
    worker.status_lock = threading.Lock()
    worker.status = coin_prep_worker.CoinPrepStatus(
        phase="idle",
        progress=0,
        message="",
        xch_coins_current=0,
        xch_coins_target=126,
        cat_coins_current=0,
        cat_coins_target=76,
    )
    worker._tx_fee_mojos = lambda: 10
    worker.update_status = lambda phase=None, progress=None, message=None, error=None: (
        None
    )
    worker.log = lambda _message: None
    return worker


def _coin(asset, coin_id, amount, purpose=""):
    return SelectableCoin(asset, coin_id, amount, purpose)


def test_observed_wallet_shape_uses_one_cat_and_one_xch_final_batch(monkeypatch):
    worker = _worker()
    monkeypatch.setattr(
        wallet, "get_next_address", lambda *_args, **_kwargs: {"address": "xch1owner"}
    )
    monkeypatch.setenv("XCH_RESERVE", "0")

    initial = CoinSnapshot(
        (
            _coin("cat", "c" * 64, 1_000),
            _coin("xch", "f" * 64, 30),
            _coin("xch", "a" * 64, 2_000),
        )
    )
    after_cat = CoinSnapshot(
        tuple(_coin("cat", f"{index:064x}", 10, "replacement") for index in range(76))
        + (_coin("xch", "a" * 64, 2_000), _coin("xch", "e" * 64, 20))
    )
    after_xch = CoinSnapshot(
        tuple(_coin("cat", f"{index:064x}", 10, "replacement") for index in range(76))
        + tuple(
            _coin("xch", f"{index + 1000:064x}", 10, "replacement")
            for index in range(126)
        )
        + (_coin("xch", "d" * 64, 740),)
    )
    snapshots = iter((initial, after_cat, after_xch))
    worker._direct_batch_snapshot = lambda _targets: next(snapshots)
    submitted = []
    worker._submit_direct_batch_plan = lambda plan, _address: (
        submitted.append(plan) or True
    )

    assert worker._run_direct_batch_prep() is True
    assert [plan.asset for plan in submitted] == ["cat", "xch"]
    assert len(submitted[0].outputs) == 78
    assert len(submitted[1].outputs) == 127
    assert worker.status.batch_confirmed == 2
    assert worker.status.paid_fee_mojos == 20


def test_direct_batch_refusal_falls_back_only_before_any_effect(monkeypatch):
    worker = _worker()
    monkeypatch.setattr(
        wallet, "get_next_address", lambda *_args, **_kwargs: {"address": "xch1owner"}
    )
    monkeypatch.setenv("XCH_RESERVE", "0")
    worker._direct_batch_snapshot = lambda _targets: CoinSnapshot(
        tuple(_coin("cat", f"{index:064x}", 15) for index in range(60))
        + (_coin("xch", "f" * 64, 30),)
    )
    submitted = []
    worker._submit_direct_batch_plan = lambda plan, address: submitted.append(
        (plan, address)
    )

    assert worker._run_direct_batch_prep() is None
    assert submitted == []
    assert worker.status.compatibility_reason == "INPUT_CAP_REQUIRES_PREREQUISITE"


def test_direct_batch_never_falls_back_after_a_confirmed_effect(monkeypatch):
    worker = _worker()
    monkeypatch.setenv("XCH_RESERVE", "0")
    monkeypatch.setattr(
        wallet, "get_next_address", lambda *_args, **_kwargs: {"address": "xch1owner"}
    )
    initial = CoinSnapshot(
        (
            _coin("cat", "c" * 64, 1_000),
            _coin("xch", "f" * 64, 30),
            _coin("xch", "a" * 64, 2_000),
        )
    )
    snapshots = iter((initial, None))
    worker._direct_batch_snapshot = lambda _targets: next(snapshots)
    worker._submit_direct_batch_plan = lambda _plan, _address: True

    with pytest.raises(coin_prep_worker.CoinPrepAuthorityUnresolved):
        worker._run_direct_batch_prep()


def test_unsigned_output_binding_is_persisted_before_direct_batch_submit(monkeypatch):
    worker = _worker()
    monkeypatch.setenv("CAT_ASSET_ID", "a" * 64)
    source = "1" * 64
    fee_source = "2" * 64
    plan = BatchPlan(
        asset="cat",
        source_coin_ids=(source,),
        fee_source_id=fee_source,
        outputs=(
            PlannedOutput("cat", "replacement", 90, 0),
            PlannedOutput("xch", "fee_change", 20, -1),
        ),
        reused_coin_ids=(),
        reused_target_ids=(),
        fee_mojos=10,
    )
    events = []
    identity = {
        "backend": "sage",
        "name": "test",
        "fingerprint": 1,
        "network_id": "mainnet",
        "kind": "bls",
        "has_secrets": True,
        "bound_at_utc": "2026-09-04T00:00:00.000000Z",
        "maximum_age_seconds": 15,
    }
    worker._current_coin_prep_wallet_identity = lambda: identity
    worker._submitted_split_verify_timeout_seconds = lambda: 30
    worker._wait_for_coin_prep_post_effect = lambda *_args, **_kwargs: {
        "expected_outputs": [],
        "authoritative_view": {},
    }
    worker._verify_authoritative_post_operation_view = lambda **_kwargs: True
    token = "a" * 64
    operation = {
        "operation_id": "coin-prep:" + "b" * 64,
        "effect_claim_token": token,
        "effect_claim_generation": 1,
        "wallet_identity_json": json.dumps(identity),
    }
    monkeypatch.setattr(
        coin_prep_worker,
        "claim_wallet_effect",
        lambda **_kwargs: {"claim_token": token, "generation": 1},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "prepare_coin_prep_operation",
        lambda **_kwargs: {"operation": operation},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "build_transaction_rpc",
        lambda *_args: events.append("build") or {"summary": {}, "coin_spends": [{}]},
    )
    sealed = {
        "_catalyst_validated_unsigned": True,
        "constructed_outputs": [
            {
                "asset": "cat",
                "address": "xch1owner",
                "amount_mojos": 90,
                "purpose": "replacement",
                "ordinal": 0,
                "coin_id": "3" * 64,
            },
            {
                "asset": "xch",
                "address": "xch1owner",
                "amount_mojos": 20,
                "purpose": "fee_reserve",
                "ordinal": -1,
                "coin_id": "4" * 64,
            },
        ],
    }
    monkeypatch.setattr(
        coin_prep_worker,
        "validate_unsigned_transaction_effect",
        lambda *_args: events.append("validate") or sealed,
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "bind_coin_prep_constructed_outputs",
        lambda *_args, **_kwargs: events.append("bind") or {"operation": operation},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "wallet_effect_claim_is_current",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "begin_wallet_effect_dispatch",
        lambda *_args, **_kwargs: events.append("dispatch") or object(),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "wallet_effect_adapter_dispatch_authority",
        lambda _dispatch: nullcontext(),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "submit_built_transaction_rpc",
        lambda _sealed: events.append("submit") or {"success": True},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "complete_wallet_effect_dispatch",
        lambda *_args, **_kwargs: "SUBMITTED",
    )
    worker._record_coin_prep_dispatch_outcome = lambda *_args, **_kwargs: events.append(
        "record"
    )

    assert worker._submit_direct_batch_plan(plan, "xch1owner") is True
    assert events[:5] == ["build", "validate", "bind", "dispatch", "submit"]


def test_direct_batch_prepare_persistence_failure_retains_claim_without_dispatch(
    monkeypatch,
):
    worker = _worker()
    source = "1" * 64
    plan = BatchPlan(
        asset="xch",
        source_coin_ids=(source,),
        fee_source_id=None,
        outputs=(PlannedOutput("xch", "replacement", 90, 0),),
        reused_coin_ids=(),
        reused_target_ids=(),
        fee_mojos=10,
    )
    token = "a" * 64
    retained = []
    built = []
    worker._current_coin_prep_wallet_identity = lambda: {"backend": "sage"}
    monkeypatch.setattr(
        coin_prep_worker,
        "claim_wallet_effect",
        lambda **_kwargs: {"claim_token": token, "generation": 4},
    )

    def fail_prepare(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(coin_prep_worker, "prepare_coin_prep_operation", fail_prepare)
    monkeypatch.setattr(
        coin_prep_worker,
        "retain_wallet_effect_claim_for_reconciliation",
        lambda claim_token, generation, *, reason_code: retained.append(
            (claim_token, generation, reason_code)
        ),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "build_transaction_rpc",
        lambda *_args: built.append(True),
    )

    assert worker._submit_direct_batch_plan(plan, "xch1owner") is False
    assert retained == [
        (token, 4, "DIRECT_BATCH_PREPARED_PERSIST_FAILED")
    ]
    assert built == []


def test_direct_batch_output_binding_failure_retains_claim_without_dispatch(
    monkeypatch,
):
    worker = _worker()
    source = "1" * 64
    plan = BatchPlan(
        asset="xch",
        source_coin_ids=(source,),
        fee_source_id=None,
        outputs=(PlannedOutput("xch", "replacement", 90, 0),),
        reused_coin_ids=(),
        reused_target_ids=(),
        fee_mojos=10,
    )
    token = "a" * 64
    operation = {
        "operation_id": "coin-prep:" + "b" * 64,
        "effect_claim_token": token,
        "effect_claim_generation": 5,
        "wallet_identity_json": json.dumps({"backend": "sage"}),
    }
    retained = []
    dispatched = []
    worker._current_coin_prep_wallet_identity = lambda: {"backend": "sage"}
    monkeypatch.setattr(
        coin_prep_worker,
        "claim_wallet_effect",
        lambda **_kwargs: {"claim_token": token, "generation": 5},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "prepare_coin_prep_operation",
        lambda **_kwargs: {"operation": operation},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "build_transaction_rpc",
        lambda *_args: {"summary": {}, "coin_spends": [{}]},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "validate_unsigned_transaction_effect",
        lambda *_args: {
            "_catalyst_validated_unsigned": True,
            "constructed_outputs": [
                {
                    "asset": "xch",
                    "address": "xch1owner",
                    "amount_mojos": 90,
                    "purpose": "replacement",
                    "ordinal": 0,
                    "coin_id": "3" * 64,
                }
            ],
        },
    )

    def fail_binding(*_args, **_kwargs):
        raise RuntimeError("binding unavailable")

    monkeypatch.setattr(
        coin_prep_worker, "bind_coin_prep_constructed_outputs", fail_binding
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "retain_wallet_effect_claim_for_reconciliation",
        lambda claim_token, generation, *, reason_code: retained.append(
            (claim_token, generation, reason_code)
        ),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "begin_wallet_effect_dispatch",
        lambda *_args, **_kwargs: dispatched.append(True),
    )

    with pytest.raises(
        coin_prep_worker.CoinPrepAuthorityUnresolved,
        match="output binding",
    ):
        worker._submit_direct_batch_plan(plan, "xch1owner")

    assert retained == [
        (token, 5, "DIRECT_BATCH_OUTPUT_BINDING_FAILED")
    ]
    assert dispatched == []


def test_uninspectable_unsigned_batch_records_proven_no_effect_for_fallback(
    monkeypatch,
):
    worker = _worker()
    source = "1" * 64
    plan = BatchPlan(
        asset="xch",
        source_coin_ids=(source,),
        fee_source_id=None,
        outputs=(PlannedOutput("xch", "replacement", 90, 0),),
        reused_coin_ids=(),
        reused_target_ids=(),
        fee_mojos=10,
    )
    token = "a" * 64
    operation = {
        "operation_id": "coin-prep:" + "b" * 64,
        "effect_claim_token": token,
        "effect_claim_generation": 6,
        "wallet_identity_json": json.dumps({"backend": "sage"}),
    }
    recorded = []
    worker._current_coin_prep_wallet_identity = lambda: {"backend": "sage"}
    monkeypatch.setattr(
        coin_prep_worker,
        "claim_wallet_effect",
        lambda **_kwargs: {"claim_token": token, "generation": 6},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "prepare_coin_prep_operation",
        lambda **_kwargs: {"operation": operation},
    )
    monkeypatch.setattr(
        coin_prep_worker, "build_transaction_rpc", lambda *_args: {"success": True}
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "validate_unsigned_transaction_effect",
        lambda *_args: {
            "success": False,
            "reason": "UNSIGNED_EFFECT_NOT_INSPECTABLE",
        },
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "wallet_effect_claim_is_current",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "begin_wallet_effect_dispatch",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "wallet_effect_adapter_dispatch_authority",
        lambda _dispatch: nullcontext(),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "submit_built_transaction_rpc",
        lambda _invalid: {"success": False, "_catalyst_effect_attempted": False},
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "complete_wallet_effect_dispatch",
        lambda *_args, **_kwargs: "RELEASED_NO_EFFECT",
    )
    worker._record_coin_prep_dispatch_outcome = (
        lambda *_args, **kwargs: recorded.append(kwargs)
    )

    assert worker._submit_direct_batch_plan(plan, "xch1owner") is False
    assert worker.status.compatibility_reason == "UNSIGNED_EFFECT_NOT_INSPECTABLE"
    assert recorded == [
        {
            "dispatch_outcome": "RELEASED_NO_EFFECT",
            "reason_code": "DIRECT_BATCH_RELEASED_NO_EFFECT_UNRECONCILED",
        }
    ]


def test_uninspectable_unsigned_batch_enters_compatibility_before_any_effect(
    monkeypatch,
):
    worker = _worker()
    worker.xch_tier_counts = {"tier": 1}
    worker.cat_tier_counts = {"tier": 1}
    monkeypatch.setattr(
        wallet, "get_next_address", lambda *_args, **_kwargs: {"address": "xch1owner"}
    )
    monkeypatch.setenv("XCH_RESERVE", "0")
    worker._direct_batch_snapshot = lambda _targets: CoinSnapshot(
        (
            _coin("cat", "c" * 64, 100),
            _coin("xch", "f" * 64, 20),
            _coin("xch", "a" * 64, 100),
        )
    )

    def unsupported(_plan, _address):
        worker.status.compatibility_reason = "UNSIGNED_EFFECT_NOT_INSPECTABLE"
        return False

    worker._submit_direct_batch_plan = unsupported

    assert worker._run_direct_batch_prep() is None
    assert worker.status.batch_confirmed == 0
