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
