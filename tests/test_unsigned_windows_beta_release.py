import hashlib
from argparse import Namespace
from pathlib import Path

import yaml

from scripts.sign_update_manifest import build_manifest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-unsigned-windows-beta.yml"
SIGNED_WORKFLOW = ROOT / ".github" / "workflows" / "build-release.yml"


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def publish_steps() -> list[dict]:
    return load_workflow()["jobs"]["publish-unsigned-windows-beta"]["steps"]


def named_step(name: str) -> dict:
    matches = [step for step in publish_steps() if step.get("name") == name]
    assert len(matches) == 1, f"expected one workflow step named {name!r}"
    return matches[0]


def step_index(name: str) -> int:
    return next(
        index for index, step in enumerate(publish_steps()) if step.get("name") == name
    )


def test_unsigned_beta_release_is_manual_and_uses_fixed_repositories():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "tag:" in workflow
    assert "catalystxch/catalyst-bot" in workflow
    assert "Lowestofttim/catalyst-releases" in workflow
    assert (
        "repository:"
        not in workflow.split("workflow_dispatch:", 1)[1].split("permissions:", 1)[0]
    )


def test_v140_beta_tag_cannot_trigger_stable_signed_release_workflow():
    workflow = yaml.safe_load(SIGNED_WORKFLOW.read_text(encoding="utf-8"))
    for job in ("build", "publish-release"):
        assert "github.ref_name != 'v1.4.0'" in workflow["jobs"][job]["if"]


def test_unsigned_bytes_are_proven_and_smoked_before_manifest_signing():
    ordered = [
        "Validate release tag",
        "Download official Windows release assets",
        "Prove installer identity and unsigned status",
        "Install and smoke test the downloaded release",
        "Generate signed update metadata",
        "Publish unsigned beta update channel",
    ]
    positions = [step_index(name) for name in ordered]
    assert positions == sorted(positions)

    proof = named_step("Prove installer identity and unsigned status")["run"]
    assert "Get-FileHash" in proof
    assert "Get-AuthenticodeSignature" in proof
    assert 'Status -ne "NotSigned"' in proof
    assert "ProductVersion" in proof
    assert "MpCmdRun.exe" in proof

    smoke = named_step("Install and smoke test the downloaded release")["run"]
    for script in (
        "packaged_sage_rpc_smoke.py",
        "packaged_api_smoke.py",
        "packaged_desktop_first_launch_smoke.py",
        "packaged_upgrade_publication_recovery_smoke.py",
    ):
        assert script in smoke
    assert 'Status -ne "NotSigned"' in smoke
    assert "MpCmdRun.exe" in smoke


def test_unsigned_beta_keeps_signed_updater_metadata_without_fake_signature_evidence():
    metadata = named_step("Generate signed update metadata")
    assert metadata["env"]["CATALYST_UPDATE_SIGNING_KEY_B64"] == (
        "${{ secrets.CATALYST_UPDATE_SIGNING_KEY_B64 }}"
    )
    assert "scripts/sign_update_manifest.py" in metadata["run"]
    assert "latest.json.sig" in metadata["run"]
    assert "release_notes_unsigned_beta.md" in metadata["run"]
    assert "unsigned Windows beta" in metadata["run"]
    assert "SmartScreen" in metadata["run"]
    assert "--release-notes-file release_notes_unsigned_beta.md" in metadata["run"]

    publication = named_step("Publish unsigned beta update channel")
    assert publication["env"]["GH_TOKEN"] == (
        "${{ secrets.CATALYST_RELEASE_CHANNEL_TOKEN }}"
    )
    script = publication["run"]
    assert "Catalyst-Setup-$($env:RELEASE_REF).exe" in script
    assert "latest.json" in script
    assert "latest.json.sig" in script
    assert "update-manifest-$($env:RELEASE_REF).json" in script
    assert "windows-signature" not in script
    assert "unsigned Windows beta" in script


def test_publication_is_immutable_and_staged_as_prerelease():
    script = named_step("Publish unsigned beta update channel")["run"]
    assert "Release channel tag already exists" in script
    assert "--clobber" not in script
    assert "--draft" in script
    assert "gh release upload" in script
    assert "--draft=false" in script
    assert "--prerelease" in script
    assert "--latest=false" in script
    assert "--latest\n" not in script

    existing_check = script.index("gh release view")
    draft_create = script.index("gh release create")
    upload = script.index("gh release upload")
    publish = script.index("--draft=false")
    assert existing_check < draft_create < upload < publish


def test_release_tag_is_validated_as_an_immutable_main_ancestor():
    validation = named_step("Validate release tag")["run"]
    assert "refs/tags/$($env:RELEASE_REF)" in validation
    assert "merge-base --is-ancestor" in validation
    assert "git fetch" in validation
    assert "isPrerelease" in validation


def test_unsigned_beta_manifest_marks_beta_channel(tmp_path):
    installer = tmp_path / "Catalyst-Setup-v1.4.0.exe"
    installer.write_bytes(b"unsigned beta installer fixture")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    sidecar = tmp_path / f"{installer.name}.sha256"
    sidecar.write_text(f"{digest}  {installer.name}\n", encoding="utf-8")
    args = Namespace(
        version="v1.4.0",
        channel="beta",
        installer=installer,
        sha256_file=sidecar,
        download_base_url="https://github.com/Lowestofttim/catalyst-releases/releases/download/v1.4.0",
        release_url="https://github.com/Lowestofttim/catalyst-releases/releases/tag/v1.4.0",
        release_notes_file=None,
        expires_days=90,
    )

    manifest = build_manifest(args)

    assert manifest["channel"] == "beta"
    assert manifest["platforms"]["windows-x64"]["installer"]["sha256"] == digest


def test_unsigned_beta_workflow_signs_beta_channel():
    metadata = named_step("Generate signed update metadata")["run"]
    assert "--channel beta" in metadata
