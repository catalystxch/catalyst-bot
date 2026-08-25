import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "bot_gui.html"


def test_user_facing_rate_controls_and_diagnostics_are_percent_first():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "Arb Alert Threshold (%)" in html
    assert "Arb Alert Threshold (bps)" not in html
    assert "Dexie/Tibet gap, as a percentage" in html
    assert "basis points, that marks an arbitrage alert" not in html
    assert "100 bps = 1%" not in html
    assert "return n.toFixed(1) + ' bps';" not in html
    assert "return bps2pct(n);" in html
    assert "offset_bps" not in html


def test_arb_alert_threshold_round_trips_percent_in_settings_ui():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "const _pct2bps = v => Math.round((parseFloat(v) || 0) * 100);" in html
    assert (
        "document.getElementById('configArbThreshold').value = arb > 0 ? _bps2pct(arb) : '2.0';"
        in html
    )
    assert (
        "arb_threshold_bps: _pct2bps(document.getElementById('configArbThreshold')?.value || '2.0'),"
        in html
    )
    assert "_arbEl.value = _bps2pct(data.arb_alert_threshold_bps);" in html
    assert (
        "arb_threshold_bps: parseInt(document.getElementById('configArbThreshold')?.value || '200')"
        not in html
    )


def test_smart_settings_summary_converts_bps_values_before_rendering_percent():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "const spreadPct = bps2pct(data.base_spread_bps || 0);" in html
    assert "const requotePct = bps2pct(data.requote_bps || 0);" in html
    assert "Base <strong>${spreadPct}</strong>" in html
    assert "Requote at <strong>${requotePct}</strong>" in html
    assert (
        "document.getElementById('configDbxMaxSpreadBps').value = _bps2pct(data.dbx_max_spread_bps);"
        in html
    )
    assert "Base <strong>${spreadBps.toFixed(1)}%</strong>" not in html


def test_live_market_health_fallback_recomputes_inner_spread_from_edges():
    html = GUI.read_text(encoding="utf-8", errors="replace")

    assert "mid_price: data.mid_price," in html
    assert "const liveBid = parseFloat(metrics.our_best_bid || 0);" in html
    assert "const liveAsk = parseFloat(metrics.our_best_ask || 0);" in html
    assert "let liveMid = parseFloat" in html
    assert "if (!(liveMid > 0) && liveBid > 0 && liveAsk > liveBid)" in html
    assert "liveMid = (liveBid + liveAsk) / 2;" in html
    assert "metrics.your_spread_bps = ((liveAsk - liveBid) / liveMid) * 10000;" in html


def test_status_risk_restores_stopped_dashboard_position_without_waiting_for_bot_sse():
    """The five-second status poll must keep stopped-session position visible."""
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the bounded GUI position test")

    html = GUI.read_text(encoding="utf-8", errors="replace")
    helper_source = (
        "function mergeStatusRiskIntoDashboard"
        + html.split("function mergeStatusRiskIntoDashboard", 1)[1].split(
            "function syncCommandCentreFromStatus", 1
        )[0]
    )
    status = {
        "pricing": {"mid": "0.00006521353940966367"},
        "risk": {
            "net_position_cat": "-188825.894",
            "max_position_xch": "63.3",
            "pool_depth_ratio": "0.0214792263381394",
        },
    }
    dashboard = {
        "performance": {},
        "market_health": {"metrics": {}},
    }
    script = (
        helper_source
        + "\nconst status = JSON.parse(process.argv[1]);"
        + "\nconst dashboard = JSON.parse(process.argv[2]);"
        + "\nconsole.log(JSON.stringify(mergeStatusRiskIntoDashboard(status, dashboard)));"
    )

    completed = subprocess.run(
        [node, "-e", script, json.dumps(status), json.dumps(dashboard)],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    merged = json.loads(completed.stdout)

    assert merged["performance"]["net_position"] == "-188825.894"
    assert merged["market_health"]["metrics"]["net_position_cat"] == "-188825.894"
    assert round(float(merged["market_health"]["metrics"]["position_pct"]), 6) == round(
        19.45340423370296, 6
    )


def test_status_placeholder_zeroes_do_not_erase_verified_wallet_balances():
    """A read-only status poll must not replace a wallet-verified snapshot."""
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node.js is required for the bounded GUI balance test")

    html = GUI.read_text(encoding="utf-8", errors="replace")
    helper_source = (
        "function _walletBalanceNumber"
        + html.split("function _walletBalanceNumber", 1)[1].split(
            "function getCatMetaByAssetId", 1
        )[0]
    )
    asset_id = "b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105"
    verified = {
        "xch": {"spendable": "70.141600429913", "total": "135.568288128495"},
        "cat": {"spendable": "391364.944", "total": "857450.514"},
    }
    status_placeholder = {
        "xch": {"spendable": 0, "total": 0},
        "cat": {"spendable": 0, "total": 0},
    }
    script = (
        f"var currentCAT = {{asset_id: {json.dumps(asset_id)}}};"
        + "\nvar bot_state = {current_cat: currentCAT};"
        + "\nvar _lastVerifiedWalletBalances = {asset_id: '', balances: null, live: {xch: false, cat: false}};"
        + "\n"
        + helper_source
        + f"\nmergeVerifiedWalletBalances({json.dumps(verified)}, {json.dumps(asset_id)});"
        + "\nconst merged = mergeVerifiedWalletBalances("
        + f"{json.dumps(status_placeholder)}, {json.dumps(asset_id)}, "
        + "{preserveVerifiedOnZero: true});"
        + "\nconsole.log(JSON.stringify(merged));"
    )

    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    merged = json.loads(completed.stdout)

    assert merged["xch"]["spendable"] == 70.141600429913
    assert merged["xch"]["total"] == 135.568288128495
    assert merged["cat"]["spendable"] == 391364.944
    assert merged["cat"]["total"] == 857450.514
