# Escape wallet coin counts in the Coin Prep skip warning

Draft PR #220 exact source `2028c842fd1dd9953162360a6a72c1f8d0234c0b`.

The skip-prep warning displayed `xch_coins` and `cat_coins` from
`/api/coin-prep/status` with `innerHTML` without escaping them. That endpoint
can overlay counts from the local worker status JSON, so it did not enforce a
numeric type for every response. An injected markup value was parsed as HTML
in the warning. The new browser regression passed a malformed count through
the real warning function and failed before the fix. The fix escapes both
counts at the HTML sink. No campaign or wallet action is involved.

The targeted Chromium regression passed after the fix. The complete opt-in
Chromium suite passed **227 tests in 177.92 seconds**. The exact detached
`2028c84` checkout passed the complete serial Windows backend:
**7,277 passed, 228 skipped, 433 subtests passed in 1282.82 seconds**. The
additional skip is the new opt-in browser regression. Ruff check and format
of the modified test passed. All eleven exact-source PR checks passed on
`2028c84`. All eleven checks also passed on docs/evidence-only head
`5a2845ec5d62caca31017e7721fc1fd572c38924`.

The detached checkout `E:\catalyst-skip-xss-2028c84-build` built the clean
Windows bundle successfully with PyInstaller 6.21.0 and release version 1.4.0.
The 206-entry ZIP passed CRC and contains exactly one Catalyst.exe whose hash
matches the clean build. Inno Setup 6.7.3 compiled the unsigned installer.
Defender custom scans of the bundle, ZIP, and installer added zero detections
(six historical detections before and after).

The ZIP, installer, and manifest are pinned at artifact commit
`4091ad24017c83ce18f5d13375498037520ca5f1`. Independent HTTP downloads
of the pinned ZIP and installer matched the hashes below:

- [ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/4091ad24017c83ce18f5d13375498037520ca5f1/acceptance-artifacts/CATalyst-2028c84-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/4091ad24017c83ce18f5d13375498037520ca5f1/acceptance-artifacts/Catalyst-Setup-2028c84-1.4.0.exe)

| Artifact | SHA-256 |
| --- | --- |
| Clean `Catalyst.exe` | `78274A4BC08C4514243E0FEEA652518542F5375946C9AE92369221C09B8B7842` |
| Bundled `bot_gui.html` | `AF054A67393C80C760DAB00D03BD6BF416959FB13117E05125FCDADB516C6ECF` |
| `CATalyst-2028c84-primary-acceptance.zip` | `96E49DEA9289FA91C414A244A0FA4535BFE648186BE515A4DF04B003F8A13B83` |
| Unsigned `Catalyst-Setup-1.4.0.exe` | `11A3343075DE3BD705896327E5EF525A04400DF2EC4B717C4A5146851AAF3E15` |

The exact bundle's separate QA installer used AppId
`{0F49699E-DC74-4F8E-8A31-B123B51790E7}` and the E: QA install directory.
It compiled with Inno Setup 6.7.3 (QA installer SHA-256
`BB42C00A062FBC7FF2EF8B1C5F36D905EF1F7EE423370DC82595B53D56DDF204`).
A silent current-user clean install exited 0, registered version 1.4.0 in the
QA key, and installed an EXE matching the clean-build hash. A silent uninstall
exited 0 and removed the QA EXE and registration; the original TEST 7 process
and port owner remained unchanged. The QA installer has a deliberately
different AppId and hash from the pinned distributable.

The exact packaged worker passed the isolated synthetic Sage mTLS RPC smoke,
including certificate loading and fingerprint 123456789 against the mock
endpoint. Packaged publication-recovery smoke remains open for this exact
bundle. Live original-profile API and Sage reads are recorded below.

## Original TEST 7 read-only rollover

The preceding `a5f4074` process was the sole expected PID and port 5000
owner, with synced Sage, stopped bot, zero offers, and allowed safety. It
closed through its desktop window with no port listener remaining. Its monitor
ended at `2026-10-06T12:22:09Z`; that trace is historical for this new
runtime candidate.

The exact `2028c84` EXE started as sole PID 108228 and sole port 5000 owner.
Browser startup acknowledged the testing Risk Disclosure under the operator's
existing authorization and selected Sage mainnet TEST 7 fingerprint
736588221. A fresh dashboard read populated the pre-bot balance cache. The
read-only app state then showed CAT wallet 2 and exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, stopped bot, unchanged 138.470301476875 XCH and 780212.284
MZ, zero open offers, inactive Bootstrap, and allowed safety with an owned
lease. Independent read-only Sage checks found zero pending transactions and
zero fillable offers in the complete 4,095-offer history. The prior campaign
remains stopped with zero authoritative fee spend. No new campaign or wallet
effect was initiated.

Exact-PID/path/hash stopped-profile safety and port-owner monitors began at
`2026-10-06T12:27:21Z` and `12:27:19Z` under
`E:\catalyst-stability-monitor-2028c84`; their first samples passed. The
24-hour stopped-profile gate cannot pass before `2026-10-07T12:27:21Z` plus
complete trace and end-state review. A read-only live Chromium traversal after
startup covered Dashboard, Offers, P&L, Market Intel, Settings, Logs, Data
Reset, Help and About. Each navigation selection became current, both info
modals opened, and there were no page errors. Post-traversal app state still
showed the stopped bot, zero open offers, unchanged balances, inactive
Bootstrap and allowed safety.

The exact native desktop window was then exercised on the same PID. Its testing
Risk Disclosure was acknowledged under the operator's prior authorization,
Sage connected, the existing Spacescan configuration was retained, and
`MZ_XCH` selected. The native Dashboard showed the selected pair and stopped
bot. Offers showed zero active bids and asks; P&L showed prior confirmed
history; Market Intel showed RED confidence and Splash unavailable; Settings
showed fingerprint `736588221` and both Setup and idle Live views; Logs
backfilled current-session CAT discovery and pair-selection events. Data Reset
was inspected without pressing a reset action. Help and About opened and
closed, and the window returned to Dashboard. No start, settings save, Coin
Prep, campaign, offer, or wallet action was taken. A post-traversal read-only
API check showed the same EXE hash, correct mainnet/MZ identity, unchanged
balances, zero open offers, inactive Bootstrap, and ALLOWED safety with an
owned lease. This completes the inactive native UI traversal; active-state UI,
active-offer lifecycle/recovery, secondary original-profile acceptance, both
final-candidate 24-hour windows, and final review remain open. PR #220 stays
draft.
