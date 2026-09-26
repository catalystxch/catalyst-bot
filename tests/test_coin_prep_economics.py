"""Economic outputs must be derived from frozen settings, never client costs."""

from decimal import Decimal
from importlib import import_module

import pytest


def _service():
    try:
        return import_module("coin_prep_economics")
    except ModuleNotFoundError:
        pytest.fail("shared current Coin Prep economics are missing")


@pytest.fixture
def settings():
    result = {"TIER_ENABLED": True, "BUY_LADDER_REVERSED": False,
              "LIQUIDITY_MODE": "two_sided", "CAT_DECIMALS": 3,
              "SNIPER_ENABLED": False, "SNIPER_PREP_COUNT": 0,
              "SNIPER_SIZE_XCH": Decimal("0"),
              "COIN_PREP_HEADROOM_PCT": Decimal("10"), "SPREAD_BPS": Decimal("10000"),
              "MIN_EDGE_BPS": Decimal("0"), "XCH_RESERVE": Decimal("0.25"),
              "CAT_RESERVE": Decimal("1.001"), "MAX_ACTIVE_BUY_OFFERS": 3,
              "MAX_ACTIVE_SELL_OFFERS": 2, "DEFAULT_TRADE_XCH": Decimal("0.1")}
    for tier, amount in (("INNER", "1"), ("MID", "0.75"), ("OUTER", "0.5"), ("EXTREME", "0.1")):
        result[f"{tier}_SIZE_XCH"] = Decimal(amount)
        for side in ("BUY", "SELL"):
            result[f"{side}_{tier}_SIZE_XCH"] = Decimal(amount)
            result[f"{side}_{tier}_TIER_COUNT"] = 0
            result[f"{side}_{tier}_TIER_SPARE_COUNT"] = 0
    result.update(BUY_INNER_TIER_COUNT=2, BUY_INNER_TIER_SPARE_COUNT=1,
                  SELL_INNER_TIER_COUNT=1, SELL_OUTER_TIER_COUNT=1)
    return result


FEE_POOL = {"enabled": True, "count": 2, "coin_size_xch": "0.001"}


def _build(settings, **options):
    return _service().build_standard_prep_economics(
        configuration=settings, fee_pool=FEE_POOL, live_price="0.01", **options)


def test_asymmetric_live_counts_and_spares_use_actual_sell_ladder_prices(settings):
    result = _build(settings)
    assert [(o.asset, o.purpose, o.amount_mojos) for o in result["targets"]] == [
        ("xch", "replacement", 1_100_000_000_000)] * 3 + [
        ("xch", "fee_reserve", 1_000_000_000)] * 2 + [
        ("cat", "replacement", 110_000), ("cat", "replacement", 27_500)]
    plan = result["economic_plan"]
    assert plan["reserve_floors_mojos"] == {"xch": 250_000_000_000, "cat": 1001}
    assert plan["target_seconds"] == 300
    assert result["worker_args"]["prep_headroom_pct"] == "0"
    assert result["worker_args"]["cat_tier_sizes"] == "inner=110,outer=27.5"
    assert result["worker_args"]["xch_target"] == 5
    assert result["worker_args"]["cat_target"] == 2


def test_enabled_sniper_pool_is_part_of_fee_preview_and_worker_targets(settings):
    """The approved fee plan must cover every denomination the GUI verifies."""
    settings.update(
        SNIPER_ENABLED=True,
        SNIPER_PREP_COUNT=20,
        SNIPER_SIZE_XCH=Decimal("0.33"),
    )

    result = _build(settings)

    assert result["worker_args"]["xch_target"] == 25
    assert result["worker_args"]["cat_target"] == 22
    assert "sniper=0.363" in result["worker_args"]["buy_tier_sizes"]
    assert "sniper=36.3" in result["worker_args"]["cat_tier_sizes"]
    assert result["worker_args"]["tier_counts_xch"] == "inner=3,fees=2,sniper=20"
    assert result["worker_args"]["tier_counts_cat"] == "inner=1,outer=1,sniper=20"
    assert len([target for target in result["targets"] if target.asset == "xch"]) == 25
    assert len([target for target in result["targets"] if target.asset == "cat"]) == 22


@pytest.mark.parametrize("mode", ["buy_only", "sell_only"])
def test_one_sided_fee_plan_matches_ui_by_excluding_two_sided_sniper_pool(settings, mode):
    settings.update(
        LIQUIDITY_MODE=mode,
        SNIPER_ENABLED=True,
        SNIPER_PREP_COUNT=20,
        SNIPER_SIZE_XCH=Decimal("0.33"),
    )

    result = _build(settings)

    assert "sniper" not in result["worker_args"]["buy_tier_sizes"]
    assert "sniper" not in result["worker_args"]["cat_tier_sizes"]


def test_execution_worker_and_preview_share_the_hand_checked_economic_amounts(settings, monkeypatch):
    import coin_prep_worker

    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker.offer_tier_xch_sizes_sell = {"inner": Decimal("1"), "outer": Decimal("0.5")}
    worker.cat_tier_counts = {"inner": 1, "outer": 1}
    worker.cat_decimals = 3
    worker.coin_prep_headroom_multiplier = Decimal("1.1")
    worker.coin_prep_headroom_pct = Decimal("10")
    worker._get_live_price = lambda: Decimal("0.01")
    worker.log = lambda *_args, **_kwargs: None
    monkeypatch.setenv("SPREAD_BPS", "10000")
    monkeypatch.setenv("MIN_EDGE_BPS", "0")
    assert worker._derive_tier_cat_sizes() == {"inner": Decimal("110"), "outer": Decimal("27.5")}
    assert worker._apply_prep_headroom_xch(Decimal("1")) == Decimal("1.1")
    assert [o.amount_mojos for o in _build(settings)["targets"] if o.asset == "cat"] == [110_000, 27_500]


def test_worker_spare_output_counts_do_not_create_imaginary_live_sell_slots(monkeypatch):
    """Worker output counts include spares, but ladder pricing must not."""
    import coin_prep_worker

    worker = object.__new__(coin_prep_worker.CoinPrepWorker)
    worker.offer_tier_xch_sizes_sell = {
        "inner": Decimal("4.3055"),
        "mid": Decimal("3.588"),
        "outer": Decimal("2.6909"),
    }
    # One live coin plus one spare per tier is passed to the worker as the
    # total output quantity.  Those spare quantities are not live slots.
    worker.cat_tier_counts = {"inner": 2, "mid": 2, "outer": 2}
    worker.cat_live_tier_counts = {"inner": 1, "mid": 1, "outer": 1}
    worker.cat_decimals = 3
    worker.coin_prep_headroom_multiplier = Decimal("1.12")
    worker.coin_prep_headroom_pct = Decimal("12")
    worker._get_live_price = lambda: Decimal("0.000075")
    worker.log = lambda *_args, **_kwargs: None
    monkeypatch.setenv("SELL_INNER_TIER_COUNT", "1")
    monkeypatch.setenv("SELL_MID_TIER_COUNT", "1")
    monkeypatch.setenv("SELL_OUTER_TIER_COUNT", "1")
    monkeypatch.setenv("SELL_EXTREME_TIER_COUNT", "0")
    monkeypatch.setenv("MAX_ACTIVE_SELL_OFFERS", "3")
    monkeypatch.setenv("SPREAD_BPS", "850")
    monkeypatch.setenv("MIN_EDGE_BPS", "340")

    assert worker._derive_tier_cat_sizes() == {
        "inner": Decimal("62181.303"),
        "mid": Decimal("50571.78"),
        "outer": Decimal("37036.044"),
    }


@pytest.mark.parametrize("inner_spares,mid_spares", [(0, 0), (9, 0), (1, 2)])
def test_cat_spares_do_not_move_executable_live_ladder_prices(settings, inner_spares, mid_spares):
    """Spare output quantities must not create imaginary live pricing slots."""
    settings.update(
        COIN_PREP_HEADROOM_PCT=Decimal("0"), SPREAD_BPS=Decimal("1000"),
        MAX_ACTIVE_SELL_OFFERS=3, SELL_INNER_SIZE_XCH=Decimal("0.1"),
        SELL_MID_SIZE_XCH=Decimal("0.2"), SELL_INNER_TIER_COUNT=1,
        SELL_MID_TIER_COUNT=2, SELL_OUTER_TIER_COUNT=0,
        SELL_INNER_TIER_SPARE_COUNT=inner_spares, SELL_MID_TIER_SPARE_COUNT=mid_spares,
    )
    result = _service().build_standard_prep_economics(
        configuration=settings, fee_pool=FEE_POOL, live_price="0.000075")
    # Live slots are .000075, .00007875, .0000825 regardless of spares.
    # The first mid slot is the largest required mid coin: ceil(.2/.00007875).
    cat_outputs = [o.amount_mojos for o in result["targets"] if o.asset == "cat"]
    assert cat_outputs == [1_333_334] * (1 + inner_spares) + [2_539_683] * (2 + mid_spares)
    assert result["worker_args"]["cat_target"] == 3 + inner_spares + mid_spares
    assert result["worker_args"]["cat_tier_sizes"] == "inner=1333.334,mid=2539.683"


def test_reversed_modern_buy_positions_keep_counts_paired_with_their_sizes(settings):
    settings.update(BUY_LADDER_REVERSED=True, BUY_INNER_SIZE_XCH=Decimal("0.1"),
                    BUY_EXTREME_SIZE_XCH=Decimal("1"), BUY_EXTREME_TIER_COUNT=2)
    result = _build(settings)
    amounts = [o.amount_mojos for o in result["targets"] if o.asset == "xch" and o.purpose == "replacement"]
    assert amounts == [1_100_000_000_000] * 2 + [110_000_000_000] * 3


def test_reversed_legacy_sizes_do_not_get_flipped_twice(settings):
    settings["BUY_LADDER_REVERSED"] = True
    for tier in ("INNER", "MID", "OUTER", "EXTREME"):
        settings[f"BUY_{tier}_SIZE_XCH"] = Decimal("0")
    amounts = [o.amount_mojos for o in _build(settings)["targets"]
               if o.asset == "xch" and o.purpose == "replacement"]
    assert amounts == [110_000_000_000] * 3


@pytest.mark.parametrize("mode, xch_count, cat_count", [("buy_only", 5, 0), ("sell_only", 2, 2)])
def test_one_sided_operation_keeps_only_its_trade_coins_and_xch_fees(settings, mode, xch_count, cat_count):
    settings["LIQUIDITY_MODE"] = mode
    result = _build(settings)
    assert result["worker_args"]["xch_target"] == xch_count
    assert result["worker_args"]["cat_target"] == cat_count


def test_uniform_multiplier_is_decimal_and_fee_principal_is_not_headroom_inflated(settings):
    settings["TIER_ENABLED"] = False
    result = _build(settings, coin_multiplier="1.5")
    assert result["worker_args"]["xch_target"] == 9
    assert result["worker_args"]["cat_target"] == 7
    assert [o.amount_mojos for o in result["targets"] if o.asset == "cat"] == [11_000] * 7
    assert sum(o.amount_mojos for o in result["targets"] if o.purpose == "fee_reserve") == 2_000_000_000
    assert result["multiplier_applied"] is True


def test_tier_multiplier_is_visible_as_not_applied_without_changing_live_cohorts(settings):
    result = _build(settings, coin_multiplier="2")
    assert result["economic_plan"]["coin_multiplier"] == "2"
    assert result["worker_args"]["xch_target"] == 5
    assert result["multiplier_applied"] is False


@pytest.mark.parametrize("price", [None, "0", "-1", "NaN", True, 0.01])
def test_missing_or_untrusted_price_never_generates_placeholder_cat_outputs(settings, price):
    with pytest.raises(ValueError, match="FEE_PREP_PRICE_UNAVAILABLE"):
        _service().build_standard_prep_economics(configuration=settings, fee_pool=FEE_POOL, live_price=price)


def test_buy_only_does_not_require_a_cat_sizing_price(settings):
    settings["LIQUIDITY_MODE"] = "buy_only"
    result = _service().build_standard_prep_economics(configuration=settings, fee_pool=FEE_POOL, live_price=None)
    assert all(o.asset == "xch" for o in result["targets"])


@pytest.mark.parametrize("key,value", [("BUY_INNER_TIER_COUNT", True), ("BUY_INNER_TIER_SPARE_COUNT", -1),
                                      ("BUY_INNER_SIZE_XCH", "NaN"), ("COIN_PREP_HEADROOM_PCT", "101"),
                                      ("XCH_RESERVE", "-1"), ("CAT_DECIMALS", True),
                                      ("LIQUIDITY_MODE", "both"), ("TIER_ENABLED", "true")])
def test_malformed_configuration_cannot_define_approved_economics(settings, key, value):
    settings[key] = value
    with pytest.raises(ValueError):
        _build(settings)


@pytest.mark.parametrize("multiplier", [True, 1.5, "NaN", "0.4", "3.1"])
def test_invalid_multiplier_is_rejected_not_clamped(settings, multiplier):
    with pytest.raises(ValueError):
        _build(settings, coin_multiplier=multiplier)


def test_bootstrap_exact_cat_amounts_need_no_market_price_or_extra_headroom(settings):
    args = {"xch_target": 2, "cat_target": 1, "buy_tier_sizes": "inner=0.1,fees=0.001",
            "cat_tier_sizes": "inner=2.345", "tier_counts_xch": "inner=1,fees=1",
            "tier_counts_cat": "inner=1", "prep_headroom_pct": "0"}
    result = _service().build_exact_prep_economics(
        configuration=settings, worker_args=args, campaign_revision=4)
    assert [(o.asset, o.amount_mojos) for o in result["targets"]] == [
        ("xch", 100_000_000_000), ("xch", 1_000_000_000), ("cat", 2345)]
    assert result["economic_plan"]["campaign_revision"] == 4
    assert result["economic_plan"]["headroom_pct"] == "0"


def test_fresh_bootstrap_exact_economics_preserve_revision_zero(settings):
    args = {"xch_target": 1, "cat_target": 1, "buy_tier_sizes": "inner=0.1",
            "cat_tier_sizes": "inner=2.345", "tier_counts_xch": "inner=1",
            "tier_counts_cat": "inner=1", "prep_headroom_pct": "0"}
    result = _service().build_exact_prep_economics(configuration=settings, worker_args=args, campaign_revision=0)
    assert result["economic_plan"]["campaign_revision"] == 0


@pytest.mark.parametrize("field,value", [("cat_tier_sizes", "inner=2,inner=3"),
                                        ("tier_counts_cat", "inner=1.5"),
                                        ("cat_target", 2), ("prep_headroom_pct", "10")])
def test_bootstrap_exact_args_must_be_complete_consistent_and_unambiguous(settings, field, value):
    args = {"xch_target": 1, "cat_target": 1, "buy_tier_sizes": "inner=0.1",
            "cat_tier_sizes": "inner=2.345", "tier_counts_xch": "inner=1",
            "tier_counts_cat": "inner=1", "prep_headroom_pct": "0", field: value}
    with pytest.raises(ValueError):
        _service().build_exact_prep_economics(configuration=settings, worker_args=args, campaign_revision=4)
