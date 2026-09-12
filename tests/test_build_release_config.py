from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_walletconnect_dependencies_are_exactly_pinned_and_locally_bundled():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["dependencies"]["@walletconnect/sign-client"] == "2.23.4"
    assert package["dependencies"]["@walletconnect/utils"] == "2.23.4"
    assert package["dependencies"]["qrcode"] == "1.5.4"
    assert package["devDependencies"]["esbuild"] == "0.25.9"
    assert package["scripts"]["build:walletconnect"] == (
        "node scripts/build_walletconnect_signing.mjs"
    )


def test_walletconnect_source_requests_only_nonfinancial_message_signing():
    source = (ROOT / "web" / "walletconnect_signing.ts").read_text(encoding="utf-8")

    assert 'const ALLOWED_METHOD = "chia_signMessageByAddress"' in source
    assert "chia_createOffer" not in source
    assert "chia_cancelOffer" not in source
    assert "chip0002_signCoinSpends" not in source
    assert "chia_send" not in source


def test_pyinstaller_includes_walletconnect_bundle_and_python_verifier():
    spec = (ROOT / "catalyst.spec").read_text(encoding="utf-8")

    assert "walletconnect-signing.js" in spec
    assert "Reown-WalletConnect-Community-License.txt" in spec
    assert "bootstrap_manifest" in spec
    assert "walletconnect_signing" in spec


def test_gui_loads_only_the_local_walletconnect_bundle():
    gui = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert 'src="/assets/walletconnect-signing.js"' in gui
    assert "unpkg.com/@walletconnect" not in gui
    assert "cdn.jsdelivr.net/npm/@walletconnect" not in gui


def test_walletconnect_redistribution_notice_is_included():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "Portions © 2025 Reown, Inc. All Rights Reserved" in " ".join(
        notices.split()
    )
    assert (ROOT / "licenses" / "Reown-WalletConnect-Community-License.txt").is_file()
