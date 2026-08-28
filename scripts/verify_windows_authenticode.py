"""Verify CATalyst Windows release signatures and emit public evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse


EXPECTED_REPOSITORY = "catalystxch/catalyst-bot"
EXPECTED_PUBLISHER = "SignPath Foundation"
EXPECTED_PRODUCT = "CATalyst"
WINDOWS_KITS_BIN = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")

POWERSHELL_SIGNATURE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $env:CATALYST_SIGNATURE_TARGET
$version = (Get-Item -LiteralPath $env:CATALYST_SIGNATURE_TARGET).VersionInfo
[pscustomobject]@{
  status = [string]$signature.Status
  signer_subject = [string]$signature.SignerCertificate.Subject
  signer_thumbprint = [string]$signature.SignerCertificate.Thumbprint
  timestamp_subject = [string]$signature.TimeStamperCertificate.Subject
  timestamp_thumbprint = [string]$signature.TimeStamperCertificate.Thumbprint
  product_name = [string]$version.ProductName
  product_version = [string]$version.ProductVersion
  file_version = [string]$version.FileVersion
} | ConvertTo-Json -Compress
""".strip()


class VerificationError(ValueError):
    """Raised when a Windows release signature cannot be proven valid."""


def sha256_file(path: Path) -> str:
    """Return the lower-case SHA-256 digest of *path*."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_subject_value(subject: str, value: str) -> bool:
    return bool(
        re.search(
            rf"(?:^|,\s*)(?:CN|O)={re.escape(value)}(?:,|$)",
            subject,
            re.IGNORECASE,
        )
    )


def validate_signature_metadata(
    metadata: Mapping[str, object],
    expected_version: str,
    expected_publisher: str = EXPECTED_PUBLISHER,
    expected_product: str = EXPECTED_PRODUCT,
) -> dict[str, str]:
    """Validate structured Authenticode and PE version metadata."""

    fields = (
        "status",
        "signer_subject",
        "signer_thumbprint",
        "timestamp_subject",
        "timestamp_thumbprint",
        "product_name",
        "product_version",
        "file_version",
    )
    values = {key: str(metadata.get(key) or "").strip() for key in fields}
    if values["status"] != "Valid":
        raise VerificationError(
            f"Authenticode status is {values['status'] or 'missing'}"
        )
    if not _has_subject_value(values["signer_subject"], expected_publisher):
        raise VerificationError(f"publisher is not {expected_publisher}")
    if not re.fullmatch(r"[A-Fa-f0-9]{40}", values["signer_thumbprint"]):
        raise VerificationError("signer thumbprint is invalid")
    if not values["timestamp_subject"] or not values["timestamp_thumbprint"]:
        raise VerificationError("timestamp certificate is missing")
    if not re.fullmatch(r"[A-Fa-f0-9]{40}", values["timestamp_thumbprint"]):
        raise VerificationError("timestamp thumbprint is invalid")
    if values["product_name"] != expected_product:
        raise VerificationError(f"product name is not {expected_product}")
    if values["product_version"] != expected_version:
        raise VerificationError("product version does not match the release")
    if values["file_version"] != f"{expected_version}.0":
        raise VerificationError("file version does not match the release")
    values["signer_thumbprint"] = values["signer_thumbprint"].upper()
    values["timestamp_thumbprint"] = values["timestamp_thumbprint"].upper()
    return values


def _validate_origin(
    *,
    version: str,
    source_repository: str,
    source_tag: str,
    source_commit: str,
    workflow_run_url: str,
    application_signing_request_id: str,
    installer_signing_request_id: str,
) -> None:
    if source_repository != EXPECTED_REPOSITORY:
        raise VerificationError("source repository is not the CATalyst repository")
    if source_tag != f"v{version}":
        raise VerificationError("source tag does not match the signed version")
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise VerificationError("source commit is not a lower-case 40-character SHA")
    workflow_url = urlparse(workflow_run_url)
    expected_prefix = f"/{EXPECTED_REPOSITORY}/actions/runs/"
    if (
        workflow_url.scheme != "https"
        or workflow_url.netloc != "github.com"
        or not workflow_url.path.startswith(expected_prefix)
        or not workflow_url.path.removeprefix(expected_prefix).isdigit()
        or workflow_url.query
        or workflow_url.fragment
    ):
        raise VerificationError("workflow run URL is not a CATalyst GitHub Actions run")
    if not application_signing_request_id.strip():
        raise VerificationError("application signing request ID is missing")
    if not installer_signing_request_id.strip():
        raise VerificationError("installer signing request ID is missing")


def build_evidence(
    artifact: Path,
    metadata: Mapping[str, object],
    source_repository: str,
    source_tag: str,
    source_commit: str,
    workflow_run_url: str,
    application_signing_request_id: str,
    installer_signing_request_id: str,
) -> dict[str, object]:
    """Bind verified signature metadata to exact final artifact bytes and origin."""

    if not artifact.is_file():
        raise VerificationError(f"artifact is not a file: {artifact}")
    version = str(metadata.get("product_version") or "").strip()
    verified = validate_signature_metadata(metadata, expected_version=version)
    _validate_origin(
        version=version,
        source_repository=source_repository,
        source_tag=source_tag,
        source_commit=source_commit,
        workflow_run_url=workflow_run_url,
        application_signing_request_id=application_signing_request_id,
        installer_signing_request_id=installer_signing_request_id,
    )
    return {
        "schema_version": 1,
        "artifact": {
            "name": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
        },
        "signature": {
            "authenticode_status": verified["status"],
            "publisher": EXPECTED_PUBLISHER,
            "signer_subject": verified["signer_subject"],
            "signer_thumbprint": verified["signer_thumbprint"],
            "timestamp_status": "Valid",
            "timestamp_subject": verified["timestamp_subject"],
            "timestamp_thumbprint": verified["timestamp_thumbprint"],
            "product_name": verified["product_name"],
            "product_version": verified["product_version"],
            "file_version": verified["file_version"],
        },
        "source": {
            "repository": source_repository,
            "tag": source_tag,
            "commit": source_commit,
            "workflow_run_url": workflow_run_url,
        },
        "signpath": {
            "application_signing_request_id": application_signing_request_id,
            "installer_signing_request_id": installer_signing_request_id,
        },
    }


def collect_powershell_metadata(path: Path) -> dict[str, str]:
    """Collect signature and PE metadata without parsing localized status text."""

    target = path.resolve()
    if not target.is_file():
        raise VerificationError(f"signature target is not a file: {target}")
    environment = os.environ.copy()
    environment["CATALYST_SIGNATURE_TARGET"] = str(target)
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        POWERSHELL_SIGNATURE_SCRIPT,
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
    except FileNotFoundError as exc:
        raise VerificationError("powershell.exe was not found") from exc
    except subprocess.CalledProcessError as exc:
        raise VerificationError("PowerShell signature inspection failed") from exc
    try:
        metadata = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError("PowerShell returned invalid JSON") from exc
    if not isinstance(metadata, dict):
        raise VerificationError("PowerShell signature metadata is not an object")
    return {str(key): str(value or "") for key, value in metadata.items()}


def _sdk_version_key(path: Path) -> tuple[int, ...]:
    version = path.parent.parent.name
    if not re.fullmatch(r"\d+(?:\.\d+)+", version):
        return ()
    return tuple(int(part) for part in version.split("."))


def find_signtool() -> Path:
    """Find signtool.exe on PATH or in the newest installed Windows SDK."""

    from_path = shutil.which("signtool.exe")
    if from_path:
        return Path(from_path)
    candidates = (
        list(WINDOWS_KITS_BIN.glob("*/x64/signtool.exe"))
        if WINDOWS_KITS_BIN.is_dir()
        else []
    )
    versioned = [candidate for candidate in candidates if _sdk_version_key(candidate)]
    if not versioned:
        raise VerificationError("signtool.exe was not found in PATH or Windows SDK")
    return max(versioned, key=_sdk_version_key)


def run_signtool(path: Path, signtool: Path) -> None:
    """Apply the Windows Authenticode policy verifier to one PE file."""

    command = [
        str(signtool),
        "verify",
        "/pa",
        "/all",
        "/v",
        str(path.resolve()),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise VerificationError("signtool.exe could not be executed") from exc
    except subprocess.CalledProcessError as exc:
        raise VerificationError("signtool verification failed") from exc


def verify_file(path: Path, expected_version: str) -> dict[str, str]:
    """Verify a CATalyst PE through both PowerShell and Windows SDK policy."""

    target = path.resolve()
    metadata = collect_powershell_metadata(target)
    verified = validate_signature_metadata(metadata, expected_version)
    run_signtool(target, find_signtool())
    return verified


def write_json_atomic(destination: Path, value: Mapping[str, object]) -> None:
    """Write JSON atomically so failed runs cannot leave trusted-looking evidence."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(destination)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--source-repository")
    parser.add_argument("--source-tag")
    parser.add_argument("--source-commit")
    parser.add_argument("--workflow-run-url")
    parser.add_argument("--application-signing-request-id")
    parser.add_argument("--installer-signing-request-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        metadata = verify_file(args.file, args.expected_version)
        result: Mapping[str, object] = metadata
        if args.evidence_output is not None:
            evidence_fields = {
                "source_repository": args.source_repository,
                "source_tag": args.source_tag,
                "source_commit": args.source_commit,
                "workflow_run_url": args.workflow_run_url,
                "application_signing_request_id": (
                    args.application_signing_request_id
                ),
                "installer_signing_request_id": args.installer_signing_request_id,
            }
            missing = [key for key, value in evidence_fields.items() if not value]
            if missing:
                raise VerificationError(
                    "evidence output requires: " + ", ".join(sorted(missing))
                )
            result = build_evidence(
                artifact=args.file.resolve(),
                metadata=metadata,
                **evidence_fields,
            )
            write_json_atomic(args.evidence_output.resolve(), result)
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
        return 0
    except (OSError, VerificationError) as exc:
        sys.stderr.write(f"Windows signature verification failed: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
