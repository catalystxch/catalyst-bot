# Follow Fee Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind every wallet fee in a reviewed 48-hour Follow ladder to one durable cumulative 0.05 XCH ceiling, including safe shutdown after restart.

**Architecture:** A native review records one immutable wallet, configuration, offer-limit, expiry and fee consent. Every Follow offer intent carries that run ID. Fee-bearing operations obtain a fresh exact price and an atomic, append-only hold in the same run scope before wallet dispatch; unknown effects remain held until proved. Creation pauses when the shutdown reserve cannot be protected. The RED-market override consumes this run's read-only creation authority.

**Tech Stack:** Python, Flask/PyWebView, SQLite WAL, Sage wallet adapter, pytest, Playwright.

**Spec:** User instructions in this task: continuous Follow, 24 BUY + 24 SELL on each original-profile PC, maximum safely selectable XCH/MZ while retaining protected fee principal, 0.05 XCH cumulative fee cap per PC, 48-hour observation, one identical normal production-path build.

## Global Constraints

- Decimal for prices and XCH amounts; integer mojos for wallet fees.
- All database writes through `database.py`; all wallet calls through `wallet.py`.
- Preserve runtime lease, wallet identity, safety latch and exact unsigned pricing fences.
- Native final clicks require their applicable human confirmation; no CLI/API wallet-effect bypass.
- Keep PR272 and website PR93 draft/unpublished until verified.

## Review Focus

- A submitted but unconfirmed cancellation must hold its entire quoted fee across restart.
- A single-offer cancellation must not fall back to unapproved serial dispatch.
- A settings or wallet change must invalidate creation while retaining cleanup authority for prior offers.
- A Stop or expiry must remove creation authority without stranding approved cleanup.
- A new fee session or process restart must not reset the previous run's 0.05 XCH accounting.

---

### Task 1: Durable native run binding and read-only creation authority

**Files:** `src/catalyst/database.py`, `tests/test_follow_fee_authority.py`, native review route and GUI.

**Interfaces:** `create_follow_run_authority(...)` persists one reviewed run; `get_follow_creation_authority(identity, configuration_sha256, now_epoch)` returns the exact immutable run binding or a fail-closed reason. It never dispatches a wallet effect.

- [x] Write a failing test for exact run binding, config drift and expiry.
- [x] Reproduce the missing function failure.
- [x] Add immutable schema and reader; run focused tests.
- [x] Add unresolved-hold test and fail-closed reader state.
- [ ] Bind creation to an exact native review/consent event and verify copied original-profile DB migration.
- [ ] Add Stop/expiry append-only lifecycle with cleanup rights retained.

### Task 2: Attribute all Follow intents and fee effects to the run

**Files:** `src/catalyst/offer_manager.py`, `src/catalyst/bot_loop.py`, `src/catalyst/database.py`, focused tests.

**Interfaces:** Follow intents carry `follow:<run_id>:<classification>` while preserving normal/book-opportunity classification. Only matching active authority permits new creation. Existing legacy intents do not inherit a new run.

- [ ] Write a failing test for a new Follow intent created without authority and for a mismatched run ID.
- [ ] Enforce authority before persisted create and before final wallet submission.
- [ ] Verify both normal and book-opportunity intent purpose and restart recovery.

### Task 3: Exact priced cancellation hold for every Follow path

**Files:** `src/catalyst/offer_manager.py`, `src/catalyst/database.py`, fee pricing/dispatch helpers, focused tests.

**Interfaces:** The canonical Follow run ID resolves one fee approval scope. Each batch, including a singleton, obtains exact unsigned cost, fresh quote, atomic hold, dispatch recheck and terminal/no-effect outcome. No generic unpriced fallback is permitted.

- [x] Write a failing test proving a Follow-labelled cancellation reaches the generic unapproved route; reproduce the bypass before adding its fail-closed boundary.
- [x] Reproduce the unapproved Follow cancellation path and add an early fail-closed guard for scoped, malformed and singleton intents. This is a temporary safety boundary; the approved priced path remains required.
- [ ] Cover routine requote, degraded withdrawal, Stop, Cancel All, expiry and shutdown call sites.
- [ ] Enforce full-book shutdown reserve at creation and cancellation planning.
- [ ] Recheck the same approval, run, wallet, intent roots, fee coin and quote under the final dispatch lock.
- [ ] Verify crash/restart and ambiguous submitted outcomes remain held without duplicate effect.

### Task 4: Native configuration, integration and release gates

**Files:** Native GUI, Flask routes/AppBridge, integration and browser tests, build workflow.

- [ ] Present exact wallet, pair, 24/24 limits, duration, principal, 0.05 cap and shutdown reserve for native approval.
- [ ] Require financial creation authority and scoped risk consent before Start; do not auto-start on either approval.
- [ ] Show spent/held/remaining fees and clear review-needed reasons in GUI.
- [ ] Run relevant full tests, Ruff, copied original-profile migration/replay, clean default Windows build, Defender and independent review.
- [ ] Use the same exact built artifact on both original profiles after action-time executable confirmation and human wallet authentication.
- [ ] Begin new identity-bound 24-hour acceptance only after both live ladders are stable and fully audited.
