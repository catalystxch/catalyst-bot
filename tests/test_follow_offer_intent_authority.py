"""Follow-labelled offer intents retain their reviewed run at every boundary."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

import offer_manager
import confidence_override
import database


RUN_ID = "a" * 64
ASSET_ID = "b" * 64
NOW = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)


def _scope():
    return {
        "follow_run_id": RUN_ID,
        "identity": {"asset_id": ASSET_ID},
        "run_expires_at_epoch": int(NOW.timestamp()) + 48 * 3600,
    }


def test_follow_purpose_requires_the_exact_active_run(monkeypatch):
    monkeypatch.setattr(confidence_override, "current_scope", _scope)
    result = offer_manager.require_active_follow_intent_authority(
        purpose=f"follow:{RUN_ID}:normal_lifecycle",
        asset_id=ASSET_ID,
        side="buy",
        offer_max_time=int(NOW.timestamp()) + 3600,
        now=NOW,
    )
    assert result == {"run_id": RUN_ID, "classification": "normal_lifecycle"}


def test_unscoped_follow_creation_is_fenced_while_run_exists(monkeypatch):
    seen = []

    def marker(*, asset_id, now_epoch):
        seen.append((asset_id, now_epoch))
        return {"run_id": RUN_ID, "stopped": True}

    monkeypatch.setattr(database, "get_unexpired_follow_run_marker", marker)
    with pytest.raises(ValueError, match="FOLLOW_PURPOSE_REQUIRED"):
        offer_manager.require_active_follow_intent_authority(
            purpose="normal_lifecycle",
            asset_id=ASSET_ID,
            side="buy",
            offer_max_time=int(NOW.timestamp()) + 3600,
            now=NOW,
        )
    assert seen == [(ASSET_ID, int(NOW.timestamp()))]


def test_direct_legacy_wallet_path_cannot_bypass_follow_run(monkeypatch):
    monkeypatch.setattr(
        offer_manager.wallet, "get_wallet_backend_authority", lambda: "chia"
    )
    monkeypatch.setattr(
        database,
        "get_unexpired_follow_run_marker",
        lambda **_kwargs: {"run_id": RUN_ID},
    )
    monkeypatch.setattr(
        offer_manager,
        "create_offer",
        lambda *_args, **_kwargs: pytest.fail("wallet effect reached"),
    )
    result = offer_manager.OfferManager()._create_offer_with_retry_inner(
        {"1": -1000, "2": 2000},
        coin_ids_enabled=False,
        creation_context=None,
    )
    assert result["reason"] == "FOLLOW_PURPOSE_REQUIRED"
    assert result["_catalyst_effect_attempted"] is False


def test_direct_sage_producer_without_context_cannot_inherit_follow_run(monkeypatch):
    monkeypatch.setattr(offer_manager.cfg, "CAT_ASSET_ID", ASSET_ID)
    monkeypatch.setattr(
        database,
        "get_unexpired_follow_run_marker",
        lambda **_kwargs: {"run_id": RUN_ID},
    )
    with pytest.raises(ValueError, match="FOLLOW_PURPOSE_REQUIRED"):
        offer_manager.OfferManager()._build_canonical_creation_intent(
            offer_dict={"1": -1000, "2": 2000},
            selected_coin_id="d" * 64,
            preferred_tier="sniper",
            creation_context=None,
            expiry_seconds=3600,
            expiry_offset=0,
            stagger_seconds=0,
            offer_max_time=int(NOW.timestamp()) + 3600,
            min_coin_hint=None,
            max_coin_hint=None,
        )


@pytest.mark.parametrize(
    "purpose,asset_id,side,expiry",
    [
        ("follow:" + "c" * 64 + ":normal_lifecycle", ASSET_ID, "buy", 1),
        ("follow:" + RUN_ID + ":unknown", ASSET_ID, "buy", 1),
        ("follow:" + RUN_ID + ":book_opportunity", "c" * 64, "sell", 1),
        ("follow:" + RUN_ID + ":normal_lifecycle", ASSET_ID, "other", 1),
        ("follow:" + RUN_ID + ":normal_lifecycle", ASSET_ID, "buy", 49 * 3600),
    ],
)
def test_follow_purpose_rejects_mismatched_or_unbounded_intent(
    monkeypatch, purpose, asset_id, side, expiry
):
    monkeypatch.setattr(confidence_override, "current_scope", _scope)
    with pytest.raises(ValueError, match="FOLLOW_"):
        offer_manager.require_active_follow_intent_authority(
            purpose=purpose,
            asset_id=asset_id,
            side=side,
            offer_max_time=int(NOW.timestamp()) + expiry,
            now=NOW,
        )


def test_follow_purpose_fails_when_durable_authority_is_missing(monkeypatch):
    monkeypatch.setattr(
        confidence_override,
        "current_scope",
        lambda: (_ for _ in ()).throw(ValueError("FOLLOW_FEE_AUTHORITY_REQUIRED")),
    )
    with pytest.raises(ValueError, match="FOLLOW_FEE_AUTHORITY_REQUIRED"):
        offer_manager.require_active_follow_intent_authority(
            purpose=f"follow:{RUN_ID}:book_opportunity",
            asset_id=ASSET_ID,
            side="sell",
            offer_max_time=int(NOW.timestamp()) + 3600,
            now=NOW,
        )


def test_follow_intent_cannot_be_canonicalized_after_authority_is_revoked(monkeypatch):
    monkeypatch.setattr(
        confidence_override,
        "current_scope",
        lambda: (_ for _ in ()).throw(ValueError("FOLLOW_FEE_AUTHORITY_REQUIRED")),
    )
    with pytest.raises(ValueError, match="FOLLOW_FEE_AUTHORITY_REQUIRED"):
        offer_manager.OfferManager()._build_canonical_creation_intent(
            offer_dict={"1": -1000, "2": 2000},
            selected_coin_id="d" * 64,
            preferred_tier="inner",
            creation_context={
                "purpose": f"follow:{RUN_ID}:normal_lifecycle",
                "asset_id": ASSET_ID,
                "side": "buy",
            },
            expiry_seconds=3600,
            expiry_offset=0,
            stagger_seconds=0,
            offer_max_time=int(NOW.timestamp()) + 3600,
            min_coin_hint=None,
            max_coin_hint=None,
        )


def test_follow_ladder_labels_created_offer_with_exact_run(monkeypatch):
    seen = []

    def capture(_self, _offer_dict, **kwargs):
        seen.append(kwargs["creation_context"]["purpose"])
        return {"success": False, "error": "test stop before wallet"}

    monkeypatch.setattr(offer_manager.OfferManager, "create_offer_with_retry", capture)
    manager = offer_manager.OfferManager()
    manager.create_ladder(
        mid_price=Decimal("0.001"),
        side="buy",
        num_offers=1,
        cat_asset_id=ASSET_ID,
        cat_wallet_id=2,
        follow_run_id=RUN_ID,
    )
    assert seen == [f"follow:{RUN_ID}:normal_lifecycle"]


def test_follow_book_opportunity_retains_its_classification(monkeypatch):
    seen = []

    def capture(_self, _offer_dict, **kwargs):
        seen.append(kwargs["creation_context"]["purpose"])
        return {"success": False, "error": "test stop before wallet"}

    monkeypatch.setattr(offer_manager.OfferManager, "create_offer_with_retry", capture)
    monkeypatch.setattr(
        offer_manager,
        "assess_offer_book_candidate",
        lambda **_kwargs: {
            "eligible": True,
            "improves_book": True,
            "evidence_digest": "c" * 64,
        },
    )
    monkeypatch.setattr(
        database, "claim_offer_book_improvement", lambda **_kwargs: True
    )
    monkeypatch.setattr(
        offer_manager,
        "book_opportunity_size_cap",
        lambda **_kwargs: Decimal("0.25"),
    )
    offer_manager.OfferManager().create_ladder(
        mid_price=Decimal("0.001"),
        side="sell",
        num_offers=1,
        cat_asset_id=ASSET_ID,
        cat_wallet_id=2,
        market_confidence=object(),
        follow_run_id=RUN_ID,
    )
    assert seen == [f"follow:{RUN_ID}:book_opportunity"]


def test_consented_red_follow_ladder_dispatches_only_passive_quotes(monkeypatch):
    from types import SimpleNamespace

    from confidence_override import ConsentedConfidence

    bid = Decimal("0.00005025")
    ask = Decimal("0.00012000")
    observed = datetime.now(timezone.utc)
    raw = SimpleNamespace(
        state="RED",
        derived_at=observed,
        evidence_digests=("a" * 64,),
    )
    scoped = ConsentedConfidence(
        raw,
        lambda: True,
        (bid, (bid + ask) / Decimal(2), ask),
    )
    monkeypatch.setattr(offer_manager.cfg, "TIER_ENABLED", False)
    monkeypatch.setattr(offer_manager.cfg, "DEFAULT_TRADE_XCH", Decimal("0.1"))
    monkeypatch.setattr(offer_manager.cfg, "HARD_MIN_PRICE_XCH", Decimal("0.0000375"))
    monkeypatch.setattr(offer_manager.cfg, "HARD_MAX_PRICE_XCH", Decimal("0.00015"))
    seen = []

    def capture(_self, offer_dict, **kwargs):
        seen.append((offer_dict, kwargs["creation_context"]["purpose"]))
        return {"success": False, "error": "test stop before wallet"}

    monkeypatch.setattr(offer_manager.OfferManager, "create_offer_with_retry", capture)
    manager = offer_manager.OfferManager()
    for side in ("buy", "sell"):
        manager.create_ladder(
            mid_price=Decimal("0.000075"),
            side=side,
            num_offers=24,
            total_slots=24,
            trade_size_xch=Decimal("0.1"),
            spread_fraction=Decimal("0.126"),
            cat_asset_id=ASSET_ID,
            cat_wallet_id=2,
            market_confidence=scoped,
            follow_run_id=RUN_ID,
        )
    assert len(seen) == 48
    assert all(purpose == f"follow:{RUN_ID}:normal_lifecycle" for _, purpose in seen)
    buy_prices = [
        offer_manager.mojos_to_xch(-offer["1"])
        / offer_manager.mojos_to_cat(offer["2"], offer_manager.cfg.CAT_DECIMALS)
        for offer, _ in seen
        if offer["1"] < 0
    ]
    sell_prices = [
        offer_manager.mojos_to_xch(offer["1"])
        / offer_manager.mojos_to_cat(-offer["2"], offer_manager.cfg.CAT_DECIMALS)
        for offer, _ in seen
        if offer["2"] < 0
    ]
    assert len(buy_prices) == len(sell_prices) == 24
    assert all(Decimal("0.0000375") <= price <= bid for price in buy_prices)
    assert all(ask <= price <= Decimal("0.00015") for price in sell_prices)


def test_red_quote_is_rejected_when_fresh_bid_falls_before_dispatch(monkeypatch):
    from types import SimpleNamespace

    from confidence_override import ConsentedConfidence

    observed = datetime.now(timezone.utc)
    raw = SimpleNamespace(
        state="RED", derived_at=observed, evidence_digests=("a" * 64,)
    )
    first_bid = Decimal("0.00005025")
    ask = Decimal("0.00012000")
    initial = ConsentedConfidence(
        raw, lambda: True, (first_bid, (first_bid + ask) / Decimal(2), ask)
    )
    lower_bid = Decimal("0.00004000")
    changed = ConsentedConfidence(
        raw, lambda: True, (lower_bid, (lower_bid + ask) / Decimal(2), ask)
    )
    reads = []

    def fresh_view():
        reads.append(1)
        return initial if len(reads) <= 3 else changed

    scoped = ConsentedConfidence(
        raw,
        lambda: True,
        (first_bid, (first_bid + ask) / Decimal(2), ask),
        current_view=fresh_view,
    )
    monkeypatch.setattr(offer_manager.cfg, "TIER_ENABLED", False)
    monkeypatch.setattr(offer_manager.cfg, "HARD_MIN_PRICE_XCH", Decimal("0.0000375"))
    monkeypatch.setattr(offer_manager.cfg, "HARD_MAX_PRICE_XCH", Decimal("0.00015"))
    monkeypatch.setattr(
        offer_manager.OfferManager,
        "create_offer_with_retry",
        lambda *_args, **_kwargs: pytest.fail("wallet dispatch reached"),
    )
    monkeypatch.setattr(
        database,
        "claim_offer_book_improvement",
        lambda **_kwargs: pytest.fail("improvement claim reached"),
    )
    offer_manager.OfferManager().create_ladder(
        mid_price=Decimal("0.000075"),
        side="buy",
        num_offers=1,
        total_slots=24,
        trade_size_xch=Decimal("0.1"),
        spread_fraction=Decimal("0.126"),
        cat_asset_id=ASSET_ID,
        cat_wallet_id=2,
        market_confidence=scoped,
        follow_run_id=RUN_ID,
    )
    assert len(reads) >= 4
