"""Approved prep readback consumes frozen outputs, never a later market price."""

import json
import time
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

import pytest

import api_server
import database
import fee_approval_test_utils as utils
from fee_staged_preview_utils import prepare_unsigned_wallet


@pytest.fixture
def approved(tmp_path, monkeypatch):
    wallet_reads = utils.live_reads(tmp_path, monkeypatch)
    state = next(wallet_reads)
    utils.economic_reads(state, monkeypatch)
    runtime = import_module("coin_prep_fee_runtime")
    service = import_module("coin_prep_fee_approval")
    pricing = import_module("coin_prep_fee_pricing")
    monkeypatch.setattr(runtime, "cfg", state["config"])
    state["now"] = 1000
    monkeypatch.setattr(service, "_now", lambda: state["now"])
    monkeypatch.setattr(pricing, "_now", lambda: state["now"])
    monkeypatch.setattr(database, "time", SimpleNamespace(
        time=lambda: state["now"], time_ns=time.time_ns, monotonic=time.monotonic, sleep=time.sleep))

    def quote(cost, target_seconds):
        return {"available": True, "fee_mojos": 20, "source": "coinset", "cost": cost,
                "target_seconds": target_seconds, "observed_at": 1000, "expires_at": 1060}

    monkeypatch.setattr(service, "quote_fee", quote)
    monkeypatch.setattr(pricing, "quote_fee", quote)
    prepare_unsigned_wallet(state, monkeypatch)
    state["preview"] = service.preview_coin_prep_fees({})
    state["approval"] = service.approve_coin_prep_fees(
        preview_id=state["preview"]["preview_id"], maximum_fee_mojos=80, cancellation_reserve_mojos=40)
    state["reads"].clear()
    yield state
    try:
        next(wallet_reads)
    except StopIteration:
        pass


def _read(state, approval_id=None):
    reader = getattr(import_module("coin_prep_fee_runtime"), "read_approved_prep_fee_snapshot", None)
    assert callable(reader), "approved frozen execution collector is missing"
    return reader(state["approval"]["approval_id"] if approval_id is None else approval_id)


def test_public_preview_persists_server_execution_binding_without_exposing_it(approved):
    stored = database.get_coin_prep_fee_preview(approved["preview"]["preview_id"])
    binding = json.loads(stored["quote_json"]).get("execution_context")
    assert type(binding) is dict, "public runtime preview did not freeze execution settings"
    assert binding["version"] == 1
    assert binding["receive_address"] == utils.ADDRESS
    assert binding["worker_args"]["cat_target"] == 1
    assert binding["worker_args"]["prep_headroom_pct"] == "0"
    assert "execution_context" not in approved["preview"]


def test_price_change_after_consent_cannot_resize_approved_outputs(approved, monkeypatch):
    def forbidden():
        pytest.fail("execution attempted to regenerate economics from market price")
    monkeypatch.setattr(api_server, "_get_live_mid_price_str", forbidden)
    approved["live_price"] = "0.1"
    builds = len(approved["builds"])
    result = _read(approved)
    assert [(t.asset, t.amount_mojos, t.ordinal) for t in result["recipe"]["targets"]] == [
        ("xch", 110_000_000_000, 0), ("xch", 1_000_000_000, 1),
        ("xch", 1_000_000_000, 2), ("cat", 11_000, 0)]
    assert result["recipe"]["economic_plan"]["headroom_pct"] == "10"
    assert result["recipe"]["worker_args"]["prep_headroom_pct"] == "0"
    assert result["dispatch_authorized"] is False
    assert len(approved["builds"]) == builds
    assert utils._counts() == {"fee_approvals": 1, "coin_prep_fee_consents": 1,
                             "approved_fee_reservations": 0, "coin_prep_operations": 0, "wallet_effect_claims": 0}


@pytest.mark.parametrize("key,value", [("XCH_RESERVE", Decimal("1")),
                                         ("CAT_RESERVE", Decimal("1")),
                                         ("SPREAD_BPS", Decimal("20000")),
                                         ("BUY_INNER_SIZE_XCH", Decimal("2")),
                                         ("COIN_PREP_HEADROOM_PCT", Decimal("20"))])
def test_changed_settings_require_new_consent_instead_of_resizing(approved, key, value):
    setattr(approved["config"], key, value)
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _read(approved)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_expired_guidance_does_not_erase_frozen_consent_or_existing_holds(approved):
    approval = approved["approval"]
    database.reserve_approved_fee(
        approval_id=approval["approval_id"], scope_sha256=approval["scope_sha256"],
        plan_sha256=approval["plan_sha256"], operation_id="1" * 64, fee_mojos=10, cancellation=False)
    approved["now"] = 2000
    database.close_connection()
    database.init_database()
    result = _read(approved)
    assert result["approval"]["held_fee_mojos"] == 10
    assert result["approval"]["remaining_fee_mojos"] == 70
    assert result["approval"]["remaining_preparation_fee_mojos"] == 30
    assert result["recipe"]["targets"][-1].amount_mojos == 11_000
    assert result["dispatch_authorized"] is False


def test_generic_ledger_approval_cannot_supply_frozen_execution_authority(approved):
    generic = database.create_fee_approval(
        scope_sha256=approved["approval"]["scope_sha256"], plan_sha256=approved["approval"]["plan_sha256"],
        total_fee_mojos=80, cancellation_reserve_mojos=40)
    with pytest.raises(ValueError, match="FEE_APPROVAL_REQUIRED"):
        _read(approved, generic["approval_id"])
    assert approved["reads"] == []


@pytest.mark.parametrize("key,value", [
    ("TRANSACTION_FEE_MODE", "auto"),
    ("TRANSACTION_FEE_XCH", Decimal("0.00002")),
    ("WALLET_EXPECTED_NAME", "TEST 7"),
])
def test_confirmation_rejects_changed_execution_settings_even_when_outputs_match(approved, key, value):
    # These changes leave the targets unchanged, but cannot inherit consent
    # from a preview of different execution settings.
    setattr(approved["config"], key, value)
    service = import_module("coin_prep_fee_approval")
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        service.approve_coin_prep_fees(
            preview_id=approved["preview"]["preview_id"], maximum_fee_mojos=80,
            cancellation_reserve_mojos=40)
    assert utils._counts()["coin_prep_fee_consents"] == 1
    assert utils._counts()["approved_fee_reservations"] == 0


def test_typed_execution_configuration_canonicalizes_zero_without_expanding_exponent(approved):
    execution = import_module("coin_prep_fee_execution")
    runtime = import_module("coin_prep_fee_runtime")
    approved["config"].TRANSACTION_FEE_XCH = Decimal("0e-129")
    encoded = execution.encode_execution_configuration(runtime._configuration())
    assert encoded["TRANSACTION_FEE_XCH"] == {"kind": "decimal", "value": "0"}


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"),
                                   Decimal("1e100000000"), Decimal("1e-100000000"), 0.01])
def test_invalid_configuration_amounts_are_rejected_without_fixed_point_expansion(approved, value):
    execution = import_module("coin_prep_fee_execution")
    runtime = import_module("coin_prep_fee_runtime")
    approved["config"].TRANSACTION_FEE_XCH = value
    with pytest.raises(ValueError, match="FEE_EXECUTION_CONTEXT_INVALID"):
        execution.encode_execution_configuration(runtime._configuration())


def test_changed_wallet_cannot_read_old_approved_plan(approved):
    approved["identity"]["fingerprint"] = 12345
    with pytest.raises(ValueError, match="FEE_WALLET_IDENTITY_UNAVAILABLE"):
        _read(approved)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_changed_inventory_is_not_resizing_or_intermediate_completion_proof(approved):
    approved["xch"] = []
    result = _read(approved)
    assert [(c.asset, c.amount_mojos) for c in result["snapshot"].coins] == [("cat", 20_000)]
    assert result["recipe"]["targets"][0].amount_mojos == 110_000_000_000
    assert result["recipe"]["targets"][-1].amount_mojos == 11_000
    assert result["dispatch_authorized"] is False
    assert utils._counts()["coin_prep_operations"] == 0


@pytest.mark.parametrize("action", ["confirm", "read"])
def test_changed_receive_address_cannot_inherit_existing_consent(approved, monkeypatch, action):
    from chia.util.bech32m import encode_puzzle_hash
    from chia_rs.sized_bytes import bytes32
    import wallet

    new_address = encode_puzzle_hash(bytes32(b"a" * 32), "xch")
    monkeypatch.setattr(wallet, "get_next_address", lambda *_args, **_kwargs: {
        "success": True, "address": new_address})
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        if action == "read":
            _read(approved)
        else:
            import_module("coin_prep_fee_approval").approve_coin_prep_fees(
                preview_id=approved["preview"]["preview_id"], maximum_fee_mojos=80,
                cancellation_reserve_mojos=40)
    assert utils._counts()["approved_fee_reservations"] == 0


def test_frozen_cli_cannot_resize_canonical_targets(approved):
    stored = database.get_coin_prep_fee_preview(approved["preview"]["preview_id"])
    binding = json.loads(stored["quote_json"])["execution_context"]
    binding["worker_args"]["xch_target"] = 2
    with pytest.raises(ValueError, match="FEE_EXECUTION_CONTEXT_INVALID"):
        import_module("coin_prep_fee_execution").validate_execution_context(
            binding, json.loads(stored["scope_json"]), json.loads(stored["plan_json"]))
    assert utils._counts()["approved_fee_reservations"] == 0
