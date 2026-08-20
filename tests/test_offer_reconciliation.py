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
import offer_reconciliation as reconciliation
from cancel_outcomes import (
    CANCEL_FAILED,
    CANCEL_SUBMITTED_UNCONFIRMED,
    cancellation_result,
)
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
RECONCILED = "2026-08-20T12:00:10.000000Z"
HOOK_RETRY = "2026-08-20T12:01:02.000000Z"
MANIFEST_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "effect_claim_protocol": "durable_cohort_claim_v1",
            "prior_lifecycle_state": "open",
            "trade_id": TRADE,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()
MEMBER_ID = "cancel-member:" + "f" * 64
PREPARED_EVENT_ID = f"cancel:{TRADE}:attempt:1:prepared"


def _clock_at(value: str = AT):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return lambda: instant


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
    timestamp: str = AFTER,
) -> dict:
    return {
        "transaction_id": transaction_id,
        "spend_identity": SPEND,
        "confirmed": True,
        "confirmed_height": height,
        "timestamp": timestamp,
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
        "source_observed_at": None,
        "read_observed_at": [AT],
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


def _identity_source(*, observed_at: str, complete: bool = True) -> dict:
    return {
        "observed_at": observed_at,
        "source_observed_at": observed_at,
        "source_observed_at_all": [observed_at],
        "read_observed_at": [observed_at],
        "provenance": "wallet.get_wallet_identity",
        "complete": complete,
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
        "collection_started_at": observed_at,
        "observed_at": observed_at,
        "wallet_fingerprint_hash": WALLET,
        "network": NETWORK,
        "wallet_identity": _identity_source(observed_at=observed_at),
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
        evidence[name]["read_observed_at"] = [observed_at]
    return evidence


@pytest.mark.parametrize(
    "skewed_clock",
    [
        "collection_started_at",
        "collection_end",
        "wallet_identity_observed",
        "wallet_identity_read",
        "source_read",
        "evaluation",
    ],
)
def test_every_collection_and_read_clock_participates_in_durable_source_skew(
    isolated_database,
    skewed_clock,
):
    _persist_created_offer()
    evidence = _evidence()
    earlier = "2026-08-20T11:58:59.000000Z"
    later = "2026-08-20T12:01:03.000000Z"
    evaluated_at = AFTER
    if skewed_clock == "collection_started_at":
        evidence["collection_started_at"] = earlier
    elif skewed_clock == "collection_end":
        evidence["observed_at"] = later
        evaluated_at = later
    elif skewed_clock == "wallet_identity_observed":
        evidence["wallet_identity"]["observed_at"] = earlier
    elif skewed_clock == "wallet_identity_read":
        evidence["wallet_identity"]["read_observed_at"] = [earlier]
    elif skewed_clock == "source_read":
        evidence["transaction_history"]["read_observed_at"] = [earlier]
    elif skewed_clock == "evaluation":
        evaluated_at = later
    else:  # pragma: no cover - exhaustive parametrization guard
        raise AssertionError(skewed_clock)

    result = reconcile_offer(
        "intent-task9",
        evidence=evidence,
        now=evaluated_at,
    )

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_SOURCE_SKEW"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def _cancel_context(
    *,
    members: list[dict] | None = None,
    auxiliary_coin_ids: list[str] | None = None,
    transaction_id: str = TX,
    spend_identity: str = SPEND,
) -> dict:
    exact_members = members or [
        {
            "intent_id": "intent-task9",
            "trade_id": TRADE,
            "selected_coin_ids": [COIN],
            "request_timestamp": AT,
            "transaction_id": transaction_id,
            "spend_identity": spend_identity,
        }
    ]
    exact_members = [dict(member) for member in exact_members]
    for index, member in enumerate(exact_members):
        is_target = member["trade_id"] == TRADE
        member.setdefault("asset_id", ASSET)
        member.setdefault("side", "buy" if is_target else "sell")
        member.setdefault("offered_amount_atomic", "1000" if is_target else "2000")
        member.setdefault("requested_amount_atomic", "2000" if is_target else "1000")
        member.setdefault("offer_text_sha256", OFFER_HASH if is_target else "0" * 64)
        member.setdefault("transaction_timestamp", AFTER)
        member.setdefault("member_id", f"cancel-member:{index}:" + "f" * 64)
        member.setdefault(
            "prepared_event_id",
            f"cancel:{member['trade_id']}:attempt:1:prepared",
        )
    return {
        "cohort_id": "cancel-cohort:test",
        "manifest_sha256": MANIFEST_SHA256,
        "members": exact_members,
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


def _same_value_cancel_evidence(*, with_lineage: bool) -> tuple[dict, dict, dict]:
    spent = [
        {
            "coin_id": COIN,
            "asset_id": "xch",
            "amount": 1000,
            "address_kind": "offer",
        },
        {
            "coin_id": OTHER_COIN,
            "asset_id": "xch",
            "amount": 1000,
            "address_kind": "offer",
        },
    ]
    created = [
        {
            "coin_id": RETURN,
            "asset_id": "xch",
            "amount": 1000,
            "address_kind": "own",
        },
        {
            "coin_id": OTHER_RETURN,
            "asset_id": "xch",
            "amount": 1000,
            "address_kind": "own",
        },
    ]
    if with_lineage:
        created[0]["parent_coin_id"] = OTHER_COIN
        created[1]["parent_coin_id"] = COIN
    intent = _intent(coin_ids=(COIN, OTHER_COIN), offered="2000")
    context = _cancel_context(
        members=[
            {
                "intent_id": intent["intent_id"],
                "trade_id": TRADE,
                "selected_coin_ids": [COIN, OTHER_COIN],
                "request_timestamp": AT,
                "transaction_timestamp": AFTER,
                "transaction_id": TX,
                "spend_identity": SPEND,
                "offered_amount_atomic": "2000",
            }
        ]
    )
    evidence = _evidence(
        offers=[
            _offer(
                status=3,
                offered=2000,
                selected_coin_ids=[COIN, OTHER_COIN],
            )
        ],
        transactions=[_transaction(spent=spent, created=created)],
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
            OTHER_RETURN: _coin(
                OTHER_RETURN,
                asset_id="xch",
                amount=1000,
                created_height=42,
                transaction_id=TX,
            ),
        },
    )
    return intent, context, evidence


def test_cancel_return_nonunique_same_value_mapping_is_conflict():
    intent, context, evidence = _same_value_cancel_evidence(with_lineage=False)

    result = _classify(evidence, intent=intent, cancel_context=context)

    assert result["classification"] == CONFLICT
    assert result["reason_code"] == "CANCEL_RETURN_LINEAGE_AMBIGUOUS"


def test_cancel_return_parent_lineage_resolves_same_value_mapping():
    intent, context, evidence = _same_value_cancel_evidence(with_lineage=True)

    result = _classify(evidence, intent=intent, cancel_context=context)

    assert result["classification"] == CANCELLED_PROVEN
    assert result["coin_rebindings"] == [
        {
            "input_coin_id": COIN,
            "return_coin_id": OTHER_RETURN,
            "asset_id": "xch",
            "amount": 1000,
        },
        {
            "input_coin_id": OTHER_COIN,
            "return_coin_id": RETURN,
            "asset_id": "xch",
            "amount": 1000,
        },
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


def _grouped_cancel_contradiction_case(
    *, sibling_status: int = 3, sibling_offered: int = 2000
) -> tuple[dict, dict]:
    context = _cancel_context(
        members=[
            _cancel_context()["members"][0],
            {
                "intent_id": "intent-task9-other",
                "trade_id": OTHER_TRADE,
                "selected_coin_ids": [OTHER_COIN],
                "request_timestamp": AT,
                "transaction_id": TX,
                "spend_identity": SPEND,
            },
        ]
    )
    evidence = _evidence(
        offers=[
            _offer(status=3),
            _offer(
                status=sibling_status,
                trade_id=OTHER_TRADE,
                selected_coin_ids=[OTHER_COIN],
                side="sell",
                offered=sibling_offered,
                requested=1000,
            ),
        ],
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
                        "address_kind": "offer",
                    },
                ],
                created=[
                    {
                        "coin_id": RETURN,
                        "asset_id": "xch",
                        "amount": 1000,
                        "address_kind": "own",
                    },
                    {
                        "coin_id": OTHER_RETURN,
                        "asset_id": ASSET,
                        "amount": 2000,
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
                offer_id=OTHER_TRADE,
            ),
            RETURN: _coin(
                RETURN,
                asset_id="xch",
                amount=1000,
                created_height=42,
                transaction_id=TX,
            ),
            OTHER_RETURN: _coin(
                OTHER_RETURN,
                asset_id=ASSET,
                amount=2000,
                created_height=42,
                transaction_id=TX,
            ),
        },
    )
    return context, evidence


@pytest.mark.parametrize("sibling_status", [1, 4, 5])
def test_grouped_cancel_conflicts_with_non_cancelled_sibling_status(sibling_status):
    context, evidence = _grouped_cancel_contradiction_case(
        sibling_status=sibling_status
    )

    result = _classify(evidence, cancel_context=context)

    assert result["classification"] == CONFLICT
    assert result["reason_code"] == "CANCEL_COHORT_MEMBER_CONTRADICTION"


def test_grouped_cancel_conflicts_with_sibling_summary_not_bound_to_task4_facts():
    context, evidence = _grouped_cancel_contradiction_case(sibling_offered=2001)

    result = _classify(evidence, cancel_context=context)

    assert result["classification"] == CONFLICT
    assert result["reason_code"] == "CANCEL_COHORT_MEMBER_CONTRADICTION"


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


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing", "WALLET_IDENTITY_INCOMPLETE"),
        ("incomplete", "WALLET_IDENTITY_INCOMPLETE"),
        ("unprovenanced", "WALLET_IDENTITY_INCOMPLETE"),
        ("missing_timestamp", "EVIDENCE_TIMESTAMP_INVALID"),
        ("source_skew", "EVIDENCE_SOURCE_SKEW"),
    ],
)
def test_wallet_identity_source_is_required_in_freshness_and_skew_matrix(
    mutation, reason
):
    evidence = _evidence(observed_at=AFTER)
    if mutation == "missing":
        evidence.pop("wallet_identity")
    elif mutation == "incomplete":
        evidence["wallet_identity"]["complete"] = False
    elif mutation == "unprovenanced":
        evidence["wallet_identity"]["provenance"] = ""
    elif mutation == "missing_timestamp":
        evidence["wallet_identity"]["source_observed_at"] = None
        evidence["wallet_identity"]["source_observed_at_all"] = []
    else:
        stale_but_bounded = "2026-08-20T11:58:30.000000Z"
        evidence["wallet_identity"]["source_observed_at"] = stale_but_bounded
        evidence["wallet_identity"]["source_observed_at_all"] = [stale_but_bounded]

    result = _classify(evidence)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == reason


@pytest.mark.parametrize(
    ("singular_timestamp", "all_timestamps", "reason"),
    [
        (
            "2026-08-20T11:54:00.000000Z",
            [AFTER],
            "EVIDENCE_STALE",
        ),
        (
            "2026-08-20T12:01:00.000000Z",
            [AFTER],
            "EVIDENCE_STALE",
        ),
        (
            "2026-08-20T12:00:01.000000Z",
            [AFTER],
            "EVIDENCE_TIMESTAMP_INVALID",
        ),
    ],
    ids=["stale-singular", "future-singular", "singular-list-mismatch"],
)
def test_wallet_identity_singular_source_time_is_bound_to_freshness_and_provenance(
    isolated_database,
    singular_timestamp,
    all_timestamps,
    reason,
):
    _persist_created_offer()
    evidence = _evidence(observed_at=AFTER)
    evidence["wallet_identity"]["source_observed_at"] = singular_timestamp
    evidence["wallet_identity"]["source_observed_at_all"] = all_timestamps

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == reason
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_missing_transaction_asset_never_defaults_to_native_xch():
    transaction = _transaction()
    transaction["spent"][0].pop("asset_id")

    result = _classify(_evidence(transactions=[transaction]))

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "FILL_PROOF_INCOMPLETE"


@pytest.mark.parametrize(
    ("asset_id", "amount", "offer_id"),
    [
        (None, 1000, TRADE),
        (ASSET, 1000, TRADE),
        ("xch", 999, TRADE),
        ("xch", 1000, None),
        ("xch", 1000, OTHER_TRADE),
    ],
)
def test_active_requires_exact_asset_amount_and_offer_linkage(
    asset_id, amount, offer_id
):
    coin = _coin(
        COIN,
        asset_id="xch",
        amount=amount,
        offer_id=offer_id,
    )
    if asset_id is None:
        coin.pop("asset_id")
    else:
        coin["asset_id"] = asset_id
    evidence = _evidence(
        offers=[_offer(status=1, transaction_id="")],
        transactions=[],
        coins={COIN: coin},
    )

    result = _classify(evidence)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "ACTIVE_INPUT_STATE_UNPROVEN"


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


def _simple_cancel_flow_evidence(*, status) -> dict:
    return _evidence(
        offers=[_offer(status=status)],
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


def test_filled_status_contradicting_exact_cancel_flow_is_conflict():
    result = _classify(
        _simple_cancel_flow_evidence(status=4),
        cancel_context=_cancel_context(),
    )

    assert result["classification"] == CONFLICT
    assert result["reason_code"] == "TERMINAL_EVIDENCE_CONFLICT"


@pytest.mark.parametrize("status", [1, 5])
def test_active_or_expired_status_with_exact_fill_flow_is_conflict(status):
    result = _classify(_evidence(offers=[_offer(status=status)]))

    assert result["classification"] == CONFLICT
    assert result["reason_code"] == "TERMINAL_EVIDENCE_CONFLICT"


def test_active_status_with_exact_cancel_flow_is_conflict():
    result = _classify(
        _simple_cancel_flow_evidence(status=1),
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
        clock=_clock_at(),
        page_size=2,
        max_pages=2,
        max_records=10,
    )

    assert [row["trade_id"] for row in source["records"]] == [OTHER_TRADE]
    assert source["include_completed_normalized"] is True
    assert source["pagination"]["locally_normalized"] is True
    assert calls[0] == {"include_completed": False, "start": 0, "end": 2}


def test_sage_loader_rejects_stable_oversized_snapshot_without_authoritative_end():
    rows = [_offer(status=1, trade_id=f"{index:064x}") for index in range(5)]
    calls = []

    def ignored_end(**kwargs):
        calls.append(kwargs)
        return [dict(row) for row in rows]

    source = load_sage_offer_history(
        get_all_offers=ignored_end,
        include_completed=True,
        clock=_clock_at(),
        page_size=2,
        max_pages=4,
        max_records=10,
    )

    assert len(source["records"]) == 5
    assert source["complete"] is False
    assert source["pagination"]["remote_bounds_honored"] is False
    assert source["pagination"]["stable_oversized_snapshot"] is True
    assert len(calls) == 2


def test_sage_loader_accepts_oversized_snapshot_only_with_authoritative_total():
    rows = [_offer(status=1, trade_id=f"{index:064x}") for index in range(5)]

    def authoritative_snapshot(**_kwargs):
        return {"offers": [dict(row) for row in rows], "total": len(rows)}

    source = load_sage_offer_history(
        get_all_offers=authoritative_snapshot,
        include_completed=True,
        clock=_clock_at(),
        page_size=2,
        max_pages=4,
        max_records=10,
    )

    assert len(source["records"]) == 5
    assert source["complete"] is True
    assert source["pagination"]["authoritative_end"] is True


def test_offer_loader_preserves_conflicting_duplicate_identity_for_conflict():
    rows = [_offer(status=4), _offer(status=3)]

    source = load_sage_offer_history(
        get_all_offers=lambda **_kwargs: {"offers": rows, "total": 2},
        include_completed=True,
        clock=_clock_at(),
        page_size=10,
        max_pages=2,
        max_records=10,
    )
    evidence = _evidence()
    evidence["offer_history"] = source

    result = _classify(evidence)

    assert len(source["records"]) == 2
    assert result["classification"] == CONFLICT
    assert result["reason_code"] == "DUPLICATE_OFFER_IDENTITY"


def test_differing_duplicate_transaction_identity_is_conflict():
    duplicate = _transaction()
    duplicate["confirmed_height"] = 43

    result = _classify(_evidence(transactions=[_transaction(), duplicate]))

    assert result["classification"] == CONFLICT
    assert result["reason_code"] == "DUPLICATE_TRANSACTION_IDENTITY"


def test_byte_equivalent_duplicate_transaction_identity_is_deduplicated():
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
        },
        get_all_offers=lambda **_kwargs: {"offers": [_offer()], "total": 1},
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [_transaction(), dict(_transaction())],
            "total": 2,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: _coin(COIN, asset_id="xch", amount=1000),
            RECEIVE: _coin(RECEIVE, asset_id=ASSET, amount=2000),
        },
    )

    evidence = load_authoritative_evidence(
        _intent(), wallet_facade=facade, clock=_clock_at(), page_size=10
    )

    assert evidence["transaction_history"]["complete"] is True
    assert len(evidence["transaction_history"]["records"]) == 1


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
        clock=_clock_at(),
        wallet_ids=(1, 2),
        page_size=50,
        max_pages=2,
    )

    assert evidence["offer_history"]["complete"] is True
    assert evidence["transaction_history"]["complete"] is True
    assert evidence["coin_records"]["complete"] is True
    assert evidence["wallet_identity"]["source_observed_at"] == AT
    assert evidence["wallet_identity"]["source_observed_at_all"] == [AT]
    assert {kind for kind, _args in calls} == {"offers", "transactions", "coins"}


def test_loader_captures_each_post_read_time_and_rejects_excessive_source_skew(
    monkeypatch,
):
    clock = {"now": datetime.fromisoformat(AT.replace("Z", "+00:00"))}

    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = clock["now"]
            target = current if tz is None else current.astimezone(tz)
            return cls.fromtimestamp(target.timestamp(), target.tzinfo)

    def advance(seconds):
        clock["now"] += timedelta(seconds=seconds)

    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: advance(10) or [_offer(status=1)],
        get_transactions_list=lambda **_kwargs: (
            advance(70) or {"success": True, "transactions": [], "total": 0}
        ),
        get_coins_by_ids=lambda _coin_ids: (
            advance(1) or {COIN: _coin(COIN, asset_id="xch", amount=1000)}
        ),
    )
    monkeypatch.setattr(reconciliation, "datetime", ControlledDateTime)

    evidence = load_authoritative_evidence(_intent(), wallet_facade=facade)
    result = classify_terminal_evidence(
        _intent(), evidence, now=evidence["observed_at"]
    )

    assert evidence["offer_history"]["observed_at"] == ("2026-08-20T12:00:10.000000Z")
    assert evidence["transaction_history"]["observed_at"] == (
        "2026-08-20T12:01:20.000000Z"
    )
    assert evidence["coin_records"]["observed_at"] == ("2026-08-20T12:01:21.000000Z")
    assert evidence["observed_at"] == "2026-08-20T12:01:21.000000Z"
    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_SOURCE_SKEW"


def test_loader_retains_and_rejects_cached_source_timestamp(monkeypatch):
    stale = "2026-08-20T11:50:00.000000Z"

    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime.fromisoformat(AT.replace("Z", "+00:00"))
            target = current if tz is None else current.astimezone(tz)
            return cls.fromtimestamp(target.timestamp(), target.tzinfo)

    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: {
            "offers": [_offer(status=1)],
            "observed_at_utc": stale,
        },
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [],
            "total": 0,
            "observed_at_utc": AT,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: _coin(COIN, asset_id="xch", amount=1000)
        },
    )
    monkeypatch.setattr(reconciliation, "datetime", ControlledDateTime)

    evidence = load_authoritative_evidence(_intent(), wallet_facade=facade)
    result = classify_terminal_evidence(_intent(), evidence, now=AT)

    assert evidence["offer_history"]["source_observed_at"] == stale
    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_STALE"


def test_offer_loader_retains_every_page_source_time_and_rejects_hidden_stale_page():
    stale = "2026-08-20T11:50:00.000000Z"
    responses = [
        {"offers": [_offer(status=1, transaction_id="")], "observed_at_utc": stale},
        {"offers": [], "observed_at_utc": AT},
    ]

    source = load_sage_offer_history(
        get_all_offers=lambda **_kwargs: responses.pop(0),
        include_completed=True,
        clock=_clock_at(),
        page_size=1,
        max_pages=2,
        max_records=10,
    )
    evidence = _evidence(
        offers=[],
        transactions=[],
        coins={COIN: _coin(COIN, asset_id="xch", amount=1000, offer_id=TRADE)},
    )
    evidence["offer_history"] = source

    result = _classify(evidence)

    assert source["source_observed_at_all"] == [stale, AT]
    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_STALE"


def test_offer_loader_normalization_exception_is_incomplete_not_raised():
    hostile_offer = _offer()
    hostile_offer["summary"]["offered"]["xch"] = object()

    source = load_sage_offer_history(
        get_all_offers=lambda **_kwargs: [hostile_offer],
        include_completed=True,
        clock=_clock_at(),
        page_size=10,
        max_pages=1,
        max_records=10,
    )

    assert source["complete"] is False
    assert source["read_error"] == "normalization_exception"
    assert source["records"] == []


def test_expiry_loader_does_not_invent_coin_ownership_or_asset(monkeypatch):
    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime.fromisoformat(AFTER.replace("Z", "+00:00"))
            target = current if tz is None else current.astimezone(tz)
            return cls.fromtimestamp(target.timestamp(), target.tzinfo)

    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AFTER,
        },
        get_all_offers=lambda **_kwargs: [_offer(status=5, transaction_id="")],
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [],
            "total": 0,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: {
                "amount": 1000,
                "offer_id": TRADE,
                "spent_height": None,
            }
        },
    )
    monkeypatch.setattr(reconciliation, "datetime", ControlledDateTime)

    evidence = load_authoritative_evidence(_intent(), wallet_facade=facade)
    result = classify_terminal_evidence(_intent(), evidence, now=AFTER)

    assert "owned" not in evidence["coin_records"]["records"][COIN]
    assert "asset_id" not in evidence["coin_records"]["records"][COIN]
    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EXPIRY_SAFE_RELEASE_UNPROVEN"


def test_sage_coin_adapter_preserves_explicit_asset_and_ownership(monkeypatch):
    import wallet_sage

    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {
            "coins": [
                {
                    "coin_id": COIN,
                    "amount": "1000",
                    "asset_id": ASSET,
                    "owned": True,
                    "offer_id": TRADE,
                    "spent_height": None,
                    "created_height": 9,
                    "transaction_id": TX,
                }
            ]
        },
    )

    records = wallet_sage.get_coins_by_ids([COIN])

    assert records["0x" + COIN]["asset_id"] == ASSET
    assert records["0x" + COIN]["owned"] is True


def test_sage_coin_adapter_normalizes_explicit_native_asset_without_inventing_missing(
    monkeypatch,
):
    import wallet_sage

    response = {
        "coins": [
            {
                "coin_id": COIN,
                "amount": "1000",
                "asset_id": None,
                "owned": True,
                "offer_id": TRADE,
            },
            {
                "coin_id": OTHER_COIN,
                "amount": "2000",
                "owned": True,
                "offer_id": OTHER_TRADE,
            },
        ]
    }
    monkeypatch.setattr(wallet_sage, "rpc", lambda *_args, **_kwargs: response)

    records = wallet_sage.get_coins_by_ids([COIN, OTHER_COIN])

    assert records["0x" + COIN]["asset_id"] == "xch"
    assert "asset_id" not in records["0x" + OTHER_COIN]


@pytest.mark.parametrize(
    ("raw_amount", "offered"),
    [(1000.9, "1000"), (True, "1"), ("9" * 5000, "1000")],
    ids=["fractional-float", "boolean", "over-cap-digits"],
)
def test_malformed_sage_coin_amount_is_unknown_end_to_end_without_terminal_mutation(
    isolated_database,
    monkeypatch,
    raw_amount,
    offered,
):
    import wallet_sage

    _persist_created_offer(offered=offered)
    offered_int = int(offered)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {
            "coins": [
                {
                    "coin_id": COIN,
                    "amount": raw_amount,
                    "asset_id": None,
                    "owned": True,
                    "offer_id": TRADE,
                    "spent_height": 42,
                    "created_height": 1,
                    "transaction_id": TX,
                },
                {
                    "coin_id": RECEIVE,
                    "amount": "2000",
                    "asset_id": ASSET,
                    "owned": True,
                    "spent_height": None,
                    "created_height": 42,
                    "transaction_id": TX,
                },
            ]
        },
    )
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: {
            "offers": [_offer(offered=offered_int)],
            "total": 1,
        },
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [
                _transaction(
                    spent=[
                        {
                            "coin_id": COIN,
                            "asset_id": "xch",
                            "amount": offered_int,
                            "address_kind": "offer",
                        }
                    ]
                )
            ],
            "total": 1,
        },
        get_coins_by_ids=wallet_sage.get_coins_by_ids,
    )

    evidence = load_authoritative_evidence(
        _intent(offered=offered),
        wallet_facade=facade,
        clock=_clock_at(AT),
    )
    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_sage_atomic_amount_digit_cap_precedes_integer_conversion(monkeypatch):
    import wallet_sage

    calls = []

    def forbidden_int(value):
        calls.append(value)
        raise AssertionError("over-cap Sage amount reached integer conversion")

    monkeypatch.setattr(wallet_sage, "int", forbidden_int, raising=False)

    assert wallet_sage._exact_positive_atomic_amount("9" * 129) is None
    assert calls == []


@pytest.mark.parametrize("kind", ["key", "value"])
def test_sage_coin_adapter_rejects_oversized_ignored_provider_scalars(
    monkeypatch,
    kind,
):
    import wallet_sage

    record = {
        "coin_id": COIN,
        "amount": "1000",
        "asset_id": None,
        "owned": True,
        "offer_id": TRADE,
    }
    oversized = "x" * 4097
    if kind == "key":
        record[oversized] = "ignored"
    else:
        record["ignored_provider_detail"] = oversized
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda *_args, **_kwargs: {"coins": [record]},
    )

    assert wallet_sage.get_coins_by_ids([COIN]) is None


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
        _intent(), wallet_facade=facade, clock=_clock_at()
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


class _AtomicTextSubclass(str):
    """Provider text subclasses are outside the exact atomic-number domain."""


@pytest.mark.parametrize(
    ("field_name", "raw_value"),
    [
        ("amount", "01000"),
        ("amount", "+1000"),
        ("amount", " 1000"),
        ("amount", "1000.0"),
        ("amount", "١٠٠٠"),
        ("amount", "00"),
        ("amount", True),
        ("amount", 1000.0),
        ("amount", _AtomicTextSubclass("1000")),
        ("height", "042"),
        ("height", "+42"),
        ("height", " 42"),
        ("height", "42.0"),
        ("height", "٤٢"),
        ("height", "00"),
        ("height", True),
        ("height", 42.0),
        ("height", _AtomicTextSubclass("42")),
    ],
    ids=lambda value: f"{type(value).__name__}-{value!r}",
)
def test_sage_transaction_noncanonical_atomic_numbers_are_unknown_latched(
    isolated_database,
    field_name,
    raw_value,
):
    """Malformed Sage amount/height proof cannot terminalize a durable offer."""

    _persist_created_offer()
    transaction = {
        "name": "0x" + TX,
        "confirmed": True,
        "confirmed_at_height": raw_value if field_name == "height" else 42,
        "created_at_time": int(
            datetime.fromisoformat(AFTER.replace("Z", "+00:00")).timestamp()
        ),
        "removals": [
            {
                "coin_id": "0x" + COIN,
                "asset_id": None,
                "amount": raw_value if field_name == "amount" else 1000,
            }
        ],
        "additions": [
            {
                "coin_id": "0x" + RECEIVE,
                "asset": {"asset_id": ASSET},
                "amount": 2000,
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
        get_all_offers=lambda **_kwargs: [_offer()],
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
        _intent(), wallet_facade=facade, clock=_clock_at()
    )
    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize(
    "hostile_field",
    [
        "spend_identity",
        "spend_condition_id",
        "ignored_scalar_value",
        "ignored_scalar_key",
    ],
)
def test_oversized_provider_scalars_cannot_terminalize_sage_transaction(
    isolated_database,
    hostile_field,
):
    _persist_created_offer()
    oversized = "x" * 4097
    removal = {
        "coin_id": "0x" + COIN,
        "asset_id": None,
        "amount": 1000,
    }
    transaction = {
        "name": "0x" + TX,
        "confirmed": True,
        "confirmed_at_height": 42,
        "created_at_time": int(
            datetime.fromisoformat(AFTER.replace("Z", "+00:00")).timestamp()
        ),
        "removals": [removal],
        "additions": [
            {
                "coin_id": "0x" + RECEIVE,
                "asset": {"asset_id": ASSET},
                "amount": 2000,
            }
        ],
    }
    if hostile_field == "spend_identity":
        transaction["spend_identity"] = oversized
    elif hostile_field == "spend_condition_id":
        removal["spend_condition_id"] = oversized
    elif hostile_field == "ignored_scalar_value":
        removal["ignored_provider_detail"] = oversized
    else:
        removal[oversized] = "ignored"
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
            "transactions": [transaction],
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
        _intent(), wallet_facade=facade, clock=_clock_at()
    )
    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize("kind", ["key", "value"])
def test_provider_scalar_cap_is_inclusive(kind):
    at_cap = "x" * 4096
    removal = {
        "coin_id": "0x" + COIN,
        "asset_id": None,
        "amount": 1000,
    }
    if kind == "key":
        removal[at_cap] = "ignored"
    else:
        removal["ignored_provider_detail"] = at_cap
    row = reconciliation._normalized_transaction_row(
        {
            "name": "0x" + TX,
            "confirmed": True,
            "confirmed_at_height": 42,
            "created_at_time": int(
                datetime.fromisoformat(AFTER.replace("Z", "+00:00")).timestamp()
            ),
            "removals": [removal],
            "additions": [
                {
                    "coin_id": "0x" + RECEIVE,
                    "asset": {"asset_id": ASSET},
                    "amount": 2000,
                }
            ],
        }
    )

    assert row["spent"][0]["amount"] == 1000


def test_atomic_integer_bit_cap_precedes_decimal_text_allocation():
    assert reconciliation._atomic_text(1 << 100_000) == ""


def test_canonical_evidence_rejects_conservative_text_bound_before_dump():
    hostile_key = "x" * (reconciliation._MAX_CANONICAL_TEXT_BYTES // 4 + 1)

    with pytest.raises(ValueError, match="evidence text cap exceeded"):
        canonical_evidence_and_digest({hostile_key: None}, max_bytes=512)


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
        _intent(), wallet_facade=facade, clock=_clock_at()
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
        _intent(), wallet_facade=facade, clock=_clock_at()
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
        clock=_clock_at(),
        page_size=50,
        max_pages=2,
    )

    assert evidence["transaction_history"]["complete"] is False
    assert (
        evidence["transaction_history"]["pagination"]["remote_bounds_honored"] is False
    )


def test_transaction_loader_accepts_oversized_snapshot_with_authoritative_total():
    rows = [
        _transaction(transaction_id=TX),
        _transaction(transaction_id="a" * 64),
        _transaction(transaction_id="c" * 64),
    ]
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: {"offers": [_offer()], "total": 1},
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": rows,
            "total": len(rows),
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
        _intent(), wallet_facade=facade, clock=_clock_at(), page_size=2
    )
    result = _classify(evidence)

    assert evidence["transaction_history"]["complete"] is True
    assert evidence["transaction_history"]["pagination"]["authoritative_end"] is True
    assert result["classification"] == FILLED_PROVEN


def test_loader_rejects_noncanonical_clock_before_reads():
    with pytest.raises(ValueError, match="timestamp"):
        load_authoritative_evidence(
            _intent(), wallet_facade=SimpleNamespace(), clock=lambda: ""
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


@pytest.mark.parametrize(
    ("source_name", "timestamp_field"),
    [
        ("wallet_identity", "source_observed_at_all"),
        ("wallet_identity", "read_observed_at"),
        ("offer_history", "source_observed_at_all"),
        ("transaction_history", "read_observed_at"),
    ],
)
def test_classifier_caps_timestamp_arrays_before_building_effective_clock_set(
    isolated_database,
    source_name,
    timestamp_field,
):
    _persist_created_offer()
    evidence = _evidence(observed_at=AFTER)
    evidence[source_name][timestamp_field] = [AFTER] * 4097

    classified = _classify(evidence)
    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert classified["classification"] == UNKNOWN
    assert classified["reason_code"] == "EVIDENCE_SOURCE_LIMIT_EXCEEDED"
    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_ENCODING_FAILED"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    event = _journal_for("intent-task9")[-1]
    assert event["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize("source_name", ["offers", "transactions", "coins"])
def test_classifier_caps_each_hostile_evidence_source(source_name):
    kwargs = {}
    if source_name == "offers":
        kwargs["offers"] = [
            _offer(
                status=4 if index == 0 else 1,
                trade_id=TRADE if index == 0 else f"{index:064x}",
                transaction_id=TX if index == 0 else "",
            )
            for index in range(1001)
        ]
    elif source_name == "transactions":
        kwargs["transactions"] = [
            _transaction(
                transaction_id=TX if index == 0 else f"{index:064x}",
            )
            for index in range(1001)
        ]
    else:
        kwargs["coins"] = {
            **_evidence()["coin_records"]["records"],
            **{
                f"{index:064x}": _coin(f"{index:064x}", asset_id="xch", amount=1)
                for index in range(1, 4096)
                if f"{index:064x}" not in {COIN, RECEIVE}
            },
        }

    result = _classify(_evidence(**kwargs))

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_SOURCE_LIMIT_EXCEEDED"


def test_coin_map_checks_cap_before_traversing_members(monkeypatch):
    records = {
        f"{index:064x}": {"coin_id": f"{index:064x}"}
        for index in range(reconciliation._MAX_COIN_RECORDS)
    }
    assert len(reconciliation._coin_map({"records": records})) == 4096
    records[f"{reconciliation._MAX_COIN_RECORDS:064x}"] = {
        "coin_id": f"{reconciliation._MAX_COIN_RECORDS:064x}"
    }
    traversed = []

    def forbidden_member_traversal(value):
        traversed.append(value)
        raise AssertionError("oversized coin map was traversed")

    monkeypatch.setattr(reconciliation, "_hex_id", forbidden_member_traversal)

    assert reconciliation._coin_map({"records": records}) is None
    assert traversed == []


def test_transaction_row_cap_is_exact_and_precedes_member_shape_checks():
    at_cap = [{} for _index in range(reconciliation._MAX_HISTORY_RECORDS)]
    assert reconciliation._transaction_rows({"records": at_cap}) is at_cap

    over_cap = [*at_cap, {}]
    assert reconciliation._transaction_rows({"records": over_cap}) is None


def test_offer_page_cap_precedes_hostile_row_traversal():
    rows = [
        _offer(status=1, trade_id=f"{index:064x}", transaction_id="")
        for index in range(reconciliation._MAX_HISTORY_RECORDS)
    ]
    rows.append(HostileDict())

    source = load_sage_offer_history(
        get_all_offers=lambda **_kwargs: rows,
        include_completed=True,
        clock=_clock_at(),
        page_size=reconciliation._MAX_HISTORY_RECORDS,
        max_pages=1,
        max_records=reconciliation._MAX_HISTORY_RECORDS,
    )

    assert source["complete"] is False
    assert source["read_error"] == "source_limit_exceeded"
    assert source["records"] == []


def test_transaction_page_cap_precedes_hostile_row_traversal():
    rows = [
        _transaction(transaction_id=f"{index:064x}")
        for index in range(reconciliation._MAX_HISTORY_RECORDS)
    ]
    rows.append(HostileDict())

    source = reconciliation._load_transactions(
        lambda **_kwargs: {
            "success": True,
            "transactions": rows,
            "total": len(rows),
        },
        wallet_ids=(1,),
        clock=_clock_at(),
        page_size=reconciliation._MAX_HISTORY_RECORDS,
        max_pages=1,
        max_records=reconciliation._MAX_HISTORY_RECORDS,
    )

    assert source["complete"] is False
    assert source["read_error"] == "source_limit_exceeded"
    assert source["records"] == []


def test_transaction_flow_cap_precedes_normalization(monkeypatch):
    at_cap_calls = []

    def observe_at_cap(entry):
        at_cap_calls.append(entry)
        return None

    monkeypatch.setattr(reconciliation, "_normalized_transaction_flow", observe_at_cap)
    normalized = reconciliation._normalized_transaction_row(
        {
            "spent": [{} for _index in range(reconciliation._MAX_TRANSACTION_FLOWS)],
            "created": [],
        }
    )
    assert len(normalized["spent"]) == reconciliation._MAX_TRANSACTION_FLOWS
    assert len(at_cap_calls) == reconciliation._MAX_TRANSACTION_FLOWS

    def forbidden_flow_normalization(_entry):
        raise AssertionError("oversized transaction flow was traversed")

    monkeypatch.setattr(
        reconciliation, "_normalized_transaction_flow", forbidden_flow_normalization
    )
    with pytest.raises(ValueError, match="source limit"):
        reconciliation._normalized_transaction_row(
            {
                "spent": [
                    {} for _index in range(reconciliation._MAX_TRANSACTION_FLOWS + 1)
                ],
                "created": [],
            }
        )


def test_loader_absolute_page_bounds_are_validated_before_wallet_reads():
    calls = []

    with pytest.raises(ValueError, match="hard limits"):
        load_sage_offer_history(
            get_all_offers=lambda **kwargs: calls.append(kwargs) or [],
            include_completed=True,
            clock=_clock_at(),
            page_size=1,
            max_pages=reconciliation._MAX_HISTORY_PAGES + 1,
            max_records=10,
        )

    assert calls == []


def test_huge_remote_total_cannot_extend_absolute_page_count():
    calls = []

    def endless_history(**kwargs):
        calls.append(kwargs)
        return {
            "offers": [
                _offer(
                    status=1,
                    trade_id=f"{kwargs['start'] + 1:064x}",
                    transaction_id="",
                )
            ],
            "total": 10**100,
        }

    source = load_sage_offer_history(
        get_all_offers=endless_history,
        include_completed=True,
        clock=_clock_at(),
        page_size=1,
        max_pages=reconciliation._MAX_HISTORY_PAGES,
        max_records=reconciliation._MAX_HISTORY_RECORDS,
    )

    assert len(calls) == reconciliation._MAX_HISTORY_PAGES
    assert source["pagination"]["pages_read"] == reconciliation._MAX_HISTORY_PAGES
    assert source["complete"] is False


def test_selected_coin_cap_precedes_sort_and_normalization(monkeypatch):
    intent = reconciliation._exact_intent(_intent())
    offer = _offer(
        selected_coin_ids=[
            f"{index + 100:064x}"
            for index in range(reconciliation._MAX_SELECTED_COINS + 1)
        ]
    )
    original_hex_id = reconciliation._hex_id
    selected_traversal = []

    def reject_selected(value):
        if value == TRADE:
            return original_hex_id(value)
        selected_traversal.append(value)
        raise AssertionError("oversized selected-coin list was traversed")

    monkeypatch.setattr(reconciliation, "_hex_id", reject_selected)

    assert reconciliation._offer_summary_matches(intent, offer) is False
    assert selected_traversal == []


def test_selected_coin_exact_cap_is_accepted():
    selected = tuple(
        f"{index + 100:064x}" for index in range(reconciliation._MAX_SELECTED_COINS)
    )
    intent = reconciliation._exact_intent(_intent(coin_ids=selected))
    offer = _offer(selected_coin_ids=list(selected))

    assert reconciliation._offer_summary_matches(intent, offer) is True


def test_full_loader_flow_cap_is_incomplete_unknown_and_latched(isolated_database):
    _persist_created_offer()
    transaction = _transaction(
        spent=[
            {
                "coin_id": f"{index + 100:064x}",
                "asset_id": "xch",
                "amount": 1,
                "address_kind": "offer",
            }
            for index in range(reconciliation._MAX_TRANSACTION_FLOWS + 1)
        ]
    )
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: {"offers": [_offer()], "total": 1},
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [transaction],
            "total": 1,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: _coin(COIN, asset_id="xch", amount=1000)
        },
    )

    evidence = load_authoritative_evidence(
        _intent(), wallet_facade=facade, clock=_clock_at()
    )
    classified = _classify(evidence)
    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert evidence["transaction_history"]["read_error"] == "source_limit_exceeded"
    assert evidence["transaction_history"]["records"] == []
    assert classified == {
        "classification": UNKNOWN,
        "reason_code": "TRANSACTION_HISTORY_INCOMPLETE",
    }
    assert result["classification"] == UNKNOWN
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize(
    ("count", "expected_error", "expected_records"),
    [(4096, None, 4096), (4097, "source_limit_exceeded", 0)],
)
def test_raw_coin_response_cap_is_exact_before_record_copying(
    count,
    expected_error,
    expected_records,
):
    coin_records = {
        COIN: _coin(COIN, asset_id="xch", amount=1000),
        **{
            f"{index + 100:064x}": _coin(
                f"{index + 100:064x}", asset_id="xch", amount=1
            )
            for index in range(count - 1)
        },
    }
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: {
            "offers": [_offer(status=1, transaction_id="")],
            "total": 1,
        },
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [],
            "total": 0,
        },
        get_coins_by_ids=lambda _coin_ids: coin_records,
    )

    evidence = load_authoritative_evidence(
        _intent(), wallet_facade=facade, clock=_clock_at()
    )

    assert evidence["coin_records"]["read_error"] == expected_error
    assert len(evidence["coin_records"]["records"]) == expected_records
    assert evidence["coin_records"]["complete"] is False


@pytest.mark.parametrize(
    ("field_count", "expected_error", "expected_complete"),
    [(64, None, True), (65, "source_limit_exceeded", False)],
)
def test_raw_coin_record_field_cap_precedes_copying(
    field_count,
    expected_error,
    expected_complete,
):
    record = _coin(COIN, asset_id="xch", amount=1000)
    record.update(
        {f"provider_field_{index}": index for index in range(field_count - len(record))}
    )
    assert len(record) == field_count
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: {
            "offers": [_offer(status=1, transaction_id="")],
            "total": 1,
        },
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [],
            "total": 0,
        },
        get_coins_by_ids=lambda _coin_ids: {COIN: record},
    )

    evidence = load_authoritative_evidence(
        _intent(), wallet_facade=facade, clock=_clock_at()
    )

    assert evidence["coin_records"]["read_error"] == expected_error
    assert evidence["coin_records"]["complete"] is expected_complete
    assert len(evidence["coin_records"]["records"]) == int(expected_complete)


def test_loader_rejects_hostile_coin_mapping_subclass_without_iteration():
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: {
            "offers": [_offer(status=1, transaction_id="")],
            "total": 1,
        },
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [],
            "total": 0,
        },
        get_coins_by_ids=lambda _coin_ids: _HostileMapping(),
    )

    evidence = load_authoritative_evidence(
        _intent(), wallet_facade=facade, clock=_clock_at()
    )

    assert evidence["coin_records"]["read_error"] == "reader_malformed"
    assert evidence["coin_records"]["records"] == {}
    assert evidence["coin_records"]["complete"] is False


class HostileTuple(tuple):
    def __iter__(self):
        raise AssertionError("hostile wallet id tuple iteration invoked")


@pytest.mark.parametrize(
    "wallet_ids",
    [HostileTuple((1,)), tuple(range(1, reconciliation._MAX_WALLET_IDS + 2))],
)
def test_loader_rejects_hostile_or_over_cap_wallet_ids_before_reads(wallet_ids):
    calls = []
    facade = SimpleNamespace(
        get_wallet_identity=lambda: calls.append("identity"),
        get_all_offers=lambda **_kwargs: calls.append("offers"),
        get_transactions_list=lambda **_kwargs: calls.append("transactions"),
        get_coins_by_ids=lambda _coin_ids: calls.append("coins"),
    )

    with pytest.raises(ValueError, match="bounds"):
        load_authoritative_evidence(
            _intent(), wallet_facade=facade, clock=_clock_at(), wallet_ids=wallet_ids
        )

    assert calls == []


def test_over_cap_coin_evidence_is_unknown_latched_without_terminal_mutation(
    isolated_database,
):
    _persist_created_offer()
    evidence = _evidence()
    for index in range(reconciliation._MAX_COIN_RECORDS + 1):
        coin_id = f"{index + 100:064x}"
        evidence["coin_records"]["records"][coin_id] = _coin(
            coin_id, asset_id="xch", amount=1
        )

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


class HostileList(list):
    def __iter__(self):
        raise AssertionError("hostile list iteration invoked")


@pytest.mark.parametrize(
    "result",
    [HostileList(), {"offers": HostileList()}],
)
def test_offer_loader_rejects_sequence_subclasses_without_iteration(result):
    source = load_sage_offer_history(
        get_all_offers=lambda **_kwargs: result,
        include_completed=True,
        clock=_clock_at(),
        page_size=1,
        max_pages=1,
        max_records=1,
    )

    assert source["complete"] is False
    assert source["read_error"] == "reader_malformed"
    assert source["records"] == []


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
        "records": [{"identity": index} for index in range(64)],
    }

    encoded, digest = canonical_evidence_and_digest(raw, max_bytes=512)

    assert len(encoded.encode("utf-8")) <= 512
    assert "super-secret" not in encoded
    assert "offer1" not in encoded
    assert "puzzle_reveal" not in encoded
    envelope = json.loads(encoded)
    assert envelope["full_evidence_sha256"] == digest
    assert (
        envelope["exact_subset_sha256"]
        == hashlib.sha256(
            json.dumps(
                envelope["exact_subset"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    assert encoded == json.dumps(
        json.loads(encoded), sort_keys=True, separators=(",", ":")
    )


def test_durable_digest_covers_changes_beyond_first_512_list_members():
    first = {"records": [{"identity": index} for index in range(513)]}
    changed = {"records": [{"identity": index} for index in range(513)]}
    changed["records"][512]["identity"] = 999999

    first_encoded, first_digest = canonical_evidence_and_digest(first, max_bytes=512)
    changed_encoded, changed_digest = canonical_evidence_and_digest(
        changed, max_bytes=512
    )

    assert json.loads(first_encoded)["full_evidence_sha256"] == first_digest
    assert json.loads(changed_encoded)["full_evidence_sha256"] == changed_digest
    assert first_digest != changed_digest


def test_durable_digest_covers_long_and_deep_redacted_tail_changes():
    first_long = {"public_note": "a" * 5000 + "first"}
    changed_long = {"public_note": "a" * 5000 + "changed"}
    first_deep = {"value": 1}
    changed_deep = {"value": 2}
    for _index in range(14):
        first_deep = {"nested": first_deep}
        changed_deep = {"nested": changed_deep}

    first_long_json, first_long_digest = canonical_evidence_and_digest(first_long)
    changed_long_json, changed_long_digest = canonical_evidence_and_digest(changed_long)
    first_deep_json, first_deep_digest = canonical_evidence_and_digest(first_deep)
    changed_deep_json, changed_deep_digest = canonical_evidence_and_digest(changed_deep)

    assert len(first_long_json.encode()) <= 65536
    assert len(changed_long_json.encode()) <= 65536
    assert first_long_digest != changed_long_digest
    assert first_deep_json != changed_deep_json
    assert first_deep_digest != changed_deep_digest


def test_terminal_journal_accepts_bounded_full_proof_digest_and_rejects_tail_change(
    isolated_database,
):
    _persist_created_offer()
    evidence = _evidence()
    evidence["offer_history"]["records"].extend(
        _offer(status=1, trade_id=f"{index + 1000:064x}", transaction_id="")
        for index in range(600)
    )

    first = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)
    durable = json.loads(first["event"]["evidence_json"])

    assert durable["bounded"] is True
    assert durable["full_evidence_sha256"] == first["evidence_sha256"]

    changed = json.loads(json.dumps(evidence))
    changed["offer_history"]["records"][-1]["status"] = 2
    with pytest.raises(ValueError, match="different authoritative proof"):
        reconcile_offer("intent-task9", evidence=changed, now=AFTER)


def _persist_created_offer(*, coin_id: str = COIN, offered: str = "1000") -> dict:
    assert database.upsert_coin(
        coin_id,
        "xch",
        int(offered),
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
        offered_amount_atomic=offered,
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
        size_xch=database.Decimal(offered) / database.Decimal("1000000000000"),
        size_cat=database.Decimal("2"),
        cat_asset_id=ASSET,
        tier="inner",
        coin_id=database.norm_coin_id(coin_id),
    )
    return database.get_offer_intent("intent-task9")


def _persist_prepared_offer_with_unlinked_reservation() -> dict:
    assert database.upsert_coin(
        COIN,
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
        selected_coin_ids_json=[COIN],
        wallet_identity_json={"wallet_fingerprint_hash": WALLET, "network": NETWORK},
        evidence_json={"intent": "exact"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    return database.get_offer_intent("intent-task9")


def _persist_cancel_prepared(
    *, claim_effect: bool = True, claimed_at: str = AT
) -> dict:
    prepared = database.prepare_offer_cancel(
        operation_id=f"cancel:{TRADE}",
        event_id=PREPARED_EVENT_ID,
        trade_id=TRADE,
        intent_id="intent-task9",
        attempt=1,
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET,
            "network": NETWORK,
        },
        evidence_json={
            "trade_id": TRADE,
            "effect_claim_protocol": "durable_cohort_claim_v1",
        },
        prepared_at=AT,
    )
    if claim_effect:
        assert database.claim_offer_cancel_effect(
            operation_id=f"cancel:{TRADE}",
            trade_id=TRADE,
            attempt=1,
            claimed_at=claimed_at,
        )
    return prepared


def _persist_cancel_result(
    outcome: str,
    *,
    attempt: int = 1,
    transaction_id: str = "",
    spend_identity: str = "",
) -> dict:
    result = cancellation_result(
        outcome,
        method="task9_test",
        raw_response={"success": outcome != CANCEL_FAILED},
        error="REJECTED" if outcome == CANCEL_FAILED else "",
        transaction_id=transaction_id,
        spend_identity=spend_identity,
    )
    return database.finalize_offer_cancel(
        operation_id=f"cancel:{TRADE}",
        event_id=f"cancel:{TRADE}:attempt:{attempt}:finalized",
        trade_id=TRADE,
        intent_id="intent-task9",
        attempt=attempt,
        cancel_result=result,
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET,
            "network": NETWORK,
        },
        evidence_json={"trade_id": TRADE, "cancel_result": result},
        finalized_at=AFTER,
    )


def _cancel_evidence_with_identity(*, transaction_id: str, spend_identity: str) -> dict:
    evidence = _simple_cancel_flow_evidence(status=3)
    evidence["offer_history"]["records"][0]["transaction_id"] = transaction_id
    transaction = evidence["transaction_history"]["records"][0]
    transaction["transaction_id"] = transaction_id
    transaction["spend_identity"] = spend_identity
    for coin in evidence["coin_records"]["records"].values():
        coin["transaction_id"] = transaction_id
    return evidence


def _journal_for(intent_id: str) -> list[dict]:
    return [
        row
        for row in database.get_offer_operation_events(f"reconcile:{intent_id}")
        if row["operation_type"] == "RECONCILE"
    ]


def test_wallet_reconcile_preserves_absent_trade_attributed_registry_lock(
    isolated_database,
):
    _persist_created_offer()

    stats = database.reconcile_coins_with_wallet({}, {}, "xch")

    coin = database.get_coin_state(COIN)
    assert coin["status"] == "locked"
    assert coin["trade_id"] == TRADE
    assert stats["marked_gone"] == 0
    assert stats["protected"] == 1


def test_orphan_cleanup_preserves_nonterminal_registry_and_trade_lock(
    isolated_database,
):
    _persist_created_offer()

    stats = database.cleanup_orphaned_locked_coins(set())

    coin = database.get_coin_state(COIN)
    assert coin["status"] == "locked"
    assert coin["trade_id"] == TRADE
    assert stats["total_freed"] == 0
    assert stats["protected_registry_or_trade"] == 1


def test_mark_gone_restricts_legacy_cleanup_to_unreserved_coins(isolated_database):
    _persist_created_offer()
    conn = database.get_connection()
    conn.execute(
        "UPDATE coins SET status='free', trade_id=NULL WHERE coin_id=?",
        (database.norm_coin_id(COIN),),
    )
    conn.commit()

    changed = database.mark_coins_gone([database.norm_coin_id(COIN)])

    assert changed == 0
    assert database.get_coin_state(COIN)["status"] == "free"


def test_coin_manager_periodic_reconcile_has_no_terminal_lock_bypass():
    from coin_manager import CoinManager

    source = inspect.getsource(CoinManager.reconcile_with_wallet)

    assert "mark_coin_spent(cid)" not in source
    assert 'UPDATE coins SET status="free"' not in source
    assert "UPDATE coins SET status='free'" not in source
    assert "get_connection" not in source
    assert "conn.execute" not in source


def test_wallet_locked_link_audit_never_rebinds_registry_trade_lock(
    isolated_database,
):
    _persist_created_offer()

    stats = database.reconcile_wallet_locked_coin_links({COIN: OTHER_TRADE})

    assert stats["protected"] == 1
    coin = database.get_coin_state(COIN)
    assert coin["status"] == "locked"
    assert coin["trade_id"] == TRADE


def test_chia_reconcile_atomic_release_cannot_cross_new_task4_reservation(
    isolated_database,
    monkeypatch,
):
    from coin_manager import CoinManager
    from config import cfg
    import wallet

    assert database.upsert_coin(
        COIN,
        "xch",
        1000,
        tier="inner",
        designation="tier_active",
        assigned_tier="inner",
    )
    conn = database.get_connection()
    conn.execute(
        "UPDATE coins SET status='locked', trade_id=NULL WHERE coin_id=?",
        (database.norm_coin_id(COIN),),
    )
    conn.commit()

    reservation_created = False

    def create_task4_reservation() -> None:
        nonlocal reservation_created
        if reservation_created:
            return
        reservation_created = True
        database.prepare_offer_intent(
            intent_id="intent-task9-chia-race",
            operation_id="create:intent-task9-chia-race",
            event_id="create:intent-task9-chia-race:prepared",
            run_id="run-task9",
            wallet_fingerprint_hash=WALLET,
            network=NETWORK,
            asset_id=ASSET,
            side="buy",
            tier="inner",
            purpose="normal_lifecycle",
            slot_key="slot:intent-task9-chia-race",
            generation=0,
            offered_amount_atomic="1000",
            requested_amount_atomic="2000",
            selected_coin_ids_json=[COIN],
            wallet_identity_json={
                "wallet_fingerprint_hash": WALLET,
                "network": NETWORK,
            },
            evidence_json={"race": "chia_atomic_release"},
            prepared_at=AT,
            reserve_selected_coins=False,
        )

    original_protection = database.is_coin_reconciliation_protected
    old_release = database.free_coin
    atomic_release = getattr(
        database, "free_unreserved_locked_coin_for_reconciliation", None
    )
    calls = {"old": 0, "atomic": 0}

    def observed_then_old_release(coin_id):
        calls["old"] += 1
        create_task4_reservation()
        return old_release(coin_id)

    def observed_then_atomic_release(coin_id):
        calls["atomic"] += 1
        create_task4_reservation()
        assert atomic_release is not None
        return atomic_release(coin_id)

    # Against the old implementation, reservation is inserted after its
    # protection observation and immediately before free_coin. Against the
    # desired implementation, the same reservation is inserted immediately
    # before the one atomic database primitive opens BEGIN IMMEDIATE.
    def observe_unprotected_then_pause(coin_id):
        protected = original_protection(coin_id)
        assert protected is False
        return protected

    monkeypatch.setattr(
        database, "is_coin_reconciliation_protected", observe_unprotected_then_pause
    )
    monkeypatch.setattr(database, "free_coin", observed_then_old_release)
    monkeypatch.setattr(
        database,
        "free_unreserved_locked_coin_for_reconciliation",
        observed_then_atomic_release,
        raising=False,
    )
    monkeypatch.setattr(wallet, "get_wallet_type", lambda: "chia")
    monkeypatch.setattr(wallet, "get_all_offers", lambda **_kwargs: [])

    manager = CoinManager.__new__(CoinManager)
    monkeypatch.setattr(
        manager,
        "_get_coins_fast",
        lambda wallet_id: (
            {
                "success": True,
                "confirmed_records": [{"name": COIN, "coin": {"amount": 1000}}],
            }
            if wallet_id == cfg.WALLET_ID_XCH
            else {"success": True, "confirmed_records": []}
        ),
    )
    monkeypatch.setattr(manager, "_ensure_reserve_exists", lambda *_args: None)

    manager.reconcile_with_wallet()

    assert reservation_created is True
    assert database.get_offer_intent("intent-task9-chia-race") is not None
    coin = database.get_coin_state(COIN)
    assert coin["status"] == "locked"
    assert coin["trade_id"] is None
    assert calls == {"old": 0, "atomic": 1}


@pytest.mark.parametrize(
    "legacy_writer",
    [
        "mark_gone",
        "wallet_locked_links",
        "wallet_snapshot",
        "orphan_cleanup",
    ],
)
def test_task4_registry_write_cannot_cross_legacy_reconciliation_snapshot(
    isolated_database,
    monkeypatch,
    legacy_writer,
):
    assert database.upsert_coin(
        COIN,
        "xch",
        1000,
        tier="inner",
        designation="tier_active",
        assigned_tier="inner",
    )
    if legacy_writer == "orphan_cleanup":
        conn = database.get_connection()
        conn.execute(
            "UPDATE coins SET status='locked', trade_id=NULL WHERE coin_id=?",
            (database.norm_coin_id(COIN),),
        )
        conn.commit()

    registry_read = threading.Event()
    release_legacy = threading.Event()
    reservation_started = threading.Event()
    reservation_done = threading.Event()
    errors = []
    original_registry_read = database._nonterminal_registry_coin_ids

    def pause_after_registry_read(conn):
        protected = original_registry_read(conn)
        if threading.current_thread().name == "task9-legacy-race":
            registry_read.set()
            assert release_legacy.wait(timeout=5)
        return protected

    monkeypatch.setattr(
        database, "_nonterminal_registry_coin_ids", pause_after_registry_read
    )

    def run_legacy():
        try:
            if legacy_writer == "mark_gone":
                database.mark_coins_gone([database.norm_coin_id(COIN)])
            elif legacy_writer == "wallet_locked_links":
                database.reconcile_wallet_locked_coin_links({COIN: OTHER_TRADE})
            elif legacy_writer == "wallet_snapshot":
                database.reconcile_coins_with_wallet({}, {}, "xch")
            elif legacy_writer == "orphan_cleanup":
                database.cleanup_orphaned_locked_coins(set())
            else:  # pragma: no cover - exhaustive parametrization guard
                raise AssertionError(legacy_writer)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def run_task4_registry_write():
        reservation_started.set()
        try:
            database.prepare_offer_intent(
                intent_id="intent-task9-race",
                operation_id="create:intent-task9-race",
                event_id="create:intent-task9-race:prepared",
                run_id="run-task9",
                wallet_fingerprint_hash=WALLET,
                network=NETWORK,
                asset_id=ASSET,
                side="buy",
                tier="inner",
                purpose="normal_lifecycle",
                slot_key="slot:intent-task9-race",
                generation=0,
                offered_amount_atomic="1000",
                requested_amount_atomic="2000",
                selected_coin_ids_json=[COIN],
                wallet_identity_json={
                    "wallet_fingerprint_hash": WALLET,
                    "network": NETWORK,
                },
                evidence_json={"race": "task4_registry_owner"},
                prepared_at=AT,
                reserve_selected_coins=False,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            reservation_done.set()

    legacy_thread = threading.Thread(target=run_legacy, name="task9-legacy-race")
    legacy_thread.start()
    assert registry_read.wait(timeout=5)
    reservation_thread = threading.Thread(target=run_task4_registry_write)
    reservation_thread.start()
    assert reservation_started.wait(timeout=5)
    completed_before_legacy_release = reservation_done.wait(timeout=0.5)
    release_legacy.set()
    legacy_thread.join(timeout=10)
    reservation_thread.join(timeout=10)

    assert completed_before_legacy_release is False
    assert errors == []
    assert not legacy_thread.is_alive()
    assert not reservation_thread.is_alive()
    assert database.get_offer_intent("intent-task9-race") is not None


def test_periodic_amount_linker_cannot_consume_registry_owned_unlinked_coin(
    isolated_database,
    monkeypatch,
):
    from coin_manager import CoinManager
    import wallet

    _persist_prepared_offer_with_unlinked_reservation()
    conn = database.get_connection()
    conn.execute(
        "UPDATE coins SET trade_id=NULL WHERE coin_id=?",
        (database.norm_coin_id(COIN),),
    )
    conn.commit()
    manager = CoinManager.__new__(CoinManager)
    xch_snapshot = {
        "owned_map": {database.norm_coin_id(COIN): 1000},
        "selectable_map": {},
        "selectable_records": [],
        "owned_ids": {database.norm_coin_id(COIN)},
        "locked_ids": {database.norm_coin_id(COIN)},
        "offer_id_map": {},
    }
    empty_snapshot = {
        "owned_map": {},
        "selectable_map": {},
        "selectable_records": [],
        "owned_ids": set(),
        "locked_ids": set(),
        "offer_id_map": {},
    }
    monkeypatch.setattr(wallet, "get_wallet_type", lambda: "sage")
    monkeypatch.setattr(
        wallet,
        "get_all_offers",
        lambda **_kwargs: [
            {
                "trade_id": OTHER_TRADE,
                "status": "active",
                "summary": {"offered": {"xch": 1000}, "requested": {ASSET: 2000}},
            }
        ],
    )
    snapshots = iter([xch_snapshot, empty_snapshot])
    monkeypatch.setattr(
        manager, "_get_sage_owned_coin_snapshot", lambda _wallet_id: next(snapshots)
    )
    monkeypatch.setattr(manager, "_get_coins_fast", lambda _wallet_id: [])
    monkeypatch.setattr(manager, "_ensure_reserve_exists", lambda *_args: None)

    manager.reconcile_with_wallet()

    coin = database.get_coin_state(COIN)
    assert coin["status"] == "locked"
    assert coin["trade_id"] is None


@pytest.mark.parametrize("status", ["gone", "spent"])
def test_wallet_reappearance_preserves_nonterminal_registry_coin_state_and_trade(
    isolated_database,
    status,
):
    _persist_created_offer()
    conn = database.get_connection()
    conn.execute(
        "UPDATE coins SET status=? WHERE coin_id=?",
        (status, database.norm_coin_id(COIN)),
    )
    conn.commit()

    stats = database.reconcile_coins_with_wallet(
        {database.norm_coin_id(COIN): 1000},
        {database.norm_coin_id(COIN): 1000},
        "xch",
    )

    coin = database.get_coin_state(COIN)
    assert coin["status"] == status
    assert coin["trade_id"] == TRADE
    assert stats["reappeared"] == 0
    assert stats["protected"] == 1


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


def test_fill_persists_chain_time_separately_from_reconciliation_time(
    isolated_database,
):
    _persist_created_offer()
    chain_time = "2026-08-20T12:00:01.000000Z"
    evidence = _evidence(transactions=[_transaction(timestamp=chain_time)])

    result = reconcile_offer("intent-task9", evidence=evidence, now=RECONCILED)

    assert result["classification"] == FILLED_PROVEN
    assert result["filled_at"] == chain_time
    assert database.get_offer(TRADE)["filled_at"] == chain_time
    fill = next(
        row
        for row in database.get_fills(cat_asset_id=ASSET, limit=10)
        if row["trade_id"] == TRADE
    )
    assert fill["filled_at"] == chain_time
    assert database.get_offer_intent("intent-task9")["terminal_at"] == RECONCILED
    assert _journal_for("intent-task9")[-1]["created_at"] == RECONCILED


def test_fill_transaction_before_durable_offer_creation_is_unknown():
    before = "2026-08-20T11:59:59.000000Z"

    result = _classify(_evidence(transactions=[_transaction(timestamp=before)]))

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "FILL_PREDATES_OFFER"


def test_future_fill_becomes_durable_unknown_and_preserves_lock(isolated_database):
    _persist_created_offer()
    future = "2026-08-20T12:00:03.000000Z"
    evidence = _evidence(transactions=[_transaction(timestamp=future)])

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "TRANSACTION_TIME_OUTSIDE_EVIDENCE_WINDOW"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_future_cancel_becomes_durable_unknown_without_resolving_task8(
    isolated_database,
):
    _persist_created_offer()
    _persist_cancel_prepared()
    future = "2026-08-20T12:00:03.000000Z"
    evidence = _simple_cancel_flow_evidence(status=3)
    evidence["transaction_history"]["records"][0]["timestamp"] = future

    result = reconcile_offer(
        "intent-task9",
        evidence=evidence,
        cancel_context=_cancel_context(),
        now=AFTER,
    )

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "TRANSACTION_TIME_OUTSIDE_EVIDENCE_WINDOW"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    cancel_events = database.get_offer_operation_events(f"cancel:{TRADE}")
    assert [event["outcome"] for event in cancel_events] == ["PREPARED"]
    assert cancel_events[-1]["blocks_mutation"] == 1
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def _commit_fill_without_draining_hooks(monkeypatch) -> dict:
    _persist_created_offer()
    monkeypatch.setattr(reconciliation, "_run_post_fill_hooks", lambda *_a, **_k: {})
    committed = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
    fill = database.get_fill_by_trade_id(TRADE)
    assert fill is not None and fill["fill_id"] == committed["fill_id"]
    return fill


def _insert_authoritative_test_fill(trade_id: str, *, block_height: int = 42) -> dict:
    fill_id = database.record_fill(
        trade_id,
        "buy",
        price_xch=database.Decimal("0.0000005"),
        size_xch=database.Decimal("0.000000001"),
        size_cat=database.Decimal("2"),
        cat_asset_id=ASSET,
        tier="inner",
        verification_status="verified_authoritative",
        filled_at=AFTER,
    )
    assert fill_id > 0
    conn = database.get_connection()
    conn.execute(
        "UPDATE fills SET spent_block_index=?, spent_block_height=? WHERE fill_id=?",
        (block_height, block_height, fill_id),
    )
    database._ensure_authoritative_fill_hook_outbox(conn, fill_id)
    conn.commit()
    fill = database.get_fill_by_id(fill_id)
    assert fill is not None
    return fill


def _boost_materialization(
    fill_id: int,
    *,
    trade_id: str = TRADE,
    side: str = "buy",
    offset_bps: int = 137,
    last_safe_offset_bps: int = 121,
) -> dict:
    return {
        "schema_version": 1,
        "fill_id": fill_id,
        "trade_id": trade_id,
        "side": side,
        "probe_trade_id": trade_id,
        "probe_matched": True,
        "settled_before": False,
        "offset_bps": offset_bps,
        "floor_bps": offset_bps,
        "last_safe_offset_bps": last_safe_offset_bps,
    }


def _record_claimed_test_sink_ack(fill_id, hook_name, detail, claim):
    if hook_name == "offer_filled_event":
        return database.log_authoritative_offer_filled_once(
            fill_id,
            "claimed test offer-filled event",
            {"fill_id": fill_id, "test_detail": detail},
            created_at=AFTER,
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    if hook_name == "boost_notification" and detail.get("test_sink"):
        detail = {"trade_id": TRADE, "applicable": False}
    if hook_name == "fill_classification":
        return database.store_authoritative_fill_classification_ack(
            fill_id,
            {
                "classification": "unknown",
                "spent_block_index": 42,
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    if hook_name == "sweep_registration" and detail.get("test_sink"):
        database.register_authoritative_sweep_fill(
            fill_id,
            {
                "trade_id": TRADE,
                "classification": "unknown",
                "spent_block_index": 42,
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
                "side": "buy",
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
        return database.acknowledge_authoritative_sweep_registration(
            fill_id,
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    parameters = inspect.signature(database.record_offer_fill_hook_sink_ack).parameters
    if "claim_token" in parameters:
        return database.record_offer_fill_hook_sink_ack(
            fill_id,
            hook_name,
            detail,
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    return database.record_offer_fill_hook_sink_ack(fill_id, hook_name, detail)


def _invoke_claimed_hook(callback, fill, claim):
    parameters = inspect.signature(callback).parameters
    if "claim_token" in parameters:
        return callback(
            fill,
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    return callback(fill)


def test_hook_claim_uses_db_wall_clock_and_returns_fenced_generation(
    isolated_database, monkeypatch
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: RECONCILED)

    claim = database.claim_offer_fill_hook(
        fill["fill_id"], "offer_filled_event", claimed_at=AT
    )
    stored = (
        database.get_connection()
        .execute(
            "SELECT * FROM offer_fill_hook_outbox WHERE fill_id=? AND hook_name=?",
            (fill["fill_id"], "offer_filled_event"),
        )
        .fetchone()
    )

    assert claim["status"] == "claimed"
    assert claim["claim_generation"] == 1
    assert stored["claimed_at"] == RECONCILED


def test_stale_generation_sink_ack_cannot_complete_newer_outbox_owner(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    first = database.claim_offer_fill_hook(fill["fill_id"], "offer_filled_event")
    _record_claimed_test_sink_ack(
        fill["fill_id"],
        "offer_filled_event",
        {"test_sink": "first-generation"},
        first,
    )

    clock["now"] = "2026-08-20T12:10:31.000000Z"
    second = database.claim_offer_fill_hook(fill["fill_id"], "offer_filled_event")

    with pytest.raises(ValueError, match="current delivery acknowledgement"):
        database.complete_offer_fill_hook(
            fill["fill_id"],
            "offer_filled_event",
            second["claim_token"],
            claim_generation=second["claim_generation"],
        )

    stored = (
        database.get_connection()
        .execute(
            "SELECT state, attempt, claim_token FROM offer_fill_hook_outbox "
            "WHERE fill_id=? AND hook_name='offer_filled_event'",
            (fill["fill_id"],),
        )
        .fetchone()
    )
    assert stored["state"] == "running"
    assert stored["attempt"] == second["claim_generation"]
    assert stored["claim_token"] == second["claim_token"]
    assert database.get_offer_fill_hook_receipts(fill["fill_id"]) == []


@pytest.mark.parametrize(
    ("hook_name", "detail"),
    [
        ("offer_filled_event", {"event_id": 99}),
        ("boost_notification", {"trade_id": TRADE, "applicable": True}),
        ("fill_classification", {"classification": "unknown"}),
        ("sweep_registration", {"trade_id": TRADE, "spent_block_index": 42}),
    ],
)
def test_generic_sink_ack_cannot_bypass_effect_specific_durable_boundary(
    isolated_database,
    monkeypatch,
    hook_name,
    detail,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    claim = database.claim_offer_fill_hook(fill["fill_id"], hook_name)

    with pytest.raises(ValueError, match="effect-specific durable boundary"):
        database.record_offer_fill_hook_sink_ack(
            fill["fill_id"],
            hook_name,
            detail,
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )

    assert not database.has_offer_fill_hook_delivery_ack(
        fill["fill_id"],
        hook_name,
        claim["claim_token"],
        claim["claim_generation"],
    )


def test_running_hook_heartbeat_prevents_steal_and_abandoned_claim_is_recovered(
    isolated_database, monkeypatch
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    first = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")

    clock["now"] = "2026-08-20T12:10:20.000000Z"
    assert database.heartbeat_offer_fill_hook(
        fill["fill_id"],
        "boost_notification",
        first["claim_token"],
        first["claim_generation"],
    )
    clock["now"] = "2026-08-20T12:10:40.000000Z"
    assert (
        database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")["status"]
        == "in_progress"
    )

    clock["now"] = "2026-08-20T12:10:51.000000Z"
    recovered = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    assert recovered["status"] == "claimed"
    assert recovered["redelivery"] is True
    assert recovered["claim_generation"] == first["claim_generation"] + 1
    assert not database.fail_offer_fill_hook(
        fill["fill_id"],
        "boost_notification",
        first["claim_token"],
        claim_generation=first["claim_generation"],
    )


def test_boost_false_result_is_retryable_failure_not_positive_acknowledgement(
    isolated_database,
    monkeypatch,
):
    original_runner = reconciliation._run_post_fill_hooks
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    monkeypatch.setattr(reconciliation, "_run_post_fill_hooks", original_runner)
    fill["tier"] = "boost"
    manager = SimpleNamespace(notify_boost_fill=lambda _trade_id: False)
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=manager)),
    )

    result = reconciliation._run_post_fill_hooks(fill, completed_at=AFTER)

    assert result["boost_notification"] == "failed"
    row = (
        database.get_connection()
        .execute(
            "SELECT state, last_error_code FROM offer_fill_hook_outbox "
            "WHERE fill_id=? AND hook_name='boost_notification'",
            (fill["fill_id"],),
        )
        .fetchone()
    )
    assert tuple(row) == ("pending", "CALLBACK_FAILED")
    assert "boost_notification" not in database.get_offer_fill_hook_receipts(
        fill["fill_id"]
    )


def test_heartbeat_uncertainty_after_durable_effect_never_resets_pending(
    isolated_database,
    monkeypatch,
):
    original_runner = reconciliation._run_post_fill_hooks
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    monkeypatch.setattr(reconciliation, "_run_post_fill_hooks", original_runner)
    monkeypatch.setattr(database, "_AUTHORITATIVE_FILL_HOOK_LEASE_SECONDS", 0.03)
    acknowledgement_written = threading.Event()
    heartbeat_failed = threading.Event()

    def uncertain_heartbeat(*_args, **_kwargs):
        assert acknowledgement_written.wait(timeout=1)
        heartbeat_failed.set()
        return False

    def callback(row, **claim):
        acknowledgement = _record_claimed_test_sink_ack(
            row["fill_id"],
            "offer_filled_event",
            {"test_sink": "effect-before-heartbeat-failure"},
            claim,
        )
        acknowledgement_written.set()
        assert heartbeat_failed.wait(timeout=1)
        return acknowledgement

    monkeypatch.setattr(database, "heartbeat_offer_fill_hook", uncertain_heartbeat)
    monkeypatch.setattr(
        reconciliation,
        "_post_fill_hook_callbacks",
        lambda _fill: {"offer_filled_event": callback},
    )

    result = reconciliation._run_post_fill_hooks(fill, completed_at=AFTER)

    assert result["offer_filled_event"] == "completed"
    row = (
        database.get_connection()
        .execute(
            "SELECT state, last_error_code FROM offer_fill_hook_outbox "
            "WHERE fill_id=? AND hook_name='offer_filled_event'",
            (fill["fill_id"],),
        )
        .fetchone()
    )
    assert tuple(row) == ("completed", None)


def test_callback_construction_failure_is_contained_after_proof_commit(
    isolated_database,
    monkeypatch,
):
    _persist_created_offer()
    monkeypatch.setattr(
        reconciliation,
        "_post_fill_hook_callbacks",
        lambda _fill: (_ for _ in ()).throw(RuntimeError("callback import failed")),
    )

    result = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert result["classification"] == FILLED_PROVEN
    assert result["applied"] is True
    assert result["post_fill_hooks"] == {
        name: "failed" for name in database._AUTHORITATIVE_FILL_HOOKS
    }
    rows = (
        database.get_connection()
        .execute(
            "SELECT hook_name, state, last_error_code FROM offer_fill_hook_outbox "
            "WHERE fill_id=? ORDER BY hook_name",
            (result["fill_id"],),
        )
        .fetchall()
    )
    assert [
        (row["hook_name"], row["state"], row["last_error_code"]) for row in rows
    ] == [
        (name, "pending", "CALLBACK_CONSTRUCTION_FAILED")
        for name in sorted(database._AUTHORITATIVE_FILL_HOOKS)
    ]


def test_production_classification_and_sweep_preserve_authoritative_block_42(
    isolated_database,
    monkeypatch,
):
    import sweep_coordinator

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    assert fill["spent_block_index"] == 42
    sweep_coordinator.reset_coordinator()
    callbacks = reconciliation._post_fill_hook_callbacks(fill)

    classification_claim = database.claim_offer_fill_hook(
        fill["fill_id"], "fill_classification"
    )
    classification_ack = _invoke_claimed_hook(
        callbacks["fill_classification"], fill, classification_claim
    )
    assert database.validate_offer_fill_hook_sink_ack(
        fill["fill_id"],
        "fill_classification",
        classification_ack,
        claim_token=classification_claim["claim_token"],
        claim_generation=classification_claim["claim_generation"],
    )
    assert database.complete_offer_fill_hook(
        fill["fill_id"],
        "fill_classification",
        classification_claim["claim_token"],
        claim_generation=classification_claim["claim_generation"],
    )

    sweep_claim = database.claim_offer_fill_hook(fill["fill_id"], "sweep_registration")
    sweep_ack = _invoke_claimed_hook(callbacks["sweep_registration"], fill, sweep_claim)
    assert database.validate_offer_fill_hook_sink_ack(
        fill["fill_id"],
        "sweep_registration",
        sweep_ack,
        claim_token=sweep_claim["claim_token"],
        claim_generation=sweep_claim["claim_generation"],
    )

    stored_fill = database.get_fill_by_id(fill["fill_id"])
    registrations = database.get_authoritative_sweep_registrations()
    coordinator = sweep_coordinator.get_coordinator()
    assert stored_fill["spent_block_index"] == 42
    assert registrations == [
        {
            "fill_id": fill["fill_id"],
            "trade_id": TRADE,
            "classification": "unknown",
            "spent_block_index": 42,
            "taker_puzzle_hash": None,
            "sweep_group_id": None,
            "side": "buy",
        }
    ]
    assert coordinator.get_pending_summary()["pending_fill_count"] == 1


def test_recreated_production_boost_manager_uses_durable_fill_command(
    isolated_database,
    monkeypatch,
):
    from boost_manager import BoostManager

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    fill["tier"] = "boost"
    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    first_manager = BoostManager()
    first_manager._buy_probe_tid_history.add(TRADE)
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=first_manager)),
    )
    first_claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    first_callback = reconciliation._post_fill_hook_callbacks(fill)[
        "boost_notification"
    ]
    _invoke_claimed_hook(first_callback, fill, first_claim)

    clock["now"] = "2026-08-20T12:10:31.000000Z"
    recreated_manager = BoostManager()
    legacy_results = []
    legacy_notify = recreated_manager.notify_boost_fill

    def observe_legacy_notify(trade_id):
        result = legacy_notify(trade_id)
        legacy_results.append(result)
        return result

    recreated_manager.notify_boost_fill = observe_legacy_notify
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=recreated_manager)),
    )
    recovered_claim = database.claim_offer_fill_hook(
        fill["fill_id"], "boost_notification"
    )
    recovered_callback = reconciliation._post_fill_hook_callbacks(fill)[
        "boost_notification"
    ]
    acknowledgement = _invoke_claimed_hook(recovered_callback, fill, recovered_claim)
    assert database.complete_offer_fill_hook(
        fill["fill_id"],
        "boost_notification",
        recovered_claim["claim_token"],
        claim_generation=recovered_claim["claim_generation"],
    )

    assert acknowledgement["detail"]["trade_id"] == TRADE
    assert legacy_results == []
    assert "boost_notification" in database.get_offer_fill_hook_receipts(
        fill["fill_id"]
    )


def test_recreated_production_boost_manager_materializes_settlement_and_floor(
    isolated_database,
    monkeypatch,
):
    from boost_manager import BoostManager

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    fill["tier"] = "boost"
    first_manager = BoostManager()
    first_manager._buy_offset_bps = 137
    first_manager._buy_last_safe_offset_bps = 121
    first_manager._buy_probe_tid_history.add(TRADE)
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=first_manager)),
    )
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    callback = reconciliation._post_fill_hook_callbacks(fill)["boost_notification"]

    acknowledgement = _invoke_claimed_hook(callback, fill, claim)
    assert acknowledgement["disposition"] == "applied"
    assert first_manager._buy_settled is True
    assert first_manager._buy_floor_bps == 137

    recreated_manager = BoostManager()

    assert recreated_manager._buy_settled is True
    assert recreated_manager._buy_floor_bps == 137
    assert recreated_manager._buy_offset_bps == 137
    assert recreated_manager._buy_last_safe_offset_bps == 121


def test_boost_command_primary_identity_cannot_rebind_during_apply_transition(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    other_fill = _insert_authoritative_test_fill(OTHER_TRADE)
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    database.register_authoritative_boost_fill_command(
        fill["fill_id"],
        TRADE,
        "buy",
        materialization=_boost_materialization(fill["fill_id"]),
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    conn = database.get_connection()

    with pytest.raises(Exception, match="transition is invalid"):
        conn.execute(
            "UPDATE offer_fill_boost_commands "
            "SET fill_id=?, state='applied', applied_at=? WHERE fill_id=?",
            (other_fill["fill_id"], AFTER, fill["fill_id"]),
        )

    conn.rollback()
    stored = conn.execute(
        "SELECT fill_id, trade_id, state FROM offer_fill_boost_commands"
    ).fetchall()
    assert [tuple(row) for row in stored] == [(fill["fill_id"], TRADE, "registered")]


def test_recreated_boost_manager_consumes_registered_command_after_crash(
    isolated_database,
    monkeypatch,
):
    from boost_manager import BoostManager

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    fill["tier"] = "boost"
    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    abandoned = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    database.register_authoritative_boost_fill_command(
        fill["fill_id"],
        TRADE,
        "buy",
        materialization=_boost_materialization(fill["fill_id"]),
        claim_token=abandoned["claim_token"],
        claim_generation=abandoned["claim_generation"],
    )

    clock["now"] = "2026-08-20T12:10:31.000000Z"
    recreated = BoostManager()
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=recreated)),
    )
    recovered = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    callback = reconciliation._post_fill_hook_callbacks(fill)["boost_notification"]

    acknowledgement = _invoke_claimed_hook(callback, fill, recovered)

    assert acknowledgement["disposition"] == "applied"
    assert recreated._buy_settled is True


def test_registered_boost_crash_replays_exact_pre_effect_materialization(
    isolated_database,
    monkeypatch,
):
    """A crash after command registration must not replay from zero defaults."""

    from boost_manager import BoostManager

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    fill["tier"] = "boost"
    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    first_manager = BoostManager()
    first_manager._buy_offset_bps = 137
    first_manager._buy_floor_bps = 0
    first_manager._buy_last_safe_offset_bps = 121
    first_manager._buy_probe_tid = TRADE
    first_manager._buy_probe_tid_history.add(TRADE)

    def crash_after_registration(*_args, **_kwargs):
        raise SystemExit("simulated crash after durable Boost registration")

    first_manager.notify_authoritative_boost_fill = crash_after_registration
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=first_manager)),
    )
    abandoned = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    callback = reconciliation._post_fill_hook_callbacks(fill)["boost_notification"]

    with pytest.raises(SystemExit, match="after durable Boost registration"):
        _invoke_claimed_hook(callback, fill, abandoned)

    clock["now"] = "2026-08-20T12:10:31.000000Z"
    recreated = BoostManager()
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=recreated)),
    )
    recovered = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    acknowledgement = _invoke_claimed_hook(
        reconciliation._post_fill_hook_callbacks(fill)["boost_notification"],
        fill,
        recovered,
    )

    assert acknowledgement["disposition"] == "applied"
    assert recreated._buy_settled is True
    assert recreated._buy_offset_bps == 137
    assert recreated._buy_floor_bps == 137
    assert recreated._buy_last_safe_offset_bps == 121
    materialization_row = (
        database.get_connection()
        .execute(
            "SELECT materialization_json, materialization_sha256 "
            "FROM offer_fill_boost_command_materializations WHERE fill_id=?",
            (fill["fill_id"],),
        )
        .fetchone()
    )
    assert materialization_row is not None
    assert (
        hashlib.sha256(materialization_row["materialization_json"].encode()).hexdigest()
        == (materialization_row["materialization_sha256"])
    )


def test_boost_command_rejects_changed_materialization_replay(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    fill["tier"] = "boost"
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    materialization = _boost_materialization(fill["fill_id"])
    database.register_authoritative_boost_fill_command(
        fill["fill_id"],
        TRADE,
        "buy",
        materialization=materialization,
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )

    changed = dict(materialization, offset_bps=138, floor_bps=138)
    with pytest.raises(ValueError, match="materialization replay differs"):
        database.register_authoritative_boost_fill_command(
            fill["fill_id"],
            TRADE,
            "buy",
            materialization=changed,
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )


def test_migration_audits_registered_boost_command_without_materialization(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO offer_fill_boost_commands "
        "(fill_id, trade_id, side, state, registered_at, applied_at) "
        "VALUES (?, ?, 'buy', 'registered', ?, NULL)",
        (fill["fill_id"], TRADE, AFTER),
    )
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    audit = (
        database.get_connection()
        .execute(
            "SELECT reason_code, prior_state FROM offer_fill_hook_migration_audit "
            "WHERE fill_id=? AND hook_name='boost_notification'",
            (fill["fill_id"],),
        )
        .fetchone()
    )
    assert tuple(audit) == (
        "BOOST_COMMAND_MISSING_MATERIALIZATION",
        "registered",
    )


def test_legacy_boost_command_without_materialization_is_blocked_not_recaptured(
    isolated_database,
    monkeypatch,
):
    from boost_manager import BoostManager

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    fill["tier"] = "boost"
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO offer_fill_boost_commands "
        "(fill_id, trade_id, side, state, registered_at, applied_at) "
        "VALUES (?, ?, 'buy', 'registered', ?, NULL)",
        (fill["fill_id"], TRADE, AFTER),
    )
    conn.commit()
    database.close_connection()
    database._migrate_stability_schema()

    manager = BoostManager()
    manager._buy_offset_bps = 999
    manager._buy_last_safe_offset_bps = 888
    manager._buy_probe_tid = TRADE
    manager._buy_probe_tid_history.add(TRADE)
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=manager)),
    )
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    callback = reconciliation._post_fill_hook_callbacks(fill)["boost_notification"]

    with pytest.raises(RuntimeError, match="missing immutable materialization"):
        _invoke_claimed_hook(callback, fill, claim)

    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_boost_command_materializations "
            "WHERE fill_id=?",
            (fill["fill_id"],),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_boost_effects WHERE fill_id=?",
            (fill["fill_id"],),
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='gap_closer_buy_arbed'"
        ).fetchone()[0]
        == 0
    )
    audit = conn.execute(
        "SELECT reason_code, prior_state FROM offer_fill_hook_migration_audit "
        "WHERE fill_id=? AND hook_name='boost_notification'",
        (fill["fill_id"],),
    ).fetchone()
    assert tuple(audit) == (
        "BOOST_COMMAND_MISSING_MATERIALIZATION",
        "registered",
    )
    assert manager._buy_offset_bps == 999
    assert manager._buy_settled is False
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_boost_effect_and_log_are_durable_before_process_apply_and_replay_once(
    isolated_database,
    monkeypatch,
):
    from boost_manager import BoostManager

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    fill["tier"] = "boost"
    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    first = BoostManager()
    first._buy_offset_bps = 137
    first._buy_last_safe_offset_bps = 121
    first._buy_probe_tid = TRADE
    first._buy_probe_tid_history.add(TRADE)
    observations = []

    def crash_before_process_apply(*_args, **_kwargs):
        conn = database.get_connection()
        observations.append(
            (
                conn.execute(
                    "SELECT COUNT(*) FROM offer_fill_boost_effects WHERE fill_id=?",
                    (fill["fill_id"],),
                ).fetchone()[0],
                conn.execute(
                    "SELECT COUNT(*) FROM offer_fill_boost_log_sinks WHERE fill_id=?",
                    (fill["fill_id"],),
                ).fetchone()[0],
            )
        )
        raise SystemExit("crash before process Boost apply")

    first.notify_authoritative_boost_fill = crash_before_process_apply
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=first)),
    )
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    callback = reconciliation._post_fill_hook_callbacks(fill)["boost_notification"]

    with pytest.raises(SystemExit, match="before process Boost apply"):
        _invoke_claimed_hook(callback, fill, claim)

    assert observations == [(1, 1)]
    recreated = BoostManager()
    assert recreated._buy_settled is True
    assert recreated._buy_offset_bps == 137
    assert recreated._buy_floor_bps == 137
    assert recreated._buy_last_safe_offset_bps == 121

    clock["now"] = "2026-08-20T12:10:31.000000Z"
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=recreated)),
    )
    recovered = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    acknowledgement = _invoke_claimed_hook(
        reconciliation._post_fill_hook_callbacks(fill)["boost_notification"],
        fill,
        recovered,
    )

    assert acknowledgement["disposition"] == "applied"
    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT state FROM offer_fill_boost_commands WHERE fill_id=?",
            (fill["fill_id"],),
        ).fetchone()[0]
        == "applied"
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_boost_effects WHERE fill_id=?",
            (fill["fill_id"],),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_boost_log_sinks WHERE fill_id=?",
            (fill["fill_id"],),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='gap_closer_buy_arbed'"
        ).fetchone()[0]
        == 1
    )


def test_boost_crash_after_process_apply_replays_without_duplicate_log(
    isolated_database,
    monkeypatch,
):
    from boost_manager import BoostManager

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    fill["tier"] = "boost"
    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    manager = BoostManager()
    manager._buy_offset_bps = 137
    manager._buy_last_safe_offset_bps = 121
    manager._buy_probe_tid = TRADE
    manager._buy_probe_tid_history.add(TRADE)
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=manager)),
    )
    real_complete = database.complete_authoritative_boost_fill_command
    monkeypatch.setattr(
        database,
        "complete_authoritative_boost_fill_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SystemExit("crash after process Boost apply")
        ),
    )
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")

    with pytest.raises(SystemExit, match="after process Boost apply"):
        _invoke_claimed_hook(
            reconciliation._post_fill_hook_callbacks(fill)["boost_notification"],
            fill,
            claim,
        )

    monkeypatch.setattr(
        database, "complete_authoritative_boost_fill_command", real_complete
    )
    recreated = BoostManager()
    assert recreated._buy_settled is True
    assert recreated._buy_floor_bps == 137
    clock["now"] = "2026-08-20T12:10:31.000000Z"
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=recreated)),
    )
    recovered = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    acknowledgement = _invoke_claimed_hook(
        reconciliation._post_fill_hook_callbacks(fill)["boost_notification"],
        fill,
        recovered,
    )

    assert acknowledgement["disposition"] == "applied"
    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_boost_effects WHERE fill_id=?",
            (fill["fill_id"],),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_boost_log_sinks WHERE fill_id=?",
            (fill["fill_id"],),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='gap_closer_buy_arbed'"
        ).fetchone()[0]
        == 1
    )


def test_migration_backfills_prior_boost_effect_log_sink(
    isolated_database,
    monkeypatch,
):
    from boost_manager import BoostManager

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    claim = database.claim_offer_fill_hook(fill["fill_id"], "boost_notification")
    database.register_authoritative_boost_fill_command(
        fill["fill_id"],
        TRADE,
        "buy",
        materialization=_boost_materialization(fill["fill_id"]),
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    database.materialize_authoritative_boost_fill_effect(
        fill["fill_id"],
        TRADE,
        "buy",
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    conn = database.get_connection()
    event_log_id = conn.execute(
        "SELECT event_log_id FROM offer_fill_boost_log_sinks WHERE fill_id=?",
        (fill["fill_id"],),
    ).fetchone()[0]
    conn.execute("DROP TABLE offer_fill_boost_log_sinks")
    conn.execute("DELETE FROM events WHERE id=?", (event_log_id,))
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_boost_log_sinks WHERE fill_id=?",
            (fill["fill_id"],),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='gap_closer_buy_arbed'"
        ).fetchone()[0]
        == 1
    )
    recreated = BoostManager()
    assert recreated._buy_settled is True
    assert recreated._buy_offset_bps == 137
    assert recreated._buy_floor_bps == 137
    assert recreated._buy_last_safe_offset_bps == 121


def test_migration_backfills_prior_sweep_effect_safety_summary(
    isolated_database,
    monkeypatch,
):
    clock = {"now": "2099-08-20T12:00:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    effect = _insert_materialized_sweep_effect(
        index=88,
        classification="arb_sweep_buy",
        side="buy",
        finalized_at=clock["now"],
    )
    conn = database.get_connection()
    conn.execute("DROP TABLE offer_fill_sweep_safety_state")
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    assert database.get_authoritative_sweep_safety_state() == [
        {
            "side": "sell",
            "event_id": effect["event_id"],
            "expires_at": effect["protected_sides"][0]["expires_at"],
            "effect_at": effect["effect_at"],
        }
    ]


def test_recreated_production_sweep_coordinator_reconstructs_durable_registration(
    isolated_database,
    monkeypatch,
):
    import fill_classifier
    import sweep_coordinator

    fill = _commit_fill_without_draining_hooks(monkeypatch)
    classification = SimpleNamespace(
        trade_id=TRADE,
        classification="unknown",
        spent_block_index=42,
        taker_puzzle_hash=None,
        sweep_group_id=None,
        side="buy",
    )
    monkeypatch.setattr(
        fill_classifier, "classify_fill", lambda *_a, **_k: classification
    )
    sweep_coordinator.reset_coordinator()
    claim = database.claim_offer_fill_hook(fill["fill_id"], "sweep_registration")
    callback = reconciliation._post_fill_hook_callbacks(fill)["sweep_registration"]
    _invoke_claimed_hook(callback, fill, claim)
    assert database.complete_offer_fill_hook(
        fill["fill_id"],
        "sweep_registration",
        claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )

    sweep_coordinator.reset_coordinator()
    recreated = sweep_coordinator.get_coordinator()

    assert recreated.get_pending_summary()["pending_fill_count"] == 1


def test_sweep_coordinator_bounds_active_and_recent_fill_identity_buffers(
    isolated_database,
    monkeypatch,
):
    import sweep_coordinator

    monkeypatch.setattr(sweep_coordinator, "_MAX_ACTIVE_FILLS", 3)
    monkeypatch.setattr(sweep_coordinator, "_MAX_RECENT_FILL_IDS", 3)
    coordinator = sweep_coordinator.SweepCoordinator(window_secs=60)

    def classification(fill_id):
        return SimpleNamespace(
            trade_id=f"{fill_id:064x}",
            classification="unknown",
            spent_block_index=fill_id,
            taker_puzzle_hash=None,
            side="buy",
        )

    for fill_id in range(1, 4):
        coordinator.process_fill(fill_id, classification(fill_id))
    coordinator.process_authoritative_fill(4, classification(4))

    assert coordinator.get_pending_summary()["pending_fill_count"] == 3
    assert coordinator.has_registered_fill(4) is False
    assert coordinator._durable_fill_ids == set()

    coordinator._window_secs = 0
    coordinator.tick()
    assert len(coordinator._registered_fill_ids) == 0
    assert len(coordinator._recent_fill_ids) == 3

    for fill_id in range(4, 7):
        coordinator.process_fill(fill_id, classification(fill_id))
        coordinator.tick()

    assert len(coordinator._registered_fill_ids) == 0
    assert len(coordinator._recent_fill_ids) == 3
    assert len(coordinator._recent_fill_order) == 3


def _finalize_test_authoritative_sweep(monkeypatch, *, block_index: int = 42) -> dict:
    from config import cfg

    first_fill = _commit_fill_without_draining_hooks(monkeypatch)
    second_fill = _insert_authoritative_test_fill(OTHER_TRADE, block_height=block_index)
    monkeypatch.setattr(cfg, "SWEEP_MIN_FILLS", 2)
    for fill in (first_fill, second_fill):
        claim = database.claim_offer_fill_hook(fill["fill_id"], "sweep_registration")
        database.register_authoritative_sweep_fill(
            fill["fill_id"],
            {
                "trade_id": fill["trade_id"],
                "classification": "unknown",
                "spent_block_index": block_index,
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
                "side": "buy",
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )
    return database.finalize_authoritative_sweep_registrations(
        [first_fill["fill_id"], second_fill["fill_id"]],
        block_index,
        f"sweep_{block_index}",
    )


def _insert_materialized_sweep_effect(
    *,
    index: int,
    classification: str,
    side: str,
    finalized_at: str,
) -> dict:
    block_index = 10_000 + index
    payload, encoded, event_id = database._canonical_authoritative_sweep_event(
        block_index,
        f"sweep_restore_{block_index}",
        [
            {
                "fill_id": 20_000 + index,
                "trade_id": f"{30_000 + index:064x}",
                "classification": classification,
                "spent_block_index": block_index,
                "taker_puzzle_hash": None,
                "side": side,
            }
        ],
    )
    assert payload["spent_block_index"] == block_index
    token = f"{40_000 + index:064x}"
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO offer_fill_sweep_events "
        "(event_id, spent_block_index, sweep_group_id, event_json, finalized_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_id, block_index, payload["sweep_group_id"], encoded, finalized_at),
    )
    conn.execute(
        "INSERT INTO offer_fill_sweep_delivery_queue "
        "(event_id, state, generation, claim_token, claimed_at, completed_at, queued_at) "
        "VALUES (?, 'running', 1, ?, ?, NULL, ?)",
        (event_id, token, finalized_at, finalized_at),
    )
    conn.commit()
    return database.materialize_authoritative_sweep_downstream_effect(
        event_id,
        token,
        1,
        known_protection_seconds=90,
        unknown_protection_seconds=30,
    )


def test_sweep_restore_preserves_both_sides_beyond_recent_effect_window(
    isolated_database,
    monkeypatch,
):
    import dynamic_amm_buffer
    import wallet_sage

    clock = {"now": "2099-08-20T12:00:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    epoch = datetime.fromisoformat(clock["now"].replace("Z", "+00:00")).timestamp()
    monkeypatch.setattr(bot_loop.time, "time", lambda: epoch)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, *_args, **_kwargs: (
            {"fingerprint": 123, "name": "test"}
            if endpoint == "get_key"
            else {"success": True}
        ),
    )
    dynamic_amm_buffer.reset_buffer()

    oldest_sell_protection = _insert_materialized_sweep_effect(
        index=0,
        classification="arb_sweep_buy",
        side="buy",
        finalized_at=clock["now"],
    )
    for index in range(1, 22):
        clock["now"] = f"2099-08-20T12:00:{index:02d}.000000Z"
        _insert_materialized_sweep_effect(
            index=index,
            classification="arb_sweep_sell",
            side="sell",
            finalized_at=clock["now"],
        )

    dynamic_amm_buffer.reset_buffer()
    recreated = bot_loop.BotLoop()

    expected_sell = recreated._sweep_timestamp_epoch(
        oldest_sell_protection["protected_sides"][0]["expires_at"]
    )
    assert recreated._sweep_protection["sell"] == expected_sell
    assert recreated._sweep_protection["buy"] > expected_sell
    assert len(recreated._recent_sweep_events) <= 20
    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] <= 20


def test_normal_bot_start_restores_sweep_safety_after_runtime_reset(
    isolated_database,
    monkeypatch,
):
    import dynamic_amm_buffer
    import wallet_sage
    from config import cfg

    clock = {"now": "2099-08-20T12:00:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    epoch = datetime.fromisoformat(clock["now"].replace("Z", "+00:00")).timestamp()
    monkeypatch.setattr(bot_loop.time, "time", lambda: epoch)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, *_args, **_kwargs: (
            {"fingerprint": 123, "name": "test"}
            if endpoint == "get_key"
            else {"success": True}
        ),
    )
    effect = _insert_materialized_sweep_effect(
        index=1,
        classification="arb_sweep_sell",
        side="sell",
        finalized_at=clock["now"],
    )
    dynamic_amm_buffer.reset_buffer()
    loop = bot_loop.BotLoop()
    expected_expiry = loop._sweep_timestamp_epoch(
        effect["protected_sides"][0]["expires_at"]
    )
    assert loop._sweep_protection["buy"] == expected_expiry

    failed_check = SimpleNamespace(status="fail", name="test stop", message="stop")
    preflight = SimpleNamespace(
        can_start=False,
        summary="test stop after reset",
        duration_ms=0,
        checks=[failed_check],
        to_dict=lambda: {"can_start": False},
    )
    monkeypatch.setattr(cfg, "reload", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "doctor",
        SimpleNamespace(run_preflight=lambda **_kwargs: preflight),
    )

    assert loop.start() is False
    assert loop._sweep_protection["buy"] == expected_expiry
    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] == 1


def test_sweep_restore_failure_is_conservative(monkeypatch):
    loop = object.__new__(bot_loop.BotLoop)
    loop._sweep_protection = {}
    loop._recent_sweep_events = []
    monkeypatch.setattr(
        database,
        "get_authoritative_sweep_downstream_effects",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("corrupt safety state")),
    )

    loop._restore_authoritative_sweep_downstream_effects()

    assert loop._sweep_protection == {"buy": float("inf"), "sell": float("inf")}


def test_concurrent_sweep_coordinators_have_one_fenced_delivery_owner(
    isolated_database,
    monkeypatch,
):
    import sweep_coordinator

    stored = _finalize_test_authoritative_sweep(monkeypatch)
    first = sweep_coordinator.SweepCoordinator(window_secs=0)
    second = sweep_coordinator.SweepCoordinator(window_secs=0)

    deliveries = first.drain_sweep_events() + second.drain_sweep_events()

    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.event_id == stored["event_id"]
    assert type(delivery.claim_token) is str and len(delivery.claim_token) == 64
    assert delivery.claim_generation == 1
    assert (
        database.get_connection()
        .execute(
            "SELECT 1 FROM offer_fill_sweep_event_receipts WHERE event_id=?",
            (stored["event_id"],),
        )
        .fetchone()
        is None
    )


def test_sweep_claim_crash_before_ack_is_recoverable_and_fenced(
    isolated_database,
    monkeypatch,
):
    import sweep_coordinator

    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    stored = _finalize_test_authoritative_sweep(monkeypatch)
    abandoned = sweep_coordinator.SweepCoordinator(window_secs=0).drain_sweep_events()
    assert len(abandoned) == 1

    clock["now"] = "2026-08-20T12:10:31.000000Z"
    recovered = sweep_coordinator.SweepCoordinator(window_secs=0).drain_sweep_events()

    assert len(recovered) == 1
    assert recovered[0].event_id == stored["event_id"]
    assert recovered[0].claim_generation == abandoned[0].claim_generation + 1
    with pytest.raises(ValueError, match="current owner"):
        database.materialize_authoritative_sweep_downstream_effect(
            stored["event_id"],
            abandoned[0].claim_token,
            abandoned[0].claim_generation,
            known_protection_seconds=90,
            unknown_protection_seconds=30,
        )
    effect = database.materialize_authoritative_sweep_downstream_effect(
        stored["event_id"],
        recovered[0].claim_token,
        recovered[0].claim_generation,
        known_protection_seconds=90,
        unknown_protection_seconds=30,
    )
    assert effect["event_id"] == stored["event_id"]
    assert database.consume_authoritative_sweep_event(
        stored["event_id"],
        recovered[0].claim_token,
        recovered[0].claim_generation,
    )
    assert not database.consume_authoritative_sweep_event(
        stored["event_id"],
        recovered[0].claim_token,
        recovered[0].claim_generation,
    )
    with pytest.raises(ValueError, match="current owner"):
        database.consume_authoritative_sweep_event(
            stored["event_id"], "0" * 64, recovered[0].claim_generation
        )


def test_real_bot_loop_sweep_effect_is_durable_and_fresh_process_idempotent(
    isolated_database,
    monkeypatch,
):
    import dynamic_amm_buffer
    import sweep_coordinator
    import wallet_sage

    stored = _finalize_test_authoritative_sweep(monkeypatch)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, *_a, **_k: (
            {"fingerprint": 123, "name": "test"}
            if endpoint == "get_key"
            else {"success": True}
        ),
    )
    dynamic_amm_buffer.reset_buffer()
    sweep_coordinator.reset_coordinator()
    first_loop = bot_loop.BotLoop()

    assert first_loop._process_authoritative_sweep_events() == 1
    assert first_loop._sweep_protection["buy"] > 0
    assert [event["event_id"] for event in first_loop._recent_sweep_events] == [
        stored["event_id"]
    ]
    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] == 1

    # A recreated production loop rebuilds the exact durable effect.  Resetting
    # both process singletons models a fresh interpreter without synthetic sets.
    dynamic_amm_buffer.reset_buffer()
    sweep_coordinator.reset_coordinator()
    recreated_loop = bot_loop.BotLoop()

    assert recreated_loop._sweep_protection["buy"] > 0
    assert [event["event_id"] for event in recreated_loop._recent_sweep_events] == [
        stored["event_id"]
    ]
    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] == 1
    assert recreated_loop._process_authoritative_sweep_events() == 0
    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] == 1
    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_downstream_effects WHERE event_id=?",
            (stored["event_id"],),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_log_sinks WHERE event_id=?",
            (stored["event_id"],),
        ).fetchone()[0]
        == 1
    )


def test_restored_dynamic_buffer_preserves_durable_sweep_age(monkeypatch):
    import dynamic_amm_buffer
    from config import cfg

    monotonic = {"now": 1_000.0}
    monkeypatch.setattr(dynamic_amm_buffer.time, "monotonic", lambda: monotonic["now"])
    monkeypatch.setattr(bot_loop.time, "time", lambda: 150.0)
    monkeypatch.setattr(cfg, "DYNAMIC_BUFFER_WINDOW_MINS", 1, raising=False)
    dynamic_amm_buffer.reset_buffer()
    loop = object.__new__(bot_loop.BotLoop)
    loop._sweep_protection = {}
    loop._recent_sweep_events = []

    loop._apply_authoritative_sweep_downstream_effect(
        {
            "event_id": "a" * 64,
            "effect_at": "1970-01-01T00:01:40.000000Z",
            "protected_sides": [],
            "recent_events": [],
            "buffer_fill_count": 2,
        }
    )

    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] == 1
    monotonic["now"] += 11.0
    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] == 0


def test_real_bot_loop_partial_effect_crash_redelivers_without_duplicate_effects(
    isolated_database,
    monkeypatch,
):
    import dynamic_amm_buffer
    import sweep_coordinator
    import wallet_sage

    clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: clock["now"])
    effect_epoch = datetime.fromisoformat(
        clock["now"].replace("Z", "+00:00")
    ).timestamp()
    monkeypatch.setattr(bot_loop.time, "time", lambda: effect_epoch)
    stored = _finalize_test_authoritative_sweep(monkeypatch)
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, *_a, **_k: (
            {"fingerprint": 123, "name": "test"}
            if endpoint == "get_key"
            else {"success": True}
        ),
    )
    dynamic_amm_buffer.reset_buffer()
    sweep_coordinator.reset_coordinator()
    first_loop = bot_loop.BotLoop()
    real_consume = database.consume_authoritative_sweep_event
    monkeypatch.setattr(
        database,
        "consume_authoritative_sweep_event",
        lambda *_a, **_k: (_ for _ in ()).throw(
            RuntimeError("crash after process effects")
        ),
    )

    assert first_loop._process_authoritative_sweep_events() == 0
    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] == 1
    assert len(first_loop._recent_sweep_events) == 1

    monkeypatch.setattr(database, "consume_authoritative_sweep_event", real_consume)
    clock["now"] = "2026-08-20T12:10:31.000000Z"
    sweep_coordinator.reset_coordinator()
    recreated_loop = bot_loop.BotLoop()

    assert recreated_loop._process_authoritative_sweep_events() == 1
    assert dynamic_amm_buffer.get_state()["sweep_count_in_window"] == 1
    assert len(recreated_loop._recent_sweep_events) == 1
    conn = database.get_connection()
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_downstream_effects WHERE event_id=?",
            (stored["event_id"],),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_log_sinks WHERE event_id=?",
            (stored["event_id"],),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_event_receipts WHERE event_id=?",
            (stored["event_id"],),
        ).fetchone()[0]
        == 1
    )


def test_sweep_auxiliary_compaction_is_bounded_and_preserves_immutable_audit(
    isolated_database,
    monkeypatch,
):
    import sweep_coordinator

    stored = _finalize_test_authoritative_sweep(monkeypatch)
    delivery = sweep_coordinator.SweepCoordinator(window_secs=0).drain_sweep_events()[0]
    database.materialize_authoritative_sweep_downstream_effect(
        stored["event_id"],
        delivery.claim_token,
        delivery.claim_generation,
        known_protection_seconds=90,
        unknown_protection_seconds=30,
    )
    assert database.consume_authoritative_sweep_event(
        stored["event_id"], delivery.claim_token, delivery.claim_generation
    )
    conn = database.get_connection()
    immutable_before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "offer_fill_sweep_registrations",
            "offer_fill_sweep_finalizations",
            "offer_fill_sweep_events",
            "offer_fill_sweep_event_receipts",
            "offer_fill_sweep_downstream_effects",
            "offer_fill_sweep_log_sinks",
            "offer_fill_sweep_delivery_acks",
        )
    }

    compacted = database.compact_authoritative_sweep_auxiliary_state(limit=1)

    assert compacted == {"deliveries": 1, "registrations": 1}
    assert (
        conn.execute("SELECT COUNT(*) FROM offer_fill_sweep_delivery_queue").fetchone()[
            0
        ]
        == 0
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_registration_queue"
        ).fetchone()[0]
        == 1
    )
    assert {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in immutable_before
    } == immutable_before


def test_large_immutable_sweep_history_does_not_enter_active_queue_traversal(
    isolated_database,
    monkeypatch,
):
    pending = _finalize_test_authoritative_sweep(monkeypatch)
    conn = database.get_connection()
    historical_events = []
    historical_receipts = []
    for index in range(256):
        block_index = 1000 + index
        trade_id = f"{index + 100:064x}"
        payload, encoded, event_id = database._canonical_authoritative_sweep_event(
            block_index,
            f"sweep_history_{block_index}",
            [
                {
                    "fill_id": 10_000 + index,
                    "trade_id": trade_id,
                    "classification": "unknown",
                    "spent_block_index": block_index,
                    "taker_puzzle_hash": None,
                    "side": "buy",
                }
            ],
        )
        assert payload["spent_block_index"] == block_index
        historical_events.append(
            (event_id, block_index, payload["sweep_group_id"], encoded, AFTER)
        )
        historical_receipts.append((event_id, AFTER))
    conn.executemany(
        "INSERT INTO offer_fill_sweep_events "
        "(event_id, spent_block_index, sweep_group_id, event_json, finalized_at) "
        "VALUES (?, ?, ?, ?, ?)",
        historical_events,
    )
    conn.executemany(
        "INSERT INTO offer_fill_sweep_event_receipts (event_id, consumed_at) "
        "VALUES (?, ?)",
        historical_receipts,
    )
    for index in range(128):
        trade_id = f"{index + 1000:064x}"
        block_index = 2000 + index
        fill_id = database.record_fill(
            trade_id,
            "buy",
            price_xch=database.Decimal("0.1"),
            size_xch=database.Decimal("1"),
            size_cat=database.Decimal("1"),
            cat_asset_id=ASSET,
            verification_status="verified",
            filled_at=AFTER,
        )
        conn.execute(
            "UPDATE fills SET spent_block_index=? WHERE fill_id=?",
            (block_index, fill_id),
        )
        classification, encoded = (
            database._canonical_authoritative_sweep_classification(
                {
                    "trade_id": trade_id,
                    "classification": "unknown",
                    "spent_block_index": block_index,
                    "taker_puzzle_hash": None,
                    "sweep_group_id": None,
                    "side": "buy",
                }
            )
        )
        assert classification["trade_id"] == trade_id
        conn.execute(
            "INSERT INTO offer_fill_sweep_registrations "
            "(fill_id, trade_id, classification_json, registered_at) "
            "VALUES (?, ?, ?, ?)",
            (fill_id, trade_id, encoded, AFTER),
        )
        conn.execute(
            "INSERT INTO offer_fill_sweep_finalizations "
            "(fill_id, event_id, finalized_at) VALUES (?, NULL, ?)",
            (fill_id, AFTER),
        )
    conn.commit()
    active_fill = _insert_authoritative_test_fill("e" * 64, block_height=43)
    claim = database.claim_offer_fill_hook(active_fill["fill_id"], "sweep_registration")
    database.register_authoritative_sweep_fill(
        active_fill["fill_id"],
        {
            "trade_id": active_fill["trade_id"],
            "classification": "unknown",
            "spent_block_index": 43,
            "taker_puzzle_hash": None,
            "sweep_group_id": None,
            "side": "buy",
        },
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )

    assert [
        event["event_id"] for event in database.get_pending_authoritative_sweep_events()
    ] == [pending["event_id"]]
    assert [
        registration["fill_id"]
        for registration in database.get_authoritative_sweep_registrations()
    ] == [active_fill["fill_id"]]


def test_authoritative_sweep_active_cap_rejects_before_immutable_registration(
    isolated_database,
    monkeypatch,
):
    monkeypatch.setattr(database, "_MAX_AUTHORITATIVE_SWEEP_RESTORE", 1)
    first = _insert_authoritative_test_fill("d" * 64, block_height=42)
    second = _insert_authoritative_test_fill("e" * 64, block_height=43)

    def register(fill):
        claim = database.claim_offer_fill_hook(fill["fill_id"], "sweep_registration")
        return database.register_authoritative_sweep_fill(
            fill["fill_id"],
            {
                "trade_id": fill["trade_id"],
                "classification": "unknown",
                "spent_block_index": fill["spent_block_index"],
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
                "side": "buy",
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )

    register(first)
    with pytest.raises(ValueError, match="active limit"):
        register(second)

    conn = database.get_connection()
    assert (
        conn.execute("SELECT COUNT(*) FROM offer_fill_sweep_registrations").fetchone()[
            0
        ]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_registration_queue "
            "WHERE state='active'"
        ).fetchone()[0]
        == 1
    )


def test_authoritative_sweep_delivery_cap_rejects_before_event_finalization(
    isolated_database,
    monkeypatch,
):
    monkeypatch.setattr(database, "_MAX_PENDING_AUTHORITATIVE_SWEEP_EVENTS", 1)
    _finalize_test_authoritative_sweep(monkeypatch)
    fills = [
        _insert_authoritative_test_fill("e" * 64, block_height=43),
        _insert_authoritative_test_fill("f" * 64, block_height=43),
    ]
    for fill in fills:
        claim = database.claim_offer_fill_hook(fill["fill_id"], "sweep_registration")
        database.register_authoritative_sweep_fill(
            fill["fill_id"],
            {
                "trade_id": fill["trade_id"],
                "classification": "unknown",
                "spent_block_index": 43,
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
                "side": "buy",
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )

    with pytest.raises(ValueError, match="delivery active limit"):
        database.finalize_authoritative_sweep_registrations(
            [fill["fill_id"] for fill in fills], 43, "sweep_43"
        )

    conn = database.get_connection()
    assert (
        conn.execute("SELECT COUNT(*) FROM offer_fill_sweep_events").fetchone()[0] == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_finalizations "
            "WHERE fill_id IN (?, ?)",
            (fills[0]["fill_id"], fills[1]["fill_id"]),
        ).fetchone()[0]
        == 0
    )


def test_legacy_sweep_delivery_backfill_preflights_hard_cap(
    isolated_database,
    monkeypatch,
):
    conn = database.get_connection()
    rows = []
    for index in range(2):
        block_index = 100 + index
        payload, encoded, event_id = database._canonical_authoritative_sweep_event(
            block_index,
            f"sweep_{block_index}",
            [
                {
                    "fill_id": 10_000 + index,
                    "trade_id": f"{index + 100:064x}",
                    "classification": "unknown",
                    "spent_block_index": block_index,
                    "taker_puzzle_hash": None,
                    "side": "buy",
                }
            ],
        )
        assert payload["spent_block_index"] == block_index
        rows.append((event_id, block_index, payload["sweep_group_id"], encoded, AFTER))
    conn.executemany(
        "INSERT INTO offer_fill_sweep_events "
        "(event_id, spent_block_index, sweep_group_id, event_json, finalized_at) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("DROP TABLE offer_fill_sweep_delivery_queue")
    conn.commit()
    database.close_connection()
    monkeypatch.setattr(database, "_MAX_PENDING_AUTHORITATIVE_SWEEP_EVENTS", 1)

    with pytest.raises(RuntimeError, match="delivery events exceed hard limit"):
        database._migrate_stability_schema()


def test_legacy_sweep_receipt_without_effect_or_ack_is_requeued_and_applied_once(
    isolated_database,
    monkeypatch,
):
    import sweep_coordinator

    block_index = 142
    payload, encoded, event_id = database._canonical_authoritative_sweep_event(
        block_index,
        "legacy_sweep_142",
        [
            {
                "fill_id": 42_000,
                "trade_id": "4" * 64,
                "classification": "arb_sweep_sell",
                "spent_block_index": block_index,
                "taker_puzzle_hash": None,
                "side": "sell",
            }
        ],
    )
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO offer_fill_sweep_events "
        "(event_id, spent_block_index, sweep_group_id, event_json, finalized_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_id, block_index, payload["sweep_group_id"], encoded, AFTER),
    )
    conn.execute(
        "INSERT INTO offer_fill_sweep_event_receipts (event_id, consumed_at) "
        "VALUES (?, ?)",
        (event_id, AFTER),
    )
    conn.execute("DROP TABLE offer_fill_sweep_migration_audit")
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    conn = database.get_connection()
    queued = conn.execute(
        "SELECT state, generation FROM offer_fill_sweep_delivery_queue "
        "WHERE event_id=?",
        (event_id,),
    ).fetchone()
    assert tuple(queued) == ("pending", 0)
    audit = conn.execute(
        "SELECT reason_code FROM offer_fill_sweep_migration_audit WHERE event_id=?",
        (event_id,),
    ).fetchone()
    assert tuple(audit) == ("LEGACY_RECEIPT_MISSING_DOWNSTREAM_ACK",)

    delivery = sweep_coordinator.SweepCoordinator(window_secs=0).drain_sweep_events()
    assert len(delivery) == 1
    effect = database.materialize_authoritative_sweep_downstream_effect(
        event_id,
        delivery[0].claim_token,
        delivery[0].claim_generation,
        known_protection_seconds=90,
        unknown_protection_seconds=30,
    )
    assert effect["event_id"] == event_id
    assert database.consume_authoritative_sweep_event(
        event_id, delivery[0].claim_token, delivery[0].claim_generation
    )
    assert not database.consume_authoritative_sweep_event(
        event_id, delivery[0].claim_token, delivery[0].claim_generation
    )
    assert sweep_coordinator.SweepCoordinator(window_secs=0).drain_sweep_events() == []
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_event_receipts WHERE event_id=?",
            (event_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_downstream_effects WHERE event_id=?",
            (event_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM offer_fill_sweep_delivery_acks WHERE event_id=?",
            (event_id,),
        ).fetchone()[0]
        == 1
    )


def test_legacy_sweep_receipt_on_pending_queue_is_audited_and_acknowledged(
    isolated_database,
):
    import sweep_coordinator

    block_index = 143
    payload, encoded, event_id = database._canonical_authoritative_sweep_event(
        block_index,
        "legacy_sweep_pending_143",
        [
            {
                "fill_id": 42_001,
                "trade_id": "5" * 64,
                "classification": "arb_sweep_buy",
                "spent_block_index": block_index,
                "taker_puzzle_hash": None,
                "side": "buy",
            }
        ],
    )
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO offer_fill_sweep_events "
        "(event_id, spent_block_index, sweep_group_id, event_json, finalized_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_id, block_index, payload["sweep_group_id"], encoded, AFTER),
    )
    conn.execute(
        "INSERT INTO offer_fill_sweep_event_receipts (event_id, consumed_at) "
        "VALUES (?, ?)",
        (event_id, AFTER),
    )
    conn.execute(
        "INSERT INTO offer_fill_sweep_delivery_queue "
        "(event_id, state, generation, claim_token, claimed_at, completed_at, "
        " queued_at) VALUES (?, 'pending', 0, NULL, NULL, NULL, ?)",
        (event_id, AFTER),
    )
    conn.execute("DROP TABLE offer_fill_sweep_migration_audit")
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    delivery = sweep_coordinator.SweepCoordinator(window_secs=0).drain_sweep_events()
    assert len(delivery) == 1
    database.materialize_authoritative_sweep_downstream_effect(
        event_id,
        delivery[0].claim_token,
        delivery[0].claim_generation,
        known_protection_seconds=90,
        unknown_protection_seconds=30,
    )
    assert database.consume_authoritative_sweep_event(
        event_id, delivery[0].claim_token, delivery[0].claim_generation
    )
    audit = (
        database.get_connection()
        .execute(
            "SELECT reason_code FROM offer_fill_sweep_migration_audit WHERE event_id=?",
            (event_id,),
        )
        .fetchone()
    )
    assert tuple(audit) == ("LEGACY_RECEIPT_MISSING_DOWNSTREAM_ACK",)


def test_legacy_sweep_receipt_cannot_suppress_finalization_replay_delivery(
    isolated_database,
    monkeypatch,
):
    import sweep_coordinator

    block_index = 42
    first_fill = _commit_fill_without_draining_hooks(monkeypatch)
    second_fill = _insert_authoritative_test_fill(OTHER_TRADE, block_height=block_index)
    fill_ids = [first_fill["fill_id"], second_fill["fill_id"]]
    for fill in (first_fill, second_fill):
        claim = database.claim_offer_fill_hook(fill["fill_id"], "sweep_registration")
        database.register_authoritative_sweep_fill(
            fill["fill_id"],
            {
                "trade_id": fill["trade_id"],
                "classification": "unknown",
                "spent_block_index": block_index,
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
                "side": "buy",
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )

    conn = database.get_connection()
    event_fills = database._load_authoritative_sweep_event_fills(
        conn, fill_ids, block_index
    )
    payload, encoded, event_id = database._canonical_authoritative_sweep_event(
        block_index, "legacy_finalize_42", event_fills
    )
    conn.execute(
        "INSERT INTO offer_fill_sweep_events "
        "(event_id, spent_block_index, sweep_group_id, event_json, finalized_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_id, block_index, payload["sweep_group_id"], encoded, AFTER),
    )
    for fill_id in fill_ids:
        conn.execute(
            "INSERT INTO offer_fill_sweep_finalizations "
            "(fill_id, event_id, finalized_at) VALUES (?, ?, ?)",
            (fill_id, event_id, AFTER),
        )
        conn.execute(
            "UPDATE offer_fill_sweep_registration_queue "
            "SET state='finalized', finalized_at=?, event_id=? "
            "WHERE fill_id=? AND state='active'",
            (AFTER, event_id, fill_id),
        )
    conn.execute(
        "INSERT INTO offer_fill_sweep_event_receipts (event_id, consumed_at) "
        "VALUES (?, ?)",
        (event_id, AFTER),
    )
    conn.commit()

    replay = database.finalize_authoritative_sweep_registrations(
        fill_ids, block_index, "legacy_finalize_42"
    )

    assert replay["event_id"] == event_id
    delivery = sweep_coordinator.SweepCoordinator(window_secs=0).drain_sweep_events()
    assert len(delivery) == 1
    database.materialize_authoritative_sweep_downstream_effect(
        event_id,
        delivery[0].claim_token,
        delivery[0].claim_generation,
        known_protection_seconds=90,
        unknown_protection_seconds=30,
    )
    assert database.consume_authoritative_sweep_event(
        event_id, delivery[0].claim_token, delivery[0].claim_generation
    )
    audit = (
        database.get_connection()
        .execute(
            "SELECT reason_code FROM offer_fill_sweep_migration_audit WHERE event_id=?",
            (event_id,),
        )
        .fetchone()
    )
    assert tuple(audit) == ("LEGACY_RECEIPT_MISSING_DOWNSTREAM_ACK",)


def test_recreated_production_sweep_coordinator_requires_explicit_durable_ack(
    isolated_database,
    monkeypatch,
):
    import sweep_coordinator
    from config import cfg

    first_fill = _commit_fill_without_draining_hooks(monkeypatch)
    second_fill = _insert_authoritative_test_fill(OTHER_TRADE)
    monkeypatch.setattr(cfg, "SWEEP_MIN_FILLS", 2)
    for fill in (first_fill, second_fill):
        claim = database.claim_offer_fill_hook(fill["fill_id"], "sweep_registration")
        database.register_authoritative_sweep_fill(
            fill["fill_id"],
            {
                "trade_id": fill["trade_id"],
                "classification": "unknown",
                "spent_block_index": 42,
                "taker_puzzle_hash": None,
                "sweep_group_id": None,
                "side": "buy",
            },
            claim_token=claim["claim_token"],
            claim_generation=claim["claim_generation"],
        )

    before_crash = sweep_coordinator.SweepCoordinator(window_secs=0)
    assert before_crash.get_pending_summary()["pending_fill_count"] == 2
    before_crash.tick()

    recreated = sweep_coordinator.SweepCoordinator(window_secs=0)
    recreated.tick()
    recovered_events = recreated.drain_sweep_events()
    assert len(recovered_events) == 1
    assert recovered_events[0].spent_block_index == 42
    assert set(recovered_events[0].trade_ids) == {TRADE, OTHER_TRADE}
    database.materialize_authoritative_sweep_downstream_effect(
        recovered_events[0].event_id,
        recovered_events[0].claim_token,
        recovered_events[0].claim_generation,
        known_protection_seconds=90,
        unknown_protection_seconds=30,
    )
    assert database.consume_authoritative_sweep_event(
        recovered_events[0].event_id,
        recovered_events[0].claim_token,
        recovered_events[0].claim_generation,
    )

    recreated_again = sweep_coordinator.SweepCoordinator(window_secs=0)
    recreated_again.tick()
    assert recreated_again.get_pending_summary()["pending_fill_count"] == 0
    assert recreated_again.drain_sweep_events() == []


def test_migration_reopens_unproven_legacy_boost_and_sweep_receipts(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    conn = database.get_connection()
    for hook_name in ("boost_notification", "sweep_registration"):
        acknowledgement = {
            "schema_version": 1,
            "fill_id": fill["fill_id"],
            "hook_name": hook_name,
            "durable": True,
            "detail": {"legacy_pre_effect": True},
        }
        conn.execute(
            "INSERT INTO offer_fill_hook_sink_acks "
            "(fill_id, hook_name, acknowledgement_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                fill["fill_id"],
                hook_name,
                json.dumps(acknowledgement, sort_keys=True, separators=(",", ":")),
                AFTER,
            ),
        )
        conn.execute(
            "INSERT INTO offer_fill_hook_receipts (fill_id, hook_name, completed_at) "
            "VALUES (?, ?, ?)",
            (fill["fill_id"], hook_name, AFTER),
        )
        conn.execute(
            "UPDATE offer_fill_hook_outbox SET state='completed', completed_at=? "
            "WHERE fill_id=? AND hook_name=?",
            (AFTER, fill["fill_id"], hook_name),
        )
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    reopened = (
        database.get_connection()
        .execute(
            "SELECT hook_name, state, last_error_code FROM offer_fill_hook_outbox "
            "WHERE fill_id=? AND hook_name IN ('boost_notification', 'sweep_registration') "
            "ORDER BY hook_name",
            (fill["fill_id"],),
        )
        .fetchall()
    )
    assert [
        (row["hook_name"], row["state"], row["last_error_code"]) for row in reopened
    ] == [
        ("boost_notification", "pending", "LEGACY_RECEIPT_REQUIRES_REPLAY"),
        ("sweep_registration", "pending", "LEGACY_RECEIPT_REQUIRES_REPLAY"),
    ]


def test_migration_reopens_event_and_classification_receipts_without_sink_effect(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    hooks = ("offer_filled_event", "fill_classification")
    conn = database.get_connection()
    for hook_name in hooks:
        conn.execute(
            "INSERT INTO offer_fill_hook_receipts (fill_id, hook_name, completed_at) "
            "VALUES (?, ?, ?)",
            (fill["fill_id"], hook_name, AFTER),
        )
        conn.execute(
            "UPDATE offer_fill_hook_outbox SET state='completed', completed_at=? "
            "WHERE fill_id=? AND hook_name=?",
            (AFTER, fill["fill_id"], hook_name),
        )
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    conn = database.get_connection()
    reopened = conn.execute(
        "SELECT hook_name, state, last_error_code FROM offer_fill_hook_outbox "
        "WHERE fill_id=? AND hook_name IN ('offer_filled_event', 'fill_classification') "
        "ORDER BY hook_name",
        (fill["fill_id"],),
    ).fetchall()
    audits = conn.execute(
        "SELECT hook_name, reason_code, prior_state "
        "FROM offer_fill_hook_migration_audit WHERE fill_id=? "
        "AND hook_name IN ('offer_filled_event', 'fill_classification') "
        "ORDER BY hook_name",
        (fill["fill_id"],),
    ).fetchall()
    assert [tuple(row) for row in reopened] == [
        ("fill_classification", "pending", "LEGACY_RECEIPT_REQUIRES_REPLAY"),
        ("offer_filled_event", "pending", "LEGACY_RECEIPT_REQUIRES_REPLAY"),
    ]
    assert [tuple(row) for row in audits] == [
        (
            "fill_classification",
            "LEGACY_RECEIPT_REQUIRES_REPLAY",
            "completed",
        ),
        (
            "offer_filled_event",
            "LEGACY_RECEIPT_REQUIRES_REPLAY",
            "completed",
        ),
    ]


def test_migration_preserves_classification_receipt_after_durable_sweep_enrichment(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    callbacks = reconciliation._post_fill_hook_callbacks(fill)
    claim = database.claim_offer_fill_hook(fill["fill_id"], "fill_classification")
    acknowledgement = _invoke_claimed_hook(
        callbacks["fill_classification"], fill, claim
    )
    assert database.validate_offer_fill_hook_sink_ack(
        fill["fill_id"],
        "fill_classification",
        acknowledgement,
        claim_token=claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    assert database.complete_offer_fill_hook(
        fill["fill_id"],
        "fill_classification",
        claim["claim_token"],
        claim_generation=claim["claim_generation"],
    )
    conn = database.get_connection()
    conn.execute(
        "UPDATE fills SET fill_classification='dexie_combined', "
        "sweep_group_id='sweep_42' WHERE fill_id=?",
        (fill["fill_id"],),
    )
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    conn = database.get_connection()
    outbox = conn.execute(
        "SELECT state, last_error_code FROM offer_fill_hook_outbox "
        "WHERE fill_id=? AND hook_name='fill_classification'",
        (fill["fill_id"],),
    ).fetchone()
    audit = conn.execute(
        "SELECT 1 FROM offer_fill_hook_migration_audit "
        "WHERE fill_id=? AND hook_name='fill_classification'",
        (fill["fill_id"],),
    ).fetchone()
    assert tuple(outbox) == ("completed", None)
    assert audit is None


def test_migration_reopens_false_noop_ack_for_actual_boost_fill(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    acknowledgement = {
        "schema_version": 1,
        "fill_id": fill["fill_id"],
        "hook_name": "boost_notification",
        "durable": True,
        "detail": {"trade_id": TRADE, "applicable": False},
    }
    conn = database.get_connection()
    conn.execute("UPDATE fills SET tier='boost' WHERE fill_id=?", (fill["fill_id"],))
    conn.execute(
        "INSERT INTO offer_fill_hook_sink_acks "
        "(fill_id, hook_name, acknowledgement_json, created_at) "
        "VALUES (?, 'boost_notification', ?, ?)",
        (
            fill["fill_id"],
            json.dumps(acknowledgement, sort_keys=True, separators=(",", ":")),
            AFTER,
        ),
    )
    conn.execute(
        "INSERT INTO offer_fill_hook_receipts "
        "(fill_id, hook_name, completed_at) "
        "VALUES (?, 'boost_notification', ?)",
        (fill["fill_id"], AFTER),
    )
    conn.execute(
        "UPDATE offer_fill_hook_outbox SET state='completed', completed_at=? "
        "WHERE fill_id=? AND hook_name='boost_notification'",
        (AFTER, fill["fill_id"]),
    )
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    row = (
        database.get_connection()
        .execute(
            "SELECT state, last_error_code FROM offer_fill_hook_outbox "
            "WHERE fill_id=? AND hook_name='boost_notification'",
            (fill["fill_id"],),
        )
        .fetchone()
    )
    assert tuple(row) == ("pending", "LEGACY_RECEIPT_REQUIRES_REPLAY")


def test_migration_audits_unproven_receipt_when_outbox_was_missing(
    isolated_database,
    monkeypatch,
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    acknowledgement = {
        "schema_version": 1,
        "fill_id": fill["fill_id"],
        "hook_name": "sweep_registration",
        "durable": True,
        "detail": {"legacy_pre_effect": True},
    }
    conn = database.get_connection()
    conn.execute(
        "INSERT INTO offer_fill_hook_sink_acks "
        "(fill_id, hook_name, acknowledgement_json, created_at) "
        "VALUES (?, 'sweep_registration', ?, ?)",
        (
            fill["fill_id"],
            json.dumps(acknowledgement, sort_keys=True, separators=(",", ":")),
            AFTER,
        ),
    )
    conn.execute(
        "INSERT INTO offer_fill_hook_receipts "
        "(fill_id, hook_name, completed_at) "
        "VALUES (?, 'sweep_registration', ?)",
        (fill["fill_id"], AFTER),
    )
    conn.execute(
        "DELETE FROM offer_fill_hook_outbox "
        "WHERE fill_id=? AND hook_name='sweep_registration'",
        (fill["fill_id"],),
    )
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()

    conn = database.get_connection()
    outbox = conn.execute(
        "SELECT state, last_error_code FROM offer_fill_hook_outbox "
        "WHERE fill_id=? AND hook_name='sweep_registration'",
        (fill["fill_id"],),
    ).fetchone()
    audit = conn.execute(
        "SELECT reason_code, prior_state FROM offer_fill_hook_migration_audit "
        "WHERE fill_id=? AND hook_name='sweep_registration'",
        (fill["fill_id"],),
    ).fetchone()
    assert tuple(outbox) == ("pending", "LEGACY_RECEIPT_REQUIRES_REPLAY")
    assert tuple(audit) == ("LEGACY_RECEIPT_REQUIRES_REPLAY", "missing")


def test_hook_without_positive_durable_fill_ack_is_not_completed(
    isolated_database, monkeypatch
):
    _persist_created_offer()
    monkeypatch.setattr(
        reconciliation,
        "_post_fill_hook_callbacks",
        lambda _fill: {
            name: (lambda _row: None) for name in database._AUTHORITATIVE_FILL_HOOKS
        },
    )

    result = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert result["classification"] == FILLED_PROVEN
    assert result["applied"] is True
    assert result["post_fill_hooks"] == {
        name: "failed" for name in database._AUTHORITATIVE_FILL_HOOKS
    }
    assert database.get_offer_fill_hook_receipts(result["fill_id"]) == []


def test_hook_reset_failure_is_contained_and_reported_as_running_uncertainty(
    isolated_database, monkeypatch
):
    _persist_created_offer()
    monkeypatch.setattr(
        reconciliation,
        "_post_fill_hook_callbacks",
        lambda _fill: {
            name: (lambda _row: (_ for _ in ()).throw(RuntimeError("sink failed")))
            for name in database._AUTHORITATIVE_FILL_HOOKS
        },
    )
    monkeypatch.setattr(
        database,
        "fail_offer_fill_hook",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("reset failed")),
    )

    result = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert result["classification"] == FILLED_PROVEN
    assert result["post_fill_hooks"] == {
        name: "in_progress" for name in database._AUTHORITATIVE_FILL_HOOKS
    }
    assert database.get_offer(TRADE)["status"] == "filled"


def test_exact_terminal_replay_restores_missing_fill_outbox_before_return(
    isolated_database, monkeypatch
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    conn = database.get_connection()
    conn.execute(
        "DELETE FROM offer_fill_hook_outbox WHERE fill_id=?", (fill["fill_id"],)
    )
    conn.commit()

    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
    restored = conn.execute(
        "SELECT hook_name, state FROM offer_fill_hook_outbox WHERE fill_id=? "
        "ORDER BY hook_name",
        (fill["fill_id"],),
    ).fetchall()

    assert replay["idempotent"] is True
    assert [(row["hook_name"], row["state"]) for row in restored] == sorted(
        (name, "pending") for name in database._AUTHORITATIVE_FILL_HOOKS
    )


def test_schema_migration_backfills_outbox_for_existing_authoritative_fill(
    isolated_database, monkeypatch
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    conn = database.get_connection()
    conn.execute(
        "DELETE FROM offer_fill_hook_outbox WHERE fill_id=?", (fill["fill_id"],)
    )
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()
    restored = (
        database.get_connection()
        .execute(
            "SELECT hook_name, state FROM offer_fill_hook_outbox WHERE fill_id=? "
            "ORDER BY hook_name",
            (fill["fill_id"],),
        )
        .fetchall()
    )

    assert [(row["hook_name"], row["state"]) for row in restored] == sorted(
        (name, "pending") for name in database._AUTHORITATIVE_FILL_HOOKS
    )


def test_schema_migration_marks_backfilled_preexisting_receipts_completed(
    isolated_database, monkeypatch
):
    _persist_created_offer()
    committed = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
    conn = database.get_connection()
    conn.execute(
        "DELETE FROM offer_fill_hook_outbox WHERE fill_id=?", (committed["fill_id"],)
    )
    conn.commit()
    database.close_connection()

    database._migrate_stability_schema()
    restored = (
        database.get_connection()
        .execute(
            "SELECT hook_name, state FROM offer_fill_hook_outbox WHERE fill_id=?",
            (committed["fill_id"],),
        )
        .fetchall()
    )

    assert {(row["hook_name"], row["state"]) for row in restored} == {
        (name, "completed") for name in database._AUTHORITATIVE_FILL_HOOKS
    }


def test_durable_pending_outbox_has_explicit_wallet_free_drain_contract(
    isolated_database, monkeypatch
):
    original_runner = reconciliation._run_post_fill_hooks
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    monkeypatch.setattr(reconciliation, "_run_post_fill_hooks", original_runner)

    drained = reconciliation.drain_offer_fill_hook_outbox()

    assert drained[fill["fill_id"]] == {
        name: "completed" for name in database._AUTHORITATIVE_FILL_HOOKS
    }
    assert database.get_offer_fill_hook_receipts(fill["fill_id"]) == list(
        database._AUTHORITATIVE_FILL_HOOKS
    )


def test_production_fill_sinks_return_exact_durable_fill_acknowledgements(
    isolated_database, monkeypatch
):
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    manager = SimpleNamespace(notify_boost_fill=lambda _trade_id: True)
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=manager)),
    )
    coordinator = SimpleNamespace(process_fill=lambda _fill_id, _result: None)
    monkeypatch.setitem(
        sys.modules,
        "sweep_coordinator",
        SimpleNamespace(get_coordinator=lambda: coordinator),
    )
    callbacks = reconciliation._post_fill_hook_callbacks(fill)

    claims = {
        name: database.claim_offer_fill_hook(fill["fill_id"], name)
        for name in callbacks
    }
    acknowledgements = {
        name: _invoke_claimed_hook(callback, fill, claims[name])
        for name, callback in callbacks.items()
    }

    assert set(acknowledgements) == set(database._AUTHORITATIVE_FILL_HOOKS)
    for name, acknowledgement in acknowledgements.items():
        assert acknowledgement["fill_id"] == fill["fill_id"]
        assert acknowledgement["hook_name"] == name
        assert acknowledgement["durable"] is True
        assert database.validate_offer_fill_hook_sink_ack(
            fill["fill_id"],
            name,
            acknowledgement,
            claim_token=claims[name]["claim_token"],
            claim_generation=claims[name]["claim_generation"],
        )


def test_production_boost_sink_waits_for_exact_manager_state_before_registration(
    isolated_database, monkeypatch
):
    from boost_manager import BoostManager

    _persist_created_offer()
    conn = database.get_connection()
    conn.execute("UPDATE offers SET tier='boost' WHERE trade_id=?", (TRADE,))
    conn.commit()
    monkeypatch.setitem(
        sys.modules, "api_server", SimpleNamespace(bot=SimpleNamespace())
    )

    first = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
    boost_ack = conn.execute(
        "SELECT acknowledgement_json FROM offer_fill_hook_sink_acks "
        "WHERE fill_id=? AND hook_name='boost_notification'",
        (first["fill_id"],),
    ).fetchone()

    assert first["post_fill_hooks"]["boost_notification"] == "failed"
    assert boost_ack is None
    command = conn.execute(
        "SELECT trade_id, state FROM offer_fill_boost_commands WHERE fill_id=?",
        (first["fill_id"],),
    ).fetchone()
    assert command is None
    assert "boost_notification" not in database.get_offer_fill_hook_receipts(
        first["fill_id"]
    )

    manager = BoostManager()
    manager._buy_offset_bps = 137
    manager._buy_last_safe_offset_bps = 121
    manager._buy_probe_tid = TRADE
    manager._buy_probe_tid_history.add(TRADE)
    monkeypatch.setitem(
        sys.modules,
        "api_server",
        SimpleNamespace(bot=SimpleNamespace(boost_manager=manager)),
    )
    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert replay["post_fill_hooks"]["boost_notification"] == "completed"
    assert manager._buy_floor_bps == 137
    command = conn.execute(
        "SELECT trade_id, state FROM offer_fill_boost_commands WHERE fill_id=?",
        (first["fill_id"],),
    ).fetchone()
    assert tuple(command) == (TRADE, "applied")
    assert "boost_notification" in database.get_offer_fill_hook_receipts(
        first["fill_id"]
    )


def test_post_fill_hooks_run_once_by_durable_fill_id_on_exact_replay(
    isolated_database, monkeypatch
):
    _persist_created_offer()
    calls = []
    hook_names = (
        "offer_filled_event",
        "boost_notification",
        "fill_classification",
        "sweep_registration",
    )

    def callbacks(_fill):
        def callback(name):
            def run(row, **claim):
                calls.append((name, row["fill_id"]))
                return _record_claimed_test_sink_ack(
                    row["fill_id"], name, {"test_sink": name}, claim
                )

            return run

        return {name: callback(name) for name in hook_names}

    monkeypatch.setattr(
        reconciliation, "_post_fill_hook_callbacks", callbacks, raising=False
    )

    first = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    fill_id = first["fill_id"]
    assert replay["fill_id"] == fill_id
    assert calls == [(name, fill_id) for name in hook_names]
    assert first["post_fill_hooks"] == {name: "completed" for name in hook_names}
    assert replay["post_fill_hooks"] == {
        name: "already_completed" for name in hook_names
    }
    assert database.get_offer_fill_hook_receipts(fill_id) == list(hook_names)


def test_post_fill_hook_failure_never_undoes_proof_and_retries_only_failure(
    isolated_database, monkeypatch
):
    _persist_created_offer()
    calls = {
        "offer_filled_event": 0,
        "boost_notification": 0,
        "fill_classification": 0,
        "sweep_registration": 0,
    }

    def callbacks(_fill):
        def callback(name):
            def run(_row, **claim):
                calls[name] += 1
                if name == "fill_classification" and calls[name] == 1:
                    raise RuntimeError("classification hook failed")
                return _record_claimed_test_sink_ack(
                    _row["fill_id"], name, {"test_sink": name}, claim
                )

            return run

        return {name: callback(name) for name in calls}

    monkeypatch.setattr(
        reconciliation, "_post_fill_hook_callbacks", callbacks, raising=False
    )

    first = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert first["classification"] == FILLED_PROVEN
    assert first["applied"] is True
    assert first["post_fill_hooks"]["fill_classification"] == "failed"
    assert database.get_offer(TRADE)["status"] == "filled"
    assert database.get_coin_state(COIN)["status"] == "spent"

    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert replay["post_fill_hooks"]["fill_classification"] == "completed"
    assert calls == {
        "offer_filled_event": 1,
        "boost_notification": 1,
        "fill_classification": 2,
        "sweep_registration": 1,
    }


def test_post_fill_hook_claim_allows_one_effect_under_concurrent_replay(
    isolated_database,
    monkeypatch,
):
    _persist_created_offer()
    effect_entered = threading.Event()
    release_effect = threading.Event()
    second_done = threading.Event()
    calls = {name: 0 for name in database._AUTHORITATIVE_FILL_HOOKS}
    errors = []

    def callbacks(_fill):
        def callback(name):
            def run(_row, **claim):
                if name == "offer_filled_event":
                    effect_entered.set()
                    assert release_effect.wait(timeout=5)
                calls[name] += 1
                return _record_claimed_test_sink_ack(
                    _row["fill_id"], name, {"test_sink": name}, claim
                )

            return run

        return {name: callback(name) for name in calls}

    monkeypatch.setattr(reconciliation, "_post_fill_hook_callbacks", callbacks)

    def run_reconcile(*, done=None):
        try:
            reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            if done is not None:
                done.set()

    threads = [threading.Thread(target=run_reconcile)]
    threads[0].start()
    assert effect_entered.wait(timeout=5)
    threads.append(threading.Thread(target=run_reconcile, kwargs={"done": second_done}))
    threads[1].start()
    second_finished_before_release = second_done.wait(timeout=1)
    release_effect.set()
    for thread in threads:
        thread.join(timeout=10)

    assert second_finished_before_release is True
    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert calls == {name: 1 for name in calls}
    fill = database.get_fill_by_trade_id(TRADE)
    assert database.get_offer_fill_hook_receipts(fill["fill_id"]) == list(calls)


def test_post_fill_runner_heartbeats_long_sink_and_prevents_live_claim_steal(
    isolated_database,
    monkeypatch,
):
    original_runner = reconciliation._run_post_fill_hooks
    fill = _commit_fill_without_draining_hooks(monkeypatch)
    monkeypatch.setattr(reconciliation, "_run_post_fill_hooks", original_runner)
    monkeypatch.setattr(database, "_AUTHORITATIVE_FILL_HOOK_LEASE_SECONDS", 0.09)
    callback_started = threading.Event()
    heartbeat_seen = threading.Event()
    release_callback = threading.Event()
    results = {}
    errors = []
    original_heartbeat = database.heartbeat_offer_fill_hook

    def heartbeat(*args, **kwargs):
        held = original_heartbeat(*args, **kwargs)
        if held:
            heartbeat_seen.set()
        return held

    def callback(row, **claim):
        callback_started.set()
        assert heartbeat_seen.wait(timeout=0.5)
        assert release_callback.wait(timeout=2)
        return _record_claimed_test_sink_ack(
            row["fill_id"],
            "offer_filled_event",
            {"test_sink": "long_running"},
            claim,
        )

    monkeypatch.setattr(database, "heartbeat_offer_fill_hook", heartbeat)
    monkeypatch.setattr(
        reconciliation,
        "_post_fill_hook_callbacks",
        lambda _fill: {"offer_filled_event": callback},
    )

    def run():
        try:
            results.update(
                reconciliation._run_post_fill_hooks(fill, completed_at=AFTER)
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert callback_started.wait(timeout=2)
    assert heartbeat_seen.wait(timeout=0.5)
    live_claim = database.claim_offer_fill_hook(fill["fill_id"], "offer_filled_event")
    release_callback.set()
    worker.join(timeout=5)

    assert live_claim["status"] == "in_progress"
    assert not errors
    assert not worker.is_alive()
    assert results == {"offer_filled_event": "completed"}


def test_post_fill_hook_crash_after_effect_before_receipt_never_duplicates(
    isolated_database,
    monkeypatch,
):
    _persist_created_offer()
    attempts = {name: 0 for name in database._AUTHORITATIVE_FILL_HOOKS}
    effects = {name: 0 for name in database._AUTHORITATIVE_FILL_HOOKS}
    applied = set()
    hook_clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: hook_clock["now"])

    def callbacks(_fill):
        def callback(name):
            def run(row, **claim):
                attempts[name] += 1
                effect_key = (name, row["fill_id"])
                if effect_key not in applied:
                    applied.add(effect_key)
                    effects[name] += 1
                return _record_claimed_test_sink_ack(
                    row["fill_id"], name, {"test_sink": name}, claim
                )

            return run

        return {name: callback(name) for name in attempts}

    monkeypatch.setattr(reconciliation, "_post_fill_hook_callbacks", callbacks)
    original_complete = database.complete_offer_fill_hook
    crashed = False

    def crash_before_receipt(*args, **kwargs):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise KeyboardInterrupt("simulated process crash after effect")
        return original_complete(*args, **kwargs)

    monkeypatch.setattr(database, "complete_offer_fill_hook", crash_before_receipt)

    with pytest.raises(KeyboardInterrupt, match="simulated process crash"):
        reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert database.get_offer(TRADE)["status"] == "filled"
    assert effects["offer_filled_event"] == 1
    monkeypatch.setattr(database, "complete_offer_fill_hook", original_complete)
    hook_clock["now"] = "2026-08-20T12:10:31.000000Z"

    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert replay["post_fill_hooks"]["offer_filled_event"] == "completed"
    assert attempts["offer_filled_event"] == 2
    assert effects == {name: 1 for name in effects}


def test_post_fill_receipt_exception_after_effect_stays_uncertain_without_duplicate(
    isolated_database,
    monkeypatch,
):
    _persist_created_offer()
    attempts = {name: 0 for name in database._AUTHORITATIVE_FILL_HOOKS}
    effects = {name: 0 for name in database._AUTHORITATIVE_FILL_HOOKS}
    applied = set()
    hook_clock = {"now": "2026-08-20T12:10:00.000000Z"}
    monkeypatch.setattr(database, "_stability_wall_clock", lambda: hook_clock["now"])

    def callbacks(_fill):
        def callback(name):
            def run(row, **claim):
                attempts[name] += 1
                effect_key = (name, row["fill_id"])
                if effect_key not in applied:
                    applied.add(effect_key)
                    effects[name] += 1
                return _record_claimed_test_sink_ack(
                    row["fill_id"], name, {"test_sink": name}, claim
                )

            return run

        return {name: callback(name) for name in attempts}

    monkeypatch.setattr(reconciliation, "_post_fill_hook_callbacks", callbacks)
    original_complete = database.complete_offer_fill_hook
    completion_failed = False

    def fail_receipt_once(*args, **kwargs):
        nonlocal completion_failed
        if not completion_failed:
            completion_failed = True
            raise RuntimeError("receipt store unavailable after effect")
        return original_complete(*args, **kwargs)

    monkeypatch.setattr(database, "complete_offer_fill_hook", fail_receipt_once)

    first = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert first["classification"] == FILLED_PROVEN
    assert first["post_fill_hooks"]["offer_filled_event"] == "in_progress"
    assert effects["offer_filled_event"] == 1
    monkeypatch.setattr(database, "complete_offer_fill_hook", original_complete)
    hook_clock["now"] = "2026-08-20T12:10:31.000000Z"

    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert replay["post_fill_hooks"]["offer_filled_event"] == "completed"
    assert attempts["offer_filled_event"] == 2
    assert effects == {name: 1 for name in effects}


def test_default_offer_filled_event_sink_is_idempotent_by_durable_fill_id(
    isolated_database,
    monkeypatch,
):
    _persist_created_offer()
    original_callbacks = reconciliation._post_fill_hook_callbacks
    monkeypatch.setattr(
        reconciliation,
        "_post_fill_hook_callbacks",
        lambda _fill: {
            name: (lambda _row: None) for name in database._AUTHORITATIVE_FILL_HOOKS
        },
    )
    committed = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)
    fill = database.get_fill_by_trade_id(TRADE)
    assert fill["fill_id"] == committed["fill_id"]

    callback = original_callbacks(fill)["offer_filled_event"]
    claim = database.claim_offer_fill_hook(fill["fill_id"], "offer_filled_event")
    _invoke_claimed_hook(callback, fill, claim)
    _invoke_claimed_hook(callback, fill, claim)

    persisted = database.get_recent_events(limit=20, event_type="offer_filled")
    matching = [
        event
        for event in persisted
        if json.loads(event["data"])["fill_id"] == fill["fill_id"]
    ]
    assert len(matching) == 1


def test_post_fill_claim_failure_does_not_escape_or_undo_proof_and_retries(
    isolated_database,
    monkeypatch,
):
    _persist_created_offer()
    original_claim = database.claim_offer_fill_hook
    claim_failed = False

    def fail_first_claim(*args, **kwargs):
        nonlocal claim_failed
        if not claim_failed:
            claim_failed = True
            raise RuntimeError("outbox claim temporarily unavailable")
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(database, "claim_offer_fill_hook", fail_first_claim)

    first = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert first["classification"] == FILLED_PROVEN
    assert first["applied"] is True
    assert first["post_fill_hooks"]["offer_filled_event"] == "failed"
    assert database.get_offer(TRADE)["status"] == "filled"
    monkeypatch.setattr(database, "claim_offer_fill_hook", original_claim)

    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=AFTER)

    assert replay["post_fill_hooks"]["offer_filled_event"] == "completed"
    events = database.get_recent_events(limit=20, event_type="offer_filled")
    assert (
        len(
            [
                event
                for event in events
                if json.loads(event["data"])["fill_id"] == first["fill_id"]
            ]
        )
        == 1
    )


def test_default_post_fill_hooks_retry_unpersisted_event_and_unavailable_boost(
    monkeypatch,
):
    fill = {
        "fill_id": 17,
        "trade_id": TRADE,
        "side": "buy",
        "price_xch": "0.5",
        "size_xch": "1",
        "size_cat": "2",
        "tier": "boost",
        "filled_at": AFTER,
        "spent_block_index": 42,
    }
    monkeypatch.setattr(database, "get_offer", lambda _trade_id: {"coin_id": COIN})
    monkeypatch.setattr(
        database,
        "log_authoritative_offer_filled_once",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("offer_filled event was not persisted")
        ),
    )
    monkeypatch.setattr(
        database,
        "record_offer_fill_hook_sink_ack",
        lambda fill_id, hook_name, _detail, **_claim: {
            "schema_version": 1,
            "fill_id": fill_id,
            "hook_name": hook_name,
            "durable": True,
            "detail": _detail,
        },
    )
    monkeypatch.setattr(
        database,
        "register_authoritative_boost_fill_command",
        lambda *_args, **_kwargs: {"state": "registered"},
    )
    monkeypatch.setitem(
        sys.modules, "api_server", SimpleNamespace(bot=SimpleNamespace())
    )

    callbacks = reconciliation._post_fill_hook_callbacks(fill)
    claim = {"claim_token": "test-token", "claim_generation": 1}

    with pytest.raises(RuntimeError, match="offer_filled"):
        _invoke_claimed_hook(callbacks["offer_filled_event"], fill, claim)
    with pytest.raises(RuntimeError, match="BoostManager"):
        _invoke_claimed_hook(callbacks["boost_notification"], fill, claim)


def test_sweep_registration_is_idempotent_by_durable_fill_id():
    from sweep_coordinator import SweepCoordinator

    coordinator = SweepCoordinator(window_secs=60)
    classification = SimpleNamespace(
        trade_id=TRADE,
        classification="unknown",
        spent_block_index=42,
        taker_puzzle_hash=None,
        side="buy",
    )

    coordinator.process_fill(17, classification)
    coordinator.process_fill(17, classification)

    assert coordinator.get_pending_summary()["pending_fill_count"] == 1


def test_cancel_commit_spends_old_coin_and_inserts_exact_owned_return(
    isolated_database,
):
    _persist_created_offer()
    _persist_cancel_prepared()
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


def test_cancel_commit_binds_validated_task8_context_and_rejects_tampered_replay(
    isolated_database,
):
    _persist_created_offer()
    _persist_cancel_prepared()
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
    context = _cancel_context()

    first = reconcile_offer(
        "intent-task9", evidence=evidence, cancel_context=context, now=AFTER
    )
    durable = json.loads(first["event"]["evidence_json"])
    exact = durable.get("exact_subset", durable)

    assert exact["cancel_context"]["manifest_sha256"] == MANIFEST_SHA256
    assert exact["cancel_context"]["members"][0]["member_id"].startswith(
        "cancel-member:"
    )
    assert exact["cancel_context"]["members"][0]["prepared_event_id"] == (
        PREPARED_EVENT_ID
    )

    tampered = json.loads(json.dumps(context))
    tampered["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Task 8"):
        reconcile_offer(
            "intent-task9",
            evidence=evidence,
            cancel_context=tampered,
            now=AFTER,
        )


def test_cancel_commit_rejects_unbound_task8_prepared_event_and_preserves_blocker(
    isolated_database,
):
    _persist_created_offer()
    prepared = _persist_cancel_prepared()
    context = _cancel_context()
    context["members"][0]["prepared_event_id"] = f"cancel:{TRADE}:attempt:2:prepared"

    with pytest.raises(ValueError, match="Task 8"):
        reconcile_offer(
            "intent-task9",
            evidence=_simple_cancel_flow_evidence(status=3),
            cancel_context=context,
            now=AFTER,
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    latest = database.get_offer_operation_events(f"cancel:{TRADE}")[-1]
    assert latest["event_id"] == prepared["event_id"]
    assert latest["outcome"] == "PREPARED"
    assert latest["blocks_mutation"] == 1


@pytest.mark.parametrize("claim_case", ["missing", "tampered", "after_transaction"])
def test_cancel_commit_requires_exact_timely_task8_effect_claim_and_latches(
    isolated_database,
    claim_case,
):
    _persist_created_offer()
    _persist_cancel_prepared(
        claim_effect=claim_case != "missing",
        claimed_at=RECONCILED if claim_case == "after_transaction" else AT,
    )
    if claim_case == "tampered":
        conn = database.get_connection()
        conn.execute("DROP TRIGGER offer_cancel_effect_claims_no_update")
        conn.execute(
            "UPDATE offer_cancel_effect_claims SET prepared_event_id=? "
            "WHERE operation_id=? AND attempt=1",
            (f"cancel:{TRADE}:attempt:2:prepared", f"cancel:{TRADE}"),
        )
        conn.commit()

    with pytest.raises(ValueError, match="Task 8.*effect claim"):
        reconcile_offer(
            "intent-task9",
            evidence=_simple_cancel_flow_evidence(status=3),
            cancel_context=_cancel_context(),
            now=RECONCILED,
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert _journal_for("intent-task9") == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_cancel_commit_rejects_tampered_single_attempt_claim_binding(
    isolated_database,
):
    _persist_created_offer()
    _persist_cancel_prepared()
    context = _cancel_context()
    context["manifest_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="Task 8"):
        reconcile_offer(
            "intent-task9",
            evidence=_simple_cancel_flow_evidence(status=3),
            cancel_context=context,
            now=AFTER,
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    latest = database.get_offer_operation_events(f"cancel:{TRADE}")[-1]
    assert latest["outcome"] == "PREPARED"
    assert latest["blocks_mutation"] == 1


def test_cancel_commit_rejects_failed_no_effect_result_and_trips_named_latch(
    isolated_database,
):
    _persist_created_offer()
    _persist_cancel_prepared()
    _persist_cancel_result(CANCEL_FAILED)

    with pytest.raises(ValueError, match="Task 8"):
        reconcile_offer(
            "intent-task9",
            evidence=_simple_cancel_flow_evidence(status=3),
            cancel_context=_cancel_context(),
            now=AFTER,
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert _journal_for("intent-task9") == []
    assert [
        event["outcome"]
        for event in database.get_offer_operation_events(f"cancel:{TRADE}")
    ] == ["PREPARED", CANCEL_FAILED]
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert json.loads(latch["blocking_operation_ids_json"]) == [
        "reconcile:intent-task9"
    ]


def test_cancel_commit_rejects_context_identity_different_from_task8_result(
    isolated_database,
):
    _persist_created_offer()
    _persist_cancel_prepared()
    _persist_cancel_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        transaction_id=TX,
        spend_identity=SPEND,
    )
    other_transaction = OTHER_COIN
    other_spend = "sha256:" + "a" * 64

    with pytest.raises(ValueError, match="Task 8"):
        reconcile_offer(
            "intent-task9",
            evidence=_cancel_evidence_with_identity(
                transaction_id=other_transaction,
                spend_identity=other_spend,
            ),
            cancel_context=_cancel_context(
                transaction_id=other_transaction,
                spend_identity=other_spend,
            ),
            now=AFTER,
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert _journal_for("intent-task9") == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_cancel_commit_rejects_newer_attempt_than_bound_context_and_trips_latch(
    isolated_database,
):
    _persist_created_offer()
    _persist_cancel_prepared()
    _persist_cancel_result(CANCEL_FAILED)
    database.prepare_offer_cancel(
        operation_id=f"cancel:{TRADE}",
        event_id=f"cancel:{TRADE}:attempt:2:prepared",
        trade_id=TRADE,
        intent_id="intent-task9",
        attempt=2,
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET,
            "network": NETWORK,
        },
        evidence_json={"trade_id": TRADE},
        prepared_at=RECONCILED,
    )

    with pytest.raises(ValueError, match="Task 8"):
        reconcile_offer(
            "intent-task9",
            evidence=_simple_cancel_flow_evidence(status=3),
            cancel_context=_cancel_context(),
            now=RECONCILED,
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert _journal_for("intent-task9") == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def _persist_grouped_cancel_case(
    *, durable_auxiliary: list[str] | None = None
) -> tuple[dict, dict]:
    _persist_created_offer()
    assert database.upsert_coin(
        OTHER_COIN,
        "cat",
        2000,
        tier="inner",
        designation="tier_active",
        assigned_tier="inner",
    )
    database.prepare_offer_intent(
        intent_id="intent-task9-other",
        operation_id="create:intent-task9-other",
        event_id="create:intent-task9-other:prepared",
        run_id="run-task9",
        wallet_fingerprint_hash=WALLET,
        network=NETWORK,
        asset_id=ASSET,
        side="sell",
        tier="inner",
        purpose="normal_lifecycle",
        slot_key="slot:intent-task9-other",
        generation=0,
        offered_amount_atomic="2000",
        requested_amount_atomic="1000",
        selected_coin_ids_json=[OTHER_COIN],
        wallet_identity_json={"wallet_fingerprint_hash": WALLET, "network": NETWORK},
        evidence_json={"intent": "exact"},
        prepared_at=AT,
        reserve_selected_coins=True,
    )
    database.finalize_offer_intent(
        intent_id="intent-task9-other",
        operation_id="create:intent-task9-other",
        event_id="create:intent-task9-other:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=OTHER_TRADE,
        offer_text_sha256="0" * 64,
        wallet_identity_json={"wallet_fingerprint_hash": WALLET, "network": NETWORK},
        evidence_json={"offer": "confirmed"},
        finalized_at=AT,
        finalize_selected_coin_reservations=True,
    )
    assert database.add_offer(
        OTHER_TRADE,
        "sell",
        price_xch=database.Decimal("0.0000005"),
        size_xch=database.Decimal("0.000000001"),
        size_cat=database.Decimal("2"),
        cat_asset_id=ASSET,
        tier="inner",
        coin_id=database.norm_coin_id(OTHER_COIN),
    )
    core_members = [
        {
            "trade_id": TRADE,
            "operation_id": f"cancel:{TRADE}",
            "intent_id": f"cancel-target:{TRADE}",
            "attempt": 1,
            "prepared_event_id": PREPARED_EVENT_ID,
        },
        {
            "trade_id": OTHER_TRADE,
            "operation_id": f"cancel:{OTHER_TRADE}",
            "intent_id": f"cancel-target:{OTHER_TRADE}",
            "attempt": 1,
            "prepared_event_id": f"cancel:{OTHER_TRADE}:attempt:1:prepared",
        },
    ]
    manifest = database.canonical_offer_cancel_cohort_manifest(core_members)
    requests = [
        {
            "operation_id": member["operation_id"],
            "event_id": member["prepared_event_id"],
            "trade_id": member["trade_id"],
            "intent_id": member["intent_id"],
            "attempt": member["attempt"],
            "wallet_identity_json": {
                "wallet_fingerprint_hash": WALLET,
                "network": NETWORK,
            },
            "evidence_json": {
                "trade_id": member["trade_id"],
                "intent_id": member["intent_id"],
                "operation_id": member["operation_id"],
                "attempt": member["attempt"],
                "cohort_id": manifest["cohort_id"],
                "cohort_size": manifest["member_count"],
                "member_id": member["member_id"],
                "reason": "task9 authoritative reconciliation test",
                "continuation_journal_sha256": "1" * 64,
                "wallet_effect": {
                    "secure": True,
                    "auxiliary_coin_ids": list(durable_auxiliary or []),
                },
                "effect_claim_protocol": "durable_cohort_claim_v1",
            },
        }
        for member in manifest["members"]
    ]
    database.prepare_offer_cancel_cohort(
        manifest_json=manifest,
        member_requests_json=requests,
        prepared_at=AT,
    )
    for member in manifest["members"]:
        assert database.claim_offer_cancel_effect(
            operation_id=member["operation_id"],
            trade_id=member["trade_id"],
            attempt=member["attempt"],
            claimed_at=AT,
        )
    selected_by_trade = {TRADE: [COIN], OTHER_TRADE: [OTHER_COIN]}
    context = {
        "cohort_id": manifest["cohort_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "members": [
            {
                "intent_id": member["intent_id"],
                "trade_id": member["trade_id"],
                "member_id": member["member_id"],
                "prepared_event_id": member["prepared_event_id"],
                "selected_coin_ids": selected_by_trade[member["trade_id"]],
                "request_timestamp": AT,
                "transaction_timestamp": AFTER,
                "transaction_id": TX,
                "spend_identity": SPEND,
                "asset_id": ASSET,
                "side": "buy" if member["trade_id"] == TRADE else "sell",
                "offered_amount_atomic": (
                    "1000" if member["trade_id"] == TRADE else "2000"
                ),
                "requested_amount_atomic": (
                    "2000" if member["trade_id"] == TRADE else "1000"
                ),
                "offer_text_sha256": (
                    OFFER_HASH if member["trade_id"] == TRADE else "0" * 64
                ),
            }
            for member in manifest["members"]
        ],
        "auxiliary_coin_ids": list(durable_auxiliary or []),
    }
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
                        "address_kind": "offer",
                    },
                ],
                created=[
                    {
                        "coin_id": RETURN,
                        "asset_id": "xch",
                        "amount": 1000,
                        "address_kind": "own",
                    },
                    {
                        "coin_id": OTHER_RETURN,
                        "asset_id": ASSET,
                        "amount": 2000,
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
                offer_id=OTHER_TRADE,
            ),
            RETURN: _coin(
                RETURN,
                asset_id="xch",
                amount=1000,
                created_height=42,
                transaction_id=TX,
            ),
            OTHER_RETURN: _coin(
                OTHER_RETURN,
                asset_id=ASSET,
                amount=2000,
                created_height=42,
                transaction_id=TX,
            ),
        },
    )

    if durable_auxiliary:
        evidence["transaction_history"]["records"][0]["spent"].append(
            {
                "coin_id": FEE_COIN,
                "asset_id": "xch",
                "amount": 100,
                "address_kind": "own",
            }
        )
        evidence["transaction_history"]["records"][0]["created"].append(
            {
                "coin_id": FEE_RETURN,
                "asset_id": "xch",
                "amount": 90,
                "address_kind": "own",
            }
        )
        evidence["coin_records"]["records"].update(
            {
                FEE_COIN: _coin(
                    FEE_COIN,
                    asset_id="xch",
                    amount=100,
                    spent_height=42,
                    transaction_id=TX,
                ),
                FEE_RETURN: _coin(
                    FEE_RETURN,
                    asset_id="xch",
                    amount=90,
                    created_height=42,
                    transaction_id=TX,
                ),
            }
        )

    return context, evidence


def test_cancel_commit_validates_cohort_manifest_and_resolves_only_target_blocker(
    isolated_database,
):
    context, evidence = _persist_grouped_cancel_case()

    result = reconcile_offer(
        "intent-task9", evidence=evidence, cancel_context=context, now=AFTER
    )

    assert result["classification"] == CANCELLED_PROVEN
    target_events = database.get_offer_operation_events(f"cancel:{TRADE}")
    sibling_events = database.get_offer_operation_events(f"cancel:{OTHER_TRADE}")
    assert [event["outcome"] for event in target_events] == [
        "PREPARED",
        "CANCEL_CONFIRMED",
    ]
    assert target_events[-1]["blocks_mutation"] == 0
    assert [event["outcome"] for event in sibling_events] == ["PREPARED"]
    assert sibling_events[-1]["blocks_mutation"] == 1
    assert database.get_coin_state(OTHER_COIN)["status"] == "locked"


def test_cancel_commit_rechecks_changed_sibling_sequence_inside_terminal_transaction(
    isolated_database,
    monkeypatch,
):
    context, evidence = _persist_grouped_cancel_case()
    original = database._validate_reconciliation_cancel_context

    def mutate_sibling_after_snapshot(conn, *args, **kwargs):
        was_in_transaction = conn.in_transaction
        validated = original(conn, *args, **kwargs)
        result = cancellation_result(
            "CANCEL_UNKNOWN",
            method="task9_race",
            raw_response={"status": "ambiguous"},
            error="CANCEL_UNKNOWN",
        )
        journal = database._journal_values(
            event_id=f"cancel:{OTHER_TRADE}:attempt:1:finalized",
            operation_id=f"cancel:{OTHER_TRADE}",
            intent_id=f"cancel-target:{OTHER_TRADE}",
            operation_type="CANCEL",
            attempt=1,
            phase="FINALIZED",
            outcome="CANCEL_UNKNOWN",
            request_timestamp=AFTER,
            wallet_identity_json={
                "wallet_fingerprint_hash": WALLET,
                "network": NETWORK,
            },
            transaction_id=None,
            spend_identity=None,
            evidence_json={"trade_id": OTHER_TRADE, "cancel_result": result},
            evidence_sha256=None,
            reason_code="CANCEL_UNKNOWN",
            blocks_mutation=True,
            created_at=AFTER,
        )
        database._insert_offer_operation_event(conn, journal)
        if not was_in_transaction:
            conn.commit()
        return validated

    monkeypatch.setattr(
        database,
        "_validate_reconciliation_cancel_context",
        mutate_sibling_after_snapshot,
    )

    with pytest.raises(ValueError, match="Task 8.*cohort changed"):
        reconcile_offer(
            "intent-task9", evidence=evidence, cancel_context=context, now=AFTER
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_coin_state(OTHER_COIN)["status"] == "locked"
    assert _journal_for("intent-task9") == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize("field", ["evidence_sha256", "reason_code"])
def test_journal_scalar_identity_rejects_without_string_coercion(field):
    calls = []

    class HostileJournalScalar:
        def __str__(self):
            calls.append(field)
            raise AssertionError("hostile journal scalar was coerced")

    arguments = {
        "event_id": "journal:exact-scalar",
        "operation_id": "journal:exact-scalar",
        "intent_id": None,
        "operation_type": "RECONCILE",
        "attempt": 1,
        "phase": "FINALIZED",
        "outcome": "UNKNOWN",
        "request_timestamp": AFTER,
        "wallet_identity_json": {"network": NETWORK},
        "transaction_id": None,
        "spend_identity": None,
        "evidence_json": {"bounded": False},
        "evidence_sha256": None,
        "reason_code": None,
        "blocks_mutation": True,
        "created_at": AFTER,
    }
    arguments[field] = HostileJournalScalar()

    with pytest.raises(ValueError, match="exact text"):
        database._journal_values(**arguments)

    assert calls == []


def test_cancel_commit_requires_auxiliary_ids_bound_to_every_task8_member(
    isolated_database,
):
    context, evidence = _persist_grouped_cancel_case()
    context["auxiliary_coin_ids"] = [FEE_COIN]
    transaction = evidence["transaction_history"]["records"][0]
    transaction["spent"].append(
        {
            "coin_id": FEE_COIN,
            "asset_id": "xch",
            "amount": 100,
            "address_kind": "own",
        }
    )
    transaction["created"].append(
        {
            "coin_id": FEE_RETURN,
            "asset_id": "xch",
            "amount": 90,
            "address_kind": "own",
        }
    )
    evidence["coin_records"]["records"].update(
        {
            FEE_COIN: _coin(
                FEE_COIN,
                asset_id="xch",
                amount=100,
                spent_height=42,
                transaction_id=TX,
            ),
            FEE_RETURN: _coin(
                FEE_RETURN,
                asset_id="xch",
                amount=90,
                created_height=42,
                transaction_id=TX,
            ),
        }
    )

    with pytest.raises(ValueError, match="Task 8.*auxiliary"):
        reconcile_offer(
            "intent-task9", evidence=evidence, cancel_context=context, now=AFTER
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_coin_state(OTHER_COIN)["status"] == "locked"
    assert _journal_for("intent-task9") == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_cancel_commit_rejects_finalized_result_that_drops_bound_auxiliary_ids(
    isolated_database,
):
    context, evidence = _persist_grouped_cancel_case(durable_auxiliary=[FEE_COIN])
    for member in context["members"]:
        result = cancellation_result(
            CANCEL_SUBMITTED_UNCONFIRMED,
            method="task9_grouped_test",
            raw_response={"success": True},
            transaction_id=TX,
            spend_identity=SPEND,
        )
        database.finalize_offer_cancel(
            operation_id=f"cancel:{member['trade_id']}",
            event_id=f"cancel:{member['trade_id']}:attempt:1:finalized",
            trade_id=member["trade_id"],
            intent_id=member["intent_id"],
            attempt=1,
            cancel_result=result,
            wallet_identity_json={
                "wallet_fingerprint_hash": WALLET,
                "network": NETWORK,
            },
            evidence_json={
                "trade_id": member["trade_id"],
                "cancel_result": result,
                "auxiliary_coin_ids": [],
            },
            finalized_at=AFTER,
        )

    with pytest.raises(ValueError, match="Task 8.*auxiliary"):
        reconcile_offer(
            "intent-task9", evidence=evidence, cancel_context=context, now=AFTER
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_coin_state(OTHER_COIN)["status"] == "locked"
    assert _journal_for("intent-task9") == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_cancel_commit_rejects_sibling_facts_not_bound_to_task4_intent(
    isolated_database,
):
    context, evidence = _persist_grouped_cancel_case()
    sibling_context = next(
        member for member in context["members"] if member["trade_id"] == OTHER_TRADE
    )
    sibling_context["offered_amount_atomic"] = "2001"
    sibling_offer = next(
        offer
        for offer in evidence["offer_history"]["records"]
        if offer["trade_id"] == OTHER_TRADE
    )
    sibling_offer["summary"]["offered"][ASSET] = 2001
    transaction = evidence["transaction_history"]["records"][0]
    next(flow for flow in transaction["spent"] if flow["coin_id"] == OTHER_COIN)[
        "amount"
    ] = 2001
    next(flow for flow in transaction["created"] if flow["coin_id"] == OTHER_RETURN)[
        "amount"
    ] = 2001
    evidence["coin_records"]["records"][OTHER_COIN]["amount"] = 2001
    evidence["coin_records"]["records"][OTHER_RETURN]["amount"] = 2001

    assert (
        _classify(evidence, cancel_context=context)["classification"]
        == CANCELLED_PROVEN
    )
    with pytest.raises(ValueError, match="Task 8 member intent facts"):
        reconcile_offer(
            "intent-task9", evidence=evidence, cancel_context=context, now=AFTER
        )

    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_coin_state(OTHER_COIN)["status"] == "locked"
    assert _journal_for("intent-task9") == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize(
    ("asset_id", "amount", "offer_id"),
    [
        (ASSET, 1000, TRADE),
        ("xch", 999, TRADE),
        ("xch", 1000, OTHER_TRADE),
    ],
)
def test_expiry_wrong_asset_amount_or_offer_link_preserves_lock(
    isolated_database, asset_id, amount, offer_id
):
    _persist_created_offer()
    evidence = _evidence(
        offers=[_offer(status=5, transaction_id="")],
        transactions=[],
        coins={
            COIN: _coin(
                COIN,
                asset_id=asset_id,
                amount=amount,
                offer_id=offer_id,
            )
        },
    )

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EXPIRY_SAFE_RELEASE_UNPROVEN"
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"


def test_exact_expiry_proof_persists_terminal_and_releases_selected_coin(
    isolated_database,
):
    _persist_created_offer()
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

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == EXPIRED_PROVEN
    assert result["applied"] is True
    assert database.get_offer(TRADE)["status"] == "expired"
    assert database.get_coin_state(COIN)["status"] == "free"
    assert database.get_authoritative_terminal_record(TRADE)["outcome"] == (
        EXPIRED_PROVEN
    )


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


def test_wallet_reader_exception_persists_unknown_and_named_latch(
    isolated_database, monkeypatch
):
    _persist_created_offer()

    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime.fromisoformat(AFTER.replace("Z", "+00:00"))
            target = current if tz is None else current.astimezone(tz)
            return cls.fromtimestamp(target.timestamp(), target.tzinfo)

    def fail_offers(**_kwargs):
        raise RuntimeError("hostile reader detail must not escape")

    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=fail_offers,
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [],
            "total": 0,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: _coin(COIN, asset_id="xch", amount=1000)
        },
    )
    monkeypatch.setattr(reconciliation, "datetime", ControlledDateTime)

    result = reconcile_offer("intent-task9", wallet_facade=facade, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "OFFER_HISTORY_INCOMPLETE"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert json.loads(latch["blocking_operation_ids_json"]) == [
        "reconcile:intent-task9"
    ]


class _HostileEvidenceAbort(BaseException):
    pass


class _RaisingTruthValue:
    def __bool__(self):
        raise _HostileEvidenceAbort("truthiness must never escape evidence handling")


class _HostileMapping(dict):
    def items(self):
        raise _HostileEvidenceAbort("mapping subclass must never be traversed")


def test_hostile_coin_identity_truthiness_totalizes_to_minimal_unknown_and_latch(
    isolated_database,
):
    _persist_created_offer()
    evidence = _evidence()
    evidence["coin_records"]["records"][COIN]["coin_id"] = _RaisingTruthValue()

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_ENCODING_FAILED"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    durable = json.loads(_journal_for("intent-task9")[-1]["evidence_json"])
    assert durable == {
        "classification": {
            "classification": UNKNOWN,
            "reason_code": "EVIDENCE_ENCODING_FAILED",
        },
        "evidence": {"encoding_failed": True, "redacted": True},
    }
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_loader_contains_baseexception_from_hostile_coin_record_before_db_boundary(
    isolated_database,
):
    _persist_created_offer()
    hostile_record = _coin(COIN, asset_id="xch", amount=1000)
    hostile_record["coin_id"] = _RaisingTruthValue()
    facade = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "wallet_fingerprint_hash": WALLET,
            "network_id": NETWORK,
            "observed_at_utc": AT,
        },
        get_all_offers=lambda **_kwargs: {"offers": [_offer()], "total": 1},
        get_transactions_list=lambda **_kwargs: {
            "success": True,
            "transactions": [_transaction()],
            "total": 1,
        },
        get_coins_by_ids=lambda _coin_ids: {
            COIN: hostile_record,
            RECEIVE: _coin(
                RECEIVE,
                asset_id=ASSET,
                amount=2000,
                created_height=42,
                transaction_id=TX,
            ),
        },
    )

    result = reconcile_offer("intent-task9", wallet_facade=facade, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_fills(cat_asset_id=ASSET, limit=10) == []
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_hostile_mapping_subclass_is_rejected_without_traversal_or_escape(
    isolated_database,
):
    _persist_created_offer()
    evidence = _evidence()
    evidence["coin_records"]["records"] = _HostileMapping(
        evidence["coin_records"]["records"]
    )

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_ENCODING_FAILED"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def _hostile_excessive_depth() -> dict:
    root: dict = {}
    cursor = root
    for _ in range(80):
        child: dict = {}
        cursor["child"] = child
        cursor = child
    return root


def _hostile_oversized_utf8_key() -> dict:
    return {"e" * (reconciliation._MAX_CANONICAL_TEXT_BYTES + 1): None}


@pytest.mark.parametrize("source_name", ["offer_history", "transaction_history"])
def test_deep_identity_bearing_history_row_totalizes_to_durable_unknown(
    isolated_database,
    source_name,
):
    _persist_created_offer()
    evidence = _evidence()
    deep = {}
    cursor = deep
    for _index in range(10_000):
        child = {}
        cursor["child"] = child
        cursor = child
    if source_name == "offer_history":
        hostile_row = {"trade_id": OTHER_TRADE, "hostile": deep}
    else:
        hostile_row = {"transaction_id": OTHER_COIN, "hostile": deep}
    evidence[source_name]["records"].append(hostile_row)

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_ENCODING_FAILED"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    assert _journal_for("intent-task9")[-1]["outcome"] == UNKNOWN
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize(
    "hostile",
    [
        lambda: {1: "non-string", "safe": "value"},
        lambda: [float("nan"), float("inf"), float("-inf")],
        _hostile_excessive_depth,
        lambda: list(range(4097)),
        _hostile_oversized_utf8_key,
    ],
    ids=[
        "mixed-keys",
        "nonfinite",
        "excessive-depth",
        "container-cap",
        "oversized-utf8-key",
    ],
)
def test_hostile_proof_encoding_persists_minimal_unknown_and_named_latch(
    isolated_database,
    hostile,
):
    _persist_created_offer()
    evidence = _evidence()
    evidence["hostile"] = hostile()

    result = reconcile_offer("intent-task9", evidence=evidence, now=AFTER)

    assert result["classification"] == UNKNOWN
    assert result["reason_code"] == "EVIDENCE_ENCODING_FAILED"
    assert result["applied"] is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"
    events = _journal_for("intent-task9")
    assert [event["outcome"] for event in events] == [UNKNOWN]
    durable = json.loads(events[0]["evidence_json"])
    assert durable == {
        "classification": {
            "classification": UNKNOWN,
            "reason_code": "EVIDENCE_ENCODING_FAILED",
        },
        "evidence": {"encoding_failed": True, "redacted": True},
    }
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert json.loads(latch["blocking_operation_ids_json"]) == [
        "reconcile:intent-task9"
    ]
    event = _journal_for("intent-task9")[-1]
    assert event["outcome"] == UNKNOWN
    assert "hostile reader detail" not in event["evidence_json"]


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
        coins={
            COIN: _coin(
                COIN,
                asset_id="xch",
                amount=1000,
                offer_id=TRADE,
            )
        },
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


def test_repeated_wallet_absence_cannot_retire_created_intent_or_release_coin(
    isolated_database,
):
    """A fresh-but-incomplete wallet book is never terminal proof."""

    intent = _persist_created_offer()
    row = dict(database.get_offer(TRADE))
    row["created_at"] = AT
    loop = object.__new__(bot_loop.BotLoop)
    loop.offer_manager = SimpleNamespace(
        _recently_created={TRADE: 1.0},
        _offer_details_cache={TRADE: {"side": "buy"}},
    )
    loop._adaptive_target_backoff_until = {"buy": 0.0, "sell": 0.0}

    for now_ts in (2_000_000_000.0, 2_000_000_300.0, 2_000_003_600.0):
        retired = loop._retire_wallet_missing_db_offers(
            db_buy_offers=[row],
            db_sell_offers=[],
            wallet_buy_ids=set(),
            wallet_sell_ids=set(),
            wallet_sync_fresh=True,
            now_ts=now_ts,
        )
        assert retired == {"buy": set(), "sell": set()}
        assert database.get_offer(TRADE)["status"] == "open"
        assert database.get_offer(TRADE)["lifecycle_state"] == "open"
        assert database.get_offer_intent(intent["intent_id"])["lifecycle_state"] == (
            "created"
        )
        assert database.get_coin_state(COIN)["status"] == "locked"
        assert database.get_coin_state(COIN)["trade_id"] == TRADE

    # The legacy status spelling is diagnostic only and cannot bypass the
    # authoritative reconciliation transaction even when called directly.
    assert database.update_offer_status(TRADE, "not_submitted") is False
    assert database.get_offer(TRADE)["status"] == "open"
    assert database.get_coin_state(COIN)["status"] == "locked"

    with pytest.raises(ValueError, match="selected coin is not free"):
        database.prepare_offer_intent(
            intent_id="intent-task9-second",
            operation_id="create:intent-task9-second",
            event_id="create:intent-task9-second:prepared",
            run_id="run-task9",
            wallet_fingerprint_hash=WALLET,
            network=NETWORK,
            asset_id=ASSET,
            side="buy",
            tier="inner",
            purpose="normal_lifecycle",
            slot_key="slot:intent-task9-second",
            generation=0,
            offered_amount_atomic="1000",
            requested_amount_atomic="2000",
            selected_coin_ids_json=[COIN],
            wallet_identity_json={
                "wallet_fingerprint_hash": WALLET,
                "network": NETWORK,
            },
            evidence_json={"intent": "second"},
            prepared_at=AFTER,
            reserve_selected_coins=True,
        )


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
