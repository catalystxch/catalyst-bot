"""Cancel All must not race with the asynchronous bot stop finalizer."""

import threading
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import api_server
import pytest
from api_test_support import api_mutations_permitted
from bot_loop import BotLoop


@pytest.mark.parametrize("running", [True, None])
def test_bot_start_rejects_wallet_wide_cancel_in_progress(monkeypatch, running):
    bot = MagicMock()
    bot.is_running.return_value = False
    bot.start.return_value = True
    api_server.app.testing = True
    client = api_server.app.test_client()
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": running})
    with api_mutations_permitted(api_server):
        response = client.post(
            "/api/bot/start",
            json={},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert response.status_code == 409
    assert response.get_json()["reason"] == "CANCEL_ALL_IN_PROGRESS"
    bot.start.assert_not_called()


def test_bot_start_waits_for_cancel_all_stopped_book_check(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from flask import jsonify

    bot = MagicMock()
    bot.coin_manager.is_busy.return_value = False
    bot.offer_manager.sync_from_wallet.return_value = ([], [], [])
    bot.offer_manager.get_wallet_sync_meta.return_value = {
        "fresh": True,
        "using_cache": False,
    }
    bot.offer_manager.sync_from_wallet_with_meta.side_effect = lambda: (
        bot.offer_manager.sync_from_wallet(),
        bot.offer_manager.get_wallet_sync_meta(),
    )
    bot.is_running.return_value = False
    bot.start.return_value = True
    cfg = SimpleNamespace(
        CAT_ASSET_ID="ab" * 32,
        SPREAD_BPS=200,
        HARD_MIN_PRICE_XCH=Decimal("1"),
        HARD_MAX_PRICE_XCH=Decimal("2"),
        MAX_ACTIVE_BUY_OFFERS=1,
        MAX_ACTIVE_SELL_OFFERS=1,
        LIQUIDITY_MODE="buy_only",
    )
    entered = threading.Event()
    preflight_complete = threading.Event()
    release = threading.Event()

    def paused_cancel():
        entered.set()
        assert release.wait(5)
        return jsonify({"success": True})

    def completed_preflight(_cfg):
        preflight_complete.set()
        return None

    def post(path):
        return api_server.app.test_client().post(
            path,
            json={},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    api_server.app.testing = True
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(api_server, "cfg", cfg)
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": False})
    with (
        api_mutations_permitted(api_server),
        patch("blueprints.offers._api_cancel_all_locked", side_effect=paused_cancel),
        patch(
            "blueprints.bot._enforce_post_tibet_start_migration",
            return_value={"can_start": True},
        ),
        patch(
            "wallet.get_wallet_sync_status",
            return_value={"reachable": True, "sync_state": "synced"},
        ),
        patch("wallet.preflight_wallet_identity", return_value={"success": True}),
        patch.object(api_server, "_get_sage_signing_block_reason", return_value=None),
        patch(
            "wallet.get_authoritative_offer_history",
            return_value={"success": True, "offers": [], "end_of_history": True},
        ),
        patch("database.get_open_offers", return_value=[]),
        patch(
            "blueprints.bot._one_sided_open_offer_start_block",
            side_effect=completed_preflight,
        ),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        cancel_future = pool.submit(post, "/api/offers/cancel_all")
        assert entered.wait(5)
        start_future = pool.submit(post, "/api/bot/start")
        assert preflight_complete.wait(5)
        assert not start_future.done()
        bot.start.assert_not_called()
        release.set()
        assert cancel_future.result(timeout=5).status_code == 200
        assert start_future.result(timeout=5).status_code == 200
        bot.start.assert_called_once()


def test_bot_start_rejects_manual_coin_maintenance_in_progress(monkeypatch):
    bot = MagicMock()
    bot.is_running.return_value = False
    bot.coin_manager.is_busy.return_value = True
    bot.start.return_value = True
    bot.offer_manager.sync_from_wallet.return_value = ([], [], [])
    bot.offer_manager.get_wallet_sync_meta.return_value = {
        "fresh": True,
        "using_cache": False,
    }
    bot.offer_manager.sync_from_wallet_with_meta.side_effect = lambda: (
        bot.offer_manager.sync_from_wallet(),
        bot.offer_manager.get_wallet_sync_meta(),
    )
    cfg = SimpleNamespace(
        CAT_ASSET_ID="ab" * 32,
        SPREAD_BPS=200,
        HARD_MIN_PRICE_XCH=Decimal("1"),
        HARD_MAX_PRICE_XCH=Decimal("2"),
        MAX_ACTIVE_BUY_OFFERS=1,
        MAX_ACTIVE_SELL_OFFERS=1,
        LIQUIDITY_MODE="buy_only",
    )
    api_server.app.testing = True
    client = api_server.app.test_client()
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(api_server, "cfg", cfg)
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": False})
    with (
        api_mutations_permitted(api_server),
        patch(
            "blueprints.bot._enforce_post_tibet_start_migration",
            return_value={"can_start": True},
        ),
        patch(
            "wallet.get_wallet_sync_status",
            return_value={"reachable": True, "sync_state": "synced"},
        ),
        patch("wallet.preflight_wallet_identity", return_value={"success": True}),
        patch.object(api_server, "_get_sage_signing_block_reason", return_value=None),
        patch(
            "wallet.get_authoritative_offer_history",
            return_value={"success": True, "offers": [], "end_of_history": True},
        ),
        patch("database.get_open_offers", return_value=[]),
        patch("blueprints.bot._one_sided_open_offer_start_block", return_value=None),
    ):
        response = client.post(
            "/api/bot/start",
            json={},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert response.status_code == 409
    assert response.get_json()["reason"] == "COIN_MAINTENANCE_IN_PROGRESS"
    bot.start.assert_not_called()


@pytest.mark.parametrize(
    ("path", "worker_name"),
    [
        ("/api/coins/topup", "start_topup"),
        ("/api/coins/prep", "start_coin_prep"),
    ],
)
def test_bot_start_waits_for_manual_coin_dispatch(monkeypatch, path, worker_name):
    from concurrent.futures import ThreadPoolExecutor

    bot = MagicMock()
    bot.is_running.return_value = False
    bot.is_stopped.return_value = True
    bot.start.return_value = True
    bot.offer_manager.sync_from_wallet.return_value = ([], [], [])
    bot.offer_manager.get_wallet_sync_meta.return_value = {
        "fresh": True,
        "using_cache": False,
    }
    bot.offer_manager.sync_from_wallet_with_meta.side_effect = lambda: (
        bot.offer_manager.sync_from_wallet(),
        bot.offer_manager.get_wallet_sync_meta(),
    )
    cfg = SimpleNamespace(
        CAT_ASSET_ID="ab" * 32,
        SPREAD_BPS=200,
        HARD_MIN_PRICE_XCH=Decimal("1"),
        HARD_MAX_PRICE_XCH=Decimal("2"),
        MAX_ACTIVE_BUY_OFFERS=1,
        MAX_ACTIVE_SELL_OFFERS=1,
        LIQUIDITY_MODE="buy_only",
    )
    entered = threading.Event()
    preflight_complete = threading.Event()
    release = threading.Event()
    busy = False

    def paused_worker(*_args, **_kwargs):
        nonlocal busy
        entered.set()
        assert release.wait(5)
        busy = True
        return True

    def completed_preflight(_cfg):
        preflight_complete.set()
        return None

    def post(path):
        return api_server.app.test_client().post(
            path,
            json={"fee_approval_id": "a" * 64},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    api_server.app.testing = True
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(api_server, "cfg", cfg)
    monkeypatch.setattr(api_server, "_cancel_all_state", {"running": False})
    getattr(bot.coin_manager, worker_name).side_effect = paused_worker
    bot.coin_manager.is_busy.side_effect = lambda: busy
    with (
        api_mutations_permitted(api_server),
        patch(
            "blueprints.bot._enforce_post_tibet_start_migration",
            return_value={"can_start": True},
        ),
        patch(
            "wallet.get_wallet_sync_status",
            return_value={"reachable": True, "sync_state": "synced"},
        ),
        patch("wallet.preflight_wallet_identity", return_value={"success": True}),
        patch.object(api_server, "_get_sage_signing_block_reason", return_value=None),
        patch(
            "wallet.get_authoritative_offer_history",
            return_value={"success": True, "offers": [], "end_of_history": True},
        ),
        patch("database.get_open_offers", return_value=[]),
        patch(
            "blueprints.bot._one_sided_open_offer_start_block",
            side_effect=completed_preflight,
        ),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        maintenance_future = pool.submit(post, path)
        assert entered.wait(5)
        start_future = pool.submit(post, "/api/bot/start")
        assert preflight_complete.wait(5)
        assert not start_future.done()
        bot.start.assert_not_called()
        release.set()
        assert maintenance_future.result(timeout=5).status_code == 200
        start_response = start_future.result(timeout=5)

    assert start_response.status_code == 409
    assert start_response.get_json()["reason"] == "COIN_MAINTENANCE_IN_PROGRESS"
    bot.start.assert_not_called()


class _AliveThread:
    name = "bot-stop-finalizer"

    def is_alive(self):
        return True


class _UnreadableThread:
    name = "bot-stop-finalizer"

    def is_alive(self):
        raise RuntimeError("thread state unavailable")


class _DeadThread:
    name = "bot-stop-finalizer"

    def is_alive(self):
        return False


@pytest.mark.parametrize(
    ("status", "finalizer"),
    [
        ("stopping", _AliveThread()),
        ("stopped", _AliveThread()),
        ("stopped", _UnreadableThread()),
    ],
)
def test_cancel_all_rejects_unfinished_stop_before_wallet_history(
    monkeypatch, status, finalizer
):
    bot = BotLoop.__new__(BotLoop)
    bot._running = False
    bot._state_lock = threading.Lock()
    bot._bot_state = {"running": False, "status": status}
    bot._stop_finalize_thread = finalizer
    api_server.app.testing = True
    client = api_server.app.test_client()
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "read_only_status",
        lambda: type("S", (), {"allowed": True})(),
    )
    with (
        api_mutations_permitted(api_server),
        patch("wallet.get_authoritative_offer_history") as history,
    ):
        response = client.post(
            "/api/offers/cancel_all",
            json={},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert response.status_code == 409
    assert response.get_json()["reason"] == "BOT_STOPPING"
    history.assert_not_called()


@pytest.mark.parametrize("status", ["stopped", "blocked", "error"])
def test_cancel_all_allows_quiescent_bot_with_read_only_monitor(monkeypatch, status):
    bot = BotLoop.__new__(BotLoop)
    bot._running = False
    bot._state_lock = threading.Lock()
    bot._bot_state = {"running": False, "status": status}
    bot._stop_finalize_thread = _DeadThread()
    bot.runtime_monitor = SimpleNamespace(_thread=_AliveThread())
    api_server.app.testing = True
    client = api_server.app.test_client()
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(
        api_server.mutation_gate,
        "read_only_status",
        lambda: type("S", (), {"allowed": True})(),
    )
    with (
        api_mutations_permitted(api_server),
        patch(
            "offer_reconciliation.load_sage_offer_history",
            return_value={"complete": True, "read_error": None, "records": []},
        ),
    ):
        response = client.post(
            "/api/offers/cancel_all",
            json={},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
