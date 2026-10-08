"""Regression tests for CodeQL security-hardening findings."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import api_server
from api_test_support import api_mutations_permitted
import sage_node
from blueprints import bot as bot_routes
from blueprints import coin_prep as coin_prep_routes
from blueprints import config_bp
from blueprints import market as market_routes
import coin_prep_worker


ROOT = Path(__file__).resolve().parents[1]


def test_gui_does_not_reinterpret_confirmation_text_as_html():
    source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert "msgEl.innerHTML = message" not in source
    assert "msgEl.innerHTML = String(message)" not in source
    assert "allowHtml: true" not in source


def test_gui_external_links_use_protocol_allowlist_not_scheme_denylist():
    source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert "startsWith('javascript:')" not in source
    assert "!/^https?:$/i.test(parsed.protocol)" in source


def test_gui_token_icons_are_validated_before_dom_assignment():
    source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert "function getSafeTokenIconUrl(" in source
    assert "titleIcon.setAttribute('src', iconUrl)" not in source
    assert "img.setAttribute('src', url)" not in source
    assert "iconEl.src = url" not in source
    assert "titleIcon.src =" not in source


def test_confirmation_text_uses_no_custom_tag_stripping_sanitizer():
    source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert ".replace(/<[^>]*>/g" not in source
    assert ".confirm-modal-message" in source
    assert "white-space: pre-line" in source


def test_smart_settings_result_does_not_reinterpret_dynamic_markup():
    source = (ROOT / "bot_gui.html").read_text(encoding="utf-8")

    assert "resultBody.innerHTML =" not in source


def test_fee_reason_translation_never_returns_arbitrary_exception_text():
    assert (
        coin_prep_routes._public_fee_reason(
            ValueError("FEE_APPROVAL_STALE"), "FEE_APPROVAL_UNAVAILABLE"
        )
        == "FEE_APPROVAL_STALE"
    )
    assert (
        coin_prep_routes._public_fee_reason(
            ValueError("FEE_SECRET_LOCAL_PATH"), "FEE_APPROVAL_UNAVAILABLE"
        )
        == "FEE_APPROVAL_UNAVAILABLE"
    )
    assert (
        coin_prep_routes._public_fee_reason(
            ValueError("FEE_PREP_CAMPAIGN_UNAVAILABLE"), "FEE_PREVIEW_UNAVAILABLE"
        )
        == "FEE_PREP_CAMPAIGN_UNAVAILABLE"
    )
    assert (
        coin_prep_routes._public_fee_reason(
            ValueError("FEE_WALLET_IDENTITY_UNAVAILABLE"), "FEE_PREVIEW_UNAVAILABLE"
        )
        == "FEE_WALLET_IDENTITY_UNAVAILABLE"
    )


def test_coin_prep_cli_rejects_unsafe_args_without_spawning(monkeypatch):
    worker = coin_prep_worker.CoinPrepWorker.__new__(coin_prep_worker.CoinPrepWorker)
    worker.fingerprint = "123;calc"
    spawned = False

    def fake_run(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("unsafe command should not be spawned")

    monkeypatch.setattr(coin_prep_worker.subprocess, "run", fake_run)

    success, output = worker._run_chia_wallet_show()

    assert success is False
    assert "unsafe" in output.lower()
    assert spawned is False


def test_open_data_folder_error_does_not_expose_exception_details():
    api_server.app.testing = True
    client = api_server.app.test_client()
    loopback = {"REMOTE_ADDR": "127.0.0.1"}
    client.get(
        f"/?bootstrap={api_server._LOCAL_API_BOOTSTRAP_TOKEN}",
        environ_base=loopback,
    )

    with patch(
        "user_paths.data_dir", side_effect=RuntimeError("secret local path leaked")
    ):
        resp = client.post("/api/open-data-folder", environ_base=loopback)

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "data_dir_unavailable"
    assert "secret" not in str(body).lower()


def test_api_exception_response_hides_current_exception():
    with patch.object(api_server, "log_event") as log_event:
        with api_server.app.test_request_context("/api/example"):
            try:
                raise RuntimeError("secret traceback details")
            except RuntimeError:
                response, status = api_server._api_exception("/api/example")

    assert status == 500
    body = response.get_json()
    assert body == {"error": "Internal server error", "code": "SERVER_ERROR"}
    assert "secret" not in str(body).lower()
    logged_message = str(log_event.call_args.args[2]).lower()
    assert "secret traceback details" not in logged_message
    assert "traceback" not in logged_message


def test_api_error_event_log_hides_exception_details():
    with patch.object(api_server, "log_event") as log_event:
        with api_server.app.test_request_context("/api/example"):
            response, status = api_server._api_error(
                RuntimeError("secret api error details"),
                "/api/example",
            )

    assert status == 500
    assert response.get_json() == {
        "error": "Internal server error",
        "code": "SERVER_ERROR",
    }
    logged_message = str(log_event.call_args.args[2]).lower()
    assert "secret api error details" not in logged_message


def test_spacescan_context_hides_exception_details():
    with patch(
        "database.get_market_analysis_cache",
        side_effect=RuntimeError("secret spacescan path"),
    ):
        context = api_server._get_spacescan_market_context("a" * 64)

    assert context["message"] == "Spacescan context unavailable right now."
    assert "secret" not in str(context).lower()


def test_sage_cert_pair_accepts_only_wallet_pair_under_same_ssl_dir(tmp_path):
    ssl_dir = tmp_path / "PortableSage" / "ssl"
    ssl_dir.mkdir(parents=True)
    cert = ssl_dir / "wallet.crt"
    key = ssl_dir / "wallet.key"
    cert.write_text("cert", encoding="utf-8")
    key.write_text("key", encoding="utf-8")

    with patch.dict(
        "os.environ",
        {"SAGE_ALLOWED_CERT_ROOTS": str(tmp_path / "PortableSage")},
        clear=False,
    ):
        ok, reason, cert_real, key_real = sage_node.validate_sage_cert_pair(
            str(cert),
            str(key),
        )

    assert ok is True
    assert reason == ""
    assert cert_real == str(cert.resolve())
    assert key_real == str(key.resolve())


def test_sage_cert_pair_rejects_key_outside_selected_ssl_dir(tmp_path):
    ssl_dir = tmp_path / "PortableSage" / "ssl"
    ssl_dir.mkdir(parents=True)
    cert = ssl_dir / "wallet.crt"
    cert.write_text("cert", encoding="utf-8")

    outside = tmp_path / "other" / "wallet.key"
    outside.parent.mkdir()
    outside.write_text("key", encoding="utf-8")

    with patch.dict(
        "os.environ",
        {"SAGE_ALLOWED_CERT_ROOTS": str(tmp_path / "PortableSage")},
        clear=False,
    ):
        ok, reason, _, _ = sage_node.validate_sage_cert_pair(str(cert), str(outside))

    assert ok is False
    assert "same Sage ssl folder" in reason


def test_sage_cert_pair_rejects_unknown_custom_root(tmp_path):
    ssl_dir = tmp_path / "PortableSage" / "ssl"
    ssl_dir.mkdir(parents=True)
    cert = ssl_dir / "wallet.crt"
    key = ssl_dir / "wallet.key"
    cert.write_text("cert", encoding="utf-8")
    key.write_text("key", encoding="utf-8")

    with patch.dict("os.environ", {"SAGE_ALLOWED_CERT_ROOTS": ""}, clear=False):
        ok, reason, _, _ = sage_node.validate_sage_cert_pair(str(cert), str(key))

    assert ok is False
    assert "detected Sage data folder" in reason


def test_sage_cert_pair_rejects_network_path_before_resolution():
    with patch.object(
        sage_node.os.path,
        "realpath",
        side_effect=AssertionError("network path was resolved"),
    ) as resolve:
        ok, reason, _, _ = sage_node.validate_sage_cert_pair(
            r"\\attacker\share\ssl\wallet.crt"
        )

    assert ok is False
    assert reason == "Network certificate paths are not allowed."
    resolve.assert_not_called()


def test_sage_cert_candidates_rejects_unconfigured_data_dir(tmp_path):
    client, loopback = _api_client()

    resp = client.get(
        "/api/sage/cert-candidates",
        query_string={"data_dir": str(tmp_path / "UnconfiguredSage")},
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base=loopback,
    )

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_sage_cert_candidates_accepts_configured_data_dir(tmp_path):
    data_dir = tmp_path / "PortableSage"
    ssl_dir = data_dir / "ssl"
    ssl_dir.mkdir(parents=True)
    (ssl_dir / "wallet.crt").write_text("cert", encoding="utf-8")
    (ssl_dir / "wallet.key").write_text("key", encoding="utf-8")
    client, loopback = _api_client()

    with patch.dict("os.environ", {"SAGE_ALLOWED_CERT_ROOTS": str(data_dir)}):
        resp = client.get(
            "/api/sage/cert-candidates",
            query_string={"data_dir": str(data_dir)},
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base=loopback,
        )

    assert resp.status_code == 200
    assert resp.get_json()["detected_cert_path"] == str(ssl_dir / "wallet.crt")


class _StartableBot:
    def __init__(self):
        self.started = False
        self.offer_manager = MagicMock()
        self.offer_manager.sync_from_wallet.return_value = ([], [], [])
        self.offer_manager.get_wallet_sync_meta.return_value = {
            "fresh": True,
            "using_cache": False,
        }
        self.offer_manager.sync_from_wallet_with_meta.side_effect = lambda: (
            self.offer_manager.sync_from_wallet(),
            self.offer_manager.get_wallet_sync_meta(),
        )

    def is_running(self):
        return False

    def start(self):
        self.started = True
        return True


def _api_client():
    api_server.app.testing = True
    return api_server.app.test_client(), {"REMOTE_ADDR": "127.0.0.1"}


def test_bot_start_warnings_do_not_expose_exception_details(monkeypatch):
    client, loopback = _api_client()
    bot = _StartableBot()
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(api_server.cfg, "CAT_ASSET_ID", "ab" * 32, raising=False)
    monkeypatch.setattr(api_server.cfg, "SPREAD_BPS", 100, raising=False)
    monkeypatch.setattr(api_server.cfg, "ENABLE_COIN_PREP", False, raising=False)
    monkeypatch.setattr(api_server, "_get_sage_signing_block_reason", lambda: None)

    with (
        api_mutations_permitted(api_server),
        patch("database.list_active_bootstrap_campaigns_for_asset", return_value=[]),
        patch.object(
            bot_routes,
            "_enforce_post_tibet_start_migration",
            return_value={"can_start": True, "reason_code": "MIGRATION_COMPLETE"},
        ),
        patch(
            "wallet.get_wallet_sync_status",
            side_effect=RuntimeError("secret wallet traceback"),
        ),
        patch(
            "wallet.preflight_wallet_identity",
            return_value={"success": True, "reason": "identity_verified"},
        ),
        patch("coin_manager.check_tier_size_drift_standalone", return_value=[]),
    ):
        resp = client.post(
            "/api/bot/start",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base=loopback,
        )

    assert resp.status_code == 200
    body_text = resp.get_data(as_text=True).lower()
    assert "secret wallet traceback" not in body_text
    assert "traceback" not in body_text


def test_bot_start_coin_prep_gate_hides_worker_exception_details(monkeypatch):
    client, loopback = _api_client()
    bot = _StartableBot()
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(api_server.cfg, "CAT_ASSET_ID", "ab" * 32, raising=False)
    monkeypatch.setattr(api_server.cfg, "SPREAD_BPS", 100, raising=False)
    monkeypatch.setattr(api_server.cfg, "ENABLE_COIN_PREP", True, raising=False)
    monkeypatch.setattr(api_server, "_get_sage_signing_block_reason", lambda: None)

    failed_state = {
        "running": False,
        "complete": False,
        "phase": "error",
        "error": "secret coin prep traceback",
    }
    with (
        api_mutations_permitted(api_server),
        patch("database.list_active_bootstrap_campaigns_for_asset", return_value=[]),
        patch(
            "wallet.get_wallet_sync_status",
            return_value={"reachable": True, "sync_state": "synced"},
        ),
        patch("coin_manager.check_tier_size_drift_standalone", return_value=[]),
        patch.dict(api_server._coin_prep_state, failed_state, clear=True),
    ):
        resp = client.post(
            "/api/bot/start",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base=loopback,
        )

    assert resp.status_code == 400
    body_text = resp.get_data(as_text=True).lower()
    assert "coin prep failed" in body_text
    assert "secret coin prep traceback" not in body_text
    assert "traceback" not in body_text


def test_sage_route_payloads_hide_exception_derived_details(monkeypatch):
    client, loopback = _api_client()
    auth = {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}

    with (
        api_mutations_permitted(api_server),
        patch(
            "sage_node.start_chia",
            return_value={"success": False, "error": "secret daemon traceback"},
        ),
    ):
        resp = client.post(
            "/api/sage/daemon/start",
            json={"services": "all"},
            headers=auth,
            environ_base=loopback,
        )
    assert resp.status_code == 200
    assert "secret daemon traceback" not in resp.get_data(as_text=True).lower()

    with patch(
        "chia_node.get_startup_status",
        return_value={"phase": "error", "error": "secret startup traceback"},
    ):
        resp = client.get(
            "/api/sage/startup-status",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base=loopback,
        )
    assert resp.status_code == 200
    assert "secret startup traceback" not in resp.get_data(as_text=True).lower()

    with (
        api_mutations_permitted(api_server),
        patch(
            "chia_node.trigger_start",
            return_value={"success": False, "error": "secret trigger traceback"},
        ),
        patch(
            "blueprints.sage._runtime_fingerprint_decision",
            return_value={"success": True},
        ),
    ):
        resp = client.post(
            "/api/sage/start-with-fingerprint",
            json={"fingerprint": "12345678"},
            headers=auth,
            environ_base=loopback,
        )
    assert resp.status_code == 200
    assert "secret trigger traceback" not in resp.get_data(as_text=True).lower()

    fake_cfg = SimpleNamespace(update=lambda *args, **kwargs: True)
    with (
        api_mutations_permitted(api_server),
        patch.object(api_server, "bot", None),
        patch.object(api_server, "cfg", fake_cfg),
        patch(
            "chia_node.get_available_fingerprints",
            return_value=[{"fingerprint": "12345678"}],
        ),
        patch(
            "chia_node.trigger_start",
            return_value={"success": False, "error": "secret persist traceback"},
        ),
        patch(
            "blueprints.sage._runtime_fingerprint_decision",
            return_value={"success": True},
        ),
    ):
        resp = client.post(
            "/api/sage/fingerprint",
            json={"fingerprint": "12345678"},
            headers=auth,
            environ_base=loopback,
        )
    assert resp.status_code == 400
    assert "secret persist traceback" not in resp.get_data(as_text=True).lower()


def test_full_node_status_hides_watcher_exception_details(monkeypatch):
    class BrokenWatcher:
        @property
        def _full_node_active(self):
            raise RuntimeError("secret watcher traceback at C:\\private\\wallet.key")

    client, loopback = _api_client()
    monkeypatch.setattr("mempool_watcher._watcher_instance", BrokenWatcher())

    resp = client.get(
        "/api/full-node/status",
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base=loopback,
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["watcher_error"] == "Watcher status unavailable"
    assert "private" not in resp.get_data(as_text=True).lower()


def test_provider_stats_hide_exception_details():
    client, loopback = _api_client()

    with patch(
        "spacescan.get_api_stats",
        side_effect=RuntimeError("secret Spacescan traceback at C:\\private"),
    ):
        resp = client.get(
            "/api/diagnostics/api-stats",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base=loopback,
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["spacescan"]["available"] is False
    assert body["spacescan"]["error"] == "Spacescan status unavailable"
    assert "private" not in resp.get_data(as_text=True).lower()


def test_coin_prep_status_hides_drift_exception_details():
    client, loopback = _api_client()

    with (
        patch.dict(api_server._coin_prep_state, {"running": False}),
        patch(
            "blueprints.coin_prep._tier_size_drift_findings",
            side_effect=RuntimeError("secret tier traceback at C:\\private"),
        ),
    ):
        resp = client.get(
            "/api/coin-prep/status",
            environ_base=loopback,
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["tier_size_drift_error"] == "Tier status unavailable"
    assert "private" not in resp.get_data(as_text=True).lower()


def test_coin_prep_status_requires_local_api_credential():
    client, loopback = _api_client()

    unauthorized = client.get("/api/coin-prep/status", environ_base=loopback)
    assert unauthorized.status_code == 401
    assert unauthorized.get_json() == {"error": "unauthorized"}

    authorized = client.get(
        "/api/coin-prep/status",
        environ_base=loopback,
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
    )
    assert authorized.status_code == 200
    assert authorized.get_json()["success"] is True


def test_bootstrap_status_requires_local_api_credential():
    client, loopback = _api_client()

    unauthorized = client.get("/api/bootstrap/status", environ_base=loopback)
    assert unauthorized.status_code == 401
    assert unauthorized.get_json() == {"error": "unauthorized"}

    authorized = client.get(
        "/api/bootstrap/status",
        environ_base=loopback,
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
    )
    assert authorized.status_code == 200


def test_private_wallet_diagnostic_reads_require_local_api_credential():
    client, loopback = _api_client()
    for path in (
        "/api/health/runtime",
        "/api/sage/fingerprints",
        "/api/sage/cert-candidates",
        "/api/offers/diagnostic",
        "/api/reservations",
    ):
        response = client.get(path, environ_base=loopback)
        assert response.status_code == 401, path
        assert response.get_json() == {"error": "unauthorized"}, path
        assert client.head(path, environ_base=loopback).status_code == 401, path


def test_coin_inventory_get_requires_local_credential_before_worker_status_checks():
    client, loopback = _api_client()
    bot = MagicMock()
    bot.is_running.return_value = False
    bot.coin_manager.get_status.return_value = {"success": True, "coins": []}
    with patch.object(api_server, "bot", bot):
        unauthorized = client.get("/api/coins", environ_base=loopback)
        assert unauthorized.status_code == 401
        assert unauthorized.get_json() == {"error": "unauthorized"}
        bot.coin_manager.check_coin_prep_status.assert_not_called()
        bot.coin_manager.update_coin_counts.assert_not_called()

        unauthorized_head = client.head("/api/coins", environ_base=loopback)
        assert unauthorized_head.status_code == 401
        bot.coin_manager.check_coin_prep_status.assert_not_called()
        bot.coin_manager.update_coin_counts.assert_not_called()

        authorized = client.get(
            "/api/coins",
            environ_base=loopback,
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        )
        assert authorized.status_code == 200
        bot.coin_manager.check_coin_prep_status.assert_called_once()

        authorized_head = client.head(
            "/api/coins",
            environ_base=loopback,
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        )
        assert authorized_head.status_code == 405
        bot.coin_manager.check_coin_prep_status.assert_called_once()

        client.set_cookie(
            api_server._LOCAL_API_COOKIE, api_server._LOCAL_API_COOKIE_VALUE
        )
        cross_site = client.get(
            "/api/coins",
            environ_base=loopback,
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert cross_site.status_code == 403
        bot.coin_manager.check_coin_prep_status.assert_called_once()


def test_wallet_and_trade_read_routes_require_local_credential():
    client, loopback = _api_client()
    paths = (
        "/api/fingerprint",
        "/api/cats",
        "/api/coin-prep/verify",
        "/api/offers",
        "/api/fills",
        "/api/fills/classified",
        "/api/fills/arb-wallets",
        "/api/pnl",
        "/api/pnl/reset-preview",
        "/api/inventory",
        "/api/stats",
        "/api/config",
        "/api/config/validate",
        "/api/fees/status",
        "/api/wallets/detect",
        "/api/check-resume",
        "/api/diagnostics/runtime",
        "/api/diagnostics/api-stats",
        "/api/doctor",
        "/api/self-test",
        "/api/alerts",
        "/api/token_overview",
        "/api/risk/spreads",
        "/api/settings/defaults",
        "/api/smart-defaults",
        "/api/console/status",
        "/api/splash/node",
        "/api/splash/node/output",
        "/api/splash/receive",
        "/api/splash/setup/check",
        "/api/splash/setup/progress",
        "/api/splash/setup/release",
        "/api/splash/stats",
        "/api/watchdog/shape-fix-status",
        "/api/update/relaunch-intent",
        "/api/update/status",
        "/api/offers/cancel_all/status",
        "/api/market/fill-intel",
        "/api/market/intel",
        "/api/market/confidence",
        "/api/market/dbx",
        "/api/dbx/pending",
        "/api/boost/state",
        "/api/splash/incoming/list",
        "/api/bootstrap/walletconnect/config",
        "/api/bootstrap/partial-capability",
        "/api/bootstrap/capabilities/partial-offers",
        "/api/bot/state",
        "/api/bot/price",
        "/api/dbx/info",
        "/api/full-node/status",
        "/api/sage/startup-status",
        "/api/wallet/sage-running",
    )
    for path in paths:
        route = next(
            rule
            for rule in api_server.app.url_map.iter_rules()
            if rule.rule == path and "GET" in rule.methods
        )
        handler = MagicMock(return_value={"probe": True})
        with patch.dict(api_server.app.view_functions, {route.endpoint: handler}):
            unauthorized = client.get(path, environ_base=loopback)
            assert unauthorized.status_code == 401, path
            assert unauthorized.get_json() == {"error": "unauthorized"}, path
            assert client.head(path, environ_base=loopback).status_code == 401, path
            handler.assert_not_called()

            authorized = client.get(
                path,
                environ_base=loopback,
                headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            )
            assert authorized.status_code == 200, path
            assert authorized.get_json() == {"probe": True}, path
            authorized_head = client.head(
                path,
                environ_base=loopback,
                headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            )
            assert authorized_head.status_code == 405, path
            handler.assert_called_once()


def test_every_get_api_route_has_an_explicit_privacy_classification():
    # A new GET handler must be reviewed before another local process can
    # read it merely by connecting to the Flask port. Debug routes and SSE
    # have their own earlier guards; quarantine has a parameterized path.
    public_or_separately_guarded = {
        "/api/amm/price",
        "/api/check-update",
        "/api/coinset/stats",
        "/api/debug/coinprep",
        "/api/debug/pricing",
        "/api/debug/tibet-test",
        "/api/dexie/stats",
        "/api/dexie/v3-pairs",
        "/api/events",
        "/api/health",
        "/api/market/orderbook",
        "/api/market/price-history",
        "/api/market/slippage",
        "/api/market/summary",
        "/api/offers/open_count",
        "/api/price",
        "/api/price/tibet",
        "/api/safety/quarantine/<quarantine_id>",
        "/api/safety/status",
        "/api/sage/latest-release",
        "/api/spacescan/status",
    }
    registered = {
        rule.rule
        for rule in api_server.app.url_map.iter_rules()
        if rule.rule.startswith("/api/") and "GET" in rule.methods
    }
    assert not (
        registered - api_server._PRIVATE_READ_ROUTES - public_or_separately_guarded
    )
    assert api_server._PRIVATE_READ_ROUTES.isdisjoint(public_or_separately_guarded)


def test_parameterized_safety_record_requires_local_credential():
    client, loopback = _api_client()
    rule = next(
        rule
        for rule in api_server.app.url_map.iter_rules()
        if rule.rule == "/api/safety/quarantine/<quarantine_id>"
    )
    handler = MagicMock(return_value={"probe": True})
    path = "/api/safety/quarantine/probe-id"
    with patch.dict(api_server.app.view_functions, {rule.endpoint: handler}):
        assert client.get(path, environ_base=loopback).status_code == 401
        assert client.head(path, environ_base=loopback).status_code == 401
        handler.assert_not_called()
        allowed = client.get(
            path,
            environ_base=loopback,
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        )
        assert allowed.status_code == 200
        handler.assert_called_once()


def test_runtime_health_get_cannot_trigger_auto_repair():
    client, loopback = _api_client()
    auth = {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}
    with patch("bot_health.run_runtime_checks") as checks:
        response = client.get(
            "/api/health/runtime?repair=true&force=true",
            headers=auth,
            environ_base=loopback,
        )
    assert response.status_code == 400
    assert response.get_json() == {"error": "repair_requires_internal_cycle"}
    checks.assert_not_called()

    with patch(
        "bot_health.run_runtime_checks",
        return_value=SimpleNamespace(to_dict=lambda: {"healthy": True}),
    ) as checks:
        response = client.get(
            "/api/health/runtime?repair=false&force=true",
            headers=auth,
            environ_base=loopback,
        )
    assert response.status_code == 200
    checks.assert_called_once_with(auto_repair=False, force=True)


def test_disabled_debug_handlers_fail_closed_without_request_guard():
    handlers = (
        ("/api/debug/coinprep", market_routes.api_debug_coinprep, "GET"),
        ("/api/debug/pricing", market_routes.api_debug_pricing, "GET"),
        (
            "/api/debug/sage-single-offer-test",
            market_routes.api_debug_sage_single_offer_test,
            "POST",
        ),
    )
    with (
        patch.object(api_server, "bot", None),
        patch("requests.get", side_effect=RuntimeError("unexpected network access")),
        patch(
            "wallet.get_wallet_type",
            side_effect=AssertionError("debug handler touched wallet"),
        ),
    ):
        for path, handler, method in handlers:
            with api_server.app.test_request_context(path, method=method):
                result = handler()
            response, status = result if isinstance(result, tuple) else (result, 200)
            assert status == 404, path
            assert response.get_json()["error"] == "debug_routes_disabled"


def test_config_change_address_result_hides_wallet_exception_details(monkeypatch):
    client, loopback = _api_client()
    auth = {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}
    fake_cfg = SimpleNamespace(
        SAGE_SET_CHANGE_ADDRESS=True,
        WALLET_ADDRESS="",
        update=lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(api_server, "cfg", fake_cfg)
    monkeypatch.setattr(config_bp, "cfg", fake_cfg)

    with (
        api_mutations_permitted(api_server),
        patch("wallet.get_wallet_type", return_value="sage"),
        patch(
            "wallet.get_next_address",
            return_value={"success": True, "address": "xch1safeaddress"},
        ),
        patch(
            "wallet.set_change_address",
            return_value={"success": False, "error": "secret change traceback"},
        ),
    ):
        resp = client.post(
            "/api/config",
            json={"key": "SAGE_SET_CHANGE_ADDRESS", "value": "true"},
            headers=auth,
            environ_base=loopback,
        )

    assert resp.status_code == 200
    assert "secret change traceback" not in resp.get_data(as_text=True).lower()


def test_splash_receive_node_action_hides_exception_details(monkeypatch):
    client, loopback = _api_client()
    auth = {"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN}
    splash_node = SimpleNamespace(
        is_running=lambda: False,
        start=lambda: (_ for _ in ()).throw(RuntimeError("secret splash traceback")),
    )
    bot = SimpleNamespace(
        splash_node=splash_node,
        get_splash_receive_stats=lambda: {"enabled": True},
    )
    fake_cfg = SimpleNamespace(
        SPLASH_ENABLED=True,
        update=lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(api_server, "cfg", fake_cfg)

    with api_mutations_permitted(api_server):
        resp = client.post(
            "/api/splash/receive",
            json={"enabled": True},
            headers=auth,
            environ_base=loopback,
        )

    assert resp.status_code == 200
    assert "secret splash traceback" not in resp.get_data(as_text=True).lower()


def test_client_safe_payload_removes_traceback_shaped_text():
    payload = {
        "success": True,
        "details": {
            "message": "Traceback (most recent call last): secret local path",
            "count": 3,
        },
    }

    safe = api_server._client_safe_payload(payload)

    assert safe["details"]["message"] == "Details unavailable"
    assert safe["details"]["count"] == 3
    assert "secret local path" not in str(safe).lower()


def test_status_prebot_response_hides_traceback_shaped_cached_values(monkeypatch):
    client, loopback = _api_client()
    asset_id = "ab" * 32
    monkeypatch.setattr(api_server, "bot", None)
    monkeypatch.setitem(api_server._active_cat, "asset_id", asset_id)
    monkeypatch.setitem(api_server._active_cat, "decimals", 3)
    monkeypatch.setattr(api_server.cfg, "CAT_ASSET_ID", asset_id, raising=False)
    monkeypatch.setattr(api_server.cfg, "CAT_DECIMALS", 3, raising=False)
    monkeypatch.setattr(
        bot_routes,
        "_prebot_price_cache",
        {
            "pricing": {
                "mid": "Traceback (most recent call last): secret price traceback",
                "bid": 0,
                "ask": 0,
            },
            "asset_id": asset_id,
            "fetched_at": time.time(),
        },
        raising=False,
    )

    with (
        patch("wallet.get_all_offers", return_value=[]),
        patch("wallet.get_spendable_coin_count", return_value=0),
        patch("chia_node.is_startup_authorised", return_value=False),
    ):
        resp = client.get(
            "/api/status",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            environ_base=loopback,
        )

    body = resp.get_data(as_text=True).lower()
    assert resp.status_code == 200
    assert "secret price traceback" not in body
    assert "traceback" not in body


def test_coin_prep_verify_response_hides_traceback_shaped_drift_details(monkeypatch):
    client, loopback = _api_client()
    monkeypatch.setitem(api_server._active_cat, "wallet_id", 2)
    monkeypatch.setitem(api_server._active_cat, "decimals", 3)

    drift = [
        {
            "tier": "inner",
            "side": "xch",
            "detail": "Traceback (most recent call last): secret drift traceback",
        }
    ]
    balance = {"wallet_balance": {"confirmed_wallet_balance": 0}}
    with (
        patch("wallet.get_wallet_balance", return_value=balance),
        patch(
            "wallet.get_spendable_coins_rpc",
            return_value={"success": True, "records": []},
        ),
        patch("coin_manager.check_tier_size_drift_standalone", return_value=drift),
    ):
        resp = client.get(
            "/api/coin-prep/verify",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            query_string={
                "tier_enabled": "true",
                "inner_xch": "1",
                "inner_cat": "10",
                "inner_count": "1",
            },
            environ_base=loopback,
        )

    body = resp.get_data(as_text=True).lower()
    assert resp.status_code == 200
    assert "secret drift traceback" not in body
    assert "traceback" not in body


def test_coin_prep_flat_verify_response_hides_traceback_shaped_values(monkeypatch):
    client, loopback = _api_client()
    monkeypatch.setitem(api_server._active_cat, "wallet_id", 2)
    monkeypatch.setitem(api_server._active_cat, "decimals", 3)

    malicious_balance = {
        "wallet_balance": {
            "confirmed_wallet_balance": (
                "Traceback (most recent call last): secret balance traceback"
            )
        }
    }
    malicious_coins = {
        "success": True,
        "records": [
            {
                "coin": {
                    "amount": "Traceback (most recent call last): secret coin traceback"
                }
            }
        ],
    }

    with (
        patch("wallet.get_wallet_balance", side_effect=[malicious_balance] * 2),
        patch("wallet.get_spendable_coins_rpc", side_effect=[malicious_coins] * 2),
        patch("wallet.WALLET_ID_XCH", 1),
        patch.object(coin_prep_routes.cfg, "CAT_DECIMALS", 3),
    ):
        resp = client.get(
            "/api/coin-prep/verify",
            headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
            query_string={
                "tier_enabled": "false",
                "liquidity_mode": (
                    "Traceback (most recent call last): secret mode traceback"
                ),
                "trade_size": (
                    "Traceback (most recent call last): secret trade traceback"
                ),
                "prepared_xch_size": (
                    "Traceback (most recent call last): secret xch traceback"
                ),
                "prepared_cat_size": (
                    "Traceback (most recent call last): secret cat traceback"
                ),
                "max_buy": "Traceback (most recent call last): secret buy traceback",
                "max_sell": "Traceback (most recent call last): secret sell traceback",
            },
            environ_base=loopback,
        )

    body = resp.get_data(as_text=True).lower()
    assert resp.status_code == 200
    assert resp.get_json()["liquidity_mode"] == "two_sided"
    assert "secret" not in body
    assert "traceback" not in body
