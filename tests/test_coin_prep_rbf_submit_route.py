"""The recovery form requires exact visible consent before wallet dispatch."""

import wallet


ATTEMPT = "a" * 64
DIGEST = "b" * 64
OPERATION = "coin-prep:" + "c" * 64


def test_submit_route_rejects_digest_change_before_wallet_call(monkeypatch):
    import api_server
    import database

    monkeypatch.setattr(
        api_server, "_coin_prep_rbf_owned_review_snapshot",
        lambda: {"operation_id": OPERATION},
    )
    monkeypatch.setattr(
        database,
        "get_coin_prep_rbf_attempt_for_submit",
        lambda _id: {"operation_id": OPERATION, "review_sha256": DIGEST,
                     "fee_mojos": 20_000_000},
    )
    monkeypatch.setattr(
        wallet, "submit_reviewed_coin_prep_rbf",
        lambda _id: (_ for _ in ()).throw(AssertionError("wallet called")),
    )
    with api_server.app.test_request_context(
        "/api/safety/coin-prep-recovery-submit", method="POST",
        data={"attempt_id": ATTEMPT, "review_digest": "d" * 64,
              "confirmed": "on"},
    ):
        response = api_server.api_coin_prep_recovery_submit()
    assert response[1] == 409


def test_submit_route_calls_wallet_once_after_exact_consent(monkeypatch):
    import api_server
    import database

    calls = []
    monkeypatch.setattr(
        api_server, "_coin_prep_rbf_owned_review_snapshot",
        lambda: {"operation_id": OPERATION},
    )
    monkeypatch.setattr(
        database,
        "get_coin_prep_rbf_attempt_for_submit",
        lambda _id: {"operation_id": OPERATION, "review_sha256": DIGEST,
                     "fee_mojos": 20_000_000},
    )
    monkeypatch.setattr(
        wallet,
        "submit_reviewed_coin_prep_rbf",
        lambda attempt: calls.append(attempt) or {
            "success": True, "_catalyst_effect_attempted": True
        },
    )
    with api_server.app.test_request_context(
        "/api/safety/coin-prep-recovery-submit", method="POST",
        data={"attempt_id": ATTEMPT, "review_digest": DIGEST,
              "confirmed": "on"},
    ):
        response = api_server.api_coin_prep_recovery_submit()
    assert response.status_code == 202
    assert b"Trading remains paused" in response.data
    assert calls == [ATTEMPT]
