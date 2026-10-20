"""Startup should reuse an already healthy exact Sage session."""

import os
from unittest.mock import patch

import sage_node


def test_exact_active_sage_session_does_not_send_login_rpc():
    previous_phase = sage_node._sage_startup_phase
    try:
        sage_node._sage_startup_phase = "starting"
        with (
            patch.dict(os.environ, {"WALLET_TYPE": "sage"}),
            patch.object(
                sage_node, "_get_live_sage_fingerprint", return_value="736588221"
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": True, "synced": True, "syncing": False},
            ),
            patch("wallet.sage_login", side_effect=AssertionError("redundant login")),
        ):
            assert sage_node._log_in_fingerprint("736588221") is True
            assert sage_node._sage_startup_phase == "ready"
    finally:
        sage_node._sage_startup_phase = previous_phase


def test_failed_sage_login_reports_error_instead_of_endless_starting():
    previous_phase = sage_node._sage_startup_phase
    try:
        sage_node._sage_startup_phase = "error"
        with (
            patch.dict(os.environ, {"WALLET_TYPE": "sage"}),
            patch.object(
                sage_node,
                "get_sage_version_requirement",
                return_value={
                    "minimum_required_version": "0.12.9",
                    "installed_version": "0.13.0",
                    "supported": True,
                },
            ),
        ):
            assert sage_node.get_startup_status()["phase"] == "error"
    finally:
        sage_node._sage_startup_phase = previous_phase


def test_different_active_sage_key_does_not_skip_login():
    previous_phase = sage_node._sage_startup_phase
    try:
        sage_node._sage_startup_phase = "starting"
        with (
            patch.dict(os.environ, {"WALLET_TYPE": "sage"}),
            patch.object(
                sage_node, "_get_live_sage_fingerprint", return_value="3702373391"
            ),
            patch("wallet.get_wallet_sync_status") as sync_status,
            patch("wallet.sage_login", return_value=False) as login,
        ):
            assert sage_node._log_in_fingerprint("736588221") is False
            login.assert_called_once_with(736588221)
            sync_status.assert_not_called()
    finally:
        sage_node._sage_startup_phase = previous_phase


def test_unreachable_sage_wallet_does_not_skip_login():
    previous_phase = sage_node._sage_startup_phase
    try:
        sage_node._sage_startup_phase = "starting"
        with (
            patch.dict(os.environ, {"WALLET_TYPE": "sage"}),
            patch.object(
                sage_node, "_get_live_sage_fingerprint", return_value="736588221"
            ),
            patch(
                "wallet.get_wallet_sync_status",
                return_value={"reachable": False, "synced": False, "syncing": False},
            ),
            patch("wallet.sage_login", return_value=False) as login,
        ):
            assert sage_node._log_in_fingerprint("736588221") is False
            login.assert_called_once_with(736588221)
    finally:
        sage_node._sage_startup_phase = previous_phase
