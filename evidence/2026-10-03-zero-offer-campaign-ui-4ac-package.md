# Expired zero-offer campaign UI and exact 4ac831f Windows package

Draft PR #220 exact runtime/source is
`4ac831fbca007c9ebd7ca4000149d13bc9f3532d`. The TEST 7 profile still
has an expired campaign marked active, but its MZ offer table has zero open
offers. The existing Bootstrap UI called this state “cancellation required for
open offers,” labelled the action “Stop & Cancel Campaign Offers,” and reported
zero cancellations as “0 ... cancellation(s) submitted.” Those statements
misrepresented the action the backend would take.

The new browser regression reproduced the misleading status before the UI
correction and the zero-cancellation success message before that correction.
After the fix, an expired campaign with a known zero offer count says to stop
the campaign before renewal, shows “Stop Campaign,” confirms that there are
no campaign-owned offers to cancel, and reports a clean stop without implying
a wallet cancellation. Unknown or nonzero offer counts retain the protected
cancellation copy. The POST body remains bound to the exact campaign ID and
revision; no wallet or campaign state was changed during browser testing.

The related Chromium file passed 12 tests and the complete Chromium suite
passed **205 tests**. Ruff, formatting and `git diff --check` passed. All 11
PR checks passed on the exact source commit. The unchanged backend had passed
the full primary Windows suite at source `f97efd7`: 7,148 passed, 205 skipped,
427 subtests. An isolated 34-test Bootstrap API run at preceding test-only
commit `dd7f5de` proved zero-offer retirement avoids the wallet cancellation
manager and fee approval.

## Exact Windows package

- Detached clean build: `E:\catalyst-4ac-primary-build`
- EXE SHA-256: `89A29B4CA31050CEDFA657364A5905C302121FC1E288D0DAE8519A6A1FE1461C`
- Bundled `bot_gui.html` SHA-256: `25B8033FF77E8AD35A9A9A50066F7B837FDDEF0C6BD590D95874D541A6C4893C`
- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7393d7a7cb8dcb2b7ee24b081002a3cdda1815b0/acceptance-artifacts/CATalyst-4ac831f-primary-acceptance.zip), SHA-256 `1A096E69FE7790109D919A90AA18D1F477456E5199312D41BCAF7BAAB2CBE27F`
- [Unsigned test installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7393d7a7cb8dcb2b7ee24b081002a3cdda1815b0/acceptance-artifacts/Catalyst-Setup-4ac831f-1.4.0.exe), SHA-256 `68D1D12CBF605E26BBEC9AA2B2E7E57205822B27348398A37B4CEE629DA106F1`
- [Artifact manifest](https://raw.githubusercontent.com/catalystxch/catalyst-bot/7393d7a7cb8dcb2b7ee24b081002a3cdda1815b0/acceptance-artifacts/CATalyst-4ac831f-primary-acceptance.md)

The ZIP contains 192 files, passed a complete CRC read, and its embedded EXE
and UI hashes matched the detached build. Packaged API, mock Sage RPC,
publication recovery, and native clean/duplicate/persisted/safety smokes
passed. Defender custom scans of the bundle, ZIP and installer returned zero
matching detections. Independent HTTP reads of both pinned artifacts matched
their hashes.

A unique-AppId, separate-directory installer sequence installed exact
`f97efd7`, upgraded to `4ac831f`, rolled back to `f97efd7`, then restored
`4ac831f`. Each completed installer log and installed EXE hash matched the
expected build. The upgraded package passed installed API and mock Sage
smokes; restored `4ac831f` passed API again. Final uninstall succeeded and
left neither the QA directory nor its registry key. The installer test did
not open the original profile or contact the live wallet.

## Open live gates

The exact `4ac831f` package has not run against the original TEST 7 profile.
The app was offline at the latest process/port check. The 2026-10-03 read-only
SQLite check showed the expired `c275b953...` campaign still marked active,
zero open MZ offers, zero latest blocking offer operations, and no campaign
fee spend. The prior Sage read-only preflight confirmed mainnet TEST 7
fingerprint `736588221`, CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
zero open wallet offers and zero pending transactions. These are checkpoints,
not action-time authorization. The operator must manually launch the exact
EXE, personally acknowledge Risk Disclosure and connect Sage; automatic
approval review previously blocked a predecessor live command-tool launch
before execution. New campaign approval and consequential mainnet actions
need separate operator handoffs after a fresh identity, balances, offers,
safety and ledger preflight. Exact live lifecycle, restart/recovery, full
interactive UI, both 24-hour windows, independent secondary acceptance and
final review remain open. Keep PR #220 draft; no main merge, tag, release or
public-readiness claim.
