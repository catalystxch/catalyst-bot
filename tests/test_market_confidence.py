from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from market_confidence import MarketConfidenceEngine
from providers.models import (
    Capability,
    ObservationQuality,
    ProviderObservation,
    canonical_evidence_json,
    evidence_digest,
)


ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _observation(
    provider, payload, *, age=0, at=None, quality=ObservationQuality.VALID
):
    observed = (at or NOW) - timedelta(seconds=age)
    raw = canonical_evidence_json({"asset_id": ASSET_ID, **payload})
    identities = tuple(
        sorted(
            {
                ASSET_ID,
                *(
                    row["offer_id"]
                    for side in ("bids", "asks")
                    for row in payload.get(side, [])
                ),
                *(row["offer_id"] for row in payload.get("offers", [])),
            }
        )
    )
    return ProviderObservation(
        provider_id=provider,
        capability=Capability.ORDER_BOOK,
        observed_at=observed,
        source_time=None,
        source_height=None,
        fresh_until=observed + timedelta(seconds=20),
        identity_keys=identities,
        payload_sha256=evidence_digest(raw),
        quality=quality,
        reason_codes=(),
        raw_evidence_json=raw,
    )


def _dexie(
    *,
    bid="0.099",
    ask="0.101",
    amount=3_000,
    age=0,
    at=None,
    ids=("d-b", "d-a"),
):
    return _observation(
        "dexie",
        {
            "bids": [{"offer_id": ids[0], "price": bid, "amount_mojos": amount}],
            "asks": [{"offer_id": ids[1], "price": ask, "amount_mojos": amount}],
        },
        age=age,
        at=at,
    )


def _splash(*, bid="0.099", ask="0.101", amount=3_000, at=None, ids=("s-b", "s-a")):
    return _observation(
        "splash",
        {
            "offers": [
                {
                    "offer_id": ids[0],
                    "side": "buy",
                    "price": bid,
                    "amount_mojos": amount,
                },
                {
                    "offer_id": ids[1],
                    "side": "sell",
                    "price": ask,
                    "amount_mojos": amount,
                },
            ]
        },
        at=at,
    )


@pytest.mark.parametrize(
    ("observations", "expected_state", "reason"),
    [
        ((_dexie(), _splash()), "GREEN", None),
        ((_dexie(),), "AMBER", "single_provider_dependency"),
        ((_dexie(amount=500), _splash(amount=500)), "RED", "insufficient_bid_depth"),
        ((_dexie(age=21), _splash()), "AMBER", "stale_provider_data"),
        (
            (
                _observation(
                    "dexie",
                    {
                        "bids": [
                            {
                                "offer_id": "only-bid",
                                "price": "0.1",
                                "amount_mojos": 10_000,
                            }
                        ],
                        "asks": [],
                    },
                ),
            ),
            "RED",
            "one_sided_book",
        ),
    ],
)
def test_confidence_table(observations, expected_state, reason):
    result = MarketConfidenceEngine(risk_preset="balanced").evaluate(
        observations=observations,
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    assert result.state == expected_state
    assert reason is None or reason in result.reason_codes


def test_own_offers_are_excluded_before_price_and_depth():
    result = MarketConfidenceEngine(risk_preset="balanced").evaluate(
        observations=(
            _dexie(
                bid="0.20",
                ask="0.21",
                amount=50_000,
                ids=("ours-b", "ours-a"),
            ),
            _splash(amount=3_000),
        ),
        own_offer_identities=frozenset({"ours-b", "ours-a"}),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    assert result.trusted_bid == Decimal("0.099")
    assert result.trusted_ask == Decimal("0.101")
    assert result.independent_bid_depth_mojos == 3_000
    assert result.independent_ask_depth_mojos == 3_000
    assert result.excluded_own_offer_count == 2


def test_same_offer_seen_on_dexie_and_splash_is_counted_once():
    result = MarketConfidenceEngine(risk_preset="balanced").evaluate(
        observations=(
            _dexie(amount=2_000, ids=("same-b", "same-a")),
            _splash(amount=2_000, ids=("same-b", "same-a")),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    assert result.independent_bid_depth_mojos == 2_000
    assert result.independent_ask_depth_mojos == 2_000
    assert result.deduplicated_offer_count == 2


def test_depth_threshold_scales_with_offer_size_and_preset():
    conservative = MarketConfidenceEngine(risk_preset="conservative").evaluate(
        observations=(_dexie(amount=1_000), _splash(amount=1_000)),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )
    aggressive = MarketConfidenceEngine(risk_preset="aggressive").evaluate(
        observations=(_dexie(amount=1_000), _splash(amount=1_000)),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    assert conservative.required_depth_mojos == 3_000
    assert conservative.state == "RED"
    assert aggressive.required_depth_mojos == 1_500
    assert aggressive.state == "GREEN"


def test_far_away_junk_offers_cannot_satisfy_executable_depth():
    dexie = _observation(
        "dexie",
        {
            "bids": [
                {"offer_id": "top-bid", "price": "0.099", "amount_mojos": 100},
                {
                    "offer_id": "junk-bid",
                    "price": "0.001",
                    "amount_mojos": 1_000_000,
                },
            ],
            "asks": [
                {"offer_id": "top-ask", "price": "0.101", "amount_mojos": 100},
                {
                    "offer_id": "junk-ask",
                    "price": "10",
                    "amount_mojos": 1_000_000,
                },
            ],
        },
    )

    result = MarketConfidenceEngine(risk_preset="balanced").evaluate(
        observations=(dexie,),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    assert result.state == "RED"
    assert result.independent_bid_depth_mojos == 100
    assert result.independent_ask_depth_mojos == 100
    assert "insufficient_bid_depth" in result.reason_codes
    assert "insufficient_ask_depth" in result.reason_codes


def test_hydrate_normalizes_legacy_empty_offer_timestamp():
    engine = MarketConfidenceEngine(risk_preset="balanced")

    engine.hydrate(
        {
            "risk_preset": "balanced",
            "last_trusted_midpoint": None,
            "last_trusted_bid": None,
            "last_trusted_ask": None,
            "pending_midpoint": None,
            "pending_refreshes": 0,
            "prior_offer_ids": [],
            "prior_observed_at": NOW.isoformat().replace("+00:00", "Z"),
        }
    )

    assert engine.export_state()["prior_observed_at"] is None


def test_material_move_requires_persistence_but_settled_trade_can_confirm():
    engine = MarketConfidenceEngine(risk_preset="balanced")
    baseline = engine.evaluate(
        observations=(_dexie(), _splash()),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )
    first = engine.evaluate(
        observations=(
            _dexie(bid="0.11", ask="0.112", at=NOW + timedelta(seconds=20)),
            _splash(bid="0.11", ask="0.112", at=NOW + timedelta(seconds=20)),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW + timedelta(seconds=20),
    )
    second = engine.evaluate(
        observations=(
            _dexie(bid="0.11", ask="0.112", at=NOW + timedelta(seconds=40)),
            _splash(bid="0.11", ask="0.112", at=NOW + timedelta(seconds=40)),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW + timedelta(seconds=40),
    )

    assert baseline.trusted_midpoint == Decimal("0.1")
    assert first.state == "AMBER"
    assert first.trusted_midpoint == Decimal("0.1")
    assert first.pending_movement_refreshes == 1
    assert second.trusted_midpoint == Decimal("0.111")

    confirmed = MarketConfidenceEngine(risk_preset="balanced")
    confirmed.evaluate(
        observations=(_dexie(), _splash()),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )
    accepted = confirmed.evaluate(
        observations=(
            _dexie(bid="0.11", ask="0.112", at=NOW + timedelta(seconds=20)),
            _splash(bid="0.11", ask="0.112", at=NOW + timedelta(seconds=20)),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        settled_trade_price=Decimal("0.111"),
        now=NOW + timedelta(seconds=20),
    )
    assert accepted.trusted_midpoint == Decimal("0.111")
    assert "settled_trade_confirmed_move" in accepted.reason_codes


def test_material_move_persistence_allows_small_midpoint_jitter():
    engine = MarketConfidenceEngine(risk_preset="balanced")
    engine.evaluate(
        observations=(_dexie(), _splash()),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    first = engine.evaluate(
        observations=(
            _dexie(bid="0.11", ask="0.112", at=NOW + timedelta(seconds=20)),
            _splash(bid="0.11", ask="0.112", at=NOW + timedelta(seconds=20)),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW + timedelta(seconds=20),
    )
    second = engine.evaluate(
        observations=(
            _dexie(bid="0.1101", ask="0.1121", at=NOW + timedelta(seconds=40)),
            _splash(bid="0.1101", ask="0.1121", at=NOW + timedelta(seconds=40)),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW + timedelta(seconds=40),
    )

    assert first.state == "AMBER"
    assert first.pending_movement_refreshes == 1
    assert second.state == "GREEN"
    assert second.trusted_midpoint == Decimal("0.1111")
    assert second.pending_movement_refreshes == 0
    assert "movement_persistence_satisfied" in second.reason_codes


def test_material_move_persistence_jitter_does_not_ratchet_anchor():
    engine = MarketConfidenceEngine(risk_preset="conservative")
    engine.evaluate(
        observations=(_dexie(), _splash()),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    results = []
    for offset, midpoint in enumerate(("0.111", "0.1119", "0.1128"), start=1):
        half_spread = Decimal("0.001")
        results.append(
            engine.evaluate(
                observations=(
                    _dexie(
                        bid=str(Decimal(midpoint) - half_spread),
                        ask=str(Decimal(midpoint) + half_spread),
                        at=NOW + timedelta(seconds=20 * offset),
                    ),
                    _splash(
                        bid=str(Decimal(midpoint) - half_spread),
                        ask=str(Decimal(midpoint) + half_spread),
                        at=NOW + timedelta(seconds=20 * offset),
                    ),
                ),
                own_offer_identities=frozenset(),
                configured_offer_size_mojos=1_000,
                now=NOW + timedelta(seconds=20 * offset),
            )
        )

    assert [result.state for result in results] == ["AMBER", "AMBER", "AMBER"]
    assert results[-1].trusted_midpoint == Decimal("0.1")
    assert results[-1].pending_movement_refreshes == 1


def test_hard_move_cap_rejects_even_settled_trade():
    engine = MarketConfidenceEngine(risk_preset="balanced")
    engine.evaluate(
        observations=(_dexie(), _splash()),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )
    result = engine.evaluate(
        observations=(
            _dexie(bid="0.14", ask="0.142"),
            _splash(bid="0.14", ask="0.142"),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        settled_trade_price=Decimal("0.141"),
        now=NOW + timedelta(seconds=20),
    )

    assert result.state == "RED"
    assert result.trusted_midpoint == Decimal("0.1")
    assert "hard_price_move_cap" in result.reason_codes


def test_chain_evidence_overrides_provider_conflict_but_stays_amber():
    result = MarketConfidenceEngine(risk_preset="balanced").evaluate(
        observations=(
            _dexie(),
            _splash(bid="0.13", ask="0.132"),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        settled_trade_price=Decimal("0.1"),
        now=NOW,
    )

    assert result.state == "AMBER"
    assert result.trusted_midpoint == Decimal("0.1")
    assert "chain_override_source_conflict" in result.reason_codes


def test_rapid_offer_churn_raises_manipulation_and_never_improves_confidence():
    engine = MarketConfidenceEngine(risk_preset="balanced")
    first = engine.evaluate(
        observations=(_dexie(), _splash()),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )
    churned = engine.evaluate(
        observations=(
            _dexie(ids=("d-b-2", "d-a-2")),
            _splash(ids=("s-b-2", "s-a-2")),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW + timedelta(seconds=5),
    )

    assert first.state == "GREEN"
    assert churned.state in {"AMBER", "RED"}
    assert churned.manipulation_score > 0
    assert "rapid_offer_churn" in churned.reason_codes
    assert churned.derived_thresholds["manipulation_amber"] == 50


@pytest.mark.parametrize(
    ("junk_bid", "junk_ask"),
    [
        ("0.01", "1"),
        ("0.0985", "0.1015"),
    ],
)
def test_non_executable_dust_churn_cannot_force_red_confidence(
    junk_bid, junk_ask
):
    def splash_with_rotating_junk(suffix: str, at: datetime):
        offers = [
            {
                "offer_id": "stable-s-b",
                "side": "buy",
                "price": "0.099",
                "amount_mojos": 3_000,
            },
            {
                "offer_id": "stable-s-a",
                "side": "sell",
                "price": "0.101",
                "amount_mojos": 3_000,
            },
        ]
        offers.extend(
            {
                "offer_id": f"junk-{suffix}-b-{index}",
                "side": "buy",
                "price": junk_bid,
                "amount_mojos": 1,
            }
            for index in range(10)
        )
        offers.extend(
            {
                "offer_id": f"junk-{suffix}-a-{index}",
                "side": "sell",
                "price": junk_ask,
                "amount_mojos": 1,
            }
            for index in range(10)
        )
        return _observation("splash", {"offers": offers}, at=at)

    engine = MarketConfidenceEngine(risk_preset="balanced")
    baseline = engine.evaluate(
        observations=(_dexie(), splash_with_rotating_junk("first", NOW)),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )
    rotated = engine.evaluate(
        observations=(
            _dexie(at=NOW + timedelta(seconds=5)),
            splash_with_rotating_junk("second", NOW + timedelta(seconds=5)),
        ),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW + timedelta(seconds=5),
    )

    assert baseline.state == "GREEN"
    assert rotated.state == "GREEN"
    assert rotated.manipulation_score == 0
    assert "rapid_offer_churn" not in rotated.reason_codes
    if junk_bid == "0.01":
        assert "out_of_range_depth_excluded" in rotated.reason_codes
