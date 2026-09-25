"""A second stop must not prevent reviewing a fresh cleanup fee budget."""

from importlib import import_module

from flask import Flask

import api_server  # noqa: F401 - pin the blueprint import graph for this test file
import fee_approval_test_utils as utils
from bootstrap_fee_fixture import approved_bootstrap  # noqa: F401
from test_bootstrap_stopped_fee_renewal import automatically_stopped_campaign  # noqa: F401


def test_explicit_stop_after_policy_stop_can_preview_new_cleanup_consent(
    automatically_stopped_campaign,
):
    state = automatically_stopped_campaign
    database = import_module("database")
    coin_prep = import_module("blueprints.coin_prep")
    # The fixture materializes a genuine policy stop at revision 1. The actual
    # explicit-stop transition advances to 2 without changing any economics.
    assert database.stop_bootstrap_campaign(
        state["campaign_id"], "manual", "2026-09-22T12:01:00.000000Z"
    )
    database.close_connection()
    campaign = database.get_bootstrap_campaign(state["campaign_id"])
    assert campaign["status"] == "stopped"
    assert campaign["stage"] == "stopped"
    assert campaign["revision"] == 2
    assert campaign["fee_budget_xch"] == "0.01"
    assert campaign["fee_spent_xch"] == "0.01000000001"
    before = utils._counts()
    app = Flask(__name__)
    app.register_blueprint(coin_prep.bp)

    response = app.test_client().post(
        "/api/coin-prep/fee-preview",
        json={
            "bootstrap_campaign_id": state["campaign_id"],
            "bootstrap_campaign_revision": 2,
        },
    )
    payload = response.get_json()

    assert utils._counts() == before, "review must not create consent, holds or effects"
    # This asks only for a new truthful quote. It does not demand that the old
    # approval becomes executable across arbitrary revision changes.
    assert response.status_code == 200, payload
    assert payload["available"] is True, payload
    assert payload["fee_accounting"]["spent_fee_mojos"] == "10000000010"
    assert payload["dispatch_authorized"] is False
