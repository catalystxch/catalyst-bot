"""Fail-closed guard tests for the authorised TEST 7 mainnet lab."""

from __future__ import annotations

import ast
import importlib.util
import json
from decimal import Decimal
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "test7_stability_lab.py"
_SPEC = importlib.util.spec_from_file_location("test7_stability_lab", _SCRIPT)
lab = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(lab)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _identity(now: datetime, **overrides):
    identity = {
        "success": True,
        "backend": "sage",
        "name": "TEST 7",
        "fingerprint": 736588221,
        "network_id": "mainnet",
        "kind": "bls",
        "has_secrets": True,
        "observed_at_utc": _utc(now - timedelta(seconds=1)),
    }
    identity.update(overrides)
    return identity


def _live_kwargs(tmp_path: Path, now: datetime, identity=None):
    data_dir = tmp_path / "test7-lab"
    lab.initialize_lab_directory(data_dir, initialized_at=now)
    return {
        "live": True,
        "confirmation": lab.LIVE_CONFIRMATION,
        "data_dir": data_dir,
        "environment": {"CMM_DATA_DIR": str(data_dir.resolve())},
        "identity_reader": lambda: _identity(now) if identity is None else identity,
        "now": now,
    }


def test_cli_defaults_to_read_only_inventory():
    args = lab.build_parser().parse_args([])

    assert args.live is False
    assert args.stage == ["inventory"]
    assert args.confirm is None


def test_live_guard_requires_explicit_live_confirmation_and_isolated_marker(tmp_path):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    kwargs = _live_kwargs(tmp_path, now)

    for change, reason in (
        ({"live": False}, "LIVE_FLAG_REQUIRED"),
        ({"confirmation": None}, "LIVE_CONFIRMATION_REQUIRED"),
        (
            {"environment": {"CMM_DATA_DIR": str(tmp_path / "different")}},
            "ISOLATED_DATA_DIR_REQUIRED",
        ),
    ):
        candidate = {**kwargs, **change}
        with pytest.raises(lab.LabRefusal, match=reason):
            lab.authorize_live_mutation(**candidate)

    marker = kwargs["data_dir"] / lab.LAB_MARKER_NAME
    marker.unlink()
    with pytest.raises(lab.LabRefusal, match="LAB_MARKER_REQUIRED"):
        lab.authorize_live_mutation(**kwargs)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"success": False}, "IDENTITY_UNAVAILABLE"),
        ({"backend": "chia"}, "IDENTITY_BACKEND_MISMATCH"),
        ({"name": "TEST 8"}, "IDENTITY_NAME_MISMATCH"),
        ({"fingerprint": 736588222}, "IDENTITY_FINGERPRINT_MISMATCH"),
        ({"fingerprint": True}, "IDENTITY_FINGERPRINT_MISMATCH"),
        ({"network_id": "testnet11"}, "IDENTITY_NETWORK_MISMATCH"),
        ({"kind": "legacy"}, "IDENTITY_KIND_MISMATCH"),
        ({"has_secrets": False}, "SIGNING_DISABLED"),
        ({"has_secrets": 1}, "SIGNING_DISABLED"),
        ({"observed_at_utc": "not-a-time"}, "IDENTITY_TIME_INVALID"),
    ],
)
def test_live_guard_rejects_every_identity_mismatch(tmp_path, overrides, reason):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    kwargs = _live_kwargs(tmp_path, now, _identity(now, **overrides))

    with pytest.raises(lab.LabRefusal, match=reason):
        lab.authorize_live_mutation(**kwargs)


def test_live_guard_rejects_stale_or_future_identity(tmp_path):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)

    for observed, reason in (
        (now - timedelta(seconds=lab.IDENTITY_MAX_AGE_SECONDS + 1), "IDENTITY_STALE"),
        (now + timedelta(microseconds=1), "IDENTITY_FROM_FUTURE"),
    ):
        kwargs = _live_kwargs(
            tmp_path / reason.lower(),
            now,
            _identity(now, observed_at_utc=_utc(observed)),
        )
        with pytest.raises(lab.LabRefusal, match=reason):
            lab.authorize_live_mutation(**kwargs)


def test_every_mutation_uses_a_fresh_identity_and_failure_never_calls_effect(tmp_path):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    data_dir = tmp_path / "test7-lab"
    lab.initialize_lab_directory(data_dir, initialized_at=now)
    identities = [_identity(now), _identity(now, has_secrets=False)]
    effects = []

    kwargs = {
        "live": True,
        "confirmation": lab.LIVE_CONFIRMATION,
        "data_dir": data_dir,
        "environment": {"CMM_DATA_DIR": str(data_dir.resolve())},
        "identity_reader": lambda: identities.pop(0),
        "now": now,
    }

    assert lab.run_guarded_mutation(
        operation="create", effect=lambda: effects.append("create") or {"ok": True}, **kwargs
    )["result"] == {"ok": True}
    with pytest.raises(lab.LabRefusal, match="SIGNING_DISABLED"):
        lab.run_guarded_mutation(
            operation="cancel",
            effect=lambda: effects.append("cancel") or {"ok": True},
            **kwargs,
        )

    assert effects == ["create"]
    assert identities == []


def test_checkpoint_advances_only_after_success_and_keeps_bounded_redacted_evidence(
    tmp_path,
):
    checkpoint = lab.CheckpointStore(tmp_path / "checkpoint.json")

    with pytest.raises(RuntimeError, match="boom"):
        checkpoint.run_stage("lifecycle", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert checkpoint.completed_stages() == []

    result = checkpoint.run_stage(
        "lifecycle",
        lambda: {
            "success": True,
            "trade_id": "a" * 64,
            "private_key": "must-not-persist",
            "nested": {"secret": "must-not-persist"},
        },
    )

    assert result["success"] is True
    assert checkpoint.completed_stages() == ["lifecycle"]
    payload = json.loads(checkpoint.path.read_text(encoding="utf-8"))
    persisted = json.dumps(payload, sort_keys=True)
    assert "private_key" not in persisted
    assert "must-not-persist" not in persisted
    assert payload["stages"]["lifecycle"]["evidence"] == {
        "success": True,
        "trade_id": "a" * 64,
    }


def test_lab_source_never_imports_private_wallet_adapter():
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert "wallet_sage" not in imported
    assert all(not name.startswith("wallet_sage.") for name in imported)


def test_dry_run_never_invokes_mutating_stage_or_checkpoints_it(tmp_path):
    checkpoint = lab.CheckpointStore(tmp_path / "checkpoint.json")
    invoked = []

    results = lab.execute_stage_plan(
        stages=["lifecycle"],
        live=False,
        checkpoint=checkpoint,
        handlers={
            "lifecycle": lambda mutate: invoked.append("lifecycle") or {"success": True}
        },
        authority={},
    )

    assert invoked == []
    assert checkpoint.completed_stages() == []
    assert results == [
        {"success": True, "stage": "lifecycle", "planned": True, "live_effects": False}
    ]


def test_read_only_stage_runs_without_live_authority(tmp_path):
    checkpoint = lab.CheckpointStore(tmp_path / "checkpoint.json")
    invoked = []

    results = lab.execute_stage_plan(
        stages=["inventory"],
        live=False,
        checkpoint=checkpoint,
        handlers={
            "inventory": lambda: invoked.append("inventory")
            or {"success": True, "stage": "inventory", "count": 3}
        },
        authority={},
    )

    assert invoked == ["inventory"]
    assert results[0]["count"] == 3
    assert checkpoint.completed_stages() == ["inventory"]


def test_live_stage_reauthorizes_each_individual_effect(tmp_path):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    checkpoint = lab.CheckpointStore(tmp_path / "checkpoint.json")
    identity_reads = []
    effects = []
    authority = _live_kwargs(tmp_path, now)
    authority["identity_reader"] = lambda: identity_reads.append("read") or _identity(now)

    def lifecycle(mutate):
        mutate("create", lambda: effects.append("create") or {"success": True})
        mutate("cancel", lambda: effects.append("cancel") or {"success": True})
        return {"success": True, "stage": "lifecycle", "count": 2}

    results = lab.execute_stage_plan(
        stages=["lifecycle"],
        live=True,
        checkpoint=checkpoint,
        handlers={"lifecycle": lifecycle},
        authority=authority,
    )

    assert results[0]["success"] is True
    assert identity_reads == ["read", "read"]
    assert effects == ["create", "cancel"]
    assert checkpoint.completed_stages() == ["lifecycle"]


def test_runtime_environment_is_exact_and_public_modules_are_loaded(tmp_path):
    data_dir = tmp_path / "test7-lab"
    lab.initialize_lab_directory(data_dir)
    environment = {}
    imported = []

    lab.prepare_runtime_environment(
        data_dir=data_dir,
        environment=environment,
        source_root=tmp_path / "src" / "catalyst",
    )
    modules = lab.load_public_modules(
        import_module=lambda name: imported.append(name) or SimpleNamespace()
    )

    assert environment == {
        "CMM_DATA_DIR": str(data_dir.resolve()),
        "WALLET_TYPE": "sage",
        "SAGE_FINGERPRINT": "736588221",
        "WALLET_EXPECTED_NAME": "TEST 7",
        "WALLET_EXPECTED_KEY_KIND": "bls",
        "CATALYST_NETWORK_ID": "mainnet",
        "_CATALYST_PRESERVE_PROCESS_ENV": "1",
    }
    assert imported == [
        "wallet",
        "database",
        "offer_reconciliation",
        "offer_manager",
        "api_server",
        "dexie_manager",
        "price_engine",
        "coin_manager",
        "runtime_recovery",
    ]
    assert set(modules) == set(imported)
    assert "wallet_sage" not in imported


def _fake_runtime_modules(now, *, history_complete=True, wallets=None):
    if wallets is None:
        wallets = [
            {"id": 1, "name": "Chia Wallet", "type": 0},
            {"id": 1000, "name": "SBX (SBX)", "type": 6, "data": "a" * 64},
        ]
    wallet = SimpleNamespace(
        get_wallet_identity=lambda: _identity(now),
        get_wallets=lambda: {"success": True, "wallets": wallets},
        get_wallet_balance=lambda wallet_id: {
            "success": True,
            "wallet_balance": {
                "wallet_id": wallet_id,
                "confirmed_wallet_balance": 1000 + wallet_id,
                "spendable_balance": 900 + wallet_id,
            },
        },
        get_all_offers=lambda **_kwargs: {"success": True, "offers": []},
    )
    history = {
        "complete": history_complete,
        "read_error": None if history_complete else "reader_malformed",
        "records": [],
        "observed_at": _utc(now),
        "provenance": "wallet.get_all_offers",
        "pagination": {"pages_read": 1},
    }
    reconciliation = SimpleNamespace(
        load_sage_offer_history=lambda **_kwargs: history,
        reconcile_offer=lambda *_args, **_kwargs: {"classification": "ACTIVE_PROVEN"},
    )
    database = SimpleNamespace(
        init_database=lambda: None,
        check_db_integrity=lambda: {"ok": True},
        get_offer_intents_for_registry=lambda: [],
        get_unresolved_offer_operation_blockers=lambda: [],
        get_runtime_safety_latch=lambda: {"state": "resolved"},
        list_publication_outbox=lambda: [],
        get_free_coins=lambda wallet_type: [
            {
                "coin_id": "1" * 64,
                "amount_mojos": 3_000_000_000,
                "status": "free",
                "trade_id": None,
                "designation": "unknown",
                "assigned_tier": "none",
                "purpose": None,
            }
        ]
        if wallet_type == "xch"
        else [],
        set_coin_designation=lambda *_args, **_kwargs: True,
    )
    config = SimpleNamespace(
        CAT_ASSET_ID="",
        CAT_WALLET_ID=2,
        CAT_DECIMALS=3,
        CAT_TICKER_ID="",
        CAT_NAME="",
        DRY_RUN=True,
        TIER_ENABLED=True,
        MAX_PARALLEL_OFFERS=8,
    )
    return {
        "wallet": wallet,
        "database": database,
        "offer_reconciliation": reconciliation,
        "offer_manager": SimpleNamespace(cfg=config),
        "api_server": SimpleNamespace(),
        "dexie_manager": SimpleNamespace(),
        "price_engine": SimpleNamespace(),
        "coin_manager": SimpleNamespace(
            CoinManager=lambda: SimpleNamespace(reconcile_with_wallet=lambda: None),
            coin_size_tier_for_slot_position=lambda _tier, side: (
                "outer" if side == "buy" else "mid"
            ),
        ),
        "runtime_recovery": SimpleNamespace(),
    }


def test_inventory_uses_public_wallet_facade_and_requires_complete_history():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    runtime = lab.CatalystLabRuntime(_fake_runtime_modules(now))

    result = runtime.inventory(now=now)

    assert result["success"] is True
    assert result["stage"] == "inventory"
    assert result["count"] == 2
    assert result["sbx"] == {"wallet_id": 1000, "asset_id": "a" * 64}
    assert result["balances"] == {
        "xch": {"confirmed_mojos": 1001, "spendable_mojos": 901},
        "sbx": {"confirmed_mojos": 2000, "spendable_mojos": 1900},
    }
    assert result["offer_history"]["complete"] is True

    incomplete = lab.CatalystLabRuntime(
        _fake_runtime_modules(now, history_complete=False)
    )
    with pytest.raises(lab.LabRefusal, match="OFFER_HISTORY_INCOMPLETE"):
        incomplete.inventory(now=now)


def test_inventory_prefers_public_authoritative_history_reader():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    authoritative = lambda **_kwargs: {"offers": [], "total": 0}
    modules["wallet"].get_authoritative_offer_history = authoritative
    observed = []
    modules["offer_reconciliation"].load_sage_offer_history = (
        lambda **kwargs: observed.append(kwargs["get_all_offers"])
        or {
            "complete": True,
            "read_error": None,
            "records": [],
            "pagination": {"pages_read": 1},
        }
    )

    lab.CatalystLabRuntime(modules).inventory(now=now)

    assert observed == [authoritative]


def test_inventory_requires_one_exact_sbx_wallet():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    no_sbx = [{"id": 1, "name": "Chia Wallet", "type": 0}]
    two_sbx = no_sbx + [
        {"id": 1000, "name": "SBX (SBX)", "type": 6, "data": "a" * 64},
        {"id": 1001, "name": "SBX duplicate", "type": 6, "data": "b" * 64},
    ]

    for wallets in (no_sbx, two_sbx):
        runtime = lab.CatalystLabRuntime(
            _fake_runtime_modules(now, wallets=wallets)
        )
        with pytest.raises(lab.LabRefusal, match="SBX_WALLET_AMBIGUOUS"):
            runtime.inventory(now=now)


def test_reconcile_uses_durable_intents_and_requires_zero_safety_blockers():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    calls = []
    modules["database"].get_offer_intents_for_registry = lambda: [
        {"intent_id": "pending", "lifecycle_state": "creation_unknown"},
        {"intent_id": "active", "lifecycle_state": "visible"},
        {"intent_id": "done", "lifecycle_state": "cancelled"},
    ]
    modules["database"].get_stability_startup_recovery_snapshot = lambda: {
        "latch": {"state": "resolved"},
        "blocker_counts": {
            "operations": 0,
            "prepared_creations": 0,
            "submitted_cancels": 0,
            "contradictory_history": 0,
            "reservations": 0,
            "publication_claims": 0,
        },
        "reservation_issues": [],
        "publication_issues": [],
        "authority_digest": "d" * 64,
    }
    modules["offer_reconciliation"].reconcile_offer = (
        lambda intent_id, **kwargs: calls.append((intent_id, kwargs))
        or {"classification": "ACTIVE_PROVEN"}
    )

    result = lab.CatalystLabRuntime(modules).reconcile()

    assert [intent_id for intent_id, _kwargs in calls] == ["pending", "active"]
    assert all(kwargs == {"wallet_facade": modules["wallet"]} for _, kwargs in calls)
    assert result == {
        "success": True,
        "stage": "reconcile",
        "count": 2,
        "classifications": {"ACTIVE_PROVEN": 2},
        "blocker_counts": {
            "operations": 0,
            "prepared_creations": 0,
            "submitted_cancels": 0,
            "contradictory_history": 0,
            "reservations": 0,
            "publication_claims": 0,
        },
        "authority_digest": "d" * 64,
    }

    modules["database"].get_stability_startup_recovery_snapshot = lambda: {
        "latch": {"state": "tripped"},
        "blocker_counts": {"operations": 1},
        "reservation_issues": [],
        "publication_issues": [],
        "authority_digest": "e" * 64,
    }
    with pytest.raises(lab.LabRefusal, match="UNRESOLVED_BLOCKERS"):
        lab.CatalystLabRuntime(modules).reconcile()


def test_reconcile_refuses_database_integrity_failure():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    modules["database"].check_db_integrity = lambda: {"ok": False}

    with pytest.raises(lab.LabRefusal, match="DATABASE_INTEGRITY_FAILED"):
        lab.CatalystLabRuntime(modules).reconcile()


def test_main_runs_read_only_inventory_and_writes_redacted_checkpoint(
    tmp_path, monkeypatch, capsys
):
    data_dir = tmp_path / "test7-lab"
    lab.initialize_lab_directory(data_dir)
    now = datetime.now(timezone.utc)
    modules = _fake_runtime_modules(now)
    monkeypatch.setattr(lab, "load_public_modules", lambda: modules)

    result = lab.main(["--data-dir", str(data_dir)], environment={})

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["mode"] == "read-only"
    assert output["results"][0]["stage"] == "inventory"
    checkpoint = json.loads(
        (data_dir / lab.CHECKPOINT_NAME).read_text(encoding="utf-8")
    )
    assert checkpoint["order"] == ["inventory"]
    persisted = json.dumps(checkpoint, sort_keys=True)
    assert "balances" not in persisted
    assert "asset_id" not in persisted


def test_main_refuses_unmarked_directory_or_wrong_live_confirmation(tmp_path, capsys):
    unmarked = tmp_path / "unmarked"
    unmarked.mkdir()
    assert lab.main(["--data-dir", str(unmarked)], environment={}) == 2
    assert "LAB_MARKER_REQUIRED" in capsys.readouterr().err

    data_dir = tmp_path / "test7-lab"
    lab.initialize_lab_directory(data_dir)
    assert lab.main(
        [
            "--data-dir",
            str(data_dir),
            "--stage",
            "lifecycle",
            "--live",
            "--confirm",
            "wrong",
        ],
        environment={},
    ) == 2
    assert "LIVE_CONFIRMATION_REQUIRED" in capsys.readouterr().err


def test_market_price_uses_public_engine_and_exact_sbx_configuration():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    calls = []

    class Engine:
        def get_price(self, **kwargs):
            calls.append(kwargs)
            return {"mid_price": Decimal("0.00001234"), "strategy_used": "weighted"}

    modules["price_engine"].PriceEngine = Engine
    runtime = lab.CatalystLabRuntime(modules)
    inventory = runtime.inventory(now=now)

    result = runtime.market_price(inventory)

    assert result == {
        "success": True,
        "mid_price_xch": "0.00001234",
        "strategy": "weighted",
    }
    assert calls == [
        {
            "cat_asset_id": "a" * 64,
            "cat_decimals": 3,
            "ticker_id": "SBX_XCH",
        }
    ]
    cfg = modules["offer_manager"].cfg
    assert (cfg.CAT_ASSET_ID, cfg.CAT_WALLET_ID, cfg.CAT_TICKER_ID) == (
        "a" * 64,
        1000,
        "SBX_XCH",
    )


def test_coin_registry_assigns_one_small_free_nonreserve_coin_to_lifecycle():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    coin_syncs = []
    assignments = []
    rows = [
        {
            "coin_id": "1" * 64,
            "amount_mojos": 2_000_000_000,
            "status": "free",
            "trade_id": None,
            "designation": "reserve",
            "assigned_tier": "none",
            "purpose": "fee_reserve",
        },
        {
            "coin_id": "2" * 64,
            "amount_mojos": 2_100_000_000,
            "status": "locked",
            "trade_id": None,
            "designation": "unknown",
            "assigned_tier": "none",
            "purpose": None,
        },
        {
            "coin_id": "3" * 64,
            "amount_mojos": 2_200_000_000,
            "status": "free",
            "trade_id": "a" * 64,
            "designation": "unknown",
            "assigned_tier": "none",
            "purpose": None,
        },
        {
            "coin_id": "4" * 64,
            "amount_mojos": 2_300_000_000,
            "status": "free",
            "trade_id": None,
            "designation": "unknown",
            "assigned_tier": "none",
            "purpose": "replacement",
        },
        {
            "coin_id": "5" * 64,
            "amount_mojos": 3_000_000_000,
            "status": "free",
            "trade_id": None,
            "designation": "unknown",
            "assigned_tier": "none",
            "purpose": None,
        },
        {
            "coin_id": "6" * 64,
            "amount_mojos": 2_500_000_000,
            "status": "free",
            "trade_id": None,
            "designation": "unknown",
            "assigned_tier": "none",
            "purpose": None,
        },
    ]

    def assign(coin_id, designation, assigned_tier, *, purpose):
        assignments.append((coin_id, designation, assigned_tier, purpose))
        row = next(item for item in rows if item["coin_id"] == coin_id)
        row.update(
            designation=designation,
            assigned_tier=assigned_tier,
            purpose=purpose,
        )
        return True

    modules["coin_manager"].CoinManager = lambda: SimpleNamespace(
        reconcile_with_wallet=lambda: coin_syncs.append("sync")
    )
    modules["database"].get_free_coins = lambda wallet_type: (
        rows if wallet_type == "xch" else []
    )
    modules["database"].set_coin_designation = assign

    result = lab.CatalystLabRuntime(modules)._sync_coin_registry(
        required_xch_mojos=2_000_000_000
    )

    assert coin_syncs == ["sync"]
    assert assignments == [("6" * 64, "tier_spare", "outer", "lifecycle")]
    assert result == {"xch": 6, "cat": 0, "lifecycle": 1}


def test_lifecycle_guards_create_publish_cancel_and_finishes_reconciled():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    manager_calls = []
    publisher_calls = []
    coin_syncs = []

    class Manager:
        def create_ladder(self, **kwargs):
            manager_calls.append(("create", kwargs))
            return [
                {
                    "trade_id": "c" * 64,
                    "intent_id": "intent-live",
                    "offer_bech32": "offer1safe",
                    "price": Decimal("0.00000617"),
                    "size_xch": Decimal("0.001"),
                }
            ]

        def cancel_offers(self, trade_ids, **kwargs):
            manager_calls.append(("cancel", trade_ids, kwargs))
            return {trade_ids[0]: {"outcome": "CANCEL_CONFIRMED"}}

    class Publisher:
        def enable_durable_outbox(self, **kwargs):
            publisher_calls.append(("enable", kwargs))

        def queue_post(self, offer, trade_id, force=False):
            publisher_calls.append(("queue", offer, trade_id, force))

        def flush_queue(self, flush_all=False):
            publisher_calls.append(("flush", flush_all))
            return {"posted": 1, "failed": 0, "skipped": 0, "requeued": 0}

    modules["offer_manager"].OfferManager = Manager
    lifecycle_rows = modules["database"].get_free_coins("xch")
    modules["database"].get_free_coins = lambda wallet_type: (
        lifecycle_rows if wallet_type == "xch" else []
    )

    def assign_lifecycle(coin_id, designation, assigned_tier, *, purpose):
        row = next(item for item in lifecycle_rows if item["coin_id"] == coin_id)
        row.update(
            designation=designation,
            assigned_tier=assigned_tier,
            purpose=purpose,
        )
        return True

    modules["database"].set_coin_designation = assign_lifecycle
    modules["coin_manager"].CoinManager = lambda: SimpleNamespace(
        reconcile_with_wallet=lambda: coin_syncs.append("sync")
    )
    modules["dexie_manager"].DexieManager = Publisher
    modules["database"].get_runtime_mutation_lease = lambda: {
        "active": 1,
        "owner_run_id": "run-live",
        "network": "mainnet",
        "expires_at": "2026-08-22T12:01:00.000000Z",
    }
    modules["offer_reconciliation"].reconcile_offer = lambda *_args, **_kwargs: {
        "classification": "CANCELLED_PROVEN"
    }
    modules["database"].get_stability_startup_recovery_snapshot = lambda: {
        "latch": {"state": "resolved"},
        "blocker_counts": {"operations": 0},
        "reservation_issues": [],
        "publication_issues": [],
        "authority_digest": "f" * 64,
    }
    runtime = lab.CatalystLabRuntime(modules)
    inventory = runtime.inventory(now=now)
    operations = []

    def mutate(operation, effect):
        operations.append(operation)
        return {"result": effect()}

    result = runtime.lifecycle(
        mutate,
        inventory=inventory,
        mid_price=Decimal("0.00001234"),
        trade_size_xch=Decimal("0.001"),
        spread_fraction=Decimal("0.5"),
    )

    assert operations == ["create_offer", "publish_offer", "cancel_offer"]
    assert coin_syncs == ["sync"]
    assert result == {
        "success": True,
        "stage": "lifecycle",
        "count": 1,
        "trade_id": "c" * 64,
        "intent_id": "intent-live",
        "classification": "CANCELLED_PROVEN",
    }
    create = manager_calls[0][1]
    assert create["side"] == "buy"
    assert create["num_offers"] == 1
    assert create["coin_ids_enabled"] is True
    assert create["cat_asset_id"] == "a" * 64
    assert publisher_calls[1:] == [
        ("queue", "offer1safe", "c" * 64, True),
        ("flush", True),
    ]
    assert manager_calls[1] == (
        "cancel",
        ["c" * 64],
        {"reason": "test7_lifecycle", "force_storm": True},
    )


def test_lifecycle_checkpoints_exact_terminal_attempt_without_second_offer():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    trade_id = "c" * 64
    intent_id = "intent-recovered"
    modules["database"].get_offer_intents_for_registry = lambda: [
        {
            "intent_id": intent_id,
            "sage_trade_id": trade_id,
            "asset_id": "a" * 64,
            "side": "buy",
            "purpose": "normal_lifecycle",
            "lifecycle_state": "terminal",
        }
    ]
    modules["database"].get_offer_operation_events = lambda operation_id: (
        [
            {
                "phase": "RECONCILED",
                "outcome": "CANCEL_CONFIRMED",
                "blocks_mutation": 0,
                "spend_identity": "sha256:" + "d" * 64,
            }
        ]
        if operation_id == f"cancel:{trade_id}"
        else [
            {
                "phase": "FINALIZED",
                "outcome": "CANCELLED_PROVEN",
                "blocks_mutation": 0,
                "spend_identity": "sha256:" + "d" * 64,
            }
        ]
    )
    modules["database"].get_stability_startup_recovery_snapshot = lambda: {
        "latch": {"state": "resolved"},
        "blocker_counts": {"operations": 0},
        "reservation_issues": [],
        "publication_issues": [],
        "authority_digest": "f" * 64,
    }
    runtime = lab.CatalystLabRuntime(modules)
    inventory = runtime.inventory(now=now)
    mutations = []

    result = runtime.lifecycle(
        lambda operation, _effect: mutations.append(operation),
        inventory=inventory,
        mid_price=Decimal("0.00001234"),
        trade_size_xch=Decimal("0.001"),
        spread_fraction=Decimal("0.5"),
    )

    assert mutations == []
    assert result == {
        "success": True,
        "stage": "lifecycle",
        "count": 1,
        "trade_id": trade_id,
        "intent_id": intent_id,
        "classification": "CANCELLED_PROVEN",
        "recovered": True,
    }


def test_restart_releases_and_reacquires_clean_runtime_under_guard():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    calls = []
    modules["api_server"].release_mutation_runtime = lambda: (
        calls.append("release") or {"released": True}
    )
    modules["api_server"].initialize_mutation_runtime = lambda **kwargs: (
        calls.append(("initialize", kwargs))
        or {"allowed": True, "reason_code": "", "lease": {"active": True}}
    )
    modules["database"].get_stability_startup_recovery_snapshot = lambda: {
        "latch": {"state": "resolved"},
        "blocker_counts": {"operations": 0},
        "reservation_issues": [],
        "publication_issues": [],
        "authority_digest": "f" * 64,
    }
    operations = []

    def mutate(operation, effect):
        operations.append(operation)
        return {"result": effect()}

    result = lab.CatalystLabRuntime(modules).restart(mutate, now=now)

    assert operations == ["restart_runtime"]
    assert calls == [
        "release",
        (
            "initialize",
            {"start_heartbeat": True, "acquire_lease": True},
        ),
    ]
    assert result["classification"] == "RESTART_RECOVERED"


def test_stale_read_probe_freezes_before_effect(tmp_path):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    data_dir = tmp_path / "test7-lab"
    lab.initialize_lab_directory(data_dir)
    modules = _fake_runtime_modules(now)
    effects = []
    modules["database"].get_stability_startup_recovery_snapshot = lambda: {
        "latch": {"state": "resolved"},
        "blocker_counts": {"operations": 0},
        "reservation_issues": [],
        "publication_issues": [],
        "authority_digest": "f" * 64,
    }

    result = lab.CatalystLabRuntime(modules).stale_read(
        data_dir=data_dir,
        environment={"CMM_DATA_DIR": str(data_dir.resolve())},
        now=now,
        effect=lambda: effects.append("ran"),
    )

    assert effects == []
    assert result["classification"] == "STALE_READ_FROZEN"


def test_long_gap_runs_full_recovery_epoch_under_guard():
    from runtime_recovery import ClockSample, detect_discontinuity

    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    modules["runtime_recovery"] = SimpleNamespace(
        ClockSample=ClockSample,
        detect_discontinuity=detect_discontinuity,
    )
    observed = []
    modules["api_server"].run_runtime_recovery = lambda decision, sample: (
        observed.append((decision, sample))
        or {"allowed": True, "reason_code": "RECOVERY_COMPLETE"}
    )
    modules["database"].get_stability_startup_recovery_snapshot = lambda: {
        "latch": {"state": "resolved"},
        "blocker_counts": {"operations": 0},
        "reservation_issues": [],
        "publication_issues": [],
        "authority_digest": "f" * 64,
    }
    operations = []

    def mutate(operation, effect):
        operations.append(operation)
        return {"result": effect()}

    result = lab.CatalystLabRuntime(modules).long_gap(mutate, now=now)

    assert operations == ["long_gap_recovery"]
    assert observed[0][0].reason_code == "MONOTONIC_GAP"
    assert observed[0][1].wall_utc == now
    assert result["classification"] == "MONOTONIC_GAP_RECOVERED"


def test_main_live_lifecycle_acquires_and_releases_runtime(
    tmp_path, monkeypatch, capsys
):
    data_dir = tmp_path / "test7-lab"
    lab.initialize_lab_directory(data_dir)
    now = datetime.now(timezone.utc)
    modules = _fake_runtime_modules(now)
    runtime_calls = []
    modules["api_server"].initialize_mutation_runtime = lambda **kwargs: (
        runtime_calls.append(("start", kwargs))
        or {"allowed": True, "reason_code": "ALLOWED"}
    )
    modules["api_server"].release_mutation_runtime = lambda: (
        runtime_calls.append(("release", {})) or {"released": True}
    )

    class Engine:
        def get_price(self, **_kwargs):
            return {"mid_price": Decimal("0.00001234"), "strategy_used": "weighted"}

    modules["price_engine"].PriceEngine = Engine
    effects = []

    def fake_lifecycle(self, mutate, **kwargs):
        assert kwargs["mid_price"] == Decimal("0.00001234")
        mutate("create_offer", lambda: effects.append("create"))
        mutate("publish_offer", lambda: effects.append("publish"))
        mutate("cancel_offer", lambda: effects.append("cancel"))
        return {
            "success": True,
            "stage": "lifecycle",
            "count": 1,
            "trade_id": "c" * 64,
            "intent_id": "intent-live",
            "classification": "CANCELLED_PROVEN",
        }

    monkeypatch.setattr(lab, "load_public_modules", lambda: modules)
    monkeypatch.setattr(lab.CatalystLabRuntime, "lifecycle", fake_lifecycle)

    result = lab.main(
        [
            "--data-dir",
            str(data_dir),
            "--stage",
            "lifecycle",
            "--live",
            "--confirm",
            lab.LIVE_CONFIRMATION,
        ],
        environment={},
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["mode"] == "live"
    assert [item["stage"] for item in output["results"]] == [
        "inventory",
        "lifecycle",
    ]
    assert effects == ["create", "publish", "cancel"]
    assert runtime_calls == [
        ("start", {"start_heartbeat": True, "acquire_lease": True}),
        ("release", {}),
    ]


def test_main_refuses_live_mode_without_explicit_isolated_data_dir(capsys):
    assert lab.main(
        ["--live", "--confirm", lab.LIVE_CONFIRMATION], environment={}
    ) == 2
    assert "ISOLATED_DATA_DIR_REQUIRED" in capsys.readouterr().err


def _clean_safety_snapshot(digest="f" * 64):
    return {
        "latch": {"state": "resolved"},
        "blocker_counts": {"operations": 0},
        "reservation_issues": [],
        "publication_issues": [],
        "authority_digest": digest,
    }


def test_replacement_runs_two_visible_child_before_parent_cancel_waves():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    rows = [
        {
            "coin_id": str(index) * 64,
            "amount_mojos": 2_000_000_000 + index,
            "status": "free",
            "trade_id": None,
            "designation": "unknown",
            "assigned_tier": "none",
            "purpose": None,
        }
        for index in (1, 2, 3)
    ]
    modules["database"].get_free_coins = lambda wallet_type: (
        rows if wallet_type == "xch" else []
    )
    modules["database"].get_stability_startup_recovery_snapshot = (
        _clean_safety_snapshot
    )
    modules["database"].get_offer_intents_for_registry = lambda: []
    assignments = []

    def designate(coin_id, designation, assigned_tier, *, purpose):
        assignments.append((coin_id, designation, assigned_tier, purpose))
        row = next(item for item in rows if item["coin_id"] == coin_id)
        row.update(
            designation=designation,
            assigned_tier=assigned_tier,
            purpose=purpose,
        )
        return True

    modules["database"].set_coin_designation = designate
    modules["database"].get_runtime_mutation_lease = lambda: {
        "active": 1,
        "owner_run_id": "run-live",
        "network": "mainnet",
        "expires_at": "2026-08-22T12:01:00.000000Z",
    }
    trade_ids = [character * 64 for character in "abc"]
    intent_ids = [f"intent-{index}" for index in range(3)]
    creations = []
    cancellations = []

    class Manager:
        def create_offer_with_retry(self, offer_dict, **kwargs):
            index = len(creations)
            creations.append((offer_dict, kwargs))
            return {
                "success": True,
                "trade_id": trade_ids[index],
                "offer": f"offer1wave{index}",
                "_catalyst_intent_id": intent_ids[index],
                "locked_coin_id": kwargs["selected_coin_id"],
            }

        def cancel_offers(self, ids, **kwargs):
            cancellations.append((ids, kwargs))
            return {ids[0]: {"outcome": "CANCEL_CONFIRMED"}}

    modules["offer_manager"].OfferManager = Manager
    legacy = []
    modules["database"].add_offer = lambda **kwargs: legacy.append(kwargs) or True
    modules["database"].update_offer_bech32 = lambda *_args: True
    visible = []
    modules["database"].record_offer_intent_visibility = (
        lambda intent_id, **kwargs: visible.append((intent_id, kwargs))
        or {"intent": {"intent_id": intent_id}}
    )
    bound = []
    modules["database"].bind_refresh_lineage = (
        lambda parent, child: bound.append((parent, child)) or {"idempotent": False}
    )
    committed = []
    modules["database"].commit_refresh_lineage_completion = (
        lambda parent: committed.append(parent) or {"committed": True}
    )
    modules["offer_reconciliation"].reconcile_offer = lambda *_args, **_kwargs: {
        "classification": "CANCELLED_PROVEN"
    }
    publications = []

    class Publisher:
        def enable_durable_outbox(self, **_kwargs):
            return None

        def queue_post(self, offer, trade_id, force=False):
            publications.append(("queue", offer, trade_id, force))

        def flush_queue(self, flush_all=False):
            publications.append(("flush", flush_all))
            return {"posted": 1, "failed": 0, "skipped": 0, "requeued": 0}

    modules["dexie_manager"].DexieManager = Publisher
    operations = []

    def mutate(operation, effect):
        operations.append(operation)
        return {"result": effect()}

    runtime = lab.CatalystLabRuntime(modules)
    inventory = runtime.inventory(now=now)
    result = runtime.replacement(
        mutate,
        inventory=inventory,
        mid_price=Decimal("0.00001234"),
        trade_size_xch=Decimal("0.001"),
        spread_fraction=Decimal("0.5"),
    )

    assert operations == [
        "replacement_create_0",
        "replacement_publish_0",
        "replacement_create_1",
        "replacement_publish_1",
        "replacement_cancel_0",
        "replacement_create_2",
        "replacement_publish_2",
        "replacement_cancel_1",
        "replacement_cancel_2",
    ]
    assert [item[3] for item in assignments] == [
        "lifecycle",
        "replacement",
        "replacement",
    ]
    assert [call[1]["creation_context"]["purpose"] for call in creations] == [
        "normal_lifecycle",
        "replacement",
        "replacement",
    ]
    assert [call[1]["selected_coin_id"] for call in creations] == [
        "1" * 64,
        "2" * 64,
        "3" * 64,
    ]
    assert bound == [("intent-0", "intent-1"), ("intent-1", "intent-2")]
    assert committed == ["intent-0", "intent-1"]
    assert len(legacy) == 3
    assert len(visible) == 3
    assert result == {
        "success": True,
        "stage": "replacement",
        "count": 3,
        "wave_count": 2,
        "classification": "REPLACEMENT_LINEAGE_PROVEN",
    }


def test_replacement_uses_fresh_trial_after_pre_effect_failure_is_terminal():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    asset_id = "a" * 64
    base_slot = f"test7-replacement:{asset_id}"
    modules["database"].get_offer_intents_for_registry = lambda: [
        {
            "intent_id": "root",
            "slot_key": base_slot,
            "generation": 0,
            "purpose": "normal_lifecycle",
            "lifecycle_state": "terminal",
        },
        {
            "intent_id": "failed-child",
            "slot_key": base_slot,
            "generation": 1,
            "purpose": "replacement",
            "lifecycle_state": "creation_failed",
        },
    ]
    runtime = lab.CatalystLabRuntime(modules)
    inventory = {"sbx": {"asset_id": asset_id}}

    assert runtime._completed_replacement(inventory) is None
    assert runtime._replacement_slot_key(inventory) == f"{base_slot}:trial:1"


def test_fill_self_takes_through_guarded_rpc_and_proves_disjoint_assets(monkeypatch):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    maker_coin = "1" * 64
    sbx_coin = "2" * 64
    rows = [
        {
            "coin_id": maker_coin,
            "amount_mojos": 2_000_000_000,
            "status": "free",
            "trade_id": None,
            "designation": "unknown",
            "assigned_tier": "none",
            "purpose": None,
        }
    ]
    modules["database"].get_free_coins = lambda wallet_type: (
        rows if wallet_type == "xch" else []
    )
    modules["database"].get_offer_intents_for_registry = lambda: []
    modules["database"].get_stability_startup_recovery_snapshot = (
        _clean_safety_snapshot
    )

    def designate(coin_id, designation, assigned_tier, *, purpose):
        rows[0].update(
            designation=designation,
            assigned_tier=assigned_tier,
            purpose=purpose,
        )
        return coin_id == maker_coin

    modules["database"].set_coin_designation = designate
    creation_calls = []

    class Manager:
        def create_offer_with_retry(self, offer_dict, **kwargs):
            creation_calls.append((offer_dict, kwargs))
            return {
                "success": True,
                "trade_id": "a" * 64,
                "offer": "offer1fill",
                "_catalyst_intent_id": "intent-fill",
                "locked_coin_id": maker_coin,
            }

        def cancel_offers(self, ids, **_kwargs):
            return {ids[0]: {"outcome": "CANCEL_CONFIRMED"}}

    modules["offer_manager"].OfferManager = Manager
    modules["database"].add_offer = lambda **_kwargs: True
    modules["database"].update_offer_bech32 = lambda *_args: True
    monkeypatch.setattr(
        lab, "_unsigned_self_take_offer_text", lambda _offer: "offer1unsigned"
    )
    rpc_calls = []

    def take(endpoint, payload, timeout):
        rpc_calls.append((endpoint, payload, timeout))
        if endpoint == "submit_transaction":
            return {}
        return {
            "transaction_id": "b" * 64,
            "summary": {
                "inputs": [
                    {
                        "coin_id": "0x" + maker_coin,
                        "asset": {"asset_id": None},
                    },
                    {
                        "coin_id": "0x" + sbx_coin,
                        "asset": {"asset_id": "a" * 64},
                    },
                ]
            },
            "spend_bundle": {
                "coin_spends": [{"coin": {"amount": 1}}],
                "aggregated_signature": "signature",
            },
        }

    modules["wallet"].rpc = take
    modules["offer_reconciliation"].reconcile_offer = lambda *_args, **_kwargs: {
        "classification": "FILLED_PROVEN"
    }
    operations = []

    def mutate(operation, effect):
        operations.append(operation)
        return {"result": effect()}

    runtime = lab.CatalystLabRuntime(modules)
    result = runtime.fill(
        mutate,
        inventory=runtime.inventory(now=now),
        mid_price=Decimal("0.00001234"),
        trade_size_xch=Decimal("0.001"),
    )

    assert operations == [
        "fill_create_offer",
        "fill_take_offer",
        "fill_submit_transaction",
    ]
    assert creation_calls[0][1]["creation_context"]["purpose"] == "fill_response"
    assert rpc_calls == [
        (
            "take_offer",
            {"offer": "offer1unsigned", "fee": "0", "auto_submit": False},
            60,
        ),
        (
            "submit_transaction",
            {
                "spend_bundle": {
                    "coin_spends": [{"coin": {"amount": 1}}],
                    "aggregated_signature": "signature",
                }
            },
            60,
        ),
    ]
    assert result == {
        "success": True,
        "stage": "fill",
        "count": 1,
        "trade_id": "a" * 64,
        "intent_id": "intent-fill",
        "transaction_id": "b" * 64,
        "classification": "FILLED_PROVEN",
    }


def test_fill_resumes_proven_active_prior_attempt_with_explicit_submit(monkeypatch):
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    asset_id = "a" * 64
    maker_coin = "1" * 64
    sbx_coin = "2" * 64
    old_trade = "c" * 64
    old_intent = "intent-old-fill"
    rows = [
        {
            "coin_id": maker_coin,
            "amount_mojos": 2_000_000_000,
            "status": "free",
            "trade_id": None,
            "designation": "unknown",
            "assigned_tier": "none",
            "purpose": None,
        }
    ]
    intents = [
        {
            "intent_id": old_intent,
            "slot_key": f"test7-fill:{asset_id}",
            "generation": 0,
            "purpose": "fill_response",
            "sage_trade_id": old_trade,
            "selected_coin_ids_json": json.dumps([maker_coin]),
            "lifecycle_state": "visible",
        }
    ]
    modules["database"].get_free_coins = lambda wallet_type: (
        rows if wallet_type == "xch" else []
    )
    modules["database"].get_offer_intents_for_registry = lambda: intents
    modules["database"].get_stability_startup_recovery_snapshot = (
        _clean_safety_snapshot
    )
    modules["database"].get_offer = lambda trade_id: (
        {"offer_bech32": "offer1old", "coin_id": maker_coin}
        if trade_id == old_trade
        else None
    )
    def designate(coin_id, designation, assigned_tier, *, purpose):
        rows[0].update(
            designation=designation,
            assigned_tier=assigned_tier,
            purpose=purpose,
        )
        return coin_id == maker_coin

    modules["database"].set_coin_designation = designate

    class Manager:
        def create_offer_with_retry(self, _offer_dict, **_kwargs):
            raise AssertionError("active fill recovery created a duplicate maker offer")

        def cancel_offers(self, ids, **_kwargs):
            raise AssertionError(f"active fill recovery cancelled {ids!r}")

    modules["offer_manager"].OfferManager = Manager
    modules["database"].add_offer = lambda **_kwargs: True
    modules["database"].update_offer_bech32 = lambda *_args: True
    monkeypatch.setattr(
        lab, "_unsigned_self_take_offer_text", lambda _offer: "offer1unsigned"
    )
    modules["wallet"].get_pending_transactions = lambda: []
    submitted = False

    def rpc(endpoint, _payload, _timeout):
        nonlocal submitted
        if endpoint == "submit_transaction":
            submitted = True
            return {}
        return {
            "transaction_id": "b" * 64,
            "summary": {
                "inputs": [
                    {"coin_id": maker_coin, "asset": {"asset_id": None}},
                    {"coin_id": sbx_coin, "asset": {"asset_id": asset_id}},
                ]
            },
            "spend_bundle": {
                "coin_spends": [{"coin": {"amount": 1}}],
                "aggregated_signature": "signature",
            },
        }

    modules["wallet"].rpc = rpc

    def reconcile(intent_id, **_kwargs):
        if intent_id == old_intent:
            return {
                "classification": "FILLED_PROVEN" if submitted else "ACTIVE_PROVEN"
            }
        return {"classification": "FILLED_PROVEN"}

    modules["offer_reconciliation"].reconcile_offer = reconcile
    operations = []

    def mutate(operation, effect):
        operations.append(operation)
        return {"result": effect()}

    runtime = lab.CatalystLabRuntime(modules)
    result = runtime.fill(
        mutate,
        inventory=runtime.inventory(now=now),
        mid_price=Decimal("0.00001234"),
        trade_size_xch=Decimal("0.001"),
    )

    assert operations == ["fill_take_offer", "fill_submit_transaction"]
    assert result["trade_id"] == old_trade
    assert result["intent_id"] == old_intent
    assert result["classification"] == "FILLED_PROVEN"


def test_soak_samples_identity_history_and_clean_gate_without_wallet_effects():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    modules["database"].get_stability_startup_recovery_snapshot = (
        _clean_safety_snapshot
    )
    operations = []
    sleeps = []

    def mutate(operation, effect):
        operations.append(operation)
        return {"result": effect()}

    result = lab.CatalystLabRuntime(modules).soak(
        mutate,
        samples=3,
        interval_seconds=2,
        sleeper=sleeps.append,
        now_provider=lambda: now,
    )

    assert operations == ["soak_snapshot_0", "soak_snapshot_1", "soak_snapshot_2"]
    assert sleeps == [2, 2]
    assert result == {
        "success": True,
        "stage": "soak",
        "count": 3,
        "classification": "SOAK_STABLE",
    }


def test_soak_clock_is_sampled_after_fresh_identity_read():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    observed = now + timedelta(microseconds=1)
    clock = {"now": now}
    modules = _fake_runtime_modules(now)

    def identity():
        clock["now"] = observed
        return _identity(observed, observed_at_utc=_utc(observed))

    modules["wallet"].get_wallet_identity = identity
    modules["database"].get_stability_startup_recovery_snapshot = (
        _clean_safety_snapshot
    )

    result = lab.CatalystLabRuntime(modules).soak(
        lambda _operation, effect: {"result": effect()},
        samples=2,
        interval_seconds=0,
        now_provider=lambda: clock["now"],
    )

    assert result["classification"] == "SOAK_STABLE"


def test_final_reconcile_requires_terminal_lab_intents_and_terminal_outbox():
    now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    modules = _fake_runtime_modules(now)
    modules["database"].get_stability_startup_recovery_snapshot = (
        _clean_safety_snapshot
    )
    modules["database"].get_offer_intents_for_registry = lambda: [
        {
            "intent_id": "done",
            "slot_key": "test7-fill:" + "a" * 64,
            "lifecycle_state": "terminal",
        },
        {
            "intent_id": "failed-before-creation",
            "slot_key": "test7-replacement:" + "a" * 64,
            "lifecycle_state": "creation_failed",
        },
    ]
    modules["database"].list_publication_outbox = lambda: [
        {"state": "succeeded"},
        {"state": "suppressed"},
    ]
    modules["database"].get_open_offers = lambda **_kwargs: []

    result = lab.CatalystLabRuntime(modules).final_reconcile(now=now)

    assert result == {
        "success": True,
        "stage": "final-reconcile",
        "count": 2,
        "classification": "FINAL_RECONCILIATION_CLEAN",
    }
