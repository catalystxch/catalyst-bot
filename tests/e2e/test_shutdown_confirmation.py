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
    page.route("**/*", lambda route: route.abort())
    page.set_content(markup)
    page.add_script_tag(
        content="""
        const API_URL = '/api'; let TAURI_ALLOW_CLOSE = false;
        window.calls = []; window.logs = []; window.finished = false;
        async function apiFetch(path) {
            calls.push(path);
            return {json: async () => path.endsWith('/cancel_all')
                ? {success: true, async: true, total: 72}
                : path.endsWith('/status')
                    ? {success: true, complete: true, running: false,
                       phase: 'complete', pending: 72, failed: 0}
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
