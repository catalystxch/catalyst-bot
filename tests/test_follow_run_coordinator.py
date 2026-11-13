import json
from decimal import Decimal

import pytest

import database
from follow_run_policy import FollowRunPolicy
from follow_run_coordinator import FollowRunCoordinator


CONFIGURATION_SHA256 = "b" * 64
AUTHORITY_RUN_ID = "e" * 64
IDENTITY = {
    "network": "mainnet",
    "wallet_type": "sage",
    "wallet_fingerprint": 123,
    "wallet_id": 2,
    "xch_wallet_id": 1,
    "asset_id": "a" * 64,
    "ticker": "MZ",
}


def _approved_policy():
    return FollowRunPolicy(
        wallet_fingerprint="123",
        network="mainnet",
        asset_id="a" * 64,
        buy_target=100,
        sell_target=100,
        price_anchor=Decimal("0.0123"),
        price_min=Decimal("0.011"),
        price_max=Decimal("0.013"),
        maximum_fee_mojos_per_tx=2_000_000,
        fee_coin_principal_mojos=8_000_000_000,
        xch_reserve_mojos=1_000_000_000,
        cat_reserve_atoms=25_000,
        maximum_trade_xch_mojos=100_000_000_000,
        maximum_trade_cat_atoms=1_000_000_000,
    )


POLICY_DIGEST = _approved_policy().digest
PREP_APPROVAL_ID = "f" * 64
PREP_SESSION_ID = "9" * 64


def prep_snapshot(approval_id):
    return {
        "identity": IDENTITY,
        "scope": {
            **IDENTITY,
            "campaign_id": None,
            "session_id": PREP_SESSION_ID,
        },
        "approval": {"approval_id": approval_id, "unbounded": False},
        "recovery_only": False,
        "recovery_action": None,
    }


@pytest.fixture
def saved_state(monkeypatch):
    settings = {}
    policy = _approved_policy()
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
    import coin_prep_fee_runtime
    import confidence_override

    configuration = {
        "network": "mainnet",
        "WALLET_TYPE": "sage",
        "CAT_ASSET_ID": "a" * 64,
        "CAT_WALLET_ID": 2,
        "WALLET_ID_XCH": 1,
        "CAT_TICKER_ID": "MZ",
        "MAX_ACTIVE_BUY_OFFERS": 100,
        "MAX_ACTIVE_SELL_OFFERS": 100,
    }
    monkeypatch.setattr(coin_prep_fee_runtime, "_configuration", lambda: configuration)
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "_verified_identity",
        lambda _config: {
            "network": "mainnet",
            "wallet_type": "sage",
            "wallet_fingerprint": 123,
        },
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_approved_prep_fee_snapshot",
        prep_snapshot,
    )
    monkeypatch.setattr(
        confidence_override,
        "current_configuration_digest",
        lambda: CONFIGURATION_SHA256,
    )
    monkeypatch.setattr(
        confidence_override,
        "_configuration_digest",
        lambda _config: CONFIGURATION_SHA256,
    )
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


def test_prep_approval_binding_persists_exact_approval_and_session(saved_state):
    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )

    bound = service.bind_prep_approval(
        **binding(run), approval_id=PREP_APPROVAL_ID, now_epoch=101
    )

    assert bound["fee_approval_id"] == PREP_APPROVAL_ID
    assert bound["fee_approval_session_id"] == PREP_SESSION_ID
    assert service.read_state() == bound


def test_prep_approval_binding_is_idempotent_and_cannot_be_replaced(
    saved_state, monkeypatch
):
    import coin_prep_fee_runtime

    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    args = {**binding(run), "approval_id": PREP_APPROVAL_ID}
    first = service.bind_prep_approval(**args, now_epoch=101)
    assert service.bind_prep_approval(**args, now_epoch=102) == first

    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_approved_prep_fee_snapshot",
        lambda approval_id: {
            **prep_snapshot(approval_id),
            "scope": {
                **IDENTITY,
                "campaign_id": None,
                "session_id": "8" * 64,
            },
        },
    )
    with pytest.raises(ValueError, match="FOLLOW_RUN_PREP_FEE_APPROVAL_CHANGED"):
        service.bind_prep_approval(
            **binding(run), approval_id="7" * 64, now_epoch=103
        )
    assert service.read_state()["fee_approval_id"] == PREP_APPROVAL_ID


def test_prep_approval_binding_rejects_wrong_identity_or_config(
    saved_state, monkeypatch
):
    import coin_prep_fee_runtime
    import confidence_override

    service = coordinator()
    run = service.begin_run(
        policy_digest=POLICY_DIGEST,
        configuration_sha256=CONFIGURATION_SHA256,
        now_epoch=100,
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_approved_prep_fee_snapshot",
        lambda approval_id: {
            **prep_snapshot(approval_id),
            "identity": {**IDENTITY, "wallet_fingerprint": 456},
        },
    )
    with pytest.raises(ValueError, match="FOLLOW_RUN_PREP_FEE_BINDING_INVALID"):
        service.bind_prep_approval(
            **binding(run), approval_id=PREP_APPROVAL_ID, now_epoch=101
        )

    monkeypatch.setattr(confidence_override, "current_configuration_digest", lambda: "c" * 64)
    with pytest.raises(ValueError, match="FOLLOW_RUN_AUTHORITY_CHANGED"):
        service.bind_prep_approval(
            **binding(run), approval_id=PREP_APPROVAL_ID, now_epoch=102
        )


def test_legacy_coordinator_state_migrates_without_fee_approval(saved_state):
    service = coordinator()
    old = {
        "version": 1,
        "session_id": "d" * 64,
        "run_id": None,
        "policy_digest": POLICY_DIGEST,
        "configuration_sha256": CONFIGURATION_SHA256,
        "state": "preparing",
        "updated_at_epoch": 100,
        "recoverable_reason": None,
        "unknown_effect": False,
    }
    saved_state[service.SETTING_KEY] = json.dumps(old)

    migrated = service.read_state()

    assert migrated["fee_approval_id"] is None
    assert migrated["fee_approval_session_id"] is None
    assert json.loads(saved_state[service.SETTING_KEY]) == migrated


def test_partial_fee_binding_record_fails_closed(saved_state):
    service = coordinator()
    malformed = {
        "version": 1,
        "session_id": "d" * 64,
        "run_id": None,
        "policy_digest": POLICY_DIGEST,
        "configuration_sha256": CONFIGURATION_SHA256,
        "state": "preparing",
        "updated_at_epoch": 100,
        "recoverable_reason": None,
        "unknown_effect": False,
        "fee_approval_id": PREP_APPROVAL_ID,
    }
    saved_state[service.SETTING_KEY] = json.dumps(malformed)

    with pytest.raises(ValueError, match="FOLLOW_RUN_COORDINATOR_STATE_INVALID"):
        service.read_state()

