# CATalyst 61a18d6 primary acceptance package

Draft PR #220 exact source: `61a18d661e1e38a24dc0b5893e59d0f53d12e03d`.
This unsigned package is for acceptance testing. It is not a release or a
public-readiness claim.

| Artifact | SHA-256 |
| --- | --- |
| Clean detached `Catalyst.exe` | `909E569FA59D077E594757E64B5CC6F3D47DD9CE67369EF6870DADD8A8BF274D` |
| Bundled `_internal/bot_gui.html` | `6E6E7F69BFD65B3A03C3706A117EEBBF3681C3ACC74F26520CC1003B677A1CBD` |
| `CATalyst-61a18d6-primary-acceptance.zip` | `631BB97054378353C5279CB5C03E393A0BA53188303749115A09D79AA92CC1F0` |
| `Catalyst-Setup-61a18d6-1.4.0.exe` | `8E6C8320EBAF5AD190443896F7F2008B7FB694ACEEE05B596F277A411A4DB499` |

The source traps keyboard focus inside the Splash and Spacescan setup gates.
Two browser regressions failed before the correction and passed afterward;
the full Chromium suite passed 211 tests. The 192-entry ZIP passed CRC and
extracted API. The bundle passed packaged API, synthetic Sage RPC,
publication recovery, and native clean, duplicate, persisted and safety
smokes. A unique-AppId current-user QA installer passed clean install,
installed EXE hash/API/Sage, same-version reinstall and uninstall. A second
unique-AppId QA install passed prior `a3b299c` install, in-place upgrade to
`61a18d6`, rollback, restore and uninstall, with installed EXE hashes matched
at every step. Both QA directories and registrations were absent afterward.
The original TEST 7 process remained untouched. Defender custom scans
reported no matching detections. Independent HTTP downloads of the pinned
ZIP and installer matched the table hashes. All 11 exact-source PR checks
passed, including `unit-tests`.

The stopped `a3b299c` process exited through the visible shutdown UI. The
exact `61a18d6` EXE then started against the original TEST 7 profile as the
sole port 5000 owner; its process path and SHA-256 matched this package.
Browser UI startup acknowledged Risk Disclosure under the operator's testing
authorization, selected Sage fingerprint `736588221`, and completed optional
Splash and Spacescan gates. The native window displayed Risk Disclosure, but
computer-use clicks or Tab input did not activate its Continue control, so
full native UI acceptance remains open. The browser selected MZ/XCH and read-only checks
found mainnet, CAT wallet ID `2`, the exact MZ asset, synced wallet, stopped
bot, XCH `138.470301476875`, MZ `780212.284`, zero open offers and pending
transactions, inactive campaign, and ALLOWED safety. Sage's 4,095 historical
offers were all terminal. No wallet financial effect was made. Live wallet
lifecycle, complete native UI, both 24-hour windows, independent secondary
acceptance and final review remain open. PR #220 stays draft.

The secondary PC reported independent matching ZIP, installer, EXE and UI
hashes, 10 passed public-readiness browser tests, and an exact isolated-profile
package launch with identity-unbound safety denial, clean duplicate exit and
graceful shutdown. Its original Harvestr profile remained untouched and no
wallet effect occurred. Secondary full native UI, original-profile live
lifecycle and 24-hour acceptance remain open.
