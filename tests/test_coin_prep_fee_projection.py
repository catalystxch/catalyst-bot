"""Future costs must execute a bounded, explicitly projected standard profile."""

from importlib import import_module

from chia_rs import Coin, CoinSpend, Program
import pytest

import wallet
import wallet_sage
from fee_projection_test_utils import standard_puzzles


@pytest.fixture
def puzzles(monkeypatch):
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", wallet_sage)

    def forbidden(*_args, **_kwargs):
        pytest.fail("future cost projection attempted wallet RPC, signing or submission")

    monkeypatch.setattr(wallet_sage, "_sage_post", forbidden)
    monkeypatch.setattr(wallet, "build_transaction_rpc", forbidden)
    monkeypatch.setattr(wallet, "submit_built_transaction_rpc", forbidden)
    return standard_puzzles()


def _project(puzzles, **overrides):
    try:
        module = import_module("coin_prep_fee_projection")
    except ModuleNotFoundError:
        pytest.fail("CLVM-based future fee projection is missing")
    args = {"native_puzzle": puzzles[0], "cat_puzzle": puzzles[1],
            "xch_inputs": 1, "cat_inputs": 0, "xch_outputs": 2}
    args.update(overrides)
    return module.project_standard_cost(**args)


def test_future_native_projection_executes_clvm_without_exposing_spends(puzzles):
    result = _project(puzzles)
    assert result["available"] is True
    assert result["cost_kind"] == "projected"
    assert result["dispatch_authorized"] is False
    assert type(result["cost"]) is int and result["cost"] > 5_000_000
    assert result["input_count_max"] == 1
    assert result["output_count_max"] == 2
    assert "coin_spends" not in result and "validated_unsigned" not in result
    assert result["assumptions"] == ["standard_p2_cat2_only", "max_width_atomic_amounts",
                                     "one_32_byte_output_hint", "all_input_concurrent_spend_mesh",
                                     "linked_cat_ring_max_width_subtotals"]


def test_projected_cost_increases_with_real_inputs_outputs_and_cat_wrappers(puzzles):
    native = _project(puzzles)
    more_inputs = _project(puzzles, xch_inputs=2)
    more_outputs = _project(puzzles, xch_outputs=3)
    cancellation = _project(puzzles, cat_inputs=2)
    assert more_inputs["cost"] > native["cost"]
    assert more_outputs["cost"] > native["cost"]
    assert cancellation["available"] is True
    assert cancellation["cost"] > more_inputs["cost"]
    assert cancellation["input_count_max"] == 3
    assert cancellation["output_count_max"] == 4


def test_projection_covers_a_real_smaller_native_standard_transaction(puzzles):
    puzzle = puzzles[0]
    root = Coin(bytes.fromhex("31" * 32), puzzle.get_tree_hash(), 3000)
    conditions = [[51, bytes.fromhex("32" * 32), 1000], [51, bytes.fromhex("32" * 32), 1900]]
    spend = CoinSpend(root, puzzle, Program.to([[], (1, conditions), []]))
    actual_cost = wallet.estimate_unsigned_transaction_cost({"coin_spends": [spend.to_json_dict()]})
    assert type(actual_cost) is int and actual_cost > 0
    assert _project(puzzles)["cost"] >= actual_cost


@pytest.mark.parametrize("change", [{"native_puzzle": Program.to(1)},
                                   {"cat_puzzle": Program.to(1), "cat_inputs": 1},
                                   {"cat_puzzle": None, "cat_inputs": 1}])
def test_unknown_wrappers_do_not_receive_a_heuristic_price(puzzles, change):
    result = _project(puzzles, **change)
    assert result["available"] is False
    assert result["reason"] == "FEE_PROJECTION_PUZZLE_UNSUPPORTED"
    assert result.get("cost") is None


@pytest.mark.parametrize("change", [{"xch_inputs": True}, {"cat_inputs": 1.5},
                                   {"xch_outputs": -1}, {"xch_inputs": 0},
                                   {"xch_inputs": 51}, {"cat_inputs": 51},
                                   {"xch_outputs": 129}])
def test_unbounded_or_coerced_profiles_refuse_without_wallet_effects(puzzles, change):
    with pytest.raises(ValueError, match="FEE_PROJECTION_PROFILE_INVALID"):
        _project(puzzles, **change)


def test_unavailable_executable_cost_cannot_fall_back_to_flat_guess(puzzles, monkeypatch):
    monkeypatch.setattr(wallet, "estimate_unsigned_transaction_cost", lambda _bundle: None)
    result = _project(puzzles)
    assert result["available"] is False
    assert result["reason"] == "FEE_PROJECTION_COST_UNAVAILABLE"
    assert result.get("cost") is None


@pytest.mark.parametrize("cost", [True, -1, 0, "10000000", 11_000_000_001])
def test_invalid_or_over_consensus_cost_is_not_a_usable_projection(puzzles, monkeypatch, cost):
    monkeypatch.setattr(wallet, "estimate_unsigned_transaction_cost", lambda _bundle: cost)
    result = _project(puzzles)
    assert result["available"] is False
    assert result["reason"] == "FEE_PROJECTION_COST_UNAVAILABLE"


def test_total_output_profile_is_bounded_including_cat_returns(puzzles):
    with pytest.raises(ValueError, match="FEE_PROJECTION_PROFILE_INVALID"):
        _project(puzzles, xch_outputs=128, cat_inputs=1)


def test_maximum_native_and_bulk_cancel_profiles_execute(puzzles):
    native = _project(puzzles, xch_inputs=50, xch_outputs=128)
    cancel = _project(puzzles, xch_inputs=24, cat_inputs=23, xch_outputs=24)
    assert native["available"] is True
    assert cancel["available"] is True
    assert 0 < native["cost"] < 11_000_000_000
    assert 0 < cancel["cost"] < 11_000_000_000


def test_projection_amounts_keep_max_width_even_at_output_limit(puzzles, monkeypatch):
    observed = []
    original = wallet.estimate_unsigned_transaction_cost

    def inspect(bundle):
        _, node = Program.to(1).run_rust(10000, 0,
                                        Program.fromhex(bundle["coin_spends"][0]["solution"][2:]))
        # Standard solution: nil, quoted delegated conditions, nil.
        conditions = node.pair[1].pair[0].pair[1]
        while conditions.pair is not None:
            condition, conditions = conditions.pair
            if condition.pair[0].atom == b"3":
                observed.append(condition.pair[1].pair[1].pair[0].atom)
        return original(bundle)

    monkeypatch.setattr(wallet, "estimate_unsigned_transaction_cost", inspect)
    assert _project(puzzles, xch_outputs=128)["available"] is True
    assert len(observed) == 128
    assert all(len(amount) == 8 for amount in observed)


def test_cat_projection_covers_observed_linked_ring_cost(puzzles):
    # Independently executed two-CAT ring: same root/output counts, mesh/hints,
    # both CAT returns on the second spend, and a nonzero eight-byte subtotal.
    assert _project(puzzles, cat_inputs=2)["cost"] >= 80_743_184


@pytest.mark.parametrize("cat_count", [2, 3, 23])
@pytest.mark.parametrize("distribution", ["first", "last", "distributed"])
def test_projection_covers_real_linked_cat_return_distributions(
        puzzles, monkeypatch, cat_count, distribution):
    from fee_projection_test_utils import _python_tree

    original = wallet.estimate_unsigned_transaction_cost
    captured = []

    def capture(bundle):
        captured.append(bundle)
        return original(bundle)

    monkeypatch.setattr(wallet, "estimate_unsigned_transaction_cost", capture)
    projected = _project(puzzles, cat_inputs=cat_count)
    spends = [CoinSpend.from_json_dict(raw) for raw in captured[-1]["coin_spends"]]
    cats = spends[1:]
    destinations = [0 if distribution == "first" else cat_count - 1
                    if distribution == "last" else index for index in range(cat_count)]
    deltas = [coin.coin.amount - sum(other.coin.amount for index, other in enumerate(cats)
                                    if destinations[index] == position)
              for position, coin in enumerate(cats)]
    subtotals, subtotal = [], 0
    for delta in deltas:
        subtotals.append(subtotal)
        subtotal += delta
    assert subtotal == 0
    offset = min(subtotals)
    linked = [spends[0]]
    for index, spend in enumerate(cats):
        _, node = Program.to(1).run_rust(10000, 0, spend.solution)
        tree, solution = _python_tree(node), []
        while isinstance(tree, tuple):
            value, tree = tree
            solution.append(value)
        assert tree == b"" and len(solution) == 7
        conditions = [[64, other.coin.name()] for other in spends if other.coin != spend.coin]
        conditions += [[51, puzzles[0].get_tree_hash(), other.coin.amount, [b"h" * 32]]
                       for position, other in enumerate(cats) if destinations[position] == index]
        next_coin = cats[(index + 1) % cat_count].coin
        solution[0] = [[], (1, conditions), []]
        solution[2] = cats[(index - 1) % cat_count].coin.name()
        solution[4] = [next_coin.parent_coin_info, puzzles[0].get_tree_hash(), next_coin.amount]
        solution[5] = subtotals[index] - offset
        linked.append(CoinSpend(spend.coin, spend.puzzle_reveal, Program.to(solution)))
    actual = original({"coin_spends": [spend.to_json_dict() for spend in linked]})
    assert type(actual) is int and actual > 0
    assert projected["cost"] >= actual
