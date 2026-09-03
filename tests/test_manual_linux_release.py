from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-linux-release.yml"


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def steps() -> list[dict]:
    return load_workflow()["jobs"]["publish-linux-release"]["steps"]


def named_step(name: str) -> dict:
    matches = [step for step in steps() if step.get("name") == name]
    assert len(matches) == 1, f"expected one workflow step named {name!r}"
    return matches[0]


def step_index(name: str) -> int:
    return next(index for index, step in enumerate(steps()) if step.get("name") == name)


def test_linux_release_is_manual_and_validates_a_public_main_tag():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "tag:" in workflow
    validation_step = named_step("Validate release tag")
    validation = validation_step["run"]
    assert "refs/tags/${RELEASE_REF}" in validation
    assert "merge-base --is-ancestor" in validation
    assert "isDraft" in validation
    assert validation_step["env"]["SOURCE_REPOSITORY"] == "catalystxch/catalyst-bot"


def test_yaml_parser_is_a_direct_developer_dependency():
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").lower()
    assert "pyyaml>=" in requirements


def test_linux_build_uses_the_validated_tag_and_existing_release_scripts():
    ordered = [
        "Validate release tag",
        "Checkout validated release tag",
        "Build with PyInstaller",
        "Package Linux releases",
        "Smoke test Linux releases",
        "Upload Linux release assets",
    ]
    positions = [step_index(name) for name in ordered]
    assert positions == sorted(positions)

    checkout = named_step("Checkout validated release tag")["run"]
    assert "git checkout --detach" in checkout
    assert "refs/tags/${RELEASE_REF}" in checkout

    package = named_step("Package Linux releases")["run"]
    assert "scripts/package_linux.sh" in package
    assert "Catalyst-linux-${RELEASE_REF}.tar.gz" in package


def test_linux_packages_are_smoked_and_checksums_are_verified_before_upload():
    smoke = named_step("Smoke test Linux releases")["run"]
    assert smoke.count("packaged_api_smoke.py") == 2
    assert smoke.count("linux_desktop_smoke.sh") == 2
    assert "AppImage" in smoke
    assert "dpkg-deb -x" in smoke

    upload = named_step("Upload Linux release assets")["run"]
    for fragment in (
        "Catalyst-linux-${RELEASE_REF}.tar.gz",
        "Catalyst-linux-${RELEASE_REF}-x86_64.AppImage",
        "Catalyst-linux-${RELEASE_REF}-x86_64.AppImage.sha256",
        "catalyst_${RELEASE_REF}_amd64.deb",
        "catalyst_${RELEASE_REF}_amd64.deb.sha256",
    ):
        assert fragment in upload
    assert "sha256sum --check" in upload
    assert "--clobber" not in upload
    assert "already exists" in upload
