"""Real approved pricing/holds/worker must complete disclosed XCH prerequisites."""

import json
import copy
from importlib import import_module

import pytest
from chia_rs import Coin

import fee_approval_test_utils as utils
import fee_staged_preview_utils as unsigned_utils
from fee_projection_test_utils import standard_puzzles
from sage_offer_wire import decode_wallet_puzzle_hash, encode_wallet_puzzle_hash
from test_coin_prep_fee_worker_dispatch import active_worker  # noqa: F401
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


@pytest.mark.parametrize(
    "mode,root_count,amount,expected_batches,estimate,maximum_fee,reserve,fragment_asset,restart_after_first",
    [
        ("two_sided", 61, 2_000_000_000, 3, 100, 100, 40, "xch", False),
        ("two_sided", 153, 800_000_000, 4, 140, 140, 40, "xch", False),
        # The fixture has prior two-sided consent: its 40-mojo protection remains.
        ("buy_only", 61, 2_000_000_000, 2, 60, 80, 40, "xch", False),
        ("buy_only", 153, 800_000_000, 3, 100, 120, 40, "xch", False),
        ("two_sided", 55, 200, 3, 100, 100, 40, "cat", False),
        ("two_sided", 153, 80, 4, 140, 140, 40, "cat", False),
        ("two_sided", 55, 200, 3, 100, 100, 40, "cat", True),
    ],
)
def test_disclosed_fragmented_stages_execute_with_exact_holds_and_confirmation(
    active_worker,
    monkeypatch,
    mode,
    root_count,
    amount,
    expected_batches,
    estimate,
    maximum_fee,
    reserve,
    fragment_asset,
    restart_after_first,
):
    # This would fail if pricing or hold reconstruction refused the very
    # prerequisite the public preview already charged/obtained consent for.
    state = active_worker
    database = import_module("database")
    service = import_module("coin_prep_fee_approval")
    from unsigned_effect_binding import _cat_puzzle_hash

    native, cat = standard_puzzles()
    address = encode_wallet_puzzle_hash(native.get_tree_hash(), "xch")
    monkeypatch.setattr(utils, "ADDRESS", address)
    monkeypatch.setattr(unsigned_utils, "ADDRESS", address)
    state["config"].LIQUIDITY_MODE = mode
    state[fragment_asset] = []
    for index in range(root_count):
        parent = Coin(index.to_bytes(32, "big"), cat.get_tree_hash(), amount)
        coin = (
            Coin(parent.name(), cat.get_tree_hash(), amount)
            if fragment_asset == "cat"
            else Coin(index.to_bytes(32, "big"), native.get_tree_hash(), amount)
        )
        row = utils._coin(index, str(amount))
        row["coin_id"] = coin.name().hex()
        state[fragment_asset].append(row)
        state["unsigned_roots"][coin.name().hex()] = (
            coin,
            cat if fragment_asset == "cat" else native,
            utils.ASSET if fragment_asset == "cat" else None,
        )
        if fragment_asset == "cat":
            state["unsigned_parents"][coin.name().hex()] = parent
        database.upsert_coin(
            coin.name().hex(), fragment_asset, amount, purpose="replacement"
        )
    preview = service.preview_coin_prep_fees({})
    assert preview["available"] is True, preview
    assert preview["estimated_total_fee_mojos"] == estimate
    if mode == "buy_only" and root_count == 61:
        assert [(s["stage_id"], s["cost_kind"]) for s in preview["stages"]] == [
            ("prep_xch_consolidation", "exact_unsigned"),
            ("prep_xch", "projected"),
            ("cancel_xch", "projected"),
        ]
    approval = service.approve_coin_prep_fees(
        preview_id=preview["preview_id"],
        maximum_fee_mojos=maximum_fee,
        cancellation_reserve_mojos=reserve,
    )
    state["worker"].fee_approval_id = approval["approval_id"]
    sent, observations = [], []

    def submit(unsigned):
        # Only the external wallet is synthetic. Executable inspection, exact
        # fee reservations, fencing, journals and authoritative settlement run.
        account = database.get_fee_approval(approval["approval_id"])
        assert account["held_fee_mojos"] == 20
        assert account["spent_fee_mojos"] == 20 * len(sent)
        assert account["remaining_preparation_fee_mojos"] >= 0
        assert unsigned["_catalyst_executable_effect_bound"] is True
        if fragment_asset == "cat":
            competitor = copy.copy(state["worker"])
            competitor.status = copy.copy(state["worker"].status)
            with pytest.raises(ValueError, match="FEE_EFFECT_RECOVERY_REQUIRED"):
                competitor._run_direct_batch_prep()
            assert (
                database.get_fee_approval(approval["approval_id"])["held_fee_mojos"]
                == 20
            )
        sent.append(unsigned)
        return {"success": True, "transaction_id": len(sent).to_bytes(32, "big").hex()}

    def observe(operation, **_kwargs):
        unsigned = sent[-1]
        outputs = json.loads(operation["constructed_outputs_json"])
        for output in outputs:
            output["coin_id"] = output["coin_id"].removeprefix("0x")
        inputs = unsigned["summary"]["inputs"]
        parents = {
            o["coin_id"]: row["coin_id"] for row in inputs for o in row["outputs"]
        }
        spent = {row["coin_id"] for row in inputs}
        for asset in ("xch", "cat"):
            state[asset] = [row for row in state[asset] if row["coin_id"] not in spent]
        for output in outputs:
            asset = output["asset"]
            ph = decode_wallet_puzzle_hash(output["address"])
            if asset == "cat":
                ph = _cat_puzzle_hash(bytes.fromhex(utils.ASSET), ph)
            coin = Coin(
                bytes.fromhex(parents[output["coin_id"]]), ph, output["amount_mojos"]
            )
            assert coin.name().hex() == output["coin_id"]
            row = utils._coin(0, str(coin.amount))
            row["coin_id"] = coin.name().hex()
            state[asset].append(row)
            state["unsigned_roots"][coin.name().hex()] = (
                coin,
                native if asset == "xch" else cat,
                None if asset == "xch" else utils.ASSET,
            )
            if asset == "cat":
                state["unsigned_parents"][coin.name().hex()] = state["unsigned_roots"][
                    parents[output["coin_id"]]
                ][0]
        observations.append(operation)
        return {
            "expected_outputs": outputs,
            "authoritative_view": {
                "fresh": True,
                "complete": True,
                "wallet_identity": json.loads(operation["wallet_identity_json"]),
                "observed_at": "2026-08-21T12:00:01.000000Z",
                "expires_at": "2026-08-21T12:00:16.000000Z",
                "coins": outputs,
            },
        }

    monkeypatch.setattr(state["module"], "submit_built_transaction_rpc", submit)
    worker = state["worker"]
    worker._wait_for_coin_prep_post_effect = observe
    worker._submitted_split_verify_timeout_seconds = lambda: 1
    worker.log = lambda message: state.setdefault("logs", []).append(message)
    if restart_after_first:
        dispatch = import_module("coin_prep_fee_dispatch")
        price = dispatch.price_approved_prep_batch
        interrupted = []

        def interrupt_after_confirmed(approval_id):
            if len(sent) == 1 and not interrupted:
                interrupted.append(True)
                raise RuntimeError("simulated restart after confirmed prerequisite")
            return price(approval_id)

        monkeypatch.setattr(
            dispatch, "price_approved_prep_batch", interrupt_after_confirmed
        )
        with pytest.raises(RuntimeError, match="simulated restart"):
            worker._run_direct_batch_prep()
        assert len(sent) == 1 and len(observations) == 1
        assert database.get_fee_approval(approval["approval_id"])["held_fee_mojos"] == 0
        worker = copy.copy(worker)
        worker.status = copy.copy(worker.status)
    assert worker._run_direct_batch_prep() is True, state.get("logs")
    assert len(sent) == expected_batches
    assert len(observations) == expected_batches
    assert worker.status.batch_confirmed == expected_batches - int(restart_after_first)
    account = database.get_fee_approval(approval["approval_id"])
    assert account["spent_fee_mojos"] == 20 * expected_batches
    assert account["held_fee_mojos"] == 0
    assert account["cancellation_reserve_mojos"] == reserve
    assert database.settle_terminal_coin_prep_fee_reservations() == 0
    complete = worker._complete_approved_fee_session()
    assert complete["dispatch_authorized"] is False
