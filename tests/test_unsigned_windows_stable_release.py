"""Static release gates for the opt-in unsigned stable Windows workflow."""

from pathlib import Path

import yaml


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


def test_unsigned_stable_gates_precede_publication():
    _, steps = workflow_and_steps()
    names = [item.get("name") for item in steps]
    ordered = [
        "Validate release tag",
        "Build unsigned Windows installer from exact release tag",
        "Prove installer identity and unsigned status",
        "Install and smoke test the downloaded release",
        "Generate signed update metadata",
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
    publication = step(steps, "Publish unsigned stable update channel")
    assert publication["env"]["GH_TOKEN"] == (
        "${{ secrets.CATALYST_RELEASE_CHANNEL_TOKEN }}"
    )
    script = publication["run"]
    assert "IsNullOrWhiteSpace" in script
    assert "Release channel tag already exists" in script
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
    assert script.index("gh release create") < script.index("gh release upload")
    assert script.index("gh release upload") < script.index("--draft=false")


def test_signing_policy_explains_unsigned_stable_path():
    policy = POLICY.read_text(encoding="utf-8")
    assert "Unsigned stable" in policy
    assert "SmartScreen" in policy
    assert "Smart App Control" in policy
    assert "no verified publisher" in policy
