"""Market / pricing / Dexie / Coinset / debug routes.

Covers the market-intel surface (Dexie stats, orderbook, slippage, DBX
eligibility, TibetSwap AMM, price feeds) and the debug endpoints used by
operators to sanity-check pricing, coin prep, and Sage offer creation.

`_fetch_dbx_pair_status` lives here since only market routes use it.
`_fetch_price_standalone` and `_fetch_dexie_orderbook_standalone` stay in
api_server because smart-defaults also uses them; blueprint routes reach
them via `api_server.xxx`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

import api_server
import database
from config import cfg
from database import log_event

try:
    from api_call_tracker import record as _record_api_call
except Exception:

    def _record_api_call(*args, **kwargs):
        return None


bp = Blueprint("market", __name__)

_TIBET_PAIRS_CACHE_LOCK = threading.RLock()
_TIBET_PAIRS_CACHE = {"base": "", "fetched_at": 0.0, "pairs": []}
_TIBET_PAIRS_CACHE_TTL_SECS = 60.0

_STARTUP_PRICE_LOCK = threading.Lock()
_STARTUP_PRICE_CACHE = {"key": None, "expires_at": 0.0, "price": {}}


def _get_startup_price_cached(asset_id, ticker_id, decimals=3) -> dict:
    """Read-only setup pricing from the executable Dexie offer book.

    Never call PriceEngine.get_price here: GUI polling must not write price
    history or advance the trading engine's risk/reference state. Cache both
    successes and failures so an outage cannot amplify five-second UI polling.
    """
    asset = str(asset_id or "").strip().lower().removeprefix("0x")
    ticker = str(ticker_id or "").strip().upper()
    if ticker and "_" not in ticker:
        ticker += "_XCH"
    if not asset:
        return {}
    dexie_base = getattr(cfg, "DEXIE_API_BASE", "https://api.dexie.space").rstrip("/")
    key = (asset, ticker, decimals, dexie_base)
    with _STARTUP_PRICE_LOCK:
        if (
            _STARTUP_PRICE_CACHE["key"] == key
            and time.monotonic() < _STARTUP_PRICE_CACHE["expires_at"]
        ):
            return dict(_STARTUP_PRICE_CACHE["price"])
        price = {}
        if ticker:
            try:
                import requests

                _record_api_call("dexie", "/v2/prices/tickers")
                response = requests.get(
                    f"{dexie_base}/v2/prices/tickers",
                    params={"ticker_id": ticker},
                    timeout=5,
                )
                payload = response.json() if response.status_code == 200 else []
                rows = (
                    payload.get("tickers", []) if isinstance(payload, dict) else payload
                )
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("ticker_id", "")).upper() != ticker:
                        continue
                    row_asset = (
                        str(row.get("base_id") or "").strip().lower().removeprefix("0x")
                    )
                    if row_asset and row_asset != asset:
                        continue
                    bid = Decimal(str(row.get("bid") or row.get("best_bid") or 0))
                    ask = Decimal(str(row.get("ask") or row.get("best_ask") or 0))
                    if bid.is_finite() and ask.is_finite() and 0 < bid <= ask:
                        price = {
                            "mid": str((bid + ask) / 2),
                            "source": "dexie_bid_ask",
                            "tibet_available": False,
                            "tibet_status": "retired",
                        }
                    # Historical last_price is not a current executable quote.
                    break
            except (
                requests.RequestException,
                OSError,
                InvalidOperation,
                ValueError,
                TypeError,
                AttributeError,
            ):
                # A failed Dexie fallback leaves startup pricing unavailable.
                pass
        _STARTUP_PRICE_CACHE.update(
            key=key,
            price=price,
            expires_at=time.monotonic() + (60.0 if price else 15.0),
        )
        return dict(price)


def _get_tibet_pairs_cached(base: str = None, timeout: int = 8) -> list:
    """One-release compatibility stub for the retired provider."""

    return []


def _fetch_dbx_pair_status(asset_id: str, ticker_id: str) -> dict:
    """Fetch Dexie pair-level rewards status from /v1/incentives.

    The previous implementation looked for an ``incentives`` field on the
    ticker response that doesn't exist there, so it always returned None.
    The authoritative source is /v1/incentives, which dexie_incentives.py
    wraps with a 5-minute cache.

    Returns the projected per-direction shape used by the GUI Market Intel
    panel and Smart Settings.
    """
    result: dict = {
        "pair_incentivized": None,
        "pair_source": "",
        "buy": None,
        "sell": None,
    }
    if not asset_id:
        return result

    try:
        from dexie_incentives import fetch_incentives, get_pair_incentives

        bulk = fetch_incentives()
        # If the upstream call genuinely failed (no incentives at all and
        # success=False) we keep pair_incentivized as None so the GUI can
        # render "unavailable" instead of falsely claiming "not incentivized".
        if not bulk.get("success") and not bulk.get("incentives"):
            result["pair_source"] = "unavailable"
            return result
        pair = get_pair_incentives(asset_id)
        result["pair_incentivized"] = bool(pair.get("incentivized"))
        result["pair_source"] = "dexie_incentives_api"
        result["buy"] = pair.get("buy")
        result["sell"] = pair.get("sell")
    except Exception:
        result["pair_source"] = "unavailable"
    return result


@bp.route("/api/dexie/stats")
def api_dexie_stats():
    """Get Dexie posting statistics."""
    bot = api_server.bot
    if not bot:
        return jsonify({"error": "Bot not initialised"}), 500
    return jsonify(bot.dexie_manager.get_stats())


@bp.route("/api/dexie/repost", methods=["POST"])
def api_dexie_repost():
    """Repost all active offers to Dexie."""
    bot = api_server.bot
    if not bot:
        return jsonify({"error": "Bot not initialised"}), 500
    open_buys, open_sells, _ = bot.offer_manager.sync_from_wallet()
    all_offers = open_buys + open_sells
    bot.dexie_manager.repost_active_offers(all_offers)
    return jsonify({"status": "queued", "count": len(all_offers)})


@bp.route("/api/market/intel")
def api_market_intel():
    """Get full market intelligence summary.

    Includes competitor analysis, orderbook depth, and DBX eligibility.
    """
    bot = api_server.bot
    if not bot:
        return jsonify({"error": "Bot not initialised"}), 500

    try:
        bot.market_intel.refresh_orderbook(force=True)
    except Exception:
        pass

    summary = bot.market_intel.get_market_summary()
    asset_id = api_server._active_cat.get("asset_id") or getattr(
        cfg, "CAT_ASSET_ID", ""
    )
    ticker_id = api_server._active_cat.get("ticker_id") or getattr(
        cfg, "CAT_TICKER_ID", ""
    )
    try:
        buy_spread = bot.risk_manager.get_adjusted_spread("buy")
        sell_spread = bot.risk_manager.get_adjusted_spread("sell")
        avg_spread_bps = ((buy_spread + sell_spread) / 2) * Decimal("10000")
        mid_price = bot.price_engine.get_last_price() or Decimal("0")
        live_dbx = bot.market_intel.check_dbx_eligibility(avg_spread_bps, mid_price)
    except Exception:
        live_dbx = {}
        mid_price = Decimal("0")

    # A stopped bot commonly has no in-memory PriceEngine value even though the
    # forced Dexie refresh above returned a current executable book.  Preserve
    # that read-only midpoint for explorer-price sanity checks; otherwise the
    # Spacescan panel reports a zero gap and can hide a materially stale or
    # incompatible explorer quote.
    if mid_price <= 0:
        try:
            public_bid = Decimal(str(summary.get("best_bid") or 0))
            public_ask = Decimal(str(summary.get("best_ask") or 0))
            if (
                public_bid.is_finite()
                and public_ask.is_finite()
                and 0 < public_bid <= public_ask
            ):
                mid_price = (public_bid + public_ask) / Decimal("2")
        except (InvalidOperation, ValueError, TypeError, AttributeError):
            # Malformed public quotes cannot supply a safe executable midpoint.
            pass

    try:
        local_book = api_server._get_live_local_offer_edges(asset_id)
        our_best_bid = local_book.get("our_best_bid", Decimal("0"))
        our_best_ask = local_book.get("our_best_ask", Decimal("0"))
        summary["our_best_bid"] = str(our_best_bid)
        summary["our_best_ask"] = str(our_best_ask)
        summary["our_open_buys"] = int(local_book.get("our_open_buys", 0) or 0)
        summary["our_open_sells"] = int(local_book.get("our_open_sells", 0) or 0)
        summary["live_book_source"] = local_book.get("source", "")
        if our_best_bid > 0 and our_best_ask > our_best_bid:
            our_mid = (our_best_bid + our_best_ask) / Decimal("2")
            summary["our_spread_bps"] = str(
                (our_best_ask - our_best_bid) / our_mid * Decimal("10000")
            )
        else:
            summary["our_spread_bps"] = "0"

        ext_best_bid = Decimal(
            str(summary.get("overall_best_bid") or summary.get("best_bid") or 0)
        )
        ext_best_ask = Decimal(
            str(summary.get("overall_best_ask") or summary.get("best_ask") or 0)
        )
        overall_best_bid = max(ext_best_bid, our_best_bid)
        bid_candidates = [v for v in (ext_best_ask, our_best_ask) if v > 0]
        overall_best_ask = min(bid_candidates) if bid_candidates else Decimal("0")
        summary["overall_best_bid"] = str(overall_best_bid)
        summary["overall_best_ask"] = str(overall_best_ask)
        if (
            overall_best_bid > 0
            and overall_best_ask > 0
            and overall_best_bid < overall_best_ask
        ):
            overall_mid = (overall_best_bid + overall_best_ask) / 2
            summary["overall_spread_bps"] = str(
                ((overall_best_ask - overall_best_bid) / overall_mid * Decimal("10000"))
                if overall_mid > 0
                else Decimal("0")
            )
        elif overall_best_bid > 0 and overall_best_ask > 0:
            summary["overall_spread_bps"] = "0"
    except Exception:
        pass

    dbx = dict(summary.get("dbx") or {})
    if dbx or live_dbx:
        if live_dbx:
            dbx["eligible"] = bool(live_dbx.get("eligible_offers", 0))
            dbx["eligible_offers"] = live_dbx.get("eligible_offers", 0)
            dbx["eligible_buy"] = bool(live_dbx.get("eligible_buy", False))
            dbx["eligible_sell"] = bool(live_dbx.get("eligible_sell", False))
            dbx["max_spread_bps"] = str(
                live_dbx.get("max_eligible_spread", dbx.get("max_spread_bps", "0"))
            )
            dbx["estimated_apr"] = str(
                live_dbx.get("estimated_dbx_rate", dbx.get("estimated_apr", "0"))
            )
            dbx["buy_incentive"] = live_dbx.get("buy_incentive")
            dbx["sell_incentive"] = live_dbx.get("sell_incentive")
            dbx["pair_incentivized"] = live_dbx.get("pair_incentivized")
        dbx["spread_eligible"] = bool(dbx.get("eligible"))
        # Refresh pair_incentivized + per-direction details from the live
        # /v1/incentives cache. check_dbx_eligibility is TTL-gated (5 min)
        # so this fills in current data even when the eligibility check
        # itself was skipped this cycle.
        dbx.update(_fetch_dbx_pair_status(asset_id, ticker_id))
        summary["dbx"] = dbx

    try:
        splash = bot.splash_manager.get_stats()
        splash["health"] = bot.splash_manager.check_health()
        summary["splash"] = splash
    except Exception:
        pass

    try:
        summary["splash_node"] = bot.splash_node.get_status()
    except Exception:
        pass

    try:
        summary["splash_receive"] = bot.get_splash_receive_stats()
    except Exception:
        pass

    try:
        summary["spacescan"] = api_server._get_spacescan_market_context(
            asset_id=asset_id,
            ticker_id=ticker_id,
            decimals=int(
                api_server._active_cat.get("decimals")
                or getattr(cfg, "CAT_DECIMALS", 3)
                or 3
            ),
            executable_mid_price=float(mid_price or 0),
        )
    except Exception:
        pass

    return jsonify(api_server._serialize_dict(summary))


@bp.route("/api/dbx/info")
def api_dbx_info():
    """Lightweight per-pair Dexie-incentive lookup.

    Query: ?asset_id=<hex>  (defaults to the active CAT)

    Returns just the projected incentive blob for the requested pair —
    no orderbook refresh, no market-intel computation. The Smart
    Settings DBX-cap pre-prompt calls this so the modal appears
    instantly instead of waiting on a forced /api/market/intel refresh.
    """
    asset_id = (request.args.get("asset_id") or "").strip()
    if not asset_id:
        asset_id = api_server._active_cat.get("asset_id") or getattr(
            cfg, "CAT_ASSET_ID", ""
        )
    out = {
        "asset_id": asset_id,
        "pair_incentivized": None,
        "max_spread_bps": 0,
        "estimated_apr": 0.0,
        "reward_token": "",
        "buy": None,
        "sell": None,
        # Whether new offer posts carry the claim_rewards flag — drives
        # the GUI's Pending Rewards panel UX (auto-claim ON → hide manual
        # claim button, show "auto-paid by Dexie" copy).
        "auto_claim_enabled": bool(getattr(cfg, "DEXIE_AUTO_CLAIM_REWARDS", True)),
    }
    if not asset_id:
        return jsonify(out)
    try:
        from dexie_incentives import fetch_incentives, get_pair_incentives

        bulk = fetch_incentives()
        if not bulk.get("success") and not bulk.get("incentives"):
            return jsonify(out)  # API unreachable — pair_incentivized stays None
        pair = get_pair_incentives(asset_id)
        out["pair_incentivized"] = bool(pair.get("incentivized"))
        out["buy"] = pair.get("buy")
        out["sell"] = pair.get("sell")
        sides = [s for s in (out["buy"], out["sell"]) if s]
        caps = [
            int(s.get("max_spread_bps") or 0)
            for s in sides
            if (s.get("max_spread_bps") or 0) > 0
        ]
        if caps:
            out["max_spread_bps"] = min(caps)
        aprs = [
            float(s.get("estimated_apr") or 0)
            for s in sides
            if (s.get("estimated_apr") or 0) > 0
        ]
        if aprs:
            out["estimated_apr"] = max(aprs)
        for s in sides:
            tok = (s.get("reward_token") or "").strip()
            if tok:
                out["reward_token"] = tok
                break
    except Exception:
        pass
    return jsonify(out)


@bp.route("/api/dbx/pending")
def api_dbx_pending():
    """List the user's offers that currently have claimable Dexie rewards."""
    try:
        from dexie_claims import list_pending_rewards

        result = list_pending_rewards() or {}
        # Include the auto-claim toggle so the GUI panel can render the
        # right messaging in a single round-trip (auto-claim ON →
        # informational only; auto-claim OFF → show Claim button).
        result["auto_claim_enabled"] = bool(
            getattr(cfg, "DEXIE_AUTO_CLAIM_REWARDS", True)
        )
        return jsonify(result)
    except Exception as e:
        log_event("error", "dbx_claim", f"pending lookup failed: {e}")
        return jsonify(
            {
                "success": False,
                "error": "pending_rewards_lookup_failed",
                "offers": [],
                "totals": {},
            }
        )


@bp.route("/api/dbx/claim", methods=["POST"])
def api_dbx_claim():
    """Sign and submit claims for all pending Dexie rewards.

    Optional JSON body: ``{"target_address": "xch1..."}`` to redirect rewards
    to a different address. No XCH leaves the wallet — only a signed
    message is sent to Dexie.
    """
    payload = request.get_json(silent=True) or {}
    target = (payload.get("target_address") or "").strip() or None
    try:
        from dexie_claims import claim_all

        result = claim_all(target_address=target)
    except Exception as e:
        log_event("error", "dbx_claim", f"claim failed: {e}")
        return jsonify({"success": False, "error": "reward_claim_failed"})
    log_event(
        "success" if result.get("success") else "warning",
        "dbx_claim",
        f"claim attempt: submitted={result.get('claims_submitted', 0)} "
        f"success={result.get('success')}",
    )
    return jsonify(result)


@bp.route("/api/market/price-history")
def api_market_price_history():
    """Return persisted price samples for the active pair."""
    asset_id = api_server._active_cat.get("asset_id") or getattr(
        cfg, "CAT_ASSET_ID", ""
    )
    if not asset_id:
        return jsonify({"success": False, "error": "No active CAT", "points": []}), 400

    try:
        hours = float(request.args.get("hours", "0.333333") or "0.333333")
    except (TypeError, ValueError):
        hours = 0.333333
    hours = max(0.01, min(hours, 24.0))

    try:
        limit = int(request.args.get("limit", "3000") or "3000")
    except (TypeError, ValueError):
        limit = 3000
    limit = max(2, min(limit, 5000))

    try:
        from database import get_recent_prices

        rows = get_recent_prices(asset_id, hours=hours, limit=limit)
        points = [
            {
                "timestamp": row.get("timestamp"),
                "mid": row.get("combined_price"),
                "dexie": row.get("dexie_price"),
                "tibet": row.get("tibet_price"),
                "strategy": row.get("strategy_used"),
            }
            for row in rows
        ]
        return jsonify(
            {
                "success": True,
                "asset_id": asset_id,
                "range_hours": hours,
                "points": points,
            }
        )
    except Exception:
        return api_server._api_exception(request.path)


@bp.route("/api/market/orderbook")
def api_market_orderbook():
    """Force refresh and return orderbook data."""
    bot = api_server.bot
    if not bot:
        return jsonify({"error": "Bot not initialised"}), 500

    data = bot.market_intel.refresh_orderbook(force=True)
    return jsonify(api_server._serialize_dict(data))


@bp.route("/api/market/slippage")
def api_market_slippage():
    """One-release compatibility endpoint for retired AMM slippage."""

    return jsonify(
        {
            "available": False,
            "provider": "tibetswap",
            "status": "retired",
            "reason": "TIBETSWAP_SHUTDOWN",
        }
    )


@bp.route("/api/market/dbx")
def api_market_dbx():
    """Get DBX rewards eligibility status."""
    bot = api_server.bot
    if not bot:
        return jsonify({"error": "Bot not initialised"}), 500

    try:
        buy_spread = bot.risk_manager.get_adjusted_spread("buy")
        sell_spread = bot.risk_manager.get_adjusted_spread("sell")
        avg_spread_bps = ((buy_spread + sell_spread) / 2) * Decimal("10000")
        mid_price = bot.price_engine.get_last_price() or Decimal("0")

        dbx = bot.market_intel.check_dbx_eligibility(avg_spread_bps, mid_price)
        asset_id = api_server._active_cat.get("asset_id") or getattr(
            cfg, "CAT_ASSET_ID", ""
        )
        ticker_id = api_server._active_cat.get("ticker_id") or getattr(
            cfg, "CAT_TICKER_ID", ""
        )
        dbx["spread_eligible"] = bool(dbx.get("eligible_offers", 0))
        dbx.update(_fetch_dbx_pair_status(asset_id, ticker_id))
        return jsonify(api_server._serialize_dict(dbx))
    except Exception:
        return api_server._api_exception(request.path)


@bp.route("/api/coinset/stats")
def api_coinset_stats():
    """Get Coinset API query statistics."""
    bot = api_server.bot
    if not bot:
        return jsonify({"error": "Bot not initialised"}), 500

    stats = bot.coinset_client.get_stats()
    health = bot.coinset_client.check_health()
    stats["health"] = health
    return jsonify(stats)


@bp.route("/api/price")
def api_price():
    """Get current price from all sources."""
    bot = api_server.bot
    cfg = api_server.cfg
    asset_id = api_server._active_cat.get("asset_id") or (
        cfg.CAT_ASSET_ID if hasattr(cfg, "CAT_ASSET_ID") else ""
    )
    decimals = api_server._active_cat.get("decimals") or getattr(cfg, "CAT_DECIMALS", 3)
    ticker = api_server._active_cat.get("ticker_id") or (
        cfg.CAT_TICKER_ID if hasattr(cfg, "CAT_TICKER_ID") else ""
    )

    if bot:
        price_data = bot.price_engine.get_price(asset_id, decimals, ticker)
        result = api_server._serialize_dict(price_data)
        # GUI expects "mid" key — price_engine returns "mid_price"
        if "mid" not in result and "mid_price" in result:
            result["mid"] = result["mid_price"]
        # Ensure "success" key exists for GUI fallback check
        if "mid" not in result:
            result["mid"] = 0
        result["success"] = float(result.get("mid", 0) or 0) > 0
        return jsonify(result)

    # Bot not running — lightweight price lookup via api_server helper
    return api_server._fetch_price_standalone(asset_id, decimals)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc_timestamp(value) -> datetime | None:
    if type(value) is not str or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _post_tibet_provider_status(
    asset_id: str,
    *,
    now: datetime | None = None,
    evidence_digests: tuple[str, ...] = (),
) -> dict:
    """Return the newest durable evidence for each provider capability."""

    current_time = now or _utc_now()
    snapshot_digests = frozenset(str(value) for value in evidence_digests if value)

    declared = {
        "dexie": ["discover_offer", "order_book", "publish_offer", "settled_trades"],
        "splash": ["discover_offer", "order_book", "peer_health", "publish_offer"],
        "sage": ["chain_observation", "wallet_authority"],
        "coinset": ["chain_observation", "mempool_observation"],
        "spacescan": ["chain_observation", "token_metadata"],
    }
    providers = {
        provider: {
            "status": "unavailable",
            "capabilities": capabilities,
            "observed_at": None,
            "fresh_until": None,
            "reason_codes": ["no_current_evidence"],
        }
        for provider, capabilities in declared.items()
    }
    try:
        rows = database.get_market_provider_observations(asset_id, limit=100)
    except Exception:
        rows = []
    for row in rows:
        provider = str(row.get("provider_id") or "").lower()
        if provider not in providers or providers[provider]["observed_at"] is not None:
            continue
        if provider in {"dexie", "splash"}:
            if str(row.get("capability") or "").lower() != "order_book":
                continue
            if snapshot_digests and row.get("payload_sha256") not in snapshot_digests:
                continue
        quality = str(row.get("quality") or "unavailable").lower()
        fresh_until = _parse_utc_timestamp(row.get("fresh_until"))
        reasons = list(row.get("reason_codes") or [])
        if fresh_until is None or fresh_until < current_time:
            quality = "unavailable"
            if "evidence_expired" not in reasons:
                reasons.append("evidence_expired")
        providers[provider].update(
            status=quality,
            observed_at=row.get("observed_at"),
            fresh_until=row.get("fresh_until"),
            capability=row.get("capability"),
            payload_sha256=row.get("payload_sha256"),
            reason_codes=reasons,
        )
    if snapshot_digests:
        for provider in ("dexie", "splash"):
            if providers[provider]["observed_at"] is None:
                providers[provider]["reason_codes"] = ["snapshot_evidence_missing"]
    providers["tibetswap"] = {"status": "retired", "capabilities": []}
    return providers


def _age_confidence_snapshot(
    confidence: dict, providers: dict, *, now: datetime | None = None
) -> dict:
    """Project persisted confidence through current provider freshness.

    A durable snapshot is historical evidence, not an evergreen mutation
    permit.  When its book sources expire, the API must immediately degrade
    the displayed state even before the next runtime refresh is able to write
    another snapshot.
    """
    aged = dict(confidence)
    current_time = now or _utc_now()
    reasons = list(aged.get("reason_codes") or [])
    source_health = dict(aged.get("source_health") or {})
    fresh_books = 0
    for provider_id in ("dexie", "splash"):
        status = str((providers.get(provider_id) or {}).get("status") or "")
        if status == "valid":
            fresh_books += 1
        elif provider_id in source_health:
            source_health[provider_id] = "unavailable"
    derived_at = _parse_utc_timestamp(aged.get("derived_at"))
    if derived_at is not None and (current_time - derived_at).total_seconds() > 20:
        fresh_books = 0
        if "confidence_snapshot_expired" not in reasons:
            reasons.append("confidence_snapshot_expired")
    if fresh_books == 0:
        aged["state"] = "RED"
        if (
            aged.get("derived_at") is not None
            and "market_evidence_expired" not in reasons
        ):
            reasons.append("market_evidence_expired")
    elif fresh_books == 1 and str(aged.get("state") or "RED").upper() == "GREEN":
        aged["state"] = "AMBER"
        if "single_provider_dependency" not in reasons:
            reasons.append("single_provider_dependency")
    aged["reason_codes"] = reasons
    aged["source_health"] = source_health
    return aged


def _runtime_confidence_metrics() -> dict:
    result = getattr(api_server.bot, "_market_confidence_result", None)
    if result is None:
        return {}

    def _xch(mojos) -> str:
        value = Decimal(int(mojos or 0)) / Decimal("1000000000000")
        return format(value, "f").rstrip("0").rstrip(".") or "0"

    return {
        "independent_bid_depth_xch": _xch(
            getattr(result, "independent_bid_depth_mojos", 0)
        ),
        "independent_ask_depth_xch": _xch(
            getattr(result, "independent_ask_depth_mojos", 0)
        ),
        "required_depth_xch": _xch(getattr(result, "required_depth_mojos", 0)),
        "bid_depth_ratio": str(getattr(result, "bid_depth_ratio", "0")),
        "ask_depth_ratio": str(getattr(result, "ask_depth_ratio", "0")),
        "manipulation_score": int(getattr(result, "manipulation_score", 0)),
        "pending_movement_refreshes": int(
            getattr(result, "pending_movement_refreshes", 0)
        ),
        "excluded_own_offer_count": int(getattr(result, "excluded_own_offer_count", 0)),
        "deduplicated_offer_count": int(getattr(result, "deduplicated_offer_count", 0)),
        "derived_thresholds": dict(getattr(result, "derived_thresholds", {}) or {}),
    }


def _degraded_timeline(degraded: dict | None, *, now: datetime) -> dict | None:
    """Project the durable 0/3/10-minute policy into operator-facing time."""

    if not degraded or not degraded.get("degraded_since"):
        return None
    started = _parse_utc_timestamp(degraded.get("degraded_since"))
    if started is None:
        return None
    elapsed = max(0, int((now - started).total_seconds()))
    if elapsed < 180:
        next_stage = "MIDDLE"
        next_at = 180
    elif elapsed < 600:
        next_stage = "ALL"
        next_at = 600
    else:
        next_stage = None
        next_at = None
    return {
        "policy": "0/3/10-minute",
        "current_stage": str(degraded.get("withdrawal_stage") or "INNER").upper(),
        "elapsed_seconds": elapsed,
        "next_stage": next_stage,
        "seconds_until_next_stage": (
            max(0, next_at - elapsed) if next_at is not None else None
        ),
        "recovery_refreshes": int(degraded.get("recovery_refreshes") or 0),
        "recovery_refreshes_required": 3,
        "recovery_minimum_seconds": 60,
    }


@bp.route("/api/market/confidence")
def api_market_confidence():
    """Expose the single durable market/safety truth used by every UI tab."""

    asset_id = (
        str(
            api_server._active_cat.get("asset_id")
            or getattr(api_server.cfg, "CAT_ASSET_ID", "")
            or ""
        )
        .strip()
        .lower()
        .removeprefix("0x")
    )
    if not asset_id:
        generated_at = _utc_now().isoformat()
        return jsonify(
            {
                "market_model": "offer_book",
                "asset_id": "",
                "generated_at": generated_at,
                "confidence": {
                    "state": "RED",
                    "derived_at": None,
                    "reason_codes": ["asset_not_selected"],
                    "source_health": {},
                },
                "degraded": None,
                "migration": None,
                "providers": {"tibetswap": {"status": "retired", "capabilities": []}},
                "evidence": {
                    "derived_at": None,
                    "reason_codes": ["asset_not_selected"],
                    "source_ids": [],
                    "snapshot_digests": [],
                },
                "metrics": {},
                "can_create": False,
                "can_requote": False,
                "can_increase_exposure": False,
            }
        )

    try:
        confidence = database.get_latest_market_confidence_snapshot(asset_id)
    except Exception:
        confidence = None
    try:
        degraded = database.get_degraded_market_state(asset_id)
    except Exception:
        degraded = None
    try:
        migration = database.get_post_tibet_migration_report(asset_id)
    except Exception:
        migration = None

    if confidence is None:
        confidence = {
            "asset_id": asset_id,
            "state": "RED",
            "derived_at": None,
            "trusted_midpoint": None,
            "trusted_bid": None,
            "trusted_ask": None,
            "degraded_since": None,
            "withdrawal_stage": "NONE",
            "recovery_refreshes": 0,
            "reason_codes": ["market_evidence_warming"],
            "source_health": {},
            "evidence_digests": [],
            "material": True,
        }

    current_time = _utc_now()
    providers = _post_tibet_provider_status(
        asset_id,
        now=current_time,
        evidence_digests=tuple(confidence.get("evidence_digests") or ()),
    )
    confidence = _age_confidence_snapshot(confidence, providers, now=current_time)
    state = str(confidence.get("state") or "RED").upper()
    if degraded is not None:
        degraded = dict(degraded)
        timeline = _degraded_timeline(degraded, now=current_time)
        if timeline is not None:
            degraded["timeline"] = timeline
    degraded_active = bool(degraded and degraded.get("degraded_since"))
    can_create = state == "GREEN" and not degraded_active
    can_requote = state == "GREEN" and not degraded_active
    payload = {
        "market_model": "offer_book",
        "asset_id": asset_id,
        "generated_at": current_time.isoformat(),
        "confidence": confidence,
        "degraded": degraded,
        "migration": migration,
        "providers": providers,
        "evidence": {
            "derived_at": confidence.get("derived_at"),
            "reason_codes": list(confidence.get("reason_codes") or []),
            "source_ids": sorted(
                provider_id
                for provider_id, provider in providers.items()
                if provider_id != "tibetswap" and provider.get("observed_at")
            ),
            "snapshot_digests": list(confidence.get("evidence_digests") or []),
        },
        "metrics": _runtime_confidence_metrics(),
        "can_create": can_create,
        "can_requote": can_requote,
        "can_increase_exposure": can_create,
    }
    return jsonify(payload)


@bp.route("/api/market/summary")
def api_market_summary():
    """Lightweight market overview for the dashboard.

    Returns best bid/ask from the Dexie orderbook and 24h volume. Retired
    TibetSwap fields remain explicit read-only compatibility markers.
    """
    cfg = api_server.cfg
    import requests as _req

    asset_id = api_server._active_cat.get("asset_id") or (
        cfg.CAT_ASSET_ID if hasattr(cfg, "CAT_ASSET_ID") else ""
    )
    ticker_id = api_server._active_cat.get("ticker_id") or getattr(
        cfg, "CAT_TICKER_ID", ""
    )
    decimals = int(
        api_server._active_cat.get("decimals") or getattr(cfg, "CAT_DECIMALS", 3)
    )

    result = {
        "best_bid": 0,
        "best_ask": 0,
        "dexie_price": 0,
        "tibet_price": None,
        "mid_price": 0,
        "volume_24h": 0,
        "pool_xch": 0,
        "pool_cat": 0,
        "dexie_depth_xch": 0,
        "arb_gap_bps": 0,
        "tibet_available": False,
        "tibet_reason": "TIBETSWAP_SHUTDOWN",
        "tibet_status": "retired",
        "tibet_status_code": None,
        "has_data": False,
    }

    if not asset_id:
        return jsonify(result)

    dexie_base = getattr(cfg, "DEXIE_API_BASE", "https://api.dexie.space")

    # --- Dexie ticker (24h volume + last price + native bid/ask) ---
    try:
        if ticker_id:
            tid = ticker_id if "_" in ticker_id else f"{ticker_id}_XCH"
            _record_api_call("dexie", "/v2/prices/tickers")
            resp = _req.get(
                f"{dexie_base}/v2/prices/tickers", params={"ticker_id": tid}, timeout=8
            )
            if resp.status_code == 200:
                tickers = resp.json().get("tickers", [])
                if tickers:
                    t = tickers[0]
                    result["dexie_price"] = float(t.get("current_avg_price", 0) or 0)
                    result["volume_24h"] = float(t.get("target_volume", 0) or 0)
                    _ticker_bid = float(t.get("bid", 0) or 0)
                    _ticker_ask = float(t.get("ask", 0) or 0)
                    if _ticker_bid > 0:
                        result["best_bid"] = _ticker_bid
                    if _ticker_ask > 0:
                        result["best_ask"] = _ticker_ask
    except Exception:
        pass

    def _extract_xch_per_cat(offer, cat_id):
        """Extract XCH/CAT price from a Dexie v1 offer's amounts."""
        xch_amt = 0.0
        cat_amt = 0.0
        for asset in offer.get("offered", []) + offer.get("requested", []):
            code = str(asset.get("code", "")).upper()
            aid = str(asset.get("id", "")).lower().replace("0x", "")
            amt = float(asset.get("amount", 0) or 0)
            if code == "XCH" or aid == "" or aid == "xch":
                xch_amt = amt
            elif aid == cat_id.lower().replace("0x", ""):
                cat_amt = amt
        if xch_amt > 0 and cat_amt > 0:
            return xch_amt / cat_amt
        return 0.0

    try:
        _record_api_call("dexie", "/v1/offers")
        resp = _req.get(
            f"{dexie_base}/v1/offers",
            params={
                "offered": asset_id,
                "requested": "xch",
                "status": 0,
                "page_size": 3,
                "sort": "price_asc",
            },
            timeout=8,
        )
        if resp.status_code == 200:
            for offer in resp.json().get("offers", []):
                p = _extract_xch_per_cat(offer, asset_id)
                if p > 0:
                    result["best_ask"] = p
                    break

        _record_api_call("dexie", "/v1/offers")
        resp = _req.get(
            f"{dexie_base}/v1/offers",
            params={
                "offered": "xch",
                "requested": asset_id,
                "status": 0,
                "page_size": 3,
                "sort": "price_asc",
            },
            timeout=8,
        )
        if resp.status_code == 200:
            for offer in resp.json().get("offers", []):
                p = _extract_xch_per_cat(offer, asset_id)
                if p > 0:
                    result["best_bid"] = p
                    break
    except Exception:
        pass

    try:
        dexie_total_xch = 0.0
        _record_api_call("dexie", "/v1/offers")
        resp = _req.get(
            f"{dexie_base}/v1/offers",
            params={
                "offered": asset_id,
                "requested": "xch",
                "status": 0,
                "page_size": 50,
            },
            timeout=8,
        )
        if resp.status_code == 200:
            for offer in resp.json().get("offers", []):
                for asset in offer.get("requested", []):
                    if str(asset.get("code", "")).upper() == "XCH":
                        dexie_total_xch += float(asset.get("amount", 0) or 0)

        _record_api_call("dexie", "/v1/offers")
        resp = _req.get(
            f"{dexie_base}/v1/offers",
            params={
                "offered": "xch",
                "requested": asset_id,
                "status": 0,
                "page_size": 50,
            },
            timeout=8,
        )
        if resp.status_code == 200:
            for offer in resp.json().get("offers", []):
                for asset in offer.get("offered", []):
                    if str(asset.get("code", "")).upper() == "XCH":
                        dexie_total_xch += float(asset.get("amount", 0) or 0)

        result["dexie_depth_xch"] = round(dexie_total_xch, 2)
    except Exception:
        pass

    bb = result["best_bid"]
    ba = result["best_ask"]
    dexie_live_mid = (bb + ba) / 2 if bb > 0 and ba > 0 else result["dexie_price"]
    dp = result["dexie_price"]
    if dexie_live_mid > 0:
        result["mid_price"] = dexie_live_mid
    elif dp > 0:
        result["mid_price"] = dp

    result["has_data"] = result["mid_price"] > 0
    return jsonify(result)


@bp.route("/api/price/tibet")
def api_tibet_price():
    """One-release compatibility endpoint for retired TibetSwap pricing."""

    return jsonify(
        {
            "available": False,
            "provider": "tibetswap",
            "status": "retired",
            "reason": "TIBETSWAP_SHUTDOWN",
        }
    )


@bp.route("/api/amm/price")
def api_amm_price():
    """One-release compatibility endpoint for retired AMM telemetry."""

    return jsonify(
        {
            "available": False,
            "provider": "tibetswap",
            "status": "retired",
            "reason": "TIBETSWAP_SHUTDOWN",
        }
    )


@bp.route("/api/debug/coinprep")
def api_debug_coinprep():
    """Debug: shows coin prep worker status and any error output."""
    bot = api_server.bot
    result = {"_coin_prep_state": api_server._coin_prep_state}

    try:
        from user_paths import coin_prep_status_file, coin_prep_output_log_file

        status_file = coin_prep_status_file()
        log_file = coin_prep_output_log_file()
    except Exception:
        base_dir = os.path.dirname(os.path.abspath(api_server.__file__))
        status_file = os.path.join(base_dir, "coin_prep_status.json")
        log_file = os.path.join(base_dir, "coin_prep_output.log")

    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                result["worker_status_file"] = json.load(f)
        except Exception as e:
            result["worker_status_file_error"] = str(e)
    else:
        result["worker_status_file"] = "NOT FOUND"

    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                log_content = f.read()
            result["worker_output_log"] = log_content[-2000:]
        except Exception as e:
            result["worker_output_log_error"] = str(e)
    else:
        result["worker_output_log"] = "NOT FOUND"

    if bot:
        try:
            result["coin_manager_status"] = bot.coin_manager.check_coin_prep_status()
        except Exception as e:
            result["coin_manager_error"] = str(e)

    try:
        from database import get_recent_events

        events = get_recent_events(limit=20)
        prep_events = [e for e in events if "coin_prep" in str(e.get("event_type", ""))]
        result["recent_coin_prep_events"] = prep_events[:10]
    except Exception:
        pass

    return jsonify(result)


@bp.route("/api/debug/pricing")
def api_debug_pricing():
    """Debug: shows exactly what pricing the GUI sees."""
    import requests as _req

    bot = api_server.bot
    result = {
        "_active_cat": {
            k: str(v)[:50] if v else None for k, v in api_server._active_cat.items()
        }
    }
    result["bot_exists"] = bot is not None

    asset_id = api_server._active_cat.get("asset_id") or ""
    ticker_id = api_server._active_cat.get("ticker_id") or ""
    result["asset_id"] = asset_id
    result["ticker_id"] = ticker_id

    try:
        resp = _req.get("http://127.0.0.1:5000/api/status", timeout=15)
        status_data = resp.json()
        result["status_pricing"] = status_data.get("pricing", "MISSING")
        result["status_current_cat"] = status_data.get("current_cat", "MISSING")
    except Exception as e:
        result["status_error"] = str(e)

    try:
        resp = _req.get("http://127.0.0.1:5000/api/price", timeout=15)
        result["price_response"] = resp.json()
    except Exception as e:
        result["price_error"] = str(e)

    result["tibet"] = {
        "provider": "tibetswap",
        "status": "retired",
        "available": False,
        "reason": "TIBETSWAP_SHUTDOWN",
    }

    return jsonify(result)


@bp.route("/api/debug/tibet-test")
def api_debug_tibet_test():
    """One-release compatibility diagnostic for the retired provider."""

    return jsonify(
        {
            "provider": "tibetswap",
            "status": "retired",
            "available": False,
            "reason": "TIBETSWAP_SHUTDOWN",
        }
    )


@bp.route("/api/debug/sage-single-offer-test", methods=["POST"])
def api_debug_sage_single_offer_test():
    """Create one selected-coin XCH offer and one CAT offer, inspect, cancel."""
    cfg = api_server.cfg
    try:
        from wallet import (
            get_wallet_type,
            create_offer,
            cancel_offer,
            get_owned_coins_detailed,
        )

        if get_wallet_type() != "sage":
            return jsonify({"ok": False, "error": "sage_only_debug_route"}), 400

        from database import get_smallest_free_tier_spare

        def _extract_trade_id(result: dict) -> str:
            if not isinstance(result, dict):
                return ""
            trade_id = result.get("trade_id") or result.get("offer_id") or ""
            if not trade_id:
                tr = result.get("trade_record") or {}
                if isinstance(tr, dict):
                    trade_id = tr.get("trade_id") or tr.get("offer_id") or ""
            if not trade_id:
                offer_obj = result.get("offer") or {}
                if isinstance(offer_obj, dict):
                    trade_id = offer_obj.get("id") or offer_obj.get("offer_id") or ""
            return str(trade_id or "")

        def _run_case(
            name: str, wallet_id: int, offer_dict: dict, selected_coin_id: str
        ):
            result = {
                "name": name,
                "selected_coin_id": selected_coin_id,
                "offer_dict": offer_dict,
            }
            create_res = create_offer(
                offer_dict,
                validate_only=False,
                max_time=int(time.time()) + 300,
                coin_ids=[selected_coin_id],
            )
            result["create_result"] = create_res

            trade_id = _extract_trade_id(create_res or {})
            result["trade_id"] = trade_id
            if not trade_id:
                return result

            time.sleep(2)
            owned = get_owned_coins_detailed(wallet_id) or {}
            locked_inputs = []
            for coin_id, info in owned.items():
                offer_id = str(info.get("offer_id") or "").lower()
                if offer_id == trade_id.lower():
                    locked_inputs.append(
                        {
                            "coin_id": coin_id,
                            "amount": int(info.get("amount") or 0),
                        }
                    )
            result["locked_inputs"] = locked_inputs

            cancel_res = cancel_offer(trade_id, secure=False, timeout=30)
            result["cancel_result"] = cancel_res
            return result

        xch_coin = get_smallest_free_tier_spare("xch")
        cat_coin = get_smallest_free_tier_spare("cat")
        if not xch_coin or not cat_coin:
            return jsonify(
                {
                    "ok": False,
                    "error": "no_free_spare_coin",
                    "xch_coin": xch_coin,
                    "cat_coin": cat_coin,
                }
            ), 409

        xch_case = _run_case(
            name="xch_selected_manual",
            wallet_id=int(cfg.WALLET_ID_XCH),
            offer_dict={
                str(int(cfg.WALLET_ID_XCH)): -1_000_000_000,
                str(int(cfg.CAT_WALLET_ID)): 8_000,
            },
            selected_coin_id=xch_coin["coin_id"],
        )

        time.sleep(2)

        cat_case = _run_case(
            name="cat_selected_manual",
            wallet_id=int(cfg.CAT_WALLET_ID),
            offer_dict={
                str(int(cfg.CAT_WALLET_ID)): -8_000,
                str(int(cfg.WALLET_ID_XCH)): 1_000_000_000,
            },
            selected_coin_id=cat_coin["coin_id"],
        )

        payload = {
            "ok": True,
            "xch_coin": xch_coin,
            "cat_coin": cat_coin,
            "results": [xch_case, cat_case],
        }
        log_event(
            "info", "sage_single_offer_test", json.dumps(payload, default=str)[:1500]
        )
        return jsonify(payload)
    except Exception:
        return api_server._api_exception(request.path)
