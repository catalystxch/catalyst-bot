"""Pre-dispatch cancellation failures must not exhaust the fee-coin pool."""

from types import SimpleNamespace

import pytest
from flask import Flask

import coin_prep_fee_cancellation
import database
import offer_manager
from blueprints import bootstrap
from coin_manager import FeeCoinPool
from offer_manager import OfferManager


def test_stopped_campaign_cancel_hydrates_cold_fee_pool_before_planning():
    """A stopped bot has no trading cycle to populate its fee reserves."""
    fee_coin_id = "e" * 64
    trade_id = "a" * 64
    pool = FeeCoinPool()
    assert pool.reserve_largest_with_ticket() is None

    class Coins:
        def refresh_fee_pool_from_wallet(self):
            pool.refresh([{"coin_id": fee_coin_id, "coin": {"amount": 1_000_000_000}}])

    class Manager:
        def cancel_offers(self, trade_ids, **_options):
            assert trade_ids == [trade_id]
            reserved = pool.reserve_largest_with_ticket()
            assert reserved is not None, "campaign cancellation used an empty fee pool"
            assert reserved[0].removeprefix("0x") == fee_coin_id
            assert reserved[1] == 1_000_000_000
            pool.release_ticket(reserved[0], reserved[2])
            return {trade_id: {"outcome": "CANCEL_CONFIRMED"}}

    app = Flask(__name__)
    app.config["_CATALYST_API_SERVER_MODULE"] = SimpleNamespace(
        bot=SimpleNamespace(coin_manager=Coins(), offer_manager=Manager())
    )
    with app.app_context():
        assert bootstrap._cancel_campaign_offers([trade_id]) == {
            trade_id: {"outcome": "CANCEL_CONFIRMED"}
        }


def test_failed_cancel_pricing_releases_unspent_fee_coin(monkeypatch):
    fee_coin_id = "e" * 64
    source_coin_id = "c" * 64
    trade_id = "a" * 64
    pool = FeeCoinPool()
    pool.refresh([{"coin_id": fee_coin_id, "coin": {"amount": 1_000_000_000}}])
    manager = OfferManager()
    manager._fee_pool = pool
    monkeypatch.setattr(
        database, "get_offer", lambda _trade_id: {"coin_id": source_coin_id}
    )
    monkeypatch.setattr(
        database, "get_offer_intent_by_trade_id", lambda _trade_id: None
    )

    def wallet_unavailable(**_kwargs):
        raise ValueError("FEE_WALLET_IDENTITY_UNAVAILABLE")

    monkeypatch.setattr(
        coin_prep_fee_cancellation, "price_approved_cancellation", wallet_unavailable
    )
    members = [(SimpleNamespace(trade_id=trade_id), 1, "member")]

    for _ in range(2):
        with pytest.raises(ValueError, match="FEE_WALLET_IDENTITY_UNAVAILABLE"):
            manager._plan_coin_prep_cancel(members, "f" * 64)
        assert pool.available_count == 1


def test_stale_release_cannot_free_a_new_fee_coin_reservation():
    pool = FeeCoinPool()
    coin = {"coin_id": "e" * 64, "coin": {"amount": 1_000_000_000}}
    pool.refresh([coin])
    first = pool.reserve_largest_with_ticket()
    pool.refresh([coin])
    second = pool.reserve_largest_with_ticket()

    assert first[:2] == second[:2]
    assert first[2] != second[2]
    assert pool.release_ticket(first[0], first[2]) is False
    assert pool.available_count == 0


def test_approved_stopped_cancel_can_reserve_exact_selectable_topup_coin(monkeypatch):
    """A live offer need not wait a day when the prepared fee tier is empty."""
    coin_id = "d" * 64
    pool = FeeCoinPool()
    manager = OfferManager()
    manager._fee_pool = pool
    monkeypatch.setattr(
        database,
        "get_free_coins",
        lambda _wallet: [
            {
                "coin_id": coin_id,
                "purpose": "top_up",
                "designation": "unknown",
                "amount_mojos": 11_000_000_000,
            }
        ],
    )
    monkeypatch.setattr(
        offer_manager,
        "get_exact_spendable_coins_rpc",
        lambda _wallet: {
            "success": True,
            "confirmed_records": [
                {"coin_id": coin_id, "coin": {"amount": 11_000_000_000}}
            ],
        },
    )
    reserved = manager._reserve_protected_cancel_fee_source("cancel_all")
    assert reserved is not None
    assert reserved[1] == coin_id
    assert reserved[0] is pool
    assert pool.available_count == 0
    assert pool.release_ticket(reserved[1], reserved[2]) is True
    assert pool.total_count == 0


def test_topup_fee_fallback_requires_approved_recovery_and_exact_wallet_coin(
    monkeypatch,
):
    coin_id = "d" * 64
    pool = FeeCoinPool()
    manager = OfferManager()
    manager._fee_pool = pool
    monkeypatch.setattr(
        database,
        "get_free_coins",
        lambda _wallet: [
            {
                "coin_id": coin_id,
                "purpose": "top_up",
                "designation": "unknown",
                "amount_mojos": 11_000_000_000,
            }
        ],
    )
    monkeypatch.setattr(
        offer_manager,
        "get_exact_spendable_coins_rpc",
        lambda _wallet: {"success": True, "coins": []},
    )
    assert manager._reserve_protected_cancel_fee_source(None) is None
    assert manager._reserve_protected_cancel_fee_source("cancel_all") is None
    assert pool.total_count == 0


def test_approved_cancel_prices_exact_topup_source_and_releases_failed_quote(
    monkeypatch,
):
    coin_id = "d" * 64
    source_coin_id = "c" * 64
    trade_id = "a" * 64
    pool = FeeCoinPool()
    manager = OfferManager()
    manager._fee_pool = pool
    monkeypatch.setattr(
        database,
        "get_free_coins",
        lambda _wallet: [
            {
                "coin_id": coin_id,
                "purpose": "top_up",
                "designation": "unknown",
                "amount_mojos": 11_000_000_000,
            }
        ],
    )
    monkeypatch.setattr(
        offer_manager,
        "get_exact_spendable_coins_rpc",
        lambda _wallet: {
            "success": True,
            "confirmed_records": [
                {"coin_id": coin_id, "coin": {"amount": 11_000_000_000}}
            ],
        },
    )
    monkeypatch.setattr(
        database, "get_offer", lambda _trade_id: {"coin_id": source_coin_id}
    )
    monkeypatch.setattr(
        database, "get_offer_intent_by_trade_id", lambda _trade_id: None
    )
    seen = []

    def price(**kwargs):
        seen.append(kwargs)
        return {"available": False, "reason": "FEE_UNSIGNED_COST_UNAVAILABLE"}

    monkeypatch.setattr(
        coin_prep_fee_cancellation, "price_approved_cancellation", price
    )
    members = [(SimpleNamespace(trade_id=trade_id), 1, "member")]
    with pytest.raises(ValueError, match="FEE_UNSIGNED_COST_UNAVAILABLE"):
        manager._plan_coin_prep_cancel(members, "f" * 64, "cancel_all")
    assert seen[0]["fee_coin_id"] == coin_id
    assert seen[0]["trade_ids"] == [trade_id]
    assert pool.reserved_count == 0
    assert pool.total_count == 0


def test_approved_cancel_seals_topup_input_without_normal_pool_leak(monkeypatch):
    coin_id, trade_id, source_coin_id = "d" * 64, "a" * 64, "c" * 64
    pool = FeeCoinPool()
    manager = OfferManager()
    manager._fee_pool = pool
    monkeypatch.setattr(
        database,
        "get_free_coins",
        lambda _wallet: [
            {
                "coin_id": coin_id,
                "purpose": "top_up",
                "designation": "unknown",
                "amount_mojos": 11_000_000_000,
            }
        ],
    )
    monkeypatch.setattr(
        offer_manager,
        "get_exact_spendable_coins_rpc",
        lambda _wallet: {
            "success": True,
            "confirmed_records": [
                {"coin_id": coin_id, "coin": {"amount": 11_000_000_000}}
            ],
        },
    )
    monkeypatch.setattr(
        database, "get_offer", lambda _trade_id: {"coin_id": source_coin_id}
    )
    monkeypatch.setattr(
        database, "get_offer_intent_by_trade_id", lambda _trade_id: None
    )
    monkeypatch.setattr(
        coin_prep_fee_cancellation,
        "price_approved_cancellation",
        lambda **_kwargs: {
            "available": True,
            "trade_ids": [trade_id],
            "source_coin_ids": [source_coin_id],
            "fee_coin_id": coin_id,
            "fee_mojos": 20_000,
        },
    )
    contract, _priced, reservation = manager._plan_coin_prep_cancel(
        [(SimpleNamespace(trade_id=trade_id), 1, "member")], "f" * 64, "cancel_all"
    )
    assert contract["fee_coin_id"] == coin_id
    assert contract["fee_mojos"] == 20_000
    assert pool.total_count == 0
    assert pool.reserved_count == 1
    assert reservation[0].release_ticket(reservation[1], reservation[2]) is True
