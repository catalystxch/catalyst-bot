import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import verify_windows_authenticode as module
from scripts.verify_windows_authenticode import (
    VerificationError,
    build_evidence,
    sha256_file,
    validate_signature_metadata,
)


def valid_metadata() -> dict[str, str]:
    return {
        "status": "Valid",
        "signer_subject": "CN=SignPath Foundation, O=SignPath Foundation",
        "signer_thumbprint": "A" * 40,
        "timestamp_subject": "CN=DigiCert Timestamp 2025",
        "timestamp_thumbprint": "B" * 40,
        "product_name": "CATalyst",
        "product_version": "1.3.17",
        "file_version": "1.3.17.0",
    }


def test_validate_signature_metadata_accepts_expected_release():
    assert validate_signature_metadata(
        valid_metadata(), expected_version="1.3.17"
    ) == valid_metadata()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "NotSigned", "Authenticode status"),
        ("signer_subject", "CN=Unknown Publisher", "publisher"),
        ("signer_thumbprint", "not-a-thumbprint", "signer thumbprint"),
        ("timestamp_subject", "", "timestamp certificate"),
        ("timestamp_thumbprint", "", "timestamp certificate"),
        ("timestamp_thumbprint", "not-a-thumbprint", "timestamp thumbprint"),
        ("product_name", "Other", "product name"),
        ("product_version", "1.3.16", "product version"),
        ("file_version", "1.3.16.0", "file version"),
    ],
)
def test_validate_signature_metadata_rejects_invalid_fields(field, value, message):
    metadata = valid_metadata()
    metadata[field] = value
    with pytest.raises(VerificationError, match=message):
        validate_signature_metadata(metadata, expected_version="1.3.17")


def test_sha256_file_hashes_exact_bytes(tmp_path: Path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"signed-installer")
    assert sha256_file(artifact) == hashlib.sha256(b"signed-installer").hexdigest()


def test_build_evidence_binds_final_bytes_signature_and_origin(tmp_path: Path):
    artifact = tmp_path / "Catalyst-Setup-v1.3.17.exe"
    artifact.write_bytes(b"signed-installer")
    evidence = build_evidence(
        artifact=artifact,
        metadata=valid_metadata(),
        source_repository="catalystxch/catalyst-bot",
        source_tag="v1.3.17",
        source_commit="a" * 40,
        workflow_run_url=(
            "https://github.com/catalystxch/catalyst-bot/actions/runs/123"
        ),
        application_signing_request_id="application-request",
        installer_signing_request_id="installer-request",
    )
    assert evidence == {
        "schema_version": 1,
        "artifact": {
            "name": artifact.name,
            "size_bytes": len(b"signed-installer"),
            "sha256": sha256_file(artifact),
        },
        "signature": {
            "authenticode_status": "Valid",
            "publisher": "SignPath Foundation",
            "signer_subject": valid_metadata()["signer_subject"],
            "signer_thumbprint": "A" * 40,
            "timestamp_status": "Valid",
            "timestamp_subject": valid_metadata()["timestamp_subject"],
            "timestamp_thumbprint": "B" * 40,
            "product_name": "CATalyst",
            "product_version": "1.3.17",
            "file_version": "1.3.17.0",
        },
        "source": {
            "repository": "catalystxch/catalyst-bot",
            "tag": "v1.3.17",
            "commit": "a" * 40,
            "workflow_run_url": (
                "https://github.com/catalystxch/catalyst-bot/actions/runs/123"
            ),
        },
        "signpath": {
            "application_signing_request_id": "application-request",
            "installer_signing_request_id": "installer-request",
        },
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_repository": "somewhere/else"}, "source repository"),
        ({"source_tag": "v1.3.16"}, "source tag"),
        ({"source_commit": "a" * 39}, "source commit"),
        ({"workflow_run_url": "https://example.com/run/1"}, "workflow run URL"),
        ({"application_signing_request_id": ""}, "application signing request"),
        ({"installer_signing_request_id": ""}, "installer signing request"),
    ],
)
def test_build_evidence_rejects_untrusted_origin_fields(
    tmp_path: Path, overrides: dict[str, str], message: str
):
    artifact = tmp_path / "Catalyst-Setup-v1.3.17.exe"
    artifact.write_bytes(b"signed-installer")
    arguments = {
        "artifact": artifact,
        "metadata": valid_metadata(),
        "source_repository": "catalystxch/catalyst-bot",
        "source_tag": "v1.3.17",
        "source_commit": "a" * 40,
        "workflow_run_url": (
            "https://github.com/catalystxch/catalyst-bot/actions/runs/123"
        ),
        "application_signing_request_id": "application-request",
        "installer_signing_request_id": "installer-request",
    }
    arguments.update(overrides)
    with pytest.raises(VerificationError, match=message):
        build_evidence(**arguments)


def test_verify_file_collects_structured_metadata_and_runs_signtool(
    monkeypatch, tmp_path: Path
):
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if str(command[0]).lower().endswith("powershell.exe"):
            return subprocess.CompletedProcess(
                command, 0, json.dumps(valid_metadata()), ""
            )
        return subprocess.CompletedProcess(command, 0, "Successfully verified", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(module, "find_signtool", lambda: Path("signtool.exe"))
    artifact = tmp_path / "Catalyst.exe"
    artifact.write_bytes(b"signed")

    result = module.verify_file(artifact, "1.3.17")

    assert result == valid_metadata()
    powershell_command, powershell_options = calls[0]
    assert str(powershell_command[0]).lower().endswith("powershell.exe")
    assert "Get-AuthenticodeSignature" in powershell_command[-1]
    assert powershell_options["env"]["CATALYST_SIGNATURE_TARGET"] == str(
        artifact.resolve()
    )
    assert calls[1][0] == [
        "signtool.exe",
        "verify",
        "/pa",
        "/all",
        "/v",
        str(artifact.resolve()),
    ]


def test_collect_powershell_metadata_rejects_invalid_json(monkeypatch, tmp_path: Path):
    artifact = tmp_path / "Catalyst.exe"
    artifact.write_bytes(b"signed")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "not-json", ""
        ),
    )

    with pytest.raises(VerificationError, match="invalid JSON"):
        module.collect_powershell_metadata(artifact)


def test_collect_powershell_metadata_rejects_process_failure(
    monkeypatch, tmp_path: Path
):
    artifact = tmp_path / "Catalyst.exe"
    artifact.write_bytes(b"signed")

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="PowerShell failed")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(VerificationError, match="PowerShell signature inspection failed"):
        module.collect_powershell_metadata(artifact)


def test_find_signtool_rejects_missing_sdk_tool(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setattr(module, "WINDOWS_KITS_BIN", Path("Z:/missing/windows-kits"))

    with pytest.raises(VerificationError, match="signtool.exe was not found"):
        module.find_signtool()


def test_run_signtool_rejects_failed_authenticode_verification(
    monkeypatch, tmp_path: Path
):
    artifact = tmp_path / "Catalyst.exe"
    artifact.write_bytes(b"not-signed")

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="No signature found")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(VerificationError, match="signtool verification failed"):
        module.run_signtool(artifact, Path("signtool.exe"))


def test_atomic_json_write_preserves_existing_evidence_on_serialization_failure(
    tmp_path: Path
):
    destination = tmp_path / "windows-signature-v1.3.17.json"
    destination.write_text('{"trusted": true}\n', encoding="utf-8")

    with pytest.raises(TypeError):
        module.write_json_atomic(destination, {"not_json": {object()}})

    assert destination.read_text(encoding="utf-8") == '{"trusted": true}\n'
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []
