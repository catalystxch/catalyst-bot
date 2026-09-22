"""Actual unsigned pricing under consent cannot consume cancellation cover."""

from importlib import import_module
from datetime import datetime, timedelta, timezone
import time
from types import SimpleNamespace
import sqlite3

import pytest

import database
import fee_approval_test_utils as utils
import mutation_gate
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


@pytest.fixture(autouse=True)
def current_project_modules():
    global database, mutation_gate
    database = import_module("database")
    mutation_gate = import_module("mutation_gate")


def _price(state):
    try:
        service = import_module("coin_prep_fee_dispatch")
    except ModuleNotFoundError:
        pytest.fail("approved exact pre-dispatch pricing boundary is missing")
    return service.price_approved_prep_batch(state["approval"]["approval_id"])


def _network_quote(state, monkeypatch, fee):
    def quote(cost, target_seconds):
        return {"available": True, "fee_mojos": fee, "source": "coinset", "cost": cost,
                "target_seconds": target_seconds, "observed_at": state["now"],
                "expires_at": state["now"] + 60}
    monkeypatch.setattr(import_module("coin_prep_fee_pricing"), "quote_fee", quote)


def test_actual_unsigned_fee_can_rise_inside_approved_preparation_allowance(approved, monkeypatch):
    _network_quote(approved, monkeypatch, 30)
    result = _price(approved)
    assert result["available"] is True
    assert result["pricing"]["plan"].fee_mojos == 30
    assert result["pricing"]["inspection"]["cost"] > 0
    assert result["pricing"]["quote"]["cost"] == result["pricing"]["inspection"]["cost"]
    assert result["approval"]["remaining_preparation_fee_mojos"] == 40
    assert result["dispatch_authorized"] is False
    assert utils._counts()["approved_fee_reservations"] == 0
    assert utils._counts()["wallet_effect_claims"] == 0


def test_higher_fee_cannot_consume_protected_cancellation_allowance(approved, monkeypatch):
    _network_quote(approved, monkeypatch, 41)
    result = _price(approved)
    assert result["available"] is False
    assert result["reason"] == "FEE_BUDGET_EXCEEDED"
    assert result["required_fee_mojos"] == 41
    assert result["approval"]["remaining_preparation_fee_mojos"] == 40
    assert "pricing" not in result
    assert result["dispatch_authorized"] is False
    assert utils._counts()["approved_fee_reservations"] == 0


def test_existing_unknown_hold_blocks_overlapping_network_repricing(approved, monkeypatch):
    account = approved["approval"]
    database.reserve_approved_fee(
        approval_id=account["approval_id"], scope_sha256=account["scope_sha256"],
        plan_sha256=account["plan_sha256"], operation_id="1" * 64, fee_mojos=15, cancellation=False)
    service = import_module("coin_prep_fee_dispatch")
    monkeypatch.setattr(
        service,
        "read_approved_prep_fee_snapshot",
        lambda _approval_id: pytest.fail(
            "recovery gate must run before fresh wallet inventory reads"
        ),
    )
    result = _price(approved)
    assert result["available"] is False
    assert result["reason"] == "FEE_EFFECT_RECOVERY_REQUIRED"
    assert result["recovery_state"] == "held_before_submission"
    assert result["approval"]["held_fee_mojos"] == 15
    assert result["approval"]["remaining_preparation_fee_mojos"] == 25
    assert utils._counts()["approved_fee_reservations"] == 1


def test_manual_fee_mode_cannot_bypass_unavailable_network_estimate(approved, monkeypatch):
    monkeypatch.setattr(import_module("coin_prep_fee_pricing"), "quote_fee", lambda *_args, **_kwargs: {
        "available": False, "reason": "provider unavailable"})
    result = _price(approved)
    assert result["available"] is False
    assert result["reason"] == "FEE_ESTIMATE_UNAVAILABLE"
    assert "pricing" not in result
    assert result["dispatch_authorized"] is False
    assert utils._counts()["coin_prep_operations"] == 0


def test_configuration_changed_while_building_unsigned_bundle_cannot_be_priced(approved, monkeypatch):
    pricing = import_module("coin_prep_fee_pricing")
    original = pricing.quote_fee

    def change_then_quote(*args, **kwargs):
        approved["config"].TRANSACTION_FEE_MODE = "auto"
        return original(*args, **kwargs)

    monkeypatch.setattr(pricing, "quote_fee", change_then_quote)
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _price(approved)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_missing_consent_stops_before_unsigned_construction(approved):
    approved["approval"]["approval_id"] = "f" * 64
    builds = len(approved["builds"])
    with pytest.raises(ValueError, match="FEE_APPROVAL_REQUIRED"):
        _price(approved)
    assert len(approved["builds"]) == builds


@pytest.fixture
def exact_journal(approved, monkeypatch):
    def clear_runtime():
        with database._wallet_effect_process_authorities_lock:
            authorities = list(database._wallet_effect_process_authorities.values())
            database._wallet_effect_process_authorities.clear()
        for authority in authorities:
            mutation_gate.exit_wallet_mutation(authority.permit)
        mutation_gate.shutdown_runtime()
        mutation_gate.clear_worker_authority_environment()

    clear_runtime()
    when = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(mutation_gate, "_utc_now", lambda: when)
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: "2026-08-21T12:00:00.000000Z")
    monkeypatch.setattr(database, "time", SimpleNamespace(
        time=lambda: approved["now"], time_ns=time.time_ns, monotonic=time.monotonic, sleep=time.sleep))
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage", name="TEST 7", fingerprint=736588221, network_id="mainnet",
        kind="bls", has_secrets=True,
        bound_at_utc=(when - timedelta(seconds=1)).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        maximum_age_seconds=15)
    runtime = mutation_gate.initialize(
        run_id="approved-pricing", owner_pid=111, owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(binding.fingerprint),
        network="mainnet", lease_seconds=30, start_heartbeat=False,
        wallet_identity_binding=binding, wallet_adapter_authority=object())
    assert runtime.last_acquire_result["acquired"] is True
    priced = _price(approved)
    plan = priced["pricing"]["plan"]
    from replacement_capacity import canonical_coin_prep_contract
    canonical = canonical_coin_prep_contract(
        operation_kind="split", purpose="replacement", source_coin_ids=list(plan.source_coin_ids),
        target_contract=priced["pricing"]["inspection"]["target_contract"])
    for coin in priced["snapshot"].coins:
        database.upsert_coin(coin.coin_id, coin.asset, coin.amount_mojos, purpose="replacement")
    claim = database.claim_wallet_effect(
        operation_id=canonical["operation_id"], source_coin_ids=list(plan.source_coin_ids),
        fee_coin_ids=[plan.fee_source_id] if plan.fee_source_id else [])
    assert claim is not None
    database.prepare_coin_prep_operation(
        operation_kind="split", purpose="replacement", source_coin_ids=list(plan.source_coin_ids),
        target_contract=canonical["target_contract"],
        wallet_identity_json=mutation_gate.wallet_identity_binding_payload(binding), evidence_json={},
        effect_claim_token=claim["claim_token"], effect_claim_generation=claim["generation"])
    approved.update(priced=priced, operation_id=canonical["operation_id"])
    yield approved
    clear_runtime()


def _reserve(state):
    boundary = getattr(import_module("coin_prep_fee_dispatch"), "reserve_approved_prep_dispatch", None)
    assert callable(boundary), "validated exact pricing is not connected to the atomic dispatch hold"
    return boundary(approval_id=state["approval"]["approval_id"],
                    operation_id=state["operation_id"], priced_batch=state["priced"])


def test_executable_cost_and_frozen_plan_connect_to_exact_journal_hold(exact_journal):
    result = _reserve(exact_journal)
    assert result["fee_mojos"] == 20
    assert result["dispatch_authorized"] is False
    assert database.get_fee_approval(exact_journal["approval"]["approval_id"])["held_fee_mojos"] == 20
    assert database.get_connection().execute("SELECT COUNT(*) FROM wallet_effect_dispatches").fetchone()[0] == 0


def test_expired_quote_cannot_hold_fee_after_operation_was_prepared(exact_journal):
    exact_journal["now"] = 1060
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        _reserve(exact_journal)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_different_operation_cannot_inherit_valid_unsigned_fee(exact_journal):
    exact_journal["operation_id"] = "e" * 64
    with pytest.raises(ValueError, match="FEE_DISPATCH_PLAN_MISMATCH"):
        _reserve(exact_journal)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_new_competing_hold_is_counted_atomically_at_final_boundary(exact_journal):
    account = exact_journal["approval"]
    database.reserve_approved_fee(
        approval_id=account["approval_id"], scope_sha256=account["scope_sha256"],
        plan_sha256=account["plan_sha256"], operation_id="1" * 64, fee_mojos=25, cancellation=False)
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        _reserve(exact_journal)
    assert database.get_fee_approval(account["approval_id"])["held_fee_mojos"] == 25


def test_fee_hold_retrieval_never_authorizes_operation_replay(exact_journal):
    _reserve(exact_journal)
    with pytest.raises(ValueError, match="FEE_OPERATION_REPLAY"):
        _reserve(exact_journal)
    assert database.get_fee_approval(exact_journal["approval"]["approval_id"])["held_fee_mojos"] == 20


def test_modified_cost_quote_is_rejected_against_executable_bundle(exact_journal):
    exact_journal["priced"]["pricing"]["quote"]["cost"] += 1
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        _reserve(exact_journal)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_reserve_rechecks_execution_settings_after_journal_preparation(exact_journal):
    exact_journal["config"].TRANSACTION_FEE_MODE = "auto"
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _reserve(exact_journal)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_changed_source_inventory_during_estimation_requires_new_pricing_pass(approved, monkeypatch):
    pricing = import_module("coin_prep_fee_pricing")
    original = pricing.quote_fee

    def change_then_quote(*args, **kwargs):
        approved["xch"][0]["amount"] = "199999999999"
        return original(*args, **kwargs)

    monkeypatch.setattr(pricing, "quote_fee", change_then_quote)
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        _price(approved)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_missing_claimed_source_blocks_final_fee_hold(exact_journal):
    exact_journal["cat"] = []
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        _reserve(exact_journal)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_changed_claimed_amount_blocks_cached_unsigned_fee_hold(exact_journal):
    exact_journal["cat"][0]["amount"] = "19999"
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        _reserve(exact_journal)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_input_disappearing_during_executable_validation_blocks_final_hold(exact_journal, monkeypatch):
    import wallet
    original = wallet.inspect_unsigned_transaction_effect

    def validate_then_change(*args, **kwargs):
        result = original(*args, **kwargs)
        exact_journal["cat"] = []
        return result

    monkeypatch.setattr(wallet, "inspect_unsigned_transaction_effect", validate_then_change)
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        _reserve(exact_journal)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_dispatch_claim_read_cannot_create_a_missing_database(tmp_path, monkeypatch):
    path = tmp_path / "does-not-exist.db"
    monkeypatch.setattr(database, "DB_PATH", str(path))
    with pytest.raises((ValueError, sqlite3.Error)):
        database.get_coin_prep_fee_dispatch_claim("1" * 64)
    assert not path.exists()


def test_new_reserve_designation_is_checked_inside_atomic_hold(exact_journal, monkeypatch):
    original = database.reserve_coin_prep_fee_for_dispatch
    coin_id = exact_journal["priced"]["pricing"]["plan"].source_coin_ids[0]

    def designate_then_hold(**kwargs):
        database.set_coin_designation(coin_id, "reserve")
        return original(**kwargs)

    monkeypatch.setattr(database, "reserve_coin_prep_fee_for_dispatch", designate_then_hold)
    with pytest.raises(ValueError, match="FEE_EFFECT_NOT_DISPATCHABLE"):
        _reserve(exact_journal)
    assert utils._counts()["approved_fee_reservations"] == 0
