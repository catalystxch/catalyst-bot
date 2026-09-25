"""Cancellation-only fee recovery must never launch fresh Coin Prep."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .test_coin_prep_fee_approval import _open_gui, _preview


pytestmark = pytest.mark.e2e


def test_cancel_fee_review_confirmation_does_not_dispatch_coin_prep(page):
    """Exercise the real confirmation button after a cancellation cap refusal."""
    _open_gui(page)
    preview = _preview()
    preview["wallet"]["campaign_id"] = "e" * 64
    page.evaluate(
        """async preview => {
            document.getElementById('startupOverlay').style.display = 'none';
            bot_state = {running: false, offers: {buy: [{}], sell: [{}]}};
            _bootstrapActiveCampaign = {
                campaign_id: preview.wallet.campaign_id,
                revision: 1, status: 'active', stage: 'stopped',
            };
            window.__feeCalls = [];
            window.apiFetch = async (path, options = {}) => {
                const url = String(path);
                window.__feeCalls.push({path: url, body: options.body || null});
                let data;
                if (url.includes('/coin-prep/fee-preview')) {
                    data = preview;
                } else if (url.includes('/coin-prep/fee-approval')) {
                    data = {success: true, approval_id: 'd'.repeat(64)};
                } else if (url.includes('/coin-prep/trigger')) {
                    // Model the backend guard; observing this request is the bug.
                    data = {success: false, error: 'FEE_CAMPAIGN_BUDGET_EXCEEDED'};
                } else {
                    throw new Error(`Unexpected test request: ${url}`);
                }
                return new Response(JSON.stringify(data), {
                    status: 200, headers: {'Content-Type': 'application/json'},
                });
            };
            askPrepHistoryChoice = async () => ({action: 'proceed', resets: {}});
            await reviewCancelAllFeeBudgetFailure({
                reason_code: 'FEE_CAMPAIGN_BUDGET_EXCEEDED',
            });
        }""",
        preview,
    )
    expect(page.locator("#cpReasonBanner")).to_contain_text("before cancellation")
    expect(page.locator("#cpConfirmBtn")).to_be_enabled()
    page.locator("#cpConfirmBtn").click()
    page.wait_for_function("() => !_coinPrepFeeConfirmBusy")

    calls = page.evaluate("window.__feeCalls")
    approvals = [call for call in calls if "/coin-prep/fee-approval" in call["path"]]
    assert len(approvals) == 1
    assert not [call for call in calls if "/coin-prep/trigger" in call["path"]], (
        "Approving a cancellation recovery budget must not request new Coin Prep"
    )
    assert not page.evaluate(
        "document.getElementById('coinPrepConfirmOverlay').classList.contains('active')"
    )
    assert page.evaluate(
        "document.getElementById('cancelConfirmModal').classList.contains('active')"
    )
    expect(page.locator("#cancelAllConfirmBtn")).to_have_text("Cancel Offers")
