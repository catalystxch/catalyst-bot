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
