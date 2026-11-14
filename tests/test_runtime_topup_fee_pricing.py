"""Exact unsigned-cost pricing for live XCH fee-coin replenishment."""

from types import SimpleNamespace

import coin_manager
import coin_prep_fee_pricing
import fee_estimation
import wallet


SOURCE = "0x" + "a" * 64
ADDRESS = "xch1test-fee-reserve"


def _manager():
    return coin_manager.CoinManager.__new__(coin_manager.CoinManager)


def test_fee_reserve_quotes_executable_cost_and_seals_exact_outputs(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(manager, "_verified_topup_follow_fee_cap", lambda: None)
    built = []
    inspected = []
    quoted_costs = []

    def build(source_ids, actions):
        assert source_ids == [SOURCE]
        built.append(actions)
        return {"fee": int(actions[-1]["amount"])}

    def inspect(unsigned, contract):
        inspected.append(contract)
        assert contract["source_asset"] == "xch"
        assert contract["source_coin_ids"] == [SOURCE]
        assert contract["fee_coin_ids"] == []
        assert contract["fee_mojos"] == unsigned["fee"]
        assert [output["amount_mojos"] for output in contract["outputs"][:4]] == [
            100,
            100,
            100,
            100,
        ]
        assert all(output["address"] == ADDRESS for output in contract["outputs"])
        return {
            "_catalyst_validated_unsigned": True,
            "_catalyst_executable_effect_bound": True,
            "_catalyst_exact_unsigned_cost": 31_000_000,
            "sealed_fee": unsigned["fee"],
        }

    def quote(cost, *, target_seconds, force_refresh):
        quoted_costs.append((cost, target_seconds, force_refresh))
        return {"fee_mojos": 12}

    monkeypatch.setattr(wallet, "build_transaction_rpc", build)
    monkeypatch.setattr(wallet, "inspect_unsigned_transaction_effect", inspect)
    monkeypatch.setattr(
        wallet,
        "submit_built_transaction_rpc",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pricing submitted a transaction")
        ),
    )
    monkeypatch.setattr(fee_estimation, "quote_fee", quote)
    monkeypatch.setattr(
        coin_prep_fee_pricing, "is_current_fee_quote", lambda *_args: True
    )
    monkeypatch.setattr(
        coin_manager.cfg, "TRANSACTION_FEE_TARGET_SECS", 120, raising=False
    )

    priced = manager._price_sage_xch_fee_reserve_split(
        pre_owned_map={SOURCE: 600},
        source_coin_id=SOURCE,
        num_to_create=4,
        trading_size_mojos=100,
        address=ADDRESS,
    )

    assert priced["available"] is True, priced
    assert priced["fee_mojos"] == 12
    assert priced["validated_unsigned"]["sealed_fee"] == 12
    assert [actions[-1]["amount"] for actions in built] == ["1", "12"]
    assert [action["amount"] for action in built[-1][:-1]] == [
        "100",
        "100",
        "100",
        "100",
        "188",
    ]
    assert quoted_costs == [(31_000_000, 120, True)] * 2
    assert [output["amount_mojos"] for output in inspected[-1]["outputs"]] == [
        100,
        100,
        100,
        100,
        188,
    ]
    assert (
        priced["prep_contract"]["target_contract"]["outputs"][-1]["amount_mojos"] == 188
    )


def test_fee_reserve_refuses_unavailable_quote_before_wallet_effect(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(
        wallet, "build_transaction_rpc", lambda *_args: {"unsigned": True}
    )
    monkeypatch.setattr(
        wallet,
        "inspect_unsigned_transaction_effect",
        lambda *_args: {
            "_catalyst_executable_effect_bound": True,
            "_catalyst_exact_unsigned_cost": 31_000_000,
        },
    )
    monkeypatch.setattr(
        fee_estimation,
        "quote_fee",
        lambda *_args, **_kwargs: {"available": False},
    )
    monkeypatch.setattr(
        coin_prep_fee_pricing, "is_current_fee_quote", lambda *_args: False
    )
    priced = manager._price_sage_xch_fee_reserve_split(
        pre_owned_map={SOURCE: 600},
        source_coin_id=SOURCE,
        num_to_create=4,
        trading_size_mojos=100,
        address=ADDRESS,
    )
    assert priced == {"available": False, "reason": "FEE_ESTIMATE_UNAVAILABLE"}


def test_fee_reserve_submits_sealed_bundle_without_second_build(monkeypatch):
    manager = _manager()
    sealed = {
        "_catalyst_validated_unsigned": True,
        "_catalyst_exact_unsigned_cost": 31_000_000,
        "sealed_fee": 12,
    }
    quote = {"fee_mojos": 12}
    prep = {
        "operation_kind": "split",
        "purpose": "fee_reserve",
        "target_contract": {"wallet_type": "xch", "outputs": []},
        "pre_view_coin_ids": [SOURCE],
    }
    manager._recent_topup_split_submissions = {}
    manager._topup_split_chain_waits = {}
    manager._topup_spent_source_backoff_until = {}
    monkeypatch.setattr(manager, "_topup_should_stop", lambda: False)
    monkeypatch.setattr(manager, "_topup_split_source_key", lambda *_args: SOURCE)
    monkeypatch.setattr(manager, "_coinset_topup_split_state", lambda **_kwargs: None)
    monkeypatch.setattr(
        manager, "_get_owned_coin_amount_map", lambda *_args, **_kwargs: {SOURCE: 600}
    )
    monkeypatch.setattr(
        manager,
        "_price_sage_xch_fee_reserve_split",
        lambda **_kwargs: {
            "available": True,
            "fee_mojos": 12,
            "prep_contract": prep,
            "validated_unsigned": sealed,
            "quote": quote,
        },
    )
    monkeypatch.setattr(coin_manager.time, "time", lambda: 1000)
    monkeypatch.setattr(
        coin_manager.cfg, "TRANSACTION_FEE_TARGET_SECS", 120, raising=False
    )
    monkeypatch.setattr(
        coin_prep_fee_pricing,
        "is_current_fee_quote",
        lambda value, cost, target, *, now: (
            value is quote and cost == 31_000_000 and target == 120 and now == 1010
        ),
    )
    monkeypatch.setattr(
        coin_manager,
        "get_next_address",
        lambda **_kwargs: {"success": True, "address": ADDRESS},
    )
    monkeypatch.setattr(
        coin_manager.mutation_gate,
        "status",
        lambda: SimpleNamespace(allowed=True, reason_code=""),
    )
    monkeypatch.setattr(coin_manager, "log_event", lambda *_args, **_kwargs: None)
    submitted = []
    monkeypatch.setattr(
        wallet,
        "submit_built_transaction_rpc",
        lambda value: submitted.append(value) or {"transaction_id": "0xtx"},
    )
    monkeypatch.setattr(
        wallet,
        "build_transaction_rpc",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("submission rebuilt the unsigned effect")
        ),
    )
    monkeypatch.setattr(
        wallet,
        "sage_topup_split",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("submission used a second builder")
        ),
    )

    def run_claimed(_operation, callback, **kwargs):
        assert kwargs["fee_mojos"] == 12
        assert kwargs["_prep_contract"] is prep
        callback()
        return coin_manager._WALLET_EFFECT_DENIED

    monkeypatch.setattr(coin_manager, "_run_claimed_wallet_effect", run_claimed)
    assert (
        manager._sage_one_step_split(
            name="XCH-fees",
            wallet_id=1,
            source_coin_id=SOURCE,
            num_to_create=4,
            trading_size_mojos=100,
            is_cat=False,
        )
        is False
    )
    assert submitted == [sealed]


def test_fee_reserve_expired_quote_refuses_before_claim(monkeypatch):
    manager = _manager()
    manager._recent_topup_split_submissions = {}
    manager._topup_split_chain_waits = {}
    manager._topup_spent_source_backoff_until = {}
    monkeypatch.setattr(manager, "_topup_should_stop", lambda: False)
    monkeypatch.setattr(manager, "_topup_split_source_key", lambda *_args: SOURCE)
    monkeypatch.setattr(manager, "_coinset_topup_split_state", lambda **_kwargs: None)
    monkeypatch.setattr(
        manager, "_get_owned_coin_amount_map", lambda *_args, **_kwargs: {SOURCE: 600}
    )
    monkeypatch.setattr(
        manager,
        "_price_sage_xch_fee_reserve_split",
        lambda **_kwargs: {
            "available": True,
            "fee_mojos": 12,
            "prep_contract": {"purpose": "fee_reserve"},
            "validated_unsigned": {"_catalyst_exact_unsigned_cost": 31_000_000},
            "quote": {"fee_mojos": 12},
        },
    )
    monkeypatch.setattr(
        coin_manager,
        "get_next_address",
        lambda **_kwargs: {"success": True, "address": ADDRESS},
    )
    monkeypatch.setattr(
        coin_manager.mutation_gate,
        "status",
        lambda: SimpleNamespace(allowed=True, reason_code=""),
    )
    monkeypatch.setattr(coin_manager, "log_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(coin_manager.time, "time", lambda: 1000)
    monkeypatch.setattr(
        coin_manager.cfg, "TRANSACTION_FEE_TARGET_SECS", 120, raising=False
    )
    observed = []

    def stale_quote(value, cost, target, *, now):
        observed.append((value, cost, target, now))
        return False

    monkeypatch.setattr(coin_prep_fee_pricing, "is_current_fee_quote", stale_quote)
    monkeypatch.setattr(
        coin_manager,
        "_run_claimed_wallet_effect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale quote claimed a wallet effect")
        ),
    )
    monkeypatch.setattr(
        wallet,
        "submit_built_transaction_rpc",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale quote submitted a transaction")
        ),
    )
    assert (
        manager._sage_one_step_split(
            name="XCH-fees",
            wallet_id=1,
            source_coin_id=SOURCE,
            num_to_create=4,
            trading_size_mojos=100,
            is_cat=False,
        )
        is False
    )
    assert observed == [({"fee_mojos": 12}, 31_000_000, 120, 1010)]


def test_fee_reserve_unavailable_quote_never_claims_wallet_effect(monkeypatch):
    manager = _manager()
    manager._recent_topup_split_submissions = {}
    manager._topup_split_chain_waits = {}
    manager._topup_spent_source_backoff_until = {}
    monkeypatch.setattr(manager, "_topup_should_stop", lambda: False)
    monkeypatch.setattr(manager, "_topup_split_source_key", lambda *_args: SOURCE)
    monkeypatch.setattr(manager, "_coinset_topup_split_state", lambda **_kwargs: None)
    monkeypatch.setattr(
        manager, "_get_owned_coin_amount_map", lambda *_args, **_kwargs: {SOURCE: 600}
    )
    monkeypatch.setattr(
        manager,
        "_price_sage_xch_fee_reserve_split",
        lambda **_kwargs: {"available": False, "reason": "FEE_ESTIMATE_UNAVAILABLE"},
    )
    monkeypatch.setattr(
        coin_manager,
        "get_next_address",
        lambda **_kwargs: {"success": True, "address": ADDRESS},
    )
    monkeypatch.setattr(
        coin_manager.mutation_gate,
        "status",
        lambda: SimpleNamespace(allowed=True, reason_code=""),
    )
    monkeypatch.setattr(coin_manager, "log_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        coin_manager,
        "_run_claimed_wallet_effect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unpriced split claimed a wallet effect")
        ),
    )
    monkeypatch.setattr(
        wallet,
        "submit_built_transaction_rpc",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unpriced split submitted a transaction")
        ),
    )
    assert (
        manager._sage_one_step_split(
            name="XCH-fees",
            wallet_id=1,
            source_coin_id=SOURCE,
            num_to_create=4,
            trading_size_mojos=100,
            is_cat=False,
        )
        is False
    )
