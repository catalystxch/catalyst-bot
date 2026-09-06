from unittest.mock import Mock

import pytest

import wallet_sage


SOURCE = "11" * 32
FEE = "22" * 32
OUT_CAT = "33" * 32
OUT_CAT_2 = "44" * 32
OUT_FEE_CHANGE = "55" * 32
ASSET = "aa" * 32
ADDRESS = "xch1ownaddress"


def output(coin_id, amount, *, receiving=True, address=ADDRESS, burning=False):
    return {
        "coin_id": coin_id,
        "amount": str(amount),
        "address": address,
        "receiving": receiving,
        "burning": burning,
    }


def response(*, roots=None, fee=10):
    return {
        "summary": {
            "fee": str(fee),
            "inputs": roots
            or [
                {
                    "coin_id": SOURCE,
                    "amount": "100",
                    "address": ADDRESS,
                    "asset": {"asset_id": ASSET},
                    "outputs": [output(OUT_CAT, 40), output(OUT_CAT_2, 60)],
                },
                {
                    "coin_id": FEE,
                    "amount": "30",
                    "address": ADDRESS,
                    "asset": {"asset_id": None},
                    "outputs": [output(OUT_FEE_CHANGE, 20)],
                },
            ],
        },
        "coin_spends": [{"coin": {"amount": "100"}}],
    }


def contract():
    return {
        "source_asset": "cat",
        "source_coin_ids": [SOURCE],
        "fee_coin_ids": [FEE],
        "cat_asset_id": ASSET,
        "fee_mojos": 10,
        "outputs": [
            {
                "asset": "cat",
                "address": ADDRESS,
                "amount_mojos": 40,
                "purpose": "tier",
                "ordinal": 0,
            },
            {
                "asset": "cat",
                "address": ADDRESS,
                "amount_mojos": 60,
                "purpose": "change",
                "ordinal": -1,
            },
            {
                "asset": "xch",
                "address": ADDRESS,
                "amount_mojos": 20,
                "purpose": "fee_change",
                "ordinal": -1,
            },
        ],
    }


def test_unsigned_builder_never_signs_or_submits(monkeypatch):
    rpc = Mock(return_value=response())
    post = Mock()
    monkeypatch.setattr(wallet_sage, "_require_signing_capability", lambda: True)
    monkeypatch.setattr(wallet_sage, "rpc", rpc)
    monkeypatch.setattr(wallet_sage, "_sage_post", post)
    result = wallet_sage.build_transaction_rpc(
        [SOURCE, FEE], [{"type": "fee", "amount": "10"}]
    )
    assert result["coin_spends"]
    assert rpc.call_args.args[1]["auto_submit"] is False
    post.assert_not_called()


def test_validated_summary_seals_exact_distinct_effect():
    result = wallet_sage.validate_unsigned_transaction_effect(response(), contract())
    assert result["success"] is True
    assert result["constructed_output_ids"] == [OUT_CAT, OUT_CAT_2, OUT_FEE_CHANGE]
    assert result["constructed_outputs"] == [
        {
            "asset": "cat",
            "address": ADDRESS,
            "amount_mojos": 40,
            "purpose": "tier",
            "ordinal": 0,
            "coin_id": OUT_CAT,
        },
        {
            "asset": "cat",
            "address": ADDRESS,
            "amount_mojos": 60,
            "purpose": "change",
            "ordinal": -1,
            "coin_id": OUT_CAT_2,
        },
        {
            "asset": "xch",
            "address": ADDRESS,
            "amount_mojos": 20,
            "purpose": "fee_change",
            "ordinal": -1,
            "coin_id": OUT_FEE_CHANGE,
        },
    ]
    assert result["_catalyst_validated_unsigned"] is True


def test_validated_summary_accepts_official_sage_v013_asset_shape():
    """Sage 0.13 serializes TransactionInput.asset as Option<Asset>.

    CAT inputs therefore carry the complete public Asset record, while an XCH
    input may be JSON null.  This is the shape emitted by Sage itself rather
    than the minimal asset-id-only fixtures used by older CATalyst tests.
    """
    value = response()
    value["summary"]["inputs"][0]["asset"] = {
        "asset_id": ASSET,
        "name": "Monkeyzoo Token",
        "ticker": "MZ",
        "precision": 3,
        "icon_url": "https://icons.dexie.space/example.webp",
        "description": "Public display metadata",
        "is_sensitive_content": False,
        "is_visible": True,
        "revocation_address": None,
        "kind": "token",
    }
    value["summary"]["inputs"][1]["asset"] = None

    sealed = wallet_sage.validate_unsigned_transaction_effect(value, contract())

    assert sealed["success"] is True
    assert sealed["_catalyst_validated_unsigned"] is True


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda data: data["summary"]["inputs"].append(
                {
                    "coin_id": "66" * 32,
                    "amount": "1",
                    "address": ADDRESS,
                    "asset": {"asset_id": None},
                    "outputs": [],
                }
            ),
            "UNCLAIMED_REMOVAL",
        ),
        (lambda data: data["summary"]["inputs"].pop(0), "SOURCE_COHORT_MISMATCH"),
        (lambda data: data["summary"].update(fee="11"), "FEE_MISMATCH"),
        (
            lambda data: data["summary"]["inputs"][0]["asset"].update(
                asset_id="bb" * 32
            ),
            "SOURCE_ASSET_MISMATCH",
        ),
        (
            lambda data: data["summary"]["inputs"][0]["outputs"][0].update(
                address="xch1other"
            ),
            "OUTPUT_MISMATCH",
        ),
        (lambda data: data["summary"]["inputs"][0]["outputs"].pop(), "OUTPUT_MISMATCH"),
        (
            lambda data: data["summary"]["inputs"][0]["outputs"][1].update(
                coin_id=OUT_CAT
            ),
            "DUPLICATE_OUTPUT_ID",
        ),
    ],
)
def test_unsigned_validation_refuses_changed_effect(mutate, reason):
    value = response()
    mutate(value)
    result = wallet_sage.validate_unsigned_transaction_effect(value, contract())
    assert result == {"success": False, "reason": reason}


def test_ephemeral_input_is_not_an_unclaimed_external_removal():
    value = response()
    ephemeral = "77" * 32
    value["summary"]["inputs"][0]["outputs"].append(output(ephemeral, 1))
    value["summary"]["inputs"].append(
        {
            "coin_id": ephemeral,
            "amount": "1",
            "address": ADDRESS,
            "asset": {"asset_id": ASSET},
            "outputs": [],
        }
    )
    # The ephemeral branch produces no final output, so remove it from the expected effect.
    assert (
        wallet_sage.validate_unsigned_transaction_effect(value, contract())["success"]
        is True
    )


def test_summary_without_inspectable_fields_is_refused_before_signing():
    assert wallet_sage.validate_unsigned_transaction_effect(
        {"coin_spends": [{}]}, contract()
    ) == {"success": False, "reason": "UNSIGNED_EFFECT_NOT_INSPECTABLE"}


def test_malformed_summary_asset_is_not_silently_treated_as_xch():
    value = response()
    value["summary"]["inputs"][1]["asset"] = "xch"
    assert wallet_sage.validate_unsigned_transaction_effect(value, contract()) == {
        "success": False,
        "reason": "UNSIGNED_EFFECT_NOT_INSPECTABLE",
    }


def test_equal_outputs_are_bound_to_distinct_ids_deterministically():
    value = response()
    value["summary"]["inputs"][0]["outputs"] = [
        output(OUT_CAT_2, 40),
        output(OUT_CAT, 40),
    ]
    expected = contract()
    expected["outputs"][1].update(amount_mojos=40, purpose="tier", ordinal=1)
    sealed = wallet_sage.validate_unsigned_transaction_effect(value, expected)
    tier_outputs = [
        item for item in sealed["constructed_outputs"] if item["asset"] == "cat"
    ]
    assert [(item["ordinal"], item["coin_id"]) for item in tier_outputs] == [
        (0, OUT_CAT),
        (1, OUT_CAT_2),
    ]


def test_unvalidated_unsigned_result_cannot_reach_signing(monkeypatch):
    post = Mock()
    monkeypatch.setattr(wallet_sage, "_sage_post", post)
    result = wallet_sage.submit_built_transaction_rpc({"coin_spends": [{}]})
    assert result["success"] is False
    assert result["reason"] == "UNSIGNED_EFFECT_NOT_VALIDATED"
    assert result["_catalyst_effect_attempted"] is False
    post.assert_not_called()


def test_validated_result_rechecks_before_sign_and_submit(monkeypatch):
    events = []
    sealed = wallet_sage.validate_unsigned_transaction_effect(response(), contract())

    def post(endpoint, payload, timeout=30):
        events.append(endpoint)
        if endpoint == "sign_coin_spends":
            return {"spend_bundle": {"aggregated_signature": "sig", "coin_spends": []}}
        return {"success": True, "transaction_id": "99" * 32}

    monkeypatch.setattr(wallet_sage, "_sage_post", post)
    result = wallet_sage.submit_built_transaction_rpc(
        sealed, _identity_recheck=lambda step: events.append(f"check:{step}")
    )
    assert result["success"] is True
    assert events == [
        "check:create_transaction:sign",
        "sign_coin_spends",
        "check:create_transaction:submit",
        "submit_transaction",
    ]


def test_validated_result_cannot_be_changed_between_validation_and_signing(monkeypatch):
    sealed = wallet_sage.validate_unsigned_transaction_effect(response(), contract())
    sealed["coin_spends"].append({"coin": {"amount": "1"}})
    post = Mock()
    monkeypatch.setattr(wallet_sage, "_sage_post", post)
    result = wallet_sage.submit_built_transaction_rpc(sealed)
    assert result["success"] is False
    assert result["reason"] == "UNSIGNED_EFFECT_NOT_VALIDATED"
    post.assert_not_called()
