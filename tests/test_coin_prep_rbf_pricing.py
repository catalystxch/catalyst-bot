"""Cost and mempool checks for unsigned fee-only replacement guidance."""

import coin_prep_rbf_pricing as pricing


OPERATION = "coin-prep:" + "1" * 64
TRANSACTION = "2" * 64
COST = 41_891_752


def _fake_network(monkeypatch, *, mempool_cost, mempool_max, quote_fee=15_000_000):
    built_fees = []

    def build(_operation, _transaction, fee):
        built_fees.append(fee)
        return {
            "success": True,
            "unsigned": {"_catalyst_exact_unsigned_cost": COST},
        }

    monkeypatch.setattr(pricing, "preview_coin_prep_rbf_unsigned", build)
    monkeypatch.setattr(
        pricing,
        "quote_fee",
        lambda cost, target_seconds, force_refresh: {
            "available": True,
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 123,
            "fee_mojos": quote_fee,
        },
    )
    monkeypatch.setattr(pricing, "is_current_fee_quote", lambda *_args: True)
    monkeypatch.setattr(
        pricing,
        "get_suggested_transaction_fee",
        lambda cost, target_seconds: {
            "available": True,
            "cost": cost,
            "target_seconds": target_seconds,
            "observed_at": 123,
            "raw": {
                "mempool_size": mempool_cost,
                "mempool_max_size": mempool_max,
            },
        },
    )
    return built_fees


def test_pricing_rebuilds_with_quote_headroom_when_candidate_fits(monkeypatch):
    built = _fake_network(
        monkeypatch, mempool_cost=109_000_000_000, mempool_max=110_000_000_000
    )
    result = pricing.price_pending_coin_prep_replacement(OPERATION, TRANSACTION)
    assert result["available"] is True
    assert result["fee_mojos"] == 16_500_000
    assert built == [10_000_000, 16_500_000]
    assert result["dispatch_authorized"] is False


def test_pricing_applies_full_mempool_cost_floor(monkeypatch):
    built = _fake_network(
        monkeypatch, mempool_cost=109_990_000_000, mempool_max=110_000_000_000
    )
    result = pricing.price_pending_coin_prep_replacement(OPERATION, TRANSACTION)
    assert result["available"] is True
    assert result["fee_mojos"] == 5 * COST + 1
    assert built == [10_000_000, 5 * COST + 1]


def test_pricing_refuses_when_capacity_provenance_is_missing(monkeypatch):
    built = _fake_network(monkeypatch, mempool_cost=None, mempool_max=None)
    result = pricing.price_pending_coin_prep_replacement(OPERATION, TRANSACTION)
    assert result == {"available": False, "reason": "RBF_MEMPOOL_CAPACITY_UNKNOWN"}
    assert built == [10_000_000]
