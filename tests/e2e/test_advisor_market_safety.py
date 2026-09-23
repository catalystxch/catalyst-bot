"""Advice must distinguish blocked exposure from a live ladder with no fills."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def load_advisor(page, *, competitors=0, base_bps=800, bootstrap=False):
    page.goto(
        (Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri(),
        wait_until="domcontentloaded",
    )
    page.evaluate(
        """({competitors, baseBps, bootstrap}) => {
            bot_state = {running: true, pricing: {mid: '0.000075'},
                         chia_health: {wallet_reachable: true}};
            _bootstrapActiveCampaign = bootstrap ? {anchor_price: '0.000075'} : null;
            window._lastDashboard = {
                settings: {
                    trading: {max_active_buy: 3, max_active_sell: 3},
                    spreads: {base_spread_bps: baseBps, min_spread_bps: 100,
                              max_spread_bps: 1500},
                    safety: {xch_reserve: 0, cat_reserve: 0},
                    inventory: {max_position_xch: 5},
                    features: {inventory_mgmt: true}
                },
                performance: {loop_count: 20, uptime_secs: 1800, total_fills: 0,
                              open_buys: 0, open_sells: 0, fill_rate_per_hour: 0},
                // Legacy health can be green even when authoritative confidence is RED.
                market_health: {status: 'green', metrics: {
                    effective_buy_target: 0, effective_sell_target: 0,
                    market_intel_state: 'ready', competitor_count: competitors,
                    market_spread_bps: competitors ? 600 : 0,
                    buy_spread_bps: baseBps / 2, sell_spread_bps: baseBps / 2,
                    arb_gap_bps: 0
                }},
                wallet: {xch_spendable: '1', cat_spendable: '10000'},
                coins: {xch_free: 6, cat_free: 6, xch_locked: 0, cat_locked: 0}
            };
        }""",
        {"competitors": competitors, "baseBps": base_bps, "bootstrap": bootstrap},
    )


@pytest.mark.parametrize("competitors,base_bps", [(0, 800), (38, 800), (0, 400)])
def test_red_zero_target_ladder_does_not_recommend_changing_spreads(
    page, competitors, base_bps
):
    """Zero targets caused by RED are not completed, executable trading exposure."""
    load_advisor(page, competitors=competitors, base_bps=base_bps)
    page.evaluate("""() => {
        renderMarketConfidence({confidence: {state: 'RED', data_valid: false,
            trusted_midpoint: null, reason_codes: ['insufficient_ask_depth']}});
        saUpdateAdvisor(window._lastDashboard);
    }""")
    expect(page.locator("#alertsBody")).not_to_contain_text("Tighten base")
    expect(page.locator("#alertsBody")).not_to_contain_text("Widen base")
    expect(page.locator("#saList")).to_contain_text("RED")
    expect(page.locator("#saList")).to_contain_text("insufficient ask depth")
    expect(page.locator("#saList")).not_to_contain_text("quiet patch")


def test_confidence_loss_immediately_removes_stale_action_and_recovers(page):
    """A confidence refresh must clear an existing tighten button before the next poll."""
    load_advisor(page, competitors=38)
    page.evaluate("""() => {
        Object.assign(window._lastDashboard.performance, {open_buys: 3, open_sells: 3});
        Object.assign(window._lastDashboard.market_health.metrics,
                      {effective_buy_target: 3, effective_sell_target: 3});
        renderMarketConfidence({confidence: {state: 'GREEN', data_valid: true,
                                             trusted_midpoint: '0.000075'}});
        saUpdateAdvisor(window._lastDashboard);
    }""")
    expect(page.locator("#alertsBody")).to_contain_text("Tighten base")
    page.evaluate("""() => renderMarketConfidence({confidence: {
        state: 'RED', data_valid: false, trusted_midpoint: null,
        reason_codes: ['provider_evidence_expired']
    }})""")
    expect(page.locator("#alertsBody")).not_to_contain_text("Tighten base")
    expect(page.locator("#saList")).to_contain_text("provider evidence expired")
    page.evaluate("""() => renderMarketConfidence({confidence: {
        state: 'GREEN', data_valid: true, trusted_midpoint: '0.000075'
    }})""")
    expect(page.locator("#alertsBody")).to_contain_text("Tighten base")


def test_bootstrap_anchor_does_not_make_external_price_advice_trusted(page):
    """An approved anchor permits bounded Bootstrap, not ordinary market inference."""
    load_advisor(page, bootstrap=True)
    page.evaluate("""() => {
        renderMarketConfidence({confidence: {state: 'RED', data_valid: false,
                                             trusted_midpoint: null}});
        saUpdateAdvisor(window._lastDashboard);
    }""")
    expect(page.locator("#alertsBody")).not_to_contain_text("Tighten base")
    expect(page.locator("#saList")).to_contain_text("Bootstrap")
    expect(page.locator("#saList")).to_contain_text("anchor")
    expect(page.locator("#saList")).not_to_contain_text("Follow offers are paused")


def test_indicative_price_does_not_instruct_loosening_rails_or_spread_caps(page):
    """Price guard diagnosis needs a trusted price, not the remembered display mid."""
    load_advisor(page)
    page.evaluate("""() => {
        window._lastDashboard.settings.safety.hard_max_price = '0.00005';
        window._lastDashboard.settings.spreads.dynamic_enabled = true;
        window._lastDashboard.market_health.metrics.buy_spread_bps = 1500;
        renderMarketConfidence({confidence: {state: 'RED', data_valid: false,
                                             trusted_midpoint: null}});
        saUpdateAdvisor(window._lastDashboard);
    }""")
    expect(page.locator("#alertsBody")).not_to_contain_text("raise it")
    expect(page.locator("#alertsBody")).not_to_contain_text("Review Max Spread")


def test_market_block_does_not_hide_wallet_connectivity_warning(page):
    """Independent recovery guidance must remain available under RED confidence."""
    load_advisor(page)
    page.evaluate("""() => {
        bot_state.chia_health.wallet_reachable = false;
        renderMarketConfidence({confidence: {state: 'RED', data_valid: false,
                                             trusted_midpoint: null}});
        saUpdateAdvisor(window._lastDashboard);
    }""")
    expect(page.locator("#saList")).to_contain_text("cannot reach your wallet")
