"""Server-owned, non-mutating runtime inputs for Coin Prep fee previews.

Inventory is selectable-only and complete or unavailable. No configured asset
fallback, balance-as-inventory assumption, claims, signing or prep launch occurs.
Economic recipes use the shared worker sizing. Staged cost/funding collection
and HTTP/native integration follow this boundary.
"""

import os
import re
import json

from coin_prep_batch_plan import CoinSnapshot, SelectableCoin
from config import cfg
import database
from sage_offer_wire import decode_wallet_puzzle_hash
import wallet


_PAGE_SIZE = 500
_MAX_COIN_PAGES = 20
_CONTEXT_KEYS = (
    "WALLET_TYPE", "CAT_WALLET_ID", "WALLET_ID_XCH", "CAT_ASSET_ID",
    "CAT_TICKER_ID", "CAT_DECIMALS", "SAGE_FINGERPRINT", "WALLET_EXPECTED_NAME",
    "WALLET_EXPECTED_KEY_KIND", "XCH_RESERVE", "CAT_RESERVE", "TIER_ENABLED",
    "BUY_LADDER_REVERSED", "LIQUIDITY_MODE", "MAX_ACTIVE_BUY_OFFERS",
    "MAX_ACTIVE_SELL_OFFERS", "DEFAULT_TRADE_XCH", "COIN_PREP_HEADROOM_PCT",
    "SPREAD_BPS", "MIN_EDGE_BPS", "FEE_POOL_ENABLED", "FEE_PREP_COUNT",
    "FEE_COIN_SIZE_XCH", "BUY_INNER_SIZE_XCH", "BUY_MID_SIZE_XCH",
    "BUY_OUTER_SIZE_XCH", "BUY_EXTREME_SIZE_XCH", "SELL_INNER_SIZE_XCH",
    "SELL_MID_SIZE_XCH", "SELL_OUTER_SIZE_XCH", "SELL_EXTREME_SIZE_XCH",
    "INNER_SIZE_XCH", "MID_SIZE_XCH", "OUTER_SIZE_XCH", "EXTREME_SIZE_XCH",
    "TRANSACTION_FEE_MODE", "TRANSACTION_FEE_XCH", "MINIMUM_PROFIT_XCH",
    "EXPECTED_CANCEL_REQUOTES",
) + tuple(f"{side}_{tier}_TIER{suffix}_COUNT" for side in ("BUY", "SELL")
          for tier in ("INNER", "MID", "OUTER", "EXTREME") for suffix in ("", "_SPARE"))


def _configuration() -> dict:
    return {**{key: getattr(cfg, key, None) for key in _CONTEXT_KEYS},
            "network": os.environ.get("CATALYST_NETWORK_ID") or os.environ.get("CHIA_NETWORK") or "mainnet"}


def _hex(value) -> str:
    if type(value) is not str or re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", value) is None:
        raise ValueError("noncanonical coin identity")
    return value.removeprefix("0x").lower()


def _amount(value) -> int:
    if type(value) is str and re.fullmatch(r"[1-9][0-9]{0,18}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError("invalid atomic coin amount")
    return value


def _verified_identity(config: dict) -> dict:
    raw = wallet.get_wallet_identity()
    fp = config["SAGE_FINGERPRINT"]
    if (type(raw) is not dict or raw.get("success") is not True
            or raw.get("backend") != "sage" or config["WALLET_TYPE"] != "sage"
            or raw.get("has_secrets") is not True
            or type(raw.get("fingerprint")) is not int or not 1 <= raw["fingerprint"] <= 2**32 - 1
            or type(fp) is not str or not re.fullmatch(r"[1-9][0-9]{0,9}", fp)
            or int(fp) != raw["fingerprint"]
            or raw.get("network_id") != config["network"]
            or not re.fullmatch(r"mainnet|testnet[0-9]+", config["network"])
            or (config["WALLET_EXPECTED_NAME"] and config["WALLET_EXPECTED_NAME"] != raw.get("name"))
            or (config["WALLET_EXPECTED_KEY_KIND"] and config["WALLET_EXPECTED_KEY_KIND"] != raw.get("kind"))):
        raise ValueError("FEE_WALLET_IDENTITY_UNAVAILABLE")
    return {"network": raw["network_id"], "wallet_type": "sage", "wallet_fingerprint": raw["fingerprint"]}


def _succeeded(result) -> bool:
    # Native Sage read schemas need not include success=true; require the exact
    # expected collection independently, and never accept explicit errors.
    return (type(result) is dict and result.get("success", True) is True
            and not result.get("error") and not result.get("error_message")
            and result.get("status") not in ("error", "failed", "failure"))


def _selectable_inventory(asset_id: str | None, network: str) -> list[dict]:
    rows, seen = [], set()
    total, previous_id = None, ""
    for page in range(_MAX_COIN_PAGES):
        response = wallet.rpc("get_coins", {
            "asset_id": asset_id, "offset": page * _PAGE_SIZE, "limit": _PAGE_SIZE,
            "sort_mode": "coin_id", "filter_mode": "selectable", "ascending": True,
        }, timeout=15)
        if not _succeeded(response) or type(response.get("coins")) is not list:
            raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")
        values = response["coins"]
        reported = response.get("total")
        if (type(reported) is not int or not 0 <= reported <= _PAGE_SIZE * _MAX_COIN_PAGES
                or (total is not None and reported != total)):
            raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")
        total = reported
        if len(values) != min(_PAGE_SIZE, total - len(rows)):
            raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")
        try:
            for raw in values:
                amount = _amount(raw["amount"])
                coin_id = _hex(raw["coin_id"])
                # Sage v0.13 CoinRecord exposes the P2 address, not the raw coin
                # parent/outer puzzle. Executable inspection later proves those
                # fields; do not invent them or call this inventory effect proof.
                decode_wallet_puzzle_hash(raw["address"])
                prefix = "xch1" if network == "mainnet" else "txch1"
                if (coin_id in seen or coin_id <= previous_id or not raw["address"].startswith(prefix)
                        or raw["offer_id"] is not None or raw["spent_height"] is not None
                        or raw["spent_timestamp"] is not None
                        or raw.get("spent", False) is not False or raw.get("pending", False) is not False
                        or (raw.get("asset_id") is not None and _hex(raw["asset_id"]) != asset_id)):
                    raise ValueError("inconsistent selectable coin")
                seen.add(coin_id)
                previous_id = coin_id
                rows.append({"coin_id": coin_id, "amount_mojos": amount})
        except (KeyError, TypeError, ValueError):
            raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE") from None
        if len(rows) == total:
            return rows
    raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")


def read_fee_wallet_snapshot() -> dict:
    """Derive fresh trusted identity, exact asset and complete coin inventory."""
    config = _configuration()
    identity = _verified_identity(config)
    try:
        asset_id = _hex(config["CAT_ASSET_ID"])
        if (config["CAT_ASSET_ID"] != asset_id
                or type(config["CAT_WALLET_ID"]) is not int or config["CAT_WALLET_ID"] != 2
                or type(config["WALLET_ID_XCH"]) is not int or config["WALLET_ID_XCH"] != 1
                or type(config["CAT_DECIMALS"]) is not int or not 0 <= config["CAT_DECIMALS"] <= 18
                or type(config["CAT_TICKER_ID"]) is not str
                or re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", config["CAT_TICKER_ID"]) is None):
            raise ValueError("invalid configured asset scope")
        metadata = wallet.get_cat_metadata_snapshot()
        if not _succeeded(metadata) or type(metadata.get("cats")) is not list:
            raise ValueError("missing actual CAT metadata")
        matching = []
        for cat in metadata["cats"]:
            if type(cat) is not dict or "asset_id" not in cat:
                raise ValueError("malformed token metadata")
            # Sage's TokenRecord represents the native asset with null.
            if cat["asset_id"] is not None and _hex(cat["asset_id"]) == asset_id:
                matching.append(cat)
        if (len(matching) != 1 or type(matching[0].get("precision")) is not int
                or matching[0]["precision"] != config["CAT_DECIMALS"]):
            raise ValueError("actual CAT missing or ambiguous")
    except (KeyError, TypeError, ValueError):
        raise ValueError("FEE_WALLET_ASSET_UNAVAILABLE") from None
    observed = {asset: _selectable_inventory(aid, identity["network"])
                for asset, aid in (("xch", None), ("cat", asset_id))}
    address = wallet.get_next_address(config["WALLET_ID_XCH"], new_address=False)
    if not _succeeded(address) or type(address.get("address")) is not str:
        raise ValueError("FEE_WALLET_ADDRESS_UNAVAILABLE")
    try:
        decode_wallet_puzzle_hash(address["address"])
        prefix = "xch1" if identity["network"] == "mainnet" else "txch1"
        if not address["address"].startswith(prefix):
            raise ValueError("network address mismatch")
    except ValueError:
        raise ValueError("FEE_WALLET_ADDRESS_UNAVAILABLE") from None
    if config != _configuration():
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    try:
        after = _verified_identity(config)
    except ValueError:
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED") from None
    if after != identity:
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    ids = [row["coin_id"] for rows in observed.values() for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("FEE_WALLET_INVENTORY_UNAVAILABLE")
    reconciliation = set(database.get_coin_reconciliation_protected_ids(ids))
    coins = []
    for asset, rows in observed.items():
        reserves = {_hex(row["coin_id"]) for row in database.get_reserve_coins(asset)}
        for row in rows:
            protected = row["coin_id"] in reserves or row["coin_id"] in reconciliation
            purpose = ("protected" if row["coin_id"] in reconciliation
                       else "reserve" if row["coin_id"] in reserves else "")
            coins.append(SelectableCoin(asset, row["coin_id"], row["amount_mojos"],
                                        purpose, True, protected))
    return {"identity": {**identity, "wallet_id": config["CAT_WALLET_ID"],
                         "xch_wallet_id": config["WALLET_ID_XCH"], "asset_id": asset_id,
                         "ticker": config["CAT_TICKER_ID"]},
            "configuration": config, "receive_address": address["address"],
            "snapshot": CoinSnapshot(tuple(coins))}


def read_fee_economic_snapshot(request_options: dict) -> dict:
    """Read a current trusted wallet/configuration/campaign economic recipe.

    This boundary creates no approval, effect claim or spending authority. The
    preview service still needs exact staged inspection, fresh quotes and funding;
    execution must consume the frozen outputs instead of regenerating sizes.
    """
    from coin_prep_economics import (
        build_exact_prep_economics, build_standard_prep_economics, normalize_fee_prep_options,
        validate_fee_pool_configuration,
    )

    options = normalize_fee_prep_options(request_options)
    context = read_fee_wallet_snapshot()
    config, identity = context["configuration"], context["identity"]
    from blueprints.coin_prep import _active_bootstrap_coin_prep_context
    from tx_fees import get_fee_pool_plan
    import api_server

    validate_fee_pool_configuration(config)
    fee_pool = get_fee_pool_plan()
    bootstrap = _active_bootstrap_coin_prep_context(options)
    campaign = None
    if bootstrap is not None:
        campaign = bootstrap["campaign"]
        if (type(campaign) is not dict or campaign.get("status") != "active"
                or campaign.get("network") != identity["network"]
                or campaign.get("wallet_type") != identity["wallet_type"]
                or campaign.get("wallet_fingerprint") != identity["wallet_fingerprint"]
                or campaign.get("wallet_id") != identity["wallet_id"]
                or campaign.get("asset_id") != identity["asset_id"]):
            raise ValueError("FEE_PREP_CAMPAIGN_UNAVAILABLE")
        if options["coin_multiplier"] != "1":
            raise ValueError("FEE_PREP_CAMPAIGN_MULTIPLIER_UNSUPPORTED")
        recipe = build_exact_prep_economics(configuration=config, worker_args=bootstrap["worker_args"],
                                            campaign_revision=campaign["revision"],
                                            target_seconds=options["target_seconds"])
    else:
        if "bootstrap_campaign_id" in options:
            raise ValueError("FEE_PREP_CAMPAIGN_UNAVAILABLE")
        recipe = build_standard_prep_economics(configuration=config, fee_pool=fee_pool,
                                               live_price=api_server._get_live_mid_price_str(),
                                               coin_multiplier=options["coin_multiplier"],
                                               target_seconds=options["target_seconds"])
    if config != _configuration() or fee_pool != get_fee_pool_plan():
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    try:
        after = _verified_identity(config)
    except ValueError:
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED") from None
    if any(after[key] != identity[key] for key in after):
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    if campaign is not None and database.get_bootstrap_campaign(campaign["campaign_id"]) != campaign:
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    return {**context, "recipe": recipe, "campaign": campaign,
            "request_options": options, "fee_pool": fee_pool, "dispatch_authorized": False}


def read_approved_prep_fee_snapshot(approval_id: str) -> dict:
    """Read fresh selectable inventory under immutable approved economics.

    A later price or an expected change in source inventory cannot resize the
    approved targets. This does NOT prove intermediate transaction completion,
    price a bundle, claim inputs or authorize signing. Dispatch must inspect its
    exact executable effect, use authoritative operation evidence and reserve
    its fresh final fee. Changed configuration/identity/address/campaign requires
    new consent rather than silently substituting a new recipe.
    """
    from coin_prep_fee_approval import canonical_fee_contract, validate_fee_consent
    from coin_prep_fee_execution import encode_execution_configuration, validate_execution_context

    consent = database.get_coin_prep_fee_approval_context(approval_id)
    approved = canonical_fee_contract(json.loads(consent["scope_json"]), json.loads(consent["plan_json"]))
    if any(approved[key] != consent[key] for key in (
            "scope_sha256", "plan_sha256", "scope_json", "plan_json")):
        raise ValueError("FEE_APPROVAL_STALE")
    if consent["version"] != consent["latest_version"]:
        raise ValueError("FEE_APPROVAL_STALE")
    binding = json.loads(consent["quote_json"]).get("execution_context")
    if binding is None:
        raise ValueError("FEE_EXECUTION_CONTEXT_REQUIRED")
    recipe = validate_execution_context(binding, approved["scope"], approved["plan"])
    if encode_execution_configuration(_configuration()) != binding["configuration"]:
        raise ValueError("FEE_APPROVAL_STALE")
    context = read_fee_wallet_snapshot()
    scope = approved["scope"]
    if (any(context["identity"][key] != scope[key] for key in context["identity"])
            or encode_execution_configuration(context["configuration"]) != binding["configuration"]
            or context["receive_address"] != binding["receive_address"]):
        raise ValueError("FEE_APPROVAL_STALE")
    campaign = None
    if scope["session_id"] is not None:
        session = database.get_coin_prep_fee_session(scope["session_id"])
        identity_json = json.dumps(context["identity"], sort_keys=True, separators=(",", ":"))
        if (session["current_session_id"] != scope["session_id"] or session["identity_json"] != identity_json
                or database.list_active_bootstrap_campaigns_for_asset(scope["asset_id"])):
            raise ValueError("FEE_APPROVAL_STALE")
    else:
        campaign = database.get_bootstrap_campaign(scope["campaign_id"])
        if (type(campaign) is not dict or campaign.get("status") != "active"
                or campaign.get("revision") != approved["plan"]["campaign_revision"]
                or any(campaign.get(key) != scope[key] for key in (
                    "network", "wallet_type", "wallet_fingerprint", "wallet_id", "asset_id"))):
            raise ValueError("FEE_APPROVAL_STALE")
    # A version change during wallet reads must not leave stale consent usable.
    approval = validate_fee_consent(approval_id=approval_id, scope=scope, economic_plan=approved["plan"])
    if encode_execution_configuration(_configuration()) != binding["configuration"]:
        raise ValueError("FEE_APPROVAL_STALE")
    return {**context, "recipe": recipe, "campaign": campaign, "scope": scope,
            "request_options": json.loads(consent["request_options_json"]),
            "approval": approval, "dispatch_authorized": False}


def read_next_prep_fee_snapshot(request_options: dict) -> dict:
    """Collect retained funding and fresh exact cost/fee evidence for next batch.

    This internal read-only input is not a full multistage preview/approval API.
    Later stages still need honest projected costs/counts and cancellation cover;
    no caller receives a consent, reservation or dispatch permission here.
    """
    from coin_prep_fee_funding import prepare_fee_inventory
    from coin_prep_fee_pricing import is_current_fee_quote, price_next_prep_batch

    context = read_fee_economic_snapshot(request_options)
    recipe = context["recipe"]
    floors = recipe["economic_plan"]["reserve_floors_mojos"]
    funding = prepare_fee_inventory(context["snapshot"], recipe["targets"], floors)
    if funding["principal_funded"] is not True:
        return {**context, "funding": funding, "available": False,
                "reason": "FEE_PREP_PRINCIPAL_UNFUNDED", "dispatch_authorized": False}
    pricing = price_next_prep_batch(
        snapshot=funding["snapshot"], targets=recipe["targets"], reserve_floors=floors,
        receive_address=context["receive_address"], cat_asset_id=context["identity"]["asset_id"],
        target_seconds=recipe["economic_plan"]["target_seconds"],
    )
    # Re-read actual inventory/protection, not just a total or configuration flag.
    # A slow unsigned build/quote cannot leave a changed economic context usable.
    try:
        after = read_fee_economic_snapshot(context["request_options"])
    except ValueError:
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED") from None
    if any(after[key] != context[key] for key in (
            "identity", "configuration", "receive_address", "snapshot", "recipe", "campaign", "fee_pool")):
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    if pricing["available"] is True and pricing["transaction_required"] is True:
        if pricing["plan"].fee_mojos > funding["fee_funding_mojos"]:
            return {**context, "funding": funding, "available": False,
                    "reason": "FEE_PREP_FUNDING_INSUFFICIENT", "dispatch_authorized": False}
        if not is_current_fee_quote(pricing["quote"], pricing["inspection"]["cost"],
                                    recipe["economic_plan"]["target_seconds"]):
            return {**context, "funding": funding, "available": False,
                    "reason": "FEE_ESTIMATE_UNAVAILABLE", "dispatch_authorized": False}
    return {**context, "funding": funding, "pricing": pricing,
            "available": pricing["available"], "reason": pricing["reason"], "dispatch_authorized": False}


def read_staged_prep_fee_snapshot(request_options: dict, *, quote_provider) -> dict:
    """Collect exact current batch, future XCH stage and cancellation cover.

    Projections price observed standard wallet templates, never synthetic effect
    evidence. Cancellation protection covers one individually priced cancel per
    prepared replacement root; cheaper bulk cancellation does not enlarge this
    allowance. This is an estimate of cover, not a promise all cancels are needed.
    Bounded prerequisite/compatibility planning remains fail-closed when the
    shared exact batch planner cannot represent the current workflow.
    """
    from chia_rs import CoinSpend
    from coin_prep_batch_plan import BatchPlan, PlannedOutput
    from coin_prep_fee_projection import project_standard_cost
    from coin_prep_fee_pricing import is_current_fee_quote
    from coin_prep_unsigned import inspect_batch_unsigned

    context = read_next_prep_fee_snapshot(request_options)
    if context["available"] is not True:
        return context
    plan = context["pricing"]["plan"]
    stages, quotes, profiles, templates = [], {}, {}, {}
    target_seconds = context["recipe"]["economic_plan"]["target_seconds"]

    def unavailable(reason):
        return {**context, "available": False, "reason": reason, "dispatch_authorized": False}

    def remember(inspection):
        if inspection.get("available") is not True:
            return False
        validated = inspection["validated_unsigned"]
        assets = {row["coin_id"].removeprefix("0x").lower():
                  "cat" if row.get("asset") and row["asset"].get("asset_id") else "xch"
                  for row in validated["summary"]["inputs"]}
        for raw in validated["coin_spends"]:
            # Sage permits bare hex; executable inspection already validated
            # this exact bundle. chia_rs JSON parsing additionally requires 0x.
            normalized = {**raw, "coin": dict(raw["coin"])}
            for key in ("puzzle_reveal", "solution"):
                normalized[key] = "0x" + normalized[key].removeprefix("0x")
            for key in ("parent_coin_info", "puzzle_hash"):
                normalized["coin"][key] = "0x" + normalized["coin"][key].removeprefix("0x")
            spend = CoinSpend.from_json_dict(normalized)
            templates.setdefault(assets[spend.coin.name().hex()], spend.puzzle_reveal)
        return True

    if plan.transaction_required:
        inspection = context["pricing"]["inspection"]
        remember(inspection)
        name = f"prep_{plan.asset}"
        stages.append({"stage_id": name, "cost": inspection["cost"], "cost_kind": "exact_unsigned",
                       "transaction_count_min": 1, "transaction_count_max": 1, "cancellation": False})
        quotes[name] = context["pricing"]["quote"]

    cancellation_counts = {asset: sum(t.asset == asset and t.purpose == "replacement"
                                     for t in context["recipe"]["targets"])
                           for asset in ("xch", "cat")}
    missing_native = [t for t in context["recipe"]["targets"] if t.asset == "xch"
                      and (t.asset, t.ordinal) not in plan.reused_target_ids]
    need_future_native = plan.transaction_required and plan.asset == "cat" and missing_native
    needed_templates = ({"xch"} if need_future_native or any(cancellation_counts.values()) else set())
    if cancellation_counts["cat"]:
        needed_templates.add("cat")
    for asset in sorted(needed_templates - templates.keys()):
        coin = next((c for c in context["funding"]["snapshot"].coins
                     if c.asset == asset and c.selectable and not c.protected), None)
        if coin is None:
            return unavailable("FEE_PROJECTION_PUZZLE_UNSUPPORTED")
        # A read-only self-return probe learns the actual template, including
        # when a reused cohort needs no preparation transaction of its own.
        probe = BatchPlan(asset, (coin.coin_id,), None,
                          (PlannedOutput(asset, "change", coin.amount_mojos, -1),), (), (), 0)
        try:
            inspected = inspect_batch_unsigned(probe, context["receive_address"],
                                               context["identity"]["asset_id"])
            if not remember(inspected):
                return unavailable("FEE_PROJECTION_PUZZLE_UNSUPPORTED")
        except (ValueError, TypeError, KeyError):
            return unavailable("FEE_PROJECTION_PUZZLE_UNSUPPORTED")

    def add_projection(name, *, xch_inputs, cat_inputs, xch_outputs,
                       count=1, count_min=1, cancellation=False, ephemerals=0):
        try:
            projection = project_standard_cost(
                native_puzzle=templates.get("xch"), cat_puzzle=templates.get("cat"),
                xch_inputs=xch_inputs, cat_inputs=cat_inputs, xch_outputs=xch_outputs,
                native_ephemeral_outputs=ephemerals,
            )
        except ValueError:
            return "FEE_PROJECTION_PROFILE_INVALID"
        if projection["available"] is not True:
            return projection["reason"]
        try:
            quote = quote_provider(projection["cost"], target_seconds=target_seconds)
        except Exception:
            return "FEE_ESTIMATE_UNAVAILABLE"
        if not is_current_fee_quote(quote, projection["cost"], target_seconds):
            return "FEE_ESTIMATE_UNAVAILABLE"
        stages.append({"stage_id": name, "cost": projection["cost"], "cost_kind": "projected",
                       "transaction_count_min": count_min, "transaction_count_max": count,
                       "cancellation": cancellation})
        quotes[name] = quote
        profiles[name] = {key: projection[key] for key in (
            "input_count_max", "output_count_max", "ephemeral_spend_count_max", "assumptions")}
        if cancellation:
            profiles[name]["assumptions"].append("one_individual_cancel_per_prepared_replacement")
        return None

    if need_future_native:
        # Confirmation changes the fee root to change, never a known selectable
        # future coin. Bound possible roots and explicitly include intermediate
        # spends for repeated denominations, plus possible change collision.
        inputs = sum(c.asset == "xch" and c.selectable and not c.protected
                     and c.coin_id not in plan.reused_coin_ids
                     for c in context["funding"]["snapshot"].coins)
        outputs = len(missing_native) + 1
        reason = add_projection("prep_xch", xch_inputs=min(50, max(1, inputs)),
                                cat_inputs=0, xch_outputs=outputs, ephemerals=outputs)
        if reason:
            return unavailable(reason)
        # Inspect only future amounts, not invented selectable coin identities.
        # The CAT fee root is consumed; its validated change replaces it only
        # after confirmation. The later exact batch must refresh that evidence.
        future_amounts = [c.amount_mojos for c in context["funding"]["snapshot"].coins
                          if c.asset == "xch" and c.selectable and not c.protected
                          and c.coin_id not in plan.reused_coin_ids
                          and c.coin_id != plan.fee_source_id]
        future_amounts += [o.amount_mojos for o in plan.outputs
                           if o.asset == "xch" and o.purpose == "fee_change"]
        principal = sum(t.amount_mojos for t in missing_native)
        largest = sum(sorted(future_amounts, reverse=True)[:50])
        if largest < principal + quotes["prep_xch"]["fee_mojos"]:
            if len(future_amounts) <= 50:
                return unavailable("FEE_FUTURE_NATIVE_FUNDING_UNAVAILABLE")
            native_stage = stages.pop()
            # Each bounded 50-root -> 1-root prerequisite reduces the number
            # of roots by 49. This upper cover includes every such fee even
            # when the target can be funded before all roots are consolidated.
            maximum = (len(future_amounts) - 50 + 48) // 49
            reason = add_projection("prep_xch_consolidation", xch_inputs=50,
                                    cat_inputs=0, xch_outputs=1, count=maximum,
                                    count_min=1 if largest < principal else 0)
            if reason:
                return unavailable(reason)
            profiles["prep_xch_consolidation"]["assumptions"].append(
                "bounded_native_50_to_1_prerequisites")
            stages.append(native_stage)
            fee = quotes["prep_xch_consolidation"]["fee_mojos"]
            for _ in range(maximum):
                future_amounts.sort(reverse=True)
                merged = sum(future_amounts[:50]) - fee
                if merged <= 0:
                    return unavailable("FEE_FUTURE_NATIVE_FUNDING_UNAVAILABLE")
                future_amounts = [merged, *future_amounts[50:]]
            if sum(future_amounts) < principal + quotes["prep_xch"]["fee_mojos"]:
                return unavailable("FEE_FUTURE_NATIVE_FUNDING_UNAVAILABLE")
    for asset in ("xch", "cat"):
        if cancellation_counts[asset]:
            reason = add_projection(f"cancel_{asset}", xch_inputs=2 if asset == "xch" else 1,
                                    cat_inputs=1 if asset == "cat" else 0,
                                    xch_outputs=2 if asset == "xch" else 1,
                                    count=cancellation_counts[asset], cancellation=True)
            if reason:
                return unavailable(reason)
    # All network and unsigned construction has finished: do not persist a
    # confirmable preview if provider latency concealed a wallet/plan change.
    try:
        after = read_fee_economic_snapshot(context["request_options"])
    except ValueError:
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED") from None
    if any(after[key] != context[key] for key in (
            "identity", "configuration", "receive_address", "snapshot", "recipe", "campaign", "fee_pool")):
        raise ValueError("FEE_WALLET_CONTEXT_CHANGED")
    if any(not is_current_fee_quote(quote, stage["cost"], target_seconds)
           for stage in stages for quote in (quotes[stage["stage_id"]],)):
        return unavailable("FEE_ESTIMATE_UNAVAILABLE")
    return {**context, "stages": stages, "stage_quotes": quotes, "stage_profiles": profiles,
            "available": True, "dispatch_authorized": False}
