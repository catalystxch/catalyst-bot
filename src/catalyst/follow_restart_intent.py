"""Durable, non-authoritative intent to continue a reviewed Follow run.

The record only remembers that the user had a Follow run running. It grants no
wallet effect authority; startup must reprove financial authority, wallet
identity, sync state, offer membership, and unknown-effect recovery separately.
"""

from __future__ import annotations

import json
import re
import time


_SETTING_KEY = "follow_restart_intent_v1"
_VERSION = 1


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_identity(identity: object) -> bool:
    return (
        type(identity) is dict
        and identity.get("network") == "mainnet"
        and identity.get("wallet_type") == "sage"
        and type(identity.get("wallet_fingerprint")) is int
        and identity["wallet_fingerprint"] > 0
        and type(identity.get("asset_id")) is str
        and re.fullmatch(r"[0-9a-f]{64}", identity["asset_id"]) is not None
        and type(identity.get("wallet_id")) is int
        and identity["wallet_id"] >= 0
        and type(identity.get("xch_wallet_id")) is int
        and identity["xch_wallet_id"] >= 0
    )


def bind_follow_restart_intent(
    *,
    run_id: str,
    identity: dict,
    configuration_sha256: str,
    now_epoch: int | None = None,
) -> dict:
    """Persist a running intent after an approved Follow start succeeds."""
    if (
        not _digest(run_id)
        or not _valid_identity(identity)
        or not _digest(configuration_sha256)
        or (now_epoch is not None and (type(now_epoch) is not int or now_epoch <= 0))
    ):
        raise ValueError("FOLLOW_RESTART_INTENT_INVALID")
    record = {
        "version": _VERSION,
        "state": "running",
        "run_id": run_id,
        "identity": identity,
        "configuration_sha256": configuration_sha256,
        "updated_at_epoch": int(time.time()) if now_epoch is None else now_epoch,
    }
    serialized = json.dumps(
        record, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    import database

    if database.set_setting(_SETTING_KEY, serialized) is not True:
        raise ValueError("FOLLOW_RESTART_INTENT_PERSIST_FAILED")
    return record


def clear_follow_restart_intent(
    *, reason: str = "manual_stop", now_epoch: int | None = None
) -> dict:
    """Durably disable automatic continuation after an explicit Stop."""
    if (
        type(reason) is not str
        or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason)
        or (now_epoch is not None and (type(now_epoch) is not int or now_epoch <= 0))
    ):
        raise ValueError("FOLLOW_RESTART_INTENT_INVALID")
    record = {
        "version": _VERSION,
        "state": "stopped",
        "reason": reason,
        "updated_at_epoch": int(time.time()) if now_epoch is None else now_epoch,
    }
    import database

    serialized = json.dumps(
        record, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    if database.set_setting(_SETTING_KEY, serialized) is not True:
        raise ValueError("FOLLOW_RESTART_INTENT_PERSIST_FAILED")
    return record


def read_follow_restart_intent() -> dict | None:
    """Read only a well-formed running intent; malformed data never resumes."""
    import database

    try:
        raw = database.get_setting(_SETTING_KEY)
    except Exception:
        return None
    if type(raw) is not str:
        return None
    try:
        record = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if type(record) is not dict or record.get("state") != "running":
        return None
    if (
        record.get("version") != _VERSION
        or not _digest(record.get("run_id"))
        or not _valid_identity(record.get("identity"))
        or not _digest(record.get("configuration_sha256"))
        or type(record.get("updated_at_epoch")) is not int
        or record["updated_at_epoch"] <= 0
    ):
        return None
    return record


def restart_intent_matches(
    record: object,
    *,
    run_id: str,
    identity: dict,
    configuration_sha256: str,
) -> bool:
    """Compare a saved intent against the exact current Follow scope."""
    return bool(
        type(record) is dict
        and record.get("run_id") == run_id
        and record.get("identity") == identity
        and record.get("configuration_sha256") == configuration_sha256
        and _digest(run_id)
        and _valid_identity(identity)
        and _digest(configuration_sha256)
    )


def automatic_resume_empty_book(automatic_resume: bool, snapshot: object) -> bool:
    """Allow empty-book resume only from a complete, verified snapshot."""
    return bool(
        automatic_resume
        and type(snapshot) is tuple
        and len(snapshot) == 3
        and all(type(rows) is list and not rows for rows in snapshot)
    )
