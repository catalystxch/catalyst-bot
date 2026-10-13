# TEST 7 refresh-abort startup gate (2026-10-13)

## Original-profile observation

- The prior stopped TEST 7 CATalyst closed through its native shutdown dialog
  with offer cancellation unchecked. Its process and port 5000 exited and its
  mutation lease was released. Sage remained running. No wallet action was
  requested during the replacement launch.
- The clean `db07643` package (EXE SHA-256
  `F329C015BBF7F40B835AFF9A66879B4F0ECB980C6151A40F5D6141095E069BAD`)
  opened only **CATalyst Startup Safety** as PID 205956 on port 5001. The
  read-only diagnostic reported `UNRESOLVED_OPERATIONS`, latch generation 667,
  the exact submitted parent cancellation blocker, and no active lease owner.
  Normal trading and the native refresh-abort controls were unavailable.
- The live database had no `offer_refresh_aborts` table. No abort record, new
  cancellation, publication, or other wallet effect was made by this launch.

## Reproduction and source correction

- On a disposable, consistent SQLite backup of the TEST 7 profile,
  `preflight_requires_diagnostics()` was false and
  `attempt_db_recovery()` returned `action: ok`. `init_database()` then raised
  `stability migration watermark contradicts schema`: the new
  `offer_refresh_aborts` table was classified as an original stability table,
  although existing profiles have an older completed backfill watermark.
- A regression test recreates the legitimate older state by dropping only
  that new table from a valid, watermarked isolated database. It failed with
  the same error before the fix and passed after classifying the table as a
  later upgrade. The copied TEST 7 database then initialized successfully and
  created `offer_refresh_aborts`; the original profile was not migrated by
  this diagnostic test.
- Commit `01afe537ea0ff16480da17f6cb0fe414237a2065` on draft PR #268
  contains the migration correction. Local focused stability, refresh-abort,
  native UI, and related migration tests passed: **188 passed, 7 skipped**
  across the two test commands. Ruff and `git diff --check` passed. CI on this
  head must be checked separately.

## Recovery remains blocked

- Read-only Sage evidence on the disposable copy proves the parent cancelled
  on chain with an owned same-amount return coin, but the replacement child is
  only `created` and has no first-visibility proof. The ordinary Task 9
  transition correctly refuses to mark the parent terminal without a scoped
  refresh-abort authority. The existing startup recovery does not supply one.
- The current refresh-abort API requires an owned renewing lease and a running
  native API, while blocked startup falls back to a read-only diagnostics
  server and discards the pre-owner mutation runtime. The migration fix alone
  therefore does **not** complete the live cancellation or authorize a new
  launch. A reviewed restricted startup/recovery entry is still required;
  generic latch clearing, direct live SQL edits, or a second parent cancel
  would not preserve the safety proof.
- TEST 7 remains fenced. The two other Sage-active offers and any later
  wallet state require a fresh complete Sage/DB audit before a recovery action.

## Restricted-entry investigation

- A fresh disposable TEST 7 SQLite backup reproduced the one-blocker case.
  The exact candidate discovery returned true, and the amended desktop
  initialization left the latch at generation 667 with the same sole cancel
  blocker. It did not run generic legacy recovery and add a second blocker.
  Local mutation-gate and schema tests passed: **433 passed**. A separate
  formatting correction was pushed as `00dbdb6` after CI found it.
- On that copied profile, a separate recovery run acquired an inactive lease
  while the durable latch stayed tripped. Its status remained
  `UNRESOLVED_OPERATIONS`, `allowed=false`, owned by that run, with the sole
  original cancel blocker; the copied lease was then released. An isolated
  regression proves normal offer creation remains blocked under this state.
  No lease was acquired against the original TEST 7 database.
- A fresh read-only Sage identity and complete offer-book observation matched
  the configured TEST 7 fingerprint and mainnet binding, with **two active
  offers and zero pending transactions** at that observation. These are not
  durable final-state claims and must be refreshed before any wallet effect.
- The copied profile's latest stopped campaign has no applicable Coin Prep
  fee approval in the campaign lookup. Other stopped campaigns do have
  approvals, but using one of those for this campaign would be unsafe. The
  restricted recovery view needs a campaign-specific cancellation-only fee
  approval path before it can submit a remaining offer cancellation.
- A dormant restricted HTTP guard now admits only the recovery page, bounded
  safety status, exact preview, and four exact abort operations; a red/green
  regression blocks ordinary bot, Coin Prep, Bootstrap, Splash, generic offers
  and status routes when that mode is enabled. Desktop activation, the
  restricted native page and its fee approval remain unimplemented, so the
  live app remains read-only and no recovery action has occurred.

## Restart limitation found during entry design

- The current abort row stores its entering run's lease owner, PID, host,
  acquisition timestamp and version. Exact cleanup authorization compares
  them to the current lease. Ordinary expired-owner takeover rejects a
  tripped latch; a disposable regression confirms that a dead prior PID does
  not make generic takeover safe. No scoped successor for this abort record
  exists yet. Without it, a crash after abort entry could leave the profile
  permanently fenced despite valid Sage proof. A new atomic successor path
  and crash/replay tests are required before original-profile recovery.

## Isolated successor work in progress

- A disposable database reproduction now proves an exact abort can move from
  a released owner or a proven-dead expired owner to one successor while the
  safety latch stays tripped. Incomplete Sage books, pending transactions,
  asset mismatches, active predecessors and missing death proof are rejected.
- A production gate wrapper supplies the process liveness proof and keeps
  ordinary offer creation blocked after the scoped handoff. The read-only
  startup detector also recognizes a previously entered abort, including an
  expired predecessor, without granting a lease.
- A separate red/green test exposed an inconsistent state in which the child
  publication outbox said `succeeded` while the local child intent still said
  unpublished. Abort entry and successor adoption now reject that state.
- These are isolated code and database tests only. The restricted desktop
  entry, native recovery page, fee consent, final packaged candidate, and
  original TEST 7 recovery remain open. The live diagnostic process and its
  unresolved latch have not been changed by these tests.
- Each successor now writes a same-transaction, append-only receipt binding
  the prior and new leases to the exact abort, latch, campaign, identity and
  observed Sage book. Readback validates the receipt digest and bindings.
  A watermarked existing-profile schema upgrade installs the receipt table;
  the 143-test schema/recovery suite passed locally. This is still a dormant
  recovery primitive, not a live recovery result.
- A disposable two-target incident now passes through both distinct Task 8
  cancellation submissions, both Task 9 terminal chain/coin proofs, and the
  final empty-book abort completion. The test asserts one Sage cancellation
  effect per exact target, two separate fee coins, a retained fence between
  targets, and an unresolved Task 11 refresh lineage after completion. All
  ten incident variants plus the real fee-finalization test passed locally.
  This is mock-Sage evidence only; it does not approve original-profile use.
- The restricted HTTP flag now also prevents Flask startup from constructing
  the trading BotLoop or starting normal owned runtime services. Both guards
  were first tested red, then green. The full first-run/bootstrap and mutation
  gate suite passed 327 tests. The flag still has no production startup
  activation; original TEST 7 remains on its old fenced build.
- The restricted HTTP root now serves a separate authenticated, read-only
  recovery page rather than the trading GUI. It displays fresh preview
  fields through text nodes, has no trading/cancellation controls, and fails
  closed when the preview is unavailable. Two Chromium E2E tests passed,
  including hostile text that must not execute as HTML. Startup activation,
  exact operator actions and packaged acceptance remain open.
- Restricted-view/backend packaging checks passed 305 tests; Ruff and diff
  whitespace checks passed. A clean worktree PyInstaller build completed and
  contains `refresh_abort_recovery.html` in `dist/Catalyst/_internal/`. This
  confirms inclusion only; the packaged original-profile runtime has not
  been launched, and its live recovery acceptance remains open.
