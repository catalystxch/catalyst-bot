"""Minimal, side-effect-free mutation diagnostics server.

This module intentionally uses only the Python standard library.  It must be
safe to import before CATalyst's configuration, logging, path migration, or
database initialization modules when another process owns the mutation lease.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


def _data_directory() -> Path:
    override = os.environ.get("CMM_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().absolute()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "Catalyst"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Catalyst"
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    return (
        Path(base).expanduser() if base else Path.home() / ".local" / "share"
    ) / "Catalyst"


def database_path() -> Path:
    return _data_directory() / "bot.db"


def _file_identity(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (int(stat.st_ino), int(stat.st_size), stat.st_mtime_ns, stat.st_ctime_ns)


def _copy_consistent_sqlite_snapshot(target: Path, directory: Path) -> Path:
    """Copy DB/WAL/SHM only when their source identities remain unchanged."""

    sources = [target, Path(f"{target}-wal"), Path(f"{target}-shm")]
    before = tuple(_file_identity(source) for source in sources)
    if before[0] is None:
        raise FileNotFoundError(target)
    snapshot = directory / "bot.db"
    shutil.copyfile(target, snapshot)
    for source, identity in zip(sources[1:], before[1:]):
        if identity is not None:
            shutil.copyfile(source, Path(f"{snapshot}{source.name[len(target.name) :]}"))
    after = tuple(_file_identity(source) for source in sources)
    if after != before:
        raise RuntimeError("SQLite source changed while diagnostics snapshot was copied")
    return snapshot


def _pid_liveness(pid: int, owner_host: str) -> bool | None:
    try:
        safe_pid = int(pid)
        safe_host = str(owner_host).strip().casefold()
    except (TypeError, ValueError):
        return None
    if safe_pid <= 0 or not safe_host:
        return None
    local_names = {
        socket.gethostname().casefold(),
        socket.getfqdn().casefold(),
    }
    if safe_host not in local_names:
        return None
    if safe_pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process = ctypes.windll.kernel32.OpenProcess(
                0x1000 | 0x00100000, False, safe_pid
            )
            if not process:
                error = ctypes.windll.kernel32.GetLastError()
                return False if error == 87 else None
            try:
                exit_code = wintypes.DWORD()
                if not ctypes.windll.kernel32.GetExitCodeProcess(
                    process, ctypes.byref(exit_code)
                ):
                    return None
                return exit_code.value == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(process)
        except Exception:
            return None
    try:
        os.kill(safe_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def preflight_requires_diagnostics(path: Path | None = None) -> bool:
    """Fail closed on an active owner unless expired local death is proven."""

    target = Path(path) if path is not None else database_path()
    if not target.is_file():
        return False
    snapshot_dir = None
    conn = None
    try:
        snapshot_dir = tempfile.TemporaryDirectory(prefix="catalyst-preflight-")
        snapshot = _copy_consistent_sqlite_snapshot(
            target, Path(snapshot_dir.name)
        )
        uri = f"file:{quote(str(snapshot.absolute()).replace(os.sep, '/'), safe='/:')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        try:
            row = conn.execute(
                "SELECT active,owner_pid,owner_host,expires_at "
                "FROM runtime_mutation_lease WHERE singleton_id=1"
            ).fetchone()
        except sqlite3.OperationalError:
            tables = {
                str(item[0])
                for item in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            stability_tables = {
                "runtime_mutation_lease",
                "runtime_safety_latch",
                "runtime_worker_delegations",
                "offer_intents",
                "offer_operation_journal",
                "publication_outbox",
            }
            # A valid DB with none of Task 3's tables is an upgrade candidate,
            # not a foreign owner. Partial stability state fails closed.
            return bool(tables & stability_tables)
        if row is None:
            return True
        if not bool(row["active"]):
            return False
        expiry = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry.utcoffset() is None:
            return True
        if expiry.astimezone(timezone.utc) > datetime.now(timezone.utc):
            return True
        return _pid_liveness(row["owner_pid"], row["owner_host"]) is not False
    except Exception:
        return True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if snapshot_dir is not None:
            try:
                snapshot_dir.cleanup()
            except Exception:
                pass


def _bounded_text(value: Any, maximum: int = 128) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:maximum]


def _unavailable_status() -> dict[str, Any]:
    return {
        "allowed": False,
        "reason_code": "DURABLE_STATE_UNAVAILABLE",
        "source": "durable_read",
        "latch_generation": 0,
        "blocking_operation_ids": [],
        "blocking_operation_count": 0,
        "lease": {
            "active": False,
            "version": 0,
            "expires_at": None,
            "owner_run_id": None,
            "owner_pid": None,
            "owned_by_this_run": False,
        },
    }


def read_safety_status(path: Path | None = None) -> dict[str, Any]:
    """Read one existing SQLite snapshot without creating or changing files."""

    target = Path(path) if path is not None else database_path()
    if not target.is_file():
        return _unavailable_status()
    snapshot_dir = None
    conn = None
    try:
        # Opening a WAL database in-place, even with mode=ro/query_only, may
        # create its -shm file. Copy the existing DB/WAL snapshot to an OS temp
        # directory so diagnostics never changes the shared data directory.
        snapshot_dir = tempfile.TemporaryDirectory(prefix="catalyst-diagnostics-")
        snapshot = _copy_consistent_sqlite_snapshot(
            target, Path(snapshot_dir.name)
        )
        uri = f"file:{quote(str(snapshot.absolute()).replace(os.sep, '/'), safe='/:')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        latch = conn.execute(
            "SELECT generation,state,reason_code,blocking_operation_ids_json "
            "FROM runtime_safety_latch WHERE singleton_id=1"
        ).fetchone()
        lease = conn.execute(
            "SELECT lease_version,active,owner_run_id,owner_pid,expires_at "
            "FROM runtime_mutation_lease WHERE singleton_id=1"
        ).fetchone()
        blockers = conn.execute(
            """
            SELECT journal.operation_id
            FROM offer_operation_journal AS journal
            JOIN (
                SELECT operation_id, MAX(sequence) AS latest_sequence
                FROM offer_operation_journal GROUP BY operation_id
            ) AS latest ON latest.operation_id=journal.operation_id
              AND latest.latest_sequence=journal.sequence
            WHERE journal.blocks_mutation=1 ORDER BY journal.sequence LIMIT 33
            """
        ).fetchall()
        if latch is None or lease is None:
            raise sqlite3.DatabaseError("required stability singleton missing")
        conn.rollback()
        blocker_ids = [_bounded_text(row["operation_id"]) for row in blockers]
        blocker_ids = [item for item in blocker_ids if item][:32]
        state = str(latch["state"] or "")
        lease_active = bool(lease["active"])
        if state == "tripped":
            raw_reason = str(latch["reason_code"] or "")
            reason = (
                raw_reason
                if raw_reason.isascii()
                and raw_reason.isupper()
                and len(raw_reason) <= 64
                else "SAFETY_LATCH_TRIPPED"
            )
            source = "durable_latch"
        elif state != "resolved":
            reason, source = "DURABLE_STATE_UNAVAILABLE", "durable_latch"
        elif blocker_ids:
            reason, source = "UNRESOLVED_OPERATIONS", "operation_journal"
        elif lease_active:
            reason, source = "LEASE_OWNED_BY_OTHER", "lease"
        else:
            reason, source = "LEASE_UNAVAILABLE", "lease"
        return {
            "allowed": False,
            "reason_code": reason,
            "source": source,
            "latch_generation": int(latch["generation"] or 0),
            "blocking_operation_ids": blocker_ids,
            "blocking_operation_count": len(blocker_ids),
            "lease": {
                "active": lease_active,
                "version": int(lease["lease_version"] or 0),
                "expires_at": _bounded_text(lease["expires_at"]),
                "owner_run_id": _bounded_text(lease["owner_run_id"]),
                "owner_pid": int(lease["owner_pid"]) if lease["owner_pid"] else None,
                "owned_by_this_run": False,
            },
        }
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return _unavailable_status()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if snapshot_dir is not None:
            try:
                snapshot_dir.cleanup()
            except Exception:
                pass


def _handler(database: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CATalystDiagnostics"
        sys_version = ""

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path == "/api/safety/status":
                self._json(
                    200, {"success": True, "safety": read_safety_status(database)}
                )
                return
            self._json(
                423,
                {
                    "success": False,
                    "error": "diagnostics_read_only",
                    "reason": "DIAGNOSTICS_READ_ONLY",
                },
            )

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self.do_GET()

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

    return Handler


def serve(port: int, path: Path | None = None) -> None:
    safe_port = int(port)
    if not 1 <= safe_port <= 65535:
        raise ValueError("diagnostics port is out of range")
    target = Path(path) if path is not None else database_path()
    server = ThreadingHTTPServer(("127.0.0.1", safe_port), _handler(target))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CATalyst read-only safety diagnostics"
    )
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args(argv)
    serve(args.port, args.database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
