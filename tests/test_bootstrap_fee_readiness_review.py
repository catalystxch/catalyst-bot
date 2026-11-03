"""Consumed cancellation consent must require review before new exposure."""

import pytest

import bootstrap_fee_authority
import coin_prep_fee_runtime
import database


@pytest.fixture
def readiness(monkeypatch):
    campaign = {"campaign_id": "a" * 64, "revision": 3, "fee_budget_xch": "0.01"}
    approval = {
        "total_fee_mojos": 649192931,
        "cancellation_reserve_mojos": 648649620,
        "remaining_fee_mojos": 647734892,
    }
    monkeypatch.setattr(
        database, "get_latest_coin_prep_fee_approval_for_campaign", lambda _: "b" * 64
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_approved_prep_fee_snapshot",
        lambda *_a, **_k: {
            "approval": approval,
            "campaign": campaign,
            "recovery_only": False,
        },
    )
    return campaign, approval


def test_consumed_consent_requires_explicit_review_with_exact_shortfall(readiness):
    campaign, _ = readiness
    result = bootstrap_fee_authority.cancellation_fee_readiness(campaign)
    assert result["ready"] is False
    assert result["action_required"] == "review_cancellation_fee_budget"
    assert result["remaining_fee_mojos"] == 647734892
    assert result["required_cancellation_reserve_mojos"] == 648649620
    assert result["shortfall_mojos"] == 914728


def test_two_cancels_do_not_refund_protection_for_two_replacements(readiness):
    campaign, approval = readiness
    approval.update(
        total_fee_mojos=600, cancellation_reserve_mojos=600, remaining_fee_mojos=400
    )
    assert (
        bootstrap_fee_authority.cancellation_fee_readiness(campaign)["ready"] is False
    )


def test_full_reserve_remains_ready(readiness):
    campaign, approval = readiness
    approval["remaining_fee_mojos"] = approval["cancellation_reserve_mojos"]
    assert bootstrap_fee_authority.cancellation_fee_readiness(campaign) == {
        "ready": True,
        "approval_id": "b" * 64,
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("total_fee_mojos", 10000000001),
        ("remaining_fee_mojos", 0),
        ("remaining_fee_mojos", -1),
        ("remaining_fee_mojos", True),
        ("cancellation_reserve_mojos", 0),
    ],
)
def test_invalid_or_exhausted_consent_remains_blocked(readiness, key, value):
    campaign, approval = readiness
    approval[key] = value
    assert (
        bootstrap_fee_authority.cancellation_fee_readiness(campaign)["ready"] is False
    )


def test_loop_blocks_before_intent_creation_and_logs_once_until_consent_changes(
    readiness, monkeypatch
):
    from types import SimpleNamespace

    import bot_loop
    import tx_fees
    import wallet

    campaign, approval = readiness
    events, creates = [], []
    loop = object.__new__(bot_loop.BotLoop)
    loop._publication_discovery_pending = 0
    loop._market_confidence_result = None
    loop.coin_manager = SimpleNamespace(is_busy=lambda: False)
    loop.offer_manager = SimpleNamespace(
        create_bootstrap_plan=lambda *a, **k: creates.append(True) or []
    )
    loop._bootstrap_campaign_context = lambda: {
        "active": True,
        "campaign": campaign,
        "identity": {},
    }
    loop._refresh_bootstrap_campaign_evidence = lambda **kwargs: {
        "changed": False,
        "campaign": campaign,
        "runtime": {
            "transition": {"cancel_required": False},
            "plan": {
                "authorized": True,
                "sides": {side: {"levels": [{}]} for side in ("buy", "sell")},
            },
        },
    }
    monkeypatch.setattr(
        wallet,
        "get_wallet_balance",
        lambda _: {
            "success": True,
            "wallet_balance": {"confirmed_wallet_balance": 1000000000000},
        },
    )
    monkeypatch.setattr(tx_fees, "get_effective_transaction_fee_mojos", lambda: 1)
    monkeypatch.setattr(database, "get_offer_intents_for_registry", lambda: [])
    monkeypatch.setattr(bot_loop, "bootstrap_side_enabled", lambda *a: True)
    monkeypatch.setattr(bot_loop, "log_event", lambda *a, **k: events.append((a, k)))
    for _ in range(2):
        assert loop._route_bootstrap_creation_if_active(
            current_buy_ids=set(), current_sell_ids=set()
        ) == {"buy": set(), "sell": set()}
    assert creates == []
    assert len(events) == 1
    assert events[0][0][1] == "bootstrap_cancellation_fee_review_required"
    assert events[0][1]["data"]["shortfall_mojos"] == 914728
    approval["remaining_fee_mojos"] = approval["cancellation_reserve_mojos"]
    loop._route_bootstrap_creation_if_active(
        current_buy_ids=set(), current_sell_ids=set()
    )
    assert creates == [True]
