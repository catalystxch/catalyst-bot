"""Read-only previews inspect real unsigned effects and CLVM cost, not heuristics."""

import copy
from importlib import import_module
import json
from pathlib import Path

from chia_rs import Coin
from chia_rs import Program
import pytest

import database
import wallet
import wallet_sage
from coin_prep_batch_plan import BatchPlan, PlannedOutput


ADDRESS = "xch1xgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgequ6kqev"
PUZZLE = "a66b42db08e2951decefb2bfb1d0ed6254ac0293dbd2c06161106a194af24a95"
SOURCE = Coin(bytes.fromhex("31" * 32), bytes.fromhex(PUZZLE), 2000).name().hex()
OUTPUT = Coin(bytes.fromhex(SOURCE), bytes.fromhex("32" * 32), 1000).name().hex()


def _service():
    try:
        return import_module("coin_prep_unsigned")
    except ModuleNotFoundError:
        pytest.fail("shared read-only unsigned batch inspection is missing")


def _plan(fee=1000):
    return BatchPlan("xch", (SOURCE,), None,
                     (PlannedOutput("xch", "replacement", 1000, 0),), (), (), fee)


def _response():
    return {
        "summary": {"fee": "1000", "inputs": [
            {"coin_id": SOURCE, "amount": "2000", "address": ADDRESS, "asset": None,
             "outputs": [{"coin_id": OUTPUT, "amount": "1000", "address": ADDRESS,
                          "receiving": True, "burning": False}]},
        ]},
        "coin_spends": [{
            "coin": {"parent_coin_info": "31" * 32, "puzzle_hash": PUZZLE, "amount": 2000},
            "puzzle_reveal": "ff01ffff33ffa032323232323232323232323232323232323232323232323232"
                             "32323232323232ff8203e88080",
            "solution": "80",
        }],
    }


@pytest.fixture
def inspection(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "unsigned-preview.db"))
    database.init_database()
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", wallet_sage)
    calls = []
    value = _response()

    def build(ids, actions):
        # The external wallet response is only valid for this exact request.
        assert ids == [SOURCE]
        assert actions == [
            {"type": "send", "id": {"type": "xch"}, "address": ADDRESS,
             "amount": "1000", "memos": []},
            {"type": "fee", "amount": "1000"},
        ]
        calls.append("unsigned_build")
        return copy.deepcopy(value)

    def forbidden(*args, **kwargs):
        pytest.fail("read-only unsigned preview attempted a wallet effect")

    monkeypatch.setattr(wallet, "build_transaction_rpc", build)
    monkeypatch.setattr(wallet, "submit_built_transaction_rpc", forbidden)
    monkeypatch.setattr(wallet_sage, "_sage_post", forbidden)
    yield value, calls
    database.close_connection()


def test_exact_cost_from_real_unsigned_bundle_without_claim_or_signing(inspection):
    result = _service().inspect_batch_unsigned(_plan(), ADDRESS, None)
    assert result["available"] is True
    assert result["cost"] == 2_892_020
    assert result["cost_kind"] == "exact_unsigned"
    assert result["validated_unsigned"]["_catalyst_validated_unsigned"] is True
    assert inspection[1] == ["unsigned_build"]
    conn = database.get_connection()
    for table in ("coin_prep_operations", "wallet_effect_claims", "approved_fee_reservations"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r["summary"].update(fee="1001"), "FEE_MISMATCH"),
    (lambda r: r["summary"]["inputs"][0].update(coin_id="a" * 64), "SOURCE_COHORT_MISMATCH"),
    (lambda r: r["summary"]["inputs"][0]["outputs"][0].update(amount="999"), "OUTPUT_MISMATCH"),
    (lambda r: r.pop("summary"), "UNSIGNED_EFFECT_NOT_INSPECTABLE"),
])
def test_mismatched_effect_cannot_be_labeled_exact(inspection, mutation, reason):
    mutation(inspection[0])
    result = _service().inspect_batch_unsigned(_plan(), ADDRESS, None)
    assert result["available"] is False
    assert result["reason"] == reason
    assert result["cost"] is None
    assert "validated_unsigned" not in result


def test_unexecutable_clvm_is_unavailable_not_a_generic_estimated_cost(inspection):
    inspection[0]["coin_spends"][0]["solution"] = "not-hex"
    result = _service().inspect_batch_unsigned(_plan(), ADDRESS, None)
    assert result["available"] is False
    assert result["reason"] == "FEE_UNSIGNED_COST_UNAVAILABLE"
    assert result["cost"] is None


def test_executable_extra_removal_hidden_by_matching_summary_is_rejected(inspection):
    extra = copy.deepcopy(inspection[0]["coin_spends"][0])
    extra["coin"]["parent_coin_info"] = "33" * 32
    inspection[0]["coin_spends"].append(extra)
    result = _service().inspect_batch_unsigned(_plan(), ADDRESS, None)
    assert result["available"] is False
    assert result["reason"] == "UNSIGNED_EXECUTABLE_EFFECT_MISMATCH"
    assert result["cost"] is None


@pytest.mark.parametrize("mutation", [
    lambda r: r["summary"]["inputs"][0]["outputs"][0].update(coin_id="34" * 32),
    lambda r: r["summary"]["inputs"][0].update(amount="1999"),
])
def test_executable_and_summary_coin_identity_and_amount_must_agree(inspection, mutation):
    mutation(inspection[0])
    result = _service().inspect_batch_unsigned(_plan(), ADDRESS, None)
    assert result["available"] is False
    assert result["reason"] == "UNSIGNED_EXECUTABLE_EFFECT_MISMATCH"
    assert result["cost"] is None


def test_summary_cannot_disguise_an_xch_spend_as_cat(inspection, monkeypatch):
    raw = inspection[0]
    spend = raw["coin_spends"][0]
    spend["puzzle_reveal"] = spend["puzzle_reveal"].replace("8203e8", "8207d0")
    puzzle_hash = Program.fromhex(spend["puzzle_reveal"]).get_tree_hash()
    spend["coin"]["puzzle_hash"] = puzzle_hash.hex()
    source = Coin(bytes.fromhex("31" * 32), puzzle_hash, 2000).name().hex()
    output = Coin(bytes.fromhex(source), bytes.fromhex("32" * 32), 2000).name().hex()
    raw["summary"]["fee"] = "0"
    raw["summary"]["inputs"][0].update(coin_id=source, asset={"asset_id": "36" * 32})
    raw["summary"]["inputs"][0]["outputs"][0].update(coin_id=output, amount="2000")
    monkeypatch.setattr(wallet, "build_transaction_rpc", lambda *args: copy.deepcopy(raw))
    plan = BatchPlan("cat", (source,), None,
                     (PlannedOutput("cat", "replacement", 2000, 0),), (), (), 0)
    result = _service().inspect_batch_unsigned(plan, ADDRESS, "36" * 32)
    assert result["available"] is False
    assert result["reason"] == "UNSIGNED_EXECUTABLE_EFFECT_MISMATCH"


def test_real_cat2_executable_effect_is_inspectable_without_chia_python_runtime(inspection, monkeypatch):
    # Synthetic 2,000-mojo CAT2 ring generated with the official cat_utils;
    # pinned serialized data makes the test run using only bundled chia_rs.
    raw = json.loads((Path(__file__).parent / "fixtures" / "coin_prep_unsigned_cat2.json").read_text())
    source = raw["summary"]["inputs"][0]["coin_id"]
    monkeypatch.setattr(wallet, "build_transaction_rpc", lambda *args: copy.deepcopy(raw))
    plan = BatchPlan("cat", (source,), None,
                     (PlannedOutput("cat", "replacement", 2000, 0),), (), (), 0)
    result = _service().inspect_batch_unsigned(plan, ADDRESS, "36" * 32)
    assert result["available"] is True
    assert result["cost_kind"] == "exact_unsigned"
    assert result["cost"] == 27_359_224
    assert result["validated_unsigned"]["_catalyst_executable_effect_bound"] is True


def test_matching_summary_cannot_redirect_an_output_to_a_different_address(inspection, monkeypatch):
    # The requested/summary address is valid, but does not match CREATE_COIN.
    wrong = "xch1zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zyg3zygs3fazuv"
    from sage_offer_wire import decode_wallet_puzzle_hash
    assert decode_wallet_puzzle_hash(wrong) == bytes.fromhex("11" * 32)
    raw = inspection[0]
    raw["summary"]["inputs"][0]["outputs"][0]["address"] = wrong
    monkeypatch.setattr(wallet, "build_transaction_rpc", lambda *args: copy.deepcopy(raw))
    result = _service().inspect_batch_unsigned(_plan(), wrong, None)
    assert result["available"] is False
    assert result["reason"] == "UNSIGNED_EXECUTABLE_EFFECT_MISMATCH"


def test_summary_fee_must_equal_executable_bundle_fee(inspection, monkeypatch):
    inspection[0]["summary"]["fee"] = "1001"
    monkeypatch.setattr(wallet, "build_transaction_rpc", lambda *args: copy.deepcopy(inspection[0]))
    result = _service().inspect_batch_unsigned(_plan(fee=1001), ADDRESS, None)
    assert result["available"] is False
    assert result["reason"] == "UNSIGNED_EXECUTABLE_EFFECT_MISMATCH"


def test_complete_ephemeral_spend_chain_is_bound_but_not_an_extra_root(inspection, monkeypatch):
    from chia_rs import CoinSpend

    puzzle = Program.to(1)
    root = Coin(bytes.fromhex("31" * 32), puzzle.get_tree_hash(), 2000)
    ephemeral = Coin(root.name(), puzzle.get_tree_hash(), 1000)
    final = Coin(ephemeral.name(), bytes.fromhex("32" * 32), 500)
    root_spend = CoinSpend(root, puzzle, Program.to([[51, puzzle.get_tree_hash(), 1000]]))
    child_spend = CoinSpend(ephemeral, puzzle, Program.to([[51, bytes.fromhex("32" * 32), 500]]))
    child_address = "xch1nh8e0gvy7vnz85g6wvfye6ue54cfkzphy8583gtd0r6evuvt57eqm23khw"
    raw = {"coin_spends": [root_spend.to_json_dict(), child_spend.to_json_dict()], "summary": {
        "fee": "1500", "inputs": [
            {"coin_id": root.name().hex(), "amount": "2000", "address": child_address, "asset": None,
             "outputs": [{"coin_id": ephemeral.name().hex(), "amount": "1000", "address": child_address}]},
            {"coin_id": ephemeral.name().hex(), "amount": "1000", "address": child_address, "asset": None,
             "outputs": [{"coin_id": final.name().hex(), "amount": "500", "address": ADDRESS,
                          "receiving": True, "burning": False}]},
        ]}}
    monkeypatch.setattr(wallet, "build_transaction_rpc", lambda *args: copy.deepcopy(raw))
    plan = BatchPlan("xch", (root.name().hex(),), None,
                     (PlannedOutput("xch", "replacement", 500, 0),), (), (), 1500)
    result = _service().inspect_batch_unsigned(plan, ADDRESS, None)
    assert result["available"] is True
    raw["summary"]["inputs"].pop()
    result = _service().inspect_batch_unsigned(plan, ADDRESS, None)
    assert result["available"] is False


@pytest.mark.parametrize("address", [
    None, "", "xch1own", ADDRESS.upper(), ADDRESS[:-1] + "q", "offer" + ADDRESS[3:],
])
def test_invalid_wallet_destination_is_not_inspectable(address):
    from sage_offer_wire import decode_wallet_puzzle_hash

    with pytest.raises(ValueError):
        decode_wallet_puzzle_hash(address)


@pytest.mark.parametrize("fee", [True, -1, 1.0])
def test_invalid_plan_rejected_before_wallet_construction(inspection, fee):
    with pytest.raises((ValueError, TypeError)):
        _service().inspect_batch_unsigned(_plan(fee), ADDRESS, None)
    assert inspection[1] == []


def test_cat_and_fee_change_roles_and_actions_are_shared_with_execution():
    plan = BatchPlan("cat", ("a" * 64,), "b" * 64, (
        PlannedOutput("cat", "replacement", 40, 0),
        PlannedOutput("cat", "change", 60, -1),
        PlannedOutput("xch", "fee_change", 20, -1),
    ), (), (), 10)
    target = _service().batch_target_contract(plan, ADDRESS, "c" * 64)
    assert [(o["asset"], o["purpose"], o["amount_mojos"]) for o in target["outputs"]] == [
        ("cat", "replacement", 40), ("cat", "top_up", 60), ("xch", "fee_reserve", 20),
    ]
    assert target["external_fee"] == {"fee_mojos": 10, "coin_ids": ["b" * 64]}
    actions = _service().batch_actions(target)
    assert actions[0]["id"] == {"type": "existing", "asset_id": "c" * 64}
    assert actions[2]["id"] == {"type": "xch"}
    assert actions[-1] == {"type": "fee", "amount": "10"}
