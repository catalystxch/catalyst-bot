# a3b299c response boundary and primary live read-only restart

The Bootstrap stop endpoint previously returned the cancellation manager's
full result object. A focused red regression supplied an unexpected
`traceback` field containing a private wallet path and token; the HTTP 200
response exposed it. Source commit
`a3b299c5356a8b5e7f678e1eac9d8131165b140c` projects each result to
the validated public `outcome` field. The regression passed after the fix.
All 44 Bootstrap API tests, 15 opt-in cancellation and recovery browser tests,
Ruff, format and diff checks passed. The full local Windows backend suite
finished with 7,177 passed, 210 skipped and 427 subtests passed in 37:05;
all 11 PR #220 checks passed on the exact source head. PR #220 remains draft.

A clean detached source build at
`E:\catalyst-bootstrap-public-response-a3b299c-build\dist\Catalyst\Catalyst.exe`
has SHA-256
`F9E02BF9111937E292A2FF12E92F4A38448CC3209F678F13806E6965B4F69617`.
The bundled UI retained hash
`11275B592DEE766B1F0E8DBE48967AE1E50759E2ACD357FDBA0E61C2126CB3E6`.
The acceptance ZIP hash is
`3E646746240C5630B12F6FDA7985EE9F22F48DEB79490D84B2AE49D77998E02A`
and the unsigned installer hash is
`80802F514C511F55E28F8BC5A8C22E46E91E225BEED029D131BD161A3560F511`.
Both are pinned at artifact commit `e4efa5f95146d225864c2ca45b84f15e3b865ebf`;
independent HTTP downloads matched. ZIP CRC and contents, packaged API,
synthetic Sage, recovery, native clean/duplicate/persisted/safety, isolated
installer clean install/installed API/Sage/uninstall, and Defender scans passed.

The prior exact f5 app was shut down through its native UI with cancel-all
unchecked. The a3 EXE was launched against the original TEST 7 profile and
its Risk Disclosure acknowledged under the operator's existing testing
authorization. PID 126496 was the sole `127.0.0.1:5000` listener, and its
path and file hash matched the clean build. The native wallet picker selected
TEST 7 fingerprint `736588221`. Sage finished startup and the optional Splash
setup gate appeared. The available computer-control input could not scroll
that gate to its footer in the 1000×700 window; the native Splash skip/start
step and subsequent full interactive UI acceptance remain unverified on a3.
No API call was used to dismiss the gate.

An independent Chromium check of the exact served page at a 1000×700 viewport
showed the Splash overlay's `overflow-y: auto`, `clientHeight=700` and
`scrollHeight=929`. A normal browser wheel event moved `scrollTop` from 0 to
its 229-pixel maximum and put the Skip button entirely in view. This narrows
the native obstacle to the computer-control input or its window context; the
browser rendering itself is scrollable. The separate browser was closed after
this read-only check.

A separate browser session connected to the same stopped exact a3 app and
selected the already-bound MZ/XCH pair. The Dashboard showed TEST 7 fingerprint
`736588221`, Sage synced, Follow mode, no active Bootstrap campaign, and a
disabled Start Bot control pending setup review. The Offers view showed zero
active buy/sell offers and zero pending cancels; its History view showed the
three previously confirmed MZ buys. P&L rendered confirmed-evidence totals,
and Market Intelligence rendered RED confidence with Splash unavailable. In
Settings, Follow remained selected and the Coin Prep summary reflected Follow
settings. No Save, Start, Stop, Cancel or campaign control was used. After the
browser was closed, read-only app and Sage checks again showed unchanged
balances, zero pending and fillable offers, inactive Bootstrap, stopped bot,
synced wallet and ALLOWED safety with zero blockers. This passes browser-based
live read-only traversal of the exact app; the native Splash and full native
UI gates remain open.

Read-only live endpoints after Sage connection reported a healthy synced Sage
wallet, stopped bot, zero consecutive wallet failures, mainnet fingerprint
`736588221`, CAT wallet ID `2`, and MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`.
`/api/dashboard` read live spendable balances of 138.470301476875 XCH and
780212.284 MZ; subsequent `/api/status` echoed them. The wallet facade
returned zero pending transactions. Sage's complete 4,095-record offer history
returned zero fillable offers, and the app returned zero open offers. Bootstrap
reported no active campaign or attention requirement. Runtime safety was
ALLOWED with all blocker counts zero and the current run owning the lease.
The previous campaign remained stopped; no new campaign, wallet transaction,
offer, or fee approval was created in this read-only restart.

The live wallet lifecycle, native Splash footer and full UI, both 24-hour
windows, and final review remain open. The secondary host independently
checked this exact source and package in isolated mode; its original-profile
and native UI gates remain open. Keep PR #220 draft; no main merge, tag,
release, or public-readiness claim.

## Additional live browser UI and Doctor check

On 2026-10-04, a fresh Chromium session connected to the same exact a3
process on `127.0.0.1:5000`. The Logs tab backfilled startup, wallet
selection, CAT discovery, pair-selection, and Dexie refresh events. The live
Doctor completed in 16.6 seconds with nine passing checks and one warning:
the optional local Splash daemon was not running. The nine passing checks
covered database, configuration, exact CAT identity, wallet reachability,
wallet sync, signing ability, CAT wallet mapping, Dexie reachability, and
Spacescan setup. TibetSwap was explicitly reported as retired.

Data Reset, Help, and About rendered in the same session. Data Reset exposed
three separate confirmation-gated actions; none was used. Help displayed the
current Sage/Dexie/Splash authority and Bootstrap workflow. About reported
CATalyst v1.4.0. No reset, configuration save, campaign, bot, offer, or wallet
action was taken. The browser session was closed. An immediate read-only
post-check still showed a stopped bot, healthy synced wallet, TEST 7
fingerprint `736588221`, the exact MZ asset, spendable balances of
138.470301476875 XCH and 780212.284 MZ, zero open offers, no active
campaign, and runtime safety ALLOWED with zero blockers. This completes the
read-only browser tab traversal on the exact live package, but does not
substitute for native UI control or a live trading lifecycle.
