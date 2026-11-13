"""A fee-cap grant is separate from immutable Follow run policy authority."""

from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

import follow_run_fee_cap_grant as service
from follow_run_policy import FollowRunPolicy


@pytest.fixture
def grant_world(monkeypatch):
    import database
    import tx_fees

    policy = FollowRunPolicy(
        wallet_fingerprint="123",
        network="mainnet",
        asset_id="a" * 64,
        buy_target=2,
        sell_target=3,
        price_anchor=Decimal("0.01"),
        price_min=Decimal("0.009"),
        price_max=Decimal("0.011"),
        maximum_fee_mojos_per_tx=100,
        fee_coin_principal_mojos=1_000,
        xch_reserve_mojos=10,
        cat_reserve_atoms=10,
        maximum_trade_xch_mojos=500,
        maximum_trade_cat_atoms=600,
    )
    state = {
        "state": "running",
        "run_id": "b" * 64,
        "session_id": "c" * 64,
        "policy_digest": policy.digest,
        "configuration_sha256": "d" * 64,
    }
    identity = {
        "network": "mainnet",
        "wallet_fingerprint": 123,
        "asset_id": "a" * 64,
        "wallet_type": "sage",
        "wallet_id": 1,
    }
    monkeypatch.setattr(
        service,
        "_active_context",
        lambda *, now_epoch: (state, policy, identity, "d" * 64),
    )
    saved = {}
    quote = {
        "available": True,
        "fee_mojos": 150,
        "source": "test_node",
        "observed_at": 100,
        "target_seconds": 300,
        "cost": 1234,
    }
    monkeypatch.setattr(
        tx_fees,
        "get_suggested_transaction_fee",
        lambda *, force_refresh: dict(quote),
    )
    monkeypatch.setattr(
        database,
        "set_setting",
        lambda key, value: saved.__setitem__(key, value) or True,
    )
    monkeypatch.setattr(database, "get_setting", lambda key: saved.get(key))
    return policy, state, identity, saved, quote


def test_confirmation_creates_run_bound_grant_without_mutating_policy(grant_world):
    policy, state, identity, saved, _quote = grant_world
    original_digest = policy.digest
    review_result = service.prepare_follow_run_fee_cap_grant(now_epoch=100)
    review = review_result["review"]
    assert review_result["dispatch_authorized"] is False
    assert review["proposed_maximum_fee_mojos_per_tx"] == 150
    assert review["wallet_identity"] == identity
    assert review["network_recommendation"]["source"] == "test_node"

    confirmed = service.confirm_follow_run_fee_cap_grant(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        now_epoch=101,
    )
    grant = confirmed["grant"]
    assert grant["run_id"] == state["run_id"]
    assert grant["session_id"] == state["session_id"]
    assert grant["policy_digest"] == original_digest
    assert grant["maximum_fee_mojos_per_tx"] == 150
    assert grant["dispatch_authorized"] is False
    assert policy.maximum_fee_mojos_per_tx == 100
    assert policy.digest == original_digest
    assert (
        service.get_follow_run_fee_cap_grant(run_id=state["run_id"], now_epoch=102)
        == grant
    )
    assert json.loads(saved[service._GRANT_KEY]) == grant
    with pytest.raises(ValueError, match="FOLLOW_FEE_CAP_GRANT_REVIEW_REQUIRED"):
        service.confirm_follow_run_fee_cap_grant(
            review_id=review["review_id"],
            review_sha256=review["review_sha256"],
            accepted=True,
            now_epoch=102,
        )


def test_review_uses_server_recommendation_and_requires_strictly_higher_fee(
    grant_world,
):
    _policy, _state, _identity, _saved, quote = grant_world
    quote["fee_mojos"] = 100
    with pytest.raises(ValueError, match="FOLLOW_FEE_CAP_GRANT_NOT_REQUIRED"):
        service.prepare_follow_run_fee_cap_grant(now_epoch=100)


def test_confirmation_requires_explicit_acceptance_and_unexpired_exact_review(
    grant_world,
):
    review = service.prepare_follow_run_fee_cap_grant(now_epoch=100)["review"]
    with pytest.raises(ValueError, match="FOLLOW_FEE_CAP_GRANT_CONFIRMATION_REQUIRED"):
        service.confirm_follow_run_fee_cap_grant(
            review_id=review["review_id"],
            review_sha256=review["review_sha256"],
            accepted=False,
            now_epoch=101,
        )
    with pytest.raises(ValueError, match="FOLLOW_FEE_CAP_GRANT_REVIEW_EXPIRED"):
        service.confirm_follow_run_fee_cap_grant(
            review_id=review["review_id"],
            review_sha256=review["review_sha256"],
            accepted=True,
            now_epoch=review["expires_at_epoch"],
        )


def test_review_rejects_changed_run_or_policy_binding(grant_world, monkeypatch):
    policy, state, identity, _saved, _quote = grant_world
    review = service.prepare_follow_run_fee_cap_grant(now_epoch=100)["review"]
    changed = {**state, "run_id": "e" * 64}
    monkeypatch.setattr(
        service,
        "_active_context",
        lambda *, now_epoch: (changed, policy, identity, "d" * 64),
    )
    with pytest.raises(ValueError, match="FOLLOW_FEE_CAP_GRANT_REVIEW_CHANGED"):
        service.confirm_follow_run_fee_cap_grant(
            review_id=review["review_id"],
            review_sha256=review["review_sha256"],
            accepted=True,
            now_epoch=101,
        )


def test_confirmation_rechecks_recommendation_and_consumes_only_matching_quote(
    grant_world,
):
    _policy, _state, _identity, _saved, quote = grant_world
    review = service.prepare_follow_run_fee_cap_grant(now_epoch=100)["review"]
    quote["fee_mojos"] = 151
    with pytest.raises(ValueError, match="FOLLOW_FEE_CAP_GRANT_REVIEW_CHANGED"):
        service.confirm_follow_run_fee_cap_grant(
            review_id=review["review_id"],
            review_sha256=review["review_sha256"],
            accepted=True,
            now_epoch=101,
        )


def test_confirmation_accepts_same_fresh_fee_with_new_observation_time(grant_world):
    _policy, _state, _identity, _saved, quote = grant_world
    review = service.prepare_follow_run_fee_cap_grant(now_epoch=100)["review"]
    quote["observed_at"] = 101
    result = service.confirm_follow_run_fee_cap_grant(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        now_epoch=101,
    )
    assert result["success"] is True


def test_grant_read_fails_closed_for_other_run_or_modified_record(grant_world):
    policy, state, _identity, saved, _quote = grant_world
    review = service.prepare_follow_run_fee_cap_grant(now_epoch=100)["review"]
    service.confirm_follow_run_fee_cap_grant(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        accepted=True,
        now_epoch=101,
    )
    assert service.get_follow_run_fee_cap_grant(run_id="e" * 64, now_epoch=102) is None
    record = json.loads(saved[service._GRANT_KEY])
    record["maximum_fee_mojos_per_tx"] = 1_000
    saved[service._GRANT_KEY] = json.dumps(record)
    assert (
        service.get_follow_run_fee_cap_grant(run_id=state["run_id"], now_epoch=102)
        is None
    )
    assert policy.maximum_fee_mojos_per_tx == 100


def _bridge_method(name):
    from app_bridge import AppBridge

    method = getattr(AppBridge, name)
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def test_native_bridge_requires_exact_prepare_and_acceptance(monkeypatch):
    import follow_run_fee_cap_grant

    calls = []
    monkeypatch.setattr(
        follow_run_fee_cap_grant,
        "prepare_follow_run_fee_cap_grant",
        lambda **kw: (
            calls.append(("prepare", kw))
            or {"success": True, "dispatch_authorized": False}
        ),
    )
    monkeypatch.setattr(
        follow_run_fee_cap_grant,
        "confirm_follow_run_fee_cap_grant",
        lambda **kw: (
            calls.append(("confirm", kw))
            or {"success": True, "dispatch_authorized": False}
        ),
    )
    prepare = _bridge_method("prepare_follow_run_fee_cap_grant")
    confirm = _bridge_method("confirm_follow_run_fee_cap_grant")
    invalid = prepare(SimpleNamespace(), {"recommended_fee_mojos": True})
    assert invalid["success"] is False
    assert calls == []
    supplied_value = prepare(SimpleNamespace(), {"recommended_fee_mojos": 150})
    assert supplied_value["success"] is False
    prepared = prepare(SimpleNamespace(), {})
    assert prepared["success"] is True
    declined = confirm(
        SimpleNamespace(),
        {"review_id": "a" * 64, "review_sha256": "b" * 64, "accepted": False},
    )
    assert declined["success"] is False
    accepted = confirm(
        SimpleNamespace(),
        {"review_id": "a" * 64, "review_sha256": "b" * 64, "accepted": True},
    )
    assert accepted["success"] is True
    assert calls == [
        ("prepare", {}),
        (
            "confirm",
            {"review_id": "a" * 64, "review_sha256": "b" * 64, "accepted": True},
        ),
    ]
