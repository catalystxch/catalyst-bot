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

