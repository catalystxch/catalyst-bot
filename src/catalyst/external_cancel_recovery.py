"""Native, proof-only settlement of a cancellation performed directly in Sage.

This module never sends a wallet transaction. The review lives only in memory,
expires after five minutes and is consumed before the database-only commit.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from typing import Any


_REVIEW_SECONDS = 300
_REVIEW_LOCK = threading.RLock()
_pending_review: dict[str, Any] | None = None


def _clear_pending_review_for_test() -> None:
    global _pending_review
    with _REVIEW_LOCK:
        _pending_review = None


def _stable_review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in review.items()
        if key not in {"reviewed_at_epoch", "expires_at_epoch"}
    }


def _candidate(database, wallet_hash: str, network: str, asset_id: str) -> dict:
    if database.list_active_bootstrap_campaigns_for_asset(asset_id):
        raise ValueError("external cancellation requires a stopped campaign")
    roots = [
        row
        for row in database.get_offer_intents_for_registry()
        if row.get("wallet_fingerprint_hash") == wallet_hash
        and row.get("network") == network
        and row.get("asset_id") == asset_id
        and row.get("lifecycle_state") in {"created", "visible", "unknown"}
    ]
    offers = database.get_open_offers(cat_asset_id=asset_id)
    if (
        len(roots) != 1
        or len(offers) != 1
        or offers[0].get("trade_id") != roots[0].get("sage_trade_id")
        or database.get_unresolved_offer_operation_blockers()
    ):
        raise ValueError("external cancellation local offer scope is ambiguous")
    return roots[0]


@contextmanager
def _verified_external_proof():
    import api_server
    import database
    import mixed_terminal_recovery
    import mutation_gate
    import offer_reconciliation
    import wallet
    from config import cfg

    authority = mutation_gate.current_runtime()
    if authority is None:
        raise ValueError("external cancellation runtime is unavailable")
    status = authority.status().to_dict()
    lease = status.get("lease") or {}
    if (
        status.get("allowed") is not True
        or lease.get("active") is not True
        or lease.get("owned_by_this_run") is not True
    ):
        raise ValueError("external cancellation runtime is not authorized")
    bot = api_server.bot
    if bot is None or not callable(getattr(bot, "is_running", None)):
        raise ValueError("external cancellation bot is unavailable")
    binding = authority.require_wallet_identity_authority("external_cancel_review")
    if (
        type(binding) is not mutation_gate.WalletIdentityBinding
        or binding.backend != "sage"
    ):
        raise ValueError("external cancellation Sage binding is unavailable")
    with api_server._bot_cancel_lifecycle_lock:
        if bot.is_running():
            raise ValueError("external cancellation requires a stopped bot")
        manager = getattr(bot, "offer_manager", None)
        wait = getattr(manager, "wait_for_offer_creation_quiescence", None)
        if not callable(wait):
            raise ValueError("external cancellation creation fence is unavailable")
        wait()
        asset_id = cfg.CAT_ASSET_ID
        before = _candidate(
            database, authority.wallet_fingerprint_hash, binding.network_id, asset_id
        )
        first_identity = wallet.get_wallet_identity()
        first_check = mutation_gate.validate_wallet_identity(binding, first_identity)
        if first_check.get("allowed") is not True:
            raise ValueError("external cancellation wallet identity changed")
        first_sync = wallet.get_wallet_sync_status()
        if type(first_sync) is not dict or first_sync.get("synced") is not True:
            raise ValueError("external cancellation wallet is not synced")
        first_book = mixed_terminal_recovery._read_book(wallet)
        evidence = offer_reconciliation.load_authoritative_evidence(
            before, wallet_ids=tuple(sorted({1, cfg.CAT_WALLET_ID}))
        )
        second_identity = wallet.get_wallet_identity()
        second_check = mutation_gate.validate_wallet_identity(
            binding,
            second_identity,
            last_observed_at_utc=first_check["observed_at_utc"],
        )
        second_sync = wallet.get_wallet_sync_status()
        second_book = mixed_terminal_recovery._read_book(wallet)
        after = _candidate(
            database, authority.wallet_fingerprint_hash, binding.network_id, asset_id
        )
        if (
            second_check.get("allowed") is not True
            or type(second_sync) is not dict
            or second_sync.get("synced") is not True
            or before != after
            or bot.is_running()
            or authority.status().to_dict().get("lease", {}).get("owned_by_this_run")
            is not True
            or second_book["observed_at"] <= first_book["observed_at"]
        ):
            raise ValueError("external cancellation proof changed during review")
        classified = offer_reconciliation.classify_external_cancel_evidence(
            before, evidence, now=second_book["observed_at"]
        )
        if (
            classified.get("classification") != "CANCELLED_PROVEN"
            or classified.get("reason_code") != "EXACT_EXTERNAL_CANCEL_RETURN_PROOF"
            or classified.get("origin") != "external"
            or type(classified.get("coin_rebindings")) is not list
            or len(classified["coin_rebindings"]) != 1
        ):
            raise ValueError("external cancellation exact Sage proof is unavailable")
        stable_source = mixed_terminal_recovery._stable_proof_fields(evidence)
        canonical, digest = offer_reconciliation.canonical_evidence_and_digest(
            {"classification": classified, "source": stable_source}
        )
        if json.loads(canonical).get("bounded") is True:
            raise ValueError("external cancellation proof exceeds review limit")
        returned = classified["coin_rebindings"][0]
        expected_return_asset = "xch" if before["side"] == "buy" else asset_id
        if returned.get("asset_id") != expected_return_asset:
            raise ValueError("external cancellation returned asset differs")
        reviewed_at = int(time.time())
        review = {
            "intent_id": before["intent_id"],
            "trade_id": before["sage_trade_id"],
            "side": before["side"],
            "wallet_fingerprint": binding.fingerprint,
            "wallet_fingerprint_hash": before["wallet_fingerprint_hash"],
            "network": before["network"],
            "asset_id": before["asset_id"],
            "input_coin_id": returned["input_coin_id"],
            "return_coin_id": returned["return_coin_id"],
            "returned_asset_id": returned["asset_id"],
            "returned_amount_atomic": str(returned["amount"]),
            "fee_mojos": str(classified["fee_mojos"]),
            "confirmed_height": classified["block_height"],
            "transaction_id": classified.get("transaction_id"),
            "spend_identity": classified.get("spend_identity"),
            "proof_digest": digest,
            "reviewed_at_epoch": reviewed_at,
            "expires_at_epoch": reviewed_at + _REVIEW_SECONDS,
            "wallet_effect_started": False,
        }
        yield review, evidence, before, second_book["observed_at"]


def _commit_local_proof(intent_id: str, evidence: dict, observed_at: str) -> dict:
    import offer_reconciliation

    result = offer_reconciliation.reconcile_external_cancellation(
        intent_id, evidence=evidence, now=observed_at
    )
    if result.get("applied") is not True or result.get("idempotent") is True:
        raise ValueError("external cancellation did not commit exactly once")
    return {**result, "wallet_effect_started": False}


def preview_external_cancellation() -> dict[str, Any]:
    """Read one exact stopped-wallet candidate for the native GUI."""

    global _pending_review
    with _REVIEW_LOCK:
        with _verified_external_proof() as (review, _evidence, _intent, _observed):
            _pending_review = dict(review)
            return dict(review)


def commit_external_cancellation(reviewed: Any) -> dict[str, Any]:
    """Consume a fresh native review, then commit only local terminal proof."""

    global _pending_review
    with _REVIEW_LOCK:
        if _pending_review is None:
            raise ValueError("external cancellation was not reviewed")
        if type(reviewed) is not dict or reviewed != _pending_review:
            raise ValueError("external cancellation review changed")
        if int(time.time()) > _pending_review["expires_at_epoch"]:
            _pending_review = None
            raise ValueError("external cancellation review expired")
        try:
            with _verified_external_proof() as (
                fresh,
                evidence,
                intent,
                observed_at,
            ):
                if _stable_review(fresh) != _stable_review(_pending_review):
                    raise ValueError("external cancellation Sage proof changed")
                _pending_review = None
                return _commit_local_proof(intent["intent_id"], evidence, observed_at)
        finally:
            _pending_review = None
