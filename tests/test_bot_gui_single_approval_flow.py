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
