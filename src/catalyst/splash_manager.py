"""Queue and broadcast offers to the Splash P2P peer mesh for Chia offers

Splash is Dexie's peer-to-peer network — every connected peer receives
every offer, so broadcasting here widens fill opportunities alongside
direct Dexie posting. This module talks to the locally-running Splash
binary's HTTP submission endpoint and applies the same fingerprint-based
deduplication and queue-flush-retry pattern used by dexie_manager.

Key responsibilities:
    - Queue outbound offers keyed by a stable content fingerprint
    - Flush the queue to the local Splash submit URL with retries
    - Deduplicate repeats so the peer mesh isn't spammed
    - Log success/failure into the event stream for observability

Runs in addition to Dexie posting, not instead of it. Requires the
Splash binary (managed by splash_node.py) to be running locally.
"""

import time
import hashlib
import requests
import threading
import uuid
from typing import Dict, List, Optional

from config import cfg
from database import (
    claim_publication_outbox,
    complete_publication_outbox,
    enqueue_publication_for_trade,
    log_event,
    mark_publication_dispatch_started,
    retry_publication_outbox,
    unresolve_publication_outbox,
)
from publication_outbox import (
    PublicationState,
    canonical_publication_request_contract,
    classify_provider_result,
    provider_response_sha256,
    publication_request_sha256,
    retry_timestamp,
)


class SplashManager:
    """Manages broadcasting offers to the Splash P2P network.

    Key responsibilities:
    - Queue offers for broadcasting (same interface as DexieManager)
    - Post to Splash's local HTTP endpoint with retries
    - Track posted fingerprints (prevent duplicate broadcasts)
    - Report posting statistics for the GUI
    """

    def __init__(self):
        # Post queue (cleared after each flush)
        self._queue: List[Dict] = []

        # Fingerprints of already-posted offers (sha256 of bech32 string)
        self._posted_fingerprints: set = set()

        # Lock for thread safety
        self._lock = threading.Lock()
        self._durable_outbox_owner: Optional[str] = None
        self._durable_now_provider = None
        self._durable_lease_expires_provider = None
        self._durable_network: Optional[str] = None
        # A slow local relay must not monopolize the trading loop.  Durable
        # claims not reached within this budget remain queued for a later
        # cycle, preserving exact-once publication bookkeeping.
        # Dexie and Splash drain sequentially in the same cycle, so each gets
        # half of the 60-second step SLA with a small scheduling margin.
        self._durable_flush_budget_seconds: float = 25.0

        # Stats
        self._total_posted: int = 0
        self._total_failed: int = 0
        self._total_skipped: int = 0

        # Track whether Splash is reachable (avoid spamming logs)
        self._splash_healthy: bool = True
        self._consecutive_failures: int = 0
        self._max_silent_failures: int = 5  # Only log every Nth failure

    # -------------------------------------------------------------------
    # Queue management
    # -------------------------------------------------------------------

    def enable_durable_outbox(
        self,
        *,
        owner_run_id: str,
        now_provider,
        lease_expires_provider,
        network: Optional[str] = None,
    ) -> None:
        """Route subsequent flushes through committed publication claims."""

        if type(owner_run_id) is not str or not owner_run_id.strip():
            raise ValueError("owner_run_id must be exact non-empty text")
        if not callable(now_provider) or not callable(lease_expires_provider):
            raise TypeError("durable outbox timestamp providers must be callable")
        if network is not None and (type(network) is not str or not network):
            raise ValueError("network must be exact non-empty text")
        self._durable_outbox_owner = owner_run_id.strip()
        self._durable_now_provider = now_provider
        self._durable_lease_expires_provider = lease_expires_provider
        self._durable_network = network
        with self._lock:
            pending = list(self._queue)
            self._queue = []
        for item in pending:
            enqueue_publication_for_trade(
                trade_id=item["trade_id"],
                offer_fingerprint=self._fingerprint(item["offer"]),
                publisher="splash",
                force=item.get("force", False),
                network=network,
                queued_at=now_provider(),
            )

    def _flush_durable_outbox(self, flush_all: bool) -> Dict:
        limit = 500 if flush_all else int(getattr(cfg, "MAX_POSTS_PER_LOOP", 30))
        posted = failed = skipped = requeued = 0
        budget_exhausted = False
        flush_started = time.monotonic()
        for index in range(max(1, limit)):
            if not flush_all and index > 0:
                elapsed = time.monotonic() - flush_started
                budget = max(1.0, float(self._durable_flush_budget_seconds))
                request_timeout = max(
                    0.0, float(getattr(cfg, "SPLASH_POST_TIMEOUT", 15))
                )
                if budget - elapsed < request_timeout:
                    budget_exhausted = True
                    log_event(
                        "info",
                        "splash_durable_flush_budget",
                        "Splash durable publication reached its cycle time budget; "
                        "remaining claims stay queued for the next cycle",
                        data={
                            "elapsed_seconds": round(elapsed, 3),
                            "budget_seconds": budget,
                            "posted": posted,
                            "failed": failed,
                        },
                    )
                    break
            observed_at = self._durable_now_provider()
            claim = claim_publication_outbox(
                publisher="splash",
                owner_run_id=self._durable_outbox_owner,
                claim_token=uuid.uuid4().hex,
                claimed_at=observed_at,
                claim_expires_at=self._durable_lease_expires_provider(observed_at),
            )
            if claim is None:
                break
            offer_bech32 = claim.get("offer_bech32")
            trade_id = claim.get("trade_id")
            request_contract = canonical_publication_request_contract(
                publisher="splash",
                offer_bech32=offer_bech32,
                idempotency_key=claim["idempotency_key"],
                destination_url=getattr(
                    cfg, "SPLASH_SUBMIT_URL", "http://localhost:4000"
                ).rstrip("/"),
            )
            request_digest = publication_request_sha256(request_contract)
            dispatched_at = self._durable_now_provider()
            dispatched = mark_publication_dispatch_started(
                publication_id=claim["publication_id"],
                owner_run_id=claim["claim_owner_run_id"],
                claim_token=claim["claim_token"],
                claim_generation=claim["claim_generation"],
                expected_row_version=claim["row_version"],
                request_sha256=request_digest,
                dispatched_at=dispatched_at,
            )
            if dispatched is None:
                failed += 1
                continue
            result = self._post_single(
                offer_bech32,
                trade_id,
                True,
                idempotency_key=claim["idempotency_key"],
                request_contract=request_contract,
            )
            effect_completed_at = self._durable_now_provider()
            decision = classify_provider_result(
                publisher="splash",
                result=result,
                expected_idempotency_key=claim["idempotency_key"],
                expected_request_sha256=request_digest,
            )
            if decision.state is PublicationState.SUCCEEDED:
                completed = complete_publication_outbox(
                    publication_id=dispatched["publication_id"],
                    owner_run_id=dispatched["claim_owner_run_id"],
                    claim_token=dispatched["claim_token"],
                    claim_generation=dispatched["claim_generation"],
                    expected_row_version=dispatched["row_version"],
                    acknowledgement_json=decision.evidence,
                    completed_at=effect_completed_at,
                )
                if completed is not None:
                    posted += 1
                    self._total_posted += 1
                    with self._lock:
                        self._posted_fingerprints.add(self._fingerprint(offer_bech32))
                else:
                    failed += 1
            elif decision.state is PublicationState.RETRYABLE:
                retried = retry_publication_outbox(
                    publication_id=dispatched["publication_id"],
                    owner_run_id=dispatched["claim_owner_run_id"],
                    claim_token=dispatched["claim_token"],
                    claim_generation=dispatched["claim_generation"],
                    expected_row_version=dispatched["row_version"],
                    error_json=decision.evidence,
                    retry_at=retry_timestamp(
                        effect_completed_at, claim["attempt_count"]
                    ),
                    updated_at=effect_completed_at,
                )
                failed += 1
                self._total_failed += 1
                if retried is not None:
                    requeued += 1
            else:
                unresolve_publication_outbox(
                    publication_id=dispatched["publication_id"],
                    owner_run_id=dispatched["claim_owner_run_id"],
                    claim_token=dispatched["claim_token"],
                    claim_generation=dispatched["claim_generation"],
                    expected_row_version=dispatched["row_version"],
                    error_json=decision.evidence,
                    unresolved_at=effect_completed_at,
                )
                failed += 1
                self._total_failed += 1
            if trade_id:
                with self._lock:
                    self._queue = [
                        item for item in self._queue if item.get("trade_id") != trade_id
                    ]
        return {
            "posted": posted,
            "failed": failed,
            "skipped": skipped,
            "requeued": requeued,
            "budget_exhausted": budget_exhausted,
        }

    def queue_post(self, offer_bech32: str, trade_id: str = None, force: bool = False):
        """Queue an offer for broadcasting to Splash.

        Args:
            offer_bech32: The offer1... bech32 string
            trade_id: Chia trade_id (for logging/tracking)
            force: If True, post even if fingerprint matches
        """
        if not offer_bech32 or not isinstance(offer_bech32, str):
            return
        offer_text = offer_bech32.strip()
        if self._durable_outbox_owner is not None:
            if type(trade_id) is not str or not trade_id:
                raise ValueError("durable publication requires a trade reference")
            enqueue_publication_for_trade(
                trade_id=trade_id,
                offer_fingerprint=self._fingerprint(offer_text),
                publisher="splash",
                force=force,
                network=self._durable_network,
                queued_at=self._durable_now_provider(),
            )
            return

        with self._lock:
            self._queue.append(
                {
                    "offer": offer_text,
                    "trade_id": trade_id,
                    "force": force,
                }
            )

    def purge_trade_ids(self, trade_ids):
        """Remove queued entries for cancelled trade IDs."""
        if not trade_ids:
            return
        ids = set(trade_ids)
        with self._lock:
            before = len(self._queue)
            self._queue = [
                item for item in self._queue if item.get("trade_id") not in ids
            ]
            removed = before - len(self._queue)
        if removed:
            log_event(
                "debug",
                "splash_queue_purged",
                f"Removed {removed} cancelled offer(s) from Splash queue",
            )

    def flush_queue(self, flush_all: bool = False) -> Dict:
        """Submit queued offers to the local Splash node.

        Returns summary: {posted: N, failed: N, skipped: N}
        """
        if not getattr(cfg, "SPLASH_ENABLED", False):
            return {"posted": 0, "failed": 0, "skipped": 0, "disabled": True}
        if self._durable_outbox_owner is not None:
            return self._flush_durable_outbox(flush_all)

        # Grab items from queue
        with self._lock:
            if flush_all:
                batch = list(self._queue)
                self._queue = []
            else:
                max_posts = getattr(cfg, "MAX_POSTS_PER_LOOP", 30)
                batch = list(self._queue[:max_posts])
                self._queue = self._queue[max_posts:]

        if not batch:
            return {"posted": 0, "failed": 0, "skipped": 0}

        posted = 0
        failed = 0
        skipped = 0
        failed_items = []
        _MAX_SPLASH_RETRIES = 3

        # Cap per loop (same pattern as Dexie — don't block the main loop)
        def _process_one(item):
            offer_bech32 = item["offer"]
            trade_id = item.get("trade_id")
            force = item.get("force", False)
            return self._post_single(offer_bech32, trade_id, force)

        def _handle_result(result, item):
            nonlocal posted, failed, skipped
            # Updates to instance counters and failed_items list happen under
            # the lock so ThreadPoolExecutor workers don't clobber each other.
            with self._lock:
                if result.get("skipped"):
                    skipped += 1
                    self._total_skipped += 1
                elif result.get("success"):
                    posted += 1
                    self._total_posted += 1
                else:
                    failed += 1
                    self._total_failed += 1
                    retries = item.get("_splash_retries", 0)
                    if retries < _MAX_SPLASH_RETRIES:
                        item["_splash_retries"] = retries + 1
                        failed_items.append(item)

        if len(batch) > 10:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            workers = min(8, len(batch))
            log_event(
                "info",
                "splash_flush_parallel",
                f"Parallel Splash flush: {len(batch)} offers with {workers} workers",
            )
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_process_one, item): item for item in batch}
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        result = future.result()
                        _handle_result(result, item)
                    except Exception as e:
                        log_event(
                            "warning",
                            "splash_parallel_error",
                            f"Parallel Splash post failed: {e}",
                        )
                        with self._lock:
                            failed += 1
                            self._total_failed += 1
                            retries = item.get("_splash_retries", 0)
                            if retries < _MAX_SPLASH_RETRIES:
                                item["_splash_retries"] = retries + 1
                                failed_items.append(item)
        else:
            for item in batch:
                result = _process_one(item)
                _handle_result(result, item)

        # Re-queue failed items for retry on the next cycle
        if failed_items:
            with self._lock:
                self._queue.extend(failed_items)
            log_event(
                "info",
                "splash_requeue",
                f"Re-queued {len(failed_items)} failed Splash posts for next cycle",
            )

        summary = {
            "posted": posted,
            "failed": failed,
            "skipped": skipped,
            "requeued": len(failed_items),
        }
        if posted > 0:
            log_event(
                "info",
                "splash_flush",
                f"Submitted {posted} queued offers to the local Splash node "
                f"({skipped} skipped, {failed} failed); "
                "peer relay depends on daemon peers",
            )
        return summary

    # -------------------------------------------------------------------
    # Core posting
    # -------------------------------------------------------------------

    def _post_single(
        self,
        offer_bech32: str,
        trade_id: str = None,
        force: bool = False,
        idempotency_key: str = None,
        request_contract: Dict = None,
    ) -> Dict:
        """Post a single offer to Splash with retries.

        Returns result dict with success/skipped/error fields.
        """
        # Validate bech32 format
        if not offer_bech32.lower().startswith("offer1"):
            return {"success": False, "error": "not_bech32_offer1"}

        # Fingerprint check (prevent duplicate broadcasts) — lock-protected
        # to prevent race condition when flush_queue uses ThreadPoolExecutor
        fp = self._fingerprint(offer_bech32)
        with self._lock:
            if not force and fp in self._posted_fingerprints:
                return {"success": True, "skipped": True, "reason": "already_broadcast"}

        # Splash's offer submission endpoint
        # Splash expects POST to the root of the submission URL
        submit_url = getattr(cfg, "SPLASH_SUBMIT_URL", "http://localhost:4000")
        url = submit_url.rstrip("/")
        payload = {"offer": offer_bech32}
        timeout = getattr(cfg, "SPLASH_POST_TIMEOUT", 15)
        retries = getattr(cfg, "SPLASH_POST_RETRIES", 2)
        retry_sleep = getattr(cfg, "SPLASH_POST_RETRY_SLEEP", 1.5)

        if idempotency_key is not None:
            if request_contract is None:
                request_contract = canonical_publication_request_contract(
                    publisher="splash",
                    offer_bech32=offer_bech32,
                    idempotency_key=idempotency_key,
                    destination_url=url,
                )
            request_digest = publication_request_sha256(request_contract)
            if (
                request_contract["publisher"] != "splash"
                or request_contract["body"]["offer"] != offer_bech32
                or request_contract["headers"]["idempotency-key"] != idempotency_key
            ):
                raise ValueError("durable Splash request contract does not match claim")
            url = request_contract["destination_url"]
            payload = dict(request_contract["body"])
            headers = dict(request_contract["headers"])
            try:
                r = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
                response_digest = provider_response_sha256(bytes(r.content))
                if 200 <= r.status_code < 300:
                    try:
                        data = r.json()
                    except Exception:
                        data = None
                    return {
                        "outcome": "acknowledged",
                        "provider": "splash",
                        "request_sha256": request_digest,
                        "response_sha256": response_digest,
                        "status_code": r.status_code,
                        "provider_response_id": (
                            data.get("id") or data.get("offer_id")
                            if type(data) is dict
                            else None
                        ),
                        "echoed_idempotency_key": (
                            data.get("idempotency_key")
                            if type(data) is dict
                            else r.headers.get("idempotency-key")
                        ),
                    }
                if r.status_code == 429 or (
                    r.status_code == 400
                    and "invalid offer" in str(r.text or "").lower()
                ):
                    return {
                        "outcome": "no_effect",
                        "acceptance": False,
                        "provider": "splash",
                        "request_sha256": request_digest,
                        "response_sha256": response_digest,
                        "status_code": r.status_code,
                        "reason_code": (
                            "RATE_LIMITED" if r.status_code == 429 else "INVALID_OFFER"
                        ),
                    }
                return {
                    "outcome": "ambiguous",
                    "provider": "splash",
                    "request_sha256": request_digest,
                    "reason_code": "UNPROVEN_PROVIDER_RESPONSE",
                }
            except (requests.Timeout, requests.ConnectionError):
                return {
                    "outcome": "ambiguous",
                    "provider": "splash",
                    "request_sha256": request_digest,
                    "reason_code": "TRANSPORT_OUTCOME_UNKNOWN",
                }
            except Exception:
                return {
                    "outcome": "ambiguous",
                    "provider": "splash",
                    "request_sha256": request_digest,
                    "reason_code": "MALFORMED_PROVIDER_RESPONSE",
                }

        last_err = None
        for attempt in range(retries + 1):
            try:
                r = requests.post(
                    url,
                    json=payload,
                    headers={
                        "content-type": "application/json",
                        **(
                            {"idempotency-key": idempotency_key}
                            if idempotency_key
                            else {}
                        ),
                    },
                    timeout=timeout,
                )

                if 200 <= r.status_code < 300:
                    # Mark as posted + reset health tracking — lock-protected.
                    recovered = False
                    with self._lock:
                        self._posted_fingerprints.add(fp)
                        if not self._splash_healthy:
                            self._splash_healthy = True
                            self._consecutive_failures = 0
                            recovered = True
                    if recovered:
                        log_event(
                            "info", "splash_recovered", "Splash connection restored"
                        )

                    tid_short = trade_id[:16] + "..." if trade_id else "unknown"
                    log_event(
                        "debug",
                        "splash_posted",
                        f"Submitted to local Splash node OK (trade: {tid_short})",
                    )

                    provider_response_id = None
                    try:
                        response_data = r.json()
                    except Exception:
                        response_data = None
                    if isinstance(response_data, dict):
                        provider_response_id = (
                            response_data.get("id")
                            or response_data.get("offer_id")
                            or response_data.get("idempotency_key")
                        )
                    if provider_response_id is None:
                        provider_response_id = r.headers.get("idempotency-key")
                    return {
                        "success": True,
                        "trade_id": trade_id,
                        "provider_response_id": provider_response_id,
                    }

                last_err = f"HTTP {r.status_code}: {r.text[:200]}"

            except requests.Timeout:
                last_err = f"Timeout after {timeout}s"
            except requests.ConnectionError:
                last_err = "Connection refused — is Splash running?"
            except Exception as e:
                last_err = f"Unexpected error: {e}"

            # Retry with sleep
            if attempt < retries:
                time.sleep(retry_sleep)

        # All retries failed — bump counter and decide if we should log.
        with self._lock:
            self._consecutive_failures += 1
            cf = self._consecutive_failures
            should_log = (cf <= 3) or (cf % self._max_silent_failures == 0)
            should_mark_unhealthy = self._splash_healthy and cf >= 3
            if should_mark_unhealthy:
                self._splash_healthy = False

        if should_log:
            log_event(
                "warning",
                "splash_post_failed",
                f"Failed to broadcast to Splash (attempt {cf}): {last_err}",
            )
        if should_mark_unhealthy:
            log_event(
                "warning",
                "splash_unhealthy",
                "Splash appears offline — will keep trying silently",
            )

        return {"success": False, "error": last_err}

    # -------------------------------------------------------------------
    # Repost active offers (recovery after outage)
    # -------------------------------------------------------------------

    def repost_active_offers(self, active_offers: List[Dict]):
        """Re-broadcast all active offers to Splash.

        Used after startup or Splash reconnect.

        Args:
            active_offers: List of offer dicts with 'trade_id' and 'offer_bech32'
        """
        count = 0
        for offer in active_offers:
            bech32 = offer.get("offer_bech32", "")
            trade_id = offer.get("trade_id", "")

            if bech32 and trade_id:
                self.queue_post(bech32, trade_id, force=True)
                count += 1

        if count > 0:
            log_event(
                "info",
                "splash_repost_queued",
                f"Queued {count} active offers for Splash rebroadcast",
            )

    # -------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------

    def check_health(self) -> Dict:
        """Quick health check — can we reach Splash?

        Returns: {healthy: bool, url: str, error: str|None}
        """
        submit_url = getattr(cfg, "SPLASH_SUBMIT_URL", "http://localhost:4000")
        if not getattr(cfg, "SPLASH_ENABLED", False):
            return {
                "healthy": False,
                "url": submit_url,
                "error": "Splash disabled",
            }
        try:
            # Just try connecting — Splash may not have a health endpoint,
            # so we just check if the port is open with a short timeout
            requests.get(submit_url, timeout=3)
            return {"healthy": True, "url": submit_url, "error": None}
        except requests.ConnectionError:
            return {
                "healthy": False,
                "url": submit_url,
                "error": "Connection refused — Splash not running",
            }
        except Exception as e:
            return {"healthy": False, "url": submit_url, "error": str(e)}

    # -------------------------------------------------------------------
    # Stats & housekeeping
    # -------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Get broadcasting statistics (thread-safe snapshot)."""
        with self._lock:
            return {
                "total_posted": self._total_posted,
                "total_failed": self._total_failed,
                "total_skipped": self._total_skipped,
                "queue_size": len(self._queue),
                "fingerprints_cached": len(self._posted_fingerprints),
                "healthy": self._splash_healthy,
                "consecutive_failures": self._consecutive_failures,
            }

    def reset_session_stats(self):
        """Reset per-run broadcast stats and dedup state."""
        with self._lock:
            self._queue = []
            self._posted_fingerprints.clear()
            self._total_posted = 0
            self._total_failed = 0
            self._total_skipped = 0
            self._splash_healthy = True
            self._consecutive_failures = 0

    def prune_fingerprints(self):
        """Periodically clear old fingerprints to prevent unbounded growth."""
        max_fps = 400
        if len(self._posted_fingerprints) > max_fps:
            old_len = len(self._posted_fingerprints)
            self._posted_fingerprints.clear()
            log_event(
                "debug",
                "splash_fingerprints_cleared",
                f"Cleared {old_len} fingerprints (exceeded {max_fps} cap)",
            )

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _fingerprint(offer_bech32: str) -> str:
        """SHA256 fingerprint of offer bech32 string."""
        return hashlib.sha256(offer_bech32.strip().encode("utf-8")).hexdigest()
