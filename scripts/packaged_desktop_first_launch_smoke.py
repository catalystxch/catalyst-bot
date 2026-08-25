#!/usr/bin/env python3
"""Verify a packaged Windows executable opens the clean first-run desktop UI."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


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
            return
        except SmokeFailure:
            raise
        except Exception as exc:
            last_error = type(exc).__name__
            time.sleep(0.25)
    raise SmokeFailure(f"first-run desktop UI did not become ready: {last_error}")


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


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
            process = subprocess.Popen(
                [str(executable)],
                cwd=executable.parent,
                env=_clean_first_launch_env(data_dir, port),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_for_first_launch(port, process)
            except Exception:
                log_file.flush()
                details = log_path.read_text(encoding="utf-8", errors="replace")
                raise SmokeFailure(
                    "packaged clean-desktop first launch failed\n" + details[-12000:]
                )
            finally:
                _stop_process(process)
    print("Packaged clean-desktop first launch passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
