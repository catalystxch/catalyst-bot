"""The original desktop startup must route exact registry recovery narrowly."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


def _desktop(monkeypatch):
    original_platform = sys.platform
    monkeypatch.setattr(sys, "platform", "linux")
    sys.modules.pop("desktop_app", None)
    module = importlib.import_module("desktop_app")
    monkeypatch.setattr(sys, "platform", original_platform)
    return module


def test_registry_blocked_desktop_attempts_only_restricted_recovery(monkeypatch):
    import api_server
    import database
    import read_only_diagnostics

    desktop = _desktop(monkeypatch)
    events: list[str] = []
    denied = {"allowed": False, "reason_code": "REGISTRY_BLOCKED"}

    class Arbiter:
        acquired = True

        def release(self):
            events.append("arbiter_released")

    monkeypatch.setattr(read_only_diagnostics, "acquire_startup_arbiter", Arbiter)
    monkeypatch.setattr(
        read_only_diagnostics, "preflight_requires_diagnostics", lambda: False
    )
    monkeypatch.setattr(desktop, "_acquire_instance_lock", lambda: True)
    monkeypatch.setattr(database, "attempt_db_recovery", lambda: {"action": "ok"})
    monkeypatch.setattr(desktop, "_initialize_startup_ownership", lambda: denied)
    monkeypatch.setattr(
        api_server,
        "activate_registry_terminal_restricted_startup",
        lambda authorization: events.append("registry_recovery") or True,
        raising=False,
    )
    monkeypatch.setattr(
        api_server,
        "activate_wallet_setup_bootstrap",
        lambda authorization: events.append("generic_bootstrap") or False,
    )

    assert desktop._authorize_desktop_startup() is True
    assert events == ["registry_recovery", "arbiter_released"]


def test_registry_recovery_window_has_no_trading_bridge(monkeypatch):
    import api_server

    desktop = _desktop(monkeypatch)
    monkeypatch.setattr(
        api_server, "_registry_terminal_recovery_active", True, raising=False
    )
    assert desktop._create_desktop_bridge() is None


def test_registry_recovery_http_denies_normal_trading_and_refresh_abort(monkeypatch):
    import api_server

    monkeypatch.setattr(
        api_server, "_registry_terminal_recovery_active", True, raising=False
    )
    for method, path in (
        ("GET", "/api/offers"),
        ("POST", "/api/bot/start"),
        ("POST", "/api/bootstrap/start"),
        ("POST", "/api/offers/refresh_abort/fee_approval"),
        ("POST", "/api/offers/refresh_abort/cancel_next"),
    ):
        with api_server.app.test_request_context(
            path, method=method, environ_base={"REMOTE_ADDR": "127.0.0.1"}
        ):
            response = api_server.enforce_local_runtime_guard()
            assert response is not None, (method, path)
            assert response[1] == 423, (method, path)
            assert response[0].get_json()["error"] == "registry_terminal_recovery_only"


def test_registry_recovery_cannot_show_normal_dashboard(monkeypatch):
    import api_server

    monkeypatch.setattr(
        api_server, "_registry_terminal_recovery_active", True, raising=False
    )
    with api_server.app.test_request_context(
        "/", headers={api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}
    ):
        response = api_server.serve_gui()
    assert response.status_code == 503
    assert b"Bot" not in response.data


@pytest.mark.parametrize(
    "change",
    ["valid", "extra_blocker", "wrong_asset", "not_elapsed", "other_campaign"],
)
def test_registry_startup_candidate_requires_exact_elapsed_cohort(monkeypatch, change):
    import api_server
    import database
    import mutation_gate

    campaign_id = "a" * 64
    asset_id = "b" * 64
    intent_id = "c" * 64
    wallet_hash = mutation_gate.wallet_fingerprint_hash(3702373391)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    campaign = {
        "campaign_id": campaign_id,
        "status": "active",
        "asset_id": asset_id,
        "network": "mainnet",
        "wallet_fingerprint": 3702373391,
        "wallet_id": 2,
        "revision": 0,
        "expires_at": future if change == "not_elapsed" else expired,
    }
    intent = {
        "intent_id": intent_id,
        "wallet_fingerprint_hash": wallet_hash,
        "network": "mainnet",
        "asset_id": "d" * 64 if change == "wrong_asset" else asset_id,
        "purpose": f"bootstrap:{campaign_id}:revision:0",
        "lifecycle_state": "unknown",
        "sage_trade_id": "e" * 64,
        "parent_intent_id": None,
        "child_intent_id": None,
    }
    blockers = [f"reconcile:{intent_id}"]
    if change == "extra_blocker":
        blockers.append("create:other")
    latch = {
        "state": "tripped",
        "reason_code": "REGISTRY_BLOCKED",
        "generation": 150,
        "wallet_fingerprint_hash": wallet_hash,
        "network": "mainnet",
        "blocking_operation_ids_json": json.dumps(blockers),
    }
    monkeypatch.setattr(
        api_server,
        "cfg",
        SimpleNamespace(
            WALLET_TYPE="sage", CAT_ASSET_ID=asset_id, SAGE_FINGERPRINT="3702373391"
        ),
    )
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: (wallet_hash, "mainnet")
    )
    monkeypatch.setattr(
        database,
        "get_active_bootstrap_campaign",
        lambda *_args: campaign,
    )
    monkeypatch.setattr(
        database,
        "list_active_bootstrap_campaigns_for_asset",
        lambda *_args: (
            [campaign, dict(campaign, campaign_id="f" * 64)]
            if change == "other_campaign"
            else [campaign]
        ),
    )
    monkeypatch.setattr(database, "get_offer_intents_for_registry", lambda: [intent])
    monkeypatch.setattr(database, "get_runtime_safety_latch", lambda: latch)
    monkeypatch.setattr(
        database,
        "get_runtime_mutation_lease",
        lambda: {"active": 0, "lease_version": 1},
    )
    monkeypatch.setattr(
        database,
        "get_unresolved_offer_operation_blockers",
        lambda: [{"operation_id": value} for value in blockers],
    )

    result = api_server.has_exact_registry_terminal_startup_candidate()
    assert result is (change == "valid")


@pytest.mark.parametrize("change", ["valid", "pending", "book_changed", "stale"])
def test_registry_startup_preflight_requires_two_stable_sage_reads(monkeypatch, change):
    import api_server
    import mutation_gate

    asset_id = "b" * 64
    campaign_id = "a" * 64
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Harvestr",
        fingerprint=3702373391,
        network_id="mainnet",
        kind="private",
        has_secrets=True,
        bound_at_utc=datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=60,
    )
    monkeypatch.setattr(
        api_server, "cfg", SimpleNamespace(WALLET_TYPE="sage", CAT_ASSET_ID=asset_id)
    )
    monkeypatch.setattr(
        api_server,
        "has_exact_registry_terminal_startup_candidate",
        lambda **_kw: True,
        raising=False,
    )
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: (mutation_gate.wallet_fingerprint_hash(3702373391), "mainnet"),
    )
    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", lambda _net: binding
    )
    monkeypatch.setattr(
        api_server, "_read_distinct_wallet_identity_snapshots", lambda _read: ({}, {})
    )
    monkeypatch.setattr(api_server.wallet, "get_wallet_identity", lambda: {})
    first_at = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    second_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    identity_times = iter([first_at, second_at])
    monkeypatch.setattr(
        mutation_gate,
        "validate_wallet_identity",
        lambda *_args, **_kw: {
            "allowed": True,
            "observed_at_utc": next(identity_times),
        },
    )
    book_times = [
        (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat(),
        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    ]
    if change == "stale":
        book_times[1] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    books = iter(
        [
            {
                "trade_ids": [],
                "pending_transaction_ids": [],
                "observed_at": book_times[0],
            },
            {
                "trade_ids": ["e" * 64] if change == "book_changed" else [],
                "pending_transaction_ids": ["f" * 64] if change == "pending" else [],
                "observed_at": book_times[1],
            },
        ]
    )
    monkeypatch.setattr(
        api_server.wallet, "_read_refresh_abort_cleanup_snapshot", lambda: next(books)
    )
    monkeypatch.setattr(
        api_server.database,
        "get_active_bootstrap_campaign",
        lambda *_args: {"campaign_id": campaign_id, "revision": 0},
    )
    monkeypatch.setattr(
        api_server.database,
        "get_runtime_safety_latch",
        lambda: {"generation": 150, "blocking_operation_ids_json": "[]"},
    )

    result = api_server.preflight_registry_terminal_restricted_startup()
    assert result["eligible"] is (change == "valid")
    if change == "valid":
        assert result["campaign_id"] == campaign_id
        assert result["revision"] == 0
        assert result["latch_generation"] == 150
