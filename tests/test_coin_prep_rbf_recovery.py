"""The RBF observer reads confirmed Sage state and never dispatches a wallet effect."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import coin_prep_rbf_recovery as recovery


SOURCE = "1" * 64
ORIGINAL_TX = "2" * 64
SUCCESSOR_TX = "3" * 64
FEE = 17_219_875
FEE_AMOUNT = 20_000_000_000
CHANGE = 1_435_390_971_590
SHARED = [f"{index + 10:064x}" for index in range(4)]
OLD_CHANGE = "a" * 64
NEW_CHANGE = "b" * 64


@pytest.mark.parametrize(
    ("liveness", "receipt_count"),
    [(False, 1), (True, 0), (None, 0)],
)
def test_sign_only_crash_recovery_requires_decisive_dead_owner(
    monkeypatch, liveness, receipt_count,
):
    sign = {
        "attempt_id": "c" * 64, "operation_id": "coin-prep:" + "d" * 64,
        "owner_run_id": "prior", "owner_pid": 4242, "owner_host": "local",
        "lease_version": 2, "lease_acquired_at": _utc(-120),
        "started_at": _utc(-100),
    }
    receipts = []
    monkeypatch.setattr(
        recovery, "get_recoverable_coin_prep_rbf_sign_intents",
        lambda: [sign],
    )
    monkeypatch.setattr(
        recovery.mutation_gate, "pid_liveness", lambda *_: liveness,
    )
    monkeypatch.setattr(
        recovery, "record_coin_prep_rbf_sign_no_submit",
        lambda attempt_id, **kwargs: receipts.append((attempt_id, kwargs)),
    )
    monkeypatch.setattr(
        recovery, "get_coins_by_ids",
        lambda *_: pytest.fail("wallet read is not needed for sign-only proof"),
    )
    result = recovery.recover_crashed_coin_prep_rbf_sign_intents()
    assert len(receipts) == receipt_count
    assert len(result["receipts_recorded"]) == receipt_count
    if receipt_count:
        attempt_id, kwargs = receipts[0]
        assert attempt_id == sign["attempt_id"]
        assert kwargs["receipt"]["reason_code"] == "CRASH_BEFORE_SUBMIT_MARKER"
        assert kwargs["receipt"]["submit_rpc_attempted"] is False
        assert kwargs["prior_owner_liveness_proven_dead"] is True


def test_sign_only_crash_recovery_fails_closed_on_submit_race(monkeypatch):
    sign = {
        "attempt_id": "c" * 64, "owner_run_id": "prior",
        "owner_pid": 4242, "owner_host": "local", "lease_version": 2,
        "lease_acquired_at": _utc(-120), "started_at": _utc(-100),
    }
    monkeypatch.setattr(
        recovery, "get_recoverable_coin_prep_rbf_sign_intents",
        lambda: [sign],
    )
    monkeypatch.setattr(
        recovery.mutation_gate, "pid_liveness", lambda *_: False,
    )
    def marker_present(*_args, **_kwargs):
        raise ValueError("RBF submit-start marker already exists")
    monkeypatch.setattr(
        recovery, "record_coin_prep_rbf_sign_no_submit", marker_present,
    )
    result = recovery.recover_crashed_coin_prep_rbf_sign_intents()
    assert result["receipts_recorded"] == set()


def test_startup_invokes_sign_only_recovery_for_fee_split(monkeypatch):
    import coin_prep_worker

    calls = []
    monkeypatch.setattr(coin_prep_worker, "_recover_legacy_sage_consolidation",
                        lambda _worker: False)
    monkeypatch.setattr(
        coin_prep_worker, "get_recoverable_coin_prep_operations",
        lambda: [{"operation_id": "coin-prep:" + "a" * 64,
                  "purpose": "fee_reserve", "operation_kind": "split",
                  "outcome": "SUBMITTED_UNKNOWN"}],
    )
    monkeypatch.setattr(
        recovery, "recover_crashed_coin_prep_rbf_sign_intents",
        lambda: calls.append("sign_only"),
    )
    monkeypatch.setattr(
        coin_prep_worker.CoinPrepWorker,
        "_recover_coin_prep_operations_read_only",
        lambda *_args: calls.append("observe") or False,
    )
    assert coin_prep_worker.recover_coin_prep_operations_at_startup() is False
    assert calls == ["sign_only", "observe"]


def _utc(offset=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def _outputs(change_id, change_amount):
    return [
        {"coin_id": coin_id, "amount_mojos": FEE_AMOUNT,
         "purpose": "fee_reserve"}
        for coin_id in SHARED
    ] + [{"coin_id": change_id, "amount_mojos": change_amount,
          "purpose": "top_up"}]


@pytest.mark.parametrize("winner", ["ORIGINAL", "SUCCESSOR"])
def test_observer_requires_exact_confirmed_source_and_outputs(monkeypatch, winner):
    identity = {
        "backend": "sage", "name": "wallet", "fingerprint": 736588221,
        "network_id": "mainnet", "kind": "bls", "has_secrets": True,
        "bound_at_utc": _utc(-10), "maximum_age_seconds": 300,
    }
    attempt = {
        "source_coin_ids_json": json.dumps([SOURCE]),
        "original_outputs_json": json.dumps(_outputs(OLD_CHANGE, CHANGE)),
        "successor_outputs_json": json.dumps(_outputs(NEW_CHANGE, CHANGE - FEE)),
        "wallet_identity_json": json.dumps(identity),
        "original_transaction_id": ORIGINAL_TX,
        "fee_mojos": FEE,
    }
    outputs = (
        _outputs(OLD_CHANGE, CHANGE)
        if winner == "ORIGINAL" else _outputs(NEW_CHANGE, CHANGE - FEE)
    )
    txid = ORIGINAL_TX if winner == "ORIGINAL" else SUCCESSOR_TX
    monkeypatch.setattr(recovery, "get_wallet_identity_for_recovery", lambda: {
        "success": True,
        **{key: identity[key] for key in (
            "backend", "name", "fingerprint", "network_id", "kind",
            "has_secrets")},
        "observed_at_utc": _utc(0),
    })
    monkeypatch.setattr(recovery, "get_wallet_sync_status", lambda: {"synced": True})
    calls = []

    def coins(ids, **_kwargs):
        calls.append(ids)
        if ids == [SOURCE]:
            return {"0x" + SOURCE: {
                "amount": CHANGE + 4 * FEE_AMOUNT,
                "spent_height": 100,
                "created_height": 10,
                "asset_id": "xch",
            }}
        return {"0x" + output["coin_id"]: {
            "amount": output["amount_mojos"],
            "created_height": 100, "spent_height": 0, "asset_id": "xch",
        } for output in outputs}

    monkeypatch.setattr(recovery, "get_coins_by_ids", coins)
    monkeypatch.setattr(recovery, "get_transaction_by_height", lambda height: {
        "success": True,
        "transaction": {
            "transaction_id": txid,
            "spent": [{"coin_id": SOURCE, "amount": CHANGE + 4 * FEE_AMOUNT,
                       "asset": None}],
            "created": [
                {"coin_id": output["coin_id"],
                 "amount": output["amount_mojos"], "asset": None}
                for output in outputs
            ],
        },
    })
    proof = recovery.observe_coin_prep_rbf_winner(attempt)
    assert proof is not None
    assert proof["winner"] == winner
    assert proof["winner_transaction_id"] == txid
    assert proof["chain_view"]["source_spent_height"] == 100
    assert all("spent_height" not in coin for coin in proof["authoritative_view"]["coins"])
    assert len(calls) == 2


def test_observer_does_not_treat_pending_source_as_confirmation(monkeypatch):
    identity = {
        "backend": "sage", "name": "wallet", "fingerprint": 736588221,
        "network_id": "mainnet", "kind": "bls", "has_secrets": True,
        "bound_at_utc": _utc(-10), "maximum_age_seconds": 300,
    }
    attempt = {
        "source_coin_ids_json": json.dumps([SOURCE]),
        "original_outputs_json": json.dumps(_outputs(OLD_CHANGE, CHANGE)),
        "successor_outputs_json": json.dumps(_outputs(NEW_CHANGE, CHANGE - FEE)),
        "wallet_identity_json": json.dumps(identity),
    }
    monkeypatch.setattr(recovery, "get_wallet_identity_for_recovery", lambda: {
        "success": True, **{key: identity[key] for key in (
            "backend", "name", "fingerprint", "network_id", "kind",
            "has_secrets")}, "observed_at_utc": _utc(0),
    })
    monkeypatch.setattr(recovery, "get_wallet_sync_status", lambda: {"synced": True})
    monkeypatch.setattr(recovery, "get_coins_by_ids", lambda *_a, **_k: {
        "0x" + SOURCE: {"amount": CHANGE + 4 * FEE_AMOUNT,
                        "spent_height": None}
    })
    monkeypatch.setattr(recovery, "get_transaction_by_height",
                        lambda *_a: pytest.fail("no confirmed-height read"))
    assert recovery.observe_coin_prep_rbf_winner(attempt) is None


def test_startup_routes_dispatched_rbf_away_from_generic_prep(monkeypatch):
    import coin_prep_worker

    operation_id = "coin-prep:" + "5" * 64
    operation = {
        "operation_id": operation_id,
        "operation_kind": "split",
        "purpose": "fee_reserve",
        "outcome": "SUBMITTED_UNKNOWN",
    }
    monkeypatch.setattr(
        coin_prep_worker, "get_recoverable_coin_prep_operations",
        lambda: [operation],
    )
    monkeypatch.setattr(
        recovery, "recover_dispatched_coin_prep_rbf_attempts_read_only",
        lambda: {"operation_ids": {operation_id}, "settled": set()},
    )
    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.log = lambda *_args: None
    assert worker._recover_coin_prep_operations_read_only(
        lambda _row: pytest.fail("generic recovery must not observe dispatched RBF")
    ) is False
    monkeypatch.setattr(
        recovery, "recover_dispatched_coin_prep_rbf_attempts_read_only",
        lambda: {"operation_ids": {operation_id}, "settled": {operation_id}},
    )
    assert worker._recover_coin_prep_operations_read_only(
        lambda _row: pytest.fail("generic recovery must not observe dispatched RBF")
    ) is True
