"""Typed external-provider contracts for CATalyst's offer-book engine."""

from .models import (
    BookObservation,
    Capability,
    MarketQuote,
    ObservationQuality,
    ProviderCapabilities,
    ProviderObservation,
)
from .coinset import CoinsetEvidenceProvider
from .dexie import DexieOrderbookProvider
from .registry import ProviderRegistry
from .sage import SageAuthorityProvider
from .spacescan import SpacescanEvidenceProvider
from .splash import SplashOfferProvider

__all__ = [
    "BookObservation",
    "Capability",
    "MarketQuote",
    "ObservationQuality",
    "ProviderCapabilities",
    "ProviderObservation",
    "ProviderRegistry",
    "CoinsetEvidenceProvider",
    "DexieOrderbookProvider",
    "SageAuthorityProvider",
    "SpacescanEvidenceProvider",
    "SplashOfferProvider",
]
