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
    def test_free_form_sanitizer_redacts_header_value_assignment_bypasses(self):
        bypasses = (
            ("cookie_header=COOKIE_HEADER_SECRET", "COOKIE_HEADER_SECRET"),
            (
                "proxy_authorization=PROXY_AUTHORIZATION_SECRET",
                "PROXY_AUTHORIZATION_SECRET",
            ),
            (
                "authorization_value=AUTHORIZATION_VALUE_SECRET",
                "AUTHORIZATION_VALUE_SECRET",
            ),
            ("auth_header=AUTH_HEADER_SECRET", "AUTH_HEADER_SECRET"),
        )

        for source, secret in bypasses:
            with self.subTest(source=source):
                sanitized = wallet_sage._sanitize_sage_text(source)
                self.assertNotIn(secret, sanitized)
                self.assertIn("[REDACTED]", sanitized)

    def test_free_form_sanitizer_finds_bypasses_after_benign_prefixes(self):
        sensitive_names = (
            "cookie_header",
            "proxy_authorization",
            "authorization_value",
            "auth_header",
        )

        for name in sensitive_names:
            for source in (
                f"error: {name}=PREFIXED_FREE_TEXT_SECRET",
                f"detail: {name}: PREFIXED_DETAIL_SECRET",
                f"endpoint?warning: {name}=PREFIXED_ENDPOINT_SECRET",
            ):
                with self.subTest(name=name, source=source):
                    sanitized = wallet_sage._sanitize_sage_text(source)
                    self.assertNotIn("SECRET", sanitized)
                    self.assertIn("[REDACTED]", sanitized)

    def test_free_form_sanitizer_redacts_multi_word_credentials_to_next_field(self):
        assignments = (
            ("token_value", "TOKEN_TAIL_A1", "header_count=SAFE_HEADER_COUNT"),
            (
                "secretValue",
                "SECRET_TAIL_B2",
                "certificate_status=SAFE_CERTIFICATE_STATUS",
            ),
            ("key-value", "KEY_TAIL_C3", "signature_status=SAFE_SIGNATURE_STATUS"),
            ("seed value", "SEED_TAIL_D4", "auth_method=SAFE_AUTH_METHOD"),
            ("cert_value", "CERT_TAIL_E5", "seed_count=SAFE_SEED_COUNT"),
            (
                "signatureValue",
                "SIGNATURE_TAIL_F6",
                "token_presence=SAFE_TOKEN_PRESENCE",
            ),
        )

        for name, secret_tail, safe_assignment in assignments:
            for separator in ("=", ":"):
                with self.subTest(name=name, separator=separator):
                    source = (
                        f"{name}{separator}first-word {secret_tail} "
                        f"{safe_assignment}"
                    )
                    sanitized = wallet_sage._sanitize_sage_text(source)
                    self.assertNotIn("first-word", sanitized)
                    self.assertNotIn(secret_tail, sanitized)
                    self.assertIn(safe_assignment, sanitized)

    def test_free_form_sanitizer_redacts_semantic_credentials_across_name_styles(self):
        credential_name_variants = (
            (
                "cookie_header",
                "cookieHeader",
                "cookie-header",
                "cookie header",
            ),
            (
                "proxy_authorization",
                "proxyAuthorization",
                "proxy-authorization",
                "proxy authorization",
            ),
            (
                "authorization_value",
                "authorizationValue",
                "authorization-value",
                "authorization value",
            ),
            ("auth_header", "authHeader", "auth-header", "auth header"),
            ("token_value", "tokenValue", "token-value", "token value"),
            ("secret_value", "secretValue", "secret-value", "secret value"),
            ("key_value", "keyValue", "key-value", "key value"),
            ("seed_value", "seedValue", "seed-value", "seed value"),
            ("cert_value", "certValue", "cert-value", "cert value"),
            (
                "signature_value",
                "signatureValue",
                "signature-value",
                "signature value",
            ),
        )

        for names in credential_name_variants:
            for name in names:
                for separator in ("=", ":"):
                    with self.subTest(name=name, separator=separator):
                        source = f"{name}{separator}CREDENTIAL_VALUE"
                        sanitized = wallet_sage._sanitize_sage_text(source)
                        self.assertNotIn("CREDENTIAL_VALUE", sanitized)
                        self.assertIn("[REDACTED]", sanitized)

    def test_free_form_sanitizer_preserves_metadata_across_name_styles(self):
        metadata_name_variants = (
            ("header_count", "headerCount", "header-count", "header count"),
            (
                "certificate_status",
                "certificateStatus",
                "certificate-status",
                "certificate status",
            ),
            (
                "signature_status",
                "signatureStatus",
                "signature-status",
                "signature status",
            ),
            ("auth_method", "authMethod", "auth-method", "auth method"),
            ("seed_count", "seedCount", "seed-count", "seed count"),
            (
                "token_presence",
                "tokenPresence",
                "token-presence",
                "token presence",
            ),
            (
                "private_key_status",
                "privateKeyStatus",
                "private-key-status",
                "private key status",
            ),
        )

        for names in metadata_name_variants:
            for name in names:
                for separator in ("=", ":"):
                    with self.subTest(name=name, separator=separator):
                        source = f"{name}{separator}SAFE_METADATA_VALUE"
                        self.assertEqual(
                            wallet_sage._sanitize_sage_text(source), source
                        )

    def test_sanitizers_redact_nested_credentials_and_http_headers(self):
        headers = (
            "Authorization: Bearer HTTP_AUTH_VALUE_A1\n"
            "Proxy-Authorization: Basic HTTP_PROXY_VALUE_B2\n"
            "Cookie: session=HTTP_COOKIE_VALUE_C3\n"
            "Set-Cookie: session=HTTP_SET_COOKIE_VALUE_D4"
        )
        nested = {
            "outer": [
                {
                    "cookieHeader": "NESTED_COOKIE_HEADER_SECRET",
                    "proxy-authorization": "NESTED_PROXY_AUTHORIZATION_SECRET",
                    "authorization value": "NESTED_AUTHORIZATION_VALUE_SECRET",
                    "auth_header": "NESTED_AUTH_HEADER_SECRET",
                },
                {
                    "tokenValue": "NESTED_TOKEN_VALUE_SECRET",
                    "secret-value": "NESTED_SECRET_VALUE_SECRET",
                    "key value": "NESTED_KEY_VALUE_SECRET",
                    "seed_value": "NESTED_SEED_VALUE_SECRET",
                    "certValue": "NESTED_CERT_VALUE_SECRET",
                    "signature-value": "NESTED_SIGNATURE_VALUE_SECRET",
                },
                {
                    "headerCount": "SAFE_HEADER_COUNT",
                    "certificate-status": "SAFE_CERTIFICATE_STATUS",
                    "signature status": "SAFE_SIGNATURE_STATUS",
                    "auth_method": "SAFE_AUTH_METHOD",
                    "seedCount": "SAFE_SEED_COUNT",
                },
            ],
            "http_headers": {
                "Authorization": "NESTED_AUTHORIZATION_HEADER_SECRET",
                "Cookie": "NESTED_COOKIE_HEADER_MAP_SECRET",
            },
        }

        sanitized_headers = wallet_sage._sanitize_sage_text(headers)
        sanitized_nested = wallet_sage._sanitize_sage_data(nested)
        observed = repr((sanitized_headers, sanitized_nested))
        for secret in (
            "HTTP_AUTH_VALUE_A1",
            "HTTP_PROXY_VALUE_B2",
            "HTTP_COOKIE_VALUE_C3",
            "HTTP_SET_COOKIE_VALUE_D4",
            "NESTED_COOKIE_HEADER_SECRET",
            "NESTED_PROXY_AUTHORIZATION_SECRET",
            "NESTED_AUTHORIZATION_VALUE_SECRET",
            "NESTED_AUTH_HEADER_SECRET",
            "NESTED_TOKEN_VALUE_SECRET",
            "NESTED_SECRET_VALUE_SECRET",
            "NESTED_KEY_VALUE_SECRET",
            "NESTED_SEED_VALUE_SECRET",
            "NESTED_CERT_VALUE_SECRET",
            "NESTED_SIGNATURE_VALUE_SECRET",
            "NESTED_AUTHORIZATION_HEADER_SECRET",
            "NESTED_COOKIE_HEADER_MAP_SECRET",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, observed)
        for safe_value in (
            "SAFE_HEADER_COUNT",
            "SAFE_CERTIFICATE_STATUS",
            "SAFE_SIGNATURE_STATUS",
            "SAFE_AUTH_METHOD",
            "SAFE_SEED_COUNT",
        ):
            with self.subTest(safe_value=safe_value):
                self.assertIn(safe_value, observed)

    def test_rpc_redacts_header_value_bypasses_at_every_diagnostic_boundary(self):
        class FakeResponse:
            status = 500

            def read(self):
                return (
                    b"MEMPOOL_CONFLICT error: "
                    b"cookie_header=RESPONSE_COOKIE_HEADER_SECRET; detail: "
                    b"proxy_authorization=RESPONSE_PROXY_AUTHORIZATION_SECRET; warning: "
                    b"authorization_value=RESPONSE_AUTHORIZATION_VALUE_SECRET; context: "
                    b"auth_header=RESPONSE_AUTH_HEADER_SECRET; "
                    b"header_count=SAFE_RESPONSE_HEADER_COUNT"
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
            "nested": {
                "cookieHeader": "PAYLOAD_COOKIE_HEADER_SECRET",
                "proxy-authorization": "PAYLOAD_PROXY_AUTHORIZATION_SECRET",
                "authorization value": "PAYLOAD_AUTHORIZATION_VALUE_SECRET",
                "auth_header": "PAYLOAD_AUTH_HEADER_SECRET",
                "header_count": "SAFE_PAYLOAD_HEADER_COUNT",
            }
        }
        endpoint = "submit_transaction?auth_header=ENDPOINT_AUTH_HEADER_SECRET"

        with (
            patch.dict(sys.modules, {"database": fake_database}),
            patch.object(
                wallet_sage, "_get_sage_connection", return_value=FakeConnection()
            ),
            patch.object(wallet_sage, "_console", side_effect=console_messages.append),
        ):
            result = wallet_sage.rpc(endpoint, payload)

        self.assertFalse(result["success"])
        self.assertTrue(events)
        observed = repr((result, console_messages, events))
        for secret in (
            "RESPONSE_COOKIE_HEADER_SECRET",
            "RESPONSE_PROXY_AUTHORIZATION_SECRET",
            "RESPONSE_AUTHORIZATION_VALUE_SECRET",
            "RESPONSE_AUTH_HEADER_SECRET",
            "PAYLOAD_COOKIE_HEADER_SECRET",
            "PAYLOAD_PROXY_AUTHORIZATION_SECRET",
            "PAYLOAD_AUTHORIZATION_VALUE_SECRET",
            "PAYLOAD_AUTH_HEADER_SECRET",
            "ENDPOINT_AUTH_HEADER_SECRET",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, observed)
        self.assertIn("SAFE_RESPONSE_HEADER_COUNT", observed)
        self.assertIn("SAFE_PAYLOAD_HEADER_COUNT", observed)

    def test_sensitive_name_matrix_distinguishes_credentials_from_metadata(self):
        sensitive_names = (
            "authorization_header",
            "client_certificate",
            "wallet_signature",
            "auth_token",
            "auth_secret",
            "seed_phrase",
            "seed_material",
            "private_key_material",
            "secrets",
            "cookie",
        )
        harmless_metadata_names = (
            "header_count",
            "certificate_status",
            "signature_status",
            "auth_method",
            "seed_count",
            "token_presence",
            "private_key_status",
        )

        for name in sensitive_names:
            with self.subTest(name=name):
                self.assertTrue(wallet_sage._is_sensitive_name(name))
        for name in harmless_metadata_names:
            with self.subTest(name=name):
                self.assertFalse(wallet_sage._is_sensitive_name(name))

    def test_rpc_preserves_metadata_but_redacts_semantic_credential_names(self):
        class FakeResponse:
            status = 500

            def read(self):
                return (
                    b"MEMPOOL_CONFLICT header_count=SAFE_HEADER_COUNT "
                    b"certificate_status=SAFE_CERTIFICATE_STATUS "
                    b"signature_status=SAFE_SIGNATURE_STATUS "
                    b"auth_method=SAFE_AUTH_METHOD seed_count=SAFE_SEED_COUNT "
                    b"authorization_header=RESPONSE_AUTH_HEADER "
                    b"client_certificate=RESPONSE_CLIENT_CERTIFICATE "
                    b"wallet_signature=RESPONSE_WALLET_SIGNATURE "
                    b"auth_token=RESPONSE_AUTH_TOKEN auth_secret=RESPONSE_AUTH_SECRET "
                    b"seed_phrase=RESPONSE_SEED_PHRASE seed_material=RESPONSE_SEED_MATERIAL"
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
            "header_count": "PAYLOAD_HEADER_COUNT",
            "certificate_status": "PAYLOAD_CERTIFICATE_STATUS",
            "signature_status": "PAYLOAD_SIGNATURE_STATUS",
            "auth_method": "PAYLOAD_AUTH_METHOD",
            "seed_count": "PAYLOAD_SEED_COUNT",
            "authorization_header": "PAYLOAD_AUTH_HEADER",
            "client_certificate": "PAYLOAD_CLIENT_CERTIFICATE",
            "wallet_signature": "PAYLOAD_WALLET_SIGNATURE",
            "auth_token": "PAYLOAD_AUTH_TOKEN",
            "auth_secret": "PAYLOAD_AUTH_SECRET",
            "seed_phrase": "PAYLOAD_SEED_PHRASE",
            "seed_material": "PAYLOAD_SEED_MATERIAL",
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
        for safe_value in (
            "SAFE_HEADER_COUNT",
            "SAFE_CERTIFICATE_STATUS",
            "SAFE_SIGNATURE_STATUS",
            "SAFE_AUTH_METHOD",
            "SAFE_SEED_COUNT",
            "PAYLOAD_HEADER_COUNT",
            "PAYLOAD_CERTIFICATE_STATUS",
            "PAYLOAD_SIGNATURE_STATUS",
            "PAYLOAD_AUTH_METHOD",
            "PAYLOAD_SEED_COUNT",
        ):
            with self.subTest(safe_value=safe_value):
                self.assertIn(safe_value, observed)
        for secret in (
            "RESPONSE_AUTH_HEADER",
            "RESPONSE_CLIENT_CERTIFICATE",
            "RESPONSE_WALLET_SIGNATURE",
            "RESPONSE_AUTH_TOKEN",
            "RESPONSE_AUTH_SECRET",
            "RESPONSE_SEED_PHRASE",
            "RESPONSE_SEED_MATERIAL",
            "PAYLOAD_AUTH_HEADER",
            "PAYLOAD_CLIENT_CERTIFICATE",
            "PAYLOAD_WALLET_SIGNATURE",
            "PAYLOAD_AUTH_TOKEN",
            "PAYLOAD_AUTH_SECRET",
            "PAYLOAD_SEED_PHRASE",
            "PAYLOAD_SEED_MATERIAL",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, observed)

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
