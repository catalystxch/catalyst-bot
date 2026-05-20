from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_sync_release_metadata():
    path = ROOT / "website" / "scripts" / "sync_release_metadata.py"
    spec = importlib.util.spec_from_file_location("sync_release_metadata", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def test_macos_package_supports_ad_hoc_signing_without_timestamp_args():
    macos_script = (ROOT / "scripts" / "package_macos.sh").read_text(encoding="utf-8")

    assert "if [[ ${#timestamp_args[@]} -gt 0 ]]; then" in macos_script
    assert (
        "MACOS_CERTIFICATE_B64 not configured; using ad-hoc signature." in macos_script
    )
    assert "else\n  codesign \\" in macos_script


def test_pyinstaller_bundle_includes_env_template_for_app_bundles():
    spec_text = (ROOT / "catalyst.spec").read_text(encoding="utf-8")

    assert ".env.example" in spec_text
    assert "_env_example_files" in spec_text


def test_website_linux_primary_download_prefers_deb_over_appimage():
    sync = _load_sync_release_metadata()
    digest = "sha256:" + ("a" * 64)
    metadata = {
        "latest": {
            "assets": [
                {
                    "name": "Catalyst-Setup-v1.2.37.exe",
                    "platform": "windows",
                    "kind": "installer",
                    "size_bytes": 1,
                    "download_url": "https://github.com/Lowestofttim/catalyst-releases/releases/download/v1.2.37/Catalyst-Setup-v1.2.37.exe",
                    "sha256": "a" * 64,
                }
            ]
        }
    }
    release = {
        "assets": [
            {
                "name": "Catalyst-macos-v1.2.37.dmg",
                "size": 2,
                "url": "https://github.com/catalystxch/catalyst-bot/releases/download/v1.2.37/Catalyst-macos-v1.2.37.dmg",
                "digest": digest,
            },
            {
                "name": "Catalyst-linux-v1.2.37-x86_64.AppImage",
                "size": 3,
                "url": "https://github.com/catalystxch/catalyst-bot/releases/download/v1.2.37/Catalyst-linux-v1.2.37-x86_64.AppImage",
                "digest": digest,
            },
            {
                "name": "catalyst_v1.2.37_amd64.deb",
                "size": 4,
                "url": "https://github.com/catalystxch/catalyst-bot/releases/download/v1.2.37/catalyst_v1.2.37_amd64.deb",
                "digest": digest,
            },
        ]
    }

    sync.append_platform_downloads(metadata, release, include_download_urls=True)

    linux_assets = [
        asset
        for asset in metadata["latest"]["assets"]
        if asset["platform"] == "linux" and asset["kind"] == "installer"
    ]
    assert linux_assets[0]["name"].endswith(".deb")
