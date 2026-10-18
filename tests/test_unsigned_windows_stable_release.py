"""Release gates for the opt-in unsigned stable Windows workflow."""

import hashlib
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from scripts.sign_update_manifest import build_manifest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-unsigned-windows-stable.yml"
POLICY = ROOT / "docs" / "CODE_SIGNING_POLICY.md"


def workflow_and_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow, workflow["jobs"]["publish-unsigned-windows-stable"]["steps"]


def step(steps, name):
    matches = [item for item in steps if item.get("name") == name]
    assert len(matches) == 1, name
    return matches[0]


def test_unsigned_stable_release_requires_manual_exact_tag():
    workflow, steps = workflow_and_steps()
    trigger = workflow[True]  # YAML 1.1 parses `on` as True.
    assert "push" not in trigger
    assert trigger["workflow_dispatch"]["inputs"]["tag"]["required"] is True
    assert step(steps, "Checkout trusted main release tooling")["with"]["ref"] == "main"
    assert workflow["permissions"]["contents"] == "read"


def test_final_verifier_uses_trusted_main_tooling_after_tag_checkout():
    _, steps = workflow_and_steps()
    names = [item.get("name") for item in steps]
    assert names.index("Stage trusted stable verification tooling") < names.index(
        "Build unsigned Windows installer from exact release tag"
    )
    staging = step(steps, "Stage trusted stable verification tooling")["run"]
    assert "verify_unsigned_stable_assets.py" in staging
    assert "sign_update_manifest.py" in staging
    assert "app_update.py" in staging
    verification = step(steps, "Verify staged unsigned stable bytes")["run"]
    assert (
        "stable-release-tooling/scripts/verify_unsigned_stable_assets.py"
        in verification
    )
    signing = step(steps, "Generate signed update metadata")["run"]
    assert "stable-release-tooling/scripts/sign_update_manifest.py" in signing


def test_unsigned_stable_gates_precede_publication():
    _, steps = workflow_and_steps()
    names = [item.get("name") for item in steps]
    ordered = [
        "Validate release tag",
        "Build unsigned Windows installer from exact release tag",
        "Prove installer identity and unsigned status",
        "Install and smoke test the downloaded release",
        "Generate signed update metadata",
        "Verify staged unsigned stable bytes",
        "Publish unsigned stable update channel",
    ]
    assert [names.index(name) for name in ordered] == sorted(
        names.index(name) for name in ordered
    )


def test_source_and_wallet_effect_gates_fail_closed():
    _, steps = workflow_and_steps()
    validation = step(steps, "Validate release tag")["run"]
    assert "^v[0-9]+\\.[0-9]+\\.[0-9]+$" in validation
    assert "+refs/heads/main:refs/remotes/origin/main" in validation
    assert "git merge-base --is-ancestor" in validation
    assert "gh release view" in validation
    assert "isDraft" in validation and "isPrerelease" in validation
    assert "tagName" in validation and "throw" in validation
    build = step(steps, "Build unsigned Windows installer from exact release tag")[
        "run"
    ]
    assert "git checkout --detach" in build
    assert "git rev-parse HEAD" in build
    assert "python build.py" in build and "ISCC.exe" in build
    assert "Get-FileHash" in build


def test_exact_unsigned_bytes_defender_and_packaged_smokes():
    _, steps = workflow_and_steps()
    proof = step(steps, "Prove installer identity and unsigned status")["run"]
    assert "Get-FileHash" in proof
    assert "sidecar" in proof
    assert "Get-AuthenticodeSignature" in proof
    assert 'Status -ne "NotSigned"' in proof
    assert "ProductVersion" in proof
    assert "MpCmdRun.exe" in proof
    smoke = step(steps, "Install and smoke test the downloaded release")["run"]
    for script in (
        "packaged_sage_rpc_smoke.py",
        "packaged_api_smoke.py",
        "packaged_desktop_first_launch_smoke.py",
        "packaged_upgrade_publication_recovery_smoke.py",
    ):
        assert script in smoke
    assert 'Status -ne "NotSigned"' in smoke
    assert "MpCmdRun.exe" in smoke


def test_signed_stable_manifest_and_immutable_latest_publication():
    _, steps = workflow_and_steps()
    metadata = step(steps, "Generate signed update metadata")
    assert metadata["env"]["CATALYST_UPDATE_SIGNING_KEY_B64"] == (
        "${{ secrets.CATALYST_UPDATE_SIGNING_KEY_B64 }}"
    )
    assert "IsNullOrWhiteSpace" in metadata["run"]
    assert "--source-commit $env:SOURCE_COMMIT" in metadata["run"]
    assert "--channel beta" not in metadata["run"]
    assert "latest.json.sig" in metadata["run"]
    assert "unsigned windows release" in metadata["run"].lower()
    final_check = step(steps, "Verify staged unsigned stable bytes")["run"]
    assert "verify_unsigned_stable_assets.py" in final_check
    assert "--source-commit $env:SOURCE_COMMIT" in final_check
    assert 'Status -ne "NotSigned"' in final_check
    publication = step(steps, "Publish unsigned stable update channel")
    assert publication["env"]["GH_TOKEN"] == (
        "${{ secrets.CATALYST_RELEASE_CHANNEL_TOKEN }}"
    )
    script = publication["run"]
    assert "IsNullOrWhiteSpace" in script
    assert "Release channel tag already exists" in script
    assert "git/matching-refs/tags/$($env:RELEASE_REF)" in script
    assert "Release channel tag already exists without a release" in script
    assert "Unable to verify whether the release channel tag exists" in script
    assert '$tagRef.ref -ceq "refs/tags/$($env:RELEASE_REF)"' in script
    assert "--clobber" not in script
    assert "windows-signature" not in script
    for asset in (
        "Catalyst-Setup-$($env:RELEASE_REF).exe",
        "latest.json.sig",
        "update-manifest-$($env:RELEASE_REF).json",
    ):
        assert asset in script
    assert "--draft `" in script
    assert "gh release upload" in script
    assert "--draft=false" in script
    assert "--prerelease=false" in script
    assert "--latest=true" in script
    assert script.index("gh release view") < script.index("gh release create")
    assert script.index("git/matching-refs") < script.index("gh release create")
    assert script.index("gh release create") < script.index("gh release upload")
    assert script.index("gh release upload") < script.index("--draft=false")


def test_unsigned_stable_manifest_binds_exact_source_commit(tmp_path):
    installer = tmp_path / "Catalyst-Setup-v1.5.0.exe"
    installer.write_bytes(b"unsigned stable installer fixture")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    sidecar = tmp_path / f"{installer.name}.sha256"
    sidecar.write_text(f"{digest}  {installer.name}\n", encoding="utf-8")
    args = Namespace(
        version="v1.5.0",
        channel="stable",
        installer=installer,
        sha256_file=sidecar,
        download_base_url="https://github.com/Lowestofttim/catalyst-releases/releases/download/v1.5.0",
        release_url="https://github.com/Lowestofttim/catalyst-releases/releases/tag/v1.5.0",
        release_notes_file=None,
        expires_days=90,
        source_commit="a" * 40,
    )

    manifest = build_manifest(args)

    assert manifest["channel"] == "stable"
    assert manifest["source_commit"] == "a" * 40
    assert manifest["platforms"]["windows-x64"]["installer"]["sha256"] == digest

    args.source_commit = "b" * 39
    with pytest.raises(ValueError, match="source commit"):
        build_manifest(args)


def test_signing_policy_explains_unsigned_stable_path():
    policy = POLICY.read_text(encoding="utf-8")
    assert "Unsigned stable" in policy
    assert "SmartScreen" in policy
    assert "Smart App Control" in policy
    assert "no verified publisher" in policy
