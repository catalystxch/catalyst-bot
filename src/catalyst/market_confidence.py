"""Trusted offer-book confidence and manipulation-resistant price policy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from market_evidence import MarketConfidenceSnapshot
from providers.models import Capability, ObservationQuality, ProviderObservation


_PRESETS: dict[str, dict[str, Decimal | int]] = {
    "conservative": {
        "depth_multiple": Decimal("3"),
        "material_move_bps": 250,
        "hard_move_cap_bps": 1500,
        "persistence_refreshes": 3,
        "manipulation_amber": 35,
        "manipulation_red": 70,
        "source_conflict_bps": 250,
        "depth_price_envelope_bps": 250,
        "persistence_jitter_bps": 100,
        "minimum_evidence_ratio": Decimal("0.1"),
        "hard_move_reanchor_refreshes": 6,
    },
    "balanced": {
        "depth_multiple": Decimal("2"),
        "material_move_bps": 400,
        "hard_move_cap_bps": 2000,
        "persistence_refreshes": 2,
        "manipulation_amber": 50,
        "manipulation_red": 80,
        "source_conflict_bps": 400,
        "depth_price_envelope_bps": 400,
        "persistence_jitter_bps": 100,
        "minimum_evidence_ratio": Decimal("0.1"),
        "hard_move_reanchor_refreshes": 5,
    },
    "aggressive": {
        "depth_multiple": Decimal("1.5"),
        "material_move_bps": 600,
        "hard_move_cap_bps": 2500,
        "persistence_refreshes": 2,
        "manipulation_amber": 65,
        "manipulation_red": 90,
        "source_conflict_bps": 600,
        "depth_price_envelope_bps": 600,
        "persistence_jitter_bps": 100,
        "minimum_evidence_ratio": Decimal("0.1"),
        "hard_move_reanchor_refreshes": 4,
    },
}


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise TypeError("now must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _price(value: Any) -> Decimal:
    if type(value) not in {str, Decimal}:
        raise TypeError("offer price must be exact text or Decimal")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("offer price is invalid") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("offer price must be finite and positive")
    return result


def _basis_points(left: Decimal, right: Decimal) -> Decimal:
    if left <= 0 or right <= 0:
        return Decimal("Infinity")
    return abs(left - right) / min(left, right) * Decimal(10_000)


@dataclass(frozen=True, slots=True)
class _Offer:
    offer_id: str
    side: str
    price: Decimal
    amount_mojos: int
    provider_id: str


@dataclass(frozen=True, slots=True)
class MarketConfidenceResult:
    state: str
    derived_at: datetime
    trusted_midpoint: Decimal | None
    trusted_bid: Decimal | None
    trusted_ask: Decimal | None
    independent_bid_depth_mojos: int
    independent_ask_depth_mojos: int
    required_depth_mojos: int
    bid_depth_ratio: Decimal
    ask_depth_ratio: Decimal
    manipulation_score: int
    pending_movement_refreshes: int
    excluded_own_offer_count: int
    deduplicated_offer_count: int
    reason_codes: tuple[str, ...]
    source_health: Mapping[str, str]
    evidence_digests: tuple[str, ...]
    derived_thresholds: Mapping[str, int | str]

    def to_snapshot(
        self,
        *,
        asset_id: str,
        degraded_since: datetime | None = None,
        withdrawal_stage: str = "NONE",
        recovery_refreshes: int = 0,
        material: bool = True,
    ) -> MarketConfidenceSnapshot:
        return MarketConfidenceSnapshot(
            asset_id=asset_id,
            state=self.state,
            derived_at=self.derived_at,
            trusted_midpoint=self.trusted_midpoint,
            trusted_bid=self.trusted_bid,
            trusted_ask=self.trusted_ask,
            degraded_since=degraded_since,
            withdrawal_stage=withdrawal_stage,
            recovery_refreshes=recovery_refreshes,
            reason_codes=self.reason_codes,
            source_health=self.source_health,
            evidence_digests=self.evidence_digests,
            material=material,
        )


class MarketConfidenceEngine:
    """Derive safe prices solely from current attributable offer evidence."""

    def __init__(self, *, risk_preset: str) -> None:
        preset = str(risk_preset).strip().lower()
        if preset not in _PRESETS:
            raise ValueError(
                "risk_preset must be conservative, balanced, or aggressive"
            )
        self.risk_preset = preset
        self._thresholds = _PRESETS[preset]
        self._last_trusted_midpoint: Decimal | None = None
        self._last_trusted_bid: Decimal | None = None
        self._last_trusted_ask: Decimal | None = None
        self._pending_midpoint: Decimal | None = None
        self._pending_refreshes = 0
        self._prior_offer_ids: frozenset[str] = frozenset()
        self._prior_observed_at: datetime | None = None

    @property
    def derived_thresholds(self) -> dict[str, int | str]:
        return {
            key: str(value) if type(value) is Decimal else int(value)
            for key, value in self._thresholds.items()
        }

    def export_state(self) -> dict[str, Any]:
        """Return exact mutable policy state needed for fail-closed restart."""

        def decimal_text(value: Decimal | None) -> str | None:
            return str(value) if value is not None else None

        def iso(value: datetime | None) -> str | None:
            return value.isoformat().replace("+00:00", "Z") if value else None

        return {
            "risk_preset": self.risk_preset,
            "last_trusted_midpoint": decimal_text(self._last_trusted_midpoint),
            "last_trusted_bid": decimal_text(self._last_trusted_bid),
            "last_trusted_ask": decimal_text(self._last_trusted_ask),
            "pending_midpoint": decimal_text(self._pending_midpoint),
            "pending_refreshes": self._pending_refreshes,
            "prior_offer_ids": sorted(self._prior_offer_ids),
            "prior_observed_at": iso(self._prior_observed_at),
        }

    def hydrate(
        self, state: Mapping[str, Any], *, allow_preset_rebase: bool = False
    ) -> None:
        """Restore strictly validated state, optionally rebased to a new preset.

        A preset change preserves trusted anchors and churn history but clears a
        partially observed move because its persistence threshold may differ.
        """

        if type(allow_preset_rebase) is not bool:
            raise TypeError("allow_preset_rebase must be an exact bool")
        if not isinstance(state, Mapping):
            raise ValueError("market confidence state is invalid")
        preset_changed = state.get("risk_preset") != self.risk_preset
        if preset_changed and not allow_preset_rebase:
            raise ValueError("market confidence state risk preset does not match")

        def optional_price(key: str) -> Decimal | None:
            value = state.get(key)
            return None if value is None else _price(value)

        midpoint = optional_price("last_trusted_midpoint")
        bid = optional_price("last_trusted_bid")
        ask = optional_price("last_trusted_ask")
        if (bid is None) != (ask is None):
            raise ValueError("trusted restart range is incomplete")
        if bid is not None and (
            bid > ask or midpoint is None or not bid <= midpoint <= ask
        ):
            raise ValueError("trusted restart range is invalid")
        pending_midpoint = (
            None if preset_changed else optional_price("pending_midpoint")
        )
        pending_refreshes = 0 if preset_changed else state.get("pending_refreshes")
        if type(pending_refreshes) is not int or pending_refreshes < 0:
            raise ValueError("pending refresh count is invalid")
        if (pending_midpoint is None) != (pending_refreshes == 0):
            raise ValueError("pending restart movement is incomplete")
        prior_ids = state.get("prior_offer_ids")
        if type(prior_ids) is not list or any(
            type(value) is not str or not value for value in prior_ids
        ):
            raise ValueError("prior offer identities are invalid")
        prior_observed = state.get("prior_observed_at")
        if prior_observed is None:
            observed_at = None
        elif type(prior_observed) is str:
            text = (
                prior_observed[:-1] + "+00:00"
                if prior_observed.endswith("Z")
                else prior_observed
            )
            observed_at = _utc(datetime.fromisoformat(text))
        else:
            raise ValueError("prior observation time is invalid")
        if not prior_ids:
            observed_at = None
        elif observed_at is None:
            raise ValueError("prior offer churn state is incomplete")

        self._last_trusted_midpoint = midpoint
        self._last_trusted_bid = bid
        self._last_trusted_ask = ask
        self._pending_midpoint = pending_midpoint
        self._pending_refreshes = pending_refreshes
        self._prior_offer_ids = frozenset(prior_ids)
        self._prior_observed_at = observed_at

    def evaluate(
        self,
        *,
        observations: Iterable[ProviderObservation],
        own_offer_identities: frozenset[str],
        configured_offer_size_mojos: int,
        now: datetime,
        settled_trade_price: Decimal | None = None,
        supporting_evidence_digests: tuple[str, ...] = (),
    ) -> MarketConfidenceResult:
        current_time = _utc(now)
        if type(own_offer_identities) is not frozenset or any(
            type(identity) is not str or not identity
            for identity in own_offer_identities
        ):
            raise ValueError("own_offer_identities must be a frozenset of IDs")
        if (
            type(configured_offer_size_mojos) is not int
            or configured_offer_size_mojos <= 0
        ):
            raise ValueError("configured_offer_size_mojos must be positive")
        if settled_trade_price is not None:
            settled_trade_price = _price(settled_trade_price)
        if type(supporting_evidence_digests) is not tuple or any(
            type(digest) is not str or len(digest) != 64
            for digest in supporting_evidence_digests
        ):
            raise ValueError("supporting evidence digests are invalid")

        minimum_offer_amount = int(
            (
                Decimal(configured_offer_size_mojos)
                * Decimal(self._thresholds["minimum_evidence_ratio"])
            ).to_integral_value(rounding=ROUND_CEILING)
        )

        reasons: list[str] = []
        source_health: dict[str, str] = {}
        evidence_digests: list[str] = []
        provider_offers: dict[str, list[_Offer]] = {}
        provider_midpoints: dict[str, Decimal] = {}
        excluded_own = 0
        dust_offers: list[_Offer] = []

        ordered = sorted(
            tuple(observations),
            key=lambda item: (item.provider_id != "dexie", item.provider_id),
        )
        for observation in ordered:
            if type(observation) is not ProviderObservation:
                raise TypeError("observations must contain ProviderObservation values")
            if observation.capability is not Capability.ORDER_BOOK:
                continue
            evidence_digests.append(observation.payload_sha256)
            if observation.quality is ObservationQuality.INVALID:
                source_health[observation.provider_id] = "invalid"
                reasons.append("invalid_provider_data")
                continue
            if observation.fresh_until < current_time:
                source_health[observation.provider_id] = "degraded"
                reasons.append("stale_provider_data")
                continue
            source_health[observation.provider_id] = observation.quality.value
            try:
                offers = self._parse_offers(observation)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                source_health[observation.provider_id] = "invalid"
                reasons.append("malformed_provider_response")
                continue
            independent = []
            for offer in offers:
                if offer.offer_id in own_offer_identities:
                    excluded_own += 1
                elif offer.amount_mojos < minimum_offer_amount:
                    dust_offers.append(offer)
                else:
                    independent.append(offer)
            provider_offers[observation.provider_id] = independent
            bids = [offer.price for offer in independent if offer.side == "buy"]
            asks = [offer.price for offer in independent if offer.side == "sell"]
            if bids and asks:
                provider_midpoints[observation.provider_id] = (
                    max(bids) + min(asks)
                ) / Decimal(2)
        evidence_digests.extend(supporting_evidence_digests)

        source_conflict = self._source_conflict(provider_midpoints)
        selected_providers: set[str] | None = None
        if source_conflict:
            if settled_trade_price is None:
                reasons.append("provider_price_conflict")
            else:
                closest = min(
                    provider_midpoints,
                    key=lambda provider: _basis_points(
                        provider_midpoints[provider], settled_trade_price
                    ),
                )
                if _basis_points(
                    provider_midpoints[closest], settled_trade_price
                ) <= Decimal(100):
                    selected_providers = {closest}
                    reasons.append("chain_override_source_conflict")
                else:
                    reasons.append("provider_chain_conflict")

        deduplicated = 0
        seen_ids: set[str] = set()
        offers: list[_Offer] = []
        for provider_id, provider_rows in provider_offers.items():
            if selected_providers is not None and provider_id not in selected_providers:
                continue
            for offer in provider_rows:
                if offer.offer_id in seen_ids:
                    deduplicated += 1
                    continue
                seen_ids.add(offer.offer_id)
                offers.append(offer)

        bids = [offer for offer in offers if offer.side == "buy"]
        asks = [offer for offer in offers if offer.side == "sell"]
        best_bid = max((offer.price for offer in bids), default=None)
        best_ask = min((offer.price for offer in asks), default=None)
        envelope = Decimal(self._thresholds["depth_price_envelope_bps"]) / Decimal(
            10_000
        )
        executable_bids = (
            [
                offer
                for offer in bids
                if offer.price >= best_bid * (Decimal(1) - envelope)
            ]
            if best_bid is not None
            else []
        )
        executable_asks = (
            [
                offer
                for offer in asks
                if offer.price <= best_ask * (Decimal(1) + envelope)
            ]
            if best_ask is not None
            else []
        )
        bid_depth = sum(offer.amount_mojos for offer in executable_bids)
        ask_depth = sum(offer.amount_mojos for offer in executable_asks)
        executable_provider_ids = {
            offer.provider_id for offer in (*executable_bids, *executable_asks)
        }
        dust_out_of_range = any(
            (
                offer.side == "buy"
                and best_bid is not None
                and offer.price < best_bid * (Decimal(1) - envelope)
            )
            or (
                offer.side == "sell"
                and best_ask is not None
                and offer.price > best_ask * (Decimal(1) + envelope)
            )
            for offer in dust_offers
        )
        if (
            len(executable_bids) != len(bids)
            or len(executable_asks) != len(asks)
            or dust_out_of_range
        ):
            reasons.append("out_of_range_depth_excluded")
        required_depth = int(
            (
                Decimal(configured_offer_size_mojos)
                * Decimal(self._thresholds["depth_multiple"])
            ).to_integral_value(rounding=ROUND_CEILING)
        )
        proposed_midpoint = (
            (best_bid + best_ask) / Decimal(2)
            if best_bid is not None and best_ask is not None and best_bid <= best_ask
            else None
        )

        if best_bid is None or best_ask is None:
            reasons.append("one_sided_book")
        elif best_bid > best_ask:
            reasons.append("crossed_book")
        if bid_depth < required_depth:
            reasons.append("insufficient_bid_depth")
        if ask_depth < required_depth:
            reasons.append("insufficient_ask_depth")

        churn_ids = {offer.offer_id for offer in (*executable_bids, *executable_asks)}
        manipulation_score = self._churn_score(churn_ids, current_time)
        if manipulation_score:
            reasons.append("rapid_offer_churn")

        hard_cap = False
        pending = False
        settled_confirmation = False
        usable_provider_count = sum(
            1
            for provider in provider_midpoints
            if provider in executable_provider_ids
            and (selected_providers is None or provider in selected_providers)
        )
        movement_sample_safe = bool(
            bid_depth >= required_depth
            and ask_depth >= required_depth
            and not source_conflict
            and manipulation_score < int(self._thresholds["manipulation_red"])
        )
        if proposed_midpoint is not None and self._last_trusted_midpoint is not None:
            move_bps = _basis_points(proposed_midpoint, self._last_trusted_midpoint)
            hard_cap = move_bps > Decimal(self._thresholds["hard_move_cap_bps"])
            if hard_cap:
                corroborated = movement_sample_safe and usable_provider_count >= 2
                pending_anchor_matches = (
                    self._pending_midpoint is not None
                    and _basis_points(proposed_midpoint, self._pending_midpoint)
                    <= Decimal(self._thresholds["persistence_jitter_bps"])
                )
                if not corroborated:
                    reasons.append("hard_price_move_cap")
                    self._pending_midpoint = None
                    self._pending_refreshes = 0
                else:
                    if pending_anchor_matches:
                        self._pending_refreshes += 1
                    else:
                        self._pending_midpoint = proposed_midpoint
                        self._pending_refreshes = 1
                    if self._pending_refreshes >= int(
                        self._thresholds["hard_move_reanchor_refreshes"]
                    ):
                        hard_cap = False
                        reasons.append("hard_move_reanchor_persistence_satisfied")
                        self._pending_midpoint = None
                        self._pending_refreshes = 0
                    else:
                        reasons.append("hard_price_move_cap")
            elif move_bps > Decimal(self._thresholds["material_move_bps"]):
                settled_confirmation = (
                    settled_trade_price is not None
                    and _basis_points(proposed_midpoint, settled_trade_price)
                    <= Decimal(100)
                )
                if settled_confirmation:
                    reasons.append("settled_trade_confirmed_move")
                    self._pending_midpoint = None
                    self._pending_refreshes = 0
                else:
                    if not movement_sample_safe:
                        self._pending_midpoint = None
                        self._pending_refreshes = 0
                        pending = True
                        reasons.append("material_move_pending_confirmation")
                    else:
                        pending_anchor_matches = (
                            self._pending_midpoint is not None
                            and _basis_points(proposed_midpoint, self._pending_midpoint)
                            <= Decimal(self._thresholds["persistence_jitter_bps"])
                        )
                        if pending_anchor_matches:
                            self._pending_refreshes += 1
                        else:
                            self._pending_midpoint = proposed_midpoint
                            self._pending_refreshes = 1
                        pending = self._pending_refreshes < int(
                            self._thresholds["persistence_refreshes"]
                        )
                        if pending:
                            reasons.append("material_move_pending_confirmation")
                        else:
                            reasons.append("movement_persistence_satisfied")
                            self._pending_midpoint = None
                            self._pending_refreshes = 0
            else:
                self._pending_midpoint = None
                self._pending_refreshes = 0

        fatal = bool(
            proposed_midpoint is None
            or bid_depth < required_depth
            or ask_depth < required_depth
            or hard_cap
            or (source_conflict and "chain_override_source_conflict" not in reasons)
            or manipulation_score >= int(self._thresholds["manipulation_red"])
        )
        amber = bool(
            pending
            or selected_providers is not None
            or usable_provider_count < 2
            or "stale_provider_data" in reasons
            or manipulation_score >= int(self._thresholds["manipulation_amber"])
        )
        if usable_provider_count < 2 and proposed_midpoint is not None:
            reasons.append("single_provider_dependency")
        state = "RED" if fatal else ("AMBER" if amber else "GREEN")

        accept_proposed = (
            proposed_midpoint is not None
            and not fatal
            and not pending
            and (not source_conflict or selected_providers is not None)
        )
        if accept_proposed:
            self._last_trusted_midpoint = proposed_midpoint
            self._last_trusted_bid = best_bid
            self._last_trusted_ask = best_ask
        trusted_midpoint = self._last_trusted_midpoint
        trusted_bid = self._last_trusted_bid
        trusted_ask = self._last_trusted_ask

        self._prior_offer_ids = frozenset(churn_ids)
        self._prior_observed_at = current_time if churn_ids else None
        return MarketConfidenceResult(
            state=state,
            derived_at=current_time,
            trusted_midpoint=trusted_midpoint,
            trusted_bid=trusted_bid,
            trusted_ask=trusted_ask,
            independent_bid_depth_mojos=bid_depth,
            independent_ask_depth_mojos=ask_depth,
            required_depth_mojos=required_depth,
            bid_depth_ratio=Decimal(bid_depth) / Decimal(configured_offer_size_mojos),
            ask_depth_ratio=Decimal(ask_depth) / Decimal(configured_offer_size_mojos),
            manipulation_score=manipulation_score,
            pending_movement_refreshes=self._pending_refreshes,
            excluded_own_offer_count=excluded_own,
            deduplicated_offer_count=deduplicated,
            reason_codes=tuple(dict.fromkeys(reasons)),
            source_health=dict(sorted(source_health.items())),
            evidence_digests=tuple(dict.fromkeys(evidence_digests)),
            derived_thresholds=self.derived_thresholds,
        )

    def _source_conflict(self, midpoints: Mapping[str, Decimal]) -> bool:
        if len(midpoints) < 2:
            return False
        values = tuple(midpoints.values())
        return _basis_points(min(values), max(values)) > Decimal(
            self._thresholds["source_conflict_bps"]
        )

    def _churn_score(self, offer_ids: set[str], now: datetime) -> int:
        if not self._prior_offer_ids or self._prior_observed_at is None:
            return 0
        elapsed = (now - self._prior_observed_at).total_seconds()
        if elapsed < 0 or elapsed > 60:
            return 0
        changed = len(self._prior_offer_ids.symmetric_difference(offer_ids))
        denominator = max(len(self._prior_offer_ids), len(offer_ids), 1)
        return min(100, int(Decimal(changed) / Decimal(denominator) * Decimal(100)))

    @staticmethod
    def _parse_offers(observation: ProviderObservation) -> list[_Offer]:
        payload = json.loads(observation.raw_evidence_json)
        rows: list[_Offer] = []
        if observation.provider_id == "dexie" or (
            "bids" in payload and "asks" in payload
        ):
            for key, side in (("bids", "buy"), ("asks", "sell")):
                for row in payload[key]:
                    rows.append(
                        _Offer(
                            offer_id=str(row["offer_id"]),
                            side=side,
                            price=_price(row["price"]),
                            amount_mojos=MarketConfidenceEngine._amount(
                                row["amount_mojos"]
                            ),
                            provider_id=observation.provider_id,
                        )
                    )
        else:
            for row in payload["offers"]:
                side = row["side"]
                if side not in {"buy", "sell"}:
                    raise ValueError("offer side is invalid")
                rows.append(
                    _Offer(
                        offer_id=str(row["offer_id"]),
                        side=side,
                        price=_price(row["price"]),
                        amount_mojos=MarketConfidenceEngine._amount(
                            row["amount_mojos"]
                        ),
                        provider_id=observation.provider_id,
                    )
                )
        if any(not row.offer_id for row in rows):
            raise ValueError("offer identity is missing")
        return rows

    @staticmethod
    def _amount(value: Any) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError("offer amount must be a positive integer")
        return value
