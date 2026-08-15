"""Regression coverage for deterministic, non-generating Sage TLS setup."""

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import wallet_chia
import wallet_sage


class TestSageCertificateResolution(unittest.TestCase):
    """A rejected generated client certificate must never become active."""

    def test_prefers_explicit_canonical_config_pair(self):
        resolved = wallet_sage.resolve_client_cert_paths(
            configured_cert="C:/configured/ssl/wallet.crt",
            configured_key="C:/configured/ssl/wallet.key",
            platform_ssl_dirs=["C:/platform/ssl"],
        )

        self.assertEqual(
            resolved,
            ("C:/configured/ssl/wallet.crt", "C:/configured/ssl/wallet.key"),
        )

    def test_uses_platform_wallet_pair_when_canonical_config_is_empty(self):
        resolved = wallet_sage.resolve_client_cert_paths(
            configured_cert="",
            configured_key="",
            platform_ssl_dirs=["C:/platform/ssl"],
        )

        self.assertEqual(
            resolved,
            (
                os.path.join("C:/platform/ssl", "wallet.crt"),
                os.path.join("C:/platform/ssl", "wallet.key"),
            ),
        )

    def test_never_generates_a_fallback_certificate_when_platform_pair_missing(self):
        resolved = wallet_sage.resolve_client_cert_paths(
            configured_cert="",
            configured_key="",
            platform_ssl_dirs=[],
        )

        self.assertEqual(resolved, ("", ""))

    def test_platform_data_dir_requires_the_sage_wallet_pair(self):
        with tempfile.TemporaryDirectory() as data_dir:
            ssl_dir = os.path.join(data_dir, "ssl")
            os.makedirs(ssl_dir)
            open(os.path.join(ssl_dir, "wallet.crt"), "w", encoding="utf-8").close()
            open(os.path.join(ssl_dir, "wallet.key"), "w", encoding="utf-8").close()

            resolved = wallet_sage.resolve_client_cert_paths(
                "", "", wallet_sage._platform_sage_ssl_dirs(data_dir)
            )

        self.assertEqual(
            resolved,
            (os.path.join(ssl_dir, "wallet.crt"), os.path.join(ssl_dir, "wallet.key")),
        )

    def test_platform_discovery_includes_windows_sage_data_directory(self):
        with tempfile.TemporaryDirectory() as localappdata:
            ssl_dir = os.path.join(localappdata, "Sage", "ssl")
            os.makedirs(ssl_dir)
            open(os.path.join(ssl_dir, "wallet.crt"), "w", encoding="utf-8").close()
            open(os.path.join(ssl_dir, "wallet.key"), "w", encoding="utf-8").close()

            with (
                patch("platform.system", return_value="Windows"),
                patch.dict(
                    os.environ,
                    {"APPDATA": "", "LOCALAPPDATA": localappdata},
                    clear=False,
                ),
            ):
                directories = wallet_sage._platform_sage_ssl_dirs("")

        self.assertIn(ssl_dir, directories)


class TestWalletIdentitySnapshot(unittest.TestCase):
    def test_sage_identity_is_a_fresh_complete_snapshot(self):
        with patch.object(
            wallet_sage,
            "_get_current_key_read_only",
            return_value={
                "name": "TEST 7",
                "fingerprint": "1234567890",
                "network_id": "mainnet",
                "kind": "private",
                "has_secrets": True,
            },
        ):
            identity = wallet_sage.get_wallet_identity()

        self.assertTrue(identity["success"])
        self.assertEqual(identity["backend"], "sage")
        self.assertEqual(identity["name"], "TEST 7")
        self.assertEqual(identity["fingerprint"], 1234567890)
        self.assertEqual(identity["network_id"], "mainnet")
        self.assertEqual(identity["kind"], "private")
        self.assertTrue(identity["has_secrets"])
        self.assertIsNotNone(
            datetime.fromisoformat(
                identity["observed_at_utc"].replace("Z", "+00:00")
            )
        )
        self.assertNotIn("error", identity)

    def test_sage_identity_does_not_initialize_the_wallet(self):
        with (
            patch.object(wallet_sage, "ensure_initialized") as initialize,
            patch.object(
                wallet_sage,
                "rpc",
                return_value={
                    "key": {
                        "name": "TEST 7",
                        "fingerprint": 1234567890,
                        "network_id": "mainnet",
                        "kind": "private",
                        "has_secrets": True,
                    }
                },
            ),
        ):
            identity = wallet_sage.get_wallet_identity()

        initialize.assert_not_called()
        self.assertTrue(identity["success"])

    def test_chia_identity_explicitly_marks_unsupported_fields_unknown(self):
        with patch.object(
            wallet_chia,
            "rpc",
            return_value={"success": True, "fingerprint": "99887766"},
        ):
            identity = wallet_chia.get_wallet_identity()

        self.assertTrue(identity["success"])
        self.assertEqual(identity["backend"], "chia")
        self.assertIsNone(identity["name"])
        self.assertEqual(identity["fingerprint"], 99887766)
        self.assertIsNone(identity["network_id"])
        self.assertIsNone(identity["kind"])
        self.assertIsNone(identity["has_secrets"])
        self.assertIsNotNone(
            datetime.fromisoformat(
                identity["observed_at_utc"].replace("Z", "+00:00")
            )
        )
        self.assertNotIn("error", identity)

    def test_chia_identity_returns_a_failure_snapshot_when_rpc_raises(self):
        with patch.object(wallet_chia, "rpc", side_effect=RuntimeError("offline")):
            identity = wallet_chia.get_wallet_identity()

        self.assertFalse(identity["success"])
        self.assertEqual(identity["backend"], "chia")
        self.assertEqual(identity["error"], "identity_lookup_failed")


if __name__ == "__main__":
    unittest.main()
