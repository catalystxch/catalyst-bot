from decimal import Decimal

import api_server  # noqa: F401 - initializes the route module import order
from blueprints.smart_defaults import _smart_price_rails_for_book


def test_smart_rails_cover_both_sides_of_thin_book():
    low, high = _smart_price_rails_for_book(
        Decimal("0.0000092544"),
        Decimal("0.0001689582"),
        Decimal("0.00005025"),
        Decimal("0.00017945"),
    )
    assert Decimal(str(low)) <= Decimal("0.00005025")
    assert Decimal(str(high)) >= Decimal("0.00017945") * Decimal("1.15")


def test_smart_rails_do_not_follow_inverted_book():
    assert _smart_price_rails_for_book(0.00001, 0.00016, 0.00018, 0.00017) == (
        0.00001,
        0.00016,
    )
