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


def test_coin_prep_pool_exceeding_post_reserve_balance_blocks_save(page):
    """The GUI must reject a prep plan the worker will reject as pool_exceeds_avail."""
    _ready_setup(page, "allowed")
    result = page.evaluate(
        """() => {
            _pairDataReadyAssetId = currentCAT.asset_id;
            _catSwitchTargetAssetId = '';
            bot_state.balances = mergeVerifiedWalletBalances({
                xch: {total: 10, confirmed: 10, spendable: 10},
                cat: {total: 1000000, confirmed: 1000000, spendable: 1000000},
            }, currentCAT.asset_id);
            bot_state.pricing = {mid: 1};
            document.getElementById('configTradeXch').value = '1';
            document.getElementById('configMaxBuy').value = '4';
            document.getElementById('configMaxSell').value = '4';
            document.getElementById('configTierEnabled').checked = false;
            document.getElementById('configCoinPrepHeadroomPct').value = '10';
            document.getElementById('configXchReserve').value = '2';
            document.getElementById('configCatReserve').value = '0';
            document.getElementById('configTransactionFeeEnabled').checked = false;
            const sniper = document.getElementById('configSniperEnabled');
            if (sniper) sniper.checked = false;
            updateCoinPrepPreview();
            return {
                impossible: tradingSettingsImpossible,
                valid: validateSettingsForm(),
                warning: document.getElementById('coinPrepWarning').textContent,
                critical: document.getElementById('coinPrepWarning').dataset.critical,
            };
        }"""
    )

    assert result["impossible"] is True
    assert result["valid"] is False
    assert result["critical"] == "true"
    assert "available after reserve" in result["warning"]
    assert "Bot will still work" not in result["warning"]


def test_active_bootstrap_campaign_bypasses_legacy_reserve_warning_on_save(page):
    """A funded Bootstrap campaign must not be blocked by the obsolete Follow ladder."""
    _ready_setup(page, "allowed")
    result = page.evaluate(
        """() => {
            _pairDataReadyAssetId = currentCAT.asset_id;
            _catSwitchTargetAssetId = '';
            bot_state.balances = mergeVerifiedWalletBalances({
                xch: {total: 145.8086, confirmed: 145.8086, spendable: 145.8086},
                cat: {total: 702843.47, confirmed: 702843.47, spendable: 702843.47},
            }, currentCAT.asset_id);
            bot_state.pricing = {mid: 0.0000835};
            _bootstrapActiveCampaign = {
                campaign_id: 'campaign-live-regression',
                revision: 0,
                asset_id: currentCAT.asset_id,
                xch_budget: '72.8943',
                cat_budget: '351421.735',
                fee_budget_xch: '0.01',
            };

            // This legacy Follow plan cannot fit, but it is not the active authority.
            document.getElementById('configTradeXch').value = '2';
            document.getElementById('configMaxBuy').value = '45';
            document.getElementById('configMaxSell').value = '45';
            document.getElementById('configTierEnabled').checked = false;
            document.getElementById('configXchReserve').value = '15';
            document.getElementById('configCatReserve').value = '46000';

            updateCoinPrepPreview();
            const valid = validateSettingsForm();
            return {
                valid,
                impossible: tradingSettingsImpossible,
                xchCritical: document.getElementById('xchReserveWarning').dataset.critical,
                catCritical: document.getElementById('catReserveWarning').dataset.critical,
                preview: document.getElementById('coinPrepWarning').textContent,
            };
        }"""
    )

    assert result == {
        "valid": True,
        "impossible": False,
        "xchCritical": "false",
        "catCritical": "false",
        "preview": (
            "Bootstrap campaign active: Coin Prep is bound to the exact saved "
            "campaign revision and budgets; the legacy Smart Settings coin plan is bypassed."
        ),
    }


def test_coin_prep_pool_rejects_verified_zero_balance(page):
    """A verified zero balance is authoritative, not an unknown-balance sentinel."""
    _ready_setup(page, "allowed")
    result = page.evaluate(
        """() => {
            _pairDataReadyAssetId = currentCAT.asset_id;
            _catSwitchTargetAssetId = '';
            bot_state.balances = mergeVerifiedWalletBalances({
                xch: {total: 0, confirmed: 0, spendable: 0},
                cat: {total: 1000000, confirmed: 1000000, spendable: 1000000},
            }, currentCAT.asset_id);
            bot_state.pricing = {mid: 1};
            document.getElementById('configTradeXch').value = '1';
            document.getElementById('configMaxBuy').value = '1';
            document.getElementById('configMaxSell').value = '0';
            document.querySelector('input[name="liquidityMode"][value="buy_only"]').checked = true;
            document.getElementById('configTierEnabled').checked = false;
            document.getElementById('configCoinPrepHeadroomPct').value = '10';
            document.getElementById('configXchReserve').value = '0';
            document.getElementById('configTransactionFeeEnabled').checked = false;
            const sniper = document.getElementById('configSniperEnabled');
            if (sniper) sniper.checked = false;
            updateCoinPrepPreview();
            return {
                impossible: tradingSettingsImpossible,
                valid: validateSettingsForm(),
                warning: document.getElementById('coinPrepWarning').textContent,
            };
        }"""
    )

    assert result["impossible"] is True
    assert result["valid"] is False
    assert "available after reserve" in result["warning"]


def test_save_recomputes_coin_prep_gate_before_cancelling_debounce(page):
    """A rapid reserve edit followed by Save must validate the current inputs."""
    _ready_setup(page, "allowed")
    result = page.evaluate(
        """() => {
            _pairDataReadyAssetId = currentCAT.asset_id;
            _catSwitchTargetAssetId = '';
            bot_state.balances = mergeVerifiedWalletBalances({
                xch: {total: 10, confirmed: 10, spendable: 10},
                cat: {total: 1000000, confirmed: 1000000, spendable: 1000000},
            }, currentCAT.asset_id);
            bot_state.pricing = {mid: 1};
            document.getElementById('configTradeXch').value = '1';
            document.getElementById('configMaxBuy').value = '4';
            document.getElementById('configMaxSell').value = '4';
            document.getElementById('configTierEnabled').checked = false;
            document.getElementById('configCoinPrepHeadroomPct').value = '10';
            document.getElementById('configXchReserve').value = '0';
            document.getElementById('configCatReserve').value = '0';
            document.getElementById('configTransactionFeeEnabled').checked = false;
            const sniper = document.getElementById('configSniperEnabled');
            if (sniper) sniper.checked = false;
            updateCoinPrepPreview();
            let saves = 0;
            saveConfig = () => { saves += 1; };
            document.getElementById('configXchReserve').value = '2';
            scheduleSettingsUpdate();
            handleSaveClick();
            return {saves, impossible: tradingSettingsImpossible};
        }"""
    )

    assert result == {"saves": 0, "impossible": True}


def test_coin_prep_confirmation_disables_known_insufficient_plan(page):
    """The final confirmation cannot enable a prep the verifier says is unfunded."""
    _ready_setup(page, "allowed")
    disabled = page.evaluate(
        """() => {
            bot_state.pricing = {mid: 1};
            const config = {
                default_trade_xch: 1,
                max_active_buy: 1,
                max_active_sell: 0,
                liquidity_mode: 'buy_only',
                tier_enabled: false,
                coin_prep_headroom_pct: 10,
                xch_reserve: 0,
                cat_reserve: 0,
                transaction_fee_mode: 'off',
            };
            showCoinPrepConfirm(config, 'must_resize', 'Prepared pool exceeds balance', {
                success: true,
                all_sufficient: false,
                balance_sufficient: false,
                balance_warnings: ['Not enough XCH for the requested prepared pool.'],
            });
            return {
                disabled: document.getElementById('cpConfirmBtn').disabled,
                text: document.getElementById('cpConfirmBtn').textContent,
            };
        }"""
    )

    assert disabled["disabled"] is True
    assert disabled["text"] == "Balance Too Low"


def test_matching_coins_do_not_bypass_known_insufficient_balance(page):
    """Matching denominations cannot mark prep done when reserves make the plan unfunded."""
    _ready_setup(page, "allowed")
    result = page.evaluate(
        """async () => {
            bot_state.pricing = {mid: 1};
            setCoinPrepStatus('none');
            let modalArgs = null;
            apiFetch = async () => new Response(JSON.stringify({
                success: true,
                all_sufficient: true,
                balance_sufficient: false,
                balance_warnings: ['Not enough XCH after reserve.'],
            }));
            showCoinPrepConfirm = (_config, reason, _message, verification) => {
                modalArgs = {reason, balance: verification.balance_sufficient};
            };
            await checkIfCoinPrepNeeded({
                default_trade_xch: 1,
                max_active_buy: 1,
                max_active_sell: 0,
                liquidity_mode: 'buy_only',
                tier_enabled: false,
                xch_reserve: 10,
            });
            return {modalArgs, status: coinPrepStatus};
        }"""
    )

    assert result["modalArgs"] == {"reason": "recommended", "balance": False}
    assert result["status"] != "done"


def test_coin_prep_verification_receives_reserve_and_topup_budget(page):
    """The wallet verifier must evaluate the same held-back funds as the preview."""
    _ready_setup(page, "allowed")
    query = page.evaluate(
        """async () => {
            bot_state.pricing = {mid: 1};
            let requested = '';
            apiFetch = async (url) => {
                requested = String(url);
                return new Response(JSON.stringify({
                    success: true,
                    all_sufficient: true,
                    balance_sufficient: true,
                }));
            };
            await checkIfCoinPrepNeeded({
                default_trade_xch: 1,
                max_active_buy: 1,
                max_active_sell: 1,
                liquidity_mode: 'two_sided',
                tier_enabled: false,
                coin_prep_headroom_pct: 10,
                xch_reserve: 2,
                cat_reserve: 3,
                topup_pool_xch: 4,
                topup_pool_cat: 5,
            });
            return requested;
        }"""
    )

    assert "xch_reserve=2" in query
    assert "cat_reserve=3" in query
    assert "topup_pool_xch=4" in query
    assert "topup_pool_cat=5" in query


def test_tier_verification_uses_effective_residual_topup_budget(page):
    """Verification must use the capped top-up coin shown in the prep plan."""
    from coin_prep_economics import prepared_cat_sizes

    # 1 XCH / 1.03 XCH per CAT * 1.1 headroom, rounded up to a CAT mojo.
    # Two 1.068 CAT outputs leave 1000 - 100 reserve - 2.136 = 897.864 CAT.
    backend = prepared_cat_sizes(
        live_sizes={"inner": "1"}, price="1", headroom_multiplier="1.1",
        cat_decimals=3, sell_counts={"inner": 1}, max_offers=1,
        spread_bps="300", min_edge_bps="300",
    )
    assert str(backend["inner"]) == "1.068"
    _ready_setup(page, "allowed")
    query = page.evaluate(
        """async () => {
            _pairDataReadyAssetId = currentCAT.asset_id;
            _catSwitchTargetAssetId = '';
            bot_state.balances = mergeVerifiedWalletBalances({
                xch: {total: 10, confirmed: 10, spendable: 10},
                cat: {total: 1000, confirmed: 1000, spendable: 1000},
            }, currentCAT.asset_id);
            window._smartXchBalance = 8;
            bot_state.pricing = {mid: 1};
            let requested = '';
            apiFetch = async (url) => {
                requested = String(url);
                return new Response(JSON.stringify({
                    success: true,
                    all_sufficient: true,
                    balance_sufficient: true,
                }));
            };
            await checkIfCoinPrepNeeded({
                default_trade_xch: 1,
                max_active_buy: 1,
                max_active_sell: 1,
                liquidity_mode: 'two_sided',
                tier_enabled: true,
                coin_prep_multiplier: 1,
                coin_prep_headroom_pct: 10,
                spread_bps: 300,
                min_edge_bps: 300,
                xch_reserve: 2,
                cat_reserve: 100,
                topup_pool_xch: 9,
                topup_pool_cat: 999,
                buy_inner_size_xch: 1,
                sell_inner_size_xch: 1,
                buy_inner_tier_count: 1,
                sell_inner_tier_count: 1,
                buy_inner_tier_spare_count: 1,
                sell_inner_tier_spare_count: 1,
            });
            return requested;
        }"""
    )

    assert "topup_pool_xch=3.76" in query
    assert "inner_cat=1.068&" in query
    assert "topup_pool_cat=897.864" in query


def test_tier_verification_sends_separate_live_plus_spare_counts(page):
    """Tier verification must budget the same asymmetric prepared pools as the worker."""
    _ready_setup(page, "allowed")
    query = page.evaluate(
        """async () => {
            bot_state.pricing = {mid: 1};
            let requested = '';
            apiFetch = async (url) => {
                requested = String(url);
                return new Response(JSON.stringify({
                    success: true,
                    all_sufficient: true,
                    balance_sufficient: true,
                }));
            };
            await checkIfCoinPrepNeeded({
                default_trade_xch: 1,
                max_active_buy: 10,
                max_active_sell: 5,
                liquidity_mode: 'two_sided',
                tier_enabled: true,
                coin_prep_multiplier: 1,
                coin_prep_headroom_pct: 10,
                inner_size_xch: 1,
                buy_inner_size_xch: 2,
                sell_inner_size_xch: 1,
                inner_tier_count: 5,
                buy_inner_tier_count: 10,
                sell_inner_tier_count: 5,
                inner_tier_spare_count: 3,
                buy_inner_tier_spare_count: 7,
                sell_inner_tier_spare_count: 3,
            });
            return requested;
        }"""
    )

    assert "inner_xch_count=17" in query
    assert "inner_cat_count=8" in query


def test_flat_verification_sends_price_derived_cat_coin_size(page):
    """Flat verification must budget CAT units, not reuse the XCH trade size."""
    _ready_setup(page, "allowed")
    query = page.evaluate(
        """async () => {
            bot_state.pricing = {mid: 0.001};
            let requested = '';
            apiFetch = async (url) => {
                requested = String(url);
                return new Response(JSON.stringify({
                    success: true,
                    all_sufficient: true,
                    balance_sufficient: true,
                }));
            };
            await checkIfCoinPrepNeeded({
                default_trade_xch: 1,
                max_active_buy: 1,
                max_active_sell: 1,
                liquidity_mode: 'two_sided',
                tier_enabled: false,
                coin_prep_headroom_pct: 10,
            });
            return requested;
        }"""
    )

    assert "prepared_cat_size=1100" in query


def test_sage_fingerprint_timeout_keeps_polling_instead_of_claiming_start_failed(page):
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            let polls = 0;
            let errors = 0;
            apiFetch = async () => {
                const error = new Error('signal timed out');
                error.name = 'TimeoutError';
                throw error;
            };
            startupPollUntilReady = () => { polls += 1; };
            startupShowError = () => { errors += 1; };
            await startupSelectFingerprint('736588221', null);
            return {polls, errors};
        }"""
    )

    assert result == {"polls": 1, "errors": 0}
