"""A failed requote must remain eligible for a prompt retry."""

from decimal import Decimal
from types import SimpleNamespace

import database
import offer_manager


def test_cold_start_without_created_offers_does_not_start_cooldown(monkeypatch):
    manager = offer_manager.OfferManager()
    manager._last_requote_time["buy"] = 0.0
    monkeypatch.setattr(offer_manager, "get_open_offers", lambda **_kwargs: [])
    monkeypatch.setattr(
        manager, "_advance_pending_refresh_lineage", lambda *_args: None
    )
    monkeypatch.setattr(
        manager,
        "_sort_open_offers_for_requote",
        lambda offers, *_args, **_kwargs: offers,
    )
    monkeypatch.setattr(manager, "create_ladder", lambda *_args, **_kwargs: [])

    result = manager.requote_side("buy", Decimal("0.001"))

    assert result["offers"] == []
    assert result["fully_replaced"] is False
    assert manager._last_requote_time["buy"] == 0.0


def test_cold_start_with_created_offer_starts_cooldown(monkeypatch):
    manager = offer_manager.OfferManager()
    manager._last_requote_time["buy"] = 0.0
    monkeypatch.setattr(offer_manager, "get_open_offers", lambda **_kwargs: [])
    monkeypatch.setattr(
        manager, "_advance_pending_refresh_lineage", lambda *_args: None
    )
    monkeypatch.setattr(
        manager,
        "_sort_open_offers_for_requote",
        lambda offers, *_args, **_kwargs: offers,
    )
    monkeypatch.setattr(
        manager, "create_ladder", lambda *_args, **_kwargs: [{"trade_id": "created"}]
    )

    result = manager.requote_side("buy", Decimal("0.001"))

    assert result["offers"] == [{"trade_id": "created"}]
    assert result["fully_replaced"] is True
    assert manager._last_requote_time["buy"] > 0.0


def test_staged_refresh_without_created_child_does_not_start_cooldown(monkeypatch):
    manager = offer_manager.OfferManager()
    manager._last_requote_time["buy"] = 0.0
    old_offer = {"trade_id": "old", "tier": "inner"}
    monkeypatch.setattr(offer_manager, "get_open_offers", lambda **_kwargs: [old_offer])
    monkeypatch.setattr(
        manager, "_advance_pending_refresh_lineage", lambda *_args: None
    )
    monkeypatch.setattr(
        manager,
        "_sort_open_offers_for_requote",
        lambda offers, *_args, **_kwargs: offers,
    )
    monkeypatch.setattr(
        manager,
        "_collect_staged_refresh_parents",
        lambda *_args: (
            {
                "parent": (
                    old_offer,
                    {"intent_id": "parent", "slot_key": "s", "generation": 0},
                    1,
                )
            },
            None,
        ),
    )
    monkeypatch.setattr(
        database,
        "get_free_coins",
        lambda _wallet_type: [{"designation": "tier_spare", "assigned_tier": "inner"}],
    )
    monkeypatch.setattr(
        offer_manager, "_has_authoritative_coin_purpose", lambda _coin: True
    )
    monkeypatch.setattr(
        manager,
        "plan_staged_refresh",
        lambda *_args, **_kwargs: SimpleNamespace(
            mode="stage", stage_parent_ids=["parent"]
        ),
    )
    monkeypatch.setattr(manager, "create_ladder", lambda *_args, **_kwargs: [])

    result = manager.requote_side("buy", Decimal("0.001"))

    assert result["offers"] == []
    assert result["replaced_count"] == 0
    assert manager._last_requote_time["buy"] == 0.0
