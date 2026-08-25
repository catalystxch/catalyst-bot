"""Legacy Sage batch-cancel compatibility at the typed Task 8 boundary."""

import unittest
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
    def test_batch_preserves_exact_rejection_for_every_member(self):
        trade_ids = ["a" * 64, "b" * 64, "c" * 64]
        rejected = cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error_code": "REJECTED"},
            error="REJECTED",
        )

        with patch.object(wallet_sage, "cancel_offer", return_value=rejected) as cancel:
            results = wallet_sage.cancel_offers_batch(trade_ids, secure=True)

        self.assertEqual(cancel.call_count, len(trade_ids))
        self.assertEqual(set(results), set(trade_ids))
        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_FAILED)
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_preserves_submitted_only_with_exact_identity(self):
        trade_ids = ["a" * 64, "b" * 64]
        submitted = cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method="single_rpc",
            raw_response={"success": True, "transaction_id": "1" * 64},
            transaction_id="1" * 64,
        )

        with patch.object(wallet_sage, "cancel_offer", return_value=submitted):
            results = wallet_sage.cancel_offers_batch(trade_ids, secure=True)

        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_SUBMITTED_UNCONFIRMED)
            self.assertEqual(result["transaction_id"], "1" * 64)
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_truthy_ack_without_identity_is_unknown(self):
        trade_ids = ["a" * 64, "b" * 64]

        with patch.object(
            wallet_sage,
            "cancel_offer",
            return_value={"success": True, "method": "legacy_ack"},
        ):
            results = wallet_sage.cancel_offers_batch(trade_ids, secure=True)

        for result in results.values():
            self.assertEqual(result["outcome"], CANCEL_UNKNOWN)
            self.assertFalse(result["success"])
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_member_exception_is_total_and_does_not_drop_later_members(self):
        trade_ids = ["a" * 64, "b" * 64, "c" * 64]
        rejected = cancellation_result(
            CANCEL_FAILED,
            method="single_rpc",
            raw_response={"success": False, "error_code": "REJECTED"},
            error="REJECTED",
        )
        responses = iter([rejected, RuntimeError("private response"), rejected])

        def member(*_args, **_kwargs):
            response = next(responses)
            if isinstance(response, BaseException):
                raise response
            return response

        with patch.object(wallet_sage, "cancel_offer", side_effect=member):
            results = wallet_sage.cancel_offers_batch(trade_ids, secure=True)

        self.assertEqual(
            [results[trade_id]["outcome"] for trade_id in trade_ids],
            [CANCEL_FAILED, CANCEL_UNKNOWN, CANCEL_FAILED],
        )
        self.assertNotIn("private response", str(results))
        for result in results.values():
            self.assertEqual(validate_cancel_result(result), result)

    def test_batch_forwards_adapter_near_identity_recheck_to_each_member(self):
        trade_ids = ["a" * 64, "b" * 64]
        events = []

        def member(trade_id, *_args, _identity_recheck=None, **_kwargs):
            _identity_recheck("cancel_offer")
            events.append(trade_id)
            return cancellation_result(
                CANCEL_FAILED,
                method="single_rpc",
                raw_response={"success": False, "error_code": "REJECTED"},
                error="REJECTED",
            )

        with patch.object(wallet_sage, "cancel_offer", side_effect=member):
            wallet_sage.cancel_offers_batch(
                trade_ids,
                secure=True,
                _identity_recheck=lambda step: events.append(f"check:{step}"),
            )

        self.assertEqual(
            events,
            [
                "check:cancel_offer",
                trade_ids[0],
                "check:cancel_offer",
                trade_ids[1],
            ],
        )


if __name__ == "__main__":
    unittest.main()
