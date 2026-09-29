# Protected cancellation fee coin retry: candidate `bf1abe2`

## Defect and correction

In the protected Sage Cancel All path, a fee coin could be reserved in the
process before the approved cancellation fee reservation or recheck denied
dispatch. The wallet was not called and every cohort member was recorded as
`CANCEL_FAILED`, but the in-memory fee coin ticket remained reserved. When it
was the only eligible fee coin, an immediate safe retry reported
`FEE_PREP_FUNDING_INSUFFICIENT` until a pool refresh or process restart.

Commit `bf1abe2146a3982ceb49b190ebbd877932cd8e4c` releases that exact
ticket only after every member is durably finalized as
`cohort_recovery_unattempted` with `_catalyst_effect_attempted=False`. The
fee outcome is recorded before release on the recheck-denial path. Submitted,
ambiguous, and incomplete outcomes retain their reservation and reconciliation
requirements. A focused regression test first reproduced the leak against the
parent commit, then passed for both fee reservation and recheck denials after
the correction.

## Exact Windows package

Built in clean detached checkout
`C:\catalyst\.superpowers\public-ready-bf1abe2` at the commit above. The
package contains no profile `.env`. Both Windows version resources identify
version 1.4.0. These are unsigned acceptance artifacts, not a public release.

| Artifact | SHA-256 | Bytes |
|---|---|---:|
| `dist\Catalyst\Catalyst.exe` | `EC967C8A39FED50F59C0DBC81E93D153AD82A58D7D093FCDE9161AA53E6A9247` | 11,252,534 |
| `Output\CATalyst-bf1abe2-secondary-acceptance.zip` | `14A112882636662CD10E7E8CB971DCBF16591587499018D78A5BF280337D9878` | 36,448,136 |
| `Output\Catalyst-Setup-1.4.0.exe` | `97459AEF3AFD59FE0FCDE81CF8B9D408027832793E27E8A13F65BEA8FA8012B0` | 38,370,768 |

The ZIP contains 192 files under `Catalyst/`, passed CRC verification, and
contains the exact EXE hash above. The Inno Setup compiler completed the
installer with 1.4.0 metadata. The artifacts and SHA-256 sidecars are on the
separate `codex/coin-prep-fee-approval-artifacts` branch at `03096ab`, for
independent acceptance on the secondary PC.

## Completed checks

- Focused cancellation and fee coin recovery tests: 126 passed.
- Complete local Windows Python suite: 7,075 passed, 173 skipped and 422
  subtests passed in 1,120.17 seconds against the final `bf1abe2` source.
- Chromium end-to-end suite with `--e2e`: 172 passed in 94.17 seconds.
- Ruff check and format check on the two changed files, and `git diff --check`:
  passed.
- Clean Windows PyInstaller build: passed.
- Package API, synthetic Sage RPC worker, upgrade/publication recovery, and
  native clean/duplicate/persisted/safety smokes: passed with isolated profiles.
- The exact unsigned installer completed a current-user clean install in
  `C:\catalyst\.superpowers\installer-bf1abe2-test`. The installed EXE hash,
  registry version and path matched. Installed API and native smokes passed.
  The previous `a9cd077` installer replaced it with the verified prior EXE
  hash; installing `bf1abe2` again restored the exact new hash and the API
  smoke passed. Final uninstall removed the EXE and current-user registration.
  The pre-test machine had no CATalyst current-user installer registration.
- Microsoft Defender real-time protection was enabled with signature version
  1.459.447.0. Custom scans of the exact installer and a byte-identical copy
  marked with Internet-origin `ZoneId=3` completed with no matching detection.
- All eleven PR checks passed on exact source head `bf1abe2`, including CI
  unit tests, lint/syntax, security scan, CodeQL, Gitleaks and Semgrep.
- All eleven checks also passed on the later evidence-only head `a21de91`;
  no runtime/source file changed after `bf1abe2`.

## Independent secondary checkpoint

The secondary PC checked out the exact `bf1abe2` commit in a separate
detached worktree and independently verified its parent `528ea5d`, two-file
patch SHA-256 `762683750B90BCDEEE5B7B3FF8EED667005CC7120A020E0F90B843DD82F92064`,
downloaded ZIP and installer hashes, and extracted EXE hash. Its focused new
regression passed both cases; 145 affected tests passed under the package
compatible Python 3.12 runtime. Ruff, format and diff checks passed. The
downloaded package passed API, synthetic Sage RPC, publication/recovery and
native clean/duplicate/persisted/safety smokes. Its independent patch review
found the ticket release limited to the durable no-effect denial paths;
ambiguous or mixed outcomes retain the reservation. The secondary was still
reconciling its older build process at this checkpoint and had made no
`bf1abe2` live wallet effect.

The secondary later reported its complete backend suite in eight
disk-controlled batches: 7,075 passed, one skipped, 422 subtests passed and
zero failures. Its complete Chromium suite passed 172 tests. Whole-repository
Ruff passed; `pip-audit` found no known vulnerabilities in
`requirements.txt`. Bandit reported zero HIGH findings (116 MEDIUM and 595 LOW
existing findings); the changed runtime file had no MEDIUM/HIGH findings or
findings on changed lines. These results are secondary-reported evidence,
separate from the primary full-suite and CI results above.

For a read-only live check, the secondary stopped its superseded process
before launching the exact `bf1abe2` package from a lean copied profile. It
preserved an authoritative backup at
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\authoritative-backups\8e89558-profile-20260929-0414`
with `bot.db` SHA-256
`12FA89CDBD336D66F0B11800730FCBF0A79F5917F3BB3D7BA87442B40C1641C5`.
The actual secondary identity was Sage mainnet, fingerprint 3702373391, CAT
wallet ID 2 and the required MZ asset. The wallet was reachable, synced and
signing. The bot was stopped with zero active offers, locks, unresolved
operations, fee reservations and publication claims. Doctor reported
`can_start=true`, eight passes and two expected warnings (Splash port 4000
unavailable and Spacescan key absent); Dexie was reachable. Coin Prep verify
reported `all_sufficient=true` under persisted inactive settings. Smart
Settings correctly returned RED/INVALID under single-provider dependency,
insufficient ask depth and excluded out-of-range depth. The UI showed Risk
Disclosure, and no console error was observed. The secondary screenshot is
at `C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\outputs\bf1abe2-live-ui-initial.png`.
CATalyst was then stopped on the secondary, with its profile preserved. No
`bf1abe2` live wallet effect was performed.

## Primary live handoff

The old exact `a9cd077` EXE (PID 133984) still had its bot stopped before
handoff. It was shut down through authenticated `/api/shutdown` with
`cancel_offers=false`; the process exited and port 5000 closed. The exact
`bf1abe2` EXE then started against the existing `%APPDATA%\Catalyst` profile
as PID 64944. The running EXE hash matched the table above, `/api/health`
returned version 1.4.0, Sage mode and `bot_running=false`.

Read-only endpoints reported the persisted mainnet Sage identity (fingerprint
736588221, CAT wallet ID 2, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`).
The campaign `aaf64855aef9e1919d7cdfd4b15c1f589e7acf9321d71787b0b8122df9e16405`
remained expired at 2026-09-28T14:53:02.170881Z, with
`cancel_required=true` and six open offers. `/api/offers/diagnostic`
reported three buys and three sells in both Sage and the DB, unique
non-reserve offer coins, no wallet-only or DB-only rows, and
`local_book_consistent=true`. `/api/safety/status` allowed readback with zero
blocking operations, reservations, prepared creations, publication claims,
submitted cancels and contradictory history. `/api/fingerprint` still showed
`not_started`; live wallet connection has not occurred in this session.
`/api/coin-prep/status` read back fee approval
`c6651480f6044dbbd2833926d3809380c248943f7f507991ff132d7e885e6bdc`:
561,860,690 mojos total, 60,190,086 spent, zero held, 501,670,604
remaining, six confirmed operations and zero unresolved. No wallet effect
was initiated during this handoff.

## Remaining acceptance

The new packaged UI still shows Risk Disclosure, and the operator has been
asked to personally acknowledge it and connect Sage. Neither the primary nor
secondary `bf1abe2` live lifecycle and 24-hour stability windows have been
completed. The six open offers require protected cancellation. Computer-use
policy requires user handoff for the consequential wallet transaction, even
with standing test permission. Renewal of the expired campaign requires
separate approval. Draft PR #220 must remain unmerged; no tag or public
release is authorized.
