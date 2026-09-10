from __future__ import annotations

from unittest.mock import Mock
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
from datetime import datetime, timezone

import api_server
from blueprints import market


ASSET_ID = "b8" * 32


def test_market_confidence_endpoint_exposes_one_coherent_durable_snapshot(monkeypatch):
    monkeypatch.setitem(api_server._active_cat, "asset_id", ASSET_ID)
    snapshot = {
        "snapshot_id": "a" * 64,
        "asset_id": ASSET_ID,
        "state": "AMBER",
        "derived_at": "2026-09-10T12:00:00.000000Z",
        "trusted_midpoint": "0.0001",
        "trusted_bid": "0.00009",
        "trusted_ask": "0.00011",
        "degraded_since": None,
        "withdrawal_stage": "NONE",
        "recovery_refreshes": 0,
        "reason_codes": ["single_provider_dependency"],
        "source_health": {"dexie": "valid", "splash": "unavailable"},
        "evidence_digests": ["d" * 64],
        "material": True,
    }
    degraded = {
        "degraded_since": None,
        "recovery_started_at": None,
        "recovery_refreshes": 0,
        "last_confidence_state": "AMBER",
        "withdrawal_stage": "NONE",
        "updated_at": "2026-09-10T12:00:00.000000Z",
    }
    migration = {
        "migration_version": 1,
        "can_start": True,
        "reason_code": "POST_TIBET_MIGRATION_READY",
        "tibet_live_features": "retired",
    }
    monkeypatch.setattr(
        market.database, "get_latest_market_confidence_snapshot", Mock(return_value=snapshot)
    )
    monkeypatch.setattr(
        market.database, "get_degraded_market_state", Mock(return_value=degraded)
    )
    monkeypatch.setattr(
        market.database, "get_post_tibet_migration_report", Mock(return_value=migration)
    )
    monkeypatch.setattr(
        market.database,
        "get_market_provider_observations",
        Mock(
            return_value=[
                {
                    "provider_id": provider,
                    "capability": "order_book",
                    "quality": "valid",
                    "observed_at": "2999-01-01T00:00:00.000000Z",
                    "fresh_until": "2999-01-01T00:01:00.000000Z",
                    "payload_sha256": "d" * 64,
                    "reason_codes": [],
                }
                for provider in ("dexie", "splash")
            ]
        ),
    )
    monkeypatch.setattr(
        api_server,
        "bot",
        SimpleNamespace(
            _market_confidence_result=SimpleNamespace(
                independent_bid_depth_mojos=2_000_000_000_000,
                independent_ask_depth_mojos=3_000_000_000_000,
                required_depth_mojos=1_000_000_000_000,
                bid_depth_ratio=Decimal("2"),
                ask_depth_ratio=Decimal("3"),
                manipulation_score=12,
                pending_movement_refreshes=1,
                excluded_own_offer_count=2,
                deduplicated_offer_count=3,
                derived_thresholds={"manipulation_red": 80},
            )
        ),
    )
    monkeypatch.setattr(
        market,
        "_utc_now",
        lambda: datetime(2026, 9, 10, 12, 0, 10, tzinfo=timezone.utc),
        raising=False,
    )

    with api_server.app.test_request_context("/api/market/confidence"):
        response = market.api_market_confidence()

    payload = response.get_json()
    assert payload["market_model"] == "offer_book"
    assert payload["confidence"] == snapshot
    assert payload["degraded"] == degraded
    assert payload["migration"] == migration
    assert payload["providers"]["tibetswap"] == {
        "status": "retired",
        "capabilities": [],
    }
    assert payload["can_increase_exposure"] is False
    assert payload["metrics"]["independent_bid_depth_xch"] == "2"
    assert payload["metrics"]["independent_ask_depth_xch"] == "3"
    assert payload["metrics"]["required_depth_xch"] == "1"
    assert payload["metrics"]["manipulation_score"] == 12


def test_market_confidence_endpoint_ages_expired_provider_evidence(monkeypatch):
    monkeypatch.setitem(api_server._active_cat, "asset_id", ASSET_ID)
    monkeypatch.setattr(
        market.database,
        "get_latest_market_confidence_snapshot",
        Mock(
            return_value={
                "asset_id": ASSET_ID,
                "state": "GREEN",
                "derived_at": "2026-09-10T12:00:00.000000Z",
                "reason_codes": [],
                "source_health": {"dexie": "valid", "splash": "valid"},
                "evidence_digests": ["d" * 64],
            }
        ),
    )
    monkeypatch.setattr(
        market.database, "get_degraded_market_state", Mock(return_value=None)
    )
    monkeypatch.setattr(
        market.database, "get_post_tibet_migration_report", Mock(return_value=None)
    )
    monkeypatch.setattr(
        market.database,
        "get_market_provider_observations",
        Mock(
            return_value=[
                {
                    "provider_id": provider,
                    "capability": "order_book",
                    "quality": "valid",
                    "observed_at": "2026-09-10T12:00:00.000000Z",
                    "fresh_until": "2026-09-10T12:00:20.000000Z",
                    "payload_sha256": "d" * 64,
                    "reason_codes": [],
                }
                for provider in ("dexie", "splash")
            ]
        ),
    )
    monkeypatch.setattr(
        market,
        "_utc_now",
        lambda: datetime(2026, 9, 10, 12, 1, tzinfo=timezone.utc),
        raising=False,
    )

    with api_server.app.test_request_context("/api/market/confidence"):
        response = market.api_market_confidence()

    payload = response.get_json()
    assert payload["confidence"]["state"] == "RED"
    assert "market_evidence_expired" in payload["confidence"]["reason_codes"]
    assert payload["providers"]["dexie"]["status"] == "unavailable"
    assert payload["providers"]["splash"]["status"] == "unavailable"
    assert payload["can_create"] is False
    assert payload["can_requote"] is False


def test_market_confidence_rejects_newer_observation_not_bound_to_snapshot(
    monkeypatch,
):
    monkeypatch.setitem(api_server._active_cat, "asset_id", ASSET_ID)
    monkeypatch.setattr(
        market.database,
        "get_latest_market_confidence_snapshot",
        Mock(
            return_value={
                "asset_id": ASSET_ID,
                "state": "GREEN",
                "derived_at": "2026-09-10T12:00:00.000000Z",
                "reason_codes": [],
                "source_health": {"dexie": "valid"},
                "evidence_digests": ["d" * 64],
            }
        ),
    )
    monkeypatch.setattr(
        market.database, "get_degraded_market_state", Mock(return_value=None)
    )
    monkeypatch.setattr(
        market.database, "get_post_tibet_migration_report", Mock(return_value=None)
    )
    monkeypatch.setattr(
        market.database,
        "get_market_provider_observations",
        Mock(
            return_value=[
                {
                    "provider_id": "dexie",
                    "capability": "order_book",
                    "quality": "valid",
                    "observed_at": "2026-09-10T12:00:05.000000Z",
                    "fresh_until": "2026-09-10T12:00:25.000000Z",
                    "payload_sha256": "e" * 64,
                    "reason_codes": [],
                }
            ]
        ),
    )
    monkeypatch.setattr(
        market,
        "_utc_now",
        lambda: datetime(2026, 9, 10, 12, 0, 10, tzinfo=timezone.utc),
    )

    with api_server.app.test_request_context("/api/market/confidence"):
        payload = market.api_market_confidence().get_json()

    assert payload["confidence"]["state"] == "RED"
    assert "market_evidence_expired" in payload["confidence"]["reason_codes"]
    assert payload["providers"]["dexie"]["status"] == "unavailable"
    assert payload["can_create"] is False


def test_market_confidence_endpoint_fails_closed_while_evidence_is_warming(monkeypatch):
    monkeypatch.setitem(api_server._active_cat, "asset_id", ASSET_ID)
    monkeypatch.setattr(
        market.database, "get_latest_market_confidence_snapshot", Mock(return_value=None)
    )
    monkeypatch.setattr(
        market.database, "get_degraded_market_state", Mock(return_value=None)
    )
    monkeypatch.setattr(
        market.database, "get_post_tibet_migration_report", Mock(return_value=None)
    )

    with api_server.app.test_request_context("/api/market/confidence"):
        response = market.api_market_confidence()

    payload = response.get_json()
    assert payload["confidence"]["state"] == "RED"
    assert payload["confidence"]["reason_codes"] == ["market_evidence_warming"]
    assert payload["can_create"] is False
    assert payload["can_requote"] is False
    assert payload["can_increase_exposure"] is False


def test_dashboard_and_market_intel_render_offer_book_confidence_contract():
    html = (Path(__file__).resolve().parents[1] / "bot_gui.html").read_text(
        encoding="utf-8"
    )

    for element_id in (
        "marketConfidenceBar",
        "marketConfidenceState",
        "marketTrustedRange",
        "marketConfidenceReasons",
        "marketProviderHealth",
        "marketWithdrawalStage",
        "intelConfidenceTimeline",
        "derivedDepthThreshold",
        "derivedManipulationThreshold",
        "derivedChurnLimit",
    ):
        assert f'id="{element_id}"' in html
    assert "apiFetch('/api/market/confidence'" in html
    assert "function renderMarketConfidence" in html
    assert "TibetSwap Live AMM" not in html
    assert "Source · TibetSwap" not in html
    assert "Dexie vs Tibet" not in html
    assert "Arb Sniper" not in html
    assert "TibetSwap shut down" in html
    assert 'id="mktAskDepth"' in html
    assert 'id="mktTibetDepth"' not in html
    assert "function renderMarketSummaryVenueState" not in html


def test_retired_amm_controls_are_not_user_visible():
    html = (Path(__file__).resolve().parents[1] / "bot_gui.html").read_text(
        encoding="utf-8"
    )

    assert 'data-key="SNIPER_ENABLED" hidden' in html
    assert 'id="pnlSniperStatsPanel" hidden' in html
    assert 'id="boostBtn" hidden' in html
    assert 'id="ccTibetLink"' not in html
    assert "Confidence State" in html
    assert "Required Independent Depth" in html
    assert "Withdrawal Stage" in html
    market_health = html[html.index("function updateMarketHealth"):]
    market_health = market_health[: market_health.index("function mergeStatusRiskIntoDashboard")]
    assert "tibetReferenceUnavailable" not in market_health
    assert "confidenceData.confidence" in market_health


def test_post_tibet_help_and_about_describe_provider_authority_truthfully():
    html = (Path(__file__).resolve().parents[1] / "bot_gui.html").read_text(
        encoding="utf-8"
    )

    assert "Sage is the wallet and transaction authority" in html
    assert "Dexie is the primary attributable offer book" in html
    assert "Splash provides peer discovery and publication evidence" in html
    assert "Coinset and Spacescan provide corroborating chain evidence" in html
    assert "historical TibetSwap data is retained as read-only history" in html


def test_live_ui_does_not_poll_retired_tibetswap_endpoints():
    html = (Path(__file__).resolve().parents[1] / "bot_gui.html").read_text(
        encoding="utf-8"
    )

    assert "function pollAmmPrice" not in html
    assert "`${API_URL}/amm/price`" not in html
    assert "`${API_URL}/market/slippage`" not in html


def test_native_bridge_exposes_same_market_confidence_snapshot(monkeypatch):
    import app_bridge

    monkeypatch.setattr(
        api_server,
        "api_market_confidence",
        Mock(
            side_effect=lambda: api_server.jsonify(
                {"success": True, "confidence": {"state": "AMBER"}}
            )
        ),
        raising=False,
    )

    result = app_bridge.AppBridge().get_market_confidence()

    assert result["success"] is True
    assert result["confidence"]["state"] == "AMBER"
    assert "get_market_confidence" in app_bridge._APP_BRIDGE_READ_ONLY_METHODS


def test_active_offers_expose_durable_publication_and_discovery_authority(monkeypatch):
    from blueprints import offers

    wallet_offer = {"trade_id": "trade-1", "status": "PENDING_ACCEPT"}
    monkeypatch.setattr(
        api_server,
        "bot",
        SimpleNamespace(
            offer_manager=SimpleNamespace(
                sync_from_wallet=Mock(return_value=([wallet_offer], [], None))
            )
        ),
    )
    monkeypatch.setattr(
        offers.database,
        "get_offer_intent_by_trade_id",
        Mock(
            return_value={
                "intent_id": "intent-1",
                "lifecycle_state": "visible",
                "generation": 2,
                "publication_identity": "publication-identity",
                "first_visible_at": "2026-09-10T12:00:00.000000Z",
                "parent_intent_id": "intent-0",
                "child_intent_id": None,
                "updated_at": "2026-09-10T12:00:01.000000Z",
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(
        offers.database,
        "list_publication_outbox",
        Mock(
            return_value=[
                {
                    "publisher": "dexie",
                    "state": "succeeded",
                    "queued_at": "2026-09-10T11:59:59.000000Z",
                    "updated_at": "2026-09-10T12:00:00.000000Z",
                    "terminal_at": "2026-09-10T12:00:00.000000Z",
                },
                {
                    "publisher": "splash",
                    "state": "retryable",
                    "queued_at": "2026-09-10T11:59:59.000000Z",
                    "updated_at": "2026-09-10T12:00:01.000000Z",
                    "terminal_at": None,
                },
            ]
        ),
        raising=False,
    )
    monkeypatch.setattr(
        offers.database,
        "get_offer_publication_discoveries",
        Mock(
            return_value=[
                {
                    "provider": "dexie",
                    "state": "exact",
                    "deadline_at": "2026-09-10T12:01:30.000000Z",
                    "first_observed_at": "2026-09-10T12:00:00.000000Z",
                    "observed_identity": "d" * 64,
                },
                {
                    "provider": "splash",
                    "state": "pending",
                    "deadline_at": "2026-09-10T12:01:30.000000Z",
                    "first_observed_at": None,
                    "observed_identity": None,
                },
            ]
        ),
        raising=False,
    )

    with api_server.app.test_request_context("/api/offers"):
        payload = offers.api_offers().get_json()

    row = payload["buys"][0]
    assert row["authority"]["intent_id"] == "intent-1"
    assert row["authority"]["generation"] == 2
    assert row["discovery"] == {
        "state": "visible",
        "provider_identity": "publication-identity",
        "first_visible_at": "2026-09-10T12:00:00.000000Z",
        "providers": {
            "dexie": {
                "state": "exact",
                "deadline_at": "2026-09-10T12:01:30.000000Z",
                "first_observed_at": "2026-09-10T12:00:00.000000Z",
                "observed_identity": "d" * 64,
            },
            "splash": {
                "state": "pending",
                "deadline_at": "2026-09-10T12:01:30.000000Z",
                "first_observed_at": None,
                "observed_identity": None,
            },
        },
    }
    assert row["publication"]["dexie"]["state"] == "succeeded"
    assert row["publication"]["splash"]["state"] == "retryable"
    assert row["discovery"]["providers"]["dexie"]["state"] == "exact"
    assert row["discovery"]["providers"]["splash"]["state"] == "pending"


def test_offers_ui_surfaces_publication_discovery_and_confirmed_fill_authority():
    html = (Path(__file__).resolve().parents[1] / "bot_gui.html").read_text(
        encoding="utf-8"
    )

    assert "Publication:" in html
    assert "Discovery:" in html
    assert "fill_confidence" in html
    assert "Confirmed evidence" in html


def test_fills_endpoint_labels_only_authoritative_rows_as_confirmed(monkeypatch):
    from blueprints import offers

    monkeypatch.setattr(api_server, "bot", SimpleNamespace())
    monkeypatch.setattr(api_server.cfg, "CAT_ASSET_ID", ASSET_ID)
    monkeypatch.setattr(
        offers.database,
        "get_fills",
        Mock(return_value=[{"fill_id": 7, "trade_id": "trade-7"}]),
        raising=False,
    )
    monkeypatch.setattr(
        offers.database,
        "get_authoritative_fill_by_id",
        Mock(
            return_value={
                "fill_id": 7,
                "spent_block_height": 123,
                "transaction_id": "a" * 64,
                "evidence_sha256": "b" * 64,
            }
        ),
        raising=False,
    )

    with api_server.app.test_request_context("/api/fills"):
        response = offers.api_fills()

    row = response.get_json()["fills"][0]
    assert row["fill_confidence"] == "Confirmed"
    assert row["fill_authority"]["spent_block_height"] == 123
    assert row["fill_authority"]["transaction_id"] == "a" * 64


def test_prestart_status_does_not_warn_when_operator_has_not_selected_a_pair(monkeypatch):
    from blueprints import bot as bot_blueprint

    events = Mock()
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setitem(api_server._active_cat, "asset_id", None)
    monkeypatch.setattr(api_server.cfg, "CAT_ASSET_ID", "")
    monkeypatch.setattr(bot_blueprint, "log_event", events)

    with api_server.app.test_request_context("/api/status"):
        response = bot_blueprint.api_status()

    assert response.status_code == 200
    assert all(
        not (call.args and call.args[0] in {"warning", "error"})
        for call in events.call_args_list
    )
