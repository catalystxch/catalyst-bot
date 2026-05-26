from pathlib import Path
import re
import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock, patch

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


def test_setup_config_save_while_running_is_deferred_to_restart():
    sys.path.insert(0, str(ROOT))
    api_server = pytest.importorskip("api_server")

    api_server.app.testing = True
    client = api_server.app.test_client()
    api_server._rate_limit_log.clear()

    fake_bot = types.SimpleNamespace(is_running=lambda: True)
    fake_cfg = MagicMock()
    fake_cfg.update.return_value = True
    fake_cfg.update_persisted.return_value = True
    fake_cfg.to_dict.return_value = {}
    fake_cfg.LIQUIDITY_MODE = "two_sided"
    fake_cfg.SNIPER_ENABLED = False
    fake_cfg.MAX_ACTIVE_BUY_OFFERS = 1
    fake_cfg.MAX_ACTIVE_SELL_OFFERS = 1

    with (
        patch.object(api_server, "bot", fake_bot),
        patch.object(api_server, "cfg", fake_cfg),
    ):
        resp = client.post(
            "/api/config",
            json={"key": "LOOP_SECONDS", "value": "46"},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["apply_mode"] == "next_restart"
    fake_cfg.update.assert_not_called()
    fake_cfg.update_persisted.assert_called_once()
    assert fake_cfg.update_persisted.call_args.args[:2] == ("LOOP_SECONDS", "46")


def test_setup_save_while_running_allows_unchanged_liquidity_mode():
    sys.path.insert(0, str(ROOT))
    api_server = pytest.importorskip("api_server")

    api_server.app.testing = True
    client = api_server.app.test_client()
    api_server._rate_limit_log.clear()

    fake_bot = types.SimpleNamespace(is_running=lambda: True)
    fake_cfg = MagicMock()
    fake_cfg.update_persisted.return_value = True
    fake_cfg.to_dict.return_value = {}
    fake_cfg.LIQUIDITY_MODE = "two_sided"
    fake_cfg.SNIPER_ENABLED = False
    fake_cfg.MAX_ACTIVE_BUY_OFFERS = 1
    fake_cfg.MAX_ACTIVE_SELL_OFFERS = 1

    with (
        patch.object(api_server, "bot", fake_bot),
        patch.object(api_server, "cfg", fake_cfg),
    ):
        resp = client.post(
            "/api/config",
            json={"loop_seconds": 46, "liquidity_mode": "two_sided"},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["apply_mode"] == "next_restart"
    written = {
        call.args[0]: call.args[1] for call in fake_cfg.update_persisted.call_args_list
    }
    assert written["LOOP_SECONDS"] == "46"
    assert written["LIQUIDITY_MODE"] == "two_sided"


def test_bot_start_reloads_deferred_setup_config_before_validation():
    sys.path.insert(0, str(ROOT))
    api_server = pytest.importorskip("api_server")

    api_server.app.testing = True
    client = api_server.app.test_client()
    api_server._rate_limit_log.clear()

    fake_bot = MagicMock()
    fake_bot.is_running.return_value = False
    fake_bot.start.return_value = True

    fake_cfg = types.SimpleNamespace(
        reload=MagicMock(),
        has_pending_restart_changes=lambda: True,
        CAT_ASSET_ID="abc123",
        SPREAD_BPS=Decimal("200"),
        HARD_MIN_PRICE_XCH=Decimal("0.00001"),
        HARD_MAX_PRICE_XCH=Decimal("1"),
        DYNAMIC_LIMIT_PCT=Decimal("0"),
        ENABLE_COIN_PREP=False,
        MAX_ACTIVE_BUY_OFFERS=1,
        MAX_ACTIVE_SELL_OFFERS=1,
    )

    with (
        patch.object(api_server, "bot", fake_bot),
        patch.object(api_server, "cfg", fake_cfg),
        patch.object(api_server, "_get_sage_signing_block_reason", return_value=None),
        patch(
            "wallet.get_wallet_sync_status",
            return_value={"reachable": True, "sync_state": "synced"},
        ),
        patch("coin_manager.check_tier_size_drift_standalone", return_value=[]),
    ):
        resp = client.post(
            "/api/bot/start",
            json={},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "started"
    fake_cfg.reload.assert_called_once()


def test_sniper_live_toggle_uses_live_config_endpoint():
    gui = GUI.read_text(encoding="utf-8")
    body = _extract_function_body(gui, "async function lcToggle(configKey, el)")

    assert "'SNIPER_ENABLED'" in body
    quote_only = re.search(
        r"const quoteOnlyKeys = new Set\(\[(?P<body>.*?)\]\);", body, re.S
    ).group("body")

    assert "'SNIPER_ENABLED'" in quote_only
