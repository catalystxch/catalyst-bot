"""Regression coverage for upgrading legacy Sage offer reservations."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace


TRADE_ID = "1" * 64
COIN_ID = "0x" + "2" * 64
ASSET_ID = "3" * 64
WALLET_HASH = hashlib.sha256(b"fingerprint:736588221").hexdigest()
AT = "2026-08-26T03:45:00.000000Z"


def _candidate() -> dict:
    return {
        "trade_id": TRADE_ID,
        "side": "buy",
        "size_xch": "1.25",
        "size_cat": "12500",
        "tier": "outer",
        "created_at": "2026-07-16 07:37:51",
        "cat_asset_id": ASSET_ID,
        "coin_id": COIN_ID,
        "offer_bech32": "offer1legacy-proof",
        "fee_mojos_xch": 0,
        "coin_purpose": None,
    }


def _modules(classification: str = "EXPIRED_PROVEN"):
    calls = []
    intents = {}

    def prepare_offer_intent(**kwargs):
        calls.append(("prepare", kwargs))
        intents[kwargs["intent_id"]] = {
            **kwargs,
            "lifecycle_state": "prepared",
            "prepared_at": kwargs["prepared_at"],
            "selected_coin_ids_json": json.dumps([COIN_ID[2:]]),
        }
        return intents[kwargs["intent_id"]]

    def finalize_offer_intent(**kwargs):
        calls.append(("finalize", kwargs))
        intent = intents[kwargs["intent_id"]]
        intent.update(
            {
                "lifecycle_state": "created",
                "sage_trade_id": kwargs["sage_trade_id"],
                "offer_text_sha256": kwargs["offer_text_sha256"],
                "confirmed_at": kwargs["finalized_at"],
            }
        )
        return intent

    def commit_legacy_expired_offer_intent(**kwargs):
        calls.append(("commit_legacy_terminal", kwargs))
        intents[kwargs["intent_id"]] = {
            **kwargs,
            "lifecycle_state": "terminal",
            "sage_trade_id": kwargs["sage_trade_id"],
        }
        return {"event": {"outcome": "EXPIRED_PROVEN"}, "idempotent": False}

    database = SimpleNamespace(
        get_legacy_startup_reservation_candidates=lambda limit=128: [_candidate()],
        get_offer_intent=lambda intent_id: intents.get(intent_id),
        prepare_offer_intent=prepare_offer_intent,
        finalize_offer_intent=finalize_offer_intent,
        commit_legacy_expired_offer_intent=commit_legacy_expired_offer_intent,
    )
    evidence = {"wallet_identity": {"complete": True}, "observed_at": AT}
    reconciliation = SimpleNamespace(
        EXPIRED_PROVEN="EXPIRED_PROVEN",
        canonical_evidence_and_digest=lambda value, max_bytes=65536: (
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            hashlib.sha256(
                json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        ),
        load_authoritative_evidence=lambda intent, wallet_facade=None: (
            calls.append(("evidence", intent, wallet_facade)) or evidence
        ),
        classify_terminal_evidence=lambda intent, supplied, now=None: {
            "classification": classification,
            "reason_code": "AUTHORITATIVE_EXPIRY_PROOF",
        },
        reconcile_offer=lambda intent_id, evidence=None, now=None: (
            calls.append(("reconcile", intent_id, evidence, now))
            or {
                "classification": classification,
                "applied": classification == "EXPIRED_PROVEN",
            }
        ),
    )
    return database, reconciliation, calls


def test_exact_sage_expiry_is_adopted_terminally_without_publishable_state():
    import legacy_startup_recovery

    database, reconciliation, calls = _modules()
    wallet = SimpleNamespace()
    cfg = SimpleNamespace(CAT_DECIMALS=3)

    result = legacy_startup_recovery.recover_legacy_sage_reservations(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        wallet_facade=wallet,
        database_module=database,
        reconciliation_module=reconciliation,
        config=cfg,
    )

    assert result == {"examined": 1, "recovered": 1, "remaining": 0}
    assert [call[0] for call in calls] == [
        "evidence",
        "prepare",
        "commit_legacy_terminal",
    ]
    committed = calls[2][1]
    assert committed["wallet_fingerprint_hash"] == WALLET_HASH
    assert committed["network"] == "mainnet"
    assert committed["classification"] == "EXPIRED_PROVEN"
    prepared = calls[1][1]
    assert prepared["asset_id"] == ASSET_ID
    assert prepared["offered_amount_atomic"] == "1250000000000"
    assert prepared["requested_amount_atomic"] == "12500000"
    assert prepared["selected_coin_ids_json"] == [COIN_ID[2:]]


def test_nonexpired_legacy_reservation_remains_blocked_without_writes():
    import legacy_startup_recovery

    database, reconciliation, calls = _modules("ACTIVE_PROVEN")

    result = legacy_startup_recovery.recover_legacy_sage_reservations(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        wallet_facade=SimpleNamespace(),
        database_module=database,
        reconciliation_module=reconciliation,
        config=SimpleNamespace(CAT_DECIMALS=3),
    )

    assert result == {"examined": 1, "recovered": 0, "remaining": 1}
    assert [call[0] for call in calls] == ["evidence"]


def test_many_legacy_candidates_share_bounded_wallet_history_reads():
    """Repairing a large old ladder must not reload all Sage history per row."""
    import legacy_startup_recovery

    candidates = [
        {
            **_candidate(),
            "trade_id": f"{index + 1:064x}",
            "coin_id": "0x" + f"{index + 1000:064x}",
        }
        for index in range(72)
    ]
    database = SimpleNamespace(
        get_legacy_startup_reservation_candidates=lambda limit=128: candidates,
        get_offer_intent=lambda _intent_id: None,
    )
    wallet_calls = {"identity": 0, "offers": 0, "coins": 0}

    class Wallet:
        @staticmethod
        def get_wallet_identity():
            wallet_calls["identity"] += 1
            return {"success": True}

        @staticmethod
        def get_authoritative_offer_history(**_kwargs):
            wallet_calls["offers"] += 1
            return {"success": True, "offers": []}

        @staticmethod
        def get_coins_by_ids(coin_ids):
            wallet_calls["coins"] += 1
            return {
                "success": True,
                "records": {
                    coin_id.removeprefix("0x"): {
                        "coin_id": coin_id.removeprefix("0x"),
                        "amount": 1,
                    }
                    for coin_id in coin_ids
                },
            }

    def load_evidence(_intent, wallet_facade=None):
        wallet_facade.get_wallet_identity()
        wallet_facade.get_authoritative_offer_history(
            include_completed=True,
            start=0,
            end=50,
        )
        wallet_facade.get_coins_by_ids([_intent["selected_coin_ids"][0]])
        return {"observed_at": AT}

    reconciliation = SimpleNamespace(
        EXPIRED_PROVEN="EXPIRED_PROVEN",
        load_authoritative_evidence=load_evidence,
        classify_terminal_evidence=lambda *_args, **_kwargs: {
            "classification": "ACTIVE_PROVEN"
        },
    )

    result = legacy_startup_recovery.recover_legacy_sage_reservations(
        wallet_fingerprint_hash=WALLET_HASH,
        network="mainnet",
        wallet_facade=Wallet(),
        database_module=database,
        reconciliation_module=reconciliation,
        config=SimpleNamespace(CAT_DECIMALS=3),
    )

    assert result == {"examined": 72, "recovered": 0, "remaining": 72}
    assert wallet_calls == {"identity": 1, "offers": 1, "coins": 1}


def test_database_legacy_adoption_never_commits_publishable_state(
    tmp_path, monkeypatch
):
    import database
    import offer_reconciliation

    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "legacy-atomic.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    coin_id = COIN_ID[2:]
    intent_id = f"legacy-startup:{TRADE_ID}"
    try:
        assert database.upsert_coin(coin_id, "xch", 1_250_000_000_000)
        assert database.add_offer(
            TRADE_ID,
            "buy",
            Decimal("0.0001"),
            Decimal("1.25"),
            Decimal("12500"),
            ASSET_ID,
            tier="outer",
            coin_id=coin_id,
        )
        assert database.lock_coin(coin_id, TRADE_ID)
        database.prepare_offer_intent(
            intent_id=intent_id,
            operation_id=f"create:{intent_id}",
            event_id=f"create:{intent_id}:prepared",
            run_id="legacy-startup-test",
            wallet_fingerprint_hash=WALLET_HASH,
            network="mainnet",
            asset_id=ASSET_ID,
            side="buy",
            tier="outer",
            purpose="legacy_startup_migration",
            offered_amount_atomic="1250000000000",
            requested_amount_atomic="12500000",
            selected_coin_ids_json=[coin_id],
            cat_decimals=3,
            fee_mojos_xch=0,
            fee_provenance="LEGACY_OFFER_PROJECTION_V1",
            wallet_identity_json={
                "wallet_fingerprint_hash": WALLET_HASH,
                "network": "mainnet",
            },
            evidence_json={"migration": "legacy_startup_expiry"},
            prepared_at=AT,
            reserve_selected_coins=False,
            require_new_intent=False,
        )
        proof_json, proof_sha256 = offer_reconciliation.canonical_evidence_and_digest(
            {
                "classification": {
                    "classification": "EXPIRED_PROVEN",
                    "reason_code": "AUTHORITATIVE_EXPIRY_PROOF",
                },
                "evidence": {"observed_at": AT, "wallet_identity": {"complete": True}},
            }
        )

        committed = database.commit_legacy_expired_offer_intent(
            intent_id=intent_id,
            sage_trade_id=TRADE_ID,
            offer_text_sha256=hashlib.sha256(b"offer1legacy-proof").hexdigest(),
            wallet_fingerprint_hash=WALLET_HASH,
            network="mainnet",
            classification="EXPIRED_PROVEN",
            reason_code="AUTHORITATIVE_EXPIRY_PROOF",
            wallet_identity_json={
                "wallet_fingerprint_hash": WALLET_HASH,
                "network": "mainnet",
            },
            evidence_json=proof_json,
            evidence_sha256=proof_sha256,
            confirmed_at=AT,
            reconciled_at=AT,
        )

        assert committed["event"]["outcome"] == "EXPIRED_PROVEN"
        assert database.get_offer_intent(intent_id)["lifecycle_state"] == "terminal"
        conn = database.get_connection()
        assert (
            conn.execute(
                "SELECT status FROM offers WHERE trade_id=?", (TRADE_ID,)
            ).fetchone()["status"]
            == "expired"
        )
        assert database.get_coin_state(coin_id)["status"] == "free"
        states = {
            row["state"]
            for row in conn.execute(
                "SELECT state FROM publication_outbox WHERE intent_id=?", (intent_id,)
            ).fetchall()
        }
        assert states == {"suppressed"}
        assert (
            conn.execute(
                "SELECT COUNT(*) AS total FROM publication_outbox "
                "WHERE intent_id=? AND state<>'suppressed'",
                (intent_id,),
            ).fetchone()["total"]
            == 0
        )
    finally:
        database.close_connection()
