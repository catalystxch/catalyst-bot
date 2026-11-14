"""Immutable, canonical terms for one approved Follow run."""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal
import hashlib
import json


def _canonical_decimal(value: Decimal) -> str:
    """Render equal Decimal values identically without using binary floats."""
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


@dataclass(frozen=True, slots=True)
class FollowRunPolicy:
    """Material wallet, ladder, price, fee and reserve terms for a run.

    Monetary XCH values use integer mojos, CAT reserves use integer atoms,
    and prices must be ``Decimal`` values.
    """

    wallet_fingerprint: str
    network: str
    asset_id: str
    buy_target: int
    sell_target: int
    price_anchor: Decimal
    price_min: Decimal
    price_max: Decimal
    maximum_fee_mojos_per_tx: int
    fee_coin_principal_mojos: int
    xch_reserve_mojos: int
    cat_reserve_atoms: int
    maximum_trade_xch_mojos: int
    maximum_trade_cat_atoms: int

    def __post_init__(self) -> None:
        for name in ("wallet_fingerprint", "network", "asset_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

        for name in ("buy_target", "sell_target"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

        for name in ("price_anchor", "price_min", "price_max"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be Decimal")
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not self.price_min <= self.price_anchor <= self.price_max:
            raise ValueError("price range must contain the anchor")

        for name in (
            "maximum_fee_mojos_per_tx",
            "fee_coin_principal_mojos",
            "xch_reserve_mojos",
            "cat_reserve_atoms",
            "maximum_trade_xch_mojos",
            "maximum_trade_cat_atoms",
        ):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an integer")
            if value < 0 or (name == "maximum_fee_mojos_per_tx" and value == 0):
                raise ValueError(
                    f"{name} must be {'positive' if name == 'maximum_fee_mojos_per_tx' else 'non-negative'}"
                )

    @property
    def digest(self) -> str:
        """SHA-256 digest of the canonical JSON representation."""
        payload = {
            field.name: (
                _canonical_decimal(value)
                if isinstance(value := getattr(self, field.name), Decimal)
                else value
            )
            for field in fields(self)
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def material_changes(self, other: FollowRunPolicy) -> tuple[str, ...]:
        """Return the ordered names of terms that differ from ``other``."""
        if not isinstance(other, FollowRunPolicy):
            raise TypeError("other must be a FollowRunPolicy")
        return tuple(
            field.name
            for field in fields(self)
            if getattr(self, field.name) != getattr(other, field.name)
        )
