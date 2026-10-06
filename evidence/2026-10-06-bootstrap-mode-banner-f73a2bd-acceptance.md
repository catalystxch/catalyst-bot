# Bootstrap mode banner refresh and exact f73a2bd acceptance

Draft PR #220 source/runtime commit: `f73a2bd85be1ba205542530ca3752b6feaa6c04e`.

The original-profile native UI could show **Follow mode** in its global banner
after the unsaved Market Mode selector changed to Bootstrap, and could retain
**Bootstrap selected** after changing back to Follow. Navigating away refreshed
the banner. `bootstrapModeChanged()` updated the local review controls but did
not fetch and render the durable Bootstrap authority state. The focused
Chromium regression failed on the original source with the Follow banner still
visible after selecting Bootstrap. The fix calls the existing read-only
`bootstrapRefreshStatus()` on a mode change and returns its Promise. The same
test then passed in both directions without a page change. A failed status
fetch retains the last authoritative banner, as before.

Verification on the exact source:

- Focused new regression and two adjacent Bootstrap banner tests: 3 passed.
- Full Chromium E2E: 224 passed in 151.95 seconds.
- Full local Windows Python suite: 7,243 passed, 225 skipped, 431 subtests
  passed in 1,268.53 seconds.
- Ruff check, Ruff format check, and `git diff --check`: passed.
- All 11 PR checks passed on exact source `f73a2bd`.
- Independent secondary source review and complete Chromium suite: 224 passed;
  no new safety defect found. Secondary report SHA-256
  `3FEE49F62CF74564E75BF09756A528AB938351DF0C7C940C524A86214DF22F9C`.

## Clean Windows package

The detached build checkout `E:\catalyst-bootstrap-banner-f73a2bd-build` was
at the exact source commit before `python build.py`. Generated version metadata
was confined to that checkout. The accepted optional
`importlib_resources.trees` hidden-import warning remained.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `214EE6D4DCB0C6B7A00876F5F837CB6FB466BD32A2F3CCD4DD57267E95266F78` |
| Bundled `_internal/bot_gui.html` | `9FD727C40DA72C56BE948B4BFBBD4205B8B2DE33B772ACAF32C5E5DCB37B1801` |
| Acceptance ZIP | `F5C953658AA47301DB08A1848FC7E7BD719815556A166F1F610E9E6A7438CBFF` |
| Unsigned installer | `CC6826543807998B6D5F9AA8908B35FD1216DEDEA81352EB235AC4925994D758` |

Packaged API, synthetic Sage RPC worker, publication-upgrade recovery, and
native clean/duplicate/persisted/safety launch smokes passed. The 206-entry ZIP
passed CRC, and its embedded EXE matched the clean EXE hash. Inno Setup 6.7.3
compiled the unsigned 1.4.0 installer. A separate unique-AppId QA installer
`{37CB2DA7-6C54-4F9F-9A5E-970826E2F357}` installed to an isolated E:
directory; its EXE hash and packaged API passed, and uninstall removed its EXE
and unique HKCU registration. Defender custom scans of the bundle, ZIP and
installer reported zero matching detections.

Artifact commit `b5c9856e6c0e42fc98e546192d1c534a59e3d1fa` pins the
[acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/b5c9856e6c0e42fc98e546192d1c534a59e3d1fa/acceptance-artifacts/CATalyst-f73a2bd-primary-acceptance.zip)
and [unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/b5c9856e6c0e42fc98e546192d1c534a59e3d1fa/acceptance-artifacts/Catalyst-Setup-f73a2bd-1.4.0.exe).
Independent HTTP downloads of both immutable URLs matched the recorded hashes.

## Original TEST 7 read-only live check

The previous exact `a471bd0` app shut down through its native UI with
cancel-all unchecked; its monitor recorded 36 clean stopped-profile samples,
then a process-exit and end record. The exact `f73a2bd` EXE was started through
the native UI. Testing Risk Disclosure was acknowledged under the operator's
standing authorization, Sage TEST 7 fingerprint `736588221` was selected,
Splash was skipped, and the existing Spacescan key remained configured after
using the free-tier startup path. MZ/XCH was selected. No settings were saved,
and the bot was not started.

The sole `Catalyst.exe` at the live checkpoint was PID `160304`, from the exact
EXE path and hash above, and it owned the sole `127.0.0.1:5000` listener.
Read-only API state showed Sage mainnet, fingerprint `736588221`, CAT wallet
ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, balances `138.470301476875` XCH and `780212.284` MZ,
stopped bot, inactive Bootstrap, zero open offers, and safety allowed with an
owned renewing lease. The native UI displayed TEST 7/MZ and showed the global
banner changing to **Bootstrap selected** after selecting Bootstrap and back
to **Follow mode** after restoring Follow, without navigation or saving.

One read-only `/api/fees/status` request timed out at a 10-second client limit
while the full Windows suite and packaging work were running. A single retry
completed in 179 ms. The concurrent safety monitor retained an allowed,
owned lease; the latency event remains a watch item during the 24-hour window.

The exact-PID/hash stopped-profile monitor is
`E:\catalyst-stability-monitor-f73a2bd\monitor.ps1` (SHA-256
`78A8DCEA93EFAD41368AA7427E41021F41A8324DC18B25B078A0FB0A1AD7B1BC`).
Its first safety-allowed sample was at `2026-10-06T00:29:16.324513Z`. The
24-hour gate is **not complete**; evaluate the entire trace and end state no
earlier than `2026-10-07T00:29:16Z`. This is a stopped-profile window, not a
live trading window.

The old campaign remains stopped and its older fee approval must not be reused.
No new campaign or fee approval exists. Live offer lifecycle and recovery,
primary and secondary full 24-hour windows, original-profile secondary live
acceptance, and final review remain open. PR #220 remains draft; no merge, tag,
release or public-readiness claim is supported.
