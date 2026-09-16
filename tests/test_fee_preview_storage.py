"""Durable preview consent is atomic, explicit and reload-safe."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sqlite3

import pytest

import database


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    database.close_connection()
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "preview.db"))
    database.init_database()
    yield database
    database.close_connection()


def _store(ledger, **overrides):
    assert callable(getattr(ledger, "store_coin_prep_fee_preview", None)), (
        "durable server-owned fee preview is missing"
    )
    scope_json = '{"wallet":"test-scope"}'
    plan_json = '{"outputs":[1000]}'
    args = {
        "scope_json": scope_json,
        "plan_json": plan_json,
        "scope_sha256": hashlib.sha256(scope_json.encode()).hexdigest(),
        "plan_sha256": hashlib.sha256(plan_json.encode()).hexdigest(),
        "request_options_json": '{"coin_multiplier":"1"}',
        "quote_json": json.dumps({
            "available": True, "estimated_preparation_fee_mojos": 30,
            "estimated_cancellation_fee_mojos": 10, "fee_funding_mojos": 100,
        }),
        "observed_at": 100,
        "expires_at": 160,
    }
    args.update(overrides)
    return ledger.store_coin_prep_fee_preview(**args)


def _approve(ledger, preview, **overrides):
    args = {
        "preview_id": preview["preview_id"],
        "scope_sha256": preview["scope_sha256"],
        "plan_sha256": preview["plan_sha256"],
        "maximum_fee_mojos": 80,
        "cancellation_reserve_mojos": 20,
        "now": 101,
    }
    args.update(overrides)
    return ledger.approve_coin_prep_fee_preview(**args)


def test_preview_persistence_never_creates_an_approval_or_hold(ledger):
    preview = _store(ledger)
    conn = ledger.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM approved_fee_reservations").fetchone()[0] == 0
    ledger.close_connection()
    ledger.init_database()
    recovered = ledger.get_coin_prep_fee_preview(preview["preview_id"])
    assert recovered["request_options_json"] == '{"coin_multiplier":"1"}'
    assert recovered["expires_at"] == 160


def test_confirmation_creates_one_bound_durable_consent(ledger):
    preview = _store(ledger)
    approval = _approve(ledger, preview)
    assert approval["total_fee_mojos"] == 80
    assert approval["cancellation_reserve_mojos"] == 20
    assert approval["version"] == 1
    assert approval["idempotent"] is False
    ledger.close_connection()
    ledger.init_database()
    context = ledger.get_coin_prep_fee_approval_context(approval["approval_id"])
    assert context["preview_id"] == preview["preview_id"]
    assert context["plan_json"] == '{"outputs":[1000]}'


def test_confirmation_checks_fresh_funding_inside_the_approval_transaction(ledger):
    preview = _store(ledger)
    with pytest.raises(ValueError, match="FEE_FUNDING_INSUFFICIENT"):
        _approve(ledger, preview, current_fee_funding_mojos=79)
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 0
    result = _approve(ledger, preview, current_fee_funding_mojos=80)
    assert result["remaining_fee_mojos"] == 80


def test_unfunded_principal_blocks_new_consent_even_when_all_fees_are_zero(ledger):
    preview = _store(ledger, quote_json='{"available":true,"estimated_preparation_fee_mojos":0,'
                    '"estimated_cancellation_fee_mojos":0,"fee_funding_mojos":0}')
    with pytest.raises(ValueError, match="FEE_FUNDING_INSUFFICIENT"):
        _approve(ledger, preview, maximum_fee_mojos=0, cancellation_reserve_mojos=0,
                 current_fee_funding_mojos=0, current_principal_funded=False)
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 0


def test_existing_consent_readback_does_not_require_selectable_principal_again(ledger):
    preview = _store(ledger)
    first = _approve(ledger, preview)
    second = _approve(ledger, preview, current_fee_funding_mojos=0, current_principal_funded=False)
    assert second["approval_id"] == first["approval_id"]
    assert second["idempotent"] is True


@pytest.mark.parametrize("funding", [True, 1.5, -1, "100"])
def test_confirmation_cannot_coerce_fresh_funding(ledger, funding):
    preview = _store(ledger)
    with pytest.raises(ValueError):
        _approve(ledger, preview, current_fee_funding_mojos=funding)
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 0


def test_concurrent_duplicate_confirmations_create_one_approval_version(ledger):
    preview = _store(ledger)
    with ThreadPoolExecutor(max_workers=2) as pool:
        approvals = list(pool.map(lambda _: _approve(ledger, preview), [1, 2]))
    assert approvals[0]["approval_id"] == approvals[1]["approval_id"]
    assert sorted(item["idempotent"] for item in approvals) == [False, True]
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 1


def test_confirmed_preview_cannot_be_reused_for_different_budget(ledger):
    preview = _store(ledger)
    _approve(ledger, preview)
    with pytest.raises(ValueError, match="FEE_CONSENT_CONFLICT"):
        _approve(ledger, preview, maximum_fee_mojos=90)


@pytest.mark.parametrize("now", [99, 160, 200])
def test_unapproved_stale_or_future_preview_cannot_authorize_spend(ledger, now):
    preview = _store(ledger)
    with pytest.raises(ValueError, match="FEE_PREVIEW_STALE"):
        _approve(ledger, preview, now=now)
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 0


@pytest.mark.parametrize("overrides,reason", [
    ({"maximum_fee_mojos": 29, "cancellation_reserve_mojos": 0}, "FEE_BUDGET_INSUFFICIENT"),
    ({"maximum_fee_mojos": 80, "cancellation_reserve_mojos": 9}, "FEE_BUDGET_INSUFFICIENT"),
    ({"maximum_fee_mojos": 101}, "FEE_FUNDING_INSUFFICIENT"),
    ({"maximum_fee_mojos": True}, "integer"),
    ({"scope_sha256": "a" * 64}, "FEE_APPROVAL_STALE"),
    ({"plan_sha256": "b" * 64}, "FEE_APPROVAL_STALE"),
])
def test_bad_confirmation_never_creates_partial_consent(ledger, overrides, reason):
    preview = _store(ledger)
    with pytest.raises(ValueError, match=reason):
        _approve(ledger, preview, **overrides)
    conn = ledger.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM coin_prep_fee_consents").fetchone()[0] == 0


def test_missing_network_estimate_cannot_be_confirmed(ledger):
    preview = _store(ledger, quote_json='{"available":false}')
    with pytest.raises(ValueError, match="FEE_ESTIMATE_UNAVAILABLE"):
        _approve(ledger, preview)


def test_canonical_digest_mismatch_cannot_enter_preview_schema(ledger):
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        _store(ledger, scope_sha256="a" * 64)


def test_history_and_runtime_reset_preserve_preview_and_consent(ledger):
    preview = _store(ledger)
    approval = _approve(ledger, preview)
    assert ledger.guarded_reset_authoritative_state(clear_terminal_offers=True)["success"]
    ledger.reset_lifecycle_observability_stats()
    assert ledger.get_coin_prep_fee_approval_context(approval["approval_id"])["preview_id"] == preview["preview_id"]


def test_preview_and_consent_are_replacement_resistant(ledger):
    preview = _store(ledger)
    _approve(ledger, preview)
    conn = ledger.get_connection()
    for statement in [
        "DELETE FROM coin_prep_fee_previews",
        "UPDATE coin_prep_fee_previews SET expires_at=999",
        "INSERT OR REPLACE INTO coin_prep_fee_previews SELECT * FROM coin_prep_fee_previews",
        "DELETE FROM coin_prep_fee_consents",
        "UPDATE coin_prep_fee_consents SET approved_at=999",
        "INSERT OR REPLACE INTO coin_prep_fee_consents SELECT * FROM coin_prep_fee_consents",
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
        conn.rollback()


def test_prior_cancellation_commitments_leave_room_for_full_projected_work(ledger):
    preview = _store(ledger)
    prior = ledger.create_fee_approval(
        scope_sha256=preview["scope_sha256"], plan_sha256=preview["plan_sha256"],
        total_fee_mojos=80, cancellation_reserve_mojos=20,
    )
    ledger.reserve_approved_fee(
        approval_id=prior["approval_id"], scope_sha256=preview["scope_sha256"],
        plan_sha256=preview["plan_sha256"], operation_id="1" * 64,
        fee_mojos=50, cancellation=True,
    )
    with pytest.raises(ValueError, match="FEE_BUDGET_INSUFFICIENT"):
        _approve(ledger, preview, maximum_fee_mojos=80)
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM fee_approvals").fetchone()[0] == 1
    assert ledger.get_connection().execute("SELECT COUNT(*) FROM coin_prep_fee_consents").fetchone()[0] == 0
    approved = _approve(ledger, preview, maximum_fee_mojos=90)
    assert approved["remaining_fee_mojos"] == 40
    assert approved["held_fee_mojos"] == 50
