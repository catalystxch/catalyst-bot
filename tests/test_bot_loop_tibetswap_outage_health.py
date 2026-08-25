from bot_loop import BotLoop


def test_sse_market_health_names_confirmed_tibetswap_outage():
    """Cycle pushes must preserve the external TibetSwap outage context."""
    bot = object.__new__(BotLoop)
    bot._spacescan_context_getter = None
    bot._startup_self_test_results = {
        "tibet": {
            "name": "TibetSwap API",
            "ok": False,
            "status_code": 502,
            "error": "HTTP 502 (server error)",
            "critical": False,
        }
    }
    health = {
        "status": "green",
        "message": "Market healthy — bot operating normally",
        "conditions": [],
        "metrics": {"arb_gap_bps": "0", "pool_depth_ratio": "0"},
    }

    augmented = bot._augment_health_with_provider_context(health)
    augmented = bot._augment_health_with_provider_context(augmented)

    assert augmented["status"] == "amber"
    assert augmented["message"] == (
        "Market degraded — TibetSwap unavailable; Dexie-only pricing active "
        "without AMM drift protection"
    )
    assert augmented["metrics"]["tibetswap_available"] is False
    assert augmented["metrics"]["tibetswap_status_code"] == 502
    assert augmented["metrics"]["pricing_mode"] == "dexie_only"
    outage_conditions = [
        condition
        for condition in augmented["conditions"]
        if "TibetSwap API unavailable" in condition["text"]
    ]
    assert outage_conditions == [
        {
            "level": "amber",
            "text": (
                "TibetSwap API unavailable — Dexie-only pricing; "
                "AMM drift protection and reference price unavailable"
            ),
        }
    ]
