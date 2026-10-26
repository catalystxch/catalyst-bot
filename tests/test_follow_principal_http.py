"""Follow principal preview is read-only and uses exact atomic JSON strings."""

import api_server
import follow_principal


def _call(body):
    with api_server.app.test_request_context(
        "/api/follow/principal-preview", method="POST", json=body
    ):
        response = api_server.api_follow_principal_preview()
    if type(response) is tuple:
        return response[0].get_json(), response[1]
    return response.get_json(), response.status_code


def test_follow_principal_preview_requires_exact_approval_id(monkeypatch):
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda _id: (_ for _ in ()).throw(AssertionError("wallet read reached")),
    )
    body, status = _call({"approval_id": "bad"})
    assert status == 400
    assert body["reason"] == "FOLLOW_PRINCIPAL_REQUEST_INVALID"
    assert body["dispatch_authorized"] is False


def test_follow_principal_preview_returns_atomic_strings_without_authority(monkeypatch):
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda _id: {
            "maximum_trade_xch_mojos": 123_456_789_123_456,
            "maximum_trade_cat_atoms": 987_654_321_987_654,
            "protected_fee_principal_mojos": 50_000_000_000,
            "review_sha256": "b" * 64,
            "dispatch_authorized": False,
        },
    )
    body, status = _call({"approval_id": "a" * 64})
    assert status == 200
    assert body["success"] is True
    assert body["maximum_trade_xch_mojos"] == "123456789123456"
    assert body["maximum_trade_cat_atoms"] == "987654321987654"
    assert body["dispatch_authorized"] is False
