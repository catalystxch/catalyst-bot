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
