"""Fail-closed capability policy for experimental CHIP-0052 partial offers.

Detection inspects immutable provider declarations only.  It never calls a
wallet or market adapter and has no configuration/request override.  All five
wallet-side capabilities must be implemented by one wallet authority, while a
separate public provider must prove discoverability.
"""

from __future__ import annotations

from dataclasses import dataclass

from providers.models import Capability
from providers.registry import ProviderRegistry


_WALLET_REQUIREMENTS = (
    Capability.PARTIAL_CREATE,
    Capability.PARTIAL_CANCEL,
    Capability.PARTIAL_STATE,
    Capability.PARTIAL_LINEAGE,
    Capability.PARTIAL_FILL,
)


@dataclass(frozen=True, slots=True)
class PartialOfferCapabilityDecision:
    enabled: bool
    reason_codes: tuple[str, ...]
    providers: tuple[str, ...]


def evaluate_partial_offer_capability(
    registry: ProviderRegistry,
) -> PartialOfferCapabilityDecision:
    if type(registry) is not ProviderRegistry:
        raise TypeError("registry must be a ProviderRegistry")
    providers = registry.all()
    provider_ids = tuple(provider.capabilities.provider_id for provider in providers)
    wallet_providers = tuple(
        provider
        for provider in providers
        if provider.capabilities.supports(Capability.WALLET_AUTHORITY)
    )
    reasons: list[str] = []
    for capability in _WALLET_REQUIREMENTS:
        if not any(
            provider.capabilities.supports(capability) for provider in wallet_providers
        ):
            reasons.append(f"MISSING_{capability.value.upper()}")

    if not reasons and not any(
        all(
            provider.capabilities.supports(capability)
            for capability in _WALLET_REQUIREMENTS
        )
        for provider in wallet_providers
    ):
        reasons.append("PARTIAL_WALLET_CAPABILITIES_NOT_COHERENT")

    public_discovery = any(
        not provider.capabilities.supports(Capability.WALLET_AUTHORITY)
        and provider.capabilities.supports(Capability.DISCOVER_OFFER)
        and provider.capabilities.supports(Capability.PARTIAL_DISCOVERY)
        for provider in providers
    )
    if not public_discovery:
        reasons.append("MISSING_PARTIAL_DISCOVERY")

    return PartialOfferCapabilityDecision(
        enabled=not reasons,
        reason_codes=tuple(reasons),
        providers=provider_ids,
    )


__all__ = [
    "PartialOfferCapabilityDecision",
    "evaluate_partial_offer_capability",
]
