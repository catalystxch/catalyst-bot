# Single-approval CAT ladders implementation plan

> **For agentic workers:** Use `superpowers:executing-plans` task by task. Each task needs a focused failing test before code, a passing focused test, and review before the next task.

**Goal:** One reviewed decision after Smart Settings prepares coins, starts and maintains the chosen CAT ladder, including thin markets and a per-transaction fee maximum.

**Architecture:** Add a durable run policy and a small coordinator around existing wallet-effect and journal services. The policy records what the user approved; existing exact fee quotes, wallet identity, lease and pending-effect proofs remain internal checks. The GUI offers one review and displays state-machine progress instead of separate prep, Follow and RED consent screens.

**Tech Stack:** Python, Flask, SQLite through `database.py`, Sage through `wallet.py`, vanilla JS/HTML in `bot_gui.html`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-single-approval-ladders.md`

## Global constraints

- Use `Decimal` for prices/amounts and integer mojos for fees.
- Keep all database access in `database.py` and wallet access through `wallet.py`.
- Preserve exact wallet-effect journal, pending-effect, mutation-lease and identity checks.
- Stop never implies Cancel All. A manual Stop clears automatic restart intent.
- Test with a mock wallet before any live effect; do not use real funds for automated tests.
- Keep the work on the current feature branch and PR; do not commit to `main`.

## Review focus

- Same wallet, same CAT, same policy after restart with zero or nonzero offers: resume without duplicate effects.
- Unknown prep/cancel transaction: reconcile authoritative wallet state before any retry.
- Network fee estimate above approved per-transaction maximum: ask to raise; attempt a lower fee within cap when safe; never exceed cap.
- RED/stale price: warn and continue within approved range; never silently place beyond it.
- 100/100 target with insufficient coins: fundable/live counts are honest and the bot fills later.

## Tasks

### 1. Preserve user targets and support 100/100

**Files:** `src/catalyst/blueprints/smart_defaults.py`, `src/catalyst/follow_principal.py`, `bot_gui.html`, focused Smart Settings and Follow review tests.

- [ ] Write failing tests for 100/100 target, preserved user count and fee principal, and a review that reports fundable counts.
- [ ] Remove the 50-per-side input/authority cap in favour of positive bounded-by-resource planning; never advertise a live count as the target.
- [ ] Run focused Smart Settings, planner, Follow authority and GUI tests.

### 2. Persist one exact run policy

**Files:** new `src/catalyst/follow_run_policy.py`, `src/catalyst/database.py`, `src/catalyst/blueprints/coin_prep.py` or a new focused blueprint, `src/catalyst/app_bridge.py`, focused policy tests.

- [ ] Write failing tests for a disclosure bound to fingerprint, network, asset, target, price anchor/range, fee pool and per-transaction fee maximum.
- [ ] Record one durable acceptance from the native UI; reject changed terms, identity or stale disclosure; expose policy/status read-only.
- [ ] Preserve historical cumulative fee records without treating them as this run's stopping ceiling.

### 3. Enforce the per-transaction fee maximum at every wallet-effect boundary

**Files:** `coin_prep_fee_dispatch.py`, prep and runtime fee services, cancellation paths, new policy reader, focused fee tests.

- [ ] Enumerate prep, top-up, cancel and replacement dispatch paths and write a failing test for each exceeding the approved cap.
- [ ] Use the lowest reasonable fresh quote under cap. If the estimate is higher, surface a raise-cap request and try within cap only when the wallet supports safe submission; track pending effect until authoritative outcome.
- [ ] Keep existing fee reservations and effect proofs; never convert a cumulative ledger column to a per-transaction value.

### 4. Automate approve → prepare → start and restart recovery

**Files:** new `src/catalyst/follow_run_orchestrator.py`, `blueprints/coin_prep.py`, `blueprints/bot.py`, `follow_restart_intent.py`, `bot_gui.html`, state-machine tests.

- [ ] Write failing mock-wallet tests for approval, missing split, confirmed split, transient Sage failure, unknown effect, then Start with no second click.
- [ ] Reuse existing prepared coins and journal/reconcile before retry; persist progress and error state for GUI polling.
- [ ] Resume same accepted run after restart with zero or nonzero live offers; manual Stop disables auto resume and leaves offers open.

### 5. Apply approved thin-market and price policy

**Files:** `confidence_override.py`, `bot_loop.py`, `offer_manager.py`, price-anchor service, focused confidence tests.

- [ ] Write failing tests showing RED alone does not withdraw an approved run and an old agreed anchor can quote within its approved range with a persistent warning.
- [ ] Keep offers passive; warn on worsening RED; propose a new range when the market exits the approved one and leave existing offers open awaiting approval.
- [ ] Preserve wallet/asset mismatch and unknown-effect blocks.

### 6. Replace the multi-screen setup UI and verify end to end

**Files:** `bot_gui.html`, native bridge, focused GUI and lifecycle integration tests.

- [ ] Present one editable review after Smart Settings with all material facts and RED reasons.
- [ ] Show preparing, waiting for confirmation, running/building, target/fundable/live, fee-cap warning, and range-approval states.
- [ ] Run relevant tests, fresh build, and mock-wallet end-to-end setup/restart checks.
- [ ] After user review of the exact live run on each PC, verify Sage/DB/GUI active counts and monitor 48 hours. Do not infer success from a Start response.
