"""Repeated policy revisions do not relax canonical recovery consent."""

from decimal import Decimal
from importlib import import_module

from flask import Flask
import pytest

import api_server  # noqa: F401 - establish this file's isolated blueprint graph
import fee_approval_test_utils as utils
from bootstrap_fee_fixture import approved_bootstrap  # noqa: F401
from test_bootstrap_stopped_fee_renewal import automatically_stopped_campaign  # noqa: F401


@pytest.mark.parametrize("change", ["reserve", "fingerprint", "address"])
def test_repeated_stop_recovery_refuses_changed_canonical_context(
    automatically_stopped_campaign, monkeypatch, change
):
    state = automatically_stopped_campaign
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    wallet = import_module("wallet")
    assert database.stop_bootstrap_campaign(
        state["campaign_id"], "manual", "2026-09-22T12:01:00Z"
    )
    database.close_connection()
    assert database.get_bootstrap_campaign(state["campaign_id"])["revision"] == 2

    if change == "reserve":
        state["config"].XCH_RESERVE = Decimal("0.01")
    elif change == "fingerprint":
        state["identity"]["fingerprint"] = 12345
    else:
        from chia.util.bech32m import encode_puzzle_hash
        from chia_rs.sized_bytes import bytes32

        other_address = encode_puzzle_hash(bytes32(b"a" * 32), "xch")
        monkeypatch.setattr(wallet, "get_next_address", lambda *args, **kwargs: {
            "success": True, "address": other_address,
        })
    before = utils._counts()
    app = Flask(__name__)
    app.register_blueprint(import_module("blueprints.coin_prep").bp)
    response = app.test_client().post("/api/coin-prep/fee-preview", json={
        "bootstrap_campaign_id": state["campaign_id"],
        "bootstrap_campaign_revision": 2,
    })
    payload = response.get_json()

    assert response.status_code == 409, payload
    assert payload["success"] is False, payload
    assert payload["reason"] == (
        "FEE_WALLET_IDENTITY_UNAVAILABLE" if change == "fingerprint"
        else "FEE_PREP_CAMPAIGN_UNAVAILABLE"
    )
    assert payload["dispatch_authorized"] is False
    with pytest.raises(ValueError):
        runtime.read_approved_prep_fee_snapshot(
            state["approval"]["approval_id"], allow_campaign_fee_recovery=True
        )
    assert utils._counts() == before
    campaign = database.get_bootstrap_campaign(state["campaign_id"])
    assert campaign["status"] == "stopped"
    assert campaign["fee_budget_xch"] == "0.01"
    assert campaign["fee_spent_xch"] == "0.01000000001"
