"""A reviewed ceiling and a funded fee input are separate shutdown requirements."""

import time

import follow_shutdown_funding


def _quote(cost, target_seconds):
    now = int(time.time())
    return {
        "available": True,
        "source": "coinset",
        "cost": cost,
        "target_seconds": target_seconds,
        "fee_mojos": 4_100_000_000,
        "observed_at": now,
        "expires_at": now + 60,
        "network_evidence": {
            "full_node_synced": None,
            "mempool_size": None,
            "mempool_fees": None,
            "last_block_cost": None,
        },
    }


def test_fee_ceiling_does_not_substitute_for_one_spendable_fee_coin(monkeypatch):
    monkeypatch.setattr(follow_shutdown_funding, "quote_fee", _quote)
    result = follow_shutdown_funding.preview_one_block_shutdown_funding(
        maximum_fee_mojos=5_000_000_000,
        spent_fee_mojos=100_000_000,
        held_fee_mojos=0,
        largest_fee_coin_mojos=100_000_000,
        protected_shutdown_fee_mojos=4_500_000_000,
        target_seconds=300,
    )
    assert result["ready"] is False
    assert result["reason"] == "FOLLOW_SHUTDOWN_FEE_COIN_TOO_SMALL"
    assert result["quoted_fee_mojos"] == 4_100_000_000
    assert result["remaining_fee_mojos"] == 4_900_000_000
    assert result["dispatch_authorized"] is False


def test_one_block_funding_preview_requires_both_cap_and_coin(monkeypatch):
    monkeypatch.setattr(follow_shutdown_funding, "quote_fee", _quote)
    args = dict(
        spent_fee_mojos=100_000_000,
        held_fee_mojos=0,
        largest_fee_coin_mojos=4_200_000_000,
        protected_shutdown_fee_mojos=4_500_000_000,
        target_seconds=300,
    )
    assert (
        follow_shutdown_funding.preview_one_block_shutdown_funding(
            maximum_fee_mojos=5_000_000_000, **args
        )["ready"]
        is True
    )
    refused = follow_shutdown_funding.preview_one_block_shutdown_funding(
        maximum_fee_mojos=4_000_000_000, **args
    )
    assert refused["reason"] == "FOLLOW_SHUTDOWN_FEE_CAP_INSUFFICIENT"


def test_one_block_funding_needs_protected_shutdown_reserve(monkeypatch):
    monkeypatch.setattr(follow_shutdown_funding, "quote_fee", _quote)
    result = follow_shutdown_funding.preview_one_block_shutdown_funding(
        maximum_fee_mojos=5_000_000_000,
        spent_fee_mojos=100_000_000,
        held_fee_mojos=0,
        largest_fee_coin_mojos=4_200_000_000,
        protected_shutdown_fee_mojos=100_000_000,
        target_seconds=300,
    )
    assert result["ready"] is False
    assert result["reason"] == "FOLLOW_SHUTDOWN_RESERVE_INSUFFICIENT"


def test_stale_network_quote_cannot_fund_start_review(monkeypatch):
    def stale_quote(cost, target_seconds):
        return _quote(cost, target_seconds) | {
            "observed_at": int(time.time()) - 61,
            "expires_at": int(time.time()) - 1,
        }

    monkeypatch.setattr(follow_shutdown_funding, "quote_fee", stale_quote)
    result = follow_shutdown_funding.preview_one_block_shutdown_funding(
        maximum_fee_mojos=5_000_000_000,
        spent_fee_mojos=0,
        held_fee_mojos=0,
        largest_fee_coin_mojos=5_000_000_000,
        protected_shutdown_fee_mojos=5_000_000_000,
        target_seconds=300,
    )
    assert result["ready"] is False
    assert result["reason"] == "FOLLOW_SHUTDOWN_FEE_ESTIMATE_UNAVAILABLE"
