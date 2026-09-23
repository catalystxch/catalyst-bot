"""Local hostname evidence for lease ownership; safe before writable imports."""
from __future__ import annotations

import os
import socket


def _configured_local_fqdn() -> str:
    """Read Windows' physical computer name without a network DNS lookup."""
    if os.name != "nt":
        return socket.getfqdn()
    import ctypes
    from ctypes import wintypes

    get_name = ctypes.WinDLL("kernel32", use_last_error=True).GetComputerNameExW
    get_name.argtypes = [ctypes.c_int, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    get_name.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(256)
    size = wintypes.DWORD(len(buffer))
    # Physical, not a cluster virtual name whose PID may belong to another node.
    if not get_name(7, buffer, ctypes.byref(size)):
        return ""
    return buffer.value


def is_local_host(owner_host: str) -> bool:
    """Return true only with local-name evidence, never from a prefix guess."""
    if type(owner_host) is not str or not owner_host:
        return False
    try:
        if owner_host.casefold() == socket.gethostname().casefold():
            return True
        fqdn = _configured_local_fqdn().casefold()
        return bool(fqdn) and owner_host.casefold() == fqdn
    except Exception:
        return False
