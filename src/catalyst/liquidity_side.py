"""Effective side permissions for offer creation."""


def bootstrap_side_enabled(settings: object, side: str) -> bool:
    """Require the current mode and its derived flag to allow this side."""

    mode = getattr(settings, "LIQUIDITY_MODE", None)
    if side not in {"buy", "sell"} or mode not in {
        "two_sided",
        "buy_only",
        "sell_only",
    }:
        return False
    if mode == "buy_only" and side != "buy":
        return False
    if mode == "sell_only" and side != "sell":
        return False
    return (
        getattr(settings, "ENABLE_BUY" if side == "buy" else "ENABLE_SELL", None)
        is True
    )
