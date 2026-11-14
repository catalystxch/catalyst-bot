from decimal import Decimal

import bot_loop
from config import cfg


def test_follow_offer_targets_clamp_to_durable_funded_ceiling(monkeypatch):
    from follow_run_coordinator import FollowRunCoordinator

    monkeypatch.setattr(
        FollowRunCoordinator,
        "get_state",
        lambda self: {
            "run_id": "a" * 64,
            "funded_buy_limit": 4,
            "funded_sell_limit": 2,
        },
    )
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._reviewed_follow_run_id = "a" * 64
    loop.risk_manager = type(
        "Risk", (), {"should_enable_side": lambda self, _side, _price: True}
    )()
    monkeypatch.setattr(cfg, "ENABLE_BUY", True)
    monkeypatch.setattr(cfg, "ENABLE_SELL", True)
    monkeypatch.setattr(cfg, "MAX_ACTIVE_BUY_OFFERS", 100)
    monkeypatch.setattr(cfg, "MAX_ACTIVE_SELL_OFFERS", 100)

    assert loop._get_expected_offer_targets(Decimal("1")) == {
        "buy": 4,
        "sell": 2,
    }


def test_follow_offer_targets_fail_closed_when_funded_proof_is_missing(monkeypatch):
    from follow_run_coordinator import FollowRunCoordinator

    monkeypatch.setattr(
        FollowRunCoordinator,
        "get_state",
        lambda self: {"run_id": "a" * 64},
    )
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._reviewed_follow_run_id = "a" * 64
    loop.risk_manager = type(
        "Risk", (), {"should_enable_side": lambda self, _side, _price: True}
    )()
    monkeypatch.setattr(cfg, "ENABLE_BUY", True)
    monkeypatch.setattr(cfg, "ENABLE_SELL", True)
    monkeypatch.setattr(cfg, "MAX_ACTIVE_BUY_OFFERS", 100)
    monkeypatch.setattr(cfg, "MAX_ACTIVE_SELL_OFFERS", 100)

    assert loop._get_expected_offer_targets(Decimal("1")) == {
        "buy": 0,
        "sell": 0,
    }
