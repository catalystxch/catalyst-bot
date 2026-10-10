# Secondary-PC CAT tier sizing defect evidence — 24 September 2026

## Candidate identity

- Acceptance base: `5b54d9465555aaa5bbd7dd43ff51f299cab89ca6` on
  `codex/coin-prep-fee-approval`.
- Transferred candidate ZIP SHA-256:
  `28267F5906705EFFEA88DD720F8BA0AB7DA30FCD428858E100110649B59B50F2`.
- Transferred candidate EXE SHA-256:
  `696BEAD6A79CED2B846E67781F59F73A6EA05FF694BDE649AF43A3B1FFD62A25`.
- Fix branch: `codex/fix-coin-prep-cat-tier-designation`.
- Fix commit before this evidence note:
  `9eddbc78baf2f5a7efa2ce399d446ebc6b150802`.
- Fresh fixed EXE SHA-256:
  `9EB1B2985FB63B234783D1E6784D34D0F84378DE83C71CC23AA6908DDC14BD29`.
- Fixed build used Python 3.12.10 and PyInstaller 6.22.3. The Windows
  package was built from the fix branch with `python build.py`.

## Authorized live identity

- Chia mainnet; Sage v0.13.0.
- Wallet: `Harvestr test wallet`, fingerprint `3702373391`.
- CAT wallet ID `2`; ticker `MZ_XCH`.
- Asset ID
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- Isolated data directory:
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\acceptance-data\5eb10c8\isolated-live-copy`.

## Confirmed defect and root cause

The GUI passed prepared CAT output counts, including spare outputs, through
`--tier-counts-cat`. The Coin Prep worker then reused those total output
counts as the executable live sell-ladder shape when deriving CAT
denominations. One live offer plus one spare per tier was therefore priced as
two live positions per tier. The worker produced larger mid/outer CAT coins
than the GUI preview and the runtime subsequently reduced the sell target from
three to two because the expected tier inventory no longer matched.

The fix adds a separate `--live-tier-counts-cat` contract. The endpoint still
passes total prepared output counts to the worker, but passes live sell slots
independently for ladder pricing. The worker preserves legacy standalone
behavior when that new argument is absent.

## Live reproduction and corrected run

- Original 12% run reproduced the mismatch: preview inner/mid/outer CAT sizes
  were `57073.063`, `46416.662`, and `33994.323`, while the worker used
  `57073.063`, `46641.174`, and `34316.934`. Runtime then saw CAT spares
  inner/mid/outer `2/0/0` and reduced the sell target from 3 to 2.
- Corrected changed-size 13% run started 16:17:06 BST and completed 16:23:03
  BST in 5 minutes 57 seconds. Run ID: `efa16e31`.
- Approval ID:
  `a46f1cd8f340cb0c24aa148b13187b52d3bdf4820f0ab82b3964fd59ac1ea91e`.
- Approved cumulative fee cap: `0.000012190420 XCH`; protected cancellation
  reserve: `0.000001856100 XCH`.
- Authoritative actual fee: `0.000001159388 XCH` total: CAT batch `923983`
  mojos and XCH batch `235405` mojos.
- Two of two operations confirmed, 62 targets reconciled, zero unresolved and
  zero held fees. Final XCH/CAT tier groups were `2/2/2`; the fee pool held 50
  exact `0.001 XCH` coins.
- Correct 13% CAT sizes were inner `57582.644`, mid `46831.097`, and outer
  `34297.844`. The GUI preview, worker execution, database designations and
  restarted dashboard agreed. `/api/coin-prep/status` reported
  `tier_size_drift: []`.
- No `BAD_AGGREGATE_SIGNATURE`, duplicate spend, unresolved operation, or fee
  cap violation occurred. After preparation, no new adaptive sell-target
  reduction from 3 to 2 appeared.

## Restart, bot and external-gate result

- Restart recovered the exact Sage/MZ identity and showed XCH/CAT prepared
  tier groups `2/2/2` with 50 fee coins.
- Bot preflight passed with nine checks and one expected Spacescan-free-tier
  warning. Six or more loops completed with zero errors and zero offers.
- Publication correctly remained blocked by RED attributable market
  confidence: out-of-range depth excluded, insufficient ask depth, and a
  single provider dependency. The observed Dexie book had substantial bid
  depth but only about `0.55 XCH` ask depth. No safety gate was bypassed.
- There were no live CATalyst, Sage or Dexie offers to cancel. Shutdown
  confirmed no open offers were left behind.
- A later readiness check found 19 of 20 `0.3729 XCH` reusable sniper coins;
  every CAT tier, XCH tier and fee denomination remained sufficient. Coin
  Prep correctly stayed blocked when both fee estimators were unavailable.
- A temporary full-disk condition made the mutation lease heartbeat fail and
  Splash report `database or disk is full`. CATalyst switched read-only. After
  deleting only redundant acceptance-copy backups and regenerable build/test
  artifacts, CATalyst was restarted and returned to runtime safety ALLOWED
  with the same wallet/pair identity and zero unresolved mutations.

## Verification

- Focused compatibility regression: **3 passed**.
- Coin Prep economics, sell-ladder and endpoint selection: **94 passed**.
- All top-level Coin Prep and sell-ladder tests: **859 passed**, 2 collection
  warnings, 5 minutes 20 seconds.
- Ruff on changed Python files: passed.
- Packaged API smoke: passed, including health, wallet startup, config,
  diagnostics, self-test and Doctor routes.
- Packaged Sage RPC worker smoke: passed.
- Fresh Windows package build: passed.
- Full regression suite: **6990 passed, 157 skipped, 1 warning** in 27 minutes
  10 seconds (`1630.74s`), exit code 0. The sole warning is the existing
  pytest 10 deprecation for a non-Collection `parametrize` iterable in
  `tests/test_offer_registry.py`.

## Preserved evidence

- Live log:
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\acceptance-data\5eb10c8\isolated-live-copy\bot_superlog_20260924_161012.log`.
- Restart/disk-recovery log:
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\acceptance-data\5eb10c8\isolated-live-copy\bot_superlog_20260924_164621.log`.
- Redacted debug bundle:
  `C:\Users\M920q\Downloads\bot_debug_bundle_20260924_160045.zip`.
- The newest intact database backup is retained at
  `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\acceptance-data\5eb10c8\isolated-live-copy\backups\bot_backup_20260924_163755.db`.

## Separate defect

`scripts/packaged_desktop_first_launch_smoke.py` independently reproduced a
duplicate desktop-launch handoff failure twice, including with other CATalyst
processes stopped. It is intentionally excluded from this sizing fix and must
be handled on a separate branch and pull request from the acceptance base.
