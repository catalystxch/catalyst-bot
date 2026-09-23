"""Quotes must not turn missing or stale network guidance into spend permission."""

import importlib
import importlib.util
from decimal import Decimal

import pytest


def normalize(response, **overrides):
    assert importlib.util.find_spec("fee_estimation") is not None, (
        "strict fee quote normalization is missing"
    )
    module = importlib.import_module("fee_estimation")
    return module.normalize_fee_response(
        response,
        **{
            "cost": 20_000_000,
            "target_seconds": 300,
            "source": "coinset",
            "observed_at": 100,
            "now": 100,
            **overrides,
        },
    )


@pytest.mark.parametrize(
    "response", [{}, {"success": True}, {"success": True, "estimates": []}]
)
def test_missing_guidance_is_unavailable_not_zero(response):
    quote = normalize(response)
    assert quote["available"] is False
    assert quote["fee_mojos"] is None
    assert quote["fee_xch"] is None


@pytest.mark.parametrize(
    "value,expected", [(0, 0), (123, 123), ("123.01", 124), (Decimal("0.1"), 1)]
)
def test_network_estimate_rounds_up_in_atomic_mojos(value, expected):
    quote = normalize({"success": True, "estimates": [value]})
    assert quote["available"] is True
    assert quote["fee_mojos"] == expected
    assert quote["target_seconds"] == 300
    assert quote["cost"] == 20_000_000
    assert quote["source"] == "coinset"
    assert quote["observed_at"] == 100
    assert quote["expires_at"] == 160


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        -1,
        "-0.1",
        "NaN",
        "Infinity",
        "-Infinity",
        [],
        {},
        "",
        "garbage",
        2**63,
    ],
)
def test_invalid_estimate_never_becomes_spendable(value):
    quote = normalize({"success": True, "estimates": [value]})
    assert quote["available"] is False
    assert quote["fee_mojos"] is None


@pytest.mark.parametrize("success", [False, 1, "true", None])
def test_success_requires_explicit_boolean_true(success):
    assert normalize({"success": success, "estimates": [123]})["available"] is False


@pytest.mark.parametrize(
    "fields",
    [
        {"target_times": [60]},
        {"target_times": [True]},
        {"target_times": []},
        {"cost": 10},
        {"cost": True},
        {"estimates": [1, 2]},
        {"estimates": "123"},
    ],
)
def test_mismatched_or_ambiguous_network_response_is_unavailable(fields):
    response = {
        "success": True,
        "estimates": [123],
        "target_times": [300],
        "cost": 20_000_000,
        **fields,
    }
    assert normalize(response)["available"] is False


@pytest.mark.parametrize(
    "now,available", [(100, True), (159, True), (160, False), (161, False), (99, False)]
)
def test_original_observation_time_controls_quote_freshness(now, available):
    quote = normalize({"success": True, "estimates": [123]}, now=now)
    assert quote["available"] is available
    assert quote["observed_at"] == 100
    if not available:
        assert quote["fee_mojos"] is None


@pytest.mark.parametrize(
    "fields",
    [
        {"cost": True},
        {"cost": 0},
        {"cost": "20000000"},
        {"target_seconds": True},
        {"target_seconds": -1},
        {"observed_at": -1},
        {"observed_at": True},
        {"now": True},
        {"source": "unavailable"},
    ],
)
def test_invalid_quote_request_fails_closed(fields):
    assert (
        normalize({"success": True, "estimates": [123]}, **fields)["available"] is False
    )


def test_xch_display_uses_exact_decimal_conversion():
    quote = normalize({"success": True, "estimates": [13_079_100]})
    assert quote["fee_xch"] == "0.0000130791"


@pytest.mark.parametrize("observed,available", [(100, True), (40, False), (101, False)])
def test_quote_revalidates_provider_observation(monkeypatch, observed, available):
    module = importlib.import_module("fee_estimation")
    import tx_fees

    monkeypatch.setattr(module.time, "time", lambda: 100)
    monkeypatch.setattr(
        tx_fees,
        "get_suggested_transaction_fee",
        lambda **kw: {
            "available": True,
            "source": "coinset",
            "observed_at": observed,
            "fee_mojos": 999,
            "raw": {"success": True, "estimates": [123]},
        },
    )
    quote = module.quote_fee(20_000_000)
    assert quote["available"] is available
    assert quote["fee_mojos"] == (123 if available else None)


def test_invalid_cost_never_calls_provider(monkeypatch):
    module = importlib.import_module("fee_estimation")
    import tx_fees

    def forbidden(**kwargs):
        pytest.fail("invalid request reached fee provider")

    monkeypatch.setattr(tx_fees, "get_suggested_transaction_fee", forbidden)
    assert module.quote_fee(True)["available"] is False


@pytest.mark.parametrize("state", [False, None, 0, 1, "true", "false", [], {}])
def test_supplied_unhealthy_or_malformed_sync_evidence_cannot_authorize_zero_fee(state):
    quote = normalize({"success": True, "estimates": [0], "full_node_synced": state})
    assert quote["available"] is False
    assert quote["fee_mojos"] is None


def test_missing_sync_and_congestion_evidence_is_unknown_not_fabricated():
    quote = normalize({"success": True, "estimates": [0]})
    assert quote["available"] is True
    assert quote["network_evidence"] == {
        "full_node_synced": None, "mempool_size": None,
        "mempool_fees": None, "last_block_cost": None,
    }


def test_network_diagnostics_retain_real_observed_zero_and_nonzero_values():
    evidence = {"full_node_synced": True, "mempool_size": 0,
                "mempool_fees": 123456789, "last_block_cost": 20000000}
    quote = normalize({"success": True, "estimates": [0], **evidence})
    assert quote["available"] is True
    assert quote["network_evidence"] == evidence


@pytest.mark.parametrize("field", ["mempool_size", "mempool_fees", "last_block_cost"])
@pytest.mark.parametrize("value", [True, -1, "0", None, 0.5, 2**63])
def test_malformed_supplied_congestion_evidence_is_rejected(field, value):
    quote = normalize({"success": True, "estimates": [0], field: value})
    assert quote["available"] is False
    assert quote["fee_mojos"] is None


def test_public_quote_revalidates_unsynced_raw_evidence(monkeypatch):
    module = importlib.import_module("fee_estimation")
    tx_fees = importlib.import_module("tx_fees")
    monkeypatch.setattr(module.time, "time", lambda: 100)
    monkeypatch.setattr(tx_fees, "get_suggested_transaction_fee", lambda **_kwargs: {
        "available": True, "source": "coinset", "observed_at": 100,
        "raw": {"success": True, "estimates": [0], "full_node_synced": False},
    })
    quote = module.quote_fee(20_000_000)
    assert quote["available"] is False
    assert quote["fee_mojos"] is None
    assert quote["network_evidence"]["full_node_synced"] is False
