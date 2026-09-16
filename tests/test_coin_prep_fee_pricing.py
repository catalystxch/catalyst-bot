"""Final fee guidance must match the inspected unsigned effect, not a flat cost."""

from importlib import import_module
import copy
import json
from pathlib import Path
from chia_rs import Coin, CoinSpend, Program
import pytest

import wallet
import wallet_sage
from coin_prep_batch_plan import CoinSnapshot, SelectableCoin, TargetOutput


ADDRESS = "xch1xgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgequ6kqev"
ROOT_ADDRESS = "xch1nh8e0gvy7vnz85g6wvfye6ue54cfkzphy8583gtd0r6evuvt57eqm23khw"
PUZZLE = Program.to(1)
ROOT = Coin(bytes.fromhex("31" * 32), PUZZLE.get_tree_hash(), 3000)
TARGETS = (TargetOutput("xch", "replacement", 0, 1000, 0),)
SNAPSHOT = CoinSnapshot((SelectableCoin("xch", ROOT.name().hex(), 3000),))


def _service():
    try:
        return import_module("coin_prep_fee_pricing")
    except ModuleNotFoundError:
        pytest.fail("runtime cost/fee-consistent batch pricing is missing")


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", wallet_sage)
    state = {"fees": [], "costs": [], "fee": 100, "now": 1000}

    def build(ids, actions):
        assert ids == [ROOT.name().hex()]
        sends = [action for action in actions if action["type"] == "send"]
        fee = sum(int(action["amount"]) for action in actions if action["type"] == "fee")
        assert sum(int(action["amount"]) for action in sends) + fee == ROOT.amount
        conditions = [[51, bytes.fromhex("32" * 32), int(action["amount"])] for action in sends]
        spend = CoinSpend(ROOT, PUZZLE, Program.to(conditions))
        state["fees"].append(fee)
        return {"coin_spends": [spend.to_json_dict()], "summary": {
            "fee": str(fee), "inputs": [{"coin_id": ROOT.name().hex(), "amount": str(ROOT.amount),
            "address": ROOT_ADDRESS, "asset": None, "outputs": [
                {"coin_id": Coin(ROOT.name(), bytes.fromhex("32" * 32), int(action["amount"])).name().hex(),
                 "amount": action["amount"], "address": ADDRESS, "receiving": True, "burning": False}
                for action in sends]}]}}

    def forbidden(*_args, **_kwargs):
        pytest.fail("pricing attempted signing/submission or an unexpected wallet call")

    monkeypatch.setattr(wallet, "build_transaction_rpc", build)
    monkeypatch.setattr(wallet, "submit_built_transaction_rpc", forbidden)
    monkeypatch.setattr(wallet_sage, "_sage_post", forbidden)
    return state


def _price(monkeypatch, state, *, snapshot=SNAPSHOT, reserves=None, target_seconds=300):
    service = _service()
    monkeypatch.setattr(service, "_now", lambda: state["now"])

    def quote(cost, target_seconds):
        state["costs"].append(cost)
        fee = state["fee"](cost, len(state["costs"])) if callable(state["fee"]) else state["fee"]
        result = {"available": True, "reason": "network_fee_estimate", "source": "coinset",
                  "cost": cost, "target_seconds": target_seconds, "fee_mojos": fee,
                  "fee_xch": str(fee), "observed_at": 1000, "expires_at": 1060}
        result.update(state.get("quote_override", {}))
        if state.get("slow_quote"):
            state["now"] = 1060
        return result

    monkeypatch.setattr(service, "quote_fee", quote)
    return service.price_next_prep_batch(snapshot=snapshot, targets=TARGETS,
        reserve_floors={"xch": 0, "cat": 0} if reserves is None else reserves,
        receive_address=ADDRESS, cat_asset_id="36" * 32, target_seconds=target_seconds)


def test_real_unsigned_cost_is_rebuilt_with_the_network_fee_before_use(monkeypatch, transport):
    result = _price(monkeypatch, transport)
    assert result["available"] is True
    assert result["dispatch_authorized"] is False
    assert result["plan"].fee_mojos == 100
    assert [(out.purpose, out.amount_mojos) for out in result["plan"].outputs] == [
        ("change", 1900), ("replacement", 1000)]
    assert result["inspection"]["cost_kind"] == "exact_unsigned"
    assert result["quote"]["cost"] == result["inspection"]["cost"]
    assert result["inspection"]["validated_unsigned"]["_catalyst_executable_effect_bound"] is True
    assert transport["fees"] == [0, 100]
    # Pinned mainnet chia_rs executable cost for this two-output fixture.
    assert transport["costs"] == [5_172_044, 5_172_044]


def test_provisional_zero_fee_change_collision_can_be_repriced_without_a_fee_floor(monkeypatch, transport):
    import sys
    root = Coin(bytes.fromhex("31" * 32), PUZZLE.get_tree_hash(), 2000)
    monkeypatch.setattr(sys.modules[__name__], "ROOT", root)
    snapshot = CoinSnapshot((SelectableCoin("xch", root.name().hex(), 2000),))
    result = _price(monkeypatch, transport, snapshot=snapshot)
    assert result["available"] is True
    assert result["plan"].fee_mojos == 100
    assert transport["fees"] == [0, 1, 100]
    assert result["dispatch_authorized"] is False


def test_valid_zero_network_fee_is_not_replaced_by_an_arbitrary_minimum(monkeypatch, transport):
    transport["fee"] = 0
    result = _price(monkeypatch, transport)
    assert result["available"] is True
    assert result["plan"].fee_mojos == 0
    assert transport["fees"] == [0]


def test_unbuildable_final_zero_fee_cannot_turn_a_provisional_seed_into_spend(monkeypatch, transport):
    import sys
    root = Coin(bytes.fromhex("31" * 32), PUZZLE.get_tree_hash(), 2000)
    monkeypatch.setattr(sys.modules[__name__], "ROOT", root)
    transport["fee"] = 0
    result = _price(monkeypatch, transport,
        snapshot=CoinSnapshot((SelectableCoin("xch", root.name().hex(), 2000),)))
    assert result["available"] is False
    assert result["reason"] == "DUPLICATE_OUTPUT_ID"
    assert "inspection" not in result
    assert transport["fees"] == [0, 1, 0]


def test_fee_induced_change_removal_is_quoted_at_its_new_actual_cost(monkeypatch, transport):
    transport["fee"] = lambda _cost, index: 2000 if index == 1 else 100
    result = _price(monkeypatch, transport)
    assert result["available"] is True
    assert result["plan"].fee_mojos == 100
    assert transport["fees"] == [0, 2000, 100]
    assert transport["costs"][0] != transport["costs"][1]
    assert transport["costs"][0] == transport["costs"][2]


def test_real_cat2_batch_is_repriced_with_separate_xch_fee_input(monkeypatch, transport):
    raw_cat = json.loads((Path(__file__).parent / "fixtures" / "coin_prep_unsigned_cat2.json").read_text())
    cat_id = raw_cat["summary"]["inputs"][0]["coin_id"]

    def build(ids, actions):
        fee = sum(int(action["amount"]) for action in actions if action["type"] == "fee")
        assert set(ids) == ({cat_id, ROOT.name().hex()} if fee else {cat_id})
        assert [action["amount"] for action in actions
                if action["type"] == "send" and action["id"]["type"] == "existing"] == ["2000"]
        raw = copy.deepcopy(raw_cat)
        transport["fees"].append(fee)
        raw["summary"]["fee"] = str(fee)
        if fee:
            change = 3000 - fee
            assert [action["amount"] for action in actions
                    if action["type"] == "send" and action["id"]["type"] == "xch"] == [str(change)]
            raw["coin_spends"].append(CoinSpend(ROOT, PUZZLE,
                Program.to([[51, bytes.fromhex("32" * 32), change]])).to_json_dict())
            raw["summary"]["inputs"].append({"coin_id": ROOT.name().hex(), "amount": "3000",
                "address": ROOT_ADDRESS, "asset": None, "outputs": [{
                    "coin_id": Coin(ROOT.name(), bytes.fromhex("32" * 32), change).name().hex(),
                    "amount": str(change), "address": ADDRESS, "receiving": True, "burning": False}]})
        return raw

    monkeypatch.setattr(wallet, "build_transaction_rpc", build)
    service = _service()
    monkeypatch.setattr(service, "_now", lambda: 1000)
    monkeypatch.setattr(service, "quote_fee", lambda cost, target_seconds: {
        "available": True, "source": "coinset", "cost": cost, "target_seconds": target_seconds,
        "fee_mojos": 100, "observed_at": 1000, "expires_at": 1060})
    result = service.price_next_prep_batch(
        snapshot=CoinSnapshot((SelectableCoin("cat", cat_id, 2000), *SNAPSHOT.coins)),
        targets=(TargetOutput("cat", "replacement", 0, 2000, 0),),
        reserve_floors={"xch": 0, "cat": 0}, receive_address=ADDRESS, cat_asset_id="36" * 32)
    assert result["available"] is True
    assert result["plan"].asset == "cat"
    assert result["plan"].fee_source_id == ROOT.name().hex()
    assert result["plan"].fee_mojos == 100
    assert result["inspection"]["validated_unsigned"]["_catalyst_executable_effect_bound"] is True
    assert result["quote"]["cost"] == result["inspection"]["cost"]
    assert transport["fees"] == [0, 100]
    assert result["dispatch_authorized"] is False


@pytest.mark.parametrize("override", [{"available": False}, {"fee_mojos": True},
    {"fee_mojos": 1.5}, {"fee_mojos": -1}, {"cost": 20_000_000},
    {"target_seconds": 60}, {"source": "manual"}, {"observed_at": 940, "expires_at": 1000},
    {"observed_at": 1001, "expires_at": 1061}])
def test_invalid_unavailable_or_stale_guidance_cannot_supply_a_fee(monkeypatch, transport, override):
    transport["quote_override"] = override
    result = _price(monkeypatch, transport)
    assert result["available"] is False
    assert result["reason"] == "FEE_ESTIMATE_UNAVAILABLE"
    assert "inspection" not in result
    assert transport["fees"] == [0]


def test_quote_expiring_during_transport_is_unavailable(monkeypatch, transport):
    transport["slow_quote"] = True
    assert _price(monkeypatch, transport)["reason"] == "FEE_ESTIMATE_UNAVAILABLE"


def test_oscillating_guidance_is_bounded_without_returning_a_spendable_bundle(monkeypatch, transport):
    transport["fee"] = lambda _cost, index: 100 if index % 2 else 200
    result = _price(monkeypatch, transport)
    assert result["available"] is False
    assert result["reason"] == "FEE_PRICING_NOT_CONVERGED"
    assert "inspection" not in result
    assert transport["fees"] == [0, 100, 200, 100]


def test_fee_that_exhausts_funding_cannot_be_returned_as_an_exact_effect(monkeypatch, transport):
    transport["fee"] = 2001
    result = _price(monkeypatch, transport)
    assert result["available"] is False
    assert result["reason"] == "INSUFFICIENT_SOURCES"
    assert transport["fees"] == [0]


def test_fee_repricing_preserves_the_existing_reserve_floor(monkeypatch, transport):
    transport["fee"] = 2001
    result = _price(monkeypatch, transport, reserves={"xch": 1000, "cat": 0})
    assert result["available"] is False
    assert result["reason"] == "RESERVE_FLOOR"


def test_complete_reusable_targets_need_no_unsigned_or_fee_request(monkeypatch, transport):
    snapshot = CoinSnapshot((SelectableCoin("xch", "37" * 32, 1000, "replacement"),))
    result = _price(monkeypatch, transport, snapshot=snapshot)
    assert result["available"] is True
    assert result["transaction_required"] is False
    assert result["plan"].fee_mojos == 0
    assert transport["fees"] == transport["costs"] == []


@pytest.mark.parametrize("reserves,target", [({"xch": True, "cat": 0}, 300),
    ({"xch": -1, "cat": 0}, 300), ({"xch": 0.5, "cat": 0}, 300),
    ({"xch": 0}, 300), ({"xch": 0, "cat": 0}, True)])
def test_invalid_constraints_are_rejected_before_wallet_reads(monkeypatch, transport, reserves, target):
    with pytest.raises(ValueError):
        _price(monkeypatch, transport, reserves=reserves, target_seconds=target)
    assert transport["fees"] == transport["costs"] == []
