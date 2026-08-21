"""Behavioral contract for purpose-separated authoritative coin capacity."""

from __future__ import annotations

import hashlib
import inspect
from decimal import Decimal
from pathlib import Path

import pytest

import database
import replacement_capacity


PURPOSES = (
    "lifecycle",
    "replacement",
    "fill_response",
    "operator_recovery",
    "top_up",
    "fee_reserve",
)


def _coin(label: str, purpose: str | None, **overrides):
    coin = {
        "coin_id": hashlib.sha256(label.encode("utf-8")).hexdigest(),
        "amount_mojos": 100,
        "purpose": purpose,
        "spendable": True,
        "authoritative": True,
    }
    coin.update(overrides)
    return coin


@pytest.fixture
def isolated_database(tmp_path: Path, monkeypatch):
    original_path = database.DB_PATH
    original_initialized_path = database._db_initialized_path
    database.close_connection()
    database.DB_PATH = str(tmp_path / "capacity.db")
    database._db_initialized_path = ""
    monkeypatch.setattr(
        database,
        "_stability_wall_clock",
        lambda: "2026-08-21T12:00:00.000000Z",
        raising=False,
    )
    try:
        yield
    finally:
        database.close_connection()
        database.DB_PATH = original_path
        database._db_initialized_path = original_initialized_path


@pytest.mark.parametrize("purpose", PURPOSES)
def test_each_exact_purpose_has_its_own_authoritative_capacity(purpose):
    """Catches collapsing any policy purpose into a shared spare pool."""

    assert hasattr(replacement_capacity, "decide_capacity")
    decision = replacement_capacity.decide_capacity(
        [_coin(purpose, purpose)],
        purpose=purpose,
        required_count=1,
        required_amount_mojos=Decimal("100"),
    )

    assert decision.ready is True
    assert decision.available_count == 1
    assert decision.available_amount_mojos == 100
    assert decision.selected_coin_ids == (
        hashlib.sha256(purpose.encode("utf-8")).hexdigest(),
    )


def test_one_purpose_never_borrows_another_purposes_unused_floor():
    """Catches replacement silently spending lifecycle or fill-response coins."""

    coins = [
        _coin("life", "lifecycle"),
        _coin("fill", "fill_response"),
        _coin("replacement", "replacement", spendable=False),
    ]

    decision = replacement_capacity.decide_capacity(
        coins, purpose="replacement", required_count=1
    )

    assert decision.ready is False
    assert decision.available_count == 0
    assert decision.reason == "purpose_capacity_exhausted"


@pytest.mark.parametrize(
    "overrides",
    [
        {"purpose": None},
        {"purpose": "unknown"},
        {"spendable": 1},
        {"authoritative": 1},
        {"coin_id": "not-a-coin-id"},
        {"amount_mojos": True},
    ],
)
def test_ambiguous_or_unproven_coins_count_toward_no_purpose(overrides):
    """Catches truthy or malformed wallet observations manufacturing capacity."""

    coin = _coin("ambiguous", "replacement")
    coin.update(overrides)

    for purpose in PURPOSES:
        assert replacement_capacity.decide_capacity(
            [coin], purpose=purpose, required_count=1
        ).available_count == 0


def test_duplicate_authoritative_coin_identity_fails_the_whole_view_closed():
    """Catches duplicate pages counting one replacement coin twice."""

    coin = _coin("duplicate", "replacement")
    decision = replacement_capacity.decide_capacity(
        [coin, dict(coin)], purpose="replacement", required_count=1
    )

    assert decision.ready is False
    assert decision.available_count == 0
    assert decision.reason == "ambiguous_coin_view"


def test_policy_rejects_aliases_truthy_subclasses_and_float_thresholds():
    """Catches normalization or floating-point policy inputs changing floors."""

    class PurposeAlias(str):
        pass

    with pytest.raises(TypeError, match="exact purpose"):
        replacement_capacity.decide_capacity(
            [], purpose=PurposeAlias("replacement"), required_count=0
        )
    with pytest.raises(ValueError, match="purpose"):
        replacement_capacity.decide_capacity(
            [], purpose="fill-response", required_count=0
        )
    with pytest.raises(TypeError, match="Decimal"):
        replacement_capacity.decide_capacity(
            [], purpose="replacement", required_amount_mojos=1.5
        )


def test_database_persists_exact_purpose_through_designation_and_reservation(
    isolated_database,
):
    """Catches designation or Task 4 reservation silently dropping purpose."""

    assert "purpose" in inspect.signature(database.upsert_coin).parameters
    assert "purpose" in inspect.signature(database.set_coin_designation).parameters
    assert "coin_purpose" in inspect.signature(database.prepare_offer_intent).parameters
    database.init_database()
    coin_id = hashlib.sha256(b"purpose-reservation").hexdigest()
    assert database.upsert_coin(
        coin_id,
        "xch",
        100,
        designation="tier_spare",
        assigned_tier="inner",
        purpose="replacement",
    )
    assert database.set_coin_designation(
        coin_id, "tier_spare", "inner", purpose="replacement"
    )
    durable = database.get_coin_state(coin_id)
    assert "purpose" in durable
    assert durable["purpose"] == "replacement"

    database.prepare_offer_intent(
        intent_id="purpose-reservation",
        operation_id="create:purpose-reservation",
        event_id="create:purpose-reservation:prepared",
        run_id="run-a",
        wallet_fingerprint_hash=hashlib.sha256(b"wallet").hexdigest(),
        network="mainnet",
        asset_id=hashlib.sha256(b"asset").hexdigest(),
        side="buy",
        tier="inner",
        purpose="ladder",
        coin_purpose="replacement",
        offered_amount_atomic="100",
        requested_amount_atomic="200",
        selected_coin_ids_json=[coin_id],
        reserve_selected_coins=True,
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"source": "task-12-test"},
    )
    reservations = database.get_offer_intent_coin_reservations(
        "purpose-reservation"
    )
    assert reservations[0]["purpose"] == "replacement"


def test_repository_capacity_is_exact_and_excludes_intent_reservations(
    isolated_database,
):
    """Catches repository capacity bypassing Task 4 reservation authority."""

    assert hasattr(database, "get_authoritative_coin_capacity")
    assert hasattr(database, "get_authoritative_replacement_capacity_count")
    database.init_database()
    replacement_id = hashlib.sha256(b"replacement-free").hexdigest()
    lifecycle_id = hashlib.sha256(b"lifecycle-free").hexdigest()
    ambiguous_id = hashlib.sha256(b"ambiguous-free").hexdigest()
    for coin_id, purpose in (
        (replacement_id, "replacement"),
        (lifecycle_id, "lifecycle"),
        (ambiguous_id, None),
    ):
        assert database.upsert_coin(
            coin_id,
            "xch",
            100,
            designation="tier_spare",
            assigned_tier="inner",
            purpose=purpose,
        )

    before = database.get_authoritative_coin_capacity(
        "replacement", wallet_type="xch"
    )
    assert before["count"] == 1
    assert before["coin_ids"] == [database.norm_coin_id(replacement_id)]

    database.prepare_offer_intent(
        intent_id="capacity-reservation",
        operation_id="create:capacity-reservation",
        event_id="create:capacity-reservation:prepared",
        run_id="run-a",
        wallet_fingerprint_hash=hashlib.sha256(b"wallet").hexdigest(),
        network="mainnet",
        asset_id=hashlib.sha256(b"asset").hexdigest(),
        side="buy",
        tier="inner",
        purpose="ladder",
        coin_purpose="replacement",
        offered_amount_atomic="100",
        requested_amount_atomic="200",
        selected_coin_ids_json=[replacement_id],
        reserve_selected_coins=True,
        wallet_identity_json={"network": "mainnet"},
        evidence_json={"source": "task-12-test"},
    )
    assert database.get_authoritative_replacement_capacity_count(
        wallet_type="xch"
    ) == 0


def test_coin_manager_exposes_authoritative_replacement_count_without_lineage_logic(
    isolated_database,
):
    """Catches Task 11 consumers falling back to legacy free-coin heuristics."""

    import coin_manager

    assert hasattr(
        coin_manager, "get_authoritative_replacement_capacity_count_standalone"
    )
    database.init_database()
    coin_id = hashlib.sha256(b"manager-replacement").hexdigest()
    assert database.upsert_coin(
        coin_id,
        "xch",
        100,
        designation="tier_spare",
        assigned_tier="inner",
        purpose="replacement",
    )
    assert (
        coin_manager.get_authoritative_replacement_capacity_count_standalone(
            "xch"
        )
        == 1
    )


def _target_contract():
    return {
        "wallet_type": "xch",
        "outputs": [
            {
                "output_index": 0,
                "amount_mojos": 60,
                "purpose": "replacement",
            },
            {
                "output_index": 1,
                "amount_mojos": 40,
                "purpose": "fee_reserve",
            },
        ],
    }


def test_split_and_combine_identities_are_deterministic_and_purpose_bound():
    """Catches restart creating a new identity for the same prep effect."""

    source_a = hashlib.sha256(b"source-a").hexdigest()
    source_b = hashlib.sha256(b"source-b").hexdigest()
    first = replacement_capacity.coin_prep_operation_identity(
        operation_kind="split",
        purpose="replacement",
        source_coin_ids=[source_b, source_a],
        target_contract=_target_contract(),
    )
    replay = replacement_capacity.coin_prep_operation_identity(
        operation_kind="split",
        purpose="replacement",
        source_coin_ids=[source_a, source_b],
        target_contract=_target_contract(),
    )
    other_purpose = replacement_capacity.coin_prep_operation_identity(
        operation_kind="split",
        purpose="lifecycle",
        source_coin_ids=[source_a, source_b],
        target_contract=_target_contract(),
    )
    combine = replacement_capacity.coin_prep_operation_identity(
        operation_kind="combine",
        purpose="replacement",
        source_coin_ids=[source_a, source_b],
        target_contract=_target_contract(),
    )

    assert first == replay
    assert len({first, other_purpose, combine}) == 3


def test_database_prepare_is_idempotent_and_restart_lists_effect_unknown(
    isolated_database,
):
    """Catches blind split replay after a lost wallet response."""

    assert hasattr(database, "prepare_coin_prep_operation")
    assert hasattr(database, "record_coin_prep_operation_outcome")
    assert hasattr(database, "get_recoverable_coin_prep_operations")
    database.init_database()
    source = hashlib.sha256(b"journal-source").hexdigest()
    identity = {
        "backend": "sage",
        "name": "test-wallet",
        "fingerprint": 123,
        "network_id": "mainnet",
        "kind": "hot",
        "has_secrets": True,
        "bound_at_utc": "2026-08-21T12:00:00.000000Z",
        "maximum_age_seconds": 300,
    }
    first = database.prepare_coin_prep_operation(
        operation_kind="split",
        purpose="replacement",
        source_coin_ids=[source],
        target_contract=_target_contract(),
        wallet_identity_json=identity,
        evidence_json={"run_id": "prep-a"},
    )
    replay = database.prepare_coin_prep_operation(
        operation_kind="split",
        purpose="replacement",
        source_coin_ids=[source],
        target_contract=_target_contract(),
        wallet_identity_json=identity,
        evidence_json={"run_id": "prep-a"},
    )
    assert first["idempotent"] is False
    assert replay["idempotent"] is True
    assert replay["operation"] == first["operation"]

    unknown = database.record_coin_prep_operation_outcome(
        first["operation"]["operation_id"],
        outcome="SUBMITTED_UNKNOWN",
        evidence_json={"reason_code": "wallet_response_lost"},
    )
    assert unknown["operation"]["outcome"] == "SUBMITTED_UNKNOWN"
    recoverable = database.get_recoverable_coin_prep_operations()
    assert [row["operation_id"] for row in recoverable] == [
        first["operation"]["operation_id"]
    ]
    assert database.get_runtime_safety_latch()["state"] == "tripped"


def test_authoritative_post_view_requires_exact_fresh_identity_and_outputs():
    """Catches count-only success despite stale identity or output drift."""

    source = hashlib.sha256(b"post-source").hexdigest()
    output_a = hashlib.sha256(b"post-output-a").hexdigest()
    output_b = hashlib.sha256(b"post-output-b").hexdigest()
    expected_identity = {
        "fingerprint": 123,
        "network": "mainnet",
        "wallet_type": "sage",
        "wallet_id": 1,
        "binding_digest": hashlib.sha256(b"binding").hexdigest(),
        "expires_at": "2026-08-21T12:10:00.000000Z",
    }
    expected_outputs = [
        {"coin_id": output_a, "amount_mojos": 60, "purpose": "replacement"},
        {"coin_id": output_b, "amount_mojos": 40, "purpose": "fee_reserve"},
    ]
    view = {
        "fresh": True,
        "complete": True,
        "wallet_identity": dict(expected_identity),
        "coins": [dict(item) for item in expected_outputs],
    }
    confirmed = replacement_capacity.verify_coin_prep_post_view(
        source_coin_ids=[source],
        expected_outputs=expected_outputs,
        authoritative_view=view,
        expected_wallet_identity=expected_identity,
    )
    assert confirmed.confirmed is True

    for drifted, reason in (
        ({**view, "fresh": 1}, "authoritative_view_not_fresh"),
        ({**view, "complete": False}, "authoritative_view_incomplete"),
        (
            {**view, "wallet_identity": {**expected_identity, "wallet_id": 2}},
            "wallet_identity_mismatch",
        ),
        (
            {**view, "coins": [dict(expected_outputs[0])]},
            "expected_output_missing",
        ),
        (
            {**view, "coins": [dict(expected_outputs[0])] * 2 + [dict(expected_outputs[1])]},
            "duplicate_coin_identity",
        ),
        (
            {**view, "coins": [dict(expected_outputs[0]), {**expected_outputs[1], "amount_mojos": 41}]},
            "expected_output_contradiction",
        ),
        (
            {**view, "coins": [dict(expected_outputs[0]), dict(expected_outputs[1]), _coin("post-source", "replacement")]},
            "source_coin_still_present",
        ),
    ):
        decision = replacement_capacity.verify_coin_prep_post_view(
            source_coin_ids=[source],
            expected_outputs=expected_outputs,
            authoritative_view=drifted,
            expected_wallet_identity=expected_identity,
        )
        assert decision.confirmed is False
        assert decision.reason == reason
