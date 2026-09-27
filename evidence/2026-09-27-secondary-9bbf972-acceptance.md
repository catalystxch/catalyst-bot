# Secondary-PC combined integration acceptance — 2026-09-27

## Candidate identity

- Repository: `catalystxch/catalyst-bot`
- Branch fetched: `codex/coin-prep-fee-approval`
- Exact production candidate: `9bbf972a9e8b0b6459e67f483080dc487993a7ca`
- The candidate was checked out detached in a new worktree. `git rev-parse HEAD`
  and the fetched remote branch both resolved to the exact SHA above before any
  build or test.
- This checkpoint changes evidence only. It does not change production source,
  merge main, or create a release.

## Independent regression and suite results

- Four focused red-first regressions covering retired sniper inputs and standard
  Coin Prep restart rehydration: **4 passed**.
- Complete affected economics, fee-wallet-snapshot and Coin Prep endpoint group:
  **165 passed in 33.12 seconds**.
- Complete serial backend suite: **7,047 passed, 165 skipped, 422 subtests
  passed**, one pre-existing pytest deprecation warning, in **1,441.15 seconds**.
- Complete real-Chromium E2E suite: **164 passed in 107.57 seconds**.
- `ruff check src tests`: passed.
- `git diff --check 0bd46052fa67f7ad5bbef356cadf289f51c25e97..HEAD`:
  passed.
- Full-suite interpreter provenance: Python 3.12 project venv supplied
  `chia_rs`, Flask, requests, Playwright and pytest; the installed Sage
  site-packages directory was appended after venv initialization to supply the
  pure `chia` package. Module origins were printed and verified before the
  authoritative run.
- Two earlier collection-only attempts were invalid harness attempts and are not
  product failures: the lightweight venv lacked `chia`, while the machine Sage
  Python lacked the project dependencies. A path-order attempt then selected a
  Python 3.14 `chia_rs` binary ahead of the Python 3.12 venv. No tests ran in
  those attempts. The corrected runtime produced the complete green result
  above.
- An affected-group attempt ended after **164 passes and one setup error** with
  `sqlite3.OperationalError: database or disk is full`. The exact errored test
  passed alone, and the complete affected group then passed 165/165. This was a
  transient machine-capacity event, not an assertion failure.

## Windows build and package

- Fresh `build.py --no-clean` PyInstaller build: passed, including bundled HTML
  and certifi CA checks.
- Built executable:
  `dist/Catalyst/Catalyst.exe`
- Secondary executable SHA-256:
  `3210144F8DB7E6D85D13193D2B0CB5B59EF4F5089F581CD602534F20C13C8649`
- Secondary ZIP:
  `acceptance-artifacts/9bbf972/CATalyst-9bbf972-secondary-integration.zip`
- ZIP SHA-256:
  `0DD2CF7D0631C6F4E595314E7F0ABF6E77094B851E32E3A474D705DF4BFFDB4C`
- The ZIP was extracted into a new directory. The extracted executable hash was
  exactly the source build hash above.
- Packaged API smoke: passed for both the build directory and independently
  extracted ZIP.
- Packaged mock Sage RPC worker smoke: passed.
- Packaged interrupted-publication upgrade/recovery smoke: passed.
- Native isolated-profile clean launch: passed, v1.4.0 health endpoint ready.
- Duplicate launch: passed; second PID exited normally with code 0 and did not
  bind a second server or replace the original process.
- Authenticated graceful shutdown: passed; zero `Catalyst` processes remained.
- Persisted-profile relaunch: passed; the immutable completed Coin Prep state
  survived the process boundary.
- The independently built bytes differ from the primary PC's executable hash.
  Both builds are tied to the same exact source SHA; PyInstaller output is not
  treated as reproducible across the two Windows build environments.

## Live Sage read-only recovery

No economic wallet mutation or fee spend was made during this combined-candidate
verification.

- Network: Chia mainnet.
- Sage version: 0.13.0, minimum requirement 0.12.9, supported and healthy.
- Wallet label: `Harvestr test wallet`.
- Fingerprint: `3702373391`.
- CAT wallet ID: 2.
- Pair/ticker: MZ/XCH, `MZ_XCH`.
- Asset: Monkeyzoo Token (MZ).
- Asset ID:
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
- Refreshed balances: `240.800786441412 XCH` and `3,381,521.720 MZ`.
- Offers: zero buy and zero sell.
- Locks: zero XCH and zero CAT.
- Runtime errors: zero; runtime safety allowed; zero blocking operations,
  reservations, prepared creations, publication claims or submitted cancels.
- Recovered Coin Prep: `complete=true`, `previously_complete=true`, phase
  `complete`, 258/56 XCH coins and 129/6 CAT coins.
- Approval:
  `989a638875baf1a9c6d39e34a063e44ce5173a192f1dd1a55ca1965059b1a121`.
- Approval state: `complete`; `session_completed=true`; zero held, committed and
  spent fee mojos; zero unresolved operations.
- Manual configured fee remained `0.0000130791 XCH`. Read-only fee status also
  returned a fresh Coinset suggestion of `0.000007473753 XCH` for the 120-second
  target; no approval or spend was created from that estimate.
- Persisted relaunch repeated the exact completed-state recovery with zero
  offers, locks, fee holds, unresolved operations or runtime errors.

## Safety and external blockers

- Market confidence remained RED and correctly prohibited creation, exposure
  increase and requote. The loaded snapshot included
  `out_of_range_depth_excluded`, `insufficient_ask_depth`,
  `single_provider_dependency`, `confidence_snapshot_expired` and
  `market_evidence_expired`. No confidence gate was bypassed.
- Live offer create/requote/remake was therefore not repeated on the integrated
  candidate. Earlier authorized live acceptance already exercised Coin Prep,
  bot start/stop and Cancel All; this combined pass was deliberately read-only.
- Windows computer-control initialization failed twice before any UI action with
  `failed to write kernel assets: The system cannot find the path specified.
  (os error 3)`. Browser E2E, packaged API and native process smokes continued.
  This is recorded as an external automation-tool blocker, not a CATalyst
  product failure.

## Verdict

The integrated production candidate at exact SHA `9bbf972a9e8b0b6459e67f483080dc487993a7ca`
passes the independently repeatable backend, Chromium, static, Windows build,
package, duplicate-launch, persisted-restart and live Sage read-only recovery
gates. Remaining live publication work is legitimately blocked by RED market
confidence. No new CATalyst defect was found in this combined verification.
