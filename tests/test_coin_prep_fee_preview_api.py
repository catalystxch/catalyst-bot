"""Preview surfaces expose staged evidence, never fee consent or dispatch."""

from importlib import import_module
import json
from types import SimpleNamespace

import pytest

import api_server
import app_bridge
import mutation_gate
import fee_approval_test_utils as utils
from fee_staged_preview_utils import prepare_unsigned_wallet


@pytest.fixture
def local_preview(tmp_path, monkeypatch):
    reads = utils.live_reads(tmp_path, monkeypatch)
    state = next(reads)
    utils.economic_reads(state, monkeypatch)
    service = import_module("coin_prep_fee_approval")
    pricing = import_module("coin_prep_fee_pricing")
    monkeypatch.setattr(import_module("coin_prep_fee_runtime"), "cfg", state["config"])
    monkeypatch.setattr(service, "_now", lambda: 1000)
    monkeypatch.setattr(pricing, "_now", lambda: 1000)

    def quote(cost, target_seconds):
        return {"available": True, "fee_mojos": 20, "source": "coinset", "cost": cost,
                "target_seconds": target_seconds, "observed_at": 1000, "expires_at": 1060}

    monkeypatch.setattr(service, "quote_fee", quote)
    monkeypatch.setattr(pricing, "quote_fee", quote)
    prepare_unsigned_wallet(state, monkeypatch)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(api_server, "_is_rate_limited", lambda _path: False)
    monkeypatch.setattr(api_server.mutation_gate, "enter_mutation", lambda _operation: object())
    monkeypatch.setattr(api_server.mutation_gate, "exit_mutation", lambda _permit: None)
    state["client"] = api_server.app.test_client()
    yield state
    try:
        next(reads)
    except StopIteration:
        pass


def request_preview(state, surface, body):
    if surface == "native":
        method = getattr(app_bridge.AppBridge(), "preview_coin_prep_fees", None)
        assert callable(method), "native staged fee preview is missing"
        return method(body)
    response = state["client"].post(
        "/api/coin-prep/fee-preview", json=body,
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
    )
    assert response.is_json, "HTTP staged fee preview is missing"
    return response.get_json()


@pytest.mark.parametrize("surface", ["http", "native"])
def test_preview_exposes_lossless_stages_without_consent_or_dispatch(local_preview, surface):
    result = request_preview(local_preview, surface, {})
    assert result["success"] is True and result["available"] is True
    assert result["dispatch_authorized"] is False
    assert result["target_seconds"] == 300
    assert result["estimated_total_fee_mojos"] == "80"
    assert result["fee_coin_principal_mojos"] == "2000000000"
    assert len(result["stages"]) == 4
    assert result["stages"][0]["cost_kind"] == "exact_unsigned"
    assert result["stages"][1]["cost_kind"] == "projected"
    assert all(s["quote"]["fee_mojos"] == "20" for s in result["stages"])
    assert not any(utils._counts().values())


@pytest.mark.parametrize("surface", ["http", "native"])
@pytest.mark.parametrize("body", [None, [], {"cost": 1}, {"scope": {}}, {"stages": []}])
def test_invalid_preview_choices_cannot_read_wallet_or_grant_authority(local_preview, surface, body):
    result = request_preview(local_preview, surface, body)
    assert result["success"] is False
    assert result["reason"] == "FEE_PREP_OPTIONS_INVALID"
    assert result["dispatch_authorized"] is False
    assert local_preview["reads"] == [] and not local_preview.get("builds")
    assert not any(utils._counts().values())


@pytest.mark.parametrize("surface", ["http", "native"])
def test_unavailable_projected_guidance_is_actionable_without_preview_consent(local_preview, surface, monkeypatch):
    monkeypatch.setattr(import_module("coin_prep_fee_approval"), "quote_fee",
                        lambda *_a, **_k: {"available": False})
    result = request_preview(local_preview, surface, {})
    assert result["success"] is False and result["available"] is False
    assert result["reason"] == "FEE_ESTIMATE_UNAVAILABLE"
    assert result.get("preview_id") is None
    assert not any(utils._counts().values())


@pytest.mark.parametrize("surface", ["http", "native"])
def test_owner_block_precedes_wallet_preview(local_preview, surface, monkeypatch):
    def blocked(operation):
        raise mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)

    monkeypatch.setattr(api_server.mutation_gate, "enter_mutation", blocked)
    result = request_preview(local_preview, surface, {})
    assert result["success"] is False and result["reason"] == "LEASE_OWNED_BY_OTHER"
    assert local_preview["reads"] == [] and not local_preview.get("builds")


@pytest.mark.parametrize("headers,remote,status", [({}, "127.0.0.1", 401), ({}, "192.0.2.1", 403)])
def test_auth_and_loopback_precede_preview(local_preview, headers, remote, status):
    response = local_preview["client"].post(
        "/api/coin-prep/fee-preview", json={}, headers=headers,
        environ_base={"REMOTE_ADDR": remote},
    )
    assert response.status_code == status
    assert local_preview["reads"] == [] and not local_preview.get("builds")


@pytest.mark.parametrize("surface", ["http", "native"])
@pytest.mark.parametrize("stage", ["exact", "projected"])
@pytest.mark.parametrize("failure,reason,observed", [
    ("unsynced", "fee_provider_unsynced", 1000),
    ("malformed", "invalid_fee_response", 1000),
    ("throttled", "fee_provider_rate_limited", None),
    ("transport", "fee_provider_unavailable", None),
    ("disabled", "fee_provider_disabled", None),
])
def test_provider_failure_reasons_survive_real_quotes_to_public_preview(
    local_preview, monkeypatch, surface, stage, failure, reason, observed,
):
    fees = import_module("tx_fees")
    estimation = import_module("fee_estimation")
    fees._COINSET_FEE_CACHE.clear()
    fees._SUGGESTED_FEE_CACHE.clear()
    monkeypatch.setattr(fees, "time", SimpleNamespace(time=lambda: 1000, sleep=lambda _: None))
    monkeypatch.setattr(estimation, "time", SimpleNamespace(time=lambda: 1000))
    monkeypatch.setattr(fees.cfg, "COINSET_ENABLED", failure != "disabled", raising=False)
    monkeypatch.setattr(fees, "get_wallet_fee_environment", lambda: {"supports_auto_estimate": True})
    monkeypatch.setattr(fees, "_full_node_rpc", lambda *_a, **_k: {
        "success": True, "estimates": [0], "full_node_synced": False})

    def post(*_a, **_k):
        if failure == "transport":
            raise RuntimeError("https://example.invalid/?api_key=secret-test-key")
        return SimpleNamespace(status_code=429 if failure == "throttled" else 200,
            json=lambda: {"success": True, **({"estimates": [0], "full_node_synced": False}
                                            if failure == "unsynced" else {})})
    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr(import_module("coin_prep_fee_approval"), "quote_fee", estimation.quote_fee)
    if stage == "exact":
        monkeypatch.setattr(import_module("coin_prep_fee_pricing"), "quote_fee", estimation.quote_fee)
    result = request_preview(local_preview, surface, {})
    assert result["available"] is False and result["dispatch_authorized"] is False
    assert result["reason"] == "FEE_ESTIMATE_UNAVAILABLE"
    assert result.get("provider_failures") == [
        {"source": "full_node_rpc", "reason": "fee_provider_unsynced", "observed_at": 1000},
        {"source": "coinset", "reason": reason, "observed_at": observed},
    ]
    assert "secret-test-key" not in json.dumps(result)
    assert result.get("preview_id") is None
    assert not any(utils._counts().values())
