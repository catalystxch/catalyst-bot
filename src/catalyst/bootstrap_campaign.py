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


@dataclass(frozen=True, slots=True)
class BootstrapEvidence:
    confirmed_fills: int = 0
    settlement_clusters: int = 0


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
    _require_utc(now, "now")
    return BootstrapDecision(
        authorized=True,
        stage=CampaignStage.BOOTSTRAP,
        deployment_fraction=campaign.initial_deployment_fraction,
        anchor_price=campaign.anchor_price,
        minimum_price=campaign.minimum_price,
        maximum_price=campaign.maximum_price,
        allowed_sides=campaign.allowed_sides,
        cooldown_sides=frozenset(),
        stop_reason=None,
        reason_codes=("bootstrap_initial_capacity",),
    )
