"""Runtime orchestration for attributable offer-book confidence.

This module is deliberately provider-neutral at the policy boundary. Network
clients remain behind injected callbacks; the runtime normalizes their output,
persists the exact evidence, derives confidence, and advances the durable
degraded-market controller as one coherent refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from degraded_market import DegradedMarketController, DegradedMarketDecision
from market_confidence import MarketConfidenceEngine, MarketConfidenceResult
from market_evidence import persist_confidence_snapshot, persist_provider_observation
from providers.dexie import DexieOrderbookProvider
from providers.splash import SplashOfferProvider


@dataclass(frozen=True, slots=True)
class OfferBookRuntimeResult:
    confidence: MarketConfidenceResult
    degraded: DegradedMarketDecision
    snapshot_id: str


class OfferBookMarketRuntime:
    """Own the stateful confidence and withdrawal policy for one CAT asset."""

    def __init__(
        self,
        *,
        asset_id: str,
        risk_preset: str,
        fetch_dexie_book: Callable[[str], dict],
        fetch_splash_offers: Callable[[str], list[dict]],
        fetch_splash_health: Callable[[], dict],
    ) -> None:
        self.asset_id = str(asset_id).strip().lower()
        self._fetch_splash_health = fetch_splash_health
        self._dexie = DexieOrderbookProvider(fetch_book=fetch_dexie_book)
        self._splash = SplashOfferProvider(
            fetch_offers=fetch_splash_offers,
            get_health=fetch_splash_health,
        )
        self._engine = MarketConfidenceEngine(risk_preset=risk_preset)
        self._degraded = DegradedMarketController(asset_id=self.asset_id)

    def refresh(
        self,
        *,
        own_offer_identities: frozenset[str],
        configured_offer_size_mojos: int,
        now: datetime,
    ) -> OfferBookRuntimeResult:
        dexie = self._dexie.observe_order_book(self.asset_id, now=now)
        health = self._splash.observe_peer_health(now=now)
        if health.quality.value == "valid":
            splash = self._splash.observe_offers(self.asset_id, now=now)
        else:
            unavailable = SplashOfferProvider(
                fetch_offers=lambda _asset_id: [],
                get_health=self._fetch_splash_health,
            )
            splash = unavailable.observe_offers(self.asset_id, now=now)

        for observation in (dexie, splash):
            persist_provider_observation(observation)

        confidence = self._engine.evaluate(
            observations=(dexie, splash),
            own_offer_identities=own_offer_identities,
            configured_offer_size_mojos=configured_offer_size_mojos,
            now=now,
        )
        degraded = self._degraded.update(
            confidence_state=confidence.state,
            now=now,
        )
        snapshot = confidence.to_snapshot(
            asset_id=self.asset_id,
            degraded_since=degraded.degraded_since,
            withdrawal_stage=degraded.stage,
            recovery_refreshes=degraded.recovery_refreshes,
        )
        snapshot_id = persist_confidence_snapshot(snapshot)
        return OfferBookRuntimeResult(
            confidence=confidence,
            degraded=degraded,
            snapshot_id=snapshot_id,
        )
