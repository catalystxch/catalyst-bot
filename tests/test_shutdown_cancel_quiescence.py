"""Cancel All must not race with the asynchronous bot stop finalizer."""

import threading
from unittest.mock import patch

import api_server
import pytest
from api_test_support import api_mutations_permitted
from bot_loop import BotLoop


class _AliveThread:
    name = "bot-stop-finalizer"

    def is_alive(self):
        return True


class _UnreadableThread:
    name = "bot-stop-finalizer"

    def is_alive(self):
        raise RuntimeError("thread state unavailable")


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
