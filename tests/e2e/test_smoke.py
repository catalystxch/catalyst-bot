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
    expect(page.locator("#ammPlaceholder .v4-data-strip-placeholder-dots")).to_be_hidden()


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
    expect(page.locator("#mktArbSub")).to_have_text(
        "TibetSwap outage — Dexie-only"
    )
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
        lambda response: server_errors.append(
            f"{response.status} {response.request.method} {response.url}"
        )
        if response.status >= 500
        else None,
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
        f"Unexpected JS console errors: {real_errors}; "
        f"server errors: {server_errors}"
    )
