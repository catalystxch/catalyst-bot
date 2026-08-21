"""Behavioral contract for Task 11 staged refresh safety.

Each test names the production regression it catches; these tests exercise
planner/database behaviour rather than source text or mock call counts.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

import database
from refresh_safety import plan_refresh


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


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


def _prepare(intent_id: str, *, parent_intent_id: str | None = None, generation=0):
    return database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="run-a",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        asset_id=_sha("asset-a"),
        side="buy",
        tier="inner",
        purpose="ladder",
        slot_key="asset-a:buy:inner",
        generation=generation,
        parent_intent_id=parent_intent_id,
        offered_amount_atomic="100",
        requested_amount_atomic="200",
        selected_coin_ids_json=[_sha(f"coin:{intent_id}")],
        wallet_identity_json={"fingerprint_sha256": _sha("wallet-a"), "network": "mainnet"},
        evidence_json={"source": "task-11-test"},
        prepared_at="2026-08-15T12:00:00.000000Z",
    )


def _confirm(intent_id: str):
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
    blocker = database.record_refresh_lineage_blocker(
        operation_id="refresh-lineage:buy:coverage",
        wallet_fingerprint_hash=_sha("wallet-a"),
        network="mainnet",
        side="buy",
        asset_id=_sha("asset-a"),
        cohort_trade_ids=[_sha("trade:repair-parent")],
        reason_code="REGISTRY_PARENT_MISSING",
    )
    assert blocker["state"] == "blocking"
    latch = database.get_runtime_safety_latch()
    assert latch["state"] == "tripped"
    unresolved = database.resolve_refresh_lineage_blocker(
        operation_id="refresh-lineage:buy:coverage",
        cohort_trade_ids=[_sha("trade:repair-parent")],
    )
    assert unresolved["resolved"] is False
    assert unresolved["reason"] == "cohort_not_repaired"
    blind_clear = database.resolve_runtime_safety_latch(
        expected_generation=latch["generation"],
        resolved_operation_ids=["refresh-lineage:buy:coverage"],
    )
    assert blind_clear["resolved"] is False

    _prepare("repair-parent")
    _confirm("repair-parent")
    repaired = database.resolve_refresh_lineage_blocker(
        operation_id="refresh-lineage:buy:coverage",
        cohort_trade_ids=[_sha("trade:repair-parent")],
    )
    assert repaired["resolved"] is True
    assert database.resolve_refresh_lineage_blocker(
        operation_id="refresh-lineage:buy:coverage",
        cohort_trade_ids=[_sha("trade:repair-parent")],
    )["idempotent"] is True
    final_clear = database.resolve_runtime_safety_latch(
        expected_generation=latch["generation"],
        resolved_operation_ids=["refresh-lineage:buy:coverage"],
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
