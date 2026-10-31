import re
from pathlib import Path


def test_pyinstaller_spec_bundles_gui_asset_references():
    root = Path(__file__).resolve().parents[1]
    gui = (root / "bot_gui.html").read_text(encoding="utf-8")
    spec = (root / "catalyst.spec").read_text(encoding="utf-8")

    referenced_assets = set(re.findall(r'["\']/assets/([^"\']+)["\']', gui))
    assert referenced_assets, "bot_gui.html should reference bundled assets"

    missing = sorted(
        asset
        for asset in referenced_assets
        if (root / "assets" / asset).is_file() and asset not in spec
    )
    assert missing == []


def test_pyinstaller_spec_bundles_restricted_recovery_page():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "catalyst.spec").read_text(encoding="utf-8")
    recovery_page = root / "refresh_abort_recovery.html"

    assert recovery_page.is_file()
    assert "(os.path.join(_HERE, 'refresh_abort_recovery.html'), '.')" in spec
