import socket

import pytest

from cancel_outcomes import (
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    CANCEL_UNKNOWN,
    cancellation_result,
    validate_cancel_result,
)
import wallet_chia


@pytest.fixture(autouse=True)
def _fail_closed_network_guard(monkeypatch):
    attempts = []

    def blocked(*_args, **_kwargs):
        attempts.append("socket")
        raise AssertionError("network access is forbidden in Task 8 tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"success": True}, CANCEL_UNKNOWN),
        (
            {"success": True, "transaction_id": "1" * 64},
            CANCEL_SUBMITTED_UNCONFIRMED,
        ),
        ({"success": False, "error": "rejected"}, CANCEL_FAILED),
        (None, CANCEL_UNKNOWN),
    ],
)
def test_chia_cancel_offer_returns_exact_typed_outcome(
    monkeypatch,
    raw,
    expected,
):
    checks = []
    monkeypatch.setattr(wallet_chia, "rpc", lambda *_args, **_kwargs: raw)

    result = wallet_chia.cancel_offer(
        "a" * 64,
        secure=False,
        _identity_recheck=lambda step: checks.append(step),
    )

    assert result["outcome"] == expected
    assert checks == ["cancel_offer"]
    validate_cancel_result(result)


def test_chia_cancel_offer_exception_after_effect_boundary_is_unknown(monkeypatch):
    checks = []

    def explode(*_args, **_kwargs):
        raise ConnectionError("response lost")

    monkeypatch.setattr(wallet_chia, "rpc", explode)
    result = wallet_chia.cancel_offer(
        "a" * 64,
        secure=False,
        _identity_recheck=lambda step: checks.append(step),
    )

    assert result["outcome"] == CANCEL_UNKNOWN
    assert checks == ["cancel_offer"]
    validate_cancel_result(result)


def test_chia_cancel_offer_hostile_mapping_after_effect_boundary_is_unknown(
    monkeypatch,
):
    class HostileMapping(dict):
        def get(self, *_args, **_kwargs):
            raise AssertionError("hostile mapping accessor")

    monkeypatch.setattr(
        wallet_chia,
        "rpc",
        lambda *_args, **_kwargs: HostileMapping(success=True),
    )

    result = wallet_chia.cancel_offer(
        "a" * 64,
        secure=False,
        _identity_recheck=lambda _step: None,
    )

    assert result["outcome"] == CANCEL_UNKNOWN
    validate_cancel_result(result)


def test_chia_cancel_batch_normalizes_every_member_without_alias_success(monkeypatch):
    submitted = cancellation_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        method="single_rpc",
        raw_response={"success": True, "transaction_id": "2" * 64},
        transaction_id="2" * 64,
    )
    responses = iter(
        [
            submitted,
            {"success": True},
            {"success": False, "error": "not found"},
        ]
    )
    monkeypatch.setattr(
        wallet_chia,
        "cancel_offer",
        lambda *_args, **_kwargs: next(responses),
    )
    monkeypatch.setattr(wallet_chia.time, "sleep", lambda _seconds: None)
    trade_ids = ["a" * 64, "b" * 64, "c" * 64]

    results = wallet_chia.cancel_offers_batch(trade_ids, secure=False)

    assert [results[trade_id]["outcome"] for trade_id in trade_ids] == [
        CANCEL_SUBMITTED_UNCONFIRMED,
        CANCEL_UNKNOWN,
        CANCEL_FAILED,
    ]
    for result in results.values():
        validate_cancel_result(result)
