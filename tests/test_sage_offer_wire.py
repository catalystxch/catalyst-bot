from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import zlib

import pytest

import sage_offer_wire

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "catalyst"
VALID_SAGE_OFFER = (
    "offer1qqr83wcuu2rykcmqvpsxggqqemhmlaekcenaz02ma6hs5w600dhjlvfjn477nkwz369h88"
    "kll73h37fefnwk3qqnz8s0lle02q3qpqz2qsycpl7d3j83esykrsspg7c5qgqvq6x5vsu9w2c4"
)


@pytest.fixture(autouse=True)
def _fail_closed_network_guard(monkeypatch):
    attempts: list[str] = []

    def blocked(*_args, **_kwargs):
        attempts.append("socket")
        raise AssertionError("network access is forbidden in Sage Offer wire tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.mark.parametrize(
    "offer_text",
    [
        "offer1qqq838rrvpsxqwxqgpdsqqzgvsqvzhp6u9v",
        "offer1qqqh3wergt5w5ccqsgpsedq9qpyxgqxpud2f6n",
        "offer1qqp83w76wzru6ccqsgpsedq9qpyxgqxp07sj55",
        "offer1qqph3wlykhv8jccqsgpsedq9qpyxgqxp97098j",
        "offer1qqz83wcsltt6wccqsgpsedq9qpyxgqxpxdtleu",
        "offer1qqzh3wcuu2rykccqsgpsedq9qpyxgqxpef85zs",
        "offer1qqr83wcuu2rykccqsgpsedq9qpyxgqxptsfxvk",
    ],
)
def test_all_supported_offer_compression_dictionary_versions_parse(offer_text):
    assert sage_offer_wire.canonical_sage_offer_text(offer_text) == offer_text


def test_offer_decompression_rejects_unsupported_version_and_bounded_output(
    monkeypatch,
):
    with pytest.raises(ValueError, match="unsupported"):
        sage_offer_wire._decompress_offer(b"\x00\x07" + zlib.compress(b"payload"))

    monkeypatch.setattr(sage_offer_wire, "_MAX_DECOMPRESSED_OFFER_LENGTH", 32)
    with pytest.raises(ValueError, match="size exceeds"):
        sage_offer_wire._decompress_offer(b"\x00\x00" + zlib.compress(b"x" * 33))


@pytest.mark.parametrize(
    "offer_text",
    [
        # A valid checksum over a final 5-bit group with non-zero unused bits.
        "offer1qqr83wcuu2rykcmqvpsxggqqemhmlaekcenaz02ma6hs5w600dhjlvfjn477nkwz369h88"
        "kll73h37fefnwk3qqnz8s0lle02q3qpqz2qsycpl7d3j83esykrsspg7c5qgqvq6x5v3pn6l98",
        # A valid Offer zlib stream followed by an extra byte, then checksummed.
        "offer1qqr83wcuu2rykccqsgpsedq9qpyxgqxp0q5qkhte",
        # A checksummed but truncated zlib stream.
        "offer1qqr83wcuu2rykccqsgpsedq9qpyxgqq9phzv3",
    ],
)
def test_offer_wire_rejects_noncanonical_padding_and_zlib_boundaries(offer_text):
    assert sage_offer_wire.canonical_sage_offer_text(offer_text) is None


def _encode_test_offer(payload: bytes) -> str:
    data = sage_offer_wire._convertbits(payload, 8, 5, pad=True)
    checksum_value = (
        sage_offer_wire._bech32_polymod(
            sage_offer_wire._bech32_hrp_expand("offer") + data + [0] * 6
        )
        ^ sage_offer_wire._BECH32M_CONSTANT
    )
    checksum = [(checksum_value >> (5 * (5 - index))) & 31 for index in range(6)]
    return "offer1" + "".join(
        sage_offer_wire._CHARSET[value] for value in data + checksum
    )


def test_unsigned_offer_preserves_exact_coin_spends_and_removes_only_signature():
    from chia_rs import G2Element, SpendBundle

    encoded = sage_offer_wire._decode_offer_bech32(VALID_SAGE_OFFER)
    version = int.from_bytes(encoded[:2], "big")
    original = SpendBundle.from_bytes(sage_offer_wire._decompress_offer(encoded))
    signed = SpendBundle(original.coin_spends, G2Element.generator())
    compressor = zlib.compressobj(zdict=sage_offer_wire._puzzle_dictionary(version))
    signed_text = _encode_test_offer(
        version.to_bytes(2, "big")
        + compressor.compress(bytes(signed))
        + compressor.flush()
    )

    unsigned_text = sage_offer_wire.unsigned_sage_offer_text(signed_text)

    assert unsigned_text is not None
    assert unsigned_text != signed_text
    assert sage_offer_wire.canonical_sage_offer_text(unsigned_text) == unsigned_text
    unsigned_encoded = sage_offer_wire._decode_offer_bech32(unsigned_text)
    unsigned = SpendBundle.from_bytes(
        sage_offer_wire._decompress_offer(unsigned_encoded)
    )
    assert [bytes(spend) for spend in unsigned.coin_spends] == [
        bytes(spend) for spend in signed.coin_spends
    ]
    assert bytes(unsigned.aggregated_signature) == bytes(G2Element())
    assert int.from_bytes(unsigned_encoded[:2], "big") == version


@pytest.mark.parametrize("value", [None, "offer1bad", VALID_SAGE_OFFER + " "])
def test_unsigned_offer_rejects_noncanonical_input(value):
    assert sage_offer_wire.unsigned_sage_offer_text(value) is None


def test_genuine_offer_identity_succeeds_when_full_chia_import_is_blocked(tmp_path):
    code = f"""
import builtins
import json
import socket

attempts = []
def blocked_socket(*args, **kwargs):
    attempts.append('socket')
    raise AssertionError('network forbidden')
socket.socket.connect = blocked_socket
socket.socket.connect_ex = blocked_socket
socket.create_connection = blocked_socket

real_import = builtins.__import__
def without_full_chia(name, *args, **kwargs):
    if name == 'chia' or name.startswith('chia.'):
        raise ImportError('full chia-blockchain blocked by contract test')
    return real_import(name, *args, **kwargs)
builtins.__import__ = without_full_chia

from offer_manager import OfferManager
result = OfferManager._canonical_sage_creation_identity({{
    'success': True,
    'trade_id': {"3" * 64!r},
    'offer': {VALID_SAGE_OFFER!r},
}})
print(json.dumps({{'result': result, 'attempts': attempts}}))
"""
    env = os.environ.copy()
    env["CMM_DATA_DIR"] = str(tmp_path / "catalyst-data")
    env["SAGE_RPC_URL"] = "https://127.0.0.1:1"
    env["PYTHONPATH"] = str(SOURCE)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "result": ["3" * 64, VALID_SAGE_OFFER],
        "attempts": [],
    }


def test_sage_offer_wire_runtime_and_bundle_contracts_are_declared():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    spec = (ROOT / "catalyst.spec").read_text(encoding="utf-8")
    manager = (SOURCE / "offer_manager.py").read_text(encoding="utf-8")

    assert "chia_rs>=0.30,<0.31" in requirements.splitlines()
    assert "'chia_rs'" in spec
    assert "'chia_rs.chia_rs'" in spec
    assert "from chia." not in manager


def test_sage_offer_wire_upstream_licenses_are_preserved_and_bundled():
    spec = (ROOT / "catalyst.spec").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    pieter_license_path = ROOT / "licenses" / "Pieter-Wuille-bech32-MIT.txt"
    chia_license_path = (
        ROOT / "licenses" / "Chia-Network-chia-blockchain-Apache-2.0.txt"
    )

    assert pieter_license_path.is_file()
    assert chia_license_path.is_file()
    pieter_license = pieter_license_path.read_text(encoding="utf-8")
    chia_license = chia_license_path.read_text(encoding="utf-8")
    assert "Copyright (c) 2017 Pieter Wuille" in pieter_license
    assert "Permission is hereby granted, free of charge" in pieter_license
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in pieter_license
    assert "Apache License" in chia_license
    assert "Version 2.0, January 2004" in chia_license
    assert "END OF TERMS AND CONDITIONS" in chia_license

    assert "Pieter Wuille Bech32m reference implementation" in notices
    assert "Chia Network chia-blockchain 2.5.7" in notices
    assert "7c2632368f37f21a33b179c9bfd07c383d23c12fb48b47a9b24fa5029f8690a1" in notices
    assert "CATalyst changes" in notices
    assert "_license_files" in spec
    assert "THIRD_PARTY_NOTICES.md" in spec
    assert "Pieter-Wuille-bech32-MIT.txt" in spec
    assert "Chia-Network-chia-blockchain-Apache-2.0.txt" in spec
