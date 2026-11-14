"""Read-only browser proof for the native Follow fee ceiling review."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_active_run_review_shows_exact_ledger_and_invalidates_changed_ceiling(page):
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
        window.__confirmCalls = [];
        window.pywebview = {api: {
            prepare_follow_fee_ceiling_review: async () => ({
                success: true, dispatch_authorized: false, consumed: false,
                review_id: 'a'.repeat(64), review_sha256: 'b'.repeat(64),
                run_id: 'c'.repeat(64), prior_revision: 2,
                expires_at_epoch: Math.floor(Date.now() / 1000) + 120,
                run_stopped: false,
                prior_maximum_fee_mojos: 5000000000,
                proposed_maximum_fee_mojos: 6000000000,
                reviewed_spent_fee_mojos: 1250000000,
                reviewed_held_fee_mojos: 250000000,
                protected_shutdown_fee_mojos: 300000000,
                observed_fee_principal_mojos: 7000000000,
                identity: {wallet_fingerprint: 736588221, network: 'mainnet',
                    asset_id: 'asset', ticker: '<img src=x onerror=window.__injected=true>'},
            }),
            confirm_follow_fee_ceiling_review: async request => {
                window.__confirmCalls.push(request);
                return {success: true, dispatch_authorized: false,
                    run_id: 'c'.repeat(64), maximum_fee_mojos: 6000000000};
            },
        }};
        openFollowFeeCeilingReview();
        document.getElementById('followFeeCeilingProposedXch').value = '0.006';
        await prepareFollowFeeCeilingReview();
    }""")

    output = page.locator("#followFeeCeilingReviewText")
    expect(output).to_contain_text("Wallet 736588221 · mainnet")
    expect(output).to_contain_text("State at review: active")
    expect(output).to_contain_text("Current cumulative ceiling: 0.005 XCH")
    expect(output).to_contain_text("New cumulative ceiling: 0.006 XCH")
    expect(output).to_contain_text("Already spent: 0.00125 XCH")
    expect(output).to_contain_text("Pending fee holds: 0.00025 XCH")
    expect(output).to_contain_text("<img src=x")
    assert page.evaluate("window.__injected === undefined")
    expect(page.locator("#followFeeCeilingReviewConfirm")).to_be_disabled()
    page.locator("#followFeeCeilingReviewAccept").check()
    expect(page.locator("#followFeeCeilingReviewConfirm")).to_be_enabled()
    page.locator("#followFeeCeilingProposedXch").fill("0.007")
    expect(page.locator("#followFeeCeilingReviewConfirm")).to_be_disabled()
    assert page.evaluate("window.__confirmCalls") == []
