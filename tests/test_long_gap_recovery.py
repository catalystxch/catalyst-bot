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


socket.socket.connect = _blocked_socket
socket.socket.connect_ex = _blocked_socket
socket.create_connection = _blocked_socket

import database  # noqa: E402
import mutation_gate  # noqa: E402


UTC = timezone.utc
NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)
WALLET_HASH = "f" * 64
NETWORK = "mainnet"


@pytest.fixture(autouse=True)
def no_network_attempts():
    before = len(_SOCKET_ATTEMPTS)
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
        quarantined_at="2026-08-21T12:01:00.000000Z",
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
