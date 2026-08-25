from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "bot_gui.html"
RISK_MANAGER = ROOT / "src" / "catalyst" / "risk_manager.py"
APP_BRIDGE = ROOT / "src" / "catalyst" / "app_bridge.py"


def test_dashboard_sse_keeps_advisor_performance_state_fresh():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "_lcDashboardData.performance.loop_count = data.loop_count;" in html
    assert "_lcDashboardData.performance.uptime_secs = data.uptime_secs;" in html
    assert "_lcDashboardData.performance.open_buys = data.open_buys;" in html
    assert "_lcDashboardData.performance.open_sells = data.open_sells;" in html
    assert (
        "_lcDashboardData.performance.open_offers = data.open_buys + data.open_sells;"
        in html
    )


def test_recommendations_clear_stale_rotator_cache_when_empty():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert (
        """if (active.length === 0) {
                _alertActiveCache = [];
                _alertRotatorIdx = 0;
                if (_alertRotatorTimer) {
                    clearInterval(_alertRotatorTimer);
                    _alertRotatorTimer = null;
                }"""
        in html
    )


def test_alert_refresh_removes_backend_alerts_missing_from_server_snapshot():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "let _serverAlertIds = new Set();" in html
    assert "function syncServerAlerts(alerts = [])" in html
    assert "const knownBackendIds = new Set([" in html
    assert "..._serverAlertIds" in html
    assert "...ACTIONABLE_ALERT_IDS" in html
    assert "...ADVISOR_DIAGNOSTIC_ALERT_IDS" in html
    assert (
        "if (!nextServerAlertIds.has(alertId)) delete _activeAlerts[alertId];" in html
    )
    assert "syncServerAlerts(data.alerts);" in html


def test_recommendation_action_row_wraps_inside_guidance_card():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert ".alert-item .alert-content { flex: 1; min-width: 0;" in html
    assert (
        ".alert-item .alert-msg { color: var(--text-secondary); font-size: 10px; overflow-wrap: anywhere;"
        in html
    )
    assert ".alert-actions-row" in html
    assert "flex-wrap: wrap" in html
    assert "max-width: 100%" in html
    assert '<div class="alert-actions-row">' in html


def test_update_badge_is_compact_sidebar_control():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert 'id="v4UpdateBadge" class="v4-update-badge"' in html
    assert ".v4-update-badge" in html
    assert "width: 44px" in html
    assert "white-space: normal" in html
    assert "v4-update-badge-version" in html


def test_data_reset_success_refreshes_visible_stats():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert (
        "async function refreshAfterDataReset({ clearPnlCharts = true } = {})" in html
    )
    assert "await refreshAfterDataReset();" in html
    assert "await refreshAfterDataReset({ clearPnlCharts });" in html
    assert "fetchDashboard()" in html
    assert "fetchPnLData()" in html
    assert "_v4LastPnlSignature = ''" in html
    assert "v4RenderPnlChart()" in html
    assert "v4RenderInventoryChart()" in html
    assert "updateDashboard()" not in html


def test_offer_history_reset_preserves_pnl_chart_history():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert (
        "async function _runReset(endpoint, label, successMsgBuilder, { clearPnlCharts = true } = {})"
        in html
    )
    assert "await _runReset('reset/offer-history', 'Clear offer history'," in html
    assert "{ clearPnlCharts: false });" in html


def test_smart_settings_preview_uses_smart_balance_snapshot_when_bot_stopped():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    gate_start = html.index("const _previewDepsReady = () => {")
    gate_end = html.index("if (!_previewDepsReady())", gate_start)
    gate_block = html[gate_start:gate_end]
    assert "getWalletBalance('xch')" in gate_block
    assert "getWalletBalance('cat')" in gate_block

    preview_start = html.index("function updateCoinPrepPreview()")
    preview_end = html.index("const _liveMid", preview_start)
    preview_block = html[preview_start:preview_end]
    assert "getWalletBalance('xch')" in preview_block
    assert "getWalletBalance('cat')" in preview_block
    assert "bot_state?.balances?.xch?.total || 0" not in preview_block
    assert "bot_state?.balances?.cat?.total || 0" not in preview_block


def test_smart_settings_snapshots_wallet_balances_from_response_sources():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    snapshot_start = html.index("const _xchBal")
    snapshot_end = html.index("window._smartMidPrice", snapshot_start)
    snapshot_block = html[snapshot_start:snapshot_end]
    assert "data.xch_balance" in snapshot_block
    assert "data?._data_sources?.xch_balance" in snapshot_block
    assert "data._capital_plan?.total_xch" in snapshot_block
    assert "_cp.total_cat" in snapshot_block
    assert "_cp.available_cat" in snapshot_block
    assert "_cp.cat_reserve" in snapshot_block


def test_settings_review_state_survives_reload_before_blank_template_gate():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "function readStoredSettingsReviewed()" in html
    assert "localStorage.getItem('settingsReviewed') === 'true'" in html
    assert "function isSettingsReviewedForCurrentPair()" in html
    assert (
        "localStorage.setItem('settingsReviewedAssetId', currentCAT.asset_id)" in html
    )
    assert "let settingsReviewed = readStoredSettingsReviewed();" in html
    assert "let _freshStartBlankTierTemplates = !settingsReviewed;" in html

    gate_start = html.index("function shouldUseFreshStartBlankTierTemplates()")
    gate_end = html.index(
        "function resetCoreOrderBookInputsForFreshStart()", gate_start
    )
    gate_block = html[gate_start:gate_end]
    assert "!isSettingsReviewedForCurrentPair()" in gate_block
    assert "!settingsReviewed" not in gate_block

    start_gate = html.index("function canAttemptBotStart()")
    start_end = html.index("function _getPairFromSelector", start_gate)
    start_block = html[start_gate:start_end]
    assert "isSettingsReviewedForCurrentPair()" in start_block


def test_reselecting_persisted_pair_loads_saved_config_for_explicit_review():
    """Re-confirming the server's saved pair must not look like a new CAT switch."""
    html = GUI.read_text(encoding="utf-8", errors="replace")

    select_start = html.index("async function selectCAT()")
    select_end = html.index("async function refreshBalances", select_start)
    select_block = html[select_start:select_end]

    assert "const reselectingPersistedPair" in select_block
    assert "_resumeCandidateCAT?.asset_id === assetId" in select_block
    assert "previousCAT.asset_id === assetId" in select_block
    assert "setFreshStartTemplateState(!reselectingPersistedPair);" in select_block
    # Review remains explicit even though the valid saved values are reloaded.
    assert "setSettingsReviewedState(false);" in select_block

    resume_start = html.index("async function checkForResume()")
    resume_end = html.index("async function resumeSession()", resume_start)
    resume_block = html[resume_start:resume_end]
    assert "const reselectingPersistedPair" in resume_block
    assert "setFreshStartTemplateState(!reselectingPersistedPair);" in resume_block


def test_resume_session_revalidates_live_summary_after_status_refresh():
    """A concurrent idle-status refresh must not blank the post-load summary."""
    html = GUI.read_text(encoding="utf-8", errors="replace")

    resume_start = html.index("async function resumeSession()")
    resume_end = html.index("function dismissResume()", resume_start)
    resume_block = html[resume_start:resume_end]
    status_refresh = resume_block.index("await fetchStatus();")
    summary_render = resume_block.index("const _rs = _resumeSessionSummary || {};")
    between = resume_block[status_refresh:summary_render]

    assert "`${API_URL}/check-resume`" in between
    assert "refreshedResume.can_resume" in between
    assert "setResumeSessionSummary(refreshedResume);" in between
    assert "throw new Error" in between


def test_coin_prep_reload_restores_and_balance_caps_cat_topup_coin():
    """The modal must not lose the saved CAT topup pool after a page reload."""
    html = GUI.read_text(encoding="utf-8", errors="replace")

    plan_start = html.index("function buildCoinPrepPlan({")
    plan_end = html.index("function updateCoinPrepPreview()", plan_start)
    plan_block = html[plan_start:plan_end]
    assert "topupPoolCat" in plan_block
    assert "topupPoolXch" in plan_block
    assert "getWalletBalance('cat')" in plan_block
    assert "_catBalanceResidual" in plan_block

    preview_start = html.index("function updateCoinPrepPreview()")
    preview_end = html.index("function setWarning", preview_start)
    preview_block = html[preview_start:preview_end]
    assert "topupPoolCat: parseFloat(document.getElementById('configTopupPoolCat')?.value) || 0" in preview_block

    modal_start = html.index("function showCoinPrepConfirm(config")
    modal_end = html.index("function closeCoinPrepConfirm()", modal_start)
    modal_block = html[modal_start:modal_end]
    assert "topupPoolCat: parseFloat(config.topup_pool_cat) || 0" in modal_block


def test_coin_prep_preflight_verifies_prepared_buy_sizes_with_headroom():
    """The wallet preflight must compare against the coins prep actually creates."""
    html = GUI.read_text(encoding="utf-8", errors="replace")

    check_start = html.index("async function checkIfCoinPrepNeeded(config)")
    check_end = html.index("function showCoinPrepConfirm(config", check_start)
    check_block = html[check_start:check_end]

    assert "const preparedBuyXch = buyXch * prepFactor;" in check_block
    assert "params.set(`${t}_xch`, String(preparedBuyXch));" in check_block
    assert "const preparedSniperXch = sniperSize * prepFactor;" in check_block
    assert "params.set('sniper_xch', String(preparedSniperXch));" in check_block
    assert "const preparedFeeXch = feeSize * prepFactor;" in check_block
    assert "params.set('fees_xch', String(preparedFeeXch));" in check_block
    assert "const xch = Number(config[sizeKey(t)] || sellXch || 0);" not in check_block


def test_desktop_bridge_covers_reset_routes_used_by_data_buttons():
    html = GUI.read_text(encoding="utf-8", errors="replace")
    bridge = APP_BRIDGE.read_text(encoding="utf-8", errors="replace")

    for route, method in (
        ("pnl/reset-preview", "get_pnl_reset_preview"),
        ("pnl/reset", "reset_pnl"),
        ("reset/offer-history", "reset_offer_history"),
        ("reset/full", "reset_full"),
    ):
        assert f"clean === '{route}'" in html
        assert f"return '{method}'" in html
        assert f"def {method}" in bridge


def test_diagnostics_are_distributed_across_existing_workflow_tabs():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    required_ids = [
        "offersDiagnosticsGrid",
        "diagBuyRequotePressure",
        "diagSellRequotePressure",
        "diagPendingCancels",
        "diagRequoteBatch",
        "intelSourceCoverage",
        "intelArbGapTrend",
        "pnlFlowDiagnostics",
        "pnlPendingVerification",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in html


def test_market_price_history_has_range_controls_without_adding_new_main_tab():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert 'data-price-range="24"' in html
    assert 'data-price-range="0.333333"' in html
    assert 'id="v4View-analysis"' not in html


def test_market_price_history_treats_sql_timestamps_as_utc():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "function _v4ParsePriceHistoryTimestamp" in html
    assert "normalized + 'Z'" in html
    assert "const t = _v4ParsePriceHistoryTimestamp(point.timestamp);" in html


def test_market_price_history_preserves_live_samples_when_server_history_empty():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "function _v4MergePriceHistoryPoints" in html
    assert "const existingLiveSamples = _v4PriceHistory.slice();" in html
    assert "if (!loadedPoints.length)" in html


def test_market_price_history_accepts_running_bot_pair_context():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "function _v4HasPriceHistoryPairContext" in html
    assert "bot_state.current_cat.asset_id" in html
    assert "!shouldRequireExplicitPairSelection(bot_state)" in html


def test_dry_run_is_not_user_facing_setting():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert 'id="configDryRun"' not in html
    assert 'id="ccDryRun"' not in html
    assert "Dry Run Mode" not in html
    assert "dry_run:" not in html


def test_market_diagnostics_uses_live_amm_and_summary_sources():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "_lastAmmPriceData" in html
    assert "_lastMarketSummary" in html
    assert "summaryTibetXch" in html


def test_close_gap_recommendation_has_confidence_gate():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "_SA_CLOSE_GAP_PROMOTE_BPS = 200" in html
    assert "_SA_CLOSE_GAP_CONFIRM_UPDATES = 3" in html
    assert "saCloseGapSignalReady(" in html
    assert "closeGapCandidate" in html
    assert "if (closeGapReady)" in html


def test_min_spread_clamp_copy_is_diagnostic_not_directive():
    html = GUI.read_text(encoding="utf-8", errors="replace")
    text = RISK_MANAGER.read_text(encoding="utf-8", errors="replace")

    assert "raise MIN_SPREAD_BPS" not in text
    assert "configured minimum clamp" in text
    assert "normalizeMarketConditionText" in html
    assert "raise MIN_SPREAD_BPS" not in html


def test_max_spread_clamp_recommendation_opens_running_settings():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert 'id="settings-section-smart-pricing"' in html
    assert "reviewMaxSpread" in html
    assert "Review Max Spread" in html
    assert "actionType: 'reviewMaxSpread'" in html
    assert "Settings > Setup > Smart Pricing" in html
    assert "settingsSwitchSubview('setup')" in html
    assert "configMaxSpreadBps" in html
    assert "future requotes and new offers" in html


def test_live_controls_points_max_spread_users_to_setup():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "Max Spread caps live in Setup > Smart Pricing" in html


def test_spread_tighten_recommendations_pause_at_max_spread_clamp():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "const maxSpreadClampActive" in html
    assert "if (!_gapCloserActive && !maxSpreadClampActive" in html
    assert "fillsHr === 0 && !maxSpreadClampActive" in html


def test_inventory_drift_advisor_uses_backend_position_percent():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "const positionLoadPct" in html
    assert "positionLoadPct > 70" in html
    assert "Math.abs(netPos) > maxPos * 0.7" not in html


def test_pnl_position_limit_uses_live_backend_value():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert 'id="invMaxPosition"' in html
    assert 'id="invMaxPosition" style="font-size: var(--text-xl); font-weight: 700; font-family: var(--font-mono); color: var(--text-primary);">—</div>' in html
    assert "data.max_position_xch !== undefined && el('invMaxPosition')" in html
    assert "el('invMaxPosition').textContent = formatXchAmount(data.max_position_xch) + ' XCH';" in html


def test_advisor_fill_rate_reads_dashboard_field_name():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "perf.fill_rate_per_hour ?? perf.fills_per_hour" in html


def test_running_settings_restart_warning_is_setup_only():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "function updateSettingsRestartBannerVisibility()" in html
    assert (
        "const setupActive = !!(setupView && setupView.classList.contains('is-active'));"
        in html
    )
    assert "isRunning && setupActive" in html
    assert "try { updateSettingsRestartBannerVisibility(); } catch (_) {}" in html
    assert "banner.classList.toggle('is-visible', isRunning);" not in html


def test_recovery_guidance_collapses_expected_ladder_noise():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "function isRecoveryGuidanceActive()" in html
    assert "ladderStillBuilding && !isRecoveryGuidanceActive()" in html
    assert "function isRecoveryExpectedOfferCountDiagnostic(alert)" in html
    assert "if (isRecoveryExpectedOfferCountDiagnostic(a)) return false;" in html


def test_splash_incoming_hint_explains_sparse_relevant_gossip():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "gossip sparse" in html
    assert "no relevant offers seen" in html
    assert "Connected" in html


def test_splash_panel_distinguishes_local_submits_from_peer_relay():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "Local Submit" in html
    assert "local submits " in html
    assert "local submits only; peer relay depends on daemon peers" in html
    assert "Local submits</div><div>${fmtN(sp.total_posted)}</div>" in html


def test_market_health_copy_distinguishes_recovery_from_market_health():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "Market healthy — bot rebuilding ladder" in html


def test_logs_tab_has_run_doctor_button_wired_to_existing_modal():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert 'id="logsRunDoctorBtn"' in html
    assert 'onclick="runDoctorFromLogs(this)"' in html
    assert "async function runDoctorFromLogs" in html
    assert "await showDoctorReport();" in html
    assert "const resp = await apiFetch('/api/doctor?force=true');" in html


def test_logs_tab_orders_api_backfill_and_polls_while_visible():
    """A dropped SSE stream must not leave the operator log frozen."""
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "function orderSystemLogEntries(entries)" in html
    assert "const orderedEntries = orderSystemLogEntries(entries);" in html
    assert "_sysLogBuffer = orderedEntries" in html
    assert "function startSystemLogBackfillPolling()" in html
    assert "if (_v4CurrentView !== 'logs') return;" in html
    assert "_systemLogBackfillPoll = setInterval" in html
    assert "startSystemLogBackfillPolling();" in html


def test_dashboard_has_active_toxicity_guard_notice():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert 'id="ccToxicityAction"' in html
    assert 'id="ccToxicityActionScore"' in html
    assert "function updateToxicityAction" in html
    assert "toxicity_buy_spread_multiplier" in html
    assert "toxicity_throttle_until" in html
    assert "openToxicityGuardSettings" in html
    assert 'data-toxicity-action="settings"' in html
    assert 'data-toxicity-action="smart-settings"' in html
    assert "Adverse Selection Guard active" in html
