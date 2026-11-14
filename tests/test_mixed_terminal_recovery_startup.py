"""The original desktop startup must route exact registry recovery narrowly."""

from __future__ import annotations

import importlib
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


def _desktop(monkeypatch):
    original_platform = sys.platform
    monkeypatch.setattr(sys, "platform", "linux")
    sys.modules.pop("desktop_app", None)
    module = importlib.import_module("desktop_app")
    monkeypatch.setattr(sys, "platform", original_platform)
    return module


def test_registry_blocked_desktop_attempts_only_restricted_recovery(monkeypatch):
    import api_server
    import database
    import read_only_diagnostics

    desktop = _desktop(monkeypatch)
    events: list[str] = []
    denied = {"allowed": False, "reason_code": "REGISTRY_BLOCKED"}

    class Arbiter:
        acquired = True

        def release(self):
            events.append("arbiter_released")

    monkeypatch.setattr(read_only_diagnostics, "acquire_startup_arbiter", Arbiter)
    monkeypatch.setattr(
        read_only_diagnostics, "preflight_requires_diagnostics", lambda: False
    )
    monkeypatch.setattr(desktop, "_acquire_instance_lock", lambda: True)
    monkeypatch.setattr(database, "attempt_db_recovery", lambda: {"action": "ok"})
    monkeypatch.setattr(desktop, "_initialize_startup_ownership", lambda: denied)
    monkeypatch.setattr(
        api_server,
        "activate_registry_terminal_restricted_startup",
        lambda authorization: events.append("registry_recovery") or True,
        raising=False,
    )
    monkeypatch.setattr(
        api_server,
        "activate_wallet_setup_bootstrap",
        lambda authorization: events.append("generic_bootstrap") or False,
    )

    assert desktop._authorize_desktop_startup() is True
    assert events == ["registry_recovery", "arbiter_released"]


def test_registry_blocked_startup_does_not_reconcile_before_operator_review(
    monkeypatch,
):
    import api_server
    import database

    desktop = _desktop(monkeypatch)
    denied = {"allowed": False, "reason_code": "REGISTRY_BLOCKED"}
    recovered = []
    monkeypatch.setattr(database, "init_database", lambda: None)
    monkeypatch.setattr(desktop, "_retire_expired_dead_startup_lease", lambda: None)
    monkeypatch.setattr(api_server, "initialize_mutation_runtime", lambda: denied)
    monkeypatch.setattr(
        api_server,
        "recover_legacy_startup_reservations",
        lambda: recovered.append(True) or {"recovered": 6, "remaining": 0},
    )

    assert desktop._initialize_startup_ownership() == denied
    assert recovered == []


def test_registry_recovery_window_has_no_trading_bridge(monkeypatch):
    import api_server

    desktop = _desktop(monkeypatch)
    monkeypatch.setattr(
        api_server, "_registry_terminal_recovery_active", True, raising=False
    )
    assert desktop._create_desktop_bridge() is None


def test_registry_recovery_http_denies_normal_trading_and_refresh_abort(monkeypatch):
    import api_server

    monkeypatch.setattr(
        api_server, "_registry_terminal_recovery_active", True, raising=False
    )
    for method, path in (
        ("GET", "/api/offers"),
        ("POST", "/api/bot/start"),
        ("POST", "/api/bootstrap/start"),
        ("POST", "/api/offers/refresh_abort/fee_approval"),
        ("POST", "/api/offers/refresh_abort/cancel_next"),
    ):
        with api_server.app.test_request_context(
            path, method=method, environ_base={"REMOTE_ADDR": "127.0.0.1"}
        ):
            response = api_server.enforce_local_runtime_guard()
            assert response is not None, (method, path)
            assert response[1] == 423, (method, path)
            assert response[0].get_json()["error"] == "registry_terminal_recovery_only"


def test_registry_recovery_cannot_show_normal_dashboard(monkeypatch):
    import api_server

    monkeypatch.setattr(
        api_server, "_registry_terminal_recovery_active", True, raising=False
    )
    with api_server.app.test_request_context(
        "/", headers={api_server._LOCAL_API_TOKEN_HEADER: api_server._LOCAL_API_TOKEN}
    ):
        response = api_server.serve_gui()
    assert response.status_code == 200
    assert b"Verify Terminal Offers" in response.data
    assert b"Start Bot Now" not in response.data
    assert b"Bot" not in response.data


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "mixed_visible_without_journal",
        "wrong_unknown_journal",
        "extra_blocker",
        "wrong_asset",
        "not_elapsed",
        "other_campaign",
    ],
)
def test_registry_startup_candidate_requires_exact_elapsed_cohort(monkeypatch, change):
    import api_server
    import database
    import mutation_gate

    campaign_id = "a" * 64
    asset_id = "b" * 64
    intent_id = "c" * 64
    wallet_hash = mutation_gate.wallet_fingerprint_hash(3702373391)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    campaign = {
        "campaign_id": campaign_id,
        "status": "active",
        "asset_id": asset_id,
        "network": "mainnet",
        "wallet_fingerprint": 3702373391,
        "wallet_id": 2,
        "revision": 0,
        "expires_at": future if change == "not_elapsed" else expired,
    }
    intent = {
        "intent_id": intent_id,
        "wallet_fingerprint_hash": wallet_hash,
        "network": "mainnet",
        "asset_id": "d" * 64 if change == "wrong_asset" else asset_id,
        "purpose": f"bootstrap:{campaign_id}:revision:0",
        "lifecycle_state": "unknown",
        "sage_trade_id": "e" * 64,
        "parent_intent_id": None,
        "child_intent_id": None,
    }
    blockers = [f"reconcile:{intent_id}"]
    intents = [intent]
    if change == "mixed_visible_without_journal":
        for index in range(5):
            visible = {
                **intent,
                "intent_id": f"{index + 1:064x}",
                "sage_trade_id": f"{index + 11:064x}",
                "lifecycle_state": "visible",
            }
            intents.append(visible)
            blockers.append(f"reconcile:{visible['intent_id']}")
    if change == "extra_blocker":
        blockers.append("create:other")
    latch = {
        "state": "tripped",
        "reason_code": "REGISTRY_BLOCKED",
        "generation": 150,
        "wallet_fingerprint_hash": wallet_hash,
        "network": "mainnet",
        "blocking_operation_ids_json": json.dumps(blockers),
    }
    monkeypatch.setattr(
        api_server,
        "cfg",
        SimpleNamespace(
            WALLET_TYPE="sage", CAT_ASSET_ID=asset_id, SAGE_FINGERPRINT="3702373391"
        ),
    )
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: (wallet_hash, "mainnet")
    )
    monkeypatch.setattr(
        database,
        "get_active_bootstrap_campaign",
        lambda *_args: campaign,
    )
    monkeypatch.setattr(
        database,
        "list_active_bootstrap_campaigns_for_asset",
        lambda *_args: (
            [campaign, dict(campaign, campaign_id="f" * 64)]
            if change == "other_campaign"
            else [campaign]
        ),
    )
    monkeypatch.setattr(database, "get_offer_intents_for_registry", lambda: intents)
    monkeypatch.setattr(database, "get_runtime_safety_latch", lambda: latch)
    monkeypatch.setattr(
        database,
        "get_runtime_mutation_lease",
        lambda: {"active": 0, "lease_version": 1},
    )
    monkeypatch.setattr(
        database,
        "get_unresolved_offer_operation_blockers",
        lambda: [
            {
                "operation_id": f"reconcile:{intent_id}",
                "intent_id": intent_id,
                "operation_type": "RECONCILE",
                "outcome": "CONFLICT"
                if change == "wrong_unknown_journal"
                else "UNKNOWN",
                "blocks_mutation": 1,
            }
        ],
    )

    result = api_server.has_exact_registry_terminal_startup_candidate()
    assert result is (change in {"valid", "mixed_visible_without_journal"})


@pytest.mark.parametrize("change", ["valid", "pending", "book_changed", "stale"])
def test_registry_startup_preflight_requires_two_stable_sage_reads(monkeypatch, change):
    import api_server
    import mutation_gate

    asset_id = "b" * 64
    campaign_id = "a" * 64
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Harvestr",
        fingerprint=3702373391,
        network_id="mainnet",
        kind="private",
        has_secrets=True,
        bound_at_utc=datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=60,
    )
    monkeypatch.setattr(
        api_server, "cfg", SimpleNamespace(WALLET_TYPE="sage", CAT_ASSET_ID=asset_id)
    )
    monkeypatch.setattr(
        api_server,
        "has_exact_registry_terminal_startup_candidate",
        lambda **_kw: True,
        raising=False,
    )
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: (mutation_gate.wallet_fingerprint_hash(3702373391), "mainnet"),
    )
    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", lambda _net: binding
    )
    monkeypatch.setattr(
        api_server, "_read_distinct_wallet_identity_snapshots", lambda _read: ({}, {})
    )
    monkeypatch.setattr(api_server.wallet, "get_wallet_identity", lambda: {})
    first_at = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    second_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    identity_times = iter([first_at, second_at])
    monkeypatch.setattr(
        mutation_gate,
        "validate_wallet_identity",
        lambda *_args, **_kw: {
            "allowed": True,
            "observed_at_utc": next(identity_times),
        },
    )
    book_times = [
        (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat(),
        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    ]
    if change == "stale":
        book_times[1] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    books = iter(
        [
            {
                "trade_ids": [],
                "pending_transaction_ids": [],
                "observed_at": book_times[0],
            },
            {
                "trade_ids": ["e" * 64] if change == "book_changed" else [],
                "pending_transaction_ids": ["f" * 64] if change == "pending" else [],
                "observed_at": book_times[1],
            },
        ]
    )
    monkeypatch.setattr(
        api_server.wallet, "_read_refresh_abort_cleanup_snapshot", lambda: next(books)
    )
    monkeypatch.setattr(
        api_server.database,
        "get_active_bootstrap_campaign",
        lambda *_args: {"campaign_id": campaign_id, "revision": 0},
    )
    monkeypatch.setattr(
        api_server.database,
        "get_runtime_safety_latch",
        lambda: {"generation": 150, "blocking_operation_ids_json": "[]"},
    )

    result = api_server.preflight_registry_terminal_restricted_startup()
    assert result["eligible"] is (change == "valid")
    if change == "valid":
        assert result["campaign_id"] == campaign_id
        assert result["revision"] == 0
        assert result["latch_generation"] == 150


@pytest.mark.parametrize("prior", ["dead", "active", "uncertain"])
def test_registry_successor_requires_expired_dead_prior_owner(monkeypatch, prior):
    import database
    import mutation_gate

    now = datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)
    wallet_hash = mutation_gate.wallet_fingerprint_hash(3702373391)
    gate = mutation_gate.MutationGate(
        run_id="new-recovery-owner",
        owner_pid=111,
        owner_host="test-host",
        wallet_fingerprint_hash=wallet_hash,
        network="mainnet",
        lease_seconds=30,
        clock=lambda: now,
        pid_liveness=lambda _pid, _host: None if prior == "uncertain" else False,
    )
    current = {
        "active": 1,
        "lease_version": 10,
        "owner_run_id": "prior-owner",
        "owner_pid": 222,
        "owner_host": "test-host",
        "expires_at": (
            now
            + (timedelta(seconds=30) if prior == "active" else -timedelta(seconds=1))
        ).isoformat(),
    }
    monkeypatch.setattr(gate, "_authorization_snapshot", lambda: {"lease": current})
    monkeypatch.setattr(
        mutation_gate, "_rotate_owner_identity_authority", lambda _gate: True
    )
    calls = []

    def adopt(**kwargs):
        calls.append(kwargs)
        return {
            "adopted": True,
            "lease": {
                **current,
                "active": 1,
                "lease_version": 11,
                "owner_run_id": gate.run_id,
                "acquired_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=30)).isoformat(),
            },
        }

    monkeypatch.setattr(
        database, "adopt_registry_terminal_successor", adopt, raising=False
    )
    result = gate.acquire_registry_terminal_successor(
        campaign_id="a" * 64,
        revision=0,
        asset_id="b" * 64,
        latch_generation=150,
        blocking_operation_ids=["reconcile:" + "c" * 64],
        observed_trade_ids=[],
        observed_pending_transaction_ids=[],
        observed_at=now.isoformat(),
    )
    assert result["acquired"] is (prior == "dead")
    assert len(calls) == (1 if prior == "dead" else 0)
    if calls:
        assert calls[0]["prior_owner_liveness_proven_dead"] is True


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "mixed_visible_without_journal",
        "wrong_unknown_journal",
        "live_owner",
        "pid_changed",
        "wrong_generation",
        "extra_blocker",
        "pending",
        "other_root",
        "creation_failed_other_root",
    ],
)
def test_registry_successor_database_cas_is_exact(tmp_path, monkeypatch, change):
    import database
    import mutation_gate

    database.close_connection()

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "registry-cas.db"))
    database._db_initialized = False
    database._db_initialized_path = None
    database.init_database()
    now = datetime.now(timezone.utc)
    at = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
    old = (
        (now - timedelta(minutes=2))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    campaign_id = "a" * 64
    asset = "b" * 64
    intent_id = "c" * 64
    trade_id = "d" * 64
    wallet_hash = mutation_gate.wallet_fingerprint_hash(3702373391)
    blocker = f"reconcile:{intent_id}"
    latch_blockers = [blocker]
    coins = json.dumps(["e" * 64], separators=(",", ":"))
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO bootstrap_campaigns (campaign_id,network,wallet_type,"
        "wallet_fingerprint,wallet_id,asset_id,anchor_price,minimum_price,"
        "maximum_price,xch_budget,cat_budget,fee_budget_xch,subsidy_budget_xch,"
        "created_at,expires_at,current_anchor_price,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            campaign_id,
            "mainnet",
            "sage",
            3702373391,
            2,
            asset,
            "0.01",
            "0.005",
            "0.02",
            "10",
            "100000",
            "0.05",
            "0",
            old,
            old,
            "0.01",
            old,
        ),
    )
    purpose = f"bootstrap:{campaign_id}:revision:0"
    conn.execute(
        "INSERT INTO offer_intents (intent_id,run_id,wallet_fingerprint_hash,"
        "network,asset_id,side,tier,purpose,offered_amount_atomic,"
        "requested_amount_atomic,selected_coin_ids_json,selected_coin_ids_sha256,"
        "sage_trade_id,lifecycle_state,prepared_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            intent_id,
            "prior-owner",
            wallet_hash,
            "mainnet",
            asset,
            "buy",
            "inner",
            purpose,
            "1000",
            "2000",
            coins,
            hashlib.sha256(coins.encode()).hexdigest(),
            trade_id,
            "unknown",
            old,
            old,
        ),
    )
    evidence = "{}"
    conn.execute(
        "INSERT INTO offer_operation_journal (event_id,operation_id,intent_id,"
        "operation_type,attempt,phase,outcome,request_timestamp,evidence_json,"
        "evidence_sha256,blocks_mutation,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "registry-blocker",
            blocker,
            intent_id,
            "RECONCILE",
            1,
            "PREPARED",
            "CONFLICT" if change == "wrong_unknown_journal" else "UNKNOWN",
            old,
            evidence,
            hashlib.sha256(evidence.encode()).hexdigest(),
            1,
            old,
        ),
    )
    if change == "mixed_visible_without_journal":
        for index in range(5):
            visible_id = f"{index + 1:064x}"
            latch_blockers.append(f"reconcile:{visible_id}")
            conn.execute(
                "INSERT INTO offer_intents (intent_id,run_id,wallet_fingerprint_hash,"
                "network,asset_id,side,tier,purpose,offered_amount_atomic,"
                "requested_amount_atomic,selected_coin_ids_json,selected_coin_ids_sha256,"
                "sage_trade_id,lifecycle_state,prepared_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    visible_id,
                    "prior-owner",
                    wallet_hash,
                    "mainnet",
                    asset,
                    "sell",
                    "inner",
                    purpose,
                    "1000",
                    "2000",
                    coins,
                    hashlib.sha256(coins.encode()).hexdigest(),
                    f"{index + 11:064x}",
                    "visible",
                    old,
                    old,
                ),
            )
    conn.execute(
        "UPDATE runtime_mutation_lease SET lease_version=10,active=1,"
        "owner_run_id='prior-owner',owner_pid=222,owner_host='test-host',"
        "wallet_fingerprint_hash=?,network='mainnet',acquired_at=?,"
        "heartbeat_at=?,expires_at=?,updated_at=? WHERE singleton_id=1",
        (wallet_hash, old, old, old, old),
    )
    conn.execute(
        "UPDATE runtime_safety_latch SET generation=150,state='tripped',"
        "reason_code='REGISTRY_BLOCKED',blocking_operation_ids_json=?,"
        "wallet_fingerprint_hash=?,network='mainnet',tripped_at=?,updated_at=? "
        "WHERE singleton_id=1",
        (json.dumps(latch_blockers), wallet_hash, old, old),
    )
    if change == "live_owner":
        conn.execute(
            "UPDATE runtime_mutation_lease SET expires_at=? WHERE singleton_id=1",
            ((now + timedelta(minutes=1)).isoformat(),),
        )
    elif change == "pid_changed":
        conn.execute(
            "UPDATE runtime_mutation_lease SET owner_pid=333 WHERE singleton_id=1"
        )
    elif change == "extra_blocker":
        conn.execute(
            "UPDATE runtime_safety_latch SET blocking_operation_ids_json=? "
            "WHERE singleton_id=1",
            (json.dumps([blocker, "unrelated"]),),
        )
    elif change in {"other_root", "creation_failed_other_root"}:
        conn.execute(
            "INSERT INTO offer_intents (intent_id,run_id,wallet_fingerprint_hash,"
            "network,asset_id,side,tier,purpose,offered_amount_atomic,"
            "requested_amount_atomic,selected_coin_ids_json,selected_coin_ids_sha256,"
            "sage_trade_id,lifecycle_state,prepared_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "f" * 64,
                "prior-owner",
                wallet_hash,
                "mainnet",
                asset,
                "sell",
                "inner",
                "unrelated",
                "1000",
                "2000",
                coins,
                hashlib.sha256(coins.encode()).hexdigest(),
                "1" * 64,
                "creation_failed"
                if change == "creation_failed_other_root"
                else "created",
                old,
                old,
            ),
        )
    conn.commit()
    before = dict(database.get_runtime_mutation_lease())
    request = dict(
        campaign_id=campaign_id,
        revision=0,
        asset_id=asset,
        latch_generation=151 if change == "wrong_generation" else 150,
        blocking_operation_ids=latch_blockers,
        successor_owner_run_id="new-owner",
        successor_owner_pid=111,
        successor_owner_host="test-host",
        wallet_fingerprint_hash=wallet_hash,
        network="mainnet",
        expected_lease_version=10,
        expected_prior_owner_run_id="prior-owner",
        expected_prior_owner_pid=222,
        expected_prior_owner_host="test-host",
        expected_prior_acquired_at=old,
        expected_prior_expires_at=(
            (now + timedelta(minutes=1)).isoformat() if change == "live_owner" else old
        ),
        expected_prior_released_at=None,
        lease_expires_at=now + timedelta(minutes=1),
        prior_owner_liveness_proven_dead=True,
        observed_trade_ids=[],
        observed_pending_transaction_ids=["2" * 64] if change == "pending" else [],
        observed_at=at,
    )
    if change in {
        "valid",
        "mixed_visible_without_journal",
        "creation_failed_other_root",
    }:
        adopted = database.adopt_registry_terminal_successor(**request)
        assert adopted["adopted"] is True
        assert adopted["lease"]["owner_run_id"] == "new-owner"
        assert adopted["lease"]["lease_version"] == 11
        assert database.get_runtime_safety_latch()["state"] == "tripped"
        target = database.get_offer_intent(intent_id)
        fence = dict(
            campaign_id=campaign_id,
            revision=0,
            asset_id=asset,
            wallet_fingerprint_hash=wallet_hash,
            network="mainnet",
            owner_run_id="new-owner",
            owner_pid=111,
            owner_host="test-host",
            acquired_at=adopted["lease"]["acquired_at"],
            latch_generation=150,
            blocking_operation_ids=latch_blockers,
            proof_observed_at=at,
            target_intent_id=intent_id,
            target_row_version=target["row_version"],
            target_lifecycle_state="unknown",
        )
        proof = database.fence_mixed_terminal_commit(**fence)
        assert proof["lease_version"] == 11
        assert database.get_runtime_mutation_lease()["lease_version"] == 11
        with pytest.raises(ValueError):
            database.fence_mixed_terminal_commit(
                **{**fence, "owner_run_id": "unrelated-owner"}
            )
        with pytest.raises(ValueError):
            database.fence_mixed_terminal_commit(
                **{**fence, "target_row_version": target["row_version"] + 1}
            )
        with pytest.raises(ValueError):
            database.fence_mixed_terminal_commit(
                **{**fence, "blocking_operation_ids": ["reconcile:unrelated"]}
            )
        with pytest.raises(ValueError, match="proof.*stale"):
            database.fence_mixed_terminal_commit(**{**fence, "proof_observed_at": old})
        if change == "mixed_visible_without_journal":
            visible_id = latch_blockers[1].removeprefix("reconcile:")
            conn.execute(
                "UPDATE offer_intents SET asset_id=? WHERE intent_id=?",
                ("c" * 64, visible_id),
            )
            conn.commit()
            with pytest.raises(ValueError, match="authority changed"):
                database.fence_mixed_terminal_commit(**fence)
            conn.execute(
                "UPDATE offer_intents SET asset_id=? WHERE intent_id=?",
                (asset, visible_id),
            )
            conn.commit()
        conn.execute(
            "UPDATE runtime_mutation_lease SET heartbeat_at=? WHERE singleton_id=1",
            (old,),
        )
        conn.commit()
        with pytest.raises(ValueError, match="authority changed"):
            database.fence_mixed_terminal_commit(**fence)
        if change == "valid":
            # A normal stopped campaign may have an allowed latch and no
            # reconcile blockers. It still needs the exact target/lease fence.
            conn.execute(
                "UPDATE runtime_mutation_lease SET heartbeat_at=? WHERE singleton_id=1",
                (at,),
            )
            conn.execute(
                "INSERT INTO offer_operation_journal (event_id,operation_id,intent_id,"
                "operation_type,attempt,phase,outcome,request_timestamp,evidence_json,"
                "evidence_sha256,blocks_mutation,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "registry-blocker-closed",
                    blocker,
                    intent_id,
                    "RECONCILE",
                    1,
                    "COMPLETED",
                    "EXPIRED_PROVEN",
                    at,
                    evidence,
                    hashlib.sha256(evidence.encode()).hexdigest(),
                    0,
                    at,
                ),
            )
            conn.execute(
                "UPDATE offer_intents SET lifecycle_state='visible',row_version=row_version+1 "
                "WHERE intent_id=?",
                (intent_id,),
            )
            conn.execute(
                "UPDATE runtime_safety_latch SET state='resolved',reason_code=NULL,"
                "blocking_operation_ids_json='[]' WHERE singleton_id=1"
            )
            conn.commit()
            visible = database.get_offer_intent(intent_id)
            allowed_fence = {
                **fence,
                "blocking_operation_ids": [],
                "target_row_version": visible["row_version"],
                "target_lifecycle_state": "visible",
            }
            assert (
                database.fence_mixed_terminal_commit(**allowed_fence)["lease_version"]
                == 11
            )
            # A clean profile starts resolved at generation zero, with no
            # historical wallet or network binding in the latch.
            conn.execute(
                "UPDATE runtime_safety_latch SET generation=0,"
                "wallet_fingerprint_hash=NULL,network=NULL WHERE singleton_id=1"
            )
            conn.commit()
            assert (
                database.fence_mixed_terminal_commit(
                    **{**allowed_fence, "latch_generation": 0}
                )["lease_version"]
                == 11
            )
            conn.execute(
                "UPDATE runtime_safety_latch SET wallet_fingerprint_hash=? "
                "WHERE singleton_id=1",
                (wallet_hash,),
            )
            conn.commit()
            with pytest.raises(ValueError, match="authority changed"):
                database.fence_mixed_terminal_commit(
                    **{**allowed_fence, "latch_generation": 0}
                )
    else:
        with pytest.raises(ValueError):
            database.adopt_registry_terminal_successor(**request)
        assert dict(database.get_runtime_mutation_lease()) == before
    database.close_connection()


@pytest.mark.parametrize(
    "change",
    ["stable", "changed_blocker", "changed_book", "changed_owner", "heartbeat_failed"],
)
def test_registry_restricted_activation_rechecks_and_releases_on_failure(
    monkeypatch, change
):
    import api_server
    import mutation_gate

    wallet_hash = mutation_gate.wallet_fingerprint_hash(3702373391)
    asset = "b" * 64
    blocker = "reconcile:" + "c" * 64
    proof = {
        "eligible": True,
        "campaign_id": "a" * 64,
        "revision": 0,
        "latch_generation": 150,
        "blocking_operation_ids": [blocker],
        "wallet_snapshot": {
            "trade_ids": [],
            "pending_transaction_ids": [],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", False)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "cfg", SimpleNamespace(CAT_ASSET_ID=asset))
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: (wallet_hash, "mainnet")
    )
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Harvestr",
        fingerprint=3702373391,
        network_id="mainnet",
        kind="private",
        has_secrets=True,
        bound_at_utc=datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=60,
    )
    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", lambda _net: binding
    )
    monkeypatch.setattr(api_server, "get_wallet_adapter_authority", lambda: object())
    reads = []

    def preflight(**kwargs):
        reads.append(kwargs)
        if len(reads) == 2 and change == "changed_blocker":
            return {**proof, "blocking_operation_ids": ["reconcile:" + "d" * 64]}
        if len(reads) == 2 and change == "changed_book":
            return {
                **proof,
                "wallet_snapshot": {
                    **proof["wallet_snapshot"],
                    "trade_ids": ["d" * 64],
                },
            }
        return proof

    monkeypatch.setattr(
        api_server, "preflight_registry_terminal_restricted_startup", preflight
    )
    events = []

    class Runtime:
        run_id = "new-owner"
        owner_pid = 111
        owner_host = "test-host"
        _lease_acquired_at = "2026-10-18T08:00:00.000000Z"

        def acquire_registry_terminal_successor(self, **kwargs):
            events.append(("adopt", kwargs))
            return {"acquired": True}

        def status(self):
            return SimpleNamespace(
                to_dict=lambda: {
                    "allowed": False,
                    "reason_code": "REGISTRY_BLOCKED",
                    "source": "durable_latch",
                    "lease": {
                        "active": True,
                        "owned_by_this_run": True,
                        "owner_run_id": self.run_id,
                        "version": 11,
                    },
                }
            )

        def register_stop_handler(self, _handler):
            events.append(("stop_handler", None))

        def start_heartbeat(self):
            events.append(("heartbeat", None))
            return change != "heartbeat_failed"

    runtime = Runtime()
    monkeypatch.setattr(
        api_server.database,
        "get_runtime_mutation_lease",
        lambda: {
            "owner_run_id": "other-owner"
            if change == "changed_owner"
            else runtime.run_id,
            "owner_pid": runtime.owner_pid,
            "owner_host": runtime.owner_host,
            "acquired_at": runtime._lease_acquired_at,
            "lease_version": 11,
        },
    )
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(mutation_gate, "initialize", lambda **_kw: runtime)
    monkeypatch.setattr(
        mutation_gate,
        "shutdown_runtime",
        lambda **kw: events.append(("shutdown", kw)),
    )
    allowed = api_server.activate_registry_terminal_restricted_startup(
        {"allowed": False, "reason_code": "REGISTRY_BLOCKED"}
    )
    assert allowed is (change == "stable")
    assert len(reads) == 2
    assert events[0][0] == "adopt"
    assert (
        ("shutdown", {"release_owned_lease": True}) in events if not allowed else True
    )
    assert api_server._registry_terminal_recovery_active is allowed
    monkeypatch.setattr(api_server, "_registry_terminal_recovery_active", False)
    monkeypatch.setattr(api_server, "_mutation_runtime", None)
    monkeypatch.setattr(api_server, "_mutation_runtime_db_path", None)
