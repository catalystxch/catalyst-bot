"""Pre-dispatch cancellation failures must not exhaust the fee-coin pool."""

from types import SimpleNamespace

import pytest

import coin_prep_fee_cancellation
import database
from coin_manager import FeeCoinPool
from offer_manager import OfferManager


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
