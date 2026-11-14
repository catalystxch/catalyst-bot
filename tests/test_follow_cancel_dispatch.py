"""The only Follow wallet route requires a durable hold and final callback."""

from types import SimpleNamespace

import database
import offer_manager
import wallet
from cancel_outcomes import (
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    cancellation_result,
)


def test_follow_batch_holds_before_effect_and_rechecks_at_wallet(monkeypatch):
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(manager, "_offer_cancel_crash_boundary", lambda *_args: None)
    intent = SimpleNamespace(
        trade_id="a" * 64, operation_id="cancel:" + "a" * 64, intent_id="b" * 64
    )
    member = (intent, 1, "cancel-member:test")
    manifest = {"cohort_id": "cancel-cohort:test", "member_count": 1}
    contract = {
        "protocol": "sage_native_cancel_offers_zero_plus_fee_v1",
        "trade_ids": [intent.trade_id],
        "source_coin_ids": ["c" * 64],
        "fee_coin_id": "e" * 64,
        "fee_mojos": 20,
    }
    quote = {"available": True, "fee_mojos": 20}
    priced = {"quote": quote, "validated_unsigned": {"unsigned": "exact"}}
    identity = {"network": "mainnet"}
    run_id = "f" * 64
    calls = []

    def reserve(**kwargs):
        calls.append("hold")
        assert kwargs["run_id"] == run_id
        assert kwargs["batch_contract"] == contract
        assert kwargs["final_quote"] == quote
        return {"operation_id": "d" * 64}

    def recheck(**kwargs):
        calls.append("recheck")
        assert kwargs["run_id"] == run_id
        return True

    monkeypatch.setattr(database, "reserve_follow_cancellation_fee", reserve)
    monkeypatch.setattr(database, "recheck_follow_cancellation_fee_hold", recheck)
    monkeypatch.setattr(
        database,
        "claim_offer_cancel_cohort_effects",
        lambda **_kwargs: {
            "cohort_id": manifest["cohort_id"],
            "effect_claimed": True,
            "member_count": 1,
        },
    )
    monkeypatch.setattr(database, "finalize_offer_cancel_cohort", lambda **_kw: None)
    monkeypatch.setattr(database, "trip_runtime_safety_latch", lambda **_kw: None)
    monkeypatch.setattr(
        database,
        "record_follow_cancellation_fee_outcome",
        lambda **_kw: (_ for _ in ()).throw(ValueError("FEE_EFFECT_UNRESOLVED")),
    )
    monkeypatch.setattr(
        wallet, "refresh_offer_cancel_continuation", lambda *_a, **_k: True
    )

    def cancel(_trades, **kwargs):
        calls.append("wallet")
        assert calls[0] == "hold"
        assert kwargs["_validated_unsigned"] == priced["validated_unsigned"]
        assert kwargs["_fee_authorizer"]() is True
        assert kwargs["_fee_authorizer"]() is True
        return {
            intent.trade_id: cancellation_result(
                CANCEL_SUBMITTED_UNCONFIRMED,
                method="test",
                raw_response={"reason_code": "SUBMITTED"},
                transaction_id="1" * 64,
                spend_identity="2" * 64,
            ),
            "_catalyst_effect_attempted": True,
        }

    monkeypatch.setattr(wallet, "cancel_offers_batch", cancel)
    result = manager._cancel_prepared_sage_batch(
        members=[member],
        manifest=manifest,
        authorities={intent.trade_id: ("continuation", {}, "w" * 64, "mainnet")},
        batch_contract=contract,
        priced_cancellation=priced,
        follow_run_id=run_id,
        follow_identity=identity,
    )
    assert result[intent.trade_id]["outcome"] == CANCEL_SUBMITTED_UNCONFIRMED
    assert calls.count("recheck") >= 2


def test_follow_batch_rejected_hold_never_claims_or_calls_wallet(monkeypatch):
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(manager, "_offer_cancel_crash_boundary", lambda *_args: None)
    intent = SimpleNamespace(
        trade_id="a" * 64, operation_id="cancel:" + "a" * 64, intent_id="b" * 64
    )
    manifest = {"cohort_id": "cancel-cohort:test", "member_count": 1}
    fee_pool = SimpleNamespace(release_ticket=lambda *_args: released.append(True))
    released = []
    monkeypatch.setattr(
        database,
        "reserve_follow_cancellation_fee",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("FEE_BUDGET_EXCEEDED")),
    )
    monkeypatch.setattr(
        database,
        "claim_offer_cancel_cohort_effects",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("effect claim")),
    )
    monkeypatch.setattr(
        wallet,
        "cancel_offers_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("wallet effect")
        ),
    )

    def finalize(*_args, **_kwargs):
        result = cancellation_result(
            CANCEL_FAILED,
            method="cohort_recovery_unattempted",
            raw_response={"reason_code": "FEE_FOLLOW_RESERVATION_BLOCKED"},
            error="CANCEL_REJECTED",
        )
        result["_catalyst_effect_attempted"] = False
        return result

    monkeypatch.setattr(manager, "_finalize_unattempted_cohort_cancel", finalize)
    result = manager._cancel_prepared_sage_batch(
        members=[(intent, 1, "cancel-member:test")],
        manifest=manifest,
        authorities={intent.trade_id: ("continuation", {}, "w" * 64, "mainnet")},
        batch_contract={"trade_ids": [intent.trade_id]},
        priced_cancellation={"quote": {}, "validated_unsigned": {}},
        fee_reservation=(fee_pool, "e" * 64, 1),
        follow_run_id="f" * 64,
        follow_identity={"network": "mainnet"},
    )
    assert result[intent.trade_id]["outcome"] == CANCEL_FAILED
    assert released == [True]


def test_follow_batch_revoked_hold_after_claim_blocks_wallet(monkeypatch):
    manager = offer_manager.OfferManager()
    monkeypatch.setattr(manager, "_offer_cancel_crash_boundary", lambda *_args: None)
    intent = SimpleNamespace(
        trade_id="a" * 64, operation_id="cancel:" + "a" * 64, intent_id="b" * 64
    )
    manifest = {"cohort_id": "cancel-cohort:test", "member_count": 1}
    calls = []
    monkeypatch.setattr(
        database,
        "reserve_follow_cancellation_fee",
        lambda **_kwargs: calls.append("hold"),
    )
    monkeypatch.setattr(
        database,
        "claim_offer_cancel_cohort_effects",
        lambda **_kwargs: {
            "cohort_id": manifest["cohort_id"],
            "effect_claimed": True,
            "member_count": 1,
        },
    )
    monkeypatch.setattr(
        database,
        "recheck_follow_cancellation_fee_hold",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        database,
        "trip_runtime_safety_latch",
        lambda **_kwargs: calls.append("latch"),
    )
    monkeypatch.setattr(
        wallet,
        "cancel_offers_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("wallet effect")
        ),
    )
    result = manager._cancel_prepared_sage_batch(
        members=[(intent, 1, "cancel-member:test")],
        manifest=manifest,
        authorities={intent.trade_id: ("continuation", {}, "w" * 64, "mainnet")},
        batch_contract={"trade_ids": [intent.trade_id]},
        priced_cancellation={"quote": {}, "validated_unsigned": {}},
        follow_run_id="f" * 64,
        follow_identity={"network": "mainnet"},
    )
    assert result[intent.trade_id]["outcome"] == "CANCEL_UNKNOWN"
    assert calls == ["hold", "latch"]


def test_restart_replays_only_authoritative_follow_fee_outcome(monkeypatch):
    manifest = {"cohort_id": "cancel-cohort:test", "member_count": 1}
    run_id = "f" * 64
    monkeypatch.setattr(
        database, "get_unresolved_offer_cancel_cohort_manifests", lambda: []
    )
    monkeypatch.setattr(
        database, "get_unsettled_coin_prep_cancellation_manifests", lambda: []
    )
    monkeypatch.setattr(
        database,
        "get_unsettled_follow_cancellation_manifests",
        lambda: [{"run_id": run_id, "manifest": manifest}],
    )
    seen = []
    monkeypatch.setattr(
        database,
        "record_follow_cancellation_fee_outcome",
        lambda **kwargs: seen.append(kwargs),
    )
    manager = offer_manager.OfferManager()
    assert manager._recover_persisted_cancel_cohorts() == {}
    assert seen == [{"run_id": run_id, "manifest_json": manifest}]
