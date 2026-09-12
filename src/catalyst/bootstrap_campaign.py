"""Pure, immutable policy types for bounded CAT market Bootstrap campaigns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum


_ASSET_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ZERO = Decimal("0")
_INITIAL_DEPLOYMENT = Decimal("0.10")
_MINIMUM_CORRIDOR_FACTOR = Decimal("0.50")
_MAXIMUM_CORRIDOR_FACTOR = Decimal("2.00")
_MAXIMUM_CAMPAIGN_DURATION = timedelta(days=7)
_DISCOVERY_25_DEPLOYMENT = Decimal("0.25")
_DISCOVERY_50_DEPLOYMENT = Decimal("0.50")
_ESTABLISHED_DEPLOYMENT = Decimal("1.00")
_HOURLY_ANCHOR_LIMIT = Decimal("0.05")
_DAILY_ANCHOR_LIMIT = Decimal("0.20")
_LOSS_LIMIT = Decimal("0.05")
_FEE_CREATION_FRACTION = Decimal("0.80")
_FEE_CANCELLATION_FRACTION = Decimal("0.20")
_ADVERSE_FILL_COOLDOWN = timedelta(minutes=5)


class CampaignMode(str, Enum):
    FOLLOW = "follow"
    BOOTSTRAP = "bootstrap"


class CampaignStage(str, Enum):
    BOOTSTRAP = "bootstrap"
    DISCOVERY_25 = "discovery_25"
    DISCOVERY_50 = "discovery_50"
    ESTABLISHED = "established"
    UNSAFE = "unsafe"
    STOPPED = "stopped"


class CampaignSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class CampaignStopReason(str, Enum):
    EXPIRED = "expired"
    LOSS_LIMIT = "loss_limit"
    FEE_RESERVE = "fee_reserve"
    MANUAL = "manual"
    IDENTITY_MISMATCH = "identity_mismatch"
    UNSAFE = "unsafe"


def _require_decimal(
    value: object,
    label: str,
    *,
    allow_zero: bool,
) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{label} must be a Decimal")
    if not value.is_finite() or value < _ZERO or (not allow_zero and value == _ZERO):
        raise ValueError(f"{label} is invalid")
    return value


def _require_utc(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be a UTC datetime")
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _utc_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class BootstrapCampaign:
    network: str
    wallet_type: str
    wallet_fingerprint: int
    wallet_id: int
    asset_id: str
    anchor_price: Decimal
    xch_budget: Decimal
    cat_budget: Decimal
    fee_budget_xch: Decimal
    subsidy_budget_xch: Decimal
    created_at: datetime
    expires_at: datetime
    minimum_price: Decimal | None = None
    maximum_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.network not in {"mainnet", "testnet"}:
            raise ValueError("network must be mainnet or testnet")
        if self.wallet_type != "sage":
            raise ValueError("wallet type must be sage")
        if type(self.wallet_fingerprint) is not int or self.wallet_fingerprint <= 0:
            raise ValueError("wallet fingerprint must be a positive integer")
        if type(self.wallet_id) is not int or self.wallet_id <= 0:
            raise ValueError("wallet ID must be a positive integer")
        if type(self.asset_id) is not str or not _ASSET_ID_RE.fullmatch(self.asset_id):
            raise ValueError("asset ID must be exactly 64 hexadecimal characters")
        object.__setattr__(self, "asset_id", self.asset_id.lower())

        anchor = _require_decimal(self.anchor_price, "anchor", allow_zero=False)
        minimum = (
            anchor * _MINIMUM_CORRIDOR_FACTOR
            if self.minimum_price is None
            else _require_decimal(
                self.minimum_price,
                "minimum price",
                allow_zero=False,
            )
        )
        maximum = (
            anchor * _MAXIMUM_CORRIDOR_FACTOR
            if self.maximum_price is None
            else _require_decimal(
                self.maximum_price,
                "maximum price",
                allow_zero=False,
            )
        )
        if not minimum <= anchor <= maximum:
            raise ValueError("price corridor must contain the anchor")
        object.__setattr__(self, "minimum_price", minimum)
        object.__setattr__(self, "maximum_price", maximum)

        xch_budget = _require_decimal(
            self.xch_budget,
            "XCH budget",
            allow_zero=True,
        )
        cat_budget = _require_decimal(
            self.cat_budget,
            "CAT budget",
            allow_zero=True,
        )
        _require_decimal(self.fee_budget_xch, "fee budget", allow_zero=True)
        _require_decimal(
            self.subsidy_budget_xch,
            "subsidy budget",
            allow_zero=True,
        )
        if xch_budget == _ZERO and cat_budget == _ZERO:
            raise ValueError("campaign must have at least one funded side")

        created_at = _require_utc(self.created_at, "created_at")
        expires_at = _require_utc(self.expires_at, "expires_at")
        duration = expires_at - created_at
        if duration <= timedelta(0):
            raise ValueError("expires_at must be after created_at")
        if duration > _MAXIMUM_CAMPAIGN_DURATION:
            raise ValueError("campaign expiry cannot exceed seven days")

    @property
    def mode(self) -> CampaignMode:
        return CampaignMode.BOOTSTRAP

    @property
    def initial_deployment_fraction(self) -> Decimal:
        return _INITIAL_DEPLOYMENT

    @property
    def allowed_sides(self) -> frozenset[CampaignSide]:
        sides: set[CampaignSide] = set()
        if self.xch_budget > _ZERO:
            sides.add(CampaignSide.BUY)
        if self.cat_budget > _ZERO:
            sides.add(CampaignSide.SELL)
        return frozenset(sides)

    def to_record(self) -> dict[str, object]:
        """Return the exact canonical database authority fields."""

        return {
            "network": self.network,
            "wallet_type": self.wallet_type,
            "wallet_fingerprint": self.wallet_fingerprint,
            "wallet_id": self.wallet_id,
            "asset_id": self.asset_id,
            "anchor_price": _decimal_text(self.anchor_price),
            "minimum_price": _decimal_text(self.minimum_price),
            "maximum_price": _decimal_text(self.maximum_price),
            "xch_budget": _decimal_text(self.xch_budget),
            "cat_budget": _decimal_text(self.cat_budget),
            "fee_budget_xch": _decimal_text(self.fee_budget_xch),
            "subsidy_budget_xch": _decimal_text(self.subsidy_budget_xch),
            "created_at": _utc_text(self.created_at),
            "expires_at": _utc_text(self.expires_at),
        }


@dataclass(frozen=True, slots=True)
class BootstrapEvidence:
    confirmed_fills: int = 0
    settlement_clusters: int = 0
    independent_depth_sides: frozenset[CampaignSide] = frozenset()
    stable_since: datetime | None = None
    suspected_linked_activity: bool = False
    adverse_fill_times: tuple[tuple[CampaignSide, datetime], ...] = ()
    fee_spent_xch: Decimal = Decimal("0")
    realized_loss_xch: Decimal = Decimal("0")
    marked_inventory_loss_xch: Decimal = Decimal("0")
    current_anchor_price: Decimal | None = None
    proposed_anchor_price: Decimal | None = None
    anchor_price_one_hour_ago: Decimal | None = None
    anchor_price_one_day_ago: Decimal | None = None

    def __post_init__(self) -> None:
        if type(self.confirmed_fills) is not int or self.confirmed_fills < 0:
            raise ValueError("confirmed fills must be a nonnegative integer")
        if type(self.settlement_clusters) is not int or self.settlement_clusters < 0:
            raise ValueError("settlement clusters must be a nonnegative integer")
        if self.settlement_clusters > self.confirmed_fills:
            raise ValueError("settlement clusters cannot exceed confirmed fills")
        if type(self.independent_depth_sides) is not frozenset or any(
            type(side) is not CampaignSide for side in self.independent_depth_sides
        ):
            raise TypeError("independent depth must contain campaign side values")
        if self.stable_since is not None:
            _require_utc(self.stable_since, "stable_since")
        if type(self.suspected_linked_activity) is not bool:
            raise TypeError("suspected_linked_activity must be a bool")
        if type(self.adverse_fill_times) is not tuple:
            raise TypeError("adverse_fill_times must be a tuple")
        for side, occurred_at in self.adverse_fill_times:
            if type(side) is not CampaignSide:
                raise TypeError("adverse fill must contain a campaign side")
            _require_utc(occurred_at, "adverse fill time")

        _require_decimal(self.fee_spent_xch, "fee spent", allow_zero=True)
        _require_decimal(self.realized_loss_xch, "realized loss", allow_zero=True)
        _require_decimal(
            self.marked_inventory_loss_xch,
            "marked inventory loss",
            allow_zero=True,
        )
        for value, label in (
            (self.current_anchor_price, "current anchor"),
            (self.proposed_anchor_price, "proposed anchor"),
            (self.anchor_price_one_hour_ago, "hourly anchor"),
            (self.anchor_price_one_day_ago, "daily anchor"),
        ):
            if value is not None:
                _require_decimal(value, label, allow_zero=False)


@dataclass(frozen=True, slots=True)
class BootstrapDecision:
    authorized: bool
    stage: CampaignStage
    deployment_fraction: Decimal
    anchor_price: Decimal
    minimum_price: Decimal
    maximum_price: Decimal
    allowed_sides: frozenset[CampaignSide]
    cooldown_sides: frozenset[CampaignSide]
    stop_reason: CampaignStopReason | None
    reason_codes: tuple[str, ...]
    cancellation_required: bool
    manual_restart_required: bool
    cancellation_fee_reserve_xch: Decimal


def derive_anchor_from_valuation(
    *,
    circulating_supply: Decimal,
    implied_valuation_xch: Decimal,
) -> Decimal:
    """Return exact XCH-per-CAT from explicit supply and XCH valuation."""

    supply = _require_decimal(
        circulating_supply,
        "circulating supply",
        allow_zero=False,
    )
    valuation = _require_decimal(
        implied_valuation_xch,
        "implied valuation",
        allow_zero=False,
    )
    return valuation / supply


def evaluate_bootstrap_campaign(
    campaign: BootstrapCampaign,
    evidence: BootstrapEvidence,
    *,
    now: datetime,
) -> BootstrapDecision:
    """Return the initial bounded authorization for a valid campaign."""

    if type(campaign) is not BootstrapCampaign:
        raise TypeError("campaign must be a BootstrapCampaign")
    if type(evidence) is not BootstrapEvidence:
        raise TypeError("evidence must be BootstrapEvidence")
    now = _require_utc(now, "now")
    cancellation_fee_reserve = campaign.fee_budget_xch * _FEE_CANCELLATION_FRACTION

    def stopped(
        reason: CampaignStopReason,
        *,
        manual_restart_required: bool,
    ) -> BootstrapDecision:
        return BootstrapDecision(
            authorized=False,
            stage=CampaignStage.STOPPED,
            deployment_fraction=_ZERO,
            anchor_price=_bounded_anchor(campaign, evidence),
            minimum_price=campaign.minimum_price,
            maximum_price=campaign.maximum_price,
            allowed_sides=campaign.allowed_sides,
            cooldown_sides=frozenset(),
            stop_reason=reason,
            reason_codes=(reason.value,),
            cancellation_required=True,
            manual_restart_required=manual_restart_required,
            cancellation_fee_reserve_xch=cancellation_fee_reserve,
        )

    campaign_value = campaign.xch_budget + campaign.cat_budget * campaign.anchor_price
    total_loss = evidence.realized_loss_xch + evidence.marked_inventory_loss_xch
    if total_loss >= campaign_value * _LOSS_LIMIT:
        return stopped(CampaignStopReason.LOSS_LIMIT, manual_restart_required=True)
    if now >= campaign.expires_at:
        return stopped(CampaignStopReason.EXPIRED, manual_restart_required=True)
    fee_creation_limit = campaign.fee_budget_xch * _FEE_CREATION_FRACTION
    if evidence.fee_spent_xch >= fee_creation_limit:
        return stopped(CampaignStopReason.FEE_RESERVE, manual_restart_required=False)

    reason_codes: list[str] = []
    eligible_fills = evidence.confirmed_fills
    eligible_clusters = evidence.settlement_clusters
    if evidence.suspected_linked_activity:
        eligible_fills = 0
        eligible_clusters = 0
        reason_codes.append("linked_activity_excluded")

    has_required_depth = campaign.allowed_sides.issubset(
        evidence.independent_depth_sides
    )
    stable_duration = timedelta(0)
    if evidence.stable_since is not None and evidence.stable_since <= now:
        stable_duration = now - evidence.stable_since

    stage = CampaignStage.BOOTSTRAP
    deployment_fraction = _INITIAL_DEPLOYMENT
    if (
        has_required_depth
        and eligible_fills >= 12
        and eligible_clusters >= 5
        and stable_duration >= timedelta(hours=2)
    ):
        stage = CampaignStage.ESTABLISHED
        deployment_fraction = _ESTABLISHED_DEPLOYMENT
    elif (
        has_required_depth
        and eligible_fills >= 6
        and eligible_clusters >= 3
        and stable_duration >= timedelta(minutes=30)
    ):
        stage = CampaignStage.DISCOVERY_50
        deployment_fraction = _DISCOVERY_50_DEPLOYMENT
    elif has_required_depth and eligible_fills >= 2 and eligible_clusters >= 2:
        stage = CampaignStage.DISCOVERY_25
        deployment_fraction = _DISCOVERY_25_DEPLOYMENT

    anchor = _bounded_anchor(campaign, evidence)
    proposed_anchor = evidence.proposed_anchor_price
    if proposed_anchor is not None and anchor != proposed_anchor:
        reason_codes.append("anchor_movement_capped")

    cooldown_sides = frozenset(
        side
        for side, occurred_at in evidence.adverse_fill_times
        if timedelta(0) <= now - occurred_at < _ADVERSE_FILL_COOLDOWN
    )
    if cooldown_sides:
        reason_codes.append("adverse_fill_side_cooldown")
    reason_codes.append(f"bootstrap_capacity_{deployment_fraction}")

    return BootstrapDecision(
        authorized=True,
        stage=stage,
        deployment_fraction=deployment_fraction,
        anchor_price=anchor,
        minimum_price=campaign.minimum_price,
        maximum_price=campaign.maximum_price,
        allowed_sides=campaign.allowed_sides,
        cooldown_sides=cooldown_sides,
        stop_reason=None,
        reason_codes=tuple(reason_codes),
        cancellation_required=False,
        manual_restart_required=False,
        cancellation_fee_reserve_xch=cancellation_fee_reserve,
    )


def _bounded_anchor(
    campaign: BootstrapCampaign,
    evidence: BootstrapEvidence,
) -> Decimal:
    current = evidence.current_anchor_price or campaign.anchor_price
    proposed = evidence.proposed_anchor_price or current
    hour_reference = evidence.anchor_price_one_hour_ago or current
    day_reference = evidence.anchor_price_one_day_ago or current
    lower = max(
        campaign.minimum_price,
        hour_reference * (Decimal("1") - _HOURLY_ANCHOR_LIMIT),
        day_reference * (Decimal("1") - _DAILY_ANCHOR_LIMIT),
    )
    upper = min(
        campaign.maximum_price,
        hour_reference * (Decimal("1") + _HOURLY_ANCHOR_LIMIT),
        day_reference * (Decimal("1") + _DAILY_ANCHOR_LIMIT),
    )
    if lower > upper:
        return current
    return min(max(proposed, lower), upper)
