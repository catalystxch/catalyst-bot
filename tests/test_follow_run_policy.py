from decimal import Decimal

import pytest

from follow_run_policy import FollowRunPolicy


def policy(**overrides):
    values = {
        "wallet_fingerprint": "a" * 64,
        "network": "mainnet",
        "asset_id": "b" * 64,
        "buy_target": 100,
        "sell_target": 100,
        "price_anchor": Decimal("0.012300"),
        "price_min": Decimal("0.011"),
        "price_max": Decimal("0.013"),
        "maximum_fee_mojos_per_tx": 2_000_000,
        "fee_coin_principal_mojos": 8_000_000_000,
        "xch_reserve_mojos": 1_000_000_000,
        "cat_reserve_atoms": 25_000,
        "maximum_trade_xch_mojos": 2_000_000_000_000,
        "maximum_trade_cat_atoms": 1_000_000,
    }
    values.update(overrides)
    return FollowRunPolicy(**values)


def test_policy_is_frozen_and_digest_is_canonical():
    first = policy()
    equivalent = policy(price_anchor=Decimal("0.0123"))

    assert first.digest == equivalent.digest
    assert len(first.digest) == 64
    with pytest.raises(AttributeError):
        first.buy_target = 24


def test_material_changes_name_changed_terms():
    original = policy()
    changed = policy(buy_target=24, price_max=Decimal("0.014"))

    assert original.material_changes(changed) == ("buy_target", "price_max")
    assert original.material_changes(policy()) == ()


@pytest.mark.parametrize(
    "override",
    [
        {"buy_target": 0},
        {"sell_target": -1},
        {"maximum_fee_mojos_per_tx": 0},
        {"fee_coin_principal_mojos": -1},
        {"xch_reserve_mojos": 1.5},
        {"cat_reserve_atoms": True},
        {"price_anchor": Decimal("NaN")},
        {"price_min": Decimal("0.014")},
    ],
)
def test_policy_rejects_invalid_terms(override):
    with pytest.raises((TypeError, ValueError)):
        policy(**override)
