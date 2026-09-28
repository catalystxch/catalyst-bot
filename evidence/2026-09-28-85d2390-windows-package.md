# Windows package checkpoint for source 85d2390 — 28 September 2026

## Exact candidate

Source commit `85d23909bdc436add66671249904e1a4777cbb8f` is pushed on
`codex/coin-prep-fee-approval` in draft PR #220. The Windows package was
built from a fresh detached checkout at
`C:\catalyst\.superpowers\public-ready-85d2390` around 11:50 UTC. Build
metadata synchronized to 1.4.0 and changed only `_version.py` line endings;
its semantic diff was empty and the detached checkout was restored clean.
The source ancestry contains integrated fixes `922ae5b` and `54f5f33`
corresponding to the closed, unmerged PRs #221 and #222; their implementation
is present in this candidate.

| Artifact | Location | SHA-256 | Bytes |
| --- | --- | --- | ---: |
| EXE | `C:\catalyst\.superpowers\public-ready-85d2390\dist\Catalyst\Catalyst.exe` | `966EA2EB49E762FBAC7F8FEFBBDD9A56CAA4BEFDE3690F8C133CA17CC4D7C1B7` | 11,247,841 |
| ZIP | `C:\catalyst\.superpowers\public-ready-85d2390\CATalyst-85d2390-public-ready.zip` | `20E13F5469D6E0C0E4D7E94ACB58AABDAD0BB7587190916F04A13ED3650EC84B` | 37,309,270 |
| Test installer | `C:\catalyst\.superpowers\public-ready-85d2390\Output\Catalyst-Setup-1.4.0.exe` | `A9A36BB5CA0D1585CD1B10A78AAE407D51B908E64C72EEF5487D4B89FBF657E3` | 38,365,800 |

The ZIP has 206 entries; it contains no `.env`, SQLite database, log or Coin
Prep runtime-state file. The extracted EXE hash equals the built EXE hash.
EXE and installer identify version 1.4.0. The installer is unsigned, consistent
with the repository's explicitly labelled unsigned-beta policy. Neither ZIP
nor installer has been uploaded or released.

## Automated and package acceptance

- Five focused Chromium UI regressions passed after first failing against
  their corresponding old behavior. The full Chromium suite passed **170
  tests in 92.55 seconds**. Ruff check passed repository-wide, format check
  passed all **479 tracked Python files**, and `git diff --check` passed.
- The complete serial Python suite passed **7,062 tests, skipped 171, and
  passed 422 subtests in 1125.60 seconds** with exit code zero. Its full log is
  `.tmp-public-readiness-85d2390-pytest.log` in the branch worktree.
  The five additional skips versus the prior candidate are the new opt-in
  browser regressions; they passed in the separate Chromium run above.
- All draft PR #220 checks were green for exact head `85d2390`, including
  unit-tests, lint, CodeQL, Semgrep, Gitleaks and security-scan.
  After the evidence-only head advanced to `27e12d1`, all PR checks passed
  again. Runtime and source files remain byte-identical to `85d2390` across
  those evidence commits. Earlier automated PR review comments reference
  older revisions; current CodeQL and security checks pass. Final code review
  remains a separate gate.
- Packaged API, synthetic Sage RPC, interrupted-publication/upgrade recovery,
  and native clean/duplicate/persisted/safety launch smokes passed. API smoke
  passed again from the extracted ZIP.
- Inno Setup 6.7.3 compiled the test installer. It performed a clean
  current-user installation in an isolated directory with the exact EXE
  hash and correct 1.4.0 registration; native smoke passed from the installed
  path. An installer built from the prior `d048f44` package then replaced the
  isolated installation with the exact old EXE hash; this candidate's
  installer restored the exact new EXE hash and native smoke passed again.
  Uninstall removed the isolated executable and registration. This proves
  same-version replacement/rollback mechanics, not a version-number upgrade
  or actual website download.
- An installer copy marked with Internet-origin ZoneId=3 retained the exact
  installer hash. Microsoft Defender custom scan completed with zero
  detections. This simulates download provenance; it is not an actual browser
  download from an official release.

Build, package, installation and recovery logs remain in the detached checkout
as `public-readiness-build.log` and `.tmp-*.log` files.

## Preserved prior live process

At 11:56:44 UTC the original primary `d048f44` process was rediscovered as
PID 19568 at its exact package path and expected SHA-256
`C200D870F3849A8D8D5E3541F5FBED5C7E36B95C5AD42A967DBCF4CF824CC200`.
Its bot was still running, Sage was reachable and synced with zero consecutive
failures, and the campaign remained bound to mainnet fingerprint 736588221,
CAT wallet 2 and exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
Sage and CATalyst agreed on three open buys and three open sells, with no
wallet-only, stale, duplicate-coin or reserve-backed offers. Runtime safety
was allowed with every blocker count zero. No wallet mutation was performed
during this read-only checkpoint. This is old-candidate stability evidence,
not acceptance of the `85d2390` runtime.

The old package's later status readback showed 138.471039414354 XCH and
780212.284 MZ total, 138.381039414354 XCH and 779012.284 MZ spendable,
with saved reserves 13.847 XCH and 78021 MZ. These are display-level wallet
readbacks, not new immutable campaign approvals.
At 12:16 UTC the old bot had completed 230 loops with zero reported errors,
three historical fills and the same three-buy/three-sell book.
At 12:23 UTC, the exact old executable was still PID 19568. Its status showed
235 completed loops, zero errors, a healthy Chia connection, three buys and
three sells, and the exact MZ asset. The Bootstrap status API still bound the
active campaign to mainnet, Sage fingerprint 736588221, wallet 2, and revision
0, with expiry `2026-09-28T14:53:02.170881Z`. Coin Prep reported complete and
fee approval version 3: 561,860,690 mojos total, 60,190,086 spent, zero held,
501,670,604 remaining, six confirmed operations and zero unresolved. The
`fee_resume_required` flag is the expected protection against an unapproved
post-completion Coin Prep resume for this live campaign.

At a later read-only offer check all six prior-package offers remained active
and exactly discovered on Dexie. Splash discovery remained pending for all
six despite local submission acknowledgments. The old UI still uses its
incorrect `Splash succeeded` wording; the corrected `85d2390` presentation
must be observed from the new package before that live UI gate can pass.

## Unfinished gates

At this checkpoint the secondary PC is independently building and testing this exact
commit. The primary live process and secondary monitored process remain on
the previous exact `d048f44` package; neither has been replaced for this
checkpoint. The original 24-hour windows, new-candidate live lifecycle and
stability, wallet fee/accounting recovery, independent acceptance, official
download/update path and final review remain open. No merge, tag, upload or
release occurred.

A primary attempt to launch an additional persistent, isolated packaged UI
process for the prior checkpoint was rejected by automatic command approval
review with only "blocked by policy" given as the reason. This candidate was
exercised by the short-lived native smokes above; interactive packaged
startup/focus review is assigned to the secondary PC and remains pending for
this exact candidate.
