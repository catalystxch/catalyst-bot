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
    def test_rpc_recursively_redacts_secret_name_variants_without_over_redacting_safe_fields(self):
        class FakeResponse:
            status = 500

            def read(self):
                return (
                    b"MEMPOOL_CONFLICT private_key_material=RESPONSE_PRIVATE_MATERIAL "
                    b"secrets=RESPONSE_SECRETS secret_value=RESPONSE_SECRET_VALUE "
                    b"seed_phrase=RESPONSE_SEED_PHRASE mnemonic=RESPONSE_MNEMONIC "
                    b"apiToken=RESPONSE_API_TOKEN accessToken=RESPONSE_ACCESS_TOKEN "
                    b"auth=RESPONSE_AUTH header=RESPONSE_HEADER cookie=RESPONSE_COOKIE"
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
        payload = {
            "outer": [
                {"privateKey": "PAYLOAD_PRIVATE_KEY"},
                {"secrets": "PAYLOAD_SECRETS", "secret_value": "PAYLOAD_SECRET_VALUE"},
            ],
            "credentials": {
                "seed_phrase": "PAYLOAD_SEED_PHRASE",
                "mnemonic": "PAYLOAD_MNEMONIC",
                "apiToken": "PAYLOAD_API_TOKEN",
                "accessToken": "PAYLOAD_ACCESS_TOKEN",
                "auth": "PAYLOAD_AUTH",
                "header": "PAYLOAD_HEADER",
                "cookie": "PAYLOAD_COOKIE",
            },
            "headers": {"X-Api-Token": "PAYLOAD_HEADER_TOKEN"},
            "monkey_count": "SAFE_MONKEY_COUNT",
            "keyframe": "SAFE_KEYFRAME",
            "token_count": "SAFE_TOKEN_COUNT",
            "public_key": "SAFE_PUBLIC_KEY",
        }

        with (
            patch.dict(sys.modules, {"database": fake_database}),
            patch.object(
                wallet_sage, "_get_sage_connection", return_value=FakeConnection()
            ),
            patch.object(wallet_sage, "_console", side_effect=console_messages.append),
        ):
            result = wallet_sage.rpc("submit_transaction", payload)

        observed = repr((result, console_messages, events))
        for secret in (
            "RESPONSE_PRIVATE_MATERIAL",
            "RESPONSE_SECRETS",
            "RESPONSE_SECRET_VALUE",
            "RESPONSE_SEED_PHRASE",
            "RESPONSE_MNEMONIC",
            "RESPONSE_API_TOKEN",
            "RESPONSE_ACCESS_TOKEN",
            "RESPONSE_AUTH",
            "RESPONSE_HEADER",
            "RESPONSE_COOKIE",
            "PAYLOAD_PRIVATE_KEY",
            "PAYLOAD_SECRETS",
            "PAYLOAD_SECRET_VALUE",
            "PAYLOAD_SEED_PHRASE",
            "PAYLOAD_MNEMONIC",
            "PAYLOAD_API_TOKEN",
            "PAYLOAD_ACCESS_TOKEN",
            "PAYLOAD_AUTH",
            "PAYLOAD_HEADER",
            "PAYLOAD_COOKIE",
            "PAYLOAD_HEADER_TOKEN",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, observed)
        for safe_value in (
            "SAFE_MONKEY_COUNT",
            "SAFE_KEYFRAME",
            "SAFE_TOKEN_COUNT",
            "SAFE_PUBLIC_KEY",
        ):
            with self.subTest(safe_value=safe_value):
                self.assertIn(safe_value, observed)

    def test_sanitizers_recursively_bound_variant_secret_data(self):
        secret = "LONG_SECRET_VALUE_" + "x" * 200
        safe_text = "SAFE_TEXT_" + "y" * 200

        text = wallet_sage._sanitize_sage_text(
            f"private_key_material={secret}", limit=64
        )
        data = wallet_sage._sanitize_sage_data(
            {"nested": [{"secret_value": secret, "safe_text": safe_text}]},
            limit=32,
        )

        self.assertLessEqual(len(text), 64)
        self.assertNotIn(secret, text)
        self.assertEqual(data["nested"][0]["secret_value"], "[REDACTED]")
        self.assertLessEqual(len(data["nested"][0]["safe_text"]), 32)
        self.assertTrue(data["nested"][0]["safe_text"].startswith("SAFE_TEXT_"))

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
