# Secondary original-profile read-only acceptance — 74da24c

Date: 2026-10-05 (Europe/London)

## Scope

This secondary-PC pass tested exact runtime/source
`74da24c34c0e107ff4c4bf9be7a719e8ae3777d0` with the original Harvestr
profile, after verifying its authoritative backup. The bot was never started.
No Coin Prep, fee approval, offer create/cancel, campaign mutation, or data
reset occurred.

The evidence-only commit containing this report is based on the later feature
branch documentation head so it can fast-forward cleanly. This acceptance
result itself is deliberately bounded to the exact 74da24c runtime candidate.

## Exact identities and packages

- Detached source under test:
  `74da24c34c0e107ff4c4bf9be7a719e8ae3777d0`
- Fresh secondary build: PASS (`py -3.14 build.py`), Python 3.14.3,
  PyInstaller 6.22.3
- Secondary build EXE SHA-256:
  `569404987BFFD97938141682F5C59983416AEB996AC1A79EC182D6984AE7CA92`
- Source and bundled `bot_gui.html` SHA-256:
  `2778E110E3E358D05E6E84E9EE8645AD71233FCDCB9D396BD219D62D4774D6F5`
- Pinned artifact provenance commit:
  `7b90d6dca999eec6a3e28083037b581484255b01`
- Downloaded ZIP size: 36,476,935 bytes
- Downloaded ZIP SHA-256:
  `7120A8B1490D8EE551210F57372FF8BA65637A9CA1698796559758C0215334AB`
  (exact expected match)
- Extracted pinned EXE size: 11,276,460 bytes
- Extracted pinned EXE SHA-256:
  `C03A78147CDAA3532F6F103E46328DEA53F6FF3B41F51F3FEA1E8134709B4664`
  (exact expected match)
- Verified running pinned-package process: PID 15956 at the extracted exact
  path with the same EXE hash

The fresh build marked `src/catalyst/_version.py` modified because of checkout
line normalization. Its Git blob remained exact: `git hash-object` and
`HEAD:src/catalyst/_version.py` both resolved to
`119dfcaadcc2a528d6308dab1f566f5781632db8`. No source delta was tested.

## Independent tests on the exact integrated candidate

- Affected backend breadth: 131 passed
- Chromium E2E: 223 passed in 146.67 seconds
- Targeted blocked/error and timeout browser cases: 2 passed
- Stop/quiescence race repetition: 20/20 passed
- Ruff and diff check: PASS
- Packaged API and Sage mock RPC smokes: PASS
- Upgrade/publication recovery smoke: PASS
- Desktop clean launch, duplicate handoff, persisted relaunch, and native
  startup-safety smokes: PASS

Primary-provided exact-source result, recorded for comparison rather than
claimed as a second local full-suite run: 7,218 passed / 224 skipped / 431
subtests and Chromium 223 passed.

## Profile preservation

Authoritative backup remained untouched:
`backups/harvestr-original-before-6e4d61d-20261005T1845BST` (23 files,
283,332,889 bytes).

The profile `.env` hash was unchanged before and after every launch:
`A73F8C9D64EC1E07B864F18D7A91C110984C33B21FBBEBE28D2D399D1BCD68D5`.

Final hashes after three graceful package cycles:

- `bot.db`:
  `B2AA80ECB8449CB30D66F85BD7DD944894713632539572F336505B0D3F1183FA`
- `bot.db-wal`:
  `8295B5F01A434D2E351279B3BE8AEA6315364C001E26C7D2D45A23BF7E424A48`
- `bot.db-shm`:
  `5C34304037FB1FB376EE8258204ABF35BDB48CFA0E3A6CF00769A35B8C1A8CD8`

The DB/WAL/SHM changes were limited to expected startup, health, log, lease,
and graceful-shutdown activity. Final durable state: inactive released lease,
resolved safety latch with no blockers, and zero open offer rows.

## Sage and CATalyst state

Direct Sage mTLS RPC and CATalyst APIs agreed:

- Wallet: Harvestr test wallet
- Fingerprint: `3702373391`
- Network: mainnet
- Sage: 0.13.0, supported; BLS signing secrets present
- CAT wallet ID: `2`
- Pair: `MZ_XCH`
- MZ asset:
  `b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`
- XCH: `240.800676512155` total/spendable
- MZ: `3381521.72` total/spendable
- XCH coins: 216 free, 0 locked
- MZ coins: 140 free, 0 locked
- Sage sync: 19,425 / 19,425 coins
- Pending transactions: 0
- Sage offers: 949 = 818 cancelled + 131 expired; fillable 0
- CATalyst offers: 0 buy / 0 sell
- Reservations, fee holds, unresolved fee operations: 0
- Bot and Coin Prep: stopped
- Safety while running: ALLOWED with owned renewing lease
- Final shutdown: lease inactive/released, latch resolved, CATalyst and Sage
  closed, no port 5000 listener

Balances and all zero counts were unchanged after restart and after the pinned
package smoke.

## Campaign and fee state

- Campaign:
  `d61791de6807761e4a81c2a3ce58fb7b2ebad2dd012593ba0a37a122198694d5`
- State: active but expired, `cancel_required=true`,
  `manual_restart_required=true`, zero open offers
- Durable campaign `fee_spent_xch`: `0.000037339821`
- Latest immutable approval:
  `1b8f1d017baa03ce2b83b3cfb877d9e93f7de4fa20c5db7534af589b6e7c588f`
- Cap: 0.1 XCH; approval committed/spent accounting: 82,338,193 mojos
- Held: 0; unresolved: 0; dispatch authorized: false
- `fee_resume_required=true`; overlapping Coin Prep blocked

The app correctly surfaced that protected campaign stop is required before
restart or renewal. This pass did not alter the campaign.

## GUI and restart results

PASS: Risk Disclosure, exact Sage wallet chooser, Dashboard, Offers, P&L,
Market Intel, Settings Setup and Live, Logs, Help, About, Doctor, shutdown,
restart/recovery, and the independently downloaded pinned package.

All three Data Reset choices were exercised only to their irreversible-action
confirmation: Reset P&L, Clear History, and Full Reset. Each confirmation was
cancelled. No reset request was dispatched.

Doctor: 8 passed and 2 legitimate warnings. The warnings were Splash
unreachable and a configured Spacescan Pro URL without a Pro API key. Database,
configuration, Sage reachability/sync/signing, CAT mapping, and Dexie passed.

Market confidence remained RED/INVALID because attributable depth was
out-of-range, single-provider dependent, and expired. Creation, requote, and
exposure increase were denied as required. No gate was bypassed.

Shutdown correctly described wallet-wide cancellation, defaulted its checkbox
to unchecked, and was completed with cancellation unchecked while fillable
offers were zero.

Native computer-use automation could not initialize on this PC because its
helper failed to write kernel assets (`path not found`) after three attempts.
GUI acceptance therefore used Playwright Chromium against the exact package's
sole localhost process with DOM assertions and local screenshots. This is an
automation-environment limitation, not a CATalyst defect.

## Result

No new reproducible CATalyst defect was found. No runtime/source change or fix
PR was produced.

**PASS for exact 74da24c original-profile read-only startup, restart, package,
and GUI scope.** Broader release readiness remains separately gated by the
newer feature-branch head, protected expired-campaign handling, RED external
market confidence, and primary-owned live/long-duration acceptance.
