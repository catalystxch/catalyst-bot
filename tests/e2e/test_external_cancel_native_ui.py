"""A Sage-only terminal proof gets an exact native, local-only review."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def test_external_cancel_review_disables_broad_cancel_and_shows_exact_fee(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async () => {
            document.getElementById('startupOverlay').style.display = 'none';
            IS_DESKTOP = true;
            bot_state = {running: false, offers: {buy: [], sell: [{trade_id: 'b'.repeat(64)}]}};
            window.__externalCommitCalls = [];
            const review = {
                intent_id: 'a'.repeat(64), trade_id: 'b'.repeat(64),
                wallet_fingerprint: 736588221, network: 'mainnet',
                asset_id: 'd'.repeat(64), input_coin_id: 'e'.repeat(64),
                return_coin_id: 'f'.repeat(64), returned_amount_atomic: '24166667',
                fee_mojos: '10000000', confirmed_height: 9483977,
                proof_digest: '1'.repeat(64), expires_at_epoch: 9999999999,
                wallet_effect_started: false
            };
            window.pywebview = {api: {
                preview_external_cancellation: async () => ({success: true, review}),
                commit_external_cancellation: async body => {
                    window.__externalCommitCalls.push(body);
                    return {success: false, error: 'mock_blocked'};
                }
            }};
            window.apiFetch = async () => new Response(JSON.stringify({
                success: true, stage: 'normal', safety: {allowed: true},
                wallet: {fingerprint: 736588221, active_trade_ids: [],
                         pending_transaction_count: 0}
            }), {status: 200});
            await cancelAllOffers();
        }"""
    )
    expect(page.locator("#cancelAllConfirmBtn")).to_be_disabled()
    expect(page.locator("#externalCancelPanel")).to_be_visible()
    expect(page.locator("#externalCancelFee")).to_contain_text("0.000010000000 XCH")
    expect(page.locator("#externalCancelCommitBtn")).to_be_enabled()
    assert page.evaluate("window.__externalCommitCalls") == []
    page.locator("#externalCancelCommitBtn").click()
    page.wait_for_function("() => window.__externalCommitCalls.length === 1")
    assert (
        page.evaluate("window.__externalCommitCalls[0].reviewed.trade_id") == "b" * 64
    )
