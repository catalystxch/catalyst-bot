"""Full read-only runtime preview must price future stages and cancellation."""

import json
from importlib import import_module

import pytest

import database
import fee_approval_test_utils as utils
from fee_staged_preview_utils import prepare_unsigned_wallet


@pytest.fixture
def staged(tmp_path, monkeypatch):
    yield_from = utils.live_reads(tmp_path, monkeypatch)
    state = next(yield_from)
    utils.economic_reads(state, monkeypatch)
    runtime = import_module("coin_prep_fee_runtime")
    service = import_module("coin_prep_fee_approval")
    pricing = import_module("coin_prep_fee_pricing")
    monkeypatch.setattr(runtime, "cfg", state["config"])
    state["now"] = 1000
    monkeypatch.setattr(service, "_now", lambda: state["now"])
    monkeypatch.setattr(pricing, "_now", lambda: state["now"])

    def quote(cost, target_seconds):
        if state.get("quote_hook"):
            state["quote_hook"]()
        return {"available": True, "fee_mojos": 20, "source": "coinset", "cost": cost,
                "target_seconds": target_seconds, "observed_at": 1000, "expires_at": 1060}

    monkeypatch.setattr(service, "quote_fee", quote)
    monkeypatch.setattr(pricing, "quote_fee", quote)
    state["quote"] = quote
    prepare_unsigned_wallet(state, monkeypatch)
    yield state
    try:
        next(yield_from)
    except StopIteration:
        pass


def preview(options=None):
    function = getattr(import_module("coin_prep_fee_approval"), "preview_coin_prep_fees", None)
    assert callable(function), "full staged runtime fee preview is missing"
    return function({} if options is None else options)


def test_runtime_preview_prices_exact_cat_future_native_and_protected_cancels(staged):
    result = preview()
    assert result["available"] is True and result["funded"] is True
    assert result["dispatch_authorized"] is False
    assert result["target_seconds"] == 300
    assert [(s["stage_id"], s["cost_kind"], s["cancellation"], s["transaction_count_max"])
            for s in result["stages"]] == [
        ("prep_cat", "exact_unsigned", False, 1), ("prep_xch", "projected", False, 1),
        ("cancel_xch", "projected", True, 1), ("cancel_cat", "projected", True, 1)]
    assert result["estimated_preparation_fee_mojos"] == 40
    assert result["estimated_cancellation_fee_mojos"] == 40
    assert result["estimated_total_fee_mojos"] == 80
    assert result["fee_coin_principal_mojos"] == 2_000_000_000
    assert result["fee_funding_mojos"] == 88_000_000_000
    assert "native_output_ephemeral_spends" in result["stages"][1]["profile"]["assumptions"]
    saved = database.get_coin_prep_fee_preview(result["preview_id"])
    assert json.loads(saved["quote_json"])["stages"] == result["stages"]
    assert not any(utils._counts().values())
    assert "validated_unsigned" not in json.dumps(result) and "coin_spends" not in json.dumps(result)


@pytest.mark.parametrize("options", [{"stages": []}, {"scope": {}}, {"funding": 100}, {"cost": 1}])
def test_client_authority_is_rejected_before_wallet_reads(staged, options):
    with pytest.raises(ValueError, match="FEE_PREP_OPTIONS_INVALID"):
        preview(options)
    assert staged["reads"] == [] and not staged.get("builds")


def test_projection_quote_unavailable_cannot_produce_confirmable_preview(staged, monkeypatch):
    service = import_module("coin_prep_fee_approval")
    monkeypatch.setattr(service, "quote_fee", lambda *_a, **_k: {"available": False})
    result = preview()
    assert result["available"] is False
    assert result.get("preview_id") is None
    assert not any(utils._counts().values())


def test_changed_wallet_during_projected_quote_is_rejected_before_persistence(staged):
    calls = []

    def change_after_exact_quotes():
        calls.append(1)
        if len(calls) == 3:
            staged["identity"]["fingerprint"] = 12345

    staged["quote_hook"] = change_after_exact_quotes
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        preview()
    assert database.get_connection().execute("SELECT COUNT(*) FROM coin_prep_fee_previews").fetchone()[0] == 0


def test_sage_bare_hex_unsigned_spends_can_supply_verified_projection_templates(staged, monkeypatch):
    wallet = import_module("wallet")
    build = wallet.build_transaction_rpc

    def bare_hex(ids, actions):
        result = build(ids, actions)
        for spend in result["coin_spends"]:
            for key in ("puzzle_reveal", "solution"):
                spend[key] = spend[key].removeprefix("0x")
            for key in ("parent_coin_info", "puzzle_hash"):
                spend["coin"][key] = spend["coin"][key].removeprefix("0x")
        return result

    monkeypatch.setattr(wallet, "build_transaction_rpc", bare_hex)
    result = preview()
    assert result["available"] is True
    assert result["estimated_total_fee_mojos"] == 80
    assert not any(utils._counts().values())


def test_latency_cannot_refresh_original_quote_age_or_persist_confirmable_preview(staged):
    calls = []

    def expire_last_quote():
        calls.append(1)
        if len(calls) == 5:
            staged["now"] = 1060

    staged["quote_hook"] = expire_last_quote
    result = preview()
    assert result["available"] is False and result["reason"] == "FEE_ESTIMATE_UNAVAILABLE"
    assert result.get("preview_id") is None
    assert not any(utils._counts().values())


@pytest.mark.parametrize("mode,stages,total", [
    ("buy_only", ["prep_xch", "cancel_xch"], 40),
    ("sell_only", ["prep_cat", "prep_xch", "cancel_cat"], 60),
])
def test_one_sided_previews_price_only_required_preparation_and_protection(staged, mode, stages, total):
    staged["config"].LIQUIDITY_MODE = mode
    result = preview()
    assert result["available"] is True
    assert [stage["stage_id"] for stage in result["stages"]] == stages
    assert result["stages"][0]["cost_kind"] == "exact_unsigned"
    assert result["estimated_total_fee_mojos"] == total
    assert not any(utils._counts().values())


@pytest.mark.parametrize("root_count,amount,maximum,total", [
    (61, 2_000_000_000, 1, 100),
    (153, 800_000_000, 3, 140),
    (61, 3_000_000_000, 0, 80),
])
def test_future_fragmentation_prices_every_bounded_prerequisite(staged, root_count, amount, maximum, total):
    from chia_rs import Coin
    from fee_projection_test_utils import standard_puzzles

    native, _cat = standard_puzzles()
    staged["xch"] = []
    # Principal is 112b; total funding alone does not prove a 50-input
    # batch can fund it. A large enough cohort must not be overcharged.
    for index in range(root_count):
        coin = Coin(index.to_bytes(32, "big"), native.get_tree_hash(), amount)
        row = utils._coin(index + 1, str(coin.amount))
        row["coin_id"] = coin.name().hex()
        staged["xch"].append(row)
        staged["unsigned_roots"][coin.name().hex()] = (coin, native, None)
    result = preview()
    assert result["available"] is True and result["funded"] is True
    if maximum == 0:
        assert [stage["stage_id"] for stage in result["stages"]] == [
            "prep_cat", "prep_xch", "cancel_xch", "cancel_cat"]
        assert result["estimated_total_fee_mojos"] == 80
        assert not any(utils._counts().values())
        return
    assert [stage["stage_id"] for stage in result["stages"]] == [
        "prep_cat", "prep_xch_consolidation", "prep_xch", "cancel_xch", "cancel_cat"]
    consolidation = result["stages"][1]
    assert consolidation["cost_kind"] == "projected"
    assert consolidation["transaction_count_min"] == 1
    assert consolidation["transaction_count_max"] == maximum
    assert consolidation["profile"]["input_count_max"] == 50
    assert consolidation["profile"]["output_count_max"] == 1
    assert result["preparation_transaction_count_max"] == maximum + 2
    assert result["estimated_total_fee_mojos"] == total
    assert not any(utils._counts().values())
