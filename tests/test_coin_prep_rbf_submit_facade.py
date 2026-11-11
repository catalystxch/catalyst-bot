"""The rescue facade seals its effect and fences Sage submission once."""

import json
from types import SimpleNamespace

import database
import wallet
import coin_prep_rbf_pricing


ATTEMPT = "a" * 64
OPERATION = "coin-prep:" + "b" * 64
ORIGINAL = "c" * 64
DIGEST = "d" * 64


def _fixture(monkeypatch, *, digest=DIGEST):
    outputs = [
        {
            "coin_id": f"{index:064x}",
            "amount_mojos": index + 1,
            "purpose": "fee_reserve" if index < 4 else "top_up",
        }
        for index in range(5)
    ]
    attempt = {
        "operation_id": OPERATION,
        "original_transaction_id": ORIGINAL,
        "unsigned_sha256": DIGEST,
        "latch_generation": 1,
        "fee_mojos": 20_000_000,
        "successor_outputs_json": json.dumps(outputs),
    }
    unsigned = {
        "_catalyst_executable_effect_bound": True,
        "_catalyst_unsigned_digest": digest,
        "_catalyst_exact_unsigned_cost": 42_000_000,
        "constructed_outputs": outputs,
    }
    monkeypatch.setattr(
        database, "get_coin_prep_rbf_attempt_for_submit", lambda _id: attempt
    )
    monkeypatch.setattr(
        database,
        "get_coin_prep_rbf_preview_authority",
        lambda _id: {"operation": {"source_coin_ids_json": json.dumps(["1" * 64])}},
    )
    monkeypatch.setattr(
        wallet,
        "preview_coin_prep_rbf_unsigned",
        lambda *_args: {"success": True, "unsigned": unsigned},
    )
    monkeypatch.setattr(
        coin_prep_rbf_pricing,
        "quote_required_replacement_fee",
        lambda _cost: {"available": True, "minimum_fee_mojos": 15_000_000},
    )
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    return unsigned


def test_seal_change_refuses_before_permit_or_sign(monkeypatch):
    _fixture(monkeypatch, digest="e" * 64)
    monkeypatch.setattr(
        wallet.mutation_gate,
        "enter_coin_prep_rbf_rescue_wallet_mutation",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("permit entered")),
    )
    monkeypatch.setattr(
        wallet,
        "_wallet_adapter",
        SimpleNamespace(submit_reviewed_coin_prep_rbf_rpc=lambda *_a, **_k: None),
    )
    result = wallet.submit_reviewed_coin_prep_rbf(ATTEMPT)
    assert result["success"] is False
    assert result["reason"] == "COIN_PREP_RBF_UNSIGNED_SEAL_CHANGED"


def test_one_shot_marker_precedes_sage_sign_and_uncertain_result_stays_attempted(
    monkeypatch,
):
    _fixture(monkeypatch)
    events = []
    quote_checks = []
    permit = object()
    adapter = SimpleNamespace()

    def fresh_quote(cost):
        quote_checks.append(cost)
        return {"available": True, "minimum_fee_mojos": 15_000_000}

    monkeypatch.setattr(
        coin_prep_rbf_pricing, "quote_required_replacement_fee", fresh_quote
    )

    def submit(_unsigned, *, _identity_recheck):
        events.append("sign")
        _identity_recheck("sign")
        _identity_recheck("rpc:submit_transaction:send")
        return {"success": False, "reason": "network_timeout"}

    adapter.submit_reviewed_coin_prep_rbf_rpc = submit
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_identity_from_adapter", lambda _adapter: {})
    monkeypatch.setattr(
        wallet,
        "get_pending_transactions_strict",
        lambda: [
            {
                "transaction_id": ORIGINAL,
                "fee": 0,
                "spent": [{"coin_id": "1" * 64}],
                "created": [],
            }
        ],
    )
    monkeypatch.setattr(
        wallet.mutation_gate,
        "enter_coin_prep_rbf_rescue_wallet_mutation",
        lambda **_kwargs: permit,
    )
    monkeypatch.setattr(
        wallet.mutation_gate,
        "require_fresh_coin_prep_rbf_rescue_wallet_continuation",
        lambda *_args, **_kwargs: (SimpleNamespace(backend="sage"), adapter, {}),
    )
    monkeypatch.setattr(
        wallet.mutation_gate,
        "wallet_mutation_permit_journal_authority",
        lambda *_args: {"owner_run_id": "run", "lease_version": 1},
    )
    monkeypatch.setattr(
        wallet.mutation_gate,
        "exit_wallet_mutation",
        lambda _permit: events.append("exit"),
    )
    monkeypatch.setattr(
        database,
        "record_coin_prep_rbf_sign_start",
        lambda *_args, **_kwargs: events.append("sign_intent"),
    )
    monkeypatch.setattr(
        database,
        "record_coin_prep_rbf_submit_start",
        lambda *_args, **_kwargs: events.append("submit_marker"),
    )
    monkeypatch.setattr(
        database,
        "record_coin_prep_rbf_sign_no_submit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no-submit receipt after submit marker")
        ),
    )
    result = wallet.submit_reviewed_coin_prep_rbf(ATTEMPT)
    assert result["success"] is False
    assert result["_catalyst_effect_attempted"] is True
    assert events == ["sign_intent", "sign", "submit_marker", "exit"]
    assert quote_checks == [42_000_000, 42_000_000]


def test_sign_refusal_records_no_submit_and_does_not_burn_submit_marker(monkeypatch):
    _fixture(monkeypatch)
    events = []
    adapter = SimpleNamespace(
        submit_reviewed_coin_prep_rbf_rpc=lambda _unsigned, **_kwargs: {
            "success": False,
            "reason": "RBF_SIGN_RESPONSE_INVALID",
        }
    )
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(wallet, "_identity_from_adapter", lambda _adapter: {})
    monkeypatch.setattr(
        wallet,
        "get_pending_transactions_strict",
        lambda: [
            {
                "transaction_id": ORIGINAL,
                "fee": 0,
                "spent": [{"coin_id": "1" * 64}],
                "created": [],
            }
        ],
    )
    monkeypatch.setattr(
        wallet.mutation_gate,
        "enter_coin_prep_rbf_rescue_wallet_mutation",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        wallet.mutation_gate,
        "require_fresh_coin_prep_rbf_rescue_wallet_continuation",
        lambda *_args, **_kwargs: (SimpleNamespace(backend="sage"), adapter, {}),
    )
    monkeypatch.setattr(
        wallet.mutation_gate,
        "wallet_mutation_permit_journal_authority",
        lambda *_args: {"owner_run_id": "run", "lease_version": 1},
    )
    monkeypatch.setattr(wallet.mutation_gate, "exit_wallet_mutation", lambda _p: None)
    monkeypatch.setattr(
        database,
        "record_coin_prep_rbf_sign_start",
        lambda *_a, **_k: events.append("sign_intent"),
    )
    monkeypatch.setattr(
        database,
        "record_coin_prep_rbf_submit_start",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("submit marker")),
    )

    def receipt(_attempt, *, receipt):
        assert receipt["reason_code"] == "SIGN_REFUSED"
        assert receipt["submit_rpc_attempted"] is False
        events.append("no_submit")

    monkeypatch.setattr(database, "record_coin_prep_rbf_sign_no_submit", receipt)
    result = wallet.submit_reviewed_coin_prep_rbf(ATTEMPT)
    assert result["_catalyst_effect_attempted"] is False
    assert events == ["sign_intent", "no_submit"]
