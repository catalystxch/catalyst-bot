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
class TestWalletSageLogin(unittest.TestCase):
    def setUp(self):
        """Reset init state so each test starts clean."""
        wallet_sage._init_ok = False
        wallet_sage._init_last_attempt = 0.0
        self._reachable_patch = patch.object(
            wallet_sage, "_sage_rpc_port_reachable", return_value=True
        )
        self._reachable_patch.start()
        self.addCleanup(self._reachable_patch.stop)

    def test_login_follows_version_initialize_login_sequence(self):
        """sage_login should call get_version -> initialize -> login -> get_current_key."""
        calls = []

        def fake_rpc(method, payload, timeout=0):
            calls.append(method)
            if method == "get_version":
                return {"version": "0.12.10"}
            if method == "initialize":
                return {"success": True}
            if method == "login":
                return {"success": True}
            return None

        with patch.object(wallet_sage, "rpc", side_effect=fake_rpc):
            with patch.object(
                wallet_sage,
                "get_current_key",
                return_value={
                    "fingerprint": 1234567890,
                    "name": "Test",
                    "has_secrets": True,
                },
            ):
                with patch.object(wallet_sage.time, "sleep", return_value=None):
                    ok = wallet_sage.sage_login(1234567890)

        self.assertTrue(ok)
        self.assertEqual(calls, ["get_version", "initialize", "login"])

    def test_login_with_force_resync_calls_resync(self):
        """sage_login with force_resync=True should call resync between initialize and login."""
        calls = []

        def fake_rpc(method, payload, timeout=0):
            calls.append(method)
            if method == "get_version":
                return {"version": "0.12.10"}
            if method == "initialize":
                return {"success": True}
            if method == "resync":
                return {"success": True}
            if method == "login":
                return {"success": True}
            return None

        with patch.object(wallet_sage, "rpc", side_effect=fake_rpc):
            with patch.object(
                wallet_sage,
                "get_current_key",
                return_value={
                    "fingerprint": 1234567890,
                    "name": "Test",
                    "has_secrets": True,
                },
            ):
                with patch.object(wallet_sage.time, "sleep", return_value=None):
                    ok = wallet_sage.sage_login(1234567890, force_resync=True)

        self.assertTrue(ok)
        self.assertEqual(calls, ["get_version", "initialize", "resync", "login"])

    def test_login_returns_false_when_initialize_fails(self):
        """If initialize returns a structured error, sage_login should return False."""
        calls = []

        def fake_rpc(method, payload, timeout=0):
            calls.append(method)
            if method == "get_version":
                return {"version": "0.12.10"}
            if method == "initialize":
                return {"success": False, "error": "Sage HTTP 500: internal error"}
            return None

        with patch.object(wallet_sage, "rpc", side_effect=fake_rpc):
            with patch.object(wallet_sage.time, "sleep", return_value=None):
                ok = wallet_sage.sage_login(1234567890)

        self.assertFalse(ok)
        self.assertIn("initialize", calls)

    def test_optional_initialize_404_is_logged_as_compatibility_info(self):
        """Sage versions without /initialize must not raise an operator warning."""
        diagnostic = wallet_sage._build_sage_diagnostic(
            endpoint="initialize",
            payload={},
            error_code="SAGE_HTTP_ERROR",
            elapsed=0.01,
            http_status=404,
            response_summary={"type": "text", "size": 0},
        )

        with (
            patch.object(wallet_sage, "_console") as console,
            patch("database.log_event") as log_event,
        ):
            wallet_sage._emit_sage_diagnostic(diagnostic, "initialize")

        console.assert_called_once()
        args, kwargs = log_event.call_args
        self.assertEqual(args[0], "info")
        self.assertEqual(args[1], "sage_initialize_not_required")
        self.assertNotIn("warning", args)
        self.assertEqual(kwargs["data"]["http_status"], 404)

    def test_non_optional_sage_http_errors_remain_warnings(self):
        """Only the exact optional /initialize 404 may be downgraded."""
        cases = (
            ("get_version", 404),
            ("initialize", 500),
        )

        for endpoint, http_status in cases:
            with self.subTest(endpoint=endpoint, http_status=http_status):
                diagnostic = wallet_sage._build_sage_diagnostic(
                    endpoint=endpoint,
                    payload={},
                    error_code="SAGE_HTTP_ERROR",
                    elapsed=0.01,
                    http_status=http_status,
                    response_summary={"type": "text", "size": 0},
                )

                with (
                    patch.object(wallet_sage, "_console"),
                    patch("database.log_event") as log_event,
                ):
                    wallet_sage._emit_sage_diagnostic(diagnostic, endpoint)

                args, kwargs = log_event.call_args
                self.assertEqual(args[0], "warning")
                self.assertEqual(args[1], "sage_sage_http_error")
                self.assertEqual(kwargs["data"]["http_status"], http_status)

    def test_login_returns_false_when_sage_unreachable(self):
        """If get_version returns None, sage_login should return False immediately."""
        calls = []

        def fake_rpc(method, payload, timeout=0):
            calls.append(method)
            return None  # Sage not responding

        with patch.object(wallet_sage, "rpc", side_effect=fake_rpc):
            with patch.object(wallet_sage.time, "sleep", return_value=None):
                ok = wallet_sage.sage_login(1234567890)

        self.assertFalse(ok)
        self.assertEqual(calls, ["get_version"])

    def test_login_returns_false_when_version_returns_error_dict(self):
        """If get_version returns a structured error dict, sage_login should return False."""
        calls = []

        def fake_rpc(method, payload, timeout=0):
            calls.append(method)
            if method == "get_version":
                return {"success": False, "error": "Connection refused"}
            return None

        with patch.object(wallet_sage, "rpc", side_effect=fake_rpc):
            with patch.object(wallet_sage.time, "sleep", return_value=None):
                ok = wallet_sage.sage_login(1234567890)

        self.assertFalse(ok)
        self.assertEqual(calls, ["get_version"])

    def test_login_returns_false_on_fingerprint_mismatch(self):
        """sage_login returns False when active key fingerprint differs."""

        def fake_rpc(method, payload, timeout=0):
            if method == "get_version":
                return {"version": "0.12.10"}
            if method == "initialize":
                return {"success": True}
            if method == "login":
                return {"success": True}
            return None

        with patch.object(wallet_sage, "rpc", side_effect=fake_rpc):
            with patch.object(
                wallet_sage,
                "get_current_key",
                return_value={
                    "fingerprint": 999999,
                    "name": "Wrong",
                    "has_secrets": True,
                },
            ):
                with patch.object(wallet_sage.time, "sleep", return_value=None):
                    ok = wallet_sage.sage_login(1234567890)

        # Returns False -- fingerprint mismatch is a hard error.
        self.assertFalse(ok)

    def test_login_returns_false_when_login_rpc_returns_error(self):
        """If login RPC returns structured error, sage_login should return False."""
        calls = []

        def fake_rpc(method, payload, timeout=0):
            calls.append(method)
            if method == "get_version":
                return {"version": "0.12.10"}
            if method == "initialize":
                return {"success": True}
            if method == "login":
                return {"success": False, "error": "fingerprint not found"}
            return None

        with patch.object(wallet_sage, "rpc", side_effect=fake_rpc):
            with patch.object(wallet_sage.time, "sleep", return_value=None):
                ok = wallet_sage.sage_login(1234567890)

        self.assertFalse(ok)
        self.assertIn("login", calls)


if __name__ == "__main__":
    unittest.main()
