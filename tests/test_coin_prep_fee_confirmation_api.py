"""HTTP/native confirmation shares strict payload, current context and safety gates."""

import json

import pytest

import api_server
import app_bridge
import mutation_gate
from fee_approval_test_utils import (
    _counts, confirmation as _confirmation,
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


@pytest.fixture
def local_api(confirmation, monkeypatch):
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(api_server, "_is_rate_limited", lambda _path: False)
    monkeypatch.setattr(api_server.mutation_gate, "enter_mutation", lambda _operation: object())
    monkeypatch.setattr(api_server.mutation_gate, "exit_mutation", lambda _permit: None)
    return api_server.app.test_client(), {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}


def _body(state):
    return {"preview_id": state["preview"]["preview_id"],
            "maximum_fee_mojos": 80, "cancellation_reserve_mojos": 20}


def _http(local_api, body, **kwargs):
    client, headers = local_api
    return client.post("/api/coin-prep/fee-approval", json=body,
                       headers=kwargs.get("headers", headers),
                       environ_base={"REMOTE_ADDR": kwargs.get("remote", "127.0.0.1")})


def _native(body):
    method = getattr(app_bridge.AppBridge(), "approve_coin_prep_fees", None)
    assert callable(method), "native fee-confirmation surface is missing"
    return method(body)


def test_http_confirmation_records_consent_without_launching_prep(local_api, confirmation):
    response = _http(local_api, _body(confirmation))
    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is True
    assert result["dispatch_authorized"] is False
    assert result["total_fee_mojos"] == "80"
    assert _counts() == {"fee_approvals": 1, "coin_prep_fee_consents": 1,
                         "approved_fee_reservations": 0, "coin_prep_operations": 0, "wallet_effect_claims": 0}


def test_http_and_native_duplicate_confirmations_share_one_durable_consent(local_api, confirmation):
    first = _http(local_api, _body(confirmation)).get_json()
    second = _native(_body(confirmation))
    assert first["success"] is second["success"] is True
    assert second["approval_id"] == first["approval_id"]
    assert second["idempotent"] is True
    assert second["dispatch_authorized"] is False
    assert _counts()["fee_approvals"] == 1


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("mutation", [{"maximum_fee_mojos": True}, {"maximum_fee_mojos": 1.5},
                                      {"maximum_fee_mojos": -1}, {"maximum_fee_mojos": "080"},
                                      {"maximum_fee_mojos": "8e1"}, {"maximum_fee_mojos": " 80"},
                                      {"maximum_fee_mojos": "9223372036854775808"},
                                      {"scope_sha256": "a" * 64}, {"plan": {}}, {"cost": 1}])
def test_malformed_or_client_authority_fields_are_rejected_before_wallet_reads(
        local_api, confirmation, native, mutation):
    body = {**_body(confirmation), **mutation}
    result = _native(body) if native else _http(local_api, body).get_json()
    assert result["success"] is False
    assert result["reason"] == "FEE_APPROVAL_REQUEST_INVALID"
    assert confirmation["reads"] == []
    assert not any(_counts().values())


@pytest.mark.parametrize("body", [None, [], "confirmation", {}, {"preview_id": "a" * 64}])
def test_nonobject_or_incomplete_http_request_cannot_record_consent(local_api, confirmation, body):
    response = _http(local_api, body)
    assert response.status_code == 400
    assert response.get_json()["reason"] == "FEE_APPROVAL_REQUEST_INVALID"
    assert confirmation["reads"] == []
    assert not any(_counts().values())


def test_canonical_atomic_strings_preserve_exact_values_at_json_boundary(local_api, confirmation):
    response = _http(local_api, {**_body(confirmation), "maximum_fee_mojos": "80",
                                 "cancellation_reserve_mojos": "20"})
    assert response.status_code == 200
    assert response.get_json()["total_fee_mojos"] == "80"


@pytest.mark.parametrize("surface", ["http", "native"])
def test_fee_accounting_readback_is_lossless_beyond_javascript_integer_precision(
        local_api, confirmation, surface):
    import database
    from fee_approval_test_utils import _coin

    maximum = 9007199254740993
    stored = database.get_coin_prep_fee_preview(confirmation["preview"]["preview_id"])
    quote = {**json.loads(stored["quote_json"]), "fee_funding_mojos": maximum}
    preview = database.store_coin_prep_fee_preview(
        scope_json=stored["scope_json"], plan_json=stored["plan_json"],
        scope_sha256=stored["scope_sha256"], plan_sha256=stored["plan_sha256"],
        request_options_json=stored["request_options_json"], quote_json=json.dumps(quote),
        observed_at=1000, expires_at=1060,
    )
    confirmation["xch"] = [_coin(1, str(112_000_000_000 + maximum))]
    body = {"preview_id": preview["preview_id"], "maximum_fee_mojos": str(maximum),
            "cancellation_reserve_mojos": "20"}
    if surface == "http":
        response = _http(local_api, body)
        assert response.status_code == 200
        result = response.get_json()
    else:
        result = _native(body)
        assert result["success"] is True
    assert result["total_fee_mojos"] == "9007199254740993"
    assert result["remaining_preparation_fee_mojos"] == "9007199254740973"
    assert result["held_fee_mojos"] == "0"
    assert all(type(value) is str for key, value in result.items() if key.endswith("_mojos"))
    assert database.get_fee_approval(result["approval_id"])["total_fee_mojos"] == maximum


@pytest.mark.parametrize("headers,remote,status", [({}, "127.0.0.1", 401),
                                                    ({}, "192.0.2.1", 403)])
def test_http_auth_and_loopback_guards_precede_confirmation(local_api, confirmation, headers, remote, status):
    assert _http(local_api, _body(confirmation), headers=headers, remote=remote).status_code == status
    assert confirmation["reads"] == []
    assert not any(_counts().values())


@pytest.mark.parametrize("native", [False, True])
def test_blocked_mutation_owner_cannot_record_consent(local_api, confirmation, monkeypatch, native):
    def blocked(operation):
        raise mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)

    monkeypatch.setattr(api_server.mutation_gate, "enter_mutation", blocked)
    result = _native(_body(confirmation)) if native else _http(local_api, _body(confirmation)).get_json()
    assert result["success"] is False
    assert result["reason"] == "LEASE_OWNED_BY_OTHER"
    assert confirmation["reads"] == []
    assert not any(_counts().values())


def test_changed_plan_has_actionable_http_pause_and_no_partial_consent(local_api, confirmation):
    confirmation["live_price"] = "0.02"
    response = _http(local_api, _body(confirmation))
    assert response.status_code == 409
    assert response.get_json()["reason"] == "FEE_APPROVAL_STALE"
    assert not any(_counts().values())
