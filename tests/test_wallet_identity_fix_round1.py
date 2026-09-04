"""Controller-review regressions for Task 6 wallet identity authority."""

from __future__ import annotations

import ast
import gc
import threading
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import mutation_gate
import wallet
import wallet_sage
import config as config_module


CATALYST_ROOT = Path(__file__).resolve().parents[1] / "src" / "catalyst"


def _utc(offset_seconds: int = 0) -> str:
    value = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _binding(*, fingerprint: int = 123456) -> mutation_gate.WalletIdentityBinding:
    return mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Expected Wallet",
        fingerprint=fingerprint,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=_utc(-2),
        maximum_age_seconds=10,
    )


def _authorize_wallet(monkeypatch, adapter, *, fingerprint: int = 123456):
    binding = _binding(fingerprint=fingerprint)
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_expected_identity_binding", lambda: binding)
    monkeypatch.setattr(
        wallet, "_expected_identity_authority", lambda: (binding, adapter)
    )
    monkeypatch.setattr(
        wallet, "_revalidate_adapter_authority", lambda received, operation: None
    )
    monkeypatch.setattr(mutation_gate, "enter_wallet_mutation", lambda operation: "p")
    monkeypatch.setattr(mutation_gate, "exit_wallet_mutation", lambda permit: True)
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda permit, operation: (binding, adapter),
    )
    monkeypatch.setattr(
        mutation_gate,
        "wallet_mutation_permit_journal_authority",
        lambda permit, operation: {"owner_run_id": "wallet-identity-round1"},
    )
    monkeypatch.setattr(
        wallet,
        "_identity_from_adapter",
        lambda received: {
            "success": True,
            "backend": "sage",
            "name": "Expected Wallet",
            "fingerprint": fingerprint,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": _utc(),
        },
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda binding, snapshot, operation: {"allowed": True},
    )
    return binding


@pytest.mark.parametrize(
    ("read_call", "expected"),
    [
        (lambda: wallet_sage.get_current_key(), {"fingerprint": 123}),
        (
            lambda: wallet_sage.get_wallet_sync_status(),
            {
                "reachable": True,
                "synced": True,
                "syncing": False,
                "sync_state": "synced",
            },
        ),
        (lambda: wallet_sage.get_spendable_coin_count(1), 2),
        (lambda: wallet_sage.get_pending_transactions(), [{"transaction_id": "tx"}]),
    ],
)
def test_sage_nominal_reads_never_initialize(monkeypatch, read_call, expected):
    """Reintroducing ensure_initialized in a nominal read must fail this test."""

    monkeypatch.setattr(
        wallet_sage,
        "ensure_initialized",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("nominal read attempted initialization")
        ),
    )

    def read_rpc(endpoint, payload, timeout=10):
        responses = {
            "get_key": {"success": True, "key": {"fingerprint": 123}},
            "get_sync_status": {
                "success": True,
                "synced": True,
                "synced_coins": 1,
                "total_coins": 1,
            },
            "get_spendable_coin_count": {"success": True, "count": 2},
            "get_pending_transactions": {
                "success": True,
                "pending_transactions": [{"transaction_id": "tx"}],
            },
        }
        return responses[endpoint]

    monkeypatch.setattr(wallet_sage, "rpc", read_rpc)

    assert read_call() == expected


def test_sage_wallet_discovery_never_initializes(monkeypatch):
    """Wallet discovery is a read even when Sage has not been initialized."""

    monkeypatch.setattr(wallet_sage, "_CAT_ASSET_ID", "")
    monkeypatch.setattr(wallet_sage, "_wallet_id_to_asset_id", {})
    monkeypatch.setattr(
        wallet_sage,
        "ensure_initialized",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("wallet discovery attempted initialization")
        ),
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, payload, timeout=10: {"success": True, "cats": []},
    )

    result = wallet_sage.get_wallets()

    assert result == {
        "success": True,
        "wallets": [
            {"id": wallet_sage.WALLET_ID_XCH, "name": "Chia Wallet", "type": 0}
        ],
    }


def test_explicit_sage_initialize_is_a_guarded_wallet_export(monkeypatch):
    """Initialization must not reach the adapter without a mutation permit."""

    adapter_calls = []
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        SimpleNamespace(sage_initialize=lambda **kwargs: adapter_calls.append(kwargs)),
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_LOST", operation)
        ),
    )

    result = wallet.sage_initialize()

    assert result == {
        "success": False,
        "error": "Wallet mutation blocked by identity safety check",
        "reason": "LEASE_LOST",
        "_catalyst_effect_attempted": False,
    }
    assert adapter_calls == []


def test_sage_initialize_rechecks_identity_immediately_before_initialize(monkeypatch):
    """Readiness preparation must precede the final exact check and effect."""

    events = []
    monkeypatch.setattr(wallet_sage, "_init_ok", False)
    monkeypatch.setattr(wallet_sage, "_init_last_attempt", 0.0)
    monkeypatch.setattr(
        wallet_sage,
        "_sage_rpc_port_reachable",
        lambda: events.append("readiness") or True,
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, payload, timeout=10: (
            events.append(f"effect:{endpoint}") or {"success": True}
        ),
    )

    result = wallet_sage.sage_initialize(
        _identity_recheck=lambda step: events.append(f"check:{step}")
    )

    assert result is True
    assert events == [
        "readiness",
        "check:sage_initialize",
        "effect:initialize",
    ]


def test_sage_login_forwards_recheck_through_nested_initialize(monkeypatch):
    """Nested initialization cannot put readiness work after the last exact check."""

    events = []
    monkeypatch.setattr(wallet_sage, "_init_ok", False)
    monkeypatch.setattr(wallet_sage, "_init_last_attempt", 0.0)
    monkeypatch.setattr(
        wallet_sage,
        "_sage_rpc_port_reachable",
        lambda: events.append("readiness") or True,
    )

    def rpc(endpoint, payload, timeout=10):
        events.append(f"effect:{endpoint}")
        if endpoint == "get_version":
            return {"success": True, "version": "1.2.3"}
        return {"success": True}

    monkeypatch.setattr(wallet_sage, "rpc", rpc)
    monkeypatch.setattr(
        wallet_sage,
        "get_current_key",
        lambda: {"fingerprint": 123456, "name": "Expected Wallet"},
    )
    monkeypatch.setattr(wallet_sage.time, "sleep", lambda seconds: None)

    result = wallet_sage.sage_login(
        123456,
        _identity_recheck=lambda step: events.append(f"check:{step}"),
    )

    assert result is True
    initialize_effect = events.index("effect:initialize")
    assert events[initialize_effect - 2 : initialize_effect + 1] == [
        "readiness",
        "check:sage_initialize",
        "effect:initialize",
    ]


def test_production_modules_do_not_call_sage_ensure_initialized_directly():
    """A direct initializer call bypasses the guarded wallet facade."""

    violations = []
    for path in CATALYST_ROOT.glob("*.py"):
        if path.name == "wallet_sage.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr == "ensure_initialized"
            ):
                violations.append((path.name, node.lineno))

    assert violations == []


def test_nominal_identity_and_readiness_reads_use_wallet_facade():
    """Consumers cannot bypass the backend-neutral non-initializing read surface."""

    nominal_reads = {
        "get_current_key",
        "get_pending_transactions",
        "get_spendable_coin_count",
        "get_wallet_sync_status",
        "get_wallets",
    }
    violations = []
    for path in CATALYST_ROOT.rglob("*.py"):
        if path.name in {"wallet.py", "wallet_sage.py", "wallet_chia.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {
                "wallet_sage",
                "wallet_chia",
            }:
                for alias in node.names:
                    if alias.name in nominal_reads:
                        violations.append((str(path), node.lineno, alias.name))
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"wallet_sage", "wallet_chia"}
                and node.attr in nominal_reads
            ):
                violations.append((str(path), node.lineno, node.attr))

    assert violations == []


@pytest.mark.parametrize("target", [654321, "123456", 123456.0, True, None])
def test_sage_login_target_must_be_exact_frozen_fingerprint(monkeypatch, target):
    """A login target cannot select another key or rely on type coercion."""

    adapter_calls = []
    adapter = SimpleNamespace(
        sage_login=lambda *args, **kwargs: adapter_calls.append((args, kwargs)) or True
    )
    _authorize_wallet(monkeypatch, adapter)

    result = wallet.sage_login(target)

    assert result["success"] is False
    assert result["reason"] in {
        "WALLET_IDENTITY_MALFORMED",
        "WALLET_IDENTITY_MISMATCH",
    }
    assert result["_catalyst_effect_attempted"] is False
    assert adapter_calls == []


def test_sage_login_legacy_true_is_normalized_after_guarded_dispatch(monkeypatch):
    """The bool success contract from wallet_sage must survive the facade."""

    adapter_calls = []

    def sage_login(fingerprint, force_resync, *, _identity_recheck=None):
        adapter_calls.append((fingerprint, force_resync, _identity_recheck))
        return True

    _authorize_wallet(monkeypatch, SimpleNamespace(sage_login=sage_login))

    result = wallet.sage_login(123456)

    assert result == {"success": True, "_catalyst_effect_attempted": True}
    assert len(adapter_calls) == 1
    assert adapter_calls[0][:2] == (123456, False)
    assert callable(adapter_calls[0][2])


def test_sage_login_switches_other_active_key_to_exact_frozen_target(monkeypatch):
    """A bound login may replace another active key, then must verify the target."""

    current_fingerprint = {"value": 654321}
    events = []

    def sage_login(fingerprint, force_resync, *, _identity_recheck=None):
        events.append("adapter")
        _identity_recheck("sage_login:login")
        current_fingerprint["value"] = fingerprint
        events.append("effect")
        return True

    _authorize_wallet(monkeypatch, SimpleNamespace(sage_login=sage_login))

    def identity_from_adapter(_adapter):
        fingerprint = current_fingerprint["value"]
        return {
            "success": True,
            "backend": "sage",
            "name": "Expected Wallet" if fingerprint == 123456 else "Other Wallet",
            "fingerprint": fingerprint,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": _utc(),
        }

    def require_fresh_identity(binding, snapshot, operation):
        events.append(f"verified:{snapshot['fingerprint']}")
        if snapshot["fingerprint"] != binding.fingerprint:
            raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MISMATCH", operation)
        return {"allowed": True}

    monkeypatch.setattr(wallet, "_identity_from_adapter", identity_from_adapter)
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        require_fresh_identity,
    )

    result = wallet.sage_login(123456)

    assert result == {"success": True, "_catalyst_effect_attempted": True}
    assert events == ["adapter", "effect", "verified:123456"]


@pytest.mark.parametrize(
    ("adapter_name", "facade_name", "facade_args"),
    [
        ("sage_initialize", "sage_initialize", ()),
        ("delete_offer", "sage_delete_offer", ("offer-id",)),
    ],
)
def test_other_legacy_true_mutations_are_normalized_after_guarded_dispatch(
    monkeypatch, adapter_name, facade_name, facade_args
):
    adapter_calls = []

    def legacy_mutation(*args, **kwargs):
        adapter_calls.append((args, kwargs))
        return True

    adapter = SimpleNamespace(**{adapter_name: legacy_mutation})
    _authorize_wallet(monkeypatch, adapter)

    result = getattr(wallet, facade_name)(*facade_args)

    assert result == {"success": True, "_catalyst_effect_attempted": True}
    assert len(adapter_calls) == 1


def test_set_change_address_none_binds_frozen_fingerprint(monkeypatch):
    """The adapter must not rediscover a potentially switched active key."""

    adapter_calls = []

    def set_change_address(address, fingerprint, *, _identity_recheck=None):
        adapter_calls.append((address, fingerprint))
        return {"success": True}

    _authorize_wallet(
        monkeypatch,
        SimpleNamespace(set_change_address=set_change_address),
    )

    result = wallet.set_change_address("xch1safe", None)

    assert result == {"success": True, "_catalyst_effect_attempted": True}
    assert adapter_calls == [("xch1safe", 123456)]


@pytest.mark.parametrize(
    ("endpoint", "payload", "reason"),
    [
        ("login", {"fingerprint": 654321}, "WALLET_IDENTITY_MISMATCH"),
        ("resync", {"fingerprint": 654321}, "WALLET_IDENTITY_MISMATCH"),
        ("log_in", {"fingerprint": 654321}, "WALLET_IDENTITY_MISMATCH"),
        ("login", {"fingerprint": "123456"}, "WALLET_IDENTITY_MALFORMED"),
        ("resync", {"fingerprint": True}, "WALLET_IDENTITY_MALFORMED"),
        ("login", [("fingerprint", 123456)], "WALLET_IDENTITY_MALFORMED"),
    ],
)
def test_generic_identity_switch_rpc_requires_exact_frozen_target(
    monkeypatch, endpoint, payload, reason
):
    """Generic login/resync must not bypass the target-fingerprint contract."""

    adapter_calls = []
    adapter = SimpleNamespace(
        rpc=lambda *args, **kwargs: (
            adapter_calls.append((args, kwargs)) or {"success": True}
        )
    )
    _authorize_wallet(monkeypatch, adapter)

    result = wallet.rpc(endpoint, payload)

    expected = {
        "success": False,
        "error": "Wallet mutation blocked by identity safety check",
        "reason": reason,
    }
    if type(payload) is dict:
        expected["_catalyst_effect_attempted"] = False
    assert result == expected
    assert adapter_calls == []


def test_matching_generic_login_rechecks_at_raw_rpc_effect(monkeypatch):
    """The exact generic target still requires an adapter-near fresh check."""

    events = []

    def adapter_rpc(endpoint, payload, timeout=10, *, _identity_recheck=None):
        events.append("adapter")
        assert _identity_recheck is not None
        _identity_recheck("rpc:login")
        events.append("effect")
        return {"success": True}

    _authorize_wallet(monkeypatch, SimpleNamespace(rpc=adapter_rpc))

    result = wallet.rpc("login", {"fingerprint": 123456})

    assert result == {"success": True, "_catalyst_effect_attempted": True}
    assert events == ["adapter", "effect"]


def test_generic_login_freezes_validated_target_across_identity_read(monkeypatch):
    """An intervening identity read cannot rewrite the validated login target."""

    payload = {"fingerprint": 123456}
    adapter_calls = []

    def adapter_rpc(endpoint, forwarded_payload, timeout=10, *, _identity_recheck=None):
        adapter_calls.append((endpoint, dict(forwarded_payload), forwarded_payload))
        return {"success": True}

    _authorize_wallet(monkeypatch, SimpleNamespace(rpc=adapter_rpc))

    def mutate_payload_during_identity_read(received_adapter):
        payload["fingerprint"] = 654321
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

    monkeypatch.setattr(
        wallet, "_identity_from_adapter", mutate_payload_during_identity_read
    )

    result = wallet.rpc("login", payload)

    assert result == {"success": True, "_catalyst_effect_attempted": True}
    assert payload == {"fingerprint": 654321}
    assert adapter_calls[0][0:2] == ("login", {"fingerprint": 123456})
    assert adapter_calls[0][2] is not payload


class _HostileRpcEndpoint:
    def __hash__(self):
        return hash("hostile-rpc-endpoint")

    def __eq__(self, other):
        return False

    def lstrip(self, chars):
        return "login"


@pytest.mark.parametrize("endpoint", ["/login", "///resync", _HostileRpcEndpoint()])
def test_generic_rpc_rejects_normalizing_identity_endpoint_alias(monkeypatch, endpoint):
    """Endpoint aliases cannot evade the facade's identity-target validation."""

    adapter_calls = []
    adapter = SimpleNamespace(
        rpc=lambda *args, **kwargs: (
            adapter_calls.append((args, kwargs)) or {"success": True}
        )
    )
    _authorize_wallet(monkeypatch, adapter)

    result = wallet.rpc(endpoint, {"fingerprint": 654321})

    assert result["success"] is False
    assert result["reason"] == "WALLET_IDENTITY_MALFORMED"
    assert adapter_calls == []


class _HostilePayload(dict):
    pass


@pytest.mark.parametrize(
    ("endpoint", "payload", "timeout"),
    [
        (b"login", {"fingerprint": 123456}, 10),
        ("submit_transaction", _HostilePayload(spend_bundle={}), 10),
        ("submit_transaction", {}, True),
        ("submit_transaction", {}, 1.5),
        ("submit_transaction", {}, 0),
    ],
)
def test_generic_rpc_requires_exact_boundary_types(
    monkeypatch, endpoint, payload, timeout
):
    """Generic RPC request types are exact before read/mutation dispatch."""

    adapter_calls = []
    adapter = SimpleNamespace(
        rpc=lambda *args, **kwargs: (
            adapter_calls.append((args, kwargs)) or {"success": True}
        )
    )
    _authorize_wallet(monkeypatch, adapter)

    result = wallet.rpc(endpoint, payload, timeout)

    assert result["success"] is False
    assert result["reason"] == "WALLET_IDENTITY_MALFORMED"
    assert adapter_calls == []


@pytest.mark.parametrize("force_resync", [1, 0, "yes", None])
def test_sage_login_requires_exact_resync_flag(monkeypatch, force_resync):
    """Ambiguous truthy values cannot silently enable identity resync."""

    adapter_calls = []
    adapter = SimpleNamespace(
        sage_login=lambda *args, **kwargs: (
            adapter_calls.append((args, kwargs)) or {"success": True}
        )
    )
    _authorize_wallet(monkeypatch, adapter)

    result = wallet.sage_login(123456, force_resync)

    assert result["success"] is False
    assert result["reason"] == "WALLET_IDENTITY_MALFORMED"
    assert result["_catalyst_effect_attempted"] is False
    assert adapter_calls == []


def test_sage_node_selection_rejects_runtime_rebind_before_state_change(monkeypatch):
    """Every trigger_start caller is fenced before global/session selection."""

    import sage_node

    monkeypatch.setenv("WALLET_TYPE", "sage")
    monkeypatch.setattr(
        sage_node,
        "get_sage_version_requirement",
        lambda: {"supported": True},
    )
    monkeypatch.setattr(sage_node, "_selected_fingerprint", "123456")
    sage_node._start_triggered.clear()
    starts = []
    monkeypatch.setattr(
        sage_node.threading,
        "Thread",
        lambda *args, **kwargs: SimpleNamespace(start=lambda: starts.append(True)),
    )
    monkeypatch.setattr(
        wallet,
        "validate_runtime_target_fingerprint",
        lambda target: {
            "success": False,
            "error": "Wallet mutation blocked by identity safety check",
            "reason": "WALLET_IDENTITY_MISMATCH",
        },
    )

    result = sage_node.trigger_start("654321")

    assert result["success"] is False
    assert result["reason"] == "WALLET_IDENTITY_MISMATCH"
    assert sage_node._selected_fingerprint == "123456"
    assert sage_node._start_triggered.is_set() is False
    assert starts == []


def test_chia_saved_startup_fingerprint_requires_runtime_target_authority(monkeypatch):
    """A persisted preload target cannot bypass the exact runtime binding."""

    import sage_node

    decisions = []
    monkeypatch.setenv("WALLET_TYPE", "chia")
    monkeypatch.setenv("SAGE_FINGERPRINT", "")
    monkeypatch.setenv("WALLET_FINGERPRINT", "654321")
    monkeypatch.setattr(
        wallet,
        "validate_runtime_target_fingerprint",
        lambda target: (
            decisions.append(target)
            or {
                "success": False,
                "error": "Wallet mutation blocked by identity safety check",
                "reason": "WALLET_IDENTITY_MISMATCH",
            }
        ),
    )

    fingerprint = sage_node._resolve_startup_fingerprint()

    assert fingerprint is None
    assert decisions == [654321]


def test_sage_node_chia_split_routes_effect_through_wallet_facade(monkeypatch):
    """The legacy Chia CLI helper cannot submit outside wallet mutation guards."""

    import sage_node

    coin_id = "0xabc123"
    facade_calls = []
    monkeypatch.setenv("WALLET_TYPE", "chia")
    monkeypatch.setattr(
        wallet,
        "get_spendable_coins_rpc",
        lambda wallet_id: {
            "success": True,
            "confirmed_records": [
                {
                    "coin": {
                        "parent_coin_info": "0xparent",
                        "puzzle_hash": "0xpuzzle",
                        "amount": 3000,
                    }
                }
            ],
        },
    )
    monkeypatch.setattr(sage_node, "_compute_coin_id", lambda *args: coin_id)
    monkeypatch.setattr(
        wallet,
        "split_coins_rpc",
        lambda *args: facade_calls.append(args) or {"success": True},
    )
    monkeypatch.setattr(
        sage_node.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("direct Chia CLI mutation")
        ),
    )

    result = sage_node.split_coin(1, coin_id, 3)

    assert result["success"] is True
    assert facade_calls == [(1, coin_id, 3, 1000, 0, False)]


@pytest.mark.parametrize(
    "operation",
    [
        "coin_prep.cli_consolidate",
        "coin_prep.cli_create_pool",
        "coin_prep.cli_split",
    ],
)
def test_coin_prep_chia_cli_effects_are_unsupported(operation):
    """Chia cannot bypass its read-only Task 6 adapter through worker CLIs."""

    import coin_prep_worker

    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker.is_sage = False
    worker._is_subprocess = False

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        worker._require_cli_mutation(operation)

    assert error.value.reason_code == "WALLET_BACKEND_UNSUPPORTED"


def _owner_gate(binding=None):
    binding = binding or _binding()
    return mutation_gate.MutationGate(
        run_id="fix-round-owner",
        owner_pid=101,
        owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network=binding.network_id,
        wallet_identity_binding=binding,
    )


def _snapshot_for(binding):
    return {
        "success": True,
        "backend": binding.backend,
        "name": binding.name,
        "fingerprint": binding.fingerprint,
        "network_id": binding.network_id,
        "kind": binding.kind,
        "has_secrets": binding.has_secrets,
        "observed_at_utc": _utc(),
    }


def test_owner_identity_authority_rejects_public_reassignment():
    """Runtime code cannot replace the identity authority after construction."""

    gate = _owner_gate()

    with pytest.raises(AttributeError):
        gate.wallet_identity_binding = _binding(fingerprint=654321)

    assert gate.wallet_identity_binding.fingerprint == 123456


def test_owner_identity_authority_tamper_fails_every_wallet_boundary(monkeypatch):
    """Private/public dict tampering cannot create a self-consistent new authority."""

    original = _binding()
    hostile = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Hostile Wallet",
        fingerprint=original.fingerprint,
        network_id=original.network_id,
        kind="hostile-kind",
        has_secrets=True,
        bound_at_utc=original.bound_at_utc,
        maximum_age_seconds=original.maximum_age_seconds,
    )
    gate = _owner_gate(original)
    monkeypatch.setattr(gate, "require_allowed", lambda operation: SimpleNamespace())
    monkeypatch.setattr(mutation_gate, "_runtime", gate)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: gate)
    gate.__dict__["wallet_identity_binding"] = hostile
    gate.__dict__["_wallet_identity_binding"] = hostile

    with pytest.raises(mutation_gate.MutationBlocked) as enter_error:
        mutation_gate.enter_wallet_mutation("wallet:create_offer")
    assert enter_error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"

    with pytest.raises(mutation_gate.MutationBlocked) as identity_error:
        gate.require_fresh_wallet_identity(
            _snapshot_for(hostile), "wallet:create_offer"
        )
    assert identity_error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


def test_owner_identity_authority_reassignment_is_thread_safe():
    """Concurrent reassignment attempts are all rejected without partial rebind."""

    gate = _owner_gate()
    errors = []

    def replace():
        try:
            gate.wallet_identity_binding = _binding(fingerprint=654321)
        except Exception as exc:
            errors.append(type(exc))

    threads = [threading.Thread(target=replace) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == [AttributeError] * 8
    assert gate.wallet_identity_binding.fingerprint == 123456


def test_corrupted_owner_authority_cannot_be_reinitialized(monkeypatch):
    """Re-initialization validates the old authority before comparing candidates."""

    binding = _binding()
    hostile = mutation_gate.WalletIdentityBinding(
        backend=binding.backend,
        name="Rebound Wallet",
        fingerprint=binding.fingerprint,
        network_id=binding.network_id,
        kind=binding.kind,
        has_secrets=True,
        bound_at_utc=binding.bound_at_utc,
        maximum_age_seconds=binding.maximum_age_seconds,
    )
    gate = _owner_gate(binding)
    gate.__dict__["_wallet_identity_binding"] = hostile
    monkeypatch.setattr(mutation_gate, "_runtime", gate)

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        mutation_gate.initialize(
            wallet_fingerprint_hash=gate.wallet_fingerprint_hash,
            network=gate.network,
            run_id=gate.run_id,
            owner_pid=gate.owner_pid,
            owner_host=gate.owner_host,
            lease_seconds=gate.lease_seconds,
            start_heartbeat=False,
            acquire_lease=False,
            wallet_identity_binding=binding,
        )

    assert error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


def test_runtime_target_selection_revalidates_owner_authority(monkeypatch):
    """Selection cannot trust a binding that was replaced through hostile internals."""

    original = _binding()
    hostile = _binding(fingerprint=654321)
    gate = _owner_gate(original)
    gate.__dict__["_wallet_identity_binding"] = hostile
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: gate)

    result = wallet.validate_runtime_target_fingerprint(hostile.fingerprint)

    assert result == {
        "success": False,
        "error": "Wallet mutation blocked by identity safety check",
        "reason": "WALLET_IDENTITY_BINDING_INVALID",
    }


def test_owner_authority_rejects_self_consistent_hostile_internal_replacement():
    """Replacing every instance-local anchor cannot replace acquired authority."""

    original = _binding()
    hostile = _binding(fingerprint=654321)
    gate = _owner_gate(original)
    hostile_hash = mutation_gate.wallet_fingerprint_hash(hostile.fingerprint)
    object.__setattr__(gate, "_wallet_identity_binding", hostile)
    object.__setattr__(
        gate,
        "_wallet_identity_binding_digest",
        mutation_gate.wallet_identity_binding_digest(hostile),
    )
    object.__setattr__(gate, "wallet_fingerprint_hash", hostile_hash)
    object.__setattr__(gate, "_identity_wallet_fingerprint_hash", hostile_hash)
    object.__setattr__(gate, "_identity_network", hostile.network_id)
    object.__setattr__(gate, "_identity_backend", hostile.backend)

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        gate.require_wallet_identity_authority("wallet:create_offer")

    assert error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


def test_owner_authority_registry_does_not_retain_released_runtime():
    """The external immutable authority must not leak a shut-down gate."""

    gate = _owner_gate()
    gate_reference = weakref.ref(gate)

    del gate
    gc.collect()

    assert gate_reference() is None


@pytest.mark.parametrize("drift", ["backend", "adapter"])
def test_owner_binding_rejects_wallet_dispatch_drift(monkeypatch, drift):
    """The pinned owner backend must match the actual dispatcher at each boundary."""

    gate = _owner_gate()
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: gate)
    if drift == "backend":
        monkeypatch.setattr(wallet, "WALLET_TYPE", "chia")
    else:
        monkeypatch.setattr(wallet, "_wallet_adapter", SimpleNamespace())

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        wallet._expected_identity_binding()

    assert error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


def test_delegated_binding_rejects_wallet_adapter_drift(monkeypatch):
    """A worker cannot redirect its authenticated binding to another adapter."""

    binding = _binding()
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(
        mutation_gate,
        "worker_identity_lease_binding",
        lambda: {
            "binding": binding,
            "binding_digest": mutation_gate.wallet_identity_binding_digest(binding),
            "wallet_fingerprint_hash": mutation_gate.wallet_fingerprint_hash(
                binding.fingerprint
            ),
            "network": binding.network_id,
            "bound_at_utc": binding.bound_at_utc,
        },
    )
    monkeypatch.setattr(wallet, "_wallet_adapter", SimpleNamespace())

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        wallet._expected_identity_binding()

    assert error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


def test_coin_prep_delegation_requires_complete_identity_at_issuance(
    monkeypatch,
):
    """A wallet worker handoff cannot be created with an empty identity payload."""

    gate = mutation_gate.MutationGate(
        run_id="unbound-parent",
        owner_pid=101,
        owner_host="test-host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(123456),
        network="mainnet",
        wallet_identity_binding=None,
    )
    gate._lease_acquired_at = _utc(-1)
    monkeypatch.setattr(gate, "require_allowed", lambda operation: SimpleNamespace())

    with pytest.raises(mutation_gate.MutationBlocked) as error:
        gate.issue_worker_delegation(
            operation_id="coin-prep:run",
            purpose="coin_prep",
            worker_id="coin-prep-worker:run",
            ttl_seconds=30,
            require_wallet_identity=True,
        )

    assert error.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


def test_coin_prep_issuer_requests_complete_wallet_identity():
    """The only production worker issuer must opt into complete identity binding."""

    import coin_manager
    import inspect

    source = inspect.getsource(coin_manager._issue_coin_prep_worker_delegation)
    assert "require_wallet_identity=True" in source


def test_coin_prep_worker_copies_complete_delegation_environment():
    """The subprocess must not drop authenticated identity fields at startup."""

    import coin_prep_worker

    assert set(coin_prep_worker._WORKER_DELEGATION_ENV_NAMES) == set(
        mutation_gate._DELEGATION_ENV_NAMES
    )


@pytest.mark.parametrize(
    "rpc_result",
    [
        None,
        True,
        ["hostile"],
        "accepted",
        {"success": False, "error": "secret backend rejection"},
        {"success": 1},
        {"success": True, "error": "rejected"},
        {"success": True, "error_message": "rejected"},
        {"success": True, "status": "failed"},
    ],
)
def test_set_change_address_requires_exact_rpc_success(monkeypatch, rpc_result):
    """Rejected and malformed Sage responses can never become success."""

    monkeypatch.setattr(
        wallet_sage,
        "_validate_address_for_active_network",
        lambda address, context: address,
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *args, **kwargs: rpc_result,
    )

    result = wallet_sage.set_change_address("xch1safe", 123456)

    assert result == {"success": False, "error": "set_change_address_failed"}


def test_set_change_address_accepts_only_exact_success_true(monkeypatch):
    """A genuine exact success keeps the bounded legacy success fields."""

    monkeypatch.setattr(
        wallet_sage,
        "_validate_address_for_active_network",
        lambda address, context: address,
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *args, **kwargs: {"success": True},
    )

    assert wallet_sage.set_change_address("xch1safe", 123456) == {
        "success": True,
        "fingerprint": 123456,
        "address": "xch1safe",
    }


def test_set_change_address_accepts_documented_empty_response(monkeypatch):
    """Sage v0.12.10 returns its documented EmptyResponse as an empty object."""

    monkeypatch.setattr(
        wallet_sage,
        "_validate_address_for_active_network",
        lambda address, context: address,
    )
    monkeypatch.setattr(wallet_sage, "rpc", lambda *args, **kwargs: {})

    assert wallet_sage.set_change_address("xch1safe", 123456) == {
        "success": True,
        "fingerprint": 123456,
        "address": "xch1safe",
    }


@pytest.mark.parametrize("fingerprint", [None, "123456", 123456.0, True, -1])
def test_adapter_set_change_address_rejects_ambiguous_target(monkeypatch, fingerprint):
    """Direct adapter misuse cannot rediscover or coerce an identity target."""

    rpc_calls = []
    monkeypatch.setattr(
        wallet_sage,
        "_validate_address_for_active_network",
        lambda address, context: address,
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *args, **kwargs: rpc_calls.append((args, kwargs)) or {"success": True},
    )
    monkeypatch.setattr(
        wallet_sage,
        "_get_current_key_read_only",
        lambda: {"fingerprint": 123456},
    )

    result = wallet_sage.set_change_address("xch1safe", fingerprint)

    assert result == {"success": False, "error": "invalid_fingerprint"}
    assert rpc_calls == []


@pytest.mark.parametrize(
    "raw_value",
    ["", " 10", "10 ", "true", "10.0", "+10", "01", "0", "301"],
)
def test_malformed_identity_max_age_never_silently_defaults(monkeypatch, raw_value):
    """Identity-critical age syntax/range errors remain visibly invalid."""

    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("WALLET_IDENTITY_MAX_AGE_SECONDS", raw_value)

    parsed = config_module.Config().WALLET_IDENTITY_MAX_AGE_SECONDS

    assert parsed is None


def test_absent_identity_max_age_uses_documented_safe_default(monkeypatch):
    """Only an absent setting receives the documented ten-second default."""

    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("WALLET_IDENTITY_MAX_AGE_SECONDS", raising=False)

    assert config_module.Config().WALLET_IDENTITY_MAX_AGE_SECONDS == 10
