"""Tier-size drift checks should match live offer coin-fit bounds."""

import coin_manager
import database
from config import cfg


def _coin(amount_mojos, status="free"):
    return {"amount_mojos": int(amount_mojos), "status": status}


def _patch_drift_inputs(monkeypatch, amounts_by_key):
    monkeypatch.setattr(cfg, "TIER_ENABLED", True, raising=False)
    monkeypatch.setattr(cfg, "COIN_MAX_SIZE_RATIO", 1.5, raising=False)
    monkeypatch.setattr(cfg, "COIN_PREP_HEADROOM_PCT", 0, raising=False)

    def fake_tier_sizes(is_cat=False):
        return {"inner": 1000, "mid": 500, "outer": 250, "extreme": 125}

    def fake_coins(wallet_type, designation, tier):
        assert designation == "tier_spare"
        return [_coin(v) for v in amounts_by_key.get((wallet_type, tier), [])]

    monkeypatch.setattr(coin_manager, "get_tier_sizes_mojos_from_cfg", fake_tier_sizes)
    monkeypatch.setattr(database, "get_coins_by_designation", fake_coins)


def test_standalone_drift_accepts_usable_oversize_coins(monkeypatch):
    _patch_drift_inputs(monkeypatch, {("cat", "outer"): [305, 305]})

    findings = coin_manager.check_tier_size_drift_standalone()

    assert findings == []


def test_standalone_drift_flags_under_floor_coins(monkeypatch):
    _patch_drift_inputs(monkeypatch, {("xch", "inner"): [970, 970]})

    findings = coin_manager.check_tier_size_drift_standalone()

    assert len(findings) == 1
    assert findings[0]["side"] == "xch"
    assert findings[0]["tier"] == "inner"
    assert findings[0]["ratio"] == 0.97


def test_standalone_drift_keeps_prepared_coins_within_headroom(monkeypatch):
    _patch_drift_inputs(monkeypatch, {("cat", "inner"): [900, 900]})
    monkeypatch.setattr(cfg, "COIN_PREP_HEADROOM_PCT", 15, raising=False)

    findings = coin_manager.check_tier_size_drift_standalone()

    assert findings == []


def test_standalone_drift_ignores_locked_offer_coins(monkeypatch):
    monkeypatch.setattr(cfg, "TIER_ENABLED", True, raising=False)
    monkeypatch.setattr(cfg, "COIN_MAX_SIZE_RATIO", 1.5, raising=False)

    def fake_tier_sizes(is_cat=False):
        return {"inner": 1000, "mid": 500, "outer": 250, "extreme": 125}

    def fake_coins(wallet_type, designation, tier):
        assert designation == "tier_spare"
        if (wallet_type, tier) == ("cat", "outer"):
            return [
                _coin(250, status="free"),
                _coin(250, status="free"),
                _coin(220, status="locked"),
                _coin(220, status="locked"),
            ]
        return []

    monkeypatch.setattr(coin_manager, "get_tier_sizes_mojos_from_cfg", fake_tier_sizes)
    monkeypatch.setattr(database, "get_coins_by_designation", fake_coins)

    findings = coin_manager.check_tier_size_drift_standalone()

    assert findings == []


def test_standalone_drift_flags_above_configured_max_ratio(monkeypatch):
    _patch_drift_inputs(monkeypatch, {("cat", "mid"): [755, 755]})

    findings = coin_manager.check_tier_size_drift_standalone()

    assert len(findings) == 1
    assert findings[0]["side"] == "cat"
    assert findings[0]["tier"] == "mid"
    assert findings[0]["ratio"] == 1.51


def test_instance_drift_uses_same_bounds(monkeypatch):
    _patch_drift_inputs(monkeypatch, {("cat", "outer"): [305, 305]})
    manager = coin_manager.CoinManager.__new__(coin_manager.CoinManager)

    findings = manager.check_tier_size_drift()

    assert findings == []


def test_reclassify_moves_reserve_sized_tier_spares_to_reserve(monkeypatch):
    monkeypatch.setattr(cfg, "TIER_ENABLED", True, raising=False)
    monkeypatch.setattr(
        coin_manager,
        "get_tier_sizes_mojos_from_cfg",
        lambda is_cat=False: {"inner": 1000, "mid": 500, "outer": 250},
    )

    def fake_coins(wallet_type, designation, tier=None):
        assert designation == "tier_spare"
        if wallet_type == "cat":
            return [
                {
                    "coin_id": "0xreservefuel",
                    "amount_mojos": 2000,
                    "assigned_tier": "inner",
                }
            ]
        return []

    designations = []

    def fake_set_coin_designation(coin_id, designation, assigned_tier=None):
        designations.append((coin_id, designation, assigned_tier))

    monkeypatch.setattr(database, "get_coins_by_designation", fake_coins)
    monkeypatch.setattr(database, "set_coin_designation", fake_set_coin_designation)

    moved = coin_manager.reclassify_tier_spare_coins()

    assert designations == [("0xreservefuel", "reserve", "none")]
    assert moved["reclassified"] == 1


def test_reclassify_keeps_prepared_tier_assignment_within_headroom(monkeypatch):
    monkeypatch.setattr(cfg, "TIER_ENABLED", True, raising=False)
    monkeypatch.setattr(cfg, "COIN_PREP_HEADROOM_PCT", 15, raising=False)
    monkeypatch.setattr(cfg, "COIN_MAX_SIZE_RATIO", 1.5, raising=False)
    monkeypatch.setattr(
        coin_manager,
        "get_tier_sizes_mojos_from_cfg",
        lambda is_cat=False: {
            "inner": 1000,
            "mid": 780,
            "outer": 400,
            "extreme": 200,
        },
    )

    def fake_coins(wallet_type, designation, tier=None):
        assert designation == "tier_spare"
        if wallet_type == "cat":
            return [
                {
                    "coin_id": "0xpreparedinner",
                    "amount_mojos": 900,
                    "assigned_tier": "inner",
                }
            ]
        return []

    designations = []
    monkeypatch.setattr(database, "get_coins_by_designation", fake_coins)
    monkeypatch.setattr(
        database,
        "set_coin_designation",
        lambda coin_id, designation, assigned_tier=None: designations.append(
            (coin_id, designation, assigned_tier)
        ),
    )

    moved = coin_manager.reclassify_tier_spare_coins()

    assert designations == []
    assert moved["unchanged"] == 1
