"""Recheck final unsigned stable release bytes before staging publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "catalyst"))

from app_update import (  # noqa: E402
    UPDATE_MANIFEST_PUBLIC_KEY_B64,
    verify_signed_manifest,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_staged_assets(
    *,
    installer: Path,
    sidecar: Path,
    manifest_path: Path,
    signature_path: Path,
    versioned_manifest_path: Path,
    versioned_signature_path: Path,
    release_ref: str,
    source_commit: str,
    release_channel_repository: str,
    public_key_b64: str = UPDATE_MANIFEST_PUBLIC_KEY_B64,
) -> dict[str, str]:
    if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", release_ref) is None:
        raise ValueError("release tag is invalid")
    if re.fullmatch(r"[a-f0-9]{40}", source_commit) is None:
        raise ValueError("source commit is invalid")
    if release_channel_repository != "Lowestofttim/catalyst-releases":
        raise ValueError("release channel repository is invalid")

    paths = (
        installer,
        sidecar,
        manifest_path,
        signature_path,
        versioned_manifest_path,
        versioned_signature_path,
    )
    if any(not path.is_file() for path in paths):
        raise ValueError("a staged release asset is missing")
    installer_name = f"Catalyst-Setup-{release_ref}.exe"
    if (
        installer.name != installer_name
        or sidecar.name != f"{installer_name}.sha256"
        or manifest_path.name != "latest.json"
        or signature_path.name != "latest.json.sig"
        or versioned_manifest_path.name != f"update-manifest-{release_ref}.json"
        or versioned_signature_path.name != f"update-manifest-{release_ref}.json.sig"
    ):
        raise ValueError("staged asset name does not match release tag")

    digest = _sha256_file(installer)
    sidecar_line = sidecar.read_text(encoding="ascii")
    if sidecar_line != f"{digest}  {installer_name}":
        raise ValueError("installer digest does not match sidecar")
    manifest_bytes = manifest_path.read_bytes()
    signature_bytes = signature_path.read_bytes()
    if (
        versioned_manifest_path.read_bytes() != manifest_bytes
        or versioned_signature_path.read_bytes() != signature_bytes
    ):
        raise ValueError("versioned update metadata differs from latest")

    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("update manifest is not an object")
    verified = verify_signed_manifest(
        manifest,
        signature_bytes.decode("ascii"),
        public_b64=public_key_b64,
    )
    download_base = (
        f"https://github.com/{release_channel_repository}/releases/download/"
        f"{release_ref}"
    )
    expected_release_url = (
        f"https://github.com/{release_channel_repository}/releases/tag/{release_ref}"
    )
    installer_metadata = (
        verified.get("platforms", {}).get("windows-x64", {}).get("installer", {})
    )
    expected = {
        "tag": (verified.get("tag"), release_ref),
        "version": (verified.get("version"), release_ref[1:]),
        "source commit": (verified.get("source_commit"), source_commit),
        "release URL": (verified.get("release_url"), expected_release_url),
        "installer name": (installer_metadata.get("name"), installer_name),
        "installer URL": (
            installer_metadata.get("url"),
            f"{download_base}/{installer_name}",
        ),
        "installer size": (installer_metadata.get("size"), installer.stat().st_size),
        "installer digest": (installer_metadata.get("sha256"), digest),
    }
    for name, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ValueError(f"signed manifest {name} does not match staged assets")
    if _sha256_file(installer) != digest:
        raise ValueError("installer changed during final verification")
    return {"source_commit": source_commit, "installer_sha256": digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--signature", required=True, type=Path)
    parser.add_argument("--versioned-manifest", required=True, type=Path)
    parser.add_argument("--versioned-signature", required=True, type=Path)
    parser.add_argument("--release-ref", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--release-channel-repository", required=True)
    args = parser.parse_args(argv)
    verify_staged_assets(
        installer=args.installer,
        sidecar=args.sidecar,
        manifest_path=args.manifest,
        signature_path=args.signature,
        versioned_manifest_path=args.versioned_manifest,
        versioned_signature_path=args.versioned_signature,
        release_ref=args.release_ref,
        source_commit=args.source_commit,
        release_channel_repository=args.release_channel_repository,
    )
    print(f"Verified staged unsigned stable assets for {args.release_ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
