"""Safety proof for resolving one ambiguous offer creation with no effect."""

from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

import creation_no_effect_recovery as recovery
from creation_no_effect_recovery import (
    capture_creation_observation,
    classify_no_effect_creation,
    sage_process_identity,
)


INTENT_ID = "a" * 64
COIN_ID = "b" * 64
ASSET_ID = "c" * 64
WALLET_HASH = "d" * 64
OPERATION_ID = f"create:{INTENT_ID}"


def proof():
    intent = {
        "intent_id": INTENT_ID,
        "lifecycle_state": "creation_unknown",
        "row_version": 1,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": "mainnet",
        "asset_id": ASSET_ID,
        "side": "sell",
        "offered_amount_atomic": "1000",
        "requested_amount_atomic": "2700000000003",
        "selected_coin_ids_json": f'["{COIN_ID}"]',
        "sage_trade_id": None,
    }
    latch = {
        "state": "tripped",
        "generation": 694,
        "reason_code": "UNRESOLVED_OPERATIONS",
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": "mainnet",
        "blocking_operation_ids_json": f'["{OPERATION_ID}"]',
    }
    journal = {
        "operation_id": OPERATION_ID,
        "intent_id": INTENT_ID,
        "operation_type": "CREATE",
        "outcome": "UNKNOWN",
        "blocks_mutation": 1,
    }
    reservations = [
        {
            "coin_id": COIN_ID,
            "status": "reserved",
            "reservation_identity": f"intent:{INTENT_ID}",
        }
    ]

    def observation(at):
        return {
            "observed_at": at,
            "wallet_identity": {
                "success": True,
                "backend": "sage",
                "fingerprint": 736588221,
                "network_id": "mainnet",
                "kind": "local",
                "has_secrets": True,
            },
            "sage_process": {
                "pid": 160832,
                "created_at": 1793475658.0,
                "exe": "C:/Sage/sage-tauri.exe",
            },
            "synced": True,
            "pending_transaction_ids": [],
            "coin": {
                "amount": 1000,
                "spent_height": None,
                "offer_id": None,
                "asset_id": ASSET_ID,
            },
            "history": {
                "complete": True,
                "read_error": None,
                "pagination": {"authoritative_end": True},
                "records": [
                    {
                        "trade_id": "1" * 64,
                        "status": "ACTIVE",
                        "summary": {
                            "offered": {ASSET_ID: 1000},
                            "requested": {"xch": 2700000000000},
                        },
                    },
                    {
                        "trade_id": "2" * 64,
                        "status": "ACTIVE",
                        "summary": {
                            "offered": {ASSET_ID: 1000},
                            "requested": {"xch": 2700000000001},
                        },
                    },
                    {
                        "trade_id": "5" * 64,
                        "status": "EXPIRED",
                        "summary": {
                            "offered": {ASSET_ID: 1000},
                            "requested": {"xch": 0},
                        },
                    },
                ],
            },
        }

    return (
        intent,
        latch,
        journal,
        reservations,
        [
            observation("2026-10-31T20:00:00Z"),
            observation("2026-10-31T20:00:02Z"),
        ],
    )


def test_no_effect_creation_proof_binds_exact_stable_wallet_and_book():
    result = classify_no_effect_creation(*proof())
    assert result["intent_id"] == INTENT_ID
    assert result["operation_id"] == OPERATION_ID
    assert result["latch_generation"] == 694
    assert len(result["proof_digest"]) == 64


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p[4][1]["sage_process"].update(pid=160833),
        lambda p: p[4][1]["history"]["records"].append(
            {
                "trade_id": "3" * 64,
                "status": "ACTIVE",
                "summary": {"offered": {ASSET_ID: 1000}, "requested": {"xch": 3}},
            }
        ),
        lambda p: p[4][1]["coin"].update(spent_height=1),
        lambda p: p[4][1]["coin"].update(offer_id="3" * 64),
        lambda p: p[4][1]["pending_transaction_ids"].append("4" * 64),
        lambda p: p[4][1]["wallet_identity"].update(fingerprint=123),
        lambda p: p[4][1]["history"].update(complete=False),
        lambda p: p[4][1]["history"]["records"].append(
            {
                "trade_id": "3" * 64,
                "status": "ACTIVE",
                "summary": {
                    "offered": {ASSET_ID: 1000},
                    "requested": {"xch": 2700000000003},
                },
            }
        ),
    ],
)
def test_no_effect_creation_proof_refuses_changed_or_ambiguous_evidence(change):
    candidate = deepcopy(proof())
    change(candidate)
    with pytest.raises(ValueError):
        classify_no_effect_creation(*candidate)


def test_no_effect_review_digest_changes_with_latch_generation():
    original = proof()
    changed = deepcopy(original)
    changed[1]["generation"] = 695
    assert (
        classify_no_effect_creation(*changed)["proof_digest"]
        != (classify_no_effect_creation(*original)["proof_digest"])
    )


def test_native_no_effect_proof_survives_json_bridge_round_trip(monkeypatch):
    import database

    recovery._clear_pending_review_for_test()
    current = classify_no_effect_creation(*proof())
    current.update(
        {
            "lease_owner_run_id": "test-run",
            "lease_owner_pid": 42,
            "lease_owner_host": "test-host",
            "lease_version": 1,
        }
    )
    material = {key: value for key, value in current.items() if key != "proof_digest"}
    import hashlib

    current["proof_digest"] = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(recovery, "collect_no_effect_creation_proof", lambda: current)
    monkeypatch.setattr(
        database,
        "settle_no_effect_offer_creation",
        lambda *, proof: {
            "applied": True,
            "wallet_effect_started": False,
        },
    )
    review = recovery.preview_no_effect_creation()
    assert type(review["sage_stable"]) is list
    from_native_js = json.loads(json.dumps(review))
    assert recovery.commit_no_effect_creation(from_native_js)["applied"] is True


def test_sage_process_identity_requires_one_listener(monkeypatch):
    class Address:
        port = 9257

    class Listener:
        status = "LISTEN"
        laddr = Address()
        pid = 160832

    class Process:
        def __init__(self, pid):
            assert pid == 160832

        def create_time(self):
            return 1793475658.0

        def exe(self):
            return "C:/Sage/sage-tauri.exe"

    import creation_no_effect_recovery

    monkeypatch.setattr(
        creation_no_effect_recovery.psutil,
        "net_connections",
        lambda **kwargs: [Listener()],
    )
    monkeypatch.setattr(creation_no_effect_recovery.psutil, "Process", Process)
    assert sage_process_identity()["pid"] == 160832
    monkeypatch.setattr(
        creation_no_effect_recovery.psutil,
        "net_connections",
        lambda **kwargs: [Listener(), Listener()],
    )
    with pytest.raises(ValueError):
        sage_process_identity()


def test_capture_creation_observation_reads_wallet_only():
    intent = proof()[0]
    calls = []
    wallet = SimpleNamespace(
        get_wallet_identity=lambda: (
            calls.append("identity") or proof()[4][0]["wallet_identity"]
        ),
        get_wallet_sync_status=lambda: calls.append("sync") or {"synced": True},
        get_pending_transactions=lambda: calls.append("pending") or [],
        get_coins_by_ids=lambda ids, **kwargs: (
            calls.append(("coins", ids, kwargs))
            or {"0x" + COIN_ID: proof()[4][0]["coin"]}
        ),
        get_authoritative_offer_history=lambda **kwargs: (
            calls.append("history")
            or {
                "success": True,
                "offers": proof()[4][0]["history"]["records"],
                "total": 3,
                "end_of_history": True,
            }
        ),
    )
    observation = capture_creation_observation(
        intent,
        wallet_module=wallet,
        process_reader=lambda: proof()[4][0]["sage_process"],
    )
    assert observation["history"]["complete"] is True
    assert observation["coin"]["amount"] == 1000
    assert observation["pending_transaction_ids"] == []
    assert calls == [
        "identity",
        "sync",
        "pending",
        "history",
        ("coins", [COIN_ID], {"authoritative_asset_hints": {COIN_ID: ASSET_ID}}),
    ]


def test_native_no_effect_commit_rechecks_same_proof_and_consumes_review(monkeypatch):
    import database

    recovery._clear_pending_review_for_test()
    current = {
        "proof_digest": "1" * 64,
        "intent_id": INTENT_ID,
        "operation_id": OPERATION_ID,
        "latch_generation": 694,
        "selected_coin_id": COIN_ID,
        "lease_owner_run_id": "same",
        "lease_owner_pid": 42,
        "lease_owner_host": "same",
        "lease_version": 1,
    }
    writes = []
    monkeypatch.setattr(
        recovery, "collect_no_effect_creation_proof", lambda: dict(current)
    )
    monkeypatch.setattr(
        database,
        "settle_no_effect_offer_creation",
        lambda *, proof: (
            writes.append(proof) or {"applied": True, "wallet_effect_started": False}
        ),
    )
    review = recovery.preview_no_effect_creation()
    current["proof_digest"] = "2" * 64
    current["selected_coin_id"] = "3" * 64
    with pytest.raises(ValueError, match="changed"):
        recovery.commit_no_effect_creation(review)
    assert writes == []

    review = recovery.preview_no_effect_creation()
    result = recovery.commit_no_effect_creation(review)
    assert result["wallet_effect_started"] is False
    assert len(writes) == 1
    with pytest.raises(ValueError, match="not reviewed"):
        recovery.commit_no_effect_creation(review)


def test_native_no_effect_review_allows_same_owner_lease_renewal(monkeypatch):
    import database

    recovery._clear_pending_review_for_test()
    current = {
        "proof_digest": "1" * 64,
        "intent_id": INTENT_ID,
        "operation_id": OPERATION_ID,
        "latch_generation": 694,
        "lease_owner_run_id": "same",
        "lease_owner_pid": 42,
        "lease_owner_host": "same",
        "lease_version": 1,
    }
    monkeypatch.setattr(
        recovery, "collect_no_effect_creation_proof", lambda: dict(current)
    )
    monkeypatch.setattr(
        database,
        "settle_no_effect_offer_creation",
        lambda *, proof: {"applied": True, "lease_version": proof["lease_version"]},
    )
    review = recovery.preview_no_effect_creation()
    current["lease_version"] = 2
    current["proof_digest"] = "2" * 64
    assert recovery.commit_no_effect_creation(review)["lease_version"] == 2


def test_native_bridge_exposes_db_only_recovery_under_owned_latch(monkeypatch):
    import app_bridge

    bridge = app_bridge.AppBridge()
    reviewed = {"proof_digest": "1" * 64}
    runtime = SimpleNamespace(
        status=lambda: SimpleNamespace(
            to_dict=lambda: {"lease": {"owned_by_this_run": True}}
        )
    )
    api = SimpleNamespace(
        _ensure_mutation_runtime=lambda: None,
        mutation_gate=SimpleNamespace(current_runtime=lambda: runtime),
    )
    monkeypatch.setattr(app_bridge, "_bridge_runtime_api", lambda _bridge: api)
    monkeypatch.setattr(
        recovery,
        "commit_no_effect_creation",
        lambda value: (
            {"applied": True, "wallet_effect_started": False}
            if value == reviewed
            else (_ for _ in ()).throw(ValueError())
        ),
    )
    assert bridge.commit_no_effect_creation({"reviewed": reviewed}) == {
        "success": True,
        "applied": True,
        "wallet_effect_started": False,
    }
    assert "commit_no_effect_creation" in app_bridge._APP_BRIDGE_MUTATION_METHODS
