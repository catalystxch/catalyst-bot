"""Proof-only recovery for a Follow cancellation fenced before Sage dispatch."""

from __future__ import annotations

import json
import time

import database
import wallet


def recover_claimed_predispatch_follow_cancel(run_id: str, manifest: dict) -> dict:
    """Reconcile one exact claimed cohort after fresh Sage no-effect reads.

    A normal cancellation is never retried here. Any partial or stale read
    leaves the runtime latch and protected fee hold unchanged.
    """

    exact = database.validate_offer_cancel_cohort_manifest(manifest)
    identity = database.get_follow_run_identity(run_id)
    latch = database.get_runtime_safety_latch()
    operation_ids = [member["operation_id"] for member in exact["members"]]
    if (
        latch.get("state") != "tripped"
        or latch.get("reason_code") != "UNRESOLVED_OPERATIONS"
        or latch.get("reason")
        != "Follow cancellation fee hold changed after effect claim"
        or json.loads(latch.get("blocking_operation_ids_json") or "[]")
        != sorted(operation_ids)
    ):
        raise ValueError("Follow pre-dispatch recovery latch is not exact")

    def checked_identity() -> dict:
        observed = wallet.get_wallet_identity_for_recovery()
        if (
            type(observed) is not dict
            or observed.get("success") is not True
            or observed.get("backend") != "sage"
            or observed.get("fingerprint") != identity["wallet_fingerprint"]
            or observed.get("network_id") != identity["network"]
        ):
            raise ValueError("Follow pre-dispatch wallet identity changed")
        return observed

    checked_identity()
    prepared = database.get_offer_cancel_cohort_prepared_events(exact["cohort_id"])
    if type(prepared) is not list or len(prepared) != exact["member_count"]:
        raise ValueError("Follow pre-dispatch prepared cohort is incomplete")
    batches = [
        json.loads(event["evidence_json"])["wallet_effect"]["batch"]
        for event in prepared
    ]
    if any(batch != batches[0] for batch in batches):
        raise ValueError("Follow pre-dispatch wallet effects differ")
    batch = batches[0]
    trade_ids = [member["trade_id"] for member in exact["members"]]
    source_ids = batch.get("source_coin_ids")
    fee_coin_id = batch.get("fee_coin_id")
    if (
        batch.get("trade_ids") != trade_ids
        or type(source_ids) is not list
        or len(source_ids) != len(trade_ids)
        or type(fee_coin_id) is not str
    ):
        raise ValueError("Follow pre-dispatch wallet effect is not exact")
    coin_ids = [*source_ids, fee_coin_id]
    sweep_started_at = time.time()
    coins = wallet.get_recovery_coins_by_ids(coin_ids)
    offers = wallet.get_recovery_active_offers_by_ids(tuple(trade_ids))
    pending = wallet.get_pending_transactions_strict()
    checked_identity()
    sweep_finished_at = time.time()
    if (
        sweep_finished_at < sweep_started_at
        or sweep_finished_at - sweep_started_at > 15
        or type(coins) is not dict
        or set(coins) != {"0x" + coin_id for coin_id in coin_ids}
        or type(offers) is not dict
        or offers.get("complete") is not True
        or offers.get("requested_ids") != trade_ids
        or type(offers.get("offers")) is not list
        or len(offers["offers"]) != len(trade_ids)
        or pending != []
    ):
        raise ValueError("Follow pre-dispatch Sage no-effect read is incomplete")
    evidence = {
        "source_coins": [
            {
                "coin_id": coin_id,
                "offer_id": coins["0x" + coin_id].get("offer_id"),
                "spent_height": coins["0x" + coin_id].get("spent_height"),
            }
            for coin_id in source_ids
        ],
        "fee_coin": {
            "coin_id": fee_coin_id,
            "offer_id": coins["0x" + fee_coin_id].get("offer_id"),
            "spent_height": coins["0x" + fee_coin_id].get("spent_height"),
        },
        "offers": [
            {"offer_id": offer["offer_id"], "status": offer["status"]}
            for offer in offers["offers"]
        ],
        "pending_transactions": [],
        "observed_at_epoch": int(time.time()),
    }
    result = database.reconcile_follow_predispatch_cancel_cohort(
        run_id=run_id,
        manifest_json=exact,
        expected_latch_generation=latch["generation"],
        wallet_fingerprint_hash=latch["wallet_fingerprint_hash"],
        network=latch["network"],
        wallet_evidence=evidence,
    )
    # The process that tripped the latch may still own an in-memory fee-coin
    # ticket. Its pool is rebuilt only on a controlled process restart.
    return {**result, "restart_required": True}
