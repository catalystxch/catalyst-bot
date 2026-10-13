"""The restricted page shows proof without exposing broad trading controls."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def test_restricted_view_escapes_wallet_data_and_has_no_unscoped_action(page):
    page.add_init_script(
        """(() => {
            window.fetch = async () => new Response(JSON.stringify({
                success: true,
                stage: '<img src=x onerror="window.__injected=true">',
                wallet: {fingerprint: 736588221, network: 'mainnet',
                    asset_id: 'a'.repeat(64), active_trade_ids: ['b'.repeat(64)],
                    pending_transaction_count: 0, observed_at: '2026-10-13T19:00:00Z'},
                safety: {state: 'tripped', reason_code: 'UNRESOLVED_OPERATIONS',
                    lease_owned: true}
            }), {status: 200, headers: {'Content-Type': 'application/json'}});
        })();"""
    )
    page.goto(
        (Path(__file__).resolve().parents[2] / "refresh_abort_recovery.html").as_uri()
    )

    expect(page.locator("#status")).to_have_text(
        "Exact proof loaded. Review the next action before proceeding."
    )
    expect(page.locator("#stage")).to_contain_text("<img src=x")
    assert page.locator("img").count() == 0
    assert page.evaluate("window.__injected === true") is False
    assert page.locator("button").all_text_contents() == [
        "Refresh proof",
        "Review exact recovery",
    ]
    expect(page.locator("#advance")).to_be_disabled()
    assert page.locator("#offers").inner_text() == "b" * 64


def test_restricted_view_fails_closed_when_preview_unavailable(page):
    page.add_init_script(
        """(() => {
            window.fetch = async () => new Response(
                JSON.stringify({success: false, error: 'authoritative_preview_unavailable'}),
                {status: 503, headers: {'Content-Type': 'application/json'}}
            );
        })();"""
    )
    page.goto(
        (Path(__file__).resolve().parents[2] / "refresh_abort_recovery.html").as_uri()
    )

    expect(page.locator("#status")).to_have_text(
        "Recovery proof is unavailable. Trading remains stopped."
    )
    expect(page.locator("#offers")).to_have_text("Unavailable")
