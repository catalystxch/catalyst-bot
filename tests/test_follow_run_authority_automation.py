from decimal import Decimal
from types import SimpleNamespace

import pytest

from follow_run_authority_automation import _validate_proposal


def _policy(**changes):
    terms = {
        "network": "mainnet",
        "wallet_fingerprint": "123",
        "asset_id": "a" * 64,
        "buy_target": 2,
        "sell_target": 3,
        "price_anchor": Decimal("0.01"),
        "price_min": Decimal("0.009"),
        "price_max": Decimal("0.011"),
        "maximum_fee_mojos_per_tx": 100,
        "maximum_trade_xch_mojos": 500,
        "maximum_trade_cat_atoms": 600,
    }
    terms.update(changes)
    return SimpleNamespace(**terms)


def _proposal(**changes):
    proposal = {
        "dispatch_authorized": False,
        "identity": {
            "network": "mainnet",
            "wallet_fingerprint": 123,
            "asset_id": "a" * 64,
        },
        "buy_limit": 2,
        "sell_limit": 3,
        "replacement_count_gate_passed": True,
        "buy_slots_arithmetic_fit": 2,
        "sell_slots_arithmetic_fit": 3,
        "maximum_trade_xch_mojos": 450,
        "maximum_trade_cat_atoms": 550,
        "shutdown_funding": {"ready": True, "quoted_fee_mojos": 100},
    }
    proposal.update(changes)
    return proposal


def test_fresh_proposal_accepts_exact_policy_principal_and_fee_cap():
    _validate_proposal(_policy(), _proposal())


@pytest.mark.parametrize(
    ("policy_changes", "proposal_changes", "reason"),
    [
        (
            {},
            {"maximum_trade_xch_mojos": 501},
            "FOLLOW_TRADING_PRINCIPAL_EXCEEDS_APPROVAL",
        ),
        (
            {},
            {"maximum_trade_cat_atoms": 601},
            "FOLLOW_TRADING_PRINCIPAL_EXCEEDS_APPROVAL",
        ),
        (
            {},
            {"shutdown_funding": {"ready": True, "quoted_fee_mojos": 0}},
            "FOLLOW_SHUTDOWN_FUNDING_REQUIRED",
        ),
        ({}, {"buy_slots_arithmetic_fit": 1}, "FOLLOW_SLOT_INVENTORY_SHORT"),
        (
            {},
            {
                "identity": {
                    "network": "mainnet",
                    "wallet_fingerprint": 123,
                    "asset_id": "b" * 64,
                }
            },
            "FOLLOW_RUN_AUTHORITY_CHANGED",
        ),
    ],
)
def test_fresh_proposal_rejects_policy_or_proof_expansion(
    policy_changes, proposal_changes, reason
):
    with pytest.raises(ValueError, match=reason):
        _validate_proposal(_policy(**policy_changes), _proposal(**proposal_changes))


def test_unready_shutdown_funding_keeps_existing_reason():
    with pytest.raises(ValueError, match="FOLLOW_SHUTDOWN_FEE_CAP_INSUFFICIENT"):
        _validate_proposal(
            _policy(),
            _proposal(
                shutdown_funding={
                    "ready": False,
                    "reason": "FOLLOW_SHUTDOWN_FEE_CAP_INSUFFICIENT",
                    "quoted_fee_mojos": 101,
                }
            ),
        )


def test_recommendation_above_per_transaction_cap_does_not_block_authority():
    _validate_proposal(
        _policy(maximum_fee_mojos_per_tx=100),
        _proposal(shutdown_funding={"ready": True, "quoted_fee_mojos": 101}),
    )
