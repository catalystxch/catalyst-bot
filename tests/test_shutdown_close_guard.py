"""Native close must remain responsive while guarding cancellation workers."""

import ast
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def close_harness(monkeypatch):
    # Import only this factory: importing the desktop launcher changes the
    # process cwd/stdout and starts application bootstrap dependencies.
    source = Path(__file__).resolve().parents[1] / "desktop_app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_create_close_handler"
    )
    threads = []

    def tracked_thread(**kwargs):
        thread = threading.Thread(**kwargs)
        threads.append(thread)
        return thread

    window = Mock()
    window.evaluate_js.return_value = False
    cleanup = Mock(return_value={"released": True})
    namespace = {
        "_state": {"confirmed_close": False},
        "_cleanup": cleanup,
        "_save_window_state": Mock(),
        "threading": SimpleNamespace(Lock=threading.Lock, Thread=tracked_thread),
    }
    api = SimpleNamespace(
        bot=SimpleNamespace(_running=False),
        _cancel_all_thread=None,
        _cancel_all_state={"running": False},
        _cancel_all_state_lock=threading.Lock(),
    )
    monkeypatch.setitem(sys.modules, "api_server", api)
    monkeypatch.setitem(sys.modules, "super_log", SimpleNamespace(slog=Mock()))
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    handler = namespace["_create_close_handler"](window, None)

    def drain():
        for thread in threads:
            thread.join(timeout=3)
            assert not thread.is_alive(), "Native close coordinator did not finish"

    yield SimpleNamespace(
        window=window,
        cleanup=cleanup,
        state=namespace["_state"],
        api=api,
        handler=handler,
        drain=drain,
        threads=threads,
    )
    drain()


@pytest.mark.parametrize("confirmed_close", [False, True])
@pytest.mark.parametrize("active", [False, "state", "thread"])
@pytest.mark.parametrize("flow_active", [False, True])
def test_native_close_waits_for_cancel_worker(
    close_harness, confirmed_close, active, flow_active
):
    h = close_harness
    h.state["confirmed_close"] = confirmed_close
    h.api._cancel_all_state["running"] = active == "state"
    h.api._cancel_all_thread = SimpleNamespace(is_alive=lambda: active == "thread")
    h.window.evaluate_js.return_value = flow_active
    assert h.handler() is False
    h.drain()
    allowed = not active and (confirmed_close or not flow_active)
    assert h.cleanup.call_count == int(allowed)
    assert h.window.destroy.call_count == int(allowed)
    if allowed:
        assert h.handler() is True


def test_native_close_callback_never_waits_for_ui_javascript(close_harness):
    """Use PyWebView's actual synchronous Event, as WinForms FormClosing does."""
    from webview.event import Event

    h = close_harness
    ui_thread = threading.get_ident()
    ui_returned = threading.Event()
    attempts = []

    def ui_call(*args):
        attempts.append(threading.get_ident())
        assert ui_returned.wait(timeout=1)
        return False

    h.window.evaluate_js.side_effect = ui_call
    h.cleanup.side_effect = lambda: (ui_call(), {"released": True})[1]
    closing = Event(h.window, True)
    closing += h.handler
    assert closing.set() is True
    ui_returned.set()
    h.drain()
    assert attempts and ui_thread not in attempts
    h.window.destroy.assert_called_once()


def test_repeated_native_close_deduplicates_pending_probe(close_harness):
    h = close_harness
    entered, release = threading.Event(), threading.Event()

    def blocked_js(*args):
        entered.set()
        assert release.wait(timeout=2)
        return True

    h.window.evaluate_js.side_effect = blocked_js
    try:
        assert h.handler() is False
        assert entered.wait(timeout=1)
        for _ in range(10):
            assert h.handler() is False
        assert len(h.threads) == 1
    finally:
        release.set()
    h.drain()
    h.window.destroy.assert_not_called()
    h.window.evaluate_js.side_effect = None
    h.window.evaluate_js.return_value = False
    assert h.handler() is False
    h.drain()
    h.window.destroy.assert_called_once()


@pytest.mark.parametrize("js_state", [None, 0, "false", RuntimeError("unreadable")])
def test_unreadable_gui_state_preserves_window(close_harness, js_state):
    h = close_harness
    if isinstance(js_state, Exception):
        h.window.evaluate_js.side_effect = js_state
    else:
        h.window.evaluate_js.return_value = js_state
    assert h.handler() is False
    h.drain()
    h.cleanup.assert_not_called()
    h.window.destroy.assert_not_called()


def test_running_bot_routes_to_modal_without_cleanup(close_harness):
    h = close_harness
    h.api.bot._running = True
    assert h.handler() is False
    h.drain()
    h.window.evaluate_js.assert_any_call(
        "window.showShutdownModal && window.showShutdownModal();"
    )
    h.cleanup.assert_not_called()
    h.window.destroy.assert_not_called()


def test_modal_error_does_not_fall_back_to_hard_close(close_harness):
    h = close_harness
    h.api.bot._running = True
    h.window.evaluate_js.side_effect = [False, RuntimeError("modal unavailable")]
    assert h.handler() is False
    h.drain()
    h.cleanup.assert_not_called()
    h.window.destroy.assert_not_called()


@pytest.mark.parametrize("cleanup", [None, {}, {"released": False}])
def test_failed_cleanup_keeps_window_open(close_harness, cleanup):
    h = close_harness
    h.cleanup.return_value = cleanup
    assert h.handler() is False
    h.drain()
    h.window.destroy.assert_not_called()
