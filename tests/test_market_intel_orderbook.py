import importlib
import sys
import types
import unittest
import hashlib
from decimal import Decimal


class MarketIntelOrderbookTests(unittest.TestCase):
    def setUp(self):
        fake_config = types.ModuleType("config")
        fake_config.cfg = types.SimpleNamespace(
            CAT_ASSET_ID="test-cat",
            DBX_MAX_SPREAD_BPS=Decimal("500"),
        )
        fake_database = types.ModuleType("database")
        fake_database.log_event = lambda *args, **kwargs: None
        fake_database.get_trade_dexie_map = lambda *args, **kwargs: {}
        fake_requests = types.ModuleType("requests")

        class _FakeSession:
            def __init__(self):
                self.headers = {}

        fake_requests.Session = _FakeSession

        sys.modules["config"] = fake_config
        sys.modules["database"] = fake_database
        sys.modules["requests"] = fake_requests
        sys.modules.pop("market_intel", None)
        self.market_intel = importlib.import_module("market_intel")
        self.intel = self.market_intel.MarketIntel()

    def tearDown(self):
        sys.modules.pop("market_intel", None)
        sys.modules.pop("config", None)
        sys.modules.pop("database", None)
        sys.modules.pop("requests", None)

    def test_inverted_competitor_book_is_ignored(self):
        buy_offers = [
            {
                "price": Decimal("0.00012"),
                "xch_amount": Decimal("1.0"),
                "side": "buy",
                "is_ours": False,
            },
        ]
        sell_offers = [
            {
                "price": Decimal("0.00011"),
                "xch_amount": Decimal("1.0"),
                "side": "sell",
                "is_ours": False,
            },
        ]

        self.intel._analyse_orderbook(buy_offers, sell_offers)
        summary = self.intel.get_market_summary()

        self.assertEqual(summary["best_bid"], "0")
        self.assertEqual(summary["best_ask"], "0")
        self.assertEqual(summary["competitor_spread_bps"], "0")
        self.assertEqual(summary["overall_spread_bps"], "0")

    def test_parse_dexie_offer_marks_known_dexie_ids_as_ours(self):
        self.intel._known_dexie_ids = {"dexie-123"}

        parsed = self.intel._parse_dexie_offer(
            {
                "id": "dexie-123",
                "offered": [{"id": "", "code": "XCH", "amount": "1.2"}],
                "requested": [{"id": "test-cat", "code": "TEST", "amount": "1000"}],
                "tags": [],
            },
            "buy",
        )

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["is_ours"])

    def test_parse_dexie_offer_preserves_exact_publication_identity(self):
        offer_text = "offer1exact-publication"
        parsed = self.intel._parse_dexie_offer(
            {
                "id": "dexie-row-1",
                "trade_id": "0x" + "ab" * 32,
                "offer": offer_text,
                "offered": {"code": "XCH", "amount": "1"},
                "requested": {
                    "id": "test-cat",
                    "code": "MZ",
                    "amount": "10000",
                },
            },
            "buy",
        )

        self.assertEqual(
            parsed["offer_identity"],
            hashlib.sha256(offer_text.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(parsed["trade_id"], "ab" * 32)

    def test_parse_current_dexie_v1_single_asset_objects(self):
        """Dexie v1 currently returns offered/requested as objects, not arrays."""
        self.intel._known_dexie_ids = {"dexie-current-shape"}

        parsed = self.intel._parse_dexie_offer(
            {
                "id": "dexie-current-shape",
                "offered": {
                    "id": "test-cat",
                    "code": "TEST",
                    "name": "Test Token",
                    "amount": 9151.136,
                },
                "requested": {
                    "id": "xch",
                    "code": "XCH",
                    "name": "Chia",
                    "amount": 0.7901,
                },
                "date_found": "2026-09-05T16:23:34Z",
            },
            "sell",
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["price"], Decimal("0.7901") / Decimal("9151.136"))
        self.assertEqual(parsed["cat_amount"], Decimal("9151.136"))
        self.assertEqual(parsed["xch_amount"], Decimal("0.7901"))
        self.assertTrue(parsed["is_ours"])

    def test_orderbook_snapshot_identifies_aggregated_v3_source(self):
        """Catches v3 price levels being mistaken for attributable offers."""

        self.intel._competitors["orderbook_source"] = "dexie_v3_orderbook"

        snapshot = self.intel.get_orderbook_snapshot()

        self.assertEqual(snapshot["source"], "dexie_v3_orderbook")

    def test_anonymous_v3_book_does_not_replace_attributed_own_only_v1_book(self):
        """An own-only v1 book is valid evidence that there are no competitors."""
        own_buy = {
            "price": Decimal("0.00008066"),
            "xch_amount": Decimal("0.9581"),
            "cat_amount": Decimal("11878.107"),
            "side": "buy",
            "is_ours": True,
        }
        own_sell = {
            "price": Decimal("0.00008634"),
            "xch_amount": Decimal("0.7901"),
            "cat_amount": Decimal("9151.136"),
            "side": "sell",
            "is_ours": True,
        }
        self.intel._orderbook["buy_offers"] = [own_buy]
        self.intel._orderbook["sell_offers"] = [own_sell]
        self.intel._analyse_orderbook([own_buy], [own_sell], source="dexie_v1_offers")

        anonymous_v3_buy = [{**own_buy, "is_ours": False}]
        anonymous_v3_sell = [{**own_sell, "is_ours": False}]

        self.assertFalse(
            self.intel._should_use_v3_orderbook(anonymous_v3_buy, anonymous_v3_sell)
        )

    def test_attributable_snapshot_never_returns_anonymous_v3_levels(self):
        exact_buy = {
            "offer_id": "dexie-buy-1",
            "price": Decimal("0.00008"),
            "xch_amount": Decimal("1.25"),
            "cat_amount": Decimal("15625"),
            "side": "buy",
            "is_ours": False,
        }
        exact_sell = {
            "offer_id": "dexie-sell-1",
            "price": Decimal("0.00009"),
            "xch_amount": Decimal("1.35"),
            "cat_amount": Decimal("15000"),
            "side": "sell",
            "is_ours": False,
        }
        anonymous_v3 = {
            "offer_id": "v3-level-buy-0",
            "price": Decimal("0.000081"),
            "xch_amount": Decimal("99"),
            "cat_amount": Decimal("1"),
            "side": "buy",
            "is_ours": False,
        }
        self.intel._orderbook.update(
            {
                "exact_buy_offers": [exact_buy],
                "exact_sell_offers": [exact_sell],
                "buy_offers": [anonymous_v3],
                "sell_offers": [],
                "last_refresh": 123.0,
            }
        )

        snapshot = self.intel.get_attributable_orderbook()

        self.assertEqual(snapshot["bids"][0]["offer_id"], "dexie-buy-1")
        self.assertEqual(snapshot["asks"][0]["offer_id"], "dexie-sell-1")
        self.assertEqual(snapshot["bids"][0]["amount_mojos"], 1_250_000_000_000)
        self.assertEqual(snapshot["observed_at_unix"], 123.0)
        self.assertEqual(snapshot["source_time"], "1970-01-01T00:02:03Z")


if __name__ == "__main__":
    unittest.main()
