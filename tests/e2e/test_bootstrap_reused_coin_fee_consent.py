"""Native review of cancellation protection when campaign coins are reused."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def test_reused_coin_fee_review_records_consent_without_coin_prep(page):
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")
    result = page.evaluate(
        """async () => {
            document.getElementById('startupOverlay').style.display = 'none';
            const campaignId = 'a'.repeat(64);
            _bootstrapActiveCampaign = {
                campaign_id: campaignId, revision: 0,
                fee_budget_xch: '0.05', asset_id: 'b'.repeat(64), status: 'active'
            };
            currentCAT = {wallet_id: 2, asset_id: 'b'.repeat(64), name: 'MZ'};
            const now = Math.floor(Date.now() / 1000);
            window.__feeCalls = [];
            window.apiFetch = async (path, options = {}) => {
                window.__feeCalls.push({path: String(path), body: options.body || null});
                if (String(path).endsWith('/coin-prep/fee-preview')) {
                    return new Response(JSON.stringify({
                        success: true, available: true, funded: true,
                        preview_id: 'c'.repeat(64),
                        wallet: {campaign_id: campaignId, wallet_fingerprint: 736588221,
                            wallet_id: 2, network: 'mainnet', asset_id: 'b'.repeat(64)},
                        preparation_transaction_count_min: 0,
                        preparation_transaction_count_max: 0,
                        estimated_total_fee_mojos: '1000',
                        estimated_cancellation_fee_mojos: '1000',
                        minimum_cancellation_reserve_mojos: '1000',
                        minimum_cumulative_fee_mojos: '1000',
                        suggested_maximum_fee_mojos: '1000',
                        fee_accounting: {spent_fee_mojos: '0', held_fee_mojos: '0'},
                        observed_at: now, expires_at: now + 60,
                    }), {status: 200});
                }
                if (String(path).endsWith('/coin-prep/fee-approval')) {
                    return new Response(JSON.stringify({success: true, approval_id: 'd'.repeat(64)}),
                        {status: 200});
                }
                throw new Error('Unexpected wallet or bot call: ' + path);
            };
            await openBootstrapFeeConsentReview();
            return {calls: window.__feeCalls, text:
                document.getElementById('bootstrapFeeConsentOverlay').textContent};
        }"""
    )
    assert len(result["calls"]) == 1
    assert result["calls"][0]["path"].endswith("/coin-prep/fee-preview")
    expect(page.locator("#bootstrapFeeConsentOverlay")).to_have_class("confirm-overlay active")
    expect(page.locator("#bootstrapFeeConsentSummary")).to_contain_text(
        "0 preparation transactions"
    )
    page.locator("#bootstrapFeeConsentMaximum").fill("0.05")
    page.locator("#bootstrapFeeConsentApprove").click()
    page.wait_for_function("window.__feeCalls.length === 2")
    calls = page.evaluate("window.__feeCalls")
    assert calls[1]["path"].endswith("/coin-prep/fee-approval")
    assert all("/coin-prep/trigger" not in call["path"] for call in calls)
    assert all("/bot/start" not in call["path"] for call in calls)
    expect(page.locator("#bootstrapFeeConsentOverlay")).not_to_have_class(
        "confirm-overlay active"
    )


@pytest.mark.parametrize(
    ("invalid_field", "invalid_value"),
    [
        ("preparation_transaction_count_max", 1),
        ("wallet_campaign_id", "b" * 64),
        ("wallet_asset_id", "c" * 64),
        ("expires_at", 1),
        ("minimum_cumulative_fee_mojos", "60000000000"),
    ],
)
def test_reused_coin_fee_review_rejects_changed_or_unfunded_plan(
    page, invalid_field, invalid_value
):
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """async ([field, value]) => {
            document.getElementById('startupOverlay').style.display = 'none';
            const campaignId = 'a'.repeat(64);
            _bootstrapActiveCampaign = {
                campaign_id: campaignId, revision: 0,
                fee_budget_xch: '0.05', asset_id: 'b'.repeat(64), status: 'active'
            };
            currentCAT = {wallet_id: 2, asset_id: 'b'.repeat(64), name: 'MZ'};
            const preview = {
                success: true, available: true, funded: true,
                preview_id: 'c'.repeat(64),
                wallet: {campaign_id: campaignId, wallet_fingerprint: 736588221,
                    wallet_id: 2, network: 'mainnet', asset_id: 'b'.repeat(64)},
                preparation_transaction_count_min: 0,
                preparation_transaction_count_max: 0,
                estimated_total_fee_mojos: '1000',
                estimated_cancellation_fee_mojos: '1000',
                minimum_cancellation_reserve_mojos: '1000',
                minimum_cumulative_fee_mojos: '1000',
                fee_accounting: {spent_fee_mojos: '0', held_fee_mojos: '0'},
                expires_at: Math.floor(Date.now() / 1000) + 60,
            };
            if (field === 'wallet_campaign_id') preview.wallet.campaign_id = value;
            else if (field === 'wallet_asset_id') preview.wallet.asset_id = value;
            else preview[field] = value;
            window.__feeCalls = [];
            window.apiFetch = async (path) => {
                window.__feeCalls.push(String(path));
                if (String(path).endsWith('/coin-prep/fee-preview')) {
                    return new Response(JSON.stringify(preview), {status: 200});
                }
                throw new Error('Fee approval or wallet action must not occur');
            };
            await openBootstrapFeeConsentReview();
        }""",
        [invalid_field, invalid_value],
    )
    expect(page.locator("#bootstrapFeeConsentApprove")).to_be_disabled()
    expect(page.locator("#bootstrapFeeConsentError")).not_to_be_empty()
    assert len(page.evaluate("window.__feeCalls")) == 1
