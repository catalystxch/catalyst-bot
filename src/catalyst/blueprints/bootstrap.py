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
import secrets
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
from liquidity_side import bootstrap_side_enabled
from offer_book_policy import derive_bootstrap_plan
from partial_offer_capability import evaluate_partial_offer_capability
from providers.dexie import DexieOrderbookProvider
from providers.registry import ProviderRegistry
from providers.sage import SageAuthorityProvider
from providers.splash import SplashOfferProvider
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
    ticker_id = str(getattr(cfg, "CAT_TICKER_ID", "") or "").strip().upper()
    ticker = ticker_id.removesuffix("_XCH")
    if not ticker:
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
    mode = getattr(cfg, "LIQUIDITY_MODE", None)
    buy_enabled = bootstrap_side_enabled(cfg, "buy")
    sell_enabled = bootstrap_side_enabled(cfg, "sell")
    if not buy_enabled and not sell_enabled:
        raise BootstrapApiError("bootstrap_liquidity_side_disabled", 409)
    effective_xch_budget = fields["xch_budget"] if buy_enabled else Decimal("0")
    effective_cat_budget = fields["cat_budget"] if sell_enabled else Decimal("0")
    if effective_xch_budget == 0 and effective_cat_budget == 0:
        raise BootstrapApiError("bootstrap_enabled_side_unfunded")
    if (
        effective_xch_budget + fields["fee_budget_xch"] + fields["subsidy_budget_xch"]
        > balances["xch_available"]
    ):
        raise BootstrapApiError("bootstrap_xch_budget_exceeds_available")
    if effective_cat_budget > balances["cat_available"]:
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
        "liquidity_mode": mode,
        "effective_xch_budget": effective_xch_budget,
        "effective_cat_budget": effective_cat_budget,
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
        xch_budget=reviewed["effective_xch_budget"],
        cat_budget=reviewed["effective_cat_budget"],
        fee_budget_xch=reviewed["fee_budget_xch"],
        subsidy_budget_xch=reviewed["subsidy_budget_xch"],
        created_at=now,
        expires_at=now + timedelta(seconds=reviewed["expires_in_seconds"]),
    )
    decision = evaluate_bootstrap_campaign(campaign, BootstrapEvidence(), now=now)
    plan = derive_bootstrap_plan(campaign, decision, balances)
    # Coin Prep can prepare every replacement wave, so retain the full market
    # budget as principal even though the first offer deployment is smaller.
    fee_principal = sum(
        (row["amount_xch"] for row in plan["coin_prep"]["fee_coins"]), Decimal("0")
    )
    for asset, reserve_key, budget, principal in (
        ("xch", "XCH_RESERVE", campaign.xch_budget, fee_principal),
        ("cat", "CAT_RESERVE", campaign.cat_budget, Decimal("0")),
    ):
        try:
            reserve = Decimal(str(getattr(cfg, reserve_key)))
            if not reserve.is_finite() or reserve < 0:
                raise ValueError("invalid reserve")
        except (AttributeError, InvalidOperation, ValueError) as exc:
            raise BootstrapApiError(
                f"bootstrap_{asset}_reserve_unavailable", 409
            ) from exc
        if budget + reserve + principal > balances[f"{asset}_available"]:
            raise BootstrapApiError(f"bootstrap_{asset}_prep_principal_unfunded")
    return {
        "reviewed": reviewed,
        "preview_digest": _preview_digest(reviewed),
        "liquidity_mode": reviewed["liquidity_mode"],
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
    for prior in database.list_stopped_bootstrap_campaigns_for_identity(
        identity["asset_id"], identity["wallet_fingerprint"], identity["network"]
    ):
        if (
            prior["wallet_type"] == identity["wallet_type"]
            and prior["wallet_id"] == identity["wallet_id"]
            and _campaign_unresolved_creation_count(prior["campaign_id"])
        ):
            raise BootstrapApiError("bootstrap_prior_creation_unresolved", 409)
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


def _campaign_expiry_has_elapsed(campaign: dict[str, Any], now: datetime) -> bool:
    try:
        expires_at = datetime.fromisoformat(
            str(campaign.get("expires_at") or "").replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        # Show a damaged active authority as requiring operator attention.
        return True
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        return True
    return now.astimezone(timezone.utc) >= expires_at.astimezone(timezone.utc)


def _status_campaign_view(campaign: dict[str, Any] | None) -> dict[str, Any] | None:
    if campaign is None:
        return None
    view = dict(campaign)
    expired = _campaign_expiry_has_elapsed(campaign, _utcnow())
    trade_ids = _campaign_trade_ids(str(campaign.get("campaign_id") or ""))
    view["expired"] = expired
    view["cancel_required"] = expired
    view["cancel_reason"] = "bootstrap_expired" if expired else None
    view["manual_restart_required"] = expired
    view["open_offer_count"] = len(trade_ids)
    view["unresolved_creation_count"] = _campaign_unresolved_creation_count(
        str(campaign.get("campaign_id") or "")
    )
    view["active_authority_retained"] = (
        expired and str(campaign.get("status") or "") == "active"
    )
    return view


def _stopped_cancellation_status(identity: dict[str, Any]) -> dict[str, Any] | None:
    """Hydrate a durable campaign retry or unresolved cancel outcome."""

    for campaign in database.list_stopped_bootstrap_campaigns_for_identity(
        identity["asset_id"], identity["wallet_fingerprint"], identity["network"]
    ):
        if (
            campaign["wallet_type"] != identity["wallet_type"]
            or campaign["wallet_id"] != identity["wallet_id"]
        ):
            continue
        trade_ids = _campaign_trade_ids(campaign["campaign_id"])
        unresolved_count = _campaign_unresolved_creation_count(campaign["campaign_id"])
        if not trade_ids and not unresolved_count:
            continue
        if unresolved_count:
            return {
                "campaign_id": campaign["campaign_id"],
                "revision": campaign["revision"],
                "code": "bootstrap_cancel_outcome_unknown",
                "financial_action_started": None,
                "cancel_targets": len(trade_ids),
                "unresolved_creation_count": unresolved_count,
            }
        attempt = database.get_latest_bootstrap_cancel_attempt(campaign["campaign_id"])
        if attempt is None:
            return {
                "campaign_id": campaign["campaign_id"],
                "revision": campaign["revision"],
                "code": "bootstrap_cancel_outcome_unknown",
                "financial_action_started": None,
                "cancel_targets": len(trade_ids),
                "unresolved_creation_count": unresolved_count,
            }
        data = attempt["data"]
        code = data.get("code") or data.get("cancel_error")
        if not code:
            continue
        financial_action_started = data.get("financial_action_started")
        if attempt["event_type"] == "campaign_stopped":
            known_no_effect = {
                "FEE_APPROVAL_STALE",
                "FEE_APPROVAL_LEGACY_UNSCOPED",
                "FEE_APPROVAL_RECOVERY_ONLY",
                "FEE_APPROVAL_RECOVERY_ACTION_MISMATCH",
                "FEE_BUDGET_APPROVAL_REQUIRED",
                "FEE_BUDGET_EXCEEDED",
                "FEE_CAMPAIGN_BUDGET_EXCEEDED",
                "FEE_PREP_FUNDING_INSUFFICIENT",
                "BOOTSTRAP_CANCEL_MANAGER_UNAVAILABLE",
            }
            financial_action_started = (
                False if str(code).upper() in known_no_effect else None
            )
        return {
            "campaign_id": campaign["campaign_id"],
            "revision": campaign["revision"],
            "code": code,
            "financial_action_started": financial_action_started,
            "cancel_targets": len(trade_ids),
            "unresolved_creation_count": unresolved_count,
        }
    return None


@bp.get("/api/bootstrap/status")
def api_bootstrap_status():
    try:
        identity = _read_bootstrap_identity()
        active = database.get_active_bootstrap_campaign(
            identity["asset_id"],
            identity["wallet_fingerprint"],
            identity["network"],
        )
        campaign_view = _status_campaign_view(active)
        stopped_cancellation = _stopped_cancellation_status(identity)
        return jsonify(
            _json_safe(
                {
                    "success": True,
                    "identity": identity,
                    "active": active is not None,
                    "campaign": campaign_view,
                    "stopped_cancellation": stopped_cancellation,
                    "needs_attention": bool(
                        stopped_cancellation is not None
                        or (
                            campaign_view is not None
                            and (
                                campaign_view["expired"]
                                or campaign_view["unresolved_creation_count"]
                            )
                        )
                    ),
                }
            )
        )
    except BootstrapApiError as exc:
        # Status is a read-only hydration endpoint called before startup has
        # necessarily selected a Sage wallet and CAT.  Report that temporary
        # absence in-band so a normal first load does not emit an HTTP 409 or
        # overwrite any last-known durable campaign shown by the frontend.
        return jsonify(
            {
                "success": False,
                "active": None,
                "campaign": None,
                "identity": None,
                "code": exc.code,
                "error": exc.code,
            }
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
                    "liquidity_mode": preview["liquidity_mode"],
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
        created = _create_reviewed_campaign(_request_body(), _read_bootstrap_identity())
        return jsonify(
            _json_safe(
                {
                    "success": True,
                    "campaign_id": created["campaign_id"],
                    "liquidity_mode": created["liquidity_mode"],
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


def _campaign_unresolved_creation_count(campaign_id: str) -> int:
    """Count campaign intents whose wallet offer identity is not yet known."""

    prefix = f"bootstrap:{campaign_id}:revision:"
    return sum(
        1
        for intent in database.get_offer_intents_for_registry()
        if type(intent) is dict
        and str(intent.get("purpose") or "").startswith(prefix)
        and str(intent.get("lifecycle_state") or "").lower()
        in _NONTERMINAL_INTENT_STATES
        and not str(intent.get("sage_trade_id") or "").strip()
    )


def _campaign_cancel_manager():
    owner = current_app.config.get("_CATALYST_API_SERVER_MODULE")
    server = owner or sys.modules.get("api_server")
    manager = getattr(getattr(server, "bot", None), "offer_manager", None)
    if manager is None or not callable(getattr(manager, "cancel_offers", None)):
        raise BootstrapApiError("bootstrap_cancel_manager_unavailable", 409)
    return manager


def _await_campaign_creation_quiescence() -> None:
    owner = current_app.config.get("_CATALYST_API_SERVER_MODULE")
    server = owner or sys.modules.get("api_server")
    manager = getattr(getattr(server, "bot", None), "offer_manager", None)
    if manager is None:
        return
    wait = getattr(manager, "wait_for_offer_creation_quiescence", None)
    if not callable(wait):
        raise BootstrapApiError("bootstrap_creation_fence_unavailable", 503)
    wait()


def _cancel_campaign_offers(
    trade_ids: list[str], *, fee_approval_id: str | None = None
) -> dict[str, Any]:
    if not trade_ids:
        return {}
    manager = _campaign_cancel_manager()
    cancel_options = {
        "reason": "bootstrap_manual_stop",
        "force_storm": True,
    }
    if fee_approval_id is not None:
        cancel_options["fee_approval_id"] = fee_approval_id
    result = manager.cancel_offers(trade_ids, **cancel_options)
    if type(result) is not dict:
        raise BootstrapApiError("bootstrap_cancel_result_invalid", 500)
    return result


def _record_campaign_cancel_attempt(
    campaign_id: str,
    *,
    revision: int,
    cancel_targets: int,
    code: str | None,
    financial_action_started: bool | None,
) -> bool:
    try:
        database.append_bootstrap_campaign_event(
            {
                "campaign_id": campaign_id,
                "event_type": "campaign_cancel_attempt",
                "occurred_at": _utcnow(),
                "data": {
                    "attempt_nonce": secrets.token_hex(16),
                    "campaign_revision": revision,
                    "cancel_targets": cancel_targets,
                    "code": code,
                    "financial_action_started": financial_action_started,
                },
            }
        )
        return True
    except Exception:
        slog(
            "BOOTSTRAP",
            "Campaign cancellation attempt could not be recorded",
            {"campaign_id": campaign_id},
            level="error",
        )
        return False


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
                campaign["wallet_fingerprint"] != identity["wallet_fingerprint"],
                campaign["wallet_id"] != identity["wallet_id"],
                campaign["asset_id"] != identity["asset_id"],
            )
        ):
            raise BootstrapApiError("bootstrap_identity_mismatch", 409)
        revision = body.get("revision")
        if type(revision) is not int or revision != campaign["revision"]:
            raise BootstrapApiError("bootstrap_revision_stale", 409)
        observed_count = body.get("observed_open_offer_count")
        if "observed_open_offer_count" in body and (
            type(observed_count) is not int or observed_count < 0
        ):
            raise BootstrapApiError("invalid_observed_open_offer_count")
        fee_approval_id = body.get("fee_approval_id")
        if fee_approval_id is not None and (
            type(fee_approval_id) is not str
            or _ASSET_ID_RE.fullmatch(fee_approval_id) is None
        ):
            raise BootstrapApiError("invalid_fee_approval", 400)
        stopped_at = _utcnow()
        was_active = campaign.get("status") == "active"
        # Disable creation before any cancellation attempt. The cancellation
        # fee runtime explicitly accepts the frozen prior campaign recipe for a
        # stopped campaign, so a stale or insufficient approval can now enter a
        # bounded renewal flow without leaving creation authority live.
        if not database.stop_bootstrap_campaign(campaign_id, "manual", stopped_at):
            raise BootstrapApiError("bootstrap_stop_failed", 409)
        stopped_campaign = database.get_bootstrap_campaign(campaign_id)
        if type(stopped_campaign) is not dict:
            raise BootstrapApiError("bootstrap_stop_failed", 409)
        trade_ids: list[str] = []
        try:
            # A creation can pass its final campaign check immediately before
            # this HTTP request stops the campaign. Wait for that serialized
            # wallet call and its journal result before selecting cancel targets.
            _await_campaign_creation_quiescence()
            trade_ids = _campaign_trade_ids(campaign_id)
            if _campaign_unresolved_creation_count(campaign_id):
                raise BootstrapApiError("bootstrap_cancel_outcome_unknown", 503)
            if (
                trade_ids
                and observed_count is not None
                and observed_count != len(trade_ids)
            ):
                raise BootstrapApiError("bootstrap_stop_targets_changed", 409)
            if trade_ids and not _record_campaign_cancel_attempt(
                campaign_id,
                revision=stopped_campaign["revision"],
                cancel_targets=len(trade_ids),
                code="bootstrap_cancel_attempt_started",
                financial_action_started=None,
            ):
                raise BootstrapApiError("bootstrap_cancel_journal_unavailable", 503)
            cancel_results = (
                _cancel_campaign_offers(trade_ids)
                if fee_approval_id is None
                else _cancel_campaign_offers(trade_ids, fee_approval_id=fee_approval_id)
            )
            safe_cancel_results = _json_safe(cancel_results)
            json.dumps(safe_cancel_results)
            submitted_or_confirmed = {
                "CANCEL_CONFIRMED",
                "CANCEL_SUBMITTED_UNCONFIRMED",
            }
            if trade_ids and (
                set(safe_cancel_results) != set(trade_ids)
                or any(
                    type(safe_cancel_results[trade_id]) is not dict
                    or safe_cancel_results[trade_id].get("outcome")
                    not in submitted_or_confirmed
                    for trade_id in trade_ids
                )
            ):
                raise BootstrapApiError("bootstrap_cancel_result_unresolved", 503)
        except Exception as exc:
            no_effect_refusals = {
                "FEE_APPROVAL_STALE",
                "FEE_APPROVAL_LEGACY_UNSCOPED",
                "FEE_APPROVAL_RECOVERY_ONLY",
                "FEE_APPROVAL_RECOVERY_ACTION_MISMATCH",
                "FEE_BUDGET_APPROVAL_REQUIRED",
                "FEE_BUDGET_EXCEEDED",
                "FEE_CAMPAIGN_BUDGET_EXCEEDED",
                "FEE_PREP_FUNDING_INSUFFICIENT",
                "BOOTSTRAP_CANCEL_MANAGER_UNAVAILABLE",
                "BOOTSTRAP_CANCEL_JOURNAL_UNAVAILABLE",
                "BOOTSTRAP_STOP_TARGETS_CHANGED",
            }
            # The exception message may contain internals; return only fixed
            # public codes selected by equality with this allowlist.
            known_no_effect_code = (
                next(
                    (
                        code
                        for code in no_effect_refusals
                        if str(exc).strip().upper() == code
                    ),
                    None,
                )
                if isinstance(exc, (ValueError, BootstrapApiError))
                else None
            )
            if known_no_effect_code is not None:
                reason = (
                    known_no_effect_code.lower()
                    if known_no_effect_code.startswith("BOOTSTRAP_")
                    else known_no_effect_code
                )
                financial_action_started = False
                status = 409
            else:
                reason = "bootstrap_cancel_outcome_unknown"
                financial_action_started = None
                status = 503
                slog(
                    "BOOTSTRAP",
                    "Campaign stopped but cancellation outcome is uncertain",
                    {"error_type": type(exc).__name__},
                    level="error",
                )
            if was_active:
                try:
                    database.append_bootstrap_campaign_event(
                        {
                            "campaign_id": campaign_id,
                            "event_type": "campaign_stopped",
                            "occurred_at": stopped_at,
                            "data": {
                                "reason": "manual",
                                "cancel_targets": trade_ids,
                                "cancel_result_count": 0,
                                "cancel_error": reason,
                            },
                        }
                    )
                except Exception:
                    slog(
                        "BOOTSTRAP",
                        "Campaign stop event recording failed after cancellation error",
                        level="error",
                    )
            _record_campaign_cancel_attempt(
                campaign_id,
                revision=stopped_campaign["revision"],
                cancel_targets=len(trade_ids),
                code=reason,
                financial_action_started=financial_action_started,
            )
            return (
                jsonify(
                    {
                        "success": False,
                        "code": reason,
                        "error": reason,
                        "stopped": True,
                        "campaign_id": campaign_id,
                        "campaign_revision": stopped_campaign["revision"],
                        "cancel_targets": len(trade_ids),
                        "financial_action_started": financial_action_started,
                    }
                ),
                status,
            )
        if was_active:
            try:
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
            except Exception:
                slog(
                    "BOOTSTRAP",
                    "Campaign stop event recording failed after cancellation response",
                    level="error",
                )
        recorded = not trade_ids or _record_campaign_cancel_attempt(
            campaign_id,
            revision=stopped_campaign["revision"],
            cancel_targets=len(trade_ids),
            code=None,
            financial_action_started=True,
        )
        if not recorded:
            return (
                jsonify(
                    {
                        "success": False,
                        "code": "bootstrap_cancel_outcome_unknown",
                        "error": "bootstrap_cancel_outcome_unknown",
                        "stopped": True,
                        "campaign_id": campaign_id,
                        "campaign_revision": stopped_campaign["revision"],
                        "cancel_targets": len(trade_ids),
                        "financial_action_started": None,
                    }
                ),
                503,
            )
        return jsonify(
            {
                "success": True,
                "campaign_id": campaign_id,
                "stopped": True,
                "cancel_targets": len(trade_ids),
                "cancel_results": safe_cancel_results,
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
    def unavailable(*_args, **_kwargs):
        raise AssertionError("partial capability detection must not invoke adapters")

    registry = ProviderRegistry()
    registry.register(SageAuthorityProvider(None))
    registry.register(
        DexieOrderbookProvider(
            fetch_book=unavailable,
            fetch_settled_trades=unavailable,
            fetch_metadata=unavailable,
        )
    )
    registry.register(
        SplashOfferProvider(fetch_offers=unavailable, get_health=unavailable)
    )
    decision = evaluate_partial_offer_capability(registry)
    return jsonify(
        {
            "success": True,
            "enabled": decision.enabled,
            "reason_code": (
                None if decision.enabled else "PARTIAL_OFFERS_CAPABILITY_NOT_PROVEN"
            ),
            "reason_codes": list(decision.reason_codes),
            "providers": list(decision.providers),
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
