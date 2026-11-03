# Thin-market 24/24 ladders implementation plan

> **For agentic workers:** Use superpowers:executing-plans task by task. Each task starts with a failing behavior test and ends with focused verification. The live wallet is outside the automated test environment.

**Goal:** Establish continuous 24 BUY and 24 SELL MZ/XCH Follow ladders on each original-profile PC, with automatic fee-coin maintenance, thin-market operation and restart recovery.

**Architecture:** Keep market-policy consent separate from wallet-effect authority. Derive a provenance-bound reference price from current external evidence or a durable trusted anchor at most 24 hours old, then feed it through the existing quote, profitability, run-authority and effect-boundary checks. Replace cumulative fee ceilings with exact per-effect fee pricing and ledger accounting; reuse the existing fee tier for automatic replenishment. Resume only an exact run-bound wallet book after startup proof.

**Tech Stack:** Python 3.12, Flask, SQLite via `database.py`, Sage via `wallet.py`, vanilla HTML/JS, pytest, Playwright, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-11-03-thin-market-ladders.md`.

## Global constraints

- Use `Decimal` for prices/XCH and integer mojos for wallet amounts; do not add float-based price or fee calculations.
- Preserve wallet fingerprint/network/asset binding, mutation lease, unknown-effect journals, terminal proof and pending cancellation checks.
- The saved thin-market policy never grants wallet permission by itself. On restart it may supply RED-market policy only after the same wallet/pair binding and existing financial run authority are reproved.
- No live wallet mutations from tests, source investigation or build verification.
- Start with this PC; deploy the identical verified build to the other PC only after the first ladder is established.

## Review focus

- An empty or one-sided order book can start a passive ladder from a documented reliable external price or a trusted anchor younger than 24 hours.
- Conflicting or manipulated current prices never become a new trusted anchor; an anchor older than 24 hours pauses creation without cancelling existing offers.
- Repeated wallet-effect checks cannot turn stale evidence, a changed wallet or an expired run into authority.
- Fee-coin principal is never counted as a paid fee; an unknown submitted effect retains its held actual fee across restart.
- Restart reconciliation never duplicates an existing offer, silently creates a new run, or treats a missing Sage response as proof of no effect.

## Task 1: Baseline and exact state

**Files:** no product changes; record verification under `evidence/` or plan ledger.

- [x] Fetch draft PR272 head `1bbdad925f15dd5a8d9d4dcd5b8352ac74a64b3e` into an isolated feature worktree.
- [x] Run focused baseline policy, market, fee and coin-pool tests: 169 passed.
- [x] Capture this PC's stopped CATalyst/Sage identity, offers, pending effects, balances and fee coins read-only: `docs/superpowers/evidence/2026-11-03-primary-readonly.md`.
- [x] Capture fresh read-only market evidence: Dexie current book is RED due thin ask depth and single-provider dependency; see primary baseline evidence. Refresh again immediately before live action.
- [x] Capture current executable/hash before any live action: `C:\Users\t_you\AppData\Local\Programs\Catalyst\Catalyst.exe`, 10,728,382 bytes, modified 2026-09-04 02:35:10 UTC, SHA-256 `4338F1DEF53E6791AA98D0A400B2B426AE3B78690CEA0BDD05A46B3419676B33`.

## Task 2: Reliable thin-market reference and saved user choice

**Files:** `src/catalyst/market_confidence.py`, `src/catalyst/market_runtime.py`, `src/catalyst/confidence_override.py`, `src/catalyst/offer_manager.py`, `src/catalyst/bot_loop.py`, `src/catalyst/blueprints/smart_defaults.py`, `src/catalyst/blueprints/config_bp.py`, `src/catalyst/config.py`, `bot_gui.html`, focused market/GUI tests.

- [ ] Write failing tests for empty and one-sided book, own-offer exclusion, a durable age-stamped 24-hour trusted anchor, conflicting source, anchor expiry, and RED depth-only consent through final wallet-effect assessment.
- [ ] Persist the thin-market choice with exact wallet/pair scope and show its state in Smart Settings and runtime diagnostics.
- [ ] Build a reference-price reader with provenance and age; accept current nonconflicting evidence and at most 24-hour trusted fallback without a fixed absolute MZ band.
- [ ] Make depth-only RED skip progressive withdrawal when the saved choice and usable reference both hold; preserve current cancellation and creation guards for price-integrity and wallet failures. Scope the saved choice to exact wallet fingerprint, network and asset, and recheck it at each wallet-effect boundary.
- [ ] Requote and refill 24/24 from the effective reference, preserving positive fee-aware spread and current effect-boundary checks.
- [x] Verify focused Python and browser tests, then review the changed code: 249 market/restart tests, 55 fee desktop browser tests, and scoped price-rail review completed.

## Task 3: Fee coins for one week without a cumulative ceiling

**Files:** `src/catalyst/blueprints/smart_defaults.py`, `src/catalyst/tx_fees.py`, `src/catalyst/coin_manager.py`, `src/catalyst/coin_prep_fee_approval.py`, Follow fee service/DB readers, native fee review UI, focused fee tests.

- [ ] Write failing tests for week-based fee-coin count, last-good fee estimate with margin for sizing only, larger denomination after fee increase, and automatic low-supply replenishment.
- [ ] Replace the fixed 3%-of-XCH fee pool with a seven-day activity and fee estimate bounded by spendable inventory; keep principal and actual fees distinct.
- [ ] Make fee-coin denomination and target count update through the existing tier maintenance path without orphaning old fee coins.
- [ ] Replace the standard Coin Prep/Follow cumulative-ceiling mode with an explicit unbounded mode for new approvals, leaving historical bounded records and bootstrap campaigns intact. Retain reviewed run authority, exact current fee quote, available XCH, append-only spent/held ledger and unknown-effect protections.
- [ ] Update native copy and tests to describe fee coins and actual fee costs accurately.
- [x] Verify focused fee, coin-prep, cancellation and ledger tests: 176 passed after unbounded-mode integration.

## Task 4: Restart-safe continuation

**Files:** `src/catalyst/follow_principal.py`, `src/catalyst/blueprints/bot.py`, `src/catalyst/bot_loop.py`, `src/catalyst/database.py`, `bot_gui.html`, focused startup/resume tests.

- [ ] Write failing tests for a saved running intent, correct/wrong wallet, wrong network or unknown/unsynced Sage state, active 24/24 wallet book, partial book, pending/unknown effect, saved thin-market choice and no intent.
- [ ] Persist a restart intent only for a running Follow ladder and bind it to wallet, asset, config and run ID.
- [ ] Prove exact Sage-to-local membership of the retained Follow offers before resuming the same run; reconcile pending effects without blind replay.
- [ ] Start automatically only after wallet startup, strict mainnet sync, offer proof, matching saved RED policy and the same reviewed financial run authority pass; otherwise stay stopped with a precise reason. The saved RED choice removes repeat policy prompts but never substitutes for a wallet-effect approval. Preserve manual Stop as durable opt-out.
- [ ] Verify startup, resume, wallet and browser tests.

## Task 5: Build and live acceptance

Clean Windows build from the final formatted feature worktree passed on 2026-11-03. Staged `dist/Catalyst/Catalyst.exe` is 11,708,731 bytes, SHA-256 `09A1CAA091DB20B73821C6472B45DBF6184DA8A5A4E2084DBABEF04121103C85`. The installed executable was not replaced. Full suite: 8,440 passed, 384 skipped, 460 subtests passed; 85 focused tests passed after formatting. Ruff lint/format, `git diff --check`, and Bandit for the three new source modules passed.

- [ ] Run relevant tests and full suite in clean profiles, lint/format/security gates and a normal Windows build from the exact commit.
- [ ] Verify each build file/hash and open a draft PR into `main`; keep release unpublished during acceptance.
- [ ] Review this PC's exact wallet, market, coin-prep and 24/24 run terms in native CATalyst; establish and independently verify 24 BUY and 24 SELL Sage-active offers, zero unknown effects and a matching fee ledger. Perform a controlled restart and prove exact offer membership and automatic continuation before rollout to PC2.
- [ ] Transfer the identical verified build to the other PC, confirm its separate wallet and inventory, establish its independent 24/24 ladder and verify Sage-active counts.
- [ ] Monitor both PCs for 48 hours with timestamped Sage/DB/GUI snapshots at least every 15 minutes and immediate event captures for fills, reprices, top-ups and restarts. Record each side's active count, reason and recovery time for any under-target interval; never count a sustained empty or partial book as success. Reconcile paid/held fees and pending effects at the start, end and after material events. Leave both ladders running.
