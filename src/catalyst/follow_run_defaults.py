"""Exact server-owned funding defaults for a single Follow approval."""

from __future__ import annotations

from decimal import Decimal


def _atomic(value: object, scale: int) -> int:
    try:
        amount = Decimal(str(value)) * (10**scale)
    except Exception as exc:
        raise ValueError("FOLLOW_RUN_DEFAULTS_CONFIG_INVALID") from exc
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise ValueError("FOLLOW_RUN_DEFAULTS_CONFIG_INVALID")
    return int(amount)


def exact_funding_defaults() -> dict:
    """Read a fresh wallet inventory; never accept financial amounts from JS."""
    import confidence_override
    from coin_prep_fee_runtime import read_fee_wallet_snapshot

    before = confidence_override.current_configuration_digest()
    observed = read_fee_wallet_snapshot()
    after = confidence_override.current_configuration_digest()
    if before != after:
        raise ValueError("FOLLOW_RUN_DEFAULTS_CONFIG_CHANGED")
    configuration = observed["configuration"]
    snapshot = observed["snapshot"]
    decimals = configuration["CAT_DECIMALS"]
    if type(decimals) is not int or not 0 <= decimals <= 18:
        raise ValueError("FOLLOW_RUN_DEFAULTS_CONFIG_INVALID")
    fee_count = configuration["FEE_PREP_COUNT"]
    if type(fee_count) is not int or fee_count < 0:
        raise ValueError("FOLLOW_RUN_DEFAULTS_CONFIG_INVALID")
    fee_principal = fee_count * _atomic(configuration["FEE_COIN_SIZE_XCH"], 12)
    xch_reserve = _atomic(configuration["XCH_RESERVE"], 12)
    cat_reserve = _atomic(configuration["CAT_RESERVE"], decimals)
    available = {"xch": 0, "cat": 0}
    for coin in snapshot.coins:
        if coin.asset not in available or type(coin.amount_mojos) is not int:
            raise ValueError("FOLLOW_RUN_DEFAULTS_INVENTORY_INVALID")
        if coin.selectable and not coin.protected:
            available[coin.asset] += coin.amount_mojos
    xch_trade = available["xch"] - xch_reserve - fee_principal
    cat_trade = available["cat"] - cat_reserve
    if xch_trade <= 0 or cat_trade <= 0:
        raise ValueError("FOLLOW_RUN_DEFAULTS_PRINCIPAL_INSUFFICIENT")
    buy = configuration["MAX_ACTIVE_BUY_OFFERS"]
    sell = configuration["MAX_ACTIVE_SELL_OFFERS"]
    if any(type(value) is not int or value <= 0 for value in (buy, sell)):
        raise ValueError("FOLLOW_RUN_DEFAULTS_CONFIG_INVALID")
    return {
        "buy_target": buy,
        "sell_target": sell,
        "fee_coin_principal_mojos": str(fee_principal),
        "xch_reserve_mojos": str(xch_reserve),
        "cat_reserve_atoms": str(cat_reserve),
        "maximum_trade_xch_mojos": str(xch_trade),
        "maximum_trade_cat_atoms": str(cat_trade),
        "wallet_identity": observed["identity"],
        "configuration_sha256": before,
    }
