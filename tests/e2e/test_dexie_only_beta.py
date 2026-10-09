"""Browser regressions for optional Splash publication and startup."""

import pytest


pytestmark = pytest.mark.e2e


def test_optional_splash_setting_and_status_are_available(app_page):
    toggle = app_page.locator("#configSplashEnabled")

    assert toggle.count() == 1
    assert toggle.get_attribute("type") == "checkbox"
    assert not toggle.is_disabled()
    app_page.evaluate("v4SwitchView('intel')")
    assert app_page.locator("#splashNetworkCard").is_visible()
    app_page.evaluate("updateSettingsLocks(true)")
    assert toggle.is_disabled()
    assert app_page.locator("#splashLock").count() == 1
    app_page.evaluate("updateSettingsLocks(false)")
    assert not toggle.is_disabled()


def test_splash_startup_gate_checks_node_before_continuing(app_page):
    app_page.route(
        "**/api/config",
        lambda route: route.fulfill(status=200, json={"SPLASH_ENABLED": True}),
    )
    splash_requests = []
    app_page.on(
        "request",
        lambda request: (
            splash_requests.append(request.url)
            if "/api/splash/" in request.url
            else None
        ),
    )

    app_page.evaluate("splashGateBegin()")
    app_page.wait_for_timeout(500)

    assert any("/api/splash/setup/check" in url for url in splash_requests)
    assert app_page.locator("#splashGateOverlay").is_visible()


def test_disabled_optional_splash_skips_startup_install_gate(app_page):
    app_page.route(
        "**/api/config",
        lambda route: route.fulfill(status=200, json={"SPLASH_ENABLED": False}),
    )
    splash_requests = []
    app_page.on(
        "request",
        lambda request: (
            splash_requests.append(request.url)
            if "/api/splash/setup/check" in request.url
            else None
        ),
    )

    app_page.evaluate("splashGateBegin()")
    app_page.wait_for_timeout(300)

    assert not splash_requests
    assert app_page.locator("#splashGateOverlay").is_hidden()


def test_running_splash_node_does_not_claim_peer_broadcast(app_page):
    app_page.route(
        "**/api/config",
        lambda route: route.fulfill(status=200, json={"SPLASH_ENABLED": True}),
    )
    app_page.route(
        "**/api/splash/setup/check",
        lambda route: route.fulfill(
            status=200, json={"installed": True, "version": "0.2.0"}
        ),
    )
    app_page.route(
        "**/api/splash/node",
        lambda route: route.fulfill(
            status=200,
            json={"process_running": True, "api_reachable": True, "peers": 0},
        ),
    )

    app_page.evaluate("splashGateBegin()")

    assert app_page.locator("#splashGateTitle").inner_text() == "Splash node running"
    assert (
        "Peer broadcast is unverified"
        in app_page.locator("#splashGateSubtitle").inner_text()
    )
