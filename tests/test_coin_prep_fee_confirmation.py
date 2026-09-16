"""Public confirmation must derive authority and current funding on the server."""

import json

import pytest

import coin_prep_fee_approval as service
import coin_prep_fee_runtime as runtime
import database
import wallet
import wallet_sage
from fee_approval_test_utils import (
    _coin, _counts, confirmation as _confirmation,
    economic_reads as _economic_reads, live_reads as _live_reads,
)


@pytest.fixture
def live_reads(tmp_path, monkeypatch):
    yield from _live_reads(tmp_path, monkeypatch)


@pytest.fixture
def economic_reads(live_reads, monkeypatch):
    return _economic_reads(live_reads, monkeypatch)


@pytest.fixture
def confirmation(economic_reads, monkeypatch):
    return _confirmation(economic_reads, monkeypatch)


def _confirm(state, **overrides):
    import coin_prep_fee_approval as service

    confirm = getattr(service, "approve_coin_prep_fees", None)
    assert callable(confirm), "server-owned runtime fee confirmation is missing"
    args = {"preview_id": state["preview"]["preview_id"],
            "maximum_fee_mojos": 80, "cancellation_reserve_mojos": 20}
    args.update(overrides)
    return confirm(**args)




def test_confirmation_uses_persisted_scope_and_current_wallet_economics(confirmation):
    result = _confirm(confirmation)
    assert result["total_fee_mojos"] == 80
    assert result["cancellation_reserve_mojos"] == 20
    assert result["remaining_preparation_fee_mojos"] == 60
    assert result["dispatch_authorized"] is False
    assert result["preview_id"] == confirmation["preview"]["preview_id"]
    assert _counts() == {"fee_approvals": 1, "coin_prep_fee_consents": 1,
                         "approved_fee_reservations": 0, "coin_prep_operations": 0, "wallet_effect_claims": 0}


@pytest.mark.parametrize("field,value", [("wallet_fingerprint", 3702373391),
                                          ("asset", "37" * 32), ("price", "0.02"), ("reserve", 1)])
def test_changed_wallet_asset_price_or_reserve_cannot_confirm_old_plan(confirmation, field, value):
    if field == "wallet_fingerprint":
        confirmation["identity"]["fingerprint"] = value
        confirmation["config"].SAGE_FINGERPRINT = str(value)
    elif field == "asset":
        confirmation["config"].CAT_ASSET_ID = value
        confirmation["cats"]["cats"][0]["asset_id"] = value
        # This is a valid selectable view of a *different* current CAT, not a
        # transport failure from the fixture's original asset allowlist.
        original = wallet_sage._sage_post

        def different_asset(endpoint, payload, *, timeout):
            if endpoint == "get_coins" and payload["asset_id"] == value:
                payload = {**payload, "asset_id": "36" * 32}
            return original(endpoint, payload, timeout=timeout)

        confirmation["monkeypatch"].setattr(wallet_sage, "_sage_post", different_asset)
    elif field == "price":
        confirmation["live_price"] = value
    else:
        confirmation["config"].XCH_RESERVE = value
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _confirm(confirmation)
    assert not any(_counts().values())


def test_current_funding_not_old_preview_balance_limits_confirmation(confirmation):
    confirmation["xch"] = [_coin(1, str(112_000_000_079))]
    with pytest.raises(ValueError, match="FEE_FUNDING_INSUFFICIENT"):
        _confirm(confirmation)
    assert not any(_counts().values())


def test_ended_campaign_cannot_be_confirmed_as_a_standalone_session(confirmation):
    old = database.get_coin_prep_fee_preview(confirmation["preview"]["preview_id"])
    scope = {**json.loads(old["scope_json"]), "session_id": None, "campaign_id": "c" * 64}
    plan = {**json.loads(old["plan_json"]), "campaign_revision": 0}
    contract = service.canonical_fee_contract(scope, plan)
    new = database.store_coin_prep_fee_preview(
        scope_sha256=contract["scope_sha256"], plan_sha256=contract["plan_sha256"],
        scope_json=contract["scope_json"], plan_json=contract["plan_json"],
        request_options_json=old["request_options_json"], quote_json=old["quote_json"],
        observed_at=1000, expires_at=1060,
    )
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _confirm(confirmation, preview_id=new["preview_id"])
    assert not any(_counts().values())


def test_current_principal_shortfall_cannot_be_hidden_by_preview_funding(confirmation):
    confirmation["cat"] = [_coin(10001, "10999")]
    with pytest.raises(ValueError, match="FEE_FUNDING_INSUFFICIENT"):
        _confirm(confirmation)
    assert not any(_counts().values())


def test_prior_commitments_are_subtracted_before_checking_current_funding(confirmation):
    preview = confirmation["preview"]
    prior = database.create_fee_approval(
        scope_sha256=preview["scope_sha256"], plan_sha256=preview["plan_sha256"],
        total_fee_mojos=80, cancellation_reserve_mojos=20)
    database.reserve_approved_fee(
        approval_id=prior["approval_id"], scope_sha256=prior["scope_sha256"],
        plan_sha256=prior["plan_sha256"], operation_id="1" * 64, fee_mojos=50, cancellation=True)
    confirmation["xch"] = [_coin(1, str(112_000_000_040))]
    result = _confirm(confirmation, maximum_fee_mojos=90)
    assert result["held_fee_mojos"] == 50
    assert result["remaining_fee_mojos"] == 40
    assert result["version"] == 2


def test_preview_expiring_during_wallet_reads_cannot_be_confirmed(confirmation, monkeypatch):
    original = runtime.read_fee_economic_snapshot

    def slow_read(options):
        result = original(options)
        confirmation["now"] = 1060
        return result

    monkeypatch.setattr(runtime, "read_fee_economic_snapshot", slow_read)
    with pytest.raises(ValueError, match="FEE_PREVIEW_STALE"):
        _confirm(confirmation)
    assert not any(_counts().values())


def test_preview_expiring_while_waiting_for_database_lock_cannot_be_confirmed(confirmation, monkeypatch):
    original = database._stability_connection

    class DelayedConnection:
        def __init__(self):
            self.connection = original()

        def execute(self, sql, *args):
            result = self.connection.execute(sql, *args)
            if sql == "BEGIN IMMEDIATE":
                # Deterministically model the clock advancing during lock wait.
                confirmation["now"] = 1060
            return result

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(database, "_stability_connection", DelayedConnection)
    with pytest.raises(ValueError, match="FEE_PREVIEW_STALE"):
        _confirm(confirmation)
    assert not any(_counts().values())


def test_duplicate_confirmation_returns_durable_accounting_not_dispatch_permission(confirmation):
    first = _confirm(confirmation)
    confirmation["now"] = 2000
    database.close_connection()
    second = _confirm(confirmation)
    assert second["approval_id"] == first["approval_id"]
    assert second["idempotent"] is True
    assert second["dispatch_authorized"] is False
    assert _counts()["fee_approvals"] == 1


def test_duplicate_confirmation_does_not_require_pending_inputs_to_be_selectable(confirmation):
    first = _confirm(confirmation)
    database.reserve_approved_fee(
        approval_id=first["approval_id"], scope_sha256=first["scope_sha256"],
        plan_sha256=first["plan_sha256"], operation_id="1" * 64, fee_mojos=30, cancellation=False)
    confirmation["xch"] = []
    confirmation["cat"] = []
    second = _confirm(confirmation)
    assert second["approval_id"] == first["approval_id"]
    assert second["idempotent"] is True
    assert second["held_fee_mojos"] == 30
    assert second["remaining_fee_mojos"] == 50
    assert second["dispatch_authorized"] is False
    assert _counts()["fee_approvals"] == 1


@pytest.mark.parametrize("overrides", [{"maximum_fee_mojos": True}, {"maximum_fee_mojos": 1.5},
                                      {"maximum_fee_mojos": -1}, {"cancellation_reserve_mojos": "20"},
                                      {"preview_id": "not-a-server-preview"}])
def test_bad_confirmation_is_rejected_before_wallet_reads(confirmation, overrides):
    with pytest.raises(ValueError):
        _confirm(confirmation, **overrides)
    assert confirmation["reads"] == []
    assert not any(_counts().values())


def test_server_preview_id_does_not_accept_client_economic_authority(confirmation):
    with pytest.raises(TypeError):
        _confirm(confirmation, scope_sha256="a" * 64)
    assert not any(_counts().values())


def test_stored_request_options_are_used_not_later_client_defaults(confirmation):
    persisted = database.get_coin_prep_fee_preview(confirmation["preview"]["preview_id"])
    assert json.loads(persisted["request_options_json"]) == {"coin_multiplier": "1", "target_seconds": 300}
    result = _confirm(confirmation)
    context = database.get_coin_prep_fee_approval_context(result["approval_id"])
    assert context["request_options_json"] == persisted["request_options_json"]
