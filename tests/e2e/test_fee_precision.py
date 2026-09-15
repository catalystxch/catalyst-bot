"""Settings must display the full configured XCH transaction fee."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
GUI = Path(__file__).resolve().parents[2] / "bot_gui.html"


def test_fee_status_hint_preserves_all_meaningful_xch_decimals(page):
    """A 10-decimal fee must not be rounded to the old 8-decimal display."""
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")

    page.evaluate(
        """() => {
            document.getElementById('configTransactionFeeEnabled').checked = true;
            document.getElementById('configTransactionFeeXch').value = '0.0000130791';
            document.getElementById('configFeeCoinSizeXch').value = '0.001';
            document.getElementById('configFeePrepCount').value = '50';
            document.getElementById('configTierEnabled').checked = true;
            renderFeeStatusHint();
        }"""
    )

    expect(page.locator("#feeStatusHint")).to_contain_text(
        "0.0000130791 XCH"
    )
