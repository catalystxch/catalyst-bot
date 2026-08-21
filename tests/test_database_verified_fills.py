import os
import tempfile
import unittest
import importlib
import sys
import hashlib
import json
from decimal import Decimal


def _load_real_database_module():
    module = sys.modules.get("database")
    if module is not None and hasattr(module, "DB_PATH"):
        return module
    sys.modules.pop("database", None)
    return importlib.import_module("database")


database = _load_real_database_module()


_TEST_WALLET = "f" * 64
_TEST_NETWORK = "mainnet"
_TEST_PREPARED_AT = "2026-01-01T00:00:00+00:00"
_TEST_FILLED_AT = "2026-03-28T00:00:00+00:00"
_TEST_RECONCILED_AT = "2026-12-31T00:00:00+00:00"


def _authoritatively_terminalize_offer(
    trade_id,
    *,
    classification="FILLED_PROVEN",
    selected_coin_ids=None,
    filled_at=_TEST_FILLED_AT,
):
    """Build exact Task 4 state and cross Task 9's sole terminal boundary."""

    offer = database.get_offer(trade_id)
    if offer is None:
        raise AssertionError(f"missing offer fixture: {trade_id}")
    identity = hashlib.sha256(trade_id.encode("utf-8")).hexdigest()
    intent_id = f"verified-fill-test:{identity}"
    selected = list(
        selected_coin_ids
        or [hashlib.sha256(f"selected:{trade_id}".encode("utf-8")).hexdigest()]
    )
    for coin_id in selected:
        database.upsert_coin(
            coin_id,
            "xch" if offer["side"] == "buy" else "cat",
            1,
            tier=offer.get("tier") or "unknown",
        )
    wallet_identity = {
        "wallet_fingerprint_hash": _TEST_WALLET,
        "network": _TEST_NETWORK,
    }
    database.prepare_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:prepared",
        run_id="verified-fill-test-run",
        wallet_fingerprint_hash=_TEST_WALLET,
        network=_TEST_NETWORK,
        asset_id=offer["cat_asset_id"],
        side=offer["side"],
        tier=offer.get("tier") or "unknown",
        purpose="verified_fill_test",
        slot_key=f"verified-fill-test-slot:{identity}",
        generation=0,
        offered_amount_atomic="1",
        requested_amount_atomic="1",
        selected_coin_ids_json=selected,
        wallet_identity_json=wallet_identity,
        evidence_json={"fixture": "authoritative intent"},
        prepared_at=_TEST_PREPARED_AT,
        reserve_selected_coins=True,
    )
    database.finalize_offer_intent(
        intent_id=intent_id,
        operation_id=f"create:{intent_id}",
        event_id=f"create:{intent_id}:finalized",
        lifecycle_state="created",
        outcome="CONFIRMED",
        sage_trade_id=trade_id,
        offer_text_sha256=hashlib.sha256(
            f"offer:{trade_id}".encode("utf-8")
        ).hexdigest(),
        wallet_identity_json=wallet_identity,
        evidence_json={"fixture": "authoritative creation"},
        finalized_at=_TEST_PREPARED_AT,
        finalize_selected_coin_reservations=True,
    )
    evidence = {"fixture": "authoritative terminal proof", "trade_id": trade_id}
    evidence_json = json.dumps(
        evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    terminal = {}
    if classification == "FILLED_PROVEN":
        terminal = {
            "transaction_id": hashlib.sha256(
                f"transaction:{trade_id}".encode("utf-8")
            ).hexdigest(),
            "block_height": 42,
            "receive_coin_id": hashlib.sha256(
                f"receive:{trade_id}".encode("utf-8")
            ).hexdigest(),
            "receive_amount_mojos": 1,
            "filled_at": filled_at,
        }
    return database.commit_offer_reconciliation(
        intent_id=intent_id,
        operation_id=f"reconcile:{intent_id}",
        classification=classification,
        reason_code="TEST_AUTHORITATIVE_PROOF",
        wallet_identity_json=wallet_identity,
        evidence_json=evidence,
        evidence_sha256=hashlib.sha256(evidence_json.encode("utf-8")).hexdigest(),
        reconciled_at=_TEST_RECONCILED_AT,
        **terminal,
    )


class DatabaseVerifiedFillsTests(unittest.TestCase):
    def setUp(self):
        self._orig_db_path = database.DB_PATH
        database.close_connection()
        self._tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self._tmp.close()
        database.DB_PATH = self._tmp.name
        database.init_database()

    def tearDown(self):
        database.close_connection()
        database.DB_PATH = self._orig_db_path
        try:
            os.unlink(self._tmp.name)
        except FileNotFoundError:
            pass

    def test_stats_and_position_ignore_legacy_fills(self):
        conn = database.get_connection()
        asset_id = "asset-test"

        conn.execute(
            """INSERT INTO fills (
                   trade_id, side, price_xch, size_xch, size_cat,
                   filled_at, cat_asset_id, tier, verification_status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "legacy-fill",
                "buy",
                "0.1",
                "1.0",
                "1000",
                "2026-03-20T00:00:00+00:00",
                asset_id,
                "mid",
                "legacy",
            ),
        )
        conn.commit()

        database.record_fill(
            trade_id="verified-fill",
            side="sell",
            price_xch=Decimal("0.2"),
            size_xch=Decimal("2.0"),
            size_cat=Decimal("2000"),
            cat_asset_id=asset_id,
            tier="outer",
        )

        stats = database.get_stats(asset_id)
        fills = database.get_fills(cat_asset_id=asset_id, limit=10)
        position = database.get_net_position(asset_id)

        self.assertEqual(stats["total_fills"], 0)
        self.assertEqual(stats["fill_rate_per_hour"], 0.0)
        self.assertEqual(stats["buy_fills"], 0)
        self.assertEqual(stats["sell_fills"], 0)
        self.assertEqual(fills, [])
        self.assertEqual(position, Decimal("0"))

    def test_stats_report_fee_adjusted_net_xch_flow(self):
        asset_id = "asset-fee-flow"

        database.add_offer(
            trade_id="fee-buy",
            side="buy",
            price_xch=Decimal("0.001"),
            size_xch=Decimal("0.100"),
            size_cat=Decimal("100"),
            cat_asset_id=asset_id,
            tier="inner",
            fee_mojos_xch=1_000_000_000,
        )
        _authoritatively_terminalize_offer("fee-buy")
        database.add_offer(
            trade_id="fee-sell",
            side="sell",
            price_xch=Decimal("0.0011"),
            size_xch=Decimal("0.110"),
            size_cat=Decimal("100"),
            cat_asset_id=asset_id,
            tier="inner",
            fee_mojos_xch=1_000_000_000,
        )
        _authoritatively_terminalize_offer("fee-sell")

        stats = database.get_stats(asset_id)

        self.assertEqual(stats["net_xch_flow"], "0.010")
        self.assertEqual(stats["fee_xch"], "0.002")
        self.assertEqual(stats["net_xch_flow_after_fees"], "0.008")

    def test_offer_coin_usage_summary_counts_requoted_source_coin(self):
        asset_id = "asset-requote"
        coin_id = "0xcoin-reused"

        database.add_offer(
            trade_id="trade-old",
            side="sell",
            price_xch=Decimal("0.001"),
            size_xch=Decimal("0.1"),
            size_cat=Decimal("100"),
            cat_asset_id=asset_id,
            tier="inner",
            coin_id=coin_id,
        )
        database.add_offer(
            trade_id="trade-new",
            side="sell",
            price_xch=Decimal("0.001"),
            size_xch=Decimal("0.1"),
            size_cat=Decimal("100"),
            cat_asset_id=asset_id,
            tier="inner",
            coin_id=coin_id,
        )
        _authoritatively_terminalize_offer("trade-new")

        summary = database.get_offer_coin_usage_summary(coin_id, asset_id)

        self.assertEqual(summary["offer_count"], 2)
        self.assertEqual(summary["verified_fill_count"], 1)
        self.assertEqual(set(summary["trade_ids"]), {"trade-old", "trade-new"})
        self.assertEqual(summary["verified_trade_ids"], ["trade-new"])

    def test_stats_deduplicate_verified_fills_for_reused_source_coin(self):
        asset_id = "asset-requote-stats"
        coin_id = "0xcoin-reused-stats"

        for trade_id in ("trade-old", "trade-new"):
            database.add_offer(
                trade_id=trade_id,
                side="sell",
                price_xch=Decimal("0.001"),
                size_xch=Decimal("0.1"),
                size_cat=Decimal("100"),
                cat_asset_id=asset_id,
                tier="inner",
                coin_id=coin_id,
            )
            _authoritatively_terminalize_offer(trade_id)

        stats = database.get_stats(asset_id)

        self.assertEqual(stats["raw_total_fills"], 2)
        self.assertEqual(stats["duplicate_fill_rows"], 1)
        self.assertEqual(stats["total_fills"], 1)
        self.assertEqual(stats["sell_fills"], 1)
        self.assertEqual(stats["volume_xch"], "0.1")

    def test_status_text_cannot_override_source_coin_authority_deduplication(self):
        asset_id = "asset-requote-exact-stats"
        coin_id = "0xcoin-reused-exact-stats"

        for trade_id, status in (
            ("trade-old", "verified"),
            ("trade-new", "verified_exact"),
        ):
            database.add_offer(
                trade_id=trade_id,
                side="sell",
                price_xch=Decimal("0.001"),
                size_xch=Decimal("0.1"),
                size_cat=Decimal("100"),
                cat_asset_id=asset_id,
                tier="inner",
                coin_id=coin_id,
            )
            result = _authoritatively_terminalize_offer(trade_id)
            database.get_connection().execute(
                "UPDATE fills SET verification_status=? WHERE fill_id=?",
                (status, result["fill_id"]),
            )
            database.get_connection().commit()

        stats = database.get_stats(asset_id)

        self.assertEqual(stats["raw_total_fills"], 2)
        self.assertEqual(stats["duplicate_fill_rows"], 1)
        self.assertEqual(stats["total_fills"], 1)
        self.assertEqual(stats["sell_fills"], 1)
        self.assertEqual(stats["volume_xch"], "0.1")

    def test_unmatched_fills_deduplicate_verified_fills_for_reused_source_coin(self):
        asset_id = "asset-requote-unmatched"
        coin_id = "0xcoin-reused-unmatched"

        for trade_id in ("trade-old", "trade-new"):
            database.add_offer(
                trade_id=trade_id,
                side="sell",
                price_xch=Decimal("0.001"),
                size_xch=Decimal("0.1"),
                size_cat=Decimal("100"),
                cat_asset_id=asset_id,
                tier="inner",
                coin_id=coin_id,
            )
            _authoritatively_terminalize_offer(trade_id)

        unmatched = database.get_unmatched_fills(asset_id, "sell")

        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["trade_id"], "trade-new")

    def test_fill_and_expiry_update_all_locked_coins_for_trade(self):
        conn = database.get_connection()
        asset_id = "asset-test"
        coin_a = hashlib.sha256(b"trade-multi-a").hexdigest()
        coin_b = hashlib.sha256(b"trade-multi-b").hexdigest()

        database.add_offer(
            trade_id="trade-multi",
            side="buy",
            price_xch=Decimal("0.1"),
            size_xch=Decimal("2.2"),
            size_cat=Decimal("22000"),
            cat_asset_id=asset_id,
            tier="inner",
            coin_id=coin_a,
        )
        _authoritatively_terminalize_offer(
            "trade-multi", selected_coin_ids=[coin_a, coin_b]
        )

        rows = conn.execute(
            "SELECT coin_id, status, designation, assigned_tier FROM coins WHERE trade_id=? ORDER BY coin_id",
            ("trade-multi",),
        ).fetchall()
        self.assertEqual(
            [
                (
                    row["coin_id"],
                    row["status"],
                    row["designation"],
                    row["assigned_tier"],
                )
                for row in rows
            ],
            sorted(
                [
                    (database.norm_coin_id(coin_a), "spent", "unknown", "none"),
                    (database.norm_coin_id(coin_b), "spent", "unknown", "none"),
                ]
            ),
        )

        coin_c = hashlib.sha256(b"trade-expire-c").hexdigest()
        coin_d = hashlib.sha256(b"trade-expire-d").hexdigest()
        database.add_offer(
            trade_id="trade-expire",
            side="sell",
            price_xch=Decimal("0.1"),
            size_xch=Decimal("1.1"),
            size_cat=Decimal("8446"),
            cat_asset_id=asset_id,
            tier="mid",
            coin_id=coin_c,
        )
        _authoritatively_terminalize_offer(
            "trade-expire",
            classification="EXPIRED_PROVEN",
            selected_coin_ids=[coin_c, coin_d],
        )

        rows = conn.execute(
            "SELECT coin_id, status, trade_id FROM coins WHERE coin_id IN (?, ?) ORDER BY coin_id",
            (database.norm_coin_id(coin_c), database.norm_coin_id(coin_d)),
        ).fetchall()
        self.assertEqual(
            [(row["coin_id"], row["status"], row["trade_id"]) for row in rows],
            sorted(
                [
                    (database.norm_coin_id(coin_c), "free", None),
                    (database.norm_coin_id(coin_d), "free", None),
                ]
            ),
        )

    def test_stats_net_position_honors_fresh_run_cutoff(self):
        asset_id = "asset-test"

        database.add_offer(
            trade_id="old-run-buy",
            side="buy",
            price_xch=Decimal("0.1"),
            size_xch=Decimal("1.0"),
            size_cat=Decimal("1000"),
            cat_asset_id=asset_id,
            tier="mid",
        )
        _authoritatively_terminalize_offer(
            "old-run-buy", filled_at="2026-03-27T20:00:00+00:00"
        )
        database.add_offer(
            trade_id="fresh-run-sell",
            side="sell",
            price_xch=Decimal("0.1"),
            size_xch=Decimal("0.2"),
            size_cat=Decimal("200"),
            cat_asset_id=asset_id,
            tier="mid",
        )
        _authoritatively_terminalize_offer(
            "fresh-run-sell", filled_at="2026-03-28T22:10:00+00:00"
        )

        stats = database.get_stats(asset_id, since="2026-03-28T22:07:28+00:00")

        self.assertEqual(stats["total_fills"], 1)
        self.assertEqual(stats["net_position"], "-200")
        self.assertEqual(stats["net_cat_flow"], "-200")

    def test_fill_upgrade_clears_cancelled_timestamp(self):
        conn = database.get_connection()
        asset_id = "asset-test"

        database.add_offer(
            trade_id="trade-upgrade",
            side="sell",
            price_xch=Decimal("0.1"),
            size_xch=Decimal("0.24"),
            size_cat=Decimal("1900"),
            cat_asset_id=asset_id,
            tier="extreme",
            coin_id="0xcoin-upgrade",
        )
        conn.execute(
            "UPDATE offers SET cancelled_at=? WHERE trade_id=?",
            ("2026-02-01T00:00:00+00:00", "trade-upgrade"),
        )
        conn.commit()

        _authoritatively_terminalize_offer("trade-upgrade")

        row = conn.execute(
            "SELECT status, filled_at, cancelled_at FROM offers WHERE trade_id=?",
            ("trade-upgrade",),
        ).fetchone()
        self.assertEqual(row["status"], "filled")
        self.assertIsNotNone(row["filled_at"])
        self.assertIsNone(row["cancelled_at"])

    def test_backfill_parks_filled_offer_without_authoritative_proof(self):
        asset_id = "asset-test"
        conn = database.get_connection()

        database.add_offer(
            trade_id="trade-backfill",
            side="sell",
            price_xch=Decimal("0.125"),
            size_xch=Decimal("0.6"),
            size_cat=Decimal("4800"),
            cat_asset_id=asset_id,
            tier="outer",
            coin_id="0xcoin-backfill",
        )
        conn.execute(
            "UPDATE offers SET status='filled', lifecycle_state='filled', filled_at=? "
            "WHERE trade_id=?",
            ("2026-03-27T20:00:00+00:00", "trade-backfill"),
        )
        conn.commit()

        stats_before = database.get_stats(asset_id)
        self.assertEqual(stats_before["total_fills"], 0)

        repaired = database.backfill_verified_fills_from_offers(limit=10)
        self.assertEqual(len(repaired), 1)
        self.assertTrue(repaired[0]["created"])
        self.assertEqual(repaired[0]["trade_id"], "trade-backfill")
        self.assertEqual(repaired[0]["tier"], "outer")
        self.assertEqual(repaired[0]["verification_status"], "legacy_unproven_filled")

        fills = database.get_fills(cat_asset_id=asset_id, limit=10)
        parked = database.get_fills(
            cat_asset_id=asset_id, limit=10, include_legacy=True
        )
        stats_after = database.get_stats(asset_id)

        self.assertEqual(fills, [])
        self.assertEqual(len(parked), 1)
        self.assertEqual(parked[0]["trade_id"], "trade-backfill")
        self.assertEqual(parked[0]["verification_status"], "legacy_unproven_filled")
        self.assertEqual(stats_after["total_fills"], 0)
        self.assertEqual(stats_after["sell_fills"], 0)

    def test_backfill_parks_legacy_fill_without_authoritative_proof(self):
        conn = database.get_connection()
        asset_id = "asset-test"

        database.add_offer(
            trade_id="trade-upgrade-verified",
            side="buy",
            price_xch=Decimal("0.11"),
            size_xch=Decimal("1.2"),
            size_cat=Decimal("10000"),
            cat_asset_id=asset_id,
            tier="mid",
            coin_id="0xcoin-upgrade-verified",
        )
        conn.execute(
            "UPDATE offers SET status='filled', lifecycle_state='filled', filled_at=? "
            "WHERE trade_id=?",
            ("2026-03-27T20:00:00+00:00", "trade-upgrade-verified"),
        )

        conn.execute(
            """INSERT INTO fills (
                   trade_id, side, price_xch, size_xch, size_cat,
                   filled_at, cat_asset_id, tier, verification_status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "trade-upgrade-verified",
                "buy",
                "0.11",
                "1.2",
                "10000",
                "2026-03-27T20:00:00+00:00",
                asset_id,
                "mid",
                "legacy",
            ),
        )
        conn.commit()

        repaired = database.backfill_verified_fills_from_offers(limit=10)
        self.assertEqual(len(repaired), 1)
        self.assertFalse(repaired[0]["upgraded"])
        self.assertFalse(repaired[0]["created"])
        self.assertEqual(repaired[0]["verification_status"], "legacy_unproven_filled")

        row = conn.execute(
            "SELECT verification_status FROM fills WHERE trade_id=?",
            ("trade-upgrade-verified",),
        ).fetchone()
        self.assertEqual(row["verification_status"], "legacy_unproven_filled")
        self.assertEqual(database.get_stats(asset_id)["total_fills"], 0)

    def test_backfill_promotes_only_exact_existing_authoritative_fill(self):
        conn = database.get_connection()
        asset_id = "asset-test"
        trade_id = "trade-authoritative-backfill"

        database.add_offer(
            trade_id=trade_id,
            side="buy",
            price_xch=Decimal("0.11"),
            size_xch=Decimal("1.2"),
            size_cat=Decimal("10000"),
            cat_asset_id=asset_id,
            tier="mid",
            coin_id="0xcoin-authoritative-backfill",
        )
        terminal = _authoritatively_terminalize_offer(trade_id)
        fill_id = terminal["fill_id"]
        conn.execute(
            "UPDATE fills SET verification_status='legacy' WHERE fill_id=?",
            (fill_id,),
        )
        conn.commit()

        repaired = database.backfill_verified_fills_from_offers(limit=10)

        self.assertEqual(
            repaired,
            [
                {
                    "fill_id": fill_id,
                    "trade_id": trade_id,
                    "side": "buy",
                    "price_xch": "0.11",
                    "size_xch": "1.2",
                    "size_cat": "10000",
                    "filled_at": "2026-03-28T00:00:00.000000Z",
                    "cat_asset_id": asset_id,
                    "tier": "mid",
                    "verification_status": "verified_authoritative",
                    "created": False,
                    "upgraded": True,
                }
            ],
        )
        row = conn.execute(
            "SELECT verification_status, spent_block_index, receive_coin_id, "
            "receive_amount_mojos FROM fills WHERE fill_id=?",
            (fill_id,),
        ).fetchone()
        self.assertEqual(row["verification_status"], "verified_authoritative")
        self.assertEqual(row["spent_block_index"], 42)
        self.assertEqual(
            row["receive_coin_id"],
            database.norm_coin_id(
                hashlib.sha256(f"receive:{trade_id}".encode("utf-8")).hexdigest()
            ),
        )
        self.assertEqual(row["receive_amount_mojos"], 1)
        self.assertEqual(database.get_stats(asset_id)["total_fills"], 1)

    def test_backfill_parks_changed_authoritative_fill_identity(self):
        conn = database.get_connection()
        asset_id = "asset-test"
        trade_id = "trade-changed-authoritative-backfill"

        database.add_offer(
            trade_id=trade_id,
            side="sell",
            price_xch=Decimal("0.125"),
            size_xch=Decimal("0.6"),
            size_cat=Decimal("4800"),
            cat_asset_id=asset_id,
            tier="outer",
            coin_id="0xcoin-changed-authoritative-backfill",
        )
        terminal = _authoritatively_terminalize_offer(trade_id)
        conn.execute(
            "UPDATE fills SET verification_status='legacy', size_cat='9999' "
            "WHERE fill_id=?",
            (terminal["fill_id"],),
        )
        conn.commit()

        repaired = database.backfill_verified_fills_from_offers(limit=10)

        self.assertEqual(len(repaired), 1)
        self.assertEqual(repaired[0]["verification_status"], "legacy_unproven_filled")
        row = conn.execute(
            "SELECT verification_status, size_cat FROM fills WHERE fill_id=?",
            (terminal["fill_id"],),
        ).fetchone()
        self.assertEqual(row["verification_status"], "legacy_unproven_filled")
        self.assertEqual(row["size_cat"], "9999")
        self.assertEqual(database.get_stats(asset_id)["total_fills"], 0)

    def test_backfill_and_stats_honor_fresh_run_cutoff(self):
        conn = database.get_connection()
        asset_id = "asset-test"

        database.add_offer(
            trade_id="trade-old-filled",
            side="sell",
            price_xch=Decimal("0.12"),
            size_xch=Decimal("0.6"),
            size_cat=Decimal("5000"),
            cat_asset_id=asset_id,
            tier="outer",
            coin_id="0xcoin-old-filled",
        )
        conn.execute(
            "UPDATE offers SET status='filled', filled_at=?, created_at=? WHERE trade_id=?",
            (
                "2026-03-27T22:00:00+00:00",
                "2026-03-27T21:59:00+00:00",
                "trade-old-filled",
            ),
        )

        database.add_offer(
            trade_id="trade-new-filled",
            side="buy",
            price_xch=Decimal("0.11"),
            size_xch=Decimal("0.6"),
            size_cat=Decimal("5000"),
            cat_asset_id=asset_id,
            tier="outer",
            coin_id="0xcoin-new-filled",
        )
        conn.execute(
            "UPDATE offers SET status='filled', filled_at=?, created_at=? WHERE trade_id=?",
            (
                "2026-03-28T22:10:00+00:00",
                "2026-03-28T22:09:00+00:00",
                "trade-new-filled",
            ),
        )
        conn.commit()

        repaired = database.backfill_verified_fills_from_offers(
            limit=10,
            since="2026-03-28T22:07:28+00:00",
        )
        self.assertEqual(len(repaired), 1)
        self.assertEqual(repaired[0]["trade_id"], "trade-new-filled")
        self.assertEqual(repaired[0]["verification_status"], "legacy_unproven_filled")

        fills = database.get_fills(cat_asset_id=asset_id, limit=10)
        self.assertEqual(fills, [])
        parked = database.get_fills(
            cat_asset_id=asset_id, limit=10, include_legacy=True
        )
        self.assertEqual([f["trade_id"] for f in parked], ["trade-new-filled"])

        stats = database.get_stats(asset_id, since="2026-03-28T22:07:28+00:00")
        self.assertEqual(stats["total_fills"], 0)
        self.assertEqual(stats["buy_fills"], 0)
        self.assertEqual(stats["sell_fills"], 0)


if __name__ == "__main__":
    unittest.main()
