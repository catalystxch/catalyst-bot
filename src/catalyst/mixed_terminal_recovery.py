"""Proof-only recovery of an exact elapsed campaign's terminal offer cohort.

The cohort validator is deliberately pure. It grants no lease, trading permit,
wallet effect, or terminal database write. Sage evidence collection and the
fenced commit are separate steps and must recheck this result.
"""

from __future__ import annotations

import json
import re
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any


_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_OPEN_STATES = frozenset({"created", "visible", "unknown"})
_TERMINAL_OUTCOMES = frozenset({"FILLED_PROVEN", "EXPIRED_PROVEN"})


def _hex_identity(value: Any) -> bool:
    return type(value) is str and _HEX_64.fullmatch(value) is not None


def _intent_identity(value: Any) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 128
        and value.strip() == value
        and not any(ord(char) < 32 for char in value)
    )


def validate_mixed_terminal_cohort(
    campaign: Any,
    intents: Any,
    open_offers: Any,
    unresolved_blockers: Any,
    terminal_records: Any,
    latch: Any,
) -> list[dict[str, Any]]:
    """Return sorted exact roots or refuse the entire mixed recovery cohort."""

    if (
        type(campaign) is not dict
        or not _hex_identity(campaign.get("campaign_id"))
        or not _hex_identity(campaign.get("asset_id"))
        or type(campaign.get("revision")) is not int
        or campaign["revision"] < 0
        or campaign.get("network") not in {"mainnet", "testnet"}
        or campaign.get("status") != "active"
        or type(intents) is not list
        or type(open_offers) is not list
        or type(unresolved_blockers) is not list
        or type(terminal_records) is not dict
        or type(latch) is not dict
    ):
        raise ValueError("mixed terminal campaign authority is invalid")
    purpose = f"bootstrap:{campaign['campaign_id']}:revision:{campaign['revision']}"
    prefix = f"bootstrap:{campaign['campaign_id']}:revision:"
    asset = campaign["asset_id"]
    network = campaign["network"]
    roots = [
        row for row in intents if type(row) is dict and row.get("purpose") == purpose
    ]
    if not 1 <= len(roots) <= 256 or any(type(row) is not dict for row in intents):
        raise ValueError("mixed terminal roots are incomplete")
    wallet_hashes = {row.get("wallet_fingerprint_hash") for row in roots}
    if len(wallet_hashes) != 1 or not _hex_identity(next(iter(wallet_hashes))):
        raise ValueError("mixed terminal wallet binding differs")
    wallet_hash = next(iter(wallet_hashes))
    if any(
        row.get("purpose") != purpose
        and row.get("lifecycle_state") != "terminal"
        and (
            str(row.get("purpose") or "").startswith(prefix)
            or (
                row.get("wallet_fingerprint_hash") == wallet_hash
                and row.get("network") == network
                and row.get("asset_id") == asset
            )
        )
        for row in intents
    ):
        raise ValueError("unrelated unresolved offer root exists")
    intent_ids = [row.get("intent_id") for row in roots]
    trade_ids = [row.get("sage_trade_id") for row in roots]
    if (
        any(not _intent_identity(value) for value in intent_ids)
        or any(not _hex_identity(value) for value in trade_ids)
        or len(set(intent_ids)) != len(roots)
        or len(set(trade_ids)) != len(roots)
        or any(
            row.get("wallet_fingerprint_hash") != wallet_hash
            or row.get("network") != network
            or row.get("asset_id") != asset
            or row.get("side") not in {"buy", "sell"}
            or type(row.get("tier")) is not str
            or not row["tier"]
            or row.get("lifecycle_state") not in _OPEN_STATES | {"terminal"}
            or row.get("parent_intent_id") is not None
            or row.get("child_intent_id") is not None
            for row in roots
        )
    ):
        raise ValueError("mixed terminal root identity differs")
    open_roots = [row for row in roots if row["lifecycle_state"] in _OPEN_STATES]
    expected_blockers = {f"reconcile:{row['intent_id']}" for row in open_roots}
    expected_journal = {
        f"reconcile:{row['intent_id']}"
        for row in open_roots
        if row["lifecycle_state"] == "unknown"
    }
    if len(expected_blockers) != len(open_roots):
        raise ValueError("mixed terminal blockers are duplicated")
    if any(type(row) is not dict for row in unresolved_blockers):
        raise ValueError("mixed terminal journal is invalid")
    journal = {row.get("operation_id"): row for row in unresolved_blockers}
    if len(journal) != len(unresolved_blockers):
        raise ValueError("mixed terminal journal identities are duplicated")
    try:
        latch_ids = json.loads(latch["blocking_operation_ids_json"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("mixed terminal latch blockers are invalid") from exc
    if type(latch_ids) is not list or len(latch_ids) != len(set(latch_ids)):
        raise ValueError("mixed terminal latch blockers are duplicated")
    restricted = latch.get("state") == "tripped"
    if restricted:
        if (
            latch.get("reason_code") != "REGISTRY_BLOCKED"
            or type(latch.get("generation")) is not int
            or latch["generation"] < 1
            or latch.get("wallet_fingerprint_hash") != wallet_hash
            or latch.get("network") != network
            or not expected_blockers
            or set(latch_ids) != expected_blockers
            or set(journal) != expected_journal
        ):
            raise ValueError("mixed terminal restricted blocker set differs")
    elif latch.get("state") == "resolved":
        if (
            latch_ids
            or journal
            or any(row["lifecycle_state"] == "unknown" for row in roots)
        ):
            raise ValueError("mixed terminal normal authority is not clear")
    else:
        raise ValueError("mixed terminal latch state is unsupported")
    for row in open_roots:
        blocker = journal.get(f"reconcile:{row['intent_id']}")
        if (
            restricted
            and row["lifecycle_state"] == "unknown"
            and (
                blocker is None
                or blocker.get("intent_id") != row["intent_id"]
                or blocker.get("operation_type") != "RECONCILE"
                or blocker.get("outcome") != "UNKNOWN"
                or blocker.get("blocks_mutation") != 1
            )
        ):
            raise ValueError("mixed terminal journal does not match the root")
    projected = {
        offer.get("trade_id"): offer for offer in open_offers if type(offer) is dict
    }
    if (
        len(projected) != len(open_offers)
        or set(projected) != {row["sage_trade_id"] for row in open_roots}
        or any(
            type(offer) is not dict
            or offer.get("status") != "open"
            or offer.get("cat_asset_id") != asset
            or offer.get("side") != row["side"]
            or offer.get("tier") != row["tier"]
            for row in open_roots
            for offer in [projected.get(row["sage_trade_id"])]
        )
    ):
        raise ValueError("mixed terminal open projection differs")
    expected_terminal = {
        row["sage_trade_id"] for row in roots if row["lifecycle_state"] == "terminal"
    }
    if set(terminal_records) != expected_terminal:
        raise ValueError("mixed terminal durable proofs are incomplete")
    for row in roots:
        if row["lifecycle_state"] != "terminal":
            continue
        proof = terminal_records[row["sage_trade_id"]]
        if (
            type(proof) is not dict
            or proof.get("intent_id") != row["intent_id"]
            or proof.get("operation_id") != f"reconcile:{row['intent_id']}"
            or proof.get("outcome") not in _TERMINAL_OUTCOMES
            or not _hex_identity(proof.get("evidence_sha256"))
        ):
            raise ValueError("mixed terminal durable proof differs")
    return [dict(row) for row in sorted(roots, key=lambda row: row["intent_id"])]


def _utc(value: Any) -> datetime:
    if type(value) is not str:
        raise ValueError("mixed terminal time is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("mixed terminal time is not UTC")
    return parsed.astimezone(timezone.utc)


def _lease_epoch(lease: Any, authority: Any) -> tuple[str, int, str, str, int]:
    if (
        type(lease) is not dict
        or lease.get("active") != 1
        or lease.get("owner_run_id") != authority.run_id
        or lease.get("owner_pid") != authority.owner_pid
        or lease.get("owner_host") != authority.owner_host
        or lease.get("acquired_at") != authority._lease_acquired_at
        or lease.get("wallet_fingerprint_hash") != authority.wallet_fingerprint_hash
        or lease.get("network") != authority.network
        or type(lease.get("lease_version")) is not int
        or _utc(lease.get("expires_at")) <= datetime.now(timezone.utc)
    ):
        raise ValueError("mixed terminal lease authority changed")
    return (
        lease["owner_run_id"],
        lease["owner_pid"],
        lease["owner_host"],
        lease["acquired_at"],
        lease["lease_version"],
    )


def _read_book(wallet_module: Any) -> dict[str, Any]:
    book = wallet_module._read_refresh_abort_cleanup_snapshot()
    if (
        type(book) is not dict
        or type(book.get("trade_ids")) is not list
        or type(book.get("pending_transaction_ids")) is not list
        or book["trade_ids"]
        or book["pending_transaction_ids"]
        or not timedelta(seconds=0)
        <= datetime.now(timezone.utc) - _utc(book.get("observed_at"))
        <= timedelta(seconds=30)
    ):
        raise ValueError("mixed terminal Sage book is not complete and empty")
    return book


def _stable_proof_fields(value: Any) -> Any:
    """Drop observation-clock metadata while retaining source witness values."""

    volatile = {
        "observed_at",
        "observed_at_utc",
        "source_observed_at",
        "source_observed_at_all",
        "read_observed_at",
        "collection_started_at",
        "collection_finished_at",
        "read_at",
        "read_at_utc",
    }
    if type(value) is dict:
        return {
            key: _stable_proof_fields(item)
            for key, item in value.items()
            if key not in volatile
        }
    if type(value) is list:
        return [_stable_proof_fields(item) for item in value]
    return value


def _capture_context(database_module: Any, campaign_id: str, asset_id: str):
    campaign = database_module.get_bootstrap_campaign(campaign_id)
    intents = database_module.get_offer_intents_for_registry()
    offers = database_module.get_open_offers(cat_asset_id=asset_id)
    blockers = database_module.get_unresolved_offer_operation_blockers()
    latch = database_module.get_runtime_safety_latch()
    lease = database_module.get_runtime_mutation_lease()
    purpose = (
        f"bootstrap:{campaign_id}:revision:{campaign['revision']}"
        if type(campaign) is dict and type(campaign.get("revision")) is int
        else None
    )
    terminal_ids = [
        row["sage_trade_id"]
        for row in intents
        if type(row) is dict
        and row.get("purpose") == purpose
        and row.get("lifecycle_state") == "terminal"
        and type(row.get("sage_trade_id")) is str
    ]
    if len(terminal_ids) > 256:
        raise ValueError("mixed terminal historical proof scope exceeds bound")
    terminal = database_module.get_authoritative_terminal_records(terminal_ids)
    return campaign, intents, offers, blockers, terminal, latch, lease


def preview_terminal_offers(
    campaign_id: str, revision: int, authority: object
) -> dict[str, Any]:
    """Read and classify a complete stopped campaign without any DB write."""

    import api_server
    import database
    import mutation_gate
    import offer_reconciliation
    import wallet
    from blueprints import bootstrap
    from config import cfg

    if not _hex_identity(campaign_id) or type(revision) is not int or revision < 0:
        raise ValueError("mixed terminal scope is invalid")
    if authority is not mutation_gate.current_runtime():
        raise ValueError("mixed terminal runtime authority is unavailable")
    status = authority.status().to_dict()
    restricted = bool(api_server._registry_terminal_recovery_active)
    if (
        status.get("lease", {}).get("owned_by_this_run") is not True
        or status.get("lease", {}).get("active") is not True
        or (restricted and status.get("reason_code") != "REGISTRY_BLOCKED")
        or (not restricted and status.get("allowed") is not True)
    ):
        raise ValueError("mixed terminal recovery authority is not active")
    bot = api_server.bot
    if restricted:
        if bot is not None:
            raise ValueError("mixed terminal restricted runtime constructed a bot")
    elif (
        bot is None
        or not callable(getattr(bot, "is_running", None))
        or bot.is_running()
    ):
        raise ValueError("mixed terminal bot must be stopped")
    binding = authority.require_wallet_identity_authority("mixed_terminal_preview")
    if (
        type(binding) is not mutation_gate.WalletIdentityBinding
        or binding.backend != "sage"
    ):
        raise ValueError("mixed terminal Sage identity binding is unavailable")
    with bootstrap._CAMPAIGN_LIFECYCLE_LOCK, api_server._bot_cancel_lifecycle_lock:
        if not restricted:
            manager = getattr(bot, "offer_manager", None)
            wait = getattr(manager, "wait_for_offer_creation_quiescence", None)
            if not callable(wait):
                raise ValueError("mixed terminal creation fence is unavailable")
            wait()
        before = _capture_context(database, campaign_id, cfg.CAT_ASSET_ID)
        campaign, intents, offers, blockers, terminal, latch, lease = before
        if (
            type(campaign) is not dict
            or campaign.get("revision") != revision
            or campaign.get("asset_id") != cfg.CAT_ASSET_ID
            or campaign.get("wallet_id") != cfg.CAT_WALLET_ID
            or campaign.get("wallet_fingerprint") != binding.fingerprint
            or campaign.get("network") != binding.network_id
            or _utc(campaign.get("expires_at")) > datetime.now(timezone.utc)
        ):
            raise ValueError("mixed terminal campaign authority changed")
        active_campaigns = database.list_active_bootstrap_campaigns_for_asset(
            cfg.CAT_ASSET_ID
        )
        if (
            len(active_campaigns) != 1
            or active_campaigns[0].get("campaign_id") != campaign_id
        ):
            raise ValueError("mixed terminal active campaign is not unique")
        first_epoch = _lease_epoch(lease, authority)
        roots = validate_mixed_terminal_cohort(
            campaign, intents, offers, blockers, terminal, latch
        )
        first_identity = wallet.get_wallet_identity()
        first_check = mutation_gate.validate_wallet_identity(binding, first_identity)
        if first_check.get("allowed") is not True:
            raise ValueError("mixed terminal wallet identity is unavailable")
        first_sync = wallet.get_wallet_sync_status()
        if type(first_sync) is not dict or first_sync.get("synced") is not True:
            raise ValueError("mixed terminal Sage wallet is not synced")
        first_book = _read_book(wallet)
        wallet_ids = tuple(sorted({1, campaign["wallet_id"]}))
        evidence = {
            row["intent_id"]: offer_reconciliation.load_authoritative_evidence(
                row, offer_scope="exact_intent", wallet_ids=wallet_ids
            )
            for row in roots
            if row["lifecycle_state"] != "terminal"
        }
        second_identity = wallet.get_wallet_identity()
        second_check = mutation_gate.validate_wallet_identity(
            binding,
            second_identity,
            last_observed_at_utc=first_check["observed_at_utc"],
        )
        second_sync = wallet.get_wallet_sync_status()
        second_book = _read_book(wallet)
        after = _capture_context(database, campaign_id, cfg.CAT_ASSET_ID)
        after_epoch = _lease_epoch(after[-1], authority)
        if (
            second_check.get("allowed") is not True
            or type(second_sync) is not dict
            or second_sync.get("synced") is not True
            or _utc(second_book["observed_at"]) <= _utc(first_book["observed_at"])
            or before[:-1] != after[:-1]
            or cfg.CAT_ASSET_ID != campaign["asset_id"]
            or cfg.CAT_WALLET_ID != campaign["wallet_id"]
            or first_epoch[:4] != after_epoch[:4]
            or after_epoch[4] < first_epoch[4]
            or authority.status().to_dict().get("lease", {}).get("owned_by_this_run")
            is not True
            or (
                restricted
                and authority.status().to_dict().get("reason_code")
                != "REGISTRY_BLOCKED"
            )
            or (
                not restricted
                and authority.status().to_dict().get("allowed") is not True
            )
        ):
            raise ValueError("mixed terminal proof changed during preview")
        vector = []
        for row in roots:
            if row["lifecycle_state"] == "terminal":
                proof = terminal[row["sage_trade_id"]]
                classification = proof["outcome"]
                proof_digest = proof["evidence_sha256"]
            else:
                source = evidence[row["intent_id"]]
                outcome = offer_reconciliation.classify_terminal_evidence(
                    row, source, now=second_book["observed_at"]
                )
                classification = outcome.get("classification")
                if classification not in _TERMINAL_OUTCOMES or (
                    row["lifecycle_state"] == "unknown"
                    and classification != "FILLED_PROVEN"
                ):
                    raise ValueError("mixed terminal root lacks conclusive proof")
                _encoded, proof_digest = (
                    offer_reconciliation.canonical_evidence_and_digest(
                        {
                            "classification": outcome,
                            "source": _stable_proof_fields(source),
                        }
                    )
                )
            vector.append(
                {
                    "intent_id": row["intent_id"],
                    "trade_id": row["sage_trade_id"],
                    "side": row["side"],
                    "tier": row["tier"],
                    "classification": classification,
                    "proof_digest": proof_digest,
                    "already_terminal": row["lifecycle_state"] == "terminal",
                }
            )
        binding_data = {
            "campaign_id": campaign_id,
            "revision": revision,
            "asset_id": campaign["asset_id"],
            "network": campaign["network"],
            "wallet_fingerprint_hash": authority.wallet_fingerprint_hash,
            "lease_owner_run_id": first_epoch[0],
            "lease_owner_pid": first_epoch[1],
            "lease_owner_host": first_epoch[2],
            "lease_acquired_at": first_epoch[3],
            "latch_generation": latch["generation"],
            "blocking_operation_ids": json.loads(latch["blocking_operation_ids_json"]),
            "offers": vector,
        }
        encoded = json.dumps(binding_data, sort_keys=True, separators=(",", ":"))
        return {
            **binding_data,
            "proof_digest": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "sage_live_offers": 0,
            "sage_pending_transactions": 0,
            "wallet_effect_started": False,
        }
