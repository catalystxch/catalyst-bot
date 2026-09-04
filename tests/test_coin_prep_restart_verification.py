"""Recheck saved asymmetric prep against wallet coins after an app restart."""

import json

import pytest

import api_server
import database
import wallet
from blueprints import coin_prep


@pytest.mark.parametrize(
    "case,expected_complete",
    [
        ("asymmetric", True),
        ("legacy", True),
        ("missing_xch", False),
        ("wrong_cat_size", False),
        ("unavailable_wallet", False),
        ("overlapping_fee_shortfall", False),
        ("disabled_cat", True),
    ],
)
def test_restart_rechecks_each_saved_side_against_wallet(
    monkeypatch, tmp_path, case, expected_complete
):
    saved = {
        "tier_enabled": True,
        "tier_sizes_xch": {"inner": "5", "mid": "3", "sniper": "0.1", "fees": "0.1"},
        "tier_sizes_cat": {"inner": "500", "mid": "300", "sniper": "10"},
        "tier_counts": {"inner": 4, "mid": 3, "sniper": 1, "fees": 2},
        "tier_counts_xch": {"inner": 2, "mid": 3, "sniper": 1, "fees": 2},
        "tier_counts_cat": {"inner": 4, "mid": 1, "sniper": 1},
    }
    xch = [5_000_000_000_000] * 2 + [3_000_000_000_000] * 3 + [100_000_000_000] * 3
    cat = [500_000] * 4 + [300_000] + [10_000]
    if case == "legacy":
        saved.pop("tier_counts_xch")
        saved.pop("tier_counts_cat")
        xch += [5_000_000_000_000] * 2
        cat += [300_000] * 2
    elif case == "missing_xch":
        xch.pop(0)
    elif case == "wrong_cat_size":
        cat[0] = 100
    elif case == "overlapping_fee_shortfall":
        xch.pop()
    elif case == "disabled_cat":
        saved["tier_counts_cat"] = {}
        cat = []

    status_path = tmp_path / "status.json"
    last_path = tmp_path / "last.json"
    status_path.write_text(json.dumps({"phase": "complete", "run_id": "previous-run"}))
    last_path.write_text(json.dumps(saved))
    monkeypatch.setattr(coin_prep, "_coin_prep_status_file", lambda: str(status_path))
    monkeypatch.setattr(coin_prep, "_coin_prep_last_file", lambda: str(last_path))
    monkeypatch.setattr(coin_prep, "_tier_size_drift_findings", lambda **_: [])
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_active_cat", {"wallet_id": 2, "decimals": 3})
    monkeypatch.setattr(
        api_server,
        "_coin_prep_state",
        {
            "running": False,
            "complete": False,
            "error": None,
            "run_id": None,
        },
    )
    monkeypatch.setattr(wallet, "WALLET_ID_XCH", 1)

    def wallet_coins(wallet_id):
        if case == "unavailable_wallet":
            return {"success": False}
        return {
            "success": True,
            "records": [
                {"coin": {"amount": amount}}
                for amount in (xch if wallet_id == 1 else cat)
            ],
        }

    monkeypatch.setattr(wallet, "get_spendable_coins_rpc", wallet_coins)
    monkeypatch.setattr(
        wallet, "get_spendable_coin_count", lambda wid: len(xch if wid == 1 else cat)
    )
    monkeypatch.setattr(database, "get_coin_summary", lambda: {})
    monkeypatch.setattr(database, "get_events_since", lambda *_, **__: [])
    monkeypatch.setattr(database, "get_recent_events", lambda *_, **__: [])
    with api_server.app.test_request_context("/api/coin-prep/status"):
        payload = coin_prep.api_coin_prep_status().get_json()

    assert payload["success"] is True
    assert payload["complete"] is expected_complete
    if expected_complete:
        assert payload["previously_complete"] is True
        assert payload["xch_target"] == len(xch)
        assert payload["cat_target"] == len(cat)
