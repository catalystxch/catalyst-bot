"""Reference-price selection when a user permits thin-market Follow quotes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from thin_market_reference import select_thin_market_reference


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64


def confidence(**changes):
    fields = {
        "derived_at": NOW,
        "observed_bid": Decimal("0.000070"),
        "observed_ask": Decimal("0.000090"),
        "trusted_midpoint": Decimal("0.000080"),
        "last_trusted_at": NOW - timedelta(hours=2),
        "last_trusted_evidence_digests": (DIGEST,),
        "evidence_digests": (DIGEST,),
        "observed_book_evidence_digests": (DIGEST,),
        "manipulation_score": 0,
        "reason_codes": ("insufficient_bid_depth", "insufficient_ask_depth"),
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_current_thin_two_sided_book_supplies_dynamic_midpoint():
    selected = select_thin_market_reference(confidence(), now=NOW)

    assert selected is not None
    assert selected.midpoint == Decimal("0.000080")
    assert selected.source == "current_book"
    assert selected.observed_bid == Decimal("0.000070")
    assert selected.observed_ask == Decimal("0.000090")


def test_one_sided_book_can_use_proven_trusted_anchor_for_24_hours():
    selected = select_thin_market_reference(
        confidence(observed_ask=None, reason_codes=("one_sided_book",)), now=NOW
    )

    assert selected is not None
    assert selected.midpoint == Decimal("0.000080")
    assert selected.source == "trusted_anchor"
    assert selected.observed_bid == Decimal("0.000070")
    assert selected.observed_ask is None


def test_anchor_older_than_24_hours_cannot_authorize_new_quotes():
    selected = select_thin_market_reference(
        confidence(
            observed_ask=None,
            last_trusted_at=NOW - timedelta(hours=24, seconds=1),
            reason_codes=("one_sided_book",),
        ),
        now=NOW,
    )

    assert selected is None


def test_legacy_anchor_without_age_or_provenance_is_unusable():
    selected = select_thin_market_reference(
        confidence(
            observed_ask=None,
            last_trusted_at=None,
            last_trusted_evidence_digests=(),
            reason_codes=("one_sided_book",),
        ),
        now=NOW,
    )

    assert selected is None


def test_conflicting_source_blocks_even_a_recent_anchor():
    selected = select_thin_market_reference(
        confidence(
            observed_ask=None,
            reason_codes=("one_sided_book", "provider_price_conflict"),
        ),
        now=NOW,
    )

    assert selected is None


def test_manipulation_blocks_thin_market_reference():
    selected = select_thin_market_reference(confidence(manipulation_score=1), now=NOW)

    assert selected is None


def test_unknown_or_invalid_provider_reason_blocks_thin_market_reference():
    for reason in ("future_unknown_reason", "invalid_provider_data"):
        assert (
            select_thin_market_reference(confidence(reason_codes=(reason,)), now=NOW)
            is None
        )


def test_hard_move_blocks_recent_anchor():
    selected = select_thin_market_reference(
        confidence(
            observed_ask=None,
            reason_codes=("one_sided_book", "hard_price_move_cap"),
        ),
        now=NOW,
    )

    assert selected is None


def test_current_book_needs_current_attributable_evidence():
    selected = select_thin_market_reference(
        confidence(last_trusted_at=None, observed_book_evidence_digests=()), now=NOW
    )

    assert selected is None


def test_stale_current_observation_cannot_refresh_old_anchor():
    selected = select_thin_market_reference(
        confidence(
            observed_ask=None,
            derived_at=NOW - timedelta(minutes=1),
            reason_codes=("one_sided_book",),
        ),
        now=NOW,
    )

    assert selected is None


def test_fresh_settled_trade_seeds_one_sided_book_without_prior_anchor():
    selected = select_thin_market_reference(
        confidence(
            observed_ask=None,
            trusted_midpoint=None,
            last_trusted_at=None,
            last_trusted_evidence_digests=(),
            reason_codes=("one_sided_book",),
            settled_trade_price=Decimal("0.000080"),
            settled_trade_evidence_digests=("c" * 64,),
        ),
        now=NOW,
    )
    assert selected is not None
    assert selected.source == "settled_trade"
    assert selected.midpoint == Decimal("0.000080")
    assert set(selected.evidence_digests) == {DIGEST, "c" * 64}


def test_settled_trade_conflicting_with_book_side_is_rejected():
    selected = select_thin_market_reference(
        confidence(
            observed_ask=None,
            trusted_midpoint=None,
            last_trusted_at=None,
            last_trusted_evidence_digests=(),
            reason_codes=("one_sided_book",),
            settled_trade_price=Decimal("0.000060"),
            settled_trade_evidence_digests=("c" * 64,),
        ),
        now=NOW,
    )
    assert selected is None
