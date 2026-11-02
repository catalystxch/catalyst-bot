"""Deferred mixed-recovery hooks require restored normal authority."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest


def test_deferred_hook_drain_requires_fresh_resolved_proof(monkeypatch):
    import api_server
    import database
    import mixed_terminal_recovery
    import mutation_gate
    import offer_reconciliation

    reviewed = {"campaign_id": "a" * 64, "revision": 0, "proof_digest": "d" * 64}
    proof = {
        **reviewed,
        "offers": [{"intent_id": "b" * 64, "classification": "FILLED_PROVEN"}],
    }
    roots = [{"intent_id": "b" * 64, "lifecycle_state": "terminal"}]
    calls = []
    authority = SimpleNamespace(
        status=lambda: SimpleNamespace(
            to_dict=lambda: {"allowed": True, "lease": {"owned_by_this_run": True}}
        )
    )
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", False)

    @contextmanager
    def verified(*_args):
        calls.append("prove")
        yield proof, {}, roots, "2026-10-18T09:00:00Z"

    monkeypatch.setattr(mixed_terminal_recovery, "_verified_terminal_proof", verified)
    monkeypatch.setattr(
        database,
        "get_runtime_safety_latch",
        lambda: {"state": "resolved", "blocking_operation_ids_json": "[]"},
    )
    monkeypatch.setattr(
        database,
        "get_campaign_deferred_fill_hook_ids",
        lambda campaign_id, revision: calls.append((campaign_id, revision)) or [17],
        raising=False,
    )
    monkeypatch.setattr(
        database,
        "get_authoritative_fill_by_id",
        lambda fill_id: {
            "fill_id": fill_id,
            "intent_id": "b" * 64,
            "filled_at": "2026-10-18T09:00:00Z",
        },
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "_run_post_fill_hooks",
        lambda fill, completed_at, authority_check: (
            authority_check()
            or authority_check()
            or calls.append((fill["fill_id"], completed_at))
            or {"offer_filled_event": "completed"}
        ),
    )
    with pytest.raises(ValueError, match="reviewed proof changed"):
        mixed_terminal_recovery.drain_deferred_terminal_hooks(reviewed, authority)
    assert calls == ["prove"]
    result = mixed_terminal_recovery.drain_deferred_terminal_hooks(proof, authority)
    assert result["fill_ids"] == [17]
    assert result["hooks"][17]["offer_filled_event"] == "completed"
    assert calls == [
        "prove",
        "prove",
        ("a" * 64, 0),
        (17, "2026-10-18T09:00:00Z"),
    ]


def test_deferred_hook_drain_refuses_tripped_latch(monkeypatch):
    import database
    import mixed_terminal_recovery

    proof = {"campaign_id": "a" * 64, "revision": 0, "offers": []}

    @contextmanager
    def verified(*_args):
        yield proof, {}, [], "2026-10-18T09:00:00Z"

    monkeypatch.setattr(mixed_terminal_recovery, "_verified_terminal_proof", verified)
    monkeypatch.setattr(
        database, "get_runtime_safety_latch", lambda: {"state": "tripped"}
    )
    with pytest.raises(ValueError, match="normal authority"):
        mixed_terminal_recovery.drain_deferred_terminal_hooks(proof, object())


def test_deferred_hook_drain_refuses_lost_normal_authority(monkeypatch):
    import api_server
    import database
    import mixed_terminal_recovery
    import mutation_gate
    import offer_reconciliation

    proof = {
        "campaign_id": "a" * 64,
        "revision": 0,
        "offers": [{"intent_id": "b" * 64, "classification": "FILLED_PROVEN"}],
    }
    authority = SimpleNamespace(
        status=lambda: SimpleNamespace(
            to_dict=lambda: {"allowed": False, "lease": {"owned_by_this_run": True}}
        )
    )
    calls = []

    @contextmanager
    def verified(*_args):
        yield proof, {}, [{"intent_id": "b" * 64, "lifecycle_state": "terminal"}], None

    monkeypatch.setattr(mixed_terminal_recovery, "_verified_terminal_proof", verified)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", False)
    monkeypatch.setattr(
        database,
        "get_runtime_safety_latch",
        lambda: {"state": "resolved", "blocking_operation_ids_json": "[]"},
    )
    monkeypatch.setattr(
        database,
        "get_campaign_deferred_fill_hook_ids",
        lambda *_args: calls.append("list") or [17],
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "_run_post_fill_hooks",
        lambda *_args, **_kwargs: calls.append("deliver"),
    )
    with pytest.raises(ValueError, match="normal authority"):
        mixed_terminal_recovery.drain_deferred_terminal_hooks(proof, authority)
    assert calls == []


def test_deferred_hook_drain_blocks_lost_fill_receipt(monkeypatch):
    import api_server
    import database
    import mixed_terminal_recovery
    import mutation_gate
    import offer_reconciliation

    proof = {
        "campaign_id": "a" * 64,
        "revision": 0,
        "offers": [{"intent_id": "b" * 64, "classification": "FILLED_PROVEN"}],
    }
    authority = SimpleNamespace(
        status=lambda: SimpleNamespace(
            to_dict=lambda: {"allowed": True, "lease": {"owned_by_this_run": True}}
        )
    )
    calls = []

    @contextmanager
    def verified(*_args):
        yield proof, {}, [{"intent_id": "b" * 64, "lifecycle_state": "terminal"}], None

    monkeypatch.setattr(mixed_terminal_recovery, "_verified_terminal_proof", verified)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", False)
    monkeypatch.setattr(
        database,
        "get_runtime_safety_latch",
        lambda: {"state": "resolved", "blocking_operation_ids_json": "[]"},
    )
    monkeypatch.setattr(
        database, "get_campaign_deferred_fill_hook_ids", lambda *_: [17]
    )
    monkeypatch.setattr(database, "get_authoritative_fill_by_id", lambda *_: None)
    monkeypatch.setattr(
        database,
        "block_offer_fill_hook_authority_loss",
        lambda fill_id: calls.append(fill_id),
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "_run_post_fill_hooks",
        lambda *_args, **_kwargs: calls.append("delivered"),
    )
    with pytest.raises(ValueError, match="fill hook authority is missing"):
        mixed_terminal_recovery.drain_deferred_terminal_hooks(proof, authority)
    assert calls == [17]


def test_campaign_deferred_hook_selector_empty_database(tmp_path, monkeypatch):
    import database

    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "deferred-hooks.db"))
    database._db_initialized = False
    database._db_initialized_path = None
    database.init_database()
    assert database.get_campaign_deferred_fill_hook_ids("a" * 64, 0) == []
    with pytest.raises(ValueError):
        database.get_campaign_deferred_fill_hook_ids("bad", 0)
    database.close_connection()


def test_deferred_hook_http_is_normal_only_and_token_guarded(monkeypatch):
    import api_server
    import mixed_terminal_recovery
    import mutation_gate

    authority = object()
    proof = {"campaign_id": "a" * 64, "revision": 0, "proof_digest": "d" * 64}
    calls = []
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(
        mixed_terminal_recovery,
        "drain_deferred_terminal_hooks",
        lambda reviewed, runtime: calls.append((reviewed, runtime)) or {"fill_ids": []},
    )
    client = api_server.app.test_client()
    path = "/api/bootstrap/drain_terminal_hooks"
    headers = {api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", True)
    assert (
        client.post(path, json={"reviewed": proof}, headers=headers).status_code == 423
    )
    assert calls == []
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", False)
    assert client.post(path, json={"reviewed": proof}).status_code == 401
    assert (
        client.post(path, json={"reviewed": proof}, headers=headers).status_code == 200
    )
    assert calls == [(proof, authority)]


def test_deferred_hook_native_bridge_calls_same_service(monkeypatch):
    import app_bridge
    import mixed_terminal_recovery
    import mutation_gate

    authority = object()
    proof = {"campaign_id": "a" * 64, "revision": 0, "proof_digest": "d" * 64}
    calls = []
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(
        mixed_terminal_recovery,
        "drain_deferred_terminal_hooks",
        lambda reviewed, runtime: calls.append((reviewed, runtime)) or {"fill_ids": []},
    )
    result = app_bridge.AppBridge().drain_deferred_terminal_hooks({"reviewed": proof})
    assert result["success"] is True
    assert calls == [(proof, authority)]
    assert "drain_deferred_terminal_hooks" in app_bridge._APP_BRIDGE_CONTROL_METHODS
