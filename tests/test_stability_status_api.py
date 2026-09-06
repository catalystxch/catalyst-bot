import json
from datetime import datetime, timedelta, timezone
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

    class _TimestampContainingPidDigits(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime.now(tz)
            if current.microsecond < 432100:
                current -= timedelta(seconds=1)
            return current.replace(microsecond=432100)

    # Keep the output timestamp realistic while proving that coincidental PID
    # digits inside an unrelated string do not make this redaction test flaky.
    monkeypatch.setattr(api_server, "datetime", _TimestampContainingPidDigits)

    expected_counts = _install_diagnostic_counts(monkeypatch, api_server)
    monkeypatch.setattr(
        api_server,
        "_stability_startup_status",
        _startup_status(),
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "read_only_status",
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
    freshness = safety["recovery"]["freshness"]
    observed = datetime.fromisoformat(
        freshness["observed_at_utc"].replace("Z", "+00:00")
    )
    assert 0 <= (datetime.now(timezone.utc) - observed).total_seconds() < 2
    assert freshness == {
        "observed_at_utc": freshness["observed_at_utc"],
        "age_seconds": 0,
        "max_age_seconds": 30,
        "provenance": "live_gate_and_durable_snapshot",
        "valid": True,
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
    public_leaf_values = []

    def _collect_leaf_values(value):
        if isinstance(value, dict):
            for nested in value.values():
                _collect_leaf_values(nested)
        elif isinstance(value, list):
            for nested in value:
                _collect_leaf_values(nested)
        else:
            public_leaf_values.append(value)

    _collect_leaf_values(payload)
    assert 4321 not in public_leaf_values
    assert "4321" not in public_leaf_values
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
        "read_only_status",
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


def test_safety_status_uses_the_non_mutating_gate_reader(monkeypatch):
    import api_server

    _install_diagnostic_counts(monkeypatch, api_server)
    monkeypatch.setattr(
        api_server,
        "_stability_startup_status",
        _startup_status(allowed=True, reason_code=""),
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "read_only_status",
        lambda: SimpleNamespace(
            to_dict=lambda: _gate_status(allowed=True, reason_code="")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "status",
        lambda: (_ for _ in ()).throw(
            AssertionError("read-only diagnostics used the enforcing gate reader")
        ),
    )
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: ("a" * 64, "mainnet"),
    )

    response = api_server.app.test_client().get("/api/safety/status")

    assert response.status_code == 200
    assert response.get_json()["safety"]["allowed"] is True


def test_app_bridge_safety_status_matches_api_exactly(monkeypatch):
    import api_server
    import app_bridge

    _install_diagnostic_counts(monkeypatch, api_server)
    monkeypatch.setattr(api_server, "_stability_startup_status", _startup_status())
    monkeypatch.setattr(
        api_server.mutation_gate,
        "read_only_status",
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
    expected_observed = expected["safety"]["recovery"]["freshness"].pop(
        "observed_at_utc"
    )
    result_observed = result["safety"]["recovery"]["freshness"].pop("observed_at_utc")
    assert result == expected
    for observed_at in (expected_observed, result_observed):
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        assert 0 <= (datetime.now(timezone.utc) - observed).total_seconds() < 2


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
        "read_only_status",
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


def test_safety_release_resolved_uses_exact_runtime_cas(monkeypatch):
    import api_server

    calls = []

    class FakeRuntime:
        def release_resolved(self, expected_generation, resolved_operation_ids):
            calls.append((expected_generation, resolved_operation_ids))
            return {
                "released": True,
                "reason": "released",
                "status": {"allowed": True},
            }

    monkeypatch.setattr(
        api_server.mutation_gate,
        "current_runtime",
        lambda: FakeRuntime(),
    )
    client = api_server.app.test_client()
    response = client.post(
        "/api/safety/release-resolved",
        json={
            "expected_generation": 7,
            "resolved_operation_ids": ["cancel:" + "a" * 64],
        },
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "released": True,
        "reason_code": "RELEASED",
    }
    assert calls == [(7, ["cancel:" + "a" * 64])]
    assert "api_safety_release_resolved" in api_server._CONTROL_WRITE_API_ENDPOINTS


def test_safety_release_resolved_rejects_malformed_authority(monkeypatch):
    import api_server

    calls = []
    monkeypatch.setattr(
        api_server.mutation_gate,
        "current_runtime",
        lambda: SimpleNamespace(release_resolved=lambda *args: calls.append(args)),
    )
    response = api_server.app.test_client().post(
        "/api/safety/release-resolved",
        json={"expected_generation": True, "resolved_operation_ids": []},
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "released": False,
        "reason_code": "RELEASE_REQUEST_MALFORMED",
    }
    assert calls == []
