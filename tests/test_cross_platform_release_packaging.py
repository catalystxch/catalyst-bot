from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_builds_windows_and_linux_downloads_only():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )

    assert "windows-latest" in workflow
    assert "scripts/package_linux.sh" in workflow
    assert 'scripts/package_linux.sh "$RELEASE_REF"' in workflow
    assert "Catalyst-linux-${RELEASE_REF}-x86_64.AppImage" in workflow
    assert "catalyst_${RELEASE_REF}_amd64.deb" in workflow
    assert 'gh release upload "$RELEASE_REF" "${assets[@]}" --clobber' in workflow
    assert "packaged_api_smoke.py --exe" in workflow
    assert "macos-latest" not in workflow
    assert "Catalyst-macos" not in workflow
    assert "scripts/package_macos.sh" not in workflow


def test_release_workflow_uses_identity_aware_packaged_smoke_only():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )

    assert "Smoke test packaged API runtime" in workflow
    assert 'python scripts/packaged_api_smoke.py --exe "$exe"' in workflow
    assert "Smoke test (verify binary starts)" not in workflow
    assert "curl -sf http://127.0.0.1:5000/api/health" not in workflow


def test_release_workflow_does_not_publish_macos_assets():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )

    assert not (ROOT / "scripts" / "package_macos.sh").exists()
    assert "Upload macOS" not in workflow
    assert "Package macOS" not in workflow
    assert "MACOS_" not in workflow
    assert "APPLE_ID" not in workflow


def test_readme_describes_macos_as_source_only():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "macOS packages are not currently" in readme
    assert "Mac users can use the GitHub source code path below" in readme
    assert "### From Source on macOS or Linux" in readme
    assert "macOS release builds are currently not" in readme


def test_release_workflow_keeps_github_context_out_of_shell_scripts():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )

    assert "RELEASE_REF: ${{ github.ref_name }}" in workflow
    assert 'appimage_path="Catalyst-linux-${RELEASE_REF}-x86_64.AppImage"' in workflow
    assert 'deb_path="catalyst_${RELEASE_REF}_amd64.deb"' in workflow


def test_release_publish_job_uses_explicit_repository_context():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )

    assert (
        'gh release edit "$RELEASE_REF" --repo "$GITHUB_REPOSITORY" --draft=false --latest'
        in workflow
    )


def test_packaging_scripts_create_normal_desktop_downloads():
    linux_script = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")

    assert "appimagetool-x86_64.AppImage" in linux_script
    assert "dpkg-deb --build" in linux_script
    assert "$appdir/.DirIcon" in linux_script
    assert '$(basename "$appimage_path")' in linux_script
    assert '$(basename "$deb_path")' in linux_script


def test_pyinstaller_bundle_includes_env_template_for_app_bundles():
    spec_text = (ROOT / "catalyst.spec").read_text(encoding="utf-8")

    assert ".env.example" in spec_text
    assert "_env_example_files" in spec_text
