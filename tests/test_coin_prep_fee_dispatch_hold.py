"""A final prep hold requires consent, fresh pricing and an undispatched journal."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import time
from types import SimpleNamespace

import pytest

import coin_prep_fee_approval as service
import database
import mutation_gate
import replacement_capacity


@pytest.fixture
def prepared(tmp_path, monkeypatch, request):
    def clear_authorities():
        with database._wallet_effect_process_authorities_lock:
            states = list(database._wallet_effect_process_authorities.values())
            database._wallet_effect_process_authorities.clear()
        for state in states:
            mutation_gate.exit_wallet_mutation(state.permit)

    clear_authorities()
    mutation_gate.shutdown_runtime()
    mutation_gate.clear_worker_authority_environment()
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "dispatch-hold.db"))
    database.init_database()
    when = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(mutation_gate, "_utc_now", lambda: when)
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: "2026-08-21T12:00:00.000000Z")
    state = {"now": 1000}
    monkeypatch.setattr(database, "time", SimpleNamespace(
        time=lambda: state["now"], time_ns=time.time_ns, monotonic=time.monotonic, sleep=time.sleep))
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage", name="Fee test", fingerprint=736588221,
        network_id="mainnet", kind="bls", has_secrets=True,
        bound_at_utc=(when - timedelta(seconds=1)).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        maximum_age_seconds=15,
    )
    runtime = mutation_gate.initialize(
        run_id="prep-fee-hold", owner_pid=111, owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(binding.fingerprint),
        network="mainnet", lease_seconds=30, start_heartbeat=False,
        wallet_identity_binding=binding, wallet_adapter_authority=object(),
    )
    assert runtime.last_acquire_result["acquired"] is True
    scope = service.resolve_server_fee_scope(identity={
        "network": "mainnet", "wallet_type": "sage", "wallet_fingerprint": 736588221,
        "wallet_id": 2, "xch_wallet_id": 1, "asset_id": "a" * 64, "ticker": "MZ_XCH",
    })
    plan = {
        "target_seconds": 300, "coin_multiplier": "1", "headroom_pct": "0",
        "liquidity_mode": "two_sided", "reserve_floors_mojos": {"xch": 0, "cat": 0},
        "campaign_revision": None, "cancellation_policy": "protected_no_prep",
        "outputs": [{"asset": "cat", "purpose": "replacement", "tier_rank": 0,
                     "amount_mojos": 90, "ordinal": 0}],
    }
    contract = service.canonical_fee_contract(scope, plan)
    preview = database.store_coin_prep_fee_preview(
        **{key: contract[key] for key in ("scope_sha256", "plan_sha256", "scope_json", "plan_json")},
        request_options_json="{}", quote_json=json.dumps({
            "available": True, "estimated_preparation_fee_mojos": 10,
            "estimated_cancellation_fee_mojos": 10, "fee_funding_mojos": 100}),
        observed_at=1000, expires_at=1060,
    )
    approval = database.approve_coin_prep_fee_preview(
        preview_id=preview["preview_id"], scope_sha256=contract["scope_sha256"],
        plan_sha256=contract["plan_sha256"], maximum_fee_mojos=100,
        cancellation_reserve_mojos=20,
    )
    target = {
        "contract_version": 2, "wallet_type": "cat", "cat_asset_id": "a" * 64,
        "fee_mojos": 10, "external_fee": {"fee_mojos": 10, "coin_ids": ["2" * 64]},
        "outputs": [
            {"output_index": 0, "asset": "cat", "address": "xch1batchowner",
             "amount_mojos": 90, "purpose": "replacement", "ordinal": 0},
            {"output_index": 1, "asset": "xch", "address": "xch1batchowner",
             "amount_mojos": 20, "purpose": "fee_reserve", "ordinal": -1},
        ],
    }
    operation = replacement_capacity.canonical_coin_prep_contract(
        operation_kind="split", purpose="replacement", source_coin_ids=["1" * 64], target_contract=target)
    database.upsert_coin("1" * 64, "cat", 90, purpose="replacement")
    database.upsert_coin("2" * 64, "xch", 30, purpose="fee_reserve")
    fee_claim_ids = getattr(request, "param", {}).get("fee_claim_ids", ["2" * 64])
    for coin_id in fee_claim_ids:
        database.upsert_coin(coin_id, "xch", 30, purpose="fee_reserve")
    claim = database.claim_wallet_effect(
        operation_id=operation["operation_id"], source_coin_ids=["1" * 64], fee_coin_ids=fee_claim_ids)
    database.prepare_coin_prep_operation(
        operation_kind="split", purpose="replacement", source_coin_ids=["1" * 64],
        target_contract=operation["target_contract"],
        wallet_identity_json=mutation_gate.wallet_identity_binding_payload(binding), evidence_json={},
        effect_claim_token=claim["claim_token"], effect_claim_generation=claim["generation"],
    )
    constructed = [{key: value for key, value in item.items() if key != "output_index"}
                   | {"coin_id": str(index + 3) * 64} for index, item in enumerate(target["outputs"])]
    database.bind_coin_prep_constructed_outputs(
        operation["operation_id"], plan_hash=operation["target_contract"]["plan_hash"],
        constructed_outputs=constructed)
    state.update(approval=approval, contract=contract, operation=operation, claim=claim)
    yield state
    clear_authorities()
    mutation_gate.shutdown_runtime()
    mutation_gate.clear_worker_authority_environment()
    database.close_connection()


def _hold(state, **changes):
    reserve = getattr(database, "reserve_coin_prep_fee_for_dispatch", None)
    assert callable(reserve), "consent/journal-bound atomic final fee hold is missing"
    args = {
        "approval_id": state["approval"]["approval_id"],
        "scope_sha256": state["contract"]["scope_sha256"],
        "plan_sha256": state["contract"]["plan_sha256"],
        "operation_id": state["operation"]["operation_id"],
        "final_quote": {"available": True, "cost": 20_000_000, "target_seconds": 300,
                        "fee_mojos": 10, "source": "coinset", "observed_at": 1000, "expires_at": 1060},
    }
    args.update(changes)
    return reserve(**args)


def _held(state):
    return database.get_fee_approval(state["approval"]["approval_id"])["held_fee_mojos"]


def test_exact_hold_counts_fee_without_granting_external_dispatch(prepared):
    result = _hold(prepared)
    assert result["fee_mojos"] == 10
    assert result["dispatch_authorized"] is False
    assert _held(prepared) == 10
    assert database.get_connection().execute("SELECT COUNT(*) FROM wallet_effect_dispatches").fetchone()[0] == 0


def test_generic_ledger_approval_cannot_replace_deliberate_preview_consent(prepared):
    approval = database.create_fee_approval(
        scope_sha256=prepared["contract"]["scope_sha256"], plan_sha256=prepared["contract"]["plan_sha256"],
        total_fee_mojos=100, cancellation_reserve_mojos=20)
    with pytest.raises(ValueError, match="FEE_APPROVAL_REQUIRED"):
        _hold(prepared, approval_id=approval["approval_id"])
    assert _held(prepared) == 0


@pytest.mark.parametrize("change,reason", [
    ({"available": False}, "FEE_ESTIMATE_UNAVAILABLE"),
    ({"observed_at": 940, "expires_at": 1000}, "FEE_QUOTE_STALE"),
    ({"observed_at": 1001, "expires_at": 1061}, "FEE_QUOTE_STALE"),
    ({"expires_at": 9999}, "FEE_QUOTE_INVALID"),
    ({"cost": True}, "FEE_QUOTE_INVALID"),
    ({"fee_mojos": True}, "FEE_QUOTE_INVALID"),
    ({"source": "manual"}, "FEE_QUOTE_INVALID"),
    ({"target_seconds": 60}, "FEE_APPROVAL_STALE"),
    ({"fee_mojos": 11}, "FEE_EFFECT_CONTRACT_MISMATCH"),
])
def test_invalid_stale_or_nonmatching_final_price_creates_no_hold(prepared, change, reason):
    quote = {"available": True, "cost": 20_000_000, "target_seconds": 300,
             "fee_mojos": 10, "source": "coinset", "observed_at": 1000, "expires_at": 1060}
    with pytest.raises(ValueError, match=reason):
        _hold(prepared, final_quote=quote | change)
    assert _held(prepared) == 0


def test_exceeded_preparation_allowance_cannot_borrow_cancellation_protection(prepared):
    database.reserve_approved_fee(
        approval_id=prepared["approval"]["approval_id"],
        scope_sha256=prepared["contract"]["scope_sha256"], plan_sha256=prepared["contract"]["plan_sha256"],
        operation_id="f" * 64, fee_mojos=71, cancellation=False)
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        _hold(prepared)
    assert _held(prepared) == 71


def test_previously_held_operation_cannot_receive_another_dispatch_permit(prepared):
    _hold(prepared)
    with pytest.raises(ValueError, match="FEE_OPERATION_REPLAY"):
        _hold(prepared)
    assert _held(prepared) == 10


def test_already_dispatched_operation_cannot_acquire_a_late_fee_hold(prepared):
    claim = prepared["claim"]
    dispatch = database.begin_wallet_effect_dispatch(
        claim["claim_token"], claim["generation"], operation_id=prepared["operation"]["operation_id"],
        source_coin_ids=["1" * 64], fee_coin_ids=["2" * 64])
    assert dispatch is not None
    with pytest.raises(ValueError, match="FEE_EFFECT_NOT_DISPATCHABLE"):
        _hold(prepared)
    assert _held(prepared) == 0


def test_competing_workers_only_create_one_exact_hold(prepared):
    def attempt():
        try:
            _hold(prepared)
            return "held"
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["FEE_OPERATION_REPLAY", "held"]
    assert _held(prepared) == 10


def test_quote_expiring_while_waiting_for_writer_lock_creates_no_hold(prepared, monkeypatch):
    original = database._stability_connection

    class ContendedConnection:
        def __init__(self):
            self.connection = original()

        def execute(self, sql, *args):
            result = self.connection.execute(sql, *args)
            if sql == "BEGIN IMMEDIATE":
                prepared["now"] = 1060
            return result

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(database, "_stability_connection", ContendedConnection)
    with pytest.raises(ValueError, match="FEE_QUOTE_STALE"):
        _hold(prepared)
    assert _held(prepared) == 0


def test_superseded_consent_cannot_start_a_new_operation(prepared):
    database.create_fee_approval(
        scope_sha256=prepared["contract"]["scope_sha256"], plan_sha256=prepared["contract"]["plan_sha256"],
        total_fee_mojos=110, cancellation_reserve_mojos=20)
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _hold(prepared)
    assert _held(prepared) == 0


def test_unknown_prepared_operation_creates_no_hold(prepared):
    with pytest.raises(ValueError, match="FEE_EFFECT_NOT_DISPATCHABLE"):
        _hold(prepared, operation_id="f" * 64)
    assert _held(prepared) == 0


@pytest.mark.parametrize("field,value", [("wallet_fingerprint", 3702373391),
                                         ("network", "testnet11"), ("asset_id", "b" * 64)])
def test_consent_for_another_identity_cannot_fund_the_prepared_effect(prepared, field, value):
    scope = {**prepared["contract"]["scope"], field: value}
    contract = service.canonical_fee_contract(scope, prepared["contract"]["plan"])
    original = database.get_coin_prep_fee_preview(prepared["approval"]["preview_id"])
    preview = database.store_coin_prep_fee_preview(
        **{key: contract[key] for key in ("scope_sha256", "plan_sha256", "scope_json", "plan_json")},
        **{key: original[key] for key in ("request_options_json", "quote_json", "observed_at", "expires_at")})
    approval = database.approve_coin_prep_fee_preview(
        preview_id=preview["preview_id"], scope_sha256=contract["scope_sha256"],
        plan_sha256=contract["plan_sha256"], maximum_fee_mojos=100, cancellation_reserve_mojos=20)
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _hold(prepared, approval_id=approval["approval_id"],
              scope_sha256=contract["scope_sha256"], plan_sha256=contract["plan_sha256"])
    assert _held(prepared) == 0
    assert database.get_fee_approval(approval["approval_id"])["held_fee_mojos"] == 0


@pytest.mark.parametrize("prepared", [{"fee_claim_ids": ["9" * 64]}], indirect=True)
def test_exact_external_fee_cohort_must_match_the_effect_claim(prepared):
    with pytest.raises(ValueError, match="FEE_EFFECT_CONTRACT_MISMATCH"):
        _hold(prepared)
    assert _held(prepared) == 0
