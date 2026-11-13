from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_single_approval_gui_uses_native_review_and_automatic_advance():
    html = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert 'id="singleApprovalRunBtn"' in html
    assert "get_single_approval_follow_run_defaults" in html
    assert "prepare_single_approval_follow_run_review({policy})" in html
    assert "confirm_single_approval_follow_run_review({" in html
    assert "advance_single_approval_follow_run" in html
    confirm = html.split("async function confirmSingleApprovalRunReview()", 1)[1].split(
        "async function advanceSingleApprovalRun", 1
    )[0]
    assert "closeFollowRunReview();" not in confirm


def test_primary_native_save_enters_single_review():
    html = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    assert 'id="saveConfigBtn" onclick="handlePrimarySettingsSave()"' in html
    save = html.split("function handlePrimarySettingsSave()", 1)[1].split(
        "function clearSingleApprovalRunSaveIntent()", 1
    )[0]
    assert "IS_DESKTOP && !bot_state?.running" in save
    assert "saveSettingsAndReviewSingleRun();" in save


def test_single_approval_disclosure_uses_text_nodes_and_exact_atomic_strings():
    html = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    flow = html.split("async function prepareSingleApprovalRunReview()", 1)[1].split(
        "async function confirmSingleApprovalRunReview()", 1
    )[0]

    assert "output.textContent = [" in flow
    assert "singleRunXchToMojos" in flow
    assert "maximum_fee_mojos_per_tx: feeMojos" in flow
    assert "innerHTML" not in flow


def test_single_approval_is_only_offered_for_fresh_smart_settings():
    html = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    dirty_check = html.split("function checkSmartSettingsDirty()", 1)[1].split(
        "function _bindSmartSettingsBannerListeners()", 1
    )[0]

    assert "runButton.style.display = 'none'" in dirty_check
    assert "runButton.style.display = 'inline-flex'" in dirty_check
    assert "saveSettingsAndReviewSingleRun()" in html


def test_approved_run_resumes_from_read_only_status_without_duplicate_pollers():
    html = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    recovery = html.split("async function recoverSingleApprovalRunOnStartup()", 1)[
        1
    ].split("let _followRunReview", 1)[0]
    polling = html.split("async function advanceSingleApprovalRun(sessionId)", 1)[
        1
    ].split("async function recoverSingleApprovalRunOnStartup()", 1)[0]

    assert "get_single_approval_follow_run_status" in recovery
    assert "['prep_pending', 'preparing', 'ready', 'start_pending']" in recovery
    assert "runState === 'recoverable_error'" in recovery
    assert "_singleApprovalRunPollingPromise" in polling
    assert "_singleApprovalRunPollSession === sessionId" in polling
    assert "setTimeout(resolve, 7000)" in polling
    assert "attempt < 120" not in polling


def test_above_cap_warning_offers_scoped_native_confirmation_without_restart():
    html = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    prompt = html.split("async function reviewRaisedFollowFeeCap", 1)[1].split(
        "async function advanceSingleApprovalRun", 1
    )[0]
    assert "prepare_follow_run_fee_cap_grant({})" in prompt
    assert "confirm_follow_run_fee_cap_grant({" in prompt
    assert "window.confirm(" in prompt
    assert "The bot is still running" in prompt
    assert "does not restart setup" in prompt
    assert "review.proposed_maximum_fee_mojos_per_tx" in prompt
    assert "state.fee_warning.run_id || sessionId" in html
    assert "void reviewRaisedFollowFeeCap(" in html


def test_smart_settings_retains_manual_targets_and_discloses_sizing_estimate():
    html = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    smart_settings = html.split("async function getSmartDefaults()", 1)[1].split(
        '// ── "Settings changed since Smart Settings" tracker', 1
    )[0]

    assert "const _smartRequestedBuy" in smart_settings
    assert "const _smartRequestedSell" in smart_settings
    assert "Math.max(...selectedTargets)" in smart_settings
    assert (
        "if (!_preserveBuyTarget && data.max_active_buy !== undefined)"
        in smart_settings
    )
    assert (
        "if (!_preserveSellTarget && data.max_active_sell !== undefined)"
        in smart_settings
    )
    assert "Requested targets retained" in smart_settings


def test_single_review_collects_save_warnings_and_keeps_blockers():
    html = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    save_config = html.split("async function saveConfig()", 1)[1].split(
        "function closeCtgErrorModal()", 1
    )[0]
    review = html.split("async function prepareSingleApprovalRunReview()", 1)[1].split(
        "async function confirmSingleApprovalRunReview()", 1
    )[0]

    assert "_singleApprovalRunWarnings.push(lowSpreadWarning)" in save_config
    assert "_singleApprovalRunWarnings.push(..._riskWarnings)" in save_config
    assert "_singleApprovalRunWarnings.push(...validationWarnings" in save_config
    assert "if (_riskBlockers.length > 0)" in save_config
    assert "Save warnings:" in review
