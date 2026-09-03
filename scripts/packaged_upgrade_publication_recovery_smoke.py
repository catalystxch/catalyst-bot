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


def _seed_upgrade_interrupted_claims(data_dir: Path) -> tuple[object, str, str]:
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
    asset_id = "0" * 64

    def seed_claim(label: str, epoch: str) -> dict:
        trade_id = hashlib.sha256(f"packaged-upgrade-{label}".encode()).hexdigest()
        offer_text = f"offer1packaged-upgrade-{label}"
        fingerprint = hashlib.sha256(offer_text.encode("utf-8")).hexdigest()
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
            publication_id=f"packaged-upgrade-{label}",
            idempotency_key=f"mainnet:{fingerprint}:{epoch}",
            network="mainnet",
            offer_fingerprint=fingerprint,
            publication_epoch=epoch,
            publisher="dexie",
            payload_json={"offer_ref": trade_id},
            queued_at=queued_at,
        )
        claim = database.claim_publication_outbox(
            publisher="dexie",
            owner_run_id=f"upgrade-interrupted-owner-{label}",
            claim_token=f"upgrade-interrupted-claim-{label}",
            claimed_at=claimed_at,
            claim_expires_at=expires_at,
        )
        if not isinstance(claim, dict):
            raise SmokeFailure("packaged upgrade publication claim was not seeded")
        return claim

    undispatched = seed_claim("undispatched", "packaged-upgrade-undispatched")
    if (
        undispatched.get("dispatch_started_at") is not None
        or undispatched.get("request_sha256") is not None
    ):
        raise SmokeFailure("packaged upgrade claim was not seeded before dispatch")

    ambiguous = seed_claim("ambiguous", "packaged-upgrade-ambiguous")
    request_sha256 = hashlib.sha256(b"packaged-upgrade-request").hexdigest()
    dispatched = database.mark_publication_dispatch_started(
        publication_id=ambiguous["publication_id"],
        owner_run_id=ambiguous["claim_owner_run_id"],
        claim_token=ambiguous["claim_token"],
        claim_generation=ambiguous["claim_generation"],
        expected_row_version=ambiguous["row_version"],
        request_sha256=request_sha256,
        dispatched_at=claimed_at,
    )
    if not isinstance(dispatched, dict):
        raise SmokeFailure("packaged upgrade dispatch was not seeded")
    unresolved = database.unresolve_publication_outbox(
        publication_id=dispatched["publication_id"],
        owner_run_id=dispatched["claim_owner_run_id"],
        claim_token=dispatched["claim_token"],
        claim_generation=dispatched["claim_generation"],
        expected_row_version=dispatched["row_version"],
        error_json={
            "code": "AMBIGUOUS_TRANSPORT_FAILURE",
            "provider": "dexie",
            "request_sha256": request_sha256,
        },
        unresolved_at=claimed_at,
    )
    if not isinstance(unresolved, dict) or unresolved.get("state") != "unresolved":
        raise SmokeFailure("packaged upgrade ambiguity was not seeded")
    database.close_connection()
    return (
        database,
        str(undispatched["publication_id"]),
        str(unresolved["publication_id"]),
    )


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
        database, undispatched_id, ambiguous_id = _seed_upgrade_interrupted_claims(
            data_dir
        )

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
        environment["DEXIE_API_BASE"] = f"http://127.0.0.1:{_free_port()}"
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
                recovered = database.get_publication_outbox(undispatched_id)
                suppressed = database.get_publication_outbox(ambiguous_id)
                snapshot = database.get_stability_startup_recovery_snapshot()
                if recovered is None or recovered.get("state") != "retryable":
                    raise SmokeFailure("packaged upgrade claim was not made retryable")
                if recovered.get("claim_owner_run_id") is not None:
                    raise SmokeFailure(
                        "packaged upgrade claim retained stale authority"
                    )
                if suppressed is None or suppressed.get("state") != "suppressed":
                    raise SmokeFailure(
                        "packaged upgrade ambiguous dispatch was not suppressed"
                    )
                if suppressed.get("claim_owner_run_id") is not None:
                    raise SmokeFailure(
                        "packaged upgrade suppressed dispatch retained stale authority"
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

    print("Packaged upgrade publication recovery smoke PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    return run_smoke(args.exe.resolve(), args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
