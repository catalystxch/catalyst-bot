"""Thin-market mode: quote from whatever outside book exists, hold when it vanishes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from market_confidence import MarketConfidenceEngine
from providers.models import (
    Capability,
    ObservationQuality,
    ProviderObservation,
    canonical_evidence_json,
    evidence_digest,
)

# Helpers are local (not imported from test_market_confidence) so the engine
# and the observation class always come from the same module import.
ASSET_ID = "b8" * 32
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _observation(provider, payload, *, at=None):
    observed = at or NOW
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
        quality=ObservationQuality.VALID,
        reason_codes=(),
        raw_evidence_json=raw,
    )


def _dexie(*, bid="0.099", ask="0.101", amount=3_000, at=None):
    return _observation(
        "dexie",
        {
            "bids": [{"offer_id": "d-b", "price": bid, "amount_mojos": amount}],
            "asks": [{"offer_id": "d-a", "price": ask, "amount_mojos": amount}],
        },
        at=at,
    )


def _engine(**kwargs):
    return MarketConfidenceEngine(
        risk_preset="balanced", minimum_provider_count=1, thin_market=True, **kwargs
    )


def _evaluate(engine, observation, *, at=NOW):
    return engine.evaluate(
        observations=(observation,),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=at,
    )


def _one_sided(*, at=NOW):
    return _observation(
        "dexie",
        {
            "bids": [{"offer_id": "only-bid", "price": "0.1", "amount_mojos": 10_000}],
            "asks": [],
        },
        at=at,
    )


def test_default_engine_still_rejects_shallow_book():
    result = MarketConfidenceEngine(risk_preset="balanced").evaluate(
        observations=(_dexie(amount=500),),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    assert result.state == "RED"
    assert result.data_valid is False


def test_thin_market_accepts_shallow_single_provider_book_at_full_capacity():
    result = _evaluate(_engine(), _dexie(bid="0.05", ask="0.18", amount=500))

    assert result.data_valid is True
    assert result.state != "RED"
    assert result.trusted_bid == Decimal("0.05")
    assert result.trusted_ask == Decimal("0.18")
    assert result.follow_capacity_fraction == Decimal("1")
    assert "insufficient_bid_depth" in result.reason_codes


def test_thin_market_holds_last_edges_when_book_goes_one_sided():
    engine = _engine()
    _evaluate(engine, _dexie(bid="0.05", ask="0.18", amount=500))

    later = NOW + timedelta(seconds=30)
    result = _evaluate(engine, _one_sided(at=later), at=later)

    assert result.data_valid is True
    assert result.state == "AMBER"
    assert "holding_last_trusted_price" in result.reason_codes
    assert result.trusted_bid == Decimal("0.05")
    assert result.trusted_ask == Decimal("0.18")
    assert result.follow_capacity_fraction == Decimal("1")


def test_thin_market_stays_red_when_there_is_nothing_to_hold():
    result = _evaluate(_engine(), _one_sided())

    assert result.state == "RED"
    assert result.data_valid is False
    assert result.trusted_midpoint is None


def test_thin_market_holds_through_hard_move_then_reanchors_on_persistence():
    engine = _engine()
    _evaluate(engine, _dexie(bid="0.05", ask="0.07", amount=500))

    results = []
    for step in range(1, 6):
        at = NOW + timedelta(seconds=30 * step)
        results.append(
            _evaluate(
                engine,
                _dexie(bid="0.05", ask="0.18", amount=500, at=at),
                at=at,
            )
        )

    first = results[0]
    assert first.data_valid is True
    assert "hard_price_move_cap" in first.reason_codes
    assert "holding_last_trusted_price" in first.reason_codes
    # The outside ask moved away from us: follow it at once, never sell below it.
    assert first.trusted_ask == Decimal("0.18")

    last = results[-1]
    assert last.data_valid is True
    assert "hard_move_reanchor_persistence_satisfied" in last.reason_codes
    assert last.trusted_ask == Decimal("0.18")


def test_thin_market_hold_keeps_safer_edge_when_outside_ask_drops_sharply():
    engine = _engine()
    _evaluate(engine, _dexie(bid="0.05", ask="0.18", amount=500))

    at = NOW + timedelta(seconds=30)
    result = _evaluate(engine, _dexie(bid="0.05", ask="0.07", amount=500, at=at), at=at)

    assert "holding_last_trusted_price" in result.reason_codes
    assert result.trusted_ask == Decimal("0.18")
    assert result.trusted_bid == Decimal("0.05")
    assert result.trusted_midpoint == Decimal("0.115")


# ---- per-side edge anchoring -------------------------------------------------

from ladder_sizing import ladder_price_for_slot, thin_market_side_mid  # noqa: E402


def test_side_mid_puts_inner_slot_just_inside_each_outside_edge():
    bid, ask = Decimal("0.00005"), Decimal("0.00018")
    kwargs = {
        "trusted_bid": bid,
        "trusted_ask": ask,
        "step_bps": 10,
        "min_edge_bps": 50,
    }

    sell_mid = thin_market_side_mid("sell", **kwargs)
    buy_mid = thin_market_side_mid("buy", **kwargs)

    inner_sell = ladder_price_for_slot(0, "sell", sell_mid, Decimal("0.05"), 6, 50)
    inner_buy = ladder_price_for_slot(0, "buy", buy_mid, Decimal("0.05"), 6, 50)
    outer_sell = ladder_price_for_slot(5, "sell", sell_mid, Decimal("0.05"), 6, 50)
    outer_buy = ladder_price_for_slot(5, "buy", buy_mid, Decimal("0.05"), 6, 50)

    assert inner_sell == ask * Decimal("0.999")
    assert inner_buy == bid * Decimal("1.001")
    assert outer_sell > inner_sell > inner_buy > outer_buy > 0


def test_side_mid_declines_when_edges_missing_or_too_tight_to_step_inside():
    assert (
        thin_market_side_mid(
            "sell",
            trusted_bid=None,
            trusted_ask=Decimal("1"),
            step_bps=10,
            min_edge_bps=0,
        )
        is None
    )
    assert (
        thin_market_side_mid(
            "buy",
            trusted_bid=Decimal("1.0000"),
            trusted_ask=Decimal("1.0005"),
            step_bps=10,
            min_edge_bps=0,
        )
        is None
    )
    assert (
        thin_market_side_mid(
            "hold",
            trusted_bid=Decimal("1"),
            trusted_ask=Decimal("2"),
            step_bps=10,
            min_edge_bps=0,
        )
        is None
    )


# ---- runtime: thin book authorises a ladder and survives the book vanishing --

import database  # noqa: E402
import pytest  # noqa: E402
from market_runtime import OfferBookMarketRuntime  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "thin-market.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    yield
    database.close_connection()


def _thin_runtime(book, *, thin_market=True):
    return OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda asset_id: book["current"],
        fetch_splash_offers=lambda asset_id: [],
        fetch_splash_health=lambda: {
            "running": False,
            "api_reachable": False,
            "peers": 0,
        },
        minimum_provider_count=1 if thin_market else 2,
        thin_market=thin_market,
    )


_WIDE_SHALLOW_BOOK = {
    "bids": [{"offer_id": "b1", "price": "0.00005", "amount_mojos": 400_000_000_000}],
    "asks": [{"offer_id": "a1", "price": "0.00018", "amount_mojos": 400_000_000_000}],
}
_EMPTY_BOOK = {"bids": [], "asks": []}


def _refresh(runtime, at):
    return runtime.refresh(
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000_000_000_000,
        now=at,
    )


def test_strict_runtime_refuses_the_wide_shallow_book(isolated_db):
    result = _refresh(
        _thin_runtime({"current": _WIDE_SHALLOW_BOOK}, thin_market=False), NOW
    )

    assert result.confidence.state == "RED"
    assert result.degraded.can_create is False


def test_thin_runtime_authorises_ladder_and_holds_when_book_vanishes(isolated_db):
    book = {"current": _WIDE_SHALLOW_BOOK}
    runtime = _thin_runtime(book)

    first = _refresh(runtime, NOW)
    assert first.degraded.can_create is True
    assert first.degraded.can_requote is True
    assert first.degraded.cancel_tiers == ()

    book["current"] = _EMPTY_BOOK
    for minutes in (1, 5, 15):
        held = _refresh(runtime, NOW + timedelta(minutes=minutes))
        assert held.confidence.data_valid is True
        assert "holding_last_trusted_price" in held.confidence.reason_codes
        assert held.confidence.trusted_bid == Decimal("0.00005")
        assert held.confidence.trusted_ask == Decimal("0.00018")
        assert held.degraded.can_create is True
        assert held.degraded.cancel_tiers == ()
        assert held.degraded.stage == "NONE"

    # A restart must come back holding the same edges, not RED.
    restarted = _refresh(_thin_runtime(book), NOW + timedelta(minutes=20))
    assert restarted.confidence.data_valid is True
    assert restarted.confidence.trusted_ask == Decimal("0.00018")
    assert restarted.degraded.can_create is True


# ---- operator starting price: a brand-new token still gets a ladder ----------


def _empty(*, at=NOW):
    return _observation("dexie", {"bids": [], "asks": []}, at=at)


def test_starting_price_is_ignored_outside_thin_market_mode():
    result = MarketConfidenceEngine(
        risk_preset="balanced", fallback_price=Decimal("0.002")
    ).evaluate(
        observations=(_empty(),),
        own_offer_identities=frozenset(),
        configured_offer_size_mojos=1_000,
        now=NOW,
    )

    assert result.state == "RED"
    assert result.data_valid is False


def test_starting_price_quotes_a_brand_new_token_with_an_empty_book():
    result = _evaluate(_engine(fallback_price=Decimal("0.002")), _empty())

    assert result.data_valid is True
    assert result.state == "AMBER"
    assert "using_manual_reference_price" in result.reason_codes
    assert result.trusted_midpoint == Decimal("0.002")
    assert result.trusted_bid == result.trusted_ask == Decimal("0.002")
    assert result.follow_capacity_fraction == Decimal("1")


def test_starting_price_change_applies_at_once_until_a_real_book_exists():
    first = _engine(fallback_price=Decimal("0.002"))
    _evaluate(first, _empty())

    second = _engine(fallback_price=Decimal("0.003"))
    second.hydrate(first.export_state())
    result = _evaluate(second, _empty())

    assert result.trusted_midpoint == Decimal("0.003")


def test_real_two_sided_book_replaces_the_starting_price_immediately():
    engine = _engine(fallback_price=Decimal("0.002"))
    _evaluate(engine, _empty())

    at = NOW + timedelta(seconds=30)
    result = _evaluate(engine, _dexie(bid="0.05", ask="0.18", amount=500, at=at), at=at)

    assert "using_manual_reference_price" not in result.reason_codes
    assert result.trusted_bid == Decimal("0.05")
    assert result.trusted_ask == Decimal("0.18")

    # ...and once a real price is known, an empty book holds that, not the setting.
    later = at + timedelta(seconds=30)
    held = _evaluate(engine, _empty(at=later), at=later)
    assert "holding_last_trusted_price" in held.reason_codes
    assert held.trusted_ask == Decimal("0.18")


def test_starting_price_never_crosses_a_lone_visible_edge():
    # Only a bid is on the book, above the starting price: do not sell below it.
    engine = _engine(fallback_price=Decimal("0.05"))
    result = _evaluate(engine, _one_sided())
    assert result.trusted_bid == Decimal("0.05")
    assert result.trusted_ask == Decimal("0.1")

    # Only an ask is on the book, below the starting price: do not buy above it.
    lone_ask = _observation(
        "dexie",
        {
            "bids": [],
            "asks": [{"offer_id": "only-ask", "price": "0.02", "amount_mojos": 10_000}],
        },
    )
    result = _evaluate(_engine(fallback_price=Decimal("0.05")), lone_ask)
    assert result.trusted_bid == Decimal("0.02")
    assert result.trusted_ask == Decimal("0.05")


def test_runtime_builds_ladder_for_brand_new_token_and_survives_outage(isolated_db):
    def failing_book(_asset_id):
        raise RuntimeError("dexie unreachable")

    runtime = OfferBookMarketRuntime(
        asset_id=ASSET_ID,
        risk_preset="balanced",
        fetch_dexie_book=lambda asset_id: _EMPTY_BOOK,
        fetch_splash_offers=lambda asset_id: [],
        fetch_splash_health=lambda: {
            "running": False,
            "api_reachable": False,
            "peers": 0,
        },
        minimum_provider_count=1,
        thin_market=True,
        fallback_price=Decimal("0.002"),
    )

    first = _refresh(runtime, NOW)
    assert first.confidence.trusted_midpoint == Decimal("0.002")
    assert first.degraded.can_create is True
    assert first.degraded.can_requote is True
    assert first.degraded.cancel_tiers == ()
    # The permit must outlive the refresh or the loop would treat it as expired.
    assert first.valid_until > NOW

    runtime._dexie._fetch_book = failing_book
    for minutes in (1, 15, 60):
        at = NOW + timedelta(minutes=minutes)
        outage = _refresh(runtime, at)
        assert outage.confidence.data_valid is True
        assert outage.degraded.can_create is True
        assert outage.degraded.cancel_tiers == ()
        assert outage.valid_until > at


# ---- per-offer guard: warnings, not blocks, in thin-market mode --------------


def _guard(monkeypatch, *, thin, price, confidence_overrides=None, age_seconds=0):
    import offer_manager

    monkeypatch.setattr(offer_manager.cfg, "THIN_MARKET_MODE", thin, raising=False)
    confidence = {
        "data_valid": True,
        "state": "AMBER",
        "derived_at": NOW,
        "trusted_midpoint": Decimal("0.002"),
        "trusted_bid": Decimal("0.002"),
        "trusted_ask": Decimal("0.002"),
        "evidence_digests": ("ab" * 32,),
    }
    confidence.update(confidence_overrides or {})
    return offer_manager._assess_candidate_for_market_mode(
        side="sell",
        candidate_price=price,
        size_xch=Decimal("0.01"),
        confidence=confidence,
        network_fee_xch=Decimal("0.0001"),
        expected_cancel_requotes=2,
        minimum_profit_xch=Decimal("0.0001"),
        now=NOW + timedelta(seconds=age_seconds),
    )


def test_strict_mode_still_blocks_thin_profit_and_stale_snapshots(monkeypatch):
    assert (
        _guard(monkeypatch, thin=False, price=Decimal("0.00201"))["eligible"] is False
    )
    stale = _guard(monkeypatch, thin=False, price=Decimal("0.003"), age_seconds=25)
    assert stale["reason_code"] == "market_confidence_stale"
    assert stale["eligible"] is False


def test_thin_mode_lets_low_profit_and_stale_candidates_through(monkeypatch):
    low = _guard(monkeypatch, thin=True, price=Decimal("0.00201"))
    assert low["eligible"] is True
    assert low["improves_book"] is False
    assert low["warning_code"] == "profit_floor_not_met"

    stale = _guard(monkeypatch, thin=True, price=Decimal("0.003"), age_seconds=25)
    assert stale["eligible"] is True
    assert stale["warning_code"] == "market_confidence_stale"


def test_thin_mode_never_marks_an_inner_slot_as_a_restricted_book_opportunity(
    monkeypatch,
):
    wide = {
        "trusted_midpoint": Decimal("0.000115"),
        "trusted_bid": Decimal("0.00005"),
        "trusted_ask": Decimal("0.00018"),
    }
    result = _guard(
        monkeypatch, thin=True, price=Decimal("0.00017982"), confidence_overrides=wide
    )
    assert result["eligible"] is True
    assert result["improves_book"] is False


def test_thin_mode_still_refuses_a_sell_below_the_midpoint_or_no_price(monkeypatch):
    wrong_side = _guard(monkeypatch, thin=True, price=Decimal("0.0019"))
    assert wrong_side["eligible"] is False
    assert wrong_side["reason_code"] == "candidate_outside_profitable_side"

    invalid = _guard(
        monkeypatch,
        thin=True,
        price=Decimal("0.003"),
        confidence_overrides={"data_valid": False},
    )
    assert invalid["eligible"] is False


def test_thin_mode_ignores_stale_dynamic_band_but_keeps_hard_limits(monkeypatch):
    import risk_manager
    from types import SimpleNamespace

    manager = risk_manager.RiskManager.__new__(risk_manager.RiskManager)
    manager._price_engine = SimpleNamespace(
        get_dynamic_limits=lambda: (Decimal("0.00004"), Decimal("0.00006"))
    )
    trips = []
    manager._trip_circuit_breaker = lambda reason, **_kwargs: trips.append(reason)
    monkeypatch.setattr(risk_manager.cfg, "HARD_MIN_PRICE_XCH", Decimal("0"))
    monkeypatch.setattr(risk_manager.cfg, "HARD_MAX_PRICE_XCH", Decimal("0"))

    monkeypatch.setattr(risk_manager.cfg, "THIN_MARKET_MODE", False, raising=False)
    assert manager._check_price_limits(Decimal("0.000115")) is True

    trips.clear()
    monkeypatch.setattr(risk_manager.cfg, "THIN_MARKET_MODE", True, raising=False)
    assert manager._check_price_limits(Decimal("0.000115")) is False
    assert trips == []

    monkeypatch.setattr(risk_manager.cfg, "HARD_MAX_PRICE_XCH", Decimal("0.0001"))
    assert manager._check_price_limits(Decimal("0.000115")) is True


# ---- ladder depth: thin-market ladders reach a fixed distance from the edge --

from ladder_sizing import thin_market_edges, thin_market_slot_price  # noqa: E402


def test_thin_ladder_reaches_ten_percent_from_each_edge_whatever_the_spread():
    buy_edge, sell_edge = thin_market_edges(
        trusted_bid=Decimal("0.000045"),
        trusted_ask=Decimal("0.000179"),
        step_bps=10,
    )
    sells = [thin_market_slot_price(i, "sell", sell_edge, 1000, 24) for i in range(24)]
    buys = [thin_market_slot_price(i, "buy", buy_edge, 1000, 24) for i in range(24)]

    assert sells[0] == Decimal("0.000179") * Decimal("0.999")
    assert sells[-1] == sells[0] * Decimal("1.1")
    assert buys[0] == Decimal("0.000045") * Decimal("1.001")
    assert buys[-1] == buys[0] * Decimal("0.9")
    assert sells == sorted(sells) and buys == sorted(buys, reverse=True)
    assert len(set(sells)) == 24 and len(set(buys)) == 24


def test_offer_manager_prices_from_the_edge_only_in_thin_mode(monkeypatch):
    import offer_manager

    manager = offer_manager.OfferManager.__new__(offer_manager.OfferManager)
    monkeypatch.setattr(offer_manager.cfg, "MIN_EDGE_BPS", Decimal("3577"))
    monkeypatch.setattr(
        offer_manager.cfg,
        "THIN_MARKET_LADDER_DEPTH_BPS",
        Decimal("1000"),
        raising=False,
    )
    mid, half_spread = Decimal("0.000112"), Decimal("0.8944")

    # No edges recorded: ordinary midpoint pricing, even in thin mode.
    monkeypatch.setattr(offer_manager.cfg, "THIN_MARKET_MODE", True, raising=False)
    plain = manager._get_ladder_price(23, "buy", mid, half_spread, 24)
    assert plain == mid * (Decimal("1") - half_spread)

    manager.set_thin_market_edges(Decimal("0.00004505"), Decimal("0.00017882"))
    assert manager._get_ladder_price(0, "sell", mid, half_spread, 24) == Decimal(
        "0.00017882"
    )
    assert manager._get_ladder_price(23, "buy", mid, half_spread, 24) == Decimal(
        "0.00004505"
    ) * Decimal("0.9")

    # Strict mode ignores recorded edges.
    monkeypatch.setattr(offer_manager.cfg, "THIN_MARKET_MODE", False, raising=False)
    assert manager._get_ladder_price(23, "buy", mid, half_spread, 24) == plain

    manager.set_thin_market_edges(None, None)
    assert manager._thin_market_edges == {}


def test_smart_settings_bootstrap_suggestion_does_not_block_thin_markets():
    import inspect

    import api_server  # noqa: F401  (must load before its blueprints)
    from blueprints import smart_defaults

    source = inspect.getsource(smart_defaults._calculate_smart_defaults)
    assert "if thin_market_mode and data_valid is True:" in source
    assert "bootstrap_suggested = False" in source


# ---- display: the dashboard must report what the runtime actually decided ----


def _aged(monkeypatch, *, thin, state, reasons, providers):
    import api_server
    from blueprints import market

    monkeypatch.setattr(api_server.cfg, "THIN_MARKET_MODE", thin, raising=False)
    return market._age_confidence_snapshot(
        {
            "state": state,
            "derived_at": NOW.isoformat(),
            "reason_codes": list(reasons),
            "source_health": {"dexie": "valid", "splash": "unavailable"},
        },
        providers,
        now=NOW,
    )


_DEXIE_ONLY = {"dexie": {"status": "valid"}, "splash": {"status": "unavailable"}}
_NO_PROVIDERS = {"dexie": {"status": "degraded"}, "splash": {"status": "unavailable"}}


def test_strict_display_downgrades_a_single_provider_to_restricted(monkeypatch):
    aged = _aged(
        monkeypatch, thin=False, state="GREEN", reasons=(), providers=_DEXIE_ONLY
    )
    assert aged["state"] == "AMBER"
    assert aged["follow_capacity_fraction"] == "0.25"
    assert "single_provider_dependency" in aged["reason_codes"]


def test_thin_display_keeps_single_provider_green_at_full_size(monkeypatch):
    aged = _aged(
        monkeypatch, thin=True, state="GREEN", reasons=(), providers=_DEXIE_ONLY
    )
    assert aged["state"] == "GREEN"
    assert aged["follow_capacity_fraction"] == "1"
    assert aged["market_stage"] == "FOLLOW"
    assert "single_provider_dependency" not in aged["reason_codes"]


def test_thin_display_shows_a_held_price_as_valid_when_no_book_is_usable(monkeypatch):
    held = _aged(
        monkeypatch,
        thin=True,
        state="AMBER",
        reasons=("holding_last_trusted_price",),
        providers=_NO_PROVIDERS,
    )
    assert held["state"] == "AMBER"
    assert held["data_valid"] is True
    assert held["follow_capacity_fraction"] == "1"

    # With nothing held, an unusable book is still shown as RED.
    lost = _aged(
        monkeypatch, thin=True, state="GREEN", reasons=(), providers=_NO_PROVIDERS
    )
    assert lost["state"] == "RED"
    assert lost["data_valid"] is False


def test_competitor_analysis_keeps_a_wide_book_only_in_thin_mode(monkeypatch):
    import market_intel

    intel = market_intel.MarketIntel(price_engine=None)
    buys = [
        {
            "price": Decimal("0.00005"),
            "xch_amount": Decimal("1"),
            "cat_amount": Decimal("20000"),
            "is_ours": False,
            "side": "buy",
            "offer_id": "outside-bid",
            "age_secs": 60,
        },
    ]
    sells = [
        {
            "price": Decimal("0.00018"),
            "xch_amount": Decimal("1"),
            "cat_amount": Decimal("5555"),
            "is_ours": False,
            "side": "sell",
            "offer_id": "outside-ask",
            "age_secs": 60,
        },
    ]

    def analysed(thin):
        monkeypatch.setattr(market_intel.cfg, "THIN_MARKET_MODE", thin, raising=False)
        intel._analyse_orderbook(list(buys), list(sells))
        return dict(intel._competitors)

    strict = analysed(False)
    thin = analysed(True)
    assert strict.get("best_bid", Decimal("0")) == 0
    assert strict.get("best_ask", Decimal("0")) == 0
    assert thin.get("best_bid") == Decimal("0.00005")
    assert thin.get("best_ask") == Decimal("0.00018")


# ---- restart: a resumed ladder must not look like a price move ----------------


def test_restart_baseline_matches_the_resumed_ladder_not_the_plain_mid(monkeypatch):
    import bot_loop

    monkeypatch.setattr(bot_loop.cfg, "THIN_MARKET_MODE", True, raising=False)
    monkeypatch.setattr(bot_loop.cfg, "MIN_EDGE_BPS", Decimal("3577"), raising=False)
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", ASSET_ID, raising=False)
    monkeypatch.setattr(
        bot_loop,
        "get_open_offers",
        lambda cat_asset_id=None: [
            {"side": "buy", "price_xch": "0.00004605"},
            {"side": "buy", "price_xch": "0.00004144"},
            {"side": "sell", "price_xch": "0.00017927"},
            {"side": "sell", "price_xch": "0.00019720"},
        ],
    )
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    plain_mid = Decimal("0.00011272")
    loop._last_quoted_price = {"buy": plain_mid, "sell": plain_mid}
    loop._ladder_grid_mid = {"buy": Decimal("0"), "sell": Decimal("0")}
    loop._ladder_anchor_plain_mid = {"buy": Decimal("0"), "sell": Decimal("0")}
    inner = Decimal("0.3577")
    side_mids = {
        "buy": Decimal("0.00004605") / (1 - inner),
        "sell": Decimal("0.00017927") / (1 + inner),
    }
    loop._get_thin_market_side_mid = lambda side: side_mids[side]

    loop._apply_thin_market_startup_baseline(plain_mid)

    # Untouched ladder: baseline equals the current side mid, so zero drift.
    assert loop._last_quoted_price == side_mids
    assert loop._ladder_grid_mid == side_mids
    assert loop._ladder_anchor_plain_mid == {"buy": plain_mid, "sell": plain_mid}

    # Outside ask moved 5% while the app was down: the stale ladder shows it.
    side_mids["sell"] *= Decimal("1.05")
    loop._apply_thin_market_startup_baseline(plain_mid)
    drift = (
        abs(side_mids["sell"] - loop._last_quoted_price["sell"])
        / loop._last_quoted_price["sell"]
    )
    assert drift > Decimal("0.045")


def test_restart_baseline_is_left_alone_outside_thin_market_mode(monkeypatch):
    import bot_loop

    monkeypatch.setattr(bot_loop.cfg, "THIN_MARKET_MODE", False, raising=False)
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    plain_mid = Decimal("0.1")
    loop._last_quoted_price = {"buy": plain_mid, "sell": plain_mid}

    loop._apply_thin_market_startup_baseline(plain_mid)

    assert loop._last_quoted_price == {"buy": plain_mid, "sell": plain_mid}
