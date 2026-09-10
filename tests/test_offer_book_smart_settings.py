from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from offer_book_policy import derive_offer_book_policy
from offer_manager import offer_is_profitable


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def test_market_risk_preset_is_typed_validated_and_api_updatable(monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("MARKET_RISK_PRESET", "aggressive")
    assert config_module.Config().MARKET_RISK_PRESET == "aggressive"

    monkeypatch.setenv("MARKET_RISK_PRESET", "not-a-preset")
    assert config_module.Config().MARKET_RISK_PRESET == "balanced"
    assert "MARKET_RISK_PRESET" in config_module.Config._UPDATABLE_KEYS


def test_offer_book_cost_controls_fail_config_validation_when_negative(monkeypatch):
    import config as config_module
    from config_validator import validate_config

    monkeypatch.setattr(config_module, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("MINIMUM_PROFIT_XCH", "-0.1")
    monkeypatch.setenv("EXPECTED_CANCEL_REQUOTES", "-1")
    monkeypatch.setenv("COMPETITION_COOLDOWN_SECS", "0")

    report = config_module.Config().validate()

    assert any("MINIMUM_PROFIT_XCH" in error for error in report["errors"])
    assert any("EXPECTED_CANCEL_REQUOTES" in error for error in report["errors"])
    assert any("COMPETITION_COOLDOWN_SECS" in error for error in report["errors"])
    structured = validate_config(config_module.Config())
    assert {
        "MINIMUM_PROFIT_XCH",
        "EXPECTED_CANCEL_REQUOTES",
        "COMPETITION_COOLDOWN_SECS",
    } <= {issue.key for issue in structured.errors}


def test_smart_settings_persists_selected_offer_book_risk_preset():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    backend = (root / "src" / "catalyst" / "blueprints" / "smart_defaults.py").read_text(
        encoding="utf-8"
    )
    html = (root / "bot_gui.html").read_text(encoding="utf-8")

    assert '"market_risk_preset": _risk_profile_name' in backend
    assert "market_risk_preset: getSelectedRiskProfile()" in html


@pytest.mark.parametrize(
    ("preset", "depth_multiple", "move_persistence", "churn_limit"),
    [
        ("conservative", "3", 3, 35),
        ("balanced", "2", 2, 50),
        ("aggressive", "1.5", 2, 65),
    ],
)
def test_presets_expose_noneditable_offer_book_thresholds(
    preset, depth_multiple, move_persistence, churn_limit
):
    policy = derive_offer_book_policy(
        risk_profile=preset,
        configured_offer_size_xch=Decimal("0.5"),
        independent_depth_xch=Decimal("2"),
        volatility_bps=Decimal("80"),
        churn_score=0,
        network_fee_xch=Decimal("0.00001"),
        expected_cancel_requotes=2,
        minimum_profit_xch=Decimal("0.0001"),
    )

    assert policy["market_model"] == "offer_book"
    assert policy["derived_thresholds"]["editable"] is False
    assert policy["derived_thresholds"]["depth_multiple"] == depth_multiple
    assert (
        policy["derived_thresholds"]["movement_persistence_refreshes"]
        == move_persistence
    )
    assert policy["derived_thresholds"]["churn_amber"] == churn_limit
    assert Decimal(policy["minimum_independent_depth_xch"]) == Decimal("0.5") * Decimal(
        depth_multiple
    )
    assert "tibet" not in str(policy).lower()
    assert "amm" not in str(policy).lower()
    assert "sniper" not in str(policy).lower()


def test_profit_floor_includes_network_cancel_requote_and_configured_profit():
    policy = derive_offer_book_policy(
        risk_profile="balanced",
        configured_offer_size_xch=Decimal("1"),
        independent_depth_xch=Decimal("4"),
        volatility_bps=Decimal("0"),
        churn_score=0,
        network_fee_xch=Decimal("0.00002"),
        expected_cancel_requotes=3,
        minimum_profit_xch=Decimal("0.0001"),
    )

    assert policy["profit_floor_xch"] == "0.00018"
    assert Decimal(policy["spread_floor_bps"]) >= Decimal("1.8")


def test_book_opportunity_is_small_bounded_and_requires_confirmed_depth():
    thin = derive_offer_book_policy(
        risk_profile="balanced",
        configured_offer_size_xch=Decimal("1"),
        independent_depth_xch=Decimal("1.5"),
        volatility_bps=Decimal("20"),
        churn_score=0,
        network_fee_xch=Decimal("0.00001"),
        expected_cancel_requotes=1,
        minimum_profit_xch=Decimal("0.0001"),
    )
    deep = derive_offer_book_policy(
        risk_profile="balanced",
        configured_offer_size_xch=Decimal("1"),
        independent_depth_xch=Decimal("10"),
        volatility_bps=Decimal("20"),
        churn_score=0,
        network_fee_xch=Decimal("0.00001"),
        expected_cancel_requotes=1,
        minimum_profit_xch=Decimal("0.0001"),
    )

    assert thin["opportunity_orders"]["enabled"] is False
    assert thin["independent_depth_sufficient"] is False
    assert deep["opportunity_orders"]["enabled"] is True
    assert deep["independent_depth_sufficient"] is True
    assert deep["independent_depth_xch"] == "10"
    assert deep["opportunity_orders"]["purpose"] == "book_opportunity"
    assert Decimal(deep["opportunity_orders"]["max_size_xch"]) <= Decimal("0.5")
    assert Decimal(deep["opportunity_orders"]["max_size_xch"]) <= Decimal("0.2")


def test_high_churn_widens_spread_and_disables_opportunity_orders():
    quiet = derive_offer_book_policy(
        risk_profile="balanced",
        configured_offer_size_xch=Decimal("1"),
        independent_depth_xch=Decimal("10"),
        volatility_bps=Decimal("20"),
        churn_score=0,
        network_fee_xch=Decimal("0.00001"),
        expected_cancel_requotes=1,
        minimum_profit_xch=Decimal("0.0001"),
    )
    churn = derive_offer_book_policy(
        risk_profile="balanced",
        configured_offer_size_xch=Decimal("1"),
        independent_depth_xch=Decimal("10"),
        volatility_bps=Decimal("20"),
        churn_score=55,
        network_fee_xch=Decimal("0.00001"),
        expected_cancel_requotes=1,
        minimum_profit_xch=Decimal("0.0001"),
    )

    assert Decimal(churn["recommended_spread_bps"]) > Decimal(
        quiet["recommended_spread_bps"]
    )
    assert churn["opportunity_orders"]["enabled"] is False


def test_offer_profitability_uses_full_cost_floor():
    assert offer_is_profitable(
        expected_gross_xch=Decimal("0.001"),
        network_fee_xch=Decimal("0.0001"),
        expected_cancel_requotes=2,
        minimum_profit_xch=Decimal("0.0005"),
    )
    assert not offer_is_profitable(
        expected_gross_xch=Decimal("0.00079"),
        network_fee_xch=Decimal("0.0001"),
        expected_cancel_requotes=2,
        minimum_profit_xch=Decimal("0.0005"),
    )
