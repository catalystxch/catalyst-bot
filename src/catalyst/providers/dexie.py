"""Dexie adapter producing exact offer-book evidence."""

from __future__ import annotations

from datetime import datetime
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
        fetch_metadata: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._fetch_book = fetch_book
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
                    price = exact_price(row.get("price"))
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
