from __future__ import annotations

from copy import deepcopy

import pytest
from chia_rs import AugSchemeMPL, Program

from bootstrap_manifest import (
    ManifestError,
    canonical_manifest_bytes,
    manifest_campaign_id,
    safe_import_manifest,
    verify_campaign_manifest,
)


ADDRESS = "xch1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"
ASSET_ID = "b8" * 32


def make_manifest() -> dict:
    return {
        "schema": "catalyst.bootstrap.manifest.v1",
        "network": "mainnet",
        "asset_id": ASSET_ID,
        "ticker": "MZ",
        "anchor_price": "0.001",
        "minimum_price": "0.0005",
        "maximum_price": "0.002",
        "created_at": "2026-09-12T10:00:00.000000Z",
        "expires_at": "2026-09-19T10:00:00.000000Z",
        "offer_levels_per_side": 3,
        "capacity_stages": ["0.1", "0.25", "0.5", "1"],
        "stage_thresholds": {
            "discovery_25": {
                "confirmed_fills": 2,
                "settlement_clusters": 2,
                "stable_seconds": 0,
            },
            "discovery_50": {
                "confirmed_fills": 6,
                "settlement_clusters": 3,
                "stable_seconds": 1800,
            },
            "established": {
                "confirmed_fills": 12,
                "settlement_clusters": 5,
                "stable_seconds": 7200,
            },
        },
        "anchor_caps": {"hourly": "0.05", "daily": "0.2"},
        "adverse_fill_cooldown_seconds": 300,
        "loss_stop_fraction": "0.05",
        "partial_offers": "disabled_until_capability_proven",
    }


def sign_manifest(manifest: dict) -> dict:
    secret_key = AugSchemeMPL.key_gen(b"catalyst bootstrap manifest test" + b"\0" * 5)
    message = canonical_manifest_bytes(manifest)
    tree_hash = bytes(Program.to((b"Chia Signed Message", message)).get_tree_hash())
    return {
        "manifest": deepcopy(manifest),
        "signature": {
            "algorithm": "chia-bls-aug-synthetic-v1",
            "signing_address": ADDRESS,
            "public_key": bytes(secret_key.get_g1()).hex(),
            "signature": bytes(AugSchemeMPL.sign(secret_key, tree_hash)).hex(),
            "message_digest": __import__("hashlib").sha256(message).hexdigest(),
        },
    }


def test_canonicalization_and_campaign_id_ignore_dictionary_order():
    manifest = make_manifest()
    reordered = {key: manifest[key] for key in reversed(manifest)}
    reordered["stage_thresholds"] = {
        key: manifest["stage_thresholds"][key]
        for key in reversed(manifest["stage_thresholds"])
    }

    assert canonical_manifest_bytes(reordered) == canonical_manifest_bytes(manifest)
    assert manifest_campaign_id(reordered) == manifest_campaign_id(manifest)


@pytest.mark.parametrize(
    "forbidden",
    [
        {"wallet_fingerprint": 736588221},
        {"balances": {"xch": "1"}},
        {"credential": "secret"},
        {"unrelated_address": "xch1other"},
        {"local_path": "C:/Users/example/wallet"},
        {"xch_budget": "1"},
        {"cat_budget": "100"},
        {"fee_budget_xch": "0.1"},
        {"subsidy_budget_xch": "0.1"},
        {"reserve_xch": "0.5"},
    ],
)
def test_private_or_financial_authority_fields_are_rejected(forbidden):
    manifest = make_manifest() | forbidden

    with pytest.raises(ManifestError, match="forbidden_manifest_field"):
        canonical_manifest_bytes(manifest)


def test_noncanonical_decimal_text_is_rejected():
    manifest = make_manifest()
    manifest["anchor_price"] = "0.0010"

    with pytest.raises(ManifestError, match="invalid_anchor_price"):
        canonical_manifest_bytes(manifest)


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("minimum_price",), "0.0004", "invalid_price_corridor"),
        (("maximum_price",), "0.003", "invalid_price_corridor"),
        (("anchor_caps", "hourly"), "0.06", "invalid_anchor_caps"),
        (("anchor_caps", "daily"), "0.25", "invalid_anchor_caps"),
        (("loss_stop_fraction",), "0.1", "invalid_loss_stop_fraction"),
        (
            ("stage_thresholds", "discovery_25", "confirmed_fills"),
            1,
            "invalid_stage_thresholds",
        ),
    ],
)
def test_manifest_cannot_weaken_the_approved_bootstrap_safety_policy(path, value, code):
    manifest = make_manifest()
    target = manifest
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ManifestError, match=code):
        canonical_manifest_bytes(manifest)


def test_valid_sage_style_bls_signature_is_verified():
    signed = sign_manifest(make_manifest())

    verification = verify_campaign_manifest(signed)

    assert verification.status == "VERIFIED"
    assert verification.campaign_id == manifest_campaign_id(make_manifest())
    assert verification.signing_address == ADDRESS


def test_changing_one_anchor_digit_invalidates_signature():
    signed = sign_manifest(make_manifest())
    signed["manifest"]["anchor_price"] = "0.002"
    signed["manifest"]["minimum_price"] = "0.001"
    signed["manifest"]["maximum_price"] = "0.004"

    verification = verify_campaign_manifest(signed)

    assert verification.status == "INVALID"
    assert verification.reason_code == "message_digest_mismatch"


def test_import_contains_no_remote_financial_or_trading_authority():
    imported = safe_import_manifest(sign_manifest(make_manifest()), "mainnet")

    assert imported.verification_status == "VERIFIED"
    assert imported.network == "mainnet"
    assert imported.asset_id == ASSET_ID
    assert imported.anchor_price == "0.001"
    assert imported.minimum_price == "0.0005"
    assert imported.maximum_price == "0.002"
    assert imported.requires_local_budget_acceptance is True
    assert not hasattr(imported, "xch_budget")
    assert not hasattr(imported, "cat_budget")
    assert not hasattr(imported, "fee_budget_xch")
    assert not hasattr(imported, "subsidy_budget_xch")
    assert not hasattr(imported, "trading_authority")


def test_import_rejects_wrong_network():
    with pytest.raises(ManifestError, match="manifest_network_mismatch"):
        safe_import_manifest(sign_manifest(make_manifest()), "testnet")


def test_unlisted_asset_is_explicitly_unverified_not_rejected():
    imported = safe_import_manifest(
        sign_manifest(make_manifest()),
        "mainnet",
        known_asset_ids=set(),
    )

    assert imported.verification_status == "UNVERIFIED_ASSET"
    assert imported.requires_local_budget_acceptance is True
