"""Dedicated RBF submission must keep the sealed unsigned spend set exact."""

from __future__ import annotations

import hashlib
import json

import pytest

import mutation_gate
import wallet_sage


TX_ID = "a" * 64


def _spend(amount: int = 42) -> dict:
    return {
        "coin": {
            "parent_coin_info": "11" * 32,
            "puzzle_hash": "22" * 32,
            "amount": amount,
        },
        "puzzle_reveal": "80",
        "solution": "80",
    }


def _sealed_unsigned() -> dict:
    result = {
        "summary": {"fee": "10000000", "inputs": []},
        "coin_spends": [_spend()],
        "_catalyst_validated_unsigned": True,
        "_catalyst_executable_effect_bound": True,
    }
    result["_catalyst_unsigned_digest"] = hashlib.sha256(
        json.dumps(
            {"summary": result["summary"], "coin_spends": result["coin_spends"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return result


def test_rbf_signs_then_submits_only_same_coin_spends(monkeypatch):
    unsigned = _sealed_unsigned()
    calls = []
    checks = []

    def rpc(endpoint, payload, **kwargs):
        calls.append((endpoint, payload))
        assert callable(kwargs["_identity_recheck"])
        if endpoint == "sign_coin_spends":
            assert payload == {
                "coin_spends": unsigned["coin_spends"],
                "auto_submit": False,
                "partial": False,
            }
            return {
                "spend_bundle": {
                    "coin_spends": [
                        {
                            **_spend(),
                            "coin": {
                                **_spend()["coin"],
                                "parent_coin_info": "0x" + "11" * 32,
                            },
                        }
                    ],
                    "aggregated_signature": "00" * 96,
                }
            }
        assert endpoint == "submit_transaction"
        return {"success": True, "transaction_id": TX_ID}

    monkeypatch.setattr(wallet_sage, "_sage_post", rpc)
    monkeypatch.setattr(wallet_sage, "_spend_bundle_transaction_id", lambda _: TX_ID)
    result = wallet_sage.submit_reviewed_coin_prep_rbf_rpc(
        unsigned, _identity_recheck=checks.append
    )
    assert result["success"] is True
    assert result["transaction_id"] == TX_ID
    assert [endpoint for endpoint, _ in calls] == [
        "sign_coin_spends",
        "submit_transaction",
    ]
    assert checks == ["coin_prep_rbf_rescue:sign", "coin_prep_rbf_rescue:submit"]


def test_rbf_rejects_changed_signed_spend_before_submit(monkeypatch):
    calls = []

    def rpc(endpoint, payload, **_kwargs):
        calls.append(endpoint)
        return {
            "spend_bundle": {
                "coin_spends": [_spend(43)],
                "aggregated_signature": "00" * 96,
            }
        }

    monkeypatch.setattr(wallet_sage, "_sage_post", rpc)
    result = wallet_sage.submit_reviewed_coin_prep_rbf_rpc(_sealed_unsigned())
    assert result["reason"] == "RBF_SIGNED_SPENDS_MISMATCH"
    assert calls == ["sign_coin_spends"]


def test_rbf_rejects_tampered_seal_before_sign(monkeypatch):
    monkeypatch.setattr(
        wallet_sage,
        "_sage_post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no Sage RPC is allowed")
        ),
    )
    unsigned = _sealed_unsigned()
    unsigned["coin_spends"][0]["coin"]["amount"] = 43
    result = wallet_sage.submit_reviewed_coin_prep_rbf_rpc(unsigned)
    assert result["reason"] == "RBF_UNSIGNED_EFFECT_UNVERIFIED"
    assert result["_catalyst_effect_attempted"] is False


def test_rbf_rechecks_after_sign_and_blocks_submit(monkeypatch):
    calls = []

    def rpc(endpoint, payload, **_kwargs):
        calls.append(endpoint)
        return {
            "spend_bundle": {
                "coin_spends": [_spend()],
                "aggregated_signature": "00" * 96,
            }
        }

    def recheck(step):
        if step.endswith(":submit"):
            raise mutation_gate.MutationBlocked("COIN_PREP_RECOVERY_REQUIRED", step)

    monkeypatch.setattr(wallet_sage, "_sage_post", rpc)
    monkeypatch.setattr(wallet_sage, "_spend_bundle_transaction_id", lambda _: TX_ID)
    with pytest.raises(mutation_gate.MutationBlocked):
        wallet_sage.submit_reviewed_coin_prep_rbf_rpc(
            _sealed_unsigned(), _identity_recheck=recheck
        )
    assert calls == ["sign_coin_spends"]
