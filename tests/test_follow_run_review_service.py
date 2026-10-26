"""Only a current server-derived 24/24 proposal may become a Follow review."""

import pytest


def _proposal():
    return {
        "identity": {
            "network": "mainnet",
            "wallet_type": "sage",
            "wallet_fingerprint": 123,
            "wallet_id": 2,
            "xch_wallet_id": 1,
            "asset_id": "a" * 64,
            "ticker": "MZ",
        },
        "configuration_sha256": "b" * 64,
        "proposal_sha256": "c" * 64,
        "buy_limit": 24,
        "sell_limit": 24,
        "replacement_count_gate_passed": True,
        "buy_slots_arithmetic_fit": 24,
        "sell_slots_arithmetic_fit": 24,
        "slot_assignment_sha256": "d" * 64,
        "current_prep_targets_proven": True,
        "maximum_trade_xch_mojos": 123_000_000_000_000,
        "maximum_trade_cat_atoms": 987_000_000,
        "maximum_fee_mojos": 50_000_000_000,
        "cancellation_reserve_mojos": 10_000_000_000,
        "shutdown_funding": {
            "ready": True,
            "full_book_proven": False,
            "dispatch_authorized": False,
        },
        "dispatch_authorized": False,
    }


def test_review_freezes_server_derived_24_by_24_proposal(monkeypatch):
    import database
    import follow_principal

    proposal = _proposal()
    calls = []
    monkeypatch.setattr(follow_principal.time, "time", lambda: 1_000_000)

    def preview(approval_id, *, buy_limit, sell_limit):
        calls.append((approval_id, buy_limit, sell_limit))
        return dict(proposal)

    def save(**terms):
        calls.append(terms)
        return {
            "review_id": "e" * 64,
            "review_sha256": "f" * 64,
            "dispatch_authorized": False,
        }

    monkeypatch.setattr(follow_principal, "preview_approved_follow_principal", preview)
    monkeypatch.setattr(database, "create_follow_run_review", save)
    result = follow_principal.prepare_follow_run_review(
        "1" * 64,
        buy_limit=24,
        sell_limit=24,
        duration_seconds=48 * 3600,
        requested_fee_cap_mojos=50_000_000_000,
    )
    assert calls[0] == calls[2] == ("1" * 64, 24, 24)
    assert calls[1] == {
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
    }
    assert result["proposal_sha256"] == proposal["proposal_sha256"]
    assert result["review_id"] == "e" * 64
    assert result["dispatch_authorized"] is False


def test_continuous_review_uses_explicit_nonexpiring_term(monkeypatch):
    import database
    import follow_principal
    from follow_run_terms import CONTINUOUS_RUN_EXPIRY

    monkeypatch.setattr(follow_principal.time, "time", lambda: 1_000_000)
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda *_a, **_kw: _proposal(),
    )
    captured = {}
    monkeypatch.setattr(
        database,
        "create_follow_run_review",
        lambda **terms: captured.update(terms) or {"review_id": "e" * 64},
    )
    result = follow_principal.prepare_follow_run_review(
        "1" * 64,
        buy_limit=24,
        sell_limit=24,
        duration_seconds=None,
        continuous=True,
        requested_fee_cap_mojos=50_000_000_000,
    )
    assert captured["expires_at_epoch"] == CONTINUOUS_RUN_EXPIRY
    assert captured["continuous"] is True
    assert result["continuous"] is True
    assert result["review_expires_at_epoch"] == 1_000_300


@pytest.mark.parametrize(
    "change",
    [
        {"maximum_fee_mojos": 50_000_000_001},
        {"replacement_count_gate_passed": False},
        {"sell_slots_arithmetic_fit": 23},
        {"dispatch_authorized": True},
        {"cancellation_reserve_mojos": 0},
        {"slot_assignment_sha256": None},
        {"shutdown_funding": {"ready": False}},
    ],
)
def test_review_rejects_incomplete_or_inexact_proposal(monkeypatch, change):
    import database
    import follow_principal

    proposal = _proposal() | change
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda *_a, **_kw: proposal,
    )
    monkeypatch.setattr(
        database,
        "create_follow_run_review",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("review persisted")),
    )
    with pytest.raises(ValueError, match="FOLLOW_REVIEW_PROPOSAL_INVALID"):
        follow_principal.prepare_follow_run_review(
            "1" * 64,
            buy_limit=24,
            sell_limit=24,
            duration_seconds=48 * 3600,
            requested_fee_cap_mojos=50_000_000_000,
        )


def test_review_rejects_proposal_drift_after_persistence(monkeypatch):
    import database
    import follow_principal

    proposal = _proposal()
    reads = iter((proposal, proposal | {"proposal_sha256": "9" * 64}))
    monkeypatch.setattr(follow_principal.time, "time", lambda: 1_000_000)
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda *_a, **_kw: next(reads),
    )
    monkeypatch.setattr(
        database,
        "create_follow_run_review",
        lambda **_kw: {"review_id": "e" * 64, "review_sha256": "f" * 64},
    )
    with pytest.raises(ValueError, match="FOLLOW_REVIEW_PROPOSAL_CHANGED"):
        follow_principal.prepare_follow_run_review(
            "1" * 64,
            buy_limit=24,
            sell_limit=24,
            duration_seconds=48 * 3600,
            requested_fee_cap_mojos=50_000_000_000,
        )


def test_review_names_insufficient_fee_coin_before_persisting(monkeypatch):
    import database
    import follow_principal

    proposal = _proposal() | {
        "shutdown_funding": {
            "ready": False,
            "reason": "FOLLOW_SHUTDOWN_FEE_COIN_TOO_SMALL",
            "full_book_proven": False,
            "dispatch_authorized": False,
        }
    }
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda *_a, **_kw: proposal,
    )
    monkeypatch.setattr(
        database,
        "create_follow_run_review",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("review persisted")),
    )
    with pytest.raises(ValueError, match="FOLLOW_SHUTDOWN_FEE_COIN_TOO_SMALL"):
        follow_principal.prepare_follow_run_review(
            "1" * 64,
            buy_limit=24,
            sell_limit=24,
            duration_seconds=None,
            continuous=True,
            requested_fee_cap_mojos=50_000_000_000,
        )
