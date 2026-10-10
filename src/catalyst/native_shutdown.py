"""Fail-closed native-window shutdown admission."""

from __future__ import annotations

from typing import Any


def native_close_readiness() -> dict[str, Any]:
    """Prove that closing the native window cannot cut off a wallet mutation."""

    import api_server

    try:
        # Cancel All reserves its worker under this same lock. Quiescing the
        # mutation gate before releasing it prevents a later request from
        # starting a new wallet mutation while shutdown drains producers.
        with api_server._bot_cancel_lifecycle_lock:
            with api_server._cancel_all_state_lock:
                cancel_active = api_server._cancel_all_state.get("running") is not False
            cancel_thread = api_server._cancel_all_thread
            cancel_active = cancel_active or (
                cancel_thread is not None and cancel_thread.is_alive()
            )
            if cancel_active:
                return {"released": False, "reason": "cancel_all_in_progress"}

            runtime = api_server.mutation_gate.current_runtime()
            if runtime is None:
                active_bot = api_server.bot
                if active_bot is not None and active_bot.is_running():
                    return {"released": False, "reason": "runtime_unavailable"}
                return {"released": True, "reason": "no_mutation_runtime"}
            runtime.begin_quiesce()
    except Exception:
        return {"released": False, "reason": "native_close_preflight_unavailable"}

    try:
        result = api_server.quiesce_and_release_mutation_runtime()
    except Exception:
        return {"released": False, "reason": "native_close_quiesce_failed"}
    if type(result) is not dict or result.get("released") is not True:
        return (
            result
            if type(result) is dict
            else {
                "released": False,
                "reason": "native_close_proof_invalid",
            }
        )
    return result
