"""Follow cancellation plans stay exact before any wallet or ledger effect."""

from types import SimpleNamespace
from importlib import import_module
import time

import database
import follow_fee_cancellation
import pytest
from coin_manager import FeeCoinPool
from offer_manager import OfferManager


TRADE = "a" * 64
SOURCE = "c" * 64
FEE_COIN = "e" * 64
RUN = "f" * 64


@pytest.fixture(autouse=True)
def current_database_module():
    global database, OfferManager
    database = import_module("database")
    OfferManager = import_module("offer_manager").OfferManager


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


@pytest.mark.parametrize(
    ("remaining_fee", "fee_coin_count", "expected_reason"),
    [
        (100, 4, None),
        (70, 4, "FEE_BUDGET_EXCEEDED"),
        (100, 2, "FEE_PREP_FUNDING_INSUFFICIENT"),
    ],
)
def test_follow_full_book_preflight_prices_all_cohorts_before_effect(
    monkeypatch, remaining_fee, fee_coin_count, expected_reason
):
    pool = FeeCoinPool()
    pool.refresh(
        [
            {"coin_id": f"{index + 100:064x}", "coin": {"amount": 1_000_000}}
            for index in range(fee_coin_count)
        ]
    )
    manager = OfferManager()
    manager._fee_pool = pool
    trade_ids = [f"{index:064x}" for index in range(1, 49)]
    identity = {"network": "mainnet"}
    monkeypatch.setattr(
        manager,
        "_canonical_cancel_intent",
        lambda trade_id: SimpleNamespace(trade_id=trade_id, intent_id=trade_id),
    )
    monkeypatch.setattr(
        database,
        "get_effective_follow_fee_policy",
        lambda **_kwargs: {
            "ready": True,
            "remaining_fee_mojos": remaining_fee,
            "revision": 0,
            "approval_id": "d" * 64,
        },
    )
    monkeypatch.setattr(database, "get_unresolved_offer_operation_blockers", lambda: [])
    monkeypatch.setattr(
        manager,
        "cancel_offers",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("preflight must not dispatch")
        ),
    )
    planned_fee_coins = []

    def price(members, _run_id, _identity, _action):
        if len(members) > 12:
            raise ValueError("FEE_CANCELLATION_BATCH_OVER_BLOCK_LIMIT")
        reserved = pool.reserve_largest_with_ticket()
        if reserved is None:
            raise ValueError("FEE_PREP_FUNDING_INSUFFICIENT")
        fee_coin_id, _amount, ticket = reserved
        planned_fee_coins.append(fee_coin_id)
        cohort = [member[0].trade_id for member in members]
        return (
            {
                "trade_ids": cohort,
                "source_coin_ids": cohort,
                "fee_coin_id": fee_coin_id,
            },
            {"fee_mojos": 20, "quote": {"expires_at": int(time.time()) + 60}},
            (pool, fee_coin_id, ticket),
        )

    monkeypatch.setattr(manager, "_plan_follow_cancel", price)
    if expected_reason is not None:
        with pytest.raises(ValueError, match=expected_reason):
            manager.preview_follow_cancel_book(
                [trade_ids], run_id=RUN, identity=identity, recovery_action="cancel_all"
            )
    else:
        preview = manager.preview_follow_cancel_book(
            [trade_ids], run_id=RUN, identity=identity, recovery_action="cancel_all"
        )
        assert preview["cohorts"] == [
            trade_ids[index : index + 12] for index in range(0, 48, 12)
        ]
        assert preview["total_fee_mojos"] == 80
        assert preview["dispatch_authorized"] is False
        assert len(set(planned_fee_coins)) == 4
    assert pool.reserved_count == 0


def test_follow_full_book_preflight_rejects_fee_coin_used_by_later_offer(
    monkeypatch,
):
    manager = OfferManager()
    trade_ids = ["1" * 64, "2" * 64]
    releases = []
    pool = SimpleNamespace(
        release_ticket=lambda coin_id, ticket: (
            releases.append((coin_id, ticket)) or True
        )
    )
    monkeypatch.setattr(
        manager,
        "_canonical_cancel_intent",
        lambda trade_id: SimpleNamespace(trade_id=trade_id, intent_id=trade_id),
    )
    monkeypatch.setattr(
        database,
        "get_effective_follow_fee_policy",
        lambda **_kwargs: {"ready": True, "remaining_fee_mojos": 100},
    )

    def price(members, _run_id, _identity, _action):
        trade_id = members[0][0].trade_id
        fee_coin_id = trade_ids[1] if trade_id == trade_ids[0] else "3" * 64
        return (
            {
                "trade_ids": [trade_id],
                "source_coin_ids": [trade_id],
                "fee_coin_id": fee_coin_id,
            },
            {"fee_mojos": 20, "quote": {"expires_at": int(time.time()) + 60}},
            (pool, fee_coin_id, len(releases) + 1),
        )

    monkeypatch.setattr(manager, "_plan_follow_cancel", price)
    with pytest.raises(ValueError, match="FEE_CANCELLATION_PLAN_INVALID"):
        manager.preview_follow_cancel_book(
            [[trade_ids[0]], [trade_ids[1]]],
            run_id=RUN,
            identity={"network": "mainnet"},
            recovery_action="cancel_all",
        )
    assert len(releases) == 2


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
