"""Pure policy for purpose-separated authoritative coin capacity.

No function in this module reads a database, wallet, clock, or network.  It
accepts exact observations and returns deterministic fail-closed decisions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping


COIN_PURPOSES = (
    "lifecycle",
    "replacement",
    "fill_response",
    "operator_recovery",
    "top_up",
    "fee_reserve",
)
_PURPOSE_SET = frozenset(COIN_PURPOSES)
COIN_PREP_OPERATION_KINDS = ("split", "combine")
_COIN_ID_RE = re.compile(r"[0-9a-f]{64}")
_MAX_CAPACITY_COINS = 4096
_MAX_TARGET_OUTPUTS = 512


@dataclass(frozen=True, slots=True)
class CapacityDecision:
    purpose: str
    required_count: int
    required_amount_mojos: Decimal
    available_count: int
    available_amount_mojos: int
    selected_coin_ids: tuple[str, ...]
    ready: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class CoinPrepPostViewDecision:
    confirmed: bool
    reason: str | None
    output_coin_ids: tuple[str, ...]


def validate_purpose(value: Any) -> str:
    if type(value) is not str:
        raise TypeError("purpose must be an exact purpose string")
    if value not in _PURPOSE_SET:
        raise ValueError("purpose is not a recognized policy purpose")
    return value


def _canonical_coin_id(value: Any, label: str = "coin_id") -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    normalized = value[2:] if value.startswith("0x") else value
    if _COIN_ID_RE.fullmatch(normalized) is None:
        raise ValueError(f"{label} is not a canonical coin identity")
    return normalized


def _exact_nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise TypeError(f"{label} must be an exact non-negative integer")
    return value


def _required_amount(value: Any) -> Decimal:
    if type(value) is int and type(value) is not bool:
        amount = Decimal(value)
    elif type(value) is Decimal:
        amount = value
    else:
        raise TypeError("required_amount_mojos must be Decimal or an exact integer")
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise ValueError("required_amount_mojos must be a non-negative whole mojo")
    return amount


def decide_capacity(
    coins: Iterable[Mapping[str, Any]],
    *,
    purpose: str,
    required_count: int = 0,
    required_amount_mojos: Decimal | int = 0,
) -> CapacityDecision:
    """Count only exact, authoritative, spendable coins for one purpose."""

    safe_purpose = validate_purpose(purpose)
    safe_count = _exact_nonnegative_int(required_count, "required_count")
    safe_amount = _required_amount(required_amount_mojos)
    try:
        observed = tuple(coins)
    except TypeError as exc:
        raise TypeError("coins must be iterable") from exc
    if len(observed) > _MAX_CAPACITY_COINS:
        return CapacityDecision(
            safe_purpose,
            safe_count,
            safe_amount,
            0,
            0,
            (),
            False,
            "ambiguous_coin_view",
        )

    eligible: list[tuple[str, int]] = []
    seen: set[str] = set()
    ambiguous_view = False
    for raw in observed:
        if not isinstance(raw, Mapping):
            continue
        try:
            coin_id = _canonical_coin_id(raw.get("coin_id"))
        except (TypeError, ValueError):
            continue
        if coin_id in seen:
            ambiguous_view = True
            break
        seen.add(coin_id)
        amount = raw.get("amount_mojos")
        coin_purpose = raw.get("purpose")
        if (
            type(amount) is not int
            or amount < 0
            or type(coin_purpose) is not str
            or coin_purpose not in _PURPOSE_SET
            or raw.get("spendable") is not True
            or raw.get("authoritative") is not True
        ):
            continue
        if coin_purpose == safe_purpose:
            eligible.append((coin_id, amount))

    if ambiguous_view:
        return CapacityDecision(
            safe_purpose,
            safe_count,
            safe_amount,
            0,
            0,
            (),
            False,
            "ambiguous_coin_view",
        )
    eligible.sort(key=lambda item: item[0])
    available_amount = sum(amount for _coin_id, amount in eligible)
    ready = len(eligible) >= safe_count and Decimal(available_amount) >= safe_amount
    return CapacityDecision(
        safe_purpose,
        safe_count,
        safe_amount,
        len(eligible),
        available_amount,
        tuple(coin_id for coin_id, _amount in eligible),
        ready,
        None if ready else "purpose_capacity_exhausted",
    )


def _canonical_target_contract(target_contract: Any) -> dict[str, Any]:
    if type(target_contract) is not dict:
        raise TypeError("target_contract must be an exact mapping")
    wallet_type = target_contract.get("wallet_type")
    if type(wallet_type) is not str or wallet_type not in {"xch", "cat"}:
        raise ValueError("target_contract wallet_type is invalid")
    outputs = target_contract.get("outputs")
    if (
        type(outputs) is not list
        or not outputs
        or len(outputs) > _MAX_TARGET_OUTPUTS
    ):
        raise ValueError("target_contract outputs are invalid")
    canonical_outputs = []
    indexes: set[int] = set()
    for output in outputs:
        if type(output) is not dict:
            raise TypeError("target output must be an exact mapping")
        index = _exact_nonnegative_int(output.get("output_index"), "output_index")
        if index in indexes:
            raise ValueError("target output indexes must be unique")
        indexes.add(index)
        amount = _exact_nonnegative_int(output.get("amount_mojos"), "amount_mojos")
        if amount == 0:
            raise ValueError("target output amount must be positive")
        canonical_outputs.append(
            {
                "output_index": index,
                "amount_mojos": amount,
                "purpose": validate_purpose(output.get("purpose")),
            }
        )
    canonical_outputs.sort(key=lambda output: output["output_index"])
    return {"wallet_type": wallet_type, "outputs": canonical_outputs}


def canonical_coin_prep_contract(
    *,
    operation_kind: str,
    purpose: str,
    source_coin_ids: list[str],
    target_contract: dict[str, Any],
) -> dict[str, Any]:
    if type(operation_kind) is not str:
        raise TypeError("operation_kind must be an exact string")
    if operation_kind not in COIN_PREP_OPERATION_KINDS:
        raise ValueError("operation_kind must be split or combine")
    safe_purpose = validate_purpose(purpose)
    if type(source_coin_ids) is not list or not source_coin_ids:
        raise TypeError("source_coin_ids must be an exact non-empty list")
    sources = sorted(_canonical_coin_id(value, "source coin id") for value in source_coin_ids)
    if len(sources) != len(set(sources)):
        raise ValueError("source coin identities must be unique")
    target = _canonical_target_contract(target_contract)
    material = {
        "contract_version": "coin_prep_operation_v1",
        "operation_kind": operation_kind,
        "purpose": safe_purpose,
        "source_coin_ids": sources,
        "target_contract": target,
    }
    encoded = json.dumps(
        material, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    material["operation_id"] = "coin-prep:" + hashlib.sha256(
        encoded.encode("utf-8")
    ).hexdigest()
    return material


def coin_prep_operation_identity(**kwargs: Any) -> str:
    return canonical_coin_prep_contract(**kwargs)["operation_id"]


def _parse_time(value: Any) -> datetime | None:
    if type(value) is not str or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def verify_coin_prep_post_view(
    *,
    source_coin_ids: list[str],
    expected_outputs: list[dict[str, Any]],
    authoritative_view: dict[str, Any],
    expected_wallet_identity: dict[str, Any],
) -> CoinPrepPostViewDecision:
    """Verify one fresh complete wallet view against an exact effect result."""

    if type(authoritative_view) is not dict:
        return CoinPrepPostViewDecision(False, "authoritative_view_malformed", ())
    if authoritative_view.get("fresh") is not True:
        return CoinPrepPostViewDecision(False, "authoritative_view_not_fresh", ())
    if authoritative_view.get("complete") is not True:
        return CoinPrepPostViewDecision(False, "authoritative_view_incomplete", ())
    if (
        type(expected_wallet_identity) is not dict
        or type(authoritative_view.get("wallet_identity")) is not dict
        or authoritative_view["wallet_identity"] != expected_wallet_identity
    ):
        return CoinPrepPostViewDecision(False, "wallet_identity_mismatch", ())
    observed_at = _parse_time(authoritative_view.get("observed_at"))
    expires_at = _parse_time(expected_wallet_identity.get("expires_at"))
    if observed_at is not None and (expires_at is None or observed_at > expires_at):
        return CoinPrepPostViewDecision(False, "wallet_identity_expired", ())
    try:
        sources = {_canonical_coin_id(value, "source coin id") for value in source_coin_ids}
    except (TypeError, ValueError):
        return CoinPrepPostViewDecision(False, "source_coin_identity_malformed", ())
    if type(expected_outputs) is not list or not expected_outputs:
        return CoinPrepPostViewDecision(False, "expected_outputs_malformed", ())
    expected: dict[str, tuple[int, str]] = {}
    try:
        for output in expected_outputs:
            if type(output) is not dict:
                raise TypeError
            coin_id = _canonical_coin_id(output.get("coin_id"), "output coin id")
            amount = output.get("amount_mojos")
            if type(amount) is not int or amount <= 0:
                raise ValueError
            purpose = validate_purpose(output.get("purpose"))
            if coin_id in expected:
                return CoinPrepPostViewDecision(False, "duplicate_expected_output", ())
            expected[coin_id] = (amount, purpose)
    except (TypeError, ValueError):
        return CoinPrepPostViewDecision(False, "expected_outputs_malformed", ())
    coins = authoritative_view.get("coins")
    if type(coins) is not list or len(coins) > _MAX_CAPACITY_COINS:
        return CoinPrepPostViewDecision(False, "authoritative_view_malformed", ())
    observed: dict[str, tuple[Any, Any]] = {}
    for coin in coins:
        if type(coin) is not dict:
            return CoinPrepPostViewDecision(False, "authoritative_view_malformed", ())
        try:
            coin_id = _canonical_coin_id(coin.get("coin_id"))
        except (TypeError, ValueError):
            return CoinPrepPostViewDecision(False, "authoritative_view_malformed", ())
        if coin_id in observed:
            return CoinPrepPostViewDecision(False, "duplicate_coin_identity", ())
        observed[coin_id] = (coin.get("amount_mojos"), coin.get("purpose"))
    if sources.intersection(observed):
        return CoinPrepPostViewDecision(False, "source_coin_still_present", ())
    if not set(expected).issubset(observed):
        return CoinPrepPostViewDecision(False, "expected_output_missing", ())
    if any(observed[coin_id] != facts for coin_id, facts in expected.items()):
        return CoinPrepPostViewDecision(False, "expected_output_contradiction", ())
    return CoinPrepPostViewDecision(True, None, tuple(sorted(expected)))


__all__ = [
    "COIN_PURPOSES",
    "COIN_PREP_OPERATION_KINDS",
    "CapacityDecision",
    "CoinPrepPostViewDecision",
    "canonical_coin_prep_contract",
    "coin_prep_operation_identity",
    "decide_capacity",
    "validate_purpose",
    "verify_coin_prep_post_view",
]
