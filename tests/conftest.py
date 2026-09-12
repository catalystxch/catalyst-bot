"""
Pytest configuration — test collection, isolation, and encoding settings.

Fixes:
- Excludes standalone diagnostic scripts that crash pytest collection
- Sets UTF-8 encoding for stdout/stderr capture on Windows (prevents
  UnicodeDecodeError from emoji output in print() statements when pytest
  tries to decode its capture buffer with cp1252)
"""

import sys
import os
import io
import importlib

# ---------------------------------------------------------------------------
# Isolate the test run from the user's real %APPDATA%\Catalyst\ data dir.
#
# Tests import api_server / database, both of which call user_paths.data_dir()
# at module-load time to decide where bot.db, bot_superlog_*.log, .env, and
# the singleton lock live. Without an override that resolves to the user's
# production data dir, so:
#   - every pytest session writes bot_superlog_*.log files into the live data
#     dir, mixed in with the user's real bot logs;
#   - a buggy test teardown that resets DB_PATH back to the original could
#     run real-DB queries against a partially-migrated schema and corrupt the
#     production bot.db (the 26-04 incident class of bug).
#
# Setting CMM_DATA_DIR before user_paths is imported (any catalyst import
# pulls it in transitively) pins data_dir() to a throwaway temp dir for the
# whole session. setdefault() lets CI override.
# ---------------------------------------------------------------------------
import atexit as _atexit
import shutil as _shutil
import tempfile as _tempfile

if not os.environ.get("CMM_DATA_DIR"):
    _TEST_DATA_DIR = _tempfile.mkdtemp(prefix="catalyst-tests-")
    os.environ["CMM_DATA_DIR"] = _TEST_DATA_DIR

    def _cleanup_test_data_dir(path=_TEST_DATA_DIR):
        # Tolerant of WinError 32 when SQLite/log handles are still open;
        # the OS reaps stale entries under TEMP eventually.
        try:
            _shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    _atexit.register(_cleanup_test_data_dir)

# ---------------------------------------------------------------------------
# Src-layout bootstrap: add src/catalyst/ to sys.path so tests can use
# flat imports (`from database import X`) against the reorganised source
# tree.  This runs at conftest load time, before any collection happens.
# ---------------------------------------------------------------------------
_SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "catalyst")
)
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


# Some older pure-unit tests install tiny import-time stubs for optional-ish
# dependencies when those packages are absent from sys.modules. Under full
# collection those stubs can leak into later modules before fixture teardown
# runs, so preload the real packages once for the test session.
def _preload_real_package(package: str) -> None:
    try:
        importlib.import_module(package)
    except ModuleNotFoundError as exc:
        if exc.name != package:
            raise
        # Ad-hoc unit-test environments may omit optional runtime packages.
        return


_preload_real_package("dotenv")
_preload_real_package("urllib3")
_preload_real_package("requests")

# ---------------------------------------------------------------------------
# Exclude standalone integration scripts from collection.
# These files contain module-level code (sys.exit, live API calls) that
# crashes pytest's importer. They're meant to be run directly, not via pytest.
# ---------------------------------------------------------------------------
collect_ignore = [
    "test_parallel_offers.py",
    "test_spacescan.py",
    "test_api_data_sources.py",
    "test_all_apis.py",
    "test_coin_prep.py",
    "test_coin_prep_v2.py",
    "test_hidden_coins.py",
    "test_offer_create.py",
]

# ---------------------------------------------------------------------------
# Force UTF-8 for pytest's stdout/stderr capture on Windows.
#
# On Windows, the default console encoding is cp1252 (or the OEM code page).
# Our bot code contains emoji (✅, 🎯, 💰, ×) and Unicode math symbols in
# print() statements. When these are captured by pytest, the bytes land in
# the capture buffer. When pytest later tries to decode the buffer as UTF-8
# (for display in its output), an isolated 0x97 continuation byte (part of
# the UTF-8 × sequence \xc3\x97, split across two capture reads) causes
# UnicodeDecodeError inside contextlib._GeneratorContextManager.__exit__,
# appearing as hundreds of spurious "ERROR at setup/teardown" lines.
#
# The os.environ approach doesn't help because Python has already determined
# sys.stdout's encoding at process start. We must reconfigure the actual
# stream objects AND set the env var for any child processes.
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

    # Reconfigure stdout and stderr to use UTF-8, replacing any bytes that
    # can't be encoded with the Unicode replacement character rather than
    # raising. This covers the case where pytest has NOT yet replaced
    # sys.stdout with its own capture object.
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name, None)
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        elif _stream is not None and hasattr(_stream, "buffer"):
            try:
                _wrapped = io.TextIOWrapper(
                    _stream.buffer,
                    encoding="utf-8",
                    errors="replace",
                    line_buffering=True,
                )
                setattr(sys, _stream_name, _wrapped)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# sys.modules isolation between test files.
#
# Several test files install stub `sys.modules` entries for `database`,
# `wallet`, `wallet_sage`, `coin_manager`, etc. to isolate the module
# under test from the real bot dependencies. A few had buggy tearDowns
# that popped those entries instead of restoring the originals — leaving
# later files to re-import fresh copies of those modules which then broke
# `patch(...)` calls that assume sys.modules still holds the original.
#
# Pytest imports every test module during collection before it runs module
# fixtures.  Isolation therefore has two phases: a collection hook records
# the module environment each file deliberately constructed and restores the
# clean baseline before collecting the next file; the fixture reinstates that
# recorded environment while the file's tests execute.
# ---------------------------------------------------------------------------
import pytest


def _project_module_names() -> set[str]:
    names: set[str] = set()
    for root, _dirs, files in os.walk(_SRC_DIR):
        relative_root = os.path.relpath(root, _SRC_DIR)
        prefix = "" if relative_root == "." else relative_root.replace(os.sep, ".")
        for filename in files:
            if not filename.endswith(".py"):
                continue
            stem = filename[:-3]
            if stem == "__init__":
                if prefix:
                    names.add(prefix)
                continue
            names.add(f"{prefix}.{stem}" if prefix else stem)
    return names


_ISOLATION_GUARDED = _project_module_names() | {
    "requests",
    "requests.adapters",
    "dotenv",
    "urllib3",
}
_COLLECTION_MODULE_STATES: dict[str, dict[str, object]] = {}
_MISSING_MODULE = object()


def _capture_guarded_modules() -> dict[str, object]:
    return {name: sys.modules.get(name, _MISSING_MODULE) for name in _ISOLATION_GUARDED}


def _restore_guarded_modules(saved: dict[str, object]) -> None:
    for name in _ISOLATION_GUARDED:
        original = saved.get(name, _MISSING_MODULE)
        if original is _MISSING_MODULE:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    """Prevent import-time stubs from leaking into the next test module."""

    if not isinstance(collector, pytest.Module):
        yield
        return

    baseline = _capture_guarded_modules()
    yield
    _COLLECTION_MODULE_STATES[collector.nodeid] = _capture_guarded_modules()
    _restore_guarded_modules(baseline)


@pytest.fixture(autouse=True, scope="module")
def _restore_isolation_guarded_modules(request):
    """Run each test file with the imports it established at collection."""

    saved = _capture_guarded_modules()
    collected = _COLLECTION_MODULE_STATES.get(request.node.nodeid)
    if collected is not None:
        _restore_guarded_modules(collected)
    yield
    _restore_guarded_modules(saved)
