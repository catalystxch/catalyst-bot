"""Behavioral contract for Task 11 staged refresh safety.

Each test names the production regression it catches; these tests exercise
planner/database behaviour rather than source text or mock call counts.
"""

from __future__ import annotations

import hashlib
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
