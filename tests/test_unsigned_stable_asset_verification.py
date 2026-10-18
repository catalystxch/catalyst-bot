"""Final byte checks before staging an unsigned stable release."""

import base64
import hashlib
import json
from argparse import Namespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.sign_update_manifest import build_manifest, sign_manifest
from scripts.verify_unsigned_stable_assets import verify_staged_assets


@pytest.fixture
def staged_assets(tmp_path):
    tag = "v1.5.0"
    source_commit = "a" * 40
    repository = "Lowestofttim/catalyst-releases"
    installer = tmp_path / f"Catalyst-Setup-{tag}.exe"
    installer.write_bytes(b"unsigned stable installer fixture")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    sidecar = tmp_path / f"{installer.name}.sha256"
    sidecar.write_text(f"{digest}  {installer.name}", encoding="ascii")
    args = Namespace(
        version=tag,
        channel="stable",
        installer=installer,
        sha256_file=sidecar,
        download_base_url=f"https://github.com/{repository}/releases/download/{tag}",
        release_url=f"https://github.com/{repository}/releases/tag/{tag}",
        release_notes_file=None,
        expires_days=90,
        source_commit=source_commit,
    )
    manifest = build_manifest(args)
    key_bytes = bytes(range(32))
    private_key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    public_key_b64 = base64.b64encode(
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")
    manifest_path = tmp_path / "latest.json"
    signature_path = tmp_path / "latest.json.sig"
    versioned_manifest_path = tmp_path / f"update-manifest-{tag}.json"
    versioned_signature_path = tmp_path / f"update-manifest-{tag}.json.sig"
    manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    signature_bytes = (
        sign_manifest(manifest, base64.b64encode(key_bytes).decode("ascii")) + "\n"
    ).encode()
    manifest_path.write_bytes(manifest_bytes)
    signature_path.write_bytes(signature_bytes)
    versioned_manifest_path.write_bytes(manifest_bytes)
    versioned_signature_path.write_bytes(signature_bytes)
    return {
        "installer": installer,
        "sidecar": sidecar,
        "manifest_path": manifest_path,
        "signature_path": signature_path,
        "versioned_manifest_path": versioned_manifest_path,
        "versioned_signature_path": versioned_signature_path,
        "release_ref": tag,
        "source_commit": source_commit,
        "release_channel_repository": repository,
        "public_key_b64": public_key_b64,
    }


def test_final_assets_verify_exact_bytes_and_source(staged_assets):
    result = verify_staged_assets(**staged_assets)
    assert result["source_commit"] == "a" * 40
    assert (
        result["installer_sha256"]
        == hashlib.sha256(staged_assets["installer"].read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "changed_file",
    ("installer", "sidecar", "versioned_manifest_path", "signature_path"),
)
def test_final_assets_reject_any_changed_byte(staged_assets, changed_file):
    path = staged_assets[changed_file]
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        verify_staged_assets(**staged_assets)


def test_final_assets_reject_resigned_wrong_source(staged_assets):
    manifest_path = staged_assets["manifest_path"]
    manifest = json.loads(manifest_path.read_bytes())
    manifest["source_commit"] = "b" * 40
    changed = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    manifest_path.write_bytes(changed)
    staged_assets["versioned_manifest_path"].write_bytes(changed)
    signature = sign_manifest(
        manifest, base64.b64encode(bytes(range(32))).decode("ascii")
    )
    staged_assets["signature_path"].write_text(signature + "\n", encoding="ascii")
    staged_assets["versioned_signature_path"].write_text(
        signature + "\n", encoding="ascii"
    )
    with pytest.raises(ValueError, match="source commit"):
        verify_staged_assets(**staged_assets)
