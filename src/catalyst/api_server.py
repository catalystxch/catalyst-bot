"""Flask HTTP + SSE server backing the dashboard and the in-process bridge

Thin translation layer between HTTP and the trading modules. Routes delegate
straight into `bot_loop`, `offer_manager`, `coin_manager`, `wallet`, and the
other domain modules; this file owns request validation, response shaping, and
the real-time event stream. Consumed both by `bot_gui.html` over `fetch` and
by `app_bridge.py` via `test_request_context()`.

Key responsibilities:
    - Expose REST routes for bot control, config, offers, fills, coins,
      wallet/Sage lifecycle, Splash, Dexie, Spacescan, and diagnostics
    - Stream live updates to the GUI over Server-Sent Events at `/api/events`
    - Gate state-changing routes behind a loopback-origin check plus a
      per-run `X-Bot-Local-Token`
    - Install superlog hooks at startup and bind strictly to `127.0.0.1:5000`

The server is never exposed beyond loopback. Any change that relaxes the
origin or token checks must preserve that invariant.
"""

import os
import sys
import io
import json
import time
import signal
import queue
import logging
import threading
import secrets
import webbrowser
import hashlib

# When run as the entry point (`python api_server.py`), Python loads this file
# as the `__main__` module — `sys.modules` has no `api_server` key. Any
# blueprint that does `import api_server` later in this file would then trigger
# a second load of this file under the `api_server` name, re-running every
# side effect and crashing mid-blueprint-import with a circular-import error.
# Aliasing `sys.modules['api_server']` to the running `__main__` module makes
# subsequent `import api_server` calls return the already-initialized object.
if __name__ == "__main__":
    sys.modules.setdefault("api_server", sys.modules[__name__])

    import atexit as _early_atexit
    import read_only_diagnostics as _early_diagnostics

    _early_startup_arbiter = _early_diagnostics.acquire_startup_arbiter()
    _early_atexit.register(_early_startup_arbiter.release)
    _early_diagnostics_only = not _early_startup_arbiter.acquired
    if not _early_diagnostics_only:
        _early_diagnostics_only = _early_diagnostics.preflight_requires_diagnostics()
    if _early_diagnostics_only:
        _early_startup_arbiter.release()
        try:
            _early_preferred_port = int(os.environ.get("CATALYST_FLASK_PORT", "5000"))
        except (TypeError, ValueError):
            _early_preferred_port = 5000
        if not 1 <= _early_preferred_port <= 65535:
            _early_preferred_port = 5000
        try:
            _early_reservation = _early_diagnostics.reserve_loopback_port(
                _early_preferred_port,
                include_preferred=False,
            )
        except Exception:
            raise SystemExit(1)
        _early_diagnostics.serve(reservation=_early_reservation)
        raise SystemExit(0)

import database
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse, quote

# ---------------------------------------------------------------------------
# Fix Windows cp1252 terminal encoding so emoji in log messages don't crash.
# ---------------------------------------------------------------------------
# Use reconfigure() instead of detach+wrap: reconfigure changes encoding
# in-place without detaching the underlying buffer.  This is critical when
# running under pytest --capture=sys: sys.stdout is a CaptureIO wrapping a
# BytesIO, and calling detach() on it would rip the BytesIO away, causing
# pytest's getvalue() to fail with "assert isinstance(self.buffer, BytesIO)".
if sys.platform == "win32":
    for _attr in ("stdout", "__stdout__", "stderr", "__stderr__"):
        _st = getattr(sys, _attr, None)
        if _st is not None and hasattr(_st, "reconfigure"):
            try:
                _st.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        elif _st is not None and hasattr(_st, "buffer"):
            # Fallback for streams that don't support reconfigure — only safe
            # to detach when the buffer is a real file (not BytesIO capture).
            try:
                if not isinstance(_st.buffer, io.BytesIO):
                    _buf = _st.detach()
                    _wrapped = io.TextIOWrapper(
                        _buf,
                        encoding="utf-8",
                        errors="replace",
                        line_buffering=True,
                    )
                    setattr(sys, _attr, _wrapped)
            except Exception:
                pass
from flask import Flask, jsonify, request, send_from_directory, send_file, Response, g

# ---- Super Log: capture EVERYTHING to terminal + file ----
from super_log import init_super_log, slog, intercept_log_event

init_super_log()
slog("STARTUP", "=== API SERVER STARTING ===")

from config import cfg
from database import (
    init_database,
    log_event,
    get_stats,
    backup_database,
    get_connection,
    get_live_tier_group_counts,
)
from tx_fees import get_fee_settings_snapshot
import mutation_gate

# ---------------------------------------------------------------------------
# Bundle-aware path resolution.
#
# In a PyInstaller onedir bundle, __file__ for non-entry-point modules
# resolves to the _internal/ subdirectory, NOT the bundle root where
# data files (HTML, images) are placed. sys._MEIPASS always points to
# the bundle root, so we use it when available.
#
# In dev mode this file lives at src/catalyst/api_server.py, so the repo
# root (where bot_gui.html sits) is two dirname() hops up from here.
# ---------------------------------------------------------------------------
_APP_ROOT = getattr(sys, "_MEIPASS", None)
if _APP_ROOT is None:
    # Dev mode: this module lives at src/catalyst/api_server.py, and
    # bot_gui.html sits at the repo root (three dirname() hops up).
    _APP_ROOT = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    # Legacy fallback: if bot_gui.html isn't at that computed root
    # (e.g. a flat install for ad-hoc testing), look alongside this
    # module instead so we don't regress the pre-src-layout behaviour.
    if not os.path.isfile(os.path.join(_APP_ROOT, "bot_gui.html")):
        _APP_ROOT = os.path.dirname(os.path.abspath(__file__))
_SPACESCAN_PUBLIC_PLANS = {
    "free": {
        "label": "Free",
        "requests_per_minute": 5,
        "requests_per_month": 1000,
    },
    "hobbyist": {
        "label": "Hobbyist",
        "requests_per_minute": 10,
        "requests_per_month": 10000,
    },
    "builder": {
        "label": "Builder",
        "requests_per_minute": 20,
        "requests_per_month": 40000,
    },
    "startup": {
        "label": "Startup",
        "requests_per_minute": 60,
        "requests_per_month": 100000,
    },
}

# Intercept log_event so ALL events appear in super_log too
intercept_log_event()

from bot_loop import BotLoop
from wallet import get_wallet_adapter_authority, get_wallet_type

# ---- Super Log: hook ALL module methods for complete visibility ----
try:
    from super_log_hooks import install_all_hooks

    install_all_hooks()
except Exception as e:
    slog("STARTUP", f"Failed to install hooks: {e}")


# ---------------------------------------------------------------------------
# Suppress noisy Flask/Werkzeug request logs for polling endpoints
# ---------------------------------------------------------------------------
# These endpoints are hit every 1-5 seconds by the GUI and flood the terminal
# with useless lines. We filter them so only "interesting" requests show up.

_QUIET_ENDPOINTS = {
    "/api/status",
    "/api/bot/state",
    "/api/health",
    "/api/coin-prep/status",
    "/api/offers/cancel_all/status",
    "/api/splash/incoming",
    "/api/events",
    "/api/sage/startup-status",
    "/api/console/status",
}

# Loopback-only machine producers may post here without the GUI token.
# Keep this list extremely small and only for routes that are not user-driven.
_TOKEN_EXEMPT_WRITE_ROUTES = {
    "/api/splash/incoming",
}

# Generic control-plane throttling is too aggressive for local webhook bursts.
# Those machine routes stay loopback-only and must implement their own validation.
_RATE_LIMIT_EXEMPT_WRITE_ROUTES = {
    "/api/splash/incoming",
    "/api/log",  # GUI flushes buffered log entries in bursts
}

# Every state-changing HTTP verb is classified explicitly. Only the first
# group may initiate wallet/signing effects; safety/diagnostic and stop/abort
# controls remain usable while another process owns the mutation lease.
_MUTATING_API_ENDPOINTS = {
    "api_update_install",
    "api_update_relaunch_intent",
    "boost.api_boost_activate",
    "boost.api_boost_deactivate",
    "bot.api_bot_start",
    "cat.api_cat_refresh",
    "cat.api_cat_select",
    "cat.api_deposit_advisory_allocate",
    "coin_prep.api_coin_prep",
    "coin_prep.api_coin_prep_reset",
    "coin_prep.api_coin_prep_trigger",
    "coin_prep.api_coin_topup",
    "coin_prep.api_db_backup",
    "coin_prep.api_log_event",
    "coin_prep.api_logs_clear",
    "config_bp.api_config_apply",
    "config_bp.api_config_live",
    "config_bp.api_config_reload",
    "config_bp.api_config_update",
    "market.api_dbx_claim",
    "market.api_debug_sage_single_offer_test",
    "market.api_dexie_repost",
    "offers.api_cancel_all",
    "offers.api_cancel_offer",
    "offers.api_cleanup_orphans",
    "offers.api_pnl_reset",
    "offers.api_purge_fills",
    "offers.api_reset_full",
    "offers.api_reset_offer_history",
    "sage.api_chia_start_with_fingerprint",
    "sage.api_sage_daemon_start",
    "sage.api_sage_set_fingerprint",
    "sage.api_sage_setup_certs",
    "sage.api_wallet_begin_startup",
    "sage.api_wallet_retry_sage_connect",
    "session.api_session_fresh_start",
    "session.api_session_resume_chosen",
    "spacescan.api_spacescan_setup",
    "splash.api_splash_incoming",
    "splash.api_splash_node_start",
    "splash.api_splash_receive",
    "splash.api_splash_setup_download",
    "superlog.api_superlog_level",
    "system.api_wallets_switch",
    "watchdog.api_watchdog_cancel_mismatched_offers",
    "watchdog.api_dismiss_alert",
}

_READ_ONLY_WRITE_API_ENDPOINTS = {
    "cat.api_balances_refresh",
    "config_bp.api_settings_validate",
}

_CONTROL_WRITE_API_ENDPOINTS = {
    "api_safety_quarantine",
    "api_safety_quarantine_resolve",
    "api_open_data_folder",
    "api_open_external",
    "bot.api_bot_stop",
    "bot.api_shutdown",
    "coin_prep.api_coin_prep_cancel",
    "system.api_console_toggle",
    "watchdog.api_watchdog_shape_fix_abort",
}

_read_only_diagnostics_active = False


def _write_endpoint_requires_mutation(endpoint: str) -> bool:
    """Default every unrecognized write endpoint to mutation-protected."""

    return endpoint not in (
        _READ_ONLY_WRITE_API_ENDPOINTS | _CONTROL_WRITE_API_ENDPOINTS
    )


# Dedicated limiter/backlog guard for /api/splash/incoming so an unbounded
# webhook flood cannot amplify into runaway DB writes.
_SPLASH_RATE_LIMIT = {"window_s": 1.0, "hits": [], "lock": threading.Lock()}
_SPLASH_BACKLOG_CACHE = {
    "checked_at": 0.0,
    "new_count": 0,
    "lock": threading.Lock(),
}
_SPLASH_INCOMING_WRITE_LOCK = threading.Lock()


def _splash_incoming_max_per_sec() -> int:
    try:
        configured = int(getattr(cfg, "SPLASH_RECEIVE_MAX_PER_SEC", 3) or 3)
    except Exception:
        configured = 3
    return max(1, configured)


def _splash_incoming_max_backlog() -> int:
    try:
        configured = int(getattr(cfg, "SPLASH_RECEIVE_MAX_BACKLOG", 250) or 0)
    except Exception:
        configured = 250
    return max(0, configured)


def _splash_incoming_rate_limited() -> bool:
    import time as _t

    now = _t.time()
    with _SPLASH_RATE_LIMIT["lock"]:
        hits = _SPLASH_RATE_LIMIT["hits"]
        cutoff = now - _SPLASH_RATE_LIMIT["window_s"]
        # Drop expired entries
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= _splash_incoming_max_per_sec():
            return True
        hits.append(now)
        return False


def _splash_incoming_backlog_full() -> bool:
    import time as _t

    limit = _splash_incoming_max_backlog()
    if limit <= 0:
        return False

    now = _t.time()
    with _SPLASH_BACKLOG_CACHE["lock"]:
        if now - float(_SPLASH_BACKLOG_CACHE["checked_at"] or 0.0) < 1.0:
            return int(_SPLASH_BACKLOG_CACHE["new_count"] or 0) >= limit

    try:
        from database import get_splash_incoming_stats

        stats = get_splash_incoming_stats()
        new_count = int((stats or {}).get("new") or 0)
    except Exception as e:
        slog(
            "API",
            f"Splash incoming backlog check failed; accepting offer: {e}",
            level="debug",
        )
        return False

    with _SPLASH_BACKLOG_CACHE["lock"]:
        _SPLASH_BACKLOG_CACHE["checked_at"] = now
        _SPLASH_BACKLOG_CACHE["new_count"] = new_count
    return new_count >= limit


def _splash_incoming_note_recorded(was_new: bool) -> None:
    if not was_new:
        return
    with _SPLASH_BACKLOG_CACHE["lock"]:
        if float(_SPLASH_BACKLOG_CACHE["checked_at"] or 0.0) > 0.0:
            _SPLASH_BACKLOG_CACHE["new_count"] = (
                int(_SPLASH_BACKLOG_CACHE["new_count"] or 0) + 1
            )


def _record_splash_incoming_locked(
    offer_bech32: str, fingerprint: str, source_ip: str = None
) -> bool:
    from database import record_splash_incoming

    with _SPLASH_INCOMING_WRITE_LOCK:
        return record_splash_incoming(offer_bech32, fingerprint, source_ip=source_ip)


# ---------------------------------------------------------------------------
# Simple per-endpoint rate limiter for state-changing operations
#
# Thread-safe within a single process (threading.Lock). This does NOT protect
# across multiple worker processes, but Flask runs single-process in this app
# (embedded in desktop_app.py or standalone). If ever deployed multi-worker
# (gunicorn -w N), replace with a shared store (Redis, SQLite, etc.).
# ---------------------------------------------------------------------------
_rate_limit_log: dict = {}  # {endpoint: [timestamp, ...]}
_rate_limit_lock = threading.Lock()
_RATE_LIMIT_WINDOW = 10  # seconds
_RATE_LIMIT_MAX = 20  # max requests per window


def _is_rate_limited(endpoint: str) -> bool:
    """Check if an endpoint is being called too frequently."""
    import time as _rl_time

    now = _rl_time.time()
    cutoff = now - _RATE_LIMIT_WINDOW
    with _rate_limit_lock:
        hits = _rate_limit_log.get(endpoint, [])
        hits = [t for t in hits if t > cutoff]
        hits.append(now)
        _rate_limit_log[endpoint] = hits
        return len(hits) > _RATE_LIMIT_MAX


_dbx_pair_cache = {}
_LOCAL_API_TOKEN_HEADER = "X-Bot-Local-Token"
_LOCAL_API_COOKIE = "catalyst_local_session"
_LOCAL_API_TOKEN = os.environ.get("BOT_LOCAL_WRITE_TOKEN") or secrets.token_urlsafe(32)
os.environ["BOT_LOCAL_WRITE_TOKEN"] = _LOCAL_API_TOKEN
_LOCAL_API_COOKIE_VALUE = secrets.token_urlsafe(32)

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

# Substrings that flag a config key as sensitive — these values are never
# logged or returned in API error messages.
_SENSITIVE_KEY_FRAGMENTS = {
    "key",
    "cert",
    "password",
    "secret",
    "token",
    "mnemonic",
    "seed",
    "fingerprint",
    "private",
}


def _is_sensitive_key(key: str) -> bool:
    """Return True if the config key name suggests a sensitive value."""
    k = str(key).lower()
    return any(frag in k for frag in _SENSITIVE_KEY_FRAGMENTS)


def _sanitize_config_dict(d: object) -> object:
    """Recursively redact values whose keys look sensitive.

    Used before any dict reaches a log line or API response to prevent
    accidental credential exposure.
    """
    if isinstance(d, dict):
        return {
            k: "***" if _is_sensitive_key(k) else _sanitize_config_dict(v)
            for k, v in d.items()
        }
    if isinstance(d, (list, tuple)):
        return [_sanitize_config_dict(x) for x in d]
    return d


def _decimal_safe(obj):
    """Recursively convert Decimal values to float for JSON serialization.

    Decimal arithmetic is used for price calculations to avoid float rounding,
    but JSON (and JS) only support float — convert at the serialization boundary.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_decimal_safe(x) for x in obj]
    return obj


def _api_error(e: Exception, endpoint: str = "", status: int = 500):
    """Return a safe JSON error response that does NOT expose internal details.

    The real exception is written to the local superlog so it is still visible
    in the debug bundle, while the UI-visible event log gets generic text.
    """
    endpoint_name = endpoint or "unknown"
    try:
        slog(
            "API_ERROR", f"Unhandled exception on {endpoint_name}: {e!r}", level="error"
        )
    except Exception as log_exc:
        from contextlib import suppress

        # Last-resort diagnostics only; API error handling must never raise.
        with suppress(Exception):
            import sys

            sys.stderr.write(
                f"CATalyst API error logging failed for {endpoint_name}: {log_exc!r}\n"
            )
    try:
        log_event(
            "error",
            "api_error",
            f"Unhandled exception on {endpoint_name}; see debug bundle for details.",
            {"endpoint": endpoint},
        )
    except Exception as log_exc:
        from contextlib import suppress

        with suppress(Exception):
            slog(
                "API_ERROR",
                f"Failed to record API error for {endpoint_name}: {log_exc}",
                level="warning",
            )
    return jsonify({"error": "Internal server error", "code": "SERVER_ERROR"}), status


def _api_exception(endpoint: str = "", status: int = 500):
    """Return a safe JSON response for the exception currently being handled."""
    endpoint_name = endpoint or "unknown"
    from contextlib import suppress

    with suppress(Exception):
        import traceback

        slog(
            "API_ERROR",
            f"Unhandled exception on {endpoint_name}:\n{traceback.format_exc()}",
            level="error",
        )
    try:
        log_event(
            "error",
            "api_error",
            f"Unhandled exception on {endpoint_name}; see debug bundle for details.",
            {"endpoint": endpoint},
        )
    except Exception as log_exc:
        from contextlib import suppress

        with suppress(Exception):
            slog(
                "API_ERROR",
                f"Failed to record API exception for {endpoint_name}: {log_exc}",
                level="warning",
            )
    return jsonify({"error": "Internal server error", "code": "SERVER_ERROR"}), status


def _client_safe_result(
    payload: object, *, error_message: str = "Operation failed"
) -> object:
    """Return an API-safe copy of a helper result without exception-derived text."""
    if not isinstance(payload, dict):
        return payload

    safe = _sanitize_config_dict(dict(payload))
    failed = (
        safe.get("success") is False
        or bool(safe.get("error"))
        or str(safe.get("phase") or "").lower() == "error"
    )
    if not failed:
        return safe

    for key in ("error", "message", "detail", "details", "traceback"):
        if key in safe:
            safe[key] = error_message
    if "output" in safe:
        safe["output"] = ""
    for key in ("errors", "warnings"):
        value = safe.get(key)
        if isinstance(value, list) and value:
            safe[key] = [error_message]
        elif isinstance(value, str) and value:
            safe[key] = error_message
    return safe


_TRACEBACK_TEXT_MARKERS = (
    "traceback (most recent call last)",
    "\n  file ",
    "runtimeerror:",
    "valueerror:",
    "exception:",
)


def _looks_like_traceback_text(value: str) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in _TRACEBACK_TEXT_MARKERS)


def _client_safe_payload(
    payload: object, *, error_message: str = "Details unavailable"
) -> object:
    """Strip exception and traceback-shaped values from client JSON payloads."""
    if isinstance(payload, BaseException):
        return error_message
    if isinstance(payload, dict):
        return {
            key: "***"
            if _is_sensitive_key(str(key))
            else _client_safe_payload(value, error_message=error_message)
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [
            _client_safe_payload(value, error_message=error_message)
            for value in payload
        ]
    if isinstance(payload, str) and _looks_like_traceback_text(payload):
        return error_message
    return payload


# ---------------------------------------------------------------------------
# Startup security checks
# ---------------------------------------------------------------------------


def _check_env_file_permissions():
    """Warn if the .env file is readable by group or others.

    POSIX permission bits only have meaningful semantics on Unix-like
    platforms. On Windows, ``os.stat()`` happily returns an ``st_mode``
    value with group/other bits set (NTFS typically reports 0o666), so
    the naive mask check fires a false-positive on every startup — we
    saw it spamming the logs tab. Skip the check entirely on Windows
    where NTFS ACLs are the actual access-control layer.
    """
    if sys.platform == "win32":
        return
    import stat as _stat

    try:
        from user_paths import env_file as _env_file

        env_path = _env_file()
    except Exception:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    try:
        mode = os.stat(env_path).st_mode
        if mode & (_stat.S_IRGRP | _stat.S_IWGRP | _stat.S_IROTH | _stat.S_IWOTH):
            print(
                "[SECURITY] WARNING: .env file is readable/writable by group or others. "
                "Run: chmod 600 .env"
            )
            try:
                log_event(
                    "warning",
                    "security",
                    ".env file has insecure permissions (readable by group/others)",
                )
            except Exception:
                pass
    except OSError:
        pass


_check_env_file_permissions()
_LIVE_REQUOTE_ONLY_KEYS = {
    "SPREAD_BPS",
    "BASE_SPREAD_BPS",
    "MIN_EDGE_BPS",
    "MIN_SPREAD_BPS",
    "MAX_SPREAD_BPS",
    "VOLATILITY_WINDOW_HOURS",
    "SKEW_INTENSITY",
    "MAX_POSITION_XCH",
    "DYNAMIC_SPREAD_ENABLED",
    "INVENTORY_ENABLED",
    "COMPETITOR_AWARE_ENABLED",
    "DBX_MAX_SPREAD_BPS",
}


def get_app_version() -> str:
    """Return the packaged app version from _version.py (single source of truth)."""
    try:
        from _version import get_version

        return get_version()
    except ImportError:
        try:
            from _version import __version__

            return __version__
        except Exception:
            return "unknown"
    except Exception:
        return "unknown"


def _get_spacescan_plan_advice() -> Dict[str, object]:
    """Estimate sensible Spacescan plan guidance for this bot profile."""
    loop_seconds = max(15, int(getattr(cfg, "LOOP_SECONDS", 90) or 90))
    balance_every_loops = max(
        1, int(getattr(cfg, "SPACESCAN_BALANCE_CHECK_EVERY_N", 10) or 10)
    )

    loops_per_day = 86400 / float(loop_seconds)
    balance_checks_per_day = loops_per_day / float(balance_every_loops)

    # Paid mode performs both XCH and CAT balance checks on each scheduled pass.
    balance_calls_month = int(round(balance_checks_per_day * 2 * 30))
    token_context_calls_month = 120  # ~4 calls/day from cached token context refreshes
    baseline_paid_monthly = balance_calls_month + token_context_calls_month

    if (
        baseline_paid_monthly
        <= _SPACESCAN_PUBLIC_PLANS["hobbyist"]["requests_per_month"]
    ):
        minimum_paid_tier = "hobbyist"
    elif (
        baseline_paid_monthly
        <= _SPACESCAN_PUBLIC_PLANS["builder"]["requests_per_month"]
    ):
        minimum_paid_tier = "builder"
    else:
        minimum_paid_tier = "startup"

    if baseline_paid_monthly <= 4000:
        recommended_paid_tier = "hobbyist"
    elif baseline_paid_monthly <= 30000:
        recommended_paid_tier = "builder"
    else:
        recommended_paid_tier = "startup"

    if recommended_paid_tier == "startup":
        message = (
            f"At a {loop_seconds}s loop, this bot would use about "
            f"{baseline_paid_monthly:,} paid-plan calls/month before fills. "
            "Startup is the safer fit for this profile."
        )
    elif minimum_paid_tier == "hobbyist" and recommended_paid_tier == "builder":
        message = (
            f"At a {loop_seconds}s loop, this bot would use about "
            f"{baseline_paid_monthly:,} paid-plan calls/month before fills. "
            "Hobbyist can work, but Builder gives safer 24/7 headroom for restarts, "
            "fills, and on-chain sanity checks."
        )
    else:
        message = (
            f"At a {loop_seconds}s loop, this bot would use about "
            f"{baseline_paid_monthly:,} paid-plan calls/month before fills. "
            f"{_SPACESCAN_PUBLIC_PLANS[recommended_paid_tier]['label']} is the sensible fit."
        )

    return {
        "loop_seconds": loop_seconds,
        "balance_every_loops": balance_every_loops,
        "balance_calls_month": balance_calls_month,
        "token_context_calls_month": token_context_calls_month,
        "baseline_paid_monthly": baseline_paid_monthly,
        "fill_verify_call_cost": 1,
        "topup_cross_check_call_cost": 1,
        "minimum_paid_tier": minimum_paid_tier,
        "recommended_paid_tier": recommended_paid_tier,
        "message": message,
        "plans": _SPACESCAN_PUBLIC_PLANS,
    }


def _get_spacescan_market_context(
    asset_id: str = "",
    ticker_id: str = "",
    decimals: int = 3,
    *,
    executable_mid_price: float = 0.0,
) -> dict:
    """Return cached Spacescan-assisted token context for live UI decisions.

    This is deliberately *not* a live pricing feed. Dexie + Tibet remain the
    executable market sources. Spacescan contributes token health, activity,
    supply, and explorer-price sanity checks.
    """
    # Tier reflects whether a Spacescan API key is configured. The free tier
    # endpoint doesn't return holder/activity/risk fields, so the UI uses
    # this flag to show "Not available (Free tier)" instead of a generic
    # "Unknown" — that wording is misleading when the data is genuinely
    # unreachable rather than just not yet fetched.
    _api_key = (getattr(cfg, "SPACESCAN_API_KEY", "") or "").strip()
    context = {
        "enabled": bool(getattr(cfg, "SPACESCAN_ENABLED", True)),
        "tier": "pro" if _api_key else "free",
        "has_data": False,
        "holder_count": 0,
        "activity_count": 0,
        "activity_level": "unknown",
        "risk_level": "unknown",
        "confidence": "low",
        "price_xch": 0.0,
        "price_usd": 0.0,
        "circulating_supply": 0.0,
        "total_supply": 0.0,
        "price_gap_bps": 0.0,
        "regime_hint": "unknown",
        "message": "Spacescan token context not loaded",
        "cache_age_secs": None,
        "stale": False,
    }
    if not asset_id:
        return context

    try:
        from database import (
            get_market_analysis_cache,
            get_market_analysis_cache_age_secs,
        )

        spacescan = get_market_analysis_cache(asset_id, "spacescan") or {}
        analysis = get_market_analysis_cache(asset_id, "full_analysis") or {}
        # Advisor tips that depend on Spacescan should degrade gracefully when
        # the cache is old. 12h is well inside the 24h TTL but clearly past
        # "fresh" — beyond this threshold we tag the context stale so the
        # front-end can suppress or annotate the dependent advisories.
        _age = get_market_analysis_cache_age_secs(asset_id, "spacescan")
        if _age is not None:
            context["cache_age_secs"] = int(_age)
            context["stale"] = bool(_age > 12 * 3600)
        if not spacescan:
            # Spacescan raw data not cached at all — return empty context rather than
            # triggering a full background data collection here. Smart Defaults
            # populates this cache when explicitly run.
            return context
        # full_analysis may have expired (30min TTL) while spacescan data (24hr TTL)
        # is still valid. Use spacescan raw data directly, fall back to analysis
        # for derived fields (activity_level, risk_level) when available.
        health = (
            (analysis.get("token_health") or {}) if isinstance(analysis, dict) else {}
        )

        context["has_data"] = bool(spacescan.get("has_data"))
        context["token_preview_url"] = str(spacescan.get("token_preview_url", "") or "")
        context["holder_count"] = int(spacescan.get("holder_count", 0) or 0)
        context["activity_count"] = int(spacescan.get("activity_count", 0) or 0)
        # Surface partial-fetch flags from the cache so the GUI can render
        # "rate-limited / fetch failed" instead of "0 holders" when the
        # Spacescan free-tier sub-call (holders/activities) failed but the
        # parent /token/info succeeded. holder_count_from_prior_cache is
        # set by _merge_partial_spacescan when a previously-good value is
        # being preserved across a partial failure.
        context["activity_fetch_failed"] = bool(spacescan.get("activity_fetch_failed"))
        context["holder_count_from_prior_cache"] = bool(
            spacescan.get("holder_count_from_prior_cache")
        )
        context["activity_count_from_prior_cache"] = bool(
            spacescan.get("activity_count_from_prior_cache")
        )
        # Derive activity_level and risk_level from raw spacescan data when
        # full_analysis has expired but spacescan cache is still valid.
        if health:
            context["activity_level"] = str(
                health.get("activity_level", "unknown") or "unknown"
            )
            context["risk_level"] = str(
                health.get("risk_level", "unknown") or "unknown"
            )
            context["confidence"] = str(health.get("confidence", "low") or "low")
        else:
            # Derive from raw spacescan data inline (same logic as _analyze_token_health)
            hc = context["holder_count"]
            ac = int(spacescan.get("activity_count", 0) or 0)
            if hc >= 200:
                context["risk_level"] = "healthy"
            elif hc >= 50:
                context["risk_level"] = "moderate"
            elif hc > 0:
                context["risk_level"] = "thin"
            else:
                context["risk_level"] = "unknown"
            if ac >= 500:
                context["activity_level"] = "active"
            elif ac >= 100:
                context["activity_level"] = "moderate"
            elif ac > 0:
                context["activity_level"] = "quiet"
            elif hc >= 500:
                # Activity endpoint returned 0 but token has many holders —
                # likely a Spacescan data gap, not genuinely zero activity.
                # Infer from holder count as a proxy.
                context["activity_level"] = "active"
            elif hc >= 100:
                context["activity_level"] = "moderate"
            elif hc > 0:
                context["activity_level"] = "quiet"
            else:
                context["activity_level"] = "unknown"
            context["confidence"] = "medium" if hc > 0 else "low"
        context["price_xch"] = float(spacescan.get("price_xch", 0) or 0)
        context["price_usd"] = float(spacescan.get("price_usd", 0) or 0)
        context["circulating_supply"] = float(
            spacescan.get("circulating_supply", 0) or 0
        )
        context["total_supply"] = float(spacescan.get("total_supply", 0) or 0)

        mid = float(executable_mid_price or 0)
        explorer_px = context["price_xch"]
        if mid > 0 and explorer_px > 0:
            context["price_gap_bps"] = round(abs(explorer_px - mid) / mid * 10000, 2)

        risk = context["risk_level"].lower()
        activity = context["activity_level"].lower()
        if risk in {"risky", "thin"} and activity in {"dormant", "quiet"}:
            context["regime_hint"] = "fragile"
        elif risk == "healthy" and activity in {"active", "moderate"}:
            context["regime_hint"] = "established"
        elif activity in {"dormant", "quiet"}:
            context["regime_hint"] = "quiet"
        elif risk in {"risky", "thin"}:
            context["regime_hint"] = "thin"
        else:
            context["regime_hint"] = "balanced"

        holders = context["holder_count"]
        msg = f"{holders} holders, {activity} activity, {risk} risk"
        if context["price_gap_bps"] > 0:
            msg += f", explorer gap {context['price_gap_bps'] / 100:.1f}%"
        context["message"] = msg
    except Exception as e:
        slog("API_STATUS", f"Spacescan context unavailable: {e!r}", level="debug")
        context["message"] = "Spacescan context unavailable right now."

    return context


def _get_live_requote_notice(changed_keys):
    """Explain when a config change only affects future quotes.

    Quote-affecting risk/spread controls should never force a live migration
    from the GUI. Existing offers stay live; the new values are picked up by
    future requotes and newly-created offers.
    """
    try:
        if not bot or not bot.is_running():
            return None
    except Exception:
        return None

    keys = sorted(
        {str(k) for k in (changed_keys or []) if str(k) in _LIVE_REQUOTE_ONLY_KEYS}
    )
    if not keys:
        return None

    return {
        "keys": keys,
        "apply_mode": "next_requote",
        "warning": (
            "Saved without live offer migration — existing offers stay live and "
            "the change will take effect on future requotes and new offers."
        ),
    }


def _is_loopback_addr(addr: str) -> bool:
    addr = str(addr or "").strip().lower()
    if addr in {"localhost"}:
        return True
    try:
        import ipaddress

        # Handles 127.0.0.0/8, ::1, ::ffff:127.x.x.x and all other loopback forms
        return ipaddress.ip_address(addr).is_loopback
    except (ValueError, AttributeError):
        return False


def _has_valid_local_token() -> bool:
    supplied_header = str(request.headers.get(_LOCAL_API_TOKEN_HEADER, "") or "")
    if supplied_header and secrets.compare_digest(supplied_header, _LOCAL_API_TOKEN):
        return True

    supplied_cookie = str(request.cookies.get(_LOCAL_API_COOKIE, "") or "")
    return bool(supplied_cookie) and secrets.compare_digest(
        supplied_cookie,
        _LOCAL_API_COOKIE_VALUE,
    )


def _request_origin_matches_app() -> bool:
    """Allow browser write requests only from the app's own origin."""
    raw_origin = request.headers.get("Origin", "")
    if not raw_origin:
        return True
    try:
        parsed = urlparse(str(raw_origin).strip())
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return (
        _is_loopback_addr(parsed.hostname)
        and parsed.netloc.lower() == (request.host or "").lower()
    )


def _get_sage_signing_block_reason():
    """Return a message when the active Sage key is present but cannot sign."""
    try:
        if get_wallet_type() != "sage":
            return None
    except Exception:
        return None

    try:
        from wallet import get_wallet_identity

        identity = get_wallet_identity()
        if type(identity) is not dict or identity.get("success") is not True:
            return None
        if identity.get("has_secrets") is not True:
            fp = identity.get("fingerprint")
            msg = "Active Sage wallet is watch-only and cannot sign offers"
            if type(fp) is int and fp > 0:
                msg += f" (fingerprint {fp})"
            return msg
    except Exception:
        return None

    return None


def _serve_bootstrapped_html(filename: str):
    """Serve HTML and bind the local runtime token to an HttpOnly cookie."""
    gui_dir = _APP_ROOT
    path = os.path.join(gui_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        html_doc = f.read()

    response = Response(html_doc, mimetype="text/html")
    response.set_cookie(
        _LOCAL_API_COOKIE,
        # Per-process loopback browser session nonce. The worker/header token
        # stays out of browser storage.
        _LOCAL_API_COOKIE_VALUE,
        httponly=True,
        samesite="Strict",
        secure=False,
        path="/",
    )
    return response


class _QuietRequestFilter(logging.Filter):
    """Filter out repetitive polling requests from Werkzeug's access log."""

    def filter(self, record):
        msg = record.getMessage()
        # Werkzeug log format: '127.0.0.1 - - [date] "GET /api/status HTTP/1.1" 200 -'
        for endpoint in _QUIET_ENDPOINTS:
            if endpoint in msg:
                return False  # Suppress this log line
        return True  # Show everything else


# Apply the filter to Werkzeug's logger
logging.getLogger("werkzeug").addFilter(_QuietRequestFilter())
# Suppress the "This is a development server" startup warning.
# Flask's built-in server is intentional here (single-user desktop app),
# so the warning adds no value and clutters the console.
logging.getLogger("werkzeug").setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _bps_to_pct(val):
    """Convert a BPS value to a formatted % string."""
    try:
        n = float(val) / 100
        if n < 1:
            return f"{n:.2f}%"
        return f"{n:.1f}%"
    except (ValueError, TypeError):
        return str(val)


def _history_age_label(timestamp_value: str) -> str:
    """Convert an ISO timestamp into the short relative label used by the GUI."""
    age = "Recently"
    try:
        if timestamp_value:
            dt = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
            age_secs = max(0, (datetime.now(timezone.utc) - dt).total_seconds())
            if age_secs < 60:
                age = f"{int(age_secs)}s ago"
            elif age_secs < 3600:
                age = f"{int(age_secs / 60)}m ago"
            elif age_secs < 86400:
                age = f"{age_secs / 3600:.1f}h ago"
            else:
                age = f"{age_secs / 86400:.1f}d ago"
    except Exception:
        age = "Recently"
    return age


# _build_fill_history_for_gui moved to blueprint


def _live_wallet_reads_allowed(bot_obj=None) -> bool:
    """True only when both public bot state and thread state are running."""
    if bot_obj is None:
        return False
    state_running = False
    try:
        state = bot_obj.get_state() if hasattr(bot_obj, "get_state") else {}
        state_running = bool((state or {}).get("running", False))
    except Exception:
        state_running = False
    try:
        method_running = (
            bool(bot_obj.is_running()) if hasattr(bot_obj, "is_running") else False
        )
    except Exception:
        method_running = False
    return bool(state_running and method_running)


def _get_live_local_offer_edges(asset_id: str) -> dict:
    """Get our current best live bid/ask from wallet-open offers.

    Uses wallet-open trade IDs when possible so stale DB rows do not distort the
    Market Intel "best live" display. Falls back to DB-open rows only if wallet
    sync is unavailable.
    """
    result = {
        "our_best_bid": Decimal("0"),
        "our_best_ask": Decimal("0"),
        "our_open_buys": 0,
        "our_open_sells": 0,
        "source": "db_open_offers",
    }
    if not asset_id:
        return result

    trade_ids = None
    if _live_wallet_reads_allowed(bot) and getattr(bot, "offer_manager", None):
        try:
            wallet_open_buys, wallet_open_sells, _ = (
                bot.offer_manager.sync_from_wallet()
            )
            trade_ids = [
                o.get("trade_id", "")
                for o in (wallet_open_buys + wallet_open_sells)
                if o.get("trade_id")
            ]
            result["our_open_buys"] = len(wallet_open_buys)
            result["our_open_sells"] = len(wallet_open_sells)
            result["source"] = "wallet_sync"
        except Exception:
            trade_ids = None

    conn = get_connection()
    params = [asset_id]
    query = (
        "SELECT side, MIN(CAST(price_xch AS REAL)) AS min_price, "
        "MAX(CAST(price_xch AS REAL)) AS max_price, COUNT(*) AS cnt "
        "FROM offers WHERE status='open' AND cat_asset_id=?"
    )
    if trade_ids is not None:
        if not trade_ids:
            return result
        placeholders = ",".join("?" for _ in trade_ids)
        query += f" AND trade_id IN ({placeholders})"
        params.extend(trade_ids)
    query += " GROUP BY side"

    rows = conn.execute(query, params).fetchall()
    for row in rows:
        side = row["side"]
        if side == "buy":
            result["our_best_bid"] = Decimal(str(row["max_price"] or 0))
            if trade_ids is None:
                result["our_open_buys"] = int(row["cnt"] or 0)
        elif side == "sell":
            result["our_best_ask"] = Decimal(str(row["min_price"] or 0))
            if trade_ids is None:
                result["our_open_sells"] = int(row["cnt"] or 0)
    return result


# ---------------------------------------------------------------------------
# Flask App
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["_CATALYST_API_SERVER_MODULE"] = sys.modules[__name__]

# The bot loop instance (created at startup)
bot: BotLoop = None
_mutation_runtime = None
_mutation_runtime_db_path = None
_mutation_runtime_init_lock = threading.RLock()
_runtime_recovery_lock = threading.RLock()
_stability_startup_status = {
    "allowed": False,
    "reason_code": "STARTUP_RECOVERY_NOT_RUN",
    "source": "startup_recovery",
    "failed_check": "not_started",
    "checks": [],
    "blocker_counts": {},
    "source_ages_seconds": {},
}

_STABILITY_STARTUP_CHECKS = (
    "lease",
    "wallet_identity_freshness",
    "unresolved_operations",
    "reservations",
    "publication_claims",
    "authority_revalidation",
)

_STABILITY_BLOCKER_COUNT_KEYS = (
    "operations",
    "prepared_creations",
    "submitted_cancels",
    "contradictory_history",
    "reservations",
    "publication_claims",
)

_STABILITY_PUBLIC_SOURCES = frozenset(
    {
        "startup_recovery",
        "durable_latch",
        "durable_read",
        "operation_journal",
        "lease",
        "process",
    }
)

_STABILITY_CHECK_SOURCES = frozenset(
    {"durable_snapshot", "configured_binding", "authorized_snapshot"}
)


def _bounded_stability_count(value: Any) -> int:
    if type(value) is not int or value < 0:
        return 0
    return min(value, 2_147_483_647)


def _stability_recommended_action(reason_code: str, *, allowed: bool) -> str:
    if allowed:
        return "NONE"
    if reason_code in {"DATABASE_INTEGRITY_FAILED", "DURABLE_STATE_UNAVAILABLE"}:
        return "RESTORE_DATABASE_BACKUP"
    if reason_code == "LEASE_OWNED_BY_OTHER":
        return "USE_ACTIVE_CATALYST_INSTANCE"
    if reason_code in {"LEASE_EXPIRED", "LEASE_LOST", "STARTUP_AUTHORITY_CHANGED"}:
        return "RESTART_CATALYST"
    if reason_code.startswith("WALLET_IDENTITY_"):
        return "VERIFY_WALLET_IDENTITY"
    if reason_code == "RESERVATION_RECONCILIATION_REQUIRED":
        return "RECONCILE_COIN_RESERVATIONS"
    if reason_code == "PUBLICATION_CLAIM_RECOVERY_REQUIRED":
        return "RETRY_PUBLICATION_RECOVERY"
    if reason_code in {
        "UNRESOLVED_OPERATIONS",
        "RECONCILIATION_REQUIRED",
        "CONTRADICTORY_HISTORY",
    }:
        return "RUN_AUTHORITATIVE_RECONCILIATION"
    return "REVIEW_SAFETY_DIAGNOSTICS"


def get_public_stability_status() -> dict:
    """Return the stable, redacted Task 10 diagnostics contract."""

    live = mutation_gate.status().to_dict()
    startup = _stability_startup_status
    if type(live) is not dict or type(startup) is not dict:
        raise RuntimeError("malformed stability status")

    startup_allowed = startup.get("allowed") is True
    live_allowed = live.get("allowed") is True
    allowed = startup_allowed and live_allowed
    authority = live if startup_allowed else startup
    reason_code = str(authority.get("reason_code") or "")[:64]
    if not allowed and not reason_code:
        reason_code = "DURABLE_STATE_UNAVAILABLE"
    source = str(authority.get("source") or "durable_read")
    if source not in _STABILITY_PUBLIC_SOURCES:
        source = "durable_read"

    raw_counts = startup.get("blocker_counts")
    if type(raw_counts) is not dict:
        raw_counts = {}
    blocker_counts = {
        key: _bounded_stability_count(raw_counts.get(key))
        for key in _STABILITY_BLOCKER_COUNT_KEYS
    }

    checks = startup.get("checks")
    if type(checks) is not list:
        checks = []
    source_ages = {name: None for name in _STABILITY_STARTUP_CHECKS}
    public_checks = []
    for raw_check in checks[: len(_STABILITY_STARTUP_CHECKS)]:
        if type(raw_check) is not dict:
            continue
        name = raw_check.get("name")
        if name not in _STABILITY_STARTUP_CHECKS:
            continue
        age = raw_check.get("source_age_seconds")
        age = _bounded_stability_count(age) if type(age) is int else None
        source_ages[name] = age
        check_reason = str(raw_check.get("reason_code") or "")[:64]
        check_source = str(raw_check.get("source") or "durable_snapshot")
        if check_source not in _STABILITY_CHECK_SOURCES:
            check_source = "durable_snapshot"
        public_checks.append(
            {
                "name": name,
                "ok": raw_check.get("ok") is True,
                "reason_code": check_reason,
                "source_age_seconds": age,
                "source": check_source,
            }
        )

    wallet_hash, network = _configured_mutation_binding()
    if type(wallet_hash) is not str or len(wallet_hash) < 12:
        redacted_fingerprint = None
    else:
        redacted_fingerprint = f"sha256:{wallet_hash[:12]}…"
    if type(network) is not str or not network or len(network) > 64:
        network = "unknown"

    raw_lease = live.get("lease")
    if type(raw_lease) is not dict:
        raw_lease = {}
    lease_active = raw_lease.get("active") is True
    owned_by_this_run = lease_active and raw_lease.get("owned_by_this_run") is True
    lease_owner = (
        "this_run" if owned_by_this_run else "other_run" if lease_active else None
    )
    lease = {
        "active": lease_active,
        "version": _bounded_stability_count(raw_lease.get("version")),
        "expires_at": (
            str(raw_lease.get("expires_at"))[:40]
            if type(raw_lease.get("expires_at")) is str
            else None
        ),
        "owned_by_this_run": owned_by_this_run,
    }
    failed_check = startup.get("failed_check")
    if failed_check not in {*_STABILITY_STARTUP_CHECKS, "database_integrity", None}:
        failed_check = "startup_recovery"

    return {
        "allowed": allowed,
        "reason_code": reason_code,
        "source": source,
        "blocking_operation_count": max(
            blocker_counts["operations"],
            _bounded_stability_count(live.get("blocking_operation_count")),
        ),
        "blocker_counts": blocker_counts,
        "identity": {
            "wallet_fingerprint": redacted_fingerprint,
            "network": network,
            "lease_owner": lease_owner,
        },
        "lease": lease,
        "source_ages_seconds": source_ages,
        "recommended_action": _stability_recommended_action(
            reason_code, allowed=allowed
        ),
        "recovery": {
            "failed_check": failed_check,
            "checks": public_checks,
        },
    }


def _configured_mutation_binding() -> tuple[str, str]:
    """Return a deterministic config-only binding without wallet RPC."""

    backend = str(getattr(cfg, "WALLET_TYPE", "") or "").strip().lower()
    configured_fingerprint = (
        getattr(cfg, "SAGE_FINGERPRINT", "")
        if backend == "sage"
        else getattr(cfg, "WALLET_FINGERPRINT", "")
        if backend == "chia"
        else ""
    )
    raw_fingerprint = str(configured_fingerprint or "unconfigured").strip()
    fingerprint_hash = hashlib.sha256(
        f"fingerprint:{raw_fingerprint}".encode("utf-8")
    ).hexdigest()
    network = str(
        os.environ.get("CATALYST_NETWORK_ID")
        or os.environ.get("CHIA_NETWORK")
        or "mainnet"
    ).strip()
    if not network or len(network) > 64:
        network = "mainnet"
    return fingerprint_hash, network


def _configured_wallet_identity_binding(
    network: str,
) -> Optional[mutation_gate.WalletIdentityBinding]:
    """Build exact expected identity from canonical config without wallet RPC."""

    try:
        raw_backend = getattr(cfg, "WALLET_TYPE", "")
        if type(raw_backend) is not str:
            return None
        backend = raw_backend.strip().lower()
        if backend not in {"sage", "chia"}:
            return None
        raw_fingerprint = (
            getattr(cfg, "SAGE_FINGERPRINT", "")
            if backend == "sage"
            else getattr(cfg, "WALLET_FINGERPRINT", "")
        )
        if type(raw_fingerprint) is not str:
            return None
        if not raw_fingerprint.isascii() or not raw_fingerprint.isdigit():
            return None
        fingerprint = int(raw_fingerprint)
        if str(fingerprint) != raw_fingerprint:
            return None
        raw_expected_name = getattr(cfg, "WALLET_EXPECTED_NAME", "")
        if type(raw_expected_name) is not str:
            return None
        expected_name = raw_expected_name.strip()
        if not expected_name:
            return None
        raw_expected_kind = getattr(cfg, "WALLET_EXPECTED_KEY_KIND", "")
        if type(raw_expected_kind) is not str:
            return None
        expected_kind = raw_expected_kind.strip()
        if not expected_kind:
            return None
        maximum_age = getattr(cfg, "WALLET_IDENTITY_MAX_AGE_SECONDS", None)
        if type(maximum_age) is not int:
            return None
        bound_at = (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        return mutation_gate.WalletIdentityBinding(
            backend=backend,
            name=expected_name,
            fingerprint=fingerprint,
            network_id=network,
            kind=expected_kind,
            has_secrets=True,
            bound_at_utc=bound_at,
            maximum_age_seconds=maximum_age,
        )
    except Exception:
        return None


def _mutation_stop_handler(reason_code: str) -> None:
    """Stop a running bot immediately after the mutation lease fails."""

    current_bot = bot
    if current_bot is None:
        return
    try:
        if current_bot.is_running():
            try:
                current_bot.stop(wait=False)
            except TypeError:
                current_bot.stop()
        slog(
            "SAFETY",
            "Bot switched to read-only after mutation safety stop",
            {"reason_code": str(reason_code or "MUTATION_GATE_SAFETY_STOP")},
            level="critical",
        )
    except Exception:
        slog(
            "SAFETY",
            "Could not confirm bot stop after mutation safety event",
            {"reason_code": "MUTATION_GATE_SAFETY_STOP"},
            level="critical",
        )


def _startup_source_age_seconds(value: Any) -> Optional[int]:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed.tzinfo is None or observed.utcoffset() is None:
            return None
        age = (
            datetime.now(timezone.utc) - observed.astimezone(timezone.utc)
        ).total_seconds()
        if age < 0:
            return None
        return min(int(age), 2_147_483_647)
    except (TypeError, ValueError, OverflowError):
        return None


def _startup_check_result(
    ok: bool,
    reason_code: str = "",
    *,
    source: str = "durable_snapshot",
    source_age_seconds: Optional[int] = None,
    blocker_counts: Optional[dict] = None,
) -> dict:
    safe_source = source if source in _STABILITY_CHECK_SOURCES else "durable_snapshot"
    return {
        "ok": ok is True,
        "reason_code": str(reason_code or "")[:64],
        "source": safe_source,
        "source_age_seconds": (
            source_age_seconds
            if type(source_age_seconds) is int and source_age_seconds >= 0
            else None
        ),
        "blocker_counts": dict(blocker_counts or {}),
    }


def _configured_startup_identity_authority(
    binding: Any,
    wallet_fingerprint_hash: Any,
    network: Any,
) -> Optional[dict[str, str]]:
    """Validate the immutable config binding without importing a wallet adapter."""

    try:
        if type(binding) is not mutation_gate.WalletIdentityBinding:
            return None
        if type(wallet_fingerprint_hash) is not str:
            return None
        if type(network) is not str or not network.strip():
            return None
        if (
            mutation_gate.wallet_fingerprint_hash(binding.fingerprint)
            != wallet_fingerprint_hash
            or binding.network_id != network.strip().lower()
        ):
            return None
        return {
            "binding_digest": mutation_gate.wallet_identity_binding_digest(binding),
            "wallet_fingerprint_hash": wallet_fingerprint_hash,
            "network": binding.network_id,
            "bound_at_utc": binding.bound_at_utc,
        }
    except Exception:
        return None


def _run_stability_startup_check(name: str, **context) -> dict:
    """Run one allowlisted read-only Task 10 recovery check."""

    if name not in _STABILITY_STARTUP_CHECKS:
        return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")
    state = context.get("state")
    runtime = context.get("runtime")
    binding = context.get("wallet_identity_binding")
    if type(state) is not dict or runtime is None:
        return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")

    if name == "lease":
        snapshot = database.get_stability_startup_recovery_snapshot()
        state["initial_snapshot"] = snapshot
        lease = snapshot.get("lease")
        if type(lease) is not dict:
            return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")
        heartbeat_age = _startup_source_age_seconds(lease.get("heartbeat_at"))
        if lease.get("active") not in {0, 1, False, True}:
            return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")
        if bool(lease.get("active")):
            recovery_epoch = context.get("recovery_epoch")
            exact_current_owner = (
                type(recovery_epoch) is dict
                and lease.get("owner_run_id") == runtime.run_id
                and lease.get("owner_pid") == runtime.owner_pid
                and lease.get("owner_host") == runtime.owner_host
                and lease.get("wallet_fingerprint_hash")
                == recovery_epoch.get("wallet_fingerprint_hash")
                and lease.get("network") == recovery_epoch.get("network")
                and recovery_epoch.get("owner_run_id") == runtime.run_id
            )
            if exact_current_owner:
                return _startup_check_result(
                    True, source_age_seconds=heartbeat_age
                )
            try:
                expiry = datetime.fromisoformat(
                    str(lease.get("expires_at") or "").replace("Z", "+00:00")
                )
                expired = (
                    expiry.tzinfo is not None
                    and expiry.utcoffset() is not None
                    and expiry.astimezone(timezone.utc) <= datetime.now(timezone.utc)
                )
            except (TypeError, ValueError, OverflowError):
                expired = False
            if not expired:
                return _startup_check_result(
                    False,
                    "LEASE_OWNED_BY_OTHER",
                    source_age_seconds=heartbeat_age,
                )
            try:
                prior_alive = runtime._pid_liveness(
                    int(lease.get("owner_pid") or 0),
                    str(lease.get("owner_host") or ""),
                )
            except Exception:
                prior_alive = None
            if prior_alive is not False:
                return _startup_check_result(
                    False,
                    "LEASE_EXPIRED",
                    source_age_seconds=heartbeat_age,
                )
        return _startup_check_result(True, source_age_seconds=heartbeat_age)

    initial = state.get("initial_snapshot")
    if type(initial) is not dict:
        return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")

    if name == "wallet_identity_freshness":
        configured_authority = _configured_startup_identity_authority(
            binding,
            context.get("wallet_fingerprint_hash"),
            context.get("network"),
        )
        if configured_authority is None:
            return _startup_check_result(
                False,
                "WALLET_IDENTITY_BINDING_INVALID",
                source="configured_binding",
            )
        state["configured_identity_authority"] = configured_authority
        if "cached_wallet_identity_snapshot" not in context:
            state["identity_source"] = "configured_binding"
            return _startup_check_result(True, source="configured_binding")

        identity = context.get("cached_wallet_identity_snapshot")
        decision = mutation_gate.validate_wallet_identity(binding, identity)
        if decision.get("allowed") is not True:
            return _startup_check_result(
                False,
                str(decision.get("reason") or "WALLET_IDENTITY_MALFORMED"),
                source="authorized_snapshot",
                source_age_seconds=_startup_source_age_seconds(
                    identity.get("observed_at_utc") if type(identity) is dict else None
                ),
            )
        state["identity_source"] = "authorized_snapshot"
        state["identity_observed_at_utc"] = str(decision["observed_at_utc"])
        return _startup_check_result(
            True,
            source="authorized_snapshot",
            source_age_seconds=_startup_source_age_seconds(decision["observed_at_utc"]),
        )

    counts = initial.get("blocker_counts")
    if type(counts) is not dict:
        return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")
    if name == "unresolved_operations":
        latch = initial.get("latch")
        blockers = initial.get("blockers")
        if type(latch) is not dict or type(blockers) is not list:
            return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")
        recovery_epoch = context.get("recovery_epoch")
        recovery_latch = (
            type(recovery_epoch) is dict
            and latch.get("state") == "tripped"
            and int(latch.get("generation") or -1)
            == recovery_epoch.get("latch_generation")
            and latch.get("wallet_fingerprint_hash")
            == recovery_epoch.get("wallet_fingerprint_hash")
            and latch.get("network") == recovery_epoch.get("network")
            and json.loads(latch.get("blocking_operation_ids_json") or "null")
            == [recovery_epoch.get("blocker_id")]
        )
        if latch.get("state") != "resolved" and not recovery_latch:
            reason = str(latch.get("reason_code") or "RECONCILIATION_REQUIRED")
            return _startup_check_result(False, reason, blocker_counts=counts)
        if blockers:
            return _startup_check_result(
                False,
                "UNRESOLVED_OPERATIONS",
                source_age_seconds=_startup_source_age_seconds(
                    initial.get("source_timestamps", {}).get("operations")
                ),
                blocker_counts=counts,
            )
        return _startup_check_result(True, blocker_counts=counts)

    if name == "reservations":
        issues = initial.get("reservation_issues")
        if type(issues) is not list:
            return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")
        return _startup_check_result(
            not issues,
            "RESERVATION_RECONCILIATION_REQUIRED" if issues else "",
            source_age_seconds=_startup_source_age_seconds(
                initial.get("source_timestamps", {}).get("reservations")
            ),
            blocker_counts=counts,
        )

    if name == "publication_claims":
        issues = initial.get("publication_issues")
        if type(issues) is not list:
            return _startup_check_result(False, "DURABLE_STATE_UNAVAILABLE")
        return _startup_check_result(
            not issues,
            "PUBLICATION_CLAIM_RECOVERY_REQUIRED" if issues else "",
            source_age_seconds=_startup_source_age_seconds(
                initial.get("source_timestamps", {}).get("publication_claims")
            ),
            blocker_counts=counts,
        )

    current = database.get_stability_startup_recovery_snapshot()
    if current.get("authority_digest") != initial.get("authority_digest"):
        return _startup_check_result(
            False,
            "STARTUP_AUTHORITY_CHANGED",
            blocker_counts=current.get("blocker_counts"),
        )
    configured_authority = _configured_startup_identity_authority(
        binding,
        context.get("wallet_fingerprint_hash"),
        context.get("network"),
    )
    if configured_authority is None or configured_authority != state.get(
        "configured_identity_authority"
    ):
        return _startup_check_result(
            False,
            "STARTUP_AUTHORITY_CHANGED",
            source="configured_binding",
            blocker_counts=current.get("blocker_counts"),
        )
    if state.get("identity_source") == "configured_binding":
        return _startup_check_result(
            True,
            source="configured_binding",
            blocker_counts=current.get("blocker_counts"),
        )
    if state.get("identity_source") != "authorized_snapshot":
        return _startup_check_result(
            False,
            "WALLET_IDENTITY_UNAVAILABLE",
            source="authorized_snapshot",
            blocker_counts=current.get("blocker_counts"),
        )

    identity = context.get("cached_wallet_identity_revalidation_snapshot")
    decision = mutation_gate.validate_wallet_identity(
        binding,
        identity,
        last_observed_at_utc=state.get("identity_observed_at_utc"),
    )
    if decision.get("allowed") is not True:
        return _startup_check_result(
            False,
            str(decision.get("reason") or "WALLET_IDENTITY_MALFORMED"),
            source="authorized_snapshot",
            source_age_seconds=_startup_source_age_seconds(
                identity.get("observed_at_utc") if type(identity) is dict else None
            ),
            blocker_counts=current.get("blocker_counts"),
        )
    return _startup_check_result(
        True,
        source="authorized_snapshot",
        source_age_seconds=_startup_source_age_seconds(decision["observed_at_utc"]),
        blocker_counts=current.get("blocker_counts"),
    )


def _run_runtime_recovery(decision: Any, sample: Any) -> dict:
    """Fence one discontinuity and reuse the exact ordered Task 10 checks."""

    global _stability_startup_status
    with _runtime_recovery_lock:
        runtime = mutation_gate.current_runtime()
        if runtime is None:
            return {"allowed": False, "reason_code": "MUTATION_RUNTIME_NOT_INITIALIZED"}
        clock_evidence = {
            "reason_code": decision.reason_code,
            "monotonic_delta_seconds": decision.monotonic_delta_seconds,
            "wall_delta_seconds": decision.wall_delta_seconds,
            "sample_monotonic_seconds": str(sample.monotonic_seconds),
            "sample_wall_utc": sample.wall_utc.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
        }
        try:
            try:
                lease_version = runtime.require_allowed(
                    "runtime_recovery:boundary"
                ).lease_version
                existing_epoch = None
            except Exception:
                # A failed read-only recovery pass deliberately leaves the durable
                # latch tripped.  Only the exact same owner/binding/lease may retry
                # that epoch; this neither clears the gate nor acquires a lease.
                existing_epoch = database.get_current_runtime_recovery()
                lease = database.get_runtime_mutation_lease()
                if (
                    type(existing_epoch) is not dict
                    or type(lease) is not dict
                    or existing_epoch.get("owner_run_id") != runtime.run_id
                    or existing_epoch.get("wallet_fingerprint_hash")
                    != runtime.wallet_fingerprint_hash
                    or existing_epoch.get("network") != runtime.network
                    or lease.get("owner_run_id") != runtime.run_id
                    or lease.get("wallet_fingerprint_hash")
                    != runtime.wallet_fingerprint_hash
                    or lease.get("network") != runtime.network
                    or type(lease.get("lease_version")) is not int
                    or lease["lease_version"] < 1
                ):
                    raise
                lease_version = lease["lease_version"]
            recovery_material = json.dumps(
                {
                    "owner_run_id": runtime.run_id,
                    "lease_version": lease_version,
                    "clock_evidence": clock_evidence,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            recovery_id = "recovery:" + hashlib.sha256(
                recovery_material.encode("utf-8")
            ).hexdigest()
            if (
                existing_epoch is not None
                and existing_epoch.get("recovery_id") != recovery_id
            ):
                raise ValueError("runtime recovery replay does not match current epoch")
            epoch_result = database.begin_runtime_recovery_epoch(
                recovery_id=recovery_id,
                reason_code=decision.reason_code,
                clock_evidence=clock_evidence,
                wallet_fingerprint_hash=runtime.wallet_fingerprint_hash,
                network=runtime.network,
                owner_run_id=runtime.run_id,
                started_at=sample.wall_utc,
            )
            epoch = epoch_result["record"]
        except Exception:
            return {"allowed": False, "reason_code": "DURABLE_STATE_UNAVAILABLE"}

        wallet_hash, network = _configured_mutation_binding()
        binding = runtime.wallet_identity_binding
        try:
            from wallet import get_wallet_identity

            first_identity = get_wallet_identity()
            second_identity = get_wallet_identity()
        except Exception:
            first_identity = None
            second_identity = None
        state: dict[str, Any] = {}
        checks: list[dict] = []
        for check_name in _STABILITY_STARTUP_CHECKS:
            check = _run_stability_startup_check(
                check_name,
                state=state,
                runtime=runtime,
                recovery_epoch=epoch,
                wallet_identity_binding=binding,
                wallet_fingerprint_hash=wallet_hash,
                network=network,
                cached_wallet_identity_snapshot=first_identity,
                cached_wallet_identity_revalidation_snapshot=second_identity,
            )
            recorded = {"name": check_name, **check}
            checks.append(recorded)
            if check.get("ok") is not True:
                result = _blocked_startup_recovery_status(
                    check.get("reason_code") or "DURABLE_STATE_UNAVAILABLE",
                    check_name,
                    checks,
                    runtime,
                )
                result["blocker_counts"] = dict(check.get("blocker_counts") or {})
                _stability_startup_status = _redacted_startup_status(result)
                return result
        try:
            initial = state["initial_snapshot"]
            database.record_runtime_recovery_pass(
                recovery_id=recovery_id,
                expected_latch_generation=int(epoch["latch_generation"]),
                authority_digest=initial["authority_digest"],
                checks=checks,
                passed_at=datetime.now(timezone.utc),
            )
            rotate = getattr(mutation_gate, "_rotate_owner_identity_authority", None)
            if not callable(rotate) or rotate(runtime) is not True:
                raise RuntimeError("mutation authority rotation unavailable")
            released = runtime.release_resolved(
                int(epoch["latch_generation"]), [epoch["blocker_id"]]
            )
            if released.get("released") is not True:
                raise RuntimeError("runtime recovery latch release failed")
        except Exception:
            return {"allowed": False, "reason_code": "RECOVERY_PROMOTION_FAILED"}
        result = released["status"]
        result.update(
            {
                "allowed": True,
                "reason_code": "RECOVERY_COMPLETE",
                "source": "startup_recovery",
                "failed_check": None,
                "checks": checks,
                "blocker_counts": dict(checks[-1].get("blocker_counts") or {}),
            }
        )
        _stability_startup_status = _redacted_startup_status(result)
        return result


def _blocked_startup_recovery_status(
    reason_code: str,
    failed_check: str,
    checks: list[dict],
    runtime,
) -> dict:
    try:
        raw_status = runtime.status().to_dict() if runtime is not None else {}
    except Exception:
        raw_status = {}
    raw_lease = raw_status.get("lease")
    if type(raw_lease) is not dict:
        raw_lease = {}
    return {
        "allowed": False,
        "reason_code": str(reason_code or "DURABLE_STATE_UNAVAILABLE")[:64],
        "source": "startup_recovery",
        "failed_check": failed_check,
        "checks": [dict(item) for item in checks],
        "blocker_counts": {},
        "blocking_operation_count": _bounded_stability_count(
            raw_status.get("blocking_operation_count")
        ),
        "lease": {
            "active": raw_lease.get("active") is True,
            "version": _bounded_stability_count(raw_lease.get("version")),
            "expires_at": (
                str(raw_lease.get("expires_at"))[:40]
                if type(raw_lease.get("expires_at")) is str
                else None
            ),
            "owned_by_this_run": raw_lease.get("owned_by_this_run") is True,
        },
    }


def _redacted_startup_status(status: Any) -> dict:
    """Retain diagnostics without durable owner, PID, or operation identities."""

    if type(status) is not dict:
        status = {}
    raw_lease = status.get("lease")
    if type(raw_lease) is not dict:
        raw_lease = {}
    raw_counts = status.get("blocker_counts")
    if type(raw_counts) is not dict:
        raw_counts = {}
    raw_checks = status.get("checks")
    if type(raw_checks) is not list:
        raw_checks = []
    return {
        "allowed": status.get("allowed") is True,
        "reason_code": str(status.get("reason_code") or "")[:64],
        "source": "startup_recovery",
        "failed_check": status.get("failed_check"),
        "checks": [dict(item) for item in raw_checks[: len(_STABILITY_STARTUP_CHECKS)]],
        "blocker_counts": {
            key: _bounded_stability_count(raw_counts.get(key))
            for key in _STABILITY_BLOCKER_COUNT_KEYS
        },
        "blocking_operation_count": _bounded_stability_count(
            status.get("blocking_operation_count")
        ),
        "lease": {
            "active": raw_lease.get("active") is True,
            "version": _bounded_stability_count(raw_lease.get("version")),
            "expires_at": (
                str(raw_lease.get("expires_at"))[:40]
                if type(raw_lease.get("expires_at")) is str
                else None
            ),
            "owned_by_this_run": raw_lease.get("owned_by_this_run") is True,
        },
    }


def _discard_failed_owner_startup_runtime(runtime: Any) -> None:
    """Detach a failed pre-owner runtime without releasing any durable lease."""

    global _mutation_runtime, _mutation_runtime_db_path
    if mutation_gate.current_runtime() is runtime and runtime is not None:
        mutation_gate.shutdown_runtime(release_owned_lease=False)
    _mutation_runtime = None
    _mutation_runtime_db_path = None


def initialize_mutation_runtime(
    *, start_heartbeat: bool = True, acquire_lease: bool = True
) -> dict:
    """Complete ordered read-only recovery before acquiring mutation ownership."""

    global _mutation_runtime, _mutation_runtime_db_path, _stability_startup_status
    with _mutation_runtime_init_lock:
        current_path = os.path.normcase(os.path.abspath(database.DB_PATH))
        current_runtime = mutation_gate.current_runtime()
        if (
            current_runtime is not None
            and _mutation_runtime is current_runtime
            and _mutation_runtime_db_path == current_path
        ):
            result = current_runtime.status().to_dict()
            startup = _stability_startup_status
            if type(startup) is dict:
                raw_checks = startup.get("checks")
                raw_counts = startup.get("blocker_counts")
                result["failed_check"] = startup.get("failed_check")
                result["checks"] = (
                    [dict(item) for item in raw_checks]
                    if type(raw_checks) is list
                    and all(type(item) is dict for item in raw_checks)
                    else []
                )
                result["blocker_counts"] = (
                    dict(raw_counts) if type(raw_counts) is dict else {}
                )
                if startup.get("allowed") is True and result.get("allowed") is True:
                    result["source"] = "startup_recovery"
            return result

        wallet_hash, network = _configured_mutation_binding()
        wallet_identity_binding = _configured_wallet_identity_binding(network)
        if acquire_lease:
            try:
                integrity = database.check_db_integrity()
            except Exception:
                integrity = {"ok": False}
            if type(integrity) is not dict or integrity.get("ok") is not True:
                result = _blocked_startup_recovery_status(
                    "DATABASE_INTEGRITY_FAILED",
                    "database_integrity",
                    [],
                    None,
                )
                _discard_failed_owner_startup_runtime(mutation_gate.current_runtime())
                _stability_startup_status = _redacted_startup_status(result)
                return result
        _mutation_runtime = mutation_gate.initialize(
            wallet_fingerprint_hash=wallet_hash,
            network=network,
            wallet_identity_binding=wallet_identity_binding,
            wallet_adapter_authority=get_wallet_adapter_authority(),
            start_heartbeat=False if acquire_lease else start_heartbeat,
            acquire_lease=False if acquire_lease else False,
        )
        _mutation_runtime_db_path = os.path.normcase(os.path.abspath(database.DB_PATH))
        _mutation_runtime.register_stop_handler(_mutation_stop_handler)
        if acquire_lease:
            state: dict[str, Any] = {}
            checks = []
            try:
                for check_name in _STABILITY_STARTUP_CHECKS:
                    check = _run_stability_startup_check(
                        check_name,
                        state=state,
                        runtime=_mutation_runtime,
                        wallet_identity_binding=wallet_identity_binding,
                        wallet_fingerprint_hash=wallet_hash,
                        network=network,
                    )
                    if type(check) is not dict or type(check.get("ok")) is not bool:
                        raise RuntimeError(
                            "startup recovery check returned malformed data"
                        )
                    recorded = {"name": check_name, **check}
                    checks.append(recorded)
                    if check["ok"] is not True:
                        result = _blocked_startup_recovery_status(
                            check.get("reason_code") or "DURABLE_STATE_UNAVAILABLE",
                            check_name,
                            checks,
                            _mutation_runtime,
                        )
                        result["blocker_counts"] = dict(
                            check.get("blocker_counts") or {}
                        )
                        failed_runtime = _mutation_runtime
                        _discard_failed_owner_startup_runtime(failed_runtime)
                        _stability_startup_status = _redacted_startup_status(result)
                        return result
                _mutation_runtime = mutation_gate.initialize(
                    wallet_fingerprint_hash=wallet_hash,
                    network=network,
                    wallet_identity_binding=wallet_identity_binding,
                    wallet_adapter_authority=get_wallet_adapter_authority(),
                    start_heartbeat=start_heartbeat,
                    acquire_lease=True,
                )
                _mutation_runtime.register_stop_handler(_mutation_stop_handler)
            except Exception:
                result = _blocked_startup_recovery_status(
                    "DURABLE_STATE_UNAVAILABLE",
                    checks[-1]["name"] if checks else "startup_recovery",
                    checks,
                    _mutation_runtime,
                )
                failed_runtime = _mutation_runtime
                _discard_failed_owner_startup_runtime(failed_runtime)
                _stability_startup_status = _redacted_startup_status(result)
                return result
        result = _mutation_runtime.status().to_dict()
        if acquire_lease:
            result["failed_check"] = (
                None if result.get("allowed") else "lease_promotion"
            )
            result["checks"] = checks
            result["source"] = (
                "startup_recovery" if result.get("allowed") else result.get("source")
            )
            result["blocker_counts"] = dict(
                checks[-1].get("blocker_counts") if checks else {}
            )
            if result.get("allowed") is not True:
                failed_runtime = _mutation_runtime
                _discard_failed_owner_startup_runtime(failed_runtime)
            _stability_startup_status = _redacted_startup_status(result)
    slog(
        "SAFETY",
        "Mutation runtime initialized",
        {
            "allowed": result["allowed"],
            "reason_code": result["reason_code"],
            "lease_owner_pid": result["lease"]["owner_pid"],
        },
        level="info" if result["allowed"] else "warning",
    )
    return result


def _start_owned_runtime_services(startup_authorization: dict) -> dict:
    """Start tracked background services only from an actual owner entry path."""

    if not isinstance(startup_authorization, dict) or (
        startup_authorization.get("allowed") is not True
    ):
        return {"cat_resolver_started": False}
    starter = globals().get("_start_background_cat_resolver")
    if not callable(starter):
        return {"cat_resolver_started": False}
    try:
        return {"cat_resolver_started": starter() is not None}
    except Exception:
        slog(
            "SAFETY",
            "Owned CAT resolver startup failed closed",
            {"reason_code": "CAT_RESOLVER_START_FAILED"},
            level="warning",
        )
        return {"cat_resolver_started": False}


def _ensure_mutation_runtime() -> None:
    global _mutation_runtime, _mutation_runtime_db_path
    with _mutation_runtime_init_lock:
        current_path = os.path.normcase(os.path.abspath(database.DB_PATH))
        if (
            mutation_gate.current_runtime() is not None
            and _mutation_runtime_db_path == current_path
        ):
            return
        try:
            if mutation_gate.current_runtime() is not None:
                mutation_gate.shutdown_runtime()
                _mutation_runtime = None
                _mutation_runtime_db_path = None
            init_database()
            initialize_mutation_runtime()
        except Exception:
            # The request guard below still fails closed with the stable
            # MUTATION_RUNTIME_NOT_INITIALIZED result.
            slog(
                "SAFETY",
                "Mutation runtime initialization failed",
                {"reason_code": "DURABLE_STATE_UNAVAILABLE"},
                level="error",
            )


def release_mutation_runtime() -> dict:
    global _mutation_runtime, _mutation_runtime_db_path
    with _mutation_runtime_init_lock:
        result = mutation_gate.shutdown_runtime(release_owned_lease=True)
        _mutation_runtime = None
        _mutation_runtime_db_path = None
        return result


_background_mutation_threads_lock = threading.Lock()
_background_mutation_threads: dict[int, threading.Thread] = {}


def start_mutation_thread(*, operation: str, target, name: str) -> threading.Thread:
    """Start one tracked async mutator with a permit held for its lifetime."""

    permit = mutation_gate.enter_mutation(operation)
    holder: dict[str, threading.Thread] = {}

    def run() -> None:
        try:
            target()
        finally:
            mutation_gate.exit_mutation(permit)
            thread = holder.get("thread")
            if thread is not None:
                with _background_mutation_threads_lock:
                    _background_mutation_threads.pop(id(thread), None)

    thread = threading.Thread(target=run, name=str(name)[:128], daemon=True)
    holder["thread"] = thread
    with _background_mutation_threads_lock:
        _background_mutation_threads[id(thread)] = thread
    try:
        thread.start()
    except Exception:
        with _background_mutation_threads_lock:
            _background_mutation_threads.pop(id(thread), None)
        mutation_gate.exit_mutation(permit)
        raise
    return thread


def _shutdown_thread_refs(bot_instance) -> list[Any]:
    """Return a de-duplicated snapshot of mutation-producing threads."""

    class _UnverifiableThreadInventory:
        name = "mutation-thread-inventory"

        @staticmethod
        def is_alive():
            raise RuntimeError("mutation thread inventory unavailable")

    refs: list[Any] = []
    owners = [bot_instance]
    if bot_instance is not None:
        owners.extend(
            [
                getattr(bot_instance, "coin_manager", None),
                getattr(bot_instance, "runtime_monitor", None),
                getattr(bot_instance, "amm_monitor", None),
                getattr(bot_instance, "shape_fix_orchestrator", None),
            ]
        )
    for owner in owners:
        if owner is None:
            continue
        for attr in (
            "_thread",
            "_topup_thread",
            "_splash_receive_thread",
            "_health_thread",
            "_watcher_thread",
            "_coin_watcher_thread",
            "_startup_repost_thread",
            "_stop_finalize_thread",
            "_graceful_cancel_thread",
        ):
            candidate = getattr(owner, attr, None)
            if candidate is not None and callable(getattr(candidate, "is_alive", None)):
                refs.append(candidate)
        for collection_name in ("_ladder_threads", "_sniper_threads"):
            ladder_threads = getattr(owner, collection_name, None)
            if not isinstance(ladder_threads, (list, tuple, set)):
                continue
            refs.extend(
                candidate
                for candidate in ladder_threads
                if callable(getattr(candidate, "is_alive", None))
            )
        worker_threads = getattr(owner, "_threads", None)
        if isinstance(worker_threads, dict):
            owner_lock = getattr(owner, "_lock", None)
            try:
                if owner_lock is None:
                    worker_snapshot = tuple(worker_threads.values())
                else:
                    with owner_lock:
                        worker_snapshot = tuple(worker_threads.values())
            except Exception:
                refs.append(_UnverifiableThreadInventory())
                continue
            refs.extend(
                candidate
                for candidate in worker_snapshot
                if callable(getattr(candidate, "is_alive", None))
            )
    for global_name in (
        "_coin_prep_thread",
        "_cancel_all_thread",
        "_boost_activation_thread",
    ):
        candidate = globals().get(global_name)
        if candidate is not None and callable(getattr(candidate, "is_alive", None)):
            refs.append(candidate)
    with _background_mutation_threads_lock:
        refs.extend(_background_mutation_threads.values())
    return list({id(item): item for item in refs}.values())


def _stop_child_process(process, *, timeout_seconds: float) -> bool:
    """Stop one child and prove it exited; uncertainty is a hard failure."""

    if process is None:
        return True
    try:
        if process.poll() is not None:
            return True
    except Exception:
        return False
    try:
        process.terminate()
        process.wait(timeout=max(0.0, timeout_seconds))
    except Exception:
        try:
            process.kill()
            process.wait(timeout=max(0.0, timeout_seconds))
        except Exception:
            return False
    try:
        return process.poll() is not None
    except Exception:
        return False


def _thread_name(thread) -> str:
    name = getattr(thread, "name", None)
    return str(name)[:128] if name else "unnamed-mutation-thread"


def quiesce_and_release_mutation_runtime(
    *, bot_instance=None, wait_seconds: float = 30.0
) -> dict[str, Any]:
    """Release ownership only after every local mutation source is proven stopped."""

    global _coin_prep_proc, _coin_prep_thread
    runtime = mutation_gate.current_runtime()
    if runtime is None:
        return {"released": False, "reason": "not_initialized"}

    runtime.begin_quiesce()
    target_bot = bot if bot_instance is None else bot_instance
    manager = (
        getattr(target_bot, "coin_manager", None) if target_bot is not None else None
    )
    known_threads = _shutdown_thread_refs(target_bot)
    stop_failed = False

    if target_bot is not None:
        try:
            target_bot.stop(wait=True)
        except Exception:
            stop_failed = True

    shape_fix = (
        getattr(target_bot, "shape_fix_orchestrator", None)
        if target_bot is not None
        else None
    )
    if shape_fix is not None and callable(getattr(shape_fix, "abort_flow", None)):
        for side in ("buy", "sell"):
            try:
                shape_fix.abort_flow(side)
            except Exception:
                stop_failed = True

    for monitor_name in ("runtime_monitor", "amm_monitor"):
        monitor = (
            getattr(target_bot, monitor_name, None) if target_bot is not None else None
        )
        if monitor is not None and callable(getattr(monitor, "stop", None)):
            try:
                monitor.stop()
            except Exception:
                stop_failed = True

    manager_process = getattr(manager, "_prep_process", None) if manager else None
    blueprint_process = _coin_prep_proc
    process_results: list[tuple[Any, bool]] = []
    unique_processes = {
        id(item): item
        for item in (manager_process, blueprint_process)
        if item is not None
    }
    for process in unique_processes.values():
        process_results.append(
            (process, _stop_child_process(process, timeout_seconds=wait_seconds))
        )
    if any(not stopped for _process, stopped in process_results):
        stop_failed = True

    manager_process_stopped = manager_process is None or any(
        process is manager_process and stopped for process, stopped in process_results
    )
    blueprint_process_stopped = blueprint_process is None or any(
        process is blueprint_process and stopped for process, stopped in process_results
    )
    if manager_process_stopped and manager is not None:
        delegation = getattr(manager, "_prep_delegation", None)
        if delegation is not None:
            try:
                from coin_manager import _revoke_coin_prep_worker_delegation

                revoke = _revoke_coin_prep_worker_delegation(delegation)
            except Exception:
                revoke = {"revoked": False, "reason": "delegation_revoke_failed"}
            if not revoke.get("revoked") and revoke.get("reason") not in {
                "delegation_not_active",
                "delegation_not_found",
            }:
                stop_failed = True
            else:
                manager._prep_delegation = None
        manager._prep_process = None
        manager._prep_running = False
    if blueprint_process_stopped:
        _coin_prep_proc = None
        _coin_prep_state["running"] = False

    live_child_pids = sorted(
        {
            int(getattr(process, "pid", 0) or 0)
            for process, stopped in process_results
            if not stopped and int(getattr(process, "pid", 0) or 0) > 0
        }
    )
    if live_child_pids:
        stop_failed = True

    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    all_threads = list(
        {
            id(item): item for item in known_threads + _shutdown_thread_refs(target_bot)
        }.values()
    )
    for thread in all_threads:
        if thread is threading.current_thread():
            continue
        try:
            if thread.is_alive() and callable(getattr(thread, "join", None)):
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        except Exception:
            stop_failed = True

    all_threads = list(
        {
            id(item): item for item in all_threads + _shutdown_thread_refs(target_bot)
        }.values()
    )
    live_threads: list[str] = []
    unverified_threads: list[str] = []
    for thread in all_threads:
        if thread is threading.current_thread():
            continue
        try:
            alive = bool(thread.is_alive())
        except Exception:
            unverified_threads.append(_thread_name(thread))
            stop_failed = True
            continue
        if alive:
            live_threads.append(_thread_name(thread))
    live_threads = sorted(set(live_threads))
    unverified_threads = sorted(set(unverified_threads))
    if live_threads:
        stop_failed = True
    if manager is not None and (
        bool(getattr(manager, "_prep_running", False))
        or bool(getattr(manager, "_topup_running", False))
    ):
        stop_failed = True

    if not runtime.wait_for_quiescence(max(0.0, deadline - time.monotonic())):
        runtime.stop_heartbeat()
        return {
            "released": False,
            "reason": "mutations_in_flight",
            "live_threads": live_threads,
            "unverified_threads": unverified_threads,
            "live_child_pids": live_child_pids,
        }

    # A permitted launcher may publish its subprocess handle immediately
    # before returning. Re-snapshot children only after permits have drained.
    final_manager_process = getattr(manager, "_prep_process", None) if manager else None
    final_blueprint_process = _coin_prep_proc
    known_process_ids = {id(process) for process, _stopped in process_results}
    for process in (final_manager_process, final_blueprint_process):
        if process is not None and id(process) not in known_process_ids:
            process_results.append(
                (process, _stop_child_process(process, timeout_seconds=wait_seconds))
            )
            known_process_ids.add(id(process))
    if any(not stopped for _process, stopped in process_results):
        stop_failed = True

    final_manager_stopped = final_manager_process is None or any(
        process is final_manager_process and stopped
        for process, stopped in process_results
    )
    if final_manager_stopped and manager is not None:
        delegation = getattr(manager, "_prep_delegation", None)
        if delegation is not None:
            try:
                from coin_manager import _revoke_coin_prep_worker_delegation

                revoke = _revoke_coin_prep_worker_delegation(delegation)
            except Exception:
                revoke = {"revoked": False, "reason": "delegation_revoke_failed"}
            if not revoke.get("revoked") and revoke.get("reason") not in {
                "delegation_not_active",
                "delegation_not_found",
            }:
                stop_failed = True
            else:
                manager._prep_delegation = None
        manager._prep_process = None
        manager._prep_running = False
    final_blueprint_stopped = final_blueprint_process is None or any(
        process is final_blueprint_process and stopped
        for process, stopped in process_results
    )
    if final_blueprint_stopped:
        _coin_prep_proc = None
        _coin_prep_state["running"] = False
    live_child_pids = sorted(
        {
            int(getattr(process, "pid", 0) or 0)
            for process, stopped in process_results
            if not stopped and int(getattr(process, "pid", 0) or 0) > 0
        }
    )

    # A request that already held a permit when quiescence began may publish
    # its worker reference immediately before exiting that permit.  Drain
    # permits first, then take the definitive producer snapshot.
    final_threads = _shutdown_thread_refs(target_bot)
    for thread in final_threads:
        if thread is threading.current_thread():
            continue
        try:
            if thread.is_alive() and callable(getattr(thread, "join", None)):
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        except Exception:
            unverified_threads.append(_thread_name(thread))
            stop_failed = True
    for thread in final_threads:
        if thread is threading.current_thread():
            continue
        try:
            if thread.is_alive():
                live_threads.append(_thread_name(thread))
                stop_failed = True
        except Exception:
            unverified_threads.append(_thread_name(thread))
            stop_failed = True
    live_threads = sorted(set(live_threads))
    unverified_threads = sorted(set(unverified_threads))
    if stop_failed:
        runtime.stop_heartbeat()
        return {
            "released": False,
            "reason": "mutation_producers_not_stopped",
            "live_threads": live_threads,
            "unverified_threads": unverified_threads,
            "live_child_pids": live_child_pids,
        }

    return release_mutation_runtime()


# Active CAT selection — updated when user picks a CAT from the dropdown.
# Stores wallet_id, asset_id, name, decimals so /api/status can fetch
# the correct balance regardless of what's in .env.
# Initialize from .env so pricing works immediately on startup (before user selects a CAT)
_active_cat = {
    "wallet_id": getattr(cfg, "CAT_WALLET_ID", None),
    "asset_id": getattr(cfg, "CAT_ASSET_ID", None) or None,
    "name": getattr(cfg, "CAT_NAME", None) or None,
    "decimals": getattr(cfg, "CAT_DECIMALS", None),
    "ticker_id": getattr(cfg, "CAT_TICKER_ID", None) or None,
}
# Lock for multi-key mutations of _active_cat so readers never see a
# half-updated pair (e.g. asset_id from the new CAT but decimals from the old).
_active_cat_lock = threading.Lock()
SAGE_ACTIVE_CAT_WALLET_ID = 2
_balance_snapshot_lock = threading.Lock()
_latest_balance_snapshot: dict[str, Any] = {}


def active_cat_wallet_id(wallet_id=None, asset_id: str = "") -> int:
    if asset_id and get_wallet_type() == "sage":
        return SAGE_ACTIVE_CAT_WALLET_ID
    try:
        return int(wallet_id)
    except (TypeError, ValueError):
        return int(getattr(cfg, "CAT_WALLET_ID", SAGE_ACTIVE_CAT_WALLET_ID))


def sync_active_cat_wallet_id(wallet_id=None, asset_id: str = "") -> int:
    resolved_wallet_id = active_cat_wallet_id(wallet_id, asset_id)
    with _active_cat_lock:
        _active_cat["wallet_id"] = resolved_wallet_id
    if asset_id and get_wallet_type() == "sage":
        cfg.CAT_WALLET_ID = resolved_wallet_id
    return resolved_wallet_id


def _balance_snapshot_payload(balances: dict | None) -> dict:
    balances = balances or {}
    xch = balances.get("xch") or {}
    cat = balances.get("cat") or {}
    return {
        "xch": {
            "spendable": _safe_float(xch.get("spendable", 0)),
            "total": _safe_float(xch.get("total", 0)),
        },
        "cat": {
            "spendable": _safe_float(cat.get("spendable", 0)),
            "total": _safe_float(cat.get("total", 0)),
        },
    }


def _balance_side_zero(balance: dict | None) -> bool:
    balance = balance or {}
    return (
        _safe_float(balance.get("total", 0)) <= 0
        and _safe_float(balance.get("spendable", 0)) <= 0
    )


def _balance_side_nonzero(balance: dict | None) -> bool:
    balance = balance or {}
    return (
        _safe_float(balance.get("total", 0)) > 0
        or _safe_float(balance.get("spendable", 0)) > 0
    )


def _balance_snapshot_context_matches(
    snapshot: dict, *, asset_id: str = "", cat_wallet_id=None
) -> bool:
    cached_asset_id = str((snapshot or {}).get("asset_id") or "").strip().lower()
    requested_asset_id = str(asset_id or "").strip().lower()
    if requested_asset_id != cached_asset_id:
        return False
    try:
        requested_wallet_id = int(cat_wallet_id) if cat_wallet_id is not None else None
    except (TypeError, ValueError):
        requested_wallet_id = None
    cached_wallet_id = (snapshot or {}).get("cat_wallet_id")
    return not (
        requested_wallet_id is not None
        and cached_wallet_id is not None
        and requested_wallet_id != cached_wallet_id
    )


def cache_balance_snapshot(
    *,
    asset_id: str = "",
    cat_wallet_id=None,
    balances: dict | None = None,
    source: str = "",
) -> dict:
    """Remember the last wallet-verified balance for status polls.

    /api/status avoids live wallet RPCs while the bot is idle. This cache lets
    it echo an explicit balance refresh instead of overwriting the GUI with
    synthetic zeroes on the next poll.
    """
    try:
        normalized_wallet_id = int(cat_wallet_id) if cat_wallet_id is not None else None
    except (TypeError, ValueError):
        normalized_wallet_id = None
    incoming = _balance_snapshot_payload(balances)
    suspicious_zero_sides = []
    with _balance_snapshot_lock:
        previous = dict(_latest_balance_snapshot)
        merged = _balance_snapshot_payload(incoming)
        if previous and _balance_snapshot_context_matches(
            previous, asset_id=asset_id, cat_wallet_id=normalized_wallet_id
        ):
            previous_balances = _balance_snapshot_payload(
                previous.get("balances") or {}
            )
            for side in ("xch", "cat"):
                if _balance_side_zero(merged[side]) and _balance_side_nonzero(
                    previous_balances[side]
                ):
                    merged[side] = dict(previous_balances[side])
                    suspicious_zero_sides.append(side)
        snapshot = {
            "asset_id": str(asset_id or "").strip().lower(),
            "cat_wallet_id": normalized_wallet_id,
            "balances": _balance_snapshot_payload(merged),
            "source": str(source or ""),
            "updated_at": time.time(),
        }
        _latest_balance_snapshot.clear()
        _latest_balance_snapshot.update(snapshot)
        result = _balance_snapshot_payload(snapshot["balances"])

    if suspicious_zero_sides:
        try:
            slog(
                "BALANCE",
                "Ignored transient zero balance read for "
                + ", ".join(suspicious_zero_sides),
                {
                    "source": source,
                    "asset_id": snapshot["asset_id"],
                    "cat_wallet_id": normalized_wallet_id,
                },
                level="warning",
            )
        except Exception:
            logging.getLogger(__name__).debug(
                "Failed to log transient zero balance read warning",
                exc_info=True,
            )
    return result


def clear_balance_snapshot() -> None:
    with _balance_snapshot_lock:
        _latest_balance_snapshot.clear()


def get_cached_balance_snapshot(
    *, asset_id: str = "", cat_wallet_id=None
) -> dict | None:
    requested_asset_id = str(asset_id or "").strip().lower()
    try:
        requested_wallet_id = int(cat_wallet_id) if cat_wallet_id is not None else None
    except (TypeError, ValueError):
        requested_wallet_id = None
    with _balance_snapshot_lock:
        snapshot = dict(_latest_balance_snapshot)
        balances = dict(snapshot.get("balances") or {})
    if not snapshot or not balances:
        return None
    cached_asset_id = str(snapshot.get("asset_id") or "").strip().lower()
    if requested_asset_id != cached_asset_id:
        return None
    cached_wallet_id = snapshot.get("cat_wallet_id")
    if (
        requested_wallet_id is not None
        and cached_wallet_id is not None
        and requested_wallet_id != cached_wallet_id
    ):
        return None
    return _balance_snapshot_payload(balances)


def merge_cached_balance_snapshot(
    *, asset_id: str = "", cat_wallet_id=None, balances: dict | None = None
) -> dict | None:
    cached = get_cached_balance_snapshot(
        asset_id=asset_id,
        cat_wallet_id=cat_wallet_id,
    )
    if not cached:
        return None
    merged = _balance_snapshot_payload(balances)
    for side in ("xch", "cat"):
        if _balance_side_zero(merged[side]) and _balance_side_nonzero(
            cached.get(side) or {}
        ):
            merged[side] = dict(cached[side])
    return merged


# Auto-fix: Dexie ticker format is "{CAT}_XCH" e.g. "SBX_XCH" (V1 confirmed)
if _active_cat["ticker_id"] and "_" not in _active_cat["ticker_id"]:
    _active_cat["ticker_id"] = f"{_active_cat['ticker_id']}_XCH"
    cfg.update("CAT_TICKER_ID", _active_cat["ticker_id"])
print(f"[STARTUP] _active_cat initialized from .env: {_active_cat}")


# Auto-resolve CAT metadata (TIBET_PAIR_ID, CAT_TICKER_ID, CAT_NAME) at startup.
# Runs in a background thread so it doesn't block Flask startup.
# Clears TIBET_PAIR_ID first — it may belong to a previous token if the user
# switched CATs via the GUI in a prior session and then restarted. The resolver
# will fill in the correct pair for the current CAT_ASSET_ID.
def _background_cat_resolve():
    try:
        from cat_resolver import resolve_and_apply as _resolve_cat

        # Clear stale TIBET_PAIR_ID before resolving — ensures we always get
        # the pair for the currently configured CAT, not a leftover from the last session.
        cfg.update("TIBET_PAIR_ID", "")
        meta = _resolve_cat(cfg)
        if meta:
            # Keep _active_cat in sync with any newly resolved fields
            with _active_cat_lock:
                if meta.get("ticker_id") and not _active_cat.get("ticker_id"):
                    _active_cat["ticker_id"] = meta["ticker_id"]
                if meta.get("name") and (
                    not _active_cat.get("name") or _active_cat.get("name") == "MZ"
                ):
                    _active_cat["name"] = meta["name"]
            print(
                f"[STARTUP] CAT metadata resolved: pair_id={str(meta.get('pair_id') or '')[:20]}... "
                f"ticker={meta.get('ticker_id')} name={meta.get('name')}"
            )
    except Exception as e:
        print(f"[STARTUP] CAT metadata resolve failed (non-critical): {e}")


_startup_cat_resolver_thread = None
_startup_cat_resolver_lock = threading.Lock()


def _start_background_cat_resolver():
    """Start the CAT resolver only under an owned mutation permit."""

    global _startup_cat_resolver_thread
    with _startup_cat_resolver_lock:
        current = _startup_cat_resolver_thread
        if current is not None:
            try:
                if current.is_alive():
                    return current
            except Exception:
                return None
        try:
            current = start_mutation_thread(
                operation="startup:cat_metadata_resolve",
                target=_background_cat_resolve,
                name="cat-resolver",
            )
        except mutation_gate.MutationBlocked:
            return None
        _startup_cat_resolver_thread = current
        return current


# Track when the GUI log panel was last cleared.
# Events older than this timestamp are hidden from the GUI but still
# available via the debug log download (preserves full history).
# Loaded from database on startup so it survives restarts.
_logs_cleared_at = None
_session_start_time = None  # Set at app startup — logs older than this are hidden
_run_history_cutoff = None  # Set when the user explicitly starts a fresh run
if not hasattr(cfg, "RUN_HISTORY_CUTOFF"):
    cfg.RUN_HISTORY_CUTOFF = None

# Persists the user's "Start Fresh" choice across process restarts so the
# resume modal doesn't reappear.  Uses a flag file rather than memory so
# it survives the app being fully closed and reopened.
import os as _os

_FRESH_START_FLAG = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)), ".fresh_start_chosen"
)


def _fresh_start_is_set() -> bool:
    return _os.path.exists(_FRESH_START_FLAG)


def _fresh_start_set():
    try:
        open(_FRESH_START_FLAG, "w").close()
    except Exception:
        pass


def _fresh_start_clear():
    try:
        if _os.path.exists(_FRESH_START_FLAG):
            _os.remove(_FRESH_START_FLAG)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Event Bus (for SSE push to GUI)
# ---------------------------------------------------------------------------


class EventBus:
    """Simple event bus for Server-Sent Events (SSE).

    Modules call emit() to push events. Connected GUI clients
    receive them instantly via the /api/events SSE endpoint.
    """

    def __init__(self):
        self._subscribers: list = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        """Create a new subscriber queue."""
        q = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        """Remove a subscriber."""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def emit(self, event_type: str, data: dict):
        """Push an event to all subscribers."""
        msg = {"type": event_type, "data": data, "ts": time.time()}
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def alert(
        self,
        alert_id: str,
        severity: str,
        title: str,
        message: str,
        action: str = None,
        action_label: str = None,
        action_value: str = None,
    ):
        """Convenience: set a persistent alert and emit it.

        ``action_value`` is an opaque string passed to the action handler
        in the frontend (e.g. a comma-separated list of trade_ids). The
        default is ``None``; set it when the action needs a payload.
        """
        if hasattr(self, "_alert_store"):
            self._alert_store.set_alert(
                alert_id, severity, title, message, action, action_label, action_value
            )

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class AlertStore:
    """Persistent alerts that require user acknowledgment.

    Unlike the activity feed (rolling, ephemeral), alerts persist until
    the user dismisses them. Used for important state changes the user
    needs to know about: pricing strategy, position limits, side disabled, etc.
    """

    def __init__(self):
        self._alerts: Dict[str, dict] = {}  # keyed by alert_id
        self._lock = threading.Lock()

    def set_alert(
        self,
        alert_id: str,
        severity: str,
        title: str,
        message: str,
        action: str = None,
        action_label: str = None,
        action_value: str = None,
    ):
        """Create or update an alert. Severity: 'error', 'warning', 'info', 'success'.

        ``action_value`` is an opaque payload passed to the action handler
        (e.g. a comma-separated list of trade_ids). Optional.
        """
        with self._lock:
            self._alerts[alert_id] = {
                "id": alert_id,
                "severity": severity,
                "title": title,
                "message": message,
                "action": action,  # optional action ID handled client-side
                "action_label": action_label,  # button text
                "action_value": action_value,  # optional payload for the action
                "created_at": time.time(),
                "dismissed": False,
            }
        # Push to GUI via SSE
        events.emit("alert", self._alerts[alert_id])

    def dismiss(self, alert_id: str):
        """Mark an alert as dismissed."""
        with self._lock:
            if alert_id in self._alerts:
                self._alerts[alert_id]["dismissed"] = True

    def clear(self, alert_id: str):
        """Remove an alert entirely (e.g. condition resolved)."""
        with self._lock:
            self._alerts.pop(alert_id, None)
        events.emit("alert_cleared", {"id": alert_id})

    def get_active(self) -> list:
        """Get all non-dismissed alerts."""
        with self._lock:
            return [a for a in self._alerts.values() if not a["dismissed"]]


events = EventBus()
alerts = AlertStore()
# Wire alerts to event bus for accessing from bot_loop via events._alert_store
events._alert_store = alerts

# Hook log_event() to push to the live console via SSE
try:
    from database import set_log_sse_callback

    set_log_sse_callback(events.emit)
    print("  [SSE] log_event → SSE callback registered ✓", flush=True)
except Exception as e:
    print(f"  [SSE] ⚠️ Failed to register log_event callback: {e}", flush=True)


def _get_live_mid_price_str() -> Optional[str]:
    """Return the bot's current weighted mid as a decimal string, or None.

    Used to seed the coin-prep subprocess with the same price the bot trades
    against, so CAT-coin sizes align with live ladder sizes. Tries the cached
    last_price first, then a fresh fetch via get_price() if the cache is empty
    or stale (common when prep is triggered before the bot loop has started
    and no cycle has populated the cache yet).

    Returns None only when both paths fail; the worker then falls back to
    Dexie's last_price ticker, which may lag on thin markets.
    """
    try:
        pe = getattr(bot, "price_engine", None) if "bot" in globals() else None
        if pe is None:
            return None
        p = pe.get_last_price()
        if p is None or Decimal(str(p)) <= 0:
            # Cache miss — force a fresh fetch of the weighted mid so prep
            # and the bot agree on price even on first run.
            try:
                fresh = pe.get_price()
                if isinstance(fresh, dict):
                    p = fresh.get("mid_price") or fresh.get("mid") or fresh.get("price")
                else:
                    p = fresh
            except Exception:
                p = None
        if p is None:
            return None
        p_dec = Decimal(str(p))
        if p_dec <= 0:
            return None
        return format(p_dec, "f")
    except Exception:
        return None


def create_bot() -> BotLoop:
    """Create and return the bot loop instance."""
    global bot
    # Database initialization is completed by both desktop and Flask entry
    # points before this function. Acquire the lease before constructing any
    # background component that could eventually reach a wallet mutation.
    if mutation_gate.current_runtime() is None:
        initialize_mutation_runtime()
    mutation_gate.require_allowed("startup:create_bot")
    bot = BotLoop()
    bot.set_runtime_recovery_coordinator(_run_runtime_recovery)
    # Wire up event bus to bot loop for push updates
    bot._event_bus = events
    # Inject spacescan getter so SSE dashboard_update events include spacescan metrics.
    # This avoids a circular import: api_server → bot_loop is the import direction,
    # so we inject the callable after construction instead.
    bot._spacescan_context_getter = _get_spacescan_market_context
    # F74: shape-fix recovery orchestrator. Attached after the event
    # bus is wired so flows can emit SSE progress events.
    try:
        from shape_fix_orchestrator import ShapeFixOrchestrator

        bot.shape_fix_orchestrator = ShapeFixOrchestrator(bot, events)
    except Exception as _sf_err:
        # Non-fatal — dashboard simply won't have the modal experience
        print(f"  [SHAPE-FIX] ⚠️  Could not init orchestrator: {_sf_err}", flush=True)
        bot.shape_fix_orchestrator = None
    bot.runtime_monitor.start()
    # A latch may have tripped before the bot existed. Late registration
    # immediately observes it and stops the new loop before it can trade.
    runtime = mutation_gate.current_runtime()
    if runtime is not None:
        runtime.register_stop_handler(_mutation_stop_handler)
    return bot


# ---------------------------------------------------------------------------
# GUI Route
# ---------------------------------------------------------------------------


@app.after_request
def add_no_cache_headers(response):
    """Prevent browser from caching HTML and API responses.

    This fixes the 'stuck GUI after restart' problem — without these headers
    the browser serves a stale cached page that can't connect to the new server.
    """
    if response.content_type and (
        "text/html" in response.content_type
        or "application/json" in response.content_type
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # CORS — restrict to loopback origin only (prevents any webpage from reading API)
    response.headers["Access-Control-Allow-Origin"] = _cors_origin_for_request()
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Bot-Local-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    if response.content_type and "text/html" in response.content_type:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://icons.dexie.space https://*.spacescan.io https://cdn.spacescan.io https://assets.spacescan.io; "
            "connect-src 'self'; "
            "base-uri 'none'; "
            "object-src 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
    return response


@app.before_request
def enforce_local_runtime_guard():
    """Keep the control plane loopback-only and require a per-run token for writes."""
    path = request.path or ""

    if path.startswith("/api/debug/"):
        return jsonify({"error": "debug_routes_disabled"}), 404

    if (
        _read_only_diagnostics_active
        and path.startswith("/api/")
        and path != "/api/safety/status"
    ):
        return jsonify(
            {
                "success": False,
                "error": "diagnostics_read_only",
                "reason": "DIAGNOSTICS_READ_ONLY",
            }
        ), 423

    protected_pages = {"/", "/console", "/api/events"}
    if path.startswith("/api/") or path in protected_pages:
        if not _is_loopback_addr(request.remote_addr):
            if path.startswith("/api/"):
                return jsonify({"error": "loopback_only"}), 403
            return Response("Loopback only", status=403, mimetype="text/plain")

    if path == "/api/events" and not _has_valid_local_token():
        return Response("Unauthorized", status=401, mimetype="text/plain")

    if request.method in {
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    } and path.startswith("/api/"):
        if not _request_origin_matches_app():
            return jsonify({"error": "origin_not_allowed"}), 403

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith(
        "/api/"
    ):
        requires_token = path not in _TOKEN_EXEMPT_WRITE_ROUTES
        if requires_token and not _has_valid_local_token():
            return jsonify({"error": "unauthorized"}), 401
        if path not in _RATE_LIMIT_EXEMPT_WRITE_ROUTES and _is_rate_limited(path):
            return jsonify(
                {"error": "rate_limited", "message": "Too many requests"}
            ), 429

        endpoint = request.endpoint or ""
        requires_mutation = bool(
            {"POST", "PUT", "PATCH", "DELETE"}.intersection({request.method})
        ) and _write_endpoint_requires_mutation(endpoint)
        if endpoint == "bot.api_shutdown":
            try:
                requires_mutation = bool(
                    (request.get_json(silent=True) or {}).get("cancel_offers", False)
                )
            except Exception:
                requires_mutation = False
        if requires_mutation:
            _ensure_mutation_runtime()
            operation = f"api:{endpoint}"
            try:
                g._mutation_permit = mutation_gate.enter_mutation(operation)
            except mutation_gate.MutationBlocked as exc:
                return jsonify(
                    {
                        "success": False,
                        "error": "mutation_gate_blocked",
                        "reason": exc.reason_code,
                        "operation": operation,
                    }
                ), 423


@app.teardown_request
def release_local_runtime_guard(_error=None):
    """Always retire the exact in-flight permit, including exceptional routes."""

    permit = getattr(g, "_mutation_permit", None)
    if permit:
        mutation_gate.exit_mutation(permit)


@app.route("/")
def serve_gui():
    """Serve the bot GUI HTML file."""
    return _serve_bootstrapped_html("bot_gui.html")


@app.route("/api/safety/status")
def api_safety_status():
    """Return bounded, non-secret startup and live safety diagnostics."""

    try:
        return jsonify({"success": True, "safety": get_public_stability_status()})
    except Exception:
        return jsonify(
            {
                "success": False,
                "error": "safety_status_unavailable",
                "safety": {
                    "allowed": False,
                    "reason_code": "DURABLE_STATE_UNAVAILABLE",
                    "recommended_action": "RESTORE_DATABASE_BACKUP",
                },
            }
        ), 503


def _quarantine_runtime_request(payload: Any) -> dict:
    """Validate a bounded operator CAS and archive server-derived evidence."""

    if type(payload) is not dict:
        return {"success": False, "reason_code": "QUARANTINE_REQUEST_MALFORMED"}
    required = {
        "confirmation",
        "quarantine_id",
        "blocker_ids",
        "expected_latch_generation",
        "expected_recovery_id",
    }
    if set(payload) != required or type(payload.get("confirmation")) is not bool:
        return {"success": False, "reason_code": "QUARANTINE_REQUEST_MALFORMED"}
    if payload["confirmation"] is not True:
        return {"success": False, "reason_code": "QUARANTINE_CONFIRMATION_REQUIRED"}
    try:
        epoch = database.get_runtime_recovery_epoch(payload["expected_recovery_id"])
        if type(epoch) is not dict:
            return {"success": False, "reason_code": "RECOVERY_EPOCH_NOT_CURRENT"}
        archived = database.quarantine_runtime_blockers(
            confirmation=payload["confirmation"],
            quarantine_id=payload["quarantine_id"],
            blocker_ids=payload["blocker_ids"],
            expected_latch_generation=payload["expected_latch_generation"],
            expected_recovery_id=payload["expected_recovery_id"],
            owner_run_id=epoch["owner_run_id"],
            wallet_fingerprint_hash=epoch["wallet_fingerprint_hash"],
            network=epoch["network"],
            quarantined_at=datetime.now(timezone.utc),
        )
        return {
            "success": True,
            "quarantine_id": archived["quarantine_id"],
            "reason_code": "QUARANTINE_ARCHIVED_MUTATION_BLOCKED",
            "manifest_sha256": archived["manifest_sha256"],
        }
    except (TypeError, ValueError):
        return {"success": False, "reason_code": "QUARANTINE_AUTHORITY_CONFLICT"}
    except Exception:
        return {"success": False, "reason_code": "DURABLE_STATE_UNAVAILABLE"}


@app.route("/api/safety/quarantine", methods=["POST"])
def api_safety_quarantine():
    """Archive one exact recovery epoch without restoring mutation."""

    result = _quarantine_runtime_request(request.get_json(silent=True))
    return jsonify(result), (200 if result.get("success") is True else 409)


@app.route("/api/safety/quarantine/<quarantine_id>")
def api_safety_quarantine_status(quarantine_id: str):
    """Return bounded, redacted quarantine status."""

    try:
        row = database.get_runtime_quarantine_manifest(quarantine_id)
        if row is None:
            return jsonify(
                {"success": False, "reason_code": "QUARANTINE_NOT_FOUND"}
            ), 404
        return jsonify(
            {
                "success": True,
                "quarantine": {
                    "quarantine_id": row["quarantine_id"],
                    "recovery_id": row["recovery_id"],
                    "latch_generation": int(row["latch_generation"]),
                    "manifest_sha256": row["manifest_sha256"],
                    "quarantined_at": row["quarantined_at"],
                    "mutation_blocked": True,
                },
            }
        )
    except (TypeError, ValueError):
        return jsonify(
            {"success": False, "reason_code": "QUARANTINE_REQUEST_MALFORMED"}
        ), 400
    except Exception:
        return jsonify(
            {"success": False, "reason_code": "DURABLE_STATE_UNAVAILABLE"}
        ), 503


def _collect_quarantine_resolution_proof(requirements: dict) -> dict:
    """Collect fresh Task 9 evidence through wallet.py-backed read-only loaders."""

    from offer_reconciliation import load_authoritative_evidence

    absent_offer_ids: list[str] = []
    coins_by_id: dict[str, dict] = {}
    observed_at = None
    complete = True
    for offer in requirements.get("offers", []):
        evidence = load_authoritative_evidence(offer["intent"])
        if (
            type(evidence) is not dict
            or evidence.get("wallet_fingerprint_hash")
            != requirements["wallet_fingerprint_hash"]
            or evidence.get("network") != requirements["network"]
        ):
            complete = False
            continue
        history = evidence.get("offer_history")
        transactions = evidence.get("transaction_history")
        coin_records = evidence.get("coin_records")
        identity = evidence.get("wallet_identity")
        if any(
            type(section) is not dict or section.get("complete") is not True
            for section in (history, transactions, coin_records, identity)
        ):
            complete = False
            continue
        records = history.get("records")
        if type(records) is not list:
            complete = False
            continue
        trade_id = offer["trade_id"]
        if any(
            type(row) is dict
            and str(row.get("trade_id") or row.get("offer_id") or "").lower()
            == trade_id.lower()
            for row in records
        ):
            complete = False
        else:
            absent_offer_ids.append(trade_id)
        raw_coins = coin_records.get("records")
        if type(raw_coins) is not dict:
            complete = False
            continue
        for coin_id in offer["selected_coin_ids"]:
            row = raw_coins.get(coin_id)
            if type(row) is not dict:
                complete = False
                continue
            owned = row.get("owned") is True
            unlocked = (
                row.get("spent_height") in (None, 0)
                and row.get("locked") is not True
                and not row.get("offer_id")
            )
            candidate = {"coin_id": coin_id, "owned": owned, "unlocked": unlocked}
            if coin_id in coins_by_id and coins_by_id[coin_id] != candidate:
                complete = False
            coins_by_id[coin_id] = candidate
        candidate_observed = evidence.get("observed_at")
        if type(candidate_observed) is str and (
            observed_at is None or candidate_observed > observed_at
        ):
            observed_at = candidate_observed
    if not requirements.get("offers"):
        observed_at = datetime.now(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    return {
        "version": 1,
        "quarantine_id": requirements["quarantine_id"],
        "recovery_id": requirements["recovery_id"],
        "latch_generation": requirements["latch_generation"],
        "wallet_fingerprint_hash": requirements["wallet_fingerprint_hash"],
        "network": requirements["network"],
        "authority_digest": requirements["authority_digest"],
        "observed_at": observed_at,
        "history_complete": complete,
        "absent_offer_ids": sorted(absent_offer_ids),
        "coins": [coins_by_id[key] for key in sorted(coins_by_id)],
    }


def _resolve_runtime_quarantine_request(payload: Any) -> dict:
    """Resolve from fresh server-collected evidence, never request booleans."""

    required = {
        "confirmation",
        "quarantine_id",
        "expected_recovery_id",
        "expected_latch_generation",
    }
    if type(payload) is not dict or set(payload) != required:
        return {"success": False, "reason_code": "QUARANTINE_REQUEST_MALFORMED"}
    if type(payload.get("confirmation")) is not bool or payload["confirmation"] is not True:
        return {"success": False, "reason_code": "QUARANTINE_CONFIRMATION_REQUIRED"}
    try:
        requirements = database.get_runtime_quarantine_resolution_requirements(
            payload["quarantine_id"]
        )
        if (
            requirements["recovery_id"] != payload["expected_recovery_id"]
            or requirements["latch_generation"]
            != payload["expected_latch_generation"]
        ):
            return {"success": False, "reason_code": "RECOVERY_EPOCH_NOT_CURRENT"}
        proof = _collect_quarantine_resolution_proof(requirements)
        from runtime_recovery import validate_quarantine_resolution_proof

        decision = validate_quarantine_resolution_proof(
            requirements,
            proof,
            now=datetime.now(timezone.utc),
            maximum_age_seconds=30,
        )
        if decision.get("allowed") is not True:
            return {"success": False, "reason_code": decision["reason_code"]}
        epoch = database.get_runtime_recovery_epoch(requirements["recovery_id"])
        if type(epoch) is not dict:
            return {"success": False, "reason_code": "RECOVERY_EPOCH_NOT_CURRENT"}
        result = database.resolve_runtime_quarantine(
            quarantine_id=requirements["quarantine_id"],
            expected_recovery_id=requirements["recovery_id"],
            expected_latch_generation=requirements["latch_generation"],
            expected_owner_run_id=epoch["owner_run_id"],
            proof_decision=decision,
            resolved_at=datetime.now(timezone.utc),
        )
        return {
            "success": True,
            "quarantine_id": requirements["quarantine_id"],
            "reason_code": "QUARANTINE_PROOF_ARCHIVED_RECOVERY_REQUIRED",
            "proof_sha256": result["record"]["proof_sha256"],
            "mutation_blocked": True,
        }
    except (TypeError, ValueError):
        return {"success": False, "reason_code": "QUARANTINE_RESOLUTION_BLOCKED"}
    except Exception:
        return {"success": False, "reason_code": "DURABLE_STATE_UNAVAILABLE"}


@app.route("/api/safety/quarantine/resolve", methods=["POST"])
def api_safety_quarantine_resolve():
    result = _resolve_runtime_quarantine_request(request.get_json(silent=True))
    return jsonify(result), (200 if result.get("success") is True else 409)


@app.route("/console")
def serve_console():
    """Legacy console page removed; keep a safe 404 instead of a missing file."""
    return Response("Console page removed", status=404, mimetype="text/plain")


@app.route("/brand/<path:filename>")
@app.route("/assets/<path:filename>")
def serve_brand_asset(filename: str):
    """Serve brand assets used by the GUI from the assets/ folder."""
    gui_dir = _APP_ROOT
    assets_dir = os.path.join(gui_dir, "assets")
    allowed = {
        "bot_icon_new.png": "bot_icon_new.png",
        "favicon.ico": "favicon.ico",
        "sage_logo_official.png": "sage_logo_official.png",
        "dexie_logo_official.png": "dexie_logo_official.png",
        "dexie_logo_official.ico": "dexie_logo_official.ico",
        "tibetswap_logo_official.png": "tibetswap_logo_official.png",
        "MonkeyZoo_Logo.png": "MonkeyZoo_Logo.png",
        "monkeyzoo-logo-1.gif": "monkeyzoo-logo-1.gif",
        "spacescan-logo-192.webp": "spacescan-logo-192.webp",
        "sage_rpc_advanced.png": "sage_rpc_advanced.png",
    }
    safe_name = allowed.get(filename)
    if safe_name is None:
        return Response("Not Found", status=404, mimetype="text/plain")
    # Try assets/ folder first, fall back to app root for backward compat
    if os.path.isfile(os.path.join(assets_dir, safe_name)):
        return send_from_directory(assets_dir, safe_name)
    return send_from_directory(gui_dir, safe_name)


def _get_session_pending_verification_count() -> int:
    """Count unverified closures in the current bot session."""
    if not bot or not getattr(bot, "_start_time", 0):
        return 0
    try:
        since_iso = datetime.fromtimestamp(bot._start_time, timezone.utc).isoformat()
        row = (
            get_connection()
            .execute(
                """SELECT COUNT(*) as cnt
               FROM events
               WHERE event_type='offer_closed_unverified'
                 AND timestamp >= ?""",
                (since_iso,),
            )
            .fetchone()
        )
        return int((row["cnt"] if row else 0) or 0)
    except Exception:
        return 0


def _get_run_history_cutoff() -> str:
    """Return the current fresh-run history cutoff, if one exists."""
    return _run_history_cutoff or getattr(cfg, "RUN_HISTORY_CUTOFF", None)


def _restore_run_history_cutoff_from_events() -> str:
    """Restore the latest fresh-run cutoff from persisted events.

    Fresh-run resets are logged into the events table, so we can recover the
    most recent cutoff after an app restart and keep history/PnL scoped to the
    current run instead of reverting to lifetime stats.
    """
    global _run_history_cutoff
    try:
        row = (
            get_connection()
            .execute(
                """SELECT timestamp
               FROM events
               WHERE event_type IN ('session_fresh_start', 'fresh_start_cleanup')
               ORDER BY id DESC
               LIMIT 1"""
            )
            .fetchone()
        )
        cutoff = str((row["timestamp"] if row else "") or "").strip()
        _run_history_cutoff = cutoff or None
        cfg.RUN_HISTORY_CUTOFF = _run_history_cutoff
        return _run_history_cutoff
    except Exception:
        return None


def _reset_runtime_session_stats() -> Dict:
    """Reset in-memory per-run stats for a new bot/session start."""
    reset_summary = {
        "market_intel_reset": False,
        "splash_reset": False,
        "splash_incoming_cleared": 0,
    }

    try:
        from database import clear_splash_incoming

        reset_summary["splash_incoming_cleared"] = int(clear_splash_incoming() or 0)
    except Exception:
        reset_summary["splash_incoming_cleared"] = 0

    if not bot:
        return reset_summary

    try:
        if getattr(bot, "market_intel", None):
            bot.market_intel.reset_session_stats()
            reset_summary["market_intel_reset"] = True
    except Exception:
        reset_summary["market_intel_reset"] = False

    try:
        if getattr(bot, "splash_manager", None):
            bot.splash_manager.reset_session_stats()
            reset_summary["splash_reset"] = True
    except Exception:
        reset_summary["splash_reset"] = False

    try:
        events.emit("splash_incoming", bot.get_splash_receive_stats())
    except Exception:
        pass

    return reset_summary


def _reset_fresh_run_runtime_memory() -> list[str]:
    """Clear in-memory state that should not survive a full fresh reset."""
    reset_components: list[str] = []

    def note_reset_failure(component: str, exc: Exception) -> None:
        slog(
            "RESET",
            f"Fresh-run reset skipped {component}: {exc}",
            level="debug",
        )

    if bot:
        try:
            if bot.is_running():
                return ["bot_runtime_skipped_running"]
        except Exception as exc:
            note_reset_failure("bot.is_running", exc)

    try:
        from sweep_coordinator import reset_coordinator

        reset_coordinator()
        reset_components.append("sweep_coordinator")
    except Exception as exc:
        note_reset_failure("sweep_coordinator", exc)

    try:
        from dynamic_amm_buffer import reset_buffer

        reset_buffer()
        reset_components.append("dynamic_amm_buffer")
    except Exception as exc:
        note_reset_failure("dynamic_amm_buffer", exc)

    if not bot:
        return reset_components

    try:
        sweep_protection = getattr(bot, "_sweep_protection", None)
        if isinstance(sweep_protection, dict):
            sweep_protection.clear()
        else:
            setattr(bot, "_sweep_protection", {})
        reset_components.append("bot.sweep_protection")
    except Exception as exc:
        note_reset_failure("bot.sweep_protection", exc)

    try:
        recent_sweeps = getattr(bot, "_recent_sweep_events", None)
        if isinstance(recent_sweeps, list):
            recent_sweeps.clear()
        else:
            setattr(bot, "_recent_sweep_events", [])
        reset_components.append("bot.recent_sweep_events")
    except Exception as exc:
        note_reset_failure("bot.recent_sweep_events", exc)

    try:
        setattr(
            bot,
            "_last_toxicity_live_cancel",
            {
                "buy": {"at": 0.0, "signature": ""},
                "sell": {"at": 0.0, "signature": ""},
            },
        )
        reset_components.append("bot.toxicity_live_cancel")
    except Exception as exc:
        note_reset_failure("bot.toxicity_live_cancel", exc)

    try:
        guard = getattr(bot, "market_toxicity_guard", None)
        if guard is not None and hasattr(guard, "reset"):
            guard.reset()
            reset_components.append("market_toxicity_guard")
    except Exception as exc:
        note_reset_failure("market_toxicity_guard", exc)

    try:
        risk_manager = getattr(bot, "risk_manager", None)
        if risk_manager is not None and hasattr(risk_manager, "reset_session"):
            risk_manager.reset_session()
            reset_components.append("risk_manager.session")
        elif risk_manager is not None and hasattr(risk_manager, "reset_position"):
            risk_manager.reset_position()
            reset_components.append("risk_manager.position")
    except Exception as exc:
        note_reset_failure("risk_manager", exc)

    try:
        sniper = getattr(bot, "sniper", None)
        if sniper is not None:
            with getattr(sniper, "_snipe_lock", _SNIPE_LOCK_NOOP):
                sniper._total_snipes = 0
                sniper._total_skipped = 0
                if hasattr(sniper, "_snipe_history"):
                    sniper._snipe_history.clear()
                if hasattr(sniper, "_active_snipe_ids"):
                    sniper._active_snipe_ids.clear()
                sniper._last_snipe_time = 0
            reset_components.append("sniper.counters")
    except Exception as exc:
        note_reset_failure("sniper.counters", exc)

    try:
        fill_tracker = getattr(bot, "fill_tracker", None)
        if fill_tracker is not None:
            if hasattr(fill_tracker, "_mass_disappearance_count"):
                fill_tracker._mass_disappearance_count = 0
            if hasattr(fill_tracker, "_mass_disappearance_first_at"):
                fill_tracker._mass_disappearance_first_at = None
            reset_components.append("fill_tracker.counters")
    except Exception as exc:
        note_reset_failure("fill_tracker.counters", exc)

    try:
        watchdog_streaks = getattr(bot, "_watchdog_violation_streaks", None)
        if isinstance(watchdog_streaks, dict):
            watchdog_streaks.clear()
            reset_components.append("watchdog.streaks")
    except Exception as exc:
        note_reset_failure("watchdog.streaks", exc)

    return reset_components


def _reset_fresh_run_session(
    clear_coins: bool = False,
    clear_price_history: bool = False,
    clear_inventory: bool = False,
    cancel_open_offers: bool = False,
    preserve_history: bool = False,
    reason: str = "fresh_start",
) -> Dict:
    """Reset session-facing bot state.

    Two request modes are retained for client compatibility:

    * ``preserve_history=False`` (default / legacy / "Start Fresh"):
        Requests the broad legacy reset. The database guard refuses the
        operation without mutation whenever authoritative fills, protected
        offers, intents, or reservations exist; proof and fill history are
        never deleted. Empty legacy state remains reset-compatible.

    * ``preserve_history=True`` (coin-prep re-run):
        Keeps the fills / round-trips tables and the position baseline.
        Coin prep can still request coin and offer cleanup, but the same
        authority guard preserves every protected row and lock. This is the
        default Prepare Coins flow.
    """
    global _run_history_cutoff, _session_start_time

    from database import _sqlite_ts, guarded_reset_authoritative_state

    reset_at = _sqlite_ts(datetime.now(timezone.utc))
    summary = {
        "success": True,
        "reset_at": reset_at,
        "preserve_history": bool(preserve_history),
        "fills_cleared": 0,
        "round_trips_cleared": 0,
        "coins_cleared": 0,
        "open_offers_cancelled": 0,
        "price_history_cleared": False,
        "inventory_cleared": False,
    }

    db_summary = guarded_reset_authoritative_state(
        clear_fills=not preserve_history,
        clear_round_trips=not preserve_history,
        clear_coins=clear_coins,
        cancel_open_offers=cancel_open_offers,
        clear_price_history=clear_price_history,
        clear_inventory=clear_inventory,
    )
    summary.update(db_summary)
    if not summary["success"]:
        summary["reset_at"] = reset_at
        summary["preserve_history"] = bool(preserve_history)
        return summary

    if not preserve_history:
        # Advance the run-history cutoff so dashboard queries (/api/logs,
        # offer history, etc.) stop surfacing pre-reset entries. Under
        # preserve-history mode we keep the existing cutoff so the user's
        # own history stays visible after a coin-prep re-run.
        _run_history_cutoff = reset_at
        cfg.RUN_HISTORY_CUTOFF = reset_at
        _session_start_time = reset_at

    if not preserve_history and bot and getattr(bot, "risk_manager", None):
        # Only zero the position baseline on a full reset. A coin-prep
        # re-run doesn't change the on-chain position, so the accumulated
        # net_position_cat must remain intact (otherwise the next cycle
        # believes it's starting from zero and will happily rebuild
        # exposure past MAX_POSITION_XCH).
        try:
            bot.risk_manager.reset_position()
        except Exception:
            pass

    if not preserve_history:
        stats_reset = _reset_runtime_session_stats()
        summary.update(stats_reset)
        summary["runtime_memory_reset"] = _reset_fresh_run_runtime_memory()
    else:
        # Always drain Splash incoming (those offers reference the old
        # coin IDs) but DON'T reset market_intel / splash session stats
        # under preserve_history.
        try:
            from database import clear_splash_incoming

            summary["splash_incoming_cleared"] = int(clear_splash_incoming() or 0)
        except Exception:
            summary["splash_incoming_cleared"] = 0

    if reason:
        if preserve_history:
            details = (
                f"Coin-prep re-run at {reset_at}: preserved fills / round-trips / "
                f"position baseline, cleared {summary['coins_cleared']} coin rows"
            )
            if cancel_open_offers:
                details += f", cancelled {summary['open_offers_cancelled']} open offers"
        else:
            details = (
                f"Fresh run reset at {reset_at}: cleared {summary['fills_cleared']} fills, "
                f"{summary['round_trips_cleared']} round-trips, "
                f"{summary.get('splash_incoming_cleared', 0)} Splash incoming offers"
            )
            if clear_coins:
                details += f", {summary['coins_cleared']} coins"
            if cancel_open_offers:
                details += f", cancelled {summary['open_offers_cancelled']} open offers"
        log_event("info", reason, details)

    return summary


@app.route("/favicon.ico")
def favicon():
    gui_dir = _APP_ROOT
    assets_dir = os.path.join(gui_dir, "assets")
    # Try assets/ first, then app root for backward compat
    for d in (assets_dir, gui_dir):
        if os.path.isfile(os.path.join(d, "favicon.ico")):
            return send_from_directory(d, "favicon.ico")
        if os.path.isfile(os.path.join(d, "bot_icon_new.ico")):
            return send_from_directory(d, "bot_icon_new.ico")
    return Response(status=404)


def _is_allowed_external_url(raw_url: str) -> bool:
    """Allow only absolute http/https URLs for desktop external-link opens."""
    try:
        parsed = urlparse(str(raw_url or "").strip())
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_loopback_origin(raw_origin: str) -> bool:
    """Return True when an Origin header points at this local machine."""
    try:
        parsed = urlparse(str(raw_origin or "").strip())
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and _is_loopback_addr(parsed.hostname)


def _cors_origin_for_request() -> str:
    """Reflect loopback browser origins, otherwise use the configured default."""
    origin = request.headers.get("Origin", "")
    if origin and _is_loopback_origin(origin):
        return origin
    try:
        port = int(os.environ.get("CATALYST_FLASK_PORT", "5000"))
    except (TypeError, ValueError):
        port = 5000
    return f"http://127.0.0.1:{port}"


def _launch_external_url(raw_url: str) -> bool:
    """Best-effort launch in the OS default browser without touching bot state."""
    url = str(raw_url or "").strip()
    if not _is_allowed_external_url(url):
        return False
    try:
        return webbrowser.open(url, new=2)
    except Exception:
        return False


@app.route("/api/open-external", methods=["POST"])
def api_open_external():
    """Open a vetted external URL in the user's default browser.

    POST-only to prevent CSRF via cross-origin GET from any webpage.
    Requires the per-run local token (enforced by before_request).
    """
    if not _is_loopback_addr(request.remote_addr):
        return jsonify({"success": False, "error": "loopback_only"}), 403

    payload = request.get_json(silent=True)
    raw_url = (payload or {}).get("url") if isinstance(payload, dict) else None
    url = str(raw_url or "").strip()

    if not _is_allowed_external_url(url):
        return jsonify(
            {"success": False, "error": "Only absolute http/https URLs are allowed"}
        ), 400

    if not _launch_external_url(url):
        return jsonify(
            {"success": False, "error": "Could not open URL in the default browser"}
        ), 500

    return jsonify({"success": True, "url": url})


@app.route("/api/open-data-folder", methods=["POST"])
def api_open_data_folder():
    """Reveal the per-user data directory in the OS file manager.

    Useful for support: users can click this button and then attach
    crash.log / bot.db / bot_superlog_*.log to a bug report.
    Loopback only and POST-only to prevent CSRF.
    """
    if not _is_loopback_addr(request.remote_addr):
        return jsonify({"success": False, "error": "loopback_only"}), 403

    try:
        from user_paths import data_dir as _dd

        folder = _dd()
    except Exception as e:
        log_event("error", "open_data_folder_data_dir_unavailable", str(e))
        return jsonify({"success": False, "error": "data_dir_unavailable"}), 500

    if not os.path.isdir(folder):
        return jsonify(
            {"success": False, "error": f"data dir does not exist: {folder}"}
        ), 500

    try:
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess as _sp

            _sp.Popen(["open", folder])
        else:
            import subprocess as _sp

            _sp.Popen(["xdg-open", folder])
    except Exception as e:
        log_event("error", "open_data_folder_failed", str(e))
        return jsonify({"success": False, "error": "open_folder_failed"}), 500

    return jsonify({"success": True, "folder": folder})


@app.route("/api/crash-log", methods=["GET"])
def api_crash_log():
    """Return the most recent crash.log contents (truncated) so the GUI
    can show users why the app failed last time, with a button to copy
    or email it to support.

    Loopback only. Returns a bounded amount of text (256 KiB) and never
    follows symlinks.
    """
    if not _is_loopback_addr(request.remote_addr):
        return jsonify({"success": False, "error": "loopback_only"}), 403

    try:
        from user_paths import crash_log_file, data_dir as _dd

        path = crash_log_file()
        data_folder = _dd()
    except Exception as e:
        log_event("error", "crash_log_data_dir_unavailable", str(e))
        return jsonify({"success": False, "error": "data_dir_unavailable"}), 500

    if not os.path.isfile(path):
        return jsonify(
            {
                "success": True,
                "exists": False,
                "path": path,
                "folder": data_folder,
                "content": "",
                "size": 0,
            }
        )

    try:
        st = os.stat(path)
    except OSError as e:
        log_event("error", "crash_log_stat_failed", str(e))
        return jsonify({"success": False, "error": "crash_log_stat_failed"}), 500

    MAX_BYTES = 256 * 1024  # 256 KiB cap — plenty for a traceback
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if st.st_size > MAX_BYTES:
                fh.seek(st.st_size - MAX_BYTES)
                content = "[... truncated — older content omitted ...]\n" + fh.read()
            else:
                content = fh.read()
    except OSError as e:
        log_event("error", "crash_log_read_failed", str(e))
        return jsonify({"success": False, "error": "crash_log_read_failed"}), 500

    return jsonify(
        {
            "success": True,
            "exists": True,
            "path": path,
            "folder": data_folder,
            "content": content,
            "size": st.st_size,
            "mtime": st.st_mtime,
        }
    )


# ---------------------------------------------------------------------------
# Version check against the signed public update manifest
# ---------------------------------------------------------------------------
#
# The updater pins the manifest source to the official CATalyst public release
# channel. UPDATE_MANIFEST_URL is read for deployment flexibility, but
# app_update rejects any value outside that exact public manifest path.


@app.route("/api/check-update", methods=["GET"])
def api_check_update():
    """Check whether a newer release is published on GitHub.

    Returns:
        {
            "success": True,
            "enabled": True/False,
            "current": "4.0.0",
            "latest": "4.1.0" | None,
            "update_available": True/False,
            "url": "https://github.com/.../releases/tag/v4.1.0" | None,
            "checked_at": <unix ts>,
        }

    Loopback only. Silently caches for 6 hours. Never blocks the GUI —
    network failures return `update_available: False` so the banner
    stays hidden.
    """
    if not _is_loopback_addr(request.remote_addr):
        return jsonify({"success": False, "error": "loopback_only"}), 403

    try:
        import app_update

        force_refresh = str(request.args.get("force", "") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        result = app_update.public_update_info(
            app_update.get_update_info(
                get_app_version(),
                str(os.environ.get("UPDATE_MANIFEST_URL", "") or ""),
                force=force_refresh,
            )
        )
    except Exception as e:
        log_event("info", "update_check_failed", f"{e}")
        result = {
            "success": True,
            "enabled": False,
            "current": get_app_version(),
            "latest": None,
            "update_available": False,
            "installer_ready": False,
            "manifest_verified": False,
            "url": None,
            "release_notes": "",
            "error": "Update check failed",
            "checked_at": time.time(),
        }
    result["platform"] = sys.platform
    if sys.platform != "win32":
        result["installer_ready"] = False
        result["installer_name"] = None
        result["installer_size"] = None
        result["checksum_name"] = None
        result["automatic_update_supported"] = False
        result["security"] = (
            "Automatic upgrade is available on Windows only. On Linux and macOS, "
            "open the release page and download the latest package manually."
        )
    else:
        result["automatic_update_supported"] = True
    return jsonify(result)


@app.route("/api/update/status", methods=["GET"])
def api_update_status():
    """Return current secure updater progress."""
    if not _is_loopback_addr(request.remote_addr):
        return jsonify({"success": False, "error": "loopback_only"}), 403
    try:
        import app_update

        status = app_update.get_update_status()
        status["success"] = True
        return jsonify(status)
    except Exception:
        return _api_exception(request.path)


@app.route("/api/update/install", methods=["POST"])
def api_update_install():
    """Start verified Windows installer download and launch.

    Requires the write token via before_request. If the bot is currently
    running, the updater records a one-shot relaunch intent so the restarted
    app can resume managing the existing live offers after the installer exits.
    """
    if not _is_loopback_addr(request.remote_addr):
        return jsonify({"success": False, "error": "loopback_only"}), 403

    bot_was_running = False
    try:
        bot_was_running = bool(bot and bot.is_running())
    except Exception:
        bot_was_running = True

    try:
        import app_update

        result = app_update.start_update_install(
            get_app_version(),
            str(os.environ.get("UPDATE_MANIFEST_URL", "") or ""),
            relaunch_intent={
                "auto_start_bot": bot_was_running,
                "resume_existing_offers": True,
                "cancel_offers": False,
            },
        )
        if result.get("success"):
            result["restart_bot_after_update"] = bot_was_running
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code
    except Exception:
        return _api_exception(request.path)


@app.route("/api/update/relaunch-intent", methods=["GET", "POST", "DELETE"])
def api_update_relaunch_intent():
    """Return or clear the one-shot post-update relaunch intent."""
    if not _is_loopback_addr(request.remote_addr):
        return jsonify({"success": False, "error": "loopback_only"}), 403

    try:
        import app_update

        if request.method == "GET":
            return jsonify(
                {
                    "success": True,
                    "intent": app_update.get_update_relaunch_intent(),
                }
            )

        app_update.clear_update_relaunch_intent()
        return jsonify({"success": True})
    except Exception:
        return _api_exception(request.path)


# ---------------------------------------------------------------------------
# Sage wallet release check (backend proxy for the startup version card)
# ---------------------------------------------------------------------------
#
# The startup flow used to hit api.github.com directly from JavaScript to
# see if the installed Sage is out of date. That works inside WebView2 on
# Windows but fails with "Failed to fetch" in a plain browser because of
# CORS on local-origin requests. Proxying through Flask removes the CORS
# surface entirely, lets the same HTML run in dev mode without errors,
# and gives us one place to cache + rate-limit the call.

_SAGE_RELEASE_CACHE: dict = {"at": 0.0, "data": None}
_SAGE_RELEASE_TTL = 6 * 3600  # 6 hours — GitHub's unauth rate limit is 60/hr


@app.route("/api/sage/latest-release", methods=["GET"])
def api_sage_latest_release():
    """Return the latest Sage release tag from GitHub, cached 6 hours.

    Response:
        {"success": True, "tag": "0.12.10", "url": "https://..."}
        {"success": False, "error": "..."} on failure (non-fatal for GUI)

    Loopback only. Never raises to the caller — network failures return
    success=False so the startup flow can skip the update card quietly.
    """
    if not _is_loopback_addr(request.remote_addr):
        return jsonify({"success": False, "error": "loopback_only"}), 403

    now = time.time()
    cached = _SAGE_RELEASE_CACHE.get("data")
    cached_at = float(_SAGE_RELEASE_CACHE.get("at") or 0)
    if cached and (now - cached_at) < _SAGE_RELEASE_TTL:
        return jsonify(cached)

    try:
        import requests as _req

        try:
            from api_call_tracker import record as _t

            _t("github", "/repos/xch-dev/sage/releases/latest")
        except Exception:
            pass
        r = _req.get(
            "https://api.github.com/repos/xch-dev/sage/releases/latest",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "CATalyst/sage-version-check",
            },
            timeout=6,
        )
        if r.status_code != 200:
            result = {"success": False, "error": f"github_http_{r.status_code}"}
        else:
            j = r.json()
            tag = str(j.get("tag_name") or "").lstrip("vV").strip()
            url = str(j.get("html_url") or "").strip() or None
            if not tag:
                result = {"success": False, "error": "no_tag_in_response"}
            else:
                result = {"success": True, "tag": tag, "url": url}
    except Exception as e:
        # Network error, timeout, DNS, etc. — non-fatal
        log_event("warning", "sage_latest_release_fetch_failed", str(e))
        result = {"success": False, "error": "fetch_failed"}

    _SAGE_RELEASE_CACHE["at"] = now
    _SAGE_RELEASE_CACHE["data"] = result
    return jsonify(result)


# ---------------------------------------------------------------------------
# SSE (Server-Sent Events) — Real-time push to GUI
# ---------------------------------------------------------------------------

# api_events moved to blueprint


# ---------------------------------------------------------------------------
# Bot Control Routes
# ---------------------------------------------------------------------------

# api_bot_start moved to blueprint


# api_bot_stop moved to blueprint


# api_shutdown moved to blueprint


# api_bot_state moved to blueprint


def _health_consecutive_failures(raw_health: dict) -> int:
    """Count a live health probe as failed when wallet or node is unreachable."""
    if not isinstance(raw_health, dict):
        return 1
    existing = raw_health.get("consecutive_failures")
    if existing is not None:
        try:
            return max(0, int(existing))
        except (TypeError, ValueError):
            pass
    if raw_health.get("healthy") is True:
        return 0
    wallet = raw_health.get("wallet") or {}
    node = raw_health.get("node") or {}
    wallet_bad = wallet.get("reachable") is False
    node_bad = node.get("reachable") is False
    status_bad = str(raw_health.get("status", "")).lower() in {
        "unreachable",
        "rpc_failed",
        "error",
        "unknown",
    }
    return 1 if wallet_bad or node_bad or status_bad else 0


def _get_health_snapshot() -> dict:
    """Quick health check for /api/status when bot hasn't started yet."""
    import chia_node

    if not chia_node.is_startup_authorised():
        return {"status": "not_started", "consecutive_failures": 0}
    try:
        from wallet import get_chia_health

        h = get_chia_health()
        wallet = h.get("wallet", {}) or {}
        node = h.get("node", {}) or {}
        return {
            "status": h.get("status", "unknown"),
            "wallet_reachable": wallet.get("reachable", False),
            "wallet_synced": wallet.get("synced", False),
            "wallet_syncing": wallet.get("syncing", False),
            "wallet_sync_state": wallet.get("sync_state", "unknown"),
            "node_reachable": node.get("reachable", False),
            "node_synced": node.get("synced", False),
            "consecutive_failures": _health_consecutive_failures(h),
            "last_check": time.time(),
        }
    except Exception:
        return {"status": "unknown", "consecutive_failures": 1}


# api_status moved to blueprint


def _build_liquidity_status_block(raw_status: dict) -> dict:
    """Build the ``liquidity`` payload for /api/status.

    Returns::

        {
          "mode": "two_sided" | "buy_only" | "sell_only",
          "active_side": "both" | "buy" | "sell",
          "parked": bool,
          "parked_reason": str | None,      # short code for the banner
          "parked_message": str | None,     # user-visible detail
        }

    Parked = the active side can't fund another offer. In buy_only that's
    "XCH balance below the smallest buy tier size"; in sell_only that's
    "CAT balance below the smallest sell tier size". Two-sided never
    parks (the bot's existing inventory logic handles exhaustion
    differently).
    """
    block = {
        "mode": (getattr(cfg, "LIQUIDITY_MODE", "two_sided") or "two_sided").lower(),
        "active_side": "both",
        "parked": False,
        "parked_reason": None,
        "parked_message": None,
    }
    if block["mode"] not in ("two_sided", "buy_only", "sell_only"):
        block["mode"] = "two_sided"
    try:
        block["active_side"] = cfg.active_side()
    except Exception:
        pass
    if block["mode"] == "two_sided":
        return block

    try:
        _offers = raw_status.get("offers") or {}
        _coin_tracking = raw_status.get("coin_tracking") or {}
        if block["mode"] == "buy_only":
            _live_buys = _offers.get("buy") or []
            _xch_free_count = int(_coin_tracking.get("xch_free", 0) or 0)
            if _live_buys or _xch_free_count > 1:
                return block
        elif block["mode"] == "sell_only":
            _live_sells = _offers.get("sell") or []
            _cat_free_count = int(_coin_tracking.get("cat_free", 0) or 0)
            if _live_sells or _cat_free_count > 1:
                return block
    except Exception:
        pass

    # Compute parked-state for the single-sided modes. We use "smallest
    # prep tier size" as the floor — if the wallet can't cover even one
    # offer at the smallest tier (with a 10% headroom margin) there's
    # nothing useful to do and the bot is effectively parked.
    try:
        _bal = raw_status.get("balances") or {}
        if block["mode"] == "buy_only":
            xch_avail = float(_bal.get("xch", {}).get("spendable") or 0)
            # Smallest buy-side offer size — prefer per-side fields,
            # fall back to shared legacy. Under reverse-buy the smallest
            # position size is still the inner POSITION (not bucket).
            try:
                from config import get_buy_tier_size_xch

                _sizes = [
                    float(get_buy_tier_size_xch(t) or 0)
                    for t in ("inner", "mid", "outer", "extreme")
                ]
                _sizes = [s for s in _sizes if s > 0]
                floor = (
                    min(_sizes)
                    if _sizes
                    else float(getattr(cfg, "DEFAULT_TRADE_XCH", 0.01) or 0.01)
                )
            except Exception:
                floor = float(getattr(cfg, "DEFAULT_TRADE_XCH", 0.01) or 0.01)
            reserve = float(getattr(cfg, "XCH_RESERVE", 0) or 0)
            usable = max(0.0, xch_avail - reserve)
            if floor > 0 and usable < floor * 1.02:
                block["parked"] = True
                block["parked_reason"] = "xch_exhausted"
                block["parked_message"] = (
                    f"Accumulation parked: {usable:.4f} XCH available "
                    f"(below smallest buy tier {floor:.4f} XCH). "
                    f"Add XCH to resume, or switch to Two-Sided to recycle "
                    f"the CAT you've accumulated."
                )
        elif block["mode"] == "sell_only":
            cat_avail = float(_bal.get("cat", {}).get("spendable") or 0)
            try:
                from config import get_sell_tier_size_xch

                mid = None
                try:
                    pricing = raw_status.get("pricing") or {}
                    if pricing.get("mid"):
                        mid = float(pricing.get("mid") or 0)
                except Exception:
                    mid = None
                _xch_sizes = [
                    float(get_sell_tier_size_xch(t) or 0)
                    for t in ("inner", "mid", "outer", "extreme")
                ]
                _xch_sizes = [s for s in _xch_sizes if s > 0]
                xch_floor = min(_xch_sizes) if _xch_sizes else 0.0
                cat_floor = (
                    (xch_floor / mid) if (mid and mid > 0 and xch_floor > 0) else 0.0
                )
            except Exception:
                cat_floor = 0.0
            reserve = float(getattr(cfg, "CAT_RESERVE", 0) or 0)
            usable = max(0.0, cat_avail - reserve)
            if cat_floor > 0 and usable < cat_floor * 1.02:
                block["parked"] = True
                block["parked_reason"] = "cat_exhausted"
                cat_name = getattr(cfg, "CAT_NAME", None) or "tokens"
                block["parked_message"] = (
                    f"Distribution parked: {usable:,.0f} {cat_name} available "
                    f"(below smallest sell tier {cat_floor:,.0f}). "
                    f"Top up {cat_name} to resume, or switch to Two-Sided "
                    f"to buy more back."
                )
    except Exception:
        # Never let a parked-state computation break /api/status
        pass
    return block


def _safe_float(val) -> float:
    """Safely convert a value to float (handles Decimal, str, None)."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# api_runtime_diagnostics moved to blueprint


# api_diagnostics_api_stats moved to blueprint


def _sage_ts_to_iso(ts) -> str:
    """Convert a Sage creation_timestamp (unix epoch) to ISO format string."""
    if not ts:
        return ""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return ""


# api_bot_price moved to blueprint


# ---------------------------------------------------------------------------
# Config Routes
# ---------------------------------------------------------------------------

# api_config_get moved to blueprint


# api_fees_status moved to blueprint


# _apply_sage_change_address_setting moved to blueprint


# api_config_update moved to blueprint


# api_config_reload moved to blueprint


# api_config_apply moved to blueprint


# api_config_live moved to blueprint


# ---------------------------------------------------------------------------
# Offer Routes
# ---------------------------------------------------------------------------

# api_offers moved to blueprint


# api_cancel_all_status moved to blueprint


# api_open_offer_count moved to blueprint


# api_cancel_all moved to blueprint


# api_cleanup_orphans moved to blueprint


# api_cancel_offer moved to blueprint


# Boost routes moved to blueprints/boost.py

# ---------------------------------------------------------------------------
# Fill & PnL Routes
# ---------------------------------------------------------------------------

# api_fills moved to blueprint


# api_fills_classified moved to blueprint


# api_fills_arb_wallets moved to blueprint


# api_market_fill_intel moved to blueprint


# api_offers_diagnostic moved to blueprint


# api_purge_fills moved to blueprint


# api_pnl_reset_preview moved to blueprint


# api_pnl_reset moved to blueprint


# api_reset_offer_history moved to blueprint


# api_reset_full moved to blueprint


# Sentinel context manager for the sniper lock fallback above.
class _SNIPE_LOCK_NOOP_CLS:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_SNIPE_LOCK_NOOP = _SNIPE_LOCK_NOOP_CLS()


# api_deposit_advisory_allocate moved to blueprint


# Session routes moved to blueprints/session.py


# api_pnl moved to blueprint


# ---------------------------------------------------------------------------
# Dashboard Command Centre (aggregated endpoint for the top panel)
# ---------------------------------------------------------------------------

# api_dashboard moved to blueprint


# api_stats moved to blueprint


# ---------------------------------------------------------------------------
# Inventory & Risk Routes
# ---------------------------------------------------------------------------

# api_inventory moved to blueprint


# api_risk_spreads moved to blueprint


# ---------------------------------------------------------------------------
# Coin Routes
# ---------------------------------------------------------------------------

# api_coins moved to blueprint


# api_coin_topup moved to blueprint


# api_coin_prep moved to blueprint


# ---------------------------------------------------------------------------
# Dexie Routes
# ---------------------------------------------------------------------------

# api_dexie_stats moved to blueprint


# api_dexie_repost moved to blueprint


# ---------------------------------------------------------------------------
# Market Intelligence Routes (NEW — ecosystem upgrades)
# ---------------------------------------------------------------------------

# _fetch_dbx_pair_status moved to blueprint


# api_market_intel moved to blueprint


# api_market_orderbook moved to blueprint


# api_market_slippage moved to blueprint


# api_market_dbx moved to blueprint


# Alert/watchdog routes moved to blueprints/watchdog.py

# Splash P2P routes moved to blueprints/splash.py (registered at bottom of file)

# ---------------------------------------------------------------------------
# V3: Coinset API Routes
# ---------------------------------------------------------------------------

# api_coinset_stats moved to blueprint


# ---------------------------------------------------------------------------
# Price Routes
# ---------------------------------------------------------------------------

# api_price moved to blueprint


# api_market_summary moved to blueprint


# api_tibet_price moved to blueprint


# api_amm_price moved to blueprint


# api_debug_coinprep moved to blueprint


# api_debug_pricing moved to blueprint


# api_debug_tibet_test moved to blueprint


# api_debug_sage_single_offer_test moved to blueprint


# _fetch_price_standalone moved to blueprint


# ---------------------------------------------------------------------------
# Smart Defaults — Live Market Data Analysis
# ---------------------------------------------------------------------------

# _fetch_dexie_orderbook_standalone moved to blueprint


# api_smart_defaults moved to blueprint


# _calculate_smart_defaults moved to blueprint


# ---------------------------------------------------------------------------
# Database Routes
# ---------------------------------------------------------------------------

# api_db_backup moved to blueprint


# ---------------------------------------------------------------------------
# Log Route (for GUI log panel)
# ---------------------------------------------------------------------------

# api_logs moved to blueprint


# ---------------------------------------------------------------------------
# Wallet & CAT Discovery Routes (GUI startup needs these)
# ---------------------------------------------------------------------------

# api_fingerprint moved to blueprint


# _normalize_asset_id moved to blueprint


# _get_dexie_pairs moved to blueprint


# api_token_overview moved to blueprint


# api_dexie_v3_pairs moved to blueprint


# api_cats moved to blueprint


# api_cat_select moved to blueprint


# api_cat_refresh moved to blueprint


# api_balances_refresh moved to blueprint


# api_full_node_status moved to blueprint


# api_settings_defaults moved to blueprint


# api_settings_validate moved to blueprint


# ---------------------------------------------------------------------------
# Check Resume (GUI startup)
# ---------------------------------------------------------------------------

# _resume_last_active_label moved to blueprint


# api_check_resume moved to blueprint


# ---------------------------------------------------------------------------
# Coin Prep Routes (GUI coin preparation flow)
# ---------------------------------------------------------------------------

_coin_prep_state = {
    "running": False,
    "complete": False,
    "error": None,
    "started_at": None,
    "xch_coins": 0,
    "cat_coins": 0,
    "xch_needed": 0,
    "cat_needed": 0,
}
_coin_prep_thread = None
_cancel_all_thread = None
_boost_activation_thread = None
_coin_prep_proc = (
    None  # Global ref to subprocess — used to kill old worker on re-trigger
)


# The cancel-all state-factory/mutator helpers live in blueprints/offers.py,
# but the SHARED dict + lock must be initialized here at module load time so
# other modules (shutdown path, GUI fetch) can read it before the blueprints
# are registered below.
_cancel_all_state = {
    "running": False,
    "complete": False,
    "error": None,
    "phase": "idle",
    "message": "",
    "started_at": None,
    "finished_at": None,
    "updated_at": None,
    "total": 0,
    "batch_size": 0,
    "total_batches": 0,
    "current_batch": 0,
    "batch_cancelled": 0,
    "batch_failed": 0,
    "cancelled": 0,
    "failed": 0,
}
_cancel_all_state_lock = threading.Lock()


# _set_cancel_all_state moved to blueprint


# _reset_cancel_all_state moved to blueprint


# _get_cancel_all_state moved to blueprint


# api_log_event moved to blueprint


# api_coin_prep_status moved to blueprint


# api_coin_prep_verify moved to blueprint


# api_coin_prep_trigger moved to blueprint


# api_coin_prep_reset moved to blueprint


# Console + wallet detect/switch routes moved to blueprints/system.py

# ---------------------------------------------------------------------------
# Data Export Routes
# ---------------------------------------------------------------------------

# api_fills_export moved to blueprint


# api_logs_clear moved to blueprint


# api_logs_download moved to blueprint


# SuperLog routes moved to blueprints/superlog.py


# Health, doctor, self-test, config-validate/history/export routes moved to
# blueprints/diagnostics.py (registered at bottom of file)


# Reservations route moved to blueprints/spacescan.py


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_offers(offers: list) -> list:
    """Convert offer list to JSON-safe format."""
    result = []
    for o in offers:
        item = {}
        for k, v in o.items():
            if isinstance(v, Decimal):
                item[k] = str(v)
            else:
                item[k] = v
        result.append(item)
    return result


def _serialize_list(items: list) -> list:
    """Convert a list of dicts to JSON-safe format."""
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append(_serialize_dict(item))
        else:
            result.append(item)
    return result


def _serialize_dict(d: dict) -> dict:
    """Convert a dict to JSON-safe format (Decimal → str)."""
    if d is None:
        return {}
    result = {}
    for k, v in d.items():
        if isinstance(v, Decimal):
            result[k] = str(v)
        elif isinstance(v, dict):
            result[k] = _serialize_dict(v)
        elif isinstance(v, list):
            result[k] = _serialize_list(v)
        else:
            result[k] = v
    return result


# api_wallet_sage_running moved to blueprint


# api_wallet_retry_sage_connect moved to blueprint


# api_wallet_begin_startup moved to blueprint


# api_chia_startup_status moved to blueprint


# api_chia_fingerprints moved to blueprint


# api_chia_start_with_fingerprint moved to blueprint


# api_sage_setup_certs moved to blueprint


# Spacescan routes moved to blueprints/spacescan.py


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _graceful_shutdown(signum, _frame):
    """Handle Ctrl+C without releasing ownership ahead of live producers."""
    sig_name = (
        signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    )
    slog("SAFETY", "Shutdown requested", {"signal": sig_name})
    result = quiesce_and_release_mutation_runtime(bot_instance=bot)
    slog(
        "SAFETY",
        "Shutdown quiescence complete",
        {
            "released": bool(result.get("released")),
            "reason": str(result.get("reason") or "")[:128],
        },
        level="info" if result.get("released") else "error",
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# Blueprint registration
# ---------------------------------------------------------------------------
# Flask Blueprints let us split the route file without breaking callers that
# do `api_server.api_xxx(...)` directly (app_bridge.py and tests). Each
# blueprint imports this module and accesses shared state via attribute
# access (e.g. `api_server.bot`) so reassignments are picked up. We re-export
# the route function names below so `api_server.api_splash_stats` still
# resolves after the move.
from blueprints.splash import (
    bp as _splash_bp,
    api_splash_stats,
    api_splash_receive,
    api_splash_node,
    api_splash_node_start,
    api_splash_node_output,
    api_splash_setup_check,
    api_splash_setup_download,
    api_splash_setup_progress,
    api_splash_setup_release,
    api_splash_incoming,
    api_splash_incoming_list,
)
from blueprints.diagnostics import (
    bp as _diagnostics_bp,
    api_health,
    api_doctor,
    api_health_runtime,
    api_config_history,
    api_self_test,
    api_config_validate,
    api_config_export_env,
)
from blueprints.superlog import (
    bp as _superlog_bp,
    api_superlog_stats,
    api_superlog_level,
    api_superlog_archive,
    api_superlog_download,
)
from blueprints.watchdog import (
    bp as _watchdog_bp,
    api_alerts,
    api_dismiss_alert,
    api_watchdog_cancel_mismatched_offers,
    api_watchdog_shape_fix_status,
    api_watchdog_shape_fix_abort,
)
from blueprints.boost import (
    bp as _boost_bp,
    api_boost_activate,
    api_boost_deactivate,
    api_boost_state,
)
from blueprints.session import (
    bp as _session_bp,
    api_session_fresh_start,
    api_session_resume_chosen,
)
from blueprints.system import (
    bp as _system_bp,
    api_console_status,
    api_console_toggle,
    api_wallets_detect,
    api_wallets_switch,
)
from blueprints.spacescan import (
    bp as _spacescan_bp,
    api_spacescan_status,
    api_spacescan_setup,
    api_reservations,
)

from blueprints.market import (
    bp as _market_bp,
    api_dexie_stats,
    api_dexie_repost,
    api_market_intel,
    api_market_orderbook,
    api_market_slippage,
    api_market_dbx,
    api_coinset_stats,
    api_price,
    api_market_summary,
    api_tibet_price,
    api_amm_price,
    api_debug_coinprep,
    api_debug_pricing,
    api_debug_tibet_test,
    api_debug_sage_single_offer_test,
)
from blueprints.sage import (
    bp as _sage_bp,
    api_fingerprint,
    api_full_node_status,
    api_wallet_sage_running,
    api_wallet_retry_sage_connect,
    api_wallet_begin_startup,
    api_chia_startup_status,
    api_chia_fingerprints,
    api_chia_start_with_fingerprint,
    api_sage_set_fingerprint,
    api_sage_cert_candidates,
    api_sage_setup_certs,
)
from blueprints.cat import (
    bp as _cat_bp,
    api_deposit_advisory_allocate,
    api_token_overview,
    api_dexie_v3_pairs,
    api_cats,
    api_cat_select,
    api_cat_refresh,
    api_balances_refresh,
)
from blueprints.config_bp import (
    bp as _config_bp,
    api_config_get,
    api_fees_status,
    api_config_update,
    api_config_reload,
    api_config_apply,
    api_config_live,
    api_settings_defaults,
    api_settings_validate,
    api_check_resume,
)
from blueprints.coin_prep import (
    bp as _coin_prep_bp,
    api_coins,
    api_coin_topup,
    api_coin_prep,
    api_db_backup,
    api_logs,
    api_log_event,
    api_coin_prep_status,
    api_coin_prep_verify,
    api_coin_prep_trigger,
    api_coin_prep_reset,
    api_fills_export,
    api_logs_clear,
    api_logs_download,
)

from blueprints.offers import (
    bp as _offers_bp,
    api_offers,
    api_cancel_all_status,
    api_open_offer_count,
    api_cancel_all,
    api_cleanup_orphans,
    api_cancel_offer,
    api_fills,
    api_fills_classified,
    api_fills_arb_wallets,
    api_market_fill_intel,
    api_offers_diagnostic,
    api_purge_fills,
    api_pnl_reset_preview,
    api_pnl_reset,
    api_reset_offer_history,
    api_reset_full,
    api_pnl,
)
from blueprints.dashboard import (
    bp as _dashboard_bp,
    api_dashboard,
    api_stats,
    api_inventory,
    api_risk_spreads,
)
from blueprints.smart_defaults import (
    bp as _smart_defaults_bp,
    api_smart_defaults,
)
from blueprints.bot import (
    bp as _bot_bp,
    api_events,
    api_bot_start,
    api_bot_stop,
    api_shutdown,
    api_bot_state,
    api_status,
    api_runtime_diagnostics,
    api_diagnostics_api_stats,
    api_bot_price,
)

app.register_blueprint(_splash_bp)
app.register_blueprint(_diagnostics_bp)
app.register_blueprint(_superlog_bp)
app.register_blueprint(_watchdog_bp)
app.register_blueprint(_boost_bp)
app.register_blueprint(_session_bp)
app.register_blueprint(_system_bp)
app.register_blueprint(_spacescan_bp)
app.register_blueprint(_market_bp)
app.register_blueprint(_sage_bp)
app.register_blueprint(_cat_bp)
app.register_blueprint(_config_bp)
app.register_blueprint(_coin_prep_bp)
app.register_blueprint(_offers_bp)
app.register_blueprint(_dashboard_bp)
app.register_blueprint(_smart_defaults_bp)
app.register_blueprint(_bot_bp)


def _validate_write_route_classification() -> None:
    classified = (
        _MUTATING_API_ENDPOINTS
        | _READ_ONLY_WRITE_API_ENDPOINTS
        | _CONTROL_WRITE_API_ENDPOINTS
    )
    write_endpoints = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if {"POST", "PUT", "PATCH", "DELETE"}.intersection(rule.methods)
    }
    overlaps = (
        (_MUTATING_API_ENDPOINTS & _READ_ONLY_WRITE_API_ENDPOINTS)
        | (_MUTATING_API_ENDPOINTS & _CONTROL_WRITE_API_ENDPOINTS)
        | (_READ_ONLY_WRITE_API_ENDPOINTS & _CONTROL_WRITE_API_ENDPOINTS)
    )
    if overlaps or classified != write_endpoints:
        raise RuntimeError(
            "API write-route mutation classification is incomplete or ambiguous"
        )


_validate_write_route_classification()


# Re-export helpers that moved into blueprint modules so tests doing
# `patch.object(api_server, "_xxx", ...)` keep working unchanged.
from blueprints.market import _fetch_dbx_pair_status  # noqa: E402
from blueprints.smart_defaults import (  # noqa: E402
    _calculate_smart_defaults,
    _fetch_price_standalone,
    _fetch_dexie_orderbook_standalone,
)
from blueprints.offers import _build_fill_history_for_gui  # noqa: E402


def _configured_flask_port() -> int:
    try:
        port = int(os.environ.get("CATALYST_FLASK_PORT", "5000"))
    except (TypeError, ValueError):
        return 5000
    return port if 1 <= port <= 65535 else 5000


def _build_flask_server_on_reservation(reservation):
    """Build Werkzeug around the exact pre-bound socket without a bind gap."""

    from werkzeug.serving import make_server

    server = None
    try:
        server = make_server(
            "127.0.0.1",
            int(reservation.port),
            app,
            threaded=True,
            fd=reservation.fileno(),
        )
        server.server_activate()
    except BaseException:
        if server is not None:
            try:
                server.server_close()
            except Exception:
                pass
        reservation.release()
        raise
    reservation.release()
    return server


def _serve_flask_app_on_reservation(reservation) -> None:
    server = _build_flask_server_on_reservation(reservation)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _reserve_standalone_server_port(preferred_port: int):
    """Atomically select the preferred or nearest bounded owner port."""

    import read_only_diagnostics

    return read_only_diagnostics.reserve_loopback_port(
        preferred_port, include_preferred=True
    )


def _read_only_diagnostics_shutdown(_signum, _frame) -> None:
    """Exit a non-owner diagnostics process without touching shared services."""

    mutation_gate.shutdown_runtime()
    raise SystemExit(0)


def _serve_read_only_diagnostics(reservation) -> None:
    """Serve a fail-closed view using only the existing database in read-only mode."""

    global _read_only_diagnostics_active
    previous_mode = _read_only_diagnostics_active
    _read_only_diagnostics_active = True
    try:
        initialize_mutation_runtime(start_heartbeat=False, acquire_lease=False)
        slog(
            "SAFETY",
            "Read-only diagnostics server starting",
            {
                "port": int(reservation.port),
                "reason_code": "DIAGNOSTICS_READ_ONLY",
            },
            level="warning",
        )
        _serve_flask_app_on_reservation(reservation)
    finally:
        reservation.release()
        _read_only_diagnostics_active = previous_mode
        release_mutation_runtime()


if __name__ == "__main__":
    print("=" * 60)
    print("  CATalyst V2 - The Smart One")
    print("=" * 60)

    _reservation = None
    try:
        init_database()
        _startup_authorization = initialize_mutation_runtime()
    except Exception:
        _startup_authorization = {
            "allowed": False,
            "reason_code": "DURABLE_STATE_UNAVAILABLE",
        }
    try:
        _reservation = _reserve_standalone_server_port(_configured_flask_port())
    except Exception:
        if _startup_authorization.get("allowed"):
            quiesce_and_release_mutation_runtime(bot_instance=None)
        raise
    finally:
        _early_startup_arbiter.release()

    if not _startup_authorization.get("allowed"):
        signal.signal(signal.SIGINT, _read_only_diagnostics_shutdown)
        signal.signal(signal.SIGTERM, _read_only_diagnostics_shutdown)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _read_only_diagnostics_shutdown)
        _early_diagnostics.serve(reservation=_reservation)
        sys.exit(0)

    _port = int(_reservation.port)
    os.environ["CATALYST_FLASK_PORT"] = str(_port)
    _start_owned_runtime_services(_startup_authorization)

    # A non-owner diagnostic process must never stop shared wallet services.
    _shutdown_handler = _graceful_shutdown
    signal.signal(signal.SIGINT, _shutdown_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, _shutdown_handler)  # kill / task manager
    # SIGBREAK is Windows-only (terminal close / Ctrl+Break)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _shutdown_handler)

    # One-shot migration: mark all currently-designated reserve coins as
    # already-advised. Earlier coin-prep runs designated these coins but
    # didn't register them with the deposit advisor, so bot_health kept
    # re-raising "New XCH/CAT deposit" alerts for coins that were not
    # actually new. Runs once per install, gated by a settings flag.
    try:
        from database import get_setting, set_setting, get_reserve_coins

        if not get_setting("deposit_advisory_startup_backfill_v1"):
            raw = get_setting("deposit_advisory_advised_coins", "") or ""
            advised = {s.strip() for s in raw.split(",") if s.strip()}
            added = 0
            for _wt in ("xch", "cat"):
                try:
                    for _rc in get_reserve_coins(_wt) or []:
                        _cid = _rc.get("coin_id") or ""
                        if _cid and _cid not in advised:
                            advised.add(_cid)
                            added += 1
                except Exception:
                    pass
            if added:
                set_setting("deposit_advisory_advised_coins", ",".join(sorted(advised)))
                print(
                    f"  [DepositAdvisory] Backfilled {added} existing reserve coin(s)"
                )
            set_setting("deposit_advisory_startup_backfill_v1", "1")
            # Best-effort: clear any currently-live advisory alerts so the
            # UI updates immediately instead of waiting for the next cycle.
            try:
                store = getattr(events, "_alert_store", None)
                if store is not None:
                    for item in list(store.get_active()):
                        _id = str(item.get("id", ""))
                        if _id.startswith("deposit_advisory_"):
                            store.clear(_id)
            except Exception:
                pass
    except Exception as _e:
        print(f"  [DepositAdvisory] Backfill skipped: {_e}")

    # Record session start time — console only shows events from THIS session
    _session_start_time = datetime.now(timezone.utc).isoformat()

    # Restore "logs cleared at" from database so Clear survives restarts
    try:
        from database import get_setting

        saved = get_setting("logs_cleared_at")
        if saved:
            _logs_cleared_at = saved
            print(f"  [Logs] Restored clear-point: {saved}")
    except Exception:
        pass

    # Restore the latest fresh-run cutoff so PnL/history stay scoped to the
    # current run even after an app restart.
    try:
        restored_cutoff = _restore_run_history_cutoff_from_events()
        if restored_cutoff:
            print(f"  [Fresh Run] Restored history cutoff: {restored_cutoff}")
    except Exception:
        pass

    # Fresh app startups should not inherit old Splash receive counters.
    try:
        from database import clear_splash_incoming

        clear_splash_incoming()
    except Exception:
        pass

    create_bot()

    # Load user-local secrets (e.g. Spacescan API key) into cfg in-memory.
    # These are stored in %APPDATA%\Catalyst\ and are never written to .env.
    try:
        import user_secrets as _user_secrets

        _user_secrets.apply_to_config(cfg)
        if cfg.SPACESCAN_API_KEY:
            print("  [Secrets] Spacescan API key loaded from user secrets.", flush=True)
    except Exception as _e:
        print(f"  [Secrets] Could not load user secrets: {_e}", flush=True)

    # Wallet preload is NOT auto-started here.
    # It is triggered explicitly by the GUI after the user accepts the risk
    # disclosure, via POST /api/wallet/begin-startup.  This ensures no wallet
    # RPC calls are made before the user has acknowledged the disclaimer.

    log_event("info", "server_started", f"API server starting on port {_port}")

    try:
        _serve_flask_app_on_reservation(_reservation)
    except BaseException:
        _reservation.release()
        quiesce_and_release_mutation_runtime()
        raise
