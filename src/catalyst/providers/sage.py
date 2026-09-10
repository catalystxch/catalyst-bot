"""Sage adapter for wallet-authoritative identity evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._normalization import failed_observation, observation, utc_now
from .models import (
    Capability,
    ObservationQuality,
    ProviderCapabilities,
    ProviderObservation,
)


class SageAuthorityProvider:
    def __init__(self, wallet_facade: Any) -> None:
        self._wallet = wallet_facade
        self.capabilities = ProviderCapabilities(
            "sage",
            frozenset(
                {
                    Capability.WALLET_AUTHORITY,
                    Capability.CHAIN_EVIDENCE,
                }
            ),
        )

    def observe_identity(
        self,
        *,
        expected_fingerprint: int,
        expected_network: str,
        now: datetime | None = None,
    ) -> ProviderObservation:
        observed_at = utc_now(now)
        identity_key = f"{expected_fingerprint}:{expected_network.lower()}"
        try:
            raw = self._wallet.get_wallet_identity()
            if type(raw) is not dict:
                raise TypeError("Sage identity must be an object")
            fingerprint = raw.get("fingerprint")
            network = str(raw.get("network_id") or "").lower()
            success = raw.get("success") is True
            if type(fingerprint) is not int or not network:
                raise ValueError("Sage identity is incomplete")
            matches = (
                success
                and fingerprint == expected_fingerprint
                and network == expected_network.lower()
            )
            return observation(
                provider_id="sage",
                capability=Capability.WALLET_AUTHORITY,
                payload={
                    "success": success,
                    "fingerprint": fingerprint,
                    "network_id": network,
                },
                observed_at=observed_at,
                identity_keys=(identity_key,),
                freshness_seconds=10,
                quality=(
                    ObservationQuality.VALID if matches else ObservationQuality.INVALID
                ),
                reason_codes=() if matches else ("wallet_identity_mismatch",),
            )
        except Exception as exc:
            return failed_observation(
                provider_id="sage",
                capability=Capability.WALLET_AUTHORITY,
                identity_keys=(identity_key,),
                now=observed_at,
                error=exc,
                freshness_seconds=5,
            )
