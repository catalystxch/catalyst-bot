from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-unsigned-windows-beta.yml"


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


def test_release_tag_is_validated_as_an_immutable_main_ancestor():
    validation = named_step("Validate release tag")["run"]
    assert "refs/tags/$($env:RELEASE_REF)" in validation
    assert "merge-base --is-ancestor" in validation
    assert "git fetch" in validation
