from types import SimpleNamespace

import pytest


def test_exact_funding_defaults_uses_unprotected_integer_inventory(monkeypatch):
    import confidence_override
    import coin_prep_fee_runtime
    from follow_run_defaults import exact_funding_defaults

    configuration = {
        "CAT_DECIMALS": 3,
        "FEE_PREP_COUNT": 5,
        "FEE_COIN_SIZE_XCH": "0.2",
        "XCH_RESERVE": "0.5",
        "CAT_RESERVE": "10.125",
        "MAX_ACTIVE_BUY_OFFERS": 24,
        "MAX_ACTIVE_SELL_OFFERS": 24,
    }
    coins = (
        SimpleNamespace(
            asset="xch",
            amount_mojos=5_000_000_000_000,
            selectable=True,
            protected=False,
        ),
        SimpleNamespace(
            asset="xch", amount_mojos=1_000_000_000_000, selectable=True, protected=True
        ),
        SimpleNamespace(
            asset="cat", amount_mojos=200_000, selectable=True, protected=False
        ),
    )
    monkeypatch.setattr(
        confidence_override, "current_configuration_digest", lambda: "a" * 64
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_fee_wallet_snapshot",
        lambda: {
            "configuration": configuration,
            "snapshot": SimpleNamespace(coins=coins),
            "identity": {"wallet_fingerprint": 123},
        },
    )
    result = exact_funding_defaults()
    assert result["fee_coin_principal_mojos"] == "1000000000000"
    assert result["maximum_trade_xch_mojos"] == "3500000000000"
    assert result["maximum_trade_cat_atoms"] == "189875"
    assert result["buy_target"] == result["sell_target"] == 24
    assert result["funded_estimate"] == {
        "available": False,
        "buy": 0,
        "sell": 0,
        "kind": "nonbinding_current_inventory_estimate",
    }


def test_exact_funding_defaults_returns_nonbinding_funded_estimate(monkeypatch):
    import api_server
    import confidence_override
    import coin_prep_fee_runtime
    import coin_prep_economics
    import follow_slot_fit
    import tx_fees
    from follow_run_defaults import exact_funding_defaults

    configuration = {
        "CAT_DECIMALS": 3,
        "FEE_PREP_COUNT": 1,
        "FEE_COIN_SIZE_XCH": "0.2",
        "XCH_RESERVE": "0.5",
        "CAT_RESERVE": "10",
        "MAX_ACTIVE_BUY_OFFERS": 100,
        "MAX_ACTIVE_SELL_OFFERS": 100,
    }
    coins = (
        SimpleNamespace(
            asset="xch",
            amount_mojos=2_000_000_000_000,
            selectable=True,
            protected=False,
        ),
        SimpleNamespace(
            asset="cat", amount_mojos=200_000, selectable=True, protected=False
        ),
    )
    monkeypatch.setattr(
        confidence_override, "current_configuration_digest", lambda: "a" * 64
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_fee_wallet_snapshot",
        lambda: {
            "configuration": configuration,
            "snapshot": SimpleNamespace(coins=coins),
            "identity": {"wallet_fingerprint": 123},
        },
    )
    monkeypatch.setattr(api_server, "_get_readonly_mid_price_str", lambda: "1")
    monkeypatch.setattr(tx_fees, "get_fee_pool_plan", lambda: {})
    monkeypatch.setattr(
        coin_prep_economics,
        "build_standard_prep_economics",
        lambda **kwargs: {"targets": ()},
    )
    monkeypatch.setattr(
        follow_slot_fit,
        "preview_current_follow_slot_fit",
        lambda **kwargs: {"funded_buy_limit": 40, "funded_sell_limit": 30},
    )

    result = exact_funding_defaults()

    assert result["funded_estimate"] == {
        "available": True,
        "buy": 40,
        "sell": 30,
        "kind": "nonbinding_current_inventory_estimate",
    }


@pytest.mark.parametrize("reserve", ["0.0000000000001", "-1", "NaN"])
def test_exact_funding_defaults_rejects_non_atomic_or_invalid_reserve(
    monkeypatch, reserve
):
    import confidence_override
    import coin_prep_fee_runtime
    from follow_run_defaults import exact_funding_defaults

    monkeypatch.setattr(
        confidence_override, "current_configuration_digest", lambda: "a" * 64
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_fee_wallet_snapshot",
        lambda: {
            "configuration": {
                "CAT_DECIMALS": 3,
                "FEE_PREP_COUNT": 1,
                "FEE_COIN_SIZE_XCH": "0.1",
                "XCH_RESERVE": reserve,
                "CAT_RESERVE": "0",
                "MAX_ACTIVE_BUY_OFFERS": 1,
                "MAX_ACTIVE_SELL_OFFERS": 1,
            },
            "snapshot": SimpleNamespace(coins=()),
            "identity": {},
        },
    )
    with pytest.raises(ValueError, match="FOLLOW_RUN_DEFAULTS_CONFIG_INVALID"):
        exact_funding_defaults()
