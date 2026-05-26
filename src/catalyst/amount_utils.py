"""Small Decimal helpers for wallet display-unit and mojo conversions."""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING


def _cat_scale(decimals: int) -> Decimal:
    return Decimal(10) ** Decimal(int(decimals))


def cat_display_amount_to_mojos_ceil(amount, decimals: int) -> int:
    """Convert a CAT display amount to mojos, rounding any dust up.

    Coin prep sizes are capacity floors: if a target sell coin needs 2.1 CAT
    mojos, preparing only 2 mojos can make the later offer too small. Round up
    to the next integer mojo instead of rounding to whole display CATs.
    """
    value = Decimal(str(amount))
    if value <= 0:
        return 0
    return int((value * _cat_scale(decimals)).to_integral_value(rounding=ROUND_CEILING))


def cat_mojos_to_display_amount(mojos: int, decimals: int) -> Decimal:
    """Convert integer CAT mojos to a display-unit Decimal."""
    return Decimal(int(mojos)) / _cat_scale(decimals)


def round_cat_display_amount_up_to_mojo(amount, decimals: int) -> Decimal:
    """Round a CAT display amount up to the nearest representable mojo."""
    mojos = cat_display_amount_to_mojos_ceil(amount, decimals)
    return cat_mojos_to_display_amount(mojos, decimals)


def format_cat_display_amount(amount, decimals: int) -> str:
    """Format CAT display amounts without hiding sub-1-CAT values as zero."""
    places = max(0, min(int(decimals), 12))
    value = Decimal(str(amount))
    text = f"{value:,.{places}f}".rstrip("0").rstrip(".")
    return text or "0"


def format_signed_cat_display_amount(amount, decimals: int) -> str:
    """Format a CAT amount with an explicit plus sign for positive values."""
    value = Decimal(str(amount))
    if value > 0:
        return f"+{format_cat_display_amount(value, decimals)}"
    return format_cat_display_amount(value, decimals)
