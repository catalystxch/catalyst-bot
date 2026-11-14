"""Necessary arithmetic and denomination fit for a reviewed initial Follow book."""

from decimal import Decimal
from types import SimpleNamespace

import pytest


def _terms():
    return {
        "buy_limit": 2,
        "sell_limit": 2,
        "mid_price": Decimal("1"),
        "half_spread": Decimal("0.1"),
        "min_edge_bps": Decimal("0"),
        "buy_tier_counts": {"inner": 1, "extreme": 1},
        "sell_tier_counts": {"inner": 1, "extreme": 1},
        "buy_tier_sizes_xch": {"inner": Decimal("1"), "extreme": Decimal("2")},
        "sell_tier_sizes_xch": {"inner": Decimal("1"), "extreme": Decimal("2")},
        "buy_reversed": False,
        "cat_decimals": 3,
        "max_coin_size_ratio": Decimal("1.5"),
        "maximum_trade_xch_mojos": 3_000_000_000_000,
        "maximum_trade_cat_atoms": 2_818,
        "outputs": [
            {
                "asset": "xch",
                "purpose": "replacement",
                "tier_rank": 0,
                "amount_mojos": 1_000_000_000_000,
                "ordinal": 0,
            },
            {
                "asset": "xch",
                "purpose": "replacement",
                "tier_rank": 3,
                "amount_mojos": 2_000_000_000_000,
                "ordinal": 1,
            },
            {
                "asset": "cat",
                "purpose": "replacement",
                "tier_rank": 0,
                "amount_mojos": 1_000,
                "ordinal": 0,
            },
            {
                "asset": "cat",
                "purpose": "replacement",
                "tier_rank": 3,
                "amount_mojos": 1_818,
                "ordinal": 1,
            },
        ],
    }


def test_initial_follow_slot_fit_requires_each_tier_coin_and_trade_principal():
    from follow_slot_fit import prove_initial_follow_slot_fit

    terms = _terms()
    result = prove_initial_follow_slot_fit(**terms)
    assert result["buy_slots_arithmetic_fit"] == 2
    assert result["sell_slots_arithmetic_fit"] == 2
    assert result["required_xch_mojos"] == 3_000_000_000_000
    assert result["required_cat_atoms"] == 2_818
    assert result["dispatch_authorized"] is False

    terms["outputs"][-1]["amount_mojos"] = 1_817
    with pytest.raises(ValueError, match="FOLLOW_SLOT_DENOMINATION_SHORT"):
        prove_initial_follow_slot_fit(**terms)
    terms["outputs"][-1]["amount_mojos"] = 1_818
    terms["maximum_trade_cat_atoms"] = 2_817
    with pytest.raises(ValueError, match="FOLLOW_SLOT_PRINCIPAL_SHORT"):
        prove_initial_follow_slot_fit(**terms)


def test_legacy_full_fit_still_rejects_zero_slots():
    from follow_slot_fit import prove_initial_follow_slot_fit

    terms = _terms()
    terms["buy_limit"] = 0
    with pytest.raises(ValueError, match="FOLLOW_SLOT_INPUT_INVALID"):
        prove_initial_follow_slot_fit(**terms)


def test_full_assigned_coin_principal_must_fit_after_protected_reserves():
    from follow_slot_fit import prove_initial_follow_slot_fit

    terms = _terms()
    terms["outputs"][0]["amount_mojos"] = 1_100_000_000_000
    terms["outputs"][1]["amount_mojos"] = 2_200_000_000_000
    with pytest.raises(ValueError, match="FOLLOW_SLOT_SOURCE_PRINCIPAL_SHORT"):
        prove_initial_follow_slot_fit(**terms)

    terms = _terms()
    terms["outputs"][2]["amount_mojos"] = 1_100
    terms["outputs"][3]["amount_mojos"] = 2_000
    with pytest.raises(ValueError, match="FOLLOW_SLOT_SOURCE_PRINCIPAL_SHORT"):
        prove_initial_follow_slot_fit(**terms)


def test_reversed_buy_slots_use_reversed_prepared_size_tiers():
    from follow_slot_fit import prove_initial_follow_slot_fit

    terms = _terms()
    terms["buy_reversed"] = True
    terms["outputs"][0]["tier_rank"] = 3
    terms["outputs"][1]["tier_rank"] = 0
    result = prove_initial_follow_slot_fit(**terms)
    assert result["buy_slots_arithmetic_fit"] == 2
    terms["outputs"][0]["tier_rank"] = 0
    with pytest.raises(ValueError, match="FOLLOW_SLOT_DENOMINATION_SHORT"):
        prove_initial_follow_slot_fit(**terms)


def test_slot_fit_can_prove_exact_vacant_slots_for_top_up(monkeypatch):
    import api_server  # Load wallet/config modules before swapping the cfg fixture.
    import config
    from follow_slot_fit import preview_current_follow_slot_fit

    terms = _terms()
    cfg = SimpleNamespace(
        ENABLE_BUY=True,
        ENABLE_SELL=True,
        DRY_RUN=False,
        COIN_IDS_ENABLED=True,
        COIN_MAX_SIZE_RATIO=1.5,
        BUY_LADDER_REVERSED=False,
        TIER_ENABLED=True,
        **{
            f"{side}_{tier.upper()}_SIZE_XCH": size
            for side, sizes in (
                ("BUY", terms["buy_tier_sizes_xch"]),
                ("SELL", terms["sell_tier_sizes_xch"]),
            )
            for tier, size in sizes.items()
        },
    )
    monkeypatch.setattr(config, "cfg", cfg)
    configuration = {
        "LIQUIDITY_MODE": "two_sided",
        "TIER_ENABLED": True,
        "MAX_ACTIVE_BUY_OFFERS": 2,
        "MAX_ACTIVE_SELL_OFFERS": 2,
        "SPREAD_BPS": Decimal("2000"),
        "MIN_EDGE_BPS": Decimal("0"),
        "CAT_DECIMALS": 3,
        "BUY_LADDER_REVERSED": False,
        **{
            f"{side}_{tier.upper()}_TIER_COUNT": count
            for side, counts in (
                ("BUY", terms["buy_tier_counts"]),
                ("SELL", terms["sell_tier_counts"]),
            )
            for tier, count in counts.items()
        },
    }

    result = preview_current_follow_slot_fit(
        configuration=configuration,
        outputs=terms["outputs"],
        buy_limit=2,
        sell_limit=2,
        maximum_trade_xch_mojos=terms["maximum_trade_xch_mojos"],
        maximum_trade_cat_atoms=terms["maximum_trade_cat_atoms"],
        allow_partial=True,
        mid_price_override=Decimal("1"),
        buy_slot_candidates=[1],
        sell_slot_candidates=[0],
    )

    assert result["funded_buy_limit"] == 1
    assert result["funded_sell_limit"] == 1
    assert result["funded_output_assignments"] == [
        {
            "side": "buy",
            "slot": 1,
            "tier": "extreme",
            "price_xch": "0.9",
            "output_ordinal": 1,
        },
        {
            "side": "sell",
            "slot": 0,
            "tier": "inner",
            "price_xch": "1.0",
            "output_ordinal": 0,
        },
    ]


def test_slot_assignment_digest_binds_price_and_coin_size_policy():
    from follow_slot_fit import prove_initial_follow_slot_fit

    terms = _terms()
    baseline = prove_initial_follow_slot_fit(**terms)["slot_assignment_sha256"]
    terms["max_coin_size_ratio"] = Decimal("2")
    assert prove_initial_follow_slot_fit(**terms)["slot_assignment_sha256"] != baseline
    terms["max_coin_size_ratio"] = Decimal("1.5")
    terms["mid_price"] = Decimal("1.001")
    assert prove_initial_follow_slot_fit(**terms)["slot_assignment_sha256"] != baseline


def test_slot_fit_rejects_noncanonical_or_reused_outputs():
    from follow_slot_fit import prove_initial_follow_slot_fit

    terms = _terms()
    terms["outputs"][1]["ordinal"] = 0
    with pytest.raises(ValueError, match="FOLLOW_SLOT_PLAN_INVALID"):
        prove_initial_follow_slot_fit(**terms)


def test_exact_24_by_24_requires_one_fitting_coin_per_slot():
    from follow_slot_fit import prove_initial_follow_slot_fit

    tiers = ("inner", "mid", "outer", "extreme")
    terms = _terms()
    terms.update(
        buy_limit=24,
        sell_limit=24,
        buy_tier_counts={tier: 6 for tier in tiers},
        sell_tier_counts={tier: 6 for tier in tiers},
        buy_tier_sizes_xch={tier: Decimal("1") for tier in tiers},
        sell_tier_sizes_xch={tier: Decimal("1") for tier in tiers},
        maximum_trade_xch_mojos=24_000_000_000_000,
        maximum_trade_cat_atoms=26_400,
        outputs=[
            {
                "asset": asset,
                "purpose": "replacement",
                "tier_rank": ordinal // 6,
                "amount_mojos": amount,
                "ordinal": ordinal,
            }
            for asset, amount in (("xch", 1_000_000_000_000), ("cat", 1_100))
            for ordinal in range(24)
        ],
    )
    result = prove_initial_follow_slot_fit(**terms)
    assert result["buy_slots_arithmetic_fit"] == 24
    assert result["sell_slots_arithmetic_fit"] == 24
    assert result["dispatch_authorized"] is False
    terms["outputs"].pop()
    with pytest.raises(ValueError, match="FOLLOW_SLOT_DENOMINATION_SHORT"):
        prove_initial_follow_slot_fit(**terms)


def test_exact_100_by_100_requires_one_fitting_coin_per_slot():
    from follow_slot_fit import prove_initial_follow_slot_fit

    tiers = ("inner", "mid", "outer", "extreme")
    terms = _terms()
    terms.update(
        buy_limit=100,
        sell_limit=100,
        buy_tier_counts={tier: 25 for tier in tiers},
        sell_tier_counts={tier: 25 for tier in tiers},
        buy_tier_sizes_xch={tier: Decimal("1") for tier in tiers},
        sell_tier_sizes_xch={tier: Decimal("1") for tier in tiers},
        maximum_trade_xch_mojos=100_000_000_000_000,
        maximum_trade_cat_atoms=110_000,
        outputs=[
            {
                "asset": asset,
                "purpose": "replacement",
                "tier_rank": ordinal // 25,
                "amount_mojos": amount,
                "ordinal": ordinal,
            }
            for asset, amount in (("xch", 1_000_000_000_000), ("cat", 1_100))
            for ordinal in range(100)
        ],
    )
    result = prove_initial_follow_slot_fit(**terms)
    assert result["buy_slots_arithmetic_fit"] == 100
    assert result["sell_slots_arithmetic_fit"] == 100
    assert result["dispatch_authorized"] is False
    terms = _terms()
    terms["outputs"][0]["asset"] = []
    with pytest.raises(ValueError, match="FOLLOW_SLOT_PLAN_INVALID"):
        prove_initial_follow_slot_fit(**terms)


def test_partial_initial_fit_keeps_signed_target_and_uses_target_prefix():
    from follow_slot_fit import find_fundable_follow_slot_limits

    terms = _terms()
    terms["outputs"][2]["amount_mojos"] = 1_200
    terms["outputs"][3]["amount_mojos"] = 1_818
    result = find_fundable_follow_slot_limits(
        buy_target=2,
        sell_target=2,
        mid_price=Decimal("1"),
        half_spread=Decimal("0.1"),
        min_edge_bps=Decimal("0"),
        buy_tier_counts=terms["buy_tier_counts"],
        sell_tier_counts=terms["sell_tier_counts"],
        buy_tier_sizes_xch=terms["buy_tier_sizes_xch"],
        sell_tier_sizes_xch=terms["sell_tier_sizes_xch"],
        buy_reversed=False,
        cat_decimals=3,
        max_coin_size_ratio=Decimal("1.5"),
        maximum_trade_xch_mojos=1_000_000_000_000,
        maximum_trade_cat_atoms=1_200,
        outputs=terms["outputs"],
    )
    assert result["buy_target"] == 2
    assert result["sell_target"] == 2
    assert result["funded_buy_limit"] == 1
    assert result["funded_sell_limit"] == 1
    assert result["buy_slots_arithmetic_fit"] == 1
    assert result["sell_slots_arithmetic_fit"] == 1
    assert result["funded_output_assignments"] == [
        {
            "side": "buy",
            "slot": 0,
            "tier": "inner",
            "price_xch": "1.0",
            "output_ordinal": 0,
        },
        {
            "side": "sell",
            "slot": 0,
            "tier": "inner",
            "price_xch": "1.0",
            "output_ordinal": 0,
        },
    ]
    assert result["partial_target"] is True
    assert result["dispatch_authorized"] is False


def test_current_slot_preview_uses_server_configuration_and_readonly_price(monkeypatch):
    import api_server
    import config
    from follow_slot_fit import preview_current_follow_slot_fit

    terms = _terms()
    cfg = SimpleNamespace(
        ENABLE_BUY=True,
        ENABLE_SELL=True,
        DRY_RUN=False,
        COIN_IDS_ENABLED=True,
        COIN_MAX_SIZE_RATIO=1.5,
        BUY_LADDER_REVERSED=False,
        TIER_ENABLED=True,
        **{
            f"{side}_{tier.upper()}_SIZE_XCH": size
            for side, sizes in (
                ("BUY", terms["buy_tier_sizes_xch"]),
                ("SELL", terms["sell_tier_sizes_xch"]),
            )
            for tier, size in sizes.items()
        },
    )
    monkeypatch.setattr(config, "cfg", cfg)
    monkeypatch.setattr(api_server, "_get_readonly_mid_price_str", lambda: "1")
    configuration = {
        "LIQUIDITY_MODE": "two_sided",
        "TIER_ENABLED": True,
        "MAX_ACTIVE_BUY_OFFERS": 2,
        "MAX_ACTIVE_SELL_OFFERS": 2,
        "SPREAD_BPS": Decimal("2000"),
        "MIN_EDGE_BPS": Decimal("0"),
        "CAT_DECIMALS": 3,
        "BUY_LADDER_REVERSED": False,
        **{
            f"{side}_{tier.upper()}_TIER_COUNT": count
            for side, counts in (
                ("BUY", terms["buy_tier_counts"]),
                ("SELL", terms["sell_tier_counts"]),
            )
            for tier, count in counts.items()
        },
    }
    result = preview_current_follow_slot_fit(
        configuration=configuration,
        outputs=terms["outputs"],
        buy_limit=2,
        sell_limit=2,
        maximum_trade_xch_mojos=terms["maximum_trade_xch_mojos"],
        maximum_trade_cat_atoms=terms["maximum_trade_cat_atoms"],
    )
    assert result["sell_slots_arithmetic_fit"] == 2
    assert result["readonly_mid_price_xch"] == "1"


def test_current_slot_preview_can_bind_to_approved_policy_anchor(monkeypatch):
    import api_server
    import config
    from follow_slot_fit import preview_current_follow_slot_fit

    terms = _terms()
    cfg = SimpleNamespace(
        ENABLE_BUY=True,
        ENABLE_SELL=True,
        DRY_RUN=False,
        COIN_IDS_ENABLED=True,
        COIN_MAX_SIZE_RATIO=1.5,
        BUY_LADDER_REVERSED=False,
        TIER_ENABLED=True,
        **{
            f"{side}_{tier.upper()}_SIZE_XCH": size
            for side, sizes in (
                ("BUY", terms["buy_tier_sizes_xch"]),
                ("SELL", terms["sell_tier_sizes_xch"]),
            )
            for tier, size in sizes.items()
        },
    )
    monkeypatch.setattr(config, "cfg", cfg)
    monkeypatch.setattr(
        api_server,
        "_get_readonly_mid_price_str",
        lambda: pytest.fail("the approved anchor should be used directly"),
    )
    configuration = {
        "LIQUIDITY_MODE": "two_sided",
        "TIER_ENABLED": True,
        "MAX_ACTIVE_BUY_OFFERS": 2,
        "MAX_ACTIVE_SELL_OFFERS": 2,
        "SPREAD_BPS": Decimal("2000"),
        "MIN_EDGE_BPS": Decimal("0"),
        "BUY_LADDER_REVERSED": False,
        "CAT_DECIMALS": 3,
        **{
            f"{side}_{tier.upper()}_TIER_COUNT": count
            for side, counts in (
                ("BUY", terms["buy_tier_counts"]),
                ("SELL", terms["sell_tier_counts"]),
            )
            for tier, count in counts.items()
        },
    }

    result = preview_current_follow_slot_fit(
        configuration=configuration,
        outputs=terms["outputs"],
        buy_limit=2,
        sell_limit=2,
        maximum_trade_xch_mojos=terms["maximum_trade_xch_mojos"],
        maximum_trade_cat_atoms=terms["maximum_trade_cat_atoms"],
        mid_price_override=Decimal("1.01"),
    )

    assert result["readonly_mid_price_xch"] == "1.01"
    configuration["MAX_ACTIVE_SELL_OFFERS"] = 3
    with pytest.raises(ValueError, match="FOLLOW_SLOT_CONFIGURATION_MISMATCH"):
        preview_current_follow_slot_fit(
            configuration=configuration,
            outputs=terms["outputs"],
            buy_limit=2,
            sell_limit=2,
            maximum_trade_xch_mojos=terms["maximum_trade_xch_mojos"],
            maximum_trade_cat_atoms=terms["maximum_trade_cat_atoms"],
        )
    configuration["MAX_ACTIVE_SELL_OFFERS"] = 2
    quotes = iter(("1", "1.001"))
    monkeypatch.setattr(api_server, "_get_readonly_mid_price_str", lambda: next(quotes))
    with pytest.raises(ValueError, match="FOLLOW_SLOT_PRICE_CHANGED"):
        preview_current_follow_slot_fit(
            configuration=configuration,
            outputs=terms["outputs"],
            buy_limit=2,
            sell_limit=2,
            maximum_trade_xch_mojos=terms["maximum_trade_xch_mojos"],
            maximum_trade_cat_atoms=terms["maximum_trade_cat_atoms"],
        )
