"""Canonical public manifests for isolated Market Bootstrap campaigns.

The manifest is deliberately descriptive, not authoritative.  It carries a
public price corridor and fixed safety policy, but never another user's wallet
identity, balances, budgets, reserves, or permission to trade.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Collection

from chia_rs import AugSchemeMPL, G1Element, G2Element, Program


MANIFEST_SCHEMA = "catalyst.bootstrap.manifest.v1"
SIGNATURE_ALGORITHM = "chia-bls-aug-synthetic-v1"

_MANIFEST_FIELDS = {
    "schema",
    "network",
    "asset_id",
    "ticker",
    "anchor_price",
    "minimum_price",
    "maximum_price",
    "created_at",
    "expires_at",
    "offer_levels_per_side",
    "capacity_stages",
    "stage_thresholds",
    "anchor_caps",
    "adverse_fill_cooldown_seconds",
    "loss_stop_fraction",
    "partial_offers",
}
_STAGE_NAMES = ("discovery_25", "discovery_50", "established")
_STAGE_FIELDS = {"confirmed_fills", "settlement_clusters", "stable_seconds"}
_STAGE_THRESHOLDS = {
    "discovery_25": (2, 2, 0),
    "discovery_50": (6, 3, 1800),
    "established": (12, 5, 7200),
}
_SIGNATURE_FIELDS = {
    "algorithm",
    "signing_address",
    "public_key",
    "signature",
    "message_digest",
}
_FORBIDDEN_FIELD_PARTS = (
    "fingerprint",
    "balance",
    "credential",
    "secret",
    "private",
    "local_path",
    "budget",
    "reserve",
    "trading_authority",
)


class ManifestError(ValueError):
    """Stable validation failure for an untrusted manifest."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ManifestVerification:
    status: str
    campaign_id: str
    reason_code: str | None
    signing_address: str | None
    public_key: str | None


@dataclass(frozen=True)
class ImportedManifest:
    campaign_id: str
    verification_status: str
    network: str
    asset_id: str
    ticker: str
    anchor_price: str
    minimum_price: str
    maximum_price: str
    created_at: str
    expires_at: str
    offer_levels_per_side: int
    capacity_stages: tuple[str, ...]
    stage_thresholds: dict[str, dict[str, int]]
    anchor_caps: dict[str, str]
    adverse_fill_cooldown_seconds: int
    loss_stop_fraction: str
    partial_offers: str
    signer_public_key: str
    signing_address: str
    requires_local_budget_acceptance: bool = True


def _forbid_private_fields(value: Any) -> None:
    if type(value) is dict:
        for key, nested in value.items():
            if type(key) is not str:
                raise ManifestError("invalid_manifest_field")
            lowered = key.lower()
            if any(part in lowered for part in _FORBIDDEN_FIELD_PARTS):
                raise ManifestError(f"forbidden_manifest_field:{key}")
            if lowered.endswith("address"):
                raise ManifestError(f"forbidden_manifest_field:{key}")
            _forbid_private_fields(nested)
    elif type(value) is list:
        for nested in value:
            _forbid_private_fields(nested)


def _canonical_decimal(value: Any, field: str, *, positive: bool = True) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ManifestError(f"invalid_{field}")
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ManifestError(f"invalid_{field}") from exc
    if not decimal.is_finite() or (positive and decimal <= 0):
        raise ManifestError(f"invalid_{field}")
    canonical = format(decimal, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical == "-0":
        canonical = "0"
    if canonical != value:
        raise ManifestError(f"invalid_{field}")
    return canonical


def _canonical_timestamp(value: Any, field: str) -> str:
    if type(value) is not str or not value.endswith("Z"):
        raise ManifestError(f"invalid_{field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ManifestError(f"invalid_{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ManifestError(f"invalid_{field}")
    canonical = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if canonical != value:
        raise ManifestError(f"invalid_{field}")
    return canonical


def _exact_nonnegative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ManifestError(f"invalid_{field}")
    return value


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """Validate and return a detached canonical-shape manifest."""

    if type(manifest) is not dict:
        raise ManifestError("invalid_manifest")
    _forbid_private_fields(manifest)
    if set(manifest) != _MANIFEST_FIELDS:
        unknown = sorted(set(manifest) - _MANIFEST_FIELDS)
        if unknown:
            raise ManifestError(f"forbidden_manifest_field:{unknown[0]}")
        raise ManifestError("missing_manifest_field")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ManifestError("invalid_manifest_schema")
    if manifest["network"] not in {"mainnet", "testnet"}:
        raise ManifestError("invalid_network")
    asset_id = manifest["asset_id"]
    if type(asset_id) is not str or re.fullmatch(r"[0-9a-f]{64}", asset_id) is None:
        raise ManifestError("invalid_asset_id")
    ticker = manifest["ticker"]
    if (
        type(ticker) is not str
        or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,15}", ticker) is None
    ):
        raise ManifestError("invalid_ticker")

    anchor = _canonical_decimal(manifest["anchor_price"], "anchor_price")
    minimum = _canonical_decimal(manifest["minimum_price"], "minimum_price")
    maximum = _canonical_decimal(manifest["maximum_price"], "maximum_price")
    if Decimal(minimum) != Decimal(anchor) * Decimal("0.5") or Decimal(
        maximum
    ) != Decimal(anchor) * Decimal("2"):
        raise ManifestError("invalid_price_corridor")

    created_at = _canonical_timestamp(manifest["created_at"], "created_at")
    expires_at = _canonical_timestamp(manifest["expires_at"], "expires_at")
    if expires_at <= created_at:
        raise ManifestError("invalid_expiry")
    if manifest["offer_levels_per_side"] != 3:
        raise ManifestError("invalid_offer_levels_per_side")
    if manifest["capacity_stages"] != ["0.1", "0.25", "0.5", "1"]:
        raise ManifestError("invalid_capacity_stages")

    thresholds = manifest["stage_thresholds"]
    if type(thresholds) is not dict or set(thresholds) != set(_STAGE_NAMES):
        raise ManifestError("invalid_stage_thresholds")
    normalized_thresholds: dict[str, dict[str, int]] = {}
    for stage in _STAGE_NAMES:
        threshold = thresholds[stage]
        if type(threshold) is not dict or set(threshold) != _STAGE_FIELDS:
            raise ManifestError("invalid_stage_thresholds")
        current = tuple(
            _exact_nonnegative_int(threshold[field], f"{stage}_{field}")
            for field in ("confirmed_fills", "settlement_clusters", "stable_seconds")
        )
        if current != _STAGE_THRESHOLDS[stage]:
            raise ManifestError("invalid_stage_thresholds")
        normalized_thresholds[stage] = {
            "confirmed_fills": current[0],
            "settlement_clusters": current[1],
            "stable_seconds": current[2],
        }

    caps = manifest["anchor_caps"]
    if type(caps) is not dict or set(caps) != {"hourly", "daily"}:
        raise ManifestError("invalid_anchor_caps")
    hourly = _canonical_decimal(caps["hourly"], "hourly_anchor_cap")
    daily = _canonical_decimal(caps["daily"], "daily_anchor_cap")
    if hourly != "0.05" or daily != "0.2":
        raise ManifestError("invalid_anchor_caps")
    if manifest["adverse_fill_cooldown_seconds"] != 300:
        raise ManifestError("invalid_adverse_fill_cooldown_seconds")
    loss_stop = _canonical_decimal(manifest["loss_stop_fraction"], "loss_stop_fraction")
    if loss_stop != "0.05":
        raise ManifestError("invalid_loss_stop_fraction")
    if manifest["partial_offers"] != "disabled_until_capability_proven":
        raise ManifestError("invalid_partial_offer_policy")

    return {
        "schema": MANIFEST_SCHEMA,
        "network": manifest["network"],
        "asset_id": asset_id,
        "ticker": ticker,
        "anchor_price": anchor,
        "minimum_price": minimum,
        "maximum_price": maximum,
        "created_at": created_at,
        "expires_at": expires_at,
        "offer_levels_per_side": 3,
        "capacity_stages": ["0.1", "0.25", "0.5", "1"],
        "stage_thresholds": normalized_thresholds,
        "anchor_caps": {"hourly": hourly, "daily": daily},
        "adverse_fill_cooldown_seconds": 300,
        "loss_stop_fraction": loss_stop,
        "partial_offers": "disabled_until_capability_proven",
    }


def canonical_manifest_bytes(manifest: Any) -> bytes:
    normalized = validate_manifest(manifest)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def manifest_campaign_id(manifest: Any) -> str:
    return "bootstrap_" + hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def sage_message_tree_hash(message: bytes) -> bytes:
    if type(message) is not bytes or not message:
        raise ManifestError("invalid_signature_message")
    return bytes(Program.to((b"Chia Signed Message", message)).get_tree_hash())


def _hex_bytes(value: Any, length: int, field: str) -> bytes:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]+", value) is None:
        raise ManifestError(f"invalid_{field}")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ManifestError(f"invalid_{field}") from exc
    if len(decoded) != length:
        raise ManifestError(f"invalid_{field}")
    return decoded


def verify_campaign_manifest(signed_manifest: Any) -> ManifestVerification:
    campaign_id = ""
    try:
        if type(signed_manifest) is not dict or set(signed_manifest) != {
            "manifest",
            "signature",
        }:
            raise ManifestError("invalid_signed_manifest")
        message = canonical_manifest_bytes(signed_manifest["manifest"])
        campaign_id = manifest_campaign_id(signed_manifest["manifest"])
        signature = signed_manifest["signature"]
        if type(signature) is not dict or set(signature) != _SIGNATURE_FIELDS:
            raise ManifestError("invalid_signature_envelope")
        if signature["algorithm"] != SIGNATURE_ALGORITHM:
            raise ManifestError("unsupported_signature_algorithm")
        address = signature["signing_address"]
        if (
            type(address) is not str
            or re.fullmatch(r"(?:xch|txch)1[0-9a-z]{20,90}", address) is None
        ):
            raise ManifestError("invalid_signing_address")
        expected_prefix = (
            "xch1" if signed_manifest["manifest"]["network"] == "mainnet" else "txch1"
        )
        if not address.startswith(expected_prefix):
            raise ManifestError("signing_address_network_mismatch")
        digest = hashlib.sha256(message).hexdigest()
        if signature["message_digest"] != digest:
            raise ManifestError("message_digest_mismatch")
        public_key_text = signature["public_key"]
        public_key = G1Element.from_bytes(_hex_bytes(public_key_text, 48, "public_key"))
        bls_signature = G2Element.from_bytes(
            _hex_bytes(signature["signature"], 96, "signature")
        )
        if not AugSchemeMPL.verify(
            public_key, sage_message_tree_hash(message), bls_signature
        ):
            raise ManifestError("signature_invalid")
        return ManifestVerification(
            status="VERIFIED",
            campaign_id=campaign_id,
            reason_code=None,
            signing_address=address,
            public_key=public_key_text,
        )
    except (ManifestError, ValueError) as exc:
        code = exc.code if isinstance(exc, ManifestError) else "signature_invalid"
        return ManifestVerification(
            status="INVALID",
            campaign_id=campaign_id,
            reason_code=code,
            signing_address=None,
            public_key=None,
        )


def safe_import_manifest(
    signed_manifest: Any,
    expected_network: str,
    *,
    known_asset_ids: Collection[str] | None = None,
) -> ImportedManifest:
    verification = verify_campaign_manifest(signed_manifest)
    if verification.status != "VERIFIED":
        raise ManifestError(verification.reason_code or "invalid_manifest_signature")
    manifest = validate_manifest(signed_manifest["manifest"])
    if manifest["network"] != expected_network:
        raise ManifestError("manifest_network_mismatch")
    status = "VERIFIED"
    if known_asset_ids is not None and manifest["asset_id"] not in known_asset_ids:
        status = "UNVERIFIED_ASSET"
    return ImportedManifest(
        campaign_id=verification.campaign_id,
        verification_status=status,
        network=manifest["network"],
        asset_id=manifest["asset_id"],
        ticker=manifest["ticker"],
        anchor_price=manifest["anchor_price"],
        minimum_price=manifest["minimum_price"],
        maximum_price=manifest["maximum_price"],
        created_at=manifest["created_at"],
        expires_at=manifest["expires_at"],
        offer_levels_per_side=manifest["offer_levels_per_side"],
        capacity_stages=tuple(manifest["capacity_stages"]),
        stage_thresholds=manifest["stage_thresholds"],
        anchor_caps=manifest["anchor_caps"],
        adverse_fill_cooldown_seconds=manifest["adverse_fill_cooldown_seconds"],
        loss_stop_fraction=manifest["loss_stop_fraction"],
        partial_offers=manifest["partial_offers"],
        signer_public_key=verification.public_key or "",
        signing_address=verification.signing_address or "",
    )
