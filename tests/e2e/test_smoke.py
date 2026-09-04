"""End-to-end smoke tests for the CATalyst dashboard.

Scope: verify the app boots, the risk disclaimer renders, and the primary
navigation tabs are present. These tests are deliberately Sage-free — they
prove the static UI shell works, which is what breaks most often when the
HTML/JS is refactored.

Run with:

    cd tests
    python -m pytest e2e/test_smoke.py --e2e -v --headed   # watch in browser
    python -m pytest e2e/test_smoke.py --e2e               # headless

Anything that requires a real Sage connection should live in a separate
file (e.g. `test_full_setup.py`) marked accordingly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

from .conftest import dismiss_disclaimer

pytestmark = pytest.mark.e2e


def reveal_app_shell_for_nav(page) -> None:
    """Hide startup gates so nav smoke tests can exercise the main shell.

    The real first-run flow intentionally keeps the sidebar blocked until the
    wallet/Splash/Spacescan gates complete. These tests are not validating
    those gates; they validate that the public shell views still switch once
    startup is past them.
    """
    dismiss_disclaimer(page)
    page.evaluate(
        """() => {
            for (const id of ['startupOverlay', 'splashGateOverlay', 'spacescanGateOverlay']) {
                const el = document.getElementById(id);
                if (!el) continue;
                el.classList.add('hidden');
                el.classList.remove('active');
                el.style.display = 'none';
            }
            if (typeof window.finalDismiss === 'function') {
                window.finalDismiss();
            }
        }"""
    )


def test_app_loads_with_disclaimer(app_page):
    """The dashboard should boot, render the title, and show the disclaimer."""
    assert app_page.title() == "CATalyst"
    disclaimer_btn = app_page.locator("#startupDisclaimerContinueBtn")
    disclaimer_btn.wait_for(state="visible", timeout=10_000)
    assert disclaimer_btn.is_visible()
    close_btn = app_page.locator("#startupDisclaimerCloseBtn")
    assert close_btn.is_visible()


def test_running_session_reload_never_shows_risk_disclosure(flask_server, page):
    """A running session must stay behind the neutral probe overlay on reload."""
    page.add_init_script(
        """(() => {
            window.__riskDisclosureEverVisible = false;
            document.addEventListener('DOMContentLoaded', () => {
                const disclosure = document.getElementById('startupDisclaimerSection');
                if (!disclosure) return;
                const recordVisibility = () => {
                    if (window.getComputedStyle(disclosure).display !== 'none') {
                        window.__riskDisclosureEverVisible = true;
                    }
                };
                new MutationObserver(recordVisibility).observe(disclosure, {
                    attributes: true,
                    attributeFilter: ['style', 'class'],
                });
                recordVisibility();
            });
        })()"""
    )

    status_calls = 0

    def running_status_once(route):
        nonlocal status_calls
        status_calls += 1
        if status_calls == 1:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"running": True, "stats": {"loop_count": 1}}),
            )
            return
        route.continue_()

    page.route("**/api/status", running_status_once)
    page.goto(flask_server, wait_until="domcontentloaded")

    expect(page.locator("#startupOverlay")).to_be_hidden(timeout=5_000)
    assert status_calls >= 1
    assert page.evaluate("window.__riskDisclosureEverVisible") is False


def test_dismissing_disclaimer_reveals_wallet_gate(app_page):
    """Continuing past the disclaimer should land on a Sage startup gate."""
    assert dismiss_disclaimer(app_page) is True
    # In the Sage-free smoke environment the expected branch is "wallet not
    # open"; on a developer box with Sage already running, the same gate may
    # instead show the "Connect to Sage" button.
    connect = app_page.get_by_role("button", name=re.compile(r"Connect to Sage", re.I))
    wallet_not_open = app_page.locator("#startupSubtitle")
    try:
        connect.first.wait_for(state="visible", timeout=7_000)
    except PlaywrightTimeoutError:
        expect(wallet_not_open).to_contain_text(
            "Sage wallet isn't running", timeout=10_000
        )
    assert (
        connect.first.is_visible()
        or "Sage wallet isn't running" in wallet_not_open.text_content()
    )


def test_primary_nav_tabs_present(app_page):
    """Primary nav should be in the DOM even before the user connects a wallet.

    Names are the buttons' accessible names (aria-label), which differ from
    the visible label in a couple of cases ("P&L" → "Profit and loss",
    "Market Intel" → "Market intelligence"). Test against the accessible
    name so screen-reader users and the test stay aligned.
    """
    dismiss_disclaimer(app_page)
    expected = [
        "Dashboard",
        "Offers",
        "Profit and loss",
        "Market intelligence",
        "Settings",
        "Logs",
        "Data reset",
    ]
    for label in expected:
        nav_btn = app_page.get_by_role("button", name=label, exact=True)
        assert nav_btn.count() >= 1, f"nav button '{label}' missing from DOM"


@pytest.mark.parametrize(
    ("label", "view_id"),
    [
        ("Dashboard", "v4View-dashboard"),
        ("Offers", "v4View-offers"),
        ("Profit and loss", "v4View-pnl"),
        ("Market intelligence", "v4View-intel"),
        ("Settings", "v4View-settings"),
        ("Logs", "v4View-logs"),
        ("Data reset", "v4View-data"),
    ],
)
def test_primary_nav_views_switch_without_wallet(app_page, label, view_id):
    """Core public UI views should switch once the startup gates are past."""
    reveal_app_shell_for_nav(app_page)

    app_page.get_by_role("button", name=label, exact=True).click(timeout=5_000)

    expect(app_page.locator(f"#{view_id}")).to_have_class(re.compile(r"\bactive\b"))


def test_data_reset_button_opens_destructive_confirmation(app_page):
    """Data-reset actions should show a confirmation dialog before POSTing."""
    reveal_app_shell_for_nav(app_page)
    app_page.get_by_role("button", name="Data reset", exact=True).click(timeout=5_000)

    app_page.locator("#btnResetPnl").click(timeout=5_000)

    expect(app_page.locator("#styledConfirmOverlay")).to_have_class(
        re.compile(r"\bactive\b")
    )
    expect(app_page.locator("#confirmTitle")).to_have_text("Reset P&L Counters")
    expect(app_page.locator("#confirmOkBtn")).to_have_text("Reset P&L")


def test_opening_logs_view_reveals_latest_entry(page):
    """Opening Logs should show the newest entry, not a stale scroll position."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")
    log_panel = page.locator("#logsContainer")
    page.evaluate(
        """() => {
            const panel = document.getElementById('logsContainer');
            panel.innerHTML = Array.from(
                { length: 200 },
                (_, index) => `<div style="height:20px">entry-${index}</div>`,
            ).join('');
            panel.scrollTop = 0;
            window.v4SwitchView('dashboard');
        }"""
    )

    page.evaluate("window.v4SwitchView('logs')")

    page.wait_for_function(
        """() => {
            const panel = document.getElementById('logsContainer');
            return panel.scrollHeight > panel.clientHeight;
        }"""
    )
    assert log_panel.evaluate(
        "panel => panel.scrollHeight - panel.scrollTop - panel.clientHeight < 2"
    )


def test_returning_to_logs_fetches_fresh_events_immediately(page):
    """Dashboard -> Logs must replace stale DOM before the 15s fallback poll."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")
    log_panel = page.locator("#logsContainer")
    page.evaluate(
        """() => {
            window.__logsRequestCount = 0;
            window.apiFetch = async (path) => {
                if (!String(path).includes('/logs?limit=2000')) {
                    throw new Error(`Unexpected test request: ${path}`);
                }
                window.__logsRequestCount += 1;
                return new Response(JSON.stringify({
                    logs: [{
                        id: 2,
                        timestamp: '2026-08-23 10:50:48',
                        severity: 'success',
                        event_type: 'cycle_complete',
                        message: 'Cycle #133 complete — 24b/24s active',
                        data: null,
                    }],
                }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            document.getElementById('logsContainer').innerHTML = '<div>stale-startup-entry</div>';
            window.v4SwitchView('dashboard');
        }"""
    )

    page.evaluate("window.v4SwitchView('logs')")

    expect(log_panel).to_contain_text("Cycle #133 complete", timeout=2_000)
    assert page.evaluate("window.__logsRequestCount") == 1


def test_inactive_amm_monitor_is_not_shown_as_still_gathering(page):
    """A resolved inactive monitor state must not look like an endless fetch."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.updateAmmStatusBar({
                available: false,
                amm_price: null,
                xch_reserve: null,
                token_reserve: null,
                fetched_at: 0,
                pair_id: '',
                total_polls: 0,
                failed_polls: 0,
                consecutive_failures: 0,
                last_success_ago_secs: null,
            });
        }"""
    )

    expect(page.locator("#ammPlaceholder")).to_contain_text(
        "TibetSwap monitor inactive"
    )
    expect(
        page.locator("#ammPlaceholder .v4-data-strip-placeholder-dots")
    ).to_be_hidden()


def test_market_intel_names_confirmed_tibetswap_outage(page):
    """Market Intel must distinguish a TibetSwap outage from an absent pool."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.renderTibetSlippageContext({
                available: false,
                error: 'TibetSwap quote unavailable',
                message: 'TibetSwap outage (HTTP 502): pool depth and slippage are unavailable. CATalyst is using Dexie-only pricing; AMM drift protection is unavailable.',
                provider: 'tibetswap',
                reason: 'provider_outage',
                status_code: 502,
            });
        }"""
    )

    expect(page.locator("#intelTibetContext")).to_have_text(
        "TibetSwap outage (HTTP 502): pool depth and slippage are unavailable. "
        "CATalyst is using Dexie-only pricing; AMM drift protection is unavailable."
    )
    expect(page.locator("#intelSlippage")).to_have_text("Unavailable")
    expect(page.locator("#intelPoolRatio")).to_have_text("Unavailable")


def test_dashboard_diagnostics_do_not_render_false_tibet_values_during_outage(page):
    """The TibetSwap outage must not look like a zero pool or zero arb gap."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.renderMarketSummaryVenueState({
                has_data: true,
                dexie_depth_xch: 420,
                pool_xch: 0,
                arb_gap_bps: 0,
                tibet_available: false,
                tibet_reason: 'provider_outage',
                tibet_status_code: 502,
            });
            window.updateIntelDiagnostics({
                pricing: { bid: 0.00006723, ask: 0.00006792 },
                arb_gap_bps: 0,
                chia_health: { status: 'healthy' },
                diagnostics: { spacescan_enabled: true },
            });
        }"""
    )

    expect(page.locator("#mktTibetDepth")).to_have_text("Tibet: unavailable")
    expect(page.locator("#mktArbGap")).to_have_text("Unavailable")
    expect(page.locator("#mktArbSub")).to_have_text("TibetSwap outage — Dexie-only")
    expect(page.locator("#coverageTibet")).to_have_text("outage")
    expect(page.locator("#intelArbGapTrend")).to_have_text("Unavailable")
    expect(page.locator("#intelArbGapTrendSub")).to_have_text(
        "TibetSwap outage — Dexie-only"
    )


def test_dashboard_market_health_marks_tibet_metrics_unavailable_during_outage(page):
    """The TibetSwap outage must not render AMM-only health metrics as zero."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.updateMarketHealth({
                status: 'amber',
                message: 'Market degraded — TibetSwap unavailable; Dexie-only pricing active without AMM drift protection',
                conditions: [{
                    level: 'amber',
                    text: 'TibetSwap API unavailable — Dexie-only pricing; AMM drift protection and reference price unavailable',
                }],
                metrics: {
                    pricing_mode: 'dexie_only',
                    tibetswap_available: false,
                    tibetswap_status_code: 502,
                    arb_gap_bps: '0',
                    pool_depth_ratio: '0',
                },
            });
        }"""
    )

    expect(page.locator("#ccHealthMsg")).to_have_text(
        "Market degraded — TibetSwap unavailable; Dexie-only pricing active without AMM drift protection"
    )
    expect(page.locator("#ccArbGap")).to_have_text("Unavailable")
    expect(page.locator("#ccPoolDepth")).to_have_text("Unavailable")
    expect(page.locator("#ccConditions")).to_contain_text(
        "TibetSwap API unavailable — Dexie-only pricing"
    )


def test_running_status_pair_drives_market_cards_before_cat_list_hydrates(page):
    """A running pair must not flash the misleading ``Select pair`` state."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """async () => {
            currentCAT = {};
            bot_state = {
                running: true,
                current_cat: {
                    asset_id: 'b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105',
                    wallet_id: 2,
                    ticker_id: 'MZ_XCH',
                    name: 'Monkeyzoo Token',
                    decimals: 3,
                },
            };
            apiFetch = async () => new Response(JSON.stringify({
                has_data: true,
                best_bid: 0.0000672337521645723,
                best_ask: 0.0000679213506120472,
                volume_24h: 0.242291699794,
                dexie_depth_xch: 420,
                pool_xch: 0,
                arb_gap_bps: 0,
                mid_price: 0.0000675775515,
                tibet_available: false,
                tibet_reason: 'provider_outage',
                tibet_status_code: 502,
            }), { status: 200 });

            await fetchMarketSummary();
        }"""
    )

    expect(page.locator("#mktBestBid")).to_have_text("0.00006723")
    expect(page.locator("#mktBestAsk")).to_have_text("0.00006792")
    expect(page.locator("#mktVolume24h")).to_have_text("0.242")
    expect(page.locator("#mktTibetDepth")).to_have_text("Tibet: unavailable")
    expect(page.locator("#mktArbGap")).to_have_text("Unavailable")


def test_pair_pnl_reset_allows_identical_fill_snapshot_to_render_again(page):
    """A pair reset must clear both P&L points and their dedupe signature."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.v4SwitchView('pnl');
            window.v4AddPnlPoint(0, { fills: 12, pending: 0 });
            window.v4ResetPnlHistory();
            window.v4AddPnlPoint(0, { fills: 12, pending: 0 });
        }"""
    )

    expect(page.locator("#pnlEmptyState")).to_be_hidden()


def test_smart_settings_snapshot_ignores_equivalent_number_formatting(page):
    """A save/reload formatting round-trip must not mark Smart Settings stale."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    is_dirty = page.evaluate(
        """async () => {
            const tradeSize = document.getElementById('configTradeXch');
            tradeSize.value = '2.0810';
            markSmartSettingsApplied();
            await new Promise(resolve => setTimeout(resolve, 0));

            // /api/config reloads the same number without presentation-only
            // trailing zeroes after Save & Continue -> Back to Settings.
            tradeSize.value = '2.081';
            return checkSmartSettingsDirty();
        }"""
    )

    assert is_dirty is False
    expect(page.locator("#smartSettingsStaleBanner")).to_be_hidden()


def test_coin_prep_open_offer_conflict_prompts_for_confirmed_cancellation(page):
    """A live ladder must lead to a usable cancel-first recovery, not raw JSON."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """async () => {
            bot_state = { running: false, offers: { buy: [], sell: [] } };
            askPrepHistoryChoice = async () => ({
                action: 'proceed',
                resets: { pnl: false, offers: false, counters: false },
            });
            apiFetch = async (path) => {
                if (!String(path).includes('/coin-prep/trigger')) {
                    throw new Error(`Unexpected test request: ${path}`);
                }
                return new Response(JSON.stringify({
                    success: false,
                    error: 'coin_prep_requires_offer_cancellation',
                    reason: 'OPEN_OFFERS_REQUIRE_CANCELLATION',
                    message: '72 open offers must be cancelled and authoritatively confirmed before coin prep can safely replace their locked coins.',
                    action: 'cancel_all_then_retry',
                    open_offer_count: 72,
                    open_buy_count: 36,
                    open_sell_count: 36,
                }), {
                    status: 409,
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            await startCoinPrepFromModal();
        }"""
    )

    expect(page.locator("#cancelConfirmModal")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#cancelConfirmTitle")).to_have_text(
        "Cancel offers before coin prep?"
    )
    expect(page.locator("#cancelConfirmCopy")).to_contain_text(
        "every live offer in the connected wallet"
    )
    expect(page.locator("#cancelConfirmCopy")).to_contain_text(
        "including offers not tracked by CATalyst"
    )
    expect(page.locator("#cancelOfferCount")).to_contain_text(
        "72 CATalyst-tracked active offers"
    )
    expect(page.locator("#cancelOfferCount")).to_contain_text("36 buy")
    expect(page.locator("#cancelOfferCount")).to_contain_text("36 sell")
    expect(page.locator("#cancelAllConfirmBtn")).to_have_text(
        "Cancel Offers & Continue"
    )


def test_coin_prep_full_reset_conflict_preserves_proof_warning(page):
    """Cancelling live offers must not promise to clear protected history."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """async () => {
            bot_state = { running: false, offers: { buy: [], sell: [] } };
            askPrepHistoryChoice = async () => ({
                action: 'proceed',
                resets: { pnl: true, offers: false, counters: false },
            });
            apiFetch = async () => new Response(JSON.stringify({
                success: false,
                error: 'coin_prep_requires_offer_cancellation',
                reason: 'OPEN_OFFERS_REQUIRE_CANCELLATION',
                message: '2 open offers must be cancelled. The requested history reset is also blocked by protected authoritative state; after cancellation, retry coin prep without clearing protected history.',
                action: 'cancel_all_then_retry_without_protected_resets',
                open_offer_count: 2,
                open_buy_count: 1,
                open_sell_count: 1,
                additional_conflicts: ['authoritative_session_state', 'coin_reservations'],
            }), {
                status: 409,
                headers: { 'Content-Type': 'application/json' },
            });
            await startCoinPrepFromModal();
        }"""
    )

    expect(page.locator("#cancelConfirmModal")).to_have_class(re.compile(r"\bactive\b"))
    expect(page.locator("#cancelConfirmCopy")).to_contain_text(
        "retry Prepare Coins without resetting protected history"
    )
    expect(page.locator("#cancelAllConfirmBtn")).to_have_text("Cancel Offers")
    assert page.evaluate("_cancelAllContext.resumeAfterCancel") is False


def test_coin_prep_offer_history_reset_requires_manual_safe_retry(page):
    """Offer-history reset must not auto-resume after cancellation creates proof."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    submitted = page.evaluate(
        """async () => {
            bot_state = { running: false, offers: { buy: [], sell: [] } };
            askPrepHistoryChoice = async () => ({
                action: 'proceed',
                resets: { pnl: false, offers: true, counters: false },
            });
            window.__submittedPrepPayload = null;
            apiFetch = async (_path, options) => {
                window.__submittedPrepPayload = JSON.parse(options.body);
                return new Response(JSON.stringify({
                    success: false,
                    error: 'coin_prep_requires_offer_cancellation',
                    reason: 'OPEN_OFFERS_REQUIRE_CANCELLATION',
                    message: '1 open offer must be cancelled. After cancellation, retry coin prep without clearing protected history.',
                    action: 'cancel_all_then_retry_without_protected_resets',
                    open_offer_count: 1,
                    open_buy_count: 1,
                    open_sell_count: 0,
                    additional_conflicts: ['offer_proof_history'],
                }), {
                    status: 409,
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            await startCoinPrepFromModal();
            return window.__submittedPrepPayload;
        }"""
    )

    assert submitted["reset_pnl"] is False
    assert submitted["reset_offer_history"] is True
    expect(page.locator("#cancelAllConfirmBtn")).to_have_text("Cancel Offers")
    expect(page.locator("#cancelConfirmCopy")).to_contain_text(
        "retry Prepare Coins without resetting protected history"
    )
    assert page.evaluate("_cancelAllContext.resumeAfterCancel") is False


def test_generic_cancel_all_explicitly_covers_every_live_sage_offer(page):
    """Consent text must match wallet-wide cancellation, including orphan offers."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """async () => {
            bot_state = {
                running: false,
                offers: { buy: [{ trade_id: 'tracked' }], sell: [] },
            };
            await cancelAllOffers();
        }"""
    )

    expect(page.locator("#cancelConfirmCopy")).to_contain_text(
        "every live offer in the connected wallet"
    )
    expect(page.locator("#cancelConfirmCopy")).to_contain_text(
        "including offers not tracked by CATalyst"
    )
    expect(page.locator("#cancelOfferCount")).to_contain_text(
        "CATalyst currently shows 1 active offer"
    )


def test_coin_prep_waits_for_authoritative_cancel_then_starts(page):
    """Submitted cancels must be proven terminal before prep starts automatically."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            let triggerCalls = 0;
            window.__coinPrepRecoveryLogs = [];
            addLogEntry = (_level, message) => window.__coinPrepRecoveryLogs.push(message);
            document.getElementById('coinPrepConfirmOverlay').classList.add('active');
            apiFetch = async (path) => {
                if (!String(path).includes('/coin-prep/trigger')) {
                    throw new Error(`Unexpected test request: ${path}`);
                }
                triggerCalls += 1;
                const body = triggerCalls === 1
                    ? {
                        success: false,
                        error: 'coin_prep_requires_offer_cancellation',
                        message: '2 open offers are still awaiting Sage confirmation.',
                        open_offer_count: 2,
                      }
                    : { success: true, message: 'Coin preparation started' };
                return new Response(JSON.stringify(body), {
                    status: triggerCalls === 1 ? 409 : 200,
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            const started = await resumeCoinPrepAfterCancelledOffers({
                source: 'coin_prep',
                prepPayload: {
                    coin_multiplier: 1,
                    reset_pnl: false,
                    reset_offer_history: false,
                    reset_counters: false,
                },
            }, { retryDelayMs: 0, timeoutMs: 1000 });
            return { started, triggerCalls, logs: window.__coinPrepRecoveryLogs };
        }"""
    )

    assert result["started"] is True
    assert result["triggerCalls"] == 2
    assert any("Offer states confirmed terminal" in line for line in result["logs"])
    expect(page.locator("#coinPrepProgressView")).to_be_visible()


def test_coin_prep_cancel_confirmation_runs_async_recovery_end_to_end(page):
    """Confirm must journal cancels, await proof, and retry prep with saved settings."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """async () => {
            const nativeSetInterval = window.setInterval.bind(window);
            const nativeSetTimeout = window.setTimeout.bind(window);
            window.setInterval = (fn, delay, ...args) => nativeSetInterval(fn, Math.min(Number(delay) || 0, 20), ...args);
            window.setTimeout = (fn, delay, ...args) => nativeSetTimeout(fn, Math.min(Number(delay) || 0, 20), ...args);
            window.__cancelRecovery = { cancelCalls: 0, statusCalls: 0, triggerCalls: 0, logs: [] };
            bot_state = { running: false, offers: { buy: [], sell: [] } };
            document.getElementById('coinPrepConfirmOverlay').classList.add('active');
            fetchStatus = async () => {};
            updateResumeOverview = () => {};
            pollCoinPrepProgress = async () => {};
            addLogEntry = (_level, message) => window.__cancelRecovery.logs.push(message);
            apiFetch = async (path, options = {}) => {
                const url = String(path);
                if (url.includes('/offers/cancel_all/status')) {
                    window.__cancelRecovery.statusCalls += 1;
                    return new Response(JSON.stringify({
                        success: true,
                        phase: 'complete',
                        total: 2,
                        pending: 2,
                        failed: 0,
                        message: 'Cancellation requests journaled',
                    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
                }
                if (url.includes('/offers/cancel_all')) {
                    window.__cancelRecovery.cancelCalls += 1;
                    return new Response(JSON.stringify({ success: true, async: true, total: 2 }), {
                        status: 202,
                        headers: { 'Content-Type': 'application/json' },
                    });
                }
                if (url.includes('/coin-prep/trigger')) {
                    window.__cancelRecovery.triggerCalls += 1;
                    const waiting = window.__cancelRecovery.triggerCalls === 1;
                    return new Response(JSON.stringify(waiting ? {
                        success: false,
                        error: 'coin_prep_requires_offer_cancellation',
                        message: '2 offers remain pending authoritative proof',
                        open_offer_count: 2,
                    } : { success: true, message: 'Coin preparation started' }), {
                        status: waiting ? 409 : 200,
                        headers: { 'Content-Type': 'application/json' },
                    });
                }
                throw new Error(`Unexpected test request: ${url} ${options.method || 'GET'}`);
            };

            await cancelAllOffers({
                source: 'coin_prep',
                prepPayload: {
                    coin_multiplier: 1,
                    reset_pnl: false,
                    reset_offer_history: false,
                    reset_counters: false,
                },
                openOfferCount: 2,
                openBuyCount: 1,
                openSellCount: 1,
                resumeAfterCancel: true,
            });
            await confirmCancelAll();
        }"""
    )

    page.wait_for_function(
        "window.__cancelRecovery && window.__cancelRecovery.triggerCalls >= 2",
        timeout=5_000,
    )
    result = page.evaluate("window.__cancelRecovery")
    assert result["cancelCalls"] == 1
    assert result["statusCalls"] >= 1
    assert result["triggerCalls"] == 2
    assert any(
        "2 CATalyst-tracked offers; checking connected wallet" in line
        for line in result["logs"]
    )
    assert any("Offer states confirmed terminal" in line for line in result["logs"])
    expect(page.locator("#coinPrepProgressView")).to_be_visible()


def test_cancel_all_keeps_operation_latched_until_async_work_finishes(page):
    """Hiding or re-clicking must not start a second cancel while one is active."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    still_latched = page.evaluate(
        """async () => {
            const nativeSetInterval = window.setInterval.bind(window);
            window.setInterval = (fn, delay, ...args) => nativeSetInterval(fn, Math.min(Number(delay) || 0, 20), ...args);
            window.__cancelLatchPhase = 'running';
            bot_state = { running: false, offers: { buy: [{ trade_id: 'one' }], sell: [] } };
            fetchStatus = async () => {};
            addLogEntry = () => {};
            showToast = () => {};
            apiFetch = async (path) => {
                if (String(path).includes('/offers/cancel_all/status')) {
                    return new Response(JSON.stringify({
                        success: true,
                        phase: window.__cancelLatchPhase,
                        total: 1,
                        pending: window.__cancelLatchPhase === 'complete' ? 1 : 0,
                        failed: 0,
                    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
                }
                return new Response(JSON.stringify({ success: true, async: true, total: 1 }), {
                    status: 202,
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            await cancelAllOffers();
            await confirmCancelAll();
            return _cancelAllInProgress;
        }"""
    )

    assert still_latched is True
    page.evaluate("window.__cancelLatchPhase = 'complete'")
    page.wait_for_function("_cancelAllInProgress === false", timeout=2_000)


def test_cancel_all_clears_cached_completion_before_new_async_operation(page):
    """A previous completion must not prematurely finish a new wallet request."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    cached_state = page.evaluate(
        """async () => {
            _cancelAllLastState = { success: true, phase: 'complete', total: 99 };
            bot_state = { running: false, offers: { buy: [{ trade_id: 'one' }], sell: [] } };
            fetchStatus = async () => {};
            addLogEntry = () => {};
            showToast = () => {};
            apiFetch = async (path) => {
                if (String(path).includes('/offers/cancel_all/status')) {
                    return new Promise(() => {});
                }
                return new Response(JSON.stringify({ success: true, async: true, total: 1 }), {
                    status: 202,
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            await cancelAllOffers();
            await confirmCancelAll();
            return _cancelAllLastState;
        }"""
    )

    assert cached_state is None


def test_cancel_all_discards_status_from_older_operation_generation(page):
    """A late poll from an old operation must not overwrite the current state."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            let resolveStatus;
            _cancelAllInProgress = true;
            _cancelAllOperationGeneration = 10;
            apiFetch = () => new Promise(resolve => { resolveStatus = resolve; });
            const oldPoll = pollCancelAllProgressOnce(1, 10);
            await Promise.resolve();
            _cancelAllOperationGeneration = 11;
            _cancelAllLastState = { phase: 'current' };
            resolveStatus(new Response(JSON.stringify({
                success: true,
                phase: 'complete',
                total: 1,
                pending: 1,
                failed: 0,
            }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
            await oldPoll;
            return _cancelAllLastState;
        }"""
    )

    assert result["phase"] == "current"


def test_cancel_all_timeout_is_visible_and_releases_latch(page):
    """A stalled journal poll must end in an explicit, safe timeout state."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """async () => {
            const nativeSetInterval = window.setInterval.bind(window);
            const nativeSetTimeout = window.setTimeout.bind(window);
            window.setInterval = (fn, delay, ...args) => nativeSetInterval(fn, Math.min(Number(delay) || 0, 20), ...args);
            window.setTimeout = (fn, delay, ...args) => nativeSetTimeout(fn, Math.min(Number(delay) || 0, 60), ...args);
            bot_state = { running: false, offers: { buy: [{ trade_id: 'one' }], sell: [] } };
            fetchStatus = async () => {};
            addLogEntry = () => {};
            showToast = () => {};
            apiFetch = async (path) => {
                if (String(path).includes('/offers/cancel_all/status')) {
                    return new Response(JSON.stringify({
                        success: true,
                        phase: 'running',
                        total: 1,
                        pending: 0,
                        failed: 0,
                    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
                }
                return new Response(JSON.stringify({ success: true, async: true, total: 1 }), {
                    status: 202,
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            await cancelAllOffers();
            await confirmCancelAll();
        }"""
    )

    expect(page.locator("#cancelProgressStatus")).to_contain_text(
        "timed out", timeout=2_000
    )
    assert page.evaluate("_cancelAllInProgress") is False


def test_no_console_errors_on_initial_load(app_page):
    """Catch JS console errors that fire just from loading the dashboard."""
    errors: list[str] = []
    server_errors: list[str] = []
    app_page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )
    app_page.on(
        "response",
        lambda response: (
            server_errors.append(
                f"{response.status} {response.request.method} {response.url}"
            )
            if response.status >= 500
            else None
        ),
    )
    # Note: cannot use wait_until="networkidle" — the dashboard holds an
    # open SSE connection (`/api/events`) that never goes idle.
    app_page.reload(wait_until="domcontentloaded")
    # Allow a moment for deferred init scripts + the first SSE event to settle.
    app_page.wait_for_timeout(3_000)
    # SSE/network-related errors are expected when there's no real Sage —
    # filter those out so the test is meaningful.
    real_errors = [
        e
        for e in errors
        if "EventSource" not in e
        and "Failed to fetch" not in e
        and "NetworkError" not in e
        and "ERR_NETWORK" not in e
    ]
    assert not real_errors, (
        f"Unexpected JS console errors: {real_errors}; server errors: {server_errors}"
    )
