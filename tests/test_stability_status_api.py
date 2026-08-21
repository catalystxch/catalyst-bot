import json
from types import SimpleNamespace


def _gate_status(*, allowed=False, reason_code="UNRESOLVED_OPERATIONS"):
    return {
        "allowed": allowed,
        "reason_code": reason_code,
        "source": "operation_journal" if not allowed else "lease",
        "latch_generation": 7,
        "blocking_operation_ids": ["operation-secret-id"],
        "blocking_operation_count": 1,
        "lease": {
            "active": True,
            "version": 9,
            "expires_at": "2026-08-21T12:00:30.000000Z",
            "owner_run_id": "raw-owner-run-id",
            "owner_pid": 4321,
            "owned_by_this_run": allowed,
        },
    }


def _startup_status(*, allowed=False, reason_code="UNRESOLVED_OPERATIONS"):
    return {
        **_gate_status(allowed=allowed, reason_code=reason_code),
        "source": "startup_recovery",
        "failed_check": None if allowed else "unresolved_operations",
        "blocker_counts": {
            "operations": 3,
            "prepared_creations": 1,
            "submitted_cancels": 1,
            "contradictory_history": 1,
            "reservations": 0,
            "publication_claims": 0,
        },
        "checks": [
            {
                "name": "lease",
                "ok": True,
                "reason_code": "",
                "source_age_seconds": 2,
                "blocker_counts": {},
            },
            {
                "name": "wallet_identity_freshness",
                "ok": True,
                "reason_code": "",
                "source_age_seconds": 4,
                "blocker_counts": {},
            },
            {
                "name": "unresolved_operations",
                "ok": allowed,
                "reason_code": "" if allowed else reason_code,
                "source_age_seconds": 6,
                "blocker_counts": {},
            },
        ],
    }


def _install_diagnostic_counts(monkeypatch, api_server):
    counts = {
        "registry": 8,
        "lineage": 3,
        "reserve": 11,
        "publication": 6,
    }
    monkeypatch.setattr(api_server.database, "DB_PATH", __file__)
    monkeypatch.setattr(
        api_server.database,
        "get_stability_diagnostic_counts",
        lambda: dict(counts),
    )
    return counts


def test_safety_status_contract_is_actionable_bounded_and_redacted(monkeypatch):
    import api_server

    expected_counts = _install_diagnostic_counts(monkeypatch, api_server)
    monkeypatch.setattr(
        api_server,
        "_stability_startup_status",
        _startup_status(),
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "status",
        lambda: SimpleNamespace(to_dict=lambda: _gate_status()),
    )
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: ("f" * 64, "mainnet"),
    )

    response = api_server.app.test_client().get("/api/safety/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"success", "safety"}
    assert payload["success"] is True
    safety = payload["safety"]
    assert set(safety) == {
        "allowed",
        "reason_code",
        "source",
        "blocking_operation_count",
        "blocker_counts",
        "identity",
        "lease",
        "source_ages_seconds",
        "recommended_action",
        "recovery",
    }
    assert safety["allowed"] is False
    assert safety["reason_code"] == "UNRESOLVED_OPERATIONS"
    assert safety["blocker_counts"] == {
        "operations": 3,
        "prepared_creations": 1,
        "submitted_cancels": 1,
        "contradictory_history": 1,
        "reservations": 0,
        "publication_claims": 0,
    }
    assert safety["identity"] == {
        "wallet_fingerprint": "sha256:ffffffffffff…",
        "network": "mainnet",
        "lease_owner": "other_run",
    }
    assert safety["source_ages_seconds"] == {
        "lease": 2,
        "wallet_identity_freshness": 4,
        "unresolved_operations": 6,
        "reservations": None,
        "publication_claims": None,
        "authority_revalidation": None,
    }
    assert safety["recommended_action"] == "RUN_AUTHORITATIVE_RECONCILIATION"
    assert safety["recovery"]["failed_check"] == "unresolved_operations"
    assert safety["recovery"]["freshness"] == {
        "age_seconds": 6,
        "provenance": "durable_snapshot",
    }
    assert safety["recovery"]["durable_counts"] == expected_counts
    assert safety["lease"]["owner"] == "other_run"
    assert [item["name"] for item in safety["recovery"]["checks"]] == [
        "lease",
        "wallet_identity_freshness",
        "unresolved_operations",
    ]
    serialized = json.dumps(payload, sort_keys=True)
    assert "raw-owner-run-id" not in serialized
    assert "operation-secret-id" not in serialized
    assert "4321" not in serialized
    assert "f" * 64 not in serialized


def test_clean_safety_status_recommends_no_operator_action(monkeypatch):
    import api_server

    expected_counts = _install_diagnostic_counts(monkeypatch, api_server)
    monkeypatch.setattr(
        api_server,
        "_stability_startup_status",
        _startup_status(allowed=True, reason_code=""),
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "status",
        lambda: SimpleNamespace(
            to_dict=lambda: _gate_status(allowed=True, reason_code="")
        ),
    )
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: ("a" * 64, "testnet11"),
    )

    payload = api_server.app.test_client().get("/api/safety/status").get_json()

    assert payload["safety"]["allowed"] is True
    assert payload["safety"]["reason_code"] == ""
    assert payload["safety"]["recommended_action"] == "NONE"
    assert payload["safety"]["identity"]["lease_owner"] == "this_run"
    assert payload["safety"]["lease"]["owner"] == "this_run"
    assert payload["safety"]["recovery"]["durable_counts"] == expected_counts


def test_app_bridge_safety_status_matches_api_exactly(monkeypatch):
    import api_server
    import app_bridge

    _install_diagnostic_counts(monkeypatch, api_server)
    monkeypatch.setattr(api_server, "_stability_startup_status", _startup_status())
    monkeypatch.setattr(
        api_server.mutation_gate,
        "status",
        lambda: SimpleNamespace(to_dict=lambda: _gate_status()),
    )
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: ("b" * 64, "mainnet"),
    )
    expected = api_server.app.test_client().get("/api/safety/status").get_json()

    result = app_bridge.AppBridge().get_safety_status()

    assert type(result) is dict
    assert result == expected


def test_app_bridge_safety_status_never_raises(monkeypatch):
    import api_server
    import app_bridge

    def fail():
        raise RuntimeError("secret database path")

    monkeypatch.setattr(api_server, "api_safety_status", fail)

    result = app_bridge.AppBridge().get_safety_status()

    assert result == {
        "success": False,
        "error": "Internal error — check bot logs for details",
    }


def test_safety_status_api_fails_closed_when_live_gate_read_raises(monkeypatch):
    import api_server

    monkeypatch.setattr(
        api_server.mutation_gate,
        "status",
        lambda: (_ for _ in ()).throw(RuntimeError("secret database path")),
    )

    response = api_server.app.test_client().get("/api/safety/status")

    assert response.status_code == 503
    assert response.get_json() == {
        "success": False,
        "error": "safety_status_unavailable",
        "safety": {
            "allowed": False,
            "reason_code": "DURABLE_STATE_UNAVAILABLE",
            "recommended_action": "RESTORE_DATABASE_BACKUP",
        },
    }
