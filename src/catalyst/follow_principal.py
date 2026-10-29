"""Exact read-only principal bound for a reviewed two-sided Follow run."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING

from coin_prep_batch_plan import CoinSnapshot


_VOLATILE_SHUTDOWN_QUOTE_FIELDS = frozenset(
    {"quoted_fee_mojos", "observed_at", "expires_at"}
)
_FOLLOW_REVIEW_MIN_QUOTE_REMAINING_SECONDS = 20


def _bound_shutdown_funding(funding: dict) -> dict:
    return {
        key: value
        for key, value in funding.items()
        if key not in _VOLATILE_SHUTDOWN_QUOTE_FIELDS
    }


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
    largest_fee_coin = 0
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
            largest_fee_coin = max(largest_fee_coin, amount)
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
        "largest_spendable_fee_coin_mojos": largest_fee_coin,
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
    fee_ids = set()
    for row in fee_rows:
        if type(row) is not dict or row.get("purpose") != "fee_reserve":
            continue
        coin_id = row.get("coin_id")
        if (
            type(coin_id) is not str
            or re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", coin_id) is None
        ):
            raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
        normalized_id = coin_id.lower().removeprefix("0x")
        if normalized_id in fee_ids:
            raise ValueError("FOLLOW_FEE_POOL_UNAVAILABLE")
        fee_ids.add(normalized_id)
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
    largest_planned_fee_coin_mojos = 0
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
        else:
            largest_planned_fee_coin_mojos = max(
                largest_planned_fee_coin_mojos, output["amount_mojos"]
            )
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
    shutdown_funding = {
        "ready": False,
        "reason": "FOLLOW_SLOT_REVIEW_REQUIRED",
        "full_book_proven": False,
        "dispatch_authorized": False,
    }
    if count_gate["replacement_count_gate_passed"]:
        from follow_slot_fit import preview_current_follow_slot_fit
        from follow_shutdown_funding import preview_one_block_shutdown_funding
        from config import cfg

        slot_fit = preview_current_follow_slot_fit(
            configuration=observed.get("configuration"),
            outputs=outputs,
            buy_limit=buy_limit,
            sell_limit=sell_limit,
            maximum_trade_xch_mojos=principal["maximum_trade_xch_mojos"],
            maximum_trade_cat_atoms=principal["maximum_trade_cat_atoms"],
        )
        shutdown_funding = preview_one_block_shutdown_funding(
            maximum_fee_mojos=before["total_fee_mojos"],
            spent_fee_mojos=before["spent_fee_mojos"],
            held_fee_mojos=before["held_fee_mojos"],
            largest_fee_coin_mojos=principal["largest_spendable_fee_coin_mojos"],
            protected_shutdown_fee_mojos=before["cancellation_reserve_mojos"],
            target_seconds=int(getattr(cfg, "TRANSACTION_FEE_TARGET_SECS", 300)),
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
        "largest_planned_fee_coin_mojos": largest_planned_fee_coin_mojos,
        "shutdown_funding": shutdown_funding,
    }
    # A network quote's amount and lifetime are live funding evidence, not
    # economic authority. Bind the approved cap, reserve and funding result;
    # recheck the exact current quote before every financial effect.
    bound_terms = dict(review_terms)
    bound_terms["shutdown_funding"] = _bound_shutdown_funding(shutdown_funding)
    proposal_sha256 = hashlib.sha256(
        json.dumps(bound_terms, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
    duration_seconds: int | None,
    requested_fee_cap_mojos: int,
    continuous: bool = False,
) -> dict:
    """Persist a short-lived review from server-verified principal and slots.

    The returned review is display data only. A later native final click must
    reprove the proposal and consume this exact review before Start is allowed.
    """

    import database
    from follow_run_terms import CONTINUOUS_RUN_EXPIRY

    if (
        type(approval_id) is not str
        or re.fullmatch(r"[0-9a-f]{64}", approval_id) is None
        or type(buy_limit) is not int
        or type(sell_limit) is not int
        or not 1 <= buy_limit <= 50
        or not 1 <= sell_limit <= 50
        or type(continuous) is not bool
        or (
            (duration_seconds is not None)
            if continuous
            else (
                type(duration_seconds) is not int
                or not 0 < duration_seconds <= 48 * 3600
            )
        )
        or type(requested_fee_cap_mojos) is not int
        or requested_fee_cap_mojos <= 0
    ):
        raise ValueError("FOLLOW_REVIEW_REQUEST_INVALID")

    def _current_proposal() -> dict:
        proposal = preview_approved_follow_principal(
            approval_id, buy_limit=buy_limit, sell_limit=sell_limit
        )
        funding = proposal.get("shutdown_funding")
        if type(funding) is dict and funding.get("ready") is False:
            reason = funding.get("reason")
            if reason in {
                "FOLLOW_SHUTDOWN_FEE_ESTIMATE_UNAVAILABLE",
                "FOLLOW_SHUTDOWN_FEE_FUNDING_REQUIRED",
                "FOLLOW_SHUTDOWN_FEE_CAP_INSUFFICIENT",
                "FOLLOW_SHUTDOWN_RESERVE_INSUFFICIENT",
                "FOLLOW_SHUTDOWN_FEE_COIN_TOO_SMALL",
            }:
                raise ValueError(reason)
        reserve = proposal.get("cancellation_reserve_mojos")
        if (
            proposal.get("dispatch_authorized") is not False
            or proposal.get("buy_limit") != buy_limit
            or proposal.get("sell_limit") != sell_limit
            or proposal.get("replacement_count_gate_passed") is not True
            or proposal.get("buy_slots_arithmetic_fit") != buy_limit
            or proposal.get("sell_slots_arithmetic_fit") != sell_limit
            or proposal.get("current_prep_targets_proven") is not True
            or type(proposal.get("shutdown_funding")) is not dict
            or proposal["shutdown_funding"].get("ready") is not True
            or proposal["shutdown_funding"].get("full_book_proven") is not False
            or proposal["shutdown_funding"].get("dispatch_authorized") is not False
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
    refreshed = _current_proposal()

    def _stable_view(value: dict) -> dict:
        funding = value["shutdown_funding"]
        return {
            **value,
            "shutdown_funding": _bound_shutdown_funding(funding),
        }

    if _stable_view(refreshed) != _stable_view(proposal):
        raise ValueError("FOLLOW_REVIEW_PROPOSAL_CHANGED")
    proposal = refreshed
    started_at_epoch = int(time.time())
    quote_expires_at = proposal["shutdown_funding"].get("expires_at")
    if (
        type(quote_expires_at) is not int
        or quote_expires_at - started_at_epoch
        < _FOLLOW_REVIEW_MIN_QUOTE_REMAINING_SECONDS
    ):
        raise ValueError("FOLLOW_SHUTDOWN_FEE_ESTIMATE_UNAVAILABLE")
    terms = {
        "approval_id": approval_id,
        "identity": proposal["identity"],
        "configuration_sha256": proposal["configuration_sha256"],
        "principal_review_sha256": proposal["proposal_sha256"],
        "buy_limit": buy_limit,
        "sell_limit": sell_limit,
        "started_at_epoch": started_at_epoch,
        "expires_at_epoch": (
            CONTINUOUS_RUN_EXPIRY if continuous else started_at_epoch + duration_seconds
        ),
        "maximum_fee_mojos": requested_fee_cap_mojos,
        "protected_shutdown_fee_mojos": proposal["cancellation_reserve_mojos"],
    }
    if continuous:
        terms["continuous"] = True
    review = database.create_follow_run_review(**terms)
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
            or type(proposal.get("shutdown_funding")) is not dict
            or proposal["shutdown_funding"].get("ready") is not True
            or proposal["shutdown_funding"].get("full_book_proven") is not False
            or proposal["shutdown_funding"].get("dispatch_authorized") is not False
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
        existing = database.get_follow_creation_authority(
            identity=review["identity"],
            configuration_sha256=review["configuration_sha256"],
            now_epoch=now_epoch,
        )
        if existing.get("ready") is True:
            if (
                existing.get("approval_id") != approval_id
                or existing.get("buy_limit") != buy_limit
                or existing.get("sell_limit") != sell_limit
                or existing.get("maximum_fee_mojos") != review["maximum_fee_mojos"]
                or existing.get("protected_shutdown_fee_mojos")
                != review["protected_shutdown_fee_mojos"]
                or existing.get("principal_review_sha256")
                == review["principal_review_sha256"]
            ):
                raise ValueError("FOLLOW_RUN_OVERLAP")
            from wallet import get_all_offers, get_pending_transactions

            pending = get_pending_transactions()
            offers = get_all_offers(include_completed=True, start=0, end=10000)
            if (
                type(pending) is not list
                or pending
                or type(offers) is not list
                or len(offers) >= 10000
                or any(
                    type(offer) is not dict
                    or str(offer.get("status", "")).lower()
                    not in {"cancelled", "expired", "completed", "filled"}
                    for offer in offers
                )
            ):
                raise ValueError("FOLLOW_RUN_OVERLAP")
            terms["reapprove_run_id"] = existing["run_id"]
        authority = database.create_follow_run_authority(**terms)
        return {**authority, "dispatch_authorized": False}


def _current_follow_fee_funding(run_id: str) -> dict:
    """Read selectable designated fee coins for the exact running wallet."""

    import database
    from coin_prep_fee_runtime import read_fee_wallet_snapshot
    from confidence_override import current_configuration_digest

    expected_identity = database.get_follow_run_identity(run_id)
    observed = read_fee_wallet_snapshot()
    if type(observed) is not dict or observed.get("identity") != expected_identity:
        raise ValueError("FOLLOW_FEE_REVISION_WALLET_CHANGED")
    snapshot = observed.get("snapshot")
    if type(snapshot) is not CoinSnapshot:
        raise ValueError("FOLLOW_FEE_REVISION_FUNDING_UNAVAILABLE")
    rows = database.get_free_coins("xch")
    if type(rows) is not list:
        raise ValueError("FOLLOW_FEE_REVISION_FUNDING_UNAVAILABLE")
    fee_ids = {
        row["coin_id"]
        for row in rows
        if type(row) is dict and row.get("purpose") == "fee_reserve"
    }
    if not fee_ids or any(
        type(coin_id) is not str or re.fullmatch(r"[0-9a-f]{64}", coin_id) is None
        for coin_id in fee_ids
    ):
        raise ValueError("FOLLOW_FEE_REVISION_FUNDING_UNAVAILABLE")
    seen = set()
    total = 0
    for coin in snapshot.coins:
        if coin.coin_id in fee_ids:
            if (
                coin.coin_id in seen
                or coin.asset != "xch"
                or coin.selectable is not True
                or type(coin.amount_mojos) is not int
                or coin.amount_mojos <= 0
                or coin.purpose == "reserve"
            ):
                raise ValueError("FOLLOW_FEE_REVISION_FUNDING_UNAVAILABLE")
            seen.add(coin.coin_id)
            total += coin.amount_mojos
    if seen != fee_ids:
        raise ValueError("FOLLOW_FEE_REVISION_FUNDING_UNAVAILABLE")
    return {
        "identity": expected_identity,
        "configuration_sha256": current_configuration_digest(),
        "observed_fee_principal_mojos": total,
        "dispatch_authorized": False,
    }


def prepare_follow_fee_ceiling_review(
    run_id: str, *, proposed_maximum_fee_mojos: int
) -> dict:
    """Freeze a fee-ceiling proposal from a fresh trusted wallet read."""

    import database

    if (
        type(run_id) is not str
        or re.fullmatch(r"[0-9a-f]{64}", run_id) is None
        or type(proposed_maximum_fee_mojos) is not int
        or proposed_maximum_fee_mojos <= 0
    ):
        raise ValueError("FOLLOW_FEE_REVISION_INVALID")
    observed = _current_follow_fee_funding(run_id)
    now_epoch = int(time.time())
    review = database.create_follow_fee_ceiling_review(
        run_id=run_id,
        identity=observed["identity"],
        configuration_sha256=observed["configuration_sha256"],
        proposed_maximum_fee_mojos=proposed_maximum_fee_mojos,
        observed_fee_principal_mojos=observed["observed_fee_principal_mojos"],
        now_epoch=now_epoch,
    )
    if _current_follow_fee_funding(run_id) != observed:
        raise ValueError("FOLLOW_FEE_REVISION_WALLET_CHANGED")
    return {
        **database.get_follow_fee_ceiling_review(review["review_id"]),
        "dispatch_authorized": False,
    }


def confirm_follow_fee_ceiling_review(review_id: str, review_sha256: str) -> dict:
    """Consume the exact native review against a fresh wallet funding read."""

    import api_server
    import database

    if any(
        type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in (review_id, review_sha256)
    ):
        raise ValueError("FOLLOW_FEE_REVISION_REVIEW_REQUIRED")
    with api_server._bot_cancel_lifecycle_lock:
        review = database.get_follow_fee_ceiling_review(review_id)
        if review["consumed"]:
            raise ValueError("FOLLOW_FEE_REVISION_REVIEW_USED")
        if review["review_sha256"] != review_sha256:
            raise ValueError("FOLLOW_FEE_REVISION_REVIEW_CHANGED")
        observed = _current_follow_fee_funding(review["run_id"])
        if (
            observed["configuration_sha256"] != review["configuration_sha256"]
            or observed["observed_fee_principal_mojos"]
            != review["observed_fee_principal_mojos"]
        ):
            raise ValueError("FOLLOW_FEE_REVISION_WALLET_CHANGED")
        return database.confirm_follow_fee_ceiling_review(
            review_id=review_id,
            review_sha256=review_sha256,
            identity=observed["identity"],
            configuration_sha256=observed["configuration_sha256"],
            observed_fee_principal_mojos=observed["observed_fee_principal_mojos"],
            now_epoch=int(time.time()),
        )


def reviewed_follow_start_readiness(cfg_obj, *, resume_existing_offers: bool) -> dict:
    """Reprove a two-sided Follow run immediately before the trading thread starts.

    The review and its native confirmation are separate from Start. This
    reader cannot create run authority or submit a wallet effect.
    """
    if (
        str(getattr(cfg_obj, "LIQUIDITY_MODE", "two_sided") or "").lower()
        != "two_sided"
    ):
        return {"ready": True}
    if resume_existing_offers:
        # A retained offer book needs its own exact run-bound membership proof.
        return {"ready": False, "reason": "FOLLOW_RESUME_REVIEW_REQUIRED"}
    try:
        import database
        from confidence_override import current_scope

        scope = current_scope()
        identity = scope["identity"]
        authority = database.get_follow_creation_authority(
            identity=identity,
            configuration_sha256=scope["configuration_sha256"],
            now_epoch=int(time.time()),
        )
        if (
            authority.get("ready") is not True
            or authority.get("run_id") != scope.get("follow_run_id")
            or authority.get("consent_id") != scope.get("financial_consent_id")
            or authority.get("identity") != identity
            or authority.get("buy_limit")
            != getattr(cfg_obj, "MAX_ACTIVE_BUY_OFFERS", None)
            or authority.get("sell_limit")
            != getattr(cfg_obj, "MAX_ACTIVE_SELL_OFFERS", None)
        ):
            return {"ready": False, "reason": "FOLLOW_REVIEW_CHANGED"}
        asset_id = getattr(cfg_obj, "CAT_ASSET_ID", None)
        fingerprint = identity.get("wallet_fingerprint")
        if (
            type(asset_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", asset_id) is None
            or type(fingerprint) is not int
            or fingerprint <= 0
        ):
            return {"ready": False, "reason": "FOLLOW_REVIEW_CHANGED"}
        wallet_hash = hashlib.sha256(
            f"fingerprint:{fingerprint}".encode("utf-8")
        ).hexdigest()
        local_open = database.get_open_offers(cat_asset_id=asset_id)
        unresolved = [
            row
            for row in database.get_offer_intents_for_registry()
            if row.get("wallet_fingerprint_hash") == wallet_hash
            and row.get("network") == identity.get("network")
            and row.get("asset_id") == asset_id
            and row.get("lifecycle_state") not in {"terminal", "creation_failed"}
        ]
        if local_open or unresolved:
            return {"ready": False, "reason": "FOLLOW_LOCAL_OFFERS_UNRESOLVED"}
        proposal = preview_approved_follow_principal(
            authority["approval_id"],
            buy_limit=authority["buy_limit"],
            sell_limit=authority["sell_limit"],
        )
        if (
            proposal.get("dispatch_authorized") is not False
            or proposal.get("identity") != identity
            or proposal.get("configuration_sha256") != authority["configuration_sha256"]
            or proposal.get("proposal_sha256") != authority["principal_review_sha256"]
            or proposal.get("maximum_fee_mojos") != authority["maximum_fee_mojos"]
            or proposal.get("cancellation_reserve_mojos")
            != authority["protected_shutdown_fee_mojos"]
            or proposal.get("replacement_count_gate_passed") is not True
            or proposal.get("current_prep_targets_proven") is not True
            or proposal.get("buy_slots_arithmetic_fit") != authority["buy_limit"]
            or proposal.get("sell_slots_arithmetic_fit") != authority["sell_limit"]
        ):
            return {"ready": False, "reason": "FOLLOW_REVIEW_CHANGED"}
        return {"ready": True, "run_id": authority["run_id"]}
    except (ValueError, KeyError, TypeError):
        return {"ready": False, "reason": "FOLLOW_REVIEW_REQUIRED"}
    except Exception:
        return {"ready": False, "reason": "FOLLOW_REVIEW_UNAVAILABLE"}
