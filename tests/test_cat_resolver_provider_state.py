"""Regression tests for retired TibetSwap CAT metadata compatibility state."""

import requests

import cat_resolver
import api_server  # noqa: F401 - completes blueprint registration before import
from blueprints import cat as cat_blueprint


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_pair_lookup_is_retired_and_only_dexie_is_contacted(monkeypatch):
    """The retired provider must never be contacted during metadata lookup."""

    calls = []

    def get(url, **_kwargs):
        calls.append(url)
        assert "tibet" not in url.lower()
        return _Response({"tickers": []})

    monkeypatch.setattr(cat_resolver.requests, "get", get)

    metadata = cat_resolver.resolve_cat_metadata("a" * 64)

    assert metadata["pair_lookup_status"] == "retired"
    assert metadata["retired_provider"] == "TibetSwap"
    assert calls and all("dexie" in url.lower() for url in calls)


def test_cat_selection_classifies_provider_outage_as_unavailable():
    """CAT selection must not tell operators an unavailable pair is absent."""

    event_builder = getattr(cat_blueprint, "_tibet_resolution_event", None)
    assert callable(event_builder), "CAT selection has no provider-state classifier"

    event = event_builder(
        {"pair_id": None, "pair_lookup_status": "unavailable"},
        "Monkeyzoo Token",
        "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105",
    )

    assert event["level"] == "warning"
    assert event["event_type"] == "cat_tibet_pair_unavailable"
    assert "unavailable" in event["message"].lower()
    assert "has no TibetSwap pair" not in event["message"]
