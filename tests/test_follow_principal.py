"""A Follow review must bound trading principal after protected wallet funds."""

from decimal import Decimal
import hashlib
import json

import pytest

from coin_prep_batch_plan import CoinSnapshot, SelectableCoin
from follow_principal import (
    calculate_follow_principal,
    preview_approved_follow_principal,
    read_follow_principal_snapshot,
)
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


def _coin(asset, marker, amount, *, purpose="", protected=False):
    return SelectableCoin(asset, marker * 64, amount, purpose, True, protected)


def test_max_safe_principal_preserves_fee_pool_and_configured_reserves():
    coins = CoinSnapshot(
        (
            _coin("xch", "a", 80_000_000_000),
            _coin("xch", "b", 12_000_000_000, purpose="reserve", protected=True),
            _coin("xch", "c", 30_000_000_000, purpose="fee_reserve"),
            _coin("cat", "d", 900_000),
            _coin("cat", "e", 100_000, purpose="reserve", protected=True),
        )
    )
    result = calculate_follow_principal(
        coins,
        xch_reserve=Decimal("0.02"),
        cat_reserve=Decimal("150"),
        cat_decimals=3,
        fee_cap_mojos=50_000_000_000,
        fee_pool_principal_mojos=40_000_000_000,
        fee_reserve_coin_ids={"c" * 64},
    )
    assert result["maximum_trade_xch_mojos"] == 52_000_000_000
    assert result["maximum_trade_cat_atoms"] == 850_000
    assert result["protected_fee_principal_mojos"] == 50_000_000_000
    assert result["protected_xch_reserve_mojos"] == 20_000_000_000
    assert result["protected_cat_reserve_atoms"] == 150_000
    assert result["unprotected_xch_coin_count"] == 1
    assert result["unprotected_cat_coin_count"] == 1


def test_principal_refuses_insufficient_xch_after_protected_fee():
    coins = CoinSnapshot((_coin("xch", "a", 49_000_000_000), _coin("cat", "b", 1000)))
    with pytest.raises(ValueError, match="FOLLOW_FEE_PRINCIPAL_UNAVAILABLE"):
        calculate_follow_principal(
            coins,
            xch_reserve=Decimal("0"),
            cat_reserve=Decimal("0"),
            cat_decimals=3,
            fee_cap_mojos=50_000_000_000,
            fee_pool_principal_mojos=0,
            fee_reserve_coin_ids=set(),
        )


def test_principal_rejects_duplicate_or_float_inventory():
    for coins in (
        CoinSnapshot((_coin("xch", "a", 100), _coin("cat", "a", 100))),
        CoinSnapshot((_coin("xch", "a", 100.0), _coin("cat", "b", 100))),
    ):
        with pytest.raises(ValueError, match="FOLLOW_PRINCIPAL_INVENTORY_INVALID"):
            calculate_follow_principal(
                coins,
                xch_reserve=Decimal("0"),
                cat_reserve=Decimal("0"),
                cat_decimals=3,
                fee_cap_mojos=1,
                fee_pool_principal_mojos=0,
                fee_reserve_coin_ids=set(),
            )


def test_live_principal_reader_uses_verified_snapshot_and_durable_fee_purpose(
    monkeypatch,
):
    import coin_prep_fee_runtime
    import database
    import tx_fees

    config = {
        "XCH_RESERVE": Decimal("0.02"),
        "CAT_RESERVE": Decimal("150"),
        "CAT_DECIMALS": 3,
    }
    snapshot = CoinSnapshot(
        (
            _coin("xch", "a", 80_000_000_000),
            _coin("xch", "b", 12_000_000_000, purpose="reserve", protected=True),
            _coin("xch", "c", 30_000_000_000),
            _coin("cat", "d", 900_000),
            _coin("cat", "e", 100_000, purpose="reserve", protected=True),
        )
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_fee_wallet_snapshot",
        lambda: {
            "identity": {"wallet_fingerprint": 123, "asset_id": "f" * 64},
            "configuration": config,
            "snapshot": snapshot,
        },
    )
    monkeypatch.setattr(
        database,
        "get_free_coins",
        lambda asset: (
            [{"coin_id": "c" * 64, "purpose": "fee_reserve"}] if asset == "xch" else []
        ),
    )
    monkeypatch.setattr(
        tx_fees,
        "get_fee_pool_plan",
        lambda: {"enabled": True, "count": 4, "coin_size_mojos": 10_000_000_000},
    )
    result = read_follow_principal_snapshot(fee_cap_mojos=50_000_000_000)
    assert result["maximum_trade_xch_mojos"] == 52_000_000_000
    assert result["maximum_trade_cat_atoms"] == 850_000
    assert result["identity"]["wallet_fingerprint"] == 123
    assert result["dispatch_authorized"] is False
    assert len(result["inventory_sha256"]) == 64
    assert len(result["principal_review_sha256"]) == 64
    assert (
        read_follow_principal_snapshot(fee_cap_mojos=50_000_000_000)[
            "principal_review_sha256"
        ]
        == result["principal_review_sha256"]
    )
    config["XCH_RESERVE"] = Decimal("0.03")
    assert (
        read_follow_principal_snapshot(fee_cap_mojos=50_000_000_000)[
            "principal_review_sha256"
        ]
        != result["principal_review_sha256"]
    )
    monkeypatch.setattr(
        database,
        "get_free_coins",
        lambda _asset: [{"coin_id": "b" * 64, "purpose": "fee_reserve"}],
    )
    with pytest.raises(ValueError, match="FOLLOW_PRINCIPAL_INVENTORY_INVALID"):
        read_follow_principal_snapshot(fee_cap_mojos=50_000_000_000)


def test_fee_coin_cannot_also_be_a_wallet_reserve():
    coins = CoinSnapshot(
        (
            _coin("xch", "a", 1000),
            _coin("xch", "b", 100, purpose="reserve", protected=True),
            _coin("cat", "c", 1000),
        )
    )
    with pytest.raises(ValueError, match="FOLLOW_PRINCIPAL_INVENTORY_INVALID"):
        calculate_follow_principal(
            coins,
            xch_reserve=Decimal("0"),
            cat_reserve=Decimal("0"),
            cat_decimals=3,
            fee_cap_mojos=1,
            fee_pool_principal_mojos=0,
            fee_reserve_coin_ids={"b" * 64},
        )


def test_approved_principal_preview_binds_scope_and_rechecks_fee_state(monkeypatch):
    import confidence_override
    import coin_prep_fee_approval
    import coin_prep_fee_runtime
    import database
    import follow_principal

    approval_id = "a" * 64
    identity = {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 123,
        "wallet_id": 2,
        "xch_wallet_id": 1,
        "asset_id": "f" * 64,
        "ticker": "MZ",
    }
    scope = {**identity, "campaign_id": None, "session_id": "b" * 64}
    scope_json = json.dumps(scope, sort_keys=True, separators=(",", ":"))
    plan_json = json.dumps(
        {
            "outputs": [
                {"asset": "xch", "purpose": "replacement", "amount_mojos": 10},
                {"asset": "cat", "purpose": "replacement", "amount_mojos": 20},
                {"asset": "xch", "purpose": "fee_reserve", "amount_mojos": 30},
            ]
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    context = {
        "scope_json": scope_json,
        "scope_sha256": hashlib.sha256(scope_json.encode()).hexdigest(),
        "plan_json": plan_json,
        "plan_sha256": hashlib.sha256(plan_json.encode()).hexdigest(),
        "version": 1,
        "latest_version": 1,
    }
    status = {
        "approval_id": approval_id,
        "stale": False,
        "session_completed": True,
        "unresolved_operation_count": 0,
        "total_fee_mojos": 50_000_000_000,
        "cancellation_reserve_mojos": 10_000_000_000,
        "spent_fee_mojos": 0,
        "held_fee_mojos": 0,
        "remaining_fee_mojos": 50_000_000_000,
    }
    principal = {
        "identity": identity,
        "principal_review_sha256": "e" * 64,
        "maximum_trade_xch_mojos": 100_000_000_000,
        "maximum_trade_cat_atoms": 1_000_000,
        "dispatch_authorized": False,
    }
    monkeypatch.setattr(
        database, "get_coin_prep_fee_approval_context", lambda _id: context
    )
    monkeypatch.setattr(
        database, "get_coin_prep_fee_approval_status", lambda _id: dict(status)
    )
    monkeypatch.setattr(
        follow_principal,
        "_principal_from_observed_snapshot",
        lambda *_a, **_kw: principal,
    )
    monkeypatch.setattr(
        confidence_override, "current_configuration_digest", lambda: "f" * 64
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_approved_prep_fee_snapshot",
        lambda _id: (_ for _ in ()).throw(ValueError("FEE_APPROVAL_STALE")),
    )
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        preview_approved_follow_principal(approval_id)
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_approved_prep_fee_snapshot",
        lambda _id: {"scope": scope, "identity": identity},
    )
    monkeypatch.setattr(
        coin_prep_fee_approval,
        "_prove_approved_coin_prep_targets",
        lambda _context: (_ for _ in ()).throw(ValueError("FEE_SESSION_INCOMPLETE")),
    )
    with pytest.raises(ValueError, match="FEE_SESSION_INCOMPLETE"):
        preview_approved_follow_principal(approval_id)
    monkeypatch.setattr(
        coin_prep_fee_approval,
        "_prove_approved_coin_prep_targets",
        lambda _context: object(),
    )
    result = preview_approved_follow_principal(approval_id)
    assert result["identity"] == identity
    assert result["maximum_trade_xch_mojos"] == 100_000_000_000
    assert result["maximum_fee_mojos"] == 50_000_000_000
    assert result["configuration_sha256"] == "f" * 64
    assert result["planned_replacement_xch_coin_count"] == 1
    assert result["planned_replacement_cat_coin_count"] == 1
    assert result["planned_replacement_xch_mojos"] == 10
    assert result["planned_replacement_cat_atoms"] == 20
    assert result["current_prep_targets_proven"] is True
    assert len(result["proposal_sha256"]) == 64
    assert result["dispatch_authorized"] is False
    status["stale"] = True
    with pytest.raises(ValueError, match="FOLLOW_FEE_APPROVAL_STALE"):
        preview_approved_follow_principal(approval_id)
    status["stale"] = False
    drifted = dict(principal)
    drifted["identity"] = {**identity, "wallet_fingerprint": 456}
    monkeypatch.setattr(
        follow_principal,
        "_principal_from_observed_snapshot",
        lambda *_a, **_kw: drifted,
    )
    with pytest.raises(ValueError, match="FOLLOW_PRINCIPAL_REVIEW_CHANGED"):
        preview_approved_follow_principal(approval_id)
    context["plan_json"] = (
        '{"outputs":[{"asset":"xch","purpose":"replacement","amount_mojos":true}]}'
    )
    context["plan_sha256"] = hashlib.sha256(context["plan_json"].encode()).hexdigest()
    with pytest.raises(ValueError, match="FOLLOW_FEE_SCOPE_INVALID"):
        preview_approved_follow_principal(approval_id)


def test_approved_principal_preview_rejects_fee_change_during_wallet_read(monkeypatch):
    import confidence_override
    import coin_prep_fee_approval
    import coin_prep_fee_runtime
    import database
    import follow_principal

    approval_id = "a" * 64
    scope = {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 123,
        "wallet_id": 2,
        "xch_wallet_id": 1,
        "asset_id": "f" * 64,
        "ticker": "MZ",
        "campaign_id": None,
        "session_id": "b" * 64,
    }
    scope_json = json.dumps(scope, sort_keys=True, separators=(",", ":"))
    plan_json = '{"outputs":[]}'
    context = {
        "scope_json": scope_json,
        "scope_sha256": hashlib.sha256(scope_json.encode()).hexdigest(),
        "plan_json": plan_json,
        "plan_sha256": hashlib.sha256(plan_json.encode()).hexdigest(),
        "version": 1,
        "latest_version": 1,
    }
    status = {
        "approval_id": approval_id,
        "stale": False,
        "session_completed": True,
        "unresolved_operation_count": 0,
        "total_fee_mojos": 50_000_000_000,
        "cancellation_reserve_mojos": 10_000_000_000,
        "spent_fee_mojos": 0,
        "held_fee_mojos": 0,
        "remaining_fee_mojos": 50_000_000_000,
    }
    calls = iter((dict(status), {**status, "held_fee_mojos": 1}))
    monkeypatch.setattr(
        database, "get_coin_prep_fee_approval_status", lambda _id: next(calls)
    )
    monkeypatch.setattr(
        database, "get_coin_prep_fee_approval_context", lambda _id: context
    )
    monkeypatch.setattr(
        follow_principal,
        "_principal_from_observed_snapshot",
        lambda *_a, **_kw: {
            "identity": {
                key: scope[key]
                for key in scope
                if key not in {"campaign_id", "session_id"}
            },
            "principal_review_sha256": "e" * 64,
        },
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_approved_prep_fee_snapshot",
        lambda _id: {"scope": scope},
    )
    monkeypatch.setattr(
        coin_prep_fee_approval,
        "_prove_approved_coin_prep_targets",
        lambda _context: object(),
    )
    monkeypatch.setattr(
        confidence_override, "current_configuration_digest", lambda: "f" * 64
    )
    with pytest.raises(ValueError, match="FOLLOW_PRINCIPAL_REVIEW_CHANGED"):
        preview_approved_follow_principal(approval_id)


def test_approved_principal_preview_proves_current_frozen_prep_targets(
    approved, monkeypatch
):
    from importlib import import_module

    import config
    from fee_approval_test_utils import _coin

    runtime = import_module("coin_prep_fee_runtime")
    service = import_module("coin_prep_fee_approval")
    targets = runtime.read_approved_prep_fee_snapshot(
        approved["approval"]["approval_id"]
    )["recipe"]["targets"]
    approved["xch"] = [
        _coin(20000 + i, str(target.amount_mojos))
        for i, target in enumerate(targets)
        if target.asset == "xch"
    ]
    approved["cat"] = [
        _coin(30000 + i, str(target.amount_mojos))
        for i, target in enumerate(targets)
        if target.asset == "cat"
    ]
    service.complete_coin_prep_fee_session(approved["approval"]["approval_id"])
    monkeypatch.setattr(config, "cfg", approved["config"])
    result = preview_approved_follow_principal(approved["approval"]["approval_id"])
    assert result["current_prep_targets_proven"] is True
    assert result["planned_replacement_xch_coin_count"] == 1
    assert result["planned_replacement_cat_coin_count"] == 1
    assert result["dispatch_authorized"] is False
    approved["cat"] = []
    with pytest.raises(ValueError, match="FEE_SESSION_INCOMPLETE"):
        preview_approved_follow_principal(approved["approval"]["approval_id"])
