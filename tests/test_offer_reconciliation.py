"""Authoritative, proof-bound terminal offer reconciliation tests.

These tests deliberately install a socket guard as well as relying on the
process-level guard used by the Task 9 verification commands.  Every evidence
reader is deterministic and local.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
import sys
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import bot_health
import bot_loop
import database
from offer_registry import AuthorizationCode, AuthorizationDecision
from offer_reconciliation import (
    ACTIVE_PROVEN,
    CANCELLED_PROVEN,
    CONFLICT,
    EXPIRED_PROVEN,
    FILLED_PROVEN,
    UNKNOWN,
    canonical_evidence_and_digest,
    classify_terminal_evidence,
    load_authoritative_evidence,
    load_sage_offer_history,
    reconcile_offer,
)


WALLET = "f" * 64
NETWORK = "mainnet"
ASSET = "a" * 64
TRADE = "b" * 64
OTHER_TRADE = "c" * 64
OFFER_HASH = "d" * 64
COIN = "1" * 64
OTHER_COIN = "2" * 64
FEE_COIN = "3" * 64
RETURN = "4" * 64
OTHER_RETURN = "5" * 64
FEE_RETURN = "6" * 64
RECEIVE = "7" * 64
TX = "8" * 64
SPEND = "sha256:" + "9" * 64
AT = "2026-08-20T12:00:00.000000Z"
AFTER = "2026-08-20T12:00:02.000000Z"


@pytest.fixture(autouse=True)
def _socket_guard(monkeypatch):
    attempts: list[str] = []

    def blocked(*_args, **_kwargs):
        attempts.append("socket")
        raise AssertionError("Task 9 tests forbid network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "task9.db"))
    database._db_initialized = False
    database._db_initialized_path = None
    database.init_database()
    yield
    database.close_connection()


def _intent(
    *,
    trade_id: str = TRADE,
    intent_id: str = "intent-task9",
    coin_ids: tuple[str, ...] = (COIN,),
    offered: str = "1000",
    requested: str = "2000",
    side: str = "buy",
    state: str = "created",
) -> dict:
    coins_json = json.dumps(sorted(coin_ids), separators=(",", ":"))
    return {
        "intent_id": intent_id,
        "run_id": "run-task9",
        "wallet_fingerprint_hash": WALLET,
        "network": NETWORK,
        "asset_id": ASSET,
        "side": side,
        "tier": "inner",
        "purpose": "normal_lifecycle",
        "slot_key": f"slot:{intent_id}",
        "generation": 0,
        "parent_intent_id": None,
        "child_intent_id": None,
        "offered_amount_atomic": offered,
        "requested_amount_atomic": requested,
        "selected_coin_ids_json": coins_json,
        "selected_coin_ids_sha256": hashlib.sha256(coins_json.encode()).hexdigest(),
        "offer_text_sha256": OFFER_HASH,
        "sage_trade_id": trade_id,
        "publication_identity": None,
        "lifecycle_state": state,
        "row_version": 1,
        "prepared_at": AT,
        "submitted_at": None,
        "confirmed_at": AT,
        "first_visible_at": None,
        "terminal_at": None,
        "updated_at": AT,
    }


def _offer(
    *,
    status=4,
    trade_id: str = TRADE,
    selected_coin_ids: list[str] | None = None,
    transaction_id: str = TX,
    side: str = "buy",
    offered: int = 1000,
    requested: int = 2000,
) -> dict:
    if side == "buy":
        offered_map = {"xch": offered}
        requested_map = {ASSET: requested}
    else:
        offered_map = {ASSET: offered}
        requested_map = {"xch": requested}
    return {
        "trade_id": trade_id,
        "status": status,
        "summary": {"offered": offered_map, "requested": requested_map},
        "selected_coin_ids": list(selected_coin_ids or [COIN]),
        "transaction_id": transaction_id,
    }


def _transaction(
    *,
    transaction_id: str = TX,
    spent: list[dict] | None = None,
    created: list[dict] | None = None,
    height: int = 42,
) -> dict:
    return {
        "transaction_id": transaction_id,
        "spend_identity": SPEND,
        "confirmed": True,
        "confirmed_height": height,
        "timestamp": AFTER,
        "spent": spent
        or [
            {
                "coin_id": COIN,
                "asset_id": "xch",
                "amount": 1000,
                "address_kind": "offer",
            }
        ],
        "created": created
        or [
            {
                "coin_id": RECEIVE,
                "asset_id": ASSET,
                "amount": 2000,
                "address_kind": "own",
            }
        ],
    }


def _coin(
    coin_id: str,
    *,
    asset_id: str,
    amount: int,
    spent_height: int | None = None,
    created_height: int = 1,
    transaction_id: str | None = None,
    offer_id: str | None = None,
) -> dict:
    return {
        "coin_id": coin_id,
        "asset_id": asset_id,
        "amount": amount,
        "created_height": created_height,
        "spent_height": spent_height,
        "transaction_id": transaction_id,
        "offer_id": offer_id,
        "owned": True,
    }


def _source(records, *, complete: bool = True, provenance: str) -> dict:
    return {
        "observed_at": AT,
        "provenance": provenance,
        "complete": complete,
        "records": records,
        "pagination": {
            "pages_read": 1,
            "page_size": 50,
            "remote_bounds_honored": True,
            "locally_normalized": True,
        },
    }


def _evidence(
    *,
    offers: list[dict] | None = None,
    transactions: list[dict] | None = None,
    coins: dict[str, dict] | None = None,
    offer_complete: bool = True,
    transaction_complete: bool = True,
    coin_complete: bool = True,
    observed_at: str = AT,
    local_expired: bool = False,
) -> dict:
    evidence = {
        "schema_version": 1,
        "observed_at": observed_at,
        "wallet_fingerprint_hash": WALLET,
        "network": NETWORK,
        "offer_history": _source(
            offers if offers is not None else [_offer()],
            complete=offer_complete,
            provenance="wallet.get_all_offers",
        ),
        "transaction_history": _source(
            transactions if transactions is not None else [_transaction()],
            complete=transaction_complete,
            provenance="wallet.get_transactions_list",
        ),
        "coin_records": _source(
            coins
            if coins is not None
            else {
                COIN: _coin(
                    COIN,
                    asset_id="xch",
                    amount=1000,
                    spent_height=42,
                    transaction_id=TX,
                    offer_id=TRADE,
                ),
                RECEIVE: _coin(
                    RECEIVE,
                    asset_id=ASSET,
                    amount=2000,
                    created_height=42,
                    transaction_id=TX,
                ),
            },
            complete=coin_complete,
            provenance="wallet.get_coins_by_ids",
        ),
        "local_expired": local_expired,
    }
    for name in ("offer_history", "transaction_history", "coin_records"):
        evidence[name]["observed_at"] = observed_at
    return evidence


def _cancel_context(
    *,
    members: list[dict] | None = None,
    auxiliary_coin_ids: list[str] | None = None,
    transaction_id: str = TX,
    spend_identity: str = SPEND,
) -> dict:
    return {
        "cohort_id": "cancel-cohort:test",
        "members": members
        or [
            {
                "intent_id": "intent-task9",
                "trade_id": TRADE,
                "selected_coin_ids": [COIN],
                "request_timestamp": AT,
                "transaction_id": transaction_id,
                "spend_identity": spend_identity,
            }
        ],
        "auxiliary_coin_ids": list(auxiliary_coin_ids or []),
    }


def _classify(
    evidence: dict,
    *,
    intent: dict | None = None,
    cancel_context: dict | None = None,
) -> dict:
    return classify_terminal_evidence(
        intent or _intent(),
        evidence,
        cancel_context=cancel_context,
        now=AFTER,
    )


def test_exact_fill_requires_offer_amount_inputs_transaction_height_and_receipt():
    result = _classify(_evidence())

    assert result["classification"] == FILLED_PROVEN
    assert result["transaction_id"] == TX
    assert result["spend_identity"] == SPEND
    assert result["block_height"] == 42
    assert result["receive_coin_id"] == RECEIVE


def test_fill_accepts_exact_transaction_identity_without_redundant_spend_identity():
    transaction = _transaction()
    transaction.pop("spend_identity")

    result = _classify(_evidence(transactions=[transaction]))

    assert result["classification"] == FILLED_PROVEN
    assert result["transaction_id"] == TX
    assert result["spend_identity"] is None


def test_exact_zero_fee_cancel_return_flow_is_proven():
    evidence = _evidence(
        offers=[_offer(status=3)],
        transactions=[
            _transaction(
                created=[
                    {
                        "coin_id": RETURN,
                        "asset_id": "xch",
                        "amount": 1000,
                        "address_kind": "own",
                    }
                ]
            )
        ],
        coins={
            COIN: _coin(
                COIN,
                asset_id="xch",
                amount=1000,
                spent_height=42,
                transaction_id=TX,
                offer_id=TRADE,
            ),
            RETURN: _coin(
                RETURN,
                asset_id="xch",
                amount=1000,
                created_height=42,
                transaction_id=TX,
            ),
        },
    )

    result = _classify(evidence, cancel_context=_cancel_context())

    assert result["classification"] == CANCELLED_PROVEN
    assert result["fee_mojos"] == 0
    assert result["coin_rebindings"] == [
        {
            "input_coin_id": COIN,
            "return_coin_id": RETURN,
            "asset_id": "xch",
            "amount": 1000,
        }
    ]


def test_fee_bearing_group_cancel_proves_every_member_and_auxiliary_fee_flow():
    second_intent = _intent(
        trade_id=OTHER_TRADE,
        intent_id="intent-task9-other",
        coin_ids=(OTHER_COIN,),
        offered="2000",
        requested="1000",
        side="sell",
    )
    spent = [
        {"coin_id": COIN, "asset_id": "xch", "amount": 1000, "address_kind": "offer"},
        {
            "coin_id": OTHER_COIN,
            "asset_id": ASSET,
            "amount": 2000,
            "address_kind": "offer",
        },
        {"coin_id": FEE_COIN, "asset_id": "xch", "amount": 100, "address_kind": "own"},
    ]
    created = [
        {"coin_id": RETURN, "asset_id": "xch", "amount": 1000, "address_kind": "own"},
        {
            "coin_id": OTHER_RETURN,
            "asset_id": ASSET,
            "amount": 2000,
            "address_kind": "own",
        },
        {"coin_id": FEE_RETURN, "asset_id": "xch", "amount": 90, "address_kind": "own"},
    ]
    coin_rows = {
        COIN: _coin(
            COIN,
            asset_id="xch",
            amount=1000,
            spent_height=42,
            transaction_id=TX,
            offer_id=TRADE,
        ),
        OTHER_COIN: _coin(
            OTHER_COIN,
            asset_id=ASSET,
            amount=2000,
            spent_height=42,
            transaction_id=TX,
            offer_id=OTHER_TRADE,
        ),
        FEE_COIN: _coin(
            FEE_COIN, asset_id="xch", amount=100, spent_height=42, transaction_id=TX
        ),
        RETURN: _coin(
            RETURN, asset_id="xch", amount=1000, created_height=42, transaction_id=TX
        ),
        OTHER_RETURN: _coin(
            OTHER_RETURN,
            asset_id=ASSET,
            amount=2000,
            created_height=42,
            transaction_id=TX,
        ),
        FEE_RETURN: _coin(
            FEE_RETURN, asset_id="xch", amount=90, created_height=42, transaction_id=TX
        ),
    }
    context = _cancel_context(
        members=[
            _cancel_context()["members"][0],
            {
                "intent_id": second_intent["intent_id"],
                "trade_id": OTHER_TRADE,
                "selected_coin_ids": [OTHER_COIN],
                "request_timestamp": AT,
                "transaction_id": TX,
                "spend_identity": SPEND,
            },
        ],
        auxiliary_coin_ids=[FEE_COIN],
    )
    evidence = _evidence(
        offers=[
            _offer(status=3),
            _offer(
                status=3,
                trade_id=OTHER_TRADE,
                selected_coin_ids=[OTHER_COIN],
                side="sell",
                offered=2000,
                requested=1000,
            ),
        ],
        transactions=[_transaction(spent=spent, created=created)],
        coins=coin_rows,
    )

    result = _classify(evidence, cancel_context=context)

    assert result["classification"] == CANCELLED_PROVEN
    assert result["fee_mojos"] == 10
    assert result["grouped_cancel"] is True
    assert result["coin_rebindings"][0]["return_coin_id"] == RETURN


def test_same_wallet_self_take_is_fill_not_cancel():
    evidence = _evidence(
        transactions=[
            _transaction(
                spent=[
                    {
                        "coin_id": COIN,
                        "asset_id": "xch",
                        "amount": 1000,
                        "address_kind": "offer",
                    },
                    {
                        "coin_id": OTHER_COIN,
                        "asset_id": ASSET,
                        "amount": 2000,
                        "address_kind": "own",
                    },
                ],
                created=[
                    {
                        "coin_id": RECEIVE,
                        "asset_id": ASSET,
                        "amount": 2000,
                        "address_kind": "own",
                    },
                    {
                        "coin_id": RETURN,
                        "asset_id": "xch",
                        "amount": 1000,
                        "address_kind": "own",
                    },
                ],
            )
        ],
        coins={
            COIN: _coin(
                COIN,
                asset_id="xch",
                amount=1000,
                spent_height=42,
                transaction_id=TX,
                offer_id=TRADE,
            ),
            OTHER_COIN: _coin(
                OTHER_COIN,
                asset_id=ASSET,
                amount=2000,
                spent_height=42,
                transaction_id=TX,
            ),
            RECEIVE: _coin(
                RECEIVE,
                asset_id=ASSET,
                amount=2000,
                created_height=42,
                transaction_id=TX,
            ),
            RETURN: _coin(
                RETURN,
                asset_id="xch",
                amount=1000,
                created_height=42,
                transaction_id=TX,
            ),
        },
    )

    assert _classify(evidence)["classification"] == FILLED_PROVEN


def test_exact_authoritative_active_offer_is_nonterminal():
    evidence = _evidence(
        offers=[_offer(status=1, transaction_id="")],
        transactions=[],
        coins={
            COIN: _coin(
                COIN,
                asset_id="xch",
                amount=1000,
                offer_id=TRADE,
            )
        },
    )

    assert _classify(evidence)["classification"] == ACTIVE_PROVEN


def test_exact_authoritative_expiry_with_owned_unspent_input_is_proven():
    evidence = _evidence(
        offers=[_offer(status=5, transaction_id="")],
        transactions=[],
        coins={
            COIN: _coin(
                COIN,
                asset_id="xch",
                amount=1000,
                offer_id=TRADE,
            )
        },
    )

    assert _classify(evidence)["classification"] == EXPIRED_PROVEN


def test_local_expiry_and_offer_absence_are_never_terminal_proof():
    result = _classify(
        _evidence(offers=[], transactions=[], local_expired=True),
    )

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "OFFER_ABSENCE_NOT_PROOF"


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("offer_complete", "OFFER_HISTORY_INCOMPLETE"),
        ("transaction_complete", "TRANSACTION_HISTORY_INCOMPLETE"),
        ("coin_complete", "COIN_RECORDS_INCOMPLETE"),
    ],
)
def test_missing_or_incomplete_pages_are_unknown(field, reason):
    result = _classify(_evidence(**{field: False}))

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == reason


def test_stale_source_reads_are_unknown():
    stale = datetime(2026, 8, 20, 12, tzinfo=timezone.utc) - timedelta(minutes=10)
    result = _classify(_evidence(observed_at=stale.strftime("%Y-%m-%dT%H:%M:%S.%fZ")))

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_STALE"


def test_conflicting_cancel_status_and_exact_fill_receipt_fails_closed():
    result = _classify(
        _evidence(offers=[_offer(status=3)]),
        cancel_context=_cancel_context(),
    )

    assert result["classification"] == CONFLICT
    assert result["reason_code"] == "TERMINAL_EVIDENCE_CONFLICT"


def test_wrong_amount_or_selected_coin_identity_is_unknown_not_truthy_terminal():
    wrong_amount = _evidence(offers=[_offer(requested=2001)])
    wrong_coin = _evidence(offers=[_offer(selected_coin_ids=[OTHER_COIN])])

    assert _classify(wrong_amount)["classification"] == UNKNOWN
    assert _classify(wrong_coin)["classification"] == UNKNOWN


def test_sage_loader_locally_filters_ignored_include_completed():
    calls = []

    def ignored_filter(**kwargs):
        calls.append(kwargs)
        return [_offer(status=4), _offer(status=1, trade_id=OTHER_TRADE)]

    source = load_sage_offer_history(
        get_all_offers=ignored_filter,
        include_completed=False,
        observed_at=AT,
        page_size=2,
        max_pages=2,
        max_records=10,
    )

    assert [row["trade_id"] for row in source["records"]] == [OTHER_TRADE]
    assert source["include_completed_normalized"] is True
    assert source["pagination"]["locally_normalized"] is True
    assert calls[0] == {"include_completed": False, "start": 0, "end": 2}


def test_sage_loader_salvages_stable_oversized_snapshot_when_end_is_ignored():
    rows = [_offer(status=1, trade_id=f"{index:064x}") for index in range(5)]
    calls = []

    def ignored_end(**kwargs):
        calls.append(kwargs)
        return [dict(row) for row in rows]

    source = load_sage_offer_history(
        get_all_offers=ignored_end,
        include_completed=True,
        observed_at=AT,
        page_size=2,
        max_pages=4,
        max_records=10,
    )

    assert len(source["records"]) == 5
    assert source["complete"] is True
    assert source["pagination"]["remote_bounds_honored"] is False
    assert source["pagination"]["stable_oversized_snapshot"] is True
    assert len(calls) == 2


def test_authoritative_loader_uses_wallet_facade_readers_and_marks_coin_completeness():
    calls = []
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **kwargs: calls.append(("offers", kwargs)) or [_offer()],
        get_transactions_list=lambda **kwargs: (
            calls.append(("transactions", kwargs))
            or {"success": True, "transactions": [_transaction()], "total": 1}
        ),
        get_coins_by_ids=lambda coin_ids: (
            calls.append(("coins", list(coin_ids)))
            or {
                COIN: _coin(
                    COIN,
                    asset_id="xch",
                    amount=1000,
                    spent_height=42,
                    transaction_id=TX,
                    offer_id=TRADE,
                ),
                RECEIVE: _coin(
                    RECEIVE,
                    asset_id=ASSET,
                    amount=2000,
                    created_height=42,
                    transaction_id=TX,
                ),
            }
        ),
    )

    evidence = load_authoritative_evidence(
        _intent(),
        wallet_facade=facade,
        observed_at=AT,
        wallet_ids=(1, 2),
        page_size=50,
        max_pages=2,
    )

    assert evidence["offer_history"]["complete"] is True
    assert evidence["transaction_history"]["complete"] is True
    assert evidence["coin_records"]["complete"] is True
    assert {kind for kind, _args in calls} == {"offers", "transactions", "coins"}


def test_loader_normalizes_sage_transaction_fields_without_inventing_proof():
    offer = _offer()
    offer.pop("selected_coin_ids")
    transaction = {
        "name": "0x" + TX,
        "confirmed": True,
        "confirmed_at_height": 42,
        "created_at_time": int(
            datetime.fromisoformat(AFTER.replace("Z", "+00:00")).timestamp()
        ),
        "removals": [
            {
                "coin_id": "0x" + COIN,
                "asset_id": None,
                "amount": "1000",
            }
        ],
        "additions": [
            {
                "coin_id": "0x" + RECEIVE,
                "asset": {"asset_id": ASSET},
                "amount": "2000",
            }
        ],
    }
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: [offer],
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [transaction],
            "total": 1,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: _coin(
                COIN,
                asset_id="xch",
                amount=1000,
                spent_height=42,
                transaction_id="0x" + TX,
                offer_id=TRADE,
            ),
            RECEIVE: _coin(
                RECEIVE,
                asset_id=ASSET,
                amount=2000,
                created_height=42,
                transaction_id="0x" + TX,
            ),
        },
    )

    evidence = load_authoritative_evidence(
        _intent(), wallet_facade=facade, observed_at=AT
    )
    result = _classify(evidence)

    assert evidence["transaction_history"]["records"] == [
        {
            "transaction_id": TX,
            "spend_identity": None,
            "confirmed": True,
            "confirmed_height": 42,
            "timestamp": "2026-08-20T12:00:02.000000Z",
            "spent": [
                {
                    "coin_id": COIN,
                    "asset_id": "xch",
                    "amount": 1000,
                    "address_kind": None,
                }
            ],
            "created": [
                {
                    "coin_id": RECEIVE,
                    "asset_id": ASSET,
                    "amount": 2000,
                    "address_kind": None,
                }
            ],
        }
    ]
    assert result["classification"] == FILLED_PROVEN


def test_authoritative_loader_uses_task4_fingerprint_binding_domain():
    fingerprint = 123456789
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "fingerprint": fingerprint,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: [_offer()],
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [_transaction()],
            "total": 1,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: _coin(
                COIN,
                asset_id="xch",
                amount=1000,
                spent_height=42,
                transaction_id=TX,
                offer_id=TRADE,
            ),
            RECEIVE: _coin(
                RECEIVE,
                asset_id=ASSET,
                amount=2000,
                created_height=42,
                transaction_id=TX,
            ),
        },
    )

    evidence = load_authoritative_evidence(
        _intent(), wallet_facade=facade, observed_at=AT
    )

    assert (
        evidence["wallet_fingerprint_hash"]
        == hashlib.sha256(f"fingerprint:{fingerprint}".encode()).hexdigest()
    )


def test_authoritative_loader_rejects_stale_wallet_identity():
    stale = "2026-08-20T11:00:00.000000Z"
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": stale,
        },
        get_all_offers=lambda **_kwargs: [_offer()],
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [],
            "total": 0,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: _coin(COIN, asset_id="xch", amount=1000)
        },
    )

    evidence = load_authoritative_evidence(
        _intent(), wallet_facade=facade, observed_at=AT
    )

    assert evidence["wallet_fingerprint_hash"] == ""
    assert _classify(evidence)["classification"] == UNKNOWN


def test_transaction_loader_detects_ignored_page_bounds():
    rows = [_transaction() for _index in range(50)]
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: [_offer()],
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [dict(row) for row in rows],
            "total": 100,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: _coin(COIN, asset_id="xch", amount=1000),
            RECEIVE: _coin(RECEIVE, asset_id=ASSET, amount=2000),
        },
    )

    evidence = load_authoritative_evidence(
        _intent(),
        wallet_facade=facade,
        observed_at=AT,
        page_size=50,
        max_pages=2,
    )

    assert evidence["transaction_history"]["complete"] is False
    assert (
        evidence["transaction_history"]["pagination"]["remote_bounds_honored"] is False
    )


def test_loader_rejects_falsey_noncanonical_observation_time_before_reads():
    with pytest.raises(ValueError, match="timestamp"):
        load_authoritative_evidence(
            _intent(), wallet_facade=SimpleNamespace(), observed_at=""
        )


def test_classifier_rejects_noncanonical_utc_source_timestamp():
    evidence = _evidence(observed_at="2026-08-20T12:00:00+00:00")

    result = _classify(evidence)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_TIMESTAMP_INVALID"


def test_classifier_caps_selected_coins_and_transaction_flows():
    too_many_coins = tuple(f"{index:064x}" for index in range(1, 258))
    oversized_tx = _transaction(
        created=[
            {
                "coin_id": RECEIVE,
                "asset_id": ASSET,
                "amount": 2000,
                "address_kind": "own",
            },
            *[
                {
                    "coin_id": f"{index + 1000:064x}",
                    "asset_id": "xch",
                    "amount": 1,
                    "address_kind": "own",
                }
                for index in range(512)
            ],
        ]
    )

    selected_result = _classify(_evidence(), intent=_intent(coin_ids=too_many_coins))
    transaction_result = _classify(_evidence(transactions=[oversized_tx]))

    assert selected_result["classification"] == UNKNOWN
    assert transaction_result["classification"] == UNKNOWN


class HostileDict(dict):
    def get(self, *_args, **_kwargs):
        raise AssertionError("hostile dict method invoked")


@pytest.mark.parametrize("hostile", [HostileDict(), {"schema_version": True}])
def test_hostile_or_coercible_evidence_types_fail_closed(hostile):
    result = classify_terminal_evidence(_intent(), hostile, now=AFTER)

    assert result["classification"] == UNKNOWN


def test_durable_evidence_is_redacted_bounded_canonical_and_digest_bound():
    raw = {
        "intent_id": "intent-task9",
        "private_key": "super-secret",
        "offer": "offer1" + "q" * 10000,
        "nested": {"puzzle_reveal": "ab" * 10000},
    }

    encoded, digest = canonical_evidence_and_digest(raw, max_bytes=512)

    assert len(encoded.encode("utf-8")) <= 512
    assert "super-secret" not in encoded
    assert "offer1" not in encoded
    assert "puzzle_reveal" not in encoded
    assert digest == hashlib.sha256(encoded.encode()).hexdigest()
    assert encoded == json.dumps(
        json.loads(encoded), sort_keys=True, separators=(",", ":")
    )


def _persist_created_offer(*, coin_id: str = COIN) -> dict:
    assert database.upsert_coin(
        coin_id,
        "xch",
        1000,
        tier="inner",
        designation="tier_active",
        assigned_tier="inner",
    )
    database.prepare_offer_intent(
        intent_id="intent-task9",
        operation_id="create:intent-task9",
        event_id="create:intent-task9:prepared",
        run_id="run-task9",
        wallet_fingerprint_hash=WALLET,
        network=NETWORK,
        asset_id=ASSET,
        side="buy",
        tier="inner",
        purpose="normal_lifecycle",
        slot_key="slot:intent-task9",
        generation=0,
        offered_amount_atomic="1000",
        requested_amount_atomic="2000",
        selected_coin_ids_json=[coin_id],
        wallet_identity_json={"wallet_fingerprint_hash": WALLET, "network": NETWORK},
        evidence_json={"intent": "exact"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    database.finalize_offer_intent(
        intent_id="intent-task9",
        operation_id="create:intent-task9",
        event_id="create:intent-task9:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=TRADE,
        offer_text_sha256=OFFER_HASH,
        wallet_identity_json={"wallet_fingerprint_hash": WALLET, "network": NETWORK},
        evidence_json={"offer": "confirmed"},
        finalized_at=AT,
        finalize_selected_coin_reservations=True,
    )
    assert database.add_offer(
        TRADE,
        "buy",
        price_xch=database.Decimal("0.0000005"),
        size_xch=database.Decimal("0.000000001"),
        size_cat=database.Decimal("2"),
        cat_asset_id=ASSET,
        tier="inner",
        coin_id=database.norm_coin_id(coin_id),
    )
    return database.get_offer_intent("intent-task9")


def _journal_for(intent_id: str) -> list[dict]:
    return [
        row
        for row in database.get_offer_operation_events(f"reconcile:{intent_id}")
        if row["operation_type"] == "RECONCILE"
    ]


def test_fill_commit_is_one_exact_terminal_event_fill_and_coin_transition(
    isolated_database,
):
    _persist_created_offer()

    applied = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert applied["applied"] is True
    assert applied["classification"] == FILLED_PROVEN
    assert database.get_offer_intent("intent-task9")["lifecycle_state"] == "terminal"
    assert database.get_offer(TRADE)["status"] == "filled"
    fills = database.get_fills(cat_asset_id=ASSET, limit=10)
    assert len([row for row in fills if row["trade_id"] == TRADE]) == 1
    coin = database.get_coin_state(COIN)
    assert coin["status"] == "spent"
    events = _journal_for("intent-task9")
    assert len(events) == 1
    assert events[0]["outcome"] == FILLED_PROVEN
    assert events[0]["evidence_sha256"] == applied["evidence_sha256"]


def test_cancel_commit_spends_old_coin_and_inserts_exact_owned_return(
    isolated_database,
):
    _persist_created_offer()
    evidence = _evidence(
        offers=[_offer(status=3)],
        transactions=[
            _transaction(
                created=[
                    {
                        "coin_id": RETURN,
                        "asset_id": "xch",
                        "amount": 1000,
                        "address_kind": "own",
                    }
                ]
            )
        ],
        coins={
            COIN: _coin(
                COIN,
                asset_id="xch",
                amount=1000,
                spent_height=42,
                transaction_id=TX,
                offer_id=TRADE,
            ),
            RETURN: _coin(
                RETURN,
                asset_id="xch",
                amount=1000,
                created_height=42,
                transaction_id=TX,
            ),
        },
    )

    applied = reconcile_offer(
        "intent-task9",
        evidence=evidence,
        cancel_context=_cancel_context(),
        now=AFTER,
    )

    assert applied["classification"] == CANCELLED_PROVEN
    assert database.get_offer(TRADE)["status"] == "cancelled"
    assert database.get_coin_state(COIN)["status"] == "spent"
    assert database.get_coin_state(RETURN)["status"] == "free"
    assert database.get_coin_state(RETURN)["amount_mojos"] == 1000


def test_exact_replay_is_idempotent_and_changed_proof_is_rejected(isolated_database):
    _persist_created_offer()

    first = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
    changed = _evidence()
    changed["offer_history"]["pagination"]["pages_read"] = 2

    assert replay["event"] == first["event"]
    assert replay["idempotent"] is True
    with pytest.raises(ValueError, match="different authoritative proof"):
        reconcile_offer("intent-task9", evidence=changed, now=AFTER)
    assert len(_journal_for("intent-task9")) == 1
    assert (
        len(
            [
                row
                for row in database.get_fills(cat_asset_id=ASSET, limit=10)
                if row["trade_id"] == TRADE
            ]
        )
        == 1
    )


def test_racing_exact_replays_create_one_fill_and_one_terminal_event(isolated_database):
    _persist_created_offer()
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def run():
        try:
            barrier.wait(timeout=5)
            results.append(
                reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(results) == 2
    assert len(_journal_for("intent-task9")) == 1
    assert (
        len(
            [
                row
                for row in database.get_fills(cat_asset_id=ASSET, limit=10)
                if row["trade_id"] == TRADE
            ]
        )
        == 1
    )


def test_crash_inside_terminal_commit_rolls_back_every_effect(isolated_database):
    _persist_created_offer()
    conn = database.get_connection()
    conn.execute(
        """
        CREATE TRIGGER task9_abort_terminal
        BEFORE UPDATE OF lifecycle_state ON offer_intents
        WHEN NEW.lifecycle_state='terminal'
        BEGIN SELECT RAISE(ABORT, 'task9 crash'); END
        """
    )
    conn.commit()

    with pytest.raises(Exception, match="task9 crash"):
        reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert _journal_for("intent-task9") == []
    assert database.get_offer_intent("intent-task9")["lifecycle_state"] == "created"
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    assert database.get_coin_state(COIN)["status"] == "locked"


def test_unknown_and_conflict_trip_latch_without_rows_locks_or_wallet_mutation(
    isolated_database,
):
    _persist_created_offer()
    missing = _evidence(offers=[], transactions=[])

    result = reconcile_offer("intent-task9", evidence=missing, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert "reconcile:intent-task9" in json.loads(latch["blocking_operation_ids_json"])


def test_exact_active_proof_resolves_prior_unknown_without_releasing_lock(
    isolated_database,
):
    _persist_created_offer()
    reconcile_offer(
        "intent-task9",
        evidence=_evidence(offers=[], transactions=[]),
        now=AFTER,
    )
    active = _evidence(
        offers=[_offer(status=1, transaction_id="")],
        transactions=[],
        coins={COIN: _coin(COIN, asset_id="xch", amount=1000)},
    )

    result = reconcile_offer("intent-task9", evidence=active, now=AFTER)

    assert result["classification"] == ACTIVE_PROVEN
    assert result["applied"] is False
    assert database.get_offer_intent("intent-task9")["lifecycle_state"] == "created"
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_runtime_safety_latch()["state"] == "resolved"
    assert [event["outcome"] for event in _journal_for("intent-task9")] == [
        UNKNOWN,
        ACTIVE_PROVEN,
    ]


def test_registry_denial_never_crosses_terminal_commit_boundary(
    isolated_database, monkeypatch
):
    _persist_created_offer()
    monkeypatch.setattr(
        "offer_reconciliation.authorize_transition",
        lambda *_args, **_kwargs: AuthorizationDecision(
            False,
            AuthorizationCode.EVIDENCE_MISMATCH,
            "denied by test",
        ),
    )

    result = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert result["applied"] is False
    assert result["authorization_code"] == "evidence_mismatch"
    assert database.get_offer_intent("intent-task9")["lifecycle_state"] == "created"
    assert database.get_offer(TRADE)["status"] == "open"
    assert _journal_for("intent-task9") == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_reconcile_rejects_falsey_noncanonical_commit_time(isolated_database):
    _persist_created_offer()

    with pytest.raises(ValueError, match="timestamp"):
        reconcile_offer("intent-task9", evidence=_evidence(), now="")

    assert database.get_offer_intent("intent-task9")["lifecycle_state"] == "created"
    assert _journal_for("intent-task9") == []


def test_fill_tracker_exhaustion_and_third_party_cancel_keep_offer_parked(monkeypatch):
    from fill_tracker import FillTracker

    tracker = FillTracker()
    tracker._pending_reverify_max_attempts = 1
    tracker._pending_reverify[TRADE] = {
        "side": "buy",
        "attempts": 0,
        "first_seen": 0,
        "local_clock_expired": True,
    }
    monkeypatch.setattr(tracker, "_verify_fill_on_chain", lambda *_args: "unverified")
    monkeypatch.setattr(tracker, "_dexie_terminal_status", lambda *_args: "cancelled")
    monkeypatch.setattr(
        tracker,
        "_retire_local_offer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("third-party cancellation must not terminalize")
        ),
    )

    result = tracker._retry_pending_reverify({})

    assert result == {"buy_fills": [], "sell_fills": []}
    assert TRADE in tracker._pending_reverify


def test_bot_health_spacescan_fill_observation_does_not_write_terminal(monkeypatch):
    pending = {
        "trade_id": TRADE,
        "dexie_id": "dexie-1",
        "lifecycle_state": "cancel_sent",
        "status": "open",
        "side": "buy",
        "tier": "inner",
        "coin_id": COIN,
    }
    update_status = MagicMock()
    fake_database = SimpleNamespace(
        get_open_offers=lambda **_kwargs: [pending],
        update_offer_status=update_status,
        transition_offer=MagicMock(),
        get_locked_coin_ids_for_trade=lambda _trade: [COIN],
    )
    monkeypatch.setitem(sys.modules, "database", fake_database)
    monkeypatch.setitem(
        sys.modules,
        "spacescan",
        SimpleNamespace(verify_fill=lambda *_args, **_kwargs: "filled"),
    )
    monkeypatch.setattr(bot_health.cfg, "WALLET_ADDRESS", "xch1test")
    monkeypatch.setattr(
        bot_health,
        "_dexie_get_offer",
        lambda *_args, **_kwargs: {"status": bot_health.DEXIE_STATUS_COMPLETED},
    )

    check = bot_health.check_pending_cancels(auto_repair=True)

    assert check.repaired_count == 0
    update_status.assert_not_called()


def test_unlinked_coin_repair_never_terminalizes_from_wallet_absence(monkeypatch):
    row = {"trade_id": TRADE, "coin_id": database.norm_coin_id(COIN), "side": "buy"}

    fake_database = SimpleNamespace(
        get_unlinked_open_offer_coins=lambda **_kwargs: [row],
        lock_coin=MagicMock(return_value=True),
        update_offer_status=MagicMock(),
    )
    monkeypatch.setitem(sys.modules, "database", fake_database)
    monkeypatch.setitem(
        sys.modules,
        "wallet",
        SimpleNamespace(get_all_offers=lambda **_kwargs: []),
    )
    loop = object.__new__(bot_loop.BotLoop)
    loop._adaptive_target_backoff_until = {"buy": 0.0, "sell": 0.0}

    loop._repair_unlinked_offer_coins()

    fake_database.update_offer_status.assert_not_called()
    fake_database.lock_coin.assert_called_once_with(database.norm_coin_id(COIN), TRADE)


def test_legacy_terminal_bypasses_are_not_callable_from_runtime_orchestration():
    from fill_tracker import FillTracker

    assert not hasattr(FillTracker, "_record_fill")
    assert "wallet_sage" not in inspect.getsource(bot_health)

    forbidden_by_method = {
        bot_loop.BotLoop._startup_sync: (
            "batch_cancel_stale_offers",
            "update_offer_status",
            "cleanup_orphaned_locked_coins",
            "cleanup_expired_db_offers",
        ),
        bot_loop.BotLoop._run_one_cycle: ("cleanup_expired_db_offers",),
        bot_loop.BotLoop._handle_housekeeping: (
            "batch_cancel_stale_offers",
            "cleanup_orphaned_locked_coins",
            "backfill_verified_fills_from_offers",
        ),
        bot_loop.BotLoop._maybe_run_daily_reconcile: (
            "backfill_verified_fills_from_offers",
        ),
    }
    for method, forbidden_names in forbidden_by_method.items():
        source = inspect.getsource(method)
        for forbidden_name in forbidden_names:
            assert forbidden_name not in source


def test_authoritative_terminal_record_exposes_exact_journal_identity(
    isolated_database,
):
    _persist_created_offer()
    result = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    terminal = database.get_authoritative_terminal_record(TRADE)

    assert result["applied"] is True
    assert terminal == {
        "attempt_no": 1,
        "event_id": terminal["event_id"],
        "evidence_sha256": result["evidence_sha256"],
        "intent_id": "intent-task9",
        "operation_id": "reconcile:intent-task9",
        "outcome": FILLED_PROVEN,
        "sage_trade_id": TRADE,
        "terminal_state": "filled",
    }
    assert terminal["event_id"] == "reconcile:intent-task9:attempt:1:finalized"
