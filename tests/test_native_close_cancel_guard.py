"""Native window closure must preserve in-flight wallet mutation proof."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import api_server
from app_bridge import AppBridge
from native_shutdown import native_close_readiness


def test_stopped_native_close_rejects_active_cancel_all(monkeypatch):
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": True})
    monkeypatch.setattr(api_server, "_cancel_all_thread", None)
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(is_running=lambda: False))
    with patch.object(api_server, "quiesce_and_release_mutation_runtime") as release:
        result = native_close_readiness()

    assert result["released"] is False
    assert result["reason"] == "cancel_all_in_progress"
    release.assert_not_called()


def test_native_close_rejects_unproven_mutation_quiescence(monkeypatch):
    runtime = MagicMock()
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": False})
    monkeypatch.setattr(api_server, "_cancel_all_thread", None)
    monkeypatch.setattr(api_server.mutation_gate, "current_runtime", lambda: runtime)
    with patch.object(
        api_server,
        "quiesce_and_release_mutation_runtime",
        return_value={"released": False, "reason": "mutations_in_flight"},
    ):
        result = native_close_readiness()

    assert result == {"released": False, "reason": "mutations_in_flight"}
    runtime.begin_quiesce.assert_called_once_with()


def test_native_close_allows_proven_release(monkeypatch):
    runtime = MagicMock()
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": False})
    monkeypatch.setattr(api_server, "_cancel_all_thread", None)
    monkeypatch.setattr(api_server.mutation_gate, "current_runtime", lambda: runtime)
    with patch.object(
        api_server,
        "quiesce_and_release_mutation_runtime",
        return_value={"released": True},
    ):
        result = native_close_readiness()

    assert result == {"released": True}
    runtime.begin_quiesce.assert_called_once_with()


def test_native_close_allows_no_runtime_only_when_idle(monkeypatch):
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": False})
    monkeypatch.setattr(api_server, "_cancel_all_thread", None)
    monkeypatch.setattr(api_server.mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(is_running=lambda: False))
    assert native_close_readiness() == {
        "released": True,
        "reason": "no_mutation_runtime",
    }
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(is_running=lambda: True))
    assert native_close_readiness() == {
        "released": False,
        "reason": "runtime_unavailable",
    }


def test_bridge_confirm_close_keeps_window_when_proof_incomplete(monkeypatch):
    window = MagicMock()
    fake_webview = SimpleNamespace(windows=[window])
    monkeypatch.setitem(__import__("sys").modules, "webview", fake_webview)
    fake_desktop = SimpleNamespace(
        _state={"confirmed_close": False},
        _cleanup=lambda: {"released": False, "reason": "mutations_in_flight"},
    )
    monkeypatch.setitem(__import__("sys").modules, "desktop_app", fake_desktop)
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(_running=False))
    result = AppBridge.confirm_close_window(AppBridge())

    assert result["success"] is False
    window.destroy.assert_not_called()
    assert fake_desktop._state.get("confirmed_close") is not True


def test_bridge_fallback_close_keeps_window_when_proof_incomplete(monkeypatch):
    window = MagicMock()
    fake_webview = SimpleNamespace(windows=[window])
    monkeypatch.setitem(__import__("sys").modules, "webview", fake_webview)
    fake_desktop = SimpleNamespace(
        _cleanup=lambda: {"released": False, "reason": "mutations_in_flight"}
    )
    monkeypatch.setitem(__import__("sys").modules, "desktop_app", fake_desktop)
    result = AppBridge.close_window(AppBridge())

    assert result["success"] is False
    window.destroy.assert_not_called()
