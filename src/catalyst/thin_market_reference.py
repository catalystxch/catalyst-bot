"""Choose a provenance-bound price reference for user-enabled thin markets.

This is a pricing input, not wallet-effect or Follow run authority. Callers
must still validate the wallet, run, quote, offer and mutation at dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any


_MAX_ANCHOR_AGE = timedelta(hours=24)
_MAX_OBSERVATION_AGE = timedelta(seconds=30)
_UNSAFE_REASONS = frozenset(
    {
        "crossed_book",
        "provider_price_conflict",
        "provider_chain_conflict",
        "hard_price_move_cap",
        "material_move_pending_confirmation",
        "thin_move_pending_confirmation",
        "rapid_offer_churn",
    }
)
_KNOWN_SAFE_REASONS = frozenset(
    {
        "market_data_absent",
        "stale_provider_data",
        "one_sided_book",
        "insufficient_bid_depth",
        "insufficient_ask_depth",
        "single_provider_dependency",
        "out_of_range_depth_excluded",
        "movement_persistence_satisfied",
        "hard_move_reanchor_persistence_satisfied",
        "settled_trade_confirmed_move",
    }
)


@dataclass(frozen=True, slots=True)
class ThinMarketReference:
    midpoint: Decimal
    source: str
    observed_at: datetime
    observed_bid: Decimal | None
    observed_ask: Decimal | None
    evidence_digests: tuple[str, ...]


def _utc(value: Any) -> datetime | None:
    if type(value) is not datetime or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def _price(value: Any) -> Decimal | None:
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        return None
    return value


def _digests(value: Any) -> tuple[str, ...] | None:
    if type(value) is not tuple or not value:
        return None
    if any(
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for digest in value
    ):
        return None
    return value


def select_thin_market_reference(
    confidence: Any, *, now: datetime
) -> ThinMarketReference | None:
    """Use a current attributable two-sided book or a <=24h trusted anchor.

    A poor depth rating is allowed. Conflicting, manipulated or unconfirmed
    movement evidence is never converted into a usable reference.
    """
    current = _utc(now)
    derived = _utc(getattr(confidence, "derived_at", None))
    if current is None or derived is None:
        return None
    observation_age = current - derived
    if not -timedelta(seconds=2) <= observation_age <= _MAX_OBSERVATION_AGE:
        return None
    reasons = getattr(confidence, "reason_codes", ())
    if type(reasons) is not tuple or any(type(reason) is not str for reason in reasons):
        return None
    if _UNSAFE_REASONS.intersection(reasons) or set(reasons) - _KNOWN_SAFE_REASONS:
        return None
    if getattr(confidence, "manipulation_score", None) != 0:
        return None

    raw_bid = getattr(confidence, "observed_bid", None)
    raw_ask = getattr(confidence, "observed_ask", None)
    bid = _price(raw_bid)
    ask = _price(raw_ask)
    if (raw_bid is not None and bid is None) or (raw_ask is not None and ask is None):
        return None
    if bid is not None and ask is not None:
        digests = _digests(getattr(confidence, "observed_book_evidence_digests", None))
        if digests is None or bid > ask:
            return None
        return ThinMarketReference(
            midpoint=(bid + ask) / Decimal(2),
            source="current_book",
            observed_at=derived,
            observed_bid=bid,
            observed_ask=ask,
            evidence_digests=digests,
        )

    current_digests = _digests(
        getattr(confidence, "observed_book_evidence_digests", None)
    )
    if (bid is not None or ask is not None) and current_digests is None:
        return None
    trade_price = _price(getattr(confidence, "settled_trade_price", None))
    trade_digests = _digests(
        getattr(confidence, "settled_trade_evidence_digests", None)
    )
    if (
        (bid is not None or ask is not None)
        and trade_price is not None
        and trade_digests is not None
    ):
        if (bid is not None and bid >= trade_price) or (
            ask is not None and ask <= trade_price
        ):
            return None
        return ThinMarketReference(
            midpoint=trade_price,
            source="settled_trade",
            observed_at=derived,
            observed_bid=bid,
            observed_ask=ask,
            evidence_digests=tuple(sorted(set(current_digests + trade_digests))),
        )

    anchor = _price(getattr(confidence, "trusted_midpoint", None))
    anchor_at = _utc(getattr(confidence, "last_trusted_at", None))
    digests = _digests(getattr(confidence, "last_trusted_evidence_digests", None))
    source = "trusted_anchor"
    thin_anchor = _price(getattr(confidence, "thin_anchor_midpoint", None))
    thin_at = _utc(getattr(confidence, "thin_anchor_at", None))
    thin_digests = _digests(getattr(confidence, "thin_anchor_evidence_digests", None))
    if (
        thin_anchor is not None
        and thin_at is not None
        and thin_digests is not None
        and (anchor_at is None or thin_at > anchor_at)
    ):
        anchor, anchor_at, digests = thin_anchor, thin_at, thin_digests
        source = "thin_anchor"
    if anchor is None or anchor_at is None or digests is None:
        return None
    age = current - anchor_at
    if not -timedelta(seconds=2) <= age <= _MAX_ANCHOR_AGE:
        return None
    return ThinMarketReference(
        midpoint=anchor,
        source=source,
        observed_at=anchor_at,
        observed_bid=bid,
        observed_ask=ask,
        evidence_digests=tuple(sorted(set(digests + (current_digests or ())))),
    )
