"""Live-package regressions found during public-readiness review."""

from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e


def _open_gui(page):
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")


def test_running_bootstrap_reload_does_not_request_coin_prep_again(page):
    """Locked live offers must not trigger a new fee approval on reload."""
    _open_gui(page)
    result = page.evaluate(
        """async () => {
            const assetId = 'ab'.repeat(32);
            const campaignId = 'cd'.repeat(32);
            currentCAT = {asset_id: assetId, wallet_id: 2, name: 'MZ', decimals: 3};
            _bootstrapActiveCampaign = {
                campaign_id: campaignId, revision: 0, asset_id: assetId,
            };
            settingsReviewed = true;
            coinPrepStatus = 'none';
            bot_state = {
                running: true,
                current_cat: currentCAT,
                offers: {buy: [{trade_id: 'buy-1'}], sell: [{trade_id: 'sell-1'}]},
            };
            window.__prepReloadCalls = [];
            apiFetch = async path => {
                const url = String(path);
                window.__prepReloadCalls.push(url);
                if (url.endsWith('/coin-prep/status')) {
                    return new Response(JSON.stringify({
                        success: true,
                        complete: true,
                        phase: 'complete',
                        bootstrap_campaign_id: campaignId,
                        bootstrap_campaign_revision: 0,
                        last_prep_settings: {cat_asset_id: assetId},
                    }), {status: 200});
                }
                if (url.endsWith('/config')) {
                    return new Response(JSON.stringify({
                        XCH_RESERVE: '10', CAT_RESERVE: '100',
                    }), {status: 200});
                }
                if (url.includes('/coin-prep/verify?')) {
                    return new Response(JSON.stringify({
                        success: true,
                        all_sufficient: false,
                        balance_sufficient: true,
                        reason: 'must_resize',
                        message: 'Current campaign outputs require re-preparation.',
                        bootstrap_campaign_id: campaignId,
                        bootstrap_campaign_revision: 0,
                        tiers: {},
                    }), {status: 200});
                }
                if (url.endsWith('/coin-prep/fee-preview')) {
                    return new Response(JSON.stringify({
                        success: false, available: false,
                        reason: 'FEE_ESTIMATE_UNAVAILABLE',
                    }), {status: 503});
                }
                throw new Error(`Unexpected request: ${url}`);
            };
            const restored = await restoreCoinPrepReadiness();
            return {
                restored,
                coinPrepStatus,
                calls: window.__prepReloadCalls,
                modalOpen: document.getElementById('coinPrepConfirmOverlay')
                    .classList.contains('active'),
            };
        }"""
    )

    assert result == {
        "restored": True,
        "coinPrepStatus": "skipped-safe",
        "calls": ["/api/coin-prep/status"],
        "modalOpen": False,
    }


def test_splash_local_acknowledgement_is_not_labeled_published(page):
    """A 2xx from the local daemon cannot prove peer broadcast or discovery."""
    _open_gui(page)
    details = page.evaluate(
        """() => {
            currentCAT = {name: 'MZ', decimals: 3};
            updateOffers('buyOffers', [{
                full_id: 'aa'.repeat(32),
                side: 'buy',
                status: 'PENDING_ACCEPT',
                size_xch: '0.03',
                size_cat: '400',
                price: '0.000075',
                publication: {
                    dexie: {state: 'succeeded'},
                    splash: {state: 'succeeded'},
                },
                discovery: {providers: {
                    dexie: {state: 'exact'},
                    splash: {state: 'pending'},
                }},
            }]);
            return document.querySelector('#buyOffers .offer-details').textContent;
        }"""
    )

    assert "Splash local submit acknowledged" in details
    assert "Splash succeeded" not in details
    assert "Splash pending" in details


def test_startup_risk_dialog_keeps_keyboard_focus_inside(page):
    """Tab and Shift+Tab must not reach background trading controls."""
    _open_gui(page)
    page.evaluate("startupShowRiskDisclosure()")
    continue_button = page.locator("#startupDisclaimerContinueBtn")
    close_button = page.locator("#startupDisclaimerCloseBtn")

    close_button.focus()
    page.keyboard.press("Tab")
    assert continue_button.evaluate("element => document.activeElement === element")

    continue_button.focus()
    page.keyboard.press("Shift+Tab")
    assert close_button.evaluate("element => document.activeElement === element")


def test_startup_risk_dialog_opens_at_top_on_small_window(page):
    """Focus must not skip the disclosure text above the Continue button."""
    page.set_viewport_size({"width": 360, "height": 640})
    _open_gui(page)
    page.evaluate("startupShowRiskDisclosure()")
    overlay = page.locator("#startupOverlay")

    assert overlay.evaluate("element => element.scrollTop") == 0
    assert overlay.evaluate("element => element.contains(document.activeElement)")
    page.keyboard.press("Tab")
    assert page.locator("#startupDisclaimerContinueBtn").evaluate(
        "element => document.activeElement === element"
    )
