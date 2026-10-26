"""Native Follow consent consumes only the current displayed review."""

from threading import RLock
from types import SimpleNamespace

import pytest

from test_follow_run_review_service import _proposal


def _review():
    proposal = _proposal()
    return {
        "review_id": "e" * 64,
        "review_sha256": "f" * 64,
        "approval_id": "1" * 64,
        "identity": proposal["identity"],
        "configuration_sha256": proposal["configuration_sha256"],
        "principal_review_sha256": proposal["proposal_sha256"],
        "buy_limit": 24,
        "sell_limit": 24,
        "started_at_epoch": 1_000_000,
        "expires_at_epoch": 1_000_000 + 48 * 3600,
        "maximum_fee_mojos": 50_000_000_000,
        "protected_shutdown_fee_mojos": 10_000_000_000,
        "review_expires_at_epoch": 1_000_300,
        "consumed": False,
        "dispatch_authorized": False,
    }


def _setup(monkeypatch, *, running=False, review=None, proposal=None):
    import api_server
    import database
    import follow_principal

    saved = []
    review = _review() if review is None else review
    proposal = _proposal() if proposal is None else proposal
    monkeypatch.setattr(follow_principal.time, "time", lambda: 1_000_030)
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(is_running=lambda: running))
    monkeypatch.setattr(api_server, "_bot_cancel_lifecycle_lock", RLock())
    monkeypatch.setattr(api_server, "_cancel_all_state_lock", RLock())
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": False})
    monkeypatch.setattr(api_server, "_cancel_all_thread", None)
    monkeypatch.setattr(database, "get_follow_run_review", lambda _id: review)
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda _id, **_kw: proposal,
    )
    monkeypatch.setattr(
        database,
        "create_follow_run_authority",
        lambda **terms: (
            saved.append(terms)
            or {
                "run_id": "a" * 64,
                "dispatch_authorized": False,
            }
        ),
    )
    return saved


def test_native_confirmation_rechecks_and_consumes_exact_review(monkeypatch):
    import follow_principal

    saved = _setup(monkeypatch)
    result = follow_principal.confirm_follow_run_review("e" * 64, "f" * 64)
    assert saved == [
        {
            "consent_id": "e" * 64,
            "review_sha256": "f" * 64,
            "approval_id": "1" * 64,
            "identity": _proposal()["identity"],
            "configuration_sha256": "b" * 64,
            "principal_review_sha256": "c" * 64,
            "buy_limit": 24,
            "sell_limit": 24,
            "started_at_epoch": 1_000_000,
            "expires_at_epoch": 1_000_000 + 48 * 3600,
            "maximum_fee_mojos": 50_000_000_000,
            "protected_shutdown_fee_mojos": 10_000_000_000,
        }
    ]
    assert result["run_id"] == "a" * 64
    assert result["dispatch_authorized"] is False


def test_native_bridge_requires_explicit_acceptance_and_forwards_only_review_ids(
    monkeypatch,
):
    import follow_principal
    from app_bridge import AppBridge

    calls = []
    monkeypatch.setattr(
        follow_principal,
        "confirm_follow_run_review",
        lambda *args: (
            calls.append(args)
            or {
                "run_id": "a" * 64,
                "dispatch_authorized": False,
            }
        ),
    )
    method = AppBridge.confirm_follow_run_review
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    result = method(
        SimpleNamespace(),
        {"review_id": "e" * 64, "review_sha256": "f" * 64, "accepted": True},
    )
    assert result["success"] is True
    assert result["dispatch_authorized"] is False
    assert calls == [("e" * 64, "f" * 64)]
    rejected = method(
        SimpleNamespace(),
        {"review_id": "e" * 64, "review_sha256": "f" * 64, "accepted": False},
    )
    assert rejected["success"] is False
    assert calls == [("e" * 64, "f" * 64)]


@pytest.mark.parametrize(
    "review_change,proposal_change,running,reason",
    [
        ({"consumed": True}, {}, False, "FOLLOW_REVIEW_USED"),
        ({"review_expires_at_epoch": 1_000_030}, {}, False, "FOLLOW_REVIEW_EXPIRED"),
        ({"review_sha256": "9" * 64}, {}, False, "FOLLOW_REVIEW_CHANGED"),
        ({}, {"proposal_sha256": "9" * 64}, False, "FOLLOW_REVIEW_CHANGED"),
        ({}, {"maximum_fee_mojos": 49_000_000_000}, False, "FOLLOW_REVIEW_CHANGED"),
        ({}, {}, True, "FOLLOW_BOT_MUST_BE_STOPPED"),
    ],
)
def test_native_confirmation_fails_closed_before_authority(
    monkeypatch, review_change, proposal_change, running, reason
):
    import follow_principal

    saved = _setup(
        monkeypatch,
        running=running,
        review=_review() | review_change,
        proposal=_proposal() | proposal_change,
    )
    with pytest.raises(ValueError, match=reason):
        follow_principal.confirm_follow_run_review("e" * 64, "f" * 64)
    assert saved == []
