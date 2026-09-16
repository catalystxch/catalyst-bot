"""Server-owned, non-mutating runtime inputs for Coin Prep fee previews.

Inventory is selectable-only and complete or unavailable. No configured asset
fallback, balance-as-inventory assumption, claims, signing or prep launch occurs.
Economic target/stage collection and HTTP/native integration follow this boundary.
"""

import os
import re

from coin_prep_batch_plan import CoinSnapshot, SelectableCoin
from config import cfg
import database
from sage_offer_wire import decode_wallet_puzzle_hash
import wallet


_PAGE_SIZE = 500
_MAX_COIN_PAGES = 20
_CONTEXT_KEYS = (
    "WALLET_TYPE", "CAT_WALLET_ID", "WALLET_ID_XCH", "CAT_ASSET_ID",
    "CAT_TICKER_ID", "CAT_DECIMALS", "SAGE_FINGERPRINT", "WALLET_EXPECTED_NAME",
    "WALLET_EXPECTED_KEY_KIND", "XCH_RESERVE", "CAT_RESERVE", "TIER_ENABLED",
    "BUY_LADDER_REVERSED", "LIQUIDITY_MODE", "MAX_ACTIVE_BUY_OFFERS",
    "MAX_ACTIVE_SELL_OFFERS", "DEFAULT_TRADE_XCH", "COIN_PREP_HEADROOM_PCT",
    "SPREAD_BPS", "MIN_EDGE_BPS", "FEE_POOL_ENABLED", "FEE_PREP_COUNT",
    "FEE_COIN_SIZE_XCH", "BUY_INNER_SIZE_XCH", "BUY_MID_SIZE_XCH",
    "BUY_OUTER_SIZE_XCH", "BUY_EXTREME_SIZE_XCH", "SELL_INNER_SIZE_XCH",
    "SELL_MID_SIZE_XCH", "SELL_OUTER_SIZE_XCH", "SELL_EXTREME_SIZE_XCH",
    "INNER_SIZE_XCH", "MID_SIZE_XCH", "OUTER_SIZE_XCH", "EXTREME_SIZE_XCH",
) + tuple(f"{side}_{tier}_TIER{suffix}_COUNT" for side in ("BUY", "SELL")
          for tier in ("INNER", "MID", "OUTER", "EXTREME") for suffix in ("", "_SPARE"))


def _configuration() -> dict:
    return {**{key: getattr(cfg, key, None) for key in _CONTEXT_KEYS},
            "network": os.environ.get("CATALYST_NETWORK_ID") or os.environ.get("CHIA_NETWORK") or "mainnet"}


def _hex(value) -> str:
    if type(value) is not str or re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", value) is None:
        raise ValueError("noncanonical coin identity")
    return value.removeprefix("0x").lower()


def _amount(value) -> int:
    if type(value) is str and re.fullmatch(r"[1-9][0-9]{0,18}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError("invalid atomic coin amount")
    return value


def _verified_identity(config: dict) -> dict:
    raw = wallet.get_wallet_identity()
    fp = config["SAGE_FINGERPRINT"]
    if (type(raw) is not dict or raw.get("success") is not True
            or raw.get("backend") != "sage" or config["WALLET_TYPE"] != "sage"
            or raw.get("has_secrets") is not True
            or type(raw.get("fingerprint")) is not int or not 1 <= raw["fingerprint"] <= 2**32 - 1
            or type(fp) is not str or not re.fullmatch(r"[1-9][0-9]{0,9}", fp)
            or int(fp) != raw["fingerprint"]
            or raw.get("network_id") != config["network"]
            or not re.fullmatch(r"mainnet|testnet[0-9]+", config["network"])
            or (config["WALLET_EXPECTED_NAME"] and config["WALLET_EXPECTED_NAME"] != raw.get("name"))
            or (config["WALLET_EXPECTED_KEY_KIND"] and config["WALLET_EXPECTED_KEY_KIND"] != raw.get("kind"))):
        raise ValueError("FEE_WALLET_IDENTITY_UNAVAILABLE")
    return {"network": raw["network_id"], "wallet_type": "sage", "wallet_fingerprint": raw["fingerprint"]}


def _succeeded(result) -> bool:
    # Native Sage read schemas need not include success=true; require the exact
    # expected collection independently, and never accept explicit errors.
    return (type(result) is dict and result.get("success", True) is True
            and not result.get("error") and not result.get("error_message")
            and result.get("status") not in ("error", "failed", "failure"))


def _selectable_inventory(asset_id: str | None, network: str) -> list[dict]:
    rows, seen = [], set()
    total, previous_id = None, ""
    for page in range(_MAX_COIN_PAGES):
        response = wallet.rpc("get_coins", {
            "asset_id": asset_id, "offset": page * _PAGE_SIZE, "limit": _PAGE_SIZE,
            "sort_mode": "coin_id", "filter_mode": "selectable", "ascending": True,
        }, timeout=15)
        if not _succeeded(response) or type(response.get("coins")) is not list:
            raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")
        values = response["coins"]
        reported = response.get("total")
        if (type(reported) is not int or not 0 <= reported <= _PAGE_SIZE * _MAX_COIN_PAGES
                or (total is not None and reported != total)):
            raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")
        total = reported
        if len(values) != min(_PAGE_SIZE, total - len(rows)):
            raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")
        try:
            for raw in values:
                amount = _amount(raw["amount"])
                coin_id = _hex(raw["coin_id"])
                # Sage v0.13 CoinRecord exposes the P2 address, not the raw coin
                # parent/outer puzzle. Executable inspection later proves those
                # fields; do not invent them or call this inventory effect proof.
                decode_wallet_puzzle_hash(raw["address"])
                prefix = "xch1" if network == "mainnet" else "txch1"
                if (coin_id in seen or coin_id <= previous_id or not raw["address"].startswith(prefix)
                        or raw["offer_id"] is not None or raw["spent_height"] is not None
                        or raw["spent_timestamp"] is not None
                        or raw.get("spent", False) is not False or raw.get("pending", False) is not False
                        or (raw.get("asset_id") is not None and _hex(raw["asset_id"]) != asset_id)):
                    raise ValueError("inconsistent selectable coin")
                seen.add(coin_id)
                previous_id = coin_id
                rows.append({"coin_id": coin_id, "amount_mojos": amount})
        except (KeyError, TypeError, ValueError):
            raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE") from None
        if len(rows) == total:
            return rows
    raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")


def read_fee_wallet_snapshot() -> dict:
    """Derive fresh trusted identity, exact asset and complete coin inventory."""
    config = _configuration()
    identity = _verified_identity(config)
    try:
        asset_id = _hex(config["CAT_ASSET_ID"])
        if (config["CAT_ASSET_ID"] != asset_id
                or type(config["CAT_WALLET_ID"]) is not int or config["CAT_WALLET_ID"] != 2
                or type(config["WALLET_ID_XCH"]) is not int or config["WALLET_ID_XCH"] != 1
                or type(config["CAT_DECIMALS"]) is not int or not 0 <= config["CAT_DECIMALS"] <= 18
                or type(config["CAT_TICKER_ID"]) is not str
                or re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", config["CAT_TICKER_ID"]) is None):
            raise ValueError("invalid configured asset scope")
        metadata = wallet.get_cat_metadata_snapshot()
        if not _succeeded(metadata) or type(metadata.get("cats")) is not list:
            raise ValueError("missing actual CAT metadata")
        matching = []
        for cat in metadata["cats"]:
            if type(cat) is not dict or "asset_id" not in cat:
                raise ValueError("malformed token metadata")
            # Sage's TokenRecord represents the native asset with null.
            if cat["asset_id"] is not None and _hex(cat["asset_id"]) == asset_id:
                matching.append(cat)
        if (len(matching) != 1 or type(matching[0].get("precision")) is not int
                or matching[0]["precision"] != config["CAT_DECIMALS"]):
            raise ValueError("actual CAT missing or ambiguous")
    except (KeyError, TypeError, ValueError):
        raise ValueError("FEE_WALLET_ASSET_UNAVAILABLE") from None
    observed = {asset: _selectable_inventory(aid, identity["network"])
                for asset, aid in (("xch", None), ("cat", asset_id))}
    address = wallet.get_next_address(config["WALLET_ID_XCH"], new_address=False)
    if not _succeeded(address) or type(address.get("address")) is not str:
        raise ValueError("FEE_WALLET_ADDRESS_UNAVAILABLE")
    try:
        decode_wallet_puzzle_hash(address["address"])
        prefix = "xch1" if identity["network"] == "mainnet" else "txch1"
        if not address["address"].startswith(prefix):
            raise ValueError("network address mismatch")
    except ValueError:
        raise ValueError("FEE_WALLET_ADDRESS_UNAVAILABLE") from None
    if config != _configuration():
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    try:
        after = _verified_identity(config)
    except ValueError:
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED") from None
    if after != identity:
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    ids = [row["coin_id"] for rows in observed.values() for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")
    reconciliation = set(database.get_coin_reconciliation_protected_ids(ids))
    coins = []
    for asset, rows in observed.items():
        reserves = {_hex(row["coin_id"]) for row in database.get_reserve_coins(asset)}
        for row in rows:
            protected = row["coin_id"] in reserves or row["coin_id"] in reconciliation
            coins.append(SelectableCoin(asset, row["coin_id"], row["amount_mojos"],
                                        "reserve" if protected else "", True, protected))
    return {"identity": {**identity, "wallet_id": config["CAT_WALLET_ID"],
                         "xch_wallet_id": config["WALLET_ID_XCH"], "asset_id": asset_id,
                         "ticker": config["CAT_TICKER_ID"]},
            "configuration": config, "receive_address": address["address"],
            "snapshot": CoinSnapshot(tuple(coins))}
