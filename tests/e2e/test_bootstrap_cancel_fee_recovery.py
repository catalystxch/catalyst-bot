"""A stopped Bootstrap campaign must retain targeted fee-renewal recovery."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from .test_coin_prep_fee_approval import _open_gui, _preview


pytestmark = pytest.mark.e2e


def test_ordinary_campaign_prep_omits_cancellation_intent(page):
    _open_gui(page)
    options = page.evaluate(
        """() => {
            _bootstrapActiveCampaign = {
                campaign_id: 'e'.repeat(64), revision: 2, status: 'active',
            };
            _coinPrepFeeRecoveryIntent = null;
            return buildCoinPrepFeePreviewOptions();
        }"""
    )
    assert options["bootstrap_campaign_id"] == "e" * 64
    assert options["bootstrap_campaign_revision"] == 2
    assert "cancellation_recovery" not in options


@pytest.mark.parametrize(
    ("recovery_reason", "reason_text"),
    [
        ("FEE_APPROVAL_STALE", "expired"),
        ("FEE_PREP_FUNDING_INSUFFICIENT", "funding"),
    ],
)
def test_bootstrap_stop_fee_recovery_renews_then_retries_only_campaign(
    page, recovery_reason, reason_text
):
    _open_gui(page)
    preview = _preview()
    campaign_id = "e" * 64
    preview["wallet"]["campaign_id"] = campaign_id
    page.evaluate(
        """({preview, campaignId, recoveryReason}) => {
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
                            success: false, code: recoveryReason,
                            error: recoveryReason, stopped: true,
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
        {
            "preview": preview,
            "campaignId": campaign_id,
            "recoveryReason": recovery_reason,
        },
    )

    page.evaluate("bootstrapStopCampaign()")
    expect(page.locator("#coinPrepConfirmOverlay")).to_have_class(
        "coin-prep-overlay active"
    )
    expect(page.locator("#cpReasonBanner")).to_contain_text(reason_text)
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
    assert previews[0]["body"]["cancellation_recovery"] is True
    assert not [call for call in calls if "/offers/cancel_all" in call["path"]]
    assert not [call for call in calls if "/coin-prep/trigger" in call["path"]]
    assert page.evaluate("window.__historyChoiceCalls") == 0


@pytest.mark.parametrize(
    ("code", "financial_action_started", "expected"),
    [
        ("bootstrap_cancel_manager_unavailable", False, "Cancellation did not start"),
        (
            "bootstrap_cancel_outcome_unknown",
            None,
            "Cancellation outcome is unresolved",
        ),
    ],
)
def test_bootstrap_stop_failure_refreshes_durable_state(
    page, code, financial_action_started, expected
):
    _open_gui(page)
    campaign_id = "e" * 64
    page.evaluate(
        """({campaignId, code, financialActionStarted}) => {
            _bootstrapActiveCampaign = {
                campaign_id: campaignId, revision: 0, status: 'active', stage: 'bootstrap',
            };
            window.__statusRefreshes = 0;
            window.__stopBodies = [];
            showStyledConfirm = async () => true;
            bootstrapRefreshStatus = async () => {
                window.__statusRefreshes++;
                _bootstrapRenderStatus({success: true, active: false, campaign: null});
            };
            window.apiFetch = async (path, options = {}) => {
                if (String(path) !== '/api/bootstrap/stop') throw new Error(String(path));
                window.__stopBodies.push(JSON.parse(options.body));
                if (window.__stopBodies.length > 1) {
                    return new Response(JSON.stringify({
                        success: true, stopped: true, cancel_targets: 3,
                    }), {status: 200, headers: {'Content-Type': 'application/json'}});
                }
                return new Response(JSON.stringify({
                    success: false, code, stopped: true,
                    campaign_id: campaignId, campaign_revision: 1,
                    cancel_targets: 3, financial_action_started: financialActionStarted,
                }), {status: financialActionStarted === false ? 409 : 503,
                    headers: {'Content-Type': 'application/json'}});
            };
        }""",
        {
            "campaignId": campaign_id,
            "code": code,
            "financialActionStarted": financial_action_started,
        },
    )
    page.evaluate("bootstrapStopCampaign()")
    assert page.evaluate("window.__statusRefreshes") == 1
    expect(page.locator("#bootstrapStatusPanel")).to_contain_text(expected)
    retry = page.locator("#bootstrapStopBtn")
    if financial_action_started is False:
        expect(retry).to_be_enabled()
        expect(retry).to_contain_text("Retry")
        expect(page.locator("#bootstrapDashboardStatus")).to_contain_text(
            "cancellation retry required"
        )
        page.evaluate("bootstrapStopCampaign()")
        assert page.evaluate("window.__stopBodies") == [
            {"campaign_id": campaign_id, "revision": 0},
            {"campaign_id": campaign_id, "revision": 1},
        ]
    else:
        expect(retry).to_be_disabled()


def test_approved_stop_retry_keeps_targeted_retry_after_no_effect(page):
    _open_gui(page)
    campaign_id = "e" * 64
    result = page.evaluate(
        """async campaignId => {
            _bootstrapPendingStopRetry = null;
            window.__statusRefreshes = 0;
            bootstrapRefreshStatus = async () => {
                window.__statusRefreshes++;
                _bootstrapRenderStatus({success: true, active: false, campaign: null});
            };
            window.apiFetch = async () => new Response(JSON.stringify({
                success: false, code: 'bootstrap_cancel_manager_unavailable',
                stopped: true, campaign_id: campaignId, campaign_revision: 2,
                financial_action_started: false,
            }), {status: 409, headers: {'Content-Type': 'application/json'}});
            try {
                await resumeBootstrapStopAfterFeeApproval(
                    {campaign_id: campaignId, campaign_revision: 1}, 'd'.repeat(64)
                );
            } catch (_) {}
            return {refreshes: window.__statusRefreshes,
                retry: _bootstrapPendingStopRetry};
        }""",
        campaign_id,
    )
    assert result == {
        "refreshes": 1,
        "retry": {"campaign_id": campaign_id, "revision": 2},
    }
    expect(page.locator("#bootstrapStopBtn")).to_be_enabled()
