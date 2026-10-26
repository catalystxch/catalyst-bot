"""Exact read-only principal bound for a reviewed two-sided Follow run."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING

from coin_prep_batch_plan import CoinSnapshot


def _floor_atoms(value: Decimal, decimals: int) -> int:
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise ValueError("FOLLOW_PRINCIPAL_RESERVE_INVALID")
    return int((value * (10**decimals)).to_integral_value(rounding=ROUND_CEILING))


def calculate_follow_principal(
    snapshot: CoinSnapshot,
    *,
    xch_reserve: Decimal,
    cat_reserve: Decimal,
    cat_decimals: int,
    fee_cap_mojos: int,
    fee_pool_principal_mojos: int,
    fee_reserve_coin_ids: set[str],
) -> dict:
    """Bound both trading balances without spending protected fee principal.

    The caller supplies a complete, identity-verified selectable Sage snapshot.
    This function is pure: it cannot grant run authority, change settings or
    submit a wallet effect. Any missing or contradictory coin data fails closed.
    """

    if (
        type(snapshot) is not CoinSnapshot
        or type(cat_decimals) is not int
        or not 0 <= cat_decimals <= 18
        or type(fee_cap_mojos) is not int
        or fee_cap_mojos <= 0
        or type(fee_pool_principal_mojos) is not int
        or fee_pool_principal_mojos < 0
        or type(fee_reserve_coin_ids) is not set
    ):
        raise ValueError("FOLLOW_PRINCIPAL_INPUT_INVALID")
    xch_floor = _floor_atoms(xch_reserve, 12)
    cat_floor = _floor_atoms(cat_reserve, cat_decimals)
    fee_floor = max(fee_cap_mojos, fee_pool_principal_mojos)
    if any(
        type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in fee_reserve_coin_ids
    ):
        raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")

    totals = {"xch": 0, "cat": 0}
    protected = {"xch": 0, "cat": 0}
    user_reserve = {"xch": 0, "cat": 0}
    unprotected_count = {"xch": 0, "cat": 0}
    fee_coins = 0
    seen = set()
    canonical = []
    for coin in snapshot.coins:
        coin_id = getattr(coin, "coin_id", None)
        asset = getattr(coin, "asset", None)
        amount = getattr(coin, "amount_mojos", None)
        purpose = getattr(coin, "purpose", None)
        selectable = getattr(coin, "selectable", None)
        is_protected = getattr(coin, "protected", None)
        if (
            type(coin_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", coin_id) is None
            or coin_id in seen
            or asset not in totals
            or type(amount) is not int
            or amount <= 0
            or type(purpose) is not str
            or type(selectable) is not bool
            or selectable is not True
            or type(is_protected) is not bool
            or (purpose == "fee_reserve") != (coin_id in fee_reserve_coin_ids)
            or (coin_id in fee_reserve_coin_ids and asset != "xch")
        ):
            raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")
        seen.add(coin_id)
        totals[asset] += amount
        if is_protected or coin_id in fee_reserve_coin_ids:
            protected[asset] += amount
        else:
            unprotected_count[asset] += 1
        if purpose == "reserve":
            if not is_protected:
                raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")
            user_reserve[asset] += amount
        if coin_id in fee_reserve_coin_ids:
            fee_coins += amount
        canonical.append((asset, coin_id, amount, purpose, is_protected))
    if not fee_reserve_coin_ids.issubset(seen):
        raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")

    extra_xch_reserve = max(0, xch_floor - user_reserve["xch"])
    extra_cat_reserve = max(0, cat_floor - user_reserve["cat"])
    extra_fee = max(0, fee_floor - fee_coins)
    trade_xch = totals["xch"] - protected["xch"] - extra_xch_reserve - extra_fee
    trade_cat = totals["cat"] - protected["cat"] - extra_cat_reserve
    if trade_xch <= 0:
        raise ValueError("FOLLOW_FEE_PRINCIPAL_UNAVAILABLE")
    if trade_cat <= 0:
        raise ValueError("FOLLOW_TRADING_PRINCIPAL_UNAVAILABLE")
    digest = hashlib.sha256(
        json.dumps(sorted(canonical), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "maximum_trade_xch_mojos": trade_xch,
        "maximum_trade_cat_atoms": trade_cat,
        "protected_fee_principal_mojos": fee_floor,
        "protected_xch_reserve_mojos": xch_floor,
        "protected_cat_reserve_atoms": cat_floor,
        "selectable_xch_mojos": totals["xch"],
        "selectable_cat_atoms": totals["cat"],
        "unprotected_xch_coin_count": unprotected_count["xch"],
        "unprotected_cat_coin_count": unprotected_count["cat"],
        "inventory_sha256": digest,
        "dispatch_authorized": False,
    }


def read_follow_principal_snapshot(*, fee_cap_mojos: int) -> dict:
    """Read the verified Sage inventory and durable fee-coin designation.

    The result is a principal proposal for native review, never wallet-effect
    authority. A later review must re-read it before consuming consent.
    """

    from coin_prep_fee_runtime import read_fee_wallet_snapshot

    return _principal_from_observed_snapshot(
        read_fee_wallet_snapshot(), fee_cap_mojos=fee_cap_mojos
    )


def _principal_from_observed_snapshot(observed: dict, *, fee_cap_mojos: int) -> dict:
    """Calculate principal from one trusted, identity-verified wallet read."""

    from tx_fees import get_fee_pool_plan
    import database

    config = observed["configuration"]
    snapshot = observed["snapshot"]
    plan = get_fee_pool_plan()
    if type(plan) is not dict or type(plan.get("enabled")) is not bool:
        raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
    fee_pool_principal = 0
    if plan["enabled"]:
        count = plan.get("count")
        size = plan.get("coin_size_mojos")
        if type(count) is not int or count < 1 or type(size) is not int or size < 1:
            raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
        fee_pool_principal = count * size
    fee_rows = database.get_free_coins("xch")
    if type(fee_rows) is not list:
        raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
    fee_ids = {
        row["coin_id"]
        for row in fee_rows
        if type(row) is dict and row.get("purpose") == "fee_reserve"
    }
    if any(type(coin_id) is not str for coin_id in fee_ids):
        raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
    if any(
        coin.coin_id in fee_ids and coin.purpose not in {"", "fee_reserve"}
        for coin in snapshot.coins
    ):
        raise ValueError("FOLLOW_PRINCIPAL_INVENTORY_INVALID")
    enriched = CoinSnapshot(
        tuple(
            replace(coin, purpose="fee_reserve") if coin.coin_id in fee_ids else coin
            for coin in snapshot.coins
        )
    )
    selected_fee_ids = fee_ids.intersection(coin.coin_id for coin in enriched.coins)
    result = calculate_follow_principal(
        enriched,
        xch_reserve=config["XCH_RESERVE"],
        cat_reserve=config["CAT_RESERVE"],
        cat_decimals=config["CAT_DECIMALS"],
        fee_cap_mojos=fee_cap_mojos,
        fee_pool_principal_mojos=fee_pool_principal,
        fee_reserve_coin_ids=selected_fee_ids,
    )
    identity = observed["identity"]
    proposal_sha256 = hashlib.sha256(
        json.dumps(
            {"identity": identity, "principal": result},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {**result, "identity": identity, "principal_review_sha256": proposal_sha256}


def prove_follow_replacement_count_capacity(
    *, buy_limit: int, sell_limit: int, replacement_counts: dict
) -> dict:
    """Require one approved replacement coin per requested initial offer.

    This is a necessary count gate, not a price, denomination, market or
    dispatch proof. Those checks must still pass before a Follow run starts.
    """

    if (
        type(buy_limit) is not int
        or type(sell_limit) is not int
        or not 1 <= buy_limit <= 50
        or not 1 <= sell_limit <= 50
        or type(replacement_counts) is not dict
        or set(replacement_counts) != {"xch", "cat"}
        or any(
            type(value) is not int or value < 0 for value in replacement_counts.values()
        )
    ):
        raise ValueError("FOLLOW_SLOT_LIMIT_INVALID")
    if replacement_counts["xch"] < buy_limit or replacement_counts["cat"] < sell_limit:
        raise ValueError("FOLLOW_SLOT_INVENTORY_SHORT")
    return {
        "buy_limit": buy_limit,
        "sell_limit": sell_limit,
        "replacement_count_gate_passed": True,
    }


def preview_approved_follow_principal(
    approval_id: str, *, buy_limit: int | None = None, sell_limit: int | None = None
) -> dict:
    """Bind a fresh principal proposal to one completed, current fee scope.

    This is a read-only candidate for the native Follow review. The final
    consent route must re-read it and consume a persisted single-use review.
    """

    import database
    from coin_prep_fee_approval import _prove_approved_coin_prep_targets
    from coin_prep_fee_runtime import read_approved_prep_fee_snapshot
    from confidence_override import current_configuration_digest

    if (
        type(approval_id) is not str
        or re.fullmatch(r"[0-9a-f]{64}", approval_id) is None
    ):
        raise ValueError("FOLLOW_FEE_APPROVAL_REQUIRED")
    before = database.get_coin_prep_fee_approval_status(approval_id)
    context = database.get_coin_prep_fee_approval_context(approval_id)
    if (
        type(before) is not dict
        or before.get("approval_id") != approval_id
        or before.get("stale") is not False
        or before.get("session_completed") is not True
        or before.get("unresolved_operation_count") != 0
        or type(before.get("total_fee_mojos")) is not int
        or before["total_fee_mojos"] <= 0
        or type(before.get("cancellation_reserve_mojos")) is not int
        or not 0 < before["cancellation_reserve_mojos"] <= before["total_fee_mojos"]
        or type(context) is not dict
        or context.get("version") != context.get("latest_version")
    ):
        raise ValueError("FOLLOW_FEE_APPROVAL_STALE")
    scope_json = context.get("scope_json")
    plan_json = context.get("plan_json")
    if (
        type(scope_json) is not str
        or type(plan_json) is not str
        or hashlib.sha256(scope_json.encode("utf-8")).hexdigest()
        != context.get("scope_sha256")
        or hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
        != context.get("plan_sha256")
    ):
        raise ValueError("FOLLOW_FEE_APPROVAL_STALE")
    try:
        scope = json.loads(scope_json)
        plan = json.loads(plan_json)
    except (TypeError, ValueError) as exc:
        raise ValueError("FOLLOW_FEE_SCOPE_INVALID") from exc
    identity_keys = {
        "network",
        "wallet_type",
        "wallet_fingerprint",
        "wallet_id",
        "xch_wallet_id",
        "asset_id",
        "ticker",
    }
    if (
        type(scope) is not dict
        or scope.get("campaign_id") is not None
        or type(scope.get("session_id")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", scope["session_id"]) is None
    ):
        raise ValueError("FOLLOW_FEE_SCOPE_INVALID")
    outputs = plan.get("outputs") if type(plan) is dict else None
    if type(outputs) is not list:
        raise ValueError("FOLLOW_FEE_SCOPE_INVALID")
    replacement_counts = {"xch": 0, "cat": 0}
    replacement_atoms = {"xch": 0, "cat": 0}
    for output in outputs:
        if (
            type(output) is not dict
            or output.get("asset") not in replacement_counts
            or output.get("purpose") not in {"replacement", "fee_reserve"}
            or type(output.get("amount_mojos")) is not int
            or output["amount_mojos"] <= 0
            or (output["purpose"] == "fee_reserve" and output["asset"] != "xch")
        ):
            raise ValueError("FOLLOW_FEE_SCOPE_INVALID")
        if output["purpose"] == "replacement":
            replacement_counts[output["asset"]] += 1
            replacement_atoms[output["asset"]] += output["amount_mojos"]
    count_gate = {"replacement_count_gate_passed": False}
    if buy_limit is not None or sell_limit is not None:
        count_gate = prove_follow_replacement_count_capacity(
            buy_limit=buy_limit,
            sell_limit=sell_limit,
            replacement_counts=replacement_counts,
        )
    identity = {key: scope.get(key) for key in identity_keys}
    configuration_sha256 = current_configuration_digest()
    observed = read_approved_prep_fee_snapshot(approval_id)
    if type(observed) is not dict or observed.get("scope") != scope:
        raise ValueError("FOLLOW_FEE_APPROVAL_STALE")
    _prove_approved_coin_prep_targets(observed)
    principal = _principal_from_observed_snapshot(
        observed, fee_cap_mojos=before["total_fee_mojos"]
    )
    slot_fit = {}
    if count_gate["replacement_count_gate_passed"]:
        from follow_slot_fit import preview_current_follow_slot_fit

        slot_fit = preview_current_follow_slot_fit(
            configuration=observed.get("configuration"),
            outputs=outputs,
            buy_limit=buy_limit,
            sell_limit=sell_limit,
            maximum_trade_xch_mojos=principal["maximum_trade_xch_mojos"],
            maximum_trade_cat_atoms=principal["maximum_trade_cat_atoms"],
        )
    after = database.get_coin_prep_fee_approval_status(approval_id)
    if (
        principal.get("identity") != identity
        or type(principal.get("principal_review_sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", principal["principal_review_sha256"]) is None
        or after != before
        or current_configuration_digest() != configuration_sha256
    ):
        raise ValueError("FOLLOW_PRINCIPAL_REVIEW_CHANGED")
    review_terms = {
        "approval_id": approval_id,
        "scope_sha256": context["scope_sha256"],
        "plan_sha256": context["plan_sha256"],
        "configuration_sha256": configuration_sha256,
        "principal_review_sha256": principal["principal_review_sha256"],
        **count_gate,
        **{
            key: value
            for key, value in slot_fit.items()
            if key != "dispatch_authorized"
        },
        "maximum_fee_mojos": before["total_fee_mojos"],
        "cancellation_reserve_mojos": before["cancellation_reserve_mojos"],
    }
    proposal_sha256 = hashlib.sha256(
        json.dumps(review_terms, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        **principal,
        **review_terms,
        "proposal_sha256": proposal_sha256,
        "spent_fee_mojos": before["spent_fee_mojos"],
        "held_fee_mojos": before["held_fee_mojos"],
        "remaining_fee_mojos": before["remaining_fee_mojos"],
        "planned_replacement_xch_coin_count": replacement_counts["xch"],
        "planned_replacement_cat_coin_count": replacement_counts["cat"],
        "planned_replacement_xch_mojos": replacement_atoms["xch"],
        "planned_replacement_cat_atoms": replacement_atoms["cat"],
        **count_gate,
        **slot_fit,
        "current_prep_targets_proven": True,
        "dispatch_authorized": False,
    }


def prepare_follow_run_review(
    approval_id: str,
    *,
    buy_limit: int,
    sell_limit: int,
    duration_seconds: int,
    requested_fee_cap_mojos: int,
) -> dict:
    """Persist a short-lived review from server-verified principal and slots.

    The returned review is display data only. A later native final click must
    reprove the proposal and consume this exact review before Start is allowed.
    """

    import database

    if (
        type(approval_id) is not str
        or re.fullmatch(r"[0-9a-f]{64}", approval_id) is None
        or type(buy_limit) is not int
        or type(sell_limit) is not int
        or not 1 <= buy_limit <= 50
        or not 1 <= sell_limit <= 50
        or type(duration_seconds) is not int
        or not 0 < duration_seconds <= 48 * 3600
        or type(requested_fee_cap_mojos) is not int
        or requested_fee_cap_mojos <= 0
    ):
        raise ValueError("FOLLOW_REVIEW_REQUEST_INVALID")

    def _current_proposal() -> dict:
        proposal = preview_approved_follow_principal(
            approval_id, buy_limit=buy_limit, sell_limit=sell_limit
        )
        reserve = proposal.get("cancellation_reserve_mojos")
        if (
            proposal.get("dispatch_authorized") is not False
            or proposal.get("buy_limit") != buy_limit
            or proposal.get("sell_limit") != sell_limit
            or proposal.get("replacement_count_gate_passed") is not True
            or proposal.get("buy_slots_arithmetic_fit") != buy_limit
            or proposal.get("sell_slots_arithmetic_fit") != sell_limit
            or proposal.get("current_prep_targets_proven") is not True
            or proposal.get("maximum_fee_mojos") != requested_fee_cap_mojos
            or type(reserve) is not int
            or not 0 < reserve <= requested_fee_cap_mojos
            or type(proposal.get("maximum_trade_xch_mojos")) is not int
            or proposal["maximum_trade_xch_mojos"] <= 0
            or type(proposal.get("maximum_trade_cat_atoms")) is not int
            or proposal["maximum_trade_cat_atoms"] <= 0
            or any(
                type(proposal.get(key)) is not str
                or re.fullmatch(r"[0-9a-f]{64}", proposal[key]) is None
                for key in (
                    "configuration_sha256",
                    "proposal_sha256",
                    "slot_assignment_sha256",
                )
            )
            or type(proposal.get("identity")) is not dict
        ):
            raise ValueError("FOLLOW_REVIEW_PROPOSAL_INVALID")
        return proposal

    proposal = _current_proposal()
    started_at_epoch = int(time.time())
    terms = {
        "approval_id": approval_id,
        "identity": proposal["identity"],
        "configuration_sha256": proposal["configuration_sha256"],
        "principal_review_sha256": proposal["proposal_sha256"],
        "buy_limit": buy_limit,
        "sell_limit": sell_limit,
        "started_at_epoch": started_at_epoch,
        "expires_at_epoch": started_at_epoch + duration_seconds,
        "maximum_fee_mojos": requested_fee_cap_mojos,
        "protected_shutdown_fee_mojos": proposal["cancellation_reserve_mojos"],
    }
    review = database.create_follow_run_review(**terms)
    if _current_proposal() != proposal:
        raise ValueError("FOLLOW_REVIEW_PROPOSAL_CHANGED")
    return {
        **proposal,
        **terms,
        **review,
        "review_expires_at_epoch": started_at_epoch + 300,
        "dispatch_authorized": False,
    }


def confirm_follow_run_review(review_id: str, review_sha256: str) -> dict:
    """Consume one native-confirmed review without starting or dispatching.

    This service must only be reached from the native confirmation control.
    The bot and wallet-wide cancellation remain stopped while the current
    principal proposal is rechecked and the durable authority is recorded.
    """

    import api_server
    import database

    if any(
        type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (review_id, review_sha256)
    ):
        raise ValueError("FOLLOW_REVIEW_CONFIRMATION_INVALID")
    with api_server._bot_cancel_lifecycle_lock:
        bot = api_server.bot
        try:
            stopped = bot is not None and bot.is_running() is False
        except Exception:
            stopped = False
        if not stopped:
            raise ValueError("FOLLOW_BOT_MUST_BE_STOPPED")
        with api_server._cancel_all_state_lock:
            cancelling = api_server._cancel_all_state.get("running") is not False
        worker = api_server._cancel_all_thread
        if cancelling or (worker is not None and worker.is_alive()):
            raise ValueError("FOLLOW_CANCELLATION_IN_PROGRESS")

        review = database.get_follow_run_review(review_id)
        if type(review) is not dict or review.get("review_id") != review_id:
            raise ValueError("FOLLOW_REVIEW_REQUIRED")
        if review.get("consumed") is not False:
            raise ValueError("FOLLOW_REVIEW_USED")
        if review.get("review_sha256") != review_sha256:
            raise ValueError("FOLLOW_REVIEW_CHANGED")
        now_epoch = int(time.time())
        if (
            type(review.get("started_at_epoch")) is not int
            or type(review.get("review_expires_at_epoch")) is not int
            or type(review.get("expires_at_epoch")) is not int
            or not review["started_at_epoch"]
            <= now_epoch
            < review["review_expires_at_epoch"]
            or now_epoch >= review["expires_at_epoch"]
        ):
            raise ValueError("FOLLOW_REVIEW_EXPIRED")
        approval_id = review.get("approval_id")
        buy_limit = review.get("buy_limit")
        sell_limit = review.get("sell_limit")
        if (
            type(approval_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", approval_id) is None
            or type(buy_limit) is not int
            or type(sell_limit) is not int
            or not 1 <= buy_limit <= 50
            or not 1 <= sell_limit <= 50
            or type(review.get("identity")) is not dict
            or type(review.get("maximum_fee_mojos")) is not int
            or type(review.get("protected_shutdown_fee_mojos")) is not int
        ):
            raise ValueError("FOLLOW_REVIEW_CHANGED")
        proposal = preview_approved_follow_principal(
            approval_id, buy_limit=buy_limit, sell_limit=sell_limit
        )
        if (
            proposal.get("dispatch_authorized") is not False
            or proposal.get("replacement_count_gate_passed") is not True
            or proposal.get("current_prep_targets_proven") is not True
            or proposal.get("buy_slots_arithmetic_fit") != buy_limit
            or proposal.get("sell_slots_arithmetic_fit") != sell_limit
            or proposal.get("identity") != review["identity"]
            or proposal.get("configuration_sha256")
            != review.get("configuration_sha256")
            or proposal.get("proposal_sha256") != review.get("principal_review_sha256")
            or proposal.get("maximum_fee_mojos") != review["maximum_fee_mojos"]
            or proposal.get("cancellation_reserve_mojos")
            != review["protected_shutdown_fee_mojos"]
        ):
            raise ValueError("FOLLOW_REVIEW_CHANGED")
        terms = {
            "consent_id": review_id,
            "review_sha256": review_sha256,
            "approval_id": approval_id,
            "identity": review["identity"],
            "configuration_sha256": review["configuration_sha256"],
            "principal_review_sha256": review["principal_review_sha256"],
            "buy_limit": buy_limit,
            "sell_limit": sell_limit,
            "started_at_epoch": review["started_at_epoch"],
            "expires_at_epoch": review["expires_at_epoch"],
            "maximum_fee_mojos": review["maximum_fee_mojos"],
            "protected_shutdown_fee_mojos": review["protected_shutdown_fee_mojos"],
        }
        authority = database.create_follow_run_authority(**terms)
        return {**authority, "dispatch_authorized": False}
