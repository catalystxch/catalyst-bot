"""Authenticate an earlier stable installer before executing upgrade smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "catalyst"))

from app_update import (  # noqa: E402
    UPDATE_MANIFEST_PUBLIC_KEY_B64,
    select_windows_manifest_installer,
    verify_signed_manifest,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_previous_installer(
    *,
    installer: Path,
    sidecar: Path,
    manifest_path: Path,
    signature_path: Path,
    release_ref: str,
    public_key_b64: str = UPDATE_MANIFEST_PUBLIC_KEY_B64,
) -> str:
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", release_ref) is None:
        raise ValueError("previous release tag is invalid")
    installer_name = f"Catalyst-Setup-{release_ref}.exe"
    if (
        installer.name != installer_name
        or sidecar.name != f"{installer_name}.sha256"
        or manifest_path.name != f"update-manifest-{release_ref}.json"
        or signature_path.name != f"update-manifest-{release_ref}.json.sig"
    ):
        raise ValueError("previous release asset name does not match tag")

    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError("previous update manifest is not an object")
    published = datetime.fromisoformat(
        str(manifest.get("published_at") or "").replace("Z", "+00:00")
    )
    if published.tzinfo is None:
        raise ValueError("previous update manifest publication time lacks timezone")
    # Historical manifests may have expired for update offers. Their signed
    # publication time still lets us verify the exact historical installer.
    verified = verify_signed_manifest(
        manifest,
        signature_path.read_text(encoding="ascii"),
        public_b64=public_key_b64,
        now=published,
    )
    if verified.get("tag") != release_ref or verified.get("version") != release_ref[1:]:
        raise ValueError("previous signed manifest version does not match tag")
    expected_release_url = (
        f"https://github.com/Lowestofttim/catalyst-releases/releases/tag/{release_ref}"
    )
    if verified.get("release_url") != expected_release_url:
        raise ValueError("previous signed release URL is not the public channel")
    metadata = select_windows_manifest_installer(verified)
    if metadata is None:
        raise ValueError("previous signed manifest installer is invalid")
    digest = _sha256_file(installer)
    if (
        metadata["name"] != installer_name
        or metadata["size"] != installer.stat().st_size
        or metadata["sha256"] != digest
    ):
        raise ValueError("previous installer differs from signed update manifest")
    if sidecar.read_text(encoding="ascii").strip() != f"{digest}  {installer_name}":
        raise ValueError("previous installer digest differs from sidecar")
    if _sha256_file(installer) != digest:
        raise ValueError("previous installer changed during verification")
    return digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--signature", required=True, type=Path)
    parser.add_argument("--release-ref", required=True)
    parser.add_argument("--public-key-b64", default=UPDATE_MANIFEST_PUBLIC_KEY_B64)
    args = parser.parse_args(argv)
    verify_previous_installer(
        installer=args.installer,
        sidecar=args.sidecar,
        manifest_path=args.manifest,
        signature_path=args.signature,
        release_ref=args.release_ref,
        public_key_b64=args.public_key_b64,
    )
    print(f"Verified signed previous stable installer for {args.release_ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
