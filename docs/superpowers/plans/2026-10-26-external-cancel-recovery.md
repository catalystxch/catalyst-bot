# External Sage Cancellation Recovery Implementation Plan

> **For agentic workers:** Execute the tasks below in order with test-first verification. The calling agent performs the work directly; no delegation is required.

**Goal:** Safely reconcile a cancellation made in Sage while CATalyst was closed, so the original TEST7 profile can pass the next Follow start gate without falsifying CATalyst's failed cancellation attempts.

**Architecture:** Keep ordinary Task 8/Task 9 cancellation unchanged. Add a separate external terminal authority built from exact Sage transaction and coin evidence, then commit the terminal projection and an external fee audit atomically. Expose only a native proof-only review and confirmation; no wallet-effect method is reachable from this path.

**Tech Stack:** Python, SQLite WAL, Flask/AppBridge, PyWebView, vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-external-cancel-recovery.md`

## Global Constraints

- All app DB access stays in `database.py`; wallet reads go through `wallet.py`.
- Use integer mojos/atoms and `Decimal`, never float, for economics.
- The external cancellation fee is historical wallet activity, never charged to a new Follow run.
- No live profile mutation, wallet effect, or new EXE launch from heartbeat checkpoints.
- Initial new Follow ceiling is 0.005 XCH per PC, adjustable during the run through fresh native review.

## Review Focus

- Sage's CANCELLED label without a confirmed matching spend leaves the intent unresolved.
- A returned coin belonging to another wallet, asset, or offer leaves the intent unresolved.
- A second external spend or changed proof cannot replay the recovery.
- An in-flight CATalyst-submitted Task 8 cancellation cannot be adopted as external.
- A GUI request cannot supply its own transaction proof or call a wallet-effect method.

---

### Task 1: Exact read-only external proof

**Files:** `src/catalyst/offer_reconciliation.py`, `tests/test_offer_reconciliation.py`

**Interface:** `classify_external_cancel_evidence(intent, evidence, *, now=None) -> dict`

- [ ] Add tests for exact single-offer cancellation and each Review Focus evidence mismatch.
- [ ] Run the tests to observe the intended failures.
- [ ] Implement read-only evidence classification using the existing authoritative Sage loader and exact coin/transaction helpers. Do not synthesize Task 8 context.
- [ ] Run the focused tests and Ruff.

### Task 2: Durable external authority and atomic settlement

**Files:** `src/catalyst/database.py`, `tests/test_task9_authoritative_terminal_policy.py`

**Interface:** `commit_external_offer_cancellation(...) -> dict`, consuming an exact bounded proof and committing an append-only external journal event, terminal offer/intent, coin returns, and fee audit in one transaction.

- [ ] Add tests for exact commit, same-proof replay, changed proof, conflicting spend, failed Task 8 history, and active submitted Task 8 blocker refusal.
- [ ] Run the tests to observe the intended failures.
- [ ] Add schema/migration and commit validation. Keep the Task 8 guard on `commit_offer_reconciliation` unchanged.
- [ ] Run focused database/schema tests and Ruff.

### Task 3: Native proof-only review and confirmation

**Files:** `src/catalyst/blueprints/offers.py`, `src/catalyst/app_bridge.py`, `bot_gui.html`, `tests/test_plan_04_04_offers_endpoints.py`, `tests/e2e/test_external_cancel_recovery.py`

**Interface:** A read-only preview bound to one exact trade/wallet/network and a short-lived digest; final confirmation re-reads fresh evidence and commits only the same proof.

- [ ] Add failing route and browser tests for exact review text, changed evidence rejection, no wallet-effect calls, and inaccessible/ambiguous wallet state.
- [ ] Implement preview and final confirmation with the existing native request/session gates and escaped UI rendering.
- [ ] Run focused route/browser tests and Ruff.

### Task 4: Start gate and original-profile validation

**Files:** `src/catalyst/bot_loop.py`, `tests/test_bot_loop_daily_reconcile.py`, original TEST7 evidence files.

- [ ] Add a regression showing an unresolved external cancellation blocks a new Follow start with a clear reason.
- [ ] Verify the normal safety gate permits start only after exact terminal proof and Sage/DB agreement.
- [ ] Run affected tests, then the complete suite, normal build, CI, artifact hash/Defender checks.
- [ ] With user-reviewed native launch and confirmation, apply proof-only recovery to original TEST7; compare Sage, original DB, fees and GUI before any live start.

### Task 5: Identical two-PC release handoff

- [ ] Verify one immutable normal EXE hash and full file manifest on both PCs.
- [ ] Keep PR272 and site PR93 draft until the live acceptance objective and release gates pass.
- [ ] Review 24 BUY/24 SELL inventory, max safely selectable balances, 0.005 XCH initial fee ceiling, scoped RED override and 48-hour observation through the native UI on each original profile.
