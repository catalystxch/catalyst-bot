"""Exact Sage offer reads must remain usable after the wallet history grows."""

import wallet_sage


def test_exact_offer_set_reads_only_requested_cohort_after_history_cap(monkeypatch):
    first_id = "a" * 64
    second_id = "b" * 64
    calls = []

    def rpc(method, payload, timeout):
        calls.append((method, payload))
        assert method == "get_offer"
        assert set(payload) == {"offer_id"}
        assert payload["offer_id"] in {first_id, second_id}
        assert timeout <= 15
        return {
            "offer": {
                "offer_id": payload["offer_id"],
                "offer": "offer1private-payload",
                "status": "CANCELLED",
                "summary": {
                    "maker": [{"asset": {"asset_id": None}, "amount": 1000}],
                    "taker": [{"asset": {"asset_id": "c" * 64}, "amount": 500}],
                },
            }
        }

    monkeypatch.setattr(wallet_sage, "rpc", rpc)

    result = wallet_sage.get_authoritative_offers_by_ids((first_id, second_id))

    assert result["complete"] is True
    assert result["requested_ids"] == [first_id, second_id]
    assert [row["trade_id"] for row in result["offers"]] == [first_id, second_id]
    assert all("offer" not in row for row in result["offers"])
    assert all(row["summary"]["offered"] == {"xch": 1000} for row in result["offers"])
    assert len(calls) == 2


def test_exact_offer_set_rejects_mismatched_identity_and_transport_failure(monkeypatch):
    wanted = "d" * 64
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {"offer": {"offer_id": "e" * 64}},
    )
    assert wallet_sage.get_authoritative_offers_by_ids((wanted,))["complete"] is False

    monkeypatch.setattr(wallet_sage, "rpc", lambda *_args, **_kwargs: None)
    assert wallet_sage.get_authoritative_offers_by_ids((wanted,))["complete"] is False


def test_exact_offer_set_discards_partial_cohort_on_later_failure(monkeypatch):
    first_id = "a" * 64
    second_id = "b" * 64

    def rpc(_method, payload, _timeout):
        if payload["offer_id"] == first_id:
            return {
                "offer": {
                    "offer_id": first_id,
                    "status": "CANCELLED",
                    "summary": {"offered": {"xch": 1000}, "requested": {}},
                }
            }
        return {"success": False, "error": "missing offer"}

    monkeypatch.setattr(wallet_sage, "rpc", rpc)
    result = wallet_sage.get_authoritative_offers_by_ids((first_id, second_id))
    assert result["complete"] is False
    assert result["offers"] == []


def test_exact_offer_set_rejects_unbounded_or_duplicate_scope():
    import pytest

    with pytest.raises(ValueError):
        wallet_sage.get_authoritative_offers_by_ids(
            tuple(f"{index:064x}" for index in range(257))
        )
    with pytest.raises(ValueError):
        wallet_sage.get_authoritative_offers_by_ids(("a" * 64, "a" * 64))
