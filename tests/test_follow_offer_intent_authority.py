"""Follow-labelled offer intents retain their reviewed run at every boundary."""

from datetime import datetime, timezone

import pytest

import offer_manager
import confidence_override


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
