"""Privacy-bounded participation proofs for Market Bootstrap campaigns.

The report builder deliberately projects untrusted observations onto a small
public schema.  Wallet fingerprints, balances, local paths, unrelated history,
trade volume, and reward amounts therefore cannot enter the canonical bytes.
Signing is interactive: :func:`sign_participation_report` only constructs the
single ``chia_signMessageByAddress`` request that Sage must approve.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
import re
from typing import Any

from chia_rs import AugSchemeMPL, G1Element, G2Element

from bootstrap_manifest import (
    SIGNATURE_ALGORITHM,
    manifest_campaign_id,
    sage_message_tree_hash,
    verify_campaign_manifest,
)


PARTICIPATION_SCHEMA = "catalyst.bootstrap.participation.v1"
DIRECTORY_SCHEMA = "catalyst.bootstrap.directory.v1"
WALLETCONNECT_METHOD = "chia_signMessageByAddress"

_HEX_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_ADDRESS_RE = re.compile(r"^(?:xch|txch)1[0-9a-z]{20,90}$")
_REPORT_FIELDS = {
    "schema",
    "campaign_id",
    "network",
    "asset_id",
    "period_start",
    "period_end",
    "expires_at",
    "eligible_observation_ids",
    "eligible_offer_ids",
    "eligible_fill_ids",
    "quality",
}
_QUALITY_FIELDS = {
    "depth_xch_seconds",
    "uptime_seconds",
    "average_independent_depth_xch",
    "average_spread_bps",
    "depth_score",
    "uptime_score",
    "spread_score",
    "total_score",
}
_SIGNATURE_FIELDS = {
    "algorithm",
    "signing_address",
    "public_key",
    "signature",
    "message_digest",
}
_DIRECTORY_FIELDS = {
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
_FORBIDDEN_PARTS = (
    "fingerprint",
    "balance",
    "credential",
    "secret",
    "private",
    "local_path",
    "unrelated",
    "volume",
    "reward",
    "budget",
    "reserve",
)
_MAX_SAMPLE_SECONDS = 300
_MAX_REPORT_PERIOD = timedelta(days=7)
_MAX_REPORT_SAMPLES = 2016
_MAX_REPORT_LIFETIME = timedelta(days=7)
_MAX_DEPTH_XCH = Decimal("1000000000")
_MAX_SPREAD_BPS = Decimal("100000")
_SCORE_QUANTUM = Decimal("0.000001")


class ProofError(ValueError):
    """Stable validation failure for an untrusted participation artifact."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProofVerification:
    status: str
    report_id: str
    campaign_id: str
    reason_code: str | None
    signing_address: str | None
    public_key: str | None


@dataclass(frozen=True)
class DirectoryVerification:
    status: str
    manifest_campaign_id: str
    reason_code: str | None
    signing_address: str | None
    public_key: str | None


def _canonical_decimal(
    value: Any,
    field: str,
    *,
    maximum: Decimal | None = None,
) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProofError(f"invalid_{field}")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ProofError(f"invalid_{field}") from exc
    if (
        not number.is_finite()
        or number < 0
        or (maximum is not None and number > maximum)
    ):
        raise ProofError(f"invalid_{field}")
    canonical = format(number, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical == "-0":
        canonical = "0"
    if canonical != value:
        raise ProofError(f"invalid_{field}")
    return canonical


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _score_text(value: Decimal) -> str:
    return _decimal_text(value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN))


def _canonical_timestamp(value: Any, field: str) -> tuple[str, datetime]:
    if type(value) is not str or not value.endswith("Z"):
        raise ProofError(f"invalid_{field}")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ProofError(f"invalid_{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ProofError(f"invalid_{field}")
    parsed = parsed.astimezone(timezone.utc)
    canonical = parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if canonical != value:
        raise ProofError(f"invalid_{field}")
    return canonical, parsed


def _hex_id(value: Any, field: str) -> str:
    if type(value) is not str or _HEX_ID_RE.fullmatch(value) is None:
        raise ProofError(f"invalid_{field}")
    return value


def _sorted_ids(value: Any, field: str) -> list[str]:
    if type(value) is not list:
        raise ProofError(f"invalid_{field}")
    normalized = [_hex_id(item, field) for item in value]
    if normalized != sorted(set(normalized)):
        raise ProofError(f"invalid_{field}")
    return normalized


def _forbid_private_fields(value: Any) -> None:
    if type(value) is dict:
        for key, nested in value.items():
            if type(key) is not str:
                raise ProofError("invalid_participation_field")
            lowered = key.lower()
            if any(part in lowered for part in _FORBIDDEN_PARTS):
                raise ProofError(f"forbidden_participation_field:{key}")
            _forbid_private_fields(nested)
    elif type(value) is list:
        for nested in value:
            _forbid_private_fields(nested)


def _normalize_quality(quality: Any, period_seconds: int) -> dict[str, Any]:
    if type(quality) is not dict or set(quality) != _QUALITY_FIELDS:
        raise ProofError("invalid_quality")
    depth_seconds = _canonical_decimal(
        quality["depth_xch_seconds"], "depth_xch_seconds"
    )
    uptime = quality["uptime_seconds"]
    if type(uptime) is not int or not 0 <= uptime <= period_seconds:
        raise ProofError("invalid_uptime_seconds")
    average_depth = _canonical_decimal(
        quality["average_independent_depth_xch"],
        "average_independent_depth_xch",
        maximum=_MAX_DEPTH_XCH,
    )
    average_spread = _canonical_decimal(
        quality["average_spread_bps"],
        "average_spread_bps",
        maximum=_MAX_SPREAD_BPS,
    )
    scores: dict[str, str] = {}
    for field, maximum in (
        ("depth_score", Decimal("40")),
        ("uptime_score", Decimal("35")),
        ("spread_score", Decimal("25")),
        ("total_score", Decimal("100")),
    ):
        text = _canonical_decimal(quality[field], field, maximum=maximum)
        if Decimal(text).as_tuple().exponent < -6:
            raise ProofError(f"invalid_{field}")
        scores[field] = text
    if Decimal(scores["total_score"]) != sum(
        Decimal(scores[field])
        for field in ("depth_score", "uptime_score", "spread_score")
    ):
        raise ProofError("invalid_total_score")
    if uptime == 0 and any(
        Decimal(value) != 0
        for value in (depth_seconds, average_depth, average_spread, *scores.values())
    ):
        raise ProofError("invalid_empty_quality")
    return {
        "depth_xch_seconds": depth_seconds,
        "uptime_seconds": uptime,
        "average_independent_depth_xch": average_depth,
        "average_spread_bps": average_spread,
        **scores,
    }


def validate_participation_report(report: Any) -> dict[str, Any]:
    if type(report) is not dict:
        raise ProofError("invalid_participation_report")
    _forbid_private_fields(report)
    if set(report) != _REPORT_FIELDS:
        unknown = sorted(set(report) - _REPORT_FIELDS)
        if unknown:
            raise ProofError(f"forbidden_participation_field:{unknown[0]}")
        raise ProofError("missing_participation_field")
    if report["schema"] != PARTICIPATION_SCHEMA:
        raise ProofError("invalid_participation_schema")
    campaign_id = _hex_id(report["campaign_id"], "campaign_id")
    network = report["network"]
    if network not in {"mainnet", "testnet"}:
        raise ProofError("invalid_network")
    asset_id = _hex_id(report["asset_id"], "asset_id")
    period_start, start = _canonical_timestamp(report["period_start"], "period_start")
    period_end, end = _canonical_timestamp(report["period_end"], "period_end")
    expires_at, expiry = _canonical_timestamp(report["expires_at"], "expires_at")
    if end <= start:
        raise ProofError("invalid_participation_period")
    if end - start > _MAX_REPORT_PERIOD:
        raise ProofError("participation_period_unbounded")
    if expiry <= end or expiry - end > _MAX_REPORT_LIFETIME:
        raise ProofError("invalid_participation_expiry")
    period_seconds = int((end - start).total_seconds())
    observations = _sorted_ids(
        report["eligible_observation_ids"], "eligible_observation_ids"
    )
    offers = _sorted_ids(report["eligible_offer_ids"], "eligible_offer_ids")
    fills = _sorted_ids(report["eligible_fill_ids"], "eligible_fill_ids")
    quality = _normalize_quality(report["quality"], period_seconds)
    return {
        "schema": PARTICIPATION_SCHEMA,
        "campaign_id": campaign_id,
        "network": network,
        "asset_id": asset_id,
        "period_start": period_start,
        "period_end": period_end,
        "expires_at": expires_at,
        "eligible_observation_ids": observations,
        "eligible_offer_ids": offers,
        "eligible_fill_ids": fills,
        "quality": quality,
    }


def canonical_participation_bytes(report: Any) -> bytes:
    return json.dumps(
        validate_participation_report(report),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def participation_report_id(report: Any) -> str:
    return hashlib.sha256(
        b"catalyst-bootstrap-participation-v1\0" + canonical_participation_bytes(report)
    ).hexdigest()


def build_participation_report(
    campaign_id: str, observations: dict[str, Any]
) -> dict[str, Any]:
    """Project bounded public observations into a deterministic report.

    Extra input fields are intentionally ignored rather than copied.  Samples
    marked own, linked, or outside the campaign corridor are ineligible before
    overlap checks and aggregation.
    """

    campaign_id = _hex_id(campaign_id, "campaign_id")
    if type(observations) is not dict:
        raise ProofError("invalid_observations")
    network = observations.get("network")
    if network not in {"mainnet", "testnet"}:
        raise ProofError("invalid_network")
    asset_id = _hex_id(observations.get("asset_id"), "asset_id")
    period_start, start = _canonical_timestamp(
        observations.get("period_start"), "period_start"
    )
    period_end, end = _canonical_timestamp(observations.get("period_end"), "period_end")
    expires_at, expiry = _canonical_timestamp(
        observations.get("expires_at"), "expires_at"
    )
    if end <= start:
        raise ProofError("invalid_participation_period")
    if end - start > _MAX_REPORT_PERIOD:
        raise ProofError("participation_period_unbounded")
    if expiry <= end or expiry - end > _MAX_REPORT_LIFETIME:
        raise ProofError("invalid_participation_expiry")
    raw_samples = observations.get("samples")
    if type(raw_samples) is not list:
        raise ProofError("invalid_observation_samples")
    if len(raw_samples) > _MAX_REPORT_SAMPLES:
        raise ProofError("too_many_observation_samples")

    eligible: list[dict[str, Any]] = []
    seen_observation_ids: set[str] = set()
    for sample in raw_samples:
        if type(sample) is not dict:
            raise ProofError("invalid_observation_sample")
        own = sample.get("own")
        linked = sample.get("linked")
        within_corridor = sample.get("within_corridor")
        if type(own) is not bool or type(linked) is not bool:
            raise ProofError("invalid_observation_attribution")
        if type(within_corridor) is not bool:
            raise ProofError("invalid_observation_corridor")
        if own or linked or not within_corridor:
            continue
        observation_id = _hex_id(sample.get("observation_id"), "observation_id")
        if observation_id in seen_observation_ids:
            raise ProofError("duplicate_observation_id")
        seen_observation_ids.add(observation_id)
        _observed_at, observed = _canonical_timestamp(
            sample.get("observed_at"), "observed_at"
        )
        duration = sample.get("duration_seconds")
        if type(duration) is not int or duration <= 0:
            raise ProofError("invalid_observation_duration")
        if duration > _MAX_SAMPLE_SECONDS:
            raise ProofError("observation_duration_unbounded")
        sample_end = observed + timedelta(seconds=duration)
        if observed < start or sample_end > end:
            raise ProofError("observation_outside_report_period")
        depth = Decimal(
            _canonical_decimal(
                sample.get("independent_depth_xch"),
                "independent_depth_xch",
                maximum=_MAX_DEPTH_XCH,
            )
        )
        spread = Decimal(
            _canonical_decimal(
                sample.get("spread_bps"),
                "spread_bps",
                maximum=_MAX_SPREAD_BPS,
            )
        )
        offers = sample.get("offer_ids")
        fills = sample.get("fill_ids")
        if type(offers) is not list or type(fills) is not list:
            raise ProofError("invalid_observation_identities")
        eligible.append(
            {
                "observation_id": observation_id,
                "start": observed,
                "end": sample_end,
                "duration": duration,
                "depth": depth,
                "spread": spread,
                "offer_ids": [_hex_id(item, "offer_id") for item in offers],
                "fill_ids": [_hex_id(item, "fill_id") for item in fills],
            }
        )

    eligible.sort(key=lambda item: (item["start"], item["observation_id"]))
    for previous, current in zip(eligible, eligible[1:]):
        if current["start"] < previous["end"]:
            raise ProofError("overlapping_observation_window")

    uptime = sum(item["duration"] for item in eligible)
    depth_seconds = sum(
        (item["depth"] * item["duration"] for item in eligible), Decimal("0")
    )
    spread_seconds = sum(
        (item["spread"] * item["duration"] for item in eligible), Decimal("0")
    )
    period_seconds = int((end - start).total_seconds())
    if uptime:
        average_depth = depth_seconds / uptime
        average_spread = spread_seconds / uptime
        depth_score = Decimal("40") * average_depth / (average_depth + 1)
        uptime_score = Decimal("35") * Decimal(uptime) / Decimal(period_seconds)
        spread_score = (
            Decimal("25") * Decimal("1000") / (Decimal("1000") + average_spread)
        )
        score_parts = tuple(
            value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)
            for value in (depth_score, uptime_score, spread_score)
        )
    else:
        average_depth = Decimal("0")
        average_spread = Decimal("0")
        score_parts = (Decimal("0"), Decimal("0"), Decimal("0"))
    total_score = sum(score_parts, Decimal("0"))
    report = {
        "schema": PARTICIPATION_SCHEMA,
        "campaign_id": campaign_id,
        "network": network,
        "asset_id": asset_id,
        "period_start": period_start,
        "period_end": period_end,
        "expires_at": expires_at,
        "eligible_observation_ids": sorted(item["observation_id"] for item in eligible),
        "eligible_offer_ids": sorted(
            {identifier for item in eligible for identifier in item["offer_ids"]}
        ),
        "eligible_fill_ids": sorted(
            {identifier for item in eligible for identifier in item["fill_ids"]}
        ),
        "quality": {
            "depth_xch_seconds": _decimal_text(depth_seconds),
            "uptime_seconds": uptime,
            "average_independent_depth_xch": _decimal_text(average_depth),
            "average_spread_bps": _decimal_text(average_spread),
            "depth_score": _score_text(score_parts[0]),
            "uptime_score": _score_text(score_parts[1]),
            "spread_score": _score_text(score_parts[2]),
            "total_score": _score_text(total_score),
        },
    }
    return validate_participation_report(report)


def sign_participation_report(report: dict[str, Any], address: str) -> dict[str, str]:
    """Return the sole WalletConnect request Sage must approve interactively."""

    message = canonical_participation_bytes(report)
    if type(address) is not str or _ADDRESS_RE.fullmatch(address) is None:
        raise ProofError("invalid_signing_address")
    expected_prefix = "xch1" if report["network"] == "mainnet" else "txch1"
    if not address.startswith(expected_prefix):
        raise ProofError("signing_address_network_mismatch")
    return {
        "method": WALLETCONNECT_METHOD,
        "address": address,
        "message": "0x" + message.hex(),
        "message_digest": hashlib.sha256(message).hexdigest(),
    }


def _signature_bytes(value: Any, size: int, field: str) -> bytes:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]+", value) is None:
        raise ProofError(f"invalid_{field}")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ProofError(f"invalid_{field}") from exc
    if len(decoded) != size:
        raise ProofError(f"invalid_{field}")
    return decoded


def verify_participation_report(
    signed_report: Any,
    *,
    expected_network: str | None = None,
    now: datetime | None = None,
) -> ProofVerification:
    report_id = ""
    campaign_id = ""
    try:
        if type(signed_report) is not dict or set(signed_report) != {
            "report",
            "signature",
        }:
            raise ProofError("invalid_signed_participation_report")
        report = validate_participation_report(signed_report["report"])
        campaign_id = report["campaign_id"]
        message = canonical_participation_bytes(report)
        report_id = participation_report_id(report)
        signature = signed_report["signature"]
        if type(signature) is not dict or set(signature) != _SIGNATURE_FIELDS:
            raise ProofError("invalid_signature_envelope")
        if signature["algorithm"] != SIGNATURE_ALGORITHM:
            raise ProofError("unsupported_signature_algorithm")
        address = signature["signing_address"]
        if type(address) is not str or _ADDRESS_RE.fullmatch(address) is None:
            raise ProofError("invalid_signing_address")
        expected_prefix = "xch1" if report["network"] == "mainnet" else "txch1"
        if not address.startswith(expected_prefix):
            raise ProofError("signing_address_network_mismatch")
        if expected_network is not None and report["network"] != expected_network:
            raise ProofError("participation_network_mismatch")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        _expiry_text, expiry = _canonical_timestamp(report["expires_at"], "expires_at")
        if current > expiry:
            raise ProofError("participation_report_expired")
        digest = hashlib.sha256(message).hexdigest()
        if signature["message_digest"] != digest:
            raise ProofError("message_digest_mismatch")
        public_key_text = signature["public_key"]
        public_key = G1Element.from_bytes(
            _signature_bytes(public_key_text, 48, "public_key")
        )
        bls_signature = G2Element.from_bytes(
            _signature_bytes(signature["signature"], 96, "signature")
        )
        if not AugSchemeMPL.verify(
            public_key, sage_message_tree_hash(message), bls_signature
        ):
            raise ProofError("signature_invalid")
        return ProofVerification(
            status="VERIFIED",
            report_id=report_id,
            campaign_id=campaign_id,
            reason_code=None,
            signing_address=address,
            public_key=public_key_text,
        )
    except (ProofError, ValueError) as exc:
        code = exc.code if isinstance(exc, ProofError) else "signature_invalid"
        return ProofVerification(
            status="INVALID",
            report_id=report_id,
            campaign_id=campaign_id,
            reason_code=code,
            signing_address=None,
            public_key=None,
        )


def build_directory_record(
    signed_manifest: dict[str, Any], *, asset_verification_status: str
) -> dict[str, Any]:
    verification = verify_campaign_manifest(signed_manifest)
    if verification.status != "VERIFIED":
        raise ProofError("directory_manifest_signature_invalid")
    if asset_verification_status not in {"VERIFIED", "UNVERIFIED_ASSET"}:
        raise ProofError("invalid_asset_verification_status")
    manifest = signed_manifest["manifest"]
    signature = signed_manifest["signature"]
    return {
        "schema": DIRECTORY_SCHEMA,
        "network": manifest["network"],
        "asset_id": manifest["asset_id"],
        "ticker": manifest["ticker"],
        "manifest_campaign_id": verification.campaign_id,
        "expires_at": manifest["expires_at"],
        "signing_address": verification.signing_address,
        "signer_public_key": verification.public_key,
        "signature": signature["signature"],
        "message_digest": signature["message_digest"],
        "asset_verification_status": asset_verification_status,
        "signed_manifest": deepcopy(signed_manifest),
    }


def verify_directory_record(
    record: Any,
    *,
    expected_network: str,
    now: datetime | None = None,
) -> DirectoryVerification:
    campaign_id = ""
    try:
        if type(record) is not dict or set(record) != _DIRECTORY_FIELDS:
            raise ProofError("invalid_directory_record")
        if record["schema"] != DIRECTORY_SCHEMA:
            raise ProofError("invalid_directory_schema")
        if record["network"] != expected_network:
            raise ProofError("directory_network_mismatch")
        expires_at, expiry = _canonical_timestamp(
            record["expires_at"], "directory_expires_at"
        )
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if current > expiry:
            raise ProofError("directory_record_expired")
        verification = verify_campaign_manifest(record["signed_manifest"])
        campaign_id = verification.campaign_id
        if verification.status != "VERIFIED":
            raise ProofError("directory_manifest_signature_invalid")
        manifest = record["signed_manifest"]["manifest"]
        signature = record["signed_manifest"]["signature"]
        expected = {
            "network": manifest["network"],
            "asset_id": manifest["asset_id"],
            "ticker": manifest["ticker"],
            "manifest_campaign_id": manifest_campaign_id(manifest),
            "expires_at": manifest["expires_at"],
            "signing_address": signature["signing_address"],
            "signer_public_key": signature["public_key"],
            "signature": signature["signature"],
            "message_digest": signature["message_digest"],
        }
        for field, value in expected.items():
            if record[field] != value:
                raise ProofError(f"directory_{field}_mismatch")
        if record["asset_verification_status"] not in {
            "VERIFIED",
            "UNVERIFIED_ASSET",
        }:
            raise ProofError("invalid_asset_verification_status")
        if expires_at != manifest["expires_at"]:
            raise ProofError("directory_expires_at_mismatch")
        return DirectoryVerification(
            status="VERIFIED",
            manifest_campaign_id=campaign_id,
            reason_code=None,
            signing_address=verification.signing_address,
            public_key=verification.public_key,
        )
    except (ProofError, ValueError) as exc:
        code = exc.code if isinstance(exc, ProofError) else "invalid_directory_record"
        return DirectoryVerification(
            status="INVALID",
            manifest_campaign_id=campaign_id,
            reason_code=code,
            signing_address=None,
            public_key=None,
        )


__all__ = [
    "DIRECTORY_SCHEMA",
    "PARTICIPATION_SCHEMA",
    "DirectoryVerification",
    "ProofError",
    "ProofVerification",
    "build_directory_record",
    "build_participation_report",
    "canonical_participation_bytes",
    "participation_report_id",
    "sign_participation_report",
    "validate_participation_report",
    "verify_directory_record",
    "verify_participation_report",
]
