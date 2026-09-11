from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from providers.coinset import CoinsetEvidenceProvider
from providers.dexie import DexieOrderbookProvider
from providers.models import Capability, ObservationQuality
from providers.sage import SageAuthorityProvider
from providers.spacescan import SpacescanEvidenceProvider
from providers.splash import SplashOfferProvider


ASSET_ID = "b8" * 32
COIN_ID = "ca" * 32
NOW = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)


def _payload(observation):
    return json.loads(observation.raw_evidence_json)


def test_dexie_normalizes_exact_book_and_deduplicates_offer_identity():
    provider = DexieOrderbookProvider(
        fetch_book=lambda _asset: {
            "bids": [
                {"price": "0.10", "amount_mojos": 2000, "offer_id": "bid-1"},
                {"price": "0.09", "amount_mojos": 1000, "offer_id": "bid-1"},
            ],
            "asks": [{"price": "0.12", "amount_mojos": 3000, "offer_id": "ask-1"}],
            "source_time": "2026-09-10T14:59:59Z",
        }
    )

    observation = provider.observe_order_book(ASSET_ID, now=NOW)

    assert observation.quality is ObservationQuality.VALID
    assert observation.capability is Capability.ORDER_BOOK
    assert _payload(observation)["bids"] == [
        {"amount_mojos": 2000, "offer_id": "bid-1", "price": "0.10"}
    ]
    assert observation.reason_codes == ("duplicate_offer_identity",)


def test_dexie_empty_book_is_degraded_not_zero_priced():
    provider = DexieOrderbookProvider(
        fetch_book=lambda _asset: {"bids": [], "asks": []}
    )

    observation = provider.observe_order_book(ASSET_ID, now=NOW)

    assert observation.quality is ObservationQuality.DEGRADED
    assert "empty_book" in observation.reason_codes
    assert "price" not in _payload(observation)


def test_dexie_preserves_a_real_sized_public_book_as_valid_evidence():
    provider = DexieOrderbookProvider(
        fetch_book=lambda _asset: {
            "bids": [
                {
                    "price": f"0.00002{index:02d}",
                    "amount_mojos": 1_000_000_000_000,
                    "offer_id": f"bid-{index}-" + "a" * 56,
                }
                for index in range(4, 0, -1)
            ],
            "asks": [
                {
                    "price": f"0.0001{index:04d}",
                    "amount_mojos": 1_000_000_000_000,
                    "offer_id": f"ask-{index}-" + "b" * 55,
                }
                for index in range(1, 33)
            ],
        }
    )

    observation = provider.observe_order_book(ASSET_ID, now=NOW)

    assert observation.quality is ObservationQuality.VALID
    assert len(_payload(observation)["bids"]) == 4
    assert len(_payload(observation)["asks"]) == 32


def test_dexie_rejects_float_price_and_redacts_failure_detail():
    provider = DexieOrderbookProvider(
        fetch_book=lambda _asset: {
            "bids": [{"price": 0.1, "amount_mojos": 1, "offer_id": "bid-1"}],
            "asks": [],
            "api_key": "must-not-leak",
        }
    )

    observation = provider.observe_order_book(ASSET_ID, now=NOW)

    assert observation.quality is ObservationQuality.INVALID
    assert observation.reason_codes == ("malformed_provider_response",)
    assert "must-not-leak" not in observation.raw_evidence_json


def test_dexie_timeout_is_bounded_provider_failure():
    def timeout(_asset):
        raise TimeoutError("GET https://dexie.invalid/?token=secret")

    observation = DexieOrderbookProvider(fetch_book=timeout).observe_order_book(
        ASSET_ID, now=NOW
    )

    assert observation.quality is ObservationQuality.INVALID
    assert observation.reason_codes == ("provider_timeout",)
    assert _payload(observation) == {"available": False, "error_type": "TimeoutError"}


def test_dexie_cached_book_keeps_source_age_instead_of_becoming_fresh_again():
    cached_at = NOW - timedelta(minutes=5)
    provider = DexieOrderbookProvider(
        fetch_book=lambda _asset: {
            "bids": [{"price": "0.10", "amount_mojos": 3_000, "offer_id": "bid"}],
            "asks": [{"price": "0.11", "amount_mojos": 3_000, "offer_id": "ask"}],
            "source_time": cached_at.isoformat().replace("+00:00", "Z"),
        }
    )

    observation = provider.observe_order_book(ASSET_ID, now=NOW)

    assert observation.source_time == cached_at
    assert observation.fresh_until == cached_at + timedelta(seconds=20)


def test_dexie_normalizes_latest_settled_trade_with_exact_price_and_time():
    provider = DexieOrderbookProvider(
        fetch_book=lambda _asset: {"bids": [], "asks": []},
        fetch_settled_trades=lambda _asset: [
            {
                "trade_id": "older-trade",
                "price": "0.00010",
                "base_volume": "1000",
                "target_volume": "0.1",
                "trade_timestamp": int(
                    (NOW - timedelta(seconds=30)).timestamp() * 1000
                ),
                "type": "buy",
            },
            {
                "trade_id": "latest-trade",
                "price": "0.00011",
                "base_volume": "2000",
                "target_volume": "0.22",
                "trade_timestamp": int((NOW - timedelta(seconds=5)).timestamp() * 1000),
                "type": "sell",
            },
        ],
    )

    observation = provider.observe_settled_trade(ASSET_ID, now=NOW)

    assert observation.capability is Capability.SETTLED_TRADES
    assert observation.quality is ObservationQuality.VALID
    assert observation.source_time == NOW - timedelta(seconds=5)
    assert observation.fresh_until == NOW + timedelta(seconds=55)
    assert observation.identity_keys == (ASSET_ID, "latest-trade")
    assert _payload(observation)["trade"] == {
        "base_volume": "2000",
        "price": "0.00011",
        "side": "sell",
        "target_volume": "0.22",
        "trade_id": "latest-trade",
    }


def test_dexie_rejects_inexact_settled_trade_price():
    provider = DexieOrderbookProvider(
        fetch_book=lambda _asset: {"bids": [], "asks": []},
        fetch_settled_trades=lambda _asset: [
            {
                "trade_id": "bad-trade",
                "price": 0.00011,
                "base_volume": "2000",
                "target_volume": "0.22",
                "trade_timestamp": int(NOW.timestamp() * 1000),
                "type": "sell",
            }
        ],
    )

    observation = provider.observe_settled_trade(ASSET_ID, now=NOW)

    assert observation.quality is ObservationQuality.INVALID
    assert observation.reason_codes == ("malformed_provider_response",)


def test_dexie_settled_trade_freshness_is_anchored_to_trade_time():
    trade_time = NOW - timedelta(minutes=5)
    provider = DexieOrderbookProvider(
        fetch_book=lambda _asset: {"bids": [], "asks": []},
        fetch_settled_trades=lambda _asset: [
            {
                "trade_id": "stale-trade",
                "price": "0.00011",
                "base_volume": "2000",
                "target_volume": "0.22",
                "trade_timestamp": int(trade_time.timestamp() * 1000),
                "type": "sell",
            }
        ],
    )

    observation = provider.observe_settled_trade(ASSET_ID, now=NOW)

    assert observation.quality is ObservationQuality.VALID
    assert observation.source_time == trade_time
    assert observation.fresh_until == trade_time + timedelta(seconds=60)
    assert observation.fresh_until < NOW


def test_splash_normalizes_peer_health_and_exact_offer_set():
    provider = SplashOfferProvider(
        fetch_offers=lambda _asset: [
            {
                "offer_id": "offer-2",
                "side": "sell",
                "price": "0.13",
                "amount_mojos": 3,
                "observed_at": "2026-09-10T14:59:58Z",
            },
            {
                "offer_id": "offer-1",
                "side": "buy",
                "price": "0.10",
                "amount_mojos": 2,
                "observed_at": "2026-09-10T14:59:59Z",
            },
        ],
        get_health=lambda: {"running": True, "peers": 4, "api_reachable": True},
    )

    offers = provider.observe_offers(ASSET_ID, now=NOW)
    health = provider.observe_peer_health(now=NOW)

    assert offers.quality is ObservationQuality.VALID
    assert offers.source_time == NOW - timedelta(seconds=2)
    assert offers.fresh_until == NOW + timedelta(seconds=18)
    assert [row["offer_id"] for row in _payload(offers)["offers"]] == [
        "offer-1",
        "offer-2",
    ]
    assert _payload(offers)["offers"][0]["observed_at"] == (
        "2026-09-10T14:59:59.000000Z"
    )
    assert health.quality is ObservationQuality.VALID
    assert _payload(health)["peers"] == 4


def test_splash_no_peers_is_degraded_and_not_fabricated_healthy():
    provider = SplashOfferProvider(
        fetch_offers=lambda _asset: [],
        get_health=lambda: {"running": True, "peers": 0, "api_reachable": True},
    )

    health = provider.observe_peer_health(now=NOW)

    assert health.quality is ObservationQuality.DEGRADED
    assert health.reason_codes == ("no_peers",)


def test_sage_identity_is_authoritative_and_mismatch_is_invalid():
    wallet = SimpleNamespace(
        get_wallet_identity=lambda: {
            "success": True,
            "fingerprint": 736588221,
            "network_id": "mainnet",
        }
    )
    provider = SageAuthorityProvider(wallet)

    valid = provider.observe_identity(
        expected_fingerprint=736588221, expected_network="mainnet", now=NOW
    )
    mismatch = provider.observe_identity(
        expected_fingerprint=123, expected_network="mainnet", now=NOW
    )

    assert valid.quality is ObservationQuality.VALID
    assert mismatch.quality is ObservationQuality.INVALID
    assert mismatch.reason_codes == ("wallet_identity_mismatch",)


def test_chain_adapters_preserve_exact_coin_and_height_evidence():
    parent = "11" * 32
    puzzle_hash = "22" * 32
    coin_id = hashlib.sha256(
        bytes.fromhex(parent) + bytes.fromhex(puzzle_hash) + b"\x0a"
    ).hexdigest()
    coinset = CoinsetEvidenceProvider(
        SimpleNamespace(
            get_coin_by_name=lambda _coin: {
                "coin": {
                    "parent_coin_info": parent,
                    "puzzle_hash": puzzle_hash,
                    "amount": 10,
                },
                "spent": True,
                "spent_block_index": 123456,
                "confirmed_block_index": 123000,
            }
        )
    )
    spacescan = SpacescanEvidenceProvider(
        SimpleNamespace(
            is_coin_spent=lambda _coin: {
                "spent": True,
                "spent_block": "123456",
                "receiver_address": "xch1example",
            }
        )
    )

    coinset_observation = coinset.observe_coin(coin_id, now=NOW)
    spacescan_observation = spacescan.observe_coin(COIN_ID, now=NOW)

    assert coinset_observation.source_height == 123456
    assert spacescan_observation.source_height == 123456
    assert coinset_observation.quality is ObservationQuality.VALID
    assert spacescan_observation.quality is ObservationQuality.VALID


def test_generic_chain_evidence_never_claims_exact_fill_authority():
    coinset = CoinsetEvidenceProvider(
        SimpleNamespace(get_coin_by_name=lambda _coin: None)
    )
    spacescan = SpacescanEvidenceProvider(
        SimpleNamespace(is_coin_spent=lambda _coin: None)
    )

    assert coinset.capabilities.supports(Capability.CHAIN_EVIDENCE)
    assert spacescan.capabilities.supports(Capability.CHAIN_EVIDENCE)
    assert not coinset.capabilities.supports(Capability.EXACT_FILL_AUTHORITY)
    assert not spacescan.capabilities.supports(Capability.EXACT_FILL_AUTHORITY)


def test_chain_adapter_missing_result_is_degraded_not_unspent():
    provider = CoinsetEvidenceProvider(
        SimpleNamespace(get_coin_by_name=lambda _coin: None)
    )

    observation = provider.observe_coin(COIN_ID, now=NOW)

    assert observation.quality is ObservationQuality.DEGRADED
    assert observation.reason_codes == ("coin_not_observed",)
    assert _payload(observation) == {"available": True, "observed": False}
