"""Regression coverage for the v1.3.13 post-prep price-request flood."""

from decimal import Decimal
from types import SimpleNamespace

import api_server
import coin_manager
import config
import database
import wallet
from blueprints import coin_prep as coin_prep_blueprint


class _TrackingPriceEngine:
    def __init__(self, cached_price=None):
        self.cached_price = cached_price
        self.fresh_calls = 0

    def get_last_price(self):
        return self.cached_price

    def get_price(self):
        self.fresh_calls += 1
        return {"mid_price": "0.000084116603"}


def _patch_tier_price_inputs(monkeypatch, price_engine):
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(price_engine=price_engine))
    monkeypatch.setattr(coin_manager.cfg, "TIER_ENABLED", True)
    monkeypatch.setattr(coin_manager.cfg, "LAST_QUOTED_MID", 0, raising=False)
    monkeypatch.setattr(config, "get_buy_tier_size_xch", lambda _tier: Decimal("0.1"))
    monkeypatch.setattr(config, "get_sell_tier_size_xch", lambda _tier: Decimal("0.1"))
    monkeypatch.delenv("_CLI_LIVE_PRICE", raising=False)


def test_completed_status_does_not_launch_fresh_market_price_requests(
    monkeypatch, tmp_path
):
    """Polling completed coin prep must stay local even when no price is cached."""

    class PriceEngine:
        def __init__(self):
            self.fresh_calls = 0

        def get_last_price(self):
            return None

        def get_price(self):
            self.fresh_calls += 1
            return {"mid_price": "0.000084116603"}

    price_engine = PriceEngine()
    bot = SimpleNamespace(price_engine=price_engine)
    completed_state = {
        "running": False,
        "complete": True,
        "phase": "complete",
        "progress": 1.0,
        "message": "Coin preparation complete",
        "xch_target": 127,
        "cat_target": 77,
        "run_id": "regression-run",
    }

    monkeypatch.setattr(api_server, "bot", bot)
    monkeypatch.setattr(coin_prep_blueprint.cfg, "TIER_ENABLED", True)
    monkeypatch.setattr(coin_prep_blueprint.cfg, "LAST_QUOTED_MID", 0, raising=False)
    monkeypatch.setattr(
        coin_prep_blueprint,
        "_coin_prep_status_file",
        lambda: str(tmp_path / "missing-status.json"),
    )
    monkeypatch.setattr(
        database,
        "get_coin_summary",
        lambda: {
            "xch_free_count": 128,
            "cat_free_count": 78,
            "xch_total": 128,
            "cat_total": 78,
        },
    )
    monkeypatch.setattr(database, "get_coins_by_designation", lambda *_args: [])
    monkeypatch.setattr(database, "get_events_since", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(database, "get_recent_events", lambda *_args, **_kwargs: [])

    with monkeypatch.context() as state_patch:
        state_patch.setattr(api_server, "_coin_prep_state", completed_state)
        with api_server.app.test_request_context("/api/coin-prep/status"):
            response = coin_prep_blueprint.api_coin_prep_status()

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["phase"] == "complete"
    assert price_engine.fresh_calls == 0


def test_cache_only_cat_tier_sizes_do_not_invent_a_placeholder_price(monkeypatch):
    """A local-only status check must omit CAT drift when no price is cached."""

    class PriceEngine:
        def __init__(self):
            self.fresh_calls = 0

        def get_last_price(self):
            return None

        def get_price(self):
            self.fresh_calls += 1
            return {"mid_price": "0.000084116603"}

    price_engine = PriceEngine()
    monkeypatch.setattr(api_server, "bot", SimpleNamespace(price_engine=price_engine))
    monkeypatch.setattr(coin_manager.cfg, "TIER_ENABLED", True)
    monkeypatch.setattr(coin_manager.cfg, "LAST_QUOTED_MID", 0, raising=False)
    monkeypatch.setattr(config, "get_sell_tier_size_xch", lambda _tier: Decimal("0.1"))
    monkeypatch.delenv("_CLI_LIVE_PRICE", raising=False)

    sizes = coin_manager.get_tier_sizes_mojos_from_cfg(
        is_cat=True, allow_fresh_price=False
    )

    assert sizes == {}
    assert price_engine.fresh_calls == 0


def test_completed_status_uses_cached_price_to_detect_cat_drift(monkeypatch, tmp_path):
    """Cache-only polling must retain CAT drift checks when a price is cached."""

    price_engine = _TrackingPriceEngine(cached_price=Decimal("0.001"))
    _patch_tier_price_inputs(monkeypatch, price_engine)
    monkeypatch.setattr(
        database,
        "get_coin_summary",
        lambda: {
            "xch_free_count": 0,
            "cat_free_count": 2,
            "xch_total": 0,
            "cat_total": 2,
        },
    )

    def designated(wallet_type, _designation, tier):
        if wallet_type == "cat" and tier == "inner":
            return [
                {"amount_mojos": 1, "status": "free"},
                {"amount_mojos": 1, "status": "free"},
            ]
        return []

    monkeypatch.setattr(database, "get_coins_by_designation", designated)
    monkeypatch.setattr(database, "get_events_since", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(database, "get_recent_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        coin_prep_blueprint,
        "_coin_prep_status_file",
        lambda: str(tmp_path / "missing-status.json"),
    )
    completed_state = {
        "running": False,
        "complete": True,
        "phase": "complete",
        "progress": 1.0,
        "message": "Coin preparation complete",
    }

    with monkeypatch.context() as state_patch:
        state_patch.setattr(api_server, "_coin_prep_state", completed_state)
        with api_server.app.test_request_context("/api/coin-prep/status"):
            response = coin_prep_blueprint.api_coin_prep_status()

    payload = response.get_json()
    assert payload["needs_coin_prep"] is True
    assert any(item["side"] == "cat" for item in payload["tier_size_drift"])
    assert price_engine.fresh_calls == 0


def test_explicit_coin_prep_verify_fetches_fresh_price_when_cache_empty(monkeypatch):
    """The explicit verify gate must remain authoritative during an outage test."""

    price_engine = _TrackingPriceEngine()
    _patch_tier_price_inputs(monkeypatch, price_engine)
    empty_coins = {"success": True, "records": []}
    enough_balance = {
        "wallet_balance": {
            "confirmed_wallet_balance": 10_000_000_000_000,
            "spendable_balance": 10_000_000_000_000,
        }
    }
    monkeypatch.setattr(
        wallet, "get_spendable_coins_rpc", lambda _wallet_id: empty_coins
    )
    monkeypatch.setattr(wallet, "get_wallet_balance", lambda _wallet_id: enough_balance)
    monkeypatch.setattr(wallet, "WALLET_ID_XCH", 1)
    monkeypatch.setattr(database, "get_coins_by_designation", lambda *_args: [])

    client = api_server.app.test_client()
    response = client.get(
        "/api/coin-prep/verify?tier_enabled=true"
        "&inner_xch=0.1&inner_cat=100&inner_count=2",
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert price_engine.fresh_calls == 1


def test_start_bot_gate_fetches_fresh_price_when_cache_empty(monkeypatch):
    """Start Bot must preserve its authoritative fresh-price drift gate."""

    price_engine = _TrackingPriceEngine()

    class Bot:
        def __init__(self):
            self.price_engine = price_engine
            self.started = False

        def is_running(self):
            return False

        def start(self):
            self.started = True
            return True

        def get_state(self):
            return {"running": False, "status": "idle"}

    bot = Bot()
    _patch_tier_price_inputs(monkeypatch, price_engine)
    monkeypatch.setattr(api_server, "bot", bot)
    start_cfg = SimpleNamespace(
        CAT_ASSET_ID="asset-id",
        SPREAD_BPS=Decimal("200"),
        HARD_MIN_PRICE_XCH=Decimal("0.000001"),
        HARD_MAX_PRICE_XCH=Decimal("1"),
        DYNAMIC_LIMIT_PCT=Decimal("10"),
        MAX_ACTIVE_BUY_OFFERS=1,
        MAX_ACTIVE_SELL_OFFERS=1,
        ENABLE_COIN_PREP=False,
        has_pending_restart_changes=lambda: False,
    )
    monkeypatch.setattr(api_server, "cfg", start_cfg)
    monkeypatch.setattr(database, "get_coins_by_designation", lambda *_args: [])
    monkeypatch.setattr(
        wallet,
        "get_wallet_sync_status",
        lambda: {"reachable": True, "sync_state": "synced"},
    )
    monkeypatch.setattr(
        wallet,
        "preflight_wallet_identity",
        lambda: {"success": True, "reason": "identity_verified"},
    )
    monkeypatch.setattr(api_server, "_get_sage_signing_block_reason", lambda: None)
    monkeypatch.setattr(api_server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(
        api_server.mutation_gate, "enter_mutation", lambda *_args, **_kwargs: "permit"
    )
    monkeypatch.setattr(
        api_server.mutation_gate, "exit_mutation", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(api_server, "_reset_runtime_session_stats", lambda: None)
    monkeypatch.setattr(api_server, "_fresh_start_clear", lambda: None)

    client = api_server.app.test_client()
    response = client.post(
        "/api/bot/start",
        headers={"X-Bot-Local-Token": api_server._LOCAL_API_TOKEN},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "started"
    assert bot.started is True
    assert price_engine.fresh_calls == 1
