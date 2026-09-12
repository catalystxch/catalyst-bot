"""Runtime orchestration for attributable offer-book confidence.

This module is deliberately provider-neutral at the policy boundary. Network
clients remain behind injected callbacks; the runtime normalizes their output,
persists the exact evidence, derives confidence, and advances the durable
degraded-market controller as one coherent refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
import json
from typing import Callable

from degraded_market import DegradedMarketController, DegradedMarketDecision
from market_confidence import MarketConfidenceEngine, MarketConfidenceResult
from market_evidence import (
    load_confidence_engine_state,
    persist_confidence_snapshot,
    persist_provider_observation,
)
from providers.dexie import DexieOrderbookProvider
from providers.splash import SplashOfferProvider


@dataclass(frozen=True, slots=True)
class OfferBookRuntimeResult:
    confidence: MarketConfidenceResult
    degraded: DegradedMarketDecision
    snapshot_id: str
    valid_until: datetime


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
        fetch_dexie_settled_trades: Callable[[str], list[dict]] | None = None,
        refresh_cadence_seconds: int = 60,
        minimum_provider_count: int = 2,
        evidence_freshness_seconds: int = 30,
    ) -> None:
        self.asset_id = str(asset_id).strip().lower()
        self._fetch_splash_health = fetch_splash_health
        self._dexie = DexieOrderbookProvider(
            fetch_book=fetch_dexie_book,
            fetch_settled_trades=fetch_dexie_settled_trades,
            order_book_freshness_seconds=evidence_freshness_seconds,
        )
        self._has_dexie_settled_trades = fetch_dexie_settled_trades is not None
        self._splash = SplashOfferProvider(
            fetch_offers=fetch_splash_offers,
            get_health=fetch_splash_health,
            order_book_freshness_seconds=evidence_freshness_seconds,
        )
        self._engine = MarketConfidenceEngine(
            risk_preset=risk_preset,
            refresh_cadence_seconds=refresh_cadence_seconds,
            minimum_provider_count=minimum_provider_count,
        )
        persisted_state = load_confidence_engine_state(self.asset_id)
        if persisted_state is not None:
            self._engine.hydrate(persisted_state, allow_preset_rebase=True)
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

        settled_trade_price = None
        supporting_evidence_digests: tuple[str, ...] = ()
        if self._has_dexie_settled_trades:
            settled = self._dexie.observe_settled_trade(self.asset_id, now=now)
            persist_provider_observation(settled)
            if settled.quality.value == "valid" and settled.fresh_until >= now:
                payload = json.loads(settled.raw_evidence_json)
                minimum_trade_mojos = (
                    Decimal(configured_offer_size_mojos)
                    * Decimal(self._engine.derived_thresholds["minimum_evidence_ratio"])
                ).to_integral_value(rounding=ROUND_CEILING)
                settled_trade_mojos = Decimal(
                    payload["trade"]["target_volume"]
                ) * Decimal("1000000000000")
                if settled_trade_mojos >= minimum_trade_mojos:
                    settled_trade_price = Decimal(payload["trade"]["price"])
                    supporting_evidence_digests = (settled.payload_sha256,)

        confidence = self._engine.evaluate(
            observations=(dexie, splash),
            own_offer_identities=own_offer_identities,
            configured_offer_size_mojos=configured_offer_size_mojos,
            now=now,
            settled_trade_price=settled_trade_price,
            supporting_evidence_digests=supporting_evidence_digests,
        )
        degraded = self._degraded.update(
            confidence_state=("GREEN" if confidence.data_valid else confidence.state),
            now=now,
        )
        snapshot = confidence.to_snapshot(
            asset_id=self.asset_id,
            degraded_since=degraded.degraded_since,
            withdrawal_stage=degraded.stage,
            recovery_refreshes=degraded.recovery_refreshes,
        )
        snapshot_id = persist_confidence_snapshot(
            snapshot, engine_state=self._engine.export_state()
        )
        valid_observation_deadlines = [
            observation.fresh_until
            for observation in (dexie, splash)
            if observation.quality.value == "valid" and observation.fresh_until >= now
        ]
        return OfferBookRuntimeResult(
            confidence=confidence,
            degraded=degraded,
            snapshot_id=snapshot_id,
            valid_until=(
                min(valid_observation_deadlines) if valid_observation_deadlines else now
            ),
        )
