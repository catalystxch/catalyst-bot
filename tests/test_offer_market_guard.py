from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import inspect

import database
import offer_manager
import pytest
from offer_manager import assess_offer_book_candidate, book_opportunity_size_cap


ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 22, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "competition.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def _confidence(**overrides):
    values = {
        "state": "GREEN",
        "trusted_midpoint": Decimal("0.101"),
        "trusted_bid": Decimal("0.099"),
        "trusted_ask": Decimal("0.103"),
        "evidence_digests": (DIGEST_A, DIGEST_B),
        "derived_at": NOW,
        "independent_bid_depth_mojos": 10_000_000_000_000,
        "independent_ask_depth_mojos": 10_000_000_000_000,
        "required_depth_mojos": 2_000_000_000_000,
        "manipulation_score": 0,
        "derived_thresholds": {"manipulation_amber": 50},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_candidate_profit_floor_uses_directional_exact_final_edge():
    accepted = assess_offer_book_candidate(
        side="buy",
        candidate_price=Decimal("0.1"),
        size_xch=Decimal("1"),
        confidence=_confidence(),
        network_fee_xch=Decimal("0.003"),
        expected_cancel_requotes=2,
        minimum_profit_xch=Decimal("0.001"),
        now=NOW,
    )
    wrong_side = assess_offer_book_candidate(
        side="sell",
        candidate_price=Decimal("0.1"),
        size_xch=Decimal("1"),
        confidence=_confidence(),
        network_fee_xch=Decimal("0.003"),
        expected_cancel_requotes=2,
        minimum_profit_xch=Decimal("0.001"),
        now=NOW,
    )

    assert accepted["eligible"] is True
    assert accepted["expected_gross_xch"] == Decimal("0.010")
    assert accepted["required_xch"] == Decimal("0.010")
    assert wrong_side["eligible"] is False
    assert wrong_side["reason_code"] == "candidate_outside_profitable_side"


def test_candidate_requires_green_exact_snapshot_evidence():
    for confidence in (
        _confidence(state="AMBER"),
        _confidence(evidence_digests=()),
        _confidence(trusted_bid=None),
        _confidence(derived_at=NOW - timedelta(seconds=21)),
    ):
        result = assess_offer_book_candidate(
            side="buy",
            candidate_price=Decimal("0.1"),
            size_xch=Decimal("1"),
            confidence=confidence,
            network_fee_xch=Decimal("0"),
            expected_cancel_requotes=0,
            minimum_profit_xch=Decimal("0"),
            now=NOW,
        )
        assert result["eligible"] is False


def test_profitable_candidate_only_competes_when_it_improves_trusted_book():
    result = assess_offer_book_candidate(
        side="buy",
        candidate_price=Decimal("0.095"),
        size_xch=Decimal("1"),
        confidence=_confidence(),
        network_fee_xch=Decimal("0"),
        expected_cancel_requotes=0,
        minimum_profit_xch=Decimal("0"),
        now=NOW,
    )

    assert result["eligible"] is True
    assert result["improves_book"] is False


def test_book_opportunity_size_is_exactly_bounded_by_size_and_confirmed_depth():
    confidence = _confidence(
        independent_bid_depth_mojos=10_000_000_000_000,
        independent_ask_depth_mojos=20_000_000_000_000,
    )

    assert book_opportunity_size_cap(
        requested_size_xch=Decimal("1"), confidence=confidence
    ) == Decimal("0.20")
    assert (
        book_opportunity_size_cap(
            requested_size_xch=Decimal("1"),
            confidence=_confidence(manipulation_score=50),
        )
        is None
    )


def test_ladder_labels_book_improvements_as_bounded_opportunities():
    source = inspect.getsource(offer_manager.OfferManager.create_ladder)

    assert 'purpose = "book_opportunity"' in source
    assert '"purpose": spec["purpose"]' in source
    assert "book_opportunity_size_cap(" in source


def test_competition_claim_is_durable_per_asset_side_and_not_digest_bypassable(
    isolated_db,
):
    assert database.claim_offer_book_improvement(
        asset_id=ASSET_ID,
        side="buy",
        evidence_digest=DIGEST_A,
        cooldown_seconds=30,
        now=NOW,
    )
    database.close_connection()  # simulate process restart
    assert not database.claim_offer_book_improvement(
        asset_id=ASSET_ID,
        side="buy",
        evidence_digest=DIGEST_B,
        cooldown_seconds=30,
        now=NOW + timedelta(seconds=29),
    )
    assert database.claim_offer_book_improvement(
        asset_id=ASSET_ID,
        side="sell",
        evidence_digest=DIGEST_B,
        cooldown_seconds=30,
        now=NOW + timedelta(seconds=10),
    )
    assert database.claim_offer_book_improvement(
        asset_id=ASSET_ID,
        side="buy",
        evidence_digest=DIGEST_B,
        cooldown_seconds=30,
        now=NOW + timedelta(seconds=30),
    )


def test_unprofitable_ladder_is_rejected_before_coin_inventory_rpc():
    manager = offer_manager.OfferManager()
    with (
        patch.object(
            offer_manager.cfg, "MINIMUM_PROFIT_XCH", Decimal("0.01"), create=True
        ),
        patch.object(offer_manager.cfg, "EXPECTED_CANCEL_REQUOTES", 2, create=True),
        patch.object(
            offer_manager, "get_effective_transaction_fee_mojos", return_value=1
        ),
        patch.object(
            offer_manager,
            "get_exact_spendable_coins_rpc",
            side_effect=AssertionError("unprofitable offer reached coin selection"),
        ),
    ):
        created = manager.create_ladder(
            mid_price=Decimal("0.101"),
            side="buy",
            num_offers=1,
            trade_size_xch=Decimal("0.01"),
            coin_ids_enabled=True,
            market_confidence=_confidence(derived_at=datetime.now(timezone.utc)),
        )

    assert created == []


def test_all_production_ladder_paths_forward_current_confidence():
    import bot_loop

    cycle = inspect.getsource(bot_loop.BotLoop._run_one_cycle)
    requote = inspect.getsource(bot_loop.BotLoop._handle_requoting)
    create = inspect.getsource(bot_loop.BotLoop._create_offers_if_needed)
    manager_requote = inspect.getsource(offer_manager.OfferManager.requote_side)

    assert "market_confidence=self._market_confidence_result" in cycle
    assert "market_confidence=self._market_confidence_result" in requote
    assert "market_confidence=self._market_confidence_result" in create
    assert manager_requote.count("market_confidence=market_confidence") == 2
