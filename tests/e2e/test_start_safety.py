"""Startup must never advertise safety readiness from coin readiness alone."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
GUI = Path(__file__).resolve().parents[2] / "bot_gui.html"


def _ready_setup(page, mode="blocked"):
    # The real GUI runs, but no requests can reach a wallet or trading API.
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")
    page.evaluate(
        """mode => {
            currentCAT = {asset_id: 'ab'.repeat(32), wallet_id: 2,
                          name: 'Test CAT', ticker_id: 'TEST_XCH'};
            _pairSelectedByUser = true;
            const selector = document.getElementById('catSelector');
            selector.replaceChildren(new Option('Test CAT', currentCAT.asset_id));
            settingsReviewed = true;
            localStorage.setItem('settingsReviewed', 'true');
            localStorage.setItem('settingsReviewedAssetId', currentCAT.asset_id);
            coinPrepStatus = 'done';
            const safety = {
                allowed: mode !== 'blocked',
                reason_code: mode === 'blocked' ? 'COIN_PREP_EFFECT_UNKNOWN' : '',
                source: 'process',
                lease: {active: true, owner: 'this_run', owned_by_this_run: true},
                recovery: {freshness: {valid: true, age_seconds: 0, max_age_seconds: 30,
                    observed_at_utc: new Date(Date.now() - (mode === 'stale' ? 60000 : 0)).toISOString(),
                    provenance: 'live_gate_and_durable_snapshot'}},
            };
            if (mode === 'malformed') safety.allowed = 'true';
            bot_state = {running: false, offers: {buy: [], sell: []},
                chia_health: {wallet_reachable: true, wallet_synced: true},
                runtime_safety: mode === 'missing' ? undefined : safety};
            updateStartupChecklist(bot_state);
        }""",
        mode,
    )


@pytest.mark.parametrize("mode", ["blocked", "missing", "stale", "malformed"])
def test_start_safety_never_claims_ready_for_blocked_or_unknown_state(page, mode):
    _ready_setup(page, mode)
    assert page.evaluate("canAttemptBotStart()") is False
    expect(page.locator("#startupStepStart")).not_to_contain_text(
        "All pre-flight checks look good"
    )
    expect(page.locator("#startupReadyCtaBtn")).to_be_disabled()


def test_start_safety_fresh_allowed_state_keeps_prepared_start_available(page):
    _ready_setup(page, "allowed")
    assert page.evaluate("canAttemptBotStart()") is True
    expect(page.locator("#startupReadyCtaBtn")).to_be_enabled()


def test_start_safety_failure_explains_reason_and_does_not_dispatch(page):
    _ready_setup(page)
    result = page.evaluate(
        """async () => {
            let dispatched = 0;
            checkForResume = async () => false;
            apiFetch = async () => {
                dispatched++;
                return new Response(JSON.stringify({success: false,
                    error: 'mutation_gate_blocked', reason: 'COIN_PREP_EFFECT_UNKNOWN'}));
            };
            await startBot();
            return {dispatched, message: formatError({error:'mutation_gate_blocked',
                reason: 'COIN_PREP_EFFECT_UNKNOWN'})};
        }"""
    )
    assert result["dispatched"] == 0
    assert "COIN_PREP_EFFECT_UNKNOWN" in result["message"]
    expect(page.locator("#startupStepStart")).to_contain_text(
        "COIN_PREP_EFFECT_UNKNOWN"
    )


def test_start_safety_error_uses_allowlisted_reason_not_untrusted_detail(page):
    _ready_setup(page)
    message = page.evaluate(
        """formatError({error:'mutation_gate_blocked', reason:'<script>secret</script>'})"""
    )
    assert "secret" not in message
    assert "safety" in message.lower()


def test_start_safety_server_denial_remains_visible_until_fresh_status(page):
    _ready_setup(page, "allowed")
    page.evaluate("""async () => {
        checkForResume = async () => false;
        apiFetch = async () => new Response(JSON.stringify({success: false,
            error: 'mutation_gate_blocked', reason: 'COIN_PREP_EFFECT_UNKNOWN'}));
        await startBot();
    }""")
    assert page.evaluate("canAttemptBotStart()") is False
    expect(page.locator("#startupStepStart")).to_contain_text(
        "COIN_PREP_EFFECT_UNKNOWN"
    )
    expect(page.locator("#startBtn")).to_be_disabled()
    expect(page.locator("#startupReadyCtaBtn")).to_be_disabled()


def test_start_safety_failed_poll_invalidates_previously_allowed_state(page):
    _ready_setup(page, "allowed")
    page.evaluate("""async () => {
        apiFetch = async () => { throw new Error('offline'); };
        await fetchStatus();
    }""")
    assert page.evaluate("canAttemptBotStart()") is False
    expect(page.locator("#startBtn")).to_be_disabled()


def test_start_safety_force_start_cannot_bypass_runtime_block(page):
    _ready_setup(page)
    assert (
        page.evaluate("""async () => {
        let calls = 0;
        apiFetch = async () => { calls++; return new Response('{}'); };
        await forceStartBot();
        return calls;
    }""")
        == 0
    )


def test_start_safety_ready_display_expires_while_status_poll_is_stalled(page):
    page.clock.install()
    _ready_setup(page, "allowed")
    page.evaluate("""() => {
        // A desktop bridge request can remain pending without a fetch timeout.
        fetchStatus = () => new Promise(() => {});
    }""")
    page.clock.fast_forward(31000)
    expect(page.locator("#startupStepStart")).not_to_contain_text(
        "All pre-flight checks look good"
    )
    expect(page.locator("#startupReadyCtaBtn")).to_be_disabled()


def test_start_safety_preserves_every_trusted_mutation_gate_reason(page):
    import mutation_gate

    _ready_setup(page)
    messages = page.evaluate(
        """reasons => reasons.map(reason => ({reason,
        message: formatError({error: 'mutation_gate_blocked', reason})}))""",
        sorted(mutation_gate._ALLOWED_REASON_CODES),
    )
    for result in messages:
        assert result["reason"] in result["message"]


def test_tibetswap_outage_does_not_make_coin_prep_warning_require_tibet(page):
    _ready_setup(page, "allowed")
    page.evaluate("""() => {
        _pairDataReadyAssetId = currentCAT.asset_id;
        _catSwitchTargetAssetId = '';
        window._smartMidPrice = 0;
        bot_state.pricing = {mid: 0};
        document.getElementById('configTradeXch').value = '1';
        document.getElementById('configMaxBuy').value = '1';
        document.getElementById('configMaxSell').value = '1';
        document.getElementById('configTierEnabled').checked = false;
        updateCoinPrepPreview();
    }""")
    expect(page.locator("#coinPrepWarning")).to_contain_text(
        "Waiting for current market pricing"
    )
    expect(page.locator("#coinPrepWarning")).not_to_contain_text(
        "TibetSwap is reachable"
    )
    assert page.evaluate("tradingSettingsImpossible") is True
