"""Executable unsigned Sage responses for read-only staged preview tests."""

from chia_rs import Coin, CoinSpend, Program
import pytest

from fee_approval_test_utils import ADDRESS, ASSET, _coin
from fee_projection_test_utils import standard_puzzles
from sage_offer_wire import decode_wallet_puzzle_hash, encode_wallet_puzzle_hash


def prepare_unsigned_wallet(state, monkeypatch):
    import wallet
    from unsigned_effect_binding import _cat_puzzle_hash

    native, cat = standard_puzzles()
    native_coin = Coin(b"n" * 32, native.get_tree_hash(), 200_000_000_000)
    cat_parent = Coin(b"c" * 32, cat.get_tree_hash(), 20_000)
    cat_coin = Coin(cat_parent.name(), cat.get_tree_hash(), 20_000)
    roots = {
        coin.name().hex(): (coin, puzzle, asset)
        for coin, puzzle, asset in ((native_coin, native, None), (cat_coin, cat, ASSET))
    }
    state["unsigned_roots"] = roots
    state["unsigned_parents"] = {cat_coin.name().hex(): cat_parent}
    for asset, coin in (("xch", native_coin), ("cat", cat_coin)):
        row = _coin(1, str(coin.amount))
        row["coin_id"] = coin.name().hex()
        state[asset] = [row]

    def build(ids, actions):
        state.setdefault("builds", []).append((tuple(ids), actions))
        selected = [roots[cid] for cid in ids]
        fee = sum(int(a["amount"]) for a in actions if a["type"] == "fee")
        spends, summaries = [], []
        assigned_assets = set()
        cat_ring = [item[0] for item in selected if item[2] is not None]
        cat_index = 0
        cat_subtotal = 0
        for coin, puzzle, asset in selected:
            first_for_asset = asset not in assigned_assets
            assigned_assets.add(asset)
            sends = [
                a
                for a in actions
                if a["type"] == "send"
                and (a["id"]["type"] == "xch") == (asset is None)
                and first_for_asset
            ]
            destination = decode_wallet_puzzle_hash(ADDRESS)
            conditions, output_rows, duplicate_amounts, ephemeral_spends = (
                [],
                [],
                set(),
                [],
            )
            for action in sends:
                assert action["address"] == ADDRESS and action["memos"] == []
                amount = int(action["amount"])
                parent = coin
                if amount in duplicate_amounts:
                    assert asset is None, "fixture only needs duplicate native sends"
                    parent = Coin(
                        coin.name(), native.get_tree_hash(), len(ephemeral_spends)
                    )
                    conditions.append([51, native.get_tree_hash(), parent.amount])
                    output_rows.append(
                        {
                            "coin_id": parent.name().hex(),
                            "amount": str(parent.amount),
                            "address": encode_wallet_puzzle_hash(
                                native.get_tree_hash(), "xch"
                            ),
                            "receiving": True,
                            "burning": False,
                        }
                    )
                else:
                    duplicate_amounts.add(amount)
                ph = (
                    destination
                    if asset is None
                    else _cat_puzzle_hash(bytes.fromhex(ASSET), destination)
                )
                row = {
                    "coin_id": Coin(parent.name(), ph, amount).name().hex(),
                    "amount": str(amount),
                    "address": ADDRESS,
                    "receiving": True,
                    "burning": False,
                }
                if parent == coin:
                    conditions.append([51, destination, amount])
                    output_rows.append(row)
                else:
                    ephemeral_spends.append(
                        CoinSpend(
                            parent,
                            native,
                            Program.to([[], (1, [[51, destination, amount]]), []]),
                        )
                    )
                    summaries.append(
                        {
                            "coin_id": parent.name().hex(),
                            "amount": str(parent.amount),
                            "address": ADDRESS,
                            "asset": None,
                            "outputs": [row],
                        }
                    )
            if asset is None and fee and first_for_asset:
                conditions.append([52, fee])
            inner_solution = [[], (1, conditions), []]
            lineage_parent = state["unsigned_parents"].get(
                coin.name().hex(), cat_parent
            )
            solution = (
                inner_solution
                if asset is None
                else [
                    inner_solution,
                    [
                        lineage_parent.parent_coin_info,
                        native.get_tree_hash(),
                        lineage_parent.amount,
                    ],
                    cat_ring[(cat_index - 1) % len(cat_ring)].name(),
                    [coin.parent_coin_info, coin.puzzle_hash, coin.amount],
                    [
                        cat_ring[(cat_index + 1) % len(cat_ring)].parent_coin_info,
                        native.get_tree_hash(),
                        cat_ring[(cat_index + 1) % len(cat_ring)].amount,
                    ],
                    cat_subtotal,
                    0,
                ]
            )
            if asset is not None:
                cat_subtotal += coin.amount - sum(int(a["amount"]) for a in sends)
                cat_index += 1
            spends.append(CoinSpend(coin, puzzle, Program.to(solution)))
            spends += ephemeral_spends
            summaries.append(
                {
                    "coin_id": coin.name().hex(),
                    "amount": str(coin.amount),
                    "address": ADDRESS,
                    "asset": {"asset_id": ASSET} if asset else None,
                    "outputs": output_rows,
                }
            )
        return {
            "summary": {"fee": str(fee), "inputs": summaries},
            "coin_spends": [spend.to_json_dict() for spend in spends],
        }

    monkeypatch.setattr(wallet, "build_transaction_rpc", build)
    monkeypatch.setattr(
        wallet,
        "submit_built_transaction_rpc",
        lambda *_a, **_k: pytest.fail("preview attempted submission"),
    )
    return state
