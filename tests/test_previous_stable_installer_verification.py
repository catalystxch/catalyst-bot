"""A prior stable installer must be authenticated before upgrade smoke runs it."""

import base64
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.sign_update_manifest import sign_manifest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_previous_stable_installer.py"


@pytest.fixture
def previous_release(tmp_path):
    tag = "v1.4.2"
    installer = tmp_path / f"Catalyst-Setup-{tag}.exe"
    installer.write_bytes(b"previous genuine installer")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    sidecar = tmp_path / f"{installer.name}.sha256"
    sidecar.write_text(f"{digest}  {installer.name}", encoding="ascii")
    published = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manifest = {
        "schema": 1,
        "app": "CATalyst",
        "channel": "stable",
        "version": tag[1:],
        "tag": tag,
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "expires_at": (published + timedelta(days=90))
        .isoformat()
        .replace("+00:00", "Z"),
        "release_url": f"https://github.com/Lowestofttim/catalyst-releases/releases/tag/{tag}",
        "platforms": {
            "windows-x64": {
                "installer": {
                    "name": installer.name,
                    "url": f"https://github.com/Lowestofttim/catalyst-releases/releases/download/{tag}/{installer.name}",
                    "size": installer.stat().st_size,
                    "sha256": digest,
                }
            }
        },
    }
    key_bytes = bytes(range(32))
    key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    public_key = base64.b64encode(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")
    manifest_path = tmp_path / f"update-manifest-{tag}.json"
    signature_path = tmp_path / f"update-manifest-{tag}.json.sig"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    signature_path.write_text(
        sign_manifest(manifest, base64.b64encode(key_bytes).decode("ascii")),
        encoding="ascii",
    )
    return installer, sidecar, manifest_path, signature_path, tag, public_key


def _check(previous_release):
    installer, sidecar, manifest, signature, tag, public_key = previous_release
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--installer",
            str(installer),
            "--sidecar",
            str(sidecar),
            "--manifest",
            str(manifest),
            "--signature",
            str(signature),
            "--release-ref",
            tag,
            "--public-key-b64",
            public_key,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_historical_signed_installer_verifies_after_manifest_expiry(previous_release):
    result = _check(previous_release)
    assert result.returncode == 0, result.stderr


def test_replaced_installer_and_matching_sidecar_cannot_pass(previous_release):
    installer, sidecar, *_ = previous_release
    installer.write_bytes(b"attacker replacement")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    sidecar.write_text(f"{digest}  {installer.name}", encoding="ascii")
    result = _check(previous_release)
    assert result.returncode != 0


def test_modified_signed_manifest_cannot_pass(previous_release):
    manifest_path = previous_release[2]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tag"] = "v1.4.3"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = _check(previous_release)
    assert result.returncode != 0
