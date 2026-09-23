"""Settings must display the full configured XCH transaction fee."""

from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
GUI = Path(__file__).resolve().parents[2] / "bot_gui.html"


def test_fee_status_hint_preserves_all_meaningful_xch_decimals(page):
    """A 10-decimal fee must not be rounded to the old 8-decimal display."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            document.getElementById('configTransactionFeeEnabled').checked = true;
            document.getElementById('configTransactionFeeXch').value = '0.0000130791';
            document.getElementById('configFeeCoinSizeXch').value = '0.001';
            document.getElementById('configFeePrepCount').value = '50';
            document.getElementById('configTierEnabled').checked = true;
            renderFeeStatusHint();
        }"""
    )

    expect(page.locator("#feeStatusHint")).to_contain_text("0.0000130791 XCH")


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("supports_auto_estimate", [False, True])
def test_manual_fee_toggle_does_not_describe_prep_as_manual_or_free(
    page, enabled, supports_auto_estimate
):
    """Manual fee controls cannot hide the independent prep approval boundary."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """({enabled, supportsAutoEstimate}) => {
            feeStatusCache = {environment: {supports_auto_estimate: supportsAutoEstimate}};
            document.getElementById('configTransactionFeeXch').value = '0.0000130791';
            const toggle = document.getElementById('configTransactionFeeEnabled');
            toggle.checked = enabled;
            toggle.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        {"enabled": enabled, "supportsAutoEstimate": supports_auto_estimate},
    )
    hint = page.locator("#feeStatusHint")
    expect(hint).to_contain_text(re.compile(r"Coin Prep.*fresh.*estimat", re.S))
    expect(hint).to_contain_text(re.compile(r"approved.*budget", re.S))
    expect(hint).to_contain_text(re.compile(r"protected cancellation", re.I))
    expect(hint).not_to_contain_text(re.compile(r"will be sent with zero fee|transactions will use"))
    if enabled:
        expect(hint).to_contain_text("0.0000130791 XCH")
    else:
        expect(hint).to_contain_text(re.compile(r"manual.*OFF", re.I))


@pytest.mark.parametrize("tiered", [False, True])
def test_configured_fee_pool_is_retained_principal_for_flat_and_tiered_prep(page, tiered):
    """Uniform prep also freezes fee outputs; they are not fees already spent."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """tiered => {
            document.getElementById('configTransactionFeeEnabled').checked = true;
            document.getElementById('configTransactionFeeXch').value = '0.0000130791';
            document.getElementById('configFeeCoinSizeXch').value = '0.001';
            document.getElementById('configFeePrepCount').value = '50';
            document.getElementById('configTierEnabled').checked = tiered;
            updateFeeSettingsUi();
        }""",
        tiered,
    )
    hint = page.locator("#feeStatusHint")
    expect(hint).to_contain_text(re.compile(r"50 x 0\.001(?:0*) XCH"))
    expect(hint).to_contain_text(re.compile(r"retained.*not.*spent", re.S | re.I))
    expect(hint).not_to_contain_text("only prepared during tiered")


@pytest.mark.parametrize("fee_enabled, want_coins, want_total", [(True, 56, 0.65), (False, 6, 0.6)])
def test_flat_prep_summary_accounts_for_fee_outputs(page, fee_enabled, want_coins, want_total):
    """The flat Settings preview must not omit fifty approved fee-reserve outputs."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    result = page.evaluate(
        """feeEnabled => {
            const plan = buildCoinPrepPlan({
                liquidityMode: 'two_sided', tradeSize: 0.1, maxBuy: 3, maxSell: 3,
                coinPrepMultiplier: 1, tierEnabled: false, midPrice: 0.0001,
                headroomPct: 0, feePoolEnabled: feeEnabled, feeCoinSize: 0.001, feeCount: 50
            });
            const xch = document.createElement('div');
            xch.innerHTML = buildCoinPrepSizeMarkup(plan, 'xch');
            const cat = document.createElement('div');
            cat.innerHTML = buildCoinPrepSizeMarkup(plan, 'cat');
            return {xchCount: plan.xchCoinsNeeded, catCount: plan.catCoinsNeeded,
                xchTotal: plan.totalXchForCoinPrep, xchText: xch.textContent,
                catText: cat.textContent};
        }""",
        fee_enabled,
    )
    assert result["xchCount"] == want_coins
    assert result["xchTotal"] == pytest.approx(want_total)
    assert result["catCount"] == 6
    assert "Fees" not in result["catText"]
    if fee_enabled:
        assert "Fees" in result["xchText"]
        assert re.search(r"50\s*[x×]\s*0\.001(?:0*)", result["xchText"])
    else:
        assert "Fees" not in result["xchText"]


@pytest.mark.parametrize(
    "mode,multiplier,want_xch,want_cat",
    [("two_sided", 0.5, 2, 2), ("two_sided", 1.5, 7, 7),
     ("buy_only", 1.5, 7, 0), ("sell_only", 1.5, 0, 7)],
)
def test_uniform_summary_uses_frozen_backend_multiplier_semantics(
    page, mode, multiplier, want_xch, want_cat
):
    """Floor((configured buy + sell) * multiplier), then omit inactive assets."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    result = page.evaluate(
        """({mode, multiplier}) => {
            const plan = buildCoinPrepPlan({
                liquidityMode: mode, tradeSize: 0.1, maxBuy: 3, maxSell: 2,
                coinPrepMultiplier: multiplier, tierEnabled: false, midPrice: 0.0001,
                headroomPct: 0, feePoolEnabled: false, feeCoinSize: 0.001, feeCount: 50
            });
            return {xchCount: plan.xchCoinsNeeded, catCount: plan.catCoinsNeeded};
        }""",
        {"mode": mode, "multiplier": multiplier},
    )
    assert result == {"xchCount": want_xch, "catCount": want_cat}


@pytest.mark.parametrize(
    "decimals,price,headroom,want_amount,want_text",
    [(3, 0.000075, 0, 1333.334, "1,333.334"),
     (3, 0.000075, 10, 1466.667, "1,466.667"),
     (3, 0.0001, 10, 1100, "1,100"),
     (0, 0.000075, 0, 1334, "1,334"),
     (6, 0.000075, 0, 1333.333334, "1,333.333334")],
)
def test_uniform_cat_preview_rounds_capacity_up_to_the_actual_mojo(
    page, decimals, price, headroom, want_amount, want_text
):
    """Rounding to whole CATs understates the real frozen denomination."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    result = page.evaluate(
        """({decimals, price, headroom}) => {
            currentCAT = {decimals};
            const plan = buildCoinPrepPlan({
                liquidityMode: 'two_sided', tradeSize: 0.1, maxBuy: 3, maxSell: 3,
                coinPrepMultiplier: 1, tierEnabled: false, midPrice: price,
                headroomPct: headroom, feePoolEnabled: false
            });
            return {amount: plan.preparedCatPerCoin, text: formatCoinPrepCat(plan.preparedCatPerCoin)};
        }""",
        {"decimals": decimals, "price": price, "headroom": headroom},
    )
    assert result["amount"] == want_amount
    assert result["text"] == want_text


def test_prep_xch_breakdown_does_not_hide_one_mojo_fee_coins(page):
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    assert page.evaluate("formatCoinPrepXch(0.000000000001)") == "0.000000000001"


@pytest.mark.parametrize("surface", ["settings", "preflight"])
def test_tiered_cat_sizes_match_actual_ladder_mojo_capacities(page, surface):
    """First two tier prices are .000075 and .00007875, with 10% headroom."""
    from coin_prep_economics import prepared_cat_sizes

    expected = {"inner": "1466.667", "mid": "2793.651"}
    backend = prepared_cat_sizes(
        live_sizes={"inner": "0.1", "mid": "0.2"}, price="0.000075",
        headroom_multiplier="1.1", cat_decimals=3,
        sell_counts={"inner": 1, "mid": 2}, max_offers=3,
        spread_bps="1000", min_edge_bps="0",
    )
    assert {key: str(value) for key, value in backend.items()} == expected
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    result = page.evaluate(
        """async surface => {
            currentCAT = {decimals: 3};
            bot_state = {pricing: {mid: 0.000075}, balances: {}};
            document.getElementById('configMinEdgeBps').value = '0';
            if (surface === 'settings') {
                const plan = buildCoinPrepPlan({
                    liquidityMode: 'two_sided', tradeSize: 0.1, maxBuy: 3, maxSell: 3,
                    coinPrepMultiplier: 1, tierEnabled: true, midPrice: 0.000075,
                    headroomPct: 10, spreadBps: 1000, minEdgeBps: 0,
                    innerSize: 0.1, midSize: 0.2, outerSize: 0.1, extremeSize: 0.1,
                    tierCountInner: 1, tierCountMid: 2, tierCountOuter: 0, tierCountExtreme: 0,
                    feePoolEnabled: false
                });
                return {inner: String(plan.preparedTierSizesCat.inner), mid: String(plan.preparedTierSizesCat.mid)};
            }
            let query;
            apiFetch = async url => {
                if (String(url).includes('/coin-prep/verify?')) query = new URL(String(url), 'http://example.test').searchParams;
                return {json: async () => ({success: true, all_sufficient: true, balance_sufficient: true})};
            };
            await checkIfCoinPrepNeeded({tier_enabled: true, liquidity_mode: 'two_sided',
                max_active_buy: 3, max_active_sell: 3, coin_prep_headroom_pct: 10,
                coin_prep_multiplier: 1, spread_bps: 1000, min_edge_bps: 0,
                inner_size_xch: '0.1', mid_size_xch: '0.2',
                inner_tier_count: 1, mid_tier_count: 2, transaction_fee_xch: '0',
                xch_reserve: 0, cat_reserve: 0, topup_pool_xch: 0, topup_pool_cat: 0});
            return {inner: query?.get('inner_cat'), mid: query?.get('mid_cat')};
        }""",
        surface,
    )
    assert result == expected


def test_uniform_preflight_uses_mojo_rounded_capacity(page):
    """Readiness must verify the same 1333.334 CAT denomination as preparation."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    result = page.evaluate(
        """async () => {
            currentCAT = {decimals: 3};
            bot_state = {pricing: {mid: 0.000075}, balances: {}};
            let query;
            apiFetch = async url => {
                if (String(url).includes('/coin-prep/verify?')) query = new URL(String(url), 'http://example.test').searchParams;
                return {json: async () => ({success: true, all_sufficient: true, balance_sufficient: true})};
            };
            await checkIfCoinPrepNeeded({tier_enabled: false, liquidity_mode: 'two_sided',
                default_trade_xch: '0.1', max_active_buy: 3, max_active_sell: 3,
                coin_prep_headroom_pct: 0, coin_prep_multiplier: 1});
            return query?.get('prepared_cat_size');
        }"""
    )
    assert result == "1333.334"


@pytest.mark.parametrize("spread,edge", [(0, 300), (1000, 0)])
def test_tier_preflight_respects_explicit_zero_price_settings(page, spread, edge):
    """Unsaved form values must not replace a configured zero spread or edge."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    amount = page.evaluate(
        """async ({spread, edge}) => {
            currentCAT = {decimals: 3};
            bot_state = {pricing: {mid: 0.000075}, balances: {}};
            document.getElementById('configSpreadBps').value = '25';
            document.getElementById('configMinEdgeBps').value = '10';
            let query;
            apiFetch = async url => {
                if (String(url).includes('/coin-prep/verify?')) query = new URL(String(url), 'http://example.test').searchParams;
                return {json: async () => ({success: true, all_sufficient: true, balance_sufficient: true})};
            };
            await checkIfCoinPrepNeeded({tier_enabled: true, liquidity_mode: 'two_sided',
                max_active_buy: 1, max_active_sell: 1, coin_prep_headroom_pct: 10,
                coin_prep_multiplier: 1, spread_bps: spread, min_edge_bps: edge,
                inner_size_xch: '0.1', inner_tier_count: 1});
            return query?.get('inner_cat');
        }""",
        {"spread": spread, "edge": edge},
    )
    # At one slot the price is the anchor in both cases: zero spread clamps
    # the nonzero inner edge, and zero inner edge is the one-slot distance.
    assert amount == "1466.667"


@pytest.mark.parametrize("surface", ["settings", "preflight"])
@pytest.mark.parametrize("tiered", [False, True])
def test_prep_headroom_does_not_add_binary_dust_before_exact_rounding(page, surface, tiered):
    """1 XCH / .01 XCH per CAT with 14% headroom is exactly 114 CAT."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    amount = page.evaluate(
        """async ({surface, tiered}) => {
            currentCAT = {decimals: 3};
            bot_state = {pricing: {mid: 0.01}, balances: {}};
            if (surface === 'settings') {
                const plan = buildCoinPrepPlan({liquidityMode: 'two_sided',
                    tradeSize: 1, maxBuy: 1, maxSell: 1, coinPrepMultiplier: 1,
                    tierEnabled: tiered, midPrice: 0.01, spreadBps: 0, minEdgeBps: 0,
                    headroomPct: 14, innerSize: 1, tierCountInner: 1, feePoolEnabled: false});
                return String(tiered ? plan.preparedTierSizesCat.inner : plan.preparedCatPerCoin);
            }
            let query;
            apiFetch = async url => {
                if (String(url).includes('/coin-prep/verify?')) query = new URL(String(url), 'http://example.test').searchParams;
                return {json: async () => ({success: true, all_sufficient: true, balance_sufficient: true})};
            };
            await checkIfCoinPrepNeeded({tier_enabled: tiered, liquidity_mode: 'two_sided',
                default_trade_xch: '1', max_active_buy: 1, max_active_sell: 1,
                coin_prep_headroom_pct: 14, coin_prep_multiplier: 1,
                spread_bps: 0, min_edge_bps: 0, inner_size_xch: '1', inner_tier_count: 1});
            return query?.get(tiered ? 'inner_cat' : 'prepared_cat_size');
        }""",
        {"surface": surface, "tiered": tiered},
    )
    assert amount == "114"


@pytest.mark.parametrize("spread,edge", [(0, 300), (1000, 0)])
def test_prep_confirmation_preserves_saved_zero_pricing(page, spread, edge):
    """The visible confirmation must not substitute unsaved form spread/edge."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """({spread, edge}) => {
            currentCAT = {decimals: 3, name: 'MZ'};
            bot_state = {pricing: {mid: 0.000075}, balances: {}};
            document.getElementById('configSpreadBps').value = '25';
            document.getElementById('configMinEdgeBps').value = '10';
            showCoinPrepConfirm({tier_enabled: true, liquidity_mode: 'two_sided',
                default_trade_xch: '0.1', max_active_buy: 1, max_active_sell: 1,
                coin_prep_headroom_pct: 10, coin_prep_multiplier: 1,
                spread_bps: spread, min_edge_bps: edge,
                inner_size_xch: '0.1', inner_tier_count: 1}, 'recommended', 'Review');
        }""",
        {"spread": spread, "edge": edge},
    )
    expect(page.locator("#coinPrepConfirmOverlay")).to_be_visible()
    expect(page.locator("#cpConfirmCatSize")).to_contain_text("1,466.667")


def test_uniform_prep_count_floors_decimal_product_without_binary_loss(page):
    """Fifty configured slots times .58 is exactly 29, not 28."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    result = page.evaluate(
        """() => {
            const plan = buildCoinPrepPlan({liquidityMode: 'two_sided',
                tradeSize: 0.1, maxBuy: 25, maxSell: 25, coinPrepMultiplier: 0.58,
                tierEnabled: false, midPrice: 0.01, headroomPct: 0, feePoolEnabled: false});
            return {xch: plan.xchCoinsNeeded, cat: plan.catCoinsNeeded};
        }"""
    )
    assert result == {"xch": 29, "cat": 29}


@pytest.mark.parametrize(
    "size,price,spread,edge,want",
    [(0.14, 0.01, 0, 0, 14), (0.0114, 0.01, 2000, 1400, 1),
     (0.0105, 0.01, 500, 1400, 1)],
)
def test_tier_capacity_does_not_add_a_mojo_at_exact_price_boundaries(
    page, size, price, spread, edge, want
):
    """Decimal-exact capacities must not inherit binary product/division dust."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    value = page.evaluate(
        """({size, price, spread, edge}) => {
            currentCAT = {decimals: 3};
            return buildCoinPrepPlan({liquidityMode: 'two_sided', tradeSize: size,
                maxBuy: 1, maxSell: 1, coinPrepMultiplier: 1, tierEnabled: true,
                midPrice: price, spreadBps: spread, minEdgeBps: edge, headroomPct: 0,
                innerSize: size, tierCountInner: 1, feePoolEnabled: false
            }).preparedTierSizesCat.inner;
        }""",
        {"size": size, "price": price, "spread": spread, "edge": edge},
    )
    assert value == want
