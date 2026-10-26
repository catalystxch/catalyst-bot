"""An in-run fee change needs an exact native review and final acceptance."""

from types import SimpleNamespace

import pytest

from test_coin_prep_fee_frozen_execution import approved  # noqa: F401
from test_follow_fee_cancellation import _run


def _method(name):
    from app_bridge import AppBridge

    method = getattr(AppBridge, name)
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def test_native_fee_change_prepares_only_current_asset_run(monkeypatch):
    import coin_prep_fee_runtime
    import database
    import follow_principal

    seen = []
    monkeypatch.setattr(
        coin_prep_fee_runtime, "_configuration", lambda: {"CAT_ASSET_ID": "a" * 64}
    )
    monkeypatch.setattr(
        database,
        "get_unexpired_follow_run_marker",
        lambda **kw: seen.append(kw) or {"run_id": "b" * 64, "stopped": False},
    )
    monkeypatch.setattr(
        database,
        "get_follow_run_identity",
        lambda _run: {"network": "mainnet", "wallet_fingerprint": 123},
    )
    monkeypatch.setattr(
        follow_principal,
        "prepare_follow_fee_ceiling_review",
        lambda run, *, proposed_maximum_fee_mojos: {
            "review_id": "c" * 64,
            "run_id": run,
            "proposed_maximum_fee_mojos": proposed_maximum_fee_mojos,
            "dispatch_authorized": False,
        },
    )
    result = _method("prepare_follow_fee_ceiling_review")(
        SimpleNamespace(), {"proposed_maximum_fee_mojos": 5_000_000_000}
    )
    assert result["success"] is True
    assert result["run_id"] == "b" * 64
    assert result["proposed_maximum_fee_mojos"] == 5_000_000_000
    assert result["identity"]["wallet_fingerprint"] == 123
    assert seen[0]["asset_id"] == "a" * 64


@pytest.mark.parametrize(
    "body",
    [
        {"proposed_maximum_fee_mojos": True},
        {"proposed_maximum_fee_mojos": 0},
        {"proposed_maximum_fee_mojos": 120, "run_id": "b" * 64},
    ],
)
def test_native_fee_change_rejects_unreviewed_terms(body):
    result = _method("prepare_follow_fee_ceiling_review")(SimpleNamespace(), body)
    assert result["success"] is False
    assert result["reason"] == "FOLLOW_FEE_REVISION_INVALID"


def test_native_fee_change_confirmation_requires_exact_acceptance(monkeypatch):
    import follow_principal

    seen = []
    monkeypatch.setattr(
        follow_principal,
        "confirm_follow_fee_ceiling_review",
        lambda review, digest: (
            seen.append((review, digest))
            or {"run_id": "b" * 64, "revision": 1, "dispatch_authorized": False}
        ),
    )
    method = _method("confirm_follow_fee_ceiling_review")
    invalid = method(
        SimpleNamespace(),
        {"review_id": "c" * 64, "review_sha256": "d" * 64, "accepted": False},
    )
    assert invalid["success"] is False
    assert seen == []
    confirmed = method(
        SimpleNamespace(),
        {"review_id": "c" * 64, "review_sha256": "d" * 64, "accepted": True},
    )
    assert confirmed["success"] is True
    assert confirmed["revision"] == 1
    assert seen == [("c" * 64, "d" * 64)]


def test_native_fee_change_consumes_review_in_original_run_ledger(
    approved, monkeypatch
):
    from importlib import import_module

    import coin_prep_fee_runtime
    import follow_principal

    database = import_module("database")
    run_id, identity = _run(approved)
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "_configuration",
        lambda: {"CAT_ASSET_ID": identity["asset_id"]},
    )
    monkeypatch.setattr(follow_principal.time, "time", lambda: 1002)
    monkeypatch.setattr(
        follow_principal,
        "_current_follow_fee_funding",
        lambda _run_id: {
            "identity": identity,
            "configuration_sha256": "a" * 64,
            "observed_fee_principal_mojos": 120,
            "dispatch_authorized": False,
        },
    )
    review = _method("prepare_follow_fee_ceiling_review")(
        SimpleNamespace(), {"proposed_maximum_fee_mojos": 120}
    )
    assert review["success"] is True
    assert review["run_id"] == run_id
    assert review["prior_maximum_fee_mojos"] == 80
    assert review["reviewed_spent_fee_mojos"] == 0
    assert review["reviewed_held_fee_mojos"] == 0
    assert review["identity"] == identity
    confirmed = _method("confirm_follow_fee_ceiling_review")(
        SimpleNamespace(),
        {
            "review_id": review["review_id"],
            "review_sha256": review["review_sha256"],
            "accepted": True,
        },
    )
    assert confirmed["success"] is True
    assert confirmed["run_id"] == run_id
    assert confirmed["maximum_fee_mojos"] == 120
    assert (
        database.get_effective_follow_fee_policy(
            run_id=run_id, identity=identity, now_epoch=1003
        )["revision"]
        == 1
    )


def test_native_stopped_run_can_review_funded_cleanup_increase(approved, monkeypatch):
    from importlib import import_module

    import coin_prep_fee_runtime
    import follow_principal

    database = import_module("database")
    run_id, identity = _run(approved)
    database.stop_follow_run_authority(run_id=run_id, stopped_at_epoch=1002)
    monkeypatch.setattr(
        coin_prep_fee_runtime,
        "_configuration",
        lambda: {"CAT_ASSET_ID": identity["asset_id"]},
    )
    monkeypatch.setattr(follow_principal.time, "time", lambda: 1003)
    monkeypatch.setattr(
        follow_principal,
        "_current_follow_fee_funding",
        lambda _run_id: {
            "identity": identity,
            "configuration_sha256": "a" * 64,
            "observed_fee_principal_mojos": 120,
            "dispatch_authorized": False,
        },
    )
    review = _method("prepare_follow_fee_ceiling_review")(
        SimpleNamespace(), {"proposed_maximum_fee_mojos": 120}
    )
    assert review["success"] is True
    assert review["run_stopped"] is True
    confirmed = _method("confirm_follow_fee_ceiling_review")(
        SimpleNamespace(),
        {
            "review_id": review["review_id"],
            "review_sha256": review["review_sha256"],
            "accepted": True,
        },
    )
    assert confirmed["success"] is True
    assert confirmed["maximum_fee_mojos"] == 120
    assert (
        database.get_follow_creation_authority(
            identity=identity, configuration_sha256="a" * 64, now_epoch=1003
        )["ready"]
        is False
    )
