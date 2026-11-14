"""Bootstrap Coin Prep keeps exact campaign authority through fee dispatch."""

from importlib import import_module
from decimal import Decimal
import time
from types import SimpleNamespace

import pytest

import api_server  # noqa: F401 - establishes blueprint import order
import fee_approval_test_utils as utils
from fee_staged_preview_utils import prepare_unsigned_wallet


@pytest.fixture
def approved_bootstrap(tmp_path, monkeypatch):
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    service = import_module("coin_prep_fee_approval")
    pricing = import_module("coin_prep_fee_pricing")
    coin_prep = import_module("blueprints.coin_prep")

    wallet_reads = utils.live_reads(tmp_path, monkeypatch)
    state = next(wallet_reads)
    utils.economic_reads(state, monkeypatch)
    monkeypatch.setattr(runtime, "cfg", state["config"])
    state["now"] = 1000
    monkeypatch.setattr(service, "_now", lambda: state["now"])
    monkeypatch.setattr(pricing, "_now", lambda: state["now"])
    monkeypatch.setattr(
        database,
        "time",
        SimpleNamespace(
            time=lambda: state["now"],
            time_ns=time.time_ns,
            monotonic=time.monotonic,
            sleep=time.sleep,
        ),
    )
    campaign_id = database.create_bootstrap_campaign(
        {
            "network": "mainnet",
            "wallet_type": "sage",
            "wallet_fingerprint": 736588221,
            "wallet_id": 2,
            "asset_id": utils.ASSET,
            "anchor_price": "0.01",
            "minimum_price": "0.005",
            "maximum_price": "0.02",
            "xch_budget": "1",
            "cat_budget": "2000",
            "fee_budget_xch": "0.01",
            "subsidy_budget_xch": "0",
            "created_at": "2026-09-22T10:00:00Z",
            "expires_at": "2026-09-23T10:00:00Z",
        }
    )
    campaign = database.get_bootstrap_campaign(campaign_id)
    worker_args = {
        "xch_target": 2,
        "cat_target": 1,
        "buy_tier_sizes": "inner=0.1,fees=0.001",
        "cat_tier_sizes": "inner=9",
        "tier_counts_xch": "inner=1,fees=1",
        "tier_counts_cat": "inner=1",
        "prep_headroom_pct": "0",
    }

    def bootstrap_context(options):
        assert options == {
            "coin_multiplier": "1",
            "target_seconds": 300,
            "bootstrap_campaign_id": campaign_id,
            "bootstrap_campaign_revision": 0,
        }
        return {
            "campaign": database.get_bootstrap_campaign(campaign_id),
            "worker_args": worker_args,
            "xch_balance_mojos": 200_000_000_000,
            "cat_balance_mojos": 20_000,
            "cat_decimals": 3,
        }

    monkeypatch.setattr(
        coin_prep, "_active_bootstrap_coin_prep_context", bootstrap_context
    )

    def quote(cost, target_seconds):
        return {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 1000,
            "expires_at": 1060,
        }

    monkeypatch.setattr(service, "quote_fee", quote)
    monkeypatch.setattr(pricing, "quote_fee", quote)
    prepare_unsigned_wallet(state, monkeypatch)
    options = {
        "bootstrap_campaign_id": campaign_id,
        "bootstrap_campaign_revision": 0,
    }
    preview = service.preview_coin_prep_fees(options)
    assert preview["available"] is True, preview
    approval = service.approve_coin_prep_fees(
        preview_id=preview["preview_id"],
        maximum_fee_mojos=preview["suggested_maximum_fee_mojos"],
        cancellation_reserve_mojos=preview["estimated_cancellation_fee_mojos"],
    )
    state.update(
        campaign_id=campaign_id,
        campaign=campaign,
        worker_args=worker_args,
        preview=preview,
        approval=approval,
    )
    yield state
    try:
        next(wallet_reads)
    except StopIteration:
        pass


def test_bootstrap_preview_consent_and_exact_pricing_share_campaign_revision(
    approved_bootstrap,
):
    runtime = import_module("coin_prep_fee_runtime")
    dispatch = import_module("coin_prep_fee_dispatch")
    state = approved_bootstrap

    frozen = runtime.read_approved_prep_fee_snapshot(state["approval"]["approval_id"])
    priced = dispatch.price_approved_prep_batch(state["approval"]["approval_id"])

    assert frozen["scope"]["session_id"] is None
    assert frozen["scope"]["campaign_id"] == state["campaign_id"]
    assert frozen["campaign"]["revision"] == 0
    assert frozen["recipe"]["worker_args"] == state["worker_args"]
    assert frozen["recipe"]["economic_plan"]["campaign_revision"] == 0
    assert priced["available"] is True
    assert priced["scope"]["campaign_id"] == state["campaign_id"]
    assert priced["pricing"]["plan"].fee_mojos == 20


def test_bootstrap_campaign_resolves_its_latest_explicit_fee_approval(
    approved_bootstrap,
):
    database = import_module("database")

    approval_id = database.get_latest_coin_prep_fee_approval_for_campaign(
        approved_bootstrap["campaign_id"]
    )

    assert approval_id == approved_bootstrap["approval"]["approval_id"]


def test_ordinary_fee_consent_survives_evidence_only_state_update(
    approved_bootstrap,
):
    """A live evidence update must not strand the approved cancellation reserve."""
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    from bootstrap_fee_authority import cancellation_fee_readiness

    campaign = database.get_bootstrap_campaign(approved_bootstrap["campaign_id"])
    state_fields = (
        "stage",
        "deployment_fraction",
        "current_anchor_price",
        "stable_since",
        "confirmed_fills",
        "settlement_clusters",
        "independent_depth_sides",
        "suspected_linked_activity",
        "adverse_fill_times",
        "fee_spent_xch",
        "realized_loss_xch",
        "marked_inventory_loss_xch",
        "updated_at",
    )
    state = {key: campaign[key] for key in state_fields}
    state["independent_depth_sides"] = ["buy"]
    revision = database.update_bootstrap_campaign_state(
        campaign["campaign_id"],
        expected_revision=0,
        record=state,
    )
    assert revision == 0
    assert (
        database.get_bootstrap_campaign(campaign["campaign_id"])["state_revision"] == 1
    )

    runtime.read_approved_prep_fee_snapshot(
        approved_bootstrap["approval"]["approval_id"]
    )
    context = runtime.read_approved_prep_fee_snapshot(
        approved_bootstrap["approval"]["approval_id"],
        allow_policy_only_revision=True,
    )
    assert context["campaign"]["revision"] == 0
    assert cancellation_fee_readiness(
        database.get_bootstrap_campaign(campaign["campaign_id"])
    ) == {
        "ready": True,
        "approval_id": approved_bootstrap["approval"]["approval_id"],
    }


def test_historical_evidence_revision_still_allows_protected_consent(
    approved_bootstrap,
):
    """Campaigns written by older builds may already have policy-only revisions."""
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    campaign_id = approved_bootstrap["campaign_id"]
    database.get_connection().execute(
        "UPDATE bootstrap_campaigns SET revision=revision+1 WHERE campaign_id=?",
        (campaign_id,),
    )

    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        runtime.read_approved_prep_fee_snapshot(
            approved_bootstrap["approval"]["approval_id"]
        )
    context = runtime.read_approved_prep_fee_snapshot(
        approved_bootstrap["approval"]["approval_id"],
        allow_policy_only_revision=True,
    )
    assert context["campaign"]["revision"] == 1


def test_ordinary_fee_consent_rejects_changed_immutable_campaign_budget(
    approved_bootstrap, monkeypatch
):
    """A matching campaign ID cannot authorize a changed principal budget."""
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    original = database.get_bootstrap_campaign(approved_bootstrap["campaign_id"])
    monkeypatch.setattr(
        database,
        "get_bootstrap_campaign",
        lambda _campaign_id: {**original, "xch_budget": "2"},
    )

    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        runtime.read_approved_prep_fee_snapshot(
            approved_bootstrap["approval"]["approval_id"],
            allow_policy_only_revision=True,
        )


def test_cancellation_pricing_keeps_protected_consent_after_policy_revision(
    approved_bootstrap, monkeypatch
):
    """Policy evidence alone must not strand an exact unsigned cancellation."""
    database = import_module("database")
    service = import_module("coin_prep_fee_cancellation")
    wallet = import_module("wallet")
    campaign = database.get_bootstrap_campaign(approved_bootstrap["campaign_id"])
    state_fields = (
        "stage",
        "deployment_fraction",
        "current_anchor_price",
        "stable_since",
        "confirmed_fills",
        "settlement_clusters",
        "independent_depth_sides",
        "suspected_linked_activity",
        "adverse_fill_times",
        "fee_spent_xch",
        "realized_loss_xch",
        "marked_inventory_loss_xch",
        "updated_at",
    )
    state = {key: campaign[key] for key in state_fields}
    state["independent_depth_sides"] = ["buy"]
    database.update_bootstrap_campaign_state(
        campaign["campaign_id"],
        expected_revision=0,
        record=state,
    )
    monkeypatch.setattr(
        wallet,
        "build_cancel_offers_batch_unsigned",
        lambda *_args, **_kwargs: {
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": 123_456,
        },
    )
    monkeypatch.setattr(
        service,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": approved_bootstrap["now"],
            "expires_at": approved_bootstrap["now"] + 60,
        },
    )

    result = service.price_approved_cancellation(
        approval_id=approved_bootstrap["approval"]["approval_id"],
        trade_ids=["a" * 64],
        source_coin_ids=["b" * 64],
        fee_coin_id="c" * 64,
    )

    assert result["available"] is True
    assert result["fee_mojos"] == 20
    assert result["campaign"]["revision"] == 0
    assert result["dispatch_authorized"] is False


def test_policy_revision_allowance_does_not_revive_stopped_campaign(
    approved_bootstrap,
):
    """A policy stop requires a new action-bound recovery approval."""
    database = import_module("database")
    runtime = import_module("coin_prep_fee_runtime")
    campaign = database.get_bootstrap_campaign(approved_bootstrap["campaign_id"])
    state_fields = (
        "stage",
        "deployment_fraction",
        "current_anchor_price",
        "stable_since",
        "confirmed_fills",
        "settlement_clusters",
        "independent_depth_sides",
        "suspected_linked_activity",
        "adverse_fill_times",
        "fee_spent_xch",
        "realized_loss_xch",
        "marked_inventory_loss_xch",
        "updated_at",
    )
    state = {key: campaign[key] for key in state_fields}
    state.update(stage="stopped", deployment_fraction="0")
    database.update_bootstrap_campaign_state(
        campaign["campaign_id"], expected_revision=0, record=state
    )

    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        runtime.read_approved_prep_fee_snapshot(
            approved_bootstrap["approval"]["approval_id"],
            allow_policy_only_revision=True,
        )


def test_campaign_renewal_discloses_journal_fees_missing_from_approval_ledger(
    approved_bootstrap, monkeypatch
):
    database = import_module("database")
    service = import_module("coin_prep_fee_approval")
    state = approved_bootstrap
    external_spend = 1_736_563_369
    monkeypatch.setattr(
        database,
        "_bootstrap_campaign_authoritative_fee_spent_mojos",
        lambda _conn, campaign_id, **_context: (
            external_spend if campaign_id == state["campaign_id"] else 0
        ),
    )

    accounting = database.get_fee_scope_budget(state["preview"]["scope_sha256"])
    renewed = service.preview_coin_prep_fees(
        {
            "bootstrap_campaign_id": state["campaign_id"],
            "bootstrap_campaign_revision": 0,
        }
    )

    assert accounting["spent_fee_mojos"] == external_spend
    assert accounting["committed_fee_mojos"] == external_spend
    assert accounting["noncancellation_committed_fee_mojos"] == 0
    assert renewed["fee_accounting"]["spent_fee_mojos"] == external_spend
    assert renewed["suggested_maximum_fee_mojos"] > external_spend


def test_bootstrap_cancellation_cannot_exceed_authoritative_campaign_fee_budget(
    approved_bootstrap, monkeypatch
):
    database = import_module("database")
    cancellation = import_module("coin_prep_fee_cancellation")
    wallet = import_module("wallet")
    state = approved_bootstrap
    campaign_budget_mojos = int(
        Decimal(state["campaign"]["fee_budget_xch"]) * Decimal(10**12)
    )
    monkeypatch.setattr(
        database,
        "_bootstrap_campaign_authoritative_fee_spent_mojos",
        lambda _conn, campaign_id, **_context: (
            campaign_budget_mojos if campaign_id == state["campaign_id"] else 0
        ),
    )
    monkeypatch.setattr(
        wallet,
        "build_cancel_offers_batch_unsigned",
        lambda trade_ids, *, fee_mojos, source_coin_ids, fee_coin_id: {
            "summary": {"fee": fee_mojos},
            "coin_spends": ["sealed"],
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": 123_456,
            "_catalyst_cancel_unsigned_digest": "f" * 64,
        },
    )
    monkeypatch.setattr(
        cancellation,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": state["now"],
            "expires_at": state["now"] + 60,
        },
    )

    result = cancellation.price_approved_cancellation(
        approval_id=state["approval"]["approval_id"],
        trade_ids=["a" * 64],
        source_coin_ids=["b" * 64],
        fee_coin_id="c" * 64,
    )

    assert result["available"] is False
    assert result["reason"] == "FEE_CAMPAIGN_BUDGET_EXCEEDED"
    assert result["required_fee_mojos"] == 20
    assert result["remaining_campaign_fee_mojos"] == 0


def test_explicit_renewed_ceiling_allows_only_the_displayed_campaign_recovery(
    approved_bootstrap, monkeypatch
):
    database = import_module("database")
    cancellation = import_module("coin_prep_fee_cancellation")
    service = import_module("coin_prep_fee_approval")
    wallet = import_module("wallet")
    state = approved_bootstrap
    original_budget = int(
        Decimal(state["campaign"]["fee_budget_xch"]) * Decimal(10**12)
    )
    external_spend = original_budget + 10
    monkeypatch.setattr(
        database,
        "_bootstrap_campaign_authoritative_fee_spent_mojos",
        lambda _conn, campaign_id, **_context: (
            external_spend if campaign_id == state["campaign_id"] else 0
        ),
    )
    assert database.stop_bootstrap_campaign(
        state["campaign_id"], "manual", "2026-09-22T12:01:00Z"
    )
    renewed_preview = service.preview_coin_prep_fees(
        {
            "bootstrap_campaign_id": state["campaign_id"],
            "bootstrap_campaign_revision": 1,
            "cancellation_recovery_action": "bootstrap_stop",
        }
    )
    renewed = service.approve_coin_prep_fees(
        preview_id=renewed_preview["preview_id"],
        maximum_fee_mojos=renewed_preview["suggested_maximum_fee_mojos"],
        cancellation_reserve_mojos=renewed_preview[
            "minimum_cancellation_reserve_mojos"
        ],
    )
    monkeypatch.setattr(
        wallet,
        "build_cancel_offers_batch_unsigned",
        lambda trade_ids, *, fee_mojos, source_coin_ids, fee_coin_id: {
            "summary": {"fee": fee_mojos},
            "coin_spends": ["sealed"],
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": 123_456,
            "_catalyst_cancel_unsigned_digest": "f" * 64,
        },
    )
    monkeypatch.setattr(
        cancellation,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": state["now"],
            "expires_at": state["now"] + 60,
        },
    )

    result = cancellation.price_approved_cancellation(
        approval_id=renewed["approval_id"],
        trade_ids=["a" * 64],
        source_coin_ids=["b" * 64],
        fee_coin_id="c" * 64,
        expected_recovery_action="bootstrap_stop",
    )

    assert renewed["version"] == 2
    assert renewed["total_fee_mojos"] > original_budget
    assert result["available"] is True
    assert result["fee_mojos"] == 20


def test_bootstrap_revision_change_invalidates_consent_before_dispatch(
    approved_bootstrap,
):
    database = import_module("database")
    dispatch = import_module("coin_prep_fee_dispatch")
    state = approved_bootstrap
    database.get_connection().execute(
        "UPDATE bootstrap_campaigns SET revision=revision+1 WHERE campaign_id=?",
        (state["campaign_id"],),
    )
    database.get_connection().commit()

    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        dispatch.price_approved_prep_batch(state["approval"]["approval_id"])
    assert state["builds"]
    assert utils._counts()["approved_fee_reservations"] == 0
