from dataclasses import asdict
from decimal import Decimal

import pytest

from coin_prep_batch_plan import TargetOutput
from follow_funded_targets import (
    derive_refreshed_funded_limits,
    trim_follow_prep_recipe,
    validate_follow_prep_authority,
)
from coin_prep_economics import normalize_fee_prep_options
from follow_run_policy import FollowRunPolicy
from follow_principal import prove_follow_replacement_count_capacity


@pytest.fixture
def full_recipe():
    targets = (
        TargetOutput("xch", "replacement", 0, 1_000_000_000_000, 0),
        TargetOutput("xch", "replacement", 3, 2_000_000_000_000, 1),
        TargetOutput("xch", "fee_reserve", 4, 500_000_000, 2),
        TargetOutput("cat", "replacement", 0, 1_100, 0),
        TargetOutput("cat", "replacement", 3, 1_800, 1),
    )
    outputs = [asdict(target) for target in targets]
    return {
        "targets": targets,
        "worker_args": {
            "xch_target": 3,
            "cat_target": 2,
            "buy_tier_sizes": "inner=1,extreme=2,fees=0.0005",
            "cat_tier_sizes": "inner=1.1,extreme=1.8",
            "tier_counts_xch": "inner=1,extreme=1,fees=1",
            "tier_counts_cat": "inner=1,extreme=1",
            "prep_headroom_pct": "0",
        },
        "economic_plan": {
            "target_seconds": 300,
            "coin_multiplier": "1",
            "headroom_pct": "0",
            "liquidity_mode": "two_sided",
            "reserve_floors_mojos": {"xch": 1, "cat": 1},
            "campaign_revision": None,
            "cancellation_policy": "protected_no_prep",
            "outputs": outputs,
        },
        "multiplier_applied": False,
    }


def test_partial_prep_recipe_keeps_assigned_slots_and_fee_reserve(full_recipe):
    fit = {
        "buy_target": 2,
        "sell_target": 2,
        "funded_buy_limit": 1,
        "funded_sell_limit": 1,
        "slot_assignment_sha256": "a" * 64,
        "funded_output_assignments": [
            {
                "side": "buy",
                "slot": 0,
                "tier": "inner",
                "price_xch": "1",
                "output_ordinal": 0,
            },
            {
                "side": "sell",
                "slot": 0,
                "tier": "inner",
                "price_xch": "1",
                "output_ordinal": 0,
            },
        ],
    }
    configuration = {
        "CAT_DECIMALS": 3,
        "LIQUIDITY_MODE": "two_sided",
        "XCH_RESERVE": "0.000000000001",
        "CAT_RESERVE": "0.001",
    }

    result = trim_follow_prep_recipe(
        full_recipe,
        fit,
        configuration=configuration,
        buy_target=2,
        sell_target=2,
    )

    assert [(t.asset, t.purpose, t.ordinal) for t in result["targets"]] == [
        ("xch", "replacement", 0),
        ("xch", "fee_reserve", 1),
        ("cat", "replacement", 0),
    ]
    assert result["worker_args"]["xch_target"] == 2
    assert result["worker_args"]["cat_target"] == 1
    assert result["worker_args"]["tier_counts_xch"] == "inner=1,fees=1"
    assert result["worker_args"]["tier_counts_cat"] == "inner=1"
    assert result["funded_buy_limit"] == 1
    assert result["funded_sell_limit"] == 1


def test_partial_prep_recipe_rejects_missing_assignment(full_recipe):
    fit = {
        "buy_target": 2,
        "sell_target": 2,
        "funded_buy_limit": 1,
        "funded_sell_limit": 1,
        "slot_assignment_sha256": "a" * 64,
        "funded_output_assignments": [
            {
                "side": "buy",
                "slot": 0,
                "tier": "inner",
                "price_xch": "1",
                "output_ordinal": 99,
            },
            {
                "side": "sell",
                "slot": 0,
                "tier": "inner",
                "price_xch": "1",
                "output_ordinal": 0,
            },
        ],
    }
    configuration = {
        "CAT_DECIMALS": 3,
        "LIQUIDITY_MODE": "two_sided",
        "XCH_RESERVE": "0.000000000001",
        "CAT_RESERVE": "0.001",
    }

    with pytest.raises(ValueError, match="FOLLOW_FUNDED_TARGET_PROOF_INVALID"):
        trim_follow_prep_recipe(
            full_recipe,
            fit,
            configuration=configuration,
            buy_target=2,
            sell_target=2,
        )


def test_prep_options_accept_internal_follow_session_binding():
    session_id = "a" * 64
    assert normalize_fee_prep_options(
        {
            "coin_multiplier": "1",
            "target_seconds": 300,
            "follow_run_session_id": session_id,
        }
    ) == {
        "coin_multiplier": "1",
        "target_seconds": 300,
        "follow_run_session_id": session_id,
    }


def test_prep_options_reject_malformed_follow_session_binding():
    with pytest.raises(ValueError, match="FEE_PREP_OPTIONS_INVALID"):
        normalize_fee_prep_options(
            {
                "coin_multiplier": "1",
                "target_seconds": 300,
                "follow_run_session_id": "../x",
            }
        )


def _policy():
    return FollowRunPolicy(
        wallet_fingerprint="123",
        network="mainnet",
        asset_id="a" * 64,
        buy_target=100,
        sell_target=100,
        price_anchor=Decimal("1"),
        price_min=Decimal("0.9"),
        price_max=Decimal("1.1"),
        maximum_fee_mojos_per_tx=100,
        fee_coin_principal_mojos=500,
        xch_reserve_mojos=1_000,
        cat_reserve_atoms=2_000,
        maximum_trade_xch_mojos=10_000,
        maximum_trade_cat_atoms=20_000,
    )


def _prep_binding(policy):
    return {
        "session_id": "b" * 64,
        "run_id": None,
        "policy_digest": policy.digest,
        "configuration_sha256": "c" * 64,
        "state": "prep_pending",
        "unknown_effect": False,
        "fee_approval_id": None,
        "fee_approval_session_id": None,
    }


def test_follow_prep_authority_binds_active_policy_and_session():
    policy = _policy()
    assert (
        validate_follow_prep_authority(
            session_id="b" * 64,
            coordinator_state=_prep_binding(policy),
            policy=policy,
            configuration={"MAX_ACTIVE_BUY_OFFERS": 100, "MAX_ACTIVE_SELL_OFFERS": 100},
            configuration_sha256="c" * 64,
            identity={
                "network": "mainnet",
                "wallet_fingerprint": 123,
                "asset_id": "a" * 64,
            },
        )
        is True
    )


def test_follow_prep_authority_rejects_changed_identity():
    policy = _policy()
    with pytest.raises(ValueError, match="FOLLOW_RUN_AUTHORITY_CHANGED"):
        validate_follow_prep_authority(
            session_id="b" * 64,
            coordinator_state=_prep_binding(policy),
            policy=policy,
            configuration={"MAX_ACTIVE_BUY_OFFERS": 100, "MAX_ACTIVE_SELL_OFFERS": 100},
            configuration_sha256="c" * 64,
            identity={
                "network": "mainnet",
                "wallet_fingerprint": 456,
                "asset_id": "a" * 64,
            },
        )


def test_replacement_count_gate_can_report_partial_funded_limits():
    with pytest.raises(ValueError, match="FOLLOW_SLOT_INVENTORY_SHORT"):
        prove_follow_replacement_count_capacity(
            buy_limit=100,
            sell_limit=100,
            replacement_counts={"xch": 40, "cat": 30},
        )
    assert prove_follow_replacement_count_capacity(
        buy_limit=100,
        sell_limit=100,
        replacement_counts={"xch": 40, "cat": 30},
        allow_partial=True,
    ) == {
        "buy_limit": 100,
        "sell_limit": 100,
        "funded_buy_limit": 40,
        "funded_sell_limit": 30,
        "partial_target": True,
        "replacement_count_gate_passed": True,
    }


def test_refresh_limit_uses_active_book_plus_fresh_free_prefix():
    assert derive_refreshed_funded_limits(
        target_buy=100,
        target_sell=100,
        current_buy=40,
        current_sell=30,
        active_buy=39,
        active_sell=30,
        free_buy=2,
        free_sell=1,
    ) == (41, 31)


def test_refresh_limit_never_decreases_or_exceeds_approved_target():
    assert derive_refreshed_funded_limits(
        target_buy=100,
        target_sell=100,
        current_buy=40,
        current_sell=30,
        active_buy=20,
        active_sell=25,
        free_buy=2,
        free_sell=2,
    ) == (40, 30)
    with pytest.raises(ValueError, match="FOLLOW_FUNDED_TARGET_PROOF_INVALID"):
        derive_refreshed_funded_limits(
            target_buy=100,
            target_sell=100,
            current_buy=40,
            current_sell=30,
            active_buy=101,
            active_sell=25,
            free_buy=10,
            free_sell=10,
        )


def test_running_refresh_rejects_stale_session_before_wallet_reads(monkeypatch):
    import database
    from follow_funded_targets import refresh_running_follow_funded_limits
    from follow_run_coordinator import FollowRunCoordinator

    policy = _policy()
    monkeypatch.setattr(database, "get_active_follow_run_policy", lambda: policy)
    monkeypatch.setattr(
        FollowRunCoordinator,
        "get_state",
        lambda self: {
            "session_id": "b" * 64,
            "run_id": "e" * 64,
            "policy_digest": policy.digest,
            "configuration_sha256": "c" * 64,
            "state": "running",
            "unknown_effect": False,
            "fee_approval_id": "f" * 64,
        },
    )

    with pytest.raises(ValueError, match="FOLLOW_FUNDED_TARGET_AUTHORITY_CHANGED"):
        refresh_running_follow_funded_limits("d" * 64, offer_manager=object())


def _mock_refresh_environment(monkeypatch, *, free_rows_change=False):
    import database
    import confidence_override
    import coin_prep_fee_runtime
    import follow_funded_targets
    import follow_principal
    import follow_slot_fit
    from coin_prep_batch_plan import CoinSnapshot, SelectableCoin
    from follow_run_coordinator import FollowRunCoordinator

    policy = _policy()
    session_id, run_id, approval_id, prep_session_id = (
        "b" * 64,
        "e" * 64,
        "f" * 64,
        "d" * 64,
    )
    configuration = {
        "MAX_ACTIVE_BUY_OFFERS": 100,
        "MAX_ACTIVE_SELL_OFFERS": 100,
        "CAT_ASSET_ID": "a" * 64,
    }
    state = {
        "session_id": session_id,
        "run_id": run_id,
        "policy_digest": policy.digest,
        "configuration_sha256": "c" * 64,
        "state": "running",
        "unknown_effect": False,
        "fee_approval_id": approval_id,
        "fee_approval_session_id": prep_session_id,
        "funded_buy_limit": 1,
        "funded_sell_limit": 1,
    }
    snapshot = CoinSnapshot(
        (
            SelectableCoin("xch", "1" * 64, 1_000, "", True, False),
            SelectableCoin("cat", "2" * 64, 1_000, "", True, False),
        )
    )
    approved = {
        "request_options": {"follow_run_session_id": session_id},
        "identity": {
            "network": "mainnet",
            "wallet_type": "sage",
            "wallet_fingerprint": 123,
            "wallet_id": 2,
            "xch_wallet_id": 1,
            "asset_id": "a" * 64,
            "ticker": "MZ",
        },
        "scope": {"session_id": prep_session_id},
        "configuration": configuration,
        "snapshot": snapshot,
        "recipe": {"recipe_id": "frozen"},
    }
    row_map = {
        "xch": [
            {
                "coin_id": "1" * 64,
                "amount_mojos": 1_000,
                "assigned_tier": "inner",
                "designation": "tier_spare",
                "purpose": "replacement",
            }
        ],
        "cat": [
            {
                "coin_id": "2" * 64,
                "amount_mojos": 1_000,
                "assigned_tier": "inner",
                "designation": "tier_spare",
                "purpose": "replacement",
            }
        ],
    }
    free_calls = {"xch": 0, "cat": 0}

    def get_free_coins(asset):
        free_calls[asset] += 1
        if free_rows_change and asset == "xch" and free_calls[asset] > 1:
            return []
        return row_map[asset]

    monkeypatch.setattr(database, "get_active_follow_run_policy", lambda: policy)
    monkeypatch.setattr(
        database,
        "get_coin_prep_fee_approval_status",
        lambda _id: {
            "approval_id": approval_id,
            "stale": False,
            "session_completed": True,
            "unresolved_operation_count": 0,
            "unbounded": False,
            "total_fee_mojos": 500,
        },
    )
    monkeypatch.setattr(database, "get_free_coins", get_free_coins)
    monkeypatch.setattr(
        database,
        "get_active_offer_slot_keys",
        lambda *, asset_id, side: [f"ladder:{configuration['CAT_ASSET_ID']}:{side}:0"],
    )
    monkeypatch.setattr(
        FollowRunCoordinator,
        "get_state",
        lambda self: dict(state),
    )
    saved = {}

    def refresh(**kwargs):
        saved.update(kwargs)
        return {
            **state,
            "funded_buy_limit": kwargs["funded_buy_limit"],
            "funded_sell_limit": kwargs["funded_sell_limit"],
        }

    monkeypatch.setattr(
        FollowRunCoordinator,
        "refresh_funded_limits",
        lambda self, **kwargs: refresh(**kwargs),
    )
    monkeypatch.setattr(
        confidence_override, "current_configuration_digest", lambda: "c" * 64
    )
    monkeypatch.setattr(
        confidence_override, "current_scope", lambda: {"follow_run_id": run_id}
    )
    monkeypatch.setattr(coin_prep_fee_runtime, "_configuration", lambda: configuration)
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_approved_prep_fee_snapshot",
        lambda _id: approved,
    )
    monkeypatch.setattr(
        follow_principal,
        "_principal_from_observed_snapshot",
        lambda *_args, **_kwargs: {
            "maximum_trade_xch_mojos": policy.maximum_trade_xch_mojos,
            "maximum_trade_cat_atoms": policy.maximum_trade_cat_atoms,
            "principal_review_sha256": "8" * 64,
        },
    )
    monkeypatch.setattr(
        follow_slot_fit,
        "preview_current_follow_slot_fit",
        lambda **kwargs: {
            "funded_buy_limit": 1,
            "funded_sell_limit": 1,
            "slot_assignment_sha256": "9" * 64,
            "funded_output_assignments": [
                {"price_xch": "1"},
                {"price_xch": "1"},
            ],
        },
    )
    monkeypatch.setattr(
        database,
        "get_active_offer_slot_keys",
        lambda *, asset_id, side: [f"ladder:{configuration['CAT_ASSET_ID']}:{side}:0"],
    )
    monkeypatch.setattr(
        follow_funded_targets,
        "_unused_test_marker",
        None,
        raising=False,
    )

    class OfferManager:
        @staticmethod
        def get_replenishment_slots(side, total_slots, *, cat_asset_id):
            return [1]

    return policy, state, saved, OfferManager()


def test_running_refresh_raises_limits_from_stable_wallet_backed_proof(monkeypatch):
    from follow_funded_targets import refresh_running_follow_funded_limits

    policy, state, saved, offer_manager = _mock_refresh_environment(monkeypatch)

    result = refresh_running_follow_funded_limits(
        state["session_id"], offer_manager=offer_manager
    )

    assert result["funded_buy_limit"] == 2
    assert result["funded_sell_limit"] == 2
    assert saved["funded_buy_limit"] == 2
    assert saved["funded_sell_limit"] == 2
    assert saved["proof_sha256"]


def test_running_refresh_rejects_changed_free_inventory(monkeypatch):
    from follow_funded_targets import refresh_running_follow_funded_limits

    _policy_value, state, saved, offer_manager = _mock_refresh_environment(
        monkeypatch,
        free_rows_change=True,
    )

    with pytest.raises(ValueError, match="FOLLOW_FUNDED_TARGET_PROOF_CHANGED"):
        refresh_running_follow_funded_limits(
            state["session_id"], offer_manager=offer_manager
        )
    assert saved == {}


def test_plan_partial_follow_prep_caps_principal_and_keeps_full_target(monkeypatch):
    from follow_funded_targets import plan_partial_follow_prep_recipe
    import follow_slot_fit

    policy = _policy()
    full_recipe = {
        "targets": (),
        "worker_args": {},
        "economic_plan": {"target_seconds": 300},
    }
    captured = {}

    def fit(**kwargs):
        captured.update(kwargs)
        return {
            "buy_target": 100,
            "sell_target": 100,
            "funded_buy_limit": 40,
            "funded_sell_limit": 30,
            "funded_output_assignments": [],
            "slot_assignment_sha256": "d" * 64,
        }

    monkeypatch.setattr(follow_slot_fit, "preview_current_follow_slot_fit", fit)
    monkeypatch.setattr(
        "follow_funded_targets.trim_follow_prep_recipe",
        lambda recipe, fit, **kwargs: {
            "funded_buy_limit": fit["funded_buy_limit"],
            "funded_sell_limit": fit["funded_sell_limit"],
        },
    )
    result = plan_partial_follow_prep_recipe(
        full_recipe,
        configuration={
            "MAX_ACTIVE_BUY_OFFERS": 100,
            "MAX_ACTIVE_SELL_OFFERS": 100,
        },
        policy=policy,
        available_trade_xch_mojos=50_000,
        available_trade_cat_atoms=60_000,
    )

    assert captured["maximum_trade_xch_mojos"] == policy.maximum_trade_xch_mojos
    assert captured["maximum_trade_cat_atoms"] == policy.maximum_trade_cat_atoms
    assert captured["buy_limit"] == captured["sell_limit"] == 100
    assert result["funded_buy_limit"] == 40
    assert result["funded_sell_limit"] == 30
