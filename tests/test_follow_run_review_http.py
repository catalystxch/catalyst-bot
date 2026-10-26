"""A Follow review route can persist display terms but cannot grant effects."""

import api_server
import follow_principal


def _call(body):
    with api_server.app.test_request_context(
        "/api/follow/run-review", method="POST", json=body
    ):
        response = api_server.api_follow_run_review()
    if type(response) is tuple:
        return response[0].get_json(), response[1]
    return response.get_json(), response.status_code


def test_follow_review_accepts_only_explicit_public_run_terms(monkeypatch):
    calls = []
    monkeypatch.setattr(
        follow_principal,
        "prepare_follow_run_review",
        lambda approval_id, **terms: (
            calls.append((approval_id, terms))
            or {
                "review_id": "b" * 64,
                "maximum_trade_xch_mojos": 123_456_789_123_456,
                "dispatch_authorized": False,
            }
        ),
    )
    body, status = _call(
        {
            "approval_id": "a" * 64,
            "buy_limit": 24,
            "sell_limit": 24,
            "duration_seconds": 48 * 3600,
            "maximum_fee_mojos": 50_000_000_000,
        }
    )
    assert status == 200
    assert calls == [
        (
            "a" * 64,
            {
                "buy_limit": 24,
                "sell_limit": 24,
                "duration_seconds": 48 * 3600,
                "requested_fee_cap_mojos": 50_000_000_000,
            },
        )
    ]
    assert body["maximum_trade_xch_mojos"] == "123456789123456"
    assert body["dispatch_authorized"] is False


def test_follow_review_rejects_missing_or_coerced_terms_before_service(monkeypatch):
    monkeypatch.setattr(
        follow_principal,
        "prepare_follow_run_review",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("service reached")),
    )
    for body in (
        {"approval_id": "a" * 64, "buy_limit": 24},
        {
            "approval_id": "a" * 64,
            "buy_limit": True,
            "sell_limit": 24,
            "duration_seconds": 48 * 3600,
            "maximum_fee_mojos": 50_000_000_000,
        },
        {
            "approval_id": "a" * 64,
            "buy_limit": 24,
            "sell_limit": 24,
            "duration_seconds": 48 * 3600,
            "maximum_fee_mojos": "50000000000",
        },
    ):
        result, status = _call(body)
        assert status == 400
        assert result["reason"] == "FOLLOW_REVIEW_REQUEST_INVALID"
        assert result["dispatch_authorized"] is False
