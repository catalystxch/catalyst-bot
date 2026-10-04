# Signing preflight fail-closed correction and exact b78ce49 package

Draft PR #220 exact source/runtime commit:
`b78ce495b17772b4586dc4afefca2229c4bc466f`.

## Reproduced defects and correction

`BotLoop.start()` previously continued toward a running trading loop after
either the complete Doctor preflight threw or its fallback Sage key lookup
threw. A focused test reached the trading-start boundary in both cases before
the correction. Both exceptions now set the bot to `blocked` and return
before the watcher and trading threads start. Doctor also reports a Sage
signing-check exception as `fail`, making `can_start` false. These paths use
bounded messages without exception text.

The secondary PC independently found that `config._safe_url()` included the
parsed scheme from a malformed configured URL in the startup log. The
regression reproduced disclosure of a `private-token` scheme before the fix.
The warning now names only the setting and the invalid URL scheme category;
the configured value is omitted. Both red/green regressions and the adjacent
Doctor/config suite passed **82 tests**. The full local Windows backend suite
passed **7,185 tests, 212 skipped and 431 subtests** in 566.57 seconds with
four workers. Ruff check, format and `git diff --check` passed. All **11 PR
checks** passed on the exact source commit. The bundled frontend is unchanged
from `61a18d6`, whose complete Chromium suite passed 211 tests.

## Detached Windows package

The detached build checkout was `E:\catalyst-startup-b78ce49-build` at the
exact source commit before `python build.py`.

| Artifact | SHA-256 |
| --- | --- |
| `dist/Catalyst/Catalyst.exe` | `A2EE395EDD88461407B6E5269F7A0B14DA9F1B9B68126A433FDF8DACE7FDB2F8` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-b78ce49-primary-acceptance.zip` | `BFA996AA4BA3793C01DC5B992B5B114922B8ABF18228BCA2DB6D92D29B17B6C6` |
| Unsigned `Catalyst-Setup-b78ce49-1.4.0.exe` | `A9F7F8AA233C8C4A5E2E8D45D014088EEEB375F8AF620B28175FE4764968F02F` |

The 192-file ZIP passed CRC. Packaged API, synthetic Sage RPC, and
interrupted-publication recovery smokes passed. A unique-AppId current-user
QA installer installed to `E:\catalyst-startup-b78ce49-qa-install`; installed
EXE hash and packaged API matched. The QA uninstaller exited zero and left
neither the installed EXE nor its registration. Defender custom scans of the
bundle, ZIP, and public unsigned installer reported zero matching detections.

Both files are pinned at artifact commit
`5d396c1c9e469805b13120adfe7321518c2de03b`; independent HTTP downloads
matched their hashes:

- [Acceptance ZIP](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5d396c1c9e469805b13120adfe7321518c2de03b/acceptance-artifacts/CATalyst-b78ce49-primary-acceptance.zip)
- [Unsigned installer](https://raw.githubusercontent.com/catalystxch/catalyst-bot/5d396c1c9e469805b13120adfe7321518c2de03b/acceptance-artifacts/Catalyst-Setup-b78ce49-1.4.0.exe)

The secondary PC independently reviewed the exact source and ran 103 focused
tests with four subtests, Ruff and format. It independently matched the ZIP,
installer, EXE and UI hashes, verified isolated packaged startup, Doctor's
bounded messages with injected secret-bearing malformed URLs, duplicate exit,
and graceful shutdown. The isolated DB had zero offers, campaigns, Coin Prep
operations, approvals, journals, or effect claims. Its original wallet profile
was untouched. This closes the delegated read-only package gate, not the
secondary live lifecycle.

## Original TEST 7 read-only restart

The stopped `eb8df03` process was checked as the sole prior app, with zero
open offers, unchanged balances, and ALLOWED safety. It shut down through its
visible browser UI with offer cancellation unchecked; process and port 5000
listener both exited. The exact `b78ce49` EXE started against the original
profile. At the checkpoint it was the sole `Catalyst.exe` process and sole
127.0.0.1:5000 listener owner (PID `83412`); path and hash matched the table.
PID must be rediscovered before future action.

Visible browser startup acknowledged Risk Disclosure under the operator's
existing testing authorization, selected Sage mainnet TEST 7 fingerprint
`736588221`, skipped the stopped optional Splash node, continued with the
configured Spacescan key, and selected MZ/XCH. The live read-only status
showed CAT wallet ID `2`, exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
stopped bot, 138.470301476875 XCH, 780212.284 MZ, zero open offers,
synced wallet, ALLOWED safety, and zero blockers. On-demand Doctor reported
nine passes and one expected warning for stopped Splash; signing capability
passed and the Splash message was only `Splash unreachable`. After closing
the browser, the process/hash/port, stopped bot, balances, zero open offers
and ALLOWED safety remained unchanged. No new campaign, fee approval,
offer, or wallet transaction was made.

Full native UI, both exact-candidate live wallet lifecycles, both 24-hour
windows, and final review remain open. PR #220 stays draft; no main merge,
tag, release, or public-readiness claim.

## Original TEST 7 native desktop UI traversal

The exact `b78ce49` process was rediscovered as PID `83412`; its executable
path, SHA-256, and exclusive port 5000 ownership matched the package above
before each native-window interaction. The app's own PyWebView window was
used. Under the operator's existing testing authorization, the native Risk
Disclosure was acknowledged. Native startup continued through Sage, skipped
the optional stopped Splash node, and used the configured Spacescan key. It
reached Dashboard with a stopped bot and no active Bootstrap campaign.

Read-only native navigation rendered Dashboard, Offers, P&L & Inventory,
Market Intelligence, Settings, Logs, Data Reset, Help, and About. Offers
showed no active offers; P&L showed no current fills; Settings displayed
fingerprint `736588221`; Logs showed Sage login and selection of Monkeyzoo
Token, wallet `2`; Market Intelligence showed Dexie ready, Splash
unavailable, Spacescan enabled, and Sage ready. Data Reset was viewed but no
reset button was pressed. Help and About modals opened and closed. The
native window was returned to Dashboard. This closes the exact-candidate
native read-only UI traversal gate. No campaign, fee approval, offer, wallet
transaction, or data reset was made.

An independent read-only API check after traversal showed the exact MZ asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
138.470301476875 XCH and 780212.284 MZ, stopped bot, zero open offers,
inactive Bootstrap, ALLOWED safety, and zero blockers. The optional Splash
node remained stopped. Live offer lifecycle, both 24-hour windows, and final
review remain open.

## Exact-package duplicate launch and same-build native restart

With the original TEST 7 bot stopped, sole PID `83412`, exact EXE path/hash,
one port 5000 owner, unchanged balances and zero open offers, the same EXE
was launched a second time. The duplicate PID `48912` exited within the
bounded wait. PID `83412` remained the only `Catalyst.exe` and port owner;
the bot stayed stopped, TEST 7 fingerprint `736588221` and MZ wallet `2`
remained selected, balances were unchanged, Bootstrap remained inactive,
and runtime safety remained ALLOWED with zero blockers.

The original app then shut down through its native Shutdown dialog with
"Cancel all offers before shutdown" left unchecked. The port listener
exited first and the process then exited; both counts reached zero. The
same hash-verified EXE restarted as sole PID `115676` and sole port 5000
owner. Its native startup showed Risk Disclosure, Sage wallet selection,
optional stopped Splash, and configured Spacescan. Risk Disclosure was
acknowledged under existing testing authorization. The native picker
displayed TEST 7 fingerprint `736588221` and it was selected. Sage reached
`ready` with that fingerprint; optional Splash was skipped; configured
Spacescan continued to Dashboard.

As designed for a stopped fresh session, the Dashboard initially required
an explicit trading-pair choice. While it was unselected, `/api/status`
withheld balances as zero despite retaining the configured MZ identity.
The exact Monkeyzoo Token `MZ_XCH` option was selected in the native UI;
the original 138.470301476875 XCH and 780212.284 MZ balances then
returned. A read-only post-selection check found exact asset
`b8edcc6a7cf3738a3806fdbadb1bbcfc2540ec37f6732ab3a6a4bbcd2dbec105`,
wallet ID `2`, fingerprint `736588221`, stopped bot, zero open offers,
inactive Bootstrap, and ALLOWED safety with zero blockers. No fee approval,
offer, wallet transaction, or reset was made. This covers stopped-profile
same-build restart and duplicate ownership; active-offer recovery remains
unverified.

## Exact-source opt-in Chromium rerun

An additional opt-in Chromium run against source `b78ce49` initially found
two failures in Coin Prep fee-approval tests. The tests replaced the global
`apiFetch` after `DOMContentLoaded` and then counted unrelated asynchronous
startup polling as the last wallet-verification call or an attempted Coin
Prep approval. No product call was implicated. Test-only child
`eb1f1f5d9b9b8980cff4dcb9e637dbf07b447ee9` records and asserts only
Coin Prep requests while providing a benign response to background polls.
The focused Coin Prep browser file passed 41 tests; the complete opt-in
Chromium suite passed **211 tests** on the exact `b78ce49` runtime source
with that test-only child. Ruff check/format and diff checks passed. Package
and live runtime identities above remain attributable to `b78ce49`.
