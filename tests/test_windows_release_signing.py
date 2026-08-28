from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-release.yml"
SIGNPATH_ACTION = (
    "signpath/github-action-submit-signing-request@"
    "c92b958760219087e01f8d67a1669ed57afe2627"
)
UPLOAD_ACTION = (
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
)


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def build_steps() -> list[dict]:
    return load_workflow()["jobs"]["build"]["steps"]


def named_step(name: str) -> dict:
    matches = [step for step in build_steps() if step.get("name") == name]
    assert len(matches) == 1, f"expected exactly one workflow step named {name!r}"
    return matches[0]


def step_index(name: str) -> int:
    return next(
        index for index, step in enumerate(build_steps()) if step.get("name") == name
    )


def test_application_signature_is_required_before_windows_packaging():
    assert step_index("Upload unsigned CATalyst application for SignPath") < step_index(
        "Sign CATalyst application with SignPath"
    )
    assert step_index("Sign CATalyst application with SignPath") < step_index(
        "Replace and verify signed CATalyst application"
    )
    assert step_index("Replace and verify signed CATalyst application") < step_index(
        "Package signed Windows zip"
    )
    assert step_index("Package signed Windows zip") < step_index(
        "Build Windows installer from signed application"
    )


def test_application_signing_uses_pinned_actions_and_exact_policy():
    upload = named_step("Upload unsigned CATalyst application for SignPath")
    assert upload["uses"] == UPLOAD_ACTION
    assert upload["id"] == "upload-unsigned-application"
    assert upload["with"] == {
        "name": "catalyst-windows-application-${{ github.run_id }}-${{ github.run_attempt }}",
        "path": "dist/Catalyst/Catalyst.exe",
        "archive": False,
    }

    signing = named_step("Sign CATalyst application with SignPath")
    assert signing["uses"] == SIGNPATH_ACTION
    assert signing["id"] == "sign-application"
    assert signing["with"] == {
        "api-token": "${{ secrets.SIGNPATH_API_TOKEN }}",
        "organization-id": "${{ vars.SIGNPATH_ORGANIZATION_ID }}",
        "project-slug": "catalyst",
        "signing-policy-slug": "release-signing",
        "artifact-configuration-slug": "catalyst-windows-application-v1",
        "github-artifact-id": (
            "${{ steps.upload-unsigned-application.outputs.artifact-id }}"
        ),
        "wait-for-completion": True,
        "wait-for-completion-timeout-in-seconds": 7200,
        "output-artifact-directory": "signed/application",
        "skip-decompress": True,
        "parameters": (
            'version: "${{ steps.release-version.outputs.version }}"\n'
        ),
    }


def test_signing_preflight_fails_closed_without_required_configuration():
    workflow = load_workflow()
    assert workflow["permissions"]["actions"] == "read"
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["jobs"]["build"]["timeout-minutes"] == 360

    version = named_step("Resolve release version")
    assert version["id"] == "release-version"
    assert "GITHUB_OUTPUT" in version["run"]

    preflight = named_step("Require Windows release signing configuration")
    assert preflight["env"] == {
        "SIGNPATH_API_TOKEN": "${{ secrets.SIGNPATH_API_TOKEN }}",
        "SIGNPATH_ORGANIZATION_ID": "${{ vars.SIGNPATH_ORGANIZATION_ID }}",
        "CATALYST_UPDATE_SIGNING_KEY_B64": (
            "${{ secrets.CATALYST_UPDATE_SIGNING_KEY_B64 }}"
        ),
        "CATALYST_RELEASE_CHANNEL_TOKEN": (
            "${{ secrets.CATALYST_RELEASE_CHANNEL_TOKEN }}"
        ),
    }
    for name in preflight["env"]:
        assert f"{name} is required" in preflight["run"]


def test_signed_application_replaces_unsigned_bytes_before_verification():
    replacement = named_step("Replace and verify signed CATalyst application")
    assert replacement["env"]["RELEASE_VERSION"] == (
        "${{ steps.release-version.outputs.version }}"
    )
    script = replacement["run"]
    copy_position = script.index("Copy-Item")
    verify_position = script.index("verify_windows_authenticode.py")
    assert "signed/application/Catalyst.exe" in script
    assert "dist/Catalyst/Catalyst.exe" in script
    assert copy_position < verify_position


def test_installer_signature_precedes_final_byte_metadata_and_publication():
    ordered_names = [
        "Build Windows installer from signed application",
        "Upload unsigned Windows installer for SignPath",
        "Sign Windows installer with SignPath",
        "Replace and verify signed Windows installer",
        "Generate signed-installer checksum and update manifest",
        "Smoke test signed Windows installer payload",
        "Upload signed Windows installer to Release",
        "Publish verified public update channel",
    ]
    positions = [step_index(name) for name in ordered_names]
    assert positions == sorted(positions)


def test_installer_signing_uses_pinned_action_and_evidence_request_ids():
    upload = named_step("Upload unsigned Windows installer for SignPath")
    assert upload["uses"] == UPLOAD_ACTION
    assert upload["id"] == "upload-unsigned-installer"
    assert upload["with"] == {
        "name": "catalyst-windows-installer-${{ github.run_id }}-${{ github.run_attempt }}",
        "path": "Catalyst-Setup-${{ github.ref_name }}.exe",
        "archive": False,
    }

    signing = named_step("Sign Windows installer with SignPath")
    assert signing["uses"] == SIGNPATH_ACTION
    assert signing["id"] == "sign-installer"
    assert signing["with"]["artifact-configuration-slug"] == (
        "catalyst-windows-installer-v1"
    )
    assert signing["with"]["github-artifact-id"] == (
        "${{ steps.upload-unsigned-installer.outputs.artifact-id }}"
    )
    assert signing["with"]["output-artifact-directory"] == "signed/installer"
    assert signing["with"]["skip-decompress"] is True

    verification = named_step("Replace and verify signed Windows installer")
    assert verification["env"]["APPLICATION_SIGNING_REQUEST_ID"] == (
        "${{ steps.sign-application.outputs.signing-request-id }}"
    )
    assert verification["env"]["INSTALLER_SIGNING_REQUEST_ID"] == (
        "${{ steps.sign-installer.outputs.signing-request-id }}"
    )
    assert "--evidence-output" in verification["run"]
    assert "windows-signature-$($env:RELEASE_REF).json" in verification["run"]


def test_unsigned_installer_build_cannot_generate_final_metadata():
    build = named_step("Build Windows installer from signed application")["run"]
    assert "ISCC.exe" in build
    assert "Get-FileHash" not in build
    assert "sign_update_manifest.py" not in build
    assert ".sha256" not in build

    final_metadata = named_step(
        "Generate signed-installer checksum and update manifest"
    )["run"]
    assert "Get-FileHash" in final_metadata
    assert "sign_update_manifest.py" in final_metadata
    assert "CATALYST_UPDATE_SIGNING_KEY_B64 secret is required" in final_metadata


def test_missing_publication_token_cannot_create_unsigned_fallback():
    publication = named_step("Publish verified public update channel")["run"]
    assert "skipping public update channel publish" not in publication.lower()
    assert "CATALYST_RELEASE_CHANNEL_TOKEN is required" in publication
    assert "exit 0" not in publication


def test_signed_installer_evidence_is_uploaded_to_both_release_repositories():
    expected = '"windows-signature-$($env:RELEASE_REF).json"'
    source_upload = named_step("Upload signed Windows installer to Release")["run"]
    public_upload = named_step("Publish verified public update channel")["run"]
    assert expected in source_upload
    assert expected in public_upload
