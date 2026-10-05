"""Wallet picker controls stay usable by keyboard and assistive technology."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
GUI = Path(__file__).resolve().parents[2] / "bot_gui.html"


def _load_picker_page(page, label="Harvestr test wallet"):
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """label => {
            document.getElementById('startupOverlay').style.display = 'none';
            apiFetch = async () => new Response(JSON.stringify({
                success: true,
                fingerprints: [{label, fingerprint: '3702373391'}]
            }));
            walletSwitchLockedReason = () => '';
        }""",
        label,
    )


def test_toolbar_wallet_trigger_opens_with_enter(page):
    _load_picker_page(page)
    trigger = page.get_by_role("button", name="Change wallet fingerprint")
    expect(trigger).to_be_visible()
    trigger.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#walletPickerModal")).to_have_class("modal active")


def test_wallet_picker_traps_focus_and_restores_opener(page):
    _load_picker_page(page)
    page.evaluate(
        """() => {
            const opener = document.createElement('button');
            opener.id = 'testWalletOpener';
            opener.textContent = 'Open wallet picker';
            opener.onclick = showWalletPickerModal;
            document.body.appendChild(opener);
        }"""
    )
    opener = page.locator("#testWalletOpener")
    opener.focus()
    opener.evaluate("element => element.click()")
    card = page.locator("#walletPickerCards .fp-card")
    close = page.locator("#walletPickerModal button", has_text="Close")
    expect(card).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(close).to_be_focused()
    page.keyboard.press("Tab")
    expect(card).to_be_focused()
    close.focus()
    page.keyboard.press("Tab")
    expect(card).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("#walletPickerModal")).not_to_have_class("modal active")
    expect(opener).to_be_focused()


def test_long_wallet_label_wraps_inside_picker(page):
    _load_picker_page(page, "A very long wallet label " + "W" * 160)
    page.set_viewport_size({"width": 390, "height": 700})
    page.evaluate("showWalletPickerModal()")
    card = page.locator("#walletPickerCards .fp-card")
    expect(card).to_be_visible()
    geometry = card.evaluate(
        """card => ({
            clientWidth: card.clientWidth,
            scrollWidth: card.scrollWidth,
            right: card.getBoundingClientRect().right,
            labelRight: card.querySelector('.fp-card-label').getBoundingClientRect().right,
            arrowRight: card.querySelector('.fp-card-arrow').getBoundingClientRect().right,
        })"""
    )
    assert geometry["scrollWidth"] <= geometry["clientWidth"] + 1
    assert geometry["labelRight"] <= geometry["right"] + 1
    assert geometry["arrowRight"] <= geometry["right"] + 1


def test_disabled_start_button_describes_its_reason(page):
    _load_picker_page(page)
    start = page.locator("#startBtn")
    expect(start).to_be_disabled()
    assert (
        "startupStepStartDetail"
        in (start.get_attribute("aria-describedby") or "").split()
    )
    assert page.locator("#startupStepStartDetail").inner_text().strip()
