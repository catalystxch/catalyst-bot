"""Live-package regressions found during public-readiness review."""

from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e


def _open_gui(page):
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")


def test_splash_pending_start_does_not_claim_listening_enabled(page):
    _open_gui(page)
    result = page.evaluate(
        """async () => {
            const btn = document.getElementById('splashListenToggle');
            btn.dataset.enabled = '0';
            btn.textContent = 'Start Listening';
            const toasts = [];
            window.apiFetch = async () => new Response(JSON.stringify({
                success: false, applied: false, pending: true,
                node_action: 'starting',
                stats: {enabled: true, active: false, node_metrics: {}}
            }), {status: 202, headers: {'Content-Type': 'application/json'}});
            window.fetchMarketIntel = async () => {};
            window.showToast = (message, kind) => toasts.push({message, kind});
            window.addLogEntry = () => {};
            await window.toggleSplashListening();
            return {text: btn.textContent, busy: btn.dataset.busy, toasts};
        }"""
    )

    assert result["text"] == "Listening Enabled"
    assert result["busy"] == "0"
    assert not any(t["kind"] == "success" for t in result["toasts"])
    assert any("starting" in t["message"].lower() for t in result["toasts"])


@pytest.mark.parametrize("width", [390, 480])
def test_dashboard_quick_start_remains_visible_in_small_window(page, width):
    """The pair selector and Refresh control must not be clipped by the guide."""
    page.set_viewport_size({"width": width, "height": 640})
    _open_gui(page)
    page.evaluate(
        """() => {
            const overlay = document.getElementById('startupOverlay');
            overlay.classList.add('hidden');
            overlay.style.display = 'none';
            const selector = document.getElementById('catSelector');
            selector.add(new Option('Monkeyzoo Token (MZ_XCH) │ 0 XCH/day', 'mz'));
        }"""
    )

    viewport_width = page.evaluate("window.innerWidth")
    for selector in (
        "#startupGuideTitle",
        ".dashboard-pair-card",
        ".dashboard-pair-row button",
    ):
        box = page.locator(selector).bounding_box()
        assert box is not None
        assert box["x"] + box["width"] <= viewport_width, selector


def test_settings_setup_remains_visible_in_small_window(page):
    """Settings cards and the Setup tab must fit beside the compact sidebar."""
    page.set_viewport_size({"width": 390, "height": 640})
    _open_gui(page)
    page.evaluate("window.v4SwitchView('settings')")

    viewport_width = page.evaluate("window.innerWidth")
    for selector in (
        "#v4View-settings .container",
        "#settingsSubtabSetup",
        "#settingsWalletSessionSection",
    ):
        box = page.locator(selector).bounding_box()
        assert box is not None
        assert box["x"] + box["width"] <= viewport_width, selector


def test_doctor_report_escapes_duration_from_api(page):
    _open_gui(page)
    malicious_duration = '<img src=x onerror="window.__doctorDurationInjected=true">'
    page.evaluate(
        """async duration => {
            window.__doctorDurationInjected = false;
            window.apiFetch = async path => {
                if (path !== '/api/doctor?force=true') throw new Error('Unexpected request');
                return new Response(JSON.stringify({
                    can_start: true,
                    summary: 'Ready',
                    duration_ms: duration,
                    checks: [],
                }), {status: 200});
            };
            await showDoctorReport();
        }""",
        malicious_duration,
    )
    modal = page.locator(".v4-modal-shell").last
    assert malicious_duration in modal.locator(".v4-modal-copy").inner_text()
    assert modal.locator("img").count() == 0
    assert page.evaluate("window.__doctorDurationInjected") is False


@pytest.mark.parametrize(
    ("mode", "xch_budget", "cat_budget", "buy_count", "sell_count"),
    [
        ("buy_only", "1", "0", 3, 0),
        ("sell_only", "0", "1000", 0, 3),
    ],
)
def test_bootstrap_preview_shows_effective_one_sided_authority(
    page, mode, xch_budget, cat_budget, buy_count, sell_count
):
    _open_gui(page)
    panel = page.evaluate(
        """async ({mode, xchBudget, catBudget, buyCount, sellCount}) => {
            _bootstrapBuildReviewBody = () => ({asset_id: 'ab'.repeat(32)});
            apiFetch = async () => new Response(JSON.stringify({
                success: true,
                preview_digest: 'reviewed-digest',
                liquidity_mode: mode,
                campaign: {
                    asset_id: 'ab'.repeat(32), anchor_price: '0.001',
                    minimum_price: '0.0005', maximum_price: '0.002',
                    xch_budget: xchBudget, cat_budget: catBudget,
                },
                plan: {
                    deployment_fraction: '0.1',
                    sides: {
                        buy: {levels: Array(buyCount).fill({})},
                        sell: {levels: Array(sellCount).fill({})},
                    },
                },
            }), {status: 200});
            await bootstrapPreviewCampaign();
            return document.getElementById('bootstrapStatusPanel').textContent;
        }""",
        {
            "mode": mode,
            "xchBudget": xch_budget,
            "catBudget": cat_budget,
            "buyCount": buy_count,
            "sellCount": sell_count,
        },
    )
    assert f"Liquidity mode {mode.replace('_', ' ')}" in panel
    assert f"effective market budgets {xch_budget} XCH / {cat_budget} CAT" in panel
    assert f"{buy_count} buy / {sell_count} sell offers" in panel


def test_stopped_bootstrap_clears_stale_authority_and_asset_confirmation(page):
    """A stopped campaign must not leave its old authority review armed in the UI."""
    _open_gui(page)
    result = page.evaluate(
        """() => {
            const campaignId = 'ab'.repeat(32);
            _bootstrapActiveCampaign = {campaign_id: campaignId, revision: 0};
            _bootstrapPreviewDigest = 'old-preview';
            _bootstrapPreviewBody = {asset_id: 'old-asset'};
            document.getElementById('bootstrapStatusPanel').textContent =
                `Campaign ${campaignId} is active and locked to revision 0.`;
            document.getElementById('bootstrapExactAssetConfirm').checked = true;

            _bootstrapRenderStatus({active: false, campaign: null, identity: null});

            return {
                panel: document.getElementById('bootstrapStatusPanel').textContent,
                confirmed: document.getElementById('bootstrapExactAssetConfirm').checked,
                digest: _bootstrapPreviewDigest,
                body: _bootstrapPreviewBody,
                startDisabled: document.getElementById('bootstrapStartBtn').disabled,
            };
        }"""
    )

    assert result == {
        "panel": "No active Bootstrap campaign. Review exact local budgets and Preview before starting.",
        "confirmed": False,
        "digest": "",
        "body": None,
        "startDisabled": True,
    }


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


def test_startup_wallet_choice_starts_at_top_after_scrolled_disclosure(page):
    """A shorter next step must not inherit the prior step's scroll position."""
    page.set_viewport_size({"width": 600, "height": 400})
    _open_gui(page)
    page.evaluate(
        """() => {
            startupShowRiskDisclosure();
            const overlay = document.getElementById('startupOverlay');
            overlay.scrollTop = overlay.scrollHeight;
            document.getElementById('startupDisclaimerSection').style.display = 'none';
            document.getElementById('startupSageConnectSection').style.display = 'block';
            startupSetPhase('wallet_choice', 'Connect Wallet', 'Sage is already open', '');
        }"""
    )

    assert page.locator("#startupOverlay").evaluate("element => element.scrollTop") == 0


def test_startup_wallet_choice_keeps_dialog_focus_after_disclosure(app_page):
    """Advancing the dialog must not leave keyboard focus on the background."""
    app_page.set_viewport_size({"width": 600, "height": 400})
    app_page.locator("#startupDisclaimerContinueBtn").click()
    app_page.locator(
        "#startupSageConnectSection:visible, #startupSageLaunchSection:visible"
    ).wait_for(state="visible")

    assert app_page.locator("#startupOverlay").evaluate(
        "element => element.contains(document.activeElement)"
    )


def test_startup_wallet_choice_keeps_keyboard_focus_inside(page):
    """Later startup steps must not leak focus to background navigation."""
    _open_gui(page)
    page.evaluate(
        """() => {
            startupShowRiskDisclosure();
            document.getElementById('startupDisclaimerSection').style.display = 'none';
            document.getElementById('startupSageLaunchSection').style.display = 'block';
            startupSetPhase('wallet_choice', 'Connect Wallet', 'Sage is not running', '');
        }"""
    )
    buttons = page.locator("#startupSageLaunchSection button")
    first, last = buttons.first, buttons.last

    last.focus()
    page.keyboard.press("Tab")
    assert first.evaluate("element => document.activeElement === element")

    first.focus()
    page.keyboard.press("Shift+Tab")
    assert last.evaluate("element => document.activeElement === element")

    page.get_by_role("button", name="Dashboard").focus()
    page.keyboard.press("Tab")
    assert first.evaluate("element => document.activeElement === element")


@pytest.mark.parametrize("gate_id", ["splashGateOverlay", "spacescanGateOverlay"])
def test_service_gate_keeps_keyboard_focus_inside(page, gate_id):
    """Setup gates must not let Tab reach controls behind the overlay."""
    _open_gui(page)
    page.evaluate(
        """gateId => {
            const startup = document.getElementById('startupOverlay');
            startup.classList.add('hidden');
            startup.style.display = 'none';
            const gate = document.getElementById(gateId);
            gate.style.display = 'flex';
            gate.classList.add('active');
            if (gateId === 'splashGateOverlay') {
                document.getElementById('splashGateStartSection').style.display = 'block';
            }
        }""",
        gate_id,
    )
    gate = page.locator(f"#{gate_id}")
    controls = gate.locator(
        "a[href]:visible, button:not([disabled]):visible, input:not([disabled]):visible"
    )
    first, last = controls.first, controls.last

    last.focus()
    page.keyboard.press("Tab")
    assert first.evaluate("element => document.activeElement === element")

    first.focus()
    page.keyboard.press("Shift+Tab")
    assert last.evaluate("element => document.activeElement === element")

    page.get_by_role("button", name="Dashboard").focus()
    page.keyboard.press("Tab")
    assert first.evaluate("element => document.activeElement === element")
