"""Incomplete Sage owned-coin pages cannot become reconciliation authority."""

import wallet_sage


def _coin(index):
    return {
        "coin_id": f"{index:064x}",
        "amount": "100",
        "offer_id": None,
        "created_height": 1,
        "spent_height": None,
        "transaction_id": None,
    }


def test_detailed_owned_coins_rejects_failed_later_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)

    def fake_rpc(endpoint, payload, timeout):
        assert endpoint == "get_coins"
        assert payload["filter_mode"] == "owned"
        if payload["offset"] == 0:
            return {"coins": [_coin(index) for index in range(500)], "total": 501}
        return {"success": False, "error": "SAGE_CONNECTION_ERROR"}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)

    assert wallet_sage.get_owned_coins_detailed(1) is None


def test_basic_owned_coins_includes_later_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)

    def fake_rpc(endpoint, payload, timeout):
        assert endpoint == "get_coins"
        assert payload["filter_mode"] == "owned"
        if payload["offset"] == 0:
            return {"coins": [_coin(index) for index in range(500)], "total": 501}
        if payload["offset"] == 500:
            return {"coins": [_coin(500)], "total": 501}
        raise AssertionError("unexpected Sage page")

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)

    owned = wallet_sage.get_owned_coins(1)
    assert owned is not None
    assert len(owned) == 501
    assert owned[f"0x{500:064x}"] == 100


def test_detailed_owned_coins_rejects_unproven_page_limit(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)

    def fake_rpc(endpoint, payload, timeout):
        assert endpoint == "get_coins"
        assert payload["filter_mode"] == "owned"
        offset = payload["offset"]
        return {"coins": [_coin(index) for index in range(offset, offset + 500)]}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)

    assert wallet_sage.get_owned_coins_detailed(1) is None


def test_selectable_coins_includes_later_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)

    def fake_rpc(endpoint, payload, timeout):
        assert endpoint == "get_coins"
        assert payload["filter_mode"] == "selectable"
        if payload["offset"] == 0:
            return {"coins": [_coin(index) for index in range(500)]}
        return {"coins": [_coin(500)]}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    selectable = wallet_sage.get_selectable_coins_map(1)
    assert selectable is not None
    assert len(selectable) == 501


def test_selectable_coins_rejects_failed_later_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)

    def fake_rpc(endpoint, payload, timeout):
        if payload["offset"] == 0:
            return {"coins": [_coin(index) for index in range(500)]}
        return {"success": False, "error": "SAGE_CONNECTION_ERROR"}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    assert wallet_sage.get_selectable_coins_map(1) is None


def test_detailed_owned_coins_rejects_malformed_coin(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {"coins": [_coin(1), {"amount": "100"}]},
    )
    assert wallet_sage.get_owned_coins_detailed(1) is None


def test_detailed_owned_coins_rejects_boolean_amount(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {
            "coins": [{**_coin(1), "amount": True}],
            "total": 1,
        },
    )
    assert wallet_sage.get_owned_coins_detailed(1) is None


def test_selectable_coins_rejects_fractional_amount(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {
            "coins": [{**_coin(1), "amount": 1.5}],
            "total": 1,
        },
    )
    assert wallet_sage.get_selectable_coins_map(1) is None


def test_detailed_owned_coins_rejects_repeated_page(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)

    def fake_rpc(_endpoint, payload, timeout):
        if payload["offset"] == 0:
            return {"coins": [_coin(index) for index in range(500)]}
        return {"coins": [_coin(499)]}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    assert wallet_sage.get_owned_coins_detailed(1) is None


def test_detailed_owned_coins_rejects_changing_total(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)

    def fake_rpc(_endpoint, payload, timeout):
        if payload["offset"] == 0:
            return {"coins": [_coin(index) for index in range(500)], "total": 501}
        return {"coins": [_coin(500)], "total": 502}

    monkeypatch.setattr(wallet_sage, "rpc", fake_rpc)
    assert wallet_sage.get_owned_coins_detailed(1) is None


def test_selectable_coins_rejects_short_page_with_larger_total(monkeypatch):
    monkeypatch.setattr(wallet_sage, "_is_cat_wallet", lambda _wallet_id: False)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {"coins": [_coin(1)], "total": 2},
    )
    assert wallet_sage.get_selectable_coins_map(1) is None
