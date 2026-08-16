from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ast
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import mutation_gate
import wallet


NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)


def _binding(**overrides):
    values = {
        "backend": "sage",
        "name": "Expected Wallet",
        "fingerprint": 123456789,
        "network_id": "mainnet",
        "kind": "bls",
        "has_secrets": True,
        "bound_at_utc": "2026-08-16T11:59:50Z",
        "maximum_age_seconds": 15,
    }
    values.update(overrides)
    return mutation_gate.WalletIdentityBinding(**values)


def _identity(**overrides):
    values = {
        "success": True,
        "backend": "sage",
        "name": "Expected Wallet",
        "fingerprint": 123456789,
        "network_id": "mainnet",
        "kind": "bls",
        "has_secrets": True,
        "observed_at_utc": "2026-08-16T11:59:59Z",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    ("identity", "reason"),
    [
        (_identity(success=False), "WALLET_IDENTITY_UNAVAILABLE"),
        (_identity(fingerprint=987654321), "WALLET_IDENTITY_MISMATCH"),
        (_identity(network_id="testnet11"), "WALLET_IDENTITY_MISMATCH"),
        (_identity(kind="watch_only"), "WALLET_IDENTITY_MISMATCH"),
        (_identity(has_secrets=False), "WALLET_IDENTITY_NON_SIGNING"),
        (_identity(backend="chia"), "WALLET_IDENTITY_MISMATCH"),
        (_identity(name="Other Wallet"), "WALLET_IDENTITY_MISMATCH"),
        (
            _identity(observed_at_utc="2026-08-16T11:59:30Z"),
            "WALLET_IDENTITY_STALE",
        ),
        (
            _identity(observed_at_utc="2026-08-16T12:00:01Z"),
            "WALLET_IDENTITY_STALE",
        ),
        (
            _identity(observed_at_utc="2026-08-16T11:59:59"),
            "WALLET_IDENTITY_MALFORMED",
        ),
        (
            _identity(fingerprint=True),
            "WALLET_IDENTITY_MALFORMED",
        ),
    ],
)
def test_identity_policy_fails_closed(identity, reason):
    decision = mutation_gate.validate_wallet_identity(_binding(), identity, now=NOW)

    assert decision == {"allowed": False, "reason": reason}


def test_identity_policy_accepts_exact_fresh_snapshot():
    decision = mutation_gate.validate_wallet_identity(_binding(), _identity(), now=NOW)

    assert decision["allowed"] is True
    assert decision["reason"] == "identity_verified"
    assert decision["observed_at_utc"] == "2026-08-16T11:59:59.000000Z"


def test_unsupported_or_incomplete_expected_backend_fails_closed():
    unsupported = _binding(backend="unknown")

    assert mutation_gate.validate_wallet_identity(
        unsupported, _identity(backend="unknown"), now=NOW
    ) == {"allowed": False, "reason": "WALLET_BACKEND_UNSUPPORTED"}
    assert mutation_gate.validate_wallet_identity(
        None,
        _identity(backend="chia", name=None, kind=None),
        now=NOW,
    ) == {"allowed": False, "reason": "WALLET_IDENTITY_BINDING_INVALID"}
    chia_binding = _binding(backend="chia")
    assert mutation_gate.validate_wallet_identity(
        chia_binding,
        _identity(
            backend="chia",
            name=None,
            network_id=None,
            kind=None,
            has_secrets=None,
        ),
        now=NOW,
    ) == {"allowed": False, "reason": "WALLET_BACKEND_UNSUPPORTED"}


def test_binding_rejects_naive_or_non_utc_observation_baseline():
    with pytest.raises(ValueError):
        _binding(bound_at_utc="2026-08-16T11:59:50")
    with pytest.raises(ValueError):
        _binding(bound_at_utc="2026-08-16T12:59:50+01:00")


def test_mutation_binding_requires_an_exact_expected_wallet_name():
    with pytest.raises(ValueError):
        _binding(name=None)
    with pytest.raises(ValueError):
        _binding(name="")


def test_runtime_rejects_replayed_or_rollback_identity_observation(monkeypatch):
    gate = mutation_gate.MutationGate(
        run_id="run-identity",
        owner_pid=123,
        owner_host="host",
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(123456789),
        network="mainnet",
        wallet_identity_binding=_binding(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(gate, "require_allowed", lambda operation: None)

    first = gate.require_fresh_wallet_identity(_identity(), "offer:create")
    assert first["allowed"] is True
    with pytest.raises(mutation_gate.MutationBlocked) as replay:
        gate.require_fresh_wallet_identity(_identity(), "offer:create")
    assert replay.value.reason_code == "WALLET_IDENTITY_STALE"


def test_exported_mutation_reads_identity_again_after_preflight(monkeypatch):
    adapter_calls = []
    identities = [
        _identity(observed_at_utc="2026-08-16T11:59:58Z"),
        _identity(
            fingerprint=777777777,
            observed_at_utc="2026-08-16T11:59:59Z",
        ),
    ]
    fake_adapter = SimpleNamespace(
        get_wallet_identity=lambda: identities.pop(0),
        create_offer=lambda *args, **kwargs: (
            adapter_calls.append((args, kwargs)) or {"success": True}
        ),
    )
    checked = []

    monkeypatch.setattr(wallet, "_wallet_adapter", fake_adapter)
    monkeypatch.setattr(wallet, "_expected_identity_binding", lambda: _binding())
    monkeypatch.setattr(
        wallet, "_expected_identity_authority", lambda: (_binding(), fake_adapter)
    )
    monkeypatch.setattr(
        wallet, "_revalidate_adapter_authority", lambda adapter, operation: None
    )
    monkeypatch.setattr(
        mutation_gate,
        "validate_wallet_identity",
        lambda binding, snapshot, **kwargs: (
            {"allowed": True, "reason": "identity_verified"}
            if snapshot["fingerprint"] == binding.fingerprint
            else {"allowed": False, "reason": "WALLET_IDENTITY_MISMATCH"}
        ),
    )

    def require_identity(binding, snapshot, operation):
        decision = mutation_gate.validate_wallet_identity(binding, snapshot)
        if decision["allowed"] is not True:
            raise mutation_gate.MutationBlocked(decision["reason"], operation)
        return decision

    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        require_identity,
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda operation: checked.append(operation) or "permit",
    )
    monkeypatch.setattr(mutation_gate, "exit_wallet_mutation", lambda permit: True)
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda permit, operation: (_binding(), fake_adapter),
    )

    assert wallet.preflight_wallet_identity() == {
        "success": True,
        "reason": "identity_verified",
    }
    result = wallet.create_offer({1: -1, 2: 1}, validate_only=False)

    assert result == {
        "success": False,
        "error": "Wallet mutation blocked by identity safety check",
        "reason": "WALLET_IDENTITY_MISMATCH",
    }
    assert checked == ["wallet:create_offer"]
    assert adapter_calls == []
    assert identities == []


@pytest.mark.parametrize(
    "export_name",
    [
        "create_offer",
        "cancel_offer",
        "cancel_offers_batch",
        "cleanup_expired_offers",
        "split_coins_rpc",
        "split_coins_bulk",
        "send_transaction",
        "send_transaction_multi",
    ],
)
def test_all_common_exported_mutations_are_wrapped(export_name):
    assert export_name in wallet.MUTATING_WALLET_EXPORTS
    assert getattr(wallet, export_name) is not getattr(
        wallet._wallet_adapter, export_name
    )


def test_wallet_mutation_inventory_is_exact_and_facade_owned():
    expected = {
        "auto_combine_cat",
        "auto_combine_xch",
        "cancel_offer",
        "cancel_offers_batch",
        "cleanup_expired_offers",
        "combine_coins",
        "create_offer",
        "create_transaction_rpc",
        "full_node_rpc",
        "get_next_address",
        "rpc",
        "sage_delete_offer",
        "sage_delete_offers_batch",
        "sage_initialize",
        "sage_login",
        "sage_topup_split",
        "send_cat_multi",
        "send_transaction",
        "send_transaction_multi",
        "set_change_address",
        "sign_message_by_address",
        "split_coins_bulk",
        "split_coins_rpc",
    }

    assert wallet.MUTATING_WALLET_EXPORTS == frozenset(expected)
    assert all(getattr(wallet, name).__module__ == "wallet" for name in expected)


def test_new_address_export_is_guarded_but_existing_address_read_stays_available(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        SimpleNamespace(
            get_next_address=lambda wallet_id, new_address=True: (
                calls.append((wallet_id, new_address))
                or {"success": True, "address": "xch1safe"}
            )
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_LOST", operation)
        ),
    )

    assert wallet.get_next_address(1, new_address=False)["success"] is True
    blocked = wallet.get_next_address(1, new_address=True)

    assert calls == [(1, False)]
    assert blocked["success"] is False
    assert blocked["reason"] == "LEASE_LOST"


def test_sage_existing_address_read_does_not_initialize_wallet(monkeypatch):
    import wallet_sage

    monkeypatch.setattr(
        wallet_sage,
        "ensure_initialized",
        lambda: (_ for _ in ()).throw(
            AssertionError("read-only address lookup must not initialize")
        ),
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *args, **kwargs: {
            "success": True,
            "receive_address": "xch1safe",
        },
    )

    assert wallet_sage.get_next_address(new_address=False) == {
        "success": True,
        "address": "xch1safe",
    }


@pytest.mark.parametrize(
    ("backend", "expected_validate_only", "expected_reuse"),
    [("sage", False, True), ("chia", True, False)],
)
def test_create_offer_preserves_selected_adapter_defaults(
    monkeypatch, backend, expected_validate_only, expected_reuse
):
    calls = []
    monkeypatch.setattr(wallet, "WALLET_TYPE", backend)
    monkeypatch.setattr(
        wallet,
        "_run_wallet_mutation",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )

    assert wallet.create_offer({1: -1, 2: 1}) == {"success": True}
    assert calls[0][1]["validate_only"] is expected_validate_only
    assert calls[0][1]["_reuse_puzhash"] is expected_reuse


def test_mutation_requires_lease_even_when_identity_matches(monkeypatch):
    adapter_calls = []
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        SimpleNamespace(
            get_wallet_identity=lambda: _identity(),
            cancel_offer=lambda *args, **kwargs: adapter_calls.append(True),
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_LOST", operation)
        ),
    )

    result = wallet.cancel_offer("a" * 64)

    assert result["success"] is False
    assert result["reason"] == "LEASE_LOST"
    assert adapter_calls == []


def test_read_only_exports_remain_usable_when_mutation_is_blocked(monkeypatch):
    calls = []
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        SimpleNamespace(
            get_wallet_balance=lambda wallet_id: (
                calls.append(wallet_id) or {"success": True, "wallet_id": wallet_id}
            )
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_LOST", operation)
        ),
    )

    assert wallet.get_wallet_balance(1) == {"success": True, "wallet_id": 1}
    assert calls == [1]


def test_mutation_exceptions_preserve_stable_dict_and_release_permit(monkeypatch):
    exits = []
    fake_adapter = SimpleNamespace(
        get_wallet_identity=lambda: _identity(),
        send_transaction=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("private remote text")
        ),
    )
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        fake_adapter,
    )
    monkeypatch.setattr(wallet, "_expected_identity_binding", lambda: _binding())
    monkeypatch.setattr(
        wallet, "_expected_identity_authority", lambda: (_binding(), fake_adapter)
    )
    monkeypatch.setattr(
        wallet, "_revalidate_adapter_authority", lambda adapter, operation: None
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda operation: "permit",
    )
    monkeypatch.setattr(
        mutation_gate,
        "validate_wallet_identity",
        lambda *args, **kwargs: {"allowed": True, "reason": "identity_verified"},
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda *args, **kwargs: {"allowed": True, "reason": "identity_verified"},
    )
    monkeypatch.setattr(
        mutation_gate,
        "exit_wallet_mutation",
        lambda permit: exits.append(permit) or True,
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda permit, operation: (_binding(), fake_adapter),
    )

    result = wallet.send_transaction(1, 1, "xch1destination")

    assert result == {
        "success": False,
        "error": "Wallet mutation failed after authorization",
        "reason": "WALLET_MUTATION_FAILED",
    }
    assert "private remote text" not in str(result)
    assert exits == ["permit"]


def test_exit_failure_never_raises_through_wallet_boundary(monkeypatch):
    fake_adapter = SimpleNamespace(
        get_wallet_identity=lambda: _identity(),
        cancel_offer=lambda *args, **kwargs: {"success": True},
    )
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        fake_adapter,
    )
    monkeypatch.setattr(wallet, "_expected_identity_binding", lambda: _binding())
    monkeypatch.setattr(
        wallet, "_expected_identity_authority", lambda: (_binding(), fake_adapter)
    )
    monkeypatch.setattr(
        wallet, "_revalidate_adapter_authority", lambda adapter, operation: None
    )
    monkeypatch.setattr(
        mutation_gate, "enter_wallet_mutation", lambda operation: "permit"
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda *args, **kwargs: {"allowed": True},
    )
    monkeypatch.setattr(
        mutation_gate,
        "exit_wallet_mutation",
        lambda permit: (_ for _ in ()).throw(RuntimeError("private exit error")),
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda permit, operation: (_binding(), fake_adapter),
    )

    assert wallet.cancel_offer("a" * 64) == {"success": True}


def test_async_adapter_callback_is_not_returned_outside_permit(monkeypatch):
    closed = []

    class AwaitableResult:
        def __await__(self):
            yield

        def close(self):
            closed.append(True)

    fake_adapter = SimpleNamespace(
        get_wallet_identity=lambda: _identity(),
        send_transaction=lambda *args, **kwargs: AwaitableResult(),
    )
    monkeypatch.setattr(wallet, "_wallet_adapter", fake_adapter)
    monkeypatch.setattr(wallet, "_expected_identity_binding", lambda: _binding())
    monkeypatch.setattr(
        wallet, "_expected_identity_authority", lambda: (_binding(), fake_adapter)
    )
    monkeypatch.setattr(
        wallet, "_revalidate_adapter_authority", lambda adapter, operation: None
    )
    monkeypatch.setattr(
        mutation_gate, "enter_wallet_mutation", lambda operation: "permit"
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda *args, **kwargs: {"allowed": True},
    )
    monkeypatch.setattr(mutation_gate, "exit_wallet_mutation", lambda permit: True)
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda permit, operation: (_binding(), fake_adapter),
    )

    result = wallet.send_transaction(1, 1, "xch1destination")

    assert result["success"] is False
    assert result["reason"] == "WALLET_BACKEND_UNSUPPORTED"
    assert closed == [True]


def test_generic_rpc_defaults_to_guarded_but_known_reads_stay_available(monkeypatch):
    calls = []
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        SimpleNamespace(
            rpc=lambda endpoint, payload, timeout=10: (
                calls.append(endpoint) or {"success": True}
            )
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_LOST", operation)
        ),
    )

    assert wallet.rpc("get_coins", {}) == {"success": True}
    blocked = wallet.rpc("submit_transaction", {"spend_bundle": {}})

    assert calls == ["get_coins"]
    assert blocked["success"] is False
    assert blocked["reason"] == "LEASE_LOST"


def test_full_node_rpc_defaults_to_guarded_but_known_reads_stay_available(monkeypatch):
    calls = []
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        SimpleNamespace(
            full_node_rpc=lambda endpoint, payload, timeout=5: (
                calls.append(endpoint) or {"success": True}
            )
        ),
    )
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_LOST", operation)
        ),
    )

    assert wallet.full_node_rpc("get_blockchain_state", {}) == {"success": True}
    blocked = wallet.full_node_rpc("push_tx", {"spend_bundle": {}})

    assert calls == ["get_blockchain_state"]
    assert blocked["success"] is False
    assert blocked["reason"] == "LEASE_LOST"


def test_compound_wallet_export_rechecks_identity_inside_adapter(monkeypatch):
    identity_calls = []
    authorization_calls = []

    def adapter_batch(*args, **kwargs):
        recheck = kwargs["_identity_recheck"]
        recheck("first")
        recheck("second")
        return {"success": True}

    fake_adapter = SimpleNamespace(
        get_wallet_identity=lambda: identity_calls.append(True) or _identity(),
        cancel_offers_batch=adapter_batch,
    )
    monkeypatch.setattr(wallet, "_wallet_adapter", fake_adapter)
    monkeypatch.setattr(wallet, "_expected_identity_binding", lambda: _binding())
    monkeypatch.setattr(
        wallet, "_expected_identity_authority", lambda: (_binding(), fake_adapter)
    )
    monkeypatch.setattr(
        wallet, "_revalidate_adapter_authority", lambda adapter, operation: None
    )
    monkeypatch.setattr(
        mutation_gate, "enter_wallet_mutation", lambda operation: "permit"
    )
    monkeypatch.setattr(mutation_gate, "exit_wallet_mutation", lambda permit: True)
    monkeypatch.setattr(
        mutation_gate,
        "require_wallet_mutation_permit_authority",
        lambda permit, operation: (_binding(), fake_adapter),
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_fresh_wallet_identity",
        lambda binding, snapshot, operation: (
            authorization_calls.append(operation) or {"allowed": True}
        ),
    )

    result = wallet.cancel_offers_batch(["a" * 64, "b" * 64])

    assert result == {"success": True}
    assert identity_calls == [True, True, True]
    assert authorization_calls == [
        "wallet:cancel_offers_batch",
        "wallet:cancel_offers_batch:first",
        "wallet:cancel_offers_batch:second",
    ]


@pytest.mark.parametrize(
    ("adapter_name", "caller_name", "callee_name"),
    [
        ("wallet_sage", "split_coins_bulk", "split_coins_rpc"),
        ("wallet_sage", "cleanup_expired_offers", "cancel_offer"),
        ("wallet_sage", "cancel_offers_batch", "cancel_offer"),
        ("wallet_sage", "delete_offers_batch", "delete_offer"),
        ("wallet_chia", "split_coins_bulk", "split_coins_rpc"),
        ("wallet_chia", "split_coins_bulk", "send_transaction"),
        ("wallet_chia", "cleanup_expired_offers", "cancel_offer"),
        ("wallet_chia", "cancel_offers_batch", "cancel_offer"),
    ],
)
def test_nested_mutating_adapter_calls_forward_identity_recheck(
    adapter_name, caller_name, callee_name
):
    adapter = __import__(adapter_name)
    caller = ast.parse(inspect.getsource(getattr(adapter, caller_name)))
    calls = [
        node
        for node in ast.walk(caller)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == callee_name
    ]

    assert calls
    assert all(
        any(
            keyword.arg == "_identity_recheck"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "_identity_recheck"
            for keyword in call.keywords
        )
        for call in calls
    )


def test_sage_split_bulk_rechecks_after_nested_signing_read(monkeypatch):
    import wallet_sage

    events = []
    coin_id = "a" * 64
    monkeypatch.setattr(
        wallet_sage,
        "get_spendable_coins_rpc",
        lambda wallet_id: {
            "success": True,
            "confirmed_records": [
                {
                    "coin_id": coin_id,
                    "coin": {"name": coin_id, "amount": 1_000_000},
                    "spent_block_index": 0,
                }
            ],
        },
    )
    monkeypatch.setattr(
        wallet_sage,
        "_require_signing_capability",
        lambda: events.append("signing_read") or True,
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, payload, timeout=10: (
            events.append(f"effect:{endpoint}") or {"success": True}
        ),
    )

    result = wallet_sage.split_coins_bulk(
        wallet_id=1,
        num_coins=2,
        coin_size_mojos=100,
        _identity_recheck=lambda step: events.append(f"check:{step}"),
    )

    assert result["success"] is True
    assert events == [
        "check:split_coins_bulk:split",
        "signing_read",
        "check:split_coins_rpc",
        "effect:split",
    ]


def test_sage_nested_cancel_recheck_block_propagates_before_effect(monkeypatch):
    import wallet_sage

    events = []
    monkeypatch.setattr(wallet_sage, "get_spendable_coin_count", lambda wallet_id: 1)
    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)
    monkeypatch.setattr(
        wallet_sage,
        "_sage_post",
        lambda *args, **kwargs: events.append("effect") or {"success": True},
    )

    def recheck(step):
        events.append(f"check:{step}")
        if step == "cancel_offer":
            raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MISMATCH", step)

    with pytest.raises(mutation_gate.MutationBlocked):
        wallet_sage.cancel_offers_batch(
            ["a" * 64],
            secure=False,
            skip_confirmation=True,
            _identity_recheck=recheck,
        )

    assert events == ["check:cancel_offer:0", "check:cancel_offer"]


def test_chia_nested_cancel_recheck_block_propagates_before_effect(monkeypatch):
    import wallet_chia

    events = []
    monkeypatch.setattr(
        wallet_chia,
        "rpc",
        lambda *args, **kwargs: events.append("effect") or {"success": True},
    )
    monkeypatch.setattr(wallet_chia.time, "sleep", lambda seconds: None)

    def recheck(step):
        events.append(f"check:{step}")
        if step == "cancel_offer":
            raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MISMATCH", step)

    with pytest.raises(mutation_gate.MutationBlocked):
        wallet_chia.cancel_offers_batch(
            ["a" * 64],
            secure=False,
            skip_confirmation=True,
            _identity_recheck=recheck,
        )

    assert events == ["check:cancel_offer:0", "check:cancel_offer"]


def test_chia_multi_send_rechecks_before_each_submission_attempt(monkeypatch):
    import wallet_chia

    events = []

    def rpc(endpoint, payload):
        events.append(endpoint)
        return {"success": len(events) > 3}

    monkeypatch.setattr(wallet_chia, "rpc", rpc)

    result = wallet_chia.send_transaction_multi(
        [{"address": "xch1destination", "amount": 1}],
        _identity_recheck=lambda step: events.append(f"check:{step}"),
    )

    assert result["success"] is True
    assert events == [
        "check:send_transaction_multi:additions",
        "send_transaction_multi",
        "check:send_transaction_multi:payments",
        "send_transaction_multi",
    ]


def test_sage_create_transaction_rechecks_create_sign_and_submit(monkeypatch):
    import wallet_sage

    events = []

    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, payload, timeout=10: (
            events.append(endpoint) or {"coin_spends": [{"coin": "safe"}]}
        ),
    )

    def sage_post(endpoint, payload, timeout=10):
        events.append(endpoint)
        if endpoint == "sign_coin_spends":
            return {"spend_bundle": {"aggregated_signature": "signature"}}
        return {"success": True, "transaction_id": "a" * 64}

    monkeypatch.setattr(wallet_sage, "_sage_post", sage_post)

    result = wallet_sage.create_transaction_rpc(
        ["b" * 64],
        [{"type": "fee", "amount": "0"}],
        _identity_recheck=lambda step: events.append(f"check:{step}"),
    )

    assert result["success"] is True
    assert events == [
        "check:create_transaction",
        "create_transaction",
        "check:create_transaction:sign",
        "sign_coin_spends",
        "check:create_transaction:submit",
        "submit_transaction",
    ]


@pytest.mark.parametrize(
    ("adapter_name", "function_name"),
    [
        ("wallet_sage", "cancel_offers_batch"),
        ("wallet_sage", "cancel_offer"),
        ("wallet_sage", "cleanup_expired_offers"),
        ("wallet_sage", "combine_coins"),
        ("wallet_sage", "create_offer"),
        ("wallet_sage", "delete_offers_batch"),
        ("wallet_sage", "delete_offer"),
        ("wallet_sage", "sage_login"),
        ("wallet_sage", "sage_topup_split"),
        ("wallet_sage", "send_cat_multi"),
        ("wallet_sage", "send_transaction"),
        ("wallet_sage", "send_transaction_multi"),
        ("wallet_sage", "set_change_address"),
        ("wallet_sage", "sign_message_by_address"),
        ("wallet_sage", "split_coins_rpc"),
        ("wallet_sage", "split_coins_bulk"),
        ("wallet_sage", "auto_combine_cat"),
        ("wallet_sage", "auto_combine_xch"),
        ("wallet_chia", "cancel_offers_batch"),
        ("wallet_chia", "cancel_offer"),
        ("wallet_chia", "cleanup_expired_offers"),
        ("wallet_chia", "create_offer"),
        ("wallet_chia", "get_next_address"),
        ("wallet_chia", "send_transaction"),
        ("wallet_chia", "split_coins_rpc"),
        ("wallet_chia", "split_coins_bulk"),
    ],
)
def test_every_compound_adapter_accepts_internal_identity_recheck(
    adapter_name, function_name
):
    adapter = __import__(adapter_name)
    signature = inspect.signature(getattr(adapter, function_name))
    assert "_identity_recheck" in signature.parameters


def test_chia_cancel_batch_rechecks_each_offer(monkeypatch):
    import wallet_chia

    events = []
    monkeypatch.setattr(
        wallet_chia,
        "cancel_offer",
        lambda trade_id, *args, **kwargs: (
            events.append(f"cancel:{trade_id}") or {"success": True}
        ),
    )
    monkeypatch.setattr(wallet_chia.time, "sleep", lambda seconds: None)

    result = wallet_chia.cancel_offers_batch(
        ["offer-1", "offer-2"],
        _identity_recheck=lambda step: events.append(f"check:{step}"),
    )

    assert result["offer-1"]["success"] is True
    assert events == [
        "check:cancel_offer:0",
        "cancel:offer-1",
        "check:cancel_offer:1",
        "cancel:offer-2",
    ]


def test_sage_login_rechecks_before_each_wallet_state_change(monkeypatch):
    import wallet_sage

    events = []

    def rpc(endpoint, payload, timeout=10):
        events.append(endpoint)
        if endpoint == "get_version":
            return {"success": True, "version": "1.2.3"}
        return {"success": True}

    monkeypatch.setattr(wallet_sage, "rpc", rpc)
    monkeypatch.setattr(
        wallet_sage,
        "sage_initialize",
        lambda **kwargs: events.append("initialize") or True,
    )
    monkeypatch.setattr(
        wallet_sage,
        "get_current_key",
        lambda: {"fingerprint": 123456, "name": "expected"},
    )
    monkeypatch.setattr(wallet_sage.time, "sleep", lambda seconds: None)

    result = wallet_sage.sage_login(
        123456,
        force_resync=True,
        _identity_recheck=lambda step: events.append(f"check:{step}"),
    )

    assert result is True
    assert events == [
        "get_version",
        "check:sage_login:initialize",
        "initialize",
        "check:sage_login:resync",
        "resync",
        "check:sage_login:login",
        "login",
    ]


def test_sage_message_signing_rechecks_identity_immediately_before_rpc(monkeypatch):
    import wallet_sage

    events = []
    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)
    monkeypatch.setattr(
        wallet_sage,
        "_validate_address_for_active_network",
        lambda address, **kwargs: address,
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *args, **kwargs: (
            events.append("rpc")
            or {"success": True, "public_key": "pk", "signature": "sig"}
        ),
    )

    result = wallet_sage.sign_message_by_address(
        "xch1safe",
        "message",
        _identity_recheck=lambda step: events.append(f"check:{step}"),
    )

    assert result["success"] is True
    assert events == ["check:sign_message_by_address", "rpc"]


def test_sage_create_offer_rechecks_identity_immediately_before_rpc(monkeypatch):
    import wallet_sage

    events = []
    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)
    monkeypatch.setattr(wallet_sage, "_get_cat_asset_id", lambda: "asset")
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *args, **kwargs: (
            events.append("rpc") or {"success": True, "offer_id": "a" * 64}
        ),
    )

    result = wallet_sage.create_offer(
        {wallet_sage.WALLET_ID_XCH: -1},
        _identity_recheck=lambda step: events.append(f"check:{step}"),
    )

    assert result["success"] is True
    assert events == ["check:create_offer", "rpc"]


def test_wallet_mutation_success_check_does_not_treat_block_dict_as_truthy():
    assert wallet.wallet_mutation_succeeded(True) is True
    assert wallet.wallet_mutation_succeeded({"success": True}) is True
    assert wallet.wallet_mutation_succeeded(False) is False
    assert (
        wallet.wallet_mutation_succeeded(
            {
                "success": False,
                "error": "Wallet mutation blocked by identity safety check",
                "reason": "WALLET_IDENTITY_MISMATCH",
            }
        )
        is False
    )


def test_legacy_batch_and_count_consumers_preserve_structured_denial():
    blocked = {
        "success": False,
        "error": "Wallet mutation blocked by identity safety check",
        "reason": "WALLET_IDENTITY_MISMATCH",
    }

    expanded = wallet.wallet_batch_results(blocked, ["offer-1", "offer-2"])

    assert expanded == {"offer-1": blocked, "offer-2": blocked}
    assert wallet.wallet_mutation_count(blocked) == 0
    assert wallet.wallet_mutation_count(3) == 3


def test_compound_adapter_propagates_identity_block_without_fallback(monkeypatch):
    import wallet_chia

    calls = []
    monkeypatch.setattr(
        wallet_chia,
        "cancel_offer",
        lambda *args, **kwargs: calls.append("cancel") or {"success": True},
    )
    monkeypatch.setattr(wallet_chia.time, "sleep", lambda seconds: None)

    def block(step):
        raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MISMATCH", step)

    with pytest.raises(mutation_gate.MutationBlocked):
        wallet_chia.cancel_offers_batch(["offer-1", "offer-2"], _identity_recheck=block)
    assert calls == []


def test_sage_sign_recheck_block_is_not_converted_to_adapter_error(monkeypatch):
    import wallet_sage

    calls = []
    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *args, **kwargs: {"coin_spends": [{"coin": "safe"}]},
    )
    monkeypatch.setattr(
        wallet_sage,
        "_sage_post",
        lambda *args, **kwargs: calls.append("post") or {"success": True},
    )

    def recheck(step):
        if step.endswith(":sign"):
            raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MISMATCH", step)

    with pytest.raises(mutation_gate.MutationBlocked):
        wallet_sage.create_transaction_rpc(
            ["b" * 64],
            [{"type": "fee", "amount": "0"}],
            _identity_recheck=recheck,
        )
    assert calls == []


def test_adapter_identity_rechecks_are_never_inside_broad_exception_catches():
    root = Path(__file__).resolve().parents[1] / "src" / "catalyst"
    violations = []

    def catches_broad_exception(handler):
        if handler.type is None:
            return True
        caught = (
            handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        )
        return any(
            isinstance(item, ast.Name) and item.id in {"Exception", "BaseException"}
            for item in caught
        )

    for filename in ("wallet_sage.py", "wallet_chia.py"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try) or not any(
                catches_broad_exception(handler) for handler in node.handlers
            ):
                continue
            for statement in node.body:
                for descendant in ast.walk(statement):
                    if (
                        isinstance(descendant, ast.Name)
                        and descendant.id == "_identity_recheck"
                    ):
                        violations.append((filename, descendant.lineno))

    assert violations == []


def test_adapter_identity_timestamps_are_taken_after_rpc(monkeypatch):
    import wallet_sage

    events = []
    monkeypatch.setattr(
        wallet_sage,
        "_identity_now_utc",
        lambda: (
            events.append("clock")
            or datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
        ),
    )
    monkeypatch.setattr(
        wallet_sage,
        "_get_current_key_read_only",
        lambda: (
            events.append("rpc")
            or {
                "name": "Expected Wallet",
                "fingerprint": 123456789,
                "network_id": "mainnet",
                "kind": "bls",
                "has_secrets": True,
            }
        ),
    )

    identity = wallet_sage.get_wallet_identity()

    assert identity["observed_at_utc"] == "2026-08-16T12:00:00.000000Z"
    assert events == ["rpc", "clock"]


def test_sage_identity_failure_never_exposes_raw_exception(monkeypatch):
    import wallet_sage

    monkeypatch.setattr(
        wallet_sage,
        "_get_current_key_read_only",
        lambda: (_ for _ in ()).throw(RuntimeError("seed_phrase=do not expose")),
    )

    identity = wallet_sage.get_wallet_identity()

    assert identity["success"] is False
    assert identity["error"] == "identity_lookup_failed"
    assert "seed_phrase" not in str(identity)


def test_sage_identity_rejects_error_response_even_if_it_contains_a_key(monkeypatch):
    import wallet_sage

    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *args, **kwargs: {
            "success": False,
            "error": "not_logged_in",
            "key": {
                "fingerprint": 123456789,
                "name": "Expected Wallet",
                "network_id": "mainnet",
                "kind": "bls",
                "has_secrets": True,
            },
        },
    )

    identity = wallet_sage.get_wallet_identity()

    assert identity["success"] is False
    assert identity["fingerprint"] is None


def test_sage_signing_guard_never_initializes_or_changes_wallet_state(monkeypatch):
    import wallet_sage

    monkeypatch.setattr(
        wallet_sage,
        "get_current_key",
        lambda: (_ for _ in ()).throw(
            AssertionError("signing guard must not initialize the wallet")
        ),
    )
    monkeypatch.setattr(
        wallet_sage,
        "_get_current_key_read_only",
        lambda: {"has_secrets": True},
    )

    assert wallet_sage._require_signing_capability() is True


def test_chia_identity_timestamp_is_observed_after_rpc(monkeypatch):
    import wallet_chia

    events = []
    monkeypatch.setattr(
        wallet_chia,
        "_identity_now_utc",
        lambda: (
            events.append("clock")
            or datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
        ),
    )
    monkeypatch.setattr(
        wallet_chia,
        "rpc",
        lambda *args, **kwargs: (
            events.append("rpc") or {"success": True, "fingerprint": 123456789}
        ),
    )

    identity = wallet_chia.get_wallet_identity()

    assert identity["observed_at_utc"] == "2026-08-16T12:00:00.000000Z"
    assert events == ["rpc", "clock"]


@pytest.mark.parametrize("adapter_name", ["wallet_sage", "wallet_chia"])
@pytest.mark.parametrize(
    "field_value",
    [True, 123.0, " 123456789", "0123456789", "+123456789"],
)
def test_adapter_identity_rejects_coerced_fingerprints(
    monkeypatch, adapter_name, field_value
):
    adapter = __import__(adapter_name)
    if adapter_name == "wallet_sage":
        monkeypatch.setattr(
            adapter,
            "_get_current_key_read_only",
            lambda: {
                "fingerprint": field_value,
                "name": "Expected Wallet",
                "network_id": "mainnet",
                "kind": "bls",
                "has_secrets": True,
            },
        )
    else:
        monkeypatch.setattr(
            adapter,
            "rpc",
            lambda *args, **kwargs: {"success": True, "fingerprint": field_value},
        )

    identity = adapter.get_wallet_identity()

    assert identity["success"] is False
    assert identity["fingerprint"] is None
    assert identity["error"] == "invalid_fingerprint"


@pytest.mark.parametrize("value", ["true", 1, [], object()])
def test_sage_identity_never_coerces_signing_capability(monkeypatch, value):
    import wallet_sage

    monkeypatch.setattr(
        wallet_sage,
        "_get_current_key_read_only",
        lambda: {
            "fingerprint": 123456789,
            "name": "Expected Wallet",
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": value,
        },
    )

    identity = wallet_sage.get_wallet_identity()

    assert identity["success"] is False
    assert identity["has_secrets"] is None
    assert identity["error"] == "invalid_identity_fields"


def test_api_runtime_builds_exact_binding_without_wallet_rpc(monkeypatch):
    import api_server

    captured = {}
    fake_gate = SimpleNamespace(
        last_acquire_result={"acquired": False},
        register_stop_handler=lambda handler: None,
        status=lambda: mutation_gate.GateStatus(
            allowed=False,
            reason_code="LEASE_OWNED_BY_OTHER",
            source="lease",
        ),
    )
    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_NAME", "Expected Wallet", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 15, raising=False
    )
    monkeypatch.setattr(
        sys.modules["wallet"],
        "get_wallet_identity",
        lambda: (_ for _ in ()).throw(
            AssertionError("startup must not contact wallet")
        ),
    )

    def fake_initialize(**kwargs):
        captured.update(kwargs)
        return fake_gate

    monkeypatch.setattr(api_server.mutation_gate, "initialize", fake_initialize)

    api_server.initialize_mutation_runtime(start_heartbeat=False)

    binding = captured["wallet_identity_binding"]
    assert type(binding) is mutation_gate.WalletIdentityBinding
    assert binding.backend == "sage"
    assert binding.name == "Expected Wallet"
    assert binding.fingerprint == 123456789
    assert binding.network_id == "mainnet"
    assert binding.kind == "bls"
    assert binding.has_secrets is True
    assert binding.maximum_age_seconds == 15


def test_api_signing_preflight_uses_noninitializing_wallet_dispatcher_read(monkeypatch):
    import api_server
    import wallet_sage

    monkeypatch.setattr(api_server, "get_wallet_type", lambda: "sage")
    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: _identity(has_secrets=False),
    )
    monkeypatch.setattr(
        wallet_sage,
        "get_current_key",
        lambda: (_ for _ in ()).throw(
            AssertionError("signing UX preflight must not initialize Sage")
        ),
    )

    assert (
        api_server._get_sage_signing_block_reason()
        == "Active Sage wallet is watch-only and cannot sign offers "
        "(fingerprint 123456789)"
    )
    assert "wallet_sage" not in inspect.getsource(
        api_server._get_sage_signing_block_reason
    )


def test_api_lease_hash_matches_backend_specific_identity_binding(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "chia")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "111111")
    monkeypatch.setattr(api_server.cfg, "WALLET_FINGERPRINT", "222222")
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_NAME", "Expected Wallet", raising=False
    )

    fingerprint_hash, network = api_server._configured_mutation_binding()
    binding = api_server._configured_wallet_identity_binding(network)

    assert binding is not None
    assert binding.fingerprint == 222222
    assert fingerprint_hash == mutation_gate.wallet_fingerprint_hash(222222)


def test_api_refuses_to_build_mutation_binding_without_expected_name(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(api_server.cfg, "WALLET_EXPECTED_NAME", "", raising=False)

    assert api_server._configured_wallet_identity_binding("mainnet") is None


def test_env_template_documents_required_wallet_identity_binding():
    template = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )

    assert "WALLET_EXPECTED_NAME=" in template
    assert "WALLET_EXPECTED_KEY_KIND=bls" in template
    assert "WALLET_IDENTITY_MAX_AGE_SECONDS=10" in template


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("WALLET_TYPE", "unsupported"),
        ("SAGE_FINGERPRINT", 123456789),
        ("WALLET_EXPECTED_NAME", object()),
        ("WALLET_EXPECTED_KEY_KIND", object()),
        ("WALLET_IDENTITY_MAX_AGE_SECONDS", True),
        ("WALLET_IDENTITY_MAX_AGE_SECONDS", 1.5),
    ],
)
def test_api_refuses_malformed_persisted_identity_config(monkeypatch, setting, value):
    import api_server

    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(api_server.cfg, "WALLET_FINGERPRINT", "987654321")
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_NAME", "Expected Wallet", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 15, raising=False
    )
    monkeypatch.setattr(api_server.cfg, setting, value, raising=False)

    assert api_server._configured_wallet_identity_binding("mainnet") is None


def test_owner_runtime_identity_binding_ignores_later_cfg_mutation(monkeypatch):
    frozen = _binding()
    monkeypatch.setattr(
        mutation_gate,
        "current_runtime",
        lambda: SimpleNamespace(
            require_wallet_identity_authority=lambda operation: frozen,
            require_wallet_adapter_authority=lambda candidate, operation: candidate,
        ),
    )

    monkeypatch.setattr(wallet.cfg, "SAGE_FINGERPRINT", "987654321")
    monkeypatch.setattr(
        wallet.cfg, "WALLET_EXPECTED_NAME", "Replacement Wallet", raising=False
    )
    monkeypatch.setattr(
        wallet.cfg, "WALLET_EXPECTED_KEY_KIND", "hostile-kind", raising=False
    )
    monkeypatch.setattr(
        wallet.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 300, raising=False
    )

    assert wallet._expected_identity_binding() is frozen


def test_worker_installs_delegation_for_adapter_bound_rechecks(monkeypatch):
    import coin_prep_worker

    environment = {
        mutation_gate.DELEGATION_ID_ENV: "delegation",
        mutation_gate.DELEGATION_TOKEN_ENV: "token",
        mutation_gate.DELEGATION_PARENT_RUN_ENV: "parent",
        mutation_gate.DELEGATION_OPERATION_ENV: "coin-prep:run-1",
        mutation_gate.DELEGATION_PURPOSE_ENV: "coin_prep",
        mutation_gate.DELEGATION_WORKER_ENV: "coin-prep-worker:run-1",
        mutation_gate.DELEGATION_WALLET_ENV: "a" * 64,
        mutation_gate.DELEGATION_NETWORK_ENV: "mainnet",
        mutation_gate.DELEGATION_IDENTITY_ENV: "{}",
        mutation_gate.DELEGATION_IDENTITY_DIGEST_ENV: "b" * 64,
        mutation_gate.DELEGATION_PARENT_EPOCH_ENV: "2026-08-16T12:00:00Z",
    }
    installed = []
    monkeypatch.setattr(
        coin_prep_worker.mutation_gate,
        "require_worker_allowed_from_environment",
        lambda operation, received: {"allowed": True, "reason": "delegated"},
    )
    monkeypatch.setattr(
        coin_prep_worker.mutation_gate,
        "install_worker_authority_environment",
        lambda received, **kwargs: installed.append((dict(received), kwargs)),
    )

    monkeypatch.setattr(coin_prep_worker, "_worker_delegation_environment", None)
    with monkeypatch.context() as context:
        for key, value in environment.items():
            context.setenv(key, value)
        result = coin_prep_worker._validate_coin_prep_worker_delegation(
            SimpleNamespace(sage_rpc_smoke=False, run_id="run-1")
        )

    assert result["allowed"] is True
    assert installed == [
        (
            environment,
            {"wallet_adapter_authority": wallet.get_wallet_adapter_authority()},
        )
    ]


def test_worker_identity_binding_fails_if_authority_is_cleared_during_recheck(
    monkeypatch,
):
    environment = {
        name: f"value-{index}"
        for index, name in enumerate(mutation_gate._DELEGATION_ENV_NAMES)
    }
    environment[mutation_gate.DELEGATION_NETWORK_ENV] = "mainnet"
    monkeypatch.setattr(
        mutation_gate, "_worker_authority_environment", dict(environment)
    )
    monkeypatch.setattr(
        mutation_gate,
        "_worker_authority_bound_at_utc",
        "2026-08-16T12:00:00.000000Z",
    )
    monkeypatch.setattr(
        mutation_gate,
        "require_worker_allowed_from_environment",
        lambda *args, **kwargs: mutation_gate.clear_worker_authority_environment(),
    )

    assert mutation_gate.worker_identity_lease_binding() is None


@pytest.mark.parametrize("fingerprint", [True, 123.0, "0123", "+123"])
def test_delegated_expected_binding_rejects_ambiguous_fingerprint(
    monkeypatch, fingerprint
):
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet.cfg, "SAGE_FINGERPRINT", fingerprint)
    monkeypatch.setattr(
        mutation_gate,
        "worker_identity_lease_binding",
        lambda: {
            "wallet_fingerprint_hash": "a" * 64,
            "network": "mainnet",
            "bound_at_utc": "2026-08-16T12:00:00.000000Z",
        },
    )

    with pytest.raises(mutation_gate.MutationBlocked) as blocked:
        wallet._expected_identity_binding()
    assert blocked.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


@pytest.mark.parametrize(
    ("setting", "value", "bound_at"),
    [
        ("WALLET_EXPECTED_NAME", object(), "2026-08-16T12:01:01.000000Z"),
        ("WALLET_EXPECTED_KEY_KIND", object(), "2026-08-16T12:01:02.000000Z"),
        ("WALLET_IDENTITY_MAX_AGE_SECONDS", True, "2026-08-16T12:01:03.000000Z"),
        ("WALLET_IDENTITY_MAX_AGE_SECONDS", 1.5, "2026-08-16T12:01:04.000000Z"),
    ],
)
def test_delegated_expected_binding_rejects_malformed_config(
    monkeypatch, setting, value, bound_at
):
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(
        wallet.cfg, "WALLET_EXPECTED_NAME", "Expected Wallet", raising=False
    )
    monkeypatch.setattr(wallet.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False)
    monkeypatch.setattr(
        wallet.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 15, raising=False
    )
    monkeypatch.setattr(wallet.cfg, setting, value, raising=False)
    monkeypatch.setattr(
        mutation_gate,
        "worker_identity_lease_binding",
        lambda: {
            "wallet_fingerprint_hash": mutation_gate.wallet_fingerprint_hash(123456789),
            "network": "mainnet",
            "bound_at_utc": bound_at,
        },
    )

    with pytest.raises(mutation_gate.MutationBlocked) as blocked:
        wallet._expected_identity_binding()
    assert blocked.value.reason_code == "WALLET_IDENTITY_BINDING_INVALID"


def test_delegated_identity_binding_is_frozen_across_cfg_mutation(monkeypatch):
    frozen = _binding(bound_at_utc="2026-08-16T12:02:00.000000Z")
    delegated = {
        "wallet_fingerprint_hash": mutation_gate.wallet_fingerprint_hash(123456789),
        "network": "mainnet",
        "bound_at_utc": "2026-08-16T12:02:00.000000Z",
        "binding": frozen,
        "binding_digest": mutation_gate.wallet_identity_binding_digest(frozen),
        "parent_lease_epoch": "2026-08-16T12:01:59.000000Z",
    }
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(
        mutation_gate, "worker_identity_lease_binding", lambda: dict(delegated)
    )
    monkeypatch.setattr(
        mutation_gate,
        "worker_wallet_adapter_authority",
        lambda candidate, operation: candidate,
    )
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(
        wallet.cfg, "WALLET_EXPECTED_NAME", "Expected Wallet", raising=False
    )
    monkeypatch.setattr(wallet.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False)
    monkeypatch.setattr(
        wallet.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 15, raising=False
    )

    original = wallet._expected_identity_binding()
    monkeypatch.setattr(wallet.cfg, "SAGE_FINGERPRINT", "987654321")
    monkeypatch.setattr(
        wallet.cfg, "WALLET_EXPECTED_NAME", "Replacement Wallet", raising=False
    )
    monkeypatch.setattr(
        wallet.cfg, "WALLET_EXPECTED_KEY_KIND", "hostile-kind", raising=False
    )
    monkeypatch.setattr(
        wallet.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 300, raising=False
    )

    assert wallet._expected_identity_binding() is original
    assert original == frozen


def test_identity_gate_public_api_is_explicitly_exported():
    expected = {
        "WalletIdentityBinding",
        "WalletMutationPermit",
        "clear_worker_authority_environment",
        "enter_wallet_mutation",
        "exit_wallet_mutation",
        "install_worker_authority_environment",
        "require_fresh_wallet_identity",
        "validate_wallet_identity",
        "wallet_fingerprint_hash",
        "worker_identity_lease_binding",
    }

    assert expected <= set(mutation_gate.__all__)


def test_production_workers_do_not_import_mutating_adapter_functions_directly():
    root = Path(__file__).resolve().parents[1] / "src" / "catalyst"
    mutators = {
        "auto_combine_cat",
        "auto_combine_xch",
        "combine_coins",
        "create_transaction_rpc",
        "sage_login",
        "sage_topup_split",
        "send_cat_multi",
        "send_transaction",
        "send_transaction_multi",
        "split_coins_rpc",
    }
    bypasses = []
    for filename in ("coin_manager.py", "coin_prep_worker.py"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "wallet_sage":
                for alias in node.names:
                    if alias.name in mutators:
                        bypasses.append((filename, node.lineno, alias.name))
    assert bypasses == []


def test_all_production_mutator_imports_route_through_wallet_dispatcher():
    root = Path(__file__).resolve().parents[1] / "src" / "catalyst"
    mutators = {
        "auto_combine_cat",
        "auto_combine_xch",
        "cancel_offer",
        "cancel_offers_batch",
        "cleanup_expired_offers",
        "combine_coins",
        "create_offer",
        "create_transaction_rpc",
        "delete_offer",
        "delete_offers_batch",
        "sage_login",
        "sage_topup_split",
        "send_cat_multi",
        "send_transaction",
        "send_transaction_multi",
        "set_change_address",
        "split_coins_bulk",
        "split_coins_rpc",
    }
    bypasses = []
    for path in root.rglob("*.py"):
        if path.name in {"wallet.py", "wallet_sage.py", "wallet_chia.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {
                "wallet_sage",
                "wallet_chia",
            }:
                for alias in node.names:
                    if alias.name in mutators:
                        bypasses.append(
                            (str(path.relative_to(root)), node.lineno, alias.name)
                        )

    assert bypasses == []
