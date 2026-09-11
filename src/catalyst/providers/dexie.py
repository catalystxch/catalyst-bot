"""Dexie adapter producing exact offer-book evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from ._normalization import (
    exact_price,
    failed_observation,
    observation,
    source_datetime,
    utc_now,
)
from .models import (
    BookObservation,
    Capability,
    ObservationQuality,
    ProviderCapabilities,
    ProviderObservation,
)


class DexieOrderbookProvider:
    def __init__(
        self,
        *,
        fetch_book: Callable[[str], dict[str, Any]],
        fetch_settled_trades: Callable[[str], list[dict[str, Any]]] | None = None,
        fetch_metadata: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._fetch_book = fetch_book
        self._fetch_settled_trades = fetch_settled_trades
        self._fetch_metadata = fetch_metadata
        self.capabilities = ProviderCapabilities(
            "dexie",
            frozenset(
                {
                    Capability.ORDER_BOOK,
                    Capability.SETTLED_TRADES,
                    Capability.TOKEN_METADATA,
                    Capability.PUBLISH_OFFER,
                    Capability.DISCOVER_OFFER,
                }
            ),
        )

    def observe_order_book(
        self, asset_id: str, *, now: datetime | None = None
    ) -> ProviderObservation:
        observed_at = utc_now(now)
        try:
            payload = self._fetch_book(asset_id)
            if type(payload) is not dict:
                raise TypeError("Dexie order book must be an object")
            duplicate = False
            seen: set[str] = set()

            def normalize_side(rows: Any, side: str) -> list[dict[str, Any]]:
                nonlocal duplicate
                if type(rows) is not list:
                    raise TypeError(f"Dexie {side} rows must be a list")
                normalized = []
                for row in rows:
                    if type(row) is not dict:
                        raise TypeError("Dexie offer row must be an object")
                    offer_id = row.get("offer_id")
                    amount = row.get("amount_mojos")
                    if type(offer_id) is not str or not offer_id.strip():
                        raise ValueError("Dexie offer identity is missing")
                    if offer_id in seen:
                        duplicate = True
                        continue
                    if type(amount) is not int or amount <= 0:
                        raise ValueError("Dexie offer amount is invalid")
                    exact_price(row.get("price"))
                    seen.add(offer_id)
                    normalized.append(
                        {
                            "offer_id": offer_id,
                            "price": str(row.get("price")),
                            "amount_mojos": amount,
                        }
                    )
                normalized.sort(
                    key=lambda item: exact_price(item["price"]),
                    reverse=side == "bids",
                )
                return normalized

            bids = normalize_side(payload.get("bids"), "bids")
            asks = normalize_side(payload.get("asks"), "asks")
            BookObservation(
                asset_id=asset_id,
                quote_asset_id="xch",
                bids=tuple(
                    (exact_price(row["price"]), row["amount_mojos"], row["offer_id"])
                    for row in bids
                ),
                asks=tuple(
                    (exact_price(row["price"]), row["amount_mojos"], row["offer_id"])
                    for row in asks
                ),
                observed_at=observed_at,
                provider_id="dexie",
            )
            reasons = []
            if duplicate:
                reasons.append("duplicate_offer_identity")
            if not bids and not asks:
                reasons.append("empty_book")
            elif not bids or not asks:
                reasons.append("one_sided_book")
            quality = (
                ObservationQuality.VALID
                if bids and asks
                else ObservationQuality.DEGRADED
            )
            normalized_payload = {
                "asset_id": asset_id.lower(),
                "quote_asset_id": "xch",
                "bids": bids,
                "asks": asks,
            }
            return observation(
                provider_id="dexie",
                capability=Capability.ORDER_BOOK,
                payload=normalized_payload,
                observed_at=observed_at,
                source_time=source_datetime(payload.get("source_time")),
                identity_keys=(asset_id.lower(), *sorted(seen)),
                freshness_seconds=20,
                quality=quality,
                reason_codes=tuple(reasons),
            )
        except Exception as exc:
            return failed_observation(
                provider_id="dexie",
                capability=Capability.ORDER_BOOK,
                identity_keys=(asset_id.lower(),),
                now=observed_at,
                error=exc,
                freshness_seconds=5,
            )

    def observe_settled_trade(
        self, asset_id: str, *, now: datetime | None = None
    ) -> ProviderObservation:
        """Normalize the newest attributable Dexie trade as short-lived evidence."""

        observed_at = utc_now(now)
        try:
            if self._fetch_settled_trades is None:
                raise RuntimeError("Dexie settled-trade callback is unavailable")
            rows = self._fetch_settled_trades(asset_id)
            if type(rows) is not list:
                raise TypeError("Dexie settled trades must be a list")
            if not rows:
                return observation(
                    provider_id="dexie",
                    capability=Capability.SETTLED_TRADES,
                    payload={
                        "asset_id": asset_id.lower(),
                        "quote_asset_id": "xch",
                        "trade": None,
                    },
                    observed_at=observed_at,
                    identity_keys=(asset_id.lower(),),
                    freshness_seconds=5,
                    quality=ObservationQuality.DEGRADED,
                    reason_codes=("no_settled_trades",),
                )

            normalized: list[tuple[datetime, dict[str, str]]] = []
            for row in rows:
                if type(row) is not dict:
                    raise TypeError("Dexie settled trade must be an object")
                trade_id = row.get("trade_id")
                if type(trade_id) is not str or not trade_id.strip():
                    raise ValueError("Dexie settled trade identity is missing")
                exact_price(row.get("price"))
                side = row.get("type") or row.get("side")
                if side not in {"buy", "sell"}:
                    raise ValueError("Dexie settled trade side is invalid")

                def positive_exact_text(key: str) -> str:
                    value = row.get(key)
                    if type(value) not in {str, Decimal}:
                        raise TypeError(f"Dexie settled trade {key} must be exact text")
                    try:
                        amount = Decimal(value)
                    except (InvalidOperation, ValueError) as exc:
                        raise ValueError(
                            f"Dexie settled trade {key} is invalid"
                        ) from exc
                    if not amount.is_finite() or amount <= 0:
                        raise ValueError(f"Dexie settled trade {key} must be positive")
                    return str(value)

                raw_timestamp = row.get("trade_timestamp")
                if raw_timestamp is None:
                    raw_timestamp = row.get("timestamp") or row.get("time")
                if type(raw_timestamp) is int:
                    seconds = (
                        Decimal(raw_timestamp) / Decimal(1000)
                        if raw_timestamp >= 100_000_000_000
                        else Decimal(raw_timestamp)
                    )
                    trade_time = datetime.fromtimestamp(float(seconds), tz=timezone.utc)
                elif type(raw_timestamp) is str:
                    trade_time = source_datetime(raw_timestamp)
                    if trade_time is None:
                        raise ValueError("Dexie settled trade time is missing")
                else:
                    raise TypeError("Dexie settled trade time is invalid")
                normalized.append(
                    (
                        trade_time,
                        {
                            "trade_id": trade_id.strip(),
                            "price": str(row.get("price")),
                            "base_volume": positive_exact_text("base_volume"),
                            "target_volume": positive_exact_text("target_volume"),
                            "side": side,
                        },
                    )
                )

            trade_time, trade = max(normalized, key=lambda item: item[0])
            return observation(
                provider_id="dexie",
                capability=Capability.SETTLED_TRADES,
                payload={
                    "asset_id": asset_id.lower(),
                    "quote_asset_id": "xch",
                    "trade": trade,
                },
                observed_at=observed_at,
                source_time=trade_time,
                identity_keys=(asset_id.lower(), trade["trade_id"]),
                freshness_seconds=60,
                quality=ObservationQuality.VALID,
            )
        except Exception as exc:
            return failed_observation(
                provider_id="dexie",
                capability=Capability.SETTLED_TRADES,
                identity_keys=(asset_id.lower(),),
                now=observed_at,
                error=exc,
                freshness_seconds=5,
            )
