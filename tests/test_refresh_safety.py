"""Behavioral contract for Task 11 staged refresh safety.

Each test names the production regression it catches; these tests exercise
planner/database behaviour rather than source text or mock call counts.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

import database
from cancel_outcomes import CANCEL_SUBMITTED_UNCONFIRMED, cancellation_result
from refresh_safety import plan_refresh


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class _TradeIdSubclass(str):
    pass


def _parent(intent_id: str, *, severity: int = 1, slot: str | None = None):
    return {
        "intent_id": intent_id,
        "severity": severity,
        "slot_key": slot or f"asset:buy:{intent_id}",
        "generation": 0,
    }


@pytest.fixture
def isolated_database(tmp_path: Path, monkeypatch):
    """Use a disposable database without importing a wallet backend."""

    original_path = database.DB_PATH
    original_initialized_path = database._db_initialized_path
    database.close_connection()
    database.DB_PATH = str(tmp_path / "refresh.db")
    database._db_initialized_path = ""
    monkeypatch.setattr(
        database,
        "_stability_wall_clock",
        lambda: "2026-08-15T12:00:00.000000Z",
        raising=False,
    )
    try:
        yield
    finally:
        database.close_connection()
        database.DB_PATH = original_path
        database._db_initialized_path = original_initialized_path


def _prepare(
    intent_id: str,
    *,
    parent_intent_id: str | None = None,
    generation=0,
    reserve_selected_coins: bool = False,
    slot_key: str = "asset-a:buy:inner",
    run_id: str = "run-a",
):
    return database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id=run_id,
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        asset_id=_sha("asset-a"),
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key=slot_key,
        generation=generation,
        parent_intent_id=parent_intent_id,
        offered_amount_atomic="100",
        requested_amount_atomic="200",
        selected_coin_ids_json=[_sha(f"coin:{intent_id}")],
        wallet_identity_json={"fingerprint_sha256": _sha("wallet-a"), "network": "mainnet"},
        evidence_json={"source": "task-11-test"},
        prepared_at="2026-08-15T12:00:00.000000Z",
        reserve_selected_coins=reserve_selected_coins,
    )


def _confirm(intent_id: str, *, finalize_selected_coin_reservations: bool = False):
    return database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:confirmed",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=_sha(f"trade:{intent_id}"),
        offer_text_sha256=_sha(f"offer:{intent_id}"),
        wallet_identity_json={"fingerprint_sha256": _sha("wallet-a"), "network": "mainnet"},
        evidence_json={"source": "task-11-test"},
        finalized_at="2026-08-15T12:01:00.000000Z",
        finalize_selected_coin_reservations=finalize_selected_coin_reservations,
    )


def test_refresh_planner_is_a_noop_for_an_empty_target_set():
    """Catches a refresh implementation that manufactures cancellation work."""

    plan = plan_refresh([], overlap_capacity=3, batch_size=2)

    assert plan.mode == "noop"
    assert plan.stage_parent_ids == ()
    assert plan.cancel_parent_ids == ()


def test_refresh_planner_stages_bounded_batches_before_any_cancellation():
    """Catches the historical cancel-first requote ordering."""

    plan = plan_refresh(
        [_parent("p1"), _parent("p2"), _parent("p3")],
        overlap_capacity=3,
        batch_size=2,
    )

    assert plan.mode == "stage"
    assert plan.stage_parent_ids == ("p1", "p2")
    assert plan.cancel_parent_ids == ()
    assert plan.create_child_first is True


def test_refresh_planner_pauses_when_authoritative_overlap_is_exhausted():
    """Catches silent mass cancellation when no overlap capacity exists."""

    plan = plan_refresh([_parent("p1")], overlap_capacity=0, batch_size=1)

    assert plan.mode == "pause"
    assert plan.reason == "overlap_capacity_exhausted"
    assert plan.cancel_parent_ids == ()


def test_refresh_planner_allows_cancel_first_only_for_exact_bool_operator_request():
    """Catches truthy values accidentally authorizing an emergency mass cancel."""

    with pytest.raises(TypeError, match="exact bool"):
        plan_refresh([_parent("p1")], overlap_capacity=0, batch_size=1, operator_mass_cancel=1)

    plan = plan_refresh(
        [_parent("p1"), _parent("p2")],
        overlap_capacity=0,
        batch_size=1,
        operator_mass_cancel=True,
    )
    assert plan.mode == "operator_cancel_first"
    assert plan.cancel_parent_ids == ("p1", "p2")
    assert plan.requires_mutation_authority is True


def test_refresh_planner_orders_equal_batches_deterministically_by_risk_then_identity():
    """Catches nondeterministic batches that change refresh exposure on restart."""

    plan = plan_refresh(
        [_parent("z", severity=1), _parent("a", severity=3), _parent("b", severity=3)],
        overlap_capacity=3,
        batch_size=3,
    )

    assert plan.stage_parent_ids == ("a", "b", "z")


def test_offer_manager_exposes_the_staged_refresh_planner_without_wallet_effects():
    """Catches routine requote bypassing the staged planner at its manager boundary."""

    from offer_manager import OfferManager

    plan = OfferManager.plan_staged_refresh(
        [_parent("p1"), _parent("p2")], overlap_capacity=1, batch_size=2
    )

    assert plan.mode == "stage"
    assert plan.stage_parent_ids == ("p1",)
    assert plan.cancel_parent_ids == ()


def test_parent_cannot_be_cancel_eligible_until_exact_confirmed_child_is_visible(isolated_database):
    """Catches a parent cancellation before child identity/visibility is durable."""

    database.init_database()
    _prepare("parent")
    _confirm("parent")
    _prepare("child", parent_intent_id="parent", generation=1)

    with pytest.raises(ValueError, match="confirmed"):
        database.bind_refresh_lineage("parent", "child")

    _confirm("child")
    database.bind_refresh_lineage("parent", "child")
    assert database.refresh_parent_cancel_eligibility("parent", require_visible=True)["eligible"] is False

    database.record_offer_intent_visibility("child", publication_identity="registry:child")
    eligibility = database.refresh_parent_cancel_eligibility("parent", require_visible=True)
    assert eligibility["eligible"] is True
    assert eligibility["child_trade_id"] == _sha("trade:child")


def test_refresh_lineage_binding_is_idempotent_and_rejects_cross_lineage_rows(isolated_database):
    """Catches a child being attached to a mismatched parent or generation."""

    database.init_database()
    _prepare("parent")
    _confirm("parent")
    _prepare("child", parent_intent_id="parent", generation=1)
    _confirm("child")

    first = database.bind_refresh_lineage("parent", "child")
    replay = database.bind_refresh_lineage("parent", "child")
    assert first["idempotent"] is False
    assert replay["idempotent"] is True
    assert replay["parent"] == first["parent"]
    assert database.get_offer_intent("parent")["child_intent_id"] == "child"
    assert database.get_offer_intent("child")["parent_intent_id"] == "parent"

    _prepare("wrong", parent_intent_id="parent", generation=2)
    _confirm("wrong")
    with pytest.raises(ValueError, match="already bound|generation"):
        database.bind_refresh_lineage("parent", "wrong")


def test_lineage_recovery_is_safe_at_each_durable_crash_boundary(isolated_database):
    """Catches restart paths that lose or duplicate child/visibility lineage state."""

    database.init_database()
    _prepare("parent")
    _confirm("parent")
    _prepare("child", parent_intent_id="parent", generation=1)  # child intent crash
    assert database.get_offer_intent("child")["lifecycle_state"] == "prepared"

    _confirm("child")  # child creation crash
    database.bind_refresh_lineage("parent", "child")
    assert database.refresh_parent_cancel_eligibility("parent", require_visible=True)["eligible"] is False

    database.record_offer_intent_visibility("child", publication_identity="registry:child")  # publication crash
    assert database.refresh_parent_cancel_eligibility("parent", require_visible=True)["eligible"] is True
    assert database.record_offer_intent_visibility("child", publication_identity="registry:child")["idempotent"] is True


def test_visible_parent_selects_exact_next_generation_for_a_replacement_child(isolated_database):
    """Catches visible registry rows being rejected as an unknown generation state."""

    database.init_database()
    _prepare("parent")
    _confirm("parent")
    database.record_offer_intent_visibility("parent", publication_identity="registry:parent")
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=1,
        owner_host="test-host",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now="2026-08-15T12:00:00.000000Z",
    )

    from offer_manager import OfferManager

    resolved = OfferManager._resolve_creation_context_generation(
        {
            "select_next_generation": True,
            "slot_key": "asset-a:buy:inner",
            "parent_intent_id": "parent",
        }
    )
    assert resolved["generation"] == 1
    assert resolved["_authority_run_id"] == "run-a"
    _prepare("visible-child", parent_intent_id="parent", generation=resolved["generation"])
    _confirm("visible-child")
    bound = database.bind_refresh_lineage("parent", "visible-child")
    assert bound["child"]["sage_trade_id"] == _sha("trade:visible-child")


def test_restarted_runtime_can_stage_a_replacement_for_its_exact_visible_parent(
    isolated_database,
):
    """Catches a restart making every inherited live offer impossible to requote."""

    database.init_database()
    _prepare("parent", run_id="run-old")
    _confirm("parent")
    database.record_offer_intent_visibility(
        "parent", publication_identity="registry:parent"
    )
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-new",
        owner_pid=1,
        owner_host="test-host",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now="2026-08-15T12:00:00.000000Z",
    )

    from offer_manager import OfferManager

    resolved = OfferManager._resolve_creation_context_generation(
        {
            "select_next_generation": True,
            "slot_key": "asset-a:buy:inner",
            "parent_intent_id": "parent",
        }
    )
    assert resolved["generation"] == 1
    assert resolved["_authority_run_id"] == "run-new"

    _prepare(
        "replacement",
        parent_intent_id="parent",
        generation=resolved["generation"],
        run_id=resolved["_authority_run_id"],
    )
    _confirm("replacement")
    bound = database.bind_refresh_lineage("parent", "replacement")

    assert bound["parent"]["run_id"] == "run-old"
    assert bound["child"]["run_id"] == "run-new"


def test_lineage_completion_requires_cancel_resolution_and_terminal_proof(isolated_database):
    """Catches a staged parent being retired from absence or a local status string."""

    database.init_database()
    _prepare("parent")
    _confirm("parent")
    _prepare("child", parent_intent_id="parent", generation=1)
    _confirm("child")
    database.bind_refresh_lineage("parent", "child")
    database.record_offer_intent_visibility("child", publication_identity="registry:child")

    pending = database.commit_refresh_lineage_completion("parent")
    assert pending == {"committed": False, "reason": "terminal_proof_missing"}


def test_real_task8_task9_completion_replays_one_exact_lineage_commit(isolated_database):
    """Catches completion tests that replace either durable proof authority with a mock."""

    database.init_database()
    parent_coin = _sha("coin:parent")
    return_coin = _sha("coin:parent-return")
    transaction_id = _sha("transaction:parent-cancel")
    spend_identity = f"sha256:{_sha('spend:parent-cancel')}"
    assert database.upsert_coin(
        parent_coin, "xch", 100, tier="inner",
        designation="tier_active", assigned_tier="inner", purpose="lifecycle",
    )
    _prepare("parent", reserve_selected_coins=True)
    _confirm("parent", finalize_selected_coin_reservations=True)
    _prepare("child", parent_intent_id="parent", generation=1)
    _confirm("child")
    database.bind_refresh_lineage("parent", "child")
    database.record_offer_intent_visibility(
        "child", publication_identity="registry:child"
    )

    parent_trade = _sha("trade:parent")
    cancel_operation = f"cancel:{parent_trade}"
    prepared = database.prepare_offer_cancel(
        operation_id=cancel_operation,
        event_id=f"{cancel_operation}:attempt:1:prepared",
        trade_id=parent_trade,
        intent_id="parent",
        attempt=1,
        wallet_identity_json={
            "wallet_fingerprint_hash": _sha("wallet-a"), "network": "mainnet"
        },
        evidence_json={
            "trade_id": parent_trade,
            "effect_claim_protocol": "durable_cohort_claim_v1",
        },
        prepared_at="2026-08-15T12:02:00.000000Z",
    )
    assert database.claim_offer_cancel_effect(
        operation_id=cancel_operation,
        trade_id=parent_trade,
        attempt=1,
        claimed_at="2026-08-15T12:02:00.000000Z",
    )
    cancel_result = cancellation_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        method="task11_integration",
        raw_response={"success": True},
        transaction_id=transaction_id,
        spend_identity=spend_identity,
    )
    database.finalize_offer_cancel(
        operation_id=cancel_operation,
        event_id=f"{cancel_operation}:attempt:1:finalized",
        trade_id=parent_trade,
        intent_id="parent",
        attempt=1,
        cancel_result=cancel_result,
        wallet_identity_json={
            "wallet_fingerprint_hash": _sha("wallet-a"), "network": "mainnet"
        },
        evidence_json={"trade_id": parent_trade, "cancel_result": cancel_result},
        finalized_at="2026-08-15T12:02:30.000000Z",
    )
    cancel_context = {
        "cohort_id": "cancel-cohort:task11-integration",
        "manifest_sha256": prepared["evidence_sha256"],
        "members": [{
            "intent_id": "parent",
            "trade_id": parent_trade,
            "member_id": "cancel-member:task11-integration",
            "prepared_event_id": f"{cancel_operation}:attempt:1:prepared",
            "selected_coin_ids": [parent_coin],
            "request_timestamp": "2026-08-15T12:02:00.000000Z",
            "transaction_timestamp": "2026-08-15T12:03:00.000000Z",
            "asset_id": _sha("asset-a"),
            "side": "buy",
            "offered_amount_atomic": "100",
            "requested_amount_atomic": "200",
            "offer_text_sha256": _sha("offer:parent"),
            "transaction_id": transaction_id,
            "spend_identity": spend_identity,
        }],
        "auxiliary_coin_ids": [],
    }
    terminal_evidence = {
        "source": "task-9-authoritative-test-proof",
        "trade_id": parent_trade,
        "transaction_id": transaction_id,
    }
    terminal_text = json.dumps(
        terminal_evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    terminal = database.commit_offer_reconciliation(
        intent_id="parent",
        operation_id="reconcile:parent",
        classification="CANCELLED_PROVEN",
        reason_code="AUTHORITATIVE_TERMINAL_PROOF",
        wallet_identity_json={
            "wallet_fingerprint_hash": _sha("wallet-a"), "network": "mainnet"
        },
        evidence_json=terminal_evidence,
        evidence_sha256=hashlib.sha256(terminal_text.encode("utf-8")).hexdigest(),
        transaction_id=transaction_id,
        spend_identity=spend_identity,
        block_height=42,
        coin_rebindings=[{
            "input_coin_id": parent_coin,
            "return_coin_id": return_coin,
            "asset_id": "xch",
            "amount": 100,
        }],
        cancel_context_json=cancel_context,
        reconciled_at="2026-08-15T12:03:00.000000Z",
    )

    # A retry before Task 11's final commit re-verifies the exact durable
    # authorities but cannot manufacture a lineage-commit record.
    first_proof = database.refresh_lineage_completion("parent")
    retry_proof = database.refresh_lineage_completion("parent")
    assert first_proof["complete"] is retry_proof["complete"] is True
    assert retry_proof["terminal"]["event_id"] == terminal["event"]["event_id"]
    assert database.get_refresh_lineage_commit_for_child("child") is None

    first_commit = database.commit_refresh_lineage_completion("parent")
    # Simulate loss of the successful response after the final commit, then retry.
    replay_proof = database.refresh_lineage_completion("parent")
    replay_commit = database.commit_refresh_lineage_completion("parent")
    expected_tuple = {
        "parent_intent_id": "parent",
        "child_intent_id": "child",
        "cancel_event_id": f"{cancel_operation}:attempt:1:reconciled",
        "terminal_event_id": terminal["event"]["event_id"],
    }
    assert replay_proof["complete"] is True
    assert first_commit["idempotent"] is False
    assert replay_commit["idempotent"] is True
    assert {
        key: first_commit["commit"][key] for key in expected_tuple
    } == expected_tuple
    assert replay_commit["commit"] == first_commit["commit"]
    assert database.get_refresh_lineage_commit_for_child("child") == first_commit["commit"]
    assert database.get_pending_refresh_lineage_parent_ids(
        asset_id=_sha("asset-a"), side="buy", limit=8
    ) == []


def test_incomplete_refresh_parent_coverage_trips_the_durable_mutation_latch(
    isolated_database, monkeypatch
):
    """Catches a requote staging known parents while silently skipping an open row."""

    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=1,
        owner_host="test-host",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now="2026-08-15T12:00:00.000000Z",
    )
    from offer_manager import OfferManager

    monkeypatch.setattr("offer_manager.cfg.CAT_ASSET_ID", _sha("asset-a"))
    manager = OfferManager.__new__(OfferManager)
    parents, pause = manager._collect_staged_refresh_parents(
        [{"trade_id": _sha("unregistered-open-offer")}], "buy"
    )

    assert parents == {}
    assert pause == "registry_parent_missing"
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert "refresh-lineage:buy:coverage" in latch["blocking_operation_ids_json"]


def test_refresh_blocker_requires_exact_repair_proof_before_latch_resolution(isolated_database):
    """Catches synthetic refresh blockers that can never be resolved safely."""

    database.init_database()
    repair_trade = _sha("trade:repair-parent")
    operation_id = database.refresh_lineage_blocker_operation_id(
        reason_code="REGISTRY_PARENT_MISSING", cohort_trade_ids=[repair_trade]
    )
    blocker = database.record_refresh_lineage_blocker(
        operation_id=operation_id,
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        side="buy",
        asset_id=_sha("asset-a"),
        cohort_trade_ids=[repair_trade],
        reason_code="REGISTRY_PARENT_MISSING",
    )
    assert blocker["state"] == "blocking"
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    unresolved = database.resolve_refresh_lineage_blocker(
        operation_id=operation_id, cohort_trade_ids=[repair_trade],
    )
    assert unresolved["resolved"] is False
    assert unresolved["reason"] == "cohort_not_repaired"
    blind_clear = database.resolve_runtime_safety_latch(
        expected_generation=latch["generation"],
        resolved_operation_ids=[operation_id],
    )
    assert blind_clear["resolved"] is False

    _prepare("repair-parent")
    _confirm("repair-parent")
    repaired = database.resolve_refresh_lineage_blocker(
        operation_id=operation_id, cohort_trade_ids=[repair_trade],
    )
    assert repaired["resolved"] is True
    assert database.resolve_refresh_lineage_blocker(
        operation_id=operation_id, cohort_trade_ids=[repair_trade],
    )["idempotent"] is True
    final_clear = database.resolve_runtime_safety_latch(
        expected_generation=latch["generation"],
        resolved_operation_ids=[operation_id],
    )
    assert database.get_runtime_safety_latch()["state"] == "resolved"
    assert final_clear["reason"] == "not_tripped"


def test_refresh_cohort_validation_latches_before_any_eligible_parent_cancel(
    isolated_database, monkeypatch
):
    """Catches a valid early parent being cancelled before a later row is proven exact."""

    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=1,
        owner_host="test-host",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now="2026-08-15T12:00:00.000000Z",
    )
    _prepare("parent")
    _confirm("parent")
    _prepare("child", parent_intent_id="parent", generation=1)
    _confirm("child")
    database.bind_refresh_lineage("parent", "child")
    database.record_offer_intent_visibility("child", publication_identity="registry:child")

    from offer_manager import OfferManager

    monkeypatch.setattr("offer_manager.cfg.CAT_ASSET_ID", _sha("asset-a"))
    manager = OfferManager.__new__(OfferManager)
    cancelled = []
    manager.cancel_offers = lambda ids, **_kwargs: cancelled.extend(ids)
    parent_trade = _sha("trade:parent")
    missing_trade = _sha("later-unregistered-open-offer")

    parents, pause = manager._collect_staged_refresh_parents(
        [{"trade_id": parent_trade}, {"trade_id": missing_trade}], "buy"
    )

    assert parents == {}
    assert pause == "registry_parent_missing"
    assert cancelled == []
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"


def test_requote_resumes_eligible_lineage_before_zero_spare_capacity_gate(
    isolated_database, monkeypatch
):
    """Catches zero overlap capacity stranding Task 8 cancellation behind planning."""

    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a",
        owner_pid=1,
        owner_host="test-host",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now="2026-08-15T12:00:00.000000Z",
    )
    _prepare("parent")
    _confirm("parent")
    _prepare("child", parent_intent_id="parent", generation=1)
    _confirm("child")
    database.bind_refresh_lineage("parent", "child")
    database.record_offer_intent_visibility("child", publication_identity="registry:child")

    from offer_manager import OfferManager

    monkeypatch.setattr("offer_manager.cfg.CAT_ASSET_ID", _sha("asset-a"))
    parent_trade = _sha("trade:parent")
    monkeypatch.setattr("offer_manager.get_open_offers", lambda **_kwargs: [{"trade_id": parent_trade}])
    monkeypatch.setattr(database, "get_free_coins", lambda _wallet_type: [])
    manager = OfferManager.__new__(OfferManager)
    manager._sort_open_offers_for_requote = lambda offers, *_args, **_kwargs: offers
    cancelled = []
    manager.cancel_offers = lambda ids, **_kwargs: cancelled.extend(ids) or {}

    result = manager.requote_side("buy", Decimal("1"))

    assert cancelled == [parent_trade]
    assert result["refresh_paused"] is True


def test_replaying_task8_reconciled_cancel_waits_for_task9_proof(
    isolated_database, monkeypatch
):
    """Catches a restart issuing a second cancel after Task 8 reconciliation."""

    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a", owner_pid=1, owner_host="test-host",
        wallet_fingerprint_hash=_sha("wallet-a"), network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now="2026-08-15T12:00:00.000000Z",
    )
    _prepare("parent")
    _confirm("parent")
    _prepare("child", parent_intent_id="parent", generation=1)
    _confirm("child")
    database.bind_refresh_lineage("parent", "child")
    database.record_offer_intent_visibility("child", publication_identity="registry:child")

    from offer_manager import OfferManager

    monkeypatch.setattr("offer_manager.cfg.CAT_ASSET_ID", _sha("asset-a"))
    monkeypatch.setattr(
        database, "get_offer_operation_events",
        lambda _operation_id: [{
            "blocks_mutation": 0, "phase": "RECONCILED",
            "outcome": "CANCEL_CONFIRMED",
        }],
    )
    manager = OfferManager.__new__(OfferManager)
    cancelled = []
    manager.cancel_offers = lambda ids, **_kwargs: cancelled.extend(ids)

    parents, pause = manager._collect_staged_refresh_parents(
        [{"trade_id": _sha("trade:parent")}], "buy"
    )

    assert parents == {}
    assert pause == "awaiting_task8_task9"
    assert cancelled == []


def test_pending_lineage_query_finds_parent_when_only_its_live_child_remains(
    isolated_database,
):
    """Catches completion being gated on the terminal parent remaining open."""

    database.init_database()
    _prepare("absent-parent")
    _confirm("absent-parent")
    _prepare("live-child", parent_intent_id="absent-parent", generation=1)
    _confirm("live-child")
    database.bind_refresh_lineage("absent-parent", "live-child")
    database.record_offer_intent_visibility("live-child", publication_identity="registry:child")

    assert database.get_pending_refresh_lineage_parent_ids(
        asset_id=_sha("asset-a"), side="buy", limit=8
    ) == ["absent-parent"]


def test_parent_absent_completion_resume_replays_before_and_after_commit(
    isolated_database, monkeypatch
):
    """Catches crash recovery leaving a live child blocked after its parent vanished."""

    database.init_database()
    _prepare("absent-parent")
    _confirm("absent-parent")
    _prepare("live-child", parent_intent_id="absent-parent", generation=1)
    _confirm("live-child")
    database.bind_refresh_lineage("absent-parent", "live-child")
    database.record_offer_intent_visibility("live-child", publication_identity="registry:child")

    from offer_manager import OfferManager

    monkeypatch.setattr("offer_manager.cfg.CAT_ASSET_ID", _sha("asset-a"))
    manager = OfferManager.__new__(OfferManager)
    monkeypatch.setattr(
        database, "refresh_lineage_completion",
        lambda _parent_id, **_kwargs: {"complete": True, "reason": "complete"},
    )
    commits = []

    def commit(parent_id):
        commits.append(parent_id)
        if len(commits) == 1:
            raise RuntimeError("crash-before-lineage-commit")
        return {"committed": True, "idempotent": len(commits) > 2}

    monkeypatch.setattr(database, "commit_refresh_lineage_completion", commit)
    with pytest.raises(RuntimeError, match="crash-before-lineage-commit"):
        manager._resume_pending_refresh_lineage_completions("buy")
    assert manager._resume_pending_refresh_lineage_completions("buy") == "awaiting_terminal_projection"
    assert manager._resume_pending_refresh_lineage_completions("buy") == "awaiting_terminal_projection"
    assert commits == ["absent-parent", "absent-parent", "absent-parent"]


def test_refresh_blocker_incidents_are_exact_cohort_scoped_and_replayable(
    isolated_database,
):
    """Catches a resolved refresh blocker preventing a distinct later incident."""

    database.init_database()
    first_trade = _sha("trade:first-incident")
    second_trade = _sha("trade:second-incident")
    first_id = database.refresh_lineage_blocker_operation_id(
        reason_code="REGISTRY_PARENT_MISSING", cohort_trade_ids=[first_trade]
    )
    first = database.record_refresh_lineage_blocker(
        operation_id=first_id, wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet", side="buy", asset_id=_sha("asset-a"),
        cohort_trade_ids=[first_trade], reason_code="REGISTRY_PARENT_MISSING",
    )
    _prepare("first-incident")
    _confirm("first-incident")
    resolved_first = database.resolve_refresh_lineage_blocker(
        operation_id=first["operation_id"], cohort_trade_ids=[first_trade]
    )
    assert resolved_first["resolved"] is True
    resolved_generation = database.get_runtime_safety_latch()["generation"]
    resolved_replay = database.record_refresh_lineage_blocker(
        operation_id=first_id, wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet", side="buy", asset_id=_sha("asset-a"),
        cohort_trade_ids=[first_trade], reason_code="REGISTRY_PARENT_MISSING",
    )
    assert resolved_replay == resolved_first["blocker"]
    assert database.get_runtime_safety_latch()["state"] == "resolved"

    second_id = database.refresh_lineage_blocker_operation_id(
        reason_code="REGISTRY_PARENT_MISSING", cohort_trade_ids=[second_trade]
    )
    assert second_id != first_id
    second = database.record_refresh_lineage_blocker(
        operation_id=second_id, wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet", side="buy", asset_id=_sha("asset-a"),
        cohort_trade_ids=[second_trade], reason_code="REGISTRY_PARENT_MISSING",
    )
    replay = database.record_refresh_lineage_blocker(
        operation_id=second_id, wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet", side="buy", asset_id=_sha("asset-a"),
        cohort_trade_ids=[second_trade], reason_code="REGISTRY_PARENT_MISSING",
    )
    assert second["state"] == replay["state"] == "blocking"
    later_latch = database.get_runtime_safety_latch()
    assert later_latch["state"] == "tripped"
    assert later_latch["generation"] > resolved_generation


def test_all_malformed_refresh_snapshot_latches_without_inventing_a_trade_id(
    isolated_database,
):
    """Catches all-malformed selected rows bypassing the durable mutation latch."""

    database.init_database()
    material = [{"entry_index": 0, "trade_id": None, "tier": "inner"}]
    operation_id = database.refresh_lineage_blocker_operation_id(
        reason_code="REGISTRY_PARENT_MISSING", cohort_trade_ids=[],
        malformed_snapshot_entries=material,
    )
    blocker = database.record_refresh_lineage_blocker(
        operation_id=operation_id, wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet", side="buy", asset_id=_sha("asset-a"),
        cohort_trade_ids=[], malformed_snapshot_entries=material,
        reason_code="REGISTRY_PARENT_MISSING",
    )
    assert blocker["state"] == "blocking"
    assert database.get_runtime_safety_latch()["state"] == "tripped"
    assert database.resolve_refresh_lineage_blocker(
        operation_id=operation_id, cohort_trade_ids=[],
        malformed_snapshot_entries=material,
    )["resolved"] is False
    _prepare("malformed-repair")
    _confirm("malformed-repair")
    repaired = database.resolve_refresh_lineage_blocker(
        operation_id=operation_id, cohort_trade_ids=[],
        malformed_snapshot_entries=material,
        repaired_snapshot_entries=[
            {"entry_index": 0, "trade_id": _sha("trade:malformed-repair")}
        ],
    )
    assert repaired["resolved"] is True
    assert database.resolve_refresh_lineage_blocker(
        operation_id=operation_id, cohort_trade_ids=[],
        malformed_snapshot_entries=material,
        repaired_snapshot_entries=[
            {"entry_index": 0, "trade_id": _sha("trade:malformed-repair")}
        ],
    )["idempotent"] is True


@pytest.mark.parametrize("collision", ["duplicate-repair", "valid-cohort"])
def test_malformed_snapshot_repair_requires_one_to_one_trade_mapping(
    isolated_database, collision,
):
    """Catches two malformed indexes or a valid row sharing one repaired trade."""

    database.init_database()
    _prepare("valid-cohort", slot_key="asset-a:buy:valid")
    _confirm("valid-cohort")
    _prepare("repair-a", slot_key="asset-a:buy:repair-a")
    _confirm("repair-a")
    _prepare("repair-b", slot_key="asset-a:buy:repair-b")
    _confirm("repair-b")
    valid_trade = _sha("trade:valid-cohort")
    repair_a = _sha("trade:repair-a")
    repair_b = _sha("trade:repair-b")
    material = [
        {"entry_index": 0, "entry_sha256": _sha("malformed:0")},
        {"entry_index": 1, "entry_sha256": _sha("malformed:1")},
    ]
    operation_id = database.refresh_lineage_blocker_operation_id(
        reason_code="REGISTRY_PARENT_MISSING",
        cohort_trade_ids=[valid_trade],
        malformed_snapshot_entries=material,
    )
    database.record_refresh_lineage_blocker(
        operation_id=operation_id,
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        side="buy",
        asset_id=_sha("asset-a"),
        cohort_trade_ids=[valid_trade],
        malformed_snapshot_entries=material,
        reason_code="REGISTRY_PARENT_MISSING",
    )
    colliding_trade = repair_a if collision == "duplicate-repair" else valid_trade
    invalid = database.resolve_refresh_lineage_blocker(
        operation_id=operation_id,
        cohort_trade_ids=[valid_trade],
        malformed_snapshot_entries=material,
        repaired_snapshot_entries=[
            {"entry_index": 0, "trade_id": colliding_trade},
            {"entry_index": 1, "trade_id": repair_a},
        ],
    )
    assert invalid["resolved"] is False
    assert database.get_runtime_safety_latch()["state"] == "tripped"

    exact = database.resolve_refresh_lineage_blocker(
        operation_id=operation_id,
        cohort_trade_ids=[valid_trade],
        malformed_snapshot_entries=material,
        repaired_snapshot_entries=[
            {"entry_index": 0, "trade_id": repair_a},
            {"entry_index": 1, "trade_id": repair_b},
        ],
    )
    assert exact["resolved"] is True
    assert exact["idempotent"] is False
    replay = database.resolve_refresh_lineage_blocker(
        operation_id=operation_id,
        cohort_trade_ids=[valid_trade],
        malformed_snapshot_entries=material,
        repaired_snapshot_entries=[
            {"entry_index": 0, "trade_id": repair_a},
            {"entry_index": 1, "trade_id": repair_b},
        ],
    )
    assert replay["resolved"] is True
    assert replay["idempotent"] is True


def test_all_malformed_open_rows_latch_before_any_refresh_effect(
    isolated_database, monkeypatch
):
    """Catches no-ID cohorts falling through to cancellation or child creation."""

    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a", owner_pid=1, owner_host="test-host",
        wallet_fingerprint_hash=_sha("wallet-a"), network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now="2026-08-15T12:00:00.000000Z",
    )
    from offer_manager import OfferManager

    monkeypatch.setattr("offer_manager.cfg.CAT_ASSET_ID", _sha("asset-a"))
    manager = OfferManager.__new__(OfferManager)
    cancelled = []
    manager.cancel_offers = lambda ids, **_kwargs: cancelled.extend(ids)

    parents, pause = manager._collect_staged_refresh_parents(
        [{"trade_id": None, "tier": "inner"}], "buy"
    )

    assert parents == {}
    assert pause == "registry_parent_missing"
    assert cancelled == []
    assert database.get_runtime_safety_latch()["state"] == "tripped"


@pytest.mark.parametrize(
    "candidate",
    [
        "not-a-canonical-trade-id",
        _sha("upper-case-trade-id").upper(),
        _TradeIdSubclass(_sha("string-subclass-trade-id")),
        "f" * 4097,
    ],
    ids=["nonhex", "uppercase", "str-subclass", "oversized"],
)
def test_malformed_nonempty_trade_id_latches_before_cancel_or_create(
    isolated_database, monkeypatch, candidate,
):
    """Catches malformed nonempty identities escaping before durable latching."""

    database.init_database()
    database.acquire_runtime_mutation_lease(
        owner_run_id="run-a", owner_pid=1, owner_host="test-host",
        wallet_fingerprint_hash=_sha("wallet-a"), network="mainnet",
        lease_expires_at="2026-08-15T12:10:00.000000Z",
        now="2026-08-15T12:00:00.000000Z",
    )
    from offer_manager import OfferManager

    monkeypatch.setattr("offer_manager.cfg.CAT_ASSET_ID", _sha("asset-a"))
    monkeypatch.setattr(
        "offer_manager.get_open_offers",
        lambda **_kwargs: [{"trade_id": candidate, "tier": "inner"}],
    )
    manager = OfferManager.__new__(OfferManager)
    manager._sort_open_offers_for_requote = lambda offers, *_args, **_kwargs: offers
    cancelled = []
    created = []
    manager.cancel_offers = lambda ids, **_kwargs: cancelled.extend(ids)
    manager.create_ladder = lambda *_args, **_kwargs: created.append("create") or []

    result = manager.requote_side("buy", Decimal("1"))

    assert result["refresh_paused"] is True
    assert cancelled == []
    assert created == []
    material = [{
        "entry_index": 0,
        "entry_sha256": hashlib.sha256(str.encode(candidate, "utf-8")).hexdigest(),
    }]
    operation_id = database.refresh_lineage_blocker_operation_id(
        reason_code="refresh-lineage:buy:coverage",
        cohort_trade_ids=[],
        malformed_snapshot_entries=material,
    )
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    assert operation_id in json.loads(latch["blocking_operation_ids_json"])
    assert database.resolve_refresh_lineage_blocker(
        operation_id=operation_id,
        cohort_trade_ids=[],
        malformed_snapshot_entries=material,
    )["resolved"] is False

    _prepare("malformed-candidate-repair")
    _confirm("malformed-candidate-repair")
    repaired = database.resolve_refresh_lineage_blocker(
        operation_id=operation_id,
        cohort_trade_ids=[],
        malformed_snapshot_entries=material,
        repaired_snapshot_entries=[{
            "entry_index": 0,
            "trade_id": _sha("trade:malformed-candidate-repair"),
        }],
    )
    assert repaired["resolved"] is True
