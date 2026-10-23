"""Read-only, exact proof for a native cancellation-latch review.

This module never releases a latch or calls a wallet mutation.  The caller
must repeat the review immediately before the existing durable release CAS.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import database
import mutation_gate
import wallet
from cancel_outcomes import CANCEL_CONFIRMED
from offer_manager import OfferManager


_CANCELLED_SAGE_STATUSES = frozenset({3, "cancelled", "canceled"})


def _not_ready(reason: str) -> dict[str, Any]:
    return {
        "ready": False,
        "reason_code": reason,
        "generation": None,
        "operation_ids": [],
        "proofs": [],
        "review_digest": None,
        "scope_digest": None,
    }


def review(*, bot: Any = None) -> dict[str, Any]:
    """Prove every blocker is the same durably cancelled Sage offer.

    An incomplete RPC, wrong wallet, pending transaction, active bot, or
    non-cancel blocker leaves the latch untouched and the review unavailable.
    """

    runtime = mutation_gate.current_runtime()
    if runtime is None:
        return _not_ready("RUNTIME_NOT_INITIALIZED")
    try:
        if bot is not None and bot.is_running():
            return _not_ready("BOT_RUNNING")
        if wallet.get_wallet_type() != "sage":
            return _not_ready("SAGE_REQUIRED")
        latch = database.get_runtime_safety_latch()
        generation = latch.get("generation")
        operation_ids = json.loads(latch.get("blocking_operation_ids_json", ""))
        if (
            latch.get("state") != "tripped"
            or type(generation) is not int
            or generation < 1
            or type(operation_ids) is not list
            or not 1 <= len(operation_ids) <= 32
            or len(set(operation_ids)) != len(operation_ids)
            or any(
                type(operation_id) is not str
                or re.fullmatch(r"cancel:[0-9a-f]{64}", operation_id) is None
                for operation_id in operation_ids
            )
        ):
            return _not_ready("EXACT_CANCEL_LATCH_REQUIRED")
        operation_ids = sorted(operation_ids)
        status = runtime.status().to_dict()
        if (
            status.get("latch_generation") != generation
            or sorted(status.get("blocking_operation_ids", [])) != operation_ids
            or status.get("blocking_operation_count") != len(operation_ids)
            or status.get("allowed") is not False
        ):
            return _not_ready("LATCH_STATE_CHANGED")
        identity = wallet.get_wallet_identity()
        fingerprint = identity.get("fingerprint") if type(identity) is dict else None
        network = identity.get("network_id") if type(identity) is dict else None
        if (
            identity.get("success") is not True
            or identity.get("backend") != "sage"
            or type(fingerprint) is not int
            or type(network) is not str
            or mutation_gate.wallet_fingerprint_hash(fingerprint)
            != runtime.wallet_fingerprint_hash
            or runtime.wallet_fingerprint_hash != latch.get("wallet_fingerprint_hash")
            or network.lower() != runtime.network.lower()
            or runtime.network != latch.get("network")
        ):
            return _not_ready("WALLET_BINDING_MISMATCH")
        pending = wallet.get_pending_transactions()
        if type(pending) is not list or pending:
            return _not_ready("PENDING_TRANSACTIONS_OR_READ_FAILURE")

        trade_ids = tuple(
            operation_id.split(":", 1)[1] for operation_id in operation_ids
        )
        sage = wallet.get_authoritative_offers_by_ids(trade_ids)
        if (
            type(sage) is not dict
            or sage.get("complete") is not True
            or sage.get("requested_ids") != list(trade_ids)
            or type(sage.get("offers")) is not list
            or len(sage["offers"]) != len(trade_ids)
        ):
            return _not_ready("SAGE_EXACT_OFFER_READ_INCOMPLETE")
        records = database.get_authoritative_terminal_records(trade_ids)
        scope = {
            "generation": generation,
            "operation_ids": operation_ids,
            "wallet_fingerprint": fingerprint,
            "network": network.lower(),
        }
        scope_digest = hashlib.sha256(
            json.dumps(scope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        proofs = []
        local_proof_incomplete = False
        for operation_id, trade_id, sage_offer in zip(
            operation_ids, trade_ids, sage["offers"]
        ):
            intent = OfferManager._canonical_cancel_intent(trade_id)
            projection = OfferManager._read_existing_cancel_result(intent)
            terminal = records.get(trade_id)
            sage_status = sage_offer.get("status") if type(sage_offer) is dict else None
            normalized_status = (
                sage_status.strip().lower() if type(sage_status) is str else sage_status
            )
            if (
                type(sage_offer) is not dict
                or sage_offer.get("trade_id") != trade_id
                or normalized_status not in _CANCELLED_SAGE_STATUSES
            ):
                return _not_ready("CANCELLATION_PROOF_INCOMPLETE")
            if (
                intent.operation_id != operation_id
                or projection.authoritative is not True
                or type(projection.result) is not dict
                or projection.result.get("outcome") != CANCEL_CONFIRMED
                or type(terminal) is not dict
                or terminal.get("sage_trade_id") != trade_id
                or terminal.get("intent_id") != intent.intent_id
                or terminal.get("outcome") != "CANCELLED_PROVEN"
                or terminal.get("terminal_state") != "cancelled"
            ):
                local_proof_incomplete = True
                continue
            proofs.append(
                {
                    "operation_id": operation_id,
                    "trade_id": trade_id,
                    "outcome": "CANCELLED_PROVEN",
                    "sage_status": "cancelled",
                    "evidence_sha256": terminal["evidence_sha256"],
                }
            )
        if local_proof_incomplete:
            return {
                **_not_ready("CANCELLATION_PROOF_INCOMPLETE"),
                **scope,
                "scope_digest": scope_digest,
            }
        canonical = {
            "generation": generation,
            "operation_ids": operation_ids,
            "wallet_fingerprint": fingerprint,
            "network": network.lower(),
            "proofs": proofs,
        }
        digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "ready": True,
            "reason_code": "CANCELLATIONS_PROVEN",
            "generation": generation,
            "operation_ids": operation_ids,
            "wallet_fingerprint": fingerprint,
            "network": network.lower(),
            "proofs": proofs,
            "review_digest": digest,
            "scope_digest": scope_digest,
        }
    except Exception:
        return _not_ready("CANCELLATION_REVIEW_UNAVAILABLE")
