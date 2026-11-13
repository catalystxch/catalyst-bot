"""Fee-cap grants are applied only inside an exact active-run scope."""

from types import SimpleNamespace


def test_cancellation_fee_cap_uses_exact_run_bound_grant(monkeypatch):
    import confidence_override
    import database
    import follow_fee_cancellation
    import follow_run_coordinator
    import follow_run_fee_cap_grant

    run_id = "a" * 64
    config_digest = "b" * 64
    policy = SimpleNamespace(
        digest="c" * 64,
        maximum_fee_mojos_per_tx=50,
        network="mainnet",
        asset_id="d" * 64,
        wallet_fingerprint="7",
    )
    identity = {
        "network": "mainnet",
        "wallet_fingerprint": 7,
        "asset_id": "d" * 64,
    }
    state = {
        "state": "running",
        "run_id": run_id,
        "policy_digest": policy.digest,
        "configuration_sha256": config_digest,
    }
    monkeypatch.setattr(
        follow_run_coordinator.FollowRunCoordinator,
        "read_state",
        lambda _self: state,
    )
    monkeypatch.setattr(database, "get_active_follow_run_policy", lambda: policy)
    monkeypatch.setattr(
        confidence_override, "current_configuration_digest", lambda: config_digest
    )
    monkeypatch.setattr(
        confidence_override,
        "current_scope",
        lambda: {
            "follow_run_id": run_id,
            "configuration_sha256": config_digest,
            "identity": identity,
        },
    )
    monkeypatch.setattr(
        follow_run_fee_cap_grant,
        "get_follow_run_fee_cap_grant",
        lambda *, run_id, now_epoch: {
            "run_id": run_id,
            "maximum_fee_mojos_per_tx": 90,
        },
    )
    assert (
        follow_fee_cancellation._verified_active_transaction_fee_cap(
            run_id=run_id, identity=identity, now_epoch=100
        )
        == 90
    )
