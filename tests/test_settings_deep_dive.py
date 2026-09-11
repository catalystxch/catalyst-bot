from pathlib import Path
import re
import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from api_test_support import api_mutations_permitted


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


def _number_input_constraints(source: str, field_id: str) -> dict[str, str]:
    match = re.search(rf'<input\b(?=[^>]*\bid="{re.escape(field_id)}")[^>]*>', source)
    assert match is not None, f"Missing number input {field_id}"
    markup = match.group(0)
    assert 'type="number"' in markup
    return dict(re.findall(r'\b(min|max|step)="([^"]+)"', markup))


def _assert_browser_accepts_number(source: str, field_id: str, value: str) -> None:
    constraints = _number_input_constraints(source, field_id)
    number = Decimal(value)
    if constraints.get("min"):
        assert number >= Decimal(constraints["min"]), (field_id, constraints, value)
    if constraints.get("max"):
        assert number <= Decimal(constraints["max"]), (field_id, constraints, value)
    step = constraints.get("step")
    if step and step != "any":
        base = Decimal(constraints.get("min", "0"))
        assert (number - base) % Decimal(step) == 0, (field_id, constraints, value)


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


def test_settings_save_handles_expired_session_before_reading_validation_errors():
    gui = GUI.read_text(encoding="utf-8")
    body = _extract_function_body(gui, "async function saveConfig()")

    response_guard = body.index("if (!validationResponse.ok")
    safe_error_read = body.index("validationErrors[0]")

    assert response_guard < safe_error_read
    assert "Array.isArray(validation.errors)" in body[response_guard:safe_error_read]
    guarded = body[response_guard:safe_error_read]
    assert "validationFailure = formatError(" in guarded
    assert "validationResponse.status === 401" in guarded


def test_successful_settings_save_refreshes_dashboard_before_coin_prep_handoff():
    gui = GUI.read_text(encoding="utf-8")
    body = _extract_function_body(gui, "async function saveConfig()")

    reviewed = body.index("setSettingsReviewedState(true);")
    dashboard_refresh = body.index("await fetchDashboard(currentCAT?.asset_id || '');")
    coin_prep_handoff = body.index("checkIfCoinPrepNeeded(config);")

    assert reviewed < dashboard_refresh < coin_prep_handoff


def test_smart_settings_generated_dbx_values_are_valid_number_inputs():
    """Browser constraints must accept the exact values Smart Settings emits.

    DBX live testing exposed stale MZ-era limits and coarse steps that marked
    the generated setup invalid before it could be saved reliably.
    """
    gui = GUI.read_text(encoding="utf-8")
    generated_values = {
        "configXchReserve": "14.592",
        "configTopupPoolCat": "119.854",
        "configMinMid": "0.0070246455",
        "configMaxMid": "0.0162584515",
        "configTradeXch": "1.3824",
        "configBuyInnerSizeXch": "0.6283",
        "configBuyMidSizeXch": "1.3824",
        "configBuyOuterSizeXch": "2.5134",
        "configBuyExtremeSizeXch": "4.5242",
        "configInnerSizeXch": "0.115",
        "configMidSizeXch": "0.0639",
        "configOuterSizeXch": "0.0351",
        "configExtremeSizeXch": "0.016",
        "configBaseSpreadBps": "25.7",
        "configMinEdgeBps": "10.3",
        "configMinSpreadBps": "15.4",
        "configMaxSpreadBps": "30.9",
        "configRequoteBps": "14.2",
        "configRequoteCooldown": "45",
        "configSniperSizeXch": "0",
        "configTransactionFeeXch": "0.0000130791",
    }

    for field_id, value in generated_values.items():
        _assert_browser_accepts_number(gui, field_id, value)

    save_markup = re.search(r'<button\b(?=[^>]*\bid="saveConfigBtn")[^>]*>', gui).group(
        0
    )
    assert 'type="button"' in save_markup


def test_saved_smart_tier_template_survives_asymmetric_offer_limits_on_reload():
    """A fuller-side Smart template must not be replaced after app restart.

    Live DBX Smart Settings produced 45 buy / 44 sell offers with one shared
    45-slot template.  Treating the smaller side as a mismatch replaced the
    saved market-adaptive counts and made Coin Prep exceed the XCH balance.
    """
    gui = GUI.read_text(encoding="utf-8")

    assert "const fullerSide = Math.max(mb || 0, ms || 0);" in gui
    assert "fullerSide !== loadedTierTotal" in gui
    assert "mb !== loadedTierTotal || ms !== loadedTierTotal" not in gui


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
        api_mutations_permitted(api_server),
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
        api_mutations_permitted(api_server),
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
        api_mutations_permitted(api_server),
        patch.object(api_server, "bot", fake_bot),
        patch.object(api_server, "cfg", fake_cfg),
        patch(
            "blueprints.bot._enforce_post_tibet_start_migration",
            return_value={
                "can_start": True,
                "reason_code": "POST_TIBET_MIGRATION_READY",
            },
        ),
        patch.object(api_server, "_get_sage_signing_block_reason", return_value=None),
        patch(
            "wallet.get_wallet_sync_status",
            return_value={"reachable": True, "sync_state": "synced"},
        ),
        patch(
            "wallet.preflight_wallet_identity",
            return_value={"success": True, "reason": "identity_verified"},
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


def test_sticky_toast_message_cannot_block_setup_controls():
    """Persistent errors stay readable without intercepting the page beneath them."""
    gui = GUI.read_text(encoding="utf-8")

    toast_rule = re.search(r"\.toast\s*\{(?P<body>.*?)\n\s*\}", gui, re.S)
    close_rule = re.search(r"\.toast \.toast-close\s*\{(?P<body>.*?)\n\s*\}", gui, re.S)

    assert toast_rule is not None
    assert close_rule is not None
    assert "pointer-events: none" in toast_rule.group("body")
    assert "pointer-events: auto" in close_rule.group("body")
