"""Coin-prep-attributable cancellations use exact protected fee consent."""

from importlib import import_module
import hashlib
import json

import pytest

import database
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401


@pytest.fixture(autouse=True)
def current_database_module():
    global database
    database = import_module("database")


def _price(state):
    service = import_module("coin_prep_fee_cancellation")
    return service.price_approved_cancellation(
        approval_id=state["approval"]["approval_id"],
        trade_ids=["a" * 64, "b" * 64],
        source_coin_ids=["c" * 64, "d" * 64],
        fee_coin_id="e" * 64,
    )


def _builder(monkeypatch, state, *, cost=123_456):
    calls = []

    def build(trade_ids, *, fee_mojos, source_coin_ids, fee_coin_id):
        calls.append(fee_mojos)
        return {
            "summary": {"fee": fee_mojos, "inputs": []},
            "coin_spends": ["sealed"],
            "_catalyst_validated_cancel_unsigned": True,
            "_catalyst_exact_unsigned_cost": cost,
            "_catalyst_cancel_unsigned_digest": "f" * 64,
        }

    wallet = import_module("wallet")
    monkeypatch.setattr(wallet, "build_cancel_offers_batch_unsigned", build)
    return calls


def _quote(monkeypatch, state, fee):
    pricing = import_module("coin_prep_fee_cancellation")
    monkeypatch.setattr(
        pricing,
        "quote_fee",
        lambda cost, target_seconds: {
            "available": True,
            "fee_mojos": fee,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": state["now"],
            "expires_at": state["now"] + 60,
        },
    )


def test_cancellation_price_converges_on_actual_unsigned_cost_without_dispatch(
    approved, monkeypatch
):
    calls = _builder(monkeypatch, approved)
    _quote(monkeypatch, approved, 20)

    result = _price(approved)

    assert result["available"] is True
    assert result["fee_mojos"] == 20
    assert result["cost"] == 123_456
    assert result["quote"]["source"] == "coinset"
    assert result["validated_unsigned"]["_catalyst_validated_cancel_unsigned"] is True
    assert result["dispatch_authorized"] is False
    assert calls == [0, 20]
    assert database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )["reservation_count"] == 0


def test_cancellation_price_preserves_available_zero_fee_without_extra_build(
    approved, monkeypatch
):
    calls = _builder(monkeypatch, approved)
    _quote(monkeypatch, approved, 0)

    result = _price(approved)

    assert result["available"] is True
    assert result["fee_mojos"] == 0
    assert result["quote"]["source"] == "coinset"
    assert calls == [0]


def test_cancellation_price_cannot_exceed_remaining_total_budget(approved, monkeypatch):
    calls = _builder(monkeypatch, approved)
    _quote(monkeypatch, approved, 81)

    result = _price(approved)

    assert result["available"] is False
    assert result["reason"] == "FEE_BUDGET_EXCEEDED"
    assert result["required_fee_mojos"] == 81
    assert calls == [0, 81]


def test_cancellation_price_fails_closed_when_guidance_is_unavailable(
    approved, monkeypatch
):
    calls = _builder(monkeypatch, approved)
    pricing = import_module("coin_prep_fee_cancellation")
    monkeypatch.setattr(
        pricing,
        "quote_fee",
        lambda *_args, **_kwargs: {"available": False, "reason": "provider down"},
    )

    result = _price(approved)

    assert result["available"] is False
    assert result["reason"] == "FEE_ESTIMATE_UNAVAILABLE"
    assert calls == [0]


def test_context_change_during_cancellation_pricing_invalidates_result(
    approved, monkeypatch
):
    _builder(monkeypatch, approved)
    pricing = import_module("coin_prep_fee_cancellation")

    def change_then_quote(cost, target_seconds):
        approved["config"].TRANSACTION_FEE_MODE = "auto"
        return {
            "available": True,
            "fee_mojos": 20,
            "source": "coinset",
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": approved["now"],
            "expires_at": approved["now"] + 60,
        }

    monkeypatch.setattr(pricing, "quote_fee", change_then_quote)

    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        _price(approved)


def _prepared_cancel_cohort(
    state, *, reason="coin_prep_cancel_all", fee=20, member_count=2
):
    members = [
        {
            "trade_id": trade_id,
            "operation_id": f"cancel:{trade_id}",
            "intent_id": f"cancel-target:{trade_id}",
            "attempt": 1,
            "prepared_event_id": f"cancel:{trade_id}:attempt:1:prepared",
        }
        for trade_id in ("a" * 64, "b" * 64)[:member_count]
    ]
    manifest = database.canonical_offer_cancel_cohort_manifest(members)
    contract = {
        "protocol": "sage_native_cancel_offers_zero_plus_fee_v1",
        "trade_ids": [member["trade_id"] for member in manifest["members"]],
        "source_coin_ids": ["c" * 64, "d" * 64][:member_count],
        "fee_coin_id": "e" * 64,
        "fee_mojos": fee,
    }
    requests = []
    for member in manifest["members"]:
        requests.append(
            {
                "operation_id": member["operation_id"],
                "event_id": member["prepared_event_id"],
                "trade_id": member["trade_id"],
                "intent_id": member["intent_id"],
                "attempt": member["attempt"],
                "wallet_identity_json": {
                    "snapshot": {
                        "binding": {
                            "backend": "sage",
                            "fingerprint": 736588221,
                            "network_id": "mainnet",
                        }
                    }
                },
                "evidence_json": {
                    "trade_id": member["trade_id"],
                    "intent_id": member["intent_id"],
                    "operation_id": member["operation_id"],
                    "attempt": member["attempt"],
                    "cohort_id": manifest["cohort_id"],
                    "cohort_size": manifest["member_count"],
                    "member_id": member["member_id"],
                    "reason": reason,
                    "continuation_journal_sha256": "f" * 64,
                    "wallet_effect": {
                        "secure": True,
                        "timeout": 60,
                        "fee_mojos": fee,
                        "batch": {
                            key: value
                            for key, value in contract.items()
                            if key != "fee_mojos"
                        },
                    },
                    "effect_claim_protocol": "durable_cohort_claim_v1",
                },
            }
        )
    database.prepare_offer_cancel_cohort(
        manifest_json=manifest,
        member_requests_json=requests,
    )
    quote = {
        "available": True,
        "fee_mojos": fee,
        "source": "coinset",
        "cost": 123_456,
        "target_seconds": 300,
        "observed_at": state["now"],
        "expires_at": state["now"] + 60,
    }
    return manifest, contract, quote


def _reserve_cancel(state, manifest, contract, quote):
    account = state["approval"]
    return database.reserve_coin_prep_cancellation_fee(
        approval_id=account["approval_id"],
        scope_sha256=account["scope_sha256"],
        plan_sha256=account["plan_sha256"],
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=quote,
    )


def test_prepared_coin_prep_cancel_reserves_exact_protected_fee(approved):
    manifest, contract, quote = _prepared_cancel_cohort(approved)

    hold = _reserve_cancel(approved, manifest, contract, quote)

    expected_operation = hashlib.sha256(
        f"coin-prep-cancel:{manifest['cohort_id']}".encode("utf-8")
    ).hexdigest()
    assert hold["operation_id"] == expected_operation
    assert hold["fee_mojos"] == 20
    assert hold["cancellation"] == 1
    assert hold["dispatch_authorized"] is False


def test_unrelated_cancel_cannot_charge_coin_prep_approval(approved):
    manifest, contract, quote = _prepared_cancel_cohort(
        approved, reason="manual_cancel_all"
    )

    with pytest.raises(ValueError, match="FEE_CANCELLATION_SCOPE_INVALID"):
        _reserve_cancel(approved, manifest, contract, quote)

    assert database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )["reservation_count"] == 0


def test_cancel_reservation_rechecks_quote_after_database_lock(approved):
    manifest, contract, quote = _prepared_cancel_cohort(approved)
    approved["now"] = quote["expires_at"]

    with pytest.raises(ValueError, match="FEE_QUOTE_STALE"):
        _reserve_cancel(approved, manifest, contract, quote)


def test_cancel_reservation_replay_cannot_authorize_second_dispatch(approved):
    manifest, contract, quote = _prepared_cancel_cohort(approved)
    _reserve_cancel(approved, manifest, contract, quote)

    with pytest.raises(ValueError, match="FEE_OPERATION_REPLAY"):
        _reserve_cancel(approved, manifest, contract, quote)


def test_reserved_cancel_recheck_fails_closed_on_context_change(
    approved, monkeypatch
):
    _builder(monkeypatch, approved)
    _quote(monkeypatch, approved, 20)
    priced = _price(approved)
    manifest, _contract, _quote_value = _prepared_cancel_cohort(approved)
    service = import_module("coin_prep_fee_cancellation")
    service.reserve_approved_cancellation(
        approval_id=approved["approval"]["approval_id"],
        manifest=manifest,
        priced_cancellation=priced,
    )
    approved["config"].TRANSACTION_FEE_MODE = "auto"

    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        service.recheck_reserved_approved_cancellation(
            approval_id=approved["approval"]["approval_id"],
            manifest=manifest,
            priced_cancellation=priced,
        )


def _finalize_no_effect(manifest):
    outcomes = import_module("cancel_outcomes")
    result = outcomes.cancellation_result(
        outcomes.CANCEL_FAILED,
        method="protected_cancel_test",
        raw_response={"reason_code": "CONTINUATION_REFRESH_BLOCKED"},
        error="CANCEL_REJECTED",
    )
    for member in manifest["members"]:
        prepared = database.get_offer_operation_events(member["operation_id"])[0]
        database.finalize_offer_cancel(
            operation_id=member["operation_id"],
            event_id=f"{member['operation_id']}:attempt:1:finalized",
            trade_id=member["trade_id"],
            intent_id=member["intent_id"],
            attempt=1,
            cancel_result=result,
            wallet_identity_json=json.loads(prepared["wallet_identity_json"]),
            evidence_json={
                "trade_id": member["trade_id"],
                "attempt": 1,
                "cohort_id": manifest["cohort_id"],
                "member_id": member["member_id"],
                "effect_attempted": False,
                "cancel_result": result,
            },
            require_unclaimed=True,
        )


def _finalize_submitted(manifest, *, transaction_id="6" * 64):
    outcomes = import_module("cancel_outcomes")
    submitted = outcomes.cancellation_result(
        outcomes.CANCEL_SUBMITTED_UNCONFIRMED,
        method="sage_native_cancel_offers",
        raw_response={"success": True, "transaction_id": transaction_id},
        transaction_id=transaction_id,
    )
    database.claim_offer_cancel_cohort_effects(manifest_json=manifest)
    requests = []
    for member in manifest["members"]:
        prepared = database.get_offer_operation_events(member["operation_id"])[0]
        requests.append(
            {
                "operation_id": member["operation_id"],
                "event_id": f"{member['operation_id']}:attempt:1:finalized",
                "trade_id": member["trade_id"],
                "intent_id": member["intent_id"],
                "attempt": 1,
                "cancel_result": submitted,
                "wallet_identity_json": json.loads(prepared["wallet_identity_json"]),
                "evidence_json": {
                    "trade_id": member["trade_id"],
                    "attempt": 1,
                    "cohort_id": manifest["cohort_id"],
                    "member_id": member["member_id"],
                    "effect_attempted": True,
                    "cancel_result": submitted,
                },
            }
        )
    database.finalize_offer_cancel_cohort(
        manifest_json=manifest,
        member_requests_json=requests,
    )
    return transaction_id


def test_unattempted_protected_cancel_releases_hold_exactly_once(approved):
    manifest, contract, quote = _prepared_cancel_cohort(approved)
    hold = _reserve_cancel(approved, manifest, contract, quote)
    _finalize_no_effect(manifest)

    settled = database.record_coin_prep_cancellation_fee_outcome(manifest)
    replay = database.record_coin_prep_cancellation_fee_outcome(manifest)

    assert settled["operation_id"] == hold["operation_id"]
    assert settled["state"] == "RELEASED_NO_EFFECT"
    assert settled["idempotent"] is False
    assert replay == {**settled, "idempotent": True}
    status = database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )
    assert status["held_fee_mojos"] == 0
    assert status["spent_fee_mojos"] == 0


def test_protected_cancel_hold_cannot_release_before_authoritative_outcome(approved):
    manifest, contract, quote = _prepared_cancel_cohort(approved)
    _reserve_cancel(approved, manifest, contract, quote)

    with pytest.raises(ValueError, match="FEE_EFFECT_UNRESOLVED"):
        database.record_coin_prep_cancellation_fee_outcome(manifest)

    status = database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )
    assert status["held_fee_mojos"] == quote["fee_mojos"]


def test_authoritative_peer_rejection_releases_protected_hold(approved):
    manifest, contract, quote = _prepared_cancel_cohort(approved)
    _reserve_cancel(approved, manifest, contract, quote)
    transaction_id = _finalize_submitted(manifest)

    database.reconcile_rejected_offer_cancel_cohort(
        manifest_json=manifest,
        transaction_id=transaction_id,
        relay_evidence_json={
            "status": "rejected",
            "transaction_id": transaction_id,
            "reason_code": "INVALID_FEE_TOO_CLOSE_TO_ZERO",
            "evidence_sha256": "7" * 64,
            "source": "sage_native_log",
            "source_file": "app.log.2026-09-22",
        },
        wallet_fingerprint_hash="f" * 64,
        network="mainnet",
    )

    settled = database.record_coin_prep_cancellation_fee_outcome(manifest)
    assert settled["state"] == "RELEASED_NO_EFFECT"
    assert database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )["held_fee_mojos"] == 0


@pytest.mark.parametrize("member_count", [1, 2])
@pytest.mark.parametrize("fee", [0, 20])
def test_authoritative_confirmation_charges_hold_and_restart_scan_is_idempotent(
    approved,
    member_count,
    fee,
):
    manifest, contract, quote = _prepared_cancel_cohort(
        approved, member_count=member_count, fee=fee
    )
    _reserve_cancel(approved, manifest, contract, quote)
    transaction_id = _finalize_submitted(manifest)
    for member in manifest["members"]:
        finalized = database.get_offer_operation_events(member["operation_id"])[-1]
        database.append_offer_operation_event(
            event_id=f"{member['operation_id']}:attempt:1:reconciled",
            operation_id=member["operation_id"],
            intent_id=member["intent_id"],
            operation_type="CANCEL",
            attempt=1,
            phase="RECONCILED",
            outcome="CANCEL_CONFIRMED",
            request_timestamp="2026-09-22T12:00:00Z",
            wallet_identity_json=json.loads(finalized["wallet_identity_json"]),
            transaction_id=transaction_id,
            evidence_json={
                "trade_id": member["trade_id"],
                "cohort_id": manifest["cohort_id"],
                "member_id": member["member_id"],
                "effect_attempted": True,
                "authoritative_terminal_proof": True,
            },
            reason_code="AUTHORITATIVE_TERMINAL_PROOF",
            blocks_mutation=False,
            created_at="2026-09-22T12:00:00Z",
        )

    assert database.get_unsettled_coin_prep_cancellation_manifests() == [manifest]
    settled = database.record_coin_prep_cancellation_fee_outcome(manifest)
    assert settled["state"] == "CONFIRMED_SPENT"
    status = database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )
    assert status["held_fee_mojos"] == 0
    assert status["spent_fee_mojos"] == quote["fee_mojos"]
    assert database.get_unsettled_coin_prep_cancellation_manifests() == []
