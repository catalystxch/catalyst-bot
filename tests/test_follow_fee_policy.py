"""Per-transaction fee selection stays within the approved run maximum."""

import pytest

from follow_fee_policy import guard_explicit_run_fee, select_transaction_fee


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


def test_explicit_fee_guard_accepts_only_fee_at_or_below_verified_cap():
    assert guard_explicit_run_fee(
        fee_mojos=0,
        verified_maximum_fee_per_transaction_mojos=100,
    ) == {
        "within_cap": True,
        "raise_cap_needed": False,
        "reason": None,
    }
    assert guard_explicit_run_fee(
        fee_mojos=100,
        verified_maximum_fee_per_transaction_mojos=100,
    ) == {
        "within_cap": True,
        "raise_cap_needed": False,
        "reason": None,
    }
    assert guard_explicit_run_fee(
        fee_mojos=101,
        verified_maximum_fee_per_transaction_mojos=100,
    ) == {
        "within_cap": False,
        "raise_cap_needed": True,
        "reason": "FEE_CAP_BELOW_EXPLICIT_TRANSACTION_FEE",
    }


def test_explicit_fee_guard_fails_closed_when_verified_cap_is_missing():
    with pytest.raises(ValueError, match="verified_fee_cap_required"):
        guard_explicit_run_fee(
            fee_mojos=1,
            verified_maximum_fee_per_transaction_mojos=None,
        )


@pytest.mark.parametrize("fee", [-1, 1.0, True])
def test_explicit_fee_guard_rejects_invalid_fee_amount(fee):
    with pytest.raises(ValueError, match="invalid_fee_policy_amount"):
        guard_explicit_run_fee(
            fee_mojos=fee,
            verified_maximum_fee_per_transaction_mojos=10,
        )
