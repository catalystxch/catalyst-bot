"""Minimal, side-effect-free mutation diagnostics server.

This module intentionally uses only the Python standard library.  It must be
safe to import before CATalyst's configuration, logging, path migration, or
database initialization modules when another process owns the mutation lease.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


_SOCKET_TYPE = socket.socket


def _authority_sql_sha256(value: Any) -> str | None:
    if type(value) is not str:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _authority_sql_is_canonical_json(value: Any) -> int:
    if type(value) is not str or len(value) > 262_144:
        return 0
    try:
        decoded = json.loads(value)
        canonical = json.dumps(
            decoded,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return 0
    return int(value == canonical)


def _sqlite_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
    """Open SQLite with the deterministic authority helpers installed."""

    conn = sqlite3.connect(*args, **kwargs)
    try:
        conn.create_function(
            "catalyst_sha256", 1, _authority_sql_sha256, deterministic=True
        )
        conn.create_function(
            "catalyst_is_canonical_json",
            1,
            _authority_sql_is_canonical_json,
            deterministic=True,
        )
    except BaseException:
        conn.close()
        raise
    return conn


def _close_socket_handle(handle) -> tuple[bool, BaseException | None]:
    """Close one socket even when an override raises before releasing it."""

    close_error = None
    try:
        handle.close()
    except BaseException as exc:
        close_error = exc

    if isinstance(handle, _SOCKET_TYPE):
        try:
            _SOCKET_TYPE.close(handle)
        except BaseException:
            return False, close_error
        try:
            return handle.fileno() == -1, close_error
        except BaseException:
            return False, close_error

    if close_error is not None:
        try:
            handle.close()
        except BaseException:
            return False, close_error
    return True, close_error


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


def _normalized_loopback_port(value: int | str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 5000
    return port if 1 <= port <= 65535 else 5000


def _candidate_loopback_ports(
    preferred_port: int | str,
    *,
    include_preferred: bool,
    search_limit: int,
):
    preferred = _normalized_loopback_port(preferred_port)
    limit = max(0, min(65534, int(search_limit)))
    if include_preferred:
        yield preferred
    for offset in range(1, limit + 1):
        upper = preferred + offset
        lower = preferred - offset
        if upper <= 65535:
            yield upper
        if lower >= 1:
            yield lower


class LoopbackPortReservation:
    """Own one bound/listening loopback socket until its server takes over."""

    def __init__(self, handle):
        self._handle = handle
        self.port = int(handle.getsockname()[1])
        self._listening = False
        self._release_lock = threading.Lock()

    def fileno(self) -> int:
        handle = self._handle
        if handle is None:
            raise RuntimeError("loopback port reservation is released")
        return int(handle.fileno())

    def release(self) -> bool:
        with self._release_lock:
            handle = self._handle
            if handle is None:
                return False
            closed, close_error = _close_socket_handle(handle)
            if closed:
                self._handle = None
                self._listening = False
            if close_error is not None and not isinstance(close_error, Exception):
                raise close_error
            return closed

    def listen(self) -> None:
        handle = self._handle
        if handle is None:
            raise RuntimeError("loopback port reservation is released")
        if not self._listening:
            handle.listen(socket.SOMAXCONN)
            self._listening = True

    def into_http_server(self, handler):
        """Transfer this exact listening socket to a stdlib HTTP server."""

        handle = self._handle
        if handle is None:
            raise RuntimeError("loopback port reservation is released")
        try:
            server = ThreadingHTTPServer(
                ("127.0.0.1", self.port), handler, bind_and_activate=False
            )
        except BaseException:
            self.release()
            raise
        try:
            server.socket.close()
            self.listen()
            self._handle = None
            server.socket = handle
            server.server_address = handle.getsockname()
            server.server_name = "localhost"
            server.server_port = self.port
            return server
        except BaseException:
            try:
                server.server_close()
            except BaseException:
                pass
            self.release()
            raise


def reserve_loopback_port(
    preferred_port: int | str,
    *,
    include_preferred: bool = True,
    search_limit: int = 50,
) -> LoopbackPortReservation:
    """Atomically reserve a bounded preferred/upper/lower loopback port."""

    for candidate in _candidate_loopback_ports(
        preferred_port,
        include_preferred=bool(include_preferred),
        search_limit=search_limit,
    ):
        handle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                handle.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            if hasattr(handle, "set_inheritable"):
                handle.set_inheritable(False)
            handle.bind(("127.0.0.1", candidate))
            return LoopbackPortReservation(handle)
        except OSError:
            closed, close_error = _close_socket_handle(handle)
            if close_error is not None and not isinstance(close_error, Exception):
                raise close_error
            if not closed:
                raise RuntimeError("loopback socket cleanup failed") from close_error
        except BaseException:
            _close_socket_handle(handle)
            raise
    raise RuntimeError("no loopback server port is available")


def _canonical_data_directory(data_dir: str | os.PathLike[str] | None = None) -> str:
    """Return one stable identity for aliases of the same CATalyst data path."""

    candidate = Path(data_dir) if data_dir is not None else _data_directory()
    resolved = candidate.expanduser().resolve(strict=False)
    canonical = os.path.normcase(os.path.normpath(str(resolved)))
    return canonical.casefold() if os.name == "nt" else canonical


def _startup_lock_path(data_dir: str | os.PathLike[str] | None = None) -> Path:
    identity = _canonical_data_directory(data_dir)
    digest = hashlib.sha256(
        identity.encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    return Path(tempfile.gettempdir()) / "catalyst-startup-arbiters" / f"{digest}.lock"


def _open_startup_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        return handle
    except Exception:
        handle.close()
        raise


class StartupArbiter:
    """An OS-released startup lock keyed outside the shared data directory."""

    def __init__(self, *, lock_path: Path, handle=None, reason: str = ""):
        self.lock_path = lock_path
        self._handle = handle
        self.acquired = handle is not None
        self.reason = reason

    def release(self) -> bool:
        handle = self._handle
        if handle is None:
            return False
        self._handle = None
        was_acquired = self.acquired
        self.acquired = False
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        finally:
            try:
                handle.close()
            except Exception:
                pass
        return was_acquired

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.release()


def acquire_startup_arbiter(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    wait_seconds: float = 60.0,
) -> StartupArbiter:
    """Acquire the startup arbiter, failing closed on every lock error."""

    try:
        timeout = max(0.0, float(wait_seconds))
        lock_path = _startup_lock_path(data_dir)
        handle = _open_startup_lock(lock_path)
    except Exception:
        return StartupArbiter(
            lock_path=locals().get("lock_path", Path()),
            reason="startup_arbiter_unavailable",
        )

    deadline = time.monotonic() + timeout
    while True:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return StartupArbiter(lock_path=lock_path, handle=handle)
        except (OSError, IOError):
            if time.monotonic() >= deadline:
                try:
                    handle.close()
                except Exception:
                    pass
                return StartupArbiter(
                    lock_path=lock_path, reason="startup_arbiter_busy"
                )
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        except Exception:
            try:
                handle.close()
            except Exception:
                pass
            return StartupArbiter(
                lock_path=lock_path, reason="startup_arbiter_unavailable"
            )


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
            shutil.copyfile(
                source, Path(f"{snapshot}{source.name[len(target.name) :]}")
            )
    after = tuple(_file_identity(source) for source in sources)
    if after != before:
        raise RuntimeError(
            "SQLite source changed while diagnostics snapshot was copied"
        )
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
        snapshot = _copy_consistent_sqlite_snapshot(target, Path(snapshot_dir.name))
        uri = f"file:{quote(str(snapshot.absolute()).replace(os.sep, '/'), safe='/:')}?mode=ro"
        conn = _sqlite_connect(uri, uri=True, timeout=1, isolation_level=None)
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
        snapshot = _copy_consistent_sqlite_snapshot(target, Path(snapshot_dir.name))
        uri = f"file:{quote(str(snapshot.absolute()).replace(os.sep, '/'), safe='/:')}?mode=ro"
        conn = _sqlite_connect(uri, uri=True, timeout=1, isolation_level=None)
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


def serve(
    port: int | None = None,
    path: Path | None = None,
    *,
    reservation: LoopbackPortReservation | None = None,
    ready_callback=None,
) -> None:
    if reservation is None:
        if port is None:
            raise ValueError("diagnostics port is required")
        reservation = reserve_loopback_port(port, search_limit=0)
    target = Path(path) if path is not None else database_path()
    try:
        server = reservation.into_http_server(_handler(target))
    except BaseException:
        reservation.release()
        raise
    try:
        if ready_callback is not None:
            ready_callback()
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
