"""A native Follow review must still be current at the Start boundary."""

import hashlib
from types import SimpleNamespace

import api_server  # noqa: F401  # Registers the blueprint before importing it directly.
from blueprints import bot as routes


IDENTITY = {"network": "mainnet", "wallet_fingerprint": 123}
SCOPE = {
    "identity": IDENTITY,
    "configuration_sha256": "a" * 64,
    "follow_run_id": "b" * 64,
    "financial_consent_id": "c" * 64,
}
AUTHORITY = {
    "ready": True,
    "run_id": "b" * 64,
    "consent_id": "c" * 64,
    "approval_id": "d" * 64,
    "identity": IDENTITY,
    "configuration_sha256": "a" * 64,
    "principal_review_sha256": "e" * 64,
    "buy_limit": 24,
    "sell_limit": 24,
    "maximum_fee_mojos": 50_000_000_000,
    "protected_shutdown_fee_mojos": 1_000_000_000,
}
PROPOSAL = {
    "dispatch_authorized": False,
    "identity": IDENTITY,
    "configuration_sha256": "a" * 64,
    "proposal_sha256": "e" * 64,
    "maximum_fee_mojos": 50_000_000_000,
    "cancellation_reserve_mojos": 1_000_000_000,
    "replacement_count_gate_passed": True,
    "current_prep_targets_proven": True,
    "buy_slots_arithmetic_fit": 24,
    "sell_slots_arithmetic_fit": 24,
}
CFG = SimpleNamespace(
    LIQUIDITY_MODE="two_sided",
    MAX_ACTIVE_BUY_OFFERS=24,
    MAX_ACTIVE_SELL_OFFERS=24,
    CAT_ASSET_ID="f" * 64,
)


def _ready_sources(monkeypatch):
    import confidence_override
    import database
    import follow_principal

    monkeypatch.setattr(confidence_override, "current_scope", lambda: SCOPE)
    monkeypatch.setattr(
        database,
        "get_follow_creation_authority",
        lambda **_kwargs: AUTHORITY.copy(),
    )
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda *_args, **_kwargs: PROPOSAL.copy(),
    )
    monkeypatch.setattr(database, "get_open_offers", lambda **_kwargs: [])
    monkeypatch.setattr(database, "get_offer_intents_for_registry", lambda: [])


def test_two_sided_follow_start_requires_native_review(monkeypatch):
    import confidence_override

    monkeypatch.setattr(
        confidence_override,
        "current_scope",
        lambda: (_ for _ in ()).throw(ValueError("FOLLOW_FEE_AUTHORITY_REQUIRED")),
    )
    result = routes._reviewed_follow_start_readiness(CFG, resume_existing_offers=False)
    assert result == {"ready": False, "reason": "FOLLOW_REVIEW_REQUIRED"}


def test_two_sided_follow_start_reproves_principal_and_slots(monkeypatch):
    _ready_sources(monkeypatch)
    result = routes._reviewed_follow_start_readiness(CFG, resume_existing_offers=False)
    assert result == {"ready": True, "run_id": AUTHORITY["run_id"]}


def test_two_sided_follow_start_rejects_changed_inventory(monkeypatch):
    import follow_principal

    _ready_sources(monkeypatch)
    monkeypatch.setattr(
        follow_principal,
        "preview_approved_follow_principal",
        lambda *_args, **_kwargs: PROPOSAL | {"proposal_sha256": "f" * 64},
    )
    result = routes._reviewed_follow_start_readiness(CFG, resume_existing_offers=False)
    assert result == {"ready": False, "reason": "FOLLOW_REVIEW_CHANGED"}


def test_two_sided_follow_start_rejects_stale_local_offer(monkeypatch):
    import database

    _ready_sources(monkeypatch)
    monkeypatch.setattr(
        database,
        "get_open_offers",
        lambda **_kwargs: [{"trade_id": "e" * 64, "status": "open"}],
    )

    assert routes._reviewed_follow_start_readiness(
        CFG, resume_existing_offers=False
    ) == {"ready": False, "reason": "FOLLOW_LOCAL_OFFERS_UNRESOLVED"}


def test_two_sided_follow_start_rejects_unresolved_intent_without_offer_row(
    monkeypatch,
):
    import database

    _ready_sources(monkeypatch)
    wallet_hash = hashlib.sha256(b"fingerprint:123").hexdigest()
    monkeypatch.setattr(
        database,
        "get_offer_intents_for_registry",
        lambda: [
            {
                "wallet_fingerprint_hash": wallet_hash,
                "network": "mainnet",
                "asset_id": CFG.CAT_ASSET_ID,
                "lifecycle_state": "visible",
            }
        ],
    )

    assert routes._reviewed_follow_start_readiness(
        CFG, resume_existing_offers=False
    ) == {"ready": False, "reason": "FOLLOW_LOCAL_OFFERS_UNRESOLVED"}


def test_two_sided_follow_resume_needs_exact_book_review():
    assert routes._reviewed_follow_start_readiness(
        CFG, resume_existing_offers=True
    ) == {"ready": False, "reason": "FOLLOW_RESUME_REVIEW_REQUIRED"}
