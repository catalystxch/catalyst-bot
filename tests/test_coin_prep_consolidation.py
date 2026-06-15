import importlib
import os
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import patch
from pathlib import Path


_MODS_TO_RESTORE = ("coin_prep_worker", "wallet_sage", "database", "wallet", "dotenv")


class CoinPrepConsolidationTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = {
            "WALLET_TYPE": os.environ.get("WALLET_TYPE"),
            "WALLET_FINGERPRINT": os.environ.get("WALLET_FINGERPRINT"),
            "DEFAULT_TRADE_XCH": os.environ.get("DEFAULT_TRADE_XCH"),
            "CAT_COIN_SIZE": os.environ.get("CAT_COIN_SIZE"),
            "CHIA_WALLET_ID_XCH": os.environ.get("CHIA_WALLET_ID_XCH"),
            "CAT_WALLET_ID": os.environ.get("CAT_WALLET_ID"),
            "MAX_ACTIVE_BUY_OFFERS": os.environ.get("MAX_ACTIVE_BUY_OFFERS"),
            "MAX_ACTIVE_BUY": os.environ.get("MAX_ACTIVE_BUY"),
            "MAX_ACTIVE_SELL_OFFERS": os.environ.get("MAX_ACTIVE_SELL_OFFERS"),
            "MAX_ACTIVE_SELL": os.environ.get("MAX_ACTIVE_SELL"),
            "CAT_DECIMALS": os.environ.get("CAT_DECIMALS"),
            "MZ_DECIMALS": os.environ.get("MZ_DECIMALS"),
            "CAT_ASSET_ID": os.environ.get("CAT_ASSET_ID"),
        }
        self._saved_modules = {name: sys.modules.get(name) for name in _MODS_TO_RESTORE}

        os.environ["WALLET_TYPE"] = "sage"
        os.environ["WALLET_FINGERPRINT"] = "123"
        os.environ["DEFAULT_TRADE_XCH"] = ""
        os.environ["CAT_COIN_SIZE"] = "4000"
        os.environ["CHIA_WALLET_ID_XCH"] = ""
        os.environ["CAT_WALLET_ID"] = ""
        os.environ["MAX_ACTIVE_BUY_OFFERS"] = ""
        os.environ["MAX_ACTIVE_BUY"] = ""
        os.environ["MAX_ACTIVE_SELL_OFFERS"] = ""
        os.environ["MAX_ACTIVE_SELL"] = ""
        os.environ["CAT_DECIMALS"] = ""
        os.environ["MZ_DECIMALS"] = ""

        fake_wallet = types.ModuleType("wallet")
        fake_wallet.get_all_offers = lambda *args, **kwargs: {"offers": []}
        fake_wallet.cancel_offer = lambda *args, **kwargs: {"success": True}
        fake_wallet.cancel_offers_batch = lambda *args, **kwargs: {"success": True}
        fake_wallet.get_wallet_sync_status = lambda *args, **kwargs: {"synced": True}
        fake_wallet.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "records": [],
        }
        fake_wallet.split_coins_rpc = lambda *args, **kwargs: {"success": True}
        fake_wallet.get_transaction = lambda *args, **kwargs: {"success": True}
        sys.modules["wallet"] = fake_wallet

        fake_database = types.ModuleType("database")
        fake_database.init_database = lambda: None
        fake_database.upsert_coin = lambda *args, **kwargs: True
        fake_database.set_coin_designation = lambda *args, **kwargs: True
        fake_database.designate_reserve = lambda *args, **kwargs: True
        fake_database.get_reserve_coins = lambda *args, **kwargs: []
        fake_database.mark_coins_gone = lambda *args, **kwargs: True
        sys.modules["database"] = fake_database

        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.dotenv_values = lambda *args, **kwargs: {}
        fake_dotenv.load_dotenv = lambda *args, **kwargs: True
        fake_dotenv.set_key = lambda *args, **kwargs: True
        sys.modules["dotenv"] = fake_dotenv

        sys.modules.pop("coin_prep_worker", None)
        self.coin_prep_worker = importlib.import_module("coin_prep_worker")

    def tearDown(self):
        for name, saved in self._saved_modules.items():
            sys.modules.pop(name, None)
            if saved is not None:
                sys.modules[name] = saved

        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_sage_consolidation_uses_send_to_self_and_subtracts_xch_fee(self):
        calls = {"send": []}
        counts = iter([3, 0, 1])

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_spendable_coin_count = lambda wallet_id: 3
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }
        fake_wallet_sage.get_wallet_balance = lambda wallet_id: {
            "success": True,
            "wallet_balance": {"spendable_balance": 1000},
        }
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": [
                {"coin_id": "0x" + "11" * 32, "spent_block_index": 0, "amount": 400},
                {
                    "coin_id": "0x" + "22" * 32,
                    "spent_block_index": 0,
                    "coin": {"amount": 600},
                },
            ],
        }

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            calls["send"].append(
                {
                    "wallet_id": wallet_id,
                    "amount_mojos": amount_mojos,
                    "address": address,
                    "fee_mojos": fee_mojos,
                    "source_coin_ids": source_coin_ids,
                }
            )
            return {"success": True, "submitted": True}

        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.get_coin_count = lambda wallet_id: next(counts, 1)
        worker._tx_fee_mojos = lambda: 10

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertTrue(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(
            calls["send"],
            [
                {
                    "wallet_id": 1,
                    "amount_mojos": 990,
                    "address": "xch1self",
                    "fee_mojos": 10,
                    "source_coin_ids": ["11" * 32, "22" * 32],
                }
            ],
        )

    def test_sage_cat_consolidation_sends_full_cat_balance_to_self(self):
        calls = {"send": []}
        counts = iter([2, 0, 1])

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_spendable_coin_count = lambda wallet_id: 2
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }
        fake_wallet_sage.get_wallet_balance = lambda wallet_id: {
            "success": True,
            "wallet_balance": {"spendable_balance": 1000},
        }

        def get_spendable_coins_rpc(wallet_id):
            if wallet_id == 1:
                return {
                    "success": True,
                    "confirmed_records": [
                        {
                            "coin_id": "0x" + "aa" * 32,
                            "spent_block_index": 0,
                            "amount": 25,
                        },
                        {
                            "coin_id": "0x" + "bb" * 32,
                            "spent_block_index": 0,
                            "amount": 100,
                        },
                    ],
                }
            return {
                "success": True,
                "confirmed_records": [
                    {
                        "coin_id": "0x" + "11" * 32,
                        "spent_block_index": 0,
                        "amount": 400,
                    },
                    {
                        "coin_id": "0x" + "22" * 32,
                        "spent_block_index": 0,
                        "coin": {"amount": 600},
                    },
                ],
            }

        fake_wallet_sage.get_spendable_coins_rpc = get_spendable_coins_rpc

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            calls["send"].append(
                {
                    "wallet_id": wallet_id,
                    "amount_mojos": amount_mojos,
                    "address": address,
                    "fee_mojos": fee_mojos,
                    "source_coin_ids": source_coin_ids,
                }
            )
            return {"success": True, "submitted": True}

        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage
        os.environ["CAT_ASSET_ID"] = "abc123"

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.cat_wallet_id = 2
        worker.get_coin_count = lambda wallet_id: next(counts, 1)
        worker._tx_fee_mojos = lambda: 10

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertTrue(worker._consolidate_wallet_sage(2, "CAT"))

        self.assertEqual(
            calls["send"],
            [
                {
                    "wallet_id": 2,
                    "amount_mojos": 1000,
                    "address": "xch1self",
                    "fee_mojos": 10,
                    "source_coin_ids": ["11" * 32, "22" * 32],
                }
            ],
        )

    def test_sage_large_xch_consolidation_uses_priority_fee(self):
        calls = {"send": []}
        counts = iter([20, 0, 1])

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_spendable_coin_count = lambda wallet_id: 20
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": [
                {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
                for i in range(1, 21)
            ],
        }

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            calls["send"].append(
                {
                    "wallet_id": wallet_id,
                    "amount_mojos": amount_mojos,
                    "address": address,
                    "fee_mojos": fee_mojos,
                    "source_coin_ids": source_coin_ids,
                }
            )
            return {"success": True, "submitted": True}

        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.get_coin_count = lambda wallet_id: next(counts, 1)
        worker._tx_fee_mojos = lambda: 10

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertTrue(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(calls["send"][0]["amount_mojos"], 1980)
        self.assertEqual(calls["send"][0]["fee_mojos"], 20)

    def test_sage_large_xch_consolidation_uses_one_balance_self_send(self):
        records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(1, 46)
        ]
        calls = []
        counts = iter([45, 0, 1])

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": list(records),
        }

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            calls.append(
                {
                    "wallet_id": wallet_id,
                    "amount_mojos": amount_mojos,
                    "address": address,
                    "fee_mojos": fee_mojos,
                    "source_coin_ids": list(source_coin_ids or []),
                }
            )
            return {"success": True, "submitted": True}

        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.get_coin_count = lambda wallet_id: next(counts, 1)
        worker._tx_fee_mojos = lambda: 10

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertTrue(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["amount_mojos"], 4500 - 20)
        self.assertEqual(calls[0]["fee_mojos"], 20)
        self.assertEqual(len(calls[0]["source_coin_ids"]), 45)

    def test_sage_large_xch_consolidation_waits_between_self_send_batches(self):
        initial_records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(1, 61)
        ]
        after_first_batch_records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(101, 112)
        ]
        calls = []
        waits = []
        state = {"first_batch_confirmed": False}

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }

        def get_spendable_coins_rpc(wallet_id):
            return {
                "success": True,
                "confirmed_records": list(
                    after_first_batch_records
                    if state["first_batch_confirmed"]
                    else initial_records
                ),
            }

        fake_wallet_sage.get_spendable_coins_rpc = get_spendable_coins_rpc

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            if len(calls) >= 1 and not state["first_batch_confirmed"]:
                return {"success": False, "error": "second batch before wait"}
            calls.append(
                {
                    "wallet_id": wallet_id,
                    "amount_mojos": amount_mojos,
                    "address": address,
                    "fee_mojos": fee_mojos,
                    "source_coin_ids": list(source_coin_ids or []),
                }
            )
            return {"success": True, "submitted": True}

        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.xch_wallet_id = 1
        worker.get_coin_count = lambda wallet_id: 60
        worker._tx_fee_mojos = lambda: 10
        worker._sage_consolidation_max_inputs_per_tx = lambda: 50

        def wait_for_stage(
            wallet_id, name, before_count, target_count, *args, **kwargs
        ):
            waits.append((wallet_id, name, before_count, target_count))
            state["first_batch_confirmed"] = True
            return True

        worker._wait_for_sage_coin_count_at_most = wait_for_stage
        worker._wait_for_sage_consolidation = lambda *args, **kwargs: True

        self.assertTrue(worker._consolidate_wallet_sage_fallback(1, "XCH"))

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[0]["source_coin_ids"]), 50)
        self.assertEqual(len(calls[1]["source_coin_ids"]), 11)
        self.assertEqual(waits, [(1, "XCH", 60, 11)])

    def test_sage_large_cat_consolidation_batches_self_send_inputs(self):
        records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(1, 200)
        ]
        calls = []

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": list(records),
        }

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            calls.append(
                {
                    "wallet_id": wallet_id,
                    "amount_mojos": amount_mojos,
                    "address": address,
                    "fee_mojos": fee_mojos,
                    "source_coin_ids": list(source_coin_ids or []),
                }
            )
            return {"success": True, "submitted": True}

        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.cat_wallet_id = 2
        counts = iter([199, 1])
        worker.get_coin_count = lambda wallet_id: next(counts, 1)
        worker._tx_fee_mojos = lambda: 0
        worker._wait_for_sage_consolidation = lambda *args, **kwargs: True
        worker._wait_for_sage_coin_count_at_most = lambda *args, **kwargs: True

        self.assertTrue(worker._consolidate_wallet_sage(2, "CAT"))

        self.assertEqual(len(calls), 4)
        self.assertTrue(all(len(call["source_coin_ids"]) <= 50 for call in calls))
        self.assertEqual(sum(len(call["source_coin_ids"]) for call in calls), 199)

    def test_sage_large_combine_batches_coin_ids(self):
        records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(1, 200)
        ]
        calls = []

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": list(records),
        }

        def combine_coins(coin_ids, fee_mojos=0):
            calls.append(list(coin_ids))
            return {"success": True, "submitted": True}

        fake_wallet_sage.combine_coins = combine_coins
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker._consolidate_wallet_sage_fallback = lambda wallet_id, name: False
        worker._tx_fee_mojos = lambda: 0

        self.assertTrue(worker._consolidate_wallet_sage_combine(2, "CAT"))

        self.assertEqual(len(calls), 4)
        self.assertTrue(all(len(batch) <= 50 for batch in calls))
        self.assertEqual(sum(len(batch) for batch in calls), 199)

    def test_sage_consolidation_rejects_transient_pending_lock_that_restores_old_count(
        self,
    ):
        calls = []
        counts = iter([3, 0, 3, 3, 3])

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": [
                {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
                for i in range(1, 4)
            ],
        }

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            calls.append(source_coin_ids)
            return {"success": True, "submitted": True}

        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.get_coin_count = lambda wallet_id: next(counts, 3)
        worker._tx_fee_mojos = lambda: 0

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertFalse(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(len(calls), 1)

    def test_sage_consolidation_recovers_by_resync_when_wallet_view_is_stale(self):
        calls = {"send": 0, "resync": 0}
        counts = iter([3, 0, 3, 3, 3, 3, 3, 3, 1])

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": [
                {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
                for i in range(1, 4)
            ],
        }

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            calls["send"] += 1
            return {"success": True, "submitted": True}

        def sage_login(fingerprint, force_resync=False):
            calls["resync"] += 1
            self.assertEqual(fingerprint, 123)
            self.assertTrue(force_resync)
            return True

        fake_wallet_sage.send_transaction = send_transaction
        fake_wallet_sage.sage_login = sage_login
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.get_coin_count = lambda wallet_id: next(counts, 1)
        worker._tx_fee_mojos = lambda: 0

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertTrue(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(calls, {"send": 1, "resync": 1})

    def test_sage_consolidation_reports_wallet_still_settling_when_resync_count_changes(
        self,
    ):
        logs = []
        counts = iter([73, 0, 73, 73, 73, 73, 73, 73, 94, 94, 94])

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": [
                {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
                for i in range(1, 74)
            ],
        }
        fake_wallet_sage.send_transaction = lambda *args, **kwargs: {
            "success": True,
            "submitted": True,
        }
        fake_wallet_sage.sage_login = lambda fingerprint, force_resync=False: True
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.log = lambda message: logs.append(str(message))
        worker.get_coin_count = lambda wallet_id: next(counts, 94)
        worker._tx_fee_mojos = lambda: 0

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertFalse(worker._consolidate_wallet_sage(1, "CAT"))

        joined = "\n".join(logs).lower()
        self.assertIn("sage wallet is still settling", joined)
        self.assertNotIn("rejected or dropped", joined)

    def test_worker_aborts_when_consolidation_never_verifies(self):
        source = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "catalyst"
            / "coin_prep_worker.py"
        ).read_text(encoding="utf-8")

        self.assertIn("Consolidation did not complete", source)
        self.assertNotIn(
            "Continuing anyway - transactions may still be pending", source
        )

    def test_sage_combine_zero_spendable_coins_is_not_success(self):
        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": [],
        }
        fake_wallet_sage.combine_coins = lambda *args, **kwargs: {
            "success": True,
            "submitted": True,
        }
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker._consolidate_wallet_sage_fallback = lambda wallet_id, name: False

        self.assertFalse(worker._consolidate_wallet_sage_combine(1, "XCH"))

    def test_prepared_tier_wallet_skips_full_consolidation(self):
        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_wallet_balance = lambda wallet_id: {
            "success": True,
            "wallet_balance": {"unconfirmed_wallet_balance": 10_000_000_000_000_000},
        }
        fake_coin_manager = types.ModuleType("coin_manager")
        fake_coin_manager.reclassify_tier_spare_coins = lambda: {
            "reclassified": 0,
            "to_dust": 0,
        }
        fake_coin_manager.check_tier_size_drift_standalone = lambda: []

        worker = self.coin_prep_worker.CoinPrepWorker.__new__(
            self.coin_prep_worker.CoinPrepWorker
        )
        worker.is_sage = True
        worker._db_ready = False
        worker.xch_wallet_id = 1
        worker.cat_wallet_id = 2
        worker.tier_enabled = True
        worker.tier_order = ["inner", "mid"]
        worker.tier_counts = {"inner": 2, "mid": 1}
        worker.xch_tier_counts = {"inner": 2, "mid": 1}
        worker.cat_tier_counts = {"inner": 1, "mid": 1}
        worker.tier_xch_sizes = {
            "inner": Decimal("2.0"),
            "mid": Decimal("1.0"),
        }
        worker.tier_cat_sizes = {
            "inner": Decimal("100"),
            "mid": Decimal("50"),
        }
        worker.offer_tier_xch_sizes = dict(worker.tier_xch_sizes)
        worker.xch_target_coins = 3
        worker.cat_target_coins = 2
        worker.xch_expected_total_coins = 4
        worker.cat_expected_total_coins = 3
        worker.xch_coin_size = Decimal("1.0")
        worker.cat_coin_size = Decimal("50")
        worker.offer_xch_size = Decimal("1.0")
        worker.cat_decimals = 3
        worker.cat_reserve = Decimal("0")
        worker.xch_reserve = Decimal("0")
        worker.coin_prep_headroom_pct = Decimal("0")
        worker.log = lambda message: None
        worker.update_status = lambda *args, **kwargs: None
        worker._set_status_coin_counts = lambda *args, **kwargs: None
        worker._log_coin_snapshot = lambda *args, **kwargs: None
        worker.cancel_all_offers = lambda: True
        worker._tx_fee_mojos = lambda: 0
        worker.get_balance = lambda wallet_id: Decimal("999999")
        worker.get_coin_count = lambda wallet_id: 4 if wallet_id == 1 else 3
        worker.get_confirmed_coin_count = worker.get_coin_count
        worker.verify_coins = lambda: (4, 3)
        worker._merge_xch_fee_change_into_reserve = lambda: False
        worker._designate_final_sweep = lambda: None

        def coins_for(wallet_id, name, selectable_only=False):
            if wallet_id == 1:
                return [
                    {"coin_id": "xch-reserve", "amount": 5_000_000_000_000},
                    {"coin_id": "xch-inner-1", "amount": 2_000_000_000_000},
                    {"coin_id": "xch-inner-2", "amount": 2_000_000_000_000},
                    {"coin_id": "xch-mid-1", "amount": 1_000_000_000_000},
                ]
            return [
                {"coin_id": "cat-reserve", "amount": 900_000},
                {"coin_id": "cat-inner-1", "amount": 100_000},
                {"coin_id": "cat-mid-1", "amount": 50_000},
            ]

        worker._get_coins_via_rpc = coins_for

        def fail_consolidate(wallet_id, name):
            raise AssertionError(f"{name} consolidation should have been skipped")

        worker.consolidate_wallet = fail_consolidate

        with (
            patch.dict(
                sys.modules,
                {
                    "wallet_sage": fake_wallet_sage,
                    "coin_manager": fake_coin_manager,
                },
            ),
            patch.object(self.coin_prep_worker.time, "sleep", return_value=None),
        ):
            self.assertTrue(worker.run_full_preparation())


if __name__ == "__main__":
    unittest.main()
