"""Durable restart intent is a reminder, never wallet authority."""

import json

import pytest

import database
from follow_restart_intent import (
    bind_follow_restart_intent,
    clear_follow_restart_intent,
    read_follow_restart_intent,
    restart_intent_matches,
)


RUN_ID = "a" * 64
IDENTITY = {
    "network": "mainnet",
    "wallet_type": "sage",
    "wallet_fingerprint": 123,
    "wallet_id": 2,
    "xch_wallet_id": 1,
    "asset_id": "b" * 64,
}
CONFIG = "c" * 64


@pytest.fixture
def saved_setting(monkeypatch):
    state = {"raw": None}
    monkeypatch.setattr(
        database, "get_setting", lambda _key, default=None: state["raw"] or default
    )
    monkeypatch.setattr(
        database, "set_setting", lambda _key, value: state.update(raw=value) or True
    )
    return state


def test_running_intent_round_trips_exact_run_wallet_asset_and_config(saved_setting):
    written = bind_follow_restart_intent(
        run_id=RUN_ID, identity=IDENTITY, configuration_sha256=CONFIG, now_epoch=1234
    )
    assert json.loads(saved_setting["raw"]) == written
    saved = read_follow_restart_intent()
    assert saved == written
    assert restart_intent_matches(
        saved, run_id=RUN_ID, identity=IDENTITY, configuration_sha256=CONFIG
    )
    assert not restart_intent_matches(
        saved,
        run_id=RUN_ID,
        identity={**IDENTITY, "wallet_fingerprint": 456},
        configuration_sha256=CONFIG,
    )
    assert not restart_intent_matches(
        saved, run_id=RUN_ID, identity=IDENTITY, configuration_sha256="d" * 64
    )


def test_manual_stop_writes_durable_opt_out(saved_setting):
    bind_follow_restart_intent(
        run_id=RUN_ID, identity=IDENTITY, configuration_sha256=CONFIG, now_epoch=1234
    )
    stopped = clear_follow_restart_intent(now_epoch=1235)
    assert stopped["state"] == "stopped"
    assert stopped["reason"] == "manual_stop"
    assert read_follow_restart_intent() is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "{",
        "{}",
        '{"version":1,"state":"stopped"}',
        '{"version":1,"state":"running","run_id":"x"}',
    ],
)
def test_missing_or_malformed_intent_never_resumes(saved_setting, raw):
    saved_setting["raw"] = raw
    assert read_follow_restart_intent() is None


@pytest.mark.parametrize(
    "changes",
    [
        {"network": "testnet"},
        {"wallet_type": "chia"},
        {"wallet_fingerprint": True},
        {"asset_id": "bad"},
    ],
)
def test_binding_rejects_invalid_identity(changes):
    with pytest.raises(ValueError, match="FOLLOW_RESTART_INTENT_INVALID"):
        bind_follow_restart_intent(
            run_id=RUN_ID,
            identity={**IDENTITY, **changes},
            configuration_sha256=CONFIG,
            now_epoch=1234,
        )


def test_failed_persistence_is_not_reported_as_saved(monkeypatch):
    monkeypatch.setattr(database, "set_setting", lambda *_args: False)
    with pytest.raises(ValueError, match="FOLLOW_RESTART_INTENT_PERSIST_FAILED"):
        bind_follow_restart_intent(
            run_id=RUN_ID,
            identity=IDENTITY,
            configuration_sha256=CONFIG,
            now_epoch=1234,
        )
