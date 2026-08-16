import itertools
import sys
import types
import unittest
from unittest.mock import patch

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")

    class _StubSession:
        """Minimal Session stub with headers so amm_monitor.__init__ doesn't crash."""

        def __init__(self):
            self.headers = {}

        def get(self, *args, **kwargs):
            class _R:
                status_code = 200

                def json(self):
                    return {}

                def raise_for_status(self):
                    pass

            return _R()

        def mount(self, *args, **kwargs):
            pass

    requests_stub.Session = _StubSession
    requests_stub.exceptions = types.SimpleNamespace(RequestException=Exception)
    requests_adapters_stub = types.ModuleType("requests.adapters")
    requests_adapters_stub.HTTPAdapter = object
    requests_stub.adapters = requests_adapters_stub
    sys.modules["requests"] = requests_stub
    sys.modules["requests.adapters"] = requests_adapters_stub

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.set_key = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

if "urllib3" not in sys.modules:
    urllib3_stub = types.ModuleType("urllib3")
    urllib3_stub.Retry = object
    urllib3_stub.disable_warnings = lambda *args, **kwargs: None
    urllib3_stub.exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
    sys.modules["urllib3"] = urllib3_stub

import wallet_sage
from cancel_outcomes import (
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    CANCEL_UNKNOWN,
    validate_cancel_result,
)


class WalletSageCancelBatchTests(unittest.TestCase):
    def test_cancel_batch_never_confirms_by_unlock_or_absence(self):
        ticks = itertools.count(start=0, step=1)

        with (
            patch.object(wallet_sage, "cancel_offer", return_value={"success": True}),
            patch.object(wallet_sage, "get_spendable_coin_count", return_value=100),
            patch.object(wallet_sage, "get_pending_transactions", return_value=[]),
            patch.object(wallet_sage, "get_all_offers", return_value=[]),
            patch.object(wallet_sage, "get_owned_coins_detailed", return_value={}),
            patch("builtins.print"),
            patch.object(wallet_sage.time, "sleep", return_value=None),
            patch.object(wallet_sage.time, "time", side_effect=lambda: next(ticks)),
        ):
            results = wallet_sage.cancel_offers_batch(["0xabc123"], secure=False)

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_UNKNOWN)
        self.assertFalse(results["0xabc123"]["success"])
        validate_cancel_result(results["0xabc123"])

    def test_cancel_batch_does_not_confirm_when_offer_disappears_but_tx_pending(self):
        ticks = itertools.count(start=0, step=31)

        with (
            patch.object(wallet_sage, "cancel_offer", return_value={"success": True}),
            patch.object(wallet_sage, "get_spendable_coin_count", return_value=100),
            patch.object(
                wallet_sage,
                "get_pending_transactions",
                return_value=[{"transaction_id": "pending"}],
            ),
            patch.object(wallet_sage, "get_all_offers", return_value=[]),
            patch.object(wallet_sage, "get_owned_coins_detailed", return_value={}),
            patch("builtins.print"),
            patch.object(wallet_sage.time, "sleep", return_value=None),
            patch.object(wallet_sage.time, "time", side_effect=lambda: next(ticks)),
        ):
            results = wallet_sage.cancel_offers_batch(["0xabc123"], secure=False)

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_UNKNOWN)
        validate_cancel_result(results["0xabc123"])

    def test_cancel_batch_does_not_confirm_when_offer_lock_still_visible(self):
        ticks = itertools.count(start=0, step=31)

        with (
            patch.object(wallet_sage, "cancel_offer", return_value={"success": True}),
            patch.object(wallet_sage, "get_spendable_coin_count", return_value=100),
            patch.object(wallet_sage, "get_pending_transactions", return_value=[]),
            patch.object(wallet_sage, "get_all_offers", return_value=[]),
            patch.object(
                wallet_sage,
                "get_owned_coins_detailed",
                return_value={"0xcoin": {"offer_id": "0xabc123"}},
            ),
            patch("builtins.print"),
            patch.object(wallet_sage.time, "sleep", return_value=None),
            patch.object(wallet_sage.time, "time", side_effect=lambda: next(ticks)),
        ):
            results = wallet_sage.cancel_offers_batch(["0xabc123"], secure=False)

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_UNKNOWN)
        validate_cancel_result(results["0xabc123"])

    def test_sequential_cancel_retries_without_fee_when_fee_coin_unavailable(self):
        no_fee_coin = {
            "success": False,
            "error": "Sage HTTP 500: Wallet error: Coin selection error: no spendable coins",
        }
        accepted_without_fee = {"success": True}

        with (
            patch.object(
                wallet_sage,
                "cancel_offer",
                side_effect=[no_fee_coin, accepted_without_fee],
            ) as cancel,
            patch.object(wallet_sage, "get_spendable_coin_count", return_value=100),
            patch("builtins.print"),
            patch.object(wallet_sage.time, "sleep", return_value=None),
        ):
            results = wallet_sage.cancel_offers_batch(
                ["0xabc123"],
                secure=True,
                fee_mojos=100,
                skip_confirmation=True,
            )

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_FAILED)
        self.assertEqual(cancel.call_args_list[0].kwargs["fee_mojos"], 100)
        self.assertEqual(cancel.call_count, 1)

    def test_cancel_offer_treats_mempool_conflict_as_pending_cancel(self):
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageMempoolConflict("MEMPOOL_CONFLICT"),
            ),
            patch("builtins.print"),
        ):
            result = wallet_sage.cancel_offer("0xabc123", secure=False)

        self.assertEqual(result["outcome"], CANCEL_UNKNOWN)
        self.assertFalse(result["success"])
        validate_cancel_result(result)

    def test_cancel_offer_uses_typed_http_404_for_already_gone(self):
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageHTTPError(status=404),
            ),
            patch("builtins.print"),
        ):
            result = wallet_sage.cancel_offer("0xabc123", secure=False)

        self.assertEqual(result["outcome"], CANCEL_UNKNOWN)
        self.assertFalse(result["success"])
        validate_cancel_result(result)

    def test_cancel_offer_preserves_stable_no_spendable_code(self):
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageOperationalError(
                    error_code="NO_SPENDABLE_COINS"
                ),
            ),
            patch("builtins.print"),
        ):
            result = wallet_sage.cancel_offer("0xabc123", secure=True, fee_mojos=100)

        self.assertEqual(result["outcome"], CANCEL_FAILED)
        self.assertFalse(result["success"])
        validate_cancel_result(result)

    def test_sequential_cancel_retries_stable_no_spendable_code_without_fee(self):
        stable_no_fee_coin = {
            "success": False,
            "error": "NO_SPENDABLE_COINS",
            "error_code": "NO_SPENDABLE_COINS",
            "message": "Sage reports that no spendable coins are available.",
        }

        with (
            patch.object(
                wallet_sage,
                "cancel_offer",
                side_effect=[stable_no_fee_coin, {"success": True}],
            ) as cancel,
            patch.object(wallet_sage, "get_spendable_coin_count", return_value=100),
            patch("builtins.print"),
            patch.object(wallet_sage.time, "sleep", return_value=None),
        ):
            results = wallet_sage.cancel_offers_batch(
                ["0xabc123"],
                secure=True,
                fee_mojos=100,
                skip_confirmation=True,
            )

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_FAILED)
        self.assertEqual(cancel.call_count, 1)
        self.assertEqual(cancel.call_args_list[0].kwargs["fee_mojos"], 100)

    def test_cancel_offer_success_without_identity_is_unknown(self):
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(wallet_sage, "_sage_post", return_value={"success": True}),
            patch("builtins.print"),
        ):
            result = wallet_sage.cancel_offer("0xabc123", secure=False)

        self.assertEqual(result["outcome"], CANCEL_UNKNOWN)
        validate_cancel_result(result)

    def test_cancel_offer_exact_transaction_identity_is_submitted(self):
        transaction_id = "1" * 64
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                return_value={"success": True, "transaction_id": transaction_id},
            ),
            patch("builtins.print"),
        ):
            result = wallet_sage.cancel_offer("0xabc123", secure=False)

        self.assertEqual(result["outcome"], CANCEL_SUBMITTED_UNCONFIRMED)
        self.assertEqual(result["transaction_id"], transaction_id)
        validate_cancel_result(result)

    def test_cancel_offer_local_signing_rejection_is_failed_without_effect(self):
        rechecks = []
        with (
            patch.object(
                wallet_sage, "_require_signing_capability", return_value=False
            ),
            patch.object(wallet_sage, "_sage_post") as post,
        ):
            result = wallet_sage.cancel_offer(
                "0xabc123",
                secure=False,
                _identity_recheck=lambda step: rechecks.append(step),
            )

        self.assertEqual(result["outcome"], CANCEL_FAILED)
        self.assertEqual(rechecks, [])
        post.assert_not_called()
        validate_cancel_result(result)

    def test_cancel_offer_disconnect_after_effect_boundary_is_unknown(self):
        rechecks = []
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageConnectionError(
                    error_code="SAGE_CONNECTION_ERROR"
                ),
            ),
            patch("builtins.print"),
        ):
            result = wallet_sage.cancel_offer(
                "0xabc123",
                secure=False,
                _identity_recheck=lambda step: rechecks.append(step),
            )

        self.assertEqual(result["outcome"], CANCEL_UNKNOWN)
        self.assertEqual(rechecks, ["cancel_offer"])
        validate_cancel_result(result)

    def test_cancel_offer_response_loss_never_resubmits_transport_request(self):
        sends = []

        class LostResponseConnection:
            def request(self, method, path, **kwargs):
                sends.append((method, path))

            def getresponse(self):
                raise ConnectionResetError("response lost after dispatch")

        class RetryWouldSubmitConnection:
            def request(self, method, path, **kwargs):
                sends.append((method, path))

            def getresponse(self):
                raise AssertionError("cancel transport must not retry")

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_get_sage_connection",
                return_value=LostResponseConnection(),
            ),
            patch.object(
                wallet_sage.http.client,
                "HTTPSConnection",
                return_value=RetryWouldSubmitConnection(),
            ),
            patch.object(wallet_sage, "CERT_PATH", None),
            patch.object(wallet_sage, "KEY_PATH", None),
        ):
            result = wallet_sage.cancel_offer("0xabc123", secure=False)

        self.assertEqual(sends, [("POST", "/cancel_offer")])
        self.assertEqual(result["outcome"], CANCEL_UNKNOWN)
        self.assertFalse(result["success"])
        validate_cancel_result(result)

    def test_already_including_transaction_is_info_for_cancel(self):
        self.assertEqual(
            wallet_sage._sage_tx_error_level(
                "ALREADY_INCLUDING_TRANSACTION", "cancel_offer"
            ),
            "info",
        )


if __name__ == "__main__":
    unittest.main()
