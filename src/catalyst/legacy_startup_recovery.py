"""Proof-bound recovery for pre-intent Sage offer reservations.

Older CATalyst releases stored an open offer and its locked coin before the
append-only intent registry existed. New startup safety correctly refuses an
unowned lock. This migration adopts only an offer that Sage independently
proves expired, then routes its terminal write through Task 9's existing
reconciliation boundary. No wallet mutation is performed here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import time
from typing import Any


_HEX = frozenset("0123456789abcdef")
_XCH_SCALE = Decimal("1000000000000")


class _CachedReadOnlyWallet:
    """Share immutable Sage history reads across a bounded legacy ladder."""

    _SHARED_METHODS = frozenset(
        {
            "get_wallet_backend_authority",
            "get_wallet_identity",
            "get_authoritative_offer_history",
            "get_all_offers",
            "get_transactions_list",
        }
    )

    def __init__(self, wallet_facade: Any, *, seed_coin_ids: set[str] | None = None):
        self._wallet = wallet_facade
        self._cache: dict[tuple[str, str], Any] = {}
        self._seed_coin_ids = {
            normalized
            for value in (seed_coin_ids or set())
            if (normalized := _hex_id(value))
        }
        self._coin_records: Any = None

    @staticmethod
    def _key(
        name: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[str, str]:
        encoded = json.dumps(
            {"args": args, "kwargs": kwargs},
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return name, encoded

    def __getattr__(self, name: str):
        target = getattr(self._wallet, name)
        if name == "get_coins_by_ids" and callable(target):

            def cached_coins(coin_ids):
                requested = {
                    normalized for value in coin_ids if (normalized := _hex_id(value))
                }
                if self._coin_records is None:
                    self._coin_records = target(sorted(requested | self._seed_coin_ids))
                result = self._coin_records
                if type(result) is not dict or result.get("success") is not True:
                    return result
                records = result.get("records")
                if type(records) is not dict:
                    return result
                filtered = {
                    key: value
                    for key, value in records.items()
                    if _hex_id(key) in requested
                    or (
                        type(value) is dict
                        and _hex_id(value.get("coin_id")) in requested
                    )
                }
                return {**result, "records": filtered}

            return cached_coins
        if name not in self._SHARED_METHODS or not callable(target):
            return target

        def cached(*args, **kwargs):
            key = self._key(name, args, kwargs)
            if key not in self._cache:
                self._cache[key] = target(*args, **kwargs)
            return self._cache[key]

        return cached


def _hex_id(value: Any) -> str:
    if type(value) is not str:
        return ""
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return (
        text if len(text) == 64 and all(character in _HEX for character in text) else ""
    )


def _canonical_utc(value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("legacy offer timestamp is unavailable")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text
        )
    except ValueError as exc:
        raise ValueError("legacy offer timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _wallet_identity_matches(identity: Any, wallet_hash: str, network: str) -> bool:
    """Accept only the exact live Sage identity bound to the durable intent."""

    if (
        type(identity) is not dict
        or identity.get("success") is not True
        or type(identity.get("fingerprint")) is not int
        or identity.get("network_id") != network
    ):
        return False
    observed_hash = hashlib.sha256(
        f"fingerprint:{identity['fingerprint']}".encode("utf-8")
    ).hexdigest()
    return observed_hash == wallet_hash


def _prepared_creation_selected_coin(intent: Any) -> str:
    if type(intent) is not dict or intent.get("lifecycle_state") != "prepared":
        return ""
    raw = intent.get("selected_coin_ids_json")
    if type(raw) is not str or len(raw) > 4096:
        return ""
    try:
        selected = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if type(selected) is not list or len(selected) != 1:
        return ""
    return _hex_id(selected[0])


def _recover_unlocked_prepared_creation(
    blocker: Any,
    *,
    wallet_hash: str,
    network: str,
    wallet_facade: Any,
    database_module: Any,
) -> bool:
    """Terminalize a PREPARED create only when Sage proves no live effect.

    Sage offer creation is an off-chain lock.  If the exact selected coin is
    still owned, unspent, and has no Sage offer_id, the interrupted operation
    cannot have a live wallet effect.  Two matching identity reads bind the
    observation to the configured wallet before the durable reservation is
    released.
    """

    if type(blocker) is not dict:
        return False
    intent_id = blocker.get("intent_id")
    operation_id = blocker.get("operation_id")
    event_id = blocker.get("event_id")
    if (
        type(intent_id) is not str
        or not intent_id
        or operation_id != f"create:{intent_id}"
        or event_id != f"{operation_id}:prepared"
        or blocker.get("operation_type") != "CREATE"
        or blocker.get("attempt") != 1
        or blocker.get("phase") != "PREPARED"
        or blocker.get("outcome") != "PREPARED"
        or blocker.get("reason_code") != "INTENT_PREPARED"
        or blocker.get("blocks_mutation") != 1
    ):
        return False
    validator = getattr(database_module, "validate_offer_operation_event", None)
    if not callable(validator):
        return False
    event = validator(blocker)
    if type(event) is not dict or event.get("event_id") != event_id:
        return False
    intent = database_module.get_offer_intent(intent_id)
    coin_id = _prepared_creation_selected_coin(intent)
    if (
        not coin_id
        or intent.get("wallet_fingerprint_hash") != wallet_hash
        or str(intent.get("network") or "").strip().lower() != network
    ):
        return False
    backend_reader = getattr(wallet_facade, "get_wallet_backend_authority", None)
    if not callable(backend_reader) or backend_reader() != "sage":
        return False
    identity_reader = getattr(wallet_facade, "get_wallet_identity", None)
    coin_reader = getattr(wallet_facade, "get_coins_by_ids", None)
    if not callable(identity_reader) or not callable(coin_reader):
        return False
    identity_before = identity_reader()
    if not _wallet_identity_matches(identity_before, wallet_hash, network):
        return False
    raw_coins = coin_reader([coin_id])
    if type(raw_coins) is dict and raw_coins.get("success") is True:
        raw_coins = raw_coins.get("records")
    if type(raw_coins) is not dict or len(raw_coins) > 16:
        return False
    matching = []
    for raw_id, record in raw_coins.items():
        if _hex_id(raw_id) == coin_id:
            matching.append(record)
        elif type(record) is dict and _hex_id(record.get("coin_id")) == coin_id:
            matching.append(record)
    if len(matching) != 1 or type(matching[0]) is not dict:
        return False
    coin = matching[0]
    if (
        type(coin.get("amount")) is not int
        or coin["amount"] <= 0
        or coin.get("offer_id") is not None
        or coin.get("spent_height") not in {None, 0}
    ):
        return False
    identity_after = identity_reader()
    if (
        not _wallet_identity_matches(identity_after, wallet_hash, network)
        or identity_after.get("fingerprint") != identity_before.get("fingerprint")
        or identity_after.get("network_id") != identity_before.get("network_id")
    ):
        return False
    try:
        prepared_wallet_identity = json.loads(event["wallet_identity_json"])
    except (KeyError, TypeError, ValueError):
        return False
    if type(prepared_wallet_identity) is not dict:
        return False
    finalized_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    finalized = database_module.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:finalized:startup-unlocked",
        lifecycle_state="creation_failed",
        outcome="FAILED",
        wallet_identity_json=prepared_wallet_identity,
        evidence_json={
            "effect_attempted": False,
            "failure_stage": "startup_recovery",
            "selected_coin_id": coin_id,
            "sage_coin_owned": True,
            "sage_coin_unspent": True,
            "sage_offer_id": None,
            "wallet_identity_before": {
                "fingerprint": identity_before["fingerprint"],
                "network_id": identity_before["network_id"],
            },
            "wallet_identity_after": {
                "fingerprint": identity_after["fingerprint"],
                "network_id": identity_after["network_id"],
            },
        },
        reason_code="CREATE_PREPARED_INPUT_PROVEN_UNLOCKED",
        finalized_at=finalized_at,
        finalize_selected_coin_reservations=True,
    )
    return (
        type(finalized) is dict
        and finalized.get("lifecycle_state") == "creation_failed"
    )


def _resolve_cleared_startup_latch(database_module: Any) -> bool:
    """Resolve a stale latch only through the database's journal proof gate."""

    latch_reader = getattr(database_module, "get_runtime_safety_latch", None)
    resolver = getattr(database_module, "resolve_runtime_safety_latch", None)
    if not callable(latch_reader) or not callable(resolver):
        return False
    latch = latch_reader()
    if type(latch) is not dict or latch.get("state") != "tripped":
        return False
    generation = latch.get("generation")
    raw_ids = latch.get("blocking_operation_ids_json")
    if type(generation) is not int or type(raw_ids) is not str or len(raw_ids) > 65536:
        return False
    try:
        operation_ids = json.loads(raw_ids)
    except (TypeError, ValueError):
        return False
    if (
        type(operation_ids) is not list
        or len(operation_ids) > 256
        or any(type(value) is not str or not value for value in operation_ids)
    ):
        return False
    resolved = resolver(
        expected_generation=generation,
        resolved_operation_ids=operation_ids,
    )
    return type(resolved) is dict and resolved.get("resolved") is True


def _atomic_amount(value: Any, scale: Decimal, label: str) -> str:
    try:
        amount = Decimal(str(value)) * scale
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    integral = amount.to_integral_value()
    if amount != integral or integral <= 0:
        raise ValueError(f"{label} is not an exact positive atomic amount")
    return str(int(integral))


def _cancel_cohort_manifest(blocker: Any, database_module: Any) -> dict | None:
    """Identify the exact durable cancellation cohort owning one blocker."""

    if type(blocker) is not dict:
        return None
    try:
        evidence = json.loads(blocker["evidence_json"])
        cohort_id = evidence.get("cohort_id") if type(evidence) is dict else None
        if type(cohort_id) is not str or not cohort_id:
            return None
        manifest = database_module.get_offer_cancel_cohort_manifest(cohort_id)
        validator = getattr(
            database_module, "validate_offer_cancel_cohort_manifest", None
        )
        if callable(validator):
            manifest = validator(manifest)
        if (
            type(manifest) is not dict
            or manifest.get("member_count", 0) < 2
            or type(manifest.get("members")) is not list
            or blocker.get("operation_id")
            not in {member.get("operation_id") for member in manifest["members"]}
        ):
            return None
        return manifest
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _native_bulk_cancel_manifest(blocker: Any, database_module: Any) -> dict | None:
    """Identify the exact durable Sage bulk cohort owning one blocker."""

    manifest = _cancel_cohort_manifest(blocker, database_module)
    if manifest is None:
        return None
    try:
        prepared = database_module.get_offer_cancel_cohort_prepared_events(
            manifest["cohort_id"]
        )
        if type(prepared) is not list or len(prepared) != manifest["member_count"]:
            return None
        protocols = []
        for event in prepared:
            prepared_evidence = json.loads(event["evidence_json"])
            wallet_effect = (
                prepared_evidence.get("wallet_effect")
                if type(prepared_evidence) is dict
                else None
            )
            batch = wallet_effect.get("batch") if type(wallet_effect) is dict else None
            protocols.append(batch.get("protocol") if type(batch) is dict else None)
        if set(protocols) != {"sage_native_cancel_offers_zero_plus_fee_v1"}:
            return None
        return manifest
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _legacy_intent(
    candidate: Any, wallet_hash: str, network: str, decimals: int
) -> dict:
    if type(candidate) is not dict:
        raise ValueError("legacy reservation candidate is malformed")
    trade_id = _hex_id(candidate.get("trade_id"))
    coin_id = _hex_id(candidate.get("coin_id"))
    asset_id = _hex_id(candidate.get("cat_asset_id"))
    side = candidate.get("side")
    tier = candidate.get("tier")
    offer_text = candidate.get("offer_bech32")
    if (
        not trade_id
        or not coin_id
        or not asset_id
        or side not in {"buy", "sell"}
        or type(tier) is not str
        or not tier.strip()
        or type(offer_text) is not str
        or not offer_text
        or type(decimals) is not int
        or not 0 <= decimals <= 18
    ):
        raise ValueError("legacy reservation candidate identity is invalid")
    xch = _atomic_amount(candidate.get("size_xch"), _XCH_SCALE, "legacy XCH amount")
    cat = _atomic_amount(
        candidate.get("size_cat"), Decimal(10) ** decimals, "legacy CAT amount"
    )
    prepared_at = _canonical_utc(candidate.get("created_at"))
    return {
        "intent_id": f"legacy-startup:{trade_id}",
        "wallet_fingerprint_hash": wallet_hash,
        "network": network,
        "asset_id": asset_id,
        "side": side,
        "tier": tier.strip(),
        "offered_amount_atomic": xch if side == "buy" else cat,
        "requested_amount_atomic": cat if side == "buy" else xch,
        "selected_coin_ids_json": json.dumps([coin_id], separators=(",", ":")),
        "selected_coin_ids": [coin_id],
        "offer_text_sha256": hashlib.sha256(offer_text.encode("utf-8")).hexdigest(),
        "sage_trade_id": trade_id,
        "prepared_at": prepared_at,
        "confirmed_at": prepared_at,
        "fee_mojos_xch": candidate.get("fee_mojos_xch", 0),
        "coin_purpose": candidate.get("coin_purpose"),
    }


def recover_legacy_sage_reservations(
    *,
    wallet_fingerprint_hash: str,
    network: str,
    wallet_facade: Any = None,
    database_module: Any = None,
    reconciliation_module: Any = None,
    config: Any = None,
    deadline_seconds: float = 60.0,
) -> dict[str, int]:
    """Recover proof-bound startup offer blockers using fresh Sage evidence.

    The public name is retained for compatibility with the desktop startup
    coordinator.  In addition to old pre-registry reservations, this boundary
    settles a modern submitted-cancel journal only when Sage provides the
    exact Task 8/9 cancellation proof required by normal reconciliation.
    """

    wallet_hash = _hex_id(wallet_fingerprint_hash)
    if not wallet_hash or type(network) is not str or not network.strip():
        raise ValueError("legacy recovery wallet binding is invalid")
    safe_network = network.strip().lower()
    if database_module is None:
        import database as database_module
    if reconciliation_module is None:
        import offer_reconciliation as reconciliation_module
    if wallet_facade is None:
        import wallet as wallet_facade
    if config is None:
        from config import cfg as config
    decimals = getattr(config, "CAT_DECIMALS", None)
    if type(decimals) is not int or not 0 <= decimals <= 18:
        raise ValueError("legacy recovery CAT decimals are invalid")

    candidates = database_module.get_legacy_startup_reservation_candidates(limit=128)
    if type(candidates) is not list or len(candidates) > 128:
        raise RuntimeError("legacy reservation inventory is malformed")
    if type(deadline_seconds) not in {int, float} or not 0 < deadline_seconds <= 300:
        raise ValueError("legacy recovery deadline must be between 0 and 300 seconds")
    deadline = time.monotonic() + float(deadline_seconds)
    parsed_candidates: list[tuple[Any, dict | None]] = []
    seed_coin_ids: set[str] = set()
    for candidate in candidates:
        try:
            synthetic = _legacy_intent(candidate, wallet_hash, safe_network, decimals)
        except Exception:
            synthetic = None
        parsed_candidates.append((candidate, synthetic))
        if synthetic is not None:
            seed_coin_ids.update(synthetic["selected_coin_ids"])
    live_wallet_facade = wallet_facade
    wallet_facade = _CachedReadOnlyWallet(
        wallet_facade,
        seed_coin_ids=seed_coin_ids,
    )
    result = {"examined": len(candidates), "recovered": 0, "remaining": 0}
    wallet_identity = {
        "wallet_fingerprint_hash": wallet_hash,
        "network": safe_network,
    }

    for index, (candidate, synthetic) in enumerate(parsed_candidates):
        if time.monotonic() >= deadline:
            result["remaining"] += len(parsed_candidates) - index
            break
        try:
            if synthetic is None:
                raise ValueError("legacy reservation candidate is malformed")
            intent_id = synthetic["intent_id"]
            existing = database_module.get_offer_intent(intent_id)
            evidence_target = (
                existing
                if type(existing) is dict
                and existing.get("lifecycle_state")
                in {"created", "unknown", "conflicted"}
                else synthetic
            )
            evidence = reconciliation_module.load_authoritative_evidence(
                evidence_target, wallet_facade=wallet_facade
            )
            observed_at = (
                evidence.get("observed_at") if type(evidence) is dict else None
            )
            classification = reconciliation_module.classify_terminal_evidence(
                evidence_target, evidence, now=observed_at
            )
            if (
                type(classification) is not dict
                or classification.get("classification")
                != reconciliation_module.EXPIRED_PROVEN
            ):
                result["remaining"] += 1
                continue

            durable_json, evidence_sha256 = (
                reconciliation_module.canonical_evidence_and_digest(
                    {"classification": classification, "evidence": evidence},
                    max_bytes=65536,
                )
            )

            if existing is None:
                database_module.prepare_offer_intent(
                    intent_id=intent_id,
                    operation_id=f"create:{intent_id}",
                    event_id=f"create:{intent_id}:prepared",
                    run_id=f"legacy-startup:{wallet_hash[:16]}",
                    wallet_fingerprint_hash=wallet_hash,
                    network=safe_network,
                    asset_id=synthetic["asset_id"],
                    side=synthetic["side"],
                    tier=synthetic["tier"],
                    purpose="legacy_startup_migration",
                    coin_purpose=synthetic["coin_purpose"],
                    offered_amount_atomic=synthetic["offered_amount_atomic"],
                    requested_amount_atomic=synthetic["requested_amount_atomic"],
                    selected_coin_ids_json=synthetic["selected_coin_ids"],
                    cat_decimals=decimals,
                    fee_mojos_xch=synthetic["fee_mojos_xch"],
                    fee_provenance="LEGACY_OFFER_PROJECTION_V1",
                    wallet_identity_json=wallet_identity,
                    evidence_json={
                        "migration": "legacy_startup_expiry",
                        "trade_id": synthetic["sage_trade_id"],
                    },
                    prepared_at=synthetic["prepared_at"],
                    reserve_selected_coins=False,
                    require_new_intent=False,
                )
                existing = database_module.get_offer_intent(intent_id)

            reconciled = database_module.commit_legacy_expired_offer_intent(
                intent_id=intent_id,
                sage_trade_id=synthetic["sage_trade_id"],
                offer_text_sha256=synthetic["offer_text_sha256"],
                wallet_fingerprint_hash=wallet_hash,
                network=safe_network,
                classification=reconciliation_module.EXPIRED_PROVEN,
                reason_code=classification.get(
                    "reason_code", "AUTHORITATIVE_EXPIRY_PROOF"
                ),
                wallet_identity_json=wallet_identity,
                evidence_json=durable_json,
                evidence_sha256=evidence_sha256,
                confirmed_at=synthetic["confirmed_at"],
                reconciled_at=observed_at,
            )
            if (
                type(reconciled) is dict
                and type(reconciled.get("event")) is dict
                and reconciled["event"].get("outcome")
                == reconciliation_module.EXPIRED_PROVEN
            ):
                result["recovered"] += 1
            else:
                result["remaining"] += 1
        except Exception:
            result["remaining"] += 1

    blocker_reader = getattr(
        database_module, "get_unresolved_offer_operation_blockers", None
    )
    blockers = blocker_reader() if callable(blocker_reader) else []
    if type(blockers) is not list or len(blockers) > 128:
        raise RuntimeError("startup offer operation inventory is malformed")
    prepared_creations = [
        blocker
        for blocker in blockers
        if type(blocker) is dict
        and blocker.get("operation_type") == "CREATE"
        and blocker.get("phase") == "PREPARED"
        and blocker.get("outcome") == "PREPARED"
        and blocker.get("blocks_mutation") == 1
    ]
    result["examined"] += len(prepared_creations)
    for index, blocker in enumerate(prepared_creations):
        if time.monotonic() >= deadline:
            result["remaining"] += len(prepared_creations) - index
            break
        try:
            if _recover_unlocked_prepared_creation(
                blocker,
                wallet_hash=wallet_hash,
                network=safe_network,
                wallet_facade=live_wallet_facade,
                database_module=database_module,
            ):
                result["recovered"] += 1
            else:
                result["remaining"] += 1
        except Exception:
            result["remaining"] += 1

    submitted_cancels = [
        blocker
        for blocker in blockers
        if type(blocker) is dict
        and blocker.get("operation_type") == "CANCEL"
        and blocker.get("phase") == "FINALIZED"
        and blocker.get("outcome") in {"CANCEL_SUBMITTED_UNCONFIRMED", "CANCEL_UNKNOWN"}
        and blocker.get("blocks_mutation") == 1
    ]
    result["examined"] += len(submitted_cancels)
    for index, blocker in enumerate(submitted_cancels):
        if time.monotonic() >= deadline:
            result["remaining"] += len(submitted_cancels) - index
            break
        try:
            intent_id = blocker.get("intent_id")
            if type(intent_id) is not str or not intent_id:
                raise ValueError("submitted cancel intent identity is unavailable")
            intent = database_module.get_offer_intent(intent_id)
            trade_id = _hex_id(
                intent.get("sage_trade_id") if type(intent) is dict else None
            )
            if (
                type(intent) is not dict
                or not trade_id
                or blocker.get("operation_id") != f"cancel:{trade_id}"
                or intent.get("wallet_fingerprint_hash") != wallet_hash
                or str(intent.get("network") or "").strip().lower() != safe_network
            ):
                raise ValueError("submitted cancel authority binding is invalid")
            evidence = reconciliation_module.load_authoritative_evidence(
                intent, wallet_facade=wallet_facade
            )
            observed_at = (
                evidence.get("observed_at") if type(evidence) is dict else None
            )
            bulk_manifest = _native_bulk_cancel_manifest(blocker, database_module)
            external_recovery_context = False
            if bulk_manifest is not None:
                manifest_operation_ids = {
                    member["operation_id"] for member in bulk_manifest["members"]
                }
                current_blockers = (
                    database_module.get_unresolved_offer_operation_blockers()
                )
                blocking_operation_ids = [
                    row.get("operation_id")
                    for row in current_blockers
                    if type(row) is dict
                    and row.get("operation_id") in manifest_operation_ids
                    and row.get("blocks_mutation") == 1
                ]
                cancel_context = reconciliation_module._derive_sage_bulk_cancel_context(
                    bulk_manifest,
                    blocking_operation_ids,
                    evidence,
                    database_module=database_module,
                    observed_at=observed_at,
                )
                if type(cancel_context) is not dict:
                    result["remaining"] += 1
                    continue
            else:
                cancel_context = None
                cohort_manifest = _cancel_cohort_manifest(blocker, database_module)
                derive_external = getattr(
                    reconciliation_module,
                    "_derive_aborted_cohort_recovery_cancel_context",
                    None,
                )
                if cohort_manifest is not None and callable(derive_external):
                    cancel_context = derive_external(
                        cohort_manifest,
                        [blocker["operation_id"]],
                        evidence,
                        database_module=database_module,
                        observed_at=observed_at,
                    )
                    external_recovery_context = type(cancel_context) is dict
                if cancel_context is None:
                    cancel_context = (
                        reconciliation_module._derive_single_cancel_context(
                            intent,
                            evidence,
                            database_module=database_module,
                            observed_at=observed_at,
                        )
                    )
            classification = reconciliation_module.classify_terminal_evidence(
                intent,
                evidence,
                cancel_context=cancel_context,
                now=observed_at,
            )
            terminal_classification = classification.get("classification")
            terminal_outcomes = {
                reconciliation_module.CANCELLED_PROVEN,
                reconciliation_module.FILLED_PROVEN,
                reconciliation_module.EXPIRED_PROVEN,
            }
            if (
                type(classification) is not dict
                or terminal_classification not in terminal_outcomes
                or (
                    terminal_classification == reconciliation_module.CANCELLED_PROVEN
                    and type(cancel_context) is not dict
                )
            ):
                result["remaining"] += 1
                continue
            reconcile_intent_ids = [intent_id]
            if (
                external_recovery_context
                and terminal_classification == reconciliation_module.CANCELLED_PROVEN
            ):
                reconcile_intent_ids = [
                    member["intent_id"]
                    for member in cancel_context["members"]
                    if member["intent_id"] != intent_id
                ] + [intent_id]
            reconciled = None
            for reconcile_intent_id in reconcile_intent_ids:
                member_intent = database_module.get_offer_intent(reconcile_intent_id)
                member_classification = (
                    reconciliation_module.classify_terminal_evidence(
                        member_intent,
                        evidence,
                        cancel_context=cancel_context,
                        now=observed_at,
                    )
                )
                if (
                    type(member_classification) is not dict
                    or member_classification.get("classification")
                    != terminal_classification
                ):
                    raise ValueError("external cohort recovery proof differs by member")
                reconciled = reconciliation_module.reconcile_offer(
                    reconcile_intent_id,
                    evidence=evidence,
                    cancel_context=cancel_context,
                    now=observed_at,
                )
                if (
                    type(reconciled) is not dict
                    or reconciled.get("applied") is not True
                    or reconciled.get("classification") != terminal_classification
                ):
                    raise ValueError("external cohort recovery could not be committed")
            if (
                type(reconciled) is dict
                and reconciled.get("applied") is True
                and reconciled.get("classification") == terminal_classification
            ):
                result["recovered"] += 1
            else:
                result["remaining"] += 1
        except Exception:
            result["remaining"] += 1
    try:
        _resolve_cleared_startup_latch(database_module)
    except Exception:
        # Reconciliation results above remain authoritative; latch cleanup is
        # best-effort and the next startup pass will retry it.
        pass
    return result
