"""The fenced cancellation review shows exact proof and no trading controls."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e
PAGE = (Path(__file__).resolve().parents[2] / "cancel_latch_recovery.html").as_uri()


def test_cancel_latch_recovery_requires_proof_and_posts_only_digest(page):
    page.add_init_script(
        """(() => {
            const review = {
                ready: true, generation: 154,
                wallet_fingerprint: 3702373391, network: 'mainnet',
                operation_ids: ['cancel:' + 'a'.repeat(64), 'cancel:' + 'b'.repeat(64)],
                review_digest: 'd'.repeat(64),
                proofs: [
                    {operation_id: 'cancel:' + 'a'.repeat(64), outcome: 'CANCELLED_PROVEN',
                     sage_status: 'cancelled', evidence_sha256: 'e'.repeat(64)},
                    {operation_id: 'cancel:' + 'b'.repeat(64), outcome: 'CANCELLED_PROVEN',
                     sage_status: 'cancelled', evidence_sha256: 'f'.repeat(64)}
                ]
            };
            window.__posted = [];
            window.confirm = () => true;
            window.fetch = async (path, options = {}) => {
                const url = String(path);
                const data = url.includes('confirm-cancel-latch-review')
                    ? (window.__posted.push(JSON.parse(options.body)),
                       {success: true, released: true})
                    : {success: true, review};
                return new Response(JSON.stringify(data),
                    {status: 200, headers: {'Content-Type': 'application/json'}});
            };
        })();"""
    )
    page.goto(PAGE, wait_until="domcontentloaded")

    expect(page.locator("#confirm")).to_be_enabled()
    expect(page.locator("#proofs li")).to_have_count(2)
    assert page.locator("button").all_text_contents() == [
        "Refresh exact proof",
        "Confirm database-only cancellation recovery",
        "Confirm database-only latch release",
    ]
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("#confirm").click()
    expect(page.locator("#confirm")).to_be_disabled()
    expect(page.locator("#status")).to_contain_text("Trading remains stopped")
    assert page.evaluate("window.__posted") == [
        {"expected_generation": 154, "review_digest": "d" * 64}
    ]


def test_cancel_latch_recovery_refuses_incomplete_proof(page):
    page.add_init_script(
        """(() => {
            window.fetch = async () => new Response(JSON.stringify({
                success: true, review: {ready: false,
                    reason_code: 'CANCELLATION_PROOF_INCOMPLETE'}
            }), {status: 200, headers: {'Content-Type': 'application/json'}});
        })();"""
    )
    page.goto(PAGE, wait_until="domcontentloaded")

    expect(page.locator("#confirm")).to_be_disabled()
    expect(page.locator("#status")).to_contain_text("Review refused")
    expect(page.locator("#proofs li")).to_have_count(0)


def test_restricted_view_checks_exact_submitted_scope_before_release(page):
    page.add_init_script(
        """(() => {
            const ids = ['cancel:' + 'a'.repeat(64), 'cancel:' + 'b'.repeat(64)];
            window.__posted = [];
            window.__settled = false;
            window.confirm = () => true;
            window.fetch = async (path, options = {}) => {
                if (String(path).includes('check-submitted-cancellations')) {
                    window.__posted.push(JSON.parse(options.body));
                    window.__settled = true;
                    return new Response(JSON.stringify({success: true,
                        recovered: true, generation: 155}),
                        {status: 200, headers: {'Content-Type': 'application/json'}});
                }
                const review = window.__settled
                    ? {ready: true, generation: 155, operation_ids: ids,
                       wallet_fingerprint: 3702373391, network: 'mainnet',
                       review_digest: 'd'.repeat(64),
                       proofs: ids.map(operation_id => ({operation_id,
                           outcome: 'CANCELLED_PROVEN', sage_status: 'cancelled',
                           evidence_sha256: 'e'.repeat(64)}))}
                    : {ready: false, reason_code: 'CANCELLATION_PROOF_INCOMPLETE',
                       generation: 155, operation_ids: ids,
                       wallet_fingerprint: 3702373391, network: 'mainnet',
                       scope_digest: 'c'.repeat(64)};
                return new Response(JSON.stringify({success: true, review}),
                    {status: 200, headers: {'Content-Type': 'application/json'}});
            };
        })();"""
    )
    page.goto(PAGE, wait_until="domcontentloaded")
    expect(page.locator("#checkSubmitted")).to_be_enabled()
    expect(page.locator("#confirm")).to_be_disabled()
    page.locator("#checkSubmitted").click()
    expect(page.locator("#confirm")).to_be_disabled()
    expect(page.locator("#status")).to_contain_text("safety latch resolved")
    assert page.evaluate("window.__posted") == [
        {
            "expected_generation": 155,
            "operation_ids": ["cancel:" + "a" * 64, "cancel:" + "b" * 64],
            "scope_digest": "c" * 64,
        }
    ]
