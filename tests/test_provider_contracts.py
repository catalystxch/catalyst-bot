from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from providers.models import (
    BookObservation,
    Capability,
    MarketQuote,
    ObservationQuality,
    ProviderCapabilities,
    ProviderObservation,
    canonical_evidence_json,
    evidence_digest,
)
from providers.registry import ProviderRegistry


ASSET_ID = "ab" * 32
QUOTE_ID = "xch"
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _observation(provider_id: str = "dexie") -> ProviderObservation:
    raw = canonical_evidence_json({"offers": 2, "price": Decimal("0.125")})
    return ProviderObservation(
        provider_id=provider_id,
        capability=Capability.ORDER_BOOK,
        observed_at=NOW,
        source_time=NOW - timedelta(seconds=1),
        source_height=None,
        fresh_until=NOW + timedelta(seconds=20),
        identity_keys=(ASSET_ID, "offer-1"),
        payload_sha256=evidence_digest(raw),
        quality=ObservationQuality.VALID,
        reason_codes=(),
        raw_evidence_json=raw,
    )


def test_capabilities_are_immutable_and_normalized():
    capabilities = ProviderCapabilities(
        provider_id="DEXIE",
        capabilities=frozenset({Capability.ORDER_BOOK, Capability.DISCOVER_OFFER}),
    )

    assert capabilities.provider_id == "dexie"
    assert capabilities.supports(Capability.ORDER_BOOK)
    with pytest.raises(AttributeError):
        capabilities.provider_id = "other"


@pytest.mark.parametrize("provider_id", ["", "../dexie", "dexie splash", "DÉXIE"])
def test_capabilities_reject_invalid_provider_ids(provider_id):
    with pytest.raises(ValueError):
        ProviderCapabilities(
            provider_id=provider_id,
            capabilities=frozenset({Capability.ORDER_BOOK}),
        )


def test_provider_observation_is_immutable_and_serializable():
    observation = _observation()

    assert observation.to_dict() == {
        "provider_id": "dexie",
        "capability": "order_book",
        "observed_at": "2026-09-10T12:00:00.000000Z",
        "source_time": "2026-09-10T11:59:59.000000Z",
        "source_height": None,
        "fresh_until": "2026-09-10T12:00:20.000000Z",
        "identity_keys": [ASSET_ID, "offer-1"],
        "payload_sha256": evidence_digest(observation.raw_evidence_json),
        "quality": "valid",
        "reason_codes": [],
        "raw_evidence": {"offers": 2, "price": "0.125"},
    }
    with pytest.raises(AttributeError):
        observation.quality = ObservationQuality.INVALID


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_at", datetime(2026, 9, 10, 12, 0)),
        ("source_time", datetime(2026, 9, 10, 12, 1, tzinfo=timezone.utc)),
        ("source_height", -1),
        ("fresh_until", NOW - timedelta(seconds=2)),
        ("identity_keys", ()),
        ("payload_sha256", "bad"),
        ("raw_evidence_json", "not-json"),
    ],
)
def test_provider_observation_rejects_invalid_authority_fields(field, value):
    values = _observation().constructor_values()
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        ProviderObservation(**values)


def test_provider_observation_rejects_digest_mismatch_and_oversized_evidence():
    values = _observation().constructor_values()
    values["raw_evidence_json"] = canonical_evidence_json({"different": True})
    with pytest.raises(ValueError, match="digest"):
        ProviderObservation(**values)

    with pytest.raises(ValueError, match="4096"):
        canonical_evidence_json({"payload": "x" * 5000})


def test_canonical_evidence_redacts_secret_fields_and_is_deterministic():
    first = canonical_evidence_json(
        {"z": Decimal("1.20"), "api_key": "secret", "nested": {"token": "secret"}}
    )
    second = canonical_evidence_json(
        {"nested": {"token": "different"}, "api_key": "different", "z": "1.20"}
    )

    assert first == second
    assert json.loads(first) == {
        "api_key": "[redacted]",
        "nested": {"token": "[redacted]"},
        "z": "1.20",
    }


def test_market_quote_requires_exact_decimal_positive_ordered_prices():
    quote = MarketQuote(
        base_asset_id=ASSET_ID,
        quote_asset_id=QUOTE_ID,
        bid=Decimal("0.10"),
        ask=Decimal("0.12"),
        observed_at=NOW,
        provider_id="dexie",
    )
    assert quote.midpoint == Decimal("0.11")

    with pytest.raises(TypeError):
        MarketQuote(ASSET_ID, QUOTE_ID, 0.10, Decimal("0.12"), NOW, "dexie")
    with pytest.raises(ValueError):
        MarketQuote(ASSET_ID, QUOTE_ID, Decimal("0.13"), Decimal("0.12"), NOW, "dexie")
    with pytest.raises(ValueError):
        MarketQuote("wrong", QUOTE_ID, Decimal("0.10"), Decimal("0.12"), NOW, "dexie")


def test_book_observation_requires_sorted_positive_attributable_levels():
    book = BookObservation(
        asset_id=ASSET_ID,
        quote_asset_id=QUOTE_ID,
        bids=((Decimal("0.10"), 2000, "offer-bid-1"),),
        asks=((Decimal("0.12"), 3000, "offer-ask-1"),),
        observed_at=NOW,
        provider_id="dexie",
    )
    assert book.best_bid == Decimal("0.10")
    assert book.best_ask == Decimal("0.12")

    with pytest.raises(ValueError):
        BookObservation(
            ASSET_ID,
            QUOTE_ID,
            ((Decimal("0.10"), 0, "offer-bid-1"),),
            (),
            NOW,
            "dexie",
        )
    with pytest.raises(ValueError):
        BookObservation(
            ASSET_ID,
            QUOTE_ID,
            ((Decimal("0.13"), 1, "offer-bid-1"),),
            ((Decimal("0.12"), 1, "offer-ask-1"),),
            NOW,
            "dexie",
        )


class _Provider:
    def __init__(self, provider_id: str, capabilities: frozenset[Capability]):
        self.capabilities = ProviderCapabilities(provider_id, capabilities)


def test_registry_is_deterministic_and_rejects_duplicate_ids():
    registry = ProviderRegistry()
    splash = _Provider("splash", frozenset({Capability.DISCOVER_OFFER}))
    dexie = _Provider(
        "dexie", frozenset({Capability.ORDER_BOOK, Capability.DISCOVER_OFFER})
    )

    registry.register(splash)
    registry.register(dexie)

    assert [p.capabilities.provider_id for p in registry.all()] == ["dexie", "splash"]
    assert [
        p.capabilities.provider_id
        for p in registry.for_capability(Capability.ORDER_BOOK)
    ] == ["dexie"]
    with pytest.raises(ValueError, match="already registered"):
        registry.register(dexie)
