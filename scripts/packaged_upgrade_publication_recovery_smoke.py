#!/usr/bin/env python3
"""Prove a packaged app recovers an upgrade-interrupted publication claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from packaged_api_smoke import (
    SmokeFailure,
    _build_env,
    _free_port,
    _start_mock_sage,
    _terminate_process,
    _wait_for_health,
)


_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "src" / "catalyst"


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _seed_undispatched_claim(data_dir: Path) -> tuple[object, str]:
    if str(_SOURCE) not in sys.path:
        sys.path.insert(0, str(_SOURCE))
    import database

    database.close_connection()
    database.DB_PATH = str(data_dir / "bot.db")
    database._db_initialized_path = ""
    database.init_database()

    now = datetime.now(timezone.utc)
    queued_at = _timestamp(now - timedelta(seconds=5))
    claimed_at = _timestamp(now)
    expires_at = _timestamp(now + timedelta(minutes=4))
    trade_id = hashlib.sha256(b"packaged-upgrade-trade").hexdigest()
    offer_text = "offer1packaged-upgrade-publication-recovery"
    fingerprint = hashlib.sha256(offer_text.encode("utf-8")).hexdigest()
    asset_id = "0" * 64

    if not database.add_offer(
        trade_id=trade_id,
        side="buy",
        price_xch=Decimal("0.5"),
        size_xch=Decimal("1"),
        size_cat=Decimal("2"),
        cat_asset_id=asset_id,
        tier="inner",
    ):
        raise SmokeFailure("could not seed packaged upgrade offer projection")
    if not database.update_offer_bech32(trade_id, offer_text):
        raise SmokeFailure("could not seed packaged upgrade offer bytes")
    database.enqueue_publication_outbox(
        publication_id="packaged-upgrade-publication",
        idempotency_key=f"mainnet:{fingerprint}:packaged-upgrade",
        network="mainnet",
        offer_fingerprint=fingerprint,
        publication_epoch="packaged-upgrade",
        publisher="dexie",
        payload_json={"offer_ref": trade_id},
        queued_at=queued_at,
    )
    claim = database.claim_publication_outbox(
        publisher="dexie",
        owner_run_id="upgrade-interrupted-owner",
        claim_token="upgrade-interrupted-claim",
        claimed_at=claimed_at,
        claim_expires_at=expires_at,
    )
    if (
        not isinstance(claim, dict)
        or claim.get("dispatch_started_at") is not None
        or claim.get("request_sha256") is not None
    ):
        raise SmokeFailure("packaged upgrade claim was not seeded before dispatch")
    database.close_connection()
    return database, str(claim["publication_id"])


def _read_safety(base_url: str) -> dict:
    with urllib.request.urlopen(  # nosec B310 - fixed loopback URL
        base_url + "/api/safety/status", timeout=5
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    safety = payload.get("safety") if isinstance(payload, dict) else None
    if not isinstance(safety, dict):
        raise SmokeFailure("packaged upgrade recovery returned malformed safety status")
    return safety


def run_smoke(executable: Path, timeout_seconds: int) -> int:
    if not executable.is_file():
        raise SmokeFailure(f"packaged executable not found: {executable}")

    with tempfile.TemporaryDirectory(prefix="catalyst-upgrade-recovery-") as raw_temp:
        temp_dir = Path(raw_temp)
        data_dir = temp_dir / "catalyst-data"
        data_dir.mkdir()
        database, publication_id = _seed_undispatched_claim(data_dir)

        server, thread, client_cert, client_key = _start_mock_sage(temp_dir)
        host, sage_port = server.server_address
        flask_port = _free_port()
        base_url = f"http://127.0.0.1:{flask_port}"
        local_token = "packaged-upgrade-recovery-token"
        environment = _build_env(
            base_env=os.environ.copy(),
            temp_dir=temp_dir,
            sage_rpc_url=f"https://{host}:{sage_port}",
            client_cert=client_cert,
            client_key=client_key,
            flask_port=flask_port,
            local_token=local_token,
        )
        environment["CMM_DATA_DIR"] = str(data_dir)
        environment["DEXIE_POST_ENABLED"] = "false"
        environment["SPLASH_ENABLED"] = "false"

        stdout_path = temp_dir / "catalyst-upgrade-recovery.log"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with stdout_path.open("w", encoding="utf-8", errors="replace") as output:
            process = subprocess.Popen(
                [str(executable), "--flask"],
                cwd=str(executable.parent),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            try:
                _wait_for_health(base_url, time.time() + timeout_seconds)
                safety = _read_safety(base_url)
                if safety.get("allowed") is not True:
                    raise SmokeFailure(
                        "packaged upgrade restart remained blocked: "
                        + str(safety.get("reason_code") or "unknown")
                    )

                database.close_connection()
                recovered = database.get_publication_outbox(publication_id)
                snapshot = database.get_stability_startup_recovery_snapshot()
                if recovered is None or recovered.get("state") != "retryable":
                    raise SmokeFailure("packaged upgrade claim was not made retryable")
                if recovered.get("claim_owner_run_id") is not None:
                    raise SmokeFailure(
                        "packaged upgrade claim retained stale authority"
                    )
                if snapshot["blocker_counts"]["publication_claims"] != 0:
                    raise SmokeFailure("packaged upgrade recovery retained a blocker")
            except Exception as exc:
                output.flush()
                details = stdout_path.read_text(encoding="utf-8", errors="replace")
                raise SmokeFailure(
                    f"packaged upgrade publication recovery failed: {exc}\n"
                    + details[-12000:]
                ) from exc
            finally:
                _terminate_process(process, base_url, local_token)
                database.close_connection()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    print("Packaged upgrade publication-claim recovery smoke PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    return run_smoke(args.exe.resolve(), args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
