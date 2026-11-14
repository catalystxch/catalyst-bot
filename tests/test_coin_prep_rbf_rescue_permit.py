"""A coin-prep RBF rescue has one exact effect permit under a closed latch."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import database
import mutation_gate
import wallet


NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
OPERATION = "coin-prep:" + "3" * 64
CLAIM = "4" * 64
ATTEMPT = "5" * 64
UNSIGNED_SHA256 = "6" * 64


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


@pytest.fixture
def owned_coin_prep_latch(tmp_path, monkeypatch):
    """Use a throwaway DB and a pinned owner adapter; never contact Sage."""

    original_path = database.DB_PATH
    original_initialized_path = database._db_initialized_path
    database.close_connection()
    database.DB_PATH = str(tmp_path / "rbf-rescue-permit.db")
    database._db_initialized_path = ""
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: _timestamp(NOW))
    try:
        database.init_database()
        adapter = object()
        binding = mutation_gate.WalletIdentityBinding(
            backend="sage",
            name="Permit Wallet",
            fingerprint=736588221,
            network_id="mainnet",
            kind="bls",
            has_secrets=True,
            bound_at_utc=_timestamp(NOW - timedelta(seconds=1)),
            maximum_age_seconds=30,
        )
        gate = mutation_gate.MutationGate(
            run_id="rbf-permit-owner",
            owner_pid=111,
            owner_host="test-host",
            wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
                binding.fingerprint
            ),
            network="mainnet",
            lease_seconds=60,
            clock=lambda: NOW,
            pid_liveness=lambda _pid, _host: False,
            wallet_identity_binding=binding,
            wallet_adapter_authority=adapter,
        )
        assert gate.acquire()["acquired"] is True
        database.trip_runtime_safety_latch(
            reason_code="COIN_PREP_RECOVERY_REQUIRED",
            blocking_operation_ids=sorted([OPERATION, f"wallet-effect:{CLAIM}"]),
            wallet_fingerprint_hash=gate.wallet_fingerprint_hash,
            network="mainnet",
            tripped_at=NOW,
        )
        status = gate.status()
        assert status.allowed is False
        assert status.owner_is_this_run is True
        monkeypatch.setattr(mutation_gate, "_runtime", gate)
        yield gate, binding, adapter, status.latch_generation
    finally:
        mutation_gate.shutdown_runtime()
        database.close_connection()
        database.DB_PATH = original_path
        database._db_initialized_path = original_initialized_path


def _request(generation: int) -> dict:
    return {
        "attempt_id": ATTEMPT,
        "operation_id": OPERATION,
        "expected_latch_generation": generation,
        "unsigned_sha256": UNSIGNED_SHA256,
    }


def _authorize(owned, request):
    gate, _binding, _adapter, generation = owned
    latch = database.get_runtime_safety_latch()
    if latch["generation"] != generation:
        raise ValueError("RBF latch generation changed")
    if json.loads(latch["blocking_operation_ids_json"]) != sorted(
        [OPERATION, f"wallet-effect:{CLAIM}"]
    ):
        raise ValueError("RBF blocker set changed")
    if request["attempt_id"] != ATTEMPT:
        raise ValueError("wrong RBF attempt")
    if request["operation_id"] != OPERATION:
        raise ValueError("wrong RBF operation")
    if request["unsigned_sha256"] != UNSIGNED_SHA256:
        raise ValueError("wrong sealed unsigned bundle")
    return {
        "attempt_id": ATTEMPT,
        "operation_id": OPERATION,
        "unsigned_sha256": UNSIGNED_SHA256,
        "wallet_fingerprint_hash": gate.wallet_fingerprint_hash,
        "network": "mainnet",
        "latch_generation": generation,
        "lease_version": gate._lease_version,
        "lease_acquired_at": gate._lease_acquired_at,
    }


def test_exact_rbf_permit_leaves_generic_mutations_blocked(
    owned_coin_prep_latch, monkeypatch
):
    owned = owned_coin_prep_latch
    gate, binding, adapter, generation = owned
    monkeypatch.setattr(
        database,
        "authorize_coin_prep_rbf_rescue_target",
        lambda **request: _authorize(owned, request),
        raising=False,
    )
    with pytest.raises(mutation_gate.MutationBlocked):
        mutation_gate.enter_wallet_mutation("wallet:create_offer")

    request = _request(generation)
    permit = mutation_gate.enter_coin_prep_rbf_rescue_wallet_mutation(**request)
    assert permit.mode == "coin_prep_rbf_rescue"
    assert gate.active_mutation_count() == 1
    snapshot = {
        "success": True,
        "backend": binding.backend,
        "name": binding.name,
        "fingerprint": binding.fingerprint,
        "network_id": binding.network_id,
        "kind": binding.kind,
        "has_secrets": binding.has_secrets,
        "observed_at_utc": _timestamp(NOW),
    }
    checked_binding, checked_adapter, decision = (
        mutation_gate.require_fresh_coin_prep_rbf_rescue_wallet_continuation(
            permit, snapshot, **request
        )
    )
    assert checked_binding is binding
    assert checked_adapter is adapter
    assert decision["allowed"] is True
    with pytest.raises(mutation_gate.MutationBlocked):
        mutation_gate.enter_wallet_mutation("wallet:submit_built_transaction_rpc")
    assert mutation_gate.exit_wallet_mutation(permit) is True


def test_rbf_permit_refuses_other_attempt_or_latch_generation(
    owned_coin_prep_latch, monkeypatch
):
    owned = owned_coin_prep_latch
    _gate, _binding, _adapter, generation = owned
    monkeypatch.setattr(
        database,
        "authorize_coin_prep_rbf_rescue_target",
        lambda **request: _authorize(owned, request),
        raising=False,
    )
    for bad in (
        {"attempt_id": "9" * 64},
        {"operation_id": "coin-prep:" + "9" * 64},
        {"unsigned_sha256": "9" * 64},
        {"expected_latch_generation": generation + 1},
    ):
        with pytest.raises((mutation_gate.MutationBlocked, ValueError)):
            mutation_gate.enter_coin_prep_rbf_rescue_wallet_mutation(
                **(_request(generation) | bad)
            )


def test_rbf_permit_is_revoked_when_latch_changes(owned_coin_prep_latch, monkeypatch):
    owned = owned_coin_prep_latch
    gate, binding, _adapter, generation = owned
    monkeypatch.setattr(
        database,
        "authorize_coin_prep_rbf_rescue_target",
        lambda **request: _authorize(owned, request),
        raising=False,
    )
    request = _request(generation)
    permit = mutation_gate.enter_coin_prep_rbf_rescue_wallet_mutation(**request)
    database.trip_runtime_safety_latch(
        reason_code="COIN_PREP_RECOVERY_REQUIRED",
        blocking_operation_ids=sorted(
            [OPERATION, f"wallet-effect:{CLAIM}", "other-operation"]
        ),
        wallet_fingerprint_hash=gate.wallet_fingerprint_hash,
        network="mainnet",
        tripped_at=NOW,
    )
    snapshot = {
        "success": True,
        "backend": binding.backend,
        "name": binding.name,
        "fingerprint": binding.fingerprint,
        "network_id": binding.network_id,
        "kind": binding.kind,
        "has_secrets": binding.has_secrets,
        "observed_at_utc": _timestamp(NOW),
    }
    with pytest.raises((mutation_gate.MutationBlocked, ValueError)):
        mutation_gate.require_fresh_coin_prep_rbf_rescue_wallet_continuation(
            permit, snapshot, **request
        )
    assert mutation_gate.exit_wallet_mutation(permit) is True


def test_wallet_rescue_facade_without_owner_never_reaches_adapter(monkeypatch):
    class Adapter:
        def submit_built_transaction_rpc(self, *_args, **_kwargs):
            raise AssertionError("Sage must not be called without a rescue permit")

    monkeypatch.setattr(mutation_gate, "_runtime", None)
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", Adapter())
    result = wallet.submit_reviewed_coin_prep_rbf(ATTEMPT)
    assert result["success"] is False
    assert result.get("_catalyst_effect_attempted") is not True
