import os
import tempfile
import unittest
import ast
from pathlib import Path
from unittest.mock import patch

try:
    import wallet_sage

    _IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    wallet_sage = None
    _IMPORT_ERROR = exc


@unittest.skipIf(
    wallet_sage is None, f"wallet_sage import unavailable: {_IMPORT_ERROR}"
)
class TestWalletSageStartupReadiness(unittest.TestCase):
    def test_wallet_sage_routes_console_output_through_safe_wrapper(self):
        source_path = Path(wallet_sage.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        unsafe_lines = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                continue
            parent = parents.get(node)
            while parent is not None and not isinstance(
                parent, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                parent = parents.get(parent)
            if parent is None or parent.name != "_console":
                unsafe_lines.append(node.lineno)

        self.assertEqual(unsafe_lines, [])

    def test_authoritative_offer_history_marks_sage_unfiltered_snapshot_complete(self):
        rows = [
            {"trade_id": "a" * 64, "offer": "offer1" + "secret" * 1000},
            {"trade_id": "b" * 64},
        ]

        with patch.object(wallet_sage, "get_all_offers", return_value=rows) as reader:
            result = wallet_sage.get_authoritative_offer_history(
                include_completed=True,
                start=50,
                end=100,
            )

        self.assertEqual(
            result,
            {
                "success": True,
                "offers": [{"trade_id": "a" * 64}, {"trade_id": "b" * 64}],
                "total": 2,
                "end_of_history": True,
            },
        )
        reader.assert_called_once_with(
            include_completed=True,
            start=50,
            end=100,
        )

    def test_get_all_offers_rejects_missing_or_malformed_offer_collection(self):
        for response in ({"success": True}, {"success": True, "offers": {}}, [1, 2]):
            with (
                self.subTest(response=response),
                patch.object(wallet_sage, "rpc", return_value=response),
            ):
                self.assertIsNone(wallet_sage.get_all_offers(include_completed=True))

    def test_get_all_offers_keeps_unknown_statuses_when_filtering_open_book(self):
        rows = [
            {"trade_id": "a" * 64, "status": 99},
            {"trade_id": "b" * 64, "status": "SAGE_FUTURE_ACTIVE"},
            {"trade_id": "c" * 64, "status": 4},
            {"trade_id": "d" * 64, "status": "CANCELLED"},
        ]
        with patch.object(
            wallet_sage, "rpc", return_value={"success": True, "offers": rows}
        ):
            result = wallet_sage.get_all_offers(include_completed=False)

        self.assertEqual(
            [row["trade_id"] for row in result],
            ["a" * 64, "b" * 64],
        )

    def test_reload_connection_settings_uses_canonical_cfg_values(self):
        old_cert = wallet_sage.CERT_PATH
        old_key = wallet_sage.KEY_PATH
        old_url = wallet_sage.WALLET_URL
        try:
            with (
                patch.object(
                    wallet_sage.cfg,
                    "SAGE_RPC_URL",
                    "https://127.0.0.1:9257",
                ),
                patch.object(
                    wallet_sage.cfg,
                    "SAGE_CERT_PATH",
                    "C:/configured/ssl/wallet.crt",
                ),
                patch.object(
                    wallet_sage.cfg,
                    "SAGE_KEY_PATH",
                    "C:/configured/ssl/wallet.key",
                ),
                patch.object(wallet_sage.cfg, "sage_connection_settings"),
                patch.dict(
                    os.environ,
                    {
                        "SAGE_RPC_URL": "https://127.0.0.1:9999",
                        "SAGE_CERT_PATH": "C:/process/ssl/wallet.crt",
                        "SAGE_KEY_PATH": "C:/process/ssl/wallet.key",
                        "_CATALYST_PRESERVE_PROCESS_ENV": "",
                    },
                    clear=False,
                ),
            ):
                wallet_sage.cfg.sage_connection_settings.return_value = (
                    "https://127.0.0.1:9257",
                    "C:/configured/ssl/wallet.crt",
                    "C:/configured/ssl/wallet.key",
                    "",
                )
                wallet_sage.reload_connection_settings()
                self.assertEqual(wallet_sage.CERT_PATH, "C:/configured/ssl/wallet.crt")
                self.assertEqual(wallet_sage.KEY_PATH, "C:/configured/ssl/wallet.key")
                self.assertEqual(wallet_sage.WALLET_URL, "https://127.0.0.1:9257")
        finally:
            wallet_sage.CERT_PATH = old_cert
            wallet_sage.KEY_PATH = old_key
            wallet_sage.WALLET_URL = old_url
            wallet_sage._conn_local.conn = None

    def test_reload_connection_settings_preserves_process_env_over_env_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_cert = os.path.join(temp_dir, "file.crt")
            file_key = os.path.join(temp_dir, "file.key")
            env_cert = os.path.join(temp_dir, "env.crt")
            env_key = os.path.join(temp_dir, "env.key")
            old_cert = wallet_sage.CERT_PATH
            old_key = wallet_sage.KEY_PATH
            old_url = wallet_sage.WALLET_URL
            old_host = wallet_sage._SAGE_HOST
            old_port = wallet_sage._SAGE_PORT
            try:
                with (
                    patch.object(
                        wallet_sage.cfg,
                        "sage_connection_settings",
                        return_value=(
                            "https://127.0.0.1:9999",
                            file_cert,
                            file_key,
                            "",
                        ),
                    ),
                    patch.dict(
                        os.environ,
                        {
                            "_CATALYST_PRESERVE_PROCESS_ENV": "1",
                            "SAGE_RPC_URL": "https://127.0.0.1:9257",
                            "SAGE_CERT_PATH": env_cert,
                            "SAGE_KEY_PATH": env_key,
                        },
                        clear=False,
                    ),
                ):
                    wallet_sage.reload_connection_settings()
                    self.assertEqual(wallet_sage.WALLET_URL, "https://127.0.0.1:9257")
                    self.assertEqual(wallet_sage.CERT_PATH, env_cert)
                    self.assertEqual(wallet_sage.KEY_PATH, env_key)
            finally:
                wallet_sage.CERT_PATH = old_cert
                wallet_sage.KEY_PATH = old_key
                wallet_sage.WALLET_URL = old_url
                wallet_sage._SAGE_HOST = old_host
                wallet_sage._SAGE_PORT = old_port
                wallet_sage._conn_local.conn = None

    def test_reload_connection_settings_honours_validated_process_cert_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cert_path = os.path.join(temp_dir, "wallet.crt")
            key_path = os.path.join(temp_dir, "wallet.key")
            open(cert_path, "w", encoding="utf-8").close()
            open(key_path, "w", encoding="utf-8").close()
            old_cert = wallet_sage.CERT_PATH
            old_key = wallet_sage.KEY_PATH
            old_url = wallet_sage.WALLET_URL
            try:
                with (
                    patch.object(
                        wallet_sage.cfg,
                        "sage_connection_settings",
                        return_value=(
                            "https://127.0.0.1:9999",
                            "C:/stale/wallet.crt",
                            "C:/stale/wallet.key",
                            "",
                        ),
                    ),
                    patch.dict(
                        os.environ,
                        {
                            "_CATALYST_PRESERVE_PROCESS_ENV": "1",
                            "SAGE_RPC_URL": "https://127.0.0.1:9257",
                            "SAGE_CERT_PATH": cert_path,
                            "SAGE_KEY_PATH": key_path,
                        },
                        clear=False,
                    ),
                ):
                    wallet_sage.reload_connection_settings()
                    self.assertEqual(wallet_sage.CERT_PATH, cert_path)
                    self.assertEqual(wallet_sage.KEY_PATH, key_path)
            finally:
                wallet_sage.CERT_PATH = old_cert
                wallet_sage.KEY_PATH = old_key
                wallet_sage.WALLET_URL = old_url
                wallet_sage._conn_local.conn = None

    def test_reload_connection_settings_does_not_mix_partial_process_cert_pair(self):
        old_cert = wallet_sage.CERT_PATH
        old_key = wallet_sage.KEY_PATH
        old_url = wallet_sage.WALLET_URL
        try:
            with (
                patch.object(
                    wallet_sage.cfg,
                    "sage_connection_settings",
                    return_value=(
                        "https://127.0.0.1:9257",
                        "C:/configured/ssl/wallet.crt",
                        "C:/configured/ssl/wallet.key",
                        "",
                    ),
                ),
                patch.dict(
                    os.environ,
                    {
                        "_CATALYST_PRESERVE_PROCESS_ENV": "1",
                        "SAGE_CERT_PATH": "C:/process/ssl/wallet.crt",
                        "SAGE_KEY_PATH": "",
                    },
                    clear=False,
                ),
            ):
                wallet_sage.reload_connection_settings()
                self.assertEqual(wallet_sage.CERT_PATH, "C:/configured/ssl/wallet.crt")
                self.assertEqual(wallet_sage.KEY_PATH, "C:/configured/ssl/wallet.key")
        finally:
            wallet_sage.CERT_PATH = old_cert
            wallet_sage.KEY_PATH = old_key
            wallet_sage.WALLET_URL = old_url
            wallet_sage._conn_local.conn = None

    def test_get_chia_health_reports_syncing_when_wallet_not_synced(self):
        # Mock get_peer_connections to avoid real network calls that may fail
        # when the Sage wallet is under load from earlier tests in the suite.
        with (
            patch.object(
                wallet_sage,
                "get_wallet_sync_status",
                return_value={
                    "reachable": True,
                    "synced": False,
                    "syncing": True,
                    "sync_state": "not_synced",
                },
            ),
            patch.object(
                wallet_sage,
                "get_peer_connections",
                return_value=[
                    {"peer_host": "127.0.0.1"},
                ],
            ),
        ):
            health = wallet_sage.get_chia_health()

        self.assertEqual(health["status"], "wallet_not_synced")
        self.assertFalse(health["healthy"])

    def test_get_chia_health_reports_unknown_when_sync_state_unknown(self):
        with (
            patch.object(
                wallet_sage,
                "get_wallet_sync_status",
                return_value={
                    "reachable": True,
                    "synced": False,
                    "syncing": False,
                    "sync_state": "unknown",
                },
            ),
            patch.object(
                wallet_sage,
                "get_peer_connections",
                return_value=[
                    {"peer_host": "127.0.0.1"},
                ],
            ),
        ):
            health = wallet_sage.get_chia_health()

        self.assertEqual(health["status"], "wallet_sync_unknown")
        self.assertFalse(health["healthy"])

    def test_get_wallets_does_not_crash_when_no_configured_cat(self):
        # Reset init state in case previous tests set it
        wallet_sage._init_ok = True
        wallet_sage._init_last_attempt = 0.0

        sample_cats = {
            "cats": [
                {"asset_id": "a" * 64, "name": "Alpha", "ticker": "ALPHA"},
                {"asset_id": "b" * 64, "name": "Beta", "ticker": "BETA"},
            ]
        }
        if hasattr(wallet_sage.get_wallets, "_discovery_logged"):
            delattr(wallet_sage.get_wallets, "_discovery_logged")

        with patch.object(wallet_sage, "_get_cat_asset_id", return_value=None):
            with patch.object(wallet_sage, "rpc", return_value=sample_cats):
                result = wallet_sage.get_wallets()

        self.assertTrue(result["success"])
        self.assertGreaterEqual(len(result["wallets"]), 3)  # XCH + discovered CATs

    def test_get_wallets_does_not_crash_on_emoji_ticker_in_cp1252_console(self):
        wallet_sage._init_ok = True
        wallet_sage._init_last_attempt = 0.0
        sample_cats = {
            "cats": [
                {
                    "asset_id": "a" * 64,
                    "name": "S.E.C.",
                    "ticker": "🪙",
                }
            ]
        }

        def cp1252_console(message, **kwargs):
            str(message).encode("cp1252")

        if hasattr(wallet_sage.get_wallets, "_discovery_logged"):
            delattr(wallet_sage.get_wallets, "_discovery_logged")

        with (
            patch.object(wallet_sage, "_get_cat_asset_id", return_value=None),
            patch.object(wallet_sage, "rpc", return_value=sample_cats),
            patch("builtins.print", side_effect=cp1252_console),
        ):
            result = wallet_sage.get_wallets()

        self.assertTrue(result["success"])
        self.assertEqual(result["wallets"][1]["name"], "S.E.C. (🪙)")

    def test_resolve_asset_id_mismatch_warning_is_cp1252_safe(self):
        def cp1252_console(message, **kwargs):
            str(message).encode("cp1252")

        warning_flag = "_mismatch_warned_1005"
        if hasattr(wallet_sage._resolve_asset_id, warning_flag):
            delattr(wallet_sage._resolve_asset_id, warning_flag)

        with (
            patch.object(wallet_sage, "_wallet_id_to_asset_id", {1005: "a" * 64}),
            patch.object(wallet_sage, "_get_cat_asset_id", return_value="b" * 64),
            patch("builtins.print", side_effect=cp1252_console),
        ):
            result = wallet_sage._resolve_asset_id(1005)

        self.assertEqual(result, "a" * 64)

    def test_get_all_offers_diagnostics_are_cp1252_safe(self):
        def cp1252_console(message, **kwargs):
            str(message).encode("cp1252")

        for flag in (
            "_format_logged",
            "_offers_logged",
            "_norm_logged",
            "_filter_logged",
        ):
            if hasattr(wallet_sage.get_all_offers, flag):
                delattr(wallet_sage.get_all_offers, flag)

        response = {
            "offers": [
                {
                    "offer_id": "offer-id",
                    "status": "cancelled",
                    "summary": {
                        "maker": [
                            {
                                "asset": {"asset_id": None, "ticker": "XCH"},
                                "amount": 1,
                            }
                        ],
                        "taker": [
                            {
                                "asset": {"asset_id": "a" * 64, "ticker": "🪙"},
                                "amount": 1,
                            }
                        ],
                    },
                }
            ]
        }

        with (
            patch.object(wallet_sage, "rpc", return_value=response),
            patch("builtins.print", side_effect=cp1252_console),
        ):
            result = wallet_sage.get_all_offers(include_completed=False)

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
