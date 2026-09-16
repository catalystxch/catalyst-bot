"""Preview and execution must agree on every atomic prepared output."""

from decimal import Decimal
from importlib import import_module

import pytest

import coin_prep_worker


def _targets(**overrides):
    try:
        planning = import_module("coin_prep_targets")
    except ModuleNotFoundError:
        pytest.fail("shared atomic Coin Prep output planner is missing")
    args = {
        "tier_order": ("inner", "mid", "fees"),
        "xch_counts": {"inner": 2, "mid": 1, "fees": 2},
        "cat_counts": {"inner": 1, "mid": 2},
        "xch_sizes": {"inner": Decimal("1.1"), "mid": Decimal("0.5"),
                      "fees": Decimal("0.001")},
        "cat_sizes": {"inner": Decimal("100.0001"), "mid": Decimal("20.00001")},
        "cat_decimals": 3,
    }
    args.update(overrides)
    return planning.build_prep_targets(**args)


def test_prepared_atomic_outputs_use_exact_xch_and_upward_cat_rounding():
    targets = _targets()
    assert [(t.asset, t.purpose, t.tier_rank, t.amount_mojos, t.ordinal) for t in targets] == [
        ("xch", "replacement", 0, 1_100_000_000_000, 0),
        ("xch", "replacement", 0, 1_100_000_000_000, 1),
        ("xch", "replacement", 1, 500_000_000_000, 2),
        ("xch", "fee_reserve", 2, 1_000_000_000, 3),
        ("xch", "fee_reserve", 2, 1_000_000_000, 4),
        ("cat", "replacement", 0, 100_001, 0),
        ("cat", "replacement", 1, 20_001, 1),
        ("cat", "replacement", 1, 20_001, 2),
    ]


def test_empty_side_does_not_invent_coins_or_require_its_sizes():
    targets = _targets(cat_counts={}, cat_sizes={})
    assert len(targets) == 5
    assert {target.asset for target in targets} == {"xch"}


@pytest.mark.parametrize("counts", [{"inner": True}, {"inner": 1.0},
                                    {"inner": -1}, {"hidden": 1}, {"inner": 10_001}])
def test_malformed_or_unrepresented_counts_cannot_become_targets(counts):
    with pytest.raises(ValueError):
        _targets(xch_counts=counts)


@pytest.mark.parametrize("value", [True, 1.0, Decimal("NaN"), Decimal("Infinity"),
                                   Decimal("-1"), Decimal("0"), Decimal("10000000")])
def test_bad_prepared_amounts_cannot_become_atomic_effects(value):
    with pytest.raises(ValueError):
        _targets(xch_sizes={"inner": value, "mid": Decimal("0.5"), "fees": Decimal("0.001")})


@pytest.mark.parametrize("decimals", [True, 3.0, -1, 19])
def test_invalid_cat_scale_is_rejected(decimals):
    with pytest.raises(ValueError):
        _targets(cat_decimals=decimals)


def test_duplicate_tier_cannot_repeat_the_same_outputs():
    with pytest.raises(ValueError):
        _targets(tier_order=("inner", "inner", "fees"))


def test_cat_fee_tier_is_rejected_instead_of_claiming_xch_fee_funding():
    with pytest.raises(ValueError):
        _targets(cat_counts={"fees": 1}, cat_sizes={"fees": Decimal("1")})


def test_worker_rejects_implicitly_coerced_coin_count():
    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.tier_order = ["inner"]
    worker.xch_tier_counts = {"inner": True}
    worker.cat_tier_counts = {}
    worker.tier_xch_sizes = {"inner": Decimal("1")}
    worker.tier_cat_sizes = {}
    worker.cat_decimals = 3
    with pytest.raises(ValueError):
        worker._direct_batch_targets()
