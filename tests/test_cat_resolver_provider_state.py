"""Regression tests for TibetSwap CAT metadata provider state."""

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


def test_pair_lookup_reports_unavailable_when_tibet_pairs_request_fails(monkeypatch):
    """A provider failure must not be represented as a genuine missing pair."""

    def get(url, **_kwargs):
        if url.endswith("/tokens"):
            return _Response([])
        return _Response(None, status_code=502)

    monkeypatch.setattr(cat_resolver.requests, "get", get)

    metadata = cat_resolver.resolve_cat_metadata("a" * 64)

    assert metadata["pair_lookup_status"] == "unavailable"


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
