import json
from decimal import Decimal

import pytest

import database
from follow_run_policy import FollowRunPolicy


def make_policy(**changes):
    terms = {
        "wallet_fingerprint": "fingerprint-123",
        "network": "mainnet",
        "asset_id": "a" * 64,
        "buy_target": 100,
        "sell_target": 100,
        "price_anchor": Decimal("0.0123"),
        "price_min": Decimal("0.011"),
        "price_max": Decimal("0.013"),
        "maximum_fee_mojos_per_tx": 2_000_000,
        "fee_coin_principal_mojos": 8_000_000_000,
        "xch_reserve_mojos": 1_000_000_000,
        "cat_reserve_atoms": 25_000,
        "maximum_trade_xch_mojos": 2_000_000_000_000,
        "maximum_trade_cat_atoms": 1_000_000,
    }
    terms.update(changes)
    return FollowRunPolicy(**terms)


@pytest.fixture
def saved_policy_setting(monkeypatch):
    state = {"raw": None}

    def get_setting(_key, default=None):
        return state["raw"] if state["raw"] is not None else default

    def set_setting(_key, value):
        state["raw"] = value
        return True

    monkeypatch.setattr(database, "get_setting", get_setting)
    monkeypatch.setattr(database, "set_setting", set_setting)
    return state


def test_active_policy_round_trips_through_canonical_durable_record(saved_policy_setting):
    from database import (
        get_active_follow_run_policy,
        record_active_follow_run_policy,
    )

    expected = make_policy()
    record_active_follow_run_policy(expected)
    envelope = json.loads(saved_policy_setting["raw"])

    assert envelope["version"] == 1
    assert envelope["digest"] == expected.digest
    assert get_active_follow_run_policy() == expected


def test_clear_active_policy_disables_future_read(saved_policy_setting):
    from database import (
        clear_active_follow_run_policy,
        get_active_follow_run_policy,
        record_active_follow_run_policy,
    )

    record_active_follow_run_policy(make_policy())
    assert clear_active_follow_run_policy() is True
    assert get_active_follow_run_policy() is None


def test_policy_tampering_and_duplicate_keys_fail_closed(saved_policy_setting):
    from database import get_active_follow_run_policy, record_active_follow_run_policy

    record_active_follow_run_policy(make_policy())
    envelope = json.loads(saved_policy_setting["raw"])
    envelope["terms"]["buy_target"] = 24
    saved_policy_setting["raw"] = json.dumps(envelope)
    assert get_active_follow_run_policy() is None

    saved_policy_setting["raw"] = (
        '{"version":1,"version":1,"terms":{},"digest":"' + "0" * 64 + '"}'
    )
    assert get_active_follow_run_policy() is None


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        "{}",
        '{"version":1,"terms":{},"digest":"' + "0" * 64 + '"}',
        '{"version":true,"terms":{},"digest":"' + "0" * 64 + '"}',
        '{"version":1,"terms":{},"digest":"' + "z" * 64 + '"}',
    ],
)
def test_malformed_active_policy_fails_closed(saved_policy_setting, raw):
    from database import get_active_follow_run_policy

    saved_policy_setting["raw"] = raw
    assert get_active_follow_run_policy() is None


def test_record_rejects_non_policy_and_reports_persistence_failure(monkeypatch):
    from database import record_active_follow_run_policy

    with pytest.raises(ValueError):
        record_active_follow_run_policy({})

    monkeypatch.setattr(database, "set_setting", lambda *_args: False)
    with pytest.raises(ValueError, match="FOLLOW_RUN_POLICY_PERSIST_FAILED"):
        record_active_follow_run_policy(make_policy())

