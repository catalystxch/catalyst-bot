"""Direct Coin Prep runner coverage under explicit approved fee pricing.

Low-level journal/hold/dispatch behavior lives in the dedicated fee-worker
tests. This module retains wallet-shape and confirmation regressions while
ensuring the runner never re-enters the retired manual-fee compatibility path.
"""

import threading
from decimal import Decimal
from types import SimpleNamespace

import pytest

import coin_prep_worker
from coin_prep_batch_plan import BatchPlan, PlannedOutput, SelectableCoin


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
    worker.update_status = lambda phase=None, progress=None, message=None, error=None: None
    worker.log = lambda _message: None
    return worker


def _approved_worker():
    worker = _worker()
    worker.fee_approval_id = "a" * 64
    return worker


def _coin(asset, coin_id, amount, purpose=""):
    return SelectableCoin(asset, coin_id, amount, purpose)


def _priced(plan, *, target_count=1):
    return {
        "available": True,
        "reason": "ready" if plan.transaction_required else "already_prepared",
        "receive_address": "xch1owner",
        "recipe": {"targets": tuple(object() for _ in range(target_count))},
        "pricing": {"plan": plan},
        "dispatch_authorized": False,
    }


def _complete_plan(target_count):
    return BatchPlan(
        asset="",
        source_coin_ids=(),
        fee_source_id=None,
        outputs=(),
        reused_coin_ids=tuple(f"{index:064x}" for index in range(target_count)),
        reused_target_ids=tuple(("xch", index) for index in range(target_count)),
        fee_mojos=0,
        transaction_required=False,
    )


def test_direct_snapshot_labels_database_reserve_for_floor_accounting(monkeypatch):
    worker = _worker()
    reserve_id = "a" * 64
    source_id = "b" * 64
    monkeypatch.setattr(
        coin_prep_worker,
        "get_reserve_coins",
        lambda wallet_type: [{"coin_id": reserve_id}] if wallet_type == "xch" else [],
    )
    monkeypatch.setattr(
        coin_prep_worker, "get_coin_reconciliation_protected_ids", lambda _coin_ids: []
    )
    worker._get_coins_via_rpc = lambda wallet_id, *_args, **_kwargs: (
        [
            {"coin_id": reserve_id, "amount_mojos": 30},
            {"coin_id": source_id, "amount_mojos": 20},
        ]
        if wallet_id == worker.xch_wallet_id
        else []
    )
    target = SimpleNamespace(
        asset="xch", amount_mojos=10, purpose="mid", tier_rank=0, ordinal=0
    )

    snapshot = worker._direct_batch_snapshot((target,))

    reserve = next(item for item in snapshot.coins if item.coin_id == reserve_id)
    assert reserve.protected is True
    assert reserve.purpose == "reserve"


def test_direct_snapshot_excludes_durably_protected_wallet_effect_coin(monkeypatch):
    worker = _worker()
    protected_id = "a" * 64
    safe_id = "b" * 64
    monkeypatch.setattr(coin_prep_worker, "get_reserve_coins", lambda _kind: [])
    monkeypatch.setattr(
        coin_prep_worker,
        "get_coin_reconciliation_protected_ids",
        lambda coin_ids: (
            [protected_id]
            if protected_id in {str(value).removeprefix("0x") for value in coin_ids}
            else []
        ),
    )
    worker._get_coins_via_rpc = lambda wallet_id, *_args, **_kwargs: (
        [
            {"coin_id": protected_id, "amount_mojos": 20},
            {"coin_id": safe_id, "amount_mojos": 20},
        ]
        if wallet_id == worker.xch_wallet_id
        else []
    )
    target = SimpleNamespace(
        asset="xch", amount_mojos=10, purpose="mid", tier_rank=0, ordinal=0
    )

    snapshot = worker._direct_batch_snapshot((target,))

    assert [coin.coin_id for coin in snapshot.coins] == [safe_id]


def test_approved_wallet_shape_uses_one_cat_and_one_xch_final_batch(monkeypatch):
    worker = _approved_worker()
    cat_plan = BatchPlan(
        "cat",
        ("c" * 64,),
        "f" * 64,
        tuple(PlannedOutput("cat", "replacement", 10, index) for index in range(76))
        + (PlannedOutput("xch", "fee_change", 20, -1),),
        (),
        (),
        7,
    )
    xch_plan = BatchPlan(
        "xch",
        ("a" * 64,),
        None,
        tuple(PlannedOutput("xch", "replacement", 10, index) for index in range(126))
        + (PlannedOutput("xch", "change", 740, -1),),
        (),
        (),
        11,
    )
    priced = iter(
        (
            _priced(cat_plan, target_count=202),
            _priced(xch_plan, target_count=202),
            _priced(_complete_plan(202), target_count=202),
        )
    )
    monkeypatch.setattr(
        "coin_prep_fee_dispatch.price_approved_prep_batch",
        lambda _approval_id: next(priced),
    )
    submitted = []
    worker._submit_direct_batch_plan = lambda plan, _address, *, priced_batch: (
        submitted.append(plan) or True
    )

    assert worker._run_direct_batch_prep() is True
    assert [plan.asset for plan in submitted] == ["cat", "xch"]
    assert [len(plan.outputs) for plan in submitted] == [77, 127]
    assert worker.status.batch_confirmed == 2
    assert worker.status.paid_fee_mojos == 18


def test_unpriced_compatibility_refusal_pauses_without_legacy_fallback(monkeypatch):
    worker = _approved_worker()
    submitted = []
    worker._submit_direct_batch_plan = lambda *args, **kwargs: submitted.append(
        (args, kwargs)
    )
    monkeypatch.setattr(
        "coin_prep_fee_dispatch.price_approved_prep_batch",
        lambda _approval_id: {
            "available": False,
            "reason": "FEE_PREP_COMPATIBILITY_UNSUPPORTED",
            "dispatch_authorized": False,
        },
    )

    with pytest.raises(ValueError, match="FEE_PREP_COMPATIBILITY_UNSUPPORTED"):
        worker._run_direct_batch_prep()
    assert submitted == []
    assert worker.status.batch_confirmed == 0


def test_direct_batch_never_falls_back_after_a_confirmed_effect(monkeypatch):
    worker = _approved_worker()
    plan = BatchPlan(
        "cat",
        ("c" * 64,),
        "f" * 64,
        (PlannedOutput("cat", "replacement", 10, 0),),
        (),
        (),
        7,
    )
    priced = iter(
        (
            _priced(plan),
            {
                "available": False,
                "reason": "FEE_EFFECT_RECOVERY_REQUIRED",
                "dispatch_authorized": False,
            },
        )
    )
    monkeypatch.setattr(
        "coin_prep_fee_dispatch.price_approved_prep_batch",
        lambda _approval_id: next(priced),
    )
    submitted = []
    worker._submit_direct_batch_plan = lambda plan, _address, *, priced_batch: (
        submitted.append(plan) or True
    )

    with pytest.raises(ValueError, match="FEE_EFFECT_RECOVERY_REQUIRED"):
        worker._run_direct_batch_prep()
    assert submitted == [plan]


def test_submitted_batch_wait_persists_live_confirmation_elapsed(monkeypatch):
    worker = _worker()
    clock = {"now": 0.0}
    persisted = []
    monkeypatch.setattr(coin_prep_worker.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        coin_prep_worker.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    worker._observe_coin_prep_post_effect = lambda _operation: (
        {"confirmed": True} if clock["now"] >= 15 else None
    )
    worker.update_status = lambda **_kwargs: persisted.append(
        worker.status.confirmation_elapsed_seconds
    )

    result = worker._wait_for_coin_prep_post_effect(
        {"operation_id": "coin-prep:" + "1" * 64}, timeout_s=30, poll_interval_s=5
    )

    assert result == {"confirmed": True}
    assert persisted == [5, 10, 15]
    assert worker.status.confirmation_elapsed_seconds == 15


def test_submitted_batch_does_not_confirm_while_exact_sage_tx_is_pending(monkeypatch):
    worker = _worker()
    clock = {"now": 0.0}
    txid = "3" * 64
    pending_views = iter(
        ([{"transaction_id": "0x" + txid}], [{"transaction_id": "4" * 64}])
    )
    observations = []
    monkeypatch.setattr(coin_prep_worker.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        coin_prep_worker.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    monkeypatch.setattr(
        coin_prep_worker, "get_pending_transactions", lambda: next(pending_views)
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "get_transaction_relay_outcome",
        lambda transaction_id: {"status": "accepted", "transaction_id": transaction_id},
    )
    worker._observe_coin_prep_post_effect = lambda _operation: (
        observations.append(clock["now"]) or {"confirmed": True}
    )
    worker.update_status = lambda **_kwargs: None

    result = worker._wait_for_coin_prep_post_effect(
        {"operation_id": "coin-prep:" + "1" * 64},
        transaction_id=txid,
        timeout_s=30,
        poll_interval_s=5,
    )

    assert result == {"confirmed": True}
    assert observations == [10]
    assert worker.status.confirmation_elapsed_seconds == 10


def test_submitted_batch_fails_closed_when_sage_pending_view_is_unavailable(monkeypatch):
    worker = _worker()
    clock = {"now": 0.0}
    observations = []
    monkeypatch.setattr(coin_prep_worker.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        coin_prep_worker.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    monkeypatch.setattr(coin_prep_worker, "get_pending_transactions", lambda: None)
    monkeypatch.setattr(
        coin_prep_worker,
        "get_transaction_relay_outcome",
        lambda transaction_id: {"status": "accepted", "transaction_id": transaction_id},
    )
    worker._observe_coin_prep_post_effect = lambda _operation: observations.append(True)
    worker.update_status = lambda **_kwargs: None

    result = worker._wait_for_coin_prep_post_effect(
        {"operation_id": "coin-prep:" + "1" * 64},
        transaction_id="5" * 64,
        timeout_s=15,
        poll_interval_s=5,
    )

    assert result is None
    assert observations == []


def test_network_priced_high_fee_is_reflected_without_legacy_fee_floor(monkeypatch):
    worker = _approved_worker()
    plan = BatchPlan(
        "xch",
        ("a" * 64,),
        None,
        (PlannedOutput("xch", "replacement", 10, 0),),
        (),
        (),
        3_881_141_382,
    )
    priced = iter((_priced(plan), _priced(_complete_plan(1))))
    monkeypatch.setattr(
        "coin_prep_fee_dispatch.price_approved_prep_batch",
        lambda _approval_id: next(priced),
    )
    submitted = []
    worker._submit_direct_batch_plan = lambda plan, _address, *, priced_batch: (
        submitted.append(plan) or True
    )

    assert worker._run_direct_batch_prep() is True
    assert submitted == [plan]
    assert worker.status.planned_fee_mojos == 3_881_141_382
    assert worker.status.paid_fee_mojos == 3_881_141_382


def test_direct_batch_relay_safe_fee_preserves_explicit_zero():
    worker = _worker()
    worker._tx_fee_mojos = lambda: 0
    plan = BatchPlan(
        asset="xch",
        source_coin_ids=("1" * 64,),
        fee_source_id=None,
        outputs=tuple(
            PlannedOutput("xch", "fees", 1_000_000_000, ordinal)
            for ordinal in range(42)
        ),
        reused_coin_ids=(),
        reused_target_ids=(),
        fee_mojos=0,
    )

    assert worker._direct_batch_relay_safe_fee_mojos(plan) == 0


def test_submitted_batch_surfaces_sage_relay_rejection_and_bounds_wait(monkeypatch):
    worker = _worker()
    clock = {"now": 0.0}
    messages = []
    txid = "2" * 64
    monkeypatch.setattr(coin_prep_worker.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        coin_prep_worker.time,
        "sleep",
        lambda seconds: clock.__setitem__("now", clock["now"] + seconds),
    )
    monkeypatch.setattr(
        coin_prep_worker,
        "get_transaction_relay_outcome",
        lambda transaction_id: {
            "status": "rejected",
            "transaction_id": transaction_id,
            "reason_code": "INVALID_FEE_TOO_CLOSE_TO_ZERO",
            "source": "sage_native_log",
        },
    )
    monkeypatch.setattr(coin_prep_worker, "get_pending_transactions", lambda: [])
    worker._observe_coin_prep_post_effect = lambda _operation: None
    worker.update_status = lambda **_kwargs: None
    worker.log = messages.append

    result = worker._wait_for_coin_prep_post_effect(
        {"operation_id": "coin-prep:" + "1" * 64},
        transaction_id=txid,
        timeout_s=900,
        poll_interval_s=5,
    )

    assert result["relay_rejection"]["reason_code"] == "INVALID_FEE_TOO_CLOSE_TO_ZERO"
    assert clock["now"] <= 65
    assert "Sage relay rejected" in "\n".join(messages)
    assert "INVALID_FEE_TOO_CLOSE_TO_ZERO" in worker.status.message


def test_approved_runner_uses_bounded_xch_prerequisite_after_cat_is_prepared(
    monkeypatch,
):
    worker = _approved_worker()
    prerequisite = BatchPlan(
        "xch",
        tuple(f"{index + 20_000:064x}" for index in range(50)),
        None,
        (PlannedOutput("xch", "change", 990, -1),),
        (),
        (),
        13,
    )
    final = BatchPlan(
        "xch",
        tuple(f"{index + 30_000:064x}" for index in range(15)),
        None,
        tuple(PlannedOutput("xch", "replacement", 10, index) for index in range(126))
        + (PlannedOutput("xch", "change", 320, -1),),
        (),
        (),
        17,
    )
    priced = iter(
        (
            _priced(prerequisite, target_count=202),
            _priced(final, target_count=202),
            _priced(_complete_plan(202), target_count=202),
        )
    )
    monkeypatch.setattr(
        "coin_prep_fee_dispatch.price_approved_prep_batch",
        lambda _approval_id: next(priced),
    )
    submitted = []
    worker._submit_direct_batch_plan = lambda plan, _address, *, priced_batch: (
        submitted.append(plan) or True
    )

    assert worker._run_direct_batch_prep() is True
    assert [plan.asset for plan in submitted] == ["xch", "xch"]
    assert [len(plan.source_coin_ids) for plan in submitted] == [50, 15]
    assert submitted[0].outputs[0].purpose == "change"
    assert worker.status.batch_confirmed == 2
    assert worker.status.paid_fee_mojos == 30


def test_uninspectable_unsigned_batch_pauses_before_any_effect(monkeypatch):
    worker = _approved_worker()
    submitted = []
    worker._submit_direct_batch_plan = lambda *args, **kwargs: submitted.append(
        (args, kwargs)
    )
    monkeypatch.setattr(
        "coin_prep_fee_dispatch.price_approved_prep_batch",
        lambda _approval_id: {
            "available": False,
            "reason": "FEE_UNSIGNED_COST_UNAVAILABLE",
            "dispatch_authorized": False,
        },
    )

    with pytest.raises(ValueError, match="FEE_UNSIGNED_COST_UNAVAILABLE"):
        worker._run_direct_batch_prep()
    assert submitted == []
    assert worker.status.batch_confirmed == 0
