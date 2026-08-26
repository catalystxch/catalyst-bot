"""Regression coverage for upgrading legacy Sage offer reservations."""

from __future__ import annotations

import hashlib
import json
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

    database = SimpleNamespace(
        get_legacy_startup_reservation_candidates=lambda limit=128: [_candidate()],
        get_offer_intent=lambda intent_id: intents.get(intent_id),
        prepare_offer_intent=prepare_offer_intent,
        finalize_offer_intent=finalize_offer_intent,
    )
    evidence = {"wallet_identity": {"complete": True}, "observed_at": AT}
    reconciliation = SimpleNamespace(
        EXPIRED_PROVEN="EXPIRED_PROVEN",
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


def test_exact_sage_expiry_is_adopted_then_reconciled_through_task9():
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
        "finalize",
        "reconcile",
    ]
    prepared = calls[1][1]
    assert prepared["wallet_fingerprint_hash"] == WALLET_HASH
    assert prepared["network"] == "mainnet"
    assert prepared["asset_id"] == ASSET_ID
    assert prepared["offered_amount_atomic"] == "1250000000000"
    assert prepared["requested_amount_atomic"] == "12500000"
    assert prepared["selected_coin_ids_json"] == [COIN_ID[2:]]
    assert prepared["reserve_selected_coins"] is False


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
