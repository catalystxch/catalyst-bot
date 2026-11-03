"""Exercise a real approved fee hold through fenced cancellation finalization."""

import json
import socket
import time
from importlib import import_module, util
from pathlib import Path

import pytest

import api_server  # noqa: F401 - establish blueprint import order before fixture loading


class _Finalized(BaseException):
    """End the shared incident fixture before its separate terminal-proof phase."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("fee-finalization test forbids network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def approved_bootstrap(tmp_path, monkeypatch):
    fixtures = import_module("test_coin_prep_fee_bootstrap_integration")
    yield from fixtures.approved_bootstrap.__wrapped__(tmp_path, monkeypatch)


def test_real_approved_hold_claim_and_fenced_finalization(
    approved_bootstrap, monkeypatch
):
    spec = util.spec_from_file_location(
        "fee_finalization_incident_fixture",
        Path(__file__).with_name("test_offer_reconciliation.py"),
    )
    incident = util.module_from_spec(spec)
    spec.loader.exec_module(incident)
    database = import_module("database")
    manager_module = import_module("offer_manager")
    pricing = import_module("coin_prep_fee_cancellation")
    state = approved_bootstrap
    monkeypatch.setattr(
        database.time, "perf_counter_ns", time.perf_counter_ns, raising=False
    )
    original_finalization = database.finalize_offer_cancel_cohort
    original_hold_binding = database._refresh_abort_prepared_fee_hold
    original_cancel = manager_module.OfferManager.cancel_refresh_abort_targets
    monkeypatch.setattr(incident, "database", database)
    monkeypatch.setattr(incident, "ASSET", state["config"].CAT_ASSET_ID)
    monkeypatch.setattr(
        database, "create_bootstrap_campaign", lambda _spec: state["campaign_id"]
    )
    monkeypatch.setattr(
        manager_module.OfferManager,
        "cancel_refresh_abort_targets",
        lambda self, **request: original_cancel(
            self, **{**request, "fee_approval_id": state["approval"]["approval_id"]}
        ),
    )
    seen = {}

    def reserve(**request):
        assert request["approval_id"] == state["approval"]["approval_id"]
        priced = request["priced_cancellation"]
        hold = database.reserve_coin_prep_cancellation_fee(
            approval_id=request["approval_id"],
            scope_sha256=state["approval"]["scope_sha256"],
            plan_sha256=state["approval"]["plan_sha256"],
            manifest_json=request["manifest"],
            batch_contract={
                "protocol": "sage_native_cancel_offers_zero_plus_fee_v1",
                "trade_ids": priced["trade_ids"],
                "source_coin_ids": priced["source_coin_ids"],
                "fee_coin_id": priced["fee_coin_id"],
                "fee_mojos": 20,
            },
            final_quote={
                "available": True,
                "fee_mojos": 20,
                "source": "coinset",
                "cost": 123456,
                "target_seconds": 300,
                "observed_at": state["now"],
                "expires_at": state["now"] + 60,
            },
        )
        seen["hold"] = hold
        return {"validated_unsigned": {"sealed": True}}

    def finalized(**request):
        try:
            result = original_finalization(**request)
        except ValueError as exc:
            if request.get("refresh_abort_id") not in {None, "0" * 64}:
                member = request["manifest_json"]["members"][0]
                seen["claim_before_finalization"] = (
                    database.get_offer_cancel_effect_claim(
                        operation_id=member["operation_id"], attempt=1
                    )
                    is not None
                )
                seen["finalization_error"] = str(exc)
            raise
        if request.get("refresh_abort_id") is not None:
            manifest = request["manifest_json"]
            member = manifest["members"][0]
            assert (
                database.get_offer_cancel_effect_claim(
                    operation_id=member["operation_id"], attempt=1
                )
                is not None
            )
            events = database.get_offer_operation_events(member["operation_id"])
            assert [event["phase"] for event in events] == ["PREPARED", "FINALIZED"]
            assert events[-1]["outcome"] == "CANCEL_SUBMITTED_UNCONFIRMED"
            assert (
                database.get_coin_prep_cancellation_fee_hold(manifest)["operation_id"]
                == seen["hold"]["operation_id"]
            )
            assert database.get_runtime_safety_latch()["state"] == "tripped"
            seen["finalized"] = True
            raise _Finalized()
        return result

    class ScopedMonkeypatch:
        def setattr(self, target, name, value, **kwargs):
            if target is pricing and name == "reserve_approved_cancellation":
                value = reserve
            elif target is pricing and name == "price_approved_cancellation":
                value = lambda **request: {
                    "available": True,
                    "trade_ids": request["trade_ids"],
                    "source_coin_ids": request["source_coin_ids"],
                    "fee_coin_id": request["fee_coin_id"],
                    "fee_mojos": 20,
                }
            elif target is database and name == "_refresh_abort_prepared_fee_hold":
                value = original_hold_binding
            elif (
                target is manager_module.OfferManager
                and name == "_acquire_cancel_authority"
            ):
                value = staticmethod(
                    lambda _intent, **_scope: (
                        object(),
                        {
                            "snapshot_sha256": "e" * 64,
                            "snapshot": {
                                "binding": {
                                    "backend": "sage",
                                    "fingerprint": 736588221,
                                    "network_id": "mainnet",
                                }
                            },
                        },
                        incident.WALLET,
                        incident.NETWORK,
                    )
                )
            monkeypatch.setattr(target, name, value, **kwargs)

    monkeypatch.setattr(database, "finalize_offer_cancel_cohort", finalized)
    try:
        incident.test_fenced_abort_records_confirmed_parent_without_publishing_child(
            None, ScopedMonkeypatch(), "integrated"
        )
    except _Finalized:
        pass
    except AssertionError:
        if seen.get("finalization_error"):
            raise AssertionError(json.dumps(seen)) from None
        raise
    assert seen.get("finalized") is True, json.dumps(seen)
