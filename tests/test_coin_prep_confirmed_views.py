import importlib
from contextlib import nullcontext
import os
import sys
import types
import unittest
import hashlib
import json
from datetime import datetime, timedelta, timezone


_MODS_TO_RESTORE = ("coin_prep_worker", "wallet_sage", "database", "wallet", "dotenv")


class CoinPrepConfirmedViewTests(unittest.TestCase):
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
            "success": True,
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": "2026-08-21T12:00:01.000000Z",
        }
        fake_wallet.get_spendable_coin_count = lambda wallet_id: sys.modules[
            "wallet_sage"
        ].get_spendable_coin_count(wallet_id)
        fake_wallet.get_pending_transactions = lambda: []
        fake_wallet.split_coins_rpc = lambda *args, **kwargs: {"success": True}
        fake_wallet.get_transaction = lambda *args, **kwargs: {"success": True}
        fake_wallet.get_spendable_coins_rpc = lambda wallet_id: {
            "success": True,
            "records": [
                {
                    "coin": {
                        "parent_coin_info": "cc" * 32,
                        "puzzle_hash": "dd" * 32,
                        "amount": 123,
                    },
                    "coin_id": "0x" + "22" * 32,
                }
            ],
        }
        sys.modules["wallet"] = fake_wallet

        fake_database = types.ModuleType("database")
        fake_database.init_database = lambda: None
        fake_database.upsert_coin = lambda *args, **kwargs: True
        fake_database.set_coin_designation = lambda *args, **kwargs: True
        fake_database.designate_reserve = lambda *args, **kwargs: True
        fake_database.get_reserve_coins = lambda *args, **kwargs: []
        fake_database.mark_coins_gone = lambda *args, **kwargs: True
        fake_database.mark_unreserved_free_coins_gone_for_preparation = lambda: 0
        sys.modules["database"] = fake_database

        fake_wallet_sage = types.ModuleType("wallet_sage")
        fake_wallet_sage.get_current_key = lambda: {"fingerprint": "123"}
        fake_wallet_sage.get_spendable_coin_count = lambda wallet_id: (
            17 if wallet_id == 1 else 19
        )
        fake_wallet_sage.get_selectable_coins_only = lambda wallet_id: {
            "success": True,
            "records": [
                {
                    "coin": {
                        "parent_coin_info": "cc" * 32,
                        "puzzle_hash": "dd" * 32,
                        "amount": 123,
                    },
                    "coin_id": "0x" + "22" * 32,
                }
            ],
        }
        fake_wallet_sage.get_wallet_balance = lambda wallet_id: {
            "success": True,
            "wallet_balance": {"spendable_balance": 0},
        }
        fake_wallet_sage.get_owned_coins_detailed = lambda wallet_id: {}
        sys.modules["wallet_sage"] = fake_wallet_sage

        fake_dotenv = types.ModuleType("dotenv")
        fake_dotenv.dotenv_values = lambda *args, **kwargs: {}
        fake_dotenv.load_dotenv = lambda *args, **kwargs: True
        fake_dotenv.set_key = lambda *args, **kwargs: True
        sys.modules["dotenv"] = fake_dotenv

        sys.modules.pop("coin_prep_worker", None)
        self.coin_prep_worker = importlib.import_module("coin_prep_worker")
        self.worker = self.coin_prep_worker.CoinPrepWorker()

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

    def test_get_confirmed_coin_count_prefers_sage_count_endpoint(self):
        self.assertEqual(self.worker.get_confirmed_coin_count(1), 17)
        self.assertEqual(self.worker.get_confirmed_coin_count(2), 19)

    def test_get_coin_count_prefers_sage_count_endpoint(self):
        self.assertEqual(self.worker.get_coin_count(1), 17)
        self.assertEqual(self.worker.get_coin_count(2), 19)

    def test_get_coins_via_rpc_can_use_strict_selectable_view(self):
        strict_coins = self.worker._get_coins_via_rpc(
            1, "strict-test", selectable_only=True
        )
        default_coins = self.worker._get_coins_via_rpc(1, "default-test")

        self.assertEqual(len(strict_coins), 1)
        self.assertEqual(strict_coins[0]["amount"], 123)
        self.assertTrue(strict_coins[0]["coin_id"].startswith("0x22"))

        self.assertEqual(len(default_coins), 1)
        self.assertEqual(default_coins[0]["amount"], 123)
        self.assertTrue(default_coins[0]["coin_id"].startswith("0x22"))

    def test_authoritative_sage_owned_view_excludes_unconfirmed_predictions(self):
        pending_id = "0x" + "33" * 32
        confirmed_id = "0x" + "44" * 32
        sys.modules["wallet_sage"].get_owned_coins_detailed = lambda _wallet_id: {
            pending_id: {
                "amount": 100,
                "created_height": None,
                "spent_height": None,
            },
            confirmed_id: {
                "amount": 200,
                "created_height": 9194291,
                "spent_height": None,
            },
        }

        coins = self.worker._get_confirmed_owned_coins_via_rpc(
            2, "authoritative-post-view"
        )

        self.assertEqual(
            coins,
            [
                {
                    "coin_id": confirmed_id,
                    "id": confirmed_id,
                    "amount": 200,
                    "amount_mojos": 200,
                    "created_height": 9194291,
                }
            ],
        )

    def test_confirmation_order_lag_is_logged_as_info(self):
        logged = []
        self.worker.log = lambda message, severity=None: logged.append(
            (message, severity)
        )

        self.worker._log_confirmation_order_lag(
            "XCH",
            "fees",
            50,
            {
                "pool_still_visible": False,
                "pool_still_selectable": False,
                "owned_output_count": 50,
                "selectable_output_count": 46,
            },
        )

        self.assertEqual(len(logged), 1)
        message, severity = logged[0]
        self.assertEqual(severity, "info")
        self.assertIn("confirmation lag", message)
        self.assertNotIn("confirmation order anomaly", message)

    def test_strict_selectable_helper_uses_selectable_view_not_merged_view(self):
        selectable_id = "0x" + "22" * 32
        merged_only_id = "0x" + "11" * 32

        self.assertTrue(
            self.worker._are_coin_ids_selectable(1, [selectable_id], "strict-helper")
        )
        self.assertFalse(
            self.worker._are_coin_ids_selectable(1, [merged_only_id], "strict-helper")
        )

    def test_status_targets_track_prepared_coins_not_reserve_bonus(self):
        self.assertEqual(
            self.worker.status.xch_coins_target, self.worker.xch_target_coins
        )
        self.assertEqual(
            self.worker.status.cat_coins_target, self.worker.cat_target_coins
        )
        self.assertEqual(
            self.worker.xch_expected_total_coins, self.worker.xch_target_coins + 1
        )
        self.assertEqual(
            self.worker.cat_expected_total_coins, self.worker.cat_target_coins + 1
        )

    def test_blank_template_env_values_use_worker_defaults(self):
        self.assertEqual(self.worker.xch_wallet_id, 1)
        self.assertEqual(self.worker.cat_wallet_id, 2)
        self.assertEqual(self.worker.xch_target_coins, 50)
        self.assertEqual(self.worker.cat_target_coins, 50)
        self.assertEqual(self.worker.cat_decimals, 3)

    def test_preselected_pool_helper_falls_back_to_same_amount_coin_when_exact_id_not_found(
        self,
    ):
        # When the exact coin ID is not selectable AND a selectable coin with the
        # same amount exists, the worker should fall back to that coin.
        # This handles stale wallet data where the pool coin map was built before
        # the split confirmed.
        fallback_coin = {
            "coin_id": "0x" + "44" * 32,
            "id": "0x" + "44" * 32,
            "amount": 220,
            "amount_mojos": 220,
        }

        original_get = self.worker._get_coins_via_rpc
        original_selectable = self.worker._are_coin_ids_selectable
        try:

            def fake_get(wallet_id, name, selectable_only=False):
                if selectable_only:
                    return [fallback_coin]
                return []

            self.worker._get_coins_via_rpc = fake_get
            self.worker._are_coin_ids_selectable = lambda *args, **kwargs: False

            resolved = self.worker._wait_for_preselected_pool_coin(
                wallet_id=1,
                pool_coin={
                    "coin_id": "0x" + "33" * 32,
                    "amount": 220,
                    "amount_mojos": 220,
                },
                side_label="XCH",
                tier_name="fees",
                timeout_s=1,
                poll_interval_s=1,
            )
        finally:
            self.worker._get_coins_via_rpc = original_get
            self.worker._are_coin_ids_selectable = original_selectable

        # Amount-fallback: returns the selectable coin with matching amount
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.get("coin_id"), fallback_coin["coin_id"])

    def test_preselected_pool_helper_can_resolve_exact_id_from_selectable_check(self):
        expected_coin_id = "0x" + "33" * 32

        original_get = self.worker._get_coins_via_rpc
        original_selectable = self.worker._are_coin_ids_selectable
        try:
            self.worker._get_coins_via_rpc = lambda *args, **kwargs: []

            def fake_selectable(wallet_id, coin_ids, label):
                normalized = [cid.replace("0x", "").lower() for cid in coin_ids]
                return normalized == [expected_coin_id.replace("0x", "").lower()]

            self.worker._are_coin_ids_selectable = fake_selectable

            resolved = self.worker._wait_for_preselected_pool_coin(
                wallet_id=1,
                pool_coin={
                    "coin_id": expected_coin_id,
                    "amount": 220,
                    "amount_mojos": 220,
                },
                side_label="XCH",
                tier_name="fees",
                timeout_s=1,
                poll_interval_s=1,
            )
        finally:
            self.worker._get_coins_via_rpc = original_get
            self.worker._are_coin_ids_selectable = original_selectable

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["coin_id"].replace("0x", "").lower(), ("33" * 32))
        self.assertEqual(resolved["amount"], 220)

    def test_preselected_pool_helper_returns_exact_owned_coin_when_selectable_view_lags(
        self,
    ):
        expected_coin_id = "0x" + "55" * 32

        original_get = self.worker._get_coins_via_rpc
        original_owned = self.worker._get_owned_coins_via_rpc
        original_selectable = self.worker._are_coin_ids_selectable
        try:
            self.worker._get_coins_via_rpc = lambda *args, **kwargs: []
            self.worker._are_coin_ids_selectable = lambda *args, **kwargs: False
            self.worker._get_owned_coins_via_rpc = lambda *args, **kwargs: [
                {
                    "coin_id": expected_coin_id,
                    "id": expected_coin_id,
                    "amount": 220,
                    "amount_mojos": 220,
                }
            ]

            resolved = self.worker._wait_for_preselected_pool_coin(
                wallet_id=1,
                pool_coin={
                    "coin_id": expected_coin_id,
                    "amount": 220,
                    "amount_mojos": 220,
                },
                side_label="XCH",
                tier_name="sniper",
                timeout_s=1,
                poll_interval_s=1,
            )
        finally:
            self.worker._get_coins_via_rpc = original_get
            self.worker._get_owned_coins_via_rpc = original_owned
            self.worker._are_coin_ids_selectable = original_selectable

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["coin_id"].replace("0x", "").lower(), ("55" * 32))
        self.assertTrue(resolved.get("_catalyst_owned_only"))

    def test_extract_sage_transaction_ids_handles_both_plural_and_single_fields(self):
        tx_ids = self.coin_prep_worker.CoinPrepWorker._extract_sage_transaction_ids(
            {
                "transaction_ids": ["aa" * 32],
                "transaction_id": "0x" + "bb" * 32,
                "transaction": {"transaction_id": "cc" * 32},
            }
        )

        self.assertEqual(
            tx_ids,
            [
                "0x" + "aa" * 32,
                "0x" + "bb" * 32,
                "0x" + "cc" * 32,
            ],
        )

    def test_transaction_confirmation_state_marks_single_tx_confirmed(self):
        original_get_transaction = self.coin_prep_worker.get_transaction
        try:
            self.coin_prep_worker.get_transaction = lambda tx_id: {
                "confirmed": True,
                "confirmed_at_height": 12345,
            }
            state = self.worker._get_transaction_confirmation_state(["0x" + "aa" * 32])
        finally:
            self.coin_prep_worker.get_transaction = original_get_transaction

        self.assertTrue(state["confirmed"])
        self.assertEqual(state["confirmed_count"], 1)
        self.assertEqual(state["height"], 12345)

    def test_transaction_confirmation_state_marks_pending_list_tx_known(self):
        tx_id = "aa" * 32
        original_get_transaction = self.coin_prep_worker.get_transaction
        original_get_pending = getattr(
            self.coin_prep_worker, "get_pending_transactions", None
        )
        try:
            self.coin_prep_worker.get_transaction = lambda _tx_id: None
            self.coin_prep_worker.get_pending_transactions = lambda: [
                {"transaction_id": tx_id}
            ]
            state = self.worker._get_transaction_confirmation_state(["0x" + tx_id])
        finally:
            self.coin_prep_worker.get_transaction = original_get_transaction
            if original_get_pending is None:
                del self.coin_prep_worker.get_pending_transactions
            else:
                self.coin_prep_worker.get_pending_transactions = original_get_pending

        self.assertTrue(state["known"])
        self.assertFalse(state["confirmed"])

    def test_restart_recovery_observes_prepared_operation_without_wallet_replay(self):
        """Catches a PREPARED split being blindly submitted again after restart."""

        self.assertTrue(
            hasattr(
                self.coin_prep_worker.CoinPrepWorker,
                "_recover_coin_prep_operations_read_only",
            )
        )
        source = hashlib.sha256(b"recover-source").hexdigest()
        output = hashlib.sha256(b"recover-output").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-21T12:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        claim_token = "d" * 64
        operation_id = "coin-prep:" + hashlib.sha256(b"recover").hexdigest()
        operation = {
            "operation_id": operation_id,
            "source_coin_ids_json": '["' + source + '"]',
            "target_contract_json": '{"outputs":[{"amount_mojos":100,"output_index":0,"purpose":"replacement"}],"wallet_type":"xch"}',
            "wallet_identity_json": __import__("json").dumps(
                identity, sort_keys=True, separators=(",", ":")
            ),
            "effect_claim_token": claim_token,
            "effect_claim_generation": 1,
            "outcome": "PREPARED",
        }
        recorded = []
        self.coin_prep_worker.get_recoverable_coin_prep_operations = lambda: [operation]
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda op_id, **kwargs: (
                recorded.append((op_id, kwargs))
                or {"operation": {"operation_id": op_id, **kwargs}}
            )
        )
        self.worker._call_wallet_mutation = lambda *_args, **_kwargs: self.fail(
            "restart recovery must not dispatch a wallet effect"
        )

        recovered = self.worker._recover_coin_prep_operations_read_only(
            lambda row: {
                "expected_outputs": [
                    {
                        "coin_id": output,
                        "amount_mojos": 100,
                        "purpose": "replacement",
                    }
                ],
                "authoritative_view": {
                    "fresh": True,
                    "complete": True,
                    "wallet_identity": identity,
                    "observed_at": "2026-08-21T12:00:01.000000Z",
                    "expires_at": "2026-08-21T12:05:01.000000Z",
                    "coins": [
                        {
                            "coin_id": output,
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                },
            }
        )

        self.assertTrue(recovered)
        self.assertEqual(recorded[0][0], operation_id)
        self.assertEqual(recorded[0][1]["outcome"], "CONFIRMED")

    def test_startup_recovery_constructs_only_an_observer_and_never_replays(self):
        """Catches desktop recovery invoking the full prep constructor or a split."""

        now = datetime.now(timezone.utc)
        source = hashlib.sha256(b"startup-recovery-source").hexdigest()
        output = hashlib.sha256(b"startup-recovery-output").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": (now - timedelta(seconds=1))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "maximum_age_seconds": 300,
        }
        operation_id = "coin-prep:" + hashlib.sha256(b"startup-recovery").hexdigest()
        operation = {
            "operation_id": operation_id,
            "operation_kind": "split",
            "purpose": "replacement",
            "source_coin_ids_json": json.dumps([source]),
            "target_contract_json": json.dumps(
                {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                }
            ),
            "prepared_evidence_json": json.dumps({"pre_view_coin_ids": [source]}),
            "wallet_identity_json": json.dumps(identity),
            "effect_claim_token": "f" * 64,
            "effect_claim_generation": 1,
            "outcome": "SUBMITTED_UNKNOWN",
        }
        recorded = []
        self.coin_prep_worker.get_wallet_identity = lambda: {
            "success": True,
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": now.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
        }
        self.coin_prep_worker.get_recoverable_coin_prep_operations = lambda: [operation]
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda op_id, **kwargs: (
                recorded.append((op_id, kwargs))
                or {"operation": {"operation_id": op_id, **kwargs}}
            )
        )
        sys.modules["wallet_sage"].get_owned_coins = lambda wallet_id: {output: 100}
        sys.modules["wallet_sage"].get_owned_coins_detailed = lambda wallet_id: {
            output: {
                "amount": 100,
                "created_height": 9194200,
                "spent_height": None,
            }
        }
        original_init = self.coin_prep_worker.CoinPrepWorker.__init__
        original_mutation = self.coin_prep_worker.CoinPrepWorker._call_wallet_mutation
        self.coin_prep_worker.CoinPrepWorker.__init__ = lambda _worker: self.fail(
            "startup recovery must not construct the full coin-prep worker"
        )
        self.coin_prep_worker.CoinPrepWorker._call_wallet_mutation = (
            lambda *_args, **_kwargs: self.fail(
                "startup recovery must not dispatch a wallet effect"
            )
        )
        try:
            recovered = self.coin_prep_worker.recover_coin_prep_operations_at_startup()
        finally:
            self.coin_prep_worker.CoinPrepWorker.__init__ = original_init
            self.coin_prep_worker.CoinPrepWorker._call_wallet_mutation = (
                original_mutation
            )

        self.assertTrue(recovered)
        self.assertEqual(recorded[0][0], operation_id)
        self.assertEqual(recorded[0][1]["outcome"], "CONFIRMED")

    def test_startup_recovery_releases_rejected_sage_effect_only_from_exact_selectable_cohort(
        self,
    ):
        """Catches a Sage peer rejection permanently latching untouched inputs."""

        now = datetime.now(timezone.utc)
        cat_source = hashlib.sha256(b"rejected-cat-source").hexdigest()
        fee_source = hashlib.sha256(b"rejected-fee-source").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": (now - timedelta(seconds=1))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "maximum_age_seconds": 300,
        }
        operation_id = (
            "coin-prep:" + hashlib.sha256(b"rejected-sage-combine").hexdigest()
        )
        operation = {
            "operation_id": operation_id,
            "operation_kind": "combine",
            "purpose": "replacement",
            "source_coin_ids_json": json.dumps([cat_source]),
            "target_contract_json": json.dumps(
                {
                    "wallet_type": "cat",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                }
            ),
            "prepared_evidence_json": json.dumps({"pre_view_coin_ids": [cat_source]}),
            "wallet_identity_json": json.dumps(identity),
            "effect_claim_token": "e" * 64,
            "effect_claim_generation": 1,
            "effect_fee_coin_ids_json": json.dumps([fee_source]),
            "effect_dispatch_token": "d" * 64,
            "effect_authority_sha256": "a" * 64,
            "effect_adapter_operation": operation_id,
            "outcome": "SUBMITTED_UNKNOWN",
        }
        recorded = []
        self.coin_prep_worker.get_wallet_identity = lambda: {
            "success": True,
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": now.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
        }
        self.coin_prep_worker.get_recoverable_coin_prep_operations = lambda: [operation]
        self.coin_prep_worker.get_pending_transactions = lambda: []
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda op_id, **kwargs: (
                recorded.append((op_id, kwargs))
                or {"operation": {"operation_id": op_id, **kwargs}}
            )
        )

        def selectable(wallet_id):
            coin_id = fee_source if wallet_id == 1 else cat_source
            return {
                "success": True,
                "records": [
                    {
                        "coin": {
                            "parent_coin_info": "cc" * 32,
                            "puzzle_hash": "dd" * 32,
                            "amount": 100,
                        },
                        "coin_id": "0x" + coin_id,
                    }
                ],
            }

        sys.modules["wallet_sage"].get_selectable_coins_only = selectable

        recovered = self.coin_prep_worker.recover_coin_prep_operations_at_startup()

        self.assertTrue(recovered)
        self.assertEqual(recorded[0][0], operation_id)
        self.assertEqual(recorded[0][1]["outcome"], "FAILED")
        evidence = recorded[0][1]["evidence_json"]
        self.assertEqual(evidence["reason_code"], "AUTHORITATIVE_NO_EFFECT_CONFIRMED")
        self.assertEqual(evidence["source_coin_ids"], [cat_source])
        self.assertEqual(evidence["fee_coin_ids"], [fee_source])
        self.assertEqual(
            evidence["authoritative_view"]["selectable_coin_ids"],
            sorted([cat_source, fee_source]),
        )
        self.assertEqual(evidence["authoritative_view"]["pending_transaction_ids"], [])

    def test_startup_recovery_keeps_rejected_sage_effect_latched_when_fee_is_not_selectable(
        self,
    ):
        """Catches CAT-only evidence releasing an unresolved XCH fee input."""

        now = datetime.now(timezone.utc)
        cat_source = hashlib.sha256(b"latched-cat-source").hexdigest()
        fee_source = hashlib.sha256(b"latched-fee-source").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": (now - timedelta(seconds=1))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "maximum_age_seconds": 300,
        }
        operation = {
            "operation_id": "coin-prep:" + "b" * 64,
            "operation_kind": "combine",
            "purpose": "replacement",
            "source_coin_ids_json": json.dumps([cat_source]),
            "target_contract_json": json.dumps(
                {
                    "wallet_type": "cat",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                }
            ),
            "prepared_evidence_json": json.dumps({"pre_view_coin_ids": [cat_source]}),
            "wallet_identity_json": json.dumps(identity),
            "effect_claim_token": "e" * 64,
            "effect_claim_generation": 1,
            "effect_fee_coin_ids_json": json.dumps([fee_source]),
            "effect_dispatch_token": "d" * 64,
            "effect_authority_sha256": "a" * 64,
            "effect_adapter_operation": "coin-prep:" + "b" * 64,
            "outcome": "SUBMITTED_UNKNOWN",
        }
        self.coin_prep_worker.get_wallet_identity = lambda: {
            "success": True,
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": now.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
        }
        self.coin_prep_worker.get_recoverable_coin_prep_operations = lambda: [operation]
        self.coin_prep_worker.get_pending_transactions = lambda: []
        recorded = []
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda *args, **kwargs: recorded.append((args, kwargs))
        )
        sys.modules["wallet_sage"].get_selectable_coins_only = lambda wallet_id: {
            "success": True,
            "records": (
                []
                if wallet_id == 1
                else [
                    {
                        "coin": {
                            "parent_coin_info": "cc" * 32,
                            "puzzle_hash": "dd" * 32,
                            "amount": 100,
                        },
                        "coin_id": "0x" + cat_source,
                    }
                ]
            ),
        }

        recovered = self.coin_prep_worker.recover_coin_prep_operations_at_startup()

        self.assertFalse(recovered)
        self.assertEqual(recorded, [])

    def test_split_dispatch_commits_prepared_before_effect_and_confirms_exact_view(
        self,
    ):
        """Catches an actual split dispatch bypassing the Task 12 journal sequence."""

        source = hashlib.sha256(b"dispatch-source").hexdigest()
        output = hashlib.sha256(b"dispatch-output").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-21T12:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        expected_outputs = [
            {"coin_id": output, "amount_mojos": 100, "purpose": "replacement"}
        ]
        view = {
            "fresh": True,
            "complete": True,
            "wallet_identity": identity,
            "observed_at": "2026-08-21T12:00:01.000000Z",
            "expires_at": "2026-08-21T12:05:01.000000Z",
            "coins": expected_outputs,
        }
        events = []
        claim = {"claim_token": "c" * 64, "generation": 1}
        dispatch = object()
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **kwargs: (
            events.append(("claim", kwargs)) or claim
        )
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **kwargs: (
            events.append(("begin", kwargs)) or dispatch
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **kwargs: (
                events.append(("classified", kwargs)) or "SUBMITTED"
            )
        )
        self.coin_prep_worker.prepare_coin_prep_operation = lambda **kwargs: (
            events.append(("prepared", kwargs))
            or {
                "operation": {
                    "operation_id": "coin-prep:" + "a" * 64,
                    "outcome": "PREPARED",
                    "source_coin_ids_json": json.dumps([source]),
                    "wallet_identity_json": json.dumps(identity),
                    "effect_claim_token": claim["claim_token"],
                    "effect_claim_generation": claim["generation"],
                }
            }
        )
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda operation_id, **kwargs: (
                events.append(("outcome", {"operation_id": operation_id, **kwargs}))
                or {"operation": {"operation_id": operation_id, **kwargs}}
            )
        )
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._observe_coin_prep_post_effect = lambda _operation: {
            "expected_outputs": expected_outputs,
            "authoritative_view": view,
        }

        result = self.worker._call_wallet_mutation(
            "coin_prep.split_single_sage",
            lambda **_kwargs: events.append(("effect", {})) or {"success": True},
            wallet_id=1,
            target_coin_id=source,
            num_coins=1,
            amount_per_coin=100,
            fee_mojos=0,
            is_cat=False,
            _prep_contract={
                "operation_kind": "split",
                "purpose": "replacement",
                "target_contract": {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                },
                "pre_view_coin_ids": [],
            },
        )

        self.assertEqual(result, {"success": True})
        names = [name for name, _payload in events]
        self.assertIn("prepared", names)
        self.assertIn("outcome", names)
        self.assertLess(names.index("claim"), names.index("prepared"))
        self.assertLess(names.index("prepared"), names.index("effect"))
        self.assertLess(names.index("classified"), names.index("outcome"))
        self.assertEqual(events[-1][1]["outcome"], "CONFIRMED")

    def test_subprocess_split_waits_for_authoritative_post_view_before_returning(self):
        """A live worker must not submit a sibling split while one is unresolved."""

        source = hashlib.sha256(b"serialized-split-source").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-21T12:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        claim = {"claim_token": "d" * 64, "generation": 1}
        observations = iter(
            [
                None,
                {
                    "expected_outputs": [
                        {
                            "coin_id": hashlib.sha256(b"serialized-output").hexdigest(),
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                    "authoritative_view": {"fresh": True, "complete": True},
                },
            ]
        )
        observed = []
        verified = []
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **_kwargs: claim
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **_kwargs: (
            object()
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **_kwargs: "SUBMITTED"
        )
        self.coin_prep_worker.prepare_coin_prep_operation = lambda **_kwargs: {
            "operation": {
                "operation_id": "coin-prep:" + "f" * 64,
                "outcome": "PREPARED",
                "source_coin_ids_json": json.dumps([source]),
                "wallet_identity_json": json.dumps(identity),
                "effect_claim_token": claim["claim_token"],
                "effect_claim_generation": claim["generation"],
            }
        }
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda operation_id, **kwargs: {
                "operation": {"operation_id": operation_id, **kwargs}
            }
        )
        self.coin_prep_worker._guarded_wallet_mutation = (
            lambda _operation, callback, *args, **kwargs: callback(*args, **kwargs)
        )
        original_sleep = self.coin_prep_worker.time.sleep
        self.addCleanup(setattr, self.coin_prep_worker.time, "sleep", original_sleep)
        self.coin_prep_worker.time.sleep = lambda _seconds: None
        self.worker._is_subprocess = True
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._observe_coin_prep_post_effect = lambda operation: (
            observed.append(operation["operation_id"]) or next(observations)
        )
        self.worker._verify_authoritative_post_operation_view = lambda **kwargs: (
            verified.append(kwargs) or True
        )

        result = self.worker._call_wallet_mutation(
            "coin_prep.split_single_sage",
            lambda **_kwargs: {"success": True, "submitted": True},
            wallet_id=1,
            target_coin_id=source,
            num_coins=1,
            amount_per_coin=100,
            fee_mojos=0,
            is_cat=False,
            _prep_contract={
                "operation_kind": "split",
                "purpose": "replacement",
                "target_contract": {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                },
                "pre_view_coin_ids": [],
            },
        )

        self.assertEqual(result, {"success": True, "submitted": True})
        self.assertEqual(observed, ["coin-prep:" + "f" * 64] * 2)
        self.assertEqual(len(verified), 1)

    def test_authoritatively_confirmed_effect_overrides_adapter_error_result(self):
        """A proven wallet effect must not be retried because Sage omitted its tx id."""

        source = hashlib.sha256(b"confirmed-pool-source").hexdigest()
        output = hashlib.sha256(b"confirmed-pool-output").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 16 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-24T14:15:00.000000Z",
            "maximum_age_seconds": 300,
        }
        claim = {"claim_token": "7" * 64, "generation": 1}
        operation_id = "coin-prep:" + "9" * 64
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **_kwargs: claim
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **_kwargs: (
            object()
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **_kwargs: "SUBMITTED"
        )
        self.coin_prep_worker.prepare_coin_prep_operation = lambda **_kwargs: {
            "operation": {
                "operation_id": operation_id,
                "outcome": "PREPARED",
                "source_coin_ids_json": json.dumps([source]),
                "wallet_identity_json": json.dumps(identity),
                "effect_claim_token": claim["claim_token"],
                "effect_claim_generation": claim["generation"],
            }
        }
        outcomes = []
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda recorded_operation_id, **kwargs: (
                outcomes.append((recorded_operation_id, kwargs["outcome"]))
                or {"operation": {"operation_id": recorded_operation_id, **kwargs}}
            )
        )
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._observe_coin_prep_post_effect = lambda _operation: {
            "expected_outputs": [
                {
                    "coin_id": output,
                    "amount_mojos": 100,
                    "purpose": "replacement",
                }
            ],
            "authoritative_view": {"fresh": True, "complete": True},
        }
        verified = []
        self.worker._verify_authoritative_post_operation_view = lambda **kwargs: (
            verified.append(kwargs) or True
        )

        result = self.worker._call_wallet_mutation(
            "coin_prep.create_tier_pools_exact",
            lambda **_kwargs: {
                "success": False,
                "error": (
                    "create_transaction submit_transaction returned no transaction "
                    "id and pending transaction state could not be verified"
                ),
            },
            selected_coin_ids=[source],
            actions=[{"type": "send", "amount": "100"}],
            auto_submit=True,
            fee_mojos=0,
            _prep_contract={
                "operation_kind": "split",
                "purpose": "replacement",
                "target_contract": {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                },
                "pre_view_coin_ids": [source],
            },
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["outcome"], "CONFIRMED")
        self.assertNotIn("error", result)
        self.assertNotIn("transaction_id", result)
        self.assertEqual(outcomes, [(operation_id, "SUBMITTED_UNKNOWN")])
        self.assertEqual(len(verified), 1)

    def test_submitted_unknown_combine_caller_never_falls_back_or_replays(self):
        """Catches delayed confirmation being returned as retry permission."""

        sources = [hashlib.sha256(label).hexdigest() for label in (b"a", b"b")]
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-21T12:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        target_contract = {
            "wallet_type": "cat",
            "outputs": [
                {
                    "output_index": 0,
                    "amount_mojos": 100,
                    "purpose": "top_up",
                }
            ],
        }
        wallet_calls = []
        fallback_calls = []
        outcomes = []
        caller_results = []
        fake_wallet = sys.modules["wallet"]
        fake_wallet.get_spendable_coins_rpc = lambda _wallet_id: {
            "success": True,
            "confirmed_records": [
                {
                    "coin_id": "0x" + coin_id,
                    "spent_block_index": 0,
                    "amount": 50,
                }
                for coin_id in sources
            ],
        }
        fake_wallet.combine_coins = lambda **_kwargs: (
            wallet_calls.append("effect") or {"success": True, "submitted": True}
        )
        claim = {"claim_token": "f" * 64, "generation": 1}
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **_kwargs: claim
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **_kwargs: (
            object()
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **_kwargs: "SUBMITTED"
        )
        self.coin_prep_worker.prepare_coin_prep_operation = lambda **_kwargs: {
            "operation": {
                "operation_id": "coin-prep:" + "b" * 64,
                "outcome": "PREPARED",
                "source_coin_ids_json": json.dumps(sources),
                "wallet_identity_json": json.dumps(identity),
                "effect_claim_token": claim["claim_token"],
                "effect_claim_generation": claim["generation"],
            }
        }
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda operation_id, **kwargs: (
                outcomes.append((operation_id, kwargs["outcome"]))
                or {"operation": {"operation_id": operation_id, **kwargs}}
            )
        )
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._build_coin_prep_contract = lambda **_kwargs: {
            "operation_kind": "combine",
            "purpose": "top_up",
            "target_contract": target_contract,
            "pre_view_coin_ids": sources,
        }
        self.worker._observe_coin_prep_post_effect = lambda _operation: None
        self.worker._priority_combine_fee_mojos = lambda _count: 0
        self.worker._sage_consolidation_max_inputs_per_tx = lambda: 50
        submit_succeeded = self.worker._sage_submit_succeeded
        self.worker._sage_submit_succeeded = lambda result: (
            caller_results.append(result) or submit_succeeded(result)
        )
        self.worker._consolidate_wallet_sage_fallback = lambda *_args: (
            fallback_calls.append("fallback") or False
        )

        accepted = self.worker._consolidate_wallet_sage_combine(2, "CAT")

        self.assertTrue(accepted)
        self.assertEqual(wallet_calls, ["effect"])
        self.assertEqual(fallback_calls, [])
        self.assertEqual(
            type(caller_results[0]), self.coin_prep_worker.CoinPrepSubmittedUnknown
        )
        self.assertEqual(caller_results[0].outcome, "SUBMITTED_UNKNOWN")
        self.assertEqual(outcomes, [("coin-prep:" + "b" * 64, "SUBMITTED_UNKNOWN")])

    def test_subprocess_combine_waits_for_authoritative_confirmation(self):
        """Catches CAT combine blocking the immediately following XCH combine."""

        sources = [hashlib.sha256(label).hexdigest() for label in (b"cat-a", b"cat-b")]
        output = hashlib.sha256(b"combined-cat").hexdigest()
        identity = {
            "backend": "sage",
            "name": "TEST 7",
            "fingerprint": 736588221,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-24T16:00:00.000000Z",
            "maximum_age_seconds": 10,
        }
        claim = {"claim_token": "9" * 64, "generation": 1}
        operation_id = "coin-prep:" + "8" * 64
        prepared_operation = {
            "operation_id": operation_id,
            "outcome": "PREPARED",
            "source_coin_ids_json": json.dumps(sources),
            "wallet_identity_json": json.dumps(identity),
            "effect_claim_token": claim["claim_token"],
            "effect_claim_generation": claim["generation"],
        }
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **_kwargs: claim
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **_kwargs: (
            object()
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **_kwargs: "SUBMITTED"
        )
        self.coin_prep_worker.prepare_coin_prep_operation = lambda **_kwargs: {
            "operation": prepared_operation
        }
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda _operation_id, **kwargs: {
                "operation": {**prepared_operation, **kwargs}
            }
        )
        self.coin_prep_worker._guarded_wallet_mutation = (
            lambda _operation, callback, *args, **kwargs: callback(*args, **kwargs)
        )
        self.worker._is_subprocess = True
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._observe_coin_prep_post_effect = lambda _operation: None
        wait_calls = []
        self.worker._wait_for_coin_prep_post_effect = (
            lambda operation, *, timeout_s, poll_interval_s: (
                wait_calls.append(
                    (operation["operation_id"], timeout_s, poll_interval_s)
                )
                or {
                    "expected_outputs": [
                        {
                            "coin_id": output,
                            "amount_mojos": 100,
                            "purpose": "top_up",
                        }
                    ],
                    "authoritative_view": {"fresh": True, "complete": True},
                }
            )
        )
        self.worker._verify_authoritative_post_operation_view = lambda **_kwargs: True
        adapter_result = {"success": True, "submitted": True}

        result = self.worker._call_wallet_mutation(
            "coin_prep.combine",
            lambda **_kwargs: adapter_result,
            coin_ids=sources,
            fee_mojos=0,
            _prep_contract={
                "operation_kind": "combine",
                "purpose": "top_up",
                "target_contract": {
                    "wallet_type": "cat",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "top_up",
                        }
                    ],
                },
                "pre_view_coin_ids": sources,
            },
        )

        self.assertIs(result, adapter_result)
        self.assertEqual(wait_calls, [(operation_id, 900, 5)])

    def test_exact_source_tier_pool_creation_reaches_adapter_with_bound_fee_cohort(
        self,
    ):
        sources = [
            hashlib.sha256(label).hexdigest() for label in (b"pool-a", b"pool-b")
        ]
        identity = {
            "backend": "sage",
            "name": "Task 16 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-22T00:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        claims = []
        adapter_calls = []
        claim = {"claim_token": "e" * 64, "generation": 1}
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **kwargs: (
            claims.append(kwargs) or claim
        )
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **_kwargs: (
            object()
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **_kwargs: "SUBMITTED"
        )
        self.coin_prep_worker.prepare_coin_prep_operation = lambda **_kwargs: {
            "operation": {
                "operation_id": "coin-prep:" + "d" * 64,
                "outcome": "PREPARED",
                "source_coin_ids_json": json.dumps(sources),
                "wallet_identity_json": json.dumps(identity),
                "effect_claim_token": claim["claim_token"],
                "effect_claim_generation": claim["generation"],
            }
        }
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda operation_id, **kwargs: {
                "operation": {"operation_id": operation_id, **kwargs}
            }
        )
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._observe_coin_prep_post_effect = lambda _operation: None

        result = self.worker._call_wallet_mutation(
            "coin_prep.create_tier_pools_exact",
            lambda **kwargs: (
                adapter_calls.append(kwargs) or {"success": True, "submitted": True}
            ),
            selected_coin_ids=sources,
            actions=[{"type": "fee", "amount": "10"}],
            auto_submit=True,
            fee_mojos=10,
            _authority_fee_coin_ids=sources,
            _prep_contract={
                "operation_kind": "split",
                "purpose": "replacement",
                "target_contract": {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 190,
                            "purpose": "replacement",
                        }
                    ],
                },
                "pre_view_coin_ids": sources,
            },
        )

        self.assertEqual(type(result), self.coin_prep_worker.CoinPrepSubmittedUnknown)
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(claims[0]["source_coin_ids"], sources)
        self.assertEqual(claims[0]["fee_coin_ids"], sources)

    def test_exact_source_cat_combine_binds_a_separate_xch_fee_cohort(self):
        sources = [hashlib.sha256(label).hexdigest() for label in (b"cat-a", b"cat-b")]
        fee_coin_id = hashlib.sha256(b"xch-fee").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 16 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-22T00:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        claims = []
        prepared_calls = []
        adapter_calls = []
        claim = {"claim_token": "c" * 64, "generation": 1}
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **kwargs: (
            claims.append(kwargs) or claim
        )
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **_kwargs: (
            object()
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **_kwargs: "SUBMITTED"
        )

        def prepare_coin_prep_operation(**kwargs):
            prepared_calls.append(kwargs)
            return {
                "operation": {
                    "operation_id": "coin-prep:" + "a" * 64,
                    "outcome": "PREPARED",
                    "source_coin_ids_json": json.dumps(sources),
                    "wallet_identity_json": json.dumps(identity),
                    "effect_claim_token": claim["claim_token"],
                    "effect_claim_generation": claim["generation"],
                }
            }

        self.coin_prep_worker.prepare_coin_prep_operation = prepare_coin_prep_operation
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda operation_id, **kwargs: {
                "operation": {"operation_id": operation_id, **kwargs}
            }
        )
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._observe_coin_prep_post_effect = lambda _operation: None

        result = self.worker._call_wallet_mutation(
            "coin_prep.combine_cat_with_fee",
            lambda **kwargs: (
                adapter_calls.append(kwargs) or {"success": True, "submitted": True}
            ),
            coin_ids=sources,
            amount_mojos=200,
            own_address="xch1exactfee",
            asset_id="bb" * 32,
            fee_coin_id=fee_coin_id,
            fee_mojos=100_000_000,
            _authority_fee_coin_ids=[fee_coin_id],
            _prep_contract={
                "operation_kind": "combine",
                "purpose": "top_up",
                "target_contract": {
                    "wallet_type": "cat",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 200,
                            "purpose": "top_up",
                        }
                    ],
                },
                "pre_view_coin_ids": sources,
            },
        )

        self.assertEqual(type(result), self.coin_prep_worker.CoinPrepSubmittedUnknown)
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(claims[0]["source_coin_ids"], sources)
        self.assertEqual(claims[0]["fee_coin_ids"], [fee_coin_id])
        self.assertEqual(
            prepared_calls[0]["target_contract"]["external_fee"],
            {"fee_mojos": 100_000_000, "coin_ids": [fee_coin_id]},
        )

    def test_zero_fee_cat_split_keeps_fee_free_prep_contract(self):
        source = hashlib.sha256(b"zero-fee-cat-source").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 16 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-22T00:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        prepared_calls = []
        adapter_calls = []
        claim = {"claim_token": "f" * 64, "generation": 1}
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **_kwargs: claim
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **_kwargs: (
            object()
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **_kwargs: "SUBMITTED"
        )

        def prepare_coin_prep_operation(**kwargs):
            prepared_calls.append(kwargs)
            return {
                "operation": {
                    "operation_id": "coin-prep:" + "b" * 64,
                    "outcome": "PREPARED",
                    "source_coin_ids_json": json.dumps([source]),
                    "wallet_identity_json": json.dumps(identity),
                    "effect_claim_token": claim["claim_token"],
                    "effect_claim_generation": claim["generation"],
                }
            }

        self.coin_prep_worker.prepare_coin_prep_operation = prepare_coin_prep_operation
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda operation_id, **kwargs: {
                "operation": {"operation_id": operation_id, **kwargs}
            }
        )
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._observe_coin_prep_post_effect = lambda _operation: None

        result = self.worker._call_wallet_mutation(
            "coin_prep.split_cat_pool",
            lambda **kwargs: (
                adapter_calls.append(kwargs) or {"success": True, "submitted": True}
            ),
            source_coin_id=source,
            num_coins=2,
            trading_size_mojos=100,
            own_address="xch1zerofee",
            fee_mojos=0,
            is_cat=True,
            fee_coin_id=None,
            _prep_contract={
                "operation_kind": "split",
                "purpose": "top_up",
                "target_contract": {
                    "wallet_type": "cat",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "top_up",
                        },
                        {
                            "output_index": 1,
                            "amount_mojos": 100,
                            "purpose": "top_up",
                        },
                    ],
                },
                "pre_view_coin_ids": [source],
            },
        )

        self.assertEqual(type(result), self.coin_prep_worker.CoinPrepSubmittedUnknown)
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(len(prepared_calls), 1)
        self.assertNotIn("external_fee", prepared_calls[0]["target_contract"])

    def test_submitted_unknown_fee_reserve_combine_is_mapping_safe(self):
        """Catches an accepted effect crashing a caller that reads result metadata."""

        sources = [hashlib.sha256(label).hexdigest() for label in (b"reserve", b"fee")]
        output = hashlib.sha256(b"merged-reserve").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-21T12:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        source_coins = [
            {"coin_id": "0x" + sources[0], "amount": 2_000_000_000},
            {"coin_id": "0x" + sources[1], "amount": 1_000_000_000},
        ]
        wallet_calls = []
        outcomes = []
        caller_results = []
        fake_wallet = sys.modules["wallet"]
        fake_wallet.get_spendable_coins_rpc = lambda _wallet_id: {
            "success": True,
            "confirmed_records": [
                {
                    "coin_id": coin["coin_id"],
                    "spent_block_index": 0,
                    "amount": coin["amount"],
                }
                for coin in source_coins
            ],
        }
        fake_wallet.combine_coins = lambda *_args, **_kwargs: (
            wallet_calls.append("effect") or {"success": True, "submitted": True}
        )
        fake_wallet.get_pending_transactions = lambda: []
        claim = {"claim_token": "e" * 64, "generation": 1}
        self.coin_prep_worker.DB_AVAILABLE = True
        self.coin_prep_worker.claim_wallet_effect = lambda **_kwargs: claim
        self.coin_prep_worker.wallet_effect_claim_is_current = (
            lambda *_args, **_kwargs: True
        )
        self.coin_prep_worker.begin_wallet_effect_dispatch = lambda *_args, **_kwargs: (
            object()
        )
        self.coin_prep_worker.wallet_effect_adapter_dispatch_authority = (
            lambda _dispatch: nullcontext()
        )
        self.coin_prep_worker.complete_wallet_effect_dispatch = (
            lambda *_args, **_kwargs: "SUBMITTED"
        )
        self.coin_prep_worker.prepare_coin_prep_operation = lambda **_kwargs: {
            "operation": {
                "operation_id": "coin-prep:" + "e" * 64,
                "outcome": "PREPARED",
                "source_coin_ids_json": json.dumps(sources),
                "wallet_identity_json": json.dumps(identity),
                "effect_claim_token": claim["claim_token"],
                "effect_claim_generation": claim["generation"],
            }
        }
        self.coin_prep_worker.record_coin_prep_operation_outcome = (
            lambda operation_id, **kwargs: (
                outcomes.append((operation_id, kwargs["outcome"]))
                or {"operation": {"operation_id": operation_id, **kwargs}}
            )
        )
        self.worker.is_sage = True
        self.worker.tier_enabled = True
        self.worker.xch_wallet_id = 1
        self.worker._fee_pool_enabled = lambda: True
        self.worker._tx_fee_mojos = lambda: 1
        self.worker._partition_coins_for_designation = lambda coins, _wallet_type: (
            [],
            coins,
        )
        views = iter(
            [
                source_coins,
                [{"coin_id": "0x" + output, "amount": 2_999_999_999}],
            ]
        )
        self.worker._get_coins_via_rpc = lambda *_args, **_kwargs: next(views)
        self.worker.get_confirmed_coin_count = lambda _wallet_id: 1
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        self.worker._observe_coin_prep_post_effect = lambda _operation: None
        extract_ids = self.worker._extract_sage_transaction_ids
        self.worker._extract_sage_transaction_ids = lambda result: (
            caller_results.append(result) or extract_ids(result)
        )

        accepted = self.worker._merge_xch_fee_change_into_reserve()

        self.assertTrue(accepted)
        self.assertEqual(wallet_calls, ["effect"])
        self.assertEqual(len(caller_results), 1)
        self.assertEqual(
            type(caller_results[0]), self.coin_prep_worker.CoinPrepSubmittedUnknown
        )
        self.assertEqual(
            dict(caller_results[0]),
            {
                "success": True,
                "submitted": True,
                "outcome": "SUBMITTED_UNKNOWN",
                "operation_id": "coin-prep:" + "e" * 64,
                "dispatch_outcome": "SUBMITTED",
            },
        )
        self.assertNotIn("confirmed", caller_results[0])
        self.assertNotIn("transaction_id", caller_results[0])
        with self.assertRaises(TypeError):
            caller_results[0]["success"] = False
        self.assertEqual(outcomes, [("coin-prep:" + "e" * 64, "SUBMITTED_UNKNOWN")])

    def test_equal_amount_different_purposes_have_no_inferred_coin_mapping(self):
        """Catches coin-ID sort order assigning policy purpose without evidence."""

        source = hashlib.sha256(b"ambiguous-source").hexdigest()
        outputs = [
            hashlib.sha256(b"ambiguous-output-a").hexdigest(),
            hashlib.sha256(b"ambiguous-output-b").hexdigest(),
        ]
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-21T12:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        operation = {
            "operation_id": "coin-prep:" + "c" * 64,
            "source_coin_ids_json": json.dumps([source]),
            "target_contract_json": json.dumps(
                {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 50,
                            "purpose": "replacement",
                        },
                        {
                            "output_index": 1,
                            "amount_mojos": 50,
                            "purpose": "fee_reserve",
                        },
                    ],
                }
            ),
            "prepared_evidence_json": json.dumps({"pre_view_coin_ids": [source]}),
            "wallet_identity_json": json.dumps(identity),
        }
        self.worker.xch_wallet_id = 1
        self.worker.cat_wallet_id = 2
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        observed_at = (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        self.coin_prep_worker.get_wallet_identity = lambda: {
            "success": True,
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": observed_at,
        }
        self.worker._get_confirmed_owned_coins_via_rpc = lambda *_args: [
            {"coin_id": coin_id, "amount_mojos": 50} for coin_id in outputs
        ]

        observation = self.worker._observe_recoverable_coin_prep_operation(operation)

        self.assertIsNone(observation)

    def test_sage_native_split_contract_matches_ceil_then_final_output(self):
        """Sage /split divides the exact total across output_count outputs."""

        self.worker._build_coin_prep_contract = lambda **kwargs: kwargs

        contract = self.worker._build_split_prep_contract(
            wallet_id=1,
            purpose="replacement",
            source_amount_mojos=100,
            count=3,
            amount_per_coin=33,
            fee_mojos=0,
            sage_native_even_split=True,
        )

        self.assertEqual(
            contract["output_amounts_and_purposes"],
            [(34, "replacement"), (34, "replacement"), (32, "replacement")],
        )

    def test_legacy_sage_split_recovery_accepts_exact_even_distribution(self):
        """Recover a submitted split journaled with the old change-output model."""

        source = hashlib.sha256(b"legacy-sage-source").hexdigest()
        output_ids = [
            hashlib.sha256(f"legacy-sage-output-{index}".encode()).hexdigest()
            for index in range(3)
        ]
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-21T12:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        operation = {
            "operation_id": "coin-prep:" + "1" * 64,
            "operation_kind": "split",
            "purpose": "replacement",
            "source_coin_ids_json": json.dumps([source]),
            "target_contract_json": json.dumps(
                {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": index,
                            "amount_mojos": 33,
                            "purpose": "replacement",
                        }
                        for index in range(3)
                    ]
                    + [
                        {
                            "output_index": 3,
                            "amount_mojos": 1,
                            "purpose": "top_up",
                        }
                    ],
                }
            ),
            "prepared_evidence_json": json.dumps({"pre_view_coin_ids": [source]}),
            "wallet_identity_json": json.dumps(identity),
        }
        observed_at = (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        self.coin_prep_worker.get_wallet_identity = lambda: {
            "success": True,
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": observed_at,
        }
        self.worker.xch_wallet_id = 1
        self.worker.cat_wallet_id = 2
        self.worker._get_confirmed_owned_coins_via_rpc = lambda *_args: [
            {"coin_id": coin_id, "amount_mojos": amount}
            for coin_id, amount in zip(output_ids, [34, 34, 32])
        ]

        observation = self.worker._observe_recoverable_coin_prep_operation(operation)

        self.assertIsInstance(observation, dict)
        self.assertEqual(
            sorted(item["amount_mojos"] for item in observation["expected_outputs"]),
            [32, 34, 34],
        )
        self.assertEqual(
            {item["purpose"] for item in observation["expected_outputs"]},
            {"replacement"},
        )

    def test_equal_amount_same_purpose_outputs_remain_unambiguous(self):
        source = hashlib.sha256(b"same-purpose-source").hexdigest()
        outputs = [
            hashlib.sha256(b"same-purpose-output-a").hexdigest(),
            hashlib.sha256(b"same-purpose-output-b").hexdigest(),
        ]
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": "2026-08-21T12:00:00.000000Z",
            "maximum_age_seconds": 300,
        }
        operation = {
            "operation_id": "coin-prep:" + "d" * 64,
            "source_coin_ids_json": json.dumps([source]),
            "target_contract_json": json.dumps(
                {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": index,
                            "amount_mojos": 50,
                            "purpose": "replacement",
                        }
                        for index in range(2)
                    ],
                }
            ),
            "prepared_evidence_json": json.dumps({"pre_view_coin_ids": [source]}),
            "wallet_identity_json": json.dumps(identity),
        }
        self.worker.xch_wallet_id = 1
        self.worker.cat_wallet_id = 2
        self.worker._current_coin_prep_wallet_identity = lambda: identity
        observed_at = (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        self.coin_prep_worker.get_wallet_identity = lambda: {
            "success": True,
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": observed_at,
        }
        self.worker._get_confirmed_owned_coins_via_rpc = lambda *_args: [
            {"coin_id": coin_id, "amount_mojos": 50} for coin_id in outputs
        ]

        observation = self.worker._observe_recoverable_coin_prep_operation(operation)

        self.assertIsInstance(observation, dict)
        self.assertEqual(
            {item["purpose"] for item in observation["expected_outputs"]},
            {"replacement"},
        )

    def test_recovery_observation_uses_fresh_read_only_identity_while_gate_is_blocked(
        self,
    ):
        """The operation's own safety latch must not block read-only reconciliation."""

        now = datetime.now(timezone.utc)
        bound_at = (
            (now - timedelta(minutes=5))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        observed_at = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
        source = hashlib.sha256(b"self-fenced-recovery-source").hexdigest()
        output = hashlib.sha256(b"self-fenced-recovery-output").hexdigest()
        identity = {
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "bound_at_utc": bound_at,
            "maximum_age_seconds": 10,
        }
        operation = {
            "operation_id": "coin-prep:" + "e" * 64,
            "source_coin_ids_json": json.dumps([source]),
            "target_contract_json": json.dumps(
                {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": 0,
                            "amount_mojos": 100,
                            "purpose": "replacement",
                        }
                    ],
                }
            ),
            "prepared_evidence_json": json.dumps({"pre_view_coin_ids": [source]}),
            "wallet_identity_json": json.dumps(identity),
        }
        self.worker.xch_wallet_id = 1
        self.worker.cat_wallet_id = 2
        self.worker._current_coin_prep_wallet_identity = lambda: self.fail(
            "read-only recovery must not re-enter the closed mutation gate"
        )
        original_identity = self.coin_prep_worker.get_wallet_identity
        self.coin_prep_worker.get_wallet_identity = lambda: {
            "success": True,
            "backend": "sage",
            "name": "Task 12 Wallet",
            "fingerprint": 123,
            "network_id": "mainnet",
            "kind": "bls",
            "has_secrets": True,
            "observed_at_utc": observed_at,
        }
        self.worker._get_confirmed_owned_coins_via_rpc = lambda *_args: [
            {"coin_id": output, "amount_mojos": 100}
        ]
        try:
            observation = self.worker._observe_recoverable_coin_prep_operation(
                operation
            )
        finally:
            self.coin_prep_worker.get_wallet_identity = original_identity

        self.assertIsInstance(observation, dict)
        self.assertEqual(observation["authoritative_view"]["observed_at"], observed_at)
        self.assertEqual(
            observation["authoritative_view"]["expires_at"],
            (now + timedelta(seconds=10))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
        )

    def test_run_recovery_is_mandatory_when_database_bootstrap_failed(self):
        """Catches `_db_ready=False` skipping recovery and continuing to mutations."""

        worker = self.coin_prep_worker.CoinPrepWorker.__new__(
            self.coin_prep_worker.CoinPrepWorker
        )
        worker._db_ready = False
        self.coin_prep_worker.DB_AVAILABLE = True
        worker.log = lambda *_args, **_kwargs: None
        worker.update_status = lambda *_args, **_kwargs: None
        calls = []
        worker._recover_coin_prep_operations_read_only = lambda _observer: (
            calls.append("recovery") or False
        )
        worker._observe_recoverable_coin_prep_operation = lambda _row: None
        worker.get_current_state = lambda: self.fail(
            "wallet observation must not start after recovery is unavailable"
        )

        self.assertFalse(worker.run_full_preparation())
        self.assertEqual(calls, ["recovery"])


if __name__ == "__main__":
    unittest.main()
