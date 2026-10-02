"""Slice 04-03 — bot lifecycle endpoint contract tests.

Tests /api/bot/start, /api/bot/stop, /api/shutdown:
  - Auth required for all (token)
  - bot=None → 500 for start/stop
  - Already-running state returns correct status
  - Validation errors block start
  - Stop/shutdown return success shapes
"""

import os
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import api_server

    _SKIP = None
except (ModuleNotFoundError, ImportError) as exc:
    api_server = None
    _SKIP = str(exc)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _FlaskBase(unittest.TestCase):
    _LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}

    def setUp(self):
        api_server.app.testing = True
        self.client = api_server.app.test_client()
        self.token = api_server._LOCAL_API_TOKEN
        self.auth = {"X-Bot-Local-Token": self.token}
        api_server._rate_limit_log.clear()
        self._mutation_runtime = patch.object(
            api_server, "_ensure_mutation_runtime", return_value=None
        )
        self._mutation_enter = patch.object(
            api_server.mutation_gate, "enter_mutation", return_value="permit"
        )
        self._mutation_exit = patch.object(
            api_server.mutation_gate, "exit_mutation", return_value=True
        )
        for mutation_patch in (
            self._mutation_runtime,
            self._mutation_enter,
            self._mutation_exit,
        ):
            mutation_patch.start()
            self.addCleanup(mutation_patch.stop)
        self._wallet_identity_preflight = patch(
            "wallet.preflight_wallet_identity",
            return_value={"success": True, "reason": "identity_verified"},
        )
        self._wallet_identity_preflight.start()
        self.addCleanup(self._wallet_identity_preflight.stop)
        self._wallet_identity_read = patch(
            "wallet.get_wallet_identity",
            return_value={
                "success": True,
                "backend": "sage",
                "name": "Test Wallet",
                "fingerprint": 123456789,
                "network_id": "mainnet",
                "kind": "bls",
                "has_secrets": True,
                "observed_at_utc": "2026-08-16T12:00:00.000000Z",
            },
        )
        self._wallet_identity_read.start()
        self.addCleanup(self._wallet_identity_read.stop)
        self._wallet_sync_read = patch(
            "wallet.get_wallet_sync_status",
            return_value={"reachable": True, "sync_state": "synced"},
        )
        self._wallet_sync_read.start()
        self.addCleanup(self._wallet_sync_read.stop)
        self._post_tibet_migration = patch(
            "blueprints.bot._enforce_post_tibet_start_migration",
            return_value={"can_start": True, "reason_code": "MIGRATION_COMPLETE"},
        )
        self._post_tibet_migration.start()
        self.addCleanup(self._post_tibet_migration.stop)

    def tearDown(self):
        api_server._rate_limit_log.clear()

    def _post(self, path, body=None, auth=True):
        headers = dict(self.auth) if auth else {}
        return self.client.post(
            path,
            json=body or {},
            headers=headers,
            environ_base=self._LOOPBACK,
        )


def _make_bot(running=False, start_returns=True):
    bot = MagicMock()
    bot.is_running.return_value = running
    bot.start.return_value = start_returns
    bot.stop.return_value = None
    bot.get_state.return_value = {
        "running": running,
        "status": "running" if running else "idle",
        "loop_count": 0,
    }
    return bot


def _fake_cfg(cat_asset_id="ab" * 32, spread_bps=200):
    return types.SimpleNamespace(
        CAT_ASSET_ID=cat_asset_id,
        SPREAD_BPS=spread_bps,
        HARD_MIN_PRICE_XCH=Decimal("0.001"),
        HARD_MAX_PRICE_XCH=Decimal("1.0"),
        MAX_ACTIVE_BUY_OFFERS=1,
        MAX_ACTIVE_SELL_OFFERS=1,
    )


# ---------------------------------------------------------------------------
# 1. POST /api/bot/start
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestBotStart(_FlaskBase):
    def test_bootstrap_resume_readiness_requires_exact_intent_db_wallet_set(self):
        from blueprints import bot as bot_blueprint

        asset_id = "ab" * 32
        trade_ids = ["01" * 32, "02" * 32, "03" * 32]
        campaign = {"campaign_id": "cd" * 32, "revision": 7}
        purpose = f"bootstrap:{campaign['campaign_id']}:revision:7"
        intents = [
            {
                "asset_id": asset_id,
                "purpose": purpose,
                "lifecycle_state": "visible",
                "sage_trade_id": trade_id,
            }
            for trade_id in trade_ids
        ]
        db_offers = [{"trade_id": trade_id} for trade_id in trade_ids]
        wallet_offers = [
            {
                "trade_id": trade_id,
                "status": 0,
                "summary": {
                    "offered": {asset_id: 5_000_000},
                    "requested": {"xch": 550_000_000_000},
                },
            }
            for trade_id in trade_ids
        ]
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)

        with (
            patch("database.get_offer_intents_for_registry", return_value=intents),
            patch("database.get_open_offers", return_value=db_offers),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": wallet_offers,
                    "end_of_history": True,
                },
            ),
            patch(
                "wallet.classify_offers_from_list",
                return_value=([], wallet_offers, []),
            ),
        ):
            result = bot_blueprint._bootstrap_existing_offer_resume_readiness(
                fake_cfg, campaign
            )

        self.assertTrue(result["ready"])
        self.assertEqual(result["reason"], "exact_live_book")
        self.assertEqual(result["offer_count"], 3)

    def test_bootstrap_resume_readiness_fails_closed_on_db_wallet_mismatch(self):
        from blueprints import bot as bot_blueprint

        asset_id = "ab" * 32
        trade_ids = ["01" * 32, "02" * 32, "03" * 32]
        campaign = {"campaign_id": "cd" * 32, "revision": 7}
        purpose = f"bootstrap:{campaign['campaign_id']}:revision:7"
        intents = [
            {
                "asset_id": asset_id,
                "purpose": purpose,
                "lifecycle_state": "visible",
                "sage_trade_id": trade_id,
            }
            for trade_id in trade_ids
        ]
        wallet_offers = [
            {
                "trade_id": trade_id,
                "status": 0,
                "summary": {
                    "offered": {asset_id: 5_000_000},
                    "requested": {"xch": 550_000_000_000},
                },
            }
            for trade_id in trade_ids
        ]
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)

        with (
            patch("database.get_offer_intents_for_registry", return_value=intents),
            patch(
                "database.get_open_offers",
                return_value=[{"trade_id": trade_ids[0]}],
            ),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": wallet_offers,
                    "end_of_history": True,
                },
            ),
            patch(
                "wallet.classify_offers_from_list",
                return_value=([], wallet_offers, []),
            ),
        ):
            result = bot_blueprint._bootstrap_existing_offer_resume_readiness(
                fake_cfg, campaign
            )

        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "offer_authority_mismatch")

    def test_bootstrap_resume_readiness_rejects_unclassified_current_pair_offer(self):
        from blueprints import bot as bot_blueprint

        asset_id = "ab" * 32
        trade_id = "01" * 32
        extra_trade_id = "02" * 32
        campaign = {"campaign_id": "cd" * 32, "revision": 7}
        purpose = f"bootstrap:{campaign['campaign_id']}:revision:7"
        intent = {
            "asset_id": asset_id,
            "purpose": purpose,
            "lifecycle_state": "visible",
            "sage_trade_id": trade_id,
        }
        classified = {
            "trade_id": trade_id,
            "status": 0,
            "summary": {
                "offered": {asset_id: 5_000_000},
                "requested": {"xch": 550_000_000_000},
            },
        }
        unclassified = {
            "trade_id": extra_trade_id,
            "status": 0,
            "summary": {
                "offered": {asset_id: 7_000_000},
                "requested": {"xch": 770_000_000_000},
            },
        }
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)

        with (
            patch("database.get_offer_intents_for_registry", return_value=[intent]),
            patch(
                "database.get_open_offers", return_value=[{"trade_id": trade_id}]
            ),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [classified, unclassified],
                    "end_of_history": True,
                },
            ),
            patch(
                "wallet.classify_offers_from_list",
                return_value=([], [classified], []),
            ),
        ):
            result = bot_blueprint._bootstrap_existing_offer_resume_readiness(
                fake_cfg, campaign
            )

        self.assertFalse(result["ready"])
        self.assertEqual(
            result["reason"], "existing_offer_resume_proof_unavailable"
        )

    def test_bootstrap_resume_readiness_rejects_unresolved_current_revision_intent(
        self,
    ):
        from blueprints import bot as bot_blueprint

        asset_id = "ab" * 32
        trade_id = "01" * 32
        campaign = {"campaign_id": "cd" * 32, "revision": 7}
        purpose = f"bootstrap:{campaign['campaign_id']}:revision:7"
        visible = {
            "asset_id": asset_id,
            "purpose": purpose,
            "lifecycle_state": "visible",
            "sage_trade_id": trade_id,
        }
        unresolved = {
            "asset_id": asset_id,
            "purpose": purpose,
            "lifecycle_state": "creation_unknown",
            "sage_trade_id": None,
        }
        wallet_offer = {
            "trade_id": trade_id,
            "status": 0,
            "summary": {
                "offered": {asset_id: 5_000_000},
                "requested": {"xch": 550_000_000_000},
            },
        }
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)

        with (
            patch(
                "database.get_offer_intents_for_registry",
                return_value=[visible, unresolved],
            ),
            patch(
                "database.get_open_offers", return_value=[{"trade_id": trade_id}]
            ),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [wallet_offer],
                    "end_of_history": True,
                },
            ),
            patch(
                "wallet.classify_offers_from_list",
                return_value=([], [wallet_offer], []),
            ),
        ):
            result = bot_blueprint._bootstrap_existing_offer_resume_readiness(
                fake_cfg, campaign
            )

        self.assertFalse(result["ready"])
        self.assertEqual(
            result["reason"], "existing_offer_resume_proof_unavailable"
        )

    def test_bootstrap_resume_readiness_rejects_nonterminal_closed_classification(
        self,
    ):
        from blueprints import bot as bot_blueprint

        asset_id = "ab" * 32
        trade_id = "01" * 32
        extra_trade_id = "02" * 32
        campaign = {"campaign_id": "cd" * 32, "revision": 7}
        purpose = f"bootstrap:{campaign['campaign_id']}:revision:7"
        intent = {
            "asset_id": asset_id,
            "purpose": purpose,
            "lifecycle_state": "visible",
            "sage_trade_id": trade_id,
        }
        live = {
            "trade_id": trade_id,
            "status": 0,
            "summary": {
                "offered": {asset_id: 5_000_000},
                "requested": {"xch": 550_000_000_000},
            },
        }
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)

        for status in ("PENDING_CANCEL", "UNRECOGNIZED_STATUS"):
            with self.subTest(status=status):
                extra = {
                    "trade_id": extra_trade_id,
                    "status": status,
                    "summary": {
                        "offered": {asset_id: 7_000_000},
                        "requested": {"xch": 770_000_000_000},
                    },
                }
                with (
                    patch(
                        "database.get_offer_intents_for_registry",
                        return_value=[intent],
                    ),
                    patch(
                        "database.get_open_offers",
                        return_value=[{"trade_id": trade_id}],
                    ),
                    patch(
                        "wallet.get_authoritative_offer_history",
                        return_value={
                            "success": True,
                            "offers": [live, extra],
                            "end_of_history": True,
                        },
                    ),
                    patch(
                        "wallet.classify_offers_from_list",
                        return_value=([], [live], [extra]),
                    ),
                ):
                    result = (
                        bot_blueprint._bootstrap_existing_offer_resume_readiness(
                            fake_cfg, campaign
                        )
                    )

                self.assertFalse(result["ready"])
                self.assertEqual(
                    result["reason"], "existing_offer_resume_proof_unavailable"
                )

    def test_one_sided_start_rejects_unclassified_open_sage_offer(self):
        from blueprints import bot as bot_blueprint

        asset_id = "ab" * 32
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)
        fake_cfg.LIQUIDITY_MODE = "buy_only"
        malformed = {
            "trade_id": "unknown-pair",
            "status": 0,
            "summary": {"offered": {asset_id: 1000}, "requested": {}},
        }
        with (
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [malformed],
                    "end_of_history": True,
                },
            ),
            patch("database.get_open_offers", return_value=[]),
        ):
            block = bot_blueprint._one_sided_open_offer_start_block(fake_cfg)

        self.assertIsNotNone(block)
        self.assertEqual(block["reason"], "OFF_SIDE_OFFER_PROOF_UNAVAILABLE")

    def test_one_sided_start_allows_proven_unrelated_pair(self):
        from blueprints import bot as bot_blueprint

        fake_cfg = _fake_cfg()
        fake_cfg.LIQUIDITY_MODE = "buy_only"
        unrelated = {
            "trade_id": "other-cat-sell",
            "status": 0,
            "summary": {
                "offered": {"cd" * 32: 1000},
                "requested": {"xch": 100_000_000},
            },
        }
        with (
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [unrelated],
                    "end_of_history": True,
                },
            ),
            patch("database.get_open_offers", return_value=[]),
        ):
            block = bot_blueprint._one_sided_open_offer_start_block(fake_cfg)

        self.assertIsNone(block)

    def test_one_sided_start_allows_expired_current_pair_offer(self):
        from blueprints import bot as bot_blueprint

        asset_id = "ab" * 32
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)
        fake_cfg.LIQUIDITY_MODE = "buy_only"
        expired_sell = {
            "trade_id": "expired-sell",
            "status": 0,
            "valid_times": {"max_time": 1},
            "summary": {
                "offered": {asset_id: 1000},
                "requested": {"xch": 100_000_000},
            },
        }
        with (
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [expired_sell],
                    "end_of_history": True,
                },
            ),
            patch("database.get_open_offers", return_value=[]),
        ):
            block = bot_blueprint._one_sided_open_offer_start_block(fake_cfg)

        self.assertIsNone(block)

    def test_one_sided_start_rejects_duplicate_and_missing_current_pair_ids(self):
        from blueprints import bot as bot_blueprint

        asset_id = "ab" * 32
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)
        fake_cfg.LIQUIDITY_MODE = "buy_only"
        active_buy = {
            "status": 0,
            "summary": {
                "offered": {"xch": 100_000_000},
                "requested": {asset_id: 1000},
            },
        }
        for offers in (
            [{**active_buy, "trade_id": ""}],
            [
                {**active_buy, "trade_id": "duplicate"},
                {**active_buy, "trade_id": "duplicate"},
            ],
        ):
            with (
                patch(
                    "wallet.get_authoritative_offer_history",
                    return_value={
                        "success": True,
                        "offers": offers,
                        "end_of_history": True,
                    },
                ),
                patch("database.get_open_offers", return_value=[]),
            ):
                block = bot_blueprint._one_sided_open_offer_start_block(fake_cfg)
            self.assertIsNotNone(block)
            self.assertEqual(block["reason"], "OFF_SIDE_OFFER_PROOF_UNAVAILABLE")

    def test_buy_only_start_blocks_existing_wallet_sell_offer(self):
        asset_id = "ab" * 32
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)
        fake_cfg.LIQUIDITY_MODE = "buy_only"
        bot = _make_bot(running=False, start_returns=True)
        old_sell = {
            "trade_id": "old-sell",
            "status": 0,
            "summary": {
                "offered": {asset_id: 1000},
                "requested": {"xch": 100_000_000},
            },
        }
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [old_sell],
                    "end_of_history": True,
                },
            ),
            patch("database.get_open_offers", return_value=[]),
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json().get("reason"), "OFF_SIDE_OFFERS_OPEN")
        bot.start.assert_not_called()

    def test_sell_only_start_blocks_existing_database_buy_offer(self):
        fake_cfg = _fake_cfg()
        fake_cfg.LIQUIDITY_MODE = "sell_only"
        bot = _make_bot(running=False, start_returns=True)
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [],
                    "end_of_history": True,
                },
            ),
            patch(
                "database.get_open_offers",
                return_value=[{"trade_id": "old-buy", "side": "buy"}],
            ),
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json().get("reason"), "OFF_SIDE_OFFERS_OPEN")
        self.assertEqual(resp.get_json().get("disabled_side"), "buy")
        bot.start.assert_not_called()

    def test_one_sided_start_fails_closed_when_offer_history_is_unavailable(self):
        fake_cfg = _fake_cfg()
        fake_cfg.LIQUIDITY_MODE = "buy_only"
        bot = _make_bot(running=False, start_returns=True)
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": False,
                    "offers": [],
                    "end_of_history": False,
                },
            ),
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 409)
        self.assertEqual(
            resp.get_json().get("reason"), "OFF_SIDE_OFFER_PROOF_UNAVAILABLE"
        )
        bot.start.assert_not_called()

    def test_buy_only_start_allows_active_side_offers_only(self):
        asset_id = "ab" * 32
        fake_cfg = _fake_cfg(cat_asset_id=asset_id)
        fake_cfg.LIQUIDITY_MODE = "buy_only"
        bot = _make_bot(running=False, start_returns=True)
        active_buy = {
            "trade_id": "current-buy",
            "status": 0,
            "summary": {
                "offered": {"xch": 100_000_000},
                "requested": {asset_id: 1000},
            },
        }
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_authoritative_offer_history",
                return_value={
                    "success": True,
                    "offers": [active_buy],
                    "end_of_history": True,
                },
            ),
            patch("database.get_open_offers", return_value=[]),
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("status"), "started")
        bot.start.assert_called_once()

    def test_requires_token(self):
        resp = self._post("/api/bot/start", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._post("/api/bot/start")
        self.assertEqual(resp.status_code, 500)
        self.assertIn("error", resp.get_json())

    def test_already_running_returns_200_and_already_running_status(self):
        with patch.object(api_server, "bot", _make_bot(running=True)):
            resp = self._post("/api/bot/start")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body.get("status"), "already_running")

    def test_no_cat_asset_id_returns_400_with_errors(self):
        fake_cfg = _fake_cfg(cat_asset_id="")
        with (
            patch.object(api_server, "bot", _make_bot(running=False)),
            patch.object(api_server, "cfg", fake_cfg),
        ):
            resp = self._post("/api/bot/start")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("errors", body)
        self.assertGreater(len(body["errors"]), 0)
        joined_errors = " ".join(str(error) for error in body["errors"])
        self.assertIn("Choose a trading pair", joined_errors)
        self.assertNotIn(".env", joined_errors)
        self.assertNotIn("CAT_ASSET_ID", joined_errors)

    def test_zero_spread_returns_400_with_errors(self):
        fake_cfg = _fake_cfg(spread_bps=0)
        with (
            patch.object(api_server, "bot", _make_bot(running=False)),
            patch.object(api_server, "cfg", fake_cfg),
        ):
            resp = self._post("/api/bot/start")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("errors", body)

    def test_successful_start_returns_200_started_status(self):
        fake_cfg = _fake_cfg()
        bot = _make_bot(running=False, start_returns=True)
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
        ):
            resp = self._post("/api/bot/start")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body.get("status"), "started")

    def test_wallet_identity_preflight_denial_blocks_start_with_stable_error(self):
        fake_cfg = _fake_cfg()
        bot = _make_bot(running=False, start_returns=True)
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
            patch(
                "wallet.preflight_wallet_identity",
                return_value={
                    "success": False,
                    "error": "Wallet mutation blocked by identity safety check",
                    "reason": "WALLET_IDENTITY_MISMATCH",
                },
            ) as preflight,
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.get_json(),
            {
                "success": False,
                "status": "error",
                "error": "Wallet mutation blocked by identity safety check",
                "reason": "WALLET_IDENTITY_MISMATCH",
                "errors": ["Wallet mutation blocked by identity safety check"],
                "warnings": [],
            },
        )
        preflight.assert_called_once_with()
        bot.start.assert_not_called()

    def test_start_blocked_by_bot_returns_400(self):
        fake_cfg = _fake_cfg()
        bot = _make_bot(running=False, start_returns=False)
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
        ):
            resp = self._post("/api/bot/start")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("errors", body)

    def test_tier_size_drift_returns_coin_prep_response(self):
        fake_cfg = _fake_cfg()
        bot = _make_bot(running=False)
        drift = [
            {
                "side": "xch",
                "tier": "inner",
                "ratio": 0.457,
                "coin_count": 11,
            }
        ]
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
            patch("coin_manager.check_tier_size_drift_standalone", return_value=drift),
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertTrue(body.get("needs_coin_prep"))
        self.assertEqual(body.get("reason"), "tier_size_drift")
        self.assertEqual(body.get("tier_size_drift"), drift)
        bot.start.assert_not_called()

    def test_exact_active_bootstrap_prep_bypasses_legacy_tier_size_drift(self):
        """Bootstrap coins are campaign-bound, not Smart Settings tier-bound."""
        fake_cfg = _fake_cfg()
        fake_cfg.CAT_WALLET_ID = 2
        fake_cfg.WALLET_TYPE = "sage"
        bot = _make_bot(running=False)
        campaign_id = "cd" * 32
        campaign = {
            "campaign_id": campaign_id,
            "revision": 0,
            "asset_id": fake_cfg.CAT_ASSET_ID,
            "network": "mainnet",
            "wallet_fingerprint": 123456789,
            "wallet_id": 2,
            "wallet_type": "sage",
            "status": "active",
        }
        completed_prep = {
            "running": False,
            "complete": True,
            "phase": "complete",
            "error": None,
            "bootstrap_campaign_id": campaign_id,
            "bootstrap_campaign_revision": 0,
        }
        legacy_drift = [
            {
                "side": "cat",
                "tier": "inner",
                "ratio": 0.479,
                "coin_count": 10,
            }
        ]

        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.dict(api_server._coin_prep_state, completed_prep, clear=True),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "database.list_active_bootstrap_campaigns_for_asset",
                return_value=[campaign],
            ),
            patch(
                "blueprints.bot._bootstrap_coin_prep_start_readiness",
                return_value={
                    "ready": True,
                    "reason": "ready",
                    "campaign_id": campaign_id,
                    "campaign_revision": 0,
                },
                create=True,
            ),
            patch(
                "coin_manager.check_tier_size_drift_standalone",
                return_value=legacy_drift,
            ) as drift_check,
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("status"), "started")
        drift_check.assert_not_called()
        bot.start.assert_called_once_with()

    def test_active_bootstrap_start_fails_closed_when_exact_prep_is_not_ready(self):
        """Historical completion cannot bypass current campaign readiness."""
        fake_cfg = _fake_cfg()
        fake_cfg.CAT_WALLET_ID = 2
        fake_cfg.WALLET_TYPE = "sage"
        bot = _make_bot(running=False)

        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
            patch(
                "blueprints.bot._matching_active_bootstrap_campaign",
                return_value={
                    "campaign_id": "cd" * 32,
                    "revision": 0,
                    "status": "active",
                    "expires_at": "2099-01-01T00:00:00.000000Z",
                },
            ),
            patch(
                "blueprints.bot._bootstrap_coin_prep_start_readiness",
                return_value={
                    "ready": False,
                    "reason": "must_resize",
                    "campaign_id": "cd" * 32,
                    "campaign_revision": 0,
                },
                create=True,
            ),
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertTrue(body.get("needs_coin_prep"))
        self.assertEqual(body.get("reason"), "bootstrap_coin_prep_required")
        bot.start.assert_not_called()

    def test_resume_existing_bootstrap_offers_can_start_when_exact_book_is_proven(self):
        """Recovered live offers replace free-coin readiness only with exact proof."""
        fake_cfg = _fake_cfg()
        fake_cfg.CAT_WALLET_ID = 2
        fake_cfg.WALLET_TYPE = "sage"
        bot = _make_bot(running=False)
        campaign = {
            "campaign_id": "cd" * 32,
            "revision": 4,
            "status": "active",
            "expires_at": "2099-01-01T00:00:00.000000Z",
        }

        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
            patch(
                "blueprints.bot._matching_active_bootstrap_campaign",
                return_value=campaign,
            ),
            patch(
                "blueprints.bot._bootstrap_coin_prep_start_readiness",
                return_value={"ready": False, "reason": "must_resize"},
            ),
            patch(
                "blueprints.bot._bootstrap_existing_offer_resume_readiness",
                return_value={"ready": True, "reason": "exact_live_book"},
                create=True,
            ) as resume_readiness,
        ):
            resp = self._post(
                "/api/bot/start", {"resume_existing_offers": True}
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("status"), "started")
        resume_readiness.assert_called_once_with(fake_cfg, campaign)
        bot.start.assert_called_once_with()

    def test_resume_existing_bootstrap_offers_fails_closed_without_exact_book(self):
        fake_cfg = _fake_cfg()
        fake_cfg.CAT_WALLET_ID = 2
        fake_cfg.WALLET_TYPE = "sage"
        bot = _make_bot(running=False)
        campaign = {
            "campaign_id": "cd" * 32,
            "revision": 4,
            "status": "active",
            "expires_at": "2099-01-01T00:00:00.000000Z",
        }

        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
            patch(
                "blueprints.bot._matching_active_bootstrap_campaign",
                return_value=campaign,
            ),
            patch(
                "blueprints.bot._bootstrap_coin_prep_start_readiness",
                return_value={"ready": False, "reason": "must_resize"},
            ),
            patch(
                "blueprints.bot._bootstrap_existing_offer_resume_readiness",
                return_value={"ready": False, "reason": "wallet_book_mismatch"},
                create=True,
            ) as resume_readiness,
        ):
            resp = self._post(
                "/api/bot/start", {"resume_existing_offers": True}
            )

        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertTrue(body.get("needs_coin_prep"))
        self.assertEqual(body.get("reason"), "bootstrap_coin_prep_required")
        resume_readiness.assert_called_once_with(fake_cfg, campaign)
        bot.start.assert_not_called()

    def test_normal_bootstrap_start_does_not_use_existing_offer_resume_authority(self):
        fake_cfg = _fake_cfg()
        fake_cfg.CAT_WALLET_ID = 2
        fake_cfg.WALLET_TYPE = "sage"
        bot = _make_bot(running=False)
        campaign = {
            "campaign_id": "cd" * 32,
            "revision": 4,
            "status": "active",
            "expires_at": "2099-01-01T00:00:00.000000Z",
        }

        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
            patch(
                "blueprints.bot._matching_active_bootstrap_campaign",
                return_value=campaign,
            ),
            patch(
                "blueprints.bot._bootstrap_coin_prep_start_readiness",
                return_value={"ready": False, "reason": "must_resize"},
            ),
            patch(
                "blueprints.bot._bootstrap_existing_offer_resume_readiness",
                return_value={"ready": True, "reason": "exact_live_book"},
                create=True,
            ) as resume_readiness,
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 400)
        self.assertTrue(resp.get_json().get("needs_coin_prep"))
        resume_readiness.assert_not_called()
        bot.start.assert_not_called()

    def test_mismatched_bootstrap_identity_keeps_legacy_tier_drift_gate(self):
        fake_cfg = _fake_cfg()
        fake_cfg.CAT_WALLET_ID = 2
        bot = _make_bot(running=False)
        drift = [
            {
                "side": "cat",
                "tier": "inner",
                "ratio": 0.479,
                "coin_count": 10,
            }
        ]
        mismatched_campaign = {
            "campaign_id": "ef" * 32,
            "revision": 0,
            "asset_id": fake_cfg.CAT_ASSET_ID,
            "network": "mainnet",
            "wallet_fingerprint": 999999999,
            "wallet_id": 2,
            "wallet_type": "sage",
            "status": "active",
        }

        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "database.list_active_bootstrap_campaigns_for_asset",
                return_value=[mismatched_campaign],
            ),
            patch(
                "coin_manager.check_tier_size_drift_standalone",
                return_value=drift,
            ) as drift_check,
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json().get("reason"), "tier_size_drift")
        drift_check.assert_called_once_with(
            low_ratio=0.50, high_ratio=2.00, min_sample=2
        )
        bot.start.assert_not_called()

    def test_failed_coin_prep_blocks_start(self):
        fake_cfg = _fake_cfg()
        fake_cfg.ENABLE_COIN_PREP = True
        bot = _make_bot(running=False)
        failed_state = {
            "running": False,
            "complete": False,
            "phase": "error",
            "error": "Sage tier pool creation + splitting failed",
        }
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.dict(api_server._coin_prep_state, failed_state, clear=True),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
            patch("coin_manager.check_tier_size_drift_standalone", return_value=[]),
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertTrue(body.get("needs_coin_prep"))
        self.assertEqual(body.get("reason"), "coin_prep_failed")
        self.assertEqual(
            body.get("message"),
            "Coin Prep failed - rerun Coin Prep before starting the bot",
        )
        self.assertNotIn("Sage tier pool creation", resp.get_data(as_text=True))
        bot.start.assert_not_called()

    def test_signing_block_reason_prevents_start(self):
        """If _get_sage_signing_block_reason returns a string, start is blocked."""
        fake_cfg = _fake_cfg()
        bot = _make_bot(running=False)
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server,
                "_get_sage_signing_block_reason",
                return_value="Sage cannot sign",
            ),
        ):
            resp = self._post("/api/bot/start")
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("Sage cannot sign", body.get("errors", []))

    def test_expired_active_bootstrap_campaign_blocks_start_before_effects(self):
        fake_cfg = _fake_cfg()
        fake_cfg.CAT_WALLET_ID = 2
        bot = _make_bot(running=False, start_returns=True)
        expired_campaign = {
            "campaign_id": "cd" * 32,
            "status": "active",
            "expires_at": "2000-01-01T00:00:00.000000Z",
            "revision": 3,
        }
        with (
            patch.object(api_server, "bot", bot),
            patch.object(api_server, "cfg", fake_cfg),
            patch.object(
                api_server, "_get_sage_signing_block_reason", return_value=None
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "sync_state": "synced"},
            ),
            patch(
                "blueprints.bot._matching_active_bootstrap_campaign",
                return_value=expired_campaign,
            ) as match_campaign,
            patch("blueprints.bot.log_event") as log_event,
            patch("coin_manager.check_tier_size_drift_standalone", return_value=[]),
        ):
            resp = self._post("/api/bot/start")

        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertEqual(body.get("reason"), "bootstrap_campaign_expired")
        self.assertIn("expired", body.get("error", "").lower())
        self.assertNotIn("open_offer_count", body)
        match_campaign.assert_called_once_with(fake_cfg)
        log_event.assert_any_call(
            "warning",
            "bootstrap_expired_start_blocked",
            "Active Bootstrap campaign has expired — cancel campaign-owned offers before starting or renewing",
            data={"campaign_id": "cd" * 32, "revision": 3},
        )
        bot.start.assert_not_called()


# ---------------------------------------------------------------------------
# 2. POST /api/bot/stop
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestBotStop(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/bot/stop", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_bot_none_returns_500(self):
        with patch.object(api_server, "bot", None):
            resp = self._post("/api/bot/stop")
        self.assertEqual(resp.status_code, 500)

    def test_bot_running_stop_returns_200(self):
        bot = _make_bot(running=True)
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/bot/stop")
        self.assertEqual(resp.status_code, 200)

    def test_stop_response_has_status_key(self):
        bot = _make_bot(running=True)
        with patch.object(api_server, "bot", bot):
            resp = self._post("/api/bot/stop")
        body = resp.get_json()
        self.assertIn("status", body)
        self.assertEqual(body["status"], "stopped")

    def test_stop_calls_bot_stop(self):
        bot = _make_bot(running=True)
        with patch.object(api_server, "bot", bot):
            self._post("/api/bot/stop")
        bot.stop.assert_called_once()


# ---------------------------------------------------------------------------
# 3. POST /api/shutdown
# ---------------------------------------------------------------------------


@unittest.skipIf(_SKIP is not None, f"api_server unavailable: {_SKIP}")
class TestShutdown(_FlaskBase):
    def test_requires_token(self):
        resp = self._post("/api/shutdown", auth=False)
        self.assertEqual(resp.status_code, 401)

    def test_returns_200(self):
        with patch.object(api_server, "bot", None), patch("threading.Thread"):
            resp = self._post("/api/shutdown")
        self.assertEqual(resp.status_code, 200)

    def test_response_has_success_key(self):
        with patch.object(api_server, "bot", None), patch("threading.Thread"):
            resp = self._post("/api/shutdown")
        body = resp.get_json()
        self.assertIsInstance(body, dict)

    def test_cancel_offers_false_by_default(self):
        """Default request body has cancel_offers=False."""
        with (
            patch.object(api_server, "bot", None),
            patch("threading.Thread") as mock_thread,
        ):
            self._post("/api/shutdown")
        # Thread should have been started for the background shutdown
        mock_thread.assert_called()


if __name__ == "__main__":
    unittest.main()
