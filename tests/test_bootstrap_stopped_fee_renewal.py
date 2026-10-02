"""Stopping must not strand fee renewal for outstanding cancellation work."""

from importlib import import_module
from datetime import datetime, timezone
from decimal import Decimal
import json

from chia_rs import Coin
from flask import Flask
import pytest

import fee_approval_test_utils as utils
from bootstrap_fee_fixture import (
    approved_bootstrap,  # noqa: F401 - isolated SQLite and unsigned wallet fixture
)


@pytest.mark.parametrize("spent", [0, 10_000_000_000])
def test_stopped_campaign_can_review_cancel_budget_without_prior_overrun(
    request, monkeypatch, spent
):
    # This file can be imported for its shared fixture before pytest collects
    # it. Establish the app entry point after per-file module isolation.
    import_module("api_server")
    coin_prep = import_module("blueprints.coin_prep")
    real_context = coin_prep._active_bootstrap_coin_prep_context
    state = request.getfixturevalue("approved_bootstrap")
    monkeypatch.setattr(coin_prep, "_active_bootstrap_coin_prep_context", real_context)
    database = import_module("database")
    service = import_module("coin_prep_fee_approval")
    pricing = import_module("coin_prep_fee_pricing")
    runtime = import_module("coin_prep_fee_runtime")
    assert state["approval"]["total_fee_mojos"] < 1000

    # Persist a real campaign-owned cancellation obligation; this is not an
    # empty stopped campaign asking for a new preparation session.
    intent_id, trade_id = "a" * 64, "b" * 64
    operation_id = f"create:{intent_id}"
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:prepared",
        run_id="stopped-renewal",
        wallet_fingerprint_hash=import_module("mutation_gate").wallet_fingerprint_hash(
            736588221
        ),
        network="mainnet",
        asset_id=utils.ASSET,
        side="buy",
        tier="inner",
        purpose=f"bootstrap:{state['campaign_id']}:revision:0",
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=["c" * 64],
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"canonical_intent_sha256": intent_id},
        prepared_at="2026-09-22T12:00:00Z",
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256="e" * 64,
        wallet_identity_json={"binding_digest": "d" * 64},
        evidence_json={"effect_attempted": True},
        finalized_at="2026-09-22T12:00:01Z",
    )
    assert import_module("blueprints.bootstrap")._campaign_trade_ids(
        state["campaign_id"]
    ) == [trade_id]

    # A higher network quote needs renewed consent even when the original
    # campaign cap has never been exceeded. No wallet effect is performed.
    def higher_quote(cost, target_seconds):
        return {
            "available": True,
            "fee_mojos": 1000,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 1000,
            "expires_at": 1060,
        }

    monkeypatch.setattr(service, "quote_fee", higher_quote)
    monkeypatch.setattr(pricing, "quote_fee", higher_quote)
    monkeypatch.setattr(
        database,
        "_bootstrap_campaign_authoritative_fee_spent_mojos",
        lambda _conn, campaign_id, **_context: (
            spent if campaign_id == state["campaign_id"] else 0
        ),
    )
    assert database.stop_bootstrap_campaign(
        state["campaign_id"], "manual", "2026-09-22T12:01:00.000000Z"
    )
    # The immutable prior approval retains revision 0; stop increments the
    # campaign to revision 1 without changing its economics or fee ceiling.
    options = {
        "bootstrap_campaign_id": state["campaign_id"],
        "bootstrap_campaign_revision": 0,
    }
    assert real_context(options) is None
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        runtime.read_approved_prep_fee_snapshot(state["approval"]["approval_id"])
    before = utils._counts()
    app = Flask(__name__)
    app.register_blueprint(coin_prep.bp)

    response = app.test_client().post("/api/coin-prep/fee-preview", json=options)
    payload = response.get_json()

    assert utils._counts() == before, (
        "preview must not create consent or dispatch authority"
    )
    assert response.status_code == 200, payload
    assert payload["available"] is True, payload
    assert payload["fee_accounting"]["spent_fee_mojos"] == str(spent)
    assert int(payload["suggested_maximum_fee_mojos"]) >= spent + 1000
    assert payload["dispatch_authorized"] is False
    campaign = database.get_bootstrap_campaign(state["campaign_id"])
    assert campaign["status"] == "stopped"
    assert campaign["fee_budget_xch"] == "0.01"


@pytest.mark.parametrize(
    "restored_session_mode",
    [False, True],
    ids=["original-settings", "restored-buy-only-settings"],
)
def test_stopped_campaign_cancel_review_ignores_locked_principal_and_mode_drift(
    request, monkeypatch, restored_session_mode
):
    """Live offer roots are unavailable to prep but must not block cancel cover."""

    import_module("api_server")
    coin_prep = import_module("blueprints.coin_prep")
    real_context = coin_prep._active_bootstrap_coin_prep_context
    state = request.getfixturevalue("approved_bootstrap")
    monkeypatch.setattr(coin_prep, "_active_bootstrap_coin_prep_context", real_context)
    database = import_module("database")

    intent_id, trade_id = "1" * 64, "2" * 64
    operation_id = f"create:{intent_id}"
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:prepared",
        run_id="locked-principal-renewal",
        wallet_fingerprint_hash=import_module("mutation_gate").wallet_fingerprint_hash(
            736588221
        ),
        network="mainnet",
        asset_id=utils.ASSET,
        side="buy",
        tier="inner",
        purpose=f"bootstrap:{state['campaign_id']}:revision:0",
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=["3" * 64],
        wallet_identity_json={"binding_digest": "4" * 64},
        evidence_json={"canonical_intent_sha256": intent_id},
        prepared_at="2026-09-22T12:00:00Z",
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256="5" * 64,
        wallet_identity_json={"binding_digest": "4" * 64},
        evidence_json={"effect_attempted": True},
        finalized_at="2026-09-22T12:00:01Z",
    )
    assert database.stop_bootstrap_campaign(
        state["campaign_id"], "manual", "2026-09-22T12:01:00.000000Z"
    )
    if restored_session_mode:
        runtime = import_module("coin_prep_fee_runtime")
        cfg = runtime.cfg
        monkeypatch.setattr(cfg, "LIQUIDITY_MODE", "buy_only")
        monkeypatch.setattr(cfg, "MAX_ACTIVE_SELL_OFFERS", 0)
        for tier in ("INNER", "MID", "OUTER", "EXTREME"):
            monkeypatch.setattr(cfg, f"SELL_{tier}_SIZE_XCH", Decimal("0"))
            monkeypatch.setattr(cfg, f"SELL_{tier}_TIER_COUNT", 0)
            monkeypatch.setattr(cfg, f"SELL_{tier}_TIER_SPARE_COUNT", 0)
            monkeypatch.setattr(cfg, f"{tier}_SIZE_XCH", Decimal("0"))
            monkeypatch.setattr(
                cfg,
                f"BUY_{tier}_TIER_SPARE_COUNT",
                getattr(cfg, f"BUY_{tier}_TIER_SPARE_COUNT") + 1,
            )
        execution = import_module("coin_prep_fee_execution")
        approval_id = database.get_latest_coin_prep_fee_approval_for_campaign(
            state["campaign_id"]
        )
        consent = database.get_coin_prep_fee_approval_context(approval_id)
        binding = json.loads(consent["quote_json"])["execution_context"]
        current_config = runtime._configuration()
        assert current_config["LIQUIDITY_MODE"] == "buy_only"
        assert binding["configuration"] != execution.encode_execution_configuration(
            current_config
        )

    # Model the real post-publication wallet: the 0.1 XCH replacement root is
    # locked in the live offer, while a small selectable XCH fee root remains.
    original_coin, native_puzzle, _asset = next(
        value for value in state["unsigned_roots"].values() if value[2] is None
    )
    fee_coin = Coin(b"f" * 32, native_puzzle.get_tree_hash(), 10_000_000)
    state["unsigned_roots"][fee_coin.name().hex()] = (fee_coin, native_puzzle, None)
    fee_row = utils._coin(77, str(fee_coin.amount))
    fee_row["coin_id"] = fee_coin.name().hex()
    state["xch"] = [fee_row]
    assert original_coin.amount > fee_coin.amount

    app = Flask(__name__)
    app.register_blueprint(coin_prep.bp)
    options = {
        "bootstrap_campaign_id": state["campaign_id"],
        "bootstrap_campaign_revision": 1,
    }
    preview = import_module("coin_prep_fee_approval").preview_coin_prep_fees(options)
    assert preview["available"] is True
    response = app.test_client().post(
        "/api/coin-prep/fee-preview",
        json=options,
    )
    payload = response.get_json()

    assert response.status_code == 200, payload
    assert payload["available"] is True, payload
    assert payload["preparation_transaction_count_min"] == 0
    assert payload["preparation_transaction_count_max"] == 0
    assert int(payload["estimated_preparation_fee_mojos"]) == 0
    assert int(payload["estimated_cancellation_fee_mojos"]) > 0
    assert all(stage["cancellation"] is True for stage in payload["stages"])
    assert payload["dispatch_authorized"] is False
    approval = import_module("coin_prep_fee_approval").approve_coin_prep_fees(
        preview_id=payload["preview_id"],
        maximum_fee_mojos=int(payload["suggested_maximum_fee_mojos"]),
        cancellation_reserve_mojos=int(payload["minimum_cancellation_reserve_mojos"]),
    )
    recovered = import_module("coin_prep_fee_runtime").read_approved_prep_fee_snapshot(
        approval["approval_id"], allow_campaign_fee_recovery=True
    )
    assert recovered["recipe"]["economic_plan"]["campaign_revision"] == 0
    assert approval["dispatch_authorized"] is False


def test_active_campaign_revision_advance_preserves_cancellation_only_renewal(
    request, monkeypatch
):
    """A policy heartbeat must not strand cancellation of its live offers."""

    import_module("api_server")
    coin_prep = import_module("blueprints.coin_prep")
    real_context = coin_prep._active_bootstrap_coin_prep_context
    state = request.getfixturevalue("approved_bootstrap")
    monkeypatch.setattr(coin_prep, "_active_bootstrap_coin_prep_context", real_context)
    database = import_module("database")

    intent_id, trade_id = "6" * 64, "7" * 64
    operation_id = f"create:{intent_id}"
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:prepared",
        run_id="active-revision-renewal",
        wallet_fingerprint_hash=import_module("mutation_gate").wallet_fingerprint_hash(
            736588221
        ),
        network="mainnet",
        asset_id=utils.ASSET,
        side="sell",
        tier="inner",
        purpose=f"bootstrap:{state['campaign_id']}:revision:0",
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=["8" * 64],
        wallet_identity_json={"binding_digest": "9" * 64},
        evidence_json={"canonical_intent_sha256": intent_id},
        prepared_at="2026-09-22T12:00:00Z",
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256="a" * 64,
        wallet_identity_json={"binding_digest": "9" * 64},
        evidence_json={"effect_attempted": True},
        finalized_at="2026-09-22T12:00:01Z",
    )
    campaign = database.get_bootstrap_campaign(state["campaign_id"])
    next_state = {
        key: campaign[key]
        for key in (
            "stage",
            "deployment_fraction",
            "current_anchor_price",
            "stable_since",
            "confirmed_fills",
            "settlement_clusters",
            "independent_depth_sides",
            "suspected_linked_activity",
            "adverse_fill_times",
            "fee_spent_xch",
            "realized_loss_xch",
            "marked_inventory_loss_xch",
            "updated_at",
        )
    }
    assert (
        database.update_bootstrap_campaign_state(
            state["campaign_id"], expected_revision=0, record=next_state
        )
        == 1
    )
    assert database.get_bootstrap_campaign(state["campaign_id"])["status"] == "active"

    app = Flask(__name__)
    app.register_blueprint(coin_prep.bp)
    response = app.test_client().post(
        "/api/coin-prep/fee-preview",
        json={
            "bootstrap_campaign_id": state["campaign_id"],
            "bootstrap_campaign_revision": 1,
        },
    )
    payload = response.get_json()

    assert response.status_code == 200, payload
    assert payload["available"] is True, payload
    assert payload["preparation_transaction_count_min"] == 0
    assert payload["preparation_transaction_count_max"] == 0
    assert int(payload["estimated_cancellation_fee_mojos"]) > 0
    assert payload["dispatch_authorized"] is False
    approval = import_module("coin_prep_fee_approval").approve_coin_prep_fees(
        preview_id=payload["preview_id"],
        maximum_fee_mojos=int(payload["suggested_maximum_fee_mojos"]),
        cancellation_reserve_mojos=int(payload["minimum_cancellation_reserve_mojos"]),
    )
    recovered = import_module("coin_prep_fee_runtime").read_approved_prep_fee_snapshot(
        approval["approval_id"], allow_campaign_fee_recovery=True
    )
    assert recovered["recipe"]["economic_plan"]["campaign_revision"] == 0
    assert recovered["campaign"]["revision"] == 1
    assert approval["dispatch_authorized"] is False


@pytest.fixture
def automatically_stopped_campaign(request, monkeypatch):
    import_module("api_server")
    coin_prep = import_module("blueprints.coin_prep")
    real_context = coin_prep._active_bootstrap_coin_prep_context
    state = request.getfixturevalue("approved_bootstrap")
    monkeypatch.setattr(coin_prep, "_active_bootstrap_coin_prep_context", real_context)
    database = import_module("database")
    bootstrap = import_module("blueprints.bootstrap")
    policy = import_module("bootstrap_runtime")
    wallet = import_module("wallet")
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)

    class FixedClock:
        @staticmethod
        def now(_tz):
            return now

    monkeypatch.setattr(coin_prep, "datetime", FixedClock)
    monkeypatch.setattr(
        bootstrap,
        "_read_bootstrap_identity",
        lambda: {
            key: state["campaign"][key]
            for key in (
                "network",
                "wallet_type",
                "wallet_fingerprint",
                "wallet_id",
                "asset_id",
            )
        },
    )

    def balance(wallet_id):
        assert wallet_id in (1, 2)
        return {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": (
                    200_000_000_000 if wallet_id == 1 else 20_000
                )
            },
        }

    monkeypatch.setattr(wallet, "get_wallet_balance", balance)
    options = {
        "bootstrap_campaign_id": state["campaign_id"],
        "bootstrap_campaign_revision": 0,
    }
    assert real_context(options)["campaign"]["revision"] == 0
    monkeypatch.setattr(
        database,
        "_bootstrap_campaign_authoritative_fee_spent_mojos",
        lambda _conn, campaign_id, **_context: (
            10_000_000_010 if campaign_id == state["campaign_id"] else 0
        ),
    )
    campaign = database.get_bootstrap_campaign(state["campaign_id"])
    evidence = policy.evidence_from_record(campaign)
    decision = policy.evaluate_bootstrap_campaign(
        policy.campaign_from_record(campaign), evidence, now=now
    )
    assert decision.authorized is False
    materialized = policy.plan_bootstrap_state_update(
        campaign_record=campaign, evidence=evidence, decision=decision, now=now
    )
    assert materialized["stage"] == "stopped"
    assert (
        database.update_bootstrap_campaign_state(
            state["campaign_id"], expected_revision=0, record=materialized
        )
        == 1
    )
    database.close_connection()
    restored = database.get_bootstrap_campaign(state["campaign_id"])
    assert restored["status"] == "active"
    assert restored["stage"] == "stopped"
    assert restored["revision"] == 1
    assert restored["fee_budget_xch"] == "0.01"
    return {**state, "recovery_options": options}


def test_automatic_policy_stop_preserves_read_only_recovery_preview(
    automatically_stopped_campaign,
):
    state = automatically_stopped_campaign
    coin_prep = import_module("blueprints.coin_prep")
    app = Flask(__name__)
    app.register_blueprint(coin_prep.bp)
    before = utils._counts()

    current_revision_options = {
        **state["recovery_options"],
        "bootstrap_campaign_revision": 1,
    }
    response = app.test_client().post(
        "/api/coin-prep/fee-preview", json=current_revision_options
    )
    payload = response.get_json()

    assert utils._counts() == before, (
        "preview must not create consent or wallet authority"
    )
    assert response.status_code == 200, payload
    assert payload["available"] is True, payload
    assert payload["fee_accounting"]["spent_fee_mojos"] == "10000000010"
    assert payload["dispatch_authorized"] is False


def test_automatic_policy_stop_preserves_only_cancellation_recovery_context(
    automatically_stopped_campaign,
):
    state = automatically_stopped_campaign
    runtime = import_module("coin_prep_fee_runtime")
    before = utils._counts()
    with pytest.raises(ValueError):
        runtime.read_approved_prep_fee_snapshot(state["approval"]["approval_id"])

    recovered = runtime.read_approved_prep_fee_snapshot(
        state["approval"]["approval_id"], allow_campaign_fee_recovery=True
    )

    assert utils._counts() == before, "readback must not create new consent or holds"
    assert recovered["campaign"]["stage"] == "stopped"
    assert recovered["campaign"]["fee_budget_xch"] == "0.01"
    assert recovered["recipe"]["economic_plan"]["campaign_revision"] == 0
    assert recovered["dispatch_authorized"] is False
