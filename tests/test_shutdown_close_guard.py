"""Native close must not kill an active cancel-on-exit worker."""

import ast
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("confirmed_close", [False, True])
@pytest.mark.parametrize("active", [False, True])
def test_native_close_waits_for_cancel_worker(monkeypatch, confirmed_close, active):
    source = Path(__file__).resolve().parents[1] / "desktop_app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "on_closing"
    )
    cleanup = Mock()
    namespace = {
        "_state": {"confirmed_close": confirmed_close},
        "_cleanup": cleanup,
        "_save_window_state": Mock(),
        "window": Mock(),
        "tray": None,
    }
    fake = SimpleNamespace(
        bot=SimpleNamespace(_running=False),
        _cancel_all_thread=SimpleNamespace(is_alive=lambda: active),
        _cancel_all_state={"running": active},
        _cancel_all_state_lock=threading.Lock(),
    )
    monkeypatch.setitem(sys.modules, "api_server", fake)
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    assert namespace["on_closing"]() is (not active)
    assert cleanup.call_count == int(not active)
