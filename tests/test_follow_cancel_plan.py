"""Follow cancellation plans stay exact before any wallet or ledger effect."""

from types import SimpleNamespace

import database
import follow_fee_cancellation
import pytest
from coin_manager import FeeCoinPool
from offer_manager import OfferManager


TRADE = "a" * 64
SOURCE = "c" * 64
FEE_COIN = "e" * 64
RUN = "f" * 64


def test_follow_cancel_plan_prices_exact_source_and_releases_on_refusal(monkeypatch):
    pool = FeeCoinPool()
    pool.refresh([{"coin_id": FEE_COIN, "coin": {"amount": 1_000_000}}])
    manager = OfferManager()
    manager._fee_pool = pool
    intent = SimpleNamespace(trade_id=TRADE, intent_id="1" * 64)
    monkeypatch.setattr(database, "get_offer", lambda _trade: {"coin_id": SOURCE})
    monkeypatch.setattr(
        database,
        "get_offer_intent_by_trade_id",
        lambda _trade: {
            "intent_id": intent.intent_id,
            "sage_trade_id": TRADE,
            "purpose": f"follow:{RUN}:normal_lifecycle",
            "lifecycle_state": "visible",
            "selected_coin_ids_json": '["' + SOURCE + '"]',
        },
    )
    seen = []

    def price(**request):
        seen.append(request)
        return {"available": False, "reason": "FEE_ESTIMATE_UNAVAILABLE"}

    monkeypatch.setattr(follow_fee_cancellation, "price_follow_cancellation", price)
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        manager._plan_follow_cancel(
            [(intent, 1, "member")], RUN, {"network": "mainnet"}
        )
    assert seen[0]["trade_ids"] == [TRADE]
    assert seen[0]["source_coin_ids"] == [SOURCE]
    assert seen[0]["fee_coin_id"] == FEE_COIN
    assert seen[0]["run_id"] == RUN
    assert pool.reserved_count == 0


def test_follow_cancel_plan_keeps_exact_singleton_fee_input(monkeypatch):
    pool = FeeCoinPool()
    pool.refresh([{"coin_id": FEE_COIN, "coin": {"amount": 1_000_000}}])
    manager = OfferManager()
    manager._fee_pool = pool
    intent = SimpleNamespace(trade_id=TRADE, intent_id="1" * 64)
    monkeypatch.setattr(database, "get_offer", lambda _trade: {"coin_id": SOURCE})
    monkeypatch.setattr(
        database,
        "get_offer_intent_by_trade_id",
        lambda _trade: {
            "intent_id": intent.intent_id,
            "sage_trade_id": TRADE,
            "purpose": f"follow:{RUN}:normal_lifecycle",
            "lifecycle_state": "visible",
            "selected_coin_ids_json": '["' + SOURCE + '"]',
        },
    )
    monkeypatch.setattr(
        follow_fee_cancellation,
        "price_follow_cancellation",
        lambda **request: {
            "available": True,
            "trade_ids": request["trade_ids"],
            "source_coin_ids": request["source_coin_ids"],
            "fee_coin_id": request["fee_coin_id"],
            "fee_mojos": 20,
        },
    )
    contract, priced, reservation = manager._plan_follow_cancel(
        [(intent, 1, "member")], RUN, {"network": "mainnet"}
    )
    assert contract == {
        "protocol": "sage_native_cancel_offers_zero_plus_fee_v1",
        "trade_ids": [TRADE],
        "source_coin_ids": [SOURCE],
        "fee_coin_id": FEE_COIN,
        "fee_mojos": 20,
    }
    assert priced["fee_mojos"] == 20
    assert pool.reserved_count == 1
    assert reservation[0].release_ticket(reservation[1], reservation[2]) is True
    assert pool.reserved_count == 0


def test_follow_cancel_plan_refuses_coin_substitution(monkeypatch):
    pool = FeeCoinPool()
    pool.refresh([{"coin_id": FEE_COIN, "coin": {"amount": 1_000_000}}])
    manager = OfferManager()
    manager._fee_pool = pool
    intent = SimpleNamespace(trade_id=TRADE, intent_id="1" * 64)
    monkeypatch.setattr(database, "get_offer", lambda _trade: {"coin_id": "d" * 64})
    monkeypatch.setattr(
        database,
        "get_offer_intent_by_trade_id",
        lambda _trade: {
            "intent_id": intent.intent_id,
            "sage_trade_id": TRADE,
            "purpose": f"follow:{RUN}:normal_lifecycle",
            "lifecycle_state": "visible",
            "selected_coin_ids_json": '["' + SOURCE + '"]',
        },
    )
    with pytest.raises(ValueError, match="FEE_CANCELLATION_PLAN_INVALID"):
        manager._plan_follow_cancel(
            [(intent, 1, "member")], RUN, {"network": "mainnet"}
        )
    assert pool.reserved_count == 0


def test_follow_cancel_plan_refuses_other_run_before_fee_input(monkeypatch):
    pool = FeeCoinPool()
    pool.refresh([{"coin_id": FEE_COIN, "coin": {"amount": 1_000_000}}])
    manager = OfferManager()
    manager._fee_pool = pool
    intent = SimpleNamespace(trade_id=TRADE, intent_id="1" * 64)
    monkeypatch.setattr(database, "get_offer", lambda _trade: {"coin_id": SOURCE})
    monkeypatch.setattr(
        database,
        "get_offer_intent_by_trade_id",
        lambda _trade: {
            "intent_id": intent.intent_id,
            "sage_trade_id": TRADE,
            "purpose": f"follow:{'d' * 64}:normal_lifecycle",
            "lifecycle_state": "visible",
            "selected_coin_ids_json": '["' + SOURCE + '"]',
        },
    )
    with pytest.raises(ValueError, match="FEE_CANCELLATION_PLAN_INVALID"):
        manager._plan_follow_cancel(
            [(intent, 1, "member")], RUN, {"network": "mainnet"}
        )
    assert pool.reserved_count == 0
