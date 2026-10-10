"""Coin Prep must read the live Sage book after terminal history grows."""

import api_server  # noqa: F401 - registers blueprints before direct import
from blueprints import coin_prep
import wallet
import wallet_sage


def test_coin_prep_uses_complete_live_book_beyond_terminal_history_cap(monkeypatch):
    terminal = [
        {"offer_id": f"{index:064x}", "status": "CANCELLED"} for index in range(4097)
    ]
    active_id = "f" * 64
    active = {
        "offer_id": active_id,
        "status": 1,
        "summary": {"offered": {"xch": 1000}, "requested": {}},
    }

    def sage_rpc(method, payload, timeout):
        assert method == "get_offers"
        return {"success": True, "offers": [*terminal, active]}

    monkeypatch.setattr(wallet_sage, "rpc", sage_rpc)
    monkeypatch.setattr(
        wallet,
        "get_authoritative_offer_history",
        wallet_sage.get_authoritative_offer_history,
    )

    snapshot = coin_prep._wallet_open_offer_snapshot_before_prep()

    assert snapshot["complete"] is True
    assert snapshot["open_offer_count"] == 1
    assert snapshot["open_buy_count"] == 1
    assert snapshot["open_trade_ids"] == [active_id]
