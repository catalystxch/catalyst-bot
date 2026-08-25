#!/usr/bin/env python3
"""Verify a packaged Windows executable opens the clean first-run desktop UI."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

if os.name == "nt":
    import ctypes.wintypes


class SmokeFailure(RuntimeError):
    """Raised when the packaged desktop first-launch contract is broken."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _clean_first_launch_env(data_dir: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "SAGE_FINGERPRINT",
        "WALLET_FINGERPRINT",
        "WALLET_EXPECTED_NAME",
        "WALLET_EXPECTED_KEY_KIND",
        "_CATALYST_PRESERVE_PROCESS_ENV",
    ):
        env.pop(key, None)
    env.update(
        {
            "CMM_DATA_DIR": str(data_dir),
            "CATALYST_FLASK_PORT": str(port),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def _visible_catalyst_window(process_id: int) -> str | None:
    """Return the title of a visible CATalyst top-level window for one PID."""

    if os.name != "nt":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    titles: list[str] = []
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )

    @callback_type
    def inspect_window(handle, _context):
        if not user32.IsWindowVisible(handle):
            return True
        owner_pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner_pid))
        if owner_pid.value != process_id:
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length < 1:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, len(buffer))
        title = buffer.value.strip()
        if "catalyst" in title.lower():
            titles.append(title)
            return False
        return True

    user32.EnumWindows(inspect_window, 0)
    return titles[0] if titles else None


def _visible_catalyst_window_handle(process_id: int) -> int | None:
    """Return the exact visible main CATalyst HWND owned by one process."""

    if os.name != "nt":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    handles: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )

    @callback_type
    def inspect_window(handle, _context):
        owner_pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner_pid))
        if owner_pid.value != process_id:
            return True
        length = int(user32.GetWindowTextLengthW(handle) or 0)
        if length < 1:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, len(buffer))
        if buffer.value.strip().casefold() == "catalyst":
            handles.append(int(handle))
            return False
        return True

    user32.EnumWindows(inspect_window, 0)
    return handles[0] if handles else None


def _minimize_catalyst_window(process_id: int) -> int:
    """Minimize the owner window so duplicate-launch handoff is observable."""

    handle = _visible_catalyst_window_handle(process_id)
    if handle is None:
        raise SmokeFailure("owner desktop window was not available to minimize")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow(handle, 6)  # SW_MINIMIZE
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if user32.IsIconic(handle):
            return handle
        time.sleep(0.05)
    raise SmokeFailure("owner desktop window did not minimize before duplicate launch")


def _window_is_restored_and_foreground(process_id: int, handle: int) -> bool:
    """Return true only when the same owner HWND is visible and foregrounded."""

    if os.name != "nt":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if not user32.IsWindow(handle) or not user32.IsWindowVisible(handle):
        return False
    owner_pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(owner_pid))
    return (
        owner_pid.value == process_id
        and not user32.IsIconic(handle)
        and int(user32.GetForegroundWindow() or 0) == int(handle)
    )


def _wait_for_first_launch(port: int, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 45
    root_url = f"http://127.0.0.1:{port}/"
    safety_url = f"http://127.0.0.1:{port}/api/safety/status"
    last_error = "server not reached"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure(
                f"desktop process exited before first-run UI was ready: {process.returncode}"
            )
        try:
            # Both URLs are constructed above from a fixed loopback HTTP origin.
            with urllib.request.urlopen(root_url, timeout=2) as response:  # nosec B310
                content_type = response.headers.get("content-type", "").lower()
                body = response.read().decode("utf-8", errors="replace")
            if "text/html" not in content_type:
                raise SmokeFailure(
                    f"first launch returned {content_type or 'unknown content type'}, not HTML"
                )
            required = ('id="startupOverlay"', "Risk Disclosure", "CATalyst")
            missing = [value for value in required if value not in body]
            if missing:
                raise SmokeFailure(
                    "first-launch HTML is missing the wallet setup UI: "
                    + ", ".join(missing)
                )
            with urllib.request.urlopen(safety_url, timeout=2) as response:  # nosec B310
                safety = json.loads(response.read().decode("utf-8"))
            status = safety.get("safety") if isinstance(safety, dict) else None
            if not isinstance(status, dict):
                raise SmokeFailure("first launch returned malformed safety status")
            if status.get("allowed") is not False:
                raise SmokeFailure(
                    "unconfigured first launch unexpectedly enabled trading"
                )
            if _visible_catalyst_window(process.pid) is None:
                last_error = "native CATalyst window not visible"
                time.sleep(0.25)
                continue
            return
        except SmokeFailure:
            raise
        except Exception as exc:
            last_error = type(exc).__name__
            time.sleep(0.25)
    raise SmokeFailure(f"first-run desktop UI did not become ready: {last_error}")


def _wait_for_duplicate_launch_handoff(
    process: subprocess.Popen, owner_process_id: int, owner_window_handle: int
) -> None:
    """Require a duplicate launcher to restore the owner and exit promptly."""

    try:
        return_code = process.wait(timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure(
            "duplicate desktop launch did not hand off to the existing window"
        ) from exc
    if return_code != 0:
        raise SmokeFailure(f"duplicate desktop launch exited with code {return_code}")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _window_is_restored_and_foreground(owner_process_id, owner_window_handle):
            return
        time.sleep(0.1)
    raise SmokeFailure(
        "duplicate launcher exited but the owner window was not restored and foregrounded"
    )


def _nearby_diagnostics_ports(preferred: int) -> tuple[int, ...]:
    candidates = []
    for distance in range(1, 9):
        for candidate in (preferred + distance, preferred - distance):
            if 1 <= candidate <= 65535 and candidate not in candidates:
                candidates.append(candidate)
    return tuple(candidates)


def _wait_for_safety_fallback(port: int, process: subprocess.Popen) -> None:
    """Require a branded native window for a fail-closed startup denial."""

    deadline = time.monotonic() + 45
    last_error = "diagnostics server not reached"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure(
                "desktop process exited before native safety diagnostics were ready: "
                f"{process.returncode}"
            )
        title = _visible_catalyst_window(process.pid)
        for candidate in _nearby_diagnostics_ports(port):
            try:
                root_url = f"http://127.0.0.1:{candidate}/"
                with urllib.request.urlopen(root_url, timeout=1) as response:  # nosec B310
                    content_type = response.headers.get("content-type", "").lower()
                    body = response.read().decode("utf-8", errors="replace")
                if "text/html" not in content_type or (
                    "CATalyst could not start normally" not in body
                ):
                    continue
                safety_url = root_url + "api/safety/status"
                with urllib.request.urlopen(safety_url, timeout=1) as response:  # nosec B310
                    payload = json.loads(response.read().decode("utf-8"))
                status = payload.get("safety") if isinstance(payload, dict) else None
                if not isinstance(status, dict) or status.get("allowed") is not False:
                    raise SmokeFailure(
                        "startup safety fallback did not remain fail-closed"
                    )
                if title != "CATalyst Startup Safety":
                    last_error = "native startup safety window not visible"
                    continue
                return
            except SmokeFailure:
                raise
            except Exception as exc:
                last_error = type(exc).__name__
        time.sleep(0.2)
    raise SmokeFailure(
        f"native startup safety fallback did not become ready: {last_error}"
    )


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _launch(
    executable: Path,
    environment: dict[str, str],
    log_file,
) -> subprocess.Popen:
    return subprocess.Popen(
        [str(executable)],
        cwd=executable.parent,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    args = parser.parse_args()
    executable = args.exe.resolve()
    if not executable.is_file():
        raise SmokeFailure(f"packaged executable not found: {executable}")

    with tempfile.TemporaryDirectory(prefix="catalyst-first-launch-") as raw_temp:
        temp_dir = Path(raw_temp)
        data_dir = temp_dir / "clean-user-data"
        port = _free_port()
        log_path = temp_dir / "desktop-first-launch.log"
        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            environment = _clean_first_launch_env(data_dir, port)
            process = _launch(executable, environment, log_file)
            try:
                _wait_for_first_launch(port, process)
                owner_window_handle = _minimize_catalyst_window(process.pid)
                duplicate = _launch(executable, environment, log_file)
                try:
                    _wait_for_duplicate_launch_handoff(
                        duplicate, process.pid, owner_window_handle
                    )
                finally:
                    _stop_process(duplicate)
                if process.poll() is not None:
                    raise SmokeFailure(
                        "owner desktop exited during duplicate-launch handoff"
                    )
                if _visible_catalyst_window(process.pid) is None:
                    raise SmokeFailure(
                        "owner desktop window disappeared during duplicate-launch handoff"
                    )
            except Exception:
                log_file.flush()
                details = log_path.read_text(encoding="utf-8", errors="replace")
                raise SmokeFailure(
                    "packaged clean-desktop first launch failed\n" + details[-12000:]
                )
            finally:
                _stop_process(process)

            persisted = _launch(executable, environment, log_file)
            try:
                _wait_for_first_launch(port, persisted)
            except Exception:
                log_file.flush()
                details = log_path.read_text(encoding="utf-8", errors="replace")
                raise SmokeFailure(
                    "packaged persisted-profile desktop relaunch failed\n"
                    + details[-12000:]
                )
            finally:
                _stop_process(persisted)

            blocked_data_dir = temp_dir / "malformed-identity-user-data"
            blocked_data_dir.mkdir()
            (blocked_data_dir / ".env").write_text(
                "WALLET_TYPE=sage\n"
                "SAGE_FINGERPRINT=malformed-test-identity\n"
                "WALLET_EXPECTED_NAME=Synthetic Invalid Identity\n"
                "WALLET_EXPECTED_KEY_KIND=bls\n"
                "CATALYST_NETWORK_ID=mainnet\n",
                encoding="utf-8",
            )
            blocked_port = _free_port()
            blocked_environment = _clean_first_launch_env(
                blocked_data_dir, blocked_port
            )
            blocked = _launch(executable, blocked_environment, log_file)
            try:
                _wait_for_safety_fallback(blocked_port, blocked)
            except Exception:
                log_file.flush()
                details = log_path.read_text(encoding="utf-8", errors="replace")
                raise SmokeFailure(
                    "packaged native safety fallback failed\n" + details[-12000:]
                )
            finally:
                _stop_process(blocked)
    print("Packaged clean, duplicate, persisted, and native safety launches passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
