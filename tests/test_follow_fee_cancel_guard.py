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
