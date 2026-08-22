#!/usr/bin/env python3
"""Checkpointed TEST 7 mainnet stability lab.

The command is dry-run by default. Wallet effects are available only through
``run_guarded_mutation`` after a fresh exact TEST 7 identity read and validation
of an explicitly initialised, isolated ``CMM_DATA_DIR``.

The checkpoint file is scheduling evidence only. It never grants wallet,
mutation-gate, operation-journal, reconciliation, or coin-release authority.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping


EXPECTED_BACKEND = "sage"
EXPECTED_NAME = "TEST 7"
EXPECTED_FINGERPRINT = 736588221
EXPECTED_NETWORK = "mainnet"
EXPECTED_KIND = "bls"
LIVE_CONFIRMATION = "TEST7-MAINNET-736588221"
IDENTITY_MAX_AGE_SECONDS = 10
LAB_MARKER_NAME = ".test7-stability-lab.json"
CHECKPOINT_NAME = "test7-stability-checkpoint.json"
LAB_PURPOSE = "catalyst-test7-mainnet-stability-lab"
LAB_SCHEMA_VERSION = 1

STAGES = (
    "inventory",
    "reconcile",
    "lifecycle",
    "restart",
    "stale-read",
    "long-gap",
    "replacement",
    "fill",
    "soak",
    "final-reconcile",
)

MUTATING_STAGES = frozenset(
    {
        "lifecycle",
        "restart",
        "long-gap",
        "replacement",
        "fill",
        "soak",
    }
)

RECONCILABLE_INTENT_STATES = frozenset(
    {
        "prepared",
        "submitted_unconfirmed",
        "creation_unknown",
        "created",
        "visible",
        "cancel_requested",
        "unknown",
        "conflicted",
    }
)


def _unsigned_self_take_offer_text(offer_text: Any) -> str | None:
    """Return the exact unsigned maker body needed for a Sage self-take."""

    try:
        from sage_offer_wire import unsigned_sage_offer_text
    except ImportError:
        return None
    return unsigned_sage_offer_text(offer_text)

_CHECKPOINT_EVIDENCE_KEYS = frozenset(
    {
        "success",
        "stage",
        "trade_id",
        "intent_id",
        "operation_id",
        "reason_code",
        "classification",
        "count",
    }
)


class LabRefusal(RuntimeError):
    """Stable fail-closed refusal raised before a lab wallet effect."""

    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _canonical_utc(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise LabRefusal("IDENTITY_TIME_INVALID")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_utc(value: Any) -> datetime:
    if type(value) is not str or not value.endswith("Z") or len(value) > 64:
        raise LabRefusal("IDENTITY_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError) as exc:
        raise LabRefusal("IDENTITY_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LabRefusal("IDENTITY_TIME_INVALID")
    return parsed.astimezone(timezone.utc)


def _default_user_data_directories(environment: Mapping[str, str]) -> set[Path]:
    candidates: set[Path] = set()
    appdata = environment.get("APPDATA")
    if type(appdata) is str and appdata:
        candidates.add((Path(appdata) / "Catalyst").resolve())
    if sys.platform == "darwin":
        candidates.add((Path.home() / "Library" / "Application Support" / "Catalyst").resolve())
    elif sys.platform != "win32":
        xdg = environment.get("XDG_DATA_HOME")
        base = Path(xdg) if type(xdg) is str and xdg else Path.home() / ".local" / "share"
        candidates.add((base / "Catalyst").resolve())
    return candidates


def _marker_payload(initialized_at: datetime) -> dict[str, Any]:
    return {
        "schema_version": LAB_SCHEMA_VERSION,
        "purpose": LAB_PURPOSE,
        "expected_backend": EXPECTED_BACKEND,
        "expected_name": EXPECTED_NAME,
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "expected_network": EXPECTED_NETWORK,
        "expected_kind": EXPECTED_KIND,
        "initialized_at_utc": _canonical_utc(initialized_at),
    }


def initialize_lab_directory(
    data_dir: str | os.PathLike[str], *, initialized_at: datetime | None = None
) -> Path:
    """Create or validate the explicit marker for one isolated lab directory."""

    path = Path(data_dir)
    if not path.is_absolute():
        raise LabRefusal("ISOLATED_DATA_DIR_REQUIRED")
    resolved = path.resolve()
    if resolved in _default_user_data_directories(os.environ):
        raise LabRefusal("PRODUCTION_DATA_DIR_FORBIDDEN")
    resolved.mkdir(parents=True, exist_ok=True)
    marker = resolved / LAB_MARKER_NAME
    now = datetime.now(timezone.utc) if initialized_at is None else initialized_at
    expected = _marker_payload(now)
    if marker.exists():
        try:
            current = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LabRefusal("LAB_MARKER_INVALID") from exc
        stable_expected = dict(expected)
        stable_expected["initialized_at_utc"] = current.get("initialized_at_utc")
        if type(current) is not dict or current != stable_expected:
            raise LabRefusal("LAB_MARKER_INVALID")
        _parse_utc(current.get("initialized_at_utc"))
        return resolved
    if any(resolved.iterdir()):
        raise LabRefusal("LAB_DIRECTORY_NOT_EMPTY")
    temporary = marker.with_suffix(marker.suffix + ".tmp")
    temporary.write_text(
        json.dumps(expected, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, marker)
    return resolved


def prepare_runtime_environment(
    *,
    data_dir: str | os.PathLike[str],
    environment: MutableMapping[str, str],
    source_root: str | os.PathLike[str],
) -> Path:
    """Bind CATalyst imports to the isolated TEST 7 lab configuration."""

    path = Path(data_dir)
    if not path.is_absolute():
        raise LabRefusal("ISOLATED_DATA_DIR_REQUIRED")
    resolved = path.resolve()
    if resolved in _default_user_data_directories(environment):
        raise LabRefusal("PRODUCTION_DATA_DIR_FORBIDDEN")
    _validate_marker(resolved)
    if not isinstance(environment, MutableMapping):
        raise LabRefusal("ISOLATED_DATA_DIR_REQUIRED")
    environment.update(
        {
            "CMM_DATA_DIR": str(resolved),
            "WALLET_TYPE": EXPECTED_BACKEND,
            "SAGE_FINGERPRINT": str(EXPECTED_FINGERPRINT),
            "WALLET_EXPECTED_NAME": EXPECTED_NAME,
            "WALLET_EXPECTED_KEY_KIND": EXPECTED_KIND,
            "CATALYST_NETWORK_ID": EXPECTED_NETWORK,
            "_CATALYST_PRESERVE_PROCESS_ENV": "1",
        }
    )
    source = str(Path(source_root).resolve())
    if Path(source).is_dir() and source not in sys.path:
        sys.path.insert(0, source)
    return resolved


def load_public_modules(
    *, import_module: Callable[[str], Any] = importlib.import_module
) -> dict[str, Any]:
    """Load only CATalyst's public facade and repository modules."""

    if not callable(import_module):
        raise LabRefusal("RUNTIME_IMPORT_INVALID")
    names = (
        "wallet",
        "database",
        "offer_reconciliation",
        "offer_manager",
        "api_server",
        "dexie_manager",
        "price_engine",
        "coin_manager",
        "runtime_recovery",
    )
    return {name: import_module(name) for name in names}


def _validate_marker(data_dir: Path) -> None:
    marker = data_dir / LAB_MARKER_NAME
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LabRefusal("LAB_MARKER_REQUIRED") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LabRefusal("LAB_MARKER_INVALID") from exc
    if type(payload) is not dict:
        raise LabRefusal("LAB_MARKER_INVALID")
    expected = _marker_payload(_parse_utc(payload.get("initialized_at_utc")))
    if payload != expected:
        raise LabRefusal("LAB_MARKER_INVALID")


def validate_test7_identity(
    snapshot: Any, *, now: datetime | None = None
) -> dict[str, Any]:
    """Return a redacted exact TEST 7 identity or raise a stable refusal."""

    observed_now = datetime.now(timezone.utc) if now is None else now
    if (
        type(observed_now) is not datetime
        or observed_now.tzinfo is None
        or observed_now.utcoffset() is None
    ):
        raise LabRefusal("IDENTITY_TIME_INVALID")
    observed_now = observed_now.astimezone(timezone.utc)
    if type(snapshot) is not dict or snapshot.get("success") is not True:
        raise LabRefusal("IDENTITY_UNAVAILABLE")
    if type(snapshot.get("backend")) is not str or snapshot["backend"] != EXPECTED_BACKEND:
        raise LabRefusal("IDENTITY_BACKEND_MISMATCH")
    if type(snapshot.get("name")) is not str or snapshot["name"] != EXPECTED_NAME:
        raise LabRefusal("IDENTITY_NAME_MISMATCH")
    if (
        type(snapshot.get("fingerprint")) is not int
        or snapshot["fingerprint"] != EXPECTED_FINGERPRINT
    ):
        raise LabRefusal("IDENTITY_FINGERPRINT_MISMATCH")
    if (
        type(snapshot.get("network_id")) is not str
        or snapshot["network_id"] != EXPECTED_NETWORK
    ):
        raise LabRefusal("IDENTITY_NETWORK_MISMATCH")
    if type(snapshot.get("kind")) is not str or snapshot["kind"] != EXPECTED_KIND:
        raise LabRefusal("IDENTITY_KIND_MISMATCH")
    if snapshot.get("has_secrets") is not True:
        raise LabRefusal("SIGNING_DISABLED")
    observed_at = _parse_utc(snapshot.get("observed_at_utc"))
    age_seconds = (observed_now - observed_at).total_seconds()
    if age_seconds < 0:
        raise LabRefusal("IDENTITY_FROM_FUTURE")
    if age_seconds > IDENTITY_MAX_AGE_SECONDS:
        raise LabRefusal("IDENTITY_STALE")
    return {
        "backend": EXPECTED_BACKEND,
        "name": EXPECTED_NAME,
        "fingerprint": EXPECTED_FINGERPRINT,
        "network_id": EXPECTED_NETWORK,
        "kind": EXPECTED_KIND,
        "has_secrets": True,
        "observed_at_utc": _canonical_utc(observed_at),
        "age_seconds": age_seconds,
    }


def _wallet_rows(result: Any) -> list[dict[str, Any]]:
    if type(result) is not dict or result.get("success") is not True:
        raise LabRefusal("WALLET_INVENTORY_UNAVAILABLE")
    rows = result.get("wallets")
    if type(rows) is not list or not rows or not all(type(row) is dict for row in rows):
        raise LabRefusal("WALLET_INVENTORY_UNAVAILABLE")
    return rows


def _wallet_balance(result: Any, wallet_id: int) -> dict[str, int]:
    if type(result) is not dict or result.get("success") is not True:
        raise LabRefusal("BALANCE_UNAVAILABLE")
    balance = result.get("wallet_balance")
    if type(balance) is not dict or balance.get("wallet_id") != wallet_id:
        raise LabRefusal("BALANCE_UNAVAILABLE")
    confirmed = balance.get("confirmed_wallet_balance")
    spendable = balance.get("spendable_balance")
    if any(type(value) is not int or value < 0 for value in (confirmed, spendable)):
        raise LabRefusal("BALANCE_UNAVAILABLE")
    if spendable > confirmed:
        raise LabRefusal("BALANCE_INCONSISTENT")
    return {"confirmed_mojos": confirmed, "spendable_mojos": spendable}


class CatalystLabRuntime:
    """Narrow testable adapter over CATalyst's public application modules."""

    def __init__(self, modules: Mapping[str, Any]):
        required = {
            "wallet",
            "database",
            "offer_reconciliation",
            "offer_manager",
            "api_server",
            "dexie_manager",
            "price_engine",
            "coin_manager",
            "runtime_recovery",
        }
        if not isinstance(modules, Mapping) or not required.issubset(modules):
            raise LabRefusal("RUNTIME_IMPORT_INVALID")
        self.wallet = modules["wallet"]
        self.database = modules["database"]
        self.reconciliation = modules["offer_reconciliation"]
        self.offer_manager_module = modules["offer_manager"]
        self.api_server = modules["api_server"]
        self.dexie_manager_module = modules["dexie_manager"]
        self.price_engine_module = modules["price_engine"]
        self.coin_manager_module = modules["coin_manager"]
        self.runtime_recovery_module = modules["runtime_recovery"]

    def inventory(
        self,
        *,
        now: datetime | Callable[[], datetime] | None = None,
    ) -> dict[str, Any]:
        """Read and validate exact identity, balances, CATs, and full history."""

        identity_snapshot = self.wallet.get_wallet_identity()
        identity_now = now() if callable(now) else now
        identity = validate_test7_identity(identity_snapshot, now=identity_now)
        rows = _wallet_rows(self.wallet.get_wallets())
        xch = [
            row
            for row in rows
            if type(row.get("id")) is int and row.get("type") == 0
        ]
        sbx = [
            row
            for row in rows
            if type(row.get("id")) is int
            and row.get("type") == 6
            and type(row.get("name")) is str
            and re.search(r"(?:^|[^A-Z0-9])SBX(?:[^A-Z0-9]|$)", row["name"].upper())
            and type(row.get("data")) is str
            and re.fullmatch(r"[0-9a-fA-F]{64}", row["data"]) is not None
        ]
        if len(xch) != 1:
            raise LabRefusal("XCH_WALLET_AMBIGUOUS")
        if len(sbx) != 1:
            raise LabRefusal("SBX_WALLET_AMBIGUOUS")
        xch_wallet_id = xch[0]["id"]
        sbx_wallet_id = sbx[0]["id"]
        balances = {
            "xch": _wallet_balance(
                self.wallet.get_wallet_balance(xch_wallet_id), xch_wallet_id
            ),
            "sbx": _wallet_balance(
                self.wallet.get_wallet_balance(sbx_wallet_id), sbx_wallet_id
            ),
        }
        history_reader = getattr(
            self.wallet,
            "get_authoritative_offer_history",
            self.wallet.get_all_offers,
        )
        history = self.reconciliation.load_sage_offer_history(
            get_all_offers=history_reader,
            include_completed=True,
        )
        if (
            type(history) is not dict
            or history.get("complete") is not True
            or history.get("read_error") is not None
            or type(history.get("records")) is not list
        ):
            raise LabRefusal("OFFER_HISTORY_INCOMPLETE")
        pagination = history.get("pagination")
        if type(pagination) is not dict:
            pagination = {}
        return {
            "success": True,
            "stage": "inventory",
            "count": len(rows),
            "identity": identity,
            "xch": {"wallet_id": xch_wallet_id},
            "sbx": {
                "wallet_id": sbx_wallet_id,
                "asset_id": sbx[0]["data"].lower(),
            },
            "balances": balances,
            "offer_history": {
                "complete": True,
                "record_count": len(history["records"]),
                "observed_at": history.get("observed_at"),
                "provenance": history.get("provenance"),
                "pages_read": pagination.get("pages_read"),
            },
        }

    def _require_database_integrity(self) -> None:
        self.database.init_database()
        integrity = self.database.check_db_integrity()
        if type(integrity) is not dict or integrity.get("ok") is not True:
            raise LabRefusal("DATABASE_INTEGRITY_FAILED")

    def _configure_sbx(self, inventory: Any) -> Any:
        if type(inventory) is not dict or inventory.get("success") is not True:
            raise LabRefusal("WALLET_INVENTORY_UNAVAILABLE")
        sbx = inventory.get("sbx")
        if type(sbx) is not dict:
            raise LabRefusal("SBX_WALLET_AMBIGUOUS")
        wallet_id = sbx.get("wallet_id")
        asset_id = sbx.get("asset_id")
        if (
            type(wallet_id) is not int
            or wallet_id < 1
            or type(asset_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", asset_id) is None
        ):
            raise LabRefusal("SBX_WALLET_AMBIGUOUS")
        cfg = getattr(self.offer_manager_module, "cfg", None)
        if cfg is None:
            raise LabRefusal("RUNTIME_CONFIGURATION_UNAVAILABLE")
        cfg.CAT_ASSET_ID = asset_id
        cfg.CAT_WALLET_ID = wallet_id
        cfg.CAT_DECIMALS = 3
        cfg.CAT_TICKER_ID = "SBX_XCH"
        cfg.CAT_NAME = "SBX"
        cfg.DRY_RUN = False
        cfg.TIER_ENABLED = False
        cfg.MAX_PARALLEL_OFFERS = 1
        return cfg

    def market_price(self, inventory: Any) -> dict[str, Any]:
        """Fetch one current SBX/XCH midpoint through the public price engine."""

        cfg = self._configure_sbx(inventory)
        engine_type = getattr(self.price_engine_module, "PriceEngine", None)
        if not callable(engine_type):
            raise LabRefusal("PRICE_ENGINE_UNAVAILABLE")
        result = engine_type().get_price(
            cat_asset_id=cfg.CAT_ASSET_ID,
            cat_decimals=cfg.CAT_DECIMALS,
            ticker_id=cfg.CAT_TICKER_ID,
        )
        price = result.get("mid_price") if type(result) is dict else None
        if type(price) is not Decimal or not price.is_finite() or price <= 0:
            raise LabRefusal("PRICE_UNAVAILABLE")
        strategy = result.get("strategy_used")
        if type(strategy) is not str or not strategy or len(strategy) > 64:
            raise LabRefusal("PRICE_UNAVAILABLE")
        return {
            "success": True,
            "mid_price_xch": str(price),
            "strategy": strategy,
        }

    def _require_zero_blockers(self) -> dict[str, Any]:
        try:
            snapshot = self.database.get_stability_startup_recovery_snapshot()
        except BaseException as exc:
            raise LabRefusal("SAFETY_SNAPSHOT_UNAVAILABLE") from exc
        if type(snapshot) is not dict:
            raise LabRefusal("SAFETY_SNAPSHOT_UNAVAILABLE")
        latch = snapshot.get("latch")
        counts = snapshot.get("blocker_counts")
        reservations = snapshot.get("reservation_issues")
        publications = snapshot.get("publication_issues")
        digest = snapshot.get("authority_digest")
        if (
            type(latch) is not dict
            or type(counts) is not dict
            or type(reservations) is not list
            or type(publications) is not list
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or any(type(value) is not int or value < 0 for value in counts.values())
        ):
            raise LabRefusal("SAFETY_SNAPSHOT_UNAVAILABLE")
        if (
            latch.get("state") != "resolved"
            or any(value != 0 for value in counts.values())
            or reservations
            or publications
        ):
            raise LabRefusal("UNRESOLVED_BLOCKERS")
        return {"blocker_counts": dict(counts), "authority_digest": digest}

    def reconcile(self) -> dict[str, Any]:
        """Reconcile every durable nonterminal intent, then require a clean gate."""

        self._require_database_integrity()
        intents = self.database.get_offer_intents_for_registry()
        if type(intents) is not list or not all(type(row) is dict for row in intents):
            raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
        candidates = [
            row
            for row in intents
            if row.get("lifecycle_state") in RECONCILABLE_INTENT_STATES
        ]
        classifications: dict[str, int] = {}
        for intent in candidates:
            intent_id = intent.get("intent_id")
            if type(intent_id) is not str or not intent_id:
                raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
            result = self.reconciliation.reconcile_offer(
                intent_id,
                wallet_facade=self.wallet,
            )
            classification = result.get("classification") if type(result) is dict else None
            if (
                type(classification) is not str
                or not classification.isascii()
                or not classification
                or len(classification) > 64
            ):
                raise LabRefusal("RECONCILIATION_MALFORMED")
            classifications[classification] = classifications.get(classification, 0) + 1
        safety = self._require_zero_blockers()
        return {
            "success": True,
            "stage": "reconcile",
            "count": len(candidates),
            "classifications": classifications,
            **safety,
        }

    def _durable_publisher(self) -> Any:
        lease = self.database.get_runtime_mutation_lease()
        if (
            type(lease) is not dict
            or lease.get("active") != 1
            or type(lease.get("owner_run_id")) is not str
            or not lease["owner_run_id"]
            or lease.get("network") != EXPECTED_NETWORK
            or type(lease.get("expires_at")) is not str
        ):
            raise LabRefusal("MUTATION_RUNTIME_NOT_ALLOWED")
        publisher_type = getattr(self.dexie_manager_module, "DexieManager", None)
        if not callable(publisher_type):
            raise LabRefusal("PUBLICATION_UNAVAILABLE")
        publisher = publisher_type()

        def now_provider() -> str:
            return _canonical_utc(datetime.now(timezone.utc))

        def lease_expires_provider(_observed_at: Any) -> str:
            current = self.database.get_runtime_mutation_lease()
            if (
                type(current) is not dict
                or current.get("active") != 1
                or current.get("owner_run_id") != lease["owner_run_id"]
                or type(current.get("expires_at")) is not str
            ):
                raise LabRefusal("MUTATION_RUNTIME_NOT_ALLOWED")
            return current["expires_at"]

        publisher.enable_durable_outbox(
            owner_run_id=lease["owner_run_id"],
            now_provider=now_provider,
            lease_expires_provider=lease_expires_provider,
            network=EXPECTED_NETWORK,
        )
        return publisher

    def _sync_coin_registry(self, *, required_xch_mojos: int) -> dict[str, int]:
        """Import wallet coins and allocate one exact lab spend authority.

        The isolated registry starts without policy purposes.  Allocate only
        the smallest sufficient free, non-reserve, non-attributed XCH coin to
        the lifecycle purpose, then read it back before offer selection.  This
        changes only the isolated lab database; it does not mutate the wallet.
        """

        if type(required_xch_mojos) is not int or required_xch_mojos < 1:
            raise LabRefusal("COIN_REGISTRY_UNAVAILABLE")
        manager_type = getattr(self.coin_manager_module, "CoinManager", None)
        if not callable(manager_type):
            raise LabRefusal("COIN_REGISTRY_UNAVAILABLE")
        manager_type().reconcile_with_wallet()
        counts: dict[str, int] = {}
        rows_by_wallet: dict[str, list[dict[str, Any]]] = {}
        for wallet_type in ("xch", "cat"):
            rows = self.database.get_free_coins(wallet_type)
            if type(rows) is not list or not all(type(row) is dict for row in rows):
                raise LabRefusal("COIN_REGISTRY_UNAVAILABLE")
            rows_by_wallet[wallet_type] = rows
            counts[wallet_type] = len(rows)
        # The lifecycle is deliberately a BUY and spends only XCH. SBX is
        # still proven present and spendable by ``inventory``; its single
        # large coin need not be imported as spend authority for this stage.
        if counts["xch"] < 1:
            raise LabRefusal("COIN_REGISTRY_EMPTY")

        tier_reader = getattr(
            self.coin_manager_module,
            "coin_size_tier_for_slot_position",
            None,
        )
        designation_writer = getattr(self.database, "set_coin_designation", None)
        if not callable(tier_reader) or not callable(designation_writer):
            raise LabRefusal("COIN_PURPOSE_UNAVAILABLE")
        assigned_tier = tier_reader("mid", side="buy")
        if assigned_tier not in {"inner", "mid", "outer", "extreme"}:
            raise LabRefusal("COIN_PURPOSE_UNAVAILABLE")

        def normalized_coin_id(row: Mapping[str, Any]) -> str | None:
            coin_id = row.get("coin_id")
            if type(coin_id) is not str:
                return None
            normalized = coin_id.lower()
            bare = normalized[2:] if normalized.startswith("0x") else normalized
            if re.fullmatch(r"[0-9a-f]{64}", bare) is None:
                return None
            return normalized

        eligible: list[tuple[int, str, dict[str, Any]]] = []
        for row in rows_by_wallet["xch"]:
            coin_id = normalized_coin_id(row)
            amount = row.get("amount_mojos")
            purpose = row.get("purpose")
            designation = row.get("designation")
            if (
                coin_id is None
                or type(amount) is not int
                or type(amount) is bool
                or amount < required_xch_mojos
                or row.get("status") != "free"
                or row.get("trade_id") is not None
                or designation == "reserve"
                or purpose not in {None, "lifecycle"}
            ):
                continue
            eligible.append((amount, coin_id, row))
        if not eligible:
            raise LabRefusal("LIFECYCLE_COIN_UNAVAILABLE")

        # A differently purposed preferred coin could otherwise outrank the
        # lab coin in OfferManager's deterministic selector. Refuse instead of
        # borrowing or rewriting that authority.
        for row in rows_by_wallet["xch"]:
            if (
                row.get("status") == "free"
                and row.get("trade_id") is None
                and row.get("designation") in {"tier_spare", "tier_active"}
                and row.get("purpose") not in {None, "lifecycle"}
                and type(row.get("amount_mojos")) is int
                and row["amount_mojos"] >= required_xch_mojos
            ):
                raise LabRefusal("COIN_PURPOSE_CONFLICT")

        _amount, selected_coin_id, _selected = min(
            eligible, key=lambda item: (item[0], item[1])
        )
        if designation_writer(
            selected_coin_id,
            "tier_spare",
            assigned_tier,
            purpose="lifecycle",
        ) is not True:
            raise LabRefusal("COIN_PURPOSE_ASSIGNMENT_FAILED")

        verified = self.database.get_free_coins("xch")
        if type(verified) is not list:
            raise LabRefusal("COIN_PURPOSE_ASSIGNMENT_FAILED")
        selected_rows = [
            row
            for row in verified
            if type(row) is dict and normalized_coin_id(row) == selected_coin_id
        ]
        if (
            len(selected_rows) != 1
            or selected_rows[0].get("status") != "free"
            or selected_rows[0].get("trade_id") is not None
            or selected_rows[0].get("designation") != "tier_spare"
            or selected_rows[0].get("assigned_tier") != assigned_tier
            or selected_rows[0].get("purpose") != "lifecycle"
        ):
            raise LabRefusal("COIN_PURPOSE_ASSIGNMENT_FAILED")
        counts["lifecycle"] = 1
        return counts

    def _completed_lifecycle(self, inventory: Any) -> dict[str, Any] | None:
        """Recover one exact terminal lab lifecycle without another wallet effect."""

        asset_id = (
            inventory.get("sbx", {}).get("asset_id")
            if type(inventory) is dict
            and type(inventory.get("sbx")) is dict
            else None
        )
        if type(asset_id) is not str or re.fullmatch(r"[0-9a-f]{64}", asset_id) is None:
            raise LabRefusal("SBX_WALLET_AMBIGUOUS")
        rows = self.database.get_offer_intents_for_registry()
        if type(rows) is not list or not all(type(row) is dict for row in rows):
            raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
        candidates = [
            row
            for row in rows
            if row.get("asset_id") == asset_id
            and row.get("side") == "buy"
            and row.get("purpose") == "normal_lifecycle"
            and row.get("lifecycle_state") == "terminal"
        ]
        if not candidates:
            return None
        if len(candidates) != 1:
            raise LabRefusal("LIFECYCLE_RECOVERY_AMBIGUOUS")
        intent = candidates[0]
        intent_id = intent.get("intent_id")
        trade_id = intent.get("sage_trade_id")
        if (
            type(intent_id) is not str
            or not intent_id
            or type(trade_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", trade_id) is None
        ):
            raise LabRefusal("LIFECYCLE_RECOVERY_AMBIGUOUS")
        cancel_events = self.database.get_offer_operation_events(f"cancel:{trade_id}")
        reconcile_events = self.database.get_offer_operation_events(
            f"reconcile:{intent_id}"
        )
        if (
            type(cancel_events) is not list
            or not cancel_events
            or type(reconcile_events) is not list
            or not reconcile_events
            or type(cancel_events[-1]) is not dict
            or type(reconcile_events[-1]) is not dict
        ):
            raise LabRefusal("LIFECYCLE_RECOVERY_AMBIGUOUS")
        cancel = cancel_events[-1]
        reconciled = reconcile_events[-1]
        cancel_identity = (cancel.get("transaction_id"), cancel.get("spend_identity"))
        reconcile_identity = (
            reconciled.get("transaction_id"),
            reconciled.get("spend_identity"),
        )
        if (
            cancel.get("phase") != "RECONCILED"
            or cancel.get("outcome") != "CANCEL_CONFIRMED"
            or cancel.get("blocks_mutation") != 0
            or reconciled.get("phase") != "FINALIZED"
            or reconciled.get("outcome") != "CANCELLED_PROVEN"
            or reconciled.get("blocks_mutation") != 0
            or cancel_identity != reconcile_identity
            or not any(
                type(value) is str and bool(value)
                for value in cancel_identity
            )
        ):
            raise LabRefusal("LIFECYCLE_RECOVERY_AMBIGUOUS")
        self._require_zero_blockers()
        return {
            "success": True,
            "stage": "lifecycle",
            "count": 1,
            "trade_id": trade_id,
            "intent_id": intent_id,
            "classification": "CANCELLED_PROVEN",
            "recovered": True,
        }

    def lifecycle(
        self,
        mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
        *,
        inventory: Any,
        mid_price: Decimal,
        trade_size_xch: Decimal,
        spread_fraction: Decimal,
        terminal_attempts: int = 1,
        terminal_poll_seconds: float = 0,
        sleeper: Callable[[float], Any] = time.sleep,
    ) -> dict[str, Any]:
        """Create, publish, cancel, and prove one tiny wide-spread SBX bid."""

        if not callable(mutate) or not callable(sleeper):
            raise LabRefusal("OPERATION_INVALID")
        if (
            type(mid_price) is not Decimal
            or not mid_price.is_finite()
            or mid_price <= 0
            or type(trade_size_xch) is not Decimal
            or not trade_size_xch.is_finite()
            or not Decimal("0.0001") <= trade_size_xch <= Decimal("0.01")
            or type(spread_fraction) is not Decimal
            or not spread_fraction.is_finite()
            or not Decimal("0.25") <= spread_fraction <= Decimal("0.90")
            or type(terminal_attempts) is not int
            or terminal_attempts < 1
            or terminal_attempts > 120
            or type(terminal_poll_seconds) not in {int, float}
            or not 0 <= terminal_poll_seconds <= 30
        ):
            raise LabRefusal("LIFECYCLE_PARAMETERS_INVALID")
        completed = self._completed_lifecycle(inventory)
        if completed is not None:
            return completed
        cfg = self._configure_sbx(inventory)
        # OfferManager may add up to 0.001 XCH of deterministic uniqueness
        # variation.  Prove that the designated coin can cover that ceiling.
        required_xch_mojos = int(
            (trade_size_xch + Decimal("0.001")) * Decimal("1000000000000")
        )
        self._sync_coin_registry(required_xch_mojos=required_xch_mojos)
        manager_type = getattr(self.offer_manager_module, "OfferManager", None)
        if not callable(manager_type):
            raise LabRefusal("OFFER_MANAGER_UNAVAILABLE")
        manager = manager_type()
        publisher = self._durable_publisher()
        trade_id = None
        intent_id = None
        cancel_result = None
        primary_error: BaseException | None = None
        try:
            guarded_create = mutate(
                "create_offer",
                lambda: manager.create_ladder(
                    mid_price=mid_price,
                    side="buy",
                    num_offers=1,
                    trade_size_xch=trade_size_xch,
                    spread_fraction=spread_fraction,
                    cat_asset_id=cfg.CAT_ASSET_ID,
                    cat_decimals=cfg.CAT_DECIMALS,
                    cat_wallet_id=cfg.CAT_WALLET_ID,
                    total_slots=1,
                    coin_ids_enabled=True,
                ),
            )
            created = (
                guarded_create.get("result")
                if type(guarded_create) is dict
                else None
            )
            if type(created) is not list or len(created) != 1 or type(created[0]) is not dict:
                raise LabRefusal("OFFER_CREATE_FAILED")
            offer = created[0]
            trade_id = offer.get("trade_id")
            intent_id = offer.get("intent_id")
            bech32 = offer.get("offer_bech32")
            if type(trade_id) is not str or re.fullmatch(r"[0-9a-f]{64}", trade_id) is None:
                raise LabRefusal("OFFER_CREATE_FAILED")
            if type(intent_id) is not str or not intent_id:
                lookup = getattr(self.database, "get_offer_intent_by_trade_id", None)
                durable_intent = lookup(trade_id) if callable(lookup) else None
                intent_id = (
                    durable_intent.get("intent_id")
                    if type(durable_intent) is dict
                    else None
                )
            if type(intent_id) is not str or not intent_id:
                raise LabRefusal("OFFER_CREATE_FAILED")
            if type(bech32) is not str or not bech32.startswith("offer1"):
                raise LabRefusal("OFFER_CREATE_FAILED")

            def publish() -> Any:
                publisher.queue_post(bech32, trade_id, force=True)
                return publisher.flush_queue(flush_all=True)

            publication = mutate("publish_offer", publish)
            published = publication.get("result") if type(publication) is dict else None
            if (
                type(published) is not dict
                or published.get("posted") != 1
                or published.get("failed") != 0
                or published.get("requeued") != 0
            ):
                raise LabRefusal("PUBLICATION_FAILED")
        except BaseException as exc:
            primary_error = exc
        finally:
            if trade_id is not None:
                try:
                    guarded_cancel = mutate(
                        "cancel_offer",
                        lambda: manager.cancel_offers(
                            [trade_id],
                            reason="test7_lifecycle",
                            force_storm=True,
                        ),
                    )
                    cancel_result = (
                        guarded_cancel.get("result")
                        if type(guarded_cancel) is dict
                        else None
                    )
                except BaseException as cancel_exc:
                    if primary_error is None:
                        primary_error = cancel_exc
        if primary_error is not None:
            raise primary_error
        if type(cancel_result) is not dict or type(cancel_result.get(trade_id)) is not dict:
            raise LabRefusal("CANCEL_FAILED")

        classification = None
        for attempt in range(terminal_attempts):
            reconciled = self.reconciliation.reconcile_offer(
                intent_id,
                wallet_facade=self.wallet,
            )
            classification = (
                reconciled.get("classification")
                if type(reconciled) is dict
                else None
            )
            if classification == "CANCELLED_PROVEN":
                break
            if attempt + 1 < terminal_attempts and terminal_poll_seconds:
                sleeper(terminal_poll_seconds)
        if classification != "CANCELLED_PROVEN":
            raise LabRefusal("CANCELLATION_NOT_PROVEN")
        self._require_zero_blockers()
        return {
            "success": True,
            "stage": "lifecycle",
            "count": 1,
            "trade_id": trade_id,
            "intent_id": intent_id,
            "classification": classification,
        }

    @staticmethod
    def _normalized_coin_id(value: Any) -> str | None:
        if type(value) is not str:
            return None
        normalized = value.strip().lower()
        if normalized.startswith("0x"):
            normalized = normalized[2:]
        if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
            return None
        return normalized

    def _allocate_lab_offer_coins(
        self, *, required_xch_mojos: int, purposes: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        """Allocate exact, distinct free XCH coins to ordered lab purposes."""

        if (
            type(required_xch_mojos) is not int
            or required_xch_mojos < 1
            or type(purposes) is not tuple
            or not purposes
            or any(
                type(purpose) is not str
                or purpose not in {"lifecycle", "replacement", "fill_response"}
                for purpose in purposes
            )
        ):
            raise LabRefusal("COIN_PURPOSE_UNAVAILABLE")
        manager_type = getattr(self.coin_manager_module, "CoinManager", None)
        tier_reader = getattr(
            self.coin_manager_module, "coin_size_tier_for_slot_position", None
        )
        designation_writer = getattr(self.database, "set_coin_designation", None)
        if not callable(manager_type) or not callable(tier_reader) or not callable(
            designation_writer
        ):
            raise LabRefusal("COIN_PURPOSE_UNAVAILABLE")
        manager_type().reconcile_with_wallet()
        rows = self.database.get_free_coins("xch")
        if type(rows) is not list or not all(type(row) is dict for row in rows):
            raise LabRefusal("COIN_REGISTRY_UNAVAILABLE")
        assigned_tier = tier_reader("mid", side="buy")
        if assigned_tier not in {"inner", "mid", "outer", "extreme"}:
            raise LabRefusal("COIN_PURPOSE_UNAVAILABLE")
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        for row in rows:
            coin_id = self._normalized_coin_id(row.get("coin_id"))
            amount = row.get("amount_mojos")
            if (
                coin_id is None
                or type(amount) is not int
                or type(amount) is bool
                or amount < required_xch_mojos
                or row.get("status") != "free"
                or row.get("trade_id") is not None
                or row.get("designation") == "reserve"
                or row.get("purpose") == "fee_reserve"
            ):
                continue
            candidates.append((amount, coin_id, row))
        candidates.sort(key=lambda item: (item[0], item[1]))
        if len(candidates) < len(purposes):
            raise LabRefusal("LAB_COIN_CAPACITY_UNAVAILABLE")
        selected = candidates[: len(purposes)]
        for (_amount, coin_id, _row), purpose in zip(selected, purposes):
            if (
                designation_writer(
                    coin_id,
                    "tier_spare",
                    assigned_tier,
                    purpose=purpose,
                )
                is not True
            ):
                raise LabRefusal("COIN_PURPOSE_ASSIGNMENT_FAILED")
        verified = self.database.get_free_coins("xch")
        if type(verified) is not list:
            raise LabRefusal("COIN_PURPOSE_ASSIGNMENT_FAILED")
        by_id = {
            self._normalized_coin_id(row.get("coin_id")): row
            for row in verified
            if type(row) is dict
        }
        result = []
        for (_amount, coin_id, _row), purpose in zip(selected, purposes):
            row = by_id.get(coin_id)
            if (
                type(row) is not dict
                or row.get("status") != "free"
                or row.get("trade_id") is not None
                or row.get("designation") != "tier_spare"
                or row.get("assigned_tier") != assigned_tier
                or row.get("purpose") != purpose
            ):
                raise LabRefusal("COIN_PURPOSE_ASSIGNMENT_FAILED")
            result.append(
                {
                    "coin_id": coin_id,
                    "amount_mojos": int(row["amount_mojos"]),
                    "assigned_tier": assigned_tier,
                    "purpose": purpose,
                }
            )
        return result

    @staticmethod
    def _offer_terms(
        *, mid_price: Decimal, trade_size_xch: Decimal, spread_fraction: Decimal
    ) -> dict[str, Any]:
        if (
            type(mid_price) is not Decimal
            or not mid_price.is_finite()
            or mid_price <= 0
            or type(trade_size_xch) is not Decimal
            or not trade_size_xch.is_finite()
            or not Decimal("0.0001") <= trade_size_xch <= Decimal("0.01")
            or type(spread_fraction) is not Decimal
            or not spread_fraction.is_finite()
            or not Decimal("0.25") <= spread_fraction <= Decimal("0.90")
        ):
            raise LabRefusal("LIFECYCLE_PARAMETERS_INVALID")
        price = mid_price * (Decimal("1") - spread_fraction)
        spend_mojos = int(trade_size_xch * Decimal("1000000000000"))
        requested_atomic = int((trade_size_xch / price) * Decimal("1000"))
        if spend_mojos < 1 or requested_atomic < 1:
            raise LabRefusal("LIFECYCLE_PARAMETERS_INVALID")
        size_cat = Decimal(requested_atomic) / Decimal("1000")
        return {
            "spend_mojos": spend_mojos,
            "requested_atomic": requested_atomic,
            "size_cat": size_cat,
            "price": trade_size_xch / size_cat,
        }

    def _create_registered_lab_offer(
        self,
        manager: Any,
        *,
        cfg: Any,
        asset_id: str,
        slot_key: str,
        coin: Mapping[str, Any],
        purpose: str,
        parent_intent_id: str | None,
        terms: Mapping[str, Any],
        uniqueness_offset: int,
    ) -> dict[str, Any]:
        requested_atomic = int(terms["requested_atomic"]) + uniqueness_offset
        spend_mojos = int(terms["spend_mojos"])
        result = manager.create_offer_with_retry(
            {
                str(getattr(cfg, "WALLET_ID_XCH", 1)): -spend_mojos,
                str(cfg.CAT_WALLET_ID): requested_atomic,
            },
            max_retries=0,
            expiry_secs=3600,
            coin_ids_enabled=True,
            selected_coin_id=coin["coin_id"],
            preferred_tier=coin["assigned_tier"],
            strict_preferred_tier=True,
            creation_context={
                "slot_key": slot_key,
                "select_next_generation": True,
                "asset_id": asset_id,
                "side": "buy",
                "tier": coin["assigned_tier"],
                "purpose": purpose,
                "parent_intent_id": parent_intent_id,
                "offer_size_uniqueness": {
                    "lab": LAB_PURPOSE,
                    "requested_amount_atomic": str(requested_atomic),
                },
            },
        )
        if type(result) is not dict or result.get("success") is not True:
            raise LabRefusal("OFFER_CREATE_FAILED")
        trade_id = result.get("trade_id")
        intent_id = result.get("_catalyst_intent_id")
        offer_text = result.get("offer")
        locked_coin_id = self._normalized_coin_id(result.get("locked_coin_id"))
        if (
            type(trade_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", trade_id) is None
            or type(intent_id) is not str
            or not intent_id
            or type(offer_text) is not str
            or not offer_text.startswith("offer1")
            or locked_coin_id != coin["coin_id"]
        ):
            raise LabRefusal("OFFER_CREATE_FAILED")
        size_cat = Decimal(requested_atomic) / Decimal("1000")
        price = (Decimal(spend_mojos) / Decimal("1000000000000")) / size_cat
        if (
            self.database.add_offer(
                trade_id=trade_id,
                side="buy",
                price_xch=price,
                size_xch=Decimal(spend_mojos) / Decimal("1000000000000"),
                size_cat=size_cat,
                cat_asset_id=asset_id,
                tier=coin["assigned_tier"],
                coin_id=coin["coin_id"],
            )
            is not True
            or self.database.update_offer_bech32(trade_id, offer_text) is not True
        ):
            raise LabRefusal("OFFER_REGISTRY_WRITE_FAILED")
        return {
            "trade_id": trade_id,
            "intent_id": intent_id,
            "offer": offer_text,
            "coin_id": coin["coin_id"],
        }

    def _publish_lab_offer(
        self, publisher: Any, *, trade_id: str, intent_id: str, offer_text: str
    ) -> None:
        publisher.queue_post(offer_text, trade_id, force=True)
        published = publisher.flush_queue(flush_all=True)
        if (
            type(published) is not dict
            or published.get("posted") != 1
            or published.get("failed") != 0
            or published.get("requeued") != 0
        ):
            raise LabRefusal("PUBLICATION_FAILED")
        visibility = self.database.record_offer_intent_visibility(
            intent_id,
            publication_identity=f"dexie:{trade_id}",
        )
        if type(visibility) is not dict or type(visibility.get("intent")) is not dict:
            raise LabRefusal("PUBLICATION_FAILED")

    def _cancel_and_prove_lab_offer(
        self,
        manager: Any,
        mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
        *,
        offer: Mapping[str, Any],
        operation: str,
        reason: str,
        terminal_attempts: int,
        terminal_poll_seconds: float,
        sleeper: Callable[[float], Any],
    ) -> str:
        trade_id = offer["trade_id"]
        intent_id = offer["intent_id"]
        guarded = mutate(
            operation,
            lambda: manager.cancel_offers(
                [trade_id],
                reason=reason,
                force_storm=True,
            ),
        )
        cancelled = guarded.get("result") if type(guarded) is dict else None
        if type(cancelled) is not dict or type(cancelled.get(trade_id)) is not dict:
            raise LabRefusal("CANCEL_FAILED")
        classification = None
        for attempt in range(terminal_attempts):
            result = self.reconciliation.reconcile_offer(
                intent_id,
                wallet_facade=self.wallet,
            )
            classification = (
                result.get("classification") if type(result) is dict else None
            )
            if classification == "CANCELLED_PROVEN":
                return classification
            if attempt + 1 < terminal_attempts and terminal_poll_seconds:
                sleeper(terminal_poll_seconds)
        raise LabRefusal("CANCELLATION_NOT_PROVEN")

    def _completed_replacement(self, inventory: Any) -> dict[str, Any] | None:
        asset_id = inventory.get("sbx", {}).get("asset_id")
        slot_prefix = f"test7-replacement:{asset_id}"
        rows = self.database.get_offer_intents_for_registry()
        if type(rows) is not list or not all(type(row) is dict for row in rows):
            raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
        candidates = [
            row
            for row in rows
            if row.get("slot_key") == slot_prefix
            or (
                type(row.get("slot_key")) is str
                and row["slot_key"].startswith(f"{slot_prefix}:trial:")
            )
        ]
        if not candidates:
            return None
        trials: dict[str, list[dict[str, Any]]] = {}
        for row in candidates:
            trials.setdefault(row["slot_key"], []).append(row)
        for trial in trials.values():
            successful = [
                row
                for row in trial
                if row.get("lifecycle_state") != "creation_failed"
            ]
            if len(successful) != 3 or any(
                row.get("lifecycle_state") != "terminal" for row in successful
            ):
                continue
            successful.sort(key=lambda row: row.get("generation", -1))
            if [row.get("purpose") for row in successful] != [
                "normal_lifecycle",
                "replacement",
                "replacement",
            ]:
                raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS")
            commit_reader = getattr(
                self.database, "get_refresh_lineage_commit_for_child", None
            )
            if not callable(commit_reader) or any(
                type(commit_reader(successful[index + 1].get("intent_id")))
                is not dict
                for index in range(2)
            ):
                raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS")
            self._require_zero_blockers()
            return {
                "success": True,
                "stage": "replacement",
                "count": 3,
                "wave_count": 2,
                "classification": "REPLACEMENT_LINEAGE_PROVEN",
                "recovered": True,
            }
        return None

    def _replacement_slot_key(self, inventory: Any) -> str:
        asset_id = inventory.get("sbx", {}).get("asset_id")
        base = f"test7-replacement:{asset_id}"
        rows = self.database.get_offer_intents_for_registry()
        if type(rows) is not list or not all(type(row) is dict for row in rows):
            raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
        trial_numbers = []
        active_slots = set()
        for row in rows:
            slot_key = row.get("slot_key")
            if slot_key == base:
                trial_numbers.append(0)
            elif type(slot_key) is not str or not slot_key.startswith(
                f"{base}:trial:"
            ):
                continue
            else:
                suffix = slot_key[len(f"{base}:trial:") :]
                if not suffix.isascii() or not suffix.isdigit() or int(suffix) < 1:
                    raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS")
                trial_numbers.append(int(suffix))
            if row.get("lifecycle_state") not in {"terminal", "creation_failed"}:
                active_slots.add(slot_key)
        if len(active_slots) > 1:
            raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS")
        if active_slots:
            return next(iter(active_slots))
        if not trial_numbers:
            return base
        return f"{base}:trial:{max(trial_numbers) + 1}"

    def _replacement_progress(
        self, inventory: Any, slot_key: str
    ) -> list[dict[str, Any]]:
        rows = self.database.get_offer_intents_for_registry()
        if type(rows) is not list or not all(type(row) is dict for row in rows):
            raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
        successful = [
            row
            for row in rows
            if row.get("slot_key") == slot_key
            and row.get("lifecycle_state") != "creation_failed"
        ]
        successful.sort(key=lambda row: row.get("generation", -1))
        if not successful:
            return []
        if (
            len(successful) > 3
            or [row.get("generation") for row in successful]
            != list(range(len(successful)))
            or [row.get("purpose") for row in successful]
            != ["normal_lifecycle"] + ["replacement"] * (len(successful) - 1)
            or any(
                row.get("lifecycle_state") not in {"created", "visible", "terminal"}
                for row in successful
            )
        ):
            raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS")
        recovered = []
        for index, row in enumerate(successful):
            expected_parent = successful[index - 1]["intent_id"] if index else None
            trade_id = row.get("sage_trade_id")
            selected = row.get("selected_coin_ids_json")
            try:
                selected_coin_ids = (
                    json.loads(selected) if type(selected) is str else selected
                )
            except json.JSONDecodeError as exc:
                raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS") from exc
            legacy = (
                self.database.get_offer(trade_id)
                if type(trade_id) is str
                else None
            )
            if (
                row.get("parent_intent_id") != expected_parent
                or type(trade_id) is not str
                or re.fullmatch(r"[0-9a-f]{64}", trade_id) is None
                or type(selected_coin_ids) is not list
                or len(selected_coin_ids) != 1
                or self._normalized_coin_id(selected_coin_ids[0]) is None
                or type(legacy) is not dict
                or type(legacy.get("offer_bech32")) is not str
                or not legacy["offer_bech32"].startswith("offer1")
            ):
                raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS")
            recovered.append(
                {
                    "trade_id": trade_id,
                    "intent_id": row["intent_id"],
                    "offer": legacy["offer_bech32"],
                    "coin_id": self._normalized_coin_id(selected_coin_ids[0]),
                    "lifecycle_state": row["lifecycle_state"],
                }
            )
        return recovered

    def replacement(
        self,
        mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
        *,
        inventory: Any,
        mid_price: Decimal,
        trade_size_xch: Decimal,
        spread_fraction: Decimal,
        terminal_attempts: int = 1,
        terminal_poll_seconds: float = 0,
        sleeper: Callable[[float], Any] = time.sleep,
    ) -> dict[str, Any]:
        """Run two child-visible-before-parent-cancel replacement waves."""

        if (
            not callable(mutate)
            or not callable(sleeper)
            or type(terminal_attempts) is not int
            or not 1 <= terminal_attempts <= 120
            or type(terminal_poll_seconds) not in {int, float}
            or not 0 <= terminal_poll_seconds <= 30
        ):
            raise LabRefusal("OPERATION_INVALID")
        completed = self._completed_replacement(inventory)
        if completed is not None:
            return completed
        cfg = self._configure_sbx(inventory)
        terms = self._offer_terms(
            mid_price=mid_price,
            trade_size_xch=trade_size_xch,
            spread_fraction=spread_fraction,
        )
        manager_type = getattr(self.offer_manager_module, "OfferManager", None)
        if not callable(manager_type):
            raise LabRefusal("OFFER_MANAGER_UNAVAILABLE")
        manager = manager_type()
        publisher = self._durable_publisher()
        asset_id = inventory["sbx"]["asset_id"]
        slot_key = self._replacement_slot_key(inventory)
        created = self._replacement_progress(inventory, slot_key)
        cancelled = {
            offer["trade_id"]
            for offer in created
            if offer["lifecycle_state"] == "terminal"
        }
        remaining = 3 - len(created)
        if remaining < 0:
            raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS")
        purposes = (
            tuple(["lifecycle"] + ["replacement"] * (remaining - 1))
            if not created and remaining
            else tuple(["replacement"] * remaining)
        )
        coins = self._allocate_lab_offer_coins(
            required_xch_mojos=int(terms["spend_mojos"]),
            purposes=purposes,
        )
        try:
            for index, offer in enumerate(created):
                if index:
                    parent = created[index - 1]
                    current_parent = self.database.get_offer_intent(
                        parent["intent_id"]
                    )
                    if (
                        type(current_parent) is not dict
                        or current_parent.get("child_intent_id")
                        not in {None, offer["intent_id"]}
                    ):
                        raise LabRefusal("REPLACEMENT_RECOVERY_AMBIGUOUS")
                    if current_parent.get("child_intent_id") is None:
                        self.database.bind_refresh_lineage(
                            parent["intent_id"], offer["intent_id"]
                        )
                if offer["lifecycle_state"] == "created":
                    mutate(
                        f"replacement_publish_{index}",
                        lambda offer=offer: self._publish_lab_offer(
                            publisher,
                            trade_id=offer["trade_id"],
                            intent_id=offer["intent_id"],
                            offer_text=offer["offer"],
                        ),
                    )
                    offer["lifecycle_state"] = "visible"
                if index:
                    parent = created[index - 1]
                    if parent["trade_id"] not in cancelled:
                        self._cancel_and_prove_lab_offer(
                            manager,
                            mutate,
                            offer=parent,
                            operation=f"replacement_cancel_{index - 1}",
                            reason="test7_replacement_resume",
                            terminal_attempts=terminal_attempts,
                            terminal_poll_seconds=terminal_poll_seconds,
                            sleeper=sleeper,
                        )
                        cancelled.add(parent["trade_id"])
                    committed = self.database.commit_refresh_lineage_completion(
                        parent["intent_id"]
                    )
                    if (
                        type(committed) is not dict
                        or committed.get("committed") is not True
                    ):
                        raise LabRefusal("REFRESH_LINEAGE_COMMIT_FAILED")

            start_index = len(created)
            for offset, coin in enumerate(coins):
                index = start_index + offset
                parent = created[-1] if created else None
                purpose = "normal_lifecycle" if parent is None else "replacement"
                guarded = mutate(
                    f"replacement_create_{index}",
                    lambda coin=coin, parent=parent, index=index, purpose=purpose: self._create_registered_lab_offer(
                        manager,
                        cfg=cfg,
                        asset_id=asset_id,
                        slot_key=slot_key,
                        coin=coin,
                        purpose=purpose,
                        parent_intent_id=(parent["intent_id"] if parent else None),
                        terms=terms,
                        uniqueness_offset=index,
                    ),
                )
                offer = guarded.get("result") if type(guarded) is dict else None
                if type(offer) is not dict:
                    raise LabRefusal("OFFER_CREATE_FAILED")
                created.append(offer)
                if parent is not None:
                    bound = self.database.bind_refresh_lineage(
                        parent["intent_id"], offer["intent_id"]
                    )
                    if type(bound) is not dict:
                        raise LabRefusal("REFRESH_LINEAGE_BIND_FAILED")
                mutate(
                    f"replacement_publish_{index}",
                    lambda offer=offer: self._publish_lab_offer(
                        publisher,
                        trade_id=offer["trade_id"],
                        intent_id=offer["intent_id"],
                        offer_text=offer["offer"],
                    ),
                )
                if parent is not None:
                    self._cancel_and_prove_lab_offer(
                        manager,
                        mutate,
                        offer=parent,
                        operation=f"replacement_cancel_{index - 1}",
                        reason="test7_replacement",
                        terminal_attempts=terminal_attempts,
                        terminal_poll_seconds=terminal_poll_seconds,
                        sleeper=sleeper,
                    )
                    cancelled.add(parent["trade_id"])
                    committed = self.database.commit_refresh_lineage_completion(
                        parent["intent_id"]
                    )
                    if type(committed) is not dict or committed.get("committed") is not True:
                        raise LabRefusal("REFRESH_LINEAGE_COMMIT_FAILED")
            final_offer = created[-1]
            self._cancel_and_prove_lab_offer(
                manager,
                mutate,
                offer=final_offer,
                operation="replacement_cancel_2",
                reason="test7_replacement_cleanup",
                terminal_attempts=terminal_attempts,
                terminal_poll_seconds=terminal_poll_seconds,
                sleeper=sleeper,
            )
            cancelled.add(final_offer["trade_id"])
        except BaseException:
            for index, offer in reversed(list(enumerate(created))):
                if offer["trade_id"] in cancelled:
                    continue
                try:
                    self._cancel_and_prove_lab_offer(
                        manager,
                        mutate,
                        offer=offer,
                        operation=f"replacement_cleanup_{index}",
                        reason="test7_replacement_failure_cleanup",
                        terminal_attempts=terminal_attempts,
                        terminal_poll_seconds=terminal_poll_seconds,
                        sleeper=sleeper,
                    )
                except BaseException:
                    pass
            raise
        self._require_zero_blockers()
        return {
            "success": True,
            "stage": "replacement",
            "count": 3,
            "wave_count": 2,
            "classification": "REPLACEMENT_LINEAGE_PROVEN",
        }

    def _completed_fill(self, inventory: Any) -> dict[str, Any] | None:
        asset_id = inventory.get("sbx", {}).get("asset_id")
        slot_key = f"test7-fill:{asset_id}"
        rows = self.database.get_offer_intents_for_registry()
        if type(rows) is not list or not all(type(row) is dict for row in rows):
            raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
        candidates = [row for row in rows if row.get("slot_key") == slot_key]
        if not candidates:
            return None
        if any(
            row.get("lifecycle_state") not in {"terminal", "creation_failed"}
            for row in candidates
        ):
            return None
        for intent in sorted(candidates, key=lambda row: row.get("generation", -1), reverse=True):
            if intent.get("lifecycle_state") != "terminal":
                continue
            events = self.database.get_offer_operation_events(
                f"reconcile:{intent.get('intent_id')}"
            )
            if type(events) is list and events and events[-1].get("outcome") == "FILLED_PROVEN":
                self._require_zero_blockers()
                return {
                    "success": True,
                    "stage": "fill",
                    "count": 1,
                    "trade_id": intent.get("sage_trade_id"),
                    "intent_id": intent.get("intent_id"),
                    "classification": "FILLED_PROVEN",
                    "recovered": True,
                }
        return None

    def _incomplete_fill_intent(self, inventory: Any) -> dict[str, Any] | None:
        asset_id = inventory.get("sbx", {}).get("asset_id")
        slot_key = f"test7-fill:{asset_id}"
        rows = self.database.get_offer_intents_for_registry()
        if type(rows) is not list or not all(type(row) is dict for row in rows):
            raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
        incomplete = [
            row
            for row in rows
            if row.get("slot_key") == slot_key
            and row.get("lifecycle_state") not in {"terminal", "creation_failed"}
        ]
        if len(incomplete) > 1:
            raise LabRefusal("FILL_RECOVERY_REQUIRED")
        return incomplete[0] if incomplete else None

    def fill(
        self,
        mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
        *,
        inventory: Any,
        mid_price: Decimal,
        trade_size_xch: Decimal,
        terminal_attempts: int = 1,
        terminal_poll_seconds: float = 0,
        sleeper: Callable[[float], Any] = time.sleep,
    ) -> dict[str, Any]:
        """Create and self-take one tiny offer, then prove the exact fill."""

        if (
            not callable(mutate)
            or not callable(sleeper)
            or type(terminal_attempts) is not int
            or not 1 <= terminal_attempts <= 120
            or type(terminal_poll_seconds) not in {int, float}
            or not 0 <= terminal_poll_seconds <= 30
        ):
            raise LabRefusal("OPERATION_INVALID")
        completed = self._completed_fill(inventory)
        if completed is not None:
            return completed
        cfg = self._configure_sbx(inventory)
        terms = self._offer_terms(
            mid_price=mid_price,
            trade_size_xch=trade_size_xch,
            spread_fraction=Decimal("0.5"),
        )
        manager_type = getattr(self.offer_manager_module, "OfferManager", None)
        if not callable(manager_type):
            raise LabRefusal("OFFER_MANAGER_UNAVAILABLE")
        manager = manager_type()
        asset_id = inventory["sbx"]["asset_id"]
        offer: dict[str, Any] | None = None
        created_for_attempt = False
        incomplete = self._incomplete_fill_intent(inventory)
        if incomplete is not None:
            intent_id = incomplete.get("intent_id")
            trade_id = self._normalized_coin_id(incomplete.get("sage_trade_id"))
            if type(intent_id) is not str or not intent_id or trade_id is None:
                raise LabRefusal("FILL_RECOVERY_REQUIRED")
            recovered = self.reconciliation.reconcile_offer(
                intent_id,
                wallet_facade=self.wallet,
            )
            classification = (
                recovered.get("classification") if type(recovered) is dict else None
            )
            if classification == "FILLED_PROVEN":
                self._require_zero_blockers()
                return {
                    "success": True,
                    "stage": "fill",
                    "count": 1,
                    "trade_id": trade_id,
                    "intent_id": intent_id,
                    "classification": "FILLED_PROVEN",
                    "recovered": True,
                }
            if classification == "ACTIVE_PROVEN":
                pending_reader = getattr(
                    self.wallet, "get_pending_transactions", None
                )
                pending = pending_reader() if callable(pending_reader) else None
                if type(pending) is not list or pending:
                    raise LabRefusal("FILL_RECOVERY_REQUIRED")
                selected = incomplete.get("selected_coin_ids_json")
                try:
                    selected_coin_ids = (
                        json.loads(selected) if type(selected) is str else selected
                    )
                except json.JSONDecodeError as exc:
                    raise LabRefusal("FILL_RECOVERY_REQUIRED") from exc
                legacy = self.database.get_offer(trade_id)
                selected_coin_id = (
                    self._normalized_coin_id(selected_coin_ids[0])
                    if type(selected_coin_ids) is list
                    and len(selected_coin_ids) == 1
                    else None
                )
                if (
                    selected_coin_id is None
                    or type(legacy) is not dict
                    or self._normalized_coin_id(legacy.get("coin_id"))
                    != selected_coin_id
                    or type(legacy.get("offer_bech32")) is not str
                    or not legacy["offer_bech32"].startswith("offer1")
                ):
                    raise LabRefusal("FILL_RECOVERY_REQUIRED")
                offer = {
                    "trade_id": trade_id,
                    "intent_id": intent_id,
                    "offer": legacy["offer_bech32"],
                    "coin_id": selected_coin_id,
                }
            elif classification not in {"CANCELLED_PROVEN", "EXPIRED_PROVEN"}:
                raise LabRefusal("FILL_RECOVERY_REQUIRED")
        if offer is None:
            coin = self._allocate_lab_offer_coins(
                required_xch_mojos=int(terms["spend_mojos"]),
                purposes=("fill_response",),
            )[0]
            guarded_create = mutate(
                "fill_create_offer",
                lambda: self._create_registered_lab_offer(
                    manager,
                    cfg=cfg,
                    asset_id=asset_id,
                    slot_key=f"test7-fill:{asset_id}",
                    coin=coin,
                    purpose="fill_response",
                    parent_intent_id=None,
                    terms=terms,
                    uniqueness_offset=0,
                ),
            )
            offer = (
                guarded_create.get("result")
                if type(guarded_create) is dict
                else None
            )
            if type(offer) is not dict:
                raise LabRefusal("OFFER_CREATE_FAILED")
            created_for_attempt = True
        transaction_id = None
        submission_attempted = False
        try:
            unsigned_offer = _unsigned_self_take_offer_text(offer["offer"])
            if unsigned_offer is None:
                raise LabRefusal("FILL_SELF_TAKE_UNAVAILABLE")
            guarded_take = mutate(
                "fill_take_offer",
                lambda: self.wallet.rpc(
                    "take_offer",
                    {"offer": unsigned_offer, "fee": "0", "auto_submit": False},
                    60,
                ),
            )
            taken = guarded_take.get("result") if type(guarded_take) is dict else None
            transaction_id = taken.get("transaction_id") if type(taken) is dict else None
            summary = taken.get("summary") if type(taken) is dict else None
            inputs = summary.get("inputs") if type(summary) is dict else None
            spend_bundle = (
                taken.get("spend_bundle") if type(taken) is dict else None
            )
            coin_spends = (
                spend_bundle.get("coin_spends")
                if type(spend_bundle) is dict
                else None
            )
            signature = (
                spend_bundle.get("aggregated_signature")
                if type(spend_bundle) is dict
                else None
            )
            if (
                type(transaction_id) is not str
                or re.fullmatch(r"[0-9a-f]{64}", transaction_id) is None
                or type(inputs) is not list
                or not all(type(row) is dict for row in inputs)
                or type(coin_spends) is not list
                or not coin_spends
                or not all(type(row) is dict for row in coin_spends)
                or type(signature) is not str
                or not signature
                or len(signature) > 4096
            ):
                raise LabRefusal("FILL_SUBMISSION_FAILED")
            maker_inputs = [
                row
                for row in inputs
                if self._normalized_coin_id(row.get("coin_id")) == offer["coin_id"]
                and "asset" in row
                and (
                    row["asset"] is None
                    or (
                        type(row["asset"]) is dict
                        and "asset_id" in row["asset"]
                        and row["asset"]["asset_id"] is None
                    )
                )
            ]
            cat_inputs = [
                row
                for row in inputs
                if type(row.get("asset")) is dict
                and self._normalized_coin_id(row["asset"].get("asset_id")) == asset_id
            ]
            cat_coin_ids = {
                self._normalized_coin_id(row.get("coin_id")) for row in cat_inputs
            }
            if (
                len(maker_inputs) != 1
                or not cat_inputs
                or None in cat_coin_ids
                or offer["coin_id"] in cat_coin_ids
            ):
                raise LabRefusal("FILL_INPUT_AUTHORITY_INVALID")
            submission_attempted = True
            guarded_submit = mutate(
                "fill_submit_transaction",
                lambda: self.wallet.rpc(
                    "submit_transaction",
                    {"spend_bundle": spend_bundle},
                    60,
                ),
            )
            submitted = (
                guarded_submit.get("result")
                if type(guarded_submit) is dict
                else None
            )
            if (
                type(submitted) is not dict
                or submitted.get("success") is False
                or submitted.get("error") not in {None, ""}
                or submitted.get("error_code") not in {None, ""}
            ):
                raise LabRefusal("FILL_SUBMISSION_FAILED")
            classification = None
            for attempt in range(terminal_attempts):
                reconciled = self.reconciliation.reconcile_offer(
                    offer["intent_id"],
                    wallet_facade=self.wallet,
                )
                classification = (
                    reconciled.get("classification")
                    if type(reconciled) is dict
                    else None
                )
                if classification == "FILLED_PROVEN":
                    break
                if attempt + 1 < terminal_attempts and terminal_poll_seconds:
                    sleeper(terminal_poll_seconds)
            if classification != "FILLED_PROVEN":
                raise LabRefusal("FILL_NOT_PROVEN")
        except BaseException:
            if not submission_attempted and created_for_attempt:
                try:
                    self._cancel_and_prove_lab_offer(
                        manager,
                        mutate,
                        offer=offer,
                        operation="fill_cleanup_cancel",
                        reason="test7_fill_failure_cleanup",
                        terminal_attempts=terminal_attempts,
                        terminal_poll_seconds=terminal_poll_seconds,
                        sleeper=sleeper,
                    )
                except BaseException:
                    pass
            raise
        self._require_zero_blockers()
        return {
            "success": True,
            "stage": "fill",
            "count": 1,
            "trade_id": offer["trade_id"],
            "intent_id": offer["intent_id"],
            "transaction_id": transaction_id,
            "classification": "FILLED_PROVEN",
        }

    def soak(
        self,
        mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
        *,
        samples: int = 3,
        interval_seconds: float = 5,
        sleeper: Callable[[float], Any] = time.sleep,
        now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> dict[str, Any]:
        """Take bounded periodic identity/history/safety snapshots."""

        if (
            not callable(mutate)
            or type(samples) is not int
            or not 2 <= samples <= 12
            or type(interval_seconds) not in {int, float}
            or not 0 <= interval_seconds <= 60
            or not callable(sleeper)
            or not callable(now_provider)
        ):
            raise LabRefusal("SOAK_PARAMETERS_INVALID")
        for index in range(samples):
            guarded = mutate(
                f"soak_snapshot_{index}",
                lambda: {
                    "inventory": self.inventory(now=now_provider),
                    "safety": self._require_zero_blockers(),
                },
            )
            snapshot = guarded.get("result") if type(guarded) is dict else None
            if (
                type(snapshot) is not dict
                or type(snapshot.get("inventory")) is not dict
                or type(snapshot.get("safety")) is not dict
            ):
                raise LabRefusal("SOAK_SNAPSHOT_FAILED")
            if index + 1 < samples and interval_seconds:
                sleeper(interval_seconds)
        return {
            "success": True,
            "stage": "soak",
            "count": samples,
            "classification": "SOAK_STABLE",
        }

    def final_reconcile(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Require exact terminal registry, publication, offer book, and gate state."""

        reconciliation = self.reconcile()
        inventory = self.inventory(now=now)
        asset_id = inventory["sbx"]["asset_id"]
        intents = self.database.get_offer_intents_for_registry()
        if type(intents) is not list or not all(type(row) is dict for row in intents):
            raise LabRefusal("REGISTRY_SNAPSHOT_UNAVAILABLE")
        lab_intents = [
            row
            for row in intents
            if type(row.get("slot_key")) is str
            and row["slot_key"].startswith("test7-")
        ]
        if not lab_intents or any(
            row.get("lifecycle_state") not in {"terminal", "creation_failed"}
            for row in lab_intents
        ):
            raise LabRefusal("FINAL_REGISTRY_NOT_TERMINAL")
        outbox = self.database.list_publication_outbox()
        if type(outbox) is not list or any(
            type(row) is not dict
            or row.get("state") not in {"succeeded", "suppressed"}
            for row in outbox
        ):
            raise LabRefusal("FINAL_PUBLICATION_NOT_TERMINAL")
        open_offers = self.database.get_open_offers(cat_asset_id=asset_id)
        if type(open_offers) is not list or open_offers:
            raise LabRefusal("FINAL_OFFER_BOOK_NOT_TERMINAL")
        if reconciliation.get("success") is not True:
            raise LabRefusal("FINAL_RECONCILIATION_FAILED")
        self._require_zero_blockers()
        return {
            "success": True,
            "stage": "final-reconcile",
            "count": len(lab_intents),
            "classification": "FINAL_RECONCILIATION_CLEAN",
        }

    def restart(
        self,
        mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Release and reacquire the runtime through the ordered startup gates."""

        if not callable(mutate):
            raise LabRefusal("OPERATION_INVALID")
        observed_now = datetime.now(timezone.utc) if now is None else now

        def effect() -> dict[str, Any]:
            released = self.api_server.release_mutation_runtime()
            if type(released) is not dict:
                raise LabRefusal("RUNTIME_RESTART_FAILED")
            started = self.api_server.initialize_mutation_runtime(
                start_heartbeat=True,
                acquire_lease=True,
            )
            if type(started) is not dict or started.get("allowed") is not True:
                raise LabRefusal("RUNTIME_RESTART_FAILED")
            identity = self.wallet.get_wallet_identity()
            validate_test7_identity(
                identity,
                now=(datetime.now(timezone.utc) if now is None else observed_now),
            )
            self._require_zero_blockers()
            return started

        guarded = mutate("restart_runtime", effect)
        if type(guarded) is not dict or type(guarded.get("result")) is not dict:
            raise LabRefusal("RUNTIME_RESTART_FAILED")
        return {
            "success": True,
            "stage": "restart",
            "count": 1,
            "classification": "RESTART_RECOVERED",
        }

    def stale_read(
        self,
        *,
        data_dir: str | os.PathLike[str],
        environment: Mapping[str, str],
        now: datetime | None = None,
        effect: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        """Prove a stale Sage identity freezes mutation before its callback."""

        observed_now = datetime.now(timezone.utc) if now is None else now
        snapshot = self.wallet.get_wallet_identity()
        if type(snapshot) is not dict:
            raise LabRefusal("IDENTITY_UNAVAILABLE")
        stale = dict(snapshot)
        stale["observed_at_utc"] = _canonical_utc(
            observed_now - timedelta(seconds=IDENTITY_MAX_AGE_SECONDS + 1)
        )
        sentinel = effect if callable(effect) else lambda: None
        try:
            run_guarded_mutation(
                operation="stale_read_probe",
                effect=sentinel,
                live=True,
                confirmation=LIVE_CONFIRMATION,
                data_dir=data_dir,
                environment=environment,
                identity_reader=lambda: stale,
                now=observed_now,
            )
        except LabRefusal as exc:
            if exc.reason_code != "IDENTITY_STALE":
                raise
        else:
            raise LabRefusal("STALE_READ_MUTATION_NOT_FROZEN")
        fresh_identity = self.wallet.get_wallet_identity()
        validate_test7_identity(
            fresh_identity,
            now=(datetime.now(timezone.utc) if now is None else observed_now),
        )
        self._require_zero_blockers()
        return {
            "success": True,
            "stage": "stale-read",
            "count": 1,
            "classification": "STALE_READ_FROZEN",
        }

    def long_gap(
        self,
        mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Run a real isolated recovery epoch from an injected monotonic gap."""

        if not callable(mutate):
            raise LabRefusal("OPERATION_INVALID")
        observed_now = datetime.now(timezone.utc) if now is None else now
        sample_type = getattr(self.runtime_recovery_module, "ClockSample", None)
        detector = getattr(self.runtime_recovery_module, "detect_discontinuity", None)
        coordinator = getattr(self.api_server, "run_runtime_recovery", None)
        if not callable(sample_type) or not callable(detector) or not callable(coordinator):
            raise LabRefusal("LONG_GAP_RECOVERY_UNAVAILABLE")
        previous = sample_type(
            monotonic_seconds=Decimal("100"),
            wall_utc=observed_now - timedelta(seconds=40),
        )
        current = sample_type(monotonic_seconds=Decimal("140"), wall_utc=observed_now)
        decision = detector(
            previous,
            current,
            maximum_monotonic_gap_seconds=Decimal("10"),
            maximum_wall_skew_seconds=Decimal("2"),
        )
        if (
            getattr(decision, "discontinuity", None) is not True
            or getattr(decision, "reason_code", None) != "MONOTONIC_GAP"
        ):
            raise LabRefusal("LONG_GAP_DETECTION_FAILED")
        guarded = mutate(
            "long_gap_recovery",
            lambda: coordinator(decision, current),
        )
        recovered = guarded.get("result") if type(guarded) is dict else None
        if (
            type(recovered) is not dict
            or recovered.get("allowed") is not True
            or recovered.get("reason_code") != "RECOVERY_COMPLETE"
        ):
            raise LabRefusal("LONG_GAP_RECOVERY_FAILED")
        self._require_zero_blockers()
        return {
            "success": True,
            "stage": "long-gap",
            "count": 1,
            "classification": "MONOTONIC_GAP_RECOVERED",
        }


def authorize_live_mutation(
    *,
    live: bool,
    confirmation: str | None,
    data_dir: str | os.PathLike[str],
    environment: Mapping[str, str],
    identity_reader: Callable[[], Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate every non-wallet precondition and perform one fresh identity read."""

    if live is not True:
        raise LabRefusal("LIVE_FLAG_REQUIRED")
    if type(confirmation) is not str or confirmation != LIVE_CONFIRMATION:
        raise LabRefusal("LIVE_CONFIRMATION_REQUIRED")
    path = Path(data_dir)
    if not path.is_absolute():
        raise LabRefusal("ISOLATED_DATA_DIR_REQUIRED")
    resolved = path.resolve()
    configured = environment.get("CMM_DATA_DIR")
    if type(configured) is not str or not configured:
        raise LabRefusal("ISOLATED_DATA_DIR_REQUIRED")
    try:
        configured_path = Path(configured).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise LabRefusal("ISOLATED_DATA_DIR_REQUIRED") from exc
    if configured_path != resolved:
        raise LabRefusal("ISOLATED_DATA_DIR_REQUIRED")
    if resolved in _default_user_data_directories(environment):
        raise LabRefusal("PRODUCTION_DATA_DIR_FORBIDDEN")
    _validate_marker(resolved)
    if not callable(identity_reader):
        raise LabRefusal("IDENTITY_UNAVAILABLE")
    try:
        snapshot = identity_reader()
    except BaseException as exc:
        raise LabRefusal("IDENTITY_UNAVAILABLE") from exc
    return validate_test7_identity(snapshot, now=now)


def run_guarded_mutation(
    *, operation: str, effect: Callable[[], Any], **authority: Any
) -> dict[str, Any]:
    """Run one effect only after a fresh exact authorisation at this boundary."""

    if type(operation) is not str or not operation or operation != operation.strip():
        raise LabRefusal("OPERATION_INVALID")
    if not callable(effect):
        raise LabRefusal("OPERATION_INVALID")
    identity = authorize_live_mutation(**authority)
    result = effect()
    return {"operation": operation, "identity": identity, "result": result}


def _bounded_evidence(result: Any) -> dict[str, Any]:
    if type(result) is not dict:
        return {"success": False, "reason_code": "STAGE_RESULT_MALFORMED"}
    evidence: dict[str, Any] = {}
    for key in sorted(_CHECKPOINT_EVIDENCE_KEYS):
        value = result.get(key)
        if key not in result:
            continue
        if type(value) is bool:
            evidence[key] = value
        elif type(value) is int and 0 <= value <= 2_147_483_647:
            evidence[key] = value
        elif type(value) is str and 0 < len(value) <= 128 and value.isascii():
            evidence[key] = value
    return evidence


class CheckpointStore:
    """Atomic redacted schedule checkpoints; never an economic authority."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": LAB_SCHEMA_VERSION, "order": [], "stages": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LabRefusal("CHECKPOINT_INVALID") from exc
        if (
            type(payload) is not dict
            or payload.get("schema_version") != LAB_SCHEMA_VERSION
            or type(payload.get("order")) is not list
            or type(payload.get("stages")) is not dict
        ):
            raise LabRefusal("CHECKPOINT_INVALID")
        return payload

    def completed_stages(self) -> list[str]:
        payload = self._read()
        order = payload["order"]
        if not all(type(stage) is str and stage in STAGES for stage in order):
            raise LabRefusal("CHECKPOINT_INVALID")
        return list(order)

    def run_stage(self, stage: str, action: Callable[[], Any]) -> Any:
        if type(stage) is not str or stage not in STAGES or not callable(action):
            raise LabRefusal("STAGE_INVALID")
        result = action()
        payload = self._read()
        order = payload["order"]
        stages = payload["stages"]
        if stage not in order:
            order.append(stage)
        stages[stage] = {
            "completed_at_utc": _canonical_utc(datetime.now(timezone.utc)),
            "evidence": _bounded_evidence(result),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return result


def execute_stage_plan(
    *,
    stages: list[str],
    live: bool,
    checkpoint: CheckpointStore,
    handlers: Mapping[str, Callable[..., Any]],
    authority: Mapping[str, Any],
) -> list[Any]:
    """Execute read-only stages and gate every individual wallet effect.

    A dry run records mutating stages as planned without invoking their handler
    or advancing the durable checkpoint. Read-only observations may run and be
    checkpointed without live authority. A live mutating handler receives only
    a narrow ``mutate(operation, effect)`` callback; every callback invocation
    performs a fresh exact identity check immediately before its effect.
    """

    if type(stages) is not list or type(live) is not bool:
        raise LabRefusal("STAGE_INVALID")
    if not isinstance(checkpoint, CheckpointStore):
        raise LabRefusal("CHECKPOINT_INVALID")
    if not isinstance(handlers, Mapping) or not isinstance(authority, Mapping):
        raise LabRefusal("STAGE_INVALID")

    results: list[Any] = []
    for stage in stages:
        if type(stage) is not str or stage not in STAGES:
            raise LabRefusal("STAGE_INVALID")
        handler = handlers.get(stage)
        if not callable(handler):
            raise LabRefusal("STAGE_HANDLER_MISSING")

        if stage in MUTATING_STAGES and not live:
            results.append(
                {
                    "success": True,
                    "stage": stage,
                    "planned": True,
                    "live_effects": False,
                }
            )
            continue

        if stage not in MUTATING_STAGES:
            results.append(checkpoint.run_stage(stage, handler))
            continue

        def action(
            stage_handler: Callable[..., Any] = handler,
        ) -> Any:
            def mutate(operation: str, effect: Callable[[], Any]) -> dict[str, Any]:
                return run_guarded_mutation(
                    operation=operation,
                    effect=effect,
                    **dict(authority),
                )

            return stage_handler(mutate)

        results.append(checkpoint.run_stage(stage, action))

    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CATalyst TEST 7 stability lab")
    parser.add_argument("--live", action="store_true", help="Enable guarded wallet effects")
    parser.add_argument("--confirm", help="Required exact live mainnet confirmation token")
    parser.add_argument("--data-dir", help="Explicit isolated CMM_DATA_DIR")
    parser.add_argument("--mid-price-xch", help="Explicit positive SBX midpoint override")
    parser.add_argument(
        "--trade-size-xch",
        default="0.001",
        help="Tiny lifecycle notional in XCH (0.0001 through 0.01)",
    )
    parser.add_argument(
        "--spread-fraction",
        default="0.5",
        help="Lifecycle buy discount fraction (0.25 through 0.90)",
    )
    parser.add_argument(
        "--init-data-dir",
        action="store_true",
        help="Create the isolated lab marker before a later live run",
    )
    parser.add_argument(
        "--stage",
        action="append",
        choices=STAGES,
        default=["inventory"],
        help="Checkpointed lab stage (repeatable)",
    )
    return parser


def _unsupported_stage(_mutate: Callable[..., Any] | None = None) -> Any:
    raise LabRefusal("STAGE_NOT_IMPLEMENTED")


def _decimal_argument(value: Any, reason_code: str) -> Decimal:
    if type(value) is not str or not value or len(value) > 64:
        raise LabRefusal(reason_code)
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LabRefusal(reason_code) from exc
    if not parsed.is_finite():
        raise LabRefusal(reason_code)
    return parsed


def main(
    argv: list[str] | None = None,
    *,
    environment: MutableMapping[str, str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.live and not args.data_dir:
        print("REFUSED: ISOLATED_DATA_DIR_REQUIRED", file=sys.stderr)
        return 2
    if args.init_data_dir:
        if not args.data_dir:
            print("REFUSED: ISOLATED_DATA_DIR_REQUIRED", file=sys.stderr)
            return 2
        try:
            path = initialize_lab_directory(args.data_dir)
        except LabRefusal as exc:
            print(f"REFUSED: {exc.reason_code}", file=sys.stderr)
            return 2
        print(json.dumps({"initialized": True, "data_dir": str(path)}))
        return 0
    if args.data_dir:
        active_environment = os.environ if environment is None else environment
        source_root = Path(__file__).resolve().parents[1] / "src" / "catalyst"
        live_runtime_started = False
        try:
            if args.live and args.confirm != LIVE_CONFIRMATION:
                raise LabRefusal("LIVE_CONFIRMATION_REQUIRED")
            data_dir = prepare_runtime_environment(
                data_dir=args.data_dir,
                environment=active_environment,
                source_root=source_root,
            )
            runtime = CatalystLabRuntime(load_public_modules())
            inventory_cache: dict[str, Any] = {}

            def inventory_handler() -> dict[str, Any]:
                snapshot = runtime.inventory()
                inventory_cache.clear()
                inventory_cache.update(snapshot)
                return snapshot

            def lifecycle_handler(
                mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
            ) -> dict[str, Any]:
                inventory = inventory_cache or inventory_handler()
                if args.mid_price_xch is None:
                    price_result = runtime.market_price(inventory)
                    mid_price = _decimal_argument(
                        price_result["mid_price_xch"],
                        "PRICE_UNAVAILABLE",
                    )
                else:
                    mid_price = _decimal_argument(
                        args.mid_price_xch,
                        "LIFECYCLE_PARAMETERS_INVALID",
                    )
                return runtime.lifecycle(
                    mutate,
                    inventory=inventory,
                    mid_price=mid_price,
                    trade_size_xch=_decimal_argument(
                        args.trade_size_xch,
                        "LIFECYCLE_PARAMETERS_INVALID",
                    ),
                    spread_fraction=_decimal_argument(
                        args.spread_fraction,
                        "LIFECYCLE_PARAMETERS_INVALID",
                    ),
                    terminal_attempts=36,
                    terminal_poll_seconds=5,
                )

            def replacement_handler(
                mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
            ) -> dict[str, Any]:
                inventory = inventory_cache or inventory_handler()
                if args.mid_price_xch is None:
                    mid_price = _decimal_argument(
                        runtime.market_price(inventory)["mid_price_xch"],
                        "PRICE_UNAVAILABLE",
                    )
                else:
                    mid_price = _decimal_argument(
                        args.mid_price_xch,
                        "LIFECYCLE_PARAMETERS_INVALID",
                    )
                return runtime.replacement(
                    mutate,
                    inventory=inventory,
                    mid_price=mid_price,
                    trade_size_xch=_decimal_argument(
                        args.trade_size_xch,
                        "LIFECYCLE_PARAMETERS_INVALID",
                    ),
                    spread_fraction=_decimal_argument(
                        args.spread_fraction,
                        "LIFECYCLE_PARAMETERS_INVALID",
                    ),
                    terminal_attempts=72,
                    terminal_poll_seconds=5,
                )

            def fill_handler(
                mutate: Callable[[str, Callable[[], Any]], dict[str, Any]],
            ) -> dict[str, Any]:
                inventory = inventory_cache or inventory_handler()
                if args.mid_price_xch is None:
                    mid_price = _decimal_argument(
                        runtime.market_price(inventory)["mid_price_xch"],
                        "PRICE_UNAVAILABLE",
                    )
                else:
                    mid_price = _decimal_argument(
                        args.mid_price_xch,
                        "LIFECYCLE_PARAMETERS_INVALID",
                    )
                return runtime.fill(
                    mutate,
                    inventory=inventory,
                    mid_price=mid_price,
                    trade_size_xch=_decimal_argument(
                        args.trade_size_xch,
                        "LIFECYCLE_PARAMETERS_INVALID",
                    ),
                    terminal_attempts=72,
                    terminal_poll_seconds=5,
                )

            handlers: dict[str, Callable[..., Any]] = {
                stage: _unsupported_stage for stage in STAGES
            }
            handlers.update(
                {
                    "inventory": inventory_handler,
                    "reconcile": runtime.reconcile,
                    "lifecycle": lifecycle_handler,
                    "restart": runtime.restart,
                    "stale-read": lambda: runtime.stale_read(
                        data_dir=data_dir,
                        environment=active_environment,
                    ),
                    "long-gap": runtime.long_gap,
                    "replacement": replacement_handler,
                    "fill": fill_handler,
                    "soak": runtime.soak,
                    "final-reconcile": runtime.final_reconcile,
                }
            )
            checkpoint = CheckpointStore(data_dir / CHECKPOINT_NAME)
            authority: dict[str, Any] = {}
            if args.live:
                authority = {
                    "live": True,
                    "confirmation": args.confirm,
                    "data_dir": data_dir,
                    "environment": active_environment,
                    "identity_reader": runtime.wallet.get_wallet_identity,
                }
                authorize_live_mutation(**authority)
                runtime._require_database_integrity()
                startup = runtime.api_server.initialize_mutation_runtime(
                    start_heartbeat=True,
                    acquire_lease=True,
                )
                if type(startup) is not dict or startup.get("allowed") is not True:
                    raise LabRefusal("MUTATION_RUNTIME_NOT_ALLOWED")
                live_runtime_started = True
            results = execute_stage_plan(
                stages=args.stage,
                live=args.live,
                checkpoint=checkpoint,
                handlers=handlers,
                authority=authority,
            )
        except LabRefusal as exc:
            print(f"REFUSED: {exc.reason_code}", file=sys.stderr)
            return 2
        finally:
            if live_runtime_started:
                try:
                    runtime.api_server.release_mutation_runtime()
                except BaseException:
                    pass
        print(
            json.dumps(
                {
                    "success": True,
                    "mode": "live" if args.live else "read-only",
                    "live_effects": args.live,
                    "results": results,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 0
    print(
        json.dumps(
            {
                "mode": "dry-run",
                "stages": args.stage,
                "live_effects": False,
                "expected_identity": {
                    "backend": EXPECTED_BACKEND,
                    "name": EXPECTED_NAME,
                    "fingerprint": EXPECTED_FINGERPRINT,
                    "network_id": EXPECTED_NETWORK,
                    "kind": EXPECTED_KIND,
                    "has_secrets": True,
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
