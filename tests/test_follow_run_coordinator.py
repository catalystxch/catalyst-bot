import json
from types import SimpleNamespace

import pytest

import database
from follow_run_coordinator import FollowRunCoordinator


POLICY_DIGEST = "a" * 64
CONFIGURATION_SHA256 = "b" * 64
AUTHORITY_RUN_ID = "e" * 64
IDENTITY = {
    "network": "mainnet",
    "wallet_type": "sage",
    "wallet_fingerprint": "fingerprint-123",
    "wallet_id": 2,
    "xch_wallet_id": 1,
    "asset_id": "a" * 64,
}


@pytest.fixture
def saved_state(monkeypatch):
    settings = {}
    policy = SimpleNamespace(
        digest=POLICY_DIGEST,
        network="mainnet",
        wallet_fingerprint="fingerprint-123",
        asset_id="a" * 64,
        buy_target=100,
        sell_target=100,
    )
    active = {"policy": policy}
    monkeypatch.setattr(
        database, "get_active_follow_run_policy", lambda: active["policy"]
    )
    monkeypatch.setattr(database, "get_follow_run_identity", lambda _run_id: IDENTITY)
    monkeypatch.setattr(
        database,
        "get_follow_creation_authority",
        lambda **kwargs: {
            "ready": True,
            "run_id": AUTHORITY_RUN_ID,
            "identity": kwargs["identity"],
            "configuration_sha256": kwargs["configuration_sha256"],
            "buy_limit": 100,
            "sell_limit": 100,
        },
    )
    def clear_policy():
        active["policy"] = None
        return True

    monkeypatch.setattr(database, "clear_active_follow_run_policy", clear_policy)
    monkeypatch.setattr(
        database,
        "get_setting",
        lambda key, default=None: settings.get(key, default),
    )

    def set_setting(key, value):
        settings[key] = value
        return True

    monkeypatch.setattr(database, "set_setting", set_setting)
    return settings


def coordinator():
    return FollowRunCoordinator()


def binding(run):
    return {
        "session_id": run["session_id"],
        "policy_digest": POLICY_DIGEST,
        "configuration_sha256": CONFIGURATION_SHA256,
    }


def test_begin_persists_exact_approval_binding_and_is_idempotent(saved_state):
    service = coordinator()
    first = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    second = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=101,
    )

    assert first["state"] == "prep_pending"
    assert first["run_id"] is None
    assert len(first["session_id"]) == 64
    assert first["policy_digest"] == POLICY_DIGEST
    assert first["configuration_sha256"] == CONFIGURATION_SHA256
    assert second["run_id"] == first["run_id"]
    assert json.loads(saved_state[service.SETTING_KEY]) == second


def test_prep_reconciliation_and_start_transitions_are_idempotent(saved_state):
    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    key = binding(run)
    assert service.mark_preparing(**key, now_epoch=101)["state"] == "preparing"
    ready = service.reconcile_prep(
        **key,
        effect_status="confirmed",
        prep_complete=True,
        fee_status="within_cap",
        now_epoch=102,
    )
    assert ready["state"] == "ready"
    authority = service.bind_authority(
        **key, run_id=AUTHORITY_RUN_ID, now_epoch=103
    )
    assert authority["run_id"] == AUTHORITY_RUN_ID
    assert service.reconcile_prep(
        **key,
        effect_status="confirmed",
        prep_complete=True,
        fee_status="within_cap",
        now_epoch=104,
    )["run_id"] == AUTHORITY_RUN_ID
    assert service.read_state()["run_id"] == AUTHORITY_RUN_ID
    pending = service.mark_start_pending(**key, now_epoch=105)
    assert service.mark_start_pending(**key, now_epoch=106) == pending
    running = service.mark_running(**key, now_epoch=107)
    assert service.mark_running(**key, now_epoch=108) == running
    assert running["state"] == "running"


def test_fee_over_cap_pauses_at_awaiting_confirmation(saved_state):
    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    result = service.reconcile_prep(
        **binding(run),
        effect_status="none",
        prep_complete=False,
        fee_status="above_cap",
        now_epoch=101,
    )
    assert result["state"] == "awaiting_confirmation"


def test_unknown_effect_enters_fail_closed_recoverable_error(saved_state):
    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    key = binding(run)
    failed = service.reconcile_prep(
        **key,
        effect_status="unknown",
        prep_complete=False,
        fee_status="within_cap",
        now_epoch=101,
    )
    assert failed["state"] == "recoverable_error"
    assert failed["unknown_effect"] is True
    unchanged = service.reconcile_prep(
        **key,
        effect_status="none",
        prep_complete=True,
        fee_status="within_cap",
        now_epoch=102,
    )
    assert unchanged == failed
    with pytest.raises(ValueError, match="UNKNOWN_EFFECT"):
        service.mark_preparing(**key, now_epoch=103)

    resolved = service.reconcile_prep(
        **key,
        effect_status="proven_absent",
        prep_complete=False,
        fee_status="within_cap",
        now_epoch=104,
    )
    assert resolved["state"] == "preparing"
    assert resolved["unknown_effect"] is False


def test_policy_or_configuration_mismatch_cannot_inherit_run(saved_state):
    service = coordinator()
    service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    with pytest.raises(ValueError, match="FOLLOW_RUN_AUTHORITY_CHANGED"):
        service.begin_run(
            policy_digest=POLICY_DIGEST,
            configuration_sha256="c" * 64,
            now_epoch=101,
        )
    with pytest.raises(ValueError, match="FOLLOW_RUN_AUTHORITY_CHANGED"):
        service.begin_run(
            policy_digest="d" * 64,
            configuration_sha256=CONFIGURATION_SHA256,
            now_epoch=101,
        )


def test_malformed_persisted_coordinator_state_fails_closed(saved_state):
    service = coordinator()
    saved_state[service.SETTING_KEY] = "{"
    with pytest.raises(ValueError, match="FOLLOW_RUN_COORDINATOR_STATE_INVALID"):
        service.begin_run(
            policy_digest=POLICY_DIGEST,
            configuration_sha256=CONFIGURATION_SHA256,
            now_epoch=100,
        )


def test_failed_write_does_not_report_transition(monkeypatch, saved_state):
    service = coordinator()
    monkeypatch.setattr(database, "set_setting", lambda *_args: False)
    with pytest.raises(ValueError, match="FOLLOW_RUN_COORDINATOR_PERSIST_FAILED"):
        service.begin_run(
            policy_digest=POLICY_DIGEST,
            configuration_sha256=CONFIGURATION_SHA256,
            now_epoch=100,
        )


def test_authority_binding_rejects_unproven_or_wrong_run_id(monkeypatch, saved_state):
    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    key = binding(run)
    service.reconcile_prep(
        **key,
        effect_status="none",
        prep_complete=True,
        fee_status="within_cap",
        now_epoch=101,
    )

    with pytest.raises(ValueError, match="FOLLOW_RUN_AUTHORITY_PROOF_INVALID"):
        service.bind_authority(**key, run_id="f" * 64, now_epoch=102)
    assert service.read_state()["run_id"] is None


def test_start_and_running_require_live_unstopped_authority(monkeypatch, saved_state):
    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    key = binding(run)
    service.reconcile_prep(
        **key,
        effect_status="none",
        prep_complete=True,
        fee_status="within_cap",
        now_epoch=101,
    )
    service.bind_authority(**key, run_id=AUTHORITY_RUN_ID, now_epoch=102)
    monkeypatch.setattr(
        database,
        "get_follow_creation_authority",
        lambda **kwargs: {
            "ready": False,
            "reason_code": "FOLLOW_RUN_STOPPED",
            "run_id": AUTHORITY_RUN_ID,
            "identity": kwargs["identity"],
            "configuration_sha256": kwargs["configuration_sha256"],
            "buy_limit": 100,
            "sell_limit": 100,
        },
    )

    with pytest.raises(ValueError, match="FOLLOW_RUN_AUTHORITY_PROOF_INVALID"):
        service.mark_start_pending(**key, now_epoch=103)
    assert service.read_state()["state"] == "ready"


def test_stop_clears_approval_and_prevents_reusing_old_session(monkeypatch, saved_state):
    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    result = service.stop_run(**binding(run), now_epoch=101)

    assert result["state"] == "stopped"
    assert result["recoverable_reason"] == "MANUAL_STOP"
    with pytest.raises(ValueError, match="FOLLOW_RUN_POLICY_NOT_APPROVED"):
        service.begin_run(
            policy_digest=POLICY_DIGEST,
            configuration_sha256=CONFIGURATION_SHA256,
            now_epoch=102,
        )


def test_stop_marks_existing_authority_stopped_without_offer_cancellation(
    monkeypatch, saved_state
):
    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    key = binding(run)
    service.reconcile_prep(
        **key,
        effect_status="none",
        prep_complete=True,
        fee_status="within_cap",
        now_epoch=101,
    )
    service.bind_authority(**key, run_id=AUTHORITY_RUN_ID, now_epoch=102)
    stopped_authorities = []
    monkeypatch.setattr(
        database,
        "stop_follow_run_authority",
        lambda **kwargs: stopped_authorities.append(kwargs) or kwargs,
    )

    stopped = service.stop_run(**key, now_epoch=103)

    assert stopped["state"] == "stopped"
    assert stopped_authorities == [
        {"run_id": AUTHORITY_RUN_ID, "stopped_at_epoch": 103}
    ]

