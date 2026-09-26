"""Fresh server-owned wallet reads must not use configured fallback inventory."""

from decimal import Decimal
from importlib import import_module

import pytest

import database
import wallet
import wallet_sage
import fee_approval_test_utils as fee_test_utils
from fee_approval_test_utils import _cat, _coin


ASSET = "36" * 32
ADDRESS = "xch1xgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgeryv3jxgequ6kqev"


def _service():
    try:
        return import_module("coin_prep_fee_runtime")
    except ModuleNotFoundError:
        pytest.fail("current authoritative fee wallet collector is missing")


@pytest.fixture
def live_reads(tmp_path, monkeypatch):
    yield from fee_test_utils.live_reads(tmp_path, monkeypatch)


def _collect(state):
    service = _service()
    state["monkeypatch"].setattr(service, "cfg", state["config"])
    return service.read_fee_wallet_snapshot()


def test_fresh_identity_asset_and_integer_selectable_inventory_without_effects(live_reads):
    result = _collect(live_reads)
    assert result["identity"]["wallet_fingerprint"] == 736588221
    assert result["identity"]["asset_id"] == ASSET
    assert result["identity"]["ticker"] == "MZ_XCH"
    assert result["receive_address"] == ADDRESS
    assert [(c.asset, c.amount_mojos) for c in result["snapshot"].coins] == [("xch", 2000), ("cat", 2000)]
    conn = database.get_connection()
    for table in ("coin_prep_operations", "wallet_effect_claims", "approved_fee_reservations"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("reserved,recon,purpose", [(True, False, "reserve"),
                                                  (False, True, "protected"), (True, True, "protected")])
def test_reconciliation_claim_is_not_misclassified_as_permanent_reserve(live_reads, reserved, recon, purpose):
    coin_id = live_reads["xch"][0]["coin_id"]
    patch = live_reads["monkeypatch"]
    patch.setattr(database, "get_reserve_coins", lambda asset: [{"coin_id": coin_id}]
                  if reserved and asset == "xch" else [])
    patch.setattr(database, "get_coin_reconciliation_protected_ids", lambda _ids: [coin_id] if recon else [])
    coin = next(c for c in _collect(live_reads)["snapshot"].coins if c.coin_id == coin_id)
    assert coin.purpose == purpose
    assert coin.protected is True


@pytest.mark.parametrize("cats", [None, {}, {"success": False, "cats": [{"asset_id": ASSET}]},
                                  {"cats": []}, {"cats": [{"asset_id": "37" * 32}]},
                                  {"cats": [{"asset_id": ASSET}, {"asset_id": ASSET}]}])
def test_configured_asset_is_not_evidence_of_actual_wallet_asset(live_reads, cats):
    live_reads["cats"] = cats
    with pytest.raises(ValueError, match="FEE_WALLET_ASSET_UNAVAILABLE"):
        _collect(live_reads)


@pytest.mark.parametrize("mutation", [
    {"fingerprint": True}, {"fingerprint": 12345}, {"network_id": "testnet11"},
    {"backend": "chia"}, {"has_secrets": False}, {"success": False},
])
def test_wrong_or_malformed_identity_cannot_supply_preview_inventory(live_reads, mutation):
    live_reads["identity"].update(mutation)
    with pytest.raises(ValueError, match="FEE_WALLET_IDENTITY_UNAVAILABLE"):
        _collect(live_reads)
    assert live_reads["reads"] == []


@pytest.mark.parametrize("flag", ["switch_on_coins", "change_config", "change_modern_size"])
def test_identity_and_configuration_switch_during_reads_is_rejected(live_reads, flag):
    live_reads[flag] = True
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        _collect(live_reads)


def test_inventory_paginates_instead_of_silently_truncating_500_coins(live_reads):
    live_reads["xch"] = [_coin(i + 1) for i in range(501)]
    result = _collect(live_reads)
    assert len([c for c in result["snapshot"].coins if c.asset == "xch"]) == 501
    assert ("get_coins", {"asset_id": None, "offset": 500, "limit": 500,
                          "sort_mode": "coin_id", "filter_mode": "selectable", "ascending": True}) in live_reads["reads"]


def test_repeated_page_is_not_a_complete_inventory(live_reads):
    live_reads["xch"] = [_coin(i + 1) for i in range(501)]
    live_reads["repeat_page"] = True
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


@pytest.mark.parametrize("amount", [True, 1.5, "2.5", "-1", "NaN"])
def test_malformed_atomic_inventory_amount_is_not_coerced(live_reads, amount):
    live_reads["xch"][0]["amount"] = amount
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


@pytest.mark.parametrize("coin_id", [None, "38", True, "g" * 64])
def test_inventory_coin_id_must_be_canonical(live_reads, coin_id):
    live_reads["xch"][0]["coin_id"] = coin_id
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


@pytest.mark.parametrize("total", [None, True, -1, "1", 1.5, 0, 2, 10001])
def test_incomplete_or_malformed_inventory_total_is_rejected(live_reads, total):
    live_reads["total_override"] = total
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


def test_missing_inventory_total_is_not_a_complete_snapshot(live_reads):
    live_reads["omit_total"] = True
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


def test_inventory_total_change_during_pagination_is_rejected(live_reads):
    live_reads["xch"] = [_coin(i + 1) for i in range(501)]
    live_reads["change_total"] = True
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


def test_empty_inventory_is_available_only_with_a_zero_total(live_reads):
    live_reads["xch"] = []
    live_reads["cat"] = []
    assert _collect(live_reads)["snapshot"].coins == ()


@pytest.mark.parametrize("precision", [None, True, "3", 4])
def test_wallet_asset_precision_must_match_economic_configuration(live_reads, precision):
    live_reads["cats"]["cats"][0]["precision"] = precision
    with pytest.raises(ValueError, match="FEE_WALLET_ASSET_UNAVAILABLE"):
        _collect(live_reads)


def test_optional_native_asset_metadata_does_not_hide_actual_cat(live_reads):
    native = {**_cat(), "asset_id": None, "name": "Chia", "ticker": "XCH", "precision": 12}
    live_reads["cats"]["cats"].insert(0, native)
    assert _collect(live_reads)["identity"]["asset_id"] == ASSET


@pytest.mark.parametrize("mutation", [{"offer_id": "38" * 32}, {"spent_height": 1},
                                      {"spent_timestamp": 100}, {"address": "xch1invalid"}])
def test_nonselectable_or_invalid_address_record_is_rejected(live_reads, mutation):
    live_reads["xch"][0].update(mutation)
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


def test_unstable_coin_order_cannot_supply_a_complete_inventory(live_reads):
    live_reads["xch"] = [_coin(1), _coin(2)]
    live_reads["reverse_page"] = True
    with pytest.raises(ValueError, match="FEE_WALLET_INVENTORY_UNAVAILABLE"):
        _collect(live_reads)


@pytest.fixture
def economic_reads(live_reads, monkeypatch):
    return fee_test_utils.economic_reads(live_reads, monkeypatch)


def _economic_collect(state, options=None):
    return fee_test_utils._economic_collect(state, options)


def test_runtime_economics_are_derived_from_current_wallet_settings_without_effects(economic_reads):
    result = _economic_collect(economic_reads)
    assert result["identity"]["wallet_fingerprint"] == 736588221
    assert result["recipe"]["economic_plan"]["target_seconds"] == 300
    assert [(o.asset, o.purpose, o.amount_mojos) for o in result["recipe"]["targets"]] == [
        ("xch", "replacement", 110_000_000_000), ("xch", "fee_reserve", 1_000_000_000),
        ("xch", "fee_reserve", 1_000_000_000), ("cat", "replacement", 11_000)]
    assert result["campaign"] is None
    assert result["dispatch_authorized"] is False
    for table in ("coin_prep_operations", "wallet_effect_claims", "approved_fee_reservations", "fee_approvals",
                  "coin_prep_fee_previews", "coin_prep_fee_consents"):
        assert database.get_connection().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_runtime_fee_snapshot_carries_enabled_sniper_pool_into_authoritative_plan(economic_reads):
    economic_reads["config"].SNIPER_ENABLED = True
    economic_reads["config"].SNIPER_PREP_COUNT = 20
    economic_reads["config"].SNIPER_SIZE_XCH = Decimal("0.33")

    result = _economic_collect(economic_reads)

    assert result["recipe"]["worker_args"]["xch_target"] == 23
    assert result["recipe"]["worker_args"]["cat_target"] == 21
    assert "sniper=0.363" in result["recipe"]["worker_args"]["buy_tier_sizes"]
    assert "sniper=36.3" in result["recipe"]["worker_args"]["cat_tier_sizes"]


@pytest.mark.parametrize("options", [{"scope_sha256": "38" * 32}, {"cost": 1}, {"outputs": []},
                                     {"coin_multiplier": True}, {"coin_multiplier": 1.5},
                                     {"target_seconds": True}, {"bootstrap_campaign_id": "38" * 32}])
def test_client_cannot_supply_economic_authority_or_malformed_choices(economic_reads, options):
    with pytest.raises(ValueError, match="FEE_PREP_OPTIONS_INVALID"):
        _economic_collect(economic_reads, options)
    assert economic_reads["reads"] == []


@pytest.mark.parametrize("flag", ["change_fee_configuration", "switch_on_price"])
def test_fee_configuration_or_identity_change_during_economic_collection_is_rejected(economic_reads, flag):
    economic_reads[flag] = True
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        _economic_collect(economic_reads)


def test_no_market_price_cannot_be_disguised_as_a_valid_runtime_plan(economic_reads):
    economic_reads["live_price"] = None
    with pytest.raises(ValueError, match="FEE_PREP_PRICE_UNAVAILABLE"):
        _economic_collect(economic_reads)


@pytest.mark.parametrize("key,value", [("FEE_PREP_COUNT", True), ("FEE_PREP_COUNT", 2.5),
                                      ("FEE_PREP_COUNT", -1), ("FEE_COIN_SIZE_XCH", "not-a-fee")])
def test_runtime_fee_pool_cannot_silently_coerce_invalid_settings(economic_reads, key, value):
    setattr(economic_reads["config"], key, value)
    with pytest.raises(ValueError, match="FEE_PREP_CONFIGURATION_INVALID"):
        _economic_collect(economic_reads)


def test_explicit_campaign_choices_without_a_current_campaign_cannot_fall_back_to_standard(economic_reads):
    with pytest.raises(ValueError, match="FEE_PREP_CAMPAIGN_UNAVAILABLE"):
        _economic_collect(economic_reads, {"bootstrap_campaign_id": "38" * 32,
                                           "bootstrap_campaign_revision": 0})


def _next_collect(state):
    service = _service()
    state["monkeypatch"].setattr(service, "cfg", state["config"])
    collector = getattr(service, "read_next_prep_fee_snapshot", None)
    assert callable(collector), "runtime funding and unsigned cost collection are missing"
    return collector({})


def _ready_inventory(state):
    state["xch"] = [_coin(1, "110000000000"), _coin(2, "1000000000"), _coin(3, "1000000000")]
    state["cat"] = [_coin(10001, "11000")]


def test_underfunded_runtime_plan_cannot_build_unsigned_or_guess_a_fee(economic_reads):
    result = _next_collect(economic_reads)
    assert result["available"] is False
    assert result["reason"] == "FEE_PREP_PRINCIPAL_UNFUNDED"
    assert result["funding"]["fee_funding_mojos"] == 0
    assert result["dispatch_authorized"] is False
    assert "inspection" not in result


def test_ready_runtime_inventory_has_no_fake_prep_transactions_or_fee_spend(economic_reads):
    _ready_inventory(economic_reads)
    result = _next_collect(economic_reads)
    assert result["available"] is True
    assert result["pricing"]["transaction_required"] is False
    assert result["funding"]["reused_target_count"] == 4
    assert result["funding"]["fee_funding_mojos"] == 0
    assert result["dispatch_authorized"] is False
    for table in ("coin_prep_operations", "wallet_effect_claims", "approved_fee_reservations", "fee_approvals"):
        assert database.get_connection().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_next_batch_fee_cannot_consume_principal_reserved_for_later_batches(economic_reads):
    import coin_prep_fee_pricing
    from coin_prep_batch_plan import BatchPlan, PlannedOutput
    _ready_inventory(economic_reads)
    economic_reads["xch"].append(_coin(4, "100"))
    plan = BatchPlan("cat", (economic_reads["cat"][0]["coin_id"],),
        economic_reads["xch"][0]["coin_id"], (PlannedOutput("cat", "replacement", 11000, 0),),
        (), (), 101)
    economic_reads["monkeypatch"].setattr(coin_prep_fee_pricing, "price_next_prep_batch", lambda **_kwargs: {
        "available": True, "reason": "cost_fee_consistent", "plan": plan,
        "transaction_required": True, "dispatch_authorized": False})
    result = _next_collect(economic_reads)
    assert result["available"] is False
    assert result["reason"] == "FEE_PREP_FUNDING_INSUFFICIENT"
    assert result["funding"]["fee_funding_mojos"] == 100
    assert "pricing" not in result


def test_quote_expiring_during_final_wallet_recheck_is_no_longer_usable(economic_reads):
    import coin_prep_fee_pricing
    from coin_prep_batch_plan import BatchPlan, PlannedOutput
    _ready_inventory(economic_reads)
    economic_reads["xch"].append(_coin(4, "100"))
    plan = BatchPlan("cat", (economic_reads["cat"][0]["coin_id"],), economic_reads["xch"][0]["coin_id"],
        (PlannedOutput("cat", "replacement", 11000, 0),), (), (), 1)
    quote = {"available": True, "source": "coinset", "cost": 42, "target_seconds": 300,
             "fee_mojos": 1, "observed_at": 1000, "expires_at": 1060}
    economic_reads["monkeypatch"].setattr(coin_prep_fee_pricing, "price_next_prep_batch", lambda **_kwargs: {
        "available": True, "reason": "cost_fee_consistent", "plan": plan, "quote": quote,
        "inspection": {"cost": 42}, "transaction_required": True, "dispatch_authorized": False})
    clock = {"now": 1000, "reads": 0}
    economic_reads["monkeypatch"].setattr(coin_prep_fee_pricing, "_now", lambda: clock["now"])
    service = _service()
    read_context = service.read_fee_economic_snapshot

    def slow_recheck(options):
        result = read_context(options)
        clock["reads"] += 1
        if clock["reads"] == 2:
            clock["now"] = 1060
        return result

    economic_reads["monkeypatch"].setattr(service, "read_fee_economic_snapshot", slow_recheck)
    result = _next_collect(economic_reads)
    assert result["available"] is False
    assert result["reason"] == "FEE_ESTIMATE_UNAVAILABLE"
    assert "pricing" not in result


@pytest.mark.parametrize("change", ["inventory", "configuration", "identity"])
def test_runtime_change_after_cost_collection_cannot_return_a_confirmable_context(economic_reads, change):
    import coin_prep_fee_pricing
    _ready_inventory(economic_reads)
    original = coin_prep_fee_pricing.price_next_prep_batch

    def changed(**kwargs):
        result = original(**kwargs)
        if change == "inventory":
            economic_reads["xch"] = [_coin(4, "112000000000")]
        elif change == "configuration":
            economic_reads["config"].COIN_PREP_HEADROOM_PCT = Decimal("20")
        else:
            economic_reads["identity"]["fingerprint"] = 12345
        return result

    economic_reads["monkeypatch"].setattr(coin_prep_fee_pricing, "price_next_prep_batch", changed)
    with pytest.raises(ValueError, match="FEE_WALLET_CONTEXT_CHANGED"):
        _next_collect(economic_reads)
