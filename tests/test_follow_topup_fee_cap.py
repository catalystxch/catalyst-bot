"""Follow transaction fee caps cover runtime coin top-up transactions."""

from types import SimpleNamespace
from importlib import import_module

import pytest


def _manager(binding):
    manager_module = import_module("coin_manager")
    manager = object.__new__(manager_module.CoinManager)
    manager._topup_follow_fee_binding = binding
    return manager


def _patch_active_binding(monkeypatch, manager, *, run_id="a" * 64):
    import database
    import follow_run_coordinator
    import confidence_override

    identity = {
        "network": "mainnet",
        "wallet_fingerprint": 7,
        "asset_id": "b" * 64,
    }
    policy = SimpleNamespace(
        digest="c" * 64,
        maximum_fee_mojos_per_tx=123,
        network="mainnet",
        wallet_fingerprint="7",
        asset_id="b" * 64,
    )
    state = {
        "state": "running",
        "run_id": run_id,
        "policy_digest": policy.digest,
        "configuration_sha256": "d" * 64,
    }
    monkeypatch.setattr(
        follow_run_coordinator.FollowRunCoordinator,
        "read_state",
        lambda _self: state,
    )
    monkeypatch.setattr(database, "get_active_follow_run_policy", lambda: policy)
    monkeypatch.setattr(database, "get_follow_run_identity", lambda _run: identity)
    monkeypatch.setattr(
        confidence_override,
        "current_configuration_digest",
        lambda: state["configuration_sha256"],
    )
    monkeypatch.setattr(
        confidence_override,
        "current_scope",
        lambda: {
            "follow_run_id": run_id,
            "configuration_sha256": state["configuration_sha256"],
            "identity": identity,
        },
    )
    manager._topup_follow_fee_binding = {
        "run_id": run_id,
        "policy_digest": policy.digest,
        "configuration_sha256": state["configuration_sha256"],
        "identity": identity,
    }


def test_runtime_topup_fee_uses_verified_follow_per_transaction_cap(monkeypatch):
    manager = _manager(None)
    _patch_active_binding(monkeypatch, manager)
    manager_module = import_module("coin_manager")
    monkeypatch.setattr(manager_module, "get_effective_transaction_fee_mojos", lambda: 456)
    monkeypatch.setattr(manager_module, "get_transaction_fee_mode", lambda: "auto")
    assert manager._tx_fee_mojos() == 123


def test_runtime_topup_fails_closed_without_binding_during_active_follow(monkeypatch):
    manager = _manager(None)
    _patch_active_binding(monkeypatch, manager)
    manager._topup_follow_fee_binding = None
    with pytest.raises(ValueError, match="FOLLOW_TOPUP_FEE_BINDING_REQUIRED"):
        manager._verified_topup_follow_fee_cap()


def test_runtime_topup_rejects_mismatched_coordinator_configuration(monkeypatch):
    manager = _manager(None)
    _patch_active_binding(monkeypatch, manager)
    import confidence_override

    monkeypatch.setattr(confidence_override, "current_configuration_digest", lambda: "e" * 64)
    with pytest.raises(ValueError, match="FOLLOW_TOPUP_FEE_AUTHORITY_MISMATCH"):
        manager._verified_topup_follow_fee_cap()
