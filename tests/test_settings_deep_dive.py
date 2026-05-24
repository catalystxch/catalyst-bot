from pathlib import Path
import os
import re
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "bot_gui.html"


def _extract_function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index, char in enumerate(source[brace:], start=brace):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract function body for {signature}")


def _settings_setup_markup(source: str) -> str:
    return re.search(
        r'<div class="v4-settings-subview is-active" id="settingsSetupView">'
        r"(?P<body>.*?)\n\s*</div>\s*<!-- /#settingsSetupView -->",
        source,
        re.S,
    ).group("body")


def _settings_field_ids(source: str) -> set[str]:
    body = re.search(
        r"const SETTINGS_FIELD_IDS = \[(?P<body>.*?)\];", source, re.S
    ).group("body")
    return set(re.findall(r"'([^']+)'", body))


def _save_config_input_ids(source: str) -> set[str]:
    body = _extract_function_body(source, "async function saveConfig()")
    return {
        field_id
        for field_id in re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", body)
        if field_id.startswith("config")
    }


def test_saved_setup_controls_are_tracked_for_dirty_state_preservation():
    gui = GUI.read_text(encoding="utf-8")
    setup_markup = _settings_setup_markup(gui)
    setup_ids = set(
        re.findall(r'<(?:input|select|textarea)\b[^>]*\bid="([^"]+)"', setup_markup)
    )
    saved_setup_ids = _save_config_input_ids(gui) & setup_ids
    tracked_ids = _settings_field_ids(gui)

    missing = sorted(saved_setup_ids - tracked_ids)

    assert missing == []


def test_removed_max_mid_move_setting_is_not_visible_in_setup():
    gui = GUI.read_text(encoding="utf-8")
    setup_markup = _settings_setup_markup(gui)

    assert 'id="configMaxMidMove"' not in setup_markup
    assert "Max Price Move" not in setup_markup


def test_settings_validate_rejects_negative_topup_budget():
    sys.path.insert(0, str(ROOT))
    api_server = pytest.importorskip("api_server")

    api_server.app.testing = True
    client = api_server.app.test_client()
    api_server._rate_limit_log.clear()

    resp = client.post(
        "/api/settings/validate",
        json={"topup_pool_xch": -1, "topup_pool_cat": 0, "topup_pool_pct": 0.2},
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valid"] is False
    assert any("Topup" in msg for msg in body["errors"])
