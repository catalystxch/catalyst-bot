"""Cancellation consent for a campaign that reused already prepared coins."""

from importlib import import_module

import pytest

from bootstrap_fee_fixture import approved_bootstrap  # noqa: F401
import fee_approval_test_utils as utils


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
    assert database.stop_bootstrap_campaign(
        campaign_id, "manual", "2026-09-22T12:01:00Z"
    )
    with pytest.raises(ValueError, match="FEE_PREP_CAMPAIGN_UNAVAILABLE"):
        runtime.read_fee_economic_snapshot(
            {
                **options,
                "bootstrap_campaign_revision": 1,
            }
        )
