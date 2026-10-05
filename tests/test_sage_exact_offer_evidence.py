"""Exact Sage offer reads must remain usable after the wallet history grows."""

import wallet_sage
import pytest


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
    with pytest.raises(ValueError):
        wallet_sage.get_authoritative_offers_by_ids(
            tuple(f"{index:064x}" for index in range(257))
        )
    with pytest.raises(ValueError):
        wallet_sage.get_authoritative_offers_by_ids(("a" * 64, "a" * 64))


@pytest.mark.parametrize(
    ("body", "path", "requested_id", "expected"),
    [
        (lambda wanted: f"Missing offer: {wanted}", "get_offer", "a" * 64, True),
        (lambda wanted: f"Missing offer: {wanted}", "get_offer", "b" * 64, True),
        (lambda wanted: f"Missing offer: {wanted}", "other_endpoint", "a" * 64, False),
        (lambda wanted: f"Missing offer: {'b' * 64}", "get_offer", "a" * 64, False),
        (lambda wanted: f"Missing offer: {wanted} extra", "get_offer", "a" * 64, False),
        (lambda _wanted: "Not Found", "get_offer", "a" * 64, False),
    ],
)
def test_only_exact_sage_missing_offer_404_has_absence_code(
    monkeypatch, body, path, requested_id, expected
):
    class FakeResponse:
        status = 404

        def read(self):
            return body(requested_id).encode()

    class FakeConnection:
        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return FakeResponse()

    monkeypatch.setattr(
        wallet_sage, "_get_sage_connection", lambda _timeout: FakeConnection()
    )
    with pytest.raises(wallet_sage._SageRPCFailure) as caught:
        wallet_sage._sage_post(path, {"offer_id": requested_id})
    assert (caught.value.error_code == "SAGE_OFFER_NOT_FOUND") is expected


def test_exact_absence_reader_requires_every_id_and_rejects_generic_404(monkeypatch):
    ids = ("a" * 64, "b" * 64)
    seen = []

    def missing(_method, payload, timeout):
        assert timeout == 10
        seen.append(payload["offer_id"])
        return {
            "success": False,
            "error_code": "SAGE_OFFER_NOT_FOUND",
            "endpoint": "get_offer",
            "http_status": 404,
        }

    monkeypatch.setattr(wallet_sage, "rpc", missing)
    result = wallet_sage.get_authoritative_offer_absence_by_ids(ids)
    assert result["complete"] is True
    assert result["absent_offer_ids"] == list(ids)
    assert seen == list(ids)

    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {
            "success": False,
            "error_code": "SAGE_HTTP_ERROR",
            "endpoint": "get_offer",
            "http_status": 404,
        },
    )
    denied = wallet_sage.get_authoritative_offer_absence_by_ids(ids)
    assert denied["complete"] is False
    assert denied["absent_offer_ids"] == []


def test_exact_absence_reader_uses_real_transport_discriminator(monkeypatch):
    wanted = "d" * 64

    class FakeResponse:
        status = 404

        def read(self):
            return f"Missing offer: {wanted}".encode()

    class FakeConnection:
        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return FakeResponse()

    monkeypatch.setattr(
        wallet_sage, "_get_sage_connection", lambda _timeout: FakeConnection()
    )
    monkeypatch.setattr(wallet_sage, "_emit_sage_diagnostic", lambda *_args: None)
    result = wallet_sage.get_authoritative_offer_absence_by_ids((wanted,))
    assert result == {
        "complete": True,
        "requested_ids": [wanted],
        "absent_offer_ids": [wanted],
        "read_error": None,
    }
