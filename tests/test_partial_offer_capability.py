from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from partial_offer_capability import evaluate_partial_offer_capability
from providers.dexie import DexieOrderbookProvider
from providers.models import Capability, ProviderCapabilities
from providers.registry import ProviderRegistry
from providers.sage import SageAuthorityProvider
from providers.splash import SplashOfferProvider


ROOT = Path(__file__).resolve().parents[1]
WALLET_PARTIAL = frozenset(
    {
        Capability.PARTIAL_CREATE,
        Capability.PARTIAL_CANCEL,
        Capability.PARTIAL_STATE,
        Capability.PARTIAL_LINEAGE,
        Capability.PARTIAL_FILL,
    }
)


class Provider:
    def __init__(self, provider_id: str, capabilities: frozenset[Capability]):
        self.capabilities = ProviderCapabilities(provider_id, capabilities)


def complete_registry(*, missing: Capability | None = None) -> ProviderRegistry:
    wallet = set(WALLET_PARTIAL | {Capability.WALLET_AUTHORITY})
    discovery = {Capability.DISCOVER_OFFER, Capability.PARTIAL_DISCOVERY}
    if missing in wallet:
        wallet.remove(missing)
    if missing in discovery:
        discovery.remove(missing)
    registry = ProviderRegistry()
    registry.register(Provider("sage", frozenset(wallet)))
    registry.register(Provider("dexie", frozenset(discovery)))
    return registry


def test_complete_coherent_wallet_and_independent_discovery_enable_capability():
    decision = evaluate_partial_offer_capability(complete_registry())

    assert decision.enabled is True
    assert decision.reason_codes == ()
    assert decision.providers == ("dexie", "sage")


@pytest.mark.parametrize(
    "missing",
    [
        Capability.PARTIAL_CREATE,
        Capability.PARTIAL_CANCEL,
        Capability.PARTIAL_STATE,
        Capability.PARTIAL_LINEAGE,
        Capability.PARTIAL_FILL,
        Capability.PARTIAL_DISCOVERY,
    ],
)
def test_every_required_partial_capability_fails_closed_with_exact_reason(missing):
    decision = evaluate_partial_offer_capability(complete_registry(missing=missing))

    assert decision.enabled is False
    assert f"MISSING_{missing.value.upper()}" in decision.reason_codes
    assert decision.providers == ("dexie", "sage")


def test_wallet_capabilities_cannot_be_composed_across_multiple_wallets():
    registry = ProviderRegistry()
    registry.register(
        Provider(
            "sage_a",
            frozenset(
                {
                    Capability.WALLET_AUTHORITY,
                    Capability.PARTIAL_CREATE,
                    Capability.PARTIAL_CANCEL,
                }
            ),
        )
    )
    registry.register(
        Provider(
            "sage_b",
            frozenset(
                {
                    Capability.WALLET_AUTHORITY,
                    Capability.PARTIAL_STATE,
                    Capability.PARTIAL_LINEAGE,
                    Capability.PARTIAL_FILL,
                }
            ),
        )
    )
    registry.register(
        Provider(
            "dexie",
            frozenset({Capability.DISCOVER_OFFER, Capability.PARTIAL_DISCOVERY}),
        )
    )

    decision = evaluate_partial_offer_capability(registry)

    assert decision.enabled is False
    assert "PARTIAL_WALLET_CAPABILITIES_NOT_COHERENT" in decision.reason_codes


def test_wallet_authority_cannot_self_attest_public_partial_discovery():
    registry = ProviderRegistry()
    registry.register(
        Provider(
            "sage",
            frozenset(
                WALLET_PARTIAL
                | {
                    Capability.WALLET_AUTHORITY,
                    Capability.DISCOVER_OFFER,
                    Capability.PARTIAL_DISCOVERY,
                }
            ),
        )
    )

    decision = evaluate_partial_offer_capability(registry)

    assert decision.enabled is False
    assert decision.reason_codes == ("MISSING_PARTIAL_DISCOVERY",)


def test_partial_discovery_requires_a_provider_with_standard_offer_discovery():
    registry = ProviderRegistry()
    registry.register(
        Provider(
            "sage",
            frozenset(WALLET_PARTIAL | {Capability.WALLET_AUTHORITY}),
        )
    )
    registry.register(Provider("indexer", frozenset({Capability.PARTIAL_DISCOVERY})))

    decision = evaluate_partial_offer_capability(registry)

    assert decision.enabled is False
    assert decision.reason_codes == ("MISSING_PARTIAL_DISCOVERY",)


def test_current_real_adapters_are_disabled_without_invoking_any_adapter_method():
    def forbidden(*_args, **_kwargs):
        raise AssertionError("capability detection invoked an adapter")

    registry = ProviderRegistry()
    registry.register(
        SageAuthorityProvider(type("Wallet", (), {"__getattr__": forbidden})())
    )
    registry.register(
        DexieOrderbookProvider(
            fetch_book=forbidden,
            fetch_settled_trades=forbidden,
            fetch_metadata=forbidden,
        )
    )
    registry.register(SplashOfferProvider(fetch_offers=forbidden, get_health=forbidden))

    decision = evaluate_partial_offer_capability(registry)

    assert decision.enabled is False
    assert decision.reason_codes == (
        "MISSING_PARTIAL_CREATE",
        "MISSING_PARTIAL_CANCEL",
        "MISSING_PARTIAL_STATE",
        "MISSING_PARTIAL_LINEAGE",
        "MISSING_PARTIAL_FILL",
        "MISSING_PARTIAL_DISCOVERY",
    )
    assert decision.providers == ("dexie", "sage", "splash")


def test_no_force_enable_setting_or_evaluator_bypass_exists():
    config_source = (ROOT / "src" / "catalyst" / "config.py").read_text(
        encoding="utf-8"
    )
    api_source = (ROOT / "src" / "catalyst" / "blueprints" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    evaluator_source = inspect.getsource(evaluate_partial_offer_capability)

    assert "FORCE_PARTIAL" not in config_source
    assert "ENABLE_PARTIAL" not in config_source
    assert "force_partial" not in api_source.lower()
    assert tuple(inspect.signature(evaluate_partial_offer_capability).parameters) == (
        "registry",
    )
    assert "cfg" not in evaluator_source
    assert "request" not in evaluator_source


def test_current_adapters_do_not_claim_unimplemented_partial_contracts():
    def unused(*_args, **_kwargs):
        return {}

    providers = (
        SageAuthorityProvider(object()),
        DexieOrderbookProvider(fetch_book=unused),
        SplashOfferProvider(fetch_offers=unused, get_health=unused),
    )

    for provider in providers:
        assert provider.capabilities.capabilities.isdisjoint(
            {
                Capability.PARTIAL_CREATE,
                Capability.PARTIAL_CANCEL,
                Capability.PARTIAL_STATE,
                Capability.PARTIAL_LINEAGE,
                Capability.PARTIAL_FILL,
                Capability.PARTIAL_DISCOVERY,
            }
        )
