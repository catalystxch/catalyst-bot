from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function_source(gui: str, name: str) -> str:
    marker = f"function {name}("
    start = gui.index(marker)
    next_function = gui.find("\n        function ", start + len(marker))
    if next_function < 0:
        next_function = gui.find("\nfunction ", start + len(marker))
    assert next_function > start
    return gui[start:next_function]


def test_running_bot_reactively_dismisses_stale_startup_overlays():
    gui = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    update_ui = _function_source(gui, "updateUI")
    dismiss = _function_source(gui, "dismissStartupOverlaysForRunningBot")

    assert "if (isRunning)" in update_ui
    assert "dismissStartupOverlaysForRunningBot();" in update_ui
    assert "startupOverlay" in dismiss
    assert "splashGateOverlay" in dismiss
    assert "spacescanGateOverlay" in dismiss
    assert "_startupGatesComplete = true" in dismiss


def test_restored_live_book_can_resume_without_repeating_coin_prep_review():
    """Live offers are proof of prior prep; stale prep metadata must not lock Resume."""
    gui = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    start_gate = _function_source(gui, "canAttemptBotStart")
    checklist = _function_source(gui, "updateStartupChecklist")
    start_bot = _function_source(gui, "startBot")

    assert "hasResumedLiveBook()" in start_gate
    assert "coinPrepStatus !== 'checking'" in start_gate
    assert "hasResumedLiveBook()" in checklist
    assert "Existing live offers are already using prepared coins" in checklist
    assert "coinPrepStatus === 'none' && !hasResumedLiveBook()" in start_bot
