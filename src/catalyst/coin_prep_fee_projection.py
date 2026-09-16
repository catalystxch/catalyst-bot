"""Read-only CLVM cost projections for explicitly bounded standard profiles.

Synthetic coins are used only to price future stages whose real inputs do not
exist yet. This is not an unsigned transaction or an authorization: dispatch
must independently inspect and price the real wallet-built transaction.
"""

from hashlib import sha256

from chia_rs import Coin, CoinSpend, G1Element, Program

import wallet


_STANDARD_HASH = bytes.fromhex("e9aaa49f45bad5c889b86ee3341550c155cfdd10c3a6757de618d20612fffd52")
_CAT_HASH = bytes.fromhex("37bef360ee858133b69d595a906dc45d01af50379dad515eb9518abb7c1d2a7a")
_MAX_AMOUNT = (1 << 63) - 1
_ASSUMPTIONS = ["standard_p2_cat2_only", "max_width_atomic_amounts",
                "one_32_byte_output_hint", "all_input_concurrent_spend_mesh",
                "linked_cat_ring_max_width_subtotals"]


def _tree(node, depth=0, budget=None):
    if budget is None:
        budget = [10000]
    budget[0] -= 1
    if depth > 256 or budget[0] < 0:
        raise ValueError("puzzle exceeds projection bounds")
    if node.atom is not None:
        return node.atom
    return tuple(_tree(child, depth + 1, budget) for child in node.pair)


def _arguments(node, count):
    arguments = []
    for _ in range(count):
        if node.pair is None:
            raise ValueError("missing curried argument")
        item, node = node.pair
        arguments.append(item)
    if node.atom != b"":
        raise ValueError("extra curried argument")
    return arguments


def _standard(puzzle):
    if not isinstance(puzzle, Program) or len(bytes(puzzle)) > 65536:
        raise ValueError("unsupported standard puzzle")
    module, args = puzzle.uncurry_rust()
    if bytes(Program.to(_tree(module)).get_tree_hash()) != _STANDARD_HASH:
        raise ValueError("unsupported standard module")
    key = _arguments(args, 1)[0].atom
    if key is None or len(key) != 48:
        raise ValueError("unsupported standard key")
    G1Element.from_bytes(key)
    return puzzle


def _cat_inner(puzzle):
    if not isinstance(puzzle, Program) or len(bytes(puzzle)) > 65536:
        raise ValueError("unsupported CAT puzzle")
    module, args = puzzle.uncurry_rust()
    if bytes(Program.to(_tree(module)).get_tree_hash()) != _CAT_HASH:
        raise ValueError("unsupported CAT module")
    module_hash, asset, inner = _arguments(args, 3)
    if module_hash.atom != _CAT_HASH or asset.atom is None or len(asset.atom) != 32:
        raise ValueError("unsupported CAT arguments")
    return _standard(Program.to(_tree(inner)))


def _tag(label):
    return sha256(label.encode("ascii")).digest()


def _unavailable(reason):
    return {"available": False, "cost": None, "cost_kind": "projected",
            "dispatch_authorized": False, "reason": reason}


def project_standard_cost(*, native_puzzle, cat_puzzle=None, xch_inputs,
                          cat_inputs, xch_outputs, native_ephemeral_outputs=0):
    """Execute a conservative, disclosed profile, never a flat fee guess.

    This envelope covers the standard delegated-condition shape represented
    here, not arbitrary delegated programs, extra memos or wallet extensions.
    Such changes require a new profile or an exact unsigned cost.
    """
    counts = (xch_inputs, cat_inputs, xch_outputs, native_ephemeral_outputs)
    if (any(type(value) is not int for value in counts)
            or not 1 <= xch_inputs <= 50 or not 0 <= cat_inputs <= 50
            or not 1 <= xch_outputs <= 128 or xch_outputs + cat_inputs > 128
            or not 0 <= native_ephemeral_outputs <= xch_outputs):
        raise ValueError("FEE_PROJECTION_PROFILE_INVALID")
    try:
        _standard(native_puzzle)
        inner = _cat_inner(cat_puzzle) if cat_inputs else None
    except (ValueError, TypeError, AttributeError, RecursionError):
        return _unavailable("FEE_PROJECTION_PUZZLE_UNSUPPORTED")

    native_coins = [Coin(_tag(f"projected-native:{i}"), native_puzzle.get_tree_hash(),
                         _MAX_AMOUNT // xch_inputs - i) for i in range(xch_inputs)]
    cat_parents = [Coin(_tag(f"projected-cat-parent:{i}"), cat_puzzle.get_tree_hash(),
                        _MAX_AMOUNT // cat_inputs - i) for i in range(cat_inputs)]
    cat_coins = [Coin(parent.name(), cat_puzzle.get_tree_hash(), parent.amount)
                 for parent in cat_parents]
    roots = native_coins + cat_coins

    def mesh(coin):
        return [[64, other.name()] for other in roots if other != coin]

    native_total = sum(coin.amount for coin in native_coins)
    outputs = [[51, _tag(f"projected-native-output:{i}"),
                native_total // (xch_outputs + 1) - i, [_tag("projected-hint")]]
               for i in range(xch_outputs)]
    ephemerals = [Coin(native_coins[0].name(), native_puzzle.get_tree_hash(), outputs[i][2])
                  for i in range(native_ephemeral_outputs)]
    roots += ephemerals
    reserve_fee = native_total - sum(output[2] for output in outputs)
    spends = []
    for index, coin in enumerate(native_coins):
        conditions = mesh(coin)
        if index == 0:
            conditions += [[51, native_puzzle.get_tree_hash(), output[2], output[3]]
                           if i < native_ephemeral_outputs else output
                           for i, output in enumerate(outputs)] + [[52, reserve_fee]]
        solution = Program.to([[], (1, conditions), []])
        spends.append(CoinSpend(coin, native_puzzle, solution).to_json_dict())
    for index, coin in enumerate(ephemerals):
        solution = Program.to([[], (1, mesh(coin) + [outputs[index]]), []])
        spends.append(CoinSpend(coin, native_puzzle, solution).to_json_dict())
    subtotal = 0
    for index, (parent, coin) in enumerate(zip(cat_parents, cat_coins)):
        conditions = mesh(coin)
        if index == cat_inputs - 1:
            conditions += [[51, inner.get_tree_hash(), other.amount,
                            [_tag("projected-hint")]] for other in cat_coins]
        inner_solution = [[], (1, conditions), []]
        # Concentrated returns produce maximum-width nonzero ring subtotals;
        # independent conserving rings underestimate normal linked CAT spends.
        previous = cat_coins[(index - 1) % cat_inputs]
        next_coin = cat_coins[(index + 1) % cat_inputs]
        solution = Program.to([inner_solution,
                               [parent.parent_coin_info, inner.get_tree_hash(), parent.amount],
                               previous.name(),
                               [coin.parent_coin_info, coin.puzzle_hash, coin.amount],
                               [next_coin.parent_coin_info, inner.get_tree_hash(), next_coin.amount],
                               subtotal, 0])
        spends.append(CoinSpend(coin, cat_puzzle, solution).to_json_dict())
        subtotal += coin.amount
    try:
        cost = wallet.estimate_unsigned_transaction_cost({"coin_spends": spends})
    except (ValueError, TypeError, AttributeError, RuntimeError):
        return _unavailable("FEE_PROJECTION_COST_UNAVAILABLE")
    if type(cost) is not int or not 0 < cost <= 11_000_000_000:
        return _unavailable("FEE_PROJECTION_COST_UNAVAILABLE")
    return {"available": True, "cost": cost, "cost_kind": "projected",
            "dispatch_authorized": False, "input_count_max": xch_inputs + cat_inputs,
            "ephemeral_spend_count_max": native_ephemeral_outputs,
            "output_count_max": xch_outputs + cat_inputs,
            "assumptions": list(_ASSUMPTIONS) + (
                ["native_output_ephemeral_spends"] if native_ephemeral_outputs else [])}
