"""Executable unsigned Sage responses for read-only staged preview tests."""

from chia_rs import Coin, CoinSpend, Program
from chia.util.bech32m import encode_puzzle_hash
import pytest

from fee_approval_test_utils import ADDRESS, ASSET, _coin
from fee_projection_test_utils import standard_puzzles


def prepare_unsigned_wallet(state, monkeypatch):
    import wallet
    from unsigned_effect_binding import _cat_puzzle_hash

    native, cat = standard_puzzles()
    native_coin = Coin(b"n" * 32, native.get_tree_hash(), 200_000_000_000)
    cat_parent = Coin(b"c" * 32, cat.get_tree_hash(), 20_000)
    cat_coin = Coin(cat_parent.name(), cat.get_tree_hash(), 20_000)
    roots = {coin.name().hex(): (coin, puzzle, asset)
             for coin, puzzle, asset in ((native_coin, native, None), (cat_coin, cat, ASSET))}
    state["unsigned_roots"] = roots
    for asset, coin in (("xch", native_coin), ("cat", cat_coin)):
        row = _coin(1, str(coin.amount))
        row["coin_id"] = coin.name().hex()
        state[asset] = [row]

    def build(ids, actions):
        state.setdefault("builds", []).append((tuple(ids), actions))
        selected = [roots[cid] for cid in ids]
        fee = sum(int(a["amount"]) for a in actions if a["type"] == "fee")
        spends, summaries = [], []
        for coin, puzzle, asset in selected:
            sends = [a for a in actions if a["type"] == "send"
                     and (a["id"]["type"] == "xch") == (asset is None)]
            conditions, output_rows, duplicate_amounts, ephemeral_spends = [], [], set(), []
            for action in sends:
                assert action["address"] == ADDRESS and action["memos"] == []
                amount = int(action["amount"])
                parent = coin
                if amount in duplicate_amounts:
                    assert asset is None, "fixture only needs duplicate native sends"
                    parent = Coin(coin.name(), native.get_tree_hash(), len(ephemeral_spends))
                    conditions.append([51, native.get_tree_hash(), parent.amount])
                    output_rows.append({"coin_id": parent.name().hex(), "amount": str(parent.amount),
                                        "address": encode_puzzle_hash(native.get_tree_hash(), "xch"),
                                        "receiving": True, "burning": False})
                else:
                    duplicate_amounts.add(amount)
                ph = b"\x32" * 32 if asset is None else _cat_puzzle_hash(bytes.fromhex(ASSET), b"\x32" * 32)
                row = {"coin_id": Coin(parent.name(), ph, amount).name().hex(), "amount": str(amount),
                       "address": ADDRESS, "receiving": True, "burning": False}
                if parent == coin:
                    conditions.append([51, b"\x32" * 32, amount])
                    output_rows.append(row)
                else:
                    ephemeral_spends.append(CoinSpend(parent, native,
                        Program.to([[], (1, [[51, b"\x32" * 32, amount]]), []])))
                    summaries.append({"coin_id": parent.name().hex(), "amount": str(parent.amount),
                                      "address": ADDRESS, "asset": None, "outputs": [row]})
            if asset is None and fee:
                conditions.append([52, fee])
            inner_solution = [[], (1, conditions), []]
            solution = inner_solution if asset is None else [inner_solution,
                [cat_parent.parent_coin_info, native.get_tree_hash(), cat_parent.amount],
                coin.name(), [coin.parent_coin_info, coin.puzzle_hash, coin.amount],
                [coin.parent_coin_info, native.get_tree_hash(), coin.amount], 0, 0]
            spends.append(CoinSpend(coin, puzzle, Program.to(solution)))
            spends += ephemeral_spends
            summaries.append({"coin_id": coin.name().hex(), "amount": str(coin.amount),
                              "address": ADDRESS, "asset": {"asset_id": ASSET} if asset else None,
                              "outputs": output_rows})
        return {"summary": {"fee": str(fee), "inputs": summaries},
                "coin_spends": [spend.to_json_dict() for spend in spends]}

    monkeypatch.setattr(wallet, "build_transaction_rpc", build)
    monkeypatch.setattr(wallet, "submit_built_transaction_rpc",
                        lambda *_a, **_k: pytest.fail("preview attempted submission"))
    return state
