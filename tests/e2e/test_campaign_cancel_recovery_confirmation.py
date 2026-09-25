"""The second cancellation confirmation retains consent without starting prep."""

import json

import pytest
from playwright.sync_api import expect

from .test_coin_prep_fee_approval import _open_gui, _preview


pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("action", ["confirm", "keep_offers", "approval_refused"])
def test_recovery_confirmation_keeps_cancel_only_intent(page, action):
    _open_gui(page)
    preview = _preview()
    preview["wallet"]["campaign_id"] = "e" * 64
    page.evaluate(
        """async ({preview, action}) => {
            document.getElementById('startupOverlay').style.display = 'none';
            bot_state = {running: false, offers: {buy: [{}], sell: [{}]}};
            _bootstrapActiveCampaign = {
                campaign_id: preview.wallet.campaign_id,
                revision: 2, status: 'stopped', stage: 'stopped',
            };
            window.__recoveryCalls = [];
            window.__historyPrompts = 0;
            askPrepHistoryChoice = async () => {
                window.__historyPrompts++;
                throw new Error('Cancellation recovery must not reset prep history');
            };
            fetchStatus = async () => {};
            updateResumeOverview = () => {};
            window.apiFetch = async (path, options = {}) => {
                const url = String(path);
                window.__recoveryCalls.push({path: url, body: options.body || null});
                let data;
                let status = 200;
                if (url.includes('/coin-prep/fee-preview')) {
                    data = preview;
                } else if (url.includes('/coin-prep/fee-approval')) {
                    data = action === 'approval_refused'
                        ? {success: false, reason: 'FEE_BUDGET_EXCEEDED'}
                        : {success: true, approval_id: 'd'.repeat(64)};
                    status = action === 'approval_refused' ? 409 : 200;
                } else if (url.includes('/offers/cancel_all/status')) {
                    data = {success: true, running: false, complete: true,
                            phase: 'complete', total: 2, cancelled: 2,
                            confirmed_cancelled: 2, pending: 0, failed: 0};
                } else if (url.endsWith('/offers/cancel_all')) {
                    data = {success: true, async: true, total: 2, timeout_seconds: 180};
                } else {
                    throw new Error(`Unexpected recovery request: ${url}`);
                }
                return new Response(JSON.stringify(data), {
                    status, headers: {'Content-Type': 'application/json'},
                });
            };
            await reviewCancelAllFeeBudgetFailure({
                reason_code: 'FEE_CAMPAIGN_BUDGET_EXCEEDED',
                total: 2, buy_count: 1, sell_count: 1,
            });
        }""",
        {"preview": preview, "action": action},
    )
    page.locator("#cpConfirmBtn").click()
    page.wait_for_function("() => !_coinPrepFeeConfirmBusy")
    if action == "approval_refused":
        expect(page.locator("#coinPrepConfirmOverlay")).to_have_class("coin-prep-overlay active")
        expect(page.locator("#cancelConfirmModal")).not_to_have_class("modal active")
    else:
        expect(page.locator("#cancelAllConfirmBtn")).to_be_visible()
        # Approval itself must not send the cancellation effect.
        assert not page.evaluate(
            "window.__recoveryCalls.some(c => c.path.endsWith('/offers/cancel_all'))"
        )
        if action == "keep_offers":
            page.locator("#cancelConfirmModal").get_by_role("button", name="Keep Offers").click()
        else:
            page.locator("#cancelAllConfirmBtn").click()
            page.wait_for_function("() => !_cancelAllInProgress", timeout=10000)

    calls = page.evaluate("window.__recoveryCalls")
    approvals = [call for call in calls if "/coin-prep/fee-approval" in call["path"]]
    cancellations = [call for call in calls if call["path"].endswith("/offers/cancel_all")]
    assert len(approvals) == 1
    assert len(cancellations) == (1 if action == "confirm" else 0)
    if cancellations:
        assert json.loads(cancellations[0]["body"]) == {
            "source": "coin_prep", "fee_approval_id": "d" * 64,
        }
    assert not [call for call in calls if "/coin-prep/trigger" in call["path"]]
    assert page.evaluate("window.__historyPrompts") == 0
