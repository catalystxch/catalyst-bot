from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json

import pytest
from chia_rs import AugSchemeMPL, Program

from bootstrap_manifest import manifest_campaign_id
from bootstrap_proof import (
    DirectoryVerification,
    ProofError,
    build_directory_record,
    build_participation_report,
    canonical_participation_bytes,
    participation_report_id,
    sign_participation_report,
    verify_directory_record,
    verify_participation_report,
)
from test_bootstrap_manifest import ADDRESS, ASSET_ID, make_manifest, sign_manifest


CAMPAIGN_ID = "ab" * 32
OFFER_1 = "01" * 32
OFFER_2 = "02" * 32
OFFER_OWN = "03" * 32
FILL_1 = "11" * 32
FILL_LINKED = "12" * 32
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def observations(*, depth="2", spread="150", volume="0") -> dict:
    return {
        "network": "mainnet",
        "asset_id": ASSET_ID,
        "period_start": "2026-09-12T10:00:00.000000Z",
        "period_end": "2026-09-12T11:00:00.000000Z",
        "expires_at": "2026-09-19T11:00:00.000000Z",
        "wallet_fingerprint": 736588221,
        "balances": {"xch": "99", "cat": "1000000"},
        "local_path": "C:/Users/private/AppData/Roaming/Catalyst",
        "unrelated_history": [{"trade_id": "private"}],
        "samples": [
            {
                "observation_id": "21" * 32,
                "observed_at": "2026-09-12T10:00:00.000000Z",
                "duration_seconds": 300,
                "independent_depth_xch": depth,
                "spread_bps": spread,
                "within_corridor": True,
                "own": False,
                "linked": False,
                "offer_ids": [OFFER_2, OFFER_1],
                "fill_ids": [FILL_1],
                "trade_volume_xch": volume,
                "wallet_balance": "999",
            },
            {
                "observation_id": "22" * 32,
                "observed_at": "2026-09-12T10:05:00.000000Z",
                "duration_seconds": 300,
                "independent_depth_xch": "500",
                "spread_bps": "1",
                "within_corridor": True,
                "own": True,
                "linked": False,
                "offer_ids": [OFFER_OWN],
                "fill_ids": [],
            },
            {
                "observation_id": "23" * 32,
                "observed_at": "2026-09-12T10:10:00.000000Z",
                "duration_seconds": 300,
                "independent_depth_xch": "500",
                "spread_bps": "1",
                "within_corridor": True,
                "own": False,
                "linked": True,
                "offer_ids": [],
                "fill_ids": [FILL_LINKED],
            },
        ],
    }


def sign_report(report: dict) -> dict:
    secret_key = AugSchemeMPL.key_gen(b"catalyst participation report test" + b"\0")
    message = canonical_participation_bytes(report)
    tree_hash = bytes(Program.to((b"Chia Signed Message", message)).get_tree_hash())
    return {
        "report": deepcopy(report),
        "signature": {
            "algorithm": "chia-bls-aug-synthetic-v1",
            "signing_address": ADDRESS,
            "public_key": bytes(secret_key.get_g1()).hex(),
            "signature": bytes(AugSchemeMPL.sign(secret_key, tree_hash)).hex(),
            "message_digest": hashlib.sha256(message).hexdigest(),
        },
    }


def test_quality_score_changes_with_depth_uptime_and_spread_but_not_volume():
    baseline = build_participation_report(CAMPAIGN_ID, observations())
    deeper = build_participation_report(
        CAMPAIGN_ID, observations(depth="4", volume="999999")
    )
    tighter = build_participation_report(CAMPAIGN_ID, observations(spread="50"))
    longer_input = observations()
    longer_input["samples"].append(
        {
            "observation_id": "25" * 32,
            "observed_at": "2026-09-12T10:15:00.000000Z",
            "duration_seconds": 300,
            "independent_depth_xch": "2",
            "spread_bps": "150",
            "within_corridor": True,
            "own": False,
            "linked": False,
            "offer_ids": [OFFER_1],
            "fill_ids": [],
        }
    )
    longer = build_participation_report(CAMPAIGN_ID, longer_input)
    volume_only = build_participation_report(
        CAMPAIGN_ID, observations(volume="123456789")
    )

    assert deeper["quality"]["depth_score"] > baseline["quality"]["depth_score"]
    assert tighter["quality"]["spread_score"] > baseline["quality"]["spread_score"]
    assert longer["quality"]["uptime_score"] > baseline["quality"]["uptime_score"]
    assert volume_only == baseline
    assert "volume" not in json.dumps(baseline).lower()
    assert Decimal(baseline["quality"]["total_score"]) <= 100


def test_own_linked_and_out_of_corridor_observations_are_excluded():
    data = observations()
    data["samples"].append(
        {
            "observation_id": "24" * 32,
            "observed_at": "2026-09-12T10:15:00.000000Z",
            "duration_seconds": 300,
            "independent_depth_xch": "500",
            "spread_bps": "1",
            "within_corridor": False,
            "own": False,
            "linked": False,
            "offer_ids": ["04" * 32],
            "fill_ids": ["14" * 32],
        }
    )

    report = build_participation_report(CAMPAIGN_ID, data)

    assert report["eligible_offer_ids"] == [OFFER_1, OFFER_2]
    assert report["eligible_fill_ids"] == [FILL_1]
    assert report["eligible_observation_ids"] == ["21" * 32]
    assert report["quality"]["uptime_seconds"] == 300
    assert report["quality"]["depth_xch_seconds"] == "600"
    assert report["quality"]["average_spread_bps"] == "150"


def test_private_wallet_fields_never_serialize_into_report_or_signing_request():
    report = build_participation_report(CAMPAIGN_ID, observations())
    signing_request = sign_participation_report(report, ADDRESS)
    serialized = json.dumps({"report": report, "request": signing_request}).lower()

    for forbidden in (
        "fingerprint",
        "balance",
        "local_path",
        "c:/users",
        "unrelated_history",
        "private",
    ):
        assert forbidden not in serialized
    assert signing_request["method"] == "chia_signMessageByAddress"
    assert signing_request["address"] == ADDRESS
    assert (
        signing_request["message"] == "0x" + canonical_participation_bytes(report).hex()
    )


def test_report_is_canonical_deterministic_and_signature_verifies():
    data = observations()
    data["samples"] = list(reversed(data["samples"]))
    report = build_participation_report(CAMPAIGN_ID, data)
    signed = sign_report(report)

    verification = verify_participation_report(
        signed, expected_network="mainnet", now=NOW
    )

    assert verification.status == "VERIFIED"
    assert verification.report_id == participation_report_id(report)
    assert verification.campaign_id == CAMPAIGN_ID
    assert verification.signing_address == ADDRESS
    assert verification.public_key == signed["signature"]["public_key"]


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda signed: signed["signature"].__setitem__("signature", "00" * 96),
            "signature_invalid",
        ),
        (
            lambda signed: signed["report"].__setitem__("network", "testnet"),
            "signing_address_network_mismatch",
        ),
        (
            lambda signed: signed["report"]["quality"].__setitem__(
                "total_score", "1.0"
            ),
            "invalid_total_score",
        ),
    ],
)
def test_tampered_or_noncanonical_report_is_rejected(mutate, reason):
    signed = sign_report(build_participation_report(CAMPAIGN_ID, observations()))
    mutate(signed)

    verification = verify_participation_report(signed, now=NOW)

    assert verification.status == "INVALID"
    assert verification.reason_code == reason


def test_report_rejects_wrong_expected_network_and_expiry():
    signed = sign_report(build_participation_report(CAMPAIGN_ID, observations()))

    wrong_network = verify_participation_report(
        signed, expected_network="testnet", now=NOW
    )
    expired = verify_participation_report(
        signed, expected_network="mainnet", now=NOW + timedelta(days=8)
    )

    assert wrong_network.reason_code == "participation_network_mismatch"
    assert expired.reason_code == "participation_report_expired"


def test_static_directory_record_requires_valid_bound_manifest_and_report():
    signed_manifest = sign_manifest(make_manifest())
    record = build_directory_record(
        signed_manifest,
        asset_verification_status="UNVERIFIED_ASSET",
    )

    result = verify_directory_record(record, expected_network="mainnet", now=NOW)

    assert isinstance(result, DirectoryVerification)
    assert result.status == "VERIFIED"
    assert record["network"] == "mainnet"
    assert record["asset_id"] == ASSET_ID
    assert record["manifest_campaign_id"] == manifest_campaign_id(make_manifest())
    assert record["asset_verification_status"] == "UNVERIFIED_ASSET"
    assert record["signer_public_key"] == signed_manifest["signature"]["public_key"]
    assert "endorsement" not in record


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda record: record["signed_manifest"]["signature"].__setitem__(
                "signature", "00" * 96
            ),
            "directory_manifest_signature_invalid",
        ),
        (
            lambda record: record.__setitem__("network", "testnet"),
            "directory_network_mismatch",
        ),
        (
            lambda record: record.__setitem__(
                "expires_at", "2026-09-11T11:00:00.000000Z"
            ),
            "directory_record_expired",
        ),
        (
            lambda record: record.__setitem__("expires_at", "2026-09-19T11:00:00Z"),
            "invalid_directory_expires_at",
        ),
    ],
)
def test_static_directory_rejects_bad_signature_network_expiry_or_canonicality(
    mutate, reason
):
    signed_manifest = sign_manifest(make_manifest())
    record = build_directory_record(
        signed_manifest,
        asset_verification_status="VERIFIED",
    )
    mutate(record)

    result = verify_directory_record(record, expected_network="mainnet", now=NOW)

    assert result.status == "INVALID"
    assert result.reason_code == reason


def test_overlapping_or_unbounded_samples_are_rejected():
    data = observations()
    data["samples"][1]["own"] = False
    data["samples"][1]["observed_at"] = "2026-09-12T10:04:59.000000Z"
    with pytest.raises(ProofError, match="overlapping_observation_window"):
        build_participation_report(CAMPAIGN_ID, data)

    data = observations()
    data["samples"][0]["duration_seconds"] = 301
    with pytest.raises(ProofError, match="observation_duration_unbounded"):
        build_participation_report(CAMPAIGN_ID, data)

    data = observations()
    data["period_start"] = "2026-09-04T10:00:00.000000Z"
    with pytest.raises(ProofError, match="participation_period_unbounded"):
        build_participation_report(CAMPAIGN_ID, data)

    data = observations()
    data["samples"] = [{}] * 2017
    with pytest.raises(ProofError, match="too_many_observation_samples"):
        build_participation_report(CAMPAIGN_ID, data)


def test_static_directory_schema_and_docs_are_fail_closed_and_nonendorsing():
    schema = json.loads(
        (ROOT / "docs" / "bootstrap-directory" / "schema.json").read_text(
            encoding="utf-8"
        )
    )
    readme = (ROOT / "docs" / "bootstrap-directory" / "README.md").read_text(
        encoding="utf-8"
    )

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema",
        "network",
        "asset_id",
        "ticker",
        "manifest_campaign_id",
        "expires_at",
        "signing_address",
        "signer_public_key",
        "signature",
        "message_digest",
        "asset_verification_status",
        "signed_manifest",
    }
    assert schema["properties"]["asset_verification_status"]["enum"] == [
        "VERIFIED",
        "UNVERIFIED_ASSET",
    ]
    assert "not an endorsement" in readme.lower()
    assert "chooses its own" in readme.lower()
    for word in ("budget", "reserve", "loss", "fee"):
        assert word in readme.lower()
