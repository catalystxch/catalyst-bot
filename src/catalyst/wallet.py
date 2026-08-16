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
import threading
import time
from dotenv import load_dotenv
from config import cfg
import mutation_gate

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
    ):
        self.adapter = adapter
        self.binding = binding
        self.creator_thread_id = creator_thread_id
        self.deadline = deadline
        self.intent_id = intent_id
        self.journal = journal
        self.operation_id = operation_id
        self.permit = permit


_offer_creation_continuation_lock = threading.RLock()
_offer_creation_continuations: dict[
    _OfferCreationContinuation, _OfferCreationContinuationState
] = {}


def _exact_continuation_text(value, name: str) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise ValueError(f"{name} must be non-empty canonical text")
    if value != value.strip() or any(ord(character) < 0x20 for character in value):
        raise ValueError(f"{name} must be non-empty canonical text")
    return value


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


def begin_offer_creation_continuation(
    *,
    operation_id: str,
    intent_id: str,
    ttl_seconds: int = 30,
):
    """Enter offer authority before PREPARED and return an opaque one-shot handle."""

    operation = _exact_continuation_text(operation_id, "operation_id")
    intent = _exact_continuation_text(intent_id, "intent_id")
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 60:
        raise ValueError("ttl_seconds must be an exact integer from 1 to 60")
    wallet_operation = "wallet:create_offer"
    permit = None
    try:
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
        snapshot = _identity_from_adapter(adapter)
        mutation_gate.require_wallet_mutation_permit_authority(
            permit,
            f"{wallet_operation}:continuation:identity",
        )
        decision = mutation_gate.require_fresh_wallet_identity(
            binding,
            snapshot,
            f"{wallet_operation}:continuation",
        )
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


def offer_creation_continuation_journal(continuation) -> dict:
    """Return a detached canonical snapshot; never expose the held permit."""

    with _offer_creation_continuation_lock:
        state = _offer_creation_continuations.get(continuation)
        if state is None or threading.get_ident() != state.creator_thread_id:
            raise ValueError("offer creation continuation is invalid")
        return json.loads(_canonical_json(state.journal))


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


def _run_offer_creation_continuation(
    continuation,
    operation_id,
    intent_id,
    *args,
    **kwargs,
):
    wallet_operation = "wallet:create_offer"
    with _offer_creation_continuation_lock:
        state = _offer_creation_continuations.pop(continuation, None)
    if state is None:
        return _blocked_offer_creation_continuation()
    effect_attempted = False
    try:
        try:
            operation = _exact_continuation_text(operation_id, "operation_id")
            intent = _exact_continuation_text(intent_id, "intent_id")
        except (TypeError, ValueError):
            return _blocked_offer_creation_continuation()
        if (
            threading.get_ident() != state.creator_thread_id
            or time.monotonic() > state.deadline
            or operation != state.operation_id
            or intent != state.intent_id
        ):
            return _blocked_offer_creation_continuation()
        snapshot = _identity_from_adapter(state.adapter)
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
            fresh_snapshot = _identity_from_adapter(adapter)
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
            effect_attempted = True

        kwargs["_identity_recheck"] = identity_recheck
        callback = getattr(adapter, "create_offer")
        result = callback(*args, **kwargs)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            return _blocked_offer_creation_continuation(
                "WALLET_BACKEND_UNSUPPORTED",
                effect_attempted=effect_attempted,
            )
        if type(result) is not dict:
            return _blocked_offer_creation_continuation(
                "WALLET_MUTATION_FAILED",
                effect_attempted=effect_attempted,
            )
        result = dict(result)
        result["_catalyst_effect_attempted"] = effect_attempted
        return result
    except mutation_gate.MutationBlocked as exc:
        return _blocked_offer_creation_continuation(
            exc.reason_code,
            effect_attempted=effect_attempted,
        )
    except Exception:
        return _blocked_offer_creation_continuation(
            "WALLET_MUTATION_FAILED",
            effect_attempted=effect_attempted,
        )
    finally:
        try:
            mutation_gate.exit_wallet_mutation(state.permit)
        except BaseException:
            pass


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


def _run_wallet_mutation(export_name: str, *args, **kwargs):
    operation = f"wallet:{export_name}"
    permit = None
    try:
        permit = mutation_gate.enter_wallet_mutation(operation)
        binding, adapter = mutation_gate.require_wallet_mutation_permit_authority(
            permit, f"{operation}:acquire"
        )
        if binding.backend != WALLET_TYPE or adapter is not _wallet_adapter:
            raise mutation_gate.MutationBlocked(
                "WALLET_IDENTITY_BINDING_INVALID", operation
            )
        args = _bind_identity_selecting_arguments(export_name, args, binding, operation)
        snapshot = _identity_from_adapter(adapter)
        mutation_gate.require_wallet_mutation_permit_authority(
            permit, f"{operation}:identity"
        )
        mutation_gate.require_fresh_wallet_identity(binding, snapshot, operation)
        mutation_gate.require_wallet_mutation_permit_authority(
            permit, f"{operation}:dispatch"
        )
        if export_name in _COMPOUND_MUTATION_EXPORTS:

            def identity_recheck(step: str) -> None:
                safe_step = (
                    step if type(step) is str and step and len(step) <= 64 else "effect"
                )
                fresh_snapshot = _identity_from_adapter(adapter)
                mutation_gate.require_wallet_mutation_permit_authority(
                    permit, f"{operation}:{safe_step}:identity"
                )
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
        result = callback(*args, **kwargs)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            return _blocked_mutation("WALLET_BACKEND_UNSUPPORTED")
        return result
    except mutation_gate.MutationBlocked as exc:
        return _blocked_mutation(exc.reason_code)
    except Exception:
        return {
            "success": False,
            "error": "Wallet mutation failed after authorization",
            "reason": "WALLET_MUTATION_FAILED",
        }
    finally:
        if permit is not None:
            try:
                mutation_gate.exit_wallet_mutation(permit)
            except BaseException:
                pass


def get_wallet_balance(wallet_id: int):
    """Read-only balance calls remain available while mutation is blocked."""

    return _wallet_adapter.get_wallet_balance(wallet_id)


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
        return _run_offer_creation_continuation(
            _creation_continuation,
            _creation_operation_id,
            _creation_intent_id,
            offer_dict,
            **kwargs,
        )
    return _run_wallet_mutation("create_offer", offer_dict, **kwargs)


def cancel_offer(
    trade_id: str,
    secure: bool = True,
    timeout: int = 60,
    fee_mojos: int = None,
):
    return _run_wallet_mutation(
        "cancel_offer",
        trade_id,
        secure,
        timeout,
        fee_mojos,
    )


def cancel_offers_batch(
    trade_ids: list,
    secure: bool = True,
    max_workers: int = 3,
    fee_mojos: int = None,
    skip_confirmation: bool = False,
):
    return _run_wallet_mutation(
        "cancel_offers_batch",
        trade_ids,
        secure,
        max_workers,
        fee_mojos,
        skip_confirmation,
    )


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
