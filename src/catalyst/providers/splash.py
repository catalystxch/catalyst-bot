"""Splash adapter for exact peer offers and local peer health."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ._normalization import exact_price, failed_observation, observation, utc_now
from .models import (
    Capability,
    ObservationQuality,
    ProviderCapabilities,
    ProviderObservation,
)


class SplashOfferProvider:
    def __init__(
        self,
        *,
        fetch_offers: Callable[[str], list[dict[str, Any]]],
        get_health: Callable[[], dict[str, Any]],
    ) -> None:
        self._fetch_offers = fetch_offers
        self._get_health = get_health
        self.capabilities = ProviderCapabilities(
            "splash",
            frozenset(
                {
                    Capability.ORDER_BOOK,
                    Capability.PUBLISH_OFFER,
                    Capability.DISCOVER_OFFER,
                    Capability.PEER_HEALTH,
                }
            ),
        )

    def observe_offers(
        self, asset_id: str, *, now: datetime | None = None
    ) -> ProviderObservation:
        observed_at = utc_now(now)
        try:
            rows = self._fetch_offers(asset_id)
            if type(rows) is not list:
                raise TypeError("Splash offer set must be a list")
            normalized: list[dict[str, Any]] = []
            seen: set[str] = set()
            duplicate = False
            for row in rows:
                if type(row) is not dict:
                    raise TypeError("Splash offer row must be an object")
                offer_id = row.get("offer_id")
                side = row.get("side")
                amount = row.get("amount_mojos")
                price = exact_price(row.get("price"))
                if type(offer_id) is not str or not offer_id:
                    raise ValueError("Splash offer identity is missing")
                if offer_id in seen:
                    duplicate = True
                    continue
                if side not in {"buy", "sell"}:
                    raise ValueError("Splash offer side is invalid")
                if type(amount) is not int or amount <= 0:
                    raise ValueError("Splash offer amount is invalid")
                seen.add(offer_id)
                normalized.append(
                    {
                        "offer_id": offer_id,
                        "side": side,
                        "price": str(row.get("price")),
                        "amount_mojos": amount,
                    }
                )
            normalized.sort(key=lambda row: row["offer_id"])
            reasons = ("duplicate_offer_identity",) if duplicate else ()
            quality = (
                ObservationQuality.VALID if normalized else ObservationQuality.DEGRADED
            )
            if not normalized:
                reasons = (*reasons, "empty_offer_set")
            return observation(
                provider_id="splash",
                capability=Capability.ORDER_BOOK,
                payload={"asset_id": asset_id.lower(), "offers": normalized},
                observed_at=observed_at,
                identity_keys=(asset_id.lower(), *sorted(seen)),
                freshness_seconds=20,
                quality=quality,
                reason_codes=reasons,
            )
        except Exception as exc:
            return failed_observation(
                provider_id="splash",
                capability=Capability.ORDER_BOOK,
                identity_keys=(asset_id.lower(),),
                now=observed_at,
                error=exc,
                freshness_seconds=5,
            )

    def observe_peer_health(
        self, *, now: datetime | None = None
    ) -> ProviderObservation:
        observed_at = utc_now(now)
        try:
            raw = self._get_health()
            if type(raw) is not dict:
                raise TypeError("Splash health must be an object")
            running = raw.get("running") is True
            reachable = raw.get("api_reachable") is True
            peers = raw.get("peers")
            if type(peers) is not int or peers < 0:
                raise ValueError("Splash peer count is invalid")
            reasons = []
            if not running:
                reasons.append("node_not_running")
            if not reachable:
                reasons.append("api_unreachable")
            if peers == 0:
                reasons.append("no_peers")
            return observation(
                provider_id="splash",
                capability=Capability.PEER_HEALTH,
                payload={
                    "running": running,
                    "api_reachable": reachable,
                    "peers": peers,
                },
                observed_at=observed_at,
                identity_keys=("splash-local-node",),
                freshness_seconds=10,
                quality=(
                    ObservationQuality.VALID
                    if not reasons
                    else ObservationQuality.DEGRADED
                ),
                reason_codes=tuple(reasons),
            )
        except Exception as exc:
            return failed_observation(
                provider_id="splash",
                capability=Capability.PEER_HEALTH,
                identity_keys=("splash-local-node",),
                now=observed_at,
                error=exc,
                freshness_seconds=5,
            )
