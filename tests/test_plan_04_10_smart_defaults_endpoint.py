"""Slice 04-10 — smart-defaults endpoint contract tests.

Tests GET /api/smart-defaults:
  - No auth required (read-only)
  - liquidity_mode parameter routing (two_sided/buy_only/sell_only)
  - Invalid liquidity_mode falls back to two_sided
  - risk_profile parameter forwarded
  - Exception path returns 500
"""

import os
import sys
import unittest
from decimal import Decimal
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import api_server
    from flask import jsonify as _jsonify

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    _SKIP = str(exc)


def _fake_defaults_response(**kwargs):
    """Return a Flask Response mimicking _calculate_smart_defaults output."""
    with api_server.app.app_context():
        return _jsonify(
            {
                "success": True,
                "spread_bps": 200,
                "default_trade_xch": "0.5",
                "liquidity_mode": kwargs.get("liquidity_mode", "two_sided"),
                "risk_profile": kwargs.get("risk_profile", "balanced"),
            }
        )


def _green_market_confidence(
    bid="0.00009", ask="0.00011", depth_mojos=1_000_000_000_000_000
):
    bid_value = Decimal(str(bid))
    ask_value = Decimal(str(ask))
    return SimpleNamespace(
        state="GREEN",
        trusted_midpoint=(bid_value + ask_value) / Decimal("2"),
        trusted_bid=bid_value,
        trusted_ask=ask_value,
        independent_bid_depth_mojos=depth_mojos,
        independent_ask_depth_mojos=depth_mojos,
        manipulation_score=0,
        reason_codes=(),
        evidence_digests=("a" * 64, "b" * 64),
        source_health={"dexie": "valid", "splash": "valid"},
    )


class _FlaskBase(unittest.TestCase):
    _LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

    def setUp(self):
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        api_server._rate_limit_log.clear()

    def tearDown(self):
        api_server._rate_limit_log.clear()


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSmartDefaults(_FlaskBase):
    def test_returns_200(self):
        with patch.object(
            api_server, "_calculate_smart_defaults", side_effect=_fake_defaults_response
        ):
            resp = self.client.get("/api/smart-defaults", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_default_liquidity_mode_two_sided(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_defaults_response(**kwargs)

        with patch.object(api_server, "_calculate_smart_defaults", side_effect=capture):
            self.client.get("/api/smart-defaults", environ_base=self._LOOPBACK)
        self.assertEqual(captured.get("liquidity_mode"), "two_sided")

    def test_buy_only_mode_forwarded(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_defaults_response(**kwargs)

        with patch.object(api_server, "_calculate_smart_defaults", side_effect=capture):
            self.client.get(
                "/api/smart-defaults?liquidity_mode=buy_only",
                environ_base=self._LOOPBACK,
            )
        self.assertEqual(captured.get("liquidity_mode"), "buy_only")

    def test_sell_only_mode_forwarded(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_defaults_response(**kwargs)

        with patch.object(api_server, "_calculate_smart_defaults", side_effect=capture):
            self.client.get(
                "/api/smart-defaults?liquidity_mode=sell_only",
                environ_base=self._LOOPBACK,
            )
        self.assertEqual(captured.get("liquidity_mode"), "sell_only")

    def test_invalid_liquidity_mode_falls_back_to_two_sided(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_defaults_response(**kwargs)

        with patch.object(api_server, "_calculate_smart_defaults", side_effect=capture):
            self.client.get(
                "/api/smart-defaults?liquidity_mode=invalid_mode",
                environ_base=self._LOOPBACK,
            )
        self.assertEqual(captured.get("liquidity_mode"), "two_sided")

    def test_risk_profile_forwarded(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_defaults_response(**kwargs)

        with patch.object(api_server, "_calculate_smart_defaults", side_effect=capture):
            self.client.get(
                "/api/smart-defaults?risk_profile=conservative",
                environ_base=self._LOOPBACK,
            )
        self.assertEqual(captured.get("risk_profile"), "conservative")

    def test_exception_returns_500(self):
        with patch.object(
            api_server,
            "_calculate_smart_defaults",
            side_effect=Exception("market data unavailable"),
        ):
            resp = self.client.get("/api/smart-defaults", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertIn("error", body)

    def test_reserve_params_forwarded(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_defaults_response(**kwargs)

        with patch.object(api_server, "_calculate_smart_defaults", side_effect=capture):
            self.client.get(
                "/api/smart-defaults?xch_reserve=0.5&cat_reserve=100",
                environ_base=self._LOOPBACK,
            )
        self.assertEqual(str(captured.get("xch_reserve")), "0.5")
        self.assertEqual(str(captured.get("cat_reserve")), "100")

    def test_selected_cat_params_forwarded(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_defaults_response(**kwargs)

        with patch.object(api_server, "_calculate_smart_defaults", side_effect=capture):
            self.client.get(
                "/api/smart-defaults?"
                "asset_id=abc123&cat_wallet_id=7&cat_decimals=5&"
                "cat_ticker_id=FOO_XCH&cat_name=Foo",
                environ_base=self._LOOPBACK,
            )

        self.assertEqual(captured.get("asset_id"), "abc123")
        self.assertEqual(captured.get("cat_wallet_id"), 7)
        self.assertEqual(captured.get("cat_decimals"), 5)
        self.assertEqual(captured.get("cat_ticker_id"), "FOO_XCH")
        self.assertEqual(captured.get("cat_name"), "Foo")

    def test_zero_cat_decimals_are_forwarded(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return _fake_defaults_response(**kwargs)

        with patch.object(api_server, "_calculate_smart_defaults", side_effect=capture):
            self.client.get(
                "/api/smart-defaults?asset_id=abc123&cat_decimals=0",
                environ_base=self._LOOPBACK,
            )

        self.assertEqual(captured.get("cat_decimals"), 0)


class TestSmartDefaultsSourceContract(unittest.TestCase):
    _ASSET_ID = "b8" * 32

    def test_standalone_dexie_offer_normalization_is_exact_and_attributable(self):
        from blueprints.smart_defaults import _normalise_standalone_dexie_offer

        offer_text = "offer1qqqqexact"
        row = _normalise_standalone_dexie_offer(
            {
                "id": "dexie-row-1",
                "offer": offer_text,
                "offered": {"id": "xch", "code": "XCH", "amount": "0.3"},
                "requested": {
                    "id": self._ASSET_ID,
                    "code": "MZ",
                    "amount": "3",
                },
            },
            expected_side="buy",
            asset_id=self._ASSET_ID,
        )

        self.assertEqual(
            row,
            {
                "offer_id": hashlib.sha256(offer_text.encode("utf-8")).hexdigest(),
                "provider_offer_id": "dexie-row-1",
                "trade_id": "",
                "price": "0.1",
                "amount_mojos": 300_000_000_000,
            },
        )

    def test_standalone_dexie_offer_preserves_whole_number_price(self):
        from blueprints.smart_defaults import _normalise_standalone_dexie_offer

        row = _normalise_standalone_dexie_offer(
            {
                "id": "whole-number-price",
                "offered": {"id": "xch", "code": "XCH", "amount": "10"},
                "requested": {
                    "id": self._ASSET_ID,
                    "code": "MZ",
                    "amount": "1",
                },
            },
            expected_side="buy",
            asset_id=self._ASSET_ID,
        )

        self.assertEqual(row["price"], "10")

    def test_standalone_dexie_offer_rejects_fractional_mojos(self):
        from blueprints.smart_defaults import _normalise_standalone_dexie_offer

        with self.assertRaisesRegex(ValueError, "whole mojos"):
            _normalise_standalone_dexie_offer(
                {
                    "id": "dexie-row-2",
                    "offered": {
                        "id": "xch",
                        "code": "XCH",
                        "amount": "0.0000000000001",
                    },
                    "requested": {"id": self._ASSET_ID, "amount": "1"},
                },
                expected_side="buy",
                asset_id=self._ASSET_ID,
            )

    def test_standalone_dexie_book_uses_v1_filters_and_excludes_owned_depth(self):
        from blueprints.smart_defaults import _fetch_dexie_orderbook_standalone

        own_text = "offer1owned"
        own_identity = hashlib.sha256(own_text.encode("utf-8")).hexdigest()
        sell_response = MagicMock(
            status_code=200,
            json=lambda: {
                "offers": [
                    {
                        "id": "sell-provider-id",
                        "offer": own_text,
                        "offered": {"id": self._ASSET_ID, "amount": "10"},
                        "requested": {"id": "xch", "amount": "1"},
                    }
                ]
            },
        )
        buy_response = MagicMock(
            status_code=200,
            json=lambda: {
                "offers": [
                    {
                        "id": "buy-provider-id",
                        "offer": "offer1competitor",
                        "offered": {"id": "xch", "amount": "0.9"},
                        "requested": {"id": self._ASSET_ID, "amount": "10"},
                    }
                ]
            },
        )

        with patch("requests.get", side_effect=[sell_response, buy_response]) as get:
            result = _fetch_dexie_orderbook_standalone(
                self._ASSET_ID,
                own_offer_identities=frozenset({own_identity}),
            )

        self.assertEqual(
            get.call_args_list[0].kwargs["params"]["offered"], self._ASSET_ID
        )
        self.assertEqual(get.call_args_list[0].kwargs["params"]["requested"], "xch")
        self.assertEqual(get.call_args_list[1].kwargs["params"]["offered"], "xch")
        self.assertEqual(
            get.call_args_list[1].kwargs["params"]["requested"], self._ASSET_ID
        )
        self.assertEqual(result["num_sell_offers"], 0)
        self.assertEqual(result["sell_depth_xch"], Decimal("0"))
        self.assertEqual(result["best_bid"], Decimal("0.09"))
        self.assertEqual(result["buy_depth_xch"], Decimal("0.9"))
        self.assertEqual(result["provider_book"]["asks"][0]["offer_id"], own_identity)

    def test_smart_mid_uses_only_green_trusted_confidence(self):
        from blueprints.smart_defaults import _resolve_smart_mid_price

        green = {
            "state": "GREEN",
            "trusted_midpoint": Decimal("0.1000000000000000001"),
            "trusted_bid": Decimal("0.09"),
            "trusted_ask": Decimal("0.11"),
        }
        accepted = _resolve_smart_mid_price(
            ticker={},
            tibet={},
            spacescan={},
            trades={},
            orderbook={"best_bid": Decimal("9"), "best_ask": Decimal("10")},
            market_confidence=green,
            messages=[],
        )
        rejected = _resolve_smart_mid_price(
            ticker={},
            tibet={},
            spacescan={},
            trades={},
            orderbook={"best_bid": Decimal("0.09"), "best_ask": Decimal("0.11")},
            market_confidence={**green, "state": "AMBER"},
            messages=[],
        )

        self.assertEqual(accepted["mid_price"], Decimal("0.1000000000000000001"))
        self.assertEqual(accepted["price_source"], "trusted_offer_book")
        self.assertEqual(rejected["mid_price"], Decimal("0"))

    def test_smart_budget_price_math_preserves_decimal_precision(self):
        import inspect
        from blueprints.smart_defaults import (
            _calculate_smart_defaults,
            _cat_units_for_xch_exact,
            _xch_value_for_cat_exact,
        )

        price = Decimal("0.1000000000000000001")
        self.assertEqual(
            _cat_units_for_xch_exact(Decimal("1"), price), Decimal("1") / price
        )
        self.assertEqual(
            _xch_value_for_cat_exact(Decimal("10"), price),
            Decimal("1.0000000000000000010"),
        )

        source = inspect.getsource(_calculate_smart_defaults)
        self.assertNotIn("_avail_cat * mid_price", source)
        self.assertNotIn("_base_size / mid_price", source)
        self.assertIn("mid_price=mid_price_decimal", source)

    def test_calculation_has_no_live_tibet_decision_inputs(self):
        import inspect
        from blueprints.smart_defaults import _calculate_smart_defaults

        source = inspect.getsource(_calculate_smart_defaults)
        self.assertNotIn('tibet.get("xch_reserve"', source)
        self.assertNotIn("tibet_quote.get", source)
        self.assertNotIn("_smart_tibet_shock_trigger_pct", source)
        self.assertIn('"market_model": "offer_book"', source)
        self.assertIn('"tibet_status": "retired"', source)

    def test_price_resolver_uses_orderbook_when_ticker_and_tibet_missing(self):
        from blueprints.smart_defaults import _resolve_smart_mid_price

        messages = []
        resolved = _resolve_smart_mid_price(
            ticker={},
            tibet={},
            spacescan={},
            trades={},
            orderbook={"best_bid": 0.90, "best_ask": 1.10},
            market_confidence={
                "state": "GREEN",
                "trusted_midpoint": Decimal("1"),
                "trusted_bid": Decimal("0.90"),
                "trusted_ask": Decimal("1.10"),
            },
            messages=messages,
        )

        self.assertEqual(resolved["mid_price"], 1.0)
        self.assertEqual(resolved["dexie_price"], 1.0)
        self.assertEqual(resolved["price_source"], "trusted_offer_book")
        self.assertIn("trusted offer book", messages[0])

    def test_price_resolver_ignores_retired_tibet_and_prefers_live_book(self):
        from blueprints.smart_defaults import _resolve_smart_mid_price

        resolved = _resolve_smart_mid_price(
            ticker={"price": 2.0},
            tibet={"has_data": True, "price": 100.0},
            spacescan={},
            trades={},
            orderbook={"best_bid": 0.90, "best_ask": 1.10},
            market_confidence={
                "state": "GREEN",
                "trusted_midpoint": Decimal("1"),
                "trusted_bid": Decimal("0.90"),
                "trusted_ask": Decimal("1.10"),
            },
            messages=[],
        )

        self.assertEqual(resolved["mid_price"], 1.0)
        self.assertEqual(resolved["tibet_price"], 0)
        self.assertEqual(resolved["arb_gap_bps"], 0)
        self.assertEqual(resolved["price_source"], "trusted_offer_book")

    def test_price_resolver_rejects_ticker_and_trade_history_without_two_sided_book(
        self,
    ):
        from blueprints.smart_defaults import _resolve_smart_mid_price

        messages = []
        resolved = _resolve_smart_mid_price(
            ticker={"price": 9.0},
            tibet={},
            spacescan={},
            trades={
                "trades": [
                    {"price": 2.0, "xch_amount": 1.0},
                    {"price": 4.0, "xch_amount": 3.0},
                    {"price": 10.0, "xch_amount": 0.0},
                ]
            },
            orderbook={},
            market_confidence={"state": "RED"},
            messages=messages,
        )

        self.assertEqual(resolved["mid_price"], 0)
        self.assertEqual(resolved["dexie_price"], 0)
        self.assertEqual(resolved["price_source"], "")
        self.assertTrue(any("GREEN" in message for message in messages))

    def test_price_resolver_rejects_one_sided_orderbook(self):
        from blueprints.smart_defaults import _resolve_smart_mid_price

        messages = []
        resolved = _resolve_smart_mid_price(
            ticker={"price": 2.0},
            tibet={},
            spacescan={},
            trades={},
            orderbook={"best_bid": 1.0, "best_ask": 0},
            market_confidence={"state": "RED"},
            messages=messages,
        )

        self.assertEqual(resolved["mid_price"], 0)
        self.assertEqual(resolved["price_source"], "")
        self.assertTrue(any("GREEN" in message for message in messages))

    def test_response_contract_includes_safety_fields(self):
        root = Path(__file__).resolve().parents[1]
        src = (
            root / "src" / "catalyst" / "blueprints" / "smart_defaults.py"
        ).read_text(encoding="utf-8")
        result_block = src.split(
            '    result = {\n        "market_model": "offer_book"', 1
        )[1].split('print(f"[SMART_DEFAULTS v2]', 1)[0]

        self.assertIn('result = {\n        "market_model": "offer_book"', src)
        self.assertIn('"offer_book_policy"', result_block)
        self.assertIn('"tibet_status": "retired"', result_block)
        self.assertIn('"market_toxicity_enabled"', result_block)
        self.assertIn('"toxicity_protection_level"', result_block)
        self.assertIn('"toxicity_max_spread_multiplier"', result_block)
        self.assertIn('"toxicity_throttle_secs"', result_block)

    def test_frontend_has_safety_fields_and_matches_backend_keys(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "bot_gui.html").read_text(encoding="utf-8")

        self.assertIn('id="configTibetShockCancelPct"', html)
        self.assertIn('id="configArbThreshold"', html)
        self.assertIn("data.tibet_shock_cancel_trigger_pct", html)
        self.assertIn("data.arb_alert_threshold_bps", html)
        self.assertNotIn("data.arb_threshold_bps", html)
        self.assertIn("'ARB_ALERT_THRESHOLD_BPS':    'configArbThreshold'", html)

    def test_frontend_has_market_toxicity_settings_and_save_mapping(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "bot_gui.html").read_text(encoding="utf-8")

        for field_id in (
            "configMarketToxicityEnabled",
            "configToxicityProtectionLevel",
            "configToxicityMaxSpreadMultiplier",
            "configToxicityThrottleSecs",
        ):
            self.assertIn(f'id="{field_id}"', html)
            self.assertIn(f"'{field_id}'", html)

        self.assertIn("data.market_toxicity_enabled", html)
        self.assertIn("data.toxicity_protection_level", html)
        self.assertIn("market_toxicity_enabled:", html)
        self.assertIn("toxicity_protection_level:", html)
        self.assertIn("toxicity_max_spread_multiplier:", html)
        self.assertIn("toxicity_throttle_secs:", html)

    def test_frontend_explains_toxicity_levels_location(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "bot_gui.html").read_text(encoding="utf-8")

        self.assertIn("Market toxicity levels", html)
        self.assertIn("v4-settings-info-note", html)
        self.assertIn("Dashboard &rarr; Market Health &rarr; Toxicity", html)
        self.assertIn("Live score:", html)
        self.assertIn("Normal &lt;30", html)
        self.assertIn("Extreme 90+", html)

    def test_smart_toxicity_defaults_defensive_for_small_thin_one_sided_wallet(self):
        from blueprints.smart_defaults import _smart_toxicity_defaults

        rec = _smart_toxicity_defaults(
            avail_xch=1.5,
            avail_cat=500,
            liquidity_mode="buy_only",
            risk_level="thin",
            activity_level="quiet",
            fills_per_day=0.2,
            daily_volume=0.05,
            regime="volatile",
            arb_gap_bps=350,
            orderbook={"has_data": True, "num_buy_offers": 1, "num_sell_offers": 1},
        )

        self.assertTrue(rec["market_toxicity_enabled"])
        self.assertEqual(rec["toxicity_protection_level"], "defensive")
        self.assertLessEqual(rec["toxicity_throttle_start"], 65)
        self.assertEqual(rec["toxicity_min_throttle_signals"], 1)
        self.assertEqual(rec["toxicity_cancel_enabled"], False)

    def test_smart_toxicity_defaults_gentle_for_deep_healthy_market(self):
        from blueprints.smart_defaults import _smart_toxicity_defaults

        rec = _smart_toxicity_defaults(
            avail_xch=50,
            avail_cat=1_000_000,
            liquidity_mode="two_sided",
            risk_level="healthy",
            activity_level="active",
            fills_per_day=12,
            daily_volume=15,
            regime="normal",
            arb_gap_bps=20,
            orderbook={"has_data": True, "num_buy_offers": 30, "num_sell_offers": 28},
        )

        self.assertEqual(rec["toxicity_protection_level"], "gentle")
        self.assertGreaterEqual(rec["toxicity_throttle_start"], 85)
        self.assertLessEqual(rec["toxicity_max_spread_multiplier"], 1.5)

    def test_frontend_sends_selected_cat_to_smart_settings(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "bot_gui.html").read_text(encoding="utf-8")
        smart_block = html.split("async function getSmartDefaults()", 1)[1].split(
            "const resp = await apiFetch(`${API_URL}/smart-defaults?${params}`);", 1
        )[0]

        for key in (
            "asset_id",
            "cat_wallet_id",
            "cat_decimals",
            "cat_ticker_id",
            "cat_name",
        ):
            self.assertIn(key, smart_block)
        self.assertIn("selectedCAT.decimals ?? 3", smart_block)
        self.assertIn("currentCAT = { ...selectedCAT }", smart_block)

    def test_single_sided_smart_defaults_disable_inventory_management(self):
        root = Path(__file__).resolve().parents[1]
        src = (
            root / "src" / "catalyst" / "blueprints" / "smart_defaults.py"
        ).read_text(encoding="utf-8")
        buy_block = src.split('if liquidity_mode == "buy_only":', 1)[1].split(
            'elif liquidity_mode == "sell_only":', 1
        )[0]
        sell_block = src.split('elif liquidity_mode == "sell_only":', 1)[1].split(
            "# ── UNIVERSAL MAX_POSITION_XCH", 1
        )[0]

        self.assertIn('result["inventory_enabled"] = False', buy_block)
        self.assertIn('result["inventory_enabled"] = False', sell_block)

    def test_frontend_smart_settings_watches_safety_fields(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "bot_gui.html").read_text(encoding="utf-8")
        watched = html.split("const SMART_SETTINGS_WATCHED_INPUTS = [", 1)[1].split(
            "];", 1
        )[0]

        for field_id in (
            "configBaseSpreadBps",
            "configMinEdgeBps",
            "configRequoteBps",
            "configRequoteCooldown",
            "configDynamicLimitPct",
            "configMaxStepChange",
            "configTibetShockCancelPct",
            "configArbThreshold",
            "configCompetitorEnabled",
            "configDbxMaxSpreadBps",
            "configTopupPoolXch",
            "configTopupPoolCat",
            "configBuyInnerSizeXch",
            "configBuyExtremeSizeXch",
            "configSniperRearmPriceMovePct",
            "configSniperRearmGapMovePct",
            "configTransactionFeeTargetSecs",
            "configSplashEnabled",
            "configCoinPrepEnabled",
            "configRuntimeCoinHealth",
            "configSageChangeAddress",
        ):
            self.assertIn(field_id, watched)

    def test_frontend_reserve_advisor_preserves_zero_reserve(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "bot_gui.html").read_text(encoding="utf-8")

        self.assertIn("function readDashboardReserve", html)
        self.assertIn("readDashboardReserve(safety.xch_reserve)", html)
        self.assertIn("readDashboardReserve(safety.cat_reserve)", html)
        self.assertNotIn("parseFloat(safety.xch_reserve) || 25", html)
        self.assertNotIn("parseFloat(safety.cat_reserve) || 25", html)

    def test_frontend_reserve_action_scrolls_to_reserve_section(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "bot_gui.html").read_text(encoding="utf-8")

        self.assertIn('id="settings-section-reserves"', html)
        self.assertIn("getElementById('settings-section-reserves')", html)

    def test_frontend_reserve_warning_uses_buy_side_tier_count_ids(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "bot_gui.html").read_text(encoding="utf-8")
        reserve_fn = html.split("function checkReserveWarnings()", 1)[1].split(
            "function checkRiskWarnings()", 1
        )[0]

        for tier in ("Inner", "Mid", "Outer", "Extreme"):
            self.assertIn(f"config{tier}TierCountXch", reserve_fn)
            self.assertNotIn(f"configBuy{tier}TierCount", reserve_fn)
        self.assertIn("const _buyTierCount", reserve_fn)
        self.assertNotRegex(
            reserve_fn,
            r"_i\('config(?:Inner|Mid|Outer|Extreme)TierCountXch'\)\s*\|\|",
        )


class TestSmartDefaultsSmallWalletSizing(unittest.TestCase):
    def test_small_wallet_position_limit_has_no_five_xch_floor(self):
        from blueprints.smart_defaults import _smart_initial_max_position

        self.assertEqual(_smart_initial_max_position(1, 0, "healthy"), 0.4)
        self.assertEqual(_smart_initial_max_position(5, 0, "healthy"), 2.0)
        self.assertEqual(_smart_initial_max_position(5, 0, "moderate"), 1.5)
        self.assertLess(_smart_initial_max_position(5, 0, "healthy"), 5.0)

    def test_stale_trade_size_floor_is_capped_by_small_wallet(self):
        from blueprints.smart_defaults import _smart_initial_max_position

        self.assertLessEqual(_smart_initial_max_position(1, 0.5, "healthy"), 0.5)
        self.assertLessEqual(_smart_initial_max_position(5, 1.0, "healthy"), 2.5)

    def test_cat_topup_cap_floors_fractional_residual_units(self):
        from blueprints.smart_defaults import _cat_prep_units_floor

        self.assertEqual(_cat_prep_units_floor(0.999), 0)
        self.assertEqual(_cat_prep_units_floor(12.999), 12)
        self.assertEqual(_cat_prep_units_floor(-1), 0)

    def test_large_wallet_position_limit_keeps_existing_shape(self):
        from blueprints.smart_defaults import _smart_initial_max_position

        self.assertEqual(_smart_initial_max_position(100, 0, "healthy"), 40.0)
        self.assertEqual(_smart_initial_max_position(100, 0, "thin"), 20.0)

    def test_small_wallet_prep_counts_are_scaled_down(self):
        from blueprints.smart_defaults import (
            _smart_fee_prep_count,
            _smart_sniper_prep_plan,
        )

        self.assertLessEqual(_smart_fee_prep_count(1, 0.001), 10)

        self.assertLessEqual(_smart_fee_prep_count(5, 0.001), 20)

        one_xch_sniper = _smart_sniper_prep_plan(
            1, fills_per_day=12, sniper_size_xch=0.01
        )
        self.assertLessEqual(one_xch_sniper["count"], 2)
        self.assertLessEqual(one_xch_sniper["pool_xch"], 0.02)

        sniper = _smart_sniper_prep_plan(5, fills_per_day=12, sniper_size_xch=0.01)
        self.assertLessEqual(sniper["count"], 12)
        self.assertLessEqual(sniper["pool_xch"], 0.12)

    def test_sniper_size_scales_with_market_conditions(self):
        from blueprints.smart_defaults import _smart_sniper_size_xch

        thin_market_size = _smart_sniper_size_xch(
            avail_xch=5,
            fills_per_day=0.2,
            daily_volume_xch=0.03,
            orderbook={
                "has_data": True,
                "buy_depth_xch": 0.12,
                "sell_depth_xch": 0.10,
                "competitor_spread_bps": 1200,
            },
            arb_gap_bps=20,
            fee_coin_size_xch=0.001,
        )
        liquid_market_size = _smart_sniper_size_xch(
            avail_xch=80,
            fills_per_day=14,
            daily_volume_xch=8,
            orderbook={
                "has_data": True,
                "buy_depth_xch": 80,
                "sell_depth_xch": 100,
                "competitor_spread_bps": 250,
            },
            arb_gap_bps=300,
            fee_coin_size_xch=0.001,
        )

        self.assertEqual(thin_market_size, 0.01)
        self.assertGreater(liquid_market_size, thin_market_size * 10)
        self.assertGreaterEqual(liquid_market_size, 0.2)

    def test_sniper_size_keeps_fee_coins_smaller(self):
        from blueprints.smart_defaults import _smart_sniper_size_xch

        sniper_size = _smart_sniper_size_xch(
            avail_xch=50,
            fills_per_day=6,
            daily_volume_xch=3,
            orderbook={
                "has_data": True,
                "buy_depth_xch": 25,
                "sell_depth_xch": 30,
                "competitor_spread_bps": 500,
            },
            arb_gap_bps=100,
            fee_coin_size_xch=0.02,
        )

        self.assertGreater(sniper_size, 0.02)
        self.assertGreaterEqual(sniper_size, 0.04)

    def test_liquid_market_sniper_plan_uses_the_allocated_pool(self):
        from blueprints.smart_defaults import (
            _smart_sniper_prep_plan,
            _smart_sniper_size_xch,
        )

        sniper_size = _smart_sniper_size_xch(
            avail_xch=80,
            fills_per_day=14,
            daily_volume_xch=8,
            orderbook={
                "has_data": True,
                "buy_depth_xch": 80,
                "sell_depth_xch": 100,
                "competitor_spread_bps": 250,
            },
            arb_gap_bps=300,
            fee_coin_size_xch=0.001,
        )
        sniper_plan = _smart_sniper_prep_plan(
            80, fills_per_day=14, sniper_size_xch=sniper_size
        )

        self.assertGreaterEqual(
            sniper_plan["pool_xch"], sniper_plan["target_xch"] * 0.75
        )


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestSmartDefaultsBalanceSizingRegression(_FlaskBase):
    @staticmethod
    def _cat_coin_prep_total(body):
        mid_price = float(body["smart_mid_price"])
        headroom = 1 + (float(body.get("coin_prep_headroom_pct", 0)) / 100)
        total = 0
        for tier in ("inner", "mid", "outer", "extreme"):
            size = float(body.get(f"sell_{tier}_size_xch") or 0)
            count = int(body.get(f"sell_{tier}_tier_count") or 0)
            spares = int(body.get(f"sell_{tier}_tier_spare_count") or 0)
            if size > 0 and count + spares > 0:
                total += (count + spares) * round((size / mid_price) * headroom)

        if body.get("sniper_enabled"):
            sniper_size = float(body.get("sniper_size_xch") or 0)
            sniper_count = int(body.get("sniper_prep_count") or 0)
            if sniper_size > 0 and sniper_count > 0:
                total += sniper_count * round((sniper_size / mid_price) * headroom)

        total += round(float(body.get("topup_pool_cat") or 0))
        return total

    def test_large_xch_sniper_pool_does_not_overrun_cat_coin_prep_budget(self):
        from blueprints import smart_defaults

        available_cat = 50_727.149

        def fake_balance(wallet_id):
            if wallet_id == 1:
                mojos = int(70.8513 * 1_000_000_000_000)
            else:
                mojos = int(available_cat * 1_000)
            return {
                "success": True,
                "wallet_balance": {
                    "unconfirmed_wallet_balance": mojos,
                    "confirmed_wallet_balance": mojos,
                    "spendable_balance": mojos,
                    "pending_coin_removal_count": 0,
                },
            }

        raw_market = {
            "dexie_ticker": {
                "price": 0.00010947,
                "volume_30d": 10.4683,
                "high_30d": 0.00020141,
                "low_30d": 0.00010435,
            },
            "dexie_trades": {
                "total_count": 200,
                "volume_trend": "stable",
                "trades": [
                    {"price": 0.00011793, "xch_amount": 1.0},
                    {"price": 0.00011793, "xch_amount": 1.0},
                    {"price": 0.00011793, "xch_amount": 1.0},
                ],
            },
            "tibet_pool": {
                "has_data": True,
                "price": 0.00010843,
                "xch_reserve": 114,
            },
            "tibet_quote": {},
            "spacescan": {"has_data": True, "price_xch": 0.00010843},
            "internal_db": {"price_count": 0, "fill_count": 0, "pool_trend": "stable"},
        }
        analysis = {
            "volatility": {
                "regime": "volatile",
                "range_30d_pct": 63.49,
                "range_90d_pct": 199.98,
                "max_single_move_pct": 14.59,
                "confidence": "high",
                "std_dev_pct": 7.04,
                "quiet_phase": True,
            },
            "liquidity": {
                "fills_per_day": 6.67,
                "daily_volume_xch": 10.4683,
                "pool_depth_xch": 115.2,
                "level": "moderate",
                "volume_trend": "stable",
            },
            "token_health": {
                "risk_level": "risky",
                "activity_level": "dormant",
                "holder_count": 0,
            },
            "bot_performance": {"has_history": False},
            "data_quality": {
                "score": 100,
                "quality": "excellent (partial: spacescan_activity)",
            },
        }
        orderbook = {
            "has_data": True,
            "api_ok": True,
            "num_buy_offers": 1,
            "num_sell_offers": 1,
            "competitor_spread_bps": 100,
            "best_bid": 0.0001089,
            "best_ask": 0.0001100,
        }

        with (
            patch("wallet.get_wallet_balance", side_effect=fake_balance),
            patch(
                "market_data_collector.collect_all_market_data",
                return_value=raw_market,
            ),
            patch("market_data_collector.analyze_market_data", return_value=analysis),
            patch.object(
                smart_defaults,
                "_fetch_dexie_orderbook_standalone",
                return_value=orderbook,
            ),
            patch.object(
                smart_defaults,
                "_smart_market_own_offer_identities",
                return_value=frozenset(),
            ),
            patch.object(
                smart_defaults,
                "_derive_smart_market_confidence",
                return_value=_green_market_confidence("0.0001089", "0.0001100"),
            ),
            patch.object(
                smart_defaults,
                "_smart_dbx_defaults",
                return_value={
                    "dbx_max_spread_bps": 500,
                    "pair_incentivized": False,
                    "dbx_buy_incentive": None,
                    "dbx_sell_incentive": None,
                },
            ),
            patch(
                "tx_fees.get_suggested_transaction_fee",
                return_value={"available": False},
            ),
        ):
            with api_server.app.test_request_context("/api/smart-defaults"):
                resp = smart_defaults._calculate_smart_defaults(
                    xch_reserve=0,
                    cat_reserve=0,
                    risk_profile="balanced",
                    asset_id="a" * 64,
                    cat_wallet_id=2,
                    cat_decimals=3,
                    cat_ticker_id="MZ_XCH",
                    cat_name="Monkeyzoo Token",
                )

        body = resp.get_json()
        self.assertLessEqual(self._cat_coin_prep_total(body), available_cat)

    def test_smart_defaults_reuses_verified_cat_balance_on_transient_zero(self):
        from blueprints import smart_defaults

        asset_id = "e" * 64
        cached_cat = 6_500_000.0
        original_cat = dict(api_server._active_cat)
        api_server.clear_balance_snapshot()
        api_server._active_cat.update(
            {
                "asset_id": asset_id,
                "wallet_id": 2,
                "ticker_id": "TST_XCH",
                "decimals": 3,
                "name": "TestCAT",
            }
        )
        api_server.cache_balance_snapshot(
            asset_id=asset_id,
            cat_wallet_id=2,
            balances={
                "xch": {"total": 5.0, "spendable": 4.5},
                "cat": {"total": cached_cat, "spendable": cached_cat - 1000},
            },
            source="test",
        )

        def fake_balance(wallet_id):
            mojos = 5_000_000_000_000 if wallet_id == 1 else 0
            return {
                "success": True,
                "wallet_balance": {
                    "unconfirmed_wallet_balance": mojos,
                    "confirmed_wallet_balance": mojos,
                    "spendable_balance": mojos,
                    "pending_coin_removal_count": 0,
                },
            }

        raw_market = {
            "dexie_ticker": {
                "price": 0.0001,
                "volume_30d": 10,
                "high_30d": 0.00012,
                "low_30d": 0.00009,
            },
            "dexie_trades": {
                "total_count": 100,
                "volume_trend": "stable",
                "trades": [{"price": 0.0001, "xch_amount": 1.0}],
            },
            "tibet_pool": {"has_data": True, "price": 0.0001, "xch_reserve": 200},
            "tibet_quote": {},
            "spacescan": {"has_data": True, "price_xch": 0.0001},
            "internal_db": {"price_count": 0, "fill_count": 0, "pool_trend": "stable"},
        }
        analysis = {
            "volatility": {
                "regime": "normal",
                "range_30d_pct": 10,
                "range_90d_pct": 20,
                "max_single_move_pct": 3,
                "confidence": "high",
                "std_dev_pct": 1,
                "quiet_phase": False,
            },
            "liquidity": {
                "fills_per_day": 5,
                "daily_volume_xch": 10,
                "pool_depth_xch": 200,
                "level": "deep",
                "volume_trend": "stable",
            },
            "token_health": {
                "risk_level": "healthy",
                "activity_level": "active",
                "holder_count": 1000,
            },
            "bot_performance": {"has_history": False},
            "data_quality": {"score": 100, "quality": "excellent"},
        }
        orderbook = {
            "has_data": True,
            "api_ok": True,
            "num_buy_offers": 10,
            "num_sell_offers": 10,
            "competitor_spread_bps": 500,
            "best_bid": 0.00009,
            "best_ask": 0.00011,
        }

        try:
            with (
                patch("wallet.get_wallet_balance", side_effect=fake_balance),
                patch(
                    "market_data_collector.collect_all_market_data",
                    return_value=raw_market,
                ),
                patch(
                    "market_data_collector.analyze_market_data", return_value=analysis
                ),
                patch.object(
                    smart_defaults,
                    "_fetch_dexie_orderbook_standalone",
                    return_value=orderbook,
                ),
                patch.object(
                    smart_defaults,
                    "_smart_market_own_offer_identities",
                    return_value=frozenset(),
                ),
                patch.object(
                    smart_defaults,
                    "_derive_smart_market_confidence",
                    return_value=_green_market_confidence("0.00009", "0.00011"),
                ),
                patch.object(
                    smart_defaults,
                    "_smart_dbx_defaults",
                    return_value={
                        "dbx_max_spread_bps": 500,
                        "pair_incentivized": False,
                        "dbx_buy_incentive": None,
                        "dbx_sell_incentive": None,
                    },
                ),
                patch(
                    "tx_fees.get_suggested_transaction_fee",
                    return_value={"available": False},
                ),
            ):
                with api_server.app.test_request_context("/api/smart-defaults"):
                    resp = smart_defaults._calculate_smart_defaults(
                        xch_reserve=0,
                        cat_reserve=0,
                        risk_profile="balanced",
                        asset_id=asset_id,
                        cat_wallet_id=2,
                        cat_decimals=3,
                        cat_ticker_id="TST_XCH",
                        cat_name="TestCAT",
                    )
        finally:
            api_server.clear_balance_snapshot()
            api_server._active_cat.clear()
            api_server._active_cat.update(original_cat)

        body = resp.get_json()
        self.assertEqual(body["_capital_plan"]["available_cat"], cached_cat)
        self.assertGreater(body["max_active_sell"], 0)

    def test_large_xch_balance_is_not_stranded_in_topup_when_cat_is_smaller(self):
        from blueprints import smart_defaults

        def fake_balance(wallet_id):
            if wallet_id == 1:
                mojos = int(70.8517 * 1_000_000_000_000)
            else:
                mojos = 50_433_477
            return {
                "success": True,
                "wallet_balance": {
                    "unconfirmed_wallet_balance": mojos,
                    "confirmed_wallet_balance": mojos,
                    "spendable_balance": mojos,
                    "pending_coin_removal_count": 0,
                },
            }

        raw_market = {
            "dexie_ticker": {
                "price": 0.00011083,
                "volume_30d": 60,
                "high_30d": 0.00013,
                "low_30d": 0.00009,
            },
            "dexie_trades": {
                "total_count": 200,
                "volume_trend": "flat",
                "trades": [
                    {"price": 0.00011083, "xch_amount": 1.0},
                    {"price": 0.00011083, "xch_amount": 1.0},
                    {"price": 0.00011083, "xch_amount": 1.0},
                ],
            },
            "tibet_pool": {
                "has_data": True,
                "price": 0.00011083,
                "xch_reserve": 100,
            },
            "tibet_quote": {},
            "spacescan": {"has_data": True, "price_xch": 0.00011083},
            "internal_db": {"price_count": 60, "fill_count": 0, "pool_trend": "stable"},
        }
        analysis = {
            "volatility": {
                "regime": "volatile",
                "range_30d_pct": 30,
                "range_90d_pct": 40,
                "max_single_move_pct": 10,
                "confidence": "high",
                "std_dev_pct": 4,
            },
            "liquidity": {
                "fills_per_day": 6.67,
                "daily_volume_xch": 2.0,
                "level": "moderate",
            },
            "token_health": {
                "risk_level": "healthy",
                "activity_level": "active",
                "holder_count": 100,
            },
            "bot_performance": {"has_history": False},
            "data_quality": {"score": 100, "quality": "excellent"},
        }
        orderbook = {
            "has_data": True,
            "api_ok": True,
            "num_buy_offers": 10,
            "num_sell_offers": 10,
            "competitor_spread_bps": 500,
            "best_bid": 0.00010,
            "best_ask": 0.00012,
        }

        with (
            patch("wallet.get_wallet_balance", side_effect=fake_balance),
            patch(
                "market_data_collector.collect_all_market_data",
                return_value=raw_market,
            ),
            patch("market_data_collector.analyze_market_data", return_value=analysis),
            patch.object(
                smart_defaults,
                "_fetch_dexie_orderbook_standalone",
                return_value=orderbook,
            ),
            patch.object(
                smart_defaults,
                "_smart_market_own_offer_identities",
                return_value=frozenset(),
            ),
            patch.object(
                smart_defaults,
                "_derive_smart_market_confidence",
                return_value=_green_market_confidence("0.00010", "0.00012"),
            ),
            patch.object(
                smart_defaults,
                "_smart_dbx_defaults",
                return_value={
                    "dbx_max_spread_bps": 500,
                    "pair_incentivized": False,
                    "dbx_buy_incentive": None,
                    "dbx_sell_incentive": None,
                },
            ),
            patch(
                "tx_fees.get_suggested_transaction_fee",
                return_value={"available": False},
            ),
        ):
            with api_server.app.test_request_context("/api/smart-defaults"):
                resp = smart_defaults._calculate_smart_defaults(
                    xch_reserve=17.713,
                    cat_reserve=0,
                    risk_profile="aggressive",
                    asset_id="a" * 64,
                    cat_wallet_id=2,
                    cat_decimals=3,
                    cat_ticker_id="MZ_XCH",
                    cat_name="Monkeyzoo Token",
                )

        body = resp.get_json()
        self.assertLess(body["topup_pool_xch"], 5)
        self.assertGreater(body["buy_mid_size_xch"], 0.5)
        self.assertGreater(body["_capital_plan"]["trading_xch"], 25)

    def test_large_wallet_defaults_return_trade_bounds_for_generated_sizes(self):
        from blueprints import smart_defaults

        def fake_balance(wallet_id):
            if wallet_id == 1:
                mojos = int(203.93589188879 * 1_000_000_000_000)
            else:
                mojos = int(3_810_952.337 * 1_000)
            return {
                "success": True,
                "wallet_balance": {
                    "unconfirmed_wallet_balance": mojos,
                    "confirmed_wallet_balance": mojos,
                    "spendable_balance": mojos,
                    "pending_coin_removal_count": 0,
                },
            }

        raw_market = {
            "dexie_ticker": {
                "price": 0.000081965,
                "volume_30d": 12,
                "high_30d": 0.00009,
                "low_30d": 0.000075,
            },
            "dexie_trades": {
                "total_count": 75,
                "volume_trend": "stable",
                "trades": [
                    {"price": 0.000081965, "xch_amount": 1.0},
                    {"price": 0.000081965, "xch_amount": 1.0},
                    {"price": 0.000081965, "xch_amount": 1.0},
                ],
            },
            "tibet_pool": {
                "has_data": True,
                "price": 0.000081965,
                "xch_reserve": 230,
            },
            "tibet_quote": {},
            "spacescan": {"has_data": True, "price_xch": 0.000081965},
            "internal_db": {"price_count": 60, "fill_count": 0, "pool_trend": "stable"},
        }
        analysis = {
            "volatility": {
                "regime": "quiet",
                "range_30d_pct": 12,
                "range_90d_pct": 20,
                "max_single_move_pct": 3,
                "confidence": "high",
                "std_dev_pct": 2,
            },
            "liquidity": {
                "fills_per_day": 2.5,
                "daily_volume_xch": 4.0,
                "level": "moderate",
            },
            "token_health": {
                "risk_level": "healthy",
                "activity_level": "active",
                "holder_count": 100,
            },
            "bot_performance": {"has_history": False},
            "data_quality": {"score": 100, "quality": "excellent"},
        }
        orderbook = {
            "has_data": True,
            "api_ok": True,
            "num_buy_offers": 10,
            "num_sell_offers": 10,
            "competitor_spread_bps": 600,
            "best_bid": 0.000079,
            "best_ask": 0.000085,
        }

        with (
            patch("wallet.get_wallet_balance", side_effect=fake_balance),
            patch(
                "market_data_collector.collect_all_market_data",
                return_value=raw_market,
            ),
            patch("market_data_collector.analyze_market_data", return_value=analysis),
            patch.object(
                smart_defaults,
                "_fetch_dexie_orderbook_standalone",
                return_value=orderbook,
            ),
            patch.object(
                smart_defaults,
                "_smart_market_own_offer_identities",
                return_value=frozenset(),
            ),
            patch.object(
                smart_defaults,
                "_derive_smart_market_confidence",
                return_value=_green_market_confidence("0.000079", "0.000085"),
            ),
            patch.object(
                smart_defaults,
                "_smart_dbx_defaults",
                return_value={
                    "dbx_max_spread_bps": 500,
                    "pair_incentivized": False,
                    "dbx_buy_incentive": None,
                    "dbx_sell_incentive": None,
                },
            ),
            patch(
                "tx_fees.get_suggested_transaction_fee",
                return_value={"available": False},
            ),
        ):
            with api_server.app.test_request_context("/api/smart-defaults"):
                resp = smart_defaults._calculate_smart_defaults(
                    xch_reserve=0,
                    cat_reserve=0,
                    risk_profile="balanced",
                    asset_id="a" * 64,
                    cat_wallet_id=2,
                    cat_decimals=3,
                    cat_ticker_id="MZ_XCH",
                    cat_name="Monkeyzoo Token",
                )

        body = resp.get_json()
        generated_sizes = [
            float(body.get(key) or 0)
            for key in (
                "default_trade_xch",
                "inner_size_xch",
                "mid_size_xch",
                "outer_size_xch",
                "extreme_size_xch",
                "buy_inner_size_xch",
                "buy_mid_size_xch",
                "buy_outer_size_xch",
                "buy_extreme_size_xch",
                "sell_inner_size_xch",
                "sell_mid_size_xch",
                "sell_outer_size_xch",
                "sell_extreme_size_xch",
            )
        ]
        self.assertGreater(float(body["min_trade_xch"]), 0)
        self.assertGreaterEqual(float(body["max_trade_xch"]), max(generated_sizes))

    def test_wallet_balance_unavailable_does_not_crash(self):
        from blueprints import smart_defaults

        raw_market = {
            "dexie_ticker": {
                "price": 0.000081965,
                "volume_30d": 12,
                "high_30d": 0.00009,
                "low_30d": 0.000075,
            },
            "dexie_trades": {
                "total_count": 75,
                "volume_trend": "stable",
                "trades": [
                    {"price": 0.000081965, "xch_amount": 1.0},
                    {"price": 0.000081965, "xch_amount": 1.0},
                    {"price": 0.000081965, "xch_amount": 1.0},
                ],
            },
            "tibet_pool": {
                "has_data": True,
                "price": 0.000081965,
                "xch_reserve": 100,
            },
            "tibet_quote": {},
            "spacescan": {"has_data": True, "price_xch": 0.000081965},
            "internal_db": {"price_count": 60, "fill_count": 0, "pool_trend": "stable"},
        }
        analysis = {
            "volatility": {
                "regime": "quiet",
                "range_30d_pct": 12,
                "range_90d_pct": 20,
                "max_single_move_pct": 3,
                "confidence": "high",
                "std_dev_pct": 2,
            },
            "liquidity": {
                "fills_per_day": 2.5,
                "daily_volume_xch": 4.0,
                "level": "moderate",
            },
            "token_health": {
                "risk_level": "healthy",
                "activity_level": "active",
                "holder_count": 100,
            },
            "bot_performance": {"has_history": False},
            "data_quality": {"score": 100, "quality": "excellent"},
        }

        with (
            patch(
                "wallet.get_wallet_balance",
                return_value={"success": False, "error": "rpc unavailable"},
            ),
            patch(
                "market_data_collector.collect_all_market_data",
                return_value=raw_market,
            ),
            patch("market_data_collector.analyze_market_data", return_value=analysis),
            patch.object(
                smart_defaults,
                "_fetch_dexie_orderbook_standalone",
                return_value={
                    "has_data": True,
                    "api_ok": True,
                    "num_buy_offers": 1,
                    "num_sell_offers": 1,
                    "competitor_spread_bps": 100,
                    "best_bid": 0.0000815,
                    "best_ask": 0.0000824,
                },
            ),
            patch.object(
                smart_defaults,
                "_smart_market_own_offer_identities",
                return_value=frozenset(),
            ),
            patch.object(
                smart_defaults,
                "_derive_smart_market_confidence",
                return_value=_green_market_confidence("0.0000815", "0.0000824"),
            ),
            patch.object(
                smart_defaults,
                "_smart_dbx_defaults",
                return_value={
                    "dbx_max_spread_bps": 500,
                    "pair_incentivized": False,
                    "dbx_buy_incentive": None,
                    "dbx_sell_incentive": None,
                },
            ),
            patch(
                "tx_fees.get_suggested_transaction_fee",
                return_value={"available": False},
            ),
        ):
            with api_server.app.test_request_context("/api/smart-defaults"):
                resp = smart_defaults._calculate_smart_defaults(
                    xch_reserve=0,
                    cat_reserve=0,
                    risk_profile="balanced",
                    asset_id="a" * 64,
                    cat_wallet_id=2,
                    cat_decimals=3,
                    cat_ticker_id="MZ_XCH",
                    cat_name="Monkeyzoo Token",
                )

        body = resp.get_json()
        self.assertIsNone(body["default_trade_xch"])
        self.assertIsNone(body["max_trade_xch"])
        self.assertFalse(body["_data_sources"]["has_wallet_balance"])
        self.assertEqual(body["_capital_plan"]["available_xch"], 0)


if __name__ == "__main__":
    unittest.main()
