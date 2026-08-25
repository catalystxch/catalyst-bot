"""Regression coverage for runtime top-up Task 12 reconciliation."""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import coin_manager
import mutation_gate
import replacement_capacity


SOURCE = "01" * 32
MISFIT = "02" * 32
TARGET = "11" * 32
CHANGE = "22" * 32


def _identity() -> dict:
    binding = mutation_gate.WalletIdentityBinding(
        backend="sage",
        name="TEST 7",
        fingerprint=736588221,
        network_id="mainnet",
        kind="bls",
        has_secrets=True,
        bound_at_utc="2026-08-22T19:59:59.000000Z",
        maximum_age_seconds=15,
    )
    return mutation_gate.wallet_identity_binding_payload(binding)


def _prep_contract() -> dict:
    return {
        "operation_kind": "split",
        "purpose": "replacement",
        "target_contract": {
            "wallet_type": "cat",
            "outputs": [
                {
                    "output_index": 0,
                    "amount_mojos": 100,
                    "purpose": "replacement",
                },
                {
                    "output_index": 1,
                    "amount_mojos": 400,
                    "purpose": "top_up",
                },
            ],
        },
        "pre_view_coin_ids": [SOURCE],
    }


def test_runtime_topup_persists_prepared_before_dispatch(monkeypatch):
    """A live top-up must become recoverable before Sage receives the spend."""

    events = []
    identity = _identity()

    def claim(**kwargs):
        events.append(("claim", kwargs))
        return {"claim_token": "a" * 64, "generation": 1}

    def prepare(**kwargs):
        events.append(("prepare", kwargs))
        contract = replacement_capacity.canonical_coin_prep_contract(
            operation_kind=kwargs["operation_kind"],
            purpose=kwargs["purpose"],
            source_coin_ids=kwargs["source_coin_ids"],
            target_contract=kwargs["target_contract"],
        )
        return {
            "operation": {
                "operation_id": contract["operation_id"],
                "source_coin_ids_json": json.dumps(kwargs["source_coin_ids"]),
                "target_contract_json": json.dumps(kwargs["target_contract"]),
                "wallet_identity_json": json.dumps(kwargs["wallet_identity_json"]),
                "prepared_evidence_json": json.dumps(kwargs["evidence_json"]),
                "effect_claim_token": kwargs["effect_claim_token"],
                "effect_claim_generation": kwargs["effect_claim_generation"],
            }
        }

    def begin(*_args, **_kwargs):
        events.append(("begin", {}))
        return object()

    def callback():
        events.append(("adapter", {}))
        return {"transaction_id": "0xtx"}

    outcomes = []
    monkeypatch.setattr(coin_manager, "claim_wallet_effect", claim)
    monkeypatch.setattr(coin_manager, "prepare_coin_prep_operation", prepare)
    monkeypatch.setattr(
        coin_manager, "wallet_effect_claim_is_current", lambda *_a, **_k: True
    )
    monkeypatch.setattr(coin_manager, "begin_wallet_effect_dispatch", begin)
    monkeypatch.setattr(
        coin_manager, "wallet_effect_adapter_dispatch_authority", nullcontext
    )
    monkeypatch.setattr(
        coin_manager, "complete_wallet_effect_dispatch", lambda *_a, **_k: "SUBMITTED"
    )
    monkeypatch.setattr(
        coin_manager,
        "record_coin_prep_operation_outcome",
        lambda *a, **k: outcomes.append((a, k)),
    )
    monkeypatch.setattr(
        coin_manager, "_current_coin_prep_wallet_identity", lambda: identity
    )

    receipt = coin_manager._run_claimed_wallet_effect(
        "coin_manager.topup_split_sage",
        callback,
        source_coin_ids=[SOURCE],
        _prep_contract=_prep_contract(),
    )

    assert [event[0] for event in events] == ["claim", "prepare", "begin", "adapter"]
    assert events[0][1]["operation_id"].startswith("coin-prep:")
    assert receipt.operation["operation_id"] == events[0][1]["operation_id"]
    assert receipt.result == {"transaction_id": "0xtx"}
    assert receipt.dispatch_outcome == "SUBMITTED"
    assert outcomes[0][1]["outcome"] == "SUBMITTED_UNKNOWN"


def test_runtime_topup_confirmation_records_exact_new_outputs(monkeypatch):
    """A fresh complete post-view clears the submitted latch with exact outputs."""

    identity = _identity()
    operation = {
        "operation_id": "coin-prep:" + "b" * 64,
        "source_coin_ids_json": json.dumps([SOURCE]),
        "target_contract_json": json.dumps(_prep_contract()["target_contract"]),
        "wallet_identity_json": json.dumps(identity),
        "prepared_evidence_json": json.dumps({"pre_view_coin_ids": [SOURCE]}),
        "effect_claim_token": "a" * 64,
        "effect_claim_generation": 1,
    }
    receipt = coin_manager._PreparedWalletEffectReceipt(
        result={"transaction_id": "0xtx"},
        operation=operation,
        dispatch_outcome="SUBMITTED",
    )
    recorded = []
    observed = datetime(2026, 8, 22, 20, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(
        mutation_gate,
        "validate_wallet_identity",
        lambda *_a, **_k: {
            "allowed": True,
            "observed_at_utc": observed.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
        },
    )
    monkeypatch.setattr(
        coin_manager,
        "get_wallet_identity",
        lambda: {"success": True, "fingerprint": 736588221, "network_id": "mainnet"},
    )
    monkeypatch.setattr(
        coin_manager,
        "record_coin_prep_operation_outcome",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )

    manager = coin_manager.CoinManager.__new__(coin_manager.CoinManager)
    confirmed = manager._confirm_runtime_topup_prep(
        receipt,
        owned_map={"0x" + TARGET: 100, "0x" + CHANGE: 400},
    )

    assert confirmed is True
    args, kwargs = recorded[0]
    assert args == (operation["operation_id"],)
    assert kwargs["outcome"] == "CONFIRMED"
    evidence = kwargs["evidence_json"]
    assert evidence["source_coin_ids"] == [SOURCE]
    assert sorted(
        (item["coin_id"], item["amount_mojos"], item["purpose"])
        for item in evidence["expected_outputs"]
    ) == sorted(
        [
            (TARGET, 100, "replacement"),
            (CHANGE, 400, "top_up"),
        ]
    )
    assert evidence["authoritative_view"]["fresh"] is True
    assert evidence["authoritative_view"]["complete"] is True
    expected_expiry = observed + timedelta(seconds=identity["maximum_age_seconds"])
    assert evidence["authoritative_view"]["expires_at"] == expected_expiry.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def test_runtime_absorb_journals_and_confirms_exact_combined_output(monkeypatch):
    """A submitted live reserve absorption must resolve its own safety latch."""

    output = "33" * 32
    reserve_amount = 1_000
    misfit_amount = 200
    fee_mojos = 1
    pre_owned = {SOURCE: reserve_amount, MISFIT: misfit_amount, TARGET: 50}
    post_owned = {TARGET: 50, output: reserve_amount + misfit_amount - fee_mojos}
    inventory = {
        "reserve": [{"coin_id": "0x" + SOURCE, "coin": {"amount": reserve_amount}}],
        "small": [{"coin_id": "0x" + MISFIT, "coin": {"amount": misfit_amount}}],
        "inner": [],
        "mid": [],
        "outer": [],
        "extreme": [],
    }
    captured = {}
    confirmations = []
    receipt = coin_manager._PreparedWalletEffectReceipt(
        result={
            "success": True,
            "transaction_id": "0xabsorbtx",
            "coin_spends": [{}, {}],
        },
        operation={"operation_id": "coin-prep:" + "c" * 64},
        dispatch_outcome="SUBMITTED",
    )

    def claimed_effect(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return receipt

    manager = coin_manager.CoinManager.__new__(coin_manager.CoinManager)
    manager._recent_absorb_submissions = {}
    monkeypatch.setattr(coin_manager, "get_wallet_type", lambda: "sage")
    monkeypatch.setattr(
        coin_manager,
        "_get_free_coins_rpc",
        lambda _wallet_id: {
            "confirmed_records": inventory["reserve"] + inventory["small"]
        },
    )
    monkeypatch.setattr(coin_manager, "_run_claimed_wallet_effect", claimed_effect)
    monkeypatch.setattr(manager, "_get_coin_prep_headroom_multiplier", lambda: 1)
    monkeypatch.setattr(manager, "_tx_fee_mojos", lambda: fee_mojos)
    monkeypatch.setattr(
        manager, "_filter_out_protected_coin_ids", lambda coin_ids: coin_ids
    )
    owned_views = iter([pre_owned, post_owned])
    monkeypatch.setattr(
        manager,
        "_get_owned_coin_amount_map",
        lambda *_args, **_kwargs: next(owned_views),
    )
    monkeypatch.setattr(
        manager,
        "_confirm_runtime_topup_prep",
        lambda actual_receipt, *, owned_map: (
            confirmations.append((actual_receipt, owned_map)) or True
        ),
    )
    monkeypatch.setattr(manager, "_record_topup_pool_refund", lambda *_a, **_k: None)
    monkeypatch.setattr(coin_manager.time, "sleep", lambda *_a, **_k: None)

    submitted = manager._absorb_misfits_to_reserve(
        "XCH",
        1,
        inventory,
        {
            "inner": 500,
            "mid": 250,
            "outer": 125,
            "extreme": 60,
        },
        is_cat=False,
    )

    assert submitted is True
    assert captured["args"][0] == "coin_manager.absorb_sage"
    assert captured["kwargs"]["source_coin_ids"] == [
        "0x" + SOURCE,
        "0x" + MISFIT,
    ]
    assert captured["kwargs"]["_prep_contract"] == {
        "operation_kind": "combine",
        "purpose": "top_up",
        "target_contract": {
            "wallet_type": "xch",
            "outputs": [
                {
                    "output_index": 0,
                    "amount_mojos": reserve_amount + misfit_amount - fee_mojos,
                    "purpose": "top_up",
                }
            ],
        },
        "pre_view_coin_ids": sorted(pre_owned),
    }
    assert confirmations == [(receipt, post_owned)]
