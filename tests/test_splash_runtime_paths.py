import os
import time


def test_splash_install_path_lives_under_user_data():
    import splash_setup
    from user_paths import data_dir

    info = splash_setup.detect_platform()
    install_path = os.path.abspath(info["install_path"])

    assert install_path.startswith(os.path.abspath(data_dir()) + os.sep)
    assert os.path.dirname(os.path.abspath(splash_setup.__file__)) not in install_path


def test_splash_node_prefers_user_data_binary(monkeypatch):
    import splash_node
    from config import cfg
    from user_paths import data_dir

    binary_name = "splash.exe" if os.name == "nt" else "splash"
    splash_dir = os.path.join(data_dir(), "splash")
    os.makedirs(splash_dir, exist_ok=True)
    binary_path = os.path.join(splash_dir, binary_name)
    with open(binary_path, "wb") as fh:
        fh.write(b"fake splash binary")

    monkeypatch.setattr(cfg, "SPLASH_BINARY_PATH", "", raising=False)
    node = splash_node.SplashNode()

    assert os.path.abspath(node.find_binary()) == os.path.abspath(binary_path)


def test_disabled_stopped_splash_health_does_not_probe_submit_endpoint(monkeypatch):
    import splash_node
    from config import cfg

    submit_calls = []

    def unexpected_get(*args, **kwargs):
        submit_calls.append((args, kwargs))
        raise AssertionError("disabled Splash must not make a network health probe")

    monkeypatch.setattr(cfg, "SPLASH_ENABLED", False, raising=False)
    monkeypatch.setattr(splash_node.requests, "get", unexpected_get)

    node = splash_node.SplashNode()
    result = node.check_health()

    assert result["process_running"] is False
    assert result["api_reachable"] is False
    assert submit_calls == []


def test_stopped_splash_status_marks_cached_metrics_unreachable(monkeypatch):
    import splash_node
    from config import cfg

    monkeypatch.setattr(cfg, "SPLASH_ENABLED", False, raising=False)
    node = splash_node.SplashNode()
    node._metrics = {
        "peers": 4,
        "offers_received": 123,
        "offers_broadcasted": 7,
        "reachable": True,
        "last_error": None,
    }

    status = node.get_status()

    assert status["process_running"] is False
    assert status["metrics"]["reachable"] is False
    assert status["metrics"]["peers"] == 4
    assert status["metrics"]["offers_received"] == 123


def test_stopped_splash_receive_stats_do_not_publish_cached_metrics_as_live(
    monkeypatch,
):
    import bot_loop
    import database
    from config import cfg

    monkeypatch.setattr(cfg, "CAT_ASSET_ID", "ab" * 32, raising=False)
    monkeypatch.setattr(cfg, "CAT_TICKER_ID", "MZ_XCH", raising=False)
    monkeypatch.setattr(cfg, "SPLASH_RECEIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(
        database,
        "get_splash_incoming_stats",
        lambda **_kwargs: {
            "total": 245,
            "new": 0,
            "processed": 0,
            "ignored": 245,
            "expired": 0,
            "relevant": 0,
            "last_received_at": "2026-09-05 00:57:39",
            "last_relevant_at": None,
        },
    )

    class StoppedSplashNode:
        @staticmethod
        def is_running():
            return False

        @staticmethod
        def get_metrics():
            return {
                "reachable": True,
                "peers": 4,
                "offers_received": 3619,
                "offers_broadcasted": 15,
            }

    loop = object.__new__(bot_loop.BotLoop)
    loop.splash_node = StoppedSplashNode()
    loop._splash_receive_interval = 5
    loop._splash_receive_batch_size = 10

    stats = loop.get_splash_receive_stats()

    assert stats["active"] is False
    assert stats["node_metrics"]["reachable"] is False
    assert stats["node_metrics"]["peers"] == 4
    assert stats["node_metrics"]["offers_received"] == 3619


def test_splash_download_refuses_release_without_checksum(monkeypatch):
    import splash_setup

    info = splash_setup.detect_platform()
    requested_urls = []

    monkeypatch.delenv("CATALYST_ALLOW_UNVERIFIED_SPLASH_DOWNLOAD", raising=False)
    monkeypatch.setattr(
        splash_setup,
        "get_latest_release",
        lambda: {
            "tag": "v-test",
            "assets": [
                {
                    "name": info["asset_name"],
                    "size": 12,
                    "url": "https://example.invalid/splash",
                }
            ],
        },
    )

    def fake_get(url, *args, **kwargs):
        requested_urls.append(url)
        raise AssertionError("binary download should not start without checksum")

    monkeypatch.setattr(splash_setup.requests, "get", fake_get, raising=False)

    result = splash_setup.download_splash()

    assert result["success"] is False
    assert "sha256" in result["message"].lower()
    assert requested_urls == []


def test_splash_node_offer_hook_uses_ipv4_loopback(monkeypatch):
    import splash_node
    from config import cfg

    captured = {}

    class FakeProcess:
        pid = 12345
        stdout = []

        def poll(self):
            return None

    class FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return False

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr(cfg, "SPLASH_RECEIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(cfg, "PORT", 5000, raising=False)
    monkeypatch.setattr(
        cfg, "SPLASH_SUBMIT_URL", "http://localhost:4000", raising=False
    )
    monkeypatch.setattr(cfg, "SPLASH_P2P_PORT", 11511, raising=False)
    monkeypatch.setattr(cfg, "SPLASH_METRICS_PORT", 4001, raising=False)
    monkeypatch.setattr(splash_node.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(splash_node.threading, "Thread", FakeThread)

    node = splash_node.SplashNode()
    node._binary_path = "splash.exe"
    node._kill_stale_process = lambda port: None

    node._launch_process()

    hook_index = captured["cmd"].index("--offer-hook") + 1
    assert captured["cmd"][hook_index] == "http://127.0.0.1:5000/api/splash/incoming"
    assert "http://localhost:5000/api/splash/incoming" not in captured["cmd"]


def test_splash_output_reader_keeps_reading_lines(monkeypatch):
    import splash_node

    class FakeProcess:
        stdout = iter(
            [
                "connected to peer one\n",
                "connected to peer two\n",
            ]
        )

    monkeypatch.setattr(splash_node, "log_event", lambda *args, **kwargs: None)
    node = splash_node.SplashNode()
    node._process = FakeProcess()
    node._last_start_time = time.time()

    node._read_output()

    assert node.get_recent_output(10) == [
        "connected to peer one",
        "connected to peer two",
    ]


def test_splash_output_reader_suppresses_hook_connection_refused_burst(monkeypatch):
    import splash_node

    class FakeProcess:
        stdout = iter(
            [
                "failed POST http://127.0.0.1:5000/api/splash/incoming: Connection refused\n",
                "failed POST http://127.0.0.1:5000/api/splash/incoming: Connection refused\n",
                "failed POST http://127.0.0.1:5000/api/splash/incoming: Connection refused\n",
            ]
        )

    events = []
    monkeypatch.setattr(
        splash_node,
        "log_event",
        lambda severity, event_type, message: events.append(
            (severity, event_type, message)
        ),
    )
    node = splash_node.SplashNode()
    node._process = FakeProcess()
    node._last_start_time = time.time()

    node._read_output()

    warnings = [event for event in events if event[0] == "warning"]
    assert len(warnings) <= 1


def test_splash_output_reader_suppresses_windows_hook_refused_burst(monkeypatch):
    import splash_node

    refused_line = (
        "Error posting to offer hook: error sending request for url "
        "(http://127.0.0.1:5000/api/splash/incoming): error trying "
        "to connect: tcp connect error: No connection could be made "
        "because the target machine actively refused it. (os error 10061)\n"
    )

    class FakeProcess:
        stdout = iter([refused_line, refused_line, refused_line])

    events = []
    monkeypatch.setattr(
        splash_node,
        "log_event",
        lambda severity, event_type, message: events.append(
            (severity, event_type, message)
        ),
    )
    node = splash_node.SplashNode()
    node._process = FakeProcess()
    node._last_start_time = time.time()

    node._read_output()

    warnings = [event for event in events if event[0] == "warning"]
    assert len(warnings) <= 1


def test_splash_output_reader_throttles_hook_http_failures_and_redacts_offer(
    monkeypatch,
):
    import splash_node

    bad_offer = "offer1" + ("x" * 120)
    hook_line = (
        "Error posting to offer hook http://127.0.0.1:5000/api/splash/incoming: "
        f"HTTP 429 Too Many Requests for {bad_offer}\n"
    )

    class FakeProcess:
        stdout = iter([hook_line, hook_line, hook_line])

    events = []
    monkeypatch.setattr(
        splash_node,
        "log_event",
        lambda severity, event_type, message: events.append(
            (severity, event_type, message)
        ),
    )
    node = splash_node.SplashNode()
    node._process = FakeProcess()
    node._last_start_time = time.time() - 120

    node._read_output()

    hook_events = [
        event
        for event in events
        if event[1] == "splash_node_output" and "webhook" in event[2].lower()
    ]
    assert len(hook_events) == 1
    assert hook_events[0][0] == "warning"
    assert bad_offer not in hook_events[0][2]


def test_splash_output_reader_labels_json_rate_limit_as_backpressure(monkeypatch):
    import splash_node

    hook_line = (
        "Error posting to offer hook http://127.0.0.1:5000/api/splash/incoming: "
        'response body {"error":"rate_limited"}\n'
    )

    class FakeProcess:
        stdout = iter([hook_line])

    events = []
    monkeypatch.setattr(
        splash_node,
        "log_event",
        lambda severity, event_type, message: events.append(
            (severity, event_type, message)
        ),
    )
    node = splash_node.SplashNode()
    node._process = FakeProcess()
    node._last_start_time = time.time() - 120

    node._read_output()

    assert events == [
        (
            "warning",
            "splash_node_output",
            "Splash webhook backpressure active; suppressing repeated hook errors for 60s",
        )
    ]


def test_splash_output_reader_redacts_and_throttles_interleaved_offer_errors(
    monkeypatch,
):
    """Concurrent Splash output must not leak full offers into activity logs.

    The Windows daemon can interleave its connection-error and received-offer
    writes before Python sees a newline.  Those fragments no longer contain the
    offer-hook URL, so they previously bypassed hook throttling and emitted the
    complete bech32 offer as a warning for every peer message.
    """
    import splash_node

    offer_blob = "offer1" + ("q" * 900)

    class FakeProcess:
        stdout = iter(
            [
                f"error trying to connectReceived Offer: {offer_blob}\n",
                f"tcp connect errorReceived Offer: : {offer_blob}\n",
                "No connection could be made because the target machine "
                "actively refused it.Received Offer: (os error 10061)\n",
            ]
        )

    events = []
    monkeypatch.setattr(
        splash_node,
        "log_event",
        lambda severity, event_type, message: events.append(
            (severity, event_type, message)
        ),
    )
    node = splash_node.SplashNode()
    node._process = FakeProcess()
    node._last_start_time = time.time() - 120

    node._read_output()

    warnings = [event for event in events if event[0] == "warning"]
    assert len(warnings) == 1
    assert "webhook" in warnings[0][2].lower()
    assert all(offer_blob not in event[2] for event in events)
    assert all(offer_blob not in line for line in node.get_recent_output(10))


def test_splash_output_reader_groups_fragmented_hook_connection_failure(monkeypatch):
    """One split Windows hook failure must produce one actionable warning."""
    import splash_node

    class FakeProcess:
        stdout = iter(
            [
                "error trying to connectReceived Offer: offer1abc123\n",
                "No connection could be made because the target machine actively "
                + "refused it. (os error 10061)\n",
                "error sending requestReceived Offer: offer1def456\n",
                ": tcp connect error\n",
                " (os error Received Offer: offer1fedcba\n",
                " (os error Received Offer: offer1fedcba)\n",
            ]
        )

    events = []
    monkeypatch.setattr(
        splash_node,
        "log_event",
        lambda severity, event_type, message: events.append(
            (severity, event_type, message)
        ),
    )
    node = splash_node.SplashNode()
    node._process = FakeProcess()
    node._last_start_time = time.time() - 120

    node._read_output()

    warnings = [event for event in events if event[0] == "warning"]
    assert warnings == [
        (
            "warning",
            "splash_node_output",
            "Splash webhook delivery failing; suppressing repeated hook errors for 60s",
        )
    ]


def test_splash_output_reader_classifies_isolated_failure_as_backpressure_when_hook_is_live(
    monkeypatch,
):
    import splash_node

    class FakeProcess:
        stdout = iter(["error trying to connectReceived Offer: offer1abc123\n"])

    events = []
    monkeypatch.setattr(
        splash_node,
        "log_event",
        lambda severity, event_type, message: events.append(
            (severity, event_type, message)
        ),
    )
    node = splash_node.SplashNode()
    node._process = FakeProcess()
    node._last_start_time = time.time() - 120
    node.note_webhook_delivery()

    node._read_output()

    assert events == [
        (
            "warning",
            "splash_node_output",
            "Splash webhook backpressure active; inbound delivery remains live; "
            "suppressing repeated hook errors for 60s",
        )
    ]
