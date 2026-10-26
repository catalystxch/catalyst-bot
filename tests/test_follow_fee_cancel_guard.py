"""Follow cancellations cannot fall through to unapproved wallet effects."""

import pytest

from test_offer_cancel_journal import (
    ASSET_ID,
    _fail_closed_network_guard,  # noqa: F401
    _seed_task7_created_offer,
    _stub_cancel_continuation_authority,
    isolated_database,  # noqa: F401
    offer_manager,
)


@pytest.mark.parametrize(
    "purpose",
    [
        f"follow:{'f' * 64}:normal_lifecycle",
        f"follow:{'f' * 64}:book_opportunity",
        f"follow:{'f' * 64}",
        f"follow:{'f' * 64}:unknown",
    ],
)
def test_follow_offer_without_durable_fee_authority_cannot_cancel(
    isolated_database, monkeypatch, purpose
):
    _seed_task7_created_offer(
        trade_id="a" * 64,
        coin_id="c" * 64,
        intent_seed="missing-follow-fee-authority",
        wallet_fingerprint_hash=offer_manager.mutation_gate.wallet_fingerprint_hash(
            123456789
        ),
        purpose=purpose,
    )

    effects = []

    def forbidden_effect(*_args, **_kwargs):
        effects.append(True)
        raise AssertionError("unapproved Follow wallet effect")

    _stub_cancel_continuation_authority(monkeypatch, effect=forbidden_effect)
    manager = offer_manager.OfferManager()
    with pytest.raises(ValueError, match="FEE_FOLLOW_AUTHORITY_REQUIRED"):
        manager.cancel_offers(["a" * 64], force_storm=True, reason="manual_cancel_all")
    assert effects == []


def test_follow_and_legacy_offers_cannot_share_cancel_batch(
    isolated_database, monkeypatch
):
    _seed_task7_created_offer(
        trade_id="a" * 64,
        coin_id="c" * 64,
        intent_seed="mixed-follow",
        purpose=f"follow:{'f' * 64}:normal_lifecycle",
    )
    _seed_task7_created_offer(
        trade_id="b" * 64,
        coin_id="d" * 64,
        intent_seed="mixed-legacy",
    )
    effects = []
    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        batch_effect=lambda *_args, **_kwargs: effects.append(True),
    )
    with pytest.raises(ValueError, match="FEE_FOLLOW_AUTHORITY_REQUIRED"):
        offer_manager.OfferManager().cancel_offers(
            ["a" * 64, "b" * 64], force_storm=True, reason="manual_cancel_all"
        )
    assert effects == []


def test_cancel_all_partitions_legacy_and_each_follow_run(monkeypatch):
    trade_ids = ["a" * 64, "b" * 64, "c" * 64, "d" * 64]
    purposes = {
        trade_ids[0]: "normal_lifecycle",
        trade_ids[1]: f"follow:{'e' * 64}:normal_lifecycle",
        trade_ids[2]: f"follow:{'f' * 64}:book_opportunity",
        trade_ids[3]: f"follow:{'e' * 64}:book_opportunity",
    }
    monkeypatch.setattr(
        offer_manager.database,
        "get_offer_intent_by_trade_id",
        lambda trade_id: {"purpose": purposes[trade_id]},
    )
    groups = offer_manager.OfferManager._cancel_fee_scope_groups(trade_ids)
    assert [group["trade_ids"] for group in groups] == [
        [trade_ids[0]],
        [trade_ids[1], trade_ids[3]],
        [trade_ids[2]],
    ]
    assert [group.get("follow_run_id") for group in groups] == [
        None,
        "e" * 64,
        "f" * 64,
    ]


def test_reviewed_follow_singleton_reaches_exact_plan_without_wallet_effect(
    isolated_database, monkeypatch
):
    run_id = "f" * 64
    _seed_task7_created_offer(
        trade_id="a" * 64,
        coin_id="c" * 64,
        intent_seed="reviewed-follow-singleton",
        purpose=f"follow:{run_id}:normal_lifecycle",
    )
    effects = []
    _stub_cancel_continuation_authority(
        monkeypatch,
        effect=lambda *_args, **_kwargs: effects.append(True),
        batch_effect=lambda *_args, **_kwargs: effects.append(True),
    )
    monkeypatch.setattr(
        offer_manager.database,
        "get_follow_run_identity",
        lambda exact_run: {"network": "mainnet"} if exact_run == run_id else None,
    )
    monkeypatch.setattr(
        offer_manager.database,
        "get_follow_cleanup_authority",
        lambda **_kwargs: {"ready": True},
    )
    seen = []

    def plan(_self, _members, exact_run, identity, recovery_action):
        seen.append((len(_members), exact_run, identity, recovery_action))
        raise ValueError("FOLLOW_PLAN_SENTINEL")

    monkeypatch.setattr(offer_manager.OfferManager, "_plan_follow_cancel", plan)
    with pytest.raises(ValueError, match="FOLLOW_PLAN_SENTINEL"):
        offer_manager.OfferManager().cancel_offers(
            ["a" * 64], force_storm=True, reason="cancel_all"
        )
    assert seen == [(1, run_id, {"network": "mainnet"}, "cancel_all")]
    assert effects == []
