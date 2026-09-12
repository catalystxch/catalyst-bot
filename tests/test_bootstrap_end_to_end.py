from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import inspect
from types import SimpleNamespace

from chia_rs import AugSchemeMPL, Program
from flask import Flask
import pytest

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapEvidence,
    CampaignSide,
    CampaignStage,
    CampaignStopReason,
    evaluate_bootstrap_campaign,
)
from bootstrap_manifest import verify_campaign_manifest
from bootstrap_proof import verify_participation_report
from bootstrap_runtime import (
    active_bootstrap_levels,
    derive_bootstrap_authoritative_evidence,
    derive_bootstrap_runtime,
    plan_bootstrap_state_update,
    superseded_bootstrap_trade_ids,
)
from bot_loop import (
    BotLoop,
    plan_bootstrap_cycle_mutations,
    plan_bootstrap_runtime_transition,
)
import api_server  # noqa: F401 - establishes blueprint import order
from blueprints.coin_prep import (
    _active_bootstrap_coin_prep_worker_args,
    bootstrap_coin_prep_requirements,
    bootstrap_coin_prep_worker_args,
)
from coin_prep_worker import CoinPrepWorker, tier_requires_split
import database
from fill_tracker import derive_bootstrap_settlement_evidence
from offer_book_policy import derive_bootstrap_plan
from offer_manager import (
    OfferManager,
    bootstrap_offer_specs,
    require_active_bootstrap_intent_authority,
)
from offer_reconciliation import plan_bootstrap_restart_recovery
from walletconnect_signing import (
    SigningError,
    WalletConnectSigningService,
    WalletIdentity,
)


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ASSET_ID = "b8" * 32
ADDRESS = "xch1" + "q" * 58


def _request(**overrides):
    body = {
        "asset_id": ASSET_ID,
        "ticker": "NEWCAT",
        "anchor_price": "0.001",
        "xch_budget": "1",
        "cat_budget": "1000",
        "fee_budget_xch": "0.05",
        "subsidy_budget_xch": "0",
        "expires_in_seconds": 604800,
        "balances": {
            "xch_available": "2",
            "cat_available": "2000",
            "fee_spent_xch": "0",
            "subsidy_spent_xch": "0",
            "network_fee_xch": "0.00001",
            "minimum_profit_xch": "0",
            "fee_coin_size_xch": "0.001",
            "expected_cancel_requotes": 1,
        },
    }
    body.update(overrides)
    return body


@pytest.fixture
def bootstrap_app(tmp_path, monkeypatch):
    from blueprints import bootstrap

    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bootstrap-e2e.db"))
    monkeypatch.setattr(database, "_db_initialized_path", "")
    database.init_database()
    identity = {
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_fingerprint": 736588221,
        "wallet_id": 2,
        "asset_id": ASSET_ID,
        "ticker": "NEWCAT",
        "has_secrets": True,
    }
    clock = {"now": NOW}
    monkeypatch.setattr(bootstrap, "_read_bootstrap_identity", lambda: dict(identity))
    monkeypatch.setattr(bootstrap, "_utcnow", lambda: clock["now"])
    app = Flask(__name__)
    app.register_blueprint(bootstrap.bp)
    app.config.update(TESTING=True)
    yield bootstrap, app.test_client(), identity, clock
    database.close_connection()


def _campaign_from_record(record):
    def timestamp(value):
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")

    return BootstrapCampaign(
        network=record["network"],
        wallet_type=record["wallet_type"],
        wallet_fingerprint=record["wallet_fingerprint"],
        wallet_id=record["wallet_id"],
        asset_id=record["asset_id"],
        anchor_price=Decimal(record["anchor_price"]),
        minimum_price=Decimal(record["minimum_price"]),
        maximum_price=Decimal(record["maximum_price"]),
        xch_budget=Decimal(record["xch_budget"]),
        cat_budget=Decimal(record["cat_budget"]),
        fee_budget_xch=Decimal(record["fee_budget_xch"]),
        subsidy_budget_xch=Decimal(record["subsidy_budget_xch"]),
        created_at=timestamp(record["created_at"]),
        expires_at=timestamp(record["expires_at"]),
    )


def _balances(**overrides):
    values = {
        "xch_available": Decimal("2"),
        "cat_available": Decimal("2000"),
        "fee_spent_xch": Decimal("0"),
        "subsidy_spent_xch": Decimal("0"),
        "network_fee_xch": Decimal("0.00001"),
        "minimum_profit_xch": Decimal("0"),
        "fee_coin_size_xch": Decimal("0.001"),
        "expected_cancel_requotes": 1,
    }
    values.update(overrides)
    return values


def _walletconnect_response(request, *, account=None):
    secret_key = AugSchemeMPL.key_gen(b"bootstrap e2e wallet signature" + b"\0" * 4)
    message = bytes.fromhex(request.message.removeprefix("0x"))
    tree_hash = bytes(Program.to((b"Chia Signed Message", message)).get_tree_hash())
    return {
        "requestId": request.request_id,
        "account": account or request.account,
        "address": request.signing_address,
        "messageDigest": request.message_digest,
        "publicKey": bytes(secret_key.get_g1()).hex(),
        "signature": bytes(AugSchemeMPL.sign(secret_key, tree_hash)).hex(),
    }


def test_mock_wallet_campaign_runs_from_confirmation_to_cancel_and_restart(
    bootstrap_app, monkeypatch
):
    bootstrap, client, identity, _clock = bootstrap_app

    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    unconfirmed = client.post(
        "/api/bootstrap/start",
        json=_request(preview_digest=preview["preview_digest"]),
    )
    assert unconfirmed.status_code == 400
    assert unconfirmed.get_json()["code"] == "exact_asset_confirmation_required"

    started = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()
    campaign_id = started["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)
    campaign = _campaign_from_record(record)
    decision = evaluate_bootstrap_campaign(campaign, BootstrapEvidence(), now=NOW)
    plan = derive_bootstrap_plan(campaign, decision, _balances())
    prep = bootstrap_coin_prep_requirements(plan)
    specs = bootstrap_offer_specs(plan, campaign_authority=record)

    assert started["financial_action_started"] is False
    assert len(prep["xch_offer_coins"]) == 3
    assert len(prep["cat_offer_coins"]) == 3
    assert len(prep["fee_coins"]) == 6
    assert prep["excluded_xch"]["cancellation_fee_reserve_xch"] == Decimal("0.01")
    assert len(specs) == 6
    assert {spec["side"] for spec in specs} == {"buy", "sell"}
    assert all(spec["campaign_id"] == campaign_id for spec in specs)

    # The mock wallet and public index preserve the same exact campaign-bound IDs.
    wallet_offers = {
        hashlib.sha256(f"wallet:{index}".encode()).hexdigest(): spec
        for index, spec in enumerate(specs)
    }
    public_discovery = set(wallet_offers)
    assert public_discovery == set(wallet_offers)
    monkeypatch.setattr(
        "offer_manager.database.get_bootstrap_campaign",
        lambda exact_id: record if exact_id == campaign_id else None,
    )
    for spec in wallet_offers.values():
        assert require_active_bootstrap_intent_authority(
            purpose=spec["purpose"], asset_id=ASSET_ID, now=NOW
        ) == {
            "campaign_id": campaign_id,
            "campaign_revision": 0,
            "status": "active",
        }

    cancelled = []
    monkeypatch.setattr(
        bootstrap, "_campaign_trade_ids", lambda _id: sorted(wallet_offers)
    )
    monkeypatch.setattr(
        bootstrap,
        "_cancel_campaign_offers",
        lambda trade_ids: {
            trade_id: {"outcome": "CANCEL_SUBMITTED"}
            for trade_id in (cancelled.extend(trade_ids) or trade_ids)
        },
    )
    stopped = client.post(
        "/api/bootstrap/stop",
        json={"campaign_id": campaign_id, "revision": 0},
    ).get_json()
    assert stopped["cancel_targets"] == 6
    assert cancelled == sorted(wallet_offers)

    stopped_record = database.get_bootstrap_campaign(campaign_id)
    recovery = plan_bootstrap_restart_recovery(
        campaign_record=stopped_record,
        unresolved_trade_ids=tuple(cancelled[:2]),
    )
    transition = plan_bootstrap_runtime_transition(
        campaign_record=stopped_record,
        decision=decision,
        unresolved_cancellation_count=2,
    )
    assert recovery["action"] == "resume_cancellation"
    assert recovery["allow_replacement"] is False
    assert transition["allow_create"] is False
    assert transition["cancel_required"] is True
    assert identity["wallet_fingerprint"] == 736588221


def test_bootstrap_coin_prep_uses_exact_campaign_outputs_including_single_coins(
    bootstrap_app,
):
    _bootstrap, client, _identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)
    runtime = derive_bootstrap_runtime(
        campaign_record=record,
        identity={
            key: record[key]
            for key in (
                "network",
                "wallet_type",
                "wallet_fingerprint",
                "wallet_id",
                "asset_id",
            )
        },
        balances=_balances(),
        now=NOW,
    )

    args = bootstrap_coin_prep_worker_args(runtime["plan"])

    assert args == {
        "xch_target": 9,
        "cat_target": 3,
        "buy_tier_sizes": "inner=0.03333333333333333333333333333,mid=0.03333333333333333333333333333,outer=0.03333333333333333333333333334,fees=0.001",
        "cat_tier_sizes": "inner=33.33333333333333333333333333,mid=33.33333333333333333333333333,outer=33.33333333333333333333333334",
        "tier_counts_xch": "inner=1,mid=1,outer=1,fees=6",
        "tier_counts_cat": "inner=1,mid=1,outer=1",
        "prep_headroom_pct": "0",
    }
    assert tier_requires_split(1) is False
    assert tier_requires_split(2) is True

    precision_worker = object.__new__(CoinPrepWorker)
    precision_worker.coin_prep_headroom_multiplier = Decimal("1")
    prepared_xch = {
        tier: precision_worker._apply_prep_headroom_xch(amount)
        for tier, amount in {
            "inner": Decimal("0.03333333333333333333333333333"),
            "mid": Decimal("0.03333333333333333333333333333"),
            "outer": Decimal("0.03333333333333333333333333334"),
        }.items()
    }
    assert prepared_xch == {
        "inner": Decimal("0.033333333333"),
        "mid": Decimal("0.033333333333"),
        "outer": Decimal("0.033333333333"),
    }
    assert all(
        int(prepared_xch[tier] * Decimal("1000000000000"))
        >= int(live_size * Decimal("1000000000000"))
        for tier, live_size in {
            "inner": Decimal("0.03333333333333333333333333333"),
            "mid": Decimal("0.03333333333333333333333333333"),
            "outer": Decimal("0.03333333333333333333333333334"),
        }.items()
    )

    worker = object.__new__(CoinPrepWorker)
    worker.coin_prep_headroom_multiplier = Decimal("1")
    worker.cat_decimals = 3
    worker.offer_tier_xch_sizes_sell = {
        "inner": Decimal("0.04"),
        "mid": Decimal("0.03"),
        "outer": Decimal("0.03"),
    }
    worker.offer_tier_xch_sizes = dict(worker.offer_tier_xch_sizes_sell)
    worker.tier_xch_sizes = dict(worker.offer_tier_xch_sizes_sell)
    worker.cat_tier_counts = {"inner": 1, "mid": 1, "outer": 1}
    worker.log = lambda *_args, **_kwargs: None
    worker._get_live_price = lambda: pytest.fail(
        "exact Bootstrap CAT sizes must not call an external price source"
    )
    worker.exact_tier_cat_sizes = {
        "inner": Decimal("40"),
        "mid": Decimal("30"),
        "outer": Decimal("30"),
    }
    assert worker._derive_tier_cat_sizes() == worker.exact_tier_cat_sizes


def test_bootstrap_coin_prep_converts_unavailable_identity_to_stable_safe_block(
    bootstrap_app, monkeypatch
):
    from blueprints import bootstrap

    _bootstrap, client, _identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    started = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()
    monkeypatch.setattr(
        bootstrap,
        "_read_bootstrap_identity",
        lambda: (_ for _ in ()).throw(
            bootstrap.BootstrapApiError("wallet_identity_unavailable", 409)
        ),
    )
    monkeypatch.setattr("blueprints.coin_prep.cfg.CAT_ASSET_ID", ASSET_ID)

    with pytest.raises(ValueError, match="^bootstrap_wallet_identity_unavailable$"):
        _active_bootstrap_coin_prep_worker_args(
            {
                "bootstrap_campaign_id": started["campaign_id"],
                "bootstrap_campaign_revision": 0,
            }
        )


def test_offer_manager_executes_only_the_exact_campaign_plan(bootstrap_app):
    _bootstrap, client, _identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)
    campaign = _campaign_from_record(record)
    decision = evaluate_bootstrap_campaign(campaign, BootstrapEvidence(), now=NOW)
    plan = derive_bootstrap_plan(campaign, decision, _balances())

    calls = []
    manager = object.__new__(OfferManager)

    def create(offer_dict, **kwargs):
        calls.append((offer_dict, kwargs))
        return {
            "success": True,
            "trade_id": hashlib.sha256(str(len(calls)).encode()).hexdigest(),
            "offer_bech32": f"offer1mock{len(calls)}",
        }

    manager.create_offer_with_retry = create
    created = manager.create_bootstrap_plan(
        plan,
        campaign_authority=record,
        xch_wallet_id=1,
        cat_wallet_id=2,
        cat_decimals=3,
        coin_ids_enabled=True,
    )

    assert len(created) == len(calls) == 6
    assert all(
        len([amount for amount in offer.values() if amount < 0]) == 1
        for offer, _ in calls
    )
    assert all(
        len([amount for amount in offer.values() if amount > 0]) == 1
        for offer, _ in calls
    )
    assert {kwargs["creation_context"]["side"] for _offer, kwargs in calls} == {
        "buy",
        "sell",
    }
    assert all(
        kwargs["creation_context"]["purpose"] == f"bootstrap:{campaign_id}:revision:0"
        for _offer, kwargs in calls
    )
    assert all(kwargs["coin_ids_enabled"] is True for _offer, kwargs in calls)


def test_bootstrap_offer_is_projected_before_it_can_be_published(
    bootstrap_app, monkeypatch
):
    _bootstrap, client, _identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)
    campaign = _campaign_from_record(record)
    decision = evaluate_bootstrap_campaign(campaign, BootstrapEvidence(), now=NOW)
    plan = derive_bootstrap_plan(campaign, decision, _balances())

    projected = []
    cached = []
    locked = []
    manager = OfferManager()

    def create(_offer_dict, **_kwargs):
        index = len(projected) + 1
        trade_id = hashlib.sha256(f"bootstrap-{index}".encode()).hexdigest()
        return {
            "success": True,
            "trade_id": trade_id,
            "offer": f"offer1bootstrap{index}",
            "locked_coin_id": hashlib.sha256(f"coin-{index}".encode()).hexdigest(),
            "offer_max_time": int(NOW.timestamp()) + 86_400,
            "_catalyst_locked_input_verification": {
                "verified": True,
                "selected_present": True,
                "locked_coin_ids": [
                    hashlib.sha256(f"coin-{index}".encode()).hexdigest()
                ],
            },
        }

    manager.create_offer_with_retry = create
    monkeypatch.setattr(
        "offer_manager.add_offer",
        lambda **kwargs: projected.append(kwargs) or True,
    )
    monkeypatch.setattr(
        "offer_manager.update_offer_bech32",
        lambda trade_id, offer: cached.append((trade_id, offer)) or True,
    )
    monkeypatch.setattr(
        "offer_manager.lock_coin",
        lambda coin_id, trade_id: locked.append((coin_id, trade_id)) or True,
    )

    created = manager.create_bootstrap_plan(
        plan,
        campaign_authority=record,
        xch_wallet_id=1,
        cat_wallet_id=2,
        cat_decimals=3,
        coin_ids_enabled=True,
    )

    assert len(created) == len(projected) == len(cached) == 6
    assert len(locked) == 6
    for result, projection, (cached_trade_id, cached_offer) in zip(
        created, projected, cached
    ):
        assert projection["trade_id"] == result["trade_id"] == cached_trade_id
        assert projection["side"] == result["side"]
        assert projection["price_xch"] == result["price"]
        assert projection["size_xch"] == result["size_xch"]
        assert projection["size_cat"] > Decimal("0")
        assert projection["cat_asset_id"] == ASSET_ID
        assert projection["coin_id"] == result["locked_coin_id"]
        assert cached_offer.startswith("offer1bootstrap")


def test_bootstrap_offer_rejects_a_mismatched_existing_projection(
    bootstrap_app, monkeypatch
):
    _bootstrap, client, _identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)
    campaign = _campaign_from_record(record)
    decision = evaluate_bootstrap_campaign(campaign, BootstrapEvidence(), now=NOW)
    plan = derive_bootstrap_plan(campaign, decision, _balances())

    trade_id = hashlib.sha256(b"mismatched-projection").hexdigest()
    coin_id = hashlib.sha256(b"mismatched-coin").hexdigest()
    manager = OfferManager()
    manager.create_offer_with_retry = lambda *_args, **_kwargs: {
        "success": True,
        "trade_id": trade_id,
        "offer": "offer1mismatched",
        "locked_coin_id": coin_id,
    }
    cancelled = []
    manager.cancel_offers = lambda trade_ids, **_kwargs: cancelled.extend(trade_ids)
    cached = []
    monkeypatch.setattr(
        "offer_manager.database.get_offer",
        lambda _trade_id: {
            "trade_id": trade_id,
            "status": "open",
            "side": "buy",
            "cat_asset_id": ASSET_ID,
            "price_xch": "999",
            "size_xch": "999",
            "size_cat": "999",
            "tier": "wrong",
            "coin_id": "ff" * 32,
        },
    )
    monkeypatch.setattr(
        "offer_manager.update_offer_bech32",
        lambda *args: cached.append(args) or True,
    )

    created = manager.create_bootstrap_plan(
        plan,
        campaign_authority=record,
        xch_wallet_id=1,
        cat_wallet_id=2,
        cat_decimals=3,
        coin_ids_enabled=True,
    )

    assert created == []
    assert cancelled == [trade_id] * 6
    assert cached == []


def test_runtime_binds_exact_identity_and_only_creates_missing_levels(bootstrap_app):
    _bootstrap, client, identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)

    runtime = derive_bootstrap_runtime(
        campaign_record=record,
        identity={
            key: identity[key]
            for key in (
                "network",
                "wallet_type",
                "wallet_fingerprint",
                "wallet_id",
                "asset_id",
            )
        },
        balances=_balances(),
        now=NOW,
    )
    assert runtime["authority"]["allowed"] is True
    assert runtime["authority"]["mode"] == "bootstrap"
    assert runtime["transition"]["allow_create"] is True
    assert runtime["plan"]["authorized"] is True

    purpose = f"bootstrap:{campaign_id}:revision:0"
    existing = active_bootstrap_levels(
        [
            {
                "purpose": purpose,
                "slot_key": f"bootstrap:{campaign_id}:0:buy:near",
                "lifecycle_state": "visible",
            },
            {
                "purpose": purpose,
                "slot_key": f"bootstrap:{campaign_id}:0:sell:middle",
                "lifecycle_state": "created",
            },
            {
                "purpose": purpose,
                "slot_key": f"bootstrap:{campaign_id}:0:buy:far",
                "lifecycle_state": "cancelled",
            },
        ],
        campaign_id=campaign_id,
        revision=0,
    )
    assert existing == frozenset({("buy", "near"), ("sell", "middle")})

    calls = []
    manager = object.__new__(OfferManager)
    manager.create_offer_with_retry = lambda offer, **kwargs: (
        calls.append((offer, kwargs))
        or {
            "success": True,
            "trade_id": hashlib.sha256(str(len(calls)).encode()).hexdigest(),
            "offer_bech32": f"offer1missing{len(calls)}",
        }
    )
    created = manager.create_bootstrap_plan(
        runtime["plan"],
        campaign_authority=record,
        xch_wallet_id=1,
        cat_wallet_id=2,
        cat_decimals=3,
        coin_ids_enabled=True,
        existing_levels=existing,
    )
    assert len(created) == 4
    assert {(item["side"], item["level"]) for item in created} == {
        ("buy", "middle"),
        ("buy", "far"),
        ("sell", "near"),
        ("sell", "far"),
    }

    with pytest.raises(ValueError, match="identity"):
        derive_bootstrap_runtime(
            campaign_record=record,
            identity={**identity, "wallet_fingerprint": 999},
            balances=_balances(),
            now=NOW,
        )


def test_live_bot_routes_bootstrap_before_follow_creation_and_requote():
    loop = object.__new__(BotLoop)
    loop._enter_runtime_effect_phase = lambda phase: phase == "create"
    routed = {
        "buy": {"bootstrap-buy"},
        "sell": {"bootstrap-sell"},
    }
    loop._route_bootstrap_creation_if_active = lambda **_kwargs: routed

    assert loop._create_offers_if_needed(Decimal("1"), 0, 0) is routed

    create_source = inspect.getsource(BotLoop._create_offers_if_needed)
    requote_source = inspect.getsource(BotLoop._handle_requoting)
    assert create_source.index("_route_bootstrap_creation_if_active") < (
        create_source.index("unsuspend_slots_if_coins_available")
    )
    assert "_bootstrap_campaign_blocks_follow_mutations" in requote_source


def test_bootstrap_startup_skips_legacy_tier_readiness(monkeypatch):
    loop = object.__new__(BotLoop)
    loop._bootstrap_campaign_context = lambda: {
        "active": True,
        "blocked": False,
        "campaign": {"campaign_id": "campaign-1", "revision": 2},
    }
    loop.coin_manager = type(
        "CoinManager",
        (),
        {
            "coin_readiness_report": lambda _self: (_ for _ in ()).throw(
                AssertionError("legacy tier readiness must not run for Bootstrap")
            )
        },
    )()
    events = []
    monkeypatch.setattr(
        "bot_loop.log_event",
        lambda level, event_type, message, data=None: events.append(
            (level, event_type, message, data)
        ),
    )

    readiness = loop._startup_coin_readiness_report()

    assert readiness is None
    assert events == [
        (
            "info",
            "bootstrap_exact_coin_readiness",
            "Market Bootstrap uses its exact campaign Coin Prep plan; legacy tier targets do not apply",
            {"campaign_id": "campaign-1", "revision": 2},
        )
    ]


def test_active_bootstrap_suppresses_follow_churn_but_keeps_safety_and_recovery():
    policy = plan_bootstrap_cycle_mutations(bootstrap_active=True)

    assert policy == {
        "toxicity_cancel": False,
        "expiry_refresh": False,
        "emergency_requote": False,
        "sniper_cleanup": False,
        "boost_mutation": False,
        "follow_requote": False,
        "follow_trim": False,
        "follow_recovery_evaluation": False,
        "legacy_coin_topup": False,
        "safety_cancel": True,
        "cancel_retry": True,
        "bootstrap_create": True,
        "publication_reconcile": True,
        "fill_reconcile": True,
    }
    assert all(plan_bootstrap_cycle_mutations(bootstrap_active=False).values())

    loop = object.__new__(BotLoop)
    loop.coin_manager = SimpleNamespace(
        check_coin_prep_status=lambda: {"cancelled_ids": []}
    )
    loop.offer_manager = SimpleNamespace(_bot_cancelled_ids=set())
    loop._enter_runtime_effect_phase = lambda _phase: pytest.fail(
        "Bootstrap must not enter legacy Coin Prep/top-up mutation authority"
    )
    loop._reclaim_oversized_locked_offers = lambda: pytest.fail(
        "Bootstrap must not cancel campaign offers for legacy coin reshaping"
    )
    loop._handle_coins(0, 0, allow_legacy_topup=False)


def test_live_bot_executes_active_bootstrap_and_queues_publication(
    bootstrap_app, monkeypatch
):
    _bootstrap, client, _identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)

    import bot_loop
    import tx_fees
    import wallet

    monkeypatch.setattr(bot_loop.cfg, "CAT_ASSET_ID", ASSET_ID, raising=False)
    monkeypatch.setattr(bot_loop.cfg, "CAT_WALLET_ID", 2, raising=False)
    monkeypatch.setattr(bot_loop.cfg, "WALLET_ID_XCH", 1, raising=False)
    monkeypatch.setattr(bot_loop.cfg, "CAT_DECIMALS", 3, raising=False)
    monkeypatch.setattr(bot_loop.cfg, "COIN_IDS_ENABLED", True, raising=False)
    monkeypatch.setattr(bot_loop.cfg, "SPLASH_ENABLED", True, raising=False)
    monkeypatch.setattr(
        bot_loop.cfg, "FEE_COIN_SIZE_XCH", Decimal("0.001"), raising=False
    )
    monkeypatch.setattr(bot_loop.cfg, "MINIMUM_PROFIT_XCH", Decimal("0"), raising=False)
    monkeypatch.setattr(bot_loop.cfg, "EXPECTED_CANCEL_REQUOTES", 1, raising=False)
    monkeypatch.setattr(
        bot_loop.database,
        "list_active_bootstrap_campaigns_for_asset",
        lambda asset_id: [record] if asset_id == ASSET_ID else [],
    )
    monkeypatch.setattr(bot_loop.database, "get_offer_intents_for_registry", lambda: [])
    monkeypatch.setattr(
        wallet,
        "get_wallet_identity",
        lambda: {
            "success": True,
            "backend": "sage",
            "fingerprint": 736588221,
            "network_id": "mainnet",
            "has_secrets": True,
        },
    )
    monkeypatch.setattr(
        wallet,
        "get_wallet_balance",
        lambda wallet_id: {
            "success": True,
            "wallet_balance": {
                "spendable_balance": 20_000_000_000 if wallet_id == 1 else 20_000,
                "confirmed_wallet_balance": 2_000_000_000_000
                if wallet_id == 1
                else 2_000_000,
            },
        },
    )
    monkeypatch.setattr(
        wallet,
        "get_wallet_puzzle_hashes",
        lambda: {"99" * 32},
    )
    monkeypatch.setattr(bot_loop.database, "get_fills", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        tx_fees, "get_effective_transaction_fee_mojos", lambda: 10_000_000
    )

    created_call = {}
    queued_dexie = []
    queued_splash = []
    loop = object.__new__(BotLoop)
    loop._publication_discovery_pending = 0
    loop._last_bulk_create_time = 0
    loop._market_confidence_result = SimpleNamespace(
        data_valid=True,
        trusted_midpoint=Decimal("0.001"),
        trusted_bid=Decimal("0.00096"),
        trusted_ask=Decimal("0.00104"),
        independent_bid_depth_mojos=0,
        independent_ask_depth_mojos=0,
        required_depth_mojos=1,
    )
    loop.coin_manager = SimpleNamespace(
        is_busy=lambda: False,
        snapshot_coins=lambda reason: created_call.setdefault("snapshot", reason),
    )
    loop.offer_manager = SimpleNamespace(
        create_bootstrap_plan=lambda plan, **kwargs: (
            created_call.update(plan=plan, kwargs=kwargs)
            or [
                {
                    "success": True,
                    "side": "buy",
                    "level": "near",
                    "trade_id": "61" * 32,
                    "offer_bech32": "offer1bootstrap",
                }
            ]
        )
    )
    loop.dexie_manager = SimpleNamespace(
        queue_post=lambda offer, trade_id: queued_dexie.append((offer, trade_id))
    )
    loop.splash_manager = SimpleNamespace(
        queue_post=lambda offer, trade_id: queued_splash.append((offer, trade_id))
    )
    loop._emit_coin_update = lambda reason: created_call.setdefault("emit", reason)

    result = loop._route_bootstrap_creation_if_active(
        current_buy_ids=set(), current_sell_ids=set()
    )
    assert result == {"buy": {"61" * 32}, "sell": set()}
    assert created_call["kwargs"]["existing_levels"] == frozenset()
    assert sum(
        level["xch_amount"] for level in created_call["plan"]["sides"]["buy"]["levels"]
    ) == Decimal("0.1")
    assert max(
        level["price"] for level in created_call["plan"]["sides"]["buy"]["levels"]
    ) <= Decimal("0.00096")
    assert min(
        level["price"] for level in created_call["plan"]["sides"]["sell"]["levels"]
    ) >= Decimal("0.00104")
    assert queued_dexie == [("offer1bootstrap", "61" * 32)]
    assert queued_splash == queued_dexie


def test_live_bot_finalizes_automatic_bootstrap_stop_after_offer_clearance(monkeypatch):
    import bot_loop
    import tx_fees
    import wallet

    campaign = {
        "campaign_id": "31" * 32,
        "revision": 4,
    }
    stopped = []
    events = []
    monkeypatch.setattr(
        wallet,
        "get_wallet_balance",
        lambda wallet_id: {
            "success": True,
            "wallet_balance": {
                "confirmed_wallet_balance": 1_000_000_000_000
                if wallet_id == 1
                else 1_000,
            },
        },
    )
    monkeypatch.setattr(
        tx_fees, "get_effective_transaction_fee_mojos", lambda: 10_000_000
    )
    monkeypatch.setattr(bot_loop.database, "get_offer_intents_for_registry", lambda: [])
    monkeypatch.setattr(
        bot_loop.database,
        "stop_bootstrap_campaign",
        lambda campaign_id, reason, stopped_at: (
            stopped.append((campaign_id, reason, stopped_at)) or True
        ),
    )
    monkeypatch.setattr(
        bot_loop.database,
        "append_bootstrap_campaign_event",
        lambda record: events.append(record) or "event-id",
    )

    loop = object.__new__(BotLoop)
    loop._publication_discovery_pending = 0
    loop._market_confidence_result = None
    loop.coin_manager = SimpleNamespace(is_busy=lambda: False)
    loop.offer_manager = SimpleNamespace(
        cancel_offers=lambda *_args, **_kwargs: pytest.fail(
            "no cancellation call is needed after authoritative offer clearance"
        )
    )
    loop._bootstrap_campaign_context = lambda: {
        "active": True,
        "blocked": False,
        "campaign": campaign,
        "identity": {},
    }
    loop._refresh_bootstrap_campaign_evidence = lambda **_kwargs: {
        "campaign": campaign,
        "runtime": {
            "transition": {
                "cancel_required": True,
                "cancel_reason": "bootstrap_expired",
            },
            "decision": SimpleNamespace(
                stop_reason=CampaignStopReason.EXPIRED,
            ),
        },
        "changed": False,
    }

    result = loop._route_bootstrap_creation_if_active(
        current_buy_ids=set(), current_sell_ids=set()
    )

    assert result == {"buy": set(), "sell": set()}
    assert [(campaign_id, reason) for campaign_id, reason, _at in stopped] == [
        ("31" * 32, "expired")
    ]
    assert events[0]["event_type"] == "campaign_stopped"
    assert events[0]["data"] == {
        "reason": "expired",
        "cancel_targets": [],
        "automatic": True,
    }


def test_stages_inventory_anchor_cooldown_and_stops_remain_bounded(bootstrap_app):
    _bootstrap, client, _identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    campaign = _campaign_from_record(database.get_bootstrap_campaign(campaign_id))

    for fills, clusters, stable, stage, fraction in (
        (0, 0, 0, CampaignStage.BOOTSTRAP, Decimal("0.10")),
        (2, 2, 0, CampaignStage.DISCOVERY_25, Decimal("0.25")),
        (6, 3, 30, CampaignStage.DISCOVERY_50, Decimal("0.50")),
        (12, 5, 120, CampaignStage.ESTABLISHED, Decimal("1")),
    ):
        evidence = BootstrapEvidence(
            confirmed_fills=fills,
            settlement_clusters=clusters,
            independent_depth_sides=frozenset({CampaignSide.BUY, CampaignSide.SELL}),
            stable_since=NOW - timedelta(minutes=stable),
        )
        decision = evaluate_bootstrap_campaign(campaign, evidence, now=NOW)
        assert (decision.stage, decision.deployment_fraction) == (stage, fraction)

    capped = evaluate_bootstrap_campaign(
        campaign,
        BootstrapEvidence(
            current_anchor_price=Decimal("0.001"),
            proposed_anchor_price=Decimal("0.002"),
            anchor_price_one_hour_ago=Decimal("0.001"),
            anchor_price_one_day_ago=Decimal("0.001"),
            adverse_fill_times=((CampaignSide.SELL, NOW - timedelta(minutes=4)),),
        ),
        now=NOW,
    )
    skewed_plan = derive_bootstrap_plan(
        campaign,
        capped,
        _balances(xch_available=Decimal("0.05"), cat_available=Decimal("2000")),
    )
    assert capped.anchor_price == Decimal("0.00105")
    assert capped.cooldown_sides == frozenset({CampaignSide.SELL})
    assert skewed_plan["sides"]["sell"]["levels"] == []
    assert skewed_plan["sides"]["buy"]["levels"]

    own_and_linked_rows = [
        {
            "campaign_id": campaign_id,
            "trade_id": "01" * 32,
            "settlement_identity": "11" * 32,
            "participant_cluster": "external-a",
            "side": "buy",
            "filled_at": "2026-09-12T11:50:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000000,
            "receive_coin_id": "21" * 32,
            "independent_depth": True,
            "adverse": False,
        },
        {
            "campaign_id": campaign_id,
            "trade_id": "02" * 32,
            "settlement_identity": "12" * 32,
            "participant_cluster": "own",
            "side": "sell",
            "filled_at": "2026-09-12T11:51:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000001,
            "receive_coin_id": "22" * 32,
            "independent_depth": True,
            "adverse": False,
        },
        {
            "campaign_id": campaign_id,
            "trade_id": "03" * 32,
            "settlement_identity": "13" * 32,
            "participant_cluster": "linked",
            "side": "sell",
            "filled_at": "2026-09-12T11:52:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000002,
            "receive_coin_id": "23" * 32,
            "independent_depth": True,
            "adverse": True,
        },
    ]
    settlement = derive_bootstrap_settlement_evidence(
        own_and_linked_rows,
        campaign_id=campaign_id,
        own_trade_ids=frozenset({"02" * 32}),
        linked_cluster_ids=frozenset({"linked"}),
    )
    assert settlement.confirmed_fills == 1
    assert settlement.settlement_clusters == 1

    campaign_value = campaign.xch_budget + campaign.cat_budget * campaign.anchor_price
    loss = evaluate_bootstrap_campaign(
        campaign,
        BootstrapEvidence(realized_loss_xch=campaign_value * Decimal("0.05")),
        now=NOW,
    )
    fees = evaluate_bootstrap_campaign(
        campaign,
        BootstrapEvidence(fee_spent_xch=Decimal("0.04")),
        now=NOW,
    )
    expired = evaluate_bootstrap_campaign(
        campaign, BootstrapEvidence(), now=NOW + timedelta(days=7)
    )
    assert loss.stop_reason is CampaignStopReason.LOSS_LIMIT
    assert loss.manual_restart_required is True
    assert fees.stop_reason is CampaignStopReason.FEE_RESERVE
    assert fees.cancellation_fee_reserve_xch == Decimal("0.01")
    assert expired.stop_reason is CampaignStopReason.EXPIRED


def test_authoritative_campaign_fills_and_current_independent_depth_drive_stage(
    bootstrap_app,
):
    _bootstrap, client, _identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)
    purpose = f"bootstrap:{campaign_id}:revision:0"
    intents = [
        {
            "sage_trade_id": "01" * 32,
            "purpose": purpose,
            "asset_id": ASSET_ID,
        },
        {
            "sage_trade_id": "02" * 32,
            "purpose": purpose,
            "asset_id": ASSET_ID,
        },
    ]
    fills = [
        {
            "trade_id": "01" * 32,
            "side": "buy",
            "price_xch": "0.0011",
            "filled_at": "2026-09-12T11:50:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000000,
            "receive_coin_id": "11" * 32,
            "taker_puzzle_hash": "21" * 32,
        },
        {
            "trade_id": "02" * 32,
            "side": "sell",
            "price_xch": "0.00105",
            "filled_at": "2026-09-12T11:51:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000001,
            "receive_coin_id": "12" * 32,
            "taker_puzzle_hash": "22" * 32,
        },
        {
            "trade_id": "03" * 32,
            "side": "buy",
            "filled_at": "2026-09-12T11:52:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000002,
            "receive_coin_id": "13" * 32,
            "taker_puzzle_hash": "23" * 32,
        },
    ]
    confidence = SimpleNamespace(
        data_valid=True,
        trusted_midpoint=Decimal("0.00102"),
        independent_bid_depth_mojos=100_000_000_000,
        independent_ask_depth_mojos=100_000_000_000,
        required_depth_mojos=50_000_000_000,
    )

    evidence = derive_bootstrap_authoritative_evidence(
        campaign_record=record,
        authoritative_fills=fills,
        intents=intents,
        market_confidence=confidence,
        now=NOW,
        own_participant_clusters=frozenset(),
        linked_participant_clusters=frozenset(),
        include_anchor_proposal=True,
    )
    campaign = _campaign_from_record(record)
    decision = evaluate_bootstrap_campaign(campaign, evidence, now=NOW)

    assert evidence.confirmed_fills == 2
    assert evidence.settlement_clusters == 2
    assert evidence.independent_depth_sides == frozenset(
        {CampaignSide.BUY, CampaignSide.SELL}
    )
    assert evidence.stable_since == NOW
    assert evidence.proposed_anchor_price == Decimal("0.00102")
    assert evidence.adverse_fill_times == (
        (CampaignSide.BUY, NOW - timedelta(minutes=10)),
    )
    assert decision.stage is CampaignStage.DISCOVERY_25

    state_update = plan_bootstrap_state_update(
        campaign_record=record,
        evidence=evidence,
        decision=decision,
        now=NOW,
    )
    assert state_update["stage"] == "discovery_25"
    assert state_update["deployment_fraction"] == "0.25"
    assert state_update["confirmed_fills"] == 2
    assert state_update["settlement_clusters"] == 2
    assert state_update["stable_since"] == "2026-09-12T12:00:00.000000Z"

    runtime = derive_bootstrap_runtime(
        campaign_record=record,
        identity={
            key: record[key]
            for key in (
                "network",
                "wallet_type",
                "wallet_fingerprint",
                "wallet_id",
                "asset_id",
            )
        },
        balances=_balances(),
        now=NOW,
        evidence=evidence,
    )
    assert runtime["decision"].stage is CampaignStage.DISCOVERY_25
    assert runtime["decision"].deployment_fraction == Decimal("0.25")


def test_superseded_revision_trade_ids_are_fenced_before_replacement():
    campaign_id = "ab" * 32
    live = {"01" * 32, "02" * 32, "03" * 32, "04" * 32}
    intents = [
        {
            "sage_trade_id": "01" * 32,
            "purpose": f"bootstrap:{campaign_id}:revision:0",
            "lifecycle_state": "created",
        },
        {
            "sage_trade_id": "02" * 32,
            "purpose": f"bootstrap:{campaign_id}:revision:1",
            "lifecycle_state": "terminal",
        },
        {
            "sage_trade_id": "03" * 32,
            "purpose": f"bootstrap:{campaign_id}:revision:2",
            "lifecycle_state": "created",
        },
        {
            "sage_trade_id": "04" * 32,
            "purpose": f"bootstrap:{'cd' * 32}:revision:0",
            "lifecycle_state": "created",
        },
        {
            "sage_trade_id": "05" * 32,
            "purpose": f"bootstrap:{campaign_id}:revision:0",
            "lifecycle_state": "created",
        },
    ]

    assert superseded_bootstrap_trade_ids(
        intents,
        campaign_id=campaign_id,
        revision=2,
        live_trade_ids=live,
    ) == ("01" * 32, "02" * 32)


def test_live_bot_materializes_authoritative_stage_before_creating(
    bootstrap_app, monkeypatch
):
    _bootstrap, client, identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)
    purpose = f"bootstrap:{campaign_id}:revision:0"
    intents = [
        {
            "sage_trade_id": "01" * 32,
            "purpose": purpose,
            "asset_id": ASSET_ID,
        },
        {
            "sage_trade_id": "02" * 32,
            "purpose": purpose,
            "asset_id": ASSET_ID,
        },
    ]
    fills = [
        {
            "trade_id": "01" * 32,
            "side": "buy",
            "filled_at": "2026-09-12T11:50:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000000,
            "receive_coin_id": "11" * 32,
            "taker_puzzle_hash": "21" * 32,
        },
        {
            "trade_id": "02" * 32,
            "side": "sell",
            "filled_at": "2026-09-12T11:51:00.000000Z",
            "verification_status": "verified_authoritative",
            "spent_block_height": 7000001,
            "receive_coin_id": "12" * 32,
            "taker_puzzle_hash": "22" * 32,
        },
    ]
    confidence = SimpleNamespace(
        data_valid=True,
        trusted_midpoint=Decimal("0.00102"),
        independent_bid_depth_mojos=100_000_000_000,
        independent_ask_depth_mojos=100_000_000_000,
        required_depth_mojos=50_000_000_000,
    )

    import bot_loop
    import wallet

    monkeypatch.setattr(wallet, "get_wallet_puzzle_hashes", lambda: {"99" * 32})
    monkeypatch.setattr(bot_loop.database, "get_fills", lambda *_args, **_kwargs: fills)
    loop = object.__new__(BotLoop)
    loop._market_confidence_result = confidence

    result = loop._refresh_bootstrap_campaign_evidence(
        campaign=record,
        intents=intents,
        identity={
            key: identity[key]
            for key in (
                "network",
                "wallet_type",
                "wallet_fingerprint",
                "wallet_id",
                "asset_id",
            )
        },
        balances=_balances(),
        now=NOW,
    )

    assert result["changed"] is True
    assert result["runtime"] is None
    assert result["campaign"]["revision"] == 1
    assert result["campaign"]["stage"] == "discovery_25"
    assert result["campaign"]["confirmed_fills"] == 2
    assert result["campaign"]["settlement_clusters"] == 2
    assert result["campaign"]["current_anchor_price"] == "0.001"
    events = database.list_bootstrap_campaign_events(campaign_id)
    assert events[-1]["event_type"] == "authoritative_evidence_materialized"


def test_live_bot_blocks_higher_stage_replacement_without_owned_hash_proof(
    bootstrap_app, monkeypatch
):
    _bootstrap, client, identity, _clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    record = database.get_bootstrap_campaign(campaign_id)
    record.update(
        stage="discovery_25",
        deployment_fraction="0.25",
        confirmed_fills=2,
        settlement_clusters=2,
        independent_depth_sides=["buy", "sell"],
        stable_since="2026-09-12T12:00:00.000000Z",
    )

    import wallet

    monkeypatch.setattr(wallet, "get_wallet_puzzle_hashes", lambda: set())
    loop = object.__new__(BotLoop)
    loop._market_confidence_result = SimpleNamespace(data_valid=True)
    result = loop._refresh_bootstrap_campaign_evidence(
        campaign=record,
        intents=[],
        identity={
            key: identity[key]
            for key in (
                "network",
                "wallet_type",
                "wallet_fingerprint",
                "wallet_id",
                "asset_id",
            )
        },
        balances=_balances(),
        now=NOW,
    )

    assert result == {
        "campaign": record,
        "runtime": None,
        "changed": False,
        "blocked": True,
    }


def test_interactive_signing_join_and_private_proof_export(bootstrap_app):
    bootstrap, client, _identity, clock = bootstrap_app
    preview = client.post("/api/bootstrap/preview", json=_request()).get_json()
    campaign_id = client.post(
        "/api/bootstrap/start",
        json=_request(
            preview_digest=preview["preview_digest"],
            exact_asset_warning_accepted=True,
        ),
    ).get_json()["campaign_id"]
    manifest = client.post(
        "/api/bootstrap/manifest/export",
        json={"campaign_id": campaign_id, "ticker": "NEWCAT"},
    ).get_json()["manifest"]
    identity = WalletIdentity("sage", 736588221, "mainnet", ADDRESS)

    missing = WalletConnectSigningService(
        project_id="", identity_reader=lambda: identity, clock=lambda: NOW
    )
    with pytest.raises(SigningError, match="walletconnect_project_id_missing"):
        missing.begin_manifest_signature(manifest, identity)

    service = WalletConnectSigningService(
        project_id="public-project-id",
        identity_reader=lambda: identity,
        clock=lambda: NOW,
    )
    rejected = service.begin_manifest_signature(manifest, identity)
    with pytest.raises(SigningError, match="walletconnect_user_rejected"):
        service.fail_request(rejected.request_id, "user_rejected")

    mismatched = service.begin_manifest_signature(manifest, identity)
    with pytest.raises(SigningError, match="walletconnect_account_mismatch"):
        service.complete_manifest_signature(
            mismatched.request_id,
            _walletconnect_response(mismatched, account="chia:mainnet:1"),
            identity,
        )

    signing = service.begin_manifest_signature(manifest, identity)
    signed_manifest = service.complete_manifest_signature(
        signing.request_id, _walletconnect_response(signing), identity
    )
    assert verify_campaign_manifest(signed_manifest).status == "VERIFIED"
    joined = client.post(
        "/api/bootstrap/manifest/import", json={"signed_manifest": signed_manifest}
    ).get_json()
    assert joined["can_start"] is False
    assert joined["requires_local_budget_acceptance"] is True
    assert joined["financial_authority"] is False

    database.record_bootstrap_participation(
        {
            "campaign_id": campaign_id,
            "report_id": "31" * 32,
            "recorded_at": NOW + timedelta(minutes=5),
            "data": {
                "kind": "quality_sample",
                "duration_seconds": 300,
                "independent_depth_xch": "2",
                "spread_bps": "150",
                "within_corridor": True,
                "own": False,
                "linked": False,
                "offer_ids": ["41" * 32],
                "fill_ids": ["51" * 32],
                "wallet_fingerprint": 736588221,
                "balances": {"xch": "999"},
            },
        }
    )
    clock["now"] = NOW + timedelta(hours=1)
    proof = client.post(
        "/api/bootstrap/participation/export", json={"campaign_id": campaign_id}
    ).get_json()
    assert proof["financial_authority"] is False
    assert proof["reward_amount"] is None
    assert "fingerprint" not in str(proof).lower()
    proof_service = WalletConnectSigningService(
        project_id="public-project-id",
        identity_reader=lambda: identity,
        clock=lambda: clock["now"],
    )
    proof_request = proof_service.begin_participation_signature(
        proof["report"], identity
    )
    signed_proof = proof_service.complete_participation_signature(
        proof_request.request_id,
        _walletconnect_response(proof_request),
        identity,
    )
    assert (
        verify_participation_report(
            signed_proof, expected_network="mainnet", now=clock["now"]
        ).status
        == "VERIFIED"
    )

    partial = client.get("/api/bootstrap/partial-capability").get_json()
    assert partial["enabled"] is False
    assert partial["policy"] == "disabled_until_capability_proven"
