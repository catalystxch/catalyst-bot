# Sage interruption and coin-watcher recovery — 28 September 2026

## Live observation

The primary `d048f44` package (PID 19568, EXE SHA-256
`C200D870F3849A8D8D5E3541F5FBED5C7E36B95C5AD42A967DBCF4CF824CC200`)
encountered a Sage RPC interruption beginning around 12:29 UTC. Requests
first failed to connect, then returned HTTP 401. The health monitor reported
Sage recovered at 12:31:41 UTC after 135 seconds of unhealthy status. The
runtime log is `%APPDATA%\Catalyst\bot_superlog_20260927_223345.log`.

During the interruption, the market-confidence safety path repeatedly tried
to withdraw the six active offers. Cancellation failed closed with
`FEE_WALLET_IDENTITY_UNAVAILABLE` and then
`FEE_PREP_FUNDING_INSUFFICIENT`; the log includes critical
`market_refresh_failure_withdrawal_failed` events. These are a failed clean
24-hour stability result for the old package. The cause of the Sage RPC
interruption itself is not established by CATalyst's log, and no claim is made
that CATalyst caused it.

The coin watcher then received a successful but empty `get_coins(selectable)`
response for both wallets (`total=0`) while surrounding Sage calls still
returned 401. At 12:31:35-36 it logged 312 XCH and CAT coins as `GONE`.
At 12:32:06, after Sage recovered, it logged 312 coins as `NEW`.
Balances did not show a corresponding wallet drain. The bot's later wallet
sync still showed three buys and three sells. Coin-watcher events are read-only,
but the false event flood obscured the critical errors in the recent-log UI.

Post-recovery readback: the old bot remained running at 258 completed loops
with three buys and three sells; Sage was reachable and synced. The immutable
fee approval remained at 561,860,690 mojos total, 60,190,086 spent, zero held,
and zero unresolved operations. Five free XCH coins were still durably
designated for the fee reserve, each 1,000,000,000 mojos. Runtime safety was
allowed and Doctor passed all ten checks. These readbacks do not prove that
the interruption was harmless at every instant; the failed protective
cancellation remains an acceptance failure requiring investigation.

## Reproduction and root cause of the false coin events

`BotLoop._is_coin_watcher_snapshot_reliable()` rejected explicit RPC errors
and a stale-cycle flag but accepted `success=True` with empty coin lists.
Its subsequent comparison treated the empty response as an authoritative
wallet snapshot and emitted the mass `GONE` events. The successful but empty
Sage response amid 401s is recorded immediately before those events in the
live log. No wallet mutation is needed to reproduce the bug.

The new focused regression in `tests/test_bot_loop_recovery_mode.py` sets a
live XCH/CAT baseline, supplies successful empty RPC responses for both
wallets, and asserts that the baseline and event stream remain intact. It
failed before the fix because the reliability check returned `True`; after
the fix it passed. A second red/green case covers one empty wallet while the
other has recovered. The correction rejects an empty response from either
wallet when the established baseline contains its wallet coins. An initial
empty baseline remains allowed. Four focused coin-watcher tests passed; the
90-test affected backend run passed before the one-wallet case was added and
will be rerun for the final source. Full verification and a fresh
Windows build are in progress for the resulting source identity.

## Protected cancellation fee-input exhaustion

The cancellation failures have a different immediate cause: during the Sage
interruption, wallet identity and exact fee inputs could not be verified, so
the protected cancellation path refused to dispatch. The log shows five
`FEE_WALLET_IDENTITY_UNAVAILABLE` failures from 12:29:24 through 12:30:00,
followed by `FEE_PREP_FUNDING_INSUFFICIENT` at 12:30:05. The durable database
still held five free, 1,000,000,000-mojo fee-reserve coins after recovery and
the approval had no new spend or hold. This ruled out an exhausted durable
approval or wallet fee balance as the cause of the later error.

`OfferManager._plan_coin_prep_cancel()` reserved a fee coin before the
read-only pricing call, which rechecked Sage identity. On identity failure the
method raised without returning that unspent coin to `FeeCoinPool`. Repeated
failures consumed the five in-memory reservations until the next pool refresh.
The new regression uses a real one-coin pool and makes pricing raise
`FEE_WALLET_IDENTITY_UNAVAILABLE` twice. Before the fix, the first attempt
left zero available fee coins and the second would fail with the misleading
funding error. After the fix, both attempts preserve the original identity
error and the unspent coin remains available.

The correction adds a ticket to protected cancellation fee reservations and
releases only that ticket if read-only pricing or plan validation fails.
Ticket identity prevents a stale failure from releasing a newer reservation
for the same coin after a concurrent pool refresh. A separate red/green
regression covers that race. Successful plans retain their reservation, and
all durable fee, campaign, and wallet dispatch gates remain unchanged.

A further review found that a successful read-only plan could reserve the fee
coin and then fail while acquiring cancellation authority or preparing the
durable journal, still before any wallet dispatch. A new regression seeded a
real disposable offer journal, made pricing succeed, then made authority
acquisition fail. Before the additional correction, the pool showed zero
available coins; after it, the original coin was available. The planning
method now returns its reservation ticket to the caller. The outer
cancellation boundary releases it on every exit before the batch dispatcher
starts, including authority/journal failure or idempotent replay. Once the
dispatcher starts, it retains the reservation because the wallet effect may
be submitted or ambiguous. The focused failure and four existing successful
dispatch cases passed together.

## Verification in progress

The final-source combined affected backend suite passed **218 tests** in
134.16 seconds. The final-source complete Chromium suite passed **170 tests**
in 101.72 seconds. Ruff check passed repository-wide, formatting passed all
479 tracked Python files, and `git diff --check` passed. The first complete
serial Python run was interrupted after discovering the additional leak; the
final-source complete serial Python suite passed **7,067 tests**, skipped
**171**, and passed **422 subtests** in 1,329.03 seconds with exit code zero.
An earlier ordering of those tests exposed an independent test-isolation
problem: `test_bootstrap_cancel_fee_budget.py` imported a different `database`
and `offer_manager` module instance from the ones used by its imported
disposable SQLite fixture. That ordering failed before the campaign-cap logic
with `no such table: bootstrap_campaigns`. Reproducing with only the two
relevant modules confirmed the distinct database paths. The test now imports
the fixture's module instances; its isolated reproduction and the 217-test
affected run both pass. This change affects test isolation only.

The exact old `d048f44` executable was still running on the primary PC at
13:01 UTC, with its previously recorded SHA-256. Its health endpoint reported
bot running, Sage wallet reachable/synced and zero consecutive health failures.
That post-incident health does not turn the failed stability window into a pass.
The corrected source is not yet represented by that running executable.

The clean Windows build, package smokes, and new-candidate live acceptance
remain pending at this checkpoint. The secondary PC has been
asked to examine its old stability end state and capacity for an independent
new-candidate build. No release or merge gate is marked complete by this note.

The secondary task subsequently reported that its old `d048f44` process was
still alive in a deliberately wallet-blocked isolated profile. Its monitor
recorded hash-matched health snapshots with no newly reported runtime errors
through 11:15 UTC, but `bot_running=false` and
`WALLET_IDENTITY_BINDING_INVALID` were expected throughout. This can support
read-only packaged stability only, and its 24-hour monitor had not reached an
end-state pass at the report. The secondary C: drive had about 1.19 GiB free
and no alternate filesystem drive; it is preserving active worktrees and
evidence while assessing safe space for a new independent build.

In a separate read-only Sage RPC check, the secondary PC found an active
Sage 0.13.0 mainnet test wallet named `Harvestr test wallet`, fingerprint
`3702373391`, with the exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
Sage reported 240,800,786,441,412 selectable XCH mojos and 3,381,521,720
selectable MZ mojos (3,381,521.720 MZ at precision 3). These are availability
observations only. CATalyst's synthetic CAT wallet ID, profile identity,
reserves, a bounded campaign, and fee scope must be verified on the corrected
package before any secondary live action. No wallet selection or mutation was
performed during this discovery.

## First corrected source/package checkpoint, superseded by review cleanup

Commit `c5c321804380c837dccd1f3be748c6fe96c3c1d3` was pushed to draft
PR #220 after the 7,067-test full Python pass, 170-test Chromium pass, Ruff,
and the 218-test affected pass above. A clean detached checkout built the
Windows EXE. Build metadata synchronized to 1.4.0 and changed only
`_version.py` line endings; its semantic diff was empty, and the checkout was
restored clean. The only PyInstaller warning was the previously accepted
optional `importlib_resources.trees` hidden import warning.

| Artifact | SHA-256 | Bytes |
| --- | --- | ---: |
| `C:\catalyst\.superpowers\public-ready-c5c3218\dist\Catalyst\Catalyst.exe` | `DFF98FC93433403FC6C919CFC910EE1CD30C3DB8F1BC6B373B8590C642554BBC` | 11,249,100 |
| `C:\catalyst\.superpowers\public-ready-c5c3218\CATalyst-c5c3218-public-ready.zip` | `58BF07D48A635AC84FB29685BF90F2D3662AD1A930578D4884903A6F07B702F9` | 37,310,444 |
| `C:\catalyst\.superpowers\public-ready-c5c3218\Output\Catalyst-Setup-1.4.0.exe` | `6738BC78B2B06DF69E53A6A14BDBFAE1278F787F7A3FE2D89300B98109465F37` | 38,366,173 |

The ZIP had 206 entries, contained the environment template and no runtime
`.env`, database or log, and its extracted EXE hash matched the built EXE.
Packaged API, synthetic Sage RPC, interrupted-publication recovery, and
native clean/duplicate/persisted/safety smokes passed. The unsigned test
installer completed a clean current-user installation in an isolated
worktree directory, registered version 1.4.0.0, and installed the exact EXE
hash; native smoke passed from the installed path. Replacing it with the old
`d048f44` installer produced the exact old EXE hash. Installing the
`c5c3218` installer again restored its exact new EXE hash, and native smoke
passed again. Uninstall removed the isolated EXE and registration. The tests
did not operate the primary live wallet or alter its old running package.

The secondary PC independently fetched exact `c5c3218` into a clean detached
worktree, reviewed the full incident diff, passed 303 focused/affected
backend tests and `git diff --check`, and found no blocking defect. It found
two stale descriptions: `_plan_coin_prep_cancel()` still annotated a two-item
return although it now returns three, and `FeeCoinPool` still documented that
no explicit release occurs. Both were confirmed and corrected in the next
source revision. They are documentation/type-hint changes, but the exact
source identity changes. The `c5c3218` package and its test receipts above
are retained as historical evidence, not final new-candidate acceptance.

The follow-up source changed only those two descriptions: the planner's
three-item return annotation and the fee pool's pre-dispatch ticket lifecycle
docstring. The complete serial Python suite passed again on that source:
**7,067 passed, 171 skipped, 422 subtests passed in 1,214.30 seconds**. The
complete Chromium suite passed **170 tests in 94.07 seconds**; Ruff and format
checks passed all **480 tracked Python files**, and `git diff --check` passed.
Its exact source commit and fresh package hashes are recorded in the next
checkpoint after building; the `c5c3218` artifacts above are not reused as
that final source's package.

## Exact corrected candidate and package checkpoint

The corrected source commit is
`8beb3a9068dce8709d670e06ee4605f526315e28`. A clean detached checkout
at `C:\catalyst\.superpowers\public-ready-8beb3a9` built the Windows
package. Build-generated `_version.py` line endings were restored; the
checkout has no semantic source diff. PyInstaller reported only the accepted
optional `importlib_resources.trees` hidden import warning.

| Artifact | SHA-256 | Bytes |
| --- | --- | ---: |
| `C:\catalyst\.superpowers\public-ready-8beb3a9\dist\Catalyst\Catalyst.exe` | `BEB72BE54D81ABD2FC863D065995C533353C1F1F815253232E9399578831A834` | 11,249,146 |
| `C:\catalyst\.superpowers\public-ready-8beb3a9\CATalyst-8beb3a9-secondary-acceptance.zip` | `C6675C8CCE53C1EF116280E244F6D11F0265AA4ED7D2E0EF8ACA7968EF8BE4B4` | 37,310,717 |
| `C:\catalyst\.superpowers\public-ready-8beb3a9\Output\Catalyst-Setup-1.4.0.exe` | `C79CF5E736DD53C3FB780776DE70DB22BA756C9DF88BC46AB3A50B0ADA0F01FE` | 38,366,613 |

The ZIP contains 206 entries, including the environment template and no
runtime `.env`, database or log. Its extracted EXE hash matched the built
EXE. Packaged API, synthetic Sage RPC, upgrade/publication recovery, and
native clean/duplicate/persisted/safety smokes passed. The unsigned test
installer completed an isolated current-user clean install, registered
version 1.4.0.0 and installed the exact EXE hash; native smoke passed. An
old `d048f44` installer installed the exact old EXE, and the new installer
restored the exact `8beb3a9` EXE with a second native smoke pass. The
isolated installation was uninstalled cleanly. PR #220 CI checks for
`8beb3a9` all passed, including unit, lint, security, CodeQL and analysis.

The acceptance ZIP and SHA-256 sidecar were committed and pushed on the
separate `codex/coin-prep-fee-approval-artifacts` branch at
`c826439e7017e9b1d2e8e24be360c909e5565a2c`. The secondary PC downloaded
the ZIP and independently matched the ZIP and extracted EXE hashes above.
It passed packaged API, synthetic Sage RPC, upgrade/publication recovery,
and native clean/duplicate/persisted/safety smokes. In a separate isolated
read-only package launch, it verified mainnet Sage fingerprint `3702373391`,
the exact MZ asset ID and CATalyst CAT wallet ID 2. Safety reported allowed
with no blockers; Doctor reported eight passes and one warning for an
unconfigured Spacescan API key. The secondary package UI rendered the
dashboard, offers, P&L, Market Intel, Settings, Logs, Data Reset, Help,
About and Doctor with no browser console errors. No secondary wallet
transaction or campaign activation occurred. The secondary old `d048f44`
wallet-blocked monitor remains separate; it cannot count as new-candidate
live acceptance.

## Primary package swap and live acceptance state

At approximately 14:29 UTC, the exact old `d048f44` primary executable was
stopped through the authenticated CATalyst UI and shut down. The shutdown
dialog showed six active offers and `Cancel all offers` unchecked. It
reported that the six offers remained live. PID 19568 then exited and port
5000 became free. The exact new EXE above started as PID 122184 at about
14:30 UTC under the existing primary profile; it now owns `127.0.0.1:5000`.

Read-only API calls from the new process reported the existing campaign
`aaf64855aef9e1919d7cdfd4b15c1f589e7acf9321d71787b0b8122df9e16405`
at revision 0, mainnet Sage fingerprint 736588221, CAT wallet ID 2 and
exact MZ asset. Corridor, budgets, deployment and expiry are unchanged:
0.0000375–0.00015 XCH/MZ, 0.9 XCH / 12,000 MZ, 0.001 XCH fee budget,
10% deployed, expiry `2026-09-28T14:53:02.170881Z`. The offer API shows
three active buys and three active sells using six distinct coins, matching
the database open count. `/api/safety/status` reports allowed with no
blocking operations, reservations, publication claims, submitted cancels or
contradictory history. The existing fee approval is 561,860,690 mojos total,
60,190,086 spent, zero held and 501,670,604 remaining; six operations are
confirmed, with no unresolved operation.

The new process was stopped at this checkpoint. Its fresh browser session
showed the Risk Disclosure before wallet connection; CATalyst's read-only
`/api/fingerprint` and Sage startup status remained `not_started`/`idle`.
Consequently the read-only counts and durable safety gate do **not** yet
prove a freshly connected, synced wallet or a resumed live bot. The primary
new-candidate 24-hour stability window and full lifecycle are unfinished.
The old primary window remains a failure due to the Sage outage and false
coin snapshots. The existing campaign expiry prevents assuming a new
24-hour window under the same authorization. PR #220 stays draft; no main
merge, tag, or release is justified by these checks.

## Later frontend and Doctor corrections: source `7ca6fa8`

The primary live UI displayed `1h remaining` during the final minutes of
the approved campaign. `_bootstrapRenderStatus` rounded any positive
fraction of an hour up to a whole hour. A new Chromium regression reproduced
`1h remaining` at exactly 14 minutes before expiry; after the fix it shows
`14m remaining`. The affected `test_smoke.py` file passed 68 Chromium tests.
This source change supersedes the `8beb3a9` package as a final candidate.

The secondary PC independently found that Doctor could report the configured
CAT as `found in wallet` during a synthetic Sage RPC outage. The CAT mapping
check independently consulted Sage's configured fallback wallet metadata
instead of observing the failed wallet reachability result. Secondary commit
`1f7c01a22467c5470fc33220ad56dbbd18265a60` added a red/green test and
made Doctor skip the mapping check when the wallet is unreachable; the
primary reviewed and cherry-picked it as
`7ca6fa857f28083e2f34138fa75e4728621e6497`. The primary Doctor module
passed 14 tests and Ruff; the secondary reported the same focused pass and
its independent read-only synthetic outage reproduction. Secondary PR #227
is superseded by this integration and remains separate from draft PR #220.

The exact `7ca6fa8` source built successfully from a clean detached checkout
at `C:\catalyst\.superpowers\public-ready-7ca6fa8`. Only generated
`_version.py` line endings changed during build; they were restored, leaving
the source checkout clean. The package API, synthetic Sage RPC,
upgrade/publication recovery, native clean/duplicate/persisted/safety
smokes passed. A new unsigned 1.4.0 installer installed the exact EXE in an
isolated current-user location; native smoke passed there. The old
`d048f44` installer replaced it with the exact old EXE hash, and the new
installer restored the exact new hash, followed by another native smoke
pass. The isolated install was uninstalled and its registration removed.
The complete Chromium suite passed **171 tests in 107.51 seconds**; the
complete final-source Python suite and PR CI were still running at this
checkpoint. Ruff check and format verification passed all 480 tracked
Python files.

| Artifact | SHA-256 | Bytes |
| --- | --- | ---: |
| `C:\catalyst\.superpowers\public-ready-7ca6fa8\dist\Catalyst\Catalyst.exe` | `CFE177F4CD8265878829C2A6F4056722F0DCC78C9F5A47B8A02BE3D4040F898A` | 11,249,233 |
| `C:\catalyst\.superpowers\public-ready-7ca6fa8\CATalyst-7ca6fa8-secondary-acceptance.zip` | `4E83EC8941335451E2C7072CC777A3D9CF837B7ACAB80DCBA613ABEEBA647AE6` | 36,441,838 |
| `C:\catalyst\.superpowers\public-ready-7ca6fa8\Output\Catalyst-Setup-1.4.0.exe` | `EB93F9D5DF937CB4C1B34FC27412113D66843C57F22DF02FF577C3338D9958CE` | 38,368,273 |

The ZIP contains 192 files, including `.env.example`, and no runtime
`.env`, database or log. The ZIP's EXE hash matches the built EXE. It was
committed and pushed, with a SHA-256 sidecar, on the acceptance-artifact
branch at `9856190eb850399a34f25871e6c9d496f268af16`; the secondary PC
has been assigned independent verification of that exact artifact. An
initial Inno invocation omitted the 1.4.0 version define and produced an
unrelated `Catalyst-Setup-1.0.0.exe` in this isolated build worktree. The
correct 1.4.0 installer above was then built and tested. Automatic approval
review blocked deletion of the extra generated 1.0.0 file with the stated
reason `blocked by policy`; it remains outside the acceptance ZIP and is
not an accepted installer artifact.

At `2026-09-28T14:53:18Z`, after the existing campaign's approved
`2026-09-28T14:53:02Z` end time, the stopped primary `8beb3a9` process still
reported the campaign's durable status as `active` and six live offers via
read-only APIs. The bot had been stopped for the package swap, so those
offers were unmanaged. This is a failed live end-state gate requiring
operator cancellation/renewal decisions and investigation of idle expiry
behavior. It does not establish a new-candidate trading window. The
secondary PC was assigned independent source investigation without wallet
effects. The fresh `7ca6fa8` EXE has not replaced the stopped primary
process or been used with the primary wallet at this checkpoint.

## Expired campaign guard and exact `8e89558` package

The secondary PC reproduced the stopped-bot expiry gap and submitted PR #228.
Primary review integrated its final six-file patch as
`8e89558871d8cdba0206304ae02a0f98b2c8b87f`; PR #228 was then closed
as superseded. The status API now labels an active but elapsed campaign
`expired` and `cancel_required`, reports campaign-owned open offer count,
and preserves the durable active authority until protected cancellation.
The frontend shows cancellation required and disables Start Bot. The backend
independently rejects Start Bot for the matching expired campaign before
`bot.start()` is called. Neither GET nor start preflight submits cancels.

Focused Bootstrap, lifecycle, and Doctor tests passed **109** on the
integrated source. Ruff passed the repository Python check. The complete
Chromium suite passed **172 tests in 108.87 seconds**. The full serial Python
suite and new PR CI were still running at this checkpoint.
PR #220 CI subsequently passed all checks on exact head `8e89558`; its
`unit-tests` job reported **7,056 passed, 187 skipped, four warnings in
553.39 seconds** on the CI runner. The duplicate local Windows serial Python
run was stopped intentionally after reaching 42%, because the complete
exact-source CI suite, focused Windows backend suite, complete Windows
Chromium suite, and package checks had passed. No complete local Windows
Python result is claimed for `8e89558`.
The complete Windows Python suite was then rerun with two file-distributed
workers on the same exact source. It passed **7,070 tests, skipped 173, and
passed 422 subtests in 641.61 seconds**. PR CI also passed all checks on the
evidence-only head `4458af0`; its unit-test job again passed 7,056 tests,
skipped 187 and reported four warnings (703.98 seconds). The differing
platform totals are recorded separately rather than combined.

A clean detached checkout at
`C:\catalyst\.superpowers\public-ready-8e89558` built exact source
`8e89558`. Generated `_version.py` line endings were restored; the tracked
checkout is clean. The ZIP has 192 entries, includes `.env.example`, excludes
runtime `.env`/database/log files, passes `testzip()`, and contains the exact
built executable. The package API, synthetic Sage RPC, upgrade/publication
recovery, and native clean/duplicate/persisted/safety smokes passed. The
1.4.0 unsigned installer installed the exact executable to an isolated
current-user location (hash and version matched), the native smoke passed
from that install, and the uninstaller removed the isolated executable and
registration.
The isolated installer update path also passed: old `d048f44` install
(`C200D870...` EXE), new `8e89558` replacement (`A08D5D95...`), old
rollback, and new restore each produced the expected complete EXE SHA-256.
The final uninstaller again removed the isolated executable and registration.

| Artifact | SHA-256 | Bytes |
| --- | --- | ---: |
| `C:\catalyst\.superpowers\public-ready-8e89558\dist\Catalyst\Catalyst.exe` | `A08D5D958519E5A3DD5575CB442500DF05DE52A66CC7022661225E5598544FE7` | 11,250,960 |
| `C:\catalyst\.superpowers\public-ready-8e89558\CATalyst-8e89558-secondary-acceptance.zip` | `C1D08667F12EF5293542667D1458AD4E9637EFC81662851EEBC2B7A8A1C2DC15` | 36,441,777 |
| `C:\catalyst\.superpowers\public-ready-8e89558\Output\Catalyst-Setup-1.4.0.exe` | `D4BE7443EEAA952F3BEA821A566CC44257A61D1C75D3715D0D63E7A3603E8ED9` | 38,367,980 |

The ZIP and SHA-256 sidecar were committed to the acceptance-artifact
branch as `819456d`; the raw ZIP endpoint returned HTTP 200 with content
length 36,441,777. Exact hashes and URL were sent to the secondary PC for
independent acceptance. The primary live process still runs the older
`8beb3a9` package with the bot stopped. At 15:16 UTC, read-only APIs still
reported the expired campaign as durable `active` and six open offers.
No `8e89558` live wallet action or new-candidate 24-hour window has occurred.
At 15:36 UTC a fresh read-only `/api/offers/diagnostic` compared Sage's live
book with the database: three wallet buys and three wallet sells matched
three DB buys and three DB sells. It reported no wallet-only or stale DB
offers, no duplicated offer coins, no reserve-backed offers, no wallet error,
and `local_book_consistent=true`. The six offers are therefore a confirmed
live exposure after campaign expiry, rather than merely stale DB rows.

### Secondary PC exact-package acceptance

The independent secondary task on the connected Windows PC verified the
`8e89558` acceptance ZIP SHA-256
`C1D08667F12EF5293542667D1458AD4E9637EFC81662851EEBC2B7A8A1C2DC15`
and extracted EXE SHA-256
`A08D5D958519E5A3DD5575CB442500DF05DE52A66CC7022661225E5598544FE7`.
Its exact-package API, synthetic Sage RPC worker, upgrade/publication
recovery, and clean/duplicate/persisted/native safety smokes passed. It also
reported 48 focused source regressions, two Chromium Bootstrap/start-gate
checks, 104 broader Bootstrap tests, and affected-file Ruff passing.

The secondary launched the package from a clean isolated profile as PID
13492 and started a read-only monitor as PID 24400. Its first sample reported
the process alive, bot stopped, no active offers, and Doctor `can_start=true`
with eight passes and warnings for unreachable Splash and an unset Spacescan
Pro key. Sage identity was mainnet, fingerprint 3702373391, CAT wallet ID 2,
and the exact MZ asset. Smart Defaults returned RED/409
`BOOTSTRAP_SUGGESTED`; fee preview was available with suggested maximum
0.003224347212 XCH and `dispatch_authorized=false`. No fee approval,
Coin Prep, bot start, offer mutation, or new campaign occurred. The monitor
log is at
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\outputs\8e89558-clean-live-profile-20260928-162641\monitor-8e89558-readonly.jsonl`.
Its original AppData profile was preserved. A recursive backup of older
nested artifacts initially filled the disk; the secondary recovered space
from failed-copy files only and reported approximately 954 MB free. Its
final `8e89558` package remains a read-only acceptance monitor, not a
24-hour live trading pass. Secondary live lifecycle, installer/update,
interactive UI and 24-hour end state remain unverified.
