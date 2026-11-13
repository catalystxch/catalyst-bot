"""Per-transaction fee selection stays within the approved run maximum."""

import pytest

from follow_fee_policy import select_transaction_fee


def test_selects_fresh_recommendation_when_it_is_within_the_cap():
    decision = select_transaction_fee(
        recommended_fee_mojos=25,
        maximum_fee_per_transaction_mojos=100,
    )

    assert decision == {
        "fee_mojos": 25,
        "raise_cap_needed": False,
        "reason": None,
    }


def test_caps_fee_and_flags_when_recommendation_exceeds_the_cap():
    decision = select_transaction_fee(
        recommended_fee_mojos=150,
        maximum_fee_per_transaction_mojos=100,
    )

    assert decision == {
        "fee_mojos": 100,
        "raise_cap_needed": True,
        "reason": "FEE_CAP_BELOW_RECOMMENDATION",
    }


@pytest.mark.parametrize(
    "recommendation,maximum",
    [(0, 10), (-1, 10), (1.0, 10), (True, 10), (1, 0), (1, -1), (1, True)],
)
def test_rejects_nonpositive_or_noninteger_mojo_amounts(recommendation, maximum):
    with pytest.raises(ValueError, match="invalid_fee_policy_amount"):
        select_transaction_fee(
            recommended_fee_mojos=recommendation,
            maximum_fee_per_transaction_mojos=maximum,
        )


def test_does_not_claim_to_authorize_wallet_effects():
    decision = select_transaction_fee(
        recommended_fee_mojos=25,
        maximum_fee_per_transaction_mojos=100,
    )

    assert "dispatch_authorized" not in decision
    assert "authorization" not in decision
