"""Canonical fee consent binds economic choices, not transient market guidance."""

import copy
import importlib.util

import pytest


def _scope():
    return {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 736588221,
        "wallet_id": 2,
        "xch_wallet_id": 1,
        "asset_id": "b8" * 32,
        "ticker": "MZ_XCH",
        "session_id": "d" * 64,
        "campaign_id": None,
    }


def _plan():
    return {
        "target_seconds": 300,
        "coin_multiplier": "1.0",
        "headroom_pct": "10",
        "liquidity_mode": "two_sided",
        "reserve_floors_mojos": {"xch": 10_000, "cat": 100},
        "campaign_revision": None,
        "cancellation_policy": "protected_no_prep",
        "outputs": [
            {"asset": "xch", "purpose": "replacement", "tier_rank": 0,
             "amount_mojos": 1_000, "ordinal": 0},
            {"asset": "cat", "purpose": "replacement", "tier_rank": 0,
             "amount_mojos": 100, "ordinal": 0},
        ],
    }


def _contract(scope=None, plan=None):
    assert importlib.util.find_spec("coin_prep_fee_approval"), (
        "canonical fee consent service is missing"
    )
    import coin_prep_fee_approval as service
    return service.canonical_fee_contract(scope or _scope(), plan or _plan())


def test_canonical_contract_is_order_independent_and_decimal_exact():
    first = _contract()
    plan = _plan()
    plan["outputs"].reverse()
    plan["coin_multiplier"] = "1.0000"
    plan["headroom_pct"] = "10.000"
    second = _contract(dict(reversed(list(_scope().items()))), plan)
    assert first["scope_sha256"] == second["scope_sha256"]
    assert first["plan_sha256"] == second["plan_sha256"]
    assert first["plan"]["coin_multiplier"] == "1"
    assert first["plan"]["outputs"][0]["asset"] == "cat"
    assert len(first["scope_sha256"]) == 64


def test_signed_zero_headroom_is_the_same_economic_plan():
    positive = _plan()
    positive["headroom_pct"] = "0.00"
    negative = _plan()
    negative["headroom_pct"] = "-0.00"
    assert _contract(plan=positive)["plan_sha256"] == _contract(plan=negative)["plan_sha256"]
    assert _contract(plan=negative)["plan"]["headroom_pct"] == "0"


@pytest.mark.parametrize("field,value", [
    ("wallet_fingerprint", 3702373391), ("wallet_id", 3),
    ("xch_wallet_id", 4), ("network", "testnet11"),
    ("wallet_type", "chia"), ("asset_id", "a" * 64),
    ("ticker", "DBX_XCH"), ("session_id", "e" * 64),
])
def test_wallet_network_asset_and_session_change_scope(field, value):
    baseline = _contract()
    scope = _scope()
    scope[field] = value
    assert _contract(scope)["scope_sha256"] != baseline["scope_sha256"]


@pytest.mark.parametrize("field,value", [
    ("target_seconds", 600), ("coin_multiplier", "2"),
    ("headroom_pct", "5"), ("liquidity_mode", "buy_only"),
    ("reserve_floors_mojos", {"xch": 10_001, "cat": 100}),
    ("campaign_revision", 2),
])
def test_economic_choice_changes_plan_not_wallet_scope(field, value):
    baseline = _contract()
    plan = _plan()
    plan[field] = value
    changed = _contract(plan=plan)
    assert changed["scope_sha256"] == baseline["scope_sha256"]
    assert changed["plan_sha256"] != baseline["plan_sha256"]


def test_exact_output_amount_changes_plan():
    baseline = _contract()
    plan = _plan()
    plan["outputs"][0]["amount_mojos"] = 1_001
    assert _contract(plan=plan)["plan_sha256"] != baseline["plan_sha256"]


@pytest.mark.parametrize("path,value", [
    (("wallet_fingerprint",), True), (("wallet_id",), 2.0),
    (("asset_id",), "B8" * 32), (("session_id",), "client-session"),
    (("campaign_id",), "bad"), (("wallet_type",), "unknown"),
])
def test_invalid_scope_cannot_become_consent_authority(path, value):
    scope = _scope()
    scope[path[0]] = value
    with pytest.raises(ValueError):
        _contract(scope)


@pytest.mark.parametrize("field,value", [
    ("target_seconds", True), ("coin_multiplier", "NaN"),
    ("coin_multiplier", "0.4"), ("coin_multiplier", "3.1"),
    ("headroom_pct", "Infinity"), ("liquidity_mode", "anything"),
    ("campaign_revision", 1.0), ("cancellation_policy", "spend_protection_on_prep"),
    ("reserve_floors_mojos", {"xch": True, "cat": 100}),
])
def test_invalid_economic_choices_cannot_be_approved(field, value):
    plan = _plan()
    plan[field] = value
    with pytest.raises(ValueError):
        _contract(plan=plan)


@pytest.mark.parametrize("field,value", [
    ("amount_mojos", 1.0), ("amount_mojos", True),
    ("amount_mojos", 0), ("amount_mojos", 2**63),
    ("ordinal", True), ("asset", "other"),
])
def test_invalid_output_atoms_are_rejected(field, value):
    plan = _plan()
    plan["outputs"][0][field] = value
    with pytest.raises(ValueError):
        _contract(plan=plan)


def test_duplicate_output_identity_is_not_a_valid_plan():
    plan = _plan()
    plan["outputs"].append(copy.deepcopy(plan["outputs"][0]))
    with pytest.raises(ValueError):
        _contract(plan=plan)


def test_transient_quotes_and_selected_coins_cannot_enter_economic_contract():
    plan = _plan()
    for field, value in [("fee_estimate", 10), ("selected_coin_ids", ["1" * 64])]:
        with pytest.raises(ValueError):
            _contract(plan={**plan, field: value})


def test_campaign_scope_uses_campaign_not_refresh_session():
    scope = _scope()
    scope["campaign_id"] = "c" * 64
    scope["session_id"] = None
    baseline = _contract(scope)
    assert baseline["scope"]["campaign_id"] == "c" * 64
    with pytest.raises(ValueError):
        _contract({**scope, "session_id": "d" * 64})


def test_fresh_bootstrap_revision_zero_is_bound_without_inventing_a_revision():
    scope = {**_scope(), "campaign_id": "c" * 64, "session_id": None}
    plan = {**_plan(), "campaign_revision": 0}
    initial = _contract(scope, plan)
    assert initial["plan"]["campaign_revision"] == 0
    assert _contract(scope, {**plan, "campaign_revision": 1})["plan_sha256"] != initial["plan_sha256"]
