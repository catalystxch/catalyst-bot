"""Auto-resolve CAT metadata (pair_id, ticker_id, short_name) from TibetSwap

Given CAT_ASSET_ID, looks up the TibetSwap pair and fills any empty
derived fields on the cfg singleton so operators don't have to enter
them by hand. Called once at startup via `resolve_and_apply(cfg)`.

Key responsibilities:
    - Populate TIBET_PAIR_ID, CAT_TICKER_ID, and CAT_NAME when blank
    - Overwrite CAT_NAME only when empty or the generic default "MZ"
    - Cache the resolved metadata to avoid repeat network calls

CAT_DECIMALS is intentionally NOT auto-resolved — a wrong value would
corrupt every offer amount, so it must be set manually when it differs
from the default. Failures are soft: the bot continues even if TibetSwap
is unreachable.
"""

import time
import threading
import requests
from typing import Optional, Dict
from database import log_event

try:
    from api_call_tracker import record as _record_api_call
except Exception:

    def _record_api_call(*args, **kwargs):
        return None


# Module-level cache so resolver only hits the network once per process.
_cache: Optional[Dict] = None
_cache_lock = threading.Lock()
_last_resolve_at: float = 0
_CACHE_TTL_SECS = 300  # 5 minutes — refresh if bot is long-running


def resolve_cat_metadata(
    asset_id: str,
    tibet_api_base: str | None = None,
    timeout: int = 10,
    *,
    dexie_api_base: str = "https://api.dexie.space",
) -> Dict:
    """Query Dexie to resolve CAT metadata from an exact asset ID.

    Returns dict with keys: pair_id, ticker_id, name, short_name, verified,
    and pair_lookup_status.  The status distinguishes a successful lookup
    with no matching pool from an unavailable provider.

    This is safe to call at startup — failures return empty dict, never raise.
    """
    result = {
        "pair_id": None,
        "ticker_id": None,
        "name": None,
        "short_name": None,
        "verified": None,
        "pair_lookup_status": "retired",
        "retired_provider": "TibetSwap",
        "metadata_provider": "dexie",
        "metadata_lookup_status": "not_found",
    }

    if not asset_id:
        return result

    asset_id_norm = asset_id.lower().strip()
    base = dexie_api_base.rstrip("/")

    try:
        _record_api_call("dexie", "/v2/prices/tickers")
        resp = requests.get(
            f"{base}/v2/prices/tickers",
            params={"asset_id": asset_id_norm.removeprefix("0x")},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("tickers", []) if isinstance(payload, dict) else payload
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            row_asset = (
                str(
                    row.get("base_id")
                    or row.get("asset_id")
                    or row.get("base_asset_id")
                    or ""
                )
                .lower()
                .removeprefix("0x")
            )
            if row_asset and row_asset != asset_id_norm.removeprefix("0x"):
                continue
            ticker_id = str(row.get("ticker_id") or "").strip().upper()
            short_name = str(
                row.get("base_currency")
                or row.get("base_code")
                or (ticker_id.split("_", 1)[0] if ticker_id else "")
            ).strip()
            result["ticker_id"] = ticker_id or (
                f"{short_name}_XCH" if short_name else None
            )
            result["short_name"] = short_name or None
            result["name"] = (
                row.get("base_name") or row.get("asset_name") or row.get("name") or None
            )
            result["verified"] = row.get("verified")
            result["metadata_lookup_status"] = "resolved"
            break
    except Exception as e:
        result["metadata_lookup_status"] = "unavailable"
        log_event(
            "warning",
            "cat_resolver_dexie_fetch_failed",
            f"CAT resolver: could not fetch token metadata from Dexie: {e}",
        )

    return result


def resolve_and_apply(cfg_obj, force: bool = False) -> Dict:
    """Resolve CAT metadata and apply any missing fields to cfg.

    Only fills fields that are empty/unset in cfg — never overwrites .env values.

    Args:
        cfg_obj : The live cfg object (config.Config instance)
        force   : Bypass the 5-minute cache and re-fetch from API

    Returns the resolved metadata dict (useful for logging/display).
    """
    global _cache, _last_resolve_at

    asset_id = getattr(cfg_obj, "CAT_ASSET_ID", "").strip()
    if not asset_id:
        return {}

    # Return cached result unless stale or forced
    with _cache_lock:
        now = time.time()
        if (
            not force
            and _cache is not None
            and (now - _last_resolve_at) < _CACHE_TTL_SECS
        ):
            _apply_to_cfg(_cache, cfg_obj)
            return dict(_cache)

    # Fetch fresh from the active offer-book ecosystem.
    dexie_base = str(
        getattr(cfg_obj, "DEXIE_API_BASE", "https://api.dexie.space")
        or "https://api.dexie.space"
    )
    metadata = resolve_cat_metadata(
        asset_id,
        timeout=int(getattr(cfg_obj, "DEXIE_TIMEOUT", 10) or 10),
        dexie_api_base=dexie_base,
    )

    with _cache_lock:
        _cache = metadata
        _last_resolve_at = time.time()

    _apply_to_cfg(metadata, cfg_obj)
    return dict(metadata)


def _apply_to_cfg(metadata: Dict, cfg_obj) -> None:
    """Write resolved values into cfg — only for fields that are currently empty.

    Fields already set in .env (i.e. non-empty in cfg) are left untouched.
    """
    applied = []
    skipped = []

    # TIBET_PAIR_ID — empty string default in config.py
    if metadata.get("pair_id"):
        current = str(getattr(cfg_obj, "TIBET_PAIR_ID", "") or "").strip()
        if not current:
            cfg_obj.update("TIBET_PAIR_ID", metadata["pair_id"])
            applied.append(f"TIBET_PAIR_ID={metadata['pair_id'][:16]}...")
        else:
            skipped.append(f"TIBET_PAIR_ID (already: {current[:16]}...)")

    # CAT_TICKER_ID — empty default
    if metadata.get("ticker_id"):
        current = str(getattr(cfg_obj, "CAT_TICKER_ID", "") or "").strip()
        if not current:
            cfg_obj.update("CAT_TICKER_ID", metadata["ticker_id"])
            applied.append(f"CAT_TICKER_ID={metadata['ticker_id']}")
        else:
            skipped.append(f"CAT_TICKER_ID (already: {current})")

    # CAT_NAME — default "MZ" treated as not explicitly set
    if metadata.get("name"):
        current = str(getattr(cfg_obj, "CAT_NAME", "") or "").strip()
        # Only fill if empty or still the generic default "MZ"
        if not current or current == "MZ":
            cfg_obj.update("CAT_NAME", metadata["name"])
            applied.append(f"CAT_NAME={metadata['name']}")
        else:
            skipped.append(f"CAT_NAME (already: {current})")

    if applied or skipped:
        log_event(
            "info",
            "cat_resolver_applied",
            f"CAT metadata resolved from Dexie — "
            f"applied: [{', '.join(applied) or 'none'}] | "
            f"kept .env: [{', '.join(skipped) or 'none'}]",
        )
    else:
        log_event(
            "debug",
            "cat_resolver_noop",
            "CAT resolver: no metadata found or all fields already set",
        )
