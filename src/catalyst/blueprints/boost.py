"""Close the Gap / maker boost routes.

Three routes that control the sniper-style adaptive probe that tightens
spreads to improve Dexie ranking. Activation is async (background thread)
so the GUI doesn't block on wallet RPC.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

import api_server


bp = Blueprint("boost", __name__)


@bp.route("/api/boost/activate", methods=["POST"])
def api_boost_activate():
    """Reject the retired TibetSwap-dependent Close-the-Gap workflow."""
    return (
        jsonify(
            {
                "success": False,
                "status": "retired",
                "reason": "TIBETSWAP_SHUTDOWN",
                "replacement": "book_opportunity",
            }
        ),
        410,
    )


@bp.route("/api/boost/deactivate", methods=["POST"])
def api_boost_deactivate():
    """Deactivate Close the Gap — cancel all gap-closer offers."""
    bot = api_server.bot
    if not bot:
        return jsonify({"error": "Bot not initialised"}), 500

    result = bot.boost_manager.deactivate()
    api_server.events.emit("boost", bot.boost_manager.get_state())
    return jsonify(result)


@bp.route("/api/boost/state")
def api_boost_state():
    """Get current boost state."""
    bot = api_server.bot
    if not bot:
        return jsonify({"error": "Bot not initialised"}), 500

    return jsonify(bot.boost_manager.get_state())
