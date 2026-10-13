"""Fenced wallet recovery never falls through to broad Cancel All."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def test_fenced_cancel_dialog_submits_one_exact_target(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async () => {
            document.getElementById('startupOverlay').style.display = 'none';
            bot_state = {running: false, offers: {buy: [], sell: []}};
            const trade = 'c'.repeat(64), campaign = 'b'.repeat(64);
            window.__abortCalls = [];
            const preview = {
                success: true, stage: 'parent_terminal',
                abort: {abort_id: 'a'.repeat(64), campaign_id: campaign,
                        latch_generation: 2},
                wallet: {fingerprint: 736588221,
                         active_trade_ids: [trade, 'd'.repeat(64), 'e'.repeat(64)],
                         pending_transaction_count: 0},
                safety: {state: 'tripped', generation: 2, lease_owned: true},
                stopped_campaigns: [{campaign_id: campaign,
                    fee_approval_id: 'f'.repeat(64), fee_budget_xch: '0.05'}],
                next_target_journal: null,
            };
            window.apiFetch = async (path, options = {}) => {
                if (options.method === 'POST') {
                    window.__abortCalls.push({path, body: JSON.parse(options.body)});
                    return new Response(JSON.stringify({success: true,
                        stage: 'awaiting_target_proof'}), {status: 200});
                }
                return new Response(JSON.stringify(preview), {status: 200});
            };
            showStyledConfirm = async () => true;
            await cancelAllOffers();
        }"""
    )
    expect(page.locator("#cancelConfirmTitle")).to_have_text("Recover fenced offers")
    expect(page.locator("#cancelAllConfirmBtn")).to_be_disabled()
    page.locator("#refreshAbortActionBtn").click()
    page.wait_for_function("() => window.__abortCalls.length === 1")
    calls = page.evaluate("window.__abortCalls")
    assert calls[0]["path"].endswith("/offers/refresh_abort/cancel_next")
    assert calls[0]["body"]["expected_next_trade_id"] == "c" * 64
    assert calls[0]["body"]["expected_trade_ids"] == ["c" * 64, "d" * 64, "e" * 64]


def test_submitted_parent_requires_explicit_stopped_campaign(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async () => {
            document.getElementById('startupOverlay').style.display = 'none';
            bot_state = {running: false, offers: {buy: [], sell: []}};
            window.apiFetch = async () => new Response(JSON.stringify({
                success: true, stage: 'submitted_parent_proof',
                candidate: {parent_intent_id: 'parent', child_intent_id: 'child',
                            parent_trade_id: 'a'.repeat(64)},
                wallet: {fingerprint: 736588221,
                         active_trade_ids: ['c'.repeat(64)],
                         pending_transaction_count: 0},
                safety: {state: 'tripped', generation: 2, lease_owned: true},
                stopped_campaigns: [{campaign_id: 'b'.repeat(64),
                    fee_budget_xch: '0.05'}],
            }), {status: 200});
            await cancelAllOffers();
        }"""
    )
    expect(page.locator("#cancelAllConfirmBtn")).to_be_disabled()
    expect(page.locator("#refreshAbortActionBtn")).to_be_disabled()
    page.locator("#refreshAbortCampaign").select_option("b" * 64)
    expect(page.locator("#refreshAbortActionBtn")).to_be_enabled()


def test_submitted_target_removed_from_sage_book_still_checks_proof(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async () => {
            document.getElementById('startupOverlay').style.display = 'none';
            bot_state = {running: false, offers: {buy: [], sell: []}};
            const submitted = 'c'.repeat(64), remaining = 'd'.repeat(64);
            window.__abortCalls = [];
            const preview = {
                success: true, stage: 'parent_terminal',
                abort: {abort_id: 'a'.repeat(64), campaign_id: 'b'.repeat(64),
                        latch_generation: 2},
                wallet: {fingerprint: 736588221, active_trade_ids: [remaining],
                         pending_transaction_count: 0},
                safety: {state: 'tripped', generation: 2, lease_owned: true},
                next_target_journal: {trade_id: submitted, phase: 'FINALIZED',
                                      outcome: 'CANCEL_SUBMITTED_UNCONFIRMED'},
            };
            window.apiFetch = async (path, options = {}) => {
                if (options.method === 'POST') {
                    window.__abortCalls.push({path, body: JSON.parse(options.body)});
                    return new Response(JSON.stringify({success: false,
                        stage: 'awaiting_target_proof'}), {status: 409});
                }
                return new Response(JSON.stringify(preview), {status: 200});
            };
            showStyledConfirm = async () => true;
            await cancelAllOffers();
        }"""
    )
    expect(page.locator("#cancelAllConfirmBtn")).to_be_disabled()
    expect(page.locator("#refreshAbortActionBtn")).to_have_text(
        "Check target cancellation proof"
    )
    page.locator("#refreshAbortActionBtn").click()
    page.wait_for_function("() => window.__abortCalls.length === 1")
    calls = page.evaluate("window.__abortCalls")
    assert calls[0]["path"].endswith("/offers/refresh_abort/reconcile_target")
    assert calls[0]["body"]["trade_id"] == "c" * 64


@pytest.mark.parametrize("cached_allowed", [True, False])
def test_preview_failure_keeps_broad_cancel_disabled(page, cached_allowed):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async cachedAllowed => {
            document.getElementById('startupOverlay').style.display = 'none';
            bot_state = {running: false, offers: {buy: [], sell: []},
                         runtime_safety: {allowed: cachedAllowed}};
            window.apiFetch = async () => {throw new Error('diagnostic unavailable')};
            await cancelAllOffers();
        }""",
        cached_allowed,
    )
    expect(page.locator("#cancelAllConfirmBtn")).to_be_disabled()
    expect(page.locator("#refreshAbortActionBtn")).to_be_disabled()
