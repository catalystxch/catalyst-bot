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
                    proposed_maximum_fee_mojos: 5000000000,
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
                return {success: true, total_fee_mojos: 5000000000,
                    dispatch_authorized: false};
            },
        }};
        openPrestartFollowFeeReview();
        await preparePrestartFollowFeeReview();
    }""")
    output = page.locator("#prestartFollowFeeText")
    expect(output).to_contain_text("Original cumulative ceiling: 0.004059096837 XCH")
    expect(output).to_contain_text("New cumulative ceiling: 0.005 XCH")
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
