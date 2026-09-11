from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import inspect
from types import SimpleNamespace

import database
import pytest
from market_runtime import OfferBookMarketRuntime


ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "market-runtime.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def _book():
    return {
        "bids": [
            {"offer_id": "buy-1", "price": "0.00009", "amount_mojos": 3_000_000_000_000}
        ],
        "asks": [
            {
                "offer_id": "sell-1",
                "price": "0.00011",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
    }


def _splash():
    return [
        {
            "offer_id": "splash-buy",
            "side": "buy",
            "price": "0.00009",
            "amount_mojos": 3_000_000_000_000,
        },
        {
            "offer_id": "splash-sell",
            "side": "sell",
            "price": "0.00011",
            "amount_mojos": 3_000_000_000_000,
        },
    ]


def test_runtime_persists_one_coherent_green_decision(isolated_db):
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda asset_id: _book(),
        fetch_splash_offers=lambda asset_id: _splash(),
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )

    result = runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )

    assert result.confidence.state == "GREEN"
    assert result.confidence.trusted_midpoint is not None
    assert result.degraded.can_create is True
    assert result.degraded.can_requote is True
    stored = database.get_latest_market_confidence_snapshot(ASSET_ID)
    assert stored["state"] == "GREEN"
    assert stored["snapshot_id"] == result.snapshot_id
    providers = database.get_market_provider_observations(ASSET_ID, limit=10)
    assert {row["provider_id"] for row in providers} == {"dexie", "splash"}


def test_runtime_fails_closed_when_only_our_offers_remain(isolated_db):
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda asset_id: _book(),
        fetch_splash_offers=lambda asset_id: [],
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 1,
        },
    )

    result = runtime.refresh(
        own_offer_identities=frozenset({"buy-1", "sell-1"}),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )

    assert result.confidence.state == "RED"
    assert result.degraded.can_create is False
    assert result.degraded.can_requote is False
    assert result.degraded.cancel_tiers == ("inner",)
    assert "one_sided_book" in result.confidence.reason_codes


def test_bot_own_offer_identities_include_durable_offer_fingerprints(monkeypatch):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    monkeypatch.setattr(
        bot_loop,
        "get_open_offers",
        lambda cat_asset_id=None: [
            {"trade_id": "trade-1", "dexie_id": "dexie-1", "coin_id": "coin-1"}
        ],
    )
    monkeypatch.setattr(
        bot_loop,
        "get_active_offer_market_identities",
        lambda asset_id: frozenset(
            {"intent-trade-1", "offer-fingerprint-1", "dexie:offer-fingerprint-1"}
        ),
        raising=False,
    )

    identities = loop._market_own_offer_identities(ASSET_ID)

    assert {
        "trade-1",
        "dexie-1",
        "coin-1",
        "intent-trade-1",
        "offer-fingerprint-1",
        "dexie:offer-fingerprint-1",
    } <= identities


def test_active_intent_market_identities_bridge_dexie_fingerprint_space(isolated_db):
    offer_text_sha256 = hashlib.sha256(b"exact-offer").hexdigest()
    trade_id = hashlib.sha256(b"sage-trade").hexdigest()
    coin_id = hashlib.sha256(b"input-coin").hexdigest()
    at = NOW.isoformat().replace("+00:00", "Z")
    database.prepare_offer_intent(
        intent_id="intent-market-identity",
        operation_id="create:intent-market-identity",
        event_id="create:intent-market-identity:prepared",
        run_id="run:test",
        wallet_fingerprint_hash=hashlib.sha256(b"wallet").hexdigest(),
        network="mainnet",
        asset_id=ASSET_ID,
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key="slot:market-identity",
        generation=1,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[coin_id],
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"phase": "prepared"},
        prepared_at=at,
    )
    database.finalize_offer_intent(
        intent_id="intent-market-identity",
        operation_id="create:intent-market-identity",
        event_id="create:intent-market-identity:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=offer_text_sha256,
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"phase": "confirmed"},
        finalized_at=at,
    )

    identities = database.get_active_offer_market_identities(ASSET_ID)

    assert {trade_id, offer_text_sha256, coin_id} <= identities


def test_restart_hydrates_trusted_price_and_rejects_a_hard_move(isolated_db):
    baseline = _book()
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: baseline,
        fetch_splash_offers=lambda _asset: _splash(),
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    original = runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )
    moved = {
        "bids": [
            {
                "offer_id": "moved-bid",
                "price": "0.00014",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
        "asks": [
            {
                "offer_id": "moved-ask",
                "price": "0.00016",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
    }
    restarted = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: moved,
        fetch_splash_offers=lambda _asset: [
            {
                "offer_id": "s-moved-bid",
                "side": "buy",
                "price": "0.00014",
                "amount_mojos": 3_000_000_000_000,
            },
            {
                "offer_id": "s-moved-ask",
                "side": "sell",
                "price": "0.00016",
                "amount_mojos": 3_000_000_000_000,
            },
        ],
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )

    result = restarted.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=20),
    )

    assert result.confidence.state == "RED"
    assert result.confidence.trusted_midpoint == original.confidence.trusted_midpoint
    assert "hard_price_move_cap" in result.confidence.reason_codes


def test_restart_preserves_pending_movement_state(isolated_db):
    current_book = _book()
    current_splash = _splash()
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: current_book,
        fetch_splash_offers=lambda _asset: current_splash,
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )
    current_book = {
        "bids": [
            {
                "offer_id": "buy-1",
                "price": "0.000104",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
        "asks": [
            {
                "offer_id": "sell-1",
                "price": "0.000116",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
    }
    current_splash = [
        {
            "offer_id": "splash-buy",
            "side": "buy",
            "price": "0.000104",
            "amount_mojos": 3_000_000_000_000,
        },
        {
            "offer_id": "splash-sell",
            "side": "sell",
            "price": "0.000116",
            "amount_mojos": 3_000_000_000_000,
        },
    ]
    first = runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=20),
    )
    assert first.confidence.pending_movement_refreshes == 1

    restarted = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: current_book,
        fetch_splash_offers=lambda _asset: current_splash,
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    second = restarted.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=40),
    )

    assert "movement_persistence_satisfied" in second.confidence.reason_codes
    assert second.confidence.trusted_midpoint == Decimal("0.00011")


def test_fresh_dexie_settled_trade_confirms_material_move_and_is_persisted(isolated_db):
    current_book = _book()
    current_splash = _splash()
    current_trades = []
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: current_book,
        fetch_dexie_settled_trades=lambda _asset: current_trades,
        fetch_splash_offers=lambda _asset: current_splash,
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )
    current_book = {
        "bids": [
            {
                "offer_id": "buy-1",
                "price": "0.000104",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
        "asks": [
            {
                "offer_id": "sell-1",
                "price": "0.000116",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
    }
    current_splash = [
        {
            "offer_id": "splash-buy",
            "side": "buy",
            "price": "0.000104",
            "amount_mojos": 3_000_000_000_000,
        },
        {
            "offer_id": "splash-sell",
            "side": "sell",
            "price": "0.000116",
            "amount_mojos": 3_000_000_000_000,
        },
    ]
    current_trades = [
        {
            "trade_id": "confirming-trade",
            "price": "0.00011",
            "base_volume": "1000",
            "target_volume": "0.11",
            "trade_timestamp": int((NOW + timedelta(seconds=19)).timestamp() * 1000),
            "type": "buy",
        }
    ]

    result = runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=20),
    )

    assert result.confidence.state == "GREEN"
    assert result.confidence.trusted_midpoint == Decimal("0.00011")
    assert "settled_trade_confirmed_move" in result.confidence.reason_codes
    observations = database.get_market_provider_observations(ASSET_ID, limit=10)
    settled = [row for row in observations if row["capability"] == "settled_trades"]
    assert settled
    assert settled[0]["payload_sha256"] in result.confidence.evidence_digests


def test_dust_dexie_trade_cannot_confirm_material_move(isolated_db):
    current_book = _book()
    current_splash = _splash()
    current_trades = []
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: current_book,
        fetch_dexie_settled_trades=lambda _asset: current_trades,
        fetch_splash_offers=lambda _asset: current_splash,
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )
    current_book = {
        "bids": [
            {
                "offer_id": "buy-1",
                "price": "0.000104",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
        "asks": [
            {
                "offer_id": "sell-1",
                "price": "0.000116",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
    }
    current_splash = [
        {
            "offer_id": "splash-buy",
            "side": "buy",
            "price": "0.000104",
            "amount_mojos": 3_000_000_000_000,
        },
        {
            "offer_id": "splash-sell",
            "side": "sell",
            "price": "0.000116",
            "amount_mojos": 3_000_000_000_000,
        },
    ]
    current_trades = [
        {
            "trade_id": "dust-confirmation",
            "price": "0.00011",
            "base_volume": "0.000001",
            "target_volume": "0.000000000001",
            "trade_timestamp": int((NOW + timedelta(seconds=19)).timestamp() * 1000),
            "type": "buy",
        }
    ]

    result = runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=20),
    )

    assert result.confidence.state == "AMBER"
    assert result.confidence.trusted_midpoint == Decimal("0.0001")
    assert "material_move_pending_confirmation" in result.confidence.reason_codes
    assert "settled_trade_confirmed_move" not in result.confidence.reason_codes
    observations = database.get_market_provider_observations(ASSET_ID, limit=10)
    assert any(row["capability"] == "settled_trades" for row in observations)


def test_restart_preserves_prior_offer_ids_for_churn_detection(isolated_db):
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: _book(),
        fetch_splash_offers=lambda _asset: _splash(),
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )
    changed = {
        "bids": [
            {
                "offer_id": "changed-bid",
                "price": "0.00009",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
        "asks": [
            {
                "offer_id": "changed-ask",
                "price": "0.00011",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
    }
    restarted = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: changed,
        fetch_splash_offers=lambda _asset: [],
        fetch_splash_health=lambda: {
            "running": False,
            "api_reachable": False,
            "peers": 0,
        },
    )

    result = restarted.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=20),
    )

    assert result.confidence.manipulation_score > 0
    assert "rapid_offer_churn" in result.confidence.reason_codes


def test_restart_tolerates_a_persisted_empty_offer_book(isolated_db):
    unavailable = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: {"bids": [], "asks": []},
        fetch_splash_offers=lambda _asset: [],
        fetch_splash_health=lambda: {
            "running": False,
            "api_reachable": False,
            "peers": 0,
        },
    )
    first = unavailable.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )

    persisted = database.get_market_confidence_engine_state(ASSET_ID)
    assert first.confidence.state == "RED"
    assert persisted["prior_offer_ids"] == []
    assert persisted["prior_observed_at"] is None

    restarted = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: _book(),
        fetch_splash_offers=lambda _asset: _splash(),
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    recovered = restarted.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=20),
    )

    assert recovered.confidence.state == "GREEN"


def test_bot_rebuilds_market_runtime_when_risk_preset_changes(isolated_db, monkeypatch):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._market_runtime = None
    loop._market_runtime_asset_id = ""
    loop._market_runtime_risk_preset = ""
    loop._market_refresh_now = NOW
    loop.market_intel = SimpleNamespace(
        refresh_orderbook=lambda force=False: None,
        get_attributable_orderbook=lambda: {
            **_book(),
            "source_time": NOW.isoformat().replace("+00:00", "Z"),
        },
    )
    loop.splash_node = SimpleNamespace(
        get_status=lambda: {
            "process_running": False,
            "api_reachable": False,
            "metrics": {"peers": 0},
        }
    )
    loop._splash_confidence_offers = {}
    loop._splash_confidence_lock = __import__("threading").Lock()
    monkeypatch.setattr(bot_loop.cfg, "MARKET_RISK_PRESET", "balanced", raising=False)

    balanced = loop._ensure_market_runtime(ASSET_ID)
    monkeypatch.setattr(bot_loop.cfg, "MARKET_RISK_PRESET", "aggressive", raising=False)
    aggressive = loop._ensure_market_runtime(ASSET_ID)

    assert aggressive is not balanced
    assert aggressive._engine.risk_preset == "aggressive"


def test_runtime_rebases_persisted_confidence_state_when_risk_preset_changes(
    isolated_db,
):
    balanced = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: _book(),
        fetch_splash_offers=lambda _asset: _splash(),
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    balanced.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )
    before = balanced._engine.export_state()

    aggressive = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="aggressive",
        fetch_dexie_book=lambda _asset: _book(),
        fetch_splash_offers=lambda _asset: _splash(),
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    after = aggressive._engine.export_state()

    assert after["risk_preset"] == "aggressive"
    assert after["last_trusted_midpoint"] == before["last_trusted_midpoint"]
    assert after["last_trusted_bid"] == before["last_trusted_bid"]
    assert after["last_trusted_ask"] == before["last_trusted_ask"]
    assert after["prior_offer_ids"] == before["prior_offer_ids"]
    assert after["prior_observed_at"] == before["prior_observed_at"]
    assert after["pending_midpoint"] is None
    assert after["pending_refreshes"] == 0


def test_first_large_move_after_risk_preset_rebase_still_hard_blocks(isolated_db):
    balanced = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset: _book(),
        fetch_splash_offers=lambda _asset: _splash(),
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    balanced.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )
    moved_book = {
        "bids": [
            {
                "offer_id": "moved-buy",
                "price": "0.000139",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
        "asks": [
            {
                "offer_id": "moved-sell",
                "price": "0.000141",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
    }
    moved_splash = [
        {
            "offer_id": "splash-moved-buy",
            "side": "buy",
            "price": "0.000139",
            "amount_mojos": 3_000_000_000_000,
        },
        {
            "offer_id": "splash-moved-sell",
            "side": "sell",
            "price": "0.000141",
            "amount_mojos": 3_000_000_000_000,
        },
    ]

    aggressive = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="aggressive",
        fetch_dexie_book=lambda _asset: moved_book,
        fetch_splash_offers=lambda _asset: moved_splash,
        fetch_splash_health=lambda: {
            "running": True,
            "api_reachable": True,
            "peers": 2,
        },
    )
    result = aggressive.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=20),
    )

    assert result.confidence.derived_thresholds["hard_move_cap_bps"] == 2500
    assert result.confidence.state == "RED"
    assert "hard_price_move_cap" in result.confidence.reason_codes
    assert result.confidence.trusted_midpoint == Decimal("0.0001")


def test_bot_runtime_phase_gate_blocks_exposure_but_never_safety_cancel(monkeypatch):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._market_runtime_required = True
    loop._market_degraded_decision = SimpleNamespace(
        can_create=False,
        can_requote=False,
    )
    monkeypatch.setattr(loop, "_runtime_recovery_cycle_boundary", lambda: True)
    loop._runtime_recovery_monotonic = lambda: 1
    loop._runtime_recovery_wall_clock = lambda: NOW
    loop._runtime_recovery_gap_seconds = 10
    loop._runtime_recovery_skew_seconds = 2

    assert loop._enter_runtime_effect_phase("create") is False
    assert loop._enter_runtime_effect_phase("publication") is False
    assert loop._enter_runtime_effect_phase("requote") is False
    assert loop._enter_runtime_effect_phase("cancel") is True
    assert loop._enter_runtime_effect_phase("trim") is True


def test_bot_runtime_phase_gate_fails_closed_before_first_confidence_refresh(
    monkeypatch,
):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._market_runtime_required = True
    loop._market_degraded_decision = None
    monkeypatch.setattr(loop, "_runtime_recovery_cycle_boundary", lambda: True)
    loop._runtime_recovery_monotonic = lambda: 1
    loop._runtime_recovery_wall_clock = lambda: NOW
    loop._runtime_recovery_gap_seconds = 10
    loop._runtime_recovery_skew_seconds = 2

    assert loop._enter_runtime_effect_phase("create") is False
    assert loop._enter_runtime_effect_phase("cancel") is True


def test_bot_records_exact_splash_offer_for_confidence():
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._splash_confidence_offers = {}
    loop._splash_confidence_lock = __import__("threading").Lock()
    classified = {
        "relevant": True,
        "side": "sell",
        "summary": {
            "offered": {ASSET_ID: 12_500_000},
            "requested": {"xch": 1_000_000_000_000},
        },
    }

    assert (
        loop._remember_splash_confidence_offer(
            fingerprint="splash-offer-1",
            classified=classified,
            observed_at=NOW,
        )
        is True
    )

    row = loop._get_fresh_splash_confidence_offers(ASSET_ID, now=NOW)[0]
    assert row == {
        "offer_id": "splash-offer-1",
        "side": "sell",
        "price": "0.00008",
        "amount_mojos": 1_000_000_000_000,
    }


def test_bot_preserves_whole_number_splash_confidence_price():
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._splash_confidence_offers = {}
    loop._splash_confidence_lock = __import__("threading").Lock()
    classified = {
        "relevant": True,
        "side": "sell",
        "summary": {
            "offered": {ASSET_ID: 1_000},
            "requested": {"xch": 10_000_000_000_000},
        },
    }

    assert loop._remember_splash_confidence_offer(
        fingerprint="whole-number-splash-offer",
        classified=classified,
        observed_at=NOW,
    )

    row = loop._get_fresh_splash_confidence_offers(ASSET_ID, now=NOW)[0]
    assert row["price"] == "10"


def test_market_withdrawal_cancels_only_requested_tiers(monkeypatch):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    cancelled = []
    loop.offer_manager = SimpleNamespace(
        cancel_offers=lambda ids, **kwargs: cancelled.extend(ids) or {}
    )
    monkeypatch.setattr(
        loop, "_enter_runtime_effect_phase", lambda phase: phase == "cancel"
    )
    monkeypatch.setattr(
        bot_loop,
        "get_open_offers",
        lambda cat_asset_id=None: [
            {"trade_id": "inner", "tier": "inner"},
            {"trade_id": "mid", "tier": "mid"},
            {"trade_id": "outer", "tier": "outer"},
        ],
        raising=False,
    )

    loop._apply_market_withdrawal(
        SimpleNamespace(
            cancel_tiers=("inner", "middle"), reason_code="MARKET_DEGRADED_MIDDLE"
        )
    )

    assert cancelled == ["inner", "mid"]


def test_trading_cycle_prices_mutations_from_offer_book_confidence_only():
    import bot_loop

    source = inspect.getsource(bot_loop.BotLoop._run_one_cycle)

    assert "_refresh_offer_book_market" in source
    assert "self.price_engine.get_price(" not in source
    assert "both oracles (Dexie + TibetSwap)" not in source


def test_all_mutation_adjacent_price_reads_use_offer_book_confidence_only():
    import bot_loop

    methods = (
        bot_loop.BotLoop._refresh_price_if_mempool_move_pending,
        bot_loop.BotLoop._startup_sync,
        bot_loop.BotLoop._create_offers_if_needed,
        bot_loop.BotLoop.graceful_config_change,
    )

    for method in methods:
        source = inspect.getsource(method)
        assert "self.price_engine.get_price(" not in source, method.__name__
