"""Wallet balance and strict selectable views require all Sage coin pages."""

import wallet_sage


def _coin(index):
    return {"coin_id": f"{index:064x}", "amount": "100"}


def test_selectable_only_includes_later_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wid: False)

    def fake_rpc(endpoint, payload, timeout):
        assert endpoint == "get_coins"
        assert payload["filter_mode"] == "selectable"
        offset = payload["offset"]
        rows = [_coin(index) for index in range(501)]
        return {"coins": rows[offset : offset + payload["limit"]], "total": 501}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    result = wallet_sage.get_selectable_coins_only(1)
    assert result is not None
    assert len(result["confirmed_records"]) == 501


def test_selectable_only_rejects_failed_later_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wid: False)

    def fake_rpc(endpoint, payload, timeout):
        if payload["offset"] == 0:
            return {"coins": [_coin(index) for index in range(500)]}
        return {"success": False, "error": "SAGE_TIMEOUT"}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    assert wallet_sage.get_selectable_coins_only(1) is None


def test_selectable_only_uses_stable_pages_and_preserves_amount_order(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wid: False)

    def fake_rpc(endpoint, payload, timeout):
        assert payload["sort_mode"] == "coin_id"
        assert payload["ascending"] is True
        offset = payload["offset"]
        rows = [_coin(index) for index in range(501)]
        rows[500]["amount"] = "1000"
        return {"coins": rows[offset : offset + payload["limit"]], "total": 501}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    result = wallet_sage.get_selectable_coins_only(1)
    assert result["confirmed_records"][0]["coin"]["amount"] == 1000


def test_cat_balance_sums_all_pages(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wid: True)
    monkeypatch.setattr(wallet_sage, "_resolve_asset_id", lambda _wid: "ab" * 32)
    monkeypatch.setattr(wallet_sage, "_get_cat_asset_id", lambda: "ab" * 32)

    def fake_rpc(endpoint, payload, timeout):
        offset = payload["offset"]
        count = 501 if payload["filter_mode"] == "owned" else 500
        rows = [_coin(index) for index in range(count)]
        return {"coins": rows[offset : offset + payload["limit"]], "total": count}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    result = wallet_sage.get_wallet_balance(2)
    assert result["success"] is True
    assert result["wallet_balance"]["confirmed_wallet_balance"] == 50100
    assert result["wallet_balance"]["spendable_balance"] == 50000


def test_xch_balance_rejects_failed_owned_later_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wid: False)

    def fake_rpc(endpoint, payload, timeout):
        if endpoint == "get_sync_status":
            return {"selectable_balance": 50000}
        if payload["offset"] == 0:
            return {"coins": [_coin(index) for index in range(500)]}
        return {"success": False, "error": "SAGE_TIMEOUT"}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    result = wallet_sage.get_wallet_balance(1)
    assert result["success"] is False


def test_xch_balance_includes_later_owned_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wid: False)

    def fake_rpc(endpoint, payload, timeout):
        if endpoint == "get_sync_status":
            return {"selectable_balance": 50000}
        offset = payload["offset"]
        rows = [_coin(index) for index in range(501)]
        return {"coins": rows[offset : offset + payload["limit"]], "total": 501}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    result = wallet_sage.get_wallet_balance(1)
    assert result["success"] is True
    assert result["wallet_balance"]["confirmed_wallet_balance"] == 50100
