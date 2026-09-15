"""Deterministic registry for providers selected by declared capability."""

from __future__ import annotations

from typing import Any

from .models import Capability, ProviderCapabilities


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}

    def register(self, provider: Any) -> None:
        capabilities = getattr(provider, "capabilities", None)
        if type(capabilities) is not ProviderCapabilities:
            raise TypeError("provider must expose exact ProviderCapabilities")
        provider_id = capabilities.provider_id
        if provider_id in self._providers:
            raise ValueError(f"provider '{provider_id}' is already registered")
        self._providers[provider_id] = provider

    def all(self) -> tuple[Any, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))

    def for_capability(self, capability: Capability) -> tuple[Any, ...]:
        if type(capability) is not Capability:
            raise TypeError("capability is invalid")
        return tuple(
            provider
            for provider in self.all()
            if provider.capabilities.supports(capability)
        )
