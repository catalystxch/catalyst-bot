"""Sage native batch-cancel compatibility at the typed Task 8 boundary."""

import unittest
import json
from pathlib import Path
from unittest.mock import patch

import wallet_sage
from cancel_outcomes import (
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    CANCEL_UNKNOWN,
    cancellation_result,
    validate_cancel_result,
)


class SageTypedBatchCancelCompatibilityTests(unittest.TestCase):
    def test_fee_bearing_batch_adds_one_explicit_fee_spend_before_one_submission(self):
        from chia_rs import Coin, CoinSpend, G2Element, Program, SpendBundle
        from chia_rs.sized_bytes import bytes32

        from chia.util.bech32m import encode_puzzle_hash

        fee_mojos = 13_079_100
        # Use real executable CAT/native effects. A summary claiming outputs
        # with empty puzzle solutions must be refused by the adapter.
        cat = json.loads((Path(__file__).parent / "fixtures" / "coin_prep_unsigned_cat2.json").read_text())
        puzzle = Program.to(1)
        destination = bytes32(b"d" * 32)

        def native(parent, amount, fee):
            coin = Coin(parent, puzzle.get_tree_hash(), amount)
            output = Coin(coin.name(), destination, amount - fee)
            spend = CoinSpend(coin, puzzle, Program.to([[51, destination, amount - fee]]))
            return spend, {"coin_id": coin.name().hex(), "amount": amount, "asset": None,
                           "outputs": [{"coin_id": output.name().hex(), "amount": amount - fee,
                                        "address": encode_puzzle_hash(destination, "xch"),
                                        "receiving": True, "burning": False}]}

        native_spend, native_summary = native(b"2" * 32, 2_000, 0)
        fee_spend, fee_summary = native(b"3" * 32, 1_000_000_000, fee_mojos)
        spends = [CoinSpend.from_json_dict(cat["coin_spends"][0]), native_spend, fee_spend]
        source_coin_ids = [spend.coin.name().hex() for spend in spends[:2]]
        fee_coin_id = fee_spend.coin.name().hex()
        trade_ids = ["a" * 64, "b" * 64]
        signed_bundle = SpendBundle(spends, G2Element())
        signed_json = signed_bundle.to_json_dict()
        requests = []

        def sage_post(endpoint, payload, **kwargs):
            requests.append((endpoint, payload))
            if endpoint == "cancel_offers":
                return {
                    "summary": {
                        "fee": 0,
                        "inputs": [cat["summary"]["inputs"][0], native_summary],
                    },
                    "coin_spends": signed_json["coin_spends"][:2],
                }
            if endpoint == "create_transaction":
                return {
                    "summary": {
                        "fee": fee_mojos,
                        "inputs": [fee_summary],
                    },
                    "coin_spends": signed_json["coin_spends"][2:],
                }
            if endpoint == "sign_coin_spends":
                return {"spend_bundle": signed_json}
            if endpoint == "submit_transaction":
                return {}
            raise AssertionError(f"unexpected Sage endpoint: {endpoint}")

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(wallet_sage, "_sage_post", side_effect=sage_post),
        ):
            results = wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=fee_mojos,
                source_coin_ids=source_coin_ids,
                fee_coin_id=fee_coin_id,
            )

        self.assertEqual(
            [endpoint for endpoint, _payload in requests],
            [
                "cancel_offers",
                "create_transaction",
                "sign_coin_spends",
                "submit_transaction",
            ],
        )
        self.assertEqual(requests[0][1]["fee"], "0")
        self.assertEqual(requests[0][1]["offer_ids"], trade_ids)
        self.assertEqual(requests[1][1]["selected_coin_ids"], [fee_coin_id])
        self.assertEqual(
            requests[1][1]["actions"],
            [{"type": "fee", "amount": str(fee_mojos)}],
        )
        self.assertEqual(len(requests[2][1]["coin_spends"]), 3)
        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_SUBMITTED_UNCONFIRMED)
            self.assertEqual(result["transaction_id"], signed_bundle.name().hex())
            self.assertEqual(result["method"], "bulk_rpc")
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_refuses_sage_v013_repeated_fee_bundle_before_signing(self):
        trade_ids = ["a" * 64, "b" * 64]
        unsafe_unsigned = {
            "summary": {
                "fee": 26_158_200,
                "inputs": [
                    {"coin_id": "1" * 64, "outputs": []},
                    {"coin_id": "2" * 64, "outputs": []},
                    {"coin_id": "2" * 64, "outputs": []},
                ],
            },
            "coin_spends": [{"coin": "unsafe"}],
        }

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                return_value=unsafe_unsigned,
            ) as sage_post,
        ):
            results = wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=13_079_100,
            )

        sage_post.assert_called_once_with(
            "cancel_offers",
            {
                "offer_ids": trade_ids,
                "fee": "13079100",
                "auto_submit": False,
            },
            timeout=60,
            retry_transport_error=False,
        )
        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_FAILED)
            self.assertEqual(result["method"], "bulk_rpc")
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_uses_sage_native_cancel_offers_once_for_every_member(self):
        trade_ids = ["a" * 64, "b" * 64, "c" * 64]
        transaction_id = "1" * 64

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                return_value={"success": True, "transaction_id": transaction_id},
            ) as sage_post,
        ):
            results = wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=13_079_100,
            )

        sage_post.assert_called_once_with(
            "cancel_offers",
            {
                "offer_ids": trade_ids,
                "fee": "13079100",
                "auto_submit": False,
            },
            timeout=60,
            retry_transport_error=False,
        )
        self.assertEqual(set(results), set(trade_ids))
        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_SUBMITTED_UNCONFIRMED)
            self.assertEqual(result["transaction_id"], transaction_id)
            self.assertEqual(result["method"], "bulk_rpc")
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_preserves_exact_rejection_for_every_member(self):
        trade_ids = ["a" * 64, "b" * 64, "c" * 64]

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageOperationalError(error_code="REJECTED"),
            ) as sage_post,
        ):
            results = wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=13_079_100,
            )

        sage_post.assert_called_once()
        self.assertEqual(set(results), set(trade_ids))
        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_FAILED)
            self.assertEqual(result["method"], "bulk_rpc")
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_preserves_submitted_only_with_exact_identity(self):
        trade_ids = ["a" * 64, "b" * 64]
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                return_value={"success": True, "transaction_id": "1" * 64},
            ) as sage_post,
        ):
            results = wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=13_079_100,
            )

        sage_post.assert_called_once()
        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_SUBMITTED_UNCONFIRMED)
            self.assertEqual(result["transaction_id"], "1" * 64)
            self.assertEqual(result["method"], "bulk_rpc")
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_truthy_ack_without_identity_is_unknown(self):
        trade_ids = ["a" * 64, "b" * 64]

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                return_value={"success": True},
            ) as sage_post,
        ):
            results = wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=13_079_100,
            )

        sage_post.assert_called_once()
        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_UNKNOWN)
            self.assertFalse(result["success"])
            self.assertEqual(result["method"], "bulk_rpc")
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_endpoint_exception_is_total_and_does_not_leak_private_text(self):
        trade_ids = ["a" * 64, "b" * 64, "c" * 64]
        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=RuntimeError("private response"),
            ) as sage_post,
        ):
            results = wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=13_079_100,
            )

        sage_post.assert_called_once()
        self.assertEqual(set(results), set(trade_ids))
        self.assertEqual(
            {result["outcome"] for result in results.values()}, {CANCEL_UNKNOWN}
        )
        self.assertNotIn("private response", str(results))
        for result in results.values():
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_runs_adapter_near_identity_recheck_once_for_shared_effect(self):
        trade_ids = ["a" * 64, "b" * 64]
        events = []

        with (
            patch.object(wallet_sage, "_require_signing_capability", return_value=True),
            patch.object(
                wallet_sage,
                "_sage_post",
                side_effect=wallet_sage.SageOperationalError(error_code="REJECTED"),
            ) as sage_post,
        ):
            wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                fee_mojos=13_079_100,
                _identity_recheck=events.append,
            )

        sage_post.assert_called_once()
        self.assertEqual(events, ["cancel_offers"])


if __name__ == "__main__":
    unittest.main()
