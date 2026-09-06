from dataclasses import replace

import pytest

from coin_prep_batch_plan import (
    BatchConstraints,
    BatchPlan,
    BatchRefusal,
    CoinSnapshot,
    SelectableCoin,
    TargetOutput,
    plan_batch,
)


def coin(asset, name, amount, *, purpose="", selectable=True, protected=False):
    return SelectableCoin(asset, name, amount, purpose, selectable, protected)


def target(asset, purpose, amount, ordinal, rank=0):
    return TargetOutput(asset, purpose, rank, amount, ordinal)


def constraints(**changes):
    base = BatchConstraints({"xch": 100, "cat": 50}, fee_mojos=10)
    return replace(base, **changes)


def test_plan_is_deterministic_and_conserves_cat_with_external_xch_fee():
    snapshot = CoinSnapshot(
        (coin("cat", "c2", 800), coin("cat", "c1", 700), coin("xch", "f1", 30))
    )
    targets = (target("cat", "inner", 500, 1), target("cat", "inner", 500, 0))
    limits = constraints(reserve_floors={"xch": 0, "cat": 0})
    first = plan_batch(snapshot, targets, limits)
    second = plan_batch(snapshot, tuple(reversed(targets)), limits)
    assert first == second
    assert isinstance(first, BatchPlan)
    assert first.asset == "cat"
    assert first.source_coin_ids == ("c1", "c2")
    assert first.fee_source_id == "f1"
    assert sum(o.amount_mojos for o in first.outputs if o.asset == "cat") == 1500
    assert (
        sum(o.amount_mojos for o in first.outputs if o.asset == "xch") + first.fee_mojos
        == 30
    )


def test_ready_targets_reuse_distinct_coins_without_a_transaction():
    targets = (target("xch", "fee", 10, 0), target("xch", "fee", 10, 1))
    result = plan_batch(
        CoinSnapshot(
            (coin("xch", "b", 10, purpose="fee"), coin("xch", "a", 10, purpose="fee"))
        ),
        targets,
        constraints(fee_mojos=0, reserve_floors={"xch": 0, "cat": 0}),
    )
    assert isinstance(result, BatchPlan)
    assert result.transaction_required is False
    assert result.reused_coin_ids == ("a", "b")
    assert result.reused_target_ids == (("xch", 0), ("xch", 1))


def test_reused_target_identity_cannot_collide_between_assets():
    result = plan_batch(
        CoinSnapshot(
            (
                coin("xch", "x-ready", 10, purpose="tier"),
                coin("cat", "c-ready", 10, purpose="tier"),
            )
        ),
        (
            target("xch", "tier", 10, 0),
            target("cat", "tier", 10, 0),
        ),
        constraints(fee_mojos=0, reserve_floors={"xch": 0, "cat": 0}),
    )
    assert isinstance(result, BatchPlan)
    assert result.reused_target_ids == (("cat", 0), ("xch", 0))


def test_partial_reuse_never_selects_reused_or_protected_coins_as_sources():
    result = plan_batch(
        CoinSnapshot(
            (
                coin("xch", "ready", 20, purpose="mid"),
                coin("xch", "locked", 1000, protected=True),
                coin("xch", "source", 50),
            )
        ),
        (target("xch", "mid", 20, 0), target("xch", "mid", 20, 1)),
        constraints(fee_mojos=5, reserve_floors={"xch": 20, "cat": 0}),
    )
    assert isinstance(result, BatchPlan)
    assert result.reused_coin_ids == ("ready",)
    assert result.source_coin_ids == ("source",)
    assert "locked" not in result.source_coin_ids


@pytest.mark.parametrize(
    "bad_coins",
    [
        (coin("xch", "same", 10), coin("xch", "same", 20)),
        (coin("xch", "a", 0),),
        (coin("xch", "a", -1),),
    ],
)
def test_malformed_snapshots_are_refused(bad_coins):
    result = plan_batch(
        CoinSnapshot(bad_coins),
        (target("xch", "mid", 5, 0),),
        constraints(reserve_floors={"xch": 0, "cat": 0}),
    )
    assert isinstance(result, BatchRefusal)
    assert result.code == "INVALID_SNAPSHOT"


def test_fragmentation_over_input_cap_requests_bounded_prerequisite():
    result = plan_batch(
        CoinSnapshot(tuple(coin("xch", f"c{i:02}", 10) for i in range(6))),
        (target("xch", "mid", 45, 0),),
        constraints(max_asset_inputs=4, reserve_floors={"xch": 0, "cat": 0}),
    )
    assert isinstance(result, BatchRefusal)
    assert result.code == "INPUT_CAP_REQUIRES_PREREQUISITE"
    assert result.prerequisite_allowed is True


def test_output_cap_refuses_before_selecting_inputs():
    result = plan_batch(
        CoinSnapshot((coin("cat", "cat-source", 1000), coin("xch", "fee", 100))),
        tuple(target("cat", "mid", 10, i) for i in range(5)),
        constraints(max_outputs=4, reserve_floors={"xch": 0, "cat": 0}),
    )
    assert isinstance(result, BatchRefusal)
    assert result.code == "OUTPUT_CAP_EXCEEDED"


def test_reserve_floor_counts_fee_and_refuses_erosion():
    result = plan_batch(
        CoinSnapshot((coin("xch", "source", 100),)),
        (target("xch", "mid", 80, 0),),
        constraints(reserve_floors={"xch": 95, "cat": 0}, fee_mojos=10),
    )
    assert isinstance(result, BatchRefusal)
    assert result.code == "RESERVE_FLOOR"


def test_cat_without_separate_fee_source_requests_compatibility_prerequisite():
    result = plan_batch(
        CoinSnapshot(
            (
                coin("cat", "cat-source", 1_000),
                coin("xch", "only-xch", 10, purpose="fee"),
            )
        ),
        (target("cat", "mid", 100, 0), target("xch", "fee", 10, 0)),
        constraints(reserve_floors={"xch": 0, "cat": 0}, fee_mojos=10),
    )
    assert isinstance(result, BatchRefusal)
    assert result.code == "FEE_SOURCE_REQUIRED"
    assert result.prerequisite_allowed is True


def test_protected_balance_cannot_satisfy_reserve_floor():
    result = plan_batch(
        CoinSnapshot(
            (
                coin("xch", "source", 100),
                coin("xch", "offer-locked", 1_000, protected=True),
            )
        ),
        (target("xch", "mid", 80, 0),),
        constraints(reserve_floors={"xch": 95, "cat": 0}, fee_mojos=10),
    )
    assert isinstance(result, BatchRefusal)
    assert result.code == "RESERVE_FLOOR"


def test_designated_protected_reserve_counts_toward_floor_but_is_not_spent():
    """Removing reserve-designated balance from floor accounting blocks safe prep."""
    result = plan_batch(
        CoinSnapshot(
            (
                coin("xch", "source", 20),
                coin(
                    "xch",
                    "protected-reserve",
                    30,
                    purpose="reserve",
                    protected=True,
                ),
            )
        ),
        (target("xch", "mid", 10, 0),),
        constraints(reserve_floors={"xch": 30, "cat": 0}, fee_mojos=10),
    )
    assert isinstance(result, BatchPlan)
    assert result.source_coin_ids == ("source",)
    assert "protected-reserve" not in result.source_coin_ids


def test_equal_outputs_remain_separate_planned_outputs():
    result = plan_batch(
        CoinSnapshot((coin("xch", "source", 100),)),
        tuple(target("xch", "mid", 20, i) for i in range(3)),
        constraints(reserve_floors={"xch": 0, "cat": 0}, fee_mojos=0),
    )
    trading = [o for o in result.outputs if o.purpose == "mid"]
    assert [o.amount_mojos for o in trading] == [20, 20, 20]
    assert [o.ordinal for o in trading] == [0, 1, 2]


def test_observed_size_fixture_needs_one_cat_then_one_xch_batch():
    xch_targets = tuple(target("xch", "tier", 10, i) for i in range(126))
    cat_targets = tuple(target("cat", "tier", 10, i) for i in range(76))
    limits = constraints(max_outputs=128, reserve_floors={"xch": 0, "cat": 0})
    first = plan_batch(
        CoinSnapshot(
            (
                coin("cat", "cat-source", 1000),
                coin("xch", "fee", 20),
                coin("xch", "x-source", 2000),
            )
        ),
        xch_targets + cat_targets,
        limits,
    )
    assert isinstance(first, BatchPlan) and first.asset == "cat"
    prepared_cat = tuple(
        coin("cat", f"prepared-{i}", 10, purpose="tier") for i in range(76)
    )
    second = plan_batch(
        CoinSnapshot(prepared_cat + (coin("xch", "x-source", 2000),)),
        xch_targets + cat_targets,
        limits,
    )
    assert isinstance(second, BatchPlan) and second.asset == "xch"
    assert len(first.outputs) <= 128 and len(second.outputs) <= 128
