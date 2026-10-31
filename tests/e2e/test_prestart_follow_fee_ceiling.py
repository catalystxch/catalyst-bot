"""Native pre-start review displays exact accounting and records no Start."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_completed_session_prestart_review_is_native_and_single_use(page):
    page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith("file:")
            else route.abort()
        ),
    )
    page.goto(
        (Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri(),
        wait_until="domcontentloaded",
    )
    page.evaluate("""async () => {
        document.querySelectorAll('.modal.active, #startupOverlay, #splashGateOverlay, #spacescanGateOverlay').forEach(e => e.style.display='none');
        IS_DESKTOP = true;
        window.__prestartCalls = [];
        window.__started = false;
        window.pywebview = {api: {
            get_coin_prep_status: async () => ({
                success: true, fee_approval_id: 'a'.repeat(64),
                fee_approval: {session_completed: true, total_fee_mojos: 4059096837},
            }),
            prepare_prestart_follow_fee_ceiling_review: async body => {
                window.__prestartCalls.push(['prepare', body]);
                return {
                    success: true, preview_id: 'b'.repeat(64), review_sha256: 'c'.repeat(64),
                    prior_approval_id: 'a'.repeat(64),
                    prior_maximum_fee_mojos: 4059096837,
                    proposed_maximum_fee_mojos: body.proposed_maximum_fee_mojos,
                    spent_fee_mojos: 774766315, held_fee_mojos: 0,
                    protected_cancellation_fee_mojos: 1037763168,
                    fee_funding_mojos: 10000000000,
                    expires_at: Math.floor(Date.now()/1000)+50,
                    wallet: {wallet_type: 'sage', network: 'mainnet',
                        wallet_fingerprint: 3702373391, ticker: '<img src=x onerror=window.__started=true>',
                        asset_id: 'd'.repeat(64), session_id: 'e'.repeat(64)},
                    dispatch_authorized: false,
                };
            },
            confirm_prestart_follow_fee_ceiling_review: async body => {
                window.__prestartCalls.push(['confirm', body]);
                return {success: true, total_fee_mojos: 10000000000,
                    dispatch_authorized: false};
            },
        }};
        openPrestartFollowFeeReview();
    }""")
    amount = page.locator("#prestartFollowFeeXch")
    expect(amount).to_be_editable()
    amount.fill("0.01")
    page.evaluate("preparePrestartFollowFeeReview()")
    output = page.locator("#prestartFollowFeeText")
    expect(output).to_contain_text("Original cumulative ceiling: 0.004059096837 XCH")
    expect(output).to_contain_text("New cumulative ceiling: 0.01 XCH")
    assert (
        page.evaluate("window.__prestartCalls[0][1].proposed_maximum_fee_mojos")
        == 10_000_000_000
    )
    expect(output).to_contain_text("Already spent: 0.000774766315 XCH")
    expect(output).to_contain_text("Pending fee holds: 0.0 XCH")
    expect(output).to_contain_text("Protected cancellation reserve: 0.001037763168 XCH")
    expect(output).to_contain_text("<img src=x")
    assert page.evaluate("window.__started === false")
    expect(page.locator("#prestartFollowFeeConfirm")).to_be_disabled()
    page.locator("#prestartFollowFeeAccept").check()
    expect(page.locator("#prestartFollowFeeConfirm")).to_be_enabled()
    page.evaluate("""() => {
        const input = document.getElementById('prestartFollowFeeXch');
        input.value = '0.006';
        input.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    expect(page.locator("#prestartFollowFeeConfirm")).to_be_disabled()
    assert len(page.evaluate("window.__prestartCalls")) == 1
    amount.fill("0.01")
    page.evaluate("preparePrestartFollowFeeReview()")
    page.locator("#prestartFollowFeeAccept").check()
    page.locator("#prestartFollowFeeConfirm").click()
    expect(page.locator("#followRunFeeCapXch")).to_have_value("0.01")
    assert page.evaluate("window.__started === false")


def test_follow_refresh_uses_new_ceiling_while_worker_approval_stays_historical(page):
    page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith("file:")
            else route.abort()
        ),
    )
    page.goto(
        (Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri(),
        wait_until="domcontentloaded",
    )
    request = page.evaluate("""async () => {
        document.querySelectorAll('.modal.active, #startupOverlay, #splashGateOverlay, #spacescanGateOverlay').forEach(e => e.style.display='none');
        IS_DESKTOP = true;
        window.__followRequest = null;
        window.pywebview = {api: {
            get_coin_prep_status: async () => ({
                success: true, fee_approval_id: 'a'.repeat(64),
                fee_approval: {session_completed: true, total_fee_mojos: 4059096837},
                follow_fee_approval_id: 'b'.repeat(64),
                follow_fee_approval: {session_completed: true, total_fee_mojos: 5000000000},
            }),
            confirm_follow_run_review: async () => ({success:false}),
            prepare_follow_run_review: async body => {
                window.__followRequest = body;
                return {success:false, reason:'TEST_STOP'};
            },
        }};
        openFollowRunReview();
        await prepareFollowRunReview();
        return window.__followRequest;
    }""")
    assert request["approval_id"] == "b" * 64
    assert request["maximum_fee_mojos"] == 5_000_000_000
    assert request["buy_limit"] == request["sell_limit"] == 24


def test_follow_review_uses_current_approved_ceiling_instead_of_stale_default(page):
    page.route(
        "**/*",
        lambda route: route.continue_()
        if route.request.url.startswith("file:")
        else route.abort(),
    )
    page.goto(
        (Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri(),
        wait_until="domcontentloaded",
    )
    request = page.evaluate("""async () => {
        document.querySelectorAll('.modal.active, #startupOverlay, #splashGateOverlay, #spacescanGateOverlay').forEach(e => e.style.display='none');
        IS_DESKTOP = true;
        window.__followRequest = null;
        window.pywebview = {api: {
            get_coin_prep_status: async () => ({
                success: true, follow_fee_approval_id: 'a'.repeat(64),
                follow_fee_approval: {total_fee_mojos: 50000000000},
            }),
            confirm_follow_run_review: async () => ({success: false}),
            prepare_follow_run_review: async body => {
                window.__followRequest = body;
                return {success: false, reason: 'TEST_STOP'};
            },
        }};
        openFollowRunReview();
        await prepareFollowRunReview();
        return window.__followRequest;
    }""")
    assert request["maximum_fee_mojos"] == 50_000_000_000
    expect(page.locator("#followRunFeeCapXch")).to_have_value("0.05")


def test_follow_review_preserves_an_explicit_fee_edit(page):
    page.route(
        "**/*",
        lambda route: route.continue_()
        if route.request.url.startswith("file:")
        else route.abort(),
    )
    page.goto(
        (Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri(),
        wait_until="domcontentloaded",
    )
    result = page.evaluate("""async () => {
        document.querySelectorAll('.modal.active, #startupOverlay, #splashGateOverlay, #spacescanGateOverlay').forEach(e => e.style.display='none');
        IS_DESKTOP = true;
        window.__followRequest = null;
        window.pywebview = {api: {
            get_coin_prep_status: async () => ({
                success: true, follow_fee_approval_id: 'a'.repeat(64),
                follow_fee_approval: {total_fee_mojos: 50000000000},
            }),
            confirm_follow_run_review: async () => ({success: false}),
            prepare_follow_run_review: async body => {
                window.__followRequest = body;
                return {success: false, reason: 'TEST_STOP'};
            },
        }};
        openFollowRunReview();
        const input = document.getElementById('followRunFeeCapXch');
        input.value = '0.04';
        input.dispatchEvent(new Event('input', {bubbles: true}));
        await prepareFollowRunReview();
        return {value: input.value, request: window.__followRequest,
            message: document.getElementById('followRunReviewText').textContent};
    }""")
    assert result["value"] == "0.04"
    assert result["request"] is None
    assert "0.05 XCH" in result["message"]


def test_follow_approval_rechecks_expired_quote_at_native_confirmation(page):
    def route_local_file(route):
        if route.request.url.startswith("file:"):
            route.continue_()
        else:
            route.abort()

    page.route(
        "**/*",
        route_local_file,
    )
    page.goto(
        (Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri(),
        wait_until="domcontentloaded",
    )
    page.evaluate("""async () => {
        document.querySelectorAll('.modal.active, #startupOverlay, #splashGateOverlay, #spacescanGateOverlay').forEach(e => e.style.display='none');
        IS_DESKTOP = true;
        window.__reviewNow = Date.now();
        Date.now = () => window.__reviewNow;
        window.__nativeConfirmCalls = 0;
        window.pywebview = {api: {
            get_coin_prep_status: async () => ({
                success: true, follow_fee_approval_id: 'a'.repeat(64),
                follow_fee_approval: {total_fee_mojos: 5000000000},
            }),
            prepare_follow_run_review: async () => ({
                success: true, review_id: 'b'.repeat(64), review_sha256: 'c'.repeat(64),
                buy_limit: 24, sell_limit: 24, continuous: true,
                maximum_fee_mojos: 5000000000,
                replacement_count_gate_passed: true, current_prep_targets_proven: true,
                buy_slots_arithmetic_fit: 24, sell_slots_arithmetic_fit: 24,
                shutdown_funding: {ready: true, full_book_proven: false,
                    dispatch_authorized: false,
                    quoted_fee_mojos: 123, expires_at: Math.floor(Date.now()/1000)+1},
                review_expires_at_epoch: Math.floor(Date.now()/1000)+300,
                identity: {wallet_fingerprint: 736588221, network: 'mainnet',
                    ticker: 'MZ_XCH', asset_id: 'd'.repeat(64)},
                maximum_trade_xch_mojos: 1000000000000,
                maximum_trade_cat_atoms: 1000000,
                protected_fee_principal_mojos: 100000000000,
                cancellation_reserve_mojos: 675003900,
                largest_spendable_fee_coin_mojos: 2000000000,
            }),
            confirm_follow_run_review: async () => {
                window.__nativeConfirmCalls++;
                return {success: true, dispatch_authorized: false};
            },
        }};
        openFollowRunReview();
        await prepareFollowRunReview();
        Date.now = () => window.__reviewNow + 2000;
    }""")
    page.locator("#followRunReviewAccept").check()
    expect(page.locator("#followRunReviewConfirm")).to_be_enabled()
    page.locator("#followRunReviewConfirm").click()
    assert page.evaluate("window.__nativeConfirmCalls") == 1
