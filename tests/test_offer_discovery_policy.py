from __future__ import annotations

from datetime import datetime, timedelta, timezone

from offer_lifecycle import OfferDiscoveryTracker


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
IDENTITY = "ab" * 32


def test_publication_targets_are_independent_and_partial_failure_waits_for_discovery():
    tracker = OfferDiscoveryTracker(offer_identity=IDENTITY, created_at=NOW)

    assert tracker.publication_targets == ("dexie", "splash")
    tracker.record_submission(provider="dexie", succeeded=False)
    tracker.record_submission(provider="splash", succeeded=True)
    decision = tracker.evaluate(now=NOW + timedelta(seconds=45))

    assert decision.action == "WAIT_FOR_DISCOVERY"
    assert decision.reason_code == "PUBLICATION_DISCOVERY_PENDING"


def test_exact_offer_discovery_on_either_provider_proves_publication():
    for provider in ("dexie", "splash"):
        tracker = OfferDiscoveryTracker(offer_identity=IDENTITY, created_at=NOW)
        tracker.record_discovery(provider=provider, observed_offer_identity=IDENTITY)

        decision = tracker.evaluate(now=NOW + timedelta(seconds=20))

        assert decision.action == "KEEP_LIVE"
        assert decision.exact_providers == (provider,)


def test_duplicate_discovery_evidence_is_idempotent():
    tracker = OfferDiscoveryTracker(offer_identity=IDENTITY, created_at=NOW)
    tracker.record_discovery(provider="dexie", observed_offer_identity=IDENTITY)
    tracker.record_discovery(provider="dexie", observed_offer_identity=IDENTITY)

    assert tracker.evaluate(now=NOW).exact_providers == ("dexie",)


def test_wrong_offer_identity_never_proves_publication():
    tracker = OfferDiscoveryTracker(offer_identity=IDENTITY, created_at=NOW)
    tracker.record_discovery(provider="dexie", observed_offer_identity="cd" * 32)

    decision = tracker.evaluate(now=NOW + timedelta(seconds=90))

    assert decision.action == "CANCEL_VIA_SAGE"
    assert decision.reason_code == "PUBLICATION_DISCOVERY_DEADLINE_EXCEEDED"
    assert decision.mismatched_providers == ("dexie",)


def test_no_exact_discovery_by_ninety_seconds_requires_sage_cancel():
    tracker = OfferDiscoveryTracker(offer_identity=IDENTITY, created_at=NOW)

    before = tracker.evaluate(now=NOW + timedelta(seconds=89, milliseconds=999))
    deadline = tracker.evaluate(now=NOW + timedelta(seconds=90))

    assert before.action == "WAIT_FOR_DISCOVERY"
    assert deadline.action == "CANCEL_VIA_SAGE"


def test_replacement_waits_for_terminal_proof_and_exponential_backoff():
    tracker = OfferDiscoveryTracker(offer_identity=IDENTITY, created_at=NOW)
    terminal_at = NOW + timedelta(seconds=100)

    blocked = tracker.replacement_decision(
        authoritative_terminal=False,
        terminal_at=None,
        attempt=0,
        now=terminal_at,
    )
    backing_off = tracker.replacement_decision(
        authoritative_terminal=True,
        terminal_at=terminal_at,
        attempt=2,
        now=terminal_at + timedelta(seconds=19),
    )
    allowed = tracker.replacement_decision(
        authoritative_terminal=True,
        terminal_at=terminal_at,
        attempt=2,
        now=terminal_at + timedelta(seconds=20),
    )

    assert blocked.action == "BLOCK_REPLACEMENT"
    assert blocked.reason_code == "AUTHORITATIVE_TERMINAL_PROOF_REQUIRED"
    assert backing_off.action == "WAIT_REPLACEMENT_BACKOFF"
    assert backing_off.retry_after_seconds == 1
    assert allowed.action == "ALLOW_REPLACEMENT"


def test_state_round_trip_preserves_deadline_and_prevents_duplicate_live_offer():
    first = OfferDiscoveryTracker(offer_identity=IDENTITY, created_at=NOW)
    first.record_submission(provider="dexie", succeeded=True)
    restored = OfferDiscoveryTracker.from_state(first.to_state())

    assert restored.to_state() == first.to_state()
    assert (
        restored.evaluate(now=NOW + timedelta(seconds=90)).action == "CANCEL_VIA_SAGE"
    )
    assert restored.authorize_duplicate_create(IDENTITY) is False
    assert restored.authorize_duplicate_create("ef" * 32) is True
