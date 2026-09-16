"""Server-owned economic contracts for explicit Coin Prep fee consent.

Economic approval excludes transient quotes and selected intermediate coins.
Exact per-operation effect authority remains the wallet journal's responsibility.
No function here signs or submits a wallet transaction.
"""

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import time

from replacement_capacity import COIN_PURPOSES
import database
from fee_estimation import quote_fee


MAX_ATOMIC_AMOUNT = 2**63 - 1


def _now():
    return int(time.time())


def _exact_int(value, minimum=0, maximum=MAX_ATOMIC_AMOUNT):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("fee contract requires an exact bounded integer")
    return value


def _digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("fee contract identity requires a canonical digest")
    return value


def _decimal_text(value, minimum, maximum):
    if type(value) not in (str, int, Decimal):
        raise ValueError("fee contract decimal cannot be implicitly coerced")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or not minimum <= amount <= maximum:
            raise ValueError("fee contract decimal is out of range")
        if amount == 0:
            return "0"
        text = format(amount, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    except InvalidOperation as exc:
        raise ValueError("fee contract decimal is invalid") from exc


def _closed_dict(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("fee contract has missing or unsupported fields")


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_fee_contract(scope: dict, economic_plan: dict) -> dict:
    """Bind a trusted server snapshot to deterministic wallet/economic digests.

    This validator is not an HTTP authority boundary: callers must derive scope
    and plan from the wallet/configuration, never accept them from a client.
    A standalone session is server-persisted; a campaign uses its durable ID.
    """
    _closed_dict(scope, (
        "network", "wallet_type", "wallet_fingerprint", "wallet_id",
        "xch_wallet_id", "asset_id", "ticker", "session_id", "campaign_id",
    ))
    if scope["wallet_type"] not in ("sage", "chia"):
        raise ValueError("fee contract wallet backend is unsupported")
    if type(scope["network"]) is not str or re.fullmatch(
        r"mainnet|testnet[0-9]+", scope["network"]
    ) is None:
        raise ValueError("fee contract network is invalid")
    if type(scope["ticker"]) is not str or re.fullmatch(
        r"[A-Za-z0-9_\-]{1,64}", scope["ticker"]
    ) is None:
        raise ValueError("fee contract ticker is invalid")
    _exact_int(scope["wallet_fingerprint"], 1, 2**32 - 1)
    _exact_int(scope["wallet_id"], 1)
    _exact_int(scope["xch_wallet_id"], 1)
    _digest(scope["asset_id"])
    if (scope["session_id"] is None) == (scope["campaign_id"] is None):
        raise ValueError("fee contract requires exactly one economic scope identity")
    _digest(scope["session_id"] or scope["campaign_id"])
    normalized_scope = dict(scope)

    _closed_dict(economic_plan, (
        "target_seconds", "coin_multiplier", "headroom_pct", "liquidity_mode",
        "reserve_floors_mojos", "campaign_revision", "cancellation_policy", "outputs",
    ))
    target = _exact_int(economic_plan["target_seconds"])
    multiplier = _decimal_text(economic_plan["coin_multiplier"], Decimal("0.5"), Decimal("3"))
    headroom = _decimal_text(economic_plan["headroom_pct"], Decimal("0"), Decimal("100"))
    if economic_plan["liquidity_mode"] not in ("two_sided", "buy_only", "sell_only"):
        raise ValueError("fee contract liquidity mode is invalid")
    if economic_plan["cancellation_policy"] != "protected_no_prep":
        raise ValueError("fee contract cancellation protection is required")
    reserves = economic_plan["reserve_floors_mojos"]
    _closed_dict(reserves, ("xch", "cat"))
    reserves = {asset: _exact_int(value) for asset, value in reserves.items()}
    revision = economic_plan["campaign_revision"]
    if revision is not None:
        _exact_int(revision, 0)
    outputs = economic_plan["outputs"]
    if type(outputs) is not list:
        raise ValueError("fee contract output collection is invalid")
    normalized_outputs = []
    identities = set()
    for output in outputs:
        _closed_dict(output, ("asset", "purpose", "tier_rank", "amount_mojos", "ordinal"))
        if output["asset"] not in ("xch", "cat") or output["purpose"] not in COIN_PURPOSES:
            raise ValueError("fee contract output asset or purpose is invalid")
        _exact_int(output["tier_rank"])
        _exact_int(output["amount_mojos"], 1)
        _exact_int(output["ordinal"])
        identity = (output["asset"], output["ordinal"])
        if identity in identities:
            raise ValueError("fee contract output identity is duplicated")
        identities.add(identity)
        normalized_outputs.append(dict(output))
    normalized_outputs.sort(key=lambda item: (item["asset"], item["ordinal"]))
    plan = {
        **economic_plan,
        "target_seconds": target,
        "coin_multiplier": multiplier,
        "headroom_pct": headroom,
        "reserve_floors_mojos": reserves,
        "outputs": normalized_outputs,
    }
    scope_json = _canonical_json(normalized_scope)
    plan_json = _canonical_json(plan)
    return {
        "scope": normalized_scope,
        "plan": plan,
        "scope_json": scope_json,
        "plan_json": plan_json,
        "scope_sha256": hashlib.sha256(scope_json.encode("utf-8")).hexdigest(),
        "plan_sha256": hashlib.sha256(plan_json.encode("utf-8")).hexdigest(),
    }


def estimate_coin_prep_fee_preview(
    *, scope: dict, economic_plan: dict, stages: list,
    fee_funding_mojos: int, request_options: dict,
) -> dict:
    """Price trusted server-planned stages and persist an unapproved preview.

    The planning layer supplies validated unsigned costs for available effects
    and explicit projected costs/count ranges for future stages. This function
    never creates effect claims, consent, a worker, signatures or submissions.
    HTTP/native callers must use the server collector, not supply these inputs.
    """
    contract = canonical_fee_contract(scope, economic_plan)
    funding = _exact_int(fee_funding_mojos)
    if type(request_options) is not dict or type(stages) is not list:
        raise ValueError("fee preview options/stages are invalid")
    stage_ids = set()
    # Validate the complete plan before any provider request or persistence.
    for stage in stages:
        _closed_dict(stage, (
            "stage_id", "cost", "cost_kind", "transaction_count_min",
            "transaction_count_max", "cancellation",
        ))
        if type(stage["stage_id"]) is not str or re.fullmatch(
            r"[a-z0-9_\-]{1,64}", stage["stage_id"]
        ) is None or stage["stage_id"] in stage_ids:
            raise ValueError("fee preview stage identity is invalid or duplicated")
        stage_ids.add(stage["stage_id"])
        _exact_int(stage["cost"], 1)
        lower = _exact_int(stage["transaction_count_min"], 1)
        upper = _exact_int(stage["transaction_count_max"], lower)
        if stage["cost_kind"] not in ("projected", "exact_unsigned"):
            raise ValueError("fee preview stage cost is unproven")
        if stage["cost_kind"] == "exact_unsigned" and lower != upper:
            raise ValueError("exact unsigned stage must have an exact count")
        if type(stage["cancellation"]) is not bool:
            raise ValueError("fee preview cancellation classification is invalid")
    now = _exact_int(_now())
    prep = cancel = minimum = 0
    count_min = count_max = 0
    available = True
    priced_stages = []
    observations = []
    expiries = []
    for stage in stages:
        quote = quote_fee(stage["cost"], target_seconds=contract["plan"]["target_seconds"])
        priced_stages.append({**stage, "quote": quote})
        if quote["available"] is not True:
            available = False
        else:
            fee = _exact_int(quote["fee_mojos"])
            upper_fee = _exact_int(fee * stage["transaction_count_max"])
            minimum = _exact_int(minimum + fee * stage["transaction_count_min"])
            if stage["cancellation"]:
                cancel = _exact_int(cancel + upper_fee)
            else:
                prep = _exact_int(prep + upper_fee)
            observations.append(_exact_int(quote["observed_at"]))
            expiries.append(_exact_int(quote["expires_at"]))
        if not stage["cancellation"]:
            count_min = _exact_int(count_min + stage["transaction_count_min"])
            count_max = _exact_int(count_max + stage["transaction_count_max"])
    principal = _exact_int(sum(
        output["amount_mojos"] for output in contract["plan"]["outputs"]
        if output["asset"] == "xch" and output["purpose"] == "fee_reserve"
    ))
    total = _exact_int(prep + cancel) if available else None
    # Recheck age after the last transport: a slow multistage preview must not
    # become confirmable merely because its earliest request was once fresh.
    now = _exact_int(_now())
    observed = min(observations) if available and observations else now
    expires = min(expiries) if available and expiries else now + 60
    if not observed <= now < expires:
        available = False
        total = None
        observed, expires = now, now + 60
    result = {
        "available": available,
        "reason": "network_fee_estimate" if available else "FEE_ESTIMATE_UNAVAILABLE",
        "scope_sha256": contract["scope_sha256"],
        "plan_sha256": contract["plan_sha256"],
        "wallet": contract["scope"],
        "target_seconds": contract["plan"]["target_seconds"],
        "stages": priced_stages,
        "preparation_transaction_count_min": count_min,
        "preparation_transaction_count_max": count_max,
        "estimated_preparation_fee_mojos": prep if available else None,
        "estimated_cancellation_fee_mojos": cancel if available else None,
        "estimated_total_fee_mojos": total,
        "estimated_minimum_fee_mojos": minimum if available else None,
        "suggested_maximum_fee_mojos": total,
        "fee_coin_principal_mojos": principal,
        "fee_funding_mojos": funding,
        "funded": available and total <= funding,
        "observed_at": observed,
        "expires_at": expires,
        "inclusion_is_guaranteed": False,
    }
    saved = database.store_coin_prep_fee_preview(
        scope_sha256=contract["scope_sha256"], plan_sha256=contract["plan_sha256"],
        scope_json=contract["scope_json"], plan_json=contract["plan_json"],
        request_options_json=_canonical_json(request_options),
        quote_json=_canonical_json(result), observed_at=observed, expires_at=expires,
    )
    return {**result, "preview_id": saved["preview_id"]}


def validate_fee_consent(*, approval_id: str, scope: dict, economic_plan: dict) -> dict:
    """Read consent against trusted current economics, never grant dispatch.

    The runtime collector supplies freshly verified wallet/configuration inputs;
    clients cannot supply these contracts. Quote expiry is deliberately not a
    refund or consent-expiry event. Each dispatch still needs fresh exact pricing,
    an atomic current-version reservation and the wallet effect journal fence.
    """
    contract = canonical_fee_contract(scope, economic_plan)
    context = database.get_coin_prep_fee_approval_context(_digest(approval_id))
    if (
        context["scope_sha256"] != contract["scope_sha256"]
        or context["plan_sha256"] != contract["plan_sha256"]
        or context["scope_json"] != contract["scope_json"]
        or context["plan_json"] != contract["plan_json"]
        or context["version"] != context["latest_version"]
    ):
        raise ValueError("FEE_APPROVAL_STALE")
    return {
        **database.get_fee_approval(approval_id),
        "preview_id": context["preview_id"],
        "approved_at": context["approved_at"],
        "dispatch_authorized": False,
    }
