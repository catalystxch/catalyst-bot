"""Exercise the real startup upgrade controls with isolated download responses."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def prepare_upgrade(page, *, running=False):
    page.route("**/api/config", lambda r: r.fulfill(json={"SPLASH_ENABLED": True}))
    page.route(
        "**/api/splash/setup/check",
        lambda r: r.fulfill(json={"installed": True, "version": "Splash! 0.2.0"}),
    )
    page.route(
        "**/api/splash/node",
        lambda r: r.fulfill(
            json={"process_running": running, "api_reachable": running, "peers": 0}
        ),
    )
    page.route(
        "**/api/splash/setup/release",
        lambda r: r.fulfill(json={"release": {"tag": "0.3.0"}}),
    )
    page.evaluate(
        "document.getElementById('startupOverlay').style.display='none'; splashGateBegin()"
    )
    expect(page.locator("#splashGateUpdateNotice")).to_be_visible()


def test_upgrade_downloads_once_shows_progress_and_never_starts_node(app_page):
    page = app_page
    requests = []
    page.route(
        "**/api/splash/setup/download",
        lambda r: (
            requests.append(r.request.method),
            r.fulfill(json={"started": True}),
        ),
    )
    page.route(
        "**/api/splash/setup/progress",
        lambda r: r.fulfill(
            json={
                "in_progress": True,
                "percent": 42,
                "message": "Downloading binary...",
                "result": None,
            }
        ),
    )
    starts = []
    page.route(
        "**/api/splash/node/start",
        lambda r: (starts.append(r.request.url), r.fulfill(json={"success": True})),
    )
    prepare_upgrade(page)
    page.locator("#splashGateUpgradeBtn").click(timeout=2000)
    expect(page.locator("#splashGateUpgradeMsg")).to_contain_text("Downloading")
    expect(page.locator("#splashGateUpgradeBtn")).to_be_disabled()
    expect(page.locator("#splashGateStartBtn")).to_be_disabled()
    page.evaluate("splashGateUpgrade(); splashGateDismiss(); splashGateStart()")
    assert requests == ["POST"]
    assert starts == []
    expect(page.locator("#splashGateOverlay")).to_be_visible()
    page.route(
        "**/api/splash/setup/progress",
        lambda r: r.fulfill(
            json={
                "in_progress": False,
                "percent": 100,
                "message": "Installation complete",
                "result": {
                    "success": True,
                    "version": "Splash! 0.3.0",
                    "message": "Installed",
                },
            }
        ),
    )
    expect(page.locator("#splashGateUpgradeMsg")).to_contain_text("0.3.0")
    expect(page.locator("#splashGateStartBtn")).to_be_enabled()
    expect(page.locator("#splashGateUpgradeBtn")).to_be_hidden()
    assert starts == []


@pytest.mark.parametrize("failure", ["verification"])
def test_upgrade_failure_keeps_start_available_and_allows_explicit_retry(
    app_page, failure
):
    page = app_page
    page.route(
        "**/api/splash/setup/download",
        lambda r: r.fulfill(
            status=503 if failure == "request" else 200,
            json={"error": "Unavailable"}
            if failure == "request"
            else {"started": True},
        ),
    )
    page.route(
        "**/api/splash/setup/progress",
        lambda r: r.fulfill(
            status=503 if failure == "poll" else 200,
            json={
                "in_progress": False,
                "result": {"success": False, "message": "SHA256 verification failed"},
            },
        ),
    )
    prepare_upgrade(page)
    page.locator("#splashGateUpgradeBtn").click(timeout=2000)
    expect(page.locator("#splashGateUpgradeMsg")).to_contain_text(
        "failed", ignore_case=True
    )
    expect(page.locator("#splashGateUpgradeBtn")).to_be_enabled()
    expect(page.locator("#splashGateStartBtn")).to_be_enabled()


def test_lost_progress_keeps_start_blocked_and_status_retry_does_not_redownload(
    app_page,
):
    page = app_page
    downloads = []
    page.route(
        "**/api/splash/setup/download",
        lambda r: (
            downloads.append(r.request.method),
            r.fulfill(json={"started": True}),
        ),
    )
    page.route(
        "**/api/splash/setup/progress",
        lambda r: r.fulfill(status=503, json={"error": "Unavailable"}),
    )
    prepare_upgrade(page)
    page.locator("#splashGateUpgradeBtn").click(timeout=2000)
    expect(page.locator("#splashGateUpgradeMsg")).to_contain_text(
        "Check upgrade status"
    )
    expect(page.locator("#splashGateStartBtn")).to_be_disabled()
    page.route(
        "**/api/splash/setup/progress",
        lambda r: r.fulfill(
            json={
                "in_progress": False,
                "percent": 100,
                "result": {"success": True, "version": "Splash! 0.3.0"},
            }
        ),
    )
    page.locator("#splashGateUpgradeBtn").click()
    expect(page.locator("#splashGateStartBtn")).to_be_enabled()
    assert downloads == ["POST"]


def test_running_node_update_stays_visible_without_stopping_or_downloading(app_page):
    page = app_page
    mutations = []
    page.on(
        "request",
        lambda r: (
            mutations.append(r.url)
            if r.method == "POST" and "/splash/" in r.url
            else None
        ),
    )
    prepare_upgrade(page, running=True)
    expect(page.locator("#splashGateUpgradeBtn")).to_be_disabled()
    expect(page.locator("#splashGateUpgradeMsg")).to_contain_text("Stop Splash")
    page.wait_for_timeout(5500)
    expect(page.locator("#splashGateUpdateNotice")).to_be_visible()
    page.evaluate("splashGateUpgrade()")
    assert mutations == []


def test_upgrade_rechecks_process_before_download(app_page):
    page = app_page
    prepare_upgrade(page)
    page.route(
        "**/api/splash/node", lambda r: r.fulfill(json={"process_running": True})
    )
    downloads = []
    page.route(
        "**/api/splash/setup/download",
        lambda r: (downloads.append(r.request.url), r.fulfill(json={"started": True})),
    )
    page.locator("#splashGateUpgradeBtn").click(timeout=2000)
    expect(page.locator("#splashGateUpgradeMsg")).to_contain_text("Stop Splash")
    assert downloads == []


def test_undelivered_upgrade_recovers_from_idle_progress(app_page):
    page = app_page
    prepare_upgrade(page)
    page.route("**/api/splash/setup/download", lambda r: r.abort())
    page.route(
        "**/api/splash/setup/progress",
        lambda r: r.fulfill(
            json={"in_progress": False, "percent": 0, "message": "", "result": None}
        ),
    )
    page.locator("#splashGateUpgradeBtn").click()
    expect(page.locator("#splashGateUpgradeBtn")).to_have_text("Check upgrade status")
    page.locator("#splashGateUpgradeBtn").click()
    expect(page.locator("#splashGateStartBtn")).to_be_enabled(timeout=2000)
    expect(page.locator("#splashGateUpgradeBtn")).to_have_text("Upgrade Splash")


def test_requested_node_start_blocks_upgrade_before_process_appears(app_page):
    page = app_page
    prepare_upgrade(page)
    page.route("**/api/splash/node/start", lambda r: None)
    downloads = []
    page.route(
        "**/api/splash/setup/download",
        lambda r: (downloads.append(r.request.url), r.fulfill(json={"started": True})),
    )
    page.locator("#splashGateStartBtn").click()
    expect(page.locator("#splashGateUpgradeBtn")).to_be_disabled(timeout=2000)
    page.evaluate("splashGateUpgrade()")
    assert downloads == []
