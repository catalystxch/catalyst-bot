"""A stopped Bootstrap campaign must retain targeted fee-renewal recovery."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from .test_coin_prep_fee_approval import _open_gui, _preview


pytestmark = pytest.mark.e2e


def test_stale_bootstrap_stop_approval_renews_then_retries_only_campaign(page):
    _open_gui(page)
    preview = _preview()
    campaign_id = "e" * 64
    preview["wallet"]["campaign_id"] = campaign_id
    page.evaluate(
        """({preview, campaignId}) => {
            document.getElementById('startupOverlay').style.display = 'none';
            _bootstrapActiveCampaign = {
                campaign_id: campaignId, revision: 0, status: 'active', stage: 'bootstrap',
            };
            window.__recoveryCalls = [];
            window.__stopAttempts = 0;
            window.__historyChoiceCalls = 0;
            showStyledConfirm = async () => true;
            askPrepHistoryChoice = async () => {
                window.__historyChoiceCalls++;
                return {action: 'proceed', resets: {}};
            };
            bootstrapRefreshStatus = async () => {};
            window.apiFetch = async (path, options = {}) => {
                const url = String(path);
                const body = options.body ? JSON.parse(options.body) : null;
                window.__recoveryCalls.push({path: url, body});
                let data;
                let status = 200;
                if (url.endsWith('/api/bootstrap/stop')) {
                    window.__stopAttempts++;
                    if (window.__stopAttempts === 1) {
                        status = 409;
                        data = {
                            success: false, code: 'FEE_APPROVAL_STALE',
                            error: 'FEE_APPROVAL_STALE', stopped: true,
                            campaign_id: campaignId, campaign_revision: 1,
                            cancel_targets: 3, financial_action_started: false,
                        };
                    } else {
                        data = {success: true, stopped: true, cancel_targets: 3};
                    }
                } else if (url.includes('/coin-prep/fee-preview')) {
                    data = preview;
                } else if (url.includes('/coin-prep/fee-approval')) {
                    data = {success: true, approval_id: 'd'.repeat(64)};
                } else {
                    throw new Error(`Unexpected request: ${url}`);
                }
                return new Response(JSON.stringify(data), {
                    status, headers: {'Content-Type': 'application/json'},
                });
            };
        }""",
        {"preview": preview, "campaignId": campaign_id},
    )

    page.evaluate("bootstrapStopCampaign()")
    expect(page.locator("#coinPrepConfirmOverlay")).to_have_class(
        "coin-prep-overlay active"
    )
    expect(page.locator("#cpReasonBanner")).to_contain_text("expired")
    expect(page.locator("#cpConfirmBtn")).to_be_enabled()
    page.locator("#cpConfirmBtn").click()
    page.wait_for_function("() => !_coinPrepFeeConfirmBusy")

    calls = page.evaluate("window.__recoveryCalls")
    stops = [call for call in calls if call["path"].endswith("/api/bootstrap/stop")]
    assert len(stops) == 2
    assert stops[0]["body"] == {"campaign_id": campaign_id, "revision": 0}
    assert stops[1]["body"] == {
        "campaign_id": campaign_id,
        "revision": 1,
        "fee_approval_id": "d" * 64,
    }
    previews = [call for call in calls if "/coin-prep/fee-preview" in call["path"]]
    assert len(previews) == 1
    assert previews[0]["body"]["bootstrap_campaign_id"] == campaign_id
    assert previews[0]["body"]["bootstrap_campaign_revision"] == 1
    assert not [call for call in calls if "/offers/cancel_all" in call["path"]]
    assert not [call for call in calls if "/coin-prep/trigger" in call["path"]]
    assert page.evaluate("window.__historyChoiceCalls") == 0
