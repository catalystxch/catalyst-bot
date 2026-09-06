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
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(wallet_sage, "_sage_post", return_value={"success": True}),
            patch.object(wallet_sage, "get_pending_transactions") as pending,
            patch.object(wallet_sage, "get_all_offers") as offers,
            patch.object(wallet_sage, "get_owned_coins_detailed") as owned,
        ):
            results = wallet_sage.cancel_offers_batch(["0xabc123"], secure=False)

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_UNKNOWN)
        self.assertFalse(results["0xabc123"]["success"])
        pending.assert_not_called()
        offers.assert_not_called()
        owned.assert_not_called()
        validate_cancel_result(results["0xabc123"])

    def test_cancel_batch_does_not_confirm_when_offer_disappears_but_tx_pending(self):
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(wallet_sage, "_sage_post", return_value={"success": True}),
            patch.object(
                wallet_sage,
                "get_pending_transactions",
                return_value=[{"transaction_id": "pending"}],
            ) as pending,
            patch.object(wallet_sage, "get_all_offers", return_value=[]) as offers,
            patch.object(
                wallet_sage, "get_owned_coins_detailed", return_value={}
            ) as owned,
        ):
            results = wallet_sage.cancel_offers_batch(["0xabc123"], secure=False)

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_UNKNOWN)
        pending.assert_not_called()
        offers.assert_not_called()
        owned.assert_not_called()
        validate_cancel_result(results["0xabc123"])

    def test_cancel_batch_does_not_confirm_when_offer_lock_still_visible(self):
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(wallet_sage, "_sage_post", return_value={"success": True}),
            patch.object(wallet_sage, "get_pending_transactions") as pending,
            patch.object(wallet_sage, "get_all_offers", return_value=[]) as offers,
            patch.object(
                wallet_sage,
                "get_owned_coins_detailed",
                return_value={"0xcoin": {"offer_id": "0xabc123"}},
            ) as owned,
        ):
            results = wallet_sage.cancel_offers_batch(["0xabc123"], secure=False)

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_UNKNOWN)
        pending.assert_not_called()
        offers.assert_not_called()
        owned.assert_not_called()
        validate_cancel_result(results["0xabc123"])

    def test_bulk_cancel_preserves_no_spendable_failure_without_fee_fallback(self):
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageOperationalError(
                    error_code="NO_SPENDABLE_COINS"
                ),
            ) as sage_post,
        ):
            results = wallet_sage.cancel_offers_batch(
                ["0xabc123"],
                secure=True,
                fee_mojos=100,
                skip_confirmation=True,
            )

        self.assertEqual(results["0xabc123"]["outcome"], CANCEL_FAILED)
        sage_post.assert_called_once_with(
            "cancel_offers",
            {
                "offer_ids": ["0xabc123"],
                "fee": "100",
                "auto_submit": False,
            },
            timeout=60,
            retry_transport_error=False,
        )

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

    def test_bulk_cancel_replicates_stable_no_spendable_code_to_every_member(self):
        trade_ids = ["0xabc123", "0xdef456"]
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageOperationalError(
                    error_code="NO_SPENDABLE_COINS"
                ),
            ) as sage_post,
        ):
            results = wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=100,
                skip_confirmation=True,
            )

        sage_post.assert_called_once()
        self.assertEqual(set(results), set(trade_ids))
        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_FAILED)
            self.assertEqual(result["error"], "REJECTED")
            validate_cancel_result(result)

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

    def test_cancel_offer_derives_identity_from_signed_sage_bundle(self):
        from chia_rs import Coin, CoinSpend, G2Element, Program, SpendBundle
        from chia_rs.sized_bytes import bytes32

        coin = Coin(bytes32(b"1" * 32), bytes32(b"2" * 32), 1)
        coin_spend = CoinSpend(coin, Program.to(1), Program.to([]))
        spend_bundle = SpendBundle([coin_spend], G2Element())
        spend_bundle_json = spend_bundle.to_json_dict()
        expected_transaction_id = spend_bundle.name().hex()
        requests = []

        def sage_post(endpoint, payload, **kwargs):
            requests.append((endpoint, payload))
            if endpoint == "cancel_offer":
                return {
                    "summary": {"inputs": [], "outputs": []},
                    "coin_spends": spend_bundle_json["coin_spends"],
                }
            if endpoint == "sign_coin_spends":
                return {"spend_bundle": spend_bundle_json}
            if endpoint == "submit_transaction":
                return {}
            raise AssertionError(f"unexpected Sage endpoint: {endpoint}")

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(wallet_sage, "_sage_post", side_effect=sage_post),
            patch.object(wallet_sage, "get_pending_transactions") as pending,
            patch("builtins.print"),
        ):
            result = wallet_sage.cancel_offer("0xabc123", secure=False)

        self.assertEqual(
            [endpoint for endpoint, _payload in requests],
            ["cancel_offer", "sign_coin_spends", "submit_transaction"],
        )
        self.assertFalse(requests[0][1]["auto_submit"])
        self.assertEqual(result["outcome"], CANCEL_SUBMITTED_UNCONFIRMED)
        self.assertTrue(result["submitted"])
        self.assertEqual(result["transaction_id"], expected_transaction_id)
        pending.assert_not_called()
        validate_cancel_result(result)

    def test_signed_sage_v013_bare_program_hex_still_derives_identity(self):
        """Sage v0.13 omits 0x on puzzle_reveal and solution fields."""
        from chia_rs import Coin, CoinSpend, G2Element, Program, SpendBundle
        from chia_rs.sized_bytes import bytes32

        coin = Coin(bytes32(b"3" * 32), bytes32(b"4" * 32), 2)
        coin_spend = CoinSpend(coin, Program.to(1), Program.to([]))
        spend_bundle = SpendBundle([coin_spend], G2Element())
        sage_v013_json = spend_bundle.to_json_dict()
        for spend in sage_v013_json["coin_spends"]:
            spend["puzzle_reveal"] = spend["puzzle_reveal"].removeprefix("0x")
            spend["solution"] = spend["solution"].removeprefix("0x")

        self.assertEqual(
            wallet_sage._spend_bundle_transaction_id(sage_v013_json),
            spend_bundle.name().hex(),
        )
        self.assertFalse(
            sage_v013_json["coin_spends"][0]["puzzle_reveal"].startswith("0x")
        )
        self.assertFalse(sage_v013_json["coin_spends"][0]["solution"].startswith("0x"))

    def test_cancel_offer_uses_single_new_pending_txid_when_bundle_name_is_unavailable(
        self,
    ):
        transaction_id = "a" * 64
        requests = []

        def sage_post(endpoint, payload, **kwargs):
            requests.append((endpoint, payload))
            if endpoint == "cancel_offer":
                return {
                    "summary": {"inputs": [], "outputs": []},
                    "coin_spends": [{"coin": "live-sage-shape"}],
                }
            if endpoint == "sign_coin_spends":
                return {
                    "spend_bundle": {
                        "coin_spends": [{"coin": "live-sage-shape"}],
                        "aggregated_signature": "0xsig",
                    }
                }
            if endpoint == "submit_transaction":
                return {"success": True, "status": "success"}
            raise AssertionError(f"unexpected Sage endpoint: {endpoint}")

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(wallet_sage, "_sage_post", side_effect=sage_post),
            patch.object(
                wallet_sage,
                "_spend_bundle_transaction_id",
                return_value=None,
            ),
            patch.object(
                wallet_sage,
                "get_pending_transactions",
                side_effect=[[], [{"transaction_id": transaction_id}]],
            ),
            patch("builtins.print"),
        ):
            result = wallet_sage.cancel_offer("0xabc123", secure=False)

        self.assertEqual(
            [endpoint for endpoint, _payload in requests],
            ["cancel_offer", "sign_coin_spends", "submit_transaction"],
        )
        self.assertEqual(result["outcome"], CANCEL_SUBMITTED_UNCONFIRMED)
        self.assertTrue(result["submitted"])
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
