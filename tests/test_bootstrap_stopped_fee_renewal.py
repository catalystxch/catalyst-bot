"""Stopping must not strand fee renewal for outstanding cancellation work."""

from importlib import import_module
from datetime import datetime, timezone

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
        wallet_fingerprint_hash=import_module("mutation_gate").wallet_fingerprint_hash(736588221),
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
    assert import_module("blueprints.bootstrap")._campaign_trade_ids(state["campaign_id"]) == [trade_id]

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
        lambda _conn, campaign_id, **_context: spent if campaign_id == state["campaign_id"] else 0,
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

    assert utils._counts() == before, "preview must not create consent or dispatch authority"
    assert response.status_code == 200, payload
    assert payload["available"] is True, payload
    assert payload["fee_accounting"]["spent_fee_mojos"] == str(spent)
    assert int(payload["suggested_maximum_fee_mojos"]) >= spent + 1000
    assert payload["dispatch_authorized"] is False
    campaign = database.get_bootstrap_campaign(state["campaign_id"])
    assert campaign["status"] == "stopped"
    assert campaign["fee_budget_xch"] == "0.01"


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
                "network", "wallet_type", "wallet_fingerprint", "wallet_id", "asset_id"
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
    assert database.update_bootstrap_campaign_state(
        state["campaign_id"], expected_revision=0, record=materialized
    ) == 1
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

    assert utils._counts() == before, "preview must not create consent or wallet authority"
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
