import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_linux_release_build_installs_qt_webview_backend():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )
    linux_requirements = ROOT / "requirements-linux.txt"

    assert "requirements-linux.txt" in workflow
    assert linux_requirements.is_file()

    requirements = linux_requirements.read_text(encoding="utf-8")
    assert "qtpy" in requirements
    assert "PyQt6-WebEngine" in requirements


def test_linux_pyinstaller_spec_bundles_qt_backend():
    spec = (ROOT / "catalyst.spec").read_text(encoding="utf-8")

    for hidden_import in (
        "webview.platforms.qt",
        "qtpy",
        "qtpy.QtWebEngineWidgets",
        "PyQt6.QtWebEngineWidgets",
    ):
        assert hidden_import in spec


def test_linux_release_ci_runs_desktop_smoke_test():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )
    smoke_script = ROOT / "scripts" / "linux_desktop_smoke.sh"

    assert smoke_script.is_file()
    assert "scripts/linux_desktop_smoke.sh" in workflow
    assert "xvfb-run" in smoke_script.read_text(encoding="utf-8")


def test_linux_qt_xcb_runtime_dependencies_are_declared():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )
    package_script = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")

    for package in (
        "libxcb-cursor0",
        "libxcb-icccm4",
        "libxcb-image0",
        "libxcb-keysyms1",
        "libxcb-randr0",
        "libxcb-render-util0",
        "libxcb-shape0",
        "libxcb-sync1",
        "libxcb-xinerama0",
        "libxcb-xkb1",
        "libxkbcommon-x11-0",
    ):
        assert package in workflow
        assert package in package_script


def test_linux_notification_runtime_dependencies_are_declared():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )
    package_script = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")

    assert "libnotify-bin" in workflow
    assert "libnotify-bin" in package_script


def test_linux_detect_gui_backend_prefers_qt_when_available(monkeypatch):
    sys.modules.pop("desktop_app", None)
    monkeypatch.setattr(sys, "platform", "linux")
    desktop_app = importlib.import_module("desktop_app")

    monkeypatch.setattr(
        desktop_app.importlib.util,
        "find_spec",
        lambda name: object() if name == "qtpy" else None,
    )

    assert desktop_app._detect_gui_backend() == "qt"
