"""Bind executable CLVM effects to Sage's previously validated summary.

Uses only the bundled chia_rs and existing licensed Bech32m decoder. CAT2's
module identity and curry layout follow Chia's 2.5.7 reference cat_utils.py:
https://github.com/Chia-Network/chia-blockchain/blob/2.5.7/chia/wallet/cat_wallet/cat_utils.py
Unknown asset wrappers fail closed; no signing, RPC or database access occurs.
"""

from collections import Counter
from hashlib import sha256

from chia_rs import Coin

from sage_offer_wire import decode_wallet_puzzle_hash


CAT2_MOD_HASH = bytes.fromhex("37bef360ee858133b69d595a906dc45d01af50379dad515eb9518abb7c1d2a7a")


def _atom_hash(value: bytes) -> bytes:
    return sha256(b"\x01" + value).digest()


def _pair_hash(left: bytes, right: bytes) -> bytes:
    return sha256(b"\x02" + left + right).digest()


def _node_hash(node) -> bytes:
    if node.atom is not None:
        return _atom_hash(node.atom)
    left, right = node.pair
    return _pair_hash(_node_hash(left), _node_hash(right))


def _cat_puzzle_hash(asset_id: bytes, inner_hash: bytes) -> bytes:
    # Hash the canonical (a (q . MOD) (c (q . ARG) ... 1)) curry expression.
    nil, one = _atom_hash(b""), _atom_hash(b"\x01")
    environment = one
    for argument in reversed((_atom_hash(CAT2_MOD_HASH), _atom_hash(asset_id), inner_hash)):
        environment = _pair_hash(_atom_hash(b"\x04"), _pair_hash(
            _pair_hash(one, argument), _pair_hash(environment, nil)))
    return _pair_hash(_atom_hash(b"\x02"), _pair_hash(
        _pair_hash(one, CAT2_MOD_HASH), _pair_hash(environment, nil)))


def _cat_asset_id(program) -> bytes | None:
    module, arguments = program.uncurry_rust()
    if _node_hash(module) != CAT2_MOD_HASH:
        return None
    values = []
    while arguments.pair is not None:
        value, arguments = arguments.pair
        values.append(value)
        if len(values) > 3:
            raise ValueError("unexpected CAT arguments")
    if (arguments.atom != b"" or len(values) != 3
            or values[0].atom != CAT2_MOD_HASH
            or values[1].atom is None or len(values[1].atom) != 32):
        raise ValueError("malformed CAT identity")
    return values[1].atom


def executable_matches_summary(spends, conditions, summary: dict, exact_amount) -> bool:
    """Require every removal/addition, fee, asset and output address to agree."""
    try:
        inputs = summary["inputs"]
        by_id = {item["coin_id"].removeprefix("0x").lower(): item for item in inputs}
        actual = {spend.coin.name().hex(): spend for spend in spends}
        executed = {spend.coin_id.hex(): spend for spend in conditions.spends}
        if (len(by_id) != len(inputs) or len(actual) != len(spends)
                or len(executed) != len(conditions.spends)
                or set(by_id) != set(actual) or set(actual) != set(executed)):
            return False
        if (int(conditions.removal_amount) - int(conditions.addition_amount)
                != exact_amount(summary["fee"])):
            return False
        for coin_id, spend in actual.items():
            item = by_id[coin_id]
            if (spend.puzzle_reveal.get_tree_hash() != spend.coin.puzzle_hash
                    or int(spend.coin.amount) != exact_amount(item["amount"])):
                return False
            executable_asset = _cat_asset_id(spend.puzzle_reveal)
            asset = item.get("asset")
            summary_asset = None if asset is None or asset.get("asset_id") is None else bytes.fromhex(
                asset["asset_id"].removeprefix("0x"))
            if summary_asset != executable_asset:
                return False
            expected = Counter()
            for output in item["outputs"]:
                puzzle_hash = decode_wallet_puzzle_hash(output["address"])
                if executable_asset is not None:
                    puzzle_hash = _cat_puzzle_hash(executable_asset, puzzle_hash)
                amount = exact_amount(output["amount"])
                output_id = Coin(bytes.fromhex(coin_id), puzzle_hash, amount).name().hex()
                if output_id != output["coin_id"].removeprefix("0x").lower():
                    return False
                expected[(output_id, amount)] += 1
            additions = Counter((Coin(bytes.fromhex(coin_id), puzzle_hash, amount).name().hex(),
                                 int(amount))
                                for puzzle_hash, amount, _hint in executed[coin_id].create_coin)
            if expected != additions:
                return False
        return True
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return False
