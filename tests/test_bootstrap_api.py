from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from flask import Flask
import pytest

import database


ASSET_ID = "b8" * 32
OTHER_ASSET_ID = "cd" * 32


@pytest.mark.parametrize("expires_at", ["not-a-time", "2026-09-12T12:00:00"])
def test_unparseable_active_campaign_expiry_requires_attention(expires_at):
    from blueprints import bootstrap

    campaign = {
        "campaign_id": "ab" * 32,
        "status": "active",
        "expires_at": expires_at,
    }
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

    assert bootstrap._campaign_expiry_has_elapsed(campaign, now) is True


def test_bootstrap_identity_uses_configured_ticker_id_not_display_name(monkeypatch):
    from blueprints import bootstrap
    import wallet

    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: {
            "success": True,
            "backend": "sage",
            "has_secrets": True,
            "fingerprint": 736588221,
            "network_id": "mainnet",
        },
    )
    monkeypatch.setattr(
        bootstrap,
        "cfg",
        SimpleNamespace(
            CAT_ASSET_ID=ASSET_ID,
            CAT_WALLET_ID=2,
            CAT_TICKER_ID="MZ_XCH",
            CAT_NAME="Monkeyzoo Token",
        ),
    )

    assert bootstrap._read_bootstrap_identity()["ticker"] == "MZ"


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
        "_campaign_cancel_manager",
        lambda: SimpleNamespace(cancel_offers=lambda *_args, **_kwargs: {}),
    )
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


def test_preview_rejects_full_wave_principal_that_consumes_reserve_and_fee_coins(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    monkeypatch.setattr(
        bootstrap,
        "cfg",
        SimpleNamespace(
            XCH_RESERVE="24.082",
            CAT_RESERVE="338152.172",
            LIQUIDITY_MODE="two_sided",
            ENABLE_BUY=True,
            ENABLE_SELL=True,
        ),
    )
    body = _request(
        anchor_price="0.000075",
        xch_budget="216.72070779727",
        cat_budget="3043369.548",
        balances={
            "xch_available": "240.800786441412",
            "cat_available": "3381521.72",
            "fee_spent_xch": "0",
            "subsidy_spent_xch": "0",
            "network_fee_xch": "0.0000130791",
            "minimum_profit_xch": "0",
            "fee_coin_size_xch": "0.001",
            "expected_cancel_requotes": 1,
        },
    )

    response = client.post("/api/bootstrap/preview", json=body)

    assert response.status_code == 400
    assert response.get_json()["code"] == "bootstrap_xch_prep_principal_unfunded"
    assert (
        database.get_active_bootstrap_campaign(ASSET_ID, 736588221, "mainnet") is None
    )


def test_preview_rejects_cat_budget_that_consumes_configured_reserve(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    monkeypatch.setattr(
        bootstrap,
        "cfg",
        SimpleNamespace(
            XCH_RESERVE="0",
            CAT_RESERVE="200",
            LIQUIDITY_MODE="two_sided",
            ENABLE_BUY=True,
            ENABLE_SELL=True,
        ),
    )

    response = client.post("/api/bootstrap/preview", json=_request(cat_budget="1900"))

    assert response.status_code == 400
    assert response.get_json()["code"] == "bootstrap_cat_prep_principal_unfunded"
    assert (
        database.get_active_bootstrap_campaign(ASSET_ID, 736588221, "mainnet") is None
    )


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


def test_status_reports_temporarily_unavailable_identity_without_http_conflict(
    bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    monkeypatch.setattr(
        bootstrap,
        "_read_bootstrap_identity",
        lambda: (_ for _ in ()).throw(
            bootstrap.BootstrapApiError("bootstrap_asset_not_selected", 409)
        ),
    )

    response = client.get("/api/bootstrap/status")

    assert response.status_code == 200
    assert response.get_json() == {
        "success": False,
        "active": None,
        "campaign": None,
        "identity": None,
        "code": "bootstrap_asset_not_selected",
        "error": "bootstrap_asset_not_selected",
    }


def test_status_uses_authoritative_campaign_fee_evidence(
    isolated_db, bootstrap_api, monkeypatch
):
    _bootstrap, client, _identity = bootstrap_api
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    started = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()
    campaign_id = started["campaign_id"]
    monkeypatch.setattr(
        database,
        "get_bootstrap_campaign_authoritative_fee_spent_mojos",
        lambda exact_id: 8_563_369 if exact_id == campaign_id else 0,
    )

    status = client.get("/api/bootstrap/status").get_json()

    assert status["campaign"]["fee_spent_xch"] == "0.000008563369"


def test_status_flags_expired_active_campaign_as_cancel_required(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    preview = client.post(
        "/api/bootstrap/preview", json=_request(expires_in_seconds=60)
    ).get_json()
    started = client.post(
        "/api/bootstrap/start",
        json=_request(
            expires_in_seconds=60,
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()
    campaign_id = started["campaign_id"]
    monkeypatch.setattr(
        bootstrap,
        "_utcnow",
        lambda: datetime(2026, 9, 12, 12, 1, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        bootstrap,
        "_campaign_trade_ids",
        lambda exact_id: ["trade-a", "trade-b"] if exact_id == campaign_id else [],
    )

    status = client.get("/api/bootstrap/status").get_json()

    assert status["active"] is True
    assert status["campaign"]["campaign_id"] == campaign_id
    assert status["campaign"]["status"] == "active"
    assert status["campaign"]["expired"] is True
    assert status["campaign"]["cancel_required"] is True
    assert status["campaign"]["cancel_reason"] == "bootstrap_expired"
    assert status["campaign"]["manual_restart_required"] is True
    assert status["campaign"]["open_offer_count"] == 2
    assert status["needs_attention"] is True
    assert database.get_bootstrap_campaign(campaign_id)["status"] == "active"


def test_expired_campaign_without_offers_stops_without_wallet_cancellation(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    request = _request(expires_in_seconds=60)
    preview = client.post("/api/bootstrap/preview", json=request).get_json()
    started = client.post(
        "/api/bootstrap/start",
        json={
            **request,
            "preview_digest": preview["preview_digest"],
            "exact_asset_warning_accepted": True,
        },
    ).get_json()
    campaign_id = started["campaign_id"]
    monkeypatch.setattr(
        bootstrap,
        "_utcnow",
        lambda: datetime(2026, 9, 12, 12, 1, 1, tzinfo=timezone.utc),
    )
    assert bootstrap._campaign_trade_ids(campaign_id) == []
    monkeypatch.setattr(
        bootstrap,
        "_campaign_cancel_manager",
        lambda: pytest.fail("zero-offer stop accessed the wallet cancel manager"),
    )

    stopped = client.post(
        "/api/bootstrap/stop",
        json={
            "campaign_id": campaign_id,
            "revision": 0,
            "observed_open_offer_count": 1,
        },
    )

    assert stopped.status_code == 200
    assert stopped.get_json() == {
        "success": True,
        "campaign_id": campaign_id,
        "stopped": True,
        "cancel_targets": 0,
        "cancel_results": {},
    }
    campaign = database.get_bootstrap_campaign(campaign_id)
    assert campaign["status"] == "stopped"
    assert campaign["revision"] == 1
    assert client.get("/api/bootstrap/status").get_json()["active"] is False


def test_stop_collects_offers_after_in_flight_creation_finishes(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    request = _request(expires_in_seconds=60)
    preview = client.post("/api/bootstrap/preview", json=request).get_json()
    started = client.post(
        "/api/bootstrap/start",
        json={
            **request,
            "preview_digest": preview["preview_digest"],
            "exact_asset_warning_accepted": True,
        },
    ).get_json()
    campaign_id = started["campaign_id"]
    creation_finished = False
    cancellations = []

    class Manager:
        def wait_for_offer_creation_quiescence(self):
            nonlocal creation_finished
            assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
            creation_finished = True

        def cancel_offers(self, trade_ids, **_kwargs):
            cancellations.extend(trade_ids)
            return {trade_id: {"outcome": "CANCEL_CONFIRMED"} for trade_id in trade_ids}

    manager = Manager()
    monkeypatch.setattr(bootstrap, "_campaign_cancel_manager", lambda: manager)
    monkeypatch.setattr(
        bootstrap,
        "_campaign_trade_ids",
        lambda exact_id: (
            ["late-trade"] if exact_id == campaign_id and creation_finished else []
        ),
    )
    client.application.config["_CATALYST_API_SERVER_MODULE"] = SimpleNamespace(
        bot=SimpleNamespace(offer_manager=manager)
    )

    stopped = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )

    assert stopped.status_code == 200
    assert creation_finished is True
    assert stopped.get_json()["cancel_targets"] == 1
    assert cancellations == ["late-trade"]


def test_stop_requires_new_review_when_offer_count_changes_during_stop(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    request = _request(expires_in_seconds=60)
    preview = client.post("/api/bootstrap/preview", json=request).get_json()
    started = client.post(
        "/api/bootstrap/start",
        json={
            **request,
            "preview_digest": preview["preview_digest"],
            "exact_asset_warning_accepted": True,
        },
    ).get_json()
    campaign_id = started["campaign_id"]
    creation_finished = False
    cancelled = []

    class Manager:
        def wait_for_offer_creation_quiescence(self):
            nonlocal creation_finished
            creation_finished = True

        def cancel_offers(self, trade_ids, **_kwargs):
            cancelled.extend(trade_ids)
            return {trade_id: {"outcome": "CANCEL_CONFIRMED"} for trade_id in trade_ids}

    manager = Manager()
    monkeypatch.setattr(bootstrap, "_campaign_cancel_manager", lambda: manager)
    monkeypatch.setattr(
        bootstrap,
        "_campaign_trade_ids",
        lambda exact_id: (
            ["late-trade"] if exact_id == campaign_id and creation_finished else []
        ),
    )
    client.application.config["_CATALYST_API_SERVER_MODULE"] = SimpleNamespace(
        bot=SimpleNamespace(offer_manager=manager)
    )

    stopped = client.post(
        "/api/bootstrap/stop",
        json={
            "campaign_id": campaign_id,
            "revision": 0,
            "observed_open_offer_count": 0,
        },
    )

    assert stopped.status_code == 409
    assert stopped.get_json()["code"] == "bootstrap_stop_targets_changed"
    assert stopped.get_json()["financial_action_started"] is False
    assert stopped.get_json()["cancel_targets"] == 1
    assert cancelled == []
    assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"


def test_stop_does_not_claim_clearance_for_unknown_creation_without_trade_id(
    isolated_db, bootstrap_api
):
    _bootstrap, client, _identity = bootstrap_api
    request = _request(expires_in_seconds=60)
    preview = client.post("/api/bootstrap/preview", json=request).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json={
            **request,
            "preview_digest": preview["preview_digest"],
            "exact_asset_warning_accepted": True,
        },
    ).get_json()["campaign_id"]
    intent_id = "a" * 64
    operation_id = f"create:{intent_id}"
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:prepared",
        run_id="unknown-creation-stop",
        wallet_fingerprint_hash="b" * 64,
        network="mainnet",
        asset_id=ASSET_ID,
        side="buy",
        tier="inner",
        purpose=f"bootstrap:{campaign_id}:revision:0",
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=["c" * 64],
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"canonical_intent_sha256": intent_id},
        prepared_at="2026-09-12T12:00:00Z",
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:unknown",
        lifecycle_state="creation_unknown",
        outcome="UNKNOWN",
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"effect_attempted": True},
        reason_code="CREATE_RESPONSE_AMBIGUOUS",
        finalized_at="2026-09-12T12:00:01Z",
    )
    active_status = client.get("/api/bootstrap/status").get_json()
    assert active_status["campaign"]["open_offer_count"] == 0
    assert active_status["campaign"]["unresolved_creation_count"] == 1
    assert active_status["needs_attention"] is True

    stopped = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )

    assert stopped.status_code == 503
    assert stopped.get_json()["success"] is False
    assert stopped.get_json()["code"] == "bootstrap_cancel_outcome_unknown"
    assert stopped.get_json()["stopped"] is True
    stopped_status = client.get("/api/bootstrap/status").get_json()
    assert stopped_status["needs_attention"] is True
    retry = stopped_status["stopped_cancellation"]
    assert retry["code"] == "bootstrap_cancel_outcome_unknown"
    assert retry["cancel_targets"] == 0
    assert retry["unresolved_creation_count"] == 1
    assert retry["financial_action_started"] is None

    next_request = _request(expires_in_seconds=60)
    next_preview = client.post("/api/bootstrap/preview", json=next_request).get_json()
    confirmed = {
        **next_request,
        "preview_digest": next_preview["preview_digest"],
        "exact_asset_warning_accepted": True,
    }
    for path, body in (
        ("/api/bootstrap/start", confirmed),
        ("/api/bootstrap/renew", {**confirmed, "prior_campaign_id": campaign_id}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 409
        assert response.get_json()["code"] == "bootstrap_prior_creation_unresolved"


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

    def cancel_after_creation_authority_is_stopped(trade_ids):
        assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
        cancelled.extend(trade_ids)
        return {
            trade_id: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}
            for trade_id in trade_ids
        }

    monkeypatch.setattr(
        bootstrap,
        "_cancel_campaign_offers",
        cancel_after_creation_authority_is_stopped,
    )
    stopped = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    assert stopped.status_code == 200
    assert cancelled == ["trade-a", "trade-b"]
    assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"


def test_submitted_prior_cancellation_blocks_start_and_renew_until_terminal(
    isolated_db, bootstrap_api, monkeypatch
):
    bootstrap, client, _identity = bootstrap_api
    request = _request(expires_in_seconds=60)
    preview = client.post("/api/bootstrap/preview", json=request).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json={
            **request,
            "preview_digest": preview["preview_digest"],
            "exact_asset_warning_accepted": True,
        },
    ).get_json()["campaign_id"]
    pending = True
    monkeypatch.setattr(
        bootstrap,
        "_campaign_trade_ids",
        lambda exact_id: ["trade-a"] if exact_id == campaign_id and pending else [],
    )
    monkeypatch.setattr(
        bootstrap,
        "_cancel_campaign_offers",
        lambda _trade_ids: {"trade-a": {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}},
    )
    stopped = client.post(
        "/api/bootstrap/stop", json={"campaign_id": campaign_id, "revision": 0}
    )
    assert stopped.status_code == 200
    assert stopped.get_json()["cancel_results"]["trade-a"]["outcome"] == (
        "CANCEL_SUBMITTED_UNCONFIRMED"
    )

    status = client.get("/api/bootstrap/status").get_json()
    assert status["needs_attention"] is True
    assert status["stopped_cancellation"]["campaign_id"] == campaign_id
    assert status["stopped_cancellation"]["cancel_targets"] == 1

    next_preview = client.post("/api/bootstrap/preview", json=request).get_json()
    confirmed = {
        **request,
        "preview_digest": next_preview["preview_digest"],
        "exact_asset_warning_accepted": True,
    }
    for path, body in (
        ("/api/bootstrap/start", confirmed),
        ("/api/bootstrap/renew", {**confirmed, "prior_campaign_id": campaign_id}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 409
        assert response.get_json()["code"] == "bootstrap_prior_cancel_unconfirmed"

    pending = False  # Authoritative reconciliation made the intent terminal.
    assert (
        client.get("/api/bootstrap/status").get_json()["stopped_cancellation"] is None
    )
    assert client.post("/api/bootstrap/start", json=confirmed).status_code == 200


@pytest.mark.parametrize(
    "identity_field, changed_value",
    [
        ("wallet_fingerprint", 123456789),
        ("wallet_id", 3),
        ("asset_id", OTHER_ASSET_ID),
        ("network", "testnet"),
    ],
)
def test_renew_rejects_stopped_campaign_from_another_wallet(
    isolated_db, bootstrap_api, identity_field, changed_value
):
    _bootstrap, client, identity = bootstrap_api
    prior_id = _start_campaign(client)
    stopped = client.post(
        "/api/bootstrap/stop", json={"campaign_id": prior_id, "revision": 0}
    )
    assert stopped.status_code == 200

    identity[identity_field] = changed_value
    request = _request(asset_id=identity["asset_id"], expires_in_seconds=60)
    preview = client.post("/api/bootstrap/preview", json=request).get_json()
    response = client.post(
        "/api/bootstrap/renew",
        json={
            **request,
            "prior_campaign_id": prior_id,
            "preview_digest": preview["preview_digest"],
            "exact_asset_warning_accepted": True,
        },
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "bootstrap_identity_mismatch"
    assert (
        database.get_active_bootstrap_campaign(
            identity["asset_id"],
            identity["wallet_fingerprint"],
            identity["network"],
        )
        is None
    )


def test_renew_accepts_stopped_campaign_for_same_wallet(isolated_db, bootstrap_api):
    _bootstrap, client, _identity = bootstrap_api
    prior_id = _start_campaign(client)
    assert (
        client.post(
            "/api/bootstrap/stop", json={"campaign_id": prior_id, "revision": 0}
        ).status_code
        == 200
    )
    request = _request(expires_in_seconds=60)
    preview = client.post("/api/bootstrap/preview", json=request).get_json()
    response = client.post(
        "/api/bootstrap/renew",
        json={
            **request,
            "prior_campaign_id": prior_id,
            "preview_digest": preview["preview_digest"],
            "exact_asset_warning_accepted": True,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["prior_campaign_id"] == prior_id


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("FEE_APPROVAL_STALE", "FEE_APPROVAL_STALE"),
        ("FEE_APPROVAL_LEGACY_UNSCOPED", "FEE_APPROVAL_LEGACY_UNSCOPED"),
        ("FEE_APPROVAL_RECOVERY_ONLY", "FEE_APPROVAL_RECOVERY_ONLY"),
        (
            "FEE_APPROVAL_RECOVERY_ACTION_MISMATCH",
            "FEE_APPROVAL_RECOVERY_ACTION_MISMATCH",
        ),
        ("fee_approval_stale", "FEE_APPROVAL_STALE"),
    ],
)
def test_stop_fee_refusal_is_structured_and_leaves_campaign_in_recovery(
    isolated_db, bootstrap_api, monkeypatch, reason, expected
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
    monkeypatch.setattr(
        bootstrap,
        "_campaign_trade_ids",
        lambda exact_id: ["trade-a"] if exact_id == campaign_id else [],
    )

    def stale_after_stop(_trade_ids):
        assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
        raise ValueError(reason)

    monkeypatch.setattr(bootstrap, "_cancel_campaign_offers", stale_after_stop)
    response = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    payload = response.get_json()

    assert response.status_code == 409, payload
    assert payload == {
        "success": False,
        "code": expected,
        "error": expected,
        "stopped": True,
        "campaign_id": campaign_id,
        "campaign_revision": 1,
        "cancel_targets": 1,
        "financial_action_started": False,
    }
    campaign = database.get_bootstrap_campaign(campaign_id)
    assert campaign["status"] == "stopped"
    assert campaign["stage"] == "stopped"
    assert campaign["revision"] == 1


def test_stop_manager_unavailable_reports_committed_revision(
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
    monkeypatch.setattr(bootstrap, "_campaign_trade_ids", lambda exact_id: ["trade-a"])

    def unavailable(_trade_ids):
        assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
        raise bootstrap.BootstrapApiError("bootstrap_cancel_manager_unavailable", 409)

    monkeypatch.setattr(bootstrap, "_cancel_campaign_offers", unavailable)
    response = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    payload = response.get_json()

    assert response.status_code == 409, payload
    assert payload["stopped"] is True
    assert payload["campaign_revision"] == 1
    assert payload["code"] == "bootstrap_cancel_manager_unavailable"
    assert payload["cancel_targets"] == 1
    assert database.get_bootstrap_campaign(campaign_id)["revision"] == 1


@pytest.mark.parametrize("final_recorded", [True, False])
def test_stop_manager_unavailable_still_freezes_creation_authority(
    isolated_db, bootstrap_api, monkeypatch, final_recorded
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
    monkeypatch.setattr(bootstrap, "_campaign_trade_ids", lambda _id: ["trade-a"])

    def no_manager():
        raise bootstrap.BootstrapApiError("bootstrap_cancel_manager_unavailable", 409)

    monkeypatch.setattr(bootstrap, "_campaign_cancel_manager", no_manager)
    response = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    assert response.status_code == 409
    assert response.get_json()["stopped"] is True
    assert response.get_json()["campaign_revision"] == 1
    assert response.get_json()["financial_action_started"] is False
    assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
    assert database.get_bootstrap_campaign(campaign_id)["revision"] == 1
    status = client.get("/api/bootstrap/status").get_json()
    assert status["active"] is False
    assert status["stopped_cancellation"]["campaign_id"] == campaign_id
    assert status["stopped_cancellation"]["revision"] == 1
    assert status["stopped_cancellation"]["financial_action_started"] is False
    monkeypatch.setattr(
        bootstrap,
        "_campaign_cancel_manager",
        lambda: SimpleNamespace(
            cancel_offers=lambda *_args, **_kwargs: {
                "trade-a": {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}
            }
        ),
    )
    if not final_recorded:
        append_event = database.append_bootstrap_campaign_event

        def fail_final_event(record):
            if (
                record["event_type"] == "campaign_cancel_attempt"
                and record["data"]["code"] is None
            ):
                raise RuntimeError("event storage unavailable")
            return append_event(record)

        monkeypatch.setattr(
            database, "append_bootstrap_campaign_event", fail_final_event
        )
    retry = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 1},
    )
    if final_recorded:
        assert retry.status_code == 200, retry.get_json()
        status = client.get("/api/bootstrap/status").get_json()
        assert status["needs_attention"] is True
        assert status["stopped_cancellation"]["code"] == (
            "bootstrap_cancel_outcome_unknown"
        )
    else:
        assert retry.status_code == 503, retry.get_json()
        assert retry.get_json()["financial_action_started"] is None
        status = client.get("/api/bootstrap/status").get_json()
        assert status["stopped_cancellation"]["financial_action_started"] is None


@pytest.mark.parametrize("record_final_attempt", [True, False])
def test_stop_transport_failure_reports_committed_revision_and_unknown_effect(
    isolated_db, bootstrap_api, monkeypatch, record_final_attempt
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
    monkeypatch.setattr(bootstrap, "_campaign_trade_ids", lambda _id: ["trade-a"])

    def uncertain(_trade_ids):
        assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
        raise RuntimeError("transport failed after cancellation submission")

    monkeypatch.setattr(bootstrap, "_cancel_campaign_offers", uncertain)
    if not record_final_attempt:
        record_attempt = bootstrap._record_campaign_cancel_attempt

        def fail_final_attempt(*args, **kwargs):
            if kwargs.get("code") == "bootstrap_cancel_attempt_started":
                return record_attempt(*args, **kwargs)
            return False

        monkeypatch.setattr(
            bootstrap, "_record_campaign_cancel_attempt", fail_final_attempt
        )
    response = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    payload = response.get_json()
    assert response.status_code == 503, payload
    assert payload["stopped"] is True
    assert payload["campaign_revision"] == 1
    assert payload["code"] == "bootstrap_cancel_outcome_unknown"
    assert payload["financial_action_started"] is None
    status = client.get("/api/bootstrap/status").get_json()
    assert status["stopped_cancellation"]["campaign_id"] == campaign_id
    assert status["stopped_cancellation"]["financial_action_started"] is None


def test_stop_invalid_manager_result_does_not_claim_no_financial_action(
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
    monkeypatch.setattr(bootstrap, "_campaign_trade_ids", lambda _id: ["trade-a"])
    monkeypatch.setattr(
        bootstrap,
        "_campaign_cancel_manager",
        lambda: SimpleNamespace(cancel_offers=lambda *_args, **_kwargs: None),
    )
    response = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    payload = response.get_json()
    assert response.status_code == 503, payload
    assert payload["stopped"] is True
    assert payload["campaign_revision"] == 1
    assert payload["financial_action_started"] is None


def test_stop_journal_failure_remains_visible_after_status_reload(
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
    monkeypatch.setattr(bootstrap, "_campaign_trade_ids", lambda _id: ["trade-a"])
    manager_calls = []
    monkeypatch.setattr(
        bootstrap,
        "_campaign_cancel_manager",
        lambda: SimpleNamespace(
            cancel_offers=lambda *_args, **_kwargs: manager_calls.append(1)
        ),
    )
    monkeypatch.setattr(
        database,
        "append_bootstrap_campaign_event",
        lambda _record: (_ for _ in ()).throw(RuntimeError("journal unavailable")),
    )

    response = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    payload = response.get_json()
    assert response.status_code == 409, payload
    assert payload["stopped"] is True
    assert payload["financial_action_started"] is False
    assert not manager_calls
    assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"

    status = client.get("/api/bootstrap/status").get_json()
    assert status["stopped_cancellation"] == {
        "campaign_id": campaign_id,
        "revision": 1,
        "code": "bootstrap_cancel_outcome_unknown",
        "financial_action_started": None,
        "cancel_targets": 1,
        "unresolved_creation_count": 0,
    }


@pytest.mark.parametrize("outcome", ["CANCEL_UNKNOWN", "CANCEL_FAILED", None])
def test_stop_unknown_per_offer_result_remains_unresolved_after_reload(
    isolated_db, bootstrap_api, monkeypatch, outcome
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
    monkeypatch.setattr(bootstrap, "_campaign_trade_ids", lambda _id: ["trade-a"])
    monkeypatch.setattr(
        bootstrap,
        "_campaign_cancel_manager",
        lambda: SimpleNamespace(
            cancel_offers=lambda *_args, **_kwargs: (
                {} if outcome is None else {"trade-a": {"outcome": outcome}}
            )
        ),
    )
    response = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    assert response.status_code == 503, response.get_json()
    assert response.get_json()["financial_action_started"] is None
    status = client.get("/api/bootstrap/status").get_json()
    assert status["stopped_cancellation"]["campaign_id"] == campaign_id
    assert status["stopped_cancellation"]["financial_action_started"] is None


def test_stop_fee_prep_funding_shortfall_enters_approval_recovery(
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
    monkeypatch.setattr(
        bootstrap,
        "_campaign_trade_ids",
        lambda exact_id: ["trade-a"] if exact_id == campaign_id else [],
    )

    def funding_shortfall_after_stop(_trade_ids):
        assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
        raise ValueError("FEE_PREP_FUNDING_INSUFFICIENT")

    monkeypatch.setattr(
        bootstrap, "_cancel_campaign_offers", funding_shortfall_after_stop
    )
    response = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    payload = response.get_json()

    assert response.status_code == 409, payload
    assert payload == {
        "success": False,
        "code": "FEE_PREP_FUNDING_INSUFFICIENT",
        "error": "FEE_PREP_FUNDING_INSUFFICIENT",
        "stopped": True,
        "campaign_id": campaign_id,
        "campaign_revision": 1,
        "cancel_targets": 1,
        "financial_action_started": False,
    }


def test_stopped_campaign_retry_passes_exact_fee_approval_to_scoped_cancellation(
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
    trade_id = "a" * 64
    approval_id = "f" * 64
    monkeypatch.setattr(
        bootstrap,
        "_campaign_trade_ids",
        lambda exact_id: [trade_id] if exact_id == campaign_id else [],
    )
    attempts = []

    def cancel_after_stop(trade_ids, *, fee_approval_id=None):
        assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
        attempts.append((trade_ids, fee_approval_id))
        if fee_approval_id is None:
            raise ValueError("FEE_APPROVAL_STALE")
        return {trade_id: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}}

    monkeypatch.setattr(bootstrap, "_cancel_campaign_offers", cancel_after_stop)
    first = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    )
    retry = client.post(
        "/api/bootstrap/stop",
        json={
            "campaign_id": campaign_id,
            "revision": 1,
            "fee_approval_id": approval_id,
        },
    )

    assert first.status_code == 409
    assert retry.status_code == 200, retry.get_json()
    assert retry.get_json()["success"] is True
    assert attempts == [([trade_id], None), ([trade_id], approval_id)]
    campaign = database.get_bootstrap_campaign(campaign_id)
    assert campaign["status"] == "stopped"
    assert campaign["revision"] == 1
