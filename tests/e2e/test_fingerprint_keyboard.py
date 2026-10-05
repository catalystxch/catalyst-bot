"""Wallet fingerprint choices must work without a mouse or wallet mutation."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
GUI = Path(__file__).resolve().parents[2] / "bot_gui.html"


@pytest.mark.parametrize(
    ("show_picker", "card_selector", "select_function"),
    [
        (
            "startupShowFingerprints",
            "#startupFpCards .fp-card",
            "startupSelectFingerprint",
        ),
        ("showWalletPickerModal", "#walletPickerCards .fp-card", "walletPickerSelect"),
    ],
)
def test_fingerprint_card_is_named_button_and_activates_by_keyboard(
    page, show_picker, card_selector, select_function
):
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """async ({showPicker, selectFunction}) => {
            window.__fingerprintSelections = [];
            apiFetch = async () => new Response(JSON.stringify({
                success: true,
                fingerprints: [{label: 'Harvestr test wallet', fingerprint: '3702373391'}]
            }));
            walletSwitchLockedReason = () => '';
            window[selectFunction] = (fingerprint) => {
                window.__fingerprintSelections.push(fingerprint);
            };
            if (showPicker === 'showWalletPickerModal') {
                document.getElementById('startupOverlay').classList.add('hidden');
            }
            await window[showPicker]();
        }""",
        {"showPicker": show_picker, "selectFunction": select_function},
    )

    card = page.locator(card_selector)
    expect(card).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 700})
    card_box = card.bounding_box()
    list_box = card.locator("..").bounding_box()
    assert card_box["x"] + card_box["width"] <= list_box["x"] + list_box["width"] + 1
    expect(
        page.get_by_role("button", name="Harvestr test wallet 3702373391 →")
    ).to_have_count(1)
    card.focus()
    page.keyboard.press("Enter")
    page.keyboard.press("Space")
    assert page.evaluate("window.__fingerprintSelections") == [
        "3702373391",
        "3702373391",
    ]
