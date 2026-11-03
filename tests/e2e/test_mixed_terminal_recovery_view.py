"""Browser checks for the fenced database-only recovery screen."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e
PAGE = (Path(__file__).resolve().parents[2] / "terminal_offer_recovery.html").as_uri()


def test_terminal_recovery_reviews_six_roots_and_refuses_stale_retry(page):
    page.add_init_script(
        """(() => {
            const campaign = 'a'.repeat(64);
            const offers = Array.from({length: 6}, (_, index) => ({
                intent_id: String(index + 1).padStart(64, '0'),
                trade_id: String(index + 11).padStart(64, '0'),
                side: index < 3 ? 'buy' : 'sell',
                tier: index === 0 ? '<img src=x onerror="window.__injected=true">' : 'inner',
                classification: index === 0 ? 'FILLED_PROVEN' : 'EXPIRED_PROVEN',
                already_terminal: false,
                proof_digest: 'c'.repeat(64)
            }));
            const proof = {
                success: true, campaign_id: campaign, revision: 0,
                wallet_fingerprint_hash: 'f'.repeat(64), network: 'mainnet',
                asset_id: 'b'.repeat(64), latch_generation: 150,
                blocking_operation_ids: offers.map(offer => `reconcile:${offer.intent_id}`),
                lease_owner_run_id: 'test-run', lease_owner_pid: 1,
                lease_owner_host: 'test-host', lease_acquired_at: '2026-10-18T08:00:00Z',
                proof_digest: 'd'.repeat(64), sage_live_offers: 0,
                sage_pending_transactions: 0, wallet_effect_started: false,
                offers
            };
            window.__commitBodies = [];
            window.__injected = false;
            window.confirm = () => true;
            window.fetch = async (path, options = {}) => {
                const url = String(path);
                let data;
                if (url.includes('terminal_recovery_scope')) {
                    data = {success: true, campaign_id: campaign, revision: 0,
                        latch_generation: 150, blocking_count: 6};
                } else if (url.includes('preview_terminal')) {
                    data = proof;
                } else if (url.includes('commit_terminal')) {
                    window.__commitBodies.push(JSON.parse(options.body));
                    data = {success: true, filled: 1, expired: 0,
                        already_terminal: 0, pending_hooks: 4,
                        remaining_blockers: 5, unresolved_journals: 0,
                        partial_commit: true};
                } else {
                    throw new Error(`Unexpected fetch: ${url}`);
                }
                return new Response(JSON.stringify(data),
                    {status: 200, headers: {'Content-Type': 'application/json'}});
            };
        })();"""
    )
    page.goto(PAGE, wait_until="domcontentloaded")

    expect(page.locator("#commit")).to_be_enabled()
    expect(page.locator("#outcomes tr")).to_have_count(6)
    expect(page.locator("#outcomes")).to_contain_text("<img src=x")
    assert page.locator("img").count() == 0
    assert page.evaluate("window.__injected") is False

    page.locator("#commit").click()

    expect(page.locator("#status")).to_contain_text("fresh preview")
    expect(page.locator("#commit")).to_be_disabled()
    assert page.evaluate("window.__commitBodies.length") == 1
    assert page.evaluate("window.__commitBodies[0].reviewed.success") is None
    assert page.evaluate("window.__commitBodies[0].reviewed.offers.length") == 6
    page.locator("#refresh").click()
    expect(page.locator("#commit")).to_be_enabled()


def test_terminal_recovery_screen_denies_incomplete_preview(page):
    page.add_init_script(
        """(() => {
            window.fetch = async path => new Response(JSON.stringify(
                String(path).includes('terminal_recovery_scope')
                    ? {success: true, campaign_id: 'a'.repeat(64), revision: 0,
                        latch_generation: 150, blocking_count: 6}
                    : {success: false, error: 'mixed_terminal_preview_refused'}
            ), {status: String(path).includes('terminal_recovery_scope') ? 200 : 409,
                headers: {'Content-Type': 'application/json'}});
        })();"""
    )
    page.goto(PAGE, wait_until="domcontentloaded")

    expect(page.locator("#commit")).to_be_disabled()
    expect(page.locator("#status")).to_contain_text("Proof refused")
    expect(page.locator("#outcomes tr")).to_have_count(0)
