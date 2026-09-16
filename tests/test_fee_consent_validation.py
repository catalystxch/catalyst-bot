"""Consent readback validates trusted current economics without refreshing holds."""

import copy

import pytest

import coin_prep_fee_approval as service
import database


@pytest.fixture
def consent(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "consent.db"))
    database.init_database()
    scope = {
        "network": "mainnet", "wallet_type": "sage", "wallet_fingerprint": 736588221,
        "wallet_id": 2, "xch_wallet_id": 1, "asset_id": "b8" * 32, "ticker": "MZ_XCH",
        "session_id": "d" * 64, "campaign_id": None,
    }
    plan = {
        "target_seconds": 300, "coin_multiplier": "1", "headroom_pct": "0",
        "liquidity_mode": "two_sided", "reserve_floors_mojos": {"xch": 0, "cat": 0},
        "campaign_revision": None, "cancellation_policy": "protected_no_prep",
        "outputs": [{"asset": "cat", "purpose": "replacement", "tier_rank": 0,
                     "amount_mojos": 100, "ordinal": 0}],
    }
    contract = service.canonical_fee_contract(scope, plan)
    preview = database.store_coin_prep_fee_preview(
        scope_sha256=contract["scope_sha256"], plan_sha256=contract["plan_sha256"],
        scope_json=contract["scope_json"], plan_json=contract["plan_json"],
        request_options_json='{"coin_multiplier":"1"}',
        quote_json='{"available":true,"estimated_preparation_fee_mojos":30,'
                   '"estimated_cancellation_fee_mojos":10,"fee_funding_mojos":100}',
        observed_at=100, expires_at=160,
    )
    approval = database.approve_coin_prep_fee_preview(
        preview_id=preview["preview_id"], scope_sha256=contract["scope_sha256"],
        plan_sha256=contract["plan_sha256"], maximum_fee_mojos=80,
        cancellation_reserve_mojos=20, now=101,
    )
    yield scope, plan, approval
    database.close_connection()


def _validate(consent, **overrides):
    assert callable(getattr(service, "validate_fee_consent", None)), (
        "trusted current-economic consent validation is missing"
    )
    scope, plan, approval = consent
    args = {"approval_id": approval["approval_id"], "scope": scope, "economic_plan": plan}
    args.update(overrides)
    return service.validate_fee_consent(**args)


def test_estimate_expiry_does_not_expire_consent_or_refund_holds(consent, monkeypatch):
    _, _, approval = consent
    database.reserve_approved_fee(
        approval_id=approval["approval_id"], scope_sha256=approval["scope_sha256"],
        plan_sha256=approval["plan_sha256"], operation_id="1" * 64,
        fee_mojos=30, cancellation=False,
    )
    monkeypatch.setattr(service, "_now", lambda: 1000)
    database.close_connection()
    database.init_database()
    result = _validate(consent)
    assert result["held_fee_mojos"] == 30
    assert result["remaining_fee_mojos"] == 50
    assert result["remaining_preparation_fee_mojos"] == 30
    assert result["dispatch_authorized"] is False
    assert database.get_connection().execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 1
    assert database.get_connection().execute("SELECT COUNT(*) FROM approved_fee_reservations").fetchone()[0] == 1


@pytest.mark.parametrize("field,value", [
    ("wallet_fingerprint", 3702373391), ("network", "testnet11"),
    ("wallet_id", 3), ("asset_id", "a" * 64), ("session_id", "e" * 64),
])
def test_changed_current_identity_rejects_consent(consent, field, value):
    scope = {**consent[0], field: value}
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _validate(consent, scope=scope)


@pytest.mark.parametrize("field,value", [
    ("target_seconds", 600), ("coin_multiplier", "2"),
    ("reserve_floors_mojos", {"xch": 100, "cat": 0}),
])
def test_changed_current_economics_rejects_consent(consent, field, value):
    plan = {**consent[1], field: value}
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _validate(consent, economic_plan=plan)


def test_changed_output_rejects_consent(consent):
    plan = copy.deepcopy(consent[1])
    plan["outputs"][0]["amount_mojos"] = 101
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _validate(consent, economic_plan=plan)


def test_arbitrary_ledger_approval_is_not_operator_consent(consent):
    approval = consent[2]
    generic = database.create_fee_approval(
        scope_sha256=approval["scope_sha256"], plan_sha256=approval["plan_sha256"],
        total_fee_mojos=90, cancellation_reserve_mojos=20,
    )
    with pytest.raises(ValueError, match="FEE_APPROVAL_REQUIRED"):
        _validate(consent, approval_id=generic["approval_id"])


def test_superseded_consent_cannot_authorize_new_work(consent):
    approval = consent[2]
    database.create_fee_approval(
        scope_sha256=approval["scope_sha256"], plan_sha256=approval["plan_sha256"],
        total_fee_mojos=90, cancellation_reserve_mojos=20,
    )
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _validate(consent)


def test_missing_consent_is_structured_approval_required(consent):
    with pytest.raises(ValueError, match="FEE_APPROVAL_REQUIRED"):
        _validate(consent, approval_id="f" * 64)
