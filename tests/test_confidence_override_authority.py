"""Contract tests for the separate durable Follow financial authority.

The production integration owner supplies the ledger/reader. These tests do
not pretend a preparation consent alone proves capped Follow authority.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import database
import confidence_override as policy
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


def complete(approved, monkeypatch):
    import coin_prep_fee_approval as service
    import config
    import mutation_gate

    # Resolve module objects at fixture time; conftest restores modules per file.
    from importlib import import_module
    from fee_approval_test_utils import _coin

    runtime = import_module("coin_prep_fee_runtime")
    targets = runtime.read_approved_prep_fee_snapshot(
        approved["approval"]["approval_id"]
    )["recipe"]["targets"]
    approved["xch"] = [
        _coin(20000 + i, str(t.amount_mojos))
        for i, t in enumerate(targets)
        if t.asset == "xch"
    ]
    approved["cat"] = [
        _coin(30000 + i, str(t.amount_mojos))
        for i, t in enumerate(targets)
        if t.asset == "cat"
    ]
    service.complete_coin_prep_fee_session(approved["approval"]["approval_id"])
    monkeypatch.setattr(config, "cfg", approved["config"])
    monkeypatch.setattr(
        mutation_gate, "current_runtime", lambda: SimpleNamespace(run_id="process-123")
    )


def install_reader(monkeypatch, changes=None):
    calls = []
    expires = int(datetime.now(timezone.utc).timestamp()) + 48 * 3600

    def read(*, identity, configuration_sha256, now_epoch):
        assert type(now_epoch) is int
        calls.append((identity, configuration_sha256, now_epoch))
        return {
            "ready": True,
            "reason_code": None,
            "run_id": "a" * 64,
            "identity": identity,
            "configuration_sha256": configuration_sha256,
            "buy_limit": 1,
            "sell_limit": 1,
            "expires_at_epoch": expires,
            "maximum_fee_mojos": 50000000000,
            "protected_shutdown_fee_mojos": 123456789,
            "consent_id": "d" * 64,
        } | (changes or {})

    monkeypatch.setattr(database, "get_follow_creation_authority", read, raising=False)
    return calls


def test_scope_requires_real_follow_authority_and_records_audit_only(
    approved, monkeypatch
):
    complete(approved, monkeypatch)
    calls = install_reader(monkeypatch)
    scope = policy.current_scope()
    assert calls
    assert scope["identity"]["wallet_fingerprint"] == 736588221
    assert scope["fee_cap_mojos"] == "50000000000"
    assert scope["protected_cancel_mojos"] == "123456789"
    assert scope["follow_run_id"] == "a" * 64
    assert scope["financial_consent_id"] == "d" * 64
    permit = policy.RunConsent.confirm(
        scope=scope,
        reviewed_digest=policy.scope_digest(scope),
        duration_hours=48,
        now=datetime.now(timezone.utc),
    )
    database.record_confidence_override_consent(permit.record(), scope)
    saved = json.loads(
        database.get_setting("confidence_override_consent:" + permit.consent_id)
    )
    assert saved["restorable"] is False and saved["scope"] == scope


def test_scope_accepts_only_actual_durable_follow_run(approved, monkeypatch):
    complete(approved, monkeypatch)
    from coin_prep_fee_runtime import _configuration, _verified_identity

    configuration = _configuration()
    identity = {
        **_verified_identity(configuration),
        "asset_id": configuration["CAT_ASSET_ID"],
        "wallet_id": configuration["CAT_WALLET_ID"],
        "xch_wallet_id": configuration["WALLET_ID_XCH"],
        "ticker": configuration["CAT_TICKER_ID"],
    }
    now = int(datetime.now(timezone.utc).timestamp())
    run = database.create_follow_run_authority(
        consent_id="d" * 64,
        approval_id=approved["approval"]["approval_id"],
        identity=identity,
        configuration_sha256=policy.current_configuration_digest(),
        buy_limit=configuration["MAX_ACTIVE_BUY_OFFERS"],
        sell_limit=configuration["MAX_ACTIVE_SELL_OFFERS"],
        started_at_epoch=now,
        expires_at_epoch=now + 48 * 3600,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    scope = policy.current_scope()
    assert scope["follow_run_id"] == run["run_id"]
    assert scope["financial_consent_id"] == "d" * 64
    database.stop_follow_run_authority(run_id=run["run_id"], stopped_at_epoch=now)
    with pytest.raises(ValueError, match="FOLLOW_FEE_AUTHORITY_REQUIRED"):
        policy.current_scope()


def test_completed_prep_consent_alone_cannot_grant_override(approved, monkeypatch):
    complete(approved, monkeypatch)
    monkeypatch.delattr(database, "get_follow_creation_authority", raising=False)
    with pytest.raises(ValueError, match="FOLLOW_FEE_AUTHORITY_REQUIRED"):
        policy.current_scope()


@pytest.mark.parametrize(
    "changes",
    [
        {"ready": False, "reason_code": "FOLLOW_FEE_AUTHORITY_REQUIRED"},
        {"run_id": None},
        {"consent_id": "bad"},
        {"identity": {}},
        {"configuration_sha256": "0" * 64},
        {"buy_limit": 24},
        {"expires_at_epoch": 1},
        {"maximum_fee_mojos": True},
        {"protected_shutdown_fee_mojos": 50000000001},
    ],
)
def test_unproved_or_mismatched_run_blocks_before_override(
    approved, monkeypatch, changes
):
    complete(approved, monkeypatch)
    install_reader(monkeypatch, changes)
    with pytest.raises(ValueError):
        policy.current_scope()


def test_wrong_wallet_never_uses_old_follow_run(approved, monkeypatch):
    complete(approved, monkeypatch)
    install_reader(monkeypatch)
    approved["identity"]["fingerprint"] = 1234
    with pytest.raises(ValueError, match="IDENTITY_UNAVAILABLE"):
        policy.current_scope()


def test_pending_effect_blocks_but_is_identified_as_temporary(approved, monkeypatch):
    complete(approved, monkeypatch)
    install_reader(
        monkeypatch, {"ready": False, "reason_code": "FOLLOW_UNRESOLVED_EFFECT"}
    )
    with pytest.raises(ValueError, match="CONFIDENCE_OVERRIDE_OPERATION_PENDING"):
        policy.current_scope()


def test_mutable_counters_do_not_rebind_risk_consent(approved, monkeypatch):
    complete(approved, monkeypatch)
    changes = {"spent_fee_mojos": 0, "held_fee_mojos": 0}
    install_reader(monkeypatch, changes)
    first = policy.current_scope()
    changes["spent_fee_mojos"] = 1000
    changes["held_fee_mojos"] = 100
    assert policy.current_scope() == first
