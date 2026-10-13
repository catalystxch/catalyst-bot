# Confirmed Refresh Cancel Abort Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover a chain-confirmed parent cancellation whose replacement
child never became visibly published, then finish the operator's Cancel All
without reopening trading or inventing publication proof.

**Architecture:** Add one exact durable abort record and blocker. The parent
chain result can be committed through Task 9 only while that blocker remains;
the child stays `created`. A restricted cleanup permit can cancel only the
abort's exact Sage-active targets under normal wallet and fee checks. The
abort closes only after terminal proof and a complete empty wallet read.

**Tech Stack:** Python 3.12, SQLite WAL, Flask/PyWebView, Sage RPC, pytest,
Chromium UI tests, Windows PyInstaller package.

**Spec:** `docs/superpowers/specs/2026-10-13-refresh-abort-cleanup-design.md`.

## Global Constraints

- All database writes remain in `src/catalyst/database.py` and every wallet
  call remains through `wallet.py`.
- Amounts/prices use `Decimal` or integer mojos; no `float` fee arithmetic.
- Normal visible-child refresh and the new PR #268 pre-effect parent guard
  retain their existing behavior.
- Never treat Splash local dispatch, a Dexie 404, or expiry as child visibility.
- Do not run the original TEST 7 profile against a candidate until isolated
  tests, package and independent review pass.

## Review Focus

- Wrong wallet/network, asset, reciprocal lineage or selected input: reject
  before creating an abort record (Task 1 tests).
- Changed latch generation, additional blocker, lost lease or pending effect:
  leave the fence closed without attempting a wallet action (Tasks 1 and 3).
- Crash after chain proof but before the response: replay the same terminal
  journal and never resubmit the parent cancel (Task 2).
- Queued or possible in-flight child publication: suppress only a proven
  terminal queued row; refuse ambiguous dispatch (Tasks 1 and 4).
- A new/unknown Sage offer or a fill during cleanup: stop and require fresh
  review; never silently widen targets (Tasks 3 and 4).

---

### Task 1: Durable abort identity and retained fence

**Files:** Modify `src/catalyst/database.py`; extend
`tests/test_refresh_safety.py`, then use `tests/test_refresh_abort_cleanup.py`
for the later proof and cleanup boundaries.

**Interfaces:** `begin_refresh_abort(*, parent_intent_id: str,
child_intent_id: str, campaign_id: str, expected_latch_generation: int,
owner_run_id: str, expected_lease_version: int,
observed_trade_ids: list[str], observed_at: str) -> dict` and
`get_refresh_abort(abort_id: str) -> dict | None`. The abort ID is a digest of
the immutable parent/child/cancel/generation tuple. Store its exact target
list, wallet binding, status, and blocker in the existing stability schema.

- [x] Write disposable-DB tests that set up a confirmed parent, reciprocally
  bound `created` child and submitted cancellation, then assert an exact abort
  is durable and the existing latch cannot become resolved. Add wrong
  generation/wallet/lineage, second blocker, and replay mismatch refusals.
- [x] Run those tests and confirm they fail for the missing recovery API.
- [x] Implement the smallest schema, migration and atomic compare-and-set
  entry. Record the abort blocker in the same transaction as its immutable
  entry; do not make a wallet or publication call.
- [x] Run the focused tests and existing stability schema/migration tests;
  commit this independently reviewable database boundary.

### Task 2: Record the chain result while coverage remains false

**Files:** Modify `src/catalyst/offer_registry.py`,
`src/catalyst/offer_reconciliation.py`, `src/catalyst/database.py`; extend
`tests/test_refresh_abort_cleanup.py`.

**Interfaces:** `reconcile_aborted_refresh_parent(abort_id: str, *,
wallet_facade: object | None = None) -> dict` may select the exceptional
terminal transition only for the exact Task 1 abort and Task 8 cancellation.
`commit_offer_reconciliation(..., refresh_abort_id: str | None = None)` must
verify that authority again in its transaction and retain the abort blocker.

- [ ] Write a failing test using complete Task 8 transaction, spent selected
  coin and owned return proof: parent becomes `CANCELLED_PROVEN` once, child
  remains `created`, Task 11 completion remains false, and the latch remains
  tripped for the abort. Add missing/changed proof and crash replay tests.
- [ ] Run red tests; implement the narrow typed registry exception and
  transactional DB checks without relaxing ordinary `authorize_transition`.
- [ ] Run focused Task 8/9/11, registry and recovery suites; commit only
  after normal visible-child behavior still passes.

### Task 3: Restricted cleanup cancellation authority

**Files:** Modify `src/catalyst/mutation_gate.py`,
`src/catalyst/offer_manager.py`, `src/catalyst/database.py`; extend
`tests/test_refresh_abort_cleanup.py` and mutation-gate tests.

**Interfaces:** `enter_refresh_abort_cleanup(abort_id: str,
trade_id: str) -> str` returns a wallet mutation permit only for one exact
target still in the abort record. `OfferManager.cancel_refresh_abort_targets`
uses that permit and the existing Task 8/Sage/fee path; it never bypasses
the lower wallet permit, creates an offer, or retries the confirmed parent.

- [ ] Write a failing test proving cancellation of one exact remaining live
  child while the abort fence remains, with normal Task 8 journal and fee
  accounting. Add wrong target, pending transaction, unknown offer, lease
  loss, extra blocker and duplicate submission refusals.
- [ ] Run red tests; implement the permit and sequential cleanup path with
  fresh complete Sage identity/book reads before each effect.
- [ ] Run mutation, cancellation, wallet identity, fee and recovery suites;
  commit the reviewed cleanup boundary.

### Task 4: Close only after exact empty-book proof

**Files:** Modify `src/catalyst/database.py`,
`src/catalyst/offer_manager.py`; extend `tests/test_refresh_abort_cleanup.py`.

**Interfaces:** `complete_refresh_abort(abort_id: str, *,
observed_trade_ids: list[str], observed_at: str) -> dict` requires every
target's Task 9 terminal proof, no pending wallet effects, no live Sage offer,
and no ambiguous publication dispatch. It records `aborted`, suppresses
only proven-terminal queued publication rows, and releases the one abort
blocker. Task 11's successful commit remains absent.

- [ ] Write red tests for exact cleanup, stale row, an additional Sage offer,
  publication claim already dispatched, partial fill, and crash replay.
- [ ] Implement the atomic finalization and make pending-lineage reads
  distinguish an aborted pair from a successfully refreshed pair.
- [ ] Run focused tests and startup/recovery tests; commit after the normal
  refresh and new-campaign guards remain correct.

### Task 5: Operator view and isolated acceptance

**Files:** Modify `src/catalyst/blueprints/offers.py`,
`src/catalyst/app_bridge.py`, `src/catalyst/bot_gui.html`; extend offers API
and Chromium tests; update the incident evidence file.

**Interfaces:** A read-only recovery preview names the bound parent, child,
remaining Sage offers, safety generation, fee scope and exact abort stage.
The native final action starts only the reviewed abort/cleanup route after
the required action-time UI confirmation; status distinguishes proof waiting,
abort fenced, cleanup pending, and zero-offer completion.

- [ ] Write red API and Chromium tests for a stale four-row CATalyst counter
  versus three active Sage offers, exact preview, blocked states, and no
  second parent cancel. Test restart/rehydration of each stage.
- [ ] Implement the route, bridge and UI without an automatic wallet action
  on page load or a broad Cancel All retry.
- [ ] Run relevant frontend/backend suites, full serial Windows tests,
  isolated packaged mock-Sage and native smokes, build and Defender scan.
- [ ] Obtain independent second-PC source/package review. Only after that,
  hand off the exact candidate for original TEST 7 recovery, refresh every
  wallet/lease/fee/offer fact, and use the native action-time confirmation.
  Audit final Sage, CATalyst, Dexie/Splash and fee state before closing the
  live acceptance item.
