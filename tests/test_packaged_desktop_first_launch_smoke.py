"""Release-gate coverage for the packaged Windows desktop smoke test."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

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
