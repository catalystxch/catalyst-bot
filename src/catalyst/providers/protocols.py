"""Structural protocols implemented by CATalyst provider adapters."""

from __future__ import annotations

from typing import Any, Protocol

from .models import Capability, ProviderCapabilities, ProviderObservation


class EvidenceProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    def observe(self, capability: Capability, **request: Any) -> ProviderObservation:
        raise NotImplementedError


class OfferPublisher(EvidenceProvider, Protocol):
    def publish_offer(self, offer_text: str, **context: Any) -> ProviderObservation:
        raise NotImplementedError

    def discover_offer(
        self, offer_identity: str, **context: Any
    ) -> ProviderObservation:
        raise NotImplementedError
