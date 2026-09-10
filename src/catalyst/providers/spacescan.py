"""Spacescan adapter for optional exact chain evidence."""

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


class SpacescanEvidenceProvider:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.capabilities = ProviderCapabilities(
            "spacescan",
            frozenset({Capability.CHAIN_EVIDENCE, Capability.TOKEN_METADATA}),
        )

    def observe_coin(
        self, coin_id: str, *, now: datetime | None = None
    ) -> ProviderObservation:
        observed_at = utc_now(now)
        try:
            raw = self._client.is_coin_spent(coin_id)
            if raw is None:
                return observation(
                    provider_id="spacescan",
                    capability=Capability.CHAIN_EVIDENCE,
                    payload={"available": False, "observed": False},
                    observed_at=observed_at,
                    identity_keys=(coin_id.lower(),),
                    freshness_seconds=20,
                    quality=ObservationQuality.DEGRADED,
                    reason_codes=("provider_unavailable",),
                )
            if (
                type(raw) is not dict
                or str(raw.get("coin_id") or "").lower() != coin_id.lower()
            ):
                raise ValueError("Spacescan coin identity mismatch")
            spent = raw.get("spent")
            if type(spent) is not bool:
                raise ValueError("Spacescan spent state is invalid")
            height = exact_nonnegative_height(raw.get("spent_block_height"))
            return observation(
                provider_id="spacescan",
                capability=Capability.CHAIN_EVIDENCE,
                payload={
                    "coin_id": coin_id.lower(),
                    "spent": spent,
                    "spent_block_height": height,
                },
                observed_at=observed_at,
                source_height=height,
                identity_keys=(coin_id.lower(),),
                freshness_seconds=20,
                quality=ObservationQuality.VALID,
            )
        except Exception as exc:
            return failed_observation(
                provider_id="spacescan",
                capability=Capability.CHAIN_EVIDENCE,
                identity_keys=(coin_id.lower(),),
                now=observed_at,
                error=exc,
                freshness_seconds=5,
            )
