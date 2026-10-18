# Stopped Mixed Offer Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely reconcile one filled and five naturally expired Harvestr campaign offers while the bot and trading authority remain stopped.

**Architecture:** A narrow restricted-startup authority proves the exact blocked campaign and adopts a dead owner's lease. A shared terminal-proof service previews and re-proves the complete cohort at commit, then applies existing Task 9 reconciliation with durable post-fill hooks deferred. A separate normal-authority drain handles those hooks after recovery.

**Tech Stack:** Python 3.12, Flask, SQLite WAL, Sage RPC, PyWebView/vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-stopped-mixed-offer-recovery-design.md`

## Global Constraints

- This operation is database-only: no wallet mutation, fee, offer creation/cancellation, marketplace publication, notification, BoostManager, SweepCoordinator or Splash dispatch.
- Campaign must be active but elapsed, bot stopped, Sage synced to exact network/fingerprint/wallet/asset, with zero live/fillable offers and zero pending transactions.
- For restricted startup, require the exact `REGISTRY_BLOCKED` generation and `reconcile:<intent_id>` blockers for the campaign. The normal stopped-bot view may also operate with an allowed latch, subject to the same wallet, campaign and proof checks. Deny an extra blocker or unrelated unresolved creation in either mode.
- Preview is read-only. Commit re-proves the entire cohort, exact owner/acquisition epoch, current heartbeat version, immutable digest and classifications before the first terminal write.
- Keep campaign status, budgets and fee ledger unchanged. Keep the bot stopped and all ordinary mutation guards closed.
- A partial commit retains the latch and is retried with fresh proof; already-terminal roots are displayed but never reapplied.
- Keep the PR draft and require independent review, packaged smoke and original-profile action-time confirmation before any Harvestr commit.

## Review Focus

- An `unknown` root without its exact journal or conclusive fill evidence must refuse preview (Task 2 test).
- A heartbeat version that advances during preview must be accepted only if the same owner and acquisition epoch are freshly fenced at commit (Task 1 and 3 tests).
- A Sage book or wallet identity change between preview and commit must refuse all new writes (Task 3 test).
- A crash after one fill or expiry must resume from durable proof without repeating its accounting or hook records (Task 3 test).
- A restricted recovery must leave each post-fill callback pending; a later normal-authority drain must acknowledge each effect exactly once or durably refuse it (Task 4 test).

---

### Task 1: Restricted lease and recovery authority

**Files:** Modify root `desktop_app.py`, `src/catalyst/api_server.py`, `src/catalyst/database.py`, `src/catalyst/runtime_recovery.py`, `src/catalyst/mutation_gate.py`; test `tests/test_mutation_gate.py` and a new `tests/test_mixed_terminal_recovery_startup.py`.

**Interfaces:** Produce `preflight_registry_terminal_restricted_startup()` and `activate_registry_terminal_restricted_startup(authorization)` analogous to the existing refresh-abort path, with a typed authority record binding campaign/revision, network/wallet/asset, run ID/PID/host, acquisition epoch, latch generation/blockers and book digest. Produce a database compare-and-set lease adoption restricted to a proven dead prior owner. The service in Task 2 consumes this record.

- [ ] **Step 1: Add failing tests.** Exact elapsed campaign, two stable complete Sage snapshots and dead prior owner allow restricted adoption; active/uncertain owner, changed blocker, changed identity/book, or extra campaign deny it. Exercise the actual root `desktop_app.py` startup dispatcher on `REGISTRY_BLOCKED` and prove it reaches only heartbeat and restricted view. Direct normal mutation routes and existing refresh-abort fee approval/cancellation routes and bridge calls remain denied. Test the allowed-latch normal stopped-bot path separately.
- [ ] **Step 2: Run** `python -m pytest tests/test_mixed_terminal_recovery_startup.py tests/test_mutation_gate.py -q`; verify new tests fail for missing authority.
- [ ] **Step 3: Implement** the narrow preflight, dead-owner compare-and-set, root desktop startup dispatch and post-acquisition reproof. Release only the newly owned lease on failure. Fence run ID/PID/host and acquisition epoch while permitting heartbeat version advancement when its current value is read and compared at commit.
- [ ] **Step 4: Repeat Step 2 and verify the new tests pass.**
- [ ] **Step 5: Commit** the restricted authority and tests.

### Task 2: Complete mixed terminal preview

**Files:** Create `src/catalyst/mixed_terminal_recovery.py`; modify `src/catalyst/blueprints/bootstrap.py`, `src/catalyst/app_bridge.py`; test `tests/test_bootstrap_api.py`, `tests/test_bootstrap_mutation_gate.py` and new `tests/test_mixed_terminal_recovery.py`.

**Interfaces:** Produce `preview_terminal_offers(campaign_id: str, revision: int, authority: object) -> dict` returning the sorted intent/trade/side/tier/classification/proof-digest vector plus authority binding, latch generation and Sage live/pending counts. The preview is read-only. HTTP and bridge entrypoints call the same service and scoped guard.

- [ ] **Step 1: Add failing tests.** Prove the exact one-fill/five-expiry cohort including the journal-matched `unknown` fill under both the restricted `REGISTRY_BLOCKED` mode and the allowed-latch normal stopped-bot mode. Reject unsupported unknown, duplicate/missing trade ID, more than 256 roots, wrong asset/side/tier/revision, parent/child lineage, unrelated root, unresolved creation, live offer, pending transaction and changed first/second snapshot.
- [ ] **Step 2: Run** `python -m pytest tests/test_mixed_terminal_recovery.py tests/test_bootstrap_api.py tests/test_bootstrap_mutation_gate.py -q`; verify missing preview fails.
- [ ] **Step 3: Implement** complete cohort collection and two-snapshot classification through `classify_terminal_evidence`. Canonicalize immutable proof fields and authority bindings for the digest; exclude observation time. Make HTTP and direct bridge calls share the restricted proof guard without opening generic mutations.
- [ ] **Step 4: Repeat Step 2 and verify green; assert preview makes zero DB writes and wallet mutations.**
- [ ] **Step 5: Commit** preview and tests.

### Task 3: Fenced commit and restartable Task 9 reconciliation

**Files:** Modify `src/catalyst/mixed_terminal_recovery.py`, `src/catalyst/offer_reconciliation.py`, `src/catalyst/database.py`, `src/catalyst/blueprints/bootstrap.py`, `src/catalyst/app_bridge.py`; test `tests/test_mixed_terminal_recovery.py`, `tests/test_offer_reconciliation.py`, `tests/test_bootstrap_mutation_gate.py`.

**Interfaces:** Produce `commit_terminal_offers(reviewed: dict, authority: object) -> dict`, receiving only exact campaign/revision, latch generation and sorted vector/digest. Add explicit `defer_post_fill_hooks: bool = False` to `reconcile_offer(...)`, preserving normal callers. Return fill/expiry/already-terminal/pending-hook/remaining-blocker counts and a partial-commit marker.

- [ ] **Step 1: Add failing tests.** Fresh Sage proof and compare-and-set reject changed owner/epoch/heartbeat fence, identity, book, campaign, row, journal, latch or class before applying new roots. A stable advancing heartbeat passes. A fill applies once before expiries and closes its `UNKNOWN` journal; a crash/retry does not double count it or replay an expiry. Partial failure keeps latch tripped; only the existing resolver can clear all exact blockers.
- [ ] **Step 2: Run** `python -m pytest tests/test_mixed_terminal_recovery.py tests/test_offer_reconciliation.py -q`; verify new assertions fail.
- [ ] **Step 3: Implement** fresh proof under campaign and bot lifecycle locks, final lease heartbeat CAS, fill-first Task 9 calls with hook deferral, and restartable already-terminal checks. Do not change campaign/fee state or add a generic mutation permit.
- [ ] **Step 4: Repeat Step 2 and verify green; inspect exact DB and Sage projections after fault injection.**
- [ ] **Step 5: Commit** commit path and tests.

### Task 4: Durable deferred hooks and normal-authority drain

**Files:** Modify `src/catalyst/offer_reconciliation.py`, `src/catalyst/database.py` and the existing normal post-fill drain entrypoint; test `tests/test_offer_reconciliation.py` and new `tests/test_mixed_terminal_hooks.py`.

**Interfaces:** The recovery fill records pending hook outbox rows without claims or callback invocation. A separate `drain_deferred_terminal_hooks(...)` normal-authority entrypoint reuses existing claim/ack/failure machinery and is never callable under the restricted permit.

- [ ] **Step 1: Add failing integration tests with real callbacks.** Recovery leaves all hooks pending, no callback/notification/BoostManager/SweepCoordinator/Splash effect occurs; normal authority delivers and acknowledges each once, while an unavailable effect is durably refused. Crash/retry cannot duplicate a claim or acknowledgement.
- [ ] **Step 2: Run** `python -m pytest tests/test_mixed_terminal_hooks.py tests/test_offer_reconciliation.py -q`; verify failures.
- [ ] **Step 3: Implement** explicit recovery hook deferral and separate normal-authority drain. Keep existing all-filled and all-expired behavior unchanged.
- [ ] **Step 4: Repeat Step 2 and verify green; audit outbox states before and after drain.**
- [ ] **Step 5: Commit** hook handling and tests.

### Task 5: Native review, package verification and Harvestr handoff

**Files:** Modify `bot_gui.html`, `src/catalyst/api_server.py`, `catalyst.spec`; create `terminal_offer_recovery.html` and `tests/test_mixed_terminal_recovery_ui.py`; update the draft PR description and local verification ledger.

**Interfaces:** Restricted and normal stopped-bot views expose `Verify Terminal Offers`: preview exact cohort, show per-root result and wallet/latch binding, require an explicit database-only confirmation, then show terminal counts, pending hooks, blockers, Sage counts and campaign/bot state.

- [ ] **Step 1: Add failing UI tests.** Root desktop startup serves the actual restricted HTML when `REGISTRY_BLOCKED`; its preview/commit control is reachable through the packaged native window. The normal stopped-bot dashboard also exposes it with an allowed latch. Button disabled until a complete preview; confirmation includes every outcome and no trading promise; partial failure stays in restricted view and requires a fresh preview. Existing completed/expired controls retain behavior.
- [ ] **Step 2: Run** `python -m pytest tests/test_bootstrap_ui_contract.py -q` and relevant Chromium UI tests; verify new assertions fail.
- [ ] **Step 3: Implement** restricted page and normal-view presentation, route allowlist, PyInstaller asset inclusion and native startup wiring to the scoped preview/commit service; escape server data and use event delegation. Keep existing refresh-abort fee approval and cancellation controls inaccessible from this recovery mode.
- [ ] **Step 4: Run** focused and full backend/frontend suites, Ruff, clean package and Defender; obtain independent review and run isolated packaged smoke on a disposable online copy. Resolve all material findings and repeat exact-head gates.
- [ ] **Step 5: Before original-profile use, recheck source/hash/PID, Sage identity/balances/full offers/pending, campaign, fee ledger, lease/latch and GUI. Obtain required Windows action-time confirmation, then verify native Harvestr outcome and keep the PR draft.**

## Execution boundary

The plan ends with a reviewed draft PR, isolated package evidence and an explicitly approved original-profile proof-only recovery. It does not authorize starting the bot, draining hooks under restricted authority, creating/cancelling offers, or publishing the general release.
