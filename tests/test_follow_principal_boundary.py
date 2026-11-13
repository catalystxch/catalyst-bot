from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import database
import mutation_gate
from decimal import Decimal
from follow_run_policy import FollowRunPolicy


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    original_path = database.DB_PATH
    original_initialized_path = database._db_initialized_path
    database.close_connection()
    database.DB_PATH = str(tmp_path / "principal.db")
    database._db_initialized_path = ""
    try:
        yield
    finally:
        database.close_connection()
        database.DB_PATH = original_path
        database._db_initialized_path = original_initialized_path


def make_policy(**changes):
    terms = dict(
        wallet_fingerprint="12345", network="mainnet", asset_id="a" * 64,
        buy_target=100, sell_target=100,
        price_anchor=Decimal("0.0123"), price_min=Decimal("0.011"),
        price_max=Decimal("0.013"), maximum_fee_mojos_per_tx=2_000_000,
        fee_coin_principal_mojos=8_000_000_000, xch_reserve_mojos=1_000_000_000,
        cat_reserve_atoms=25_000, maximum_trade_xch_mojos=2_000_000_000_000,
        maximum_trade_cat_atoms=1_000_000,
    )
    terms.update(changes)
    return FollowRunPolicy(**terms)


FOLLOW_RUN = 'f' * 64


def prepare(label, policy, side='buy', amount=60, digest=True, **changes):
    values = dict(
        intent_id=label, operation_id='create:' + label, event_id='event:' + label,
        run_id='runtime:' + label,
        wallet_fingerprint_hash=mutation_gate.wallet_fingerprint_hash(int(policy.wallet_fingerprint)),
        network=policy.network, asset_id=policy.asset_id, side=side, tier='inner',
        purpose=f'follow:{FOLLOW_RUN}:normal_lifecycle',
        offered_amount_atomic=str(amount), requested_amount_atomic='100',
        selected_coin_ids_json=[label.encode().hex().ljust(64, '0')],
        cat_decimals=3, prepared_at='2026-11-13T12:00:00.000000Z',
    )
    if digest:
        values['follow_policy_digest'] = policy.digest
    values.update(changes)
    return database.prepare_offer_intent(**values)


@pytest.mark.parametrize('side', ['buy', 'sell'])
def test_concurrent_follow_intents_share_signed_principal_cap(isolated_database, side):
    policy = make_policy(maximum_trade_xch_mojos=100, maximum_trade_cat_atoms=100)
    database.init_database()
    database.record_active_follow_run_policy(policy)
    barrier = Barrier(2)

    def attempt(label):
        barrier.wait()
        try:
            prepare(label, policy, side)
            return 'prepared'
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ['first', 'second']))
    assert sorted(outcomes) == ['FOLLOW_PRINCIPAL_CAP_EXCEEDED', 'prepared']


def test_follow_principal_retry_and_terminal_release(isolated_database):
    policy = make_policy(maximum_trade_xch_mojos=100)
    database.init_database()
    database.record_active_follow_run_policy(policy)
    prepare('first', policy)
    prepare('first', policy)
    with pytest.raises(ValueError, match='FOLLOW_PRINCIPAL_CAP_EXCEEDED'):
        prepare('second', policy)
    # A terminal creation failure releases principal without wallet effects.
    database.get_connection().execute(
        "UPDATE offer_intents SET lifecycle_state='creation_failed' WHERE intent_id='first'"
    )
    database.get_connection().commit()
    prepare('second', policy)


@pytest.mark.parametrize('changes', [
    {'digest': False}, {'follow_policy_digest': 'a' * 64},
    {'network': 'testnet'}, {'wallet_fingerprint_hash': '0' * 64},
    {'asset_id': '0' * 64},
])
def test_active_policy_cannot_be_bypassed(isolated_database, changes):
    policy = make_policy()
    database.init_database()
    database.record_active_follow_run_policy(policy)
    with pytest.raises(ValueError, match='FOLLOW_RUN_POLICY_'):
        prepare('first', policy, **changes)


def test_legacy_follow_without_policy_still_prepares(isolated_database):
    database.init_database()
    prepare('first', make_policy(), digest=False)




def test_both_classifications_share_cap_and_sides_have_independent_caps(isolated_database):
    policy = make_policy(maximum_trade_xch_mojos=100, maximum_trade_cat_atoms=100)
    database.init_database()
    database.record_active_follow_run_policy(policy)
    prepare('first', policy)
    prepare('sell', policy, side='sell', amount=100)
    prepare('book', policy, amount=40, purpose=f'follow:{FOLLOW_RUN}:book_opportunity')
    with pytest.raises(ValueError, match='FOLLOW_PRINCIPAL_CAP_EXCEEDED'):
        prepare('overflow', policy, amount=1)


def test_cap_uses_exact_atoms_above_sqlite_integer_range(isolated_database):
    cap = 2 ** 100
    policy = make_policy(maximum_trade_xch_mojos=cap)
    database.init_database()
    database.record_active_follow_run_policy(policy)
    prepare('first', policy, amount=cap - 1)
    prepare('second', policy, amount=1)
    with pytest.raises(ValueError, match='FOLLOW_PRINCIPAL_CAP_EXCEEDED'):
        prepare('third', policy, amount=1)


def test_malformed_policy_cannot_fall_back_to_legacy(isolated_database):
    database.init_database()
    database.set_setting(database._ACTIVE_FOLLOW_RUN_POLICY_SETTING, '{')
    with pytest.raises(ValueError, match='FOLLOW_RUN_POLICY_REQUIRED'):
        prepare('first', make_policy(), digest=False)

def test_alternate_session_cannot_reset_aggregate_principal(isolated_database):
    policy = make_policy(maximum_trade_xch_mojos=100)
    database.init_database()
    database.record_active_follow_run_policy(policy)
    prepare('first', policy)
    with pytest.raises(ValueError, match='FOLLOW_PRINCIPAL_CAP_EXCEEDED'):
        prepare('second', policy, purpose=f"follow:{'e' * 64}:normal_lifecycle")
