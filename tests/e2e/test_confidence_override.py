"""Native HTML review tested with all network requests intercepted."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def open_review(page):
    page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith("file:")
            else route.abort()
        ),
    )
    page.goto(
        (Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri(),
        wait_until="domcontentloaded",
    )
    page.evaluate("""async () => {
        document.querySelectorAll('.modal.active, #startupOverlay, #splashGateOverlay, #spacescanGateOverlay').forEach(e => e.style.display='none');
        window.__starts = [];
        window.__reviewRequests = [];
        bot_state = {running:false};
        startBot = async options => window.__starts.push(options);
        window.apiFetch = async (_url, options) => {
          const requested = JSON.parse(options.body);
          window.__reviewRequests.push(requested);
          return new Response(JSON.stringify({confidence_override_review:{
            review_id:'review-123', duration_hours:requested.duration_hours, review_expires_at:new Date(Date.now()+60000).toISOString(),
            scope:{identity:{wallet_fingerprint:123,network:'mainnet',ticker:'<img src=x onerror=window.__injected=true>',asset_id:'asset'},
                buy_limit:24,sell_limit:24,fee_cap_mojos:'50000000000',protected_cancel_mojos:'123456789',xch_reserve:'0.05',cat_reserve:'100'}
          }}));
        };
        await reviewConfidenceOverride();
    }""")


def test_review_visible_escaped_and_explicit_before_start(page):
    open_review(page)
    expect(
        page.get_by_role("heading", name="Continue despite low market confidence")
    ).to_be_visible()
    expect(page.locator("#confidenceOverrideReviewText")).to_contain_text("50000000000")
    expect(page.locator("#confidenceOverrideReviewText")).to_contain_text("<img src=x")
    assert page.evaluate("window.__injected === undefined")
    expect(page.locator("#confidenceOverrideConfirm")).to_be_disabled()
    assert page.evaluate("window.__starts") == []
    assert page.evaluate("window.__reviewRequests[0].duration_hours") == 72
    page.locator("#confidenceOverrideAccept").check()
    page.locator("#confidenceOverrideConfirm").click()
    assert page.evaluate("window.__starts") == [
        {"confidenceOverride": {"review_id": "review-123", "accepted": True}}
    ]


def test_changing_override_duration_requires_new_exact_review(page):
    open_review(page)
    page.locator("#confidenceOverrideAccept").check()
    page.locator("#confidenceOverrideHours").fill("96")
    expect(page.locator("#confidenceOverrideConfirm")).to_be_disabled()
    assert page.evaluate("_confidenceOverrideReview === null")
    page.get_by_role("button", name="Refresh exact review").click()
    expect(page.locator("#confidenceOverrideReviewText")).to_contain_text(
        "up to 96 hours"
    )
    assert page.evaluate("window.__reviewRequests.at(-1).duration_hours") == 96


def test_expired_review_never_starts_and_red_stays_red(page):
    open_review(page)
    page.evaluate("""() => {
        _confidenceOverrideReview.review_expires_at = new Date(Date.now()-1).toISOString();
        renderMarketConfidence({confidence:{state:'RED', reason_codes:['insufficient_ask_depth']},
            confidence_override:{approved:true,active:true,expires_at:'tomorrow'}});
    }""")
    page.locator("#confidenceOverrideAccept").check()
    expect(page.locator("#confidenceOverrideConfirm")).to_be_disabled()
    expect(page.locator("#marketConfidenceState")).to_have_text("RED")
    expect(page.locator("#confidenceOverrideStatus")).to_contain_text(
        "confidence remains RED"
    )
    page.evaluate("confirmConfidenceOverrideStart()")
    assert page.evaluate("window.__starts") == []


def test_resume_handoff_requires_fresh_override_review_instead_of_plain_start(page):
    open_review(page)
    page.evaluate("""async () => {
        _confidenceOverrideResumeReviewRequired = true;
        _resumeSessionSummary = {buy_count:3,sell_count:3,offer_count:6};
        window.__reviews = 0;
        reviewConfidenceOverride = async () => { window.__reviews += 1; };
        apiFetch = async () => new Response(JSON.stringify({can_resume:true,buy_count:3,sell_count:3,offer_count:6}));
        await resumeStartNow();
    }""")
    assert page.evaluate("window.__starts") == []
    assert page.evaluate("window.__reviews") == 1
