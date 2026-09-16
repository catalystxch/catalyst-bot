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


_IDENTITY_FIELDS = (
    "network", "wallet_type", "wallet_fingerprint", "wallet_id",
    "xch_wallet_id", "asset_id", "ticker",
)


def _canonical_fee_identity(scope: dict) -> dict:
    """Validate the closed trusted wallet identity before persisting a session."""
    _closed_dict(scope, _IDENTITY_FIELDS)
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
    return dict(scope)


def resolve_server_fee_scope(*, identity: dict, campaign_id: str | None = None) -> dict:
    """Resolve durable ownership from trusted identity, never client authority.

    Refresh and restart reuse a standalone session; campaigns retain their
    existing durable identity. This does not create approval or wallet effects.
    Session completion/new-generation transitions remain a separate open gate.
    """
    identity = _canonical_fee_identity(identity)
    if campaign_id is not None:
        return {**identity, "campaign_id": _digest(campaign_id), "session_id": None}
    session = database.get_or_create_coin_prep_fee_session(identity_json=_canonical_json(identity))
    return {**identity, "campaign_id": None, "session_id": session["session_id"]}


def canonical_fee_contract(scope: dict, economic_plan: dict) -> dict:
    """Bind a trusted server snapshot to deterministic wallet/economic digests.

    This validator is not an HTTP authority boundary: callers must derive scope
    and plan from the wallet/configuration, never accept them from a client.
    A standalone session is server-persisted; a campaign uses its durable ID.
    """
    _closed_dict(scope, (*_IDENTITY_FIELDS, "session_id", "campaign_id"))
    _canonical_fee_identity({key: scope[key] for key in _IDENTITY_FIELDS})
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
    stage_quotes: dict | None = None,
    stage_profiles: dict | None = None,
) -> dict:
    """Price trusted server-planned stages and persist an unapproved preview.

    The planning layer supplies validated unsigned costs for available effects
    and explicit projected costs/count ranges for future stages. This function
    never creates effect claims, consent, a worker, signatures or submissions.
    HTTP/native callers must use the server collector, not supply these inputs.
    A collector can preserve a batch's cost/fee-consistent quote in stage_quotes;
    replacing that quote would sever its relationship to the inspected effect.
    Preserved guidance is revalidated, not refreshed or used as dispatch consent.
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
        lower = _exact_int(stage["transaction_count_min"], 0 if stage["cost_kind"] == "projected" else 1)
        upper = _exact_int(stage["transaction_count_max"], max(1, lower))
        if stage["cost_kind"] not in ("projected", "exact_unsigned"):
            raise ValueError("fee preview stage cost is unproven")
        if stage["cost_kind"] == "exact_unsigned" and lower != upper:
            raise ValueError("exact unsigned stage must have an exact count")
        if type(stage["cancellation"]) is not bool:
            raise ValueError("fee preview cancellation classification is invalid")
    if stage_quotes is None:
        stage_quotes = {}
    if type(stage_quotes) is not dict or not set(stage_quotes) <= stage_ids:
        raise ValueError("fee preview matched quotes have unsupported stage identities")
    if stage_profiles is None:
        stage_profiles = {}
    if type(stage_profiles) is not dict or not set(stage_profiles) <= stage_ids:
        raise ValueError("fee preview profiles have unsupported stage identities")
    for profile in stage_profiles.values():
        _closed_dict(profile, ("input_count_max", "output_count_max",
                               "ephemeral_spend_count_max", "assumptions"))
        for key in ("input_count_max", "output_count_max", "ephemeral_spend_count_max"):
            _exact_int(profile[key], 0, 10000)
        if (type(profile["assumptions"]) is not list or len(profile["assumptions"]) > 16
                or any(type(a) is not str or re.fullmatch(r"[a-z0-9_]{1,64}", a) is None
                       for a in profile["assumptions"])):
            raise ValueError("fee preview profile assumptions are invalid")
    now = _exact_int(_now())
    prep = cancel = minimum = 0
    count_min = count_max = 0
    available = True
    priced_stages = []
    observations = []
    expiries = []
    from coin_prep_fee_pricing import is_current_fee_quote

    for stage in stages:
        quote = (stage_quotes[stage["stage_id"]] if stage["stage_id"] in stage_quotes else
                 quote_fee(stage["cost"], target_seconds=contract["plan"]["target_seconds"]))
        if not is_current_fee_quote(
            quote, stage["cost"], contract["plan"]["target_seconds"], now=_now(),
        ):
            # Invalid matched guidance must not fall back to a different quote.
            # Do not persist a malformed usable fee or untrusted extra fields.
            quote = {"available": False, "reason": "FEE_ESTIMATE_UNAVAILABLE",
                     "fee_mojos": None}
        else:
            quote = {key: quote[key] for key in (
                "available", "source", "cost", "target_seconds", "fee_mojos",
                "observed_at", "expires_at",
            )}
            quote["reason"] = "network_fee_estimate"
            quote["fee_xch"] = format(Decimal(quote["fee_mojos"]) / Decimal(10**12), "f")
        priced = {**stage, "quote": quote}
        if stage["stage_id"] in stage_profiles:
            priced["profile"] = stage_profiles[stage["stage_id"]]
        priced_stages.append(priced)
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


def preview_coin_prep_fees(request_options: dict) -> dict:
    """Derive the complete read-only preview from trusted runtime state.

    Client inputs are choices only. No worker, consent, journal, fee reservation
    or wallet effect is created; persisted previews and session ownership do not
    authorize spending. Every dispatch still needs a fresh exact transaction.
    """
    from coin_prep_fee_runtime import read_staged_prep_fee_snapshot

    context = read_staged_prep_fee_snapshot(request_options, quote_provider=quote_fee)
    if context["available"] is not True:
        return {"available": False, "reason": context["reason"], "dispatch_authorized": False}
    campaign = context["campaign"]
    scope = resolve_server_fee_scope(identity=context["identity"],
                                    campaign_id=campaign["campaign_id"] if campaign else None)
    result = estimate_coin_prep_fee_preview(
        scope=scope, economic_plan=context["recipe"]["economic_plan"],
        stages=context["stages"], stage_quotes=context["stage_quotes"],
        stage_profiles=context["stage_profiles"],
        fee_funding_mojos=context["funding"]["fee_funding_mojos"],
        request_options=context["request_options"],
    )
    return {**result, "dispatch_authorized": False}


def approve_coin_prep_fees(
    *, preview_id: str, maximum_fee_mojos: int, cancellation_reserve_mojos: int,
) -> dict:
    """Record deliberate confirmation against fresh server-owned economics.

    Only the persisted preview supplies choices and its standalone session ID.
    Current wallet/asset/campaign/outputs and retained funding are read again;
    caller hashes, plans, costs or balances are never accepted. This creates
    consent only, not a fee hold, effect claim, worker or dispatch permission.
    """
    _digest(preview_id)
    _exact_int(maximum_fee_mojos)
    _exact_int(cancellation_reserve_mojos)
    if cancellation_reserve_mojos > maximum_fee_mojos:
        raise ValueError("FEE_BUDGET_INSUFFICIENT")
    preview = database.get_coin_prep_fee_preview(preview_id)
    persisted = canonical_fee_contract(
        json.loads(preview["scope_json"]), json.loads(preview["plan_json"])
    )
    if persisted["scope"]["session_id"] is not None:
        session = database.get_coin_prep_fee_session(persisted["scope"]["session_id"])
        identity_json = _canonical_json({key: persisted["scope"][key] for key in _IDENTITY_FIELDS})
        if (session["current_session_id"] != persisted["scope"]["session_id"]
                or session["identity_json"] != identity_json):
            raise ValueError("FEE_APPROVAL_STALE")
    from coin_prep_fee_funding import prepare_fee_inventory
    from coin_prep_fee_runtime import read_fee_economic_snapshot

    context = read_fee_economic_snapshot(json.loads(preview["request_options_json"]))
    campaign = context["campaign"]
    if (campaign is None) != (persisted["scope"]["campaign_id"] is None):
        raise ValueError("FEE_APPROVAL_STALE")
    scope = {**context["identity"],
             "campaign_id": campaign["campaign_id"] if campaign is not None else None,
             "session_id": persisted["scope"]["session_id"] if campaign is None else None}
    current = canonical_fee_contract(scope, context["recipe"]["economic_plan"])
    if any(current[key] != preview[key] for key in (
            "scope_sha256", "plan_sha256", "scope_json", "plan_json")):
        raise ValueError("FEE_APPROVAL_STALE")
    funding = prepare_fee_inventory(
        context["snapshot"], context["recipe"]["targets"],
        current["plan"]["reserve_floors_mojos"],
    )
    result = database.approve_coin_prep_fee_preview(
        preview_id=preview_id, scope_sha256=current["scope_sha256"],
        plan_sha256=current["plan_sha256"], maximum_fee_mojos=maximum_fee_mojos,
        cancellation_reserve_mojos=cancellation_reserve_mojos,
        current_fee_funding_mojos=funding["fee_funding_mojos"],
        current_principal_funded=funding["principal_funded"],
    )
    return {**result, "dispatch_authorized": False}


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
