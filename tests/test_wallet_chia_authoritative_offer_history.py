"""The cancellation history reader must distinguish empty from malformed."""

from unittest.mock import patch

import wallet_chia


def test_authoritative_chia_history_rejects_missing_collection():
    with patch.object(wallet_chia, "rpc", return_value={"success": True}):
        assert wallet_chia.get_authoritative_offer_history(False, 0, 50) is None


def test_authoritative_chia_history_rejects_malformed_collection():
    with patch.object(
        wallet_chia, "rpc", return_value={"success": True, "trades": "bad"}
    ):
        assert wallet_chia.get_authoritative_offer_history(False, 0, 50) is None


def test_authoritative_chia_history_accepts_explicit_empty_page():
    with patch.object(wallet_chia, "rpc", return_value={"success": True, "trades": []}):
        assert wallet_chia.get_authoritative_offer_history(False, 0, 50) == []


def test_authoritative_chia_history_rejects_ambiguous_collections():
    response = {"success": True, "trades": [], "offers": [{"trade_id": "abc"}]}
    with patch.object(wallet_chia, "rpc", return_value=response):
        assert wallet_chia.get_authoritative_offer_history(False, 0, 50) is None


def test_authoritative_chia_history_accepts_nested_data_page():
    response = {"success": True, "data": {"trades": [{"trade_id": "abc"}]}}
    with patch.object(wallet_chia, "rpc", return_value=response) as rpc:
        assert wallet_chia.get_authoritative_offer_history(False, 50, 100) == [
            {"trade_id": "abc"}
        ]
    assert rpc.call_args.args == (
        "get_all_offers",
        {
            "include_completed": False,
            "start": 50,
            "end": 100,
            "reverse": True,
        },
    )
