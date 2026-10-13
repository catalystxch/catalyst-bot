"""Isolated SQL characterization, NOT a compiled Sage test or recovery tool.

Source: Sage v0.13.0 a98ca34b3f6f802c7070834ec914cab1995ca822,
coins.rs update_coin/unsynced_coins and puzzle_queue.rs kind=None fallback.
No filesystem, network, RPC, keys or live database access.
--require-retry intentionally fails against released semantics.
"""
import argparse
import hashlib
import json
import sqlite3

ASSET = 'b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105'
INNER = '57d46e4646727fc15530f79cf94b41048cade4642d6b7c89008c36ab082a2347'
OUTER = '25c64fb600509f0dfcc04e3cb5492c9ca72c63e5b80828981a7ee721df241f4d'
PARENT = '451b3f586b70fe01fb3afbb7e2247676e80dfe096faf6cbdd42e11c36865d6c1'
COIN = 'f80e20e4ab1f21815b9cd34bb64ae95ff11d83b2ea1dcb18be15c0e698c3c509'


def characterize(preserve_unknown=False):
    # Exact released SQL semantics, simplified columns only.
    db = sqlite3.connect(':memory:')
    db.executescript('''
      CREATE TABLE assets(id INTEGER, hash BLOB);
      CREATE TABLE p2_puzzles(id INTEGER, hash BLOB);
      CREATE TABLE coins(hash BLOB, asset_id INTEGER, p2_puzzle_id INTEGER,
                         spent_height INTEGER, is_children_synced INTEGER);
    ''')
    db.execute('INSERT INTO assets VALUES(0,?)', (bytes(32),))
    db.execute('INSERT INTO assets VALUES(40,?)', (bytes.fromhex(ASSET),))
    db.execute('INSERT INTO p2_puzzles VALUES(2,?)', (bytes.fromhex(INNER),))
    db.execute('INSERT INTO coins VALUES(?,NULL,NULL,NULL,0)', (bytes.fromhex(COIN),))
    queue = '''SELECT hash FROM coins WHERE asset_id IS NULL OR
               (spent_height IS NOT NULL AND is_children_synced=FALSE)'''
    assert len(db.execute(queue).fetchall()) == 1
    # puzzle_queue kind=None passes zero asset hash and OUTER as p2 hash.
    if not preserve_unknown:
        db.execute('''UPDATE coins SET
          asset_id=(SELECT id FROM assets WHERE hash=?),
          p2_puzzle_id=(SELECT id FROM p2_puzzles WHERE hash=?) WHERE hash=?''',
          (bytes(32), bytes.fromhex(OUTER), bytes.fromhex(COIN)))
    state = db.execute('SELECT asset_id,p2_puzzle_id FROM coins').fetchone()
    retryable = bool(db.execute(queue).fetchall())
    assert state == ((None, None) if preserve_unknown else (0, None))
    assert retryable is preserve_unknown
    assert not db.execute('SELECT hash FROM coins WHERE asset_id=40 AND p2_puzzle_id IS NOT NULL').fetchall()
    # Independently hand-fixed public literal name, not Dexie's dummy output.
    amount = 98276643
    encoded_amount = amount.to_bytes((amount.bit_length()+7)//8, 'big')
    assert hashlib.sha256(bytes.fromhex(PARENT+OUTER)+encoded_amount).hexdigest() == COIN
    if preserve_unknown:
        # Isolated successful retry boundary: only exact validated parent/asset
        # proof may register the asset, wallet inner puzzle and lineage.
        h = lambda value: hashlib.sha256(value).digest()
        atom = lambda value: h(b'\x01' + value)
        pair = lambda left, right: h(b'\x02' + left + right)
        nil, q = atom(b''), atom(b'\x01')
        mod = bytes.fromhex('37bef360ee858133b69d595a906dc45d01af50379dad515eb9518abb7c1d2a7a')
        args = q
        for arg in reversed([atom(mod), atom(bytes.fromhex(ASSET)), bytes.fromhex(INNER)]):
            args = pair(atom(b'\x04'), pair(pair(q, arg), pair(args, nil)))
        assert pair(atom(b'\x02'), pair(pair(q, mod), pair(args, nil))).hex() == OUTER
        db.execute('CREATE TABLE lineage(coin_hash BLOB, parent_hash BLOB)')
        db.execute('UPDATE coins SET asset_id=40,p2_puzzle_id=2 WHERE hash=?', (bytes.fromhex(COIN),))
        db.execute('INSERT INTO lineage VALUES(?,?)', (bytes.fromhex(COIN), bytes.fromhex(PARENT)))
        assert db.execute('SELECT asset_id,p2_puzzle_id FROM coins').fetchone() == (40, 2)
        assert db.execute('SELECT COUNT(*) FROM lineage').fetchone()[0] == 1
        assert not db.execute(queue).fetchall()
    db.close()
    return {'source':'Sage v0.13.0 released SQL semantics', 'receive_coin':COIN,
            'asset_id_after_fallback':state[0], 'p2_id_after_fallback':state[1],
            'queued_for_retry':retryable, 'owned_cat_visible_after_retry':preserve_unknown,
            'compiled_rust_executed':False, 'live_state_touched':False,
            'isolated_validated_binding_after_retry':preserve_unknown,
            'lineage_limit':'parent ID association only; full parent CLVM lineage execution not tested'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-retry', action='store_true')
    parser.add_argument('--preserve-unknown', action='store_true')
    args = parser.parse_args()
    result = characterize(args.preserve_unknown)
    print(json.dumps(result))
    if args.require_retry:
        assert result['queued_for_retry'], 'REGRESSION: missing parent evidence must remain retryable'
