"""Controller-review regressions for Task 6 wallet identity Fix Round 2."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest

import api_server
import mutation_gate
import wallet
import wallet_sage


def _utc(offset_seconds: int = 0) -> str:
    value = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _identity() -> dict:
    return {
        "success": True,
        "backend": "sage",
        "name": "Expected Wallet",
        "fingerprint": 123456,
        "network_id": "mainnet",
        "kind": "bls",
        "has_secrets": True,
        "observed_at_utc": _utc(),
    }


def _configure_runtime(monkeypatch, adapter):
    mutation_gate.shutdown_runtime()
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", adapter)
    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "123456")
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_NAME", "Expected Wallet", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 10, raising=False
    )
    api_server.initialize_mutation_runtime(
        start_heartbeat=False,
        acquire_lease=False,
    )
    monkeypatch.setattr(mutation_gate, "enter_wallet_mutation", lambda operation: "p")
    monkeypatch.setattr(mutation_gate, "exit_wallet_mutation", lambda permit: True)
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda permit, operation: (
            mutation_gate.current_runtime().wallet_identity_binding,
            adapter,
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "wallet_mutation_permit_journal_authority",
        lambda permit, operation: {"owner_run_id": "wallet-identity-round2"},
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda binding, snapshot, operation: {"allowed": True},
    )


def test_owner_effect_uses_acquired_adapter_when_identity_read_swaps_all_globals(
    monkeypatch,
):
    """A self-consistent adapter-global swap cannot redirect an authorized effect."""

    events = []
    evil = SimpleNamespace(
        create_offer=lambda *args, **kwargs: events.append("evil_effect")
        or {"success": True, "source": "evil"},
    )

    def original_identity():
        events.append("identity")
        monkeypatch.setattr(wallet, "_wallet_adapter", evil)
        monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", evil)
        return _identity()

    original = SimpleNamespace(
        get_wallet_identity=original_identity,
        create_offer=lambda *args, **kwargs: events.append("original_effect")
        or {"success": True, "source": "original"},
    )
    _configure_runtime(monkeypatch, original)

    try:
        result = wallet.create_offer({1: -1})
    finally:
        mutation_gate.shutdown_runtime()

    assert result == {
        "success": True,
        "source": "original",
        "_catalyst_effect_attempted": True,
    }
    assert events == ["identity", "original_effect"]


def test_owner_rejects_self_consistent_adapter_swap_before_boundary(monkeypatch):
    """Replacing both facade globals cannot replace the acquired authority."""

    effects = []
    original = SimpleNamespace(
        get_wallet_identity=_identity,
        create_offer=lambda *args, **kwargs: effects.append("original")
        or {"success": True},
    )
    evil = SimpleNamespace(
        get_wallet_identity=_identity,
        create_offer=lambda *args, **kwargs: effects.append("evil")
        or {"success": True},
    )
    _configure_runtime(monkeypatch, original)
    monkeypatch.setattr(wallet, "_wallet_adapter", evil)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", evil)

    try:
        result = wallet.create_offer({1: -1})
    finally:
        mutation_gate.shutdown_runtime()

    assert result["success"] is False
    assert result["reason"] == "WALLET_IDENTITY_BINDING_INVALID"
    assert effects == []


def test_owner_effect_keeps_acquired_adapter_during_threaded_identity_race(
    monkeypatch,
):
    """A concurrent global swap cannot redirect a locally captured effect."""

    events = []
    evil = SimpleNamespace(
        create_offer=lambda *args, **kwargs: events.append("evil_effect")
        or {"success": True, "source": "evil"},
    )

    def race_swap():
        monkeypatch.setattr(wallet, "_wallet_adapter", evil)
        monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", evil)

    def original_identity():
        worker = threading.Thread(target=race_swap)
        worker.start()
        worker.join()
        events.append("identity")
        return _identity()

    original = SimpleNamespace(
        get_wallet_identity=original_identity,
        create_offer=lambda *args, **kwargs: events.append("original_effect")
        or {"success": True, "source": "original"},
    )
    _configure_runtime(monkeypatch, original)

    try:
        result = wallet.create_offer({1: -1})
    finally:
        mutation_gate.shutdown_runtime()

    assert result == {
        "success": True,
        "source": "original",
        "_catalyst_effect_attempted": True,
    }
    assert events == ["identity", "original_effect"]


def test_nested_identity_callback_keeps_acquired_adapter(monkeypatch):
    """Compound adapter callbacks revalidate and retain the acquired object."""

    events = []
    identity_reads = 0
    evil = SimpleNamespace()

    def original_identity():
        nonlocal identity_reads
        identity_reads += 1
        events.append(f"identity:{identity_reads}")
        if identity_reads == 2:
            monkeypatch.setattr(wallet, "_wallet_adapter", evil)
            monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", evil)
        return _identity()

    def split_effect(*args, _identity_recheck=None, **kwargs):
        events.append("nested:before")
        _identity_recheck("split")
        events.append("original_effect")
        return {"success": True, "source": "original"}

    original = SimpleNamespace(
        get_wallet_identity=original_identity,
        split_coins_bulk=split_effect,
    )
    _configure_runtime(monkeypatch, original)

    try:
        result = wallet.split_coins_bulk(1, 2, 3)
    finally:
        mutation_gate.shutdown_runtime()

    assert result == {
        "success": True,
        "source": "original",
        "_catalyst_effect_attempted": True,
    }
    assert events == [
        "identity:1",
        "nested:before",
        "identity:2",
        "original_effect",
    ]


def test_runtime_reinit_cannot_replace_adapter_until_shutdown(monkeypatch):
    """Adapter switching requires full runtime shutdown and a new authority."""

    original = SimpleNamespace(get_wallet_identity=_identity)
    evil = SimpleNamespace(get_wallet_identity=_identity)
    _configure_runtime(monkeypatch, original)
    runtime = mutation_gate.current_runtime()

    with pytest.raises(RuntimeError):
        mutation_gate.initialize(
            wallet_fingerprint_hash=runtime.wallet_fingerprint_hash,
            network=runtime.network,
            start_heartbeat=False,
            acquire_lease=False,
            wallet_identity_binding=runtime.wallet_identity_binding,
            wallet_adapter_authority=evil,
        )

    mutation_gate.shutdown_runtime()
    replacement = mutation_gate.initialize(
        wallet_fingerprint_hash=runtime.wallet_fingerprint_hash,
        network=runtime.network,
        start_heartbeat=False,
        acquire_lease=False,
        wallet_identity_binding=runtime.wallet_identity_binding,
        wallet_adapter_authority=evil,
    )
    try:
        assert replacement.require_wallet_adapter_authority(evil, "test") is evil
    finally:
        mutation_gate.shutdown_runtime()


def test_worker_effect_keeps_installed_adapter_during_identity_read_swap(monkeypatch):
    """A delegated effect retains the installed adapter after facade globals move."""

    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Expected Wallet",
        fingerprint=123456,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=_utc(-2),
        maximum_age_seconds=10,
    )
    delegated = {
        "wallet_fingerprint_hash": mutation_gate.wallet_fingerprint_hash(123456),
        "network": "mainnet",
        "bound_at_utc": binding.bound_at_utc,
        "binding": binding,
        "binding_digest": mutation_gate.wallet_identity_binding_digest(binding),
    }
    events = []
    evil = SimpleNamespace(
        create_offer=lambda *args, **kwargs: events.append("evil_effect")
        or {"success": True, "source": "evil"}
    )

    def original_identity():
        events.append("identity")
        monkeypatch.setattr(wallet, "_wallet_adapter", evil)
        monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", evil)
        return _identity()

    original = SimpleNamespace(
        get_wallet_identity=original_identity,
        create_offer=lambda *args, **kwargs: events.append("original_effect")
        or {"success": True, "source": "original"},
    )
    monkeypatch.setattr(wallet, "_wallet_adapter", original)
    monkeypatch.setattr(wallet, "_WALLET_ADAPTER_AUTHORITY", original)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(
        mutation_gate, "worker_identity_lease_binding", lambda: dict(delegated)
    )

    def require_adapter(candidate, operation):
        if candidate is not original:
            raise mutation_gate.MutationBlocked(
                "WALLET_IDENTITY_BINDING_INVALID", operation
            )
        return original

    monkeypatch.setattr(
        mutation_gate, "worker_wallet_adapter_authority", require_adapter
    )
    monkeypatch.setattr(mutation_gate, "enter_wallet_mutation", lambda operation: "p")
    monkeypatch.setattr(mutation_gate, "exit_wallet_mutation", lambda permit: True)
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda permit, operation: (binding, original),
    )
    monkeypatch.setattr(
        mutation_gate,
        "wallet_mutation_permit_journal_authority",
        lambda permit, operation: {"owner_run_id": "wallet-identity-round2"},
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda binding, snapshot, operation: {"allowed": True},
    )

    assert wallet.create_offer({1: -1}) == {
        "success": True,
        "source": "original",
        "_catalyst_effect_attempted": True,
    }
    assert events == ["identity", "original_effect"]


@pytest.mark.parametrize(
    "rpc_result",
    [
        {"success": True, "status": "rejected"},
        {"success": True, "status": "denied"},
        {"success": True, "status": "cancelled"},
        {"success": True, "status": "unknown"},
        {"success": True, "status": "malformed"},
        {"success": True, "reason": "denied"},
        {"success": True, "failure": False},
        {"success": True, "rejected": False},
        {"success": True, "denied": False},
        {"success": True, "cancelled": False},
        {"success": True, "unknown": False},
        {"success": True, "malformed": False},
        {"success": 1},
        {"success": "true"},
    ],
)
def test_change_address_rejects_every_non_exact_success_schema(monkeypatch, rpc_result):
    """Only the exact documented success object can authorize UI success."""

    monkeypatch.setattr(
        wallet_sage,
        "_validate_address_for_active_network",
        lambda address, context: address,
    )
    monkeypatch.setattr(wallet_sage, "rpc", lambda *args, **kwargs: rpc_result)

    assert wallet_sage.set_change_address("xch1safe", 123456) == {
        "success": False,
        "error": "set_change_address_failed",
    }
