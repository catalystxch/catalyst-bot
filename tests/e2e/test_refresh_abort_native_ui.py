"""Fenced wallet recovery never falls through to broad Cancel All."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def test_restricted_recovery_page_only_submits_reviewed_next_target(page):
    page.goto(
        (Path(__file__).resolve().parents[2] / "refresh_abort_recovery.html").as_uri()
    )
    page.evaluate(
        """() => {
          const trade = 'c'.repeat(64), campaign = 'b'.repeat(64);
          window.__recoveryCalls = [];
          window.confirm = () => true;
          window.fetch = async (path, options = {}) => {
            if (options.method === 'POST') {
              window.__recoveryCalls.push({path, body: JSON.parse(options.body)});
              return new Response(JSON.stringify({success: true,
                stage: 'awaiting_target_proof'}), {status: 200});
            }
            return new Response(JSON.stringify({
              success: true, stage: 'parent_terminal',
              abort: {abort_id: 'a'.repeat(64), campaign_id: campaign,
                      latch_generation: 7},
              wallet: {fingerprint: 736588221, network: 'mainnet',
                       asset_id: 'd'.repeat(64), active_trade_ids: [trade],
                       pending_transaction_count: 0},
              safety: {state: 'tripped', generation: 7, lease_owned: true},
              stopped_campaigns: [{campaign_id: campaign,
                                   fee_approval_id: 'f'.repeat(64)}],
              next_target_journal: null
            }), {status: 200});
          };
        }"""
    )
    page.locator("#refresh").click()
    expect(page.locator("#advance")).to_have_text("Review cancellation of " + "c" * 64)
    page.locator("#advance").click()
    page.wait_for_function("() => window.__recoveryCalls.length === 1")
    call = page.evaluate("window.__recoveryCalls[0]")
    assert call["path"].endswith("/refresh_abort/cancel_next")
    assert call["body"]["expected_next_trade_id"] == "c" * 64
    assert call["body"]["expected_trade_ids"] == ["c" * 64]


def test_restricted_recovery_fee_flow_never_calls_coin_prep(page):
    page.goto(
        (Path(__file__).resolve().parents[2] / "refresh_abort_recovery.html").as_uri()
    )
    page.evaluate(
        """() => {
          const campaign = 'b'.repeat(64);
          window.__recoveryCalls = [];
          window.__approved = false;
          window.confirm = () => true;
          window.fetch = async (path, options = {}) => {
            if (options.method === 'POST') {
              window.__recoveryCalls.push({path, body: JSON.parse(options.body)});
              if (path.endsWith('/fee_preview')) return new Response(JSON.stringify({
                success: true, preview_id: '2'.repeat(64),
                preparation_transaction_count_min: 0,
                suggested_maximum_fee_mojos: '5000000000',
                minimum_cancellation_reserve_mojos: '1000000000'
              }), {status: 200});
              window.__approved = true;
              return new Response(JSON.stringify({success: true,
                approval_id: '3'.repeat(64)}), {status: 200});
            }
            return new Response(JSON.stringify({
              success: true, stage: 'parent_terminal',
              abort: {abort_id: 'a'.repeat(64), campaign_id: campaign,
                      latch_generation: 7},
              wallet: {fingerprint: 736588221, network: 'mainnet',
                       asset_id: 'd'.repeat(64), active_trade_ids: ['c'.repeat(64)],
                       pending_transaction_count: 0},
              safety: {state: 'tripped', generation: 7, lease_owned: true},
              stopped_campaigns: [{campaign_id: campaign,
                fee_approval_id: window.__approved ? '3'.repeat(64) : null}],
              next_target_journal: null
            }), {status: 200});
          };
        }"""
    )
    page.locator("#refresh").click()
    page.locator("#advance").click()
    expect(page.locator("#feeRow")).to_be_visible()
    expect(page.locator("#feeMaximum")).to_have_value("0.005")
    page.locator("#advance").click()
    page.wait_for_function("() => window.__recoveryCalls.length === 2")
    calls = page.evaluate("window.__recoveryCalls")
    assert [call["path"].split("/")[-1] for call in calls] == [
        "fee_preview",
        "fee_approval",
    ]
    assert calls[1]["body"]["maximum_fee_mojos"] == "5000000000"
    assert calls[1]["body"]["cancellation_reserve_mojos"] == "1000000000"


def test_restricted_recovery_retries_fenced_parent_proof(page):
    page.goto(
        (Path(__file__).resolve().parents[2] / "refresh_abort_recovery.html").as_uri()
    )
    page.evaluate(
        """() => {
          window.__recoveryCalls = [];
          window.confirm = () => true;
          window.fetch = async (path, options = {}) => {
            if (options.method === 'POST') {
              window.__recoveryCalls.push({path, body: JSON.parse(options.body)});
              return new Response(JSON.stringify({success: true,
                stage: 'parent_terminal'}), {status: 200});
            }
            return new Response(JSON.stringify({
              success: true, stage: 'fenced',
              candidate: {parent_intent_id: 'parent', child_intent_id: 'child',
                          published_cleanup: true},
              abort: {abort_id: 'a'.repeat(64), campaign_id: 'b'.repeat(64),
                      latch_generation: 7},
              wallet: {fingerprint: 736588221, network: 'mainnet',
                       asset_id: 'd'.repeat(64), active_trade_ids: ['c'.repeat(64)],
                       pending_transaction_count: 0},
              safety: {state: 'tripped', generation: 7, lease_owned: true},
              stopped_campaigns: [], next_target_journal: null
            }), {status: 200});
          };
        }"""
    )
    page.locator("#refresh").click()
    expect(page.locator("#advance")).to_have_text("Retry submitted parent proof")
    page.locator("#advance").click()
    page.wait_for_function("() => window.__recoveryCalls.length === 1")
    call = page.evaluate("window.__recoveryCalls[0]")
    assert call["path"].endswith("/refresh_abort/begin")
    assert call["body"]["campaign_id"] == "b" * 64
    assert call["body"]["expected_trade_ids"] == ["c" * 64]
    assert call["body"]["published_cleanup"] is True
    expect(page.locator("#scope")).to_contain_text("potentially public")


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


def test_trading_recovery_preserves_published_child_scope(page):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async () => {
            document.getElementById('startupOverlay').style.display = 'none';
            bot_state = {running: false, offers: {buy: [], sell: []}};
            window.__abortCalls = [];
            const preview = {
                success: true, stage: 'submitted_parent_proof',
                candidate: {parent_intent_id: 'parent', child_intent_id: 'child',
                    parent_trade_id: 'a'.repeat(64), published_cleanup: true},
                wallet: {fingerprint: 736588221,
                    active_trade_ids: ['c'.repeat(64)],
                    pending_transaction_count: 0},
                safety: {state: 'tripped', generation: 2, lease_owned: true},
                stopped_campaigns: [{campaign_id: 'b'.repeat(64),
                    fee_budget_xch: '0.05'}],
            };
            window.apiFetch = async (path, options = {}) => {
                if (options.method === 'POST') {
                    window.__abortCalls.push({path, body: JSON.parse(options.body)});
                    return new Response(JSON.stringify({success: true,
                        stage: 'fenced'}), {status: 200});
                }
                return new Response(JSON.stringify(preview), {status: 200});
            };
            showStyledConfirm = async () => true;
            await cancelAllOffers();
        }"""
    )
    expect(page.locator("#refreshAbortSummary")).to_contain_text("potentially public")
    page.locator("#refreshAbortCampaign").select_option("b" * 64)
    page.locator("#refreshAbortActionBtn").click()
    page.wait_for_function("() => window.__abortCalls.length === 1")
    call = page.evaluate("window.__abortCalls[0]")
    assert call["path"].endswith("/offers/refresh_abort/begin")
    assert call["body"]["published_cleanup"] is True


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


@pytest.mark.parametrize("gate_allowed", [True, False])
def test_ordinary_cancel_requires_fresh_runtime_gate_not_latch_spelling(
    page, gate_allowed
):
    page.goto((Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri())
    page.evaluate(
        """async gateAllowed => {
            bot_state = {running: false, offers: {buy: [], sell: []}};
            window.apiFetch = async () => new Response(JSON.stringify({
                success: true, stage: 'no_exact_candidate', candidate: null,
                abort: null, safety: {state: 'resolved', allowed: gateAllowed},
            }), {status: 200});
            await cancelAllOffers();
        }""",
        gate_allowed,
    )
    assert page.locator("#cancelAllConfirmBtn").is_disabled() is not gate_allowed


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
