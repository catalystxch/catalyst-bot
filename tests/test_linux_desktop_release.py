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


def test_linux_deb_wrapper_exports_qt_webengine_loopback_flags():
    package_script = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")
    deb_wrapper_start = package_script.index('cat > "$deb_root/usr/bin/catalyst"')
    deb_wrapper = package_script[deb_wrapper_start:]

    assert "FONTCONFIG_FILE" in package_script
    assert "FONTCONFIG_PATH" in package_script
    assert "QTWEBENGINE_CHROMIUM_FLAGS" in deb_wrapper
    assert "--disable-features=BlockInsecurePrivateNetworkRequests" in deb_wrapper
    assert "PrivateNetworkAccessSendPreflights" in deb_wrapper
    assert "--allow-insecure-localhost" in deb_wrapper
    assert "fontconfig" in package_script


def test_linux_appimage_launcher_exports_same_runtime_env():
    package_script = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")
    apprun_start = package_script.index('cat > "$appdir/AppRun"')
    apprun = package_script[apprun_start:]

    assert "FONTCONFIG_FILE" in apprun
    assert "QTWEBENGINE_CHROMIUM_FLAGS" in apprun
    assert "PrivateNetworkAccessSendPreflights" in apprun


def test_linux_packages_drop_splash_html_workaround():
    package_script = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")

    assert 'rm -f "$appdir/usr/lib/catalyst/splash.html"' in package_script
    assert 'rm -f "$deb_root/opt/catalyst/splash.html"' in package_script


def test_linux_desktop_window_wires_loopback_initial_url():
    text = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
    assert "_initial_desktop_url()" in text
    assert "_configure_linux_webengine_env()" in text
    assert "_splash_path = _bundle_path" not in text


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


def test_linux_detect_gui_backend_uses_qt_in_frozen_build(monkeypatch):
    sys.modules.pop("desktop_app", None)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    desktop_app = importlib.import_module("desktop_app")

    monkeypatch.setattr(
        desktop_app.importlib.util,
        "find_spec",
        lambda name: None,
    )

    assert desktop_app._detect_gui_backend() == "qt"


def test_linux_initial_desktop_url_uses_loopback(monkeypatch):
    sys.modules.pop("desktop_app", None)
    monkeypatch.setattr(sys, "platform", "linux")
    desktop_app = importlib.import_module("desktop_app")

    assert desktop_app._initial_desktop_url() == "http://127.0.0.1:5000/"


def test_build_py_verifies_linux_desktop_source_before_pyinstaller():
    build_py = (ROOT / "build.py").read_text(encoding="utf-8")
    assert "def _verify_linux_desktop_source" in build_py
    assert "    _verify_linux_desktop_source()" in build_py


def test_linux_package_launchers_export_qt_webengine_flags():
    package_script = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")
    assert "BlockInsecurePrivateNetworkRequests" in package_script
    assert "FONTCONFIG_FILE" in package_script


def test_linux_desktop_smoke_requires_loopback_url():
    smoke = (ROOT / "scripts" / "linux_desktop_smoke.sh").read_text(encoding="utf-8")
    assert "Desktop window URL: http://127.0.0.1:5000/" in smoke
