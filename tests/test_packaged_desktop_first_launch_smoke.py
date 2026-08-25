"""Release-gate coverage for the packaged Windows desktop smoke test."""

from __future__ import annotations

import io
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import packaged_desktop_first_launch_smoke as smoke


class _Response:
    def __init__(self, body: str, content_type: str):
        self._body = io.BytesIO(body.encode("utf-8"))
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body.read()


def test_first_launch_waits_for_visible_native_catalyst_window(monkeypatch):
    process = SimpleNamespace(pid=7365, returncode=None, poll=lambda: None)
    html = '<main id="startupOverlay">Risk Disclosure CATalyst</main>'
    safety = json.dumps({"safety": {"allowed": False}})
    native_checks = []

    def fake_urlopen(url, timeout):
        del timeout
        if url.endswith("/api/safety/status"):
            return _Response(safety, "application/json")
        return _Response(html, "text/html; charset=utf-8")

    def visible_window(process_id):
        native_checks.append(process_id)
        return None if len(native_checks) == 1 else "CATalyst"

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        smoke, "_visible_catalyst_window", visible_window, raising=False
    )
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)

    smoke._wait_for_first_launch(51345, process)

    assert native_checks == [7365, 7365]


def test_duplicate_launch_must_exit_instead_of_serving_raw_diagnostics():
    class Process:
        @staticmethod
        def wait(timeout):
            raise subprocess.TimeoutExpired("Catalyst.exe", timeout)

    with pytest.raises(
        smoke.SmokeFailure,
        match="duplicate desktop launch did not hand off",
    ):
        smoke._wait_for_duplicate_launch_handoff(Process())


def test_safety_fallback_waits_for_branded_native_window(monkeypatch):
    process = SimpleNamespace(pid=7366, returncode=None, poll=lambda: None)
    html = "<h1>CATalyst could not start normally</h1>"
    safety = json.dumps({"safety": {"allowed": False}})

    def fake_urlopen(url, timeout):
        del timeout
        if ":51346/" not in url:
            raise OSError("not the diagnostics port")
        if url.endswith("/api/safety/status"):
            return _Response(safety, "application/json")
        return _Response(html, "text/html; charset=utf-8")

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        smoke,
        "_visible_catalyst_window",
        lambda _process_id: "CATalyst Startup Safety",
    )

    smoke._wait_for_safety_fallback(51345, process)
