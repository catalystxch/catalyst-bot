"""Read-only Follow cancellation pricing remains inside the reviewed run."""

import json
from importlib import import_module
from unittest.mock import patch

import database
import pytest
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


@pytest.fixture(autouse=True)
def current_database_module():
    global database
    database = import_module("database")


def _run(approved):
    global database
    database = import_module("database")
    scope = json.loads(
        database.get_coin_prep_fee_approval_context(
            approved["approval"]["approval_id"]
        )["scope_json"]
    )
    identity = {
        key: scope[key]
        for key in (
            "network",
            "wallet_type",
            "wallet_fingerprint",
            "wallet_id",
            "xch_wallet_id",
            "asset_id",
            "ticker",
        )
    }
    terms = dict(
        approval_id=approved["approval"]["approval_id"],
        identity=identity,
        configuration_sha256="a" * 64,
        principal_review_sha256="d" * 64,
        buy_limit=24,
        sell_limit=24,
        started_at_epoch=1001,
        expires_at_epoch=1001 + 48 * 3600,
        maximum_fee_mojos=80,
        protected_shutdown_fee_mojos=40,
    )
    review = database.create_follow_run_review(**terms)
    with patch.object(database.time, "time", return_value=1002):
        run = database.create_follow_run_authority(
            consent_id=review["review_id"],
            review_sha256=review["review_sha256"],
            **terms,
        )
    return run["run_id"], identity


def test_follow_cleanup_identity_reader_survives_stop(approved):
    run_id, identity = _run(approved)
    assert database.get_follow_run_identity(run_id) == identity
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1002)
    assert database.get_follow_run_identity(run_id) == identity
    with pytest.raises(ValueError, match="FOLLOW_AUTHORITY_REQUIRED"):
        database.get_follow_run_identity("0" * 64)


def test_follow_cancel_price_requires_positive_fresh_fee_and_does_not_dispatch(
    approved, monkeypatch
):
    run_id, identity = _run(approved)
    pricing = import_module("follow_fee_cancellation")
    wallet = import_module("wallet")
    calls = []

    def build(trade_ids, *, fee_mojos, source_coin_ids, fee_coin_id):
        calls.append(fee_mojos)
        return {
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": 123456,
            "_catalyst_cancel_unsigned_digest": "f" * 64,
        }

    monkeypatch.setattr(wallet, "build_cancel_offers_batch_unsigned", build)
    monkeypatch.setattr(
        pricing,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 1002,
            "expires_at": 1062,
        },
    )
    monkeypatch.setattr(pricing, "is_current_fee_quote", lambda *_args: True)
    result = pricing.price_follow_cancellation(
        run_id=run_id,
        identity=identity,
        trade_ids=["b" * 64],
        source_coin_ids=["c" * 64],
        fee_coin_id="d" * 64,
        now_epoch=1002,
    )
    assert result["available"] is True
    assert result["fee_mojos"] == 20
    assert result["authority"]["run_id"] == run_id
    assert result["dispatch_authorized"] is False
    assert calls == [0, 20]

    monkeypatch.setattr(
        pricing,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": 0,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 1002,
            "expires_at": 1062,
        },
    )
    refused = pricing.price_follow_cancellation(
        run_id=run_id,
        identity=identity,
        trade_ids=["b" * 64],
        source_coin_ids=["c" * 64],
        fee_coin_id="d" * 64,
        now_epoch=1002,
    )
    assert refused["available"] is False
    assert refused["reason"] == "FEE_CANCELLATION_FUNDING_REQUIRED"
    assert refused["dispatch_authorized"] is False


def test_follow_cancel_price_refuses_unsigned_cost_above_one_block(
    approved, monkeypatch
):
    run_id, identity = _run(approved)
    pricing = import_module("follow_fee_cancellation")
    wallet = import_module("wallet")
    monkeypatch.setattr(
        wallet,
        "build_cancel_offers_batch_unsigned",
        lambda *_args, **_kwargs: {
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": 11_000_000_001,
        },
    )
    monkeypatch.setattr(
        pricing,
        "quote_fee",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("oversized batch must not be quoted")
        ),
    )
    result = pricing.price_follow_cancellation(
        run_id=run_id,
        identity=identity,
        trade_ids=["b" * 64],
        source_coin_ids=["c" * 64],
        fee_coin_id="d" * 64,
        now_epoch=1002,
    )
    assert result["available"] is False
    assert result["reason"] == "FEE_CANCELLATION_BATCH_OVER_BLOCK_LIMIT"
    assert result["dispatch_authorized"] is False


def test_follow_cancel_price_refuses_unresolved_run_before_unsigned_build(
    approved, monkeypatch
):
    run_id, identity = _run(approved)
    database.reserve_approved_fee(
        approval_id=approved["approval"]["approval_id"],
        scope_sha256=approved["approval"]["scope_sha256"],
        plan_sha256=approved["approval"]["plan_sha256"],
        operation_id="e" * 64,
        fee_mojos=1,
        cancellation=True,
    )
    pricing = import_module("follow_fee_cancellation")
    monkeypatch.setattr(
        import_module("wallet"),
        "build_cancel_offers_batch_unsigned",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("wallet read")),
    )
    result = pricing.price_follow_cancellation(
        run_id=run_id,
        identity=identity,
        trade_ids=["b" * 64],
        source_coin_ids=["c" * 64],
        fee_coin_id="d" * 64,
        now_epoch=1002,
    )
    assert result["available"] is False
    assert result["reason"] == "FOLLOW_UNRESOLVED_EFFECT"


def test_follow_cancel_price_refuses_fee_above_remaining_run_cap(approved, monkeypatch):
    run_id, identity = _run(approved)
    pricing = import_module("follow_fee_cancellation")
    monkeypatch.setattr(
        import_module("wallet"),
        "build_cancel_offers_batch_unsigned",
        lambda *_args, **_kwargs: {
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": 123456,
        },
    )
    monkeypatch.setattr(
        pricing,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": 81,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 1002,
            "expires_at": 1062,
        },
    )
    monkeypatch.setattr(pricing, "is_current_fee_quote", lambda *_args: True)
    result = pricing.price_follow_cancellation(
        run_id=run_id,
        identity=identity,
        trade_ids=["b" * 64],
        source_coin_ids=["c" * 64],
        fee_coin_id="d" * 64,
        now_epoch=1002,
    )
    assert result["available"] is False
    assert result["reason"] == "FEE_BUDGET_EXCEEDED"
    assert result["required_fee_mojos"] == 81
    assert result["dispatch_authorized"] is False


def test_follow_cancel_price_uses_current_confirmed_ceiling(approved, monkeypatch):
    run_id, identity = _run(approved)
    review = database.create_follow_fee_ceiling_review(
        run_id=run_id,
        identity=identity,
        configuration_sha256="a" * 64,
        proposed_maximum_fee_mojos=120,
        observed_fee_principal_mojos=120,
        now_epoch=1002,
    )
    database.confirm_follow_fee_ceiling_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        identity=identity,
        configuration_sha256="a" * 64,
        observed_fee_principal_mojos=120,
        now_epoch=1003,
    )
    pricing = import_module("follow_fee_cancellation")
    monkeypatch.setattr(
        import_module("wallet"),
        "build_cancel_offers_batch_unsigned",
        lambda *_args, **_kwargs: {
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": 123456,
        },
    )
    monkeypatch.setattr(
        pricing,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 1004,
            "expires_at": 1064,
        },
    )
    monkeypatch.setattr(pricing, "is_current_fee_quote", lambda *_args: True)
    result = pricing.price_follow_cancellation(
        run_id=run_id,
        identity=identity,
        trade_ids=["b" * 64],
        source_coin_ids=["c" * 64],
        fee_coin_id="d" * 64,
        now_epoch=1004,
    )
    assert result["available"] is True
    assert result["authority"]["maximum_fee_mojos"] == 120
    assert result["authority"]["revision"] == 1
