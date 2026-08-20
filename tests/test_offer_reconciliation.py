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
        {"prior_lifecycle_state": "open", "trade_id": TRADE},
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


def _persist_cancel_prepared() -> dict:
    return database.prepare_offer_cancel(
        operation_id=f"cancel:{TRADE}",
        event_id=PREPARED_EVENT_ID,
        trade_id=TRADE,
        intent_id="intent-task9",
        attempt=1,
        wallet_identity_json={
            "wallet_fingerprint_hash": WALLET,
            "network": NETWORK,
        },
        evidence_json={"trade_id": TRADE},
        prepared_at=AT,
    )


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
        return {
            name: (lambda _row, hook=name: calls.append((hook, _row["fill_id"])))
            for name in hook_names
        }

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
            def run(_row):
                calls[name] += 1
                if name == "fill_classification" and calls[name] == 1:
                    raise RuntimeError("classification hook failed")

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
            def run(_row):
                if name == "offer_filled_event":
                    effect_entered.set()
                    assert release_effect.wait(timeout=5)
                calls[name] += 1

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


def test_post_fill_hook_crash_after_effect_before_receipt_never_duplicates(
    isolated_database,
    monkeypatch,
):
    _persist_created_offer()
    attempts = {name: 0 for name in database._AUTHORITATIVE_FILL_HOOKS}
    effects = {name: 0 for name in database._AUTHORITATIVE_FILL_HOOKS}
    applied = set()

    def callbacks(_fill):
        def callback(name):
            def run(row):
                attempts[name] += 1
                effect_key = (name, row["fill_id"])
                if effect_key not in applied:
                    applied.add(effect_key)
                    effects[name] += 1

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

    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=HOOK_RETRY)

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

    def callbacks(_fill):
        def callback(name):
            def run(row):
                attempts[name] += 1
                effect_key = (name, row["fill_id"])
                if effect_key not in applied:
                    applied.add(effect_key)
                    effects[name] += 1

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

    replay = reconcile_offer("intent-task9", evidence=_evidence(), now=HOOK_RETRY)

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
    callback(fill)
    callback(fill)

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
    monkeypatch.setitem(
        sys.modules, "api_server", SimpleNamespace(bot=SimpleNamespace())
    )

    callbacks = reconciliation._post_fill_hook_callbacks(fill)

    with pytest.raises(RuntimeError, match="offer_filled"):
        callbacks["offer_filled_event"](fill)
    with pytest.raises(RuntimeError, match="BoostManager"):
        callbacks["boost_notification"](fill)


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


def _hostile_excessive_depth() -> dict:
    root: dict = {}
    cursor = root
    for _ in range(80):
        child: dict = {}
        cursor["child"] = child
        cursor = child
    return root


@pytest.mark.parametrize(
    "hostile",
    [
        lambda: {1: "non-string", "safe": "value"},
        lambda: [float("nan"), float("inf"), float("-inf")],
        _hostile_excessive_depth,
        lambda: list(range(4097)),
    ],
    ids=["mixed-keys", "nonfinite", "excessive-depth", "container-cap"],
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
