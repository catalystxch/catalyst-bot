"""Privacy-conscious PC diagnostics for CATalyst support bundles."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def _safe_used_percent(used_bytes: int | None, total_bytes: int | None) -> float | None:
    try:
        total = int(total_bytes or 0)
        used = int(used_bytes or 0)
        if total <= 0:
            return None
        return round((used / total) * 100, 1)
    except Exception:
        return None


def _existing_path_for_disk_usage(path: str) -> str:
    candidate = os.path.abspath(path or os.getcwd())
    while candidate and not os.path.exists(candidate):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return candidate if candidate and os.path.exists(candidate) else os.getcwd()


def _disk_root_for_path(path: str) -> str:
    absolute = os.path.abspath(path or os.getcwd())
    drive, _ = os.path.splitdrive(absolute)
    if drive:
        return drive + os.sep
    return os.path.abspath(os.path.sep)


def _disk_diagnostics(label: str, path: str) -> dict:
    try:
        import shutil

        usage_path = _existing_path_for_disk_usage(path)
        usage = shutil.disk_usage(usage_path)
        return {
            "label": label,
            "root": _disk_root_for_path(usage_path),
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
            "used_percent": _safe_used_percent(usage.used, usage.total),
        }
    except Exception as exc:
        return {"label": label, "error": str(exc)}


def _collect_disk_diagnostics() -> list[dict]:
    paths = [("app_root", _PACKAGE_DIR)]
    try:
        from user_paths import data_dir, log_dir

        paths.append(("data_dir", data_dir()))
        paths.append(("log_dir", log_dir()))
    except Exception:
        # User path helpers can be unavailable in early startup or isolated tests.
        paths.append(("runtime_dir", _PACKAGE_DIR))

    return [_disk_diagnostics(label, path) for label, path in paths]


def _windows_system_memory() -> dict | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return {
            "source": "GlobalMemoryStatusEx",
            "total_physical_bytes": int(status.ullTotalPhys),
            "available_physical_bytes": int(status.ullAvailPhys),
            "memory_load_percent": int(status.dwMemoryLoad),
            "total_page_file_bytes": int(status.ullTotalPageFile),
            "available_page_file_bytes": int(status.ullAvailPageFile),
            "total_virtual_bytes": int(status.ullTotalVirtual),
            "available_virtual_bytes": int(status.ullAvailVirtual),
        }
    except Exception:
        return None


def _proc_meminfo_memory() -> dict | None:
    meminfo_path = "/proc/meminfo"
    if not os.path.exists(meminfo_path):
        return None
    try:
        values: dict[str, int] = {}
        with open(meminfo_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                parts = raw.strip().split()
                if not parts:
                    continue
                try:
                    values[key] = int(parts[0]) * 1024
                except ValueError:
                    continue

        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        used = (
            total - available if total is not None and available is not None else None
        )
        result = {
            "source": "proc_meminfo",
            "total_physical_bytes": total,
            "available_physical_bytes": available,
            "used_physical_bytes": used,
            "memory_load_percent": _safe_used_percent(used, total),
            "swap_total_bytes": values.get("SwapTotal"),
            "swap_free_bytes": values.get("SwapFree"),
        }
        return {k: v for k, v in result.items() if v is not None}
    except Exception:
        return None


def _sysconf_memory() -> dict | None:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total_pages = int(os.sysconf("SC_PHYS_PAGES"))
        total = page_size * total_pages
        available = None
        try:
            available = page_size * int(os.sysconf("SC_AVPHYS_PAGES"))
        except Exception:
            # Some platforms expose total pages without available-page counts.
            available = None
        used = total - available if available is not None else None
        result = {
            "source": "sysconf",
            "total_physical_bytes": total,
            "available_physical_bytes": available,
            "used_physical_bytes": used,
            "memory_load_percent": _safe_used_percent(used, total),
        }
        return {k: v for k, v in result.items() if v is not None}
    except Exception:
        return None


def _collect_system_memory() -> dict:
    for collector in (_windows_system_memory, _proc_meminfo_memory, _sysconf_memory):
        data = collector()
        if data:
            return data
    return {"source": "unavailable"}


def _collect_system_uptime_secs() -> int | None:
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            return int(ctypes.windll.kernel32.GetTickCount64() // 1000)
        if os.path.exists("/proc/uptime"):
            with open("/proc/uptime", "r", encoding="utf-8") as fh:
                return int(float(fh.read().split()[0]))
    except Exception:
        return None
    return None


def _windows_process_entries() -> list[dict]:
    if os.name != "nt":
        return []
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
        MAX_PATH = 260

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * MAX_PATH),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if handle in (0, INVALID_HANDLE_VALUE):
            return []

        entries = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(handle, ctypes.byref(entry))
            while ok:
                entries.append(
                    {
                        "pid": int(entry.th32ProcessID),
                        "parent_pid": int(entry.th32ParentProcessID),
                        "name": str(entry.szExeFile or ""),
                    }
                )
                ok = kernel32.Process32NextW(handle, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(handle)
        return entries
    except Exception:
        return []


def _windows_process_memory(pid: int) -> dict:
    if os.name != "nt":
        return {}
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_VM_READ = 0x0010

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        access_modes = (
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
        )
        handle = None
        for access in access_modes:
            handle = kernel32.OpenProcess(access, False, int(pid))
            if handle:
                break
        if not handle:
            return {}

        try:
            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
            if not psapi.GetProcessMemoryInfo(
                handle,
                ctypes.byref(counters),
                counters.cb,
            ):
                return {}
            return {
                "working_set_bytes": int(counters.WorkingSetSize),
                "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
                "private_bytes": int(counters.PrivateUsage),
                "pagefile_usage_bytes": int(counters.PagefileUsage),
            }
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return {}


def _process_tree_ids(processes: list[dict], root_pid: int) -> set[int]:
    children: dict[int, list[dict]] = {}
    for proc in processes:
        children.setdefault(int(proc.get("parent_pid") or 0), []).append(proc)

    tree_ids: set[int] = set()

    def add_tree(proc_id: int) -> None:
        if proc_id in tree_ids:
            return
        tree_ids.add(proc_id)
        for child in children.get(proc_id, []):
            add_tree(int(child.get("pid") or 0))

    add_tree(int(root_pid))
    return tree_ids


def _windows_process_tree_memory(root_pid: int) -> list[dict]:
    entries = _windows_process_entries()
    if not entries:
        return []
    tree_ids = _process_tree_ids(entries, root_pid)
    rows = []
    for entry in entries:
        pid = int(entry.get("pid") or 0)
        if pid not in tree_ids:
            continue
        row = {
            "pid": pid,
            "parent_pid": int(entry.get("parent_pid") or 0),
            "name": entry.get("name") or "",
        }
        row.update(_windows_process_memory(pid))
        rows.append(row)
    return rows


def _proc_status_bytes(pid: int, key: str) -> int | None:
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith(key + ":"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * 1024
    except Exception:
        return None
    return None


def _proc_process_entries() -> list[dict]:
    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return []
    rows = []
    for name in os.listdir(proc_root):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(
                os.path.join(proc_root, name, "stat"),
                "r",
                encoding="utf-8",
                errors="replace",
            ) as fh:
                stat = fh.read()
            right = stat.rfind(")")
            left = stat.find("(")
            proc_name = stat[left + 1 : right] if left >= 0 and right > left else name
            rest = stat[right + 2 :].split()
            parent_pid = int(rest[1]) if len(rest) > 1 else 0
            rss = _proc_status_bytes(pid, "VmRSS")
            vms = _proc_status_bytes(pid, "VmSize")
            row = {
                "pid": pid,
                "parent_pid": parent_pid,
                "name": proc_name,
            }
            if rss is not None:
                row["working_set_bytes"] = rss
                row["rss_bytes"] = rss
            if vms is not None:
                row["virtual_memory_bytes"] = vms
            rows.append(row)
        except Exception:
            continue
    return rows


def _proc_process_tree_memory(root_pid: int) -> list[dict]:
    entries = _proc_process_entries()
    if not entries:
        return []
    tree_ids = _process_tree_ids(entries, root_pid)
    return [row for row in entries if int(row.get("pid") or 0) in tree_ids]


def _current_process_memory_fallback() -> dict:
    try:
        import resource

        max_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            max_rss *= 1024
        return {
            "source": "resource.getrusage",
            "peak_rss_bytes": max_rss,
        }
    except Exception:
        return {"source": "unavailable"}


def _collect_app_process_diagnostics() -> dict:
    pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, "getppid") else None
    if os.name == "nt":
        processes = _windows_process_tree_memory(pid)
        source = "windows_process_tree"
    else:
        processes = _proc_process_tree_memory(pid)
        source = "proc_process_tree" if processes else "current_process"

    if not processes:
        current = _windows_process_memory(pid) if os.name == "nt" else {}
        if not current:
            current = _current_process_memory_fallback()
        processes = [
            {
                "pid": pid,
                "parent_pid": parent_pid,
                "name": os.path.basename(sys.executable),
                **current,
            }
        ]

    working_total = sum(int(p.get("working_set_bytes") or 0) for p in processes)
    private_values = [int(p.get("private_bytes") or 0) for p in processes]
    private_total = sum(private_values) if any(private_values) else None
    current_process = next((p for p in processes if int(p.get("pid") or 0) == pid), {})

    return {
        "source": source,
        "pid": pid,
        "parent_pid": parent_pid,
        "process_name": os.path.basename(sys.executable),
        "tree_process_count": len(processes),
        "tree_working_set_bytes": working_total or None,
        "tree_private_bytes": private_total,
        "current_process": current_process,
        "processes": sorted(
            processes,
            key=lambda item: int(item.get("working_set_bytes") or 0),
            reverse=True,
        ),
    }


def collect_pc_diagnostics() -> dict:
    """Collect machine pressure plus CATalyst process-tree diagnostics."""
    import platform as _platform

    system = {
        "platform": _platform.platform(),
        "system": _platform.system(),
        "release": _platform.release(),
        "version": _platform.version(),
        "machine": _platform.machine(),
        "processor": _platform.processor(),
        "architecture": _platform.architecture()[0],
        "cpu_count_logical": os.cpu_count(),
        "uptime_secs": _collect_system_uptime_secs(),
    }
    try:
        system["load_average"] = list(os.getloadavg())
    except Exception:
        # Load average is optional and platform-dependent, especially on Windows.
        system["load_average"] = None

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": system,
        "memory": _collect_system_memory(),
        "disk": _collect_disk_diagnostics(),
        "app_process": _collect_app_process_diagnostics(),
    }
