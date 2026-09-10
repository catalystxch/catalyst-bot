"""Coinset adapter for exact coin and spend evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._normalization import (
    exact_nonnegative_height,
    failed_observation,
    observation,
    utc_now,
)
from .models import (
    Capability,
    ObservationQuality,
    ProviderCapabilities,
    ProviderObservation,
)


class CoinsetEvidenceProvider:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.capabilities = ProviderCapabilities(
            "coinset", frozenset({Capability.CHAIN_EVIDENCE})
        )

    def observe_coin(
        self, coin_id: str, *, now: datetime | None = None
    ) -> ProviderObservation:
        observed_at = utc_now(now)
        try:
            raw = self._client.get_coin_by_name(coin_id)
            if raw is None:
                return observation(
                    provider_id="coinset",
                    capability=Capability.CHAIN_EVIDENCE,
                    payload={"available": True, "observed": False},
                    observed_at=observed_at,
                    identity_keys=(coin_id.lower(),),
                    freshness_seconds=20,
                    quality=ObservationQuality.DEGRADED,
                    reason_codes=("coin_not_observed",),
                )
            if (
                type(raw) is not dict
                or str(raw.get("coin_name") or "").lower() != coin_id.lower()
            ):
                raise ValueError("Coinset coin identity mismatch")
            height = exact_nonnegative_height(raw.get("spent_block_index"))
            spent = raw.get("spent")
            if type(spent) is not bool:
                raise ValueError("Coinset spent state is invalid")
            return observation(
                provider_id="coinset",
                capability=Capability.CHAIN_EVIDENCE,
                payload={
                    "coin_id": coin_id.lower(),
                    "spent": spent,
                    "spent_block_height": height,
                    "confirmed_block_height": exact_nonnegative_height(
                        raw.get("confirmed_block_index")
                    ),
                },
                observed_at=observed_at,
                source_height=height,
                identity_keys=(coin_id.lower(),),
                freshness_seconds=20,
                quality=ObservationQuality.VALID,
            )
        except Exception as exc:
            return failed_observation(
                provider_id="coinset",
                capability=Capability.CHAIN_EVIDENCE,
                identity_keys=(coin_id.lower(),),
                now=observed_at,
                error=exc,
                freshness_seconds=5,
            )
