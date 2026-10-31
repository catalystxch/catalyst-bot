"""The fenced creation review is exact and never sends a wallet request."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def test_no_effect_creation_review_and_local_commit(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """() => {
            document.getElementById('startupOverlay').style.display = 'none';
            IS_DESKTOP = true;
            bot_state = {running: false, offers: {buy: [], sell: []}};
            const review = {
                intent_id: 'a'.repeat(64), operation_id: 'create:' + 'a'.repeat(64),
                wallet_fingerprint_hash: 'b'.repeat(64), network: 'mainnet',
                selected_coin_id: 'c'.repeat(64), requested_amount_atomic: 2700000000003,
                latch_generation: 694, row_version: 1, proof_digest: 'd'.repeat(64),
                sage_stable: [736588221, 'mainnet', 160832, 1, 'Sage-tauri.exe',
                              22292822, 'e'.repeat(64), 'f'.repeat(64), 4164],
                expires_at_epoch: 9999999999, wallet_effect_started: false
            };
            window.__creationCommits = [];
            window.pywebview = {api: {
                preview_no_effect_creation: async () => ({success: true, review}),
                commit_no_effect_creation: async body => {
                    window.__creationCommits.push(body);
                    return {success: true, applied: true, wallet_effect_started: false};
                }
            }};
            window.apiFetch = async (url, options) => {
                if (options?.method === 'POST') throw new Error('wallet effect forbidden');
                return new Response(JSON.stringify({success: true}), {status: 200});
            };
        }"""
    )
    page.locator('button[data-view="offers"]').click()
    page.locator('#noEffectCreationReviewEntry').click()
    expect(page.locator('#noEffectCreationPanel')).to_be_visible()
    expect(page.locator('#noEffectCreationCommitBtn')).to_be_enabled()
    expect(page.locator('#cancelAllConfirmBtn')).to_be_disabled()
    expect(page.locator('#noEffectCreationSummary')).to_contain_text('694')
    page.locator('#noEffectCreationCommitBtn').click()
    expect(page.locator('#cancelConfirmModal')).not_to_have_class('modal active')
    assert page.evaluate('window.__creationCommits.length') == 1


def test_no_effect_creation_preview_failure_remains_fenced(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """() => {
            document.getElementById('startupOverlay').style.display = 'none';
            IS_DESKTOP = true;
            bot_state = {running: false, offers: {buy: [], sell: []}};
            window.pywebview = {api: {
                preview_no_effect_creation: async () => ({success: false})
            }};
            window.apiFetch = async () => new Response(
                JSON.stringify({success: true}), {status: 200});
        }"""
    )
    page.locator('button[data-view="offers"]').click()
    page.locator('#noEffectCreationReviewEntry').click()
    expect(page.locator('#noEffectCreationPanel')).to_be_visible()
    expect(page.locator('#noEffectCreationCommitBtn')).to_be_disabled()
    expect(page.locator('#cancelAllConfirmBtn')).to_be_disabled()
