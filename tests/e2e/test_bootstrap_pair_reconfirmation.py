"""An expired campaign must not strand explicit same-pair confirmation."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from .test_coin_prep_fee_approval import _open_gui

pytestmark = pytest.mark.e2e
ASSET = "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105"


def _post_stop_pair(page):
    packaged_gui = os.environ.get("CATALYST_PAIR_TEST_GUI")
    if packaged_gui:
        page.goto(Path(packaged_gui).resolve().as_uri(), wait_until="domcontentloaded")
    else:
        _open_gui(page)
    return page.evaluate(
        """asset => {
            document.getElementById('startupOverlay').style.display = 'none';
            document.querySelectorAll('.v4-view').forEach(v => v.classList.remove('active'));
            document.getElementById('v4View-settings').classList.add('active');
            currentCAT = {asset_id: asset, name: 'Monkeyzoo Token', wallet_id: 2};
            bot_state = {running: false};
            _pairSelectedByUser = false;
            _resumeSessionSummary = null;
            _bootstrapActiveCampaign = null;
            _pairDataReadyAssetId = asset;
            for (const id of ['catSelector', 'configCatSelector']) {
                const sel = document.getElementById(id);
                sel.innerHTML = '';
                const blank = new Option('-- Choose a Trading Pair --', '');
                blank.disabled = true;
                sel.add(blank);
                const mz = new Option('Monkeyzoo Token (MZ_XCH)', asset);
                mz.dataset.wallet = '2'; mz.dataset.ticker = 'MZ_XCH';
                mz.dataset.name = 'Monkeyzoo Token'; mz.dataset.decimals = '3';
                sel.add(mz); sel.value = asset;
            }
            updateSettingsPairControl(currentCAT);
            return {
                explicit: _pairSelectedByUser,
                dashboard: getDashboardSelectedPair({requireExplicit: true}),
                settings: document.getElementById('settingsPairDisplayStatus').textContent,
            };
        }""",
        ASSET,
    )


def test_post_stop_settings_do_not_claim_unconfirmed_pair_is_confirmed(page):
    state = _post_stop_pair(page)
    assert state["explicit"] is False
    assert state["dashboard"]["selected"] is False
    assert state["settings"] == "Confirm trading pair for this run"


def test_same_pair_reconfirmation_starts_with_no_preselected_choice(page):
    _post_stop_pair(page)
    page.locator("#settingsPairChangeBtn").click()
    # Model the queued config response followed by normal label refreshes.
    page.evaluate("""() => {
        document.getElementById('configCatSelector').value = currentCAT.asset_id;
        updateCoinPrepPreview();
        refreshReserveDisplays();
    }""")
    expect(page.locator("#configCatSelector")).to_have_value("")
    assert page.evaluate("_pairSelectedByUser") is False
    assert (
        page.evaluate("getDashboardSelectedPair({requireExplicit:true}).selected")
        is False
    )


def test_stop_refresh_removes_confirmed_label_without_accepting_restored_pair(page):
    _post_stop_pair(page)
    page.evaluate(
        """asset => {
            _bootstrapActiveCampaign = {asset_id: asset};
            updateSettingsPairControl(currentCAT);
        }""",
        ASSET,
    )
    expect(page.locator("#settingsPairDisplayStatus")).to_have_text(
        "App-wide trading pair confirmed"
    )
    page.evaluate("_bootstrapRenderStatus({active:false,campaign:null})")
    assert (
        page.evaluate("getDashboardSelectedPair({requireExplicit:true}).selected")
        is False
    )
    expect(page.locator("#settingsPairDisplayStatus")).to_have_text(
        "Confirm trading pair for this run"
    )


@pytest.mark.parametrize("accepted", [True, False])
def test_same_pair_selection_requires_server_acceptance_before_preview(page, accepted):
    _post_stop_pair(page)
    page.evaluate(
        """({asset, accepted}) => {
            _startupGatesComplete = false;
            window.__writes = [];
            apiFetch = async (path, options = {}) => {
                const url = String(path);
                if (options.method === 'POST') {
                    window.__writes.push({url, body: JSON.parse(options.body)});
                    if (!url.endsWith('/cat/select') && !url.endsWith('/bootstrap/preview'))
                        throw new Error('Unexpected mutation: ' + url);
                }
                const data = url.endsWith('/cat/select') ? {success: accepted}
                    : url.endsWith('/bootstrap/preview') ? {
                        success:true, preview_digest:'a'.repeat(64), liquidity_mode:'two_sided',
                        campaign:{asset_id:asset,xch_budget:'216.7',cat_budget:'2400000',
                            anchor_price:'0.000075',minimum_price:'0.0000375',maximum_price:'0.00015'},
                        plan:{deployment_fraction:'0.1',sides:{buy:{levels:[1,2,3]},sell:{levels:[1,2,3]}}}}
                    : {};
                return new Response(JSON.stringify(data), {status:200,
                    headers:{'Content-Type':'application/json'}});
            };
            document.getElementById('bootstrapAnchorPrice').value = '0.000075';
            document.getElementById('bootstrapExpiryDays').value = '1';
            document.getElementById('bootstrapXchBudget').value = '216.7';
            document.getElementById('bootstrapCatBudget').value = '2400000';
            document.getElementById('bootstrapFeeBudget').value = '0.01';
        }""",
        {"asset": ASSET, "accepted": accepted},
    )
    page.locator("#settingsPairChangeBtn").click()
    page.evaluate("""() => {
        document.getElementById('configCatSelector').value = currentCAT.asset_id;
        updateCoinPrepPreview();
        refreshReserveDisplays();
    }""")
    expect(page.locator("#configCatSelector")).to_have_value("")
    page.locator("#configCatSelector").select_option(ASSET)
    page.wait_for_function("() => !_catSwitchInProgress")
    assert page.evaluate("_pairSelectedByUser") is accepted
    expect(page.locator("#configCatSelector")).to_have_value(ASSET)
    assert (
        page.evaluate("getDashboardSelectedPair({requireExplicit:true}).selected")
        is accepted
    )
    page.evaluate("bootstrapPreviewCampaign()")
    writes = page.evaluate("window.__writes")
    assert writes[0]["body"] == {
        "asset_id": ASSET,
        "ticker_id": "MZ_XCH",
        "wallet_id": 2,
        "name": "Monkeyzoo Token",
        "decimals": 3,
    }
    assert len(writes) == (2 if accepted else 1)
    if accepted:
        assert writes[1]["body"]["asset_id"] == ASSET
        assert writes[1]["body"]["xch_budget"] == "216.7"
        assert writes[1]["body"]["cat_budget"] == "2400000"
        expect(page.locator("#bootstrapStatusPanel")).to_contain_text(
            "REVIEW ONLY — no wallet action"
        )
    else:
        expect(page.locator("#bootstrapStatusPanel")).to_have_text(
            "Choose and verify a CAT trading pair first."
        )
    assert page.evaluate("_bootstrapActiveCampaign") is None
