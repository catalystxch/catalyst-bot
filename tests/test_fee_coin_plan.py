from decimal import Decimal

import pytest

from fee_coin_plan import plan_weekly_fee_coins


def test_week_plan_covers_two_operations_per_slot_per_day_plus_startup_and_shutdown():
    result = plan_weekly_fee_coins(
        estimated_fee_mojos=1_000_000,
        active_offer_target_count=5,
        allocatable_xch_mojos=20_000_000_000,
    )

    assert result["modeled_operation_count"] == 80
    assert result["target_fee_coin_count"] == 4
    assert result["fee_coin_size_mojos"] == 1_000_000_000
    assert result["fee_coin_count"] == 4
    assert result["fee_coin_principal_mojos"] == 4_000_000_000
    assert result["modeled_operations_per_coin"] == 20
    assert result["underfunded"] is False


def test_recent_activity_can_raise_weekly_operation_target():
    result = plan_weekly_fee_coins(
        estimated_fee_mojos=1_000_000,
        active_offer_target_count=5,
        recent_fee_operations_per_day=Decimal("20"),
        allocatable_xch_mojos=20_000_000_000,
    )

    assert result["modeled_operation_count"] == 150
    assert result["target_fee_coin_count"] == 8


def test_fee_coin_size_rounds_up_to_clean_million_mojo_step():
    result = plan_weekly_fee_coins(
        estimated_fee_mojos=60_000_001,
        active_offer_target_count=1,
        allocatable_xch_mojos=10_000_000_000,
    )

    assert result["fee_coin_size_mojos"] == 1_201_000_000


def test_shutdown_sized_minimum_coin_still_respects_wallet_allocation():
    result = plan_weekly_fee_coins(
        estimated_fee_mojos=13_079_100,
        active_offer_target_count=48,
        allocatable_xch_mojos=1_000_000_000_000,
        minimum_coin_size_mojos=4_660_000_000,
    )

    assert result["fee_coin_size_mojos"] == 4_660_000_000
    assert result["fee_coin_principal_mojos"] <= 1_000_000_000_000


def test_wallet_allocation_caps_count_without_overcommitting_principal():
    result = plan_weekly_fee_coins(
        estimated_fee_mojos=1_000_000,
        active_offer_target_count=5,
        allocatable_xch_mojos=2_500_000_000,
    )

    assert result["target_fee_coin_count"] == 4
    assert result["fee_coin_count"] == 2
    assert result["fee_coin_principal_mojos"] == 2_000_000_000
    assert result["fee_coin_principal_mojos"] <= 2_500_000_000
    assert result["underfunded"] is True


def test_large_fee_coin_models_a_full_week_for_48_offer_slots_with_39_coins():
    result = plan_weekly_fee_coins(
        estimated_fee_mojos=13_079_100,
        active_offer_target_count=48,
        allocatable_xch_mojos=1_000_000_000_000,
        minimum_coin_size_mojos=4_660_000_000,
    )

    assert result["modeled_operation_count"] == 768
    assert result["modeled_operations_per_coin"] == 20
    assert result["target_fee_coin_count"] == 39
    assert result["fee_coin_count"] == 39


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "estimated_fee_mojos": 0,
            "active_offer_target_count": 1,
            "allocatable_xch_mojos": 1_000_000_000,
        },
        {
            "estimated_fee_mojos": -1,
            "active_offer_target_count": 1,
            "allocatable_xch_mojos": 1_000_000_000,
        },
        {
            "estimated_fee_mojos": 1,
            "active_offer_target_count": 0,
            "allocatable_xch_mojos": 1_000_000_000,
        },
        {
            "estimated_fee_mojos": 1,
            "active_offer_target_count": 1,
            "allocatable_xch_mojos": -1,
        },
        {
            "estimated_fee_mojos": True,
            "active_offer_target_count": 1,
            "allocatable_xch_mojos": 1_000_000_000,
        },
    ],
)
def test_invalid_inputs_are_rejected(kwargs):
    with pytest.raises(ValueError):
        plan_weekly_fee_coins(**kwargs)


def test_recent_activity_must_be_nonnegative():
    with pytest.raises(ValueError):
        plan_weekly_fee_coins(
            estimated_fee_mojos=1,
            active_offer_target_count=1,
            recent_fee_operations_per_day=-1,
            allocatable_xch_mojos=1_000_000_000,
        )
