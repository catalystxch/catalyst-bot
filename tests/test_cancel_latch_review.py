"""Exact, read-only two-blocker recovery review and final CAS tests."""

import json
from types import SimpleNamespace

import cancel_latch_review
import api_server
import mutation_gate


def _install_proven_review(monkeypatch):
    trade_ids = ("a" * 64, "b" * 64)
    operation_ids = [f"cancel:{trade_id}" for trade_id in trade_ids]
    fingerprint = 3702373391
    wallet_hash = mutation_gate.wallet_fingerprint_hash(fingerprint)
    runtime = SimpleNamespace(
        wallet_fingerprint_hash=wallet_hash,
        network="mainnet",
        status=lambda: SimpleNamespace(
            to_dict=lambda: {
                "allowed": False,
                "latch_generation": 154,
                "blocking_operation_ids": operation_ids,
                "blocking_operation_count": 2,
            }
        ),
    )
    monkeypatch.setattr(
        cancel_latch_review.mutation_gate, "current_runtime", lambda: runtime
    )
    monkeypatch.setattr(
        cancel_latch_review.database,
        "get_runtime_safety_latch",
        lambda: {
            "state": "tripped",
            "generation": 154,
            "blocking_operation_ids_json": json.dumps(operation_ids),
            "wallet_fingerprint_hash": wallet_hash,
            "network": "mainnet",
        },
    )
    monkeypatch.setattr(cancel_latch_review.wallet, "get_wallet_type", lambda: "sage")
    monkeypatch.setattr(
        cancel_latch_review.wallet,
        "get_wallet_identity",
        lambda: {
            "success": True,
            "backend": "sage",
            "fingerprint": fingerprint,
            "network_id": "mainnet",
        },
    )
    monkeypatch.setattr(
        cancel_latch_review.wallet, "get_pending_transactions", lambda: []
    )
    monkeypatch.setattr(
        cancel_latch_review.wallet,
        "get_authoritative_offers_by_ids",
        lambda ids: {
            "complete": True,
            "requested_ids": list(ids),
            "offers": [{"trade_id": trade_id, "status": 3} for trade_id in ids],
        },
    )
    monkeypatch.setattr(
        cancel_latch_review.database,
        "get_authoritative_terminal_records",
        lambda ids: {
            trade_id: {
                "sage_trade_id": trade_id,
                "intent_id": f"intent:{trade_id}",
                "outcome": "CANCELLED_PROVEN",
                "terminal_state": "cancelled",
                "evidence_sha256": "c" * 64,
            }
            for trade_id in ids
        },
    )
    monkeypatch.setattr(
        cancel_latch_review.OfferManager,
        "_canonical_cancel_intent",
        lambda trade_id: SimpleNamespace(
            trade_id=trade_id,
            intent_id=f"intent:{trade_id}",
            operation_id=f"cancel:{trade_id}",
        ),
    )
    monkeypatch.setattr(
        cancel_latch_review.OfferManager,
        "_read_existing_cancel_result",
        lambda intent: SimpleNamespace(
            authoritative=True, result={"outcome": "CANCEL_CONFIRMED"}
        ),
    )
    return runtime


def test_two_cancel_blockers_require_exact_terminal_wallet_and_pending_proof(
    monkeypatch,
):
    _install_proven_review(monkeypatch)
    bot = SimpleNamespace(is_running=lambda: False)
    ready = cancel_latch_review.review(bot=bot)
    assert ready["ready"] is True
    assert ready["generation"] == 154
    assert len(ready["proofs"]) == 2

    monkeypatch.setattr(
        cancel_latch_review.wallet, "get_pending_transactions", lambda: [{}]
    )
    assert cancel_latch_review.review(bot=bot)["ready"] is False
    monkeypatch.setattr(
        cancel_latch_review.wallet, "get_pending_transactions", lambda: []
    )
    monkeypatch.setattr(
        cancel_latch_review.wallet,
        "get_authoritative_offers_by_ids",
        lambda ids: {
            "complete": True,
            "requested_ids": list(ids),
            "offers": [
                {"trade_id": ids[0], "status": 3},
                {"trade_id": ids[1], "status": 1},
            ],
        },
    )
    assert (
        cancel_latch_review.review(bot=bot)["reason_code"]
        == "CANCELLATION_PROOF_INCOMPLETE"
    )


def test_review_rejects_running_bot_and_wrong_wallet(monkeypatch):
    _install_proven_review(monkeypatch)
    assert (
        cancel_latch_review.review(bot=SimpleNamespace(is_running=lambda: True))[
            "reason_code"
        ]
        == "BOT_RUNNING"
    )
    monkeypatch.setattr(
        cancel_latch_review.wallet,
        "get_wallet_identity",
        lambda: {
            "success": True,
            "backend": "sage",
            "fingerprint": 1173457134,
            "network_id": "mainnet",
        },
    )
    assert (
        cancel_latch_review.review(bot=SimpleNamespace(is_running=lambda: False))[
            "reason_code"
        ]
        == "WALLET_BINDING_MISMATCH"
    )


def test_final_click_rechecks_proof_and_cannot_release_stale_review(monkeypatch):
    runtime = _install_proven_review(monkeypatch)
    released = []
    runtime.release_resolved = lambda generation, ids: (
        released.append((generation, ids)) or {"released": True}
    )
    monkeypatch.setattr(api_server.mutation_gate, "current_runtime", lambda: runtime)
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(is_running=lambda: False))
    ready = cancel_latch_review.review(bot=api_server.bot)
    body = {
        "expected_generation": ready["generation"],
        "review_digest": ready["review_digest"],
    }

    with api_server.app.test_request_context(
        "/api/safety/confirm-cancel-latch-review", method="POST", json=body
    ):
        response = api_server.api_safety_confirm_cancel_latch_review()
    assert response.json["released"] is True
    assert released == [(154, ready["operation_ids"])]

    monkeypatch.setattr(
        cancel_latch_review.wallet, "get_pending_transactions", lambda: None
    )
    with api_server.app.test_request_context(
        "/api/safety/confirm-cancel-latch-review", method="POST", json=body
    ):
        response, code = api_server.api_safety_confirm_cancel_latch_review()
    assert code == 409
    assert response.json["reason_code"] == "REVIEW_STALE_OR_INCOMPLETE"
    assert len(released) == 1
