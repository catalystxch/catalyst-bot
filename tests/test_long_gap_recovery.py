"""Long-gap recovery and quarantine safety boundaries."""

from __future__ import annotations

import hashlib
import json
import socket
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest


_SOCKET_ATTEMPTS: list[tuple] = []


def _blocked_socket(*args, **kwargs):
    _SOCKET_ATTEMPTS.append((args, kwargs))
    raise AssertionError("long-gap recovery tests prohibit network access")


_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_CREATE_CONNECTION = socket.create_connection
socket.socket.connect = _blocked_socket
socket.socket.connect_ex = _blocked_socket
socket.create_connection = _blocked_socket

try:
    import database  # noqa: E402
    import mutation_gate  # noqa: E402
finally:
    socket.socket.connect = _ORIGINAL_SOCKET_CONNECT
    socket.socket.connect_ex = _ORIGINAL_SOCKET_CONNECT_EX
    socket.create_connection = _ORIGINAL_CREATE_CONNECTION


UTC = timezone.utc
NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)
WALLET_HASH = "f" * 64
NETWORK = "mainnet"


def _future_lease_expiry() -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(days=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@pytest.fixture(autouse=True)
def no_network_attempts(monkeypatch):
    before = len(_SOCKET_ATTEMPTS)
    monkeypatch.setattr(socket.socket, "connect", _blocked_socket)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_socket)
    monkeypatch.setattr(socket, "create_connection", _blocked_socket)
    yield
    assert len(_SOCKET_ATTEMPTS) == before


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    mutation_gate.shutdown_runtime(release_owned_lease=True)
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "task14.db"))
    database._db_initialized_path = ""
    database.init_database()
    yield database
    mutation_gate.shutdown_runtime(release_owned_lease=True)
    database.close_connection()


def _sample(monotonic: object, wall: object):
    from runtime_recovery import ClockSample

    return ClockSample(monotonic_seconds=monotonic, wall_utc=wall)


def _acquire_runtime_lease(db, *, owner="run-gap"):
    result = db.acquire_runtime_mutation_lease(
        owner_run_id=owner,
        owner_pid=4242,
        owner_host="task14-host",
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        now="2026-08-21T12:00:00.000000Z",
        lease_expires_at=_future_lease_expiry(),
    )
    assert result["acquired"] is True
    return result["lease"]


@pytest.mark.parametrize(
    ("current_monotonic", "current_wall", "reason"),
    [
        (Decimal("140"), NOW + timedelta(seconds=40), "MONOTONIC_GAP"),
        (Decimal("101"), NOW - timedelta(seconds=1), "WALL_CLOCK_ROLLBACK"),
        (Decimal("101"), NOW + timedelta(seconds=30), "WALL_CLOCK_JUMP"),
        (Decimal("99"), NOW + timedelta(seconds=1), "MONOTONIC_ROLLBACK"),
        (True, NOW + timedelta(seconds=1), "CLOCK_SAMPLE_MALFORMED"),
        (Decimal("NaN"), NOW + timedelta(seconds=1), "CLOCK_SAMPLE_MALFORMED"),
        (Decimal("101"), (NOW + timedelta(seconds=1)).replace(tzinfo=None), "CLOCK_SAMPLE_MALFORMED"),
    ],
)
def test_detector_fails_closed_for_sleep_clock_changes_and_malformed_samples(
    current_monotonic, current_wall, reason
):
    from runtime_recovery import detect_discontinuity

    decision = detect_discontinuity(
        _sample(Decimal("100"), NOW),
        _sample(current_monotonic, current_wall),
        maximum_monotonic_gap_seconds=Decimal("10"),
        maximum_wall_skew_seconds=Decimal("2"),
    )

    assert decision.discontinuity is True
    assert decision.reason_code == reason


def test_detector_allows_normal_cadence_and_process_baseline_is_not_compared():
    from runtime_recovery import detect_discontinuity

    baseline = detect_discontinuity(
        None,
        _sample(Decimal("1"), NOW),
        maximum_monotonic_gap_seconds=Decimal("10"),
        maximum_wall_skew_seconds=Decimal("2"),
    )
    normal = detect_discontinuity(
        _sample(Decimal("100"), NOW),
        _sample(Decimal("105"), NOW + timedelta(seconds=5)),
        maximum_monotonic_gap_seconds=Decimal("10"),
        maximum_wall_skew_seconds=Decimal("2"),
    )

    assert baseline.discontinuity is False
    assert baseline.reason_code == "BASELINE_ESTABLISHED"
    assert normal.discontinuity is False
    assert normal.reason_code == "CLOCK_CONTINUOUS"


def test_begin_recovery_epoch_atomically_trips_latch_and_fences_late_publication(
    isolated_database,
):
    db = isolated_database
    _acquire_runtime_lease(db)
    offer_fingerprint = hashlib.sha256(b"offer").hexdigest()
    from publication_outbox import canonical_publication_identity

    identity = canonical_publication_identity(NETWORK, offer_fingerprint, "epoch-1")
    db.enqueue_publication_outbox(
        publication_id="publication-gap",
        idempotency_key=identity.idempotency_key,
        network=NETWORK,
        offer_fingerprint=offer_fingerprint,
        publication_epoch="epoch-1",
        publisher="dexie",
        payload_json={"offer_ref": hashlib.sha256(b"trade:gap").hexdigest()},
        queued_at="2026-08-21T12:00:00.000000Z",
    )
    db.get_connection().execute(
        "UPDATE publication_outbox SET state='claimed', attempt_count=1, "
        "claim_owner_run_id='run-gap', claim_token='claim-gap', "
        "claim_generation=1, claim_expires_at='2026-08-21T12:00:30.000000Z', "
        "row_version=1 WHERE publication_id='publication-gap'"
    )
    db.get_connection().commit()
    claim = db.get_publication_outbox("publication-gap")

    epoch = db.begin_runtime_recovery_epoch(
        recovery_id="recovery:" + "a" * 64,
        reason_code="MONOTONIC_GAP",
        clock_evidence={"monotonic_delta": "40", "wall_delta": "40"},
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        owner_run_id="run-gap",
        started_at="2026-08-21T12:00:40.000000Z",
    )

    assert epoch["latch"]["state"] == "tripped"
    assert epoch["record"]["latch_generation"] == epoch["latch"]["generation"]
    assert db.complete_publication_outbox(
        publication_id=claim["publication_id"],
        owner_run_id=claim["claim_owner_run_id"],
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
        expected_row_version=claim["row_version"],
        acknowledgement_json={"success": True},
        completed_at="2026-08-21T12:00:41.000000Z",
    ) is None
    assert db.get_publication_outbox("publication-gap")["state"] == "claimed"


def test_recovery_epoch_fences_delayed_claimed_cancel_completion(isolated_database):
    from cancel_outcomes import CANCEL_SUBMITTED_UNCONFIRMED, cancellation_result

    trade_id = "3" * 64
    _acquire_runtime_lease(isolated_database)
    operation_id = f"cancel:{trade_id}"
    wallet_identity = {"wallet_fingerprint_hash": WALLET_HASH, "network": NETWORK}
    isolated_database.prepare_offer_cancel(
        operation_id=operation_id,
        event_id=f"{operation_id}:attempt:1:prepared",
        trade_id=trade_id,
        intent_id=None,
        attempt=1,
        wallet_identity_json=wallet_identity,
        evidence_json={
            "trade_id": trade_id,
            "effect_claim_protocol": "durable_cohort_claim_v1",
        },
        prepared_at="2026-08-21T12:00:00.000000Z",
    )
    assert isolated_database.claim_offer_cancel_effect(
        operation_id=operation_id,
        trade_id=trade_id,
        attempt=1,
        claimed_at="2026-08-21T12:00:01.000000Z",
    ) is True
    isolated_database.begin_runtime_recovery_epoch(
        recovery_id="recovery:" + "9" * 64,
        reason_code="MONOTONIC_GAP",
        clock_evidence={"monotonic_delta": "40", "wall_delta": "40"},
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        owner_run_id="run-gap",
        started_at="2026-08-21T12:00:40.000000Z",
    )
    cancel_result = cancellation_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        method="wallet-rpc",
        transaction_id="4" * 64,
    )

    with pytest.raises(ValueError, match="fenced by runtime recovery"):
        isolated_database.finalize_offer_cancel(
            operation_id=operation_id,
            event_id=f"{operation_id}:attempt:1:finalized",
            trade_id=trade_id,
            intent_id=None,
            attempt=1,
            cancel_result=cancel_result,
            wallet_identity_json=wallet_identity,
            evidence_json={"trade_id": trade_id, "cancel_result": cancel_result},
            finalized_at="2026-08-21T12:00:41.000000Z",
        )


def test_recovery_epoch_replay_is_exact_and_conflict_is_rejected(isolated_database):
    _acquire_runtime_lease(isolated_database)
    kwargs = {
        "recovery_id": "recovery:" + "b" * 64,
        "reason_code": "WALL_CLOCK_JUMP",
        "clock_evidence": {"monotonic_delta": "1", "wall_delta": "30"},
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "owner_run_id": "run-gap",
        "started_at": "2026-08-21T12:00:30.000000Z",
    }
    first = isolated_database.begin_runtime_recovery_epoch(**kwargs)
    replay = isolated_database.begin_runtime_recovery_epoch(**kwargs)
    assert replay["record"] == first["record"]
    assert replay["latch"] == first["latch"]
    assert replay["idempotent"] is True

    with pytest.raises(ValueError, match="replay conflict"):
        isolated_database.begin_runtime_recovery_epoch(
            **{**kwargs, "reason_code": "MONOTONIC_GAP"}
        )


def test_quarantine_archives_immutable_evidence_without_clearing_authority(
    isolated_database,
):
    db = isolated_database
    _acquire_runtime_lease(db)
    epoch = db.begin_runtime_recovery_epoch(
        recovery_id="recovery:" + "c" * 64,
        reason_code="MONOTONIC_GAP",
        clock_evidence={"monotonic_delta": "40", "wall_delta": "40"},
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        owner_run_id="run-gap",
        started_at="2026-08-21T12:00:40.000000Z",
    )
    blocker = json.loads(epoch["latch"]["blocking_operation_ids_json"])[0]

    archived = db.quarantine_runtime_blockers(
        confirmation=True,
        quarantine_id="quarantine:" + "d" * 64,
        blocker_ids=[blocker],
        expected_latch_generation=epoch["latch"]["generation"],
        expected_recovery_id=epoch["record"]["recovery_id"],
        owner_run_id="run-gap",
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        quarantined_at="2026-08-21T12:01:30.000000Z",
    )

    assert archived["manifest_sha256"] == hashlib.sha256(
        archived["manifest_json"].encode("utf-8")
    ).hexdigest()
    assert db.get_runtime_safety_latch()["state"] == "tripped"
    assert json.loads(db.get_runtime_safety_latch()["blocking_operation_ids_json"]) == [
        blocker
    ]
    replay = db.quarantine_runtime_blockers(
        confirmation=True,
        quarantine_id="quarantine:" + "d" * 64,
        blocker_ids=[blocker],
        expected_latch_generation=epoch["latch"]["generation"],
        expected_recovery_id=epoch["record"]["recovery_id"],
        owner_run_id="run-gap",
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        quarantined_at="2026-08-21T12:01:00.000000Z",
    )
    assert replay == archived

    conn = db.get_connection()
    with pytest.raises(Exception, match="append-only"):
        conn.execute(
            "UPDATE runtime_quarantine_manifests SET manifest_json='{}' "
            "WHERE quarantine_id=?",
            (archived["quarantine_id"],),
        )


@pytest.mark.parametrize("confirmation", [1, "true", [], object()])
def test_quarantine_requires_exact_operator_confirmation(
    isolated_database, confirmation
):
    with pytest.raises((TypeError, ValueError), match="confirmation"):
        isolated_database.quarantine_runtime_blockers(
            confirmation=confirmation,
            quarantine_id="quarantine:" + "e" * 64,
            blocker_ids=["runtime-recovery:" + "e" * 64],
            expected_latch_generation=1,
            expected_recovery_id="recovery:" + "e" * 64,
            owner_run_id="run-gap",
            wallet_fingerprint_hash=WALLET_HASH,
            network=NETWORK,
            quarantined_at="2026-08-21T12:01:00.000000Z",
        )


def test_api_quarantine_response_is_structured_and_redacted(monkeypatch):
    import api_server

    monkeypatch.setattr(
        api_server,
        "_quarantine_runtime_request",
        lambda payload: {
            "success": True,
            "quarantine_id": "quarantine:" + "f" * 64,
            "reason_code": "QUARANTINE_ARCHIVED_MUTATION_BLOCKED",
            "manifest_sha256": "a" * 64,
        },
    )
    with api_server.app.test_request_context(
        "/api/safety/quarantine", method="POST", json={"confirmation": True}
    ):
        response, status = api_server.api_safety_quarantine()

    body = response.get_json()
    assert status == 200
    assert body == {
        "success": True,
        "quarantine_id": "quarantine:" + "f" * 64,
        "reason_code": "QUARANTINE_ARCHIVED_MUTATION_BLOCKED",
        "manifest_sha256": "a" * 64,
    }
    assert "wallet_fingerprint_hash" not in json.dumps(body)
    assert "owner_run_id" not in json.dumps(body)


@pytest.mark.parametrize(
    ("proof_change", "reason"),
    [
        ({"absent_offer_ids": []}, "QUARANTINED_OFFER_ABSENCE_INCOMPLETE"),
        (
            {"coins": [{"coin_id": "1" * 64, "owned": False, "unlocked": True}]},
            "QUARANTINED_INPUT_NOT_OWNED",
        ),
        (
            {"coins": [{"coin_id": "1" * 64, "owned": True, "unlocked": False}]},
            "QUARANTINED_INPUT_LOCKED",
        ),
    ],
)
def test_quarantine_resolution_requires_complete_absence_and_owned_unlocked_inputs(
    proof_change, reason
):
    from runtime_recovery import validate_quarantine_resolution_proof

    requirements = {
        "quarantine_id": "quarantine:" + "a" * 64,
        "recovery_id": "recovery:" + "b" * 64,
        "latch_generation": 1,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "authority_digest": "c" * 64,
        "offers": [
            {
                "intent_id": "intent-1",
                "trade_id": "2" * 64,
                "selected_coin_ids": ["1" * 64],
            }
        ],
    }
    proof = {
        "version": 1,
        "quarantine_id": requirements["quarantine_id"],
        "recovery_id": requirements["recovery_id"],
        "latch_generation": 1,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "authority_digest": "c" * 64,
        "observed_at": "2026-08-21T12:02:00.000000Z",
        "history_complete": True,
        "authoritative_read_performed": True,
        "history_provenance": "wallet.get_all_offers",
        "identity_provenance": "wallet.get_wallet_identity",
        "absent_offer_ids": ["2" * 64],
        "coins": [{"coin_id": "1" * 64, "owned": True, "unlocked": True}],
    }
    proof.update(proof_change)

    decision = validate_quarantine_resolution_proof(
        requirements,
        proof,
        now=NOW + timedelta(minutes=2, seconds=5),
        maximum_age_seconds=10,
    )

    assert decision == {"allowed": False, "reason_code": reason}


def test_quarantine_resolution_accepts_only_fresh_exact_complete_proof():
    from runtime_recovery import validate_quarantine_resolution_proof

    requirements = {
        "quarantine_id": "quarantine:" + "a" * 64,
        "recovery_id": "recovery:" + "b" * 64,
        "latch_generation": 1,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "authority_digest": "c" * 64,
        "offers": [{"intent_id": "intent-1", "trade_id": "2" * 64, "selected_coin_ids": ["1" * 64]}],
    }
    proof = {
        "version": 1,
        "quarantine_id": requirements["quarantine_id"],
        "recovery_id": requirements["recovery_id"],
        "latch_generation": 1,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "authority_digest": "c" * 64,
        "observed_at": "2026-08-21T12:02:00.000000Z",
        "history_complete": True,
        "authoritative_read_performed": True,
        "history_provenance": "wallet.get_all_offers",
        "identity_provenance": "wallet.get_wallet_identity",
        "absent_offer_ids": ["2" * 64],
        "coins": [{"coin_id": "1" * 64, "owned": True, "unlocked": True}],
    }

    decision = validate_quarantine_resolution_proof(
        requirements,
        proof,
        now=NOW + timedelta(minutes=2, seconds=5),
        maximum_age_seconds=10,
    )

    assert decision["allowed"] is True
    assert decision["reason_code"] == "QUARANTINE_PROOF_COMPLETE"
    assert len(decision["proof_sha256"]) == 64


def test_bot_cycle_detects_discontinuity_before_first_mutation(monkeypatch):
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._runtime_recovery_baseline = _sample(Decimal("100"), NOW)
    loop._runtime_recovery_monotonic = lambda: Decimal("140")
    loop._runtime_recovery_wall_clock = lambda: NOW + timedelta(seconds=40)
    loop._runtime_recovery_gap_seconds = Decimal("10")
    loop._runtime_recovery_skew_seconds = Decimal("2")
    loop._running = True
    loop._recovery_state = {}
    loop._set_cycle_step = lambda _name: None
    calls = []
    loop._runtime_recovery_coordinator = lambda decision, sample: calls.append(
        (decision.reason_code, sample)
    ) or {"allowed": False, "reason_code": "RECOVERY_BLOCKED"}
    loop.offer_manager = type(
        "OfferManagerSentinel",
        (),
        {
            "clear_cycle_coins": lambda self: (
                calls.append(("mutation", None)),
                (_ for _ in ()).throw(AssertionError("mutation ran before recovery")),
            )[-1]
        },
    )()

    result = loop._run_one_cycle()

    assert result is False
    assert [item[0] for item in calls] == ["MONOTONIC_GAP"]
    assert loop._runtime_recovery_baseline.monotonic_seconds == Decimal("100")


def test_successful_recovery_establishes_fresh_detector_baseline():
    import bot_loop

    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    loop._runtime_recovery_baseline = _sample(Decimal("100"), NOW)
    loop._runtime_recovery_monotonic = lambda: Decimal("140")
    loop._runtime_recovery_wall_clock = lambda: NOW + timedelta(seconds=40)
    loop._runtime_recovery_gap_seconds = Decimal("10")
    loop._runtime_recovery_skew_seconds = Decimal("2")
    loop._runtime_recovery_coordinator = lambda _decision, _sample: {
        "allowed": True,
        "reason_code": "RECOVERY_COMPLETE",
    }

    assert loop._runtime_recovery_cycle_boundary() is True
    assert loop._runtime_recovery_baseline == _sample(
        Decimal("140"), NOW + timedelta(seconds=40)
    )


def test_runtime_recovery_reuses_ordered_startup_coordinator_and_retries_same_epoch(
    monkeypatch,
):
    import api_server
    import wallet

    events: list[object] = []
    epoch = {
        "recovery_id": "recovery:" + "8" * 64,
        "blocker_id": "runtime-recovery:" + "7" * 64,
        "latch_generation": 12,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "owner_run_id": "run-recovery",
        "lease_version": 4,
    }

    class _Status:
        def to_dict(self):
            return {
                "allowed": False,
                "reason_code": "RUNTIME_SAFETY_LATCH_TRIPPED",
                "lease": {"lease_version": 4},
            }

    class _Runtime:
        run_id = "run-recovery"
        wallet_fingerprint_hash = WALLET_HASH
        network = NETWORK
        wallet_identity_binding = SimpleNamespace()

        def __init__(self):
            self.require_calls = 0

        def require_allowed(self, _operation):
            self.require_calls += 1
            if self.require_calls > 1:
                raise RuntimeError("durable recovery latch remains tripped")
            return SimpleNamespace(lease_version=4)

        def status(self):
            return _Status()

        def release_resolved(self, generation, blockers):
            events.append(("release", generation, blockers))
            return {
                "released": True,
                "status": {"allowed": True, "lease": {"lease_version": 4}},
            }

    runtime = _Runtime()
    monkeypatch.setattr(api_server.mutation_gate, "current_runtime", lambda: runtime)
    monkeypatch.setattr(
        api_server,
        "_configured_mutation_binding",
        lambda: (WALLET_HASH, NETWORK),
    )
    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: {
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": NETWORK,
            "observed_at_utc": "2026-08-21T12:00:41.000000Z",
        },
    )
    def _begin_epoch(**kwargs):
        epoch["recovery_id"] = kwargs["recovery_id"]
        return {"record": dict(epoch), "idempotent": False}

    monkeypatch.setattr(
        api_server.database,
        "begin_runtime_recovery_epoch",
        _begin_epoch,
    )
    monkeypatch.setattr(
        api_server.database,
        "get_current_runtime_recovery",
        lambda: epoch,
    )
    monkeypatch.setattr(
        api_server.database,
        "get_runtime_mutation_lease",
        lambda: {
            "lease_version": 4,
            "owner_run_id": runtime.run_id,
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": NETWORK,
        },
    )
    recorded_passes = []
    monkeypatch.setattr(
        api_server.database,
        "record_runtime_recovery_pass",
        lambda **kwargs: recorded_passes.append(kwargs) or {"recorded": True},
    )
    failed_once = {"value": False}

    def _check(check_name, *, state, **_kwargs):
        events.append(("check", check_name))
        if check_name == api_server._STABILITY_STARTUP_CHECKS[0]:
            state["initial_snapshot"] = {"authority_digest": "6" * 64}
        if (
            check_name == api_server._STABILITY_STARTUP_CHECKS[3]
            and failed_once["value"] is False
        ):
            failed_once["value"] = True
            return {
                "ok": False,
                "reason_code": "RECOVERY_RESERVATION_CONFLICT",
                "blocker_counts": {"reservations": 1},
            }
        return {"ok": True, "reason_code": "OK", "blocker_counts": {}}

    monkeypatch.setattr(api_server, "_run_stability_startup_check", _check)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "_rotate_owner_identity_authority",
        lambda current_runtime: events.append(("rotate", current_runtime.run_id))
        or True,
    )
    decision = SimpleNamespace(
        reason_code="MONOTONIC_GAP",
        monotonic_delta_seconds="40",
        wall_delta_seconds="40",
    )
    sample = _sample(Decimal("140"), NOW + timedelta(seconds=40))

    first = api_server._run_runtime_recovery(decision, sample)
    second = api_server._run_runtime_recovery(decision, sample)

    check_names = [event[1] for event in events if event[0] == "check"]
    first_names = check_names[:_STABILITY_FAILURE_INDEX]
    second_names = check_names[_STABILITY_FAILURE_INDEX:]
    assert first["allowed"] is False
    assert first_names == list(api_server._STABILITY_STARTUP_CHECKS[:4])
    assert second["allowed"] is True
    assert second_names == list(api_server._STABILITY_STARTUP_CHECKS)
    assert len(recorded_passes) == 1
    assert events[-2:] == [
        ("rotate", runtime.run_id),
        ("release", epoch["latch_generation"], [epoch["blocker_id"]]),
    ]


_STABILITY_FAILURE_INDEX = 4


@pytest.mark.parametrize("failure_stage", ["rotate", "release"])
def test_runtime_recovery_promotion_retries_with_new_append_only_attempt(
    monkeypatch, failure_stage
):
    import api_server
    import wallet

    events = []
    epoch = {
        "recovery_id": "recovery:" + "4" * 64,
        "blocker_id": "runtime-recovery:" + "4" * 64,
        "latch_generation": 8,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "owner_run_id": "run-promotion",
        "lease_version": 9,
    }

    class _Runtime:
        run_id = "run-promotion"
        wallet_fingerprint_hash = WALLET_HASH
        network = NETWORK
        wallet_identity_binding = SimpleNamespace()

        def __init__(self):
            self.boundary_calls = 0
            self.release_calls = 0

        def require_allowed(self, _operation):
            self.boundary_calls += 1
            if self.boundary_calls > 1:
                raise RuntimeError("latch remains tripped")
            return SimpleNamespace(lease_version=9)

        def status(self):
            return SimpleNamespace(
                to_dict=lambda: {
                    "allowed": False,
                    "lease": {"lease_version": 9},
                }
            )

        def release_resolved(self, generation, blockers):
            self.release_calls += 1
            events.append(("release", generation, tuple(blockers)))
            if failure_stage == "release" and self.release_calls == 1:
                return {"released": False}
            return {
                "released": True,
                "status": {"allowed": True, "lease": {"lease_version": 9}},
            }

    runtime = _Runtime()
    monkeypatch.setattr(api_server.mutation_gate, "current_runtime", lambda: runtime)
    monkeypatch.setattr(
        api_server, "_configured_mutation_binding", lambda: (WALLET_HASH, NETWORK)
    )
    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": NETWORK,
            "observed_at_utc": "2026-08-21T12:00:41.000000Z",
        },
    )
    begin_ids = []

    def _begin(**kwargs):
        begin_ids.append(kwargs["recovery_id"])
        epoch["recovery_id"] = kwargs["recovery_id"]
        return {"record": dict(epoch), "idempotent": len(begin_ids) > 1}

    monkeypatch.setattr(api_server.database, "begin_runtime_recovery_epoch", _begin)
    monkeypatch.setattr(
        api_server.database, "get_current_runtime_recovery", lambda: dict(epoch)
    )
    lease_reads = []
    monkeypatch.setattr(
        api_server.database,
        "get_runtime_mutation_lease",
            lambda: lease_reads.append(True)
            or {
                # A normal heartbeat renewed this same incarnation after the
                # recovery epoch captured version 9.
                "lease_version": 10,
                "owner_run_id": runtime.run_id,
                "wallet_fingerprint_hash": WALLET_HASH,
                "network": NETWORK,
        },
    )
    pass_attempts = []
    monkeypatch.setattr(
        api_server.database,
        "record_runtime_recovery_pass",
        lambda **kwargs: pass_attempts.append(kwargs)
        or {"attempt_number": len(pass_attempts)},
    )

    def _check(check_name, *, state, **_kwargs):
        events.append(("check", check_name))
        if check_name == api_server._STABILITY_STARTUP_CHECKS[0]:
            state["initial_snapshot"] = {"authority_digest": "8" * 64}
        return {"ok": True, "reason_code": "OK", "blocker_counts": {}}

    monkeypatch.setattr(api_server, "_run_stability_startup_check", _check)
    rotate_calls = []

    def _rotate(_runtime):
        rotate_calls.append(True)
        return not (failure_stage == "rotate" and len(rotate_calls) == 1)

    monkeypatch.setattr(
        api_server.mutation_gate, "_rotate_owner_identity_authority", _rotate
    )
    decision = SimpleNamespace(
        reason_code="MONOTONIC_GAP",
        monotonic_delta_seconds="40",
        wall_delta_seconds="40",
    )
    sample = _sample(Decimal("140"), NOW + timedelta(seconds=40))

    first = api_server._run_runtime_recovery(decision, sample)
    second = api_server._run_runtime_recovery(decision, sample)

    assert first == {"allowed": False, "reason_code": "RECOVERY_PROMOTION_FAILED"}
    assert second["allowed"] is True
    assert begin_ids[0] == begin_ids[1]
    assert len(lease_reads) == 1
    assert len(pass_attempts) == 2
    assert [event[1] for event in events if event[0] == "check"] == list(
        api_server._STABILITY_STARTUP_CHECKS
    ) * 2


@pytest.mark.parametrize(
    "phase_name",
    ["cancel", "create", "publication", "coin_prep"],
)
def test_pause_between_effect_phases_fences_before_next_effect(
    isolated_database, phase_name
):
    import bot_loop

    lease = _acquire_runtime_lease(isolated_database)
    loop = bot_loop.BotLoop.__new__(bot_loop.BotLoop)
    monotonic = {"value": Decimal("100")}
    wall = {"value": NOW}
    loop._runtime_recovery_baseline = _sample(monotonic["value"], wall["value"])
    loop._runtime_recovery_monotonic = lambda: monotonic["value"]
    loop._runtime_recovery_wall_clock = lambda: wall["value"]
    loop._runtime_recovery_gap_seconds = Decimal("10")
    loop._runtime_recovery_skew_seconds = Decimal("2")
    loop._runtime_recovery_coordinator = lambda decision, sample: (
        isolated_database.begin_runtime_recovery_epoch(
            recovery_id="recovery:" + "1" * 64,
            reason_code=decision.reason_code,
            clock_evidence={"phase": phase_name},
            wallet_fingerprint_hash=WALLET_HASH,
            network=NETWORK,
            owner_run_id="run-gap",
            started_at=sample.wall_utc,
        )
        and {"allowed": False, "reason_code": "RECOVERY_REQUIRED"}
    )
    effects = []

    assert loop._runtime_recovery_cycle_boundary() is True
    monotonic["value"] = Decimal("140")
    wall["value"] = NOW + timedelta(seconds=40)
    if loop._enter_runtime_effect_phase(phase_name):
        effects.append(phase_name)

    assert effects == []
    latch = isolated_database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert int(latch["generation"]) > 0
    assert lease["lease_version"] == 1


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("active", 0),
        ("owner_pid", 4343),
        ("owner_host", "replacement-host"),
        ("acquired_at", "2026-08-21T12:00:01.000000Z"),
        ("heartbeat_at", "2026-08-21T00:00:00.000000Z"),
        ("expires_at", "2026-08-21T14:00:00.000000Z"),
    ],
)
def test_recovery_epoch_replay_rejects_exact_lease_aba(
    isolated_database, column, value
):
    db = isolated_database
    lease = _acquire_runtime_lease(db)
    kwargs = {
        "recovery_id": "recovery:" + "2" * 64,
        "reason_code": "MONOTONIC_GAP",
        "clock_evidence": {"phase": "create"},
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "owner_run_id": "run-gap",
        "started_at": "2026-08-21T12:00:40.000000Z",
    }
    epoch = db.begin_runtime_recovery_epoch(**kwargs)["record"]

    assert epoch["lease_version"] == lease["lease_version"]
    assert epoch["lease_active"] == 1
    assert epoch["lease_owner_pid"] == 4242
    assert epoch["lease_owner_host"] == "task14-host"
    db.get_connection().execute(
        f"UPDATE runtime_mutation_lease SET {column}=? WHERE singleton_id=1",
        (value,),
    )
    db.get_connection().commit()

    with pytest.raises(ValueError, match="lease authority changed"):
        db.begin_runtime_recovery_epoch(**kwargs)


def test_recovery_epoch_accepts_monotonic_heartbeat_renewal_for_every_transition(
    isolated_database,
):
    from runtime_recovery import validate_quarantine_resolution_proof

    db = isolated_database
    lease = _acquire_runtime_lease(db)
    kwargs = {
        "recovery_id": "recovery:" + "8" * 64,
        "reason_code": "MONOTONIC_GAP",
        "clock_evidence": {"phase": "create"},
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "owner_run_id": "run-gap",
        "started_at": "2026-08-21T12:00:40.000000Z",
    }
    epoch = db.begin_runtime_recovery_epoch(**kwargs)["record"]
    heartbeat = db.heartbeat_runtime_mutation_lease(
        owner_run_id="run-gap",
        expected_lease_version=lease["lease_version"],
        heartbeat_at="2026-08-21T12:01:00.000000Z",
        lease_expires_at=_future_lease_expiry(),
    )

    assert heartbeat["heartbeat"] is True
    assert heartbeat["lease"]["lease_version"] == lease["lease_version"] + 1
    replay = db.begin_runtime_recovery_epoch(**kwargs)
    assert replay["idempotent"] is True
    assert replay["record"]["recovery_id"] == epoch["recovery_id"]
    quarantine = db.quarantine_runtime_blockers(
        confirmation=True,
        quarantine_id="quarantine:" + "8" * 64,
        blocker_ids=[epoch["blocker_id"]],
        expected_latch_generation=epoch["latch_generation"],
        expected_recovery_id=epoch["recovery_id"],
        owner_run_id="run-gap",
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        quarantined_at="2026-08-21T12:01:01.000000Z",
    )
    requirements = db.get_runtime_quarantine_resolution_requirements(
        quarantine["quarantine_id"]
    )
    observed = datetime.now(timezone.utc)
    proof = {
        "version": 1,
        "quarantine_id": requirements["quarantine_id"],
        "recovery_id": requirements["recovery_id"],
        "latch_generation": requirements["latch_generation"],
        "wallet_fingerprint_hash": requirements["wallet_fingerprint_hash"],
        "network": requirements["network"],
        "authority_digest": requirements["authority_digest"],
        "observed_at": observed.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "history_complete": True,
        "authoritative_read_performed": True,
        "history_provenance": "wallet.get_all_offers",
        "identity_provenance": "wallet.get_wallet_identity",
        "absent_offer_ids": [],
        "coins": [],
    }
    decision = validate_quarantine_resolution_proof(
        requirements,
        proof,
        now=observed,
        maximum_age_seconds=30,
    )
    assert decision["allowed"] is True
    resolved = db.resolve_runtime_quarantine(
        quarantine_id=quarantine["quarantine_id"],
        expected_recovery_id=epoch["recovery_id"],
        expected_latch_generation=epoch["latch_generation"],
        expected_owner_run_id="run-gap",
        proof_decision=decision,
        resolved_at="2026-08-21T12:01:02.000000Z",
    )
    assert resolved["resolved"] is True
    db.record_runtime_recovery_pass(
        recovery_id=epoch["recovery_id"],
        expected_latch_generation=epoch["latch_generation"],
        authority_digest="8" * 64,
        checks=[{"name": "integrity", "ok": True}],
        passed_at="2026-08-21T12:01:03.000000Z",
    )
    latch = db.resolve_runtime_safety_latch(
        expected_generation=epoch["latch_generation"],
        resolved_operation_ids=[epoch["blocker_id"]],
        resolved_at="2026-08-21T12:01:04.000000Z",
    )
    assert latch["resolved"] is True
    assert latch["latch"]["state"] == "resolved"


def test_recovery_epoch_rejects_same_owner_release_and_reacquire_aba(
    isolated_database,
):
    db = isolated_database
    lease = _acquire_runtime_lease(db)
    kwargs = {
        "recovery_id": "recovery:" + "9" * 64,
        "reason_code": "MONOTONIC_GAP",
        "clock_evidence": {"phase": "cancel"},
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "owner_run_id": "run-gap",
        "started_at": "2026-08-21T12:00:40.000000Z",
    }
    epoch = db.begin_runtime_recovery_epoch(**kwargs)["record"]
    released = db.release_runtime_mutation_lease(
        owner_run_id="run-gap",
        expected_lease_version=lease["lease_version"],
        released_at="2026-08-21T12:02:00.000000Z",
    )
    reacquired = db.acquire_runtime_mutation_lease(
        owner_run_id="run-gap",
        owner_pid=4242,
        owner_host="task14-host",
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        now="2026-08-21T12:03:00.000000Z",
        lease_expires_at=_future_lease_expiry(),
    )

    assert released["released"] is True
    assert reacquired["acquired"] is True
    assert reacquired["lease"]["owner_run_id"] == epoch["owner_run_id"]
    assert reacquired["lease"]["acquired_at"] != epoch["lease_acquired_at"]
    with pytest.raises(ValueError, match="lease authority changed"):
        db.begin_runtime_recovery_epoch(**kwargs)


def test_gap_fences_late_publication_retry_and_unresolve_callbacks(isolated_database):
    db = isolated_database
    _acquire_runtime_lease(db)
    offer_fingerprint = hashlib.sha256(b"failure-callbacks").hexdigest()
    from publication_outbox import canonical_publication_identity

    identity = canonical_publication_identity(NETWORK, offer_fingerprint, "epoch-f")
    db.enqueue_publication_outbox(
        publication_id="publication-failure-gap",
        idempotency_key=identity.idempotency_key,
        network=NETWORK,
        offer_fingerprint=offer_fingerprint,
        publication_epoch="epoch-f",
        publisher="dexie",
        payload_json={"offer_ref": hashlib.sha256(b"trade:failure").hexdigest()},
        queued_at="2026-08-21T12:00:00.000000Z",
    )
    db.get_connection().execute(
        "UPDATE publication_outbox SET state='claimed', attempt_count=1, "
        "claim_owner_run_id='run-gap', claim_token='claim-failure', "
        "claim_generation=1, claim_expires_at='2026-08-21T12:05:00.000000Z', "
        "recovery_generation=0, row_version=1 "
        "WHERE publication_id='publication-failure-gap'"
    )
    db.get_connection().commit()
    claim = db.get_publication_outbox("publication-failure-gap")
    db.begin_runtime_recovery_epoch(
        recovery_id="recovery:" + "3" * 64,
        reason_code="MONOTONIC_GAP",
        clock_evidence={"phase": "publication"},
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        owner_run_id="run-gap",
        started_at="2026-08-21T12:00:40.000000Z",
    )
    common = {
        "publication_id": claim["publication_id"],
        "owner_run_id": claim["claim_owner_run_id"],
        "claim_token": claim["claim_token"],
        "claim_generation": claim["claim_generation"],
        "expected_row_version": claim["row_version"],
        "error_json": {"reason": "late timeout"},
    }

    assert db.retry_publication_outbox(
        **common,
        retry_at="2026-08-21T12:01:40.000000Z",
        updated_at="2026-08-21T12:00:41.000000Z",
    ) is None
    assert db.unresolve_publication_outbox(
        **common,
        unresolved_at="2026-08-21T12:00:41.000000Z",
    ) is None
    assert db.get_publication_outbox(claim["publication_id"])["state"] == "claimed"


def test_recovery_pass_attempts_are_append_only_and_retryable(isolated_database):
    db = isolated_database
    _acquire_runtime_lease(db)
    epoch = db.begin_runtime_recovery_epoch(
        recovery_id="recovery:" + "4" * 64,
        reason_code="MONOTONIC_GAP",
        clock_evidence={"phase": "create"},
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        owner_run_id="run-gap",
        started_at="2026-08-21T12:00:40.000000Z",
    )["record"]
    first = db.record_runtime_recovery_pass(
        recovery_id=epoch["recovery_id"],
        expected_latch_generation=epoch["latch_generation"],
        authority_digest="a" * 64,
        checks=[{"name": "lease", "ok": True}],
        passed_at="2026-08-21T12:00:41.000000Z",
    )
    second = db.record_runtime_recovery_pass(
        recovery_id=epoch["recovery_id"],
        expected_latch_generation=epoch["latch_generation"],
        authority_digest="b" * 64,
        checks=[{"name": "lease", "ok": True}, {"name": "retry", "ok": True}],
        passed_at="2026-08-21T12:00:42.000000Z",
    )

    rows = db.get_connection().execute(
        "SELECT * FROM runtime_recovery_passes WHERE recovery_id=? "
        "ORDER BY attempt_number",
        (epoch["recovery_id"],),
    ).fetchall()
    assert first["attempt_number"] == 1
    assert second["attempt_number"] == 2
    assert len(rows) == 2
    assert rows[0]["checks_sha256"] != rows[1]["checks_sha256"]


@pytest.mark.parametrize("operation", ["pass", "quarantine", "release"])
def test_exact_lease_aba_blocks_every_recovery_promotion_step(
    isolated_database, operation
):
    db = isolated_database
    _acquire_runtime_lease(db)
    epoch = db.begin_runtime_recovery_epoch(
        recovery_id="recovery:" + "5" * 64,
        reason_code="MONOTONIC_GAP",
        clock_evidence={"monotonic_delta": "40", "wall_delta": "40"},
        wallet_fingerprint_hash=WALLET_HASH,
        network=NETWORK,
        owner_run_id="run-gap",
        started_at="2026-08-21T12:00:40.000000Z",
    )["record"]
    if operation == "release":
        db.record_runtime_recovery_pass(
            recovery_id=epoch["recovery_id"],
            expected_latch_generation=epoch["latch_generation"],
            authority_digest="1" * 64,
            checks=[{"name": "integrity", "ok": True}],
            passed_at="2026-08-21T12:01:00.000000Z",
        )
    db.get_connection().execute(
        "UPDATE runtime_mutation_lease SET lease_version=lease_version+1 "
        "WHERE singleton_id=1"
    )
    db.get_connection().commit()

    with pytest.raises(ValueError, match="lease authority changed"):
        if operation == "pass":
            db.record_runtime_recovery_pass(
                recovery_id=epoch["recovery_id"],
                expected_latch_generation=epoch["latch_generation"],
                authority_digest="1" * 64,
                checks=[{"name": "integrity", "ok": True}],
                passed_at="2026-08-21T12:01:00.000000Z",
            )
        elif operation == "quarantine":
            db.quarantine_runtime_blockers(
                confirmation=True,
                quarantine_id="quarantine:" + "5" * 64,
                blocker_ids=[epoch["blocker_id"]],
                expected_latch_generation=epoch["latch_generation"],
                expected_recovery_id=epoch["recovery_id"],
                owner_run_id="run-gap",
                wallet_fingerprint_hash=WALLET_HASH,
                network=NETWORK,
                quarantined_at="2026-08-21T12:01:00.000000Z",
            )
        else:
            db.resolve_runtime_safety_latch(
                expected_generation=epoch["latch_generation"],
                resolved_operation_ids=[epoch["blocker_id"]],
                resolved_at="2026-08-21T12:01:01.000000Z",
            )


def test_quarantine_rejects_hostile_iterable_without_traversal(isolated_database):
    traversed = {"value": False}

    def hostile():
        traversed["value"] = True
        yield "runtime-recovery:" + "5" * 64

    with pytest.raises(TypeError, match="exact bounded list or tuple"):
        isolated_database.quarantine_runtime_blockers(
            confirmation=True,
            quarantine_id="quarantine:" + "5" * 64,
            blocker_ids=hostile(),
            expected_latch_generation=1,
            expected_recovery_id="recovery:" + "5" * 64,
            owner_run_id="run-gap",
            wallet_fingerprint_hash=WALLET_HASH,
            network=NETWORK,
            quarantined_at="2026-08-21T12:01:00.000000Z",
        )
    assert traversed["value"] is False


def test_empty_quarantine_proof_requires_actual_authoritative_history_read(monkeypatch):
    import api_server
    import wallet
    from runtime_recovery import validate_quarantine_resolution_proof

    calls = []
    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: calls.append("identity") or (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(
        wallet,
        "get_all_offers",
        lambda **_kwargs: calls.append("history")
        or (_ for _ in ()).throw(RuntimeError("offline")),
    )
    requirements = {
        "quarantine_id": "quarantine:" + "6" * 64,
        "recovery_id": "recovery:" + "6" * 64,
        "latch_generation": 1,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "authority_digest": "c" * 64,
        "offers": [],
    }

    proof = api_server._collect_quarantine_resolution_proof(requirements)
    decision = validate_quarantine_resolution_proof(
        requirements,
        proof,
        now=datetime.now(timezone.utc),
        maximum_age_seconds=30,
    )

    assert calls == ["identity", "history"]
    assert decision == {
        "allowed": False,
        "reason_code": "QUARANTINE_FULL_HISTORY_INCOMPLETE",
    }


def test_fresh_authoritative_empty_history_proves_truly_empty_quarantine(monkeypatch):
    import api_server
    import wallet
    from runtime_recovery import validate_quarantine_resolution_proof

    observed = datetime.now(timezone.utc)
    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET_HASH,
            "network": NETWORK,
            "observed_at_utc": observed.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
        },
    )
    monkeypatch.setattr(wallet, "get_all_offers", lambda **_kwargs: [])
    requirements = {
        "quarantine_id": "quarantine:" + "7" * 64,
        "recovery_id": "recovery:" + "7" * 64,
        "latch_generation": 1,
        "wallet_fingerprint_hash": WALLET_HASH,
        "network": NETWORK,
        "authority_digest": "d" * 64,
        "offers": [],
    }

    proof = api_server._collect_quarantine_resolution_proof(requirements)
    decision = validate_quarantine_resolution_proof(
        requirements,
        proof,
        now=datetime.now(timezone.utc),
        maximum_age_seconds=30,
    )

    assert decision["allowed"] is True
    assert decision["reason_code"] == "QUARANTINE_PROOF_COMPLETE"


def test_quarantine_api_rejects_oversized_body_before_json_allocation():
    import api_server

    with api_server.app.test_request_context(
        "/api/safety/quarantine",
        method="POST",
        data=b"{" + (b"x" * 16384) + b"}",
        content_type="application/json",
    ):
        response, status = api_server.api_safety_quarantine()

    assert status == 409
    assert response.get_json() == {
        "success": False,
        "reason_code": "QUARANTINE_REQUEST_TOO_LARGE",
    }


@pytest.mark.parametrize(
    ("path", "route_name", "downstream_name"),
    [
        (
            "/api/safety/quarantine",
            "api_safety_quarantine",
            "_quarantine_runtime_request",
        ),
        (
            "/api/safety/quarantine/resolve",
            "api_safety_quarantine_resolve",
            "_resolve_runtime_quarantine_request",
        ),
    ],
)
def test_quarantine_api_streams_only_one_bounded_extra_byte_without_content_length(
    monkeypatch, path, route_name, downstream_name
):
    import api_server

    class CountingStream:
        def __init__(self, payload):
            self.payload = payload
            self.offset = 0
            self.bytes_read = 0

        def read(self, size=-1):
            if size is None or size < 0:
                size = len(self.payload) - self.offset
            chunk = self.payload[self.offset : self.offset + size]
            self.offset += len(chunk)
            self.bytes_read += len(chunk)
            return chunk

    stream = CountingStream(b"{" + (b"x" * 20000) + b"}")
    downstream_calls = []
    monkeypatch.setattr(
        api_server,
        downstream_name,
        lambda _payload: downstream_calls.append(True)
        or {"success": True},
    )
    with api_server.app.test_request_context(
        path,
        method="POST",
        content_type="application/json",
        environ_overrides={
            "wsgi.input": stream,
            "wsgi.input_terminated": True,
        },
    ):
        assert api_server.request.headers.get("Content-Length") is None
        response, status = getattr(api_server, route_name)()

    assert status == 409
    assert response.get_json() == {
        "success": False,
        "reason_code": "QUARANTINE_REQUEST_TOO_LARGE",
    }
    assert stream.bytes_read == 16385
    assert downstream_calls == []


def test_quarantine_api_rejects_malformed_content_length_without_read_or_db_call(
    monkeypatch,
):
    import api_server

    class HostileStream:
        def read(self, _size=-1):
            raise AssertionError("malformed Content-Length must reject before reading")

    calls = []
    monkeypatch.setattr(
        api_server,
        "_quarantine_runtime_request",
        lambda _payload: calls.append(True) or {"success": True},
    )
    with api_server.app.test_request_context(
        "/api/safety/quarantine",
        method="POST",
        content_type="application/json",
        headers={"Content-Length": "not-a-size"},
        environ_overrides={
            "wsgi.input": HostileStream(),
            "wsgi.input_terminated": True,
        },
    ):
        response, status = api_server.api_safety_quarantine()

    assert status == 409
    assert response.get_json() == {
        "success": False,
        "reason_code": "QUARANTINE_REQUEST_MALFORMED",
    }
    assert calls == []


def test_quarantine_status_reports_current_latch_state_not_capture_constant(monkeypatch):
    import api_server

    monkeypatch.setattr(
        api_server.database,
        "get_runtime_quarantine_manifest",
        lambda _quarantine_id: {
            "quarantine_id": "quarantine:" + "7" * 64,
            "recovery_id": "recovery:" + "7" * 64,
            "latch_generation": 9,
            "manifest_sha256": "8" * 64,
            "quarantined_at": "2026-08-21T12:01:00.000000Z",
        },
    )
    monkeypatch.setattr(
        api_server.database,
        "get_runtime_safety_latch",
        lambda: {"state": "resolved", "generation": 9},
    )
    with api_server.app.test_request_context(
        "/api/safety/quarantine/" + "quarantine:" + "7" * 64
    ):
        response = api_server.api_safety_quarantine_status(
            "quarantine:" + "7" * 64
        )

    body = response.get_json()
    assert body["quarantine"]["archival_blocked_at_capture"] is True
    assert body["quarantine"]["current_mutation_blocked"] is False
    assert "mutation_blocked" not in body["quarantine"]
