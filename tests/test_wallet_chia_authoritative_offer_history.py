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


def test_general_chia_offer_reader_rejects_missing_collection():
    with patch.object(wallet_chia, "rpc", return_value={"success": True}):
        assert wallet_chia.get_all_offers(False, 0, 50) is None


def test_general_chia_offer_reader_rejects_malformed_collection():
    with patch.object(
        wallet_chia, "rpc", return_value={"success": True, "trades": "bad"}
    ):
        assert wallet_chia.get_all_offers(False, 0, 50) is None


def test_general_chia_offer_reader_accepts_explicit_empty_page():
    with patch.object(wallet_chia, "rpc", return_value={"success": True, "trades": []}):
        assert wallet_chia.get_all_offers(False, 0, 50) == []


def test_open_chia_offer_reader_rejects_idless_short_page():
    row = {"status": "PENDING_ACCEPT", "summary": {"offered": {}, "requested": {}}}
    with patch.object(
        wallet_chia, "rpc", return_value={"success": True, "trades": [row]}
    ):
        assert wallet_chia.get_all_offers(False, 0, 50) is None


def test_open_chia_offer_reader_rejects_duplicate_ids_on_short_page():
    rows = [{"trade_id": "same"}, {"trade_id": "same"}]
    with patch.object(
        wallet_chia, "rpc", return_value={"success": True, "trades": rows}
    ):
        assert wallet_chia.get_all_offers(False, 0, 50) is None


def test_open_chia_offer_reader_retrieves_all_pages_before_claiming_freshness():
    all_rows = [{"trade_id": f"trade-{index}"} for index in range(501)]

    def paged_rpc(_endpoint, payload, timeout=8):
        return {
            "success": True,
            "trades": all_rows[payload["start"] : payload["end"]],
        }

    with patch.object(wallet_chia, "rpc", side_effect=paged_rpc) as rpc:
        result = wallet_chia.get_all_offers(False, 0, 500)

    assert result == all_rows
    assert rpc.call_count == 4


def test_open_chia_offer_reader_continues_after_multiple_full_pages():
    all_rows = [{"trade_id": f"trade-{index}"} for index in range(1001)]

    def paged_rpc(_endpoint, payload, timeout=8):
        return {
            "success": True,
            "trades": all_rows[payload["start"] : payload["end"]],
        }

    with patch.object(wallet_chia, "rpc", side_effect=paged_rpc) as rpc:
        result = wallet_chia.get_all_offers(False, 0, 500)

    assert result == all_rows
    assert rpc.call_count == 6


def test_open_chia_offer_reader_rejects_failed_later_page():
    rows = [{"trade_id": f"trade-{index}"} for index in range(50)]
    with patch.object(
        wallet_chia,
        "rpc",
        side_effect=[{"success": True, "trades": rows}, {"success": False}],
    ) as rpc:
        assert wallet_chia.get_all_offers(False, 0, 50) is None
    assert rpc.call_count == 2


def test_open_chia_offer_reader_rejects_repeated_page():
    rows = [{"trade_id": f"trade-{index}"} for index in range(50)]
    with patch.object(
        wallet_chia,
        "rpc",
        return_value={"success": True, "trades": rows},
    ) as rpc:
        assert wallet_chia.get_all_offers(False, 0, 50) is None
    assert rpc.call_count == 2


def test_open_chia_offer_reader_confirms_exact_page_multiple_is_complete():
    rows = [{"trade_id": f"trade-{index}"} for index in range(100)]

    def paged_rpc(_endpoint, payload, timeout=8):
        return {"success": True, "trades": rows[payload["start"] : payload["end"]]}

    with patch.object(wallet_chia, "rpc", side_effect=paged_rpc) as rpc:
        assert wallet_chia.get_all_offers(False, 0, 50) == rows
    assert rpc.call_count == 6


def test_open_chia_offer_reader_fails_closed_at_page_limit():
    def paged_rpc(_endpoint, payload, timeout=8):
        return {"success": True, "trades": [{"trade_id": str(payload["start"])}]}

    with patch.object(wallet_chia, "rpc", side_effect=paged_rpc) as rpc:
        assert wallet_chia.get_all_offers(False, 0, 1) is None
    assert rpc.call_count == 40


def test_open_chia_offer_reader_rejects_overfull_page():
    rows = [{"trade_id": f"trade-{index}"} for index in range(51)]
    with patch.object(
        wallet_chia,
        "rpc",
        return_value={"success": True, "trades": rows},
    ) as rpc:
        assert wallet_chia.get_all_offers(False, 0, 50) is None
    assert rpc.call_count == 1


def test_open_chia_offer_reader_rejects_book_shift_during_pagination():
    pages = [
        {"success": True, "trades": [{"trade_id": "a"}, {"trade_id": "b"}]},
        {"success": True, "trades": [{"trade_id": "d"}]},
        {"success": True, "trades": [{"trade_id": "b"}, {"trade_id": "c"}]},
        {"success": True, "trades": [{"trade_id": "d"}]},
    ]
    with patch.object(wallet_chia, "rpc", side_effect=pages) as rpc:
        assert wallet_chia.get_all_offers(False, 0, 2) is None
    assert rpc.call_count == 4


def test_open_chia_offer_reader_rejects_changed_status_between_passes():
    pages = [
        {"success": True, "trades": [{"trade_id": "a", "status": "PENDING_ACCEPT"}]},
        {"success": True, "trades": []},
        {"success": True, "trades": [{"trade_id": "a", "status": "PENDING_CANCEL"}]},
        {"success": True, "trades": []},
    ]
    with patch.object(wallet_chia, "rpc", side_effect=pages) as rpc:
        assert wallet_chia.get_all_offers(False, 0, 1) is None
    assert rpc.call_count == 4


def test_authoritative_chia_history_keeps_requested_page_bounds():
    rows = [{"trade_id": f"trade-{index}"} for index in range(50)]
    with patch.object(
        wallet_chia,
        "rpc",
        return_value={"success": True, "trades": rows},
    ) as rpc:
        assert wallet_chia.get_authoritative_offer_history(False, 0, 50) == rows
    assert rpc.call_count == 1
