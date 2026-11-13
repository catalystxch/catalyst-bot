"""Approved Follow anchor fallback is bounded and guard-scoped."""

from decimal import Decimal

from follow_price_policy import approved_anchor_fallback
from follow_run_policy import FollowRunPolicy


def _policy():
    return FollowRunPolicy(
        wallet_fingerprint="fingerprint",
        network="mainnet",
        asset_id="a" * 64,
        buy_target=2,
        sell_target=2,
        price_anchor=Decimal("0.000001"),
        price_min=Decimal("0.0000008"),
        price_max=Decimal("0.0000012"),
        maximum_fee_mojos_per_tx=10,
        fee_coin_principal_mojos=100,
        xch_reserve_mojos=0,
        cat_reserve_atoms=0,
        maximum_trade_xch_mojos=1000,
        maximum_trade_cat_atoms=1000,
    )


def _fallback(**overrides):
    arguments = {
        "policy": _policy(),
        "live_price_available": False,
        "run_active": True,
        "wallet_identity_matches": True,
        "red_guard_allows": True,
    }
    arguments.update(overrides)
    return approved_anchor_fallback(**arguments)


def test_uses_approved_anchor_indefinitely_with_persistent_warning_when_sources_absent():
    first = _fallback()
    later = _fallback()

    assert first == later
    assert first["use_anchor"] is True
    assert first["price"] == Decimal("0.000001")
    assert first["source"] == "approved_follow_anchor"
    assert first["warning_active"] is True
    assert first["warning_code"] == "APPROVED_PRICE_ANCHOR_IN_USE"


def test_does_not_substitute_anchor_when_live_price_is_available():
    result = _fallback(live_price_available=True)

    assert result["use_anchor"] is False
    assert result["warning_active"] is False


def test_does_not_use_anchor_when_run_or_wallet_identity_is_not_verified():
    assert _fallback(run_active=False)["use_anchor"] is False
    assert _fallback(wallet_identity_matches=False)["use_anchor"] is False


def test_does_not_bypass_existing_red_guard():
    result = _fallback(red_guard_allows=False)

    assert result["use_anchor"] is False
    assert result["reason"] == "RED_GUARD_BLOCKED"


def test_rejects_non_follow_policy_as_anchor_authority():
    result = _fallback(policy=None)

    assert result["use_anchor"] is False
    assert result["reason"] == "FOLLOW_RUN_POLICY_REQUIRED"
