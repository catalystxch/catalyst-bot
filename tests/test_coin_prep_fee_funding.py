"""Fee capacity is separate from retained target principal and protected coins."""

from importlib import import_module
import pytest
from coin_prep_batch_plan import CoinSnapshot, SelectableCoin, TargetOutput, BatchConstraints, plan_batch


TARGETS = (TargetOutput("xch", "replacement", 0, 40, 0),
           TargetOutput("xch", "fee_reserve", 4, 10, 1),
           TargetOutput("cat", "replacement", 0, 20, 0))


def _coin(index, amount, asset="xch", purpose="", protected=False, selectable=True):
    return SelectableCoin(asset, f"{index:064x}", amount, purpose, selectable, protected)


def _prepare(coins, targets=TARGETS, floors=None):
    try:
        service = import_module("coin_prep_fee_funding")
    except ModuleNotFoundError:
        pytest.fail("runtime fee funding and reusable cohort classification are missing")
    return service.prepare_fee_inventory(CoinSnapshot(tuple(coins)), targets,
        {"xch": 20, "cat": 0} if floors is None else floors)


def test_fee_coin_face_value_and_trade_principal_are_not_available_for_fee_spending():
    result = _prepare([_coin(1, 100), _coin(2, 20, "cat")])
    assert result["fee_funding_mojos"] == 30
    assert result["retained_principal_mojos"] == {"xch": 50, "cat": 20}
    assert result["principal_funded"] is True
    assert result["reused_target_count"] == 1


def test_existing_physical_reserve_overlaps_the_floor_instead_of_being_charged_twice():
    result = _prepare([_coin(1, 30, purpose="reserve", protected=True),
                       _coin(2, 70), _coin(3, 20, "cat")])
    assert result["fee_funding_mojos"] == 20
    assert result["principal_funded"] is True
    reserved = next(coin for coin in result["snapshot"].coins if coin.coin_id == f"{1:064x}")
    assert reserved.protected is True
    assert reserved.purpose == "reserve"


def test_reconciliation_protected_coins_cannot_fund_the_floor_or_fees():
    result = _prepare([_coin(1, 30, purpose="protected", protected=True),
                       _coin(2, 70), _coin(3, 20, "cat")])
    assert result["fee_funding_mojos"] == 0
    assert result["principal_funded"] is True


def test_insufficient_cat_principal_is_not_hidden_by_plentiful_xch():
    result = _prepare([_coin(1, 1000), _coin(2, 19, "cat")])
    assert result["principal_funded"] is False
    assert result["fee_funding_mojos"] == 930


def test_exact_selectable_unprotected_cohorts_are_reused_without_rebuilding():
    result = _prepare([_coin(1, 40), _coin(2, 10), _coin(3, 20, "cat"), _coin(4, 20)])
    assert result["reused_target_count"] == 3
    assert [(c.coin_id, c.purpose) for c in result["snapshot"].coins] == [
        (f"{3:064x}", "replacement"), (f"{1:064x}", "replacement"),
        (f"{2:064x}", "fee_reserve"), (f"{4:064x}", "")]
    assert plan_batch(result["snapshot"], TARGETS,
        BatchConstraints({"xch": 20, "cat": 0}, 0)).transaction_required is False
    assert result["fee_funding_mojos"] == 0


def test_protected_or_unselectable_denomination_matches_do_not_satisfy_targets():
    result = _prepare([_coin(1, 40, purpose="reserve", protected=True),
                       _coin(2, 10, selectable=False), _coin(3, 20, "cat"), _coin(4, 100)])
    assert result["reused_target_count"] == 1
    assert result["fee_funding_mojos"] == 50


def test_same_amount_with_different_target_roles_is_assigned_once_per_coin():
    targets = (TargetOutput("xch", "replacement", 0, 10, 0),
               TargetOutput("xch", "fee_reserve", 4, 10, 1))
    result = _prepare([_coin(1, 10), _coin(2, 10), _coin(3, 10)], targets, {"xch": 0, "cat": 0})
    assert [c.purpose for c in result["snapshot"].coins] == ["fee_reserve", "replacement", ""]
    assert result["fee_funding_mojos"] == 10


@pytest.mark.parametrize("coin", [_coin(1, True), _coin(1, -1), _coin(1, 1.5),
                                 _coin(1, 40, protected=1), _coin(1, 40, selectable=1)])
def test_malformed_inventory_cannot_manufacture_funding(coin):
    with pytest.raises(ValueError):
        _prepare([coin])
