"""Prep fee limits require exact Follow session, policy and approval binding."""

from decimal import Decimal

import pytest

from follow_prep_fee_authority import verified_prep_fee_cap
from follow_run_policy import FollowRunPolicy


def _policy():
    return FollowRunPolicy(
        wallet_fingerprint="12345",
        network="mainnet",
        asset_id="a" * 64,
        buy_target=2,
        sell_target=2,
        price_anchor=Decimal("0.000001"),
        price_min=Decimal("0.0000008"),
        price_max=Decimal("0.0000012"),
        maximum_fee_mojos_per_tx=50,
        fee_coin_principal_mojos=100,
        xch_reserve_mojos=0,
        cat_reserve_atoms=0,
        maximum_trade_xch_mojos=1000,
        maximum_trade_cat_atoms=1000,
    )


def _binding():
    policy = _policy()
    session_id = "1" * 64
    approval_id = "2" * 64
    prep_session_id = "3" * 64
    configuration_sha256 = "4" * 64
    return {
        "policy": policy,
        "coordinator_state": {
            "session_id": session_id,
            "run_id": None,
            "policy_digest": policy.digest,
            "configuration_sha256": configuration_sha256,
            "state": "prep_pending",
            "fee_approval_id": approval_id,
            "fee_approval_session_id": prep_session_id,
        },
        "current_configuration_sha256": configuration_sha256,
        "approved_snapshot": {
            "identity": {
                "wallet_fingerprint": 12345,
                "network": "mainnet",
                "asset_id": "a" * 64,
            },
            "scope": {"session_id": prep_session_id},
            "approval": {
                "approval_id": approval_id,
                "total_fee_mojos": 1000,
            },
        },
        "requested_approval_id": approval_id,
        "run_session_id": session_id,
    }


def test_returns_per_transaction_policy_max_only_for_exact_pre_run_binding():
    assert verified_prep_fee_cap(**_binding()) == 50


@pytest.mark.parametrize(
    "field,value",
    [
        ("current_configuration_sha256", "5" * 64),
        ("run_session_id", "6" * 64),
        ("requested_approval_id", "7" * 64),
        ("approved_snapshot", {"identity": {"wallet_fingerprint": "other"}}),
    ],
)
def test_rejects_mismatched_binding(field, value):
    binding = _binding()
    binding[field] = value
    with pytest.raises(ValueError, match="FOLLOW_RUN_PREP_FEE_BINDING_REQUIRED"):
        verified_prep_fee_cap(**binding)


def test_rejects_legacy_approval_without_run_binding():
    binding = _binding()
    binding["coordinator_state"].pop("fee_approval_id")
    with pytest.raises(ValueError, match="FOLLOW_RUN_PREP_FEE_BINDING_REQUIRED"):
        verified_prep_fee_cap(**binding)


def test_rejects_prep_approval_from_another_session():
    binding = _binding()
    binding["approved_snapshot"]["scope"]["session_id"] = "9" * 64
    with pytest.raises(ValueError, match="FOLLOW_RUN_PREP_FEE_BINDING_REQUIRED"):
        verified_prep_fee_cap(**binding)


def test_rejects_cumulative_approval_cap_as_per_transaction_authority():
    binding = _binding()
    binding["policy"] = None
    with pytest.raises(ValueError, match="FOLLOW_RUN_PREP_FEE_BINDING_REQUIRED"):
        verified_prep_fee_cap(**binding)
