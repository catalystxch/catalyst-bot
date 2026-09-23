"""Local lease-owner evidence must not depend on Windows DNS availability."""
import ctypes
import os
import socket
from types import SimpleNamespace

import pytest

import mutation_gate
import read_only_diagnostics


@pytest.fixture(params=[mutation_gate.pid_liveness, read_only_diagnostics._pid_liveness],
                ids=["runtime", "startup_preflight"])
def pid_liveness(request):
    return request.param


def _forbid_dns(monkeypatch):
    calls = []

    def lookup():
        calls.append(True)
        raise AssertionError("local PID ownership must not wait for DNS")

    monkeypatch.setattr(socket, "getfqdn", lookup)
    return calls


def test_current_hostname_owner_is_recognized_without_dns(monkeypatch, pid_liveness):
    monkeypatch.setattr(socket, "gethostname", lambda: "catalyst-host")
    dns_calls = _forbid_dns(monkeypatch)

    assert pid_liveness(os.getpid(), "CATALYST-HOST") is True
    assert dns_calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows configured-name API")
@pytest.mark.parametrize(
    ("owner_host", "expected"),
    [("catalyst-host.example.test", True),
     ("CATALYST-HOST.EXAMPLE.TEST", True),
     ("remote-host.example.test", None),
     ("catalyst-host.attacker.test", None)],
)
def test_windows_owner_uses_configured_physical_fqdn_not_dns(
    monkeypatch, pid_liveness, owner_host, expected,
):
    monkeypatch.setattr(socket, "gethostname", lambda: "catalyst-host")
    dns_calls = _forbid_dns(monkeypatch)

    def configured_name(kind, buffer, size):
        # A cluster's virtual alias is not proof of a PID on this physical PC.
        if kind != 7:  # ComputerNamePhysicalDnsFullyQualified
            return False
        buffer.value = "catalyst-host.example.test"
        return True

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: SimpleNamespace(
        GetComputerNameExW=configured_name))

    assert pid_liveness(os.getpid(), owner_host) is expected
    assert dns_calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows configured-name API")
@pytest.mark.parametrize("failure", ["unavailable", "error"])
def test_windows_uncertain_host_cannot_prove_local_pid_ownership(monkeypatch, pid_liveness, failure):
    monkeypatch.setattr(socket, "gethostname", lambda: "catalyst-host")
    dns_calls = _forbid_dns(monkeypatch)

    def unavailable(*args):
        if failure == "error":
            raise OSError("configured computer name unavailable")
        return False

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: SimpleNamespace(
        GetComputerNameExW=unavailable))

    assert pid_liveness(os.getpid(), "catalyst-host.example.test") is None
    assert dns_calls == []


def test_unavailable_local_hostname_is_uncertain_not_an_exception(monkeypatch, pid_liveness):
    def unavailable():
        raise OSError("local name unavailable")

    monkeypatch.setattr(socket, "gethostname", unavailable)
    dns_calls = _forbid_dns(monkeypatch)

    assert pid_liveness(os.getpid(), "catalyst-host") is None
    assert dns_calls == []
