"""An unbounded Follow run keeps its exact cancellation hold at dispatch."""

from importlib import import_module
from types import SimpleNamespace

import pytest

from test_coin_prep_fee_frozen_execution import approved  # noqa: F401
from test_follow_fee_cancellation import _run
import test_follow_fee_cancellation_hold as hold_helpers


def test_unbounded_follow_cancel_recheck_does_not_apply_marker_cap(approved):
    database = import_module("database")
    hold_helpers.database = database
    assert approved["approval"]["unbounded"] is True
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = hold_helpers._prepared_follow_cancel(
        run_id, identity, fee=50, reason="requote"
    )
    quote = hold_helpers._quote(approved, fee=50)

    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=quote,
    )
    assert hold["fee_mojos"] == 50
    assert (
        database.claim_offer_cancel_cohort_effects(manifest_json=manifest)[
            "effect_claimed"
        ]
        is True
    )
    assert database.recheck_follow_cancellation_fee_hold(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=quote,
    )


def _claimed_predispatch_cohort(approved):
    database = import_module("database")
    hold_helpers.database = database
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = hold_helpers._prepared_follow_cancel(
        run_id, identity, fee=50, count=2, reason="requote"
    )
    database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=hold_helpers._quote(approved, fee=50),
    )
    database.claim_offer_cancel_cohort_effects(manifest_json=manifest)
    latch = database.trip_runtime_safety_latch(
        reason_code="UNRESOLVED_OPERATIONS",
        reason="Follow cancellation fee hold changed after effect claim",
        blocking_operation_ids=[m["operation_id"] for m in manifest["members"]],
        wallet_fingerprint_hash="f" * 64,
        network=identity["network"],
    )
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=approved["now"])
    proof = {
        "source_coins": [
            {"coin_id": coin_id, "offer_id": member["trade_id"], "spent_height": None}
            for coin_id, member in zip(contract["source_coin_ids"], manifest["members"])
        ],
        "fee_coin": {
            "coin_id": contract["fee_coin_id"],
            "offer_id": None,
            "spent_height": None,
        },
        "offers": [
            {"offer_id": member["trade_id"], "status": "active"}
            for member in manifest["members"]
        ],
        "pending_transactions": [],
        "observed_at_epoch": approved["now"],
    }
    return database, run_id, manifest, identity, latch, proof


def test_claimed_predispatch_recovery_releases_exact_follow_cohort(approved):
    database, run_id, manifest, identity, latch, proof = _claimed_predispatch_cohort(
        approved
    )
    result = database.reconcile_follow_predispatch_cancel_cohort(
        run_id=run_id,
        manifest_json=manifest,
        expected_latch_generation=latch["generation"],
        wallet_fingerprint_hash="f" * 64,
        network=identity["network"],
        wallet_evidence=proof,
    )
    assert result["fee_outcome"] == "RELEASED_NO_EFFECT"
    assert database.get_runtime_safety_latch()["state"] == "resolved"
    assert database.get_unresolved_offer_operation_blockers() == []
    assert database.get_unresolved_offer_cancel_cohort_manifests() == []
    assert (
        database.get_effective_follow_fee_policy(
            run_id=run_id, identity=identity, now_epoch=approved["now"]
        )["ready"]
        is True
    )


@pytest.mark.parametrize("damage", ["pending", "spent", "offer"])
def test_claimed_predispatch_recovery_refuses_ambiguous_wallet_proof(approved, damage):
    database, run_id, manifest, identity, latch, proof = _claimed_predispatch_cohort(
        approved
    )
    if damage == "pending":
        proof["pending_transactions"] = [{"transaction_id": "7" * 64}]
    elif damage == "spent":
        proof["source_coins"][0]["spent_height"] = 100
    else:
        proof["offers"][0]["status"] = "cancelled"
    with pytest.raises(ValueError):
        database.reconcile_follow_predispatch_cancel_cohort(
            run_id=run_id,
            manifest_json=manifest,
            expected_latch_generation=latch["generation"],
            wallet_fingerprint_hash="f" * 64,
            network=identity["network"],
            wallet_evidence=proof,
        )
    assert database.get_runtime_safety_latch()["state"] == "tripped"
    assert len(database.get_unresolved_offer_operation_blockers()) == 2


def test_claimed_predispatch_recovery_refuses_live_runtime_lease(approved):
    database, run_id, manifest, identity, latch, proof = _claimed_predispatch_cohort(
        approved
    )
    conn = database._stability_connection()
    try:
        conn.execute("UPDATE runtime_mutation_lease SET active=1 WHERE singleton_id=1")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(ValueError, match="stopped runtime"):
        database.reconcile_follow_predispatch_cancel_cohort(
            run_id=run_id,
            manifest_json=manifest,
            expected_latch_generation=latch["generation"],
            wallet_fingerprint_hash="f" * 64,
            network=identity["network"],
            wallet_evidence=proof,
        )
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize("slow_sweep", [False, True])
def test_claimed_predispatch_coordinator_collects_fresh_sage_proof(
    approved, monkeypatch, slow_sweep
):
    recovery = import_module("follow_cancel_predispatch_recovery")
    database, run_id, manifest, identity, _latch, proof = _claimed_predispatch_cohort(
        approved
    )
    observed_times = iter([approved["now"], *([approved["now"] + 16] * 100)])
    monkeypatch.setattr(
        recovery,
        "time",
        SimpleNamespace(
            time=(lambda: next(observed_times))
            if slow_sweep
            else (lambda: approved["now"])
        ),
    )
    monkeypatch.setattr(
        recovery.wallet,
        "get_wallet_identity_for_recovery",
        lambda: {
            "success": True,
            "backend": "sage",
            "fingerprint": identity["wallet_fingerprint"],
            "network_id": identity["network"],
        },
    )
    coins = {
        "0x" + coin["coin_id"]: dict(coin)
        for coin in [*proof["source_coins"], proof["fee_coin"]]
    }
    monkeypatch.setattr(
        recovery.wallet, "get_recovery_coins_by_ids", lambda _ids: coins
    )
    monkeypatch.setattr(
        recovery.wallet,
        "get_recovery_active_offers_by_ids",
        lambda ids: {
            "complete": True,
            "requested_ids": list(ids),
            "offers": proof["offers"],
        },
    )
    monkeypatch.setattr(recovery.wallet, "get_pending_transactions_strict", lambda: [])

    if slow_sweep:
        with pytest.raises(ValueError, match="Sage no-effect read is incomplete"):
            recovery.recover_claimed_predispatch_follow_cancel(run_id, manifest)
        assert database.get_runtime_safety_latch()["state"] == "tripped"
    else:
        result = recovery.recover_claimed_predispatch_follow_cancel(run_id, manifest)
        assert result["fee_outcome"] == "RELEASED_NO_EFFECT"
        assert result["restart_required"] is True
        assert database.get_runtime_safety_latch()["state"] == "resolved"


def test_strict_sage_recovery_reads_require_native_evidence(monkeypatch):
    sage = import_module("wallet_sage")
    coin_id = "c" * 64
    trade_id = "a" * 64

    monkeypatch.setattr(sage, "rpc", lambda *_args, **_kwargs: {"transactions": []})
    assert sage.get_pending_transactions_strict() == []
    monkeypatch.setattr(sage, "rpc", lambda *_args, **_kwargs: {"success": True})
    assert sage.get_pending_transactions_strict() is None
    monkeypatch.setattr(
        sage,
        "rpc",
        lambda *_args, **_kwargs: {"transactions": [], "pending_transactions": [{}]},
    )
    assert sage.get_pending_transactions_strict() is None

    native_coin = {"coin_id": coin_id, "spent_height": None, "offer_id": trade_id}
    monkeypatch.setattr(sage, "rpc", lambda *_args, **_kwargs: {"coins": [native_coin]})
    assert sage.get_recovery_coins_by_ids([coin_id]) is not None
    monkeypatch.setattr(
        sage,
        "rpc",
        lambda *_args, **_kwargs: {
            "coins": [{"coin_id": coin_id, "offer_id": trade_id}]
        },
    )
    assert sage.get_recovery_coins_by_ids([coin_id]) is None
    monkeypatch.setattr(
        sage,
        "rpc",
        lambda *_args, **_kwargs: {"coins": [native_coin], "error_message": "failed"},
    )
    assert sage.get_recovery_coins_by_ids([coin_id]) is None

    monkeypatch.setattr(
        sage,
        "rpc",
        lambda *_args, **_kwargs: {"offer": {"offer_id": trade_id, "status": "active"}},
    )
    assert sage.get_recovery_active_offers_by_ids((trade_id,)) is not None
    monkeypatch.setattr(
        sage,
        "rpc",
        lambda *_args, **_kwargs: {
            "offer": {"offer_id": trade_id, "trade_id": "b" * 64, "status": "active"}
        },
    )
    assert sage.get_recovery_active_offers_by_ids((trade_id,)) is None
