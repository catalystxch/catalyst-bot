import sys
import types
import unittest
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
class TestWalletSageSigningGuard(unittest.TestCase):
    def test_rpc_redacts_sensitive_error_response_and_payload_data(self):
        class FakeResponse:
            status = 500

            def read(self):
                return (
                    b"MEMPOOL_CONFLICT private_key=RESPONSE_PRIVATE_KEY "
                    b"api_token=RESPONSE_API_TOKEN"
                )

        class FakeConnection:
            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return FakeResponse()

        console_messages = []
        events = []
        fake_database = types.ModuleType("database")
        fake_database.log_event = lambda *args, **kwargs: events.append((args, kwargs))
        endpoint = "submit_transaction?api_token=ENDPOINT_API_TOKEN"
        payload = {
            "private_key": "PAYLOAD_PRIVATE_KEY",
            "api_token": "PAYLOAD_API_TOKEN",
            "puzzle_reveal": "PUZZLE_REVEAL_SECRET",
        }

        with (
            patch.dict(sys.modules, {"database": fake_database}),
            patch.object(
                wallet_sage, "_get_sage_connection", return_value=FakeConnection()
            ),
            patch.object(wallet_sage, "_console", side_effect=console_messages.append),
        ):
            result = wallet_sage.rpc(endpoint, payload)

        observed = repr((result, console_messages, events))
        for secret in (
            "RESPONSE_PRIVATE_KEY",
            "RESPONSE_API_TOKEN",
            "PAYLOAD_PRIVATE_KEY",
            "PAYLOAD_API_TOKEN",
            "PUZZLE_REVEAL_SECRET",
            "ENDPOINT_API_TOKEN",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, observed)
        self.assertIn("[REDACTED]", observed)

    def test_rpc_connection_error_redacts_returned_error_and_console(self):
        console_messages = []
        with (
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=ConnectionError("private_key=CONNECTION_PRIVATE_KEY"),
            ),
            patch.object(wallet_sage, "_console", side_effect=console_messages.append),
        ):
            result = wallet_sage.rpc("get_balance", {})

        observed = repr((result, console_messages))
        self.assertNotIn("CONNECTION_PRIVATE_KEY", observed)
        self.assertIn("[REDACTED]", observed)

    def test_rpc_exception_paths_do_not_raise_when_console_is_cp1252(self):
        def cp1252_console(message, **kwargs):
            str(message).encode("cp1252")

        exceptions = (
            wallet_sage.SageMempoolConflict("snowman: ☃"),
            wallet_sage.SageUnknownUnspent("snowman: ☃"),
            ConnectionError("snowman: ☃"),
            RuntimeError("snowman: ☃"),
        )
        for error in exceptions:
            with self.subTest(error=type(error).__name__), patch(
                "builtins.print", side_effect=cp1252_console
            ), patch.object(wallet_sage, "_sage_post", side_effect=error):
                result = wallet_sage.rpc("test", {})
            if isinstance(error, RuntimeError):
                self.assertIsNone(result)
            else:
                self.assertFalse(result["success"])

    def test_allows_wallet_with_secrets(self):
        with patch.object(
            wallet_sage, "get_current_key", return_value={"has_secrets": True}
        ):
            self.assertTrue(wallet_sage._require_signing_capability())

    def test_blocks_watch_only_wallet(self):
        with patch.object(
            wallet_sage, "get_current_key", return_value={"has_secrets": False}
        ):
            self.assertFalse(wallet_sage._require_signing_capability())

    def test_blocks_when_active_key_missing(self):
        with patch.object(wallet_sage, "get_current_key", return_value=None):
            self.assertFalse(wallet_sage._require_signing_capability())

    def test_blocks_when_lookup_errors(self):
        with patch.object(
            wallet_sage, "get_current_key", side_effect=RuntimeError("boom")
        ):
            self.assertFalse(wallet_sage._require_signing_capability())


if __name__ == "__main__":
    unittest.main()
