import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock, patch

import coin_prep_worker


def test_sage_cat_pool_and_fee_input_creation_bind_exact_sources():
    asset_id = "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105"
    source_id = "aa" * 32
    pool_id = "bb" * 32
    change_id = "cc" * 32
    xch_source_id = "dd" * 32
    submitted = {"value": False}
    mutation_calls = []

    fake_wallet_sage = types.ModuleType("wallet_sage")
    fake_wallet_sage.get_peer_connections = lambda: [{"peer_id": "peer"}]
    fake_wallet_sage.get_selectable_coins_only = lambda wallet_id: {
        "success": True,
        "confirmed_records": [],
    }
    fake_wallet = types.ModuleType("wallet")
    fake_wallet.get_next_address = lambda wallet_id, new_address=False: {
        "address": "xch1testaddress",
    }
    fake_wallet.create_transaction_rpc = MagicMock(
        return_value={"success": True, "transaction_id": "11" * 32}
    )
    fake_wallet.send_transaction = MagicMock()
    fake_wallet.send_transaction_multi = MagicMock()
    fake_wallet.send_cat_multi = MagicMock(
        side_effect=AssertionError("CAT pool creation must not auto-select inputs")
    )
    fake_wallet.split_coins_rpc = MagicMock()
    fake_wallet.sage_topup_split = MagicMock()
    fake_wallet.get_pending_transactions = lambda: []

    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.is_sage = True
    worker.xch_wallet_id = 1
    worker.cat_wallet_id = 2
    worker.cat_decimals = 3
    worker.tier_xch_sizes = {"inner": Decimal("1")}
    worker.tier_cat_sizes = {"inner": Decimal("10")}
    worker.xch_tier_counts = {}
    worker.cat_tier_counts = {"inner": 2}
    worker.xch_target_coins = 0
    worker.cat_target_coins = 2
    worker.xch_expected_total_coins = 1
    worker.cat_expected_total_coins = 3
    worker._xch_plan_already_satisfied = True
    worker._cat_plan_already_satisfied = False
    worker.log = MagicMock()
    worker.update_status = MagicMock()
    worker._set_status_coin_counts = lambda *args, **kwargs: None
    worker._tx_fee_mojos = lambda: 13_079_100
    worker._split_tx_fee_mojos = lambda is_cat=False: 0
    worker._get_transaction_confirmation_state = lambda tx_ids: {
        "known": True,
        "confirmed": True,
        "confirmed_count": len(tx_ids or []),
        "total": len(tx_ids or []),
        "height": 1,
    }

    def owned_coins(wallet_id, label):
        if wallet_id == 1:
            return [{"coin_id": xch_source_id, "amount": 2_000_000_000}]
        if wallet_id != 2:
            return []
        if submitted["value"]:
            return [
                {"coin_id": pool_id, "amount": 20_000},
                {"coin_id": change_id, "amount": 80_000},
            ]
        return [{"coin_id": source_id, "amount": 100_000}]

    worker._get_owned_coins_via_rpc = owned_coins
    worker._get_coins_via_rpc = lambda wallet_id, label, selectable_only=False: (
        owned_coins(wallet_id, label)
    )
    worker._get_strict_selectable_coin_id_set = lambda wallet_id, label: (
        {xch_source_id}
        if wallet_id == 1
        else ({pool_id, change_id} if submitted["value"] else {source_id})
    )
    worker._wait_for_preselected_pool_coin = (
        lambda wallet_id, pool_coin, side_label, tier_name, timeout_s=300, poll_interval_s=5: (
            pool_coin
        )
    )
    worker._are_coin_ids_selectable = lambda *args, **kwargs: True

    def call_wallet_mutation(operation, callback, *args, **kwargs):
        mutation_calls.append((operation, callback, kwargs))
        if operation == "coin_prep.create_tier_pools_exact":
            send_ids = [
                action.get("id", {}).get("type")
                for action in kwargs.get("actions", [])
                if action.get("type") == "send"
            ]
            if send_ids == ["existing"]:
                submitted["value"] = True
                return {"success": True, "transaction_id": "11" * 32}
            return None
        return None

    worker._call_wallet_mutation = call_wallet_mutation

    with (
        patch.dict(
            sys.modules,
            {"wallet_sage": fake_wallet_sage, "wallet": fake_wallet},
        ),
        patch.dict("os.environ", {"CAT_ASSET_ID": asset_id}),
        patch("coin_prep_worker.time.sleep", return_value=None),
    ):
        assert (
            worker.create_and_split_tier_pools_sage(Decimal("0"), Decimal("20"))
            is False
        )

    exact_calls = [
        call
        for call in mutation_calls
        if call[0] == "coin_prep.create_tier_pools_exact"
    ]
    assert len(exact_calls) == 2
    _operation, callback, kwargs = exact_calls[0]
    assert callback is not fake_wallet.send_cat_multi
    assert kwargs["selected_coin_ids"] == [source_id]
    assert kwargs["fee_mojos"] == 0
    send_actions = [action for action in kwargs["actions"] if action["type"] == "send"]
    assert send_actions == [
        {
            "type": "send",
            "id": {"type": "existing", "asset_id": asset_id},
            "address": "xch1testaddress",
            "amount": "20000",
            "memos": [],
        }
    ]
    _operation, _callback, fee_kwargs = exact_calls[1]
    assert fee_kwargs["selected_coin_ids"] == [xch_source_id]
    assert fee_kwargs["fee_mojos"] == 13_079_100
    assert fee_kwargs["_authority_fee_coin_ids"] == [xch_source_id]
    assert fee_kwargs["actions"] == [
        {
            "type": "send",
            "id": {"type": "xch"},
            "address": "xch1testaddress",
            "amount": "1100000000",
            "memos": [],
        },
        {"type": "fee", "amount": "13079100"},
    ]
    assert not any(
        "confirmed on-chain" in str(call.args[0]) for call in worker.log.call_args_list
    )
    fake_wallet.send_cat_multi.assert_not_called()


def test_sage_tiered_prep_fails_closed_when_multi_send_cannot_bind_sources():
    fake_wallet_sage = types.ModuleType("wallet_sage")
    fake_wallet_sage.get_next_address = lambda wallet_id, new_address=False: {
        "address": "xch1testaddress",
    }
    fake_wallet_sage.send_transaction = MagicMock(return_value={"success": True})
    fake_wallet_sage.send_transaction_multi = MagicMock(
        return_value={"success": True, "transaction_id": "11" * 32}
    )
    fake_wallet_sage.create_transaction_rpc = MagicMock(
        side_effect=AssertionError("missing authoritative sources must fail closed")
    )
    fake_wallet_sage.send_cat_multi = MagicMock(
        side_effect=AssertionError("buy-only prep should not submit CAT multi_send")
    )
    fake_wallet_sage.split_coins_rpc = MagicMock(
        return_value={"success": True, "transaction_id": "22" * 32}
    )
    fake_wallet_sage.sage_topup_split = MagicMock(
        side_effect=AssertionError("buy-only prep should not split CAT pools")
    )
    fake_wallet_sage.get_pending_transactions = lambda *args, **kwargs: []
    fake_wallet_sage.get_peer_connections = lambda: [{"peer_id": "peer"}]
    fake_wallet = types.ModuleType("wallet")
    for name in (
        "get_next_address",
        "send_transaction",
        "send_transaction_multi",
        "create_transaction_rpc",
        "send_cat_multi",
        "split_coins_rpc",
        "sage_topup_split",
        "get_pending_transactions",
    ):
        setattr(fake_wallet, name, getattr(fake_wallet_sage, name))

    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.is_sage = True
    worker.xch_wallet_id = 1
    worker.cat_wallet_id = 2
    worker.cat_decimals = 3
    worker.tier_xch_sizes = {"inner": Decimal("1")}
    worker.tier_cat_sizes = {"inner": Decimal("0")}
    worker.xch_tier_counts = {"inner": 2}
    worker.cat_tier_counts = {}
    worker.xch_target_coins = 2
    worker.cat_target_coins = 0
    worker.xch_expected_total_coins = 3
    worker.cat_expected_total_coins = 1
    worker.log = MagicMock()
    worker.update_status = MagicMock()
    worker._tx_fee_mojos = lambda: 0
    worker._split_tx_fee_mojos = lambda: 0
    worker._wait_for_preselected_pool_coin = (
        lambda wallet_id, pool_coin, side_label, tier_name, timeout_s=300, poll_interval_s=5: (
            pool_coin
        )
    )
    worker._get_transaction_confirmation_state = lambda tx_ids: {
        "known": True,
        "confirmed": True,
        "confirmed_count": len(tx_ids or []),
        "total": len(tx_ids or []),
        "height": 1,
    }
    worker._set_status_coin_counts = lambda *args, **kwargs: None
    worker.get_confirmed_coin_count = lambda wallet_id: 3 if wallet_id == 1 else 1

    pool_id = "aa" * 32
    output_ids = ["bb" * 32, "cc" * 32]

    def owned_map(wallet_id, name):
        if "split-poll-cycle" in name:
            return {output_ids[0]: 1_000_000_000_000, output_ids[1]: 1_000_000_000_000}
        if wallet_id == 1:
            return {pool_id: 2_000_000_000_000}
        return {}

    worker._get_owned_coin_amount_map = owned_map
    worker._get_strict_selectable_coin_id_set = lambda wallet_id, name: (
        set(output_ids)
        if "split-poll-cycle" in name
        else ({pool_id} if wallet_id == 1 else set())
    )
    worker._are_coin_ids_selectable = lambda wallet_id, coin_ids, name: True

    with (
        patch.dict(
            sys.modules,
            {"wallet_sage": fake_wallet_sage, "wallet": fake_wallet},
        ),
        patch(
            "coin_prep_worker.claim_wallet_effect",
            return_value={"claim_token": "a" * 64, "generation": 1},
        ),
        patch("coin_prep_worker.wallet_effect_claim_is_current", return_value=True),
        patch("coin_prep_worker.begin_wallet_effect_dispatch", return_value=object()),
        patch(
            "coin_prep_worker.complete_wallet_effect_dispatch", return_value="SUBMITTED"
        ),
        patch(
            "coin_prep_worker.retain_wallet_effect_claim_for_reconciliation",
            return_value=True,
        ),
        patch("coin_prep_worker.time.sleep", return_value=None),
    ):
        assert (
            worker.create_and_split_tier_pools_sage(
                Decimal("2"),
                Decimal("0"),
            )
            is False
        )

    fake_wallet_sage.send_transaction_multi.assert_not_called()
    fake_wallet_sage.send_cat_multi.assert_not_called()
    fake_wallet_sage.sage_topup_split.assert_not_called()
