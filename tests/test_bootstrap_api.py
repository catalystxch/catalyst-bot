from __future__ import annotations

from datetime import datetime, timezone

from flask import Flask
import pytest

import database


ASSET_ID = "b8" * 32
OTHER_ASSET_ID = "cd" * 32


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bootstrap-api.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


@pytest.fixture
def bootstrap_api(monkeypatch):
    from blueprints import bootstrap

    identity = {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 736588221,
        "wallet_id": 2,
        "asset_id": ASSET_ID,
        "ticker": "MZ",
        "has_secrets": True,
    }
    monkeypatch.setattr(bootstrap, "_read_bootstrap_identity", lambda: dict(identity))
    monkeypatch.setattr(
        bootstrap,
        "_utcnow",
        lambda: datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc),
    )
    app = Flask(__name__)
    app.register_blueprint(bootstrap.bp)
    app.config.update(TESTING=True)
    return bootstrap, app.test_client(), identity


def _request(**overrides):
    body = {
        "asset_id": ASSET_ID,
        "ticker": "MZ",
        "anchor_price": "0.001",
        "xch_budget": "1",
        "cat_budget": "1000",
        "fee_budget_xch": "0.05",
        "subsidy_budget_xch": "0",
        "expires_in_seconds": 604800,
        "balances": {
            "xch_available": "2",
            "cat_available": "2000",
            "fee_spent_xch": "0",
            "subsidy_spent_xch": "0",
            "network_fee_xch": "0.00001",
            "minimum_profit_xch": "0",
            "fee_coin_size_xch": "0.001",
            "expected_cancel_requotes": 1,
        },
    }
    body.update(overrides)
    return body


def test_preview_is_pure_and_returns_bounded_plan(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    monkeypatch.setattr(
        database,
        "create_bootstrap_campaign",
        lambda _record: (_ for _ in ()).throw(AssertionError("preview mutated DB")),
    )

    response = client.post("/api/bootstrap/preview", json=_request())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert len(payload["preview_digest"]) == 64
    assert payload["campaign"]["minimum_price"] == "0.0005"
    assert payload["campaign"]["maximum_price"] == "0.002"
    assert payload["plan"]["deployment_fraction"] == "0.1"
    assert len(payload["plan"]["sides"]["buy"]["levels"]) == 3
    assert len(payload["plan"]["sides"]["sell"]["levels"]) == 3


def test_start_requires_exact_asset_warning_and_persists_before_coin_prep(
    isolated_db, bootstrap_api
):
    _bootstrap, client, _identity = bootstrap_api
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()

    rejected = client.post(
        "/api/bootstrap/start",
        json=_request(preview_digest=preview["preview_digest"]),
    )

    assert rejected.status_code == 400
    assert rejected.get_json()["code"] == "exact_asset_confirmation_required"
    assert (
        database.get_active_bootstrap_campaign(ASSET_ID, 736588221, "mainnet") is None
    )

    accepted = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    )

    assert accepted.status_code == 200
    payload = accepted.get_json()
    assert payload["success"] is True
    assert payload["coin_prep_required"] is True
    assert payload["financial_action_started"] is False
    active = database.get_active_bootstrap_campaign(ASSET_ID, 736588221, "mainnet")
    assert active["campaign_id"] == payload["campaign_id"]


def _start_campaign(client):
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    return client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]


def test_participation_export_uses_only_append_only_campaign_samples(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    campaign_id = _start_campaign(client)
    database.record_bootstrap_participation(
        {
            "campaign_id": campaign_id,
            "report_id": "21" * 32,
            "recorded_at": datetime(2026, 9, 12, 12, 5, tzinfo=timezone.utc),
            "data": {
                "kind": "quality_sample",
                "duration_seconds": 300,
                "independent_depth_xch": "2",
                "spread_bps": "150",
                "within_corridor": True,
                "own": False,
                "linked": False,
                "offer_ids": ["01" * 32],
                "fill_ids": ["11" * 32],
                "wallet_fingerprint": 736588221,
                "balances": {"xch": "99"},
                "trade_volume_xch": "1000000",
            },
        }
    )
    monkeypatch.setattr(
        bootstrap,
        "_utcnow",
        lambda: datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc),
    )

    response = client.post(
        "/api/bootstrap/participation/export",
        json={"campaign_id": campaign_id},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["report"]["eligible_observation_ids"] == ["21" * 32]
    assert payload["report"]["eligible_offer_ids"] == ["01" * 32]
    assert payload["report"]["eligible_fill_ids"] == ["11" * 32]
    serialized = __import__("json").dumps(payload).lower()
    assert "fingerprint" not in serialized
    assert "balance" not in serialized
    assert "volume" not in serialized
    assert payload["financial_authority"] is False


def test_participation_export_rejects_campaign_from_another_wallet(
    isolated_db, bootstrap_api
):
    _bootstrap, client, identity = bootstrap_api
    campaign_id = _start_campaign(client)
    identity["wallet_fingerprint"] = 123456789

    response = client.post(
        "/api/bootstrap/participation/export",
        json={"campaign_id": campaign_id},
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "bootstrap_identity_mismatch"


def test_start_rejects_identity_or_asset_changed_after_preview(
    isolated_db, bootstrap_api
):
    _bootstrap, client, identity = bootstrap_api
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    identity["wallet_fingerprint"] = 123456789

    response = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "bootstrap_preview_stale"

    identity["wallet_fingerprint"] = 736588221
    identity["asset_id"] = OTHER_ASSET_ID
    response = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "bootstrap_asset_identity_changed"


def test_import_never_grants_budget_or_start_authority(bootstrap_api, monkeypatch):
    bootstrap, client, _identity = bootstrap_api
    from bootstrap_manifest import ImportedManifest

    imported = ImportedManifest(
        campaign_id="bootstrap_" + "aa" * 32,
        verification_status="VERIFIED",
        network="mainnet",
        asset_id=ASSET_ID,
        ticker="MZ",
        anchor_price="0.001",
        minimum_price="0.0005",
        maximum_price="0.002",
        created_at="2026-09-12T12:00:00.000000Z",
        expires_at="2026-09-19T12:00:00.000000Z",
        offer_levels_per_side=3,
        capacity_stages=("0.1", "0.25", "0.5", "1"),
        stage_thresholds={},
        anchor_caps={"hourly": "0.05", "daily": "0.2"},
        adverse_fill_cooldown_seconds=300,
        loss_stop_fraction="0.05",
        partial_offers="disabled_until_capability_proven",
        signer_public_key="11" * 48,
        signing_address="xch1" + "q" * 58,
    )

    monkeypatch.setattr(bootstrap, "safe_import_manifest", lambda *_a, **_k: imported)

    response = client.post(
        "/api/bootstrap/manifest/import", json={"signed_manifest": {}}
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["can_start"] is False
    assert payload["requires_local_budget_acceptance"] is True
    assert "xch_budget" not in payload["manifest"]
    assert "cat_budget" not in payload["manifest"]


def test_partial_offer_capability_is_explicitly_disabled(bootstrap_api):
    _bootstrap, client, _identity = bootstrap_api

    response = client.get("/api/bootstrap/partial-capability")

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "enabled": False,
        "reason_code": "PARTIAL_OFFERS_CAPABILITY_NOT_PROVEN",
        "reason_codes": [
            "MISSING_PARTIAL_CREATE",
            "MISSING_PARTIAL_CANCEL",
            "MISSING_PARTIAL_STATE",
            "MISSING_PARTIAL_LINEAGE",
            "MISSING_PARTIAL_FILL",
            "MISSING_PARTIAL_DISCOVERY",
        ],
        "providers": ["dexie", "sage", "splash"],
        "policy": "disabled_until_capability_proven",
    }


def test_status_export_and_scoped_stop_use_exact_active_campaign(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    started = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()
    campaign_id = started["campaign_id"]

    status = client.get("/api/bootstrap/status").get_json()
    assert status["active"] is True
    assert status["campaign"]["campaign_id"] == campaign_id

    exported = client.post(
        "/api/bootstrap/manifest/export",
        json={"campaign_id": campaign_id, "ticker": "MZ"},
    ).get_json()
    assert exported["success"] is True
    assert exported["financial_authority"] is False
    assert exported["manifest"]["partial_offers"] == (
        "disabled_until_capability_proven"
    )
    assert "xch_budget" not in exported["manifest"]

    cancelled = []
    monkeypatch.setattr(
        bootstrap,
        "_campaign_trade_ids",
        lambda exact_id: ["trade-a", "trade-b"] if exact_id == campaign_id else [],
    )
    monkeypatch.setattr(
        bootstrap,
        "_cancel_campaign_offers",
        lambda trade_ids: (
            cancelled.extend(trade_ids)
            or {trade_id: {"outcome": "CANCEL_SUBMITTED"} for trade_id in trade_ids}
        ),
    )
    stopped = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    assert stopped.status_code == 200
    assert cancelled == ["trade-a", "trade-b"]
    assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
