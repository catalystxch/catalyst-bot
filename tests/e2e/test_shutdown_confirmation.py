"""Shutdown intent regressions using the real DOM with mocked wallet/API calls."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture
def shutdown_page(page):
    source = (Path(__file__).resolve().parents[2] / "bot_gui.html").read_text(
        encoding="utf-8"
    )
    markup = source.split("    <!-- Shutdown Confirmation Modal -->", 1)[1].split(
        '<div class="modal" id="shutdownProgressModal"', 1
    )[0]
    script = (
        "function showShutdownModal() {"
        + source.split("        function showShutdownModal() {", 1)[1].split(
            "        // Wallet Picker Modal", 1
        )[0]
    )
    script = (
        "async function cancelAllRequestJson"
        + source.split("async function cancelAllRequestJson", 1)[1].split(
            "async function confirmCancelAll", 1
        )[0]
        + script
    )
    page.route("**/*", lambda route: route.abort())
    page.set_content(markup)
    page.add_script_tag(
        content="""
        const API_URL = '/api'; let TAURI_ALLOW_CLOSE = false;
        window.calls = []; window.logs = []; window.finished = false;
        window.stopResponses = [{success: true, stopped: true}];
        window.stopBodies = [];
        window.cancelStatus = {success: true, complete: true, running: false,
            phase: 'complete', pending: 0, failed: 0, cancelled: 72,
            remaining: 0, authoritative_complete: true, resolved: 72, closed: 0};
        async function apiFetch(path, options) {
            calls.push(path);
            if (path.endsWith('/bot/stop')) {
                stopBodies.push(options && options.body ? JSON.parse(options.body) : null);
                const result = stopResponses.length > 1 ? stopResponses.shift() : stopResponses[0];
                return {json: async () => result};
            }
            return {json: async () => path.endsWith('/cancel_all')
                ? {success: true, async: true, total: 72}
                : path.endsWith('/status')
                    ? window.cancelStatus
                    : {success: true}};
        }
        function addLogEntry(level, message) {logs.push({level, message});}
        async function startupWaitForBackendShutdown() {return true;}
        async function closeDesktopWindowAfterShutdown() {finished = true; return true;}
    """
        + script
    )
    page.evaluate("showShutdownModal()")
    return page


@pytest.mark.parametrize("repeat_open", [False, True])
def test_confirmed_cancellation_survives_repeated_close_request(
    shutdown_page, repeat_open
):
    page = shutdown_page
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    if repeat_open:
        page.evaluate("showShutdownModal()")
    page.locator("#confirmShutdownBtn").click()
    page.wait_for_function("finished")
    calls = page.evaluate("calls")
    assert "/api/offers/cancel_all" in calls
    assert (
        calls.index("/api/bot/stop")
        < calls.index("/api/offers/cancel_all")
        < calls.index("/api/shutdown")
    )


def test_selected_cancellation_without_confirmation_does_not_shutdown(shutdown_page):
    page = shutdown_page
    page.locator("#shutdownCancelOffers").check()
    page.evaluate("confirmShutdown()")
    assert page.evaluate("calls") == []
    assert page.locator("#shutdownModal").evaluate(
        "el => el.classList.contains('active')"
    )
    assert page.locator("#confirmShutdownBtn").is_enabled()
    assert page.get_by_role("button", name="Yes, cancel them", exact=True).is_visible()


def test_fresh_dialog_after_go_back_resets_choice(shutdown_page):
    page = shutdown_page
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    page.get_by_role("button", name="Go Back", exact=True).click()
    page.evaluate("showShutdownModal()")
    assert not page.locator("#shutdownCancelOffers").is_checked()
    assert page.locator("#shutdownCancelConfirmed").input_value() == "no"


def test_reselecting_cancellation_allows_confirmation_again(shutdown_page):
    page = shutdown_page
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    page.locator("#shutdownCancelOffers").uncheck()
    page.locator("#shutdownCancelOffers").check()
    assert page.get_by_role("button", name="Yes, cancel them", exact=True).is_visible()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    page.locator("#confirmShutdownBtn").click()
    page.wait_for_function("finished")
    assert "/api/offers/cancel_all" in page.evaluate("calls")


def test_explicit_leave_open_choice_still_shuts_down(shutdown_page):
    page = shutdown_page
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="No, leave them open", exact=True).click()
    page.locator("#confirmShutdownBtn").click()
    page.wait_for_function("finished")
    assert page.evaluate("calls") == ["/api/bot/stop", "/api/shutdown"]


@pytest.mark.parametrize(
    "response", [{"success": False, "error": "stop failed"}, {"stopped": True}]
)
def test_shutdown_rejects_unverified_stop_response(shutdown_page, response):
    page = shutdown_page
    page.evaluate("value => {stopResponses = [value]}", response)
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    page.evaluate("confirmShutdown()")
    assert page.evaluate("finished") is False
    assert "/api/offers/cancel_all" not in page.evaluate("calls")
    assert "/api/shutdown" not in page.evaluate("calls")


def test_shutdown_waits_for_drain_and_late_confirmation(shutdown_page):
    page = shutdown_page
    page.evaluate(
        "stopResponses = [{success:true,stopped:false,status:'stopping'}, {success:true,stopped:false,status:'confirming'}, {success:true,stopped:true}]"
    )
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    page.evaluate("confirmShutdown()")
    calls = page.evaluate("calls")
    assert calls[:3] == ["/api/bot/stop"] * 3
    assert calls[3] == "/api/offers/cancel_all"
    assert page.evaluate("stopBodies.every(b => b.settle_cancellations === true)")
    assert page.evaluate("finished") is True


def test_proven_expired_members_are_not_reported_as_cancelled(shutdown_page):
    page = shutdown_page
    page.evaluate("cancelStatus.cancelled=70; cancelStatus.closed=2;")
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    page.evaluate("confirmShutdown()")
    assert page.evaluate("finished") is True
    assert page.evaluate(
        "logs.some(e => e.message.includes('70 cancellations confirmed; 2 offers otherwise ended'))"
    )


@pytest.mark.parametrize(
    "status",
    [
        {
            "complete": True,
            "running": False,
            "phase": "complete",
            "pending": 1,
            "failed": 71,
            "cancelled": 0,
        },
        {
            "complete": True,
            "running": False,
            "phase": "complete",
            "pending": 72,
            "failed": 0,
            "cancelled": 0,
        },
        {
            "complete": True,
            "running": False,
            "phase": "complete",
            "pending": 0,
            "failed": 0,
            "cancelled": 72,
        },
    ],
)
def test_journal_completion_without_authoritative_completion_keeps_app_open(
    shutdown_page, status
):
    page = shutdown_page
    page.evaluate("(s) => {window.cancelStatus={success:true,...s};}", status)
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    page.evaluate("confirmShutdown()")
    assert "/api/shutdown" not in page.evaluate("calls")
    assert page.evaluate("finished") is False
    assert page.evaluate("logs.some(e => e.level === 'error')")


@pytest.mark.parametrize("hung_path", ["/bot/stop", "/offers/cancel_all"])
def test_shutdown_unanswered_request_keeps_app_open_with_visible_error(
    shutdown_page, hung_path
):
    page = shutdown_page
    page.clock.install()
    page.evaluate(
        "suffix=>{const previous=apiFetch; apiFetch=(path,options)=>path.endsWith(suffix)?new Promise(()=>{}):previous(path,options)}",
        hung_path,
    )
    page.locator("#shutdownCancelOffers").check()
    page.get_by_role("button", name="Yes, cancel them", exact=True).click()
    page.locator("#confirmShutdownBtn").click()
    page.clock.fast_forward(120001)
    assert page.evaluate(
        "logs.some(e=>e.level==='error' && e.message.includes('timed out'))"
    )
    assert page.evaluate("finished") is False
    assert "/api/shutdown" not in page.evaluate("calls")
