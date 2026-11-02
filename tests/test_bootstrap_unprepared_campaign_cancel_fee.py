"""Cancellation consent for a campaign that reused already prepared coins."""

from importlib import import_module

import pytest
from chia_rs import Coin
from flask import Flask

from bootstrap_fee_fixture import approved_bootstrap  # noqa: F401
import fee_approval_test_utils as utils
from fee_projection_test_utils import standard_puzzles


def test_reused_campaign_coins_quote_zero_prep_with_cancellation_cover(
    approved_bootstrap,
):
    """Real executable coin roots allow consent without a prep transaction."""
    runtime = import_module("coin_prep_fee_runtime")
    service = import_module("coin_prep_fee_approval")
    state = approved_bootstrap
    options = {
        "bootstrap_campaign_id": state["campaign_id"],
        "bootstrap_campaign_revision": 0,
    }
    targets = runtime.read_fee_economic_snapshot(options)["recipe"]["targets"]
    native_puzzle, cat_puzzle = standard_puzzles()
    state["xch"], state["cat"] = [], []
    for index, target in enumerate(targets, start=1):
        puzzle = native_puzzle if target.asset == "xch" else cat_puzzle
        parent = Coin(
            index.to_bytes(32, "big"), puzzle.get_tree_hash(), target.amount_mojos
        )
        coin = (
            parent
            if target.asset == "xch"
            else Coin(parent.name(), puzzle.get_tree_hash(), target.amount_mojos)
        )
        state["unsigned_roots"][coin.name().hex()] = (
            coin,
            puzzle,
            None if target.asset == "xch" else utils.ASSET,
        )
        if target.asset == "cat":
            state["unsigned_parents"][coin.name().hex()] = parent
        row = utils._coin(index + 100, target.amount_mojos)
        row["coin_id"] = coin.name().hex()
        state[target.asset].append(row)
    fee_coin = Coin(b"f" * 32, native_puzzle.get_tree_hash(), 2_000_000_000)
    state["unsigned_roots"][fee_coin.name().hex()] = (fee_coin, native_puzzle, None)
    fee_row = utils._coin(999, int(fee_coin.amount))
    fee_row["coin_id"] = fee_coin.name().hex()
    state["xch"].append(fee_row)
    coin_ids = [row["coin_id"] for asset in ("xch", "cat") for row in state[asset]]
    assert len(coin_ids) == len(set(coin_ids))
    assert len(runtime._selectable_inventory(None, "mainnet")) == len(state["xch"])
    assert len(runtime._selectable_inventory(utils.ASSET, "mainnet")) == len(
        state["cat"]
    )

    preview = service.preview_coin_prep_fees(options)
    assert preview["available"] is True, preview
    assert preview["preparation_transaction_count_min"] == 0
    assert preview["preparation_transaction_count_max"] == 0
    assert preview["minimum_cancellation_reserve_mojos"] > 0
    approved = service.approve_coin_prep_fees(
        preview_id=preview["preview_id"],
        maximum_fee_mojos=preview["suggested_maximum_fee_mojos"],
        cancellation_reserve_mojos=preview["minimum_cancellation_reserve_mojos"],
    )
    from blueprints.bot import _bootstrap_cancellation_fee_start_readiness

    assert _bootstrap_cancellation_fee_start_readiness(
        runtime.read_fee_economic_snapshot(options)["campaign"]
    ) == {"ready": True, "approval_id": approved["approval_id"]}
    # Once offers consume their principal coins, a restart may have only the
    # designated fee coin selectable. The prior consent still protects resume.
    state["xch"], state["cat"] = [fee_row], []
    assert _bootstrap_cancellation_fee_start_readiness(state["campaign"]) == {
        "ready": True,
        "approval_id": approved["approval_id"],
    }


def test_stopped_campaign_without_offers_cannot_quote_recovery_fee(
    approved_bootstrap, monkeypatch
):
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    campaign_id = approved_bootstrap["campaign_id"]
    monkeypatch.setattr(
        database, "get_latest_coin_prep_fee_approval_for_campaign", lambda _id: None
    )
    assert database.stop_bootstrap_campaign(
        campaign_id, "manual", "2026-09-22T12:01:00Z"
    )
    with pytest.raises(ValueError, match="FEE_PREP_CAMPAIGN_UNAVAILABLE"):
        runtime.read_fee_economic_snapshot(
            {
                "bootstrap_campaign_id": campaign_id,
                "bootstrap_campaign_revision": 1,
                "cancellation_recovery_action": "bootstrap_stop",
            }
        )


def test_active_campaign_with_offers_can_quote_cancellation_without_prior_prep_approval(
    approved_bootstrap, monkeypatch
):
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    service = import_module("coin_prep_fee_approval")
    coin_prep = import_module("blueprints.coin_prep")
    campaign_id = approved_bootstrap["campaign_id"]
    options = {
        "bootstrap_campaign_id": campaign_id,
        "bootstrap_campaign_revision": 0,
        "cancellation_recovery_action": "cancel_all",
    }
    intent_id, trade_id = "8" * 64, "9" * 64
    operation_id = f"create:{intent_id}"
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:prepared",
        run_id="reused-prepared-coins",
        wallet_fingerprint_hash=import_module("mutation_gate").wallet_fingerprint_hash(
            736588221
        ),
        network="mainnet",
        asset_id=utils.ASSET,
        side="buy",
        tier="inner",
        purpose=f"bootstrap:{campaign_id}:revision:0",
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=["a" * 64],
        wallet_identity_json={"binding_digest": "b" * 64},
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
        offer_text_sha256="c" * 64,
        wallet_identity_json={"binding_digest": "b" * 64},
        evidence_json={"effect_attempted": True},
        finalized_at="2026-09-22T12:00:01Z",
    )
    assert import_module("blueprints.bootstrap")._campaign_trade_ids(campaign_id) == [
        trade_id
    ]
    original_context = coin_prep._active_bootstrap_coin_prep_context

    def active_context(request_options):
        assert "cancellation_recovery_action" not in request_options
        return original_context(request_options)

    monkeypatch.setattr(
        coin_prep, "_active_bootstrap_coin_prep_context", active_context
    )
    monkeypatch.setattr(
        database, "get_latest_coin_prep_fee_approval_for_campaign", lambda _id: None
    )
    snapshot = runtime.read_fee_economic_snapshot(options)
    assert snapshot["recovery_only"] is True
    assert snapshot["recovery_execution_context"] is not None
    preview = service.preview_coin_prep_fees(options)
    assert preview["available"] is True
    assert preview["preparation_transaction_count_min"] == 0
    approval = service.approve_coin_prep_fees(
        preview_id=preview["preview_id"],
        maximum_fee_mojos=int(preview["suggested_maximum_fee_mojos"]),
        cancellation_reserve_mojos=int(preview["minimum_cancellation_reserve_mojos"]),
    )
    recovered = runtime.read_approved_prep_fee_snapshot(
        approval["approval_id"], expected_recovery_action="cancel_all"
    )
    assert recovered["campaign"]["campaign_id"] == campaign_id
    assert recovered["recovery_only"] is True
    with pytest.raises(ValueError, match="FEE_APPROVAL_RECOVERY_ONLY"):
        runtime.read_approved_prep_fee_snapshot(approval["approval_id"])
    bootstrap = import_module("blueprints.bootstrap")
    campaign = database.get_bootstrap_campaign(campaign_id)
    monkeypatch.setattr(
        bootstrap,
        "_read_bootstrap_identity",
        lambda: {
            key: campaign[key]
            for key in (
                "network",
                "wallet_type",
                "wallet_fingerprint",
                "wallet_id",
                "asset_id",
            )
        },
    )

    def needs_cancellation_approval(_trade_ids):
        raise ValueError("FEE_BUDGET_APPROVAL_REQUIRED")

    monkeypatch.setattr(
        bootstrap, "_cancel_campaign_offers", needs_cancellation_approval
    )
    app = Flask(__name__)
    app.register_blueprint(bootstrap.bp)
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/api/bootstrap/stop", json={"campaign_id": campaign_id, "revision": 0}
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "FEE_BUDGET_APPROVAL_REQUIRED"
    assert response.get_json()["financial_action_started"] is False
    assert response.get_json()["cancel_targets"] == 1
    assert database.get_bootstrap_campaign(campaign_id)["status"] == "stopped"
    stopped_options = {
        **options,
        "bootstrap_campaign_revision": 1,
        "cancellation_recovery_action": "bootstrap_stop",
    }
    stopped_snapshot = runtime.read_fee_economic_snapshot(stopped_options)
    assert stopped_snapshot["recovery_only"] is True
    assert stopped_snapshot["recipe"]["economic_plan"]["outputs"] == []
    assert stopped_snapshot["recipe"]["economic_plan"]["campaign_revision"] == 1
    stopped_preview = service.preview_coin_prep_fees(stopped_options)
    assert stopped_preview["available"] is True
    assert stopped_preview["preparation_transaction_count_min"] == 0
    assert stopped_preview["preparation_transaction_count_max"] == 0
    assert stopped_preview["estimated_cancellation_fee_mojos"] > 0
    assert stopped_preview["minimum_cancellation_reserve_mojos"] > 0
    assert stopped_preview["suggested_maximum_fee_mojos"] > 0
    assert any(
        stage["stage_id"] == "cancel_xch" and stage["transaction_count_max"] == 1
        for stage in stopped_preview["stages"]
    )
    stop_approval = service.approve_coin_prep_fees(
        preview_id=stopped_preview["preview_id"],
        maximum_fee_mojos=int(stopped_preview["suggested_maximum_fee_mojos"]),
        cancellation_reserve_mojos=int(
            stopped_preview["minimum_cancellation_reserve_mojos"]
        ),
    )
    recovered_stop = runtime.read_approved_prep_fee_snapshot(
        stop_approval["approval_id"], expected_recovery_action="bootstrap_stop"
    )
    assert recovered_stop["campaign"]["campaign_id"] == campaign_id
    assert recovered_stop["recovery_only"] is True
    with pytest.raises(ValueError, match="FEE_APPROVAL_RECOVERY_ONLY"):
        runtime.read_approved_prep_fee_snapshot(stop_approval["approval_id"])
    cancellation = import_module("coin_prep_fee_cancellation")
    wallet = import_module("wallet")
    monkeypatch.setattr(
        wallet,
        "build_cancel_offers_batch_unsigned",
        lambda trade_ids, **_kwargs: {
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": 1234,
        },
    )
    monkeypatch.setattr(
        cancellation,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 1000,
            "expires_at": 1060,
        },
    )
    priced = cancellation.price_approved_cancellation(
        approval_id=stop_approval["approval_id"],
        trade_ids=[trade_id],
        source_coin_ids=["a" * 64],
        fee_coin_id="b" * 64,
        expected_recovery_action="bootstrap_stop",
    )
    assert priced["available"] is True, priced
    assert priced["fee_mojos"] == 20
    assert priced["approval"]["remaining_fee_mojos"] >= 20

    def cancel_with_fresh_approval(trade_ids, *, fee_approval_id=None):
        assert trade_ids == [trade_id]
        assert fee_approval_id == stop_approval["approval_id"]
        return {trade_id: {"outcome": "CANCEL_CONFIRMED"}}

    monkeypatch.setattr(
        bootstrap, "_cancel_campaign_offers", cancel_with_fresh_approval
    )
    retry = app.test_client().post(
        "/api/bootstrap/stop",
        json={
            "campaign_id": campaign_id,
            "revision": 1,
            "fee_approval_id": stop_approval["approval_id"],
        },
    )
    assert retry.status_code == 200, retry.get_json()
    assert retry.get_json()["cancel_results"] == {
        trade_id: {"outcome": "CANCEL_CONFIRMED"}
    }
