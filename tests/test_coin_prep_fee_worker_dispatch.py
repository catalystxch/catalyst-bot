"""The real prep worker must hold consent-bound fees before adapter dispatch."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from importlib import import_module
import json
import threading

import pytest

import fee_approval_test_utils as utils
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


@pytest.fixture
def active_worker(approved, monkeypatch):
    database = import_module("database")
    gate = import_module("mutation_gate")
    module = import_module("coin_prep_worker")
    monkeypatch.setenv("CAT_ASSET_ID", utils.ASSET)

    def cleanup():
        with database._wallet_effect_process_authorities_lock:
            authorities = list(database._wallet_effect_process_authorities.values())
            database._wallet_effect_process_authorities.clear()
        for authority in authorities:
            gate.exit_wallet_mutation(authority.permit)
        gate.shutdown_runtime()
        gate.clear_worker_authority_environment()

    cleanup()
    when = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(gate, "_utc_now", lambda: when)
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: "2026-08-21T12:00:00.000000Z")
    binding = gate.WalletIdentityBinding(
        backend="sage", name="TEST 7", fingerprint=736588221, network_id="mainnet",
        kind="bls", has_secrets=True,
        bound_at_utc=(when - timedelta(seconds=1)).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        maximum_age_seconds=15)
    runtime = gate.initialize(
        run_id="fee-worker-test", owner_pid=111, owner_host="test-host",
        wallet_fingerprint_hash=gate.wallet_fingerprint_hash(binding.fingerprint),
        network="mainnet", lease_seconds=30, start_heartbeat=False,
        wallet_identity_binding=binding, wallet_adapter_authority=object())
    assert runtime.last_acquire_result["acquired"] is True
    priced = import_module("coin_prep_fee_dispatch").price_approved_prep_batch(approved["approval"]["approval_id"])
    for coin in priced["snapshot"].coins:
        database.upsert_coin(coin.coin_id, coin.asset, coin.amount_mojos, purpose="replacement")
    worker = module.CoinPrepWorker.__new__(module.CoinPrepWorker)
    worker.fee_approval_id = approved["approval"]["approval_id"]
    worker.is_sage = True
    worker.tier_enabled = True
    worker._db_ready = True
    worker._is_subprocess = False
    worker.xch_wallet_id = 1
    worker.cat_wallet_id = 2
    worker.status_lock = threading.Lock()
    worker.status = module.CoinPrepStatus(
        phase="idle", progress=0, message="", xch_coins_current=0,
        xch_coins_target=3, cat_coins_current=0, cat_coins_target=1)
    worker.log = lambda _message: None
    worker.update_status = lambda *args, **kwargs: None
    approved.update(worker=worker, module=module, priced=priced, adapter_attempts=[])

    def adapter_probe(unsigned):
        # Only this external signing/submission boundary is substituted. Pricing,
        # executable inspection, claims, journal, hold and dispatch fence are real.
        account = database.get_fee_approval(approved["approval"]["approval_id"])
        approved["adapter_attempts"].append({
            "held": account["held_fee_mojos"],
            "executable": unsigned.get("_catalyst_executable_effect_bound"),
            "reservations": utils._counts()["approved_fee_reservations"],
        })
        raise RuntimeError("external adapter observation unavailable")

    monkeypatch.setattr(module, "submit_built_transaction_rpc", adapter_probe)
    yield approved
    cleanup()


def _submit(state, plan=None):
    return state["worker"]._submit_direct_batch_plan(
        state["priced"]["pricing"]["plan"] if plan is None else plan, utils.ADDRESS)


def test_missing_fee_consent_stops_worker_before_claim_or_signing(active_worker):
    active_worker["worker"].fee_approval_id = None
    with pytest.raises(ValueError, match="FEE_APPROVAL_REQUIRED"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []
    assert utils._counts()["wallet_effect_claims"] == 0
    assert utils._counts()["coin_prep_operations"] == 0


def test_unknown_fee_reference_cannot_use_other_approval(active_worker):
    active_worker["worker"].fee_approval_id = "f" * 64
    with pytest.raises(ValueError, match="FEE_APPROVAL_REQUIRED"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []
    assert utils._counts()["wallet_effect_claims"] == 0


def test_worker_holds_exact_fee_before_existing_dispatch_fence(active_worker):
    with pytest.raises(RuntimeError, match="external adapter observation unavailable"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == [{"held": 20, "executable": True, "reservations": 1}]
    assert utils._counts()["wallet_effect_claims"] == 1
    account = import_module("database").get_fee_approval(active_worker["approval"]["approval_id"])
    assert account["held_fee_mojos"] == 20
    assert account["spent_fee_mojos"] == 0
    assert account["remaining_preparation_fee_mojos"] == 20


def test_worker_cannot_submit_caller_fee_instead_of_fresh_exact_quote(active_worker):
    wrong = replace(active_worker["priced"]["pricing"]["plan"], fee_mojos=21)
    with pytest.raises(ValueError, match="FEE_DISPATCH_PLAN_MISMATCH"):
        _submit(active_worker, wrong)
    assert active_worker["adapter_attempts"] == []
    assert utils._counts()["wallet_effect_claims"] == 0


def test_worker_does_not_borrow_cancel_cover_when_network_fee_rises(active_worker, monkeypatch):
    def quote(cost, target_seconds):
        return {"available": True, "fee_mojos": 41, "source": "coinset", "cost": cost,
                "target_seconds": target_seconds, "observed_at": 1000, "expires_at": 1060}
    monkeypatch.setattr(import_module("coin_prep_fee_pricing"), "quote_fee", quote)
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []
    assert utils._counts()["wallet_effect_claims"] == 0
    assert utils._counts()["approved_fee_reservations"] == 0


def test_provider_failure_cannot_use_worker_manual_fee(active_worker, monkeypatch):
    active_worker["worker"]._tx_fee_mojos = lambda: 999999999
    monkeypatch.setattr(import_module("coin_prep_fee_pricing"), "quote_fee", lambda *args, **kwargs: {
        "available": False, "reason": "provider unavailable"})
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []
    assert utils._counts()["wallet_effect_claims"] == 0


def test_changed_settings_after_hold_stop_worker_before_signing(active_worker, monkeypatch):
    service = import_module("coin_prep_fee_dispatch")
    reserve = service.reserve_approved_prep_dispatch

    def change_after_hold(**kwargs):
        result = reserve(**kwargs)
        active_worker["config"].XCH_RESERVE = 1
        return result

    monkeypatch.setattr(service, "reserve_approved_prep_dispatch", change_after_hold)
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []
    # Stopping/crashing does not manufacture authoritative no-effect proof.
    account = import_module("database").get_fee_approval(active_worker["approval"]["approval_id"])
    assert account["held_fee_mojos"] == 20


def test_expired_quote_after_hold_stops_worker_before_signing(active_worker, monkeypatch):
    service = import_module("coin_prep_fee_dispatch")
    reserve = service.reserve_approved_prep_dispatch

    def expire_after_hold(**kwargs):
        result = reserve(**kwargs)
        active_worker["now"] = 1060
        return result

    monkeypatch.setattr(service, "reserve_approved_prep_dispatch", expire_after_hold)
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []


def test_direct_runner_uses_frozen_pricing_without_worker_price_or_fee_floor(active_worker):
    def forbidden(*args, **kwargs):
        pytest.fail("runner regenerated approved economic targets or flat duststorm fee")
    worker = active_worker["worker"]
    worker._direct_batch_targets = forbidden
    worker._direct_batch_snapshot = forbidden
    worker._direct_batch_relay_safe_fee_mojos = forbidden
    worker._direct_batch_exact_relay_safe_fee_mojos = forbidden
    worker._tx_fee_mojos = forbidden
    with pytest.raises(RuntimeError, match="external adapter observation unavailable"):
        worker._run_direct_batch_prep()
    assert active_worker["adapter_attempts"] == [{"held": 20, "executable": True, "reservations": 1}]


def test_unsupported_worker_mode_pauses_instead_of_entering_legacy_mutations(
    active_worker,
):
    worker = active_worker["worker"]
    worker.tier_enabled = False

    with pytest.raises(ValueError, match="FEE_DISPATCH_UNSUPPORTED"):
        worker._run_direct_batch_prep()

    assert active_worker["adapter_attempts"] == []


def test_quote_expired_while_entering_dispatch_fence_cannot_reach_adapter(active_worker, monkeypatch):
    original = active_worker["module"].begin_wallet_effect_dispatch

    def expired_before_fence(*args, **kwargs):
        active_worker["now"] = 1060
        return original(*args, **kwargs)

    monkeypatch.setattr(active_worker["module"], "begin_wallet_effect_dispatch", expired_before_fence)
    with pytest.raises(ValueError, match="FEE_QUOTE_STALE"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []


def test_root_designated_reserve_at_dispatch_fence_cannot_reach_adapter(active_worker, monkeypatch):
    original = active_worker["module"].begin_wallet_effect_dispatch
    source = active_worker["priced"]["pricing"]["plan"].source_coin_ids[0]

    def reserve_before_fence(*args, **kwargs):
        import_module("database").set_coin_designation(source, "reserve")
        return original(*args, **kwargs)

    monkeypatch.setattr(active_worker["module"], "begin_wallet_effect_dispatch", reserve_before_fence)
    with pytest.raises(ValueError, match="FEE_EFFECT_NOT_DISPATCHABLE"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []


def test_superseded_approval_at_dispatch_fence_cannot_reach_adapter(active_worker, monkeypatch):
    original = active_worker["module"].begin_wallet_effect_dispatch
    account = active_worker["approval"]

    def change_before_fence(*args, **kwargs):
        import_module("database").create_fee_approval(
            scope_sha256=account["scope_sha256"], plan_sha256=account["plan_sha256"],
            total_fee_mojos=80, cancellation_reserve_mojos=40)
        return original(*args, **kwargs)

    monkeypatch.setattr(active_worker["module"], "begin_wallet_effect_dispatch", change_before_fence)
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []


def test_quote_expired_after_fence_cannot_reach_adapter(active_worker, monkeypatch):
    original = active_worker["module"].begin_wallet_effect_dispatch

    def expire_after_fence(*args, **kwargs):
        result = original(*args, **kwargs)
        active_worker["now"] = 1060
        return result

    monkeypatch.setattr(active_worker["module"], "begin_wallet_effect_dispatch", expire_after_fence)
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []


def test_post_effect_observer_receives_journal_bound_constructed_additions(active_worker, monkeypatch):
    observed = []
    monkeypatch.setattr(active_worker["module"], "submit_built_transaction_rpc", lambda _unsigned: {
        "success": True, "transaction_id": "a" * 64})
    worker = active_worker["worker"]
    worker._submitted_split_verify_timeout_seconds = lambda: 1

    def observe(operation, **kwargs):
        observed.append(operation)
        raise RuntimeError("external post-effect observation unavailable")

    worker._wait_for_coin_prep_post_effect = observe
    with pytest.raises(RuntimeError, match="external post-effect observation unavailable"):
        _submit(active_worker)
    assert len(observed) == 1
    assert isinstance(observed[0].get("constructed_outputs_json"), str), "worker lost exact additions bound by fee service"
    assert observed[0]["outcome"] == "SUBMITTED_UNKNOWN"
    plan = active_worker["priced"]["pricing"]["plan"]
    assert [coin_id.removeprefix("0x") for coin_id in json.loads(observed[0]["effect_fee_coin_ids_json"])] == (
        [plan.fee_source_id] if plan.fee_source_id else [])


def test_prepared_journal_write_failure_retains_claim_without_hold_or_signing(active_worker, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("injected journal write failure")
    monkeypatch.setattr(active_worker["module"], "prepare_coin_prep_operation", fail)
    assert _submit(active_worker) is False
    assert active_worker["adapter_attempts"] == []
    assert utils._counts()["approved_fee_reservations"] == 0
    assert utils._counts()["wallet_effect_claims"] == 1


def test_constructed_output_write_failure_retains_claim_without_hold_or_signing(active_worker, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("injected output binding failure")
    monkeypatch.setattr(import_module("database"), "bind_coin_prep_constructed_outputs", fail)
    with pytest.raises(RuntimeError, match="injected output binding failure"):
        _submit(active_worker)
    assert active_worker["adapter_attempts"] == []
    assert utils._counts()["approved_fee_reservations"] == 0
    assert utils._counts()["wallet_effect_claims"] == 1


def test_worker_success_boundary_records_authoritative_session_completion(active_worker):
    runtime = import_module("coin_prep_fee_runtime")
    context = runtime.read_approved_prep_fee_snapshot(
        active_worker["approval"]["approval_id"]
    )
    active_worker["xch"] = [
        utils._coin(40000 + index, str(target.amount_mojos))
        for index, target in enumerate(context["recipe"]["targets"])
        if target.asset == "xch"
    ]
    active_worker["cat"] = [
        utils._coin(50000 + index, str(target.amount_mojos))
        for index, target in enumerate(context["recipe"]["targets"])
        if target.asset == "cat"
    ]

    result = active_worker["worker"]._complete_approved_fee_session()

    assert result["approval_id"] == active_worker["approval"]["approval_id"]
    assert result["target_count"] == len(context["recipe"]["targets"])
    assert result["dispatch_authorized"] is False


def test_existing_target_shortcut_cannot_report_complete_before_fee_session_closes(
    active_worker, monkeypatch,
):
    worker = active_worker["worker"]
    statuses = []
    worker.update_status = lambda phase, progress, message, **kwargs: statuses.append(
        (phase, progress, message, kwargs)
    )
    worker.verify_coins = lambda: (4, 2)
    worker._designate_final_sweep = lambda: None
    worker._record_prep_reserve_advisory_baseline = lambda: None
    worker._save_successful_prep_settings = lambda *_args: None
    monkeypatch.setattr(
        worker, "_complete_approved_fee_session",
        lambda: (_ for _ in ()).throw(ValueError("FEE_SESSION_INCOMPLETE")),
    )

    with pytest.raises(ValueError, match="FEE_SESSION_INCOMPLETE"):
        worker._complete_existing_tier_preparation()
    assert all(phase != active_worker["module"].PrepPhase.COMPLETE for phase, *_ in statuses)
