"""A Sage-only terminal proof gets an exact native, local-only review."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def test_sage_recovery_entry_works_without_selected_pair_or_visible_offers(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """() => {
            document.getElementById('startupOverlay').style.display = 'none';
            IS_DESKTOP = true;
            bot_state = {running: false, offers: {buy: [], sell: []}};
            window.pywebview = {api: {
                preview_external_cancellation: async () => ({success: false})
            }};
            window.apiFetch = async () => new Response(JSON.stringify({
                success: true, stage: 'normal', safety: {allowed: true},
                wallet: {fingerprint: 736588221,
                         active_trade_ids: ['c'.repeat(64)],
                         pending_transaction_count: 0}
            }), {status: 200});
        }"""
    )
    page.locator('button[data-view="offers"]').click()
    page.locator("#externalCancelReviewEntry").click()
    expect(page.locator("#cancelConfirmModal")).to_have_class("modal active")
    expect(page.locator("#cancelAllConfirmBtn")).to_be_disabled()
    expect(page.locator("#externalCancelCommitBtn")).to_be_disabled()
    wallet_writes = page.evaluate(
        """async () => {
            const writes = [];
            window.apiFetch = async (url, options) => {
                if (options?.method === 'POST') {
                    writes.push(url);
                    throw new Error('blocked test wallet effect');
                }
                return new Response(JSON.stringify({success: true}), {status: 200});
            };
            await confirmCancelAll();
            return writes;
        }"""
    )
    assert wallet_writes == []


def test_sage_recovery_entry_hides_other_wallet_recovery_actions(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """() => {
            document.getElementById('startupOverlay').style.display = 'none';
            IS_DESKTOP = true;
            bot_state = {running: false, offers: {buy: [], sell: []}};
            window.pywebview = {api: {
                preview_external_cancellation: async () => ({success: false})
            }};
            window.apiFetch = async () => new Response(JSON.stringify({
                success: true, stage: 'parent_terminal',
                candidate: {parent_trade_id: 'a'.repeat(64)},
                safety: {allowed: false, lease_owned: true},
                wallet: {fingerprint: 736588221,
                         active_trade_ids: ['c'.repeat(64)],
                         pending_transaction_count: 0}
            }), {status: 200});
        }"""
    )
    page.locator('button[data-view="offers"]').click()
    page.locator("#externalCancelReviewEntry").click()
    expect(page.locator("#externalCancelPanel")).to_be_visible()
    expect(page.locator("#refreshAbortPanel")).to_be_hidden()
    expect(page.locator("#refreshAbortActionBtn")).to_be_disabled()


def test_external_cancel_review_disables_broad_cancel_and_shows_exact_fee(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async () => {
            document.getElementById('startupOverlay').style.display = 'none';
            IS_DESKTOP = true;
            bot_state = {running: false, offers: {buy: [], sell: [{trade_id: 'b'.repeat(64)}]}};
            window.__externalCommitCalls = [];
            const review = {
                intent_id: 'a'.repeat(64), trade_id: 'b'.repeat(64), side: 'sell',
                wallet_fingerprint: 736588221, network: 'mainnet',
                asset_id: 'd'.repeat(64), input_coin_id: 'e'.repeat(64),
                return_coin_id: 'f'.repeat(64), returned_asset_id: 'd'.repeat(64),
                returned_amount_atomic: '24166667',
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
    expect(page.locator("#externalCancelSummary")).to_contain_text("CAT atoms")
    expect(page.locator("#externalCancelFee")).to_contain_text("0.000010000000 XCH")
    expect(page.locator("#externalCancelCommitBtn")).to_be_enabled()
    assert page.evaluate("window.__externalCommitCalls") == []
    page.locator("#externalCancelCommitBtn").click()
    page.wait_for_function("() => window.__externalCommitCalls.length === 1")
    assert (
        page.evaluate("window.__externalCommitCalls[0].reviewed.trade_id") == "b" * 64
    )


def test_external_cancel_identity_outage_keeps_broad_cancel_disabled(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async () => {
            document.getElementById('startupOverlay').style.display = 'none';
            IS_DESKTOP = true;
            bot_state = {running: false, offers: {buy: [], sell: [{trade_id: 'b'.repeat(64)}]}};
            window.pywebview = {api: {
                preview_external_cancellation: async () => ({success: false})
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
    expect(page.locator("#externalCancelCommitBtn")).to_be_disabled()
    expect(page.locator("#externalCancelSummary")).to_contain_text(
        "Exact cancellation proof is unavailable"
    )


def test_external_buy_cancellation_review_labels_xch_mojos(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async () => {
            IS_DESKTOP = true;
            bot_state = {running: false, offers: {buy: [], sell: []}};
            document.getElementById('cancelConfirmModal').classList.add('active');
            const review = {
                intent_id: 'a'.repeat(64), trade_id: 'b'.repeat(64), side: 'buy',
                wallet_fingerprint: 123, network: 'mainnet',
                asset_id: 'd'.repeat(64), input_coin_id: 'e'.repeat(64),
                return_coin_id: 'f'.repeat(64), returned_asset_id: 'xch',
                returned_amount_atomic: '24166667', fee_mojos: '10000000',
                confirmed_height: 9483977, proof_digest: '1'.repeat(64),
                expires_at_epoch: 9999999999, wallet_effect_started: false
            };
            window.pywebview = {api: {
                preview_external_cancellation: async () => ({success: true, review})
            }};
            await loadExternalCancelReview();
        }"""
    )
    expect(page.locator("#externalCancelSummary")).to_contain_text("BUY ")
    expect(page.locator("#externalCancelSummary")).to_contain_text("XCH mojos")
