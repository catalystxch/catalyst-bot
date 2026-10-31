"""Cancellation-only renewal may use a newly configured fee pool.

The earlier preparation targets remain frozen. Changing the fee pool cannot
resize those targets, but it must not strand live offers when prepared fee
coins have been exhausted.
"""

from decimal import Decimal

from coin_prep_fee_execution import (
    cancellation_recovery_configuration_matches,
    encode_execution_configuration,
)
from coin_prep_fee_runtime import _CONTEXT_KEYS


def _configuration(**changes):
    values = {key: None for key in _CONTEXT_KEYS}
    values.update(
        {
            "FEE_PREP_COUNT": 0,
            "FEE_COIN_SIZE_XCH": Decimal("0"),
            "SAGE_FINGERPRINT": "736588221",
            "CAT_ASSET_ID": "ab" * 32,
            "network": "mainnet",
        }
    )
    values.update(changes)
    return encode_execution_configuration(values)


def test_cancellation_only_recovery_accepts_exact_new_fee_pool_settings():
    frozen = _configuration()
    current = _configuration(FEE_PREP_COUNT=50, FEE_COIN_SIZE_XCH=Decimal("0.001"))
    assert cancellation_recovery_configuration_matches(current, frozen)


def test_cancellation_only_recovery_still_rejects_wallet_and_asset_drift():
    frozen = _configuration()
    assert not cancellation_recovery_configuration_matches(
        _configuration(SAGE_FINGERPRINT="3702373391"), frozen
    )
    assert not cancellation_recovery_configuration_matches(
        _configuration(CAT_ASSET_ID="cd" * 32), frozen
    )
