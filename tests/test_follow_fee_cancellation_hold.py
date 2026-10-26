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


def _prepared_follow_cancel(run_id, identity, *, purpose=None, fee=20):
    intent_id = "1" * 64
    operation_id = f"create:{intent_id}"
    database.upsert_coin(
        SOURCE, "xch", 1000, designation="tier_spare", purpose="lifecycle"
    )
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=operation_id,
        event_id=f"{operation_id}:prepared",
        run_id="runtime-test",
        wallet_fingerprint_hash="f" * 64,
        network=identity["network"],
        asset_id=identity["asset_id"],
        side="buy",
        tier="inner",
        purpose=purpose or f"follow:{run_id}:normal_lifecycle",
        selected_coin_ids_json=[SOURCE],
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
        sage_trade_id=TRADE,
        offer_text_sha256="2" * 64,
        wallet_identity_json={"binding_digest": "b" * 64},
        evidence_json={"effect_attempted": True},
        finalize_selected_coin_reservations=True,
    )
    member = {
        "trade_id": TRADE,
        "operation_id": f"cancel:{TRADE}",
        "intent_id": intent_id,
        "attempt": 1,
        "prepared_event_id": f"cancel:{TRADE}:attempt:1:prepared",
    }
    manifest = database.canonical_offer_cancel_cohort_manifest([member])
    contract = {
        "protocol": "sage_native_cancel_offers_zero_plus_fee_v1",
        "trade_ids": [TRADE],
        "source_coin_ids": [SOURCE],
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
                    "cohort_size": 1,
                    "member_id": manifest["members"][0]["member_id"],
                    "reason": "cancel_all",
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
                    AND run.approval_id=reservation.approval_id
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
        prior = current.replace(new_fragment, prior_fragment)
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


def test_follow_cancel_hold_survives_run_stop_but_rechecks_exact_claim(approved):
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


def test_follow_cancel_no_effect_releases_hold_only_after_journal_proof(approved):
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
