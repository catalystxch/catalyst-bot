"""The diagnostics RBF preview cannot acquire a wallet effect capability."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import database
import mutation_gate
import wallet


SOURCE = "1" * 64
TX = "2" * 64
OPERATION = "coin-prep:" + "3" * 64
CLAIM = "4" * 64
CHANGE = 1_435_390_971_590
FEE_OUTPUT = 20_000_000_000
XCH_ASSET = {"asset_id": None, "ticker": "XCH", "kind": "token"}


def _time(offset: int) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(seconds=offset))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _authority():
    identity = mutation_gate.wallet_identity_binding_payload(
        mutation_gate.WalletIdentityBinding(
            backend="sage",
            name="wallet",
            fingerprint=736588221,
            network_id="mainnet",
            kind="bls",
            has_secrets=True,
            bound_at_utc=_time(-10),
            maximum_age_seconds=30,
        )
    )
    return {
        "operation": {
            "operation_id": OPERATION,
            "operation_kind": "split",
            "purpose": "fee_reserve",
            "outcome": "SUBMITTED_UNKNOWN",
            "wallet_identity_json": json.dumps(identity),
            "source_coin_ids_json": json.dumps([SOURCE]),
            "effect_fee_coin_ids_json": "[]",
            "effect_claim_token": CLAIM,
            "effect_adapter_operation": OPERATION,
            "target_contract_json": json.dumps(
                {
                    "wallet_type": "xch",
                    "outputs": [
                        {
                            "output_index": index,
                            "amount_mojos": FEE_OUTPUT,
                            "purpose": "fee_reserve",
                        }
                        for index in range(4)
                    ]
                    + [
                        {"output_index": 4, "amount_mojos": CHANGE, "purpose": "top_up"}
                    ],
                }
            ),
        },
        "latch": {
            "state": "tripped",
            "reason_code": "COIN_PREP_RECOVERY_REQUIRED",
            "blocking_operation_ids_json": json.dumps(
                sorted([OPERATION, f"wallet-effect:{CLAIM}"])
            ),
            "wallet_fingerprint_hash": mutation_gate.wallet_fingerprint_hash(
                identity["fingerprint"]
            ),
            "network": "mainnet",
        },
    }


def _pending():
    return {
        "transaction_id": TX,
        "fee": "0",
        "spent": [
            {
                "coin_id": SOURCE,
                "address": "xch1source",
                "asset": XCH_ASSET,
                "amount": str(CHANGE + 4 * FEE_OUTPUT),
            },
            *[
                {
                    "coin_id": f"{index:064x}",
                    "address": "xch1source",
                    "asset": XCH_ASSET,
                    "amount": str(index),
                }
                for index in range(3)
            ],
        ],
        "created": [
            *[
                {
                    "coin_id": f"{index:064x}",
                    "address": "xch1source",
                    "asset": XCH_ASSET,
                    "amount": str(index),
                }
                for index in range(3)
            ],
            *[
                {
                    "coin_id": f"{index + 10:064x}",
                    "address": "xch1fees",
                    "asset": XCH_ASSET,
                    "amount": str(FEE_OUTPUT),
                }
                for index in range(4)
            ],
            {
                "coin_id": "f" * 64,
                "address": "xch1change",
                "asset": XCH_ASSET,
                "amount": str(CHANGE),
            },
        ],
    }


def test_preview_uses_only_exact_auto_submit_false_builder(monkeypatch):
    authority = _authority()
    calls = []

    class Adapter:
        def get_sage_version(self):
            return "0.13.1"

        def get_wallet_identity(self):
            identity = json.loads(authority["operation"]["wallet_identity_json"])
            return {
                "success": True,
                **{
                    key: identity[key]
                    for key in (
                        "backend",
                        "name",
                        "fingerprint",
                        "network_id",
                        "kind",
                        "has_secrets",
                    )
                },
                "observed_at_utc": _time(0),
            }

        def build_coin_prep_rbf_preview_rpc(
            self, source, outputs, fee, *, _identity_recheck
        ):
            calls.append((source, outputs, fee))
            _identity_recheck("create_transaction")
            return {
                "summary": {
                    "inputs": [
                        {"coin_id": coin_id}
                        for coin_id in [
                            SOURCE,
                            *[f"{index:064x}" for index in range(3)],
                        ]
                    ]
                },
                "coin_spends": [{}],
            }

        def inspect_unsigned_transaction_effect(self, result, contract):
            assert contract["fee_mojos"] == 10_000_000
            assert contract["outputs"][-1]["amount_mojos"] == CHANGE - 10_000_000
            assert contract["outputs"][-1]["purpose"] == "top_up"
            assert contract["outputs"][-1]["ordinal"] == 4
            return {
                **result,
                "_catalyst_executable_effect_bound": True,
                "_catalyst_exact_unsigned_cost": 1_000_000,
                "constructed_outputs": [
                    {**output, "coin_id": f"{index + 10:064x}"}
                    for index, output in enumerate(contract["outputs"])
                ],
            }

        def submit_built_transaction_rpc(self, *_args, **_kwargs):
            raise AssertionError("preview must never submit")

        def create_transaction_rpc(self, *_args, **_kwargs):
            raise AssertionError("preview must not use generic create")

    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", Adapter())
    monkeypatch.setattr(
        database, "get_coin_prep_rbf_preview_authority", lambda _: authority
    )
    monkeypatch.setattr(wallet, "get_pending_transactions_strict", lambda: [_pending()])
    monkeypatch.setattr(
        mutation_gate,
        "enter_wallet_mutation",
        lambda *_: (_ for _ in ()).throw(AssertionError("no mutation permit")),
    )
    result = wallet.preview_coin_prep_rbf_unsigned(OPERATION, TX, 10_000_000)
    assert result["success"] is True
    assert result["provenance"] == "unique_exact_pending_effect_association"
    assert len(calls) == 1
    assert calls[0][0] == SOURCE
    assert len(calls[0][1]) == 5
    assert calls[0][1][4]["address"] == "xch1change"
    assert calls[0][2] == 10_000_000


def test_preview_refuses_wrong_latch_identity_tx_and_version_before_build(monkeypatch):
    authority = _authority()
    builds = []
    adapter = SimpleNamespace(
        build_coin_prep_rbf_preview_rpc=lambda *args, **kwargs: builds.append(args),
        get_sage_version=lambda: "0.13.1",
    )
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(
        database, "get_coin_prep_rbf_preview_authority", lambda _: authority
    )
    monkeypatch.setattr(wallet, "get_pending_transactions_strict", lambda: [_pending()])

    for field, bad in [
        ("reason_code", "OTHER"),
        ("blocking_operation_ids_json", "[]"),
        ("wallet_fingerprint_hash", "0" * 64),
        ("network", "testnet"),
    ]:
        original = authority["latch"][field]
        authority["latch"][field] = bad
        assert (
            wallet.preview_coin_prep_rbf_unsigned(OPERATION, TX, 10_000_000)["success"]
            is False
        )
        authority["latch"][field] = original

    assert (
        wallet.preview_coin_prep_rbf_unsigned(OPERATION, "5" * 64, 10_000_000)[
            "success"
        ]
        is False
    )
    adapter.get_sage_version = lambda: "0.13.2"
    assert (
        wallet.preview_coin_prep_rbf_unsigned(OPERATION, TX, 10_000_000)["success"]
        is False
    )
    assert builds == []


def test_authority_reader_uses_only_read_only_snapshot(monkeypatch):
    statements = []

    class Connection:
        def execute(self, statement, *args):
            statements.append(statement.strip())
            assert statement.strip().upper().startswith(("BEGIN", "SELECT"))
            if "FROM coin_prep_operations" in statement:
                return SimpleNamespace(fetchone=lambda: {"operation_id": OPERATION})
            return SimpleNamespace(fetchone=lambda: {"state": "tripped"})

        def rollback(self):
            statements.append("ROLLBACK")

        def close(self):
            statements.append("CLOSE")

    monkeypatch.setattr(database, "_stability_read_only_connection", Connection)
    assert database.get_coin_prep_rbf_preview_authority(OPERATION) == {
        "operation": {"operation_id": OPERATION},
        "latch": {"state": "tripped"},
    }
    assert statements[0] == "BEGIN"
    assert statements[-2:] == ["ROLLBACK", "CLOSE"]


def test_sage_rbf_builder_never_auto_submits(monkeypatch):
    import wallet_sage

    requests = []
    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)

    def rpc(endpoint, payload, **_kwargs):
        requests.append((endpoint, payload))
        return {"summary": {}, "coin_spends": []}

    monkeypatch.setattr(wallet_sage, "rpc", rpc)
    outputs = [
        {"asset": "xch", "address": "xch1fees", "amount_mojos": FEE_OUTPUT}
        for _ in range(4)
    ] + [{"asset": "xch", "address": "xch1change", "amount_mojos": CHANGE - 10_000_000}]
    wallet_sage.build_coin_prep_rbf_preview_rpc(SOURCE, outputs, 10_000_000)
    assert requests == [
        (
            "create_transaction",
            {
                "selected_coin_ids": [SOURCE],
                "actions": [
                    {
                        "type": "send",
                        "id": {"type": "xch"},
                        "address": output["address"],
                        "amount": str(output["amount_mojos"]),
                        "memos": [],
                    }
                    for output in outputs
                ]
                + [{"type": "fee", "amount": "10000000"}],
                "auto_submit": False,
            },
        )
    ]


def test_diagnostics_normal_builder_blocked_but_bound_preview_reaches_sage(monkeypatch):
    import wallet_sage

    authority = _authority()
    requests = []
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", wallet_sage)
    monkeypatch.setattr(mutation_gate, "current_runtime", lambda: None)
    monkeypatch.setattr(mutation_gate, "worker_identity_lease_binding", lambda: None)
    monkeypatch.setattr(
        database, "get_coin_prep_rbf_preview_authority", lambda _: authority
    )
    monkeypatch.setattr(wallet, "get_pending_transactions_strict", lambda: [_pending()])
    monkeypatch.setattr(wallet_sage, "get_sage_version", lambda: "0.13.1")
    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)
    monkeypatch.setattr(
        wallet_sage,
        "get_wallet_identity",
        lambda: {
            "success": True,
            **{
                key: json.loads(authority["operation"]["wallet_identity_json"])[key]
                for key in (
                    "backend",
                    "name",
                    "fingerprint",
                    "network_id",
                    "kind",
                    "has_secrets",
                )
            },
            "observed_at_utc": _time(0),
        },
    )
    monkeypatch.setattr(
        wallet_sage,
        "rpc",
        lambda endpoint, payload, **kwargs: (
            requests.append((endpoint, payload))
            or {
                "summary": {
                    "inputs": [
                        {"coin_id": coin_id}
                        for coin_id in [
                            SOURCE,
                            *[f"{index:064x}" for index in range(3)],
                        ]
                    ]
                },
                "coin_spends": [{}],
            }
        ),
    )
    monkeypatch.setattr(
        wallet_sage,
        "inspect_unsigned_transaction_effect",
        lambda result, _contract: {
            **result,
            "_catalyst_executable_effect_bound": True,
            "_catalyst_exact_unsigned_cost": 1_000_000,
            "constructed_outputs": [
                {**output, "coin_id": f"{index + 10:064x}"}
                for index, output in enumerate(_contract["outputs"])
            ],
        },
    )

    assert wallet.build_transaction_rpc([SOURCE], [])["reason"] == (
        "MUTATION_RUNTIME_NOT_INITIALIZED"
    )
    result = wallet.preview_coin_prep_rbf_unsigned(OPERATION, TX, 10_000_000)
    assert result["success"] is True
    assert len(requests) == 1
    assert requests[0][0] == "create_transaction"
    assert requests[0][1]["auto_submit"] is False


def test_preview_refuses_second_pending_spend_of_source(monkeypatch):
    authority = _authority()
    calls = []
    adapter = SimpleNamespace(
        build_coin_prep_rbf_preview_rpc=lambda *args, **kwargs: calls.append(args),
        get_sage_version=lambda: "0.13.1",
        get_wallet_identity=lambda: {
            "success": True,
            **{
                key: json.loads(authority["operation"]["wallet_identity_json"])[key]
                for key in (
                    "backend",
                    "name",
                    "fingerprint",
                    "network_id",
                    "kind",
                    "has_secrets",
                )
            },
            "observed_at_utc": _time(0),
        },
    )
    other = _pending()
    other["transaction_id"] = "5" * 64
    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", adapter)
    monkeypatch.setattr(
        database, "get_coin_prep_rbf_preview_authority", lambda _: authority
    )
    monkeypatch.setattr(
        wallet, "get_pending_transactions_strict", lambda: [_pending(), other]
    )
    result = wallet.preview_coin_prep_rbf_unsigned(OPERATION, TX, 10_000_000)
    assert result == {"success": False, "reason": "ORIGINAL_PENDING_SOURCE_NOT_UNIQUE"}
    assert calls == []


def test_preview_refuses_original_disappearing_during_unsigned_build(monkeypatch):
    authority = _authority()
    calls = []
    pending_views = iter([[_pending()], []])

    class Adapter:
        def get_sage_version(self):
            return "0.13.1"

        def get_wallet_identity(self):
            identity = json.loads(authority["operation"]["wallet_identity_json"])
            return {
                "success": True,
                **{
                    key: identity[key]
                    for key in (
                        "backend",
                        "name",
                        "fingerprint",
                        "network_id",
                        "kind",
                        "has_secrets",
                    )
                },
                "observed_at_utc": _time(0),
            }

        def build_coin_prep_rbf_preview_rpc(
            self, _source, _outputs, _fee, *, _identity_recheck
        ):
            calls.append("unsigned_build")
            return {
                "summary": {
                    "inputs": [
                        {"coin_id": coin_id}
                        for coin_id in [
                            SOURCE,
                            *[f"{index:064x}" for index in range(3)],
                        ]
                    ]
                },
                "coin_spends": [{}],
            }

        def inspect_unsigned_transaction_effect(self, result, _contract):
            return {
                **result,
                "_catalyst_executable_effect_bound": True,
                "_catalyst_exact_unsigned_cost": 1_000_000,
            }

    monkeypatch.setattr(wallet, "WALLET_TYPE", "sage")
    monkeypatch.setattr(wallet, "_wallet_adapter", Adapter())
    monkeypatch.setattr(
        database, "get_coin_prep_rbf_preview_authority", lambda _: authority
    )
    monkeypatch.setattr(
        wallet, "get_pending_transactions_strict", lambda: next(pending_views)
    )
    result = wallet.preview_coin_prep_rbf_unsigned(OPERATION, TX, 10_000_000)
    assert calls == ["unsigned_build"]
    assert result == {
        "success": False,
        "reason": "ORIGINAL_PENDING_CHANGED_DURING_PREVIEW",
    }
