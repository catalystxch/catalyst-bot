from types import SimpleNamespace

import pytest


CONFIGURATION_SHA256 = "b" * 64
ASSET_ID = "a" * 64
IDENTITY = {
    "network": "mainnet",
    "wallet_type": "sage",
    "wallet_fingerprint": "123",
    "wallet_id": 2,
    "xch_wallet_id": 1,
    "asset_id": ASSET_ID,
    "ticker": "MZ",
}


def policy_terms(**changes):
    values = {
        "buy_target": 100,
        "sell_target": 100,
        "price_anchor": "0.0123",
        "price_min": "0.011",
        "price_max": "0.013",
        "maximum_fee_mojos_per_tx": "2000000",
        "fee_coin_principal_mojos": "8000000000",
        "xch_reserve_mojos": "1000000000",
        "cat_reserve_atoms": "25000",
        "maximum_trade_xch_mojos": "100000000000",
        "maximum_trade_cat_atoms": "1000000000",
    }
    values.update(changes)
    return values


def test_native_defaults_keep_funding_server_owned(bridge_world, monkeypatch):
    import app_bridge
    import follow_run_defaults
    import follow_run_coordinator

    monkeypatch.setattr(follow_run_defaults, "exact_funding_defaults", lambda: {
        "buy_target": 24,
        "sell_target": 24,
        "fee_coin_principal_mojos": "1000000000000",
        "xch_reserve_mojos": "100000000000",
        "cat_reserve_atoms": "1000",
        "maximum_trade_xch_mojos": "3000000000000",
        "maximum_trade_cat_atoms": "500000",
        "wallet_identity": {**IDENTITY, "wallet_fingerprint": 123},
        "configuration_sha256": CONFIGURATION_SHA256,
    })
    result = app_bridge.AppBridge().get_single_approval_follow_run_defaults()
    assert result["success"] is True
    assert result["policy"]["maximum_trade_xch_mojos"] == "3000000000000"
    assert result["red_reasons"] == ["THIN_BOOK", "STALE_PRICE"]
    assert result["dispatch_authorized"] is False


def test_native_status_reports_durable_setup_without_dispatch(bridge_world, monkeypatch):
    import app_bridge
    import follow_run_coordinator

    monkeypatch.setattr(
        follow_run_coordinator.FollowRunCoordinator,
        "get_state",
        lambda self: {
            "session_id": "a" * 64,
            "state": "preparing",
            "recoverable_reason": None,
        },
    )
    result = app_bridge.AppBridge().get_single_approval_follow_run_status()
    assert result == {
        "success": True,
        "session_id": "a" * 64,
        "state": "preparing",
        "recoverable_reason": None,
    }


def test_native_review_rejects_client_inflated_principal(bridge_world):
    bridge, _observed, _hash, _database = bridge_world
    result = bridge.prepare_single_approval_follow_run_review({
        "policy": policy_terms(maximum_trade_xch_mojos="999999999999999999")
    })
    assert result["success"] is False
    assert result["reason"] == "FOLLOW_RUN_REVIEW_FUNDING_CHANGED"


def test_new_policy_cannot_replace_active_session_before_recording(bridge_world, monkeypatch):
    import follow_run_coordinator

    bridge, _observed, _hash, database = bridge_world
    terms = policy_terms()
    review = bridge.prepare_single_approval_follow_run_review({"policy": terms})
    monkeypatch.setattr(
        follow_run_coordinator.FollowRunCoordinator,
        "get_state",
        lambda self: {
            "state": "running",
            "policy_digest": "0" * 64,
            "configuration_sha256": CONFIGURATION_SHA256,
        },
    )
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda _policy: pytest.fail("must not replace running policy"),
    )
    result = bridge.confirm_single_approval_follow_run_review({
        "review_id": review["review_id"],
        "review_sha256": review["review_sha256"],
        "accepted": True,
        "policy": terms,
    })
    assert result["success"] is False
    assert result["reason"] == "FOLLOW_RUN_AUTHORITY_CHANGED"


@pytest.fixture
def bridge_world(monkeypatch):
    import app_bridge
    import coin_prep_fee_runtime
    import confidence_override
    import database
    import follow_run_defaults
    import follow_run_coordinator
    import tx_fees

    configuration = {
        "network": "mainnet",
        "WALLET_TYPE": "sage",
        "CAT_ASSET_ID": ASSET_ID,
        "CAT_WALLET_ID": 2,
        "WALLET_ID_XCH": 1,
        "CAT_TICKER_ID": "MZ",
    }
    config_hash = {"value": CONFIGURATION_SHA256}
    observed = {"identity_calls": 0, "reasons": ["THIN_BOOK", "STALE_PRICE"]}

    def verified_identity(_configuration):
        observed["identity_calls"] += 1
        return {
            "network": "mainnet",
            "wallet_type": "sage",
            "wallet_fingerprint": 123,
        }

    monkeypatch.setattr(coin_prep_fee_runtime, "_configuration", lambda: configuration)
    monkeypatch.setattr(coin_prep_fee_runtime, "_verified_identity", verified_identity)
    monkeypatch.setattr(follow_run_coordinator.FollowRunCoordinator, "get_state", lambda self: None)
    monkeypatch.setattr(follow_run_defaults, "exact_funding_defaults", lambda: {
        **{key: value for key, value in policy_terms().items() if key in {
            "fee_coin_principal_mojos", "xch_reserve_mojos",
            "cat_reserve_atoms", "maximum_trade_xch_mojos",
            "maximum_trade_cat_atoms",
        }},
        "wallet_identity": {**IDENTITY, "wallet_fingerprint": 123},
        "configuration_sha256": config_hash["value"],
        "buy_target": 100,
        "sell_target": 100,
    })
    monkeypatch.setattr(
        confidence_override,
        "current_configuration_digest",
        lambda: config_hash["value"],
    )
    monkeypatch.setattr(
        confidence_override,
        "_configuration_digest",
        lambda _configuration: config_hash["value"],
    )
    monkeypatch.setattr(
        database,
        "get_latest_market_confidence_snapshot",
        lambda asset: {
            "asset_id": asset,
            "state": "RED",
            "reason_codes": list(observed["reasons"]),
        },
    )
    monkeypatch.setattr(
        tx_fees,
        "get_fee_settings_snapshot",
        lambda: {
            "suggested": {
                "available": True,
                "fee_mojos": 1200,
                "fee_xch": "0.0000000012",
                "source": "full_node_rpc",
                "observed_at": "2026-11-13T10:00:00+00:00",
                "target_seconds": 30,
            }
        },
    )
    monkeypatch.setattr(
        app_bridge,
        "_bridge_runtime_api",
        lambda _bridge: SimpleNamespace(wallet_setup_bootstrap_allows=lambda _op: True),
    )
    return app_bridge.AppBridge(), observed, config_hash, database


def test_native_preview_uses_trusted_identity_and_market_reasons(bridge_world, monkeypatch):
    bridge, observed, _config_hash, database = bridge_world
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda _policy: pytest.fail("preview must not persist active authority"),
    )

    result = bridge.prepare_single_approval_follow_run_review(
        {"policy": policy_terms()}
    )

    assert result["success"] is True, result
    disclosure = result["disclosure"]
    assert disclosure["identity"] == IDENTITY
    assert disclosure["red_reasons"] == ["THIN_BOOK", "STALE_PRICE"]
    assert disclosure["configuration_sha256"] == CONFIGURATION_SHA256
    assert disclosure["policy"]["maximum_trade_xch_mojos"] == 100_000_000_000
    assert result["fee_recommendation"] == {
        "available": True,
        "fee_mojos": "1200",
        "fee_xch": "0.0000000012",
        "source": "full_node_rpc",
        "observed_at": "2026-11-13T10:00:00+00:00",
        "target_seconds": 30,
        "authoritative": False,
    }
    assert observed["identity_calls"] == 1


def test_preview_rejects_caller_supplied_identity_or_red_reasons(bridge_world):
    bridge, _observed, _config_hash, _database = bridge_world

    result = bridge.prepare_single_approval_follow_run_review(
        {
            "policy": policy_terms(),
            "wallet_identity": IDENTITY,
            "red_reasons": ["pretend-green"],
        }
    )

    assert result["success"] is False
    assert result["reason"] == "FOLLOW_RUN_REVIEW_REQUEST_INVALID"


def test_confirm_rederives_evidence_and_persists_only_explicit_confirmation(
    bridge_world, monkeypatch
):
    bridge, observed, _config_hash, database = bridge_world
    from follow_run_coordinator import FollowRunCoordinator

    persisted = []
    started_sessions = []
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda policy: persisted.append(policy) or True,
    )
    monkeypatch.setattr(
        FollowRunCoordinator,
        "begin_run",
        lambda _self, **kwargs: started_sessions.append(kwargs)
        or {"session_id": "d" * 64, "state": "prep_pending"},
    )
    terms = policy_terms()
    review = bridge.prepare_single_approval_follow_run_review({"policy": terms})

    result = bridge.confirm_single_approval_follow_run_review(
        {
            "review_id": review["review_id"],
            "review_sha256": review["review_sha256"],
            "accepted": True,
            "policy": terms,
        }
    )

    assert result["success"] is True
    assert result["dispatch_authorized"] is False
    assert result["session_id"] == "d" * 64
    assert result["state"] == "prep_pending"
    assert len(persisted) == 1
    assert started_sessions == [
        {
            "policy_digest": persisted[0].digest,
            "configuration_sha256": CONFIGURATION_SHA256,
        }
    ]
    assert persisted[0].wallet_fingerprint == "123"
    assert observed["identity_calls"] == 2


def test_changed_red_snapshot_or_config_blocks_confirmation(bridge_world, monkeypatch):
    bridge, observed, config_hash, database = bridge_world
    monkeypatch.setattr(
        database,
        "record_active_follow_run_policy",
        lambda _policy: pytest.fail("changed evidence must not persist"),
    )
    terms = policy_terms()
    review = bridge.prepare_single_approval_follow_run_review({"policy": terms})
    observed["reasons"] = ["MARKET_EVIDENCE_WARMING"]
    config_hash["value"] = "c" * 64

    result = bridge.confirm_single_approval_follow_run_review(
        {
            "review_id": review["review_id"],
            "review_sha256": review["review_sha256"],
            "accepted": True,
            "policy": terms,
        }
    )

    assert result["success"] is False
    assert result["reason"] == "FOLLOW_RUN_REVIEW_CHANGED"
    assert observed["identity_calls"] == 2

