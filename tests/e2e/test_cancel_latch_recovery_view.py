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
