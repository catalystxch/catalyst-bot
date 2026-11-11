"""Explicit, run-scoped thin-market consent. Never wallet or fee authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import threading
import time
import uuid

from follow_run_terms import CONTINUOUS_RUN_EXPIRY


_ALLOWED_REASONS = frozenset(
    {
        "insufficient_bid_depth",
        "insufficient_ask_depth",
        "single_provider_dependency",
        "out_of_range_depth_excluded",
        "hard_price_move_cap",
    }
)


def scope_digest(scope: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            scope, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _utc(now):
    if type(now) is not datetime or now.tzinfo is None:
        raise ValueError("CONFIDENCE_OVERRIDE_TIME_INVALID")
    return now.astimezone(timezone.utc)


@dataclass
class RunConsent:
    digest: str
    approved_at: datetime
    expires_at: datetime
    consent_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    revoked: bool = False
    follow_run_id: str | None = None
    _started: float = field(default_factory=time.monotonic, repr=False)
    _movement: dict = field(default_factory=dict, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @classmethod
    def confirm(cls, *, scope, reviewed_digest, duration_hours, now):
        now = _utc(now)
        if type(duration_hours) is not int or not 1 <= duration_hours <= 168:
            raise ValueError("CONFIDENCE_OVERRIDE_DURATION_INVALID")
        digest = scope_digest(scope)
        if type(reviewed_digest) is not str or reviewed_digest != digest:
            raise ValueError("CONFIDENCE_OVERRIDE_REVIEW_CHANGED")
        expires = now + timedelta(hours=duration_hours)
        if "run_expires_at_epoch" in scope:
            epoch = scope["run_expires_at_epoch"]
            if type(epoch) is not int or epoch <= int(now.timestamp()):
                raise ValueError("FOLLOW_FEE_AUTHORITY_EXPIRED")
            if epoch != CONTINUOUS_RUN_EXPIRY:
                expires = min(expires, datetime.fromtimestamp(epoch, timezone.utc))
        return cls(
            digest=digest,
            approved_at=now,
            expires_at=expires,
            follow_run_id=scope.get("follow_run_id"),
        )

    def revoke(self):
        with self._lock:
            self.revoked = True

    def active(self, *, scope, now):
        with self._lock:
            try:
                current = _utc(now)
                elapsed = time.monotonic() - self._started
                valid = (
                    not self.revoked
                    and self.digest == scope_digest(scope)
                    and self.approved_at <= current < self.expires_at
                    and 0
                    <= elapsed
                    < (self.expires_at - self.approved_at).total_seconds()
                )
            except (TypeError, ValueError):
                valid = False
            if not valid:
                self.revoked = True
            return valid

    def candidate_active(self, *, now):
        """Cheap prefilter; the wallet effect still checks the complete scope."""
        with self._lock:
            try:
                current = _utc(now)
                elapsed = time.monotonic() - self._started
                return bool(
                    not self.revoked
                    and self.approved_at <= current < self.expires_at
                    and 0
                    <= elapsed
                    < (self.expires_at - self.approved_at).total_seconds()
                )
            except (TypeError, ValueError):
                return False

    def price_range(self, confidence, *, now, valid_until):
        """Retain price persistence independently of the waived depth policy.

        A repeated read of the same observation never counts as confirmation.
        Unknown failures and conflicting/manipulated prices remain rejected.
        A hard-cap move needs current bid/ask evidence inside the reviewed
        absolute price band.
        """
        with self._lock:
            if self.revoked:
                return None
            if (
                self._movement
                and type(getattr(confidence, "derived_at", None)) is datetime
                and confidence.derived_at < self._movement["observed"]
            ):
                return None
            strict = override_price_range(confidence, now=now, valid_until=valid_until)
            if strict is not None:
                self._movement.clear()
                return strict
            prices = override_price_range(
                confidence, now=now, valid_until=valid_until, allow_thin_pending=True
            )
            if prices is None:
                self._movement.clear()
                return None
            thresholds = getattr(confidence, "derived_thresholds", {})
            required = thresholds.get("persistence_refreshes")
            jitter = thresholds.get("persistence_jitter_bps")
            if (
                type(required) is not int
                or not 2 <= required <= 10
                or type(jitter) is not int
                or not 0 <= jitter <= 100
            ):
                self._movement.clear()
                return None
            observed = confidence.derived_at
            prior = self._movement
            if prior and observed <= prior["observed"]:
                return (
                    prices
                    if observed == prior["observed"]
                    and prices[1] == prior["observed_midpoint"]
                    and prior["count"] >= required
                    else None
                )
            matches = bool(
                prior
                and abs(prices[1] - prior["midpoint"])
                / min(prices[1], prior["midpoint"])
                * Decimal(10000)
                <= Decimal(jitter)
            )
            self._movement = {
                "observed": observed,
                "observed_midpoint": prices[1],
                "midpoint": prices[1] if not matches else prior["midpoint"],
                "count": prior["count"] + 1 if matches else 1,
            }
            return prices if self._movement["count"] >= required else None

    def record(self):
        return {
            "consent_id": self.consent_id,
            "scope_digest": self.digest,
            "approved_at": self.approved_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "restorable": False,
        }


def override_price_range(confidence, *, now, valid_until, allow_thin_pending=False):
    """Allow thin depth or bounded hard moves, never reuse price evidence."""
    try:
        current = _utc(now)
        derived = _utc(confidence.derived_at)
        deadline = _utc(valid_until)
        reasons = set(confidence.reason_codes)
        if (
            allow_thin_pending is True
            and "hard_price_move_cap" not in reasons
            and "material_move_pending_confirmation" in reasons
            and reasons & {"insufficient_bid_depth", "insufficient_ask_depth"}
        ):
            reasons.remove("material_move_pending_confirmation")
        if (
            not -2 <= (current - derived).total_seconds() <= 30
            or current >= deadline
            or reasons - _ALLOWED_REASONS
            or confidence.manipulation_score != 0
            or confidence.pending_movement_refreshes != 0
            or type(confidence.provider_redundancy) is not int
            or confidence.provider_redundancy < 1
        ):
            return None
        digests = confidence.evidence_digests
        if not digests or any(
            type(d) is not str
            or len(d) != 64
            or any(c not in "0123456789abcdef" for c in d)
            for d in digests
        ):
            return None
        bid, ask = confidence.observed_bid, confidence.observed_ask
        if (
            any(
                type(v) is not Decimal or not v.is_finite() or v <= 0
                for v in (bid, ask)
            )
            or bid > ask
        ):
            return None
        if "hard_price_move_cap" in reasons:
            from config import cfg

            hard_min = Decimal(str(getattr(cfg, "HARD_MIN_PRICE_XCH", 0)))
            hard_max = Decimal(str(getattr(cfg, "HARD_MAX_PRICE_XCH", 0)))
            if (
                not hard_min.is_finite()
                or not hard_max.is_finite()
                or hard_min <= 0
                or hard_min >= hard_max
                or bid < hard_min
                or ask > hard_max
            ):
                return None
        return bid, (bid + ask) / Decimal(2), ask
    except (AttributeError, TypeError, ValueError, ArithmeticError):
        return None


def saved_thin_market_price_range(confidence, *, now, valid_until):
    """Price corridor for a saved thin-market choice, without a fixed band.

    A current two-sided book supplies its own bounds. A one-sided book may
    use an attributable accepted midpoint from the past 24 hours. This is
    only price evidence; the live run, wallet and fee authority are separate.
    """
    from config import cfg
    from thin_market_reference import select_thin_market_reference

    try:
        current = _utc(now)
        deadline = _utc(valid_until)
        if (
            getattr(confidence, "state", None) != "RED"
            or current >= deadline
            or getattr(confidence, "pending_movement_refreshes", 0) != 0
        ):
            return None
        reference = select_thin_market_reference(confidence, now=current)
        if reference is None:
            return None
        if reference.source == "current_book":
            return (
                reference.observed_bid,
                reference.midpoint,
                reference.observed_ask,
                reference.evidence_digests,
            )
        half_spread = Decimal(str(cfg.SPREAD_BPS)) / Decimal(20000)
        if not half_spread.is_finite() or not Decimal(0) < half_spread < Decimal(1):
            return None
        midpoint = reference.midpoint
        bid = reference.observed_bid
        ask = reference.observed_ask
        if (bid is not None and bid >= midpoint) or (
            ask is not None and ask <= midpoint
        ):
            return None
        lower = midpoint * (Decimal(1) - half_spread)
        upper = midpoint * (Decimal(1) + half_spread)
        if bid is not None:
            lower = min(lower, bid)
        if ask is not None:
            upper = max(upper, ask)
        return lower, midpoint, upper, reference.evidence_digests
    except (AttributeError, TypeError, ValueError, ArithmeticError):
        return None


class SavedThinMarketConsent:
    """Run-bound use of a saved user choice; never financial authority.

    It is rebound only when a new bot run has proved a current Follow scope.
    Scope drift revokes it for the rest of that run. The saved preference is
    separate from this transient object and can be changed by the user.
    """

    dynamic_band = True

    def __init__(self, scope):
        self.digest = scope_digest(scope)
        self.follow_run_id = scope.get("follow_run_id")
        self.revoked = False
        self._lock = threading.RLock()

    def revoke(self):
        with self._lock:
            self.revoked = True

    def active(self, *, scope, now):
        with self._lock:
            valid = not self.revoked and self.digest == scope_digest(scope)
            if not valid:
                self.revoked = True
            return valid

    def candidate_active(self, *, now):
        with self._lock:
            return not self.revoked

    def price_evidence(self, confidence, *, now, valid_until):
        with self._lock:
            if self.revoked:
                return None
            return saved_thin_market_price_range(
                confidence, now=now, valid_until=valid_until
            )

    def price_range(self, confidence, *, now, valid_until):
        evidence = self.price_evidence(confidence, now=now, valid_until=valid_until)
        return evidence[:3] if evidence is not None else None


_THIN_CHOICE_SETTING = "thin_market_choice_v1"


def _thin_choice_identity(identity: dict) -> dict:
    keys = (
        "network",
        "wallet_type",
        "wallet_fingerprint",
        "asset_id",
        "wallet_id",
        "xch_wallet_id",
        "ticker",
    )
    if type(identity) is not dict or any(identity.get(key) is None for key in keys):
        raise ValueError("THIN_MARKET_IDENTITY_UNAVAILABLE")
    return {key: identity[key] for key in keys}


def record_saved_thin_market_choice() -> bool:
    """Bind the user's saved selection to the verified current Sage pair."""
    import database
    from coin_prep_fee_runtime import _configuration, _verified_identity

    configuration = _configuration()
    identity = _verified_identity(configuration)
    full_identity = {
        **identity,
        "asset_id": configuration["CAT_ASSET_ID"],
        "wallet_id": configuration["CAT_WALLET_ID"],
        "xch_wallet_id": configuration["WALLET_ID_XCH"],
        "ticker": configuration["CAT_TICKER_ID"],
    }
    payload = json.dumps(
        _thin_choice_identity(full_identity), sort_keys=True, separators=(",", ":")
    )
    return database.set_setting(_THIN_CHOICE_SETTING, payload) is True


def saved_thin_market_choice_matches(scope: dict) -> bool:
    """A saved RED choice cannot silently migrate to another wallet or CAT."""
    import database

    try:
        expected = _thin_choice_identity(scope["identity"])
        raw = database.get_setting(_THIN_CHOICE_SETTING)
        actual = json.loads(raw) if type(raw) is str else None
        return actual == expected
    except (KeyError, TypeError, ValueError):
        return False


class ConsentedConfidence:
    """Transient candidate view; raw confidence and persisted RED are untouched.

    Revalidate at every final candidate check, including after coin rounding.
    The view never survives a run or supplies authority independently of it.
    """

    def __init__(
        self,
        raw,
        authorize,
        price_range,
        *,
        candidate_authorize=None,
        current_view=None,
        evidence_digests=None,
        dynamic_band=False,
    ):
        self._raw, self._authorize, self._range = raw, authorize, price_range
        self._candidate_authorize = candidate_authorize or authorize
        self._current_view = current_view
        self._evidence_digests = evidence_digests
        self.dynamic_band = dynamic_band

    def dispatch_allowed(self):
        return self._authorize() is True

    def current_view(self):
        return self._current_view() if self._current_view is not None else self

    def __getattr__(self, key):
        if key == "data_valid":
            return self._candidate_authorize() is True
        if key in {"trusted_bid", "trusted_midpoint", "trusted_ask"}:
            return self._range[
                {"trusted_bid": 0, "trusted_midpoint": 1, "trusted_ask": 2}[key]
            ]
        if key == "evidence_digests" and self._evidence_digests is not None:
            return self._evidence_digests
        return getattr(self._raw, key)


def _configuration_digest(configuration):
    from config import cfg
    from coin_prep_fee_execution import encode_execution_configuration

    extra = {
        key: str(getattr(cfg, key, ""))
        for key in (
            "MAX_POSITION_XCH",
            "MARKET_RISK_PRESET",
            "ENABLE_BUY",
            "ENABLE_SELL",
            "HARD_MIN_PRICE_XCH",
            "HARD_MAX_PRICE_XCH",
            "DYNAMIC_LIMIT_PCT",
            "SNIPER_ENABLED",
            "SNIPER_SIZE_XCH",
            "MIN_EDGE_BPS",
            "THIN_MARKET_ENABLED",
        )
    }
    return scope_digest(
        {"configuration": encode_execution_configuration(configuration), "extra": extra}
    )


def current_configuration_digest():
    """Shared server settings digest; no wallet, DB, quote or effect calls."""
    from coin_prep_fee_runtime import _configuration

    return _configuration_digest(_configuration())


def current_scope():
    """Require proved durable Follow authority; prep consent is insufficient.

    The separate ledger reader never grants wallet dispatch. If it is not yet
    installed or cannot prove the bound run, the override remains unavailable.
    Mutable accounting counters deliberately do not enter the risk-consent hash.
    """
    import database
    import mutation_gate
    from config import cfg
    from coin_prep_fee_runtime import _configuration, _verified_identity

    configuration = _configuration()
    configuration_sha256 = _configuration_digest(configuration)
    identity = _verified_identity(configuration)
    asset = configuration["CAT_ASSET_ID"]
    if database.list_active_bootstrap_campaigns_for_asset(asset):
        raise ValueError("CONFIDENCE_OVERRIDE_FOLLOW_ONLY")
    identity = {
        **identity,
        "asset_id": asset,
        "wallet_id": configuration["CAT_WALLET_ID"],
        "xch_wallet_id": configuration["WALLET_ID_XCH"],
        "ticker": configuration["CAT_TICKER_ID"],
    }
    reader = getattr(database, "get_follow_creation_authority", None)
    if not callable(reader):
        raise ValueError("FOLLOW_FEE_AUTHORITY_REQUIRED")
    authority = reader(
        identity=identity,
        configuration_sha256=configuration_sha256,
        now_epoch=int(datetime.now(timezone.utc).timestamp()),
    )
    if type(authority) is not dict or authority.get("ready") is not True:
        if (
            type(authority) is dict
            and authority.get("reason_code") == "FOLLOW_UNRESOLVED_EFFECT"
        ):
            raise ValueError("CONFIDENCE_OVERRIDE_OPERATION_PENDING")
        raise ValueError("FOLLOW_FEE_AUTHORITY_REQUIRED")

    def digest_ok(value):
        return (
            type(value) is str
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value)
        )

    if (
        not digest_ok(authority.get("run_id"))
        or not digest_ok(authority.get("consent_id"))
        or authority.get("configuration_sha256") != configuration_sha256
        or type(authority.get("identity")) is not dict
        or scope_digest(authority["identity"]) != scope_digest(identity)
        or any(
            type(authority.get(k)) is not int
            for k in (
                "buy_limit",
                "sell_limit",
                "expires_at_epoch",
                "maximum_fee_mojos",
                "protected_shutdown_fee_mojos",
            )
        )
        or authority["buy_limit"] != configuration["MAX_ACTIVE_BUY_OFFERS"]
        or authority["sell_limit"] != configuration["MAX_ACTIVE_SELL_OFFERS"]
        or type(authority.get("unbounded", False)) is not bool
        or not 0 < authority["maximum_fee_mojos"] <= 2**63 - 1
        or not 0
        <= authority["protected_shutdown_fee_mojos"]
        <= authority["maximum_fee_mojos"]
        or authority["expires_at_epoch"] <= int(datetime.now(timezone.utc).timestamp())
    ):
        raise ValueError("FOLLOW_FEE_AUTHORITY_MISMATCH")
    runtime = mutation_gate.current_runtime()
    if runtime is None or not runtime.run_id:
        raise ValueError("CONFIDENCE_OVERRIDE_RUNTIME_REQUIRED")
    if current_configuration_digest() != configuration_sha256:
        raise ValueError("CONFIDENCE_OVERRIDE_SETTINGS_CHANGED")
    return {
        "identity": identity,
        "owner_run_id": runtime.run_id,
        "configuration_sha256": configuration_sha256,
        "follow_run_id": authority["run_id"],
        "financial_consent_id": authority["consent_id"],
        "run_expires_at_epoch": authority["expires_at_epoch"],
        "run_expires_at": (
            None
            if authority["expires_at_epoch"] == CONTINUOUS_RUN_EXPIRY
            else datetime.fromtimestamp(
                authority["expires_at_epoch"], timezone.utc
            ).isoformat()
        ),
        "buy_limit": authority["buy_limit"],
        "sell_limit": authority["sell_limit"],
        "xch_reserve": str(configuration["XCH_RESERVE"]),
        "cat_reserve": str(configuration["CAT_RESERVE"]),
        "hard_min_price_xch": str(getattr(cfg, "HARD_MIN_PRICE_XCH", "")),
        "hard_max_price_xch": str(getattr(cfg, "HARD_MAX_PRICE_XCH", "")),
        "tier_sizes_xch": {
            side.lower(): {
                tier.lower(): str(configuration[f"{side}_{tier}_SIZE_XCH"])
                for tier in ("INNER", "MID", "OUTER", "EXTREME")
            }
            for side in ("BUY", "SELL")
        },
        "default_trade_xch": str(configuration["DEFAULT_TRADE_XCH"]),
        # The ledger retains a bookkeeping amount for unbounded approval, but
        # that amount is not an enforceable cumulative fee ceiling.
        "fee_unbounded": authority.get("unbounded") is True,
        "fee_cap_mojos": (
            None
            if authority.get("unbounded") is True
            else str(authority["maximum_fee_mojos"])
        ),
        "protected_cancel_mojos": str(authority["protected_shutdown_fee_mojos"]),
    }


_REVIEW_LOCK = threading.RLock()


def prepare_review(bot, *, duration_hours=48, now=None):
    now = _utc(now or datetime.now(timezone.utc))
    if (
        type(duration_hours) is not int
        or not 1 <= duration_hours <= 168
        or bot.is_running()
    ):
        raise ValueError("CONFIDENCE_OVERRIDE_REVIEW_UNAVAILABLE")
    scope = current_scope()
    review = {
        "review_id": uuid.uuid4().hex,
        "scope": scope,
        "scope_digest": scope_digest(scope),
        "duration_hours": duration_hours,
        "review_expires_at": (now + timedelta(seconds=60)).isoformat(),
        "reviewed_at": now.isoformat(),
    }
    with _REVIEW_LOCK:
        bot._confidence_override_review = json.loads(json.dumps(review))
        bot._confidence_override_review_started = time.monotonic()
    return review


def confirm_review(bot, confirmation, *, now=None):
    now = _utc(now or datetime.now(timezone.utc))
    with _REVIEW_LOCK:
        review = getattr(bot, "_confidence_override_review", None)
        bot._confidence_override_review = None
        started = getattr(bot, "_confidence_override_review_started", None)
    if (
        type(review) is not dict
        or type(confirmation) is not dict
        or set(confirmation) != {"review_id", "accepted"}
        or confirmation.get("accepted") is not True
        or confirmation.get("review_id") != review["review_id"]
        or bot.is_running()
        or type(started) not in (int, float)
        or not 0 <= time.monotonic() - started < 60
        or now < datetime.fromisoformat(review["reviewed_at"])
        or not datetime.fromisoformat(review["review_expires_at"]) > now
    ):
        raise ValueError("CONFIDENCE_OVERRIDE_CONFIRMATION_REQUIRED")
    return RunConsent.confirm(
        scope=current_scope(),
        reviewed_digest=review["scope_digest"],
        duration_hours=review["duration_hours"],
        now=now,
    )
