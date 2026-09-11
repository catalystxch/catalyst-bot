from bot_loop import BotLoop


def test_sse_market_health_treats_tibetswap_as_retired_compatibility_only():
    """A retired provider must not degrade otherwise healthy live market state."""
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

    assert augmented["status"] == "green"
    assert augmented["message"] == "Market healthy — bot operating normally"
    assert augmented["metrics"]["tibetswap_available"] is False
    assert augmented["metrics"]["tibetswap_retired"] is True
    assert augmented["metrics"]["tibetswap_reason"] == "TIBETSWAP_SHUTDOWN"
    assert augmented["metrics"]["pricing_mode"] == "offer_book_confidence"
    assert not any(
        "TibetSwap" in item.get("text", "") for item in augmented["conditions"]
    )
