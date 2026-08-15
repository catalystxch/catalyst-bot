import json
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
    def test_full_sensitive_assignment_name_beats_safe_metadata_suffix(self):
        cases = (
            "token header_count=OVERLAP_TOKEN_SECRET",
            "authorization auth_method=OVERLAP_AUTH_SECRET",
        )

        for source in cases:
            with self.subTest(source=source):
                sanitized = wallet_sage._sanitize_sage_text(source)
                self.assertNotIn("OVERLAP", sanitized)
                self.assertIn("[REDACTED]", sanitized)

    def test_exact_safe_metadata_suffix_near_misses_fail_closed(self):
        cases = (
            "foo header_count=NEAR_MISS_SNAKE_HEADER",
            "foo headerCount=NEAR_MISS_CAMEL_HEADER",
            "foo header count=NEAR_MISS_SPACE_HEADER",
            "foo auth_method=NEAR_MISS_SNAKE_AUTH",
            "foo authMethod=NEAR_MISS_CAMEL_AUTH",
            "foo auth method=NEAR_MISS_SPACE_AUTH",
        )

        for source in cases:
            with self.subTest(source=source):
                sanitized = wallet_sage._sanitize_sage_text(source)
                self.assertNotIn("NEAR_MISS", sanitized)
                self.assertIn("[REDACTED]", sanitized)

    def test_exact_safe_metadata_terminates_only_an_active_credential(self):
        cases = (
            (
                "token=ACTIVE_TOKEN_SECRET header_count=SAFE_HEADER_COUNT",
                "token=[REDACTED] header_count=SAFE_HEADER_COUNT",
            ),
            (
                "secretValue=ACTIVE_SECRET authMethod=SAFE_AUTH_METHOD",
                "secretValue=[REDACTED] authMethod=SAFE_AUTH_METHOD",
            ),
            (
                "Authorization: Bearer ACTIVE_AUTH_SECRET; "
                "auth method=SAFE_SPACE_AUTH_METHOD",
                "Authorization: [REDACTED]; "
                "auth method=SAFE_SPACE_AUTH_METHOD",
            ),
        )

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(wallet_sage._sanitize_sage_text(source), expected)

    def test_overlong_free_text_field_name_fails_closed(self):
        source = "x" * 70 + "Token=OVERLONG_TEXT_SECRET_SENTINEL"

        sanitized = wallet_sage._sanitize_sage_text(source)

        self.assertNotIn("OVERLONG_TEXT_SECRET_SENTINEL", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_mismatched_structure_close_redacts_the_remainder(self):
        source = "token=[FIRST_SECRET} ] AFTER_MISMATCH_SECRET"

        sanitized = wallet_sage._sanitize_sage_text(source)

        self.assertNotIn("FIRST_SECRET", sanitized)
        self.assertNotIn("AFTER_MISMATCH_SECRET", sanitized)
        self.assertEqual(sanitized, "token=[REDACTED]")

    def test_invalid_json_200_is_typed_before_raw_parser_exception_escapes(self):
        invalid_json = (
            b'{"success": false, "authorization": "INVALID_JSON_AUTH_SENTINEL"'
        )

        class FakeResponse:
            status = 200

            def read(self):
                return invalid_json

        class FakeConnection:
            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return FakeResponse()

        with patch.object(
            wallet_sage, "_get_sage_connection", return_value=FakeConnection()
        ):
            with self.assertRaises(wallet_sage._SageRPCFailure) as raised:
                wallet_sage._sage_post("submit_transaction", {})

        direct_failure = raised.exception
        self.assertEqual(direct_failure.error_code, "SAGE_RPC_ERROR")
        self.assertEqual(direct_failure.status, 200)
        self.assertNotIn("INVALID_JSON_AUTH_SENTINEL", repr(direct_failure.__dict__))
        self.assertEqual(direct_failure.response_summary["type"], "text")

        with (
            patch.object(
                wallet_sage,
                "_get_sage_connection",
                return_value=FakeConnection(),
            ),
            patch.object(wallet_sage, "_console"),
        ):
            result = wallet_sage.rpc("submit_transaction", {})

        self.assertEqual(result["error_code"], "SAGE_RPC_ERROR")
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["response_summary"], direct_failure.response_summary)
        self.assertEqual(result["response_summary"]["type"], "text")
        self.assertNotIn("INVALID_JSON_AUTH_SENTINEL", repr(result))

    def test_actual_sage_post_preserves_success_with_code_shaped_metadata(self):
        success = {
            "success": True,
            "code": "MEMPOOL_CONFLICT",
            "status": "ok",
            "value": "APPLICATION_RESULT_UNCHANGED",
        }
        encoded = json.dumps(success).encode()
        real_loads = json.loads

        class FakeResponse:
            status = 200

            def read(self):
                return encoded

        class FakeConnection:
            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return FakeResponse()

        def controlled_loads(value):
            if value == encoded.decode():
                return success
            return real_loads(value)

        with (
            patch.object(
                wallet_sage,
                "_get_sage_connection",
                return_value=FakeConnection(),
            ),
            patch.object(wallet_sage._json, "loads", side_effect=controlled_loads),
        ):
            result = wallet_sage.rpc("get_balance", {})

        self.assertIs(result, success)
        self.assertEqual(
            result,
            {
                "success": True,
                "code": "MEMPOOL_CONFLICT",
                "status": "ok",
                "value": "APPLICATION_RESULT_UNCHANGED",
            },
        )

    def test_container_scanner_has_bounded_forward_work_for_many_heads(self):
        class CountingText(str):
            def __new__(cls, value):
                instance = super().__new__(cls, value)
                instance.rfind_work = 0
                return instance

            def rfind(self, sub, start=0, end=None):
                stop = len(self) if end is None else end
                self.rfind_work += max(0, stop - start)
                return super().rfind(sub, start, stop)

        source = CountingText(
            "Authorization: Digest "
            + " ".join(
                f"token_{index}=HEAD_SECRET_{index}" for index in range(120)
            )
        )

        sanitized = wallet_sage._redact_sage_assignments(source)

        self.assertNotIn("HEAD_SECRET", sanitized)
        self.assertLessEqual(source.rfind_work, len(source) * 4)

    def test_assignment_scanner_work_scales_linearly_across_records(self):
        class CountingHeads(list):
            def __init__(self, values):
                super().__init__(values)
                self.accesses = 0

            def __getitem__(self, index):
                if isinstance(index, slice):
                    self.accesses += len(range(*index.indices(len(self))))
                else:
                    self.accesses += 1
                return super().__getitem__(index)

        def measured(record_count, container):
            if container:
                source = "\r\n".join(
                    f"Authorization: Digest realm=RECORD_REALM_{index}\r\n"
                    f" token=FOLDED_RECORD_SECRET_{index}"
                    for index in range(record_count)
                )
                sentinel = "RECORD_SECRET"
            else:
                source = "\n".join(
                    f"token_{index}=SCALAR_RECORD_SECRET_{index}"
                    for index in range(record_count)
                )
                sentinel = "SCALAR_RECORD_SECRET"
            heads = CountingHeads(wallet_sage._assignment_heads(source))
            with patch.object(wallet_sage, "_assignment_heads", return_value=heads):
                sanitized = wallet_sage._redact_sage_assignments(source)
            self.assertNotIn(sentinel, sanitized)
            return heads.accesses

        for container in (False, True):
            with self.subTest(container=container):
                work_40 = measured(40, container)
                work_80 = measured(80, container)
                work_160 = measured(160, container)
                self.assertLessEqual(work_80, work_40 * 2 + 32)
                self.assertLessEqual(work_160, work_80 * 2 + 32)
                self.assertLessEqual(work_160, 160 * 24)

    def test_fail_closed_authorization_and_cookie_state_machine_matrix(self):
        cases = (
            (
                "Authorization: Digest username=AUTH_USER, realm=AUTH_REALM, "
                'nonce="AUTH_NONCE", response="AUTH_RESPONSE=="\r\n'
                " header_count=FOLDED_NOT_A_BOUNDARY\r\n"
                "header_count=SAFE_HEADER_COUNT",
                ("AUTH_USER", "AUTH_REALM", "AUTH_NONCE", "AUTH_RESPONSE"),
                "header_count=SAFE_HEADER_COUNT",
            ),
            (
                "Proxy-Authorization: Digest username=PROXY_USER; nonce=PROXY_NONCE; "
                "response=PROXY_RESPONSE==\n"
                "auth_method=SAFE_AUTH_METHOD",
                ("PROXY_USER", "PROXY_NONCE", "PROXY_RESPONSE"),
                "auth_method=SAFE_AUTH_METHOD",
            ),
            (
                "Authorization: Bearer BEARER.SECRET/+==, tail=STILL_SECRET\r"
                "Authorization: Basic BASIC_SECRET==\r",
                ("BEARER.SECRET", "STILL_SECRET", "BASIC_SECRET"),
                None,
            ),
            (
                "Cookie: first=COOKIE_ONE; second=COOKIE_TWO; flag=COOKIE_FLAG\r\n"
                "Set-Cookie: session=SET_COOKIE; Expires=Wed, 21 Oct 2030 "
                "07:28:00 GMT; Path=/admin; HttpOnly\r\n",
                ("COOKIE_ONE", "COOKIE_TWO", "COOKIE_FLAG", "SET_COOKIE", "2030"),
                None,
            ),
        )

        for source, sentinels, compatibility_value in cases:
            with self.subTest(source=source):
                sanitized = wallet_sage._sanitize_sage_text(source)
                for sentinel in sentinels:
                    self.assertNotIn(sentinel, sanitized)
                if compatibility_value is not None:
                    self.assertIn(compatibility_value, sanitized)
                self.assertEqual(
                    wallet_sage._sanitize_sage_text(sanitized), sanitized
                )

    def test_fail_closed_scalar_metadata_and_negative_name_matrix(self):
        sensitive = (
            "token=one TOKEN TWO, generic=STILL_TOKEN; tail",
            "secret: one SECRET TWO; detail=STILL_SECRET!",
            "password='one PASSWORD TWO; generic=STILL_PASSWORD'",
            "private_key=[one, KEY_TWO, nested=STILL_KEY]",
            "seed_phrase={one: SEED_TWO, nested=STILL_SEED}",
            "signature=one SIGNATURE_TWO!!!",
            "certificate=one CERTIFICATE_TWO...",
            "puzzle_reveal=one PUZZLE_REVEAL_TWO",
            "APIToken=one ACRONYM_CAMEL_TWO",
            "HTTPAuthorizationHeader=one HTTP_HEADER_TWO",
        )
        for source in sensitive:
            with self.subTest(source=source):
                sanitized = wallet_sage._sanitize_sage_text(
                    "benign prefix: " + source
                )
                self.assertNotIn("TWO", sanitized)
                self.assertNotIn("STILL_", sanitized)
                self.assertIn("[REDACTED]", sanitized)

        exact_safe = (
            "header_count=SAFE_HEADER_COUNT",
            "certificateStatus=valid",
            "signature-status=verified",
            "auth method=SAFE_AUTH_METHOD",
            "seed_count=12",
            "tokenPresence=true",
            'private-key-status="available"',
        )
        for source in exact_safe:
            with self.subTest(source=source):
                self.assertEqual(wallet_sage._sanitize_sage_text(source), source)

        fail_closed_near_misses = (
            "header_count=unsafe metadata with spaces SECRET_NEAR_MISS",
            "certificate_count=CERTIFICATE_NEAR_MISS",
            "auth_status=AUTH_NEAR_MISS",
            "private_key_status=UNSAFE*STATUS",
            "HTTPHeaderCount=HTTP_HEADER_NEAR_MISS",
        )
        for source in fail_closed_near_misses:
            with self.subTest(source=source):
                sanitized = wallet_sage._sanitize_sage_text(source)
                self.assertNotIn("NEAR_MISS", sanitized)
                self.assertNotIn("UNSAFE*STATUS", sanitized)
                self.assertIn("[REDACTED]", sanitized)

        negatives = (
            "monkey_count=VISIBLE_MONKEY",
            "keyframe=VISIBLE_KEYFRAME",
            "token_count=VISIBLE_TOKEN_COUNT",
            "public_key=VISIBLE_PUBLIC_KEY",
        )
        for source in negatives:
            with self.subTest(source=source):
                self.assertEqual(wallet_sage._sanitize_sage_text(source), source)

    def test_fail_closed_json_pem_malformed_and_output_bounds(self):
        source = {
            "nested": {
                "authorization": "JSON_AUTH_SENTINEL",
                "safe": "escaped quote: \\\" and bracket ]",
                "metadata": {"headerCount": "SAFE_HEADER_COUNT"},
            },
            "items": [{"password": "JSON_PASSWORD_SENTINEL"}],
        }
        sanitized_json = wallet_sage._sanitize_sage_text(
            json.dumps(source, indent=2)
        )
        parsed = json.loads(sanitized_json)
        self.assertEqual(parsed["nested"]["authorization"], "[REDACTED]")
        self.assertEqual(parsed["items"][0]["password"], "[REDACTED]")
        self.assertEqual(
            parsed["nested"]["metadata"]["headerCount"], "SAFE_HEADER_COUNT"
        )

        malformed = (
            '{"authorization": "MALFORMED_JSON_SENTINEL",',
            'token="UNTERMINATED_QUOTE_SENTINEL',
            "private_key=[UNBALANCED_BRACKET_SENTINEL",
            "multiline_secret=FIRST_LINE_SENTINEL\nSECOND_LINE_VISIBLE",
        )
        for source_text in malformed:
            with self.subTest(source=source_text):
                sanitized = wallet_sage._sanitize_sage_text(source_text)
                self.assertNotIn("SENTINEL", sanitized)

        pem = (
            "before\n-----BEGIN PRIVATE KEY-----\nPRIVATE_PEM_SENTINEL\n"
            "-----END PRIVATE KEY-----\nafter\n"
            "-----BEGIN CERTIFICATE-----\nCERT_PEM_SENTINEL\n"
            "-----END CERTIFICATE-----\nlast\n"
            "-----BEGIN EC PRIVATE KEY-----\nUNFINISHED_PEM_SENTINEL"
        )
        sanitized_pem = wallet_sage._sanitize_sage_text(pem)
        self.assertNotIn("PEM_SENTINEL", sanitized_pem)
        self.assertEqual(sanitized_pem.count("[REDACTED]"), 3)
        self.assertIn("before", sanitized_pem)
        self.assertIn("after", sanitized_pem)

        huge = "safe-prefix\r\ntoken=" + "HUGE_SECRET_SENTINEL" * 2000
        bounded = wallet_sage._sanitize_sage_text(huge, limit=2048)
        self.assertLessEqual(len(bounded), 2048)
        self.assertNotIn("SENTINEL", bounded)
        self.assertFalse(bounded.endswith("\r"))
        self.assertNotRegex(bounded, r"\[(?:REDACTED|TRUNCATED)$")
        self.assertEqual(wallet_sage._sanitize_sage_text(bounded, 2048), bounded)

    def test_structured_sanitizer_enforces_all_bounds_and_cycles(self):
        over_items = [{"token": f"ITEM_SECRET_{index}"} for index in range(70)]
        over_depth = current = {}
        for _ in range(10):
            child = {}
            current["child"] = child
            current = child
        over_nodes = [list(range(4)) for _ in range(64)]
        cycle = {"safe": "CYCLE_SAFE"}
        cycle["self"] = cycle
        overlong_name = "x" * 70 + "Token"

        sanitized_items = wallet_sage._sanitize_sage_data(over_items)
        sanitized_depth = wallet_sage._sanitize_sage_data(over_depth)
        sanitized_nodes = wallet_sage._sanitize_sage_data(over_nodes)
        try:
            sanitized_cycle = wallet_sage._sanitize_sage_data(cycle)
        except RecursionError:
            sanitized_cycle = "RECURSION_LEAK"
        sanitized_long_name = wallet_sage._sanitize_sage_data(
            {overlong_name: "OVERLONG_NAME_SECRET_SENTINEL"}
        )

        self.assertLessEqual(len(sanitized_items), 65)
        self.assertIn("[TRUNCATED]", repr(sanitized_items))
        self.assertIn("[TRUNCATED]", repr(sanitized_depth))
        self.assertIn("[TRUNCATED]", repr(sanitized_nodes))
        self.assertEqual(sanitized_cycle["self"], "[CYCLE]")
        self.assertNotIn("OVERLONG_NAME_SECRET_SENTINEL", repr(sanitized_long_name))
        self.assertEqual(
            wallet_sage._sanitize_sage_data(sanitized_cycle), sanitized_cycle
        )

    def test_rpc_reuses_one_fixed_diagnostic_and_discards_remote_text(self):
        class FakeResponse:
            status = 500

            def read(self):
                return (
                    b"MEMPOOL_CONFLICT remote prose RESPONSE_SENTINEL "
                    b"Authorization: Digest username=REMOTE_USER, "
                    b'response="REMOTE_DIGEST"\r\n'
                    b" auth_method=FOLDED_METADATA_SENTINEL\r\n"
                    b"header_count=SAFE_HEADER_COUNT"
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
            "token": "PAYLOAD_SENTINEL",
            "ordinary": "ARBITRARY_PAYLOAD_STRING_SENTINEL",
            "header_count": "SAFE_HEADER_COUNT",
        }

        with (
            patch.dict(sys.modules, {"database": fake_database}),
            patch.object(
                wallet_sage, "_get_sage_connection", return_value=FakeConnection()
            ),
            patch.object(wallet_sage, "_console", side_effect=console_messages.append),
        ):
            result = wallet_sage.rpc(
                "submit/api_token=PATH_SENTINEL?api_token=ENDPOINT_SENTINEL"
                "#secret=FRAGMENT_SENTINEL",
                payload,
            )

        self.assertEqual(result["error"], "MEMPOOL_CONFLICT")
        self.assertEqual(result["error_code"], "MEMPOOL_CONFLICT")
        self.assertEqual(result["http_status"], 500)
        self.assertEqual(
            result["message"],
            "Sage rejected the transaction because an input is already spent or pending.",
        )
        self.assertIs(events[0][1]["data"], result)
        self.assertEqual(events[0][0][2], result["message"])
        observed = repr((result, console_messages, events))
        for sentinel in (
            "RESPONSE_SENTINEL",
            "REMOTE_USER",
            "REMOTE_DIGEST",
            "FOLDED_METADATA_SENTINEL",
            "PAYLOAD_SENTINEL",
            "ARBITRARY_PAYLOAD_STRING_SENTINEL",
            "PATH_SENTINEL",
            "ENDPOINT_SENTINEL",
            "FRAGMENT_SENTINEL",
        ):
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel, observed)
        self.assertIn("SAFE_HEADER_COUNT", observed)
        self.assertNotIn("response_snippet", result)

    def test_rpc_preserves_success_and_classifies_stable_codes_without_substrings(self):
        success = {"success": True, "value": "APPLICATION_RESULT_UNCHANGED"}
        with patch.object(wallet_sage, "_sage_post", return_value=success):
            self.assertIs(wallet_sage.rpc("get_balance", {}), success)

        cases = (
            ("NO_SPENDABLE_COINS", "NO_SPENDABLE_COINS"),
            ("UNKNOWN_UNSPENT", "UNKNOWN_UNSPENT"),
            ("REMOTE_SECRET_SENTINEL", "SAGE_HTTP_ERROR"),
            ("prefix MEMPOOL_CONFLICT is only remote prose", "SAGE_HTTP_ERROR"),
        )
        for remote_error, expected_code in cases:
            class FakeResponse:
                status = 409

                def read(self):
                    return json.dumps({"error": remote_error}).encode()

            class FakeConnection:
                def request(self, *args, **kwargs):
                    pass

                def getresponse(self):
                    return FakeResponse()

            with (
                self.subTest(remote_error=remote_error),
                patch.object(
                    wallet_sage,
                    "_get_sage_connection",
                    return_value=FakeConnection(),
                ),
                patch.object(wallet_sage, "_console"),
            ):
                result = wallet_sage.rpc("submit_transaction", {})
            self.assertEqual(result["error_code"], expected_code)
            self.assertNotIn("REMOTE_SECRET_SENTINEL", repr(result))

    def test_sage_post_discards_transport_exception_text_before_direct_callers(self):
        with patch.object(
            wallet_sage,
            "_get_sage_connection",
            side_effect=ConnectionError("TRANSPORT_EXCEPTION_SENTINEL"),
        ):
            with self.assertRaises(wallet_sage.SageConnectionError) as raised:
                wallet_sage._sage_post("get_balance", {})

        self.assertEqual(str(raised.exception), "SAGE_CONNECTION_ERROR")
        self.assertNotIn("TRANSPORT_EXCEPTION_SENTINEL", repr(raised.exception.__dict__))

    def test_rpc_diagnostic_emit_is_bounded_for_large_structured_inputs(self):
        payload = {
            f"ordinary_field_{index:02d}": "PAYLOAD_BOUND_SECRET_SENTINEL" * 20
            for index in range(64)
        }
        response_summary = wallet_sage._summarize_sage_payload(
            {
                f"remote_field_{index:02d}": "RESPONSE_BOUND_SECRET_SENTINEL" * 20
                for index in range(64)
            }
        )
        console_messages = []
        with (
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageMempoolConflict(
                    status=500, response_summary=response_summary
                ),
            ),
            patch.object(wallet_sage, "_console", side_effect=console_messages.append),
        ):
            result = wallet_sage.rpc("submit_transaction", payload)

        self.assertLessEqual(len(console_messages[0]), 2048)
        self.assertLessEqual(len(json.dumps(result)), 2048)
        self.assertNotIn("SECRET_SENTINEL", repr((result, console_messages)))
        self.assertIn("[TRUNCATED]", repr(result))

    def test_http_200_application_failure_discards_remote_error_text(self):
        class FakeResponse:
            status = 200

            def read(self):
                return json.dumps(
                    {
                        "success": False,
                        "error": "ambiguous REMOTE_APPLICATION_ERROR_SENTINEL",
                        "authorization": "REMOTE_APPLICATION_AUTH_SENTINEL",
                    }
                ).encode()

        class FakeConnection:
            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return FakeResponse()

        with (
            patch.object(
                wallet_sage, "_get_sage_connection", return_value=FakeConnection()
            ),
            patch.object(wallet_sage, "_console"),
        ):
            result = wallet_sage.rpc("submit_transaction", {})

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "SAGE_RPC_ERROR")
        self.assertEqual(result["http_status"], 200)
        self.assertNotIn("REMOTE_APPLICATION", repr(result))

    def test_colon_credentials_preserve_trailing_assignments_and_clean_marker(self):
        cases = (
            (
                "authorization: first-word SECRET_TAIL "
                "header_count=SAFE_HEADER_COUNT",
                "authorization: [REDACTED] header_count=SAFE_HEADER_COUNT",
            ),
            (
                "proxy_authorization: first-word SECRET_TAIL "
                "auth_method=SAFE_AUTH_METHOD",
                "proxy_authorization: [REDACTED] auth_method=SAFE_AUTH_METHOD",
            ),
        )

        for source, expected in cases:
            with self.subTest(source=source):
                sanitized = wallet_sage._sanitize_sage_text(source)
                self.assertEqual(sanitized, expected)
                self.assertEqual(sanitized.count("[REDACTED]"), 1)
                self.assertNotIn("[REDACTED]]", sanitized)

    def test_assignment_redactions_share_clean_structural_boundaries(self):
        cases = (
            (
                "Authorization: Bearer CRLF_AUTH_SECRET\r\n"
                "Proxy-Authorization: Basic CRLF_PROXY_SECRET\r\n"
                "header_count=SAFE_HEADER_COUNT",
                "Authorization: [REDACTED]\r\n"
                "Proxy-Authorization: [REDACTED]\r\n"
                "header_count=SAFE_HEADER_COUNT",
                2,
            ),
            (
                "authorization: first-word COMMA_SECRET, "
                "header_count=SAFE_HEADER_COUNT",
                "authorization: [REDACTED], header_count=SAFE_HEADER_COUNT",
                1,
            ),
            (
                "proxy_authorization: first-word SEMICOLON_SECRET; "
                "auth_method=SAFE_AUTH_METHOD",
                "proxy_authorization: [REDACTED]; auth_method=SAFE_AUTH_METHOD",
                1,
            ),
            (
                '{"authorization": "Bearer JSON_AUTH_SECRET", '
                '"header_count": "SAFE_HEADER_COUNT", '
                '"proxy_authorization": "Basic JSON_PROXY_SECRET", '
                '"auth_method": "SAFE_AUTH_METHOD"}',
                '{"authorization":"[REDACTED]",'
                '"header_count":"SAFE_HEADER_COUNT",'
                '"proxy_authorization":"[REDACTED]",'
                '"auth_method":"SAFE_AUTH_METHOD"}',
                2,
            ),
            (
                "Cookie: session=COOKIE_SECRET\r\n"
                "Set-Cookie: session=SET_COOKIE_SECRET; Path=/\r\n"
                "auth_method=SAFE_AUTH_METHOD",
                "Cookie: [REDACTED]\r\n"
                "Set-Cookie: [REDACTED]\r\n"
                "auth_method=SAFE_AUTH_METHOD",
                2,
            ),
            (
                "authorization: first AUTH_SECRET "
                "header_count=SAFE_HEADER_COUNT "
                "proxy_authorization: second PROXY_SECRET "
                "auth_method=SAFE_AUTH_METHOD",
                "authorization: [REDACTED] "
                "header_count=SAFE_HEADER_COUNT "
                "proxy_authorization: [REDACTED] "
                "auth_method=SAFE_AUTH_METHOD",
                2,
            ),
        )

        for source, expected, redaction_count in cases:
            with self.subTest(source=source):
                sanitized = wallet_sage._sanitize_sage_text(source)
                self.assertEqual(sanitized, expected)
                self.assertEqual(sanitized.count("[REDACTED]"), redaction_count)
                self.assertNotIn("[REDACTED]]", sanitized)

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
                    b"MEMPOOL_CONFLICT "
                    b"authorization_header=RESPONSE_AUTH_HEADER "
                    b"header_count=SAFE_HEADER_COUNT "
                    b"certificate_status=SAFE_CERTIFICATE_STATUS "
                    b"signature_status=SAFE_SIGNATURE_STATUS "
                    b"auth_method=SAFE_AUTH_METHOD seed_count=SAFE_SEED_COUNT "
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
        for safe_name in (
            "monkey_count",
            "keyframe",
            "token_count",
            "public_key",
        ):
            with self.subTest(safe_name=safe_name):
                self.assertIn(safe_name, observed)
        for arbitrary_value in (
            "SAFE_MONKEY_COUNT",
            "SAFE_KEYFRAME",
            "SAFE_TOKEN_COUNT",
            "SAFE_PUBLIC_KEY",
        ):
            with self.subTest(arbitrary_value=arbitrary_value):
                self.assertNotIn(arbitrary_value, observed)

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
        self.assertEqual(result["error_code"], "SAGE_CONNECTION_ERROR")
        self.assertEqual(
            result["message"], "The Sage RPC service could not be reached."
        )

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
