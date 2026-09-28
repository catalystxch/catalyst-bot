"""Tests for doctor.py — preflight/readiness checks."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from doctor import (
    DoctorCheck,
    DoctorReport,
    run_preflight,
    _check_db_health,
    _check_config_sanity,
    _check_cat_config,
)


class TestDoctorReport(unittest.TestCase):
    def test_can_start_with_no_failures(self):
        report = DoctorReport(
            checks=[
                DoctorCheck("a", "test", "pass", "ok", "info"),
                DoctorCheck("b", "test", "warn", "risky", "warning"),
            ]
        )
        self.assertTrue(report.can_start)

    def test_cannot_start_with_failure(self):
        report = DoctorReport(
            checks=[
                DoctorCheck("a", "test", "pass", "ok", "info"),
                DoctorCheck("b", "test", "fail", "broken", "error"),
            ]
        )
        self.assertFalse(report.can_start)

    def test_summary_blocked(self):
        report = DoctorReport(
            checks=[
                DoctorCheck("a", "test", "fail", "bad", "error"),
            ]
        )
        self.assertIn("BLOCKED", report.summary)

    def test_summary_ok_with_warnings(self):
        report = DoctorReport(
            checks=[
                DoctorCheck("a", "test", "pass", "ok", "info"),
                DoctorCheck("b", "test", "warn", "risky", "warning"),
            ]
        )
        self.assertIn("warning", report.summary)

    def test_summary_all_pass(self):
        report = DoctorReport(
            checks=[
                DoctorCheck("a", "test", "pass", "ok", "info"),
            ]
        )
        self.assertIn("passed", report.summary)

    def test_to_dict(self):
        report = DoctorReport(
            checks=[
                DoctorCheck("test", "cat", "pass", "msg", "info"),
            ]
        )
        d = report.to_dict()
        self.assertIn("can_start", d)
        self.assertIn("checks", d)
        self.assertEqual(len(d["checks"]), 1)
        self.assertEqual(d["checks"][0]["name"], "test")


class TestDoctorCheck_DB(unittest.TestCase):
    @patch("database.get_connection")
    def test_db_health_pass(self, mock_conn_fn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"name": "offers"},
            {"name": "fills"},
            {"name": "events"},
            {"name": "coins"},
        ]
        mock_conn_fn.return_value = mock_conn
        check = _check_db_health()
        self.assertEqual(check.status, "pass")

    @patch("database.get_connection")
    def test_db_health_missing_tables(self, mock_conn_fn):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            {"name": "offers"},
        ]
        mock_conn_fn.return_value = mock_conn
        check = _check_db_health()
        self.assertEqual(check.status, "fail")

    @patch("database.get_connection", side_effect=Exception("DB locked"))
    def test_db_health_error(self, mock_conn_fn):
        check = _check_db_health()
        self.assertEqual(check.status, "fail")


class TestDoctorCheck_Config(unittest.TestCase):
    @patch("config_validator.validate_config")
    def test_config_pass(self, mock_validate):
        from config_validator import ValidationReport

        mock_validate.return_value = ValidationReport()
        check = _check_config_sanity()
        self.assertEqual(check.status, "pass")

    @patch("config_validator.validate_config")
    def test_config_with_errors(self, mock_validate):
        from config_validator import ValidationReport, ConfigIssue

        report = ValidationReport(
            errors=[
                ConfigIssue("X", "bad", "error"),
            ]
        )
        mock_validate.return_value = report
        check = _check_config_sanity()
        self.assertEqual(check.status, "fail")


class TestDoctorCheck_CAT(unittest.TestCase):
    def test_cat_configured(self):
        with patch("config.cfg") as mock_cfg:
            mock_cfg.CAT_ASSET_ID = "abc123"
            mock_cfg.CAT_NAME = "TEST"
            mock_cfg.CAT_DECIMALS = 3
            check = _check_cat_config()
            self.assertEqual(check.status, "pass")

    def test_cat_missing(self):
        with patch("config.cfg") as mock_cfg:
            mock_cfg.CAT_ASSET_ID = ""
            check = _check_cat_config()
            self.assertEqual(check.status, "fail")


class TestDoctorWalletOutage(unittest.TestCase):
    def test_cat_mapping_is_skipped_when_wallet_is_unreachable(self):
        fallback_asset_id = "abc123"
        mock_get_wallets = MagicMock(return_value=[{"asset_id": fallback_asset_id}])

        with (
            patch("doctor._check_db_health") as mock_db,
            patch("doctor._check_config_sanity") as mock_config,
            patch("doctor._check_cat_config") as mock_cat_config,
            patch("doctor._check_dexie_reachable") as mock_dexie,
            patch("doctor._check_tibet_reachable") as mock_tibet,
            patch("doctor._check_splash_reachable") as mock_splash,
            patch("doctor._check_spacescan_setup") as mock_spacescan,
            patch(
                "doctor._fetch_wallet_sync_once",
                return_value={"reachable": False, "_wallet_type": "sage"},
            ),
            patch("config.cfg") as mock_cfg,
            patch.dict(
                "sys.modules",
                {"wallet": SimpleNamespace(get_wallets=mock_get_wallets)},
            ),
        ):
            mock_db.return_value = DoctorCheck(
                "database_health", "database", "pass", "ok", "info"
            )
            mock_config.return_value = DoctorCheck(
                "config_validation", "config", "pass", "ok", "info"
            )
            mock_cat_config.return_value = DoctorCheck(
                "cat_identity", "config", "pass", "ok", "info"
            )
            mock_dexie.return_value = DoctorCheck(
                "dexie_reachable", "exchange", "pass", "ok", "info"
            )
            mock_tibet.return_value = DoctorCheck(
                "tibet_reachable", "exchange", "skip", "skip", "info"
            )
            mock_splash.return_value = DoctorCheck(
                "splash_reachable", "exchange", "skip", "skip", "info"
            )
            mock_spacescan.return_value = DoctorCheck(
                "spacescan_setup", "explorer", "skip", "skip", "info"
            )
            mock_cfg.CAT_ASSET_ID = fallback_asset_id
            mock_cfg.WALLET_TYPE = "sage"
            mock_get_wallets.return_value = [{"asset_id": fallback_asset_id}]

            report = run_preflight(force=True)

        cat_mapping = next(
            check for check in report.checks if check.name == "cat_wallet_mapping"
        )
        self.assertEqual(cat_mapping.status, "skip")
        self.assertIn("wallet not reachable", cat_mapping.message)
        mock_get_wallets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
