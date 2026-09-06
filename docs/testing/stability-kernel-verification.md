# Stability kernel verification

## Status

Task 16 automated regression and local package verification completed on
2026-08-22 (Europe/London) from branch `codex/stability-kernel`, based on
`8ef30efaf196986ca68944f97cbf75a65aed4740` before the Task 16 commit.

Task 17's authorised TEST 7 mainnet acceptance completed on 2026-08-22. The
acceptance used the isolated checkpointed lab and the exact wallet identity
gate described below; it did not use the user's normal CATalyst data directory.

## Safety envelope

Every Python, pytest, build, and packaged-smoke process used a fresh isolated
`CMM_DATA_DIR`. Automated source verification used the synthetic wallet identity
`161616161` / `Task 16 Synthetic Wallet` / `bls` / `mainnet` and pinned Sage to
`https://127.0.0.1:1`. The packaged smoke used its repository-owned synthetic
identity `123456789` / `Packaged Smoke Sage` and a temporary mutual-TLS Sage
server bound only to loopback.

The inherited Task 16 socket guard ran in `loopback_only` fatal mode. Any DNS or
non-loopback socket target terminated the process. All accepted runs recorded
zero external attempts. No live wallet, user database, public API, GitHub, or
manual trading mutation was used.

`tests/test_parallel_offers.py` and the legacy manual
`tests/test_offer_create.py` were explicitly excluded and were never imported,
collected, or run. The repository's existing `conftest.py` exclusions also kept
the other live/manual API scripts out of collection.

## Authorised TEST 7 mainnet acceptance

Every live-effect boundary freshly verified Sage reported `TEST 7`, fingerprint
`736588221`, `mainnet`, BLS keys, and signing enabled. The isolated lab completed
all ten checkpoint stages in order:

| Stage | Durable result |
| --- | --- |
| Inventory | 9 wallets; complete 1,943-record offer history |
| Reconcile | Clean authoritative startup reconciliation |
| Lifecycle | `CANCELLED_PROVEN` |
| Restart | `RESTART_RECOVERED` |
| Stale read | `STALE_READ_FROZEN` before mutation |
| Long gap | `MONOTONIC_GAP_RECOVERED` |
| Replacement | `REPLACEMENT_LINEAGE_PROVEN`, 3 offers over 2 waves |
| Fill | `FILLED_PROVEN`, recovered from the exact confirmed self-take |
| Soak | `SOAK_STABLE`, 3 invariant snapshots |
| Final reconciliation | `FINAL_RECONCILIATION_CLEAN`, 9 lab intents |

The isolated same-wallet fill consumed the exact registered XCH maker input and
the independently verified SBX taker input in one transaction. Sage peers
accepted transaction `dece54534082a2f717273da37c00faa54ff2d75e7d381199d55433fb17d7625f`,
which confirmed at height `9183928`. Sage's normalized transaction row omitted
the transaction ID but supplied deterministic spend identity
`sha256:b751a083fc1c3d8ed64b13cfa42df1f0d066a08c1363b52e451c48b0e1e10e8d`;
the exact selected-input and requested-receipt proof recorded the fill without
weakening offer-absence handling.

Sage 0.12.10 signs every locally owned spend during `take_offer`. Passing the
already signed maker offer back to the same wallet therefore produced a doubled
maker signature and peer `BAD_AGGREGATE_SIGNATURE` rejection. The lab now
preserves the canonical maker coin-spend bytes and compression version while
replacing only the pre-existing aggregate signature with the BLS identity before
the guarded self-take. Exact wire tests cover this transformation. The corrected
transaction received successful mempool acknowledgements and confirmed.

The final wallet snapshot reported all XCH and SBX owned balances as selectable,
no live offer locks, no open local offers, terminal publication state, and zero
blockers in all six safety categories: operations, submitted cancellations,
prepared creations, contradictory history, reservations, and publication
claims. The checkpoint contains bounded redacted evidence only.

## Automated test results

| Gate | Result | Network evidence |
| --- | --- | --- |
| Combined stability-kernel suites | 1,646 passed | 0 external attempts |
| Existing cancellation/lifecycle/wallet/offer/coin-prep/startup/Splash/database slice | 722 passed, 370 subtests passed | 0 external attempts |
| Post-static-cleanup affected slice | 659 passed, 366 subtests passed in 167.56s | 0 external attempts |
| Final order-reproduction and release-fix slice | 159 passed, 15 subtests passed in 9.76s | 0 external attempts |
| Task 16 whole repository, CI file-isolated mode | 5,027 passed, 13 skipped, 413 subtests passed in 335.29s | 226 guard events; 174 loopback; **0 external**; 18 guard loads; 31 guarded child launches |
| Post-acceptance whole repository, CI file-isolated mode | **5,091 passed, 13 skipped, 413 subtests passed in 297.40s** | Repository loopback-only guard remained green |

The post-acceptance whole-repository command completed on 2026-08-22:

```text
python -m pytest tests -q -n 2 --dist=loadfile \
  --ignore=tests/test_parallel_offers.py \
  --ignore=tests/test_offer_create.py
```

The two-worker `loadfile` mode is the repository's CI isolation strategy: each
test file remains within one worker, while module state cannot leak between
unrelated files. An earlier serial run on the final release-fix source reached
`5,026 passed` with one late failure caused by an unisolated
`wallet_sage._CAT_ASSET_ID` test precondition. The test now explicitly isolates
that global; the 159-test reproduction, Task 16's 5,027-test run, and the final
post-acceptance 5,091-test run all pass.

The four final warnings are duplicate xdist reports of two known pytest
collection warnings: helper classes with constructors in `test_coin_prep.py`
and `test_coin_prep_v2.py` are not test classes.

## Quality and security results

- `python -m ruff check .` — passed.
- CI-configured Vulture scan — passed:
  `python -m vulture src/catalyst scripts desktop_app.py build.py scripts/vulture_whitelist.py --min-confidence 90`.
- `python -m bandit -r src --ini .bandit -ll` — passed with zero medium/high
  findings across 130,361 lines of code.
- `git diff --check` — passed.

The verification fixes removed genuine unreachable Chia split and legacy
requote code, removed unused imports, and explicitly consumed retained public
compatibility parameters. Dynamic Flask route imports remain covered by the
repository Vulture whitelist.

## Local package verification

`python build.py` completed as a clean PyInstaller build at
`2026-08-22T09:02:30+01:00`. Post-build checks found the executable and bundled
HTML assets.

- Executable: `dist/Catalyst/Catalyst.exe`
- Size: 10,586,303 bytes (reported as 10.1 MB)
- SHA-256: `F4C5D7AB566B9AE9EE1E3B0C05773DCC892EE13159A4487A3D8E3369491E2F8B`

The isolated packaged API harness then started that public executable in
`--flask` mode and passed all of these surfaces:

- `GET /api/health` (version `1.2.65`)
- `GET /api/wallet/sage-running`
- `POST /api/wallet/begin-startup`
- `GET /api/sage/startup-status`
- `GET /api/config/validate`
- `GET /api/diagnostics/api-stats`
- `GET /api/self-test`
- `GET /api/doctor?force=true`

The packaged run recorded 14 guard events, 12 loopback socket operations, and
zero external attempts. The temporary app and mock Sage processes shut down at
the end of the harness.

The first packaged attempt correctly exposed a release-only configuration
defect: `.env.example` reload replaced the harness's synthetic fingerprint and
expected wallet name, causing startup to enter read-only diagnostics. The
process-environment preservation contract now includes the exact wallet identity
and network fields, the harness supplies them explicitly, and unit plus packaged
tests pass.

## Regression fixes made during Task 16

- Preserved HTTP 405 routing for authorised unsupported methods before the
  mutation gate can reinterpret the request.
- Made cancellation-cohort replay losers return durable read-only state before
  any wallet effect.
- Modernised API tests to use an explicit local mutation permit and safe
  dependency mocks instead of accidental global state.
- Closed order leaks in configuration, reconciliation, publication, Linux
  desktop port selection, dashboard market-data fallbacks, and wallet discovery.
- Prevented Dexie, CoinGecko, Spacescan, and other public fallbacks from being
  reached by ordinary automated fixtures.
- Added exact packaged identity preservation and its regression tests.

No test invariant, production safety gate, or external-network guard was
weakened to obtain a passing result.

## Local Sage full-app acceptance

The final Windows build was exercised end to end on this PC against the
authorised Sage `TEST 7` wallet on 2026-08-22. The run used the isolated
`.superpowers/test7-mainnet-lab` data directory and left the user's normal
CATalyst data directory untouched.

The packaged Flask/API pass checked 76 read and control endpoints with no HTTP
5xx responses or secret findings. Health, self-test, configuration validation,
wallet identity, Sage startup, balances, CAT discovery, market data, offers,
reservations, diagnostics, and all six stability blocker categories returned
valid state. A dry-run cycle completed without an offer or transaction.

The browser UI rendered Dashboard, Offers, P&L, Market Intelligence, both
Settings views, Logs, Data Reset, Help, and About with no console errors. Theme,
keyboard focus, local presets, and Smart Settings form behavior were also
checked and restored. The native PyWebView build completed risk disclosure and
Sage onboarding, displayed fingerprint `736588221` and the exact XCH/SBX
balances, rendered the principal screens, passed its Doctor check with 9 passes
and one non-blocking Spacescan free-tier warning, and completed a clean
close/restart/close cycle.

Two real packaged boundaries exposed regressions that are now covered by tests:

- Sage 0.12.10's successful legacy boolean return from `login` was rejected by
  the guarded wallet facade. The facade now normalizes `True` only for the three
  documented legacy boolean mutation exports (`sage_login`, `sage_initialize`,
  and `delete_offer`); all other malformed mutation results remain blocked.
- Sage returned the selected offer coin with a `0x` prefix while CATalyst held
  the same id without it, producing a false unexpected-coin warning. Locked
  inputs are now compared in canonical lowercase `0x` form.

The bounded live package test created exactly one buy offer for `0.001 XCH` and
stopped the bot before a second cycle. Coin preparation, sniper, Dexie posting,
and Splash remained disabled; the sell side was disabled because the wallet had
no prepared SBX trading coin. The cancellation RPC was conservatively journaled
as ambiguous, the restart correctly entered read-only diagnostics, and the
authoritative reconciliation boundary then found Sage's exact cancelled row and
returned `CANCELLED_PROVEN` with `EXACT_CANCEL_RETURN_PROOF`. The only balance
change was the expected `0.000001 XCH` cancellation fee; SBX was unchanged.

Final reconciliation reported a stopped bot, `DRY_RUN=true`, zero Sage pending
transactions, zero Sage/CATalyst open offers, zero pending cancellations, zero
locks or reservations, and zero blockers in operations, submitted cancels,
prepared creations, contradictory history, reservations, and publication
claims. All XCH and SBX balances were spendable.

Fresh post-fix gates were:

- Wallet identity/login slice: 91 passed.
- Offer manager and creation journal slice: 114 passed.
- Whole repository in CI file-isolated mode: 5,095 passed, 13 skipped, 413
  subtests passed in 307.52s.
- Ruff, Vulture, Bandit (zero medium/high findings), and `git diff --check`:
  passed.
- `python build.py --no-clean`: passed; packaged post-build Sage/Doctor smoke:
  passed.

Final local artifact:

- Executable: `dist/Catalyst/Catalyst.exe`
- Size: 10,586,545 bytes
- SHA-256: `48C28B93B93737ADE776D502FD2F748CA99F99FD1A132884F0EF4CBE7A9EA451`
- Detailed redacted report:
  `.superpowers/local-sage-acceptance/acceptance-report.json`

## Known limitations

- `python -m ruff format --check .` reports accumulated branch-wide formatting
  debt in 38 files (296 files already conform). Task 16 did not bulk-reformat
  those large prior-task files because that would create a broad mechanical diff
  and require repeating the complete build/test evidence. Ruff lint, Vulture,
  Bandit, and diff checks are green.
- PyInstaller emits one non-fatal warning that hidden import
  `importlib_resources.trees` was not found. The build, bundled-asset check, and
  complete packaged API smoke all pass.
- Sage can normalize confirmed transaction rows without a transaction ID and
  can temporarily omit a consumed offer row. Terminal fill proof therefore uses
  a unique deterministic spend identity plus exact registered input and receipt
  flows; absence by itself remains non-terminal.

## 2026-09-05 TEST 7 live recovery and runtime top-up checkpoint

The rebuilt `v1.3.21` package was restarted from the existing TEST 7 ladder and
completed the full previous-session recovery flow in the native GUI. The app
proved the mainnet safety binding, Sage fingerprint `736588221`, wallet ID `2`,
`MZ_XCH`, and asset ID
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
before resuming. Sage, CATalyst's database, and Dexie then agreed on 36 open buy
offers and 36 open sell offers, with zero pending cancels.

The recovered configuration remained Balanced/two-sided with 10% reserves
(`14.594 XCH` and `70,284 MZ`), 36 offers per side, 50 fee coins of `0.001 XCH`,
and a transaction fee of `0.0000130791 XCH`. At cycle 5, the authoritative
purpose-separated fee inventory correctly triggered at 47/50 instead of being
masked by 98 same-sized wallet coins. The worker requested five fee outputs,
submitted transaction prefix `0x95b090a8488623...`, and confirmed all 5/5
outputs selectable after 48 seconds. The authoritative fee-reserve count rose
to 52, the XCH top-up pool changed from `6.3659` to `6.3609 XCH`, and the bot
remained at 36/36 offers throughout. Cycles 6 through 9 completed without a
duplicate top-up or an error.

Dashboard, Offers (active and history), P&L, Market Intel, Settings (Live and
Setup), Logs, Data Reset gating, Help, and About were exercised after the
restart. Logs backfilled new cycles after navigation and continued advancing
while visible. TibetSwap pool data was unavailable, and the GUI explicitly
showed Dexie-only pricing with unavailable arb/pool metrics instead of stale
TibetSwap values. Splash remained reachable with four peers; its interleaved
webhook warning was reduced to one throttled diagnostic and the current
superlog contained zero unredacted `offer1...` payloads.

Post-fix verification available at this checkpoint:

- Focused coin top-up and Splash regression slice: 60 passed.
- Ruff check for the changed source and focused tests: passed.
- Clean PyInstaller rebuild: passed.
- Packaged executable: `dist/Catalyst/Catalyst.exe`, 10,794,830 bytes.
- Packaged executable SHA-256:
  `21F1216C3ADE4FAC5B50E860DA5A2C8FFB8543C63E625EAB6ED7A362140894C8`.
- Live safety state: allowed, this-run lease owner, zero unresolved operations,
  reservations, publication claims, or submitted cancels.

The next periodic health check exposed a separate Sage-only accounting defect:
the runtime monitor treated Sage's 42 selectable CAT coins as if they still
included the 36 coins locked by live offers, subtracted those offers again, and
raised a false `health_topup_trigger` at 6/7. Sage selectable views already
exclude offer-locked coins. Two focused regressions now prove both sides of the
boundary: healthy Sage selectable inventory is not double-subtracted, while a
genuinely low selectable count still triggers a top-up. The implementation
keeps the existing subtraction for non-Sage wallets.

After the fix, the clean rebuilt package was shut down without cancelling the
72 live offers, restarted, and taken through risk disclosure, TEST 7 login,
Splash, configured Spacescan, and previous-session recovery. Startup proved
the exact fingerprint, pair, and asset binding; all 11 safety checks passed;
wallet, database, and Dexie reconciled at 36 buys and 36 sells; and Dexie
reported all 72 offers already live, so nothing was reposted. Cycles 0 through
5 then completed at 36/36 with zero `health_topup_trigger`, `topup_started`,
`topup_tiers_adequate`, `drip_trigger`, error, or critical event. This is the
live boundary that had failed before the patch.

Additional verification for this follow-up:

- Runtime-health regression slice: 115 passed.
- Ruff check for the changed source and focused tests: passed.
- `git diff --check`: passed before the rebuild.
- Clean PyInstaller rebuild: passed.
- Packaged executable SHA-256:
  `7A7ADF3BF7314403993C7E517CB2D87AF7A8DBCB60DFFD3AEFA6C0F8DDA5B5B0`.

The authenticated bot-state cross-check then found the same double subtraction
in the runtime diagnostics presentation path: the authoritative Sage inventory
reported 42 selectable CAT coins plus 36 separately locked coins, while
`diagnostics.coins.cat_free` incorrectly reported 6. A focused regression first
reproduced the mismatch. `get_free_coin_counts()` now uses the explicit wallet
type contract: Sage reports its already-selectable counts unchanged, while the
legacy Chia adapter still subtracts active offers.

The Sage and Chia boundary tests passed, followed by the combined coin-health
and runtime-monitor slice (67 passed), Ruff, and `git diff --check`. A clean
package rebuild was restarted through the complete TEST 7 previous-session
recovery flow without cancelling or reposting the 72 live offers. After the
first recovered cycle, `/api/bot/state` reported XCH selectable/spendable/free
as 161/161/161 and CAT as 42/42/42, with 36 locks per side, 36/36 active offers,
healthy diagnostics, and zero active conditions. The corrected packaged
executable SHA-256 is
`E7C457B6C38995B0AABD1E9669D91CFAE1ED19074309D1472DEEACD8F2C51EFA`.

The next controlled package restart exposed a startup publication race. Sage
and the startup reconciler had already restored 36 buys and 36 sells, but the
runtime monitor was released while `_bot_state` still held its default 0/0
counts. That transient view produced false 21/36 adaptive ladder targets until
cycle 0 refreshed the state. A focused regression first proved the missing
publication before the runtime gate. Successful startup sync now returns its
authoritative offer counts, and `_run_loop()` publishes those counts before
enabling or releasing background workers.

The focused startup/publication/runtime slice passed (109 tests), Ruff passed,
and `git diff --check` remained clean. A clean package rebuild was then taken
through risk disclosure, Sage TEST 7 login, Splash, configured Spacescan, and
the existing-session recovery flow without cancelling or reposting the live
offers. `startup_sync_done` reported 36/36, cycle 0 began and completed at
36/36, runtime diagnostics remained healthy with targets 36/36, and the new
process recorded zero `adaptive_ladder_target_reduced` events and zero errors.
The verified executable SHA-256 is
`E1873CE787B5929BCA517A9C985B9C87DF6A4700C39B582425C172B292F64DE8`.

The recovered run also produced one isolated `splash_db_error` while the
startup coin recheck held SQLite busy. Investigation found that
`record_splash_incoming()` returned `False` both for a duplicate and for a
persistence failure, so the webhook replied HTTP 200 even when an incoming
offer had not been saved. Two focused regressions reproduced both the
tri-state ambiguity and the false acknowledgement. Persistence failure now
returns `None` internally and `/api/splash/incoming` returns retryable HTTP 503
with `persistence_unavailable`; genuine duplicates remain successful HTTP 200
with `new: false`.

The complete Splash receive/security/settings/runtime slice passed (93 tests),
followed by Ruff and `git diff --check`. The package was cleanly rebuilt and
again recovered through TEST 7, Splash, Spacescan, and the existing 36/36
ladder. Cycles 0 and 1 completed at 36/36; Logs backfilled the new process and
advanced while visible; runtime health stayed healthy with no conditions,
161/42 selectable coins, full 36/36 targets, four reachable Splash peers, and
zero new adaptive-target, Splash database, or error events. The latest running
executable SHA-256 is
`056BDEDCB1D7C86F94C4D9BB9CFA25ACA663CC73BDFCCD87CBD3C9545F9B76DD`.

The following live checkpoint exposed a presentation defect in Splash's
Windows stdout handling. One webhook connection failure was emitted as several
interleaved Rust fragments; the first fragment entered CATalyst's 60-second
hook-warning throttle, but three continuation fragments became independent
generic warnings. A focused regression reproduced the exact multiline shape
and initially failed with four warnings. `SplashNode` now keeps a narrowly
scoped two-second hook-fragment context, grouping only immediate connection and
request continuations while leaving unrelated errors visible.

All 14 Splash runtime-path tests passed, followed by the combined Splash
receive/manager/settings/health/publication slice (204 tests and 4 subtests),
Ruff, and `git diff --check`. The rebuilt package was stopped without
cancelling its 72 offers, then recovered through risk disclosure, Sage TEST 7,
Splash, configured Spacescan, and the previous-session prompt. Startup restored
36 buys and 36 sells, cycle 0 and cycle 1 completed at 36/36, and repeated
Dashboard-to-Logs navigation both backfilled and advanced live. The packaged
run showed zero fragmented `Splash:` warning rows; the separate TibetSwap
outage remained correctly visible as an external degraded-data warning. The
superlog then captured a real live failure burst as exactly one grouped
`Splash webhook delivery failing; suppressing repeated hook errors for 60s`
warning and no continuation warnings. Cycles 2 and 3 also completed at 36/36.
The current packaged executable SHA-256 is
`C9AC2A3BB53A9A9A4757D9B3E4871593494CEDB33E861B882221DF4CE7487067`.

The Sage native bulk-cancel follow-up found one remaining presentation and
timeout defect from the superseded serial cancellation path. CATalyst already
submitted a measured offer cohort through Sage's single `cancel_offers` RPC,
but the Cancel All modal still said offers were sent one at a time and the
backend multiplied its confirmation deadline by the number of offers. A
72-offer cancellation could therefore be shown with a multi-hour allowance
even though it was one aggregate transaction.

Focused regressions first failed on both mismatches. The modal now describes a
single bulk transaction with authoritative on-chain confirmation. The deadline
uses one transaction's confirmation allowance plus a bounded per-member budget
for recording durable terminal proofs, rather than assuming one on-chain
transaction per offer. The durable per-offer journal, exact signed transaction
identity, explicit fee-coin planning, fail-closed unsigned-effect validation,
and authoritative terminal reconciliation are unchanged. The focused wallet
and endpoint slice passed (62 tests); the broader cancel journal, integration,
wallet, and endpoint slice passed (183 tests). Ruff and `git diff --check`
passed.

The controlled live Cancel All proof then stopped the 36/36 TEST 7 ladder and
submitted all 72 offers through a single Sage transaction,
`2d7de8cfe372119e9fdc85e178c0087774096837198709138498afe7d62c4ce3`.
Sage reported one pending transaction with a 0.0000130791 XCH fee, 73 spent
coins and 73 created coins: the 72 exact offer roots plus one dedicated fee
coin. It confirmed at height 9,249,204; the pending queue returned to zero,
CATalyst's durable progress reached 72/72 authoritatively terminal with zero
failures, Sage returned zero open offers, and runtime safety cleared with all
blocker counts at zero. No `BAD_AGGREGATE_SIGNATURE`, cancel error, or CATalyst
runtime error occurred. This is direct live evidence that CATalyst is using
Sage's native bulk-cancel API rather than serial cancellation.

While that ladder continued, cycle 17 exposed a second Windows-specific Splash
interleave: the daemon split `(os error 10061)` so two continuations retained
only `(os error Received Offer: ...)`. Those fragments were redacted but still
surfaced as generic warnings. The exact live lines were added to the existing
fragment regression and reproduced two extra warnings. The classifier now
recognizes a received-offer line containing the surviving `os error` prefix as
part of the same webhook-delivery failure. All 14 Splash runtime-path tests,
Ruff, and `git diff --check` passed. The follow-up is included in the rebuilt
package below; live recurrence observation remains part of the stability loop.

The same controlled shutdown exposed a separate UI-only accuracy defect: after
the wallet and CATalyst both showed zero open offers, shutdown still displayed
`Offers left open` merely because the optional cancel checkbox was unticked. A
focused JavaScript regression first failed because no state-aware disposition
existed. Shutdown now reports `No open offers were left behind` for an empty
book and gives the exact active count only when offers really remain.

A clean build containing the native bulk-cancel presentation/deadline update,
the second Splash fragment classifier, and the shutdown wording fix completed
successfully. Its executable SHA-256 is
`9DA1E930A484C13F4A0D33A0EC4C0D2E07F475DFBA7E3B27E79610CB41D5FA30`.
The exact executable was launched through the full risk, Sage TEST 7, Splash,
configured Spacescan, MZ selection, and Settings flow. Balanced Smart Settings
were reapplied with 10% XCH and MZ reserves, 36 offers per side, 50 fee coins
of 0.001 XCH, and a 0.0000130791 XCH transaction fee. Wallet verification
correctly found all post-cancel coin shapes already prepared and avoided an
unnecessary transaction. Bot startup then created 36 buys and 36 sells with
five workers per side; cycle 0 completed at 36/36, cycle 1 started from a
36/36 authoritative baseline, daily reconciliation matched DB=72 and
wallet=72, runtime safety remained allowed, and the error count stayed zero.
The external TibetSwap outage remained explicitly degraded while live Dexie
pricing supplied the bot's midpoint.

That exact package continued for 16 clean cycles at 36 buys and 36 sells with
zero bot errors. Dexie publication reached 72/72 and Splash reached 72/72 with
zero failures, an empty queue, four reachable peers, and 72 broadcasts reported
by the node metrics. Repeated Dashboard-to-Logs navigation showed current-run
backfill and advancing events. The Market Intel API nevertheless exposed a
display-calculation defect: wallet-authoritative local edges were refreshed to
the live 36/36 book, but `our_spread_bps` retained a stale zero from the remote
summary. A focused regression reproduced that mismatch. Market Intel now
recomputes the local spread from the same live bid and ask that it returns; the
focused Market Intel slice and the combined market/dashboard slice passed.

A second controlled live Cancel All stopped the same 36/36 TEST 7 ladder and
again submitted one Sage bulk transaction,
`95064a9edf31a9fc26f22a67897a6d90b9be15179a0075f4f4cc2afa046de633`,
with the configured 0.0000130791 XCH fee. Sage's pending queue contained one
transaction and then returned to zero. CATalyst authoritatively reconciled all
72 members with zero failures and released every safety blocker. At the exact
deadline boundary, however, the worker recorded `cancelled=72`, `pending=0`,
and `failed=0` before incorrectly raising `awaiting authoritative Sage proof
for 0 offer(s)`. A focused regression reproduced the final-state race. The
worker now gives zero remaining members precedence over deadline expiry and
finishes successfully.

The same shutdown showed that the earlier empty-book wording fix still trusted
the dashboard's stale pre-cancel 72-offer snapshot. A second JavaScript
regression reproduced that condition. The shutdown disposition now prefers an
exact cancel-all terminal proof (`cancelled == confirmed == total`, with zero
pending and failed members) over a stale rendered offer count. The focused
regressions passed, followed by the combined market/dashboard/cancel endpoint
slice (98 tests) and the broader durable cancel/wallet/endpoint slice (174
tests). Ruff passed for the changed Python files.

The deadline-race correction was then exercised in the packaged application,
not only in its regression test. CATalyst stopped a live 36-buy/36-sell TEST 7
ladder and submitted one native Sage bulk-cancel transaction,
`ce0bdfe4bf267229e8340bb65fdd23dc55231a45a0f948d1528332d96d21aa83`,
with the configured 0.0000130791 XCH fee. Sage's pending queue returned to
zero, while CATalyst continued to report incremental durable terminal proof
rather than treating transaction submission as cancellation success. The
visible modal and API advanced from 0/72 through 72/72 and completed with zero
pending members, zero failures, and no deadline-boundary error. Sage reported
zero active or pending offers, and the runtime safety latch cleared with every
blocker count at zero. The packaged shutdown flow then preferred this exact
terminal proof over its stale pre-cancel dashboard count and correctly showed
`No open offers were left behind`.

The same UI pass exposed a historical-age display defect. Legacy SQLite offer
timestamps use `YYYY-MM-DD HH:MM:SS` without an explicit offset; subtracting
that naive value from an aware UTC clock raised internally, causing months-old
history rows to fall back to `Recently`. A focused regression first reproduced
the incorrect label. CATalyst now interprets those legacy timestamps as UTC
before calculating their age; all 40 offer/history endpoint tests pass.

Separately, the live Splash node continued receiving thousands of offers with
four peers while an occasional outbound hook connection warning appeared.
That evidence distinguishes bounded Windows hook backpressure from a broken
inbound path. Focused regressions first showed that the classifier had no
evidence of successful deliveries. The webhook now timestamps every successful
new or duplicate delivery, and an isolated failure within 30 seconds is
reported as `Splash webhook backpressure active; inbound delivery remains
live` rather than falsely claiming delivery is down. Genuine failures without
a recent successful delivery retain the existing failure wording. The combined
Splash runtime/settings/health slice passes (65 tests), Ruff passes for all
files changed by these two fixes, and `git diff --check` remains clean.

The rebuilt package then ran a 19-cycle live window at 36 buys and 36 sells
with zero bot errors and no active diagnostic conditions. Dexie durable
publication reached 72/72 and Splash reached 72/72 with zero failures, an
empty queue, four peers, and 72 daemon broadcasts. The external TibetSwap
outage remained explicitly visible as Dexie-only degraded mode. A controlled
runtime top-up also restored the fee-coin pool from 49/50 to 52 using one
one-step Sage split, transaction
`adea29e62f343eac9a…` (the identifier emitted by the packaged top-up log).
It confirmed after 77 seconds, Sage's pending queue returned to zero, the
36/36 ladder stayed active throughout, and runtime safety remained allowed.
Dashboard-to-Logs navigation backfilled the current run and continued
advancing while visible; Offer History displayed real multi-day ages; P&L,
Market Intel, Settings live/setup, Data Reset gating, Help, and About all
rendered successfully.

That UI pass found one more dashboard-only live-update defect. The authenticated
dashboard API reported non-zero Dexie competitors, but a sparse
`market_intel` SSE push omitted competitor-only counts and the browser converted
the missing fields to zero, temporarily displaying `0 (none)`. A focused
browser regression reproduced the exact overwrite and failed with count zero.
Sparse pushes now preserve the last authoritative competitor count, and current
bot-loop pushes include `num_competitor_buys` and `num_competitor_sells` so the
display also updates live. The regression and the Smart Settings formatting
regression pass together (2 tests); the combined offer/history, Splash, health,
and log endpoint slice passes (124 tests); Ruff and `git diff --check` pass.

A clean package rebuild completed with executable SHA-256
`DA1725C405581380FF0C2D4EC14B0801B88EA159609E4B4E4083F165E023BB51`.
The exact executable was launched through risk disclosure, Sage TEST 7,
Splash, configured Spacescan, and the previous-session recovery prompt. The
prompt correctly identified 36 buys and 36 sells, loaded the unchanged MZ/XCH
session, and resumed without coin prep or offer replacement. The first three
recovered cycles completed at 36/36 with zero errors, four Splash peers, and
runtime safety allowed. After the first live market-intel push, the rebuilt
dashboard retained and displayed `91 (both)` competitors rather than zero.

During the following live window, Splash inbound delivery continued advancing
with four peers, but one incoming offer encountered `database is locked` while
being persisted. The endpoint already serialized incoming writes and correctly
returned a retryable failure rather than acknowledging an unsaved offer; the
remaining defect was that a short SQLite collision was not retried locally. A
focused real-SQLite regression reproduced the failure before the fix. The
incoming write now retries the complete deduplication-and-insert transaction
once on a transient SQLite lock, preserving the authoritative duplicate check;
a persistent lock still produces HTTP 503 and is never falsely acknowledged.
All 17 real-SQLite receive-path tests pass, followed by 99 relevant Splash,
logs, cancellation, and native Sage bulk-cancel regressions. Ruff and
`git diff --check` pass for the change.

A clean package rebuild produced CATalyst v1.3.21 executable SHA-256
`85CE5A89DECFCE386B8D8523ABC9D3C2CCC154C8FB4A330F8F436D8C8EF3BC9C`
(10,796,333 bytes). The exact package was launched visibly and exercised
through risk disclosure, Sage TEST 7 fingerprint `736588221`, Splash startup,
the configured Spacescan path, and previous-session recovery. The recovery
prompt correctly showed the existing MZ_XCH 36-buy/36-sell ladder, and loading
it required no redundant Coin Prep. Starting the recovered bot returned it to
36/36 with 52 fee spares, no pending Sage transactions, zero bot errors, a
clear safety latch, current Dexie publication state, and four live Splash
peers. By cycle 6 the Dashboard still displayed `91 (both)` competitors and
all exact reserves and limits. Dashboard-to-Logs navigation backfilled and
advanced the current session, and the visible app was returned to Dashboard.

The external TibetSwap outage remained clearly labelled as unavailable; the
Dashboard used current Dexie executable bid/ask and liquidity, showed `No
TibetSwap pool — Dexie-only`, and left Tibet-dependent arbitrage and pool-depth
values unavailable rather than presenting stale data. The separately visible
Splash webhook-backpressure warning remained bounded while inbound offer
counts and peers advanced; it is distinct from the transient incoming SQLite
lock fixed above and currently provides no evidence that inbound delivery is
down.

A fresh visible all-tab sweep was completed while the rebuilt bot remained
running. Offers showed 72 active (36/36), zero pending cancels, zero requote
pressure, and sampled buy and sell rows published on Dexie. History rendered
real ages rather than `Recently`. P&L showed zero verified or pending fills for
the current session; its 8.0% per-side adjusted spread is consistent with the
8.5% configured base plus active competitor-aware adjustment, while the live
Dexie inner market remained 6.8%. Market Intel populated its initially loading
Spacescan context within the normal asynchronous refresh, then agreed with the
Dashboard on 3,477 holders, moderate activity, healthy risk, Dexie bid/ask,
four Splash peers, and the external TibetSwap outage. Settings Live and Setup
showed the exact fingerprint, two-sided Balanced configuration, 10% reserves,
36/36 limits, 50 fee-coin target, and 0.0000130791 XCH transaction fee; runtime
safety was ALLOWED with zero unresolved operations, reservations, or
publications. Logs advanced through cycle 11 with no bot errors and only the
bounded, correctly classified TibetSwap-outage and Splash-backpressure
warnings. Data Reset controls were disabled while running, and Help and About
both rendered. The app was returned to the visible Dashboard at cycle 12 with
36/36 offers and zero errors.

The complete current Sage cancellation regression slice was then rerun against
the worktree while the packaged bot remained live:
`test_wallet_sage_bulk_cancel_method.py`,
`test_wallet_sage_cancel_batch.py`, `test_offer_cancel_journal.py`, and
`test_plan_03_12_cancel_all_flow_integration.py`. All 146 tests passed in
201.55 seconds. This covers the native `cancel_offers` bulk transaction,
configured fee handling, per-member durable journalling, authoritative
settlement, deadline completion, partial and crash recovery, endpoint progress,
and BAD_AGGREGATE_SIGNATURE/error protections. During the same interval the
exact packaged process remained the sole port-5000 owner and advanced from
cycle 12 to cycle 16 at 36 buys and 36 sells with zero bot errors. The visible
Dashboard continued to show the exact TEST 7 fingerprint, reserves, offer
limits, 52 fee spares, 91 two-sided competitors, clear safety state, and the
explicit external TibetSwap outage/Dexie-only fallback.

The complete current Coin Prep regression group was also rerun while that same
packaged ladder stayed live. It included the direct-batch planner and execution,
Sage unsigned-effect parsing, confirmed-view reconciliation, split retry,
post-submit drift conflict handling, no-effect recovery, consolidation,
one-sided and cancellation behavior, status-event flooding, adaptive top-up
thresholds, endpoint lifecycle, and crash recovery. All 345 tests passed in
27.47 seconds. The two reported pytest collection warnings are pre-existing
helper classes with constructors and are not application failures. During this
suite the visible packaged bot advanced from cycle 19 through cycle 21 at
36/36, retained 52 fee spares and the exact configured reserves, and continued
to report zero bot errors and healthy runtime safety. No wallet-affecting test
operation was issued against the live TEST 7 session.

Smart Settings and configuration persistence received a fresh combined
regression pass next. The focused smart-defaults endpoint, config endpoints,
deep Settings behavior, GUI preset handling, and Splash settings suites all
passed (121 tests in 5.02 seconds). Coverage includes unavailable-market
failure handling, partial Spacescan inputs, transient zero-balance protection,
Balanced sizing, live versus restart-deferred settings, bulk configuration,
startup reload, and Splash receive toggling. The live Logs tab simultaneously
advanced through cycle 21 and contained no new error category: only the
explicit external TibetSwap-outage warning and bounded Splash webhook
backpressure classifications were present. After the test run, the packaged
bot reached cycle 22 at 36/36 with zero errors, exact 10% reserves, 52 fee
spares, and healthy safety, and the visible app was returned to Dashboard.

Startup recovery, safety gating, identity enforcement, publication recovery,
offer reconciliation, and diagnostics received a fresh broad regression pass
against the same candidate. The nine-suite run completed with **824 passed and
13 skipped in 277.46 seconds**; the skips are the suites' explicit conditional
cases, not failures. It covered legacy and current startup recovery, the public
startup-offer recovery contract, startup-flow integration, end-to-end start
safety, mutation and wallet-identity gates, publication outbox recovery, offer
reconciliation, and the safety-diagnostics UI.

The exact packaged process remained live throughout that load and advanced
from cycle 23 to cycle 30 without intervention. The visible Dashboard then
showed the exact mainnet Sage TEST 7 fingerprint `736588221`, MZ_XCH pair,
36/36 active offers, Balanced settings, 10% reserves (`14.594` XCH and
`70284` MZ), 52 fee spares, healthy safety, 91 two-sided competitors, zero
fills, and zero errors. The external TibetSwap outage was still explicitly
reported as unavailable, with executable pricing and liquidity sourced from
Dexie and Tibet-dependent arbitrage/pool-depth values left unavailable. The
Splash webhook-backpressure warning remained bounded and classified while the
bot continued cycling normally.

A fresh Dashboard-to-Logs transition immediately backfilled the complete
current packaged session and included cycles 30 and 31 in chronological order;
there was no stale-tab gap. The only warning classes visible were the explicit
external TibetSwap outage and the bounded Splash webhook-backpressure notice.
Returning to Dashboard showed cycle 32, 36/36 active offers, the same exact
configuration and 52 fee spares, healthy market/safety indicators, and zero
errors. Port 5000 remained owned solely by packaged `Catalyst.exe` PID 54792.

The remaining focused offer-lifecycle group was then rerun: bot-loop outage,
Sage status mapping, reserve-floor, recovery, probe-anchor, price-watcher
shutdown, toxicity, and daily-reconcile tests; authoritative fill closure;
Splash runtime; Spacescan fill verification; runtime monitoring; fills API;
fill/P&L integration; requote integration; fill classification and
verification; offer lifecycle; and verified-fill persistence. All **559 tests
passed in 74.60 seconds**. The exact packaged bot remained live and advanced
from cycle 33 through cycle 35 with 36/36 offers, the same wallet balances and
configuration, 52 fee spares, healthy safety, explicit TibetSwap-outage
Dexie-only behavior, and zero runtime errors.

The exhaustive repository suite was then run from the worktree without
interrupting the packaged bot. It completed with **5,561 passed, 55 skipped,
422 subtests passed, and zero failures in 880.03 seconds**. The three warnings
are pytest collection warnings for helper classes with constructors, not
application failures. This full run subsumes the focused lifecycle, Coin Prep,
Smart Settings, cancellation, recovery, safety, wallet, market, UI-contract,
database, build, and packaging regression slices above.

Immediately after the full suite, read-only live API and process checks showed
that packaged `Catalyst.exe` PID 54792 remained responsive and the sole owner
of `127.0.0.1:5000`. The bot had advanced to cycle 58 with healthy diagnostics,
36/36 wallet-visible and verified offers, zero wallet-sync failures, zero
orderbook errors, zero pending cancels, no active safety conditions, and no
alerts. Runtime safety remained allowed with the lease owned by this run and
zero blocking operations, reservations, publication claims, or submitted
cancels. The exact mainnet MZ_XCH asset, Sage wallet ID 2, 10% reserves
(`14.594` XCH and `70284` MZ), 36-per-side limits, 50 configured fee coins,
and `0.0000130791` XCH fee remained unchanged. Inventory reported 52 spare fee
coins. Dexie remained the fresh executable orderbook source at approximately
`0.0000806610` bid and `0.0000863390` ask; Spacescan reported 3,477 holders,
and Splash remained healthy with four peers. The current warnings were bounded
Splash webhook-backpressure notices; there were no CATalyst runtime errors.

The Windows Computer Use helper could not perform the post-suite visible-tab
sweep because its trusted RPC service was not configured. This is recorded as
a test-harness limitation rather than a CATalyst defect; the packaged process,
local API, persisted configuration, safety state, live market state, and bot
progression were independently reverified above. The earlier visible all-tab
and Dashboard-to-Logs sweeps remain the direct UI evidence for this build.

A subsequent two-snapshot monitoring checkpoint proved continued progression
rather than a single healthy sample: the bot advanced from cycle 60 to cycle
62 across the observation interval while retaining 36/36 wallet-visible and
verified offers, healthy diagnostics, zero wallet-sync or orderbook errors,
no findings or alerts, and an allowed safety gate with no reason code. Dexie
remained the executable orderbook source, Spacescan continued to report 3,477
holders, and Splash remained healthy with four peers and zero delivery
failures. Coin Prep reported zero XCH and CAT coins needed and no tier-size
drift; its `complete: false` value while the bot is live reflects that the
prepared trade coins are locked into the 72 active offers, not a failed or
stalled preparation.

Because the native Windows helper was unavailable, a fresh real Chromium
session was opened against the same packaged localhost owner and used for a
second direct rendered all-tab sweep. After its normal Sage startup handshake,
Dashboard rendered v1.3.21 as Running with fingerprint `736588221`, 72 active
offers (36/36), the exact balances and reserves, 52 spare fee coins, zero
errors, fresh Dexie bid/ask, 3,477 Spacescan holders, four Splash peers, and
explicit `No TibetSwap pool — Dexie-only` handling. The rendered values agreed
with the live APIs.

Offers rendered 36 buys and 36 sells, zero pending cancels, zero buy/sell
requote pressure, and sampled offers marked on Dexie. P&L rendered zero
verified or pending fills, agreeing with the current session. Market Intel
first showed its bounded asynchronous loading state and then populated 3,477
holders, moderate activity, healthy token risk, the same Dexie book, no false
TibetSwap pool/slippage values, a healthy Splash node, four peers, and zero
Splash failures. Settings Live and Setup rendered the active TEST 7
fingerprint, Balanced profile, 10% reserves (`14.594` XCH and `70284` MZ),
36/36 limits, 50 x 0.001 XCH fee-coin planning, and the
`0.0000130791` XCH manual Sage fee; wallet-changing controls were blocked while
running. Logs immediately backfilled the current session in chronological
order through cycle 68, with no error entries and only the explicitly
classified TibetSwap-outage and bounded Splash-backpressure warnings. Data
Reset rendered all destructive controls disabled while the bot was running.
Help and About both opened and rendered, including v1.3.21. The browser was
returned to Dashboard, where the UI and API both showed cycle 73, healthy
state, 36/36 offers, and zero orderbook or wallet-sync failures.

A later authority checkpoint at cycle 74 agreed across the Sage wallet view,
CATalyst database, and verified visible counts: 36 buys and 36 sells in every
source, with zero pending cancels, fills, wallet-sync failures, orderbook
errors, findings, alerts, safety blockers, or Splash failures. Splash remained
healthy with four peers and an empty queue. The recent structured log window
showed uninterrupted successful cycles and periodic inventory reporting with
52 spare fee coins.

The cancellation implementation was also re-audited directly against the
current source after the live check. `OfferManager` plans one durable batch and
calls the wallet adapter once; the Sage adapter sends one native
`cancel_offers` request for the complete offer-ID set. With a configured fee it
combines the native unsigned cancel effect with one explicitly selected fee
coin, validates the exact input/output/fee effect before signing, submits one
aggregate bundle, and returns the same exact transaction identity for every
member. The durable coordinator still records and authoritatively reconciles
each member separately. There is no serial per-offer cancellation fallback in
this path, and unsafe repeated-input/fee effects are rejected before signing,
preserving the BAD_AGGREGATE_SIGNATURE protection covered by the 146-test
cancellation regression slice.

The next delayed live checkpoint reached cycle 77 with unchanged balances and
36/36 agreement across database, wallet, and verified visibility. There were
still zero fills or pending fill verifications, pending cancels, sync failures,
orderbook errors, findings, alerts, safety blockers, or runtime errors. Dexie
remained fresh, Spacescan was not stale, and Splash reported healthy with four
peers, an empty queue, and zero delivery failures.

One throttled `Splash webhook backpressure active` warning was present. Its
raw node-output view contained only redacted received-offer records, while the
implementation classified the transient/interleaved hook failure as
backpressure because a successful webhook delivery had occurred within the
preceding 30 seconds. A timed 45-second counter-delta check then proved that
Splash received eight additional offers (`3430` to `3438`) through the warning,
with the last-received timestamp advancing, queue remaining zero, failures
remaining zero, and peers remaining four. The bot simultaneously advanced
from cycle 77 to cycle 79 at 36/36 with healthy diagnostics and zero wallet or
orderbook errors. This supports the warning's intended bounded degraded-but-
live classification rather than a hidden CATalyst delivery defect.

A requirement-by-requirement evidence audit confirmed that the disruptive
lifecycle coverage is not merely simulated: this candidate has direct packaged
TEST 7 evidence for applying Balanced Smart Settings, coin-shape verification
and preparation/top-up, bot creation/start/run/stop, three 72-member native
Sage bulk cancellations, exact fee usage, authoritative cancellation
settlement, restart and existing-session recovery, ladder recreation, safety
release, every UI tab, and Dexie/Splash/Spacescan reconciliation. Targeted and
full-suite tests cover the corresponding failure and BAD_AGGREGATE_SIGNATURE
boundaries. Repeating another destructive lifecycle during the clean-window
phase would add no missing requirement evidence, so the current 36/36 ladder
was intentionally preserved for sustained observation.

At 63.6 minutes of packaged-process uptime the bot had reached cycle 81. It
remained responsive and healthy with 36/36 wallet-visible and verified offers,
fresh wallet sync and Dexie orderbook, zero pending cancels, sync failures,
orderbook errors, error/critical events, alerts, findings, or safety blockers.
The only recent warnings were the already-proven bounded Splash-backpressure
classification, and successful inbound delivery continued through them.

The monitoring mechanism itself was revalidated from its authoritative local
automation record. Heartbeat `catalyst-overnight-test-7-lifecycle` is ACTIVE,
runs hourly, targets this exact thread, retains the complete TEST 7 identity
and configuration invariants, and remains scheduled through
`2026-09-07 07:11 Europe/London`. Its prompt requires live process/API/Sage,
offer/fill/requote, fee inventory, Splash, Dexie, Spacescan, safety, logs, UI,
and recovery checks; it also requires deletion after the end-time audit. At
the same checkpoint packaged PID 54792 remained responsive at cycle 81,
healthy at 36/36 with zero sync or orderbook errors. This proves the extended
clean-window observation is backed by an active scheduler rather than only an
intent or stale goal card.

An independent live Dexie comparison at `2026-09-05T15:19:53+01:00` queried
Dexie's public v3 MZ/XCH orderbook directly rather than relying on CATalyst's
aggregation. Dexie returned 41 bid levels and 50 ask levels, with best bid
`0.00008066100094905695` and best ask `0.00008633900752868278`. CATalyst's
simultaneous diagnostics reported the exact same 41/50 counts and exact best
prices, source `dexie_v3_orderbook`, and zero orderbook errors. Packaged PID
54792 remained the sole port-5000 owner, the bot advanced to cycle 86, and the
database, Sage wallet, and verified-visible views all agreed at 36 buys and 36
sells. Runtime safety remained allowed, with zero pending cancels and zero bot
errors. This supplies a source-independent market-data checkpoint during the
extended clean window.

The same checkpoint independently traced an apparent Spacescan discrepancy.
CATalyst's market-intel context showed 3,477 holders, 499,852,385 circulating
MZ, and a Spacescan explorer price of `0.000000001 XCH`, which correctly
produced a roughly 100% explorer-gap warning while leaving executable pricing
on Dexie. Direct authenticated calls to Spacescan's live Pro API proved this
was not a CATalyst parsing or asset-selection defect: `/token/info` returned
the exact MZ asset ID and metadata, total supply 500,000,000, circulating
supply 499,852,385, and its own `price.xch` value of `1e-9`; an independent
`/token/holders` request returned `total_count: 3477`. CATalyst therefore
matches Spacescan exactly and safely exposes the external explorer price-data
discrepancy rather than using it to drive the ladder. At the follow-up poll the
bot advanced to cycle 87 with 36/36 agreement across database, Sage, and
verified visibility, zero pending cancels, sync failures, orderbook errors, or
runtime errors, and an allowed safety state.

At `2026-09-05T14:20:53Z`, extended live observation found a new CATalyst
defect: packaged PID 54792 completed cycle 87 at 36/36 but the mutation-lease
heartbeat reported `HEARTBEAT_FAILED` and permanently fenced the otherwise
healthy process. Preserved durable state showed the same owner PID/run,
mainnet/fingerprint binding, active lease through `14:21:08Z`, zero unresolved
operations, reservations, publication claims, submitted cancellations, or
contradictory history, and a resolved safety latch. The prior successful
heartbeat was at `14:20:38Z`; the failure path converted any single stability-
database exception into an irreversible terminal fence without retrying even
though the gate lock prevented concurrent mutations and the lease still had
time remaining.

A focused regression,
`test_transient_durable_heartbeat_failure_retries_before_process_fence`, was
added first and observed failing because one simulated SQLite lock immediately
returned a failed heartbeat. The minimal fix retries exactly once only when
the durable heartbeat call raises. The mutation-gate lock remains held across
both attempts, so no wallet mutation can pass during uncertainty. Returned
CAS mismatch, ownership loss, expired lease, non-monotonic expiry, and a
second durable failure still take the original fail-closed terminal path. The
focused four-test boundary passed, the full mutation-gate suite passed 242
tests, and the wider stability-schema/startup-recovery slices passed 160
tests. A clean PyInstaller build completed successfully.

The rebuilt packaged executable has SHA-256
`C17EDD0602E4B866E6811EEADA317534EBF9288500D420BC96BDD2031A295C81`.
It launched visibly as sole port owner PID 47760, passed startup recovery,
connected to Sage 0.13.0 with TEST 7 fingerprint 736588221, and independently
proved the exact MZ asset/wallet identity and 72-offer prior session. Resume
and bot start succeeded without changing settings or recreating offers. Five
timed live samples advanced the lease from version 28808 through 28812 and
the bot through cycle 2; after the wider regression run it had reached cycle
5 and lease version 28826. Every sample remained safety-allowed with exact
36/36 agreement across database, Sage wallet, and verified visibility, zero
pending cancels, sync failures, orderbook errors, or bot errors. The active
overnight automation was updated to the new executable hash and specifically
watches for recurrence of `HEARTBEAT_FAILED` or stalled lease progression.

Extended observation then exposed a separate transient Splash persistence
defect at `2026-09-05 14:35:53Z`. Inbound offer row 454158 was stored, but its
classification update encountered `database is locked`; unlike the adjacent
inbound insert path, `update_splash_incoming_status()` did not retry, and the
durable row remained incorrectly `new`. This was a CATalyst database-contention
defect, distinct from the external TibetSwap outage and from the already-bounded
Splash peer/backpressure warnings.

The focused regression
`test_transient_database_lock_is_retried_before_status_update_is_lost` was
added first and observed failing with the status update returning false after
one simulated SQLite lock. The minimal change retries the complete status
update once only when `_sqlite_locked()` identifies transient contention,
rolling back before retry; persistent or non-lock failures retain the original
false result and warning. The focused regression passed, the complete Splash
receive integration slice passed 18 tests, and the broader Splash/bot/API
regression selection passed 149 tests. `git diff --check` remained clean.

A clean PyInstaller build then produced the packaged 1.3.21 candidate at
`C:\catalyst\.superpowers\sage-v013-empty-login\dist\Catalyst\Catalyst.exe`
with SHA-256
`A29B939FE1024ADF603189B455A7F2A6D678D8C8F1AE4D99273FDAF7E978B1CA`.
The previous bot was stopped cleanly with safety allowed before closing exact
PID 47760. The new package launched visibly as sole port-5000 owner PID 58720,
re-established mainnet Sage TEST 7 wallet ID 2 and exact MZ asset identity,
and started against the preserved ladder without recreating offers. Its first
full cycle completed with exact 36/36 agreement across the CATalyst database,
Sage wallet, and verified-visible views, zero bot, wallet-sync, or orderbook
errors, safety allowed, and an advancing lease at version 28873. The remaining
AMM warning is the explicitly classified external TibetSwap outage.

Continued live Splash observation identified a further CATalyst throughput
defect. During a 30-second sample, the classifier changed 50 rows to ignored
but 69 new rows arrived, increasing the pending count from 221 to 240. More
importantly, the oldest pending row stayed fixed at ID 455299. Root-cause
tracing showed that `_process_splash_incoming_batch()` requested a status-
filtered query whose database implementation used
`ORDER BY received_at DESC LIMIT 10`; sustained inbound traffic therefore
selected the newest rows repeatedly and could permanently starve older rows.

Two focused regressions were added first and observed failing: the database
API lacked an oldest-first batch mode, and the classifier did not request one.
The minimal fix adds a deterministic `oldest_first` option ordering by both
`received_at` and `id`, while preserving newest-first behavior for existing UI
callers, and makes only the classifier request oldest-first work. The focused
four-test boundary passed, the combined bot-loop/Splash suite passed 86 tests,
and the broader affected bot/Splash/API selection passed 151 tests. A clean
PyInstaller build succeeded with SHA-256
`0795DBA21909B4EA7AF04748F9382B0AFBEBFA278EF68307996695D283F97D6B`.

The fixed package launched visibly as sole port-5000 owner PID 56992, verified
the exact mainnet Sage TEST 7/MZ identity, resumed safely, and completed its
first cycle at exact 36/36 database, Sage, and visible agreement with zero bot
errors and lease version 28922. Direct read-only database samples proved the
starvation fix under real inbound traffic: the oldest pending row advanced
from ID 456362 at `14:58:10Z` to ID 456391 at `14:58:45Z`, pending work fell
from 7 to 1, and ignored/classified rows rose from 45 to 79. The existing
admission guard caps new Splash backlog at 250, so inbound overload remains
bounded while oldest-first processing now guarantees progress.

A subsequent sustained-window sample on the same packaged PID 56992 advanced
bot cycles 4 to 5 and lease versions 28936 to 28940 while database, Sage, and
verified-visible offer counts remained exactly 36/36. Bot errors, pending
cancels, wallet-sync failures, orderbook errors, and safety blockers all
remained zero. During the same 35-second live interval, Splash pending work
fell from 15 to 3 and the oldest pending identity advanced from ID 456481 to
456520; the classified count rose from 164 to 203. The current packaged
superlog contained no `BAD_AGGREGATE_SIGNATURE`, authoritative-state conflict,
`HEARTBEAT_FAILED`, publication/reservation recovery reason, traceback,
`splash_db_error`, error, or critical entry, and the durable event table had
no error/critical records since this runtime started. Remaining warnings were
bounded Splash peer/webhook backpressure and the explicitly external
TibetSwap outage.

### Running-bot health endpoint authority (2026-09-05)

Real packaged UI exercise exposed an authoritative-state contradiction after
API-based session recovery: `/api/status` reported the running Sage wallet as
healthy, reachable, and synced, while the independently polled `/api/health`
returned `bot_running=false` and `chia_health.status=not_started`. The latter
response repeatedly overwrote the header badge with a false `Disconnected`
state. The running package was otherwise healthy at the time of reproduction:
mainnet Sage TEST 7 wallet ID 2 and the exact MZ asset were verified, cycle 19
completed at exact 36/36 database, Sage, and verified-visible agreement, the
runtime safety gate was allowed, and lease version 29003 was active.

Root-cause tracing found that the diagnostics route returned a hard-coded
pre-disclaimer response whenever the process-local startup-authorisation flag
was unset, before consulting the already-running bot and its continuously
maintained wallet-health snapshot. A focused real Flask endpoint regression
was added first and observed failing because `bot_running` was false. The
minimal fix uses the running bot's existing in-memory `chia_health` snapshot
without initiating a new Sage RPC; an actually idle, unauthorised process
retains the original `not_started` behavior. The focused diagnostics suite
then passed 14 tests, including tests that had previously been hidden by two
classes sharing the same Python name. The wider status, diagnostics, frontend
layout, safety UI, and smoke set passed 115 tests with 41 environment-specific
skips and four passing subtests. Packaged live revalidation follows below.

The clean build produced `Catalyst.exe` with SHA-256
`AE69E767AC5D66A8478E1B0791C7201670683A34815E274CEF06F2C6796CF0DF`.
It launched visibly as the sole port-5000 owner (PID 74460). To exercise the
original failure path, the preserved session was resumed and the bot started
without calling the wallet-startup endpoint. After the first cycle,
`/api/status` and `/api/health` both reported running, healthy, reachable, and
synced; safety was allowed, errors were zero, lease version 29025 was active,
and database, Sage, and verified-visible views all agreed at exactly 36 buys
and 36 sells. The rendered header displayed `Synced` with the explicit Sage
connected tooltip rather than the prior false `Disconnected` state.

A real headed-browser pass then exercised Dashboard, Offers, P&L, Market
Intel, Settings Live, Logs, Data Reset, Help, and About. Dashboard values
matched the authenticated runtime; Offers showed 72 active with 36/36 depth
and zero pending cancels; P&L consistently showed no verified fills in the
fresh runtime; Market Intel used Dexie prices and explicitly marked TibetSwap
pool, arb, and slippage data unavailable; Settings preserved the running
configuration; Data Reset correctly disabled all destructive actions while
running; Help and About rendered and reported v1.3.21. Dashboard-to-Logs
navigation immediately backfilled startup through the latest completed cycle
in chronological order and continued advancing. After clearing connection
noise caused by the intentional package shutdown, a fresh Dashboard-to-Logs
interval produced zero browser console errors or warnings.

### Splash webhook backpressure classification (2026-09-05)

The remaining Splash webhook warning was rechecked against the live packaged
runtime rather than treated as a CATalyst failure by message text alone. The
receiver was active, the Splash process had not restarted, three peers were
connected, the outbound queue was empty, and no `splash_db_error`, traceback,
error, or critical event accompanied the warning. CATalyst's inbound guard
was enforcing the configured 250-row hard cap and reporting the condition as
backpressure while deliveries continued.

A read-only 35-second database sample proved starvation-free progress during
the warning. The classifier changed 50 rows from `new` to `ignored`; the
oldest pending identity advanced from ID 458881 (`15:26:28Z`) to ID 458931
(`15:26:58Z`). During the same interval 54 distinct new rows arrived, so the
pending count moved only from 242 to 246 and remained below the hard cap.
This is a bounded external inbound-rate condition, not a stuck classifier or
lost-write CATalyst defect. The warning's explicit wording -- inbound
delivery remains live while repeated hook errors are suppressed -- is
therefore the correct classification. No code or user risk configuration was
changed for this observation.

### Sage native bulk-cancel settlement and status batching (2026-09-05)

The running 36/36 ladder was stopped through the authenticated API and Cancel
All was exercised against all 72 live offers. Sage accepted one native bulk
transaction, transaction ID
`2d3edd591ab830b328778003eeb4b4d44f0075c04cd0a8981cb4999b3ce89bbe`,
using method `bulk_rpc`. The durable journal tied every member to that one
transaction and the compact Sage result reported 73 spends: 72 offer source
roots plus one fee coin. CATalyst did not claim success before authoritative
terminal proof. All 72 offers ultimately settled as cancelled, pending work
returned to zero, the safety gate released, and neither Sage nor CATalyst
reported `BAD_AGGREGATE_SIGNATURE`.

The live test also confirmed a CATalyst performance defect in cancellation
status polling. Each status request performed a separate authoritative
journal query for every trade, taking roughly 3.8 seconds per poll and
competing with the settlement worker. A focused regression was added first
and observed failing when the serial getter was forbidden. The fix adds one
validated batch database query for the full trade-ID set and makes the offers
status path use it, retaining the serial path only as a compatibility fallback
when an older/bootstrap database cannot provide the batch helper. The focused
cancel suites passed 176 tests; the wider database, status, and mutation-gate
set passed 343 tests plus four subtests.

The clean fixed build produced CATalyst v1.3.21 with SHA-256
`411FA10D605FC21788221F717F445303AE7792A5AD134686269E3C4B750DBE6F`.
It launched visibly as the sole port-5000 owner (PID 69012), retained mainnet,
Sage wallet ID 2, exact MZ asset identity, Balanced 10% reserves, 36/36 limits,
50 fee coins, and the configured transaction fee. Starting from the fully
cancelled book recreated exactly 36 buys and 36 sells. The first completed
cycle reported a healthy synced Sage wallet, zero bot errors, no unresolved
operations/publication claims/reservations, and an allowed runtime safety
gate.

A subsequent authenticated live/UI checkpoint proved continued progress on
the same packaged PID rather than merely preserving the first-cycle state.
The bot advanced through cycle 16 while remaining exactly 36 buys and 36
sells, with zero bot errors, zero pending cancels, a healthy reachable/synced
Sage wallet, an advancing lease, and no unresolved operation, publication, or
reservation blocker. The rendered Dashboard agreed at 72 active offers,
36/36 depth, v1.3.21, Running, Synced, 10% reserves (`14.594` XCH and `70284`
MZ), and zero errors. Offers showed 36 buys and 36 sells, zero pending
cancels, and Dexie publication for the sampled live offers. P&L correctly
showed no verified fills in this fresh runtime. Market Intel explicitly
reported the TibetSwap outage as unavailable/Dexie-only rather than exposing
stale AMM values. Settings remained in Live/Running mode; Data Reset disabled
all destructive controls while the bot was active; Help and About rendered,
with About reporting v1.3.21.

Dashboard-to-Logs navigation was repeated after more than one cycle. Logs
immediately backfilled the complete chronological run and had advanced from
cycle 9 to cycle 16. The only warnings were the explicit external TibetSwap
outage and the already-proven bounded Splash webhook backpressure condition;
the headed browser recorded zero console errors and zero console warnings.

The next external-source checkpoint advanced the bot from cycle 20 through
cycle 22 with exact 36/36 counts, zero errors, no pending cancels, an allowed
safety gate, and lease version 29306 advancing to 29315. The authoritative
offer diagnostic independently reported database 36/36 and Sage wallet
36/36, no wallet-only or stale-database offers, no duplicate coin IDs, no
reserve-backed offer, and Dexie publication recorded for all 72 live offers.
Market Intel's live book source was `wallet_sync`, Dexie orderbook errors were
zero, and its own-open counts were 36/36. Splash remained healthy with three
peers, zero failed posts, 72 broadcasts, and no node error. During a
39-second inbound-pressure sample, its received counter advanced from 32,208
to 33,430, ignored/classified rows advanced from 1,640 to 1,710, and pending
new rows fell from 192 to 169 despite continuing arrivals. Spacescan remained
enabled/configured and supplied token context, while its 100% explorer-price
gap stayed explicitly advisory and separate from executable Dexie pricing.

The packaged runtime superlog was then audited directly from process start,
not only through filtered UI events. It contained no error/critical entry,
traceback, `BAD_AGGREGATE_SIGNATURE`, authoritative-state conflict,
`PUBLICATION_CLAIM_RECOVERY_REQUIRED`, `RESERVATION_RECONCILIATION_REQUIRED`,
or heartbeat failure. Every completed loop continued to show Sage wallet
36/36, no fills, empty Dexie/Splash outbound queues, and successful cycle
completion. Coin-count refreshes consistently took roughly 3.5--4.8 seconds
against Sage, with one 7.2-second outlier; these remained bounded inside the
45-second loop and returned stable 164 XCH/42 CAT free-coin counts, so this is
recorded as wallet-RPC latency rather than a stalled CATalyst operation.

An additional uninterrupted 67-second sample advanced the API-observed loop
counter from 24 to 26 and lease version from 29326 to 29333. CATalyst status,
Market Intel's wallet-synchronised book, and Sage-backed counts all remained
36/36 with zero pending cancels, zero bot errors, an allowed safety gate, and
zero Dexie orderbook errors. Splash received traffic rose from 37,211 to
39,635 offers while pending new rows fell from 134 to 85 and classified rows
rose from 1,910 to 2,030; it retained three peers, an empty outbound queue,
and zero failed posts. A fresh direct superlog search still found no signing,
recovery, authoritative-state, traceback, error, or critical match.

### Packaged post-fix bulk-cancel lifecycle (2026-09-05)

The remaining proof gap was closed by exercising Cancel All again through the
rebuilt v1.3.21 package. Immediately before the action, CATalyst verified
mainnet, the expected TEST 7 fingerprint hash, Sage wallet ID 2, exact MZ
asset, Balanced two-sided 36/36 settings, 10% reserves, 50 fee coins of 0.001
XCH, the configured 0.0000130791 XCH fee, zero errors, and an allowed safety
gate. The bot stopped cleanly and submitted one 72-offer background cancel.

Sage produced one transient 20-second `SAGE_CONNECTION_ERROR` while resolving
`get_key`, but CATalyst retained and recovered the same durable operation. It
did not restart, duplicate the transaction, report premature completion, or
lose safety authority. Authoritative settlement then advanced monotonically
from 0/72 through 72/72 with zero failed members. Total wall time was 490.6
seconds. The newly batched status path initially answered in 0.040--0.046
seconds rather than the former fixed ~3.8 seconds; response time varied under
write contention while individual terminal members were durably committed,
but progress remained live.

The append-only journal proves exactly one new shared Sage transaction ID,
`36b3e98e4819a3e8ee64d80642a17494ff3f390b22b6700487b07b9896477fcd`,
across all 72 members. Its compact preserved Sage response reports
`method=bulk_rpc`, `spends=73`, and `success=true`, proving 72 offer roots plus
one fee coin. No `BAD_AGGREGATE_SIGNATURE` occurred. At completion, all 72
members were authoritatively terminal, pending work was zero, and safety
released with no operation, publication, or reservation blocker.

The unchanged prepared-coin inventory remained complete, so the bot was
started again without redundant Coin Prep. The restored live checkpoint
reached loop 28 with API, database, and Sage wallet independently agreeing at
exactly 36 buys and 36 sells. There were no stale-database, wallet-only,
duplicate-coin, or wallet-error records; bot errors remained zero and the
safety gate was allowed.

The rebuilt ladder was then followed through its complete publication drain,
closing another recovery-path evidence gap. Dexie reached 72/72 recorded live
offer publications by loop 5 with zero orderbook errors. Splash deliberately
drained at its bounded per-cycle rate, advancing from 25/72 to 72/72 over
464.6 seconds with zero failures and an empty outbound queue at completion.
Throughout the drain, database and Sage remained exactly 36/36, safety stayed
allowed, and bot errors remained zero. The run continued through loop 15;
the direct superlog still contained no signing failure, authoritative-state
conflict, recovery blocker, traceback, error, or critical event.

### Resumed-window fingerprint recovery (2026-09-05)

A fresh UI/API observation exposed a separate recovery defect while the
v1.3.21 bot was healthy at 36 buys and 36 sells: `/api/status` proved the bot
running under the allowed TEST 7 mainnet authority, but `/api/fingerprint`
returned an empty value with `source=not_started`. Consequently a newly loaded
window could briefly render the wallet as disconnected even though its bot
still owned the verified wallet lease. The runtime safety fingerprint hash was
independently consistent with fingerprint `736588221`, ruling out an identity
change.

A focused regression reproduced the failure before implementation. The
endpoint now uses the already-frozen runtime wallet identity when the bot is
running but the UI-local startup flag is absent. This path performs no Sage
RPC call; an idle process before risk-disclosure acceptance continues to
return `not_started`, preserving the startup privacy boundary. The focused
endpoint, diagnostics, identity, frontend, safety-UI, and post-build suites
then passed with 259 tests and 4 subtests.

The package was rebuilt cleanly as v1.3.21 with SHA-256
`311B853B962D0424E103BFBF2A8B19A04B2C7A888E518715FC22AF932AFF9182`.
Before replacement the bot stopped cleanly at loop 28 without cancelling its
72 offers. The rebuilt visible app verified Sage 0.13.0, selected TEST 7,
reported a healthy wallet, detected the existing 72-offer ladder, and resumed
it without Coin Prep or reposting. It restarted at exact database/Sage counts
of 36/36, zero pending cancels, zero errors, and an allowed safety gate. After
two completed cycles the counts and safety state remained exact.

A completely fresh browser load then rendered `RUNNING`, `Sage`, and
fingerprint `736588221` rather than `Connect`. After its normal asynchronous
dashboard hydration, Active Settings showed two-sided 36/36 operation, the
45-second loop, fixed spread parameters, exact tier sizes, 10% reserve amounts,
and the configured price limits. The page showed all 72 offers and zero errors,
explicitly classified the TibetSwap outage as unavailable/Dexie-only, and
recorded no browser console error or warning.

### Offer-diagnostic Dexie evidence boundary (2026-09-05)

The next live cross-check found that `/api/offers/diagnostic` returned
`likely_stale_dexie_rows=true` whenever the Sage wallet and local database
agreed, even though that endpoint had not fetched or evaluated any Dexie row.
This was a CATalyst diagnostic defect rather than evidence of a Dexie problem:
local agreement can rule out several local faults but cannot prove an external
row stale.

A focused test first reproduced the unsupported inference. The endpoint now
reports `local_book_consistent`, `cancel_settle_in_progress`, and
`dexie_rows_evaluated` independently; when no Dexie row has been evaluated,
`likely_stale_dexie_rows` is explicitly `null` and the diagnosis states that
the external condition cannot be determined. The full Offers endpoint suite
passed with 42 tests.

The package was rebuilt cleanly again as v1.3.21 with SHA-256
`C0A0AFA5945936BC454A7FE26E1CFBEFBCFE1DFF18AD994DFACA76C48AAF2361`.
The prior package stopped cleanly at loop 13, exact 36/36, zero errors, and an
allowed safety gate; its 72 offers remained live. PID 50828 then verified Sage
0.13.0 and TEST 7, detected all 72 existing offers, resumed without Coin Prep,
and restarted the bot at exact database/Sage counts of 36/36. The packaged
diagnostic returned local consistency true, Dexie rows evaluated false, and
Dexie staleness null, closing the live verification loop for the fix.

### Current Dexie v1 shape and self-competition fix (2026-09-05)

Live Dexie inspection exposed a more consequential compatibility regression.
The current `/v1/offers` response represents `offered` and `requested` as
single asset objects, whereas CATalyst's parser accepted only arrays. It
silently discarded every detailed offer, fell back to anonymous aggregated v3
levels, and consequently counted CATalyst's own best bid and ask as competitor
prices. This was a confirmed CATalyst defect, not Dexie cache lag.

Two focused regressions failed before implementation: one using Dexie's exact
current single-object response shape, and one proving that an attributed
own-only v1 book must not be replaced by anonymous v3 levels. The parser now
normalizes both historical array and current object shapes. The v3 fallback is
also prohibited whenever v1 has attributed a CATalyst-owned offer, because
anonymous aggregation cannot preserve that ownership evidence. The relevant
Market Intel, runtime-monitor, and API suites passed with 98 tests.

Direct source verification against the live Dexie API parsed all 41 buy and 68
sell rows. It identified the current 36 buys and 36 sells as CATalyst-owned and
showed that the remaining externally active rows were also known prior
CATalyst publications, leaving zero attributable competitors. The corrected
source remained `dexie_v1_offers`, with our exact best prices retained and
competitor bid/ask correctly zero.

The clean v1.3.21 package SHA-256 is
`A420F65F5129A1765065A23DE2C95FBA4D7F4F995B55D20B1D94A3043BE1827E`.
PID 48244 again verified Sage TEST 7, detected 72 existing offers, resumed
without Coin Prep, and started safely. After two full cycles the database,
Sage, and Dexie attribution all agreed at 36/36; Dexie's detailed feed reported
41/68 total rows, zero orderbook errors, and source `dexie_v1_offers`. The bot
had zero errors, zero safety blockers, and 10.61-second last-loop time. Fresh
Dashboard and Market Intel renders showed 72 active offers, correct live best
prices, no competitor spread, the explicit TibetSwap-outage Dexie-only state,
and no browser console or page error.

The first sustained packaged sample after that correction advanced from loop 6
to loop 8 over 65 seconds. Database, Sage wallet, and Dexie attribution stayed
exactly 36/36 with no pending cancellation, no orderbook error, no bot error,
and no safety blocker. Splash remained healthy with three peers and zero
failed posts while its daemon received count rose from 5,389 to 6,752. Under
that continuing inbound load, the deliberately capped unclassified queue fell
from 244 to 242 and ignored/classified rows rose from 426 to 540, proving
forward progress rather than a stalled webhook consumer. The current packaged
superlog contained no error/critical entry, traceback, signing failure,
authoritative-state conflict, or recovery blocker; its only webhook match was
the informational line confirming the local Splash callback URL.

The prior stale-Logs report was then re-exercised across a real cycle boundary
in a fresh browser. Logs initially backfilled cycles 0 through 9. After
switching to Dashboard for 52 seconds and returning to Logs, the view
immediately contained cycle 10 without a reload. The visible cycle sequence
remained chronological, TEST 7 fingerprint 736588221 remained visible, and
the browser recorded no console warning, console error, or page error.
### Native bulk-cancel and Splash revalidation (2026-09-05 18:23 BST)

The running packaged v1.3.21 process (PID 48244) remained authoritative on
port 5000 with the bot running, Sage healthy and synced, 25 wallet peers, and
an allowed safety gate with zero operation, reservation, publication-claim,
prepared-creation, or submitted-cancel blockers.  The database and Sage both
reported exactly 36 open buys and 36 open sells, with no pending cancels and a
locally consistent unique-coin book.

The Sage cancellation regression slice was rerun after confirming the native
`cancel_offers` implementation: 67 tests passed across the native method,
adapter outcome, and Cancel All endpoint suites.  This continues to support
the earlier live evidence that one Sage bulk transaction, with one configured
fee, authoritatively cancelled the complete 72-offer cohort.

The remaining Splash warning classification was rechecked against the current
packaged superlog.  Splash launched once, enabled its loopback webhook, kept
the receive watcher active, and reported an empty queue.  The current log had
no webhook-delivery failure, `splash_db_error`, traceback, error/critical
event, or `BAD_AGGREGATE_SIGNATURE`.  A fresh focused Splash runtime,
receive-path, and settings slice passed 77 tests.  This evidence continues to
classify the earlier bounded warnings as transient webhook backpressure rather
than a broken inbound path or an unresolved CATalyst defect.

The live process then advanced from cycle 23 to cycle 30 without changing PID
or configuration.  Wallet, database, and attributed Dexie views remained
exactly 36/36; safety stayed allowed with zero blockers, pending cancels, sync
failures, or runtime errors.  During one timed interval Splash received 2,177
additional offers while retaining three peers, an empty queue, and zero
failures.  No natural market fill or requote occurred in this static-price
window.  Fresh focused lifecycle verification passed 25 requote integration
tests, 23 fill-tracker verification tests, and 104 authoritative fill-closure
tests; the packaged bot continued running at 36/36 after the suites.

A new direct native-window sweep then exercised every operator page in the
same running packaged session.  Dashboard showed v1.3.21, running/synced Sage,
72 offers (36/36), zero fills/PnL/errors, exact 10% reserves, Dexie bid/ask,
and explicit TibetSwap-unavailable/Dexie-only messaging.  Offers showed exact
36/36 depth, 72 active rows, zero pending cancels and zero requote pressure.
P&L showed zero verified and zero pending fills.  Market Intel completed its
asynchronous refresh and showed Dexie/Sage ready, TibetSwap none, the same
bid/ask and 41/68 public depth, Spacescan's 3,477 holders and explicit 100%
explorer gap, plus a running Splash PID with three peers, an empty queue and
zero failures.  Settings Live and Setup both rendered; Setup showed TEST 7
fingerprint 736588221, two-sided Balanced values, 10% reserves, 36/side,
the tier/spare plan, 50 fee coins, and fee 0.0000130791 XCH.  Logs backfilled
startup through cycle 34 in chronological order.  Data Reset correctly kept
all three destructive controls disabled while the bot was running.  Help and
About rendered, with About reporting v1.3.21.  Returning to Dashboard showed
cycle 37 and unchanged 36/36 state, proving navigation did not stall the bot.

### Sustained live checkpoint (2026-09-05 18:41 BST)

The same packaged v1.3.21 process (PID 48244) remained the sole port-5000
owner and advanced from cycle 40 to cycle 42 during independent API samples.
The bot remained running with Sage healthy and wallet-synced. The configured
asset was still MZ_XCH wallet 2 with asset ID
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.

Database, Sage wallet, and Dexie attribution independently remained exactly
36 buys and 36 sells. There were zero runtime errors, wallet-sync failures,
or pending cancellations. The live safety response was fresh and allowed,
owned by this run, on mainnet, with zero operation, prepared-creation,
reservation, publication-claim, or submitted-cancel blockers. Splash was
healthy with an empty publication queue and zero consecutive or total
failures. Spacescan remained available but advisory at 3,477 holders and the
previously identified 100% explorer-price gap. TibetSwap data remained
absent, so the session continued safely on executable Dexie pricing.

At 18:46 BST the focused native bulk-cancel, cancellation-journal, and bot
shutdown regression slice completed with **136 passed in 193.09 seconds**.
The live packaged process was not disturbed by that run: immediately after
the tests it had advanced to cycle 49, was idle between cycles, and still
reported exact database/Sage/Dexie agreement at 36 buys and 36 sells. Runtime
errors and pending cancels remained zero, and the live safety gate remained
allowed with every blocker count at zero.

The next focused Smart Settings and Coin Prep slice passed **181 tests in
21.50 seconds**. It covered the Smart Settings endpoint, deterministic direct
batch planning and execution, confirmed wallet views, top-up thresholds, and
Coin Prep lifecycle integration. The live API independently confirmed the
unchanged two-sided configuration: wallet 2, MZ_XCH asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
14.594 XCH and 70,284 MZ reserves, 36 offers per side, 50 fee-prep coins of
0.001 XCH, and manual transaction fee 0.0000130791 XCH. After the slice, the
same packaged process had advanced to cycle 51 with exact 36/36 agreement,
zero errors, and an allowed safety gate with zero blockers.

Fresh restart/session recovery and UI/API smoke coverage then passed **80
tests plus 4 subtests**, with 54 environment-dependent browser cases skipped
by their declared prerequisites. The exercised slice covered startup-flow
integration, legacy recovery, recovery-before-public-post behavior, status
endpoints, UI smoke behavior, and start-safety gating. The packaged process
remained PID 48244 throughout and advanced from cycle 52 to cycle 53. Its
post-test state stayed running with database, Sage, and Dexie all exactly
36/36, zero runtime errors, and an allowed safety gate with zero blockers.

Market/publication and diagnostics coverage was refreshed with **168 tests
passed in 15.39 seconds** across Dexie orderbook parsing, Splash receive and
runtime paths, Splash settings, Dashboard data, diagnostics layout, and safety
UI gating. The concurrent live sample showed 41 public Dexie buys and 68
sells, with CATalyst's 36/36 correctly attributed; orderbook errors were zero.
Splash remained on PID 42248 with three peers, receive active, an empty queue,
zero failed posts, and its received-offer counter advanced from 45,809 to
46,856 during this checkpoint. Spacescan remained fresh at 3,477 holders with
the explicit advisory 100% price gap. The packaged bot advanced to cycle 55,
still PID 48244, with exact 36/36 agreement, zero errors, and zero safety
blockers.
## 2026-09-05 — full-suite Cancel All boundary test isolation

- A stop-on-first-failure run reached 3,963 passed, 55 skipped and 65 passed
  subtests before exposing an order-dependent failure in
  `test_cancel_all_completed_at_deadline_is_not_reported_as_zero_pending_error`.
- Root cause was the regression test mocking the legacy single-record terminal
  lookup while packaged CATalyst uses `get_authoritative_terminal_records()`.
  Earlier suite state left the real batch database helper available, so the test
  observed an empty real database and falsely reported a deadline error.  The
  production Cancel All loop already evaluates fresh authoritative proof before
  checking deadline expiry.
- The test now supplies proof through the actual batch API.  The focused case and
  the complete Offers endpoint file pass: **42 passed**.  No production trading
  code was changed for this harness defect.
- A normal-collection continuation covering every alphabetically remaining test
  completed cleanly: **1,600 passed, 54 skipped, and 357 subtests passed in
  175.01 seconds**.  An earlier explicit-file diagnostic accidentally included
  `test_spacescan.py`; `tests/conftest.py` intentionally excludes that live API
  diagnostic script, so its pytest fixture error was an operator command
  artifact rather than a CATalyst defect.  No product change was made for it.
- A final clean, normally collected full-suite run remains the definitive
  verification step because the two diagnostic checkpoints are intentionally
  partitioned rather than a single checkout-level result.

### Follow-up order-dependent Cancel All progress test

- A network-isolated full run with `SAGE_RPC_URL=https://127.0.0.1:1` and a
  60-second faulthandler exposed a second legacy mock in
  `test_cancel_all_status_advances_while_serial_retry_is_in_flight`.  Its
  simulated terminal records were wired to the single-record helper while the
  production worker reads the batch helper, so full-suite state made the test
  wait for the production cancellation deadline.
- The regression test now provides its evolving proof map through
  `get_authoritative_terminal_records()`.  The focused progress case and the
  complete Offers endpoint file pass in the network-isolated process: **42
  passed in 3.13 seconds**.  This is test-isolation repair only; production
  cancellation code was unchanged.
- The same diagnostic run identified the earlier long quiet section as
  CPU-bound canonical validation of the 71-member Sage bulk-cancel evidence
  fixture, not a live Sage wait.  The forced closed-port Sage URL confirms the
  test process does not require the active TEST 7 wallet.

### Concurrent live checkpoint

- Packaged v1.3.21 remained the sole app on port 5000 and advanced from cycle
  126 to cycle 150 during diagnostics.  Database, Sage wallet, and Dexie each
  reported exactly 36 buys and 36 sells, orderbook errors remained zero, and
  the safety gate remained allowed with zero blocker counts.
- Splash remained healthy with three peers and advanced to 126,679 received
  offers.  TibetSwap was reachable but had no MZ pool (`tibet_reason=no_pool`),
  so dashboard pricing correctly remained Dexie-only at 0.00008349693 XCH.

### Class-wide batch-proof test isolation repair

- The next normally ordered run showed that several older Cancel All tests
  still supplied authoritative proof through the retired single-record helper.
  With an initialized suite database, the real batch helper returned no rows
  and those synchronous worker tests waited for the production deadline.
- Every proof-producing Cancel All endpoint test now mocks
  `get_authoritative_terminal_records()` directly, including the durable-manager
  route, reconciliation wait, failed-attempt retry, 500-offer authority envelope,
  and coordinator-retry cases.  The intentional assertion that serial lookup is
  forbidden remains unchanged.
- With Sage forced to a closed local port, the complete Offers endpoint file
  passes: **42 passed in 2.74 seconds**.  No production trading code changed.
- The concurrent packaged bot advanced to cycle 185 and remained exact at
  36/36 across database, Sage, and Dexie.  Runtime health was green, the safety
  gate had zero blockers, Splash had three peers and 157,103 received offers,
  and the latest 500 superlog lines contained no signing, recovery, or ERROR
  markers.

### Definitive network-isolated full suite

- After migrating every proof-producing Cancel All endpoint test to the batch
  terminal-record API, a clean normal-collection run completed with Sage forced
  to the closed endpoint `https://127.0.0.1:1`: **5,573 passed, 55 skipped, 5
  collection warnings, and 422 subtests passed in 748.98 seconds**.
- The run crossed the former 70% cancellation deadline stall without delay and
  proves the suite no longer depends on the active TEST 7 Sage service.
- Pytest's slow-test report measured the 71-member native Sage bulk-cancel
  exact-height reconciliation case at **94.85 seconds**.  Correctness is green,
  but this is retained as a bounded-performance investigation before the fresh
  build gate.

### Native Sage bulk-cancel settlement performance fix

- Profiling proved that the long 71-member case was CPU-bound repeated
  validation, not a Sage RPC wait: every safely committed cohort member caused
  the still-blocking cohort to be re-derived and byte-identical immutable
  journal rows and 64-byte provider identities to be canonicalized again.
- CATalyst now retains bounded, exact-input caches for immutable journal-row
  validation and string-only 32-byte identity normalization.  Every canonical
  field participates in the journal cache key, cached journal results are
  immutable and returned as detached dictionaries, changed evidence is fully
  revalidated and rejected, and hostile non-string/unhashable provider values
  remain on the uncached fail-closed path.
- The focused cache, detached-result, changed-evidence, and malformed-provider
  regressions pass.  The 71-member exact-height native Sage `cancel_offers`
  reconciliation proof fell from **94.85 seconds to 25.85 seconds** without
  reducing the per-member durable re-derivation/commit checks.
- The complete cancellation-journal plus reconciliation regression set passes
  with Sage forced to `https://127.0.0.1:1`: **421 passed in 174.48 seconds**.
- During these tests packaged v1.3.21 remained the sole owner of port 5000 and
  advanced through cycle 227.  CATalyst, Sage, the database, and Dexie remained
  exact at 36 buys and 36 sells; the runtime safety gate was allowed with zero
  blockers and the latest 1,200 superlog lines contained zero signing errors,
  authoritative-state conflicts, error/critical entries, or cancel failures.

### Post-fix full suite, clean build, and live recovery

- A fresh normally collected, network-isolated checkout run after both bounded
  caches passed: **5,576 passed, 55 skipped, 5 collection warnings, and 422
  subtests passed in 680.80 seconds**.  The 71-member native Sage bulk-cancel
  reconciliation case remained at **25.66 seconds**.
- CATalyst was stopped through its authenticated loopback GUI endpoint and shut
  down with `cancel_offers=false`, preserving all 72 live offers.  A clean
  `python build.py` succeeded for v1.3.21, purged the previous `build/` and
  `dist/`, verified the executable and bundled GUI assets, and produced a
  10.3-MB executable.
- That exact rebuilt executable started as the sole port-5000 owner.  Sage
  v0.13.0 reached healthy on TEST 7 fingerprint 736588221, and `/api/check-resume`
  authoritatively recovered wallet 2, MZ_XCH asset
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
  with exactly 36 buys and 36 sells.  The bot then resumed without coin prep,
  cancellation, or offer recreation.
- After three new cycles, database, Sage, and Dexie remained exact at 36/36;
  orderbook errors, runtime errors, and safety blockers were zero.  The fresh
  superlog contained zero `BAD_AGGREGATE_SIGNATURE`, authoritative-state
  conflict, error/critical, or cancellation-failure markers.
- The fresh dashboard API returned MZ/USD `0.000120240006480` from
  `market × coingecko`, exactly consistent with MZ/XCH `0.0000835000045` and
  XCH/USD `1.44`.  A browser document left open across the backend replacement
  briefly rendered the obsolete Spacescan explorer price until its live state
  reconnected; the fresh runtime/API value is correct, and stale-document
  reload behavior remains an explicit UI follow-up for the extended monitor.

### Fresh-build full UI audit

- A new headed browser document loaded directly from the exact rebuilt
  v1.3.21 executable and displayed the current runtime rather than the stale
  pre-rebuild document.  Dashboard showed Running, Sage fingerprint 736588221,
  72 active offers (36 buy / 36 sell), 10% reserves (14.594 XCH / 70,284 MZ),
  50 spare fee coins, zero runtime errors, and MZ/USD `$0.000120` from
  `CAT market × coingecko`.
- Offers showed 36 buys and 36 sells with zero pending cancellations; P&L
  correctly showed zero fills for this recovered session.  Settings Live and
  Setup both loaded and preserved the selected wallet, two-sided configuration,
  offer counts, reserve values, 0.0000130791-XCH transaction fee, 0.001-XCH fee
  coin size, and safety status Allowed with no unresolved operations,
  reservations, or publications.
- Market Intelligence showed Dexie ready, Sage ready, Spacescan enabled with
  3,477 holders and healthy token risk, and Splash connected with three peers
  and an active incoming-offer listener.  TibetSwap was explicitly shown as
  having no usable MZ pool; arb gap, pool-depth, and slippage fields were marked
  unavailable and pricing remained Dexie-only.
- Data Reset correctly disabled every destructive control while the bot was
  running.  Help and About opened normally and About reported v1.3.21.
- The Dashboard-to-Logs navigation check immediately backfilled the entire
  current session in chronological order and advanced from cycle 10 through
  cycle 13 while other tabs were being exercised.  All four new cycles remained
  exact at 36 buys and 36 sells.  The only warning was the expected TibetSwap
  no-pool degraded-mode warning; no CATalyst runtime error appeared.
- The exact executable remained the sole owner of port 5000 (PID 63568) after
  the audit.  The persistent goal remains active and the hourly lifecycle
  monitor is extended for the requested additional 12-hour window.

### Extended-window checkpoint after UI audit

- The same packaged v1.3.21 process (PID 63568) advanced through cycle 20
  without restart.  Database, Sage wallet, and Dexie attribution remained
  exact at 36 buys and 36 sells, with zero pending cancels, orderbook errors,
  or wallet-sync failures; the cycle returned to idle normally.
- The live safety endpoint remained Allowed with zero operation, reservation,
  or publication-claim blockers.  The current superlog contained zero
  `BAD_AGGREGATE_SIGNATURE`, authoritative-state conflict, recovery-required,
  error/critical, `splash_db_error`, webhook-delivery-failure, or webhook-
  backpressure matches.
- Splash remained healthy with three peers, an empty queue, zero posting
  failures, and an active receive path.  Its daemon offer counter advanced to
  23,086 while CATalyst's current-run receiver recorded 1,583 deliveries and
  continued classifying new rows.  This is direct current-build confirmation
  that the earlier bounded webhook-backpressure warnings do not represent a
  stalled or broken inbound path.
- The next timed observation reached loop count 21 (completed cycle 20) and
  returned to idle in 9.4 seconds.  All three authoritative offer views stayed
  exact at 36/36 with zero pending cancels, wallet-sync failures, or orderbook
  errors.  Splash advanced again from 23,086 to 24,800 daemon-seen offers and
  from 1,583 to 1,664 CATalyst deliveries with three peers, zero failures, and
  an empty queue.  A fresh whole-log scan still found zero signing, recovery,
  authority-conflict, cancellation-failure, error/critical, Splash database,
  or webhook-backpressure markers.
- The following cross-source checkpoint completed loop count 22 in 10.85
  seconds.  Dexie attribution was freshly refreshed from `dexie_v1_offers`,
  all database/wallet/Dexie counts remained 36/36, wallet balances remained
  145.917146144111 XCH and 702,843.47 MZ total, and 106 fee-class XCH coins
  remained available.  Spacescan still reported 3,477 holders and healthy risk
  without a fetch failure; its cache was 42,973 seconds old, correctly just
  below CATalyst's 12-hour stale/auto-refresh boundary.  Crossing that boundary
  and observing the automatic background refresh is retained as the next
  extended-window check rather than forcing a manual cache mutation.
- That boundary test subsequently completed against the production path.  At
  43,220 seconds the dashboard correctly marked the Spacescan cache stale.
  The next throttled runtime-health pass (not a manual cache refresh) reported
  `Spacescan refresh dispatched`, and the background `spacescan-refresh`
  thread logged `spacescan_cache_refreshed` with 3,477 holders and 100 activity
  records.  The dashboard cache age reset to four seconds, `stale` returned to
  false, and no fetch-failure or prior-cache fallback flag was set.  Trading
  remained enabled and idle between loops with exact 36/36 database, Sage, and
  Dexie views through loop count 29.
- Two later bounded `Splash webhook backpressure active` notices were sampled
  instead of being treated as failures by message text alone.  At the first
  read the receiver was active with three peers, zero failures, an empty
  outbound queue, and only seven unclassified rows; 2,121 rows had already
  advanced to ignored.  Over the next 38 seconds the daemon-seen counter rose
  from 36,744 to 37,699, CATalyst deliveries rose from 2,128 to 2,156, ignored
  rows rose from 2,121 to 2,155, and pending `new` rows fell from seven to one.
  The bot simultaneously reached loop count 31 and remained exact at 36/36 in
  the database, Sage, and Dexie.  This confirms the notices are correctly
  classified transient inbound burst backpressure with rapid catch-up, not a
  stuck webhook, lost delivery, or CATalyst defect.
- A one-minute process-resource sample across subsequent traffic found no
  monotonic growth signal: working set moved from 325.8 MB to 318.4 MB,
  private memory from 277.2 MB to 270.2 MB, handles from 1,158 to 973, and
  threads from 33 to 30 while the same PID advanced from loop 32 to loop 33.
  Splash daemon-seen offers advanced from 39,152 to 40,518 and CATalyst
  deliveries from 2,202 to 2,245; pending `new` rows remained at two, failures
  and queues remained zero, and all three offer views stayed exact at 36/36.
  Safety remained Allowed with zero blockers.
- The longer fresh-build observation reached loop 79 on the same packaged
  v1.3.21 process (PID 63568), still running and idle between cycles with zero
  runtime errors.  Database, Sage, and Dexie remained exact at 36 buys and 36
  sells; cancellation, wallet-sync, and order-book error counters remained
  zero; and safety remained Allowed with no blocker.  Splash remained on three
  peers with an empty queue and zero failures while the daemon-seen offer count
  advanced beyond 106,000.  A later resource sample measured 313.8 MB working
  set, 266.3 MB private memory, 967 handles, and 29 threads.  Relative to the
  earlier loop-32/33 sample, neither memory, handles, nor threads showed a
  monotonic-growth signal during the sustained live window.
- A later bounded Splash backpressure notice at process-log time 21:13:52 was
  independently reclassified after recurrence rather than assumed benign from
  its wording.  By loop 102 the receiver was active, its receive timestamp was
  only seconds old, the daemon counter had advanced to 147,289 offers, all
  3,503 CATalyst-delivered rows had been classified, pending `new` rows and the
  queue were both zero, consecutive and total failures were zero, three peers
  remained reachable, and database/Sage/Dexie were still exact at 36/36.  The
  recurrence therefore remains bounded burst backpressure with proven catch-up,
  not a stuck webhook or lost-delivery defect.
- The same packaged process then reached the 150-cycle milestone after 6,770
  seconds of live bot uptime.  Database, Sage, and Dexie remained exact at
  36/36 with zero runtime errors or safety blockers.  Splash had observed
  231,806 daemon offers and delivered/classified 3,652 rows with zero pending
  rows, queue, or failures.  The fault-signature scan remained empty.  Process
  resources were still bounded at 307.6 MB working set, 259.8 MB private
  memory, 1,012 handles, and 32 threads on PID 63568, continuing to show no
  monotonic-growth signal.
- The packaged process subsequently passed the 200-cycle milestone and
  continued through loop 203 after approximately 9,299 seconds on the same
  PID.  Database, Sage, and Dexie remained exact at 36/36; pending
  cancellations, wallet-sync failures, order-book errors, and safety blockers
  remained zero.  Splash stayed connected to three peers with an empty queue
  and zero failures, while its observed-offer counter continued advancing.
  A fresh scan of the latest 2,500 superlog entries found no
  `BAD_AGGREGATE_SIGNATURE`, authoritative-state conflict, publication or
  reservation recovery requirement, cancellation failure, error/critical,
  Splash database error, or Spacescan refresh error.  Resource use remained
  bounded at 311.2 MB working set, 261.9 MB private memory, 988 handles, and 30
  threads, providing another sustained-window sample without a monotonic
  growth signal.
- A fresh rendered-browser check during the same uninterrupted packaged run
  repeated the Dashboard-to-Logs contract after the 200-cycle milestone.
  Dashboard showed v1.3.21 Running, Sage fingerprint 736588221, 72 active
  offers at 36/36, exact 10% reserves, zero fills and errors, executable Dexie
  bid/ask, 3,477 Spacescan holders, three Splash peers, and explicit
  TibetSwap-unavailable/Dexie-only handling.  Logs immediately backfilled the
  chronological current session through cycle 210, then advanced in place
  through cycles 211, 212, 213, and 214 while the tab remained visible.
  Returning to Dashboard immediately exposed cycle 214 in its activity feed.
  This directly revalidates both initial backfill and continued visible-tab
  updates during the extended stability window.
- The uninterrupted process crossed the local 2026-09-05/06 midnight boundary
  through loop 216 without a rollover fault.  Database, Sage, and Dexie stayed
  exact at 36/36, with zero pending cancels, wallet-sync failures, order-book
  errors, safety blockers, verified fills, or pending fill verification.  The
  post-boundary log scan found no target fault or traceback; periodic wallet
  reconciliations remained close to one second.  Process resources remained
  bounded at 318.4 MB working set, 269.6 MB private memory, 1,019 handles, and
  29 threads, while Splash retained three peers, an empty queue, and zero
  failures.
- The same packaged executable completed cycle 225 after 10,363 seconds of
  uptime.  Its completion event reported 36 buys and 36 sells, matching the
  database, Sage, and Dexie telemetry; pending cancellation, wallet-sync,
  order-book, safety, and Splash failure counters remained zero.  The
  authoritative fills and P&L endpoints still reported zero verified or
  pending fills.  A fresh 3,500-line fault scan returned no target match.
  Resources remained bounded at 312.6 MB working set, 263.7 MB private memory,
  1,087 handles, and 29 threads.
- One further throttled `Splash webhook backpressure active` warning occurred
  near the 225-cycle checkpoint and was re-evaluated from live counters.  After
  the warning, Splash's observed-offer counter advanced from 360,419 to
  372,816, its CATalyst-delivery counter advanced from 3,780 to 3,783, all
  pending `new` work cleared, and the queue and failure counters remained zero
  with three peers connected.  The bot simultaneously advanced to loop 227 at
  exact 36/36.  This recurrence is therefore another bounded inbound burst
  with proven catch-up, not a stalled receiver or unresolved CATalyst defect.
- A post-midnight cross-source audit investigated why Market Intel reported 41
  Dexie buys and 68 sells while the Dashboard showed zero actionable
  competitors.  Direct live Dexie v1 queries and the 72 durable publication IDs
  proved that 36 buys and 36 sells were CATalyst's own rows.  The five remaining
  bids were priced from 0.000020 to 0.000040 XCH/MZ, and the 32 remaining asks
  began at 0.000127, versus CATalyst's inner 0.0000806610 bid and 0.0000863390
  ask.  The raw Dexie totals and raw depth remained exposed separately, while
  the far-out junk guard correctly excluded every remote row from actionable
  competitor bid/ask and count metrics.  The apparently different totals are
  therefore correct raw-versus-actionable views, not a Dexie attribution or UI
  defect.
- The uninterrupted packaged process passed cycle 250 and completed cycle 251
  after 11,518 seconds of uptime.  Database, Sage, and Dexie continued to agree
  at 36/36 with no pending cancellation, wallet-sync, order-book, safety, or
  Splash failure.  The authoritative fills and P&L endpoints remained empty,
  and a fresh 4,000-line scan found no signing, authority, recovery, traceback,
  error/critical, cancellation, Splash-database, or Spacescan-refresh fault.
  Resource use remained bounded at 319.9 MB working set, 272.8 MB private
  memory, 1,014 handles, and 32 threads.
- The next broad hourly checkpoint found one and only one listener on port 5000:
  PID 63568, the exact clean-built v1.3.21 executable in this worktree.  The
  dashboard API identified Sage, wallet ID 2, ticker MZ_XCH, and exact asset ID
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
  Database and Sage remained 36/36 with no pending cancels or fills; the coin
  view reported 164 free and 36 locked XCH coins, including all 50 configured
  fee-class coins, plus 42 free and 36 locked CAT coins.  The correctly nested
  safety response reported Allowed on mainnet, an active lease owned by this
  run, current freshness, action NONE, and zero operation, reservation,
  publication, or submitted-cancel blockers.  The 4,500-line target-fault scan
  remained empty through loop 253.
- The same uninterrupted package passed cycle 275 and completed cycle 277
  after 12,665 seconds of uptime, retaining exact 36/36 database, Sage, and
  Dexie agreement with no pending work or safety blocker.  The authoritative
  fills and P&L endpoints remained empty.  A fresh 5,000-line fault scan found
  no target match.  Process resources remained bounded and were lower than the
  prior milestone at 309.8 MB working set, 261.4 MB private memory, 974 handles,
  and 28 threads, strengthening the evidence against a runtime resource leak.
- The package subsequently passed cycle 300 and completed cycle 301 after
  13,741 seconds of uptime.  Database, Sage, and Dexie remained exact at 36/36
  with every monitored pending/error/safety/Splash counter at zero.  The
  authoritative fills and P&L endpoints remained empty.  Dexie's v1 orderbook
  was 0.3 seconds fresh with zero fetch errors, and Spacescan was not stale.
  A fresh 6,000-line target-fault scan returned no match.  Resources remained
  within the established non-monotonic band at 330.4 MB working set, 284.9 MB
  private memory, 1,073 handles, and 31 threads.

### Completion audit in progress (cycle 306)

The following audit preserves the full user objective and identifies the
authoritative evidence for each requirement before any completion claim.  The
same clean-built packaged v1.3.21 process remained live while the audit was
performed and completed cycle 306 at exact database/Sage/Dexie counts of 36
buys and 36 sells.  Pending cancellations, wallet-sync failures, order-book
errors, safety blockers, Splash queue entries, and Splash failures were all
zero, with three Splash peers connected.

| Requirement | Authoritative evidence | Audit status |
| --- | --- | --- |
| Correct worktree and packaged candidate | Post-fix full-suite/build record and exact live package recovery above; sole PID/port ownership repeatedly rechecked through cycle 306 | Proved |
| Mainnet TEST 7 identity, Sage fingerprint 736588221, wallet 2, MZ_XCH, and exact MZ asset ID | Fresh-build recovery, broad hourly checkpoint, and continuous authenticated telemetry | Proved |
| Balanced Smart Settings, two-sided 10% XCH/MZ reserves, 36 offers per side, fee inventory, transaction fee, and unchanged risk profile | Direct packaged Settings/UI/API evidence plus the 181-test Smart Settings/Coin Prep slice | Proved |
| Coin Prep planning, execution, top-up, confirmation, failure recovery, and acceptable direct-batch performance | Direct packaged preparation/top-up evidence plus 345-test and 181-test focused groups | Proved |
| Bot creation, start, run, stop, restart, and existing-session recovery | Multiple packaged stop/rebuild/resume/recreate sequences and current uninterrupted run | Proved |
| Offer creation, fill closure, replacement/requote behavior, and durable fill safety | Confirmed isolated on-chain fill at height 9183928 plus focused fill/requote/authoritative-closure suites; no natural fill occurred in the current static-price window | Proved without claiming a current-window fill |
| Cancel All through Sage native `cancel_offers`, one configured fee, authoritative settlement, crash/transient recovery, and BAD_AGGREGATE_SIGNATURE protection | Three direct 72-member packaged bulk cancellations, shared transaction evidence, 72/72 terminal proof, 146/176/421-test cancellation slices, and post-cache full suite | Proved |
| Every operator tab, Dashboard/Logs backfill and live advance, destructive reset gating, Help/About/version | Repeated headed all-tab sweeps; extended-window Logs advance from cycle 210 through 214 and Dashboard reflection | Proved |
| Dexie, Splash, Spacescan, and TibetSwap-degraded reconciliation | Direct Dexie v1 comparison and ownership attribution, Spacescan API comparison/automatic cache refresh, Splash progress/backpressure samples, and explicit TibetSwap no-pool/Dexie-only behavior | Proved |
| Safety gating, wallet authority, lease heartbeat, publication/reservation recovery, signing and authoritative-state protections | Direct allowed-state snapshots, fixed transient lease retry, focused safety/recovery suites, and repeated whole-log fault scans | Proved |
| Fresh regression and build gate | 5,576 passed, 55 skipped, 422 subtests; clean `python build.py`; exact resulting executable used for the active run | Proved |
| Sustained clean live window with no unresolved confirmed CATalyst defect | The exact package remained uninterrupted for more than four hours and reached cycle 350 with exact 36/36 agreement, zero whole-log target fault matches, bounded resources, and zero monitored pending/error/safety/Splash counters | Proved; the separate hourly monitor remains active through 08:30 for the user's additional observation period |

- The first post-audit checkpoint completed cycle 310 at 01:10:57 BST.  The
  exact clean-built executable remained responsive and the sole port-5000
  owner (PID 63568).  Database, Sage, and Dexie stayed exact at 36/36;
  cancellation, sync, order-book, safety, Splash queue, and Splash failure
  counters were zero, with three peers connected.  A fresh 7,000-line scan of
  the current superlog found zero target fault matches.  Process resources
  remained inside the established non-monotonic band at 310.3 MB working set,
  262.9 MB private memory, 1,155 handles, and 30 threads.
- A fresh rendered-window cross-check at cycle 314 independently matched the
  telemetry: v1.3.21 Running, Sage fingerprint 736588221, 72 active offers at
  36/36, exact 10% reserves, 50 fee coins, zero fills and errors, executable
  Dexie bid/ask, 3,477 Spacescan holders, three Splash peers, and explicit
  TibetSwap-unavailable/Dexie-only fields.  Logs immediately rendered the
  chronological current session through cycle 313, including the latest
  bounded Splash-backpressure notices.  Live counters around those notices
  continued to advance from cycle 311 through 313 while Splash pending work,
  queue, and failures were zero; the notices therefore remain the already-
  proven transient inbound-burst classification rather than a new defect.  The
  visible app was returned to Dashboard.
- At cycle 318 one newly delivered Splash row was briefly unclassified while
  the queue and failure counts remained zero.  The immediately following
  cycle classified it and returned pending `new` rows to zero while the daemon
  observed another 2,319 offers.  This is another direct non-accumulation
  sample for the bounded inbound-burst path; all database/Sage/Dexie counts
  remained 36/36 and safety remained allowed.
- The uninterrupted package passed cycle 325 and reached loop 326 after roughly
  four hours of current-process bot uptime.  Database, Sage, and Dexie remained
  exact at 36/36, with every telemetry failure, pending, and safety counter at
  zero.  PID 63568 remained responsive and the sole port-5000 owner.  A fresh
  7,500-line fault scan returned zero target matches.  Resource use remained
  non-monotonic and bounded at 329.6 MB working set, 283.3 MB private memory,
  916 handles, and 30 threads.

### Final verification-before-completion gate

- A fresh, complete, normally collected repository run was executed with Sage
  forced to the closed loopback endpoint `https://127.0.0.1:1`.  It terminated
  successfully with **5,576 passed, 55 skipped, 3 collection warnings, 422
  subtests passed, and zero failures in 670.84 seconds**.  The warnings are the
  three known helper classes with constructors.  This fresh full run includes
  the build/post-build, lifecycle, Coin Prep, Smart Settings, bulk cancellation,
  safety, recovery, wallet, market-source, Splash, Spacescan, and UI-contract
  coverage identified in the audit table.
- During that full-suite load the exact packaged v1.3.21 bot remained live and
  advanced to cycle 350.  Database, Sage, and Dexie remained exact at 36 buys
  and 36 sells; pending cancellation, wallet-sync, order-book, safety, Splash
  queue, and Splash failure counters remained zero, with three peers connected.
- The exact running executable remained the sole owner of port 5000 as PID
  63568.  Its SHA-256 was
  `00BEA6C8809A9BA595F2E2A75FC7E6E88FE453EFA2F3ADE6AD209B6FC9F01143`,
  its size was 10,799,926 bytes, and the source/package version was 1.3.21.
  A scan of the entire current packaged superlog returned zero target fault
  matches.  `git diff --check` exited zero; its only output was Git's advisory
  CRLF-to-LF conversion warning for `_version.py`, not a whitespace error.
- The requirement-by-requirement audit above therefore has direct current-state
  evidence for every objective item and no unresolved confirmed CATalyst defect.
  The remediation/stability goal is complete.  The separate hourly heartbeat
  remains scheduled through 08:30 BST to honour the user's requested additional
  observation period without withholding the already-proved completion result.
