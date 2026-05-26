from decimal import Decimal

from amount_utils import (
    cat_display_amount_to_mojos_ceil,
    format_cat_display_amount,
    format_signed_cat_display_amount,
    round_cat_display_amount_up_to_mojo,
)


def test_cat_display_amount_rounds_up_to_nearest_mojo():
    assert cat_display_amount_to_mojos_ceil(Decimal("0.0021"), 3) == 3
    assert round_cat_display_amount_up_to_mojo(Decimal("0.0021"), 3) == Decimal("0.003")


def test_format_cat_display_amount_preserves_low_decimal_fraction():
    assert format_cat_display_amount(Decimal("0.002"), 3) == "0.002"
    assert format_cat_display_amount(Decimal("0.0020"), 3) == "0.002"
    assert format_cat_display_amount(Decimal("2.000"), 3) == "2"


def test_format_signed_cat_display_amount_preserves_sign_and_fraction():
    assert format_signed_cat_display_amount(Decimal("0.002"), 3) == "+0.002"
    assert format_signed_cat_display_amount(Decimal("-0.002"), 3) == "-0.002"
    assert format_signed_cat_display_amount(Decimal("0"), 3) == "0"
