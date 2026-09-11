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


def test_logs_backfill_includes_latest_non_debug_info_event(page):
    """The Logs tab must not keep stale rows when the newest event is ordinary info."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")
    log_panel = page.locator("#logsContainer")
    page.evaluate(
        """() => {
            window.apiFetch = async (path) => {
                if (!String(path).includes('/logs?limit=2000')) {
                    throw new Error(`Unexpected test request: ${path}`);
                }
                return new Response(JSON.stringify({
                    logs: [{
                        id: 3,
                        timestamp: '2026-09-11 03:31:33',
                        severity: 'info',
                        event_type: 'cat_selected',
                        message: 'Trading pair selected: Monkeyzoo Token (wallet 2)',
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

    expect(log_panel).to_contain_text("Trading pair selected", timeout=2_000)
    expect(log_panel).not_to_contain_text("stale-startup-entry")


def test_resolved_market_confidence_is_not_shown_as_still_gathering(page):
    """A resolved confidence snapshot must replace the warming placeholder."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.renderMarketConfidence({
                confidence: {
                    state: 'RED',
                    reason_codes: ['insufficient_attributable_depth'],
                },
                evidence: { source_ids: [] },
                providers: {},
                metrics: {},
            });
        }"""
    )

    expect(page.locator("#marketConfidencePlaceholder")).to_be_hidden()
    expect(page.locator("#marketConfidenceState")).to_have_text("RED")
    expect(page.locator("#marketConfidenceReasons")).to_have_text(
        "insufficient attributable depth"
    )


def test_market_intel_explains_tibetswap_retirement(page):
    """Market Intel must explain that TibetSwap is historical-only in v1.4."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    expect(page.locator("#intelTibetContext")).to_have_text(
        "TibetSwap shut down; historical TibetSwap data is retained as read-only "
        "history and never drives a live decision."
    )
    expect(page.locator("#intelSlippage")).to_be_hidden()
    expect(page.locator("#intelPoolRatio")).to_be_hidden()


def test_dashboard_confidence_does_not_invent_tradable_depth(page):
    """Red confidence must not turn absent attributable depth into zero-valued safety."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.renderMarketConfidence({
                confidence: {
                    state: 'RED',
                    trusted_bid: null,
                    trusted_ask: null,
                    reason_codes: ['stale_provider_evidence'],
                },
                metrics: {
                    independent_bid_depth_xch: 0,
                    independent_ask_depth_xch: 0,
                },
                evidence: { source_ids: [] },
                providers: {
                    dexie: { status: 'stale', reason_codes: ['evidence_expired'] },
                },
            });
        }"""
    )

    expect(page.locator("#mktPoolDepth")).to_have_text("—")
    expect(page.locator("#mktArbGap")).to_have_text("RED")
    expect(page.locator("#mktArbSub")).to_have_text("stale provider evidence")
    expect(page.locator("#marketTrustedRange")).to_have_text("No tradable range")
    expect(page.locator("#marketProviderHealth")).to_contain_text(
        "dexie stale (evidence expired)"
    )


def test_dashboard_renders_attributable_confidence_depth(page):
    """A coherent confidence snapshot drives trusted range and independent depth."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    rendered = page.evaluate(
        """() => {
            window.renderMarketConfidence({
                confidence: {
                    state: 'GREEN',
                    trusted_bid: '0.00007343',
                    trusted_ask: '0.00007860',
                    reason_codes: [],
                },
                metrics: {
                    independent_bid_depth_xch: 12.25,
                    independent_ask_depth_xch: 9.75,
                    required_depth_xch: 2,
                },
                evidence: { source_ids: ['dexie', 'splash'] },
                providers: {
                    dexie: { status: 'fresh', reason_codes: [] },
                    splash: { status: 'fresh', reason_codes: [] },
                },
            });
            return {
                depth: document.getElementById('mktPoolDepth').textContent,
                bidDepth: document.getElementById('mktDexieDepth').textContent,
                askDepth: document.getElementById('mktAskDepth').textContent,
                confidence: document.getElementById('mktArbGap').textContent,
                range: document.getElementById('marketTrustedRange').textContent,
            };
        }"""
    )

    assert rendered == {
        "depth": "22.00 XCH",
        "bidDepth": "Bid: 12.25 XCH",
        "askDepth": "Ask: 9.75 XCH",
        "confidence": "GREEN",
        "range": "0.00007343 – 0.00007860 XCH",
    }


def test_dashboard_market_health_uses_authoritative_confidence_snapshot(page):
    """Health cards must use the durable confidence snapshot, not legacy AMM fields."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.renderMarketConfidence({
                confidence: {
                    state: 'AMBER',
                    reason_codes: ['single_provider_evidence'],
                },
                metrics: { required_depth_xch: 1.25 },
                evidence: { source_ids: ['dexie'] },
                providers: { dexie: { status: 'fresh', reason_codes: [] } },
            });
            window.updateMarketHealth({
                status: 'amber',
                message: 'Market restricted — independent evidence is incomplete',
                conditions: [{
                    level: 'amber',
                    text: 'Only one attributable provider currently confirms the book',
                }],
                metrics: {},
            });
        }"""
    )

    expect(page.locator("#ccHealthMsg")).to_have_text(
        "Market restricted — independent evidence is incomplete"
    )
    expect(page.locator("#ccArbGap")).to_have_text("AMBER")
    expect(page.locator("#ccPoolDepth")).to_have_text("1.2500 XCH / side")
    expect(page.locator("#ccConditions")).to_contain_text(
        "Only one attributable provider currently confirms the book"
    )


def test_dashboard_health_cannot_claim_healthy_when_authoritative_confidence_is_red(
    page,
):
    """The legacy health card must not contradict the durable RED safety truth."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            window.renderMarketConfidence({
                confidence: {
                    state: 'RED',
                    reason_codes: ['market_evidence_expired'],
                    withdrawal_stage: 'ALL',
                },
                degraded: { withdrawal_stage: 'ALL' },
                metrics: {},
                evidence: { source_ids: ['dexie', 'splash'] },
                providers: {},
            });
            window.updateMarketHealth({
                status: 'green',
                message: 'Market conditions healthy — bot stopped',
                conditions: [],
                metrics: {},
            });
        }"""
    )

    expect(page.locator("#ccHealthDot")).to_have_class(re.compile(r"cc-light-red"))
    expect(page.locator("#ccHealthMsg")).to_have_text(
        "Market blocked — offer-book confidence is RED"
    )
    expect(page.locator("#ccConditions")).to_contain_text("market evidence expired")


def test_late_red_confidence_refreshes_an_already_rendered_green_health_card(page):
    """Confidence arriving after dashboard data must immediately reconcile the card."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            _dashboardData = {
                market_health: {
                    status: 'green',
                    message: 'Market conditions healthy — bot stopped',
                    conditions: [],
                    metrics: {},
                },
            };
            window.updateMarketHealth(_dashboardData.market_health);
            window.renderMarketConfidence({
                confidence: {
                    state: 'RED',
                    reason_codes: ['market_evidence_expired'],
                    withdrawal_stage: 'ALL',
                },
                degraded: { withdrawal_stage: 'ALL' },
                metrics: {},
                evidence: { source_ids: ['dexie', 'splash'] },
                providers: {},
            });
        }"""
    )

    expect(page.locator("#ccHealthDot")).to_have_class(re.compile(r"cc-light-red"))
    expect(page.locator("#ccHealthMsg")).to_have_text(
        "Market blocked — offer-book confidence is RED"
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
            apiFetch = async (url) => new Response(JSON.stringify(
                String(url).includes('/market/confidence')
                    ? {
                        confidence: {
                            state: 'GREEN',
                            trusted_bid: '0.0000672337521645723',
                            trusted_ask: '0.0000679213506120472',
                            reason_codes: [],
                        },
                        metrics: {
                            independent_bid_depth_xch: 8,
                            independent_ask_depth_xch: 7,
                        },
                        evidence: { source_ids: ['dexie', 'splash'] },
                        providers: {},
                    }
                    : {
                        has_data: true,
                        best_bid: 0.0000672337521645723,
                        best_ask: 0.0000679213506120472,
                        volume_24h: 0.242291699794,
                        mid_price: 0.0000675775515,
                    }
            ), { status: 200 });

            await fetchMarketSummary();
        }"""
    )

    expect(page.locator("#mktBestBid")).to_have_text("0.00006723")
    expect(page.locator("#mktBestAsk")).to_have_text("0.00006792")
    expect(page.locator("#mktVolume24h")).to_have_text("0.242")
    expect(page.locator("#mktPoolDepth")).to_have_text("15.00 XCH")
    expect(page.locator("#mktArbGap")).to_have_text("GREEN")


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


def test_sparse_market_intel_sse_preserves_dashboard_competitor_count(page):
    """A sparse live orderbook push must not replace known competitors with zero."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """() => {
            const health = {
                status: 'green',
                message: 'Market healthy',
                conditions: [],
                metrics: {
                    market_intel_state: 'ready',
                    competitor_count: 7,
                    competitor_sides: 'both',
                    market_spread_bps: '320',
                },
            };
            _dashboardData = { settings: {}, performance: {}, market_health: health };
            _lcDashboardData = { settings: {}, performance: {}, market_health: health };
            updateMarketHealth(health);

            // This is the sparse shape emitted by the bot loop today.  It has
            // total orderbook counts but no competitor-only counts.
            handleSSEEvent({
                type: 'market_intel',
                data: {
                    best_bid: '0.00008000',
                    best_ask: '0.00008600',
                    num_buy_offers: 18,
                    num_sell_offers: 24,
                },
            });

            return {
                count: _lcDashboardData.market_health.metrics.competitor_count,
                sides: _lcDashboardData.market_health.metrics.competitor_sides,
                text: document.getElementById('ccCompetitors').textContent,
            };
        }"""
    )

    assert result == {"count": 7, "sides": "both", "text": "7 (both)"}


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


@pytest.mark.parametrize(
    "failure, detail",
    [
        (
            {
                "success": False,
                "error": "coin_prep_mutation_exclusion_unavailable",
                "reason": "WALLET_IDENTITY_BINDING_INVALID",
            },
            "WALLET_IDENTITY_BINDING_INVALID",
        ),
        (
            {
                "success": False,
                "error": "authoritative_state_conflict",
                "conflicts": ["offer_proof_history"],
            },
            "without resetting history",
        ),
    ],
)
def test_coin_prep_rejected_start_shows_persistent_error_not_checking(
    page, failure, detail
):
    """A rejected trigger must not leave the checklist checking or lose its reason."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """async (failure) => {
            bot_state = { running: false, offers: { buy: [], sell: [] } };
            coinPrepStatus = 'checking';
            document.getElementById('coinPrepConfirmOverlay').classList.add('active');
            showCoinPrepView('confirm');
            askPrepHistoryChoice = async () => ({
                action: 'proceed', resets: { pnl: false, offers: true, counters: true },
            });
            apiFetch = async () => new Response(JSON.stringify(failure), {
                status: 423, headers: { 'Content-Type': 'application/json' },
            });
            await startCoinPrepFromModal();
        }""",
        failure,
    )

    expect(page.locator("#coinPrepErrorView")).to_be_visible()
    expect(page.locator("#cpErrorDetail")).to_contain_text(detail)
    assert page.evaluate("coinPrepStatus") == "error"
    assert page.evaluate("coinPrepPollInterval") is None


def test_reload_restores_completed_coin_prep_for_same_asset_only(page):
    """A fresh window must not forget valid prep or apply it to another CAT."""

    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            settingsReviewed = true;
            currentCAT = { asset_id: 'asset-a', wallet_id: 2 };
            coinPrepStatus = 'none';
            apiFetch = async () => new Response(JSON.stringify({
                success: true,
                complete: true,
                previously_complete: true,
                needs_coin_prep: false,
                last_prep_settings: { cat_asset_id: 'asset-a' },
            }), { status: 200, headers: { 'Content-Type': 'application/json' } });
            const sameAsset = await restoreCoinPrepReadiness();
            const restoredStatus = coinPrepStatus;

            coinPrepStatus = 'none';
            currentCAT = { asset_id: 'asset-b', wallet_id: 3 };
            const otherAsset = await restoreCoinPrepReadiness();
            return { sameAsset, restoredStatus, otherAsset, finalStatus: coinPrepStatus };
        }"""
    )

    assert result == {
        "sameAsset": True,
        "restoredStatus": "done",
        "otherAsset": False,
        "finalStatus": "none",
    }


def test_manual_cat_refresh_preserves_selected_pair_and_setup_state(page):
    """Refreshing the active wallet's CAT list must not discard its live selection."""

    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            const assetId = 'ab'.repeat(32);
            const cat = {
                asset_id: assetId,
                wallet_id: 2,
                ticker_id: 'MZ_XCH',
                name: 'Monkeyzoo Token',
                category: 'ready',
                decimals: 3,
            };
            const selector = document.getElementById('catSelector');
            selector.innerHTML = `<option value="${assetId}" data-wallet="2" selected>MZ</option>`;
            currentCAT = { ...cat };
            _pairSelectedByUser = true;
            settingsReviewed = true;
            coinPrepStatus = 'done';

            apiFetch = async (path) => {
                const url = String(path);
                if (url.includes('/cat/refresh')) {
                    return new Response(JSON.stringify({ success: true }), {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' },
                    });
                }
                if (url.endsWith('/cats')) {
                    return new Response(JSON.stringify({ cats: [cat] }), {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' },
                    });
                }
                if (url.endsWith('/status')) {
                    return new Response(JSON.stringify({
                        running: false,
                        current_cat: cat,
                    }), {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' },
                    });
                }
                throw new Error(`Unexpected test request: ${url}`);
            };
            refreshBalances = async () => {};
            fetchStatus = async () => {};
            updateFingerprint = async () => {};

            await refreshCATs(true);
            return {
                selectedAssetId: selector.value,
                currentAssetId: currentCAT.asset_id || '',
                pairSelectedByUser: _pairSelectedByUser,
                settingsReviewed,
                coinPrepStatus,
            };
        }"""
    )

    assert result == {
        "selectedAssetId": "ab" * 32,
        "currentAssetId": "ab" * 32,
        "pairSelectedByUser": True,
        "settingsReviewed": True,
        "coinPrepStatus": "done",
    }


def test_final_startup_dismiss_keeps_start_disabled_without_verified_prep(page):
    """Completing the startup overlay must not bypass Coin Prep readiness."""

    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.clock.install()
    page.goto(gui.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """() => {
            const assetId = 'ab'.repeat(32);
            settingsReviewed = true;
            localStorage.setItem('settingsReviewed', 'true');
            localStorage.setItem('settingsReviewedAssetId', assetId);
            currentCAT = { asset_id: assetId, wallet_id: 2 };
            _pairSelectedByUser = true;
            coinPrepStatus = 'none';
            _resumeHandled = true;
            hasCheckedResumeOnLoad = true;
            bot_state = {
                running: false,
                runtime_safety: {
                    allowed: true,
                    reason_code: '',
                    lease: { active: true, owned_by_this_run: true },
                    recovery: { freshness: {
                        valid: true,
                        age_seconds: 0,
                        max_age_seconds: 30,
                        provenance: 'live_gate_and_durable_snapshot',
                        observed_at_utc: new Date().toISOString(),
                    } },
                },
            };
            updateFingerprint = async () => {};
            fetchFingerprint = async () => {};
            fetchDashboard = async () => {};
            fetchStatus = async () => {};
            loadCATs = async () => {};
            showStartupLaunchBar = () => {};
            restoreCoinPrepReadiness = async () => false;
            finalDismiss();
        }"""
    )
    page.clock.fast_forward(400)
    expect(page.locator("#startBtn")).to_be_disabled()


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
                    : {
                        success: true,
                        message: 'Coin preparation started',
                        wallet_offer_book_verified_empty: true,
                      };
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


def test_coin_prep_keeps_waiting_while_terminal_proof_propagates(page):
    """A temporarily empty Sage book must not abort automatic reconciliation."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            let triggerCalls = 0;
            document.getElementById('coinPrepConfirmOverlay').classList.add('active');
            apiFetch = async (path) => {
                if (!String(path).includes('/coin-prep/trigger')) {
                    return new Response(JSON.stringify({ success: true }), {
                        status: 200,
                        headers: { 'Content-Type': 'application/json' },
                    });
                }
                triggerCalls += 1;
                const body = triggerCalls === 1
                    ? {
                        success: false,
                        error: 'coin_prep_offer_reconciliation_pending',
                        action: 'retry_authoritative_reconciliation',
                        message: 'Sage currently shows no live offers while proof propagates.',
                        open_offer_count: 2,
                      }
                    : {
                        success: true,
                        message: 'Coin preparation started',
                        wallet_offer_book_verified_empty: true,
                      };
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
            return { started, triggerCalls };
        }"""
    )

    assert result["started"] is True
    assert result["triggerCalls"] == 2
    expect(page.locator("#coinPrepProgressView")).to_be_visible()


def test_coin_prep_recovery_rejects_unverified_success_response(page):
    """The browser must not equate a generic 200 with wallet-wide terminal proof."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            document.getElementById('coinPrepConfirmOverlay').classList.add('active');
            apiFetch = async () => new Response(JSON.stringify({
                success: true,
                message: 'Coin preparation started',
            }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            });
            const started = await resumeCoinPrepAfterCancelledOffers({
                source: 'coin_prep',
                prepPayload: {
                    coin_multiplier: 1,
                    reset_pnl: false,
                    reset_offer_history: false,
                    reset_counters: false,
                },
            }, { retryDelayMs: 0, timeoutMs: 10 });
            return {
                started,
                progressVisible: getComputedStyle(
                    document.getElementById('coinPrepProgressView')
                ).display !== 'none',
            };
        }"""
    )

    assert result["started"] is False
    assert result["progressVisible"] is False


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
                    } : {
                        success: true,
                        message: 'Coin preparation started',
                        wallet_offer_book_verified_empty: true,
                    }), {
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


def test_reload_restores_active_cancel_all_progress_before_resume_prompt(page):
    """A fresh window must surface the durable cancel instead of offering Resume."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            document.getElementById('resumeSessionModal').classList.add('active');
            document.getElementById('cancelProgressModal').classList.remove('active');
            _cancelAllInProgress = false;
            _cancelAllLastState = null;
            apiFetch = async (path) => {
                if (!String(path).includes('/offers/cancel_all/status')) {
                    throw new Error(`Unexpected test request: ${path}`);
                }
                return new Response(JSON.stringify({
                    success: true,
                    running: true,
                    complete: false,
                    phase: 'reconciling',
                    total: 72,
                    cancelled: 11,
                    confirmed: 11,
                    pending: 61,
                    failed: 0,
                    message: 'Waiting for authoritative cancellation proof: 11/72 offers terminal.',
                }), { status: 200, headers: { 'Content-Type': 'application/json' } });
            };

            if (typeof restoreActiveCancelAllProgress !== 'function') {
                return { restored: false };
            }
            const restored = await restoreActiveCancelAllProgress();
            const snapshot = {
                restored,
                inProgress: _cancelAllInProgress,
                progressVisible: document.getElementById('cancelProgressModal').classList.contains('active'),
                resumeVisible: document.getElementById('resumeSessionModal').classList.contains('active'),
                summary: document.getElementById('cancelProgressSummary').textContent,
            };
            stopCancelAllProgressPolling();
            clearCancelAllCompletionTimers();
            return snapshot;
        }"""
    )

    assert result == {
        "restored": True,
        "inProgress": True,
        "progressVisible": True,
        "resumeVisible": False,
        "summary": "11 of 72 offers processed",
    }


def test_cancel_all_completion_clears_stale_resume_dashboard(page):
    """An empty authoritative wallet book must leave session-recovery mode."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            _resumeSessionSummary = {
                pair_name: 'Monkeyzoo Token',
                buy_count: 36,
                sell_count: 36,
                offer_count: 72,
                active_cat: { asset_id: 'mz', name: 'Monkeyzoo Token', ticker_id: 'MZ_XCH' },
            };
            bot_state = { running: false, offers: { buy: [], sell: [] } };
            _cancelAllInProgress = true;
            _cancelAllOperationGeneration = 4;
            addLogEntry = () => {};
            apiFetch = async () => new Response(JSON.stringify({
                success: true,
                running: false,
                complete: true,
                phase: 'complete',
                total: 72,
                cancelled: 72,
                confirmed: 72,
                pending: 0,
                failed: 0,
            }), { status: 200, headers: { 'Content-Type': 'application/json' } });

            await pollCancelAllProgressOnce(72, 4);
            updateDashboardStartupLayout(bot_state);
            return {
                summaryCleared: _resumeSessionSummary === null,
                kicker: document.getElementById('startupGuideKicker').textContent,
                title: document.getElementById('startupGuideTitle').textContent,
            };
        }"""
    )

    assert result == {
        "summaryCleared": True,
        "kicker": "Quick Start",
        "title": "Set up this trading pair before you start the bot",
    }


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


def test_status_refresh_discards_older_response_that_finishes_last(page):
    """A slow pre-cancel status response must not restore cancelled offers."""
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            const pending = [];
            const appliedOfferCounts = [];
            apiFetch = () => new Promise(resolve => pending.push(resolve));
            updateUI = data => appliedOfferCounts.push(
                (data.offers?.buy?.length || 0) + (data.offers?.sell?.length || 0)
            );
            syncCommandCentreFromStatus = () => {};
            updateWalletPickerAvailability = () => {};

            const staleRequest = fetchStatus();
            await Promise.resolve();
            const currentRequest = fetchStatus();
            await Promise.resolve();

            pending[1](new Response(JSON.stringify({
                running: false,
                offers: { buy: [], sell: [] },
            }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
            await currentRequest;

            pending[0](new Response(JSON.stringify({
                running: false,
                offers: {
                    buy: Array.from({ length: 36 }, (_, i) => ({ trade_id: `buy-${i}` })),
                    sell: Array.from({ length: 36 }, (_, i) => ({ trade_id: `sell-${i}` })),
                },
            }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
            await staleRequest;

            return {
                finalOfferCount: (bot_state.offers?.buy?.length || 0)
                    + (bot_state.offers?.sell?.length || 0),
                appliedOfferCounts,
            };
        }"""
    )

    assert result == {"finalOfferCount": 0, "appliedOfferCounts": [0]}


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
