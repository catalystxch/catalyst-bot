"""Cancellation fee scope for a fenced refresh abort."""

import json
import pytest


def test_published_abort_quotes_its_exact_normal_lifecycle_offers(monkeypatch):
    import api_server  # noqa: F401 - initialize blueprint imports
    import database
    import wallet
    from coin_prep_fee_runtime import _outstanding_campaign_cancel_assets
    from mutation_gate import wallet_fingerprint_hash

    campaign_id = "a" * 64
    buy_id, sell_id = "b" * 64, "c" * 64
    asset_id = "d" * 64
    fingerprint = 736588221
    abort = {
        "campaign_id": campaign_id,
        "state": "parent_terminal",
        "latch_generation": 7,
        "target_trade_ids_json": json.dumps([buy_id, sell_id]),
        "asset_id": asset_id,
        "network": "mainnet",
        "wallet_fingerprint_hash": wallet_fingerprint_hash(fingerprint),
    }
    monkeypatch.setattr(
        database,
        "get_bootstrap_campaign",
        lambda _id: {
            "campaign_id": campaign_id,
            "status": "stopped",
            "asset_id": asset_id,
            "network": "mainnet",
            "wallet_fingerprint": fingerprint,
        },
    )
    monkeypatch.setattr(
        database, "list_incomplete_refresh_aborts", lambda **_kw: [abort]
    )
    monkeypatch.setattr(
        database,
        "get_runtime_safety_latch",
        lambda: {
            "generation": 7,
            "state": "tripped",
            "reason_code": "REFRESH_ABORT_CLEANUP",
        },
    )
    monkeypatch.setattr(
        wallet,
        "_read_refresh_abort_cleanup_snapshot",
        lambda: {
            "trade_ids": [buy_id, sell_id],
            "pending_transaction_ids": [],
        },
    )
    intents = {
        buy_id: {
            "sage_trade_id": buy_id,
            "purpose": "normal_lifecycle",
            "side": "buy",
            "asset_id": asset_id,
            "network": "mainnet",
            "wallet_fingerprint_hash": abort["wallet_fingerprint_hash"],
        },
        sell_id: {
            "sage_trade_id": sell_id,
            "purpose": "normal_lifecycle",
            "side": "sell",
            "asset_id": asset_id,
            "network": "mainnet",
            "wallet_fingerprint_hash": abort["wallet_fingerprint_hash"],
        },
    }
    monkeypatch.setattr(database, "get_offer_intent_by_trade_id", intents.get)
    monkeypatch.setattr("blueprints.bootstrap._campaign_trade_ids", lambda _id: [])

    assert _outstanding_campaign_cancel_assets(campaign_id) == {
        buy_id: "xch",
        sell_id: "cat",
    }

    # A campaign-prefixed offer outside the abort cannot displace its exact scope.
    foreign_id = "e" * 64
    intents[foreign_id] = {
        "sage_trade_id": foreign_id,
        "purpose": f"bootstrap:{campaign_id}:revision:0",
        "side": "buy",
    }
    monkeypatch.setattr(
        "blueprints.bootstrap._campaign_trade_ids", lambda _id: [foreign_id]
    )
    with pytest.raises(ValueError, match="FEE_CANCELLATION_SCOPE_INVALID"):
        _outstanding_campaign_cancel_assets(campaign_id)
    monkeypatch.setattr("blueprints.bootstrap._campaign_trade_ids", lambda _id: [])

    # The abort must not lend its stopped campaign fee scope to another offer.
    monkeypatch.setattr(
        wallet,
        "_read_refresh_abort_cleanup_snapshot",
        lambda: {
            "trade_ids": [buy_id, "e" * 64],
            "pending_transaction_ids": [],
        },
    )
    with pytest.raises(ValueError, match="FEE_CANCELLATION_SCOPE_INVALID"):
        _outstanding_campaign_cancel_assets(campaign_id)

    monkeypatch.setattr(database, "list_incomplete_refresh_aborts", lambda **_kw: [])
    assert _outstanding_campaign_cancel_assets(campaign_id) == {}
