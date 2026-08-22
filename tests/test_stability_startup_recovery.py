import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import database
import mutation_gate


NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
AT = NOW.isoformat(timespec="microseconds").replace("+00:00", "Z")
WALLET_HASH = "f" * 64
ASSET_ID = "a" * 64


_ORDERED_CHECKS = (
    "lease",
    "wallet_identity_freshness",
    "unresolved_operations",
    "reservations",
    "publication_claims",
    "authority_revalidation",
)


def _fake_gate_status(*, allowed=False, reason_code="STARTUP_RECOVERY_PENDING"):
    return {
        "allowed": allowed,
        "reason_code": reason_code,
        "source": "startup_recovery",
        "blocking_operation_ids": [],
        "blocking_operation_count": 0,
        "lease": {
            "active": False,
            "version": 0,
            "expires_at": None,
            "owner_run_id": None,
            "owner_pid": None,
            "owned_by_this_run": False,
        },
    }


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    mutation_gate.shutdown_runtime(release_owned_lease=True)
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "task10.db"))
    database._db_initialized_path = ""
    database.init_database()
    yield tmp_path / "task10.db"
    mutation_gate.shutdown_runtime(release_owned_lease=True)
    database.close_connection()


def _seed_prepared_creation(*, coin_id="1" * 64, intent_id="intent-prepared"):
    assert database.upsert_coin(
        coin_id,
        "xch",
        1_000_000,
        designation="tier_spare",
        tier="inner",
        purpose="lifecycle",
    )
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="task10-run",
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        asset_id=ASSET_ID,
        side="buy",
        tier="inner",
        purpose="task10_startup",
        offered_amount_atomic="1000000",
        requested_amount_atomic="2000000",
        selected_coin_ids_json=[coin_id],
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
        },
        evidence_json={"fixture": "task10 prepared creation"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    return coin_id, intent_id


def _seed_submitted_cancel():
    from cancel_outcomes import CANCEL_SUBMITTED_UNCONFIRMED, cancellation_result

    trade_id = "2" * 64
    operation_id = f"cancel:{trade_id}"
    wallet_identity = {
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": "mainnet",
    }
    database.prepare_offer_cancel(
        operation_id=operation_id,
        event_id=f"{operation_id}:attempt:1:prepared",
        trade_id=trade_id,
        intent_id=None,
        attempt=1,
        wallet_identity_json=wallet_identity,
        evidence_json={"trade_id": trade_id},
        prepared_at=AT,
    )
    result = cancellation_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        method="task10_fixture",
        transaction_id="3" * 64,
    )
    database.finalize_offer_cancel(
        operation_id=operation_id,
        event_id=f"{operation_id}:attempt:1:finalized",
        trade_id=trade_id,
        intent_id=None,
        attempt=1,
        cancel_result=result,
        wallet_identity_json=wallet_identity,
        evidence_json={"trade_id": trade_id, "cancel_result": result},
        finalized_at=AT,
    )


def test_database_integrity_failure_never_promotes_mutation_runtime(monkeypatch):
    import api_server

    calls = []
    fake_gate = SimpleNamespace(
        register_stop_handler=lambda _handler: None,
        status=lambda: SimpleNamespace(
            to_dict=lambda: {
                "allowed": True,
                "reason_code": "",
                "source": "lease",
                "blocking_operation_ids": [],
                "blocking_operation_count": 0,
                "lease": {
                    "active": True,
                    "version": 1,
                    "expires_at": "2099-01-01T00:00:00.000000Z",
                    "owner_run_id": "must-not-be-exposed",
                    "owner_pid": 123,
                    "owned_by_this_run": True,
                },
            }
        ),
    )

    monkeypatch.setattr(
        api_server.database,
        "check_db_integrity",
        lambda: (
            calls.append("database_integrity")
            or {"ok": False, "result": "corrupt", "errors": ["corrupt"]}
        ),
    )

    def initialize_gate(**kwargs):
        calls.append(f"mutation_runtime:{kwargs['acquire_lease']}")
        return fake_gate

    monkeypatch.setattr(api_server.mutation_gate, "initialize", initialize_gate)

    result = api_server.initialize_mutation_runtime(
        start_heartbeat=False,
        acquire_lease=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "DATABASE_INTEGRITY_FAILED"
    assert calls == ["database_integrity"]


@pytest.mark.parametrize(
    ("failed_check", "reason_code"),
    [
        ("lease", "LEASE_OWNED_BY_OTHER"),
        ("wallet_identity_freshness", "WALLET_IDENTITY_STALE"),
        ("unresolved_operations", "UNRESOLVED_OPERATIONS"),
        ("reservations", "RESERVATION_RECONCILIATION_REQUIRED"),
        ("publication_claims", "PUBLICATION_CLAIM_RECOVERY_REQUIRED"),
        ("authority_revalidation", "STARTUP_AUTHORITY_CHANGED"),
    ],
)
def test_ordered_startup_blocker_never_reaches_mutation_promotion(
    monkeypatch,
    failed_check,
    reason_code,
):
    import api_server

    calls = []
    fake_gate = SimpleNamespace(
        register_stop_handler=lambda _handler: None,
        status=lambda: SimpleNamespace(to_dict=lambda: _fake_gate_status()),
    )
    monkeypatch.setattr(
        api_server.database,
        "check_db_integrity",
        lambda: (
            calls.append("database_integrity")
            or {"ok": True, "result": "ok", "errors": []}
        ),
    )

    def initialize_gate(**kwargs):
        calls.append(f"mutation_runtime:{kwargs['acquire_lease']}")
        return fake_gate

    monkeypatch.setattr(api_server.mutation_gate, "initialize", initialize_gate)

    def run_check(name, **_context):
        calls.append(name)
        if name == failed_check:
            return {
                "ok": False,
                "reason_code": reason_code,
                "source_age_seconds": None,
                "blocker_counts": {},
            }
        return {
            "ok": True,
            "reason_code": "",
            "source_age_seconds": 0,
            "blocker_counts": {},
        }

    monkeypatch.setattr(
        api_server,
        "_run_stability_startup_check",
        run_check,
        raising=False,
    )

    result = api_server.initialize_mutation_runtime(
        start_heartbeat=False,
        acquire_lease=True,
    )

    failed_index = _ORDERED_CHECKS.index(failed_check)
    assert result["allowed"] is False
    assert result["reason_code"] == reason_code
    assert calls == [
        "database_integrity",
        "mutation_runtime:False",
        *_ORDERED_CHECKS[: failed_index + 1],
    ]
    assert "mutation_runtime:True" not in calls


def test_prepared_creation_and_submitted_cancel_are_exact_operation_blockers(
    isolated_database,
):
    _seed_prepared_creation()
    _seed_submitted_cancel()

    snapshot = database.get_stability_startup_recovery_snapshot()

    assert snapshot["blocker_counts"] == {
        "operations": 2,
        "prepared_creations": 1,
        "submitted_cancels": 1,
        "contradictory_history": 0,
        "reservations": 0,
        "publication_claims": 0,
    }
    assert [row["operation_type"] for row in snapshot["blockers"]] == [
        "CREATE",
        "CANCEL",
    ]


def test_nonterminal_intent_without_exact_selected_coin_lock_blocks_restart(
    isolated_database,
):
    coin_id, intent_id = _seed_prepared_creation(
        coin_id="4" * 64,
        intent_id="intent-reservation-gap",
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id="5" * 64,
        offer_text_sha256="6" * 64,
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
        },
        evidence_json={"fixture": "task10 reservation gap"},
        finalized_at=AT,
        finalize_selected_coin_reservations=False,
    )
    database.get_connection().execute(
        "UPDATE coins SET status='free', trade_id=NULL WHERE coin_id=?",
        (database.norm_coin_id(coin_id),),
    )
    database.get_connection().commit()

    snapshot = database.get_stability_startup_recovery_snapshot()

    assert snapshot["blockers"] == []
    assert snapshot["blocker_counts"]["reservations"] == 1
    assert snapshot["reservation_issues"] == [f"intent:{intent_id}"]


def test_claimed_publication_is_retained_as_restart_blocker(isolated_database):
    database.enqueue_publication_outbox(
        publication_id="publication-task10",
        idempotency_key=f"mainnet:{'7' * 64}:task10-epoch",
        network="mainnet",
        offer_fingerprint="7" * 64,
        publication_epoch="task10-epoch",
        publisher="dexie",
        payload_json={"offer": "redacted"},
        queued_at=AT,
    )
    conn = database.get_connection()
    conn.execute(
        "UPDATE publication_outbox SET state='claimed', claim_owner_run_id=?, "
        "claim_expires_at=?, updated_at=? WHERE publication_id=?",
        (
            "prior-run",
            (NOW + timedelta(minutes=5))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            AT,
            "publication-task10",
        ),
    )
    conn.commit()

    snapshot = database.get_stability_startup_recovery_snapshot()

    assert snapshot["blocker_counts"]["publication_claims"] == 1
    assert snapshot["publication_issues"] == ["publication-task10"]


def test_contradictory_history_is_counted_without_inventing_terminality(
    isolated_database,
):
    database.append_offer_operation_event(
        event_id="reconcile:conflict:attempt:1:finalized",
        operation_id="reconcile:conflict",
        operation_type="RECONCILE",
        attempt=1,
        phase="FINALIZED",
        outcome="CONFLICT",
        request_timestamp=AT,
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
        },
        evidence_json={"fixture": "contradictory history"},
        reason_code="RECONCILIATION_CONFLICT",
        blocks_mutation=True,
        created_at=AT,
    )

    snapshot = database.get_stability_startup_recovery_snapshot()

    assert snapshot["blocker_counts"]["contradictory_history"] == 1
    assert snapshot["blockers"][0]["outcome"] == "CONFLICT"


@pytest.mark.parametrize(
    ("owner_liveness", "expected_ok", "expected_reason"),
    [
        (None, False, "LEASE_EXPIRED"),
        (False, True, ""),
    ],
)
def test_stale_lease_requires_proven_dead_owner_before_recovery(
    monkeypatch,
    owner_liveness,
    expected_ok,
    expected_reason,
):
    import api_server

    stale_at = (
        (datetime.now(timezone.utc) - timedelta(seconds=60))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    snapshot = {
        "lease": {
            "active": 1,
            "owner_pid": 123,
            "owner_host": "prior-host",
            "heartbeat_at": stale_at,
            "expires_at": stale_at,
        }
    }
    monkeypatch.setattr(
        api_server.database,
        "get_stability_startup_recovery_snapshot",
        lambda: snapshot,
    )
    runtime = SimpleNamespace(_pid_liveness=lambda _pid, _host: owner_liveness)
    state = {}

    result = api_server._run_stability_startup_check(
        "lease",
        state=state,
        runtime=runtime,
        wallet_identity_binding=object(),
    )

    assert result["ok"] is expected_ok
    assert result["reason_code"] == expected_reason
    assert state["initial_snapshot"] is snapshot


def test_stale_sage_identity_snapshot_blocks_before_operation_recovery(monkeypatch):
    import api_server

    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Task 10 Wallet",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        maximum_age_seconds=5,
    )
    stale_at = (
        (datetime.now(timezone.utc) - timedelta(seconds=30))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    cached_snapshot = {
        "success": True,
        "backend": "sage",
        "name": "Task 10 Wallet",
        "fingerprint": 123456789,
        "network_id": "mainnet",
        "kind": "bls",
        "has_secrets": True,
        "observed_at_utc": stale_at,
    }

    result = api_server._run_stability_startup_check(
        "wallet_identity_freshness",
        state={"initial_snapshot": {}},
        runtime=object(),
        wallet_identity_binding=binding,
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network="mainnet",
        cached_wallet_identity_snapshot=cached_snapshot,
    )

    assert result["ok"] is False
    assert result["reason_code"] == "WALLET_IDENTITY_STALE"
    assert result["source_age_seconds"] >= 30


def test_clean_restart_promotes_from_config_binding_without_identity_rpc(
    isolated_database,
    monkeypatch,
):
    import api_server

    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_NAME", "Task 10 Wallet", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 15, raising=False
    )
    binding_time = datetime.now(timezone.utc) - timedelta(seconds=2)
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="Task 10 Wallet",
        fingerprint=123456789,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc=binding_time.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        maximum_age_seconds=15,
    )
    monkeypatch.setattr(
        api_server,
        "_configured_wallet_identity_binding",
        lambda _network: binding,
    )

    result = api_server.initialize_mutation_runtime(
        start_heartbeat=False,
        acquire_lease=True,
    )

    assert result["allowed"] is True, result
    assert result["reason_code"] == ""
    assert [check["name"] for check in result["checks"]] == list(_ORDERED_CHECKS)
    identity_checks = [
        check
        for check in result["checks"]
        if check["name"] in {"wallet_identity_freshness", "authority_revalidation"}
    ]
    assert [check["source"] for check in identity_checks] == [
        "configured_binding",
        "configured_binding",
    ]
    assert all(check["source_age_seconds"] is None for check in identity_checks)
    assert mutation_gate.status().allowed is True


def test_bot_loop_blocks_before_any_startup_recovery_mutation(monkeypatch):
    import bot_loop

    calls = []

    def deny_startup_recovery(operation):
        calls.append(f"authority:{operation}")
        raise mutation_gate.MutationBlocked("UNRESOLVED_OPERATIONS", operation)

    monkeypatch.setattr(
        bot_loop,
        "mutation_gate",
        SimpleNamespace(
            MutationBlocked=mutation_gate.MutationBlocked,
            require_allowed=deny_startup_recovery,
        ),
        raising=False,
    )
    loop = SimpleNamespace(
        _running=False,
        _stop_finalize_thread=None,
        _set_state=lambda **_state: calls.append("blocked_state"),
        _reset_runtime_state=lambda: pytest.fail(
            "runtime reset occurred before startup authority"
        ),
    )

    result = bot_loop.BotLoop.start(loop)

    assert result is False
    assert calls == ["authority:startup:bot_loop_recovery", "blocked_state"]


def test_preconsent_startup_uses_config_authority_without_wallet_rpc(
    isolated_database,
    monkeypatch,
):
    import api_server
    import wallet

    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_NAME", "Task 10 Wallet", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 15, raising=False
    )
    rpc_calls = []

    def forbidden_identity_rpc():
        rpc_calls.append("wallet_identity_rpc")
        raise AssertionError("pre-consent startup attempted wallet RPC")

    monkeypatch.setattr(wallet, "get_wallet_identity", forbidden_identity_rpc)

    result = api_server.initialize_mutation_runtime(
        start_heartbeat=False,
        acquire_lease=True,
    )

    assert result["allowed"] is True, result
    assert rpc_calls == []
    identity_check = next(
        check
        for check in result["checks"]
        if check["name"] == "wallet_identity_freshness"
    )
    assert identity_check["source"] == "configured_binding"
    assert identity_check["source_age_seconds"] is None

    binding = api_server._configured_wallet_identity_binding("mainnet")
    stale_at = (
        (datetime.now(timezone.utc) - timedelta(seconds=60))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    stale = api_server._run_stability_startup_check(
        "wallet_identity_freshness",
        state={"initial_snapshot": {}},
        runtime=object(),
        wallet_identity_binding=binding,
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(
            binding.fingerprint
        ),
        network="mainnet",
        cached_wallet_identity_snapshot={
            "success": True,
            "backend": "sage",
            "name": "Task 10 Wallet",
            "fingerprint": 123456789,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": stale_at,
        },
    )
    assert stale["ok"] is False
    assert stale["reason_code"] == "WALLET_IDENTITY_STALE"
    assert stale["source"] == "authorized_snapshot"


def test_snapshot_blocks_complete_coin_and_publication_authority_gaps(
    isolated_database,
):
    selected_coin_id = "8" * 64
    source_intent_id = "spent-source"
    source_trade_id = "9" * 64
    assert database.upsert_coin(
        selected_coin_id,
        "xch",
        1_000_000,
        designation="tier_spare",
        tier="inner",
        purpose="lifecycle",
    )
    database.prepare_offer_intent(
        intent_id=source_intent_id,
        operation_id=f"create:{source_intent_id}",
        event_id=f"create:{source_intent_id}:prepared",
        run_id="task10-spent-source",
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        asset_id=ASSET_ID,
        side="buy",
        tier="inner",
        purpose="task10_spent_source",
        offered_amount_atomic="1000000",
        requested_amount_atomic="2000000",
        selected_coin_ids_json=[selected_coin_id],
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
        },
        evidence_json={"fixture": "task10 spent source"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    database.finalize_offer_intent(
        intent_id=source_intent_id,
        operation_id=f"create:{source_intent_id}",
        event_id=f"create:{source_intent_id}:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=source_trade_id,
        offer_text_sha256="a" * 64,
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
        },
        evidence_json={"fixture": "task10 spent source confirmed"},
        finalized_at=AT,
        finalize_selected_coin_reservations=True,
    )
    terminal_event = database.append_offer_operation_event(
        event_id=f"reconcile:{source_intent_id}:attempt:1:finalized",
        operation_id=f"reconcile:{source_intent_id}",
        intent_id=source_intent_id,
        operation_type="RECONCILE",
        attempt=1,
        phase="FINALIZED",
        outcome="CANCELLED_PROVEN",
        request_timestamp=AT,
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
        },
        transaction_id="b" * 64,
        evidence_json={"fixture": "task10 permanent spent"},
        reason_code="TASK10_PERMANENT_SPENT",
        blocks_mutation=False,
        created_at=AT,
    )
    conn = database.get_connection()
    conn.execute(
        "UPDATE offer_intents SET lifecycle_state='terminal', terminal_at=?, "
        "updated_at=? WHERE intent_id=?",
        (AT, AT, source_intent_id),
    )
    conn.execute(
        "INSERT INTO offer_reconciliation_coin_outcomes "
        "(coin_id,intent_id,trade_id,outcome,disposition,terminal_event_id,"
        "evidence_sha256,recorded_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            database.norm_coin_id(selected_coin_id),
            source_intent_id,
            source_trade_id,
            "CANCELLED_PROVEN",
            "spent",
            terminal_event["event_id"],
            terminal_event["evidence_sha256"],
            AT,
        ),
    )
    source = dict(
        conn.execute(
            "SELECT * FROM offer_intents WHERE intent_id=?", (source_intent_id,)
        ).fetchone()
    )
    source.update(
        {
            "intent_id": "spent-overlap",
            "run_id": "task10-overlap-run",
            "slot_key": "task10-overlap-slot",
            "parent_intent_id": None,
            "child_intent_id": None,
            "offer_text_sha256": None,
            "sage_trade_id": None,
            "publication_identity": None,
            "lifecycle_state": "prepared",
            "row_version": 0,
            "submitted_at": None,
            "confirmed_at": None,
            "first_visible_at": None,
            "terminal_at": None,
            "updated_at": AT,
        }
    )
    columns = tuple(source)
    conn.execute(
        f"INSERT INTO offer_intents ({', '.join(columns)}) VALUES "
        f"({', '.join('?' for _column in columns)})",
        tuple(source[column] for column in columns),
    )
    conn.execute(
        "UPDATE coins SET status='locked', trade_id='intent:spent-overlap' "
        "WHERE coin_id=?",
        (database.norm_coin_id(selected_coin_id),),
    )

    terminal_orphan_coin_id = "c" * 64
    assert database.upsert_coin(terminal_orphan_coin_id, "xch", 42, tier="none")
    conn.execute(
        "UPDATE coins SET status='locked', trade_id=? WHERE coin_id=?",
        (source_trade_id, database.norm_coin_id(terminal_orphan_coin_id)),
    )
    conn.commit()
    database.enqueue_publication_outbox(
        publication_id="publication-malformed-queued",
        idempotency_key=f"mainnet:{'d' * 64}:epoch-1",
        network="mainnet",
        offer_fingerprint="d" * 64,
        publication_epoch="epoch-1",
        publisher="dexie",
        payload_json={"offer_reference": "d" * 64},
        queued_at=AT,
    )
    conn.execute(
        "UPDATE publication_outbox SET claim_owner_run_id='forged-owner' "
        "WHERE publication_id='publication-malformed-queued'"
    )
    conn.commit()

    snapshot = database.get_stability_startup_recovery_snapshot()

    assert "intent:spent-overlap" in snapshot["reservation_issues"]
    assert (
        f"coin:{database.norm_coin_id(terminal_orphan_coin_id)}"
        in snapshot["reservation_issues"]
    )
    assert "malformed:publication-malformed-queued" in snapshot["publication_issues"]


def test_failed_owner_startup_discards_runtime_and_retry_promotes(
    isolated_database,
    monkeypatch,
):
    import api_server
    import wallet

    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_NAME", "Task 10 Wallet", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 15, raising=False
    )
    monkeypatch.setattr(api_server, "_mutation_runtime", None)
    monkeypatch.setattr(api_server, "_mutation_runtime_db_path", None)
    identity_observations = []

    def local_identity_observation():
        observed_at = (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        identity_observations.append(observed_at)
        return {
            "success": True,
            "backend": "sage",
            "name": "Task 10 Wallet",
            "fingerprint": 123456789,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": observed_at,
        }

    monkeypatch.setattr(wallet, "get_wallet_identity", local_identity_observation)
    coin_id, intent_id = _seed_prepared_creation(
        coin_id="e" * 64,
        intent_id="intent-retry-after-blocker",
    )

    first = api_server.initialize_mutation_runtime(
        start_heartbeat=False,
        acquire_lease=True,
    )

    assert first["allowed"] is False
    assert mutation_gate.current_runtime() is None
    assert api_server._mutation_runtime is None
    assert api_server._mutation_runtime_db_path is None
    failed_lease = database.get_runtime_mutation_lease()
    assert failed_lease["active"] == 0
    assert failed_lease["owner_run_id"] is None

    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id="f" * 64,
        offer_text_sha256=hashlib.sha256(b"task10 retry offer").hexdigest(),
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": "mainnet",
        },
        evidence_json={"fixture": "task10 retry resolved"},
        finalized_at=AT,
        finalize_selected_coin_reservations=True,
    )
    assert database.get_coin_state(coin_id)["trade_id"] == "f" * 64

    api_server._ensure_mutation_runtime()

    assert mutation_gate.status().allowed is True
    promoted_lease = database.get_runtime_mutation_lease()
    assert promoted_lease["active"] == 1
    assert promoted_lease["owner_run_id"] is not None


def test_repeated_owner_startup_reuses_exact_promoted_runtime(
    isolated_database,
    monkeypatch,
):
    import api_server
    import wallet

    monkeypatch.setattr(api_server.cfg, "WALLET_TYPE", "sage")
    monkeypatch.setattr(api_server.cfg, "SAGE_FINGERPRINT", "123456789")
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_NAME", "Task 10 Wallet", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_EXPECTED_KEY_KIND", "bls", raising=False
    )
    monkeypatch.setattr(
        api_server.cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", 15, raising=False
    )
    monkeypatch.setattr(api_server, "_mutation_runtime", None)
    monkeypatch.setattr(api_server, "_mutation_runtime_db_path", None)
    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: (_ for _ in ()).throw(
            AssertionError("repeated pre-consent startup attempted wallet RPC")
        ),
    )

    original_binding_factory = api_server._configured_wallet_identity_binding
    constructed_bindings = []

    def tracked_binding_factory(network):
        binding = original_binding_factory(network)
        constructed_bindings.append(binding)
        return binding

    monkeypatch.setattr(
        api_server, "_configured_wallet_identity_binding", tracked_binding_factory
    )

    first = api_server.initialize_mutation_runtime(
        start_heartbeat=False,
        acquire_lease=True,
    )
    first_runtime = mutation_gate.current_runtime()
    first_lease = database.get_runtime_mutation_lease()

    second = api_server.initialize_mutation_runtime(
        start_heartbeat=False,
        acquire_lease=True,
    )

    assert first["allowed"] is True
    assert second["allowed"] is True
    assert mutation_gate.current_runtime() is first_runtime
    assert database.get_runtime_mutation_lease() == first_lease
    assert len(constructed_bindings) == 1
