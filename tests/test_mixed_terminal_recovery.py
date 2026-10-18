"""The mixed terminal preview must fence the complete durable cohort."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


def test_mixed_preview_http_requires_token_and_exact_scope(monkeypatch):
    import api_server
    import mixed_terminal_recovery
    import mutation_gate

    authority = object()
    calls = []
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", True)
    monkeypatch.setattr(
        mixed_terminal_recovery,
        "preview_terminal_offers",
        lambda campaign_id, revision, runtime: (
            calls.append((campaign_id, revision, runtime))
            or {"proof_digest": "b" * 64, "wallet_effect_started": False}
        ),
    )
    client = api_server.app.test_client()
    path = f"/api/bootstrap/preview_terminal?campaign_id={'a' * 64}&revision=0"
    assert client.get(path).status_code == 401
    headers = {api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}
    assert (
        client.get(
            "/api/bootstrap/preview_terminal?campaign_id=bad&revision=0",
            headers=headers,
        ).status_code
        == 400
    )
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.get_json()["proof_digest"] == "b" * 64
    assert calls == [("a" * 64, 0, authority)]
    assert client.get("/api/offers", headers=headers).status_code == 423


def test_mixed_preview_bridge_uses_same_proof_service(monkeypatch):
    import app_bridge
    import mixed_terminal_recovery
    import mutation_gate

    authority = object()
    calls = []
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(
        mixed_terminal_recovery,
        "preview_terminal_offers",
        lambda campaign_id, revision, runtime: (
            calls.append((campaign_id, revision, runtime)) or {"proof_digest": "c" * 64}
        ),
    )
    result = app_bridge.AppBridge().preview_terminal_offers(
        {"campaign_id": "a" * 64, "revision": 0}
    )
    assert result["success"] is True
    assert result["proof_digest"] == "c" * 64
    assert calls == [("a" * 64, 0, authority)]
    assert "preview_terminal_offers" in app_bridge._APP_BRIDGE_READ_ONLY_METHODS


def test_mixed_commit_http_is_exact_scoped_and_restricted(monkeypatch):
    import api_server
    import mixed_terminal_recovery
    import mutation_gate

    authority = object()
    proof = {"campaign_id": "a" * 64, "revision": 0, "proof_digest": "d" * 64}
    calls = []
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", True)
    monkeypatch.setattr(
        mixed_terminal_recovery,
        "commit_terminal_offers",
        lambda reviewed, runtime: (
            calls.append((reviewed, runtime))
            or {"filled": 1, "expired": 5, "wallet_effect_started": False}
        ),
    )
    client = api_server.app.test_client()
    path = "/api/bootstrap/commit_terminal"
    assert client.post(path, json={"reviewed": proof}).status_code == 401
    headers = {api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}
    assert (
        client.post(path, json={"reviewed": proof}, headers=headers).status_code == 200
    )
    assert calls == [(proof, authority)]
    assert (
        client.post(
            path, json={"reviewed": proof, "extra": 1}, headers=headers
        ).status_code
        == 400
    )
    assert client.post("/api/bot/start", json={}, headers=headers).status_code == 423


def test_mixed_commit_native_bridge_uses_same_scoped_service(monkeypatch):
    import app_bridge
    import mixed_terminal_recovery
    import mutation_gate

    authority = object()
    proof = {"campaign_id": "a" * 64, "revision": 0, "proof_digest": "d" * 64}
    calls = []
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    monkeypatch.setattr(
        mixed_terminal_recovery,
        "commit_terminal_offers",
        lambda reviewed, runtime: (
            calls.append((reviewed, runtime)) or {"wallet_effect_started": False}
        ),
    )
    result = app_bridge.AppBridge().commit_terminal_offers({"reviewed": proof})
    assert result["success"] is True
    assert calls == [(proof, authority)]
    assert "commit_terminal_offers" in app_bridge._APP_BRIDGE_CONTROL_METHODS


CAMPAIGN_ID = "a" * 64
ASSET_ID = "b" * 64
WALLET_HASH = "f" * 64


@pytest.mark.parametrize("failure_after_fill", [False, True])
def test_mixed_commit_reproves_then_applies_fill_before_expiry(
    monkeypatch, failure_after_fill
):
    import database
    import mixed_terminal_recovery
    import offer_reconciliation

    fill_id, expiry_id = "1" * 64, "2" * 64
    proof = {
        "campaign_id": CAMPAIGN_ID,
        "revision": 0,
        "asset_id": ASSET_ID,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": "mainnet",
        "lease_owner_run_id": "run",
        "lease_owner_pid": 123,
        "lease_owner_host": "host",
        "lease_acquired_at": "2026-10-18T09:00:00.000000Z",
        "latch_generation": 150,
        "blocking_operation_ids": [f"reconcile:{fill_id}", f"reconcile:{expiry_id}"],
        "proof_digest": "d" * 64,
        "offers": [
            {"intent_id": expiry_id, "classification": "EXPIRED_PROVEN"},
            {"intent_id": fill_id, "classification": "FILLED_PROVEN"},
        ],
    }
    roots = [
        {"intent_id": expiry_id, "row_version": 2, "lifecycle_state": "visible"},
        {"intent_id": fill_id, "row_version": 3, "lifecycle_state": "unknown"},
    ]
    calls = []

    @contextmanager
    def verified(*_args):
        calls.append("prove")
        yield proof, {fill_id: {}, expiry_id: {}}, roots, "2026-10-18T09:01:00Z"

    def reconcile(intent_id, **kwargs):
        calls.append(intent_id)
        assert kwargs["defer_post_fill_hooks"] is True
        assert kwargs["recovery_fence"]["target_intent_id"] == intent_id
        if intent_id == expiry_id and failure_after_fill:
            raise ValueError("changed")
        return {
            "applied": True,
            "idempotent": False,
            "post_fill_hooks": {"one": "pending"} if intent_id == fill_id else {},
        }

    monkeypatch.setattr(mixed_terminal_recovery, "_verified_terminal_proof", verified)
    monkeypatch.setattr(offer_reconciliation, "reconcile_offer", reconcile)
    monkeypatch.setattr(
        database,
        "get_runtime_safety_latch",
        lambda: {
            "state": "tripped" if failure_after_fill else "resolved",
            "blocking_operation_ids_json": json.dumps(
                [f"reconcile:{expiry_id}"] if failure_after_fill else []
            ),
        },
    )
    monkeypatch.setattr(
        database,
        "get_unresolved_offer_operation_blockers",
        lambda: [],
    )
    monkeypatch.setattr(
        database,
        "get_campaign_deferred_fill_hook_count",
        lambda campaign_id, revision: 4,
        raising=False,
    )
    with pytest.raises(ValueError, match="reviewed proof changed"):
        mixed_terminal_recovery.commit_terminal_offers(
            {**proof, "proof_digest": "e" * 64}, object()
        )
    assert calls == ["prove"]
    result = mixed_terminal_recovery.commit_terminal_offers(proof, object())
    assert calls == ["prove", "prove", fill_id, expiry_id]
    assert result["filled"] == 1
    assert result["expired"] == (0 if failure_after_fill else 1)
    assert result["pending_hooks"] == 4
    assert result["partial_commit"] is failure_after_fill
    assert result["latch_state"] == ("tripped" if failure_after_fill else "resolved")
    assert result["remaining_blockers"] == (1 if failure_after_fill else 0)
    assert result["unresolved_journals"] == 0


def _cohort():
    campaign = {
        "campaign_id": CAMPAIGN_ID,
        "revision": 0,
        "asset_id": ASSET_ID,
        "network": "mainnet",
        "status": "active",
    }
    intents = []
    offers = []
    blockers = []
    for index in range(6):
        intent_id = f"{index + 1:064x}"
        trade_id = f"{index + 11:064x}"
        state = "unknown" if index == 0 else "visible"
        intent = {
            "intent_id": intent_id,
            "sage_trade_id": trade_id,
            "purpose": f"bootstrap:{CAMPAIGN_ID}:revision:0",
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
            "asset_id": ASSET_ID,
            "side": "buy" if index < 3 else "sell",
            "tier": "inner",
            "lifecycle_state": state,
            "parent_intent_id": None,
            "child_intent_id": None,
        }
        intents.append(intent)
        offers.append(
            {
                "intent_id": intent_id,
                "trade_id": trade_id,
                "cat_asset_id": ASSET_ID,
                "side": intent["side"],
                "tier": "inner",
                "status": "open",
            }
        )
        if state == "unknown":
            blockers.append(
                {
                    "operation_id": f"reconcile:{intent_id}",
                    "intent_id": intent_id,
                    "operation_type": "RECONCILE",
                    "phase": "PREPARED",
                    "outcome": "UNKNOWN",
                    "blocks_mutation": 1,
                }
            )
    latch = {
        "state": "tripped",
        "reason_code": "REGISTRY_BLOCKED",
        "generation": 150,
        "blocking_operation_ids_json": json.dumps(
            [f"reconcile:{row['intent_id']}" for row in intents]
        ),
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": "mainnet",
    }
    return campaign, intents, offers, blockers, latch


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "historical_creation_failed",
        "unsupported_unknown",
        "unrelated_root",
        "duplicate_trade",
        "missing_projection",
        "extra_blocker",
        "unexpected_visible_journal",
        "wrong_asset",
        "lineage",
    ],
)
def test_mixed_cohort_requires_exact_six_roots(change):
    from mixed_terminal_recovery import validate_mixed_terminal_cohort

    campaign, intents, offers, blockers, latch = _cohort()
    if change == "historical_creation_failed":
        intents.append(
            {
                **intents[0],
                "intent_id": "e" * 64,
                "purpose": "historical:failed-creation",
                "lifecycle_state": "creation_failed",
                "sage_trade_id": None,
            }
        )
    elif change == "unsupported_unknown":
        blockers[0]["outcome"] = "CREATED"
    elif change == "unrelated_root":
        intents.append({**intents[0], "intent_id": "e" * 64, "purpose": "unrelated"})
    elif change == "duplicate_trade":
        intents[1]["sage_trade_id"] = intents[0]["sage_trade_id"]
    elif change == "missing_projection":
        offers.pop()
    elif change == "extra_blocker":
        blockers.append({**blockers[0], "operation_id": "other"})
    elif change == "unexpected_visible_journal":
        blockers.append(
            {
                **blockers[0],
                "operation_id": f"reconcile:{intents[1]['intent_id']}",
                "intent_id": intents[1]["intent_id"],
            }
        )
    elif change == "wrong_asset":
        offers[0]["cat_asset_id"] = "d" * 64
    elif change == "lineage":
        intents[0]["parent_intent_id"] = "d" * 64
    if change in {"valid", "historical_creation_failed"}:
        result = validate_mixed_terminal_cohort(
            campaign, intents, offers, blockers, {}, latch
        )
        assert [row["intent_id"] for row in result] == sorted(
            row["intent_id"]
            for row in intents
            if row["purpose"] == intents[0]["purpose"]
        )
        assert result[0]["lifecycle_state"] == "unknown"
    else:
        with pytest.raises(ValueError):
            validate_mixed_terminal_cohort(
                campaign, intents, offers, blockers, {}, latch
            )


def test_mixed_cohort_retry_includes_proven_terminal_without_reapplying():
    from mixed_terminal_recovery import validate_mixed_terminal_cohort

    campaign, intents, offers, blockers, latch = _cohort()
    completed = intents[0]
    completed["lifecycle_state"] = "terminal"
    completed["intent_id"] = "historical-filled-intent"
    offers.pop(0)
    blockers.pop(0)
    latch["blocking_operation_ids_json"] = json.dumps(
        [f"reconcile:{row['intent_id']}" for row in intents[1:]]
    )
    proof = {
        completed["sage_trade_id"]: {
            "intent_id": completed["intent_id"],
            "operation_id": f"reconcile:{completed['intent_id']}",
            "outcome": "FILLED_PROVEN",
            "evidence_sha256": "9" * 64,
        }
    }
    result = validate_mixed_terminal_cohort(
        campaign, intents, offers, blockers, proof, latch
    )
    assert len(result) == 6
    assert sum(row["lifecycle_state"] == "terminal" for row in result) == 1


def test_mixed_cohort_allowed_latch_accepts_only_supported_open_roots():
    from mixed_terminal_recovery import validate_mixed_terminal_cohort

    campaign, intents, offers, _blockers, latch = _cohort()
    intents[0]["lifecycle_state"] = "visible"
    latch.update(
        state="resolved",
        reason_code=None,
        blocking_operation_ids_json="[]",
    )
    assert (
        len(validate_mixed_terminal_cohort(campaign, intents, offers, [], {}, latch))
        == 6
    )
    intents[0]["lifecycle_state"] = "unknown"
    with pytest.raises(ValueError):
        validate_mixed_terminal_cohort(campaign, intents, offers, [], {}, latch)


def test_mixed_proof_digest_excludes_observation_clock_only():
    from mixed_terminal_recovery import _stable_proof_fields

    first = {
        "collection_started_at": "earlier",
        "offer_history": {
            "observed_at": "earlier",
            "source_observed_at_all": ["earlier"],
            "records": [{"trade_id": "a" * 64, "status": "expired"}],
        },
    }
    later = {
        "collection_started_at": "later",
        "offer_history": {
            "observed_at": "later",
            "source_observed_at_all": ["later"],
            "records": [{"trade_id": "a" * 64, "status": "expired"}],
        },
    }
    assert _stable_proof_fields(first) == _stable_proof_fields(later)
    later["offer_history"]["records"][0]["status"] = "filled"
    assert _stable_proof_fields(first) != _stable_proof_fields(later)


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "normal_allowed",
        "live_offer",
        "pending_transaction",
        "changed_root",
        "changed_owner",
        "sync_loss",
        "unknown_unproven",
    ],
)
def test_mixed_preview_reproves_complete_sage_cohort_without_writes(
    monkeypatch, change
):
    import api_server
    import database
    import mixed_terminal_recovery
    import mutation_gate
    import offer_reconciliation
    import wallet
    from config import cfg

    campaign, intents, offers, blockers, latch = _cohort()
    now = datetime.now(timezone.utc)
    stamp = lambda seconds: (
        (now + timedelta(seconds=seconds))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    campaign.update(
        wallet_id=2,
        wallet_fingerprint=3702373391,
        expires_at=stamp(-3600),
    )
    monkeypatch.setattr(cfg, "CAT_ASSET_ID", ASSET_ID)
    monkeypatch.setattr(cfg, "CAT_WALLET_ID", 2)
    normal = change == "normal_allowed"
    if normal:
        intents[0]["lifecycle_state"] = "visible"
        blockers.clear()
        latch.update(
            state="resolved",
            reason_code=None,
            blocking_operation_ids_json="[]",
        )
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", not normal)
    monkeypatch.setattr(
        api_server,
        "bot",
        SimpleNamespace(
            is_running=lambda: False,
            offer_manager=SimpleNamespace(
                wait_for_offer_creation_quiescence=lambda: None
            ),
        )
        if normal
        else None,
    )
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Harvestr",
        fingerprint=3702373391,
        network_id="mainnet",
        kind="private",
        has_secrets=True,
        bound_at_utc=stamp(-10),
        maximum_age_seconds=60,
    )

    class Authority:
        run_id = "recovery-owner"
        owner_pid = 111
        owner_host = "test-host"
        _lease_acquired_at = stamp(-10)
        wallet_fingerprint_hash = WALLET_HASH
        network = "mainnet"

        def status(self):
            return SimpleNamespace(
                to_dict=lambda: {
                    "allowed": normal,
                    "reason_code": "ALLOWED" if normal else "REGISTRY_BLOCKED",
                    "lease": {"owned_by_this_run": True, "active": True},
                }
            )

        def require_wallet_identity_authority(self, _operation):
            return binding

    authority = Authority()
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: authority)
    lease = {
        "active": 1,
        "owner_run_id": authority.run_id,
        "owner_pid": authority.owner_pid,
        "owner_host": authority.owner_host,
        "acquired_at": authority._lease_acquired_at,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": "mainnet",
        "lease_version": 11,
        "expires_at": stamp(60),
    }
    monkeypatch.setattr(database, "get_bootstrap_campaign", lambda _id: campaign)
    reads = []

    def read_intents():
        reads.append("intents")
        if change == "changed_root" and len(reads) == 2:
            return [{**intents[0], "side": "sell"}, *intents[1:]]
        return intents

    monkeypatch.setattr(database, "get_offer_intents_for_registry", read_intents)
    monkeypatch.setattr(database, "get_open_offers", lambda **_kw: offers)
    monkeypatch.setattr(
        database, "get_unresolved_offer_operation_blockers", lambda: blockers
    )
    monkeypatch.setattr(database, "get_runtime_safety_latch", lambda: latch)
    lease_reads = []

    def read_lease():
        lease_reads.append(True)
        if change == "changed_owner" and len(lease_reads) == 2:
            return {**lease, "owner_run_id": "other-owner"}
        return lease

    monkeypatch.setattr(database, "get_runtime_mutation_lease", read_lease)
    monkeypatch.setattr(database, "get_authoritative_terminal_records", lambda _ids: {})
    monkeypatch.setattr(
        database, "list_active_bootstrap_campaigns_for_asset", lambda _asset: [campaign]
    )
    monkeypatch.setattr(
        database,
        "_stability_connection",
        lambda: (_ for _ in ()).throw(AssertionError("preview wrote the database")),
    )
    monkeypatch.setattr(wallet, "get_wallet_identity", lambda: {"success": True})
    sync_reads = []

    def read_sync():
        sync_reads.append(True)
        return {"synced": not (change == "sync_loss" and len(sync_reads) == 2)}

    monkeypatch.setattr(wallet, "get_wallet_sync_status", read_sync)
    identity_times = iter([stamp(-2), stamp(-1)])
    monkeypatch.setattr(
        mutation_gate,
        "validate_wallet_identity",
        lambda *_args, **_kw: {
            "allowed": True,
            "observed_at_utc": next(identity_times),
        },
    )
    books = iter(
        [
            {"trade_ids": [], "pending_transaction_ids": [], "observed_at": stamp(-2)},
            {
                "trade_ids": ["a" * 64] if change == "live_offer" else [],
                "pending_transaction_ids": (
                    ["b" * 64] if change == "pending_transaction" else []
                ),
                "observed_at": stamp(-1),
            },
        ]
    )
    monkeypatch.setattr(
        wallet, "_read_refresh_abort_cleanup_snapshot", lambda: next(books)
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "load_authoritative_evidence",
        lambda row, **_kw: {"witness": row["sage_trade_id"]},
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "classify_terminal_evidence",
        lambda row, _evidence, **_kw: {
            "classification": (
                "UNKNOWN"
                if change == "unknown_unproven" and row["lifecycle_state"] == "unknown"
                else "FILLED_PROVEN"
                if row["lifecycle_state"] == "unknown"
                else "EXPIRED_PROVEN"
            ),
            "reason_code": "AUTHORITATIVE_PROOF",
        },
    )
    if change in {"valid", "normal_allowed"}:
        result = mixed_terminal_recovery.preview_terminal_offers(
            CAMPAIGN_ID, 0, authority
        )
        assert len(result["offers"]) == 6
        assert sum(
            row["classification"] == "FILLED_PROVEN" for row in result["offers"]
        ) == (0 if normal else 1)
        assert result["wallet_effect_started"] is False
        assert result["sage_live_offers"] == 0
    else:
        with pytest.raises(ValueError):
            mixed_terminal_recovery.preview_terminal_offers(CAMPAIGN_ID, 0, authority)
