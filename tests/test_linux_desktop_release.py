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
    smoke_source = smoke_script.read_text(encoding="utf-8")

    assert smoke_script.is_file()
    assert "scripts/linux_desktop_smoke.sh" in workflow
    assert "xvfb-run" in smoke_source
    assert "xdotool search" in smoke_source
    assert "CATALYST_GUI_PROOF_SCREENSHOT" in smoke_source
    assert "nonblank" in smoke_source
    assert "exited before visible window proof" in smoke_source
    assert "xdotool" in workflow
    assert "x11-apps" in workflow
    assert "openbox" in workflow


def test_release_build_and_linux_package_purge_runtime_sidecars():
    build_source = (ROOT / "build.py").read_text(encoding="utf-8")
    package_source = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")

    for source in (build_source, package_source):
        assert "coin_prep_status.json" in source
        assert "coin_prep_last.json" in source
        assert "coin_prep_output.log" in source
        assert "bot_superlog_*.log" in source
        assert "user_secrets.json" in source

    assert "_purge_runtime_artifacts(OUTPUT_DIR)" in build_source
    assert 'purge_runtime_artifacts "$bundle_dir"' in package_source
    assert 'purge_runtime_artifacts "$appdir/usr/lib/catalyst"' in package_source
    assert 'purge_runtime_artifacts "$deb_root/opt/catalyst"' in package_source


def test_build_runtime_artifact_purge_keeps_worker_source(tmp_path):
    import build

    internal = tmp_path / "_internal"
    internal.mkdir()
    for name in (
        "coin_prep_status.json",
        "coin_prep_last.json",
        "coin_prep_output.log",
        "bot_superlog_20260521_000000.log",
        "user_secrets.json",
    ):
        (internal / name).write_text("stale", encoding="utf-8")
    worker = internal / "coin_prep_worker.py"
    worker.write_text("print('worker')\n", encoding="utf-8")

    removed = build._purge_runtime_artifacts(str(tmp_path))

    assert removed == 5
    assert worker.exists()
    assert not (internal / "coin_prep_status.json").exists()
    assert not (internal / "coin_prep_last.json").exists()
    assert not (internal / "coin_prep_output.log").exists()


def test_desktop_tray_start_waits_before_claiming_active():
    source = (ROOT / "desktop_app.py").read_text(encoding="utf-8")

    assert "def _start_system_tray" in source
    assert "settle_seconds" in source
    assert "desktop tray unavailable" in source
    assert 'not getattr(tray, "is_running", False)' in source
    assert "not tray_thread.is_alive()" in source


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


def test_linux_saved_window_position_is_not_restored_by_default(monkeypatch):
    sys.modules.pop("desktop_app", None)
    original_platform = sys.platform
    try:
        sys.platform = "linux"
        desktop_app = importlib.import_module("desktop_app")
        should_restore = desktop_app._should_restore_saved_window_position()
    finally:
        sys.platform = original_platform

    assert should_restore is False


def test_windows_saved_window_position_is_restored_by_default(monkeypatch):
    sys.modules.pop("desktop_app", None)
    original_platform = sys.platform
    try:
        sys.platform = "linux"
        desktop_app = importlib.import_module("desktop_app")
        desktop_app.sys.platform = "win32"
        should_restore = desktop_app._should_restore_saved_window_position()
    finally:
        sys.platform = original_platform

    assert should_restore is True


def test_coin_prep_runtime_sidecars_use_user_data_dir():
    import user_paths
    import api_server  # noqa: F401 - load blueprints through the app entry point
    from blueprints import coin_prep

    data_dir = Path(user_paths.data_dir())

    paths = [
        Path(user_paths.coin_prep_status_file()),
        Path(user_paths.coin_prep_output_log_file()),
        Path(user_paths.coin_prep_last_file()),
        Path(coin_prep._coin_prep_status_file()),
        Path(coin_prep._coin_prep_output_log_file()),
        Path(coin_prep._coin_prep_last_file()),
    ]

    for path in paths:
        assert path.parent == data_dir


def test_coin_prep_last_file_falls_back_to_legacy_install_copy(tmp_path, monkeypatch):
    import api_server  # noqa: F401 - load blueprints through the app entry point
    import user_paths
    from blueprints import coin_prep

    data_last = tmp_path / "data" / "coin_prep_last.json"
    legacy_dir = tmp_path / "install"
    legacy_dir.mkdir()
    legacy_last = legacy_dir / "coin_prep_last.json"
    legacy_last.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(user_paths, "coin_prep_last_file", lambda: str(data_last))
    monkeypatch.setattr(coin_prep, "_PACKAGE_DIR", str(legacy_dir))

    assert Path(coin_prep._coin_prep_last_file()) == legacy_last
