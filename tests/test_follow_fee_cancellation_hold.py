"""Durable Follow fee holds bind exact reviewed offer cancellation cohorts."""

import hashlib
import json
from importlib import import_module

import database
import pytest
from test_coin_prep_fee_frozen_execution import approved  # noqa: F401
from test_follow_fee_cancellation import _run


TRADE = "a" * 64
SOURCE = "c" * 64
FEE_COIN = "e" * 64


@pytest.fixture(autouse=True)
def current_database_module():
    global database
    database = import_module("database")


def _prepared_follow_cancel(
    run_id,
    identity,
    *,
    purpose=None,
    fee=20,
    count=1,
    offset=0,
    reason="cancel_all",
    mixed_sides=False,
):
    members = []
    sources = []
    trades = []
    for index in range(offset, offset + count):
        side = "sell" if mixed_sides and index % 2 else "buy"
        asset_type = "cat" if side == "sell" else "xch"
        trade = chr(ord("a") + index) * 64 if index < 2 else f"{index + 1:064x}"
        source = chr(ord("c") + index) * 64 if index < 2 else f"{index + 1000:064x}"
        intent_id = str(index + 1) * 64 if index < 2 else f"{index + 2000:064x}"
        operation_id = f"create:{intent_id}"
        database.upsert_coin(
            source, asset_type, 1000, designation="tier_spare", purpose="lifecycle"
        )
        database.prepare_offer_intent(
            intent_id=intent_id,
            operation_id=operation_id,
            event_id=f"{operation_id}:prepared",
            run_id="runtime-test",
            wallet_fingerprint_hash="f" * 64,
            network=identity["network"],
            asset_id=identity["asset_id"],
            side=side,
            tier="inner",
            purpose=purpose or f"follow:{run_id}:normal_lifecycle",
            selected_coin_ids_json=[source],
            offered_amount_atomic="1000",
            requested_amount_atomic="2000",
            wallet_identity_json={"binding_digest": "b" * 64},
            evidence_json={"canonical_intent_sha256": intent_id},
            reserve_selected_coins=True,
        )
        database.finalize_offer_intent(
            intent_id=intent_id,
            operation_id=operation_id,
            event_id=f"{operation_id}:finalized:confirmed",
            lifecycle_state="created",
            outcome="CONFIRMED",
            sage_trade_id=trade,
            offer_text_sha256=(
                str(index + 2) * 64 if index < 2 else f"{index + 3000:064x}"
            ),
            wallet_identity_json={"binding_digest": "b" * 64},
            evidence_json={"effect_attempted": True},
            finalize_selected_coin_reservations=True,
        )
        members.append(
            {
                "trade_id": trade,
                "operation_id": f"cancel:{trade}",
                "intent_id": intent_id,
                "attempt": 1,
                "prepared_event_id": f"cancel:{trade}:attempt:1:prepared",
            }
        )
        trades.append(trade)
        sources.append(source)
    manifest = database.canonical_offer_cancel_cohort_manifest(members)
    source_by_trade = dict(zip(trades, sources))
    contract = {
        "protocol": "sage_native_cancel_offers_zero_plus_fee_v1",
        "trade_ids": [member["trade_id"] for member in manifest["members"]],
        "source_coin_ids": [
            source_by_trade[member["trade_id"]] for member in manifest["members"]
        ],
        "fee_coin_id": FEE_COIN,
        "fee_mojos": fee,
    }
    database.prepare_offer_cancel_cohort(
        manifest_json=manifest,
        member_requests_json=[
            {
                "operation_id": member["operation_id"],
                "event_id": member["prepared_event_id"],
                "trade_id": member["trade_id"],
                "intent_id": member["intent_id"],
                "attempt": member["attempt"],
                "wallet_identity_json": {
                    "snapshot": {
                        "binding": {
                            "backend": "sage",
                            "fingerprint": identity["wallet_fingerprint"],
                            "network_id": identity["network"],
                        }
                    }
                },
                "evidence_json": {
                    "operation_id": member["operation_id"],
                    "trade_id": member["trade_id"],
                    "intent_id": member["intent_id"],
                    "attempt": member["attempt"],
                    "cohort_id": manifest["cohort_id"],
                    "cohort_size": count,
                    "member_id": member["member_id"],
                    "reason": reason,
                    "continuation_journal_sha256": "f" * 64,
                    "wallet_effect": {
                        "secure": True,
                        "timeout": 60,
                        "fee_mojos": fee,
                        "batch": {
                            k: v for k, v in contract.items() if k != "fee_mojos"
                        },
                    },
                    "effect_claim_protocol": "durable_cohort_claim_v1",
                },
            }
            for member in manifest["members"]
        ],
    )
    return manifest, contract


def _quote(state, fee=20):
    return {
        "available": True,
        "fee_mojos": fee,
        "source": "coinset",
        "cost": 123456,
        "target_seconds": 300,
        "observed_at": state["now"],
        "expires_at": state["now"] + 60,
    }


def _finalize_follow_submitted(manifest, transaction_id="6" * 64):
    from cancel_outcomes import CANCEL_SUBMITTED_UNCONFIRMED, cancellation_result

    submitted = cancellation_result(
        CANCEL_SUBMITTED_UNCONFIRMED,
        method="sage_native_cancel_offers",
        raw_response={"success": True, "transaction_id": transaction_id},
        transaction_id=transaction_id,
    )
    database.claim_offer_cancel_cohort_effects(manifest_json=manifest)
    requests = []
    for member in manifest["members"]:
        prepared = database.get_offer_operation_events(member["operation_id"])[0]
        requests.append(
            {
                "operation_id": member["operation_id"],
                "event_id": f"{member['operation_id']}:attempt:1:finalized",
                "trade_id": member["trade_id"],
                "intent_id": member["intent_id"],
                "attempt": 1,
                "cancel_result": submitted,
                "wallet_identity_json": json.loads(prepared["wallet_identity_json"]),
                "evidence_json": {
                    "trade_id": member["trade_id"],
                    "attempt": 1,
                    "cohort_id": manifest["cohort_id"],
                    "member_id": member["member_id"],
                    "effect_attempted": True,
                    "cancel_result": submitted,
                },
            }
        )
    database.finalize_offer_cancel_cohort(
        manifest_json=manifest, member_requests_json=requests
    )
    return transaction_id


def test_existing_fee_outcome_guard_upgrades_without_losing_proof_gate(approved):
    conn = database._stability_connection()
    try:
        current = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='approved_fee_outcomes_journal_guard'"
        ).fetchone()[0]
        new_fragment = """JOIN offer_cancel_cohort_manifests AS manifest
      ON reservation.cancellation=1
    WHERE reservation.operation_id=NEW.operation_id
      AND catalyst_sha256(NEW.evidence_json)=NEW.evidence_id
      AND json_extract(NEW.evidence_json, '$.schema_version')=1
      AND (
          (
              json_extract(NEW.evidence_json, '$.kind')=
                  'coin_prep_cancellation_fee_outcome'
              AND reservation.operation_id=catalyst_sha256(
                  'coin-prep-cancel:' || manifest.cohort_id
              )
          )
          OR (
              json_extract(NEW.evidence_json, '$.kind')=
                  'follow_cancellation_fee_outcome'
              AND EXISTS (
                  SELECT 1 FROM follow_run_authorities AS run
                  WHERE run.run_id=json_extract(
                      NEW.evidence_json, '$.follow_run_id'
                  )
                    AND (
                        run.approval_id=reservation.approval_id
                        OR EXISTS (
                            SELECT 1 FROM follow_fee_ceiling_revisions AS revision
                            WHERE revision.run_id=run.run_id
                              AND revision.approval_id=reservation.approval_id
                        )
                    )
                    AND reservation.operation_id=catalyst_sha256(
                        'follow-cancel:' || run.run_id || ':' || manifest.cohort_id
                    )
              )
          )
      )"""
        prior_fragment = """JOIN offer_cancel_cohort_manifests AS manifest
      ON reservation.operation_id=catalyst_sha256(
          'coin-prep-cancel:' || manifest.cohort_id
      )
    WHERE reservation.operation_id=NEW.operation_id
      AND reservation.cancellation=1
      AND catalyst_sha256(NEW.evidence_json)=NEW.evidence_id
      AND json_extract(NEW.evidence_json, '$.schema_version')=1
      AND json_extract(NEW.evidence_json, '$.kind')=
          'coin_prep_cancellation_fee_outcome'"""
        assert current.count(new_fragment) == 1
        old_follow_fragment = new_fragment.replace(
            """AND (
                        run.approval_id=reservation.approval_id
                        OR EXISTS (
                            SELECT 1 FROM follow_fee_ceiling_revisions AS revision
                            WHERE revision.run_id=run.run_id
                              AND revision.approval_id=reservation.approval_id
                        )
                    )""",
            "AND run.approval_id=reservation.approval_id",
        )
        assert old_follow_fragment != new_fragment
        for prior in (
            current.replace(new_fragment, old_follow_fragment),
            current.replace(new_fragment, prior_fragment),
        ):
            conn.execute("DROP TRIGGER approved_fee_outcomes_journal_guard")
            conn.execute(prior)
            database._upgrade_fee_outcome_journal_guard(conn)
            upgraded = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' "
                "AND name='approved_fee_outcomes_journal_guard'"
            ).fetchone()[0]
            assert database._normalized_schema_sql(
                upgraded
            ) == database._normalized_schema_sql(current)
    finally:
        conn.close()


def test_follow_cancel_holds_exact_run_fee_and_refuses_replay(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(run_id, identity)

    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved),
    )

    assert (
        hold["operation_id"]
        == hashlib.sha256(
            f"follow-cancel:{run_id}:{manifest['cohort_id']}".encode()
        ).hexdigest()
    )
    assert hold["fee_mojos"] == 20
    assert hold["cancellation"] == 1
    assert hold["dispatch_authorized"] is False
    with pytest.raises(ValueError, match="FEE_OPERATION_REPLAY"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=_quote(approved),
        )


def test_full_24_by_24_book_uses_one_bounded_cancel_hold(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(
        run_id, identity, count=48, fee=20, mixed_sides=True
    )
    assert len(manifest["members"]) == 48
    assert {
        side: sum(
            database.get_offer_intent(member["intent_id"])["side"] == side
            for member in manifest["members"]
        )
        for side in ("buy", "sell")
    } == {"buy": 24, "sell": 24}
    assert {
        asset: sum(
            database.get_coin_state(coin_id)["wallet_type"] == asset
            for coin_id in contract["source_coin_ids"]
        )
        for asset in ("xch", "cat")
    } == {"xch": 24, "cat": 24}
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved),
    )
    assert hold["fee_mojos"] == 20
    assert hold["dispatch_authorized"] is False
    assert (
        database.get_effective_follow_fee_policy(
            run_id=run_id,
            identity=identity,
            now_epoch=1002,
            _own_unresolved_operation_id=hold["operation_id"],
        )["remaining_fee_mojos"]
        == 60
    )


def test_full_24_by_24_book_cannot_consume_protected_shutdown_reserve(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(
        run_id, identity, count=48, fee=50, mixed_sides=True
    )
    with pytest.raises(ValueError, match="FOLLOW_SHUTDOWN_RESERVE_PROTECTED"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=_quote(approved, fee=50),
        )
    status = database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )
    assert status["held_fee_mojos"] == 0


def test_durable_stop_releases_reserve_only_for_exact_run_cleanup(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(run_id, identity, fee=50)
    quote = _quote(approved, fee=50)
    with pytest.raises(ValueError, match="FOLLOW_SHUTDOWN_RESERVE_PROTECTED"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=quote,
        )
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1002)
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=quote,
    )
    assert hold["fee_mojos"] == 50
    database.claim_offer_cancel_cohort_effects(manifest_json=manifest)
    assert (
        database.recheck_follow_cancellation_fee_hold(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=quote,
        )
        is True
    )
    assert database.get_unsettled_follow_cancellation_manifests() == [
        {"run_id": run_id, "manifest": manifest}
    ]


def test_stopped_run_routine_requote_cannot_spend_shutdown_reserve(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(
        run_id, identity, fee=50, reason="requote"
    )
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1002)
    with pytest.raises(ValueError, match="FOLLOW_SHUTDOWN_RESERVE_PROTECTED"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=_quote(approved, fee=50),
        )


def test_reserve_floor_shutdown_requires_durable_stop_before_spending_reserve(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(
        run_id, identity, fee=50, reason="reserve_floor_breached"
    )
    with pytest.raises(ValueError, match="FOLLOW_SHUTDOWN_RESERVE_PROTECTED"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=_quote(approved, fee=50),
        )
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1002)
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved, fee=50),
    )
    assert hold["fee_mojos"] == 50


def test_native_reviewed_stopped_run_increase_funds_exact_cleanup(approved):
    run_id, identity = _run(approved)
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1002)
    review = database.create_follow_fee_ceiling_review(
        run_id=run_id,
        identity=identity,
        configuration_sha256="a" * 64,
        proposed_maximum_fee_mojos=120,
        observed_fee_principal_mojos=120,
        now_epoch=1002,
    )
    database.confirm_follow_fee_ceiling_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        identity=identity,
        configuration_sha256="a" * 64,
        observed_fee_principal_mojos=120,
        now_epoch=1003,
    )
    approved["now"] = 1004
    manifest, contract = _prepared_follow_cancel(run_id, identity, fee=100)
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved, fee=100),
    )
    assert hold["fee_mojos"] == 100
    assert (
        database.get_follow_creation_authority(
            identity=identity, configuration_sha256="a" * 64, now_epoch=1004
        )["ready"]
        is False
    )


def test_expired_follow_run_can_use_reserve_for_journaled_cancel_all(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1001 + 48 * 3600 + 1
    manifest, contract = _prepared_follow_cancel(run_id, identity, fee=50)
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved, fee=50),
    )
    assert hold["fee_mojos"] == 50
    database.claim_offer_cancel_cohort_effects(manifest_json=manifest)
    assert (
        database.recheck_follow_cancellation_fee_hold(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=_quote(approved, fee=50),
        )
        is True
    )


def test_expired_follow_run_routine_requote_keeps_shutdown_reserve(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1001 + 48 * 3600 + 1
    manifest, contract = _prepared_follow_cancel(
        run_id, identity, fee=50, reason="requote"
    )
    with pytest.raises(ValueError, match="FOLLOW_SHUTDOWN_RESERVE_PROTECTED"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=_quote(approved, fee=50),
        )


def test_revised_follow_ceiling_funds_exact_routine_cancel_hold(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1004
    review = database.create_follow_fee_ceiling_review(
        run_id=run_id,
        identity=identity,
        configuration_sha256="a" * 64,
        proposed_maximum_fee_mojos=120,
        observed_fee_principal_mojos=120,
        now_epoch=1002,
    )
    revision = database.confirm_follow_fee_ceiling_review(
        review_id=review["review_id"],
        review_sha256=review["review_sha256"],
        identity=identity,
        configuration_sha256="a" * 64,
        observed_fee_principal_mojos=120,
        now_epoch=1003,
    )
    manifest, contract = _prepared_follow_cancel(
        run_id, identity, fee=60, reason="requote"
    )
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved, fee=60),
    )
    assert hold["fee_mojos"] == 60
    assert hold["approval_id"] == revision["approval_id"]
    database.claim_offer_cancel_cohort_effects(manifest_json=manifest)
    assert (
        database.recheck_follow_cancellation_fee_hold(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=_quote(approved, fee=60),
        )
        is True
    )
    assert database.get_unsettled_follow_cancellation_manifests() == [
        {"run_id": run_id, "manifest": manifest}
    ]


def test_new_fee_approval_keeps_old_run_cleanup_under_original_cap(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1002)
    original = approved["approval"]
    database.create_fee_approval(
        scope_sha256=original["scope_sha256"],
        plan_sha256=original["plan_sha256"],
        total_fee_mojos=120,
        cancellation_reserve_mojos=40,
    )
    with pytest.raises(ValueError, match="FEE_APPROVAL_STALE"):
        database.reserve_approved_fee(
            approval_id=original["approval_id"],
            scope_sha256=original["scope_sha256"],
            plan_sha256=original["plan_sha256"],
            operation_id="9" * 64,
            fee_mojos=1,
            cancellation=True,
        )
    cleanup = database.get_follow_cleanup_authority(
        run_id=run_id, identity=identity, now_epoch=1002
    )
    assert cleanup["ready"] is True
    assert cleanup["maximum_fee_mojos"] == 80
    manifest, contract = _prepared_follow_cancel(run_id, identity, fee=50)
    quote = _quote(approved, fee=50)
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=quote,
    )
    assert hold["fee_mojos"] == 50
    database.claim_offer_cancel_cohort_effects(manifest_json=manifest)
    assert (
        database.recheck_follow_cancellation_fee_hold(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=quote,
        )
        is True
    )


def test_follow_cancel_refuses_competing_hold_and_counts_prior_spend(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    first, first_contract = _prepared_follow_cancel(run_id, identity)
    second, second_contract = _prepared_follow_cancel(
        run_id, identity, fee=50, offset=1
    )
    database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=first,
        batch_contract=first_contract,
        final_quote=_quote(approved),
    )
    with pytest.raises(ValueError, match="FOLLOW_UNRESOLVED_EFFECT"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=second,
            batch_contract=second_contract,
            final_quote=_quote(approved, fee=50),
        )
    transaction_id = _finalize_follow_submitted(first)
    member = first["members"][0]
    prepared = database.get_offer_operation_events(member["operation_id"])[0]
    database.append_offer_operation_event(
        event_id=f"{member['operation_id']}:attempt:1:reconciled",
        operation_id=member["operation_id"],
        intent_id=member["intent_id"],
        operation_type="CANCEL",
        attempt=1,
        phase="RECONCILED",
        outcome="CANCEL_CONFIRMED",
        request_timestamp="2026-10-26T08:00:00Z",
        wallet_identity_json=json.loads(prepared["wallet_identity_json"]),
        transaction_id=transaction_id,
        evidence_json={
            "trade_id": member["trade_id"],
            "cohort_id": first["cohort_id"],
            "member_id": member["member_id"],
            "effect_attempted": True,
            "authoritative_terminal_proof": True,
        },
        reason_code="AUTHORITATIVE_TERMINAL_PROOF",
        blocks_mutation=False,
        created_at="2026-10-26T08:00:00Z",
    )
    assert (
        database.record_follow_cancellation_fee_outcome(
            run_id=run_id, manifest_json=first
        )["state"]
        == "CONFIRMED_SPENT"
    )
    with pytest.raises(ValueError, match="FOLLOW_SHUTDOWN_RESERVE_PROTECTED"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=second,
            batch_contract=second_contract,
            final_quote=_quote(approved, fee=50),
        )


def test_follow_cancel_cannot_charge_unrelated_offer(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(
        run_id, identity, purpose="normal_lifecycle"
    )
    with pytest.raises(ValueError, match="FEE_FOLLOW_AUTHORITY_REQUIRED"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=_quote(approved),
        )


def test_follow_cancel_hold_refuses_expired_quote_and_run_cap(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(run_id, identity, fee=81)
    quote = _quote(approved, fee=81)
    with pytest.raises(ValueError, match="FEE_BUDGET_EXCEEDED"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=quote,
        )
    approved["now"] = quote["expires_at"]
    with pytest.raises(ValueError, match="FEE_QUOTE_STALE"):
        database.reserve_follow_cancellation_fee(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=quote,
        )


def test_follow_cancel_hold_survives_run_stop_but_rechecks_exact_claim(
    approved, monkeypatch
):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(run_id, identity)
    quote = _quote(approved)
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1002)
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=quote,
    )
    assert hold["fee_mojos"] == 20
    assert (
        database.claim_offer_cancel_cohort_effects(manifest_json=manifest)[
            "effect_claimed"
        ]
        is True
    )
    assert (
        database.recheck_follow_cancellation_fee_hold(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=quote,
        )
        is True
    )
    original_totals = database._fee_scope_totals
    monkeypatch.setattr(
        database,
        "_fee_scope_totals",
        lambda *args: {
            **original_totals(*args),
            "committed_fee_mojos": 81,
        },
    )
    assert (
        database.recheck_follow_cancellation_fee_hold(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=quote,
        )
        is False
    )
    approved["now"] = quote["expires_at"]
    assert (
        database.recheck_follow_cancellation_fee_hold(
            run_id=run_id,
            identity=identity,
            manifest_json=manifest,
            batch_contract=contract,
            final_quote=quote,
        )
        is False
    )


@pytest.mark.parametrize("revised", [False, True])
def test_follow_cancel_no_effect_releases_hold_only_after_journal_proof(
    approved, revised
):
    run_id, identity = _run(approved)
    approved["now"] = 1004 if revised else 1002
    if revised:
        review = database.create_follow_fee_ceiling_review(
            run_id=run_id,
            identity=identity,
            configuration_sha256="a" * 64,
            proposed_maximum_fee_mojos=120,
            observed_fee_principal_mojos=120,
            now_epoch=1002,
        )
        database.confirm_follow_fee_ceiling_review(
            review_id=review["review_id"],
            review_sha256=review["review_sha256"],
            identity=identity,
            configuration_sha256="a" * 64,
            observed_fee_principal_mojos=120,
            now_epoch=1003,
        )
    manifest, contract = _prepared_follow_cancel(run_id, identity)
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved),
    )
    assert database.get_unsettled_follow_cancellation_manifests() == [
        {"run_id": run_id, "manifest": manifest}
    ]
    with pytest.raises(ValueError, match="FEE_EFFECT_UNRESOLVED"):
        database.record_follow_cancellation_fee_outcome(
            run_id=run_id, manifest_json=manifest
        )
    member = manifest["members"][0]
    from cancel_outcomes import CANCEL_FAILED, cancellation_result

    failed = cancellation_result(
        CANCEL_FAILED,
        method="follow_fee_test",
        raw_response={"reason_code": "CONTINUATION_REFRESH_BLOCKED"},
        error="CANCEL_REJECTED",
    )
    prepared = database.get_offer_operation_events(member["operation_id"])[0]
    database.finalize_offer_cancel(
        operation_id=member["operation_id"],
        event_id=f"{member['operation_id']}:attempt:1:finalized",
        trade_id=member["trade_id"],
        intent_id=member["intent_id"],
        attempt=1,
        cancel_result=failed,
        wallet_identity_json=json.loads(prepared["wallet_identity_json"]),
        evidence_json={
            "trade_id": member["trade_id"],
            "attempt": 1,
            "cohort_id": manifest["cohort_id"],
            "member_id": member["member_id"],
            "effect_attempted": False,
            "cancel_result": failed,
        },
        require_unclaimed=True,
    )
    settled = database.record_follow_cancellation_fee_outcome(
        run_id=run_id, manifest_json=manifest
    )
    assert settled["operation_id"] == hold["operation_id"]
    assert settled["state"] == "RELEASED_NO_EFFECT"
    assert database.get_unsettled_follow_cancellation_manifests() == []
    assert (
        database.record_follow_cancellation_fee_outcome(
            run_id=run_id, manifest_json=manifest
        )["idempotent"]
        is True
    )


@pytest.mark.parametrize("revised", [False, True])
def test_follow_confirmed_spend_charges_run_scope_after_restart(approved, revised):
    run_id, identity = _run(approved)
    approved["now"] = 1004 if revised else 1002
    if revised:
        review = database.create_follow_fee_ceiling_review(
            run_id=run_id,
            identity=identity,
            configuration_sha256="a" * 64,
            proposed_maximum_fee_mojos=120,
            observed_fee_principal_mojos=120,
            now_epoch=1002,
        )
        database.confirm_follow_fee_ceiling_review(
            review_id=review["review_id"],
            review_sha256=review["review_sha256"],
            identity=identity,
            configuration_sha256="a" * 64,
            observed_fee_principal_mojos=120,
            now_epoch=1003,
        )
    manifest, contract = _prepared_follow_cancel(run_id, identity)
    hold = database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved),
    )
    member = manifest["members"][0]
    transaction_id = _finalize_follow_submitted(manifest)
    prepared = database.get_offer_operation_events(member["operation_id"])[0]
    with pytest.raises(ValueError, match="FEE_EFFECT_UNRESOLVED"):
        database.record_follow_cancellation_fee_outcome(
            run_id=run_id, manifest_json=manifest
        )
    assert database.get_unsettled_follow_cancellation_manifests() == [
        {"run_id": run_id, "manifest": manifest}
    ]
    database.append_offer_operation_event(
        event_id=f"{member['operation_id']}:attempt:1:reconciled",
        operation_id=member["operation_id"],
        intent_id=member["intent_id"],
        operation_type="CANCEL",
        attempt=1,
        phase="RECONCILED",
        outcome="CANCEL_CONFIRMED",
        request_timestamp="2026-10-26T08:00:00Z",
        wallet_identity_json=json.loads(prepared["wallet_identity_json"]),
        transaction_id=transaction_id,
        evidence_json={
            "trade_id": member["trade_id"],
            "cohort_id": manifest["cohort_id"],
            "member_id": member["member_id"],
            "effect_attempted": True,
            "authoritative_terminal_proof": True,
        },
        reason_code="AUTHORITATIVE_TERMINAL_PROOF",
        blocks_mutation=False,
        created_at="2026-10-26T08:00:00Z",
    )
    settled = database.record_follow_cancellation_fee_outcome(
        run_id=run_id, manifest_json=manifest
    )
    assert settled["operation_id"] == hold["operation_id"]
    assert settled["state"] == "CONFIRMED_SPENT"
    assert database.get_unsettled_follow_cancellation_manifests() == []
    status = database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )
    assert status["held_fee_mojos"] == 0
    assert status["spent_fee_mojos"] == 20
    assert (
        database.record_follow_cancellation_fee_outcome(
            run_id=run_id, manifest_json=manifest
        )["idempotent"]
        is True
    )


def test_follow_partial_confirmation_keeps_entire_batch_fee_held(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(run_id, identity, count=2)
    database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved),
    )
    transaction_id = _finalize_follow_submitted(manifest)
    member = manifest["members"][0]
    prepared = database.get_offer_operation_events(member["operation_id"])[0]
    database.append_offer_operation_event(
        event_id=f"{member['operation_id']}:attempt:1:reconciled",
        operation_id=member["operation_id"],
        intent_id=member["intent_id"],
        operation_type="CANCEL",
        attempt=1,
        phase="RECONCILED",
        outcome="CANCEL_CONFIRMED",
        request_timestamp="2026-10-26T08:00:00Z",
        wallet_identity_json=json.loads(prepared["wallet_identity_json"]),
        transaction_id=transaction_id,
        evidence_json={
            "trade_id": member["trade_id"],
            "cohort_id": manifest["cohort_id"],
            "member_id": member["member_id"],
            "effect_attempted": True,
            "authoritative_terminal_proof": True,
        },
        reason_code="AUTHORITATIVE_TERMINAL_PROOF",
        blocks_mutation=False,
        created_at="2026-10-26T08:00:00Z",
    )
    with pytest.raises(ValueError, match="FEE_EFFECT_UNRESOLVED"):
        database.record_follow_cancellation_fee_outcome(
            run_id=run_id, manifest_json=manifest
        )
    status = database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )
    assert status["held_fee_mojos"] == 20
    assert status["spent_fee_mojos"] == 0
    assert database.get_unsettled_follow_cancellation_manifests() == [
        {"run_id": run_id, "manifest": manifest}
    ]
    other = manifest["members"][1]
    other_prepared = database.get_offer_operation_events(other["operation_id"])[0]
    database.append_offer_operation_event(
        event_id=f"{other['operation_id']}:attempt:1:reconciled",
        operation_id=other["operation_id"],
        intent_id=other["intent_id"],
        operation_type="CANCEL",
        attempt=1,
        phase="RECONCILED",
        outcome="CANCEL_FAILED",
        request_timestamp="2026-10-26T08:00:01Z",
        wallet_identity_json=json.loads(other_prepared["wallet_identity_json"]),
        transaction_id=transaction_id,
        evidence_json={
            "trade_id": other["trade_id"],
            "cohort_id": manifest["cohort_id"],
            "member_id": other["member_id"],
            "effect_attempted": True,
            "relay_rejection": {"reason_code": "SAGE_RELAY_REJECTED"},
        },
        reason_code="SAGE_RELAY_REJECTED",
        blocks_mutation=False,
        created_at="2026-10-26T08:00:01Z",
    )
    with pytest.raises(ValueError, match="FEE_EFFECT_UNRESOLVED"):
        database.record_follow_cancellation_fee_outcome(
            run_id=run_id, manifest_json=manifest
        )
    assert (
        database.get_coin_prep_fee_approval_status(approved["approval"]["approval_id"])[
            "held_fee_mojos"
        ]
        == 20
    )


def test_follow_all_peer_rejection_releases_without_spend(approved):
    run_id, identity = _run(approved)
    approved["now"] = 1002
    manifest, contract = _prepared_follow_cancel(run_id, identity, count=2)
    database.reserve_follow_cancellation_fee(
        run_id=run_id,
        identity=identity,
        manifest_json=manifest,
        batch_contract=contract,
        final_quote=_quote(approved),
    )
    transaction_id = _finalize_follow_submitted(manifest)
    database.reconcile_rejected_offer_cancel_cohort(
        manifest_json=manifest,
        transaction_id=transaction_id,
        relay_evidence_json={
            "status": "rejected",
            "transaction_id": transaction_id,
            "reason_code": "INVALID_FEE_TOO_CLOSE_TO_ZERO",
            "evidence_sha256": "7" * 64,
            "source": "sage_native_log",
            "source_file": "app.log.2026-10-26",
        },
        wallet_fingerprint_hash="f" * 64,
        network="mainnet",
    )
    settled = database.record_follow_cancellation_fee_outcome(
        run_id=run_id, manifest_json=manifest
    )
    assert settled["state"] == "RELEASED_NO_EFFECT"
    status = database.get_coin_prep_fee_approval_status(
        approved["approval"]["approval_id"]
    )
    assert status["held_fee_mojos"] == status["spent_fee_mojos"] == 0
