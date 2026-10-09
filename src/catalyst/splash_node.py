"""Auto-launch and monitor the Splash P2P binary as a managed subprocess

Owns the lifecycle of the Splash P2P node that broadcasts and receives
offers across the Chia ecosystem. Discovers the executable, refuses
unowned listeners on the target port, starts Splash with the correct
CLI flags, captures stdout for status, and restarts on crash up to a
configured maximum.

Key responsibilities:
    - Locate splash.exe (configured path, user data dir, bundled path, or PATH)
    - Require a free loopback submission port (default 4000)
    - Launch as a hidden subprocess and pipe stdout into logs
    - Health/status reporting and crash-restart up to a max count

Configured via SPLASH_* env vars. Pairs with splash_manager (outbound
posting) and splash_receive (inbound classification).
"""

import os
import re
import sys
import time
import signal
import socket
import threading
import subprocess
import requests
from urllib.parse import urlsplit
from typing import Dict, Optional

from config import cfg
from database import log_event
from user_paths import data_dir
from win_subprocess import hidden_subprocess_kwargs


# Default binary names by platform
_BINARY_NAME = "splash.exe" if sys.platform == "win32" else "splash"


class SplashNode:
    """Manages the Splash P2P binary as a subprocess.

    The bot auto-starts Splash when outbound or receive is enabled and a binary
    is found. If the binary isn't found, it logs a helpful message
    and the bot continues without P2P (still posts to Dexie normally).
    """

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._process_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._restart_count: int = 0
        self._max_restarts: int = 5
        self._restart_cooldown: float = 10.0  # seconds between restarts
        self._last_start_time: float = 0
        self._binary_path: Optional[str] = None
        self._pid: Optional[int] = None

        # Output capture
        self._last_output_lines: list = []
        self._max_output_lines: int = 50
        self._last_hook_failure_fragment_time: float = 0.0
        self._last_webhook_delivery_time: float = 0.0

        # Metrics: cached from Splash's Prometheus-ish JSON endpoint
        # populated by --listen-metrics. See _poll_metrics for the poller.
        # Fields as returned by splash v0.2.0:
        #   peers              — current peer count
        #   offers_broadcasted — cumulative offers sent (outbound)
        #   offers_received    — cumulative offers received from peers
        #   total_connections  — lifetime peer connections
        # Plus our own:
        #   last_polled_at, last_error, metrics_url
        self._metrics_bind: Optional[str] = None  # set at launch
        self._metrics: dict = {}
        self._metrics_lock = threading.Lock()
        self._metrics_thread: Optional[threading.Thread] = None
        self._metrics_poll_secs: float = 5.0

    # -------------------------------------------------------------------
    # Binary discovery
    # -------------------------------------------------------------------

    def note_webhook_delivery(self) -> None:
        """Record that Splash successfully reached CATalyst's offer webhook."""
        self._last_webhook_delivery_time = time.time()

    def find_binary(self) -> Optional[str]:
        """Find the Splash binary. Search order:
        1. SPLASH_BINARY_PATH from .env (explicit config)
        2. Per-user CATalyst data dir
        3. Same directory as this script or packaged bundle
        4. System PATH
        """
        # 1. Explicit config
        configured = getattr(cfg, "SPLASH_BINARY_PATH", "")
        if configured and os.path.isfile(configured):
            self._binary_path = configured
            return configured

        # 2. Per-user data dir (where splash_setup downloads runtime binaries)
        data_path = os.path.join(data_dir(), "splash", _BINARY_NAME)
        if os.path.isfile(data_path):
            self._binary_path = data_path
            return data_path

        # 3. Same directory as this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_path = os.path.join(script_dir, _BINARY_NAME)
        if os.path.isfile(local_path):
            self._binary_path = local_path
            return local_path

        # Also check a "splash" subdirectory
        subdir_path = os.path.join(script_dir, "splash", _BINARY_NAME)
        if os.path.isfile(subdir_path):
            self._binary_path = subdir_path
            return subdir_path

        # 4. System PATH
        import shutil

        found = shutil.which(_BINARY_NAME)
        if found:
            self._binary_path = found
            return found

        return None

    # -------------------------------------------------------------------
    # Start / Stop
    # -------------------------------------------------------------------

    def start(self) -> bool:
        """Launch the Splash binary in a background thread.

        Returns True if started, False if binary not found or already running.
        """
        splash_enabled = getattr(cfg, "SPLASH_ENABLED", False) or getattr(
            cfg, "SPLASH_RECEIVE_ENABLED", False
        )
        if getattr(cfg, "DEXIE_ONLY_BETA", False) or not splash_enabled:
            reason = (
                "Splash node startup blocked: release is Dexie-only"
                if getattr(cfg, "DEXIE_ONLY_BETA", False)
                else "Splash node startup skipped: Splash is disabled in Settings"
            )
            log_event(
                "info",
                "splash_node_disabled",
                reason,
            )
            return False

        if self._running or self.is_running():
            log_event("info", "splash_node", "Splash node already running")
            return False

        binary = self.find_binary()
        if not binary:
            # Try auto-downloading if enabled
            log_event(
                "info",
                "splash_node_not_found",
                "Splash binary not found — attempting auto-download...",
            )
            try:
                from splash_setup import download_splash

                result = download_splash()
                if result.get("success"):
                    binary = self.find_binary()
                    log_event(
                        "info",
                        "splash_node_auto_download",
                        f"Auto-downloaded Splash: {result.get('message', '')}",
                    )
                else:
                    log_event(
                        "warning",
                        "splash_node_download_failed",
                        f"Auto-download failed: {result.get('message', '')}. "
                        f"Use the 'Install Splash Node' button in the GUI, or "
                        f"download manually from "
                        f"https://github.com/dexie-space/splash/releases",
                    )
            except Exception as e:
                log_event(
                    "warning", "splash_node_download_error", f"Auto-download error: {e}"
                )

        if not binary:
            log_event(
                "warning",
                "splash_node_not_found",
                f"Splash binary not found! Use the 'Install Splash Node' "
                f"button in the Market Intelligence tab, or download "
                f"'{_BINARY_NAME}' from "
                f"https://github.com/dexie-space/splash/releases "
                f"and place it in the V3 folder.",
            )
            return False

        try:
            submit_port = self._managed_submit_port()
            self._require_free_submit_port(submit_port)
        except ValueError as exc:
            log_event("warning", "splash_node_invalid_submit_url", str(exc))
            return False
        except RuntimeError:
            return False

        self._stop_event.clear()
        self._running = True
        self._restart_count = 0

        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="splash-node"
        )
        self._thread.start()

        log_event(
            "info",
            "splash_node_started",
            f"Splash node manager started (binary: {binary})",
        )
        return True

    def stop(self) -> bool:
        """Stop the managed node; report whether its child has exited."""
        self._running = False
        self._stop_event.set()

        # A manager thread may be inside Popen when stop arrives. Wait for
        # that launch to finish so a child cannot appear after we report stop.
        with self._process_lock:
            if self._process:
                process = self._process
                try:
                    if sys.platform == "win32":
                        process.terminate()
                    else:
                        process.send_signal(signal.SIGTERM)

                    # Wait up to 5 seconds for clean exit
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception as e:
                        log_event(
                            "warning",
                            "splash_node_stop_error",
                            f"Error killing Splash: {e}",
                        )
                        return False
                except Exception as e:
                    log_event(
                        "warning",
                        "splash_node_stop_error",
                        f"Error stopping Splash: {e}",
                    )
                    return False
                if process.poll() is None:
                    log_event(
                        "warning",
                        "splash_node_stop_error",
                        "Splash child is still running",
                    )
                    return False
                self._process = None
                self._pid = None

        manager = self._thread
        if manager and manager is not threading.current_thread() and manager.is_alive():
            manager.join(timeout=5)
            if manager.is_alive():
                log_event(
                    "warning",
                    "splash_node_stop_error",
                    "Splash manager did not exit after stop",
                )
                return False

        log_event("info", "splash_node_stopped", "Splash node stopped")
        return True

    # -------------------------------------------------------------------
    # Run loop (background thread)
    # -------------------------------------------------------------------

    def _run_loop(self):
        """Background thread that launches and monitors the Splash process."""
        while self._running:
            if self._restart_count >= self._max_restarts:
                log_event(
                    "error",
                    "splash_node_max_restarts",
                    f"Splash node crashed {self._max_restarts} times — "
                    f"giving up. Check the binary and try restarting the bot.",
                )
                self._running = False
                break

            # Cooldown between restarts
            if self._restart_count > 0:
                self._stop_event.wait(self._restart_cooldown)
                if not self._running:
                    break

            try:
                with self._process_lock:
                    if not self._running:
                        break
                    self._launch_process()
                    process = self._process
            except Exception as e:
                log_event(
                    "error", "splash_node_launch_error", f"Failed to launch Splash: {e}"
                )
                self._restart_count += 1
                continue

            # Wait for process to exit
            if process:
                returncode = process.wait()

                if self._running:
                    # Unexpected exit — will restart
                    self._restart_count += 1
                    log_event(
                        "warning",
                        "splash_node_crashed",
                        f"Splash exited with code {returncode} "
                        f"(restart {self._restart_count}/{self._max_restarts})",
                    )
                else:
                    # Clean shutdown
                    log_event(
                        "info",
                        "splash_node_exited",
                        f"Splash exited cleanly (code {returncode})",
                    )

    def _is_port_in_use(self, port: int) -> bool:
        """Check if a TCP port is already bound."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(("127.0.0.1", port))
                return result == 0  # 0 means connection succeeded = port in use
        except Exception:
            return False

    @staticmethod
    def _managed_submit_port() -> int:
        """Accept only an explicit loopback HTTP endpoint for the managed node."""
        submit_url = getattr(cfg, "SPLASH_SUBMIT_URL", "http://localhost:4000")
        parsed = urlsplit(str(submit_url))
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError(
                "Managed Splash submission URL needs a valid loopback port"
            ) from exc
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Managed Splash submission URL must be loopback HTTP with an explicit port"
            )
        return port

    def _require_free_submit_port(self, port: int) -> None:
        """Refuse to replace a listener whose ownership cannot be proven."""
        if self._is_port_in_use(port):
            message = f"Splash submission port {port} is already in use"
            log_event("warning", "splash_node_port_in_use", message)
            raise RuntimeError(message)

    def _launch_process(self):
        """Launch the Splash binary with the correct flags."""
        binary = self._binary_path
        if not binary:
            raise FileNotFoundError("Splash binary path not set")

        # Another listener may be an operator-managed Splash node. Never
        # terminate a process based only on its name and listening port.
        submit_port = self._managed_submit_port()
        self._require_free_submit_port(submit_port)

        # Build command line
        submit_bind = f"127.0.0.1:{submit_port}"

        # P2P listen port (optional)
        p2p_port = getattr(cfg, "SPLASH_P2P_PORT", 11511)

        # Prometheus metrics port (loopback only). Splash v0.2.0+ exposes
        # peer count, offers seen, gossip rate, and bandwidth counters via
        # --listen-metrics. Without these numbers the operator has no way
        # to tell whether a silent "0 received" counter means the daemon
        # is starved of peers or its offer-hook is broken. We wire them
        # into the Market Intel panel via the stats endpoint below.
        metrics_port = int(getattr(cfg, "SPLASH_METRICS_PORT", 4001) or 4001)
        self._metrics_bind = f"127.0.0.1:{metrics_port}"

        cmd = [
            binary,
            "--listen-offer-submission",
            submit_bind,
            "--listen-address",
            f"/ip4/0.0.0.0/tcp/{p2p_port}",
            "--listen-metrics",
            self._metrics_bind,
        ]

        # Only add --offer-hook if SPLASH_RECEIVE_ENABLED is True.
        # Without this check, Splash forwards every P2P offer to the bot
        # and the bot rejects them all with 403 — flooding the terminal.
        display_hook = None
        if getattr(cfg, "SPLASH_RECEIVE_ENABLED", False):
            # Startup writes the reserved Flask port here before services start.
            # Config has no PORT attribute, so that lookup silently used 5000
            # even when Flask had bound a different port.
            try:
                bot_port = int(os.environ.get("CATALYST_FLASK_PORT", "5000"))
            except (TypeError, ValueError):
                bot_port = 5000
            if not 1 <= bot_port <= 65535:
                bot_port = 5000
            offer_hook = f"http://127.0.0.1:{bot_port}/api/splash/incoming"
            # No token in URL — the splash/incoming endpoint is token-exempt
            # (loopback-only). Use IPv4 explicitly because Flask is bound to
            # 127.0.0.1; on Windows, localhost may resolve to ::1 first.
            display_hook = offer_hook
            cmd.extend(["--offer-hook", offer_hook])
            log_event(
                "info",
                "splash_node_webhook",
                f"Offer webhook enabled -> {display_hook}",
            )
        else:
            log_event(
                "info",
                "splash_node_no_webhook",
                "Offer webhook disabled (SPLASH_RECEIVE_ENABLED=false) — "
                "outbound posting only",
            )

        # Add testnet flag if configured
        if getattr(cfg, "SPLASH_TESTNET", False):
            cmd.append("--testnet")

        launch_cmd = " ".join(
            display_hook
            if (
                display_hook
                and part.startswith("http://127.0.0.1:")
                and "/api/splash/incoming" in part
            )
            else part
            for part in cmd
        )
        log_event("info", "splash_node_launching", f"Launching: {launch_cmd}")

        # Launch with output capture
        # On Windows, use DETACHED_PROCESS instead of CREATE_NO_WINDOW.
        # CREATE_NO_WINDOW prevents the Splash HTTP listener from binding
        # to its port (confirmed by testing — port 4000 refuses connections).
        # DETACHED_PROCESS still hides the console window but allows
        # full networking (HTTP + P2P).
        kwargs = hidden_subprocess_kwargs(detached=True)

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # Line buffered
            **kwargs,
        )

        self._pid = self._process.pid
        self._last_start_time = time.time()

        log_event(
            "info", "splash_node_running", f"Splash node running (PID: {self._pid})"
        )

        # Start metrics poller thread. Pulls the JSON `/metrics` endpoint
        # every few seconds so the GUI + bot_health can reason about peer
        # count and offer throughput without re-hitting splash on every
        # dashboard request. Runs as a daemon — exits with the process.
        if self._metrics_thread is None or not self._metrics_thread.is_alive():
            self._metrics_thread = threading.Thread(
                target=self._poll_metrics,
                daemon=True,
                name="splash-metrics",
            )
            self._metrics_thread.start()

        # Start output reader thread
        reader = threading.Thread(
            target=self._read_output, daemon=True, name="splash-output"
        )
        reader.start()

    def _read_output(self):
        """Read stdout from the Splash process and capture last N lines."""
        if not self._process or not self._process.stdout:
            return

        try:
            for line in self._process.stdout:
                line = line.rstrip()
                if line:
                    # Splash can write peer and hook messages concurrently on
                    # Windows, producing one interleaved line such as
                    # ``tcp connect errorReceived Offer: offer1...``.  Never
                    # retain or surface the complete offer payload in status or
                    # activity logs, even when the daemon loses the usual hook
                    # prefix during that interleaving.
                    line = re.sub(
                        r"offer1[0-9a-z]+",
                        "offer1[redacted]",
                        line,
                        flags=re.IGNORECASE,
                    )
                    self._last_output_lines.append(line)
                    # Trim to max
                    if len(self._last_output_lines) > self._max_output_lines:
                        self._last_output_lines = self._last_output_lines[
                            -self._max_output_lines :
                        ]

                    # Log interesting lines
                    lower = line.lower()
                    # F62 (2026-04-09): suppress noisy startup burst.
                    # When the bot rebroadcasts its existing offers on start,
                    # Splash hasn't finished building its peer list yet and
                    # returns "InsufficientPeers" for every single offer.
                    # That produces 70+ warnings in the first second. Treat
                    # them as debug during the first 30 s after the process
                    # started, and only escalate to warning if they keep
                    # coming after Splash has had time to bootstrap.
                    _since_start = time.time() - float(self._last_start_time or 0)
                    _is_startup_burst = (
                        _since_start < 30
                        and "insufficientpeers" in lower.replace(" ", "")
                    )
                    _has_hook_marker = (
                        "offer hook" in lower or "/api/splash/incoming" in lower
                    )
                    _has_received_offer = "received offer:" in lower
                    _is_connection_refused = (
                        "connection refused" in lower
                        or "actively refused" in lower
                        or "os error 10061" in lower
                    )
                    _is_interleaved_offer_failure = _has_received_offer and (
                        _is_connection_refused
                        or "tcp connect error" in lower
                        or "error trying to connect" in lower
                        # Windows can split ``(os error 10061)`` across
                        # concurrent Rust writes, leaving only ``(os error``
                        # immediately before the received-offer marker.
                        or "os error" in lower
                    )
                    _is_hook_refused = _is_connection_refused and (
                        _has_hook_marker or _has_received_offer
                    )
                    _is_hook_failure = _is_interleaved_offer_failure or (
                        _has_hook_marker
                        and (
                            _is_hook_refused
                            or "429" in lower
                            or "too many requests" in lower
                            or "rate_limited" in lower
                            or "backlog_full" in lower
                            or "failed" in lower
                            or "error" in lower
                        )
                    )
                    now = time.time()
                    _is_hook_failure_fragment = (
                        now - self._last_hook_failure_fragment_time <= 2.0
                        and (
                            _is_connection_refused
                            or "tcp connect error" in lower
                            or "error trying to connect" in lower
                            or "error sending request" in lower
                        )
                    )
                    if "duplicate" in lower:
                        log_event("debug", "splash_node_output", f"Splash: {line}")
                    elif _is_hook_failure:
                        # Splash writes concurrent Rust errors to Windows stdout
                        # in fragments.  Keep a very short context window so the
                        # continuation lines cannot bypass the 60-second hook
                        # warning throttle below.
                        self._last_hook_failure_fragment_time = now
                        last_logged = float(
                            getattr(self, "_last_hook_failure_log_time", 0.0) or 0.0
                        )
                        if now - last_logged >= 60.0:
                            self._last_hook_failure_log_time = now
                            delivery_is_live = (
                                now - float(self._last_webhook_delivery_time or 0.0)
                                <= 30.0
                            )
                            severity = (
                                "debug"
                                if _since_start < 30
                                else "info"
                                if delivery_is_live
                                else "warning"
                            )
                            if _is_hook_refused and _since_start < 30:
                                prefix = "Splash webhook waiting for Flask"
                            elif (
                                "429" in lower
                                or "too many requests" in lower
                                or "rate_limited" in lower
                                or "backlog_full" in lower
                                or now - float(self._last_webhook_delivery_time or 0.0)
                                <= 30.0
                            ):
                                prefix = "Splash webhook backpressure active"
                            else:
                                prefix = "Splash webhook delivery failing"
                            log_event(
                                severity,
                                "splash_node_output",
                                (
                                    f"{prefix}; inbound delivery remains live; "
                                    "suppressing repeated hook errors for 60s"
                                    if now
                                    - float(self._last_webhook_delivery_time or 0.0)
                                    <= 30.0
                                    else f"{prefix}; suppressing repeated hook errors for 60s"
                                ),
                            )
                    elif _is_hook_failure_fragment:
                        self._last_hook_failure_fragment_time = now
                    elif _is_startup_burst:
                        log_event(
                            "debug", "splash_node_output", f"Splash (startup): {line}"
                        )
                    elif "error" in lower or "failed" in lower:
                        log_event("warning", "splash_node_output", f"Splash: {line}")
                    elif (
                        "listening" in lower or "connected" in lower or "peer" in lower
                    ):
                        log_event("debug", "splash_node_output", f"Splash: {line}")
        except Exception:
            pass  # Process ended

    # -------------------------------------------------------------------
    # Health / Status
    # -------------------------------------------------------------------

    def is_running(self) -> bool:
        """Check if the Splash process is alive."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def check_health(self) -> Dict:
        """Check Splash node health by pinging the submission endpoint."""
        submit_url = getattr(cfg, "SPLASH_SUBMIT_URL", "http://localhost:4000")

        # If the user never clicked "Start Splash Node", _binary_path is
        # still None because find_binary() only runs inside start(). Run
        # a lazy lookup here so the health check reflects the real state
        # of the filesystem rather than a stale "No binary" label when
        # splash.exe is sitting right next to the app. Cheap — it's an
        # os.path.isfile on a couple of known paths.
        if self._binary_path is None:
            try:
                self.find_binary()
            except Exception:
                pass

        process_running = self.is_running()
        result = {
            "binary_found": self._binary_path is not None,
            "binary_path": self._binary_path,
            "process_running": process_running,
            "pid": self._pid,
            "restart_count": self._restart_count,
            "uptime_seconds": 0,
            "api_reachable": False,
        }

        if self._last_start_time > 0 and process_running:
            result["uptime_seconds"] = round(time.time() - self._last_start_time)

        # A disabled, stopped Splash node cannot contribute to this bot run.
        # Avoid blocking every dashboard state snapshot on an unnecessary
        # network timeout.  Still probe when Splash is enabled or when a
        # manually-started managed process is actually running.
        splash_enabled = getattr(cfg, "SPLASH_ENABLED", False) or getattr(
            cfg, "SPLASH_RECEIVE_ENABLED", False
        )
        if not splash_enabled and not process_running:
            return result

        # A configured but stopped local node may be unreachable. A full HTTP
        # connect timeout can take several seconds on Windows and get_status()
        # is called by every /api/status poll. Probe the loopback port briefly
        # before making the HTTP request; still detect a node started outside
        # this manager when the listener is present.
        if not process_running:
            try:
                parsed = urlsplit(submit_url)
                if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
                    port = parsed.port or (443 if parsed.scheme == "https" else 80)
                    probe = socket.create_connection(
                        (parsed.hostname, port), timeout=0.25
                    )
                    probe.close()
            except (OSError, ValueError):
                return result

        # Quick connectivity check
        try:
            r = requests.get(submit_url, timeout=2)
            # Splash returns 405 for GET (it only accepts POST)
            # but that means the API is reachable
            result["api_reachable"] = r.status_code in (200, 405, 404)
        except Exception:
            result["api_reachable"] = False

        return result

    def get_status(self) -> Dict:
        """Full status for the GUI."""
        health = self.check_health()
        health["last_output"] = (
            self._last_output_lines[-10:] if self._last_output_lines else []
        )
        health["manager_running"] = self._running
        metrics = self.get_metrics()
        # Counters are intentionally retained as last-known evidence after a
        # stop, but they must not advertise a dead daemon as currently
        # reachable.  The GUI uses this flag to distinguish live peer data
        # from cached cumulative totals.
        if not health["process_running"]:
            metrics["reachable"] = False
        health["metrics"] = metrics
        return health

    def get_metrics(self) -> Dict:
        """Snapshot of the latest Splash internal metrics.

        Source: the daemon's `--listen-metrics` HTTP endpoint, polled every
        few seconds by the poller thread. Gives the GUI and bot_health a
        real window into daemon health: peer count, offers_received/broadcasted,
        and total_connections. Without this the only visible signal is
        our DB row count, which is silent when splash has peers but the
        offer-hook isn't firing.
        """
        with self._metrics_lock:
            return dict(self._metrics)

    def _poll_metrics(self) -> None:
        """Poll splash.exe's `/metrics` endpoint into `_metrics` forever.

        Exits when the managed process is no longer running. Short-circuits
        to a zeroed snapshot if the endpoint isn't reachable yet (splash
        needs a couple of seconds after Popen before binding the port).
        """
        import urllib.request
        import json as _json

        if not self._metrics_bind:
            return
        url = f"http://{self._metrics_bind}/metrics"

        while True:
            if not self.is_running():
                # Process is gone — stop polling. A fresh start spawns a
                # new poller via _launch_process().
                return

            snapshot: dict = {
                "peers": 0,
                "offers_broadcasted": 0,
                "offers_received": 0,
                "total_connections": 0,
                "last_polled_at": time.time(),
                "last_error": None,
                "metrics_url": url,
                "reachable": False,
            }
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                parsed = _json.loads(raw)
                if isinstance(parsed, dict):
                    snapshot["peers"] = int(parsed.get("peers", 0) or 0)
                    snapshot["offers_broadcasted"] = int(
                        parsed.get("offers_broadcasted", 0) or 0
                    )
                    snapshot["offers_received"] = int(
                        parsed.get("offers_received", 0) or 0
                    )
                    snapshot["total_connections"] = int(
                        parsed.get("total_connections", 0) or 0
                    )
                    snapshot["reachable"] = True
            except Exception as e:
                snapshot["last_error"] = str(e)[:120]

            with self._metrics_lock:
                # Preserve previously-observed cumulative highs in case the
                # endpoint hiccuped and returned zeros on a single poll.
                prev = self._metrics
                for k in ("offers_broadcasted", "offers_received", "total_connections"):
                    if not snapshot["reachable"]:
                        snapshot[k] = int(prev.get(k, 0) or 0)
                self._metrics = snapshot

            # Sleep between polls. No tight loop on error — the same
            # interval applies so a dead endpoint doesn't hot-loop.
            time.sleep(max(1.0, float(self._metrics_poll_secs)))

    def get_recent_output(self, lines: int = 20) -> list:
        """Get recent output lines from Splash for debugging."""
        return self._last_output_lines[-lines:]
