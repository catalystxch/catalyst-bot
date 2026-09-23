"""Read-only estimates distinguish projected fees from retained fee principal."""

import json

import pytest

import coin_prep_fee_approval as service
import database
import fee_estimation
import tx_fees


@pytest.fixture
def context(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "preview-service.db"))
    database.init_database()
    monkeypatch.setattr(service, "_now", lambda: 100, raising=False)
    monkeypatch.setattr(fee_estimation.time, "time", lambda: 100)

    def provider(*, cost, target_seconds):
        fees = {20_000_000: 30, 10_000_000: 10, 5_000_000: 5}
        return {
            "available": True, "source": "coinset", "observed_at": 99,
            "raw": {"success": True, "cost": cost, "target_times": [target_seconds],
                    "estimates": [fees[cost]]},
        }
    monkeypatch.setattr(tx_fees, "get_suggested_transaction_fee", provider)
    scope = {
        "network": "mainnet", "wallet_type": "sage", "wallet_fingerprint": 736588221,
        "wallet_id": 2, "xch_wallet_id": 1, "asset_id": "b8" * 32, "ticker": "MZ_XCH",
        "session_id": "d" * 64, "campaign_id": None,
    }
    plan = {
        "target_seconds": 300, "coin_multiplier": "1", "headroom_pct": "0",
        "liquidity_mode": "two_sided", "reserve_floors_mojos": {"xch": 0, "cat": 0},
        "campaign_revision": None, "cancellation_policy": "protected_no_prep",
        "outputs": [{"asset": "xch", "purpose": "fee_reserve", "tier_rank": 0,
                     "amount_mojos": 1_000, "ordinal": 0}],
    }
    stages = [
        {"stage_id": "cat-final", "cost": 20_000_000, "cost_kind": "projected",
         "transaction_count_min": 1, "transaction_count_max": 2, "cancellation": False},
        {"stage_id": "xch-final", "cost": 10_000_000, "cost_kind": "exact_unsigned",
         "transaction_count_min": 1, "transaction_count_max": 1, "cancellation": False},
        {"stage_id": "safe-cancel", "cost": 5_000_000, "cost_kind": "projected",
         "transaction_count_min": 1, "transaction_count_max": 2, "cancellation": True},
    ]
    yield scope, plan, stages
    database.close_connection()


def _preview(context, funding=100):
    assert callable(getattr(service, "estimate_coin_prep_fee_preview", None)), (
        "cost-specific read-only fee preview is missing"
    )
    scope, plan, stages = context
    return service.estimate_coin_prep_fee_preview(
        scope=scope, economic_plan=plan, stages=stages,
        fee_funding_mojos=funding, request_options={"coin_multiplier": "1"},
    )


def test_optional_projected_stage_exposes_zero_lower_count_but_retains_full_upper_budget(context):
    context[2][0]["transaction_count_min"] = 0
    result = _preview(context)
    assert result["available"] is True
    assert result["preparation_transaction_count_min"] == 1
    assert result["preparation_transaction_count_max"] == 3
    assert result["estimated_minimum_fee_mojos"] == 15
    assert result["estimated_total_fee_mojos"] == 80


def test_projected_upper_count_prices_total_without_charging_fee_principal(context):
    result = _preview(context)
    assert result["available"] is True
    assert result["estimated_preparation_fee_mojos"] == 70
    assert result["estimated_cancellation_fee_mojos"] == 10
    assert result["estimated_total_fee_mojos"] == 80
    assert result["estimated_minimum_fee_mojos"] == 45
    assert result["fee_coin_principal_mojos"] == 1_000
    assert result["suggested_maximum_fee_mojos"] == 80
    assert result["target_seconds"] == 300
    assert result["preparation_transaction_count_min"] == 2
    assert result["preparation_transaction_count_max"] == 3
    assert result["stages"][0]["cost_kind"] == "projected"
    assert result["stages"][1]["cost_kind"] == "exact_unsigned"


@pytest.mark.parametrize("prep_held,cancel_held,want_cap,want_funding", [
    (0, 0, 110, 110), (30, 0, 140, 110),
    (0, 50, 130, 80), (30, 50, 160, 80),
])
def test_renewal_preserves_protection_and_prices_a_cumulative_ceiling(
    context, prep_held, cancel_held, want_cap, want_funding
):
    # Earlier cancellation guidance was 40; it has now fallen to 10. Existing
    # cancellation commitments consume the total, not the non-cancellation cap.
    context[2][2]["transaction_count_max"] = 8
    first = _preview(context, funding=1000)
    approval = database.approve_coin_prep_fee_preview(
        preview_id=first["preview_id"], scope_sha256=first["scope_sha256"],
        plan_sha256=first["plan_sha256"], maximum_fee_mojos=200,
        cancellation_reserve_mojos=40, now=100,
    )
    for index, fee, cancellation in ((1, prep_held, False), (2, cancel_held, True)):
        if fee:
            database.reserve_approved_fee(
                approval_id=approval["approval_id"], scope_sha256=first["scope_sha256"],
                plan_sha256=first["plan_sha256"], operation_id=str(index) * 64,
                fee_mojos=fee, cancellation=cancellation,
            )
    context[2][2]["transaction_count_max"] = 2
    result = _preview(context, funding=want_funding)
    assert result["estimated_total_fee_mojos"] == 80
    assert result["estimated_cancellation_fee_mojos"] == 10
    assert result["suggested_maximum_fee_mojos"] == want_cap
    assert result["minimum_cumulative_fee_mojos"] == want_cap
    assert result["minimum_cancellation_reserve_mojos"] == 40
    assert result["fee_accounting"]["held_fee_mojos"] == prep_held + cancel_held
    assert result["fee_accounting"]["spent_fee_mojos"] == 0
    assert result["funded"] is True
    assert _preview(context, funding=want_funding - 1)["funded"] is False
    renewed = database.approve_coin_prep_fee_preview(
        preview_id=result["preview_id"], scope_sha256=result["scope_sha256"],
        plan_sha256=result["plan_sha256"],
        maximum_fee_mojos=result["suggested_maximum_fee_mojos"],
        cancellation_reserve_mojos=result["minimum_cancellation_reserve_mojos"], now=100,
    )
    assert renewed["version"] == 2
    assert renewed["remaining_fee_mojos"] == want_funding


def test_other_wallet_scope_does_not_inflate_renewal_disclosure(context):
    database.create_fee_approval(
        scope_sha256="f" * 64, plan_sha256="e" * 64,
        total_fee_mojos=1000, cancellation_reserve_mojos=900,
    )
    result = _preview(context)
    assert result["minimum_cancellation_reserve_mojos"] == 10
    assert result["suggested_maximum_fee_mojos"] == 80


def test_preview_does_not_create_effect_journal_consent_or_worker_state(context):
    result = _preview(context)
    conn = database.get_connection()
    for table in ["coin_prep_operations", "wallet_effect_claims", "fee_approvals",
                  "approved_fee_reservations", "coin_prep_fee_consents"]:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    saved = database.get_coin_prep_fee_preview(result["preview_id"])
    assert json.loads(saved["quote_json"])["estimated_total_fee_mojos"] == 80


def test_preview_freshness_preserves_oldest_provider_observation(context):
    result = _preview(context)
    assert result["observed_at"] == 99
    assert result["expires_at"] == 159
    assert result["stages"][0]["quote"]["observed_at"] == 99


@pytest.mark.parametrize("evidence", [
    {"full_node_synced": None, "mempool_size": None, "mempool_fees": None, "last_block_cost": None},
    {"full_node_synced": True, "mempool_size": 0, "mempool_fees": 9007199254740993,
     "last_block_cost": 20000000},
])
def test_preview_retains_exact_network_diagnostics_without_inventing_health(context, monkeypatch, evidence):
    original = tx_fees.get_suggested_transaction_fee
    def provider(**kwargs):
        response = original(**kwargs)
        response["raw"].update({key: value for key, value in evidence.items() if value is not None})
        return response
    monkeypatch.setattr(tx_fees, "get_suggested_transaction_fee", provider)
    result = _preview(context)
    want = {key: str(value) if type(value) is int else value for key, value in evidence.items()}
    assert result["available"] is True
    assert all(stage["quote"]["network_evidence"] == want for stage in result["stages"])
    saved = json.loads(database.get_coin_prep_fee_preview(result["preview_id"])["quote_json"])
    assert saved["stages"][0]["quote"]["network_evidence"] == want


@pytest.mark.parametrize("provider_response", [
    {"available": False, "source": "coinset", "observed_at": 99},
    {"available": True, "source": "coinset", "observed_at": 39,
     "raw": {"success": True, "estimates": [30]}},
    {"available": True, "source": "coinset", "observed_at": 99,
     "raw": {"success": True, "estimates": []}},
])
def test_outage_stale_and_missing_quotes_produce_unconfirmable_preview(
    context, monkeypatch, provider_response
):
    monkeypatch.setattr(tx_fees, "get_suggested_transaction_fee", lambda **_: provider_response)
    result = _preview(context)
    assert result["available"] is False
    assert result["estimated_total_fee_mojos"] is None
    assert result["suggested_maximum_fee_mojos"] is None
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        database.approve_coin_prep_fee_preview(
            preview_id=result["preview_id"], scope_sha256=result["scope_sha256"],
            plan_sha256=result["plan_sha256"], maximum_fee_mojos=80,
            cancellation_reserve_mojos=10, now=100,
        )


def test_insufficient_fee_funding_is_visible_and_blocks_consent(context):
    result = _preview(context, funding=79)
    assert result["available"] is True
    assert result["funded"] is False
    with pytest.raises(ValueError, match="FEE_FUNDING_INSUFFICIENT"):
        database.approve_coin_prep_fee_preview(
            preview_id=result["preview_id"], scope_sha256=result["scope_sha256"],
            plan_sha256=result["plan_sha256"], maximum_fee_mojos=80,
            cancellation_reserve_mojos=10, now=100,
        )


@pytest.mark.parametrize("field,value", [
    ("cost", True), ("cost", 0), ("cost_kind", "unknown"),
    ("transaction_count_min", 3), ("transaction_count_max", 1.0),
    ("cancellation", 1),
])
def test_invalid_stage_cannot_be_misrepresented_as_exact_cost(context, field, value):
    context[2][0][field] = value
    with pytest.raises(ValueError):
        _preview(context)


def _matched_quote(**overrides):
    return {"available": True, "reason": "network_fee_estimate", "source": "full_node_rpc",
            "cost": 10_000_000, "target_seconds": 300, "fee_mojos": 7,
            "fee_xch": "0.000000000007", "observed_at": 95, "expires_at": 155,
            **overrides}


def _matched_preview(context, quote):
    scope, plan, stages = context
    try:
        return service.estimate_coin_prep_fee_preview(
            scope=scope, economic_plan=plan, stages=stages,
            fee_funding_mojos=100, request_options={"coin_multiplier": "1"},
            stage_quotes={"xch-final": quote},
        )
    except TypeError as exc:
        pytest.fail(f"preview cannot preserve the exact effect's matched quote: {exc}")


def test_exact_effect_quote_is_preserved_while_other_stages_get_fresh_guidance(context):
    # Requoting xch-final would silently change 7 to the fixture provider's 10.
    result = _matched_preview(context, _matched_quote())
    assert result["available"] is True
    assert result["estimated_preparation_fee_mojos"] == 67
    assert result["estimated_total_fee_mojos"] == 77
    assert result["estimated_minimum_fee_mojos"] == 42
    assert result["observed_at"] == 95
    assert result["expires_at"] == 155
    exact = result["stages"][1]["quote"]
    assert exact["fee_mojos"] == 7
    assert exact["source"] == "full_node_rpc"
    saved = database.get_coin_prep_fee_preview(result["preview_id"])
    assert json.loads(saved["quote_json"])["stages"][1]["quote"]["fee_mojos"] == 7


@pytest.mark.parametrize("overrides", [
    {"available": False}, {"cost": 5_000_000}, {"cost": True},
    {"target_seconds": 600}, {"fee_mojos": True}, {"fee_mojos": -1},
    {"fee_mojos": "7"}, {"source": "manual"}, {"observed_at": 40, "expires_at": 100},
    {"observed_at": 101, "expires_at": 161}, {"expires_at": 156},
    {"observed_at": True}, {"expires_at": None},
])
def test_invalid_matched_quote_cannot_be_replaced_by_a_different_confirmable_fee(context, overrides):
    result = _matched_preview(context, _matched_quote(**overrides))
    assert result["available"] is False
    assert result["funded"] is False
    assert result["estimated_total_fee_mojos"] is None
    assert result["suggested_maximum_fee_mojos"] is None
    assert result["stages"][1]["quote"].get("fee_mojos") is None
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        database.approve_coin_prep_fee_preview(
            preview_id=result["preview_id"], scope_sha256=result["scope_sha256"],
            plan_sha256=result["plan_sha256"], maximum_fee_mojos=80,
            cancellation_reserve_mojos=10, now=100,
        )


def test_matched_quote_expiring_during_later_stage_pricing_stays_unconfirmable(context, monkeypatch):
    original = tx_fees.get_suggested_transaction_fee

    def slow_provider(**args):
        result = original(**args)
        if args["cost"] == 5_000_000:
            monkeypatch.setattr(service, "_now", lambda: 155)
        return result

    monkeypatch.setattr(tx_fees, "get_suggested_transaction_fee", slow_provider)
    result = _matched_preview(context, _matched_quote())
    assert result["available"] is False
    assert result["estimated_total_fee_mojos"] is None
    assert result["stages"][1]["quote"]["observed_at"] == 95
    assert result["stages"][1]["quote"]["expires_at"] == 155
