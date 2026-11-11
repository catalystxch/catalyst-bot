"""Restricted startup opens review only; it never grants trading authority."""

import importlib
import json
import sys
from types import SimpleNamespace

import pytest


def _candidate():
    return {"operation": {"operation_id": "split:exact", "source_coin_ids_json": json.dumps(["a" * 64])},
            "latch": {"generation": 7}}


def _runtime(monkeypatch, *, acquired=True, owned=True, changed=False):
    import api_server
    import mutation_gate

    calls = []
    candidate = _candidate()
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage", name="Test wallet", fingerprint=736588221,
        network_id="mainnet", kind="private", has_secrets=True,
        bound_at_utc="2026-11-11T12:00:00Z", maximum_age_seconds=60,
    )
    runtime = SimpleNamespace(
        acquire_coin_prep_rbf_successor=lambda **kw: calls.append(("adopt", kw)) or {"acquired": acquired},
        read_only_status=lambda: SimpleNamespace(to_dict=lambda: {
            "allowed": False, "reason_code": "COIN_PREP_RECOVERY_REQUIRED",
            "lease": {"owned_by_this_run": owned}}),
        register_stop_handler=lambda _handler: calls.append("handler"),
        start_heartbeat=lambda: calls.append("heartbeat") or True,
    )
    candidates = iter([candidate, None] if changed else [candidate, candidate])
    monkeypatch.setattr(api_server, "_exact_coin_prep_rbf_startup_candidate", lambda: next(candidates))
    monkeypatch.setattr(api_server, "_coin_prep_rbf_recovery_active", False)
    monkeypatch.setattr(api_server, "_coin_prep_rbf_recovery_scope", None)
    monkeypatch.setattr(api_server, "_mutation_runtime", None)
    monkeypatch.setattr(api_server, "_mutation_runtime_db_path", None)
    monkeypatch.setattr(api_server, "_stability_startup_status", None)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_configured_mutation_binding", lambda: ("wallet", "mainnet"))
    monkeypatch.setattr(api_server, "_configured_wallet_identity_binding", lambda _: binding)
    monkeypatch.setattr(api_server, "get_wallet_adapter_authority", object)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)

    def initialize(**kw):
        assert kw["acquire_lease"] is False
        assert kw["start_heartbeat"] is False
        return runtime

    monkeypatch.setattr(mutation_gate, "initialize", initialize)
    monkeypatch.setattr(mutation_gate, "shutdown_runtime", lambda **kw: calls.append(("shutdown", kw)))
    return api_server, runtime, calls


def test_admission_adopts_only_exact_operation_then_starts_heartbeat(monkeypatch):
    api_server, runtime, calls = _runtime(monkeypatch)
    assert api_server.activate_coin_prep_rbf_restricted_startup({
        "allowed": False, "reason_code": "COIN_PREP_RECOVERY_REQUIRED"}) is True
    assert calls == [("adopt", {"operation_id": "split:exact", "expected_latch_generation": 7}),
                     "handler", "heartbeat"]
    assert api_server._mutation_runtime is runtime
    assert api_server._coin_prep_rbf_recovery_active is True


@pytest.mark.parametrize("options", [{"acquired": False}, {"owned": False}, {"changed": True}])
def test_failed_admission_preserves_fence_and_releases_only_acquired_lease(monkeypatch, options):
    api_server, _, calls = _runtime(monkeypatch, **options)
    assert api_server.activate_coin_prep_rbf_restricted_startup({
        "allowed": False, "reason_code": "COIN_PREP_RECOVERY_REQUIRED"}) is False
    assert "heartbeat" not in calls
    assert calls[-1] == ("shutdown", {"release_owned_lease": options.get("acquired", True)})
    assert api_server._coin_prep_rbf_recovery_active is False


def test_recovery_routes_fence_every_write_and_bridge(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "_coin_prep_rbf_recovery_active", True)
    for method, path in [("POST", "/api/bot/start"), ("POST", "/api/coin-prep/fee-approval"),
                         ("GET", "/api/coins"), ("HEAD", "/")]:
        with api_server.app.test_request_context(path, method=method,
                environ_base={"REMOTE_ADDR": "127.0.0.1"}):
            response = api_server.enforce_local_runtime_guard()
        assert response[1] == 423
    with api_server.app.test_request_context(
        "/api/safety/coin-prep-recovery-submit", method="POST",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        response = api_server.enforce_local_runtime_guard()
    assert response[1] == 401  # Allowed route still requires local token.
    original_platform = sys.platform
    monkeypatch.setattr(sys, "platform", "linux")
    sys.modules.pop("desktop_app", None)
    desktop = importlib.import_module("desktop_app")
    monkeypatch.setattr(sys, "platform", original_platform)
    assert desktop._create_desktop_bridge() is None
    monkeypatch.setattr(api_server, "initialize_mutation_runtime", lambda: pytest.fail("normal runtime started"))
    desktop._start_owned_runtime_services()


def test_recovery_scope_rejects_lost_lease_and_privacy_bypass(monkeypatch):
    import api_server
    import mutation_gate

    monkeypatch.setattr(api_server, "_coin_prep_rbf_recovery_active", True)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    with api_server.app.test_request_context("/api/safety/coin-prep-recovery-scope",
            environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        assert api_server.api_coin_prep_recovery_scope()[1] == 423
        assert api_server.enforce_local_runtime_guard()[1] == 401


def test_candidate_reads_only_exact_latched_dispatched_split(monkeypatch):
    import api_server
    import database
    import mutation_gate

    operation_id = "coin-prep:" + "a" * 64
    wallet_hash = mutation_gate.wallet_fingerprint_hash(12345)
    latch = {"state": "tripped", "reason_code": "COIN_PREP_RECOVERY_REQUIRED",
             "generation": 4, "wallet_fingerprint_hash": wallet_hash, "network": "mainnet",
             "blocking_operation_ids_json": json.dumps(sorted([operation_id, "wallet-effect:claim"]))}
    operation = {"operation_id": operation_id, "outcome": "SUBMITTED_UNKNOWN",
                 "operation_kind": "split", "purpose": "fee_reserve",
                 "effect_adapter_operation": operation_id, "effect_dispatch_token": "dispatch",
                 "effect_claim_token": "claim", "effect_fee_coin_ids_json": "[]",
                 "wallet_identity_json": json.dumps({"fingerprint": 12345, "network_id": "mainnet"}),
                 "source_coin_ids_json": json.dumps(["b" * 64]),
                 "target_contract_json": json.dumps({"wallet_type": "xch", "outputs": [{}] * 5})}
    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server, "_configured_mutation_binding", lambda: (wallet_hash, "mainnet"))
    monkeypatch.setattr(database, "get_runtime_safety_latch", lambda: latch)
    monkeypatch.setattr(database, "get_coin_prep_rbf_preview_authority", lambda _: {
        "operation": operation, "latch": dict(latch)})
    monkeypatch.setattr(database, "get_recoverable_coin_prep_operations",
                        lambda: pytest.fail("inventory read would mutate recovery state"))
    assert api_server._exact_coin_prep_rbf_startup_candidate() is not None
    operation["effect_dispatch_token"] = None
    assert api_server._exact_coin_prep_rbf_startup_candidate() is None
    operation["effect_dispatch_token"] = "dispatch"
    latch["blocking_operation_ids_json"] = json.dumps([operation_id, "wallet-effect:claim", "other"])
    assert api_server._exact_coin_prep_rbf_startup_candidate() is None


def test_recovery_bootstrap_binds_cookie_before_reading_private_scope(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "_coin_prep_rbf_recovery_active", True)
    monkeypatch.setattr(api_server, "_coin_prep_rbf_owned_review_snapshot",
                        lambda: pytest.fail("bootstrap must not inspect private scope"))
    with api_server.app.test_request_context("/?bootstrap=" + api_server._LOCAL_API_BOOTSTRAP_TOKEN):
        response = api_server.serve_gui()
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert "Set-Cookie" in response.headers


def test_preview_uses_only_server_selected_pending_transaction(monkeypatch):
    import api_server
    import wallet
    import coin_prep_rbf_review_service

    snapshot = {"operation_id": "coin-prep:" + "a" * 64,
                "original_input_coin_ids": ["b" * 64], "dispatch_authorized": False}
    tx = "c" * 64
    monkeypatch.setattr(api_server, "_coin_prep_rbf_owned_review_snapshot", lambda: dict(snapshot))
    monkeypatch.setattr(wallet, "get_pending_transactions_strict", lambda: [
        {"transaction_id": tx, "spent": [{"coin_id": "0x" + "b" * 64}]}])
    calls = []
    monkeypatch.setattr(coin_prep_rbf_review_service, "prepare_coin_prep_rbf_review",
                        lambda op, original: calls.append((op, original)) or {
                            "available": False, "reason": "test_refusal"})
    with api_server.app.test_request_context("/api/safety/coin-prep-recovery-preview", method="POST", json={}):
        assert api_server.api_coin_prep_recovery_preview()[1] == 409
    assert calls == [(snapshot["operation_id"], tx)]
    with api_server.app.test_request_context("/api/safety/coin-prep-recovery-preview", method="POST",
                                           json={"transaction_id": tx, "fee_mojos": 1}):
        assert api_server.api_coin_prep_recovery_preview()[1] == 400
    assert len(calls) == 1
    monkeypatch.setattr(wallet, "get_pending_transactions_strict", lambda: [
        {"transaction_id": tx, "spent": [{"coin_id": "b" * 64}]},
        {"transaction_id": "d" * 64, "spent": [{"coin_id": "b" * 64}]}])
    with api_server.app.test_request_context("/api/safety/coin-prep-recovery-preview", method="POST", json={}):
        assert api_server.api_coin_prep_recovery_preview()[1] == 409
    assert len(calls) == 1
