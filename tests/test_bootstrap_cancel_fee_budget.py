"""Campaign cancellation must not escape the accepted aggregate fee ceiling."""

from types import SimpleNamespace

import database
import offer_manager
from cancel_outcomes import CANCEL_SUBMITTED_UNCONFIRMED, cancellation_result
from offer_manager import OfferManager
from test_offer_cancel_journal import (
    ASSET_ID,
    _fail_closed_network_guard,  # noqa: F401 - enforce no real wallet/network effects
    _seed_task7_created_offer,
    _stub_cancel_continuation_authority,
    isolated_database,  # noqa: F401 - real disposable SQLite journal
)


def test_generic_cancel_cannot_spend_above_owning_campaign_fee_cap(
    isolated_database, monkeypatch
):
    """A 678M-mojo batch must not dispatch under a 500M-mojo campaign cap."""
    campaign_id = database.create_bootstrap_campaign(
        {
            "network": "mainnet",
            "wallet_type": "sage",
            "wallet_fingerprint": 123456789,
            "wallet_id": 2,
            "asset_id": ASSET_ID,
            "anchor_price": "0.001",
            "minimum_price": "0.0005",
            "maximum_price": "0.002",
            "xch_budget": "1",
            "cat_budget": "1000",
            "fee_budget_xch": "0.0005",
            "subsidy_budget_xch": "0",
            "created_at": "2026-08-16T11:00:00Z",
            "expires_at": "2026-08-17T11:00:00Z",
        }
    )
    # Keep the real persisted creation/cancel journals. Only change the test
    # seeder's normal-lifecycle purpose to the actual owning campaign.
    prepare_intent = database.prepare_offer_intent

    def campaign_prepare(**kwargs):
        kwargs["purpose"] = f"bootstrap:{campaign_id}:revision:0"
        return prepare_intent(**kwargs)

    with monkeypatch.context() as seed_patch:
        seed_patch.setattr(database, "prepare_offer_intent", campaign_prepare)
        for index, (trade_id, coin_id) in enumerate(
            (("a" * 64, "c" * 64), ("b" * 64, "d" * 64))
        ):
            _seed_task7_created_offer(
                trade_id=trade_id,
                coin_id=coin_id,
                intent_seed=f"campaign-cap-{index}",
                wallet_fingerprint_hash=offer_manager.mutation_gate.wallet_fingerprint_hash(
                    123456789
                ),
            )

    effects = []

    def batch_effect(
        trade_ids,
        secure,
        max_workers,
        fee_mojos,
        skip_confirmation,
        *,
        source_coin_ids,
        fee_coin_id,
        _identity_recheck=None,
    ):
        _identity_recheck("cancel_offers")
        effects.append(fee_mojos)
        submitted = cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method="sage_native_cancel_offers",
            raw_response={"success": True, "transaction_id": "1" * 64},
            transaction_id="1" * 64,
            spend_identity="2" * 64,
        )
        return {trade_id: dict(submitted) for trade_id in trade_ids}

    def single_effect(*_args, **_kwargs):
        effects.append("unexpected_single_cancel")
        raise AssertionError("campaign cap must not be bypassed by serial fallback")

    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=single_effect,
        batch_effect=batch_effect,
        identity_count=8,
    )
    monkeypatch.setattr(
        offer_manager, "get_effective_transaction_fee_mojos", lambda: 13_079_100
    )
    manager = OfferManager()
    manager._fee_pool = SimpleNamespace(
        reserve=lambda minimum_amount_mojos=0: "e" * 64
    )

    try:
        manager.cancel_offers(
            ["a" * 64, "b" * 64], force_storm=True, reason="manual_cancel_all"
        )
    except ValueError as exc:
        # A structured refusal or an explicit boundary exception is acceptable;
        # dispatching a fee beyond the recorded authority is not.
        assert "FEE" in str(exc) and "BUDGET" in str(exc), str(exc)

    assert effects == [], "generic Cancel All dispatched above the campaign fee cap"
