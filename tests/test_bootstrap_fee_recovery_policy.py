"""Recovery quotes must be reachable through the real campaign policy boundary."""

from datetime import datetime, timezone
from importlib import import_module
import time
from types import SimpleNamespace

from flask import Flask
import pytest

import api_server  # noqa: F401 - establishes blueprint import order
import fee_approval_test_utils as utils
from fee_staged_preview_utils import prepare_unsigned_wallet


@pytest.fixture
def approved_bootstrap(tmp_path, monkeypatch):
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    service = import_module("coin_prep_fee_approval")
    pricing = import_module("coin_prep_fee_pricing")
    coin_prep = import_module("blueprints.coin_prep")

    wallet_reads = utils.live_reads(tmp_path, monkeypatch)
    state = next(wallet_reads)
    utils.economic_reads(state, monkeypatch)
    monkeypatch.setattr(runtime, "cfg", state["config"])
    state["now"] = 1000
    monkeypatch.setattr(service, "_now", lambda: state["now"])
    monkeypatch.setattr(pricing, "_now", lambda: state["now"])
    monkeypatch.setattr(
        database,
        "time",
        SimpleNamespace(
            time=lambda: state["now"],
            time_ns=time.time_ns,
            monotonic=time.monotonic,
            sleep=time.sleep,
        ),
    )
    campaign_id = database.create_bootstrap_campaign(
        {
            "network": "mainnet",
            "wallet_type": "sage",
            "wallet_fingerprint": 736588221,
            "wallet_id": 2,
            "asset_id": utils.ASSET,
            "anchor_price": "0.01",
            "minimum_price": "0.005",
            "maximum_price": "0.02",
            "xch_budget": "1",
            "cat_budget": "2000",
            "fee_budget_xch": "0.01",
            "subsidy_budget_xch": "0",
            "created_at": "2026-09-22T10:00:00Z",
            "expires_at": "2026-09-23T10:00:00Z",
        }
    )
    campaign = database.get_bootstrap_campaign(campaign_id)
    worker_args = {
        "xch_target": 2,
        "cat_target": 1,
        "buy_tier_sizes": "inner=0.1,fees=0.001",
        "cat_tier_sizes": "inner=9",
        "tier_counts_xch": "inner=1,fees=1",
        "tier_counts_cat": "inner=1",
        "prep_headroom_pct": "0",
    }

    def bootstrap_context(options):
        assert options == {
            "coin_multiplier": "1",
            "target_seconds": 300,
            "bootstrap_campaign_id": campaign_id,
            "bootstrap_campaign_revision": 0,
        }
        return {
            "campaign": database.get_bootstrap_campaign(campaign_id),
            "worker_args": worker_args,
            "xch_balance_mojos": 200_000_000_000,
            "cat_balance_mojos": 20_000,
            "cat_decimals": 3,
        }

    monkeypatch.setattr(
        coin_prep, "_active_bootstrap_coin_prep_context", bootstrap_context
    )

    def quote(cost, target_seconds):
        return {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 1000,
            "expires_at": 1060,
        }

    monkeypatch.setattr(service, "quote_fee", quote)
    monkeypatch.setattr(pricing, "quote_fee", quote)
    prepare_unsigned_wallet(state, monkeypatch)
    preview = service.preview_coin_prep_fees(
        {
            "bootstrap_campaign_id": campaign_id,
            "bootstrap_campaign_revision": 0,
        }
    )
    assert preview["available"] is True, preview
    approval = service.approve_coin_prep_fees(
        preview_id=preview["preview_id"],
        maximum_fee_mojos=preview["suggested_maximum_fee_mojos"],
        cancellation_reserve_mojos=preview["estimated_cancellation_fee_mojos"],
    )
    state.update(
        campaign_id=campaign_id,
        campaign=campaign,
        worker_args=worker_args,
        preview=preview,
        approval=approval,
    )
    yield state
    try:
        next(wallet_reads)
    except StopIteration:
        pass


def test_overrun_recovery_preview_does_not_require_creation_authority(
    request, monkeypatch
):
    # Save the real function before the shared fixture substitutes its recipe.
    # The regression specifically needs the campaign policy, not that stub.
    coin_prep = import_module("blueprints.coin_prep")
    real_context = coin_prep._active_bootstrap_coin_prep_context
    state = request.getfixturevalue("approved_bootstrap")
    monkeypatch.setattr(coin_prep, "_active_bootstrap_coin_prep_context", real_context)
    bootstrap = import_module("blueprints.bootstrap")
    database = import_module("database")
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
                "confirmed_wallet_balance": 200_000_000_000 if wallet_id == 1 else 20_000
            },
        }

    monkeypatch.setattr(wallet, "get_wallet_balance", balance)
    options = {
        "bootstrap_campaign_id": state["campaign_id"],
        "bootstrap_campaign_revision": 0,
    }
    # Establish that identity, dates and balances are valid before the overrun.
    assert real_context(options)["campaign"]["fee_spent_xch"] == "0"

    # Historical confirmed charges are independent from permission to create.
    # Only the authoritative evidence boundary is injected; policy stays real.
    monkeypatch.setattr(
        database,
        "_bootstrap_campaign_authoritative_fee_spent_mojos",
        lambda _conn, campaign_id, **_context: 10_000_000_010 if campaign_id == state["campaign_id"] else 0,
    )
    with pytest.raises(ValueError, match="bootstrap_coin_prep_not_authorized:fee_reserve"):
        real_context(options)
    before = utils._counts()
    app = Flask(__name__)
    app.register_blueprint(coin_prep.bp)
    response = app.test_client().post("/api/coin-prep/fee-preview", json=options)
    payload = response.get_json()

    assert utils._counts() == before, "a recovery preview must not grant spending authority"
    assert response.status_code == 200, payload
    assert payload["available"] is True, payload
    assert payload["fee_accounting"]["spent_fee_mojos"] == "10000000010"
    assert payload["dispatch_authorized"] is False
    assert database.get_bootstrap_campaign(state["campaign_id"])["fee_budget_xch"] == "0.01"

    # The frozen plan is exposed only to price/approve cancellation recovery;
    # it must not become executable Coin Prep or offer-creation authority.
    runtime = import_module("coin_prep_fee_runtime")
    with pytest.raises(ValueError, match="FEE_CAMPAIGN_BUDGET_EXCEEDED"):
        runtime.read_approved_prep_fee_snapshot(state["approval"]["approval_id"])

    # A stop request disables creation immediately but must not strand the
    # outstanding protected cancellation obligation across a restart.
    assert database.stop_bootstrap_campaign(
        state["campaign_id"], "manual", "2026-09-22T12:01:00.000000Z"
    )
    service = import_module("coin_prep_fee_approval")
    assert service.preview_coin_prep_fees(options)["available"] is True
    stopped_preview = app.test_client().post(
        "/api/coin-prep/fee-preview", json=options
    )
    assert stopped_preview.status_code == 200, stopped_preview.get_json()
    recovered = runtime.read_approved_prep_fee_snapshot(
        state["approval"]["approval_id"], allow_campaign_fee_recovery=True
    )
    assert recovered["campaign"]["status"] == "stopped"
