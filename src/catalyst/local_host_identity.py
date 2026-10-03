"""Local hostname evidence for lease ownership; safe before writable imports."""

from __future__ import annotations

import os
import socket


def _configured_local_fqdn() -> str:
    """Read Windows' physical computer name without a network DNS lookup."""
    if os.name != "nt":
        return socket.getfqdn()
    from ctypes import WinDLL, byref, c_int, create_unicode_buffer, wintypes

    get_name = WinDLL("kernel32", use_last_error=True).GetComputerNameExW
    get_name.argtypes = [c_int, wintypes.LPWSTR, wintypes.LPDWORD]
    get_name.restype = wintypes.BOOL
    buffer = create_unicode_buffer(256)
    size = wintypes.DWORD(len(buffer))
    # Physical, not a cluster virtual name whose PID may belong to another node.
    if not get_name(7, buffer, byref(size)):
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
