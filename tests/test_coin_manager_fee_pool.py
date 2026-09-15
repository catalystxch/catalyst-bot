import importlib
import contextlib
import os
import sys
import types
import unittest
from decimal import Decimal


_MODS_TO_RESTORE = (
    "coin_manager",
    "tx_fees",
    "wallet",
    "wallet_sage",
    "database",
    "config",
)


class CoinManagerFeePoolTests(unittest.TestCase):
    def setUp(self):
        self._saved_wallet_type = os.environ.get("WALLET_TYPE")
        os.environ["WALLET_TYPE"] = "chia"
        self._saved_modules = {name: sys.modules.get(name) for name in _MODS_TO_RESTORE}

        _TIER_SIZES = {
            "inner": Decimal("1.0"),
            "mid": Decimal("0.5"),
            "outer": Decimal("0.25"),
            "extreme": Decimal("0.1"),
        }

        fake_config = types.ModuleType("config")
        fake_config.cfg = types.SimpleNamespace(
            COINSET_ENABLED=False,
            WALLET_ID_XCH=1,
            CAT_WALLET_ID=2,
            TIER_ENABLED=True,
            ENABLE_COIN_PREP=True,
            CAT_DECIMALS=3,
            INNER_SIZE_XCH=Decimal("1.0"),
            MID_SIZE_XCH=Decimal("0.5"),
            OUTER_SIZE_XCH=Decimal("0.25"),
            EXTREME_SIZE_XCH=Decimal("0.1"),
            # Per-side sizes (required by coin_manager._configured_tier_sizes_xch)
            BUY_INNER_SIZE_XCH=Decimal("1.0"),
            BUY_MID_SIZE_XCH=Decimal("0.5"),
            BUY_OUTER_SIZE_XCH=Decimal("0.25"),
            BUY_EXTREME_SIZE_XCH=Decimal("0.1"),
            SELL_INNER_SIZE_XCH=Decimal("1.0"),
            SELL_MID_SIZE_XCH=Decimal("0.5"),
            SELL_OUTER_SIZE_XCH=Decimal("0.25"),
            SELL_EXTREME_SIZE_XCH=Decimal("0.1"),
            BUY_LADDER_REVERSED=False,
            SNIPER_ENABLED=False,
            SNIPER_SIZE_XCH=Decimal("0"),
            SNIPER_PREP_COUNT=0,
            COIN_PREP_HEADROOM_PCT=Decimal("10"),
            CAT_COIN_SIZE=Decimal("4000"),
            MAX_ACTIVE_BUY_OFFERS=0,
            MAX_ACTIVE_SELL_OFFERS=0,
            ENABLE_BUY=False,
            ENABLE_SELL=False,
            COIN_PREP_MULTIPLIER=Decimal("1.0"),
            TRANSACTION_FEE_MODE="manual",
            TRANSACTION_FEE_XCH=Decimal("0.00000050"),
            TRANSACTION_FEE_TARGET_SECS=300,
            TRANSACTION_FEE_ESTIMATE_COST=20_000_000,
            FEE_PREP_COUNT=20,
            FEE_COIN_SIZE_XCH=Decimal("0.0001"),
        )
        # Module-level helpers imported directly by coin_manager (not via cfg)
        fake_config.get_buy_tier_size_xch = lambda tier: _TIER_SIZES.get(
            (tier or "").strip().lower(), Decimal("0")
        )
        fake_config.get_sell_tier_size_xch = lambda tier: _TIER_SIZES.get(
            (tier or "").strip().lower(), Decimal("0")
        )
        sys.modules["config"] = fake_config

        fake_database = types.ModuleType("database")
        fake_database.log_event = lambda *args, **kwargs: None
        fake_database.get_free_coins = lambda *args, **kwargs: []
        fake_database.get_locked_coins = lambda *args, **kwargs: []
        fake_database.authorize_wallet_effect_coin_ids = lambda coin_ids: tuple(
            coin_ids
        )
        fake_database.claim_wallet_effect = lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("fee classification must not claim a wallet effect"))
        fake_database.resolve_wallet_effect_claim = lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("fee classification must not resolve a wallet effect"))
        fake_database.begin_wallet_effect_dispatch = lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("fee classification must not dispatch a wallet effect"))
        fake_database.complete_wallet_effect_dispatch = lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("fee classification must not complete a wallet effect"))
        fake_database.retain_wallet_effect_claim_for_reconciliation = (
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("fee classification must not retain a wallet effect")
            )
        )
        fake_database.wallet_effect_adapter_dispatch_authority = contextlib.nullcontext
        fake_database.wallet_effect_claim_is_current = lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(AssertionError("fee classification must not inspect an effect claim"))
        sys.modules["database"] = fake_database

        fake_wallet = types.ModuleType("wallet")
        fake_wallet.get_exact_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "records": [],
        }
        fake_wallet.get_all_coins_for_wallet = lambda *args, **kwargs: []
        fake_wallet.get_wallet_balance = lambda *args, **kwargs: {
            "wallet_balance": {"spendable_balance": 0}
        }
        fake_wallet.get_next_address = lambda *args, **kwargs: {
            "success": True,
            "address": "xch1test",
        }
        fake_wallet.send_transaction = lambda *args, **kwargs: {"success": True}
        fake_wallet.split_coins_rpc = lambda *args, **kwargs: {"success": True}
        fake_wallet.get_wallet_type = lambda: "chia"
        fake_wallet.WALLET_ID_XCH = 1
        fake_wallet.get_owned_coins = lambda *args, **kwargs: {}
        fake_wallet.get_owned_coins_detailed = lambda *a, **kw: None
        fake_wallet.rpc = lambda *args, **kwargs: {"fingerprint": "123"}
        sys.modules["wallet"] = fake_wallet

        sys.modules.pop("tx_fees", None)
        sys.modules.pop("coin_manager", None)
        self.coin_manager = importlib.import_module("coin_manager")
        self.manager = self.coin_manager.CoinManager()

    def tearDown(self):
        for name, saved in self._saved_modules.items():
            sys.modules.pop(name, None)
            if saved is not None:
                sys.modules[name] = saved

        if self._saved_wallet_type is None:
            os.environ.pop("WALLET_TYPE", None)
        else:
            os.environ["WALLET_TYPE"] = self._saved_wallet_type

    def test_fee_tier_is_xch_only(self):
        xch_sizes = self.manager._get_tier_sizes_mojos(is_cat=False)
        cat_sizes = self.manager._get_tier_sizes_mojos(is_cat=True)

        self.assertIn("fees", xch_sizes)
        self.assertEqual(xch_sizes["fees"], 100_000_000)
        self.assertNotIn("fees", cat_sizes)

    def test_inventory_counts_only_authoritative_fee_reserve_coins(self):
        """Legacy size matches must not be reported as dedicated fee coins.

        A live TEST 7 wallet contained 221 records in the ``fees`` size bucket,
        but only 50 were outputs from Coin Prep carrying the durable
        ``fee_reserve`` purpose.  Reporting all 221 made the dashboard and logs
        claim that ordinary legacy XCH coins were dedicated fee inventory.
        """
        authoritative = {
            "coin_id": "0x" + "aa" * 32,
            "coin": {"amount": 100_000_000},
            "_catalyst_policy_purpose": "fee_reserve",
        }
        legacy_size_match = {
            "coin_id": "0x" + "bb" * 32,
            "coin": {"amount": 100_000_000},
            "_catalyst_policy_purpose": None,
        }
        replacement_size_match = {
            "coin_id": "0x" + "cc" * 32,
            "coin": {"amount": 100_000_000},
            "_catalyst_policy_purpose": "replacement",
        }
        empty = {
            "reserve": [],
            "inner": [],
            "mid": [],
            "outer": [],
            "extreme": [],
            "sniper": [],
            "fees": [],
            "small": [],
        }
        self.manager._xch_inventory = {
            **empty,
            "fees": [authoritative, legacy_size_match, replacement_size_match],
        }
        self.manager._cat_inventory = dict(empty)
        self.manager._xch_locked_coins = 0
        self.manager._xch_locked_amount = 0
        self.manager._cat_locked_coins = 0
        self.manager._cat_locked_amount = 0
        self.manager._xch_total_coins = 3
        self.manager._cat_total_coins = 0

        summary = self.manager.get_inventory_summary()

        self.assertEqual(summary["xch_fees"], 1)

    def test_readiness_counts_only_authoritative_fee_reserve_coins(self):
        authoritative = {
            "coin_id": "0x" + "aa" * 32,
            "coin": {"amount": 100_000_000},
            "_catalyst_policy_purpose": "fee_reserve",
        }
        legacy_size_match = {
            "coin_id": "0x" + "bb" * 32,
            "coin": {"amount": 100_000_000},
            "_catalyst_policy_purpose": None,
        }
        replacement_size_match = {
            "coin_id": "0x" + "cc" * 32,
            "coin": {"amount": 100_000_000},
            "_catalyst_policy_purpose": "replacement",
        }
        self.manager._xch_inventory["fees"] = [
            authoritative,
            legacy_size_match,
            replacement_size_match,
        ]

        report = self.manager.coin_readiness_report()

        self.assertEqual(report["tiers"]["fees"]["xch_available"], 1)

    def test_quick_fee_pool_refresh_rejects_unpurposed_size_matches(self):
        authoritative_id = "0x" + "aa" * 32
        legacy_id = "0x" + "bb" * 32
        records = [
            {"coin_id": authoritative_id, "coin": {"amount": 100_000_000}},
            {"coin_id": legacy_id, "coin": {"amount": 100_000_000}},
        ]
        database = sys.modules["database"]
        database.get_free_coins = lambda wallet_type: [
            {
                "coin_id": authoritative_id,
                "assigned_tier": "fees",
                "purpose": "fee_reserve",
            },
            {
                "coin_id": legacy_id,
                "assigned_tier": "fees",
                "purpose": None,
            },
        ]
        self.coin_manager.get_exact_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "records": records,
        }

        self.manager.refresh_fee_pool_from_wallet()

        self.assertEqual(self.manager.fee_pool.available_count, 1)
        self.assertEqual(self.manager.fee_pool.reserve(), authoritative_id)
        self.assertIsNone(self.manager.fee_pool.reserve())


if __name__ == "__main__":
    unittest.main()
