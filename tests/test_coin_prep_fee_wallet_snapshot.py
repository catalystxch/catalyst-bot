"""Fresh server-owned wallet reads must not use configured fallback inventory."""

import copy
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

from chia_rs import Coin
import pytest

import database
import wallet
import wallet_sage


ASSET = "36" * 32
ADDRESS = "xch1xgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgequ6kqev"


def _service():
    try:
        return import_module("coin_prep_fee_runtime")
    except ModuleNotFoundError:
        pytest.fail("current authoritative fee wallet collector is missing")


def _coin(index, amount="2000"):
    parent, puzzle = index.to_bytes(32, "big"), bytes.fromhex("32" * 32)
    return {"coin_id": Coin(parent, puzzle, int(amount)).name().hex(),
            "address": ADDRESS, "amount": amount, "transaction_id": None,
            "offer_id": None, "clawback_timestamp": None, "created_height": 1,
            "spent_height": None, "spent_timestamp": None, "created_timestamp": 100}


def _cat():
    return {"asset_id": ASSET, "name": "Test CAT", "ticker": "MZ", "precision": 3,
            "description": None, "icon_url": None, "visible": True, "balance": 2000,
            "selectable_balance": 2000, "revocation_address": None}


@pytest.fixture
def live_reads(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "fee-wallet.db"))
    database.init_database()
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", wallet_sage)
    identity = {"success": True, "backend": "sage", "fingerprint": 736588221,
                "network_id": "mainnet", "has_secrets": True, "kind": "hot", "name": "TEST 7"}
    config = SimpleNamespace(WALLET_TYPE="sage", CAT_WALLET_ID=2, WALLET_ID_XCH=1,
                             CAT_ASSET_ID=ASSET, CAT_TICKER_ID="MZ_XCH", CAT_DECIMALS=3,
                             SAGE_FINGERPRINT="736588221", XCH_RESERVE=Decimal("0"),
                             CAT_RESERVE=Decimal("0"))
    state = {"identity": identity, "config": config, "cats": {"cats": [_cat()]},
             "xch": [_coin(1)], "cat": [_coin(10001)], "reads": [], "monkeypatch": monkeypatch}
    monkeypatch.setattr(wallet, "get_wallet_identity", lambda: copy.deepcopy(state["identity"]))
    monkeypatch.setattr(wallet, "get_next_address", lambda wid, new_address: {
        "success": True, "address": ADDRESS} if wid == 1 and new_address is False else pytest.fail("address mutation"))
    monkeypatch.setenv("CATALYST_NETWORK_ID", "mainnet")

    def transport(endpoint, payload, *, timeout):
        state["reads"].append((endpoint, copy.deepcopy(payload)))
        if endpoint == "get_cats":
            return copy.deepcopy(state["cats"])
        assert endpoint == "get_coins"
        assert payload["filter_mode"] == "selectable"
        assert payload["asset_id"] in (None, ASSET)
        values = state["xch"] if payload["asset_id"] is None else state["cat"]
        if payload["sort_mode"] == "coin_id" and payload["ascending"] is True:
            values = sorted(values, key=lambda row: row["coin_id"])
        offset, limit = payload["offset"], payload["limit"]
        result = {"coins": copy.deepcopy(values[offset:offset + limit]), "total": len(values)}
        if state.get("switch_on_coins"):
            state["identity"]["fingerprint"] = 12345
        if state.get("change_config"):
            state["config"].CAT_ASSET_ID = "37" * 32
        if state.get("change_modern_size"):
            state["config"].BUY_INNER_SIZE_XCH = Decimal("2")
        if state.get("repeat_page"):
            result["coins"] = copy.deepcopy(values[:limit])
        if "total_override" in state:
            result["total"] = state["total_override"]
        if state.get("omit_total"):
            result.pop("total")
        if state.get("change_total") and offset:
            result["total"] += 1
        if state.get("reverse_page"):
            result["coins"].reverse()
        return result

    monkeypatch.setattr(wallet_sage, "_sage_post", transport)
    yield state
    database.close_connection()


def _collect(state):
    service = _service()
    state["monkeypatch"].setattr(service, "cfg", state["config"])
    return service.read_fee_wallet_snapshot()


def test_fresh_identity_asset_and_integer_selectable_inventory_without_effects(live_reads):
    result = _collect(live_reads)
    assert result["identity"]["wallet_fingerprint"] == 736588221
    assert result["identity"]["asset_id"] == ASSET
    assert result["identity"]["ticker"] == "MZ_XCH"
    assert result["receive_address"] == ADDRESS
    assert [(c.asset, c.amount_mojos) for c in result["snapshot"].coins] == [("xch", 2000), ("cat", 2000)]
    conn = database.get_connection()
    for table in ("coin_prep_operations", "wallet_effect_claims", "approved_fee_reservations"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("cats", [None, {}, {"success": False, "cats": [{"asset_id": ASSET}]},
                                  {"cats": []}, {"cats": [{"asset_id": "37" * 32}]},
                                  {"cats": [{"asset_id": ASSET}, {"asset_id": ASSET}]}])
def test_configured_asset_is_not_evidence_of_actual_wallet_asset(live_reads, cats):
    live_reads["cats"] = cats
    with pytest.raises(ValueError, match="FEE_WALLET_ASSET_UNAVAILABLE"):
        _collect(live_reads)


@pytest.mark.parametrize("mutation", [
    {"fingerprint": True}, {"fingerprint": 12345}, {"network_id": "testnet11"},
    {"backend": "chia"}, {"has_secrets": False}, {"success": False},
])
def test_wrong_or_malformed_identity_cannot_supply_preview_inventory(live_reads, mutation):
    live_reads["identity"].update(mutation)
    with pytest.raises(ValueError, match="FEE_WALLET_IDENTITY_UNAVAILABLE"):
        _collect(live_reads)
    assert live_reads["reads"] == []


@pytest.mark.parametrize("flag", ["switch_on_coins", "change_config", "change_modern_size"])
def test_identity_and_configuration_switch_during_reads_is_rejected(live_reads, flag):
    live_reads[flag] = True
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        _collect(live_reads)


def test_inventory_paginates_instead_of_silently_truncating_500_coins(live_reads):
    live_reads["xch"] = [_coin(i + 1) for i in range(501)]
    result = _collect(live_reads)
    assert len([c for c in result["snapshot"].coins if c.asset == "xch"]) == 501
    assert ("get_coins", {"asset_id": None, "offset": 500, "limit": 500,
                          "sort_mode": "coin_id", "filter_mode": "selectable", "ascending": True}) in live_reads["reads"]


def test_repeated_page_is_not_a_complete_inventory(live_reads):
    live_reads["xch"] = [_coin(i + 1) for i in range(501)]
    live_reads["repeat_page"] = True
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


@pytest.mark.parametrize("amount", [True, 1.5, "2.5", "-1", "NaN"])
def test_malformed_atomic_inventory_amount_is_not_coerced(live_reads, amount):
    live_reads["xch"][0]["amount"] = amount
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


@pytest.mark.parametrize("coin_id", [None, "38", True, "g" * 64])
def test_inventory_coin_id_must_be_canonical(live_reads, coin_id):
    live_reads["xch"][0]["coin_id"] = coin_id
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


@pytest.mark.parametrize("total", [None, True, -1, "1", 1.5, 0, 2, 10001])
def test_incomplete_or_malformed_inventory_total_is_rejected(live_reads, total):
    live_reads["total_override"] = total
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


def test_missing_inventory_total_is_not_a_complete_snapshot(live_reads):
    live_reads["omit_total"] = True
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


def test_inventory_total_change_during_pagination_is_rejected(live_reads):
    live_reads["xch"] = [_coin(i + 1) for i in range(501)]
    live_reads["change_total"] = True
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


def test_empty_inventory_is_available_only_with_a_zero_total(live_reads):
    live_reads["xch"] = []
    live_reads["cat"] = []
    assert _collect(live_reads)["snapshot"].coins == ()


@pytest.mark.parametrize("precision", [None, True, "3", 4])
def test_wallet_asset_precision_must_match_economic_configuration(live_reads, precision):
    live_reads["cats"]["cats"][0]["precision"] = precision
    with pytest.raises(ValueError, match="FEE_WALLET_ASSET_UNAVAILABLE"):
        _collect(live_reads)


def test_optional_native_asset_metadata_does_not_hide_actual_cat(live_reads):
    native = {**_cat(), "asset_id": None, "name": "Chia", "ticker": "XCH", "precision": 12}
    live_reads["cats"]["cats"].insert(0, native)
    assert _collect(live_reads)["identity"]["asset_id"] == ASSET


@pytest.mark.parametrize("mutation", [{"offer_id": "38" * 32}, {"spent_height": 1},
                                      {"spent_timestamp": 100}, {"address": "xch1invalid"}])
def test_nonselectable_or_invalid_address_record_is_rejected(live_reads, mutation):
    live_reads["xch"][0].update(mutation)
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


def test_unstable_coin_order_cannot_supply_a_complete_inventory(live_reads):
    live_reads["xch"] = [_coin(1), _coin(2)]
    live_reads["reverse_page"] = True
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)
