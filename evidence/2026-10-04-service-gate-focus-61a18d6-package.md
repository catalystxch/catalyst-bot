# Service gate keyboard focus and exact 61a18d6 package

Draft PR #220 source commit: `61a18d661e1e38a24dc0b5893e59d0f53d12e03d`.

## Defect and correction

The existing startup Risk Disclosure trapped Tab inside its visible controls,
but the subsequent Splash and Spacescan setup gates did not. Two new browser
regressions first failed when Tab from each gate's last control reached a
control outside the gate. The corrected handler selects the visible startup
or service gate and wraps Tab and Shift+Tab within its currently visible
controls, including Spacescan accordion summaries. The regressions also
check that focus forced onto the background Dashboard returns to the gate.
The prior Risk Disclosure and wallet-choice focus checks still pass. The
complete Chromium suite passed **211 tests** in 139.25 seconds. Ruff check,
Ruff format and `git diff --check` passed. The backend source is unchanged
from `a3b299c`, whose local Windows run passed 7,177 tests, 210 skipped and
427 subtests. All 11 PR checks passed on exact source `61a18d6`, including
`unit-tests`.

## Clean Windows package

A clean detached build at `E:\catalyst-service-gate-61a-build` was checked
out at the exact source commit before packaging:

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `909E569FA59D077E594757E64B5CC6F3D47DD9CE67369EF6870DADD8A8BF274D` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-61a18d6-primary-acceptance.zip` | `631BB97054378353C5279CB5C03E393A0BA53188303749115A09D79AA92CC1F0` |
| Unsigned `Catalyst-Setup-61a18d6-1.4.0.exe` | `8E6C8320EBAF5AD190443896F7F2008B7FB694ACEEE05B596F277A411A4DB499` |

The 192-entry ZIP passed CRC and its extracted EXE passed the packaged API
smoke. The original bundle passed packaged API, synthetic Sage RPC,
upgrade-interrupted publication recovery, and clean, duplicate, persisted
and native-safety desktop launches. A unique-AppId current-user QA installer
used a separate `E:\catalyst-service-gate-61a-qa-install` directory. Clean
install, installed EXE hash equality, installed API and synthetic Sage,
same-version in-place reinstall, and uninstall passed. The isolated directory
and both QA registry scopes were absent afterward. Defender custom scans of
the bundle, ZIP and public installer returned no matching detections.

A separate unique-AppId `CATalyst Acceptance QA` sequence used AppId
`{C51E254D-F8E9-4DA7-8347-41AC68A57B16}` and the explicitly verified
`E:\catalyst-service-gate-61a-upgrade-qa-install` path. The prior `a3b299c`
package installed with EXE hash
`F9E02BF9111937E292A2FF12E92F4A38448CC3209F678F13806E6965B4F69617`.
An in-place same-version upgrade changed the installed hash to the exact
`61a18d6` value above; rollback restored the prior hash, and reinstall
restored the exact new hash. All four installer runs exited zero. The QA
uninstaller exited zero, and its directory and unique HKCU registration were
absent afterward. The original TEST 7 process retained its exact source path
and PID 33880 throughout. The first isolated QA install accidentally used
the default current-user QA path because `/DIR` was not passed as a distinct
argument; its unique registration and directory were verified and fully
uninstalled before the corrected sequence. No production registration or
original profile was changed by this QA sequence.

The ZIP and unsigned installer are pinned at artifact commit `71c5ae9`.
Independent HTTP downloads of both pinned files matched the local SHA-256
values above:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/71c5ae9/acceptance-artifacts/CATalyst-61a18d6-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/71c5ae9/acceptance-artifacts/Catalyst-Setup-61a18d6-1.4.0.exe)

## Original TEST 7 read-only startup

The stopped `a3b299c` app was shut down through its visible UI with offer
cancellation unchecked. Its process and port 5000 listener exited. Exact
`61a18d6` then launched against the original profile. At the read-only
checkpoint, its sole `Catalyst.exe` process was PID 33880 and owned the sole
127.0.0.1:5000 listener; the executable path and hash matched the clean
package above. PID is observational and must be rediscovered for later work.

The native desktop displayed Risk Disclosure, but the available computer-use
clicks or Tab input did not activate its Continue control, even after explicit
window activation. The same exact app was opened in
a browser, where the operator-authorized disclosure was acknowledged through
the visible UI. TEST 7 fingerprint `736588221` was selected in the visible
Sage chooser, then the optional Splash and Spacescan gates were completed in
the visible UI. This is browser UI startup acceptance; native control of the
disclosure and subsequent native traversal remain unverified.

The browser selected the MZ/XCH pair. The app reported mainnet Sage fingerprint
`736588221`, CAT wallet ID `2`, asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
synced wallet, stopped bot, XCH `138.470301476875`, MZ `780212.284`, zero
open offers, no active Bootstrap campaign, and safety ALLOWED with zero
blockers. Direct read-only Sage RPC returned no pending transactions and all
4,095 historical offers terminal (3,326 CANCELLED, 538 COMPLETED, 231 EXPIRED).
The Sage `/get_offers` endpoint returned the complete history despite supplied
page bounds; this check used one complete response, not repeated pagination.

No campaign, fee approval, offer, or wallet transaction was created. The full
native UI, live wallet lifecycle, both 24-hour windows, independent secondary
acceptance and final review remain open. Keep PR #220 draft; no main merge,
tag, release or public-readiness claim.

## Secondary-PC read-only package gate

The existing secondary Codex task reported a PASS for an independent
read-only `61a18d6` gate on 2026-10-04. It fetched the PR evidence head
`4dcb04e`, verified that only documentation and evidence differ from exact
source `61a18d6`, and passed the enabled public-readiness Chromium module
(10 tests in 12.37 seconds). Independent downloads matched the ZIP, installer,
embedded EXE and bundled UI hashes in this report. The ZIP had 192 entries,
passed inspection, and contained no `.env` or `bot.db`.

The secondary launched the exact EXE with a new isolated `CMM_DATA_DIR`, not
its original Harvestr profile. It observed one native window and one port 5000
owner, HTTP 200, a stopped bot, and the expected fail-closed
`WALLET_IDENTITY_SETUP_REQUIRED` / `WALLET_IDENTITY_BINDING_INVALID` first-run
state. A duplicate exited cleanly while the owner remained; the owner then
closed gracefully. The isolated DB contained zero offers, campaigns, Coin
Prep operations, approvals, journals and wallet-effect claims. The original
Harvestr profile was untouched and no wallet action occurred. The secondary
computer-control kernel remained unavailable, so native Risk Disclosure
traversal and installer interaction were not performed. Its local report is
`C:\Users\M920q\Documents\Codex\2026-09-14\catalyst-v1-4-0-secondary-pc\evidence\2026-10-04-pr220-secondary-61a18d6.md`.

This passes the secondary isolated read-only package gate only. Secondary
original-profile live lifecycle, complete UI and 24-hour window remain open.
