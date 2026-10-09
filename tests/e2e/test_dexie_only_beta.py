"""Browser regressions for the v1.4 Dexie-only beta surface."""

import re

import pytest


pytestmark = pytest.mark.e2e


def test_splash_setting_is_inert_and_not_user_toggleable(app_page):
    toggle = app_page.locator("#configSplashEnabled")

    assert toggle.count() == 1
    assert toggle.is_disabled()
    assert toggle.get_attribute("type") == "hidden"
    assert (
        app_page.get_by_text(
            re.compile("Dexie-only beta.*Splash P2P is unavailable", re.I)
        ).count()
        == 1
    )
    assert app_page.locator("#splashNetworkCard").is_hidden()


def test_splash_startup_gate_makes_no_api_request_in_dexie_only_beta(app_page):
    splash_requests = []
    app_page.on(
        "request",
        lambda request: (
            splash_requests.append(request.url)
            if "/api/splash/" in request.url
            else None
        ),
    )

    app_page.evaluate(
        """async () => {
            await splashGateBegin();
            await toggleSplashListening();
            await setupSplashNode();
            await splashGateInstall();
            await splashGateStart();
            await checkSplashInstalled();
            await refreshVisibleSplashNodeStatus();
        }"""
    )
    app_page.wait_for_timeout(250)

    assert splash_requests == []
    assert app_page.locator("#splashGateOverlay").is_hidden()
