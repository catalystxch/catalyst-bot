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
