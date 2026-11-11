"""Read-only observation of one dispatched fee-prep replacement race."""

from __future__ import annotations

import json
import re
import hashlib
from datetime import datetime, timedelta, timezone

import mutation_gate
from database import (
    coin_prep_rbf_winner_reference,
    get_recoverable_coin_prep_rbf_sign_intents,
    get_recoverable_coin_prep_rbf_attempts,
    record_coin_prep_rbf_sign_no_submit,
    resolve_coin_prep_rbf_attempt,
)
from wallet import (
    get_coins_by_ids,
    get_transaction_by_height,
    get_wallet_identity_for_recovery,
    get_wallet_sync_status,
)


def _id(value) -> str:
    if type(value) is not str:
        raise ValueError("coin identity is absent")
    value = value.lower().removeprefix("0x")
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("coin identity is malformed")
    return value


def _amount(value) -> int:
    if type(value) is int and value >= 0:
        return value
    if type(value) is str and value.isascii() and value.isdigit():
        return int(value)
    raise ValueError("coin amount is not exact")


def _xch_flow(value) -> tuple[str, int]:
    if type(value) is not dict:
        raise ValueError("transaction flow is malformed")
    asset = value.get("asset")
    if asset is not None and (
        type(asset) is not dict or asset.get("asset_id") is not None
    ):
        raise ValueError("transaction flow is not XCH")
    return _id(value.get("coin_id")), _amount(value.get("amount"))


def _coin_record(records: dict, coin_id: str) -> dict | None:
    for key in (coin_id, "0x" + coin_id):
        row = records.get(key)
        if type(row) is dict:
            return row
    return None


def observe_coin_prep_rbf_winner(attempt: dict) -> dict | None:
    """Construct a candidate proof only from a confirmed Sage source spend.

    Missing or ambiguous wallet data leaves the attempt unresolved. This
    routine performs reads only; the database validates the proof again.
    """
    try:
        if type(attempt) is not dict:
            return None
        source_ids = json.loads(attempt["source_coin_ids_json"])
        if type(source_ids) is not list or len(source_ids) != 1:
            return None
        source = _id(source_ids[0])
        original = json.loads(attempt["original_outputs_json"])
        successor = json.loads(attempt["successor_outputs_json"])
        if type(original) is not list or type(successor) is not list:
            return None
        by_id = {}
        for output in [*original, *successor]:
            coin_id = _id(output["coin_id"])
            amount = _amount(output["amount_mojos"])
            prior = by_id.get(coin_id)
            if prior is not None and prior != amount:
                return None
            by_id[coin_id] = amount
        if len(by_id) < 6:
            return None
        binding_payload = json.loads(attempt["wallet_identity_json"])
        binding = mutation_gate.WalletIdentityBinding(**binding_payload)
        if mutation_gate.wallet_identity_binding_payload(binding) != binding_payload:
            return None
        identity = get_wallet_identity_for_recovery()
        if (
            mutation_gate.validate_wallet_identity(binding, identity).get("allowed")
            is not True
        ):
            return None
        sync = get_wallet_sync_status()
        if type(sync) is not dict or sync.get("synced") is not True:
            return None
        source_view = get_coins_by_ids(
            [source], authoritative_asset_hints={source: "xch"}
        )
        if type(source_view) is not dict:
            return None
        source_record = _coin_record(source_view, source)
        if source_record is None:
            return None
        source_height = source_record.get("spent_height")
        if type(source_height) is not int or source_height <= 0:
            return None
        source_amount = _amount(source_record.get("amount"))
        tx_response = get_transaction_by_height(source_height)
        transaction = (
            tx_response.get("transaction")
            if type(tx_response) is dict and tx_response.get("success") is True
            else None
        )
        if type(transaction) is not dict:
            return None
        raw_tx_id = transaction.get("transaction_id")
        tx_id = _id(raw_tx_id) if raw_tx_id is not None else None
        spent = transaction.get("spent")
        created = transaction.get("created")
        if (
            type(spent) is not list
            or type(created) is not list
            or len(spent) > 128
            or len(created) > 128
        ):
            return None
        spent_flows = [_xch_flow(item) for item in spent]
        created_flows = [_xch_flow(item) for item in created]
        spent_ids = [item[0] for item in spent_flows]
        created_ids = [item[0] for item in created_flows]
        if (
            len(set(spent_ids)) != len(spent_ids)
            or len(set(created_ids)) != len(created_ids)
            or spent_ids.count(source) != 1
        ):
            return None
        external = {
            coin_id: amount
            for coin_id, amount in created_flows
            if coin_id not in spent_ids
        }
        if source_amount < sum(external.values()):
            return None
        original_by_id = {
            _id(item["coin_id"]): _amount(item["amount_mojos"]) for item in original
        }
        successor_by_id = {
            _id(item["coin_id"]): _amount(item["amount_mojos"]) for item in successor
        }
        original_wins = external == original_by_id
        successor_wins = external == successor_by_id
        if original_wins == successor_wins:
            return None
        winner = "ORIGINAL" if original_wins else "SUCCESSOR"
        original_id = _id(attempt["original_transaction_id"])
        if winner == "ORIGINAL" and tx_id is not None and tx_id != original_id:
            return None
        if winner == "SUCCESSOR" and tx_id == original_id:
            return None
        expected_fee = 0 if winner == "ORIGINAL" else _amount(attempt["fee_mojos"])
        if source_amount - sum(external.values()) != expected_fee:
            return None
        winner_outputs = original if winner == "ORIGINAL" else successor
        winner_reference = (
            original_id
            if winner == "ORIGINAL"
            else coin_prep_rbf_winner_reference(
                attempt["attempt_id"], source, source_height, winner_outputs
            )
        )
        winner_ids = sorted(_id(item["coin_id"]) for item in winner_outputs)
        output_view = get_coins_by_ids(
            winner_ids,
            authoritative_asset_hints={coin_id: "xch" for coin_id in winner_ids},
        )
        if type(output_view) is not dict:
            return None
        authoritative_coins = []
        for output in winner_outputs:
            coin_id = _id(output["coin_id"])
            record = _coin_record(output_view, coin_id)
            if (
                record is None
                or _amount(record.get("amount")) != output["amount_mojos"]
                or record.get("created_height") != source_height
                or record.get("asset_id") not in (None, "xch")
            ):
                return None
            observed = {
                "coin_id": coin_id,
                "amount_mojos": output["amount_mojos"],
                "purpose": output["purpose"],
            }
            spent_height = record.get("spent_height")
            if spent_height not in (None, 0):
                if type(spent_height) is not int or spent_height <= 0:
                    return None
                observed["spent_height"] = spent_height
            authoritative_coins.append(observed)
        observed_at = datetime.now(timezone.utc)
        observed_text = observed_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
        expires_text = (
            (observed_at + timedelta(seconds=binding.maximum_age_seconds))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        chain_view = {
            "complete": True,
            "network": binding.network_id,
            "observed_at": observed_text,
            "source_coin_id": source,
            "source_spent_height": source_height,
            "coins": [
                {
                    "coin_id": coin_id,
                    "amount_mojos": amount,
                    "confirmed_height": source_height if coin_id in external else None,
                }
                for coin_id, amount in sorted(by_id.items())
            ],
        }
        return {
            "winner": winner,
            "winner_transaction_id": winner_reference,
            "chain_view": chain_view,
            "authoritative_view": {
                "fresh": True,
                "complete": True,
                "wallet_identity": binding_payload,
                "observed_at": observed_text,
                "expires_at": expires_text,
                "coins": authoritative_coins,
            },
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    except Exception:
        return None


def recover_dispatched_coin_prep_rbf_attempts_read_only() -> dict:
    """Observe every dispatched RBF race, resolving only an exact winner."""
    attempts = get_recoverable_coin_prep_rbf_attempts()
    operation_ids = {item["operation_id"] for item in attempts}
    settled = set()
    for attempt in attempts:
        proof = observe_coin_prep_rbf_winner(attempt)
        if proof is None:
            continue
        try:
            resolve_coin_prep_rbf_attempt(
                attempt["attempt_id"],
                winner=proof["winner"],
                winner_transaction_id=proof["winner_transaction_id"],
                chain_view=proof["chain_view"],
                authoritative_view=proof["authoritative_view"],
            )
        except Exception:
            continue
        settled.add(attempt["operation_id"])
    return {"operation_ids": operation_ids, "settled": settled}


def recover_crashed_coin_prep_rbf_sign_intents() -> dict:
    """Close sign-only crashes only with decisive local process-death proof.

    The submit-start journal is committed at the last callback before the RPC
    request. Its absence proves this CATalyst path did not submit. This only
    appends a local receipt; it does not settle coin prep or clear its latch.
    """
    intents = get_recoverable_coin_prep_rbf_sign_intents()
    recovered = set()
    for sign in intents:
        pid = sign.get("owner_pid")
        host = sign.get("owner_host")
        acquired_at = sign.get("lease_acquired_at")
        if type(pid) is not int or pid <= 0 or not host or not acquired_at:
            # Legacy rows without the immutable signer process snapshot are
            # deliberately left blocked.
            continue
        if mutation_gate.pid_liveness(pid, host) is not False:
            continue
        evidence = {
            "attempt_id": sign["attempt_id"],
            "owner_run_id": sign["owner_run_id"],
            "owner_pid": pid,
            "owner_host": host,
            "lease_version": sign["lease_version"],
            "lease_acquired_at": acquired_at,
            "sign_started_at": sign["started_at"],
            "submit_marker_absent": True,
            "owner_liveness": "DEAD",
        }
        digest = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        try:
            record_coin_prep_rbf_sign_no_submit(
                sign["attempt_id"],
                receipt={
                    "attempt_id": sign["attempt_id"],
                    "reason_code": "CRASH_BEFORE_SUBMIT_MARKER",
                    "submit_rpc_attempted": False,
                    "evidence_sha256": digest,
                },
                prior_owner_liveness_proven_dead=True,
            )
        except (ValueError, RuntimeError):
            # A changed lease or a racing submit marker is never inferred away.
            continue
        recovered.add(sign["attempt_id"])
    return {"sign_intents": len(intents), "receipts_recorded": recovered}
