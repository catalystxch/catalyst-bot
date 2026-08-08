from decimal import Decimal, ROUND_HALF_UP

import pytest


def _sbx_counts():
    return {"inner": 20, "mid": 60, "outer": 60, "extreme": 60}


def _sbx_sizes():
    return {
        "inner": Decimal("2.5"),
        "mid": Decimal("5"),
        "outer": Decimal("7.5"),
        "extreme": Decimal("15"),
    }


def _price_for_slot(mid, spread_fraction, total_slots, slot):
    step = spread_fraction / Decimal(total_slots - 1)
    return mid * (Decimal("1") + step * Decimal(slot))


def test_sell_ladder_cat_summary_uses_generated_slot_prices_not_mid():
    from ladder_sizing import summarize_sell_ladder_cat

    mid = Decimal("0.000170")
    spread_fraction = (Decimal("0.000400") / mid) - Decimal("1")
    summary = summarize_sell_ladder_cat(
        mid_price=mid,
        spread_fraction=spread_fraction,
        max_offers=200,
        tier_counts=_sbx_counts(),
        tier_sizes_xch=_sbx_sizes(),
        min_edge_bps=Decimal("0"),
    )

    naive_mid_total = Decimal("1700") / mid
    expected_live_total = Decimal("0")
    slot = 0
    for tier, count in _sbx_counts().items():
        for _ in range(count):
            expected_live_total += _sbx_sizes()[tier] / _price_for_slot(
                mid, spread_fraction, 200, slot
            )
            slot += 1

    assert summary.live_cat_total == pytest.approx(expected_live_total)
    assert summary.live_cat_total < naive_mid_total * Decimal("0.57")
    assert summary.tier_live_cat["extreme"] < Decimal("15") * 60 / mid


def test_coin_prep_worker_derives_sell_cat_tier_sizes_from_ladder_prices(monkeypatch):
    import coin_prep_worker as cpw
    from amount_utils import round_cat_display_amount_up_to_mojo

    mid = Decimal("0.000170")
    spread_fraction = (Decimal("0.000400") / mid) - Decimal("1")
    worker = object.__new__(cpw.CoinPrepWorker)
    worker.offer_tier_xch_sizes_sell = _sbx_sizes()
    worker.offer_tier_xch_sizes = _sbx_sizes()
    worker.tier_xch_sizes = _sbx_sizes()
    worker.coin_prep_headroom_multiplier = Decimal("1.10")
    worker.coin_prep_headroom_pct = Decimal("10")
    worker.cat_decimals = 3
    worker._get_live_price = lambda: mid
    worker.log = lambda *_args, **_kwargs: None

    monkeypatch.setenv("MIN_EDGE_BPS", "0")
    monkeypatch.setenv("SPREAD_BPS", str(spread_fraction * Decimal("10000")))
    monkeypatch.setenv("MAX_ACTIVE_SELL_OFFERS", "200")
    monkeypatch.setenv("SELL_INNER_TIER_COUNT", "20")
    monkeypatch.setenv("SELL_MID_TIER_COUNT", "60")
    monkeypatch.setenv("SELL_OUTER_TIER_COUNT", "60")
    monkeypatch.setenv("SELL_EXTREME_TIER_COUNT", "60")

    result = worker._derive_tier_cat_sizes()

    expected_extreme_start_price = _price_for_slot(mid, spread_fraction, 200, 140)
    expected_extreme = round_cat_display_amount_up_to_mojo(
        (Decimal("15") / expected_extreme_start_price) * Decimal("1.10"),
        3,
    )

    assert result["extreme"] == expected_extreme
    assert result["extreme"] < round_cat_display_amount_up_to_mojo(
        (Decimal("15") / mid) * Decimal("1.10"),
        3,
    )


def test_coin_prep_worker_uses_cli_cat_tier_counts_for_ladder_prices(monkeypatch):
    import coin_prep_worker as cpw
    from amount_utils import round_cat_display_amount_up_to_mojo

    mid = Decimal("0.000170")
    spread_fraction = (Decimal("0.000400") / mid) - Decimal("1")
    worker = object.__new__(cpw.CoinPrepWorker)
    worker.offer_tier_xch_sizes_sell = _sbx_sizes()
    worker.offer_tier_xch_sizes = _sbx_sizes()
    worker.tier_xch_sizes = _sbx_sizes()
    worker.cat_tier_counts = _sbx_counts()
    worker.coin_prep_headroom_multiplier = Decimal("1.10")
    worker.coin_prep_headroom_pct = Decimal("10")
    worker.cat_decimals = 3
    worker._get_live_price = lambda: mid
    worker.log = lambda *_args, **_kwargs: None

    monkeypatch.setenv("MIN_EDGE_BPS", "0")
    monkeypatch.setenv("SPREAD_BPS", str(spread_fraction * Decimal("10000")))
    monkeypatch.setenv("MAX_ACTIVE_SELL_OFFERS", "1")
    monkeypatch.setenv("SELL_INNER_TIER_COUNT", "1")
    monkeypatch.setenv("SELL_MID_TIER_COUNT", "0")
    monkeypatch.setenv("SELL_OUTER_TIER_COUNT", "0")
    monkeypatch.setenv("SELL_EXTREME_TIER_COUNT", "0")

    result = worker._derive_tier_cat_sizes()

    expected_extreme_start_price = _price_for_slot(mid, spread_fraction, 200, 140)
    expected_extreme = round_cat_display_amount_up_to_mojo(
        (Decimal("15") / expected_extreme_start_price) * Decimal("1.10"),
        3,
    )

    assert result["extreme"] == expected_extreme


def test_smart_defaults_cat_prep_total_uses_generated_slot_prices():
    from ladder_sizing import prepared_sell_ladder_cat_total

    mid = Decimal("0.000170")
    spread_bps = ((Decimal("0.000400") / mid) - Decimal("1")) * Decimal("10000")

    actual = prepared_sell_ladder_cat_total(
        mid_price=mid,
        spread_bps=spread_bps,
        min_edge_bps=Decimal("0"),
        max_sell=200,
        tier_counts=_sbx_counts(),
        tier_spares={"inner": 0, "mid": 0, "outer": 0, "extreme": 0},
        tier_sizes_xch=_sbx_sizes(),
        headroom_mult=Decimal("1.10"),
    )
    old_mid_priced_total = sum(
        count * int(((_sbx_sizes()[tier] / mid) * Decimal("1.10")).to_integral_value())
        for tier, count in _sbx_counts().items()
    )
    expected = 0
    slot = 0
    for tier, count in _sbx_counts().items():
        max_cat = Decimal("0")
        for _ in range(count):
            max_cat = max(
                max_cat,
                _sbx_sizes()[tier]
                / _price_for_slot(mid, spread_bps / Decimal("10000"), 200, slot),
            )
            slot += 1
        expected += count * int(
            (max_cat * Decimal("1.10")).to_integral_value(rounding=ROUND_HALF_UP)
        )

    assert actual == expected
    assert actual < old_mid_priced_total * Decimal("0.65")


def test_frontend_coin_prep_uses_sell_ladder_slot_price_plan():
    with open("bot_gui.html", encoding="utf-8") as f:
        html = f.read()

    assert "function buildSellLadderCatPlan" in html
    assert "sellLadderCatPlan" in html
    assert "plan.sellLiveCatForOffers" in html
    assert "sellXch / midPrice" not in html


def test_smart_defaults_dbx_cap_runs_before_cat_budget_validation():
    with open("src/catalyst/blueprints/smart_defaults.py", encoding="utf-8") as f:
        source = f.read()

    assert source.index("DBX cap clamp") < source.index(
        "F65 FINAL SELL-SIDE CAT VERIFICATION"
    )
