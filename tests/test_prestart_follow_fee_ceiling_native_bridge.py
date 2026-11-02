"""The pre-start cap final click exists only in the native bridge."""

from types import SimpleNamespace


def _method(name):
    from app_bridge import AppBridge

    method = getattr(AppBridge, name)
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def test_prestart_bridge_requires_closed_native_review_terms(monkeypatch):
    import prestart_follow_fee_ceiling as service

    seen = []
    monkeypatch.setattr(
        service,
        "preview_prestart_follow_fee_ceiling",
        lambda approval, maximum: (
            seen.append((approval, maximum))
            or {
                "preview_id": "b" * 64,
                "proposed_maximum_fee_mojos": maximum,
                "dispatch_authorized": False,
            }
        ),
    )
    method = _method("prepare_prestart_follow_fee_ceiling_review")
    for body in (
        {"approval_id": "a" * 64, "proposed_maximum_fee_mojos": True},
        {
            "approval_id": "a" * 64,
            "proposed_maximum_fee_mojos": 5_000_000_000,
            "wallet_fingerprint": 123,
        },
    ):
        assert method(SimpleNamespace(), body)["success"] is False
    result = method(
        SimpleNamespace(),
        {
            "approval_id": "a" * 64,
            "proposed_maximum_fee_mojos": 5_000_000_000,
        },
    )
    assert result["success"] is True
    assert result["dispatch_authorized"] is False
    assert seen == [("a" * 64, 5_000_000_000)]


def test_prestart_bridge_final_requires_explicit_acceptance(monkeypatch):
    import prestart_follow_fee_ceiling as service

    seen = []
    monkeypatch.setattr(
        service,
        "confirm_prestart_follow_fee_ceiling",
        lambda preview, digest: (
            seen.append((preview, digest))
            or {
                "approval_id": "c" * 64,
                "dispatch_authorized": False,
            }
        ),
    )
    method = _method("confirm_prestart_follow_fee_ceiling_review")
    rejected = method(
        SimpleNamespace(),
        {
            "preview_id": "a" * 64,
            "review_sha256": "b" * 64,
            "accepted": False,
        },
    )
    assert rejected["success"] is False
    assert seen == []
    confirmed = method(
        SimpleNamespace(),
        {
            "preview_id": "a" * 64,
            "review_sha256": "b" * 64,
            "accepted": True,
        },
    )
    assert confirmed["success"] is True
    assert confirmed["dispatch_authorized"] is False
    assert seen == [("a" * 64, "b" * 64)]
