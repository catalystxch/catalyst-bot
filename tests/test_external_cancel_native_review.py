"""Native review must bind one external Sage proof before a local-only commit."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import external_cancel_recovery as recovery


REVIEW = {
    "intent_id": "a" * 64,
    "trade_id": "b" * 64,
    "wallet_fingerprint": 123,
    "wallet_fingerprint_hash": "c" * 64,
    "network": "mainnet",
    "asset_id": "d" * 64,
    "input_coin_id": "e" * 64,
    "return_coin_id": "f" * 64,
    "returned_amount_atomic": "24166667",
    "fee_mojos": "10000000",
    "confirmed_height": 9483977,
    "transaction_id": None,
    "spend_identity": "sha256:" + "1" * 64,
    "proof_digest": "2" * 64,
    "reviewed_at_epoch": 1000,
    "expires_at_epoch": 1300,
    "wallet_effect_started": False,
}


def test_native_external_review_rejects_unreviewed_and_changed_proof(monkeypatch):
    recovery._clear_pending_review_for_test()
    monkeypatch.setattr(recovery.time, "time", lambda: 1001)
    calls = []

    @contextmanager
    def exact_proof():
        calls.append("read")
        yield (
            dict(REVIEW),
            {"source": "exact"},
            {"intent_id": REVIEW["intent_id"]},
            "2026-10-26T15:26:22.000000Z",
        )

    monkeypatch.setattr(recovery, "_verified_external_proof", exact_proof)
    with pytest.raises(ValueError, match="not reviewed"):
        recovery.commit_external_cancellation(dict(REVIEW))
    shown = recovery.preview_external_cancellation()
    assert shown == REVIEW
    with pytest.raises(ValueError, match="changed"):
        recovery.commit_external_cancellation(REVIEW | {"fee_mojos": "1"})
    assert calls == ["read"]


def test_native_external_review_commits_once_without_wallet_effect(monkeypatch):
    recovery._clear_pending_review_for_test()
    monkeypatch.setattr(recovery.time, "time", lambda: 1001)
    reads = []

    @contextmanager
    def exact_proof():
        reads.append("read")
        proof = dict(REVIEW)
        if len(reads) == 2:
            proof["reviewed_at_epoch"] = 1001
            proof["expires_at_epoch"] = 1301
        yield (
            proof,
            {"source": "exact"},
            {"intent_id": REVIEW["intent_id"]},
            "2026-10-26T15:26:22.000000Z",
        )

    monkeypatch.setattr(recovery, "_verified_external_proof", exact_proof)
    monkeypatch.setattr(
        recovery,
        "_commit_local_proof",
        lambda intent_id, evidence, observed_at: {
            "applied": True,
            "idempotent": False,
            "classification": "CANCELLED_PROVEN",
            "wallet_effect_started": False,
        },
    )
    shown = recovery.preview_external_cancellation()
    result = recovery.commit_external_cancellation(shown)
    assert result["applied"] is True
    assert reads == ["read", "read"]
    with pytest.raises(ValueError, match="not reviewed"):
        recovery.commit_external_cancellation(shown)


def test_native_external_review_expires_before_confirmation(monkeypatch):
    recovery._clear_pending_review_for_test()
    monkeypatch.setattr(recovery.time, "time", lambda: 1000)

    @contextmanager
    def exact_proof():
        yield dict(REVIEW), {}, {}, "2026-10-26T15:26:22.000000Z"

    monkeypatch.setattr(recovery, "_verified_external_proof", exact_proof)
    shown = recovery.preview_external_cancellation()
    monkeypatch.setattr(recovery.time, "time", lambda: 1301)
    with pytest.raises(ValueError, match="expired"):
        recovery.commit_external_cancellation(shown)


def test_external_cancel_bridge_has_read_and_guarded_commit(monkeypatch):
    import app_bridge

    calls = []
    monkeypatch.setattr(
        recovery,
        "preview_external_cancellation",
        lambda: dict(REVIEW),
    )
    monkeypatch.setattr(
        recovery,
        "commit_external_cancellation",
        lambda reviewed: (
            calls.append(reviewed) or {"applied": True, "wallet_effect_started": False}
        ),
    )
    gate = SimpleNamespace(
        enter_mutation=lambda operation: calls.append(operation) or "permit",
        exit_mutation=lambda permit: calls.append(permit),
        MutationBlocked=type("MutationBlocked", (Exception,), {}),
    )
    monkeypatch.setattr(
        app_bridge,
        "_bridge_runtime_api",
        lambda _bridge: SimpleNamespace(
            wallet_setup_bootstrap_allows=lambda _operation: False,
            _ensure_mutation_runtime=lambda: None,
            mutation_gate=gate,
        ),
    )

    bridge = app_bridge.AppBridge()
    assert bridge.preview_external_cancellation() == {
        "success": True,
        "review": REVIEW,
    }
    assert bridge.commit_external_cancellation({"reviewed": REVIEW}) == {
        "success": True,
        "applied": True,
        "wallet_effect_started": False,
    }
    assert calls == [
        "app_bridge:commit_external_cancellation",
        REVIEW,
        "permit",
    ]
    assert "preview_external_cancellation" in app_bridge._APP_BRIDGE_READ_ONLY_METHODS
    assert "commit_external_cancellation" in app_bridge._APP_BRIDGE_MUTATION_METHODS


def test_native_external_proof_stops_before_sage_when_bot_is_running(monkeypatch):
    import api_server
    import mutation_gate
    import wallet

    class Authority:
        def status(self):
            return SimpleNamespace(
                to_dict=lambda: {
                    "allowed": True,
                    "lease": {"active": True, "owned_by_this_run": True},
                }
            )

        def require_wallet_identity_authority(self, _operation):
            return mutation_gate.WalletIdentityBinding(
                backend="sage",
                fingerprint=123,
                network_id="mainnet",
                kind="standard",
                has_secrets=True,
                name="Test Wallet",
                bound_at_utc="2026-10-26T15:00:00Z",
            )

    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: Authority())
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(is_running=lambda: True))
    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: pytest.fail("running bot must block Sage reads"),
    )
    with pytest.raises(ValueError, match="requires a stopped bot"):
        with recovery._verified_external_proof():
            pytest.fail("running bot must block a review")


def test_native_external_proof_fails_closed_on_wallet_identity_outage(monkeypatch):
    import api_server
    import database
    import mutation_gate
    import wallet
    from config import cfg

    asset = "d" * 64
    trade = "b" * 64
    wallet_hash = "c" * 64
    intent = {
        "intent_id": "a" * 64,
        "wallet_fingerprint_hash": wallet_hash,
        "network": "mainnet",
        "asset_id": asset,
        "lifecycle_state": "visible",
        "sage_trade_id": trade,
    }

    class Authority:
        wallet_fingerprint_hash = wallet_hash

        def status(self):
            return SimpleNamespace(
                to_dict=lambda: {
                    "allowed": True,
                    "lease": {"active": True, "owned_by_this_run": True},
                }
            )

        def require_wallet_identity_authority(self, _operation):
            return mutation_gate.WalletIdentityBinding(
                backend="sage",
                fingerprint=123,
                network_id="mainnet",
                kind="standard",
                has_secrets=True,
                name="Test Wallet",
                bound_at_utc="2026-10-26T15:00:00Z",
            )

    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: Authority())
    monkeypatch.setattr(cfg, "CAT_ASSET_ID", asset)
    monkeypatch.setattr(
        api_server,
        "bot",
        SimpleNamespace(
            is_running=lambda: False,
            offer_manager=SimpleNamespace(
                wait_for_offer_creation_quiescence=lambda: None
            ),
        ),
    )
    monkeypatch.setattr(
        database, "list_active_bootstrap_campaigns_for_asset", lambda _: []
    )
    monkeypatch.setattr(database, "get_offer_intents_for_registry", lambda: [intent])
    monkeypatch.setattr(
        database,
        "get_open_offers",
        lambda **_kwargs: [{"trade_id": trade}],
    )
    monkeypatch.setattr(database, "get_unresolved_offer_operation_blockers", lambda: [])
    monkeypatch.setattr(
        wallet, "get_wallet_identity", lambda: {"success": False, "error": "offline"}
    )
    monkeypatch.setattr(
        wallet,
        "get_wallet_sync_status",
        lambda: pytest.fail("identity outage must block further Sage reads"),
    )
    with pytest.raises(ValueError, match="wallet identity changed"):
        with recovery._verified_external_proof():
            pytest.fail("identity outage must block a review")
