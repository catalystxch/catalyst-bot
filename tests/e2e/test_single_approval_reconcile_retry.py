"""An in-flight prep effect must not abandon an already approved run."""

from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e
GUI = Path(__file__).resolve().parents[2] / "bot_gui.html"


def test_approved_run_retries_transient_prep_reconciliation_gate(page):
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            const sessionId = 'a'.repeat(64);
            const originalSetTimeout = window.setTimeout;
            let advances = 0;
            let statusReads = 0;
            window.setTimeout = (fn, delay, ...args) =>
                originalSetTimeout(fn, delay === 7000 ? 0 : delay, ...args);
            window.pywebview = {api: {
                advance_single_approval_follow_run: async () => {
                    advances++;
                    return advances === 1
                        ? {success: false, reason: 'COIN_PREP_EFFECT_UNKNOWN'}
                        : {success: true, state: 'running', message: 'Ladder running'};
                },
                get_single_approval_follow_run_status: async () => {
                    statusReads++;
                    return {success: true, state: 'preparing', session_id: sessionId};
                },
            }};
            try {
                await advanceSingleApprovalRun(sessionId);
                return {advances, statusReads,
                    progress: document.getElementById('singleApprovalRunProgress').textContent};
            } finally {
                window.setTimeout = originalSetTimeout;
            }
        }"""
    )

    assert result["advances"] == 2
    assert result["statusReads"] == 1
    assert "COIN_PREP_EFFECT_UNKNOWN" not in result["progress"]


def test_approved_run_does_not_retry_unknown_effect_for_different_session(page):
    page.route("http://**/*", lambda route: route.abort())
    page.route("https://**/*", lambda route: route.abort())
    page.goto(GUI.as_uri(), wait_until="domcontentloaded")

    result = page.evaluate(
        """async () => {
            const sessionId = 'a'.repeat(64);
            let advances = 0;
            window.pywebview = {api: {
                advance_single_approval_follow_run: async () => {
                    advances++;
                    return {success: false, reason: 'COIN_PREP_EFFECT_UNKNOWN'};
                },
                get_single_approval_follow_run_status: async () => ({
                    success: true, state: 'preparing', session_id: 'b'.repeat(64),
                }),
            }};
            await advanceSingleApprovalRun(sessionId);
            return {advances,
                progress: document.getElementById('singleApprovalRunProgress').textContent};
        }"""
    )

    assert result["advances"] == 1
    assert "COIN_PREP_EFFECT_UNKNOWN" in result["progress"]
