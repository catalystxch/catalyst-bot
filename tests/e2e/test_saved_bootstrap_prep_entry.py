"""Saved campaign review must not save blank settings or resume old cancels."""
import pytest
from .test_coin_prep_fee_approval import _open_gui

pytestmark = pytest.mark.e2e
ASSET = "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105"
CAMPAIGN = "128976c99d666d4469ccb3e5d16848bdb18e2ab5989f27029730c7856b56a2b1"


def prepare(page, failure=""):
    _open_gui(page)
    page.evaluate("""({asset,id,failure}) => {
        document.getElementById('startupOverlay').style.display='none';
        document.querySelectorAll('.v4-view').forEach(v=>v.classList.remove('active'));
        document.getElementById('v4View-settings').classList.add('active');
        currentCAT={asset_id:asset,wallet_id:2,name:'Monkeyzoo Token',decimals:3};
        bot_state={running:failure==='running',pricing:{mid:'0.000075'},
            balances:{xch:{spendable:220},cat:{spendable:3667351}}};
        settingsReviewed=false;localStorage.setItem('settingsReviewed','false');
        _pairSelectedByUser=true;_pairDataReadyAssetId=asset;
        _bootstrapActiveCampaign={campaign_id:id,revision:0,status:'active',asset_id:asset,
            wallet_fingerprint:3702373391,network:'mainnet',xch_budget:'195.03',
            cat_budget:'2695099.98',fee_budget_xch:'0.01',anchor_price:'0.000075',
            minimum_price:'0.0000375',maximum_price:'0.00015',
            expires_at:new Date(Date.now()+172800000).toISOString()};
        _coinPrepFeeRecoveryIntent={campaign_id:'c'.repeat(64),campaign_revision:3,action:'bootstrap_stop'};
        for(const field of ['configTradeXch','configSpreadBps','configFeePrepCount','configFeeCoinSizeXch'])
            document.getElementById(field).value='';
        window.__calls=[];
        apiFetch=async(path,options={})=>{
            const url=String(path);window.__calls.push({url,method:options.method||'GET',body:options.body||null});
            if(options.method && options.method!=='GET'
                && !(options.method==='POST' && url.endsWith('/coin-prep/fee-preview')))
                throw new Error('Unexpected write '+url);
            if(url.endsWith('/bootstrap/status')) {
                if(failure==='unavailable')return new Response('{}',{status:503});
                const campaign={..._bootstrapActiveCampaign};
                if(failure==='revision')campaign.revision=1;
                if(failure==='asset')campaign.asset_id='d'.repeat(64);
                if(failure==='stopped')campaign.status='stopped';
                if(failure==='expired')campaign.expires_at='2020-01-01T00:00:00Z';
                return new Response(JSON.stringify({success:true,active:true,campaign}),{status:200});
            }
            if(url.endsWith('/config'))return new Response(JSON.stringify({FEE_PREP_COUNT:failure==='fee_pool'?0:50,
                FEE_COIN_SIZE_XCH:failure==='fee_size'?'0':'0.001',
                XCH_RESERVE:failure==='missing_reserve'?null:'23.5',CAT_RESERVE:'300000',
                COIN_PREP_MULTIPLIER:1}),{status:200});
            if(url.includes('/coin-prep/verify?')) {
                if(failure==='async_drift')_bootstrapActiveCampaign.revision=1;
                return new Response(JSON.stringify({success:failure!=='verify_failure',
                    bootstrap_campaign_id:id,
                    bootstrap_campaign_revision:failure==='missing_revision'?null:0,
                    all_sufficient:failure!=='needs_prep',
                    balance_sufficient:failure==='missing_balance'?null:true}),{status:200});
            }
            if(url.endsWith('/coin-prep/fee-preview'))return new Response(JSON.stringify({success:false,
                available:false,error:'Test stops at native fee review'}),{status:409});
            throw new Error('Unexpected request '+url);
        };
        _bootstrapRenderStatus({active:true,campaign:_bootstrapActiveCampaign});
    }""", {"asset": ASSET, "id": CAMPAIGN, "failure": failure})


def test_saved_campaign_review_preserves_settings_and_rechecks_current_coins(page):
    prepare(page)
    button = page.locator('#bootstrapPrepReviewBtn')
    assert button.count() == 1, 'Saved campaigns need a native preparation review entry'
    button.click()
    page.wait_for_function("window.__calls.some(c=>c.url.includes('/coin-prep/verify?'))")
    page.wait_for_function("coinPrepStatus==='done'")
    calls = page.evaluate('window.__calls')
    assert all(c['method'] == 'GET' for c in calls)
    verify = next(c['url'] for c in calls if '/coin-prep/verify?' in c['url'])
    assert 'bootstrap_campaign_id=' + CAMPAIGN in verify
    assert 'bootstrap_campaign_revision=0' in verify
    assert 'xch_reserve=23.5' in verify and 'cat_reserve=300000' in verify
    assert page.evaluate('settingsReviewed') is False
    assert page.evaluate("localStorage.getItem('settingsReviewed')") == 'false'
    assert page.locator('#configFeePrepCount').input_value() == ''
    assert page.locator('#configFeeCoinSizeXch').input_value() == ''
    assert page.evaluate('isSettingsReviewedForCurrentPair()') is True
    assert page.evaluate('_coinPrepFeeRecoveryIntent') is None
    options = page.evaluate('buildCoinPrepFeePreviewOptions()')
    assert options['bootstrap_campaign_id'] == CAMPAIGN
    assert 'cancellation_recovery_action' not in options
    page.evaluate('_bootstrapActiveCampaign.revision=1')
    assert page.evaluate('isSettingsReviewedForCurrentPair()') is False


@pytest.mark.parametrize('failure', [
    'running','revision','asset','stopped','expired','unavailable','fee_pool',
    'fee_size','missing_reserve',
])
def test_saved_campaign_review_refuses_drift_or_missing_fee_pool(page, failure):
    prepare(page, failure)
    button = page.locator('#bootstrapPrepReviewBtn')
    assert button.count() == 1
    if failure == 'running':
        assert button.is_disabled()
        return
    button.click()
    page.wait_for_function("!document.getElementById('bootstrapPrepReviewBtn').disabled")
    assert not any('/coin-prep/verify?' in c['url'] for c in page.evaluate('window.__calls'))
    assert page.evaluate('isSettingsReviewedForCurrentPair()') is False
    assert page.evaluate('settingsReviewed') is False


@pytest.mark.parametrize('failure', [
    'verify_failure','async_drift','missing_revision','missing_balance',
])
def test_changed_or_failed_coin_verification_cannot_mark_campaign_reviewed(page, failure):
    prepare(page, failure)
    page.locator('#bootstrapPrepReviewBtn').click()
    page.wait_for_function("!document.getElementById('bootstrapPrepReviewBtn').disabled")
    assert page.evaluate('isSettingsReviewedForCurrentPair()') is False
    assert page.evaluate('coinPrepStatus') == 'none'
    assert all(c['method'] == 'GET' for c in page.evaluate('window.__calls'))


def test_needed_preparation_opens_new_campaign_fee_review_without_writes(page):
    prepare(page, 'needs_prep')
    page.locator('#bootstrapPrepReviewBtn').click()
    page.wait_for_function("window.__calls.some(c=>c.url.endsWith('/coin-prep/fee-preview'))")
    calls = page.evaluate('window.__calls')
    assert all(c['method'] == 'GET' or (
        c['method'] == 'POST' and c['url'].endswith('/coin-prep/fee-preview')
    ) for c in calls)
    assert page.locator('#coinPrepConfirmOverlay').evaluate("el=>el.classList.contains('active')")
    assert page.evaluate('_coinPrepFeePreviewOptions.bootstrap_campaign_id') == CAMPAIGN
    assert page.evaluate('_coinPrepFeePreviewOptions.cancellation_recovery_action || null') is None
    assert page.evaluate('settingsReviewed') is False
