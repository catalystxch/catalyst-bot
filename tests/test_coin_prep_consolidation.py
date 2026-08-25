import importlib
import json
import os
import sys
import types
import unittest
from contextlib import nullcontext
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
        fake_wallet.get_wallet_adapter_authority = lambda: None
        fake_wallet.get_wallet_identity = lambda: {
            "backend": "sage",
            "name": "Synthetic Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
        }

        def _spendable_coins(wallet_id):
            adapter = sys.modules.get("wallet_sage")
            if adapter is not None and hasattr(adapter, "get_spendable_coins_rpc"):
                return adapter.get_spendable_coins_rpc(wallet_id)
            return {"success": True, "records": []}

        fake_wallet.get_spendable_coins_rpc = _spendable_coins
        fake_wallet.get_pending_transactions = lambda *args, **kwargs: {
            "success": True,
            "transactions": [],
        }
        fake_wallet.split_coins_rpc = lambda *args, **kwargs: {"success": True}
        fake_wallet.get_transaction = lambda *args, **kwargs: {"success": True}
        fake_wallet.wallet_mutation_succeeded = lambda result: (
            result is True
            or (isinstance(result, dict) and result.get("success") is True)
        )

        def _wallet_adapter_export(name):
            adapter = sys.modules.get("wallet_sage")
            if adapter is not None and hasattr(adapter, name):
                return getattr(adapter, name)
            raise AttributeError(name)

        fake_wallet.__getattr__ = _wallet_adapter_export
        sys.modules["wallet"] = fake_wallet

        fake_database = types.ModuleType("database")
        fake_database.init_database = lambda: None
        fake_database.upsert_coin = lambda *args, **kwargs: True
        fake_database.set_coin_designation = lambda *args, **kwargs: True
        fake_database.designate_reserve = lambda *args, **kwargs: True
        fake_database.get_reserve_coins = lambda *args, **kwargs: []
        fake_database.mark_coins_gone = lambda *args, **kwargs: True
        fake_database.get_setting = lambda *args, **kwargs: None
        fake_database.set_setting = lambda *args, **kwargs: True
        fake_database.claim_wallet_effect = lambda **kwargs: {
            "claim_token": "a" * 64,
            "generation": 1,
        }
        fake_database.wallet_effect_claim_is_current = lambda *args, **kwargs: True
        fake_database.begin_wallet_effect_dispatch = lambda *args, **kwargs: object()
        fake_database.wallet_effect_adapter_dispatch_authority = nullcontext
        fake_database.complete_wallet_effect_dispatch = lambda *args, **kwargs: (
            "SUBMITTED"
        )
        fake_database.retain_wallet_effect_claim_for_reconciliation = (
            lambda *args, **kwargs: True
        )
        fake_database.get_recoverable_coin_prep_operations = lambda: []
        fake_database.mark_unreserved_free_coins_gone_for_preparation = lambda: 0
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

    def test_submitted_consolidation_gets_a_bounded_slow_block_grace_window(self):
        self.assertEqual(
            self.coin_prep_worker.CoinPrepWorker._consolidation_verify_timeout_seconds(
                xch_submitted=False, cat_submitted=False
            ),
            300,
        )
        self.assertEqual(
            self.coin_prep_worker.CoinPrepWorker._consolidation_verify_timeout_seconds(
                xch_submitted=False, cat_submitted=True
            ),
            900,
        )

    def test_submitted_split_gets_a_bounded_slow_block_grace_window(self):
        self.assertEqual(
            self.coin_prep_worker.CoinPrepWorker._submitted_split_verify_timeout_seconds(),
            900,
        )

    def test_unresolved_submitted_combine_never_dispatches_fallback(self):
        source_ids = ["11" * 32, "22" * 32]
        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_spendable_coins_rpc = lambda _wallet_id: {
            "success": True,
            "confirmed_records": [
                {"coin_id": "0x" + source_ids[0], "amount": 60},
                {"coin_id": "0x" + source_ids[1], "amount": 40},
            ],
        }
        fake_wallet_sage.combine_coins = lambda **_kwargs: {
            "success": True,
            "submitted": True,
        }
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.cat_wallet_id = 2
        worker._tx_fee_mojos = lambda: 0
        worker._sage_consolidation_max_inputs_per_tx = lambda: 50
        worker._build_coin_prep_contract = lambda **_kwargs: {}
        worker._call_wallet_mutation = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            self.coin_prep_worker.CoinPrepAuthorityUnresolved("still pending")
        )
        fallback_calls = []
        worker._consolidate_wallet_sage_fallback = lambda *_args: (
            fallback_calls.append("fallback") or False
        )

        self.assertFalse(worker._consolidate_wallet_sage_combine(2, "CAT"))
        self.assertEqual(fallback_calls, [])

    def test_sage_xch_send_to_self_fails_closed_when_sources_are_only_hints(self):
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
            self.assertFalse(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(calls["send"], [])

    def test_sage_cat_send_to_self_fails_closed_with_unbound_fee_input(self):
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
            self.assertFalse(worker._consolidate_wallet_sage(2, "CAT"))

        self.assertEqual(calls["send"], [])

    def test_sage_xch_priority_self_send_fails_closed_on_ignored_sources(self):
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
            self.assertFalse(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(calls["send"], [])

    def test_sage_large_xch_balance_self_send_fails_closed(self):
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
            self.assertFalse(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(calls, [])

    def test_sage_large_consolidation_uses_exact_coin_combine_before_unsafe_self_send(
        self,
    ):
        calls = []

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.get_coin_count = lambda wallet_id: 68
        worker._consolidate_wallet_sage_combine = lambda wallet_id, name: (
            calls.append(("combine", wallet_id, name)) or True
        )
        worker._consolidate_wallet_sage_fallback = lambda wallet_id, name: (
            calls.append(("self-send", wallet_id, name)) or False
        )

        self.assertTrue(worker._consolidate_wallet_sage(2, "CAT"))
        self.assertEqual(calls, [("combine", 2, "CAT")])

    def test_sage_small_consolidation_skips_guaranteed_denied_self_send(self):
        calls = []
        logs = []

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.log = lambda message: logs.append(str(message))
        worker.get_coin_count = lambda wallet_id: 7
        worker._consolidate_wallet_sage_combine = lambda wallet_id, name: (
            calls.append(("combine", wallet_id, name)) or True
        )
        worker._consolidate_wallet_sage_fallback = lambda wallet_id, name: (
            calls.append(("self-send", wallet_id, name)) or False
        )

        self.assertTrue(worker._consolidate_wallet_sage(2, "CAT"))
        self.assertEqual(calls, [("combine", 2, "CAT")])
        self.assertFalse(any("error" in message.lower() for message in logs))
        self.assertFalse(any("failed" in message.lower() for message in logs))

    def test_prepared_side_is_preserved_while_other_side_is_reprepared(self):
        worker = self.coin_prep_worker.CoinPrepWorker()

        self.assertFalse(worker._side_needs_consolidation(True, 68, 1))
        self.assertTrue(worker._side_needs_consolidation(False, 123, 3))
        self.assertTrue(worker._side_consolidation_ready(True, 68, 1))
        self.assertEqual(worker._tier_count_for_reprep(True, 14), 0)
        self.assertEqual(worker._tier_count_for_reprep(False, 14), 14)

    def test_sage_large_xch_staged_self_send_fails_closed_before_dispatch(self):
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

        self.assertFalse(worker._consolidate_wallet_sage_fallback(1, "XCH"))

        self.assertEqual(calls, [])
        self.assertEqual(waits, [])

    def test_sage_large_cat_staged_self_send_fails_closed_before_dispatch(self):
        def records_for(prefix, count):
            return [
                {
                    "coin_id": "0x" + f"{prefix:02x}{i:062x}",
                    "spent_block_index": 0,
                    "amount": 100,
                }
                for i in range(1, count + 1)
            ]

        record_stages = [
            records_for(1, 199),
            records_for(2, 150),
            records_for(3, 101),
            records_for(4, 52),
            records_for(5, 3),
        ]
        calls = []
        waits = []
        state = {"stage": 0}

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }

        def get_spendable_coins_rpc(wallet_id):
            return {
                "success": True,
                "confirmed_records": list(record_stages[state["stage"]]),
            }

        fake_wallet_sage.get_spendable_coins_rpc = get_spendable_coins_rpc

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
        worker.get_coin_count = lambda wallet_id: len(record_stages[state["stage"]])
        worker._tx_fee_mojos = lambda: 0
        worker._wait_for_sage_consolidation = lambda *args, **kwargs: True

        def wait_for_stage(
            wallet_id, name, before_count, target_count, *args, **kwargs
        ):
            waits.append((before_count, target_count))
            state["stage"] += 1
            return len(record_stages[state["stage"]]) <= target_count

        worker._wait_for_sage_coin_count_at_most = wait_for_stage

        self.assertFalse(worker._consolidate_wallet_sage(2, "CAT"))

        self.assertEqual(calls, [])
        self.assertEqual(waits, [])

    def test_sage_large_cat_fee_self_send_fails_closed_before_dispatch(self):
        initial_records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(1, 66)
        ]
        refreshed_records = [
            {"coin_id": "0x" + "aa" * 32, "spent_block_index": 0, "amount": 5000},
            *[
                {
                    "coin_id": "0x" + f"{i:064x}",
                    "spent_block_index": 0,
                    "amount": 100,
                }
                for i in range(51, 66)
            ],
        ]
        calls = []
        waits = []
        state = {"first_batch_settled": False}

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }

        def get_spendable_coins_rpc(wallet_id):
            return {
                "success": True,
                "confirmed_records": list(
                    refreshed_records
                    if state["first_batch_settled"]
                    else initial_records
                ),
            }

        fake_wallet_sage.get_spendable_coins_rpc = get_spendable_coins_rpc

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            source_ids = list(source_coin_ids or [])
            calls.append(
                {
                    "wallet_id": wallet_id,
                    "amount_mojos": amount_mojos,
                    "address": address,
                    "fee_mojos": fee_mojos,
                    "source_coin_ids": source_ids,
                }
            )
            if len(calls) == 2 and not state["first_batch_settled"]:
                return {"success": False, "error": "second CAT batch used stale inputs"}
            return {"success": True, "submitted": True}

        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.cat_wallet_id = 2
        worker._tx_fee_mojos = lambda: 10
        worker._sage_consolidation_max_inputs_per_tx = lambda: 50
        worker._wait_for_sage_consolidation = lambda *args, **kwargs: True

        def wait_for_stage(
            wallet_id, name, before_count, target_count, *args, **kwargs
        ):
            waits.append((wallet_id, name, before_count, target_count))
            state["first_batch_settled"] = True
            return True

        worker._wait_for_sage_coin_count_at_most = wait_for_stage

        self.assertFalse(worker._consolidate_wallet_sage_fallback(2, "CAT"))

        self.assertEqual(waits, [])
        self.assertEqual(calls, [])

    def test_sage_xch_consolidation_accepts_small_fee_change_set(self):
        counts = iter([0, 3])

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.xch_wallet_id = 1
        worker.get_coin_count = lambda wallet_id: next(counts, 3)
        worker._tx_fee_mojos = lambda: 10

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertTrue(
                worker._wait_for_sage_consolidation(
                    1, "XCH", before_count=36, max_wait_seconds=10
                )
            )

    def test_sage_xch_consolidation_does_not_accept_pre_submit_compact_count(self):
        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.xch_wallet_id = 1
        worker.get_coin_count = lambda wallet_id: 3
        worker._tx_fee_mojos = lambda: 10

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertFalse(
                worker._wait_for_sage_consolidation(
                    1, "XCH", before_count=3, max_wait_seconds=10
                )
            )

    def test_sage_batched_combine_waits_past_transient_locked_input_count(self):
        observed = []
        counts = iter([18, 19])

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.cat_wallet_id = 2

        def get_coin_count(wallet_id):
            count = next(counts, 19)
            observed.append(count)
            return count

        worker.get_coin_count = get_coin_count

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertTrue(
                worker._wait_for_sage_coin_count_at_most(
                    2,
                    "CAT",
                    before_count=68,
                    target_count=19,
                    max_wait_seconds=5,
                    poll_interval=5,
                )
            )

        self.assertEqual(observed, [18, 19])

    def test_sage_large_combine_waits_and_refreshes_before_next_batch(self):
        initial_records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(1, 75)
        ]
        refreshed_records = [
            {
                "coin_id": "0x" + "ff" * 32,
                "spent_block_index": 0,
                "amount": 5000,
            },
            *initial_records[50:],
        ]
        calls = []
        waits = []
        state = {"first_batch_confirmed": False}

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}

        def get_spendable_coins_rpc(wallet_id):
            return {
                "success": True,
                "confirmed_records": list(
                    refreshed_records
                    if state["first_batch_confirmed"]
                    else initial_records
                ),
            }

        fake_wallet_sage.get_spendable_coins_rpc = get_spendable_coins_rpc

        def combine_coins(coin_ids, fee_mojos=0):
            if calls and not state["first_batch_confirmed"]:
                return {
                    "success": False,
                    "error": "next batch submitted before first batch settled",
                }
            calls.append(list(coin_ids))
            return {
                "success": True,
                "submitted": True,
                "transaction_id": f"{len(calls):064x}",
            }

        fake_wallet_sage.combine_coins = combine_coins
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.cat_wallet_id = 2
        worker._consolidate_wallet_sage_fallback = lambda wallet_id, name: False
        worker._tx_fee_mojos = lambda: 0
        worker._sage_consolidation_max_inputs_per_tx = lambda: 50
        identity = {
            "backend": "sage",
            "name": "Task 16 Synthetic Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-22T00:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        worker._current_coin_prep_wallet_identity = lambda: identity

        def prepare_coin_prep_operation(**kwargs):
            return {
                "operation": {
                    "operation_id": "coin-prep:" + f"{len(calls):064x}",
                    "outcome": "PREPARED",
                    "source_coin_ids_json": json.dumps(kwargs["source_coin_ids"]),
                    "target_contract_json": json.dumps(kwargs["target_contract"]),
                    "wallet_identity_json": json.dumps(kwargs["wallet_identity_json"]),
                    "prepared_evidence_json": json.dumps(kwargs["evidence_json"]),
                    "effect_claim_token": kwargs["effect_claim_token"],
                    "effect_claim_generation": kwargs["effect_claim_generation"],
                }
            }

        self.coin_prep_worker.prepare_coin_prep_operation = prepare_coin_prep_operation
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda *args, **kwargs: {"operation": {"outcome": kwargs["outcome"]}}
        )

        def wait_for_stage(wallet_id, name, before_count, target_count):
            waits.append((wallet_id, name, before_count, target_count))
            state["first_batch_confirmed"] = True
            return True

        worker._wait_for_sage_coin_count_at_most = wait_for_stage

        self.assertTrue(worker._consolidate_wallet_sage_combine(2, "CAT"))

        self.assertEqual([len(batch) for batch in calls], [50, 25])
        self.assertEqual(waits, [(2, "CAT", 74, 25)])
        self.assertEqual(calls[1][0], "0x" + "ff" * 32)

    def test_sage_cat_combine_does_not_request_auto_selected_xch_fee(self):
        fee_calls = []
        records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(1, 3)
        ]

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": records,
        }

        def combine_coins(coin_ids, fee_mojos=0):
            fee_calls.append(fee_mojos)
            return {
                "success": True,
                "submitted": True,
                "transaction_id": "1" * 64,
            }

        fake_wallet_sage.combine_coins = combine_coins
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.xch_wallet_id = 1
        worker.cat_wallet_id = 2
        worker._tx_fee_mojos = lambda: 13_079_100

        def dispatch(_operation, callback, *args, **kwargs):
            callback_kwargs = {
                key: value for key, value in kwargs.items() if not key.startswith("_")
            }
            return callback(*args, **callback_kwargs)

        worker._call_wallet_mutation = dispatch

        self.assertTrue(worker._consolidate_wallet_sage_combine(2, "CAT"))
        self.assertEqual(fee_calls, [0])

    def test_sage_large_combine_never_leaves_singleton_batch(self):
        initial_records = [
            {"coin_id": "0x" + f"{i:064x}", "spent_block_index": 0, "amount": 100}
            for i in range(1, 52)
        ]
        refreshed_records = [
            {
                "coin_id": "0x" + "ee" * 32,
                "spent_block_index": 0,
                "amount": 4900,
            },
            *initial_records[49:],
        ]
        calls = []
        state = {"first_batch_confirmed": False}

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "confirmed_records": list(
                refreshed_records if state["first_batch_confirmed"] else initial_records
            ),
        }

        def combine_coins(coin_ids, fee_mojos=0):
            calls.append(list(coin_ids))
            return {
                "success": True,
                "submitted": True,
                "transaction_id": f"{len(calls):064x}",
            }

        fake_wallet_sage.combine_coins = combine_coins
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.cat_wallet_id = 2
        worker._consolidate_wallet_sage_fallback = lambda wallet_id, name: False
        worker._tx_fee_mojos = lambda: 0
        worker._sage_consolidation_max_inputs_per_tx = lambda: 50
        worker._current_coin_prep_wallet_identity = lambda: {
            "backend": "sage",
            "name": "Task 16 Synthetic Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-22T00:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        self.coin_prep_worker.prepare_coin_prep_operation = lambda **kwargs: {
            "operation": {
                "operation_id": "coin-prep:" + f"{len(calls):064x}",
                "outcome": "PREPARED",
                "source_coin_ids_json": json.dumps(kwargs["source_coin_ids"]),
                "target_contract_json": json.dumps(kwargs["target_contract"]),
                "wallet_identity_json": json.dumps(kwargs["wallet_identity_json"]),
                "prepared_evidence_json": json.dumps(kwargs["evidence_json"]),
                "effect_claim_token": kwargs["effect_claim_token"],
                "effect_claim_generation": kwargs["effect_claim_generation"],
            }
        }
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda *args, **kwargs: {"operation": {"outcome": kwargs["outcome"]}}
        )

        def wait_for_stage(*args, **kwargs):
            state["first_batch_confirmed"] = True
            return True

        worker._wait_for_sage_coin_count_at_most = wait_for_stage

        self.assertTrue(worker._consolidate_wallet_sage_combine(2, "CAT"))
        self.assertEqual([len(batch) for batch in calls], [49, 3])
        self.assertTrue(all(len(batch) >= 2 for batch in calls))

    def test_sage_consolidation_rejects_ignored_source_adapter_before_pending_poll(
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

        self.assertEqual(calls, [])

    def test_sage_consolidation_does_not_resync_without_a_safe_submission(self):
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
            self.assertFalse(worker._consolidate_wallet_sage(1, "XCH"))

        self.assertEqual(calls, {"send": 0, "resync": 0})

    def test_sage_consolidation_reports_authority_denial_before_settling_checks(
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
        self.assertIn("denied by durable coin authority", joined)
        self.assertNotIn("rejected or dropped", joined)

    def test_sage_consolidation_does_not_follow_up_an_unsafe_submission(self):
        calls = {"send": [], "wait": 0}
        visible_count = {"value": 15}
        coin_batches = [
            [
                {
                    "coin_id": "0x" + f"{i:064x}",
                    "spent_block_index": 0,
                    "amount": 100,
                }
                for i in range(1, 16)
            ],
            [
                {
                    "coin_id": "0x" + f"{i:064x}",
                    "spent_block_index": 0,
                    "amount": 100,
                }
                for i in range(101, 103)
            ],
        ]

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
            "address": "xch1self",
        }

        def get_spendable_coins_rpc(wallet_id):
            batch = coin_batches[min(len(calls["send"]), len(coin_batches) - 1)]
            return {"success": True, "confirmed_records": list(batch)}

        def send_transaction(
            wallet_id, amount_mojos, address, fee_mojos=0, source_coin_ids=None
        ):
            calls["send"].append(
                {
                    "wallet_id": wallet_id,
                    "amount_mojos": amount_mojos,
                    "source_coin_ids": list(source_coin_ids or []),
                }
            )
            return {"success": True, "submitted": True}

        fake_wallet_sage.get_spendable_coins_rpc = get_spendable_coins_rpc
        fake_wallet_sage.send_transaction = send_transaction
        sys.modules["wallet_sage"] = fake_wallet_sage

        worker = self.coin_prep_worker.CoinPrepWorker()
        worker.cat_wallet_id = 2
        worker.get_coin_count = lambda wallet_id: visible_count["value"]
        worker._tx_fee_mojos = lambda: 0

        def wait_for_consolidation(wallet_id, name, before_count):
            calls["wait"] += 1
            if calls["wait"] == 1:
                self.assertEqual(before_count, 15)
                visible_count["value"] = 2
                return False
            self.assertEqual(before_count, 2)
            visible_count["value"] = 1
            return True

        worker._wait_for_sage_consolidation = wait_for_consolidation

        with patch.object(self.coin_prep_worker.time, "sleep", return_value=None):
            self.assertFalse(worker._consolidate_wallet_sage(2, "CAT"))

        self.assertEqual(calls["wait"], 0)
        self.assertEqual(calls["send"], [])

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
