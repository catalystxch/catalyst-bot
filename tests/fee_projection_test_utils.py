"""Standard-puzzle fixtures; no live wallet or signing dependencies."""

import json
from pathlib import Path

from chia_rs import AugSchemeMPL, Program


STANDARD_MOD_HEX = (
    "ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080"
)


def _python_tree(node):
    return node.atom if node.atom is not None else tuple(_python_tree(child) for child in node.pair)


def standard_puzzles():
    module = Program.fromhex(STANDARD_MOD_HEX)
    key = bytes(AugSchemeMPL.key_gen(b"test-only-fee-projection-key-00000").get_g1())
    # The published module itself is curried; uncurrying it strips its constants.
    _, module_node = Program.to(1).run_rust(10000, 0, module)
    native_tree = [2, (1, _python_tree(module_node)), [4, (1, key), 1]]
    native = Program.to(native_tree)
    raw = json.loads((Path(__file__).parent / "fixtures" / "coin_prep_unsigned_cat2.json").read_text())
    cat_module, _ = Program.fromhex(raw["coin_spends"][0]["puzzle_reveal"][2:]).uncurry_rust()
    cat = Program.to([2, (1, _python_tree(cat_module)),
                      [4, (1, bytes.fromhex("37bef360ee858133b69d595a906dc45d01af50379dad515eb9518abb7c1d2a7a")),
                       [4, (1, bytes.fromhex("36" * 32)),
                        [4, (1, native_tree), 1]]]])
    return native, cat
