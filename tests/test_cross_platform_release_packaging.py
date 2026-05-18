from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_builds_native_macos_and_linux_downloads():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )

    assert "scripts/package_macos.sh" in workflow
    assert 'scripts/package_macos.sh "$RELEASE_REF"' in workflow
    assert "Catalyst-macos-${{ github.ref_name }}.dmg" in workflow
    assert "notarytool" in workflow
    assert "scripts/package_linux.sh" in workflow
    assert 'scripts/package_linux.sh "$RELEASE_REF"' in workflow
    assert "Catalyst-linux-${{ github.ref_name }}-x86_64.AppImage" in workflow
    assert "catalyst_${{ github.ref_name }}_amd64.deb" in workflow
    assert "packaged_api_smoke.py --exe" in workflow


def test_release_workflow_keeps_github_context_out_of_shell_scripts():
    workflow = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(
        encoding="utf-8"
    )

    assert "RELEASE_REF: ${{ github.ref_name }}" in workflow
    assert 'dmg_path="Catalyst-macos-${RELEASE_REF}.dmg"' in workflow
    assert 'appimage_path="Catalyst-linux-${RELEASE_REF}-x86_64.AppImage"' in workflow
    assert 'deb_path="catalyst_${RELEASE_REF}_amd64.deb"' in workflow


def test_packaging_scripts_create_normal_desktop_downloads():
    macos_script = (ROOT / "scripts" / "package_macos.sh").read_text(encoding="utf-8")
    linux_script = (ROOT / "scripts" / "package_linux.sh").read_text(encoding="utf-8")

    assert 'ditto "$app_path" "$dmg_stage/CATalyst.app"' in macos_script
    assert "ln -s /Applications" in macos_script
    assert "xcrun notarytool submit" in macos_script

    assert "appimagetool-x86_64.AppImage" in linux_script
    assert "dpkg-deb --build" in linux_script
    assert "$appdir/.DirIcon" in linux_script
    assert '$(basename "$appimage_path")' in linux_script
    assert '$(basename "$deb_path")' in linux_script


def test_pyinstaller_bundle_includes_env_template_for_app_bundles():
    spec_text = (ROOT / "catalyst.spec").read_text(encoding="utf-8")

    assert ".env.example" in spec_text
    assert "_env_example_files" in spec_text
