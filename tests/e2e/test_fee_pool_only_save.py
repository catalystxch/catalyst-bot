"""The fee reserve controls can be saved without submitting all Setup fields."""

from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e
GUI = Path(__file__).resolve().parents[2] / "bot_gui.html"


def _open_settings(page):
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """() => {
            document.getElementById('startupOverlay').style.display = 'none';
            document.querySelectorAll('.v4-view').forEach(v => v.classList.remove('active'));
            document.getElementById('v4View-settings').classList.add('active');
            bot_state = {running: false};
            window.__feeSaveCalls = [];
            apiFetch = async (path, options={}) => {
                window.__feeSaveCalls.push({path: String(path), method: options.method || 'GET',
                    body: options.body ? JSON.parse(options.body) : null});
                if (String(path).endsWith('/config') && options.method === 'POST')
                    return new Response(JSON.stringify({success: true, updated:
                        ['FEE_PREP_COUNT', 'FEE_COIN_SIZE_XCH']}), {status: 200});
                return new Response(JSON.stringify({success: true}), {status: 200});
            };
        }"""
    )


def test_fee_pool_save_sends_only_two_fields_even_when_other_settings_are_present(page):
    _open_settings(page)
    page.locator("#configTransactionFeeEnabled").uncheck()
    page.locator("#configSageChangeAddress").check()
    page.locator("#configTradeXch").fill("")
    page.locator("#configFeeCoinSizeXch").fill("0.001")
    page.locator("#configFeePrepCount").fill("50")
    page.locator("#saveFeePoolOnlyBtn").click()
    page.wait_for_function("window.__feeSaveCalls.some(c => c.method === 'POST')")
    writes = [
        c for c in page.evaluate("window.__feeSaveCalls") if c["method"] == "POST"
    ]
    assert writes == [
        {
            "path": "/api/config",
            "method": "POST",
            "body": {"fee_prep_count": 50, "fee_coin_size_xch": "0.001"},
        }
    ]
    assert page.locator("#configTransactionFeeEnabled").is_checked() is False
    assert page.locator("#configSageChangeAddress").is_checked() is True


def test_fee_pool_save_refuses_invalid_values_without_writing(page):
    _open_settings(page)
    page.locator("#configFeeCoinSizeXch").fill("0")
    page.locator("#configFeePrepCount").fill("50")
    page.locator("#saveFeePoolOnlyBtn").click()
    assert not any(
        c["method"] == "POST" for c in page.evaluate("window.__feeSaveCalls")
    )


def test_fee_pool_save_refuses_running_bot(page):
    _open_settings(page)
    page.evaluate("bot_state.running = true")
    page.locator("#configFeeCoinSizeXch").fill("0.001")
    page.locator("#configFeePrepCount").fill("50")
    page.locator("#saveFeePoolOnlyBtn").click()
    assert not any(
        c["method"] == "POST" for c in page.evaluate("window.__feeSaveCalls")
    )
