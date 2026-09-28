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
