"""Wallet backend dispatcher that re-exports a unified wallet API

Thin adapter module that reads ``WALLET_TYPE`` from the environment and
conditionally re-exports the public surface of either ``wallet_chia`` or
``wallet_sage``. Callers throughout the codebase do ``from wallet import ...``
without needing to know which backend is active, letting the trading loop,
offer manager, coin manager, and API server stay backend-agnostic.

Key responsibilities:
    - Read ``WALLET_TYPE`` from ``.env`` (``sage`` or ``chia``) on import
    - Re-export constants, offer helpers, coin helpers, and transfer functions
    - Provide a compatibility shim ``get_owned_coins_detailed`` for the Chia branch
    - Fall back to the Sage backend when ``WALLET_TYPE`` is missing or unknown

Selection happens exactly once at import time; switching backends requires an
application restart. The file intentionally contains no network or business
logic of its own beyond the shim.
"""

import hashlib
import inspect
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from config import cfg
import mutation_gate
from cancel_outcomes import CANCEL_UNKNOWN, cancellation_result
from database import (
    _issue_wallet_effect_adapter_outcome_attestation,
    _take_wallet_effect_adapter_facade_authority,
)

load_dotenv()

WALLET_TYPE = os.getenv("WALLET_TYPE", "sage").strip().lower()

if WALLET_TYPE == "chia":
    import wallet_chia as _wallet_adapter

    print("🔄 [Wallet] Using Chia wallet backend (port 9256)")
    try:
        from database import log_event as _log_wallet

        _log_wallet("info", "wallet_backend", "Using Chia wallet backend (port 9256)")
    except Exception:
        pass
    from wallet_chia import (  # noqa: F401
        # Constants
        WALLET_ID_XCH,
        WALLET_URL,
        CERT_PATH,
        KEY_PATH,
        HEADERS,
        WALLET_DEBUG,
        # Full node (Chia only)
        FULL_NODE_URL,
        FULL_NODE_CERT,
        FULL_NODE_KEY,
        # Core RPC
        rpc,
        full_node_rpc,
        set_quiet_mode,
        session,
        # Health monitoring
        get_wallet_sync_status,
        get_full_node_sync_status,
        get_chia_health,
        # Coin management
        get_spendable_coins,
        count_suitable_coins,
        get_spendable_coins_rpc,
        get_spendable_coin_count,
        split_coins_rpc,
        split_coins_bulk,
        wait_for_coin_confirmations,
        get_transaction,
        # Chia-specific coin queries (stubs for compatibility)
        get_owned_coins,
        get_selectable_coins_map,
        # Balance & address
        get_wallet_balance,
        get_balances_parallel,
        get_wallets,
        get_next_address,
        send_transaction,
        send_transaction_multi,
        # Offer management
        create_offer,
        cancel_offer,
        is_offer_time_expired,
        get_offer_expiry_info,
        cleanup_expired_offers,
        get_all_offers,
        get_authoritative_offer_history,
        get_offer_bech32,
        classify_offers_from_list,
        classify_open_offers_for_pair,
        cancel_offers_batch,
        # Helpers
        cat_to_mojos,
        # Chia Dashboard queries
        get_blockchain_state_full,
        get_peer_connections,
        get_transactions_list,
        get_transaction_count,
        get_all_coins_for_wallet,
        get_wallet_identity,
    )

    def get_owned_coins_detailed(wallet_id: int):
        """Chia backend compatibility stub for Sage-only detailed owned coins."""
        return None

    def sign_message_by_address(address: str, message: str) -> dict:
        """Chia backend stub — message signing for Dexie claims is Sage-only."""
        return {"success": False, "error": "claim_unsupported_on_chia_backend"}

    def get_wallet_puzzle_hashes(
        force: bool = False, max_derivations: int = 5000
    ) -> set:
        """Chia backend cannot prove the complete local address set here."""

        del force, max_derivations
        return set()

    def notify_cat_asset_id_changed(asset_id: str) -> None:
        """Chia backend compatibility stub for Sage active CAT cache updates."""
        return None

    def is_initialized() -> bool:
        """Chia backend has no separate Sage-style initialization step."""
        return True

    # Chia's spendable RPC is already the exact selectable view.
    get_exact_spendable_coins_rpc = get_spendable_coins_rpc
else:
    import wallet_sage as _wallet_adapter

    # Default: Sage (or unknown type falls back to Sage)
    def _safe_console(msg: str) -> None:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)

    if WALLET_TYPE != "sage":
        _safe_console(
            f"[Wallet] Unknown WALLET_TYPE '{WALLET_TYPE}', defaulting to 'sage'"
        )
    _safe_console("[Wallet] Using Sage light wallet backend (port 9257)")
    try:
        from database import log_event as _log_wallet

        _log_wallet(
            "info", "wallet_backend", "Using Sage light wallet backend (port 9257)"
        )
    except Exception:
        pass
    from wallet_sage import (  # noqa: F401
        # Constants
        WALLET_ID_XCH,
        SAGE_ACTIVE_CAT_WALLET_ID,
        WALLET_URL,
        CERT_PATH,
        KEY_PATH,
        HEADERS,
        WALLET_DEBUG,
        # Core RPC
        rpc,
        full_node_rpc,
        set_quiet_mode,
        # Health monitoring
        get_wallet_sync_status,
        get_full_node_sync_status,
        get_chia_health,
        # Coin management
        get_spendable_coins,
        count_suitable_coins,
        get_spendable_coins_rpc,
        get_spendable_coin_count,
        split_coins_rpc,
        split_coins_bulk,
        wait_for_coin_confirmations,
        get_transaction,
        # Sage-specific coin queries (owned + selectable maps)
        get_owned_coins,
        get_owned_coins_detailed,
        get_selectable_coins_map,
        get_selectable_coins_only as get_exact_spendable_coins_rpc,
        # Balance & address
        get_wallet_balance,
        get_balances_parallel,
        get_wallets,
        get_next_address,
        send_transaction,
        send_transaction_multi,
        # Offer management
        create_offer,
        cancel_offer,
        is_offer_time_expired,
        get_offer_expiry_info,
        cleanup_expired_offers,
        get_all_offers,
        get_authoritative_offer_history,
        get_authoritative_offers_by_ids,
        get_authoritative_offer_absence_by_ids,
        get_offer_bech32,
        classify_offers_from_list,
        classify_open_offers_for_pair,
        cancel_offers_batch,
        # Helpers
        cat_to_mojos,
        # Chia Dashboard queries
        get_blockchain_state_full,
        get_peer_connections,
        get_transactions_list,
        get_transaction_count,
        get_all_coins_for_wallet,
        # Sage-specific: offer cleanup (delete from Sage's local DB)
        delete_offer as sage_delete_offer,
        delete_offers_batch as sage_delete_offers_batch,
        # Sage-specific: message signing for Dexie liquidity-rewards claims
        sign_message_by_address,
        notify_cat_asset_id_changed,
        is_initialized,
        get_wallet_identity,
        get_wallet_puzzle_hashes,
    )


_WALLET_ADAPTER_AUTHORITY = _wallet_adapter
_WALLET_BACKEND_AUTHORITY = "chia" if WALLET_TYPE == "chia" else "sage"


def get_wallet_adapter_authority():
    """Return the exact adapter object selected for runtime acquisition."""

    return _wallet_adapter


def get_wallet_backend_authority() -> str:
    """Return the immutable backend selected with the adapter at import."""

    return _WALLET_BACKEND_AUTHORITY


def get_wallet_type() -> str:
    """Return which wallet backend is active: 'chia' or 'sage'."""
    return WALLET_TYPE


def get_coins_by_ids(
    coin_ids: list, *, authoritative_asset_hints: dict | None = None
) -> dict | None:
    """Read exact owned/spent coin records through the selected adapter.

    Sage provides the authoritative targeted endpoint.  Older Chia adapters do
    not expose an equivalent complete spent-coin read, so they return ``None``
    and reconciliation stays fail-closed instead of substituting a spendable
    snapshot.  This function is read-only and never enters the mutation gate.
    """

    if type(coin_ids) is not list or any(
        type(coin_id) is not str for coin_id in coin_ids
    ):
        return None
    reader = getattr(_wallet_adapter, "get_coins_by_ids", None)
    if not callable(reader):
        return None
    try:
        kwargs = {}
        if WALLET_TYPE == "sage" and authoritative_asset_hints is not None:
            kwargs["authoritative_asset_hints"] = dict(authoritative_asset_hints)
        result = reader(list(coin_ids), **kwargs)
    except Exception:
        return None
    return result if type(result) is dict else None


def get_recovery_coins_by_ids(coin_ids: list[str]) -> dict | None:
    """Read native Sage coin fields without losing missing-field evidence."""
    callback = getattr(_wallet_adapter, "get_recovery_coins_by_ids", None)
    return callback(coin_ids) if callable(callback) else None


def get_coins_by_ids_with_asset_hints(
    coin_ids: list, *, authoritative_asset_hints: dict
) -> dict | None:
    """Read Sage coin records using asset authority already collected upstream."""

    if WALLET_TYPE != "sage" or type(authoritative_asset_hints) is not dict:
        return None
    return get_coins_by_ids(
        coin_ids,
        authoritative_asset_hints=authoritative_asset_hints,
    )


def get_transaction_by_height(height: int) -> dict | None:
    """Read one exact height-addressed transaction when the backend supports it."""

    if type(height) is not int or isinstance(height, bool) or height <= 0:
        return None
    reader = getattr(_wallet_adapter, "get_transaction_by_height", None)
    if not callable(reader):
        return None
    try:
        result = reader(height)
    except Exception:
        return None
    return result if type(result) is dict else None


MUTATING_WALLET_EXPORTS = frozenset(
    {
        "cancel_offer",
        "cancel_offers_batch",
        "cleanup_expired_offers",
        "create_offer",
        "full_node_rpc",
        "get_next_address",
        "rpc",
        "send_transaction",
        "send_transaction_multi",
        "split_coins_bulk",
        "split_coins_rpc",
        "sign_message_by_address",
        "auto_combine_cat",
        "auto_combine_xch",
        "combine_coins",
        "create_transaction_rpc",
        "submit_built_transaction_rpc",
        "sage_initialize",
        "sage_login",
        "sage_topup_split",
        "send_cat_multi",
        "sage_delete_offer",
        "sage_delete_offers_batch",
        "set_change_address",
    }
)

_IDENTITY_BLOCK_ERROR = "Wallet mutation blocked by identity safety check"
_ADAPTER_DEFAULT = object()
_COMPOUND_MUTATION_EXPORTS = frozenset(
    {
        "auto_combine_cat",
        "auto_combine_xch",
        "cancel_offer",
        "cancel_offers_batch",
        "cleanup_expired_offers",
        "combine_coins",
        "create_offer",
        "create_transaction_rpc",
        "submit_built_transaction_rpc",
        "delete_offer",
        "delete_offers_batch",
        "get_next_address",
        "rpc",
        "sage_initialize",
        "sage_login",
        "sage_topup_split",
        "send_cat_multi",
        "send_transaction",
        "send_transaction_multi",
        "set_change_address",
        "sign_message_by_address",
        "split_coins_rpc",
        "split_coins_bulk",
    }
)
_LEGACY_BOOLEAN_MUTATION_EXPORTS = frozenset(
    {
        "delete_offer",
        "sage_initialize",
        "sage_login",
    }
)


def _blocked_mutation(reason: str) -> dict:
    return {
        "success": False,
        "error": _IDENTITY_BLOCK_ERROR,
        "reason": str(reason or "MUTATION_GATE_SAFETY_STOP"),
    }


def _blocked_offer_creation_continuation(
    reason: str = "OFFER_CREATION_CONTINUATION_INVALID",
    *,
    effect_attempted: bool = False,
) -> dict:
    result = _blocked_mutation(reason)
    result["_catalyst_effect_attempted"] = effect_attempted
    return result


def _blocked_offer_cancel_continuation(
    reason: str = "OFFER_CANCEL_CONTINUATION_INVALID",
    *,
    effect_attempted: bool = False,
) -> dict:
    result = cancellation_result(
        CANCEL_UNKNOWN,
        method="continuation",
        raw_response={"reason_code": reason},
        error=reason if reason == "FEE_FOLLOW_AUTHORITY_REQUIRED" else "",
    )
    result["_catalyst_effect_attempted"] = effect_attempted
    return result


class _OfferCreationContinuation:
    """Opaque process-local capability with no serializable token material."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<offer-creation-continuation opaque>"

    def __reduce__(self):
        raise TypeError("offer creation continuations cannot be serialized")


class _OfferCreationContinuationState:
    __slots__ = (
        "adapter",
        "binding",
        "creator_thread_id",
        "deadline",
        "intent_id",
        "journal",
        "operation_id",
        "permit",
        "refresh_abort_id",
        "refresh_latch_generation",
        "target_trade_id",
        "wallet_operation",
    )

    def __init__(
        self,
        *,
        adapter,
        binding,
        creator_thread_id,
        deadline,
        intent_id,
        journal,
        operation_id,
        permit,
        refresh_abort_id,
        refresh_latch_generation,
        target_trade_id,
        wallet_operation,
    ):
        self.adapter = adapter
        self.binding = binding
        self.creator_thread_id = creator_thread_id
        self.deadline = deadline
        self.intent_id = intent_id
        self.journal = journal
        self.operation_id = operation_id
        self.permit = permit
        self.refresh_abort_id = refresh_abort_id
        self.refresh_latch_generation = refresh_latch_generation
        self.target_trade_id = target_trade_id
        self.wallet_operation = wallet_operation


_offer_creation_continuation_lock = threading.RLock()
_wallet_identity_observation_lock = threading.RLock()
_offer_creation_continuations: dict[
    _OfferCreationContinuation, _OfferCreationContinuationState
] = {}


def _exact_continuation_text(value, name: str) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise ValueError(f"{name} must be non-empty canonical text")
    if value != value.strip() or any(ord(character) < 0x20 for character in value):
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


def _exact_continuation_trade_id(value) -> str:
    trade_id = _exact_continuation_text(value, "trade_id")
    if len(trade_id) != 64 or trade_id.lower() != trade_id:
        raise ValueError("trade_id must be canonical lowercase hex")
    try:
        bytes.fromhex(trade_id)
    except ValueError as exc:
        raise ValueError("trade_id must be canonical lowercase hex") from exc
    return trade_id


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_identity_observation(snapshot: dict, decision: dict) -> dict:
    return {
        "backend": snapshot["backend"],
        "name": snapshot["name"],
        "fingerprint": snapshot["fingerprint"],
        "network_id": snapshot["network_id"],
        "kind": snapshot["kind"],
        "has_secrets": snapshot["has_secrets"],
        "observed_at_utc": decision["observed_at_utc"],
    }


def _begin_offer_operation_continuation(
    *,
    operation_id: str,
    intent_id: str,
    wallet_operation: str,
    target_trade_id: str = None,
    ttl_seconds: int = 30,
    refresh_abort_id: str = None,
    refresh_latch_generation: int = None,
):
    operation = _exact_continuation_text(operation_id, "operation_id")
    intent = _exact_continuation_text(intent_id, "intent_id")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 60:
        raise ValueError("ttl_seconds must be an exact integer from 1 to 60")
    cleanup = refresh_abort_id is not None or refresh_latch_generation is not None
    if cleanup and (
        wallet_operation != "wallet:cancel_offer"
        or target_trade_id is None
        or type(refresh_abort_id) is not str
        or len(refresh_abort_id) != 64
        or any(char not in "0123456789abcdef" for char in refresh_abort_id)
        or type(refresh_latch_generation) is not int
        or refresh_latch_generation < 1
    ):
        raise ValueError("exact refresh abort cleanup authority is required")
    permit = None
    try:
        cleanup_snapshot = _read_refresh_abort_cleanup_snapshot() if cleanup else None
        if cleanup:
            permit = mutation_gate.enter_refresh_abort_cleanup_wallet_mutation(
                abort_id=refresh_abort_id,
                trade_id=target_trade_id,
                expected_latch_generation=refresh_latch_generation,
                observed_trade_ids=cleanup_snapshot["trade_ids"],
                observed_pending_transaction_ids=cleanup_snapshot[
                    "pending_transaction_ids"
                ],
                observed_at=cleanup_snapshot["observed_at"],
            )
            binding, adapter = (
                mutation_gate.require_refresh_abort_cleanup_wallet_permit_authority(
                    permit,
                    abort_id=refresh_abort_id,
                    trade_id=target_trade_id,
                    operation=f"{wallet_operation}:continuation:acquire",
                )
            )
        else:
            permit = mutation_gate.enter_wallet_mutation(wallet_operation)
            binding, adapter = mutation_gate.require_wallet_mutation_permit_authority(
                permit,
                f"{wallet_operation}:continuation:acquire",
            )
        if binding.backend != WALLET_TYPE or adapter is not _wallet_adapter:
            raise mutation_gate.MutationBlocked(
                "WALLET_IDENTITY_BINDING_INVALID",
                wallet_operation,
            )
        authority = mutation_gate.wallet_mutation_permit_journal_authority(
            permit,
            f"{wallet_operation}:continuation:journal",
        )
        with _wallet_identity_observation_lock:
            snapshot = _identity_from_adapter(adapter)
            if cleanup:
                decision = (
                    mutation_gate.require_fresh_refresh_abort_cleanup_wallet_identity(
                        permit,
                        snapshot,
                        abort_id=refresh_abort_id,
                        trade_id=target_trade_id,
                        expected_latch_generation=refresh_latch_generation,
                        observed_trade_ids=cleanup_snapshot["trade_ids"],
                        observed_pending_transaction_ids=cleanup_snapshot[
                            "pending_transaction_ids"
                        ],
                        observed_at=cleanup_snapshot["observed_at"],
                    )
                )
            else:
                mutation_gate.require_wallet_mutation_permit_authority(
                    permit,
                    f"{wallet_operation}:continuation:identity",
                )
                decision = mutation_gate.require_fresh_wallet_identity(
                    binding,
                    snapshot,
                    f"{wallet_operation}:continuation",
                )
        if cleanup:
            mutation_gate.require_refresh_abort_cleanup_wallet_permit_authority(
                permit,
                abort_id=refresh_abort_id,
                trade_id=target_trade_id,
                operation=f"{wallet_operation}:continuation:dispatch",
            )
        else:
            mutation_gate.require_wallet_mutation_permit_authority(
                permit,
                f"{wallet_operation}:continuation:dispatch",
            )
        binding_payload = mutation_gate.wallet_identity_binding_payload(binding)
        binding_digest = mutation_gate.wallet_identity_binding_digest(binding)
        if authority.get("binding_digest", binding_digest) != binding_digest:
            raise mutation_gate.MutationBlocked(
                "WALLET_IDENTITY_BINDING_INVALID",
                wallet_operation,
            )
        observation = _canonical_identity_observation(snapshot, decision)
        observation_digest = hashlib.sha256(
            _canonical_json(observation).encode("utf-8")
        ).hexdigest()
        journal_snapshot = {
            "schema_version": 1,
            "operation_id": operation,
            "intent_id": intent,
            "binding": binding_payload,
            "binding_digest": binding_digest,
            "observation": observation,
            "observation_digest": observation_digest,
            "authority": authority,
        }
        if target_trade_id is not None:
            journal_snapshot["trade_id"] = target_trade_id
        journal = {
            "snapshot": journal_snapshot,
            "snapshot_sha256": hashlib.sha256(
                _canonical_json(journal_snapshot).encode("utf-8")
            ).hexdigest(),
        }
        continuation = _OfferCreationContinuation()
        state = _OfferCreationContinuationState(
            adapter=adapter,
            binding=binding,
            creator_thread_id=threading.get_ident(),
            deadline=time.monotonic() + ttl_seconds,
            intent_id=intent,
            journal=journal,
            operation_id=operation,
            permit=permit,
            refresh_abort_id=refresh_abort_id,
            refresh_latch_generation=refresh_latch_generation,
            target_trade_id=target_trade_id,
            wallet_operation=wallet_operation,
        )
        with _offer_creation_continuation_lock:
            _offer_creation_continuations[continuation] = state
        permit = None
        return continuation
    finally:
        if permit is not None:
            try:
                mutation_gate.exit_wallet_mutation(permit)
            except BaseException:
                pass


def begin_offer_creation_continuation(
    *,
    operation_id: str,
    intent_id: str,
    ttl_seconds: int = 30,
):
    """Enter offer authority before PREPARED and return an opaque one-shot handle."""

    return _begin_offer_operation_continuation(
        operation_id=operation_id,
        intent_id=intent_id,
        wallet_operation="wallet:create_offer",
        ttl_seconds=ttl_seconds,
    )


def begin_offer_cancel_continuation(
    *,
    operation_id: str,
    intent_id: str,
    trade_id: str,
    ttl_seconds: int = 30,
    refresh_abort_id: str = None,
    refresh_latch_generation: int = None,
):
    """Enter cancellation authority before PREPARED and return a one-shot handle."""

    target_trade_id = _exact_continuation_trade_id(trade_id)
    return _begin_offer_operation_continuation(
        operation_id=operation_id,
        intent_id=intent_id,
        wallet_operation="wallet:cancel_offer",
        target_trade_id=target_trade_id,
        ttl_seconds=ttl_seconds,
        refresh_abort_id=refresh_abort_id,
        refresh_latch_generation=refresh_latch_generation,
    )


def offer_creation_continuation_journal(continuation) -> dict:
    """Return a detached canonical snapshot; never expose the held permit."""

    with _offer_creation_continuation_lock:
        state = _offer_creation_continuations.get(continuation)
        if state is None or threading.get_ident() != state.creator_thread_id:
            raise ValueError("offer creation continuation is invalid")
        return json.loads(_canonical_json(state.journal))


def offer_cancel_continuation_journal(continuation) -> dict:
    """Return the detached authority snapshot for a cancellation continuation."""

    return offer_creation_continuation_journal(continuation)


def refresh_offer_cancel_continuation(
    continuation,
    *,
    operation_id: str,
    intent_id: str,
    trade_id: str,
    ttl_seconds: int = 60,
) -> bool:
    """Refresh one held cancellation capability immediately before dispatch.

    Large cancellation cohorts acquire every capability before their PREPARED
    journal is committed.  A slow, definitive wallet failure may outlive the
    original process-local TTL for a later member.  Renewal is allowed only for
    the same creator thread and exact operation/intent/trade tuple, while the
    held permit still passes the mutation gate's exact PREPARED-blocker,
    current-lease, safety-latch, adapter, and fresh-wallet-identity checks.
    """

    try:
        operation = _exact_continuation_text(operation_id, "operation_id")
        intent = _exact_continuation_text(intent_id, "intent_id")
        target_trade_id = _exact_continuation_trade_id(trade_id)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 60:
            raise ValueError("ttl_seconds must be an exact integer from 1 to 60")
    except (TypeError, ValueError):
        return False

    with _offer_creation_continuation_lock:
        state = _offer_creation_continuations.get(continuation)
        if (
            state is None
            or threading.get_ident() != state.creator_thread_id
            or operation != state.operation_id
            or intent != state.intent_id
            or target_trade_id != state.target_trade_id
            or state.wallet_operation != "wallet:cancel_offer"
        ):
            return False

    try:
        with _wallet_identity_observation_lock:
            snapshot = _identity_from_adapter(state.adapter)
            if state.refresh_abort_id is not None:
                cleanup_snapshot = _read_refresh_abort_cleanup_snapshot()
                binding, adapter, _decision = (
                    mutation_gate.require_fresh_refresh_abort_cleanup_wallet_continuation(
                        state.permit,
                        snapshot,
                        abort_id=state.refresh_abort_id,
                        trade_id=state.target_trade_id,
                        expected_latch_generation=state.refresh_latch_generation,
                        observed_trade_ids=cleanup_snapshot["trade_ids"],
                        observed_pending_transaction_ids=cleanup_snapshot[
                            "pending_transaction_ids"
                        ],
                        observed_at=cleanup_snapshot["observed_at"],
                        prepared_operation_id=operation,
                    )
                )
            else:
                binding, adapter, _decision = (
                    mutation_gate.require_fresh_wallet_operation_continuation(
                        state.permit,
                        snapshot,
                        state.wallet_operation,
                        operation,
                        intent,
                    )
                )
        if (
            type(binding) is not mutation_gate.WalletIdentityBinding
            or mutation_gate.wallet_identity_binding_digest(binding)
            != mutation_gate.wallet_identity_binding_digest(state.binding)
            or adapter is not state.adapter
            or binding.backend != WALLET_TYPE
            or adapter is not _wallet_adapter
        ):
            return False
    except Exception:
        return False

    with _offer_creation_continuation_lock:
        if (
            _offer_creation_continuations.get(continuation) is not state
            or threading.get_ident() != state.creator_thread_id
        ):
            return False
        state.deadline = time.monotonic() + ttl_seconds
    return True


def close_offer_creation_continuation(continuation) -> bool:
    """Close an unused continuation and release its lifecycle permit exactly once."""

    with _offer_creation_continuation_lock:
        state = _offer_creation_continuations.pop(continuation, None)
    if state is None:
        return False
    try:
        return mutation_gate.exit_wallet_mutation(state.permit) is True
    except BaseException:
        return False


def close_offer_cancel_continuation(continuation) -> bool:
    """Close an unused cancellation continuation exactly once."""

    return close_offer_creation_continuation(continuation)


def _run_offer_operation_continuation(
    continuation,
    operation_id,
    intent_id,
    *,
    wallet_operation,
    adapter_method,
    blocked_result,
    callback_args,
    callback_kwargs,
    target_trade_id=None,
):
    with _offer_creation_continuation_lock:
        state = _offer_creation_continuations.pop(continuation, None)
    if state is None:
        return blocked_result()
    effect_attempted = False
    market_authorizer = callback_kwargs.pop("_market_authorizer", None)
    fee_authorizer = callback_kwargs.pop("_fee_authorizer", None)
    try:
        if market_authorizer is not None and not callable(market_authorizer):
            return blocked_result(
                "MARKET_CONFIDENCE_OVERRIDE_INACTIVE", effect_attempted=False
            )
        if fee_authorizer is not None and not callable(fee_authorizer):
            return blocked_result(
                "FEE_FOLLOW_AUTHORITY_REQUIRED", effect_attempted=False
            )
        try:
            operation = _exact_continuation_text(operation_id, "operation_id")
            intent = _exact_continuation_text(intent_id, "intent_id")
        except (TypeError, ValueError):
            return blocked_result()
        if (
            threading.get_ident() != state.creator_thread_id
            or time.monotonic() > state.deadline
            or operation != state.operation_id
            or intent != state.intent_id
            or wallet_operation != state.wallet_operation
            or target_trade_id != state.target_trade_id
        ):
            return blocked_result()
        if state.refresh_abort_id is not None:
            exact_target = state.target_trade_id
            if adapter_method == "cancel_offer":
                exact_dispatch = callback_args[0] == exact_target
            elif adapter_method == "cancel_offers_batch":
                exact_dispatch = type(callback_args[0]) is list and callback_args[
                    0
                ] == [exact_target]
            else:
                exact_dispatch = False
            if not exact_dispatch:
                return blocked_result("REFRESH_ABORT_TARGET_MISMATCH")
        with _wallet_identity_observation_lock:
            snapshot = _identity_from_adapter(state.adapter)
            if state.refresh_abort_id is not None:
                cleanup_snapshot = _read_refresh_abort_cleanup_snapshot()
                binding, adapter, _decision = (
                    mutation_gate.require_fresh_refresh_abort_cleanup_wallet_continuation(
                        state.permit,
                        snapshot,
                        abort_id=state.refresh_abort_id,
                        trade_id=state.target_trade_id,
                        expected_latch_generation=state.refresh_latch_generation,
                        observed_trade_ids=cleanup_snapshot["trade_ids"],
                        observed_pending_transaction_ids=cleanup_snapshot[
                            "pending_transaction_ids"
                        ],
                        observed_at=cleanup_snapshot["observed_at"],
                        prepared_operation_id=operation,
                    )
                )
            else:
                binding, adapter, _decision = (
                    mutation_gate.require_fresh_wallet_operation_continuation(
                        state.permit,
                        snapshot,
                        wallet_operation,
                        operation,
                        intent,
                    )
                )
        if (
            type(binding) is not mutation_gate.WalletIdentityBinding
            or mutation_gate.wallet_identity_binding_digest(binding)
            != mutation_gate.wallet_identity_binding_digest(state.binding)
            or adapter is not state.adapter
            or binding.backend != WALLET_TYPE
            or adapter is not _wallet_adapter
        ):
            raise mutation_gate.MutationBlocked(
                "WALLET_IDENTITY_BINDING_INVALID",
                wallet_operation,
            )

        def identity_recheck(step: str) -> None:
            nonlocal effect_attempted
            safe_step = (
                step if type(step) is str and step and len(step) <= 64 else "effect"
            )
            with _wallet_identity_observation_lock:
                fresh_snapshot = _identity_from_adapter(adapter)
                if state.refresh_abort_id is not None:
                    cleanup_snapshot = _read_refresh_abort_cleanup_snapshot()
                    checked_binding, checked_adapter, _step_decision = (
                        mutation_gate.require_fresh_refresh_abort_cleanup_wallet_continuation(
                            state.permit,
                            fresh_snapshot,
                            abort_id=state.refresh_abort_id,
                            trade_id=state.target_trade_id,
                            expected_latch_generation=state.refresh_latch_generation,
                            observed_trade_ids=cleanup_snapshot["trade_ids"],
                            observed_pending_transaction_ids=cleanup_snapshot[
                                "pending_transaction_ids"
                            ],
                            observed_at=cleanup_snapshot["observed_at"],
                            prepared_operation_id=operation,
                        )
                    )
                else:
                    checked_binding, checked_adapter, _step_decision = (
                        mutation_gate.require_fresh_wallet_operation_continuation(
                            state.permit,
                            fresh_snapshot,
                            f"{wallet_operation}:{safe_step}:identity",
                            operation,
                            intent,
                        )
                    )
            if (
                mutation_gate.wallet_identity_binding_digest(checked_binding)
                != mutation_gate.wallet_identity_binding_digest(binding)
                or checked_adapter is not adapter
            ):
                raise mutation_gate.MutationBlocked(
                    "WALLET_IDENTITY_BINDING_INVALID",
                    f"{wallet_operation}:{safe_step}",
                )
            if market_authorizer is not None and market_authorizer() is not True:
                raise mutation_gate.MutationBlocked(
                    "MARKET_CONFIDENCE_OVERRIDE_INACTIVE", wallet_operation
                )
            if fee_authorizer is not None and fee_authorizer() is not True:
                raise mutation_gate.MutationBlocked(
                    "FEE_FOLLOW_AUTHORITY_REQUIRED", wallet_operation
                )
            # Sage's create_offer rechecks identity while preparing the RPC.
            # Only the final send check can precede a wallet effect. A safety
            # stop during preparation must remain a proven pre-send failure.
            if (
                wallet_operation != "wallet:create_offer"
                or WALLET_TYPE != "sage"
                or safe_step in {"rpc:make_offer:send", "rpc:make_offer:retry_send"}
            ):
                effect_attempted = True

        callback_kwargs["_identity_recheck"] = identity_recheck
        callback = getattr(adapter, adapter_method)
        result = callback(*callback_args, **callback_kwargs)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            return blocked_result(
                "WALLET_BACKEND_UNSUPPORTED",
                effect_attempted=effect_attempted,
            )
        if type(result) is not dict:
            return blocked_result(
                "WALLET_MUTATION_FAILED",
                effect_attempted=effect_attempted,
            )
        result = dict(result)
        result["_catalyst_effect_attempted"] = effect_attempted
        return result
    except mutation_gate.MutationBlocked as exc:
        return blocked_result(
            exc.reason_code,
            effect_attempted=effect_attempted,
        )
    except Exception:
        return blocked_result(
            "WALLET_MUTATION_FAILED",
            effect_attempted=effect_attempted,
        )
    finally:
        try:
            mutation_gate.exit_wallet_mutation(state.permit)
        except BaseException:
            pass


def _run_offer_creation_continuation(
    continuation,
    operation_id,
    intent_id,
    *args,
    **kwargs,
):
    return _run_offer_operation_continuation(
        continuation,
        operation_id,
        intent_id,
        wallet_operation="wallet:create_offer",
        adapter_method="create_offer",
        blocked_result=_blocked_offer_creation_continuation,
        callback_args=args,
        callback_kwargs=kwargs,
        target_trade_id=None,
    )


def _require_bound_target_fingerprint(
    target, binding: mutation_gate.WalletIdentityBinding, operation: str
) -> int:
    """Require an identity-selecting target to match the frozen binding exactly."""

    if type(target) is not int or target <= 0:
        raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MALFORMED", operation)
    if target != binding.fingerprint:
        raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MISMATCH", operation)
    return target


def _bind_identity_selecting_arguments(
    export_name: str,
    args: tuple,
    binding: mutation_gate.WalletIdentityBinding,
    operation: str,
) -> tuple:
    """Validate or fill targets for operations that can switch active identity."""

    if export_name == "sage_login":
        if len(args) < 2 or type(args[1]) is not bool:
            raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MALFORMED", operation)
        _require_bound_target_fingerprint(args[0], binding, operation)
    elif export_name == "set_change_address":
        if len(args) < 2:
            raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MALFORMED", operation)
        fingerprint = args[1]
        if fingerprint is None:
            fingerprint = binding.fingerprint
            args = (*args[:1], fingerprint, *args[2:])
        _require_bound_target_fingerprint(fingerprint, binding, operation)
    elif export_name == "rpc":
        endpoint = args[0] if args else None
        if type(endpoint) is not str:
            raise mutation_gate.MutationBlocked("WALLET_IDENTITY_MALFORMED", operation)
        if endpoint in {"login", "log_in", "resync"}:
            payload = args[1] if len(args) > 1 else None
            if type(payload) is not dict or set(payload) != {"fingerprint"}:
                raise mutation_gate.MutationBlocked(
                    "WALLET_IDENTITY_MALFORMED", operation
                )
            target = _require_bound_target_fingerprint(
                payload["fingerprint"], binding, operation
            )
            args = (endpoint, {"fingerprint": target}, *args[2:])
    return args


def wallet_mutation_succeeded(result) -> bool:
    """Interpret legacy bool and structured mutation results without truthiness."""

    return result is True or (
        isinstance(result, dict) and result.get("success") is True
    )


def wallet_batch_results(result, item_ids) -> dict:
    """Expand a top-level guarded denial into the legacy per-item result shape."""

    if type(result) is dict and result.get("success") is False:
        return {str(item_id): dict(result) for item_id in item_ids}
    if type(result) is dict:
        return result
    failure = {
        "success": False,
        "error": "Wallet mutation returned malformed batch result",
        "reason": "WALLET_MUTATION_FAILED",
    }
    return {str(item_id): dict(failure) for item_id in item_ids}


def wallet_mutation_count(result) -> int:
    """Interpret legacy count results without treating a denial dict as a count."""

    return result if type(result) is int and result >= 0 else 0


def _expected_identity_authority() -> tuple[
    mutation_gate.WalletIdentityBinding, object
]:
    """Return the frozen binding and adapter selected at authority acquisition."""

    candidate_adapter = _wallet_adapter
    runtime = mutation_gate.current_runtime()
    if runtime is not None:
        binding = runtime.require_wallet_identity_authority("wallet:identity")
        adapter = runtime.require_wallet_adapter_authority(
            candidate_adapter, "wallet:identity"
        )
        if (
            type(binding) is mutation_gate.WalletIdentityBinding
            and binding.backend == WALLET_TYPE
        ):
            return binding, adapter
        raise mutation_gate.MutationBlocked(
            "WALLET_IDENTITY_BINDING_INVALID", "wallet:identity"
        )

    delegated = mutation_gate.worker_identity_lease_binding()
    if not isinstance(delegated, dict):
        raise mutation_gate.MutationBlocked(
            "MUTATION_RUNTIME_NOT_INITIALIZED", "wallet:identity"
        )
    try:
        binding = delegated["binding"]
        digest = delegated["binding_digest"]
        adapter = mutation_gate.worker_wallet_adapter_authority(
            candidate_adapter, "wallet:identity"
        )
        valid = (
            type(binding) is mutation_gate.WalletIdentityBinding
            and type(digest) is str
            and mutation_gate.wallet_identity_binding_digest(binding) == digest
            and binding.backend == WALLET_TYPE
            and mutation_gate.wallet_fingerprint_hash(binding.fingerprint)
            == delegated["wallet_fingerprint_hash"]
            and binding.network_id == delegated["network"].lower()
            and binding.bound_at_utc == delegated["bound_at_utc"]
        )
    except Exception:
        valid = False
    if not valid:
        raise mutation_gate.MutationBlocked(
            "WALLET_IDENTITY_BINDING_INVALID", "wallet:identity"
        )
    return binding, adapter


def _expected_identity_binding() -> mutation_gate.WalletIdentityBinding:
    """Return the lease/delegation-bound exact identity expected for mutation."""

    return _expected_identity_authority()[0]


def _identity_from_adapter(adapter) -> dict:
    """Observe identity through one already-authorized adapter object."""

    return adapter.get_wallet_identity()


def _revalidate_adapter_authority(adapter, operation: str) -> None:
    runtime = mutation_gate.current_runtime()
    if runtime is not None:
        runtime.require_wallet_adapter_authority(adapter, operation)
        return
    mutation_gate.worker_wallet_adapter_authority(adapter, operation)


def get_wallet_identity() -> dict:
    """Read identity directly from the selected adapter; this is never cached."""

    try:
        runtime = mutation_gate.current_runtime()
        if runtime is not None:
            adapter = runtime.require_wallet_adapter_authority(
                _wallet_adapter, "wallet:identity:read"
            )
        else:
            adapter = _wallet_adapter
        result = _identity_from_adapter(adapter)
    except Exception:
        return {
            "success": False,
            "backend": WALLET_TYPE,
            "name": None,
            "fingerprint": None,
            "network_id": None,
            "kind": None,
            "has_secrets": None,
            "observed_at_utc": "",
            "error": "identity_lookup_failed",
        }
    return result


def get_wallet_identity_for_recovery() -> dict:
    """Read the selected adapter identity while a durable latch fences effects."""
    try:
        return _identity_from_adapter(_wallet_adapter)
    except Exception:
        return {"success": False}


def preflight_wallet_identity() -> dict:
    """Read-only UX preflight; the mutation-bound read remains authoritative."""

    try:
        binding, adapter = _expected_identity_authority()
        snapshot = _identity_from_adapter(adapter)
        _revalidate_adapter_authority(adapter, "wallet:preflight")
        decision = mutation_gate.validate_wallet_identity(binding, snapshot)
        if decision.get("allowed") is True:
            return {"success": True, "reason": "identity_verified"}
        return _blocked_mutation(str(decision.get("reason") or ""))
    except mutation_gate.MutationBlocked as exc:
        return _blocked_mutation(exc.reason_code)
    except Exception:
        return _blocked_mutation("WALLET_IDENTITY_MALFORMED")


def validate_runtime_target_fingerprint(target) -> dict:
    """Reject identity selection that differs from the active runtime authority."""

    operation = "wallet:select_fingerprint"
    try:
        runtime = mutation_gate.current_runtime()
        if runtime is None:
            raise mutation_gate.MutationBlocked(
                "MUTATION_RUNTIME_NOT_INITIALIZED", operation
            )
        binding = runtime.require_wallet_identity_authority(operation)
        _require_bound_target_fingerprint(target, binding, operation)
        return {"success": True, "reason": "identity_target_verified"}
    except mutation_gate.MutationBlocked as exc:
        return _blocked_mutation(exc.reason_code)
    except Exception:
        return _blocked_mutation("WALLET_IDENTITY_MALFORMED")


def _run_wallet_mutation_with_authority(
    facade_authority: object, export_name: str, *args, **kwargs
):
    operation = f"wallet:{export_name}"
    permit = None
    effect_attempted = False
    wallet_authority = None

    def authoritative_result(value):
        if export_name in _LEGACY_BOOLEAN_MUTATION_EXPORTS and value is True:
            value = {"success": True}
        elif type(value) is not dict:
            value = _blocked_mutation("WALLET_MUTATION_FAILED")
        value = dict(value)
        value["_catalyst_effect_attempted"] = effect_attempted
        if wallet_authority is not None:
            attestation = _issue_wallet_effect_adapter_outcome_attestation(
                facade_authority,
                wallet_operation=operation,
                wallet_authority=wallet_authority,
                effect_attempted=effect_attempted,
            )
            if attestation is not None:
                value["_catalyst_wallet_effect_attestation"] = attestation
        return value

    try:
        permit = mutation_gate.enter_wallet_mutation(operation)
        binding, adapter = mutation_gate.require_wallet_mutation_permit_authority(
            permit, f"{operation}:acquire"
        )
        if binding.backend != WALLET_TYPE or adapter is not _wallet_adapter:
            raise mutation_gate.MutationBlocked(
                "WALLET_IDENTITY_BINDING_INVALID", operation
            )
        wallet_authority = mutation_gate.wallet_mutation_permit_journal_authority(
            permit, f"{operation}:authority"
        )
        wallet_authority = dict(wallet_authority)
        wallet_authority["wallet_fingerprint_hash"] = (
            mutation_gate.wallet_fingerprint_hash(binding.fingerprint)
        )
        wallet_authority["network"] = binding.network_id
        args = _bind_identity_selecting_arguments(export_name, args, binding, operation)
        is_identity_transition = export_name == "sage_login"
        if not is_identity_transition:
            with _wallet_identity_observation_lock:
                snapshot = _identity_from_adapter(adapter)
                mutation_gate.require_wallet_mutation_permit_authority(
                    permit, f"{operation}:identity"
                )
                mutation_gate.require_fresh_wallet_identity(
                    binding, snapshot, operation
                )
        mutation_gate.require_wallet_mutation_permit_authority(
            permit, f"{operation}:dispatch"
        )
        if export_name in _COMPOUND_MUTATION_EXPORTS:

            def identity_recheck(step: str) -> None:
                safe_step = (
                    step if type(step) is str and step and len(step) <= 64 else "effect"
                )
                with _wallet_identity_observation_lock:
                    mutation_gate.require_wallet_mutation_permit_authority(
                        permit, f"{operation}:{safe_step}:identity"
                    )
                    if not is_identity_transition:
                        fresh_snapshot = _identity_from_adapter(adapter)
                        mutation_gate.require_fresh_wallet_identity(
                            binding,
                            fresh_snapshot,
                            f"{operation}:{safe_step}",
                        )
                mutation_gate.require_wallet_mutation_permit_authority(
                    permit, f"{operation}:{safe_step}:dispatch"
                )

            kwargs["_identity_recheck"] = identity_recheck
        callback = getattr(adapter, export_name)
        mutation_gate.require_wallet_mutation_permit_authority(
            permit, f"{operation}:effect"
        )
        effect_attempted = True
        result = callback(*args, **kwargs)
        if (
            export_name == "submit_built_transaction_rpc"
            and type(result) is dict
            and result.get("_catalyst_effect_attempted") is False
        ):
            # The trusted Sage adapter rejected an unvalidated unsigned effect
            # before signing. Preserve that exact no-effect assertion so the
            # durable claim can be released instead of being misclassified as
            # an ambiguous submission.
            effect_attempted = False
        mutation_gate.require_wallet_mutation_permit_authority(
            permit, f"{operation}:outcome"
        )
        if is_identity_transition and wallet_mutation_succeeded(result):
            with _wallet_identity_observation_lock:
                target_snapshot = _identity_from_adapter(adapter)
                mutation_gate.require_fresh_wallet_identity(
                    binding,
                    target_snapshot,
                    f"{operation}:postcondition",
                )
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            return authoritative_result(_blocked_mutation("WALLET_BACKEND_UNSUPPORTED"))
        return authoritative_result(result)
    except mutation_gate.MutationBlocked as exc:
        return authoritative_result(_blocked_mutation(exc.reason_code))
    except Exception:
        return authoritative_result(
            {
                "success": False,
                "error": "Wallet mutation failed after authorization",
                "reason": "WALLET_MUTATION_FAILED",
            }
        )
    finally:
        if permit is not None:
            try:
                mutation_gate.exit_wallet_mutation(permit)
            except BaseException:
                pass


def _build_wallet_mutation_runner(facade_authority: object):
    def run_wallet_mutation(export_name: str, *args, **kwargs):
        return _run_wallet_mutation_with_authority(
            facade_authority, export_name, *args, **kwargs
        )

    return run_wallet_mutation


_run_wallet_mutation = _build_wallet_mutation_runner(
    _take_wallet_effect_adapter_facade_authority()
)
del _build_wallet_mutation_runner
del _take_wallet_effect_adapter_facade_authority


def get_wallet_balance(wallet_id: int):
    """Read-only balance calls remain available while mutation is blocked."""

    return _wallet_adapter.get_wallet_balance(wallet_id)


def get_cat_metadata_snapshot():
    """Read actual Sage CAT metadata without configured discovery fallbacks."""
    if WALLET_TYPE != "sage":
        return {"success": False, "reason": "WALLET_BACKEND_UNSUPPORTED"}
    return _wallet_adapter.rpc("get_cats", {}, timeout=10)


def get_current_key():
    """Return the active key through the backend-neutral read-only facade."""

    callback = getattr(_wallet_adapter, "get_current_key", None)
    if callable(callback):
        return callback()
    result = _wallet_adapter.rpc("get_logged_in_fingerprint", {}, timeout=5)
    if type(result) is not dict or result.get("success") is not True:
        return None
    fingerprint = result.get("fingerprint")
    return {"fingerprint": fingerprint} if type(fingerprint) is int else None


def get_pending_transactions():
    """Return pending transactions without initializing or mutating the wallet."""

    callback = getattr(_wallet_adapter, "get_pending_transactions", None)
    return callback() if callable(callback) else None


def get_pending_transactions_strict() -> list | None:
    """Return only a native, complete pending list for recovery proof."""
    callback = getattr(_wallet_adapter, "get_pending_transactions_strict", None)
    return callback() if callable(callback) else None


def get_authoritative_offers_by_ids(offer_ids: tuple[str, ...]) -> dict | None:
    """Read exact Sage offer rows through the selected read-only adapter."""
    callback = getattr(_wallet_adapter, "get_authoritative_offers_by_ids", None)
    return callback(offer_ids) if callable(callback) else None


def get_recovery_active_offers_by_ids(offer_ids: tuple[str, ...]) -> dict | None:
    """Read exact active offer identities from native Sage responses."""
    callback = getattr(_wallet_adapter, "get_recovery_active_offers_by_ids", None)
    return callback(offer_ids) if callable(callback) else None


def _read_refresh_abort_cleanup_snapshot() -> dict:
    """Read the complete Sage wallet book and pending effects for fenced cleanup."""

    if WALLET_TYPE != "sage":
        raise ValueError("refresh abort cleanup requires Sage wallet authority")
    from offer_reconciliation import load_sage_offer_history

    history = load_sage_offer_history(
        get_all_offers=get_authoritative_offer_history,
        include_completed=False,
        page_size=500,
        max_pages=20,
    )
    if (
        history.get("complete") is not True
        or history.get("read_error") is not None
        or history.get("pagination", {}).get("authoritative_end") is not True
    ):
        raise ValueError("complete Sage offer book is unavailable")
    trade_ids = []
    for offer in history["records"]:
        if type(offer) is not dict:
            raise ValueError("complete Sage offer book is malformed")
        aliases = [offer[key] for key in ("trade_id", "offer_id") if key in offer]
        if (
            not aliases
            or any(
                type(value) is not str
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in aliases
            )
            or len(set(aliases)) != 1
        ):
            raise ValueError("complete Sage offer identity is malformed")
        trade_ids.append(aliases[0])
    if len(trade_ids) != len(set(trade_ids)):
        raise ValueError("complete Sage offer book has duplicate identities")
    pending = get_pending_transactions()
    if type(pending) is not list or len(pending) > 256:
        raise ValueError("complete Sage pending transaction read is unavailable")
    pending_ids = []
    for transaction in pending:
        if type(transaction) is not dict:
            raise ValueError("Sage pending transaction is malformed")
        transaction_id = transaction.get("transaction_id")
        if (
            type(transaction_id) is not str
            or len(transaction_id) != 64
            or any(char not in "0123456789abcdef" for char in transaction_id)
        ):
            raise ValueError("Sage pending transaction identity is malformed")
        pending_ids.append(transaction_id)
    return {
        "trade_ids": sorted(trade_ids),
        "pending_transaction_ids": sorted(pending_ids),
        "observed_at": datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }


def get_transaction_relay_outcome(transaction_id: str):
    """Return a read-only native-wallet peer-relay outcome when available."""

    callback = getattr(_wallet_adapter, "get_transaction_relay_outcome", None)
    if not callable(callback):
        return {"status": "unknown", "transaction_id": str(transaction_id or "")}
    try:
        result = callback(transaction_id)
    except Exception:
        return {"status": "unknown", "transaction_id": str(transaction_id or "")}
    return (
        result
        if type(result) is dict
        else {
            "status": "unknown",
            "transaction_id": str(transaction_id or ""),
        }
    )


def get_next_address(wallet_id: int = WALLET_ID_XCH, new_address: bool = True):
    """Guard derivation-state changes while keeping existing-address reads usable."""

    if new_address is True:
        return _run_wallet_mutation("get_next_address", wallet_id, True)
    return _wallet_adapter.get_next_address(wallet_id, new_address=False)


_READ_ONLY_RPC_ENDPOINTS = frozenset(
    {
        "get_coins",
        "get_logged_in_fingerprint",
        "get_version",
    }
)

_RPC_ENDPOINT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _rpc_arguments_are_exact(endpoint, payload, timeout) -> bool:
    """Accept only canonical RPC request types at the backend-neutral boundary."""

    return (
        type(endpoint) is str
        and 1 <= len(endpoint) <= 64
        and endpoint[0] in "abcdefghijklmnopqrstuvwxyz"
        and all(character in _RPC_ENDPOINT_CHARS for character in endpoint)
        and type(payload) is dict
        and type(timeout) is int
        and 1 <= timeout <= 300
    )


def rpc(endpoint: str, payload: dict, timeout: int = 10):
    """Default unknown generic RPC endpoints to the guarded mutation path."""

    if not _rpc_arguments_are_exact(endpoint, payload, timeout):
        return _blocked_mutation("WALLET_IDENTITY_MALFORMED")
    if endpoint in _READ_ONLY_RPC_ENDPOINTS:
        return _wallet_adapter.rpc(endpoint, payload, timeout)
    return _run_wallet_mutation("rpc", endpoint, payload, timeout)


_READ_ONLY_FULL_NODE_RPC_ENDPOINTS = frozenset(
    {
        "get_blockchain_state",
        "get_connections",
        "get_fee_estimate",
    }
)


def full_node_rpc(endpoint: str, payload: dict, timeout: int = 5):
    """Default unknown full-node RPC endpoints to the guarded mutation path."""

    if type(endpoint) is str and endpoint in _READ_ONLY_FULL_NODE_RPC_ENDPOINTS:
        return _wallet_adapter.full_node_rpc(endpoint, payload, timeout)
    return _run_wallet_mutation("full_node_rpc", endpoint, payload, timeout)


def split_coins_rpc(
    wallet_id: int,
    target_coin_id: str,
    num_coins: int,
    amount_per_coin: int,
    fee_mojos: int = 0,
    is_cat: bool = False,
):
    return _run_wallet_mutation(
        "split_coins_rpc",
        wallet_id,
        target_coin_id,
        num_coins,
        amount_per_coin,
        fee_mojos,
        is_cat,
    )


def split_coins_bulk(
    wallet_id: int,
    num_coins: int,
    coin_size_mojos: int,
    fee_mojos: int = 0,
    reserve_multiplier: float = 2.0,
    is_cat: bool = False,
    cat_decimals: int = 3,
):
    return _run_wallet_mutation(
        "split_coins_bulk",
        wallet_id,
        num_coins,
        coin_size_mojos,
        fee_mojos,
        reserve_multiplier,
        is_cat,
        cat_decimals,
    )


def send_transaction(
    wallet_id: int,
    amount_mojos: int,
    address: str,
    fee_mojos: int = 0,
    source_coin_ids: list = None,
):
    kwargs = {}
    if WALLET_TYPE == "sage":
        kwargs["source_coin_ids"] = source_coin_ids
    elif source_coin_ids:
        return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
    return _run_wallet_mutation(
        "send_transaction",
        wallet_id,
        amount_mojos,
        address,
        fee_mojos,
        **kwargs,
    )


def send_transaction_multi(payments: list, fee_mojos: int = 0):
    return _run_wallet_mutation("send_transaction_multi", payments, fee_mojos)


def create_offer(
    offer_dict: dict,
    validate_only: bool = _ADAPTER_DEFAULT,
    max_time: int = None,
    _reuse_puzhash: bool = _ADAPTER_DEFAULT,
    min_coin_amount: int = None,
    max_coin_amount: int = None,
    coin_ids: list = None,
    fee_mojos: int = 0,
    _creation_continuation=None,
    _creation_operation_id: str = None,
    _creation_intent_id: str = None,
    _market_authorizer=None,
):
    if validate_only is _ADAPTER_DEFAULT:
        validate_only = WALLET_TYPE == "chia"
    if _reuse_puzhash is _ADAPTER_DEFAULT:
        _reuse_puzhash = WALLET_TYPE == "sage"
    kwargs = {
        "validate_only": validate_only,
        "max_time": max_time,
        "_reuse_puzhash": _reuse_puzhash,
        "min_coin_amount": min_coin_amount,
        "max_coin_amount": max_coin_amount,
        "coin_ids": coin_ids,
    }
    if WALLET_TYPE == "sage":
        kwargs["fee_mojos"] = fee_mojos
    elif fee_mojos:
        return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
    continuation_arguments = (
        _creation_continuation,
        _creation_operation_id,
        _creation_intent_id,
    )
    if any(value is not None for value in continuation_arguments):
        if not all(value is not None for value in continuation_arguments):
            return _blocked_offer_creation_continuation()
        if _market_authorizer is not None:
            if not callable(_market_authorizer):
                return _blocked_offer_creation_continuation()
            kwargs["_market_authorizer"] = _market_authorizer
        return _run_offer_creation_continuation(
            _creation_continuation,
            _creation_operation_id,
            _creation_intent_id,
            offer_dict,
            **kwargs,
        )
    if _market_authorizer is not None:
        return _blocked_offer_creation_continuation(
            "OFFER_CREATION_JOURNAL_REQUIRED", effect_attempted=False
        )
    return _run_wallet_mutation("create_offer", offer_dict, **kwargs)


def cancel_offer(
    trade_id: str,
    secure: bool = True,
    timeout: int = 60,
    fee_mojos: int = None,
    _cancel_continuation=None,
    _cancel_operation_id: str = None,
    _cancel_intent_id: str = None,
):
    continuation_arguments = (
        _cancel_continuation,
        _cancel_operation_id,
        _cancel_intent_id,
    )
    if any(value is not None for value in continuation_arguments):
        if not all(value is not None for value in continuation_arguments):
            return _blocked_offer_cancel_continuation()
        return _run_offer_operation_continuation(
            _cancel_continuation,
            _cancel_operation_id,
            _cancel_intent_id,
            wallet_operation="wallet:cancel_offer",
            adapter_method="cancel_offer",
            blocked_result=_blocked_offer_cancel_continuation,
            callback_args=(trade_id, secure, timeout, fee_mojos),
            callback_kwargs={},
            target_trade_id=(trade_id if type(trade_id) is str else None),
        )
    return _blocked_offer_cancel_continuation(
        "OFFER_CANCEL_JOURNAL_REQUIRED",
        effect_attempted=False,
    )


def cancel_offers_batch(
    trade_ids: list,
    secure: bool = True,
    max_workers: int = 3,
    fee_mojos: int = None,
    skip_confirmation: bool = False,
    *,
    source_coin_ids: list = None,
    fee_coin_id: str = None,
    _validated_unsigned: dict = None,
    _fee_authorizer=None,
    _cancel_continuation=None,
    _cancel_operation_id: str = None,
    _cancel_intent_id: str = None,
    _cancel_trade_id: str = None,
):
    def blocked_batch(
        reason_code: str = "OFFER_CANCEL_CONTINUATION_INVALID",
        *,
        effect_attempted: bool = False,
    ):
        result = {
            trade_id: _blocked_offer_cancel_continuation(
                reason_code,
                effect_attempted=effect_attempted,
            )
            for trade_id in trade_ids
            if type(trade_id) is str
        }
        result["_catalyst_effect_attempted"] = effect_attempted
        return result

    if type(trade_ids) is not list:
        return _blocked_offer_cancel_continuation(
            "OFFER_CANCEL_JOURNAL_REQUIRED",
            effect_attempted=False,
        )
    if _fee_authorizer is not None and (
        not callable(_fee_authorizer)
        or secure is not True
        or type(fee_mojos) is not int
        or fee_mojos <= 0
        or type(_validated_unsigned) is not dict
    ):
        return blocked_batch("FEE_FOLLOW_AUTHORITY_REQUIRED")
    continuation_arguments = (
        _cancel_continuation,
        _cancel_operation_id,
        _cancel_intent_id,
        _cancel_trade_id,
    )
    if any(value is not None for value in continuation_arguments):
        if not all(value is not None for value in continuation_arguments):
            return blocked_batch()
        callback_kwargs = {
            "source_coin_ids": source_coin_ids,
            "fee_coin_id": fee_coin_id,
        }
        if _validated_unsigned is not None:
            callback_kwargs["_validated_unsigned"] = _validated_unsigned
        if _fee_authorizer is not None:
            callback_kwargs["_fee_authorizer"] = _fee_authorizer
        return _run_offer_operation_continuation(
            _cancel_continuation,
            _cancel_operation_id,
            _cancel_intent_id,
            wallet_operation="wallet:cancel_offer",
            adapter_method="cancel_offers_batch",
            blocked_result=blocked_batch,
            callback_args=(
                trade_ids,
                secure,
                max_workers,
                fee_mojos,
                skip_confirmation,
            ),
            callback_kwargs=callback_kwargs,
            target_trade_id=_cancel_trade_id,
        )
    return {
        trade_id: _blocked_offer_cancel_continuation(
            "OFFER_CANCEL_JOURNAL_REQUIRED",
            effect_attempted=False,
        )
        for trade_id in trade_ids
        if type(trade_id) is str
    }


def cleanup_expired_offers(log_fn=None):
    return _run_wallet_mutation("cleanup_expired_offers", log_fn)


def _run_sage_mutation(export_name: str, *args, **kwargs):
    if WALLET_TYPE != "sage" or not hasattr(_wallet_adapter, export_name):
        return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
    return _run_wallet_mutation(export_name, *args, **kwargs)


def create_transaction_rpc(
    selected_coin_ids: list, actions: list, auto_submit: bool = True
):
    return _run_sage_mutation(
        "create_transaction_rpc", selected_coin_ids, actions, auto_submit
    )


def build_transaction_rpc(selected_coin_ids: list, actions: list):
    """Build an unsigned Sage transaction under the bound wallet identity.

    This cannot sign or submit. Its response must pass
    ``validate_unsigned_transaction_effect`` before the separately guarded
    submit entry point will accept it.
    """
    if WALLET_TYPE != "sage" or not hasattr(_wallet_adapter, "build_transaction_rpc"):
        return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
    try:
        binding, adapter = _expected_identity_authority()

        def identity_recheck(step: str) -> None:
            with _wallet_identity_observation_lock:
                _revalidate_adapter_authority(adapter, f"wallet:unsigned_build:{step}")
                mutation_gate.require_fresh_wallet_identity(
                    binding,
                    _identity_from_adapter(adapter),
                    f"wallet:unsigned_build:{step}",
                )

        identity_recheck("identity")
        result = adapter.build_transaction_rpc(
            selected_coin_ids, actions, _identity_recheck=identity_recheck
        )
        return (
            result
            if type(result) is dict
            else _blocked_mutation("WALLET_MUTATION_FAILED")
        )
    except mutation_gate.MutationBlocked as exc:
        return _blocked_mutation(exc.reason_code)
    except Exception:
        return _blocked_mutation("WALLET_MUTATION_FAILED")


def preview_coin_prep_rbf_unsigned(
    operation_id: str, original_transaction_id: str, fee_mojos: int
) -> dict:
    """Inspect one fee-only replacement while the exact prep latch is closed.

    This is intentionally separate from the normal unsigned builder: callers
    cannot supply coins, addresses or actions. Sage's v0.13.1
    ``create_transaction(auto_submit=false)`` only constructs an unsigned
    transaction. No signing or submission capability is exposed here.
    """
    from database import get_coin_prep_rbf_preview_authority

    def refuse(reason: str) -> dict:
        return {"success": False, "reason": reason}

    def hex_id(value) -> str:
        if type(value) is not str:
            raise ValueError("invalid coin identity")
        canonical = value.lower().removeprefix("0x")
        if re.fullmatch(r"[0-9a-f]{64}", canonical) is None:
            raise ValueError("invalid coin identity")
        return canonical

    def mojos(value) -> int:
        if type(value) is int and value >= 0:
            return value
        if type(value) is str and value.isascii() and value.isdigit():
            return int(value)
        raise ValueError("invalid exact amount")

    def xch_record(value) -> tuple[str, str, int]:
        if type(value) is not dict:
            raise ValueError("not a native XCH record")
        asset = value.get("asset")
        if asset is not None and (
            type(asset) is not dict
            or asset.get("asset_id") is not None
            or asset.get("ticker") != "XCH"
            or asset.get("kind") != "token"
        ):
            raise ValueError("not a native XCH record")
        address = value.get("address")
        if type(address) is not str or not address:
            raise ValueError("missing pending address")
        return hex_id(value.get("coin_id")), address, mojos(value.get("amount"))

    if WALLET_TYPE != "sage" or not callable(
        getattr(_wallet_adapter, "build_coin_prep_rbf_preview_rpc", None)
    ):
        return refuse("WALLET_BACKEND_UNSUPPORTED")
    if type(fee_mojos) is not int or fee_mojos < 10_000_000:
        return refuse("RBF_FEE_BELOW_MINIMUM")
    try:
        requested_tx = hex_id(original_transaction_id)
        authority = get_coin_prep_rbf_preview_authority(operation_id)
        operation = authority["operation"]
        latch = authority["latch"]
        identity_payload = json.loads(operation["wallet_identity_json"])
        binding = mutation_gate.WalletIdentityBinding(**identity_payload)
        if mutation_gate.wallet_identity_binding_payload(binding) != identity_payload:
            return refuse("WALLET_IDENTITY_BINDING_INVALID")
        source_ids = [
            hex_id(value) for value in json.loads(operation["source_coin_ids_json"])
        ]
        fee_ids = json.loads(operation["effect_fee_coin_ids_json"])
        target = json.loads(operation["target_contract_json"])
        blockers = json.loads(latch["blocking_operation_ids_json"])
        expected_blockers = sorted(
            [operation_id, f"wallet-effect:{operation['effect_claim_token']}"]
        )
        if (
            operation.get("outcome") != "SUBMITTED_UNKNOWN"
            or operation.get("operation_kind") != "split"
            or operation.get("purpose") != "fee_reserve"
            or operation.get("effect_adapter_operation") != operation_id
            or type(source_ids) is not list
            or len(source_ids) != 1
            or fee_ids != []
            or target.get("wallet_type") != "xch"
            or target.get("contract_version") is not None
            or latch.get("state") != "tripped"
            or latch.get("reason_code") != "COIN_PREP_RECOVERY_REQUIRED"
            or blockers != expected_blockers
            or latch.get("wallet_fingerprint_hash")
            != mutation_gate.wallet_fingerprint_hash(binding.fingerprint)
            or latch.get("network") != binding.network_id
        ):
            return refuse("COIN_PREP_RBF_PREVIEW_AUTHORITY_MISMATCH")
        version_reader = getattr(_wallet_adapter, "get_sage_version", None)
        if not callable(version_reader) or version_reader() != "0.13.1":
            return refuse("SAGE_RBF_PREVIEW_VERSION_UNSUPPORTED")

        def recheck(step: str) -> None:
            fresh = get_coin_prep_rbf_preview_authority(operation_id)
            if fresh != authority:
                raise ValueError("COIN_PREP_RBF_PREVIEW_AUTHORITY_CHANGED")
            if version_reader() != "0.13.1":
                raise ValueError("SAGE_RBF_PREVIEW_VERSION_CHANGED")
            decision = mutation_gate.validate_wallet_identity(
                binding, _identity_from_adapter(_wallet_adapter)
            )
            if decision.get("allowed") is not True:
                raise ValueError(str(decision.get("reason")))

        recheck("before_pending")
        pending = get_pending_transactions_strict()
        if type(pending) is not list:
            return refuse("SAGE_PENDING_VIEW_UNAVAILABLE")
        matches = [
            row
            for row in pending
            if type(row) is dict
            and type(row.get("transaction_id")) is str
            and hex_id(row["transaction_id"]) == requested_tx
        ]
        if len(matches) != 1:
            return refuse("ORIGINAL_PENDING_TRANSACTION_NOT_UNIQUE")
        source_pending = [
            row
            for row in pending
            if type(row) is dict
            and type(row.get("spent")) is list
            and any(
                type(spend) is dict and hex_id(spend.get("coin_id")) == source_ids[0]
                for spend in row["spent"]
            )
        ]
        if source_pending != matches:
            return refuse("ORIGINAL_PENDING_SOURCE_NOT_UNIQUE")
        old = matches[0]
        if mojos(old.get("fee")) != 0:
            return refuse("ORIGINAL_PENDING_FEE_MISMATCH")
        spent = [xch_record(row) for row in old["spent"]]
        created = [xch_record(row) for row in old["created"]]
        spent_ids = [row[0] for row in spent]
        created_ids = [row[0] for row in created]
        if (
            len(spent_ids) != len(set(spent_ids))
            or len(created_ids) != len(set(created_ids))
            or spent_ids.count(source_ids[0]) != 1
        ):
            return refuse("ORIGINAL_PENDING_INPUT_MISMATCH")
        ephemeral = set(spent_ids) - set(source_ids)
        if ephemeral != set(created_ids) & set(spent_ids):
            return refuse("ORIGINAL_PENDING_INPUT_MISMATCH")
        external = [row for row in created if row[0] not in ephemeral]
        old_outputs = target.get("outputs")
        if (
            type(old_outputs) is not list
            or len(old_outputs) != 5
            or len(external) != 5
            or sorted(row[2] for row in external)
            != sorted(mojos(row["amount_mojos"]) for row in old_outputs)
            or any(
                type(row) is not dict or row.get("output_index") != index
                for index, row in enumerate(old_outputs)
            )
            or any(row.get("purpose") != "fee_reserve" for row in old_outputs[:4])
            or old_outputs[4].get("purpose") != "top_up"
        ):
            return refuse("ORIGINAL_PENDING_OUTPUT_MISMATCH")
        source_amount = next(row[2] for row in spent if row[0] == source_ids[0])
        reserve_amounts = [mojos(row["amount_mojos"]) for row in old_outputs[:4]]
        old_change = mojos(old_outputs[4]["amount_mojos"])
        if source_amount != sum(reserve_amounts) + old_change:
            return refuse("ORIGINAL_PENDING_VALUE_MISMATCH")
        reserve_rows = [row for row in external if row[2] in reserve_amounts]
        change_rows = [row for row in external if row[2] == old_change]
        if (
            len(reserve_rows) != 4
            or len(change_rows) != 1
            or len({row[1] for row in reserve_rows}) != 1
            or old_change in reserve_amounts
        ):
            return refuse("ORIGINAL_PENDING_OUTPUT_MISMATCH")
        new_change = old_change - fee_mojos
        if new_change <= 0:
            return refuse("RBF_SOURCE_CAPACITY_UNAVAILABLE")
        address = reserve_rows[0][1]
        outputs = [
            {
                "asset": "xch",
                "address": address,
                "amount_mojos": amount,
                "purpose": "fee_reserve",
                "ordinal": index,
            }
            for index, amount in enumerate(reserve_amounts)
        ]
        outputs.append(
            {
                "asset": "xch",
                "address": change_rows[0][1],
                "amount_mojos": new_change,
                "purpose": "top_up",
                "ordinal": 4,
            }
        )
        recheck("before_unsigned_build")
        unsigned = _wallet_adapter.build_coin_prep_rbf_preview_rpc(
            source_ids[0], outputs, fee_mojos, _identity_recheck=recheck
        )
        recheck("after_unsigned_build")
        inspected = _wallet_adapter.inspect_unsigned_transaction_effect(
            unsigned,
            {
                "source_asset": "xch",
                "source_coin_ids": source_ids,
                "fee_coin_ids": [],
                "cat_asset_id": None,
                "fee_mojos": fee_mojos,
                "outputs": outputs,
            },
        )
        if (
            type(inspected) is not dict
            or inspected.get("_catalyst_executable_effect_bound") is not True
        ):
            return refuse("RBF_UNSIGNED_EFFECT_UNVERIFIED")
        preview_inputs = {
            hex_id(item["coin_id"]) for item in inspected["summary"]["inputs"]
        }
        if not set(spent_ids).issubset(preview_inputs):
            return refuse("RBF_ORIGINAL_INPUT_SUPERSET_MISMATCH")
        # The unsigned build can take long enough for the original transaction
        # to confirm or disappear. A preview must describe the same live
        # pending effect observed before the Sage call, not a stale candidate.
        pending_after = get_pending_transactions_strict()
        if type(pending_after) is not list:
            return refuse("SAGE_PENDING_VIEW_UNAVAILABLE")
        matching_after = [
            row
            for row in pending_after
            if type(row) is dict and hex_id(row.get("transaction_id")) == requested_tx
        ]
        if len(matching_after) != 1:
            return refuse("ORIGINAL_PENDING_CHANGED_DURING_PREVIEW")
        after = matching_after[0]
        if (
            mojos(after.get("fee")) != 0
            or sorted(xch_record(row) for row in after["spent"]) != sorted(spent)
            or sorted(xch_record(row) for row in after["created"]) != sorted(created)
        ):
            return refuse("ORIGINAL_PENDING_CHANGED_DURING_PREVIEW")
        source_after = [
            row
            for row in pending_after
            if type(row) is dict
            and type(row.get("spent")) is list
            and any(
                type(spend) is dict and hex_id(spend.get("coin_id")) == source_ids[0]
                for spend in row["spent"]
            )
        ]
        if source_after != matching_after:
            return refuse("ORIGINAL_PENDING_CHANGED_DURING_PREVIEW")
        recheck("after_pending_recheck")
        original_outputs = [
            {
                "coin_id": coin_id,
                "amount_mojos": amount,
                "purpose": "top_up" if amount == old_change else "fee_reserve",
            }
            for coin_id, _address, amount in external
        ]
        successor_outputs = [
            {
                "coin_id": hex_id(row["coin_id"]),
                "amount_mojos": mojos(row["amount_mojos"]),
                "purpose": row["purpose"],
            }
            for row in inspected["constructed_outputs"]
        ]
        return {
            "success": True,
            "operation_id": operation_id,
            "original_transaction_id": requested_tx,
            "provenance": "unique_exact_pending_effect_association",
            "fee_mojos": fee_mojos,
            "original_input_coin_ids": sorted(spent_ids),
            "original_outputs": original_outputs,
            "successor_outputs": successor_outputs,
            "new_change_mojos": new_change,
            "unsigned": inspected,
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return refuse("COIN_PREP_RBF_PREVIEW_UNAVAILABLE")
    except Exception:
        return refuse("COIN_PREP_RBF_PREVIEW_UNAVAILABLE")


def submit_reviewed_coin_prep_rbf(attempt_id: str) -> dict:
    """Submit exactly one durably reviewed fee-prep replacement.

    No coins, actions, fee or unsigned spends are accepted from the caller.
    The original transaction and sealed replacement are rebuilt and checked
    before a sign-only intent and the one-shot submit marker are committed.
    An uncertain outcome keeps the startup latch closed.
    """
    from coin_prep_rbf_pricing import quote_required_replacement_fee
    from database import (
        get_coin_prep_rbf_attempt_for_submit,
        get_coin_prep_rbf_preview_authority,
        record_coin_prep_rbf_sign_no_submit,
        record_coin_prep_rbf_sign_start,
        record_coin_prep_rbf_submit_start,
    )

    operation = "wallet:submit_coin_prep_rbf_rescue"
    permit = None
    sign_started = False
    submit_started = False
    sign_no_submit_reason = "PRE_SUBMIT_EXCEPTION"
    try:
        if WALLET_TYPE != "sage" or not callable(
            getattr(_wallet_adapter, "submit_reviewed_coin_prep_rbf_rpc", None)
        ):
            return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
        attempt = get_coin_prep_rbf_attempt_for_submit(attempt_id)
        operation_id = attempt["operation_id"]
        source_authority = get_coin_prep_rbf_preview_authority(operation_id)
        source_ids = json.loads(source_authority["operation"]["source_coin_ids_json"])
        if type(source_ids) is not list or len(source_ids) != 1:
            return _blocked_mutation("COIN_PREP_RBF_ATTEMPT_INVALID")
        source_id = source_ids[0].lower().removeprefix("0x")
        digest = attempt["unsigned_sha256"]
        generation = attempt["latch_generation"]
        original_tx = attempt["original_transaction_id"]
        fee = attempt["fee_mojos"]
        if (
            type(operation_id) is not str
            or type(digest) is not str
            or type(generation) is not int
            or type(fee) is not int
            or fee < 10_000_000
        ):
            return _blocked_mutation("COIN_PREP_RBF_ATTEMPT_INVALID")
        preview = preview_coin_prep_rbf_unsigned(operation_id, original_tx, fee)
        if preview.get("success") is not True:
            return _blocked_mutation(
                preview.get("reason") or "COIN_PREP_RBF_PREVIEW_UNAVAILABLE"
            )
        unsigned = preview["unsigned"]
        if (
            unsigned.get("_catalyst_executable_effect_bound") is not True
            or unsigned.get("_catalyst_unsigned_digest") != digest
        ):
            return _blocked_mutation("COIN_PREP_RBF_UNSIGNED_SEAL_CHANGED")
        constructed = sorted(
            (
                item["coin_id"].lower().removeprefix("0x"),
                item["amount_mojos"],
                item["purpose"],
            )
            for item in unsigned["constructed_outputs"]
        )
        reviewed = sorted(
            (item["coin_id"], item["amount_mojos"], item["purpose"])
            for item in json.loads(attempt["successor_outputs_json"])
        )
        if constructed != reviewed:
            return _blocked_mutation("COIN_PREP_RBF_OUTPUTS_CHANGED")
        cost = unsigned.get("_catalyst_exact_unsigned_cost")
        guidance = quote_required_replacement_fee(cost)
        if guidance.get("available") is not True or fee < guidance["minimum_fee_mojos"]:
            return _blocked_mutation("COIN_PREP_RBF_FEE_REVIEW_STALE")

        permit = mutation_gate.enter_coin_prep_rbf_rescue_wallet_mutation(
            attempt_id=attempt_id,
            operation_id=operation_id,
            expected_latch_generation=generation,
            unsigned_sha256=digest,
        )
        original_pending_fingerprint = None

        def recheck(step: str) -> None:
            nonlocal original_pending_fingerprint
            with _wallet_identity_observation_lock:
                binding, adapter, _decision = (
                    mutation_gate.require_fresh_coin_prep_rbf_rescue_wallet_continuation(
                        permit,
                        _identity_from_adapter(_wallet_adapter),
                        attempt_id=attempt_id,
                        operation_id=operation_id,
                        expected_latch_generation=generation,
                        unsigned_sha256=digest,
                        allow_dispatched=False,
                    )
                )
                if binding.backend != WALLET_TYPE or adapter is not _wallet_adapter:
                    raise mutation_gate.MutationBlocked(
                        "WALLET_IDENTITY_BINDING_INVALID", operation
                    )
            # A confirmed or replaced original must stop the pending
            # replacement before Sage receives another wallet effect.
            pending = get_pending_transactions_strict()
            if type(pending) is not list:
                raise mutation_gate.MutationBlocked(
                    "SAGE_PENDING_VIEW_UNAVAILABLE", operation
                )
            exact = [
                row
                for row in pending
                if type(row) is dict
                and str(row.get("transaction_id") or "").lower().removeprefix("0x")
                == original_tx
            ]
            if len(exact) != 1:
                raise mutation_gate.MutationBlocked(
                    "ORIGINAL_PENDING_CHANGED_DURING_RESCUE", operation
                )
            source_pending = [
                row
                for row in pending
                if type(row) is dict
                and type(row.get("spent")) is list
                and any(
                    type(spend) is dict
                    and str(spend.get("coin_id") or "").lower().removeprefix("0x")
                    == source_id
                    for spend in row["spent"]
                )
            ]
            if source_pending != exact:
                raise mutation_gate.MutationBlocked(
                    "ORIGINAL_PENDING_SOURCE_NOT_UNIQUE", operation
                )
            current_fingerprint = json.dumps(
                {
                    "fee": exact[0].get("fee"),
                    "spent": exact[0].get("spent"),
                    "created": exact[0].get("created"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            if original_pending_fingerprint is None:
                original_pending_fingerprint = current_fingerprint
            elif current_fingerprint != original_pending_fingerprint:
                raise mutation_gate.MutationBlocked(
                    "ORIGINAL_PENDING_CHANGED_DURING_RESCUE", operation
                )

        recheck("before_sign_intent")
        authority = mutation_gate.wallet_mutation_permit_journal_authority(
            permit, operation
        )
        record_coin_prep_rbf_sign_start(
            attempt_id,
            owner_run_id=authority["owner_run_id"],
            lease_version=authority["lease_version"],
        )
        sign_started = True

        def adapter_recheck(step: str) -> None:
            nonlocal submit_started
            recheck(step)
            if step == "rpc:submit_transaction:send":
                fresh_guidance = quote_required_replacement_fee(cost)
                if (
                    fresh_guidance.get("available") is not True
                    or fee < fresh_guidance["minimum_fee_mojos"]
                ):
                    raise mutation_gate.MutationBlocked(
                        "COIN_PREP_RBF_FEE_REVIEW_STALE", operation
                    )
                record_coin_prep_rbf_submit_start(
                    attempt_id,
                    owner_run_id=authority["owner_run_id"],
                    lease_version=authority["lease_version"],
                )
                submit_started = True

        result = _wallet_adapter.submit_reviewed_coin_prep_rbf_rpc(
            unsigned, _identity_recheck=adapter_recheck
        )
        if type(result) is not dict:
            result = _blocked_mutation("COIN_PREP_RBF_SUBMISSION_UNKNOWN")
        result = dict(result)
        if not submit_started:
            sign_no_submit_reason = (
                "SIGNED_BYTES_INVALID"
                if result.get("reason") == "RBF_SIGNED_SPENDS_MISMATCH"
                else "SIGN_REFUSED"
            )
        result["_catalyst_effect_attempted"] = submit_started
        return result
    except mutation_gate.MutationBlocked as exc:
        result = _blocked_mutation(exc.reason_code)
    except Exception:
        result = _blocked_mutation("COIN_PREP_RBF_SUBMISSION_UNKNOWN")
    finally:
        if sign_started and not submit_started:
            try:
                receipt_body = {
                    "attempt_id": attempt_id,
                    "reason_code": sign_no_submit_reason,
                    "submit_rpc_attempted": False,
                    "evidence_sha256": hashlib.sha256(
                        json.dumps(
                            {
                                "attempt_id": attempt_id,
                                "unsigned_sha256": digest,
                                "reason_code": sign_no_submit_reason,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                }
                record_coin_prep_rbf_sign_no_submit(attempt_id, receipt=receipt_body)
            except Exception:
                pass
        if permit is not None:
            try:
                mutation_gate.exit_wallet_mutation(permit)
            except BaseException:
                pass
    result["_catalyst_effect_attempted"] = submit_started
    return result


def build_cancel_offers_batch_unsigned(
    trade_ids: list,
    *,
    fee_mojos: int,
    source_coin_ids: list,
    fee_coin_id: str,
):
    """Build and exactly cost a Sage cancel cohort without signing it."""

    callback = getattr(_wallet_adapter, "build_cancel_offers_batch_unsigned", None)
    if WALLET_TYPE != "sage" or not callable(callback):
        return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
    try:
        binding, adapter = _expected_identity_authority()

        def identity_recheck(step: str) -> None:
            with _wallet_identity_observation_lock:
                _revalidate_adapter_authority(
                    adapter, f"wallet:unsigned_cancel_build:{step}"
                )
                mutation_gate.require_fresh_wallet_identity(
                    binding,
                    _identity_from_adapter(adapter),
                    f"wallet:unsigned_cancel_build:{step}",
                )

        identity_recheck("identity")
        result = callback(
            trade_ids,
            fee_mojos=fee_mojos,
            source_coin_ids=source_coin_ids,
            fee_coin_id=fee_coin_id,
            _identity_recheck=identity_recheck,
        )
        return (
            result
            if type(result) is dict
            else _blocked_mutation("WALLET_MUTATION_FAILED")
        )
    except mutation_gate.MutationBlocked as exc:
        return _blocked_mutation(exc.reason_code)
    except Exception:
        return _blocked_mutation("WALLET_MUTATION_FAILED")


def validate_unsigned_transaction_effect(result: dict, contract: dict):
    callback = getattr(_wallet_adapter, "validate_unsigned_transaction_effect", None)
    if WALLET_TYPE != "sage" or not callable(callback):
        return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
    return callback(result, contract)


def estimate_unsigned_transaction_cost(result: dict):
    callback = getattr(_wallet_adapter, "estimate_unsigned_transaction_cost", None)
    if WALLET_TYPE != "sage" or not callable(callback):
        return None
    return callback(result)


def inspect_unsigned_transaction_effect(result: dict, contract: dict):
    callback = getattr(_wallet_adapter, "inspect_unsigned_transaction_effect", None)
    if WALLET_TYPE != "sage" or not callable(callback):
        return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
    return callback(result, contract)


def submit_built_transaction_rpc(validated_result: dict):
    return _run_sage_mutation("submit_built_transaction_rpc", validated_result)


def sage_topup_split(
    source_coin_id: str,
    num_coins: int,
    trading_size_mojos: int,
    own_address: str,
    fee_mojos: int = 0,
    is_cat: bool = False,
    fee_coin_id=None,
):
    return _run_sage_mutation(
        "sage_topup_split",
        source_coin_id,
        num_coins,
        trading_size_mojos,
        own_address,
        fee_mojos,
        is_cat,
        fee_coin_id,
    )


def combine_coins(coin_ids: list, fee_mojos: int = 0):
    return _run_sage_mutation("combine_coins", coin_ids, fee_mojos)


def send_cat_multi(payments: list, fee_mojos: int = 0):
    return _run_sage_mutation("send_cat_multi", payments, fee_mojos)


def sign_message_by_address(address: str, message: str):
    return _run_sage_mutation("sign_message_by_address", address, message)


def auto_combine_xch(fee_mojos: int = 0, max_coins: int = 500):
    return _run_sage_mutation("auto_combine_xch", fee_mojos, max_coins)


def auto_combine_cat(asset_id: str = None, fee_mojos: int = 0, max_coins: int = 500):
    return _run_sage_mutation("auto_combine_cat", asset_id, fee_mojos, max_coins)


def sage_initialize():
    return _run_sage_mutation("sage_initialize")


def sage_login(fingerprint: int, force_resync: bool = False):
    return _run_sage_mutation("sage_login", fingerprint, force_resync)


def set_change_address(change_address: str, fingerprint: int = None):
    return _run_sage_mutation("set_change_address", change_address, fingerprint)


def sage_delete_offer(offer_id: str):
    return _run_sage_mutation("delete_offer", offer_id)


def sage_delete_offers_batch(offer_ids: list):
    return _run_sage_mutation("delete_offers_batch", offer_ids)
