"""Browser acceptance for explicit Coin Prep fee approval."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import expect


pytestmark = pytest.mark.e2e


def _open_gui(page) -> None:
    gui = Path(__file__).resolve().parents[2] / "bot_gui.html"
    page.goto(gui.as_uri(), wait_until="domcontentloaded")


def _preview(*, available: bool = True) -> dict:
    if not available:
        return {
            "success": False,
            "available": False,
            "reason": "FEE_ESTIMATE_UNAVAILABLE",
            "dispatch_authorized": False,
        }
    return {
        "success": True,
        "available": True,
        "preview_id": "a" * 64,
        "scope_sha256": "c" * 64,
        "plan_sha256": "b" * 64,
        "dispatch_authorized": False,
        "wallet": {
            "network": "mainnet",
            "wallet_type": "sage",
            "wallet_fingerprint": 736588221,
            "wallet_id": 2,
            "xch_wallet_id": 1,
            "asset_id": "b" * 64,
            "ticker": "MZ",
            "campaign_id": None,
            "session_id": "c" * 64,
        },
        "target_seconds": 300,
        "preparation_transaction_count_min": 2,
        "preparation_transaction_count_max": 4,
        "estimated_preparation_fee_mojos": "12000000",
        "estimated_cancellation_fee_mojos": "4000000",
        "estimated_total_fee_mojos": "16000000",
        "estimated_minimum_fee_mojos": "8000000",
        "suggested_maximum_fee_mojos": "16000000",
        "fee_coin_principal_mojos": "2000000000",
        "fee_funding_mojos": "88000000000",
        "funded": True,
        "observed_at": 1_800_000_000,
        "expires_at": 1_800_000_060,
        "inclusion_is_guaranteed": False,
        "stages": [
            {
                "stage_id": "prep_cat",
                "cost_kind": "exact_unsigned",
                "transaction_count_min": 1,
                "transaction_count_max": 1,
                "cancellation": False,
                "quote": {
                    "source": "coinset",
                    "observed_at": 1_800_000_000,
                    "expires_at": 1_800_000_060,
                    "fee_mojos": "4000000",
                },
            },
            {
                "stage_id": "prep_xch",
                "cost_kind": "projected",
                "transaction_count_min": 1,
                "transaction_count_max": 3,
                "cancellation": False,
                "quote": {
                    "source": "full_node",
                    "observed_at": 1_800_000_000,
                    "expires_at": 1_800_000_060,
                    "fee_mojos": "4000000",
                },
            },
        ],
    }


def test_zero_headroom_is_preserved_in_saved_coin_prep_plan(page):
    _open_gui(page)
    result = page.evaluate(
        """async () => {
            document.getElementById('configCoinPrepHeadroomPct').value = '0';
            let validated = null;
            window.showStyledConfirm = async () => true;
            window.apiFetch = async (path, options = {}) => {
                if (String(path).endsWith('/settings/validate')) {
                    validated = JSON.parse(options.body);
                    return new Response(JSON.stringify({valid: false, errors: [{message: 'test stop'}], warnings: []}), {status: 200});
                }
                throw new Error(`Unexpected request: ${path}`);
            };
            await saveConfig();
            return {headroom: validated?.coin_prep_headroom_pct,
                    displayed: getCoinPrepHeadroomPct(document.getElementById('configCoinPrepHeadroomPct').value)};
        }"""
    )
    assert result == {"headroom": 0, "displayed": 0}


def test_zero_headroom_wallet_verification_uses_unpadded_coin_size(page):
    _open_gui(page)
    query = page.evaluate(
        """async () => {
            let seen = null;
            window.apiFetch = async path => {
                seen = String(path);
                return new Response(JSON.stringify({all_sufficient: true, balance_sufficient: true}), {status: 200});
            };
            await checkIfCoinPrepNeeded({
                tier_enabled: false, liquidity_mode: 'two_sided',
                default_trade_xch: 0.1, max_active_buy: 3, max_active_sell: 3,
                coin_prep_headroom_pct: 0,
            });
            return new URLSearchParams(seen.split('?')[1]).get('prepared_xch_size');
        }"""
    )
    assert query == "0.1"


def test_fee_preview_formats_pair_ticker_without_repeating_xch(page):
    _open_gui(page)
    preview = _preview()
    preview["wallet"]["ticker"] = "MZ_XCH"
    page.evaluate("preview => renderCoinPrepFeePreview(preview)", preview)
    expect(page.locator("#cpFeeWalletPair")).to_have_text(
        "Sage 736588221 · wallet 2 · MZ/XCH · mainnet"
    )


@pytest.mark.parametrize("reported", [False, True])
def test_fee_preview_discloses_unknown_network_evidence_and_exact_observed_values(page, reported):
    _open_gui(page)
    preview = _preview()
    if reported:
        preview["stages"][0]["quote"]["network_evidence"] = {
            "full_node_synced": True, "mempool_size": "0",
            "mempool_fees": "9007199254740993", "last_block_cost": "20000000",
        }
    page.evaluate("preview => renderCoinPrepFeePreview(preview)", preview)
    expect(page.locator("#cpFeeNetwork")).to_contain_text("provider sync unknown")
    expect(page.locator("#cpFeeNetwork")).to_contain_text("congestion data unavailable")
    if reported:
        expect(page.locator("#cpFeeNetwork")).to_contain_text("provider synced")
        expect(page.locator("#cpFeeNetwork")).to_contain_text("mempool transactions 0")
        expect(page.locator("#cpFeeNetwork")).to_contain_text("9007199254740993 mojos")


def test_fee_preview_age_advances_and_expired_quote_cannot_be_approved(page):
    _open_gui(page)
    preview = _preview()
    result = page.evaluate(
        """preview => {
            const initialNow = Math.floor(Date.now() / 1000);
            preview.observed_at = initialNow;
            preview.expires_at = initialNow + 2;
            renderCoinPrepFeePreview(preview);
            const before = document.getElementById('cpFeeSource').textContent;
            const originalNow = Date.now;
            Date.now = () => (initialNow + 3) * 1000;
            try {
                updateCoinPrepFeeFreshness();
                return {
                    before,
                    after: document.getElementById('cpFeeSource').textContent,
                    disabled: document.getElementById('cpConfirmBtn').disabled,
                    maximum: validateCoinPrepFeeMaximum(),
                };
            } finally {
                Date.now = originalNow;
            }
        }""",
        preview,
    )
    assert "0s old" in result["before"]
    assert "3s old" in result["after"]
    assert "expired" in result["after"]
    assert result["disabled"] is True
    assert result["maximum"] is None


def test_fee_preview_is_read_only_and_renders_lossless_operator_evidence(page):
    _open_gui(page)
    preview = _preview()
    result = page.evaluate(
        """async preview => {
            window.__feeCalls = [];
            window.apiFetch = async (path, options = {}) => {
                window.__feeCalls.push({path: String(path), body: options.body || null});
                if (!String(path).includes('/coin-prep/fee-preview')) {
                    throw new Error(`Unexpected request: ${path}`);
                }
                return new Response(JSON.stringify(preview), {
                    status: 200,
                    headers: {'Content-Type': 'application/json'},
                });
            };
            const value = await refreshCoinPrepFeePreview({coin_multiplier: '1'});
            return {value, calls: window.__feeCalls};
        }""",
        preview,
    )

    assert result["value"] is True
    assert [call["path"] for call in result["calls"]] == ["/api/coin-prep/fee-preview"]
    expect(page.locator("#cpFeeWalletPair")).to_have_text(
        "Sage 736588221 · wallet 2 · MZ/XCH · mainnet"
    )
    expect(page.locator("#cpFeeTxCount")).to_have_text("2–4 preparation transactions")
    expect(page.locator("#cpFeeEstimate")).to_contain_text("0.000016 XCH")
    expect(page.locator("#cpFeePrincipal")).to_contain_text(
        "0.002 XCH prepared as coin principal, not spent as fees"
    )
    expect(page.locator("#cpFeeSource")).to_contain_text("Coinset + Full node")
    expect(page.locator("#cpFeeEvidence")).to_contain_text("1 exact · 1 projected")
    expect(page.locator("#cpFeeStages")).to_contain_text(
        "prep cat: exact unsigned, 1 transaction, 0.000004 XCH each (Coinset)"
    )
    expect(page.locator("#cpFeeStages")).to_contain_text(
        "prep xch: projected, 1–3 transactions, 0.000004 XCH each (Full node)"
    )
    expect(page.locator("#cpFeeDisclaimer")).to_contain_text("not a guarantee")
    expect(page.locator("#cpConfirmBtn")).to_be_enabled()


def test_confirmation_records_budget_before_one_launch_and_preserves_exact_strings(
    page,
):
    _open_gui(page)
    preview = _preview()
    result = page.evaluate(
        """async preview => {
            window.__feeCalls = [];
            window.apiFetch = async (path, options = {}) => {
                const body = options.body ? JSON.parse(options.body) : null;
                window.__feeCalls.push({path: String(path), body});
                if (String(path).includes('/coin-prep/fee-preview')) {
                    return new Response(JSON.stringify(preview), {status: 200});
                }
                if (String(path).includes('/coin-prep/fee-approval')) {
                    await new Promise(resolve => setTimeout(resolve, 20));
                    return new Response(JSON.stringify({
                        success: true,
                        approval_id: 'd'.repeat(64),
                        total_fee_mojos: body.maximum_fee_mojos,
                        dispatch_authorized: false,
                    }), {status: 200});
                }
                if (String(path).includes('/coin-prep/trigger')) {
                    return new Response(JSON.stringify({success: true}), {status: 200});
                }
                throw new Error(`Unexpected request: ${path}`);
            };
            window.askPrepHistoryChoice = async () => ({
                action: 'proceed', resets: {pnl: false, offers: false, counters: false},
            });
            window.pollCoinPrepProgress = () => {};
            await refreshCoinPrepFeePreview({coin_multiplier: '1'});
            document.getElementById('cpFeeMaximumInput').value = '0.000020000001';
            document.getElementById('configCoinPrepMultiplier').value = '9';
            await Promise.all([startCoinPrepFromModal(), startCoinPrepFromModal()]);
            return window.__feeCalls;
        }""",
        preview,
    )

    approval_calls = [call for call in result if "/fee-approval" in call["path"]]
    trigger_calls = [call for call in result if "/trigger" in call["path"]]
    assert len(approval_calls) == 1
    assert approval_calls[0]["body"] == {
        "preview_id": "a" * 64,
        "maximum_fee_mojos": "20000001",
        "cancellation_reserve_mojos": "4000000",
    }
    assert len(trigger_calls) == 1
    assert trigger_calls[0]["body"]["fee_approval_id"] == "d" * 64
    assert str(trigger_calls[0]["body"]["coin_multiplier"]) == "1"


def test_unavailable_fee_quote_blocks_approval_and_launch(page):
    _open_gui(page)
    unavailable = _preview(available=False)
    result = page.evaluate(
        """async unavailable => {
            window.__feeCalls = [];
            window.apiFetch = async (path, options = {}) => {
                window.__feeCalls.push(String(path));
                return new Response(JSON.stringify(unavailable), {status: 503});
            };
            const value = await refreshCoinPrepFeePreview({coin_multiplier: '1'});
            return {value, calls: window.__feeCalls};
        }""",
        unavailable,
    )

    assert result["value"] is False
    assert result["calls"] == ["/api/coin-prep/fee-preview"]
    expect(page.locator("#cpFeeStatus")).to_contain_text("Fee estimate unavailable")
    expect(page.locator("#cpConfirmBtn")).to_be_disabled()


def test_provider_outage_discloses_sources_and_reasons_without_enabling_approval(page):
    _open_gui(page)
    unavailable = {**_preview(available=False), "provider_failures": [
        {"source": "full_node_rpc", "reason": "fee_provider_unsynced", "observed_at": 1000},
        {"source": "coinset", "reason": "fee_provider_rate_limited", "observed_at": None},
    ]}
    result = page.evaluate("""async data => {
        window.apiFetch = async () => new Response(JSON.stringify(data), {status: 200});
        return await refreshCoinPrepFeePreview({coin_multiplier: '1'});
    }""", unavailable)
    assert result is False
    expect(page.locator("#cpFeeStatus")).to_contain_text("Full node: not synced")
    expect(page.locator("#cpFeeStatus")).to_contain_text("Coinset: rate limited")
    expect(page.locator("#cpConfirmBtn")).to_be_disabled()


@pytest.mark.parametrize("confirm", [False, True])
def test_renewal_uses_displayed_cumulative_cap_and_retains_cancellation_protection(page, confirm):
    _open_gui(page)
    preview = {**_preview(),
               "minimum_cumulative_fee_mojos": "39000000",
               "suggested_maximum_fee_mojos": "39000000",
               "minimum_cancellation_reserve_mojos": "15000000",
               "fee_accounting": {"held_fee_mojos": "8000000", "spent_fee_mojos": "12000000",
                                  "committed_fee_mojos": "20000000",
                                  "noncancellation_committed_fee_mojos": "12000000",
                                  "protected_cancellation_fee_mojos": "15000000"}}
    result = page.evaluate(
        """async ({preview, confirm}) => {
            window.__feeCalls = [];
            window.apiFetch = async (path, options = {}) => {
                const body = options.body ? JSON.parse(options.body) : null;
                window.__feeCalls.push({path: String(path), body});
                if (String(path).endsWith('/fee-preview')) {
                    return new Response(JSON.stringify(preview), {status: 200});
                }
                if (String(path).endsWith('/fee-approval') && confirm) {
                    return new Response(JSON.stringify({success: false, reason: 'test stop'}), {status: 400});
                }
                throw new Error(`Unexpected mutation: ${path}`);
            };
            window.askPrepHistoryChoice = async () => ({
                action: 'proceed', resets: {pnl: false, offers: false, counters: false}});
            await refreshCoinPrepFeePreview({coin_multiplier: '1'});
            const input = document.getElementById('cpFeeMaximumInput');
            if (!confirm) input.value = '0.000038';
            input.dispatchEvent(new Event('input'));
            const disabled = document.getElementById('cpConfirmBtn').disabled;
            const disclosure = document.getElementById('cpFeePanel').textContent;
            await startCoinPrepFromModal();
            return {calls: window.__feeCalls, disabled, disclosure};
        }""", {"preview": preview, "confirm": confirm},
    )
    assert result["disabled"] is (not confirm)
    approval_calls = [call for call in result["calls"] if call["path"].endswith('/fee-approval')]
    assert len(approval_calls) == int(confirm)
    if confirm:
        assert approval_calls[0]["body"] == {
            "preview_id": "a" * 64, "maximum_fee_mojos": "39000000",
            "cancellation_reserve_mojos": "15000000",
        }
    assert "0.000012 XCH spent" in result["disclosure"]
    assert "0.000008 XCH held" in result["disclosure"]
    assert "0.000015 XCH" in result["disclosure"]


def test_stale_confirmation_refreshes_preview_without_triggering_wallet_work(page):
    _open_gui(page)
    first = _preview()
    second = {**_preview(), "preview_id": "e" * 64}
    result = page.evaluate(
        """async ({first, second}) => {
            window.__feeCalls = [];
            let previews = 0;
            window.apiFetch = async (path, options = {}) => {
                window.__feeCalls.push(String(path));
                if (String(path).includes('/coin-prep/fee-preview')) {
                    const value = previews++ === 0 ? first : second;
                    return new Response(JSON.stringify(value), {status: 200});
                }
                if (String(path).includes('/coin-prep/fee-approval')) {
                    return new Response(JSON.stringify({
                        success: false, reason: 'FEE_APPROVAL_STALE', dispatch_authorized: false,
                    }), {status: 409});
                }
                throw new Error(`Wallet mutation must not run: ${path}`);
            };
            window.askPrepHistoryChoice = async () => ({
                action: 'proceed', resets: {pnl: false, offers: false, counters: false},
            });
            await refreshCoinPrepFeePreview({coin_multiplier: '1'});
            await startCoinPrepFromModal();
            return {
                calls: window.__feeCalls,
                activePreview: _coinPrepFeePreview && _coinPrepFeePreview.preview_id,
            };
        }""",
        {"first": first, "second": second},
    )

    assert result["calls"] == [
        "/api/coin-prep/fee-preview",
        "/api/coin-prep/fee-approval",
        "/api/coin-prep/fee-preview",
    ]
    assert result["activePreview"] == "e" * 64
    expect(page.locator("#cpConfirmBtn")).to_be_enabled()


def test_history_cancel_records_no_fee_approval_or_trigger(page):
    _open_gui(page)
    preview = _preview()
    result = page.evaluate(
        """async preview => {
            window.__feeCalls = [];
            window.apiFetch = async (path) => {
                window.__feeCalls.push(String(path));
                if (String(path).includes('/coin-prep/fee-preview')) {
                    return new Response(JSON.stringify(preview), {status: 200});
                }
                throw new Error(`No approval or wallet mutation expected: ${path}`);
            };
            window.askPrepHistoryChoice = async () => ({action: 'cancel'});
            await refreshCoinPrepFeePreview({coin_multiplier: '1'});
            await startCoinPrepFromModal();
            return window.__feeCalls;
        }""",
        preview,
    )

    assert result == ["/api/coin-prep/fee-preview"]


def test_quote_expiring_during_history_choice_does_not_record_approval(page):
    _open_gui(page)
    preview = _preview()
    result = page.evaluate(
        """async preview => {
            const originalDateNow = Date.now;
            const now = Math.floor(Date.now() / 1000);
            preview.observed_at = now;
            preview.expires_at = now + 2;
            window.__feeCalls = [];
            window.apiFetch = async path => {
                window.__feeCalls.push(String(path));
                if (String(path).includes('/coin-prep/fee-preview')) {
                    return new Response(JSON.stringify(preview), {status: 200});
                }
                throw new Error(`Expired quote must not be approved: ${path}`);
            };
            window.askPrepHistoryChoice = async () => {
                Date.now = () => (now + 3) * 1000;
                return {action: 'proceed', resets: {pnl: false, offers: false, counters: false}};
            };
            try {
                await refreshCoinPrepFeePreview({coin_multiplier: '1'});
                await startCoinPrepFromModal();
                return {calls: window.__feeCalls,
                        disabled: document.getElementById('cpConfirmBtn').disabled};
            } finally {
                Date.now = originalDateNow;
            }
        }""",
        preview,
    )
    assert result["calls"] == ["/api/coin-prep/fee-preview"]
    assert result["disabled"] is True


def test_fee_endpoints_have_native_desktop_bridge_equivalence(page):
    _open_gui(page)
    assert (
        page.evaluate("_apiBridgeMethod('/api/coin-prep/fee-preview', 'POST')")
        == "preview_coin_prep_fees"
    )
    assert (
        page.evaluate("_apiBridgeMethod('/api/coin-prep/fee-approval', 'POST')")
        == "approve_coin_prep_fees"
    )


def test_coin_prep_cancel_all_forwards_the_confirmed_approval_context(page):
    _open_gui(page)
    approval_id = "d" * 64

    result = page.evaluate(
        """async approvalId => {
            bot_state = {running: false, offers: {buy: [{}], sell: [{}]}};
            window.__feeCalls = [];
            window.apiFetch = async (path, options = {}) => {
                window.__feeCalls.push({path: String(path), body: options.body || null});
                return new Response(JSON.stringify({success: false, error: 'test stop'}), {
                    status: 400,
                    headers: {'Content-Type': 'application/json'},
                });
            };
            await cancelAllOffers({
                source: 'coin_prep',
                openBuyCount: 1,
                openSellCount: 1,
                openOfferCount: 2,
                prepPayload: {fee_approval_id: approvalId},
            });
            await confirmCancelAll();
            return window.__feeCalls;
        }""",
        approval_id,
    )

    assert result == [
        {
            "path": "/api/offers/cancel_all",
            "body": json.dumps(
                {"source": "coin_prep", "fee_approval_id": approval_id},
                separators=(",", ":"),
            ),
        }
    ]


def test_operator_cap_below_displayed_plan_fails_closed_before_approval(page):
    _open_gui(page)
    preview = _preview()
    result = page.evaluate(
        """async preview => {
            window.__feeCalls = [];
            window.apiFetch = async path => {
                window.__feeCalls.push(String(path));
                if (String(path).includes('/coin-prep/fee-preview')) {
                    return new Response(JSON.stringify(preview), {status: 200});
                }
                throw new Error(`Approval must remain blocked: ${path}`);
            };
            await refreshCoinPrepFeePreview({coin_multiplier: '1'});
            const input = document.getElementById('cpFeeMaximumInput');
            input.value = '0.000005';
            input.dispatchEvent(new Event('input'));
            await startCoinPrepFromModal();
            return window.__feeCalls;
        }""",
        preview,
    )

    assert result == ["/api/coin-prep/fee-preview"]
    expect(page.locator("#cpFeeInputError")).to_contain_text(
        "0.000016 XCH"
    )
    expect(page.locator("#cpConfirmBtn")).to_be_disabled()


def test_restart_restores_pending_fee_accounting_without_duplicate_preview_or_launch(
    page,
):
    _open_gui(page)
    status = {
        "success": True,
        "running": False,
        "complete": False,
        "phase": "idle",
        "progress": 0.5,
        "message": "Previous worker stopped",
        "overlapping_coin_prep_blocked": True,
        "fee_resume_required": True,
        "fee_approval_id": "d" * 64,
        "fee_approval": {
            "approval_id": "d" * 64,
            "state": "submitted_awaiting_confirmation",
            "total_fee_mojos": "20000001",
            "cancellation_reserve_mojos": "4000000",
            "held_fee_mojos": "12000000",
            "spent_fee_mojos": "4000000",
            "remaining_fee_mojos": "4000001",
            "remaining_preparation_fee_mojos": "1",
            "unresolved_operation_count": 1,
            "pending_operation": {
                "fee_mojos": "12000000",
                "cancellation": False,
                "effect_state": "submitted_awaiting_confirmation",
            },
            "dispatch_authorized": False,
        },
    }
    result = page.evaluate(
        """async status => {
            window.__feeCalls = [];
            window.apiFetch = async path => {
                window.__feeCalls.push(String(path));
                if (!String(path).includes('/coin-prep/status')) {
                    throw new Error(`No preview, approval or launch expected: ${path}`);
                }
                return new Response(JSON.stringify(status), {status: 200});
            };
            settingsReviewed = true;
            coinPrepStatus = 'none';
            const restored = await restoreCoinPrepReadiness();
            return {
                restored,
                calls: window.__feeCalls,
                coinPrepStatus,
                modalOpen: document.getElementById('coinPrepConfirmOverlay').classList.contains('active'),
                progressDisplay: document.getElementById('coinPrepProgressView').style.display,
            };
        }""",
        status,
    )

    assert result == {
        "restored": True,
        "calls": ["/api/coin-prep/status"],
        "coinPrepStatus": "checking",
        "modalOpen": True,
        "progressDisplay": "block",
    }
    expect(page.locator("#cpProgressTitle")).to_have_text("Coin Prep Paused Safely")
    expect(page.locator("#cpProgressFeeState")).to_contain_text(
        "submitted transaction is awaiting confirmation"
    )
    expect(page.locator("#cpProgressFeeHeld")).to_have_text("0.000012 XCH")
    expect(page.locator("#cpProgressFeeSpent")).to_have_text("0.000004 XCH")
    expect(page.locator("#cpProgressFeeRemaining")).to_have_text("0.000004000001 XCH")
    expect(page.locator("#cpProgressFeeProtected")).to_have_text("0.000004 XCH")
    expect(page.locator("#coinPrepCancelBtn")).to_be_hidden()


def _paused_recovery_status():
    return {
        "success": True, "running": False, "complete": False, "phase": "error",
        "progress": 1, "message": "Worker stopped after submission",
        "overlapping_coin_prep_blocked": True, "fee_resume_required": True,
        "fee_approval": {
            "approval_id": "d" * 64, "state": "submitted_awaiting_confirmation",
            "scope_sha256": "c" * 64, "plan_sha256": "b" * 64,
            "total_fee_mojos": "20000000", "cancellation_reserve_mojos": "4000000",
            "held_fee_mojos": "12000000", "spent_fee_mojos": "4000000",
            "remaining_fee_mojos": "4000000", "remaining_preparation_fee_mojos": "0",
            "unresolved_operation_count": 1, "stale": False, "dispatch_authorized": False,
            "request_options": {"coin_multiplier": "2", "target_seconds": 300},
        },
    }


def test_stopped_worker_keeps_observing_recovery_without_marking_progress_complete(page):
    _open_gui(page)
    page.evaluate("""async status => {
        window.__recoveryCalls = [];
        window.apiFetch = async path => {
            window.__recoveryCalls.push(String(path));
            if (!String(path).endsWith('/coin-prep/status')) throw new Error('Unexpected mutation');
            return new Response(JSON.stringify(status), {status: 200});
        };
        coinPrepStatus = 'none';
        await restoreCoinPrepReadiness();
    }""", _paused_recovery_status())
    page.wait_for_function("window.__recoveryCalls.length >= 2", timeout=4500)
    expect(page.locator("#coinPrepProgressView")).to_be_visible()
    expect(page.locator("#coinPrepCompleteView")).to_be_hidden()
    expect(page.locator("#coinPrepErrorView")).to_be_hidden()
    expect(page.locator("#cpProgressDoneFallback")).to_be_hidden()
    expect(page.locator("#cpReviewFeeBudgetBtn")).to_be_disabled()
    assert page.evaluate("coinPrepStatus") == "checking"


@pytest.mark.parametrize("reappears", [False, True])
@pytest.mark.parametrize("changed_plan", [False, True])
def test_recovery_resolution_requires_deliberate_fresh_budget_review(page, reappears, changed_plan):
    _open_gui(page)
    # Isolate the already-connected recovery screen from the unrelated
    # first-launch disclaimer. Keep real button hit-testing/handler dispatch.
    page.evaluate("document.getElementById('startupOverlay').style.display = 'none'")
    refreshed = _preview()
    if changed_plan:
        refreshed["plan_sha256"] = "e" * 64
    page.evaluate("""async ({status, preview}) => {
        window.__recoveryStatus = status;
        window.__recoveryCalls = [];
        window.apiFetch = async (path, options = {}) => {
            const body = options.body ? JSON.parse(options.body) : null;
            window.__recoveryCalls.push({path: String(path), body, method: options.method || 'GET'});
            if (String(path).endsWith('/coin-prep/status')) {
                return new Response(JSON.stringify(window.__recoveryStatus), {status: 200});
            }
            if (String(path).endsWith('/fee-preview')) {
                return new Response(JSON.stringify(preview), {status: 200});
            }
            throw new Error(`No approval, reset or launch expected: ${path}`);
        };
        coinPrepStatus = 'none';
        await restoreCoinPrepReadiness();
        window.__recoveryStatus = {...status, fee_approval: {...status.fee_approval,
            unresolved_operation_count: 0, held_fee_mojos: '0', spent_fee_mojos: '16000000',
            state: 'paused_budget'}};
        await pollCoinPrepProgress();
    }""", {"status": _paused_recovery_status(), "preview": refreshed})
    expect(page.locator("#cpReviewFeeBudgetBtn")).to_be_visible()
    expect(page.locator("#cpReviewFeeBudgetBtn")).to_be_enabled()
    assert all(call["method"] == 'GET'
               for call in page.evaluate("window.__recoveryCalls"))
    if reappears:
        page.evaluate("status => { window.__recoveryStatus = status; }", _paused_recovery_status())
    page.locator("#cpReviewFeeBudgetBtn").click()
    if reappears:
        expect(page.locator("#cpReviewFeeBudgetBtn")).to_be_disabled()
        expect(page.locator("#coinPrepProgressView")).to_be_visible()
    elif changed_plan:
        expect(page.locator("#cpFeeStatus")).to_contain_text('FEE_APPROVAL_STALE')
        expect(page.locator("#cpConfirmBtn")).to_be_disabled()
    else:
        expect(page.locator("#cpFeeWalletPair")).to_contain_text('736588221')
        expect(page.locator("#coinPrepConfirmView")).to_be_visible()
    calls = page.evaluate("window.__recoveryCalls")
    previews = [call for call in calls if call["path"].endswith('/fee-preview')]
    assert len(previews) == (0 if reappears else 1)
    if previews:
        assert previews[0]["body"] == {"coin_multiplier": "2", "target_seconds": 300}
    assert all(call["method"] == 'GET' or call["path"].endswith('/fee-preview') for call in calls), calls
