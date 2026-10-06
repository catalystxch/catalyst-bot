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

## Exact-package read-only diagnostics, 00:45 UTC

The sole port-5000 owner was still PID `160304`, with the exact executable SHA-256
above. A read-only `/api/doctor` request reported `can_start=true`: nine checks
passed, TibetSwap was skipped as a retired provider, and Splash was unreachable.
The passes covered database, config, CAT identity and wallet mapping, Sage RPC,
Sage sync and signing, Dexie, and Spacescan configuration. The read-only
`/api/health/runtime` request reported `healthy=true`, zero repairs, and zero
pending cancellation journals, orphan coin locks, stale Dexie posts, ladder
overbuild, top-up budget drift, funds-floor issues, or unallocated deposits.
Its two warnings were the unavailable Splash metrics endpoint and a missing or
expired Spacescan cache for this asset. Neither request started the bot or
changed offers. These warnings remain observable diagnostics; the 24-hour
monitor and live trading gates are still pending.

## Packaged live browser traversal, 00:47–00:50 UTC

A separate Chromium session opened the packaged app served by the exact f73
process at `127.0.0.1:5000`. Read-only navigation loaded Dashboard, Offers
(active and history), P&L, Market Intel, Settings (Setup and Live tabs), Logs,
Data Reset, Help, and About. The Offers screen showed zero active offers and
three historical confirmed fills; Market Intel showed Dexie and Sage ready,
Splash unavailable, and Spacescan enabled. Data Reset displayed its three
confirmation-gated controls; none was activated. Help and About opened and
closed. Chromium reported zero console errors and zero warnings. The separate
browser session did not select a CAT pair locally, so its pair-specific setup
panels are not evidence of the native window's already selected MZ state.

The browser session was closed. A subsequent exact PID/path/hash check found
the same sole app; `/api/health` still reported a stopped, synced wallet,
`/api/offers/open_count` was zero, Bootstrap inactive, and safety allowed with
an owned lease. `/api/bootstrap/status` still identified Sage mainnet,
fingerprint `736588221`, CAT wallet ID `2` and the exact MZ asset. No Save,
Reset, bot, campaign, or wallet action was taken. This advances packaged
browser-screen acceptance but does not replace live lifecycle or 24-hour gates.

## Minimum-window keyboard and modal check, 01:00 UTC

A separate read-only Chromium session used the packaged app at the native main
window's declared minimum `1000×700` (`desktop_app.py` sets
`WINDOW_MIN_WIDTH=1000`, `WINDOW_MIN_HEIGHT=700`). The Dashboard startup card,
pair selector, status banner and sidebar remained readable without clipped
text in the captured viewport. Sequential Tab navigation gave the Dashboard,
Offers, P&L, Market Intel, Settings and Logs buttons accessible names and a
visible solid focus outline. Opening Help moved focus to its Close help button
inside an `aria-modal` dialog; Escape closed it and returned focus to Help.
Chromium reported zero console errors or warnings. A `500×600` browser-only
viewport clipped Quick Start text horizontally; it is below the native
window's supported minimum and is not counted as native desktop acceptance.
No settings, campaign, wallet or reset action was taken.

## Independent secondary original-profile read-only check

The secondary PC independently built exact source `f73a2bd` into an EXE with
SHA-256 `9E2A80B35849550BA3C517E801F9D02D57C767B5D399AEB1CD59C34DD92E29AB`.
It selected Sage mainnet Harvestr fingerprint `3702373391`, CAT wallet ID `2`
and the exact MZ asset through rendered Chromium startup controls after the
testing Risk Disclosure; native computer control was unavailable on that host.
The original-profile read-only UI traversal covered Dashboard, Offers, P&L,
Market Intel, Settings Live and Setup, Logs, Doctor, Data Reset confirmation
gates (all cancelled), Help and About. It observed zero console errors or
warnings, page errors or failed requests. Doctor passed its preflight with
eight passes and two external configuration warnings: Splash unreachable and
Spacescan API key empty. The bot remained stopped, offers and pending effects
remained zero, safety stayed allowed with an owned renewing lease, and the
secondary exact-candidate 24-hour monitor began. The secondary report is
`2026-10-06-f73a2bd-original-profile-readonly.md`, SHA-256
`C9945E9901B9FFB3DE0C46AF40BE340C28F42C5978946B9EAB7867A2AA9BEDAE`,
on the secondary PC. Its live trading lifecycle and full 24-hour result remain
open; this report does not claim native mouse-driven acceptance on that host.
