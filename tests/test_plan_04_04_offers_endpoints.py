"""Slice 04-04 — offers endpoint contract tests.

Tests /api/offers, /api/offers/cancel_all/status, /api/offers/open_count,
/api/offers/cancel_all (POST), /api/offers/cancel (POST):
  - Auth required for write endpoints
  - bot=None → 500 for bot-dependent reads
  - Response shapes and required keys
  - Input validation (missing trade_id, bad JSON)
"""

import os
import json
import shutil
import subprocess
import sys
import types
import unittest
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_test_support import permit_api_mutations

ROOT = Path(__file__).resolve().parents[1]

try:
    import api_server
    import app_bridge

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    app_bridge = None
    _SKIP = str(exc)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _FlaskBase(unittest.TestCase):
    _LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

    def setUp(self):
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        self.token = api_server._LOCAL_API_TOKEN
        self.auth = {"X-Bot-Local-Token": self.token}
        api_server._rate_limit_log.clear()
        permit_api_mutations(self, api_server)

    def tearDown(self):
        api_server._rate_limit_log.clear()

    def _post(self, path, body=None, auth=True):
        headers = dict(self.auth) if auth else {}
        return self.client.post(
            path,
            json=body or {},
            headers=headers,
            environ_base=self._LOOPBACK,
        )

    def _get(self, path, **kwargs):
        kwargs.setdefault("headers", self.auth)
        kwargs.setdefault("environ_base", self._LOOPBACK)
        return self.client.get(path, **kwargs)


def _make_bot(offers=([], [], [])):
    bot = MagicMock()
    bot.is_running.return_value = True
    bot.offer_manager.sync_from_wallet.return_value = offers
    bot.offer_manager.get_wallet_sync_meta.return_value = {
        "fresh": True,
        "using_cache": False,
    }
    bot.offer_manager.sync_from_wallet_with_meta.side_effect = lambda: (
        bot.offer_manager.sync_from_wallet(),
        bot.offer_manager.get_wallet_sync_meta(),
    )
    bot.offer_manager.cancel_all.return_value = {"cancelled": [], "failed": []}
    bot.offer_manager.cancel_offers.return_value = {"success": True}
    bot.coin_manager.is_busy.return_value = False
    return bot


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_refresh_abort_preview_uses_complete_sage_book_not_stale_ui_count(
    monkeypatch,
):
    import blueprints.offers as offers_bp
    import database
    import wallet

    asset_id = "a" * 64
    child_trade = "c" * 64
    other_trades = ["d" * 64, "e" * 64]
    bot = MagicMock()
    bot.is_running.return_value = False
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(offers_bp.cfg, "CAT_ASSET_ID", asset_id, raising=False)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "current_runtime",
        lambda: types.SimpleNamespace(
            run_id="run-preview",
            read_only_status=lambda: types.SimpleNamespace(
                to_dict=lambda: {
                    "allowed": False,
                    "reason_code": "UNRESOLVED_OPERATIONS",
                }
            ),
            wallet_identity_binding=types.SimpleNamespace(
                backend="sage", fingerprint=736588221, network_id="mainnet"
            ),
        ),
    )
    monkeypatch.setattr(
        api_server.mutation_gate, "wallet_fingerprint_hash", lambda _value: "f" * 64
    )
    monkeypatch.setattr(
        wallet,
        "_read_refresh_abort_cleanup_snapshot",
        lambda: {
            "trade_ids": [child_trade, *other_trades],
            "pending_transaction_ids": [],
            "observed_at": "2026-10-13T16:00:00Z",
        },
    )
    monkeypatch.setattr(
        database,
        "list_fenced_refresh_abort_candidates",
        lambda **_scope: [
            {
                "parent_intent_id": "parent",
                "child_intent_id": "child",
                "parent_trade_id": "b" * 64,
                "child_trade_id": child_trade,
                "cancel_operation_id": "cancel:" + "b" * 64,
                "asset_id": asset_id,
                "side": "sell",
            }
        ],
    )
    monkeypatch.setattr(database, "list_incomplete_refresh_aborts", lambda **_scope: [])
    monkeypatch.setattr(
        database,
        "list_stopped_bootstrap_campaigns_for_identity",
        lambda *_scope: [{"campaign_id": "1" * 64, "fee_budget_xch": "0.05"}],
    )
    monkeypatch.setattr(
        database, "get_bootstrap_campaign_authoritative_fee_spent_mojos", lambda _id: 0
    )
    monkeypatch.setattr(
        database, "get_latest_coin_prep_fee_approval_for_campaign", lambda _id: "2" * 64
    )
    monkeypatch.setattr(
        database,
        "get_runtime_safety_latch",
        lambda: {
            "state": "tripped",
            "generation": 7,
            "blocking_operation_ids_json": json.dumps(["cancel:" + "b" * 64]),
        },
    )
    monkeypatch.setattr(
        database,
        "get_runtime_mutation_lease",
        lambda: {"active": 1, "owner_run_id": "run-preview"},
    )
    result = api_server.app.test_client().get(
        "/api/offers/refresh_abort/preview",
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert result.status_code == 200
    body = result.get_json()
    assert body["stage"] == "submitted_parent_proof"
    assert body["wallet"]["active_trade_ids"] == [child_trade, *other_trades]
    assert body["wallet"]["pending_transaction_count"] == 0
    assert body["candidate"]["child_trade_id"] == child_trade
    assert body["safety"]["lease_owned"] is True
    assert body["safety"]["allowed"] is False
    assert body["wallet_effect_started"] is False
    native = app_bridge.AppBridge().get_refresh_abort_preview()
    assert native["success"] is True
    assert native["wallet"]["active_trade_ids"] == [child_trade, *other_trades]

    # Sage can omit a submitted cancellation before Task 9 has written its
    # terminal proof. The preview must keep that journal as the next action.
    monkeypatch.setattr(
        wallet,
        "_read_refresh_abort_cleanup_snapshot",
        lambda: {
            "trade_ids": other_trades,
            "pending_transaction_ids": [],
            "observed_at": "2026-10-13T16:01:00Z",
        },
    )
    monkeypatch.setattr(
        database,
        "list_incomplete_refresh_aborts",
        lambda **_scope: [
            {
                "abort_id": "9" * 64,
                "parent_intent_id": "parent",
                "child_intent_id": "child",
                "campaign_id": "1" * 64,
                "latch_generation": 7,
                "target_trade_ids_json": json.dumps([child_trade, *other_trades]),
                "state": "parent_terminal",
                "wallet_fingerprint_hash": "f" * 64,
                "network": "mainnet",
                "asset_id": asset_id,
            }
        ],
    )
    monkeypatch.setattr(
        database,
        "get_offer_operation_events",
        lambda op: (
            [
                {
                    "phase": "FINALIZED",
                    "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                    "blocks_mutation": 1,
                }
            ]
            if op == f"cancel:{child_trade}"
            else []
        ),
    )
    pending = api_server.app.test_client().get(
        "/api/offers/refresh_abort/preview",
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert pending.status_code == 200
    pending_body = pending.get_json()
    assert pending_body["wallet"]["active_trade_ids"] == other_trades
    assert pending_body["next_target_journal"]["trade_id"] == child_trade
    assert pending_body["next_target_journal"]["phase"] == "FINALIZED"

    # Natural expiry of the unpublished child must be offered as a proof-only
    # step before the empty-book completion button can close the fence.
    monkeypatch.setattr(
        wallet,
        "_read_refresh_abort_cleanup_snapshot",
        lambda: {
            "trade_ids": [],
            "pending_transaction_ids": [],
            "observed_at": "2026-10-13T16:02:00Z",
        },
    )
    monkeypatch.setattr(database, "get_offer_operation_events", lambda _op: [])
    monkeypatch.setattr(
        database,
        "get_offer_intent_by_trade_id",
        lambda trade: {
            "intent_id": "child" if trade == child_trade else trade,
            "lifecycle_state": "created",
            "asset_id": asset_id,
            "wallet_fingerprint_hash": "f" * 64,
            "network": "mainnet",
        },
    )
    expired = api_server.app.test_client().get(
        "/api/offers/refresh_abort/preview",
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert expired.status_code == 200
    assert expired.get_json()["next_expired_target_trade_id"] == child_trade


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_refresh_abort_begin_rechecks_exact_preview_book_before_parent_proof(
    monkeypatch,
):
    import blueprints.offers as offers_bp
    import database
    import wallet

    parent_trade, child_trade, other_trade = "b" * 64, "c" * 64, "d" * 64
    asset_id = "a" * 64
    candidate = {
        "parent_intent_id": "parent",
        "child_intent_id": "child",
        "parent_trade_id": parent_trade,
        "child_trade_id": child_trade,
        "cancel_operation_id": "cancel:" + parent_trade,
        "asset_id": asset_id,
        "side": "sell",
    }
    bot = MagicMock()
    bot.is_running.return_value = False
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(offers_bp.cfg, "CAT_ASSET_ID", asset_id, raising=False)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "current_runtime",
        lambda: types.SimpleNamespace(
            run_id="run-exact",
            wallet_identity_binding=types.SimpleNamespace(
                backend="sage", fingerprint=736588221, network_id="mainnet"
            ),
        ),
    )
    monkeypatch.setattr(
        api_server.mutation_gate, "wallet_fingerprint_hash", lambda _value: "f" * 64
    )
    monkeypatch.setattr(
        wallet,
        "_read_refresh_abort_cleanup_snapshot",
        lambda: {
            "trade_ids": [child_trade, other_trade],
            "pending_transaction_ids": [],
            "observed_at": "2026-10-13T16:00:00Z",
        },
    )
    monkeypatch.setattr(
        database,
        "list_fenced_refresh_abort_candidates",
        lambda **_scope: [candidate],
    )
    monkeypatch.setattr(
        database,
        "get_runtime_mutation_lease",
        lambda: {
            "active": 1,
            "owner_run_id": "run-exact",
            "lease_version": 3,
        },
    )
    called = []
    monkeypatch.setattr(
        database,
        "begin_refresh_abort",
        lambda **request: (
            called.append(("begin", request))
            or {"abort_id": "e" * 64, "state": "fenced"}
        ),
    )
    import offer_reconciliation

    monkeypatch.setattr(
        offer_reconciliation,
        "reconcile_offer",
        lambda parent_id, **scope: (
            called.append(("proof", parent_id, scope))
            or {"classification": "CANCELLED_PROVEN", "applied": True}
        ),
    )
    body = {
        "confirmation": True,
        "parent_intent_id": "parent",
        "child_intent_id": "child",
        "campaign_id": "1" * 64,
        "expected_latch_generation": 7,
        "expected_trade_ids": [child_trade, other_trade],
    }
    client = api_server.app.test_client()
    request_kwargs = {
        "headers": {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        "environ_base": {"REMOTE_ADDR": "127.0.0.1"},
    }
    rejected = client.post(
        "/api/offers/refresh_abort/begin",
        json={**body, "expected_trade_ids": [child_trade]},
        **request_kwargs,
    )
    assert rejected.status_code == 409
    assert called == []
    accepted = client.post(
        "/api/offers/refresh_abort/begin", json=body, **request_kwargs
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["stage"] == "parent_terminal"
    assert called[0][0] == "begin"
    assert called[0][1]["observed_trade_ids"] == [child_trade, other_trade]
    assert called[1] == (
        "proof",
        "parent",
        {"refresh_abort_id": "e" * 64},
    )
    native = app_bridge.AppBridge().begin_refresh_abort(body)
    assert native["stage"] == "parent_terminal"
    assert len(called) == 4


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_refresh_abort_cancel_next_refuses_stale_target_before_wallet_effect(
    monkeypatch,
):
    import blueprints.offers as offers_bp
    import database
    import wallet

    first, second = "c" * 64, "d" * 64
    abort_id = "e" * 64
    approval_id = "2" * 64
    bot = MagicMock()
    bot.is_running.return_value = False
    effects = []
    bot.offer_manager.cancel_refresh_abort_targets.side_effect = lambda **request: (
        effects.append(request)
        or {
            "trade_id": first,
            "result": {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "_catalyst_effect_attempted": True,
            },
        }
    )
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(offers_bp.cfg, "CAT_ASSET_ID", "a" * 64, raising=False)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "current_runtime",
        lambda: types.SimpleNamespace(
            run_id="run-exact",
            wallet_identity_binding=types.SimpleNamespace(
                backend="sage", fingerprint=736588221, network_id="mainnet"
            ),
        ),
    )
    monkeypatch.setattr(
        wallet,
        "_read_refresh_abort_cleanup_snapshot",
        lambda: {
            "trade_ids": [first, second],
            "pending_transaction_ids": [],
            "observed_at": "2026-10-13T16:00:00Z",
        },
    )
    monkeypatch.setattr(
        database,
        "get_refresh_abort",
        lambda _abort_id: {
            "abort_id": abort_id,
            "state": "parent_terminal",
            "latch_generation": 7,
            "campaign_id": "1" * 64,
            "wallet_fingerprint_hash": "f" * 64,
            "network": "mainnet",
            "asset_id": "a" * 64,
            "target_trade_ids_json": json.dumps([first, second]),
        },
    )
    monkeypatch.setattr(
        api_server.mutation_gate, "wallet_fingerprint_hash", lambda _value: "f" * 64
    )
    monkeypatch.setattr(
        database,
        "get_latest_coin_prep_fee_approval_for_campaign",
        lambda _id: approval_id,
    )
    monkeypatch.setattr(database, "get_offer_operation_events", lambda _id: [])
    body = {
        "confirmation": True,
        "abort_id": abort_id,
        "expected_latch_generation": 7,
        "expected_trade_ids": [first, second],
        "expected_next_trade_id": first,
        "fee_approval_id": approval_id,
    }
    client = api_server.app.test_client()
    request_kwargs = {
        "headers": {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        "environ_base": {"REMOTE_ADDR": "127.0.0.1"},
    }
    rejected = client.post(
        "/api/offers/refresh_abort/cancel_next",
        json={**body, "expected_next_trade_id": second},
        **request_kwargs,
    )
    assert rejected.status_code == 409
    assert effects == []
    monkeypatch.setattr(
        database,
        "get_offer_operation_events",
        lambda _id: [{"phase": "FINALIZED", "outcome": "CANCEL_UNKNOWN"}],
    )
    held = client.post(
        "/api/offers/refresh_abort/cancel_next", json=body, **request_kwargs
    )
    assert held.status_code == 409
    assert effects == []
    monkeypatch.setattr(database, "get_offer_operation_events", lambda _id: [])
    accepted = client.post(
        "/api/offers/refresh_abort/cancel_next", json=body, **request_kwargs
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["stage"] == "awaiting_target_proof"
    assert effects == [
        {
            "abort_id": abort_id,
            "expected_latch_generation": 7,
            "fee_approval_id": approval_id,
        }
    ]
    native = app_bridge.AppBridge().cancel_next_refresh_abort_offer(body)
    assert native["stage"] == "awaiting_target_proof"
    assert len(effects) == 2

    # The fenced desktop intentionally has no BotLoop or native trading bridge.
    import coin_manager
    import offer_manager

    class FeeInventory:
        def __init__(self):
            self.fee_pool = object()

        def refresh_fee_pool_from_wallet(self):
            effects.append("fee_inventory_read")

    class CleanupManager:
        def __init__(self):
            self._fee_pool = None

        def cancel_refresh_abort_targets(self, **request):
            assert self._fee_pool is not None
            effects.append(request)
            return {
                "trade_id": first,
                "result": {
                    "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                    "_catalyst_effect_attempted": True,
                },
            }

    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_refresh_abort_recovery_active", True)
    monkeypatch.setattr(coin_manager, "CoinManager", FeeInventory)
    monkeypatch.setattr(offer_manager, "OfferManager", CleanupManager)
    restricted = client.post(
        "/api/offers/refresh_abort/cancel_next", json=body, **request_kwargs
    )
    assert restricted.status_code == 200
    assert restricted.get_json()["stage"] == "awaiting_target_proof"
    assert effects[-2:] == [
        "fee_inventory_read",
        {
            "abort_id": abort_id,
            "expected_latch_generation": 7,
            "fee_approval_id": approval_id,
        },
    ]


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
@pytest.mark.parametrize("frozen_targets", [[], [{"asset": "xch", "amount": "1"}]])
def test_restricted_refresh_abort_fee_consent_is_exact_campaign_only(
    monkeypatch, frozen_targets
):
    import blueprints.offers as offers_bp
    import coin_prep_fee_approval
    import coin_prep_fee_runtime
    import database
    import wallet

    abort_id, campaign_id, trade_id = "e" * 64, "1" * 64, "c" * 64
    preview_id, approval_id = "2" * 64, "3" * 64
    effects = []
    monkeypatch.setattr(api_server, "_refresh_abort_recovery_active", True)
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(
        api_server, "has_exact_refresh_abort_startup_candidate", lambda **_kw: True
    )
    monkeypatch.setattr(offers_bp.cfg, "CAT_ASSET_ID", "a" * 64, raising=False)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "current_runtime",
        lambda: types.SimpleNamespace(
            run_id="exact-recovery",
            wallet_identity_binding=types.SimpleNamespace(
                backend="sage", fingerprint=736588221, network_id="mainnet"
            ),
        ),
    )
    monkeypatch.setattr(
        api_server.mutation_gate, "wallet_fingerprint_hash", lambda _value: "f" * 64
    )
    monkeypatch.setattr(
        database,
        "get_runtime_mutation_lease",
        lambda: {"active": 1, "owner_run_id": "exact-recovery"},
    )
    monkeypatch.setattr(database, "get_runtime_safety_latch", lambda: {"generation": 7})
    monkeypatch.setattr(
        database,
        "get_refresh_abort",
        lambda _id: {
            "abort_id": abort_id,
            "state": "parent_terminal",
            "latch_generation": 7,
            "campaign_id": campaign_id,
            "wallet_fingerprint_hash": "f" * 64,
            "network": "mainnet",
            "asset_id": "a" * 64,
            "target_trade_ids_json": json.dumps([trade_id]),
        },
    )
    monkeypatch.setattr(
        database,
        "get_bootstrap_campaign",
        lambda _id: {
            "campaign_id": campaign_id,
            "revision": 1,
            "status": "stopped",
            "network": "mainnet",
            "wallet_fingerprint": 736588221,
            "asset_id": "a" * 64,
        },
    )
    book = {"trade_ids": [trade_id], "pending_transaction_ids": []}
    monkeypatch.setattr(wallet, "_read_refresh_abort_cleanup_snapshot", lambda: book)
    monkeypatch.setattr(
        coin_prep_fee_approval,
        "preview_coin_prep_fees",
        lambda options: (
            effects.append(("preview", options))
            or {
                "available": True,
                "preview_id": preview_id,
                "preparation_transaction_count_min": 0,
                "suggested_maximum_fee_mojos": 5000,
                "minimum_cancellation_reserve_mojos": 1000,
            }
        ),
    )
    monkeypatch.setattr(
        database,
        "get_coin_prep_fee_preview",
        lambda _id: {
            "request_options_json": json.dumps(
                {
                    "bootstrap_campaign_id": campaign_id,
                    "bootstrap_campaign_revision": 1,
                    "cancellation_recovery_action": "cancel_all",
                }
            )
        },
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_fee_economic_snapshot",
        lambda _options: {
            "recovery_only": True,
            "campaign": {"campaign_id": campaign_id},
            "recipe": {"targets": frozen_targets},
        },
    )
    monkeypatch.setattr(
        coin_prep_fee_approval,
        "approve_coin_prep_fees",
        lambda **kwargs: (
            effects.append(("approve", kwargs)) or {"approval_id": approval_id}
        ),
    )
    client = api_server.app.test_client()
    req = {
        "headers": {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        "environ_base": {"REMOTE_ADDR": "127.0.0.1"},
    }
    scope = {
        "abort_id": abort_id,
        "expected_latch_generation": 7,
        "expected_trade_ids": [trade_id],
    }
    malformed = client.post(
        "/api/offers/refresh_abort/fee_preview",
        json={**scope, "expected_trade_ids": [{"trade_id": trade_id}]},
        **req,
    )
    assert malformed.status_code == 400
    assert effects == []
    quoted = client.post("/api/offers/refresh_abort/fee_preview", json=scope, **req)
    assert quoted.status_code == 200
    assert effects == [
        (
            "preview",
            {
                "bootstrap_campaign_id": campaign_id,
                "bootstrap_campaign_revision": 1,
                "cancellation_recovery_action": "cancel_all",
            },
        )
    ]
    consent = {
        **scope,
        "confirmation": True,
        "preview_id": preview_id,
        "maximum_fee_mojos": "5000",
        "cancellation_reserve_mojos": "1000",
    }
    approved = client.post(
        "/api/offers/refresh_abort/fee_approval", json=consent, **req
    )
    assert approved.status_code == 200
    assert effects[-1] == (
        "approve",
        {
            "preview_id": preview_id,
            "maximum_fee_mojos": 5000,
            "cancellation_reserve_mojos": 1000,
        },
    )
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_fee_economic_snapshot",
        lambda _options: {
            "recovery_only": False,
            "campaign": {"campaign_id": campaign_id},
            "recipe": {"targets": frozen_targets},
        },
    )
    assert (
        client.post(
            "/api/offers/refresh_abort/fee_approval", json=consent, **req
        ).status_code
        == 409
    )
    assert len(effects) == 2
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "read_fee_economic_snapshot",
        lambda _options: {
            "recovery_only": True,
            "campaign": {"campaign_id": campaign_id},
            "recipe": {"targets": frozen_targets},
        },
    )
    book["trade_ids"] = []
    assert (
        client.post(
            "/api/offers/refresh_abort/fee_approval", json=consent, **req
        ).status_code
        == 409
    )
    assert len(effects) == 2
    book["trade_ids"] = [trade_id]
    monkeypatch.setattr(
        database,
        "get_coin_prep_fee_preview",
        lambda _id: {
            "request_options_json": json.dumps(
                {
                    "bootstrap_campaign_id": "9" * 64,
                    "bootstrap_campaign_revision": 1,
                    "cancellation_recovery_action": "cancel_all",
                }
            )
        },
    )
    assert (
        client.post(
            "/api/offers/refresh_abort/fee_approval", json=consent, **req
        ).status_code
        == 409
    )
    assert len(effects) == 2


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_refresh_abort_reconciles_exact_naturally_expired_target_without_cancel(
    monkeypatch,
):
    import database
    import mutation_gate
    import offer_reconciliation
    import wallet

    abort_id, trade_id = "e" * 64, "c" * 64
    abort = {
        "abort_id": abort_id,
        "state": "parent_terminal",
        "latch_generation": 7,
        "target_trade_ids_json": json.dumps([trade_id]),
        "wallet_fingerprint_hash": "f" * 64,
        "network": "mainnet",
        "asset_id": "a" * 64,
    }
    target = {
        "intent_id": "child",
        "lifecycle_state": "created",
        "wallet_fingerprint_hash": "f" * 64,
        "network": "mainnet",
        "asset_id": "a" * 64,
    }
    monkeypatch.setattr(database, "get_refresh_abort", lambda _id: abort)
    monkeypatch.setattr(database, "get_offer_intent_by_trade_id", lambda _id: target)
    monkeypatch.setattr(database, "get_offer_operation_events", lambda _id: [])
    authorized = []
    monkeypatch.setattr(
        database,
        "authorize_refresh_abort_expiry_target",
        lambda **kwargs: authorized.append(kwargs) or {"intent_id": "child"},
    )
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snapshot = {"trade_ids": [], "pending_transaction_ids": [], "observed_at": now}
    monkeypatch.setattr(
        wallet, "_read_refresh_abort_cleanup_snapshot", lambda: snapshot
    )
    monkeypatch.setattr(
        mutation_gate, "current_runtime", lambda: MagicMock(run_id="owner")
    )
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_refresh_abort_recovery_active", True)
    monkeypatch.setattr(
        offer_reconciliation,
        "load_authoritative_evidence",
        lambda _target: {"proof": "exact expiry"},
    )
    monkeypatch.setattr(
        offer_reconciliation,
        "classify_terminal_evidence",
        lambda *_args, **_kwargs: {"classification": "EXPIRED_PROVEN"},
    )
    committed = []
    monkeypatch.setattr(
        offer_reconciliation,
        "reconcile_offer",
        lambda intent_id, **kwargs: (
            committed.append((intent_id, kwargs))
            or {"classification": "EXPIRED_PROVEN", "applied": True}
        ),
    )
    client = api_server.app.test_client()
    response = client.post(
        "/api/offers/refresh_abort/reconcile_target",
        json={
            "abort_id": abort_id,
            "trade_id": trade_id,
            "expected_latch_generation": 7,
        },
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 200
    assert response.get_json()["classification"] == "EXPIRED_PROVEN"
    assert authorized[0]["trade_id"] == trade_id
    assert authorized[0]["observed_trade_ids"] == []
    assert committed[0][0] == "child"

    monkeypatch.setattr(
        offer_reconciliation,
        "classify_terminal_evidence",
        lambda *_args, **_kwargs: {"classification": "ACTIVE_PROVEN"},
    )
    denied = client.post(
        "/api/offers/refresh_abort/reconcile_target",
        json={
            "abort_id": abort_id,
            "trade_id": trade_id,
            "expected_latch_generation": 7,
        },
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert denied.status_code == 409
    assert len(committed) == 1


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_refresh_abort_proof_and_completion_routes_do_not_submit_wallet_effect(
    monkeypatch,
):
    import database
    import offer_reconciliation

    abort_id, trade_id = "e" * 64, "c" * 64
    abort = {
        "abort_id": abort_id,
        "state": "parent_terminal",
        "latch_generation": 7,
        "target_trade_ids_json": json.dumps([trade_id]),
        "wallet_fingerprint_hash": "f" * 64,
        "network": "mainnet",
        "asset_id": "a" * 64,
    }
    monkeypatch.setattr(database, "get_refresh_abort", lambda _id: abort)
    monkeypatch.setattr(
        database,
        "get_offer_intent_by_trade_id",
        lambda _id: {
            "intent_id": "child",
            "lifecycle_state": "created",
            "wallet_fingerprint_hash": "f" * 64,
            "network": "mainnet",
            "asset_id": "a" * 64,
        },
    )
    monkeypatch.setattr(
        database,
        "get_offer_operation_events",
        lambda _id: [{"phase": "FINALIZED"}],
    )
    proofs = []
    monkeypatch.setattr(
        offer_reconciliation,
        "reconcile_offer",
        lambda intent_id: (
            proofs.append(intent_id)
            or {"classification": "CANCELLED_PROVEN", "applied": True}
        ),
    )
    bot = MagicMock()
    bot.is_running.return_value = False
    completions = []
    bot.offer_manager.complete_refresh_abort_cleanup.side_effect = lambda **request: (
        completions.append(request) or {"state": "aborted"}
    )
    monkeypatch.setattr(api_server, "bot", bot)
    client = api_server.app.test_client()
    request_kwargs = {
        "headers": {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        "environ_base": {"REMOTE_ADDR": "127.0.0.1"},
    }
    proof_body = {
        "abort_id": abort_id,
        "trade_id": trade_id,
        "expected_latch_generation": 7,
    }
    proof = client.post(
        "/api/offers/refresh_abort/reconcile_target",
        json=proof_body,
        **request_kwargs,
    )
    assert proof.status_code == 200
    assert proof.get_json()["stage"] == "target_terminal"
    assert proofs == ["child"]
    assert (
        app_bridge.AppBridge().reconcile_refresh_abort_target(proof_body)["stage"]
        == "target_terminal"
    )
    complete_body = {
        "confirmation": True,
        "abort_id": abort_id,
        "expected_latch_generation": 7,
    }
    complete = client.post(
        "/api/offers/refresh_abort/complete", json=complete_body, **request_kwargs
    )
    assert complete.status_code == 200
    assert complete.get_json()["stage"] == "aborted"
    assert app_bridge.AppBridge().complete_refresh_abort(complete_body)["stage"] == (
        "aborted"
    )
    assert completions == [
        {"abort_id": abort_id, "expected_latch_generation": 7},
        {"abort_id": abort_id, "expected_latch_generation": 7},
    ]

    import offer_manager

    class CleanupManager:
        def complete_refresh_abort_cleanup(self, **request):
            completions.append(request)
            return {"state": "aborted"}

    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setattr(api_server, "_refresh_abort_recovery_active", True)
    monkeypatch.setattr(offer_manager, "OfferManager", CleanupManager)
    restricted = client.post(
        "/api/offers/refresh_abort/complete", json=complete_body, **request_kwargs
    )
    assert restricted.status_code == 200
    assert restricted.get_json()["stage"] == "aborted"
    assert len(completions) == 3


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_native_cancel_all_forwards_coin_prep_fee_approval_body(monkeypatch):
    from flask import request

    approval_id = "a" * 64
    captured = {}

    def fake_cancel_all():
        captured["body"] = request.get_json(silent=True)
        return {"success": True}

    monkeypatch.setattr(api_server, "api_cancel_all", fake_cancel_all)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server.mutation_gate, "enter_mutation", lambda _operation: object()
    )
    monkeypatch.setattr(api_server.mutation_gate, "exit_mutation", lambda _permit: None)

    result = app_bridge.AppBridge().cancel_all_offers(
        {"source": "coin_prep", "fee_approval_id": approval_id}
    )

    assert result["success"] is True
    assert captured["body"] == {
        "source": "coin_prep",
        "fee_approval_id": approval_id,
    }


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_native_cancel_all_reaches_proof_only_route_while_gate_blocked(monkeypatch):
    """The route owns the blocked-gate proof exception; the bridge must reach it."""
    import mutation_gate

    calls = []
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server,
        "wallet_setup_bootstrap_allows",
        lambda _operation: False,
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("UNRESOLVED_OPERATIONS", operation)
        ),
    )
    monkeypatch.setattr(
        api_server,
        "api_cancel_all",
        lambda: (
            calls.append("proof-only-route")
            or {"success": False, "async": True, "reconciliation_only": True}
        ),
    )

    result = app_bridge.AppBridge().cancel_all_offers({})

    assert calls == ["proof-only-route"]
    assert result["reconciliation_only"] is True


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_native_cancel_all_unresolved_gate_only_checks_old_proof(monkeypatch):
    from blueprints.offers import _reset_cancel_all_state

    stopped = _make_bot()
    stopped.is_running.return_value = False
    stopped.offer_manager.reconcile_submitted_cancels_only.return_value = 0
    blocked = types.SimpleNamespace(
        allowed=False,
        reason_code="UNRESOLVED_OPERATIONS",
        blocking_operation_ids=("cancel:" + "a" * 64,),
    )
    clear = types.SimpleNamespace(allowed=True, reason_code="")
    states = iter((blocked, clear))
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(api_server, "bot", stopped)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "read_only_status",
        lambda: next(states),
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "enter_mutation",
        lambda _operation: (_ for _ in ()).throw(
            AssertionError("proof-only path must not enter the mutation gate")
        ),
    )
    _reset_cancel_all_state()
    try:
        with patch("threading.Thread") as thread_cls:
            thread_cls.return_value.start.side_effect = lambda: (
                thread_cls.call_args.kwargs["target"]()
            )
            result = app_bridge.AppBridge().cancel_all_offers({})

        assert result["async"] is True
        assert result["reconciliation_only"] is True
        stopped.offer_manager.reconcile_submitted_cancels_only.assert_called_once_with()
        stopped.offer_manager.cancel_offers.assert_not_called()
    finally:
        _reset_cancel_all_state()


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_native_cancel_all_allowed_gate_still_blocks_unpermitted_cancellation(
    monkeypatch,
):
    import mutation_gate

    stopped = _make_bot()
    stopped.is_running.return_value = False
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(api_server, "bot", stopped)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "read_only_status",
        lambda: types.SimpleNamespace(allowed=True, reason_code=""),
    )
    monkeypatch.setattr(
        api_server.mutation_gate,
        "enter_mutation",
        lambda operation: (_ for _ in ()).throw(
            mutation_gate.MutationBlocked("LEASE_OWNED_BY_OTHER", operation)
        ),
    )

    result = app_bridge.AppBridge().cancel_all_offers({})

    assert result["success"] is False
    assert result["reason"] == "LEASE_OWNED_BY_OTHER"
    stopped.offer_manager.cancel_offers.assert_not_called()


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_history_age_label_treats_legacy_naive_utc_timestamp_as_utc():
    timestamp = (datetime.now(timezone.utc) - timedelta(days=90)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    label = api_server._history_age_label(timestamp)

    assert label.endswith("d ago")
    assert float(label.removesuffix("d ago")) >= 89.9


def test_generic_cancel_all_progress_consumer_never_claims_terminal_confirmation():
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the bounded GUI consumer test")
    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    helper_source = (
        "function cancelAllProgressView"
        + gui_source.split("function cancelAllProgressView", 1)[1].split(
            "function renderCancelAllProgress", 1
        )[0]
    )
    status = {
        "phase": "complete",
        "total": 3,
        "pending": 2,
        "failed": 1,
        "cancelled": 99,
        "message": "Cancellation requests journaled",
    }
    script = (
        helper_source
        + "\nconsole.log(JSON.stringify(cancelAllProgressView(JSON.parse(process.argv[1]), 0)));"
    )
    completed = subprocess.run(
        [node, "-e", script, json.dumps(status)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    view = json.loads(completed.stdout)

    assert view["total"] == 3
    assert view["pending"] == 2
    assert view["failed"] == 1
    assert view["processed"] == 3
    assert view["isDone"] is True
    assert view["severity"] == "error"
    assert "awaiting authoritative proof" in view["message"]
    assert "confirmed" not in json.dumps(view).lower()


def test_cancel_all_progress_consumer_counts_only_authoritative_terminals():
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the bounded GUI consumer test")
    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    helper_source = (
        "function cancelAllProgressView"
        + gui_source.split("function cancelAllProgressView", 1)[1].split(
            "function renderCancelAllProgress", 1
        )[0]
    )
    status = {
        "phase": "reconciling",
        "total": 3,
        "cancelled": 2,
        "pending": 1,
        "failed": 0,
        "message": "Waiting for authoritative cancellation proof: 2/3 offers terminal.",
    }
    script = (
        helper_source
        + "\nconsole.log(JSON.stringify(cancelAllProgressView(JSON.parse(process.argv[1]), 0)));"
    )
    completed = subprocess.run(
        [node, "-e", script, json.dumps(status)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    view = json.loads(completed.stdout)

    assert view["cancelled"] == 2
    assert view["processed"] == 2
    assert view["remaining"] == 1
    assert view["isDone"] is False
    assert view["severity"] == "info"
    assert "2/3 offers terminal" in view["message"]


def test_cancel_all_progress_modal_describes_native_bulk_sage_confirmation():
    """The GUI must set honest expectations for native Sage bulk cancellation."""

    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    modal_source = gui_source.split('id="cancelProgressModal"', 1)[1].split(
        "<!-- Boost Confirmation Modal -->", 1
    )[0]
    modal_text = " ".join(modal_source.lower().split())

    assert "one at a time" not in modal_text
    assert "waits for authoritative on-chain confirmation" in modal_text
    assert "single bulk transaction" in modal_text
    assert "well under a minute" not in modal_text


def test_cancel_all_deadline_bounds_bulk_proof_recording_without_multi_hour_wait():
    """One transaction still needs bounded per-member durable proof commits."""
    from blueprints import offers

    assert offers._cancel_all_deadline_seconds(1, 90) == 180.0
    assert offers._cancel_all_deadline_seconds(71, 90) == 880.0
    assert offers._cancel_all_deadline_seconds(500, 90) == 3_600.0
    assert offers._cancel_all_deadline_seconds(1, 240) == 480.0
    assert offers._cancel_all_deadline_seconds(22, 90, batch_count=6) == 1_290.0


def test_cancel_all_balances_fee_safe_batches_without_single_member_tail():
    from blueprints import offers

    trade_ids = [f"{index:064x}" for index in range(22)]

    batches = offers._balanced_cancel_batches(trade_ids, 4)

    assert [len(batch) for batch in batches] == [4, 4, 4, 4, 3, 3]
    assert [trade_id for batch in batches for trade_id in batch] == trade_ids
    assert [
        len(batch) for batch in offers._balanced_cancel_batches(trade_ids[:10], 4)
    ] == [4, 3, 3]
    assert [
        len(batch) for batch in offers._balanced_cancel_batches(trade_ids[:5], 4)
    ] == [3, 2]


def test_cancel_all_gui_timeout_honours_backend_authoritative_deadline():
    """The UI must not call a healthy long-running cancel failed after five minutes."""

    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the bounded GUI consumer test")
    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    helper_source = (
        "function cancelAllClientTimeoutMs"
        + gui_source.split("function cancelAllClientTimeoutMs", 1)[1].split(
            "async function confirmCancelAll", 1
        )[0]
    )
    script = helper_source + "\nconsole.log(cancelAllClientTimeoutMs(8280));"
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert int(completed.stdout.strip()) >= 8_310_000
    confirm_source = gui_source.split("async function confirmCancelAll()", 1)[1]
    confirm_source = confirm_source.split(
        "// Local helper: read cached cancel-all state", 1
    )[0]
    assert "cancelAllClientTimeoutMs(result.timeout_seconds)" in confirm_source
    assert "}, 300000);" not in confirm_source


def test_shutdown_offer_disposition_qualifies_catalyst_tracked_visibility():
    """Tracked rows must not be presented as an authoritative wallet snapshot."""

    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the shutdown UI test")
    gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
    helper_source = (
        "function shutdownOfferDisposition"
        + gui_source.split("function shutdownOfferDisposition", 1)[1].split(
            "async function confirmShutdown", 1
        )[0]
    )
    script = (
        helper_source
        + "\nconsole.log(JSON.stringify([shutdownOfferDisposition({offers:{buy:[],sell:[]}}), shutdownOfferDisposition({offers:{buy:[{}],sell:[{},{}]}}), shutdownOfferDisposition({offers:{buy:[{}],sell:[{},{}]}}, {total:3,cancelled:3,confirmed:3,pending:0,failed:0})]));"
    )
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    empty, active, terminal_after_stale_view = json.loads(completed.stdout)

    assert empty["count"] == 0
    assert empty["copy"] == (
        "CATalyst shows no tracked open offers. "
        "Untracked wallet offers, if any, will remain active."
    )
    assert active["count"] == 3
    assert active["copy"] == (
        "3 CATalyst-tracked open offers will remain active. "
        "Untracked wallet offers, if any, will also remain active."
    )
    assert terminal_after_stale_view["count"] == 0
    assert terminal_after_stale_view["copy"] == (
        "CATalyst shows no tracked open offers. "
        "Untracked wallet offers, if any, will remain active."
    )


# ---------------------------------------------------------------------------
# 1. GET /api/offers
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestOffersGet(_FlaskBase):
    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._get("/api/offers", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 500)

    def test_bot_set_returns_200(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._get("/api/offers", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_response_has_buys_sells_counts(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._get("/api/offers", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("buys", body)
        self.assertIn("sells", body)
        self.assertIn("buy_count", body)
        self.assertIn("sell_count", body)

    def test_empty_offers_returns_zero_counts(self):
        with patch.object(api_server, "bot", _make_bot(offers=([], [], []))):
            resp = self._get("/api/offers", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertEqual(body["buy_count"], 0)
        self.assertEqual(body["sell_count"], 0)

    def test_cached_empty_wallet_book_is_not_reported_as_current(self):
        bot = _make_bot(offers=([], [], []))
        bot.offer_manager.sync_from_wallet_with_meta.side_effect = lambda: (
            ([], [], []),
            {"fresh": False, "using_cache": False},
        )
        with patch.object(api_server, "bot", bot):
            resp = self._get("/api/offers", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json()["error"], "wallet_offer_sync_stale")


# ---------------------------------------------------------------------------
# 2. GET /api/offers/cancel_all/status
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCancelAllStatus(_FlaskBase):
    def test_returns_200_always(self):
        resp = self._get("/api/offers/cancel_all/status", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_response_has_success_key(self):
        resp = self._get("/api/offers/cancel_all/status", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertTrue(body.get("success"))


# ---------------------------------------------------------------------------
# 3. GET /api/offers/open_count
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestOpenOfferCount(_FlaskBase):
    """Stub database.get_open_offers to a clean empty list so the route's
    real DB fetch doesn't intermittently fail under parallel xdist
    workers competing for the same sqlite write-lock."""

    def setUp(self):
        super().setUp()
        import database

        self._orig_get_open_offers = database.get_open_offers
        database.get_open_offers = lambda *a, **kw: []

    def tearDown(self):
        import database

        database.get_open_offers = self._orig_get_open_offers
        super().tearDown()

    def test_returns_200(self):
        resp = self._get("/api/offers/open_count", environ_base=self._LOOPBACK)
        self.assertEqual(resp.status_code, 200)

    def test_response_has_open_count(self):
        resp = self._get("/api/offers/open_count", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertIn("open_count", body)
        self.assertIsInstance(body["open_count"], int)

    def test_success_key_true_on_success(self):
        resp = self._get("/api/offers/open_count", environ_base=self._LOOPBACK)
        body = resp.get_json()
        self.assertTrue(body.get("success"))


# ---------------------------------------------------------------------------
# 4. POST /api/offers/cancel
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCancelOffer(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/offers/cancel", {"trade_id": "abc123"}, auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._post("/api/offers/cancel", {"trade_id": "abc123"})
        self.assertEqual(resp.status_code, 500)

    def test_invalid_body_returns_400(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self.client.post(
                "/api/offers/cancel",
                data="not json",
                content_type="text/plain",
                headers=self.auth,
                environ_base=self._LOOPBACK,
            )
        self.assertEqual(resp.status_code, 400)

    def test_missing_trade_id_returns_400(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._post("/api/offers/cancel", {})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_empty_trade_id_returns_400(self):
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._post("/api/offers/cancel", {"trade_id": ""})
        self.assertEqual(resp.status_code, 400)

    def test_legacy_truthy_cancel_is_denied_without_typed_outcome(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {"success": True}
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body.get("success"))

    def test_cancel_response_has_trade_id(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {"success": True}
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})
        body = resp.get_json()
        self.assertEqual(body.get("trade_id"), "trade-abc-001")

    def test_submitted_cancel_is_reported_pending_not_cancelled(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
            }
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 202)
        self.assertEqual(
            resp.get_json(),
            {
                "success": True,
                "status": "pending_reconciliation",
                "confirmed": False,
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "trade_id": "trade-abc-001",
            },
        )

    def test_missing_requested_trade_result_fails_closed(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "different-trade": {"success": True}
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "trade_id": "trade-abc-001",
                "error": "Offer cancellation failed",
                "reason": "WALLET_MUTATION_FAILED",
            },
        )

    def test_malformed_requested_trade_result_fails_closed(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {"trade-abc-001": ["hostile"]}
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "trade_id": "trade-abc-001",
                "error": "Offer cancellation failed",
                "reason": "WALLET_MUTATION_FAILED",
            },
        )

    def test_cancel_result_error_returns_400(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {"error": "storm_protection"}
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})
        self.assertEqual(resp.status_code, 400)

    def test_identity_denial_is_not_reported_as_cancelled(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {
                "success": False,
                "error": "Wallet mutation blocked by identity safety check",
                "reason": "WALLET_IDENTITY_MISMATCH",
            }
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "trade_id": "trade-abc-001",
                "error": "Wallet mutation blocked by identity safety check",
                "reason": "WALLET_IDENTITY_MISMATCH",
            },
        )

    def test_cancel_denial_does_not_echo_hostile_wallet_reason_or_error(self):
        bot = _make_bot()
        bot.offer_manager.cancel_offers.return_value = {
            "trade-abc-001": {
                "success": False,
                "error": "secret backend traceback",
                "reason": "WALLET_HOSTILE_REASON",
            }
        }
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/offers/cancel", {"trade_id": "trade-abc-001"})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "trade_id": "trade-abc-001",
                "error": "Offer cancellation failed",
                "reason": "WALLET_MUTATION_FAILED",
            },
        )


# ---------------------------------------------------------------------------
# 5. POST /api/offers/cancel_all
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestCancelAllPost(_FlaskBase):
    def setUp(self):
        super().setUp()
        import wallet

        history_patch = patch(
            "wallet.get_authoritative_offer_history",
            side_effect=lambda **kwargs: wallet.get_all_offers(**kwargs),
        )
        history_patch.start()
        self.addCleanup(history_patch.stop)
        intent_patch = patch("database.get_offer_intent_by_trade_id", return_value=None)
        intent_patch.start()
        self.addCleanup(intent_patch.stop)

    def test_coin_prep_cancel_requires_exact_approval_shape(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        with patch.object(api_server, "bot", stopped):
            missing = self._post("/api/offers/cancel_all", {"source": "coin_prep"})
            malformed = self._post(
                "/api/offers/cancel_all",
                {"source": "coin_prep", "fee_approval_id": "not-a-digest"},
            )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        stopped.offer_manager.cancel_offers.assert_not_called()

    def test_unresolved_cancel_all_runs_proof_only_reconciliation(self):
        """The recovery button must remain useful without authorizing a second spend."""

        stopped = _make_bot()
        stopped.is_running.return_value = False
        states = iter(
            [
                types.SimpleNamespace(
                    allowed=False,
                    reason_code="UNRESOLVED_OPERATIONS",
                    blocking_operation_ids=("cancel:" + "a" * 64,),
                ),
                types.SimpleNamespace(
                    allowed=False,
                    reason_code="UNRESOLVED_OPERATIONS",
                    blocking_operation_ids=("cancel:" + "a" * 64,),
                ),
            ]
        )

        def run_now(*, target, **_kwargs):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch.object(
                api_server.mutation_gate,
                "read_only_status",
                side_effect=lambda: next(states),
            ),
            patch("threading.Thread") as thread_cls,
        ):
            thread_cls.return_value.start.side_effect = lambda: run_now(
                target=thread_cls.call_args.kwargs["target"]
            )
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertTrue(payload["reconciliation_only"])
        self.assertEqual(payload["reason"], "UNRESOLVED_OPERATIONS")
        stopped.offer_manager.reconcile_submitted_cancels_only.assert_called_once_with()
        stopped.offer_manager.cancel_offers.assert_not_called()

    def test_explicit_proof_only_reconciles_exact_latch_without_wallet_cancel(self):
        """A native proof click binds the observed generation and blockers."""
        stopped = _make_bot()
        stopped.is_running.return_value = False
        operation_id = "cancel:" + "a" * 64
        blocked = types.SimpleNamespace(
            allowed=False,
            reason_code="UNRESOLVED_OPERATIONS",
            blocking_operation_ids=(operation_id,),
        )
        cleared = types.SimpleNamespace(allowed=True, reason_code="")
        states = iter((blocked, blocked, cleared))

        with (
            patch.object(api_server, "bot", stopped),
            patch.object(
                api_server.mutation_gate,
                "read_only_status",
                side_effect=lambda: next(states),
            ),
            patch(
                "database.get_runtime_safety_latch", return_value={"generation": 155}
            ),
            patch("threading.Thread") as thread_cls,
        ):
            thread_cls.return_value.start.side_effect = lambda: (
                thread_cls.call_args.kwargs["target"]()
            )
            response = self._post(
                "/api/offers/cancel_all",
                {
                    "reconciliation_only": True,
                    "expected_latch_generation": 155,
                    "expected_operation_ids": [operation_id],
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.get_json()["reconciliation_only"])
        stopped.offer_manager.reconcile_submitted_cancels_only.assert_called_once_with()
        stopped.offer_manager.cancel_offers.assert_not_called()

    def test_explicit_proof_only_refuses_cleared_gate_and_stale_generation(self):
        """A raced or stale review cannot fall through to broad cancellation."""
        stopped = _make_bot()
        stopped.is_running.return_value = False
        operation_id = "cancel:" + "a" * 64
        request = {
            "reconciliation_only": True,
            "expected_latch_generation": 155,
            "expected_operation_ids": [operation_id],
        }
        with (
            patch.object(api_server, "bot", stopped),
            patch.object(
                api_server.mutation_gate,
                "read_only_status",
                return_value=types.SimpleNamespace(allowed=True, reason_code=""),
            ),
        ):
            cleared = self._post("/api/offers/cancel_all", request)
        with (
            patch.object(api_server, "bot", stopped),
            patch.object(
                api_server.mutation_gate,
                "read_only_status",
                return_value=types.SimpleNamespace(
                    allowed=False,
                    reason_code="UNRESOLVED_OPERATIONS",
                    blocking_operation_ids=(operation_id,),
                ),
            ),
            patch(
                "database.get_runtime_safety_latch", return_value={"generation": 156}
            ),
        ):
            stale = self._post("/api/offers/cancel_all", request)
        self.assertEqual(cleared.status_code, 409)
        self.assertEqual(stale.status_code, 409)
        stopped.offer_manager.cancel_offers.assert_not_called()
        stopped.offer_manager.reconcile_submitted_cancels_only.assert_not_called()

    def test_explicit_proof_only_worker_refuses_latch_drift(self):
        """An accepted click cannot reconcile a different latch after threading."""
        from blueprints.offers import _get_cancel_all_state

        stopped = _make_bot()
        stopped.is_running.return_value = False
        operation_id = "cancel:" + "a" * 64
        blocked = types.SimpleNamespace(
            allowed=False,
            reason_code="UNRESOLVED_OPERATIONS",
            blocking_operation_ids=(operation_id,),
        )
        states = iter((blocked, blocked))
        latches = iter(({"generation": 155}, {"generation": 156}))
        with (
            patch.object(api_server, "bot", stopped),
            patch.object(
                api_server.mutation_gate,
                "read_only_status",
                side_effect=lambda: next(states),
            ),
            patch(
                "database.get_runtime_safety_latch", side_effect=lambda: next(latches)
            ),
            patch("threading.Thread") as thread_cls,
        ):
            thread_cls.return_value.start.side_effect = lambda: (
                thread_cls.call_args.kwargs["target"]()
            )
            response = self._post(
                "/api/offers/cancel_all",
                {
                    "reconciliation_only": True,
                    "expected_latch_generation": 155,
                    "expected_operation_ids": [operation_id],
                },
            )
        self.assertEqual(response.status_code, 202)
        stopped.offer_manager.reconcile_submitted_cancels_only.assert_not_called()
        stopped.offer_manager.cancel_offers.assert_not_called()
        self.assertEqual(_get_cancel_all_state()["error"], "proof_scope_changed")

    def test_unresolved_cancel_all_proof_exception_finishes_with_error(self):
        """A failed proof read must not leave the progress indicator running forever."""
        from blueprints.offers import _reset_cancel_all_state

        stopped = _make_bot()
        stopped.is_running.return_value = False
        stopped.offer_manager.reconcile_submitted_cancels_only.side_effect = (
            RuntimeError("proof read failed")
        )
        blocked = types.SimpleNamespace(
            allowed=False,
            reason_code="UNRESOLVED_OPERATIONS",
            blocking_operation_ids=("cancel:" + "a" * 64,),
        )

        def run_now(*, target):
            try:
                target()
            except RuntimeError:
                pass  # A real Thread records the exception and keeps running the app.

        _reset_cancel_all_state()
        try:
            with (
                patch.object(api_server, "bot", stopped),
                patch.object(
                    api_server.mutation_gate,
                    "read_only_status",
                    return_value=blocked,
                ),
                patch("threading.Thread") as thread_cls,
            ):
                thread_cls.return_value.start.side_effect = lambda: run_now(
                    target=thread_cls.call_args.kwargs["target"]
                )
                response = self._post("/api/offers/cancel_all")
                status = self._get("/api/offers/cancel_all/status").get_json()

            self.assertEqual(response.status_code, 202)
            self.assertFalse(status["running"])
            self.assertFalse(status["complete"])
            self.assertEqual(status["error"], "cancel_proof_reconciliation_failed")
            stopped.offer_manager.cancel_offers.assert_not_called()
        finally:
            _reset_cancel_all_state()

    def test_requires_token(self):
        resp = self._post("/api/offers/cancel_all", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_bot_none_uses_direct_wallet_path(self):
        # bot=None → direct wallet RPC path; no open offers → 200 success
        with (
            patch.object(api_server, "bot", None),
            patch("wallet.get_all_offers", return_value=[]),
            patch("wallet.cancel_offers_batch", return_value={}),
            patch("wallet.is_offer_time_expired", return_value=False),
        ):
            resp = self._post("/api/offers/cancel_all")
        self.assertEqual(resp.status_code, 200)

    def test_bot_running_returns_409(self):
        # Running bot must be stopped before cancel_all is allowed
        with patch.object(api_server, "bot", _make_bot()):
            resp = self._post("/api/offers/cancel_all")
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.get_json().get("success"))

    def test_bot_stopped_cancel_all_returns_success(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        with (
            patch.object(api_server, "bot", stopped),
            patch("wallet.get_all_offers", return_value=[]),
            patch("wallet.cancel_offers_batch", return_value={}),
            patch("wallet.is_offer_time_expired", return_value=False),
        ):
            resp = self._post("/api/offers/cancel_all")
        self.assertIn(resp.status_code, (200, 202))

    def test_stopped_cancel_all_exposes_structured_fee_budget_failure(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        approval_id = "b" * 64
        stopped.offer_manager.cancel_offers.side_effect = ValueError(
            "FEE_CAMPAIGN_BUDGET_EXCEEDED"
        )

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch(
                "database.get_offer_intent_by_trade_id",
                return_value={"purpose": f"bootstrap:{'c' * 64}:revision:1"},
            ),
            patch("wallet.is_offer_time_expired", return_value=False),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post(
                "/api/offers/cancel_all",
                {"source": "coin_prep", "fee_approval_id": approval_id},
            )

        self.assertEqual(response.status_code, 200)
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["phase"], "error")
        self.assertEqual(status["reason_code"], "FEE_CAMPAIGN_BUDGET_EXCEEDED")

    def test_stopped_cancel_all_exposes_fee_funding_failure_for_native_review(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        stopped.offer_manager.cancel_offers.side_effect = ValueError(
            "FEE_PREP_FUNDING_INSUFFICIENT"
        )

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch(
                "database.get_offer_intent_by_trade_id",
                return_value={"purpose": f"bootstrap:{'c' * 64}:revision:1"},
            ),
            patch("wallet.is_offer_time_expired", return_value=False),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["phase"], "error")
        self.assertEqual(status["reason_code"], "FEE_PREP_FUNDING_INSUFFICIENT")

    def test_stopped_cancel_all_exposes_stale_fee_approval_for_recovery(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        stopped.offer_manager.cancel_offers.side_effect = ValueError(
            "FEE_APPROVAL_STALE"
        )

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch("wallet.is_offer_time_expired", return_value=False),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["phase"], "error")
        self.assertEqual(status["reason_code"], "FEE_APPROVAL_STALE")

    def test_stopped_cancel_all_reports_pre_effect_fee_failure_immediately(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_FAILED",
                "success": False,
                "submitted": False,
                "reconciliation_required": False,
                "error": "FEE_CANCELLATION_FUNDING_REQUIRED",
            }
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        stopped.offer_manager.retry_failed_cancels.assert_not_called()
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["phase"], "error")
        self.assertEqual(status["reason_code"], "FEE_CANCELLATION_FUNDING_REQUIRED")
        self.assertFalse(status["running"])
        self.assertFalse(status["complete"])

    def test_stopped_bot_routes_active_offer_through_durable_manager(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
                "submitted": True,
                "confirmed": False,
                "failed": False,
                "unknown": False,
                "method": "single_rpc",
                "transaction_id": "b" * 64,
                "spend_bundle_id": None,
                "error": None,
                "http_status": None,
                "raw_response": {"transaction_id": "b" * 64},
                "evidence_sha256": "c" * 64,
            }
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                side_effect=lambda **_bounds: (
                    []
                    if stopped.offer_manager.cancel_offers.call_count
                    else [{"trade_id": trade_id, "status": "ACTIVE"}]
                ),
            ),
            patch("wallet.cancel_offers_batch") as direct_batch,
            patch("wallet.is_offer_time_expired", return_value=False),
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {
                        "intent_id": "intent-a",
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.get_json(),
            {
                "success": True,
                "async": True,
                "total": 1,
                "timeout_seconds": 180.0,
                "message": "Cancelling 1 offers in background...",
            },
        )
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [trade_id], reason="manual_cancel_all", force_storm=True
        )
        stopped.coin_manager.refresh_fee_pool_from_wallet.assert_called_once_with()
        direct_batch.assert_not_called()

        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(
            {
                key: status[key]
                for key in (
                    "success",
                    "running",
                    "complete",
                    "phase",
                    "total",
                    "cancelled",
                    "pending",
                    "failed",
                )
            },
            {
                "success": True,
                "running": False,
                "complete": True,
                "phase": "complete",
                "total": 1,
                "cancelled": 1,
                "pending": 0,
                "failed": 0,
            },
        )

    def test_stopped_cancel_all_waits_for_authoritative_terminal_reconciliation(self):
        """Shutdown must not finish after one submitted cancel aborts its peers."""
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = ["a" * 64, "b" * 64]
        stopped.offer_manager.cancel_offers.return_value = {
            trade_ids[0]: {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
            },
            trade_ids[1]: {
                "outcome": "CANCEL_FAILED",
                "success": False,
            },
        }
        reconciled = {"done": False}

        def finish_retries(_batch):
            reconciled["done"] = True
            return 0

        stopped.offer_manager.retry_failed_cancels.side_effect = finish_retries

        def terminal_record(trade_id):
            if not reconciled["done"]:
                return None
            return {
                "intent_id": f"intent:{trade_id}",
                "sage_trade_id": trade_id,
                "outcome": "CANCELLED_PROVEN",
            }

        def terminal_records(candidates):
            return {
                candidate: record
                for candidate in candidates
                if (record := terminal_record(candidate)) is not None
            }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                side_effect=lambda **_bounds: (
                    []
                    if reconciled["done"]
                    else [
                        {"trade_id": trade_id, "status": "ACTIVE"}
                        for trade_id in trade_ids
                    ]
                ),
            ),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        stopped.offer_manager.retry_failed_cancels.assert_called_once_with(trade_ids)
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(
            {
                key: status[key]
                for key in (
                    "running",
                    "complete",
                    "phase",
                    "total",
                    "cancelled",
                    "pending",
                    "failed",
                )
            },
            {
                "running": False,
                "complete": True,
                "phase": "complete",
                "total": 2,
                "cancelled": 2,
                "pending": 0,
                "failed": 0,
            },
        )

    def test_stopped_cancel_all_refreshes_wallet_snapshot_after_completion(self):
        """A proven Cancel All must replace the stopped UI's stale offer cache."""

        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                side_effect=lambda **_bounds: (
                    []
                    if stopped.offer_manager.cancel_offers.call_count
                    else [{"trade_id": trade_id, "status": "ACTIVE"}]
                ),
            ),
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        stopped.offer_manager.expect_empty_wallet_offer_book.assert_called_once_with(
            "manual_cancel_all_confirmed"
        )
        stopped.offer_manager.sync_from_wallet.assert_called_once_with()

    def test_cancel_all_does_not_complete_when_new_wallet_offer_appears(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        initial_id = "a" * 64
        late_id = "b" * 64

        def read_page(**_bounds):
            trade_id = (
                late_id
                if stopped.offer_manager.cancel_offers.call_count
                else initial_id
            )
            return {
                "success": True,
                "offers": [{"trade_id": trade_id, "status": "ACTIVE"}],
                "end_of_history": True,
            }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch("wallet.get_authoritative_offer_history", side_effect=read_page),
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    initial_id: {
                        "sage_trade_id": initial_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            self._post("/api/offers/cancel_all")

        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertFalse(status["complete"])
        self.assertEqual(status["phase"], "error")
        stopped.offer_manager.expect_empty_wallet_offer_book.assert_not_called()

    def test_cancel_all_does_not_complete_when_final_wallet_read_fails(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64

        def read_page(**_bounds):
            if stopped.offer_manager.cancel_offers.call_count:
                return {"success": False, "offers": [], "end_of_history": False}
            return {
                "success": True,
                "offers": [{"trade_id": trade_id, "status": "ACTIVE"}],
                "end_of_history": True,
            }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch("wallet.get_authoritative_offer_history", side_effect=read_page),
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {"sage_trade_id": trade_id, "outcome": "CANCELLED_PROVEN"}
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            self._post("/api/offers/cancel_all")

        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertFalse(status["complete"])
        self.assertEqual(status["phase"], "error")
        stopped.offer_manager.expect_empty_wallet_offer_book.assert_not_called()

    def test_cancel_all_completed_at_deadline_is_not_reported_as_zero_pending_error(
        self,
    ):
        """Final terminal proof wins even when it arrives on the deadline boundary."""
        from blueprints import offers

        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        reconciled = {"done": False}

        def finish_retries(_batch):
            reconciled["done"] = True
            return 0

        stopped.offer_manager.retry_failed_cancels.side_effect = finish_retries

        def terminal_record(candidate):
            if not reconciled["done"]:
                return None
            return {
                "intent_id": f"intent:{candidate}",
                "sage_trade_id": candidate,
                "outcome": "CANCELLED_PROVEN",
            }

        def terminal_records(candidates):
            return {
                candidate: record
                for candidate in candidates
                if (record := terminal_record(candidate)) is not None
            }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                side_effect=lambda **_bounds: (
                    []
                    if reconciled["done"]
                    else [{"trade_id": trade_id, "status": "ACTIVE"}]
                ),
            ),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(offers, "_cancel_all_deadline_seconds", return_value=0.0),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["phase"], "complete")
        self.assertTrue(status["complete"])
        self.assertFalse(status["running"])
        self.assertIsNone(status["error"])
        self.assertEqual(status["cancelled"], 1)
        self.assertEqual(status["pending"], 0)
        self.assertEqual(status["failed"], 0)

    def test_cancel_all_status_reads_terminal_proof_in_one_batch(self):
        """Large native Sage batches must not issue one DB query per member."""
        from blueprints import offers

        trade_ids = ["a" * 64, "b" * 64, "c" * 64]
        calls = []

        def batch_records(candidates):
            calls.append(list(candidates))
            return {
                trade_ids[0]: {
                    "sage_trade_id": trade_ids[0],
                    "outcome": "CANCELLED_PROVEN",
                },
                trade_ids[1]: {
                    "sage_trade_id": trade_ids[1],
                    "outcome": "ACTIVE_PROVEN",
                },
                trade_ids[2]: {
                    "sage_trade_id": "d" * 64,
                    "outcome": "EXPIRED_PROVEN",
                },
            }

        with (
            patch.object(
                offers.database,
                "get_authoritative_terminal_records",
                side_effect=batch_records,
                create=True,
            ),
            patch.object(
                offers.database,
                "get_authoritative_terminal_record",
                side_effect=AssertionError("serial terminal lookup is forbidden"),
            ),
        ):
            terminal = offers._authoritatively_terminal_offer_ids(trade_ids)

        self.assertEqual(terminal, {trade_ids[0]})
        self.assertEqual(calls, [trade_ids])

    def test_cancel_all_status_advances_while_serial_retry_is_in_flight(self):
        """Polling must see exact durable proof before a slow retry batch returns."""
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = ["a" * 64, "b" * 64, "c" * 64]
        records = {}
        snapshots = []

        def poll():
            snapshots.append(
                self._get(
                    "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
                ).get_json()
            )

        def terminal_records(candidates):
            return {
                candidate: records[candidate]
                for candidate in candidates
                if candidate in records
            }

        def finish_retries(_batch):
            # One exact proof, one mismatched proof and one mere submission.
            records.update(
                {
                    trade_ids[0]: {
                        "sage_trade_id": trade_ids[0],
                        "outcome": "CANCELLED_PROVEN",
                    },
                    trade_ids[1]: {
                        "sage_trade_id": "d" * 64,
                        "outcome": "CANCELLED_PROVEN",
                    },
                    trade_ids[2]: {
                        "sage_trade_id": trade_ids[2],
                        "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                    },
                }
            )
            poll()
            records[trade_ids[1]] = {
                "sage_trade_id": trade_ids[1],
                "outcome": "EXPIRED_PROVEN",
            }
            poll()
            records[trade_ids[2]] = {
                "sage_trade_id": trade_ids[2],
                "outcome": "CANCELLED_PROVEN",
            }
            poll()
            return 0

        def run_now(*, operation, target, name):
            target()
            return object()

        stopped.offer_manager.retry_failed_cancels.side_effect = finish_retries
        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                side_effect=lambda **_bounds: (
                    []
                    if len(records) == len(trade_ids)
                    and all(
                        records[trade_id]["sage_trade_id"] == trade_id
                        and records[trade_id]["outcome"]
                        in {"CANCELLED_PROVEN", "EXPIRED_PROVEN"}
                        for trade_id in trade_ids
                    )
                    else [
                        {"trade_id": trade_id, "status": "ACTIVE"}
                        for trade_id in trade_ids
                    ]
                ),
            ),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(s["cancelled"], s.get("confirmed"), s["pending"]) for s in snapshots],
            [(1, 1, 2), (2, 2, 1), (3, 3, 0)],
        )
        for snapshot in snapshots:
            self.assertTrue(snapshot["running"])
            self.assertFalse(snapshot["complete"])
            self.assertEqual(snapshot["total"], 3)
            self.assertEqual(snapshot["phase"], "reconciling")
            self.assertIn(
                f"{snapshot['confirmed']}/3 offers terminal", snapshot["message"]
            )
            self.assertNotIn("_target_trade_ids", snapshot)
        # Only the worker may declare completion, after the retry call returns.
        final = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertTrue(final["complete"])
        self.assertFalse(final["running"])
        stopped.offer_manager.retry_failed_cancels.assert_called_once_with(trade_ids)

    def test_stopped_cancel_all_retries_exact_durable_failed_attempt(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_id = "a" * 64
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_UNKNOWN",
                "success": False,
                "submitted": False,
                "reconciliation_required": True,
            }
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch(
                "database.get_retryable_failed_offer_cancels",
                return_value=[
                    {
                        "trade_id": trade_id,
                        "operation_id": f"cancel:{trade_id}",
                        "attempt": 1,
                    }
                ],
            ),
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {
                        "intent_id": "intent-a",
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [trade_id],
            reason="manual_cancel_all",
            force_storm=True,
            _retry_failed_attempts={trade_id: 1},
        )

        gui_source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")
        status_consumer = gui_source.split(
            "async function pollShutdownCancelAllStatusOnce()", 1
        )[1].split("function startShutdownCancelAllPoll()", 1)[0]
        assert "const cancelled = Number(state.cancelled || 0);" in status_consumer
        assert "const pending = Number(state.pending || 0);" in status_consumer
        assert "authoritatively terminal" in status_consumer
        shutdown_source = gui_source.split("async function confirmShutdown()", 1)[1]
        shutdown_source = shutdown_source.split("// Wallet Picker Modal", 1)[0]
        assert "cancelResult.async === true" in shutdown_source
        assert "cancelResult.total" in shutdown_source
        assert "cancelResult.timeout_seconds" in shutdown_source
        assert "await waitForShutdownCancelAllCompletion" in shutdown_source
        cancel_response_window = shutdown_source.split(
            "const cancelResult = await requestShutdownCancelAllAfterStop();", 1
        )[1].split("const isAsyncCancel = cancelResult.async === true;", 1)[0]
        assert "stopShutdownCancelAllPoll();" not in cancel_response_window
        assert "cancelled + pending + failed !== count" in shutdown_source
        assert "cancelled !== count" in shutdown_source
        assert "throw e;" in shutdown_source
        assert "/offers/open_count" not in shutdown_source
        assert "authoritatively terminal" in shutdown_source

    def test_stopped_cancel_all_submits_500_offers_in_one_authority_envelope(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = [f"{index:064x}" for index in range(1, 501)]
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
            }
            for trade_id in trade_ids
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        def read_page(*, include_completed, start=0, end=50):
            if stopped.offer_manager.cancel_offers.call_count:
                return []
            return [
                {"trade_id": trade_id, "status": "ACTIVE"}
                for trade_id in trade_ids[start:end]
            ]

        with (
            patch.object(api_server, "bot", stopped),
            patch("wallet.get_all_offers", side_effect=read_page),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=lambda candidates: {
                    trade_id: {
                        "intent_id": f"intent:{trade_id}",
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                    for trade_id in candidates
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 200)
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            trade_ids,
            reason="manual_cancel_all",
            force_storm=True,
        )
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["total"], 500)
        self.assertEqual(status["batch_size"], 500)
        self.assertEqual(status["total_batches"], 1)
        self.assertEqual(status["cancelled"], 500)
        self.assertEqual(status["pending"], 0)
        self.assertEqual(status["failed"], 0)

    def test_stopped_cancel_all_finds_active_offer_after_full_terminal_page(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        active_id = "f" * 64
        history = [
            {"trade_id": f"{index:064x}", "status": "CANCELLED"}
            for index in range(1, 501)
        ] + [{"trade_id": active_id, "status": "ACTIVE"}]
        stopped.offer_manager.cancel_offers.return_value = {
            active_id: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED", "success": True}
        }

        def read_page(*, include_completed, start=0, end=50):
            # A wallet may honor pagination while ignoring include_completed.
            return history[start:end]

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch("wallet.get_all_offers", side_effect=read_page),
            patch("wallet.get_authoritative_offer_history", side_effect=read_page),
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    active_id: {
                        "sage_trade_id": active_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [active_id], reason="manual_cancel_all", force_storm=True
        )

    def test_stopped_cancel_all_rejects_failed_authoritative_history_read(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": False,
                    "offers": [],
                    "end_of_history": False,
                },
            ),
            patch("wallet.get_all_offers", return_value=[]),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 503)
        stopped.offer_manager.cancel_offers.assert_not_called()

    def test_stopped_cancel_all_does_not_claim_empty_for_pending_cancel(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [{"trade_id": "a" * 64, "status": "PENDING_CANCEL"}],
                    "end_of_history": True,
                },
            ),
            patch("wallet.get_all_offers", return_value=[]),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 503)
        stopped.offer_manager.cancel_offers.assert_not_called()

    def test_stopped_cancel_all_rejects_repeated_unbounded_page(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        page = [
            {"trade_id": f"{index:064x}", "status": "ACTIVE"} for index in range(1, 501)
        ]
        with (
            patch.object(api_server, "bot", stopped),
            patch("wallet.get_authoritative_offer_history", return_value=page),
            patch("wallet.get_all_offers", return_value=page),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 503)
        stopped.offer_manager.cancel_offers.assert_not_called()

    def test_stopped_cancel_all_sequences_balanced_fee_safe_sage_batches(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        stopped.offer_manager.get_sage_bulk_cancel_capacity.return_value = 4
        trade_ids = [f"{index:064x}" for index in range(1, 11)]
        terminal_ids = set()
        submitted_batches = []

        def cancel_batch(batch, **_kwargs):
            submitted_batches.append(list(batch))
            terminal_ids.update(batch)
            return {
                trade_id: {
                    "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                    "success": True,
                }
                for trade_id in batch
            }

        stopped.offer_manager.cancel_offers.side_effect = cancel_batch

        def terminal_records(candidates):
            return {
                trade_id: {
                    "intent_id": f"intent:{trade_id}",
                    "sage_trade_id": trade_id,
                    "outcome": "CANCELLED_PROVEN",
                }
                for trade_id in candidates
                if trade_id in terminal_ids
            }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                side_effect=lambda **_bounds: [
                    {"trade_id": trade_id, "status": "ACTIVE"}
                    for trade_id in trade_ids
                    if trade_id not in terminal_ids
                ],
            ),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([len(batch) for batch in submitted_batches], [4, 3, 3])
        self.assertEqual(
            [trade_id for batch in submitted_batches for trade_id in batch],
            trade_ids,
        )
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["batch_size"], 4)
        self.assertEqual(status["total_batches"], 3)
        self.assertEqual(status["current_batch"], 3)
        self.assertEqual(status["cancelled"], 10)

    def test_stopped_cancel_all_splits_exact_unsigned_over_block_book(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        stopped.offer_manager.get_sage_bulk_cancel_capacity.return_value = 48
        stopped.offer_manager.preview_follow_cancel_book.side_effect = (
            lambda cohorts, **_kwargs: {
                "cohorts": cohorts,
                "dispatch_authorized": False,
            }
        )
        trade_ids = [f"{index:064x}" for index in range(1, 49)]
        terminal_ids = set()
        submitted = []

        def cancel_batch(batch, **_kwargs):
            if len(batch) > 12:
                raise ValueError("FEE_CANCELLATION_BATCH_OVER_BLOCK_LIMIT")
            submitted.append(tuple(batch))
            terminal_ids.update(batch)
            return {
                trade_id: {"outcome": "CANCEL_SUBMITTED_UNCONFIRMED"}
                for trade_id in batch
            }

        stopped.offer_manager.cancel_offers.side_effect = cancel_batch

        def terminal_records(candidates):
            return {
                trade_id: {
                    "intent_id": f"intent:{trade_id}",
                    "sage_trade_id": trade_id,
                    "outcome": "CANCELLED_PROVEN",
                }
                for trade_id in candidates
                if trade_id in terminal_ids
            }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "offer_manager.OfferManager._cancel_fee_scope_groups",
                return_value=[
                    {
                        "trade_ids": trade_ids,
                        "campaign_id": None,
                        "follow_run_id": "a" * 64,
                    }
                ],
            ),
            patch(
                "wallet.get_all_offers",
                side_effect=lambda **_bounds: [
                    {"trade_id": trade_id, "status": "ACTIVE"}
                    for trade_id in trade_ids
                    if trade_id not in terminal_ids
                ],
            ),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch("database.get_unresolved_offer_operation_blockers", return_value=[]),
            patch(
                "database.get_follow_run_identity", return_value={"network": "mainnet"}
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([len(batch) for batch in submitted], [12, 12, 12, 12])
        self.assertEqual(
            set().union(*(set(batch) for batch in submitted)), set(trade_ids)
        )
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["batch_size"], 12)
        self.assertEqual(status["total_batches"], 4)
        self.assertEqual(status["cancelled"], 48)

    def test_stopped_cancel_all_does_not_split_non_follow_fee_scope(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        stopped.offer_manager.get_sage_bulk_cancel_capacity.return_value = 2
        trade_ids = ["1" * 64, "2" * 64]
        attempts = []

        def cancel_batch(batch, **_kwargs):
            attempts.append(tuple(batch))
            raise ValueError("FEE_CANCELLATION_BATCH_OVER_BLOCK_LIMIT")

        stopped.offer_manager.cancel_offers.side_effect = cancel_batch

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "offer_manager.OfferManager._cancel_fee_scope_groups",
                return_value=[{"trade_ids": trade_ids, "campaign_id": None}],
            ),
            patch(
                "wallet.get_all_offers",
                return_value=[
                    {"trade_id": trade_id, "status": "ACTIVE"} for trade_id in trade_ids
                ],
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(attempts, [tuple(trade_ids)])
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["phase"], "error")

    def test_stopped_follow_cancel_all_requires_aggregate_fee_preview(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        trade_ids = ["1" * 64, "2" * 64]
        stopped.offer_manager.get_sage_bulk_cancel_capacity.return_value = 2
        stopped.offer_manager.preview_follow_cancel_book.side_effect = ValueError(
            "FEE_BUDGET_EXCEEDED"
        )

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "offer_manager.OfferManager._cancel_fee_scope_groups",
                return_value=[
                    {
                        "trade_ids": trade_ids,
                        "campaign_id": None,
                        "follow_run_id": "a" * 64,
                    }
                ],
            ),
            patch(
                "database.get_follow_run_identity", return_value={"network": "mainnet"}
            ),
            patch(
                "wallet.get_all_offers",
                return_value=[
                    {"trade_id": trade_id, "status": "ACTIVE"} for trade_id in trade_ids
                ],
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        stopped.offer_manager.cancel_offers.assert_not_called()
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertEqual(status["phase"], "error")

    def test_stopped_cancel_all_separates_bootstrap_and_orphan_fee_scopes(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        bootstrap_id, orphan_id, campaign_id = "a" * 64, "b" * 64, "c" * 64
        terminal_ids = set()
        submitted = []

        def cancel_batch(trade_ids, **kwargs):
            submitted.append((tuple(trade_ids), kwargs))
            terminal_ids.update(trade_ids)
            return {trade_id: {"success": True} for trade_id in trade_ids}

        def terminal_records(candidates):
            return {
                trade_id: {
                    "intent_id": f"intent:{trade_id}",
                    "sage_trade_id": trade_id,
                    "outcome": "CANCELLED_PROVEN",
                }
                for trade_id in candidates
                if trade_id in terminal_ids
            }

        def run_now(*, operation, target, name):
            target()
            return object()

        stopped.offer_manager.cancel_offers.side_effect = cancel_batch
        rows = [
            {"trade_id": trade_id, "status": "ACTIVE"}
            for trade_id in (bootstrap_id, orphan_id)
        ]
        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": rows,
                    "total": 2,
                    "end_of_history": True,
                },
            ),
            patch(
                "database.get_offer_intent_by_trade_id",
                side_effect=lambda trade_id: (
                    {"purpose": f"bootstrap:{campaign_id}:revision:1"}
                    if trade_id == bootstrap_id
                    else None
                ),
            ),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item[0] for item in submitted], [(orphan_id,), (bootstrap_id,)]
        )
        self.assertEqual(submitted[0][1]["reason"], "manual_cancel_all")
        self.assertEqual(submitted[1][1]["reason"], "coin_prep_cancel_all")

    def test_stopped_cancel_all_rejects_one_approval_for_mixed_fee_scopes(self):
        stopped = _make_bot()
        stopped.is_running.return_value = False
        bootstrap_id, orphan_id, campaign_id = "a" * 64, "b" * 64, "c" * 64
        rows = [
            {"trade_id": trade_id, "status": "ACTIVE"}
            for trade_id in (bootstrap_id, orphan_id)
        ]
        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": rows,
                    "total": 2,
                    "end_of_history": True,
                },
            ),
            patch(
                "database.get_offer_intent_by_trade_id",
                side_effect=lambda trade_id: (
                    {"purpose": f"bootstrap:{campaign_id}:revision:1"}
                    if trade_id == bootstrap_id
                    else None
                ),
            ),
        ):
            response = self._post(
                "/api/offers/cancel_all",
                {"source": "coin_prep", "fee_approval_id": "d" * 64},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["reason"], "FEE_CANCELLATION_SCOPE_INVALID"
        )
        stopped.offer_manager.cancel_offers.assert_not_called()

    def test_stopped_cancel_all_retries_only_the_current_fee_safe_batch(self):
        """An older failed cancel outside the batch must never steal its retry slot."""

        stopped = _make_bot()
        stopped.is_running.return_value = False
        stopped.offer_manager.get_sage_bulk_cancel_capacity.return_value = 2
        trade_ids = [f"{index:064x}" for index in range(1, 5)]
        terminal_ids = set()
        retried_batches = []

        stopped.offer_manager.cancel_offers.side_effect = lambda batch, **_kwargs: {
            trade_id: {
                "outcome": "CANCEL_SUBMITTED_UNCONFIRMED",
                "success": True,
            }
            for trade_id in batch
        }

        def retry_current_batch(batch):
            retried_batches.append(list(batch))
            terminal_ids.update(batch)
            return 0

        stopped.offer_manager.retry_failed_cancels.side_effect = retry_current_batch

        def terminal_records(candidates):
            return {
                trade_id: {
                    "intent_id": f"intent:{trade_id}",
                    "sage_trade_id": trade_id,
                    "outcome": "CANCELLED_PROVEN",
                }
                for trade_id in candidates
                if trade_id in terminal_ids
            }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                side_effect=lambda **_bounds: [
                    {"trade_id": trade_id, "status": "ACTIVE"}
                    for trade_id in trade_ids
                    if trade_id not in terminal_ids
                ],
            ),
            patch(
                "database.get_authoritative_terminal_records",
                side_effect=terminal_records,
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            response = self._post("/api/offers/cancel_all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(retried_batches, [trade_ids[:2], trade_ids[2:]])
        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertTrue(status["complete"])
        self.assertIsNone(status["error"])
        self.assertEqual(status["current_batch"], 2)
        self.assertEqual(status["cancelled"], 4)

    def test_uninitialised_bot_denial_clears_state_and_allows_coordinator_retry(self):
        trade_id = "a" * 64
        stopped = _make_bot()
        stopped.is_running.return_value = False
        stopped.offer_manager.cancel_offers.return_value = {
            trade_id: {
                "outcome": "CANCEL_FAILED",
                "success": False,
                "submitted": False,
                "confirmed": False,
                "failed": True,
                "unknown": False,
                "method": "single_rpc",
                "transaction_id": None,
                "spend_bundle_id": None,
                "error": "not found",
                "http_status": 404,
                "raw_response": {"error": "not found"},
                "evidence_sha256": "c" * 64,
            }
        }

        def run_now(*, operation, target, name):
            target()
            return object()

        with (
            patch.object(api_server, "bot", None),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch("wallet.cancel_offers_batch") as direct_batch,
            patch("wallet.is_offer_time_expired", return_value=False),
            patch.object(api_server, "start_mutation_thread") as start_thread,
        ):
            resp = self._post("/api/offers/cancel_all")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(
            resp.get_json().get("reason"),
            "DURABLE_CANCEL_COORDINATOR_UNAVAILABLE",
        )
        direct_batch.assert_not_called()
        start_thread.assert_not_called()

        status = self._get(
            "/api/offers/cancel_all/status", environ_base=self._LOOPBACK
        ).get_json()
        self.assertFalse(status["running"])
        self.assertFalse(status["complete"])
        self.assertEqual(status["phase"], "error")
        self.assertEqual(
            status["error"], "Offer cancellation coordinator is unavailable"
        )

        with (
            patch.object(api_server, "bot", stopped),
            patch(
                "wallet.get_all_offers",
                return_value=[{"trade_id": trade_id, "status": "ACTIVE"}],
            ),
            patch("wallet.cancel_offers_batch") as retry_direct_batch,
            patch("wallet.is_offer_time_expired", return_value=False),
            patch(
                "database.get_authoritative_terminal_records",
                return_value={
                    trade_id: {
                        "intent_id": "intent-a",
                        "sage_trade_id": trade_id,
                        "outcome": "CANCELLED_PROVEN",
                    }
                },
            ),
            patch.object(api_server, "start_mutation_thread", side_effect=run_now),
        ):
            retry = self._post("/api/offers/cancel_all")

        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.get_json()["async"])
        stopped.offer_manager.cancel_offers.assert_called_once_with(
            [trade_id], reason="manual_cancel_all", force_storm=True
        )
        retry_direct_batch.assert_not_called()


def test_offer_diagnostic_does_not_invent_dexie_staleness_from_local_agreement():
    from blueprints.offers import _offer_diagnostic_assessment

    result = _offer_diagnostic_assessment(
        wallet_error=None,
        duplicate_coin_ids=[],
        reserve_backed=[],
        stale_in_db=[],
        wallet_only=[],
        wallet_cancel_pending=[],
        wallet_cancelled_still_visible=[],
    )

    assert result["local_book_consistent"] is True
    assert result["dexie_rows_evaluated"] is False
    assert result["likely_stale_dexie_rows"] is None
    assert "cannot determine" in result["diagnosis"]


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_offer_diagnostic_rejects_cached_wallet_book_after_sage_read_failure():
    bot = _make_bot()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    bot.offer_manager.get_wallet_sync_meta.return_value = {
        "fresh": False,
        "using_cache": True,
        "last_error": "sage_get_offers_unavailable",
    }

    with (
        patch.object(api_server, "bot", bot),
        patch("database.get_connection", return_value=conn),
    ):
        result = api_server.app.test_client().get(
            "/api/offers/diagnostic",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert result.status_code == 200
    body = result.get_json()
    assert body["success"] is True
    assert body["local_book_consistent"] is False
    assert body["wallet_error"] == "sage_get_offers_unavailable"
    assert "unavailable" in body["diagnosis"].lower()


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
def test_offer_diagnostic_accepts_fresh_empty_wallet_book():
    bot = _make_bot()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    bot.offer_manager.get_wallet_sync_meta.return_value = {
        "fresh": True,
        "using_cache": False,
        "last_error": "",
    }

    with (
        patch.object(api_server, "bot", bot),
        patch("database.get_connection", return_value=conn),
    ):
        result = api_server.app.test_client().get(
            "/api/offers/diagnostic",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert result.status_code == 200
    body = result.get_json()
    assert body["success"] is True
    assert body["local_book_consistent"] is True
    assert body["wallet_error"] is None


if __name__ == "__main__":
    unittest.main()
