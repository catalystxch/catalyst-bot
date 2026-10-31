"""Read-only proof classification for an ambiguous Sage offer creation.

This module deliberately exposes no wallet or database mutation. A failed
classification must leave the existing runtime safety latch untouched.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

import psutil

_REVIEW_SECONDS = 300
_REVIEW_LOCK = threading.RLock()
_pending_review: dict[str, Any] | None = None


def _clear_pending_review_for_test() -> None:
    global _pending_review
    with _REVIEW_LOCK:
        _pending_review = None


def sage_process_identity() -> dict[str, Any]:
    """Bind a read-only Sage proof to exactly one RPC listener incarnation."""

    listeners = [
        connection
        for connection in psutil.net_connections(kind="tcp")
        if connection.status == "LISTEN"
        and connection.laddr
        and connection.laddr.port == 9257
    ]
    if len(listeners) != 1 or type(listeners[0].pid) is not int:
        raise ValueError("Sage RPC listener is missing or ambiguous")
    try:
        process = psutil.Process(listeners[0].pid)
        created_at = process.create_time()
        executable = process.exe()
    except (psutil.Error, OSError) as exc:
        raise ValueError("Sage process identity is unavailable") from exc
    if (
        type(created_at) not in {float, int}
        or created_at <= 0
        or type(executable) is not str
        or not executable
        or not executable.lower().endswith("sage-tauri.exe")
    ):
        raise ValueError("Sage process identity is invalid")
    return {"pid": listeners[0].pid, "created_at": created_at, "exe": executable}


def capture_creation_observation(
    intent: dict[str, Any],
    *,
    wallet_module: Any = None,
    process_reader: Any = sage_process_identity,
) -> dict[str, Any]:
    """Read one complete wallet/book/coin witness without a wallet effect."""

    if wallet_module is None:
        import wallet as wallet_module
    from offer_reconciliation import load_sage_offer_history

    if type(intent) is not dict:
        raise ValueError("creation intent is unavailable")
    try:
        selected = json.loads(intent["selected_coin_ids_json"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selected coin identity is unavailable") from exc
    if type(selected) is not list or len(selected) != 1 or type(selected[0]) is not str:
        raise ValueError("selected coin identity is ambiguous")
    coin_id = selected[0].removeprefix("0x")
    asset_id = intent.get("asset_id") if intent.get("side") == "sell" else "xch"
    before_process = process_reader()
    identity = wallet_module.get_wallet_identity()
    sync = wallet_module.get_wallet_sync_status()
    pending = wallet_module.get_pending_transactions()
    history = load_sage_offer_history(
        get_all_offers=wallet_module.get_authoritative_offer_history,
        include_completed=True,
        page_size=500,
        max_pages=20,
    )
    coin_map = wallet_module.get_coins_by_ids(
        [coin_id], authoritative_asset_hints={coin_id: asset_id}
    )
    after_process = process_reader()
    if before_process != after_process:
        raise ValueError("Sage process changed during proof collection")
    if type(pending) is not list or type(coin_map) is not dict:
        raise ValueError("Sage pending or selected coin read is unavailable")
    pending_ids = []
    for transaction in pending:
        if (
            type(transaction) is not dict
            or type(transaction.get("transaction_id")) is not str
        ):
            raise ValueError("Sage pending transaction identity is unavailable")
        pending_ids.append(transaction["transaction_id"])
    coin = coin_map.get("0x" + coin_id)
    if type(coin) is not dict or len(coin_map) != 1:
        raise ValueError("selected Sage coin is missing or ambiguous")
    return {
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "wallet_identity": identity,
        "sage_process": after_process,
        "synced": type(sync) is dict and sync.get("synced") is True,
        "pending_transaction_ids": pending_ids,
        "coin": coin,
        "history": history,
    }


def _atomic(value: Any) -> int:
    if type(value) is int and value > 0:
        return value
    if (
        type(value) is str
        and value.isascii()
        and value.isdigit()
        and not value.startswith("0")
    ):
        return int(value)
    raise ValueError("offer amount is not an exact positive integer")


def _history_atomic(value: Any) -> int:
    # Old Sage rows can retain an exact zero requested amount. It cannot
    # match the positive candidate, but remains part of the book digest.
    if value == 0 and type(value) in {int, str}:
        return 0
    return _atomic(value)


def _trade_id(record: dict) -> str:
    values = [record[key] for key in ("trade_id", "offer_id") if key in record]
    if (
        not values
        or any(
            type(value) is not str
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in values
        )
        or len(set(values)) != 1
    ):
        raise ValueError("Sage offer ID is missing or ambiguous")
    return values[0]


def _book_fingerprint(history: Any, requested_amount: int) -> tuple[str, int]:
    if (
        type(history) is not dict
        or history.get("complete") is not True
        or history.get("read_error") is not None
        or type(history.get("pagination")) is not dict
        or history["pagination"].get("authoritative_end") is not True
        or type(history.get("records")) is not list
    ):
        raise ValueError("complete authoritative Sage history is unavailable")
    records = history["records"]
    if len(records) > 16384:
        raise ValueError("Sage history exceeds proof bound")
    stable = []
    seen = set()
    for record in records:
        if type(record) is not dict:
            raise ValueError("Sage offer record is malformed")
        trade_id = _trade_id(record)
        if trade_id in seen:
            raise ValueError("Sage offer ID is duplicated")
        seen.add(trade_id)
        summary = record.get("summary")
        if type(summary) is not dict or type(summary.get("requested")) is not dict:
            raise ValueError("Sage offer amounts are unavailable")
        requested = summary["requested"]
        if not requested:
            raise ValueError("Sage offer requested amount is unavailable")
        amounts = {
            str(asset): _history_atomic(amount) for asset, amount in requested.items()
        }
        if requested_amount in amounts.values():
            raise ValueError("Sage history contains the ambiguous offer amount")
        status = record.get("status")
        if type(status) not in {str, int}:
            raise ValueError("Sage offer status is unavailable")
        stable.append((trade_id, status, amounts))
    canonical = json.dumps(
        sorted(stable, key=lambda item: item[0]), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), len(records)


def _observed_at(value: Any) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError("proof observation time is invalid")
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("proof observation time is invalid") from exc
    return observed.astimezone(timezone.utc)


def classify_no_effect_creation(
    intent: Any,
    latch: Any,
    journal: Any,
    reservations: Any,
    observations: Any,
) -> dict[str, Any]:
    """Classify two stable, complete, identity-bound reads without a wallet effect."""

    if any(type(value) is not dict for value in (intent, latch, journal)):
        raise ValueError("local creation proof is unavailable")
    intent_id = intent.get("intent_id")
    operation_id = f"create:{intent_id}"
    if (
        type(intent_id) is not str
        or len(intent_id) != 64
        or any(char not in "0123456789abcdef" for char in intent_id)
        or intent.get("lifecycle_state") != "creation_unknown"
        or type(intent.get("row_version")) is not int
        or intent.get("sage_trade_id") is not None
        or intent.get("side") not in {"buy", "sell"}
        or type(intent.get("wallet_fingerprint_hash")) is not str
        or type(intent.get("network")) is not str
        or type(intent.get("asset_id")) is not str
    ):
        raise ValueError("ambiguous creation intent changed")
    offered = _atomic(intent.get("offered_amount_atomic"))
    requested = _atomic(intent.get("requested_amount_atomic"))
    try:
        selected = json.loads(intent["selected_coin_ids_json"])
        blockers = json.loads(latch["blocking_operation_ids_json"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("creation or latch scope is malformed") from exc
    if (
        type(selected) is not list
        or len(selected) != 1
        or type(selected[0]) is not str
        or len(selected[0]) != 64
        or type(blockers) is not list
        or blockers != [operation_id]
        or latch.get("state") != "tripped"
        or latch.get("reason_code") != "UNRESOLVED_OPERATIONS"
        or type(latch.get("generation")) is not int
        or (latch.get("wallet_fingerprint_hash"), latch.get("network"))
        != (intent["wallet_fingerprint_hash"], intent["network"])
        or (
            journal.get("operation_id"),
            journal.get("intent_id"),
            journal.get("operation_type"),
            journal.get("outcome"),
            journal.get("blocks_mutation"),
        )
        != (operation_id, intent_id, "CREATE", "UNKNOWN", 1)
        or type(reservations) is not list
        or len(reservations) != 1
        or type(reservations[0]) is not dict
        or reservations[0].get("coin_id", "").removeprefix("0x") != selected[0]
        or reservations[0].get("status") != "reserved"
        or reservations[0].get("reservation_identity") != f"intent:{intent_id}"
    ):
        raise ValueError("creation blocker or selected coin changed")
    if type(observations) is not list or len(observations) != 2:
        raise ValueError("two independent Sage observations are required")
    first, second = observations
    if type(first) is not dict or type(second) is not dict:
        raise ValueError("Sage observations are malformed")
    elapsed = (
        _observed_at(second.get("observed_at")) - _observed_at(first.get("observed_at"))
    ).total_seconds()
    if elapsed <= 0 or elapsed > 120:
        raise ValueError("Sage observations are not bounded and ordered")
    stable = []
    for observation in observations:
        identity = observation.get("wallet_identity")
        process = observation.get("sage_process")
        coin = observation.get("coin")
        if (
            type(identity) is not dict
            or identity.get("success") is not True
            or identity.get("backend") != "sage"
            or type(identity.get("fingerprint")) is not int
            or identity.get("network_id") != intent["network"]
            or type(process) is not dict
            or type(process.get("pid")) is not int
            or process["pid"] <= 0
            or type(process.get("created_at")) not in {float, int}
            or type(process.get("exe")) is not str
            or not process["exe"]
            or observation.get("synced") is not True
            or observation.get("pending_transaction_ids") != []
            or type(coin) is not dict
            or _atomic(coin.get("amount")) < offered
            or coin.get("spent_height") is not None
            or coin.get("offer_id") is not None
            or coin.get("asset_id")
            != (intent["asset_id"] if intent["side"] == "sell" else "xch")
        ):
            raise ValueError("Sage identity, coin or pending state is unsafe")
        book_digest, book_count = _book_fingerprint(
            observation.get("history"), requested
        )
        stable.append(
            (
                identity["fingerprint"],
                identity["network_id"],
                process["pid"],
                process["created_at"],
                process["exe"],
                coin["amount"],
                coin["asset_id"],
                book_digest,
                book_count,
            )
        )
    if stable[0] != stable[1]:
        raise ValueError("Sage identity or complete book changed between observations")
    digest_input = {
        "intent_id": intent_id,
        "operation_id": operation_id,
        "row_version": intent["row_version"],
        "latch_generation": latch["generation"],
        "wallet_fingerprint_hash": intent["wallet_fingerprint_hash"],
        "network": intent["network"],
        "selected_coin_id": selected[0],
        "requested_amount_atomic": requested,
        "sage_stable": list(stable[0]),
    }
    canonical = json.dumps(digest_input, sort_keys=True, separators=(",", ":"))
    return {
        **digest_input,
        "proof_digest": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def collect_no_effect_creation_proof() -> dict[str, Any]:
    """Collect a quiescent, complete witness for exactly one local blocker."""

    import api_server
    import database
    import mutation_gate

    authority = mutation_gate.current_runtime()
    if authority is None:
        raise ValueError("creation recovery runtime is unavailable")
    binding = authority.wallet_identity_binding
    if (
        type(binding) is not mutation_gate.WalletIdentityBinding
        or binding.backend != "sage"
    ):
        raise ValueError("creation recovery wallet binding is unavailable")
    status = authority.status().to_dict()
    if status.get("lease", {}).get("owned_by_this_run") is not True:
        raise ValueError("creation recovery lease is not owned")
    bot = api_server.bot
    if bot is None or not callable(getattr(bot, "is_running", None)):
        raise ValueError("creation recovery bot is unavailable")
    with api_server._bot_cancel_lifecycle_lock:
        if bot.is_running():
            raise ValueError("creation recovery requires a stopped bot")
        manager = getattr(bot, "offer_manager", None)
        wait = getattr(manager, "wait_for_offer_creation_quiescence", None)
        if not callable(wait):
            raise ValueError("creation recovery quiescence fence is unavailable")
        wait()
        latch = database.get_runtime_safety_latch()
        blockers = database.get_unresolved_offer_operation_blockers()
        if type(blockers) is not list or len(blockers) != 1:
            raise ValueError("creation recovery blocker is not unique")
        journal = database.validate_offer_operation_event(blockers[0])
        intent = database.get_offer_intent(journal["intent_id"])
        if intent is None:
            raise ValueError("creation recovery intent is missing")
        reservations = database.get_offer_intent_coin_reservations(intent["intent_id"])
        lease = database.get_runtime_mutation_lease()
        if (
            lease.get("active") != 1
            or lease.get("owner_run_id") != authority.run_id
            or lease.get("wallet_fingerprint_hash") != authority.wallet_fingerprint_hash
            or lease.get("network") != authority.network
        ):
            raise ValueError("creation recovery runtime lease differs")
        first = capture_creation_observation(intent)
        first_decision = mutation_gate.validate_wallet_identity(
            binding, first["wallet_identity"]
        )
        if first_decision.get("allowed") is not True:
            raise ValueError("creation recovery wallet identity differs")
        second = capture_creation_observation(intent)
        second_decision = mutation_gate.validate_wallet_identity(
            binding,
            second["wallet_identity"],
            last_observed_at_utc=first_decision["observed_at_utc"],
        )
        if second_decision.get("allowed") is not True:
            raise ValueError("creation recovery wallet identity changed")
        if (
            database.get_offer_intent(intent["intent_id"]) != intent
            or database.get_runtime_safety_latch() != latch
            or database.get_offer_intent_coin_reservations(intent["intent_id"])
            != reservations
            or database.get_unresolved_offer_operation_blockers() != blockers
            or bot.is_running()
        ):
            raise ValueError("creation recovery local state changed")
        proof = classify_no_effect_creation(
            intent, latch, journal, reservations, [first, second]
        )
        proof.update(
            {
                "lease_owner_run_id": lease["owner_run_id"],
                "lease_owner_pid": lease["owner_pid"],
                "lease_owner_host": lease["owner_host"],
                "lease_version": lease["lease_version"],
            }
        )
        material = {key: value for key, value in proof.items() if key != "proof_digest"}
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        proof["proof_digest"] = hashlib.sha256(canonical.encode()).hexdigest()
        return proof


def preview_no_effect_creation() -> dict[str, Any]:
    """Show the native user an exact expiring, database-only recovery review."""

    global _pending_review
    with _REVIEW_LOCK:
        proof = collect_no_effect_creation_proof()
        now = int(time.time())
        review = {
            **proof,
            "reviewed_at_epoch": now,
            "expires_at_epoch": now + _REVIEW_SECONDS,
            "wallet_effect_started": False,
        }
        _pending_review = dict(review)
        return review


def commit_no_effect_creation(reviewed: Any) -> dict[str, Any]:
    """Reprove and atomically settle only the reviewed local no-effect state."""

    global _pending_review
    with _REVIEW_LOCK:
        if _pending_review is None:
            raise ValueError("no-effect creation was not reviewed")
        if type(reviewed) is not dict or reviewed != _pending_review:
            raise ValueError("no-effect creation review changed")
        if int(time.time()) > _pending_review["expires_at_epoch"]:
            _pending_review = None
            raise ValueError("no-effect creation review expired")
        try:
            fresh = collect_no_effect_creation_proof()
            old = {
                key: value
                for key, value in _pending_review.items()
                if key
                not in {
                    "reviewed_at_epoch",
                    "expires_at_epoch",
                    "wallet_effect_started",
                }
            }
            stable_keys = set(old) - {"lease_version", "proof_digest"}
            if (
                set(fresh) != set(old)
                or any(fresh[key] != old[key] for key in stable_keys)
                or type(fresh.get("lease_version")) is not int
                or fresh["lease_version"] < old["lease_version"]
            ):
                raise ValueError("no-effect creation proof changed")
            import database

            _pending_review = None
            return database.settle_no_effect_offer_creation(proof=fresh)
        finally:
            _pending_review = None
