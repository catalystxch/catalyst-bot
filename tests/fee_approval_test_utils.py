"""Shared fee fixtures bind dependencies at setup, never at module collection."""

import copy
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

from chia_rs import Coin
import pytest

ASSET = "36" * 32
ADDRESS = "xch1xgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgequ6kqev"


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


def live_reads(tmp_path, monkeypatch):
    # Project modules are restored per test file by conftest. This fixture is
    # also reused across files, so bind the current isolated module instances.
    import database
    import wallet
    import wallet_sage

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



def economic_reads(live_reads, monkeypatch):
    import api_server
    from blueprints import coin_prep
    import tx_fees

    configuration = live_reads["config"]
    for key, value in {"TIER_ENABLED": True, "BUY_LADDER_REVERSED": False,
                       "LIQUIDITY_MODE": "two_sided", "COIN_PREP_HEADROOM_PCT": Decimal("10"),
                       "SPREAD_BPS": Decimal("10000"), "MIN_EDGE_BPS": Decimal("0"),
                       "MAX_ACTIVE_BUY_OFFERS": 1, "MAX_ACTIVE_SELL_OFFERS": 1,
                       "DEFAULT_TRADE_XCH": Decimal("0.1"), "FEE_PREP_COUNT": 2,
                       "FEE_COIN_SIZE_XCH": Decimal("0.001"), "TRANSACTION_FEE_MODE": "manual",
                       "TRANSACTION_FEE_XCH": Decimal("0.00001")}.items():
        setattr(configuration, key, value)
    for tier, size in (("INNER", "0.1"), ("MID", "0.075"), ("OUTER", "0.05"), ("EXTREME", "0.01")):
        setattr(configuration, f"{tier}_SIZE_XCH", Decimal(size))
        for side in ("BUY", "SELL"):
            setattr(configuration, f"{side}_{tier}_SIZE_XCH", Decimal(size))
            setattr(configuration, f"{side}_{tier}_TIER_COUNT", 1 if tier == "INNER" else 0)
            setattr(configuration, f"{side}_{tier}_TIER_SPARE_COUNT", 0)
    monkeypatch.setattr(tx_fees, "cfg", configuration)
    monkeypatch.setattr(coin_prep, "cfg", configuration)

    def price():
        if live_reads.get("change_fee_configuration"):
            configuration.TRANSACTION_FEE_XCH = Decimal("0.00002")
        if live_reads.get("switch_on_price"):
            live_reads["identity"]["fingerprint"] = 12345
        return live_reads.get("live_price", "0.01")

    monkeypatch.setattr(api_server, "_get_live_mid_price_str", price)
    return live_reads


def _economic_collect(state, options=None):
    service = import_module("coin_prep_fee_runtime")
    state["monkeypatch"].setattr(service, "cfg", state["config"])
    collector = getattr(service, "read_fee_economic_snapshot", None)
    assert callable(collector), "authoritative runtime economic collector is missing"
    return collector({} if options is None else options)


def confirmation(economic_reads, monkeypatch):
    import coin_prep_fee_approval as service
    import database
    import wallet

    state = economic_reads
    state["xch"] = [_coin(1, str(112_000_001_000))]
    state["cat"] = [_coin(10001, "11000")]
    context = _economic_collect(state)
    scope = service.resolve_server_fee_scope(identity=context["identity"])
    monkeypatch.setattr(service, "_now", lambda: state.get("now", 1000))
    monkeypatch.setattr(database, "time", SimpleNamespace(time=lambda: state.get("now", 1000)))
    monkeypatch.setattr(service, "quote_fee", lambda cost, target_seconds: {
        "available": True, "fee_mojos": 10 if cost == 100 else 30,
        "observed_at": 1000, "expires_at": 1060, "source": "coinset",
        "cost": cost, "target_seconds": target_seconds,
    })
    preview = service.estimate_coin_prep_fee_preview(
        scope=scope, economic_plan=context["recipe"]["economic_plan"],
        stages=[{"stage_id": name, "cost": cost, "cost_kind": "projected",
                 "transaction_count_min": 1, "transaction_count_max": 1,
                 "cancellation": cancel}
                for name, cost, cancel in (("prep", 1000, False), ("cancel", 100, True))],
        fee_funding_mojos=1000, request_options=context["request_options"],
    )
    state["preview"] = preview
    state["reads"].clear()

    def forbidden(*_args, **_kwargs):
        pytest.fail("confirmation attempted to build, sign, submit or reprice instead of recording consent")

    monkeypatch.setattr(wallet, "build_transaction_rpc", forbidden)
    monkeypatch.setattr(wallet, "submit_built_transaction_rpc", forbidden)
    monkeypatch.setattr(service, "quote_fee", forbidden)
    return state


def _counts():
    import database

    return {table: database.get_connection().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("fee_approvals", "coin_prep_fee_consents", "approved_fee_reservations",
                          "coin_prep_operations", "wallet_effect_claims")}

