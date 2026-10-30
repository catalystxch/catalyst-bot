from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from confidence_override import RunConsent, override_price_range, scope_digest

NOW = datetime(2026, 10, 25, 14, tzinfo=timezone.utc)
SCOPE = {
    "wallet": {"fingerprint": 123, "network": "mainnet"},
    "asset_id": "a" * 64,
    "follow_run_id": "f" * 64,
    "buy_limit": 24,
    "sell_limit": 24,
    "fee_cap_mojos": 50000000000,
}


def confidence(**changes):
    return SimpleNamespace(
        **(
            {
                "state": "RED",
                "data_valid": False,
                "reason_codes": (
                    "insufficient_bid_depth",
                    "insufficient_ask_depth",
                    "single_provider_dependency",
                ),
                "derived_at": NOW,
                "observed_bid": Decimal("0.00005"),
                "observed_ask": Decimal("0.00008"),
                "evidence_digests": ("b" * 64,),
                "manipulation_score": 0,
                "pending_movement_refreshes": 0,
                "provider_redundancy": 1,
            }
            | changes
        )
    )


def test_consent_bound_to_review_run_expiry_and_scope():
    permit = RunConsent.confirm(
        scope=SCOPE, reviewed_digest=scope_digest(SCOPE), duration_hours=48, now=NOW
    )
    assert permit.active(scope=SCOPE, now=NOW)
    assert not permit.active(scope=SCOPE, now=NOW + timedelta(hours=48))
    assert not permit.active(scope=SCOPE, now=NOW)


@pytest.mark.parametrize(
    "change",
    [{"buy_limit": 25}, {"asset_id": "c" * 64}, {"fee_cap_mojos": 50000000001}],
)
def test_scope_drift_revokes_even_if_changed_back(change):
    permit = RunConsent.confirm(
        scope=SCOPE, reviewed_digest=scope_digest(SCOPE), duration_hours=48, now=NOW
    )
    assert not permit.active(scope=SCOPE | change, now=NOW)
    assert not permit.active(scope=SCOPE, now=NOW)


@pytest.mark.parametrize("hours", [True, 0, -1, 169, "48"])
def test_duration_is_exact_and_bounded(hours):
    with pytest.raises(ValueError):
        RunConsent.confirm(
            scope=SCOPE,
            reviewed_digest=scope_digest(SCOPE),
            duration_hours=hours,
            now=NOW,
        )


def test_wrong_review_rejected():
    with pytest.raises(ValueError):
        RunConsent.confirm(
            scope=SCOPE, reviewed_digest="0" * 64, duration_hours=48, now=NOW
        )


def test_thin_range_is_fresh_observed_not_old_trusted():
    value = confidence(trusted_midpoint=Decimal("999"))
    assert override_price_range(
        value, now=NOW, valid_until=NOW + timedelta(seconds=20)
    ) == (Decimal("0.00005"), Decimal("0.000065"), Decimal("0.00008"))
    assert value.state == "RED" and value.data_valid is False


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_bid": None},
        {"observed_ask": Decimal("0.00004")},
        {"observed_bid": Decimal("NaN")},
        {"reason_codes": ("provider_price_conflict",)},
        {"reason_codes": ("one_sided_book",)},
        {"reason_codes": ("unknown_future_reason",)},
        {"manipulation_score": 1},
        {"pending_movement_refreshes": 1},
        {"evidence_digests": ()},
        {"provider_redundancy": 0},
        {"derived_at": NOW - timedelta(seconds=31)},
        {"derived_at": NOW + timedelta(seconds=3)},
    ],
)
def test_override_cannot_create_price_authority(changes):
    assert (
        override_price_range(
            confidence(**changes), now=NOW, valid_until=NOW + timedelta(seconds=20)
        )
        is None
    )


def test_expired_evidence_rejected():
    assert override_price_range(confidence(), now=NOW, valid_until=NOW) is None


def test_consented_hard_move_uses_fresh_book_inside_configured_price_band(monkeypatch):
    from config import cfg

    monkeypatch.setattr(cfg, "HARD_MIN_PRICE_XCH", Decimal("0.0000375"))
    monkeypatch.setattr(cfg, "HARD_MAX_PRICE_XCH", Decimal("0.00015"))
    observed = confidence(
        reason_codes=("hard_price_move_cap", "insufficient_bid_depth")
    )
    assert override_price_range(
        observed, now=NOW, valid_until=NOW + timedelta(seconds=20)
    ) == (Decimal("0.00005"), Decimal("0.000065"), Decimal("0.00008"))


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_bid": Decimal("0.00003")},
        {"observed_ask": Decimal("0.00016")},
        {"derived_at": NOW - timedelta(seconds=31)},
        {"reason_codes": ("hard_price_move_cap", "provider_price_conflict")},
    ],
)
def test_hard_move_consent_does_not_escape_price_or_evidence_bounds(
    monkeypatch, changes
):
    from config import cfg

    monkeypatch.setattr(cfg, "HARD_MIN_PRICE_XCH", Decimal("0.0000375"))
    monkeypatch.setattr(cfg, "HARD_MAX_PRICE_XCH", Decimal("0.00015"))
    observed = confidence(**({"reason_codes": ("hard_price_move_cap",)} | changes))
    assert (
        override_price_range(observed, now=NOW, valid_until=NOW + timedelta(seconds=20))
        is None
    )


def test_candidate_rechecks_consent_and_preserves_profitability():
    from confidence_override import ConsentedConfidence
    from offer_manager import assess_offer_book_candidate

    approved = [True]
    raw = confidence()
    view = ConsentedConfidence(
        raw,
        lambda: approved[0],
        (Decimal("0.00005"), Decimal("0.000065"), Decimal("0.00008")),
    )
    args = dict(
        side="buy",
        candidate_price=Decimal("0.00004"),
        size_xch=Decimal("1"),
        confidence=view,
        network_fee_xch=Decimal("0"),
        expected_cancel_requotes=1,
        minimum_profit_xch=Decimal("0"),
        now=NOW,
    )
    assert assess_offer_book_candidate(**args)["eligible"]
    assert not assess_offer_book_candidate(
        **(args | {"candidate_price": Decimal("0.00007")})
    )["eligible"]
    approved[0] = False
    assert not assess_offer_book_candidate(**args)["eligible"]
    assert raw.state == "RED" and raw.data_valid is False


def runtime_loop(monkeypatch):
    import bot_loop
    from bot_loop import BotLoop

    loop = BotLoop.__new__(BotLoop)
    loop._running = True
    monkeypatch.setattr(bot_loop.cfg, "MAX_ACTIVE_BUY_OFFERS", 24)
    monkeypatch.setattr(bot_loop.cfg, "MAX_ACTIVE_SELL_OFFERS", 24)
    loop._market_confidence_result = confidence()
    loop._market_confidence_valid_until = NOW + timedelta(seconds=20)
    loop._confidence_override_consent = RunConsent.confirm(
        scope=SCOPE, reviewed_digest=scope_digest(SCOPE), duration_hours=48, now=NOW
    )
    monkeypatch.setattr("confidence_override.current_scope", lambda: SCOPE)
    monkeypatch.setattr(
        bot_loop,
        "datetime",
        type("Clock", (datetime,), {"now": classmethod(lambda cls, tz=None: NOW)}),
    )
    return loop


def test_runtime_capacity_and_withdrawal_agree(monkeypatch):
    loop = runtime_loop(monkeypatch)
    assert loop._apply_market_follow_capacity({"buy": 24, "sell": 24}) == {
        "buy": 24,
        "sell": 24,
    }
    assert loop._apply_market_withdrawal(SimpleNamespace(cancel_tiers=())) == 0
    loop._confidence_override_consent.revoke()
    assert loop._apply_market_follow_capacity({"buy": 24, "sell": 24}) == {
        "buy": 0,
        "sell": 0,
    }


def test_effective_candidate_view_keeps_raw_red(monkeypatch):
    loop = runtime_loop(monkeypatch)
    effective = loop._effective_market_confidence()
    assert effective.data_valid is True and effective.state == "RED"
    assert effective.trusted_midpoint == Decimal("0.000065")
    assert loop._market_confidence_result.data_valid is False
    loop._confidence_override_consent.revoke()
    assert effective.data_valid is False


def test_candidate_batch_defers_expensive_scope_check_until_effect(monkeypatch):
    loop = runtime_loop(monkeypatch)
    checks = []

    def checked_scope():
        checks.append(True)
        return SCOPE

    monkeypatch.setattr("confidence_override.current_scope", checked_scope)
    effective = loop._effective_market_confidence()
    initial_checks = len(checks)
    assert initial_checks > 0
    for _ in range(48):
        assert effective.data_valid is True
    assert len(checks) == initial_checks
    assert effective.dispatch_allowed() is True
    assert len(checks) > initial_checks
    loop._confidence_override_consent.revoke()
    assert effective.data_valid is False
    assert effective.dispatch_allowed() is False


def test_review_requires_exact_confirmation_and_cannot_be_replayed(monkeypatch):
    from confidence_override import prepare_review, confirm_review

    monkeypatch.setattr("confidence_override.current_scope", lambda: SCOPE)
    bot = SimpleNamespace(is_running=lambda: False)
    review = prepare_review(bot, duration_hours=48, now=NOW)
    with pytest.raises(ValueError):
        confirm_review(
            bot, {"review_id": review["review_id"], "accepted": False}, now=NOW
        )
    review = prepare_review(bot, duration_hours=48, now=NOW)
    permit = confirm_review(
        bot, {"review_id": review["review_id"], "accepted": True}, now=NOW
    )
    assert permit.active(scope=SCOPE, now=NOW)
    with pytest.raises(ValueError):
        confirm_review(
            bot, {"review_id": review["review_id"], "accepted": True}, now=NOW
        )


def test_review_expiry_or_changed_scope_blocks_confirmation(monkeypatch):
    from confidence_override import prepare_review, confirm_review

    monkeypatch.setattr("confidence_override.current_scope", lambda: SCOPE)
    bot = SimpleNamespace(is_running=lambda: False)
    review = prepare_review(bot, duration_hours=48, now=NOW)
    with pytest.raises(ValueError):
        confirm_review(
            bot,
            {"review_id": review["review_id"], "accepted": True},
            now=NOW + timedelta(seconds=61),
        )
    review = prepare_review(bot, duration_hours=48, now=NOW)
    monkeypatch.setattr(
        "confidence_override.current_scope", lambda: SCOPE | {"buy_limit": 25}
    )
    with pytest.raises(ValueError):
        confirm_review(
            bot, {"review_id": review["review_id"], "accepted": True}, now=NOW
        )


def test_native_start_review_does_not_start_bot(monkeypatch):
    from flask import Flask
    import api_server
    from blueprints import bot as routes
    import confidence_override

    bot = SimpleNamespace(is_running=lambda: False)
    server = SimpleNamespace(
        bot=bot,
        cfg=SimpleNamespace(),
        _cancel_all_state_lock=__import__("threading").RLock(),
        _cancel_all_state={"running": False},
        _cancel_all_thread=None,
    )
    monkeypatch.setattr(routes, "_api_server", lambda: server)
    monkeypatch.setattr(confidence_override, "current_scope", lambda: SCOPE)
    app = Flask(__name__)
    with app.test_request_context(
        "/api/bot/start",
        method="POST",
        json={"review_confidence_override": True, "duration_hours": 48},
    ):
        response = routes.api_bot_start()
        assert response.get_json()["confidence_override_review"]["scope"] == SCOPE
        assert response.get_json()["success"] is False
    assert bot._confidence_override_review


def test_native_bridge_forwards_exact_override_confirmation(monkeypatch):
    import api_server
    from app_bridge import AppBridge

    payloads = []
    monkeypatch.setattr(
        api_server,
        "api_bot_start",
        lambda: (
            payloads.append(__import__("flask").request.get_json())
            or {"success": False}
        ),
    )
    method = AppBridge.start_bot
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    body = {"confidence_override": {"review_id": "abc", "accepted": True}}
    method(SimpleNamespace(), body)
    assert payloads == [body]


def test_phase_permission_preserves_freshness_and_continuity(monkeypatch):
    from bot_loop import BotLoop
    import confidence_override as policy

    current = datetime.now(timezone.utc)
    loop = BotLoop.__new__(BotLoop)
    loop._running = True
    loop._market_runtime_required = True
    loop._market_confidence_result = confidence(derived_at=current)
    loop._market_confidence_valid_until = current + timedelta(seconds=20)
    loop._market_degraded_decision = SimpleNamespace(
        can_create=False, can_requote=False
    )
    loop._confidence_override_consent = RunConsent.confirm(
        scope=SCOPE, reviewed_digest=scope_digest(SCOPE), duration_hours=48, now=current
    )
    monkeypatch.setattr(policy, "current_scope", lambda: SCOPE)
    for name in (
        "_runtime_recovery_monotonic",
        "_runtime_recovery_wall_clock",
        "_runtime_recovery_gap_seconds",
        "_runtime_recovery_skew_seconds",
    ):
        setattr(loop, name, True)
    loop._runtime_recovery_cycle_boundary = lambda: True
    assert loop._enter_runtime_effect_phase("create")
    assert loop._enter_runtime_effect_phase("requote")
    assert loop._enter_runtime_effect_phase("publication")
    assert loop._background_publication_snapshot_ready()
    loop._runtime_recovery_cycle_boundary = lambda: False
    assert not loop._enter_runtime_effect_phase("create")
    loop._runtime_recovery_cycle_boundary = lambda: True
    loop._confidence_override_consent.revoke()
    assert not loop._enter_runtime_effect_phase("publication")
    assert not loop._background_publication_snapshot_ready()


def test_stopped_bot_cannot_reuse_old_consent(monkeypatch):
    loop = runtime_loop(monkeypatch)
    loop._running = False
    assert not loop._confidence_override_active()


def test_review_clock_rollback_does_not_extend_authority(monkeypatch):
    from confidence_override import prepare_review, confirm_review

    monkeypatch.setattr("confidence_override.current_scope", lambda: SCOPE)
    bot = SimpleNamespace(is_running=lambda: False)
    review = prepare_review(bot, now=NOW)
    with pytest.raises(ValueError):
        confirm_review(
            bot,
            {"review_id": review["review_id"], "accepted": True},
            now=NOW - timedelta(days=1),
        )


def test_scope_read_cannot_extend_market_snapshot_deadline(monkeypatch):
    import bot_loop

    loop = runtime_loop(monkeypatch)
    clock = [NOW]
    monkeypatch.setattr(
        bot_loop,
        "datetime",
        type("Clock", (datetime,), {"now": classmethod(lambda cls, tz=None: clock[0])}),
    )
    loop._market_confidence_valid_until = NOW + timedelta(seconds=1)

    def delayed_scope():
        clock[0] = NOW + timedelta(seconds=2)
        return SCOPE

    monkeypatch.setattr("confidence_override.current_scope", delayed_scope)
    assert not loop._confidence_override_active()


def test_thin_depth_move_requires_distinct_persistent_fresh_observations():
    permit = RunConsent.confirm(
        scope=SCOPE, reviewed_digest=scope_digest(SCOPE), duration_hours=48, now=NOW
    )
    raw = confidence(
        reason_codes=("insufficient_ask_depth", "material_move_pending_confirmation"),
        derived_thresholds={"persistence_refreshes": 2, "persistence_jitter_bps": 100},
    )
    assert (
        permit.price_range(raw, now=NOW, valid_until=NOW + timedelta(seconds=20))
        is None
    )
    # Re-reading the same observation cannot manufacture confirmation.
    assert (
        permit.price_range(raw, now=NOW, valid_until=NOW + timedelta(seconds=20))
        is None
    )
    raw.derived_at = NOW + timedelta(seconds=5)
    prices = permit.price_range(
        raw, now=raw.derived_at, valid_until=raw.derived_at + timedelta(seconds=20)
    )
    assert prices == (Decimal("0.00005"), Decimal("0.000065"), Decimal("0.00008"))
    assert raw.state == "RED" and raw.data_valid is False
    raw.observed_bid, raw.observed_ask = Decimal("0.00006"), Decimal("0.00009")
    raw.derived_at += timedelta(seconds=5)
    assert (
        permit.price_range(
            raw, now=raw.derived_at, valid_until=raw.derived_at + timedelta(seconds=20)
        )
        is None
    )


@pytest.mark.parametrize(
    "reasons",
    [
        ("material_move_pending_confirmation",),
        (
            "insufficient_ask_depth",
            "material_move_pending_confirmation",
            "hard_price_move_cap",
        ),
        (
            "insufficient_ask_depth",
            "material_move_pending_confirmation",
            "provider_price_conflict",
        ),
    ],
)
def test_price_persistence_cannot_override_other_price_failures(reasons):
    permit = RunConsent.confirm(
        scope=SCOPE, reviewed_digest=scope_digest(SCOPE), duration_hours=48, now=NOW
    )
    raw = confidence(
        reason_codes=reasons,
        derived_thresholds={"persistence_refreshes": 2, "persistence_jitter_bps": 100},
    )
    for second in range(5):
        raw.derived_at = NOW + timedelta(seconds=second)
        assert (
            permit.price_range(
                raw,
                now=raw.derived_at,
                valid_until=raw.derived_at + timedelta(seconds=20),
            )
            is None
        )


def test_persistent_price_jitter_does_not_lose_confirmation_on_same_snapshot():
    permit = RunConsent.confirm(
        scope=SCOPE, reviewed_digest=scope_digest(SCOPE), duration_hours=48, now=NOW
    )
    raw = confidence(
        reason_codes=("insufficient_ask_depth", "material_move_pending_confirmation"),
        derived_thresholds={"persistence_refreshes": 2, "persistence_jitter_bps": 100},
    )
    assert (
        permit.price_range(raw, now=NOW, valid_until=NOW + timedelta(seconds=20))
        is None
    )
    raw.derived_at += timedelta(seconds=5)
    raw.observed_ask = Decimal("0.0000801")
    assert (
        permit.price_range(
            raw, now=raw.derived_at, valid_until=raw.derived_at + timedelta(seconds=20)
        )
        is not None
    )
    assert (
        permit.price_range(
            raw, now=raw.derived_at, valid_until=raw.derived_at + timedelta(seconds=20)
        )
        is not None
    )


def test_real_engine_thin_move_eventually_confirms_without_ever_marking_green():
    from market_confidence import MarketConfidenceEngine
    from providers.models import (
        ProviderObservation,
        Capability,
        ObservationQuality,
        canonical_evidence_json,
        evidence_digest,
    )

    engine = MarketConfidenceEngine(risk_preset="balanced")

    def evaluate(at, bid, ask, amount):
        payload = {
            "bids": [{"offer_id": "buy", "price": bid, "amount_mojos": amount}],
            "asks": [{"offer_id": "sell", "price": ask, "amount_mojos": amount}],
        }
        return engine.evaluate(
            observations=(
                ProviderObservation(
                    provider_id="dexie",
                    capability=Capability.ORDER_BOOK,
                    observed_at=at,
                    source_time=None,
                    source_height=None,
                    fresh_until=at + timedelta(seconds=20),
                    identity_keys=("b8" * 32, "buy", "sell"),
                    quality=ObservationQuality.VALID,
                    reason_codes=(),
                    raw_evidence_json=canonical_evidence_json(
                        {"asset_id": "b8" * 32, **payload}
                    ),
                    payload_sha256=evidence_digest(
                        canonical_evidence_json({"asset_id": "b8" * 32, **payload})
                    ),
                ),
            ),
            own_offer_identities=frozenset(),
            configured_offer_size_mojos=1000000000000,
            now=at,
        )

    initial = evaluate(NOW, "0.00009", "0.00011", 3000000000000)
    assert initial.data_valid and initial.trusted_midpoint == Decimal("0.0001")
    permit = RunConsent.confirm(
        scope=SCOPE, reviewed_digest=scope_digest(SCOPE), duration_hours=48, now=NOW
    )
    first_at = NOW + timedelta(seconds=5)
    first = evaluate(first_at, "0.000095", "0.000115", 500000000000)
    assert (
        first.state == "RED"
        and "material_move_pending_confirmation" in first.reason_codes
    )
    assert first.pending_movement_refreshes == 0
    assert (
        permit.price_range(
            first, now=first_at, valid_until=first_at + timedelta(seconds=20)
        )
        is None
    )
    second_at = NOW + timedelta(seconds=10)
    second = evaluate(second_at, "0.000095", "0.000115", 500000000000)
    assert second.state == "RED" and second.data_valid is False
    assert second.trusted_midpoint == Decimal("0.0001")
    assert permit.price_range(
        second, now=second_at, valid_until=second_at + timedelta(seconds=20)
    ) == (Decimal("0.000095"), Decimal("0.000105"), Decimal("0.000115"))


def test_risk_consent_cannot_extend_financial_run_expiry():
    scope = SCOPE | {
        "run_expires_at_epoch": int((NOW + timedelta(minutes=5)).timestamp())
    }
    permit = RunConsent.confirm(
        scope=scope, reviewed_digest=scope_digest(scope), duration_hours=48, now=NOW
    )
    assert permit.expires_at == NOW + timedelta(minutes=5)


def test_continuous_financial_run_keeps_risk_override_bounded():
    from follow_run_terms import CONTINUOUS_RUN_EXPIRY

    scope = SCOPE | {"run_expires_at_epoch": CONTINUOUS_RUN_EXPIRY}
    permit = RunConsent.confirm(
        scope=scope, reviewed_digest=scope_digest(scope), duration_hours=48, now=NOW
    )
    assert permit.expires_at == NOW + timedelta(hours=48)


def test_pending_financial_effect_temporarily_blocks_matching_risk_consent(monkeypatch):
    loop = runtime_loop(monkeypatch)

    def pending():
        raise ValueError("CONFIDENCE_OVERRIDE_OPERATION_PENDING")

    monkeypatch.setattr("confidence_override.current_scope", pending)
    assert not loop._confidence_override_active()
    assert loop._confidence_override_consent.revoked is False
    monkeypatch.setattr("confidence_override.current_scope", lambda: SCOPE)
    assert loop._confidence_override_active()


@pytest.mark.parametrize(
    "suffix,expected",
    [
        ("normal_lifecycle", True),
        ("book_opportunity", True),
        ("", False),
        ("legacy", False),
    ],
)
def test_override_publication_requires_durable_exact_run(monkeypatch, suffix, expected):
    import bot_loop

    loop = runtime_loop(monkeypatch)
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", SCOPE["asset_id"])
    purpose = "follow:" + "f" * 64 + (":" + suffix if suffix else "")
    intent = dict(
        purpose=purpose,
        asset_id=SCOPE["asset_id"],
        terminal_at=None,
        lifecycle_state="created",
        sage_trade_id="c" * 64,
    )
    monkeypatch.setattr(bot_loop.database, "get_offer_intent", lambda _: intent)
    assert (
        loop._override_authorizes_publication({"intent_id": "i", "purpose": "spoofed"})
        is expected
    )
    intent["purpose"] = "follow:" + "e" * 64 + ":normal_lifecycle"
    assert not loop._override_authorizes_publication({"intent_id": "i"})
    intent["purpose"] = purpose
    loop._confidence_override_consent.revoke()
    assert not loop._override_authorizes_publication({"intent_id": "i"})


def test_override_withdrawal_protection_is_exact_and_fail_closed(monkeypatch):
    import bot_loop

    loop = runtime_loop(monkeypatch)
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", SCOPE["asset_id"])
    rows = [
        dict(
            purpose=purpose,
            asset_id=SCOPE["asset_id"],
            terminal_at=None,
            lifecycle_state="visible",
            sage_trade_id=str(i) * 64,
        )
        for i, purpose in enumerate(
            [
                "follow:" + "f" * 64 + ":normal_lifecycle",
                "follow:" + "e" * 64 + ":normal_lifecycle",
                "normal_lifecycle",
            ],
            1,
        )
    ]
    monkeypatch.setattr(
        bot_loop.database, "get_offer_intents_for_registry", lambda: rows
    )
    assert loop._override_protected_trade_ids() == {"1" * 64}
    rows[0]["terminal_at"] = "done"
    assert loop._override_protected_trade_ids() == set()

    def fail():
        raise RuntimeError("unavailable")

    monkeypatch.setattr(bot_loop.database, "get_offer_intents_for_registry", fail)
    assert loop._override_protected_trade_ids() == set()


def test_publication_boundary_does_not_waive_legacy_claim(monkeypatch):
    import bot_loop

    loop = runtime_loop(monkeypatch)
    loop._market_runtime_required = True
    loop._market_degraded_decision = SimpleNamespace(can_create=False)
    monkeypatch.setattr(loop, "_enter_runtime_effect_phase", lambda _: True)
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", SCOPE["asset_id"])
    intent = dict(
        purpose="normal_lifecycle",
        asset_id=SCOPE["asset_id"],
        terminal_at=None,
        lifecycle_state="visible",
        sage_trade_id="c" * 64,
    )
    monkeypatch.setattr(bot_loop.database, "get_offer_intent", lambda _: intent)
    assert not loop._authorize_publication_claim({"intent_id": "i"})
    intent["purpose"] = "follow:" + "f" * 64 + ":normal_lifecycle"
    assert loop._authorize_publication_claim({"intent_id": "i"})
    loop._market_degraded_decision.can_create = True
    intent["purpose"] = "normal_lifecycle"
    assert loop._authorize_publication_claim({"intent_id": "i"})


def test_withdrawal_keeps_other_runs_subject_to_normal_policy(monkeypatch):
    import bot_loop

    loop = runtime_loop(monkeypatch)
    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", SCOPE["asset_id"])
    monkeypatch.setattr(loop, "_bootstrap_campaign_context", lambda: {"active": False})
    rows = [
        dict(
            purpose=purpose,
            asset_id=SCOPE["asset_id"],
            terminal_at=None,
            lifecycle_state="visible",
            sage_trade_id=str(i) * 64,
        )
        for i, purpose in enumerate(
            [
                "follow:" + "f" * 64 + ":normal_lifecycle",
                "follow:" + "e" * 64 + ":normal_lifecycle",
                "normal_lifecycle",
            ],
            1,
        )
    ]
    monkeypatch.setattr(
        bot_loop.database, "get_offer_intents_for_registry", lambda: rows
    )
    monkeypatch.setattr(
        bot_loop,
        "get_open_offers",
        lambda **_: [dict(trade_id=str(i) * 64, tier="inner") for i in range(1, 4)],
    )
    selected = []
    loop.offer_manager = SimpleNamespace(
        cancel_offers=lambda ids, **_: selected.extend(ids) or {}
    )
    monkeypatch.setattr(loop, "_enter_runtime_effect_phase", lambda _: True)
    monkeypatch.setattr(bot_loop, "log_event", lambda *a, **k: None)
    loop._apply_market_withdrawal(SimpleNamespace(cancel_tiers=("inner",)))
    assert selected == ["2" * 64, "3" * 64]
