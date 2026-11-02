import unittest

from splash_receive import classify_offer_for_asset, normalize_offer_summary


class SplashReceiveTests(unittest.TestCase):
    def test_nested_sage_buy_offer(self):
        asset = "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105"
        result = classify_offer_for_asset(
            {
                "offer": {
                    "fee": 0,
                    "maker": [{"asset": {"asset_id": None}, "amount": 250010000000}],
                    "taker": [{"asset": {"asset_id": asset}, "amount": 3707971}],
                    "expiration_height": None,
                    "expiration_timestamp": 1791948323,
                },
                "status": "active",
            },
            asset,
        )
        self.assertTrue(result["relevant"])
        self.assertEqual(result["side"], "buy")
        self.assertEqual(
            result["summary"],
            {"offered": {"xch": 250010000000}, "requested": {asset: 3707971}},
        )

    def test_nested_sage_sell_offer(self):
        asset = "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105"
        result = classify_offer_for_asset(
            {
                "offer": {
                    "fee": 0,
                    "maker": [{"asset": {"asset_id": asset}, "amount": 3027671}],
                    "taker": [{"asset": {"asset_id": None}, "amount": 250010000000}],
                    "expiration_height": None,
                    "expiration_timestamp": 1791948323,
                },
                "status": "active",
            },
            asset,
        )
        self.assertTrue(result["relevant"])
        self.assertEqual(result["side"], "sell")
        self.assertEqual(
            result["summary"],
            {"offered": {asset: 3027671}, "requested": {"xch": 250010000000}},
        )

    def test_nested_sage_other_pair_is_not_relevant(self):
        result = classify_offer_for_asset(
            {
                "offer": {
                    "maker": [{"asset": {"asset_id": None}, "amount": 1000}],
                    "taker": [{"asset": {"asset_id": "othercat"}, "amount": 5000}],
                }
            },
            "abc123",
        )
        self.assertFalse(result["relevant"])
        self.assertEqual(result["pair_hint"], "othercat")

    def test_nested_sage_complex_offer_is_not_relevant(self):
        result = classify_offer_for_asset(
            {
                "offer": {
                    "maker": [
                        {"asset": {"asset_id": None}, "amount": 1000},
                        {"asset": {"asset_id": "abc123"}, "amount": 5},
                    ],
                    "taker": [{"asset": {"asset_id": "abc123"}, "amount": 5000}],
                }
            },
            "abc123",
        )
        self.assertFalse(result["relevant"])
        self.assertEqual(result["side"], "")

    def test_normalize_maker_taker_summary(self):
        summary = normalize_offer_summary(
            {
                "summary": {
                    "maker": [{"asset": {"asset_id": None}, "amount": 1000}],
                    "taker": [{"asset": {"asset_id": "abc123"}, "amount": 5000}],
                }
            }
        )
        self.assertEqual(summary["offered"], {"xch": 1000})
        self.assertEqual(summary["requested"], {"abc123": 5000})

    def test_classify_relevant_buy_offer(self):
        result = classify_offer_for_asset(
            {
                "summary": {
                    "offered": {"xch": 1000},
                    "requested": {"abc123": 5000},
                }
            },
            "abc123",
        )
        self.assertTrue(result["relevant"])
        self.assertEqual(result["side"], "buy")
        self.assertEqual(result["pair_hint"], "abc123")

    def test_classify_relevant_sell_offer(self):
        result = classify_offer_for_asset(
            {
                "summary": {
                    "offered": {"ABC123": 5000},
                    "requested": {"xch": 1000},
                }
            },
            "abc123",
        )
        self.assertTrue(result["relevant"])
        self.assertEqual(result["side"], "sell")
        self.assertEqual(result["pair_hint"], "abc123")

    def test_ignore_other_pair(self):
        result = classify_offer_for_asset(
            {
                "summary": {
                    "offered": {"xch": 1000},
                    "requested": {"othercat": 5000},
                }
            },
            "abc123",
        )
        self.assertFalse(result["relevant"])
        self.assertEqual(result["side"], "buy")
        self.assertEqual(result["pair_hint"], "othercat")

    def test_ignore_complex_offer(self):
        result = classify_offer_for_asset(
            {
                "summary": {
                    "offered": {"xch": 1000, "abc123": 5},
                    "requested": {"abc123": 5000},
                }
            },
            "abc123",
        )
        self.assertFalse(result["relevant"])
        self.assertEqual(result["side"], "")
        self.assertEqual(result["pair_hint"], "")


if __name__ == "__main__":
    unittest.main()
