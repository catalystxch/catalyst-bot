"""A failed Sage login must stop the startup spinner and offer recovery."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e
GUI = (Path(__file__).resolve().parents[2] / "bot_gui.html").as_uri()


def test_failed_sage_login_shows_retry_instead_of_polling_forever(page):
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI, wait_until="domcontentloaded")
    page.evaluate(
        """() => {
            apiFetch = async () => new Response(JSON.stringify({
                phase: 'error', message: 'Wallet startup status unavailable',
                wallet_type: 'sage', sage_version: '0.13.0',
                sage_version_supported: true
            }), {headers: {'Content-Type': 'application/json'}});
            startupPollUntilReady();
        }"""
    )

    expect(page.locator("#startupError")).to_be_visible()
    expect(page.locator("#startupProgressTrack")).to_be_hidden()
