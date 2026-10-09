"""Regression coverage for the v1.4 Dexie-only beta boundary."""

from __future__ import annotations

from unittest.mock import MagicMock

from api_test_support import api_mutations_permitted


def test_existing_profile_cannot_restore_splash_flags(tmp_path, monkeypatch):
    """A legacy profile with Splash enabled must load as Dexie-only."""
    import config

    env_path = tmp_path / ".env"
    env_path.write_text(
        "SPLASH_ENABLED=true\nSPLASH_RECEIVE_ENABLED=true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_ENV_PATH", str(env_path))
    monkeypatch.setenv("SPLASH_ENABLED", "true")
    monkeypatch.setenv("SPLASH_RECEIVE_ENABLED", "true")

    candidate = config.Config()

    assert candidate.DEXIE_ONLY_BETA is True
    assert candidate.SPLASH_ENABLED is False
    assert candidate.SPLASH_RECEIVE_ENABLED is False
    assert candidate.update("SPLASH_ENABLED", "true") is False
    assert candidate.update_persisted("SPLASH_RECEIVE_ENABLED", "true") is False


def test_disabled_splash_manager_does_not_queue_or_flush(monkeypatch):
    """The publication manager must not retain offers while Splash is disabled."""
    import splash_manager

    monkeypatch.setattr(splash_manager.cfg, "DEXIE_ONLY_BETA", True, raising=False)
    monkeypatch.setattr(splash_manager.cfg, "SPLASH_ENABLED", True, raising=False)
    post = MagicMock(side_effect=AssertionError("Splash HTTP must remain disabled"))
    monkeypatch.setattr(splash_manager.requests, "post", post)
    manager = splash_manager.SplashManager()

    manager.queue_post("offer1dexieonly", "trade-dexie-only")
    result = manager.flush_queue(flush_all=True)

    assert manager._queue == []
    assert result == {"posted": 0, "failed": 0, "skipped": 0, "disabled": True}
    post.assert_not_called()


def test_disabled_splash_node_cannot_start(monkeypatch):
    """Direct node startup must fail closed before discovery or download."""
    import splash_node

    monkeypatch.setattr(splash_node.cfg, "DEXIE_ONLY_BETA", True, raising=False)
    monkeypatch.setattr(splash_node.cfg, "SPLASH_ENABLED", True, raising=False)
    node = splash_node.SplashNode()
    node.find_binary = MagicMock(
        side_effect=AssertionError("disabled Splash must not inspect a binary")
    )

    assert node.start() is False
    node.find_binary.assert_not_called()


def test_beta_does_not_start_splash_receive_worker(monkeypatch):
    """A stale receive flag cannot create a background Splash worker."""
    import bot_loop

    monkeypatch.setattr(bot_loop.cfg, "DEXIE_ONLY_BETA", True, raising=False)
    monkeypatch.setattr(bot_loop.cfg, "SPLASH_RECEIVE_ENABLED", True, raising=False)
    thread = MagicMock(side_effect=AssertionError("Splash worker must stay disabled"))
    monkeypatch.setattr(bot_loop.threading, "Thread", thread)
    candidate = object.__new__(bot_loop.BotLoop)
    candidate._splash_receive_thread = None

    candidate._start_splash_receive()

    assert candidate._splash_receive_thread is None
    thread.assert_not_called()


def test_beta_routes_reject_every_splash_mutation(monkeypatch):
    """Local API/bridge callers cannot route around the Dexie-only UI."""
    import api_server
    import splash_setup

    api_server.app.testing = True
    client = api_server.app.test_client()
    token = api_server._LOCAL_API_TOKEN
    headers = {"X-Bot-Local-Token": token}
    loopback = {"REMOTE_ADDR": "127.0.0.1"}
    bot = MagicMock()
    bot.splash_node.start.return_value = True
    bot.splash_node.is_running.return_value = False
    bot.get_splash_receive_stats.return_value = {"enabled": False}
    config_update = MagicMock(return_value=True)
    download = MagicMock(return_value={"success": True})
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(api_server.cfg, "DEXIE_ONLY_BETA", True, raising=False)
    monkeypatch.setattr(api_server.cfg, "update", config_update)
    monkeypatch.setattr(splash_setup, "start_background_download", download)

    with api_mutations_permitted(api_server):
        receive = client.post(
            "/api/splash/receive",
            json={"enabled": True},
            headers=headers,
            environ_base=loopback,
        )
        start = client.post(
            "/api/splash/node/start",
            json={},
            headers=headers,
            environ_base=loopback,
        )
        setup = client.post(
            "/api/splash/setup/download",
            json={},
            headers=headers,
            environ_base=loopback,
        )
        config_single = client.post(
            "/api/config",
            json={"key": "SPLASH_ENABLED", "value": "true"},
            headers=headers,
            environ_base=loopback,
        )
        config_bulk = client.post(
            "/api/config",
            json={"splash_enabled": True},
            headers=headers,
            environ_base=loopback,
        )
        config_live = client.post(
            "/api/config/live",
            json={"key": "SPLASH_ENABLED", "value": "true"},
            headers=headers,
            environ_base=loopback,
        )

    for response in (
        receive,
        start,
        setup,
        config_single,
        config_bulk,
        config_live,
    ):
        assert response.status_code == 409
        assert response.get_json()["reason"] == "DEXIE_ONLY_BETA"
    config_update.assert_not_called()
    bot.splash_node.start.assert_not_called()
    download.assert_not_called()


def test_beta_rejects_incoming_splash_even_if_stale_flag_is_true(monkeypatch):
    """An in-memory stale receive flag cannot reopen the P2P webhook."""
    import api_server

    api_server.app.testing = True
    client = api_server.app.test_client()
    monkeypatch.setattr(api_server.cfg, "DEXIE_ONLY_BETA", True, raising=False)
    monkeypatch.setattr(api_server.cfg, "SPLASH_RECEIVE_ENABLED", True, raising=False)

    response = client.post(
        "/api/splash/incoming",
        json={"offer": "offer1muststaydisabled"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 403
    assert response.get_json()["reason"] == "DEXIE_ONLY_BETA"
