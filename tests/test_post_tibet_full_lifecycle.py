"""End-to-end acceptance harness for the post-TibetSwap trading lifecycle.

The test deliberately uses the in-process mock wallet and an isolated durable
database.  It exercises real policy, coin splitting, offer creation,
publication/discovery, degraded-market gating, fill authority, replacement
backoff, bulk cancellation, and restart recovery without touching live funds
or network services.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import bot_loop
import database
import mock_wallet
import pytest
from coin_prep_policy import exclude_retired_sniper_pools
from fill_classifier import FillConfidence, assess_fill_confidence
from market_runtime import OfferBookMarketRuntime
from offer_book_policy import derive_offer_book_policy
from offer_lifecycle import OfferDiscoveryTracker


ASSET_ID = "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105"
NOW = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
AT = "2026-09-10T20:00:00.000000Z"
LATER = "2026-09-10T20:00:05.000000Z"
LEASE_END = "2026-09-10T20:00:30.000000Z"
TX_ID = "cd" * 32


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "full-lifecycle.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield database
    database.close_connection()


def _independent_book():
    return {
        "bids": [
            {
                "offer_id": _sha("independent-dexie-buy"),
                "price": "0.00009",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
        "asks": [
            {
                "offer_id": _sha("independent-dexie-sell"),
                "price": "0.00011",
                "amount_mojos": 3_000_000_000_000,
            }
        ],
    }


def _independent_splash():
    return [
        {
            "offer_id": _sha("independent-splash-buy"),
            "side": "buy",
            "price": "0.00009",
            "amount_mojos": 3_000_000_000_000,
        },
        {
            "offer_id": _sha("independent-splash-sell"),
            "side": "sell",
            "price": "0.00011",
            "amount_mojos": 3_000_000_000_000,
        },
    ]


def _persist_created_offer(
    db, *, intent_id: str, generation: int, trade_id: str, offer_text: str
):
    offer_identity = _sha(offer_text)
    selected_coin_id = _sha(f"coin:{intent_id}")
    db.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="mock-acceptance-run",
        wallet_fingerprint_hash=_sha("736588221"),
        network="mainnet",
        asset_id=ASSET_ID,
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key="buy:inner:0",
        generation=generation,
        offered_amount_atomic="1000000000000",
        requested_amount_atomic="10000000",
        selected_coin_ids_json=[selected_coin_id],
        cat_decimals=3,
        fee_mojos_xch=13_079_100,
        wallet_identity_json={
            "network": "mainnet",
            "fingerprint": 736588221,
            "wallet_id": 2,
        },
        evidence_json={"phase": "prepared", "wallet": "mock"},
        prepared_at=AT,
    )
    intent = db.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=offer_identity,
        wallet_identity_json={"network": "mainnet", "fingerprint": 736588221},
        evidence_json={"phase": "confirmed", "wallet": "mock"},
        finalized_at=LATER,
    )
    assert db.add_offer(
        trade_id=trade_id,
        side="buy",
        price_xch=Decimal("0.0001"),
        size_xch=Decimal("1"),
        size_cat=Decimal("10000"),
        cat_asset_id=ASSET_ID,
        tier="inner",
        fee_mojos_xch=13_079_100,
    )
    assert db.update_offer_bech32(trade_id, offer_text)
    return intent, offer_identity


def test_coin_prep_ignores_legacy_sniper_configuration_after_tibetswap_retirement():
    """Old hidden sniper settings must never create retired prep cohorts."""

    xch_counts, cat_counts, tier_sizes = exclude_retired_sniper_pools(
        {"inner": 4, "sniper": 9},
        {"outer": 3, "sniper": 9},
        {
            "inner": Decimal("0.25"),
            "outer": Decimal("0.75"),
            "sniper": Decimal("0.01"),
        },
    )

    assert xch_counts == {"inner": 4}
    assert cat_counts == {"outer": 3}
    assert tier_sizes == {
        "inner": Decimal("0.25"),
        "outer": Decimal("0.75"),
    }


def test_full_mock_wallet_lifecycle_survives_outage_fill_cancel_and_restart(
    isolated_db, monkeypatch
):
    """One deterministic lifecycle covers every v1.4 mutation boundary."""

    mock_wallet.reset_mock()

    # Balanced Smart Settings are derived exclusively from offer-book inputs,
    # and the profitability floor includes creation plus expected re-quote fees.
    policy = derive_offer_book_policy(
        risk_profile="balanced",
        configured_offer_size_xch=Decimal("1"),
        independent_depth_xch=Decimal("12"),
        volatility_bps=Decimal("20"),
        churn_score=10,
        network_fee_xch=Decimal("0.0000130791"),
        expected_cancel_requotes=2,
        minimum_profit_xch=Decimal("0.0001"),
    )
    assert policy["market_model"] == "offer_book"
    assert Decimal(policy["profit_floor_xch"]) == Decimal("0.0001392373")
    assert policy["opportunity_orders"]["enabled"] is True

    # Coin Prep creates dedicated fee and CAT cohorts of deliberately different
    # sizes, matching the cross-PC scenario that previously took too long.
    # The 10 XCH Balanced fixture resolves to the bounded 30-coin fee cohort;
    # the Smart Defaults route calculation itself has focused route coverage.
    fee_count = 30
    xch_source = mock_wallet.state.xch_coins[0]["id"]
    cat_source = mock_wallet.state.cat_coins[0]["id"]
    assert mock_wallet.split_coins_rpc(
        1,
        xch_source,
        fee_count,
        1_000_000_000,
        fee_mojos=13_079_100,
    )["success"]
    assert mock_wallet.split_coins_rpc(
        2,
        cat_source,
        4,
        250_000,
        fee_mojos=13_079_100,
        is_cat=True,
    )["success"]
    unspent_xch = [
        coin for coin in mock_wallet.state.xch_coins if coin["spent_block_index"] == 0
    ]
    unspent_cat = [
        coin for coin in mock_wallet.state.cat_coins if coin["spent_block_index"] == 0
    ]
    assert sum(c["coin"]["amount"] == 1_000_000_000 for c in unspent_xch) == fee_count
    assert sum(c["coin"]["amount"] == 250_000 for c in unspent_cat) == 4

    # Start the simulated live cycle by creating a real mock-wallet offer and
    # crossing the durable prepare/finalize boundary before publication.
    created = mock_wallet.create_offer(
        {"1": -1_000_000_000_000, "2": 10_000_000},
        validate_only=False,
        max_time=int(NOW.timestamp()) + 3600,
    )
    assert created["success"] is True
    trade_id = created["trade_id"]
    offer_text = created["offer"]
    intent, offer_identity = _persist_created_offer(
        isolated_db,
        intent_id="acceptance-offer-1",
        generation=1,
        trade_id=trade_id,
        offer_text=offer_text,
    )

    outbox = isolated_db.list_publication_outbox(intent_id=intent["intent_id"])
    assert {row["publisher"] for row in outbox} == {"dexie", "splash"}
    claim = isolated_db.claim_publication_outbox(
        publisher="dexie",
        owner_run_id="mock-publisher",
        claim_token="dexie-claim-1",
        claimed_at=LATER,
        claim_expires_at=LEASE_END,
    )
    assert claim is not None
    published = isolated_db.complete_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id="mock-publisher",
        claim_token="dexie-claim-1",
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        acknowledgement_json={"provider_response_id": "dexie-acceptance-1"},
        completed_at="2026-09-10T20:00:10.000000Z",
    )
    assert published["state"] == "succeeded"

    tracker = OfferDiscoveryTracker(offer_identity=offer_identity, created_at=NOW)
    tracker.record_submission(provider="dexie", succeeded=True)
    tracker.record_submission(provider="splash", succeeded=False)
    tracker.record_discovery(provider="dexie", observed_offer_identity=offer_identity)
    assert tracker.evaluate(now=NOW + timedelta(seconds=15)).action == "KEEP_LIVE"
    exact = isolated_db.record_offer_publication_discovery(
        intent["intent_id"],
        provider="dexie",
        observed_offer_identity=offer_identity,
        observed_at="2026-09-10T20:00:15.000000Z",
    )
    assert exact["state"] == "exact"
    visible = isolated_db.record_offer_intent_visibility(
        intent["intent_id"],
        publication_identity=intent["publication_identity"],
        visible_at="2026-09-10T20:00:15.000000Z",
    )
    assert visible["intent"]["lifecycle_state"] == "visible"

    # A healthy independent book permits operation. A Dexie outage plus no
    # Splash peers turns the same runtime RED; exposure mutations stop while
    # safety cancellation remains available. Recovery needs three green reads
    # over at least sixty seconds, including across the persisted controller.
    provider = {
        "dexie": _independent_book(),
        "splash": _independent_splash(),
        "health": {"running": True, "api_reachable": True, "peers": 2},
    }
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset_id: provider["dexie"],
        fetch_splash_offers=lambda _asset_id: provider["splash"],
        fetch_splash_health=lambda: provider["health"],
    )
    green = runtime.refresh(
        own_offer_identities=frozenset({offer_identity}),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=20),
    )
    assert green.confidence.state == "GREEN"
    assert green.degraded.can_create is True

    provider["dexie"] = RuntimeError("Dexie outage")
    provider["splash"] = []
    provider["health"] = {"running": True, "api_reachable": True, "peers": 0}
    red = runtime.refresh(
        own_offer_identities=frozenset({offer_identity}),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(seconds=30),
    )
    assert red.confidence.state == "RED"
    assert red.degraded.can_create is False
    assert red.degraded.can_requote is False

    gate = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    gate._market_runtime_required = True
    gate._market_degraded_decision = red.degraded
    monkeypatch.setattr(gate, "_runtime_recovery_cycle_boundary", lambda: True)
    gate._runtime_recovery_monotonic = lambda: 1
    gate._runtime_recovery_wall_clock = lambda: NOW
    gate._runtime_recovery_gap_seconds = 10
    gate._runtime_recovery_skew_seconds = 2
    wallet_effects_before = mock_wallet.get_mock_stats()["total_offers_created"]
    assert gate._enter_runtime_effect_phase("create") is False
    assert gate._enter_runtime_effect_phase("publication") is False
    assert gate._enter_runtime_effect_phase("requote") is False
    assert gate._enter_runtime_effect_phase("cancel") is True
    assert mock_wallet.get_mock_stats()["total_offers_created"] == wallet_effects_before

    provider["dexie"] = _independent_book()
    provider["splash"] = _independent_splash()
    provider["health"] = {"running": True, "api_reachable": True, "peers": 2}
    for offset in (11 * 60, 11 * 60 + 30):
        recovering = runtime.refresh(
            own_offer_identities=frozenset({offer_identity}),
            configured_offer_size_mojos=1_000_000_000_000,
            now=NOW + timedelta(seconds=offset),
        )
        assert recovering.degraded.can_create is False
    recovered = runtime.refresh(
        own_offer_identities=frozenset({offer_identity}),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW + timedelta(minutes=12),
    )
    assert recovered.confidence.state == "GREEN"
    assert recovered.degraded.can_create is True

    # Marketplace disappearance cannot account or replace a fill. Exact
    # Coinset/Spacescan agreement can while Sage is delayed, after which the
    # replacement still waits for its deterministic backoff.
    provider_hint = assess_fill_confidence(
        {"offer_missing": True, "dexie_status": "spent", "sage_status": "pending"}
    )
    assert provider_hint.confidence is FillConfidence.OBSERVED
    assert provider_hint.can_account is False
    assert provider_hint.can_replace is False

    assert mock_wallet.simulate_fills(fill_probability=1.0) == [trade_id]
    expected_inputs = [
        {
            "coin_id": _sha("filled-input"),
            "asset_id": ASSET_ID,
            "amount_mojos": 1_000_000_000_000,
        }
    ]
    exact_chain_evidence = {
        "transaction_id": TX_ID,
        "spend_identity": _sha("filled-spend"),
        "block_height": 1_234_567,
        "inputs": expected_inputs,
    }
    confirmed = assess_fill_confidence(
        {
            "offer_missing": True,
            "sage_status": "delayed",
            "expected_inputs": expected_inputs,
            "coinset_evidence": dict(exact_chain_evidence),
            "spacescan_evidence": dict(exact_chain_evidence),
        }
    )
    assert confirmed.confidence is FillConfidence.CONFIRMED
    assert confirmed.can_account is True
    assert confirmed.can_replace is True

    terminal_at = NOW + timedelta(minutes=13)
    assert (
        tracker.replacement_decision(
            authoritative_terminal=False,
            terminal_at=None,
            attempt=2,
            now=terminal_at,
        ).action
        == "BLOCK_REPLACEMENT"
    )
    assert (
        tracker.replacement_decision(
            authoritative_terminal=True,
            terminal_at=terminal_at,
            attempt=2,
            now=terminal_at + timedelta(seconds=19),
        ).action
        == "WAIT_REPLACEMENT_BACKOFF"
    )
    assert (
        tracker.replacement_decision(
            authoritative_terminal=True,
            terminal_at=terminal_at,
            attempt=2,
            now=terminal_at + timedelta(seconds=20),
        ).action
        == "ALLOW_REPLACEMENT"
    )

    replacement = mock_wallet.create_offer(
        {"1": -1_000_000_000_000, "2": 10_000_000},
        validate_only=False,
        max_time=int(NOW.timestamp()) + 7200,
    )
    assert replacement["success"] is True
    active = mock_wallet.get_all_offers(include_completed=False)
    assert [row["trade_id"] for row in active] == [replacement["trade_id"]]

    # Stop plus native-style bulk cancellation terminalizes the remaining live
    # book. The durable publication/discovery evidence then survives restart.
    cancelled = mock_wallet.cancel_offers_batch(
        [row["trade_id"] for row in active], secure=True
    )
    assert all(row["success"] for row in cancelled)
    assert mock_wallet.get_all_offers(include_completed=False) == []

    isolated_db.close_connection()
    isolated_db.init_database()
    restored_intent = isolated_db.get_offer_intent(intent["intent_id"])
    restored_discovery = isolated_db.get_offer_publication_discoveries(
        intent["intent_id"]
    )
    assert restored_intent["lifecycle_state"] == "visible"
    assert any(
        row["provider"] == "dexie" and row["state"] == "exact"
        for row in restored_discovery
    )

    html = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("bot_gui.html")
        .read_text(encoding="utf-8")
    )
    assert "Previous live book is ready to resume" in html
    assert "Resume Bot Now" in html
    assert "Start Fresh for Changes" in html


def test_source_conflict_stays_amber_and_never_authorizes_new_exposure(isolated_db):
    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda _asset_id: _independent_book(),
        fetch_splash_offers=lambda _asset_id: [
            {
                "offer_id": _sha("conflict-buy"),
                "side": "buy",
                "price": "0.00015",
                "amount_mojos": 3_000_000_000_000,
            },
            {
                "offer_id": _sha("conflict-sell"),
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

    conflict = runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=NOW,
    )

    assert conflict.confidence.state in {"AMBER", "RED"}
    assert "provider_price_conflict" in conflict.confidence.reason_codes
    assert conflict.degraded.can_create is False
    assert conflict.degraded.can_requote is False
