"""Offer-book price discovery for Chia CAT trading pairs.

The `PriceEngine` class is the central price oracle for the bot. It derives
quotes from trusted offer-book evidence, applies dynamic safety rails, and
tracks realized volatility. TibetSwap network access was retired in v1.4;
the remaining Tibet-named methods and cache are inert compatibility surfaces
for one upgrade cycle and must never provide live pricing.

Key responsibilities:
    - Fetch and cache trusted offer-book data
    - Derive a single mid-price with source and confidence metadata
    - Maintain an EMA reference and volatility signal for risk logic
    - Keep historical TibetSwap compatibility methods network-free and inert
"""

import time
import requests
import threading
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Tuple, List

from config import cfg
from database import record_price, get_recent_prices, log_event


# ---------------------------------------------------------------------------
# Retired TibetSwap cache retained only for one-release import compatibility.
# ---------------------------------------------------------------------------
_tibet_cache = {
    "pairs": [],
    "fetched_at": 0,
    "cache_ttl": 120,
}
_tibet_lock = threading.Lock()
_tibet_warning_state = {
    "last_warn": 0.0,
    "signature": "",
    "repeats": 0,
}
_tibet_warning_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Price Engine
# ---------------------------------------------------------------------------
class PriceEngine:
    """Fetches and combines prices from Dexie and TibetSwap.

    Supports multiple pricing strategies:
    - dexie_only: Use Dexie mid price only
    - tibet_only: Use TibetSwap pool price only
    - average: Simple average of both
    - weighted: Configurable weight between the two

    Also tracks price history for volatility calculation (used by risk_manager).
    """

    def __init__(self):
        self._last_mid_price: Optional[Decimal] = None
        self._last_dexie_price: Optional[Decimal] = None
        self._last_tibet_price: Optional[Decimal] = None
        self._last_price_time: float = 0
        self._last_tibet_price_time: float = (
            0  # Timestamp of last successful Tibet fetch
        )
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

        # API call counters (session-scoped, reset on restart)
        self._dexie_price_fetches: int = 0
        self._tibet_price_fetches: int = 0

        # --- Dynamic price limits ---
        # Reference price: set from first successful fetch, then tracks market
        # via exponential moving average (slow — 1% weight per update).
        # Dynamic limits = reference_price × (1 ± DYNAMIC_LIMIT_PCT).
        # .env HARD_MIN/HARD_MAX become the absolute backstop (set wide or 0).
        self._reference_price: Optional[Decimal] = None
        self._reference_price_time: float = 0
        self._ema_alpha = Decimal("0.01")  # 1% weight per update = slow drift

        # --- Rail-breach tracking (for bot_loop to route to the CB safeguard) ---
        # When _apply_safety_guards rejects a price, it records the direction
        # and rejected value here so bot_loop can trip the risk_manager CB
        # and cancel stale offers, rather than silently returning.
        #   direction: "below" | "above" | "step" | None (no breach)
        #   price:     the rejected mid price (for logging / alerting)
        #   kind:      "dyn_min" | "dyn_max" | "hard_min" | "hard_max" | "step" | None
        self._last_rail_breach: Optional[str] = None
        self._last_rail_breach_price: Optional[Decimal] = None
        self._last_rail_breach_kind: Optional[str] = None

        # Thread safety — multiple threads read price state; main loop writes it
        self._price_lock = threading.Lock()

        # --- Warning rate-limiters (suppress spammy Dexie warnings) ---
        self._last_crossed_warn: float = 0
        self._last_empty_warn: float = 0
        self._warn_cooldown_secs: int = 120  # max once per 2 min
        # Stuck-data detection: when Dexie's ticker returns the SAME broken
        # bid/ask (or the SAME stale fallback field) repeatedly, the data is
        # frozen on Dexie's side, not transiently flickering. Drop the noise
        # to once per hour after the same value has fired the warning twice.
        self._stuck_cooldown_secs: int = 3600
        self._last_crossed_signature: str = ""
        self._crossed_repeats: int = 0
        self._last_empty_signature: str = ""
        self._empty_repeats: int = 0

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def get_price(
        self, cat_asset_id: str = None, cat_decimals: int = None, ticker_id: str = None
    ) -> Optional[Dict]:
        """Get the current mid price using the configured strategy.

        Args:
            cat_asset_id: CAT asset ID (for TibetSwap lookup)
            cat_decimals: CAT decimal places (for TibetSwap calculation)
            ticker_id: Dexie ticker ID (e.g., "XCH_MZ")

        Returns dict with:
            mid_price: The final combined price (Decimal)
            dexie_price: Dexie price (Decimal or None)
            tibet_price: TibetSwap price (Decimal or None)
            strategy_used: Which strategy was applied
            arb_opportunity: Arb direction or None
            arb_gap_bps: Price difference in basis points
            tibet_available: Whether Tibet data was available
        """
        asset_id = cat_asset_id or cfg.CAT_ASSET_ID
        ticker = ticker_id or cfg.CAT_TICKER_ID

        # v1.4: TibetSwap shut down permanently.  Historical compatibility
        # fields remain for one release, but no live path may query or derive a
        # trading price from the retired AMM.
        dexie_price = self._fetch_dexie_price(ticker)
        tibet_price = None
        mid_price = dexie_price
        strategy_used = "dexie_offer_book"

        if mid_price is None:
            log_event("warning", "price_error", "No price available from any source")
            return None

        # Log strategy on first call and whenever it changes.
        _prev_strategy = getattr(self, "_last_strategy_used", None)
        if _prev_strategy != strategy_used:
            if _prev_strategy is None:
                log_event(
                    "info",
                    "price_strategy",
                    f"Pricing strategy: {strategy_used} — Dexie={dexie_price}, "
                    f"Mid={mid_price:.8f}; TibetSwap is retired",
                )
            else:
                log_event(
                    "info",
                    "price_strategy",
                    f"Pricing strategy changed: {_prev_strategy} → {strategy_used} — "
                    f"Dexie={dexie_price}, Mid={mid_price:.8f}",
                )
            self._last_strategy_used = strategy_used

        # Apply safety guards
        mid_price = self._apply_safety_guards(mid_price)
        if mid_price is None:
            return None

        # Cross-venue AMM arbitrage was retired with TibetSwap.
        arb_direction = None
        arb_gap_bps = Decimal("0")

        # Update state
        with self._price_lock:
            self._last_mid_price = mid_price
            self._last_dexie_price = dexie_price
            self._last_tibet_price = tibet_price
            if tibet_price is not None and tibet_price > 0:
                self._last_tibet_price_time = time.time()
            self._last_price_time = time.time()

        # Update dynamic reference price (EMA tracks market slowly)
        self._update_reference_price(mid_price)

        # Record to database for volatility tracking
        record_price(
            cat_asset_id=asset_id,
            combined_price=mid_price,
            dexie_price=dexie_price,
            tibet_price=tibet_price,
            strategy_used=strategy_used,
        )

        result = {
            "mid_price": mid_price,
            "dexie_price": dexie_price,
            "tibet_price": tibet_price,
            "strategy_used": strategy_used,
            "arb_opportunity": arb_direction,
            "arb_gap_bps": arb_gap_bps,
            "tibet_available": False,
            "tibet_status": "retired",
        }
        # Cache for read-only access by GUI polling (avoids DB write contention)
        self._last_price_result = result
        return result

    def get_last_price(self, max_age_secs: float = 300) -> Optional[Decimal]:
        """Return last known price, or None if older than max_age_secs.

        Pass max_age_secs=0 to get the raw value regardless of age.
        """
        with self._price_lock:
            if self._last_mid_price is None:
                return None
            if max_age_secs > 0:
                age = time.time() - self._last_price_time
                if age > max_age_secs:
                    return None
            return self._last_mid_price

    def get_volatility(self, cat_asset_id: str = None, hours: float = None) -> Decimal:
        """Calculate price volatility over recent history.

        Returns volatility as a fraction (e.g., 0.05 = 5% volatility).
        Used by risk_manager to adjust spreads dynamically.

        Resilient to underlying SQLite errors (corruption, lock contention,
        etc.): swallows the exception, returns Decimal("0") so the caller
        sees the same value as a genuinely-empty price window, and rate-
        limits the WARN log to once per minute. Without this rate-limit the
        risk manager's per-cycle volatility query produced ~35 ERROR lines
        per minute when the events/price_history indexes were corrupt.
        """
        asset_id = cat_asset_id or cfg.CAT_ASSET_ID
        window = hours or float(cfg.VOLATILITY_WINDOW_HOURS)

        try:
            prices = get_recent_prices(asset_id, hours=window)
        except Exception as e:
            now = time.time()
            last = getattr(self, "_volatility_query_warn_at", 0.0)
            if (now - last) >= 60.0:
                # Snapshot the warn window so this log fires at most once
                # per minute even if get_volatility is called every cycle.
                self._volatility_query_warn_at = now
                log_event(
                    "warning",
                    "volatility_query_failed",
                    f"price_history query for volatility failed: {e}. "
                    f"Returning 0 (dynamic spread will skip the volatility "
                    f"adjustment until the DB recovers). This warning is "
                    f"rate-limited to once per minute.",
                )
            return Decimal("0")
        if len(prices) < 2:
            return Decimal("0")

        # Extract price values
        values = []
        for p in prices:
            try:
                values.append(Decimal(p["combined_price"]))
            except (InvalidOperation, KeyError):
                continue

        if len(values) < 2:
            return Decimal("0")

        # Calculate standard deviation / mean (coefficient of variation)
        mean = sum(values) / len(values)
        if mean == 0:
            return Decimal("0")

        variance = sum((v - mean) ** 2 for v in values) / len(values)
        # Use Newton's method for square root (Decimal doesn't have sqrt)
        std_dev = _decimal_sqrt(variance)

        volatility = std_dev / mean
        return volatility

    def get_tibet_pool_info(self, cat_asset_id: str = None) -> Optional[Dict]:
        """Return the one-release compatibility marker for retired TibetSwap."""
        return {
            "available": False,
            "status": "retired",
            "reason": "TIBETSWAP_SHUTDOWN",
            "price": None,
            "xch_reserve": None,
            "token_reserve": None,
        }

    # -------------------------------------------------------------------
    # Dexie price fetching
    # -------------------------------------------------------------------

    def _fetch_dexie_price(self, ticker_id: str) -> Optional[Decimal]:
        """Fetch mid price from Dexie API.

        Uses live bid/ask midpoint only. Historical ticker fields are not a
        safe trading reference on thin CAT markets.
        """
        if not ticker_id:
            return None
        # Dexie ticker format is "{CAT}_XCH" e.g. "SBX_XCH" (V1 confirmed)
        # Auto-fix bare ticker names missing the _XCH suffix
        if "_" not in ticker_id:
            ticker_id = f"{ticker_id}_XCH"

        try:
            self._dexie_price_fetches += 1
            url = f"{cfg.DEXIE_API_BASE}/v2/prices/tickers"
            resp = self._session.get(url, params={"ticker_id": ticker_id}, timeout=10)
            if resp.status_code == 429:
                log_event(
                    "warning",
                    "dexie_rate_limited",
                    "Dexie price API returned 429 — skipping this cycle",
                )
                return None
            resp.raise_for_status()
            data = resp.json()

            tickers = data.get("tickers", [])
            if not tickers:
                return None

            ticker = tickers[0]

            # Verify the returned ticker matches our requested pair
            returned_tid = str(ticker.get("ticker_id", "")).lower().strip()
            expected_tid = str(ticker_id).lower().strip()
            if returned_tid and expected_tid and returned_tid != expected_tid:
                log_event(
                    "warning",
                    "dexie_ticker_mismatch",
                    f"Dexie returned ticker '{returned_tid}' but we asked "
                    f"for '{expected_tid}' — rejecting",
                )
                return None

            # Prefer bid/ask midpoint (real market price) over last_price
            # which can be an outlier trade far from the current market.
            # Guard: bid > ask is a crossed/corrupted market — never use it.
            # Also guard: bid > ask * 10 catches stale/garbage bids on thin books.
            bid_val = ticker.get("bid") or ticker.get("best_bid") or 0
            ask_val = ticker.get("ask") or ticker.get("best_ask") or 0
            # Track whether we've already logged a "ticker unusable" reason
            # this call so the fallback path below doesn't fire a duplicate
            # warning for the same root cause. The crossed branch handles
            # one specific cause (bid>ask) and the bid/ask-empty case below
            # handles another (no bid/ask at all); only one warning per call.
            _logged_ticker_problem = False
            try:
                bid_d = Decimal(str(bid_val)) if bid_val else Decimal("0")
                ask_d = Decimal(str(ask_val)) if ask_val else Decimal("0")
                if bid_d > 0 and ask_d > 0 and bid_d <= ask_d:
                    return (bid_d + ask_d) / 2
                elif bid_d > ask_d and ask_d > 0:
                    _now = time.time()
                    sig = f"{bid_d}/{ask_d}"
                    if sig == self._last_crossed_signature:
                        self._crossed_repeats += 1
                    else:
                        self._last_crossed_signature = sig
                        self._crossed_repeats = 1
                    cooldown = (
                        self._stuck_cooldown_secs
                        if self._crossed_repeats >= 2
                        else self._warn_cooldown_secs
                    )
                    if _now - self._last_crossed_warn >= cooldown:
                        suffix = (
                            f"appears stuck on these values; "
                            f"suppressed for {int(cooldown // 60)}m"
                            if self._crossed_repeats >= 2
                            else f"suppressed for {self._warn_cooldown_secs}s"
                        )
                        log_event(
                            "info",
                            "dexie_crossed_market",
                            f"Dexie ticker returned crossed bid/ask "
                            f"(bid={bid_d}, ask={ask_d}) — rejecting "
                            f"Dexie ticker for this cycle ({suffix})",
                        )
                        self._last_crossed_warn = _now
                    _logged_ticker_problem = True
            except InvalidOperation:
                pass

            # Historical Dexie fields are diagnostic only here. They can lag
            # the live book on thin CAT markets, so they must not become the
            # bot's trading reference.

            if not _logged_ticker_problem:
                _now = time.time()
                signature_fields = []
                for field in ("current_avg_price", "price_24h", "last_price", "price"):
                    val = ticker.get(field)
                    if val and str(val) != "0":
                        signature_fields.append(f"{field}={val}")
                sig = "|".join(signature_fields) or "no-historical-fields"
                if sig == self._last_empty_signature:
                    self._empty_repeats += 1
                else:
                    self._last_empty_signature = sig
                    self._empty_repeats = 1
                cooldown = (
                    self._stuck_cooldown_secs
                    if self._empty_repeats >= 2
                    else self._warn_cooldown_secs
                )
                if _now - self._last_empty_warn >= cooldown:
                    suffix = (
                        f"appears stuck; suppressed for {int(cooldown // 60)}m"
                        if self._empty_repeats >= 2
                        else f"suppressed for {self._warn_cooldown_secs}s"
                    )
                    log_event(
                        "info",
                        "dexie_ticker_unusable",
                        f"Dexie ticker bid/ask unavailable "
                        f"(thin/illiquid pair). Rejecting historical "
                        f"ticker fields for trading. ({suffix})",
                    )
                    self._last_empty_warn = _now

            return None

        except requests.RequestException as e:
            log_event("warning", "dexie_error", f"Dexie price fetch failed: {e}")
            return None
        except (ValueError, KeyError, TypeError) as e:
            # Catches JSONDecodeError (subclass of ValueError), missing keys,
            # or unexpected response shapes from schema changes.
            log_event(
                "warning",
                "dexie_parse_error",
                f"Dexie returned unparseable response: {e}",
            )
            return None

    # -------------------------------------------------------------------
    # TibetSwap price fetching
    # -------------------------------------------------------------------

    def _log_tibet_warning(self, event: str, message: str) -> None:
        """Rate-limit repeated warnings from one sustained Tibet outage."""
        now = time.time()
        signature = "tibet_fetch_unavailable"
        with _tibet_warning_lock:
            if signature == _tibet_warning_state["signature"]:
                _tibet_warning_state["repeats"] += 1
            else:
                _tibet_warning_state["signature"] = signature
                _tibet_warning_state["repeats"] = 1
            cooldown = (
                self._stuck_cooldown_secs
                if _tibet_warning_state["repeats"] >= 2
                else self._warn_cooldown_secs
            )
            if now - _tibet_warning_state["last_warn"] < cooldown:
                return
            _tibet_warning_state["last_warn"] = now

        log_event("warning", event, message)

    def _fetch_tibet_price(self, asset_id: str, decimals: int = 3) -> Optional[Decimal]:
        """Compatibility stub: TibetSwap is retired and never queried."""
        return None

    def _find_tibet_pair(self, asset_id: str) -> Optional[Dict]:
        """Compatibility stub: retired TibetSwap pairs are never resolved."""
        return None

    def _get_tibet_pairs(self) -> List[Dict]:
        """Compatibility stub: the retired provider can never perform I/O."""
        return []

    def invalidate_tibet_cache(self):
        """Compatibility no-op for callers retained during the v1.4 migration."""
        return None

    def inject_tibet_reserves(
        self,
        pair_id: str = None,
        asset_id: str = None,
        xch_reserve=None,
        token_reserve=None,
        fetched_at: float = None,
    ) -> bool:
        """Compatibility no-op; retired reserve evidence is never accepted."""
        _ = fetched_at  # Retained for one-release keyword compatibility.
        return False

    def get_live_amm_price(self) -> Optional[Decimal]:
        """Compatibility stub: no Chia AMM price source is active."""

        return None

    # -------------------------------------------------------------------
    # TibetSwap Quote-Based Slippage Estimation (NEW — ecosystem upgrade)
    # -------------------------------------------------------------------

    def get_tibet_quote(
        self,
        asset_id: str = None,
        amount_xch: Decimal = Decimal("0.01"),
        side: str = "buy",
    ) -> Optional[Dict]:
        """Return an explicit retired marker without contacting a network.

        TibetSwap's /quote endpoint simulates a swap and returns the
        price_impact field — this tells us how much slippage our trade
        size would cause on the AMM.

        This is valuable intelligence:
        - Large slippage = thin pool, widen spreads to protect
        - Small slippage = deep pool, can trade larger sizes safely
        - Compares our offer size against actual pool depth

        Args:
            asset_id: CAT asset ID
            amount_xch: Amount of XCH to simulate swapping
            side: "buy" (XCH -> CAT) or "sell" (CAT -> XCH)

        Returns dict with:
            input_amount, output_amount, price_impact, effective_price,
            pool_depth_xch, slippage_bps
        """
        return {
            "available": False,
            "provider": "tibetswap",
            "status": "retired",
            "reason": "TIBETSWAP_SHUTDOWN",
        }

    def _parse_tibet_quote(
        self, data: Dict, amount_xch: Decimal, side: str, pair: Dict
    ) -> Optional[Dict]:
        """Parse a TibetSwap quote response."""
        try:
            price_impact = Decimal(str(data.get("price_impact", "0")))
            amount_out = Decimal(str(data.get("amount_out", "0")))

            xch_reserve = Decimal(str(pair.get("xch_reserve", 0))) / Decimal("1e12")

            # Calculate effective price
            decimals = cfg.CAT_DECIMALS
            if side == "buy" and amount_out > 0:
                cat_amount = amount_out / (Decimal(10) ** Decimal(decimals))
                effective_price = (
                    amount_xch / cat_amount if cat_amount > 0 else Decimal("0")
                )
            else:
                effective_price = Decimal("0")

            # Convert price impact to BPS
            slippage_bps = abs(price_impact) * Decimal("10000")

            return {
                "input_amount": str(amount_xch),
                "output_amount": str(amount_out),
                "price_impact": str(price_impact),
                "effective_price": str(effective_price),
                "pool_depth_xch": str(xch_reserve),
                "slippage_bps": str(slippage_bps),
                "source": "tibet_quote",
            }

        except (InvalidOperation, ZeroDivisionError):
            return None

    def _estimate_slippage_from_reserves(
        self, pair: Dict, amount_xch: Decimal, side: str
    ) -> Optional[Dict]:
        """Estimate slippage using the constant product formula (x * y = k).

        This is a mathematical estimation when the /quote endpoint isn't available.

        For a buy (XCH -> CAT):
            new_xch = xch_reserve + amount_in
            new_cat = k / new_xch
            cat_out = cat_reserve - new_cat
            slippage = 1 - (cat_out / cat_reserve) / (amount_in / xch_reserve)

        For a sell (CAT -> XCH):
            Similar calculation in reverse.
        """
        try:
            xch_reserve = Decimal(str(pair.get("xch_reserve", 0))) / Decimal("1e12")
            token_reserve = Decimal(str(pair.get("token_reserve", 0)))
            decimals = cfg.CAT_DECIMALS
            cat_scale = Decimal(10) ** Decimal(decimals)
            token_reserve_actual = token_reserve / cat_scale

            if xch_reserve <= 0 or token_reserve_actual <= 0:
                return None

            # Constant product
            k = xch_reserve * token_reserve_actual

            if side == "buy":
                # Adding XCH, getting CAT
                # Account for TibetSwap 0.7% fee
                amount_after_fee = amount_xch * Decimal("0.993")
                new_xch = xch_reserve + amount_after_fee
                new_cat = k / new_xch
                cat_out = token_reserve_actual - new_cat

                if cat_out <= 0:
                    return None

                # Spot price vs effective price
                spot_price = xch_reserve / token_reserve_actual
                effective_price = amount_xch / cat_out
                slippage = (
                    (effective_price - spot_price) / spot_price
                    if spot_price > 0
                    else Decimal("0")
                )

            else:
                # Selling CAT for XCH
                # Estimate CAT amount from XCH equivalent
                spot_price = xch_reserve / token_reserve_actual
                cat_amount = amount_xch / spot_price if spot_price > 0 else Decimal("0")

                if cat_amount <= 0:
                    return None

                amount_after_fee = cat_amount * Decimal("0.993")
                new_cat = token_reserve_actual + amount_after_fee
                new_xch = k / new_cat
                xch_out = xch_reserve - new_xch

                effective_price = (
                    xch_out / cat_amount if cat_amount > 0 else Decimal("0")
                )
                slippage = (
                    (spot_price - effective_price) / spot_price
                    if spot_price > 0
                    else Decimal("0")
                )

            slippage_bps = abs(slippage) * Decimal("10000")

            return {
                "input_amount": str(amount_xch),
                "output_amount": str(cat_out if side == "buy" else xch_out),
                "price_impact": str(slippage),
                "effective_price": str(effective_price),
                "pool_depth_xch": str(xch_reserve),
                "slippage_bps": str(slippage_bps),
                "source": "reserves_estimate",
            }

        except (InvalidOperation, ZeroDivisionError):
            return None

    def get_pool_depth_ratio(self, trade_size_xch: Decimal = None) -> Decimal:
        """Compatibility stub; AMM depth cannot authorize a live decision."""

        return Decimal("0")

    # -------------------------------------------------------------------
    # Safety guards
    # -------------------------------------------------------------------

    def _update_reference_price(self, price: Decimal):
        """Update the dynamic reference price using exponential moving average.

        First successful price sets the reference.  After that, each update
        nudges the reference by EMA_ALPHA (1%) toward the new price — so the
        reference drifts slowly with the market but won't jump on a single
        outlier.  This means genuine trends are absorbed over time and the
        dynamic limits naturally follow.
        """
        if self._reference_price is None:
            # First price — use it directly as the baseline
            self._reference_price = price
            self._reference_price_time = time.time()
            dyn_min, dyn_max = self.get_dynamic_limits()
            if dyn_min and dyn_max:
                log_event(
                    "info",
                    "dynamic_limits_init",
                    f"Dynamic price limits initialised: "
                    f"{dyn_min:.10f} — {dyn_max:.10f} "
                    f"(ref: {price:.10f}, band: ±{cfg.DYNAMIC_LIMIT_PCT}%)",
                )
        else:
            # EMA update: ref = ref × (1 - α) + price × α
            # Fast catch-up: if price has moved more than half the dynamic
            # band away from the reference, apply 5× faster alpha so the
            # reference re-centres in ~15 loops instead of ~70.  This stops
            # a legitimate sustained trend from sitting outside the dynamic
            # limits for too long after a large price move.
            alpha = self._ema_alpha
            dyn_pct = getattr(cfg, "DYNAMIC_LIMIT_PCT", Decimal("0"))
            if self._reference_price > Decimal("0") and dyn_pct > Decimal("0"):
                deviation = abs(price - self._reference_price) / self._reference_price
                half_band = dyn_pct / Decimal("200")  # half of the ±band as a fraction
                if deviation > half_band * Decimal("0.5"):
                    alpha = min(self._ema_alpha * Decimal("5"), Decimal("0.10"))
            self._reference_price = (
                self._reference_price * (Decimal("1") - alpha) + price * alpha
            )
            self._reference_price_time = time.time()

    def get_dynamic_limits(self) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """Calculate the current dynamic min/max price limits.

        Returns (dynamic_min, dynamic_max) based on the reference price
        and DYNAMIC_LIMIT_PCT.  Returns (None, None) if no reference yet
        or dynamic limits are disabled (DYNAMIC_LIMIT_PCT = 0).
        """
        pct = cfg.DYNAMIC_LIMIT_PCT
        if pct <= 0 or self._reference_price is None:
            return None, None

        band = self._reference_price * pct / Decimal("100")
        dyn_min = self._reference_price - band
        dyn_max = self._reference_price + band
        return dyn_min, dyn_max

    def get_reference_price(self) -> Optional[Decimal]:
        """Return the current reference price (for GUI display)."""
        return self._reference_price

    def _apply_safety_guards(self, price: Decimal) -> Optional[Decimal]:
        """Apply dynamic + hard min/max bounds and step-change detection.

        Guard priority:
          1. Dynamic limits (reference ± DYNAMIC_LIMIT_PCT%) — catches runaway prices
             while automatically following the market over time.
          2. Hard limits (.env HARD_MIN/HARD_MAX) — absolute backstop for catastrophic
             moves. Set these wide (e.g. ±200%) or to 0 to disable.
          3. Step-change guard — rejects sudden single-fetch jumps.

        Returns None if price fails any check.
        Warnings throttled to once per 60 seconds per guard type.

        Side effect on rejection: stores breach direction/kind/price on
        self._last_rail_breach* so bot_loop can route the rail breach
        into the risk_manager CB path and cancel stale offers.
        """
        now = time.time()

        # Start each call with a clean breach state. A successful fetch
        # clears any previous rejection so we only latch the most recent
        # attempt's outcome.
        self._last_rail_breach = None
        self._last_rail_breach_price = None
        self._last_rail_breach_kind = None

        # --- Dynamic limits (primary protection) ---
        dyn_min, dyn_max = self.get_dynamic_limits()
        if dyn_min is not None and price < dyn_min:
            if now - getattr(self, "_last_dynmin_warn", 0) >= 60:
                log_event(
                    "warning",
                    "price_guard",
                    f"Price {price:.10f} below dynamic minimum {dyn_min:.10f} "
                    f"(ref: {self._reference_price:.10f}, band: ±{cfg.DYNAMIC_LIMIT_PCT}%)",
                )
                self._last_dynmin_warn = now
            # Nudge reference EMA very slowly toward the band edge (NOT the
            # rejected price) so a genuine sustained large move can eventually
            # unlock quoting.  Clamping to the band edge prevents an attacker
            # from dragging the reference arbitrarily far via persistent extreme
            # prices — the reference can only drift toward dyn_min, never past it.
            slow_alpha = getattr(cfg, "PRICE_LIMIT_NUDGE_ALPHA", Decimal("0.02"))
            nudge_target = dyn_min  # clamp to band edge
            self._reference_price = (
                Decimal("1") - slow_alpha
            ) * self._reference_price + slow_alpha * nudge_target
            log_event(
                "warning",
                "price_limit_nudge",
                f"Price {price:.10f} outside dynamic limits — rejected but nudging "
                f"reference EMA toward band edge {nudge_target:.10f} (alpha={slow_alpha})",
            )
            self._last_rail_breach = "below"
            self._last_rail_breach_price = price
            self._last_rail_breach_kind = "dyn_min"
            return None

        if dyn_max is not None and price > dyn_max:
            if now - getattr(self, "_last_dynmax_warn", 0) >= 60:
                log_event(
                    "warning",
                    "price_guard",
                    f"Price {price:.10f} above dynamic maximum {dyn_max:.10f} "
                    f"(ref: {self._reference_price:.10f}, band: ±{cfg.DYNAMIC_LIMIT_PCT}%)",
                )
                self._last_dynmax_warn = now
            # Nudge toward band edge (same rationale — clamp to dyn_max, not the
            # rejected price, to prevent slow-burn reference manipulation).
            slow_alpha = getattr(cfg, "PRICE_LIMIT_NUDGE_ALPHA", Decimal("0.02"))
            nudge_target = dyn_max  # clamp to band edge
            self._reference_price = (
                Decimal("1") - slow_alpha
            ) * self._reference_price + slow_alpha * nudge_target
            log_event(
                "warning",
                "price_limit_nudge",
                f"Price {price:.10f} outside dynamic limits — rejected but nudging "
                f"reference EMA toward band edge {nudge_target:.10f} (alpha={slow_alpha})",
            )
            self._last_rail_breach = "above"
            self._last_rail_breach_price = price
            self._last_rail_breach_kind = "dyn_max"
            return None

        # --- Hard limits (absolute backstop from .env) ---
        if cfg.HARD_MIN_PRICE_XCH > 0 and price < cfg.HARD_MIN_PRICE_XCH:
            if now - getattr(self, "_last_min_warn", 0) >= 60:
                log_event(
                    "warning",
                    "price_guard",
                    f"Price {price:.10f} below hard minimum {cfg.HARD_MIN_PRICE_XCH}",
                )
                self._last_min_warn = now
            self._last_rail_breach = "below"
            self._last_rail_breach_price = price
            self._last_rail_breach_kind = "hard_min"
            return None

        if cfg.HARD_MAX_PRICE_XCH > 0 and price > cfg.HARD_MAX_PRICE_XCH:
            if now - getattr(self, "_last_max_warn", 0) >= 60:
                log_event(
                    "warning",
                    "price_guard",
                    f"Price {price:.10f} above hard maximum {cfg.HARD_MAX_PRICE_XCH}",
                )
                self._last_max_warn = now
            self._last_rail_breach = "above"
            self._last_rail_breach_price = price
            self._last_rail_breach_kind = "hard_max"
            return None

        # --- Step-change guard (reject sudden jumps) ---
        if (
            cfg.MAX_STEP_CHANGE_FRACTION > 0
            and self._last_mid_price is not None
            and self._last_mid_price > 0
        ):
            change = abs(price - self._last_mid_price) / self._last_mid_price
            if change > cfg.MAX_STEP_CHANGE_FRACTION:
                if now - getattr(self, "_last_step_warn", 0) >= 60:
                    log_event(
                        "warning",
                        "price_guard",
                        f"Price step too large: {change:.4f} > {cfg.MAX_STEP_CHANGE_FRACTION}",
                    )
                    self._last_step_warn = now
                # Step rejection direction = sign of the move from last mid
                self._last_rail_breach = (
                    "above" if price > self._last_mid_price else "below"
                )
                self._last_rail_breach_price = price
                self._last_rail_breach_kind = "step"
                return None

        return price


# ---------------------------------------------------------------------------
# Utility: Decimal square root (Newton's method)
# ---------------------------------------------------------------------------
def _decimal_sqrt(value: Decimal, precision: int = 20) -> Decimal:
    """Calculate square root of a Decimal using Newton's method."""
    if value < 0:
        raise ValueError("Cannot take square root of negative number")
    if value == 0:
        return Decimal("0")

    # Initial guess
    x = value
    for _ in range(precision):
        x = (x + value / x) / Decimal("2")
    return x
