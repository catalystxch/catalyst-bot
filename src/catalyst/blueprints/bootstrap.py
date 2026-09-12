"""Market Bootstrap campaign API.

The HTTP surface is intentionally split into pure review operations and
explicit mutations.  A preview never persists authority.  Start/renew bind
the exact current Sage identity and asset to the reviewed inputs, persist the
campaign before any coin preparation, and leave wallet effects to the normal
coin-prep/start workflow.  Imported public manifests remain descriptive only.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
import sys
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from bootstrap_campaign import (
    BootstrapCampaign,
    BootstrapEvidence,
    evaluate_bootstrap_campaign,
)
from bootstrap_manifest import MANIFEST_SCHEMA, ManifestError, safe_import_manifest
from bootstrap_proof import build_participation_report, participation_report_id
from config import cfg
import database
from offer_book_policy import derive_bootstrap_plan
from super_log import slog


bp = Blueprint("bootstrap", __name__)

_ASSET_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,15}$")
_MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
_NONTERMINAL_INTENT_STATES = frozenset(
    {
        "prepared",
        "submitted_unconfirmed",
        "creation_unknown",
        "created",
        "visible",
        "unknown",
        "conflicted",
    }
)


class BootstrapApiError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_decimal(value: Any, field: str, *, allow_zero: bool) -> Decimal:
    if type(value) is not str or value.strip() != value or not value:
        raise BootstrapApiError(f"invalid_{field}")
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BootstrapApiError(f"invalid_{field}") from exc
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        raise BootstrapApiError(f"invalid_{field}")
    canonical = format(number, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical != value:
        raise BootstrapApiError(f"invalid_{field}")
    return number


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(nested) for nested in value]
    return value


def _error(exc: Exception):
    if isinstance(exc, BootstrapApiError):
        return (
            jsonify({"success": False, "code": exc.code, "error": exc.code}),
            exc.status,
        )
    if isinstance(exc, ManifestError):
        return (
            jsonify({"success": False, "code": exc.code, "error": exc.code}),
            400,
        )
    slog(
        "BOOTSTRAP",
        "Bootstrap API operation failed",
        {"error_type": type(exc).__name__},
        level="error",
    )
    return (
        jsonify(
            {
                "success": False,
                "code": "bootstrap_internal_error",
                "error": "bootstrap_internal_error",
            }
        ),
        500,
    )


def _network_name(value: Any) -> str:
    network = str(value or "").strip().lower()
    if network == "mainnet":
        return "mainnet"
    if network.startswith("testnet"):
        return "testnet"
    raise BootstrapApiError("invalid_wallet_network", 409)


def _read_bootstrap_identity() -> dict[str, Any]:
    """Read a fresh, signing-capable Sage identity and exact active CAT."""

    from wallet import get_wallet_identity

    snapshot = get_wallet_identity()
    if type(snapshot) is not dict or snapshot.get("success") is not True:
        raise BootstrapApiError("wallet_identity_unavailable", 409)
    if str(snapshot.get("backend") or "").strip().lower() != "sage":
        raise BootstrapApiError("sage_wallet_required", 409)
    if snapshot.get("has_secrets") is not True:
        raise BootstrapApiError("sage_signing_key_required", 409)
    fingerprint = snapshot.get("fingerprint")
    if type(fingerprint) is not int or fingerprint <= 0:
        raise BootstrapApiError("invalid_wallet_fingerprint", 409)
    asset_id = str(getattr(cfg, "CAT_ASSET_ID", "") or "").strip().lower()
    if _ASSET_ID_RE.fullmatch(asset_id) is None:
        raise BootstrapApiError("bootstrap_asset_not_selected", 409)
    wallet_id = getattr(cfg, "CAT_WALLET_ID", 0)
    if type(wallet_id) is not int or wallet_id <= 0:
        raise BootstrapApiError("invalid_cat_wallet_id", 409)
    ticker = str(getattr(cfg, "CAT_NAME", "CAT") or "CAT").strip().upper()
    if _TICKER_RE.fullmatch(ticker) is None:
        ticker = "CAT"
    return {
        "network": _network_name(snapshot.get("network_id")),
        "wallet_type": "sage",
        "wallet_fingerprint": fingerprint,
        "wallet_id": wallet_id,
        "asset_id": asset_id,
        "ticker": ticker,
        "has_secrets": True,
    }


def _request_body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    if type(body) is not dict:
        raise BootstrapApiError("invalid_bootstrap_request")
    return body


def _campaign_inputs(
    body: dict[str, Any], identity: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    asset_id = str(body.get("asset_id") or "").strip().lower()
    if _ASSET_ID_RE.fullmatch(asset_id) is None:
        raise BootstrapApiError("invalid_asset_id")
    if asset_id != identity["asset_id"]:
        raise BootstrapApiError("bootstrap_asset_identity_changed", 409)
    ticker = str(body.get("ticker") or "").strip().upper()
    if _TICKER_RE.fullmatch(ticker) is None:
        raise BootstrapApiError("invalid_ticker")
    duration = body.get("expires_in_seconds")
    if type(duration) is not int or not 1 <= duration <= _MAX_DURATION_SECONDS:
        raise BootstrapApiError("invalid_bootstrap_expiry")

    fields = {
        "anchor_price": _canonical_decimal(
            body.get("anchor_price"), "anchor_price", allow_zero=False
        ),
        "xch_budget": _canonical_decimal(
            body.get("xch_budget"), "xch_budget", allow_zero=True
        ),
        "cat_budget": _canonical_decimal(
            body.get("cat_budget"), "cat_budget", allow_zero=True
        ),
        "fee_budget_xch": _canonical_decimal(
            body.get("fee_budget_xch"), "fee_budget_xch", allow_zero=True
        ),
        "subsidy_budget_xch": _canonical_decimal(
            body.get("subsidy_budget_xch"),
            "subsidy_budget_xch",
            allow_zero=True,
        ),
    }
    balances_raw = body.get("balances")
    if type(balances_raw) is not dict:
        raise BootstrapApiError("invalid_bootstrap_balances")
    balances = {
        key: _canonical_decimal(
            balances_raw.get(key),
            key,
            allow_zero=True,
        )
        for key in (
            "xch_available",
            "cat_available",
            "fee_spent_xch",
            "subsidy_spent_xch",
            "network_fee_xch",
            "minimum_profit_xch",
            "fee_coin_size_xch",
        )
    }
    expected_requotes = balances_raw.get("expected_cancel_requotes")
    if type(expected_requotes) is not int or expected_requotes < 0:
        raise BootstrapApiError("invalid_expected_cancel_requotes")
    balances["expected_cancel_requotes"] = expected_requotes
    for optional in ("trusted_bid", "trusted_ask"):
        if balances_raw.get(optional) not in (None, ""):
            balances[optional] = _canonical_decimal(
                balances_raw[optional], optional, allow_zero=False
            )
    if (
        fields["xch_budget"]
        + fields["fee_budget_xch"]
        + fields["subsidy_budget_xch"]
        > balances["xch_available"]
    ):
        raise BootstrapApiError("bootstrap_xch_budget_exceeds_available")
    if fields["cat_budget"] > balances["cat_available"]:
        raise BootstrapApiError("bootstrap_cat_budget_exceeds_available")

    reviewed = {
        "identity": {
            "network": identity["network"],
            "wallet_type": identity["wallet_type"],
            "wallet_fingerprint": identity["wallet_fingerprint"],
            "wallet_id": identity["wallet_id"],
            "asset_id": identity["asset_id"],
        },
        "ticker": ticker,
        "expires_in_seconds": duration,
        **fields,
        "balances": balances,
    }
    return reviewed, balances


def _preview_digest(reviewed: dict[str, Any]) -> str:
    canonical = json.dumps(
        _json_safe(reviewed),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(b"catalyst-bootstrap-preview-v1\0" + canonical).hexdigest()


def _derive_preview(body: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    reviewed, balances = _campaign_inputs(body, identity)
    now = _utcnow()
    campaign = BootstrapCampaign(
        network=identity["network"],
        wallet_type=identity["wallet_type"],
        wallet_fingerprint=identity["wallet_fingerprint"],
        wallet_id=identity["wallet_id"],
        asset_id=identity["asset_id"],
        anchor_price=reviewed["anchor_price"],
        xch_budget=reviewed["xch_budget"],
        cat_budget=reviewed["cat_budget"],
        fee_budget_xch=reviewed["fee_budget_xch"],
        subsidy_budget_xch=reviewed["subsidy_budget_xch"],
        created_at=now,
        expires_at=now + timedelta(seconds=reviewed["expires_in_seconds"]),
    )
    decision = evaluate_bootstrap_campaign(
        campaign, BootstrapEvidence(), now=now
    )
    plan = derive_bootstrap_plan(campaign, decision, balances)
    return {
        "reviewed": reviewed,
        "preview_digest": _preview_digest(reviewed),
        "campaign_object": campaign,
        "campaign": campaign.to_record(),
        "plan": plan,
    }


def _require_review_confirmation(body: dict[str, Any], preview: dict[str, Any]) -> None:
    if body.get("exact_asset_warning_accepted") is not True:
        raise BootstrapApiError("exact_asset_confirmation_required")
    supplied_digest = body.get("preview_digest")
    if type(supplied_digest) is not str or supplied_digest != preview["preview_digest"]:
        raise BootstrapApiError("bootstrap_preview_stale", 409)


def _create_reviewed_campaign(
    body: dict[str, Any], identity: dict[str, Any]
) -> dict[str, Any]:
    preview = _derive_preview(body, identity)
    _require_review_confirmation(body, preview)
    campaign_id = database.create_bootstrap_campaign(
        preview["campaign_object"].to_record()
    )
    database.append_bootstrap_campaign_event(
        {
            "campaign_id": campaign_id,
            "event_type": "campaign_started",
            "occurred_at": _utcnow(),
            "data": {
                "preview_digest": preview["preview_digest"],
                "ticker": preview["reviewed"]["ticker"],
                "financial_action_started": False,
            },
        }
    )
    return {**preview, "campaign_id": campaign_id}


@bp.get("/api/bootstrap/status")
def api_bootstrap_status():
    try:
        identity = _read_bootstrap_identity()
        active = database.get_active_bootstrap_campaign(
            identity["asset_id"],
            identity["wallet_fingerprint"],
            identity["network"],
        )
        return jsonify(
            _json_safe(
                {
                    "success": True,
                    "identity": identity,
                    "active": active is not None,
                    "campaign": active,
                }
            )
        )
    except Exception as exc:
        return _error(exc)


@bp.post("/api/bootstrap/preview")
def api_bootstrap_preview():
    try:
        preview = _derive_preview(_request_body(), _read_bootstrap_identity())
        return jsonify(
            _json_safe(
                {
                    "success": True,
                    "preview_digest": preview["preview_digest"],
                    "campaign": preview["campaign"],
                    "plan": preview["plan"],
                    "financial_action_started": False,
                }
            )
        )
    except Exception as exc:
        return _error(exc)


@bp.post("/api/bootstrap/start")
def api_bootstrap_start():
    try:
        created = _create_reviewed_campaign(
            _request_body(), _read_bootstrap_identity()
        )
        return jsonify(
            _json_safe(
                {
                    "success": True,
                    "campaign_id": created["campaign_id"],
                    "campaign": created["campaign"],
                    "plan": created["plan"],
                    "coin_prep_required": True,
                    "financial_action_started": False,
                }
            )
        )
    except Exception as exc:
        return _error(exc)


def _campaign_trade_ids(campaign_id: str) -> list[str]:
    prefix = f"bootstrap:{campaign_id}:revision:"
    trade_ids: set[str] = set()
    for intent in database.get_offer_intents_for_registry():
        if type(intent) is not dict:
            continue
        if not str(intent.get("purpose") or "").startswith(prefix):
            continue
        if str(intent.get("lifecycle_state") or "").lower() not in (
            _NONTERMINAL_INTENT_STATES
        ):
            continue
        trade_id = str(intent.get("sage_trade_id") or "").strip()
        if trade_id:
            trade_ids.add(trade_id)
    return sorted(trade_ids)


def _cancel_campaign_offers(trade_ids: list[str]) -> dict[str, Any]:
    if not trade_ids:
        return {}
    owner = current_app.config.get("_CATALYST_API_SERVER_MODULE")
    server = owner or sys.modules.get("api_server")
    manager = getattr(getattr(server, "bot", None), "offer_manager", None)
    if manager is None:
        raise BootstrapApiError("bootstrap_cancel_manager_unavailable", 409)
    result = manager.cancel_offers(
        trade_ids,
        reason="bootstrap_manual_stop",
        force_storm=True,
    )
    if type(result) is not dict:
        raise BootstrapApiError("bootstrap_cancel_result_invalid", 500)
    return result


@bp.post("/api/bootstrap/stop")
def api_bootstrap_stop():
    try:
        body = _request_body()
        campaign_id = str(body.get("campaign_id") or "").strip().lower()
        if _ASSET_ID_RE.fullmatch(campaign_id) is None:
            raise BootstrapApiError("invalid_campaign_id")
        campaign = database.get_bootstrap_campaign(campaign_id)
        if campaign is None:
            raise BootstrapApiError("bootstrap_campaign_not_found", 404)
        identity = _read_bootstrap_identity()
        if any(
            (
                campaign["network"] != identity["network"],
                campaign["wallet_fingerprint"]
                != identity["wallet_fingerprint"],
                campaign["wallet_id"] != identity["wallet_id"],
                campaign["asset_id"] != identity["asset_id"],
            )
        ):
            raise BootstrapApiError("bootstrap_identity_mismatch", 409)
        revision = body.get("revision")
        if type(revision) is not int or revision != campaign["revision"]:
            raise BootstrapApiError("bootstrap_revision_stale", 409)
        trade_ids = _campaign_trade_ids(campaign_id)
        stopped_at = _utcnow()
        if not database.stop_bootstrap_campaign(campaign_id, "manual", stopped_at):
            raise BootstrapApiError("bootstrap_stop_failed", 409)
        cancel_results = _cancel_campaign_offers(trade_ids)
        database.append_bootstrap_campaign_event(
            {
                "campaign_id": campaign_id,
                "event_type": "campaign_stopped",
                "occurred_at": stopped_at,
                "data": {
                    "reason": "manual",
                    "cancel_targets": trade_ids,
                    "cancel_result_count": len(cancel_results),
                },
            }
        )
        return jsonify(
            {
                "success": True,
                "campaign_id": campaign_id,
                "stopped": True,
                "cancel_targets": len(trade_ids),
                "cancel_results": _json_safe(cancel_results),
            }
        )
    except Exception as exc:
        return _error(exc)


@bp.post("/api/bootstrap/renew")
def api_bootstrap_renew():
    try:
        body = _request_body()
        prior_id = str(body.get("prior_campaign_id") or "").strip().lower()
        if _ASSET_ID_RE.fullmatch(prior_id) is None:
            raise BootstrapApiError("invalid_prior_campaign_id")
        prior = database.get_bootstrap_campaign(prior_id)
        if prior is None:
            raise BootstrapApiError("bootstrap_campaign_not_found", 404)
        if prior.get("status") != "stopped":
            raise BootstrapApiError("bootstrap_renew_requires_stopped_campaign", 409)
        created = _create_reviewed_campaign(body, _read_bootstrap_identity())
        return jsonify(
            _json_safe(
                {
                    "success": True,
                    "prior_campaign_id": prior_id,
                    "campaign_id": created["campaign_id"],
                    "campaign": created["campaign"],
                    "plan": created["plan"],
                    "coin_prep_required": True,
                    "financial_action_started": False,
                }
            )
        )
    except Exception as exc:
        return _error(exc)


def _manifest_for_campaign(campaign: dict[str, Any], ticker: str) -> dict[str, Any]:
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "network": campaign["network"],
        "asset_id": campaign["asset_id"],
        "ticker": ticker,
        "anchor_price": campaign["anchor_price"],
        "minimum_price": campaign["minimum_price"],
        "maximum_price": campaign["maximum_price"],
        "created_at": campaign["created_at"],
        "expires_at": campaign["expires_at"],
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
    from bootstrap_manifest import validate_manifest

    return validate_manifest(manifest)


@bp.post("/api/bootstrap/manifest/export")
def api_bootstrap_manifest_export():
    try:
        body = _request_body()
        campaign_id = str(body.get("campaign_id") or "").strip().lower()
        if _ASSET_ID_RE.fullmatch(campaign_id) is None:
            raise BootstrapApiError("invalid_campaign_id")
        ticker = str(body.get("ticker") or "").strip().upper()
        if _TICKER_RE.fullmatch(ticker) is None:
            raise BootstrapApiError("invalid_ticker")
        campaign = database.get_bootstrap_campaign(campaign_id)
        if campaign is None:
            raise BootstrapApiError("bootstrap_campaign_not_found", 404)
        identity = _read_bootstrap_identity()
        if (
            campaign["network"] != identity["network"]
            or campaign["wallet_fingerprint"] != identity["wallet_fingerprint"]
            or campaign["asset_id"] != identity["asset_id"]
        ):
            raise BootstrapApiError("bootstrap_identity_mismatch", 409)
        return jsonify(
            {
                "success": True,
                "manifest": _manifest_for_campaign(campaign, ticker),
                "financial_authority": False,
                "walletconnect_signing_available": bool(
                    str(getattr(cfg, "WALLETCONNECT_PROJECT_ID", "") or "").strip()
                ),
            }
        )
    except Exception as exc:
        return _error(exc)


@bp.post("/api/bootstrap/manifest/import")
def api_bootstrap_manifest_import():
    try:
        body = _request_body()
        if set(body) != {"signed_manifest"}:
            raise BootstrapApiError("invalid_manifest_import_request")
        identity = _read_bootstrap_identity()
        imported = safe_import_manifest(
            body["signed_manifest"],
            identity["network"],
            known_asset_ids={identity["asset_id"]},
        )
        manifest = _json_safe(imported)
        return jsonify(
            {
                "success": True,
                "manifest": manifest,
                "requires_local_budget_acceptance": True,
                "can_start": False,
                "reason_code": "LOCAL_BUDGET_REVIEW_REQUIRED",
                "financial_authority": False,
            }
        )
    except Exception as exc:
        return _error(exc)


def _participation_observations(
    campaign_id: str,
    campaign: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Project append-only local samples without copying private fields."""

    created_at = datetime.fromisoformat(campaign["created_at"][:-1] + "+00:00")
    expires_at = datetime.fromisoformat(campaign["expires_at"][:-1] + "+00:00")
    if now <= created_at:
        raise BootstrapApiError("bootstrap_participation_period_empty", 409)
    if now >= expires_at:
        raise BootstrapApiError("bootstrap_campaign_expired", 409)
    samples: list[dict[str, Any]] = []
    for stored in database.list_bootstrap_participation(campaign_id):
        data = stored.get("data")
        if type(data) is not dict or data.get("kind") != "quality_sample":
            continue
        # This allow-list is the privacy boundary.  Do not merge ``data`` or
        # the surrounding database record into the export.
        samples.append(
            {
                "observation_id": stored["report_id"],
                "observed_at": stored["recorded_at"],
                "duration_seconds": data.get("duration_seconds"),
                "independent_depth_xch": data.get("independent_depth_xch"),
                "spread_bps": data.get("spread_bps"),
                "within_corridor": data.get("within_corridor"),
                "own": data.get("own"),
                "linked": data.get("linked"),
                "offer_ids": data.get("offer_ids"),
                "fill_ids": data.get("fill_ids"),
            }
        )
    return {
        "network": campaign["network"],
        "asset_id": campaign["asset_id"],
        "period_start": campaign["created_at"],
        "period_end": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "expires_at": campaign["expires_at"],
        "samples": samples,
    }


@bp.post("/api/bootstrap/participation/export")
def api_bootstrap_participation_export():
    try:
        body = _request_body()
        if set(body) != {"campaign_id"}:
            raise BootstrapApiError("invalid_participation_export_request")
        campaign_id = str(body.get("campaign_id") or "").strip().lower()
        if _ASSET_ID_RE.fullmatch(campaign_id) is None:
            raise BootstrapApiError("invalid_campaign_id")
        campaign = database.get_bootstrap_campaign(campaign_id)
        if campaign is None:
            raise BootstrapApiError("bootstrap_campaign_not_found", 404)
        identity = _read_bootstrap_identity()
        if any(
            (
                campaign["network"] != identity["network"],
                campaign["wallet_fingerprint"] != identity["wallet_fingerprint"],
                campaign["wallet_id"] != identity["wallet_id"],
                campaign["asset_id"] != identity["asset_id"],
            )
        ):
            raise BootstrapApiError("bootstrap_identity_mismatch", 409)
        report = build_participation_report(
            campaign_id,
            _participation_observations(campaign_id, campaign, _utcnow()),
        )
        return jsonify(
            {
                "success": True,
                "report": report,
                "report_id": participation_report_id(report),
                "financial_authority": False,
                "reward_amount": None,
                "walletconnect_signing_available": bool(
                    str(getattr(cfg, "WALLETCONNECT_PROJECT_ID", "") or "").strip()
                ),
            }
        )
    except Exception as exc:
        return _error(exc)


@bp.get("/api/bootstrap/capabilities/partial-offers")
@bp.get("/api/bootstrap/partial-capability")
def api_bootstrap_partial_offer_capability():
    return jsonify(
        {
            "success": True,
            "enabled": False,
            "reason_code": "PARTIAL_OFFERS_CAPABILITY_NOT_PROVEN",
            "policy": "disabled_until_capability_proven",
        }
    )


__all__ = [
    "bp",
    "api_bootstrap_manifest_export",
    "api_bootstrap_manifest_import",
    "api_bootstrap_partial_offer_capability",
    "api_bootstrap_participation_export",
    "api_bootstrap_preview",
    "api_bootstrap_renew",
    "api_bootstrap_start",
    "api_bootstrap_status",
    "api_bootstrap_stop",
]
