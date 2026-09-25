"""Legacy campaign cancel fees cannot disappear while effects are unresolved."""

from importlib import import_module
import json

import pytest

import api_server  # noqa: F401 - establish this file's isolated app graph
from bootstrap_fee_fixture import approved_bootstrap  # noqa: F401
from cancel_outcomes import (
    CANCEL_SUBMITTED_UNCONFIRMED,
    CANCEL_UNKNOWN,
    cancellation_result,
)
import fee_approval_test_utils as utils


def _seed_cancel(state, outcome=CANCEL_SUBMITTED_UNCONFIRMED, reserved=False,
                 fees=(40, 40), claimed=True, campaign_id=None):
    database = import_module("database")
    trades = ["a" * 64, "b" * 64]
    roots = ["c" * 64, "d" * 64]
    members = []
    # Both members repeat one 40-mojo fee. The legacy branch has no reservation;
    # the protected branch is a control that must not double-count its hold.
    for index, trade_id in enumerate(trades):
        intent_id = str(index + 1) * 64
        create_operation = f"create:{intent_id}"
        database.prepare_offer_intent(
            intent_id=intent_id,
            operation_id=create_operation,
            event_id=f"{create_operation}:prepared",
            run_id="legacy-fee-recovery",
            wallet_fingerprint_hash=import_module("mutation_gate").wallet_fingerprint_hash(
                736588221
            ),
            network="mainnet",
            asset_id=utils.ASSET,
            side="buy",
            tier="inner",
            purpose=f"bootstrap:{campaign_id or state['campaign_id']}:revision:0",
            offered_amount_atomic="1000",
            requested_amount_atomic="2000",
            selected_coin_ids_json=[roots[index]],
            wallet_identity_json={"binding_digest": "f" * 64},
            evidence_json={"canonical_intent_sha256": intent_id},
            prepared_at="2026-09-22T12:00:00Z",
        )
        database.finalize_offer_intent(
            intent_id=intent_id,
            operation_id=create_operation,
            event_id=f"{create_operation}:confirmed",
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=trade_id,
            offer_text_sha256=str(index + 3) * 64,
            wallet_identity_json={"binding_digest": "f" * 64},
            evidence_json={"effect_attempted": True},
            finalized_at="2026-09-22T12:00:01Z",
        )
        operation_id = f"cancel:{trade_id}"
        members.append({
            "operation_id": operation_id,
            "prepared_event_id": f"{operation_id}:attempt:1:prepared",
            "trade_id": trade_id,
            "intent_id": intent_id,
            "attempt": 1,
        })
    manifest = database.canonical_offer_cancel_cohort_manifest(members)
    identity = {"snapshot": {"binding": {
        "backend": "sage", "fingerprint": 736588221, "network_id": "mainnet",
    }}}
    requests = []
    for index, member in enumerate(manifest["members"]):
        requests.append({
            "operation_id": member["operation_id"],
            "event_id": member["prepared_event_id"],
            "trade_id": member["trade_id"],
            "intent_id": member["intent_id"],
            "attempt": member["attempt"],
            "wallet_identity_json": identity,
            "evidence_json": {
                "trade_id": member["trade_id"],
                "intent_id": member["intent_id"],
                "operation_id": member["operation_id"],
                "attempt": member["attempt"],
                "member_id": member["member_id"],
                "cohort_id": manifest["cohort_id"],
                "cohort_size": manifest["member_count"],
                "reason": "coin_prep_cancel_all" if reserved else "manual_cancel_all",
                "continuation_journal_sha256": "f" * 64,
                "effect_claim_protocol": "durable_cohort_claim_v1",
                "wallet_effect": {
                    "secure": True,
                    "timeout": 60,
                    "fee_mojos": fees[index],
                    "batch": {
                        "protocol": "sage_native_cancel_offers_zero_plus_fee_v1",
                        "trade_ids": trades,
                        "source_coin_ids": roots,
                        "fee_coin_id": "9" * 64,
                    },
                },
            },
        })
    database.prepare_offer_cancel_cohort(
        manifest_json=manifest, member_requests_json=requests,
    )
    if reserved:
        database.reserve_coin_prep_cancellation_fee(
            approval_id=state["approval"]["approval_id"],
            scope_sha256=state["approval"]["scope_sha256"],
            plan_sha256=state["approval"]["plan_sha256"],
            manifest_json=manifest,
            batch_contract={
                **requests[0]["evidence_json"]["wallet_effect"]["batch"],
                "fee_mojos": 40,
            },
            final_quote={
                "available": True, "fee_mojos": 40, "source": "coinset",
                "cost": 123456, "target_seconds": 300,
                "observed_at": state["now"], "expires_at": state["now"] + 60,
            },
        )
    if claimed:
        database.claim_offer_cancel_cohort_effects(manifest_json=manifest)
    if outcome is None:
        return manifest, identity
    result = cancellation_result(
        outcome,
        method="sage_native_cancel_offers",
        raw_response={"success": True, "transaction_id": "8" * 64}
        if outcome == CANCEL_SUBMITTED_UNCONFIRMED else {},
        transaction_id="8" * 64 if outcome == CANCEL_SUBMITTED_UNCONFIRMED else "",
        error="ambiguous timeout" if outcome == CANCEL_UNKNOWN else "",
    )
    database.finalize_offer_cancel_cohort(
        manifest_json=manifest,
        member_requests_json=[{
            "operation_id": member["operation_id"],
            "event_id": f"{member['operation_id']}:attempt:1:finalized",
            "trade_id": member["trade_id"],
            "intent_id": member["intent_id"],
            "attempt": member["attempt"],
            "cancel_result": result,
            "wallet_identity_json": identity,
            "evidence_json": {
                "trade_id": member["trade_id"],
                "attempt": 1,
                "cohort_id": manifest["cohort_id"],
                "member_id": member["member_id"],
                "effect_attempted": True,
                "cancel_result": result,
            },
        } for member in manifest["members"]],
    )
    return manifest, identity


@pytest.mark.parametrize("outcome", [CANCEL_SUBMITTED_UNCONFIRMED, CANCEL_UNKNOWN])
@pytest.mark.parametrize("reserved", [False, True], ids=["legacy", "protected"])
def test_unresolved_campaign_cancel_fee_remains_committed_once_after_restart(
    approved_bootstrap, outcome, reserved
):
    database = import_module("database")
    state = approved_bootstrap
    manifest, _ = _seed_cancel(state, outcome, reserved)

    before = utils._counts()
    for _read in range(2):
        database.close_connection()
        blockers = database.get_unresolved_offer_operation_blockers()
        assert {row["operation_id"] for row in blockers} == {
            member["operation_id"] for member in manifest["members"]
        }
        accounting = database.get_coin_prep_fee_approval_status(
            state["approval"]["approval_id"]
        )
        assert utils._counts() == before, "readback cannot manufacture consent or effects"
        # Exactly one native effect, not zero fees and not one fee per member.
        assert accounting["held_fee_mojos"] == 40, accounting
        assert accounting["spent_fee_mojos"] == 0
        assert accounting["committed_fee_mojos"] == 40
        assert accounting["unresolved_operation_count"] >= 1


@pytest.mark.parametrize("claimed,expected", [(False, 0), (True, 40)])
def test_legacy_crash_at_claim_boundary_preserves_commitment(
    approved_bootstrap, claimed, expected
):
    database = import_module("database")
    _seed_cancel(approved_bootstrap, outcome=None, claimed=claimed)
    database.close_connection()
    status = database.get_coin_prep_fee_approval_status(
        approved_bootstrap["approval"]["approval_id"]
    )
    assert status["held_fee_mojos"] == expected
    assert status["committed_fee_mojos"] == expected


def test_legacy_rejection_releases_only_after_authoritative_cohort_proof(approved_bootstrap):
    database = import_module("database")
    manifest, _ = _seed_cancel(approved_bootstrap)
    approval_id = approved_bootstrap["approval"]["approval_id"]
    assert database.get_coin_prep_fee_approval_status(approval_id)["held_fee_mojos"] == 40
    database.reconcile_rejected_offer_cancel_cohort(
        manifest_json=manifest, transaction_id="8" * 64,
        relay_evidence_json={
            "status": "rejected", "transaction_id": "8" * 64,
            "reason_code": "INVALID_FEE_TOO_CLOSE_TO_ZERO",
            "evidence_sha256": "7" * 64, "source": "sage_native_log",
            "source_file": "app.log.2026-09-22",
        },
        wallet_fingerprint_hash=import_module("mutation_gate").wallet_fingerprint_hash(736588221),
        network="mainnet",
    )
    for _ in range(2):
        database.close_connection()
        status = database.get_coin_prep_fee_approval_status(approval_id)
        assert status["held_fee_mojos"] == status["spent_fee_mojos"] == 0
        assert status["unresolved_operation_count"] == 0


@pytest.mark.parametrize("fees", [(40, 41), (True, True), (-1, -1), ("40", "40")])
def test_invalid_legacy_cohort_fee_evidence_fails_closed(approved_bootstrap, fees):
    database = import_module("database")
    _seed_cancel(approved_bootstrap, outcome=None, fees=fees)
    with pytest.raises(ValueError):
        database.get_coin_prep_fee_approval_status(approved_bootstrap["approval"]["approval_id"])


def test_other_campaign_cancellation_does_not_consume_this_scope(approved_bootstrap):
    database = import_module("database")
    _seed_cancel(approved_bootstrap, campaign_id="0" * 64)
    status = database.get_coin_prep_fee_approval_status(approved_bootstrap["approval"]["approval_id"])
    assert status["committed_fee_mojos"] == 0
    assert status["unresolved_operation_count"] == 0


def _confirm_cohort(manifest, identity):
    database = import_module("database")
    for member in manifest["members"]:
        database.append_offer_operation_event(
            event_id=f"{member['operation_id']}:attempt:1:reconciled",
            operation_id=member["operation_id"], intent_id=member["intent_id"],
            operation_type="CANCEL", attempt=1, phase="RECONCILED",
            outcome="CANCEL_CONFIRMED", request_timestamp="2026-09-22T12:00:02Z",
            wallet_identity_json=identity, transaction_id="8" * 64,
            evidence_json={
                "trade_id": member["trade_id"], "cohort_id": manifest["cohort_id"],
                "member_id": member["member_id"], "effect_attempted": True,
                "exact_subset": {
                    "cancel_context": {"cohort_id": manifest["cohort_id"]},
                    "classification": {"classification": "CANCELLED_PROVEN", "fee_mojos": 40},
                },
            },
            reason_code="AUTHORITATIVE_TERMINAL_PROOF", blocks_mutation=False,
            created_at="2026-09-22T12:00:02Z",
        )


def test_authoritatively_confirmed_legacy_cohort_moves_hold_to_spend_once(approved_bootstrap):
    database = import_module("database")
    manifest, identity = _seed_cancel(approved_bootstrap)
    approval_id = approved_bootstrap["approval"]["approval_id"]
    assert database.get_coin_prep_fee_approval_status(approval_id)["held_fee_mojos"] == 40
    _confirm_cohort(manifest, identity)
    before = utils._counts()
    for _ in range(2):
        database.close_connection()
        status = database.get_coin_prep_fee_approval_status(approval_id)
        assert status["held_fee_mojos"] == 0
        assert status["spent_fee_mojos"] == status["committed_fee_mojos"] == 40
        assert status["unresolved_operation_count"] == 0
        assert utils._counts() == before


def test_protected_confirmation_before_ledger_settlement_is_not_double_committed(approved_bootstrap):
    database = import_module("database")
    manifest, identity = _seed_cancel(approved_bootstrap, reserved=True)
    _confirm_cohort(manifest, identity)
    approval_id = approved_bootstrap["approval"]["approval_id"]
    # Simulate restart after journal reconciliation but before fee settlement.
    database.close_connection()
    pending = database.get_coin_prep_fee_approval_status(approval_id)
    assert pending["committed_fee_mojos"] == 40
    assert database.get_bootstrap_campaign_authoritative_fee_spent_mojos(
        approved_bootstrap["campaign_id"]
    ) == 40
    database.record_coin_prep_cancellation_fee_outcome(manifest)
    database.record_coin_prep_cancellation_fee_outcome(manifest)
    database.close_connection()
    settled = database.get_coin_prep_fee_approval_status(approval_id)
    assert settled["held_fee_mojos"] == 0
    assert settled["spent_fee_mojos"] == settled["committed_fee_mojos"] == 40


@pytest.mark.parametrize("reader", ["status", "approval", "scope"])
def test_concurrent_confirmation_cannot_mix_old_hold_with_new_spend(approved_bootstrap, monkeypatch, reader):
    database = import_module("database")
    manifest, identity = _seed_cancel(approved_bootstrap)
    original_connect = database._stability_read_only_connection
    committed = []

    class ConcurrentRead:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, sql, *args):
            # Real separate writer commits once, after the outer status snapshot
            # has started but before its authoritative spend aggregation.
            if "SELECT COALESCE(SUM(reservation.fee_mojos), 0)" in sql and not committed:
                committed.append(True)
                _confirm_cohort(manifest, identity)
            return self.connection.execute(sql, *args)

    monkeypatch.setattr(database, "_stability_read_only_connection",
                        lambda: ConcurrentRead(original_connect()))
    approval = approved_bootstrap["approval"]
    read = {
        "status": lambda: database.get_coin_prep_fee_approval_status(approval["approval_id"]),
        "approval": lambda: database.get_fee_approval(approval["approval_id"]),
        "scope": lambda: database.get_fee_scope_budget(approval["scope_sha256"]),
    }[reader]
    status = read()
    assert committed == [True]
    assert status["committed_fee_mojos"] == 40
    assert status["held_fee_mojos"] == 40
    assert status["spent_fee_mojos"] == 0
    following = read()
    assert following["held_fee_mojos"] == 0
    assert following["spent_fee_mojos"] == following["committed_fee_mojos"] == 40


def test_legacy_commitment_participates_in_atomic_next_reservation_cap(approved_bootstrap):
    database = import_module("database")
    _seed_cancel(approved_bootstrap)
    approval = approved_bootstrap["approval"]
    status = database.get_coin_prep_fee_approval_status(approval["approval_id"])
    before = utils._counts()
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        database.reserve_approved_fee(
            approval_id=approval["approval_id"], scope_sha256=approval["scope_sha256"],
            plan_sha256=approval["plan_sha256"], operation_id="e" * 64,
            fee_mojos=status["total_fee_mojos"] - 20, cancellation=True,
        )
    assert utils._counts() == before


def test_legacy_adapter_failure_is_not_no_effect_proof(approved_bootstrap):
    database = import_module("database")
    _seed_cancel(approved_bootstrap, outcome="CANCEL_FAILED")
    status = database.get_coin_prep_fee_approval_status(approved_bootstrap["approval"]["approval_id"])
    assert status["held_fee_mojos"] == 40
    assert status["unresolved_operation_count"] == 1


def test_unclaimed_legacy_no_effect_finalization_does_not_invent_spend(approved_bootstrap):
    database = import_module("database")
    manifest, identity = _seed_cancel(approved_bootstrap, outcome=None, claimed=False)
    result = cancellation_result("CANCEL_FAILED", method="test", error="CANCEL_REJECTED")
    for member in manifest["members"]:
        database.finalize_offer_cancel(
            operation_id=member["operation_id"], event_id=f"{member['operation_id']}:attempt:1:finalized",
            trade_id=member["trade_id"], intent_id=member["intent_id"], attempt=1,
            cancel_result=result, wallet_identity_json=identity,
            evidence_json={"effect_attempted": False, "cancel_result": result,
                           "cohort_id": manifest["cohort_id"], "member_id": member["member_id"],
                           "trade_id": member["trade_id"], "attempt": 1},
            require_unclaimed=True,
        )
    database.close_connection()
    status = database.get_coin_prep_fee_approval_status(approved_bootstrap["approval"]["approval_id"])
    assert status["held_fee_mojos"] == status["spent_fee_mojos"] == 0
    assert status["unresolved_operation_count"] == 0


def test_retry_after_no_effect_is_counted_once_by_new_attempt(approved_bootstrap):
    database = import_module("database")
    manifest, identity = _seed_cancel(approved_bootstrap)
    database.reconcile_rejected_offer_cancel_cohort(
        manifest_json=manifest, transaction_id="8" * 64,
        relay_evidence_json={
            "status": "rejected", "transaction_id": "8" * 64,
            "reason_code": "INVALID_FEE_TOO_CLOSE_TO_ZERO",
            "evidence_sha256": "7" * 64, "source": "sage_native_log",
            "source_file": "app.log.2026-09-22",
        },
        wallet_fingerprint_hash=import_module("mutation_gate").wallet_fingerprint_hash(736588221),
        network="mainnet",
    )
    retry = database.canonical_offer_cancel_cohort_manifest([
        {**{key: member[key] for key in ("operation_id", "trade_id", "intent_id")},
         "attempt": 2, "prepared_event_id": f"{member['operation_id']}:attempt:2:prepared"}
        for member in manifest["members"]
    ])
    requests = []
    for member in retry["members"]:
        old = database.get_offer_operation_events(member["operation_id"])[0]
        evidence = json.loads(old["evidence_json"])
        evidence.pop("prior_lifecycle_state", None)
        evidence.update(attempt=2, cohort_id=retry["cohort_id"], member_id=member["member_id"])
        requests.append({
            "operation_id": member["operation_id"], "event_id": member["prepared_event_id"],
            "trade_id": member["trade_id"], "intent_id": member["intent_id"], "attempt": 2,
            "wallet_identity_json": identity, "evidence_json": evidence,
        })
    database.prepare_offer_cancel_cohort(manifest_json=retry, member_requests_json=requests)
    database.claim_offer_cancel_cohort_effects(manifest_json=retry)
    for _ in range(2):
        database.close_connection()
        status = database.get_coin_prep_fee_approval_status(approved_bootstrap["approval"]["approval_id"])
        assert status["held_fee_mojos"] == status["committed_fee_mojos"] == 40
        assert status["unresolved_operation_count"] == 1


def test_partial_terminal_cohort_cannot_release_or_double_count_legacy_fee(approved_bootstrap):
    database = import_module("database")
    manifest, identity = _seed_cancel(approved_bootstrap)
    _confirm_cohort({**manifest, "members": manifest["members"][:1]}, identity)
    with pytest.raises(ValueError, match="FEE_CANCELLATION_EFFECT_UNRESOLVED"):
        database.get_coin_prep_fee_approval_status(approved_bootstrap["approval"]["approval_id"])


@pytest.mark.parametrize("surface", ["http", "native"])
@pytest.mark.parametrize("invalid", [False, True])
def test_restart_surfaces_real_legacy_fee_hold_and_blocks_overlap(
    approved_bootstrap, monkeypatch, tmp_path, surface, invalid
):
    database = import_module("database")
    server = import_module("api_server")
    blueprint = import_module("blueprints.coin_prep")
    _seed_cancel(approved_bootstrap, fees=(40, 41) if invalid else (40, 40))
    approval_id = approved_bootstrap["approval"]["approval_id"]
    status_path = tmp_path / "coin_prep_status.json"
    status_path.write_text(json.dumps({
        "phase": "splitting", "run_id": "legacy-restart", "fee_approval_id": approval_id,
    }), encoding="utf-8")
    monkeypatch.setattr(blueprint, "_coin_prep_status_file", lambda: str(status_path))
    monkeypatch.setattr(blueprint, "_coin_prep_last_file", lambda: str(tmp_path / "absent.json"))
    monkeypatch.setattr(server, "bot", None)
    monkeypatch.setattr(server, "_coin_prep_state", {
        **server._coin_prep_state, "running": False, "complete": False,
        "error": None, "run_id": None,
    })
    monkeypatch.setattr(server, "_ensure_mutation_runtime", lambda: None)
    monkeypatch.setattr(server, "_is_rate_limited", lambda _path: False)
    monkeypatch.setattr(import_module("wallet"), "get_spendable_coin_count", lambda _wallet_id: 0)
    before = utils._counts()
    database.close_connection()
    if surface == "http":
        response = server.app.test_client().get(
            "/api/coin-prep/status", headers={"X-Bot-Local-Token": server._LOCAL_API_TOKEN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert response.status_code == 200
        status = response.get_json()
    else:
        status = import_module("app_bridge").AppBridge().get_coin_prep_status()
    assert status["overlapping_coin_prep_blocked"] is True
    assert status["fee_approval"]["dispatch_authorized"] is False
    if invalid:
        assert status["fee_approval"]["state"] == "unavailable"
        assert status["fee_approval"]["reason"] == "FEE_APPROVAL_STATUS_UNAVAILABLE"
    else:
        assert status["fee_resume_required"] is True
        assert status["fee_approval"]["held_fee_mojos"] == "40"
        assert status["fee_approval"]["committed_fee_mojos"] == "40"
        assert status["fee_approval"]["unresolved_operation_count"] == 1
        assert status["fee_approval"]["state"] == "submitted_awaiting_confirmation"
    assert utils._counts() == before
