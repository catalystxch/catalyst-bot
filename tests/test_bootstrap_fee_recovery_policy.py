"""Recovery quotes must be reachable through the real campaign policy boundary."""

from datetime import datetime, timezone
from importlib import import_module

from flask import Flask
import pytest

import fee_approval_test_utils as utils

from test_coin_prep_fee_bootstrap_integration import (
    approved_bootstrap,  # noqa: F401 - disposable ledger and unsigned wallet
)


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
        "get_bootstrap_campaign_authoritative_fee_spent_mojos",
        lambda campaign_id: 10_000_000_010 if campaign_id == state["campaign_id"] else 0,
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
