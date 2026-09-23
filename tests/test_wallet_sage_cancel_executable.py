"""Cancellation fee approval must bind executable effects, not just summaries."""

import copy
import hashlib
import json
from importlib import import_module
from pathlib import Path

import pytest
from chia_rs import Coin, CoinSpend, Program
from chia.util.bech32m import encode_puzzle_hash
from chia_rs.sized_bytes import bytes32


PUZZLE = Program.to(1)
DESTINATION = bytes32(b"d" * 32)
ROOT = Coin(b"r" * 32, PUZZLE.get_tree_hash(), 1000)
FEE_ROOT = Coin(b"f" * 32, PUZZLE.get_tree_hash(), 500)
TRADE = "a" * 64


def native_bundle(root, fee):
    amount = int(root.amount) - fee
    output = Coin(root.name(), DESTINATION, amount)
    return {
        "summary": {"fee": str(fee), "inputs": [{
            "coin_id": root.name().hex(), "amount": str(root.amount),
            "address": encode_puzzle_hash(root.puzzle_hash, "xch"), "asset": None,
            "outputs": [{"coin_id": output.name().hex(), "amount": str(amount),
                         "address": encode_puzzle_hash(DESTINATION, "xch"),
                         "receiving": True, "burning": False}],
        }]},
        "coin_spends": [CoinSpend(root, PUZZLE,
            Program.to([[51, DESTINATION, amount]])).to_json_dict()],
    }


@pytest.fixture
def adapter(monkeypatch):
    sage = import_module("wallet_sage")
    monkeypatch.setattr(sage, "_require_signing_capability", lambda: True)
    return sage


def build(adapter, monkeypatch, fee, cancel, fee_bundle=None):
    def post(endpoint, payload, **_kwargs):
        assert payload["auto_submit"] is False
        if endpoint == "cancel_offers":
            assert payload["fee"] == "0"
            return copy.deepcopy(cancel)
        if endpoint == "create_transaction" and fee_bundle is not None:
            assert payload["selected_coin_ids"] == [FEE_ROOT.name().hex()]
            return copy.deepcopy(fee_bundle)
        pytest.fail(f"unexpected wallet endpoint: {endpoint}")

    monkeypatch.setattr(adapter, "_sage_post", post)
    return adapter.build_cancel_offers_batch_unsigned(
        [TRADE], fee_mojos=fee, source_coin_ids=[ROOT.name().hex()],
        fee_coin_id=FEE_ROOT.name().hex())


@pytest.mark.parametrize("fee", [0, 25])
def test_real_native_cancellation_cost_and_fee_are_bound_without_submission(adapter, monkeypatch, fee):
    result = build(adapter, monkeypatch, fee, native_bundle(ROOT, 0), native_bundle(FEE_ROOT, fee))
    assert result.get("_catalyst_validated_cancel_unsigned") is True
    assert int(result["summary"]["fee"]) == fee
    assert result["_catalyst_exact_unsigned_cost"] > 0
    spends, conditions = adapter._unsigned_bundle_conditions(result)
    assert len(spends) == (2 if fee else 1)
    assert int(conditions.removal_amount) - int(conditions.addition_amount) == fee


@pytest.mark.parametrize("fee,component", [(0, "cancel"), (25, "cancel"), (25, "fee")])
@pytest.mark.parametrize("mismatch", ["amount", "destination"])
def test_cancel_builder_refuses_executable_summary_disagreement(
    adapter, monkeypatch, fee, component, mismatch
):
    cancel, fee_bundle = native_bundle(ROOT, 0), native_bundle(FEE_ROOT, fee)
    root, raw = (ROOT, cancel) if component == "cancel" else (FEE_ROOT, fee_bundle)
    claimed = int(raw["summary"]["inputs"][0]["outputs"][0]["amount"])
    # Keep the superficially valid summary/root IDs but change actual CLVM.
    raw["coin_spends"] = [CoinSpend(root, PUZZLE, Program.to([[51,
        b"x" * 32 if mismatch == "destination" else DESTINATION,
        claimed - 100 if mismatch == "amount" else claimed]])).to_json_dict()]
    result = build(adapter, monkeypatch, fee, cancel, fee_bundle)
    assert result.get("success") is False
    assert result.get("reason") == "SAGE_BULK_CANCEL_UNSIGNED_UNSAFE"
    assert result.get("_catalyst_validated_cancel_unsigned") is not True


@pytest.mark.parametrize("sealed", [False, True])
def test_cancel_submit_revalidates_actual_effects_even_with_matching_digest(adapter, monkeypatch, sealed):
    raw = native_bundle(ROOT, 0)
    raw["coin_spends"] = native_bundle(ROOT, 100)["coin_spends"]
    raw["_catalyst_validated_cancel_unsigned"] = True
    raw["_catalyst_exact_unsigned_cost"] = adapter.estimate_unsigned_transaction_cost(raw)
    raw["_catalyst_cancel_unsigned_digest"] = hashlib.sha256(json.dumps(
        {"summary": raw["summary"], "coin_spends": raw["coin_spends"]},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    def post(endpoint, *_args, **_kwargs):
        if not sealed and endpoint == "cancel_offers":
            return raw
        pytest.fail("cancellation attempted an unexpected RPC")
    monkeypatch.setattr(adapter, "_sage_post", post)
    result = adapter.cancel_offers_batch([TRADE], fee_mojos=0,
        source_coin_ids=[ROOT.name().hex()], fee_coin_id=FEE_ROOT.name().hex(),
        _validated_unsigned=raw if sealed else None)
    assert result[TRADE]["success"] is False


def test_real_cat2_cancellation_is_not_rejected_by_native_effect_validation(adapter, monkeypatch):
    raw = json.loads((Path(__file__).parent / "fixtures" / "coin_prep_unsigned_cat2.json").read_text())
    root_id = raw["summary"]["inputs"][0]["coin_id"]
    monkeypatch.setattr(adapter, "_sage_post", lambda *_args, **_kwargs: copy.deepcopy(raw))
    result = adapter.build_cancel_offers_batch_unsigned([TRADE], fee_mojos=0,
        source_coin_ids=[root_id], fee_coin_id=FEE_ROOT.name().hex())
    assert result.get("_catalyst_validated_cancel_unsigned") is True
    assert result["_catalyst_exact_unsigned_cost"] > 0
