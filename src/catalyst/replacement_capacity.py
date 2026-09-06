"""Pure policy for purpose-separated authoritative coin capacity.

No function in this module reads a database, wallet, clock, or network.  It
accepts exact observations and returns deterministic fail-closed decisions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
_CANONICAL_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")
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


@dataclass(frozen=True, slots=True)
class CoinPrepNoEffectViewDecision:
    confirmed: bool
    reason: str | None
    selectable_coin_ids: tuple[str, ...]


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
    if target_contract.get("contract_version") == 2:
        return _canonical_batch_target_contract(target_contract)
    wallet_type = target_contract.get("wallet_type")
    if type(wallet_type) is not str or wallet_type not in {"xch", "cat"}:
        raise ValueError("target_contract wallet_type is invalid")
    outputs = target_contract.get("outputs")
    if type(outputs) is not list or not outputs or len(outputs) > _MAX_TARGET_OUTPUTS:
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
    canonical_target = {"wallet_type": wallet_type, "outputs": canonical_outputs}

    # CAT operations can consume a separately selected XCH coin for their fee.
    # That cohort is part of the immutable wallet-effect contract: omitting it
    # lets a retry with a different fee reuse the same operation identity.
    if "external_fee" in target_contract:
        external_fee = target_contract.get("external_fee")
        if wallet_type != "cat" or type(external_fee) is not dict:
            raise ValueError("target_contract external fee is invalid")
        if set(external_fee) != {"fee_mojos", "coin_ids"}:
            raise ValueError("target_contract external fee fields are invalid")
        fee_mojos = _exact_nonnegative_int(
            external_fee.get("fee_mojos"), "external fee mojos"
        )
        raw_coin_ids = external_fee.get("coin_ids")
        if fee_mojos <= 0 or type(raw_coin_ids) is not list or not raw_coin_ids:
            raise ValueError("target_contract external fee is invalid")
        fee_coin_ids = sorted(
            _canonical_coin_id(value, "external fee coin id") for value in raw_coin_ids
        )
        if len(fee_coin_ids) != len(set(fee_coin_ids)):
            raise ValueError("target_contract external fee coin identities repeat")
        canonical_target["external_fee"] = {
            "fee_mojos": fee_mojos,
            "coin_ids": fee_coin_ids,
        }

    return canonical_target


def _canonical_batch_target_contract(target_contract: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize the immutable plan for one Sage final-output batch."""

    allowed = {
        "contract_version",
        "wallet_type",
        "cat_asset_id",
        "fee_mojos",
        "outputs",
        "external_fee",
        "plan_hash",
    }
    if not set(target_contract).issubset(allowed):
        raise ValueError("batch target contract fields are invalid")
    wallet_type = target_contract.get("wallet_type")
    if wallet_type not in {"xch", "cat"}:
        raise ValueError("batch target wallet type is invalid")
    fee_mojos = _exact_nonnegative_int(
        target_contract.get("fee_mojos"), "batch fee mojos"
    )
    raw_cat_asset_id = target_contract.get("cat_asset_id")
    if wallet_type == "cat":
        cat_asset_id = _canonical_coin_id(raw_cat_asset_id, "CAT asset id")
    elif raw_cat_asset_id not in {None, ""}:
        raise ValueError("XCH batch cannot carry a CAT asset id")
    else:
        cat_asset_id = None

    outputs = target_contract.get("outputs")
    if type(outputs) is not list or not outputs or len(outputs) > 128:
        raise ValueError("batch target outputs are invalid")
    canonical_outputs = []
    indexes: set[int] = set()
    identities: set[tuple[str, int]] = set()
    for output in outputs:
        if type(output) is not dict or set(output) != {
            "output_index",
            "asset",
            "address",
            "amount_mojos",
            "purpose",
            "ordinal",
        }:
            raise ValueError("batch target output fields are invalid")
        index = _exact_nonnegative_int(output.get("output_index"), "output_index")
        asset = output.get("asset")
        address = output.get("address")
        amount = _exact_nonnegative_int(output.get("amount_mojos"), "amount_mojos")
        ordinal = output.get("ordinal")
        if (
            index in indexes
            or asset not in {"xch", "cat"}
            or type(address) is not str
            or not address
            or len(address) > 256
            or amount <= 0
            or type(ordinal) is not int
            or ordinal < -1
            or (asset, ordinal) in identities
        ):
            raise ValueError("batch target output is invalid or repeated")
        indexes.add(index)
        identities.add((asset, ordinal))
        canonical_outputs.append(
            {
                "output_index": index,
                "asset": asset,
                "address": address,
                "amount_mojos": amount,
                "purpose": validate_purpose(output.get("purpose")),
                "ordinal": ordinal,
            }
        )
    canonical_outputs.sort(key=lambda output: output["output_index"])
    if [output["output_index"] for output in canonical_outputs] != list(
        range(len(canonical_outputs))
    ):
        raise ValueError("batch target output indexes must be contiguous")

    canonical = {
        "contract_version": 2,
        "wallet_type": wallet_type,
        "cat_asset_id": cat_asset_id,
        "fee_mojos": fee_mojos,
        "outputs": canonical_outputs,
    }
    external_fee = target_contract.get("external_fee")
    if external_fee is not None:
        if wallet_type != "cat" or type(external_fee) is not dict:
            raise ValueError("batch external fee is invalid")
        if set(external_fee) != {"fee_mojos", "coin_ids"}:
            raise ValueError("batch external fee fields are invalid")
        external_fee_mojos = _exact_nonnegative_int(
            external_fee.get("fee_mojos"), "batch external fee mojos"
        )
        raw_ids = external_fee.get("coin_ids")
        if (
            external_fee_mojos <= 0
            or external_fee_mojos != fee_mojos
            or type(raw_ids) is not list
            or not raw_ids
        ):
            raise ValueError("batch external fee is invalid")
        coin_ids = sorted(_canonical_coin_id(value) for value in raw_ids)
        if len(coin_ids) != len(set(coin_ids)):
            raise ValueError("batch external fee coin identities repeat")
        canonical["external_fee"] = {
            "fee_mojos": external_fee_mojos,
            "coin_ids": coin_ids,
        }
    elif wallet_type == "cat" and fee_mojos:
        raise ValueError("CAT batch fee requires an external fee contract")

    encoded = json.dumps(
        canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    plan_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    supplied_hash = target_contract.get("plan_hash")
    if supplied_hash is not None and supplied_hash != plan_hash:
        raise ValueError("batch target plan hash differs")
    canonical["plan_hash"] = plan_hash
    return canonical


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
    sources = sorted(
        _canonical_coin_id(value, "source coin id") for value in source_coin_ids
    )
    if len(sources) != len(set(sources)):
        raise ValueError("source coin identities must be unique")
    target = _canonical_target_contract(target_contract)
    material = {
        "contract_version": (
            "coin_prep_operation_v2"
            if target.get("contract_version") == 2
            else "coin_prep_operation_v1"
        ),
        "operation_kind": operation_kind,
        "purpose": safe_purpose,
        "source_coin_ids": sources,
        "target_contract": target,
    }
    encoded = json.dumps(
        material, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    material["operation_id"] = (
        "coin-prep:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    )
    return material


def coin_prep_operation_identity(**kwargs: Any) -> str:
    return canonical_coin_prep_contract(**kwargs)["operation_id"]


def _canonical_utc_time(value: Any) -> datetime:
    if (
        type(value) is not str
        or len(value) != 27
        or _CANONICAL_UTC_RE.fullmatch(value) is None
    ):
        raise ValueError("timestamp is not canonical bounded UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("timestamp is not canonical bounded UTC") from exc
    if parsed.tzinfo is not timezone.utc:
        parsed = parsed.astimezone(timezone.utc)
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        raise ValueError("timestamp is not canonical bounded UTC")
    return parsed


def _canonical_wallet_identity(value: Any) -> dict[str, Any] | None:
    if type(value) is not dict:
        return None
    try:
        import mutation_gate

        binding = mutation_gate.WalletIdentityBinding(**value)
        payload = mutation_gate.wallet_identity_binding_payload(binding)
    except (TypeError, ValueError):
        return None
    return payload if payload == value else None


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
    expected_identity = _canonical_wallet_identity(expected_wallet_identity)
    observed_identity = _canonical_wallet_identity(
        authoritative_view.get("wallet_identity")
    )
    if expected_identity is None or observed_identity is None:
        return CoinPrepPostViewDecision(False, "wallet_identity_malformed", ())
    if observed_identity != expected_identity:
        return CoinPrepPostViewDecision(False, "wallet_identity_mismatch", ())
    try:
        observed_at = _canonical_utc_time(authoritative_view.get("observed_at"))
        expires_at = _canonical_utc_time(authoritative_view.get("expires_at"))
        bound_at = _canonical_utc_time(expected_identity["bound_at_utc"])
    except ValueError:
        return CoinPrepPostViewDecision(False, "authoritative_view_time_malformed", ())
    authoritative_expiry = observed_at + timedelta(
        seconds=expected_identity["maximum_age_seconds"]
    )
    if expires_at != authoritative_expiry:
        return CoinPrepPostViewDecision(False, "authoritative_view_time_malformed", ())
    if observed_at <= bound_at:
        return CoinPrepPostViewDecision(False, "wallet_identity_expired", ())
    try:
        sources = {
            _canonical_coin_id(value, "source coin id") for value in source_coin_ids
        }
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


def verify_coin_prep_no_effect_view(
    *,
    source_coin_ids: list[str],
    fee_coin_ids: list[str],
    authoritative_view: dict[str, Any],
    expected_wallet_identity: dict[str, Any],
) -> CoinPrepNoEffectViewDecision:
    """Prove that a submitted prep effect left its exact input cohort untouched."""

    denied = lambda reason: CoinPrepNoEffectViewDecision(False, reason, ())
    if type(authoritative_view) is not dict or set(authoritative_view) != {
        "fresh",
        "complete",
        "wallet_identity",
        "observed_at",
        "expires_at",
        "selectable_coin_ids",
        "pending_transaction_ids",
    }:
        return denied("authoritative_view_malformed")
    if authoritative_view.get("fresh") is not True:
        return denied("authoritative_view_not_fresh")
    if authoritative_view.get("complete") is not True:
        return denied("authoritative_view_incomplete")
    expected_identity = _canonical_wallet_identity(expected_wallet_identity)
    observed_identity = _canonical_wallet_identity(
        authoritative_view.get("wallet_identity")
    )
    if expected_identity is None or observed_identity is None:
        return denied("wallet_identity_malformed")
    if observed_identity != expected_identity:
        return denied("wallet_identity_mismatch")
    try:
        observed_at = _canonical_utc_time(authoritative_view.get("observed_at"))
        expires_at = _canonical_utc_time(authoritative_view.get("expires_at"))
        bound_at = _canonical_utc_time(expected_identity["bound_at_utc"])
    except ValueError:
        return denied("authoritative_view_time_malformed")
    if expires_at != observed_at + timedelta(
        seconds=expected_identity["maximum_age_seconds"]
    ):
        return denied("authoritative_view_time_malformed")
    if observed_at <= bound_at:
        return denied("wallet_identity_expired")
    if type(source_coin_ids) is not list or not source_coin_ids:
        return denied("source_coin_identity_malformed")
    if type(fee_coin_ids) is not list:
        return denied("fee_coin_identity_malformed")
    try:
        sources = [
            _canonical_coin_id(value, "source coin id") for value in source_coin_ids
        ]
        fees = [_canonical_coin_id(value, "fee coin id") for value in fee_coin_ids]
    except (TypeError, ValueError):
        return denied("input_coin_identity_malformed")
    cohort = sorted(set(sources) | set(fees))
    if len(sources) != len(set(sources)) or len(fees) != len(set(fees)):
        return denied("duplicate_input_coin_identity")
    selectable = authoritative_view.get("selectable_coin_ids")
    if type(selectable) is not list or len(selectable) > _MAX_CAPACITY_COINS:
        return denied("selectable_cohort_malformed")
    try:
        normalized_selectable = [
            _canonical_coin_id(value, "selectable coin id") for value in selectable
        ]
    except (TypeError, ValueError):
        return denied("selectable_cohort_malformed")
    if normalized_selectable != cohort:
        return denied("selectable_cohort_mismatch")
    pending = authoritative_view.get("pending_transaction_ids")
    if type(pending) is not list:
        return denied("pending_transaction_view_malformed")
    if pending:
        return denied("pending_transaction_still_present")
    return CoinPrepNoEffectViewDecision(True, None, tuple(cohort))


__all__ = [
    "COIN_PURPOSES",
    "COIN_PREP_OPERATION_KINDS",
    "CapacityDecision",
    "CoinPrepNoEffectViewDecision",
    "CoinPrepPostViewDecision",
    "canonical_coin_prep_contract",
    "coin_prep_operation_identity",
    "decide_capacity",
    "validate_purpose",
    "verify_coin_prep_no_effect_view",
    "verify_coin_prep_post_view",
]
