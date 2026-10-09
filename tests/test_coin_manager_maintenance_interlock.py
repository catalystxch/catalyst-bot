"""Coin maintenance workers must not overlap on the same wallet."""

import threading
from unittest.mock import patch

import coin_manager


def test_topup_refuses_to_start_while_full_coin_prep_is_running():
    manager = coin_manager.CoinManager.__new__(coin_manager.CoinManager)
    manager._lock = threading.Lock()
    manager._prep_running = True
    manager._topup_running = False
    manager._topup_is_drip = True

    with (
        patch.object(coin_manager.threading, "Thread") as thread,
        patch.object(coin_manager, "log_event"),
    ):
        started = manager.start_topup()

    assert started is False
    assert manager._prep_running is True
    assert manager._topup_running is False
    thread.assert_not_called()
