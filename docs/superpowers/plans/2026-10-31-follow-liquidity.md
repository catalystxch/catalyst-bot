# Follow Liquidity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run verified 24 BUY / 24 SELL Follow ladders on both original-profile PCs with one-time fee consent and scoped thin-market RED trading.

**Architecture:** Preserve the existing fee ledger, Follow authority, wallet mutation lease, and Sage adapter. Add a narrow proof-only recovery for TEST7's ambiguous pre-send creation; use normal CATalyst cancellation afterward. Make native reviews display current fee consent, and revalidate RED quotes at every final wallet boundary.

**Tech Stack:** Python, Flask, SQLite through `database.py`, PyWebView, vanilla JavaScript, pytest, Playwright, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-10-31-follow-liquidity.md`

## Global Constraints

- Never send a wallet transaction from a read-only review or heartbeat.
- Never exceed 50,000,000,000 mojos cumulative fee per original-profile wallet.
- Native financial final clicks require action-time confirmation; wallet authentication is human-only.
- Preserve exact run, identity, offer, price-band, expiry, fee-source and journal bindings.
- Keep PR272 and PR93 open/draft and unpublished.

## Review Focus

- A Sage process restart during recovery must invalidate a pending review; test with changed process identity.
- A newly active or filled offer between two book observations must refuse no-effect recovery; test changed book and pending state.
- A user-edited fee ceiling must not be silently replaced by a stored approval; browser test the explicit edit.
- A current RED quote that becomes stale before send must wait without creating an ambiguous intent; test the wallet continuation boundary.
- Two PCs with different binaries or fee scopes must not start observation; test the verification gate.

---

### Task 1: Show the approved fee ceiling in Follow review

**Files:** `bot_gui.html`; `tests/e2e/test_prestart_follow_fee_ceiling.py`

**Interfaces:** Consume `coin-prep/status` `follow_fee_approval.total_fee_mojos` or `fee_approval.total_fee_mojos`; produce a request to `/follow/run-review` with the exact approved mojos.

- [x] Write a browser test for a recorded 0.05 XCH ceiling and observe failure.
- [x] Hydrate the untouched field from the exact approval and preserve explicit edits.
- [x] Run the focused browser tests.
- [ ] Review the resulting native copy and the missing-approval suggestion path.

### Task 2: Prove and close one ambiguous creation with no wallet effect

**Files:** `src/catalyst/creation_no_effect_recovery.py` (new); `src/catalyst/database.py`; `src/catalyst/app_bridge.py`; `bot_gui.html`; focused tests.

**Interfaces:** Produce `preview_creation_no_effect()` with exact identity, intent, source coin, two Sage observations, latch generation, digest and expiry. Consume the identical reviewed object in `commit_creation_no_effect(reviewed)`; return `wallet_effect_started: false` and the exact resolved operation. The database commit uses one transaction and compare-and-set conditions.

- [ ] Write failing tests for the TEST7 shape, changed book, spent/bound coin, pending transaction, changed Sage process, wrong latch and stale review.
- [ ] Implement read-only proof collection and native review without storing a wallet effect.
- [ ] Implement one atomic DB-only recovery journal/intent/reservation/latch transition.
- [ ] Verify idempotency, stale-review refusal and that all unrelated records remain unchanged.
- [ ] Run focused and full tests; inspect native review before any live use.

### Task 3: Cancel only the two Sage-active TEST7 SELL offers

**Files:** existing `offer_manager.py`, `follow_fee_cancellation.py`, native Cancel All view and tests only if needed.

**Interfaces:** Reuse the current normal fee-ledger-backed cancellation, exact unsigned cost/fee quote and native final click. No direct Sage RPC from outside `wallet.py`.

- [ ] Recheck original wallet, complete book, two exact IDs, pending0, fee budget and protected fee coin.
- [ ] Obtain a current exact cancellation quote and present the native review.
- [ ] Seek action-time final confirmation, submit once, and verify both offers terminal in Sage and DB.

### Task 4: Make thin RED liquidity sustainable

**Files:** `src/catalyst/confidence_override.py`; `src/catalyst/offer_manager.py`; `src/catalyst/bot_loop.py`; focused tests.

**Interfaces:** Preserve `RunConsent` scope and hard band; pass candidate price/size through `assess_passive_red_candidate` against refreshed current evidence at the final wallet boundary.

- [ ] Reproduce the last live BUY `market_data_invalid` and third SELL pre-send safety stop using captured timing conditions.
- [ ] Add failing tests for sustained 24/24 passive quoting with thin but current evidence, and for stale/unknown evidence refusal.
- [ ] Implement one bounded change at a time; keep effect-boundary checks authoritative.
- [ ] Run focused, full, and native dry reviews without a wallet effect.

### Task 5: Normal build, both PCs, and observation

**Files:** build output and verification records; PR272 and PR93 remain draft.

- [ ] Run relevant tests, full suite, lint and normal PyInstaller build from exact PR head.
- [ ] Verify binary hash, process identity, ports, original Sage identity and complete offer/accounting history on each PC.
- [ ] Obtain action-time confirmation for each new EXE launch, wallet authentication and each final financial click.
- [ ] Prove 24 BUY and 24 SELL live per PC with identical binary and fee/RED scope.
- [ ] Observe both ladders for 48 hours, recording drift, fills, fees, latches and terminal outcomes.
