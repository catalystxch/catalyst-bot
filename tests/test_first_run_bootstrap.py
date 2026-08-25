"""Regression coverage for the packaged Windows first-launch bootstrap."""

from __future__ import annotations

import importlib
import sys
import threading
from types import SimpleNamespace


def _import_desktop_app(monkeypatch):
    """Import without letting Windows stream setup detach pytest capture."""

    original_platform = sys.platform
    monkeypatch.setattr(sys, "platform", "linux")
    sys.modules.pop("desktop_app", None)
    module = importlib.import_module("desktop_app")
    monkeypatch.setattr(sys, "platform", original_platform)
    return module


def _unconfigured_authorization() -> dict:
    return {
        "allowed": False,
        "reason_code": "WALLET_IDENTITY_BINDING_INVALID",
        "failed_check": "wallet_identity_freshness",
        "checks": [
            {
                "name": "lease",
                "ok": True,
                "reason_code": "",
                "source": "durable_snapshot",
            },
            {
                "name": "wallet_identity_freshness",
                "ok": False,
                "reason_code": "WALLET_IDENTITY_BINDING_INVALID",
                "source": "configured_binding",
            },
        ],
    }


def _clean_snapshot() -> dict:
    return {
        "lease": {"active": 0},
        "latch": {"state": "resolved"},
        "blockers": [],
        "reservation_issues": [],
        "publication_issues": [],
        "blocker_counts": {
            "operations": 0,
            "prepared_creations": 0,
            "submitted_cancels": 0,
            "contradictory_history": 0,
            "reservations": 0,
            "publication_claims": 0,
        },
    }


def test_unconfigured_clean_install_enters_desktop_bootstrap_instead_of_json(
    monkeypatch,
):
    import api_server
    import read_only_diagnostics

    desktop_app = _import_desktop_app(monkeypatch)
    events = []

    class Arbiter:
        acquired = True

        def release(self):
            events.append("arbiter_release")

    monkeypatch.setattr(read_only_diagnostics, "acquire_startup_arbiter", Arbiter)
    monkeypatch.setattr(
        read_only_diagnostics, "preflight_requires_diagnostics", lambda: False
    )
    monkeypatch.setattr(desktop_app, "_acquire_instance_lock", lambda: True)
    monkeypatch.setattr(
        desktop_app, "_initialize_startup_ownership", _unconfigured_authorization
    )
    monkeypatch.setattr(
        api_server,
        "activate_wallet_setup_bootstrap",
        lambda authorization: events.append(("bootstrap", authorization)) or True,
        raising=False,
    )

    assert desktop_app._authorize_desktop_startup() is True
    assert events == [
        ("bootstrap", _unconfigured_authorization()),
        "arbiter_release",
    ]


def test_bootstrap_candidate_requires_unconfigured_identity_and_clean_durable_state(
    monkeypatch,
):
    import api_server

    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", lambda _network: None
    )
    monkeypatch.setattr(
        api_server.database,
        "get_stability_startup_recovery_snapshot",
        _clean_snapshot,
    )

    assert api_server.activate_wallet_setup_bootstrap(_unconfigured_authorization())
    assert api_server.wallet_setup_bootstrap_active() is True

    api_server.deactivate_wallet_setup_bootstrap()
    blocked = _clean_snapshot()
    blocked["blockers"] = [{"operation_id": "create:unknown"}]
    blocked["blocker_counts"]["operations"] = 1
    monkeypatch.setattr(
        api_server.database,
        "get_stability_startup_recovery_snapshot",
        lambda: blocked,
    )

    assert (
        api_server.activate_wallet_setup_bootstrap(_unconfigured_authorization())
        is False
    )
    assert api_server.wallet_setup_bootstrap_active() is False


def test_bootstrap_allows_only_wallet_setup_operations(monkeypatch):
    import api_server

    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", lambda _network: None
    )
    monkeypatch.setattr(
        api_server.database,
        "get_stability_startup_recovery_snapshot",
        _clean_snapshot,
    )
    assert api_server.activate_wallet_setup_bootstrap(_unconfigured_authorization())

    assert api_server.wallet_setup_bootstrap_allows("api:sage.api_wallet_begin_startup")
    assert api_server.wallet_setup_bootstrap_allows("app_bridge:set_sage_fingerprint")
    assert not api_server.wallet_setup_bootstrap_allows("api:bot.api_bot_start")
    assert not api_server.wallet_setup_bootstrap_allows("app_bridge:trigger_coin_prep")

    api_server.deactivate_wallet_setup_bootstrap()


def test_bootstrap_fingerprint_binds_exact_sage_identity_before_promotion(monkeypatch):
    import api_server
    import chia_node
    from blueprints import sage

    calls = []
    monkeypatch.setattr(api_server, "_wallet_setup_bootstrap_active", True)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(
        chia_node,
        "get_available_wallet_identities",
        lambda: [
            {
                "backend": "sage",
                "fingerprint": "736588221",
                "name": "TEST 7",
                "kind": "bls",
                "has_secrets": True,
                "network_id": "mainnet",
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        type(api_server.cfg),
        "bind_wallet_identity",
        lambda _self, **identity: calls.append(("bind", identity)) or True,
    )
    monkeypatch.setattr(
        api_server,
        "promote_wallet_setup_bootstrap",
        lambda: calls.append(("promote",)) or {"allowed": True},
        raising=False,
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "enter_mutation",
        lambda operation: calls.append(("permit", operation)) or "permit",
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "exit_mutation",
        lambda permit: calls.append(("exit", permit)),
    )
    monkeypatch.setattr(
        chia_node,
        "trigger_start",
        lambda fingerprint: calls.append(("start", fingerprint)) or {"success": True},
    )

    with api_server.app.test_request_context(
        "/api/sage/fingerprint",
        method="POST",
        json={"fingerprint": "736588221"},
    ):
        response = sage.api_sage_set_fingerprint()

    body = response.get_json()
    assert body["success"] is True
    assert body["fingerprint"] == "736588221"
    assert calls == [
        (
            "bind",
            {
                "backend": "sage",
                "fingerprint": "736588221",
                "name": "TEST 7",
                "kind": "bls",
                "network_id": "mainnet",
            },
        ),
        ("promote",),
        ("permit", "api:sage.bootstrap_wallet_selection"),
        ("start", "736588221"),
        ("exit", "permit"),
    ]


def test_bootstrap_server_skips_bot_construction_until_identity_is_bound(monkeypatch):
    import api_server
    import database

    desktop_app = _import_desktop_app(monkeypatch)
    calls = []
    reservation = SimpleNamespace()
    monkeypatch.setattr(api_server, "wallet_setup_bootstrap_active", lambda: True)
    monkeypatch.setattr(database, "init_database", lambda: calls.append("database"))
    monkeypatch.setattr(
        api_server,
        "create_bot",
        lambda: (_ for _ in ()).throw(
            AssertionError("bootstrap must not construct the trading bot")
        ),
    )
    monkeypatch.setattr(
        api_server, "_serve_flask_app_on_reservation", lambda value: calls.append(value)
    )
    monkeypatch.setattr(database, "log_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        api_server, "_restore_run_history_cutoff_from_events", lambda: None
    )

    desktop_app.start_flask_server(reservation)

    assert calls == ["database", reservation]


def test_first_run_identity_binding_is_persisted_atomically(monkeypatch, tmp_path):
    import config
    import database

    env_path = tmp_path / ".env"
    env_path.write_text(
        "WALLET_TYPE=sage\nSAGE_FINGERPRINT=\nWALLET_EXPECTED_NAME=\n"
        "WALLET_EXPECTED_KEY_KIND=bls\n",
        encoding="utf-8",
    )
    instance = object.__new__(config.Config)
    instance._lock = threading.RLock()
    instance.WALLET_TYPE = "sage"
    instance.SAGE_FINGERPRINT = ""
    instance.WALLET_EXPECTED_NAME = ""
    instance.WALLET_EXPECTED_KEY_KIND = "bls"
    reloads = []

    monkeypatch.setattr(config, "_ENV_PATH", str(env_path))
    monkeypatch.setattr(config, "_restrict_env_file_permissions", lambda _path: None)
    monkeypatch.setattr(instance, "reload", lambda: reloads.append(True))
    monkeypatch.setattr(
        database, "record_config_change", lambda *_args, **_kwargs: None
    )
    monkeypatch.setenv("CATALYST_NETWORK_ID", "mainnet")
    for key in (
        "SAGE_FINGERPRINT",
        "WALLET_EXPECTED_NAME",
        "WALLET_EXPECTED_KEY_KIND",
    ):
        monkeypatch.setenv(key, "")

    assert instance.bind_wallet_identity(
        backend="sage",
        fingerprint="736588221",
        name="TEST 7",
        kind="BLS",
        network_id="mainnet",
    )

    persisted = env_path.read_text(encoding="utf-8")
    assert "SAGE_FINGERPRINT='736588221'" in persisted
    assert "WALLET_EXPECTED_NAME='TEST 7'" in persisted
    assert "WALLET_EXPECTED_KEY_KIND='bls'" in persisted
    assert reloads == [True]
    assert list(tmp_path.glob("*.tmp")) == []


def test_first_run_identity_list_excludes_watch_only_or_incomplete_keys(monkeypatch):
    import sage_node
    import wallet_sage

    monkeypatch.setenv("WALLET_TYPE", "sage")
    monkeypatch.setattr(
        wallet_sage,
        "get_sage_keys",
        lambda: [
            {
                "fingerprint": 736588221,
                "name": "TEST 7",
                "kind": "BLS",
                "has_secrets": True,
                "network_id": "mainnet",
            },
            {
                "fingerprint": 123,
                "name": "Watch only",
                "kind": "BLS",
                "has_secrets": False,
                "network_id": "mainnet",
            },
            {
                "fingerprint": 456,
                "name": "Missing network",
                "kind": "BLS",
                "has_secrets": True,
            },
        ],
    )

    assert sage_node.get_available_wallet_identities() == [
        {
            "backend": "sage",
            "fingerprint": "736588221",
            "name": "TEST 7",
            "kind": "bls",
            "has_secrets": True,
            "network_id": "mainnet",
        }
    ]
