"""Durable RBF review contains only checked, human-readable evidence."""

from __future__ import annotations

import hashlib
import json
import time

import coin_prep_rbf_review_service as service


OPERATION = "coin-prep:" + "3" * 64
TX = "2" * 64
DIGEST = "4" * 64
FEE = 16_000_000
RESERVE = 20_000_000_000
OLD_CHANGE = 1_435_390_971_590
COST = 41_891_752


def _output(index, amount, purpose, *, successor=False):
    return {
        "coin_id": f"{index + (10 if successor else 0):064x}",
        "amount_mojos": amount,
        "purpose": purpose,
    }


def _priced(*, expires=None):
    observed = int(time.time())
    expires = observed + 60 if expires is None else expires
    original = [
        _output(index, RESERVE, "fee_reserve") for index in range(4)
    ] + [_output(4, OLD_CHANGE, "top_up")]
    successor = [
        _output(index, RESERVE, "fee_reserve", successor=True)
        for index in range(4)
    ] + [_output(4, OLD_CHANGE - FEE, "top_up", successor=True)]
    return {
        "available": True,
        "fee_mojos": FEE,
        "cost": COST,
        "quote": {
            "available": True,
            "source": "coinset",
            "cost": COST,
            "target_seconds": 300,
            "fee_mojos": 15_000_000,
            "observed_at": observed,
            "expires_at": expires,
        },
        "preview": {
            "success": True,
            "operation_id": OPERATION,
            "original_transaction_id": TX,
            "fee_mojos": FEE,
            "original_outputs": original,
            "successor_outputs": successor,
            "unsigned": {
                "_catalyst_executable_effect_bound": True,
                "_catalyst_unsigned_digest": DIGEST,
                "_catalyst_exact_unsigned_cost": COST,
                "summary": {"secret": "must not reach review"},
                "coin_spends": [{"secret": "must not reach review"}],
            },
        },
    }


def _install(monkeypatch, priced):
    calls = []
    monkeypatch.setattr(
        service,
        "price_pending_coin_prep_replacement",
        lambda operation, tx: (
            calls.append(("price", operation, tx)) or priced
        ),
    )
    monkeypatch.setattr(
        service,
        "get_coin_prep_rbf_preview_authority",
        lambda operation: (
            calls.append(("authority", operation))
            or {"latch": {"generation": 7}}
        ),
    )

    def prepare(**kwargs):
        calls.append(("prepare", kwargs))
        return {
            "attempt": {
                "attempt_id": "a" * 64,
                "operation_id": kwargs["operation_id"],
                "unsigned_sha256": kwargs["unsigned_sha256"],
                "review_sha256": kwargs["review_sha256"],
            }
        }

    monkeypatch.setattr(service, "prepare_coin_prep_rbf_attempt", prepare)
    return calls


def test_review_seals_exact_fee_outputs_and_quote_expiry_without_unsigned(monkeypatch):
    priced = _priced()
    calls = _install(monkeypatch, priced)
    result = service.prepare_coin_prep_rbf_review(OPERATION, TX)
    assert result["available"] is True
    assert result["dispatch_authorized"] is False
    assert result["attempt_id"] == "a" * 64
    review = result["review"]
    assert review["fee_mojos"] == FEE
    assert review["fee_xch"] == "0.000016"
    assert review["cost"] == COST
    assert review["review_expires_at"] == service._timestamp(
        priced["quote"]["expires_at"]
    )
    assert review["unsigned_sha256"] == DIGEST
    assert "coin_spends" not in json.dumps(result)
    assert "must not reach review" not in json.dumps(result)
    assert result["review_sha256"] == hashlib.sha256(
        service._canonical_json(review).encode()
    ).hexdigest()
    assert calls[0] == ("price", OPERATION, TX)
    assert calls[-1][0] == "prepare"
    recorded = calls[-1][1]
    assert recorded["review_sha256"] == result["review_sha256"]
    assert recorded["review_expires_at"] == review["review_expires_at"]
    assert recorded["original_outputs"] == review["original_outputs"]
    assert recorded["successor_outputs"] == review["successor_outputs"]


def test_expired_quote_never_records_attempt(monkeypatch):
    calls = _install(monkeypatch, _priced(expires=int(time.time()) - 1))
    result = service.prepare_coin_prep_rbf_review(OPERATION, TX)
    assert result["available"] is False
    assert result["dispatch_authorized"] is False
    assert not any(call[0] == "prepare" for call in calls)


def test_changed_reserve_amount_never_records_attempt(monkeypatch):
    priced = _priced()
    priced["preview"]["successor_outputs"][0]["amount_mojos"] += 1
    calls = _install(monkeypatch, priced)
    result = service.prepare_coin_prep_rbf_review(OPERATION, TX)
    assert result["reason"] == "RBF_REVIEW_NOT_FEE_ONLY"
    assert not any(call[0] == "prepare" for call in calls)


def test_mismatched_preview_identity_never_records_attempt(monkeypatch):
    priced = _priced()
    priced["preview"]["original_transaction_id"] = "9" * 64
    calls = _install(monkeypatch, priced)
    result = service.prepare_coin_prep_rbf_review(OPERATION, TX)
    assert result["reason"] == "RBF_REVIEW_PREVIEW_MISMATCH"
    assert not any(call[0] == "prepare" for call in calls)
