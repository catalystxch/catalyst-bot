"""Coinset adapter for exact coin and spend evidence."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from ._normalization import (
    exact_nonnegative_height,
    failed_observation,
    observation,
    utc_now,
)
from .models import (
    Capability,
    ObservationQuality,
    ProviderCapabilities,
    ProviderObservation,
)


class CoinsetEvidenceProvider:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.capabilities = ProviderCapabilities(
            "coinset", frozenset({Capability.CHAIN_EVIDENCE})
        )

    def observe_coin(
        self, coin_id: str, *, now: datetime | None = None
    ) -> ProviderObservation:
        observed_at = utc_now(now)
        try:
            raw = self._client.get_coin_by_name(coin_id)
            if raw is None:
                return observation(
                    provider_id="coinset",
                    capability=Capability.CHAIN_EVIDENCE,
                    payload={"available": True, "observed": False},
                    observed_at=observed_at,
                    identity_keys=(coin_id.lower(),),
                    freshness_seconds=20,
                    quality=ObservationQuality.DEGRADED,
                    reason_codes=("coin_not_observed",),
                )
            if type(raw) is not dict:
                raise ValueError("Coinset coin record is invalid")
            expected_id = coin_id.lower().removeprefix("0x")
            coin = raw.get("coin") if type(raw.get("coin")) is dict else raw
            supplied_id = (
                str(
                    raw.get("coin_name")
                    or raw.get("name")
                    or coin.get("coin_name")
                    or coin.get("name")
                    or ""
                )
                .lower()
                .removeprefix("0x")
            )
            if not supplied_id:
                parent = str(coin.get("parent_coin_info") or "").removeprefix("0x")
                puzzle_hash = str(coin.get("puzzle_hash") or "").removeprefix("0x")
                amount = coin.get("amount")
                if (
                    len(parent) != 64
                    or len(puzzle_hash) != 64
                    or type(amount) is not int
                    or amount < 0
                ):
                    raise ValueError("Coinset coin identity is unavailable")
                encoded_amount = _encode_chia_amount(amount)
                supplied_id = hashlib.sha256(
                    bytes.fromhex(parent) + bytes.fromhex(puzzle_hash) + encoded_amount
                ).hexdigest()
            if supplied_id != expected_id:
                raise ValueError("Coinset coin identity mismatch")
            height = exact_nonnegative_height(raw.get("spent_block_index"))
            spent = raw.get("spent")
            if type(spent) is not bool:
                raise ValueError("Coinset spent state is invalid")
            return observation(
                provider_id="coinset",
                capability=Capability.CHAIN_EVIDENCE,
                payload={
                    "coin_id": coin_id.lower(),
                    "spent": spent,
                    "spent_block_height": height,
                    "confirmed_block_height": exact_nonnegative_height(
                        raw.get("confirmed_block_index")
                    ),
                },
                observed_at=observed_at,
                source_height=height,
                identity_keys=(coin_id.lower(),),
                freshness_seconds=20,
                quality=ObservationQuality.VALID,
            )
        except Exception as exc:
            return failed_observation(
                provider_id="coinset",
                capability=Capability.CHAIN_EVIDENCE,
                identity_keys=(coin_id.lower(),),
                now=observed_at,
                error=exc,
                freshness_seconds=5,
            )


def _encode_chia_amount(amount: int) -> bytes:
    """Encode a nonnegative Chia amount in minimal signed CLVM form."""

    if type(amount) is not int or amount < 0:
        raise ValueError("coin amount must be a nonnegative integer")
    if amount == 0:
        return b""
    return amount.to_bytes((amount.bit_length() + 8) >> 3, "big", signed=True)
